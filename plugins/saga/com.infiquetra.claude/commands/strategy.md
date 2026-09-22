---
name: strategy
description: Create or maintain the repository root STRATEGY.md — the durable direction anchor
argument-hint: "[optional: section to revisit, e.g. 'metrics' or 'approach']"
---

Load `saga/skills/strategy/SKILL.md` and run the interview-driven strategy engine.
Maintain the root `STRATEGY.md` as the durable direction anchor — target problem, approach, who it's
for, key metrics, and tracks.

Route by file state first (Phase 0): no `STRATEGY.md` -> first-run interview; an existing file plus a
named section -> targeted update; an existing file with no argument -> ask which section to revisit.
Run the section interview with two-round pushback from `references/interview.md`, fill
`references/strategy-template.md`, present the draft, then write the root `STRATEGY.md`.

`/strategy` **records** direction — it does not challenge it (`/founder-review` does), does not check
readiness (`/doc-review` does), and does not implement, write plans, file SDLC issues, or write the
saga. Downstream, `/ideate`, `/brainstorm`, and `/plan` read `STRATEGY.md` for grounding.

Treat `$ARGUMENTS` as an optional section-to-revisit focus hint (e.g. `metrics`, `approach`, `tracks`).

`$ARGUMENTS`
