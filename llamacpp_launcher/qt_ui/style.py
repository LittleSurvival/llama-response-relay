from __future__ import annotations

import os
from pathlib import Path
import sys

from PyQt6.QtCore import QFileInfo
from PyQt6.QtGui import QColor, QIcon, QPalette
from PyQt6.QtWidgets import QApplication, QFileIconProvider


COLORS = {
    "background": "#fff8fb",
    "surface": "#ffffff",
    "surface_alt": "#fff0f6",
    "border": "#f2ccdc",
    "accent": "#e83e8c",
    "accent_hover": "#cf2f78",
    "accent_soft": "#fde1ed",
    "text": "#24191f",
    "muted": "#765c69",
    "success": "#1f8a64",
    "warning": "#ae6b00",
    "error": "#c93452",
    "console": "#241c22",
}


def animations_enabled() -> bool:
    return os.environ.get("LRR_DISABLE_ANIMATIONS", "").casefold() not in {
        "1",
        "true",
        "yes",
    }


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["background"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["surface_alt"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setWindowIcon(application_icon())
    app.setStyleSheet(
        f"""
        * {{
            font-family: "Segoe UI";
            font-size: 13px;
            color: {COLORS["text"]};
        }}
        QMainWindow, QWidget#AppRoot {{ background: {COLORS["background"]}; }}
        QWidget#Sidebar {{
            background: {COLORS["surface"]};
            border-right: 1px solid {COLORS["border"]};
        }}
        QFrame[card="true"] {{
            background: {COLORS["surface"]};
            border: 1px solid {COLORS["border"]};
            border-radius: 14px;
        }}
        QLabel[role="title"] {{ font-size: 22px; font-weight: 700; }}
        QLabel[role="section"] {{ font-size: 15px; font-weight: 700; }}
        QLabel[role="muted"] {{ color: {COLORS["muted"]}; }}
        QLabel[role="error"] {{ color: {COLORS["error"]}; }}
        QLabel[role="success"] {{ color: {COLORS["success"]}; }}
        QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
            background: {COLORS["surface"]};
            border: 1px solid {COLORS["border"]};
            border-radius: 9px;
            padding: 7px 9px;
            selection-background-color: {COLORS["accent"]};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
            border: 2px solid {COLORS["accent"]};
        }}
        QLineEdit[invalid="true"], QComboBox[invalid="true"], QSpinBox[invalid="true"] {{
            border: 2px solid {COLORS["error"]};
        }}
        QPushButton {{
            min-height: 32px;
            padding: 0 14px;
            background: {COLORS["surface"]};
            border: 1px solid {COLORS["border"]};
            border-radius: 9px;
        }}
        QPushButton:hover {{ background: {COLORS["surface_alt"]}; }}
        QPushButton:focus {{ border: 2px solid {COLORS["accent"]}; }}
        QPushButton:disabled {{ color: #ad9da5; background: #f5eff2; }}
        QPushButton[primary="true"] {{
            color: white;
            background: {COLORS["accent"]};
            border-color: {COLORS["accent"]};
            font-weight: 600;
        }}
        QPushButton[primary="true"]:hover {{ background: {COLORS["accent_hover"]}; }}
        QPushButton[danger="true"] {{ color: {COLORS["error"]}; background: #fff2f5; }}
        QPushButton[nav="true"] {{ text-align: left; border: none; padding-left: 16px; }}
        QPushButton[nav="true"]:checked {{
            color: {COLORS["accent"]};
            background: {COLORS["accent_soft"]};
            font-weight: 700;
        }}
        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{ width: 34px; height: 18px; }}
        QCheckBox::indicator:unchecked {{
            border-radius: 9px; background: #d9cbd2; border: 1px solid #c8b7c0;
        }}
        QCheckBox::indicator:checked {{
            border-radius: 9px; background: {COLORS["accent"]}; border: 1px solid {COLORS["accent"]};
        }}
        QListWidget {{
            background: transparent; border: none; outline: none;
        }}
        QListWidget::item {{ padding: 9px; border-radius: 8px; }}
        QListWidget::item:selected {{ color: {COLORS["accent"]}; background: {COLORS["accent_soft"]}; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{ width: 10px; background: transparent; }}
        QScrollBar::handle:vertical {{ min-height: 28px; background: #d9b8c7; border-radius: 5px; }}
        QScrollBar:horizontal {{ height: 10px; background: transparent; }}
        QScrollBar::handle:horizontal {{ min-width: 36px; background: #d9b8c7; border-radius: 5px; }}
        QPushButton#HardwareCollapseButton {{
            min-height: 26px; padding: 0; border: none; border-radius: 8px;
            color: {COLORS["muted"]}; font-size: 16px;
        }}
        QPushButton#HardwareCollapseButton:hover {{ background: {COLORS["surface_alt"]}; }}
        QToolTip {{ color: {COLORS["text"]}; background: {COLORS["surface"]}; border: 1px solid {COLORS["border"]}; }}
        """
    )


def application_icon() -> QIcon:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    bundled_icon = bundle_root / "assets" / "LlamaCppLauncher.ico"
    if bundled_icon.exists():
        return QIcon(str(bundled_icon))
    executable = Path(sys.executable)
    if not executable.exists():
        return QIcon()
    return QFileIconProvider().icon(QFileInfo(str(executable)))
