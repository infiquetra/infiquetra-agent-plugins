# Auralis Bridge Contract v1

- **Status:** Committed Normative Specification
- **Owner:** Auralis Core (infiquetra/auralis, C10)
- **Consumer:** Adapter (infiquetra/infiquetra-agent-plugins, capability slice C3)
- **Source Revision:** `infiquetra/auralis` commit `0d1faf6ac146ee69cc5c63eea4229f6a0c09cf82` (SHA-256: `9b78f4a417700c27b3650858597bd5b968fa69302c0dff589301476b8d30c059`)
- **Schema Version:** 1

---

## 1. Overview and Scope

This document specifies the normative wire contract for Version 1 of the Auralis Local Bridge. The bridge connects the in-process Auralis Core application with out-of-process coding agent adapters (such as the Claude adapter in `infiquetra/infiquetra-agent-plugins`, capability slice C3).

C3 plans and implements against this specification independently. No Dart source code, data-transfer objects, or internal test helpers from `infiquetra/auralis` are shared across the repository boundary.

---

## 2. Discovery

On a successful start, Auralis Core atomically publishes a connection file containing loopback connection parameters and credentials.

### File Location
`~/Library/Application Support/Auralis/bridge.json`

### File Format
A compact JSON object with UTF-8 encoding:

```json
{"schema":1,"host":"127.0.0.1","port":49152,"token":"<43-character unpadded base64url>"}
```

### Member Definitions
- `schema` *(integer)*: Must be the literal integer `1`.
- `host` *(string)*: Must be the literal string `"127.0.0.1"`.
- `port` *(integer)*: The live operating-system-assigned TCP port (`1` through `65535`).
- `token` *(string)*: A 32-byte cryptographically secure random token encoded as 43 unpadded base64url characters.

### Permissions and Lifecycle
- The file is created with file mode `0600` (read/write by owner only) before publication via atomic rename.
- A missing, partial, wrong-typed, extra-keyed, schema-unknown, or permission-invalid file indicates that the bridge is unavailable. The adapter must never assume default ports or tokens.
- On process exit, the listening socket is closed. On restart, a fresh port and token are minted and published atomically.

---

## 3. Authentication

Every HTTP request to the bridge must include valid bearer credentials.

- Header: `Authorization: Bearer <token>`
- The header name `Authorization` and authentication scheme `Bearer` are ASCII-case-insensitive.
- The `<token>` string is compared byte-exact against the active per-launch token.
- A request with a missing, repeated, malformed, or invalid authorization header returns HTTP `401 Unauthorized` with error `unauthorized` before any request body is read and causes no state effect.

---

## 4. Wire Rules and Protocol Standards

1. **Protocol:** HTTP/1.1 over loopback TCP (`127.0.0.1`).
2. **Payload Format:** UTF-8 JSON.
3. **Media Type:**
   - Responses always set `Content-Type: application/json; charset=utf-8`.
   - Body-bearing requests (`PUT`, `DELETE`, `POST`) must supply `Content-Type: application/json` (optional `charset=utf-8` allowed). Requests declaring another media type or non-UTF-8 charset return `415 Unsupported Media Type` with error `unsupported_media_type`.
4. **Closed Request Shapes:** Request bodies are closed JSON objects. Missing required members, extra unexpected members, `null` values, wrong types, or empty strings where prohibited return HTTP `400 Bad Request` with error `invalid_request`.
5. **Schema Field:** Every request body must contain `"schema": 1`. A missing or non-integer schema returns `invalid_request`; an integer schema other than `1` returns `unsupported_schema`.
6. **Query Strings:** URL query strings must be empty. A non-empty query returns HTTP `400 Bad Request` with error `invalid_request`.
7. **GET Requests:** Must not include a body. A GET request carrying a body or `Content-Length > 0` returns HTTP `400 Bad Request` with error `invalid_request`.
8. **Body Size Cap:** Request bodies are limited to at most `1,048,576` raw bytes (1 MiB). A body exceeding this size returns HTTP `413 Request Entity Too Large` with error `body_too_large` without entering the coordinator.
9. **Identifier Strings:** All identifier strings (`binding_id`, `turn_id`, `agent_session_id`, `pane_id`, `terminal_id`) are non-empty, compared byte-exact, and never trimmed or normalized.
10. **Response Member Order:** Insignificant. Clients must ignore unknown response members while requiring all documented members.

---

## 5. Complete Adapter Identity

Every presence and rendering request includes a complete, three-component adapter identity object:

```json
{"agent_session_id":"session-exact","pane_id":"workspace-and-pane-exact","terminal_id":"terminal-exact"}
```

All three fields participate in byte-exact equality:
- `agent_session_id` *(string, non-empty)*: The unique agent session identifier.
- `pane_id` *(string, non-empty)*: The workspace/pane identifier.
- `terminal_id` *(string, non-empty)*: The terminal identifier.

### C3 Adapter Discovery Rule
The C3 adapter obtains its identity from its environment and Herdr:
1. Reads `HERDR_PANE_ID` from its process environment.
2. Executes the `HERDR_BIN_PATH` executable with arguments `agent`, `list`.
3. Verifies that the JSON envelope contains `result.type == "agent_list"`.
4. Finds exactly one record in `result.agents` where `pane_id == HERDR_PANE_ID`.
5. Copies that record's non-empty `agent_session.value` as `agent_session_id`, that record's `pane_id` as `pane_id`, and that record's `terminal_id` as `terminal_id`.
6. Any Claude hook or agent request carrying Claude's session identifier must match `agent_session_id`.
7. The adapter must never copy identity from `GET /v1/current`.

A missing environment value, missing executable, command or envelope failure, zero or multiple matches, a missing component, or a session mismatch means the adapter registers and submits nothing.

---

## 6. Endpoints

The Version 1 surface consists of six route operations across five distinct paths:

| Method and Path | Request Body | HTTP 200 Response | State Effect |
|---|---|---|---|
| `GET /v1/health` | *(none)* | `{"schema":1,"service":"auralis-bridge","status":"ok"}` | None. |
| `PUT /v1/presence` | `{"schema":1,"identity":<identity>}` | `{"schema":1,"disposition":"present","lease_ms":15000,"renew_after_ms":5000}` | Registers or renews the lease for the exact identity. |
| `DELETE /v1/presence` | `{"schema":1,"identity":<identity>}` | `{"schema":1,"disposition":"absent"}` | Removes the lease for the identity if present. |
| `GET /v1/current` | *(none)* | `{"schema":1,"binding":<binding|null>,"turn":<turn|null>}` | None. |
| `POST /v1/rendering` | `{"schema":1,"identity":<identity>,"binding_id":"...","turn_id":"...","text":"..."}` | Accepted or Rejected response shape | Renews identity lease, then synchronously adjudicates the rendering. |
| `POST /v1/approval` | `{"schema":1,"identity":<identity>,"binding_id":"...","session_id":"...","tool_use_id":"...","tool_name":"...","tool_input":{...},"permission_mode":"...","cwd":"..."}` | Allow or Defer response shape | Holds connection open for Core approval decision. |

---

### 6.1 `GET /v1/health`
Returns service liveness and health.

**Response Body:**
```json
{"schema":1,"service":"auralis-bridge","status":"ok"}
```

---

### 6.2 `PUT /v1/presence`
Registers or renews an adapter's presence lease.

**Request Body:**
```json
{
  "schema": 1,
  "identity": {
    "agent_session_id": "session-exact",
    "pane_id": "workspace-and-pane-exact",
    "terminal_id": "terminal-exact"
  }
}
```

**Response Body:**
```json
{
  "schema": 1,
  "disposition": "present",
  "lease_ms": 15000,
  "renew_after_ms": 5000
}
```

- Creates or extends a 15,000 ms lease for the exact three-part identity.
- Clients should renew their lease at or before `renew_after_ms` (5,000 ms).

---

### 6.3 `DELETE /v1/presence`
Removes an adapter's presence lease idempotently.

**Request Body:**
```json
{
  "schema": 1,
  "identity": {
    "agent_session_id": "session-exact",
    "pane_id": "workspace-and-pane-exact",
    "terminal_id": "terminal-exact"
  }
}
```

**Response Body:**
```json
{
  "schema": 1,
  "disposition": "absent"
}
```

---

### 6.4 `GET /v1/current`
Returns a snapshot of the active bridge binding epoch and current turn.

**Response Body (when bound with an open turn):**
```json
{
  "schema": 1,
  "binding": {
    "binding_id": "opaque",
    "identity": {
      "agent_session_id": "session-exact",
      "pane_id": "workspace-and-pane-exact",
      "terminal_id": "terminal-exact"
    }
  },
  "turn": {
    "turn_id": "opaque",
    "binding_id": "opaque",
    "state": "open"
  }
}
```

**Response Rules:**
- `binding` is `null` when no bridge binding epoch is active.
- `turn` is `null` when no voice turn is active in the single-slot registry (and must be `null` whenever `binding` is `null`).
- When present, `turn.state` is exactly one of:
  - `"open"`: Turn is actively awaiting an authored or fallback rendering.
  - `"authored_accepted"`: An authored rendering was accepted for this turn.
  - `"fallback_accepted"`: A fallback rendering was accepted for this turn.
  - `"canceled"`: The turn was canceled (due to stop, barge-in, retirement, or replacement).

---

### 6.5 `POST /v1/rendering`
Submits an authored speech rendering for the current turn.

**Request Body:**
```json
{
  "schema": 1,
  "identity": {
    "agent_session_id": "session-exact",
    "pane_id": "workspace-and-pane-exact",
    "terminal_id": "terminal-exact"
  },
  "binding_id": "opaque",
  "turn_id": "opaque",
  "text": "plain authored text"
}
```

**Accepted Response:**
```json
{
  "schema": 1,
  "binding_id": "opaque",
  "turn_id": "opaque",
  "disposition": "accepted"
}
```

**Rejected Response:**
```json
{
  "schema": 1,
  "binding_id": "opaque",
  "turn_id": "opaque",
  "disposition": "rejected",
  "reason": "binding_not_current"
}
```

#### Adjudication Order and Rejection Vocabulary
Submitted authored renderings are adjudicated in the following strict order:
1. `no_binding`: No bridge binding epoch is active.
2. `binding_not_current`: The offered `binding_id` does not match the active epoch.
3. `adapter_not_bound`: The offered `identity` does not match the bound epoch identity.
4. `turn_not_current`: The offered `turn_id` does not match the current turn slot.
5. `turn_canceled`: The current turn has been canceled.
6. `fallback_already_began`: A fallback rendering was already accepted for this turn.
7. `duplicate_rendering`: An authored rendering was already accepted for this turn.
8. `empty_rendering`: The `text` member is empty or contains only whitespace (`text.trim().isEmpty`).
9. **Accepted**: The text is accepted verbatim and spoken.

- `empty_rendering` does not resolve or consume the turn; a subsequent non-empty submission may still be accepted.
- Rejection reasons 1 through 7 are terminal for the offered `(binding_id, turn_id)` pair.

---

### 6.6 `POST /v1/approval`
Submits a tool approval request from an adapter's `PreToolUse` hook and holds the connection open for Core adjudication.

**Request Body:**
```json
{
  "schema": 1,
  "identity": {
    "agent_session_id": "session-exact",
    "pane_id": "workspace-and-pane-exact",
    "terminal_id": "terminal-exact"
  },
  "binding_id": "opaque",
  "session_id": "sess-exact",
  "tool_use_id": "toolu_exact",
  "tool_name": "Read",
  "tool_input": {
    "file_path": "path/to/file.dart"
  },
  "permission_mode": "manual",
  "cwd": "/path/to/cwd"
}
```

**Allow Response:**
```json
{
  "schema": 1,
  "tool_use_id": "toolu_exact",
  "decision": "allow",
  "reason": "approved",
  "snapshot": {
    "classification": {
      "result": "voice_approvable",
      "allow_list_entry": "Read",
      "permission_mode": "manual"
    },
    "cwd": "/path/to/cwd",
    "read_back": "Read the file path/to/file.dart",
    "tool_input": {
      "file_path": "path/to/file.dart"
    },
    "tool_name": "Read",
    "tool_use_id": "toolu_exact"
  }
}
```

**Defer Response:**
```json
{
  "schema": 1,
  "tool_use_id": "toolu_exact",
  "decision": "defer",
  "reason": "visual_route_reason"
}
```

#### Request and Response Rules
- Request shape is closed: every member is required, no extra members permitted, and `schema` must be `1`.
- `cwd` is validated for presence and string type only; it feeds read-back rendering and snapshot identity and never classification.
- The route captures the request identifier and complete action snapshot at receipt and binds them one-to-one to the request.
- The connection is held open for up to 50 seconds for Core adjudication.
- On allow, the response carries `decision: "allow"`, `reason: "approved"`, and the complete canonical snapshot document.
- On defer, the response carries `decision: "defer"`, the specific route reason, and no `snapshot` member.
- Transport errors follow Section 7.

---

## 7. Transport Errors and Precedence

Non-200 responses return `Content-Type: application/json; charset=utf-8` and a JSON body formatted as:
```json
{"schema":1,"error":"<code>"}
```

### Transport Error Table

| Status | `error` Code | Description and Exact Case |
|---:|---|---|
| 400 | `invalid_json` | The request body is not one complete JSON object. |
| 400 | `invalid_request` | A required member is missing, extra, null, empty where prohibited, or wrong-typed; the query is non-empty; HTTP is not version 1.1; or a GET carries a body. |
| 400 | `unsupported_schema` | `schema` exists as an integer but is not 1. |
| 401 | `unauthorized` | The bearer header is missing, repeated, malformed, or wrong. |
| 404 | `not_found` | The path is not one of the five exact paths. |
| 405 | `method_not_allowed` | The path exists under another method; `Allow` is `GET` for health/current, `PUT, DELETE` for presence, and `POST` for rendering and approval. |
| 413 | `body_too_large` | More than 1,048,576 raw body bytes arrive. |
| 415 | `unsupported_media_type` | A body-bearing request is not `application/json` or declares a non-UTF-8 charset. |
| 500 | `internal_error` | An unexpected server exception occurs; no exception detail is returned. |

### `Allow` Headers for 405 Method Not Allowed
- `GET /v1/health` -> `Allow: GET`
- `GET /v1/current` -> `Allow: GET`
- `/v1/presence` -> `Allow: PUT, DELETE`
- `POST /v1/rendering` -> `Allow: POST`
- `POST /v1/approval` -> `Allow: POST`

### Processing Precedence
Requests are evaluated in the following exact order:
1. **Path matching:** Non-existent path returns `404 not_found`.
2. **Method matching:** Disallowed method returns `405 method_not_allowed` with `Allow` header.
3. **Authentication:** Missing or invalid Bearer token returns `401 unauthorized`.
4. **HTTP version & query:** Non-1.1 version or non-empty query string returns `400 invalid_request`.
5. **GET-body prohibition / Media type:** GET with body returns `400 invalid_request`; non-JSON body-bearing request returns `415 unsupported_media_type`.
6. **Body size:** Body exceeding 1,048,576 bytes returns `413 body_too_large`.
7. **JSON decoding:** Malformed JSON or non-object body returns `400 invalid_json`.
8. **Schema validation:** Missing/non-integer schema returns `400 invalid_request`; integer schema != 1 returns `400 unsupported_schema`.
9. **Closed-shape validation:** Extra, missing, null, or wrong-typed members return `400 invalid_request`.
10. **Coordinator entry:** Synchronous execution and adjudication.

---

## 8. Identifier, Retry, and Extension Semantics

### Identifiers
- Turn identifiers (`turn_id`) and binding identifiers (`binding_id`) are opaque lowercase UUID v4 strings assigned exclusively by Auralis Core.
- The adapter obtains active identifiers from `GET /v1/current`, verifies its identity match, and carries the exact pair through its agent surface.

### Retry Rules
- **Discovery / Unavailability:** If `bridge.json` is absent, connection is refused, 401 is received, or health check fails, the adapter re-reads `bridge.json` at least once per second until registration succeeds.
- **500 Internal Error:** Guarantees no coordinator entry. The adapter may perform one byte-equivalent retry after confirming bridge health.
- **4xx Client Errors:** Must not be retried without correcting the request or contract violation.
- **Lost Rendering Response:** If a rendering response is lost after the request may have reached Core, the adapter may retry only the byte-equivalent request with the same identifiers. An earlier acceptance returns `duplicate_rendering` while that turn remains current; a later turn, fallback, cancellation, or retirement returns its normal higher-priority reason, and none emits again.
- **Fail Closed:** Unknown HTTP statuses, unknown error codes, or invalid response formats must fail closed and never be treated as accepted.

### Extension Rules
- Future additions within Version 1 introduce new `/v1/` paths.
- Any new turn-scoped request, response, or event must carry both `binding_id` and `turn_id`.
- Any new binding-scoped request, response, or event carries `binding_id` and `identity` and no `turn_id`.
- Breaking field changes, meaning changes, or validation modifications require incrementing the protocol version to `/v2` and `schema: 2`.

---

## 9. Downstream Consumption Contract

- **C3 (Adapter - `infiquetra/infiquetra-agent-plugins`):** Runs the presence renewal loop, implements the wire contract, verifies identity equality, and carries Core-assigned identifiers through MCP.
- **C5 (Audio):** Calls `startTurn()` on recording, `acceptFallback()` prior to fallback speech, and `cancelTurn()` on barge-in. Consumes `RenderingAccepted` and `BindingRetirement` events.
- **C7 (Rolling Text View):** Appends spoken text only upon playback confirmation from C5.
- **C8 (Approvals):** Uses `applyConfirmedForBinding()` with C2 binding confirmations to guard approval delivery.
- **C9 (Diagnostic Logging):** Implements durable logging sink for `BridgeLog` events without sensitive data or text payload.
