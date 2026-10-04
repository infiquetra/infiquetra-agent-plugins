---
title: mods U6 — Live per-unit token capture for Claude sessions
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: medium
handoff_maturity: requirements-ready
approval_state: approved
---

# mods U6 — Live per-unit token capture for Claude sessions

### Objective

Record each Claude session's token usage into the run record unit it is working, as it happens.
Cost per completed unit then comes from live data instead of being reconstructed from transcripts.

### Intent

1. A turn-complete hook reads the turn's usage: uncached input, cache read, cache writes and
   output, with the model and effort. It covers the main thread and every subagent loop.
2. The mod resolves which unit the session belongs to from its working directory and branch,
   against the run record's units. Orchestrate launches each unit in its own worktree. A session
   with no matching unit records nothing.
3. Usage is batched and written through `run_record.py usage add`, the portable writer added by the
   staffing parent's U3. The write happens on a short timer and at session end, not as one process
   per turn.

### Risk

medium
It writes to the shared run record from every Claude unit session, but only through the record's
own append command.

### Out-of-scope / non-goals

- Pricing and the report belong to staffing U3.
- No capture for non-Claude vendors.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/` (the usage capture module)
- `plugins/saga/com.infiquetra.claude/types/index.d.ts`

### Tests to add or update

- `*.test.ts`:
  - usage from a main-thread turn and a subagent turn lands on the right unit;
  - a session outside any unit writes nothing;
  - writes are batched;
  - a session end flushes.

### Context library links

- `plugins/saga/references/run-record.md`

### Acceptance criteria

- [ ] A test shows a turn's usage appended to the matching unit through `run_record.py usage add`.
- [ ] A test shows a session in an unrelated directory writes nothing.
- [ ] `claude plugin test plugins/saga` passes the capture tests.

### Verification

```bash
claude plugin validate plugins/saga
claude plugin test plugins/saga
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/d06-live-token-capture.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/d06-live-token-capture.md
- Source type: brainstorm
- Source title: mods U6 — Live per-unit token capture for Claude sessions

### Recommended Tier Band
opus/high

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/107
- Number: 107
- Created at: 2026-10-04T01:55:29.076951+00:00
