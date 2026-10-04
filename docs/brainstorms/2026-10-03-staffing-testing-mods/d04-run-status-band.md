---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# mods U4 — Saga run status band and status line

### Objective

Show the state of the saga run in this checkout as one line above the prompt, plus a short
status-line entry, so the operator can see where a run stands without asking.

### Intent

1. When a run record exists for this checkout, the band shows one line per active run. For example:
   "#412 · work · test loop pass 3, 2 failing · review cycle 1/3 · 7/10 lenses met".
2. The band has buttons to open the plan viewer (mods U3), the review findings pane (mods U7), and
   the raw record.
3. The status-line entry shows the issue and phase alone.
4. Data comes from `run_record.py show` through the shared state module in mods U0. It refreshes
   when a turn completes and on a slow timer. When no run exists, the band draws nothing.
5. A "hide" button hides the band for the session.

### Risk

low
It is read-only display of state the scripts already record.

### Out-of-scope / non-goals

- No actions that change the run from the band.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/` (the status band module)
- `plugins/saga/com.infiquetra.claude/types/index.d.ts`

### Tests to add or update

- `*.test.ts` on terminal and desktop:
  - band text from a fixture record;
  - nothing drawn without a record;
  - hide persists for the session;
  - the status-line entry matches the phase.

### Context library links

- `plugins/saga/references/run-record.md`

### Acceptance criteria

- [ ] Given a fixture run record, the band's text matches the expected line, shown by a test.
- [ ] With no run record, the band draws nothing, shown by a test.
- [ ] `claude plugin test plugins/saga` passes the band tests on terminal and desktop.

### Verification

```bash
claude plugin validate plugins/saga
claude plugin test plugins/saga
git diff --check
```
