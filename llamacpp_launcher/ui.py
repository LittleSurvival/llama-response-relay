from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .command import probe_help
from .dashboard_widgets import CompactChart
from .discovery import discover_models, resolve_llama_server
from .glossaries import GlossaryService
from .models import (
    PROFILE_NAME_PATTERN,
    AppSettings,
    FlashAttention,
    Glossary,
    GlossaryEntry,
    GpuMode,
    Profile,
    ValidationError,
)
from .process import RuntimeEvent, RuntimeState
from .profiles import ProfileService
from .runtime import LauncherRuntime
from .storage import SettingsStore
from .telemetry import (
    Availability,
    DashboardSnapshot,
    format_count,
    format_duration,
    format_ms,
    format_percent,
    format_rate,
)
from .theme import AfterAnimator, PALETTE, STATUS_COLORS, blend_color


ctk.set_appearance_mode("light")


def _chart_state(state: Availability, stopped: bool) -> str:
    return "Stopped" if stopped else state.value


def control_states(
    state: RuntimeState, has_profile: bool, process_active: bool | None = None
) -> dict[str, bool]:
    active = process_active if process_active is not None else state in {
        RuntimeState.STARTING,
        RuntimeState.READY,
        RuntimeState.STOPPING,
        RuntimeState.FAILED,
    }
    return {
        "start": has_profile and not active,
        "stop": active and state is not RuntimeState.STOPPING,
        "restart": active and state is not RuntimeState.STOPPING,
        "edit": not active,
    }


def validate_profile_name(
    value: str, existing_names: list[str], *, current_name: str = ""
) -> str:
    name = value.strip()
    if not name:
        raise ValidationError("Profile name is required.")
    if len(name) > 80 or not PROFILE_NAME_PATTERN.fullmatch(name):
        raise ValidationError("Profile name contains unsupported characters or is too long.")
    current_key = current_name.casefold()
    if any(
        candidate.casefold() == name.casefold()
        and candidate.casefold() != current_key
        for candidate in existing_names
    ):
        raise ValidationError(f'Profile name "{name}" is already in use.')
    return name


def suggest_profile_name(existing_names: list[str]) -> str:
    names = {name.casefold() for name in existing_names}
    base = "New profile"
    if base.casefold() not in names:
        return base
    suffix = 2
    while f"{base} {suffix}".casefold() in names:
        suffix += 1
    return f"{base} {suffix}"


def context_per_slot_text(context_value: str, parallel_value: str) -> str:
    try:
        context_size = int(context_value)
        parallel_slots = int(parallel_value)
    except ValueError:
        return ""
    if context_size <= 0 or parallel_slots <= 1:
        return ""
    per_slot = context_size / parallel_slots
    if context_size % parallel_slots == 0:
        amount = f"{int(per_slot):,}"
    else:
        amount = f"~{per_slot:,.1f}"
    return f"Each slot gets {amount} context ({context_size:,} ÷ {parallel_slots})"


class ProfileNameDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        action_text: str,
        initial_value: str,
        existing_names: list[str],
        current_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.result: str | None = None
        self.existing_names = existing_names
        self.current_name = current_name

        self.title(title)
        self.geometry("440x270")
        self.resizable(False, False)
        self.configure(fg_color=PALETTE["window"])
        self.transient(parent)
        self.grab_set()

        panel = ctk.CTkFrame(
            self, fg_color=PALETTE["surface"], corner_radius=20, border_width=1,
            border_color=PALETTE["border"]
        )
        panel.pack(fill="both", expand=True, padx=24, pady=24)
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            panel,
            text=title,
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 22, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 4))
        ctk.CTkLabel(
            panel,
            text="Give this configuration a name you can recognize later.",
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 12),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=24)

        self.name_var = tk.StringVar(value=initial_value)
        self.entry = ctk.CTkEntry(
            panel,
            textvariable=self.name_var,
            height=44,
            corner_radius=12,
            border_color=PALETTE["border"],
            fg_color=PALETTE["surface"],
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 13),
        )
        self.entry.grid(row=2, column=0, sticky="ew", padx=24, pady=(18, 6))
        self.error_label = ctk.CTkLabel(
            panel,
            text="",
            text_color=PALETTE["error"],
            font=ctk.CTkFont("Segoe UI", 11),
            anchor="w",
        )
        self.error_label.grid(row=3, column=0, sticky="ew", padx=24)

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="e", padx=24, pady=(12, 20))
        ctk.CTkButton(
            actions,
            text="Cancel",
            width=96,
            height=38,
            corner_radius=11,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["accent_soft"],
            text_color=PALETTE["text"],
            command=self._cancel,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text=action_text,
            width=118,
            height=38,
            corner_radius=11,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            command=self._confirm,
        ).pack(side="left")

        self.bind("<Return>", lambda _event: self._confirm())
        self.bind("<Escape>", lambda _event: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(60, self._focus_entry)
        self.after(70, self._center)

    def _focus_entry(self) -> None:
        self.entry.focus_set()
        self.entry.select_range(0, "end")

    def _center(self) -> None:
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _confirm(self) -> None:
        try:
            self.result = validate_profile_name(
                self.name_var.get(),
                self.existing_names,
                current_name=self.current_name,
            )
        except ValidationError as exc:
            self.error_label.configure(text=str(exc))
            self.entry.configure(border_color=PALETTE["error"])
            return
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()


class LauncherApp:
    POLL_MS = 100

    def __init__(
        self,
        root: tk.Misc,
        *,
        store: SettingsStore | None = None,
        manager: LauncherRuntime | None = None,
    ) -> None:
        self.root = root
        self.store = store or SettingsStore()
        self.manager = manager or LauncherRuntime()
        self.ui_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.load_error = ""
        try:
            self.settings = self.store.load()
        except ValidationError as exc:
            self.settings = self.store.last_valid
            self.load_error = str(exc)
        self.profiles = ProfileService(self.settings)
        self.glossaries = GlossaryService(self.settings)
        self.original_profile_name = ""
        self.original_glossary_id = ""
        self.glossary_rows: list[dict[str, object]] = []
        self.model_paths: dict[str, Path] = {}
        self._closing = False
        self._current_view = "Settings"
        self._view_animator = AfterAnimator(root)
        self._status_animator = AfterAnimator(root)
        self._status_bg = PALETTE["surface_alt"]
        self._status_fg = PALETTE["muted"]
        self._last_dashboard_tick = 0.0
        self.profile_buttons: list[ctk.CTkButton] = []
        self.editor_widgets: list[tuple[tk.Widget, str]] = []
        self.glossary_widgets: list[tuple[tk.Widget, str]] = []

        self._configure_root()
        self._create_variables()
        self._build_ui()
        self._refresh_glossary_choices(select=self.settings.selected_glossary_id)
        self._refresh_profile_choices(select=self.settings.selected_profile)
        self._refresh_models(show_errors=False)
        initial_profile = self.profile_choice_var.get()
        if initial_profile:
            self.profiles.select(initial_profile)
            self._load_profile(initial_profile)
        else:
            self._new_profile(prompt=False)
        if self.load_error:
            self._show_error(self.load_error)
        self.root.protocol("WM_DELETE_WINDOW", self._request_close)
        self.root.after(self.POLL_MS, self._poll_events)

    def _configure_root(self) -> None:
        self.root.title("Llama.cpp Launcher")
        width = min(1280, self.root.winfo_screenwidth() - 72)
        height = min(840, self.root.winfo_screenheight() - 104)
        x = max(24, (self.root.winfo_screenwidth() - width) // 2)
        y = max(24, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(960, 640)
        self.root.configure(background=PALETTE["window"])

    def _create_variables(self) -> None:
        self.llama_folder_var = tk.StringVar(value=self.settings.llama_cpp_folder)
        self.model_folder_var = tk.StringVar(value=self.settings.model_folder)
        self.profile_choice_var = tk.StringVar(value=self.settings.selected_profile)
        self.name_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="8080")
        self.ngl_var = tk.StringVar(value="0")
        self.context_var = tk.StringVar(value="4096")
        self.parallel_var = tk.StringVar(value="1")
        self.context_allocation_var = tk.StringVar()
        self.context_var.trace_add("write", self._update_context_allocation)
        self.parallel_var.trace_add("write", self._update_context_allocation)
        self.flash_var = tk.StringVar(value=FlashAttention.AUTO.value)
        self.no_mmap_var = tk.BooleanVar(value=False)
        self.gpu_var = tk.StringVar(value=GpuMode.AUTO.value)
        self.status_var = tk.StringVar(value=RuntimeState.STOPPED.value)
        self.detail_var = tk.StringVar(value="Choose source folders and create a profile.")
        self.error_var = tk.StringVar()
        self.interceptor_enabled_var = tk.BooleanVar(
            value=self.settings.interceptor_enabled
        )
        self.interceptor_host_var = tk.StringVar(value=self.settings.interceptor_host)
        self.interceptor_port_var = tk.StringVar(value=str(self.settings.interceptor_port))
        self.glossary_choice_var = tk.StringVar()
        self.glossary_name_var = tk.StringVar(value="No glossary selected")
        self.glossary_error_var = tk.StringVar()
        self.upstream_endpoint_var = tk.StringVar(value="Upstream: —")
        self.client_endpoint_var = tk.StringVar(
            value=(
                f"Client endpoint: http://{self.settings.interceptor_host}:"
                f"{self.settings.interceptor_port}"
            )
        )
        self.runtime_identity_var = tk.StringVar(value="No active profile · 00:00")
        self.telemetry_health_var = tk.StringVar(value="Telemetry unavailable")
        self.token_rate_var = tk.StringVar(value="—")
        self.token_rate_hint_var = tk.StringVar(value="avg —")
        self.slot_pressure_var = tk.StringVar(value="—")
        self.slot_pressure_hint_var = tk.StringVar(value="0 configured")
        self.queue_var = tk.StringVar(value="—")
        self.queue_hint_var = tk.StringVar(value="deferred requests")
        self.session_tokens_var = tk.StringVar(value="In — · Out —")
        self.session_tokens_hint_var = tk.StringVar(value="current process")
        self.latest_task_var = tk.StringVar(value="Latest client task: Unavailable")

    def _build_ui(self) -> None:
        shell = ctk.CTkFrame(self.root, fg_color=PALETTE["window"], corner_radius=0)
        shell.pack(fill="both", expand=True)
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(1, weight=1)
        self._build_sidebar(shell)

        main = ctk.CTkFrame(shell, fg_color=PALETTE["window"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew", padx=(28, 32), pady=(24, 26))
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)
        self._build_header(main)

        self.view_host = ctk.CTkFrame(main, fg_color="transparent", corner_radius=0)
        self.view_host.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        self.settings_view = self._build_settings_view(self.view_host)
        self.glossaries_view = self._build_glossaries_view(self.view_host)
        self.runtime_view = self._build_runtime_view(self.view_host)
        self.settings_view.place(x=0, y=0, relwidth=1, relheight=1)
        self.glossaries_view.place_forget()
        self.runtime_view.place_forget()
        self.settings_view.lift()

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        sidebar = ctk.CTkFrame(
            parent,
            width=268,
            corner_radius=0,
            fg_color=PALETTE["rail"],
            border_width=0,
        )
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(3, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        mark = ctk.CTkFrame(
            sidebar, width=42, height=42, corner_radius=13, fg_color=PALETTE["accent"]
        )
        mark.grid(row=0, column=0, sticky="w", padx=22, pady=(24, 12))
        mark.grid_propagate(False)
        ctk.CTkLabel(
            mark,
            text="L",
            text_color="#FFFFFF",
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(
            sidebar,
            text="Llama Launcher",
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 19, "bold"),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=22)
        ctk.CTkLabel(
            sidebar,
            text="YOUR PROFILES",
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=22, pady=(28, 8))

        self.profile_list = ctk.CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
            scrollbar_button_color=PALETTE["accent_soft"],
            scrollbar_button_hover_color=PALETTE["accent"],
        )
        self.profile_list.grid(row=3, column=0, sticky="nsew", padx=(10, 6))
        self.profile_list.grid_columnconfigure(0, weight=1)

        self.new_profile_button = ctk.CTkButton(
            sidebar,
            text="+  New profile",
            height=44,
            corner_radius=13,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            command=lambda: self._new_profile(prompt=True),
        )
        self.new_profile_button.grid(row=4, column=0, sticky="ew", padx=18, pady=(12, 8))
        actions = ctk.CTkFrame(sidebar, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 20))
        actions.grid_columnconfigure((0, 1, 2), weight=1)
        self.rename_button = self._small_action(actions, "Rename", self._rename_profile)
        self.rename_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.duplicate_button = self._small_action(actions, "Copy", self._duplicate_profile)
        self.duplicate_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.delete_button = self._small_action(
            actions, "Delete", self._delete_profile, danger=True
        )
        self.delete_button.grid(row=0, column=2, sticky="ew", padx=(4, 0))

    def _small_action(
        self,
        parent: ctk.CTkFrame,
        text: str,
        command: object,
        *,
        danger: bool = False,
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            height=34,
            corner_radius=10,
            fg_color=PALETTE["error_soft"] if danger else PALETTE["surface"],
            hover_color="#F9CCD6" if danger else PALETTE["accent_soft"],
            text_color=PALETTE["error"] if danger else PALETTE["text"],
            border_width=1,
            border_color="#F2C8D1" if danger else PALETTE["border"],
            font=ctk.CTkFont("Segoe UI", 10),
            command=command,
        )

    def _build_header(self, parent: ctk.CTkFrame) -> None:
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            textvariable=self.name_var,
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 28, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            header,
            text="Configure and run llama.cpp without a console window",
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 12),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(3, 0))

        self.view_switch = ctk.CTkSegmentedButton(
            header,
            values=["Settings", "LRR", "Runtime"],
            command=self._switch_view,
            height=38,
            corner_radius=12,
            fg_color=PALETTE["surface_alt"],
            selected_color=PALETTE["accent"],
            selected_hover_color=PALETTE["accent_hover"],
            unselected_color=PALETTE["surface_alt"],
            unselected_hover_color=PALETTE["accent_soft"],
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        self.view_switch.grid(row=0, column=1, rowspan=2, padx=(20, 16))
        self.view_switch.set("Settings")
        self.status_label = ctk.CTkLabel(
            header,
            textvariable=self.status_var,
            width=102,
            height=36,
            corner_radius=18,
            fg_color=self._status_bg,
            text_color=self._status_fg,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        self.status_label.grid(row=0, column=2, rowspan=2)

    def _card(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str = "",
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=PALETTE["surface"],
            corner_radius=18,
            border_width=1,
            border_color=PALETTE["border"],
        )
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=title,
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=22, pady=(19, 2 if subtitle else 15))
        if subtitle:
            ctk.CTkLabel(
                card,
                text=subtitle,
                text_color=PALETTE["muted"],
                font=ctk.CTkFont("Segoe UI", 11),
                anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 14))
        return card

    def _build_settings_view(self, parent: tk.Misc) -> ctk.CTkFrame:
        view = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(
            view,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=PALETTE["accent_soft"],
            scrollbar_button_hover_color=PALETTE["accent"],
        )
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1, uniform="settings")

        sources = self._card(
            body, "Source folders", "Choose the llama.cpp build and your local GGUF library."
        )
        sources.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(0, 16))
        self._folder_field(
            sources,
            2,
            "llama.cpp folder",
            "Must contain llama-server.exe directly",
            self.llama_folder_var,
            self._choose_llama_folder,
        )
        self._folder_field(
            sources,
            3,
            "Model folder",
            "Reads .gguf files in this folder",
            self.model_folder_var,
            self._choose_model_folder,
            refresh=self._refresh_models,
        )
        endpoint = self._card(body, "Model & endpoint", "What to load and where to serve it.")
        endpoint.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        endpoint.grid_columnconfigure((0, 1), weight=1, uniform="endpoint")
        self._field_label(endpoint, 2, 0, "Model")
        self.model_combo = ctk.CTkComboBox(
            endpoint,
            variable=self.model_var,
            values=[],
            state="readonly",
            height=42,
            corner_radius=11,
            border_color=PALETTE["border"],
            button_color=PALETTE["accent_soft"],
            button_hover_color=PALETTE["accent"],
            text_color=PALETTE["text"],
            fg_color=PALETTE["surface"],
            dropdown_fg_color=PALETTE["surface"],
            dropdown_hover_color=PALETTE["accent_soft"],
        )
        self.model_combo.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 15))
        self.editor_widgets.append((self.model_combo, "readonly"))
        self._labeled_entry(endpoint, 4, 0, "Host", self.host_var)
        self._labeled_entry(endpoint, 4, 1, "Port", self.port_var)
        performance = self._card(
            body, "Performance", "Keep Auto unless you know your llama.cpp build."
        )
        performance.grid(row=1, column=1, sticky="nsew", padx=(8, 8), pady=(0, 16))
        performance.grid_columnconfigure((0, 1), weight=1, uniform="performance")
        self._labeled_entry(performance, 2, 0, "GPU layers  ·  -ngl", self.ngl_var)
        self._context_entry(performance)
        self._labeled_entry(performance, 4, 0, "Parallel  ·  -np", self.parallel_var)
        self._field_label(performance, 4, 1, "GPU mode")
        self.gpu_combo = self._combo(
            performance, self.gpu_var, [item.value for item in GpuMode]
        )
        self.gpu_combo.grid(row=5, column=1, sticky="ew", padx=(8, 22), pady=(0, 15))
        self._field_label(performance, 6, 0, "Flash attention  ·  -fa")
        self.flash_combo = self._combo(
            performance, self.flash_var, [item.value for item in FlashAttention]
        )
        self.flash_combo.grid(row=7, column=0, sticky="ew", padx=(22, 8), pady=(0, 20))
        self.no_mmap_check = ctk.CTkSwitch(
            performance,
            text="Disable mmap",
            variable=self.no_mmap_var,
            onvalue=True,
            offvalue=False,
            progress_color=PALETTE["accent"],
            button_hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 11),
        )
        self.no_mmap_check.grid(row=7, column=1, sticky="w", padx=(8, 22), pady=(0, 20))
        self.editor_widgets.append((self.no_mmap_check, "normal"))

        advanced = self._card(
            body, "Advanced arguments", "Extra llama-server arguments; managed options are rejected."
        )
        advanced.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(0, 16))
        advanced.grid_columnconfigure(0, weight=1)
        self.custom_text = ctk.CTkTextbox(
            advanced,
            height=92,
            corner_radius=12,
            border_width=1,
            border_color=PALETTE["border"],
            fg_color=PALETTE["surface_alt"],
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Cascadia Mono", 11),
            wrap="word",
        )
        self.custom_text.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 14))
        self.editor_widgets.append((self.custom_text, "normal"))

        footer = ctk.CTkFrame(advanced, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 20))
        footer.grid_columnconfigure(0, weight=1)
        self.error_label = ctk.CTkLabel(
            footer,
            textvariable=self.error_var,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 11),
            anchor="w",
            wraplength=620,
        )
        self.error_label.grid(row=0, column=0, sticky="ew", padx=(0, 16))
        self.save_button = ctk.CTkButton(
            footer,
            text="Save profile",
            width=154,
            height=42,
            corner_radius=12,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self._save_profile,
        )
        self.save_button.grid(row=0, column=1)
        return view

    def _context_entry(self, parent: tk.Misc) -> ctk.CTkEntry:
        heading = ctk.CTkFrame(parent, fg_color="transparent")
        heading.grid(row=2, column=1, sticky="ew", padx=(8, 22), pady=(0, 6))
        heading.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            heading,
            text="Context  ·  -c",
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        self.context_hint_label = ctk.CTkLabel(
            heading,
            textvariable=self.context_allocation_var,
            text_color=PALETTE["accent_hover"],
            font=ctk.CTkFont("Segoe UI", 9),
            anchor="w",
        )
        self.context_hint_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        entry = ctk.CTkEntry(
            parent,
            textvariable=self.context_var,
            height=42,
            corner_radius=11,
            border_color=PALETTE["border"],
            fg_color=PALETTE["surface"],
            text_color=PALETTE["text"],
        )
        entry.grid(row=3, column=1, sticky="ew", padx=(8, 22), pady=(0, 15))
        self.editor_widgets.append((entry, "normal"))
        self._update_context_allocation()
        return entry

    def _update_context_allocation(self, *_args: object) -> None:
        text = context_per_slot_text(self.context_var.get(), self.parallel_var.get())
        self.context_allocation_var.set(text)
        if not hasattr(self, "context_hint_label"):
            return
        if text:
            self.context_hint_label.grid()
        else:
            self.context_hint_label.grid_remove()

    def _field_label(self, parent: tk.Misc, row: int, column: int, text: str) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            anchor="w",
        ).grid(
            row=row,
            column=column,
            sticky="ew",
            padx=(22, 8) if column == 0 else (8, 22),
            pady=(0, 6),
        )

    def _labeled_entry(
        self,
        parent: tk.Misc,
        label_row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
    ) -> ctk.CTkEntry:
        self._field_label(parent, label_row, column, label)
        entry = ctk.CTkEntry(
            parent,
            textvariable=variable,
            height=42,
            corner_radius=11,
            border_color=PALETTE["border"],
            fg_color=PALETTE["surface"],
            text_color=PALETTE["text"],
        )
        entry.grid(
            row=label_row + 1,
            column=column,
            sticky="ew",
            padx=(22, 8) if column == 0 else (8, 22),
            pady=(0, 15),
        )
        self.editor_widgets.append((entry, "normal"))
        return entry

    def _combo(
        self, parent: tk.Misc, variable: tk.StringVar, values: list[str]
    ) -> ctk.CTkComboBox:
        combo = ctk.CTkComboBox(
            parent,
            variable=variable,
            values=values,
            state="readonly",
            height=42,
            corner_radius=11,
            border_color=PALETTE["border"],
            button_color=PALETTE["accent_soft"],
            button_hover_color=PALETTE["accent"],
            fg_color=PALETTE["surface"],
            text_color=PALETTE["text"],
            dropdown_fg_color=PALETTE["surface"],
            dropdown_hover_color=PALETTE["accent_soft"],
        )
        self.editor_widgets.append((combo, "readonly"))
        return combo

    def _folder_field(
        self,
        parent: tk.Misc,
        row: int,
        label: str,
        hint: str,
        variable: tk.StringVar,
        command: object,
        *,
        refresh: object | None = None,
    ) -> None:
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.grid(row=row, column=0, sticky="ew", padx=22, pady=(0, 13))
        line.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            line,
            text=label,
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            line,
            text=hint,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 10),
            anchor="e",
        ).grid(row=0, column=1, columnspan=3, sticky="e")
        entry = ctk.CTkEntry(
            line,
            textvariable=variable,
            height=42,
            corner_radius=11,
            border_color=PALETTE["border"],
            fg_color=PALETTE["surface_alt"],
            text_color=PALETTE["text"],
        )
        entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0), padx=(0, 9))
        browse = ctk.CTkButton(
            line,
            text="Browse",
            width=92,
            height=42,
            corner_radius=11,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["accent_soft"],
            text_color=PALETTE["text"],
            border_width=1,
            border_color=PALETTE["border"],
            command=command,
        )
        browse.grid(row=1, column=2, pady=(6, 0), padx=(0, 8))
        self.editor_widgets.extend([(entry, "normal"), (browse, "normal")])
        if refresh is not None:
            refresh_button = ctk.CTkButton(
                line,
                text="Refresh",
                width=92,
                height=42,
                corner_radius=11,
                fg_color=PALETTE["accent_soft"],
                hover_color=PALETTE["accent"],
                text_color=PALETTE["accent_hover"],
                command=refresh,
            )
            refresh_button.grid(row=1, column=3, pady=(6, 0))
            self.editor_widgets.append((refresh_button, "normal"))

    def _build_glossaries_view(self, parent: tk.Misc) -> ctk.CTkFrame:
        view = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(
            view,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=PALETTE["accent_soft"],
            scrollbar_button_hover_color=PALETTE["accent"],
        )
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        relay = self._card(
            body,
            "LRR",
            "Control the response relay and the endpoint client applications connect to.",
        )
        relay.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        relay.grid_columnconfigure((0, 1), weight=1, uniform="relay")
        self.interceptor_enabled_switch = ctk.CTkSwitch(
            relay,
            text="Enable LRR interceptor",
            variable=self.interceptor_enabled_var,
            onvalue=True,
            offvalue=False,
            progress_color=PALETTE["accent"],
            button_hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self._update_lrr_controls,
        )
        self.interceptor_enabled_switch.grid(
            row=2, column=0, columnspan=2, sticky="w", padx=22, pady=(0, 8)
        )
        ctk.CTkLabel(
            relay,
            text="When disabled, clients connect directly to the profile's llama.cpp endpoint and glossary replacement is bypassed.",
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 10),
            anchor="w",
            wraplength=800,
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 12))
        self._field_label(relay, 4, 0, "LRR host")
        self._field_label(relay, 4, 1, "LRR port")
        self.interceptor_host_entry = ctk.CTkEntry(
            relay,
            textvariable=self.interceptor_host_var,
            height=40,
            corner_radius=10,
            border_color=PALETTE["border"],
            fg_color=PALETTE["surface_alt"],
            text_color=PALETTE["text"],
        )
        self.interceptor_host_entry.grid(
            row=5, column=0, sticky="ew", padx=(22, 8), pady=(0, 8)
        )
        self.interceptor_port_entry = ctk.CTkEntry(
            relay,
            textvariable=self.interceptor_port_var,
            height=40,
            corner_radius=10,
            border_color=PALETTE["border"],
            fg_color=PALETTE["surface_alt"],
            text_color=PALETTE["text"],
        )
        self.interceptor_port_entry.grid(
            row=5, column=1, sticky="ew", padx=(8, 22), pady=(0, 8)
        )
        ctk.CTkLabel(
            relay,
            text="Loopback is recommended; non-loopback addresses expose LRR to your network.",
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 10),
            anchor="w",
        ).grid(row=6, column=0, sticky="ew", padx=22, pady=(0, 18))
        self.save_lrr_button = ctk.CTkButton(
            relay,
            text="Save LRR settings",
            width=154,
            height=40,
            corner_radius=11,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self._save_lrr_settings,
        )
        self.save_lrr_button.grid(
            row=6, column=1, sticky="e", padx=22, pady=(0, 18)
        )
        self.glossary_widgets.extend(
            [
                (self.interceptor_enabled_switch, "normal"),
                (self.interceptor_host_entry, "normal"),
                (self.interceptor_port_entry, "normal"),
                (self.save_lrr_button, "normal"),
            ]
        )

        toolbar = self._card(
            body,
            "Glossaries",
            "Reusable plain-text replacements. LRR uses the glossary selected here.",
        )
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        toolbar.grid_columnconfigure(0, weight=1)
        self.glossary_combo = ctk.CTkComboBox(
            toolbar,
            variable=self.glossary_choice_var,
            values=[],
            state="readonly",
            height=42,
            corner_radius=11,
            border_color=PALETTE["border"],
            button_color=PALETTE["accent_soft"],
            button_hover_color=PALETTE["accent"],
            fg_color=PALETTE["surface"],
            text_color=PALETTE["text"],
            dropdown_fg_color=PALETTE["surface"],
            dropdown_hover_color=PALETTE["accent_soft"],
            command=self._select_glossary,
        )
        self.glossary_combo.grid(
            row=2, column=0, sticky="ew", padx=(22, 10), pady=(0, 19)
        )
        actions = ctk.CTkFrame(toolbar, fg_color="transparent")
        actions.grid(row=2, column=1, padx=(0, 22), pady=(0, 19))
        self.new_glossary_button = self._small_action(
            actions, "+ New", self._new_glossary
        )
        self.new_glossary_button.pack(side="left", padx=(0, 6))
        self.rename_glossary_button = self._small_action(
            actions, "Rename", self._rename_glossary
        )
        self.rename_glossary_button.pack(side="left", padx=6)
        self.delete_glossary_button = self._small_action(
            actions, "Delete", self._delete_glossary, danger=True
        )
        self.delete_glossary_button.pack(side="left", padx=(6, 0))
        self.glossary_widgets.extend(
            [
                (self.glossary_combo, "readonly"),
                (self.new_glossary_button, "normal"),
                (self.rename_glossary_button, "normal"),
                (self.delete_glossary_button, "normal"),
            ]
        )

        editor = self._card(
            body,
            "Entries",
            "Longest matching source wins. Replacements are not applied recursively.",
        )
        editor.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        editor.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            editor,
            textvariable=self.glossary_name_var,
            text_color=PALETTE["accent_hover"],
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 12))
        self.glossary_entries = ctk.CTkScrollableFrame(
            editor,
            height=300,
            fg_color=PALETTE["surface_alt"],
            corner_radius=13,
            scrollbar_button_color=PALETTE["accent_soft"],
            scrollbar_button_hover_color=PALETTE["accent"],
        )
        self.glossary_entries.grid(
            row=3, column=0, sticky="ew", padx=22, pady=(0, 12)
        )
        self.glossary_entries.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkFrame(editor, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 20))
        footer.grid_columnconfigure(1, weight=1)
        self.add_entry_button = ctk.CTkButton(
            footer,
            text="+ Add entry",
            width=118,
            height=40,
            corner_radius=11,
            fg_color=PALETTE["accent_soft"],
            hover_color=PALETTE["accent"],
            text_color=PALETTE["accent_hover"],
            command=self._add_glossary_row,
        )
        self.add_entry_button.grid(row=0, column=0, padx=(0, 14))
        self.glossary_error_label = ctk.CTkLabel(
            footer,
            textvariable=self.glossary_error_var,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 11),
            anchor="w",
            wraplength=520,
        )
        self.glossary_error_label.grid(row=0, column=1, sticky="ew")
        self.save_glossary_button = ctk.CTkButton(
            footer,
            text="Save glossary",
            width=148,
            height=42,
            corner_radius=12,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self._save_glossary,
        )
        self.save_glossary_button.grid(row=0, column=2, padx=(14, 0))
        self.glossary_widgets.extend(
            [
                (self.add_entry_button, "normal"),
                (self.save_glossary_button, "normal"),
            ]
        )
        self._update_lrr_controls()
        return view

    def _build_runtime_view(self, parent: tk.Misc) -> ctk.CTkFrame:
        view = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        view.grid_rowconfigure(1, weight=1)
        view.grid_columnconfigure(0, weight=1)
        summary = ctk.CTkFrame(
            view,
            height=196,
            corner_radius=16,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
        )
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.runtime_dashboard = summary
        summary.grid_propagate(False)
        summary.grid_columnconfigure(0, weight=1)
        summary.grid_columnconfigure(1, weight=1)

        lifecycle = ctk.CTkFrame(summary, fg_color="transparent")
        lifecycle.grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(8, 2)
        )
        lifecycle.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            lifecycle,
            textvariable=self.runtime_identity_var,
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            lifecycle,
            textvariable=self.telemetry_health_var,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 9),
        ).grid(row=0, column=1, padx=10)

        controls = ctk.CTkFrame(lifecycle, fg_color="transparent")
        controls.grid(row=0, column=2, sticky="e")
        self.start_button = ctk.CTkButton(
            controls,
            text="Start",
            width=78,
            height=30,
            corner_radius=9,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            command=self._start,
        )
        self.start_button.pack(side="left", padx=(0, 4))
        self.stop_button = self._runtime_button(controls, "Stop", self._stop)
        self.stop_button.pack(side="left", padx=4)
        self.restart_button = self._runtime_button(
            controls, "Restart", self._restart
        )
        self.restart_button.pack(side="left", padx=(4, 0))

        endpoints = ctk.CTkFrame(summary, fg_color="transparent")
        endpoints.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 2)
        )
        endpoints.grid_columnconfigure(0, weight=1)
        endpoints.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            endpoints,
            textvariable=self.upstream_endpoint_var,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Cascadia Mono", 8),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            endpoints,
            textvariable=self.client_endpoint_var,
            text_color=PALETTE["accent_hover"],
            font=ctk.CTkFont("Cascadia Mono", 8, "bold"),
            anchor="e",
        ).grid(row=0, column=1, sticky="ew")

        metrics = ctk.CTkFrame(summary, fg_color="transparent")
        metrics.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(1, 2)
        )
        for column in range(4):
            metrics.grid_columnconfigure(column, weight=1, uniform="runtime-kpi")
        self._runtime_metric(
            metrics,
            0,
            "Generation",
            self.token_rate_var,
            self.token_rate_hint_var,
        )
        self._runtime_metric(
            metrics,
            1,
            "Slots",
            self.slot_pressure_var,
            self.slot_pressure_hint_var,
        )
        self._runtime_metric(
            metrics, 2, "Queue", self.queue_var, self.queue_hint_var
        )
        self._runtime_metric(
            metrics,
            3,
            "Session tokens",
            self.session_tokens_var,
            self.session_tokens_hint_var,
        )

        ctk.CTkLabel(
            summary,
            textvariable=self.latest_task_var,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 9),
            anchor="w",
        ).grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 2)
        )

        charts = ctk.CTkFrame(summary, fg_color="transparent")
        charts.grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 5)
        )
        charts.grid_columnconfigure(0, weight=1, uniform="runtime-chart")
        charts.grid_columnconfigure(1, weight=1, uniform="runtime-chart")
        self.throughput_chart = CompactChart(
            charts, "Throughput · 5 min", "Prompt", "Generation"
        )
        self.throughput_chart.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.pressure_chart = CompactChart(
            charts,
            "Slot pressure · 5 min",
            "Occupancy",
            "Deferred",
            primary_color=PALETTE["warning"],
            secondary_color=PALETTE["error"],
        )
        self.pressure_chart.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.runtime_progress = ctk.CTkProgressBar(
            summary,
            height=3,
            corner_radius=2,
            mode="indeterminate",
            fg_color=PALETTE["surface_alt"],
            progress_color=PALETTE["accent"],
        )
        self.runtime_progress.place(
            relx=0.5, rely=1, relwidth=0.96, y=-3, anchor="s"
        )
        self.runtime_progress.set(0)

        logs = self._card(view, "Process output", "Recent stdout and stderr from the owned process.")
        self.process_output_card = logs
        logs.grid(row=1, column=0, sticky="nsew")
        logs.grid_rowconfigure(2, weight=1)
        logs.grid_columnconfigure(0, weight=1)
        self.log_text = ctk.CTkTextbox(
            logs,
            state="disabled",
            wrap="none",
            corner_radius=13,
            border_width=0,
            fg_color=PALETTE["log"],
            text_color=PALETTE["log_text"],
            font=ctk.CTkFont("Cascadia Mono", 11),
        )
        self.log_text.grid(row=2, column=0, sticky="nsew", padx=22, pady=(0, 22))
        self._sync_controls()
        return view

    def _runtime_metric(
        self,
        parent: tk.Misc,
        column: int,
        title: str,
        value: tk.StringVar,
        hint: tk.StringVar,
    ) -> None:
        card = ctk.CTkFrame(
            parent,
            height=43,
            corner_radius=9,
            fg_color=PALETTE["surface_alt"],
        )
        card.grid(row=0, column=column, sticky="ew", padx=3)
        card.grid_propagate(False)
        ctk.CTkLabel(
            card,
            text=title,
            width=100,
            height=12,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 8),
            anchor="w",
        ).place(x=8, y=3)
        ctk.CTkLabel(
            card,
            textvariable=value,
            width=130,
            height=17,
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            anchor="w",
        ).place(x=8, y=16)
        ctk.CTkLabel(
            card,
            textvariable=hint,
            width=88,
            height=12,
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 7),
            anchor="e",
        ).place(relx=1, x=-7, y=4, anchor="ne")

    def _runtime_button(
        self, parent: tk.Misc, text: str, command: object
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            width=70,
            height=30,
            corner_radius=9,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["accent_soft"],
            text_color=PALETTE["text"],
            border_width=1,
            border_color=PALETTE["border"],
            command=command,
        )

    def _switch_view(self, name: str) -> None:
        if name == self._current_view:
            return
        views = {
            "Settings": self.settings_view,
            "LRR": self.glossaries_view,
            "Runtime": self.runtime_view,
        }
        order = list(views)
        if name not in views:
            return
        incoming = views[name]
        outgoing = views[self._current_view]
        direction = 1 if order.index(name) > order.index(self._current_view) else -1
        width = max(1, self.view_host.winfo_width())
        travel = min(80, max(42, width // 12))
        incoming.place(x=direction * travel, y=0, relwidth=1, relheight=1)
        incoming.lift()
        self._current_view = name

        def update(progress: float) -> None:
            incoming.place_configure(x=round(direction * travel * (1 - progress)))
            outgoing.place_configure(x=round(-direction * travel * progress))

        def complete() -> None:
            outgoing.place_forget()
            incoming.place_configure(x=0)

        self._view_animator.run(update, duration_ms=190, complete=complete)

    def _refresh_glossary_choices(self, *, select: str = "") -> None:
        names = self.glossaries.names()
        selected: Glossary | None = None
        if select:
            try:
                selected = self.glossaries.get(select)
            except ValidationError:
                selected = None
        if selected is None and names:
            selected = self.glossaries.get(names[0])
        choice = selected.name if selected is not None else ""
        self.glossary_combo.configure(values=names)
        self.glossary_choice_var.set(choice)
        if selected is not None:
            self.glossaries.select(selected.id)
            self._load_glossary(selected.id)
        else:
            self.original_glossary_id = ""
            self.glossary_name_var.set("No glossary selected")
            self._render_glossary_rows([])
        has_glossary = selected is not None
        state = "normal" if has_glossary and not self.manager.is_active else "disabled"
        self.rename_glossary_button.configure(state=state)
        self.delete_glossary_button.configure(state=state)

    def _update_lrr_controls(self) -> None:
        if not hasattr(self, "interceptor_host_entry"):
            return
        editable = not self.manager.is_active
        endpoint_state = (
            "normal"
            if editable and self.interceptor_enabled_var.get()
            else "disabled"
        )
        self.interceptor_host_entry.configure(state=endpoint_state)
        self.interceptor_port_entry.configure(state=endpoint_state)
        self.interceptor_enabled_switch.configure(
            state="normal" if editable else "disabled"
        )
        self.save_lrr_button.configure(state="normal" if editable else "disabled")
        self._update_endpoint_labels()

    def _update_endpoint_labels(self, profile: Profile | None = None) -> None:
        if profile is None:
            name = self.profile_choice_var.get()
            if name:
                try:
                    profile = self.profiles.get(name)
                except ValidationError:
                    profile = None
        if profile is not None:
            upstream = f"http://{profile.host}:{profile.port}"
            self.upstream_endpoint_var.set(f"Upstream: {upstream}")
        else:
            upstream = ""
            self.upstream_endpoint_var.set("Upstream: —")
        if self.interceptor_enabled_var.get():
            self.client_endpoint_var.set(
                f"Client endpoint: http://{self.interceptor_host_var.get().strip()}:"
                f"{self.interceptor_port_var.get().strip()}"
            )
        elif upstream:
            self.client_endpoint_var.set(
                f"Client endpoint: {upstream} (direct · LRR disabled)"
            )
        else:
            self.client_endpoint_var.set("Client endpoint: LRR disabled")

    def _save_lrr_settings(self) -> None:
        if self._save_settings():
            state = "enabled" if self.settings.interceptor_enabled else "disabled"
            self.glossary_error_label.configure(text_color=PALETTE["muted"])
            self.glossary_error_var.set(f"LRR settings saved · {state}.")

    def _select_glossary(self, name: str) -> None:
        if self.manager.is_active or not name:
            return
        glossary = self.glossaries.select(name)
        self._load_glossary(glossary.id)
        self._save_settings()

    def _ask_glossary_name(
        self,
        *,
        title: str,
        action_text: str,
        initial_value: str,
        current_name: str = "",
    ) -> str | None:
        dialog = ProfileNameDialog(
            self.root,
            title=title,
            action_text=action_text,
            initial_value=initial_value,
            existing_names=self.glossaries.names(),
            current_name=current_name,
        )
        self.root.wait_window(dialog)
        return dialog.result

    def _new_glossary(self) -> None:
        base = "New glossary"
        names = {name.casefold() for name in self.glossaries.names()}
        candidate = base
        suffix = 2
        while candidate.casefold() in names:
            candidate = f"{base} {suffix}"
            suffix += 1
        name = self._ask_glossary_name(
            title="New glossary",
            action_text="Create glossary",
            initial_value=candidate,
        )
        if name is None:
            return
        self.original_glossary_id = ""
        self.glossary_choice_var.set("")
        self.glossary_name_var.set(name)
        self._render_glossary_rows([])
        self.glossary_error_var.set(f'Add entries, then save "{name}".')

    def _rename_glossary(self) -> None:
        if not self.original_glossary_id:
            return
        current = self.glossaries.get(self.original_glossary_id)
        name = self._ask_glossary_name(
            title="Rename glossary",
            action_text="Rename",
            initial_value=current.name,
            current_name=current.name,
        )
        if name is None or name == current.name:
            return
        snapshot = AppSettings.from_dict(self.settings.to_dict())
        try:
            updated = self.glossaries.rename(current.id, name)
            if not self._save_settings():
                self._restore_after_failed_save(snapshot)
                return
            self._refresh_glossary_choices(select=updated.id)
            self._refresh_profile_choices(select=self.settings.selected_profile)
            self.glossary_error_var.set(f'Renamed glossary to "{name}".')
        except ValidationError as exc:
            self._restore_settings(snapshot)
            self._show_glossary_error(str(exc))

    def _delete_glossary(self) -> None:
        if not self.original_glossary_id:
            return
        glossary = self.glossaries.get(self.original_glossary_id)
        if not messagebox.askyesno(
            "Delete glossary",
            f'Delete glossary "{glossary.name}"?',
            parent=self.root,
        ):
            return
        snapshot = AppSettings.from_dict(self.settings.to_dict())
        try:
            self.glossaries.delete(glossary.id)
            if not self._save_settings():
                self._restore_after_failed_save(snapshot)
                return
            self._refresh_glossary_choices(select=self.settings.selected_glossary_id)
            self._refresh_profile_choices(select=self.settings.selected_profile)
            if self.profile_choice_var.get():
                self._load_profile(self.profile_choice_var.get())
            self.glossary_error_var.set(f'Deleted glossary "{glossary.name}".')
        except ValidationError as exc:
            self._restore_settings(snapshot)
            self._show_glossary_error(str(exc))

    def _load_glossary(self, identifier: str) -> None:
        glossary = self.glossaries.get(identifier)
        self.original_glossary_id = glossary.id
        self.glossary_choice_var.set(glossary.name)
        self.glossary_name_var.set(glossary.name)
        self._render_glossary_rows(deepcopy(glossary.entries))
        self.glossary_error_var.set(f"{len(glossary.entries)} replacement(s).")

    def _render_glossary_rows(self, entries: list[GlossaryEntry]) -> None:
        for row in self.glossary_rows:
            frame = row["frame"]
            if isinstance(frame, tk.Widget):
                frame.destroy()
        row_widgets = {
            id(widget)
            for row in self.glossary_rows
            for widget in row.get("widgets", [])
            if isinstance(widget, tk.Widget)
        }
        self.glossary_widgets = [
            item for item in self.glossary_widgets if id(item[0]) not in row_widgets
        ]
        self.glossary_rows.clear()
        for entry in entries:
            self._add_glossary_row(entry)

    def _add_glossary_row(self, entry: GlossaryEntry | None = None) -> None:
        if (
            entry is None
            and not self.original_glossary_id
            and self.glossary_name_var.get() == "No glossary selected"
        ):
            self._show_glossary_error(
                'Create a named glossary with "+ New" before adding entries.'
            )
            return
        entry = entry or GlossaryEntry(source="", replacement="")
        row_index = len(self.glossary_rows)
        frame = ctk.CTkFrame(
            self.glossary_entries,
            fg_color=PALETTE["surface"],
            corner_radius=12,
            border_width=1,
            border_color=PALETTE["border"],
        )
        frame.grid(row=row_index, column=0, sticky="ew", padx=4, pady=3)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=1)
        source_var = tk.StringVar(value=entry.source)
        replacement_var = tk.StringVar(value=entry.replacement)
        enabled_var = tk.BooleanVar(value=entry.enabled)
        case_var = tk.BooleanVar(value=entry.case_sensitive)
        source = ctk.CTkEntry(
            frame, textvariable=source_var, placeholder_text="Source",
            height=34, corner_radius=9,
            border_color=PALETTE["border"], fg_color=PALETTE["surface_alt"],
            text_color=PALETTE["text"],
        )
        source.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=8)
        replacement = ctk.CTkEntry(
            frame, textvariable=replacement_var, placeholder_text="Replacement",
            height=34, corner_radius=9,
            border_color=PALETTE["border"], fg_color=PALETTE["surface_alt"],
            text_color=PALETTE["text"],
        )
        replacement.grid(row=0, column=2, sticky="ew", padx=6, pady=8)
        enabled = ctk.CTkSwitch(
            frame, text="Enabled", variable=enabled_var, width=72,
            progress_color=PALETTE["accent"], text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 9),
        )
        enabled.grid(row=0, column=0, sticky="w", padx=(10, 8), pady=8)
        case = ctk.CTkSwitch(
            frame, text="Case", variable=case_var, width=66,
            progress_color=PALETTE["accent"], text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 9),
        )
        case.grid(row=0, column=3, sticky="e", padx=(8, 0), pady=8)
        remove = ctk.CTkButton(
            frame, text="Remove", width=72, height=30, corner_radius=9,
            fg_color=PALETTE["error_soft"], hover_color="#F9CCD6",
            text_color=PALETTE["error"],
        )
        remove.grid(row=0, column=4, sticky="e", padx=(8, 10), pady=8)
        row: dict[str, object] = {
            "id": entry.id,
            "frame": frame,
            "source": source_var,
            "replacement": replacement_var,
            "enabled": enabled_var,
            "case_sensitive": case_var,
            "enabled_widget": enabled,
            "case_widget": case,
            "remove_widget": remove,
            "widgets": [source, replacement, enabled, case, remove],
        }
        remove.configure(command=lambda item=row: self._remove_glossary_row(item))
        self.glossary_rows.append(row)
        self.glossary_widgets.extend(
            (widget, "normal") for widget in row["widgets"]  # type: ignore[arg-type]
        )
        self._sync_controls()
        if hasattr(self.glossary_entries, "_parent_canvas"):
            self.glossary_entries.after(
                20,
                lambda: self.glossary_entries._parent_canvas.yview_moveto(1.0),
            )

    def _remove_glossary_row(self, row: dict[str, object]) -> None:
        if self.manager.is_active or row not in self.glossary_rows:
            return
        widgets = row.get("widgets", [])
        widget_ids = {id(widget) for widget in widgets}
        self.glossary_widgets = [
            item for item in self.glossary_widgets if id(item[0]) not in widget_ids
        ]
        frame = row["frame"]
        if isinstance(frame, tk.Widget):
            frame.destroy()
        self.glossary_rows.remove(row)
        for index, item in enumerate(self.glossary_rows):
            item_frame = item["frame"]
            if isinstance(item_frame, tk.Widget):
                item_frame.grid_configure(row=index)

    def _glossary_from_form(self) -> Glossary:
        entries: list[GlossaryEntry] = []
        for row in self.glossary_rows:
            source_var = row["source"]
            replacement_var = row["replacement"]
            enabled_var = row["enabled"]
            case_var = row["case_sensitive"]
            assert isinstance(source_var, tk.StringVar)
            assert isinstance(replacement_var, tk.StringVar)
            assert isinstance(enabled_var, tk.BooleanVar)
            assert isinstance(case_var, tk.BooleanVar)
            entries.append(
                GlossaryEntry(
                    id=str(row["id"]),
                    source=source_var.get(),
                    replacement=replacement_var.get(),
                    enabled=enabled_var.get(),
                    case_sensitive=case_var.get(),
                )
            )
        glossary = Glossary(
            id=self.original_glossary_id or Glossary(name="temporary").id,
            name=self.glossary_name_var.get(),
            entries=entries,
        )
        glossary.validate()
        return glossary

    def _save_glossary(self) -> None:
        snapshot = AppSettings.from_dict(self.settings.to_dict())
        try:
            glossary = self._glossary_from_form()
            if self.original_glossary_id:
                glossary = self.glossaries.update(self.original_glossary_id, glossary)
            else:
                glossary = self.glossaries.create(glossary)
            if not self._save_settings():
                self._restore_after_failed_save(snapshot)
                return
            self._refresh_glossary_choices(select=glossary.id)
            self.glossary_error_var.set(f'Saved glossary "{glossary.name}".')
        except ValidationError as exc:
            self._show_glossary_error(str(exc))

    def _show_glossary_error(self, message: str) -> None:
        self.glossary_error_var.set(message)
        self.glossary_error_label.configure(text_color=PALETTE["error"])

    def _choose_llama_folder(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Choose llama.cpp folder",
            initialdir=self.llama_folder_var.get() or None,
        )
        if not selected:
            return
        self.llama_folder_var.set(selected)
        self.settings.llama_cpp_folder = selected
        try:
            resolve_llama_server(selected)
            self._save_settings()
            self._show_message("Found llama-server.exe.")
        except ValidationError as exc:
            self._show_error(str(exc))

    def _choose_model_folder(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Choose model folder",
            initialdir=self.model_folder_var.get() or None,
        )
        if not selected:
            return
        self.model_folder_var.set(selected)
        self.settings.model_folder = selected
        self._refresh_models()
        self._save_settings()

    def _refresh_models(self, show_errors: bool = True) -> None:
        folder = self.model_folder_var.get().strip()
        if not folder:
            self.model_paths = {}
            self.model_combo.configure(values=[])
            return
        try:
            models = discover_models(folder)
        except ValidationError as exc:
            self.model_paths = {}
            self.model_combo.configure(values=[])
            if show_errors:
                self._show_error(str(exc))
            return
        self.model_paths = {path.name: path for path in models}
        values = list(self.model_paths)
        current = self.model_var.get()
        if current and current not in values and Path(current).name not in values:
            values.append(current)
        self.model_combo.configure(values=values)
        if not current and values:
            self.model_var.set(values[0])
        self._show_message(f"Found {len(models)} GGUF model(s).")

    def _refresh_profile_choices(self, *, select: str = "") -> None:
        names = self.profiles.names()
        choice = select if select in names else (names[0] if names else "")
        self.profile_choice_var.set(choice)
        for button in self.profile_buttons:
            button.destroy()
        self.profile_buttons.clear()
        for index, name in enumerate(names):
            selected = name == choice
            button = ctk.CTkButton(
                self.profile_list,
                text=name,
                height=42,
                corner_radius=12,
                anchor="w",
                fg_color=PALETTE["accent_soft"] if selected else "transparent",
                hover_color=PALETTE["accent_soft"],
                text_color=PALETTE["accent_hover"] if selected else PALETTE["text"],
                font=ctk.CTkFont("Segoe UI", 11, "bold" if selected else "normal"),
                command=lambda selected_name=name: self._select_profile(selected_name),
            )
            button.grid(row=index, column=0, sticky="ew", padx=2, pady=3)
            self.profile_buttons.append(button)
        has_choice = bool(choice)
        action_state = "normal" if has_choice else "disabled"
        self.rename_button.configure(state=action_state)
        self.duplicate_button.configure(state=action_state)
        self.delete_button.configure(state=action_state)
        self._sync_controls()

    def _select_profile(self, name: str) -> None:
        if not control_states(
            self.manager.state, True, process_active=self.manager.is_active
        )["edit"]:
            return
        self.profile_choice_var.set(name)
        self.profiles.select(name)
        self._load_profile(name)
        self._save_settings()
        self._refresh_profile_choices(select=name)

    def _profile_selected(self, _event: object = None) -> None:
        name = self.profile_choice_var.get()
        if name:
            self._select_profile(name)

    def _load_profile(self, name: str) -> None:
        profile = self.profiles.get(name)
        self.original_profile_name = profile.name
        self.name_var.set(profile.name)
        model_name = Path(profile.model_path).name
        self.model_var.set(model_name if model_name in self.model_paths else profile.model_path)
        self.host_var.set(profile.host)
        self.port_var.set(str(profile.port))
        self.ngl_var.set(str(profile.ngl))
        self.context_var.set(str(profile.context_size))
        self.parallel_var.set(str(profile.parallel_slots))
        self.flash_var.set(profile.flash_attention.value)
        self.no_mmap_var.set(profile.no_mmap)
        self.gpu_var.set(profile.gpu_mode.value)
        self._update_endpoint_labels(profile)
        self.custom_text.configure(state="normal")
        self.custom_text.delete("1.0", "end")
        self.custom_text.insert("1.0", profile.custom_args)
        self._show_message(f"Editing {profile.name}.")

    def _ask_profile_name(
        self,
        *,
        title: str,
        action_text: str,
        initial_value: str,
        current_name: str = "",
    ) -> str | None:
        dialog = ProfileNameDialog(
            self.root,
            title=title,
            action_text=action_text,
            initial_value=initial_value,
            existing_names=self.profiles.names(),
            current_name=current_name,
        )
        self.root.wait_window(dialog)
        return dialog.result

    def _new_profile(self, *, prompt: bool = True) -> None:
        if prompt:
            name = self._ask_profile_name(
                title="New profile",
                action_text="Create profile",
                initial_value=suggest_profile_name(self.profiles.names()),
            )
            if name is None:
                return
        else:
            name = suggest_profile_name(self.profiles.names())
        self.original_profile_name = ""
        self.profile_choice_var.set("")
        self.name_var.set(name)
        self.model_var.set(next(iter(self.model_paths), ""))
        self.host_var.set("127.0.0.1")
        self.port_var.set("8080")
        self.ngl_var.set("0")
        self.context_var.set("4096")
        self.parallel_var.set("1")
        self.flash_var.set(FlashAttention.AUTO.value)
        self.no_mmap_var.set(False)
        self.gpu_var.set(GpuMode.AUTO.value)
        self._update_endpoint_labels()
        self.custom_text.configure(state="normal")
        self.custom_text.delete("1.0", "end")
        self._show_message(f'Configure and save "{name}".')
        self.view_switch.set("Settings")
        self._switch_view("Settings")

    def _rename_profile(self) -> None:
        name = self.profile_choice_var.get()
        if not name:
            return
        renamed = self._ask_profile_name(
            title="Rename profile",
            action_text="Rename",
            initial_value=name,
            current_name=name,
        )
        if renamed is None or renamed == name:
            return
        snapshot = AppSettings.from_dict(self.settings.to_dict())
        try:
            profile = replace(self.profiles.get(name), name=renamed)
            self.profiles.update(name, profile)
            if not self._save_settings():
                self._restore_after_failed_save(snapshot)
                return
            self.original_profile_name = renamed
            self._refresh_profile_choices(select=renamed)
            self._load_profile(renamed)
            self._show_message(f'Renamed profile to "{renamed}".')
        except ValidationError as exc:
            self._restore_settings(snapshot)
            self._show_error(str(exc))

    def _profile_from_form(self) -> Profile:
        model_value = self.model_var.get()
        model_path = self.model_paths.get(model_value, Path(model_value))
        try:
            return Profile(
                name=self.name_var.get(),
                model_path=str(model_path),
                host=self.host_var.get().strip(),
                port=int(self.port_var.get()),
                ngl=int(self.ngl_var.get()),
                context_size=int(self.context_var.get()),
                parallel_slots=int(self.parallel_var.get()),
                flash_attention=FlashAttention(self.flash_var.get()),
                no_mmap=self.no_mmap_var.get(),
                gpu_mode=GpuMode(self.gpu_var.get()),
                custom_args=self.custom_text.get("1.0", "end-1c"),
            )
        except ValueError as exc:
            raise ValidationError(
                f"Numeric and option fields must contain valid values: {exc}"
            ) from exc

    def _save_profile(self) -> None:
        snapshot = AppSettings.from_dict(self.settings.to_dict())
        try:
            profile = self._profile_from_form()
            if self.original_profile_name:
                self.profiles.update(self.original_profile_name, profile)
            else:
                self.profiles.create(profile)
            if not self._save_settings():
                self._restore_after_failed_save(snapshot)
                return
            self.original_profile_name = profile.name
            self._refresh_profile_choices(select=profile.name)
            self._show_message(f'Saved profile "{profile.name}".')
        except ValidationError as exc:
            self._show_error(str(exc))

    def _duplicate_profile(self) -> None:
        name = self.profile_choice_var.get()
        if not name:
            return
        snapshot = AppSettings.from_dict(self.settings.to_dict())
        copy = self.profiles.duplicate(name)
        if not self._save_settings():
            self._restore_after_failed_save(snapshot)
            return
        self._refresh_profile_choices(select=copy.name)
        self._load_profile(copy.name)

    def _delete_profile(self) -> None:
        name = self.profile_choice_var.get()
        if not name:
            return
        if not messagebox.askyesno(
            "Delete profile", f'Delete profile "{name}"?', parent=self.root
        ):
            return
        snapshot = AppSettings.from_dict(self.settings.to_dict())
        try:
            self.profiles.delete(name, running_profile=self.manager.active_profile)
            if not self._save_settings():
                self._restore_after_failed_save(snapshot)
                return
            self._refresh_profile_choices(select=self.settings.selected_profile)
            if self.settings.selected_profile:
                self._load_profile(self.settings.selected_profile)
            else:
                self._new_profile(prompt=False)
        except ValidationError as exc:
            self._show_error(str(exc))

    def _start(self) -> None:
        self._run_lifecycle("start")

    def _stop(self) -> None:
        self._run_lifecycle("stop")

    def _restart(self) -> None:
        self._run_lifecycle("restart")

    def _run_lifecycle(self, action: str) -> None:
        if action == "stop":
            self._set_buttons_busy()

            def stop_worker() -> None:
                try:
                    self.manager.stop(
                        timeout_seconds=self.settings.shutdown_timeout_seconds
                    )
                except ValidationError as exc:
                    self.ui_events.put(("error", str(exc)))
                finally:
                    self.ui_events.put(("sync", None))

            threading.Thread(target=stop_worker, name="ui-stop", daemon=True).start()
            return
        try:
            if not self._save_settings():
                return
            profile = self.profiles.get(self.profile_choice_var.get())
            profile.validate(self.settings.model_folder, require_files=True)
            executable = resolve_llama_server(self.settings.llama_cpp_folder)
            glossary = self.glossaries.snapshot(self.settings.selected_glossary_id)
        except ValidationError as exc:
            self._show_error(str(exc))
            return
        self._set_buttons_busy()
        self.view_switch.set("Runtime")
        self._switch_view("Runtime")

        def worker() -> None:
            try:
                help_text = probe_help(executable)
                if action == "start":
                    self.manager.start(
                        executable,
                        profile,
                        help_text,
                        interceptor_enabled=self.settings.interceptor_enabled,
                        interceptor_host=self.settings.interceptor_host,
                        interceptor_port=self.settings.interceptor_port,
                        glossary=glossary,
                        startup_timeout_seconds=self.settings.startup_timeout_seconds,
                    )
                else:
                    self.manager.restart(
                        executable,
                        profile,
                        help_text,
                        interceptor_enabled=self.settings.interceptor_enabled,
                        interceptor_host=self.settings.interceptor_host,
                        interceptor_port=self.settings.interceptor_port,
                        glossary=glossary,
                        startup_timeout_seconds=self.settings.startup_timeout_seconds,
                        shutdown_timeout_seconds=self.settings.shutdown_timeout_seconds,
                    )
            except ValidationError as exc:
                self.ui_events.put(("error", str(exc)))
            finally:
                self.ui_events.put(("sync", None))

        threading.Thread(target=worker, name=f"ui-{action}", daemon=True).start()

    def _poll_events(self) -> None:
        while True:
            try:
                event = self.manager.events.get_nowait()
            except queue.Empty:
                break
            self._handle_runtime_event(event)
        while True:
            try:
                kind, payload = self.ui_events.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                self._show_error(str(payload))
            elif kind == "closed":
                self.root.destroy()
                return
            elif kind == "sync":
                self._sync_controls()
        now = time.monotonic()
        if now - self._last_dashboard_tick >= 1:
            snapshot = self.manager.dashboard_snapshot
            if snapshot is not None:
                self._render_dashboard(snapshot, redraw_charts=False)
            self._last_dashboard_tick = now
        if self.root.winfo_exists():
            self.root.after(self.POLL_MS, self._poll_events)

    def _handle_runtime_event(self, event: RuntimeEvent) -> None:
        if event.kind == "state" and event.state is not None:
            self.status_var.set(event.state.value)
            self.detail_var.set(event.message)
            self._animate_status(event.state)
            if event.state in {RuntimeState.STARTING, RuntimeState.STOPPING}:
                self.runtime_progress.start()
            else:
                self.runtime_progress.stop()
                self.runtime_progress.set(1 if event.state is RuntimeState.READY else 0)
            self._sync_controls()
        elif event.kind == "log":
            prefix = f"[{event.source}] " if event.source else ""
            self._append_log(prefix + event.message)
        elif event.kind == "telemetry" and isinstance(
            event.payload, DashboardSnapshot
        ):
            self._render_dashboard(event.payload)

    def _render_dashboard(
        self, snapshot: DashboardSnapshot, *, redraw_charts: bool = True
    ) -> None:
        lifecycle = "Stopped" if snapshot.stopped else self.status_var.get()
        self.runtime_identity_var.set(
            f"{snapshot.profile_name} · {lifecycle} · {format_duration(snapshot.uptime_seconds)}"
        )
        if snapshot.stopped:
            health = "Telemetry stopped · final snapshot"
        else:
            health = (
                f"Metrics {snapshot.metrics_state.value}"
                f" · Slots {snapshot.slots_state.value}"
            )
        self.telemetry_health_var.set(health)

        rate_state = snapshot.metrics_state.value
        self.token_rate_var.set(
            format_rate(snapshot.current_generated_tokens_per_second)
            if snapshot.current_generated_tokens_per_second is not None
            else rate_state
        )
        self.token_rate_hint_var.set(
            f"avg {format_rate(snapshot.average_generated_tokens_per_second)}"
        )
        if snapshot.active_slots is None:
            self.slot_pressure_var.set(snapshot.slots_state.value)
        else:
            self.slot_pressure_var.set(
                f"{snapshot.active_slots}/{snapshot.total_slots}"
                f" · {format_percent(snapshot.slot_occupancy)}"
            )
        self.slot_pressure_hint_var.set(f"{snapshot.total_slots} configured")
        self.queue_var.set(
            format_count(snapshot.deferred_requests)
            if snapshot.deferred_requests is not None
            else snapshot.metrics_state.value
        )
        self.session_tokens_var.set(
            f"In {format_count(snapshot.session_prompt_tokens)}"
            f" · Out {format_count(snapshot.session_generated_tokens)}"
        )

        latest = snapshot.latest_request
        if latest is None:
            self.latest_task_var.set("Latest client task: Unavailable")
        else:
            cache = (
                format_percent(latest.cache_reuse)
                if latest.cache_reuse is not None
                else "—"
            )
            self.latest_task_var.set(
                f"Latest client task · {latest.status}"
                f" · Input {format_count(latest.input_tokens)}"
                f" · Output {format_count(latest.generated_tokens)}"
                f" · Cache {cache}"
                f" · Server {format_ms(latest.server_compute_ms)}"
                f" · TTFT {format_ms(latest.time_to_first_byte_ms)}"
                f" · Total {format_ms(latest.end_to_end_ms)}"
            )

        if not redraw_charts:
            return
        history = snapshot.history
        throughput_state = _chart_state(
            snapshot.metrics_state, snapshot.stopped
        )
        pressure_state = _chart_state(
            (
                snapshot.slots_state
                if snapshot.slots_state is not Availability.UNSUPPORTED
                else snapshot.metrics_state
            ),
            snapshot.stopped,
        )
        self.throughput_chart.set_data(
            (sample.prompt_tokens_per_second for sample in history),
            (sample.generated_tokens_per_second for sample in history),
            state=throughput_state,
        )
        self.pressure_chart.set_data(
            (
                sample.slot_occupancy * 100
                if sample.slot_occupancy is not None
                else None
                for sample in history
            ),
            (sample.deferred_requests for sample in history),
            state=pressure_state,
        )

    def _animate_status(self, state: RuntimeState) -> None:
        target_bg, target_fg = STATUS_COLORS[state.value]
        start_bg, start_fg = self._status_bg, self._status_fg

        def update(progress: float) -> None:
            self._status_bg = blend_color(start_bg, target_bg, progress)
            self._status_fg = blend_color(start_fg, target_fg, progress)
            self.status_label.configure(
                fg_color=self._status_bg, text_color=self._status_fg
            )

        self._status_animator.run(update, duration_ms=180)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 2000:
            self.log_text.delete("1.0", f"{lines - 2000}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _sync_controls(self) -> None:
        states = control_states(
            self.manager.state,
            bool(self.profile_choice_var.get()),
            process_active=self.manager.is_active,
        )
        self.start_button.configure(state="normal" if states["start"] else "disabled")
        self.stop_button.configure(state="normal" if states["stop"] else "disabled")
        self.restart_button.configure(
            state="normal" if states["restart"] else "disabled"
        )
        editor_state = "normal" if states["edit"] else "disabled"
        self.save_button.configure(state=editor_state)
        self.new_profile_button.configure(state=editor_state)
        has_choice = bool(self.profile_choice_var.get())
        profile_action_state = "normal" if states["edit"] and has_choice else "disabled"
        self.rename_button.configure(state=profile_action_state)
        self.duplicate_button.configure(state=profile_action_state)
        self.delete_button.configure(state=profile_action_state)
        for button in self.profile_buttons:
            button.configure(state=editor_state)
        for widget, enabled_state in self.editor_widgets:
            widget.configure(state=enabled_state if states["edit"] else "disabled")
        for widget, enabled_state in self.glossary_widgets:
            widget.configure(state=enabled_state if states["edit"] else "disabled")
        has_glossary = bool(self.original_glossary_id)
        glossary_action_state = (
            "normal" if states["edit"] and has_glossary else "disabled"
        )
        self.rename_glossary_button.configure(state=glossary_action_state)
        self.delete_glossary_button.configure(state=glossary_action_state)
        self._update_lrr_controls()

    def _set_buttons_busy(self) -> None:
        for button in (self.start_button, self.stop_button, self.restart_button):
            button.configure(state="disabled")

    def _save_settings(self) -> bool:
        self.settings.llama_cpp_folder = self.llama_folder_var.get().strip()
        self.settings.model_folder = self.model_folder_var.get().strip()
        try:
            self.settings.interceptor_enabled = self.interceptor_enabled_var.get()
            self.settings.interceptor_host = self.interceptor_host_var.get().strip()
            self.settings.interceptor_port = int(self.interceptor_port_var.get())
            self.store.save(self.settings)
            self._update_endpoint_labels()
            return True
        except (ValidationError, ValueError) as exc:
            self._show_error(str(exc))
            return False

    def _restore_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.profiles = ProfileService(settings)
        self.glossaries = GlossaryService(settings)
        self.llama_folder_var.set(settings.llama_cpp_folder)
        self.model_folder_var.set(settings.model_folder)
        self.interceptor_enabled_var.set(settings.interceptor_enabled)
        self.interceptor_host_var.set(settings.interceptor_host)
        self.interceptor_port_var.set(str(settings.interceptor_port))
        self._update_endpoint_labels()
        self._refresh_glossary_choices(select=settings.selected_glossary_id)
        self._refresh_profile_choices(select=settings.selected_profile)
        self._refresh_models(show_errors=False)
        if self.profile_choice_var.get():
            self._load_profile(self.profile_choice_var.get())
        else:
            self._new_profile(prompt=False)

    def _restore_after_failed_save(self, settings: AppSettings) -> None:
        message = self.error_var.get()
        self._restore_settings(settings)
        self._show_error(message)

    def _show_error(self, message: str) -> None:
        self.error_var.set(message)
        self.error_label.configure(text_color=PALETTE["error"])
        self.detail_var.set(message)

    def _show_message(self, message: str) -> None:
        self.error_var.set(message)
        self.error_label.configure(text_color=PALETTE["muted"])

    def _request_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if not self.manager.is_active:
            self.root.destroy()
            return
        self.detail_var.set("Stopping llama.cpp before closing…")
        self._set_buttons_busy()

        def worker() -> None:
            try:
                self.manager.close(timeout_seconds=self.settings.shutdown_timeout_seconds)
            finally:
                self.ui_events.put(("closed", None))

        threading.Thread(target=worker, name="ui-close", daemon=True).start()


def main() -> None:
    root = ctk.CTk()
    LauncherApp(root)
    root.mainloop()
