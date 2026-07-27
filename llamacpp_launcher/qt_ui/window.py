from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..command import probe_help
from ..discovery import discover_models, resolve_llama_server
from ..glossaries import GlossaryService
from ..models import AppSettings, ValidationError
from ..process import RuntimeState
from ..runtime import LauncherRuntime
from ..storage import SettingsStore
from .bridge import RuntimeBridge
from .lrr_page import LrrPage
from .presentation import endpoint_text
from .runtime_page import RuntimePage
from .settings_page import SettingsPage
from .components import make_button
from .style import application_icon


class LauncherWindow(QMainWindow):
    def __init__(
        self,
        *,
        store: SettingsStore | None = None,
        runtime: LauncherRuntime | None = None,
    ) -> None:
        super().__init__()
        self.store = store or SettingsStore()
        self.load_error = ""
        try:
            self.settings = self.store.load()
        except ValidationError as exc:
            self.settings = AppSettings()
            self.load_error = str(exc)
        self.runtime = runtime or LauncherRuntime()
        self.bridge = RuntimeBridge(self.runtime, parent=self)
        self._closing = False
        self._allow_close = False
        self._build()
        self._connect()
        self._sync_runtime_controls()
        self._sync_endpoints()
        if self.settings.model_folder:
            self._discover_models(self.settings.model_folder)
        if self.load_error:
            self.statusBar().showMessage(self.load_error)

    def _build(self) -> None:
        self.setWindowTitle("Llama.cpp Launcher")
        self.setWindowIcon(application_icon())
        self.setMinimumSize(960, 640)
        self.resize(1180, 760)
        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(176)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 20, 16, 16)
        sidebar_layout.setSpacing(8)
        brand = QLabel("LLAMA\nRESPONSE RELAY")
        brand.setProperty("role", "section")
        sidebar_layout.addWidget(brand)
        subtitle = QLabel("Launcher + LRR")
        subtitle.setProperty("role", "muted")
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(20)
        self.nav_buttons: list[QPushButton] = []
        for index, text in enumerate(("Settings", "LRR", "Runtime")):
            button = make_button(text)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setAccessibleName(f"Open {text}")
            button.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)
        sidebar_layout.addStretch()
        self.runtime_badge = QLabel("Stopped")
        self.runtime_badge.setProperty("role", "muted")
        sidebar_layout.addWidget(self.runtime_badge)
        layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 16, 18, 16)
        self.stack = QStackedWidget()
        self.settings_page = SettingsPage(self.settings, self.store)
        self.lrr_page = LrrPage(self.settings, self.store)
        self.runtime_page = RuntimePage()
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.lrr_page)
        self.stack.addWidget(self.runtime_page)
        content_layout.addWidget(self.stack)
        layout.addWidget(content, 1)

        self.setStatusBar(QStatusBar())
        self.nav_buttons[0].setChecked(True)

    def _connect(self) -> None:
        self.settings_page.discover_requested.connect(self._discover_models)
        self.settings_page.message.connect(self.statusBar().showMessage)
        self.settings_page.error.connect(self.statusBar().showMessage)
        self.settings_page.selection_changed.connect(self._configuration_changed)
        self.lrr_page.message.connect(self.statusBar().showMessage)
        self.lrr_page.error.connect(self.statusBar().showMessage)
        self.lrr_page.settings_changed.connect(self._configuration_changed)
        self.runtime_page.start_requested.connect(self.start_runtime)
        self.runtime_page.stop_requested.connect(self.stop_runtime)
        self.runtime_page.restart_requested.connect(self.restart_runtime)
        self.bridge.state_changed.connect(self._runtime_state_changed)
        self.bridge.logs_ready.connect(self.runtime_page.append_logs)
        self.bridge.telemetry_ready.connect(self.runtime_page.render_snapshot)
        self.bridge.error.connect(self._background_error)
        self.bridge.work_finished.connect(self._sync_runtime_controls)

    def switch_page(self, index: int) -> None:
        if index < 0 or index >= self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        self.stack.currentWidget().update()
        if index == 2 and self.runtime.dashboard_snapshot is not None:
            self.runtime_page.render_snapshot(self.runtime.dashboard_snapshot)

    def _discover_models(self, folder: str) -> None:
        self.bridge.submit(
            lambda: discover_models(folder),
            on_result=lambda result: self.settings_page.apply_models(list(result)),
        ).signals.error.connect(self.settings_page.discovery_failed)

    def _configuration_changed(self) -> None:
        self._sync_runtime_controls()
        self._sync_endpoints()
        self.lrr_page.refresh_glossaries(select=self.settings.selected_glossary_id)

    def _sync_endpoints(self) -> None:
        profile = None
        if self.settings.selected_profile:
            try:
                profile = self.settings_page.profiles.get(
                    self.settings.selected_profile
                )
            except ValidationError:
                pass
        upstream = (
            endpoint_text(profile.host, profile.port) if profile else "Unavailable"
        )
        client = endpoint_text(
            self.settings.interceptor_host,
            self.settings.interceptor_port,
            enabled=self.settings.interceptor_enabled,
        )
        self.runtime_page.set_endpoints(upstream, client)

    def start_runtime(self) -> None:
        self._run_lifecycle("start")

    def stop_runtime(self) -> None:
        self._run_lifecycle("stop")

    def restart_runtime(self) -> None:
        self._run_lifecycle("restart")

    def _run_lifecycle(self, action: str) -> None:
        if action == "stop":
            self._set_lifecycle_busy()
            self.bridge.submit(
                lambda: self.runtime.stop(
                    timeout_seconds=self.settings.shutdown_timeout_seconds
                )
            )
            return
        if not self.settings_page.save_profile():
            self.switch_page(0)
            return
        if not self.lrr_page.save_lrr():
            self.switch_page(1)
            return
        try:
            profile = self.settings_page.profiles.get(
                self.settings.selected_profile
            )
            profile.validate(self.settings.model_folder, require_files=True)
            executable = resolve_llama_server(self.settings.llama_cpp_folder)
            glossary = GlossaryService(self.settings).snapshot(
                self.settings.selected_glossary_id
            )
        except ValidationError as exc:
            self._show_error(str(exc))
            return
        self._set_lifecycle_busy()
        self.switch_page(2)

        def lifecycle() -> None:
            help_text = probe_help(executable)
            arguments = {
                "interceptor_enabled": self.settings.interceptor_enabled,
                "interceptor_host": self.settings.interceptor_host,
                "interceptor_port": self.settings.interceptor_port,
                "glossary": glossary,
                "startup_timeout_seconds": self.settings.startup_timeout_seconds,
            }
            if action == "start":
                self.runtime.start(executable, profile, help_text, **arguments)
            else:
                self.runtime.restart(
                    executable,
                    profile,
                    help_text,
                    **arguments,
                    shutdown_timeout_seconds=self.settings.shutdown_timeout_seconds,
                )

        self.bridge.submit(lifecycle)

    def _set_lifecycle_busy(self) -> None:
        self.runtime_page.start_button.setEnabled(False)
        self.runtime_page.stop_button.setEnabled(False)
        self.runtime_page.restart_button.setEnabled(False)

    def _runtime_state_changed(self, state: RuntimeState, detail: str) -> None:
        self.runtime_badge.setText(state.value)
        self.runtime_page.set_runtime_state(
            state,
            detail,
            has_profile=bool(self.settings.selected_profile),
            process_active=self.runtime.is_active,
            profile_name=self.runtime.active_profile
            or self.settings.selected_profile,
        )
        self.statusBar().showMessage(detail)

    def _sync_runtime_controls(self) -> None:
        self.runtime_page.set_runtime_state(
            self.runtime.state,
            self.runtime_badge.toolTip(),
            has_profile=bool(self.settings.selected_profile),
            process_active=self.runtime.is_active,
            profile_name=self.runtime.active_profile
            or self.settings.selected_profile,
        )

    def _background_error(self, message: str) -> None:
        self.statusBar().showMessage(message)
        if not self._closing:
            self._show_error(message)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Llama.cpp Launcher", message)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._allow_close or not self.runtime.is_active:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self.setEnabled(False)
        self.statusBar().showMessage("Stopping owned services…")
        worker = self.bridge.submit(
            lambda: self.runtime.close(
                timeout_seconds=self.settings.shutdown_timeout_seconds
            )
        )
        worker.signals.finished.connect(self._finish_close)

    def _finish_close(self) -> None:
        self._allow_close = True
        self.close()
