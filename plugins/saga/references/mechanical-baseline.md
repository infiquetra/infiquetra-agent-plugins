# The mechanical baseline and the build loop's exit criterion

The build loop's finish line is written down before the first line of code, and this document is
the contract for it. `plugins/saga/scripts/build_loop.py` reads the criterion, runs it, and records
every result on the unit's row in the run record; `tests/test_build_loop.py` fails if this document
and the code disagree about the record block's key set or the exit-code table, so the two cannot
drift apart silently.

**Source of the check map:** `infiquetra/infiquetra-sdlc` at revision `5efc869f` —
`config/lens-catalogue.json` for `mechanical_checks` (the check-to-dimension map and its six rules)
and `docs/lifecycle/run-model.md` step 5 for the exit criterion and the branch-preview rule. The
combined-branch pass follows the run model at revision `e5a2be10`, section "Prove the combined
branch works, before review", which issue #174 there added.

## What the criterion is made of

Five parts, each read from somewhere that already holds it. Nothing here is judged at the end of
the work.

| Part | Where it is read from |
|---|---|
| The mechanical baseline | `run_configuration.mechanical_tool_baseline` in the run record, filled at admission from `.saga-profile.json` |
| The child-scoped functional checks | the unit's row, key `functional_checks` |
| The branch preview deployment | `admission.branch_preview` in the record, plus the optional `branch_preview_command` in `.saga-profile.json` |
| The scenario smoke | the unit's row, key `scenario_smoke` |
| The functional-test environment, or its waiver | `admission.functional_test_environment` in the record; for a record admitted before issue #97, the `functional_test_environment` or `functional_test_waiver` block in `.saga-profile.json` |

## The catalogue's rules, quoted

These are the lens catalogue's own `mechanical_checks.rules` at revision `5efc869f`, not a
paraphrase. The third and the fifth are the ones that shape this module's behaviour.

1. A failing required check caps the dimension it maps to at 5, which is below every level's floor.
2. A measured value maps through the check's bands; the band is a ceiling, never the score itself.
3. A passing check never awards the top band where judgment remains.
4. Missing evidence cannot pass. A dimension with no evidence is not a high score with a caveat.
5. An unexecutable check yields could-not-execute and an environment problem, never a pass and
   never a fail.
6. Implementation results are primary evidence, and a reviewer may re-run them rather than take
   them on trust.

## The check map

The catalogue names four checks for the `python` stack. The loop matches a baseline command to a
check by the tool's name appearing as an argument token, by basename, so `uv run ruff check .` and
`/opt/bin/ruff check .` both answer `ruff`. A command no check claims is reported as a
repository-specific entry, which is information rather than an error: a repository may run more
than the catalogue names.

| Catalogue check | The catalogue's statement of it | Result kind |
|---|---|---|
| `ruff` | lint and format conformance for Python source | pass-or-fail, caps at 5 on failure |
| `mypy` | static type checking in **strict mode** | pass-or-fail, caps at 5 on failure |
| `bandit` | static security analysis of Python source | pass-or-fail, caps at 5 on failure |
| `pytest-coverage` | measured statement coverage of the changed code, against the standard's 80 percent floor | measured |

The catalogue's pinned version for every one of the four reads `UNKNOWN` and is owned by the
organisation context library. This document cites the checks and re-declares no version, which is
the catalogue's own rule C1e: the context library is cited, not edited.

### This repository, with every divergence named

Measured on `infiquetra/infiquetra-claude-plugins` at commit `87a5329e`. A divergence is named
here and changed nowhere: closing one is a repository-wide decision, and the build loop's job is to
report the criterion honestly, not to widen it on its own authority.

| Catalogue check | This repository's command | Divergence |
|---|---|---|
| `ruff` | `uv run ruff check .` and `uv run ruff format --check .` | none; both match `.github/workflows/ci.yml` |
| `mypy` | `uv run mypy plugins/ scripts/ tests/ --ignore-missing-imports` | **not `--strict`**, and missing imports are ignored. It matches what continuous integration runs, so the profile and the workflow agree with each other and both diverge from the catalogue |
| `bandit` | **none** | **uncovered.** See below |
| `pytest-coverage` | `uv run pytest tests/ plugins/*/tests/ -q` | **no coverage measurement in the command.** Continuous integration measures it (`--cov=plugins`) and `scripts/gate.sh` checks its own coverage against the workflow; the profile's baseline entry does not |

### Why bandit is uncovered here, with the measurement

Bandit is installed in this repository (`pyproject.toml`, `bandit>=1.7`) and continuous integration
runs it **advisory**: the step at `.github/workflows/ci.yml:282` ends with `|| true`, so a bandit
finding has never blocked a merge here. Measured on the same commit:

```
uv run python -m bandit -r plugins/ scripts/ tests/ tools/ -ll -q
  Total lines of code: 231188
  Medium: 136    High: 9    (exit 1)
```

Adding that command to the profile's `mechanical_tool_baseline` would make the build loop unable to
reach green on its first iteration and on every iteration after it, for 145 findings that predate
the card that built this loop. A loop that can never go green is a refusal wearing a loop's
clothes, and the loop's own rule is that a failing check is an iteration and never a refusal. So
bandit is reported by `--dry-run` as an uncovered catalogue check rather than promoted into the
baseline, and widening the baseline is a `.saga-profile.json` change that belongs in its own card.

Issue 1027 recorded the alternative it did not take: the operator may prefer bandit left advisory
as continuous integration has it, promoted whole after a clean-up card, or scoped to the unit's own
diff — the third needing a profile field `repository_profile.v1` does not have.

### The named scanners

The card that built this loop names four security and dependency scanners as baseline entries
"where configured": `pip-audit`, `gitleaks` or `detect-secrets`, and `semgrep`. None of them is
configured in this repository — none appears in `pyproject.toml`, in `.github/workflows/ci.yml`, or
in any configuration file. The dry run reports each by name as not configured rather than dropping
the clause silently. They are reported separately from an uncovered catalogue check, because a tool
a repository has never configured is a different fact from a catalogue check whose baseline command
is missing.

## The functional-test environment

The repository declares, once, how a change is functionally tested before code review: the kind of
environment, its deploy-or-start, test and teardown commands, and whether it is private or shared.
A repository where functional testing does not apply records a waiver with its reason instead. The
shape, the waiver and the migration from `branch_preview` are in
`plugins/saga/references/repository-profile.md`.

The loop reads it, never chooses it, and records it in `exit_criterion.environment`. The dry run
prints it: the kind and scope and the three commands, or `Functional-test waiver` with its reason,
or `not declared — admission asks for it`. A profile still on the legacy `branch_preview` keys reads
as an incomplete declaration and the dry run says which field is missing. A declaration the loop
could not use (an unknown kind, no test command) is a refusal, exit 2, naming the field.

**A unit iteration does not run it.** The lifecycle at infiquetra-sdlc `e5a2be10` runs the
deployed or started check once, on the combined branch, before code review, and a shared
non-production stack only ever receives the combined branch. Running it per unit would break that,
so it runs in the combined-branch pass below (issue #99). The per-unit branch preview below still
runs for records admitted before issue #97.

## The branch preview

The per-unit branch preview is legacy. Admission no longer asks `branch_preview`, so a record
admitted after issue #97 records `no-preview-declared` here; the table below still governs a record
admitted before it.

The lifecycle repository's run model at `5efc869f`, step 5: "Where the repository declares a
branch preview, the unit's exit criterion also includes a branch preview deployment and a scenario
smoke run against that preview... Where the repository declares no preview, the criterion does not
apply and no unit is held back by it."

Three cases, and the loop errors in none of them:

| `admission.branch_preview` | `branch_preview_command` in the profile | What the loop records |
|---|---|---|
| false | anything | `no-preview-declared`, and the iteration can still be green |
| true | declared | the command runs; `pass` or `fail` as it exits |
| true | absent | `could-not-execute`, detail "the profile declares a preview but names no command" |

The third case is the catalogue's unexecutable-check rule applied to a deployment. Guessing a
deployment command is the one class of guess that can do real damage, so the loop records the gap
instead of inventing a command.

`branch_preview_command` is an **optional** key in `.saga-profile.json`; it is documented in
`plugins/saga/references/repository-profile.md` and `repository_profile.v1` does not change,
because a profile without it stays valid.

## The functional checks and the scenario smoke

The Planner writes them. `/plan` puts each unit's checks in a fenced `functional-checks` block and
the plan's smoke in a `scenario-smoke` block (the grammar is in
`plugins/saga/skills/plan/references/plan-sections.md`), and §5.3a copies them onto the unit rows
with `python3 plugins/saga/scripts/functional_checks.py write --plan <path> --issue <N>`: each
unit's own checks as `functional_checks`, and the plan's smoke as `scenario_smoke` on every unit
row. Each entry is one object:

| Key | Holds |
|---|---|
| `name` | the check's name, unique in the plan |
| `command` | the command line, run with no shell |
| `proves` | the acceptance criteria it proves, as `AC-<n>`, the criterion's position in the issue's list |
| `runs` | `local`, run in the unit's iteration, or `environment`, run against the declared functional-test environment on the combined branch |

The loop also reads an entry written before issue #98: a `{name, command}` object or a bare
command string, which runs locally. The recorded criterion keeps `proves` and `runs`, and the dry
run prints them beside each command. With no `--unit` on a record with more than one row, the dry
run lists every unit's checks under its id, and the smoke once when every unit carries the same
list.

**An `environment` check is recorded and deferred, not run, in a unit iteration.** It runs once on
the combined branch before code review (pre-review testing U4). A list whose every entry is
deferred records the reason `deferred-to-combined-branch`.

An absent or empty list reads as an **empty list** and the iteration records the reason
`none-prescribed`, and the dry run prints `none prescribed in the run record`. That still happens
for a unit the plan gave no checks, and for a run whose functional testing is waived. Without that
reason a reader of a green iteration could not tell "the plan prescribed none" from "the plan
prescribed three and the loop lost them", and those are very different facts about the same green.

## The combined-branch pass

After integration and before code review, the combined branch is built, deployed or started,
tested and torn down through the environment the repository declared, and that pass is repeated
until it is green (issue #99, the lifecycle's combined-branch functional run). `/work` runs it once
the merge turn reports every lane merged; a single-lane run, with nothing to integrate, runs it on
its one branch. Every entry into code review goes through it, including a repaired branch coming
back from review or from the post-merge `/qa` repair loop.

```bash
uv run python plugins/saga/scripts/build_loop.py --record <path> --repo-root <combined checkout> --combined
```

**One invocation is one pass**, in this order:

1. **Build.** The mechanical baseline runs on the combined revision. When it is not green, nothing
   is deployed and the pass records why in `skipped_reason`.
2. **Lease**, when the environment's scope is `shared`. See the next section. A private
   environment records `{"required": false, "status": "not-required"}`.
3. **Deploy or start**, through `deploy_command`. A `local` environment may declare none, and the
   step records `not-declared`.
4. **Test.** The declared `test_command`, then every plan check marked `runs: environment` on any
   unit row and the plan's scenario smoke, each once (`environment_checks`). They run only when the
   deploy succeeded or was not declared.
5. **Tear down**, through `teardown_command`, whenever the deploy step was reached: after a pass, a
   failed deploy, a failed test, a timeout, a missing program or an interrupt. A missing teardown
   records `not-declared`. The lease is released after it.

Each step is classified so an environment problem never reads as a defect in the code:

| Step | Exits zero | Exits non-zero | Missing program, timeout, unparseable |
|---|---|---|---|
| baseline | `pass` | `fail` | `could-not-execute` |
| deploy | `pass` | `could-not-execute`, with its exit code kept | `could-not-execute` |
| test and environment checks | `pass` | `fail` | `could-not-execute` |
| teardown | `pass` | `could-not-execute`, an environment problem | `could-not-execute` |
| lease | acquired | held by another run or another invocation of this run, or the remote unreachable: `could-not-execute` | — |

A pass is `fail` when any baseline, test or environment check failed; otherwise
`could-not-execute` when any step could not execute, the lease was not taken or not released, or
the pass was interrupted; otherwise `pass`. Every environment detail is listed in
`environment_problems`. **A failing test is a loop pass, exit 4**, fixed on the combined branch as
ordinary implementation work and never a review finding.

**Three consecutive could-not-execute passes are an environment stop, exit 5.** The loop prints
the three passes' environment problems for the operator. It is an exit code, not a refusal to run:
the next invocation still runs, and a pass that is not could-not-execute resets the streak.
Waiting on a held lease counts toward it, so a lease left by a dead run surfaces to the operator
after three passes rather than looping forever.

**A repository-level waiver runs the baseline only.** The pass records `waiver` with the level and
reason, and a green pass hands the revision to review with `waived: true`. A run-level waiver (the
Planner's, for a change that carries no code) is not on the run record yet and is not read here.

**Refusals, exit 2**, before anything runs: no declaration and no waiver, an incomplete
declaration, a declaration that names production in its kind, a command or its lease (a tripwire
that reads `prod` and `production` as words, not `nonprod`, `non-prod`, `pre-prod` or `product`;
the declaration stays the authority), a multi-lane run with a unit still to merge or a revision
that does not contain a recorded merge, and a shared lease whose remote the checkout does not have.
No production deployment exists on any path.

`--dry-run --combined` prints the baseline, the environment, the environment-bound plan checks, the
lease's reference and remote, and whether integration is complete, and runs and writes nothing.
`--lease-wait <seconds>` bounds the wait on a held lease, defaulting to 1,800.

### The shared-environment lease

A shared environment takes one run at a time, and the lease must be visible to every host that can
deploy to it, so a lock file in one checkout is not enough. `plugins/saga/scripts/environment_lease.py`
keeps it as the git reference `refs/saga/leases/<name>` on the declared remote, which every
deploying host already pushes to. `<name>` and the remote come from the declaration's optional
`lease` block and default to `shared-nonprod` on `origin`
(`plugins/saga/references/repository-profile.md`).

- **Acquire** is a compare-and-swap push: a commit on the empty tree whose message is the holder,
  pushed with `--force-with-lease=<ref>:` (an empty expected value: only if the reference does not
  exist) and `--no-verify`, so a repository's pre-push hook does not run for it.
- **The holder** names the repository, the issue, the revision under test, a short host label, the
  start time, the bound the pass expected to finish within, the pass number, and an `invocation`
  nonce drawn once per `build_loop.py --combined` invocation. The pass's `lease` block on the run
  record keeps the same `invocation` and the object id (`token`) it was given.
- **Release** is a compare-and-swap delete with the object id acquire returned. Another run's lease
  is never deleted by a release.
- **A second run waits**, polling every 30 seconds up to `--lease-wait`, and prints the holder on
  each poll. When the wait runs out the pass is could-not-execute and names the holder.
- **One invocation holds a lease, and no other invocation takes it over** (issues #139 and #140).
  Acquire never replaces an existing holder: not another run's, and not one left by an earlier
  invocation of this same run, on this host or another. A pass number cannot prove the earlier
  invocation finished, because any other invocation of the run that records a pass (one that gave
  up after `--lease-wait`, for instance) moves the count while the holder is still deploying. The
  later invocation waits and reports the holder, as for any other run.
- **A crashed invocation's lease is released by the operator.** Its holder outlives its bound and is
  reported `STALE`, with the `release --expect <object id>` command below; until someone runs it,
  every invocation of every run waits on it, and three waits in a row are an environment stop.
- **The start time and the pass number are read when the lease is taken**, not when the wait
  began. A lease won after waiting is not reported stale the moment it is taken, and it names the
  pass number the record hands out at that moment, after every pass that landed during the wait.
- **A stale lease is reported, never broken.** Past its bound it is described as `STALE` with the
  command that releases it, and the operator decides:

```bash
python3 plugins/saga/scripts/environment_lease.py --repo-root . --remote origin status --name shared-nonprod
python3 plugins/saga/scripts/environment_lease.py --repo-root . --remote origin release --name shared-nonprod --expect <object id>
```

This lease is not the run record's lock, and the run record stays a file with no lease in it
(`references/run-record.md`).

### The combined-branch record

One run-level key, `combined_branch`, at the top of the run record, because the combined branch is
not a unit. `run_record.v1` does not change: the key round-trips as an unknown top-level field, as
orchestrate's `orchestrate` block does. The pass is landed on a record re-read under the record's
file lock, after the pass ran with no lock held.

<!-- BEGIN COMBINED-BRANCH BLOCK -->

| Key | Type | Holds |
|---|---|---|
| `environment` | object | the declared environment or waiver the latest pass ran with |
| `passes` | array | one entry per invocation, in order, never replaced |
| `handed_to_code_review` | object | `{revision, at, pass, waived}`, written on a green pass only |

<!-- END COMBINED-BRANCH BLOCK -->

<!-- BEGIN COMBINED PASS KEYS -->

| Key | Type | Holds |
|---|---|---|
| `pass` | integer | 1 upward |
| `revision` | string | the full forty-character commit identifier the pass ran at |
| `branch` | string | the checked-out branch, or null |
| `started_at` | string | ISO-8601 timestamp in UTC |
| `finished_at` | string | ISO-8601 timestamp in UTC |
| `status` | string | `pass`, `fail` or `could-not-execute` |
| `green` | boolean | the status is `pass` |
| `baseline` | array | one result per baseline command |
| `lease` | object | `required`, `status`; when required also `remote`, `ref`, `invocation` (this invocation's nonce), `token`, `holder` (with its `pass_number` and `invocation`), `waited_seconds`, `release_status`, `detail` |
| `deploy` | object | the deploy result, `not-declared`, or null when not reached |
| `test` | object | the declared test command's result, or null when not reached |
| `environment_checks` | array | one result per environment-bound plan check and scenario smoke |
| `teardown` | object | the teardown result, `not-declared`, or null when the deploy step was not reached |
| `environment_problems` | array | one line per environment problem, for the operator |

<!-- END COMBINED PASS KEYS -->

Three keys appear only when they apply: `waiver` (`{level, reason}`) on a waived pass,
`skipped_reason` when a step was not reached, and `interrupted: true` on a pass an interrupt or
`SIGTERM` cut short, which is recorded before the interrupt is re-raised.

`build_loop.functional_evidence(record, revision)` is how a reader asks whether a revision carries
a passing combined-branch functional run: it admits a revision whose latest pass is green, waived
or not, and reports `missing` or `failed` otherwise. A green pass at another revision admits
nothing, and a later pass at the same revision that did not go green withdraws an earlier green
one. Three readers ask it (issue #100): the review gate `--handoff`, the cycle-cap check in
`review_result.py`, and the closeout in `release_step.py close`.

### The review gate

Code review starts only from `--handoff`, which reads the record and writes nothing:

```bash
uv run python plugins/saga/scripts/build_loop.py --record <path> --repo-root <combined checkout> --handoff
uv run python plugins/saga/scripts/build_loop.py --record <path> --handoff --revision <full sha>
```

It checks the checkout's `HEAD`, or the revision `--revision` names. **Exit 0** prints one JSON
object, `{revision, pass, status, waived, waiver_reason, environment, deploy, test, teardown}`,
only when the latest combined pass at that revision is green, or green under the repository's
waiver. **Exit 2** prints one line naming what is missing: no combined pass and no waiver at the
revision, a latest pass that is `fail` or `could-not-execute`, or `HEAD` having moved some number
of commits since the green pass. A green unit loop alone admits nothing. The review-gate override
is an acceptance override and does not reach this gate; the recorded waiver is the only exception,
and the closeout prints its reason.

## The record block

One key, `build_loop`, on the unit's row inside the record's `units` array. `run_record.v1` does
not change: `plugins/saga/references/run-record.md` states that a unit row's key set is
deliberately not fixed, because a row is one consumer's working state rather than a cross-consumer
contract, and issue 1025 added three keys under the same rule. A key another consumer put on the
same row is left alone.

<!-- BEGIN BUILD-LOOP BLOCK -->

| Key | Type | Holds |
|---|---|---|
| `exit_criterion` | object | the criterion as it was read: `baseline`, `functional_checks`, `scenario_smoke`, `preview`, `environment` (the declared functional-test environment or waiver, or null) |
| `iterations` | array | one entry per invocation, in order, never replaced |
| `handed_to_code_review` | object | `{revision, at}`, written on the green iteration only |

<!-- END BUILD-LOOP BLOCK -->

<!-- BEGIN ITERATION KEYS -->

| Key | Type | Holds |
|---|---|---|
| `iteration` | integer | 1 upward |
| `revision` | string | the full forty-character commit identifier the iteration ran at |
| `started_at` | string | ISO-8601 timestamp in UTC |
| `finished_at` | string | ISO-8601 timestamp in UTC |
| `green` | boolean | every result is `pass`, and the preview is `pass` or `no-preview-declared` |
| `baseline` | array | one result per baseline command |
| `functional_checks` | array | one result per prescribed functional check |
| `preview` | object | `declared`, `status`, `command`, `detail` |
| `scenario_smoke` | array | one result per prescribed smoke scenario |

<!-- END ITERATION KEYS -->

Each result carries `name`, `command`, `catalogue_check`, `status`, `exit_code`,
`duration_seconds` and `detail`. `catalogue_check` is `null` for a repository-specific entry.

`handed_to_code_review.revision` is a **full forty-character commit identifier**, because
`/code-review` Phase 0.2 freezes exactly that value and refuses an abbreviation or a symbolic
reference such as `HEAD`, and its staleness rule counts commits since it.

## The three statuses

<!-- BEGIN STATUSES -->

| Status | When |
|---|---|
| `pass` | the check ran and exited zero |
| `fail` | the check ran and exited non-zero |
| `could-not-execute` | the program is not installed, the check did not finish within the timeout, or the command does not parse into an argument vector |

<!-- END STATUSES -->

The third is the catalogue's fifth rule: an unexecutable check is never a pass and never a fail.
Collapsing it into `fail` would make an environment problem look like a defect in the code, and
collapsing it into `pass` would let a missing tool report green.

## Exit codes

<!-- BEGIN EXIT CODES -->

| Code | Meaning |
|---|---|
| 0 | green — every check passed, or `--dry-run` printed the criterion |
| 1 | an unexpected internal error |
| 2 | a refusal: an unresolvable store root, an unreadable record, no record at that path, no such unit, or an unnamed unit where one is required; for `--combined`, also no declaration and no waiver, a production tripwire, units still to merge, or no lease remote; for `--handoff`, no green combined pass at the revision under review |
| 3 | an unknown record version |
| 4 | **not green yet** — the iteration ran and at least one entry is `fail` or `could-not-execute` |
| 5 | **environment stop** — the third consecutive could-not-execute combined pass; it names the environment problems for the operator |

<!-- END EXIT CODES -->

The first four are `run_record.py`'s table unchanged, so a caller learns one set of codes for both
modules. **Exit 4 is not a refusal**, and it is a distinct code precisely so a caller cannot read
it as one: the instruction on seeing it is to implement again and run the loop again. A build loop
that refused would be the gate the loop replaced, wearing a new name. **Exit 5 is not a refusal
either**: the code is not the problem, the environment is, and only the operator can fix that.

## Command line

```bash
# print the criterion; run nothing, write nothing
uv run python plugins/saga/scripts/build_loop.py --record <path> --dry-run

# run one iteration against a unit and record it
uv run python plugins/saga/scripts/build_loop.py --issue <N> --unit <id>
uv run python plugins/saga/scripts/build_loop.py --record <path> --unit <id>

# after integration, before review: one combined-branch pass, or print it
uv run python plugins/saga/scripts/build_loop.py --record <path> --repo-root <combined checkout> --combined
uv run python plugins/saga/scripts/build_loop.py --record <path> --combined --dry-run

# the review gate: print the revision to review, or refuse; writes nothing
uv run python plugins/saga/scripts/build_loop.py --record <path> --repo-root <combined checkout> --handoff
uv run python plugins/saga/scripts/build_loop.py --record <path> --handoff --revision <full sha>
```

`--store-root <dir>` overrides the record store's resolution; `--repo-root <dir>` names the
repository, which is both where `.saga-profile.json` lives and whose `HEAD` the iteration records,
and is the directory every check runs in; `--profile <path>` reads the profile from somewhere else
without moving the repository. All three exist for the tests and for reading a record that belongs
to another checkout. `--timeout <seconds>` bounds one check, defaulting to 1,800.

**One invocation is one iteration.** The loop does not repeat by itself: the only thing that
changes between iterations is the code, and only the worker can change that. "Repeat until green"
is an instruction to the worker, in `plugins/saga/skills/work/SKILL.md`.

**A command never reaches a shell.** The profile's baseline entries are tracked configuration, and
they are split with `shlex.split` and run as an argument vector with `shell=False`. An entry that
does not split into a runnable vector is recorded `could-not-execute` with the parse error.

**Globs are expanded by the loop, not by a shell.** This repository's own baseline carries
`uv run pytest tests/ plugins/*/tests/ -q`, and the loop found the consequence on its first real
run: with no shell, `plugins/*/tests/` reached pytest as a literal path, pytest said
`ERROR: file or directory not found`, and the loop recorded a `fail` that was indistinguishable
from a real test failure. So each argument token carrying `*`, `?` or `[` is expanded against the
repository root the way a shell would expand it, and `shell=False` stays. A token that matches
nothing is passed through unchanged — also what a shell does — because the program's own error
about the path it was handed is clearer than the loop silently dropping the argument.

**Every check runs from the repository root.** Which directory a check runs in decides what it
checks, so `--repo-root` names it rather than the loop inheriting whatever directory the caller
happened to be in. `--profile` is separate from it: a caller that wants a different profile is not
thereby asking for a different repository, and conflating the two moved the revision lookup to a
directory that was not a checkout.

## Related

- `plugins/saga/references/run-record.md` — the record this block lives in.
- `plugins/saga/references/repository-profile.md` — the per-repository defaults the criterion reads.
- `plugins/saga/skills/work/SKILL.md` — the build loop that runs this, and repeats it until green.
- `plugins/saga/skills/code-review/SKILL.md` — what the green revision is handed to.
