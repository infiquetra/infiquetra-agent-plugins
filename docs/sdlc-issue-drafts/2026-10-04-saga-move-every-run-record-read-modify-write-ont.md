---
title: saga: move every run-record read-modify-write onto the shared record lock
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

# saga: move every run-record read-modify-write onto the shared record lock

### Objective

Make every saga script that reads, changes and rewrites a run record do it under the run-record
lock, so a usage entry, a build-loop result or a review result written by one process is never
overwritten by another process's stale copy.

### Intent

Issue #95 added the run-record lock to `plugins/saga/scripts/run_record.py`: `record_lock` takes an
exclusive `fcntl.flock` on `<record path>.lock`, and `update(store_root, issue, change)` re-reads the
record while holding it, applies the change and writes through the atomic replace. Issue #113 gave
orchestrate the same lock. But #95 moved only its own two writers (`usage add` and
`set_next_step`). The survey and #95's implementer found these saga writers still load the whole
record, change it and replace it without the lock:

- `plugins/saga/scripts/admission.py` (two writes);
- `plugins/saga/scripts/review_result.py` (two writes);
- `plugins/saga/scripts/qa_strategies.py` (two writes);
- `plugins/saga/scripts/build_loop.py` (its write by path).

Each can erase what another process wrote between its read and its replace. The live token-capture
mod (#107) will write usage entries every few seconds during a unit session, which makes that race
likely rather than rare.

**Change.** Route each of those writes through `run_record.update` (or a by-path equivalent for the
build loop), so the change is applied to a fresh read under the lock. Never take the lock inside
`run_record.save` itself: the lock is not re-entrant, and orchestrate's save already holds it while
it calls the atomic replace.

### Risk

medium
Every saga phase writes the run record through these paths, so a mistake could stall a run on the
lock or drop a write, though each change only moves an existing write under the lock.

### Out-of-scope / non-goals

- No change to the record's shape, version or keys.
- No change to orchestrate; #113 covers it.

### Files expected to change

- `plugins/saga/scripts/admission.py`
- `plugins/saga/scripts/review_result.py`
- `plugins/saga/scripts/qa_strategies.py`
- `plugins/saga/scripts/build_loop.py`
- `plugins/saga/references/run-record.md`
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- For each writer, a test that a key written to the record by another process between the writer's
  read and its write survives the write.
- A test that `run_record.save` takes no lock, so a caller holding the lock can still save.

### Context library links

- `plugins/saga/references/run-record.md`

### Acceptance criteria

- [ ] `grep` finds no saga script outside `run_record.py` that replaces a run record without going through the lock.
- [ ] A test per writer shows a concurrent key survives its write.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes.

### Verification

```bash
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/f2-saga-writers-take-record-lock.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/f2-saga-writers-take-record-lock.md
- Source type: brainstorm
- Source title: saga: move every run-record read-modify-write onto the shared record lock

### Recommended Tier Band
opus/medium

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/117
- Number: 117
- Created at: 2026-10-04T03:56:06.765982+00:00
