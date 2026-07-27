## Why

Running `llama-server.exe` with different models and performance settings currently requires users to maintain command lines manually and monitor a hidden process themselves. A Windows desktop launcher will make reusable llama.cpp configurations easy to create, start, observe, and stop safely.

## What Changes

- Add a Windows-only desktop launcher with a spacious, modern pink visual style built with CustomTkinter.
- Let users select a llama.cpp folder and resolve `llama-server.exe` from that folder.
- Let users select a model folder and populate the model selector from GGUF files in that folder.
- Add persistent named profiles for the selected model path, host, port, GPU offload, context size, parallel slots, flash attention, memory mapping, GPU mode, and custom arguments.
- Make profile creation and renaming explicit through dedicated name dialogs and a clearly visible active-profile identity.
- Allow automatic or explicit GPU configuration per profile.
- Start one selected profile at a time without showing a llama.cpp console window.
- Stop or restart only the llama.cpp process owned by the launcher.
- Report process startup, API health, runtime state, and captured logs in the UI.
- Use short, non-blocking transitions and loading feedback so navigation and runtime state changes feel smooth without delaying Stop.
- Stop the managed llama.cpp process when the launcher exits.
- Package the launcher as a distributable Windows executable.
- Exclude system-tray integration, operating-system autostart, and minimized startup from this first version.

## Capabilities

### New Capabilities

- `launcher-profile-management`: Create, edit, validate, persist, select, and delete named llama.cpp launch profiles.
- `llama-process-control`: Build safe launch commands, manage a hidden llama.cpp child process, perform health checks, capture logs, and stop or restart the owned process.
- `launcher-desktop-ui`: Provide the Windows launcher workflow and modern pink presentation for profile selection, configuration, lifecycle controls, status, and logs.

### Modified Capabilities

None.

## Impact

- Introduces a new Windows desktop application and local profile storage.
- Requires CustomTkinter, child-process management, HTTP health checks, structured configuration validation, logging, and Windows executable packaging.
- Executes `llama-server.exe` from a user-selected llama.cpp folder and accesses GGUF files from a user-selected model folder, but does not install llama.cpp or manage model downloads.
