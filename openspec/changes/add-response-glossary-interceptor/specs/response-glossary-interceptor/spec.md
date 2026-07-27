## ADDED Requirements

### Requirement: Proxy supported OpenAI-compatible endpoints
The interceptor SHALL accept POST requests to `/v1/chat/completions` and `/v1/completions` plus GET requests to `/v1/models`, SHALL forward request bodies and end-to-end request headers to the active profile's llama.cpp endpoint without semantic modification, and SHALL return the upstream status and applicable response headers.

#### Scenario: Forward chat completion
- **WHEN** a client posts a valid request to `/v1/chat/completions`
- **THEN** the interceptor sends the same request content to the active llama.cpp endpoint

#### Scenario: Forward text completion
- **WHEN** a client posts a valid request to `/v1/completions`
- **THEN** the interceptor sends the same request content to the active llama.cpp endpoint

#### Scenario: List models
- **WHEN** a client gets `/v1/models`
- **THEN** the interceptor returns the upstream response without glossary transformation

#### Scenario: Reject unsupported path
- **WHEN** a client requests a path outside the three supported endpoints
- **THEN** the interceptor returns a not-found response without forwarding it upstream

### Requirement: Support browser clients with CORS
The interceptor SHALL answer browser preflight requests locally and include permissive non-credentialed CORS headers on all responses, including errors and streaming responses.

#### Scenario: Browser sends a preflight request
- **WHEN** a browser sends `OPTIONS` with an Origin and requested headers
- **THEN** LRR returns a successful empty response allowing GET, POST, OPTIONS, and the requested headers without forwarding upstream

#### Scenario: Browser receives an API response
- **WHEN** LRR returns a supported API response or local error
- **THEN** the response includes `Access-Control-Allow-Origin: *` and does not enable credentialed CORS

### Requirement: Transform only completion text
For non-streaming JSON responses, the interceptor SHALL transform only `choices[].message.content` for chat completions and `choices[].text` for text completions. It SHALL preserve reasoning content, tool calls, response identifiers, model names, usage, finish reasons, and all other JSON values.

#### Scenario: Transform chat content
- **WHEN** an upstream chat response contains assistant content matching an enabled glossary entry
- **THEN** only the matching text inside `choices[].message.content` is replaced

#### Scenario: Preserve structured fields
- **WHEN** an upstream response contains tool calls, reasoning content, usage, or model metadata
- **THEN** those values are returned unchanged

#### Scenario: No glossary is selected
- **WHEN** LRR has no globally selected glossary
- **THEN** completion text is returned unchanged

### Requirement: Apply deterministic plain-text matching
The interceptor SHALL apply enabled plain-text entries using longest-source-match-first behavior at each source position, SHALL honor each entry's case-sensitive setting, and SHALL NOT interpret source text as a regular expression.

#### Scenario: Overlapping terminology
- **WHEN** enabled entries exist for `魔法` and `魔法少女` and the response contains `魔法少女`
- **THEN** the `魔法少女` replacement is selected at that position

#### Scenario: Case-insensitive entry
- **WHEN** a case-insensitive source `Llama` is enabled
- **THEN** matching text such as `llama` and `LLAMA` is replaced

#### Scenario: Replacement output resembles another source
- **WHEN** an entry's replacement text contains the source of another entry
- **THEN** the replacement output is not processed again during the same transformation pass

### Requirement: Preserve streaming semantics
For SSE responses, the interceptor SHALL transform chat `choices[].delta.content` and completion `choices[].text`, SHALL preserve event order and non-text fields, and SHALL recognize matches spanning upstream chunk boundaries using a bounded tail buffer.

#### Scenario: Term spans chunks
- **WHEN** a glossary source is divided between consecutive SSE content chunks
- **THEN** the client receives the replacement exactly once without receiving the divided source

#### Scenario: Stream finishes with buffered text
- **WHEN** the upstream stream finishes while source text remains buffered
- **THEN** the interceptor flushes the transformed remainder before forwarding the terminal event

#### Scenario: Preserve stream metadata
- **WHEN** SSE chunks contain finish reasons, usage, reasoning fields, or tool-call deltas
- **THEN** those fields and their order remain unchanged

### Requirement: Fail transparently and safely
The interceptor SHALL return a clear gateway error when the upstream endpoint cannot be reached and SHALL pass through an upstream response unchanged when its body is not a transformable JSON or SSE completion response.

#### Scenario: Upstream is unavailable
- **WHEN** forwarding fails before an upstream response is received
- **THEN** the interceptor returns a `502` response with a local diagnostic message

#### Scenario: Upstream returns an error body
- **WHEN** llama.cpp returns a non-success response
- **THEN** the interceptor preserves the upstream status and body without applying glossary replacement
