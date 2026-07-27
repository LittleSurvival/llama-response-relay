## Context

The repository has no launcher implementation or existing product specification. This change starts a Windows-only llama.cpp launcher from a clean baseline and intentionally does not reuse the previously supplied relay design.

Users need reusable profiles for common `llama-server.exe` arguments, a visible indication that the server is actually ready, and safe ownership of a background process whose console must remain hidden. The first release manages many saved profiles but runs at most one launcher-owned llama.cpp process at a time.

## Goals / Non-Goals

**Goals:**

- Provide a responsive Python desktop UI using CustomTkinter with a deliberate modern pink theme.
- Persist and validate named llama.cpp profiles.
- Translate structured profile values into an argument-vector launch command without invoking a shell.
- Run llama.cpp without a visible console, capture its output, and prove API readiness through a health check.
- Stop only the child process created by this launcher, including when the UI closes.
- Produce a Windows executable bundle suitable for end users.

**Non-Goals:**

- Relay or transform llama.cpp API traffic.
- Run several profiles simultaneously.
- Install, update, or download llama.cpp or GGUF models.
- Add a system tray, Windows startup registration, or minimized startup.
- Automatically tune numeric performance values through benchmarks.
- Support operating systems other than Windows in v1.

## Decisions

### CustomTkinter desktop application

Use Python 3.11+ with CustomTkinter, a Tkinter-based widget library, while retaining native Tk folder dialogs and the existing main-thread event model. Apply a light modern-pink visual system with rounded surfaces, neutral content areas, clear typography hierarchy, generous 16–24 px spacing, large click targets, and semantic success, warning, and error colors.

The window uses a persistent profile rail on the left and one focused workspace on the right. Settings and Runtime are separate views instead of two dense forms competing for width. Settings groups Source folders, Model and endpoint, Performance, and Advanced options into scrollable cards. Runtime keeps lifecycle controls, readiness feedback, and logs together. The action/status area remains visible while settings scroll.

Profile creation opens a dedicated name dialog before showing a new draft. Existing profiles expose an explicit Rename action; the active profile name is the dominant workspace heading. This avoids relying on users discovering an ordinary text field in a crowded form.

Short 160–220 ms transitions are scheduled with Tkinter `after()` at approximately 60 frames per second. View changes use eased motion, status treatment interpolates between semantic colors, and model startup uses indeterminate progress. Animations are cancellable and never sleep or block the main thread; lifecycle state remains authoritative and Stop is immediately usable during startup.

### User-selected source folders and many model profiles

Store a user-selected llama.cpp folder and model folder in application settings. Resolve the executable as `llama-server.exe` directly inside the selected llama.cpp folder. Populate the model selector from `.gguf` files directly inside the selected model folder, with an explicit refresh action and no recursive or whole-drive scan.

Store the following in each named profile:

- profile name
- GGUF model file path
- host
- port
- GPU layer count (`-ngl`)
- context size (`-c`)
- parallel slots (`-np`)
- flash-attention setting (`-fa`)
- no-memory-map flag (`--no-mmap`)
- GPU mode (`auto`, `single`, or `multi`)
- custom arguments

The selected model is persisted as its absolute file path so a profile remains unambiguous after restart. Shared source folders avoid repeating common paths. A later change can add per-profile llama.cpp folders or recursive model libraries if those become real requirements.

### GPU mode is an explicit profile intent

`auto` delegates GPU topology selection to llama.cpp and does not emit topology-selection arguments. `single` and `multi` record explicit user intent and are exposed in the profile UI, but v1 will only emit topology flags that the selected `llama-server.exe --help` reports as supported. Unsupported explicit selections fail validation with a useful message rather than guessing flags across llama.cpp versions.

This keeps the profile model stable while acknowledging that llama.cpp command-line support can differ by build. Numeric `-ngl` remains independently configurable.

### Safe command construction

Build the command as an argument vector beginning with the configured executable and selected model. Add structured arguments in a deterministic order, then append parsed custom arguments. Launch with `shell=False`.

Before starting, validate the source folders, resolved executable, selected model path, numeric ranges, host, port, duplicate profile name, and conflicts where custom arguments repeat structured options. Structured fields are the source of truth; conflicting custom arguments are rejected.

### JSON persistence with atomic replacement

Persist application settings and profiles under `%LOCALAPPDATA%\LlamaCppLauncher\` as UTF-8 JSON. Write a temporary file, flush it, and atomically replace the active file only after validation. Keep the in-memory last valid data if loading or saving fails.

JSON is sufficient for the initial local data model and remains easy to inspect and migrate.

### Single owned background process

The launcher holds the `subprocess.Popen` handle for the one active llama.cpp child. Start it with Windows flags that suppress a console window and redirect stdout/stderr for display in the UI. The UI never searches for or terminates processes by executable name.

Start is disabled while an owned process is active. Restart performs an orderly stop followed by a start of the currently selected profile.

### Health is separate from process state

After process creation, poll `http://<connect-host>:<port>/health` in a worker thread until it succeeds, the process exits, or a bounded timeout expires. For wildcard bind hosts, use `127.0.0.1` as the connection host. Present at least `Starting`, `Ready`, `Stopping`, `Stopped`, and `Failed` states.

The Tkinter main thread receives process output and state changes through a queue and `after()` polling; it must not block on process I/O or HTTP calls.

### Deterministic shutdown

On Stop or application close, request graceful child termination and wait for a bounded timeout. If the owned process remains alive, force termination and wait for it to exit before closing the UI. No system-tray continuation is provided.

### Windows executable packaging

Use PyInstaller to produce a console-free onedir distribution containing the launcher executable and required Python dependencies. The llama.cpp executable and models remain user-supplied external files.

An installer and code signing are outside v1; the packaging task will document the produced artifact and its validation limits.

## Risks / Trade-offs

- [llama.cpp folder layouts vary between builds] → Require `llama-server.exe` directly in the selected folder for v1 and report the expected path instead of guessing recursively.
- [llama.cpp flags vary between builds] → Probe the resolved executable's `--help`, validate supported structured flags, and surface incompatibilities before launch.
- [A subprocess pipe can block or freeze the UI] → Drain stdout/stderr continuously on worker threads and communicate through a bounded UI queue.
- [A health endpoint may differ in a custom build] → Use the standard `/health` behavior for v1 and report timeout separately from process exit.
- [Custom arguments can conflict with structured fields] → Parse without a shell and reject duplicate managed options.
- [CustomTkinter adds packaged data files] → Keep the existing onedir bundle and explicitly collect CustomTkinter themes and fonts in the PyInstaller specification.
- [Motion can distract or delay controls] → Keep transitions short and cancellable, animate presentation only, and update lifecycle control availability immediately.
- [Forced termination may leave llama.cpp cleanup incomplete] → Attempt graceful termination first and only force it after the configured timeout.

## Migration Plan

This is a new application with no existing user data to migrate. The first successful launch creates the local settings directory and an empty profile collection. Future schema revisions must add an explicit version field and migration path.

Rollback consists of closing the launcher, confirming its owned llama.cpp process has stopped, and removing the application bundle. User profiles in `%LOCALAPPDATA%` remain recoverable unless the user deletes them.

## Open Questions

- Whether a later version needs per-profile llama.cpp folders or recursive executable discovery.
- Whether a later version needs recursive model discovery or support for additional model file types.
- Whether explicit multi-GPU settings will need device selection and tensor-split controls beyond the initial mode.
- Whether users later need simultaneous profile instances, tray behavior, or Windows startup integration.
