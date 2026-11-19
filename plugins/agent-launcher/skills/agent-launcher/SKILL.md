---
name: agent-launcher
description: Create coding-agent sessions with the local agents wrapper in the Herdr app, then operate them with hc. The package also holds the SDLC roles prompts and a headless sandboxed review command.
---

# Agent launcher

Session creation is the installed `agents` wrapper in the Herdr app. After a session exists, herdr core (`hc`) lists, reads, sends, and waits. This package does not launch panes and does not ship a copy of those commands.

Resolve the script from this package: `skills/agent-launcher/scripts/launcher.py`.

## Create a session in the Herdr app

One named tab in a workspace:

```bash
agents --workspace "<Workspace name>" --task <tab-name> --cwd <dir> <tool>
```

A machine other than this one takes `--app-machine <machine>`.

A crew takes `agents --crew --workspace "<name>"`.

## Operate the session with hc

- `hc ls` lists terminals.
- `hc read` reads a terminal.
- `hc send` writes to a terminal.
- `hc wait` waits on a terminal.

## Roles

`roles/` holds the thirteen SDLC role prompts. Nothing in this package spawns those roles. After the session exists, send a prompt with the `hc send` command above.

## Headless review

`launcher.py review` starts the targeted reviewer in a sandboxed copy of one commit. `reviewer-probe` checks that sandbox.

The sandbox denies `/tmp`, `/private/tmp`, and `/private/var/folders`. Claude screens `AGENTS.md` for `@` imports that leave the copy.

```bash
python3 skills/agent-launcher/scripts/launcher.py review --help
python3 skills/agent-launcher/scripts/launcher.py reviewer-probe --help
```
