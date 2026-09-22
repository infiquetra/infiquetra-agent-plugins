# The mechanical baseline and the build loop's exit criterion

The build loop's finish line is written down before the first line of code, and this document is
the contract for it. `plugins/saga/scripts/build_loop.py` reads the criterion, runs it, and records
every result on the unit's row in the run record; `tests/test_build_loop.py` fails if this document
and the code disagree about the record block's key set or the exit-code table, so the two cannot
drift apart silently.

**Source of the check map:** `infiquetra/infiquetra-sdlc` at revision `5efc869f` —
`config/lens-catalogue.json` for `mechanical_checks` (the check-to-dimension map and its six rules)
and `docs/lifecycle/run-model.md` step 5 for the exit criterion and the branch-preview rule.

## What the criterion is made of

Four parts, each read from somewhere that already holds it. Nothing here is judged at the end of
the work.

| Part | Where it is read from |
|---|---|
| The mechanical baseline | `run_configuration.mechanical_tool_baseline` in the run record, filled at admission from `.saga-profile.json` |
| The child-scoped functional checks | the unit's row, key `functional_checks` |
| The branch preview deployment | `admission.branch_preview` in the record, plus the optional `branch_preview_command` in `.saga-profile.json` |
| The scenario smoke | the unit's row, key `scenario_smoke` |

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

## The branch preview

The lifecycle repository's run model, step 5: "Where the repository declares a branch preview, the
unit's exit criterion also includes a branch preview deployment and a scenario smoke run against
that preview... Where the repository declares no preview, the criterion does not apply and no unit
is held back by it."

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

No step in saga writes these onto a unit's row yet. The run model puts them at step 2, written by
the Planner, and the card that built this loop did not build that writer.

So an absent key reads as an **empty list** and the iteration records the reason
`none-prescribed`, and the dry run prints `none prescribed in the run record`. Without that reason
a reader of a green iteration could not tell "the plan prescribed none" from "the plan prescribed
three and the loop lost them", and those are very different facts about the same green.

## The record block

One key, `build_loop`, on the unit's row inside the record's `units` array. `run_record.v1` does
not change: `plugins/saga/references/run-record.md` states that a unit row's key set is
deliberately not fixed, because a row is one consumer's working state rather than a cross-consumer
contract, and issue 1025 added three keys under the same rule. A key another consumer put on the
same row is left alone.

<!-- BEGIN BUILD-LOOP BLOCK -->

| Key | Type | Holds |
|---|---|---|
| `exit_criterion` | object | the criterion as it was read: `baseline`, `functional_checks`, `scenario_smoke`, `preview` |
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
| 2 | a refusal: an unresolvable store root, an unreadable record, no record at that path, no such unit, or an unnamed unit where one is required |
| 3 | an unknown record version |
| 4 | **not green yet** — the iteration ran and at least one entry is `fail` or `could-not-execute` |

<!-- END EXIT CODES -->

The first four are `run_record.py`'s table unchanged, so a caller learns one set of codes for both
modules. **Exit 4 is not a refusal**, and it is a distinct code precisely so a caller cannot read
it as one: the instruction on seeing it is to implement again and run the loop again. A build loop
that refused would be the gate the loop replaced, wearing a new name.

## Command line

```bash
# print the criterion; run nothing, write nothing
uv run python plugins/saga/scripts/build_loop.py --record <path> --dry-run

# run one iteration against a unit and record it
uv run python plugins/saga/scripts/build_loop.py --issue <N> --unit <id>
uv run python plugins/saga/scripts/build_loop.py --record <path> --unit <id>
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
