---
date: 2026-10-06
topic: plan-viewer-markdown
maturity: requirements-ready
---

# saga mod: the plan viewer draws wide Markdown tables readably

### Objective

The plan viewer pane draws every Markdown table in a plan so that the operator can read it at the
pane's width: no row overlaps another, and no cell's text is lost. The plan file itself stays as the
author wrote it.

### Intent

The plan viewer (`plugins/saga/com.infiquetra.claude/mods/plan-viewer.tsx`, issue #104) passes each
section's text straight to the engine's `Markdown` element. On 6 October 2026 the operator opened the
#147 program plan (`docs/plans/2026-10-06-saga-review-redesign-program-plan.md`) through the run
band's Plan button. Its decision table had four columns and cells up to about 330 characters, and in
the pane the table's rows overlapped each other and could not be read. The table was rewritten as
headed sections to work around it. That is the wrong fix: saga's own formatting contract
(`plugins/saga/references/formatting-style.md`) tells plan authors to put comparative data in tables,
so every plan with long table cells has the same problem.

The fix belongs in the mod, before the text reaches `Markdown`:

- Find each GitHub-style table in the page, outside fenced code blocks.
- Work out whether it fits the width the pane draws in. The render event's `e.viewport.columns`
  gives the surface's width, and the pane's docked width when the engine reports it.
- Leave a table that fits unchanged.
- Draw a table that does not fit so it wraps without overlapping. One option is the mod's own `Box`
  and `Text` columns with wrapping text. Another is a stacked form, one block per row, with each cell
  under its column's header. The plan for this card chooses between them and records why.
- Keep the 10,000-character page limit (`MARKDOWN_LIMIT` in `plan-sections.ts`) and the pressable
  `path:line` references (`linkifyRefs`) working on the redrawn text.
- Put the table handling in `plan-sections.ts` as a pure function of the text and the width, so it
  can be tested without the engine. The review pane (`review-pane.tsx`) can use it later.

### Risk

low
It changes how one read-only pane draws text; it writes nothing and leaves the plan file untouched.

### Out-of-scope / non-goals

- Changing any plan document, or the formatting contract's advice to use tables.
- The engine's own `Markdown` table rendering in Claude Code; that is not ours to change.
- The review pane and the admission review pane, beyond leaving the new function reusable.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/mods/plan-sections.ts`
- `plugins/saga/com.infiquetra.claude/mods/plan-viewer.tsx`
- `plugins/saga/com.infiquetra.claude/mods/plan-sections.test.ts`
- `plugins/saga/com.infiquetra.claude/mods/plan-viewer.test.tsx`
- `plugins/saga/com.infiquetra.claude/mods/fixtures/` (a plan fixture with a wide table)
- `docs/engineering-journal/LEARNINGS.md`

### Tests to add or update

- `plan-sections.test.ts`: a table that fits the width is returned unchanged. A four-column table
  with 300-character cells, at 100 columns, comes back so that no drawn line is wider than 100 and
  every cell's words are present. A table inside a fenced code block is left alone. A row with fewer
  cells than the header keeps its empty cells. A page that is near the 10,000-character limit stays
  under it after the redraw. A backticked `path:line` inside a redrawn cell is still found by
  `linkifyRefs`.
- `plan-viewer.test.tsx`: rendering the wide-table fixture at a narrow viewport draws the redrawn
  form, and at a wide viewport draws the table as written.

### Context library links

- `plugins/saga/references/formatting-style.md`
- `plugins/saga/com.infiquetra.claude/mods/plan-viewer.tsx` (issue #104)

### Acceptance criteria

- [ ] In the plan viewer, a Markdown table that is wider than the pane is drawn with no overlapping rows and no lost text.
- [ ] A table that fits the pane is drawn exactly as before.
- [ ] Tables inside fenced code blocks, the page limit and pressable `path:line` references behave as before.
- [ ] The new tests pass, and the existing plan-viewer and plan-sections tests still pass.

### Verification

```bash
claude plugin validate --strict plugins/saga
claude plugin test plugins/saga
python3 scripts/check_repo.py
git diff --check
```
