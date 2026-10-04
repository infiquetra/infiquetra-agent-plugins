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
  "main_consumed_directly": false,
  "functional_test_environment": {
    "kind": "local",
    "test_command": "uv run pytest tests/functional -q",
    "scope": "private"
  },
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

It also settles two admission questions that are repository facts rather than run choices:
`main_consumed_directly`, and the functional-test environment below. Both are among the questions
admission asks, and both have the same answer every time for a given repository — which is exactly
what a profile is for.

## The functional-test environment, or a waiver

Every code-bearing run proves its change works before code review: it builds the combined branch,
deploys or starts it, runs the functional suite derived from the issue's acceptance criteria, and
tears it down. The repository says once, here, how that is done. Saga never chooses the mechanism.
This is the lifecycle's repository declaration at infiquetra-sdlc `e5a2be10` (the run model's
combined-branch functional run).

```json
"functional_test_environment": {
  "kind": "ephemeral-stack",
  "deploy_command": "make stack-up BRANCH=$BRANCH",
  "test_command": "make functional",
  "teardown_command": "make stack-down BRANCH=$BRANCH",
  "scope": "private"
}
```

| Field | Required | Holds |
|---|---|---|
| `kind` | yes | `local` (built and started on the host doing the work), `emulator` (a local emulation of the repository's cloud services, such as LocalStack), `ephemeral-stack` (a stack created for this branch alone) or `shared-nonprod` (the repository's shared non-production stack) |
| `deploy_command` | yes, except for `local` | what builds and deploys, or starts, the change |
| `test_command` | yes | what runs the functional suite against it |
| `teardown_command` | no | what tears it down; when present it runs on every exit path, including a failed pass |
| `scope` | yes, except for `shared-nonprod` | `private` to the branch, or `shared`. `shared-nonprod` is always `shared`: omit the scope or say `shared`; `private` is refused |

On a `shared-nonprod` stack only the combined branch is deployed, one run at a time, right before
review; units still run their local checks first (parent ruling 3 of issue #91). Running the
commands is pre-review testing U4: admission and the build loop read, check, record and print the
declaration, and nothing in this change runs it.

### The waiver

A repository where functional testing does not apply, such as a documentation-only catalog, records
a waiver instead:

```json
"functional_test_waiver": {"reason": "documentation only: nothing here runs"}
```

The reason is required; a waiver without one is refused. A profile that carries both
`functional_test_environment` and `functional_test_waiver` is refused, because the two are
alternatives and choosing between them is the operator's call. This is the lifecycle's
**repository-level** waiver, supplied only by the operator. The other kind, a run-level waiver for a
change that carries no code, is written by the Planner in the plan and is not part of this file.

Admission records which one the run used at `admission.functional_test_environment` in the run
record: `{"mode": "declared", <the five fields>, "source": ...}` or `{"mode": "waived", "level":
"repository", "reason": ..., "source": ...}`, where `source` is `profile` or `operator`. The build
loop's dry run prints it.

### Migration from `branch_preview`

The block replaces `branch_preview` and `branch_preview_command`, which earlier profiles carried for
a per-unit branch preview. Admission reads an old profile like this, and asks once:

| Old profile | Read as | What admission does |
|---|---|---|
| `branch_preview: true` and a `branch_preview_command` | an incomplete declaration: `kind` `ephemeral-stack`, `scope` `private`, `deploy_command` the old command, no `test_command` | asks the question once, with those values as its default, so the operator confirms or changes them and adds the test command |
| `branch_preview: true` and no command | the same, with `deploy_command` missing too | asks once, with the kind and scope as the default |
| `branch_preview: false`, or neither key | nothing declared | asks once |

The plugin never takes the migrated values as an answer: the old keys said a preview existed, not
how to test against it. When the operator answers, the write-back removes both legacy keys.
`branch_preview_command` is still read by the build loop's legacy per-unit preview for records
admitted before issue #97; see `plugins/saga/references/mechanical-baseline.md`.

The remaining nine parameters come from elsewhere and are not the profile's business:
`staffing_models_and_efforts` from the staffing component in fleet-core; `applicable_lenses` and
`per_lens_score_threshold` from the lens catalogue; and `standard_cycle_allowance`,
`escalated_cycle_allowance`, `escalation_trigger`, `lens_execution_recovery`, `repair_custody` and
`unfinished_testing_response` from the lifecycle repository's decided defaults or the operator.

## Editing it

Two ways, and both go through review.

**Admission writes the functional-test declaration once.** When the operator answers the
functional-test question, `admission.py` writes the answer into `.saga-profile.json` under the
`--repo-root` it ran with (the working directory by default, which is the checkout `/plan` writes
the plan into). It keeps every other key and its place, removes the alternative key and both legacy
keys, and creates the file with `"schema": "repository_profile.v1"` when there is none. The write is
atomic, and it happens before the run record is saved, so a failed write leaves the question
outstanding rather than recorded. `--dry-run` writes nothing. Commit the file with the run's other
changes: the declaration then reaches review in that run's pull request, and every later worktree
sees it.

**Everything else is edited by hand, in a pull request**, like any other tracked configuration. A
value changed here changes what admission stops asking, so the change belongs in review rather than
in a run.
