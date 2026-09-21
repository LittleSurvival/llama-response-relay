from __future__ import annotations

from pathlib import Path
import json
import queue
import sys
import threading
import time

from PyQt6.QtCore import QPoint, QSettings, QTimer, Qt
from PyQt6.QtWidgets import QApplication, QFrame, QMessageBox

from llamacpp_launcher.models import (
    AppSettings,
    Glossary,
    GlossaryEntry,
    Profile,
)
from llamacpp_launcher.hardware import (
    CpuSample,
    GpuSample,
    HardwareSnapshot,
    MetricReading,
)
from llamacpp_launcher.process import RuntimeEvent, RuntimeState
from llamacpp_launcher.qt_ui.bridge import RuntimeBridge
from llamacpp_launcher.qt_ui.app import _run_packaged_smoke
from llamacpp_launcher.qt_ui.components import (
    ModernButton,
    ModernComboBox,
    ModernSpinBox,
    NameDialog,
    SmoothSwitch,
)
from llamacpp_launcher.qt_ui.crash_handler import CrashHandler, CrashLogDialog
from llamacpp_launcher.qt_ui.lrr_page import LrrPage
from llamacpp_launcher.qt_ui.hardware_dashboard import DonutGauge, HardwareDashboard
from llamacpp_launcher.qt_ui.presentation import (
    context_per_slot_text,
    control_states,
    endpoint_text,
    per_active_slot_rate,
    profile_from_values,
)
from llamacpp_launcher.qt_ui.runtime_page import RuntimePage
from llamacpp_launcher.qt_ui.settings_page import SettingsPage
from llamacpp_launcher.qt_ui.window import LauncherWindow
from llamacpp_launcher.qt_ui.style import application_icon
from llamacpp_launcher.storage import SettingsStore
from llamacpp_launcher.telemetry import (
    Availability,
    ChartSample,
    DashboardSnapshot,
    RequestSummary,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.events: queue.Queue[RuntimeEvent] = queue.Queue(maxsize=2000)
        self.state = RuntimeState.STOPPED
        self.active_profile = ""
        self.is_active = False
        self.dashboard_snapshot = None
        self.closed = 0

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        del timeout_seconds
        self.state = RuntimeState.STOPPED
        self.is_active = False

    def close(self, *, timeout_seconds: float = 10.0) -> None:
        self.stop(timeout_seconds=timeout_seconds)
        self.closed += 1


class FakeHardwareCollector:
    def __init__(self) -> None:
        self.callback = lambda _snapshot: None
        self.resume_calls = 0
        self.suspend_calls = 0
        self.sample_requests = 0
        self.stop_calls = 0

    def resume(self) -> None:
        self.resume_calls += 1

    def suspend(self) -> None:
        self.suspend_calls += 1

    def request_sample(self) -> None:
        self.sample_requests += 1

    def stop(self) -> None:
        self.stop_calls += 1


def sample_snapshot(
    *,
    metrics_state: Availability = Availability.AVAILABLE,
    slots_state: Availability = Availability.AVAILABLE,
    stopped: bool = False,
) -> DashboardSnapshot:
    history = tuple(
        ChartSample(
            uptime_seconds=float(index),
            prompt_tokens_per_second=10.0 + index,
            generated_tokens_per_second=20.0 + index,
            slot_occupancy=0.5,
            deferred_requests=index % 2,
        )
        for index in range(4)
    )
    return DashboardSnapshot(
        generation=1,
        profile_name="novelia",
        uptime_seconds=65.0,
        total_slots=4,
        active_slots=2,
        slot_occupancy=0.5,
        deferred_requests=1,
        session_prompt_tokens=120,
        session_generated_tokens=80,
        average_prompt_tokens_per_second=11.5,
        average_generated_tokens_per_second=22.5,
        current_prompt_tokens_per_second=13.0,
        current_generated_tokens_per_second=23.0,
        metrics_state=metrics_state,
        slots_state=slots_state,
        latest_request=RequestSummary(
            endpoint="/v1/completions",
            status=200,
            input_tokens=30,
            generated_tokens=20,
            cached_tokens=15,
            prompt_ms=20,
            generated_ms=50,
            time_to_first_byte_ms=32,
            end_to_end_ms=88,
        ),
        history=history,
        stopped=stopped,
    )


def hardware_snapshot(*, gpu_count: int = 2) -> HardwareSnapshot:
    gpus = tuple(
        GpuSample(
            identifier=f"gpu-{index}",
            vendor=("NVIDIA", "AMD", "Intel")[index % 3],
            name=f"Test GPU {index}",
            utilization=MetricReading.number(40 + index),
            frequency_mhz=MetricReading.number(2200 + index * 100),
            vram_used_bytes=MetricReading.number((index + 1) * 1024**3),
            vram_total_bytes=MetricReading.number(8 * 1024**3),
            temperature_c=MetricReading.number(60 + index),
            source="fake",
        )
        for index in range(gpu_count)
    )
    return HardwareSnapshot(
        timestamp=time.monotonic(),
        cpu=CpuSample(
            utilization=MetricReading.number(35),
            frequency_mhz=MetricReading.number(4300),
            process_utilization=MetricReading.number(12),
        ),
        gpus=gpus,
    )


def test_presentation_helpers_cover_states_and_legacy_values() -> None:
    stopped = control_states(
        RuntimeState.STOPPED, has_profile=True, process_active=False
    )
    assert stopped.start and not stopped.stop and not stopped.restart
    starting = control_states(
        RuntimeState.STARTING, has_profile=True, process_active=True
    )
    assert not starting.start and starting.stop and starting.restart
    assert context_per_slot_text(8192, 4) == "≈ 2,048 context per slot (8,192 ÷ 4)"
    assert context_per_slot_text(8192, 1) == ""
    assert endpoint_text("0.0.0.0", 8081) == "http://127.0.0.1:8081"
    assert endpoint_text("127.0.0.1", 8081, enabled=False).startswith("Unavailable")
    assert per_active_slot_rate(80.0, 4) == 20.0
    assert per_active_slot_rate(80.0, 0) is None
    assert per_active_slot_rate(None, 4) is None
    profile = profile_from_values(
        name=" Old Profile ",
        model_path="C:/models/a.gguf",
        host="127.0.0.1",
        port="8080",
        ngl="42",
        context_size="8192",
        parallel_slots="4",
        flash_attention="auto",
        no_mmap=True,
        gpu_mode="multi",
        custom_args="--threads 8",
    )
    assert profile.name == "Old Profile"
    assert profile.parallel_slots == 4


def _accept_name_dialog(value: str) -> None:
    dialog = QApplication.activeModalWidget()
    assert isinstance(dialog, NameDialog)
    dialog.entry.setText(value)
    dialog._accept()


def test_settings_page_profile_crud_and_context_hint(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    llama = tmp_path / "llama"
    models = tmp_path / "models"
    llama.mkdir()
    models.mkdir()
    (llama / "llama-server.exe").write_bytes(b"exe")
    model = models / "novelia.gguf"
    model.write_bytes(b"gguf")
    settings = AppSettings(
        llama_cpp_folder=str(llama),
        model_folder=str(models),
    )
    store = SettingsStore(tmp_path / "settings.json")
    page = SettingsPage(settings, store)
    qtbot.addWidget(page)
    page.show()
    QTimer.singleShot(0, lambda: _accept_name_dialog("novelia"))
    qtbot.mouseClick(page.new_button, Qt.MouseButton.LeftButton)
    assert page.profile_list.currentItem().text() == "novelia"
    assert page.profile_list.count() == 1
    assert settings.profiles == []
    page.apply_models([model.resolve()])
    page.llama_path.edit.setText(str(llama))
    page.model_folder.edit.setText(str(models))
    page.context_spin.setValue(8192)
    page.parallel_spin.setValue(4)
    assert "2,048" in page.context_hint.text()
    qtbot.mouseClick(page.save_button, Qt.MouseButton.LeftButton)
    assert settings.selected_profile == "novelia"
    QTimer.singleShot(0, lambda: _accept_name_dialog("novelia 2"))
    qtbot.mouseClick(page.rename_button, Qt.MouseButton.LeftButton)
    assert settings.selected_profile == "novelia 2"
    qtbot.mouseClick(page.copy_button, Qt.MouseButton.LeftButton)
    assert len(settings.profiles) == 2
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    qtbot.mouseClick(page.delete_button, Qt.MouseButton.LeftButton)
    assert len(settings.profiles) == 1


def test_new_profile_draft_renames_and_deletes_in_rail(
    qtbot, tmp_path: Path
) -> None:
    settings = AppSettings()
    page = SettingsPage(
        settings,
        SettingsStore(tmp_path / "settings.json"),
    )
    qtbot.addWidget(page)
    page.show()
    page.new_profile("Draft profile")
    assert page.profile_list.currentItem().text() == "Draft profile"
    page.rename_profile("Renamed draft")
    assert page.profile_list.currentItem().text() == "Renamed draft"
    assert page.heading.text() == "Renamed draft"
    assert settings.profiles == []
    page.delete_profile(confirm=False)
    assert page.profile_list.count() == 0
    assert page._draft_profile_name == ""


def test_switching_away_discards_unsaved_profile_draft_without_stale_item(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    model = tmp_path / "saved.gguf"
    model.write_bytes(b"gguf")
    saved = Profile(name="Saved", model_path=str(model))
    settings = AppSettings(
        profiles=[saved],
        selected_profile=saved.name,
    )
    page = SettingsPage(
        settings,
        SettingsStore(tmp_path / "settings.json"),
    )
    qtbot.addWidget(page)
    page.show()
    page.new_profile("Temporary")
    assert page.profile_list.count() == 2
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    page.profile_list.setCurrentRow(0)
    assert page.profile_list.count() == 1
    assert page.profile_list.currentItem().text() == "Saved"
    assert page.heading.text() == "Saved"
    assert page._draft_profile_name == ""


def test_lrr_glossary_is_independent_and_entries_are_compact(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    settings = AppSettings()
    store = SettingsStore(tmp_path / "settings.json")
    page = LrrPage(settings, store)
    qtbot.addWidget(page)
    page.show()
    page.enabled.setChecked(True)
    page.host.setText("127.0.0.1")
    page.port.setValue(9090)
    qtbot.mouseClick(page.save_lrr_button, Qt.MouseButton.LeftButton)
    QTimer.singleShot(0, lambda: _accept_name_dialog("Travel"))
    qtbot.mouseClick(page.new_button, Qt.MouseButton.LeftButton)
    assert settings.selected_glossary_id
    assert page.glossary_list.currentItem().text() == "Travel"
    qtbot.mouseClick(page.add_button, Qt.MouseButton.LeftButton)
    assert len(page.rows) == 2
    row = page.rows[0]
    row.source.setText("旅人")
    row.replacement.setText("Traveler")
    page.rows[1].source.setText("日記")
    page.rows[1].replacement.setText("Journal")
    assert row.maximumHeight() <= 48
    assert row.enabled.isChecked()
    qtbot.mouseClick(page.save_glossary_button, Qt.MouseButton.LeftButton)
    glossary = settings.glossaries[0]
    assert glossary.entries[0].case_sensitive is True
    assert not hasattr(settings.profiles, "glossary")
    QTimer.singleShot(0, lambda: _accept_name_dialog("Travel Notes"))
    qtbot.mouseClick(page.rename_button, Qt.MouseButton.LeftButton)
    assert settings.glossaries[0].name == "Travel Notes"
    assert page.glossary_heading.text() == "Travel Notes"
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    qtbot.mouseClick(page.delete_button, Qt.MouseButton.LeftButton)
    assert settings.glossaries == []


def test_glossary_switch_autosaves_and_keeps_editor_aligned(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    first = Glossary(
        name="First",
        entries=[GlossaryEntry(source="A", replacement="Old")],
    )
    second = Glossary(
        name="Second",
        entries=[GlossaryEntry(source="B", replacement="Two")],
    )
    settings = AppSettings(
        glossaries=[first, second],
        selected_glossary_id=first.id,
    )
    page = LrrPage(
        settings,
        SettingsStore(tmp_path / "settings.json"),
    )
    qtbot.addWidget(page)
    page.show()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Glossary switching must not show a dialog")
        ),
    )

    page.rows[0].replacement.setText("Autosaved")
    page.add_entry()
    page.glossary_list.setCurrentRow(1)
    assert settings.glossaries[0].entries[0].replacement == "Autosaved"
    assert len(settings.glossaries[0].entries) == 1
    assert settings.selected_glossary_id == second.id
    assert page.glossary_list.currentItem().text() == "Second"
    assert page.glossary_heading.text() == "Second"
    assert page.rows[0].source.text() == "B"

    page.glossary_list.setCurrentRow(0)
    invalid = page.add_entry()
    invalid.replacement.setText("Missing source")
    page.glossary_list.setCurrentRow(1)
    assert settings.selected_glossary_id == first.id
    assert page.glossary_list.currentItem().text() == "First"
    assert page.glossary_heading.text() == "First"
    assert "source text is required" in page.glossary_error.text().lower()


def test_runtime_bridge_batches_600_logs_and_coalesces_telemetry(qtbot) -> None:
    runtime = FakeRuntime()
    bridge = RuntimeBridge(runtime, max_events_per_tick=120, interval_ms=1000)
    bridge.timer.stop()
    batches: list[str] = []
    snapshots: list[DashboardSnapshot] = []
    bridge.logs_ready.connect(lambda lines: batches.extend(lines))
    bridge.telemetry_ready.connect(snapshots.append)
    for index in range(600):
        runtime.events.put_nowait(
            RuntimeEvent(kind="log", source="stderr", message=f"line {index}")
        )
    first = sample_snapshot()
    second = sample_snapshot(stopped=True)
    runtime.events.put_nowait(
        RuntimeEvent(kind="telemetry", message="first", payload=first)
    )
    runtime.events.put_nowait(
        RuntimeEvent(kind="telemetry", message="second", payload=second)
    )
    bridge.drain()
    qtbot.waitUntil(lambda: len(batches) == 600, timeout=3000)
    qtbot.waitUntil(lambda: len(snapshots) == 1, timeout=3000)
    assert snapshots[0].stopped


def test_runtime_page_renders_states_logs_and_minimum_dashboard(qtbot) -> None:
    page = RuntimePage()
    qtbot.addWidget(page)
    page.resize(760, 580)
    page.show()
    page.render_snapshot(sample_snapshot())
    page.append_logs([f"line {index}" for index in range(650)])
    assert "2 / 4" in page.slots.value.text()
    assert page.generation.value.text() == "All-slot 23.0 tok/s"
    assert page.generation.detail.text() == "Per-active-slot avg 11.5 tok/s"
    assert "Latest client task" in page.latest.text()
    assert page.throughput_chart.property("framed") is True
    assert page.pressure_chart.property("framed") is True
    assert page.dashboard.height() == 230
    assert page.dashboard.height() <= int(page.height() * 0.40)
    page.render_snapshot(
        sample_snapshot(
            metrics_state=Availability.UNSUPPORTED,
            slots_state=Availability.STALE,
            stopped=True,
        )
    )
    assert page.generation.value.text() == "Unsupported"
    assert page.slots.value.text() == "Stale"
    assert page.output.document().blockCount() <= 2000


def test_hardware_dashboard_renders_donuts_text_and_multi_gpu_overflow(
    qtbot, tmp_path: Path
) -> None:
    settings = QSettings(
        str(tmp_path / "presentation.ini"), QSettings.Format.IniFormat
    )
    dashboard = HardwareDashboard(settings=settings)
    qtbot.addWidget(dashboard)
    dashboard.resize(720, 190)
    dashboard.show()
    dashboard.set_snapshot(hardware_snapshot(gpu_count=3))
    qtbot.wait(20)

    assert dashboard.cpu_card.usage.accessibleDescription() == "CPU usage: 35%"
    assert "4.30 GHz" in dashboard.cpu_card.frequency.text()
    assert "12%" in dashboard.cpu_card.process.text()
    assert len(dashboard._gpu_cards) == 3
    first = dashboard._gpu_cards["gpu-0"]
    assert isinstance(first.usage, DonutGauge)
    assert first.usage.accessibleDescription() == "GPU usage: 40%"
    assert "1.0 / 8.0 GiB" in first.memory.text()
    assert "60 °C" in first.temperature.text()
    assert dashboard.scroll.horizontalScrollBar().maximum() > 0

    unavailable = hardware_snapshot(gpu_count=1)
    missing = GpuSample("gpu-x", "Intel", "Partial GPU")
    dashboard.set_snapshot(
        HardwareSnapshot(unavailable.timestamp, unavailable.cpu, (missing,))
    )
    assert (
        dashboard._gpu_cards["gpu-x"].usage.accessibleDescription()
        == "GPU usage: —"
    )
    assert "Unavailable" in dashboard._gpu_cards["gpu-x"].temperature.text()
    dashboard.set_snapshot(
        HardwareSnapshot(time.monotonic() - 4, unavailable.cpu, ())
    )
    assert dashboard.no_gpu.isVisible()
    dashboard._refresh_stale_state()
    assert dashboard.status.text() == "Stale"


def test_hardware_dashboard_collapse_persists_and_requests_refresh(
    qtbot, tmp_path: Path
) -> None:
    settings = QSettings(
        str(tmp_path / "presentation.ini"), QSettings.Format.IniFormat
    )
    first = HardwareDashboard(settings=settings)
    qtbot.addWidget(first)
    refreshes: list[bool] = []
    first.refresh_requested.connect(lambda: refreshes.append(True))
    first.set_expanded(False)
    assert first.height() == 44
    assert not first.scroll.isVisible()
    first.set_expanded(True)
    assert refreshes == [True]
    assert first.height() == 190

    restored = HardwareDashboard(settings=settings)
    qtbot.addWidget(restored)
    assert restored.expanded
    restored.set_expanded(False)
    reloaded = HardwareDashboard(settings=settings)
    qtbot.addWidget(reloaded)
    assert not reloaded.expanded


def test_runtime_page_hardware_layout_preserves_output_and_device_widgets(
    qtbot, tmp_path: Path
) -> None:
    settings = QSettings(
        str(tmp_path / "presentation.ini"), QSettings.Format.IniFormat
    )
    page = RuntimePage(presentation_settings=settings)
    qtbot.addWidget(page)
    page.resize(960, 608)
    page.show()
    page.render_hardware_snapshot(hardware_snapshot(gpu_count=3))
    qtbot.wait(20)
    original_cards = dict(page.hardware_dashboard._gpu_cards)
    page.render_hardware_snapshot(hardware_snapshot(gpu_count=3))
    assert page.hardware_dashboard._gpu_cards == original_cards
    assert page.output.height() >= 40
    for width, height in ((960, 608), (1100, 700), (980, 640), (1180, 720)):
        page.resize(width, height)
        qtbot.wait(2)
    assert page.dashboard.geometry().bottom() < (
        page.hardware_dashboard.geometry().top()
    )
    assert (
        page.hardware_dashboard.geometry().bottom()
        < page.output_card.geometry().top()
    )


def test_window_uses_three_qt_pages_and_resizes_under_load(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LRR_DISABLE_ANIMATIONS", "1")
    runtime = FakeRuntime()
    window = LauncherWindow(
        store=SettingsStore(tmp_path / "settings.json"), runtime=runtime
    )
    qtbot.addWidget(window)
    window.show()
    assert window.minimumSize().width() == 960
    assert window.minimumSize().height() == 640
    assert window.stack.count() == 3
    assert not window.windowIcon().isNull()
    assert all(isinstance(button, ModernButton) for button in window.nav_buttons)
    window.switch_page(2)
    assert window.stack.currentWidget().graphicsEffect() is None
    started = time.perf_counter()
    for index in range(150):
        window.switch_page(index % 3)
    assert time.perf_counter() - started < 1.0
    assert all(
        window.stack.widget(index).graphicsEffect() is None
        for index in range(window.stack.count())
    )
    for index in range(600):
        runtime.events.put_nowait(
            RuntimeEvent(kind="log", source="stdout", message=str(index))
        )
    runtime.events.put_nowait(
        RuntimeEvent(kind="telemetry", message="snapshot", payload=sample_snapshot())
    )
    for width, height in ((960, 640), (1100, 700), (1000, 660), (1180, 760)):
        window.resize(width, height)
        qtbot.wait(5)
    qtbot.waitUntil(
        lambda: "599" in window.runtime_page.output.toPlainText(), timeout=3000
    )
    assert window.runtime_page.dashboard.geometry().bottom() < (
        window.runtime_page.output.geometry().bottom()
    )


def test_window_suspends_and_resumes_hardware_collection_with_page(
    qtbot, tmp_path: Path
) -> None:
    hardware = FakeHardwareCollector()
    window = LauncherWindow(
        store=SettingsStore(tmp_path / "settings.json"),
        runtime=FakeRuntime(),
        hardware_collector=hardware,  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    window.show()
    window.switch_page(2)
    assert hardware.resume_calls == 1
    window.runtime_page.hardware_dashboard.set_expanded(False)
    window.runtime_page.hardware_dashboard.set_expanded(True)
    assert hardware.sample_requests == 1
    window.switch_page(0)
    assert hardware.suspend_calls == 1
    window.close()
    assert hardware.stop_calls == 1


def test_close_is_idempotent_and_async_for_active_runtime(
    qtbot, tmp_path: Path
) -> None:
    runtime = FakeRuntime()
    runtime.is_active = True
    runtime.state = RuntimeState.READY
    runtime.active_profile = "running"
    window = LauncherWindow(
        store=SettingsStore(tmp_path / "settings.json"), runtime=runtime
    )
    qtbot.addWidget(window)
    window.show()
    window.close()
    window.close()
    qtbot.waitUntil(lambda: runtime.closed == 1, timeout=3000)
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=3000)


def test_keyboard_focus_and_accessible_names(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LRR_DISABLE_ANIMATIONS", "1")
    page = LrrPage(AppSettings(glossaries=[Glossary(name="Terms")]), SettingsStore(tmp_path / "s.json"))
    qtbot.addWidget(page)
    page.show()
    page.new_button.setFocus()
    qtbot.keyClick(page.new_button, Qt.Key.Key_Tab)
    assert page.focusWidget() is not None
    row = page.add_entry()
    assert row.remove.accessibleName() == "Remove glossary entry"
    assert isinstance(row.enabled, SmoothSwitch)
    row.enabled.setChecked(True)
    assert row.enabled.get_thumb_position() == 1.0
    assert page.glossary_list.accessibleName() == "Saved glossaries"
    assert isinstance(page.port, ModernSpinBox)


def test_modern_selector_popup_opens_below_select_bar(qtbot) -> None:
    combo = ModernComboBox()
    combo.addItems([f"Option {index}" for index in range(30)])
    combo.resize(240, 36)
    combo.move(40, 40)
    qtbot.addWidget(combo)
    combo.show()
    combo.showPopup()
    qtbot.wait(20)
    popup = combo.view().window()
    select_bottom = combo.mapToGlobal(QPoint(0, combo.height())).y()
    assert popup.geometry().top() >= select_bottom
    assert popup.geometry().width() >= combo.width()
    assert isinstance(popup, QFrame)
    assert popup.frameShape() is QFrame.Shape.NoFrame
    assert popup.contentsMargins().isNull()
    row_height = combo.view().sizeHintForRow(0) + combo.view().spacing() * 2
    assert popup.height() >= row_height * 10
    assert combo.view().verticalScrollBar().isVisible()
    combo.hidePopup()


def test_application_icon_uses_bundled_blue_asset() -> None:
    icon_path = (
        Path(__file__).resolve().parents[1]
        / "assets"
        / "LlamaCppLauncher.ico"
    )
    assert icon_path.is_file()
    assert not application_icon().isNull()


def test_crash_handler_shows_copyable_log_without_closing_app(qtbot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    host = QFrame()
    host.setWindowTitle("Still running")
    qtbot.addWidget(host)
    host.show()
    handler = CrashHandler(app)
    try:
        raise RuntimeError("profile click exploded")
    except RuntimeError:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        assert exc_type is not None and exc_value is not None
        handler.handle_exception(exc_type, exc_value, exc_traceback)
    qtbot.waitUntil(lambda: bool(handler._dialogs), timeout=1000)
    dialog = handler._dialogs[0]
    assert isinstance(dialog, CrashLogDialog)
    assert "RuntimeError: profile click exploded" in dialog.log_view.toPlainText()
    qtbot.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
    assert "profile click exploded" in QApplication.clipboard().text()
    dialog.reject()
    qtbot.waitUntil(lambda: not handler._dialogs, timeout=1000)
    assert host.isVisible()


def test_crash_handler_forwards_worker_thread_failure(qtbot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    handler = CrashHandler(app)
    handler.install()
    try:
        def fail_in_worker() -> None:
            raise ValueError("worker exploded")

        worker = threading.Thread(
            target=fail_in_worker,
            name="Crash test worker",
        )
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive()
        qtbot.waitUntil(lambda: bool(handler._dialogs), timeout=1000)
        log = handler._dialogs[0].log_view.toPlainText()
        assert "Thread: Crash test worker" in log
        assert "ValueError: worker exploded" in log
        handler._dialogs[0].reject()
    finally:
        handler.uninstall()


def test_packaged_smoke_hook_navigates_and_persists(qtbot, tmp_path: Path) -> None:
    window = LauncherWindow(
        store=SettingsStore(tmp_path / "data" / "settings.json"),
        runtime=FakeRuntime(),
    )
    qtbot.addWidget(window)
    window.show()
    result = tmp_path / "smoke.json"
    _run_packaged_smoke(window, result)
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload == {
        "ok": True,
        "pages": [0, 1, 2],
        "profile": "Packaged Smoke",
        "glossary": "Packaged Terms",
        "hardware_provider_assets": True,
    }
