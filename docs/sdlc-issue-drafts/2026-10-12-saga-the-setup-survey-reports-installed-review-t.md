---
title: saga: the setup survey reports installed review tools as missing, and ruff runs at whatever version PATH holds
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

# saga: the setup survey reports installed review tools as missing, and ruff runs at whatever version PATH holds

### Objective

Make saga's setup survey report pytest-randomly, pytest-socket and muter correctly, and run ruff at saga's pinned
version without requiring the operator's own ruff to match the pin.

### Intent

Installing saga's review tools on the operator's Mac on 2026-10-12 (for saga-review-corpus#3, whose harness refuses
a full run while any default tool is not installed) left three tools reported wrong and one real conflict:

- **pytest-randomly and pytest-socket** are pytest plugins with no console script. The survey looks for an executable
  of that name on PATH, so it reports them missing forever. The review run already loads both per run with
  `uv run --with pytest-randomly==5.0.0` and `uv run --with pytest-socket==0.8.1` (`review_adapters_python.py`), so
  nothing needs installing; the survey row is wrong.
- **muter** prints a bare `16` for `--version`. The survey's version pattern requires at least two dotted parts, so an
  installed muter reads as missing.
- **ruff** runs from PATH (`review_adapters_python.py`, `ruff check --isolated ...`), so a review's result depends on
  the operator's ruff. The pin is 0.15.18; this Mac has 0.16.9 for other work, and installing the pinned version
  would shadow it on PATH.

### Out-of-scope / non-goals

- Adding install commands to tool rows.
- Changing which tools the survey lists, or any other pin.

### Files expected to change

- plugins/saga/scripts/saga_setup.py
- plugins/saga/scripts/review_adapters_python.py
- plugins/saga/references/review-tools.json
- plugins/saga/tests/test_saga_setup.py
- plugins/saga/tests/test_review_adapters_python.py
- plugins/saga/CHANGELOG.md

### Tests to add or update

- A pytest plugin row is detected the way the review run uses it (importable through `uv run --with <pkg>==<pin>`, or
  marked as run-time-loaded), and an installed-on-demand plugin no longer reads as missing.
- A bare integer version such as `16` is accepted and compared against the pin.
- ruff runs through `uv run --with ruff==<pin>` (or the adapter's equivalent pinned runner), so a different ruff on
  PATH does not change the result; the survey no longer reports PATH ruff's version as a problem for the review.

### Context library links

_none_

### Acceptance criteria

- [ ] On a machine with ruff 0.16.9 on PATH, the Python review adapter runs ruff 0.15.18:
  `python3 -m pytest plugins/saga/tests/test_review_adapters_python.py` covers it.
- [ ] The survey reports pytest-randomly, pytest-socket and an installed muter as installed:
  `python3 -m pytest plugins/saga/tests/test_saga_setup.py` covers each.
- [ ] No other survey row changes status.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_saga_setup.py plugins/saga/tests/test_review_adapters_python.py
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
claude plugin validate --strict plugins/saga
git diff --check
```

### Risk

medium

A wrong detection either hides a genuinely missing tool or changes a lens's findings, which the calibration measures.

### Notes / conventions

Part of #147; blocks saga-review-corpus#3's first full run. Do not bump the saga version.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-12-saga-survey-false-missing/defect.md

### Source context
- Source: docs/brainstorms/2026-10-12-saga-survey-false-missing/defect.md
- Source type: brainstorm
- Source title: saga: the setup survey reports installed review tools as missing, and ruff runs at whatever version PATH holds

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/226
- Number: 226
- Created at: 2026-10-12T00:51:43.334937+00:00
