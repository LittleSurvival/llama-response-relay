## ADDED Requirements

### Requirement: Persist named profiles
The launcher SHALL allow users to create, edit, select, duplicate, and delete multiple named profiles and SHALL preserve them across application restarts.

#### Scenario: Create a profile
- **WHEN** the user saves a valid profile with a unique name
- **THEN** the launcher persists the profile and makes it available for selection

#### Scenario: Reject a duplicate name
- **WHEN** the user creates or renames a profile to a name already in use
- **THEN** the launcher rejects the save and preserves both previously valid profiles

#### Scenario: Delete a profile
- **WHEN** the user confirms deletion of a profile that is not running
- **THEN** the launcher removes that profile without modifying other profiles

### Requirement: Store required profile fields
Each profile SHALL store its name, GGUF model path, host, port, `-ngl`, `-c`, `-np`, `-fa`, `--no-mmap`, GPU mode, and custom arguments.

#### Scenario: Reload a complete profile
- **WHEN** the application restarts after a profile has been saved
- **THEN** every supported field is restored with the value previously saved

### Requirement: Discover launcher and model files from selected folders
The launcher SHALL let the user select a llama.cpp folder and a model folder. It SHALL resolve `llama-server.exe` directly from the llama.cpp folder and SHALL populate the model selector from `.gguf` files directly inside the model folder without recursively scanning subfolders.

#### Scenario: Select a valid llama.cpp folder
- **WHEN** the user selects a folder containing `llama-server.exe`
- **THEN** the launcher persists the folder and marks the executable source as valid

#### Scenario: Selected llama.cpp folder is invalid
- **WHEN** the selected folder does not contain `llama-server.exe` directly
- **THEN** the launcher reports the expected executable path and does not search unrelated folders

#### Scenario: Load the model selector
- **WHEN** the user selects or refreshes a valid model folder
- **THEN** the launcher lists the `.gguf` files directly in that folder in a deterministic order

#### Scenario: Persist selected model
- **WHEN** the user saves a profile after selecting a model from the folder
- **THEN** the profile stores the selected model's absolute file path

#### Scenario: Previously selected model is missing
- **WHEN** a profile is loaded after its stored model file was moved or deleted
- **THEN** the launcher keeps the stored path visible, marks it unavailable, and blocks launch until another model is selected

### Requirement: Configure GPU intent
The profile editor SHALL provide `auto`, `single`, and `multi` GPU modes. Auto mode SHALL delegate topology selection to llama.cpp, while explicit modes SHALL be validated against capabilities reported by the selected llama.cpp executable.

#### Scenario: Use automatic GPU mode
- **WHEN** a profile with GPU mode `auto` is launched
- **THEN** the launcher does not add a manual GPU-topology selection argument

#### Scenario: Explicit mode is unsupported
- **WHEN** the selected executable does not report support needed by the selected explicit GPU mode
- **THEN** the launcher blocks the launch and explains which selection is unsupported

### Requirement: Validate profiles before persistence and launch
The launcher SHALL validate required paths, numeric values, host, port, profile name, and managed-option conflicts before saving or launching a profile.

#### Scenario: Model file is missing
- **WHEN** the selected GGUF model path does not identify an existing file in the configured model folder
- **THEN** the launcher identifies the model field as invalid and does not launch llama.cpp

#### Scenario: Port is invalid
- **WHEN** the port is outside the range 1 through 65535
- **THEN** the launcher rejects the profile value with a field-specific error

#### Scenario: Custom argument conflicts with a structured field
- **WHEN** custom arguments contain an option managed by a structured profile field
- **THEN** the launcher rejects the conflict rather than silently choosing one value

### Requirement: Save profiles safely
The launcher SHALL write UTF-8 profile data using validation and atomic file replacement and SHALL retain the last valid in-memory data when a load or save fails.

#### Scenario: Profile file replacement fails
- **WHEN** the operating system prevents the temporary profile file from replacing the active file
- **THEN** the previous profile file remains usable and the UI reports that the save failed

#### Scenario: Stored data is malformed
- **WHEN** the launcher starts with a malformed profile file
- **THEN** it does not overwrite that file and presents a recoverable configuration error
