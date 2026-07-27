## 1. Project Foundation

- [x] 1.1 Create the Python package, launcher entry point, dependency metadata, and test layout for a Windows Tkinter application
- [x] 1.2 Define versioned application-settings and profile data models with field-level validation
- [x] 1.3 Implement `%LOCALAPPDATA%\LlamaCppLauncher` path resolution and atomic UTF-8 JSON load/save behavior
- [x] 1.4 Add tests for valid persistence, duplicate profile names, malformed stored data, and failed atomic replacement

## 2. Source Folders and Profiles

- [x] 2.1 Implement llama.cpp folder validation that resolves only a directly contained `llama-server.exe`
- [x] 2.2 Implement non-recursive, deterministic GGUF discovery and refresh for a user-selected model folder
- [x] 2.3 Implement profile create, edit, duplicate, select, and confirmed-delete operations
- [x] 2.4 Preserve unavailable saved model paths while blocking launch until the user chooses a valid discovered model
- [x] 2.5 Add tests for source-folder validation, GGUF discovery, profile field persistence, invalid ports and numeric values, and missing models

## 3. Command Construction and Capability Validation

- [x] 3.1 Implement deterministic argument-vector construction for model, `--host`, `--port`, `-ngl`, `-c`, `-np`, `-fa`, and `--no-mmap`
- [x] 3.2 Parse custom arguments with Windows command-line semantics and reject conflicts with structured options
- [x] 3.3 Probe the resolved executable's `--help` output and validate `auto`, `single`, and `multi` GPU intent against reported capabilities
- [x] 3.4 Add command-construction tests for boolean flags, quoted custom values, conflicting options, GPU modes, and paths containing spaces

## 4. Process Lifecycle and Health

- [x] 4.1 Implement one-process ownership with `shell=False`, hidden-console Windows flags, and captured stdout/stderr
- [x] 4.2 Drain process output on background workers and publish bounded log events without blocking the UI
- [x] 4.3 Implement background `/health` polling and the `Starting`, `Ready`, `Stopping`, `Stopped`, and `Failed` state transitions
- [x] 4.4 Implement bounded graceful Stop, forced fallback termination, Restart, and close-time shutdown using only the owned process handle
- [x] 4.5 Add tests using controllable child-process and HTTP fixtures for readiness, early exit, timeout, log capture, restart ordering, and unrelated-process safety

## 5. Modern Pink Desktop UI

- [x] 5.1 Define reusable ttk color, typography, spacing, focus, hover, disabled, success, warning, and error styles for the modern pink visual system
- [x] 5.2 Build the main window with profile selection, endpoint/model summary, lifecycle controls, health state, and runtime log view
- [x] 5.3 Build profile editing for every structured field, GPU mode, custom arguments, validation messages, and create/duplicate/delete workflows
- [x] 5.4 Add native folder pickers for the llama.cpp and model folders plus model-list Refresh behavior
- [x] 5.5 Connect worker queues to Tkinter `after()` updates and keep Stop available during model loading
- [x] 5.6 Add UI behavior tests and visually inspect all major states at common Windows display scaling values

## 6. Windows Packaging and Verification

- [x] 6.1 Add a console-free PyInstaller onedir build configuration and include all required runtime resources
- [x] 6.2 Document Windows setup, folder selection, profile fields, lifecycle behavior, local data location, and packaging commands
- [x] 6.3 Run the complete automated test suite and record any environment-specific limitations
- [x] 6.4 Smoke-test the packaged executable without a Python installation, including profile persistence, hidden process startup, health readiness, log capture, and close-time shutdown

## 7. Modern UI Redesign

- [x] 7.1 Replace the ttk presentation layer with CustomTkinter and define reusable modern-pink colors, typography, rounded surfaces, spacing, and semantic states
- [x] 7.2 Reorganize the window into a profile rail plus separate spacious Settings and Runtime workspaces that remain usable at the minimum window size
- [x] 7.3 Add dedicated New profile and Rename dialogs with unique-name validation and a prominent active-profile heading
- [x] 7.4 Add cancellable `after()`-driven workspace, status, and startup animations without delaying Stop or blocking the main thread
- [x] 7.5 Update automated UI behavior tests and visually verify major states, profile naming, animation, scrolling, and Windows display scaling
- [x] 7.6 Include CustomTkinter resources in the onedir package and repeat packaged startup, persistence, hidden-process, health, log, and close-time smoke tests

## 8. Context Allocation Hint

- [x] 8.1 Show a live per-slot context calculation below the Context title only when `-np` is greater than one
- [x] 8.2 Add calculation and UI update tests, then rebuild the Windows bundle
