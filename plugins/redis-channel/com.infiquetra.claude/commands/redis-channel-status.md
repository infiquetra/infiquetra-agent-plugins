---
description: Show current redis-channel connection status (session, endpoint, uptime, consumer attachment, inbound backlog).
argument-hint: ""
---

Report the current `redis-channel` session state.

**Action:** Call the `redis_channel_status` MCP tool (no arguments).

After the tool returns:

- On `{"ok": true, "connected": false}` — say "Not connected. Use `/redis-channel-connect` to register."
- On `{"ok": true, "connected": true, ...}` — show a compact one-line summary:
  - `session_name` (e.g., `redis-channel-mcp-env-1a2b3c4d`)
  - `endpoint` (e.g., `default`)
  - `host` (e.g., `jeff-mac-studio.infiquetra.com`)
  - `uptime_seconds` formatted as `5m 12s` or `1h 34m` for readability
  - `consumer_attached` (`yes`/`no`) — when no, the auto-connect deferred path is still pending; will attach on next inbound or tool call
  - `pending_inbound` count (XLEN of the inbound stream) — informational; not all of these are unconsumed (XPENDING would be more accurate, deferred for v2)

If `pending_inbound > 0` and `consumer_attached == false`, mention that the next tool call will drain the backlog.
