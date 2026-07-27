from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
import json
import math
import re
import threading
import time
from typing import Callable
from urllib import error, request


class Availability(StrEnum):
    AVAILABLE = "Available"
    UNAVAILABLE = "Unavailable"
    UNSUPPORTED = "Unsupported"
    STALE = "Stale"


@dataclass(frozen=True, slots=True)
class SlotState:
    id: int
    is_processing: bool
    context_size: int | None = None
    task_id: int | None = None
    decoded_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class NativeSample:
    timestamp: float
    metrics_state: Availability = Availability.UNAVAILABLE
    slots_state: Availability = Availability.UNAVAILABLE
    prompt_tokens_total: float | None = None
    prompt_seconds_total: float | None = None
    prompt_tokens_per_second: float | None = None
    generated_tokens_total: float | None = None
    generated_seconds_total: float | None = None
    generated_tokens_per_second: float | None = None
    requests_processing: float | None = None
    requests_deferred: float | None = None
    busy_slots_per_decode: float | None = None
    slots: tuple[SlotState, ...] = ()


@dataclass(frozen=True, slots=True)
class RequestSummary:
    endpoint: str
    status: int
    input_tokens: int | None = None
    generated_tokens: int | None = None
    cached_tokens: int | None = None
    prompt_ms: float | None = None
    generated_ms: float | None = None
    time_to_first_byte_ms: float | None = None
    end_to_end_ms: float | None = None

    @property
    def server_compute_ms(self) -> float | None:
        if self.prompt_ms is None or self.generated_ms is None:
            return None
        return self.prompt_ms + self.generated_ms

    @property
    def cache_reuse(self) -> float | None:
        if (
            self.input_tokens is None
            or self.input_tokens <= 0
            or self.cached_tokens is None
        ):
            return None
        return max(0.0, min(1.0, self.cached_tokens / self.input_tokens))


@dataclass(frozen=True, slots=True)
class ChartSample:
    uptime_seconds: float
    prompt_tokens_per_second: float | None
    generated_tokens_per_second: float | None
    slot_occupancy: float | None
    deferred_requests: int | None


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    generation: int
    profile_name: str
    uptime_seconds: float
    total_slots: int
    active_slots: int | None
    slot_occupancy: float | None
    deferred_requests: int | None
    session_prompt_tokens: int | None
    session_generated_tokens: int | None
    average_prompt_tokens_per_second: float | None
    average_generated_tokens_per_second: float | None
    current_prompt_tokens_per_second: float | None
    current_generated_tokens_per_second: float | None
    metrics_state: Availability
    slots_state: Availability
    latest_request: RequestSummary | None
    history: tuple[ChartSample, ...]
    stopped: bool = False


_PROMETHEUS_LINE = re.compile(
    r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{.*\})?\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|[-+]?Inf|NaN)"
    r"(?:\s+\d+)?$"
)

_METRIC_FIELDS = {
    "llamacpp:prompt_tokens_total": "prompt_tokens_total",
    "llamacpp:prompt_seconds_total": "prompt_seconds_total",
    "llamacpp:prompt_tokens_seconds": "prompt_tokens_per_second",
    "llamacpp:tokens_predicted_total": "generated_tokens_total",
    "llamacpp:tokens_predicted_seconds_total": "generated_seconds_total",
    "llamacpp:predicted_tokens_seconds": "generated_tokens_per_second",
    "llamacpp:requests_processing": "requests_processing",
    "llamacpp:requests_deferred": "requests_deferred",
    "llamacpp:n_busy_slots_per_decode": "busy_slots_per_decode",
}


def parse_prometheus_metrics(text: str, *, timestamp: float | None = None) -> NativeSample:
    values: dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _PROMETHEUS_LINE.fullmatch(line)
        if match is None:
            continue
        field = _METRIC_FIELDS.get(match.group(1))
        if field is None:
            continue
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        values[field] = values.get(field, 0.0) + value
    return NativeSample(
        timestamp=time.monotonic() if timestamp is None else timestamp,
        metrics_state=Availability.AVAILABLE,
        **values,
    )


def parse_slots(payload: str | object) -> tuple[SlotState, ...]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, list):
        raise ValueError("Slot response must be a list.")
    slots: list[SlotState] = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            continue
        next_token = item.get("next_token")
        if isinstance(next_token, list):
            next_token = next(
                (entry for entry in next_token if isinstance(entry, dict)),
                None,
            )
        decoded = (
            next_token.get("n_decoded")
            if isinstance(next_token, dict)
            and isinstance(next_token.get("n_decoded"), int)
            else None
        )
        slots.append(
            SlotState(
                id=item["id"],
                is_processing=bool(item.get("is_processing", False)),
                context_size=(
                    item.get("n_ctx") if isinstance(item.get("n_ctx"), int) else None
                ),
                task_id=(
                    item.get("id_task")
                    if isinstance(item.get("id_task"), int)
                    else None
                ),
                decoded_tokens=decoded,
            )
        )
    return tuple(slots)


class DashboardSession:
    def __init__(
        self,
        generation: int,
        profile_name: str,
        total_slots: int,
        *,
        started_at: float | None = None,
        metrics_supported: bool = True,
        slots_supported: bool = True,
        history_capacity: int = 300,
    ) -> None:
        self.generation = generation
        self.profile_name = profile_name
        self.total_slots = max(1, int(total_slots))
        self.started_at = time.monotonic() if started_at is None else started_at
        self.metrics_state = (
            Availability.UNAVAILABLE
            if metrics_supported
            else Availability.UNSUPPORTED
        )
        self.slots_state = (
            Availability.UNAVAILABLE
            if slots_supported
            else Availability.UNSUPPORTED
        )
        self._history: deque[ChartSample] = deque(maxlen=history_capacity)
        self._lock = threading.RLock()
        self._stopped_at: float | None = None
        self._previous: dict[str, float] = {}
        self._accumulated: dict[str, float] = {}
        self._misses = {"metrics": 0, "slots": 0}
        self._last_sample_time: float | None = None
        self._active_slots: int | None = None
        self._deferred: int | None = None
        self._current_prompt_tps: float | None = None
        self._current_generated_tps: float | None = None
        self._latest_request: RequestSummary | None = None

    def record_native(self, sample: NativeSample) -> DashboardSnapshot:
        with self._lock:
            self.metrics_state = self._resolve_state(
                "metrics", self.metrics_state, sample.metrics_state
            )
            self.slots_state = self._resolve_state(
                "slots", self.slots_state, sample.slots_state
            )
            elapsed = (
                sample.timestamp - self._last_sample_time
                if self._last_sample_time is not None
                else None
            )
            prompt_delta = self._record_counter(
                "prompt_tokens", sample.prompt_tokens_total
            )
            generated_delta = self._record_counter(
                "generated_tokens", sample.generated_tokens_total
            )
            self._record_counter("prompt_seconds", sample.prompt_seconds_total)
            self._record_counter("generated_seconds", sample.generated_seconds_total)
            self._current_prompt_tps = self._current_rate(
                sample.prompt_tokens_per_second, prompt_delta, elapsed
            )
            self._current_generated_tps = self._current_rate(
                sample.generated_tokens_per_second, generated_delta, elapsed
            )
            if sample.slots_state is Availability.AVAILABLE:
                self._active_slots = sum(slot.is_processing for slot in sample.slots)
            elif (
                sample.metrics_state is Availability.AVAILABLE
                and sample.requests_processing is not None
            ):
                self._active_slots = max(0, round(sample.requests_processing))
            if (
                sample.metrics_state is Availability.AVAILABLE
                and sample.requests_deferred is not None
            ):
                self._deferred = max(0, round(sample.requests_deferred))
            occupancy = self._occupancy()
            self._history.append(
                ChartSample(
                    uptime_seconds=max(0.0, sample.timestamp - self.started_at),
                    prompt_tokens_per_second=self._current_prompt_tps,
                    generated_tokens_per_second=self._current_generated_tps,
                    slot_occupancy=occupancy,
                    deferred_requests=self._deferred,
                )
            )
            self._last_sample_time = sample.timestamp
            return self._snapshot_locked(sample.timestamp)

    def record_request(self, summary: RequestSummary) -> DashboardSnapshot:
        with self._lock:
            self._latest_request = summary
            return self._snapshot_locked(time.monotonic())

    def stop(self, *, stopped_at: float | None = None) -> DashboardSnapshot:
        with self._lock:
            if self._stopped_at is None:
                self._stopped_at = (
                    time.monotonic() if stopped_at is None else stopped_at
                )
            self._active_slots = 0
            return self._snapshot_locked(self._stopped_at)

    def snapshot(self, *, now: float | None = None) -> DashboardSnapshot:
        with self._lock:
            return self._snapshot_locked(time.monotonic() if now is None else now)

    def _record_counter(self, name: str, value: float | None) -> float | None:
        if value is None or value < 0:
            return None
        previous = self._previous.get(name)
        delta = value if previous is None or value < previous else value - previous
        self._previous[name] = value
        self._accumulated[name] = self._accumulated.get(name, 0.0) + delta
        return delta

    def _resolve_state(
        self,
        source: str,
        previous: Availability,
        incoming: Availability,
    ) -> Availability:
        if incoming is Availability.AVAILABLE:
            self._misses[source] = 0
            return incoming
        if incoming is Availability.UNSUPPORTED:
            self._misses[source] = 0
            return incoming
        self._misses[source] += 1
        if previous in {Availability.AVAILABLE, Availability.STALE} and self._misses[source] >= 3:
            return Availability.STALE
        return previous if previous is Availability.AVAILABLE else incoming

    @staticmethod
    def _current_rate(
        gauge: float | None,
        token_delta: float | None,
        elapsed: float | None,
    ) -> float | None:
        if gauge is not None and gauge >= 0:
            return gauge
        if token_delta is None or elapsed is None or elapsed <= 0:
            return None
        return max(0.0, token_delta / elapsed)

    def _occupancy(self) -> float | None:
        if self._active_slots is None:
            return None
        return max(0.0, min(1.0, self._active_slots / self.total_slots))

    def _average(self, token_name: str, second_name: str) -> float | None:
        tokens = self._accumulated.get(token_name)
        seconds = self._accumulated.get(second_name)
        if tokens is None or seconds is None or seconds <= 0:
            return None
        return max(0.0, tokens / seconds)

    def _snapshot_locked(self, now: float) -> DashboardSnapshot:
        end = self._stopped_at if self._stopped_at is not None else now
        return DashboardSnapshot(
            generation=self.generation,
            profile_name=self.profile_name,
            uptime_seconds=max(0.0, end - self.started_at),
            total_slots=self.total_slots,
            active_slots=self._active_slots,
            slot_occupancy=self._occupancy(),
            deferred_requests=self._deferred,
            session_prompt_tokens=_optional_int(
                self._accumulated.get("prompt_tokens")
            ),
            session_generated_tokens=_optional_int(
                self._accumulated.get("generated_tokens")
            ),
            average_prompt_tokens_per_second=self._average(
                "prompt_tokens", "prompt_seconds"
            ),
            average_generated_tokens_per_second=self._average(
                "generated_tokens", "generated_seconds"
            ),
            current_prompt_tokens_per_second=self._current_prompt_tps,
            current_generated_tokens_per_second=self._current_generated_tps,
            metrics_state=self.metrics_state,
            slots_state=self.slots_state,
            latest_request=self._latest_request,
            history=tuple(self._history),
            stopped=self._stopped_at is not None,
        )


FetchText = Callable[[str, float], tuple[int, str]]
SampleCallback = Callable[[int, NativeSample], None]


class TelemetryCollector:
    def __init__(
        self,
        callback: SampleCallback,
        *,
        fetcher: FetchText | None = None,
        interval_seconds: float = 1.0,
        timeout_seconds: float = 0.7,
    ) -> None:
        self.callback = callback
        self.fetcher = fetcher or fetch_text
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        generation: int,
        upstream_base: str,
        *,
        metrics_supported: bool,
        slots_supported: bool,
    ) -> None:
        self.stop()
        if not metrics_supported and not slots_supported:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            args=(
                generation,
                upstream_base.rstrip("/"),
                metrics_supported,
                slots_supported,
                self._stop,
            ),
            name="llama-telemetry",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 2.0) -> None:
        with self._lock:
            thread = self._thread
            stop = self._stop
        stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout_seconds)
        with self._lock:
            if self._thread is thread:
                self._thread = None

    def _run(
        self,
        generation: int,
        upstream_base: str,
        metrics_supported: bool,
        slots_supported: bool,
        stop: threading.Event,
    ) -> None:
        metrics_disabled = not metrics_supported
        slots_disabled = not slots_supported
        while not stop.is_set():
            timestamp = time.monotonic()
            metrics_state = (
                Availability.UNSUPPORTED
                if metrics_disabled
                else Availability.UNAVAILABLE
            )
            slots_state = (
                Availability.UNSUPPORTED
                if slots_disabled
                else Availability.UNAVAILABLE
            )
            fields: dict[str, object] = {}
            if not metrics_disabled:
                try:
                    status, body = self.fetcher(
                        upstream_base + "/metrics", self.timeout_seconds
                    )
                    if status == 200:
                        parsed = parse_prometheus_metrics(body, timestamp=timestamp)
                        metrics_state = Availability.AVAILABLE
                        for name in _METRIC_FIELDS.values():
                            fields[name] = getattr(parsed, name)
                    elif status in {404, 405, 501}:
                        metrics_state = Availability.UNSUPPORTED
                        metrics_disabled = True
                except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
                    metrics_state = Availability.UNAVAILABLE
            if not slots_disabled:
                try:
                    status, body = self.fetcher(
                        upstream_base + "/slots", self.timeout_seconds
                    )
                    if status == 200:
                        fields["slots"] = parse_slots(body)
                        slots_state = Availability.AVAILABLE
                    elif status in {404, 405, 501}:
                        slots_state = Availability.UNSUPPORTED
                        slots_disabled = True
                except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
                    slots_state = Availability.UNAVAILABLE
            self.callback(
                generation,
                NativeSample(
                    timestamp=timestamp,
                    metrics_state=metrics_state,
                    slots_state=slots_state,
                    **fields,
                ),
            )
            stop.wait(self.interval_seconds)


def fetch_text(url: str, timeout_seconds: float) -> tuple[int, str]:
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (error.URLError, OSError, TimeoutError) as exc:
        raise OSError(str(exc)) from exc


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return (
        f"{hours:d}:{minutes:02d}:{secs:02d}"
        if hours
        else f"{minutes:02d}:{secs:02d}"
    )


def format_count(value: int | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,}"


def format_rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} tok/s"


def format_ms(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1000:.2f}s" if value >= 1000 else f"{value:.0f}ms"


def format_percent(value: float | None) -> str:
    return "—" if value is None else f"{max(0.0, min(1.0, value)) * 100:.0f}%"


def _optional_int(value: float | None) -> int | None:
    return None if value is None else max(0, round(value))
