# DEBUG REPORT + learning capture + defect routing

The deliverable shapes for Phase 4. The DEBUG REPORT and its `Status` enum are GRAFTED from gstack
`investigate`. The report is **agent-consumable EVIDENCE** — a future agent reads it cold and acts on it.

---

## The DEBUG REPORT template

Write to `docs/investigations/<slug>-<date>.md` (repo-relative; `<slug>` kebab-case from the symptom or
issue). The enum'd shape:

```markdown
# DEBUG REPORT — <short symptom>

- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED
- **Date:** <YYYY-MM-DD>
- **Source:** <issue #N | test path | error | description>

## Symptom
What the user / test observed (the surface failure), with the exact error or assertion.

## Root cause
The full causal chain from trigger to symptom, **no gaps**, with `file:line` references at each step.
For any uncertain link, the prediction that was tested and its result.

## Fix
What was changed, with `file:line` — OR "diagnosis only" if Phase 3 was skipped (and why: user chose
diagnosis-only, or the proper fix is real implementation work routed to mission-control).

## Evidence
The observations that ground the root cause: instrumented boundary captures, log lines, runtime values,
the reproduction showing the fix works, full-suite result. Concrete, not "it looks fixed".

## Regression test
Path to the failing-then-passing test (or "recommended: <path + what it should assert>" when diagnosis
only). Whether existing tests should have caught this and why they did not.

## Related
Prior bugs in the same area, recurring patterns (3+ locations), architectural notes, the saga id / PR /
issue refs touched.
```

**Status enum:**

- **DONE** — root cause found, fix applied, regression test written, full suite passes, original bug
  fresh-reproduced and confirmed fixed.
- **DONE_WITH_CONCERNS** — diagnosed and (maybe) fixed, but cannot fully verify here (intermittent bug,
  needs staging, environment-dependent). State the residual concern.
- **BLOCKED** — root cause unclear after investigation (hypothesis-exhaustion or 3-failed-fix gate hit),
  escalated. State what was ruled out and what is needed to proceed.

This NEW doc is a fresh file → write it directly (it is not an edit to existing content).

---

## Journal-LEARNINGS promotion template (non-obvious root cause — gated, selective)

Promote to `docs/engineering-journal/LEARNINGS.md` **only** when the lesson is generalizable (a wrong
assumption about a shared dependency / framework / convention, or a pattern found in 3+ locations). Skip
silently for a mechanical one-off (typo, missed null) — compounding those clutters the journal. Offer
neutrally when the lesson is one sentence. A promotion is a **pure append** (per the journal rules); it
does not edit existing entries.

```markdown
### YYYY-MM-DD — <one-line lesson>

**Context:** <what was being debugged>
**Evidence:** <PR / commit / file:line — the DEBUG REPORT path>
**Mechanism:** <WHY it happened, not just what — the root-cause chain in one or two sentences>
**Fix (or queued):** <what landed, or what was routed to mission-control>
**Generalizable rule:** <the lesson stripped from the incident — the highest-value line>
**Refs:** docs/investigations/<slug>-<date>.md
```

---

## Defect-routing note (trackable confirmed defect)

When the investigation confirms a **trackable defect** that needs implementation work, open a
**defect-type SDLC issue**. `defect` is a mission-control taxonomy type. The DEBUG REPORT is evidence
the issue links. It is not the document `plan` consumes.

1. **Describe the bug in the issue.** Symptom, root cause, and the fix the bug needs. Link the DEBUG
   REPORT (`docs/investigations/<slug>-<date>.md`) as supporting evidence.
2. **Open that issue through `mission-control`** when it is available. When it is not, create the same
   issue with `gh issue create`: the title is the defect, and the body is the description from rule 1.
   When neither can open an issue, leave that description in the debug report and stop.

**The fix reaches implementation through the issue.** `plan` consumes a **plan path**, a **GitHub
issue ref**, or a **resume request**. It does **not** consume an investigation doc path. So:
`/investigate` opens the defect issue (mission-control, or `gh issue create`) and `plan` carries the
issue. An **inline trivial fix already applied + self-verified** is shipped by the operator through
reviews (the fix is on a branch; `/investigate` never pushes). A **design problem** routes to
`/brainstorm`. Route to the capability that owns the finding, never restate it. No lifecycle write.
