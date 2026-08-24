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

The first portability pilot has been executed and is complete. It ported the
Claude Code `unifi` plugin into a portable Agent Plugins 1.0 package together
with one vertical slice of a portable Fleet Core source, and then assessed the
result against all ten coding-agent clients installed on the operator's machine.
Completion is recorded by the pilot
[retrospective](docs/engineering-journal/narratives/2026-08-23-unifi-portability-pilot-retrospective.md)
and by [porting runbook v1.0.0](docs/runbooks/portable-plugin-port.md), which
the pilot produced. The recorded operator decision was to stop at the completed
ten-client compatibility matrix and take no client-specific remediation
([`DECISIONS.md`](docs/engineering-journal/DECISIONS.md), 2026-08-22).

Custody did not move. Existing vendor repositories remain the runtime sources of
truth. The packages under [`plugins/`](plugins/) are derived artifacts: each is
generated from a pinned upstream commit and checked file by file against its own
SHA-256 provenance manifest. A derived package is never a second writable source,
and it is never hand-maintained.

Two facts about the current state are verified by the repository's own tests
and committed evidence:

- **Both UniFi client entrypoints run.** Each client script is classified in
  [`plugins/unifi/PROVENANCE.json`](plugins/unifi/PROVENANCE.json) as a
  `deterministic-transform` output of the versioned
  `resolve-bundled-fleet-module` rule, with a stamped build-time Fleet Core
  bundle in the `_bundled/` directory beside it.
  [`tests/test_client_entrypoints.py`](tests/test_client_entrypoints.py) runs
  both shipped scripts with no credentials and no network, asserts each answers
  `--help`, and fails when the bundle is removed.
- **All ten clients assessed; none failed.** The current
  [ten-client compatibility matrix](docs/evidence/2026-08-22-unifi-compatibility-matrix.md)
  records nine clients working directly and one, OpenAI Codex, working through
  an adapter: zero failed, zero unsupported. The adapter status is current fact
  — Codex's marketplace is its only placement path and holds no supported
  manifest, and the identified adapter, a Codex marketplace manifest, was not
  built here. Cursor Agent works directly; the matrix records why its earlier
  failure reading was an artifact of the assessment's isolation rather than a
  result of the client.

What remains open is distribution, not compatibility. OpenAI Codex needs a
marketplace manifest to be reachable at all, and Cursor Agent's marketplace
accepts only a git repository URL, so a local directory is not a path there.
Whether a client warrants a repair, an adapter, a different distribution path,
or an explicitly unsupported status is an operator decision per client, and
none has been taken. No client-specific remediation has begun; the open
decisions are recorded in the journal's
[queued work](docs/engineering-journal/QUEUED.md).

The record of the pilot, in the order a new reader should take it:

- [Ten-client compatibility matrix](docs/evidence/2026-08-22-unifi-compatibility-matrix.md)
  — what each client did with the package, stage by stage, with evidence.
- [UniFi and portable Fleet Core portability pilot plan](docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)
  — the approved plan the work followed.
- [Cross-vendor plugin architecture brief](docs/cross-vendor-plugin-architecture-brief.md)
  — the research and proposed direction the pilot tests.
- [Engineering journal](docs/engineering-journal/README.md) — the decisions taken,
  the learnings the pilot produced, and the work it deliberately deferred.

### Portable Fleet Core scope

Only the `retry_backoff` module is ported. Every other module the upstream source
carries is named as explicitly unported in
[`plugins/fleet-core/DEFERRED.md`](plugins/fleet-core/DEFERRED.md), so no reader
has to infer what is missing. Nothing in this repository claims full Fleet Core
parity.

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
| [`plugins/`](plugins/) | Portable packages, each derived from a pinned upstream revision |
| [`ports/`](ports/README.md) | One port descriptor per package: identity, custody, and assessment settings |
| [`schemas/`](schemas/) | JSON Schemas for the contracts this repository validates |
| [`scripts/`](scripts/) | Validation, synchronization, bundling, and inventory tools |
| [`docs/`](docs/README.md) | Architecture, public guidance, and durable repository knowledge |
| [`docs/plans/`](docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md) | Approved implementation plans |
| [`docs/evidence/`](docs/evidence/2026-08-22-unifi-compatibility-matrix.md) | Assessment records, written under the public evidence rules |
| [`docs/engineering-journal/`](docs/engineering-journal/README.md) | Learnings, decisions, queued work, and archive |
| [`.github/`](.github/PULL_REQUEST_TEMPLATE.md) | Pull request, issue, and validation workflow configuration |

Client-specific material lives in an explicit adapter directory inside the package
that needs it, never at the package root. `plugins/unifi/com.infiquetra.claude/`
is the Claude adapter; the portable manifest, skills, schemas, and scripts beside
it carry no client-specific assumption.

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
