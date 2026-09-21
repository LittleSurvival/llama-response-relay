from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import queue
import threading
import time
from typing import Any

from .command import supports_option
from .interceptor import InterceptorServer, upstream_base_url
from .models import Glossary, Profile, ValidationError
from .process import OwnedProcessIdentity, ProcessManager, RuntimeEvent, RuntimeState
from .telemetry import (
    DashboardSession,
    DashboardSnapshot,
    NativeSample,
    RequestSummary,
    TelemetryCollector,
)


class LauncherRuntime:
    def __init__(
        self,
        *,
        process: ProcessManager | None = None,
        interceptor: InterceptorServer | None = None,
        collector: Any | None = None,
        event_capacity: int = 1000,
    ) -> None:
        self.process = process or ProcessManager()
        self.interceptor = interceptor or InterceptorServer()
        self.events: queue.Queue[RuntimeEvent] = queue.Queue(maxsize=event_capacity)
        self._state = RuntimeState.STOPPED
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._stopping = threading.Event()
        self._interceptor_host = "127.0.0.1"
        self._interceptor_port = 8081
        self._interceptor_enabled = True
        self._glossary: Glossary | None = None
        self._generation = 0
        self._dashboard_session: DashboardSession | None = None
        self.collector = collector or TelemetryCollector(self._handle_native_sample)
        if hasattr(self.interceptor, "set_request_summary_callback"):
            self.interceptor.set_request_summary_callback(
                self._handle_request_summary
            )
        threading.Thread(
            target=self._relay_process_events,
            name="launcher-runtime-events",
            daemon=True,
        ).start()

    @property
    def state(self) -> RuntimeState:
        with self._lock:
            return self._state

    @property
    def active_profile(self) -> str:
        return self.process.active_profile

    @property
    def is_active(self) -> bool:
        return self.process.is_active

    @property
    def owned_process(self) -> OwnedProcessIdentity | None:
        return self.process.owned_process

    @property
    def dashboard_snapshot(self) -> DashboardSnapshot | None:
        with self._lock:
            session = self._dashboard_session
        return session.snapshot() if session is not None else None

    def start(
        self,
        executable: Path,
        profile: Profile,
        help_text: str,
        *,
        interceptor_enabled: bool,
        interceptor_host: str,
        interceptor_port: int,
        glossary: Glossary | None,
        startup_timeout_seconds: float = 120.0,
    ) -> list[str]:
        with self._lifecycle_lock:
            self.collector.stop()
            self._stopping.clear()
            self._interceptor_enabled = interceptor_enabled
            self._interceptor_host = interceptor_host
            self._interceptor_port = interceptor_port
            self._glossary = deepcopy(glossary)
            self._active_profile_config = deepcopy(profile)
            self._generation += 1
            generation = self._generation
            self._metrics_supported = supports_option(help_text, "--metrics")
            self._slots_supported = supports_option(help_text, "--slots")
            self._dashboard_session = DashboardSession(
                generation,
                profile.name,
                profile.parallel_slots,
                metrics_supported=self._metrics_supported,
                slots_supported=self._slots_supported,
            )
            self._emit_dashboard(self._dashboard_session.snapshot())
            return self.process.start(
                executable,
                profile,
                help_text,
                startup_timeout_seconds=startup_timeout_seconds,
            )

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        with self._lifecycle_lock:
            self._stopping.set()
            message = (
                "Stopping LRR and llama.cpp."
                if self.interceptor.is_running
                else "Stopping llama.cpp."
            )
            self._set_state(RuntimeState.STOPPING, message)
            self.collector.stop()
            if self.interceptor.is_running:
                self.interceptor.stop(timeout_seconds=min(5.0, timeout_seconds))
            self.process.stop(timeout_seconds=timeout_seconds)
            self._finalize_dashboard()

    def restart(
        self,
        executable: Path,
        profile: Profile,
        help_text: str,
        *,
        interceptor_enabled: bool,
        interceptor_host: str,
        interceptor_port: int,
        glossary: Glossary | None,
        startup_timeout_seconds: float = 120.0,
        shutdown_timeout_seconds: float = 10.0,
    ) -> list[str]:
        self.stop(timeout_seconds=shutdown_timeout_seconds)
        return self.start(
            executable,
            profile,
            help_text,
            interceptor_enabled=interceptor_enabled,
            interceptor_host=interceptor_host,
            interceptor_port=interceptor_port,
            glossary=glossary,
            startup_timeout_seconds=startup_timeout_seconds,
        )

    def close(self, *, timeout_seconds: float = 10.0) -> None:
        self.stop(timeout_seconds=timeout_seconds)

    def _relay_process_events(self) -> None:
        while True:
            event = self.process.events.get()
            if event.kind == "log":
                self._emit(event)
                continue
            if event.state is RuntimeState.READY:
                self._start_interceptor_after_llama(event)
                continue
            if event.state is RuntimeState.FAILED and self.interceptor.is_running:
                try:
                    self.interceptor.stop()
                except ValidationError as exc:
                    self._emit(
                        RuntimeEvent(
                            kind="log",
                            message=f"LRR stop after llama.cpp failure: {exc}",
                            source="lrr",
                            timestamp=time.time(),
                        )
                    )
            if event.state is RuntimeState.FAILED:
                self.collector.stop()
                self._finalize_dashboard()
            if event.state is not None:
                with self._lock:
                    self._state = event.state
            self._emit(event)

    def _start_interceptor_after_llama(self, event: RuntimeEvent) -> None:
        if self._stopping.is_set() or not self.process.is_active:
            return
        profile_config = getattr(self, "_active_profile_config", None)
        if profile_config is None:
            self._set_state(
                RuntimeState.FAILED,
                "Active profile configuration is unavailable.",
            )
            return
        self.collector.start(
            self._generation,
            upstream_base_url(profile_config.host, profile_config.port),
            metrics_supported=self._metrics_supported,
            slots_supported=self._slots_supported,
        )
        if not self._interceptor_enabled:
            self._set_state(
                RuntimeState.READY,
                (
                    f'Profile "{self.process.active_profile}" is ready directly at '
                    f"{upstream_base_url(profile_config.host, profile_config.port)} "
                    "(LRR disabled)"
                ),
            )
            return
        self._set_state(
            RuntimeState.STARTING,
            "llama.cpp is ready; starting LRR interceptor.",
        )
        profile = self.process.active_profile
        try:
            active = self.process.active_profile
            if not active:
                return
            if profile_config.name != active:
                raise ValidationError("Active profile configuration is unavailable.")
            self.interceptor.start(
                self._interceptor_host,
                self._interceptor_port,
                upstream_base_url(profile_config.host, profile_config.port),
                self._glossary,
            )
        except ValidationError as exc:
            self._set_state(
                RuntimeState.FAILED,
                f"llama.cpp is ready, but LRR failed: {exc}",
            )
            return
        if self._stopping.is_set():
            self.interceptor.stop()
            return
        self._set_state(
            RuntimeState.READY,
            (
                f'Profile "{profile}" is ready through '
                f"http://{self._interceptor_host}:{self._interceptor_port}"
            ),
        )

    def _handle_native_sample(
        self, generation: int, sample: NativeSample
    ) -> None:
        with self._lock:
            session = self._dashboard_session
            if session is None or session.generation != generation:
                return
        self._emit_dashboard(session.record_native(sample))

    def _handle_request_summary(self, summary: RequestSummary) -> None:
        with self._lock:
            session = self._dashboard_session
        if session is None:
            return
        self._emit_dashboard(session.record_request(summary))

    def _finalize_dashboard(self) -> None:
        with self._lock:
            session = self._dashboard_session
        if session is not None:
            self._emit_dashboard(session.stop())

    def _emit_dashboard(self, snapshot: DashboardSnapshot) -> None:
        self._emit(
            RuntimeEvent(
                kind="telemetry",
                message="Runtime telemetry updated.",
                source="telemetry",
                timestamp=time.time(),
                generation=snapshot.generation,
                payload=snapshot,
            )
        )

    def _set_state(self, state: RuntimeState, message: str) -> None:
        with self._lock:
            self._state = state
        self._emit(
            RuntimeEvent(
                kind="state",
                state=state,
                message=message,
                timestamp=time.time(),
            )
        )

    def _emit(self, event: RuntimeEvent) -> None:
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
