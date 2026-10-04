---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# Functional testing before code review: a repository-declared build, deploy and test loop

### Objective

Make every code-bearing saga run prove its change works before any code review starts. The run
builds, deploys or starts the change where the repository says to, and runs functional tests
derived from the issue's acceptance criteria. It repeats that until green, so review spends its
cycles on judgment rather than on code that does not run.

### Intent

**Why.** A failing test is easier to fix than a vague review judgment, and working code that meets
its acceptance criteria is easier to accept when review hits its cycle limit. Today saga's
pre-review loop is, in practice, lint, type checks and unit tests.

**Current state, verified 2026-10-03.**

- `/work` Phase 3 runs `plugins/saga/scripts/build_loop.py` until green. Phase 5.1 reviews only
  the revision the loop went green at, and a repair commit makes the review stale.
- `build_loop.py` reads per-unit `functional_checks` and `scenario_smoke`, but nothing writes them.
  It is the only non-test code that touches those keys, so every pass records "none prescribed".
- A branch preview runs before review only where `.saga-profile.json` declares
  `branch_preview: true` and a `branch_preview_command`. There is no test or teardown command.
- `/qa` runs the prescribed functional strategies only after review, merge, release and a
  non-production deploy.
- infiquetra-sdlc's run model already asks planners for "locally runnable, child-scoped functional
  checks". But it makes the deployed check conditional, "where the repository declares a branch
  preview".

**Operator rulings, settled 2026-10-03, binding on every child.**

1. Every code-bearing run proves its change works before review: build, then deploy or start, then
   functional tests against the issue's acceptance criteria, repeated until green. A failing test
   is another loop pass, never a review finding.
2. The plugin never chooses the mechanism. The repository declares it once in its saga profile:
   - a local run, an emulator such as LocalStack, an ephemeral stack, or the shared non-production
     stack;
   - each as a deploy-or-start command, a test command and an optional teardown;
   - and whether the environment is private to the branch or shared.

   If the declaration is missing, admission asks once and writes it back. A run with no functional
   testing needs a recorded waiver with a reason.
3. On a shared non-production stack, only the combined branch is deployed: one run at a time,
   right before review. Units still run their local checks first.
4. Review does not start without passing functional tests on the combined branch.
5. At the review cycle limit, the best-available revision must be one that passed the acceptance
   tests. Leftover findings become linked issues.
6. `/qa` stays after merge, as the check that the deployed, merged change works in its real
   environment.

**Dependency graph.** `U1 → {U2, U3} → U4 → U5`. U1 changes the lifecycle policy in
infiquetra-sdlc, and saga carries it out in U2 to U5.

### Risk

high
It adds deployments and a hard gate to every code-bearing run, and a shared environment adds a
cross-run coordination problem.

### Out-of-scope / non-goals

- No change to `/qa`'s post-merge role or its strategy catalogue.
- No choice of deployment technology by the plugin.
- No fix for `/code-review` ending every cycle `review_incomplete`, which comes from infiquetra-sdlc's
  empty executor ledger. It is related, but separate.

### Inputs inventory

- infiquetra-sdlc `docs/lifecycle/run-model.md`, `config/run-model.json` and
  `tools/docs/tests/test_run_model_data.py`.
- `plugins/saga/references/mechanical-baseline.md` and `plugins/saga/references/repository-profile.md`.

### Files expected to change

- `plugins/saga/references/repository-profile.md`
- `plugins/saga/scripts/admission.py`
- `plugins/saga/scripts/build_loop.py`
- `plugins/saga/references/mechanical-baseline.md`
- `plugins/saga/skills/plan/SKILL.md`
- `plugins/saga/skills/doc-review/SKILL.md`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/skills/code-review/SKILL.md`

### Tests to add or update

Each child names its own: profile declaration and waiver, the plan writer, the doc-review mapping
check, the combined-branch loop with teardown and serialization, and the review and cycle-limit
gates.

### Failure modes / pre-mortem

- **Most likely failure:** collisions on a shared non-production stack. Two runs deploy over each
  other and tests pass or fail for the wrong reasons. Ruling 3 plus U4's serialization addresses
  it. A lock that only one machine can see is not enough if more than one host deploys.
- Flaky deploys keep the loop from ever going green. An environment failure is recorded as
  could-not-execute and surfaced to the operator, never as a code defect.
- Ephemeral stacks are left running. Teardown runs on every exit path and is recorded.
- Tests that prove nothing about the acceptance criteria. `/doc-review` rejects any criterion
  without a mapped test (U3).

### Stop conditions

- Stop U2 to U5 if infiquetra-sdlc does not adopt the policy change in U1.
- Stop and ask the operator if a repository's declared mechanism needs credentials or production
  access the run is not approved for.

### Context library links

- `plugins/saga/references/mechanical-baseline.md`
- `plugins/saga/references/repository-profile.md`

### Acceptance criteria

- [ ] Every child issue closes with its own acceptance criteria met.
- [ ] A code-bearing run in a repository with a declared environment cannot reach `/code-review` without a passing combined-branch functional run recorded in its run record, shown by a `plugins/saga/tests/test_build_loop.py` case.

### Verification

```bash
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```
