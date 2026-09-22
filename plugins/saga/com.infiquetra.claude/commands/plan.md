---
name: plan
description: Create a durable Infiquetra implementation plan
argument-hint: "[issue, requirements doc, or request]"
---

Load `saga/skills/plan/SKILL.md` and run its phases.

`/plan` answers "How should it be built?" — it interrogates the HOW (assuming the WHAT came from
`/brainstorm` or the issue), writes a durable agent-consumable plan under `docs/plans/`, records a plan
saga, and routes to `/doc-review` then `/work`. It does not implement code, file SDLC issues, or run
the review gauntlet.

When the argument is a handoff issue, use its `Handoff maturity` and `Source context` sections before
planning. Store non-trivial plans under `docs/plans/` and record the plan saga via
`scripts/saga.py save` under the git-ignored `.claude/saga/` (never `git add` the
saga tick).

Arguments provided to the command:

`$ARGUMENTS`
