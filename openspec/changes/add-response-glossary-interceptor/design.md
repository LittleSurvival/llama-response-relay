## Context

The application currently stores llama.cpp profiles, starts one hidden `llama-server.exe`, waits for its `/health` endpoint, and exposes lifecycle state through a CustomTkinter UI. It does not listen for client API traffic or contain a glossary data model.

This change inserts a local LRR endpoint between an OpenAI-compatible client and the launcher-owned llama.cpp server. It must preserve low-latency streaming, recognize terms split across SSE chunks, keep structured response data untouched, migrate existing settings, and remain safe to stop from the desktop lifecycle.

## Goals / Non-Goals

**Goals:**

- Proxy `/v1/chat/completions`, `/v1/completions`, and read-only `/v1/models` to the active profile.
- Apply deterministic glossary replacement to completion text in JSON and SSE responses.
- Manage multiple independent named glossaries and select one globally for LRR.
- Start LRR after llama.cpp readiness and stop it before llama.cpp shutdown.
- Preserve existing version-one settings through an explicit migration.
- Keep the UI responsive and package the new server dependencies in the Windows bundle.

**Non-Goals:**

- Modify prompts, requests, embeddings, model metadata, reasoning content, or tool calls.
- Interpret glossary sources as regular expressions.
- Proxy arbitrary llama.cpp endpoints.
- Connect LRR to an externally managed llama.cpp process.
- Run several profile/interceptor instances simultaneously.
- Hot-reload glossary edits into an active response stream.

## Decisions

### Run an aiohttp server on a dedicated background event loop

Use `aiohttp.web` for the local server and `aiohttp.ClientSession` for upstream requests and streaming. Own one asyncio event loop in a dedicated daemon thread, expose synchronous bounded `start()` and `stop()` methods to the launcher coordinator, and never run network work on Tk's main thread.

This provides backpressure-aware request and response streaming with one dependency and avoids manually implementing HTTP chunking with `BaseHTTPRequestHandler`. A separate LRR process was considered, but an in-process server has simpler ownership, packaging, configuration sharing, and deterministic shutdown for the current single-instance scope.

### Treat enabled LRR and llama.cpp as one coordinated runtime

Keep `ProcessManager` responsible for the owned child and introduce an interceptor runtime component coordinated by the UI lifecycle. A llama.cpp Ready event becomes an intermediate condition: the UI starts LRR in a worker, reports Ready only after the listener binds, and reports Failed with Stop still enabled if binding fails.

Stop, Restart, and Close first stop accepting LRR traffic and close its client session and listener, then invoke the existing owned-process shutdown. The active glossary is copied into an immutable matcher snapshot at Start, so editing cannot change an in-flight stream.

Store a global `interceptor_enabled` setting that defaults to enabled for existing schema-version-two files. When disabled, the coordinator does not start LRR after llama.cpp readiness and reports the upstream llama.cpp URL as the usable endpoint. The saved LRR endpoint and selected glossary remain intact for the next enabled launch.

### Version settings schema and use stable glossary identifiers

Increase the settings schema to version two. Add application-level `interceptor_host`, `interceptor_port`, a list of glossary records, and `selected_glossary_id`. Each glossary and entry receives a UUID identifier; names remain unique for presentation, while the global selection survives glossary renames.

Loading schema version one performs an in-memory migration that retains every existing profile field, sets the LRR endpoint and empty glossary defaults, and writes version two only on the next successful user save. Existing version-two profile-level `glossary_id` values are ignored and omitted on the next save. Unknown future schema versions remain rejected.

### Use two deterministic prefix matchers

Compile enabled entries into case-sensitive and case-insensitive prefix indexes. At each input position, consider all complete matches and select the longest source; stable entry order breaks equal-length ties. Emit replacement text directly without feeding it back into the matcher.

For streaming, keep one matcher state per response choice. A character can be emitted when it cannot be the prefix of a longer pending glossary source; otherwise it remains in a bounded tail whose maximum is the longest enabled source. This recognizes terms across arbitrary upstream chunk boundaries without buffering the whole response. Case-insensitive comparison uses Unicode case-folding while emitted unmatched text preserves its original casing.

### Transform only endpoint-specific JSON fields

For non-streaming chat responses, transform string values at `choices[].message.content`; for text completions, transform `choices[].text`. For SSE, transform chat `choices[].delta.content` and completion `choices[].text`. All other values are serialized from the parsed event unchanged.

When a choice reports a finish reason, flush its pending tail into that choice's final text field. If `[DONE]` arrives with any remaining tail, emit a minimal endpoint-compatible content event before forwarding `[DONE]`. Malformed or non-JSON success bodies and all non-success bodies pass through unchanged.

### Forward end-to-end headers, support browser CORS, and reject unsupported paths

Expose the two exact completion POST paths and the exact `GET /v1/models` path, including their query strings when forwarding. `/v1/models` is returned byte-for-byte without glossary transformation. Copy request and response headers except hop-by-hop headers and recalculate transformed content framing. Preserve upstream status codes. Return local JSON `404` for unsupported paths, `502` for connection failures, and a local diagnostic for interceptor-internal failures.

Handle browser `OPTIONS` preflight locally and add `Access-Control-Allow-Origin: *` plus the applicable methods and requested headers to all LRR responses. Do not enable credentialed CORS. This matches the unauthenticated local-proxy model while allowing browser-based clients to call the Client endpoint.

Authorization headers are forwarded only to the user-configured local llama.cpp endpoint. LRR defaults to loopback; selecting a non-loopback bind address is allowed but the UI explains that it exposes the proxy to the network.

### Add a dedicated LRR workspace

Extend the existing Settings/Runtime segmented navigation with LRR. The LRR workspace contains the global enable switch and host/port settings, named glossary selection, and a scrollable entry editor. The selected item in Glossaries is the glossary used by LRR. Profile Settings contains only llama.cpp launch configuration and does not expose glossary controls.

Glossary edits are independently saved. Deleting the selected glossary requires confirmation and selects the first remaining glossary, if any. Profile and glossary mutation controls are disabled while the coordinated runtime is active.

The entire LRR workspace is vertically scrollable and the entry list has an explicit visible height. Adding an entry immediately creates a compact single-row editor with Enabled on the left, Remove on the right, and Case-sensitive enabled by default. An empty glossary selector directs the user to create a named glossary first.

## Risks / Trade-offs

- [A large glossary can make per-character matching expensive] → Compile prefix indexes once per Start and test with representative large rule sets; keep matching deterministic before optimizing further.
- [Unicode case-folding can change character length] → Compare prefixes using case-folded strings but bound pending input by original source character length; include non-ASCII tests and document that matching is textual rather than locale-specific.
- [Slow clients can retain upstream connections] → Use aiohttp streaming backpressure and close all active responses during bounded interceptor shutdown.
- [An SSE producer may end without a finish event] → Flush any pending tail before forwarding `[DONE]` or connection EOF.
- [Transformed JSON changes byte length] → Remove upstream content length and transfer framing and let aiohttp recalculate them.
- [Binding LRR beyond loopback exposes an unauthenticated proxy] → Default to loopback and show a UI warning for non-loopback hosts.
- [Permissive CORS allows any webpage to call an exposed LRR listener] → Keep loopback as the default, do not allow CORS credentials, and retain the non-loopback exposure warning.
- [Schema migration could overwrite recoverable version-one data] → Migrate only in memory on load and retain atomic replacement on the next explicit save.

## Migration Plan

1. Load schema version one or two; reject other versions.
2. Convert version-one profiles in memory without adding glossary fields and add default LRR endpoint values.
3. Persist schema version two through the existing atomic store only after a successful user save.
4. Package aiohttp and its runtime dependencies in the onedir bundle.
5. Validate both a clean install and a copy of version-one settings.

Rollback requires stopping the launcher and using the previous application bundle. Version-two settings are not readable by the old version, so preserve a copy of the last version-one file in migration tests and document that executable rollback may require restoring that file.

## Open Questions

- Whether a future version should proxy additional OpenAI-compatible endpoints.
- Whether glossary import/export or bulk paste should be added after the first CRUD UI.
- Whether external-llama standalone interceptor mode should be introduced later.
