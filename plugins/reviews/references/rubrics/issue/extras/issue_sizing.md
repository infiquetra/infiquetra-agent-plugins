---
phases: [issue]
applicability: conditional
---
# Issue Sizing lens

Your focus: is this issue right-sized for ONE PR? Too small =
overhead exceeds the change; too big = unwieldy review and high
abandonment rate.

## When you fire

Picker selects you when the issue's body suggests scope concerns
(many ACs, multiple components, "and also..." patterns) or when
the title is broad enough to imply >1 PR.

## What to look for

- **One-PR rule of thumb.** Can a single agent open a single PR
  in <1 day of focused work and have a competent reviewer
  approve it? If yes: well-sized. If no: too big.
- **Component count.** How many distinct files/areas does this
  issue touch? Spanning many areas usually means many concerns
  bundled. Generic guideline: 3-8 file changes is typical;
  >15 is usually multi-issue-in-disguise.
- **AC count.** 4-7 ACs typical; <3 often under-specified; >8
  usually over-bundled.
- **Cross-component coupling.** If the issue spans frontend +
  backend + database + ops, that's 4 disciplines. Splitting by
  component often reduces cycle time and per-PR review cost.
- **Refactor + feature.** Issues that mix refactoring with
  feature work are often badly-sized. Refactor PRs and feature
  PRs review differently; bundling them produces PRs that are
  hard to evaluate.
- **Test coupling.** Does the issue require establishing new
  test infrastructure? If yes, that's often a separate issue
  (the infra) before this one (the feature using it).
- **Migration-shaped.** Issues that include data migration are
  almost always too big for one PR. Migrate first, then add
  feature; two issues, two PRs.
- **Time-of-day to ship.** Some issues touch riskier production
  surface (auth, billing, data writes). Right-sizing for these
  means smaller scope so review burden is concentrated where it
  helps most.

## Scoring

- **10**: One PR, single component, 4-7 ACs, <1 day focused work,
  feature-only or refactor-only.
- **9**: Strong sizing; one minor scope item could split.
- **8**: Adequate; the issue is bounded, sizing is approximate.
- **7**: Issue spans 2-3 distinct concerns; would benefit from
  splitting but could be implemented as-is.
- **≤6**: Issue requires multiple PRs or coordinated rollout —
  must be split before agent picks it up.

## REVISE criteria

REVISE with: a specific split suggestion. "Issue covers (a) new
endpoint, (b) DB schema migration, (c) frontend integration.
Suggest splitting:
- Issue 1: schema migration + tests (no API surface change)
- Issue 2: new endpoint (using migrated schema)
- Issue 3: frontend integration (using new endpoint)
This reduces per-PR review burden and lets us pause between
phases if any of them surfaces problems."

## BLOCK only for

- Issue is so large it's effectively a spec ("implement the
  admin dashboard"). Hand back to spec phase to decompose, OR
  decompose at issue phase before picking up.
