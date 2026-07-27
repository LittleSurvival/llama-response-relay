## 1. Telemetry Domain and Parsing

- [x] 1.1 Add supported `--metrics` and `--slots` flags to launcher-owned commands, reject conflicting positive and negative custom options, and add command compatibility tests
- [x] 1.2 Add immutable native-sample, slot-state, request-summary, dashboard-snapshot, availability, and chart-sample models
- [x] 1.3 Implement tolerant Prometheus text and `/slots` JSON parsers with fixtures for labels, missing fields, extra fields, malformed values, and unsupported responses
- [x] 1.4 Implement generation-scoped session aggregation, counter baselines, session averages, occupancy, cache reuse, stale state, formatting, and a bounded 300-sample history
- [x] 1.5 Add aggregation tests for counter deltas and resets, missing denominators, uptime freeze, source fallback, and new-generation reset

## 2. Background Collection and Runtime Lifecycle

- [x] 2.1 Implement a bounded-timeout background collector for upstream `/metrics` and `/slots` with one-second polling and unsupported-endpoint backoff
- [x] 2.2 Integrate collector Start, Ready, Stop, Restart, failure, and Close ownership into `LauncherRuntime` with generation-tagged immutable events
- [x] 2.3 Retain a final stopped snapshot while discarding late samples from older process generations
- [x] 2.4 Add lifecycle tests for slow endpoints, partial telemetry, three-interval stale transitions, unsupported builds, clean shutdown, and restart isolation

## 3. LRR Request Performance Summaries

- [x] 3.1 Instrument non-streaming completion proxying to extract optional usage and timing fields and emit a numeric privacy-preserving request summary
- [x] 3.2 Instrument SSE proxying to measure first client-visible byte and final completion while extracting terminal usage and timing metadata
- [x] 3.3 Forward request summaries through `LauncherRuntime` without changing proxied JSON, SSE events, errors, or lifecycle state
- [x] 3.4 Add JSON and SSE tests for exact token, cache, server-time, TTFT, end-to-end, failed-request, missing-field, and no-content-retention behavior

## 4. Compact Runtime Dashboard UI

- [x] 4.1 Build a themed lightweight canvas chart component with bounded samples, independent labeled scales, current and peak values, and stale rendering
- [x] 4.2 Replace the Runtime summary with a compact lifecycle strip, dense metric cards, latest-task strip, throughput chart, and slot-pressure chart while preserving endpoints and lifecycle controls
- [x] 4.3 Bind dashboard snapshots and uptime ticks on Tk's main thread, format units compactly, and render Unsupported, Unavailable, Stale, Ready, and Stopped states
- [x] 4.4 Keep the complete dashboard at or below 40 percent of Runtime content height at `960x640`, leave Process output visible, and expand horizontally rather than vertically
- [x] 4.5 Add automated UI behavior and minimum-size layout tests, then visually verify idle, loading, active, saturated, queued, stale, unsupported, stopped, and restart states

## 5. Documentation and Release Verification

- [x] 5.1 Update the Chinese operating guide with metric definitions, five-minute retention, Client-endpoint scope, and unavailable-state explanations
- [x] 5.2 Run the complete automated suite and strict OpenSpec validation
- [x] 5.3 Rebuild the console-free Windows onedir bundle and smoke-test dashboard collection, Stop, Restart, and close-time cleanup against a supported llama.cpp server
