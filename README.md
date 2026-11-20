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
  three skill-scoped harnesses (OpenCode, Gemini CLI, Hermes) can reach
  them.
- **Claude-only behaviour under `com.infiquetra.claude/`** (commands, agents,
  hooks, MCP registration, output styles, Claude Code mods: TypeScript hooks
  modules under `mods/` and a `types/index.d.ts` state contract). The root `.claude-plugin/plugin.json`
  and the generated root marketplace carry paths and identity only
  (`scripts/sync_marketplace.py`, checked by `check_repo.py`).
- **Codex packaging** at `plugins/<pkg>/.codex-plugin/plugin.json` and the
  root `.agents/plugins/marketplace.json`, both generated
  (`scripts/sync_codex_packaging.py`), for the same reason and under the same
  paths-only rule.
- **Muse installs plugin bundles through a staged marketplace** at
  `build/muse-marketplace/` (`scripts/sync_marketplace.py`). The installer
  selects the 11 applicable packages, projects their Claude-compatible manifests,
  and installs via `muse plugins`, registered under the compatibility name
  `infiquetra-claude-plugins` but built from this repository. `fleet-core` is
  excluded.
  See [the Muse install workflow](docs/runbooks/install-clients.md#muse).
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
  [agent-launcher matrix, superseded 2026-09-22](docs/evidence/2026-08-27-agent-launcher-compatibility-matrix-pre-authored-import.md),
  [Mission Control matrix, superseded 2026-09-22](docs/evidence/2026-08-30-mission-control-compatibility-matrix.md),
  and [UniFi matrix, superseded 2026-09-22](docs/evidence/2026-08-22-unifi-compatibility-matrix.md).
- [Cross-vendor plugin architecture brief](docs/cross-vendor-plugin-architecture-brief.md)
  — the research and proposed direction the ports tested.
- [Engineering journal](docs/engineering-journal/README.md) — the decisions
  taken, the learnings produced, and the work deliberately deferred.

## Packages

| Package | Version | Description | Installable surfaces |
|---|---|---|---|
| [`plugins/agent-launcher/`](plugins/agent-launcher/README.md) | `3.0.1` | Headless sandboxed review, the SDLC roles library, and the herdr-app plus hc session workflow | Claude, Codex, Muse, 1 skill |
| [`plugins/brainstorm/`](plugins/brainstorm/README.md) | `0.1.0` | Pressure-tests one chosen idea into a right-sized requirements document | Claude, Codex, Muse, 1 skill |
| [`plugins/deploy/`](plugins/deploy/README.md) | `0.2.5` | Tag-promotion deployment operations for Infiquetra repositories | Claude, Codex, Muse, 1 skill |
| [`plugins/fleet-core/`](plugins/fleet-core/README.md) | `0.34.0` | Authored Fleet Core library: staffing (work shape, role, and lens to model and… | Codex |
| [`plugins/home-lab-ops/`](plugins/home-lab-ops/README.md) | `1.2.3` | Proxmox VE cluster operations, Ansible pre-flight validation, Ceph management,… | Claude, Codex, Muse, 6 skills |
| [`plugins/ideate/`](plugins/ideate/README.md) | `0.1.0` | Generates and critically evaluates grounded product, architecture, and workflow ideas | Claude, Codex, Muse, 1 skill |
| [`plugins/investigate/`](plugins/investigate/README.md) | `0.1.0` | Finds the root cause of a bug or failure before any fix | Claude, Codex, Muse, 1 skill |
| [`plugins/mission-control/`](plugins/mission-control/README.md) | `2.21.7` | SDLC management for Operations, Asgard, and CAMPPS: prepared issue drafts, live schema… | Claude, Codex, Muse, 8 skills |
| [`plugins/plan/`](plugins/plan/README.md) | `0.1.0` | Lightweight planning package: guidelines for breaking work into verifiable units | Claude, Codex, Muse, 1 skill |
| [`plugins/reviews/`](plugins/reviews/README.md) | `0.2.0` | Standalone code review, security review, document rubrics, and review-tool setup | Claude, Codex, Muse, 4 skills |
| [`plugins/strategy/`](plugins/strategy/README.md) | `0.1.0` | Maintains the repository root STRATEGY.md | Claude, Codex, Muse, 1 skill |
| [`plugins/unifi/`](plugins/unifi/README.md) | `2.0.7` | Portable UniFi Network and Protect package: two Agent Skills with their bundled Python… | Claude, Codex, Muse, 2 skills |

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
build declarations and generated bundle stamps, the portable skills'
frontmatter, and that no TypeScript or JavaScript module source (nor the
`tsconfig.json` Claude Code writes at a package root) sits outside a Claude
adapter. It installs nothing and makes no network call, so this baseline
cannot be broken by a package index outage. A second continuous integration job
pins the catalog's declared floor, `python>=3.12`, installs
[`requirements-plugin-tests.txt`](requirements-plugin-tests.txt) under the observed
[`constraints-plugin-tests.txt`](constraints-plugin-tests.txt) resolution, and runs
all ported plugin tests with importlib isolation. Requirements remain the owner of
dependency intent and additions; constraints select the tested versions. The pin is the floor
itself rather than the newest interpreter, because a floor that is never
exercised is not a floor. The floor is a single value with a single owner,
[`tests/test_python_floor.py`](tests/test_python_floor.py), and every place the
catalog states it is checked against that owner.

A third continuous integration job, `claude-mods`, installs Claude Code at the
recorded floor build (2.1.286) and at the pinned build (2.1.289) and, for every
package whose Claude adapter names a hooks module, runs
`claude plugin validate --strict` and `claude plugin test`. Neither command
needs a login.

CI caches only pip downloads/wheels and the versioned Claude npm download cache;
every install, postinstall check, and live validation still runs. Cache keys include
exact requirement/constraint inputs or CLI version and interpreter/platform/tool
policy. Unknown Claude cache platforms run without that optional cache. No installed
environment, global binary, credentials, or configuration is cached.

The root job uses the standard-library-only `scripts/ci/run_root_tests.py` wrapper
for full unittest discovery and per-module test-call timings.
The wrapper delegates execution and exit policy to unittest and reports timings
and result counts without collecting test identities or prewalking suites.
The plugin job emits
JUnit and the 25 slowest durations. Root timing and plugin JUnit artifacts are
uploaded even after test failures and retained for 14 days; timings are observations,
not a savings estimate. Provisioning is bounded by five-minute installer steps;
root, plugin, and CLI jobs have five-, twenty-, and ten-minute deadlines respectively.

Four dependency-backed repository checks live in the provisioned plugin lane:
[the two independent template audits](plugins/mission-control/tests/test_template_sync_audit.py),
[documented command execution](plugins/mission-control/tests/test_readme_commands.py),
and the plugin suites under `plugins/*/tests/`.
Their assertion bodies and original fixture/absence conditions are retained.
The remaining root tests import with the standard library alone; plugin tests use
real installed dependencies, including PyYAML. Template audits use the canonical
checkout selected by `INFIQUETRA_SDLC_PATH` and keep their original per-case
absence conditions. Integration requires the existing `Ported plugin tests` job
as a required check alongside `Repository validation`; this prerequisite does not
change workflow commands or branch protection.

## Development

- Read [`AGENTS.md`](AGENTS.md) before changing the repository.
- Use conventional commit messages.
- Use pull requests after the initial repository bootstrap.
- Update the engineering journal when work creates a durable learning,
  repository decision, or deferred item.
- Do not commit credentials, generated installed copies, or local agent state.

Public development guidance is summarized in
[`docs/public-safe-summary.md`](docs/public-safe-summary.md).
