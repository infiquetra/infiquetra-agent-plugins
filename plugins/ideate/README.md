# ideate

Standalone ideation skill. It writes `docs/ideation/` and keeps fail-open TypeSafe judgments in the skill directory so a skill-scoped install can run the script.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Vendor-neutral. |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only. |
| [`skills/ideate/SKILL.md`](skills/ideate/SKILL.md) | The portable skill. |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter manifest. The skill is the command surface, so this directory carries no command wrapper. |
| [`skills/ideate/scripts/shaping_judgments.py`](skills/ideate/scripts/shaping_judgments.py) | Advisory judgments. Fails open when no key is present. |
| [`fleet-bundle.json`](fleet-bundle.json) | Declares the Fleet Core modules copied beside that script. |

## How a harness reaches it

Resolve `scripts/shaping_judgments.py` from the directory that contains `skills/ideate/SKILL.md`, or from `$CLAUDE_PLUGIN_ROOT/skills/ideate/scripts/shaping_judgments.py` when Claude installed the package. Do not resolve `scripts/` from the repository being edited.

```bash
python3 plugins/ideate/skills/ideate/scripts/shaping_judgments.py --help
```

Session scratch under `.ideate/runs/` is listed in the repository `.gitignore` (`.ideate/`).


Claude Code install, from a checkout of this repository:

```bash
claude plugin marketplace add /path/to/infiquetra-agent-plugins
claude plugin install ideate@infiquetra-agent-plugins
```
