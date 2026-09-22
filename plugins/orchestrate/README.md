# Orchestrate

Orchestrate runs one piece of work across several Herdr agent sessions. Each unit
gets its own git worktree and branch. The operator approves the table before
anything launches. State for a run is saga's per-issue run record,
`run_record.v1`, under the primary checkout's `.claude/saga/runs/issue-<N>.json`.
Orchestrate keeps its own block on that document and one row per unit.

This package is authored in this repository. The portable core is the driver and
the skill. Claude-only procedure text lives under the client extension.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Portable Agent Plugins manifest |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only: the command directory and the portable skills directory |
| [`skills/orchestrate/SKILL.md`](skills/orchestrate/SKILL.md) | The skill: what the driver does, how to run it, and the ordering rules |
| [`skills/orchestrate/scripts/orchestrate.py`](skills/orchestrate/scripts/orchestrate.py) | The driver. Standard library only |
| [`skills/orchestrate/scripts/herdr_events.py`](skills/orchestrate/scripts/herdr_events.py) | Herdr event-socket client used by `wait` |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter: manifest and the `/orchestrate` command |
| [`tests/`](tests/) | The driver's pytest suite |

## How a harness runs it

From the package root:

```bash
python3 skills/orchestrate/scripts/orchestrate.py --help
python3 skills/orchestrate/scripts/orchestrate.py plan-check --plan plan.json
```

Claude Code installs this package from the repository marketplace. It sets
`CLAUDE_PLUGIN_ROOT` to the package root, so the same driver is
`$CLAUDE_PLUGIN_ROOT/skills/orchestrate/scripts/orchestrate.py`. The command
procedure is `com.infiquetra.claude/commands/orchestrate.md`. The skill is the
portable document skill-scoped harnesses read: OpenCode, Gemini CLI, Muse, and
Hermes.

Every stateful subcommand takes `--issue <N>`. `--store-root` overrides where
the run record is read, which is how tests avoid the primary checkout.

## Companions

Two other packages have to be reachable. Neither path is a Claude plugin cache.

| Variable | Default when unset | What it is |
|---|---|---|
| `AGENT_LAUNCHER_ROOT` | the sibling directory `plugins/agent-launcher` | Package root of the shared launch contract. Orchestrate execs that package's launcher from the root |
| `ORCHESTRATE_RUN_RECORD` | the sibling saga package's run-record module, then an installed saga | One JSON record per issue |
| `ORCHESTRATE_AGENT_LAUNCHER` | `agents` on `PATH` | The wrapper whose `--help` lists vendors this machine can launch |
| `ORCHESTRATE_WORKTREE_SETUP` | none | Optional command run after a unit worktree is created |

The catalog copy of agent-launcher may be older than the floor declared in
`com.infiquetra.claude/plugin.json`. A sibling that does not define the names
Orchestrate calls is not ingested. Read-only commands still answer. Writes
refuse and name the install. Point `AGENT_LAUNCHER_ROOT` at a package root that
meets the floor when the sibling does not.

Orchestrate reads no credential variable. `gh` and `git` use their own
configuration. Herdr is an external process; the event client uses Herdr's
socket.

## What the driver will not do

It does not write a GitHub project board. It does not count tokens, reserve
concurrency slots, or keep a lock. A unit that goes wrong still has its
worktree, its branch, and its tab.
