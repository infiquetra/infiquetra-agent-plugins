---
phases: [issue]
applicability: conditional
---
# Prerequisite Mapping lens

Your focus: what other issues / PRs / external work must complete
BEFORE this issue can be planned, and what work does THIS issue
unlock once it's done?

Issue-level analog of spec's `dependency_mapping`. Issues without
prerequisite-mapping start prematurely (agent picks up an issue,
plans for hours, only to discover an upstream issue isn't merged
yet) or block other issues without alerting their owners.

## When you fire

Picker selects you when there are >1 in-flight issues in the same
repo, OR when the issue references components / abstractions that
might not exist yet, OR when the issue is part of a broader
multi-issue effort.

## What to look for

- **Upstream issues / PRs.** Does this issue depend on another
  issue being closed or another PR being merged first? Each
  upstream is a "we wait for X" risk. The dependency should be
  named explicitly with the issue/PR number.
- **Downstream issues.** What other issues, when this closes,
  unblocks? Surfacing this prevents accidental delays — the
  downstream owner can prepare while we're working.
- **External prereqs.** Third-party action (vendor approval,
  partner integration, cloud account provisioning, secret
  rotation, security review). These are often un-tracked.
- **Schema / API prereqs.** If this issue uses a data shape or
  API contract that's still in flux (parent spec under
  iteration, or a related issue defining the schema), wait for
  the schema to stabilize first.
- **Infrastructure prereqs.** New CI runner, new monitoring
  dashboard, new secret in vault, new VPC subnet. These often
  need ops involvement and pre-arrival.
- **Team prereqs.** Does this issue require a specific person /
  reviewer / specialist? If yes, are they available? Issues
  that need a specific reviewer who's on PTO will stall.
- **Reverse coupling.** Issue creates a prerequisite for other
  work — "after merging this, downstream issues #X #Y need to
  update their data fetches." This is a coordination cost.
- **Implicit timing.** Some issues are time-sensitive (close
  before quarter-end, before a specific feature flag flips,
  before a customer demo). Time pressure is a prerequisite of
  sorts.

## Scoring

- **10**: Upstream + downstream + external + infra + team
  prereqs all named with concrete references (issue numbers,
  PR numbers, dates).
- **9**: Strong; one minor prereq glossed.
- **8**: Adequate; primary prereqs surfaced.
- **7**: Issue names some prereqs but misses the critical path
  or external risks.
- **≤6**: Issue presented as standalone when it has material
  upstream coupling. Agent will hit a wall during planning.

## REVISE criteria

REVISE with: a specific missed prerequisite + impact. "This
issue uses the new auth context shape, but issue #47 (the
auth-migration) is still in 'In Progress.' Either explicitly
depend on #47 closing first, or explicitly target the legacy
auth shape to decouple."

## BLOCK only for

- Issue has hard upstream dependency that's unscheduled or
  blocked itself, AND issue's timeline cannot tolerate the
  resulting wait. Don't pick up.
