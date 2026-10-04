---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# Claude Code mods for saga and orchestrate

### Objective

Give operators who run saga and orchestrate inside Claude Code seven mods, enabled by default in
the plugins' Claude adapters. A mod is a TypeScript module Claude Code loads from a plugin's hooks
file. These seven fix things operators currently work around by hand: badly formatted staffing
tables, plans readable only in another tool, run state that is hard to see, and subagents that are
only asked, never configured, to run at an effort level.

### Intent

**Verified 2026-10-03** against Claude Code 2.1.289's own API declarations and a validated probe
plugin. A mod can:

- open panes, draw a band above the prompt, set a status-line entry, and show toasts;
- register slash commands, and tools the model can call;
- watch, block or rewrite tool calls;
- redraw transcript rows, including the AskUserQuestion dialog and tool results;
- read and write files, run host commands, make HTTP requests, and keep state for the session and
  across sessions;
- render Markdown, tables included;
- register agent types that carry both a model and an effort.

A hook on each model request (`turn.step`) can also see and set the model and effort of any
subagent's requests. One hooks file can hold both a plugin's existing command hooks and a mod;
`claude plugin validate` accepted the mix.

**Limits that shape the designs.**

- The API is early access and changes between releases.
- A Markdown block holds at most 10,000 characters.
- A pane opened unasked needs a terminal at least 144 columns wide; one opened by a command fits
  any width, which matters in herdr's split panes.
- Mods run only in Claude Code.

**Operator rulings, settled 2026-10-03, binding on every child.**

1. All seven mods ship, enabled by default in the plugins' Claude adapters. They are not opt-in.
2. Saga's and orchestrate's scripts own state. Mods display it and collect answers, writing back
   only through those scripts. Every mod has a plain fallback the other harnesses use.
3. A mod never enforces policy on its own. Enforcement stays in the scripts.

**The seven mods.**

| Mod | What it adds |
|---|---|
| U2 | A review pane for admission's staffing (question 4) and lens (question 5) answers |
| U3 | A plan viewer pane |
| U4 | A run status band above the prompt, plus a status-line entry |
| U5 | Saga roles registered as Claude agent types carrying real model and effort |
| U6 | Live token capture per unit into the run record |
| U7 | A review findings pane |
| U8 | An orchestrate fleet pane and launch-approval table |

U0 lays the foundation. U1 is the plain fixed-format table every harness uses, and U2 builds on it.

**Dependency graph.**

- U0 comes before every mod.
- U1 comes before U2.
- The staffing parent's U1 (the implementation shape and one resolver) comes before U5.
- The staffing parent's U3 (cost per completed unit in the run record) comes before U6.
- U2 also reads the staffing parent's Jev results (its U4) and the lens-proposal card's results.

### Risk

medium
The mods load in every Claude Code session that has these plugins, so a loader regression reaches
every operator. The policy each mod displays is enforced elsewhere.

### Out-of-scope / non-goals

- No mod for Codex, Grok, Agy or any other harness; their fallbacks are the plain tables.
- No change to policy, gates or lifecycle behaviour through a mod.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/hooks.json`
- `plugins/saga/.claude-plugin/plugin.json`
- `plugins/orchestrate/com.infiquetra.claude/plugin.json`
- `plugins/saga/scripts/admission.py`
- `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`
- `.github/workflows/ci.yml`
- `scripts/check_repo.py`

### Tests to add or update

Each mod carries `*.test.ts` files run by `claude plugin test`, looped over the terminal and desktop
surfaces. Python tests cover the plain fallbacks and the new machine-readable outputs.

### Context library links

- `docs/engineering-journal/DECISIONS.md` — "Claude installs the package root", 2026-08-25

### Acceptance criteria

- [ ] Every child issue closes with its own acceptance criteria met.
- [ ] `claude plugin validate plugins/saga` and `claude plugin validate plugins/orchestrate` pass in CI.
- [ ] `claude plugin test` passes for both plugins in CI.

### Verification

```bash
claude plugin validate plugins/saga
claude plugin validate plugins/orchestrate
claude plugin test plugins/saga
claude plugin test plugins/orchestrate
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```
