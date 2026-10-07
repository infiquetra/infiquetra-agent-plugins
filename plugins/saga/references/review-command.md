# Review command

`plugins/saga/scripts/review_command.py` is one command with two calls. `prepare` writes the packet for a change. `finish` checks one or two answers and writes the review run. This command does not start a reviewer session. Orchestrate and agent-launcher start sessions. The two callers are `/code-review` (after card C10b) and the corpus harness.

The script is `plugins/saga/scripts/review_command.py`. Saga's version in `plugin.json` is not bumped here.

## Inputs

`prepare` requires `--repo`, `--base`, `--head`, `--profile`, `--builder-record` and `--out`.

`finish` requires `--packet` and one or two pairs of `--answer` and `--result`. The same number of each, and no more than two.

Both calls accept `--issue`, `--card`, `--round` (default 1), `--unit`, `--bank`, `--calibration`, `--store-root` and `--home`. `finish` also accepts `--final`.

`--builder-record` is the builder record for this run. The command does not look one up on a unit row. With `--issue`, the run record must already exist and the unit row must resolve. `--unit` names that row when the record has more than one. The question bank defaults to `plugins/saga/references/question-bank.json`. This card does not author that file. `--calibration` defaults to the installed saga's calibration file. `--home` is where the sweep cache is written, and where the machine record is read.

The commit under review does not choose the calibration file or the profile that decides whether a lens may block. Those come from the installed saga and from the base commit's `.saga-profile.json`.

## Outputs

`prepare` writes these files under `--out`. JSON is indented two spaces, with keys sorted, and a trailing newline. There is no clock and no timestamp.

| File | Holds |
|---|---|
| `change.json` | resolved repository path, full base and head SHAs, and each file's path and status |
| `diff.patch` | `git diff --find-renames` between those SHAs |
| `findings.json` | tool findings, in the input form the formula computes |
| `measurements.json` | tool measurements |
| `degraded.json` | degraded inputs, including a missing tool, a known gap, and a skipped sweep |
| `builder-record.json` | the `--builder-record` file |
| `where-to-look.json` | sweep items, then one item per missing tool or known gap. No answer yet |
| `missing-tools.json` | the question a reviewer answers when a tool did not run |
| `may-block.json` | each lens and language, with the bool and the reason line |
| `open-search-cap.json` | `{"cap": 5}` unless a later caller changes the file before `finish` |
| `grades.json` | the formula over the tool findings, measurements, builder record, degraded inputs and may-block bools |

`review_tools.run` may also write `outcomes.json` in the same directory. The stored deterministic run, when `--issue` is set, passes `where_to_look` as `[]` because an unanswered item does not validate. Without `--issue` the run record is not opened.

`finish` writes `<packet>/review-run.json` only after the answer check and, when `--issue` is set, only after the locked update that appends the review run and the usage entries together. A refused answer does not create that file, does not append a review cycle, and does not write usage.

A reproduced finding stays reproduced only when this command's own re-run exits non-zero and the recorded output line appears in the captured output. The re-run is this process, confined. It is not a reviewer session. `--final` runs that check again for blocking findings that still have a command, on a detached worktree of the packet's head.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The packet or the review run was written. An all-degraded review still exits 0. A missing tool is a degraded input and does not stop the review. A differing reviewer configuration is noted and does not refuse the run. |
| 1 | An answer was refused. Nothing new is written. |
| 2 | Bad invocation, an unreadable file, an unknown commit, a record or an answer file that does not validate, more than two answers, a mismatched answer and result count, a missing run record, a unit row that does not resolve, or an open-search cap that is not a non-negative integer. Nothing new is written. |

`prepare` and `finish` both use these codes. Exit 1 is only `finish`: `prepare` has no answer to refuse.
