## ADDED Requirements

### Requirement: Launch the selected profile safely
The launcher SHALL start the configured `llama-server.exe` for the selected profile using an argument vector, without a command shell and without displaying a console window.

#### Scenario: Start a valid profile
- **WHEN** no owned process is active and the user starts a valid profile
- **THEN** the launcher creates a hidden child process with the selected model and configured arguments

#### Scenario: Prevent a second active process
- **WHEN** an owned llama.cpp process is already active
- **THEN** the launcher does not start another profile

### Requirement: Build deterministic arguments
The launcher SHALL translate structured profile fields into one deterministic command and SHALL append non-conflicting custom arguments without reinterpreting them through a shell.

#### Scenario: Boolean option is enabled
- **WHEN** `--no-mmap` is enabled in the selected profile
- **THEN** the generated argument vector contains `--no-mmap` exactly once

#### Scenario: Custom arguments contain quoted data
- **WHEN** the user supplies a valid custom argument containing spaces
- **THEN** the child process receives it as the intended single argument

### Requirement: Report process and API readiness
The launcher SHALL distinguish child-process existence from API readiness and SHALL expose `Starting`, `Ready`, `Stopping`, `Stopped`, and `Failed` states.

#### Scenario: Health check becomes ready
- **WHEN** the child remains active and its health endpoint begins responding successfully before timeout
- **THEN** the launcher transitions from `Starting` to `Ready`

#### Scenario: Process exits during startup
- **WHEN** the child exits before its health endpoint becomes ready
- **THEN** the launcher transitions to `Failed` and reports the exit code

#### Scenario: Health check times out
- **WHEN** the child remains active but health checks do not succeed before timeout
- **THEN** the launcher reports a health timeout without claiming the API is ready

### Requirement: Capture runtime output
The launcher SHALL capture the owned process's standard output and standard error without blocking the UI and SHALL make recent output available in the launcher.

#### Scenario: llama.cpp writes output
- **WHEN** the owned process writes a line to standard output or standard error
- **THEN** the line is delivered to the UI log view with its source while the UI remains responsive

### Requirement: Stop only the owned process
The launcher SHALL stop or restart only the child process represented by its current process handle and SHALL never terminate llama.cpp processes by executable name.

#### Scenario: Stop the active process
- **WHEN** the user selects Stop
- **THEN** the launcher requests graceful termination, waits for a bounded period, and force-terminates only that same child if necessary

#### Scenario: Restart the active profile
- **WHEN** the user selects Restart
- **THEN** the launcher fully stops the owned process before starting the selected profile again

#### Scenario: Unrelated llama.cpp process exists
- **WHEN** another llama.cpp process was started outside this launcher
- **THEN** Stop and Restart do not terminate or alter that unrelated process

### Requirement: Stop on launcher exit
The launcher SHALL finish stopping its owned llama.cpp process before the application exits.

#### Scenario: Close while running
- **WHEN** the user closes the launcher while its child process is active
- **THEN** the launcher performs the bounded stop procedure and closes after the child is no longer running
