## Verification

- Automated suite: `81 passed` on Windows 11 with Python 3.14.3 and PyQt6 6.11.0.
- UI stress coverage: 600 queued process-output events, telemetry coalescing, repeated resize, lifecycle state, asynchronous close, profile CRUD, glossary CRUD, persistence, keyboard focus, and accessibility labels.
- Visual coverage: Settings, LRR, and Runtime inspected at `960x640`; Runtime additionally inspected with Windows Qt rendering at 100% and simulated 150% (`QT_SCALE_FACTOR=1.5`). The 230-pixel dashboard remained below 40% of the 586-pixel Runtime page and Process output remained visible.
- Official build: `build.bat` passed its internal 81-test run and produced only `dist\LlamaCppLauncher.exe`.
- External-directory executable smoke: window opened with title `Llama.cpp Launcher`, closed cleanly, and had no adjacent `_internal` directory.
- Packaged self-smoke with isolated `LOCALAPPDATA`: visited pages `0,1,2`, persisted and reloaded profile `Packaged Smoke` and glossary `Packaged Terms`, then exited with code 0.
- Final artifact size: 40,431,641 bytes (38.56 MiB).
- Observed onefile cold start: approximately 3.2–3.4 seconds on the current machine.

## Coverage limits

- No llama.cpp executable or model was started; backend process/runtime/interceptor behavior is covered by the existing fake-server and unit tests.
- The executable was copied outside the repository but was not tested on a separate clean Windows installation.
- 150% scaling was exercised on the current Windows installation through Qt's scale factor; other display drivers, fonts, themes, and multi-monitor DPI transitions were not tested.
- Cold-start timing is a single-machine observation, not a benchmark guarantee.

## Interaction polish follow-up

- Removed the full-page `QGraphicsOpacityEffect`; 150 repeated page switches complete without attaching a graphics effect to any page.
- Added locally animated modern buttons and switches, rounded selectors, and numeric inputs without native stepper chrome.
- Generation telemetry now labels the current all-slot total and derives the per-active-slot average only when total throughput and a positive active-slot count are available.
- Both Runtime charts paint independent rounded surfaces and visible borders.
- Settings, LRR, and Runtime were visually inspected again at `960x640` using the Windows Qt platform.
- Restored the executable shell icon to both `QApplication` and the main window; packaged Windows probing confirmed a non-zero window icon handle.
- Final automated suite: `81 passed`.
- Final `build.bat` run succeeded and produced a single 40,439,647-byte (38.57 MiB) executable.
- Final external-directory smoke: cold start approximately 3.25 seconds, clean close, packaged page/persistence self-smoke passed, and no adjacent `_internal` directory.
