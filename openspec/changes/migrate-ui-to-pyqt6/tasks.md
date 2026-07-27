## 1. Dependency and architecture setup

- [x] 1.1 Confirm that the intended distribution is compatible with PyQt6 licensing and record the release decision
- [x] 1.2 Replace the CustomTkinter runtime dependency with PyQt6 and add `pytest-qt` to development dependencies
- [x] 1.3 Create Qt bootstrap, main-window, page, component, style, and presentation/helper modules with no Tk imports
- [x] 1.4 Add shared modern-pink design tokens, QSS loading, DPI-aware application defaults, and a deterministic no-animation test mode
- [x] 1.5 Add pure presentation helpers for control state, endpoint text, metric availability, formatting, and context-per-slot calculations
- [x] 1.6 Add unit tests for presentation helpers and legacy settings-to-form mapping

## 2. Qt runtime integration

- [x] 2.1 Implement a Qt-owned runtime event bridge that drains `LauncherRuntime` events with a bounded count and time budget
- [x] 2.2 Coalesce superseded dashboard snapshots and batch process-output delivery before updating widgets
- [x] 2.3 Implement an asynchronous worker boundary for model discovery and other non-trivial filesystem work
- [x] 2.4 Implement non-blocking Start, Stop, and Restart dispatch with state-driven action availability
- [x] 2.5 Add tests for thread-safe event delivery, snapshot coalescing, burst logs, and lifecycle action states

## 3. Application shell and Settings page

- [x] 3.1 Implement `QApplication` bootstrap and the `LauncherWindow` navigation shell for Settings, LRR, and Runtime
- [x] 3.2 Implement reusable cards, labeled fields, semantic buttons, switches, path pickers, validation messages, and confirmation/name dialogs
- [x] 3.3 Implement the profile list and named profile create, select, rename, save, delete, dirty-draft, and active-profile flows
- [x] 3.4 Implement llama.cpp folder and model-folder selection with asynchronous GGUF discovery and Refresh
- [x] 3.5 Implement all launch fields and flags: host, port, GPU layers, context, parallel slots, flash attention, no-mmap, GPU mode, and custom arguments
- [x] 3.6 Implement the dynamic per-slot context hint and field-level validation/focus behavior
- [x] 3.7 Add Qt tests for profile CRUD, legacy settings loading, folder/model selection, validation, launch arguments, and context hints

## 4. LRR and glossary page

- [x] 4.1 Implement the LRR enabled switch, upstream/client endpoint settings, and the single LRR glossary selector
- [x] 4.2 Implement independent glossary create, select, rename, save, and delete flows without profile assignment UI
- [x] 4.3 Implement compact glossary entry rows with enabled control on the left, source/replacement fields, and Remove on the right
- [x] 4.4 Implement Add entry, row removal, validation, scrolling, selection persistence, and unsaved-draft handling
- [x] 4.5 Add Qt tests for LRR enablement, endpoint validation, glossary CRUD, selected-glossary persistence, and entry interactions

## 5. Runtime page and charts

- [x] 5.1 Implement Runtime header state, active profile, upstream/client endpoint labels, and Start/Stop/Restart controls
- [x] 5.2 Implement compact cards for uptime, throughput, slots/occupancy, deferred requests, session tokens, and latest-task timing/token details
- [x] 5.3 Implement bounded `QPainter` chart widgets for throughput and slot/deferred-request history with labels, current/peak values, and availability states
- [x] 5.4 Add throttled chart repainting, cached static layers, resize debounce, and latest-snapshot rendering
- [x] 5.5 Implement bounded batched process output with automatic follow behavior that does not override user scrollback
- [x] 5.6 Make the dashboard fit without overlap within 40 percent of Runtime content at `960x640` while leaving visible flexible process output
- [x] 5.7 Add Qt tests for active, stopped, failed, unsupported, unavailable, and stale dashboard states and minimum-size layout geometry
- [x] 5.8 Add stress tests covering at least 600 queued log events plus telemetry updates during repeated window resizing

## 6. Interaction, accessibility, and shutdown

- [x] 6.1 Add short non-blocking navigation/status animations and ensure tests and reduced-motion mode can disable them
- [x] 6.2 Define logical tab order, keyboard activation, visible focus styles, accessible names, and validation descriptions across all pages
- [x] 6.3 Implement idempotent asynchronous close coordination that shuts down launcher-owned llama.cpp and LRR without blocking paint events
- [x] 6.4 Add Qt tests for keyboard traversal, icon-only accessible names, validation focus, repeated close, and close during active runtime
- [x] 6.5 Replace the Tk manual preview with Qt fixtures for Stopped, Ready, Failed, Unsupported, and Stale states
- [x] 6.6 Visually inspect all preview states at `960x640` and larger sizes at 100 and 150 percent Windows scaling, recording any coverage limits

## 7. Cutover and legacy removal

- [x] 7.1 Switch `launcher.py`, `llamacpp_launcher.__main__`, and the GUI script entry point to the Qt bootstrap
- [x] 7.2 Remove production Tkinter/CustomTkinter imports, legacy Tk widget code, and CustomTkinter data collection after Qt parity tests pass
- [x] 7.3 Replace Tk-specific UI tests and ensure backend runtime, process, interceptor, telemetry, storage, and command tests remain unchanged and passing
- [x] 7.4 Search the production and test trees for obsolete Tk APIs, widget assumptions, timer callbacks, and stale documentation references

## 8. Onefile packaging and final validation

- [x] 8.1 Update `LlamaCppLauncher.spec` to validate and collect required PyQt6 platform plugins/resources while excluding unused Qt modules only when verified safe
- [x] 8.2 Update the canonical `build.bat` dependency checks and retain test-before-build, console-free, clean onefile behavior
- [x] 8.3 Run the complete automated test suite with Qt offscreen mode and resolve all regressions
- [x] 8.4 Run `build.bat` and verify that it produces only the portable `dist\LlamaCppLauncher.exe` deliverable without an `_internal` dependency
- [x] 8.5 Smoke-test the copied executable outside the repository for startup, legacy settings load, page navigation, profile/glossary persistence, and clean close
- [x] 8.6 Measure and report onefile size, cold-start behavior, resize responsiveness, and any unverified clean-machine or scaling coverage

## 9. Interaction polish and telemetry follow-up

- [x] 9.1 Remove full-page graphics effects and verify page switching has no stale frame or flash
- [x] 9.2 Implement modern locally animated button and switch components with keyboard, disabled, focus, and reduced-motion behavior
- [x] 9.3 Implement modern selector and numeric-input presentation and replace legacy-looking control instances across all pages
- [x] 9.4 Show generation throughput as all-slot total plus derived per-active-slot average with explicit unavailable handling
- [x] 9.5 Give each Runtime chart its own rounded surface and visible border without reducing plot readability
- [x] 9.6 Add regression tests and visually inspect Settings, LRR, Runtime, control states, page switching, and chart frames
- [x] 9.7 Restore the executable application icon on the Qt application, main window, and packaged taskbar entry
- [x] 9.8 Run the complete suite, rebuild through `build.bat`, and repeat external onefile smoke verification

## 10. Selector, icon, and throughput correction

- [x] 10.1 Bundle and apply the previous blue windowed application icon to source and packaged execution
- [x] 10.2 Position modern selector popups below their select bars without overlapping the originating control
- [x] 10.3 Treat llama.cpp's generation gauge as a per-slot average and derive the live all-slot total from active slots, with counter-delta fallback
- [x] 10.4 Add regression tests for popup placement, icon loading, and total/per-slot throughput semantics
- [x] 10.5 Run the complete suite, strict OpenSpec validation, and the canonical `build.bat` onefile build

## 11. CRUD stability, selector overflow, and LRR glossary rail

- [x] 11.1 Fix Qt clicked-signal argument leakage across profile and glossary New, Rename, Delete, Copy, and Add entry actions
- [x] 11.2 Remove the selector popup container's square frame, increase its preferred visible rows, and show a vertical scrollbar for overflow
- [x] 11.3 Replace the LRR glossary combo/action row with a profile-style left glossary rail and right LRR/editor workspace
- [x] 11.4 Add true button-click CRUD tests, selector overflow/frame tests, and glossary-rail selection tests
- [x] 11.5 Install a guarded global crash handler that presents copyable GUI and worker-thread tracebacks without terminating the Qt event loop
- [x] 11.6 Visually inspect the selector and LRR layout, run the full suite and strict OpenSpec validation, then rebuild with `build.bat`

## 12. Immediate profile drafts and glossary autosave

- [x] 12.1 Show a newly named unsaved profile immediately in the profile rail and reconcile that draft on save, rename, delete, or selection change
- [x] 12.2 Replace glossary switch confirmation dialogs with save-before-switch behavior and atomically keep rail selection and editor state aligned
- [x] 12.3 Ignore completely blank glossary entry rows during autosave while retaining inline validation and the current editor when a partial invalid row cannot be saved
- [x] 12.4 Add interaction regression tests, run the full suite and strict OpenSpec validation, and rebuild the onefile executable through `build.bat`
