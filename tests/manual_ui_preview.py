"""Manual visual QA helper; not collected as an automated test."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import customtkinter as ctk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llamacpp_launcher.process import RuntimeEvent, RuntimeState
from llamacpp_launcher.telemetry import (
    Availability,
    ChartSample,
    DashboardSnapshot,
    RequestSummary,
)
from llamacpp_launcher.ui import LauncherApp


root = ctk.CTk()
root.tk.call("tk", "scaling", float(os.environ.get("UI_PREVIEW_SCALING", "1.333")))
app = LauncherApp(root)
if os.environ.get("UI_PREVIEW_SIZE"):
    root.geometry(os.environ["UI_PREVIEW_SIZE"])
state = RuntimeState(os.environ.get("UI_PREVIEW_STATE", RuntimeState.STOPPED.value))
messages = {
    RuntimeState.READY: "llama.cpp API is ready at http://127.0.0.1:8080/health",
    RuntimeState.FAILED: "Health check timed out; process is still running.",
    RuntimeState.STARTING: "Loading model. Stop remains available.",
}
if state is not RuntimeState.STOPPED:
    app._handle_runtime_event(
        RuntimeEvent(kind="state", state=state, message=messages.get(state, state.value))
    )
scenario = os.environ.get("UI_PREVIEW_SCENARIO", "")
if scenario:
    app._switch_view("Runtime")
    availability = (
        Availability.STALE
        if scenario == "stale"
        else Availability.UNSUPPORTED
        if scenario == "unsupported"
        else Availability.UNAVAILABLE
        if scenario in {"idle", "loading", "restart"}
        else Availability.AVAILABLE
    )
    active = 4 if scenario in {"saturated", "queued"} else 2
    deferred = 3 if scenario == "queued" else 0
    stopped = scenario == "stopped"
    has_values = availability in {Availability.AVAILABLE, Availability.STALE}
    history = tuple(
        ChartSample(
            uptime_seconds=float(index),
            prompt_tokens_per_second=(
                28 + index % 9 if has_values else None
            ),
            generated_tokens_per_second=(
                10 + index % 6 if has_values else None
            ),
            slot_occupancy=(
                min(1, (active + (index % 2)) / 4) if has_values else None
            ),
            deferred_requests=(
                deferred if has_values else None
            ),
        )
        for index in range(60)
    )
    app._render_dashboard(
        DashboardSnapshot(
            generation=1,
            profile_name="Pink demo",
            uptime_seconds=3 if scenario == "restart" else 754,
            total_slots=4,
            active_slots=active if has_values else None,
            slot_occupancy=(
                active / 4 if has_values else None
            ),
            deferred_requests=(
                deferred if has_values else None
            ),
            session_prompt_tokens=18420 if has_values else None,
            session_generated_tokens=6290 if has_values else None,
            average_prompt_tokens_per_second=34.2 if has_values else None,
            average_generated_tokens_per_second=13.8 if has_values else None,
            current_prompt_tokens_per_second=36.5 if has_values else None,
            current_generated_tokens_per_second=15.2 if has_values else None,
            metrics_state=availability,
            slots_state=availability,
            latest_request=(
                RequestSummary(
                    endpoint="/v1/chat/completions",
                    status=200,
                    input_tokens=2048,
                    generated_tokens=612,
                    cached_tokens=1536,
                    prompt_ms=823,
                    generated_ms=8824,
                    time_to_first_byte_ms=1060,
                    end_to_end_ms=9910,
                )
                if has_values and scenario != "restart"
                else None
            ),
            history=history,
            stopped=stopped,
        )
    )
root.mainloop()
