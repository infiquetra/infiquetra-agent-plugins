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
| `where-to-look.json` | the scripted checks' own items (for instance each machine-specific value on an added line), the sweep's items, then one item per missing tool or known gap, written in canonical order. A scripted item is a fact and is never dropped; the sweep's cap of 60 bounds only the sweep's items, so a packet can hold more than 60. An item that repeats an earlier one's lens, language, location, classifier and question ids is kept once. Inside an item the questions are listed by Jev probability, highest first. No answer yet |
| `missing-tools.json` | the question a reviewer answers when a tool did not run |
| `may-block.json` | each lens and language, with the bool and the reason line |
| `open-search-cap.json` | `{"cap": 5}` unless a later caller changes the file before `finish` |
| `grades.json` | the formula over the tool findings, measurements, builder record, degraded inputs and may-block bools |
| `dependencies.json` | issue 262: the head's dependencies for an offline reviewer. `{"schema": "saga.review_dependencies.v1"}`, plus a `rust` entry when the head has a root `Cargo.toml`: `fetched` with `directory` (`dependencies/rust`, relative to the packet) and `crates`, `no-dependencies`, or `not-fetched` with `reason` |
| `check/` | the reviewer's own answer checker, copied byte for byte from this saga's `scripts/`: `reviewer_answer.py`, `review_formula.py`, `review_records.py`, `run_record.py` and `reproduction_match.py`. A reviewer runs `python3 <packet>/check/reviewer_answer.py check --answer <draft> --items <packet>/where-to-look.json` to see what saga's check would say, and fixes it before answering. For a reproduced finding it can also run its own test command, save the complete output to a file, and run `python3 <packet>/check/reviewer_answer.py output-match --answer <draft> --finding <key> --output <captured-output-file> [--exit-code <code>]` to see whether the finding's recorded `proof.output` would match saga's re-run, using saga's own matcher; it explains a recorded failure header with no failure body, or a one line summary, and runs nothing itself. It needs no network, no key and no model. The copy is advice, not authority: saga checks the answer itself at `finish` with the original checker, the launcher's record of the reviewer's scratch changes and its own re-run of the reproduction tests. A packet written before this directory existed has no `check/` and is still valid; its `finish` flow is unchanged |

A fetched Rust entry's sources sit in `<packet>/dependencies/rust`, written by `cargo vendor --locked`, which compiles nothing. The fetch works on an export of the head without its `.cargo/` and `rust-toolchain(.toml)`, with a fresh `HOME`, `TMPDIR` and `CARGO_HOME`, and refuses any source other than crates.io and any path outside the head; `plugins/saga/scripts/review_dependencies.py` holds the rules. A lock with no crates.io package counts as `no-dependencies` only when no manifest declares a dependency that is not a path; otherwise `cargo vendor --locked` decides, and a lock it refuses is `not-fetched`. cargo runs under a watcher that stops it and records `not-fetched` once the vendored folder and the fetch's own cargo home, home and temp folder pass `FETCH_MAX_BYTES` (2 GiB) together, and deletes the partial tree. agent-launcher's reviewer and `finish`'s re-run read the folder, never write it, through a cargo home whose `config.toml` replaces crates.io with it, under a name with a random suffix, and turns cargo offline. A commit's own `.cargo/config.toml` outranks that home, so the home's `bin/cargo` runs the real cargo with the same file passed as `--config`, which outranks every config file. It comes first on `PATH`, and `finish` runs a `cargo` command through it directly.

`review_tools.run` may also write `outcomes.json` in the same directory. The stored deterministic run, when `--issue` is set, passes `where_to_look` as `[]` because an unanswered item does not validate. Without `--issue` the run record is not opened.

`finish` writes `<packet>/review-run.json` only after the answer check and, when `--issue` is set, only after the locked update that appends the review run and the usage entries together. A refused answer does not create that file, does not append a review cycle, and does not write usage.

`finish` also writes `<packet>/consequence-picks.json` right after it converts the answers, before any re-run. It is a JSON array (indented two spaces, keys sorted, trailing newline) with one entry per reproduced finding, in answer order and then the reviewer's finding order, so a run can tell why a finding's `consequence_jev` is `null`. Each entry holds `answer` (the index of the answer file), `finding_id`, `reviewer_consequence`, `jev_pick` (the consequence Jev gave that cleared the floor, or `null`), `status`, `request`, `jev_value`, `jev_confidence`, `floor` and `reason`. `status` is `accepted`, `below-floor` (Jev chose a value on the list, but with confidence under the verb's floor; the value and confidence are kept), `off-list` (the value is not one of the closed consequences), `no-answer` (the request succeeded but carried no consequence, or a choice with no value), `request-failed` (`request` holds the client status, such as `error` or `timeout`, and `reason` its note) or `not-asked`. `jev_value` and `jev_confidence` are `null` when Jev gave nothing to record; `floor` is `null` only for `not-asked`. An off-list value, and the `reason` that repeats it, are scrubbed of secret shapes and cut to 200 characters. The file is a sidecar only: it is not a degraded input, `finish` prints no `warning:` line for it, and no record, lens grade or run record reads it, so a finding's grade is the same with or without it. A re-run that later downgrades a reproduced finding does not change its entry.

One scratch change is a warning, not a refusal: an added test file that no `reproduced` finding names as its `proof.test`. `finish` prints `warning: scratch.changes: <path> (added) ...` on standard error, records a degraded input for it (`tool` `review-command`, `reason` `uncited-test-file`, `input` the path) so it shows in `review-run.json` and the lens grade's `degraded_inputs`, never lays the file over a re-run tree, and grades the answer's findings as usual. A symlink, Claude configuration, a deletion, a modification and an added file that is not a test are still refused.

A reproduced finding stays reproduced only when this command's own re-run exits non-zero, the cited test is one of the tests that failed in the re-run's output, and the recorded failure is that test's failure.

**What the re-run runs and compares.** The re-run uses the `command`, `test` and `output` exactly as the reviewer wrote them in the answer file, held in memory. It does not use the stored record's copy, which is scrubbed of secret-shaped text (`[scrubbed:<kind>]` markers), so a failure message that prints a secret, or a plain phrase the scrubber mistakes for one, still compares equal, and a command or test path is never altered before it runs. The unscrubbed values are never written: the findings, `review-run.json`, the run record and the state documents keep the scrubbed copy, and so does every degraded input below. `--final` replays the same unscrubbed proof.

**How the match works.** `plugins/saga/scripts/reproduction_match.py` reads the failed tests from cargo test and nextest, pytest, unittest, Vitest, Jest, go test, dart test and swift test (XCTest and Swift Testing) output, matching the test by name and, where the runner prints one, file, so a pass or another test's failure never counts. Only the first 400,000 characters of each side are read, and colour codes are removed from both. A recording or a re-run too large to read within the parser's limits does not match.

- When the recorded output holds a runner failure block for the cited test, the message lines of the recorded block and of the re-run's block must each appear in the other. A message line is a failure line without source frames, locations, generic headers, totals or the test's own name; for pytest only the `E` lines count. A recording that has failure blocks, none of them the cited test's, does not match.
- When the recorded output is a summary with no runner block, every message line of the re-run's failure for the cited test must appear in the recorded text, and the lines must total at least 12 characters. Recording one line of a multi-line failure does not match.
- When the re-run's output holds no failure in any known runner's format, or the finding names no test, the earlier rule applies: the last specific line of the recorded output (not a header, a total or the test id) must appear in the re-run's output, and a test id written `file::name` must appear word for word.

Before lines are compared, `normalise` strips surrounding blanks and collapses runs of white space, and drops only these things that change between runs: the number in a Rust `thread '<name>' (<id>)` marker, the digits (five or more) of a file name ending in `-test-<digits>` (read as `<pid>`), the address after `object at 0x`, a Dart test clock prefix such as `00:01 +0 -1: `, and the directory in front of a `file:line:` at the very start of a line. Everything else is compared as written: process ids in any other position, time stamps, temporary paths in the middle of a line, and other numbers. A test whose failure message prints one of those fails the match on every run, so a reproduction's assertion message should not print them.

The re-run tree is the packet's head commit with the reviewer's test files laid over it. The re-run is this process, confined. It is not a reviewer session. The re-run gives the command its own `HOME`, `TMPDIR` and file-creation mask (umask) `022`, the common default, whatever mask this process runs with. The files it lays out get the modes a `022` checkout has: the exported head sets them explicitly, a copied test file is set to `0644` (`0755` when executable), and the `--final` worktree is checked out under `022`. A test whose defect depends on the mask should still set it itself. `--final` runs that check again for blocking findings that still have a command, on a detached worktree of the packet's head, with the same test files.

**When a finding is downgraded to traced.** The finding's proof is replaced by one generic step, and `finish` records a degraded input (`tool` `review-command`) so the reason shows in `review-run.json`, the lens grade's `degraded_inputs` and the state document:

| `reason` | Meaning | `input` |
|---|---|---|
| `no-sandbox` | the machine record does not say the reproduction sandbox is available | `sandbox` |
| `bad-scratch` | the reviewer's scratch folder could not be used | `scratch` |
| `head-export` | the head could not be exported for the re-run | `head` |
| `final-worktree` | `--final` could not make its detached worktree | `worktree` |
| `missing-test-file` | the cited test file was not in the reviewer's scratch folder | the test file |
| `re-run-not-argv` | the command is not a direct argument list | the command, scrubbed |
| `re-run-timeout` | the re-run passed its 120 second limit | `re-run` |
| `re-run-could-not-start` | the command never ran: a temporary folder could not be made, the sandbox helper could not start it, it exited 126 or 127, or its output holds a line from `sandbox-exec` or `bwrap` saying so. A sandbox deny line alone is a mismatch, since a test that ran can be denied an operation | the program, scrubbed (`tmp` when the temporary folder failed) |
| `re-run-mismatch` | the command ran and exited, but not with the recorded failure of the cited test | the test, scrubbed |

`lens` and `language` come from the finding, except that `no-sandbox`, `bad-scratch`, `head-export`, `final-worktree`, `re-run-timeout` and `re-run-could-not-start` record language `none`, and `final-worktree` and the final round's `bad-scratch` record lens `correctness`.

A `re-run-mismatch`, and a `re-run-could-not-start` read from the re-run's exit code or output, also carry `exit_code`, the re-run's exit code, and `output_tail`, the last 500 characters of its combined output after secret-shaped text is replaced by `[scrubbed:<kind>]` markers and colour codes are removed, so an operator can see what the re-run printed. One raised before the re-run began (the temporary folder, or an operating-system error starting the sandbox helper) carries neither. A degraded input never changes a lens's grade letter, which depends only on its counts of blocking and fix-later findings; only a finding's own `degraded` flag lowers that finding from blocking to fix-later. A re-run that matched leaves no degraded input.

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
