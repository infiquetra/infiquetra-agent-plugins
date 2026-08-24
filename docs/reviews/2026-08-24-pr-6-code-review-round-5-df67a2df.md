# Saga Code Review — PR #6 fifth review

This review covers the `infiquetra-agent-plugins` PR #6 merge-base diff because the package-porting harness must preserve trustworthy compatibility evidence across process, filesystem, and JavaScript Object Notation (JSON) boundaries.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `df67a2df2d43e3728030c0c9d7c5813a06139c6b` (`df67a2d`, `docs(evidence): publish the cycle-14 mutation proof over the round-five repairs`)
- Fetched base: `origin/main`
- Merge base: `e4dba5ad40228ec4a416cf4365613f8046b102bb`
- Target: the complete worktree diff from the merge base through the reviewed revision
- Review backend: `inline`
- Active findings: one Priority 3 (P3) advisory; no Priority 0 (P0), Priority 1 (P1), or Priority 2 (P2) finding
- Prior findings: all four P2 findings from revision `5f2d75a` are resolved

> **Verdict: revision `df67a2d` is safe to merge under the operator-fixed seven-lens contract.** Every selected lens has a derived overall score of at least 9.0, every applicable dimension is at least 7.0, and the four required repairs hold under behavior probes. The confirmed later-missing-executable defect remains a narrow P3 advisory rather than a blocker because every current multi-command stage reuses one executable; the failure needs that executable to disappear while the stage is already running.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent: move package identity and assessment policy into port descriptors, make the synchronization and matrix tools package-agnostic, and turn the ten-client assessment method into a bounded program without changing the shipped UniFi package.
- Delivered: `ports/unifi.json`, the descriptor loader, generic synchronization and matrix validation, the assessment harness, tests, runbook and journal updates, and mutation evidence.
- No active PR #6 plan exists under `docs/plans/`. The repository contains the earlier portability-pilot plan, but applying that completed plan as this PR's implementation plan would be false. The plan-completion checklist is therefore skipped under the Saga rule; the PR body, commit history, and engineering journal supply the current intent.
- The untracked `.review/brief.md` is excluded from the reviewed diff. The two review outputs are also outside the diff and are not reviewed source.

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0. Finding priority and confidence are routing metadata, not additional acceptance gates.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `previous-comments` | 10.00 | `true` | none |
| `correctness` | 9.40 | `true` | none |
| `testing` | 9.20 | `true` | none |
| `reliability` | 9.25 | `true` | none |
| `adversarial` | 9.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `api-contract` | 9.75 | `true` | none |

## Active finding

### Priority 3 (P3)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---:|---|
| F-008 | `scripts/assess_clients.py:1142` | A later executable missing from the shell executable search path (`PATH`) drops prior command evidence | `reliability` | 100 | `advisory -> downstream-resolver` |

The early return at `scripts/assess_clients.py:1142-1152` constructs a new blocked stage with only the first-command alias and reason. It does not carry `recorded_commands`, `transcript`, or completed statuses. A fake-executable probe ran the first argv, made the second argv unavailable, and returned `blocked` with `command: first-ok` but empty `commands` and transcript.

This is a confirmed defect and disclosed debt, but disclosure is the right non-blocking disposition for this bounded round. `stage_argvs` generates every current multi-command stage with the same executable for all argvs: the client binary for per-skill stages and the same Python interpreter for all entrypoints. The defect therefore needs that executable to disappear mid-stage; no stable current plan reaches it. Before any future stage uses different executables per argv, the early return should carry the accumulated commands, transcript, and statuses and gain a two-argv regression.

## Prior repair verification

### F-004 — cycle-13 evidence overstatement

Resolved. The original overstatement remains at `docs/evidence/2026-08-23-cycle13-mutation-proof-portable-copies.txt:31`, and exactly one dated 2026-08-24 correction sits beside it at lines 33-43. The correction says precisely that cycle 13 built the `setsid` escape and checked only the cleanup wording, wrote but did not read the marker, and relied on a separate uncommitted probe for observed survival. It also says the marker assertion belongs only to the later test.

Annotate rather than rewrite is the honest form. It preserves what the published cycle actually claimed while weakening that claim in place; it does not retroactively alter the digest block or pretend the new assertion ran in cycle 13. The current test at `tests/test_assess_clients.py:606-637` waits for the marker and passed in the focused run.

### F-005 — deadline representation

Resolved. `StageCommand` at `scripts/assess_clients.py:830-851` and `CommandTranscript` at lines 870-899 each reject both endings and neither ending. The timeout path at lines 1188-1206 writes `timed_out: true` with no `exit_status` to both the public command list and private transcript. A process terminated by the hang-up signal (SIGHUP) retains `exit_status: -1`; the real subprocess behavior test at `tests/test_assess_clients.py:1258-1278` passed.

The matrix validator at `scripts/check_compatibility_matrix.py:716-737` rejects both fields and neither field. The schema at `schemas/compatibility-matrix.schema.json:207-230` documents exactly-one-of but deliberately has no structural `oneOf`. That split is acceptable here: `check_compatibility_matrix.py` is already the semantic enforcement point for record version, canonical client coverage, command safety, and public-evidence rules, and its schema interpreter explicitly enumerates the supported vocabulary rather than silently accepting an unsupported keyword. A generic schema-only consumer is not sufficient validation and must not be presented as such.

### F-006 — supplied run directory

Resolved for the documented caller contract. `require_fresh_run_directory` at `scripts/assess_clients.py:1428-1467` requires an existing readable empty directory, normalizes it with `resolve`, rejects the workspace itself, and checks containment against the resolved workspace when one is supplied.

Behavior probes established:

- A symlink resolving outside the workspace is refused; a symlink resolving to an empty directory inside is normalized to that target and accepted.
- A relative path inside a relative workspace is normalized and accepted; a resolved outside path is refused.
- `workspace=None` accepts an arbitrary existing empty directory. This matches the explicit source and journal contract, which requires containment only when a workspace is supplied; the command line always supplies the workspace it allocated.
- An occupied directory, a missing directory, and the workspace itself are refused by focused tests.
- A directory can become non-empty after validation and before the first package copy. A deterministic probe inserted a file after the check and the plan-only assessment then added its package copy beside that file. This is a remaining concurrent-writer risk, not a blocker: the command-line path atomically allocates a unique directory, and a direct caller that supplies a directory owns the promise that no other process mutates it after validation. The function does not provide a filesystem lease against another writer.

### F-007 — blocked-row alias

Resolved. `check_record_version` at `scripts/check_compatibility_matrix.py:782-804` checks `command == commands[0].command` whenever both homes exist and the command list is non-empty. It no longer skips the check for blocked or not-applicable stages. The focused blocked and not-applicable regression at `tests/test_check_compatibility_matrix.py:465-490` passed, and a separate disagreeing blocked-row probe returned the expected error.

## Exit-status consumer sweep

Every consumer of the changed stage-ending representation handles the timed-out shape:

| Consumer | Current behavior | Result |
|---|---|---|
| `StageCommand.record` | Emits either integer `exit_status` or `timed_out: true` | correct |
| `CommandTranscript.record` | Mirrors the public ending shape in the private transcript | correct |
| `StageOutcome.returncode` | Applies the first-non-zero rule only to actual completed-process statuses; a timed-out stage is `blocked` and has no synthetic status | correct |
| `propose_status` | Requires `result == executed` before treating `returncode` as success or failure, so a timed-out stage cannot become direct success or package failure | correct |
| `_command_ending_problems` and `check_record_version` | Reject both endings and neither ending; accept `-1` as SIGHUP | correct |
| `_recorded_commands` safety grading | Reads command strings, not endings, and therefore grades timed-out commands without interpreting a missing status | correct |
| Private transcript rendering | Emits `timed_out: true` and omits `exit_status` | correct |
| Portable-port runbook | Tells operators that a deadline has `timed_out: true`, no `exit_status`, and that `-1` is SIGHUP | correct |

The repository-wide search also found ordinary `CompletedProcess.returncode` readers in the synchronization and entrypoint tests. They do not consume `StageCommand`, `CommandTranscript`, or compatibility records and are unaffected by this contract change.

No fifth producer-and-consumer divergence was found in the round-five repair diff. The public command, private transcript, constructor guards, validator, schema description, runbook, decision record, and tests all learned the new ending representation. F-008 is the already disclosed earlier defect, not a divergence introduced by the repair. The post-validation directory race is a concurrent filesystem mutation, not a second stored home for one value.

## Cycle-14 evidence boundary

The cycle-14 proof reports 59 mutation anchors, zero survivors, byte-identical restoration, and no final-suite failure outside the then-expected proof-binding failures. Its header correctly says that zero survivors means every listed mutation was killed, not that the code is correct.

It still does not cover:

- behavior nobody chose as an anchor, including F-008 and the directory becoming occupied after its freshness check;
- a mutation of the `StageCommand` or `CommandTranscript` exactly-one constructor guard, or a mutation changing the timeout producer back to the `-1` sentinel, even though focused and full unit tests exercise those behaviors;
- generic JSON Schema validation without the repository's semantic validator;
- cross-field combinations and concurrent interference beyond the listed one-line mutations;
- live behavior of the ten real coding-agent clients; the review obeyed the prohibition on `--execute` and used only fake executables plus plan-only output;
- correctness outside the five files whose Secure Hash Algorithm 256 (SHA-256) digests the proof binds.

## Regression evidence

- Both CI jobs are green on `df67a2d`: `Repository validation` and `Ported plugin tests`.
- `python3 scripts/check_repo.py` passed.
- `python3 -m unittest discover -s tests` passed all 621 tests in 41.978 seconds.
- Twelve focused behavior tests for the four repairs passed in 4.976 seconds.
- `python3 scripts/check_compatibility_matrix.py` validated all nine committed version-1 records.
- `python3 scripts/sync_vendor_source.py --package unifi --source <local infiquetra-claude-plugins checkout> --commit 818fd6843e51a9126752061a834db9dead28f72b --check` reproduced the shipped provenance manifest.
- `plugins/unifi/` has no merge-base diff and fingerprints to 23 files with SHA-256 value `22bfa56828fc7d0fb2246f190730082905bd71b82dee3e8d6e5afc4072498d37`.
- Cycle 11 retains Git object `93b4ea57666ec70d20725ecc6f1706e5c0e6dcb0`; cycle 12 retains `990ed18b74a08c8514732ecf6252c733c156e5ac`. Each matches revision `5f2d75a` exactly.
- Cycle 13 has exactly eleven added lines, all in its one dated correction note. Cycle 14 explicitly supersedes it.
- `git diff --check e4dba5ad40228ec4a416cf4365613f8046b102bb` passed.
- `python3 scripts/assess_clients.py --package unifi` printed all ten clients and four stages per client without starting a process.
- The live ten-client assessment was not run. All execution probes used scratch directories and fake executables.

## Routing and state

No finding was suppressed and no finding exceeded a validator budget. The four prior P2 findings are retained as resolved typed findings; F-008 is an active report-only advisory with no repair dispatch.

No work-thread Saga was found, so no Saga state was created or changed. No subagent, workflow, external reviewer, second opinion, reviewed source, commit, branch, pull request, issue, release, or deployment was changed.
