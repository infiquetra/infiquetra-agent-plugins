---
date: 2026-08-25
kind: doc-review
target: docs/brainstorms/2026-08-25-voice-plugin-requirements.md
reviewed_revision: a8fa3b94df5131fe4b0c25c8d2f84485d9ae646b
branch: orch/voice-plugin-ideation
classification: requirements
blocked: false
cycles: 2
---

# Doc Review — Voice Plugin Requirements

**Verdict: READY. Eleven validated findings (five P2, six P3), all repaired in place; no P0/P1 at any cycle, and the cycle-2 re-pass of every affected area is accepted.**

## Review result

| field | value |
|-------|-------|
| target | `docs/brainstorms/2026-08-25-voice-plugin-requirements.md` |
| reviewed revision | `a8fa3b94df5131fe4b0c25c8d2f84485d9ae646b` (frozen by operator; findings raised against this exact commit) |
| branch | `orch/voice-plugin-ideation` |
| classification | requirements (path tie-breaker: `docs/brainstorms/`) |
| rubric phase | idea (core four applied; six extras applied by judgment) |
| evidence document | `docs/ideation/2026-08-25-voice-plugin-ideation.md` (provenance only, never edited) |
| blocked | false — no P0/P1 findings in cycle 1 or cycle 2 |
| cycles run | 2 (cycle 2 accepted all affected areas) |
| artifact | `docs/reviews/2026-08-25-voice-plugin-requirements-doc-review.md` |
| override rationale | none needed |
| linked issue / plan / work-session | none — this run is scoped to review and repair only |

The reviewed commit merges `origin/main` (ef04797) into the Voice branch, so the review base is current repository truth. Repairs were applied to the working tree on top of the reviewed revision and are committed on the same branch; the reviewed revision itself is unchanged.

## Readiness summary

The document can safely drive planning. Its problem framing names a specific operator and affordance gap, its key decisions carry recorded rejections, and its assumption discipline (named dependencies, an accepted unknown, a stated residual, a durability view) is well above the rubric bar.

What it carried into review were evidence-hygiene defects, not design defects: five journal anchors shifted by the very merge under review, two load-bearing external verification claims with no durable record, one unbacked number, and three traceability gaps between the document and the ideation it consumes. All eleven were validated against the document, the ideation evidence, or repository source before repair, and all eleven were repaired.

An implementing agent following the repaired document literally no longer lands on a stale anchor, an untraceable "verified evidence" claim, or a binding journal rule with no requirement carrying it.

## Findings

All findings validated before repair; dispositions preserved from cycle 1 through cycle 2 with no renumbering.

| id | priority | anchor (at reviewed revision) | validation verdict | disposition | summary |
|----|:--------:|-------------------------------|--------------------|-------------|---------|
| D1 | P2 | Sources and Research — five journal line citations | valid — merge added +391 lines to DECISIONS.md and +83 to LEARNINGS.md; every stale anchor is displaced by exactly that delta (357→748, 426→817, 385→468, 488→571, 104→187), and each true entry was verified at its new anchor | repaired | Five journal anchors pointed at unrelated entries after the origin/main merge |
| D2 | P2 | Key Decisions — first paragraph, Herdr substrate | valid — "roughly seventeen clients" appears nowhere in the ideation or repository evidence; the document's own cited brief carries a ten-client table | repaired | Unbacked quantitative claim carrying a key decision's justification |
| D3 | P2 | Scope Boundaries — MCP listening tool item | valid — no record of the three specifics anywhere durable (`docs/evidence/`, journal, brief); the Hermes clause is fairly supported by the brief's compatibility table | repaired | "Verified evidence" claimed for specifics with no archived record |
| D4 | P3 | frontmatter `source` line | valid — R30 descends from survivor 5's custody argument verbatim; the deferred blocked-session-alert item descends from survivor 6 | repaired | Source list consumed survivors 5 and 6 without naming them |
| D5 | P3 | Scope Boundaries — response-length item | valid — R5 inverts survivor 3's producer-authored closer mechanism and the document nowhere recorded the divergence | repaired | Silent divergence from ideation survivor 3 |
| D6 | P3 | Key Decisions — response-length paragraph | valid — "three forms" never enumerated; R8, R9, R14 are the document's only stop mechanisms | repaired | Ambiguous enumeration of the stop control's three forms |
| D7 | P3 | Acceptance Examples — section head | valid — eight AEs cover 15 of 33 requirements; the section never stated its relation to the R33 acceptance gate | repaired | AE set's role versus the full acceptance gate unstated |
| D8 | P2 | Requirements — Packaging and validation group | valid — frontmatter claimed survivor 4 (lease discipline) and Sources cited the stdin/deadline journal rule as binding, but no requirement carried either | repaired — added R32; old acceptance requirement renumbered R32→R33 with no cross-references affected | Binding subprocess-discipline rule grounded but never required |
| D9 | P2 | R20 | valid — ideation survivor 1 specifies four declaration fields including "the *name* of any credential environment variable, never its value"; R20 listed three | repaired | Provider declaration dropped the credential-variable-name field, weakening R22 preflight for credential-gated providers |
| D10 | P3 | Sources — Claude Code hooks documentation entry | valid — load-bearing for Key Decision 2, R1, and R5; cited by source name only, no durable capture in the repository | repaired — epistemic status note added; archiving the excerpts themselves is owed by planning | External documentation citation carried no durable record |
| D11 | P2 | Dependencies — Herdr paragraph | valid — join keys, send-keys no-submit semantics, and the prompt/send-keys guard asymmetry are load-bearing, claimed live-verified, and have no archived record | repaired — archival status and an explicit planning re-confirmation obligation added | Herdr live-verification claims carried no durable record |

### Repair notes for the non-obvious dispositions

D1's repair rewrote the five anchors to DECISIONS.md:748, LEARNINGS.md:468, DECISIONS.md:817, LEARNINGS.md:571, and LEARNINGS.md:187 — each verified as the exact entry the citation described. The drift's arithmetic (+391/+83, confirmed via `git diff ec945e2 a8fa3b9 -- docs/engineering-journal/`) proves the citations were accurate pre-merge and stale at the reviewed revision.

D8's repair is the only structural change: new R32 ("Every subprocess Voice starts runs with its standard input explicitly closed and a deadline attached") restates the journal rule the document already cited, and the former R32 acceptance gate moved to R33. No flow, AE, or prose reference pointed at old R32, verified by search.

D3, D10, and D11 were repaired by making evidence status explicit, not by deleting claims: each decision stands, and the repaired text says what was verified at decision time and what is not archived here.

## Invalid candidates (validated and rejected, no repair)

| id | candidate | reason invalid |
|----|-----------|----------------|
| N1 | The fleet-core precedent contradicts R30 (fleet-core carries a PROVENANCE.json) | The precedent sentence is scoped to "skill-less, scripts-only, no port descriptor" — all verified true. fleet-core's manifest exists because fleet-core is a derived package; `check_provenance_manifests` states verbatim that a package with no manifest is not an error because an authored package has no upstream to pin, and `check_port_descriptors` validates only descriptors that exist. |
| N2 | R5 "speaks exactly the text" contradicts R6/R7 cleaning | R5's own exclusion list covers length and parsing operations only; R6/R7 are separate additive requirements. A literal read produces no conflict. |
| N3 | R30 settles ideation open decision 2 without a recorded custody decision | Settling an ideation open question is the brainstorm phase's function; R30 states the decision explicitly and it was verified against `scripts/check_repo.py`. |

## Applied fixes

| finding | edit made to the target document |
|---------|----------------------------------|
| D1 | Five journal anchors rewritten to their verified post-merge locations |
| D2 | "Roughly seventeen clients" sentence replaced with the grounded claim (Herdr as the repository's recorded vendor-independent execution boundary); brief Sources entry extended with :61-63 |
| D3 | MCP item restated: evidence verified at decision time but not archived; Hermes clause grounded on the brief's compatibility table |
| D4 | Frontmatter source list now names survivors 1, 2, 4, 5, 6, 7 with their contributions |
| D5 | Response-length deferred item records the deliberate divergence from survivor 3, per R5 |
| D6 | The three stop-control forms enumerated: in-pane stop key (R8), barge-in through the record toggle (R9), Herdr-wide `voice stop` keybinding preflight (R14) |
| D7 | Acceptance Examples intro states the set's role and defers completeness to the R33 gate |
| D8 | R32 added; old R32 renumbered R33 |
| D9 | R20 declaration gains the credential environment variable name (never the value), per ideation survivor 1 |
| D10 | Sources entry states the citation is name-only and directs archival before implementation relies on the field semantics |
| D11 | Dependencies states the Herdr confirmations are unarchived live-session results and obligates planning to re-confirm each |

## Rubric review record (idea phase, inline)

Core rubrics applied: `assumption_audit`, `devils_advocate_blueprint`, `internal_consistency`, `problem_framing`. Extras applied by judgment: all six (`alternatives_explored`, `binding_constraint`, `falsifiability`, `incentive_audit`, `prior_art_check`, `stakeholder_coverage`) — the document makes directional decisions, discusses multiple constraints, carries big directional claims, engages prior art heavily, and names four actor classes.

| rubric | cycle 1 | cycle 2 (affected areas) |
|--------|:-------:|:------------------------:|
| assumption_audit | 8 | 9 |
| devils_advocate_blueprint | 9 | 9 (untouched) |
| internal_consistency | 8 | 9 |
| problem_framing | 9 | 9 (untouched) |
| alternatives_explored | 9 | untouched |
| binding_constraint | 8 | untouched |
| falsifiability | 8 | untouched |
| incentive_audit | 9 | untouched |
| prior_art_check | 10 | untouched |
| stakeholder_coverage | 9 | untouched |

No rubric BLOCK condition was met in either cycle. Cycle 1 findings from the rubric pass and the readiness-skeptic pass were merged into the single D-series above; none were reclassified between passes.

## Engine offer (report-only)

`engine_offer.py offer --stage doc-review` returned `prompt_required: true`, intent `second-opinion`, advisory only. No external-engine panel was dispatched: the operator designated this session as the external reviewer for the run, so the offer is recorded and report-only per the run instructions.

## Residual risk from limited evidence

The Claude Code hooks documentation claims (Stop event, `last_assistant_message` semantics, asynchronous execution, plugin-root hooks) and the Herdr CLI claims (send-keys no-submit, prompt/send-keys guard asymmetry, join keys, the R14 keybinding's documentation status) rest on external documentation or live-session verification that is not reproducible from this repository. The repaired document now says so explicitly and assigns re-confirmation to planning.

Two prior-art specifics could not be traced to the ideation and sit outside this run's containment boundary: claude-interface's "window locator file" and "terminal-detection branch" (Key Decisions), and LifeOS's five-hundred-character whole-message rejection (Sources). Both are motivational prose about rejected or deferred prior art, not load-bearing for implementation, so they were recorded here rather than raised as findings.
