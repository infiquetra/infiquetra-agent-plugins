---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# mods U8 — Orchestrate fleet pane and launch-approval table

### Objective

Give orchestrate a machine-readable status. Show every unit of a run in a Claude Code pane. Present
the table the operator approves before launch in one fixed format, interactively where Claude Code
allows it.

### Intent

1. **Portable first.** Add `orchestrate.py status --json`, printing every unit's vendor, model,
   effort, state, branch, commit count and what it waits on. `status` has no machine-readable form
   today. The approval table in `plugins/orchestrate/com.infiquetra.claude/commands/orchestrate.md`
   is printed by the script in one fixed format and shown as printed. This is the same problem and
   the same fix as mods U1.
2. **Fleet pane.** A `/fleet-view` command opens a pane from `status --json`, refreshed on a timer.
   It holds no launch, settle or merge actions.
3. **Approval pane.** When orchestrate presents a launch table, the mod shows it with Approve and
   Change buttons. The result returns to the model as the operator's answer. The mod itself never
   launches anything. "Nothing launches until the operator approves the table" stays true.

### Risk

medium
The approval pane sits on the path to launching sessions, so a wrong answer mapping could approve
something the operator did not, though the launch itself still runs through orchestrate's own
commands.

### Out-of-scope / non-goals

- No launch, settle, merge or clean action from any pane.
- No change to orchestrate's model authority boundary: non-Claude models still come from live
  vendor catalogs.

### Files expected to change

- `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`
- `plugins/orchestrate/com.infiquetra.claude/commands/orchestrate.md`
- `plugins/orchestrate/com.infiquetra.claude/` (the fleet and approval modules)
- `plugins/orchestrate/CHANGELOG.md`

### Tests to add or update

- `plugins/orchestrate/tests/test_orchestrate_status_and_notes.py`: `status --json` emits every
  unit with the documented fields.
- `*.test.ts`:
  - fleet rows from fixture JSON;
  - Approve returns approval;
  - Change returns the edit request;
  - neither calls a launch command.

### Context library links

- `plugins/orchestrate/skills/orchestrate/SKILL.md`

### Acceptance criteria

- [ ] `python3 plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py status --issue <N> --json` prints valid JSON with every unit's documented fields.
- [ ] A test shows the approval pane returns the operator's answer and invokes no launch command.
- [ ] `claude plugin test plugins/orchestrate` passes.

### Verification

```bash
python3 plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py status --help
python3 -m pytest plugins/orchestrate/tests -q --import-mode=importlib
claude plugin validate plugins/orchestrate
claude plugin test plugins/orchestrate
git diff --check
```
