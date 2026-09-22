---
name: qa
description: Run the lifecycle's functional test — the prescribed strategy catalogue
argument-hint: "[issue <N>] [--boundary branch-preview]"
---

Load `saga/skills/qa/SKILL.md`. Run the **functional test** on shipped work: after the release step
merged the change and deployed it to the non-production destination, answer "does the shipped thing
actually work?" with prescribed strategies, declared evidence, and a computed verdict.

`/qa` is **prescribed, not improvised**. Code reads the repository profile and the run record,
computes the required strategies from file patterns, lets one advisory judgment widen that set and
never narrow it, preflights the environments and the budget, runs each strategy's driver to exactly
one of `passed` / `failed` / `blocked`, appends one evidence envelope per strategy to the run
record, counts the verdict — `pass` / `pass-with-proof-debt` / `fail` — publishes the per-strategy
statuses as a comment, and routes.

One command does all of it:

```bash
uv run python plugins/saga/scripts/qa_strategies.py run --issue <N>
```

Routing is the exit code: `0` pass, to close; `4` fail, back to the build loop; `5` a required
strategy is `blocked`, which stops for the operator because no build loop repairs a missing
environment, credential or permission; `2` a refusal (no profile, a profile that proves nothing, or
a preflight over the ceiling).

There is no score, no rating, and no model-assigned severity, in any form.

`/qa` does **NOT** fix bugs, does **NOT** edit code, does **NOT** commit, does **NOT** push, does
**NOT** open, update, or merge a PR, does **NOT** deploy, does **NOT** file SDLC issues, and does
**NOT** set readiness labels. It reports, verdicts, and routes — then stops.

Arguments provided to the command:

`$ARGUMENTS`
