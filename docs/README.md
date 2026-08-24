# Documentation

## Architecture

- [Cross-vendor plugin architecture brief](cross-vendor-plugin-architecture-brief.md)
  records the research, proposed boundaries, compatibility observations, and
  decisions that remain open.

## Plans and reviews

- [UniFi and portable Fleet Core portability pilot plan](plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)
  is the first portability pilot. It has been executed and is paused for an
  operator decision per client; the plan text itself is unchanged by execution.
- [Document review of that plan](reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review.md)
  is preserved unmodified as incoming evidence, with its
  [validation and repair record](reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review-disposition.md)
  alongside it.

## Evidence

- [Ten-client compatibility matrix](evidence/2026-08-22-unifi-compatibility-matrix.md)
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
custody, and the packages under `plugins/` are derived artifacts pinned to an
upstream revision rather than a second writable source.
