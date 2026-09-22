---
description: Cleanly disconnect this Claude Code session from its redis-channel endpoint.
---

**Action:** Call the `redis_channel_disconnect` MCP tool (no arguments).

After the tool returns:
- On `{"ok": true, "was_connected": true}` — confirm the named session has been removed from the registry. Mention briefly that any router pointing at this session will lose its target (Phase 2+).
- On `{"ok": true, "was_connected": false}` — tell the user the session wasn't connected; no action was needed.
- On `{"ok": false}` — show `error` + `detail`.

Effects on success: stops the heartbeat thread, deletes `cc-sessions:hb:<name>`, HDELs from `cc-sessions:registry`, and publishes an `unregistered` lifecycle event on `cc-sessions:events:<name>`.
