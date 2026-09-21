from __future__ import annotations

from PyQt6.QtCore import QRectF, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..hardware import (
    CpuSample,
    GpuSample,
    HardwareSnapshot,
    MetricReading,
    format_frequency,
    format_hardware_percent,
    format_temperature,
    format_vram,
)
from ..telemetry import Availability
from .components import card
from .style import COLORS


class DonutGauge(QWidget):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self._reading = MetricReading()
        self.setFixedSize(78, 92)
        self.setAccessibleName(label)
        self.setAccessibleDescription(f"{label}: —")

    def sizeHint(self) -> QSize:
        return QSize(78, 92)

    def set_reading(self, reading: MetricReading) -> None:
        if self._reading == reading:
            return
        self._reading = reading
        self.setAccessibleDescription(
            f"{label}: {format_hardware_percent(reading)}"
            if (label := self.label)
            else format_hardware_percent(reading)
        )
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(10, 4, 58, 58)
        track = QPen(QColor("#f3dce6"), 7)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(rect)

        reading = self._reading
        available = (
            reading.state is Availability.AVAILABLE and reading.value is not None
        )
        if available:
            accent = QPen(QColor(COLORS["accent"]), 7)
            accent.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(accent)
            span = -int(max(0.0, min(100.0, reading.value)) * 3.6 * 16)
            if span:
                painter.drawArc(rect, 90 * 16, span)

        painter.setPen(QColor(COLORS["text"] if available else COLORS["muted"]))
        value_font = QFont("Segoe UI", 9)
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, format_hardware_percent(reading))
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor(COLORS["muted"]))
        painter.drawText(
            QRectF(0, 69, self.width(), 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self.label,
        )


class CpuHardwareCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setMinimumWidth(245)
        self.setMaximumWidth(270)
        self.setFixedHeight(132)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)
        self.usage = DonutGauge("CPU usage")
        layout.addWidget(self.usage)
        text = QVBoxLayout()
        title = QLabel("CPU")
        title.setProperty("role", "section")
        self.frequency = QLabel("Frequency\nUnavailable")
        self.frequency.setProperty("role", "muted")
        self.process = QLabel("llama-server\nUnavailable")
        self.process.setProperty("role", "muted")
        text.addWidget(title)
        text.addWidget(self.frequency)
        text.addWidget(self.process)
        text.addStretch()
        layout.addLayout(text, 1)

    def set_sample(self, sample: CpuSample) -> None:
        self.usage.set_reading(sample.utilization)
        self.frequency.setText(f"Frequency\n{format_frequency(sample.frequency_mhz)}")
        self.process.setText(
            f"llama-server\n{format_hardware_percent(sample.process_utilization)}"
        )


class GpuHardwareCard(QFrame):
    def __init__(self, gpu: GpuSample, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setMinimumWidth(355)
        self.setMaximumWidth(380)
        self.setFixedHeight(132)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(8)
        self.usage = DonutGauge("GPU usage")
        self.vram = DonutGauge("VRAM")
        layout.addWidget(self.usage)
        layout.addWidget(self.vram)
        details = QVBoxLayout()
        details.setSpacing(2)
        self.name = QLabel()
        self.name.setProperty("role", "section")
        self.name.setWordWrap(False)
        self.name.setToolTip(gpu.name)
        self.clock = QLabel()
        self.memory = QLabel()
        self.temperature = QLabel()
        for label in (self.clock, self.memory, self.temperature):
            label.setProperty("role", "muted")
        details.addWidget(self.name)
        details.addWidget(self.clock)
        details.addWidget(self.memory)
        details.addWidget(self.temperature)
        details.addStretch()
        layout.addLayout(details, 1)
        self.set_sample(gpu)

    def set_sample(self, sample: GpuSample) -> None:
        self.name.setText(f"{sample.vendor} · {sample.name}")
        self.name.setToolTip(sample.name)
        self.usage.set_reading(sample.utilization)
        self.vram.set_reading(sample.vram_utilization)
        self.clock.setText(f"Clock  {format_frequency(sample.frequency_mhz)}")
        self.memory.setText(
            f"VRAM  {format_vram(sample.vram_used_bytes, sample.vram_total_bytes)}"
        )
        self.temperature.setText(
            f"Temperature  {format_temperature(sample.temperature_c)}"
        )


class HardwareDashboard(QWidget):
    refresh_requested = pyqtSignal()
    expanded_changed = pyqtSignal(bool)

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._snapshot: HardwareSnapshot | None = None
        self._gpu_cards: dict[str, GpuHardwareCard] = {}
        self._gpu_order: tuple[str, ...] = ()
        self._stale_rendered = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame, frame_layout = card()
        self.frame.setObjectName("HardwareDashboard")
        frame_layout.setContentsMargins(14, 8, 14, 8)
        frame_layout.setSpacing(5)
        outer.addWidget(self.frame)

        header = QHBoxLayout()
        title = QLabel("Hardware")
        title.setProperty("role", "section")
        header.addWidget(title)
        self.status = QLabel("Waiting for hardware telemetry")
        self.status.setProperty("role", "muted")
        header.addWidget(self.status, 1)
        self.toggle = QPushButton()
        self.toggle.setObjectName("HardwareCollapseButton")
        self.toggle.setFlat(True)
        self.toggle.setFixedSize(32, 28)
        self.toggle.setAccessibleName("Collapse hardware dashboard")
        header.addWidget(self.toggle)
        frame_layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(142)
        self.scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.cards_host = QWidget()
        self.cards_layout = QHBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.cpu_card = CpuHardwareCard()
        self.cards_layout.addWidget(self.cpu_card)
        self.no_gpu = QLabel("No supported GPU detected")
        self.no_gpu.setProperty("role", "muted")
        self.no_gpu.setMinimumWidth(180)
        self.cards_layout.addWidget(self.no_gpu)
        self.cards_layout.addStretch()
        self.scroll.setWidget(self.cards_host)
        frame_layout.addWidget(self.scroll)

        expanded = _setting_bool(settings, "runtime/hardware-expanded", True)
        self._expanded = not expanded
        self.set_expanded(expanded, persist=False)
        self.toggle.clicked.connect(
            lambda _checked=False: self.set_expanded(not self._expanded)
        )

        self.stale_timer = QTimer(self)
        self.stale_timer.setInterval(1000)
        self.stale_timer.timeout.connect(self._refresh_stale_state)
        self.stale_timer.start()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, *, persist: bool = True) -> None:
        expanded = bool(expanded)
        changed = expanded != self._expanded
        self._expanded = expanded
        self.scroll.setVisible(expanded)
        self.frame.setFixedHeight(190 if expanded else 44)
        self.setFixedHeight(190 if expanded else 44)
        self.toggle.setText("⌃" if expanded else "⌄")
        self.toggle.setAccessibleName(
            "Collapse hardware dashboard" if expanded else "Expand hardware dashboard"
        )
        if persist and self._settings is not None:
            self._settings.setValue("runtime/hardware-expanded", expanded)
            self._settings.sync()
        if changed:
            self.expanded_changed.emit(expanded)
            if expanded:
                self.refresh_requested.emit()

    def set_snapshot(self, snapshot: HardwareSnapshot) -> None:
        self._snapshot = snapshot
        self._stale_rendered = snapshot.state is Availability.STALE
        self.status.setText(
            "Stale" if snapshot.state is Availability.STALE else "Updates every second"
        )
        self.cpu_card.set_sample(snapshot.cpu)
        order = tuple(gpu.identifier for gpu in snapshot.gpus)
        if order != self._gpu_order:
            self._rebuild_gpu_cards(snapshot.gpus)
        else:
            for gpu in snapshot.gpus:
                self._gpu_cards[gpu.identifier].set_sample(gpu)
        self.no_gpu.setVisible(not snapshot.gpus)

    def _rebuild_gpu_cards(self, gpus: tuple[GpuSample, ...]) -> None:
        for card_widget in self._gpu_cards.values():
            self.cards_layout.removeWidget(card_widget)
            card_widget.deleteLater()
        self._gpu_cards.clear()
        for gpu in gpus:
            gpu_card = GpuHardwareCard(gpu)
            self._gpu_cards[gpu.identifier] = gpu_card
            self.cards_layout.insertWidget(
                max(1, self.cards_layout.count() - 2), gpu_card
            )
        self._gpu_order = tuple(gpu.identifier for gpu in gpus)

    def _refresh_stale_state(self) -> None:
        if (
            self._snapshot is None
            or self._stale_rendered
            or not self._snapshot.is_stale()
        ):
            return
        self.set_snapshot(self._snapshot.stale())


def _setting_bool(
    settings: QSettings | None, key: str, default: bool
) -> bool:
    if settings is None:
        return default
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() not in {"0", "false", "no", "off"}
