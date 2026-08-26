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

The requirements behind this package are
[docs/brainstorms/2026-08-25-voice-plugin-requirements.md](../../docs/brainstorms/2026-08-25-voice-plugin-requirements.md);
the run-wide implementation plan is
[docs/plans/2026-08-25-voice-plugin-implementation-plan.md](../../docs/plans/2026-08-25-voice-plugin-implementation-plan.md).

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins 1.0 manifest — the portable, vendor-neutral one |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude Code packaging manifest. A different specification, required by the Claude CLI to sit at the installed package root. Holds no behaviour: it declares the hooks path into `com.infiquetra.claude/` and the portable skills directory |
| [`scripts/providers.py`](scripts/providers.py) | Provider declaration contract: closed egress set, declarations, named refusals |
| [`scripts/settings.py`](scripts/settings.py) | The one settings reader: stated names, split defaults, absent never means empty |
| [`scripts/process.py`](scripts/process.py) | Subprocess discipline: closed stdin and a deadline on every child |
| [`scripts/text_cleanup.py`](scripts/text_cleanup.py) | Markdown cleanup for the speak path: formatting syntax stripped, fenced code blocks omitted |
| [`scripts/speak.py`](scripts/speak.py) | Speak path: synthesize and play one completed response through the declared `voice-forge` provider |
| [`scripts/record.py`](scripts/record.py) | Capture path: toggled recording tracked in state; nothing transcribed or kept without an explicit stop |
| [`scripts/transcribe.py`](scripts/transcribe.py) | Transcription path through the declared Hermes relay: session token in process memory only, nothing kept |
| [`scripts/binding.py`](scripts/binding.py) | Sticky single-agent binding store: one explicit bind, replaced only by an explicit rebind |
| [`scripts/deliver.py`](scripts/deliver.py) | Delivery path: transcript into the bound agent's input box unsubmitted, or a named audible refusal that holds it |
| [`scripts/preflight.py`](scripts/preflight.py) | Preflight the declared providers, the stop keybinding, and the executables; report by name, never install or repair |
| [`scripts/pane.py`](scripts/pane.py) | The Voice pane: the one long-running operator surface and listen-path sequencer |
| [`scripts/voice_cli.py`](scripts/voice_cli.py) | The one command surface: `pane`, `bind`, `preflight`, `toggle`, `stop` |
| [`skills/voice/`](skills/voice/SKILL.md) | Agent Skill: documents the CLI and the in-pane keys; adds no second command surface |
| [`tests/`](tests/) | `unittest` suites for the scripts above, the Stop hook, and the skill entrypoint |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude client extension directory: manifest, hook descriptor, and the Stop hook |

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

Restart Claude Code after installing: the Stop hook is registered at session
start.

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

Retention behaviour is a stated setting rather than a silent default: the
empty case — audio deleted after success and failure, no transcript log, no
telemetry — is something a person wrote down as
`VOICE_RETENTION=ephemeral`. Any other value is refused by name rather than
honoured.

## The Herdr-wide stop keybinding

Voice preflight checks — and never writes — one operator-owned keybinding: a
Herdr-wide binding whose command invokes the package's stop path. Add a
`[[keys.command]]` entry to `~/.config/herdr/config.toml` whose `command`
string contains `voice stop`; the key itself is yours to choose:

```toml
[[keys.command]]
key = "<your key here>"
command = "voice stop"
description = "stop voice playback"
```

Voice reports the keybinding's absence by name; it never creates or repairs
any Herdr configuration.

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
