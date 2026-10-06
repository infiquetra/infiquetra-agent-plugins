---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga mod: status band, second version

### Objective

While a saga run is active, the one-line status band above the prompt says which lifecycle step the
run is in, the code-review round, what the run has spent against its budget, how long it has been in
the current step, and how long ago its GitHub issue was last updated. Saga's status-line entry adds
the spend. Every word still comes from `scripts/run_status.py`, so Claude Code and every other
harness show the same line.

### Intent

This card is card 9 of the 4 October 2026 enhancement plan, which plan.md ("Decisions added when the
plan became issues") files as a card of its own, outside the review redesign.

What is true today, at origin/main (1f7137d):

- The band mod renders one `band_line` per active run from `run_status.py summary --all-active`
  and never recomputes it (`plugins/saga/com.infiquetra.claude/mods/run-band.tsx:4-9`, `:174`).
  Saga's status-line entry is the issue and its phase alone (`run-band.tsx:45-49`).
- `band_line` joins the issue, the phase, the build loop's latest pass, the review cycle against
  its allowance, and how many lenses met their bar (`plugins/saga/scripts/run_status.py:719-739`).
  A part the run has no data for is left out (`run_status.py:721-723`).
- The phase is the saga envelope's `lifecycle_phase` (`run_status.py:111-131`). Its values are
  ideation, brainstorm, plan, review, work, qa and retro (`plugins/saga/scripts/saga.py:78`), and
  the skills set only `plan` and `work` (`skills/plan/SKILL.md:651`, `skills/work/SKILL.md:324`
  and `:647`). Plan review and the test step therefore never show as steps.
- The review cycle shows as `k/3`, or `k/5 (escalated)` past the standard allowance
  (`run_status.py:557-558`, `:706-716`).
- The usage-capture mod writes each unit session's token counts into the run record every minute
  (`mods/usage-capture.ts:1-27`). `scripts/cost_report.py` prices them from
  `references/model-prices.yaml` (`cost_report.py:54`), but nothing shows spend while a run is under way.

What changes:

- `run_status.py` adds to each run's row, and to `band_line`: the step, the code-review round,
  spend so far priced the way `cost_report.py` prices it, the budget when one is recorded, time in
  the current step, and the age of the last GitHub update. The view's fields are declared in
  `types/index.d.ts` (`SagaRunStatus`, `:100-112`).
- The band mod shows the new line; the status line adds the spend.
- Spend that cannot be priced is marked, never counted as zero (the rule in `cost_report.py:22-26`).
  A price table that cannot be read leaves the spend part out and keeps every other part.

Dependencies:

- Depends on O3 (saga: budget and proportionality at admission, as guidance) for the budget field,
  which O3 records and this card only reads. Until O3 lands, the band leaves the budget out under
  the existing rule above.
- Shows the round as "round k of 3" once C10b (saga: switch /code-review to the review command, with
  the new round and merge rules) lands, because C10b sets the three-round limit. Until then, today's
  records allow five cycles (item 4 of this card's planning-step notes).
- Shares `run-band.tsx` with C14 (saga mods: review pane, merge confirmation, run band and setup
  pane), which adds the review state and a status-line entry for missing tools. The engine keeps one
  status line per plugin, and this mod is its only writer (`run-band.tsx:19-20`), so the second card
  to land merges its part into the same line.

### Risk

low
A read-only display: `run_status.py` writes nothing and the band changes nothing about the run.

### Out-of-scope / non-goals

- Recording the budget and raising the 50% and 100% notices (O3).
- The per-turn step reminder and the issue update cadence (O2, saga: per-turn step reminder and
  issue update cadence).
- Lens grades, where-to-look items and missing tools in the band (C14, reading C13's document).
- Cost by step and role in the cost report (O4, saga: run and review economics in the cost report).
- Backstop gates such as a budget stop; the operator deferred them (plan.md).
- Any new writer to the run record.

### Files expected to change

- `plugins/saga/scripts/run_status.py`
- `plugins/saga/com.infiquetra.claude/mods/run-band.tsx`
- `plugins/saga/com.infiquetra.claude/mods/run-record.ts`
- `plugins/saga/com.infiquetra.claude/types/index.d.ts`
- `plugins/saga/tests/test_run_status.py`
- `plugins/saga/tests/test_mod_run_record_contract.py`
- `plugins/saga/com.infiquetra.claude/mods/run-band.test.tsx`

### Tests to add or update

- `plugins/saga/tests/test_run_status.py`: `band_line` names the step for a run in planning, plan
  review, work, testing and code review; shows the round; prices recorded usage with a fixture price
  table and marks unpriced usage; leaves the budget out when none is recorded and shows it when one
  is; shows time in step and the age of the last update; keeps every other part when the price table
  is unreadable. `summary --json` carries each new field.
- `plugins/saga/tests/test_mod_run_record_contract.py`: the view version the mod reads still equals
  the script's `SCHEMA` (`run_status.py:61`), moved together if the view changes shape.
- `plugins/saga/com.infiquetra.claude/mods/run-band.test.tsx`: the band renders the new line, the
  status line carries the spend, and a failed read still keeps what the band showed
  (`run-band.tsx:74-85`).

### Context library links

_none_

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/run_status.py --repo-root . summary --band` prints, for an
      active run, its step, round, spend, time in step and age of the last update, and the budget
      once O3 records one; each part the run has no data for is left out. Once C10b lands, the
      round reads "round k of 3".
- [ ] The Claude Code band shows the same line, and saga's status-line entry includes the spend.
- [ ] Spend uses `references/model-prices.yaml` and never prices an unpriced model at zero.
- [ ] `run_status.py` still writes nothing.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` and
      `claude plugin test plugins/saga` pass.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests/test_run_status.py plugins/saga/tests/test_mod_run_record_contract.py -q --import-mode=importlib
claude plugin validate --strict plugins/saga
claude plugin test plugins/saga
python3 plugins/saga/scripts/run_status.py --repo-root . summary --band
```

### Notes / conventions

For this card's planning step:

1. **Where the step comes from.** The enhancement plan names the steps (plan, plan review, work,
   test, code review); the envelope phase cannot tell plan review or testing apart (see Intent).
2. **When the current step began.** No record holds it today, so time in step needs a source.
3. **When the issue was last updated.** Neither the run record nor the run view holds it. The
   board-progression ledger stamps a time on each write it records (`board_progression.py:696`).
4. **Round wording before C10b** (saga: switch /code-review to the review command, with the new
   round and merge rules). Once C10b lands, the band reads "round k of 3". Until then today's
   records allow five cycles, so the planning step picks the wording for a run still under today's
   rules.
5. **The budget's field name.** O3 (saga: budget and proportionality at admission, as guidance)
   records the budget in the run record's `admission` block and owns its key; this card reads that
   key.
6. **Spend can undercount planning.** A session that works no unit row records no usage
   (`usage-capture.ts:6-10`), so planning or plan review run outside a unit session is not counted. Reviewer sessions are counted: they work in a scratch copy that
   maps to no unit row, so the mod records nothing for them, and the review command (C10a, saga: one review command from change to records) writes their
   usage through `run_record.py usage add` as ordinary usage entries.
