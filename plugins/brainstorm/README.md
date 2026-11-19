# brainstorm

Standalone requirements skill. It writes `docs/brainstorms/`, keeps the ideate survivor schema as intake, and hands off to plan, reviews, and mission-control.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Vendor-neutral. |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only. |
| [`skills/brainstorm/SKILL.md`](skills/brainstorm/SKILL.md) | The portable skill. |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter manifest. The skill is the command surface, so this directory carries no command wrapper. |
| [`skills/brainstorm/scripts/shaping_judgments.py`](skills/brainstorm/scripts/shaping_judgments.py) | Advisory judgments. Fails open when no key is present. |
| [`fleet-bundle.json`](fleet-bundle.json) | Declares the Fleet Core modules copied beside that script. |

## How a harness reaches it

From this package, or from a skill-scoped install of `skills/brainstorm/`:

```bash
python3 skills/brainstorm/scripts/shaping_judgments.py --help
```


Claude Code install, from a checkout of this repository:

```bash
claude plugin marketplace add /path/to/infiquetra-agent-plugins
claude plugin install brainstorm@infiquetra-agent-plugins
```
