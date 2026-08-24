# Saga code review: repaired PR #6 candidate

This review covers the portable-agent-plugin source repository at frozen commit `00badee059f5c3c6370ccfd98a432936e472d73a`, where the assessment harness must be safe and truthful before an operator runs it across ten installed clients.

## Outcome

`repairs_requested`

Seven of the ten requested repairs hold under behavior checks. Three repairs remain partial: process-group cleanup, transcript retention, and fresh per-client copies. The independent pass also found four additional defects. One is Priority 0 (P0) because a copied launcher wrapper can still create unbounded recursive descendants and exhaust the host.

The next typed action is `dispatch_repairs`. The result contains four consolidated fix requests. No reviewed source was changed, no client assessment was executed, and no commit was created.

## Revision and scope binding

- Repository target: PR #6 in `infiquetra/infiquetra-agent-plugins`.
- Reviewed revision: `00badee059f5c3c6370ccfd98a432936e472d73a` (`fix(tooling): repair all ten independent-review findings in one batch`).
- Fetched `origin/main`: `e4dba5ad40228ec4a416cf4365613f8046b102bb`.
- Merge base: `e4dba5ad40228ec4a416cf4365613f8046b102bb`.
- Reviewed diff: 28 files, 5,943 insertions, and 419 deletions.
- Scope check: **REQUIREMENTS MISSING**. The delivered change substantially implements the generic port-assessment tooling, but three stated repairs do not hold on their failure or reuse paths.
- Backend: inline. No subagent, workflow, second reviewer, or external opinion was used.

## Verification of the ten requested repairs

| Prior finding | Result | Behavior evidence |
|---|---|---|
| F-01, wrapper recursion | **DONE for the requested file-identity cases** | A lone wrapper is refused; a distinct real binary behind it is selected; a symlink to the wrapper is refused; the property holds for both Grok and Agy in the focused tests. The independent pass found the copied-wrapper case in F-11. |
| F-02, version 2 command records | **DONE** | A multi-command stage records every command beside its own exit status, and the legacy `command` equals the first command. All nine committed version 1 records remain valid. |
| F-03, whole-session timeout cleanup | **PARTIAL** | The covered case, where the launcher is still alive at timeout, kills its descendant. A real subprocess probe where the launcher exited first left the descendant alive; see F-12. |
| F-04, private bounded transcript | **PARTIAL** | Successful multi-command output is bounded and stays outside the public record. Timeout and mutation branches discard transcript data, and an operator-supplied workspace creates a non-private file; see F-15 and F-16. |
| F-05, status derivation | **DONE** | `works-directly` requires all four stages to execute successfully. `failed` is proposed only after successful placement and load followed by a failed invocation. |
| F-06, assessment entrypoints | **DONE** | Entrypoints are read from `assessment.entrypoints` independently of custody. A package with no custody entries can still declare runnable entrypoints. The independent pass found missing existence validation in F-14. |
| F-07, fresh fingerprinted client copy | **PARTIAL** | Distinct clients get distinct initial copies and mutation invalidates the current row. Reusing the same workspace reuses the previous copy and can classify mutated bytes under the shipped digest; see F-13. |
| F-08, manifest extension directory | **DONE** | A descriptor that names `source.manifest_path` without `source.client_extension_dir` is refused. |
| F-09, closed descriptor objects and safety declarations | **DONE** | Unknown keys are refused at every descriptor level. Each safety list is either present or named in `assessment.declared_none`, and invalid `declared_none` values are refused. |
| F-10, known package name in preview | **DONE** | The plan-only command substitutes `unifi` in every known package-name position. Only the Grok client-generated install identifier remains `<plugin-id>`. |

Repair rollup: 7 done, 3 partial, 0 not done, 0 contradictory, and 0 uncertain.

## Findings

### Priority 0 (P0)

#### F-11: Copied launcher wrappers are mistaken for real clients

- Location: `scripts/assess_clients.py:568`
- Review lens: adversarial, `failure-amplification-silent-green`
- Confidence: 50 percent
- Route: manual, human owner, verification required

The resolver accepts the first later executable that is not the same inode as the first path entry. A byte-identical copy of the Grok or Agy wrapper is therefore treated as the real client. When the launcher receives that copy as its real-binary override, it launches another wrapper, which repeats the operation and creates an unbounded descendant chain until the host exhausts resources.

The P0 designation is deliberate and exceptional: the reproduced condition is a distinct-file copy rather than the current machine's normal repeated path entry, but the consequence is the same unbounded host-exhaustion failure that made the original wrapper recursion a P0.

Behavior probe: two executable, byte-identical but inode-distinct wrapper copies produced `os.path.samefile == False`, and `resolve_real_binary` returned the second wrapper.

Suggested repair: do not infer a real Grok or Agy executable from another same-named path entry. Require an explicit underlying executable path or a client-specific identity check, refuse every candidate that cannot prove it is not a launcher, and add a copied-wrapper regression.

### Priority 1 (P1)

#### F-12: A timed-out descendant survives after its session leader exits

- Location: `scripts/assess_clients.py:683`
- Review lens: reliability, `graceful-degradation-cancellation-cleanup`
- Confidence: 100 percent
- Route: gated automatic repair, review-fixer owner, verification required

A launcher can start a descendant and exit while the descendant still holds the captured output pipes. `communicate` then reaches its deadline, but `os.getpgid(process.pid)` fails because the leader no longer exists. The harness reports that the process group already exited even though the client continues to run and write.

Behavior probe: a real session leader backgrounded a descendant that would write a marker and then exited. The timeout path reported that the group had exited, returned only after 3.27 seconds, and the descendant wrote the marker.

Suggested repair: because `start_new_session=True` makes the child process identifier the process-group identifier, signal that identifier directly without first resolving it through the departed leader. Verify the group is gone, and add a real-subprocess regression where the leader exits before its descendant.

#### F-13: A reused workspace silently reuses a mutated package copy

- Location: `scripts/assess_clients.py:1270`
- Review lens: correctness, `state-data-invariants-transactions-concurrency`
- Confidence: 100 percent
- Route: gated automatic repair, review-fixer owner, verification required

The fresh copy is created only if the client scratch directory does not exist. A second assessment using the same `--workspace` therefore assesses whatever the prior run left behind. It can classify modified bytes as working while the record still carries the shipped package fingerprint.

Behavior probe: the first run mutated its client copy and lost classification. The second run with the same workspace retained the mutation marker, classified `works-directly`, and kept the shipped tree digest.

Suggested repair: allocate a new per-run directory or refuse an existing client scratch directory. Add a regression that performs two assessments with the same workspace.

#### F-14: A nonexistent declared entrypoint is graded as a package failure

- Location: `scripts/port_config.py:535`
- Review lens: correctness, `intent-behavior-completeness`
- Confidence: 100 percent
- Route: gated automatic repair, review-fixer owner, verification required

The descriptor parser validates only that each assessment entrypoint is a relative path. A typo passes repository validation. Placement and load can then succeed, Python exits with status 2 for the missing file, and the harness reports `failed` even though the assessment configuration—not the portable package—is invalid.

Behavior probe: an inert copy of the UniFi descriptor with a nonexistent entrypoint parsed successfully. Simulated placement and load succeeded, the real Python invocation exited 2, and `propose_status` returned `failed`. The committed existence regression still loops over `custody.entrypoint_transforms`, so it does not protect the new independent field.

Suggested repair: validate that every `assessment.entrypoints` value is a shipped file beneath the package before execution, and change the descriptor regression to iterate `config.assessment.entrypoints`.

#### F-15: Failure paths discard the transcript needed to finish the record

- Location: `scripts/assess_clients.py:1062`
- Review lens: previous comments, `resolution-completeness`
- Confidence: 100 percent
- Route: gated automatic repair, review-fixer owner, verification required

When a later command times out, the returned outcome omits earlier transcript entries and the timed-out process's partial output. When package mutation invalidates a row, every replacement outcome also omits its transcript. These failure paths are where the operator most needs output to explain a blocked record.

Behavior probes: a second-command timeout retained one recorded command but zero transcript commands. A mutation-invalidated run persisted no transcript stages.

Suggested repair: carry completed transcript entries into timeout outcomes, include bounded `TimeoutExpired` output and standard error for the timed-out command, and preserve transcript values when invalidating classification. Add behavior regressions for both branches.

### Priority 2 (P2)

#### F-16: The raw transcript is not private in an operator-supplied workspace

- Location: `scripts/assess_clients.py:1437`
- Review lens: security, `confidentiality-logs-errors-egress`
- Confidence: 100 percent
- Route: gated automatic repair, review-fixer owner, verification required

`Path.write_text` uses the process umask. In an ordinary 0755 operator-supplied workspace, `transcript.json` was created with mode 0644. Other local users can therefore read raw, unredacted client output despite the explicit private-transcript contract.

Behavior probe: an assessment in a user-supplied 0755 workspace created `transcript.json` with mode 0644 and the other-read permission bit set.

Suggested repair: create the transcript atomically with mode 0600, preserve that mode on overwrite, and add a permission regression under a permissive umask and operator-supplied workspace.

### Priority 3 (P3)

#### F-17: Version 2 safety validation inspects the first command twice

- Location: `scripts/check_compatibility_matrix.py:798`
- Review lens: architecture and maintainability, `readability-naming-error-contracts`
- Confidence: 100 percent
- Route: safe automatic repair, review-fixer owner, verification required

Version 2 retains `command` as an alias of the first entry in `commands`. The validator appends both representations, so one unsafe first command creates duplicate diagnostics and inflates problem counts. This does not bypass a safety check, but it makes machine-readable and operator-facing failures misleading.

Behavior probe: a version 2 stage whose `command` equaled `commands[0].command` produced two recorded commands and two identical safety findings.

Suggested repair: validate `commands` only for version 2 and `command` for version 1, or deduplicate the required alias against the first entry. Add a diagnostic-count regression.

## Behavior-probe evidence

The probes used real subprocess behavior where process lifetime was the contract and inert fake client executables or temporary package copies elsewhere. No live ten-client assessment ran.

- Wrapper resolution: lone wrapper refusal, real binary selection, symlink refusal, both wrapper clients, and the new copied-wrapper case.
- Timeout containment: a leader that remains alive is contained; a leader that exits before its descendant is not.
- Transcript behavior: success output is bounded and retained; timeout and mutation replacement lose it; a permissive supplied workspace creates mode 0644.
- Package isolation: separate clients receive separate initial copies; a second run in the same workspace reuses a mutated copy.
- Entrypoints: custody-independent values are invoked; a nonexistent declared value passes configuration parsing and becomes a false package failure.
- Versioned records: multi-command status pairing is preserved and all committed version 1 records validate; a version 2 alias is counted twice by safety validation.
- Status proposal: all-stage success is required for `works-directly`, and successful placement plus load is required before `failed`.
- Descriptor contract: missing manifest extension directory, unknown keys, and incomplete safety declarations are refused.
- Plan preview: known package names are substituted and the client-generated identifier remains a placeholder.

## Regression gates

| Gate | Result |
|---|---|
| `git fetch origin main --quiet` before freezing the comparison | PASS |
| Frozen head equals the brief's commit | PASS — `00badee059f5c3c6370ccfd98a432936e472d73a` |
| `plugins/unifi/` differs from the merge base | PASS — no diff |
| Official UniFi package fingerprint | PASS — 23 files, Secure Hash Algorithm 256-bit (SHA-256) `22bfa56828fc7d0fb2246f190730082905bd71b82dee3e8d6e5afc4072498d37` |
| `python3 scripts/check_repo.py` | PASS — repository validation passed |
| `python3 -m unittest discover -s tests` | PASS — 572 tests in 24.612 seconds on Python 3.14.6 |
| `python3 scripts/check_compatibility_matrix.py` | PASS — all nine committed version 1 matrices validated |
| `python3 scripts/sync_vendor_source.py --package unifi --source /Users/jefcox/workspace/infiquetra/infiquetra-claude-plugins --commit 818fd6843e51a9126752061a834db9dead28f72b --check` | PASS — shipped provenance reproduced |
| `git diff --check $(git merge-base origin/main HEAD)` | PASS |
| `python3 scripts/assess_clients.py --package unifi` | PASS — plan only; no process executed |
| `python3 scripts/assess_clients.py --execute` | NOT RUN — explicitly prohibited by the brief |

## Lens scores

Saga accepts a selected lens only when its derived overall score is at least 9.0 and every applicable dimension is at least 7.0. Finding priority and confidence are metadata, not separate gates.

| Lens | Overall | Accepted | Failing dimensions below 7.0 |
|---|---:|---|---|
| Architecture and maintainability | 8.857 | No | None; overall is below 9.0 |
| Correctness | 7.000 | No | Intent and behavior completeness; state and data invariants |
| Security | 8.200 | No | Confidentiality, logs, errors, and egress |
| Testing | 6.000 | No | Requirements and regression coverage; negative and timing cases; behavior-sensitive assertions |
| Reliability | 5.000 | No | Timeouts; partial-failure recovery; cancellation and cleanup |
| API contract | 7.250 | No | Interface compatibility; specification and documentation parity |
| Adversarial | 5.286 | No | Load-bearing assumptions; abuse cases; failure amplification; operator failure; recovery |
| Privacy | 6.250 | No | Data-flow classification; protection and sharing; retention and deletion |
| Documentation clarity | 7.000 | No | Shipped-behavior parity; runbook safety and drift |
| Agent usability | 5.800 | No | Capability reachability; actionable errors; bounded and resumable behavior |
| Previous comments | 4.000 | No | Resolution completeness |

The typed JavaScript Object Notation (JSON) artifact retains every per-dimension value and every non-applicability cause.

## Fix routing

| Fix request | Findings | Route | Owner |
|---|---|---|---|
| `fix-90fd573f7106` | F-11 | Manual | Human |
| `fix-91bd19380fec` | F-12, F-13, F-15, F-16 | Gated automatic repair | Review fixer |
| `fix-8dea4e57a7f7` | F-14 | Gated automatic repair | Review fixer |
| `fix-025905c6c7d2` | F-17 | Safe automatic repair | Review fixer |

## Residual risk and constraints

- The live ten-client assessment remains unexecuted. This review proves harness behavior with focused subprocess and fixture probes, not live vendor compatibility.
- The P0 copied-wrapper condition is reproduced in a controlled path setup. The current machine's ordinary Grok path also contains an application binary after repeated launcher entries, while Agy exposes only repeated launcher entries; neither live client was executed.
- No finding was suppressed. No external advisory finding exists because the brief prohibited external review.
- The only worktree outputs are `.review/review-result.json` and this file, alongside the coordinator-supplied `.review/brief.md`.
