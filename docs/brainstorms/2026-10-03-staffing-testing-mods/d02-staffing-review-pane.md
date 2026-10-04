---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# mods U2 — Staffing and lens review pane

### Objective

In Claude Code, show admission's staffing answers (question 4) and lens answers (question 5) in a
pane with a proper table and per-row controls. The operator's answers go straight back through
admission's script instead of the model retyping a table.

### Intent

1. The mod registers a tool the model can call when admission reaches question 4. It is listed as
   `mcp__saga__review_admission`.
2. The tool opens a pane with two tables built from mods U1's render output:
   - **Staffing:** role, default, Jev suggestion and confidence, proposed tier, and reason, with a
     dropdown per row for model and effort. The choices come from the staffing palette through a
     script call, never a hard-coded list.
   - **Lenses:** each conditional lens with include toggles, Jev's probability, and the reason.
3. "Accept all" and "Submit" write the answers through admission's answers path. The pane returns
   them to the model as the tool's structured result. Closing the pane returns "dismissed", and the
   skill falls back to mods U1's printed table.
4. The planning skill calls the tool when it is available, and prints mods U1's table otherwise.

### Risk

medium
The pane writes the operator's staffing and lens answers into the run record, so a wrong mapping
would mis-staff a run, though only through admission's own validated path.

### Out-of-scope / non-goals

- No staffing or lens decision by the mod; it shows and collects.
- No change to the palette or the lens catalogue.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/` (the admission review module)
- `plugins/saga/com.infiquetra.claude/types/index.d.ts`
- `plugins/saga/skills/plan/SKILL.md`

### Tests to add or update

- `*.test.ts` over the terminal and desktop surfaces:
  - the pane draws both tables;
  - a dropdown change and Submit produce the expected answers payload;
  - dismissing returns "dismissed";
  - an off-palette value cannot be selected.

### Context library links

_none_

### Acceptance criteria

- [ ] `claude plugin test plugins/saga` passes the admission pane tests on terminal and desktop.
- [ ] Submitting the pane writes answers that `uv run python plugins/saga/scripts/run_record.py show <N>` then reports under the run's staffing and lens parameters with the operator as their source.
- [ ] With the tool absent, the skill prints mods U1's table instead.

### Verification

```bash
claude plugin validate plugins/saga
claude plugin test plugins/saga
python3 -m pytest plugins/saga/tests/test_admission.py -q --import-mode=importlib
git diff --check
```
