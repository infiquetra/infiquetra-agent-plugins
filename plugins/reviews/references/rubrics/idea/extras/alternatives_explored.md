---
phases: [idea]
applicability: conditional
---
# Alternatives Explored lens

Your focus: did the blueprint genuinely consider real alternatives,
or did it lock onto one direction prematurely and post-rationalize?

## When you fire

Picker selects you when the blueprint contains directional decisions
(architecture choices, technology picks, business-model framing,
go-to-market approach) without an explicit "alternatives considered"
treatment.

## What to look for

- **Named alternatives, not strawmen.** Real alternatives are real
  — actual products, real competitors, viable tech stacks. A
  blueprint that lists "we considered doing nothing" or "we
  considered building from scratch in assembly" as alternatives is
  pretending to weigh options.
- **Rejection criteria, not rejection adjectives.** "Option B was
  too slow" is an adjective. "Option B's median request latency
  exceeded our 200ms target by 3x" is a criterion. Real alternatives
  analysis uses the latter.
- **Reversibility.** Does the blueprint name which decisions are
  reversible later vs. one-way doors? The latter deserve more
  alternatives analysis; the former can move with less.
- **Status quo as alternative.** Is "keep doing what we're doing
  today" treated as a real alternative, with an honest cost-benefit
  vs. the new direction? If the blueprint never engages with the
  status quo's strengths, it's not weighing alternatives.
- **Order of selection.** Was the choice made FIRST and alternatives
  retrofitted? Tells: alternatives section is short, critique of
  alternatives is one-sided, no reasoning for why the chosen option
  beat them on rejection criteria.
- **Combinatorial alternatives.** Many decisions are made jointly
  (front-end framework × backend × deployment × monitoring). Did
  the blueprint consider COMBINATIONS, or one decision at a time
  in isolation?

## Scoring

- **10**: Named alternatives, real rejection criteria, reversibility
  flagged, status quo engaged, combinatorial considerations visible.
- **9**: Strong alternatives treatment; one minor gap (e.g. status
  quo not separately addressed).
- **8**: Adequate for early blueprint; specs can sharpen later.
- **7**: Alternatives section feels retrofitted; criteria are
  adjective-level not measurement-level.
- **≤6**: Blueprint locked onto a direction with zero or strawman-
  level alternatives.

## REVISE criteria

REVISE with: a specific alternative that should have been weighed
and a measurable criterion that would have decided. "Considered Flutter
but not React Native — both fit the cross-platform mandate; the
reasoned trade-off (e.g. team's prior experience, native-feeling on
iOS, build complexity) isn't shown."

## BLOCK only for

- Blueprint declares a one-way-door decision (e.g. data architecture
  for a regulated industry) with NO alternatives analysis. The
  reversibility cost is too high to skip the work.
