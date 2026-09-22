# Test and Gates — what holds around the build loop

What `/work` does around the build loop: how it finds and shapes tests while implementing, how it runs
the criterion against the merged state, and how it reads the code review's typed outcome afterwards.
Test mechanics adapted from CE `ce-work`; the merge-base and staleness/readiness machinery from gstack
`ship` / `land-and-deploy`.

**What green means is not here.** The exit criterion — the mechanical baseline, the plan's functional
checks, the branch preview, the scenario smoke — is written in the run record at admission and is run by
`plugins/saga/scripts/build_loop.py`. Its contract is
`plugins/saga/references/mechanical-baseline.md`. The risk-gated hard test gate that used to live in
this file was removed in issue #1027: it asked a worker to decide, at the end of its own work, which
change kinds deserved tests, and a written criterion read before the work replaces that judgment. The
guidance below still shapes the tests a worker writes; it no longer decides whether the work may
proceed.

## Test discovery

Before implementing changes to a file, find its existing test files — search for test/spec files that
import, reference, or share naming patterns with the implementation file. When the plan names test
scenarios or test files, start there, then check for additional coverage the plan did not enumerate.
Implementation changes must be accompanied by matching test updates: new tests for new behavior, modified
tests for changed behavior, removed/updated tests for deleted behavior.

## Scenario completeness (four categories)

Before writing tests for a feature-bearing unit, check the plan's `Test scenarios` against the four
categories. If a category is missing or scenarios are vague ("validates correctly" without naming inputs
and expected outcomes), supplement from the unit's own context first:

| Category | When it applies | Derive if missing |
|---|---|---|
| **Happy path** | Always for feature-bearing units | The unit's Goal/Approach core input→output pairs |
| **Edge cases** | Meaningful boundaries (inputs, state, concurrency) | Boundary values, empty/nil inputs, concurrent access |
| **Error / failure paths** | Failure modes (validation, external calls, permissions) | Invalid inputs to reject, auth/permission denials, downstream failures to handle |
| **Integration** | Crosses layers (callbacks, middleware, multi-service) | The cross-layer chain — exercise it without mocks |

## System-wide test check

Before marking a task done, trace two levels out from the change:

- **What fires when this runs?** Callbacks, middleware, observers, event handlers, `after_*` hooks on the
  models/objects you touched. Read the actual code, not docs.
- **Do my tests exercise the real chain?** If every dependency is mocked, the test proves logic in
  isolation only. Write at least one integration test using real objects through the full
  callback/middleware chain — no mocks for the interacting layers.
- **Can failure leave orphaned state?** If state is persisted before a risky external call, test the
  failure path with real objects: failure cleans up, or retry is idempotent.
- **What other interfaces expose this?** Mixins, DSLs, alternative entry points. Grep for the
  method/behavior in related classes; add parity now, not as a follow-up.

**Skip** for leaf-node changes with no callbacks, no state persistence, no parallel interfaces (purely
additive helpers). **Matters most** for changes touching models with callbacks, error handling with
fallback/retry, or behavior exposed through multiple interfaces.

## Merge-base before tests

Fetch the base branch and test against the merged state, so tests reflect what actually lands — not stale
local state that omits commits landed on the base since this branch was cut:

```bash
git fetch origin <base> --quiet
git merge origin/<base> --no-edit   # or: test against $(git merge-base origin/<base> HEAD)
```

If the merge has conflicts, resolve simple ones (e.g. CHANGELOG ordering) and stop on anything ambiguous.
Run the suite after merging the base.

## Change kinds, recorded rather than gated

`change_kinds` is still derived and still recorded in the work-session writeup, because a later reader
wants to know what kind of change this was. It no longer decides anything: the exit criterion is
written in the run record before the work starts, so nothing here weighs a change kind against a test
and concludes that the work may or may not proceed.

Derive it from the plan's unit types and the `parse_issue.py` flags (`has_security`, `has_infra`,
`has_api`). Pass `--flags` to `parse_issue.py` to widen those keyword flags with a model judgment: the
union can only add a flag, never remove one, and a client failure returns the keyword result unchanged.
The keys and their meaning are identical either way.

## Review-readiness gate (the hard PR gate)

Before PR-ready, run `/code-review` programmatically (SKILL Phase 5.1), deserialize its
`review_result.v1` envelope, and use `outcome` as the sole acceptance decision:

- **`accepted`** — the review acceptance gate passes.
- **`repairs_requested`** — block PR-ready and route the typed fix requests through Work.
- **`cycle_cap_best_available`** — proceed with the cycle-three revision and surface every residual.
- **`review_incomplete`** — block PR-ready because delivery did not establish a review.

Do not derive another acceptance decision from finding Priority, confidence, or fix-request counts.
Those values remain reporting and routing metadata.

### Stale review (computed from `/work`'s own captured SHA)

`/code-review` in programmatic mode writes no durable artifact (the caller owns persistence) and the saga
has no `reviewed_sha` field — so `/work` captures the reviewed commit **itself** at review time and
computes staleness directly, with no dependency on `/code-review`'s output format:

1. At the moment `/work` runs `/code-review` (SKILL Phase 5.1), capture
   `REVIEWED_SHA=$(git rev-parse HEAD)` and record it in the work-session.
2. Compute commits since the review:
   ```bash
   git rev-list <REVIEWED_SHA>..HEAD --count
   ```
   A count `> 0` means commits landed since the review → **stale**. Re-run `/code-review` (capturing a
   fresh `REVIEWED_SHA`) before any PR-open or merge offer.

This is the same commits-since-review staleness gstack's review dashboard uses, computed against `/work`'s
own captured reviewed SHA rather than a stored field or a parse of `/code-review`'s artifact.

### Override (recorded, never silent)

Allow an explicit operator override of either block **only with a recorded rationale** — it flows into the
issue comment via `issue_progress.py --doc-review-override` and into the work-session writeup. A silent
skip of the review gate is forbidden (Jeff's no-lies rule; SKILL core principle 6).

## Autonomy contract (gstack stop-for / never-stop-for)

`/work`'s build loop runs without ceremony, but pauses at the judgment points. Adapted from gstack `ship`,
constrained to the PR-ready boundary (deploy/canary belong to `deploy`):

**Stop for (pause and ask):**

- On the default branch with no branch decision made (never commit to the default branch without explicit
  confirmation).
- Merge conflicts that cannot be auto-resolved (show them).
- In-branch test failures (fix before proceeding; do not push past a red suite).
- The hard review gate firing (a blocking typed outcome or a stale review) with no recorded override.
- The hard test gate firing on a risky change-kind with no tests and no recorded rationale.
- Any **outward GitHub mutation**: PR-open, review-request, and merge are each explicitly confirmed.
- A PR-state transition that needs operator judgment (CLOSED-unmerged; ambiguous saga match).

**Never stop for (just do it):**

- Uncommitted in-branch changes (include them).
- Incremental-commit message wording (auto-compose conventional messages).
- Work-session content (auto-write).
- Choosing the *subagent* execution strategy (inline/serial/parallel) — that is mechanical judgment, not
  an operator choice (the **backend** offer is the operator choice, and it is surfaced).
- Re-running a verification step on re-entry (idempotent: re-verify, only the actions are skip-if-done).

**Iron law:** no completion or "PR-ready" claim without fresh verification evidence. If code changed after
the last test run, re-run before claiming the gate passed. "Should work now" / "I'm confident" / "I tested
earlier" are not evidence — run it.
