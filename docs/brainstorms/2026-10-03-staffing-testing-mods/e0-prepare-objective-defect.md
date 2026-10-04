---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# mission-control: issue prepare records the source file path as the card's Objective and logs it as the operator's Jev choice

### Objective

Stop `issue prepare` from writing the source artifact's path into the card's `Objective` project
field. Stop the suggestion step from logging that path to the TypeSafe verdict log as the operator's
chosen Objective.

### Intent

**Observed 2026-10-03** while preparing cards for this repository with
`issue prepare --from docs/brainstorms/... --suggest --objective-option ...`:

- The sidecar's `project_fields.Objective` held
  `docs/brainstorms/2026-10-03-staffing-testing-mods/a0-staffing-parent.md`, a file path rather than
  an Objective option.
- The suggestion output read "objective: improve-claude-plugins ...; you chose
  docs/brainstorms/.../a0-staffing-parent.md (OVERRIDDEN by your flag)". So an override record
  naming that path as the operator's choice went into `~/.claude/typesafe/verdicts.jsonl`.
- The 2026-08-30 drafts in `docs/sdlc-issue-drafts/` show the same: their `project_fields.Objective`
  is a scratchpad path.

**Cause.** `_prepared_project_fields` in `plugins/mission-control/scripts/sdlc_manager.py` sets
`fields["Objective"] = source_artifact.ref` under the comment "Objective is carried only when the
handoff source names one". `issue_prepare` then passes that value to the suggestion step as
`chosen_objective`. The source reference is not an Objective, so every prepare with a source writes
a false operator choice.

**Why it matters.** The evaluation harness scores Jev against the labels in that log. A file path
recorded as the operator's Objective is a guaranteed false disagreement. It skews every agreement
figure for the objective judgment, which is exactly the evidence needed to decide whether Jev may
act on its own.

**Fix.** Carry an Objective only when the operator names one. Add an explicit `--objective` option
to `issue prepare` that must be one of the live field's options. Compare suggestions only against
that, and log no override when none was named. Add a one-off cleanup that marks the existing bogus
override records as invalid without rewriting them, since the log is append-only.

### Risk

low
The field is recorded in the sidecar but not yet applied to the live card, so the fix changes
bookkeeping and the verdict log, not issues on any board.

### Out-of-scope / non-goals

- No change to how create-prepared applies project fields.
- No rewrite of historical verdict log lines.

### Files expected to change

- `plugins/mission-control/scripts/sdlc_manager.py`
- `plugins/mission-control/skills/issues/SKILL.md`
- `plugins/mission-control/CHANGELOG.md`

### Tests to add or update

- `plugins/mission-control/tests/test_issue_prepare_suggest.py`: a prepare with a source and no
  `--objective` logs no objective override; with `--objective improve-agent-plugins` the comparison
  uses that value.
- `plugins/mission-control/tests/test_issue_prepare.py`: `project_fields` never carries a path as
  the Objective.

### Context library links

- `plugins/fleet-core/references/typesafe.md` — the verdict log and labels

### Acceptance criteria

- [ ] `issue prepare --from <path> --suggest --objective-option improve-agent-plugins` writes no `Objective` into `project_fields` and logs no objective override.
- [ ] `issue prepare --objective improve-agent-plugins ...` records that value and compares the suggestion against it.
- [ ] The mission-control suite passes.

### Verification

```bash
python3 -m pytest plugins/mission-control/tests/test_issue_prepare.py plugins/mission-control/tests/test_issue_prepare_suggest.py -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```
