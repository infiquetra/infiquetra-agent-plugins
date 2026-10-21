# Review command

`plugins/saga/scripts/review_command.py` is one command with two calls. `prepare` writes the packet for a change. `finish` checks one or two answers and writes the review run. This command does not start a reviewer session. Orchestrate and agent-launcher start sessions. The two callers are `/code-review` (after card C10b) and the corpus harness.

The script is `plugins/saga/scripts/review_command.py`. Saga's version in `plugin.json` is not bumped here.

## Inputs

`prepare` requires `--repo`, `--base`, `--head`, `--profile`, `--builder-record` and `--out`.

`finish` requires `--packet` and one or two pairs of `--answer` and `--result`. The same number of each, and no more than two.

Both calls accept `--issue`, `--card`, `--round` (default 1), `--unit`, `--bank`, `--calibration`, `--store-root` and `--home`. `finish` also accepts `--final`.

`--builder-record` is the builder record for this run. The command does not look one up on a unit row. With `--issue`, the run record must already exist and the unit row must resolve. `--unit` names that row when the record has more than one. `--bank` names a question bank file; without it, `prepare` uses the four approved shipped banks merged into one, the same merge the `/saga:work` path uses. A shipped bank that refuses, because its content no longer matches its approval, degrades the sweep the same way an unreadable `--bank` file does. `--calibration` defaults to the installed saga's calibration file. `--home` is where the sweep cache is written, and where the machine record is read.

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
| `dependencies.json` | issue 262: the head's dependencies for an offline reviewer. `{"schema": "saga.review_dependencies.v1"}`, plus a `rust` entry when the head has a root `Cargo.toml`: `fetched` with `directory` (`dependencies/rust`, relative to the packet) and `crates`, `no-dependencies`, or `not-fetched` with `reason` |

A fetched Rust entry's sources sit in `<packet>/dependencies/rust`, written by `cargo vendor --locked`, which compiles nothing. The fetch works on an export of the head without its `.cargo/` and `rust-toolchain(.toml)`, with a fresh `HOME`, `TMPDIR` and `CARGO_HOME`, and refuses any source other than crates.io and any path outside the head; `plugins/saga/scripts/review_dependencies.py` holds the rules. A lock with no crates.io package counts as `no-dependencies` only when no manifest declares a dependency that is not a path; otherwise `cargo vendor --locked` decides, and a lock it refuses is `not-fetched`. cargo runs under a watcher that stops it and records `not-fetched` once the vendored folder and the fetch's own cargo home, home and temp folder pass `FETCH_MAX_BYTES` (2 GiB) together, and deletes the partial tree. agent-launcher's reviewer and `finish`'s re-run read the folder, never write it, through a cargo home whose `config.toml` replaces crates.io with it, under a name with a random suffix, and turns cargo offline. A commit's own `.cargo/config.toml` outranks that home, so the home's `bin/cargo` runs the real cargo with the same file passed as `--config`, which outranks every config file. It comes first on `PATH`, and `finish` runs a `cargo` command through it directly.

`review_tools.run` may also write `outcomes.json` in the same directory. The stored deterministic run, when `--issue` is set, passes `where_to_look` as `[]` because an unanswered item does not validate. Without `--issue` the run record is not opened.

`finish` writes `<packet>/review-run.json` only after the answer check and, when `--issue` is set, only after the locked update that appends the review run and the usage entries together. A refused answer does not create that file, does not append a review cycle, and does not write usage.

One scratch change is a warning, not a refusal: an added test file that no `reproduced` finding names as its `proof.test`. `finish` prints `warning: scratch.changes: <path> (added) ...` on standard error, records a degraded input for it (`tool` `review-command`, `reason` `uncited-test-file`, `input` the path) so it shows in `review-run.json` and the lens grade's `degraded_inputs`, never lays the file over a re-run tree, and grades the answer's findings as usual. A symlink, Claude configuration, a deletion, a modification and an added file that is not a test are still refused.

A reproduced finding stays reproduced only when this command's own re-run exits non-zero, the cited test is one of the tests that failed in the re-run's output, and the recorded failure is that test's failure. `plugins/saga/scripts/reproduction_match.py` reads the failed tests from cargo test and nextest, pytest, unittest, Vitest, Jest, go test, dart test and swift test (XCTest and Swift Testing) output, matching the test by name and, where the runner prints one, file, so a pass or another test's failure never counts. The recorded failure is the last specific line of the cited test's recorded failure lines (a generic header or a total is not that line), and it has to appear in that test's failure lines in the re-run; a failure the reviewer wrote on one line also matches when the re-run test's own message lines all appear in the recorded output. Colour codes, thread ids, timings, addresses, time stamps, the directory in front of a path and runs of five or more digits are ignored on both sides. Output from no known runner keeps the earlier rule: the recorded line appears in the captured output, and a test id written `file::name` appears word for word. The re-run tree is the packet's head commit with the reviewer's test files laid over it. The re-run is this process, confined. It is not a reviewer session. `--final` runs that check again for blocking findings that still have a command, on a detached worktree of the packet's head, with the same test files.

`prepare` publishes `--out` only after every step has succeeded. A failure leaves that directory uncreated.

## Reproducibility

`prepare` runs the Jev sweep against the merged shipped banks, so it asks the model for answers. The sweep's answers are cached under `--home` at `.saga/review-sweep/<head sha>/`, keyed on the state, the questions and the requested model. The reproducibility boundary is that cache.

- A run whose cache is fully warm, replayed with the same frozen inputs, reuses the cached answers and can repeat its results.
- A run whose cache is cold makes independent model calls. Those calls are not deterministic, so two cold runs over the same change can differ. Cache reuse stabilizes Jev's answers; identical packets also require unchanged tool outputs and complete cache coverage for the same inputs.

The cache is consulted before the API key is resolved, so a warm cache stays usable without `TYPESAFE_API_KEY` set, and a cold run without that key makes no request and degrades the sweep with a `no-key` reason.

The cache transport is charged as no spend. A run that stopped on the spend cap or on unpriced usage can therefore cover more questions on a later replay, when those answers come from the cache instead of the model. That expansion is a property of the spend accounting, not a change in the provider's behaviour, and it is not suppressed.

## Posting to Langfuse

After `finish` writes `review-run.json` (and, with `--issue`, the run record), it posts the run to Langfuse through `review_trace.post_review_run` (issue 166). The post never changes a record or the exit status: any failure prints one `langfuse:` line on standard error and the review carries on.

- **What is sent:** one trace with an entry per tool, the Jev sweep, each reviewer result (vendor, model, configuration fingerprint, tokens, cost and time), the formula and each finding, with each finding's excerpt at the head commit. Raw tool output leaves only as its SHA-256; a secret-scanner finding sends its location only. The repository is named by its `owner/name` slug. Round 2 and 3 runs also post whether they found anything new.
- **Visibility** is read from `.saga-profile.json` at the base commit. A private or unrecorded repository posts only over `https`.
- **When it cannot go:** the post waits in `<home>/.saga/langfuse-queue/` with its reason (`--home` sets the home) and goes with the next post once the reason clears. `review_trace.py status` counts what waits.

`plugins/fleet-core/references/langfuse.md` holds the full rule, the trace layout and the score names.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The packet or the review run was written. An all-degraded review still exits 0. A missing tool is a degraded input and does not stop the review. A differing reviewer configuration is noted and does not refuse the run. |
| 1 | An answer was refused. Nothing new is written. An uncited added test file does not refuse an answer; see the warning above. |
| 2 | Bad invocation, an unreadable file, an unknown commit, a record or an answer file that does not validate, more than two answers, a mismatched answer and result count, a missing run record, a unit row that does not resolve, or an open-search cap that is not a non-negative integer. Nothing new is written. |

`prepare` and `finish` both use these codes. Exit 1 is only `finish`: `prepare` has no answer to refuse.
