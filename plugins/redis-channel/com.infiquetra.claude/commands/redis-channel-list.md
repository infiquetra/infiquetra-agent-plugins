---
description: List all live Claude Code sessions registered at this session's connected redis-channel endpoint.
---

**Action:** Call the `redis_channel_list` MCP tool (no arguments). Requires a prior `/redis-channel-connect`.

On `{"ok": true}`, render the `sessions` array as a compact table or bullet list. Useful columns:
- `session_name` (mark `is_self: true` with `(this session)` next to the name)
- `host`
- `cwd`
- `git_branch` (omit if null)
- elapsed since `started_at`

Show `count` in the header, and the `endpoint` they belong to. Sort is already by `started_at` ascending.

On `{"ok": false, "error": "not connected ..."}` — tell the user to run `/redis-channel-connect` first.

Stale entries (heartbeat expired) are already filtered out and lazily GC'd from the registry by the tool — you do not need to do any extra filtering.
