from __future__ import annotations

import io
from pathlib import Path
import queue
import subprocess
import threading
import time

import pytest

from llamacpp_launcher.models import GpuMode, Profile, ValidationError
from llamacpp_launcher.process import ProcessManager, RuntimeEvent, RuntimeState, health_url


class FakeProcess:
    _next_pid = 4000

    def __init__(self, output: str = "", error: str = "") -> None:
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.stdout = io.StringIO(output)
        self.stderr = io.StringIO(error)
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.signals: list[int] = []
        self._done = threading.Event()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired("fake", timeout)
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.exit(0)

    def kill(self) -> None:
        self.killed = True
        self.exit(-9)

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        self.exit(0)

    def exit(self, code: int) -> None:
        self.returncode = code
        self._done.set()


class HangingProcess(FakeProcess):
    def terminate(self) -> None:
        self.terminated = True

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)


def profile(tmp_path: Path) -> Profile:
    model = tmp_path / "model.gguf"
    model.touch()
    return Profile(name="Test", model_path=str(model), gpu_mode=GpuMode.AUTO)


def test_owned_process_identity_tracks_only_active_generation(tmp_path: Path) -> None:
    process = FakeProcess()
    manager = ProcessManager(
        popen_factory=lambda *_args, **_kwargs: process,
        health_checker=lambda *_args: False,
    )
    manager.start(tmp_path / "llama-server.exe", profile(tmp_path), "")
    identity = manager.owned_process
    assert identity is not None
    assert identity.pid == process.pid
    assert identity.generation == 1
    process.exit(0)
    process.wait(timeout=0.1)
    assert manager.owned_process is None


def wait_for_state(manager: ProcessManager, state: RuntimeState, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager.state is state:
            return
        time.sleep(0.01)
    raise AssertionError(f"Did not reach {state}; current state is {manager.state}")


def drain_events(manager: ProcessManager) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    while True:
        try:
            events.append(manager.events.get_nowait())
        except queue.Empty:
            return events


def test_health_ready_and_log_capture(tmp_path: Path) -> None:
    child = FakeProcess("hello\n", "warning\n")
    manager = ProcessManager(
        popen_factory=lambda *_args, **_kwargs: child,
        health_checker=lambda _url, _timeout: True,
    )

    manager.start(tmp_path / "llama-server.exe", profile(tmp_path), "")
    wait_for_state(manager, RuntimeState.READY)
    events = drain_events(manager)

    assert {event.message for event in events if event.kind == "log"} >= {"hello", "warning"}
    manager.stop(timeout_seconds=0.1)
    assert manager.state is RuntimeState.STOPPED


def test_early_exit_is_failed(tmp_path: Path) -> None:
    child = FakeProcess()
    manager = ProcessManager(
        popen_factory=lambda *_args, **_kwargs: child,
        health_checker=lambda _url, _timeout: False,
    )
    manager.start(tmp_path / "llama-server.exe", profile(tmp_path), "")
    child.exit(17)

    wait_for_state(manager, RuntimeState.FAILED)
    assert any("code 17" in event.message for event in drain_events(manager))


def test_health_timeout_keeps_process_owned_for_stop(tmp_path: Path) -> None:
    child = FakeProcess()
    manager = ProcessManager(
        popen_factory=lambda *_args, **_kwargs: child,
        health_checker=lambda _url, _timeout: False,
    )
    manager.start(
        tmp_path / "llama-server.exe",
        profile(tmp_path),
        "",
        startup_timeout_seconds=0.05,
    )

    wait_for_state(manager, RuntimeState.FAILED)
    assert manager.is_active
    manager.stop(timeout_seconds=0.1)
    assert child.terminated or child.signals


def test_force_stop_after_timeout_and_unrelated_process_is_untouched(tmp_path: Path) -> None:
    owned = HangingProcess()
    unrelated = FakeProcess()
    manager = ProcessManager(
        popen_factory=lambda *_args, **_kwargs: owned,
        health_checker=lambda _url, _timeout: True,
    )
    manager.start(tmp_path / "llama-server.exe", profile(tmp_path), "")
    wait_for_state(manager, RuntimeState.READY)

    manager.stop(timeout_seconds=0.02)

    assert owned.killed
    assert unrelated.returncode is None
    assert manager.state is RuntimeState.STOPPED


def test_second_start_is_rejected(tmp_path: Path) -> None:
    child = FakeProcess()
    manager = ProcessManager(
        popen_factory=lambda *_args, **_kwargs: child,
        health_checker=lambda _url, _timeout: True,
    )
    selected = profile(tmp_path)
    manager.start(tmp_path / "llama-server.exe", selected, "")

    with pytest.raises(ValidationError, match="already active"):
        manager.start(tmp_path / "llama-server.exe", selected, "")
    manager.stop(timeout_seconds=0.1)


def test_restart_stops_before_creating_new_process(tmp_path: Path) -> None:
    children: list[FakeProcess] = []

    def factory(*_args: object, **_kwargs: object) -> FakeProcess:
        child = FakeProcess()
        children.append(child)
        return child

    manager = ProcessManager(popen_factory=factory, health_checker=lambda *_args: True)
    selected = profile(tmp_path)
    manager.start(tmp_path / "llama-server.exe", selected, "")
    wait_for_state(manager, RuntimeState.READY)
    manager.restart(
        tmp_path / "llama-server.exe",
        selected,
        "",
        shutdown_timeout_seconds=0.1,
    )

    assert len(children) == 2
    assert children[0].returncode is not None
    manager.stop(timeout_seconds=0.1)


def test_health_url_handles_wildcards_and_ipv6() -> None:
    assert health_url("0.0.0.0", 8080) == "http://127.0.0.1:8080/health"
    assert health_url("::", 8080) == "http://127.0.0.1:8080/health"
    assert health_url("::1", 8080) == "http://[::1]:8080/health"
