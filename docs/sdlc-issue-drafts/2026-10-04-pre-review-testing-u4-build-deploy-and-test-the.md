---
title: pre-review testing U4 — Build, deploy and test the combined branch before review, one run at a time on shared non-production
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: high
handoff_maturity: requirements-ready
approval_state: approved
---

# pre-review testing U4 — Build, deploy and test the combined branch before review, one run at a time on shared non-production

### Objective

Extend the build loop so that, after integration and before review, it repeatedly takes the
combined branch through four steps until green:

1. Build.
2. Deploy or start it through the repository's declared environment.
3. Run the functional suite.
4. Tear down.

On a shared non-production stack, only one run may hold the environment at a time.

### Intent

1. **A combined-branch mode for `build_loop.py`.** Each pass runs the declared deploy-or-start
   command, then the test command, then the teardown command. Teardown runs on every exit path,
   including a failure. Each pass's results are recorded on the run record. A failing test is a
   loop pass (exit 4), never a refusal.
2. **Environment failures stay separate from defects.** A deploy that fails to run, a timeout, or a
   missing tool is `could-not-execute`, never a pass and never a code defect. After three
   consecutive `could-not-execute` passes the loop stops and names the environment problem for the
   operator.
3. **One run at a time on a shared environment.** Before deploying, the loop acquires a lease that
   names the run, the revision and the start time. It releases the lease after teardown. A second
   run waits and reports what it is waiting on. The lease must be visible to every host that can
   deploy, not just this machine. A lock file in one checkout is not enough.
4. **Placement in `/work`.** The step runs after the merge turn brings the units together and
   before Phase 5's review. A single-lane run, with nothing to integrate, runs it on its one
   branch.

### Risk

high
It deploys real infrastructure on every pass and coordinates a shared environment across runs and
hosts.

### Out-of-scope / non-goals

- Writing the tests is pre-review testing U3; declaring the environment is U2.
- No production deployment on any path.

### Inputs inventory

- `plugins/saga/scripts/build_loop.py` — exit codes 0, 4, 2, 3 and the record block.
- `plugins/saga/scripts/merge_turn.py` — where integration ends.

### Files expected to change

- `plugins/saga/scripts/build_loop.py`
- `plugins/saga/references/mechanical-baseline.md`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/scripts/merge_turn.py`

### Tests to add or update

- `plugins/saga/tests/test_build_loop.py`: deploy, test and teardown run in order; teardown runs
  after a failing test and after a failed deploy; three consecutive could-not-execute passes stop
  the loop; a second run cannot take a held shared lease; a released lease admits the next run.

### Failure modes / pre-mortem

- A lease that only one host can see lets two hosts deploy at once. The lease lives where every
  deploying host reads it, and `/plan` names that place.
- A crashed run never releases its lease. The lease carries a start time and an owner, and a stale
  one is reported and recoverable by the operator rather than silently broken.

### Stop conditions

- Stop if no lease location is visible to every host that deploys to the shared environment.
- Stop if a declared deploy command targets a production account or cluster.

### Context library links

- `plugins/saga/references/mechanical-baseline.md`

### Acceptance criteria

- [ ] `plugins/saga/tests/test_build_loop.py` covers deploy, test and teardown order, teardown on failure, the could-not-execute stop, and lease exclusion.
- [ ] A combined-branch pass is recorded on the run record with the deploy, test and teardown results.
- [ ] `/work`'s skill places the combined-branch loop after integration and before review.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_build_loop.py -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/c4-combined-branch-loop.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/c4-combined-branch-loop.md
- Source type: brainstorm
- Source title: pre-review testing U4 — Build, deploy and test the combined branch before review, one run at a time on shared non-production

### Recommended Tier Band
opus/high

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/99
- Number: 99
- Created at: 2026-10-04T01:52:46.716678+00:00
