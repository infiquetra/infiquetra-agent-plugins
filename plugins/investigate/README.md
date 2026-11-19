# investigate

Standalone root-cause skill. Diagnosis is the deliverable. A trivial fix may be applied and self-verified. Real implementation routes to mission-control and plan.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Vendor-neutral. |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only. |
| [`skills/investigate/SKILL.md`](skills/investigate/SKILL.md) | The portable skill. |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter manifest. The skill is the command surface, so this directory carries no command wrapper. |
| [`skills/investigate/references/`](skills/investigate/references/methodology.md) | Methodology, pattern taxonomy, and the debug-report template. |

## How a harness reaches it

The skill triggers in conversation. There is no Python entrypoint.

Claude Code install, from a checkout of this repository:

```bash
claude plugin marketplace add /path/to/infiquetra-agent-plugins
claude plugin install investigate@infiquetra-agent-plugins
```
