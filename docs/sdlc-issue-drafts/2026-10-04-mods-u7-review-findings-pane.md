---
title: mods U7 — Review findings pane
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: low
handoff_maturity: requirements-ready
approval_state: approved
---

# mods U7 — Review findings pane

### Objective

Show the current code review's results in a pane: one row per lens, its outcome, and its findings.
The operator can then work through a review without reading raw JSON or a long comment.

### Intent

1. A `/review-view` command, and a button on the run status band, open a pane built from the run
   record's latest review result.
2. The pane has one row per selected lens, showing whether the lens met its bar, did not, or could
   not run, and how many findings it has, with the top findings listed.
3. Choosing a lens lists its findings with their `file:line` citations. A button on a finding
   quotes it into the prompt.
4. The pane refreshes when the record's review result changes.

### Risk

low
It is read-only display of a result the review already wrote.

### Out-of-scope / non-goals

- No acceptance decision and no finding edits from the pane.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/` (the review findings module)
- `plugins/saga/com.infiquetra.claude/types/index.d.ts`

### Tests to add or update

- `*.test.ts` on terminal and desktop:
  - rows from a fixture review result;
  - a lens that could not run is shown as such, not as a low score;
  - quoting a finding fills the prompt.

### Context library links

- `plugins/saga/skills/code-review/SKILL.md`

### Acceptance criteria

- [ ] Given a fixture review result, the pane lists one row per selected lens with its outcome and finding count, shown by a test.
- [ ] A lens with no usable result is labeled as not run, shown by a test.
- [ ] `claude plugin test plugins/saga` passes the review pane tests.

### Verification

```bash
claude plugin validate plugins/saga
claude plugin test plugins/saga
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/d07-review-findings-pane.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/d07-review-findings-pane.md
- Source type: brainstorm
- Source title: mods U7 — Review findings pane

### Recommended Tier Band
opus/high

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/108
- Number: 108
- Created at: 2026-10-04T01:55:47.679814+00:00
