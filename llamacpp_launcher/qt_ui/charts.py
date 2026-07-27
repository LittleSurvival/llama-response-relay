from __future__ import annotations

from collections.abc import Sequence
import math

from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..telemetry import Availability, ChartSample
from .style import COLORS


class CompactChart(QWidget):
    """Small fixed-purpose chart with throttled paint scheduling."""

    def __init__(
        self,
        title: str,
        series: tuple[tuple[str, str, QColor], ...],
        *,
        percent_axis: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.series = series
        self.percent_axis = percent_axis
        self.samples: tuple[ChartSample, ...] = ()
        self.state = Availability.UNAVAILABLE
        self.setProperty("framed", True)
        self.setMinimumHeight(62)
        self.setMaximumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{title} chart")
        self._paint_timer = QTimer(self)
        self._paint_timer.setSingleShot(True)
        self._paint_timer.setInterval(80)
        self._paint_timer.timeout.connect(self.update)

    def set_data(
        self, samples: Sequence[ChartSample], state: Availability
    ) -> None:
        self.samples = tuple(samples[-300:])
        self.state = state
        values = []
        for label, field, _color in self.series:
            current, peak = _series_stats(self.samples, field)
            values.append(f"{label} current {_fmt(current, self.percent_axis)}, peak {_fmt(peak, self.percent_axis)}")
        self.setAccessibleDescription(f"{self.state.value}. " + "; ".join(values))
        if not self._paint_timer.isActive():
            self._paint_timer.start()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if not self._paint_timer.isActive():
            self._paint_timer.start()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        surface = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(COLORS["border"]), 1.0))
        painter.setBrush(QColor("#fffafd"))
        painter.drawRoundedRect(surface, 10.0, 10.0)
        rect = QRectF(self.rect()).adjusted(10, 7, -10, -7)
        painter.setPen(QColor(COLORS["text"]))
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
        painter.setFont(font)
        painter.drawText(rect, self.title)

        painter.setFont(self.font())
        legend_x = rect.left()
        for label, field, color in self.series:
            current, peak = _series_stats(self.samples, field)
            text = (
                f"{label} {_fmt(current, self.percent_axis)}"
                f"/{_fmt(peak, self.percent_axis)}"
            )
            painter.setPen(color)
            painter.drawText(QPointF(legend_x, rect.top() + 25), text)
            legend_x += painter.fontMetrics().horizontalAdvance(text) + 13

        plot = rect.adjusted(0, 31, 0, 0)
        painter.setPen(QPen(QColor("#ead9e1"), 1))
        for fraction in (0.0, 0.5, 1.0):
            y = plot.bottom() - plot.height() * fraction
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        if self.state is not Availability.AVAILABLE or len(self.samples) < 2:
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self.state.value)
            return

        all_values = [
            float(value)
            for _label, field, _color in self.series
            for sample in self.samples
            if (value := getattr(sample, field)) is not None and math.isfinite(float(value))
        ]
        maximum = max(all_values, default=1.0)
        maximum = max(1.0 if not self.percent_axis else 0.01, maximum)
        count = len(self.samples)
        for _label, field, color in self.series:
            path = QPainterPath()
            started = False
            for index, sample in enumerate(self.samples):
                value = getattr(sample, field)
                if value is None or not math.isfinite(float(value)):
                    started = False
                    continue
                x = plot.left() + plot.width() * index / max(1, count - 1)
                y = plot.bottom() - plot.height() * max(0.0, float(value)) / maximum
                if not started:
                    path.moveTo(x, y)
                    started = True
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(color, 1.7))
            painter.drawPath(path)


def _series_stats(
    samples: Sequence[ChartSample], field: str
) -> tuple[float | None, float | None]:
    values = [
        float(value)
        for sample in samples
        if (value := getattr(sample, field)) is not None and math.isfinite(float(value))
    ]
    if not values:
        return None, None
    return values[-1], max(values)


def _fmt(value: float | None, percent: bool) -> str:
    if value is None:
        return "—"
    if percent:
        return f"{value * 100:.0f}%"
    return f"{value:.1f}"
