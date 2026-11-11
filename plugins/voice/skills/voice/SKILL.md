---
name: voice
description: Operate the voice conversational loop for one bound Herdr-managed Claude session — bind its herdr core terminal, start the Voice pane, toggle recording, stop playback, and preflight the declared providers
metadata:
  compatibility: python>=3.12
---

# Voice

One explicitly bound, Herdr-managed Claude Code session gets a spoken
conversational loop: the bound session speaks its completed response, the
operator toggles recording in the Voice pane and speaks, toggles again, a
declared speech-to-text provider transcribes, and the text returns to that
same session's input box, unsubmitted and editable. One session at a time,
both directions, no arbitration anywhere.

Use this skill when the operator wants to talk with a bound session: bind
voice to an agent, start or quit the Voice pane, check that voice is ready
to run (preflight), stop playback, or toggle a recording outside the pane.

Herdr is herdr core (`hc`, which runs the session's terminal) and the Herdr
app (the window). Voice reads the bound terminal with `hc get`, types the
transcript with `hc keys` (never `hc send`, which presses Enter), and learns
the terminal's Claude session from a `voice.agent-session` label that the
plugin's SessionStart hook writes. Old Herdr (`herdr agent`, `herdr pane`)
is retired.

`hc keys` types only letters, digits, spaces and `` . , ' - ; / = ` [ ] ``
exactly. A transcript with any other character (every question mark, for
one) or one starting with `/` is not typed: voice says so and holds it.
Press `d` to discard it; `u` would only refuse it again, because the
characters do not change. Until herdr core can paste text without Enter,
spoken questions cannot be delivered.

Voice types only into an agent that reports exactly `idle`; otherwise it says
so and holds the transcript (`u` retries once the agent is idle). If the agent
changed while the keys went in, voice says the transcript may have reached a
prompt: look at the session before pressing Enter.

## Script

Every command below runs the bundled CLI from the voice package root
(the directory holding `plugin.json`):

```bash
python3 scripts/voice_cli.py <command>
```

## Commands

| Command | What it does |
|---|---|
| `bind <terminal>` | Bind voice to one Claude session explicitly, named by its herdr core terminal (`review` or `t7`) — reads the terminal, records its session and address, and stays bound until an explicit rebind. Refuses a terminal on another machine, a finished one, and one the plugin's SessionStart hook has not labelled yet |
| `pane` | Start the Voice pane. Run it in its own Herdr tab or pane: an interactive Claude session owns the terminal it occupies |
| `preflight` | Probe the declared providers, the Herdr app stop key, and the capture/playback executables; names every missing prerequisite and never substitutes anything |
| `toggle` | One recording toggle press: start recording, or stop and deliver the transcript |
| `stop` | Stop playback immediately — the command the Herdr-wide stop key invokes |

## In-pane keys

The pane reads single keys immediately, without Enter:

| Key | Action |
|---|---|
| `t` | Toggle recording. Starting a recording stops any playback first; a second press stops, transcribes, and delivers |
| `s` | Stop playback immediately |
| `u` | Use a refused transcript (deliver it) |
| `d` | Discard a refused transcript |
| `q` | Quit the pane |

While recording, the pane shows `*** RECORDING ***` next to the bound
agent name and session id, so the recording state and the bound identity
are always visible together.

## Preflight before first use

Run `preflight` and fix what it names. It proves, by provider and
prerequisite name: Voice Forge health with a loaded backend, the
configured voice id, one real short synthesis; the Hermes relay health,
its session token, the configured profile resolved among the relay's
profiles, and one synthesized sample round trip that comes back a
non-empty transcript from the `xai` speech-to-text provider — the round
trip is the speech-to-text guarantee; the Herdr-wide `voice stop` key — a
key in the Herdr app's `keys.json` that reaches a mod whose `exec` runs
`voice stop` — checked by resolving that command rather than matching its
text, because containing `voice stop` and being able to stop anything
are different claims; and the capture and playback executables. Preflight
reads and probes only — it never installs, writes, or repairs anything.

## Settings and privacy

Settings, the documented stop keybinding, and the retention posture are
in [README.md](../../README.md). In short: audio is ephemeral — deleted
after success and failure, no transcript log, no telemetry. The
speech-to-text route sends audio off the machine to the named remote
service; the speak route stays on the local network. Voice never reads
the relay's own credentials.
