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

Three portable plugin packages have been ported and assessed across all ten
coding-agent clients installed on the operator's machine:

1. **`unifi` pilot** — The first portability pilot ported the Claude Code
   `unifi` plugin into a portable Agent Plugins 1.0 package together with an
   initial vertical slice of Fleet Core. Completion is recorded by the pilot
   [retrospective](docs/engineering-journal/narratives/2026-08-23-unifi-portability-pilot-retrospective.md)
   and by [porting runbook v1.0.0](docs/runbooks/portable-plugin-port.md). The
   recorded operator decision was to stop at the completed ten-client
   compatibility matrix and take no client-specific remediation
   ([`DECISIONS.md`](docs/engineering-journal/DECISIONS.md), 2026-08-22).
2. **`mission-control` package** — Ported under the same runbook
   ([`docs/runbooks/portable-plugin-port.md`](docs/runbooks/portable-plugin-port.md) v1.0.0)
   and approved run plan
   ([`docs/plans/2026-08-24-mission-control-port-run-plan.md`](docs/plans/2026-08-24-mission-control-port-run-plan.md)),
   delivering a 71-file portable package derived from upstream commit `3b2b7083`
   (version 2.15.2) in `infiquetra-claude-plugins`, with 391 ported tests in
   continuous integration, the validation rule audit, and a full ten-client
   compatibility assessment.
3. **`agent-launcher` package** — Ported under runbook
   [v1.1.0](docs/runbooks/portable-plugin-port.md) and the approved run plan
   ([`docs/plans/2026-08-27-agent-launcher-port-plan.md`](docs/plans/2026-08-27-agent-launcher-port-plan.md)),
   delivering an 11-file portable package derived from upstream commit
   `8269f84b` (version 1.0.0, the shared single-session launch contract
   accepted in `infiquetra-claude-plugins` issue #777) with a target-owned
   portable contract suite, the packaging smoke and rule-audit guards, and a
   full ten-client compatibility assessment.

Custody did not move. Existing vendor repositories remain the runtime sources of
truth. The *ported* packages under [`plugins/`](plugins/) are derived artifacts:
each is generated from a pinned upstream commit and checked file by file against
its own SHA-256 provenance manifest. A derived package is never a second writable
source, and it is never hand-maintained. A package authored in this repository —
`voice` is the first — carries no upstream pin and no provenance manifest, and is
maintained here directly.

Key facts about the current state are verified by the repository's own tests
and committed evidence:

- **Both UniFi client entrypoints run.** Each client script is classified in
  [`plugins/unifi/PROVENANCE.json`](plugins/unifi/PROVENANCE.json) as a
  `deterministic-transform` output of the versioned
  `resolve-bundled-fleet-module` rule, with a stamped build-time Fleet Core
  bundle in the `_bundled/` directory beside it.
  [`tests/test_client_entrypoints.py`](tests/test_client_entrypoints.py) runs
  both shipped scripts with no credentials and no network, asserts each answers
  `--help`, and fails when the bundle is removed.
- **UniFi ten-client assessment: none failed.** The
  [UniFi ten-client compatibility matrix](docs/evidence/2026-08-22-unifi-compatibility-matrix.md)
  records nine clients working directly and one, OpenAI Codex, working through
  an adapter: zero failed, zero unsupported. The adapter status is current fact
  — Codex's marketplace is its only placement path and holds no supported
  manifest, and the identified adapter, a Codex marketplace manifest, was not
  built here. Cursor Agent works directly; the matrix records why its earlier
  failure reading was an artifact of the assessment's isolation rather than a
  result of the client.
- **Mission Control ships 71 portable files and 391 CI tests.** Pinned to
  `3b2b7083` (v2.15.2), the package provides seven Agent Skills (`board`, `flow`,
  `issues`, `labels`, `metrics`, `milestones`, `rollout`), the shared CLI
  (`scripts/sdlc_manager.py`), board census, pagination, template sync, and
  executor profile lint entrypoints. Twenty-eight test files (391 tests) live
  inside the package under [`plugins/mission-control/tests/`](plugins/mission-control/tests/)
  under provenance custody and run in CI on `python>=3.12`. The validation rule
  audit ([`docs/plans/2026-08-24-mission-control-port-u7-phase2-rule-audit.md`](docs/plans/2026-08-24-mission-control-port-u7-phase2-rule-audit.md),
  [`tests/test_mission_control_rule_audit.py`](tests/test_mission_control_rule_audit.py))
  audits validation rules class-first against live authority.
- **Mission Control ten-client assessment: 3 directly, 7 via adapter, 0 failed.**
  The [Mission Control compatibility matrix](docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md)
  records:
  - 3 work directly (Cursor Agent, Qwen, and Agy: placed, discovered, loaded,
    and ran all entrypoints cleanly; Qwen ran through its real binary supplied
    by exported override).
  - 7 work through an adapter (Claude Code, OpenAI Codex, Grok, OpenCode,
    Gemini CLI, Muse, Hermes). The four skill-scoped clients (OpenCode, Gemini
    CLI, Muse, Hermes) fully consume the seven skill units with zero diagnostics,
    while package-root entrypoint scripts sit outside the skill tree.
  - 0 failed, 0 unsupported.
  - Evidence is bound to the package fingerprint by
    [`scripts/check_compatibility_matrix.py`](scripts/check_compatibility_matrix.py),
    with post-activation readback in
    [`docs/evidence/2026-08-30-mission-control-post-activation-readback-post-fingerprint-move.md`](docs/evidence/2026-08-30-mission-control-post-activation-readback-post-fingerprint-move.md)
    and 0 survivors across 68 anchors in mutation proof
    [`docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt`](docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt).
- **Agent launcher ships the shared launch contract as one entrypoint.** Pinned
  to `8269f84b` (v1.0.0), the package provides one Agent Skill
  (`agent-launcher`) over the byte-copied contract script
  ([`plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py`](plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py)):
  create one session through the installed `agents` wrapper, verify it through
  Herdr, deliver a prompt, and close only a session the launch proved it owns.
  The upstream skill and README are superseded by target-owned portable docs —
  the upstream skill's Claude-runtime discovery ladder never crosses the port
  boundary — and the upstream test suite's remaining repo-wide premises are
  dropped with a recorded reason; the target-owned suite under
  [`plugins/agent-launcher/tests/`](plugins/agent-launcher/tests/) re-proves
  the portable contract on `python>=3.12`.
- **Agent launcher ten-client assessment: 7 directly, 3 via adapter, none
  failed.** The
  [agent-launcher compatibility matrix](docs/evidence/2026-08-27-agent-launcher-compatibility-matrix.md)
  records:
  - 7 work directly (Cursor Agent, Qwen, OpenCode, Gemini CLI, Muse, Agy,
    Hermes), the four skill-scoped clients among them placing the single skill
    unit.
  - 3 work through an adapter (Claude Code session-scoped through the
    local-plugin flag; OpenAI Codex on the marketplace manifest it names and
    this package does not ship; Grok placed, discovered, and loaded cleanly
    with its install trust supplied, while its invocation stayed blocked
    because the harness's capture did not resolve the client-generated plugin
    id into its command template).
  - 0 failed, 0 unsupported. The single entrypoint answered `--help` from
    every client-resolved copy, credential-free, on the floor interpreter.
  - Evidence is bound to the package fingerprint, with post-activation
    readback in
    [`docs/evidence/2026-08-27-agent-launcher-post-activation-readback.md`](docs/evidence/2026-08-27-agent-launcher-post-activation-readback.md)
    and 0 survivors across 11 mutation classes in the proof
    [`docs/evidence/2026-08-27-agent-launcher-mutation-proof-portable-docs.txt`](docs/evidence/2026-08-27-agent-launcher-mutation-proof-portable-docs.txt).

What remains open is distribution, not compatibility. OpenAI Codex needs a
marketplace manifest to be reachable at all, and Cursor Agent's marketplace
accepts only a git repository URL, so a local directory is not a path there.
Whether a client warrants a repair, an adapter, a different distribution path,
or an explicitly unsupported status is an operator decision per client, and
none has been taken. No client-specific remediation has begun; the open
decisions are recorded in the journal's
[queued work](docs/engineering-journal/QUEUED.md).

The record of the work, in the order a new reader should take it:

- [Agent launcher ten-client compatibility matrix](docs/evidence/2026-08-27-agent-launcher-compatibility-matrix.md),
  [Mission Control ten-client compatibility matrix](docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md)
  and [UniFi ten-client compatibility matrix](docs/evidence/2026-08-22-unifi-compatibility-matrix.md)
  — what each client did with each package, stage by stage, with evidence.
- [Agent launcher port run plan](docs/plans/2026-08-27-agent-launcher-port-plan.md),
  [Mission Control port run plan](docs/plans/2026-08-24-mission-control-port-run-plan.md)
  and [UniFi pilot plan](docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)
  — the approved plans the work followed.
- [Cross-vendor plugin architecture brief](docs/cross-vendor-plugin-architecture-brief.md)
  — the research and proposed direction the ports test.
- [Engineering journal](docs/engineering-journal/README.md) — the decisions taken,
  the learnings produced, and the work deliberately deferred.

## Packages

| Package | Status | Description | Upstream Pin |
|---|---|---|---|
| [`plugins/unifi/`](plugins/unifi/README.md) | Ported (pilot) | Portable UniFi network and protect management | `818fd684` (v2.0.6) |
| [`plugins/fleet-core/`](plugins/fleet-core/README.md) | Ported (vertical slice) | Shared rate-limit retry, intent envelope, tier palette, and models registry | `3b5faa6c` (v0.25.2) |
| [`plugins/mission-control/`](plugins/mission-control/README.md) | Ported | SDLC management on Operations, Asgard, and CAMPPS boards | `3b2b7083` (v2.15.2) |
| [`plugins/agent-launcher/`](plugins/agent-launcher/README.md) | Ported | Shared single-session launch contract: create, verify, prompt, and owned-close one coding-agent session | `8269f84b` (v1.0.0) |

### Portable Fleet Core scope

This package carries the shared `retry_backoff` rate-limit primitive, plus the
`intent_envelope`, `tier_palette`, and `models.json` modules that mission-control
reaches. Every other module the upstream source carries is named as explicitly
unported in [`plugins/fleet-core/DEFERRED.md`](plugins/fleet-core/DEFERRED.md),
so no reader has to infer what is missing. Nothing in this repository claims
full Fleet Core parity.

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
| [`docs/plans/`](docs/plans/2026-08-24-mission-control-port-run-plan.md) | Approved implementation plans |
| [`docs/evidence/`](docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md) | Assessment records, written under the public evidence rules |
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
