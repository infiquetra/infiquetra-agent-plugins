---
title: orchestrate: loading and saving a saga run record erases unit-row keys orchestrate does not own
repo: infiquetra-agent-plugins
type: defect
team: asgard
project: operations
labels: defect, needs-plan
risk: medium
handoff_maturity: requirements-ready
stage: Shaping
status: Discovering
approval_state: approved
---

# orchestrate: loading and saving a saga run record erases unit-row keys orchestrate does not own

### Objective

Make orchestrate keep every unit-row key it does not own when it loads and saves a saga run
record, and stop its whole-record save from overwriting what another writer recorded since the
load. Saga's build loop, the cost-per-unit usage block, and the planned functional checks all
live in those rows.

### Intent

**Observed 2026-10-04** by the survey for the staffing, testing and mods program, and reproduced in
a scratch copy: a run record whose unit row carried `build_loop` and `usage` was loaded with
orchestrate's `Run.load` and saved with `Run.save`, and came back with neither key. Orchestrate
printed "unit u1 carries unknown key 'usage'; this Orchestrate 6.0.1 ignores it".

**Cause.** In `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`:

- `read_unit` builds a `Unit` from only the keys the dataclass declares and drops the rest.
- `Run.save` rewrites the whole `units` array from the in-memory `Unit` list, so every dropped key
  is gone, and anything another process wrote after the load is overwritten.

`plugins/saga/references/run-record.md` promises the opposite: a unit row's key set is open, and a
key another consumer does not know is left alone. The build loop (`build_loop.py`, key
`build_loop`) already relies on that promise, so orchestrate-driven runs lose their build-loop
record today. Issues #95 (usage), #98 (functional checks), #99 (combined-branch loop) and #107 (live
token capture) add more keys to the same rows.

**Fix.**

1. `read_unit` keeps the keys it does not own in a pass-through mapping held beside each `Unit`,
   not as `Unit` attributes, so the existing test that an unknown key never reaches the `Unit`
   stays green.
2. `Run.save` takes the run record's lock, re-reads the record from disk, and for each unit row
   writes orchestrate's own keys from memory and carries every other key forward from the on-disk
   row. It does the same for top-level keys it does not own. Then it replaces the file atomically
   and releases the lock.
3. The lock is the same advisory lock saga's `run_record.py` takes for its own read-modify-write
   (#95 adds it there), named in `run-record.md`, so the two writers serialise rather than race.

### Risk

medium
Orchestrate writes the run record on every launch, settle and merge, so a mistake in the merge on
save could corrupt the record every run reads, though the change only adds keys it used to drop.

### Out-of-scope / non-goals

- No change to which keys orchestrate owns or to the record version.
- No change to `orchestrate start` replacing the planned units at launch; rows it creates fresh
  have nothing to carry forward.

### Files expected to change

- `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`
- `plugins/orchestrate/tests/test_orchestrate_record.py`
- `plugins/orchestrate/CHANGELOG.md`
- `plugins/saga/references/run-record.md`
- `docs/engineering-journal/LEARNINGS.md`

### Tests to add or update

- `plugins/orchestrate/tests/test_orchestrate_record.py`:
  - a row carrying `build_loop` and `usage` keeps both through `Run.load` and `Run.save`;
  - a `usage` entry written to disk between load and save survives the save;
  - an unknown top-level key survives;
  - orchestrate's own keys still take the in-memory value.
- `plugins/orchestrate/tests/test_orchestrate_launch_argv.py`: the existing assertion that an
  unknown key does not reach the `Unit` stays green.

### Context library links

- `plugins/saga/references/run-record.md`

### Acceptance criteria

- [ ] A test shows a unit row's `build_loop` and `usage` keys survive orchestrate's load and save.
- [ ] A test shows a key written by another process between orchestrate's load and save survives the save.
- [ ] `run-record.md` names the shared lock and the round-trip rule for every whole-row writer.
- [ ] `python3 -m pytest plugins/orchestrate/tests -q --import-mode=importlib` passes.

### Verification

```bash
python3 -m pytest plugins/orchestrate/tests -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/f0-orchestrate-unit-row-keys.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/f0-orchestrate-unit-row-keys.md
- Source type: brainstorm
- Source title: orchestrate: loading and saving a saga run record erases unit-row keys orchestrate does not own

### Recommended Tier Band
opus/medium

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/113
- Number: 113
- Created at: 2026-10-04T03:07:49.468599+00:00
