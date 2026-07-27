## Context

The application currently has a large CustomTkinter presentation module that owns navigation, profile editing, glossary editing, process lifecycle controls, runtime event polling, dashboard rendering, dialogs, and shutdown behavior. `dashboard_widgets.py` also draws charts through Tk primitives. The service layer is already separated into profile/storage, discovery/command, process/runtime, interceptor, and telemetry modules, and its tests do not require the UI toolkit.

The migration must retain the launcher users already have: named profiles, manual llama.cpp and model folders, model discovery, launch arguments, LRR/glossary management, Start/Stop/Restart, endpoint display, runtime telemetry, bounded process output, and a portable console-free onefile build. Existing settings under the user data directory must load without conversion or loss.

PyQt6 introduces a new event model and packaging footprint. The migration therefore needs an explicit cutover architecture, deterministic thread ownership, a replacement test harness, and packaging validation rather than a widget-for-widget mechanical translation.

## Goals / Non-Goals

**Goals:**

- Replace every visible Tk/CustomTkinter surface with a cohesive PyQt6 application.
- Preserve existing application behavior, settings schema, network contracts, and backend module boundaries.
- Establish a maintainable UI structure with separate shell, pages, reusable components, view-model/adapters, styling, and chart code.
- Keep all blocking process, network, filesystem scan, and telemetry work away from the Qt GUI thread.
- Keep resizing, navigation, lifecycle actions, log ingestion, and dashboard updates visibly responsive under realistic load.
- Retain the modern pink identity while improving spacing, visual hierarchy, DPI scaling, focus states, and minimum-size behavior.
- Continue producing the application through `build.bat` as a console-free PyInstaller onefile executable.

**Non-Goals:**

- Redesigning the profile or glossary JSON schema.
- Changing llama.cpp command semantics, LRR routes, replacement behavior, telemetry calculations, or endpoint defaults.
- Adding tray behavior, autostart, authentication, remote management, or a new operating-system target.
- Running Tkinter and Qt side by side in the released application.
- Replacing backend worker threads merely to make them use Qt classes when an adapter is sufficient.

## Decisions

### 1. Use one Qt application and an explicit presentation structure

The entry point will create exactly one `QApplication` and one `LauncherWindow`. UI code will be split by responsibility:

- application bootstrap and global exception handling;
- main window, navigation, and close coordination;
- Settings, LRR, and Runtime pages;
- reusable inputs, cards, dialogs, status indicators, log view, and charts;
- a presentation/controller layer that maps stored models and `LauncherRuntime` events into Qt-safe page state;
- centralized palette, typography, spacing, and QSS.

This structure is preferred over translating the monolithic `LauncherApp` class in place because the latter would preserve the coupling and repaint problems that motivated the migration. A declarative `.ui`-file workflow was considered, but Python widget composition is selected so conditional forms, reusable components, and tests stay directly type-checkable and reviewable.

### 2. Preserve backend services and bridge their events into Qt

`LauncherRuntime` remains the lifecycle coordinator and its queue remains the cross-thread source of truth. A Qt-owned bridge uses a bounded `QTimer` drain on the GUI thread and emits typed signals for state, logs, dashboard snapshots, and errors. It drains only a capped number of events or a capped time budget per tick, coalesces superseded dashboard snapshots, and batches log appends.

Blocking calls such as model-folder discovery or any future long-running validation execute through a worker object/thread-pool boundary and return through queued signals. Widgets and models are only mutated on the GUI thread.

This adapter is preferred over making backend modules import PyQt6 because it keeps runtime/interceptor code headless-testable and avoids binding domain behavior to a desktop toolkit. An unbounded signal per output line was rejected because it can starve paint and resize events.

### 3. Use page-local state plus pure presentation helpers

Qt widgets will not become the canonical data store. Profile and glossary edits are represented as drafts and are converted through pure validation/mapping functions before `SettingsStore` persistence. Selection changes prompt or resolve unsaved edits consistently. Runtime-derived display values such as control availability, endpoint labels, context-per-slot, metric formatting, and availability text remain pure helpers where practical.

This preserves deterministic tests and prevents signal feedback loops from silently saving partially updated forms.

A newly named profile is represented by one explicit rail-only draft item immediately, before its required paths and model are valid enough for persistence. Saving replaces it through a normal profile-list refresh; renaming updates the same draft item; deleting removes it locally. Leaving the draft uses the existing profile unsaved-change decision, and no service lookup is attempted for a rail-only draft.

Glossary navigation uses save-before-switch rather than a modal decision. The outgoing glossary id remains authoritative until its draft successfully validates and persists; only then are the selected glossary id, rail item, heading, and editor advanced to the target. Fully blank entry rows are treated as unused UI placeholders and omitted, while partially filled invalid rows retain the original selection and show inline validation.

### 4. Build the modern pink system from tokens and reusable components

Colors, type scale, spacing, radii, borders, semantic states, and control heights will be centralized. QSS handles stable visual roles; small custom widgets handle behaviors QSS cannot express cleanly. Standard Qt controls, dialogs, layouts, splitters, scroll areas, and accessibility properties are retained instead of painting entire controls from scratch.

Page content switches synchronously without a full-page opacity or graphics effect, because forcing a complete page through an offscreen effect can leave a stale frame and delay the first paint. Motion is limited to small controls such as switch thumbs, button hover/press feedback, and lightweight navigation indicators; it never gates application state. Animations respect the platform reduced-motion preference when observable and have a no-animation path for tests.

Standard buttons, checkboxes, and selectors are wrapped by lightweight custom presentation components. Buttons animate only their own fill/border state, switches paint and animate an explicit track and thumb, combo boxes use a consistent rounded field and popup list, and numeric fields avoid native stepper chrome. These controls retain Qt focus, keyboard, enabled, checked, and accessibility semantics.

The supported minimum window remains `960x640`. Settings and LRR pages scroll vertically. Runtime uses a bounded top dashboard and a flexible process-output region; layout breakpoints reorganize cards and controls before text or widgets can overlap.

### 5. Replace Tk canvas charts with bounded Qt chart widgets

The two five-minute dashboard charts will use lightweight custom `QWidget` painting with `QPainter`. They consume the existing bounded telemetry series, cache static grid/label layers, and repaint at a throttled cadence. Resizes invalidate geometry once through a debounce timer; telemetry arriving faster than the visual cadence updates only the latest pending snapshot.

Qt Charts was considered but rejected because these are two small fixed-purpose plots and an additional charting module would add package size and complexity. The custom widgets must still expose visible series labels, current/peak values, stale/unsupported states, and accessible text without hover.

Each chart paints its own rounded surface and border so the two plots remain visually distinct inside the compact dashboard. llama.cpp's `predicted_tokens_seconds` gauge is calculated from generated tokens divided by accumulated per-slot generation time, so the launcher treats it as a weighted per-slot average. The live all-slot estimate is `gauge * active_slots`, while `delta(tokens_predicted_total) / delta(wall_time)` is used as an aggregate fallback when the gauge is absent. Configured but idle slots are never included. The UI presents the resulting all-slot total plus the per-active-slot average and marks either value unavailable when its required inputs are missing.

Modern selector popups are repositioned after Qt creates their popup container. They prefer the full selector width directly below the originating control and fall back above it only when the current screen has insufficient space, never overlapping the select bar.

The popup container itself is made frameless and transparent so only the rounded list surface is visible. Selectors prefer up to twelve measured rows rather than a short native default, constrain that height to the available screen side, and force an as-needed vertical scrollbar when additional items remain.

Profile and glossary button signals are connected through zero-argument adapters. This explicitly discards Qt's `clicked(bool)` payload instead of allowing it to bind to optional domain parameters such as a name, confirmation flag, or glossary entry.

LRR adopts the Settings page's master-detail structure: a fixed-width left glossary rail owns selection and CRUD actions, while a scrollable right workspace contains LRR endpoint settings and the selected glossary's entry editor. Selecting a glossary in the rail also persists it as the glossary used by LRR, preserving the existing single-selection behavior without a second combo box.

The production entry point installs one `CrashHandler` after `QApplication` creation. `sys.excepthook` formats GUI-callback tracebacks, `threading.excepthook` forwards background failures through a queued Qt signal, and a guarded presenter opens an application-modal crash-log dialog with a read-only traceback and Copy action. Dialogs are retained until closed, and the hooks never call `exit`; a reentrancy guard plus stderr fallback prevents failures in error presentation from recursively crashing the process.

The prior blue PyInstaller windowed icon is copied into a maintained project asset, loaded by the Qt application from source or `_MEIPASS`, and passed explicitly to the onefile `EXE` build. This prevents icon identity from depending on whichever Python executable launched the source tree.

### 6. Make shutdown and lifecycle transitions asynchronous

Start, Stop, and Restart commands are dispatched without blocking the GUI thread. During close, the window enters a closing state, disables new lifecycle actions, requests owned-runtime shutdown, and waits through timer-driven state observation. It closes normally when shutdown completes and offers a bounded failure path if it does not. No nested event loop or `wait()` call blocks painting.

### 7. Cut over tests and packaging with the toolkit

PyQt6 becomes a runtime dependency and `pytest-qt` a development dependency. UI tests run with Qt's offscreen platform where possible and cover state helpers, page workflows, focus/keyboard behavior, layout geometry, lifecycle delivery, burst logs, telemetry coalescing, and shutdown. A manual preview fixture supplies representative Ready, Failed, Unsupported, Stale, and stopped snapshots without starting llama.cpp.

`LlamaCppLauncher.spec` validates and bundles PyQt6 plugins/resources in onefile windowed mode. CustomTkinter data collection and dependency checks are removed. `build.bat` remains the only supported build entry point and performs tests before packaging. A packaged smoke test checks launch, settings load, page navigation, and clean close from a directory outside the repository.

## Risks / Trade-offs

- [PyQt6 substantially increases onefile size and extraction/start time] → Measure the artifact, exclude unused Qt modules/plugins conservatively, and prioritize correctness over aggressive exclusions.
- [GPL/commercial licensing confusion] → Use PyQt6 under its applicable GPL terms for this project and document the distribution implication before release; switch to PySide6 before implementation if the intended distribution is incompatible.
- [A large one-shot UI replacement can hide behavior regressions] → Build page parity behind tests and a manual preview, then perform one explicit entry-point cutover after Settings, LRR, and Runtime acceptance checks pass.
- [Queued output or telemetry can still overwhelm the GUI thread] → Bound the backend queue, cap per-tick drain work, coalesce snapshots, batch text insertion, cap retained log blocks, and throttle chart painting.
- [Qt platform plugin errors may appear only in the packaged executable] → Validate the onefile artifact on a clean Windows environment and keep plugin collection explicit in the spec.
- [High-DPI and font metrics vary across Windows systems] → Avoid fixed text geometry, use layouts and size policies, test 100% and 150% scaling, and assert non-overlap at the supported minimum size.
- [Close-time process cleanup can race with window destruction] → Centralize close coordination, disconnect callbacks only after runtime termination, and make repeated close requests idempotent.

## Migration Plan

1. Add PyQt6 and the Qt test harness while leaving backend modules unchanged.
2. Introduce styling tokens, pure presentation helpers, and the runtime-to-Qt bridge with focused tests.
3. Implement the application shell and Settings page, including profile CRUD, folder dialogs, model refresh, validation, launch arguments, and context allocation hint.
4. Implement the LRR page, including independent glossary CRUD, entry editing, LRR enablement, selected glossary, endpoints, and validation.
5. Implement the Runtime page, lifecycle controls, status/endpoints, compact dashboard, charts, and bounded process output.
6. Implement close coordination, keyboard/focus/accessibility behavior, and manual preview states.
7. Switch both Python entry points to the Qt bootstrap and remove production imports of Tkinter/CustomTkinter.
8. Replace Tk-specific tests and dependencies, update the PyInstaller spec and `build.bat`, then validate source and packaged execution.

Rollback before release is to restore the prior entry point and dependencies while keeping backend modules and settings untouched. No user-data rollback is necessary because this change does not alter the persisted schema.

## Open Questions

- Confirm before public distribution whether the application can be released under PyQt6's GPL terms. If not, use PySide6 while retaining the same architecture and requirements; this must be resolved before implementation dependency lock-in.
