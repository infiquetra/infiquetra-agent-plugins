---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# mods U5 — Saga roles as Claude agent types with real model and effort

### Objective

In Claude Code, run saga's role subagents at the model and effort the staffing resolver chose,
through registered agent types. Today they are asked to use an effort level in their prompt text.
Also show when a subagent runs at a tier its role did not resolve to.

### Intent

Today the fleet honors effort for a Claude subagent through a prompt rider. In
`plugins/fleet-core/references/staffing.md` it is "a labeled proxy", because the agent-spawn path
had no effort parameter. Claude Code's mod API now lets a plugin register an agent type that
carries a model and an effort.

1. At session start, and whenever the run record's staffing changes, the mod registers one agent
   type per saga role, such as `saga:builder`. Each type uses the role's prompt from the roles
   library, and the model and effort from the single resolver delivered by the staffing parent's U1.
2. `/work`'s direct spawns in Claude Code use those agent types. The prompt rider remains the
   fallback for every other harness.
3. A hook on each subagent request compares the model and effort actually sent with the role's
   resolved tier. A mismatch shows a toast and writes a `tiering-drift` line, the same name
   `reconcile_effort` already uses. The mod does not rewrite the request.
4. Check whether a plain `agents/*.md` file's `effort` field is honored by Claude Code too. If so,
   record it in `staffing.md` as a second route.

### Risk

high
It changes the model and effort real subagents run at, which changes cost and quality for every
Claude run.

### Out-of-scope / non-goals

- No rewriting of a subagent's model or effort by the mod; it registers and reports.
- No change to non-Claude vendors.

### Inputs inventory

- `plugins/fleet-core/references/staffing.md` — the effort-honoring section and `reconcile_effort`.
- `plugins/agent-launcher/roles/` — the role prompts.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/` (the agent-type module)
- `plugins/saga/com.infiquetra.claude/types/index.d.ts`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/skills/work/references/execution-strategy.md`
- `plugins/fleet-core/references/staffing.md`
- `plugins/fleet-core/scripts/fleet_commons/effort_rider.py`

### Tests to add or update

- `*.test.ts`:
  - types are registered with the resolver's model and effort for each role;
  - re-registration happens after a staffing change;
  - a drifted subagent request produces a toast and a `tiering-drift` line;
  - a matching one produces none.
- `plugins/fleet-core/tests/`: the rider path is unchanged for non-Claude spawn kinds.

### Failure modes / pre-mortem

- A registered type's prompt drifts from the roles library. The type is built from the library file
  at registration, never copied.

### Stop conditions

- Stop if registering agent types would change behavior for a session with no saga run.

### Context library links

- `plugins/fleet-core/references/staffing.md`

### Acceptance criteria

- [ ] A test shows `saga:builder` registered with `opus` and `medium` when the resolver says so.
- [ ] A test shows a drifted subagent request produces a `tiering-drift` line and a matching one does not.
- [ ] `staffing.md` describes the registered-type route and keeps the rider as the fallback.

### Verification

```bash
claude plugin validate plugins/saga
claude plugin test plugins/saga
python3 -m pytest plugins/fleet-core/tests -q --import-mode=importlib
git diff --check
```
