# redis-channel ↔ external-router protocol (v1)

This document is the canonical specification for the Redis-based protocol that connects a Claude Code session (running the `redis-channel` channel plugin) to an external router/consumer (e.g., `hermes-claude-code-router`).

Both repos copy this file verbatim. Schema changes require synchronized PRs across both sides; the `v` field is bumped on any breaking change.

## Roles

- **CC plugin** (`redis-channel`) — Claude Code channel running as an MCP subprocess of a Claude Code session. Hermes-agnostic. Speaks this protocol over Redis.
- **Router** (external) — anything that drives the conversation: `hermes-claude-code-router` is the reference implementation; alternatives could include a web UI, CLI test harness, or mobile app.

## Transport

- **Redis 6+** (consumer groups + Streams required).
- Connection: TCP, auth via `requirepass` or ACL. URL configured per-endpoint on each side.
- **Durable streams** for message-bearing channels; **pub/sub** for fire-and-forget lifecycle events.
- All payloads are JSON. All payloads MUST include `"v": 1`. Mismatched versions: log and drop; do not crash.

## Key namespace

All keys live under `cc-sessions:`:

| Key | Type | Purpose | TTL |
|---|---|---|---|
| `cc-sessions:registry` | Hash | Static session metadata, field-per-session | None (lazy GC) |
| `cc-sessions:hb:<session_name>` | String | Heartbeat presence indicator | 60s, refreshed every 10s |
| `cc-sessions:<session_name>:inbound` | Stream | Messages from router → CC | MAXLEN ~10000 |
| `cc-sessions:<session_name>:outbound` | Stream | Replies from CC → router | MAXLEN ~10000 |
| `cc-sessions:<session_name>:permission_request` | Stream | CC asks for tool approval | MAXLEN ~1000 |
| `cc-sessions:<session_name>:permission_verdict` | Stream | Router answers approval request | MAXLEN ~1000 |
| `cc-sessions:events:<session_name>` | Pub/sub channel | Lifecycle and mode events | n/a |

Consumer groups:
- CC reads inbound + permission_verdict via group `cc:<session_name>` (consumer name `consumer-1`, single consumer per session).
- Router reads outbound + permission_request via group `<router-name>` (e.g., `hermes-router`).

## Presence

### Registration (CC on `/redis-channel connect`)

```
HSET cc-sessions:registry <session_name> <static_metadata_json>
SET  cc-sessions:hb:<session_name> <iso_timestamp> EX 60
```

Static metadata payload:

```json
{
  "v": 1,
  "session_name": "example-project-a3f7",
  "host": "host.example",
  "cwd": "/home/operator/example-project",
  "git_branch": "feature/redis-channel-scaffold",
  "pid": 12345,
  "started_at": 1716567890.123,
  "capabilities": ["reply", "permission", "askuserquestion_intercept"]
}
```

### Heartbeat

CC writes the hb key every 10s with `EX 60`. Six consecutive missed beats causes presence expiry. Session metadata in `cc-sessions:registry` stays in place (lazy GC); routers MUST filter by `EXISTS cc-sessions:hb:<session_name>` before treating an entry as live.

### Graceful disconnect (CC on `/redis-channel disconnect`, SIGTERM, SIGINT)

```
DEL  cc-sessions:hb:<session_name>
HDEL cc-sessions:registry <session_name>
PUBLISH cc-sessions:events:<session_name> {type:"unregistered", reason:"graceful", ts:...}
```

### Ungraceful disconnect

Hb key expires after 60s of no refresh. Router sees missing hb on next list operation; emits `unregistered{reason:"timeout"}` on the events pub/sub channel.

## Inbound (router → CC)

```
XADD cc-sessions:<session_name>:inbound *  payload <JSON>
```

Payload:

```json
{
  "v": 1,
  "router": "hermes-claude-code-router",
  "endpoint": "mimir",
  "source": "voice | dm | channel | thread",
  "chat_id": "<external-context-id, opaque to CC>",
  "user_id": "<external-user-id, opaque to CC>",
  "username": "<display name for the human>",
  "text": "<message body, already transcribed if voice>",
  "confidence": 0.93,
  "ts": 1716567890.123,
  "metadata": {}
}
```

CC consumes via:

```
XREADGROUP GROUP cc:<session_name> consumer-1 BLOCK 1000 STREAMS cc-sessions:<session_name>:inbound >
```

CC emits `notifications/claude/channel` to the Claude Code session with content:

```
<channel source="redis-channel" router="hermes-claude-code-router" endpoint="mimir"
         source_type="voice|dm|channel|thread" chat_id="..." user="..." username="..."
         confidence="0.93" ts="...">
<text body>
</channel>
```

CC `XACK`s on successful emission.

## Outbound (CC → router)

Claude calls the `reply` MCP tool. CC writes:

```
XADD cc-sessions:<session_name>:outbound *  payload <JSON>
```

Payload:

```json
{
  "v": 1,
  "session_name": "example-project-a3f7",
  "endpoint": "mimir",
  "chat_id": "<reply target, mirrored from inbound>",
  "text": "<reply body>",
  "voice": true,
  "in_reply_to": "<optional inbound stream ID for threading>",
  "ts": 1716567890.123
}
```

Router consumes via `XREADGROUP GROUP <router_name> consumer-1 BLOCK 1000 STREAMS ...:outbound >` and delivers via its native channel (Discord DM, voice channel, etc).

## Permission relay

### Request (CC → router)

When Claude Code core emits `notifications/claude/channel/permission_request`, CC writes:

```
XADD cc-sessions:<session_name>:permission_request *  payload <JSON>
```

Payload:

```json
{
  "v": 1,
  "session_name": "example-project-a3f7",
  "endpoint": "mimir",
  "request_id": "abcde",
  "tool_name": "Bash",
  "input_preview": "git push origin main",
  "description": "Push to remote",
  "destructive": true,
  "originating_chat_id": "<chat_id that started this routing>",
  "ts": 1716567890.123
}
```

`request_id` is the 5-char id supplied by Claude Code core (not generated by CC).

`destructive` is `true` when:
- `tool_name` is one of `Write`, `Edit`, `NotebookEdit`
- `tool_name` is `Bash` AND `input_preview` matches one of the destructive regex patterns in `protocol.py`

### Verdict (router → CC)

Router collects user response (within `permission_window_seconds`, default 30) and writes:

```
XADD cc-sessions:<session_name>:permission_verdict *  payload <JSON>
```

Payload:

```json
{
  "v": 1,
  "session_name": "example-project-a3f7",
  "endpoint": "mimir",
  "request_id": "abcde",
  "verdict": "allow | deny",
  "source": "voice | dm | channel | thread | timeout",
  "voice_confidence": 0.91,
  "echo_confirm_outcome": "passed | cancelled | not_required",
  "ts": 1716567890.456
}
```

CC consumes via its `cc:<session_name>` group and emits `notifications/claude/channel/permission` to Claude Code core.

`echo_confirm_outcome` is `passed` if a destructive request's 3-second cancel window elapsed silently; `cancelled` if "cancel" was heard within the window; `not_required` for non-destructive requests.

## AskUserQuestion interception

`AskUserQuestion` is a Claude Code tool that surfaces structured multi-choice UI on the terminal. The channel protocol does not natively support structured questions.

**The CC plugin intercepts the tool call** before it reaches the user. When Claude calls `AskUserQuestion` from a channel session:

1. CC plugin's MCP server intercepts the tool invocation.
2. Renders the structured question as inline text (markdown), routed through the `reply` tool with `voice=False` (if mode permits) or both `voice=True` + text per the originating source:

   ```
   I need to make a decision. Please reply with one of these options:

   **Which approach should I take?**
   - **A)** Use a connection pool — faster, more complex
   - **B)** Open per-request — simpler, slower
   - **C)** Cache results — fastest, stale data risk

   Reply with the letter (A, B, or C), or describe your choice in your own words.
   ```

3. CC parses the user's next inbound message and matches against options (letter, label substring, free-text).
4. CC returns the matched answer to the `AskUserQuestion` caller as the tool result.

This is implemented in MCP server middleware, not via agent-file coaching. Behavior is deterministic regardless of Claude's training.

## Gate-approval notices (transport-agnostic convention)

A connected session may deliver a durable approval gate (the saga `/outcome` R20 frontier-approval gate) over the channel so a keyboard-less operator can answer it. **This convention adds no new stream, verb, or message type to the protocol** — the gate semantics live entirely in the saga session, and redis-channel stays a generic bridge (it never learns about saga gates):

- **Notice:** the session sends the gate prompt as an ordinary **Outbound** `reply` (§Outbound). Its text carries a **gate id** of the form `<outcome_id>@r<spec_revision>` plus lettered choices (`A) approve` / `B) hold`). To the router this is an ordinary reply message.
- **Answer:** the operator's reply arrives as an ordinary **Inbound** (§Inbound). The session — not the router — correlates the reply to the pending gate id and applies the verdict via the saga CLI. The router delivers it like any other inbound.
- **Authority / access:** unchanged and entirely the transport's. The sender was already authorized by the transport's access policy upstream of the session (permission relay §Permission relay documents the analogous already-gated trust for permission replies). The session records the router-set sender/source as gate provenance; it never re-authorizes a sender, and a reply that matches no pending gate is ignored. A router MUST NOT special-case gate notices — they are ordinary Outbound/Inbound messages.

## Lifecycle events (pub/sub)

```
PUBLISH cc-sessions:events:<session_name> <JSON>
```

Event types:

| Type | Direction | Payload extras |
|---|---|---|
| `registered` | CC → router | `static_metadata` |
| `unregistered` | CC → router (graceful) OR router → router (timeout) | `reason: "graceful" \| "timeout"` |
| `mode_change` | router → CC | `mode: "normal"|"routing"`, `endpoint`, `reason` |
| `routing_target_changed` | router → CC | `endpoint`, `new_target: "<session_name>"|null`, `reason: "user_phrase"|"slash"|"llm_tool"` |
| `presence_ping` | either way | `who: "cc"|"router"` |

Both sides subscribe to relevant channels. Pub/sub is at-most-once; do not rely on it for state — use streams for durable handoffs.

## Programmatic session lifecycle (consumer-side)

This section documents how an external router (or any tool, e.g. a CLI test harness, a future router LLM) can spawn, observe, and tear down redis-channel-attached Claude Code sessions on the local host. The CC plugin exposes this via the `claude-channel` shell wrapper (`plugins/redis-channel/scripts/claude-channel.sh`, symlinked into `~/bin/` by the install script).

### Spawn a new session

```
claude-channel --session-name <NAME> --cwd <ABS_PATH> --bg
```

- `--session-name <NAME>` — required for programmatic use. Validated against `^[a-z0-9][a-z0-9_-]{0,63}$`. Wrapper exports it as `CLAUDE_SESSION_NAME` for the plugin.
- `--cwd <ABS_PATH>` — sets the spawned session's working dir. Load-bearing: the auto-name and registry-recorded `cwd` field both derive from this.
- `--bg` — claude's native background-agent flag. Passes through the wrapper to claude. Claude prints the agent ID + attach/logs/stop hints to stdout, then returns. The agent runs detached with a native PTY managed by claude.

The wrapper sets `CLAUDE_CHANNEL_AUTO_CONNECT=1`, so the spawned CC session auto-registers presence + creates the inbound consumer group at startup. The caller MUST poll `EXISTS cc-sessions:hb:<NAME>` with backoff (100ms) up to a 15s timeout before XADD'ing inbound. Once `hb` exists, the session is live; XADD-ed inbound will not be lost (the consumer group was created BEFORE presence published — XREADGROUP `>` picks up anything in the gap once the consumer thread starts on first MCP tool dispatch).

Discovering the spawned agent's claude-side ID (if needed): `claude agents --json` returns all live background sessions including the new one. For redis-channel purposes, `cc-sessions:registry`'s entry for `<NAME>` is the canonical source — it carries `pid`, `host`, `cwd`, `git_branch`, `started_at` — and is the only handle the protocol promises.

### Verify session readiness

The canonical readiness signal is `EXISTS cc-sessions:hb:<NAME>` returning 1. The MCP-side `redis_channel_status` tool also reports it, but external callers should use the Redis check directly — it's faster and doesn't require any MCP transport.

### List live sessions

```
HGETALL cc-sessions:registry
```

For each `<NAME> -> <JSON>` pair, filter by `EXISTS cc-sessions:hb:<NAME>` to drop stale entries. See §Presence for full details.

### Tear down a session

Two equivalent paths:

**Via claude-native stop** (when claude knows the agent ID — i.e., the spawn captured it from claude's stdout):

```
claude stop <agent-id>
```

This is the cleanest path: claude's process manager handles the SIGTERM + cleanup, and the redis-channel plugin's signal handlers fire to disconnect cleanly.

**Via redis-channel presence registry** (when only the redis-channel session name is known):

```
HGET cc-sessions:registry <NAME>  →  parse JSON  →  read `pid` and `host`
```

If `host != local hostname`: cross-host kill is **not supported in v1** — abort.

If `host == local hostname`: **verify the PID still owns a CC process** before SIGTERM, to defend against PID reuse:

```
ps -p <pid> -o comm=
# expect output containing "python3" or "server" — if neither, abort
```

Then:

```
kill <pid>             # SIGTERM; the CC plugin's signal handlers + atexit cleanly disconnect.
# Optional: wait until cc-sessions:hb:<NAME> disappears (a few seconds typical).
```

If the CC process died ungracefully (SIGKILL, crash), the registry entry persists until either (a) the next `redis_channel_list` call's GC sweep removes it, or (b) the next `list_live_sessions(gc_stale=True)` from a different live session removes it. The `hb:<NAME>` key expires within the TTL window (60s default).

### Collision handling

If a wrapper is invoked with `--session-name <NAME>` where `cc-sessions:hb:<NAME>` already exists, the new CC session's `connect` logic replaces the existing session (the older one is disconnected). Programmatic callers should `EXISTS hb:<NAME>` BEFORE spawn to avoid surprise kicks; expose a `force=True` opt-in to bypass.

### Environment variables the wrapper sets

The wrapper exports the following into the spawned CC's environment before exec:

| Var | Effect |
|---|---|
| `CLAUDE_SESSION_NAME` | (if `--session-name` given) override auto-name |
| `CLAUDE_CHANNEL_ENDPOINT` | (if `--endpoint` given) pick a specific configured endpoint |
| `CLAUDE_CHANNEL_AUTO_CONNECT=1` | always set; gates the plugin's auto-connect at MCP startup |
| `REDIS_CHANNEL_KEYCHAIN_ITEM` and `REDIS_CHANNEL_PASSWORD_ENV` | Both must be set. On macOS the wrapper reads that keychain item and exports it under the named variable, unless the variable is already set. The primary mechanism is `~/.claude/channels/redis-channel/source-env.sh`, which `scripts/mcp_server.py` sources. |

### Soft requirements + assumptions

- The wrapper requires `claude` in `PATH` or `CLAUDE_BIN` env override.
- The `--dangerously-load-development-channels` flag is prepended by default (development preview); set `CLAUDE_CHANNEL_PRODUCTION=1` to omit when channels graduate from research preview.
- Background-mode logs go to `${XDG_CACHE_HOME:-$HOME/.cache}/claude-channel/sessions/<name>-<epoch>.log`. No rotation in v1 — sweep is the user's problem (Phase 6 polish candidate).

## Versioning and compatibility

- All payloads carry `v: 1`.
- Adding optional fields is backwards-compatible; routers/CC MUST ignore unknown fields.
- Removing or repurposing fields requires `v` bump and synchronized release.
- The `pydantic` models in `server/protocol.py` (CC) and `hermes_claude_code_router/protocol.py` (router) are the enforcement layer. Both repos validate inbound payloads strictly.

## Reserved future expansion

- `notifications/claude/channel/question_request` — IF Claude Code adds it natively, this protocol grows a `question_request`/`question_verdict` stream pair and the AskUserQuestion interception is replaced by passthrough.
- Mode awareness — IF Claude Code exposes session mode, add a `mode_state` lifecycle event.
- Multi-router-per-session — currently 1 session : 1 router consumer group. Could grow to a fanout model.
