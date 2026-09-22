# mission-control portable package

Portable Agent Plugins 1.0 package for SDLC management on Infiquetra's active
boards — Operations, Asgard, and CAMPPS (upstream plugin version 2.21.0).
This tree is authored in this repository from the import of
`infiquetra-claude-plugins` at `acc99fe7`. The package version is 2.21.1.
It does not ship `PROVENANCE.json`; the pin is the changelog entry above
the 2.21.0 history.

The shared CLI is `scripts/sdlc_manager.py`. Eight Agent Skills document
slices of it. Claude-only files live under `com.infiquetra.claude/`.

`/issue [type]` is the Claude command for issue creation. The script verbs
are `issue prepare` and `issue create-prepared`.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins 1.0 manifest |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history, including the import pin |
| [`fleet-bundle.json`](fleet-bundle.json) | Fleet Core modules this package loads |
| `scripts/sdlc_manager.py` | The shared CLI |
| `scripts/board_census.py` | Board-schema census |
| `scripts/check_pagination.py` | Pagination check for `gh api` list calls |
| `scripts/sync_template_docs.py` | Regenerates the issue-template reference from infiquetra-sdlc |
| `scripts/executor_profile_lint.py` | Executor-profile lint over the bundled tier palette |
| `scripts/triage_suggest.py` | Advisory triage judgments; imported by the CLI, not a second entrypoint |
| `skills/` | The eight skills below |
| `config/` | Vendored board and workflow configuration |
| `com.infiquetra.claude/` | Claude adapter: manifest, four commands, `sdlc-operator` agent |
| `tests/` | This package's pytest suite |

## Skills

| Skill | Activates when... |
|---|---|
| `board` | Board review, item movement, WIP analysis, standup prep |
| `flow` | Project field assignment, sub-issue link and unlink, label verification, and card validation |
| `issues` | Issue creation, the five issue types, and prepared drafts |
| `labels` | Label deployment, audit, and auto-label rules |
| `metrics` | Cycle time, throughput, and WIP age |
| `milestones` | Objective milestones: create, list, progress, and linking |
| `rollout` | Rollout status, gap analysis, and SDLC deployment |
| `triage` | Recommend a type label and place an existing issue on a board |

## How a harness runs it

From this package root, the directory that contains `scripts/` and `skills/`:

```text
python3 scripts/sdlc_manager.py --help
```

A skill-scoped harness (OpenCode, Gemini CLI, Muse, Hermes) installs a skill
directory and follows that skill's commands. Those commands use the same
package-root invocation.

Claude Code installs the package root. The root `.claude-plugin/plugin.json`
points at `com.infiquetra.claude/` for commands and the agent, and at
`skills/` for the skills. Adapter commands set:

```bash
SCRIPT="$CLAUDE_PLUGIN_ROOT/scripts/sdlc_manager.py"
```

`scripts/` stays at the package root, so that variable still names the CLI.
The catalog requires `python>=3.12`.

## Read-only and GitHub-mutating subcommands

Every GitHub access goes through the `gh` CLI. The split recorded in
[`ports/mission-control.json`](../../ports/mission-control.json):

| Group | Read-only against GitHub | Mutates GitHub |
|---|---|---|
| `board` | `view`, `wip`, `standup`, `discover-fields` | `add`, `move`, `archive` |
| `issue` | `prepare`, `intent-envelope` | `create`, `create-prepared`, `approve`, `close`, `reopen`, `comment`, `label-add`, `label-remove` |
| `labels` | `audit` | `deploy`, `auto-label`, `sync-fields` |
| `fields` | `discover`, `create-option` | `set-options` |
| `metrics` | `cycle-time`, `throughput`, `wip-age`, `column-time` | — |
| `milestones` | `list`, `progress` | `create`, `link` |
| `rollout` | `status`, `gap-analysis` | `deploy-labels`, `deploy-templates`, `deploy-all` |
| `flow` | `field-options`, `discover-project`, `validate-card` | `set-field`, `assign-mimir`, `link-sub-issue`, `unlink-sub-issue`, `verify-label`, `repair-window` |
| `config` | `show`, `show-defaults`, `init-defaults` | — |

`issue prepare` writes a local draft. `config init-defaults` writes a local
defaults file. `flow repair-window` adds or removes the repair-window label
and posts a comment. When `issue create-prepared` meets an unmapped
repository it opens a mapping pull request (`_open_mapping_pr` in the
descriptor): real `git` worktree add, commit, and push, plus `gh pr create`.

## Authentication and environment

- `gh` must be installed and authenticated. The scripts do not read a token
  themselves. `gh` honors `GH_TOKEN`, `GITHUB_TOKEN`, and `GH_HOST`.
- `INFIQUETRA_SDLC_PATH` names an infiquetra-sdlc checkout. The script
  documents the path it uses when the variable is unset.
- `TYPESAFE_API_KEY` is required only for `--suggest`. When it is unset, the
  advisory path reports that and does not fail the command.
- `sync_template_docs.py` imports PyYAML at module scope.
  `sdlc_manager.py` imports PyYAML inside Team Mimir coverage validation and
  names PyYAML in the error if the import fails.

## Configuration resolution

- **Workflow schema** (`config/sdlc-schema.json`) — the `gh` API read of
  infiquetra-sdlc on `main` first, then the vendored file, then a local checkout.
- **Project mappings** — the `INFIQUETRA_SDLC_PATH` checkout, then the vendored
  file, then the `gh` API.
- **Board schema** — vendored `config/board-schema.json`.
  `board_census.py --check` reports drift; `--write` regenerates the file.

## Fleet Core bundle

The CLI loads `intent_envelope`, `plugin_resolution`, `typesafe_client`, and
`jev_log`. Those modules load `tier_resolver`, `tier_palette`,
`retry_backoff`, and `staffing.json`. `executor_profile_lint.py` loads
`tier_palette`. `fleet-bundle.json` declares that set.
[`scripts/bundle_fleet_module.py`](../../scripts/bundle_fleet_module.py)
writes `scripts/_bundled/`. This package does not ship `fleet_commons_shim`.

The Fleet Core source is [`plugins/fleet-core/`](../fleet-core/README.md).

## Validation

From the repository root. The probes below parse arguments and do not call
GitHub.

```bash
python3 scripts/bundle_fleet_module.py --check
python3 scripts/check_repo.py
python3 plugins/mission-control/scripts/sdlc_manager.py --help
python3 plugins/mission-control/scripts/board_census.py --help
python3 plugins/mission-control/scripts/check_pagination.py --help
python3 plugins/mission-control/scripts/sync_template_docs.py --help
python3 plugins/mission-control/scripts/executor_profile_lint.py --help
python3 -m pytest plugins/mission-control/tests -q
```

## Further reading

- [Port descriptor](../../ports/mission-control.json)
- [Changelog](CHANGELOG.md)
- [Portable Fleet Core](../fleet-core/README.md)
- [Repository commands](../../AGENTS.md)
