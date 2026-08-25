---
name: voice
description: Operate the voice conversational loop for one bound Herdr-managed Claude session — bind an agent, start the Voice pane, toggle recording, stop playback, and preflight the declared providers
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

## Script

Every command below runs the bundled CLI from the voice package root
(the directory holding `plugin.json`):

```bash
python3 scripts/voice_cli.py <command>
```

## Commands

| Command | What it does |
|---|---|
| `bind <herdr-agent>` | Bind voice to one Herdr agent explicitly — resolves the agent, records its session and pane, and stays bound until an explicit rebind |
| `pane` | Start the Voice pane. Run it in its own Herdr pane: an interactive Claude session owns the pane it occupies |
| `preflight` | Probe the declared providers, the stop keybinding, and the capture/playback executables; names every missing prerequisite and never substitutes anything |
| `toggle` | One recording toggle press: start recording, or stop and deliver the transcript |
| `stop` | Stop playback immediately — the command the Herdr-wide stop keybinding invokes |

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
trip is the speech-to-text guarantee; the Herdr-wide `voice stop`
keybinding presence; and the capture and playback executables. Preflight
reads and probes only — it never installs, writes, or repairs anything.

## Settings and privacy

Settings, the documented stop keybinding, and the retention posture are
in [README.md](../../README.md). In short: audio is ephemeral — deleted
after success and failure, no transcript log, no telemetry. The
speech-to-text route sends audio off the machine to the named remote
service; the speak route stays on the local network. Voice never reads
the relay's own credentials.
