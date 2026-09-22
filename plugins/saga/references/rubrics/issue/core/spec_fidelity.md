---
phases: [issue]
applicability: always
---
# Spec Fidelity lens

Your focus: does this issue actually serve a named spec, or has it
drifted into work the spec didn't authorize?

The fidelity spine continues here. Issues that don't trace back to
specs produce code that doesn't trace back to outcomes — work
shipped without a way to know if it helped.

## What to look for

- **Named spec.** Does the issue cite its parent spec? Format
  ideally: "Spec: [link to spec.md]" so a reader can verify
  descent.
- **AC ⇄ spec AC mapping.** Does each issue AC trace to a spec
  AC (or a clear sub-component of one)? Issue ACs that don't
  appear in any spec AC are scope creep.
- **Outcome alignment.** Does the issue's work move the spec's
  outcome metric, or does it move some adjacent metric? Common
  drift: spec optimizes for X, issue optimizes for Y because Y
  is easier to measure.
- **Scope subset.** Is the issue a coherent subset of the spec's
  scope, or has it expanded? Expansion is fine if EXPLICITLY
  acknowledged ("this issue extends the spec to also cover...").
- **Constraint inheritance.** The spec inherited constraints
  from its parent blueprint. Does the issue inherit them too?
  Often issues that descend from late-stage specs lose the
  upstream constraints in transit.
- **Definition consistency.** Does the issue use the same
  terms-of-art the spec defined? Drift to synonyms causes
  reviewer-vs-implementer divergence at PR time.
- **Spec freshness.** If the spec was updated AFTER the issue
  was filed, does the issue reflect the spec's current state?
  Stale-against-spec issues are common.
- **Out-of-spec hidden.** Does the issue smuggle in work that
  the spec EXPLICITLY excluded? Specs have non-goals; issues
  shouldn't quietly include them.

## Scoring

- **10**: Named spec, ACs map cleanly, outcome aligned, scope is
  a coherent subset, constraints inherited, terms consistent,
  fresh against spec.
- **9**: Strong; one minor terminology drift or one AC slightly
  expanded.
- **8**: Adequate; primary descent clean, secondary alignments
  could sharpen.
- **7**: Multiple silent expansions or one un-cited constraint
  loss.
- **≤6**: Issue contradicts the spec without acknowledgment, or
  descends from no named spec at all.

## REVISE criteria

REVISE with: a specific drift + the spec section it drifts from.
"Issue AC #3 says 'admin sees usage chart on home screen.'
Spec scope (section 4) is server-side data aggregation only;
UI is explicitly out-of-scope until a follow-up spec. Either
remove this AC or escalate to amend the spec."

## BLOCK only for

- Issue descends from a SPEC the team has never written. The
  fidelity chain is broken at the issue→spec link.
- Issue contradicts a spec AC outright.
