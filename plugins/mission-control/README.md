# mission-control portable package

Portable Agent Plugins 1.0 package for SDLC management on Infiquetra's active
boards — Operations, Asgard, and CAMPPS. It ships one shared CLI
(`scripts/sdlc_manager.py`), seven Agent Skills over it, the board census,
pagination, and template-sync helpers, and vendored board configuration.
Claude-only files live under the client extension directory
`com.infiquetra.claude/`; they are an adapter, not the identity of this
package.

This tree is a derived artifact of `infiquetra-claude-plugins` at the commit
recorded in `PROVENANCE.json` (upstream plugin version 2.12.2). Custody has
not moved. The upstream repository remains the runtime source of truth; a
needed byte change in copied content is an upstream filing, never a downstream
patch.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins 1.0 manifest (target-owned) |
| [`README.md`](README.md) | This document: the portable package README (target-owned; supersedes the upstream README) |
| `PROVENANCE.json` | Source repository, pinned commit, and per-path custody |
| `CHANGELOG.md` | Upstream version history (byte copy) |
| `fleet-bundle.json` | Build declaration: which Fleet Core modules this package consumes |
| `scripts/sdlc_manager.py` | The shared CLI every skill documents a subset of |
| `scripts/board_census.py` | Board-schema census: `--check` reports drift, `--write` regenerates `config/board-schema.json` |
| `scripts/check_pagination.py` | Pagination helper for `gh api` list operations |
| `scripts/sync_template_docs.py` | Syncs issue-template documentation from `infiquetra-sdlc` |
| `scripts/executor_profile_lint.py` | Executor profile lint (transformed entrypoint; resolves the bundled Fleet Core modules) |
| `skills/` | The seven skills below, each with its reference material |
| `config/sdlc-schema.json`, `config/project-mappings.json`, `config/board-schema.json` | Vendored board and workflow configuration |
| `com.infiquetra.claude/` | Claude adapter: relocated manifest, slash commands, agent definition |
| `tests/` | The package's own pytest suite (upstream byte copies) |

## Skills

All seven skills share the one CLI; each skill's `SKILL.md` documents the
subset of the command surface it uses.

| Skill | Activates when... |
|---|---|
| `board` | Board review, item movement, WIP analysis, standup prep. Board commands require an explicit `--project` (`operations`, `asgard`, or `campps`); no board is a default. |
| `flow` | Operator-facing GraphQL + REST helpers: project field assignment, live field-option discovery, repo-to-project resolution, Team Mimir intake, native sub-issue link and unlink, self-healing label create, and card body pre-flight validation. |
| `issues` | Issue creation, the five issue types, template guidance, and prepared handoff drafts with readiness checks and source artifact resolution. |
| `labels` | Label deployment, audit, initiative/objective field sync, and auto-label rules. |
| `metrics` | Cycle time, throughput, and WIP age computed from GitHub timeline events. |
| `milestones` | Objective milestones via GitHub Milestones: create, list, progress, and issue linking. |
| `rollout` | Rollout status, gap analysis, and SDLC deployment (labels and templates) to any Infiquetra repository. |

## Read-only and GitHub-mutating subcommands

Every GitHub access this package performs goes through the `gh` CLI. The
audited split of the CLI surface, as recorded in the port descriptor
([`ports/mission-control.json`](../../ports/mission-control.json)):

| Group | Read-only against GitHub | Mutates GitHub |
|---|---|---|
| `board` | `view`, `wip`, `standup`, `discover-fields` | `add`, `move`, `archive` |
| `issue` | `prepare`, `intent-envelope` | `create`, `create-prepared`, `approve`, `close`, `reopen`, `comment`, `label-add`, `label-remove` |
| `labels` | `audit` | `deploy`, `auto-label`, `sync-fields` |
| `fields` | `discover` | `create-option` |
| `metrics` | `cycle-time`, `throughput`, `wip-age`, `column-time` | — |
| `milestones` | `list`, `progress` | `create`, `link` |
| `rollout` | `status`, `gap-analysis`, `update` | `deploy-labels`, `deploy-templates`, `deploy-all` |
| `flow` | `field-options`, `discover-project`, `validate-card` | `set-field`, `assign-mimir`, `link-sub-issue`, `unlink-sub-issue`, `verify-label` |
| `config` | `show`, `show-defaults`, `init-defaults` | — |

"Read-only" means the subcommand performs no GitHub write. A few read-only
subcommands still write local state: `issue prepare` writes a draft and JSON
sidecar under `docs/sdlc-issue-drafts/` of the current repository, `config
init-defaults` seeds `~/.claude/sdlc-defaults.json`, and `rollout update`
maintains the legacy local rollout configuration (the upstream
`beads-config.json` was retired; reads degrade gracefully to `{}`).

One mutation route is an internal code path rather than a CLI verb: when
`issue create-prepared` meets a repository that is not mapped to the requested
project, it opens a mapping pull request — real `git` worktree add, commit,
and push plus `gh pr create` — before continuing. The descriptor lists that
path as `_open_mapping_pr` so the safety predicate treats the route as
mutating.

## Authentication and environment

- The `gh` CLI must be installed and authenticated (`gh auth status`);
  project-field writes additionally need the Projects write scope.
- The scripts delegate all GitHub access to the `gh` CLI and read no token
  environment variable themselves. `gh` manages its own credentials and
  itself honors `GH_TOKEN`, `GITHUB_TOKEN`, and `GH_HOST` — which is why the
  compatibility assessment strips both the `GH_` and the `GITHUB_` prefix from
  every subprocess it runs against this package.
- `INFIQUETRA_SDLC_PATH` is the only environment override the scripts read.
  It points at an `infiquetra-sdlc` checkout and defaults to
  `~/workspace/infiquetra/infiquetra-sdlc`.

## Configuration resolution

The catalog requires `python>=3.12`. `sdlc_manager.py` and
`sync_template_docs.py` import PyYAML at module scope, so PyYAML must be
installed before any command runs.

Resolution orders at startup, from `sdlc_manager.py`:

- **Board and workflow schema** (`config/sdlc-schema.json`) — network-first:
  read from `infiquetra-sdlc` on GitHub `main` via the `gh` API first,
  because a local checkout may be stale; on failure fall back to the vendored
  `config/sdlc-schema.json` inside this package, then to the local
  checkout's copy.
- **Project mappings** (`config/project-mappings.json`) — local-first: the
  `INFIQUETRA_SDLC_PATH` checkout, then the vendored copy, then the remote
  via the `gh` API.
- **Board schema** — the vendored `config/board-schema.json`;
  `board_census.py --check` reports drift against the live boards and
  `--write` regenerates it.

## Client extension directory

Agent Plugins 1.0 puts client-specific files in an explicit extension
directory rather than at the package root. This package's Claude adapter is
`com.infiquetra.claude/`: the relocated Claude Code manifest, the four slash
commands (`board`, `issue`, `metrics`, `triage`), and the `sdlc-operator`
agent definition, all byte copies of the upstream client files. The portable
manifest, skills, and scripts beside that directory carry no Claude loading
convention.

## Fleet Core bundle

`sdlc_manager.py` and `executor_profile_lint.py` consume three Fleet Core
modules: `intent_envelope`, `tier_palette`, and the `models.json` registry.
Agent Plugins 1.0 has no dependency field, so this package does not install
Fleet Core at runtime. `fleet-bundle.json` declares the modules and their
destinations, and
[`scripts/bundle_fleet_module.py`](../../scripts/bundle_fleet_module.py)
generates them under `scripts/_bundled/` as digest-stamped build artifacts.
The dropped `fleet_commons_shim` used Claude-specific runtime discovery; this
package does not ship it.

Verify the stamps without writing:

```bash
python3 scripts/bundle_fleet_module.py --check
```

The Fleet Core source is the sibling package
[`plugins/fleet-core/`](../fleet-core/README.md); deferred modules are named
in its `DEFERRED.md`.

## Validation in this repository

These commands run from the repository root. None of them contacts GitHub:
the live operations above all go through the `gh` CLI, and every command
below is a repository check or a usage probe that exercises import and
argument parsing without credentials or a network call.

```bash
python3 scripts/bundle_fleet_module.py --check
python3 scripts/check_repo.py
python3 plugins/mission-control/scripts/sdlc_manager.py --help
python3 plugins/mission-control/scripts/board_census.py --help
python3 plugins/mission-control/scripts/check_pagination.py --help
python3 plugins/mission-control/scripts/sync_template_docs.py --help
python3 plugins/mission-control/scripts/executor_profile_lint.py --help
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/mission-control/tests -q
```

The package's own pytest suite lives under `plugins/mission-control/tests/`
(upstream byte copies). This repository additionally enforces this README the
way a consumer reads it — the opening paragraph must identify the portable
package, every relative link must resolve, every documented `python3` command
above must actually run with the `GH_` and `GITHUB_` variables stripped, and
no documented invocation may be mutating. That check is
[`tests/test_mission_control_readme.py`](../../tests/test_mission_control_readme.py).

## Further reading

- [Port descriptor](../../ports/mission-control.json)
- [Portable port runbook](../../docs/runbooks/portable-plugin-port.md)
- [Migration run plan](../../docs/plans/2026-08-24-mission-control-port-run-plan.md)
- [Portable Fleet Core](../fleet-core/README.md)
- [Repository commands](../../AGENTS.md)
- Upstream source: `infiquetra/infiquetra-claude-plugins`
