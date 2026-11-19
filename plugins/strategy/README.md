# strategy

Standalone skill that creates and updates the repository root `STRATEGY.md`. It records direction. It does not implement, file issues, or write a run record.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Vendor-neutral. |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only. |
| [`skills/strategy/SKILL.md`](skills/strategy/SKILL.md) | The portable skill. |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter manifest. The skill is the command surface, so this directory carries no command wrapper. |
| [`skills/strategy/references/`](skills/strategy/references/interview.md) | Interview rulebook, template, and formatting contract. |

## How a harness reaches it

The skill triggers in conversation. There is no Python entrypoint.

Claude Code install, from a checkout of this repository:

```bash
claude plugin marketplace add /path/to/infiquetra-agent-plugins
claude plugin install strategy@infiquetra-agent-plugins
```
