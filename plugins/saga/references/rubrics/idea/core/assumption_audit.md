---
phases: [idea]
applicability: always
---
# Assumption Audit lens

Your focus: surface every assumption the blueprint makes — about
users, infrastructure, data, regulation, organization, time, money,
behavior — and assess which are validated vs. claimed.

Unvalidated assumptions in a blueprint compound: they become
implicit constraints in specs, hidden defaults in issues, and
silent failures in code. Catch them here, where the cost of
swapping an assumption is a paragraph rewrite, not a refactor.

## What to look for

- **User assumptions.** Does the blueprint assume users have specific
  hardware, network conditions, language, prior knowledge, support
  channels, or trust levels? Each one is potentially wrong.
- **Infrastructure assumptions.** Cloud provider, region availability,
  service-tier guarantees, third-party SLAs, backup/restore
  capabilities. Many blueprints assume "AWS works" without checking
  that the specific service is available in target regions.
- **Data assumptions.** Volume, velocity, schema stability,
  consistency model, retention requirements, regulatory class
  (PII/PHI/PCI). Wrong here = expensive rewrite later.
- **Behavioral assumptions.** "Users will X" claims. What's the
  base rate? Have we seen them do similar things before?
- **Organizational assumptions.** "We'll have a backend team
  available," "ops will own this." Is that team's headcount /
  buy-in actually confirmed, or aspirational?
- **Temporal assumptions.** "By Q3" / "in 6 months" — is that based
  on a sized estimate or a wishful target?
- **Validation status per assumption.** For each surfaced
  assumption: is it (a) validated by data the blueprint cites,
  (b) testable but not yet tested, or (c) untestable / unfalsifiable?
  The blueprint should distinguish.

## Scoring

- **10**: Every load-bearing assumption is named AND categorized
  (validated / testable / untestable). Plan for testing the
  testables exists.
- **9**: Most assumptions named; one or two slipped in implicitly.
- **8**: The big assumptions are out in the open; small ones are
  embedded but readable.
- **7**: Several material assumptions are presented as facts; needs
  a separate "assumptions" section before specs descend.
- **≤6**: Multiple critical assumptions hidden behind narrative
  voice — "users want X," "the system handles Y," "compliance
  requires Z" — without any cited basis.

## REVISE criteria

REVISE with: a specific assumption you found, the section/line that
contains it, and what category you think it falls in. Example:
"Section 4 paragraph 2 assumes users have always-on internet —
that's a behavioral + infrastructure assumption. Validated for
admin users (we have data); not validated for parents/families.
Worth surfacing as a tracked assumption."

## BLOCK only for

- A blueprint that depends on an assumption known to be FALSE
  (verifiable from data already in the blueprint or its source
  documents).
