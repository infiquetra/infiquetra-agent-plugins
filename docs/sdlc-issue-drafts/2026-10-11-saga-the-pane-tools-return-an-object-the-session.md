---
title: saga: the pane tools return an object the session rejects, and the setup pane shows no steps
repo: infiquetra-agent-plugins
type: defect
team: asgard
project: operations
labels: defect, needs-plan
handoff_maturity: requirements-ready
stage: Shaping
status: Discovering
risk: medium
approval_state: approved
---

# saga: the pane tools return an object the session rejects, and the setup pane shows no steps

### Objective

Make saga's three pane tools (`mcp__saga__setup`, `mcp__saga__review_admission`, `mcp__saga__review_merge`)
return a result the Claude Code session accepts, so the operator's choice in a pane reaches the agent. Make the
setup pane show the optional steps and stop dead-ending when nothing on screen can be installed.

### Intent

On 2026-10-11, Claude Code 2.1.296 ran `/saga:setup`. The setup pane opened, but the agent's
`mcp__saga__setup` call failed at once with "tool.call step resolved mcp__saga__setup with a result that does
not match its output shape … expected string, received object". Each `tool.call` hook in
`plugins/saga/com.infiquetra.claude/mods/setup-pane.tsx` returns `{ result: { status, ... } }` with an object
as the result. The admission-review and merge-confirmation panes do the same in every return path. The session
accepts only a string or a list of content blocks, so none of the three panes can report back. The
merge-confirmation pane gates merges, so its failure blocks the review lifecycle.

CI runs `claude plugin validate --strict` and `claude plugin test` on Claude Code 2.1.286 and 2.1.289 only, and
passes. A working hypothesis, not yet verified: a later build tightened the result check. The fix must hold on
the newest build as well as the pinned ones.

The setup pane has two further faults:

- **No steps:** it lists only tool rows. The survey's optional steps never appear, so `outcome-schedule`,
  added by #214, cannot be run from the pane.
- **Dead end:** when no visible row has an install command, pressing Install shows "Tick at least one tool
  with an install command." in red. That leaves the operator nothing to do but Done or Dismiss.

### Out-of-scope / non-goals

- Shipping these fixes to installed copies. The saga version bump belongs to #147's saga release step.
- Changing which tools the survey selects, or adding install commands for rows that have none.
- A CI rule that forces a plugin version bump when plugin content changes. If wanted, it is a separate card.

### Files expected to change

- plugins/saga/com.infiquetra.claude/mods/setup-pane.tsx
- plugins/saga/com.infiquetra.claude/mods/admission-review.tsx
- plugins/saga/com.infiquetra.claude/mods/merge-confirmation.tsx
- plugins/saga/com.infiquetra.claude/mods/setup-pane.test.tsx
- plugins/saga/com.infiquetra.claude/mods/admission-review.test.ts
- plugins/saga/com.infiquetra.claude/mods/merge-confirmation.test.tsx
- plugins/saga/skills/setup/SKILL.md
- .github/workflows/ci.yml
- plugins/saga/CHANGELOG.md

### Tests to add or update

- For each pane tool, a test that every return path yields a string (or content blocks) that parses back to
  the documented status object: submitted, dismissed, not-placed, unavailable, nothing-to-review, timed-out
  and error.
- A setup-pane test that steps from the survey render with their done state and can be run by name.
- A setup-pane test that, when no row has an install command, the pane says so and offers only Done.
- Add the newest Claude Code build to the CI matrix, so a tightened result check fails in CI first.

### Context library links

_none_

### Acceptance criteria

- [ ] Each of the three pane tools returns a value the session accepts on Claude Code 2.1.296 and on every
  build in the CI matrix: `claude plugin test plugins/saga` passes on each.
- [ ] In a live session, `mcp__saga__setup` returns its status to the agent. Dismiss returns `dismissed`, and
  an install returns `submitted` with the installed and failed ids.
- [ ] The setup pane lists the survey's optional steps with their done state and runs a step the operator
  picks through `saga_setup.py step --name`.
- [ ] With no installable row, the setup pane shows no red error and explains that nothing here installs.
- [ ] `/saga:setup` in SKILL.md still falls back to the script survey when the pane returns anything but
  submitted.

### Verification

```bash
claude plugin validate --strict plugins/saga
claude plugin test plugins/saga
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

Then run `/saga:setup` in a live Claude Code session, press Dismiss, and confirm the agent receives `dismissed`.

### Risk

medium

The merge-confirmation pane gates merges, and the change touches every pane's return path; tests cover each
status.

### Notes / conventions

Found during #147 card K2's operator steps. Fix before #147's saga release, so the release ships working panes
and the `outcome-schedule` step together.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-11-saga-pane-results/defect.md

### Source context
- Source: docs/brainstorms/2026-10-11-saga-pane-results/defect.md
- Source type: brainstorm
- Source title: saga: the pane tools return an object the session rejects, and the setup pane shows no steps

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/218
- Number: 218
- Created at: 2026-10-11T13:52:00.413071+00:00
