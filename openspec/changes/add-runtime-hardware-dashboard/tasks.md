## 1. Hardware telemetry foundation

- [x] 1.1 Add immutable CPU, GPU, and hardware snapshot models with field-level availability, validation, stable device identity, and stale-state helpers.
- [x] 1.2 Define injectable CPU/GPU provider protocols and deterministic fake providers for tests.
- [x] 1.3 Add `psutil` dependency and implement whole-system CPU usage/frequency plus normalized owned-process CPU sampling.
- [x] 1.4 Implement GPU registry discovery, provider priority, stable-identity deduplication, per-device error isolation, and periodic recovery.
- [x] 1.5 Add the preferred NVIDIA NVML adapter for utilization, core clock, VRAM used/total, and temperature.
- [x] 1.6 Add the lazy LibreHardwareMonitor bridge and adapter for AMD, Intel, and NVIDIA fallback sensors.
- [x] 1.7 Implement a non-overlapping one-second hardware collector with immediate sampling, visible/hidden lifecycle controls, stale detection, rate-limited failures, and bounded shutdown.

## 2. Process and application integration

- [x] 2.1 Expose the PID and generation identity of only the launcher-owned llama-server process through `ProcessManager`.
- [x] 2.2 Connect process start/stop/restart events to hardware process-CPU sampling without attaching to unrelated processes or reused PIDs.
- [x] 2.3 Add a Qt-safe hardware snapshot bridge and start, suspend, resume, and stop it from the window/page lifecycle.
- [x] 2.4 Persist the hardware dashboard expanded/collapsed presentation preference independently from profiles and glossaries.

## 3. Hardware dashboard UI

- [x] 3.1 Implement a lightweight reusable donut widget with bounded percentage input, center text, neutral unavailable/stale states, and in-place repainting.
- [x] 3.2 Implement the CPU card with system utilization donut, current frequency text, and launcher-owned process CPU text.
- [x] 3.3 Implement reusable per-device GPU cards with utilization and VRAM donuts plus vendor/name, clock, exact VRAM, and temperature text.
- [x] 3.4 Add a framed, collapsible Hardware dashboard between the inference dashboard and Process output, expanded by default.
- [x] 3.5 Add responsive card sizing and a discoverable horizontal scrollbar for multi-GPU overflow while preserving a usable Process output area.
- [x] 3.6 Update existing card widgets and labels in place once per snapshot, creating or removing GPU cards only when device membership changes.
- [x] 3.7 Match the existing modern pink theme, focus behavior, unavailable styling, spacing, and accessibility labels without introducing overlapping elements.

## 4. Automated verification

- [x] 4.1 Test CPU sampling, logical-core normalization, owned-process start/stop behavior, PID reuse protection, invalid values, and missing frequency.
- [x] 4.2 Test NVIDIA, AMD, and Intel provider mapping, device deduplication, multi-GPU ordering, partial sensors, provider failure, recovery, and stale snapshots using fakes/fixtures.
- [x] 4.3 Test the one-second collector schedule, non-overlap, visibility suspension, immediate resume, exception isolation, and bounded shutdown.
- [x] 4.4 Add Qt tests for donut rendering states, CPU/GPU text formatting, dynamic device cards, collapse persistence, and no-GPU presentation.
- [x] 4.5 Add Runtime page layout tests at minimum and wide sizes, including multi-GPU overflow, visible scrollbar, preserved Process output space, repeated resize, and page switching.
- [x] 4.6 Run focused hardware tests and the complete pytest suite, recording any environment-specific skips without claiming physical GPU coverage.

## 5. Packaging and final validation

- [x] 5.1 Update project metadata, dependency checks, licenses/notices, and PyInstaller hooks/data so all hardware adapters and LibreHardwareMonitor assets are collected.
- [x] 5.2 Run strict OpenSpec validation for `add-runtime-hardware-dashboard`.
- [x] 5.3 Run the canonical `build.bat` workflow and verify the console-free `dist/LlamaCppLauncher.exe` starts without an `_internal` directory or adjacent provider files.
- [x] 5.4 Smoke-test the packaged executable's no-GPU/unsupported-provider startup path and document that NVIDIA, AMD, and Intel physical-device validation remains manual.
- [x] 5.5 Replace the Windows nominal/base CPU frequency display with locale-independent PDH dynamic frequency tracking and verify consecutive samples change independently of the base clock.
