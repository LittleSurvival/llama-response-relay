from __future__ import annotations

import threading
import time

from llamacpp_launcher.telemetry import (
    Availability,
    DashboardSession,
    NativeSample,
    RequestSummary,
    TelemetryCollector,
    format_count,
    format_duration,
    format_ms,
    format_percent,
    format_rate,
    parse_prometheus_metrics,
    parse_slots,
)


METRICS = """
# HELP ignored ignored
llamacpp:prompt_tokens_total{model="pink"} 100
llamacpp:prompt_seconds_total 2
llamacpp:prompt_tokens_seconds 50
llamacpp:tokens_predicted_total 1200
llamacpp:tokens_predicted_seconds_total 24
llamacpp:predicted_tokens_seconds 50
llamacpp:requests_processing 2
llamacpp:requests_deferred 3
llamacpp:n_busy_slots_per_decode 1.5
llamacpp:unknown_metric 999
llamacpp:prompt_tokens_total NaN
malformed
"""


def test_prometheus_parser_tolerates_labels_unknown_and_malformed_values() -> None:
    sample = parse_prometheus_metrics(METRICS, timestamp=12.0)

    assert sample.timestamp == 12.0
    assert sample.metrics_state is Availability.AVAILABLE
    assert sample.prompt_tokens_total == 100
    assert sample.generated_tokens_total == 1200
    assert sample.generated_seconds_total == 24
    assert sample.requests_processing == 2
    assert sample.requests_deferred == 3


def test_slots_parser_accepts_dict_and_list_next_token_shapes() -> None:
    slots = parse_slots(
        [
            {
                "id": 0,
                "id_task": 9,
                "n_ctx": 4096,
                "is_processing": True,
                "next_token": {"n_decoded": 22},
                "extra": "ignored",
            },
            {
                "id": 1,
                "is_processing": False,
                "next_token": [{"n_decoded": 7}],
            },
            {"bad": "ignored"},
        ]
    )

    assert len(slots) == 2
    assert slots[0].is_processing is True
    assert slots[0].task_id == 9
    assert slots[0].decoded_tokens == 22
    assert slots[1].decoded_tokens == 7


def test_dashboard_session_aggregates_rates_slots_requests_and_resets() -> None:
    session = DashboardSession(3, "Pink", 4, started_at=0)
    first = session.record_native(
        NativeSample(
            timestamp=1,
            metrics_state=Availability.AVAILABLE,
            slots_state=Availability.AVAILABLE,
            prompt_tokens_total=100,
            prompt_seconds_total=2,
            prompt_tokens_per_second=50,
            generated_tokens_total=1200,
            generated_seconds_total=24,
            generated_tokens_per_second=50,
            requests_processing=2,
            requests_deferred=3,
            slots=parse_slots(
                [
                    {"id": 0, "is_processing": True},
                    {"id": 1, "is_processing": True},
                    {"id": 2, "is_processing": False},
                    {"id": 3, "is_processing": False},
                ]
            ),
        )
    )
    assert first.session_prompt_tokens == 100
    assert first.session_generated_tokens == 1200
    assert first.average_generated_tokens_per_second == 50
    assert first.active_slots == 2
    assert first.slot_occupancy == 0.5
    assert first.deferred_requests == 3

    reset = session.record_native(
        NativeSample(
            timestamp=2,
            metrics_state=Availability.AVAILABLE,
            slots_state=Availability.UNAVAILABLE,
            prompt_tokens_total=10,
            prompt_seconds_total=0.2,
            generated_tokens_total=5,
            generated_seconds_total=0.1,
            requests_processing=1,
        )
    )
    assert reset.session_prompt_tokens == 110
    assert reset.session_generated_tokens == 1205
    assert reset.current_generated_tokens_per_second == 5
    assert all(
        sample.generated_tokens_per_second is None
        or sample.generated_tokens_per_second >= 0
        for sample in reset.history
    )


def test_session_stale_final_snapshot_request_summary_and_bounded_history() -> None:
    session = DashboardSession(
        1, "Chat", 2, started_at=0, history_capacity=3
    )
    available = NativeSample(
        timestamp=1,
        metrics_state=Availability.AVAILABLE,
        slots_state=Availability.AVAILABLE,
        generated_tokens_total=10,
        generated_seconds_total=1,
        slots=parse_slots([{"id": 0, "is_processing": True}]),
    )
    session.record_native(available)
    for index in range(2, 6):
        snapshot = session.record_native(
            NativeSample(
                timestamp=float(index),
                metrics_state=Availability.UNAVAILABLE,
                slots_state=Availability.UNAVAILABLE,
            )
        )
    assert snapshot.metrics_state is Availability.STALE
    assert snapshot.slots_state is Availability.STALE
    assert len(snapshot.history) == 3

    summary = RequestSummary(
        endpoint="/v1/chat/completions",
        status=200,
        input_tokens=100,
        generated_tokens=20,
        cached_tokens=25,
        prompt_ms=100,
        generated_ms=400,
        time_to_first_byte_ms=150,
        end_to_end_ms=600,
    )
    with_request = session.record_request(summary)
    assert with_request.latest_request is not None
    assert with_request.latest_request.server_compute_ms == 500
    assert with_request.latest_request.cache_reuse == 0.25

    stopped = session.stop(stopped_at=7)
    assert stopped.stopped
    assert stopped.uptime_seconds == 7
    assert stopped.active_slots == 0
    assert session.snapshot(now=99).uptime_seconds == 7


def test_unsupported_sources_and_formatters() -> None:
    session = DashboardSession(
        1,
        "Old build",
        1,
        started_at=0,
        metrics_supported=False,
        slots_supported=False,
    )
    snapshot = session.snapshot(now=65)
    assert snapshot.metrics_state is Availability.UNSUPPORTED
    assert snapshot.slots_state is Availability.UNSUPPORTED
    assert format_duration(snapshot.uptime_seconds) == "01:05"
    assert format_count(1_250) == "1.2K"
    assert format_rate(3.25) == "3.2 tok/s"
    assert format_ms(1500) == "1.50s"
    assert format_percent(0.5) == "50%"


def test_collector_fetches_supported_sources_and_backs_off_unsupported() -> None:
    samples: list[NativeSample] = []
    received = threading.Event()
    calls = {"metrics": 0, "slots": 0}

    def fetcher(url: str, _timeout: float) -> tuple[int, str]:
        if url.endswith("/metrics"):
            calls["metrics"] += 1
            return 200, METRICS
        calls["slots"] += 1
        return 501, ""

    def callback(_generation: int, sample: NativeSample) -> None:
        samples.append(sample)
        if len(samples) >= 2:
            received.set()

    collector = TelemetryCollector(
        callback,
        fetcher=fetcher,
        interval_seconds=0.01,
        timeout_seconds=0.01,
    )
    collector.start(
        4,
        "http://127.0.0.1:8080",
        metrics_supported=True,
        slots_supported=True,
    )
    try:
        assert received.wait(1)
    finally:
        collector.stop()

    assert samples[0].metrics_state is Availability.AVAILABLE
    assert samples[0].slots_state is Availability.UNSUPPORTED
    assert calls["metrics"] >= 2
    assert calls["slots"] == 1


def test_collector_keeps_partial_slots_when_metrics_are_slow_or_unavailable() -> None:
    samples: list[NativeSample] = []
    received = threading.Event()

    def fetcher(url: str, _timeout: float) -> tuple[int, str]:
        if url.endswith("/metrics"):
            time.sleep(0.02)
            raise TimeoutError("slow")
        return 200, '[{"id":0,"is_processing":true},{"id":1,"is_processing":false}]'

    def callback(_generation: int, sample: NativeSample) -> None:
        samples.append(sample)
        received.set()

    collector = TelemetryCollector(
        callback,
        fetcher=fetcher,
        interval_seconds=0.01,
        timeout_seconds=0.01,
    )
    collector.start(
        8,
        "http://127.0.0.1:8080",
        metrics_supported=True,
        slots_supported=True,
    )
    assert received.wait(1)
    started = time.monotonic()
    collector.stop(timeout_seconds=1)

    assert time.monotonic() - started < 1
    assert samples[0].metrics_state is Availability.UNAVAILABLE
    assert samples[0].slots_state is Availability.AVAILABLE
    assert len(samples[0].slots) == 2
