# Saga Code Review — PR #6 repaired candidate

This gate reviews the `infiquetra-agent-plugins` PR #6 merge-base diff because the new portable assessment harness must produce trustworthy compatibility evidence before it can be merged.

## Outcome

- Typed outcome: `repairs_requested`
- Next action: `dispatch_repairs`
- Reviewed revision: `f8a6ad81d64f5d14c1825cd6b0e1078e266be776`
- Fetched base: `origin/main`
- Merge base: `e4dba5ad40228ec4a416cf4365613f8046b102bb`
- Target: the complete worktree diff from the merge base through the reviewed revision
- Blocking findings: three Priority 1 (P1) findings
- Review backend: `inline`
- Selected lenses: `previous-comments`, `correctness`, `testing`, `reliability`, `adversarial`, `security`, and `api-contract`
- Typed JavaScript Object Notation (JSON) result: `.review/review-result.json`

> The repaired candidate is not safe to merge. The seven named repairs improve the branch substantially, but three integration failures remain in the assessment harness: timeout containment can report a false cleanup, a timed-out later command disappears from the public record, and the command-line interface prints a transcript path that does not exist.

## P1 findings

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---:|---|
| F-001 | `scripts/assess_clients.py:753` | A descendant that leaves the original process group survives while cleanup reports that no client descendant survived. | reliability, correctness, adversarial, testing | 100 | `manual -> human` |
| F-002 | `scripts/assess_clients.py:1145` | A timed-out later command is kept privately but omitted from the version-2 public command list and its safety recheck. | api-contract, correctness, reliability, testing | 100 | `gated_auto -> review-fixer` |
| F-003 | `scripts/assess_clients.py:1733` | The command-line interface prints `<workspace>/transcript.json`, but the file is written at `<workspace>/run-NNN/transcript.json`. | correctness, previous-comments, reliability, testing | 100 | `gated_auto -> review-fixer` |

### F-001 — Escaped descendants survive a reported cleanup

`terminate_process_group` signals and later probes only the original child process group at `scripts/assess_clients.py:725-753`. A real subprocess probe started a descendant with its own session, allowed the original stage to time out, and observed both of these facts:

- cleanup returned `The whole process group was terminated, so no client descendant survived it.`;
- the escaped descendant subsequently created its marker file.

The direct child wait at `scripts/assess_clients.py:745` is bounded by two seconds and did not hang or mask the original timeout in the same-group probes. Reaping before probing also removes the false zombie warning for an empty original group. The remaining defect is the stronger descendant claim: an empty original group does not prove that a descendant did not create another group or session.

The repair needs a supported-platform containment decision. Either enforce a mechanism that can observe or prevent descendants leaving the original group, or narrow the guarantee, refuse daemonizing clients, and test that limitation with a real escaped-session subprocess.

### F-002 — Timed-out commands disappear from version-two records

On timeout, `run_stage` appends the current command to the private transcript at `scripts/assess_clients.py:1133-1140`, but constructs the public `commands` list only from commands that completed earlier at `scripts/assess_clients.py:1141-1146`. The matrix validator then treats that list as complete and grades it alone at `scripts/check_compatibility_matrix.py:798-809`.

A two-command probe completed the first command and timed out the second. The public record contained only the first command, while the transcript contained both. This contradicts the version-2 contract that every command a stage ran is recorded, makes the stage unreproducible, and prevents the after-the-fact safety rule from inspecting the timed-out command.

The contract should represent a timeout without inventing an exit status, append that command before returning, and update the schema, validator, and behavioral tests together.

### F-003 — The command-line interface reports the wrong transcript path

`assess` allocates `<workspace>/run-NNN` at `scripts/assess_clients.py:1389-1391` and writes the transcript below that directory at `scripts/assess_clients.py:1583-1586`. The command-line interface instead prints `transcript_path(workspace)` at `scripts/assess_clients.py:1733`, omitting the numbered run directory.

A safe fake-client probe showed that the reported path did not exist while `run-001/transcript.json` did. This affects every executed assessment, including a first run with the default temporary workspace, and hides the raw output the operator is told to use to complete versions, reasons, and evidence.

`assess` should return the allocated run directory or exact transcript path, and the command-line test should assert that the printed path exists for both first and reused workspaces.

## Previous repair verification

The operator supplied the prior findings and their required behaviors. There were no GitHub review comments or review threads returned by the PR API, so this lens used that operator-supplied repair inventory as the authoritative previous-comments map.

| Prior finding | Repair-specific result | Behavioral evidence |
|---|---|---|
| Copied launcher wrappers are mistaken for real clients | Holds | Explicit and exported real-binary paths work; absent values block without process launch; copied-path inference, launcher identity, symlink identity, and non-executable cases all pass targeted tests. |
| A timed-out descendant survives after its session leader exits | Partial | Signalling by the child process identifier fixes descendants that remain in the group after the leader exits. F-001 proves a descendant that starts another session survives while the reason reports none. |
| A reused workspace silently reuses a mutated package copy | Holds | Three targeted tests prove fresh numbered run directories, fresh package copies, and unconditional copy refusal on collision. |
| A nonexistent declared entrypoint is graded as a package failure | Holds | Both the repository gate and harness reject the missing entrypoint; shipped entrypoints exist. |
| Failure paths discard the transcript needed to finish the record | Partial | Timeout and mutated-copy paths retain raw output, but F-003 proves the normal command-line handoff points the operator at a nonexistent transcript path. |
| The raw transcript is not private in an operator-supplied workspace | Holds | Creation-time mode remains `0600` with the later `chmod` neutralized, and overwrite tightens an existing loose file. |
| Version-2 safety validation inspects the first command twice | Holds | Version 2 grades `commands` once, version 1 still grades `command`, and an unsafe second command remains visible. F-002 is a separate omission on timeout. |

Completion rollup for the seven prior repairs: five hold, two are partial, and none is wholly absent.

## Cycle-12 mutation-proof assessment

Excluding `MutationProofBindingTest` from mutation grading is sound. Every mutation changes a graded file, so the byte-binding test necessarily fails for bookkeeping reasons unrelated to the mutated guard. The cycle-12 rule that counts only failures added relative to the baseline prevents that test from killing every mutation by construction.

The sixteen added tests generally constrain the guards they name:

- the creation-mode test neutralizes the later `chmod`, so it observes the unique protection supplied by `os.open(..., 0o600)`;
- the missing-safety-field test distinguishes the missing-field diagnostic from the downstream empty-field refusal;
- the mutated-copy test asserts the all-blocked rewrite and its reasons, not merely the redundant final status conditional;
- version-gate, alias agreement, repository-gate wiring, unconditional-copy, known-package plan substitution, and per-command status branches have behavior-sensitive assertions.

The accounting for the three redundant guards is honest. It names the uniquely contributed behavior for two guards and retires the conditional whose removal cannot change the final status. The proof does not establish the three failures in this review because none of its mutation anchors exercises an escaped process session, the public representation of a timed-out later command, or the command-line transcript-path handoff.

The committed cycle-12 digests now pass `MutationProofBindingTest`. The evidence file records one excluded binding failure during proof generation because the proof had not yet published its own final digests; the current complete suite has no such failure.

## Scope and completion audit

Scope Check: REQUIREMENTS MISSING

Intent: move package-specific porting configuration into descriptors and provide a safe, reproducible ten-client assessment harness without changing the shipped UniFi package.

Delivered: the descriptor, synchronization, matrix validation, assessment program, documentation, and regression corpus are present, but the three P1 findings leave timeout containment, public timeout evidence, and transcript handoff incomplete.

There is no active PR-specific plan under `docs/plans/`; the only plan there is the earlier UniFi and Fleet Core pilot plan. This audit therefore uses the PR body, the operator repair brief, and the branch engineering-journal entries as the settled intent. No unrelated scope expansion was found, and the queued Fleet Core descriptor remains explicitly deferred.

## Lens scores

The roster accepts a lens only when `derived_overall >= 9.0` and every applicable dimension scores at least `7.0`. “Failing dimensions” below lists only dimensions below the `7.0` floor; the exact dimension maps and non-applicable causes are in `.review/review-result.json`.

| Lens | derived_overall | accepted | Failing dimensions and scores |
|---|---:|---|---|
| previous-comments | 6.0 | false | `resolution-completeness=6.0` |
| correctness | 6.6 | false | `intent-behavior-completeness=6.0`; `side-effects-errors-resource-lifecycle=6.0`; `caller-enum-consumer-completeness=6.0` |
| testing | 7.0 | false | `requirements-regression-coverage=6.0`; `negative-edge-state-concurrency-time=6.0`; `behavior-sensitive-assertions=6.0` |
| reliability | 6.5 | false | `timeouts-retries-circuit-breakers-idempotency=6.0`; `graceful-degradation-cancellation-cleanup=6.0`; `health-signals-observability-runbooks=6.0` |
| adversarial | 7.142857142857143 | false | `load-bearing-assumptions=6.0`; `failure-amplification-silent-green=6.0`; `environment-operator-failure=6.0`; `recovery=6.0` |
| security | 9.75 | true | None |
| api-contract | 6.75 | false | `interface-contract-compatibility=6.0`; `serialization-errors=6.0`; `specification-documentation-parity=6.0` |

The API-contract lens is applicable. The new entrypoint-existence refusal is consistent across the repository gate and harness, but the version-2 command representation does not carry the timed-out later command that actually ran.

## Checks and evidence

- `git fetch origin main --quiet` completed before the merge-base diff was read.
- The worktree head exactly matches the frozen revision `f8a6ad81d64f5d14c1825cd6b0e1078e266be776`.
- `python3 scripts/check_repo.py` passed.
- `python3 -m unittest discover -s tests -v` passed all 605 tests in 36.448 seconds on the local Python 3.14.6 interpreter.
- The current revision has two green continuous integration (CI) jobs: Repository validation and Ported plugin tests. The latter is the repository's Python 3.12 floor job.
- The focused repair corpus passed 48 tests, including the real subprocess process-group tests.
- `python3 scripts/check_compatibility_matrix.py` validated all nine committed version-1 records.
- `python3 scripts/sync_vendor_source.py --package unifi --source /Users/jefcox/workspace/infiquetra/infiquetra-claude-plugins --commit 818fd6843e51a9126752061a834db9dead28f72b --check` reproduced the shipped provenance manifest.
- The `plugins/unifi/` tree is unchanged in the merge-base diff and fingerprints to 23 files with Secure Hash Algorithm 256 (SHA-256) value `22bfa56828fc7d0fb2246f190730082905bd71b82dee3e8d6e5afc4072498d37`.
- The cycle-11 evidence file has the same Git blob object identifier, `93b4ea57666ec70d20725ecc6f1706e5c0e6dcb0`, at revision `00badee059f5c3c6370ccfd98a432936e472d73a` and at the reviewed revision.
- `git diff --check e4dba5ad40228ec4a416cf4365613f8046b102bb` passed.
- The plan-only assessment printed ten clients and four stages without `--execute`.
- The live ten-client assessment was not run, as required by the operator.

## Coverage and routing

No finding was suppressed, no finding was over the validator budget, and all three surviving findings were validated inline with current-code probes. No subagent, external reviewer, workflow, or second opinion was used.

The three findings touch the same harness and should be repaired as one batch under `FIX-001`, followed by mutation-sensitive regressions and another review of the repaired revision. No work-thread Saga state was found, so no Saga write was made. No reviewed source, commit, branch, pull request, issue, release, or deployment was changed.
