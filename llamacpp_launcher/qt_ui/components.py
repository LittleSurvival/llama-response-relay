from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRegion,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .style import COLORS, animations_enabled


def _mix(start: QColor, end: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    return QColor(
        round(start.red() + (end.red() - start.red()) * amount),
        round(start.green() + (end.green() - start.green()) * amount),
        round(start.blue() + (end.blue() - start.blue()) * amount),
        round(start.alpha() + (end.alpha() - start.alpha()) * amount),
    )


class ModernButton(QPushButton):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._hover_progress = 0.0
        self._hover_animation = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_animation.setDuration(110)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setMinimumHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def get_hover_progress(self) -> float:
        return self._hover_progress

    def set_hover_progress(self, value: float) -> None:
        self._hover_progress = value
        self.update()

    hoverProgress = pyqtProperty(
        float, fget=get_hover_progress, fset=set_hover_progress
    )

    def enterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().enterEvent(event)
        self._animate_hover(1.0)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().leaveEvent(event)
        self._animate_hover(0.0)

    def _animate_hover(self, target: float) -> None:
        if not animations_enabled():
            self.set_hover_progress(target)
            return
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        primary = bool(self.property("primary"))
        danger = bool(self.property("danger"))
        nav = bool(self.property("nav"))
        if nav and self.isChecked():
            base = QColor(COLORS["accent_soft"])
            hover = QColor("#f9cfe1")
            text = QColor(COLORS["accent"])
            border = QColor(Qt.GlobalColor.transparent)
        elif primary:
            base = QColor(COLORS["accent"])
            hover = QColor(COLORS["accent_hover"])
            text = QColor("#ffffff")
            border = base
        elif danger:
            base = QColor("#fff1f5")
            hover = QColor("#ffe1e9")
            text = QColor(COLORS["error"])
            border = QColor("#f3becb")
        else:
            base = QColor(COLORS["surface"])
            hover = QColor(COLORS["surface_alt"])
            text = QColor(COLORS["text"])
            border = QColor(COLORS["border"])
        if self.isDown():
            progress = 1.0
            hover = hover.darker(106)
        else:
            progress = self._hover_progress
        fill = _mix(base, hover, progress)
        if not self.isEnabled():
            fill = QColor("#f5eff2")
            text = QColor("#aa9aa2")
            border = QColor("#eadde3")
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 10.0, 10.0)
        font = self.font()
        font.setWeight(600 if primary or self.isChecked() else 500)
        painter.setFont(font)
        painter.setPen(text)
        alignment = (
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            if nav
            else Qt.AlignmentFlag.AlignCenter
        )
        text_rect = rect.adjusted(15 if nav else 8, 0, -8, 0)
        painter.drawText(text_rect, alignment, self.text())
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLORS["accent"]), 1.5))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 8, 8)


class SmoothSwitch(QAbstractButton):
    def __init__(
        self,
        *,
        accessible_name: str = "Switch",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(accessible_name)
        self._position = 0.0
        self._animation = QPropertyAnimation(self, b"thumbPosition", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def get_thumb_position(self) -> float:
        return self._position

    def set_thumb_position(self, value: float) -> None:
        self._position = value
        self.update()

    thumbPosition = pyqtProperty(
        float, fget=get_thumb_position, fset=set_thumb_position
    )

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        if not self.isVisible() or not animations_enabled():
            self._animation.stop()
            self.set_thumb_position(1.0 if checked else 0.0)

    def _animate(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if not animations_enabled():
            self.set_thumb_position(target)
            return
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(target)
        self._animation.start()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(1, 2, self.width() - 2, self.height() - 4)
        off = QColor("#d9cbd2")
        on = QColor(COLORS["accent"])
        fill = _mix(off, on, self._position)
        if not self.isEnabled():
            fill = QColor("#e8dfe3")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(track, 10, 10)
        diameter = 16.0
        x = 4.0 + self._position * (self.width() - diameter - 8.0)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, 4.0, diameter, diameter))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLORS["accent"]), 1.5))
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), 11, 11)


class ModernComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        view = QListView(self)
        view.setSpacing(2)
        view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        view.setStyleSheet(
            f"""
            QListView {{
                background: {COLORS["surface"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 10px;
                padding: 5px;
                outline: none;
            }}
            QListView::item {{ min-height: 30px; padding: 3px 8px; border-radius: 7px; }}
            QListView::item:hover {{ background: {COLORS["surface_alt"]}; }}
            QListView::item:selected {{ color: {COLORS["accent"]}; background: {COLORS["accent_soft"]}; }}
            """
        )
        self.setView(view)
        self.setFrame(False)
        self.setMaxVisibleItems(12)
        self.setMinimumHeight(36)

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.view().window()
        popup.setObjectName("ModernComboPopup")
        if isinstance(popup, QFrame):
            popup.setFrameShape(QFrame.Shape.NoFrame)
            popup.setLineWidth(0)
        popup.setContentsMargins(0, 0, 0, 0)
        if popup.layout() is not None:
            popup.layout().setContentsMargins(0, 0, 0, 0)
            popup.layout().setSpacing(0)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        popup.setStyleSheet(
            f"QFrame#ModernComboPopup {{ border: none; background: {COLORS['surface']}; }}"
        )
        self.view().setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        screen = QGuiApplication.screenAt(self.mapToGlobal(self.rect().center()))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        row_height = max(
            32,
            self.view().sizeHintForRow(0) + self.view().spacing() * 2,
        )
        visible_rows = max(1, min(self.count(), self.maxVisibleItems()))
        popup_height = visible_rows * row_height + 12
        popup_width = max(self.width(), popup.sizeHint().width())
        origin_top = self.mapToGlobal(QPoint(0, 0))
        origin_bottom = self.mapToGlobal(QPoint(0, self.height()))
        x = origin_top.x()
        y = origin_bottom.y() + 4
        if screen is not None:
            available = screen.availableGeometry()
            popup_width = min(popup_width, available.width())
            x = min(max(x, available.left()), available.right() - popup_width + 1)
            space_below = max(0, available.bottom() - y + 1)
            space_above = max(0, origin_top.y() - available.top() - 4)
            if space_below >= min(row_height + 12, popup_height) or space_below >= space_above:
                popup_height = min(popup_height, space_below)
            else:
                popup_height = min(popup_height, space_above)
                y = origin_top.y() - popup_height - 4
        popup.setGeometry(x, y, popup_width, popup_height)
        QTimer.singleShot(0, lambda: self._finalize_popup(popup))

    def _finalize_popup(self, popup: QWidget) -> None:
        if not popup.isVisible():
            return
        if isinstance(popup, QFrame):
            popup.setFrameStyle(QFrame.Shape.NoFrame.value)
            popup.setLineWidth(0)
        popup.setContentsMargins(0, 0, 0, 0)
        for child in popup.findChildren(QWidget):
            if child.metaObject().className() == "QComboBoxPrivateScroller":
                child.hide()
                child.setFixedHeight(0)
        if popup.layout() is not None:
            popup.layout().invalidate()
            popup.layout().activate()
        self.view().setGeometry(popup.rect())
        self.view().setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        path = QPainterPath()
        path.addRoundedRect(QRectF(popup.rect()), 10, 10)
        popup.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        border = QColor(COLORS["accent"] if self.hasFocus() else COLORS["border"])
        painter.setPen(QPen(border, 1.5 if self.hasFocus() else 1.0))
        painter.setBrush(QColor(COLORS["surface"]))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor(COLORS["text"] if self.isEnabled() else "#aa9aa2"))
        painter.drawText(
            rect.adjusted(11, 0, -32, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.currentText(),
        )
        center_x = rect.right() - 16
        center_y = rect.center().y()
        arrow = QPolygonF(
            [
                rect.topLeft() + _point(center_x - rect.left() - 4, center_y - rect.top() - 2),
                rect.topLeft() + _point(center_x - rect.left() + 4, center_y - rect.top() - 2),
                rect.topLeft() + _point(center_x - rect.left(), center_y - rect.top() + 3),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["muted"]))
        painter.drawPolygon(arrow)


class ModernSpinBox(QSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setMinimumHeight(36)


def _point(x: float, y: float):
    from PyQt6.QtCore import QPointF

    return QPointF(x, y)

def card(parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    return frame, layout


def section_header(title: str, subtitle: str = "") -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    title_label = QLabel(title)
    title_label.setProperty("role", "section")
    layout.addWidget(title_label)
    if subtitle:
        detail = QLabel(subtitle)
        detail.setProperty("role", "muted")
        detail.setWordWrap(True)
        layout.addWidget(detail)
    return widget


def make_button(
    text: str,
    *,
    primary: bool = False,
    danger: bool = False,
    accessible_name: str = "",
) -> ModernButton:
    button = ModernButton(text)
    if primary:
        button.setProperty("primary", True)
    if danger:
        button.setProperty("danger", True)
    if accessible_name:
        button.setAccessibleName(accessible_name)
    return button


class NameDialog(QDialog):
    def __init__(
        self,
        title: str,
        label: str,
        initial: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label))
        self.entry = QLineEdit(initial)
        self.entry.setMaxLength(80)
        self.entry.selectAll()
        layout.addWidget(self.entry)
        self.error = QLabel()
        self.error.setProperty("role", "error")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def value(self) -> str:
        return self.entry.text().strip()

    def _accept(self) -> None:
        if not self.value:
            self.error.setText("Name is required.")
            self.entry.setFocus()
            return
        self.accept()


class PathRow(QWidget):
    browse_requested = pyqtSignal()

    def __init__(self, accessible_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setAccessibleName(accessible_name)
        self.button = make_button("Browse", accessible_name=f"Browse {accessible_name}")
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)
        self.button.clicked.connect(
            lambda _checked=False: self.browse_requested.emit()
        )
