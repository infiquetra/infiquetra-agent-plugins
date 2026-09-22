---
phases: [spec]
applicability: always
---
# Blueprint Fidelity lens

Your focus: does this spec descend cleanly from a named blueprint
section, or does it contradict / drift from blueprint decisions?

The fidelity spine: every artifact downstream should be traceable
to its parent. Specs that quietly contradict their blueprint
produce specs-vs-blueprint divergence that costs the most to
reconcile.

## What to look for

- **Named source.** Does the spec cite its parent blueprint
  section(s)? Format ideally: "Source: Section X.Y of
  blueprint-Z" so a reader can verify the descent.
- **Decision alignment.** If the blueprint made directional
  decisions (tech stack, architecture pattern, business model,
  user workflow), does the spec align with them? Drift is fine
  if NAMED ("blueprint says X; this spec proposes Y because
  ..."). Silent drift is the failure mode.
- **Scope alignment.** Is the spec's scope a coherent subset of
  the blueprint's scope, or does it expand beyond? Expansion is
  fine if named.
- **Constraint inheritance.** The blueprint surfaces constraints
  (regulatory, technical, organizational). Does the spec inherit
  them, ignore them, or argue against them?
- **Terminology consistency.** Spec uses the same terms-of-art
  the blueprint defined? Or has it drifted to synonyms (which
  produce ambiguity at issue time)?
- **Out-of-scope correspondence.** The blueprint's "non-goals"
  and "out of scope" sections should be respected by the spec.
  If the spec quietly includes a blueprint non-goal, that's a
  fidelity violation.
- **Update freshness.** If the blueprint was updated AFTER this
  spec was started, does the spec reflect the new blueprint
  state? Stale-against-blueprint specs are common when blueprint
  evolves rapidly.

## Scoring

- **10**: Named source, decisions aligned, scope coherent,
  constraints inherited, terms consistent, fresh against latest
  blueprint version.
- **9**: Strong; one minor terminology drift or one un-cited
  inherited constraint.
- **8**: Adequate; primary descent is clean, secondary
  alignments could sharpen.
- **7**: Multiple silent drifts from blueprint — expansions of
  scope, inconsistent terminology, glossed constraints.
- **≤6**: Spec contradicts the blueprint without acknowledgment,
  or descends from no named blueprint at all.

## REVISE criteria

REVISE with: a specific drift + the blueprint section it drifts
from. "Spec proposes synchronous API; blueprint Section 4 says
'all I/O paths must be async by default for scalability.' Either
follow that, or argue for the exception explicitly."

## BLOCK only for

- Spec contradicts a blueprint ADR (Architecture Decision Record)
  without going through the ADR-supersession process. ADRs are
  the formal commitments; bypassing them is a fidelity failure
  at the level that requires a hard stop.
