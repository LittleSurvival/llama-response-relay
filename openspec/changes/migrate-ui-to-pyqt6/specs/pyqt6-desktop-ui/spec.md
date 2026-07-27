## ADDED Requirements

### Requirement: Run the complete desktop interface on PyQt6
The application SHALL create its visible desktop interface with PyQt6, SHALL use one `QApplication` event loop, and SHALL NOT import or initialize Tkinter or CustomTkinter in the production launcher path.

#### Scenario: Start from Python
- **WHEN** the user starts `launcher.py` or the package GUI entry point
- **THEN** one PyQt6 main window opens without a Tk root or an additional console window

#### Scenario: Navigate the complete application
- **WHEN** the user moves among Settings, LRR, and Runtime
- **THEN** every page, dialog, control, chart, status surface, and process-output surface is a Qt widget

#### Scenario: Display the application icon
- **WHEN** the source or packaged application opens
- **THEN** the main window and taskbar use the executable's application icon rather than an empty Qt window icon

### Requirement: Preserve existing configuration and service behavior
The PyQt6 interface SHALL load and save the existing settings schema without destructive migration, SHALL preserve profile and glossary independence, and SHALL invoke the existing discovery, command, runtime, interceptor, and telemetry behavior without changing their external contracts.

#### Scenario: Open settings created by the prior UI
- **WHEN** a valid settings file containing profiles, glossaries, LRR settings, and selections was saved by the CustomTkinter version
- **THEN** the PyQt6 application presents equivalent values without resetting, renaming, or dropping fields

#### Scenario: Persist an edited configuration
- **WHEN** the user saves a profile or glossary in the PyQt6 interface
- **THEN** the existing storage layer receives a valid model whose serialized schema remains readable by the current backend

#### Scenario: Use LRR-selected glossary
- **WHEN** LRR is enabled and a glossary is selected in the LRR workspace
- **THEN** runtime startup uses that glossary independently of the selected llama.cpp profile

### Requirement: Provide complete Settings workflow parity
The Settings page SHALL support named profile create, select, rename, save, and delete operations; manual llama.cpp folder selection; manual model-folder selection; GGUF model discovery and refresh; and editing of `--host`, `--port`, `-ngl`, `-c`, `-np`, `-fa`, `--no-mmap`, single/multi-GPU choice, and custom arguments.

#### Scenario: Create and name a profile
- **WHEN** the user creates a profile and confirms a non-empty unique name
- **THEN** a draft bearing that name appears immediately in the profile rail, opens in the editor, and can be saved as the active profile

#### Scenario: Reconcile an unsaved profile draft
- **WHEN** the user saves, renames, deletes, or switches away from a newly created profile draft
- **THEN** the rail does not retain a stale duplicate and the visible selection and editor identify the same saved profile or current draft

#### Scenario: Activate profile actions
- **WHEN** the user clicks New, Rename, Copy, or Delete in the profile rail
- **THEN** Qt's button-state signal argument is not treated as a profile name or confirmation choice and the requested action completes without an unhandled exception

#### Scenario: Choose model sources
- **WHEN** the user chooses a llama.cpp folder and a model folder through native Qt folder dialogs
- **THEN** the paths are shown and the model selector lists discovered GGUF files from the selected model folder

#### Scenario: Refresh models
- **WHEN** the selected model folder changes on disk and the user activates Refresh
- **THEN** discovery runs without freezing the window and the model selector updates when it completes

#### Scenario: Explain divided context
- **WHEN** context is `8192` and parallel slots is `4`
- **THEN** the Context field shows that each slot receives approximately `2048` context

#### Scenario: Use one slot
- **WHEN** parallel slots is one
- **THEN** the per-slot context explanation is hidden

#### Scenario: Reject invalid profile data
- **WHEN** a required path, name, number, port, or mutually constrained argument is invalid
- **THEN** Save and Start do not commit the invalid draft and the relevant Qt field exposes an explanatory error

### Requirement: Provide independent LRR and glossary workflows
The LRR page SHALL provide an explicit LRR enabled switch, upstream and client endpoint settings, a single glossary selector used by LRR, glossary create, select, rename, save, and delete operations, and compact entry create, edit, enable, and remove operations.

#### Scenario: Create a glossary
- **WHEN** the user activates New, enters a unique glossary name, and confirms it
- **THEN** an independent glossary draft opens and entries can be added immediately

#### Scenario: Manage glossaries from a rail
- **WHEN** the LRR page is visible
- **THEN** saved glossaries and their New, Rename, and Delete actions appear in a left rail matching the Settings profile workflow while LRR settings and entries remain in the right workspace

#### Scenario: Activate glossary actions
- **WHEN** the user clicks New, Rename, Delete, or Add entry
- **THEN** Qt's button-state signal argument is discarded and the action completes without an unhandled exception

#### Scenario: Add a compact entry
- **WHEN** the user activates Add entry
- **THEN** a compact row appears with source and replacement inputs, an enabled control on the left, and a remove control on the right

#### Scenario: Select the glossary used by LRR
- **WHEN** the user chooses a saved glossary in the LRR glossary selector
- **THEN** that selection is persisted as the glossary used by LRR and no per-profile glossary assignment is shown

#### Scenario: Autosave before switching glossaries
- **WHEN** the current glossary has edited entries and the user selects another glossary in the rail
- **THEN** the current glossary is saved without a confirmation dialog before the target glossary is loaded, and the rail selection, heading, and entries all identify the target glossary

#### Scenario: Autosave a blank new entry
- **WHEN** a newly added glossary entry has both source and replacement empty and the user switches glossaries
- **THEN** the blank row is omitted from persistence and does not block the switch

#### Scenario: Reject an invalid partial entry during switching
- **WHEN** an edited glossary contains a partially filled invalid entry that cannot be saved
- **THEN** the switch is cancelled without a popup, an inline validation error is shown, and both the rail and editor remain on the original glossary

#### Scenario: Disable LRR
- **WHEN** the LRR switch is off and the user starts llama.cpp
- **THEN** the llama.cpp process can run without starting the response interceptor and the UI identifies the client endpoint as unavailable

### Requirement: Present a responsive modern pink interface
The application SHALL use a centralized modern pink visual system with defined typography, spacing, radii, accent, surface, focus, hover, disabled, success, warning, and error roles. Layouts SHALL remain readable at a supported minimum window size of `960x640` and under Windows display scaling without overlapping or clipped interactive controls.

#### Scenario: Resize continuously
- **WHEN** the user continuously resizes the window across supported dimensions
- **THEN** controls reflow or scroll without overlapping and resize feedback remains smooth

#### Scenario: Use the minimum size
- **WHEN** the application is displayed at `960x640`
- **THEN** navigation and primary page actions remain visible while overflow settings and glossary content remain reachable through page-local scrolling

#### Scenario: Distinguish semantic state
- **WHEN** the application displays focus, validation failure, runtime failure, warning, success, hover, or disabled state
- **THEN** each state uses a consistent treatment that remains distinguishable from the primary pink action

#### Scenario: Display at high DPI
- **WHEN** Windows display scaling is 150 percent
- **THEN** text remains legible and layouts use measured widget sizes rather than clipping fixed-position content

#### Scenario: Switch pages without a stale frame
- **WHEN** the user navigates among Settings, LRR, and Runtime
- **THEN** the destination page is painted immediately without a full-page opacity effect, retained frame, white flash, or input-blocking transition

#### Scenario: Interact with primary controls
- **WHEN** the user hovers, presses, focuses, checks, or disables a button, switch, selector, or numeric input
- **THEN** the control uses the modern pink component treatment with smooth local feedback while preserving keyboard and accessibility behavior

### Requirement: Keep the Qt event loop responsive
The application SHALL keep process control, process I/O, health checks, telemetry polling, and non-trivial filesystem discovery away from the Qt GUI thread. Cross-thread results SHALL enter the UI through queued Qt signals or GUI-thread timer drains with bounded work.

#### Scenario: Start a slow-loading model
- **WHEN** llama.cpp takes an extended time to become ready
- **THEN** the window continues painting, resizing, and navigating and Stop becomes usable as soon as the process is active

#### Scenario: Receive burst process output
- **WHEN** at least 600 process-output events arrive faster than the UI can render individual lines
- **THEN** the UI batches bounded log appends, retains its configured output limit, and continues servicing paint and input events

#### Scenario: Receive frequent telemetry
- **WHEN** multiple dashboard snapshots arrive before the next visual refresh
- **THEN** superseded snapshots are coalesced and the latest snapshot is eventually rendered without an unbounded UI event backlog

#### Scenario: Resize while running
- **WHEN** the user drags the window border while llama.cpp is running and telemetry and logs are updating
- **THEN** visible page geometry tracks the resize without prolonged stalls or repeated full-page reconstruction

### Requirement: Preserve safe lifecycle control
The PyQt6 interface SHALL expose Start, Stop, and Restart according to runtime state, SHALL dispatch lifecycle operations without blocking the GUI thread, and SHALL coordinate application close with shutdown of launcher-owned processes and LRR.

#### Scenario: Controls follow runtime state
- **WHEN** runtime moves through Stopped, Starting, Ready, Stopping, or Failed
- **THEN** lifecycle actions are enabled or disabled to prevent duplicate or invalid operations while preserving Stop whenever an owned process can be stopped

#### Scenario: Restart a running profile
- **WHEN** the user activates Restart
- **THEN** the current owned runtime is stopped and the selected saved configuration is started through a non-blocking state transition

#### Scenario: Close with a running process
- **WHEN** the user closes the main window while llama.cpp or LRR is owned by the launcher
- **THEN** the window begins asynchronous shutdown, prevents new starts, remains able to repaint, and exits after owned services stop or a bounded failure path is presented

### Requirement: Present unhandled errors without closing the application
The production Qt entry point SHALL install a guarded crash handler for unhandled GUI-callback and background-thread exceptions, SHALL present a readable copyable traceback, and SHALL keep the application event loop running whenever the handler itself remains operational.

#### Scenario: A UI action raises unexpectedly
- **WHEN** an exception escapes a Qt button callback or other Python GUI callback
- **THEN** an application-error dialog shows the exception type, message, and traceback and closing that dialog does not close the main window

#### Scenario: A worker thread raises unexpectedly
- **WHEN** an exception escapes a Python background thread
- **THEN** the traceback is forwarded safely to the GUI thread and shown through the same crash-log dialog

#### Scenario: The crash handler encounters an error
- **WHEN** presenting the crash dialog itself fails
- **THEN** the handler writes the original and handler errors to stderr without recursively invoking itself

### Requirement: Retain the compact Runtime dashboard
The Runtime page SHALL show active profile, lifecycle state, upstream and client endpoints, uptime, generation throughput, slot activity and occupancy, deferred requests, session tokens, latest-task token and timing data, two bounded five-minute charts, and process output. At `960x640`, the complete dashboard SHALL occupy no more than 40 percent of available Runtime content height and SHALL leave a visible flexible-height output region.

#### Scenario: Open Runtime at minimum size
- **WHEN** the Runtime page is shown at `960x640`
- **THEN** all dashboard cards and controls are readable without overlap and part of Process output remains visible

#### Scenario: Render active telemetry
- **WHEN** a Ready runtime publishes a supported telemetry snapshot
- **THEN** cards and charts display the latest normalized values, series labels, current values, peaks, and occupancy state

#### Scenario: Explain generation throughput across slots
- **WHEN** llama.cpp reports an average generation throughput of `20 tok/s` and four slots are active
- **THEN** the Generation card displays `80 tok/s` as the estimated all-slot total and `20 tok/s` as the per-active-slot average

#### Scenario: Fall back to aggregate counter rate
- **WHEN** the per-slot generation gauge is unavailable but the cumulative generated-token counter advances over a known polling interval
- **THEN** the Generation card uses the counter delta divided by elapsed wall time as the all-slot total

#### Scenario: Per-slot average is unavailable
- **WHEN** total generation throughput or active-slot count is unavailable or no slot is active
- **THEN** the all-slot total follows its normal availability state and the per-active-slot average is marked unavailable rather than divided by zero or inferred

#### Scenario: Render unavailable telemetry
- **WHEN** metrics are Unsupported, Unavailable, or Stale
- **THEN** each affected Qt card or chart shows that availability state while unaffected data remains visible

#### Scenario: Update charts under resize
- **WHEN** chart samples arrive while the Runtime page is resized
- **THEN** chart geometry is recalculated on a bounded cadence and the newest sample is rendered without overlapping labels or blocking the resize interaction

#### Scenario: Distinguish the two charts
- **WHEN** the Runtime dashboard is visible
- **THEN** each chart has its own rounded surface and visible border enclosing its title, legend, grid, and series

### Requirement: Support keyboard, focus, and accessible naming
Interactive Qt controls SHALL be keyboard reachable in a logical order, SHALL expose visible focus treatment, and SHALL provide accessible names or descriptions for controls whose purpose is not fully expressed by visible text alone.

#### Scenario: Navigate without a mouse
- **WHEN** the user traverses the active page with Tab and Shift+Tab
- **THEN** focus follows the visual workflow and all primary actions, selectors, switches, and entry controls are operable

#### Scenario: Open a selector
- **WHEN** a selector has sufficient screen space below it and its popup opens
- **THEN** the popup begins below the select bar and does not cover the selected value

#### Scenario: Open a long selector
- **WHEN** a selector contains more items than its preferred popup capacity
- **THEN** the popup shows a useful multi-row height, has no square outer container frame, and exposes a visible vertical scrollbar for all remaining items

#### Scenario: Announce an icon-only control
- **WHEN** assistive technology inspects an icon-only remove, browse, refresh, or navigation control
- **THEN** the control exposes an accessible name describing its action

#### Scenario: Show validation focus
- **WHEN** Save finds an invalid field
- **THEN** focus moves to the first invalid field and the error is communicated through both visible text and accessible description

### Requirement: Provide deterministic Qt UI verification
The project SHALL provide automated PyQt6 UI tests that do not require llama.cpp, a physical display, or a foreground console, and SHALL provide a manual preview mode with representative application states for visual inspection.

#### Scenario: Run automated UI tests
- **WHEN** the test suite runs with the Qt offscreen platform
- **THEN** it verifies page creation, profile and glossary interactions, state-driven controls, runtime rendering, burst-event handling, layout bounds, and clean close behavior

#### Scenario: Preview visual states
- **WHEN** the manual preview is launched with a selected fixture state
- **THEN** it displays representative Stopped, Ready, Failed, Unsupported, or Stale UI without launching llama.cpp

### Requirement: Build a portable console-free onefile executable
The canonical `build.bat` workflow SHALL test and package the PyQt6 application as a single console-free Windows executable that does not require Python, an `_internal` directory, Tkinter, or CustomTkinter at runtime.

#### Scenario: Run the official build
- **WHEN** a developer runs `build.bat` in a supported environment with project dependencies available
- **THEN** the script validates the project and produces `dist\LlamaCppLauncher.exe` using the maintained PyInstaller spec

#### Scenario: Move the executable
- **WHEN** the generated executable is copied to a directory outside the repository without adjacent support files
- **THEN** it starts the PyQt6 interface and can load or create user settings through the normal application data location

#### Scenario: Start without legacy UI packages
- **WHEN** the packaged application starts on a supported Windows system
- **THEN** it does not load Tkinter or CustomTkinter and includes the required Qt platform plugin and resources

#### Scenario: Display the application icon
- **WHEN** the source or packaged application is shown in a window, taskbar, or executable listing
- **THEN** it uses the bundled previous blue windowed icon rather than an environment-derived Python icon
