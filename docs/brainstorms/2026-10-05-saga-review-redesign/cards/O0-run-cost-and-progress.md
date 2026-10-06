---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: see what a run costs and where it stands

### Objective

While a saga run works, the operator can see which step it is in, how far its spend has gone against
a budget set at admission, and when its issue was last updated; afterwards, the operator can see what
each step, role and review round cost. Four child cards build this, and this card closes when they
have.

### Intent

The code review redesign (#147) started from runs that spent a lot for little value, and it changes
how review works. These four cards, carried over from the 4 October enhancement plan and outside the
redesign, make any run's progress and cost visible, review or not:

- #170 (O3, saga: budget and proportionality at admission, as guidance): at admission the operator
  records what the issue is worth and a spend budget, which defaults by risk tier. At 50% and 100% of
  it saga raises a notice and comments on the issue, and the run carries on. `/plan` reports the
  plan's size against a target.
- #168 (O1, saga mod: status band, second version): the band above the prompt shows the lifecycle
  step, the code-review round, the spend against the budget, the time in the current step and the
  time since the issue was last updated. Every word still comes from `scripts/run_status.py`. It needs
  O3's budget.
- #169 (O2, saga: per-turn step reminder and issue update cadence): every operator turn in a session
  working a run carries one line naming the run, its step and the next one, and the run's issue is
  updated after plan review, after each code-review round, at every stall or restart, and every few
  hours during a long step.
- #171 (O4, saga: run and review economics in the cost report): `cost_report.py` shows what each step
  and role cost, how many code-review rounds each review used, and how its findings ended. It needs
  the redesign's records (#148) and the switch to the new review (#161).

Order: O3 before O1; O2 at any time; O4 after #148 and #161.

### Risk
medium
The children change admission, the status band, the per-turn reminder and the cost report. The highest
child risk is O3's (medium), and no child stops a run: the budget is guidance.

### Out-of-scope / non-goals

- Any change to how code review works; the review redesign (#147) owns that.
- A spending gate: a budget raises notices and never stops a run.

### Files expected to change

Each child lists its own; together they touch, among others:
- `plugins/saga/scripts/admission.py` and `plugins/saga/scripts/run_record.py` (O3)
- `plugins/saga/scripts/run_status.py` and `plugins/saga/com.infiquetra.claude/mods/run-band.tsx` (O1, O3)
- `plugins/saga/scripts/next_step_context.py` and `plugins/saga/scripts/issue_progress.py` (O2, O3)
- `plugins/saga/scripts/cost_report.py` (O4)

### Tests to add or update

None in this card; each child names its tests (for example `plugins/saga/tests/test_admission.py`,
`test_run_status.py` and `test_cost_report.py`).

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/cards-index.md` (O1 to O4)
- `plugins/saga/references/run-record.md`

### Acceptance criteria

- [ ] #168, #169, #170 and #171 are closed.
- [ ] A saga run started after they ship shows its step, its round and its spend against its budget in
      the status band, and `python3 plugins/saga/scripts/cost_report.py` reports that run's cost by
      step and role.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```
