## Context

The Runtime workspace currently has one summary card containing state, endpoints, progress, and lifecycle controls, followed by a Process output card that consumes the remaining height. `ProcessManager` owns one hidden llama.cpp process and already probes its help text, while `LauncherRuntime` coordinates that process with the in-process aiohttp LRR server. No structured telemetry is collected.

Current llama.cpp builds expose Prometheus-compatible `/metrics` when started with `--metrics`. Relevant counters and gauges include prompt and generated tokens and seconds, prompt and generation throughput, processing and deferred requests, and average busy slots. `/slots` is enabled by default in current builds and exposes `is_processing`, `n_ctx`, task identifiers, and per-slot progress. OpenAI-compatible completion responses may also contain `usage` and `timings`, but only LRR can measure request arrival, first response byte, and completion from the launcher's perspective.

The dashboard must fit above the existing logs at the `960x640` minimum size, remain responsive on Tk's main thread, support user-supplied llama.cpp versions, and avoid storing prompt or response content.

## Goals / Non-Goals

**Goals:**

- Show the server's current capacity, throughput, token volume, queue pressure, uptime, and latest observed request performance at a glance.
- Fit the complete dashboard in approximately the upper one-third of Runtime without introducing Runtime scrolling.
- Use native llama.cpp telemetry when available and LRR instrumentation only for request-scoped values that native cumulative metrics cannot provide.
- Keep collection, aggregation, and rendering bounded and generation-safe across Start, Stop, Restart, and Close.
- Preserve useful partial telemetry when a build lacks a metric or endpoint.

**Non-Goals:**

- Persist telemetry across application restarts or provide a long-term monitoring database.
- Estimate per-request latency or token counts for clients that bypass LRR.
- Collect prompt text, completion text, authorization headers, tool arguments, or other request payload data.
- Add GPU, VRAM, CPU, power, temperature, or operating-system process counters in this change.
- Replace Prometheus/Grafana for production fleet monitoring.
- Control, cancel, or reprioritize individual llama.cpp slots from the dashboard.

## Decisions

### Use native metrics for server-wide truth and LRR for request truth

Add `--metrics` and `--slots` as launcher-managed options only when `probe_help()` confirms support. Poll the upstream llama.cpp endpoint directly so metrics remain available regardless of whether LRR is enabled and without expanding LRR's public proxy routes.

Parse only the required Prometheus samples and tolerate comments, labels, reordered fields, missing metrics, and non-numeric values. Server-wide values come from:

- `prompt_tokens_total` and `tokens_predicted_total` for session volumes;
- prompt and predicted seconds for session averages;
- prompt and generation throughput gauges plus counter deltas for charts;
- `requests_processing` and `requests_deferred` for load and queue pressure;
- `/slots` `is_processing` and configured `-np` for exact occupancy when available.

LRR emits an immutable numeric request summary through a callback after a completion finishes or fails. For streaming responses it records first client-visible write and final write; for non-streaming it records request receipt through completed response construction. It extracts `usage` and `timings` when present but never retains request or response content. Native and request values remain visibly labeled because server compute duration and LRR end-to-end duration answer different questions.

Parsing stdout was considered, but log wording changes between llama.cpp versions and would couple correctness to log verbosity. Inferring per-request values from cumulative counters was rejected because concurrent requests make the result ambiguous.

### Introduce a generation-scoped background telemetry collector

Create a collector owned by `LauncherRuntime` with one daemon thread, a stop event, a monotonically increasing process-generation identifier, and bounded HTTP timeouts. It starts polling only after llama.cpp reaches Ready, polls `/metrics` and `/slots` approximately once per second, and emits immutable dashboard snapshots through the existing runtime event queue.

Every result carries its generation. Stop and Restart signal the collector before process shutdown, and UI consumers discard late events whose generation does not match. Three missed intervals mark data stale without failing the process. Unsupported endpoints back off for the remainder of that generation rather than producing one error per second.

Running collection inside Tk's `after()` loop was rejected because network delay would freeze navigation and Stop. A second asyncio loop was rejected because this collector performs two simple bounded reads and does not need to share LRR's lifecycle or public surface.

### Keep aggregation bounded and define every displayed number

Maintain a `DashboardSession` for the active process generation with at most 300 one-second samples, one latest request summary, start and stop monotonic timestamps, and counter baselines.

- Uptime is process-generation elapsed monotonic time, including model loading.
- Session prompt and generated tokens are native counter deltas from the first valid baseline.
- Average prompt and generation throughput are token deltas divided by their corresponding native processing-second deltas.
- Active slots prefer `/slots`; `requests_processing` is the fallback.
- Occupancy is clamped active slots divided by configured `parallel_slots`.
- Deferred requests are displayed separately and never included in occupancy.
- Server compute time is `prompt_ms + predicted_ms` when both are present.
- LRR end-to-end duration is request arrival through final response write.
- Cache reuse is `cached prompt tokens / input prompt tokens` when both are available.

Counter decreases create a new baseline. Missing denominators display unavailable rather than zero. Samples are never written to settings or disk.

### Use a dense two-row dashboard with CustomTkinter canvas charts

Replace the current Runtime summary card with a fixed maximum-height dashboard:

1. A compact lifecycle strip contains state, active profile, uptime, endpoints, Start/Stop/Restart, and stale or unsupported health.
2. A metrics row contains dense cards for generation speed, prompt speed, active slots and occupancy, queue depth, session tokens, and latest request.
3. Two lightweight canvases share the remaining dashboard width: throughput history and slot/queue pressure. Each displays a legend plus current and peak values so the chart remains understandable without hover.

At `960x640`, the dashboard is capped at 40 percent of Runtime content height and Process output remains visible. At wider sizes the cards expand rather than becoming taller. Drawing uses a small reusable canvas component and the existing pink palette; no plotting package is added to the Windows bundle.

A tabbed or vertically scrollable analytics page was rejected because the user asked for a complete at-a-glance dashboard in one-third of Runtime. A full plotting dependency was rejected because two bounded sparklines do not justify its bundle size and theming cost.

### Model unsupported, unavailable, and stale states separately

Each telemetry group carries availability and last-success metadata:

- Unsupported: option probing or a stable not-supported response proves the source unavailable for this process generation.
- Unavailable: the source is supported but has not produced a usable value yet, or the value does not apply because requests bypass LRR.
- Stale: a previously valid source has missed three polling intervals.

The collector logs only state transitions, not every failed poll. Dashboard failures never alter RuntimeState or Stop availability.

## Risks / Trade-offs

- [llama.cpp metric names or slot JSON fields change] → Parse fields independently, retain partial snapshots, add fixture coverage for missing and extra fields, and expose Unsupported or Stale states.
- [One-second polling adds local HTTP work] → Use two small loopback GET requests, bounded timeouts, one collector per generation, and endpoint backoff after stable unsupported responses.
- [Prompt throughput can dwarf generation throughput] → Give prompt and generation series independently labeled scales rather than implying one shared scale.
- [LRR duration includes client backpressure for streaming] → Label it LRR end-to-end, display native server compute separately, and document the distinction.
- [Direct upstream traffic creates incomplete latest-request data] → Never infer request summaries from cumulative metrics; visibly scope the latest-task card to Client endpoint traffic.
- [Dense cards become unreadable at minimum width] → Use short labels, unit-aware formatting, one-line secondary values, and layout tests at `960x640`.
- [Automatically managing metrics options conflicts with custom arguments] → Add positive and negative metrics/slots options to the managed-option conflict set and append only supported positive options.

## Migration Plan

1. Add telemetry models, Prometheus and slot parsers, aggregation tests, and managed command options.
2. Add generation-scoped collector lifecycle to `LauncherRuntime`.
3. Add privacy-preserving request summaries to JSON and SSE LRR paths.
4. Replace the Runtime summary layout with the compact dashboard and charts while retaining current controls, endpoints, progress, and logs.
5. Validate supported, partially supported, stale, stopped, restart, and minimum-size layouts.
6. Rebuild the Windows onedir bundle; no settings-schema migration is required because telemetry is session-only.

Rollback uses the previous executable. Settings remain compatible because this change adds no persisted fields.

## Open Questions

- Whether a later change should add optional GPU, VRAM, CPU, power, and temperature telemetry through platform-specific providers.
- Whether completed request summaries should later expand into an in-memory table instead of retaining only the latest request.
- Whether users will want selectable chart windows beyond the initial fixed five-minute session view.
