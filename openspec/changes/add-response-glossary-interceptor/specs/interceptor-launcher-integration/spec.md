## ADDED Requirements

### Requirement: Configure the interceptor endpoint
The launcher SHALL provide an application-level LRR enable switch and host and port settings in a dedicated LRR workspace, with defaults enabled and `127.0.0.1:8081`. It SHALL validate the endpoint before an enabled launch and SHALL display the client-facing interceptor URL separately from the upstream llama.cpp endpoint.

#### Scenario: Use default interceptor endpoint
- **WHEN** no custom LRR endpoint has been saved
- **THEN** the launcher listens on `127.0.0.1:8081`

#### Scenario: Interceptor port is unavailable
- **WHEN** the configured LRR address cannot be bound
- **THEN** the launcher reports the bind failure, does not claim LRR is Ready, and keeps Stop available for the owned llama.cpp process

#### Scenario: Disable LRR
- **WHEN** the global LRR switch is disabled and the user starts a profile
- **THEN** the launcher starts only llama.cpp, does not bind the LRR endpoint, and identifies the upstream llama.cpp URL as the client endpoint

### Requirement: Coordinate interceptor lifecycle
The launcher SHALL start LRR only after the owned llama.cpp endpoint becomes Ready, SHALL expose Ready only after LRR starts successfully, and SHALL stop LRR before stopping, restarting, or closing the owned llama.cpp process.

#### Scenario: Start a profile
- **WHEN** llama.cpp becomes Ready for the selected profile
- **THEN** the launcher starts LRR with that profile's upstream endpoint and the globally selected glossary snapshot before reporting Ready

#### Scenario: Stop the active profile
- **WHEN** the user requests Stop
- **THEN** the launcher stops accepting new LRR requests, closes the interceptor, and then stops the owned llama.cpp process

#### Scenario: Restart the active profile
- **WHEN** the user requests Restart
- **THEN** the launcher fully stops LRR and llama.cpp before starting both again in order

#### Scenario: Close while active
- **WHEN** the launcher closes while LRR is running
- **THEN** it stops LRR and the owned llama.cpp process before the desktop application exits

### Requirement: Provide glossary management UI
The desktop UI SHALL provide a dedicated scrollable LRR workspace containing LRR enable and endpoint controls plus named glossary selection, compact visible entry editing, create, rename, save, and delete workflows. The profile Settings workspace SHALL NOT contain glossary controls or glossary assignments.

#### Scenario: Edit glossary entries
- **WHEN** the user selects a glossary
- **THEN** its entries and enabled and case-sensitive states are available for editing without changing launcher profile fields

#### Scenario: Select the LRR glossary
- **WHEN** the user selects a saved item in Glossaries
- **THEN** that selection is persisted globally and is not written to a launcher profile

#### Scenario: Add an entry
- **WHEN** the user selects a named glossary and activates Add entry
- **THEN** a compact editable source and replacement row becomes immediately visible with Enabled on the left, Remove on the right, and Case-sensitive enabled by default

### Requirement: Keep active configuration stable
The interceptor SHALL use a validated snapshot of the globally selected glossary for the lifetime of one launch, and glossary selection or content changes SHALL take effect on the next Start or Restart.

#### Scenario: Edit a glossary while stopped
- **WHEN** the user changes the globally selected glossary and next starts any profile
- **THEN** LRR uses the newly saved entries

#### Scenario: Runtime is active
- **WHEN** llama.cpp and LRR are active
- **THEN** controls that would mutate the active profile or selected glossary are unavailable
