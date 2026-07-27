from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..process import RuntimeState
from ..telemetry import (
    Availability,
    DashboardSnapshot,
    format_count,
    format_duration,
    format_ms,
    format_percent,
    format_rate,
)
from .charts import CompactChart
from .components import card, make_button, section_header
from .presentation import control_states, per_active_slot_rate


class MetricCard(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = card(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(1)
        self.title = QLabel(title)
        self.title.setProperty("role", "muted")
        self.value = QLabel("—")
        self.value.setProperty("role", "section")
        self.detail = QLabel("")
        self.detail.setProperty("role", "muted")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)
        self.setMinimumHeight(56)
        self.setMaximumHeight(58)

    def set_values(self, value: str, detail: str = "") -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class RuntimePage(QWidget):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    restart_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.dashboard, dashboard_layout = card()
        self.dashboard.setObjectName("RuntimeDashboard")
        self.dashboard.setFixedHeight(230)
        dashboard_layout.setContentsMargins(14, 10, 14, 10)
        dashboard_layout.setSpacing(4)

        header = QHBoxLayout()
        self.status = QLabel("No profile · Stopped · 00:00")
        self.status.setProperty("role", "section")
        header.addWidget(self.status, 1)
        self.availability = QLabel("Metrics Unavailable · Slots Unavailable")
        self.availability.setProperty("role", "muted")
        header.addWidget(self.availability)
        self.start_button = make_button("Start", primary=True)
        self.stop_button = make_button("Stop")
        self.restart_button = make_button("Restart")
        header.addWidget(self.start_button)
        header.addWidget(self.stop_button)
        header.addWidget(self.restart_button)
        dashboard_layout.addLayout(header)

        endpoints = QHBoxLayout()
        self.upstream = QLabel("Upstream: Unavailable")
        self.upstream.setProperty("role", "muted")
        self.client = QLabel("Client endpoint: Unavailable")
        self.client.setProperty("role", "muted")
        endpoints.addWidget(self.upstream)
        endpoints.addStretch()
        endpoints.addWidget(self.client)
        dashboard_layout.addLayout(endpoints)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(8)
        metrics.setVerticalSpacing(0)
        self.generation = MetricCard("Generation throughput")
        self.slots = MetricCard("Slots")
        self.queue = MetricCard("Queue")
        self.tokens = MetricCard("Session tokens")
        for column, widget in enumerate(
            [self.generation, self.slots, self.queue, self.tokens]
        ):
            metrics.addWidget(widget, 0, column)
            metrics.setColumnStretch(column, 1)
        dashboard_layout.addLayout(metrics)

        self.latest = QLabel("Latest client task: Unavailable")
        self.latest.setProperty("role", "muted")
        self.latest.setMinimumHeight(16)
        dashboard_layout.addWidget(self.latest)

        charts = QHBoxLayout()
        charts.setSpacing(8)
        self.throughput_chart = CompactChart(
            "Throughput · 5 min",
            (
                ("Prompt", "prompt_tokens_per_second", QColor("#d74b8e")),
                ("Generation", "generated_tokens_per_second", QColor("#7c5ce5")),
            ),
        )
        self.pressure_chart = CompactChart(
            "Slot pressure · 5 min",
            (
                ("Occupancy", "slot_occupancy", QColor("#d74b8e")),
                ("Deferred", "deferred_requests", QColor("#d98a2b")),
            ),
            percent_axis=False,
        )
        charts.addWidget(self.throughput_chart, 1)
        charts.addWidget(self.pressure_chart, 1)
        dashboard_layout.addLayout(charts)
        layout.addWidget(self.dashboard, 0)

        output_card, output_layout = card()
        output_layout.addWidget(
            section_header("Process output", "Recent stdout and stderr from the owned process.")
        )
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        self.output.setAccessibleName("Process output")
        self.output.setStyleSheet(
            "QPlainTextEdit { background:#241c22; color:#fff7fb; "
            "font-family:Consolas; border-radius:10px; padding:8px; }"
        )
        output_layout.addWidget(self.output, 1)
        layout.addWidget(output_card, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(3)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.start_button.clicked.connect(
            lambda _checked=False: self.start_requested.emit()
        )
        self.stop_button.clicked.connect(
            lambda _checked=False: self.stop_requested.emit()
        )
        self.restart_button.clicked.connect(
            lambda _checked=False: self.restart_requested.emit()
        )
        self.set_runtime_state(
            RuntimeState.STOPPED, "", has_profile=False, process_active=False
        )

    def set_runtime_state(
        self,
        state: RuntimeState,
        detail: str,
        *,
        has_profile: bool,
        process_active: bool,
        profile_name: str = "",
    ) -> None:
        controls = control_states(
            state, has_profile=has_profile, process_active=process_active
        )
        self.start_button.setEnabled(controls.start)
        self.stop_button.setEnabled(controls.stop)
        self.restart_button.setEnabled(controls.restart)
        self.progress.setVisible(
            state in {RuntimeState.STARTING, RuntimeState.STOPPING}
        )
        prefix = profile_name or "No profile"
        current_uptime = self.status.text().rsplit(" · ", 1)[-1]
        if ":" not in current_uptime:
            current_uptime = "00:00"
        self.status.setText(f"{prefix} · {state.value} · {current_uptime}")
        self.status.setAccessibleDescription(detail)
        self.status.setToolTip(detail)

    def set_endpoints(self, upstream: str, client: str) -> None:
        self.upstream.setText(f"Upstream: {upstream}")
        self.client.setText(f"Client endpoint: {client}")

    def render_snapshot(self, snapshot: DashboardSnapshot) -> None:
        state_text = "Stopped" if snapshot.stopped else "Ready"
        self.status.setText(
            f"{snapshot.profile_name} · {state_text} · "
            f"{format_duration(snapshot.uptime_seconds)}"
        )
        self.availability.setText(
            f"Metrics {snapshot.metrics_state.value} · Slots {snapshot.slots_state.value}"
        )
        total_rate = snapshot.current_generated_tokens_per_second
        slot_rate = per_active_slot_rate(total_rate, snapshot.active_slots)
        generation_value = f"All-slot {format_rate(total_rate)}"
        generation_detail = f"Per-active-slot avg {format_rate(slot_rate)}"
        if snapshot.metrics_state is not Availability.AVAILABLE:
            generation_value = snapshot.metrics_state.value
            generation_detail = "Per-active-slot avg —"
        self.generation.set_values(generation_value, generation_detail)

        if snapshot.slots_state is Availability.AVAILABLE:
            active = format_count(snapshot.active_slots)
            self.slots.set_values(
                f"{active} / {snapshot.total_slots}",
                format_percent(snapshot.slot_occupancy),
            )
            queue_value = format_count(snapshot.deferred_requests)
        else:
            self.slots.set_values(snapshot.slots_state.value, "")
            queue_value = snapshot.slots_state.value
        self.queue.set_values(queue_value, "deferred requests")
        self.tokens.set_values(
            f"In {format_count(snapshot.session_prompt_tokens)} · "
            f"Out {format_count(snapshot.session_generated_tokens)}",
            f"prompt avg {format_rate(snapshot.average_prompt_tokens_per_second)}",
        )
        self.latest.setText(_latest_text(snapshot))
        self.throughput_chart.set_data(snapshot.history, snapshot.metrics_state)
        self.pressure_chart.set_data(snapshot.history, snapshot.slots_state)

    def append_logs(self, lines: list[str]) -> None:
        if not lines:
            return
        bar = self.output.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 4
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.output.document().blockCount() > 1:
            cursor.insertText("\n")
        cursor.insertText("\n".join(lines))
        if follow:
            self.output.setTextCursor(cursor)
            bar.setValue(bar.maximum())


def _latest_text(snapshot: DashboardSnapshot) -> str:
    request = snapshot.latest_request
    if request is None:
        return "Latest client task: Unavailable"
    cache = format_percent(request.cache_reuse)
    return (
        f"Latest client task · In {format_count(request.input_tokens)} · "
        f"Out {format_count(request.generated_tokens)} · Cache {cache} · "
        f"Compute {format_ms(request.server_compute_ms)} · "
        f"TTFT {format_ms(request.time_to_first_byte_ms)} · "
        f"Total {format_ms(request.end_to_end_ms)}"
    )
