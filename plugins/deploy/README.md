# deploy

Portable tag-promotion operations for Infiquetra repositories. The package mints a
policy deployment tag, reports which version each environment is on, and previews
the release notes for a candidate range. It refuses a repository that is not
`github.com/infiquetra/*`, and it refuses to promote a snapshot marked
`unhealthy-v<version>` unless the operator passes an explicit override after
checking that snapshot by hand.

The package is authored in this repository. It was imported once from
`infiquetra-claude-plugins` at `acc99fe7` (upstream 0.2.2) and is maintained here
from 0.2.3 on. There is no provenance manifest and no upstream pin to
synchronize. The custody decision is recorded in
[the 2026-09-22 plan](../../docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md).

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Name, version, and description only |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude Code packaging manifest. Paths into the adapter and the skill directory, no behaviour |
| [`skills/deploy-state/SKILL.md`](skills/deploy-state/SKILL.md) | The portable skill: tag-promotion policy and how to run the three scripts |
| [`skills/deploy-state/scripts/mint_tag.py`](skills/deploy-state/scripts/mint_tag.py) | Build a `nonprod`, `staging`, `production`, rollback, or hotfix tag. `--dry-run` prints the plan and does not push |
| [`skills/deploy-state/scripts/query_deployments.py`](skills/deploy-state/scripts/query_deployments.py) | Latest deployment in each environment, and whether the versions drift |
| [`skills/deploy-state/scripts/preview_release_notes.py`](skills/deploy-state/scripts/preview_release_notes.py) | Short summary of a commit range. Does not create a GitHub release |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter: four slash commands and the `release-orchestrator` agent |
| [`tests/`](tests/) | Package contract tests, including a credential-free `--help` run of each script |
| [`CHANGELOG.md`](CHANGELOG.md) | Upstream history through 0.2.2, then the authored cut |

The scripts sit inside the skill directory on purpose. OpenCode, Gemini CLI,
Muse, and Hermes install that directory and nothing else, so a script left at
the package root would not be there when those harnesses ran it.

## Running the scripts

Python 3.12 or newer, standard library only. From the skill directory:

```bash
python3 scripts/mint_tag.py --help
python3 scripts/query_deployments.py --help
python3 scripts/preview_release_notes.py --help
```

A dry-run promotion, which does not create or push a tag:

```bash
python3 scripts/mint_tag.py --env nonprod --version 1.2.3 --dry-run
```

The scripts call `git` and the GitHub CLI (`gh`). `gh` reads `GH_TOKEN` or
`GITHUB_TOKEN` when one of those is set, and otherwise its own login. The
scripts never take a token as an argument. Flags, inference rules, and the
per-harness path are in the [skill](skills/deploy-state/SKILL.md).

## How a harness reaches it

Claude Code installs the package root from this repository's marketplace. The
root [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) points
`commands` and `agents` at [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json)
and `skills` at [`skills/`](skills/deploy-state/SKILL.md). The slash commands
are `/deploy`, `/deploy-status`, `/deploy-notes`, and `/deploy-hotfix`. The
agent is `release-orchestrator`. `${CLAUDE_PLUGIN_ROOT}` in those commands is
the installed package root.

OpenCode, Gemini CLI, Muse, and Hermes install
[`skills/deploy-state/`](skills/deploy-state/SKILL.md). The skill's scripts are
the command surface. There is no second one.

A package-scoped client (Claude Code, Codex, Cursor Agent, Qwen, Grok, Agy)
receives the whole tree, so the same scripts are at
`skills/deploy-state/scripts/` under the installed package.

This package does not bundle Fleet Core and does not ship a Model Context Protocol (MCP) server.
