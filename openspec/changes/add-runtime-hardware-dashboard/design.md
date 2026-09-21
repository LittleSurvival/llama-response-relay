## Context

The Runtime page currently receives llama.cpp metrics and slot snapshots from `telemetry.py` and renders a fixed-height inference dashboard above Process output. Hardware sampling has different failure modes: CPU data is local and inexpensive, while GPU sensors vary by vendor, driver, device generation, and permissions. Any sensor access must therefore remain outside the Qt UI thread and must not share a failure boundary with llama.cpp telemetry.

The distributed application is a console-free PyInstaller one-file executable built through `build.bat`. New native or managed monitoring assets must work after PyInstaller extraction and cannot require files beside the final executable.

The agreed product behavior is:

- whole-system CPU utilization, current CPU frequency, and normalized CPU utilization for the owned llama-server process;
- NVIDIA, AMD, and Intel GPU support;
- one card per detected GPU;
- CPU utilization, GPU utilization, and VRAM occupancy as donut charts;
- frequency and temperature as text rather than invented percentages;
- one-second live refresh, including while llama-server is stopped;
- an independently framed, collapsible second dashboard.

## Goals / Non-Goals

**Goals:**

- Present useful CPU and per-GPU saturation data without degrading resize, navigation, process startup, or output rendering responsiveness.
- Use a provider boundary that supports NVIDIA, AMD, and Intel while allowing individual sensors to be unavailable.
- Keep hardware collection independent from llama.cpp request telemetry and from the LRR interceptor.
- Preserve a usable Process output area at the minimum supported window size.
- Keep the canonical one-file `build.bat` packaging workflow functional.

**Non-Goals:**

- Historical hardware charts, recording, export, alerts, fan control, overclocking, or power-limit controls.
- Per-core CPU charts or per-process GPU attribution.
- CPU temperature in this change.
- Requiring llama-server to be running before system hardware can be monitored.
- Changing llama.cpp profiles, command-line arguments, LRR endpoints, or glossary behavior.

## Decisions

### 1. Isolate hardware sampling behind immutable snapshots and provider protocols

Add hardware-specific immutable models such as `CpuSample`, `GpuSample`, and `HardwareSnapshot`, plus provider protocols for CPU sampling and GPU discovery/sampling. The UI consumes only snapshots and never invokes a hardware API directly.

The production collector runs on a dedicated worker thread with a monotonic one-second schedule. A poll never overlaps the previous poll; slow or failed providers delay only hardware data. The worker emits a complete snapshot through a Qt-safe bridge, and shutdown joins or cancels it without blocking the UI indefinitely.

This is preferred over extending the llama.cpp `TelemetryCollector` because hardware monitoring has a different lifecycle and should remain available when no server session exists.

### 2. Use `psutil` for CPU and owned-process utilization

`psutil` supplies whole-system CPU utilization, the nominal frequency used as the calculation baseline, and process CPU accounting. On Windows, the displayed dynamic frequency comes from the locale-independent PDH `Processor Information(_Total)\% Processor Performance` counter multiplied by the nominal MHz. The counter is primed with one sample before publishing a value, so a fixed base clock is never presented as a live reading.

The process manager exposes the PID of only the launcher-owned llama-server process; the hardware collector does not search for or attach to unrelated `llama-server.exe` processes.

Process CPU utilization is normalized by logical CPU count to a 0–100% share of total machine capacity. When the process stops, the PID is absent, inaccessible, or has been reused, the process value becomes unavailable while system CPU sampling continues.

CPU temperature is excluded because Windows availability is not dependable through the CPU provider selected for this change.

### 3. Use a cross-vendor GPU provider registry with explicit fallback

GPU access is represented by a `GpuProvider` protocol with stable device identity, vendor, display name, utilization, core clock, VRAM used/total, and temperature fields.

The Windows implementation uses:

- NVML as the preferred NVIDIA adapter for reliable utilization, clock, memory, and temperature data.
- A LibreHardwareMonitor-based adapter for AMD and Intel, and as the fallback for NVIDIA devices not readable through NVML.

Devices reported by more than one adapter are deduplicated using stable identifiers when available, then vendor/name/index as a documented fallback. Provider priority chooses one source per field rather than averaging conflicting readings.

LibreHardwareMonitor and its bridge/runtime assets are loaded lazily and bundled into the one-file package. Provider initialization failures are converted into availability states. No missing driver, API, runtime, permission, or sensor can prevent application startup.

Alternatives considered:

- Vendor command-line tools (`nvidia-smi`, `amd-smi`, `xpu-smi`) were rejected as the primary interface because their installation and device coverage cannot be assumed.
- Windows performance counters alone were rejected because frequency, temperature, and dedicated VRAM coverage is inconsistent.
- One universal aggregate GPU value was rejected because it hides which device is saturated and conflicts with multi-GPU llama.cpp profiles.

### 4. Treat availability as field-level data

Every metric field can be available or unavailable independently. A detected GPU remains visible when only some sensors are readable. Missing values render as `Unavailable`/`—`; the last valid value is not presented as current after it becomes stale.

A snapshot older than three expected refresh intervals is marked stale. Repeated errors are rate-limited in logs and remain recoverable so a driver restart or later device discovery can restore data without restarting the launcher.

### 5. Render a compact responsive hardware dashboard

The hardware dashboard is a separate framed section between the existing inference dashboard and Process output.

- The CPU card contains one donut for system utilization and text for system frequency and llama-server process CPU.
- Each GPU card contains two donuts for device utilization and VRAM occupancy, plus text for clock frequency, VRAM used/total, and temperature.
- Wide layouts show the CPU card followed by GPU cards. Overflow GPU cards use horizontal scrolling with an always-discoverable scrollbar when needed.
- Donuts use lightweight custom Qt painting and update values in place; the widget tree is not rebuilt every second.
- The expanded section uses a bounded compact height. Process output retains a minimum useful height, and the existing page scroll behavior remains available at constrained window sizes.

The section is expanded by default. Its collapse state is stored as a UI presentation preference, not in profiles or glossaries.

### 6. Limit UI work and collection lifecycle

Hardware sampling starts with the application and continues once per second while the Runtime page is visible, even when llama-server is stopped. Navigating away suspends recurring hardware polls; returning triggers an immediate sample and restarts the one-second schedule. This avoids invisible background work while preserving the requested Runtime refresh rate.

Only changed labels, donut values, availability styling, and device membership are updated. Device widgets are created or removed only when discovery changes. Resize handling uses layout geometry without animated relayout or repeated stylesheet construction.

### 7. Validate behavior without requiring physical vendor hardware

Provider contracts and the dashboard accept injected fakes. Automated tests cover each vendor, multiple GPUs, partial sensor availability, errors, stale snapshots, process start/stop, collapse persistence, responsive overflow, and collector shutdown.

The packaging task must verify that `build.bat` produces the one-file executable with all provider assets. Physical hardware checks remain optional manual smoke tests and are not claimed by the automated suite.

## Risks / Trade-offs

- [AMD or Intel sensor coverage varies by driver and generation] → Keep field-level availability, show the device even with partial metrics, and test adapter mappings against captured provider fixtures.
- [LibreHardwareMonitor bridge or managed runtime increases one-file size and packaging complexity] → Load it lazily, include only required assets, add a packaged-startup smoke test, and keep adapters independently disableable.
- [Duplicate devices can be reported by multiple providers] → Prefer stable bus/device identifiers, document fallback identity rules, and test deduplication.
- [A hardware API can block or fail during driver reset] → Keep all calls off the UI thread, prevent overlapping polls, mark stale data, and isolate each provider error.
- [One card per GPU can exceed horizontal space] → Use a bounded horizontal card strip with a visible scrollbar rather than shrinking text and donuts below readable sizes.
- [One-second repainting can reintroduce UI stutter] → Update in-place only, avoid recreating widgets or styles, and add a UI responsiveness regression test around resize and page switching.
- [Process CPU percentage can be misunderstood on multi-core systems] → Normalize it to total machine capacity and label it separately from whole-system CPU.

## Migration Plan

1. Add provider-independent models, availability handling, and fake-backed tests.
2. Add CPU and GPU adapters plus lazy initialization and packaging metadata.
3. Expose the owned llama-server PID and integrate collector lifecycle with the application.
4. Add the hardware dashboard widgets and persisted collapse behavior.
5. Run focused tests, the complete pytest suite, strict OpenSpec validation, and the canonical `build.bat` one-file packaging check.

Rollback removes the new collector, provider dependencies/assets, PID exposure, and hardware dashboard without altering saved profiles, glossaries, or LRR configuration.

## Open Questions

None. Unsupported sensors and vendor/device-specific gaps are intentionally represented as partial availability rather than blockers.
