from __future__ import annotations

import os
from pathlib import Path
import queue
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llamacpp_launcher.process import RuntimeState
from llamacpp_launcher.qt_ui.app import create_application
from llamacpp_launcher.qt_ui.window import LauncherWindow
from llamacpp_launcher.storage import SettingsStore
from llamacpp_launcher.telemetry import Availability
from test_ui_logic import FakeRuntime, sample_snapshot


state_name = os.environ.get("UI_PREVIEW_STATE", "Ready")
state = RuntimeState(state_name)
runtime = FakeRuntime()
runtime.state = state
runtime.active_profile = "novelia"
runtime.is_active = state not in {RuntimeState.STOPPED, RuntimeState.FAILED}
if state is RuntimeState.FAILED:
    runtime.dashboard_snapshot = sample_snapshot(
        metrics_state=Availability.UNAVAILABLE,
        slots_state=Availability.STALE,
        stopped=True,
    )
elif state is RuntimeState.STOPPED:
    runtime.dashboard_snapshot = sample_snapshot(stopped=True)
else:
    runtime.dashboard_snapshot = sample_snapshot()

application = create_application()
window = LauncherWindow(
    store=SettingsStore(ROOT / ".tmp-ui-preview-settings.json"),
    runtime=runtime,
)
window.switch_page(2)
if runtime.dashboard_snapshot:
    window.runtime_page.render_snapshot(runtime.dashboard_snapshot)
window._runtime_state_changed(state, f"Manual {state.value} preview")
window.show()
raise SystemExit(application.exec())
