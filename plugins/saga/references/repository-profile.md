# The repository profile — `.saga-profile.json`

The admission step asks the operator only for what it cannot work out. This file is where the rest
comes from: the facts that are true of a repository rather than of one run, so they are answered
once per repository instead of once per issue.

## Where it lives, and why there

```
<repository root>/.saga-profile.json          # tracked in git
```

Tracked, at the root, on purpose. The obvious alternative — `.saga/repository-profile.json`, beside
the existing tier overlay — fails for a specific reason: `.saga/` is git-ignored in this repository,
so a fresh clone or a fresh worktree would see no profile and admission would ask questions that are
already answered. That is the same class of failure the run record itself is designed around, and it
would be odd to reintroduce it in the file whose whole job is to stop questions being re-asked.

A missing profile is not an error. Every parameter it would have filled simply stays `unset` and
joins the question set.

## Shape

```json
{
  "schema": "repository_profile.v1",
  "repo": "infiquetra/infiquetra-claude-plugins",
  "concurrency_allocation": 10,
  "nonproduction_destination": "none",
  "branch_preview": false,
  "main_consumed_directly": false,
  "mechanical_tool_baseline": [
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run mypy plugins/ scripts/ tests/ --ignore-missing-imports",
    "uv run pytest tests/ plugins/*/tests/ -q"
  ],
  "preflight_checks": [
    "the plan cleared /doc-review with nothing above P3 open",
    "the work branch exists and is not the default branch"
  ]
}
```

## Which run-configuration parameters it fills

Four of the thirteen, named in `run-record.md`:

| Parameter | What the profile supplies |
|---|---|
| `concurrency_allocation` | how many lanes this repository's work may run at once |
| `nonproduction_destination` | which lower environment a run deploys to, or `none` where the repository has none |
| `mechanical_tool_baseline` | the commands that constitute "green" for this repository's stack |
| `preflight_checks` | the checks planning performs before implementation starts |

It also supplies two admission answers that are repository facts rather than run choices:
`branch_preview` and `main_consumed_directly`. Both are among the questions the card lists, and both
have the same answer every time for a given repository — which is exactly what a profile is for.

## One optional key, for the build loop

| Key | Type | Holds |
|---|---|---|
| `branch_preview_command` | string, optional | what the build loop runs to deploy a branch preview, in a repository whose `branch_preview` is `true` |

It is **optional**, so a profile without it stays valid and `repository_profile.v1` does not change.
It is written down here rather than only read in code because a key one consumer reads and no
document describes is precisely the drift this repository keeps tests for.

Where `branch_preview` is `true` and this key is absent, the build loop records the preview as
`could-not-execute` with the reason "the profile declares a preview but names no command". It does
**not** guess a deployment command: guessing a deployment is the one class of guess that can do
real damage. Where `branch_preview` is `false` the key is ignored and the loop records
`no-preview-declared`. Both cases are in
`plugins/saga/references/mechanical-baseline.md` under "The branch preview".

The remaining nine parameters come from elsewhere and are not the profile's business:
`staffing_models_and_efforts` from the staffing component in fleet-core; `applicable_lenses` and
`per_lens_score_threshold` from the lens catalogue; and `standard_cycle_allowance`,
`escalated_cycle_allowance`, `escalation_trigger`, `lens_execution_recovery`, `repair_custody` and
`unfinished_testing_response` from the lifecycle repository's decided defaults or the operator.

## Editing it

By hand, in a pull request, like any other tracked configuration. A value changed here changes what
admission stops asking, so the change belongs in review rather than in a run.
