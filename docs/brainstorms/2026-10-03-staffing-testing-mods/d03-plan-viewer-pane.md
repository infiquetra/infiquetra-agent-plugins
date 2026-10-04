---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# mods U3 — Plan viewer pane

### Objective

Let the operator read a saga plan inside Claude Code, one section at a time, without opening
another tool.

### Intent

1. A `/plan-view` command opens a pane for the run's plan, or for a named path or issue. The pane
   lists the plan's sections by heading. Choosing one renders it as Markdown. A section longer than
   the 10,000-character Markdown limit is paged.
2. The pane refreshes when the model edits the plan file, detected from the edit tool calls that
   touch that path, or when the file's modification time changes.
3. File links in a section can be pressed. A press quotes the file and line into the prompt rather
   than leaving Claude Code.
4. A "discuss this" button quotes the shown section into the prompt for the operator to annotate.
5. When `/plan` saves a plan, the pane opens on its own if the terminal is at least 144 columns
   wide. Otherwise a toast names the command.

### Risk

low
It is read-only display; the only writes are into the operator's own prompt.

### Out-of-scope / non-goals

- No editing of the plan from the pane.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/` (the plan viewer module)
- `plugins/saga/com.infiquetra.claude/types/index.d.ts`

### Tests to add or update

- `*.test.ts` on terminal and desktop:
  - section list and selection;
  - paging past 10,000 characters;
  - refresh after an edit to the plan path;
  - a link press fills the prompt;
  - "discuss this" quotes the section.

### Context library links

_none_

### Acceptance criteria

- [ ] `/plan-view` opens the pane and lists the plan's headings, shown by a test.
- [ ] A section longer than 10,000 characters is paged rather than refused, shown by a test.
- [ ] `claude plugin test plugins/saga` passes the plan viewer tests on terminal and desktop.

### Verification

```bash
claude plugin validate plugins/saga
claude plugin test plugins/saga
git diff --check
```
