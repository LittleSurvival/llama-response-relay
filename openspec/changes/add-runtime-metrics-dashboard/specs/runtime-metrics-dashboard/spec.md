## ADDED Requirements

### Requirement: Present a compact Runtime dashboard
The launcher SHALL present lifecycle state, API endpoints, controls, headline metrics, latest-task metrics, and live charts within a non-scrolling dashboard region at the top of the Runtime workspace. At the supported minimum window size of `960x640`, the complete dashboard SHALL remain visible, SHALL use approximately the upper one-third and no more than 40 percent of the Runtime content height, and SHALL leave a visible flexible-height Process output region below it.

#### Scenario: Open Runtime at minimum size
- **WHEN** the window is `960x640` and the user opens Runtime
- **THEN** the complete dashboard, Start or Stop controls, and part of Process output are visible without scrolling

#### Scenario: Resize the Runtime workspace
- **WHEN** the Runtime workspace becomes wider or taller
- **THEN** metric cards and charts expand responsively without increasing the dashboard beyond 40 percent of the available content height

### Requirement: Report process and capacity state
The dashboard SHALL show the active profile, lifecycle state, upstream and client endpoints, process uptime, active slots, configured total slots, slot occupancy percentage, and deferred request count. Uptime SHALL use a monotonic process-generation clock, and occupancy SHALL equal active slots divided by total slots.

#### Scenario: Process is ready
- **WHEN** a profile with four slots has run for 65 seconds and two slots are processing
- **THEN** the dashboard shows Ready, `01:05` uptime, `2 / 4` active slots, and `50%` occupancy

#### Scenario: Requests are queued
- **WHEN** llama.cpp reports three deferred requests
- **THEN** the dashboard shows queue pressure of three without counting them as active slots

#### Scenario: Process stops
- **WHEN** the active process stops
- **THEN** uptime stops advancing, active slots become zero, and the final session snapshot remains visible with a Stopped label until the next Start

### Requirement: Collect native llama.cpp telemetry
For a launcher-owned process, the launcher SHALL enable `/metrics` and `/slots` when the selected llama.cpp build exposes the corresponding command-line options, SHALL poll the upstream endpoint outside the Tk thread, and SHALL normalize available native metrics into session prompt tokens, generated tokens, prompt throughput, generation throughput, active slots, deferred requests, and per-slot processing state.

#### Scenario: Build supports metrics and slots
- **WHEN** option probing reports `--metrics` and `--slots`
- **THEN** the launcher adds both managed options exactly once and begins polling after llama.cpp is Ready

#### Scenario: Compute session averages
- **WHEN** native counters report 1,200 generated tokens over 24 seconds of generation time
- **THEN** the dashboard reports session average generation throughput as `50.0 tok/s`

#### Scenario: Polling must not block the UI
- **WHEN** `/metrics` or `/slots` responds slowly
- **THEN** Runtime navigation, Stop, and window close remain responsive while the collector times out independently

### Requirement: Report observed request performance accurately
For requests passing through the LRR Client endpoint, the launcher SHALL record a numeric request summary containing endpoint, HTTP status, input tokens, generated tokens, cached prompt tokens, server prompt time, server generation time, time to first response byte for streaming requests, and LRR end-to-end duration. It SHALL NOT retain request or response text, headers, authorization values, or tool arguments.

#### Scenario: Complete a non-streaming request through LRR
- **WHEN** llama.cpp returns usage and timing metadata for a non-streaming completion
- **THEN** the latest-task strip shows exact input and generated token counts, cache reuse, server compute time, and LRR end-to-end duration

#### Scenario: Complete a streaming request through LRR
- **WHEN** a streaming completion sends its first client-visible event and later terminates
- **THEN** the summary reports time to first response byte and total LRR end-to-end duration for that request

#### Scenario: Request bypasses LRR
- **WHEN** a client calls the upstream llama.cpp endpoint directly or LRR is disabled
- **THEN** server-wide native metrics continue updating and request-only fields are marked unavailable rather than inferred from cumulative counters

### Requirement: Visualize bounded session history
The dashboard SHALL maintain at most five minutes of one-second samples in memory and SHALL render two compact charts: prompt and generation throughput over time, and slot occupancy with deferred-request pressure over time. Each chart SHALL identify its series, current value, peak value, and stale state without requiring hover interaction.

#### Scenario: Metrics update over time
- **WHEN** three or more telemetry samples are available
- **THEN** both charts advance chronologically and display current and peak values for the visible five-minute window

#### Scenario: A new profile starts
- **WHEN** a new process generation begins after Stop or Restart
- **THEN** token totals, latest-task data, and chart history reset before samples from the new process are accepted

#### Scenario: Counter resets unexpectedly
- **WHEN** a native cumulative counter becomes lower than its previous value
- **THEN** the collector starts a new baseline and does not display a negative rate

### Requirement: Degrade explicitly across llama.cpp versions
The dashboard SHALL treat `/metrics`, `/slots`, individual metric names, and response timing fields as independently optional. Missing, malformed, or temporarily unavailable telemetry SHALL NOT fail the owned process or LRR, and each affected value SHALL show Unsupported, Unavailable, or Stale while unaffected values continue updating.

#### Scenario: Metrics endpoint is unsupported
- **WHEN** the selected llama.cpp build lacks `--metrics` or `/metrics` returns a not-supported response
- **THEN** native token and throughput cards show Unsupported while uptime and any available slot or LRR request metrics continue working

#### Scenario: Collector loses contact
- **WHEN** no successful telemetry poll occurs for three polling intervals while the process remains active
- **THEN** the last values remain visible with a Stale indicator and the collector continues retrying with bounded frequency

#### Scenario: A stale generation reports late
- **WHEN** a telemetry result from a stopped or restarted process arrives after a new generation has begun
- **THEN** the launcher discards the stale result and leaves the current generation unchanged
