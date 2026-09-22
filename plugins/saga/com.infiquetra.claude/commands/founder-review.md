---
name: founder-review
description: Review strategy, ambition, positioning, and scope from a founder/operator perspective
argument-hint: "[plan, strategy, feature, or PR]"
---

Load `saga/skills/founder-review/SKILL.md` and run the CEO/founder-mode scope and
ambition review engine. Detect the target type (plan / strategy / brainstorm / scope-question), run
the adapted system audit, challenge the premise, select one of the four committed scope modes
(SCOPE EXPANSION / SELECTIVE EXPANSION / HOLD SCOPE / SCOPE REDUCTION), run the per-expansion opt-in
ceremony, apply the CEO patterns + Prime Directives as scope lenses, write a
`docs/founder-reviews/` scope-decision artifact, and route in a closed loop.

`/founder-review` is a **review, not an implementer**: it challenges scope, ambition, timing, and
direction and captures decisions — it does **not** make code changes, commit, push, open PRs, file
SDLC issues, or `git add` anything. Keep it separate from `/strategy`: this review *challenges* the
direction; `/strategy` *records* it. On a `STRATEGY.md` it is the *ambition* lens and `/doc-review`
the *readiness* lens. Accepted scope routes to `/plan`, then back to `/doc-review` (readiness) and
`/code-review` (code) with the artifact path. Respect the hard boundary in every mode.

Arguments provided to the command:

`$ARGUMENTS`
