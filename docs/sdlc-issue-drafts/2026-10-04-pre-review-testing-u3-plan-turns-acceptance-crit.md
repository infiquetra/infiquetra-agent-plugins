---
title: pre-review testing U3 — /plan turns acceptance criteria into functional tests, and /doc-review rejects unproven criteria
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: medium
handoff_maturity: requirements-ready
approval_state: approved
---

# pre-review testing U3 — /plan turns acceptance criteria into functional tests, and /doc-review rejects unproven criteria

### Objective

Build the writer the build loop has always lacked. `/plan` turns each acceptance criterion into
named functional tests and records them on the units in the run record. `/doc-review` refuses a
plan that leaves any acceptance criterion without a test.

### Intent

`build_loop.py` already reads `functional_checks` and `scenario_smoke` from each unit's row in the
run record. It records "none prescribed" because no step writes them.
`plugins/saga/references/mechanical-baseline.md` says so: "No step in saga writes these onto a
unit's row yet."

1. In the plan's unit sections, each unit lists its functional checks. Each check names the command
   that runs it, the acceptance criterion it proves, and whether it runs locally or against the
   declared environment. The combined-branch scenario smoke is listed once, at the plan level.
2. When the plan is saved, a writer copies those checks onto the units' rows as `functional_checks`
   and the plan-level smoke as `scenario_smoke`. Each written entry is shaped exactly as
   `build_loop.py` reads it.
3. `/doc-review` gains a check: every acceptance criterion on the issue maps to at least one
   functional check or to the smoke, or the plan is not ready. A run with a recorded waiver skips
   this check and says so.

### Risk

medium
It adds a readiness gate to plan review, which can block plans, but the block names the unmapped
criterion and the fix is to add a test.

### Out-of-scope / non-goals

- Running the checks is pre-review testing U4.
- No new test framework; checks are commands the repository already can run.

### Files expected to change

- `plugins/saga/skills/plan/SKILL.md`
- `plugins/saga/skills/plan/references/plan-sections.md`
- `plugins/saga/references/plan-save-contract.yaml`
- `plugins/saga/scripts/plan_save_contract.py`
- `plugins/saga/skills/doc-review/SKILL.md`
- `plugins/saga/references/mechanical-baseline.md`

### Tests to add or update

- `plugins/saga/tests/test_plan_artifact_conformance.py`: a unit's functional checks name a command
  and a criterion.
- A writer test: a saved plan's checks appear on the run record's units in the shape
  `build_loop.py` reads, and `build_loop.py --dry-run` then lists them instead of "none
  prescribed".
- `plugins/saga/tests/test_doc_review_loop.py`: an unmapped acceptance criterion blocks readiness.

### Context library links

- `plugins/saga/references/mechanical-baseline.md`

### Acceptance criteria

- [ ] After `/plan` saves a plan with mapped checks, `uv run python plugins/saga/scripts/build_loop.py --issue <N> --dry-run` lists them and no longer prints "none prescribed in the run record".
- [ ] `/doc-review` reports a blocking finding naming any acceptance criterion with no mapped check.
- [ ] The sentence "No step in saga writes these onto a unit's row yet" is removed from `mechanical-baseline.md`.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_plan_artifact_conformance.py plugins/saga/tests/test_doc_review_loop.py plugins/saga/tests/test_build_loop.py -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/c3-plan-writes-functional-tests.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/c3-plan-writes-functional-tests.md
- Source type: brainstorm
- Source title: pre-review testing U3 — /plan turns acceptance criteria into functional tests, and /doc-review rejects unproven criteria

### Recommended Tier Band
opus/high

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/98
- Number: 98
- Created at: 2026-10-04T01:52:28.072221+00:00
