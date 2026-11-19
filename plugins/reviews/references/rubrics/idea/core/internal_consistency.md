---
phases: [idea]
applicability: always
---
# Internal Consistency lens

Your focus: do the blueprint's principles, claims, and decisions
agree with EACH OTHER, or do they contradict in ways that will
surface only when downstream specs try to descend from both?

Blueprints accumulate over multiple authoring sessions, often by
multiple authors. Contradictions creep in: a section claims
"prioritize speed," another claims "compliance gates everything";
a domain section says "users are admins," a use-case section
addresses families. The earlier you catch these, the cheaper to fix.

## What to look for

- **Principle conflicts.** Are stated principles internally
  consistent? If two principles point opposite directions, the
  blueprint should explicitly resolve which trumps which (with
  reasoning), not leave them both standing.
- **Definition drift.** Is a key term used consistently across
  sections? "User" might mean admin in section 2 and family in
  section 6 — that's a drift, even if neither is wrong on its own.
- **Scope drift.** Does an early section define a narrow scope and
  a later section expand it without acknowledgment? Common pattern:
  "MVP focuses on X" then chapter 8 quietly adds Y.
- **Contradictory non-functional claims.** "We will be cost-
  efficient AND highly available AND globally distributed AND
  open-source" — these aren't all simultaneously achievable for
  the budgets / team sizes most blueprints assume. Is the
  trade-off named?
- **Cross-section dependencies.** Does section A claim X based on
  section B providing Y, while section B describes a system that
  actually provides Z? Cross-references should match.
- **Contradiction between blueprint and ADRs.** If the blueprint
  cites ADRs (or vice-versa), do they actually align? An ADR that
  picked tech X while the blueprint discusses architecture
  assuming tech Y is a load-bearing inconsistency.
- **Stale claims.** Earlier sections that haven't been updated
  after a later section's decisions. "Section 3 (written month 1)
  predicts X; Section 9 (written month 3) decided NOT-X but
  Section 3 wasn't updated."

## Scoring

- **10**: All principles, definitions, scope, and cross-references
  align. Trade-offs explicitly named where they could conflict.
- **9**: Strong consistency; one minor terminology drift.
- **8**: Reasonable consistency; a couple of unrunchecked
  cross-references or one stale claim worth fixing.
- **7**: Two or more material contradictions present that downstream
  specs will trip over.
- **≤6**: Multiple sections contradict each other on load-bearing
  decisions. Specs descending from this will collapse.

## REVISE criteria

REVISE with: a specific contradiction, citing both sides. Format:
"Section X line N says: <claim A>. Section Y line M says: <claim B>.
These appear to contradict on <axis>. Which is intended, and should
the other be updated?"

## BLOCK only for

- A contradiction so severe that no spec can be written without
  picking a side, AND the blueprint expressly forbids picking a
  side. (Rare.)
