---
description: Connect this Claude Code session to a configured redis-channel endpoint. Registers session presence in Redis.
argument-hint: "[endpoint-name] [--session-name <name>] [--debug]"
---

Connect the current session to a configured `redis-channel` endpoint.

**Argument parsing:**
- First positional arg = endpoint name (optional). If omitted, the server resolves to `registry.defaults.default_endpoint`, with a single-endpoint convenience fallback when only one is configured.
- `--session-name <name>` flag (optional) — pass that as `session_name`. Otherwise omit and let the server auto-generate `<cwd-basename>-<short-hash>`.
- `--debug` flag (optional) — pass `debug=true` to the tool. **Default `false`.** Without this flag, reply behavior is *quiet*; with it, reply behavior is *verbose* (see below).

**Action:** Call the `redis_channel_connect` MCP tool with `endpoint`, `session_name`, and `debug` set per the above.

After the tool returns:
- On `{"ok": true}` — report the resolved `session_name`, the endpoint, the heartbeat interval, and the `debug` mode. Briefly note that the session is now visible to the router and the heartbeat refreshes every 10s.
- On `{"ok": false, "error": "registry not configured"}` — show the `hint` from the response and stop. The user needs to run `/redis-channel-configure` first.
- On `{"ok": false, "error": "endpoint not found"}` — show the `detail` (which lists available endpoints) and stop.
- On any other `{"ok": false}` — show `error` + `detail` and stop.

**Reply behavior after this connect call (read carefully):**

- If `debug=false` (the default): when channel notifications arrive and you call the `reply` tool, **do NOT also narrate the reply in the local terminal**. The user is on the channel side (Discord/voice/etc.), not the terminal — your terminal narration adds noise without value. Just call the tool; the tool's structured result is enough confirmation.
- If `debug=true`: feel free to print a one-line confirmation in the terminal after each `reply` (e.g. `→ replied to <chat_id> · msg_id=<x>`). The developer is debugging from the terminal in this mode.

Endpoints live in `~/.claude/channels/redis-channel/registry.json`. A second connect call automatically disconnects the previous session first.
