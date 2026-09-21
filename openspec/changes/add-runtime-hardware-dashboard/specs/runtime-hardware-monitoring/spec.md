## ADDED Requirements

### Requirement: Runtime page includes an independent hardware dashboard
The application SHALL render a second, visually framed hardware dashboard between the existing llama.cpp inference dashboard and Process output on the Runtime page.

#### Scenario: Hardware dashboard is shown
- **WHEN** the user opens the Runtime page
- **THEN** the hardware dashboard is visible as a section distinct from both inference telemetry and Process output

#### Scenario: Process output remains usable
- **WHEN** the Runtime page is displayed at the minimum supported window size with the hardware dashboard expanded
- **THEN** Process output retains a usable minimum height or remains reachable through the page's scrolling behavior

### Requirement: CPU metrics use system and owned-process scope
The hardware dashboard SHALL show whole-system CPU utilization, current CPU frequency, and normalized CPU utilization for the launcher-owned llama-server process when that process exists.

#### Scenario: Server is running
- **WHEN** a launcher-owned llama-server process is running and CPU metrics are available
- **THEN** the dashboard shows system CPU utilization, current CPU frequency, and that process's CPU utilization normalized to total logical CPU capacity

#### Scenario: Server is stopped
- **WHEN** no launcher-owned llama-server process is running
- **THEN** system CPU utilization and frequency continue updating and process CPU is shown as unavailable

#### Scenario: Unrelated server exists
- **WHEN** an unrelated llama-server process is running but the launcher does not own it
- **THEN** the dashboard does not report that unrelated process as launcher process CPU usage

### Requirement: GPU monitoring covers NVIDIA, AMD, and Intel
The hardware monitoring layer SHALL detect supported NVIDIA, AMD, and Intel GPUs and SHALL expose one logical device record per detected physical GPU.

#### Scenario: Single supported GPU
- **WHEN** one supported NVIDIA, AMD, or Intel GPU is detected
- **THEN** the dashboard shows one GPU card labeled with its vendor and device name

#### Scenario: Multiple supported GPUs
- **WHEN** multiple GPUs are detected
- **THEN** the dashboard shows a separate card for each physical GPU without combining or averaging their metrics

#### Scenario: Multiple providers report one GPU
- **WHEN** more than one provider reports the same physical GPU
- **THEN** the monitoring layer deduplicates the reports and displays one logical GPU card

#### Scenario: No supported GPU is detected
- **WHEN** no NVIDIA, AMD, or Intel GPU can be detected
- **THEN** the dashboard shows a non-fatal no-GPU or unavailable state while CPU monitoring continues

### Requirement: GPU cards expose live utilization, clock, VRAM, and temperature
Each GPU card SHALL expose device utilization, current core clock frequency, VRAM used and total, VRAM occupancy, and temperature whenever the provider supplies those fields.

#### Scenario: Complete GPU sample
- **WHEN** all required fields are available for a GPU
- **THEN** its card shows utilization percentage, clock frequency, used and total VRAM, VRAM occupancy percentage, and temperature in Celsius

#### Scenario: Individual sensor is unsupported
- **WHEN** a detected GPU does not expose one required sensor
- **THEN** the unsupported field is shown as unavailable without hiding the device or suppressing its remaining fields

#### Scenario: Invalid provider value
- **WHEN** a provider returns a negative, non-finite, or out-of-range percentage value
- **THEN** the application treats that field as unavailable and does not pass the invalid value to the chart

### Requirement: Percentage metrics use donut charts and scalar metrics use text
The dashboard SHALL render system CPU utilization, per-GPU utilization, and per-GPU VRAM occupancy as donut charts, while frequency, temperature, and exact VRAM values SHALL be rendered as text.

#### Scenario: Percentage sample updates
- **WHEN** a new valid utilization or VRAM occupancy sample arrives
- **THEN** the matching donut updates its fill and center value without recreating the containing card

#### Scenario: Scalar sample updates
- **WHEN** frequency, temperature, or VRAM byte values change
- **THEN** their textual values update with an appropriate unit and no artificial percentage is calculated

#### Scenario: Percentage is unavailable
- **WHEN** a donut-backed metric is unavailable
- **THEN** the donut uses a neutral unavailable appearance and does not imply zero utilization

### Requirement: Hardware metrics refresh every second without blocking the UI
The application SHALL request a hardware sample every one second while the Runtime page is visible and SHALL perform provider access outside the Qt UI thread.

#### Scenario: Runtime page remains visible
- **WHEN** the Runtime page remains visible and providers respond normally
- **THEN** the displayed hardware snapshot refreshes approximately once per second

#### Scenario: Runtime page is hidden
- **WHEN** the user navigates away from the Runtime page
- **THEN** recurring hardware polling is suspended

#### Scenario: Runtime page is revisited
- **WHEN** the user returns to the Runtime page
- **THEN** an immediate sample is requested and the one-second schedule resumes

#### Scenario: Provider call is slow
- **WHEN** a hardware provider takes longer than expected to respond
- **THEN** page navigation, window resizing, process controls, and Process output remain responsive and no overlapping poll is started

### Requirement: Hardware monitoring survives partial and transient failure
The application SHALL isolate hardware provider errors from application startup, llama.cpp telemetry, process control, and other hardware providers.

#### Scenario: Provider cannot initialize
- **WHEN** a GPU API, driver, runtime, permission, or bundled bridge is unavailable
- **THEN** the affected vendor or fields are marked unavailable and the launcher continues operating

#### Scenario: Provider recovers
- **WHEN** a previously failing provider later returns a valid sample
- **THEN** the dashboard resumes showing current data without requiring an application restart

#### Scenario: Snapshot becomes stale
- **WHEN** no fresh hardware snapshot has been received for more than three expected refresh intervals
- **THEN** the dashboard identifies existing values as stale or replaces them with an unavailable presentation rather than presenting them as current

#### Scenario: One GPU fails
- **WHEN** sampling one GPU raises an error
- **THEN** CPU and other GPU cards continue receiving updates

### Requirement: Multi-GPU layout remains readable
The dashboard SHALL preserve readable fixed-minimum card dimensions and SHALL provide horizontal scrolling when all GPU cards do not fit in the available width.

#### Scenario: Cards fit
- **WHEN** the CPU card and all GPU cards fit within the available width
- **THEN** they are visible without a horizontal scrollbar

#### Scenario: Cards overflow
- **WHEN** the cards exceed the available width
- **THEN** the card strip exposes a discoverable horizontal scrollbar and does not compress charts or labels below their minimum dimensions

#### Scenario: Window is resized
- **WHEN** the user continuously resizes the window
- **THEN** the dashboard relayout does not overlap elements, rebuild device widgets, or visibly stall page rendering

### Requirement: Hardware dashboard collapse state persists
The user SHALL be able to collapse and expand the hardware dashboard, and the application SHALL persist that presentation state independently from profiles and glossaries.

#### Scenario: User collapses the dashboard
- **WHEN** the user activates the hardware dashboard collapse control
- **THEN** hardware cards are hidden and additional vertical space becomes available to Process output

#### Scenario: User expands the dashboard
- **WHEN** the user activates the control while the dashboard is collapsed
- **THEN** the hardware cards become visible and an immediate hardware sample is requested

#### Scenario: Application restarts
- **WHEN** the user restarts the application after changing the collapse state
- **THEN** the Runtime page restores the last saved collapse state

### Requirement: One-file packaging includes hardware monitoring
The canonical `build.bat` workflow SHALL produce a console-free one-file executable that can initialize all bundled hardware monitoring adapters without depending on an `_internal` directory or files beside the executable.

#### Scenario: Canonical package is built
- **WHEN** `build.bat` completes successfully
- **THEN** `dist/LlamaCppLauncher.exe` contains the Python dependencies and runtime assets required by the hardware providers

#### Scenario: Packaged provider is unavailable on a machine
- **WHEN** the one-file executable runs on a machine without a compatible GPU API, driver, permission, or sensor
- **THEN** the application starts normally and displays partial availability instead of crashing

### Requirement: Hardware behavior is testable without physical GPUs
The hardware collector and dashboard SHALL support injected providers and deterministic snapshots so automated behavior does not require NVIDIA, AMD, or Intel hardware.

#### Scenario: Fake vendor devices are injected
- **WHEN** tests provide fake NVIDIA, AMD, and Intel devices
- **THEN** discovery, deduplication, metric formatting, chart values, and multi-GPU layout can be verified deterministically

#### Scenario: Fake failures are injected
- **WHEN** tests inject initialization errors, field errors, delays, stale timestamps, or device removal
- **THEN** partial availability, isolation, lifecycle, and recovery behavior can be verified deterministically
