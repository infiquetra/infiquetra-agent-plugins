# Voice portable package

Portable Agent Plugins 1.0 package giving one explicitly bound, Herdr-managed
Claude Code session a spoken conversational loop. The bound session speaks its
completed response — after Markdown cleanup, with fenced code-block contents
omitted — the operator toggles recording in the Voice pane and speaks,
toggles again, a declared speech-to-text provider transcribes, and the text
returns to that same session's input box, unsubmitted and editable. One
session at a time, both directions, no arbitration anywhere. The package
never installs, provisions, discovers, or substitutes a provider: providers
are declared by the operator, preflighted, and reported.

"Herdr" here is the current Herdr: herdr core (`hc`), which runs the bound
session's terminal, and the Herdr app, the window that shows it. Old Herdr
(`herdr agent`, `herdr pane`, `HERDR_PANE_ID`, `~/.config/herdr/config.toml`)
is retired and voice no longer uses it; see
[How voice uses herdr core](#how-voice-uses-herdr-core).

The requirements behind this package are
[docs/brainstorms/2026-08-25-voice-plugin-requirements.md](../../docs/brainstorms/2026-08-25-voice-plugin-requirements.md);
the run-wide implementation plan is
[docs/plans/2026-08-25-voice-plugin-implementation-plan.md](../../docs/plans/2026-08-25-voice-plugin-implementation-plan.md).

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins 1.0 manifest — the portable, vendor-neutral one |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude Code packaging manifest. A different specification, required by the Claude CLI to sit at the installed package root. Holds no behaviour: it declares the hooks and MCP server paths into `com.infiquetra.claude/` and the portable skills directory |
| [`scripts/providers.py`](scripts/providers.py) | Provider declaration contract: closed egress set, declarations, named refusals |
| [`scripts/settings.py`](scripts/settings.py) | The one settings reader: stated names, split defaults, absent never means empty |
| [`scripts/process.py`](scripts/process.py) | Subprocess discipline: closed stdin and a deadline on every child |
| [`scripts/text_cleanup.py`](scripts/text_cleanup.py) | Markdown cleanup for the speak path: formatting syntax stripped, fenced code blocks omitted |
| [`scripts/speak.py`](scripts/speak.py) | Speak path: synthesize and play one completed response through the declared `voice-forge` provider |
| [`scripts/record.py`](scripts/record.py) | Capture path: toggled recording tracked in state; nothing transcribed or kept without an explicit stop |
| [`scripts/transcribe.py`](scripts/transcribe.py) | Transcription path through the declared Hermes relay: session token in process memory only, nothing kept |
| [`scripts/binding.py`](scripts/binding.py) | Sticky single-agent binding store: one explicit bind to a herdr core terminal, replaced only by an explicit rebind |
| [`scripts/deliver.py`](scripts/deliver.py) | Delivery path: transcript typed into the bound agent's input box with `hc keys`, unsubmitted, or a named audible refusal that holds it |
| [`scripts/preflight.py`](scripts/preflight.py) | Preflight the declared providers, the stop keybinding, and the executables; report by name, never install or repair |
| [`scripts/pane.py`](scripts/pane.py) | The Voice pane: the one long-running operator surface and listen-path sequencer |
| [`scripts/voice_cli.py`](scripts/voice_cli.py) | The one command surface: `pane`, `bind`, `preflight`, `toggle`, `stop`, `policy` |
| [`scripts/bridge_client.py`](scripts/bridge_client.py) | Bridge client for Auralis loopback HTTP bridge: discovery, presence, and rendering submission |
| [`scripts/herdr_core.py`](scripts/herdr_core.py) | The one place voice runs `hc`: read a terminal, label it with its Claude session, type into it |
| [`scripts/adapter_identity.py`](scripts/adapter_identity.py) | Three-part adapter identity resolver (`agent_session_id`, `pane_id`, `terminal_id`), from herdr core |
| [`scripts/rendering_gate.py`](scripts/rendering_gate.py) | Plain-spoken-text rendering gate: rejects Markdown/fences with named reasons (R121, R20) |
| [`scripts/voice_policy.py`](scripts/voice_policy.py) | Voice policy and preferences store: renders instructions, consumes Brief Next Turn override (R25, R107) |
| [`scripts/turn_record.py`](scripts/turn_record.py) | Current turn record store: locked read-apply-write transactions (`fcntl.flock`) for turn state (KTD11) |
| [`scripts/mcp_server.py`](scripts/mcp_server.py) | Model Context Protocol (MCP) stdio server: `submit_spoken_rendering` tool and presence renewal loop (R21, KTD2, KTD8) |
| [`skills/voice/`](skills/voice/SKILL.md) | Agent Skill: documents the CLI and the in-pane keys; adds no second command surface |
| [`tests/`](tests/) | `unittest` suites for the scripts above, the hooks, and the skill entrypoint; `conftest.py` keeps every test away from the developer's real herdr core |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude client extension directory: manifest, hook descriptor, MCP server declaration, and hooks (SessionStart, UserPromptSubmit, PreToolUse, Stop) |

Claude-specific files — hooks and the client extension — never live in this
portable core; they belong under the `com.infiquetra.claude/` client
extension directory.

## Installing into Claude Code

The repository is a Claude marketplace. From a checkout:

```bash
claude plugin marketplace add /path/to/infiquetra-agent-plugins
claude plugin install voice@infiquetra-agent-plugins
```

Claude installs the **package root** — this directory — so the portable core
travels with the client extension. That is required rather than tidy: the Stop
hook imports the core and spawns [`scripts/speak.py`](scripts/speak.py) from
it, so an install carrying only `com.infiquetra.claude/` would validate, then
fail at the first spoken response. The reasoning and the rejected alternatives
are recorded in
[`docs/engineering-journal/DECISIONS.md`](../../docs/engineering-journal/DECISIONS.md).

Installing does not configure anything. Both providers are still declared by
the operator, and `voice preflight` still has to pass before the loop runs —
see [Settings](#settings) and
[The Herdr-wide stop keybinding](#the-herdr-wide-stop-keybinding).

Restart Claude Code after installing: the hooks are registered at session
start, and the SessionStart hook has to run once in a session before
`voice bind` can find it (see
[How voice uses herdr core](#how-voice-uses-herdr-core)).

## Providers are declared, never discovered

Voice ships no provider implementations. Each provider is declared with its
invocation or endpoint, its capabilities, its egress class, and the *name* of
any credential environment variable it needs — never a value. Version one
declares exactly two providers, built in code from the stated settings:

| Provider | Role | Egress class | Credential variable |
|---|---|---|---|
| `voice-forge` | text-to-speech | `local-network` | none declared |
| `hermes-xai` | speech-to-text | `named-remote-service` | none declared |

Neither provider declares a credential variable: the speech-to-text route's
upstream credential is owned by the Hermes relay, and the relay's loopback
session token is a transport detail held in process memory only — it is never
stated, persisted, or logged.

The egress class is a stated value from a closed set of exactly four
literals: `on-device`, `local-network`, `named-remote-service`, and
`unofficial-remote-endpoint`. Anything else is rejected. "External" is not a
fifth value: it is the predicate over the set that is true for
`named-remote-service` and `unofficial-remote-endpoint` and false for the
other two, which is the distinction Voice must draw between audio that
leaves the machine and audio that stays on the local network.

A provider that is unavailable produces a named refusal carrying the provider
name and the missing prerequisite. Voice never substitutes one provider for
another, and never falls back.

## Settings

All configuration is stated through the environment and read by
[`scripts/settings.py`](scripts/settings.py) alone. Absent is never treated
as empty: a setting that is present but empty is refused by name rather than
silently defaulted. No setting carries a secret; every value below is
non-sensitive.

| Setting | Default | Meaning |
|---|---|---|
| `VOICE_FORGE_BASE_URL` | none — refused by name when unset | Base URL of the Voice Forge text-to-speech service, from the operator's deployment |
| `VOICE_FORGE_VOICE_ID` | none — refused by name when unset | Voice the synthesis uses |
| `VOICE_HERMES_BASE_URL` | `http://127.0.0.1:8765` | Base URL of the Hermes relay |
| `VOICE_HERMES_PROFILE` | `mimir-engineer` | Hermes profile the speech-to-text route resolves through |
| `VOICE_CAPTURE_BIN` | `/opt/homebrew/bin/ffmpeg` | Capture executable, supplied by the operator, never discovered |
| `VOICE_PLAYBACK_BIN` | `/usr/bin/afplay` | Playback executable, supplied by the operator, never discovered |
| `VOICE_STATE_DIR` | `~/.local/state/voice` | Machine-local runtime state directory |
| `VOICE_RETENTION` | none — must be stated | Retention posture; version one accepts exactly `ephemeral` |
| `HC_TERMINAL_ID` | none — refused by name when unset | This session's herdr core terminal address (`t21`). herdr core sets it in every terminal; voice reads it for the Auralis bridge identity and the SessionStart label |
| `VOICE_HC_BIN` | `hc` | The herdr core command voice runs for `get`, `label` and `keys` |

Retention behaviour is a stated setting rather than a silent default: the
empty case — audio deleted after success and failure, no transcript log, no
telemetry — is something a person wrote down as
`VOICE_RETENTION=ephemeral`. Any other value is refused by name rather than
honoured.

## How voice uses herdr core

herdr core (`hc`) runs every terminal on its machine. Voice uses three of its
commands, all through [`scripts/herdr_core.py`](scripts/herdr_core.py), each
with standard input closed and a deadline:

| Command | Who runs it | What for |
|---|---|---|
| `hc label $HC_TERMINAL_ID voice.agent-session=<id>` | The SessionStart hook, in the Claude session | herdr core does not know which Claude session runs in a terminal. The hook records it on every start, resume, clear and compact |
| `hc get <terminal> --json` | `voice bind`, delivery, and the Auralis bridge identity | Read a terminal: its address, whether it is live, its status word (`idle`, `working`, `done`, `blocked`, `error`), and its labels |
| `hc keys <terminal> <key>...` | Delivery | Type the transcript one key per character (`space` for a space, `shift+<letter>` for a capital), never Enter |

`voice bind <terminal>` takes a terminal's name or address (`t7`). It refuses a
terminal on another machine (`mini/t3`): voice records and plays audio on this
machine, and the Stop hook reads this machine's binding. It refuses a finished
terminal, and one without the `voice.agent-session` label, which means the
voice plugin's SessionStart hook has not run there yet. The binding stores the
terminal's address, which herdr core never reuses.

Delivery never uses `hc send`, and nothing falls back to it: that command always
presses Enter, so a misheard transcript would be submitted to the agent. herdr
core has no command that pastes text without Enter, so delivery types with
`hc keys`, which takes key names, not text.

That limits what can be typed. A probe of herdr core 0.1.20 in an isolated core
(2026-11-10) found that `hc keys` types lowercase letters, digits and
`` . , ' - ; / = ` [ ] `` as themselves, `space` as a space, and `shift+a` as
`A`, while a bare `A` types `a` and `shift+/` types `/`, not `?`. It rejects
every other character, including `? ! " : ( ) @ # $ % & * + _ ~ ^ { } | < >` and
anything outside ASCII, and a rejected key fails the whole call before anything
is typed. So delivery maps only the characters known to type correctly. A
transcript with any other character, or one starting with `/` (which opens
Claude Code's command menu), is not typed at all: the refusal is spoken and the
transcript is held in the Voice pane, where `d` discards it (`u` would only
refuse it again). In practice every spoken question is held until herdr core
can paste text without Enter.

`hc keys` does not refuse a blocked program on its own, so delivery reads the
status first and refuses `blocked` itself; the race between that read and the
keys is the stated residual.

The Auralis bridge identity is the terminal's `voice.agent-session` label as
`agent_session_id`, and the terminal's address as both `terminal_id` and
`pane_id`. herdr core has no panes; panes belong to the Herdr app's window and
can move while the terminal keeps running. The identity is resolved only while
Auralis has published its bridge discovery file: the PreToolUse hook resolves
it on every tool call and the presence loop retries every second, so without
that check every Claude session would run `hc get` that often for nothing.

## The Herdr-wide stop keybinding

Voice preflights — and never writes — one operator-owned stop key that works
from anywhere in the Herdr app, not only while the Voice pane has focus.

### First, put `voice` on PATH

Claude installs a plugin under a *versioned* directory, and a version bump
creates a new one rather than reusing the old. There is no `current` or
`latest` symlink, so **no path inside an installed package is stable**, and a
keybinding written against one stops working at the next release without
announcing it: the key still exists, the command still parses, nothing runs.

So the binding invokes a small launcher that resolves the current install at
invocation time, from Claude's own plugin registry — which Claude rewrites on
every install and update. Write it once:

```bash
python3 ~/.claude/plugins/cache/infiquetra-agent-plugins/voice/*/com.infiquetra.claude/scripts/install_launcher.py
```

That writes `~/.local/bin/voice` and nothing else. It refuses to overwrite a
`voice` it did not generate unless you pass `--force`, and `--print` shows the
file without writing it. Confirm with `command -v voice`.

The launcher follows version bumps on its own; you never edit the keybinding
again.

### Then bind a key to a mod that runs it

The Herdr app's keys live in `~/.config/herdr-app/keys.json`. A key there can
run an app command, send text to the focused terminal (`send:`), or deliver a
command to a mod (`<mod>.<command>`); it cannot run a program directly. A
Herdr-wide stop key is therefore:

1. a mod in `~/.config/herdr-app/mods/<mod>/main.js` that waits on
   `nextCommand()` and, on its stop command, runs `exec("voice", ["stop"])`;
2. a key in `keys.json`, for example `"global": { "<your key>": "<mod>.stop" }`.

The Herdr app delivers a mod command only to copies of the mod that are shown
in the current layout, so the mod has to be placed in it. Check the mod with
`herdr-app check ~/.config/herdr-app/mods/<mod>` before relying on it; the
app's own guide (`~/.config/herdr-app/AGENTS.md`) documents mods. Voice ships
no such mod, and a `send:voice stop` key does not count: it types into
whichever terminal has focus.

Voice reports this key's absence by name; it never creates or repairs any
Herdr configuration.

### What preflight actually checks

Preflight follows each `<mod>.<command>` key in `keys.json` to that mod's
`main.js`, reads its literal `exec("program", ["arg", ...])` calls, and
resolves the one that names the stop path rather than pattern-matching it: it
confirms the program is on `PATH` (or is an existing executable file) and that
any `.py` script named beside it exists. An `exec` whose arguments are built at
run time cannot be resolved without running the mod, so it is not counted. It never *runs* the command — firing a
stop as a side effect of asking whether a stop is possible would be its own
defect.

This matters because containing the text `voice stop` and being able to stop
anything are different claims, and they came apart here: the binding was
documented before any `voice` existed on `PATH`. A probe that reported that as
healthy would have been worse than no probe, because it retires your own
suspicion.

## Auralis bridge adapter

The package also provides the Claude Code adapter for the Auralis V1
conversational loop (capability slice C3), specified in
[`docs/plans/2026-08-27-auralis-c3-adapter.md`](../../docs/plans/2026-08-27-auralis-c3-adapter.md).
Auralis Core (repository `infiquetra/auralis`) exposes a loopback HTTP bridge
governed by the six-route Auralis Bridge Contract v1 (`GET /v1/health`,
`PUT /v1/presence`, `DELETE /v1/presence`, `GET /v1/current`, `POST /v1/rendering`,
`POST /v1/approval`).

### Adapter architecture and lifecycle

1. **Long-lived MCP process ([`scripts/mcp_server.py`](scripts/mcp_server.py))**:
   The stdio Model Context Protocol (MCP) server declared in
   [`com.infiquetra.claude/mcp/servers.json`](com.infiquetra.claude/mcp/servers.json)
   persists for the Claude session. It runs a background presence thread that registers
   and renews presence (`PUT /v1/presence`) on the contract lease cadence and sends
   `DELETE /v1/presence` on clean shutdown (KTD2). It exposes the `submit_spoken_rendering`
   tool through which the agent submits its authored spoken rendering.
2. **Plain-spoken-text rendering gate ([`scripts/rendering_gate.py`](scripts/rendering_gate.py))**:
   Submissions are locally validated before reaching the wire (KTD1; R121, R20). Markdown
   formatting or fenced code blocks are rejected with named reasons (`fenced_code_block`,
   `markdown_formatting`) and never reformatted or cleaned. Accepted plain text is
   forwarded byte-identical to `POST /v1/rendering` using the prompt-time captured turn
   identifiers.
3. **Turn origin and policy injection ([`com.infiquetra.claude/hooks/user_prompt_submit_hook.py`](com.infiquetra.claude/hooks/user_prompt_submit_hook.py))**:
   At prompt submission, the hook queries `GET /v1/current`, matches adapter identity,
   captures `(binding_id, turn_id)` into [`scripts/turn_record.py`](scripts/turn_record.py),
   and injects explicit context telling the agent whether the turn originated via voice,
   that a spoken rendering is expected, and the operator's current voice policy instructions
   rendered by [`scripts/voice_policy.py`](scripts/voice_policy.py) (including any armed
   one-shot Brief Next Turn override, consumed on transmission; R106, R107).
4. **PreToolUse observation and approval forwarding ([`com.infiquetra.claude/hooks/pre_tool_use_hook.py`](com.infiquetra.claude/hooks/pre_tool_use_hook.py))**:
   Handles tool observation and spoken approval forwarding (KTD7; C8 Prerequisite 1):
   - First, records best-effort tool observations into the turn record if the active turn originated via Auralis.
   - Second, verifies active bridge binding coverage via `GET /v1/current`. If covered, forwards the approval request to `POST /v1/approval` and holds the connection open awaiting Core's decision (under a 60s hook / 55s client timeout budget exceeding Core's 50s hold deadline).
   - Third, validates Core's response: exact request identifier match, `decision: "allow"`, and complete canonical action snapshot match (`tool_use_id`, `tool_name`, canonical `tool_input`, `cwd`, and `classification.result == "voice_approvable"` with matching `permission_mode`). Emits `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}` only on exact match.
   - On every other path (Core deferral, snapshot mismatch, transport failure, timeout, or unbound session), defers silently with no stdout and exits 0 (fail-closed discipline).
5. **Completion reconciliation ([`com.infiquetra.claude/hooks/stop_hook.py`](com.infiquetra.claude/hooks/stop_hook.py))**:
   When the turn completes, the Stop hook reconciles the turn record: if wire-bound and an
   authored rendering was accepted, outcome is recorded as `authored`; if the voice turn
   completed without an accepted rendering, outcome is recorded as `fallback` (KTD6; R22,
   R23, R122). While wire-bound, the legacy local speak path is suppressed so Auralis retains
   sole speech custody.

## Subprocess discipline

Every subprocess Voice starts runs with its standard input explicitly closed
and a deadline attached. Bounded helper calls carry the caller's deadline; a
fully detached child runs in its own session with closed streams and carries
its deadlines internally, because its parent never waits for it. No
subprocess is ever started through a shell.

## Runtime floor

Standard-library Python at the repository floor `python>=3.12`, tested with
`unittest`. HTTP, where later units need it, uses `urllib.request`; the
package adds no third-party dependency.

## Provenance posture

This package is authored in this repository. It carries no
`PROVENANCE.json` and no port descriptor, because it has no upstream to pin
and no source repository whose bytes must be tracked. That is stated here
plainly rather than leaving the absence to carry the meaning. Version one
also ships no `CHANGELOG.md`: the git history carries the record until the
first external release.
