---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: run and review economics in the cost report

### Objective

`cost_report.py` shows, from saga's run records, what each lifecycle step and each role cost (plan,
plan review, build, test, code review and repair), how many code-review rounds each review used, and
how many of each review's findings carry each outcome (blocks merge, fix later, note) and each merge
fate (fixed, dismissed, fixed now, filed, left). The operator can then see where a run's spend went
and whether later review rounds paid for themselves.

### Intent

This card is card 12 of the 4 October 2026 enhancement plan, which plan.md ("Decisions added when
the plan became issues") files as a card of its own, outside the review redesign.

What is true today, at origin/main (1f7137d), with paths under `plugins/saga/`:

- `scripts/cost_report.py` prints cost per completed unit, grouped by role and model tier
  (docstring `:1-32`). It reads the usage entries on each unit row (`:258-265`) and prices them
  from `references/model-prices.yaml` (`:54`). It prints text or `--json` and stores nothing.
- A unit counts as completed only when its build loop is green and its latest code review, in the
  `review_result.v2` shape, ended `accepted` or `cycle_cap_best_available` (`:61-65`, `:244-255`).
- A usage entry carries the model session, role, vendor, model, effort and token counts, but no
  step (`scripts/run_record.py:188-198`). Roles are staffing role names such as `worker`,
  `lens-reviewer` and `merging-worker` (`run_record.py:199-201`).
- The usage-capture mod records nothing for a session that works no unit row, such as the
  coordinator in the primary checkout (`com.infiquetra.claude/mods/usage-capture.ts:6-10`).
- Review results carry findings with an eight-value status (`scripts/review_result.py:107-117`) but
  no tokens, cost or time.

What changes:

- The report adds cost by step and by role for plan, plan review, build, test, code review and
  repair, in the text and `--json` output.
- All spend, the reviewers' included, comes from the usage entries, so nothing is counted twice.
  The review command (C10a, saga: one review command from change to records) takes each reviewer
  session's usage from the session's result and writes it through `run_record.py usage add` as an
  ordinary usage entry with the reviewer's role, skipping a session the usage-capture mod already
  recorded. It also keeps tokens, cost and time on the review
  run record, which this card does not add to the spend.
- For each review it adds the number of code-review rounds used, read from the review run records,
  and the number of findings in each outcome, read from the finding records. The outcomes are C1's
  (blocks merge, fix later, note) and the merge fates (fixed, dismissed, fixed now, filed, left).
  Today's eight-value status is not used; C10b deletes the shape that carries it.
- The existing rules stay: the dated price table and its age warning, unpriced spend named and
  never priced at zero, and the exit codes (`:22-32`).

Dependencies, and how this sits beside the review redesign (plan.md):

- Depends on C1 (saga: review records, validation and the A–F formula), which makes each review run
  record carry its tokens, cost and time, and each finding carry its outcome (blocks merge, fix
  later or note) and its fate at merge (C1 calls that field the merge outcome). This card reads
  those records.
- Depends on C10b (saga: switch /code-review to the review command, with the new round and merge
  rules), which deletes both shapes called `review_result.v2`, caps code review at three rounds, and
  changes `cost_report.py`, where the completed-unit rule reads the old shape (`:61-65`). This card
  builds on the file as C10b leaves it.
- C15 (fleet-core + saga: Langfuse review traces and outcomes at merge) owns the Langfuse view of
  what each later round added. This card is the local report from the run records.

### Risk

low
A read-only report that writes nothing; the change is new grouping and counting over existing data.

### Out-of-scope / non-goals

- The Langfuse rounds view and the posting of finding outcomes at merge to Langfuse (C15).
- Live spend in the band (O1) and the budget and its notices (O3).
- The two baseline comparisons the 4 October plan named. Their figures live in the operator's
  private notes and do not belong in this public repository; this card's scope leaves them out.
- Changing the price table, the completed-unit rule (C10b changes its reader of the old review
  shape), or what any other script records.

### Files expected to change

- `plugins/saga/scripts/cost_report.py`
- `plugins/saga/tests/test_cost_report.py`
- `plugins/saga/scripts/run_record.py` (only if usage entries record the step; planning-step item 1)
- `plugins/saga/com.infiquetra.claude/mods/usage-capture.ts` (same condition)
- `plugins/saga/references/run-record.md` (same condition)

### Tests to add or update

- `plugins/saga/tests/test_cost_report.py`: a fixture record with usage across the steps and roles
  gives the expected cost per step and per role, in text and in `--json`; a reviewer's usage entry
  counts once, under the reviewer's role, even though the review run also records its cost; a review with
  three rounds reports three; findings are counted per outcome (blocks merge, fix later, note) and
  per merge fate (fixed, dismissed, fixed now, filed, left), read from C1's finding records;
  unpriced spend in a step is marked `+ unpriced`, never added as zero; a record with no review
  reports no rounds and no findings rather than failing; the tests for cost per completed unit, as
  C10b leaves them, still pass unchanged.

### Context library links

_none_

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/cost_report.py --issue <N>` prints cost by step and by role, the
      code-review rounds used, and findings by outcome and by merge fate for that run.
- [ ] `python3 plugins/saga/scripts/cost_report.py --issue <N> --json` carries the same figures.
- [ ] Reviewer spend is counted once, from its usage entries under the reviewer's role; the cost
      recorded on review runs is never added to it.
- [ ] Spend that has no step to attribute it to is shown apart with its reason, never dropped.
- [ ] The report still writes nothing and keeps its exit codes.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests/test_cost_report.py -q --import-mode=importlib
python3 plugins/saga/scripts/cost_report.py --help
```

### Notes / conventions

For this card's planning step:

1. **How spend is attributed to a step.** Reviewer usage arrives as usage entries with the
   reviewer's role (see Intent). Usage entries carry a role but no step, and planning or plan review run outside a unit session record no
   usage. The plan names the steps but not how their spend is recorded.
2. **Which fields of C1's records the report reads.** The review figures come from C1's review run
   and finding records, wherever C1 keeps them in the run record, and not from `review_result.v2`,
   which C10b deletes. The planning step names the exact fields.
3. **The outcome list.** C1's outcomes (blocks merge, fix later, note) plus the merge fates (fixed,
   dismissed, fixed now, filed, left), each read from the finding record. Today's eight-value status
   (`review_result.py:107-117`) is not used.
4. **Review time.** The enhancement plan names cost; plan.md's review run record also carries time.
   Whether the report shows time per step is not stated.
