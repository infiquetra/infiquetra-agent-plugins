# Changelog

All notable changes to the `redis-channel` plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and
the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.3] - 2026-09-22

0.5.3 — imported from infiquetra-claude-plugins@acc99fe7 (upstream 0.5.2); authored here from this commit; no provenance manifest from now on.

### Layout

Claude commands, the coach agent, and the MCP registration now live under `com.infiquetra.claude/`. The MCP server code stays the portable `server/` package. Claude launches `scripts/mcp_server.py` via `${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py`. The upstream `.mcp.json` shell (`uv run --with mcp --with redis --with pydantic python3 -m server`) did not name a file under `${CLAUDE_PLUGIN_ROOT}`, which this repository's packaging check requires, and it imported the runtime packages before any `--help` could run.

`server/__init__.py` `__version__` was `0.5.0` while the plugin manifest was `0.5.2`. Both are `0.5.3`. FastMCP 1.x has no version constructor argument and otherwise reports the `mcp` library version as `serverInfo.version`. `build_app` assigns the package version on the low-level server. The same number is the `serverInfo` literal in `scripts/mcp_server.py`.

The adapter manifest's `repository` now names this repository. The import left the upstream URL in place.

### Behaviour that had to change

- `scripts/integ_test.py` skips, exit 0, unless `REDIS_CHANNEL_INTEG_HOST` and `REDIS_CHANNEL_INTEG_PASSWORD` are both set. It no longer defaults the host to a lab hostname, and it no longer reads `HERMES_REDIS_PASSWORD`. `REDIS_CHANNEL_INTEG_PORT` still defaults to `6379`. `REDIS_CHANNEL_INTEG_VAR` names the env var the server's registry reads; its default is `REDIS_CHANNEL_INTEG_PASSWORD`. The harness starts `python -m server` with that interpreter. It no longer calls `uv run` against the old repository's project.
- `scripts/claude-channel.sh` no longer reads a hard-coded macOS keychain item. It reads an item only when both `REDIS_CHANNEL_KEYCHAIN_ITEM` and `REDIS_CHANNEL_PASSWORD_ENV` are set. The default development-channel plugin ref is `plugin:redis-channel@infiquetra-agent-plugins` (`CLAUDE_CHANNEL_PLUGIN_REF` overrides it).
- Symlink auto-refresh and `scripts/install-claude-channel.sh` recognize two Claude cache roots: `infiquetra-agent-plugins` (this catalog) and `infiquetra-plugins` (installs from before the move). A symlink outside both is still left alone.
- `scripts/mcp_server.py` and `python -m server` answer `--help` before importing `redis`, `mcp`, or `pydantic`.

### Tests

Carried, from the upstream repository's root `tests/` at `acc99fe7`, into `plugins/redis-channel/tests/`:

- `test_redis_channel_channel.py`
- `test_redis_channel_consumer.py`
- `test_redis_channel_notifier.py`
- `test_redis_channel_presence.py`
- `test_redis_channel_producer.py`
- `test_redis_channel_protocol.py`
- `test_redis_channel_redis_client.py`
- `test_redis_channel_registry.py`
- `test_redis_channel_session_id.py`

The protocol test's `sys.path` insert pointed at `plugins/redis-channel` relative to the old repository root. It now uses this package's `tests/conftest.py`, which inserts the package root. One presence-collision fixture stored a personal absolute path as a working directory; that value is now `/home/operator/example-project`. A new test covers symlink refresh under the `infiquetra-agent-plugins` cache root. `tests/test_entrypoint.py` runs `scripts/mcp_server.py --help`, `python -m server --help`, `scripts/integ_test.py --help`, the integration skip, and `scripts/claude-channel.sh --help` with `REDIS_CHANNEL_*` removed from the environment.

No upstream test was dropped. Nothing in this package reached Fleet Core, so there is no `fleet-bundle.json`.

The plugin-test job's dependency list gained `fakeredis`, `mcp>=1,<2`, `pydantic`, and `redis`. `mcp` is pinned below 2 because 2.x removed `mcp.server.fastmcp`.

## [0.5.2] - 2026-08-08

### Added - house-style presentation contract on the channel coach agent (#704)

- `redis-channel-coach` agent definition gains a "Presentation contract (Infiquetra house style)" section, copied verbatim from `plugins/house-style/references/subagent-presentation-preamble.md`.

## [0.5.1] - 2026-07-05

### Documented — transport-agnostic gate-approval notice/answer convention (#379)

`PROTOCOL.md` now documents how a connected session delivers a saga `/outcome` approval gate over the
channel and captures the operator's answer. **No new stream, verb, or message type** — a gate notice
is an ordinary Outbound `reply` (carrying a `<outcome_id>@r<rev>` gate id) and the answer is an
ordinary Inbound; the gate semantics live entirely in the saga session, and redis-channel stays a
generic router-agnostic bridge (a router MUST NOT special-case gate notices). Authority remains the
transport's existing access policy; the session records provenance and never re-authorizes a sender.
Docs-only change — no code behavior change.

## [0.5.0] - 2026-06-21

### Added — Phase 6 polish: configure command + auto-refresh symlink + ARCHITECTURE.md (v0.5.0)

Phase 6 wraps up the CC-plugin side of the master plan. Three deliverables:

**`/redis-channel-configure` slash command + `redis_channel_configure` MCP tool.** Was a stub since Phase 0; now fully implemented. Interactive endpoint setup that asks for redis_url, redis_password_env, display_name, set-as-default, then writes/updates `~/.claude/channels/redis-channel/registry.json` atomically. Idempotent — re-running for the same endpoint name overwrites the entry; other endpoints + defaults preserved. Validates: endpoint name matches `^[a-z0-9][a-z0-9_-]*$`, redis_url starts with `redis://` or `rediss://`. Does NOT create source-env.sh (that's `/redis-channel-setup`'s job).

**Auto-refresh stale symlink in MCP startup nag.** Extends the v0.4.14 startup nag: when `~/bin/claude-channel` is a symlink pointing into our plugin cache hierarchy but at an OLDER version (the common "plugin updated, symlink lagged" case), the MCP server now refreshes it in-place + logs INFO. Scope: only self-managed symlinks; user-customized symlinks pointing elsewhere are left alone (nag still fires for those). Missing config files (source-env.sh, registry.json) stay nag-only — never auto-create user config. New helpers `_auto_refresh_stale_symlink()` and `_is_our_plugin_cache_target()`.

**`plugins/redis-channel/ARCHITECTURE.md`** — system narrative with a Mermaid diagram covering roles, round-trip flow, components in this plugin, state + lifecycle semantics, config files, Claude Code integration knobs, known limitations (cross-ref'd to LEARNINGS). Plugin-side only; router-specific details stay in the router repo.

**README polish** — Status section restructured to reflect what's actually shipped (P1, P2, P2.5, P6) and what's deferred to the router repo. Quickstart rewritten around `/redis-channel-setup` + `/redis-channel-configure` (was: "manually copy registry.example.json"). Known limitation about bg sessions called out at the top.

Tests: 14 new (6 auto-refresh + 8 configure-endpoint); 187 redis-channel tests total; ruff clean.

This release marks the CC-plugin side of the master plan as feature-complete. Router-side work (text routing, voice routing, permission relay, LLM tools) lives in [`hermes-claude-code-router`](https://github.com/infiquetra/hermes-claude-code-router).

### Fixed — auto-connect falls back to single-endpoint convenience (v0.4.18)

Jeff tested v0.4.17, found `--bg` still landed in a session where `/redis-channel-list` reported "Not connected". Diagnostic via `ps eww -p <mcp-pid>` confirmed `CLAUDE_CHANNEL_AUTO_CONNECT=1` and `CLAUDE_SESSION_NAME=plugin-testing` DID make it into the bg session's env (so v0.4.17's `--settings` injection works). The actual bug: `_maybe_auto_connect` tried `CLAUDE_CHANNEL_ENDPOINT` env → `registry.defaults.auto_connect_endpoint` → bailed with "no endpoint resolvable" when both were unset.

Existing solo-developer setups (like Jeff's) have ONE endpoint configured (`mimir`) but never set `auto_connect_endpoint` (the field was added in v0.4.11; older registries lack it). The fix is to fall through to `Registry.resolve_default_endpoint()`, which already has the single-endpoint convenience built in from v0.4.11.

New resolution order in `_maybe_auto_connect`:
1. `CLAUDE_CHANNEL_ENDPOINT` env var (explicit per-invocation override; set by the wrapper when user passes `--endpoint`)
2. `registry.defaults.auto_connect_endpoint` (registry-wide pin; useful for multi-endpoint setups)
3. `registry.resolve_default_endpoint()` — covers two cases: (a) `defaults.default_endpoint` names a configured endpoint, or (b) single-endpoint convenience fallback when only one endpoint is configured

Multi-endpoint registries without a resolvable default still log a warning + skip (we can't guess which endpoint to pick). The warning message now includes the inner error from `resolve_default_endpoint` so the user knows whether the issue is multi-endpoint ambiguity vs missing config.

For Jeff's specific setup (`mimir` is the only endpoint), `claude-channel --session-name plugin-testing --bg` will now auto-connect to `mimir` without any explicit endpoint flag or registry edit.

New unit test: `test_maybe_auto_connect_falls_back_to_single_endpoint_convenience`. 173 redis-channel tests total; ruff clean.

### Fixed — `claude-channel --bg` injects env via `--settings` so auto-connect fires in dispatched sessions (v0.4.17)

Jeff tested v0.4.16's --bg path against a real backgrounded session, found that `/redis-channel-list` inside it reported "Not connected" — auto-connect didn't fire. Root cause: **background-dispatched claude sessions do not inherit env from the invoking shell**. claude --bg sends a spawn RPC to an agent dispatcher; the dispatched session starts with the dispatcher's env, not the wrapper's. So `CLAUDE_CHANNEL_AUTO_CONNECT=1` (set by the wrapper before exec) never reached the spawned MCP server.

Verified by inspecting `~/bin/claude-codex`, which solves the same problem the same way: when --bg is detected, prepend `--settings '{"env":{...}}'` to claude's argv. claude reads the settings JSON and propagates the env entries into the dispatched session.

**Fix in the wrapper:** when `--bg` / `--background` appears in pass-through args, the wrapper now builds a settings JSON containing the env vars the plugin needs and injects it as `--settings '{"env":{...}}'`. Vars injected:

- `CLAUDE_CHANNEL_AUTO_CONNECT=1` (always — the gate that triggers auto-connect)
- `CLAUDE_SESSION_NAME` (if `--session-name` was set)
- `CLAUDE_CHANNEL_ENDPOINT` (if `--endpoint` was set)

`HERMES_REDIS_PASSWORD` is NOT injected — it's per-deployment and handled by `~/.claude/channels/redis-channel/source-env.sh`, which the MCP launcher (`.mcp.json`) sources before starting each MCP server, including in dispatched bg sessions.

If the user supplied their own `--settings` in passthru args (rare), the wrapper warns instead of double-injecting and reminds the user to put the env vars in their settings themselves. Matches the codex pattern (line 332-335 of `~/bin/claude-codex`).

Manual smoke-tested: `--bg` alone → settings injected with the right env shape; no `--bg` → no injection (foreground inherits env normally); `--bg --settings <user>` → warn + leave their settings alone. 172 redis-channel tests pass; ruff clean.

### Changed — `claude-channel` is now a thin pass-through; `--bg` goes straight to claude (v0.4.16)

Jeff caught that v0.4.15's tmux-based `--bg` was solving the wrong problem. **`claude --bg` is a real (if undocumented-in-help) claude flag** that spawns a native background agent, prints the agent ID + attach/logs/stop hints, and returns. Verified:

```
$ claude --bg --help
backgrounded · 1d80a5ac (idle — send a prompt to start)
  claude agents             list sessions
  claude attach 1d80a5ac    open in this terminal
  claude logs 1d80a5ac      show recent output
  claude stop 1d80a5ac      stop this session
```

Claude Code already handles background agents natively — process management, PTY allocation, logging, attach, stop — all built in. The wrapper trying to reimplement this with tmux was redundant + buggy (the v0.4.13 nohup version crashed because no PTY; the v0.4.15 tmux version worked but added a tmux dependency for no reason since claude handles it natively).

**Fix.** Strip the wrapper down to a thin pure-pass-through:

- `--bg` (and everything else claude understands: `--print`, `--resume`, `--model`, `--remote-control`, `--worktree`, etc.) is now an UNCLAIMED flag → falls through to claude's argv verbatim.
- Wrapper's only owned flags: `--session-name`, `--endpoint`, `--cwd`, `--help`.
- Removed: `--bg` / `--background` arg-parsing case, `BACKGROUND` variable, the entire if-bg-then-spawn-detached block, tmux logic, `--print-info` (claude's `agents --json` and the redis-channel presence registry are the canonical discovery mechanisms — wrapper doesn't need to invent a JSON emit).
- The pass-through is greedy: any arg the wrapper doesn't claim goes to claude. Standard claude flags Just Work.

**Tmux dependency dropped.** v0.4.15's hard requirement on tmux for `--bg` is gone — `claude --bg` doesn't need tmux. (The user's `~/bin/claude-codex` confirmed the pattern: passes `--bg` straight to claude in its argv array.)

For Phase 5 (Mimir programmatic spawn): callers do `claude-channel --session-name foo --bg`. Claude returns the agent ID; caller polls `cc-sessions:hb:foo` for readiness (the canonical signal — works regardless of how claude was launched); kills via `claude stop <agent-id>` or by SIGTERM from `cc-sessions:registry`'s PID.

`--print-info` removed since callers either pass `--session-name` (and already know it) or query `claude agents --json` / `cc-sessions:registry` to discover. Net: simpler wrapper, no wrapper-specific output format to learn.

`install-claude-channel.sh` unchanged (still works as the manual install fallback). The `/redis-channel-setup` slash command shipped in v0.4.14 is still the canonical setup path.

### Fixed — `claude-channel --bg` spawns via tmux to give claude a real PTY (v0.4.15)

Jeff tested v0.4.14's wrapper, got an immediate crash with the log showing:
```
Error: Input must be provided either through stdin or as a prompt argument when using --print
```

Root cause: `claude --help` documents that "non-interactive mode (via -p, or **when stdout is not a TTY**, e.g. piped or redirected output)" auto-engages. The v0.4.13 `--bg` path used `nohup ... > log 2>&1 &`, which redirects stdout to a file → claude detects no-TTY → enters `--print` mode → no prompt arg present → exits immediately.

Fix: spawn claude inside a detached **tmux** session, which provides a real PTY headlessly. Tested empirically: `tmux new-session -d` works from non-TTY contexts (verified from a stdio-only shell), the spawned process gets a working PTY, and the pane's output mirrors to the log file via `tmux pipe-pane -o`.

Bonus: `tmux attach -t <session-name>` lets the user inspect a backgrounded session interactively. The tmux session name = the redis-channel session name (natural mapping).

Trade-off: requires tmux installed. Wrapper now hard-fails with a clear error if tmux is missing: `background mode requires tmux (install via 'brew install tmux' on macOS or your package manager on Linux)`. macOS users with Homebrew, most Linux distros, and Jeff's setup all have tmux already; for environments that don't, foreground mode still works without it. Linux fallback to `script(1)` or Python `pty` was considered and rejected — `script` errors with `tcgetattr/ioctl: Operation not supported on socket` when called from a non-TTY context (e.g., Phase 5's Mimir-spawn from Hermes), and Python `pty` adds an interpreter dependency that tmux doesn't need.

Output format unchanged. `--print-info` JSON still reports `pid` (now the tmux pane's claude PID) and `log_path` (now mirrored from tmux pipe-pane). New stderr line on spawn when not using `--print-info`: `attach with: tmux attach -t <session-name>`.

Manual smoke-tested with `CLAUDE_BIN=/bin/sleep CLAUDE_CHANNEL_PRODUCTION=1` to confirm tmux session is created, pane_pid is captured correctly, log file mirroring is set up. Existing tests still pass; no unit tests added for the wrapper here (it's bash; subprocess.run tests deferred to a follow-up).

### Added — `/redis-channel-setup` self-service install + MCP startup nag (v0.4.14)

Jeff flagged that v0.4.13's `install-claude-channel.sh` requires the user to remember to run a shell script after every plugin update — bad UX. Claude Code plugins don't expose a `postinstall` hook (verified by surveying the official plugins; Discord uses skills for setup, no install lifecycle hook exists), so the best fix is a self-service slash command + a passive startup check that nags when state drifts out of date.

**New `redis_channel_setup` MCP tool + `/redis-channel-setup` slash command.** Idempotent — safe to re-run after every plugin update. Two actions:

1. Symlink `~/bin/claude-channel` to `$CLAUDE_PLUGIN_ROOT/scripts/claude-channel.sh` (always overwrites — that's how plugin-update tracking works).
2. Scaffold `~/.claude/channels/redis-channel/source-env.sh` and `registry.json` from the bundled examples in `docs/` IF those user files don't already exist. **Never overwrites existing user config** — re-running on a configured deployment is a no-op for config files.

Returns a per-action status report (`linked` / `created_from_example` / `exists` / `skipped` / `error`) so the slash command markdown can render which actions did what.

**MCP startup nag.** New `_log_setup_nag()` runs once when the MCP server boots (after `_enable_channel_capability`, before `app.run()`). Checks whether the symlink is current, source-env.sh exists, registry.json exists. If anything's missing or stale, logs a single WARNING to stderr listing the issues and suggesting `/redis-channel-setup`. Passive — never blocks startup, never modifies anything, never fails.

This means: after every plugin update, the first time the user reconnects MCP, they see a stderr nag like:

```
WARNING redis-channel setup is incomplete — run /redis-channel-setup.
Issues: ~/bin/claude-channel: stale (expected target: .../0.4.14/scripts/claude-channel.sh)
```

They run `/redis-channel-setup` once, the symlink refreshes, the nag goes away on next startup. No more remembering to run install scripts manually.

Tests: 7 new for setup (fresh install, preserve user config, refresh stale symlink, broken plugin root, state reporting, nag fires when incomplete, nag silent when ready); 172 redis-channel tests total; ruff clean.

`install-claude-channel.sh` stays in the repo as a manual fallback for cold-install scenarios (e.g., bootstrapping before Claude itself can talk to the plugin), but the slash command is now the canonical path.

### Added — `claude-channel` wrapper + PROTOCOL.md programmatic-launch contract (v0.4.13)

Third and final slice of Phase 2.5. Together with v0.4.11 (router-agnostic refactor + registry resolver) and v0.4.12 (env-var auto-connect + status command), this closes the loop on "redis-channel sessions startable from outside the terminal."

**`~/bin/claude-channel` wrapper** at `plugins/redis-channel/scripts/claude-channel.sh`, installed via `install-claude-channel.sh` which symlinks the user's `~/bin/claude-channel` at the latest plugin cache version's wrapper. Flags:

- `--session-name NAME` → exports `CLAUDE_SESSION_NAME`; validated with bash regex matching `session_id.py:_NAME_RE` BEFORE spawning claude (exit 2 on mismatch).
- `--endpoint NAME` → exports `CLAUDE_CHANNEL_ENDPOINT`.
- `--bg`/`--background` → POSIX-portable detach (subshell + nohup + redirect + disown — works on macOS without `setsid`). Log at `${XDG_CACHE_HOME:-$HOME/.cache}/claude-channel/sessions/<name>-<epoch>.log`.
- `--cwd PATH` → cd before exec. Load-bearing for Phase 5: routers spawn in target dirs; auto-name derivation uses cwd.
- `--print-info` → emit JSON `{session_name, endpoint, log_path, pid, cwd, mode}`. **Foreground: prints to stderr** (no stdout pollution while claude is interactive). **Background: prints to stdout** (caller capturing wrapper output gets the JSON cleanly).
- `--help`.

Env knobs:
- `CLAUDE_BIN` override (required when claude isn't in `$PATH`, e.g. Phase 5's Hermes-runtime context).
- `CLAUDE_CHANNEL_PRODUCTION=1` to omit dev-only `--dangerously-*` flags.
- `CLAUDE_CHANNEL_PLUGIN_REF` to override the development-channels plugin URI.

The wrapper sets `CLAUDE_CHANNEL_AUTO_CONNECT=1` and best-effort sources `HERMES_REDIS_PASSWORD` from macOS keychain (backward-compat for the original dev setup; future deployments should rely on `~/.claude/channels/redis-channel/source-env.sh`).

**`PROTOCOL.md` programmatic-launch contract.** New section documents spawn/list/kill semantics for external consumers (Phase 5's Mimir LLM tools, future routers):

- **Spawn**: `claude-channel --bg --session-name <N> --cwd <D> --print-info` → parse JSON → poll `EXISTS cc-sessions:hb:<N>` until live.
- **List**: `HGETALL cc-sessions:registry` filtered by `EXISTS cc-sessions:hb:<name>`.
- **Kill**: HGET PID, verify with `ps -p <pid> -o comm=` to defend against PID reuse, then SIGTERM.
- **Collision**: spawning with an existing session-name replaces the previous session; callers SHOULD `EXISTS` check first.

Manual smoke tests: `--help` works, invalid session-name rejected with exit 2 before spawn, foreground prints JSON to stderr, background prints to stdout + spawns detached process. Programmatic integ test (subprocess.run on the wrapper) deferred to a follow-up PR.

### Added — env-var-driven auto-connect + `/redis-channel-status` (v0.4.12)

Second slice of Phase 2.5. Together with the v0.4.13 wrapper script (next), this makes redis-channel sessions startable from outside the terminal — needed for Phase 5 (Mimir spawning CC sessions on demand) but also a UX win for humans who don't want to type `/redis-channel-connect` on every session start.

**Auto-connect at MCP server startup.** When the MCP server boots with `CLAUDE_CHANNEL_AUTO_CONNECT=1` in its environment, the server eagerly registers presence + creates the inbound consumer group, then defers starting the consumer thread until the first MCP tool dispatch (when a live MCP Context is available to build the AsyncNotifier from). Because the consumer group is created at `id="$"` BEFORE presence publishes, XREADGROUP `>` on first tool dispatch picks up every message XADD'd in the gap — no silent drop.

- Gate is strict: only the literal value `"1"` enables. `"0"`, `"true"`, empty, unset — all off. Avoids accidental enable from a leaky shell env.
- Endpoint resolution: `CLAUDE_CHANNEL_ENDPOINT` env var if set, else `registry.defaults.auto_connect_endpoint` (added in v0.4.11). Both unset → log warning + continue running so the user can still `/redis-channel-connect` manually.
- Failure modes (registry missing, endpoint not configured, Redis unreachable) → log + continue. The MCP server never crashes on auto-connect failure.

Refactored `ServerState.connect()` to share code with the new `startup_register()` / `ensure_consumer_attached()` pair: `connect()` now does eager-register + immediate consumer-attach in one call; `startup_register()` only does the eager part (the deferred path); existing `connect()` tests still pass unchanged.

Tool handlers for `list`, `reply`, and the new `status` (below) gained a `ctx: Context | None = None` parameter and call `_STATE.ensure_consumer_attached(_build_async_notifier(ctx))` at entry — so the FIRST tool call after auto-connect lazily attaches the consumer thread + AsyncNotifier.

**`/redis-channel-status` slash command.** New MCP tool `redis_channel_status` reports current session state: `{connected, session_name, endpoint, host, uptime_seconds, consumer_attached, pending_inbound}`. New `commands/redis-channel-status.md` formats the response for terminal users. Useful for humans asking "am I still connected?" and as a programmatic probe (though the canonical readiness signal for external callers stays the `cc-sessions:hb:<name>` Redis key check).

Tests: 7 new for auto-connect paths (strict gate, env-vs-registry endpoint, failure modes); 3 new for status command. 165 redis-channel tests total, all pass; ruff clean.

### Changed — router-agnostic refactor + registry resolves default endpoint (v0.4.11)

First slice of Phase 2.5 (the convenience + programmatic-launch foundation). Two coupled changes:

**Router-agnosticism audit.** The plugin is documented as "router-agnostic by design" (any consumer that speaks the protocol can drive it), but the codebase leaked router-specific names into descriptions, defaults, and examples. Audited and genericized:

- `server/registry.py` module docstring: "Hermes profile: mimir, freya" → router-agnostic framing.
- `server/protocol.py` module docstring: "Both this repo and `hermes-claude-code-router`" → "any router implementation".
- `server/channel.py` MCP `instructions=` text: "a router (e.g. hermes-claude-code-router)" → "any router that speaks the protocol".
- `server/channel.py` `redis_channel_connect` tool description: "(typically a Hermes profile like 'mimir')" → "a configured router target from your registry". Tool default `endpoint: str = "mimir"` → `endpoint: str | None = None` (resolves via registry).
- `docs/registry.example.json`: `mimir` endpoint with `HERMES_REDIS_PASSWORD` → `default` endpoint with `MY_REDIS_PASSWORD` placeholder.
- `.mcp.json` launcher: hardcoded `export HERMES_REDIS_PASSWORD=$(get-redis-password.sh)` → sources `~/.claude/channels/redis-channel/source-env.sh` for whatever env vars the deployment needs. `docs/source-env.example.sh` provides a template.
- `README.md`, `skills/redis-channel/SKILL.md`, `commands/redis-channel-mode.md`, `commands/redis-channel-connect.md` description copy generalized; hermes-claude-code-router downgraded from "the reference router" to "one reference router implementation".
- `plugin.json` description + keywords: dropped `hermes` keyword; description reflects router-agnosticism.

**Kept** (intentional, contextual mentions of the reference router as a worked example): PROTOCOL.md, docs/STATE_MACHINE.md, CHANGELOG.md historical entries, README's "Related" link.

**Registry: `default_endpoint` + `auto_connect_endpoint` fields.** New `Defaults` fields support endpoint resolution without baking a router name into the plugin:

- `default_endpoint: str = "default"` — what `/redis-channel-connect` (no args) resolves to. Falls back to single-endpoint convenience when the named endpoint isn't configured but exactly one endpoint exists (covers solo-router setups where users just configure their one router without setting `default_endpoint`).
- `auto_connect_endpoint: str | None = None` — endpoint name to use for env-var-driven MCP-startup auto-connect (lands in v0.5.0 with the `CLAUDE_CHANNEL_AUTO_CONNECT=1` gate).

`Registry.resolve_default_endpoint()` is the canonical resolver. Existing single-endpoint registries Just Work via the convenience fallback; multi-endpoint registries get a clear error message listing the configured names.

**Soft-breaking migration for `.mcp.json`:** the launcher no longer hardcodes `HERMES_REDIS_PASSWORD`. Existing deployments need to rename their `~/.claude/channels/redis-channel/get-redis-password.sh` script to `source-env.sh` and change it from `echo "$pwd"` to `export <VAR>="$pwd"` (where `<VAR>` matches the registry's `redis_password_env` field). See `docs/source-env.example.sh` for the new template.

Tests: 14 → 18 registry tests (4 new for default/auto-connect endpoint resolution); 155 redis-channel tests total, all pass. ruff clean.

### Fixed — move runtime coaching into MCP server `instructions=` field (v0.4.10)

Major finding: the `agents/redis-channel-coach.md` file is a Claude Code **subagent definition**, not an auto-loaded context document. Subagents are invoked via the `Agent` tool — they are NOT automatically loaded into Claude's active context. So during notification-triggered turns (where no Agent invocation happens), Claude **never read our coach**.

This explains why v0.4.5 / v0.4.7 / v0.4.9 coaching iterations produced no observable behavior change — Claude wasn't reading the file. We were tuning inert text.

Comparison: the official `claude-plugins-official/discord` plugin has **no `agents/` directory at all** — all its instructional content ("The sender reads Discord, not this session. Anything you want them to see must go through the reply tool — your transcript output never reaches their chat.") lives in the MCP server's `instructions=` field. Claude Code injects that field into the system prompt automatically whenever the server is connected.

Our `instructions=` previously held 4 lines of generic blurb (no behavior coaching). v0.4.10 moves the coaching content from `agents/redis-channel-coach.md` into `instructions=` in `server/channel.py::build_app`:

- Tag-format reference (channel notification shape, attributes).
- "Two users in this conversation" framing (local terminal user sees assistant text; channel user sees `reply()`'s text arg; both want the answer; write it in both surfaces).
- Source-mode formatting table (voice → speakable prose; dm/channel/thread → markdown).
- AskUserQuestion ban.

The agent file is slimmed to a 14-line pointer doc explaining the new layout — kept around in case `agents/` is required by Claude Code plugin discovery, and as a place to document why coaching lives in `instructions=` now.

This is the most plausible fix we've had so far for the missing-text_block issue. If it still doesn't restore text_block emission, then the gap really is structural — Claude treats notification-triggered turns differently from user-message-triggered turns regardless of coaching — and we accept + move to Phase 3.

### Changed — coach reframes channel as two-user conversation, drops anti-narration list (v0.4.9)

Cheap diagnostic confirmed the previous theory: Claude itself self-reported `"no text block, only tool call"` when asked to repeat its prior turn's assistant text. The "Yes — text block is back" outbound text from v0.4.8 testing was Claude pattern-matching the question, not reporting actual output. Streaming-write debug log activity (1929 writes during a 1.4s window) was just terminal overhead — cursor, scroll, "Brewed for Xs" line — not real content.

This is a **model emission problem, not a UI rendering problem**. No amount of UI investigation helps. Coaching is the only lever.

Jeff caught the actual confound: the v0.4.7 coach had a "what `text` is for" anti-list explicitly banning "tool-call narration", "terminal-only commentary", "status updates the developer already saw" in the `text` arg. Claude appears to be over-generalizing those bans to the text_block too, since the MANDATORY rule required byte-identical content. Result: Claude's "don't narrate tool calls" prior wins, no text_block emitted.

v0.4.9 reframes the model:

- Removed the "what `text` is for" anti-narration list entirely.
- Removed the MANDATORY skeleton + anti-pattern list.
- Replaced with a "two users in this conversation" framing: a local terminal user (sees assistant text) and a channel user (sees `reply()`'s text arg). Two separate audiences, neither sees the other's surface. Writing assistant text is NOT narration — it's the answer for one audience; the reply tool is the answer for the other.

The hypothesis is that "I have two real users to serve, each with their own surface" overrides the "don't narrate" pattern more cleanly than MANDATORY framing. Whether it works empirically is the open question.

If v0.4.9 still doesn't produce reliable text_block emission, the conclusion is: Claude's training pattern around tool calls in MCP contexts is too strong to override via coaching, and the UX gap is structural. We accept and move to Phase 3.

### Changed — `reply` tool success result drops the TextContent echo (v0.4.8)

v0.4.7's coach tightening did not improve text_block emission alongside the `reply` tool call. Round-2 testing isolated that even when `reply` schema is already loaded (no ToolSearch in the assistant turn), Claude still drops the text_block. So deferred-vs-eager isn't the cause.

New working hypothesis: the v0.4.4 echo (returning `CallToolResult(content=[TextContent(text=text)], ...)`) signals to Claude that "the text was delivered as user-visible content from the tool" — making a redundant text_block feel wrong from Claude's POV. Even though Claude Code's renderer doesn't actually show MCP `TextContent` (`[ERROR] Tool ... not found in render-time tools`), Claude's training pattern of "tool result containing the answer means no text_block needed" appears to win.

Investigation via the claude-code-guide subagent confirmed: MCP spec is silent on rendering semantics ("implementations are free to expose tools through any interface pattern that suits their needs"), and Claude Code changelog has zero mentions of MCP result content rendering in 2025-2026. There is no documented mechanism to force text_block emission alongside a tool_use.

This release removes the TextContent echo from the success path:

```python
# before (v0.4.4 - v0.4.7):
return CallToolResult(content=[TextContent(text=text)], structuredContent=result)

# after (v0.4.8):
return CallToolResult(content=[], structuredContent=result)
```

Error path keeps TextContent (Claude must be able to read why the tool failed). Programmatic clients (integ_test.py + Hermes router) read `structuredContent.msg_id` and `structuredContent.ok` — both unaffected. No tests assert on the echo so no test changes needed.

If this still doesn't restore text_block emission reliably, the conclusion is: Claude Code's design intentionally skips MCP result rendering, the gap is structural, and best-effort coaching is the only available lever. We document the limitation and stop fighting it — for Phase 3 (voice routing) this UX gap is moot because TTS speaks the answer to the channel-side user.

### Changed — coach upgrades the two-places rule from soft guidance to mandatory output shape (v0.4.7)

v0.4.5 introduced the "write the same answer in two places" coaching, but live testing of v0.4.6 caught Claude occasionally emitting just the `reply` tool call with no preceding text block. The terminal then shows only `Called plugin:redis-channel:redis-channel` — the human has to expand the tool call or scroll back through `/resume` history to read what was sent. The functional pipeline (Hermes/Discord/voice) is unaffected because the outbound stream still gets the correct `text` argument, but the local-terminal UX takes a hit.

The protocol limitation is real: Claude Code's render pipeline does not surface MCP tool result content as chat (`Tool … not found in render-time tools`), and there is no notification channel that renders outbound replies. The only mechanism that puts text on the local terminal is a text block in the assistant turn — and whether Claude emits that text block alongside the tool call is inference-variant.

Coach is tightened from "write the same answer in two places" (soft) to a MANDATORY output shape with a concrete skeleton:

```
<your one answer to the user, as a plain text block>
<tool_use: reply(chat_id=…, text=<that same answer, byte-identical>, …)>
```

Plus an explicit anti-pattern list: tool call alone, text+tool with different wording, narration ("Sent reply…"), and chain-of-thought in the text. This is best-effort — coaching reduces but does not eliminate inference variance. The deterministic fix (server-side echo notification) was considered and rejected: it would double-render every reply on the local terminal, costing tokens and confusing the merged-chat illusion. Document the imperfection; accept that hands-off review may occasionally require expanding a tool call.

Files: `agents/redis-channel-coach.md`. No code or test changes.

### Fixed — per-session stream cleanup on disconnect + lazy GC (v0.4.6)

Live audit of olympus-bus Redis caught that we were leaking stream keys: every disconnected session left `cc-sessions:<name>:inbound` and `cc-sessions:<name>:outbound` behind forever. Eight orphan stream keys accumulated in one afternoon of testing.

Fix in two layers:

1. **Graceful disconnect** (`Presence.stop`) now DELs the inbound + outbound stream keys alongside the existing `HDEL cc-sessions:registry` + `DEL cc-sessions:hb:<name>`. Reflects the "this session is done" intent. Stream history is not preserved across disconnects — if you need durable transcripts, the router should snapshot them.
2. **Lazy GC on stale entries** (`list_live_sessions(gc_stale=True)`) now extends its sweep to also DEL the streams of any registry entry whose hb key has expired. Catches ungraceful crash paths (process killed mid-session) that bypass graceful disconnect.

New helper `presence.session_stream_keys(session_name)` enumerates all per-session keys (inbound, outbound, hb) so both code paths share one source of truth for what belongs to a session.

Tests: 4 new (`test_presence_stop_drops_session_streams`, `test_session_stream_keys_layout`, `test_list_live_sessions_gc_drops_stale_streams`, `test_list_live_sessions_no_gc_when_disabled`). Repo total: 418 tests pass.

### Changed — coach asks Claude to write the reply text twice: terminal + tool (v0.4.5)

Live testing of v0.4.4 surfaced that **Claude Code does not render MCP tool result text content as visible chat output** — even when the tool returns `CallToolResult(content=[TextContent(text="…")])`. The debug log confirms:
```
[ERROR] Tool mcp__plugin_redis-channel_redis-channel__reply not found in render-time tools
```
This is internal to Claude Code's render pipeline, not something we can change from the plugin side. The v0.4.4 tool-echo approach still works for programmatic clients (the integration test still parses the structured result correctly), but it doesn't surface anything to the human reading the terminal.

So the coach is updated to ask Claude to write the reply text **in two places**:

1. As the natural conversational response in the terminal turn — this is what the local user sees as the chat history.
2. As the `text` argument to the `reply` tool — this is what the channel-side user reads (or hears via TTS).

Both contain the **same words**. Composed once, rendered in both surfaces. No "I responded with…" wrappers, no double-typing of the same content in different forms. Just compose your answer naturally; output it as your turn text; call `reply` with that text.

This is the closest channels can get to Remote-Control-style chat-merging without the framework's render-time pipeline doing more for us.

The v0.4.4 `CallToolResult` machinery stays in place — useful for programmatic clients and harmless when Claude Code chooses not to render it.

### Changed — `reply` tool echoes sent text as natural MCP result content (v0.4.4)

The reply tool's MCP wrapper now returns a `CallToolResult` with the sent `text` as the unstructured `content` element + the existing `{ok, session_name, chat_id, msg_id}` as `structuredContent`. The result: the terminal automatically renders the reply text as the tool's natural output — no model-side narration ("Reply sent on the outbound stream…", "I responded with…") needed to make the back-and-forth visible.

This closes the outbound-visibility gap toward the user's stated goal of "channels should feel like Remote Control" — both sides of the chat now render in terminal without meta-decoration.

The agent coach was rewritten with **per-source-mode formatting guidance**, because voice and text sources need fundamentally different reply shapes:

| `source`              | `voice` arg | Formatting rules for `text`                                                                                          |
| --------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------- |
| `voice`               | `true`      | TTS will SPEAK aloud. Short. No markdown, no code blocks, no bare URLs. Speakable prose only. No visual references.  |
| `dm`                  | `false`     | Direct message. Full markdown, code blocks, lists, links all render properly.                                        |
| `channel`             | `false`     | Public channel. Same formatting as DM. Use `in_reply_to` to thread.                                                  |
| `thread`              | `false`     | Threaded reply. Same formatting as DM/channel.                                                                       |
| *(any other / unset)* | `false`     | Default to DM-style for forward-compatibility with future sources (email, SMS, alerts, etc.).                        |

Also:
- Removed the `debug=false/true` narration toggle (the tool's natural echo replaces it).
- Kept the TTS-safety reminder explicit: when `voice=true`, the `text` arg is what gets SPOKEN aloud — Claude must not put tool-call narration, reasoning, or terminal-only commentary into `text`.
- Added explicit "what `text` is for" section: it's the user-facing message body, full stop.
- The `debug` flag stays on the connect tool for future opt-in dev verbosity but currently has no effect.

`ServerState.reply` itself still returns a dict (unchanged) — only the MCP-tool-wrapper layer in `build_app()` was modified. Existing unit tests pass without changes.

### Added — `debug` flag on `/redis-channel-connect` controls reply narration (v0.4.3)

Live testing surfaced that Claude narrates "Reply sent on the outbound stream — msg_id=…" in the terminal after calling the `reply` tool. That's noise when the recipient is on the channel side (Discord/voice) and only the developer is watching the terminal.

`redis_channel_connect` now accepts a `debug: bool = False` arg. Honored as follows:
- **`debug=false` (default)**: quiet mode — coach + slash-command markdown tell Claude *not* to narrate replies in the terminal; the reply tool's structured result is the only confirmation.
- **`debug=true`**: verbose mode — Claude is invited to print a one-line `→ replied to <chat_id> · msg_id=<x>` after each `reply`. For developers running live integration tests.

CLI usage: `/redis-channel-connect mimir --debug` for verbose, plain `/redis-channel-connect mimir` for quiet.

The flag is stored on `ServerState`, returned in the connect response (so the coach can key off it), and reset to `false` on disconnect.

### Fixed — channel notifications now use the correct {content, meta} schema + declare `claude/channel` capability + cd to plugin root (v0.4.2)

Live install testing surfaced **three** issues that together prevented Claude Code from actually surfacing channel events end-to-end:

**1. MCP server didn't declare `claude/channel` capability.** Claude Code's launcher reads `initialize`'s `capabilities.experimental['claude/channel']` to decide whether to register a listener for channel notifications. FastMCP's `Server` doesn't expose a constructor knob for `experimental_capabilities`, so we monkey-patch `app._mcp_server.create_initialization_options` in `channel.py:_enable_channel_capability` to inject `{"claude/channel": {}}`. Without this, claude logs `"Channel notifications skipped: server did not declare claude/channel capability"` and silently drops every event.

**2. Notification params were the wrong shape.** Claude Code's [channels reference](https://code.claude.com/docs/en/channels-reference) requires `params: {content: str, meta: dict[str,str]}` — `content` becomes the body of a `<channel source="..." attr="val">…</channel>` tag in Claude's context, each `meta` key (identifiers only, no hyphens) becomes a tag attribute. We were passing the raw Inbound payload (`{v, router, source, chat_id, text, ...}`) as params, which Claude Code can't render. New `notifier.inbound_to_channel_params()` translates at the emission boundary: `content` = `text`, `meta` = the other fields stringified and filtered to identifier-safe keys. Wire format on Redis stays unchanged; only the in-process MCP frame is reshaped.

**3. `cwd: ${CLAUDE_PLUGIN_ROOT}` wasn't being honored by Claude Code's MCP launcher.** The wrapper inherited claude's cwd, so `python3 -m server` couldn't find the `server` package (error: `No module named server`). Fixed by adding `cd "$CLAUDE_PLUGIN_ROOT" || exit 1;` at the start of the shell wrapper.

**Agent coach rewrite.** `agents/redis-channel-coach.md` now describes the actual `<channel source="..." chat_id="..." …>body</channel>` tag format Claude sees in context, with concrete instructions for reading attributes and constructing replies.

**Tests:** 8 new tests in `test_redis_channel_notifier.py` covering the translation (text-only, full payload, None values dropped, nested values dropped, non-identifier keys dropped, numeric/bool stringification, missing-text fallback). Existing channel tests updated to assert the new shape. Repo total: 412 tests pass.

**Heads-up for users**: during the channels research preview, custom plugins like this one are NOT on Anthropic's approved channel allowlist. You must launch claude with `--dangerously-load-development-channels plugin:redis-channel@infiquetra-plugins` (and acknowledge the confirmation prompt) for the channel events to register. After v1 ships and Anthropic accepts the plugin onto the official allowlist, this flag becomes unnecessary.

### Changed — `.mcp.json` runs server under `uv run` + auto-sources password (v0.4.1)

Two reliability fixes to the shipped `.mcp.json` so the MCP server boots correctly out of the box:

**1. Use `uv run` with inline deps instead of bare `python`.** The previous `command: python` failed in Claude Code's MCP-spawn shell because `python` is rarely on the minimal default PATH on macOS (only `python3` is, via homebrew). Even when `python3` resolves, system Python doesn't have `mcp`/`redis`/`pydantic` installed. The new command is:

```
uv run --quiet --with "mcp>=1.0" --with "redis>=5.0" --with "pydantic>=2.5" python3 -m server
```

`uv` is reliably on PATH (homebrew default), it manages a per-spec cached env, and the `--with` flags ensure deps resolve at first launch — no pre-`pip install` step required. Subsequent launches use the cached env (~50ms cold-start overhead acceptable for a long-lived MCP server).

**2. Auto-source HERMES_REDIS_PASSWORD from the keychain helper.** The wrapper script now does:

1. If `HERMES_REDIS_PASSWORD` is already in env (you launched claude with it set) → use that value, helper not invoked.
2. Otherwise, if `~/.claude/channels/redis-channel/get-redis-password.sh` exists and is executable → source the value from it.
3. Otherwise (no env, no helper) → falls through to `uv run python3 -m server`, and the existing structured "endpoint X requires password env var Y but it is unset or empty" error fires at connect time with a clear message.

**Together, these mean** `/reload-plugins` is now the only thing needed to get a freshly-installed plugin connected to Redis, instead of "exit claude, set env, run pip install, relaunch claude".

**Requirements** on the host: `uv` installed (homebrew or astral installer) + the keychain helper script in place (which the user creates once as part of capturing the Redis password — see README).

### Added — same-cwd disambiguation + git_branch auto-detection

- `presence.detect_git_branch(cwd)`: runs `git rev-parse --abbrev-ref HEAD` with a 1s subprocess timeout. Returns `None` for non-git dirs / missing cwds / detached HEAD / git not installed / any subprocess failure. `build_metadata` calls it automatically when `git_branch` is unset, so live session metadata in `cc-sessions:registry` now carries the branch — useful for natural-language session routing later.
- `presence.disambiguate_if_collision(client, base_name, host, pid)`: prevents two CC sessions in the same cwd (which auto-name identically because the name's hash is `sha256(cwd + host)[:8]`) from clobbering each other in Redis. On collision with a live presence owned by a different PID on the same host, appends `-<pid_hex_4>` to the auto-name. Same-PID collision (reconnect) keeps the base name. Stale-entry (hb expired) and corrupt-entry cases pass through cleanly. Only applies when no explicit session_name was passed — user-supplied names are honored as intent and use regular replace semantics.
- `channel.py:connect` wires disambiguation into the auto-name path.
- Tests: 8 new presence cases (no-collision, same-PID, different-PID, different-host, short-PID zero-padding, stale, half-state, corrupt) + 2 channel cases (auto-name disambiguates on collision; explicit name does NOT).

### Added — Phase 2 (text bridge: inbound consumer + reply tool)

- `server/redis_consumer.py`: XREADGROUP consumer thread for `cc-sessions:<name>:inbound`. Creates the consumer group on first connect (idempotent on BUSYGROUP). Each decoded payload is handed to a caller-supplied `on_message` callback. Acks after the callback returns; a raising callback leaves the message in the pending entries list for re-delivery. Drops + acks structurally bad payloads (missing `payload` field, undecodable JSON, non-object body) so the consumer never loops on garbage. The original Redis message-id is attached as `_msg_id` for reply correlation.
- `server/redis_producer.py`: `publish_outbound()` XADDs a sorted-key JSON-encoded payload onto `cc-sessions:<name>:outbound` with `MAXLEN ~ 10_000` to bound stream growth.
- `server/notifier.py`: bridges the consumer thread → async `session.send_notification`. `AsyncNotifier` captures the asyncio loop + ServerSession at connect time; `emit()` (called from the consumer thread) builds a `Notification[dict, str]` (`method="notifications/claude/channel"`, `params=payload`) and schedules `send_notification` via `asyncio.run_coroutine_threadsafe`. Cleanly drops payloads if the loop is closed (no coroutine leak). `RecordingNotifier` + `NoopNotifier` are the test/no-op seams.
- `server/channel.py`: connect now also starts the consumer with the wired notifier; disconnect stops the consumer first (so it doesn't try to ack on a stale client). New `reply(chat_id, text, voice=False, in_reply_to=None)` MCP tool that XADDs an Outbound payload. Server-side guards: `chat_id` and `text` must be non-empty/non-whitespace.
- Tests: 30 new unit tests across `test_redis_channel_consumer.py` (11), `test_redis_channel_producer.py` (4), `test_redis_channel_notifier.py` (6), plus 9 additional `test_redis_channel_channel.py` cases covering consumer attachment, second-connect replaces consumer, reply XADD + voice/in_reply_to propagation, reply-when-disconnected, and empty-text/empty-chat_id rejection.

### Added — Phase 1 (presence + heartbeat + slash list)

- `server/session_id.py`: auto-generate session names from cwd + host hash (`<slug>-<8hex>`), with `CLAUDE_SESSION_NAME` env override and slug validation.
- `server/registry.py`: loads endpoint config from `~/.claude/channels/redis-channel/registry.json`; clean error types for missing/parse/unknown-endpoint cases.
- `server/redis_client.py`: Redis connection helper with password-env injection that fails loud if the configured env var is unset.
- `server/presence.py`: registry HSET + 10s heartbeat thread (TTL 60s by default) + lifecycle pub/sub events (`registered`, `unregistered`); supports context-manager use; tolerates transient errors without exiting the thread; lazy stale-entry GC on `list_live_sessions`.
- `server/channel.py`: FastMCP stdio server exposing `redis_channel_connect`, `redis_channel_disconnect`, `redis_channel_list` tools. Single-active-session state with lock; second connect replaces first; atexit + SIGTERM/SIGINT cleanup.
- `.mcp.json` manifest so Claude Code auto-launches the server.
- `docs/registry.example.json` reference config.
- Slash commands `connect`/`disconnect`/`list` rewritten to instruct Claude to invoke the matching MCP tools and interpret results.
- Tests: 57 new unit tests across `test_redis_channel_session_id.py` (12), `test_redis_channel_registry.py` (9), `test_redis_channel_presence.py` (16), `test_redis_channel_channel.py` (15). fakeredis-backed; heartbeat refresh verified with sub-TTL beat.

### Added — Phase 0 (scaffold)

- Directory layout, plugin manifest, README, CHANGELOG.
- `PROTOCOL.md` canonical wire-format spec for redis-channel ↔ router.
- `docs/STATE_MACHINE.md` routing-target state machine spec (router-side).
- `server/protocol.py` pydantic models + `is_destructive` classifier.
- `tests/test_protocol.py` covering all protocol models.
- Agent coach `agents/redis-channel-coach.md`, skill `skills/redis-channel/SKILL.md`, slash command stubs.

### Not implemented yet (planned for later phases)

- Voice routing (Phase 3).
- Permission relay + AskUserQuestion interception + audit logging (Phase 4).
- Hybrid intelligence — LLM tools for session-routing fallback (Phase 5; router-side).
