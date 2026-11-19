# plan

Lightweight planning for a repository change. The skill triggers when someone asks for a plan or a breakdown. A small plan stays in the chat. A plan that spans units or sessions is saved as `docs/plans/YYYY-MM-DD-<slug>-plan.md` and checked with `check_plan.py`.

The package is authored in this repository. There is no provenance manifest and no upstream pin.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Name, version, and description |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude Code packaging manifest. Paths into the adapter and the skill directory |
| [`.codex-plugin/plugin.json`](.codex-plugin/plugin.json) | Codex packaging manifest, generated from the portable manifest |
| [`skills/plan/SKILL.md`](skills/plan/SKILL.md) | Planning guidelines |
| [`skills/plan/references/plan-template.md`](skills/plan/references/plan-template.md) | Section order for a saved plan |
| [`skills/plan/scripts/check_plan.py`](skills/plan/scripts/check_plan.py) | Standard-library checker for a saved plan |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter: advisory hook for `docs/plans/*.md` writes |
| [`tests/`](tests/) | Checker and hook tests |
| [`CHANGELOG.md`](CHANGELOG.md) | Package history |

The checker sits inside the skill directory on purpose. OpenCode, Gemini CLI, Muse, and Hermes install that directory and nothing else, so a script left at the package root would not be there when those harnesses ran it.

## Running the checker

Python 3.12 or newer, standard library only. From the repository root:

```bash
python3 plugins/plan/skills/plan/scripts/check_plan.py --help
python3 plugins/plan/skills/plan/scripts/check_plan.py docs/plans/YYYY-MM-DD-<slug>-plan.md
```

Exit 0 means the saved plan has its sections, its unmarked paths exist, its `(new)` paths have an existing ancestor or a planned parent, and it contains no `TBD`, `TODO`, or vague file count. The checker reads the file and does not edit it.

## How a harness reaches it

Claude Code installs the package root from this repository's marketplace. The root [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) points `hooks` at [`com.infiquetra.claude/hooks/hooks.json`](com.infiquetra.claude/hooks/hooks.json) and `skills` at [`skills/`](skills/plan/SKILL.md). The hook command is `python3 "${CLAUDE_PLUGIN_ROOT}/com.infiquetra.claude/hooks/validate_plan_write_hook.py"`. It runs after Write, Edit, and MultiEdit, and only when the path is a markdown file directly under `docs/plans/`. Gaps come back as advisory context. The write is kept.

OpenCode, Gemini CLI, Muse, and Hermes install [`skills/plan/`](skills/plan/SKILL.md). The skill's script is the command surface.

This package does not bundle Fleet Core and does not ship a Model Context Protocol (MCP) server.
