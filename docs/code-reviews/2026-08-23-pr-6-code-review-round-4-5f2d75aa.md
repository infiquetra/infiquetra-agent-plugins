# Saga Code Review — PR #6 fourth-round candidate

This gate reviews the `infiquetra-agent-plugins` PR #6 merge-base diff because the portable assessment harness must produce unambiguous, reproducible compatibility evidence before the branch can merge.

## Outcome

- Typed outcome: `repairs_requested`
- Next action: `dispatch_repairs`
- Reviewed revision: `5f2d75aa71c424bc5d8890bcef40c824d1b2834f`
- Fetched base: `origin/main`
- Merge base: `e4dba5ad40228ec4a416cf4365613f8046b102bb`
- Target: the complete worktree diff from the merge base through the reviewed revision
- Findings: four Priority 2 (P2) findings; no Priority 0 (P0) or Priority 1 (P1) finding
- Review backend: `inline`
- Selected lenses: `previous-comments`, `correctness`, `testing`, `reliability`, `adversarial`, `security`, and `api-contract`
- Typed JavaScript Object Notation (JSON) result: `.review/review-result.json`

> The repaired candidate is not accepted by the canonical lens scoring policy. The three round-three repairs hold on their intended paths, but the timeout record still has an ambiguous status convention, blocked command aliases are not validated, a supplied run directory can bypass the freshness boundary, and the cycle-13 proof overstates what its escaped-session test observes.

Finding priority is metadata, not an acceptance gate. The roster accepts only an overall score of at least 9.0 with no applicable dimension below 7.0, so these P2 findings still produce `repairs_requested`.

## P2 findings

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---:|---|
| F-004 | `docs/evidence/2026-08-23-cycle13-mutation-proof-portable-copies.txt:31` | The proof says the test confirms an escaped descendant survives, while the test explicitly observes no such outcome. | testing, previous-comments, adversarial | 100 | `manual -> human` |
| F-005 | `scripts/assess_clients.py:1150` | `exit_status: -1` means both deadline termination and a real hangup-signal return, including two indistinguishable entries in one blocked stage. | api-contract, correctness, reliability, testing, adversarial | 100 | `gated_auto -> review-fixer` |
| F-006 | `scripts/assess_clients.py:1414` | A direct caller can supply a prior run directory and mix a new package copy and transcript into it. | correctness, reliability, testing, adversarial | 100 | `gated_auto -> review-fixer` |
| F-007 | `scripts/check_compatibility_matrix.py:749` | The validator skips alias agreement for blocked stages and accepts contradictory `command` and `commands[0].command` values. | api-contract, correctness, testing, adversarial | 100 | `gated_auto -> review-fixer` |

### Finding F-004 — Mutation proof overstates escaped-session coverage

The cycle-13 proof says at `docs/evidence/2026-08-23-cycle13-mutation-proof-portable-copies.txt:31` that the escaped-session test “confirms the descendant really does survive.” The test says the opposite about its evidence boundary: `tests/test_assess_clients.py:606-608` states that it deliberately asserts nothing about survival because that outcome is environment-dependent. Lines 610-627 create the marker but never read it; the assertions verify only that the cleanup sentence no longer claims containment.

This does not invalidate the narrowed runtime claim, which is accurate. It does make the committed proof overstate what its zero-survivor result established. The repair should either narrow the proof text to the wording behavior the test actually checks, or make the test observe and clean up the escaped descendant deterministically, then regenerate the bound proof rather than edit a digest by hand.

### Finding F-005 — Timeout sentinel collides with real signal status

The timeout path writes `exit_status: -1` at `scripts/assess_clients.py:1147-1154` and calls it a value no real exit status can produce. A real subprocess probe disproved that convention: a process terminated by the hangup signal (SIGHUP) returned `-1` through the same Python subprocess interface. A two-command probe then produced one command terminated by SIGHUP and a later command killed at its deadline; both serialized as `exit_status: -1` in the same blocked stage.

The stage-level `result` does not disambiguate those two entries because both sit in one blocked stage. The schema at `schemas/compatibility-matrix.schema.json:222-224` admits every integer and carries no timed-out state, and the validator accepts `-1` with an arbitrary blocked reason. Version two therefore needs an explicit per-command termination state, or a nullable exit status with enforced semantics, updated across the producer, schema, validator, runbook, and behavior tests.

### Finding F-006 — Supplied run directories bypass freshness

The command-line path is correct now: `main` allocates one numbered directory, passes it to `assess`, and announces the transcript below that same value. The no-argument `assess` path also still allocates its own numbered directory.

The new supplied path is trusted without validation at `scripts/assess_clients.py:1414`. A direct probe passed a directory already holding `openai-codex/package`, restricted the new assessment to Claude Code, and completed with both old and new package copies inside the same run directory. An executed call would also write through the overwrite-capable transcript path at line 1609. The unconditional `copytree` prevents reuse only when the current client collides; it does not preserve the one-run-one-directory boundary for other stale package copies or an old transcript.

Validate a supplied run directory as an existing empty directory allocated for this call, reject a mismatch with `workspace`, and add a stale-copy and stale-transcript regression while keeping the fallback allocation unchanged.

### Finding F-007 — Blocked command aliases escape validation

The version-two schema says `command` remains the first `commands` entry. The validator enforces that relationship only after `scripts/check_compatibility_matrix.py:749-750` skips every non-executed stage, even though the repaired timeout path now places `commands` on blocked stages.

A direct validator probe used `result: blocked`, `command: first-command`, `commands[0].command: different-command`, and `exit_status: -1`; the complete validator returned no problems. Move the alias-agreement check outside the executed-only branch and add a blocked-row disagreement regression.

## Round-three repair verification

The PR has no GitHub review, review comment, or issue comment, so the operator-supplied round-three inventory is the authoritative previous-comments map.

| Prior finding | Result | Behavioral evidence |
|---|---|---|
| Escaped descendants survive a reported cleanup | Holds | The real-process test passed. The reason now states only that the stage process group is empty, explicitly says a descendant that started its own session is neither signalled nor observed, and says this is not evidence that none remains. The runbook gives the same caveat and tells the operator to check for stragglers. |
| Timed-out commands disappear from version-two records | Core repair holds; representation remains incomplete | A first and only command that timed out appeared as `commands[0]`, remained equal to the `command` alias, and was safety-graded. A later timed-out command appeared after the completed command. Finding F-005 covers the ambiguous status representation, and finding F-007 covers the validator's blocked-alias gap. |
| The command-line interface reports the wrong transcript path | Holds on both supported allocation paths | The end-to-end fake-client command-line test announced a file that exists. The full test suite exercised `assess` without a supplied directory, so its fallback allocation remains intact. Finding F-006 covers the new caller-supplied freshness boundary, not the announced-path repair. |

The first-command and only-command timeout probe produced one public command, `command == commands[0].command`, an empty private `returncodes` tuple, and one private transcript entry. The later-timeout probe produced both public commands while `returncodes` contained only processes that completed. No current consumer breaks on that length difference: stage classification uses the blocked result, and the public validator consumes `commands`. The defect is the meaning of `-1`, not the cardinality difference.

## Cycle-13 mutation-proof assessment

Cycle 13 reports 55 anchors, zero survivors, byte-identical restoration, and no final-suite failure outside the deliberately excluded binding test. The complete current suite passed the binding test against the published cycle-13 digests.

That result proves only that the 55 named mutations are observed. It does not cover the collision between a real negative signal return and the deadline sentinel, alias agreement on a blocked version-two row, freshness of a caller-supplied run directory, or behavior that no anchor names. It also does not observe whether the escaped descendant survived, despite the proof's line 31 saying it does; finding F-004 records that contradiction.

The cycle-11 and cycle-12 files are unchanged from their committed bytes. Cycle 13 names cycle 12 as superseded and retains the cycle-12 anchors against the repaired files.

## Scope and completion audit

Scope Check: REQUIREMENTS MISSING

Intent: move package-specific porting configuration into descriptors and provide a safe, reproducible ten-client assessment harness without changing the shipped UniFi package.

Delivered: descriptor-driven synchronization, matrix validation, the assessment program, documentation, and the regression corpus are present; the four P2 findings leave the version-two timeout contract, supplied run-directory invariant, blocked-row validator, and mutation-proof statement incomplete.

There is no active PR-specific plan under `docs/plans/`; the existing plan is the earlier UniFi and Fleet Core pilot. This audit therefore uses the PR body, the operator's fourth-round brief, commit messages, and the engineering journal as the settled intent. No unrelated scope expansion was found, and the queued Fleet Core descriptor remains deferred.

| Requirement | State | Evidence |
|---|---|---|
| Package identity, custody, and assessment settings move into `ports/<package>.json` | DONE | `ports/unifi.json`, `scripts/port_config.py`, and repository validation |
| Synchronization and matrix validation resolve the package from its descriptor | DONE | Required provenance reproduction and all nine committed records pass |
| The ten-client assessment is safe by default and runs only with `--execute` | DONE | Plan-only command prints ten clients and four stages; no live assessment ran |
| Deadline cleanup reports only what its process-group mechanism established | DONE | Behavioral test and runbook caveat agree |
| Version-two timeout commands are complete and unambiguous | PARTIAL | The command is present and graded, but findings F-005 and F-007 remain |
| One run owns one fresh directory and one announced transcript | PARTIAL | Command-line and fallback paths hold; finding F-006 remains for supplied directories |
| Mutation evidence states only what its anchors prove | PARTIAL | The binding and 55 anchors hold; finding F-004 remains |
| `plugins/unifi/` stays byte-for-byte unchanged | DONE | No merge-base diff; 23-file fingerprint matches the required digest |

COMPLETION: 5 DONE, 3 PARTIAL, 0 NOT-DONE, 0 CHANGED, 0 UNVERIFIABLE

## Lens scores

The roster accepts a lens only when `derived_overall >= 9.0` and every applicable dimension scores at least `7.0`. “Failing dimensions” lists only dimensions below the 7.0 floor; a lens can still be unaccepted because its overall score is below 9.0.

| Lens | derived_overall | accepted | Failing dimensions and scores |
|---|---:|---|---|
| previous-comments | 7.0 | false | None; overall is below 9.0 |
| correctness | 6.8 | false | `boundary-types-serialization-numeric-time=6.0`; `caller-enum-consumer-completeness=6.0` |
| testing | 7.0 | false | `negative-edge-state-concurrency-time=6.0`; `behavior-sensitive-assertions=6.0` |
| reliability | 7.5 | false | `timeouts-retries-circuit-breakers-idempotency=6.0` |
| adversarial | 7.285714285714286 | false | `load-bearing-assumptions=6.0`; `abuse-edge-cases=6.0`; `failure-amplification-silent-green=6.0` |
| security | 9.5 | true | None |
| api-contract | 6.75 | false | `interface-contract-compatibility=6.0`; `serialization-errors=6.0`; `specification-documentation-parity=6.0` |

The API-contract lens is applicable. The repair did not change `ports/` or `schemas/` relative to the prior revision, but the reviewed merge-base diff still introduces descriptor version two and compatibility-record version two. Findings F-005 and F-007 are current contract defects on that branch surface.

## Checks and evidence

- `git fetch origin main --quiet` completed before the merge-base diff was read.
- The worktree head exactly matches the frozen revision `5f2d75aa71c424bc5d8890bcef40c824d1b2834f`.
- Both CI jobs are green on the PR head: two passed and zero failed.
- `python3 scripts/check_repo.py` passed.
- `python3 -m unittest discover -s tests` passed all 609 tests in 40.471 seconds.
- Four focused repair tests passed: escaped-session wording, public timeout command, announced transcript path, and blocked-stage safety grading.
- `python3 scripts/check_compatibility_matrix.py` validated all nine committed version-one records.
- `python3 scripts/sync_vendor_source.py --package unifi --source /Users/jefcox/workspace/infiquetra/infiquetra-claude-plugins --commit 818fd6843e51a9126752061a834db9dead28f72b --check` reproduced the shipped provenance manifest.
- The `plugins/unifi/` tree is unchanged in the merge-base diff and fingerprints to 23 files with Secure Hash Algorithm 256 (SHA-256) value `22bfa56828fc7d0fb2246f190730082905bd71b82dee3e8d6e5afc4072498d37`.
- `ports/` and `schemas/` have no byte difference between the prior reviewed revision and this revision.
- The cycle-11 worktree blob and committed blob both have Git object identifier `93b4ea57666ec70d20725ecc6f1706e5c0e6dcb0`.
- The cycle-12 worktree blob and committed blob both have Git object identifier `990ed18b74a08c8514732ecf6252c733c156e5ac`.
- `git diff --check e4dba5ad40228ec4a416cf4365613f8046b102bb` passed.
- The plan-only assessment printed ten clients and four stages without `--execute`.
- The live ten-client assessment was not run. The one command-line `--execute` test used only a scratch directory and a fake `codex` executable, as authorized.

## Coverage and routing

No finding was suppressed and no finding exceeded the validator budget. Each finding is introduced by this branch and was rechecked against current code or a direct behavioral probe. No subagent, workflow, external reviewer, or second opinion was used.

Route findings F-005 through F-007 together as `FIX-002`, then mutation-prove and re-review the producer, schema, validator, and run-directory relationship. Route finding F-004 as the separate human-owned evidence decision `FIX-003`. No fixer was dispatched, no Saga state was modified, and no reviewed source, commit, branch, pull request, issue, release, or deployment was changed.
