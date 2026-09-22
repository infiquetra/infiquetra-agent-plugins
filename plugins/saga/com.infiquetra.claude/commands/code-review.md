---
name: code-review
description: Run a structured Infiquetra code review and pre-PR gate
argument-hint: "[diff, branch, PR, or scope]"
---

Load `saga/skills/code-review/SKILL.md` and run the code-quality review engine at the
work-to-PR boundary: scope the merge-base diff, audit built-vs-planned, run judgment-selected lenses,
validate findings, write a durable `docs/code-reviews/` artifact, and route.

`/code-review` is a **gate, not a fixer**: it hands findings back rather than fixing them. In
interactive / standalone mode it may publish its own review artifact (write, commit, push the review
document) and submit the GitHub pull-request review on an existing PR (evidence only — the artifact
names the exact revision reviewed); in every mode it does not mutate reviewed source, commit an
implementation change, open PRs, or file issues. When an active work-thread saga exists, it appends
the artifact path to `review_paths` (scan-first, never mint, never advance `lifecycle_phase`) and never
`git add`s the tick. Respect the hard boundary in every mode — the publication lane is interactive-mode
only.

Arguments provided to the command:

`$ARGUMENTS`
