## 1. Settings Schema and Glossary Domain

- [x] 1.1 Add version-two glossary and glossary-entry models, interceptor endpoint settings, and optional per-profile glossary identifiers
- [x] 1.2 Implement in-memory version-one settings migration and retain atomic version-two persistence behavior
- [x] 1.3 Implement glossary create, rename, update, select, delete-with-assignment-clearing, and validation services
- [x] 1.4 Add model, migration, glossary CRUD, assignment, duplicate-name, and failed-persistence tests

## 2. Deterministic Replacement Engine

- [x] 2.1 Implement immutable enabled-rule compilation with longest-match-first, stable tie-breaking, case sensitivity, and non-recursive replacement
- [x] 2.2 Implement incremental per-choice matcher state that buffers only unresolved source prefixes and flushes at stream completion
- [x] 2.3 Add replacement tests for overlaps, disabled entries, mixed case modes, Unicode, replacement recursion, arbitrary chunk boundaries, and final flush

## 3. OpenAI-Compatible HTTP Interceptor

- [x] 3.1 Add aiohttp and implement a background-loop interceptor server with bounded synchronous start and stop ownership
- [x] 3.2 Forward supported request methods, bodies, query strings, and end-to-end headers while rejecting unsupported paths
- [x] 3.3 Transform only endpoint-specific completion fields in successful non-streaming JSON responses
- [x] 3.4 Transform SSE chat and completion chunks with per-choice matcher state while preserving metadata, errors, event order, and terminal events
- [x] 3.5 Add HTTP integration tests for chat and completion JSON, streaming boundary matches, no-glossary pass-through, upstream errors, gateway failures, unsupported paths, and clean shutdown

## 4. Launcher Lifecycle Integration

- [x] 4.1 Coordinate llama.cpp Ready with interceptor startup and report final Ready only after the LRR listener binds
- [x] 4.2 Stop the interceptor before owned-process Stop, Restart, and Close while retaining Stop after interceptor startup failure
- [x] 4.3 Validate and display distinct upstream and client-facing endpoints and warn on non-loopback LRR binds
- [x] 4.4 Add lifecycle tests for ordered start, bind failure, Stop, Restart, Close, and glossary snapshot stability

## 5. Glossary and Profile UI

- [x] 5.1 Add a dedicated Glossaries workspace with named glossary create, rename, save, and confirmed-delete flows
- [x] 5.2 Add editable entry rows for source, replacement, enabled, and case-sensitive values with validation feedback
- [x] 5.3 Add LRR host and port controls plus a per-profile No glossary or saved-glossary selector
- [x] 5.4 Disable active profile and glossary mutation controls while keeping runtime Stop available
- [x] 5.5 Add UI behavior tests and visually verify empty, editing, validation, assigned, Starting, Ready, and Failed states

## 6. Packaging and End-to-End Verification

- [x] 6.1 Include aiohttp and transitive runtime resources in the console-free onedir bundle and update the Chinese operating guide
- [x] 6.2 Run the complete automated suite and validate the OpenSpec change
- [x] 6.3 Smoke-test the packaged launcher with migrated settings, named glossary persistence, hidden llama.cpp, LRR JSON and SSE replacement, logs, Stop, and close-time shutdown

## 7. LRR Workspace and Optional Lifecycle

- [x] 7.1 Add a persisted global LRR enabled setting with backward-compatible defaults
- [x] 7.2 Rename the Glossaries workspace to LRR and move LRR enable, host, and port controls into it
- [x] 7.3 Skip interceptor startup when LRR is disabled while preserving llama.cpp lifecycle and endpoint reporting
- [x] 7.4 Add settings, runtime, and UI tests for enabled and disabled LRR behavior
- [x] 7.5 Update documentation, validate OpenSpec, run the full suite, and rebuild the Windows bundle

## 8. LRR Glossary Interaction Repair

- [x] 8.1 Remove glossary controls from profile Settings and add profile-to-glossary assignment controls to LRR
- [x] 8.2 Make the LRR workspace vertically scrollable with a visible entry-editor height
- [x] 8.3 Ensure glossary selection and Add entry update visible editable state immediately
- [x] 8.4 Add automated UI behavior tests for assignment, selection, and entry-row creation
- [x] 8.5 Update documentation, run the full suite, validate OpenSpec, and rebuild without manual UI testing

## 9. Global Glossary Selection and Compact Entries

- [x] 9.1 Remove per-profile glossary identifiers, assignment validation, and assignment-clearing service behavior
- [x] 9.2 Remove the Profile glossary UI and start LRR with the globally selected Glossaries item
- [x] 9.3 Redesign entry rows into a compact single-line layout with side controls and case-sensitive default enabled
- [x] 9.4 Update migration, service, runtime-selection, and UI behavior tests
- [x] 9.5 Update documentation, run the full suite, validate OpenSpec, and rebuild without manual UI testing

## 10. Browser Client Compatibility

- [x] 10.1 Add non-credentialed CORS preflight and response headers for normal, streaming, and error responses
- [x] 10.2 Proxy `GET /v1/models` without glossary transformation
- [x] 10.3 Add integration tests for CORS preflight, completion CORS headers, model listing, and unsupported paths
- [x] 10.4 Update documentation, run the full suite, validate OpenSpec, and rebuild without manual UI testing
