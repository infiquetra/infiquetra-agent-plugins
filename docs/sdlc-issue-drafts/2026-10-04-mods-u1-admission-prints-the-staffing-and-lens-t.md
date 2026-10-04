---
title: mods U1 — Admission prints the staffing and lens tables in one fixed format, for every harness
repo: infiquetra-agent-plugins
type: enhancement
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: enhancement, needs-plan
risk: low
handoff_maturity: requirements-ready
approval_state: approved
---

# mods U1 — Admission prints the staffing and lens tables in one fixed format, for every harness

### Objective

Make `admission.py` render the staffing table and the lens table itself, in one fixed Markdown
format. The planning skill then shows them as printed instead of letting the model reformat them
each time. This fixes the display in every harness, not only Claude Code.

### Intent

Operators routinely ask for the staffing layout again as a table, because the model presents
admission's question 4 and question 5 differently every time. The questions come out of
`plugins/saga/scripts/admission.py` as data, and the model improvises the presentation.

1. Add a render option to `admission.py` that prints two Markdown tables in a fixed column order:
   - **Staffing:** Role, Default, Jev suggestion (with confidence), Proposed, Why.
   - **Lenses:** Lens, Include, Reason, Jev probability.

   Empty Jev columns read "not configured" or "no suggestion". They are never left blank.
2. `plugins/saga/skills/plan/SKILL.md` tells the model to print that block exactly as rendered, and
   to collect answers against it.
3. A golden-output test pins the format, so a change to it is deliberate.

### Risk

low
It changes presentation only; the answers and the record are unchanged.

### Out-of-scope / non-goals

- The interactive pane is mods U2.
- No change to the questions themselves.

### Files expected to change

- `plugins/saga/scripts/admission.py`
- `plugins/saga/skills/plan/SKILL.md`

### Tests to add or update

- `plugins/saga/tests/test_admission.py`: a golden-output test for both tables, including the
  "not configured" Jev cells.

### Context library links

_none_

### Acceptance criteria

- [ ] `uv run python plugins/saga/scripts/admission.py --help` documents the render option.
- [ ] The rendered staffing and lens tables match the golden fixture in `plugins/saga/tests/test_admission.py`.
- [ ] The planning skill instructs printing the rendered block verbatim.

### Verification

```bash
uv run python plugins/saga/scripts/admission.py --help
python3 -m pytest plugins/saga/tests/test_admission.py -q --import-mode=importlib
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/d01-fixed-format-tables.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/d01-fixed-format-tables.md
- Source type: brainstorm
- Source title: mods U1 — Admission prints the staffing and lens tables in one fixed format, for every harness

### Recommended Tier Band
sonnet/medium

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/102
- Number: 102
- Created at: 2026-10-04T01:53:46.778148+00:00
