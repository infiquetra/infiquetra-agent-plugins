# Infiquetra Agent Plugins

Portable Agent Skills, Agent Plugins, and vendor adapters for Infiquetra
engineering workflows.

This public repository is the design and source catalog for behavior that does
not belong to one coding-agent vendor. It complements, and is intended to
eventually generate parts of, the existing Claude Code, Codex, Antigravity,
OpenCode, and Hermes plugin repositories. Those repositories remain the runtime
sources of truth until a recorded custody decision moves that authority here, and
no such decision has been made.

## Status

**Custody moved here on 2026-09-22.** This repository is the source of truth
for every Infiquetra plugin. The thirteen live plugins of
`infiquetra-claude-plugins` (commit `acc99fe7`; the fourteenth,
`team-execution`, had already been archived upstream) were imported once,
package by package, and are authored here from that commit: there is no
upstream pin and no provenance manifest any more. The decision, its
rationale, and the four rules it changed are the 2026-09-22 entry in
[`DECISIONS.md`](docs/engineering-journal/DECISIONS.md); the run plan is
[`docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md`](docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md).

What every package looks like now:

- **Vendor-neutral core at the package root** (`plugin.json`, `skills/`,
  `scripts/`, `references/`, `tests/`). A package whose upstream shipped only
  Claude commands now also carries a portable skill over its scripts, so the
  four skill-scoped harnesses (OpenCode, Gemini CLI, Muse, Hermes) can reach
  them.
- **Claude-only behaviour under `com.infiquetra.claude/`** (commands, agents,
  hooks, MCP registration, output styles). The root `.claude-plugin/plugin.json`
  and the generated root marketplace carry paths and identity only
  (`scripts/sync_marketplace.py`, checked by `check_repo.py`).
- **Codex packaging** at `plugins/<pkg>/.codex-plugin/plugin.json` and the
  root `.agents/plugins/marketplace.json`, both generated
  (`scripts/sync_codex_packaging.py`), for the same reason and under the same
  paths-only rule.
- **Fleet Core is a library, bundled at build time** into each consumer's
  `_bundled/` directory (`scripts/bundle_fleet_module.py`); it is not
  installed as a plugin by any harness. The upstream discovery shim
  (`fleet_commons_shim.py`) does not cross the boundary.
- **Tests travel with the package** under `plugins/<pkg>/tests/` and run in
  CI with pytest's importlib import mode; repository-level tests stay
  standard-library-only.

How a harness on a machine installs the catalog is
[`docs/runbooks/install-clients.md`](docs/runbooks/install-clients.md)
(`scripts/install_client.py`, with `--check` readback and a legacy uninstall
for placements that recorded the old repository).

Compatibility evidence binds to a released package version rather than to
every tree (2026-09-22 decision). The ten-client matrices under
[`docs/evidence/`](docs/evidence/) that predate the import are superseded
and kept as historical context; fresh assessments for the authored versions
are queued work, not a claim this README makes.

The record of the work, in the order a new reader should take it:

- The custody-move [run plan](docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md)
  and the per-package import narratives under
  [`docs/engineering-journal/narratives/`](docs/engineering-journal/narratives/)
  (`2026-09-22-import-<package>.md`).
- The earlier ports that proved the layout, each ten-client matrix now
  superseded and kept as historical context:
  [agent-launcher matrix, superseded 2026-09-22](docs/evidence/2026-08-27-agent-launcher-compatibility-matrix.md),
  [Mission Control matrix, superseded 2026-09-22](docs/evidence/2026-08-30-mission-control-compatibility-matrix.md),
  and [UniFi matrix, superseded 2026-09-22](docs/evidence/2026-08-22-unifi-compatibility-matrix.md).
- [Cross-vendor plugin architecture brief](docs/cross-vendor-plugin-architecture-brief.md)
  — the research and proposed direction the ports tested.
- [Engineering journal](docs/engineering-journal/README.md) — the decisions
  taken, the learnings produced, and the work deliberately deferred.

## Packages

| Package | Version | Description | Installable surfaces |
|---|---|---|---|
| [`plugins/agent-launcher/`](plugins/agent-launcher/README.md) | `1.7.1` | Create one verified coding-agent session through the agents wrapper and Herdr | Claude, Codex, 1 skill |
| [`plugins/agy/`](plugins/agy/README.md) | `0.6.2` | Antigravity-backed coder reviewer bridge agents that run in a disposable clone and… | Claude, Codex, 1 skill |
| [`plugins/codex/`](plugins/codex/README.md) | `0.1.5` | Portable Codex delegation wrapper | Claude, Codex, 1 skill |
| [`plugins/deploy/`](plugins/deploy/README.md) | `0.2.3` | Tag-promotion deployment operations for Infiquetra repositories | Claude, Codex, 1 skill |
| [`plugins/fleet-core/`](plugins/fleet-core/README.md) | `0.32.0` | Authored Fleet Core library: staffing (work shape, role, and lens to model and… | Codex |
| [`plugins/hermes-profile-evolution/`](plugins/hermes-profile-evolution/README.md) | `0.1.5` | Portable request adapter for target-sovereign Hermes profile evolution | Claude, Codex, 1 skill |
| [`plugins/home-lab-ops/`](plugins/home-lab-ops/README.md) | `1.2.2` | Proxmox VE cluster operations, Ansible pre-flight validation, Ceph management,… | Claude, Codex, 6 skills |
| [`plugins/house-style/`](plugins/house-style/README.md) | `0.1.1` | Claude-only package | Claude, Codex |
| [`plugins/mission-control/`](plugins/mission-control/README.md) | `2.21.1` | SDLC management for Operations, Asgard, and CAMPPS: prepared issue drafts, live schema… | Claude, Codex, 8 skills |
| [`plugins/orchestrate/`](plugins/orchestrate/README.md) | `6.0.1` | Run one piece of work across several herdr agent sessions, one git worktree per unit | Claude, Codex, 1 skill |
| [`plugins/redis-channel/`](plugins/redis-channel/README.md) | `0.5.3` | Portable Redis Streams bridge | Claude, Codex, 1 skill |
| [`plugins/saga/`](plugins/saga/README.md) | `1.2.1` | Infiquetra lifecycle plugin: one automatic run per issue — admission, plan, plan… | Claude, Codex, 13 skills |
| [`plugins/unifi/`](plugins/unifi/README.md) | `2.0.7` | Portable UniFi Network and Protect package: two Agent Skills with their bundled Python… | Claude, Codex, 2 skills |
| [`plugins/voice/`](plugins/voice/README.md) | `0.4.0` | Portable voice package: a spoken conversational loop for one explicitly bound,… | Claude, Codex, 1 skill |

### Portable Fleet Core scope

The full Fleet Core module set at the import commit is here
(`plugins/fleet-core/scripts/fleet_commons/`, plus `scripts/jev.py` and
`references/`). What is deliberately absent is stated in
[`plugins/fleet-core/DEFERRED.md`](plugins/fleet-core/DEFERRED.md): the
Claude-specific discovery shim, and one residual data file kept only while a
consumer still declares it.

### Operator site profile

The portable UniFi package can read an optional operator site profile — a JSON
file describing one site's topology and intent — from a machine-local path. The
profile is optional in the strong sense: a runtime with no profile anywhere loads
successfully in discovery-only mode and infers no trust role, criticality, or
ownership rather than guessing a default.

How a profile is authored and deployed is the operator's business. The Infiquetra
instance keeps its profile in a private repository and renders JSON at deployment
time through an existing Ansible harness. That arrangement is one operator's
custody instance and is not required by the portable contract, which knows only a
path. See [`plugins/unifi/references/site-profile.md`](plugins/unifi/references/site-profile.md)
for the contract itself.

## Repository layout

| Path | Purpose |
|---|---|
| [`plugins/`](plugins/) | Portable packages, authored here since the 2026-09-22 custody move |
| [`ports/`](ports/README.md) | One port descriptor per package: identity, custody, and assessment settings |
| [`schemas/`](schemas/) | JSON Schemas for the contracts this repository validates |
| [`scripts/`](scripts/) | Validation, synchronization, bundling, and inventory tools |
| [`docs/runbooks/install-clients.md`](docs/runbooks/install-clients.md) | Place this catalog on each harness, read the placement back, and remove the old marketplace |
| [`docs/`](docs/README.md) | Architecture, public guidance, and durable repository knowledge |
| [`docs/plans/`](docs/plans/2026-08-24-mission-control-port-run-plan.md) | Approved implementation plans |
| [`docs/evidence/`](docs/evidence/2026-09-22-mission-control-compatibility-notice.md) | Assessment records, written under the public evidence rules |
| [`docs/engineering-journal/`](docs/engineering-journal/README.md) | Learnings, decisions, queued work, and archive |
| [`.github/`](.github/PULL_REQUEST_TEMPLATE.md) | Pull request, issue, and validation workflow configuration |

Client-specific material lives in an explicit adapter directory inside the package
that needs it, never at the package root. `plugins/unifi/com.infiquetra.claude/`
and `plugins/mission-control/com.infiquetra.claude/` are Claude adapters; the
portable manifests, skills, schemas, and scripts beside them carry no
client-specific assumption.

## Validation

Run the same checks used by continuous integration (CI):

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

The validation script checks the repository baseline, local Markdown links, the
Agent Plugin manifests under `plugins/`, each package's provenance manifest, the
build declarations and generated bundle stamps, and the portable skills'
frontmatter. It installs nothing and makes no network call, so this baseline
cannot be broken by a package index outage. A second continuous integration job
pins the catalog's declared floor, `python>=3.12`, installs `requests`,
`urllib3`, and `pytest`, and runs the ported plugin tests. The pin is the floor
itself rather than the newest interpreter, because a floor that is never
exercised is not a floor. The floor is a single value with a single owner,
[`tests/test_python_floor.py`](tests/test_python_floor.py), and every place the
catalog states it is checked against that owner.

## Development

- Read [`AGENTS.md`](AGENTS.md) before changing the repository.
- Use conventional commit messages.
- Use pull requests after the initial repository bootstrap.
- Update the engineering journal when work creates a durable learning,
  repository decision, or deferred item.
- Do not commit credentials, generated installed copies, or local agent state.

Public development guidance is summarized in
[`docs/public-safe-summary.md`](docs/public-safe-summary.md).
