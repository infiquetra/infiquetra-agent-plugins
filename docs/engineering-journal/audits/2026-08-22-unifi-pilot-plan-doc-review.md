# Document review of the UniFi and portable Fleet Core pilot plan

Date: 2026-08-22
Author: Codex GPT-5.6 Sol document review; validated and repaired by Jeff Cox and Claude
Scope: `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` at pull request #2 head `43b4cc8`, against `infiquetra-claude-plugins` at `995a475`, the installed Orchestrate contract, and the published Agent Plugins 1.0.0 specification
Related entries:

- [Pilot decision](../DECISIONS.md#choose-unifi-plus-a-portable-fleet-core-slice-as-the-first-portability-pilot)
- [Queued pilot item](../QUEUED.md#choose-the-first-portability-pilot-and-custody-gate)
- [Void parity baseline](../ARCHIVE.md#void-parity-baseline-recorded-in-error)

## Question

Whether the first portability pilot plan was decision-complete enough to execute, or whether an
implementer would have to invent behavior or exceed an authority boundary.

## Evidence reviewed

- Immutable incoming review artifact: [`docs/reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review.md`](../../reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review.md), SHA-256 `3d50ae5ae128d3f15fcf4750c43a747d3c8dee123369997a4584e62eb24f01e5`, 228 lines.
- Independent validation and repair record: [`docs/reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review-disposition.md`](../../reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review-disposition.md).

## Findings

- Verdict was NOT READY, blocked by ten priority-1 findings with two priority-2 findings alongside.
- All twelve were independently confirmed against primary evidence. None was refuted or narrowed.
- The failures clustered in four places: a self-contradiction about execution ownership, a
  dependency graph that no single controller run could carry, contracts promised in requirements but
  owned by no file or test, and evidence gates that proved counts rather than coverage.
- None of the repairs required a new operator decision. Every one was either a correction of the
  document to match an already-settled ruling, or an application of a standing repository rule.

## Recommendations

- Treat "which file and which test own this promise?" as a first-class planning check. Most of the
  priority-1 findings were requirements no unit's file list could satisfy, which document validation
  cannot detect because the prose reads as complete.
- Prefer deriving inventories and counts from a pinned source tree over writing them down. Both
  priority-2 findings were handwritten numbers that were wrong on the day they were written.
- When a digest attests to a file, define what the digest covers before defining where it is stored.
  A stamp inside the bytes it hashes cannot be computed.

## Follow-up

- Repairs landed on the `docs/unifi-portability-pilot-plan` branch and pull request #2.
- The plan is ready for a fresh document review; requirements grew from 29 to 45 and decisions from
  8 to 15, with no identifier renumbered.
