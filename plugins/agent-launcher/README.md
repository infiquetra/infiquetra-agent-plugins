# agent-launcher

Portable Agent Plugins 1.0 package. The portable core is this directory: `plugin.json`, the `agent-launcher` skill, `skills/agent-launcher/scripts/launcher.py`, and the role prompt library. Claude-only packaging sits in two manifests that carry paths and no behaviour: the root `.claude-plugin/plugin.json` and `com.infiquetra.claude/plugin.json`. This package is authored in this repository. There is no provenance manifest.

Session creation is the installed `agents` wrapper and herdr core (`hc`). The scripts are standard library only, on the catalog floor `python>=3.12`. This package keeps no vendor or model registry. This package does not ship a copy of the `herdr` skill or of `hc`.

Resolve the script from this package: `skills/agent-launcher/scripts/launcher.py`. Claude Code sets `CLAUDE_PLUGIN_ROOT` to the installed package root, so the same file is `$CLAUDE_PLUGIN_ROOT/skills/agent-launcher/scripts/launcher.py`. Skill-scoped harnesses install the `skills/agent-launcher/` unit. Nothing in this package searches a Claude plugin cache.

## Create a session in the Herdr app

```bash
agents --workspace "<Workspace name>" --task <tab-name> --cwd <dir> <tool>
```

A machine other than this one takes `--app-machine <machine>`. A crew takes `agents --crew --workspace "<name>"`.

## Operate the session with hc

- `hc ls` lists terminals.
- `hc read` reads a terminal.
- `hc send` writes to a terminal.
- `hc wait` waits on a terminal.

## Roles

`roles/` holds one reusable prompt per role the software development lifecycle names. Its contract is in [`roles/README.md`](roles/README.md). Nothing in this package spawns those roles.

## Headless review

`launcher.py review` starts the targeted reviewer in a sandboxed copy of one commit. `reviewer-probe` checks that sandbox. The sandbox denies `/tmp`, `/private/tmp`, and `/private/var/folders`. Claude screens `AGENTS.md` for `@` imports that leave the copy.

```bash
python3 skills/agent-launcher/scripts/launcher.py review --help
python3 skills/agent-launcher/scripts/launcher.py reviewer-probe --help
```
