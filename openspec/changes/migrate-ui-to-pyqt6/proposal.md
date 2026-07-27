## Why

The current CustomTkinter interface has reached practical limits in responsive layout, animation quality, rendering performance, and maintainability as the launcher, LRR, and telemetry features have grown. Migrating the complete desktop presentation layer to PyQt6 provides a stronger widget, layout, event, styling, and testing foundation while preserving the application's existing behavior and stored user data.

## What Changes

- Replace the CustomTkinter/Tkinter application shell, Settings, LRR, Runtime, dialogs, process output, and custom dashboard charts with a PyQt6 UI.
- Preserve existing profile, glossary, runtime, interceptor, telemetry, endpoint, and settings-file semantics; this is a presentation-layer migration rather than a backend or data-format redesign.
- Rebuild the modern pink visual system with Qt styles, reusable components, DPI-aware sizing, responsive layouts, and short non-blocking transitions.
- Connect background runtime events to the Qt event loop through signals, timers, and bounded update batches so process startup, high-volume output, telemetry updates, and window resizing remain responsive.
- Provide feature-parity UI tests with `pytest-qt`, including minimum-window layout, lifecycle controls, profile/glossary workflows, dashboard states, event bursts, and close behavior.
- Update the console-free PyInstaller onefile package and canonical `build.bat` flow for PyQt6, and remove the CustomTkinter/Tkinter runtime dependency after parity is complete.
- **BREAKING** for internal UI integrations: `LauncherApp` and Tk-specific widget/testing interfaces are replaced by Qt window and widget classes. Public launcher behavior, configuration storage, and client/upstream HTTP contracts remain compatible.

## Capabilities

### New Capabilities

- `pyqt6-desktop-ui`: Complete PyQt6 desktop shell, feature-parity workspaces, responsive modern-pink presentation, thread-safe event delivery, UI performance, accessibility, testing, and Windows onefile packaging.

### Modified Capabilities

None. The repository currently has no archived main specs; existing launcher, interceptor, and dashboard requirements remain behavioral inputs to the new PyQt6 capability.

## Impact

- Primary code: `llamacpp_launcher/ui.py`, `llamacpp_launcher/dashboard_widgets.py`, launcher entry points, and new Qt-focused UI modules/components.
- Preserved backend boundaries: `models.py`, `storage.py`, `discovery.py`, `command.py`, `process.py`, `runtime.py`, `interceptor.py`, and `telemetry.py`, except for minimal adapter changes needed to expose events safely to Qt.
- Dependencies: add PyQt6 and `pytest-qt`; remove CustomTkinter once the migration cutover is complete.
- Tests and tooling: replace Tk-specific UI tests and manual preview setup with Qt equivalents; retain backend tests.
- Distribution: update `LlamaCppLauncher.spec` and `build.bat` while keeping a portable, console-free, single-file Windows executable.
- User data and network compatibility: existing settings JSON, profiles, glossaries, llama.cpp arguments, LRR enablement, and endpoint behavior are not migrated or reset.
