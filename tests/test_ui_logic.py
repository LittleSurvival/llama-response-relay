from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import customtkinter as ctk
import pytest

from llamacpp_launcher.dashboard_widgets import series_stats
from llamacpp_launcher.models import AppSettings, Glossary, ValidationError
from llamacpp_launcher.process import RuntimeEvent, RuntimeState
from llamacpp_launcher.storage import SettingsStore
from llamacpp_launcher.telemetry import (
    Availability,
    ChartSample,
    DashboardSnapshot,
    RequestSummary,
)
from llamacpp_launcher.theme import PALETTE
from llamacpp_launcher.ui import (
    LauncherApp,
    context_per_slot_text,
    control_states,
    suggest_profile_name,
    validate_profile_name,
)


@pytest.fixture(scope="module")
def tk_parent() -> ctk.CTk:
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


def ui_window(parent: ctk.CTk) -> ctk.CTkToplevel:
    window = ctk.CTkToplevel(parent)
    window.withdraw()
    return window


def test_stopped_controls_allow_start_and_edit() -> None:
    states = control_states(RuntimeState.STOPPED, has_profile=True)
    assert states == {"start": True, "stop": False, "restart": False, "edit": True}


def test_starting_controls_keep_stop_available() -> None:
    states = control_states(RuntimeState.STARTING, has_profile=True)
    assert states["stop"]
    assert not states["start"]
    assert not states["edit"]


def test_stopping_disables_lifecycle_actions() -> None:
    states = control_states(RuntimeState.STOPPING, has_profile=True)
    assert not states["start"]
    assert not states["stop"]
    assert not states["restart"]


def test_theme_has_distinct_semantic_colors() -> None:
    assert len({PALETTE["accent"], PALETTE["success"], PALETTE["warning"], PALETTE["error"]}) == 4
    assert PALETTE["window"] != PALETTE["surface"]


def test_chart_stats_ignore_gaps_and_keep_latest_and_peak() -> None:
    assert series_stats([None, 2, None, 5, 3]) == (3, 5)
    assert series_stats([None]) == (None, None)


def test_profile_name_flow_suggests_and_validates_unique_names() -> None:
    assert suggest_profile_name([]) == "New profile"
    assert suggest_profile_name(["New profile", "New profile 2"]) == "New profile 3"
    assert validate_profile_name("  Pink  ", ["Other"]) == "Pink"
    with pytest.raises(ValidationError, match="already in use"):
        validate_profile_name("pink", ["Pink"])


def test_context_per_slot_hint_only_appears_for_multiple_slots() -> None:
    assert context_per_slot_text("8192", "4") == (
        "Each slot gets 2,048 context (8,192 ÷ 4)"
    )
    assert context_per_slot_text("4096", "3") == (
        "Each slot gets ~1,365.3 context (4,096 ÷ 3)"
    )
    assert context_per_slot_text("4096", "1") == ""
    assert context_per_slot_text("invalid", "2") == ""


def test_ui_refreshes_models_and_saves_profile(
    tmp_path: Path, tk_parent: ctk.CTk
) -> None:
    llama_folder = tmp_path / "llama"
    model_folder = tmp_path / "models"
    llama_folder.mkdir()
    model_folder.mkdir()
    (llama_folder / "llama-server.exe").touch()
    model = model_folder / "pink.gguf"
    model.touch()
    root = ui_window(tk_parent)
    try:
        app = LauncherApp(root, store=SettingsStore(tmp_path / "settings.json"))
        app.llama_folder_var.set(str(llama_folder))
        app.model_folder_var.set(str(model_folder))
        app.settings.llama_cpp_folder = str(llama_folder)
        app.settings.model_folder = str(model_folder)
        app._refresh_models()
        app.name_var.set("Pink")
        app.model_var.set(model.name)
        app._save_profile()

        assert app.profiles.names() == ["Pink"]
        assert app.profiles.get("Pink").model_path == str(model.resolve())
        assert (tmp_path / "settings.json").exists()
        app.context_var.set("8192")
        app.parallel_var.set("4")
        assert app.context_allocation_var.get() == (
            "Each slot gets 2,048 context (8,192 ÷ 4)"
        )
    finally:
        root.destroy()


def test_ui_switches_to_roomy_runtime_workspace(
    tmp_path: Path, tk_parent: ctk.CTk
) -> None:
    root = ui_window(tk_parent)
    try:
        app = LauncherApp(root, store=SettingsStore(tmp_path / "settings.json"))
        root.geometry("960x640")
        root.update()
        app._switch_view("Runtime")
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and app.settings_view.place_info():
            root.update()
            time.sleep(0.01)

        assert app._current_view == "Runtime"
        assert app.runtime_view.winfo_manager() == "place"
        assert app.settings_view.place_info() == {}
        assert app.stop_button.winfo_exists()
        assert int(app.runtime_dashboard.cget("height")) <= 640 * 0.40
        assert app.runtime_view.grid_rowconfigure(1)["weight"] == 1
        assert app.log_text.winfo_exists()
    finally:
        root.destroy()


def test_runtime_dashboard_renders_active_stale_and_stopped_snapshots(
    tmp_path: Path, tk_parent: ctk.CTk
) -> None:
    root = ui_window(tk_parent)
    try:
        app = LauncherApp(root, store=SettingsStore(tmp_path / "settings.json"))
        snapshot = DashboardSnapshot(
            generation=1,
            profile_name="Pink",
            uptime_seconds=65,
            total_slots=4,
            active_slots=3,
            slot_occupancy=0.75,
            deferred_requests=2,
            session_prompt_tokens=1200,
            session_generated_tokens=345,
            average_prompt_tokens_per_second=40,
            average_generated_tokens_per_second=12,
            current_prompt_tokens_per_second=50,
            current_generated_tokens_per_second=15,
            metrics_state=Availability.AVAILABLE,
            slots_state=Availability.STALE,
            latest_request=RequestSummary(
                endpoint="/v1/chat/completions",
                status=200,
                input_tokens=100,
                generated_tokens=40,
                cached_tokens=25,
                prompt_ms=100,
                generated_ms=500,
                time_to_first_byte_ms=80,
                end_to_end_ms=650,
            ),
            history=(
                ChartSample(64, 45, 14, 0.5, 0),
                ChartSample(65, 50, 15, 0.75, 2),
            ),
        )
        app.status_var.set(RuntimeState.READY.value)
        app._handle_runtime_event(
            RuntimeEvent(
                kind="telemetry", message="", payload=snapshot, generation=1
            )
        )

        assert app.runtime_identity_var.get() == "Pink · Ready · 01:05"
        assert app.token_rate_var.get() == "15.0 tok/s"
        assert app.slot_pressure_var.get() == "3/4 · 75%"
        assert app.queue_var.get() == "2"
        assert app.session_tokens_var.get() == "In 1.2K · Out 345"
        assert "Cache 25%" in app.latest_task_var.get()
        assert "Server 600ms" in app.latest_task_var.get()
        assert "Slots Stale" in app.telemetry_health_var.get()

        unsupported = replace(
            snapshot,
            active_slots=None,
            slot_occupancy=None,
            deferred_requests=None,
            current_generated_tokens_per_second=None,
            metrics_state=Availability.UNSUPPORTED,
            slots_state=Availability.UNSUPPORTED,
            history=(),
        )
        app._render_dashboard(unsupported)
        assert app.token_rate_var.get() == "Unsupported"
        assert app.slot_pressure_var.get() == "Unsupported"
        assert app.queue_var.get() == "Unsupported"

        stopped = replace(snapshot, active_slots=0, stopped=True)
        app._render_dashboard(stopped)
        assert "Stopped" in app.runtime_identity_var.get()
        assert app.telemetry_health_var.get() == "Telemetry stopped · final snapshot"
    finally:
        root.destroy()


def test_ui_saves_and_selects_global_glossary(
    tmp_path: Path, tk_parent: ctk.CTk
) -> None:
    model_folder = tmp_path / "models"
    model_folder.mkdir()
    model = model_folder / "pink.gguf"
    model.touch()
    root = ui_window(tk_parent)
    try:
        app = LauncherApp(root, store=SettingsStore(tmp_path / "settings.json"))
        app.model_folder_var.set(str(model_folder))
        app.settings.model_folder = str(model_folder)
        app._refresh_models()

        app.original_glossary_id = ""
        app.glossary_name_var.set("Terms")
        app._render_glossary_rows([])
        app._add_glossary_row()
        app.glossary_rows[0]["source"].set("llama")  # type: ignore[union-attr]
        app.glossary_rows[0]["replacement"].set("羊駝")  # type: ignore[union-attr]
        app._save_glossary()

        glossary = app.glossaries.get("Terms")
        assert glossary.entries[0].replacement == "羊駝"
        assert app.settings.selected_glossary_id == glossary.id
        assert app.glossary_choice_var.get() == "Terms"
        assert not hasattr(app, "assignment_glossary_combo")
        assert not hasattr(app, "profile_glossary_combo")

        app.name_var.set("Pink")
        app.model_var.set(model.name)
        app._save_profile()

        persisted = SettingsStore(tmp_path / "settings.json").load()
        assert persisted.selected_glossary_id == persisted.glossaries[0].id
        assert "glossary_id" not in persisted.profiles[0].to_dict()
    finally:
        root.destroy()


def test_lrr_glossary_selection_and_add_entry_update_editor(
    tmp_path: Path, tk_parent: ctk.CTk
) -> None:
    root = ui_window(tk_parent)
    try:
        app = LauncherApp(root, store=SettingsStore(tmp_path / "settings.json"))
        first = app.glossaries.create(Glossary(name="First"))
        second = app.glossaries.create(Glossary(name="Second"))
        app._refresh_glossary_choices(select=first.id)

        app._select_glossary("Second")
        assert app.original_glossary_id == second.id
        assert app.glossary_name_var.get() == "Second"

        before = len(app.glossary_rows)
        app._add_glossary_row()
        root.update_idletasks()
        assert len(app.glossary_rows) == before + 1
        assert app.glossary_rows[-1]["frame"].grid_info()  # type: ignore[union-attr]
        assert app.glossary_rows[-1]["case_sensitive"].get() is True  # type: ignore[union-attr]
        assert app.glossary_rows[-1]["source"].get() == ""  # type: ignore[union-attr]
        assert app.glossary_rows[-1]["enabled_widget"].grid_info()["column"] == 0  # type: ignore[union-attr]
        assert app.glossary_rows[-1]["remove_widget"].grid_info()["column"] == 4  # type: ignore[union-attr]
        assert int(app.glossary_entries.cget("height")) >= 300
    finally:
        root.destroy()


def test_ui_persists_distinct_lrr_endpoint(
    tmp_path: Path, tk_parent: ctk.CTk
) -> None:
    root = ui_window(tk_parent)
    try:
        path = tmp_path / "settings.json"
        app = LauncherApp(root, store=SettingsStore(path))
        app.interceptor_host_var.set("127.0.0.1")
        app.interceptor_port_var.set("9091")
        app.interceptor_enabled_var.set(False)

        assert app._save_settings()
        saved = SettingsStore(path).load()
        assert saved.interceptor_enabled is False
        assert saved.interceptor_host == "127.0.0.1"
        assert saved.interceptor_port == 9091
        assert "LRR disabled" in app.client_endpoint_var.get()
        assert app.view_switch.cget("values") == ["Settings", "LRR", "Runtime"]
        app._update_lrr_controls()
        assert app.interceptor_host_entry.cget("state") == "disabled"
    finally:
        root.destroy()


def test_ui_rolls_back_profile_when_persistence_fails(
    tmp_path: Path, tk_parent: ctk.CTk
) -> None:
    model_folder = tmp_path / "models"
    model_folder.mkdir()
    model = model_folder / "pink.gguf"
    model.touch()

    class FailingStore(SettingsStore):
        def load(self) -> AppSettings:
            self.last_valid = AppSettings(model_folder=str(model_folder))
            return self.last_valid

        def save(self, _settings: AppSettings) -> None:
            raise ValidationError("disk is locked")

    root = ui_window(tk_parent)
    try:
        app = LauncherApp(root, store=FailingStore(tmp_path / "settings.json"))
        app.model_folder_var.set(str(model_folder))
        app.settings.model_folder = str(model_folder)
        app._refresh_models()
        app.name_var.set("Unsaved")
        app.model_var.set(model.name)
        app._save_profile()

        assert app.profiles.names() == []
        assert "disk is locked" in app.error_var.get()
    finally:
        root.destroy()
