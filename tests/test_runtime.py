from __future__ import annotations

from pathlib import Path
import queue
import time
from typing import Any

from llamacpp_launcher.models import Glossary, GlossaryEntry, Profile, ValidationError
from llamacpp_launcher.process import RuntimeEvent, RuntimeState
from llamacpp_launcher.runtime import LauncherRuntime
from llamacpp_launcher.telemetry import (
    Availability,
    NativeSample,
    RequestSummary,
    SlotState,
)


class FakeProcess:
    def __init__(self, order: list[str]) -> None:
        self.events: queue.Queue[RuntimeEvent] = queue.Queue()
        self.state = RuntimeState.STOPPED
        self.active_profile = ""
        self.is_active = False
        self.order = order

    def start(self, _executable: Path, profile: Profile, _help: str, **_kwargs: Any) -> list[str]:
        self.order.append("llama-start")
        self.active_profile = profile.name
        self.is_active = True
        self.state = RuntimeState.STARTING
        self.events.put(
            RuntimeEvent(kind="state", state=RuntimeState.STARTING, message="starting")
        )
        return ["llama-server.exe"]

    def stop(self, **_kwargs: Any) -> None:
        self.order.append("llama-stop")
        self.is_active = False
        self.active_profile = ""
        self.state = RuntimeState.STOPPED
        self.events.put(
            RuntimeEvent(kind="state", state=RuntimeState.STOPPED, message="stopped")
        )


class FakeInterceptor:
    def __init__(self, order: list[str], *, fail: bool = False) -> None:
        self.order = order
        self.fail = fail
        self.is_running = False
        self.glossary: Glossary | None = None
        self.summary_callback: Any = None

    def set_request_summary_callback(self, callback: Any) -> None:
        self.summary_callback = callback

    def start(
        self, _host: str, _port: int, _upstream: str, glossary: Glossary | None
    ) -> None:
        self.order.append("lrr-start")
        if self.fail:
            raise ValidationError("address in use")
        self.glossary = glossary
        self.is_running = True

    def stop(self, **_kwargs: Any) -> None:
        self.order.append("lrr-stop")
        self.is_running = False


class FakeCollector:
    def __init__(self) -> None:
        self.callback: Any = None
        self.starts: list[tuple[int, str, bool, bool]] = []
        self.stop_count = 0

    def start(
        self,
        generation: int,
        upstream: str,
        *,
        metrics_supported: bool,
        slots_supported: bool,
    ) -> None:
        self.starts.append(
            (generation, upstream, metrics_supported, slots_supported)
        )

    def stop(self, **_kwargs: Any) -> None:
        self.stop_count += 1

    def emit(self, generation: int, sample: NativeSample) -> None:
        assert self.callback is not None
        self.callback(generation, sample)


def wait_for(runtime: LauncherRuntime, state: RuntimeState) -> RuntimeEvent:
    deadline = time.monotonic() + 2
    latest = RuntimeEvent(kind="state", message="")
    while time.monotonic() < deadline:
        try:
            latest = runtime.events.get(timeout=0.1)
        except queue.Empty:
            continue
        if latest.state is state:
            return latest
    raise AssertionError(f"Did not reach {state}; last event was {latest}")


def profile() -> Profile:
    return Profile(
        name="Chat",
        model_path="model.gguf",
        host="127.0.0.1",
        port=8080,
    )


def test_runtime_starts_lrr_after_llama_ready_and_stops_in_order() -> None:
    order: list[str] = []
    process = FakeProcess(order)
    interceptor = FakeInterceptor(order)
    runtime = LauncherRuntime(process=process, interceptor=interceptor)  # type: ignore[arg-type]
    runtime.start(
        Path("llama-server.exe"),
        profile(),
        "help",
        interceptor_enabled=True,
        interceptor_host="127.0.0.1",
        interceptor_port=8081,
        glossary=None,
    )
    process.events.put(
        RuntimeEvent(kind="state", state=RuntimeState.READY, message="llama ready")
    )

    ready = wait_for(runtime, RuntimeState.READY)
    assert "8081" in ready.message
    assert order == ["llama-start", "lrr-start"]

    runtime.stop()
    wait_for(runtime, RuntimeState.STOPPED)
    assert order[-2:] == ["lrr-stop", "llama-stop"]


def test_runtime_keeps_llama_stoppable_when_lrr_bind_fails() -> None:
    order: list[str] = []
    process = FakeProcess(order)
    runtime = LauncherRuntime(
        process=process,  # type: ignore[arg-type]
        interceptor=FakeInterceptor(order, fail=True),  # type: ignore[arg-type]
    )
    runtime.start(
        Path("llama-server.exe"),
        profile(),
        "help",
        interceptor_enabled=True,
        interceptor_host="127.0.0.1",
        interceptor_port=8081,
        glossary=None,
    )
    process.events.put(
        RuntimeEvent(kind="state", state=RuntimeState.READY, message="llama ready")
    )

    failed = wait_for(runtime, RuntimeState.FAILED)
    assert "address in use" in failed.message
    assert runtime.is_active
    runtime.close()
    wait_for(runtime, RuntimeState.STOPPED)
    assert order[-1] == "llama-stop"


def test_runtime_uses_glossary_snapshot() -> None:
    order: list[str] = []
    process = FakeProcess(order)
    interceptor = FakeInterceptor(order)
    glossary = Glossary(
        name="Terms",
        entries=[GlossaryEntry(source="old", replacement="new")],
    )
    runtime = LauncherRuntime(process=process, interceptor=interceptor)  # type: ignore[arg-type]
    runtime.start(
        Path("llama-server.exe"),
        profile(),
        "help",
        interceptor_enabled=True,
        interceptor_host="127.0.0.1",
        interceptor_port=8081,
        glossary=glossary,
    )
    glossary.entries[0].replacement = "changed after start"
    process.events.put(
        RuntimeEvent(kind="state", state=RuntimeState.READY, message="llama ready")
    )

    wait_for(runtime, RuntimeState.READY)
    assert interceptor.glossary is not None
    assert interceptor.glossary.entries[0].replacement == "new"
    runtime.stop()


def test_runtime_restart_and_close_preserve_lrr_process_order() -> None:
    order: list[str] = []
    process = FakeProcess(order)
    interceptor = FakeInterceptor(order)
    runtime = LauncherRuntime(process=process, interceptor=interceptor)  # type: ignore[arg-type]
    args = (
        Path("llama-server.exe"),
        profile(),
        "help",
    )
    kwargs = {
        "interceptor_enabled": True,
        "interceptor_host": "127.0.0.1",
        "interceptor_port": 8081,
        "glossary": None,
    }
    runtime.start(*args, **kwargs)
    process.events.put(
        RuntimeEvent(kind="state", state=RuntimeState.READY, message="llama ready")
    )
    wait_for(runtime, RuntimeState.READY)

    runtime.restart(*args, **kwargs)
    assert order[-3:] == ["lrr-stop", "llama-stop", "llama-start"]
    process.events.put(
        RuntimeEvent(kind="state", state=RuntimeState.READY, message="llama ready")
    )
    wait_for(runtime, RuntimeState.READY)

    runtime.close()
    assert order[-2:] == ["lrr-stop", "llama-stop"]


def test_runtime_skips_interceptor_when_lrr_is_disabled() -> None:
    order: list[str] = []
    process = FakeProcess(order)
    interceptor = FakeInterceptor(order)
    runtime = LauncherRuntime(process=process, interceptor=interceptor)  # type: ignore[arg-type]
    runtime.start(
        Path("llama-server.exe"),
        profile(),
        "help",
        interceptor_enabled=False,
        interceptor_host="127.0.0.1",
        interceptor_port=8081,
        glossary=None,
    )
    process.events.put(
        RuntimeEvent(kind="state", state=RuntimeState.READY, message="llama ready")
    )

    ready = wait_for(runtime, RuntimeState.READY)
    assert "LRR disabled" in ready.message
    assert "8080" in ready.message
    assert order == ["llama-start"]

    runtime.stop()
    wait_for(runtime, RuntimeState.STOPPED)
    assert order[-1] == "llama-stop"


def test_runtime_owns_collector_and_discards_previous_generation_samples() -> None:
    order: list[str] = []
    process = FakeProcess(order)
    interceptor = FakeInterceptor(order)
    collector = FakeCollector()
    runtime = LauncherRuntime(
        process=process,  # type: ignore[arg-type]
        interceptor=interceptor,  # type: ignore[arg-type]
        collector=collector,
    )
    collector.callback = runtime._handle_native_sample
    kwargs = {
        "interceptor_enabled": False,
        "interceptor_host": "127.0.0.1",
        "interceptor_port": 8081,
        "glossary": None,
    }

    runtime.start(Path("llama-server.exe"), profile(), "--metrics --slots", **kwargs)
    process.events.put(
        RuntimeEvent(kind="state", state=RuntimeState.READY, message="ready")
    )
    wait_for(runtime, RuntimeState.READY)
    assert collector.starts == [
        (1, "http://127.0.0.1:8080", True, True)
    ]
    collector.emit(
        1,
        NativeSample(
            timestamp=time.monotonic(),
            metrics_state=Availability.AVAILABLE,
            slots_state=Availability.AVAILABLE,
            generated_tokens_total=30,
            generated_seconds_total=2,
            generated_tokens_per_second=15,
            requests_deferred=1,
            slots=(
                SlotState(id=0, is_processing=True),
                SlotState(id=1, is_processing=False),
            ),
        ),
    )
    assert runtime.dashboard_snapshot is not None
    assert runtime.dashboard_snapshot.active_slots == 1

    runtime.restart(
        Path("llama-server.exe"), profile(), "--metrics --slots", **kwargs
    )
    assert runtime.dashboard_snapshot is not None
    assert runtime.dashboard_snapshot.generation == 2
    collector.emit(
        1,
        NativeSample(
            timestamp=time.monotonic(),
            metrics_state=Availability.AVAILABLE,
            generated_tokens_total=999,
        ),
    )
    assert runtime.dashboard_snapshot.session_generated_tokens is None

    process.events.put(
        RuntimeEvent(kind="state", state=RuntimeState.READY, message="ready")
    )
    wait_for(runtime, RuntimeState.READY)
    runtime.stop()
    snapshot = runtime.dashboard_snapshot
    assert snapshot is not None and snapshot.stopped
    frozen_uptime = snapshot.uptime_seconds
    time.sleep(0.01)
    assert runtime.dashboard_snapshot.uptime_seconds == frozen_uptime
    assert collector.stop_count >= 3


def test_runtime_forwards_numeric_lrr_summary_to_dashboard() -> None:
    order: list[str] = []
    process = FakeProcess(order)
    interceptor = FakeInterceptor(order)
    runtime = LauncherRuntime(
        process=process,  # type: ignore[arg-type]
        interceptor=interceptor,  # type: ignore[arg-type]
    )
    runtime.start(
        Path("llama-server.exe"),
        profile(),
        "help",
        interceptor_enabled=True,
        interceptor_host="127.0.0.1",
        interceptor_port=8081,
        glossary=None,
    )
    assert interceptor.summary_callback is not None
    interceptor.summary_callback(
        RequestSummary(
            endpoint="/v1/completions",
            status=200,
            input_tokens=10,
            generated_tokens=20,
            cached_tokens=4,
            prompt_ms=100,
            generated_ms=500,
            time_to_first_byte_ms=80,
            end_to_end_ms=650,
        )
    )

    snapshot = runtime.dashboard_snapshot
    assert snapshot is not None
    assert snapshot.latest_request is not None
    assert snapshot.latest_request.server_compute_ms == 600
    runtime.stop()
