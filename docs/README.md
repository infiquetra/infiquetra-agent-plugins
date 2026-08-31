# Documentation

## Architecture

- [Cross-vendor plugin architecture brief](cross-vendor-plugin-architecture-brief.md)
  records the research, proposed boundaries, compatibility observations, and
  decisions that remain open.

## Plans and reviews

- [UniFi and portable Fleet Core portability pilot plan](plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)
  is the first portability pilot. It has been executed and completed; the
  recorded operator decision was to stop at the ten-client compatibility matrix
  with no client-specific remediation. The plan text itself is unchanged by
  execution.
- [Document review of that plan](reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review.md)
  is preserved unmodified as incoming evidence, with its
  [validation and repair record](reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review-disposition.md)
  alongside it.
- [Mission Control portability run plan](plans/2026-08-24-mission-control-port-run-plan.md)
  is the approved run plan for the mission-control package port. It has been
  executed and completed across all implementation units under porting runbook
  v1.0.0.
- [Mission Control migration retrospective](retros/issue-9-2026-08-25.md)
  is the evidence-based retrospective of that run: what made the unattended
  execution work, every deviation with its mechanism, the lessons folded into
  runbook v1.1.0, and the upstream filing dispositions including the one
  declined proposal.
- [Agent Launcher port run plan](plans/2026-08-27-agent-launcher-port-plan.md)
  is the approved run plan for the agent-launcher package port, executed under
  porting runbook v1.1.0. Document review blocked cycle 1 with eleven findings,
  returned PROCEED in cycle 2 with two residual wording findings, and a
  closing verification pass confirmed both repaired
  ([reviews/2026-08-27-agent-launcher-port-plan-doc-review.md](reviews/2026-08-27-agent-launcher-port-plan-doc-review.md),
  [reviews/2026-08-27-agent-launcher-port-plan-doc-review-r2.md](reviews/2026-08-27-agent-launcher-port-plan-doc-review-r2.md)).
- [PR #6 independent code reviews](code-reviews/2026-08-24-pr-6-code-review-index.md)
  indexes the five review rounds that preceded the porting tools being merged,
  each preserved byte-for-byte with the revision it reviewed and its digest.
  `docs/code-reviews/` is where a code review belongs from 2026-08-24 onward;
  the 2026-08-22 per-engine reviews in `reviews/` predate that and stay put.

## Evidence

- [Agent Launcher ten-client compatibility matrix](evidence/2026-08-27-agent-launcher-compatibility-matrix.md)
  records what every installed coding-agent client did with the portable
  agent-launcher package across four stages with fingerprint-bound
  verification, with post-activation readback in
  [evidence/2026-08-27-agent-launcher-post-activation-readback.md](evidence/2026-08-27-agent-launcher-post-activation-readback.md).
- [Mission Control ten-client compatibility matrix](evidence/2026-08-30-mission-control-compatibility-matrix.md)
  records what every installed coding-agent client did with the resynchronized
  portable mission-control package across four stages with fingerprint-bound
  verification, with post-activation readback in
  [evidence/2026-08-30-mission-control-post-activation-readback.md](evidence/2026-08-30-mission-control-post-activation-readback.md).
  The plain filename always holds the current document; three retired
  generations are kept as history under descriptive suffixes — the
  2026-08-25 pair (tree `651ac28a…`), the `-pre-fingerprint-move` pair (tree
  `1f49322e…`), and the `-pre-beads-config-ladder` pair (tree `659f91f6…`) —
  while the current pair binds tree `5fc16652…`.
- [UniFi ten-client compatibility matrix](evidence/2026-08-22-unifi-compatibility-matrix.md)
  records what every installed coding-agent client did with the portable UniFi
  package, across four stages each, with the command and evidence behind every
  result. Coverage was mandatory and passing was not: a client that could not
  load the package is recorded with its reason rather than repaired. Nothing in
  it is a release gate, and no remediation follows from it without a separate
  operator decision.

Evidence documents in this public repository carry no site-identifying address,
hostname, hardware address, camera name, or credential value, and
[`scripts/check_compatibility_matrix.py`](../scripts/check_compatibility_matrix.py)
enforces that mechanically for the matrix.

That assessment is a script rather than a method to follow:
[`scripts/assess_clients.py`](../scripts/assess_clients.py) carries the ten-client
roster, the four stages, and every client quirk the pilot learned. It runs
nothing unless `--execute` is passed, removes the package's declared credential
variables from every subprocess, refuses any command that would confirm a write,
and refuses to emit a record if the assessed tree moved while it was being read.

Which package each tool acts on is a [port descriptor](../ports/README.md) under
`ports/`, one JSON file per package, rather than a constant inside the tool.

## Repository guidance

- [Public-safe Infiquetra summary](public-safe-summary.md) gives contributors
  the local rules needed for this public repository.
- [Engineering journal](engineering-journal/README.md) stores durable
  repository learnings, decisions, queued work, and archive history.

The architecture is proposed, and the first pilot has now tested it end to end.
Existing vendor plugin repositories remain authoritative: the pilot moved no
custody, and the ported packages under `plugins/` are derived artifacts pinned
to an upstream revision rather than a second writable source; the `voice`
package is authored in this repository and carries no upstream pin.
