---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: budget and proportionality at admission, as guidance

### Objective

At admission the operator records what the issue is worth and a spend budget for the run. The
budget defaults by the run's risk tier and the operator may change it. It is guidance, not a gate:
when the run's spend reaches 50% and then 100% of the budget, saga raises a notice and comments on
the issue, and the run carries on. `/plan` reports the plan's size against a target and suggests
planning a large parent's children one at a time.

### Intent

This card is card 11 of the 4 October 2026 enhancement plan, which plan.md ("Decisions added when
the plan became issues") files as a card of its own, outside the review redesign.

What is true today, at origin/main (1f7137d), with paths under `plugins/saga/`:

- Admission is asked once, at the front of a run. `scripts/admission.py` never prompts: it prints
  the questions that remain and records an answers file (`:1-28`). `/plan` puts the questions to the
  operator (`skills/plan/SKILL.md:78-188`).
- Its ten questions (`scripts/admission.py:117-160`) include the risk tier, one of low, medium, high
  or very-high with a sentence saying why (`:120`). None asks what the issue is worth or what the run
  may spend. `tests/test_admission.py:329` pins the set of ten.
- Answers land in the run record's `admission` block (`scripts/run_record.py:374-393`), documented
  in `references/run-record.md` ("`admission`", line 106).
- Spend is recorded as token counts on unit rows (`scripts/run_record.py:188-198`) and priced only
  afterwards, by `scripts/cost_report.py`. No budget exists, so nothing can warn at a share of it.
- `/plan` sizes a plan by scope class: Lightweight about 2 to 4 units, Standard about 3 to 6, Deep
  about 4 to 8 (`skills/plan/SKILL.md:228-237`). Nothing compares a written plan with a target, and
  nothing suggests planning a large parent's children one at a time.

What changes:

- Admission asks what the issue is worth and the spend budget. The budget question offers the
  default for the run's risk tier, and the operator may change it. Both answers are recorded in the
  `admission` block. An answer already in the record is never asked again (admission's existing
  rule, `:15-16`).
- When the run's spend reaches 50% and then 100% of the budget, saga raises a notice and posts an
  issue comment, rendered by `scripts/issue_progress.py` and posted through the reconcile
  controller as `/work` already does (`skills/work/SKILL.md:705-716`). Nothing stops the run.
- `/plan` reports the plan's size against its target, and for a large parent suggests planning its
  children one at a time. The report informs; it never blocks the plan.

Dependencies: none. Neighbours:

- O1 (saga mod: status band, second version) shows the budget beside the spend; this card records
  it. Either card can land first: the band leaves out a part it has no data for.
- C10b (saga: switch /code-review to the review command, with the new round and merge rules)
  removes the lens-declaration and repair-allowance questions from the same list. Both cards change
  the pinned question set and `/plan`'s question summary (`skills/plan/SKILL.md:182-187`).

### Risk

medium
It adds questions to every run's admission and posts comments on the issue, though nothing it adds
can stop a run.

### Out-of-scope / non-goals

- A budget stop or any other gate; backstop gates stay deferred (plan.md).
- Showing spend and budget in the band (O1) and the per-turn reminder (O2, saga: per-turn step
  reminder and issue update cadence).
- Cost by step and role in the cost report (O4, saga: run and review economics in the cost report).
- The admission pane mod, which answers only the staffing and lens questions
  (`com.infiquetra.claude/mods/admission-review.tsx:1-3`).

### Files expected to change

- `plugins/saga/scripts/admission.py`
- `plugins/saga/scripts/run_record.py`
- `plugins/saga/scripts/run_status.py`
- `plugins/saga/scripts/issue_progress.py`
- `plugins/saga/references/run-record.md`
- `plugins/saga/skills/plan/SKILL.md`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/tests/test_admission.py`
- `plugins/saga/tests/test_run_status.py`
- `plugins/saga/tests/test_saga_issue_progress_is_posted.py`

### Tests to add or update

- `plugins/saga/tests/test_admission.py`: the question set gains worth and budget, and the pinned
  count moves with it; the budget question offers each risk tier's default; an operator's budget is
  never overwritten by a default; a recorded answer is not asked again; a malformed budget is
  refused with exit 2.
- `plugins/saga/tests/test_run_status.py`: a run below 50% raises no notice; at 50% and at 100% the
  view reports the crossing once each; a run with no budget reports none.
- `plugins/saga/tests/test_saga_issue_progress_is_posted.py`: the skill that raises the 50% and
  100% comments names a posting command, `reconcile_controller.py reconcile --op
  issue-progress-comment`, and an event `issue_progress.py` renders.

### Context library links

- `infiquetra-sdlc/docs/lifecycle/run-model.md` ("Run configuration — what is chosen before the
  work starts")

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/admission.py --issue <N> --dry-run --render tables` lists the
      worth and budget questions on a fresh record, with the budget default for its risk tier.
- [ ] The answers are written to the `admission` block and are not asked again.
- [ ] At 50% and 100% of the budget the operator sees a notice and the issue gets one comment each;
      the run is not stopped.
- [ ] `/plan` prints the plan's size against its target and, for a large parent, the suggestion to
      plan its children one at a time.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests/test_admission.py plugins/saga/tests/test_run_status.py -q --import-mode=importlib
python3 plugins/saga/scripts/admission.py --help
```

### Notes / conventions

For this card's planning step:

1. **The default budget for each risk tier** (low, medium, high, very-high). No values are given.
2. **What "worth" means and how it is written**: a sum of money, a size, or a statement.
3. **The plan-size measure and its targets.** "Size target by risk tier" is all the enhancement
   plan says; `/plan` already sizes plans by scope class in units.
4. **What raises the 50% and 100% notices, and when.** The plan does not name the component, nor
   whether the check runs on a clock, at each step, or when usage is written.
5. **Spend can undercount planning.** A session that works no unit row records no usage
   (`com.infiquetra.claude/mods/usage-capture.ts:6-10`), so planning or plan review run outside a
   unit session does not count toward the budget today. Reviewer sessions are counted: they work in a scratch copy that
   maps to no unit row, so the mod records nothing for them, and the review command (C10a, saga: one review command from change to records) writes their
   usage through `run_record.py usage add` as ordinary usage entries.
