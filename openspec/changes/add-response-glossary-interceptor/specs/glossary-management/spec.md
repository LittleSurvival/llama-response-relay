## ADDED Requirements

### Requirement: Manage independent named glossaries
The launcher SHALL allow users to create, rename, edit, select, and delete multiple named glossaries independently from llama.cpp launch profiles and SHALL preserve them across application restarts.

#### Scenario: Create a glossary
- **WHEN** the user saves a glossary with a non-empty unique name
- **THEN** the glossary is persisted and becomes available for global LRR selection

#### Scenario: Reject a duplicate glossary name
- **WHEN** a user creates or renames a glossary to a case-insensitive name already in use
- **THEN** the launcher rejects the change without modifying either glossary

#### Scenario: Delete the selected glossary
- **WHEN** the user confirms deletion of the globally selected glossary
- **THEN** the launcher deletes it and selects the first remaining glossary, or no glossary when none remain

### Requirement: Store deterministic glossary entries
Each glossary SHALL contain ordered entries with source text, replacement text, enabled state, and case-sensitive state. Source text SHALL be non-empty and duplicate active source definitions with the same case-sensitivity mode SHALL be rejected.

#### Scenario: Save an entry
- **WHEN** the user supplies valid source and replacement text
- **THEN** the launcher persists the entry's text and option states

#### Scenario: Disable an entry
- **WHEN** an entry is disabled
- **THEN** it remains stored and editable but does not participate in response transformation

### Requirement: Select the active LRR glossary
LRR SHALL use one globally selected saved glossary independently from launcher profiles, and glossary renames SHALL not break the selection.

#### Scenario: Select a glossary
- **WHEN** the user selects a saved glossary in the LRR workspace
- **THEN** subsequent LRR launches use that glossary with any launcher profile

#### Scenario: Select no glossary
- **WHEN** no saved glossary is selected
- **THEN** LRR forwards completion text unchanged

### Requirement: Migrate existing settings safely
The launcher SHALL migrate valid schema-version-one settings to the glossary-capable schema without changing existing profile values and SHALL keep glossary selection independent from profiles.

#### Scenario: Load existing launcher settings
- **WHEN** the launcher loads a valid version-one settings file
- **THEN** all existing profiles and source folders remain available and new interceptor and glossary fields receive defaults
