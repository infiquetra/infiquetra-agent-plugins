# saga: how /plan should plan and track a program built across vendors, cards and repositories

### Research Question

How should saga's `/plan`, and the run record admission writes for it, plan and track a program like
#147: one parent issue with many child cards across several repositories, each built and reviewed by
sessions from different vendors (Claude, Muse, Grok, Codex)? The aim is for such a program to run
through saga instead of around it.

### Context

On 6 October 2026 the program plan for #147
(`docs/plans/2026-10-06-saga-review-redesign-program-plan.md`) was written with `/plan`, reviewed once by
Codex, and repaired. To work, it had to step around saga and orchestrate in seven places. Evidence is
from `main` at 113458c:

1. **One plan per issue.** Saga has no parent or program plan. Run records, sagas and plans are keyed
   per issue. The program plan's functional checks could map only to #147's own four acceptance
   criteria, not to the children's.
2. **Admission cannot record other vendors.** Staffing overrides must use the Claude tier palette and
   the role's own vendor (`plugins/saga/scripts/admission.py:868-923`). So the plan records its Muse and
   Grok builders outside the run record (KTD13 in the program plan).
3. **`/plan`'s plan review loops.** Section 5.4 re-reviews every repaired plan
   (`plugins/saga/skills/plan/SKILL.md`). C12 (#163) already makes it one pass.
4. **`/plan` continues into `/work`, whose code review cannot accept today.** Section 5.6 enters `/work`
   for every destination except `plan-only`. `/code-review` returns `review_incomplete` while the
   executor ledger is empty (`plugins/saga/scripts/review_consensus.py:2213-2216`). C10b (#161) replaces
   that review.
5. **Orchestrate cannot carry plan, review, build and review hand-offs.**
   - A unit's worktree starts from the run branch, not from the unit it waits on
     (`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py:2585-2608`).
   - `go` refuses a dependency that committed nothing (`:3634-3637`), and a review produces findings,
     not commits.
   - Fix requests route only to declared owner roles and paths (`:1662-1706`).
   - A child plan's checks attach only to rows named by its U-IDs after `expand`
     (`plugins/saga/scripts/functional_checks.py:364-393`).
   - One run covers one repository.
6. **Muse has no saga plugin.** A Muse builder cannot run `/plan`, so it follows the plan contract file
   as prose.
7. **A child saga tick would take over the run band.** The band shows the active saga's run first
   (`plugins/saga/scripts/run_status.py:327-345`). So the children save no ticks, and #147 stays
   selected.

The program plan's answer is a coordinator protocol: per-card worktrees, two persistent agent-launcher
sessions per card (a builder and a reviewer from a different vendor), a hand-off folder per card, and a
deterministic validation gate. Its pilot (#114 on Grok, #144 on Muse) produces the first evidence of how
well that works.

### Success Criteria

- Each of the seven gaps has a recommendation: change `/plan`, change admission and the run record,
  change orchestrate, or keep the coordinator protocol as documented practice. Each comes with its
  reason and the evidence it rests on.
- The recommendations use the #147 pilot's hand-off folders: which hand-offs failed or needed the
  coordinator's judgment, and how many coordinator turns each card took.
- Every accepted change is filed as a card through mission-control, with its dependencies on C12 and
  C10b stated.

### Timebox

Two days of agent work, started after the #147 pilot (U2 in the program plan) has merged both cards.

### Deliverables

- `docs/brainstorms/<date>-saga-plan-programs/findings.md`: the seven gaps, the pilot evidence, and a
  recommendation for each.
- Follow-up cards filed through mission-control under the improve-agent-plugins objective.
- A `docs/engineering-journal/DECISIONS.md` entry for the direction chosen.

### Key Questions to Answer

- Should `/plan` support a parent plan whose units are child issues, possibly in other repositories?
  If so, what does its run record hold, and how do the children's acceptance criteria map to checks?
- Should admission and the run record hold staffing per unit (vendor, model, effort), checked against
  the live rosters rather than the Claude tier palette?
- Should the per-card protocol become an orchestrate mode, a saga phase, or stay a documented
  coordinator procedure? Which of orchestrate's unit rules would have to change for each option?
- How do saga's commands reach a harness without the saga plugin, such as Muse?
- How does a parent run stay the band's selected run while its children run?
- Which gaps disappear once C12 (#163) and C10b (#161) land, and should any of this wait for them?

### Related Issues

- #147, the program this came from, and its plan `docs/plans/2026-10-06-saga-review-redesign-program-plan.md`
- #163 (C12, plan review in one pass) and #161 (C10b, the switch to the new code review)
- #159 (C9, orchestrate's reviewer transport)
- #175 (the plan viewer's wide tables), found while reading this plan

### Intent

The operator wants multi-vendor work to offload Claude usage without losing quality, and wants the
lifecycle's tools to carry it rather than a hand-built coordinator procedure. #147 is the first program
to need this. Its workarounds are written down, so this exploration starts from evidence, not
speculation.

### Target repo / surface

`infiquetra-agent-plugins`: `plugins/saga/skills/plan/`, `plugins/saga/scripts/admission.py`, the run
record (`plugins/saga/references/run-record.md`), `plugins/orchestrate/`, and `plugins/agent-launcher/`.
The deliverables land under `docs/brainstorms/`.

### Mode

explore: research and a written recommendation, not an implementation.

### Constraints

Read-only on code. It uses the #147 pilot's evidence and does not change the running program. Any
change it recommends is filed as a separate card.

### Transfer notes

Produces `docs/brainstorms/<date>-saga-plan-programs/findings.md`, a DECISIONS.md entry, and follow-up
cards under the improve-agent-plugins objective. Related to #147, #163, #161 and #159.

### Risk

low
Research only. It changes no code, and its recommendations become separate cards.
