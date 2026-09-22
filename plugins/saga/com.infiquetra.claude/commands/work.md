---
name: work
description: Execute an approved Infiquetra plan to PR-ready, then own the round-N PR continuation loop with saga state, risk-gated tests, a hard review gate, and merge under explicit confirmation
argument-hint: "[plan path or issue]"
---

Load `saga/skills/work/SKILL.md`. Execute from a durable plan artifact or a handoff issue
marked `plan-ready` or `resume-ready`.

`/work` is the saga's **primary writer**: it restores on resume, mints/advances the work-thread saga to
`lifecycle_phase=work`, writes a tick per phase, and names that saga identity into the programmatic
`/code-review` call so the review's `review_paths` append lands on the exact thread.

It runs the **build loop**: implement, then run the exit criterion the run record already holds — the
mechanical baseline, the plan's child-scoped functional checks, the branch preview where the repository
declares one, and the plan's scenario smoke — repeating until every part is green, then handing the exact
revision it went green at to `/code-review`. A failing check is a loop iteration, never a refusal. The
criterion's contract is `plugins/saga/references/mechanical-baseline.md`. It then owns the **round-N PR
continuation loop** (re-reads live PR state and runs the transition table on re-entry), treats Code
Review's typed `outcome` as the sole
acceptance decision, and separately blocks a stale review as a freshness check.

The pull-request open, the review request, and the merge each stay **explicitly operator-confirmed** —
never silent — though the ship ceremony that used to carry them was removed in #1027 and the merge turn
itself belongs to the integrate step. `/work`
does **not** own deploy or canary (`deploy`), does **not** file SDLC issues (`mission-control`),
and does **not** advance `lifecycle_phase` past `work` (the `qa` advance is deferred to the `/qa`
rebuild). Update issue progress through `mission-control`, write `docs/work-sessions/` summaries, and do not
close or move the issue until acceptance criteria and the selected destination are satisfied.

Arguments provided to the command:

`$ARGUMENTS`
