from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtWidgets import QApplication

from ..models import Glossary, GlossaryEntry, Profile
from .crash_handler import CrashHandler
from .style import apply_theme
from .window import LauncherWindow


def create_application(argv: list[str] | None = None) -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    QCoreApplication.setOrganizationName("LlamaResponseRelay")
    QCoreApplication.setApplicationName("LlamaCppLauncher")
    application = QApplication(argv if argv is not None else sys.argv)
    application.setQuitOnLastWindowClosed(True)
    apply_theme(application)
    return application


def main() -> None:
    application = create_application()
    crash_handler = CrashHandler(application)
    crash_handler.install()
    application._lrr_crash_handler = crash_handler
    window = LauncherWindow()
    window.show()
    smoke_result = os.environ.get("LRR_PACKAGED_SMOKE_RESULT")
    if smoke_result:
        QTimer.singleShot(0, lambda: _run_packaged_smoke(window, Path(smoke_result)))
    raise SystemExit(application.exec())


def _run_packaged_smoke(window: LauncherWindow, result_path: Path) -> None:
    """Exercise packaged Qt/storage integration in an isolated test environment."""
    try:
        visited: list[int] = []
        for index in range(window.stack.count()):
            window.switch_page(index)
            visited.append(window.stack.currentIndex())
        model_path = result_path.with_suffix(".gguf")
        window.settings.profiles = [
            Profile(name="Packaged Smoke", model_path=str(model_path))
        ]
        window.settings.selected_profile = "Packaged Smoke"
        window.settings.glossaries = [
            Glossary(
                id="packaged-smoke-glossary",
                name="Packaged Terms",
                entries=[GlossaryEntry(source="source", replacement="replacement")],
            )
        ]
        window.settings.selected_glossary_id = "packaged-smoke-glossary"
        window.store.save(window.settings)
        reloaded = window.store.load()
        payload = {
            "ok": True,
            "pages": visited,
            "profile": reloaded.selected_profile,
            "glossary": reloaded.glossaries[0].name,
        }
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    window._allow_close = True
    window.close()
