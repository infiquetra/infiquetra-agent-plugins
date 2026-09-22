---
description: First-run setup. Symlinks ~/bin/claude-channel + scaffolds source-env.sh / registry.json from examples (won't overwrite existing config).
argument-hint: ""
---

Run the idempotent first-run setup for `redis-channel`.

**Action:** Call the `redis_channel_setup` MCP tool (no arguments).

The tool returns `{ok: true, actions: [...], state: {...}}`. Render the result like this:

- For each action in `actions`, show a one-line bullet:
  - `linked` → `✓ ~/bin/claude-channel → <to>`
  - `created_from_example` → `✓ <target> (from <example>) — <next_step>`
  - `exists` → `· <target> (already exists; not overwritten)`
  - `skipped` → `⚠ <target> skipped: <reason>`
  - `error` → `✗ <target> failed: <detail>`
- Then show a summary of `state`:
  - If `all_ready: true`: "Setup complete. Try `claude-channel --help` in a new terminal."
  - If `all_ready: false`: list the remaining issues from the state fields (`wrapper_symlink_status`, `source_env_exists`, `registry_exists`) and what the user should do.

When the tool creates a fresh `registry.json` from the example, ALWAYS remind the user to edit it: the bundled example has placeholder Redis URL / password env name; they must fill in real values before the connect tool will work.

Re-running this command after every plugin update is safe — the symlink gets refreshed to the latest cached version, and existing user config is never overwritten.
