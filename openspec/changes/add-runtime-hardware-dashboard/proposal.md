## Why

The Runtime page currently explains llama.cpp request activity but does not show whether CPU or GPU resources are saturated, thermally constrained, or running out of VRAM. A compact hardware dashboard gives users enough live system context to diagnose slow generation and choose better profile settings without opening a separate monitoring tool.

## What Changes

- Add a second, independently framed hardware dashboard between the existing inference dashboard and Process output.
- Show whole-system CPU utilization as a donut chart, plus current CPU frequency and llama-server process CPU utilization as text.
- Detect NVIDIA, AMD, and Intel GPUs and render a separate device card for every detected GPU.
- Show GPU utilization and VRAM occupancy as donut charts, with utilization, clock frequency, used/total VRAM, and temperature as text.
- Refresh hardware readings once per second without blocking Qt rendering or llama.cpp telemetry collection.
- Allow the hardware dashboard to be collapsed, remember that presentation state, and preserve useful Process output space at small window sizes.
- Treat unsupported, inaccessible, or temporarily missing sensors as partial data rather than an application error.

## Capabilities

### New Capabilities

- `runtime-hardware-monitoring`: Cross-vendor CPU/GPU sampling, responsive text-and-donut presentation, lifecycle handling, and partial-availability behavior for the Runtime page.

### Modified Capabilities

None.

## Impact

- Runtime page composition, responsive layout, and persisted UI presentation settings.
- Background telemetry lifecycle and the process manager interface needed to identify the owned llama-server process.
- New CPU and cross-vendor GPU monitoring dependencies or adapters, including one-file packaging support for any bundled runtime assets.
- Automated tests using deterministic fake hardware providers; real NVIDIA, AMD, and Intel hardware is not required for the test suite.
- No changes to llama.cpp launch arguments, LRR endpoints, profile data, glossary data, or external API behavior.
