---
title: pre-review testing U1 — Lifecycle policy: require functional testing before code review
repo: infiquetra-sdlc
type: enhancement
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: enhancement, needs-plan
risk: high
handoff_maturity: requirements-ready
approval_state: approved
---

# pre-review testing U1 — Lifecycle policy: require functional testing before code review

### Objective

Amend the lifecycle run model so functional testing before code review is required for
code-bearing work, using a mechanism the repository declares. Skipping it needs a recorded waiver.
Today the deployed part applies only "where the repository declares a branch preview".

### Intent

Change the run model in four places, keeping prose, data and the data test in agreement:

1. **Step 5, assign and implement.** A unit's exit criterion includes its locally runnable
   functional checks. These are derived from the acceptance criteria, and the plan names which
   criterion each check proves.
2. **Between step 6 (bring work together) and step 7 (review).** The combined branch is built,
   then deployed or started through the repository's declared environment, then tested with the
   functional suite, and torn down. This repeats until green, before review.
3. **The declaration.** Each repository declares its functional-test environment, or records a
   waiver with a reason, such as a documentation-only change:
   - its kind: a local run, an emulator, an ephemeral stack, or the shared non-production stack;
   - a deploy-or-start command, a test command and an optional teardown;
   - and whether the environment is private or shared.

   A shared environment is used only for the combined branch, one run at a time.
4. **The review cycle limit.** The best-available revision accepted at the limit must be one that
   passed the acceptance tests. Leftover findings are carried into linked issues, as the model
   already provides.

Step 11 (`/qa` after merge and deployment) is unchanged.

### Risk

high
It changes the lifecycle policy every repository and every harness executes, and adds a hard gate
before review.

### Out-of-scope / non-goals

- No change to the lens catalogue or the executor ledger.
- No change to step 11's post-merge functional test.
- No saga code; saga carries the policy out in its own child cards.

### Inputs inventory

- `docs/lifecycle/run-model.md` — step 5 "Working software, where a repository has somewhere to put
  it", step 6 to 7 transition rows, step 9 residual handling.
- `config/run-model.json` and `tools/docs/tests/test_run_model_data.py`.
- The parent issue's operator rulings.

### Files expected to change

- `docs/lifecycle/run-model.md`
- `config/run-model.json`
- `tools/docs/tests/test_run_model_data.py`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `tools/docs/tests/test_run_model_data.py`: the data declares the combined-branch functional step
  before review, the waiver, and the shared-environment rule, and agrees with the prose.

### Failure modes / pre-mortem

- Prose and `config/run-model.json` drift apart. The data test holds them together.
- The waiver becomes the default escape. The waiver needs a reason recorded in the run record and
  shown at closeout.

### Stop conditions

- Stop if the change would alter step 11 or the meaning of the Verify stage.

### Context library links

- `docs/lifecycle/run-model.md`

### Acceptance criteria

- [ ] `docs/lifecycle/run-model.md` states the combined-branch functional step before review, the repository declaration, the waiver, the shared-environment rule and the cycle-limit rule.
- [ ] `config/run-model.json` encodes the same, and `python3 -m pytest tools/docs/tests/test_run_model_data.py -q` passes.
- [ ] A `DECISIONS.md` entry records the policy change and the rejected alternative: keeping the deployed check conditional.

### Verification

```bash
python3 -m pytest tools/docs/tests/test_run_model_data.py -q
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/c1-sdlc-run-model.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/c1-sdlc-run-model.md
- Source type: brainstorm
- Source title: pre-review testing U1 — Lifecycle policy: require functional testing before code review

### Recommended Tier Band
sonnet/medium

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-sdlc/issues/174
- Number: 174
- Created with gh (repo unmapped; create-prepared would open a mapping PR)
