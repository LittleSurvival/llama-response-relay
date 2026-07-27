## Why

The Runtime page currently reports only lifecycle state, endpoints, progress, and raw process output, so users cannot tell whether llama.cpp is saturated, how fast it is generating, or how long requests actually take. A compact live dashboard will make capacity, throughput, token volume, and latency visible without displacing the existing controls and logs.

## What Changes

- Add a live llama.cpp status dashboard that fits within approximately the upper one-third of the Runtime workspace at the supported minimum window size.
- Show process uptime, active and total slots, slot occupancy, deferred requests, session prompt and generated token totals, prompt throughput, and average generation throughput.
- Show the latest observed task's input tokens, generated tokens, server compute time, end-to-end duration, and cache reuse when the request passed through LRR.
- Add compact rolling charts for prompt and generation throughput plus slot occupancy and deferred-request pressure.
- Automatically enable and poll supported llama.cpp metrics and slot endpoints for launcher-owned processes without blocking the Tk UI thread.
- Distinguish native server-wide metrics from LRR-observed request measurements and show explicit unavailable or stale states instead of estimated values.
- Reset session metrics and chart history when a new process generation starts, while retaining the current session's final snapshot after Stop.

## Capabilities

### New Capabilities

- `runtime-metrics-dashboard`: Collect, normalize, retain, and render live llama.cpp process, throughput, slot, token, queue, and request-latency telemetry in the Runtime workspace.

### Modified Capabilities

None.

## Impact

- Extends llama.cpp command construction to enable `--metrics` when supported and relies on the current `/slots` endpoint when available.
- Adds a background telemetry collector, Prometheus text parsing, bounded in-memory time-series and request-summary models, and runtime events for thread-safe UI updates.
- Extends the LRR request lifecycle to publish completion summaries without changing proxied API responses.
- Reorganizes the Runtime workspace into a fixed-height dashboard region above a flexible process-output region.
- Adds CustomTkinter-native lightweight charts and automated collector, aggregation, lifecycle, and layout tests without introducing an external charting dependency.
