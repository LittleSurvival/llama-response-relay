from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
from typing import Any, Callable, IO, Protocol
from urllib import error, request

from .command import build_command
from .models import Profile, ValidationError


class RuntimeState(StrEnum):
    STARTING = "Starting"
    READY = "Ready"
    STOPPING = "Stopping"
    STOPPED = "Stopped"
    FAILED = "Failed"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    kind: str
    message: str
    state: RuntimeState | None = None
    source: str = ""
    timestamp: float = 0.0
    generation: int = 0
    payload: Any = None


class ProcessLike(Protocol):
    stdout: IO[str] | None
    stderr: IO[str] | None
    returncode: int | None

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def send_signal(self, sig: int) -> None: ...


PopenFactory = Callable[..., ProcessLike]
HealthChecker = Callable[[str, float], bool]


class ProcessManager:
    def __init__(
        self,
        *,
        popen_factory: PopenFactory = subprocess.Popen,
        health_checker: HealthChecker | None = None,
        event_capacity: int = 1000,
    ) -> None:
        self._popen_factory = popen_factory
        self._health_checker = health_checker or check_health
        self.events: queue.Queue[RuntimeEvent] = queue.Queue(maxsize=event_capacity)
        self._lock = threading.RLock()
        self._process: ProcessLike | None = None
        self._state = RuntimeState.STOPPED
        self._active_profile = ""
        self._generation = 0
        self._stop_requested = threading.Event()

    @property
    def state(self) -> RuntimeState:
        with self._lock:
            return self._state

    @property
    def active_profile(self) -> str:
        with self._lock:
            return self._active_profile

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start(
        self,
        executable: Path,
        profile: Profile,
        help_text: str,
        *,
        startup_timeout_seconds: float = 120.0,
    ) -> list[str]:
        if startup_timeout_seconds <= 0:
            raise ValidationError("Startup timeout must be positive.")
        command = build_command(executable, profile, help_text)
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise ValidationError("A llama.cpp process is already active.")
            self._generation += 1
            generation = self._generation
            self._stop_requested = threading.Event()
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            try:
                process = self._popen_factory(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    shell=False,
                    creationflags=creationflags,
                )
            except OSError as exc:
                self._set_state(RuntimeState.FAILED, f"Could not start llama.cpp: {exc}")
                raise ValidationError(f"Could not start llama.cpp: {exc}") from exc
            self._process = process
            self._active_profile = profile.name
            self._set_state_locked(
                RuntimeState.STARTING,
                f'Starting profile "{profile.name}" on {profile.host}:{profile.port}.',
            )
        self._start_reader(process.stdout, "stdout", generation)
        self._start_reader(process.stderr, "stderr", generation)
        threading.Thread(
            target=self._watch_exit,
            args=(process, generation),
            name="llama-exit-watch",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._watch_health,
            args=(
                process,
                generation,
                health_url(profile.host, profile.port),
                startup_timeout_seconds,
            ),
            name="llama-health-watch",
            daemon=True,
        ).start()
        return command

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds <= 0:
            raise ValidationError("Shutdown timeout must be positive.")
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                self._active_profile = ""
                self._set_state_locked(RuntimeState.STOPPED, "llama.cpp is stopped.")
                return
            self._stop_requested.set()
            self._set_state_locked(RuntimeState.STOPPING, "Stopping llama.cpp.")
        self._request_graceful_stop(process)
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self._emit("log", "Graceful stop timed out; forcing termination.", source="launcher")
            process.kill()
            try:
                process.wait(timeout=max(1.0, min(5.0, timeout_seconds)))
            except subprocess.TimeoutExpired as exc:
                self._set_state(RuntimeState.FAILED, "llama.cpp did not exit after force stop.")
                raise ValidationError("llama.cpp did not exit after force stop.") from exc
        with self._lock:
            if self._process is process:
                self._process = None
                self._active_profile = ""
            self._set_state_locked(RuntimeState.STOPPED, "llama.cpp stopped.")

    def restart(
        self,
        executable: Path,
        profile: Profile,
        help_text: str,
        *,
        startup_timeout_seconds: float = 120.0,
        shutdown_timeout_seconds: float = 10.0,
    ) -> list[str]:
        self.stop(timeout_seconds=shutdown_timeout_seconds)
        return self.start(
            executable,
            profile,
            help_text,
            startup_timeout_seconds=startup_timeout_seconds,
        )

    def close(self, *, timeout_seconds: float = 10.0) -> None:
        self.stop(timeout_seconds=timeout_seconds)

    def _request_graceful_stop(self, process: ProcessLike) -> None:
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                return
            except (OSError, ValueError):
                pass
        process.terminate()

    def _start_reader(
        self, stream: IO[str] | None, source: str, generation: int
    ) -> None:
        if stream is None:
            return
        threading.Thread(
            target=self._drain_stream,
            args=(stream, source, generation),
            name=f"llama-{source}",
            daemon=True,
        ).start()

    def _drain_stream(self, stream: IO[str], source: str, generation: int) -> None:
        try:
            for line in iter(stream.readline, ""):
                if generation != self._generation:
                    return
                self._emit("log", line.rstrip("\r\n"), source=source)
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _watch_exit(self, process: ProcessLike, generation: int) -> None:
        return_code = process.wait()
        with self._lock:
            if generation != self._generation or self._process is not process:
                return
            if self._stop_requested.is_set():
                return
            self._process = None
            self._active_profile = ""
            self._set_state_locked(
                RuntimeState.FAILED,
                f"llama.cpp exited unexpectedly with code {return_code}.",
            )

    def _watch_health(
        self,
        process: ProcessLike,
        generation: int,
        url: str,
        timeout_seconds: float,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and not self._stop_requested.is_set():
            if process.poll() is not None:
                return
            try:
                if self._health_checker(url, min(1.0, timeout_seconds)):
                    with self._lock:
                        if (
                            generation == self._generation
                            and self._process is process
                            and not self._stop_requested.is_set()
                        ):
                            self._set_state_locked(
                                RuntimeState.READY, f"llama.cpp API is ready at {url}"
                            )
                    return
            except Exception as exc:
                self._emit("log", f"Health check error: {exc}", source="health")
            self._stop_requested.wait(0.25)
        with self._lock:
            if (
                generation == self._generation
                and self._process is process
                and process.poll() is None
                and not self._stop_requested.is_set()
            ):
                self._set_state_locked(
                    RuntimeState.FAILED,
                    f"Health check timed out at {url}; process is still running.",
                )

    def _set_state(self, state: RuntimeState, message: str) -> None:
        with self._lock:
            self._set_state_locked(state, message)

    def _set_state_locked(self, state: RuntimeState, message: str) -> None:
        self._state = state
        self._emit("state", message, state=state)

    def _emit(
        self,
        kind: str,
        message: str,
        *,
        state: RuntimeState | None = None,
        source: str = "",
    ) -> None:
        event = RuntimeEvent(
            kind=kind,
            message=message,
            state=state,
            source=source,
            timestamp=time.time(),
        )
        try:
            self.events.put_nowait(event)
        except queue.Full:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            try:
                self.events.put_nowait(event)
            except queue.Full:
                pass


def health_url(host: str, port: int) -> str:
    connect_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    if ":" in connect_host and not connect_host.startswith("["):
        connect_host = f"[{connect_host}]"
    return f"http://{connect_host}:{port}/health"


def check_health(url: str, timeout_seconds: float) -> bool:
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            return 200 <= response.status < 300
    except (error.URLError, TimeoutError, OSError):
        return False
