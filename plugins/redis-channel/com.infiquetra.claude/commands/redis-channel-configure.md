---
description: Add or update an endpoint in the local redis-channel registry.
argument-hint: "[endpoint-name]"
---

Help the user configure (add or update) a redis-channel endpoint. If `$1` is supplied, use it as the endpoint name; otherwise ask.

**Pre-flight check.** If `~/.claude/channels/redis-channel/registry.json` does not exist AND `~/.claude/channels/redis-channel/source-env.sh` does not exist, suggest running `/redis-channel-setup` FIRST — that creates the per-deployment env file that populates the password env var. The user can still configure an endpoint without source-env.sh, but the connect won't work until they wire it up.

**Steps to gather:**

1. **Endpoint name.** If `$1` is set and matches `^[a-z0-9][a-z0-9_-]*$`, use it. Else ask: *"What endpoint name? (e.g., `default`, `mimir`, `staging`)"*. Regex-validate before proceeding.

2. **Redis URL.** Ask: *"Redis URL? (e.g., `redis://redis-host.example.com:6379/0` or `rediss://...` for TLS)"*. Must start with `redis://` or `rediss://`.

3. **Password env var.** Ask: *"What env var name holds the Redis password? (e.g., `MY_REDIS_PASSWORD`; leave blank if Redis has no auth)"*. The actual password value lives in env — populated by `source-env.sh`, not entered here.

4. **Display name** (optional). Ask: *"Human-readable display name? (shown in `/redis-channel-list`; default: same as endpoint name)"*. Blank = use endpoint name.

5. **Set as default?** Ask: *"Make this the default endpoint for `/redis-channel-connect` (no args)? (yes/no)"*. If only one endpoint will be configured, default to yes; if multiple, default to no.

6. **Confirm.** Summarize the values back to the user. Wait for explicit OK before writing.

7. **Call the `redis_channel_configure` MCP tool** with:
   - `endpoint_name=<from step 1>`
   - `redis_url=<from step 2>`
   - `redis_password_env`: the name from step 3, or omit the argument when that step was left blank
   - `display_name=<from step 4, omit if blank>`
   - `set_default=<from step 5>`

**After the tool returns:**

- On `{ok: true}` — report:
  - `action` (created/updated)
  - `endpoint_name` and `written` (path)
  - `endpoint_count` (total endpoints now configured)
  - `default_endpoint` (if non-null, mention which one is now default)
  - **Reminder:** if `redis_password_env` is set, the user must have a line in `~/.claude/channels/redis-channel/source-env.sh` like:
    ```
    export <VAR>="$(security find-generic-password -s 'my-redis-keychain-item' -w)"
    ```
    Tell them to edit that file (or run `/redis-channel-setup` first if it doesn't exist) before trying `/redis-channel-connect`.
- On `{ok: false}` — show `error` + `detail` and offer to retry with corrected values.
