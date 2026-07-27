## Why

Applications using the local llama.cpp server currently receive model text exactly as generated, so users cannot enforce preferred names or terminology without editing every response manually. A local OpenAI-compatible response interceptor will apply reusable glossary rules while preserving the existing client and llama.cpp workflow.

## What Changes

- Add a local LRR HTTP interceptor with configurable host and port, defaulting to `127.0.0.1:8081`.
- Add a global LRR enable switch; when disabled, launch only llama.cpp and expose its upstream endpoint directly.
- Proxy `/v1/chat/completions`, `/v1/completions`, and read-only `/v1/models` requests to the selected launcher profile's llama.cpp endpoint without changing request bodies.
- Support browser clients with CORS preflight and permissive non-credentialed cross-origin response headers.
- Replace only assistant completion text in normal JSON responses and streaming SSE responses.
- Preserve response metadata, usage, model names, tool calls, JSON structure, and reasoning fields unchanged.
- Apply enabled plain-text glossary entries using longest-match-first semantics with optional case sensitivity.
- Preserve matches that span streaming chunk boundaries with a bounded tail buffer instead of buffering the entire response.
- Add independent named glossary create, save, select, and delete workflows.
- Let LRR use the currently selected saved glossary globally, independently from llama.cpp profiles.
- Start the interceptor after llama.cpp becomes Ready and stop it with Stop, Restart, or launcher shutdown.
- Do not add a standalone interceptor mode for externally managed llama.cpp in this change.

## Capabilities

### New Capabilities

- `glossary-management`: Create, edit, validate, persist, select, and delete independent named glossaries, with one global LRR selection.
- `response-glossary-interceptor`: Proxy OpenAI-compatible completion endpoints and transform only completion text in JSON and SSE responses using deterministic glossary matching.
- `interceptor-launcher-integration`: Configure the local interceptor endpoint in the desktop UI and coordinate its lifecycle with the launcher-owned llama.cpp process.

### Modified Capabilities

None.

## Impact

- Extends the local settings schema with glossary records, a global selected glossary, and interceptor host and port.
- Adds a local HTTP server, upstream HTTP streaming client behavior, SSE parsing and serialization, and a deterministic streaming text-replacement engine.
- Extends the CustomTkinter UI with one dedicated LRR workspace containing the enable switch, interceptor endpoint settings, and glossary management.
- Changes the launcher lifecycle so Ready means llama.cpp is ready and the configured interceptor has started successfully.
- Adds network and HTTP server dependencies to the packaged Windows application while keeping llama.cpp and models user supplied.
