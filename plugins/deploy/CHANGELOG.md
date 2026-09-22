# Changelog

## [0.2.2] - 2026-09-20

### Changed

- **The release orchestrator no longer defers broader validation to `team-execution`.** That plugin
  was archived by issue #1030, and what it provided for a release — reviewer consensus and named
  scanners — is now the lensed code review and the build loop's mechanical baseline. The agent's
  instruction named a plugin that will not resolve, which reads as a missing dependency rather than
  a retired one; it now names what actually performs the validation.

## [0.2.1] - 2026-08-08

### Added - house-style presentation contract on the release orchestrator (#704)

- `release-orchestrator` agent definition gains a "Presentation contract (Infiquetra house style)" section, copied verbatim from `plugins/house-style/references/subagent-presentation-preamble.md`.

## [0.2.0] - 2026-07-12

### Added - acceptance step at saga handoff boundary, gate-or-auto authorization gating (#395)

- `deploy-state` skill gains "Accepting a saga handoff" section: operators run `deploy_handoff.py
  accept` before promotion on behalf of a saga-tracked item, honoring the gate-or-auto payload read
  from the offer (gate -> blocked pending explicit confirmation, auto -> authorized for
  nonprod only, staging/production always require confirmation regardless of payload). The rule is
  implemented mechanically as `authorize_promotion` on the saga side (KTD5), not
  by deploy convention.
- `deploy.md` command docs gain acceptance step in Instructions, guiding users to run the ack before
  proceeding with promotion (R6, U4).
- Minor version bump reflects new acceptance behavior contract at the saga boundary (previously
  0.1.4: no handoff acceptance path existed).

## [0.1.4] - 2026-07-05

- `release-orchestrator` agent: add validated `effort: high` frontmatter field, consuming the
  fleet effort convention (#363) — release coordination warrants deliberate reasoning; proves
  the effort vocabulary applies fleet-wide.

## [0.1.3] - 2026-07-05

- Reformat CHANGELOG headings to the fleet's canonical grammar (bracketed version, hyphen-minus
  date) as part of the release-surface single-source generator work (#429).

## [0.1.2] - 2026-06-21

- `release-orchestrator` agent: pin `model: sonnet` in frontmatter (R1/R2a tiering;
  release coordination is structured/procedural — Sonnet is the right cost-quality tier).

## [0.1.0] - 2026-05-29

- Add Infiquetra tag-promotion deploy commands and deploy-state skill.
- Add release orchestrator guidance for rollback, hotfix, status, and release notes.
- Add deterministic helpers for tag naming, deployment status drift, and release-note preview.
- Preserve VECU deploy safety mechanics source-neutrally: version inference, hotfix refs,
  rollback tags, existing-tag rejection, dry-run protection, and unhealthy snapshot quarantine.
