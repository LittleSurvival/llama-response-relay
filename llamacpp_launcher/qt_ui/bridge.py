from __future__ import annotations

from collections.abc import Callable
import queue
import time
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from ..process import RuntimeEvent
from ..runtime import LauncherRuntime


class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:  # surfaced to the Qt error boundary
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class RuntimeBridge(QObject):
    state_changed = pyqtSignal(object, str)
    logs_ready = pyqtSignal(list)
    telemetry_ready = pyqtSignal(object)
    error = pyqtSignal(str)
    work_finished = pyqtSignal()

    def __init__(
        self,
        runtime: LauncherRuntime,
        *,
        max_events_per_tick: int = 120,
        time_budget_ms: float = 5.0,
        interval_ms: int = 25,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.max_events_per_tick = max_events_per_tick
        self.time_budget_ms = time_budget_ms
        self.pool = QThreadPool.globalInstance()
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.drain)
        self.timer.start()

    def submit(
        self,
        function: Callable[[], Any],
        *,
        on_result: Callable[[Any], None] | None = None,
    ) -> FunctionWorker:
        worker = FunctionWorker(function)
        worker.signals.error.connect(self.error)
        if on_result is not None:
            worker.signals.result.connect(on_result)
        worker.signals.finished.connect(self.work_finished)
        self.pool.start(worker)
        return worker

    def drain(self) -> None:
        started = time.perf_counter()
        logs: list[str] = []
        latest_telemetry: object | None = None
        processed = 0
        while processed < self.max_events_per_tick:
            if (time.perf_counter() - started) * 1000 >= self.time_budget_ms:
                break
            try:
                event = self.runtime.events.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if event.kind == "log":
                prefix = f"[{event.source}] " if event.source else ""
                logs.append(prefix + event.message)
            elif event.kind == "telemetry" and event.payload is not None:
                latest_telemetry = event.payload
            else:
                self._emit_state(event)
        if logs:
            self.logs_ready.emit(logs)
        if latest_telemetry is not None:
            self.telemetry_ready.emit(latest_telemetry)
        if processed == self.max_events_per_tick:
            QTimer.singleShot(0, self.drain)

    def _emit_state(self, event: RuntimeEvent) -> None:
        if event.state is not None:
            self.state_changed.emit(event.state, event.message)
