## ADDED Requirements

### Requirement: Present the launcher workflow
The Windows desktop UI SHALL provide profile selection, profile editing, llama.cpp folder selection, model-folder selection and model choice, Start, Stop, Restart, current state, health status, and runtime logs without requiring a console window.

#### Scenario: Launch from the main window
- **WHEN** the user selects a valid profile in the main window
- **THEN** the UI makes the Start action available and displays the profile's model and endpoint

#### Scenario: Controls reflect runtime state
- **WHEN** the owned process changes state
- **THEN** lifecycle controls are enabled or disabled to prevent invalid concurrent actions

### Requirement: Use a modern pink visual system
The UI SHALL use CustomTkinter to provide a consistent modern pink theme with rounded surfaces, defined accent, text, focus, hover, disabled, success, warning, and error treatments while retaining readable contrast.

#### Scenario: Visual consistency
- **WHEN** the user navigates between profile editing, status, and logs
- **THEN** typography, spacing, control states, and color roles remain consistent

#### Scenario: Error remains distinguishable
- **WHEN** validation or process failure is displayed
- **THEN** the error treatment is visually distinct from pink accent actions and includes explanatory text

### Requirement: Provide a spacious and focused layout
The UI SHALL use a persistent profile rail and separate Settings and Runtime workspaces, SHALL group related fields into cards with consistent spacing, and SHALL provide scrolling rather than compressing or clipping controls at the supported minimum window size.

#### Scenario: Edit a profile at minimum size
- **WHEN** the window is resized to its supported minimum dimensions
- **THEN** labels and controls do not overlap, primary actions remain reachable, and additional settings remain accessible by scrolling

#### Scenario: Inspect runtime output
- **WHEN** the user switches from Settings to Runtime
- **THEN** lifecycle controls, readiness detail, and process output are presented together without sharing horizontal space with the full settings form

### Requirement: Make profile naming explicit
The UI SHALL request a unique profile name in a dedicated creation flow, SHALL provide an explicit Rename action for a saved profile, and SHALL display the active profile name prominently.

#### Scenario: Create a named profile draft
- **WHEN** the user activates New profile and confirms a non-empty unique name
- **THEN** the launcher opens a new settings draft carrying that name

#### Scenario: Rename a saved profile
- **WHEN** the user activates Rename and confirms a valid unique name
- **THEN** the launcher persists the renamed profile and updates the profile rail and workspace heading

### Requirement: Animate presentation without blocking control
The UI SHALL provide short, smooth feedback for workspace and runtime-state changes using Tkinter-scheduled updates, and SHALL NOT delay lifecycle state or Stop availability for animation.

#### Scenario: Switch workspace
- **WHEN** the user switches between Settings and Runtime
- **THEN** the incoming workspace uses a short eased transition while the main thread remains responsive

#### Scenario: Model is starting
- **WHEN** runtime enters Starting
- **THEN** the UI shows animated loading feedback and enables Stop as soon as the process is active

### Requirement: Explain parallel context allocation
The profile editor SHALL show the approximate context available to each parallel slot directly below the Context title when `-np` is greater than one, and SHALL update the explanation as either `-c` or `-np` changes.

#### Scenario: Configure multiple parallel slots
- **WHEN** the user enters context size `8192` and parallel slots `4`
- **THEN** the Context field explains that each slot receives `2048` context

#### Scenario: Configure one parallel slot
- **WHEN** parallel slots is one
- **THEN** no per-slot context explanation is displayed

### Requirement: Remain responsive during background work
The UI SHALL keep all blocking process I/O and health checks off the Tkinter main thread and SHALL marshal state updates back to the UI safely.

#### Scenario: Server is loading a model
- **WHEN** llama.cpp takes an extended period to load a model
- **THEN** the window continues to repaint and allows the user to request Stop

### Requirement: Support source-folder selection
The UI SHALL provide native folder selection for the llama.cpp and model folders, SHALL display their paths, and SHALL provide a refresh action for the model selector.

#### Scenario: Select a model folder
- **WHEN** the user chooses a model folder through the folder dialog
- **THEN** the model selector is populated with GGUF files discovered in that folder

#### Scenario: Refresh a model folder
- **WHEN** the user adds a GGUF file to the selected folder and activates Refresh
- **THEN** the model selector updates without restarting the launcher

### Requirement: Exclude deferred shell features
The v1 UI SHALL close normally rather than minimizing to a system tray and SHALL not provide Windows autostart or minimized-start options.

#### Scenario: Close the main window
- **WHEN** the user closes the main window
- **THEN** the application begins owned-process shutdown instead of remaining active in a tray

### Requirement: Run as a packaged Windows application
The launcher SHALL be distributable as a console-free Windows executable bundle that starts without requiring users to install Python.

#### Scenario: Start packaged launcher
- **WHEN** a user starts the packaged executable on a supported Windows system
- **THEN** the desktop UI opens without a Python installation and without an extra console window
