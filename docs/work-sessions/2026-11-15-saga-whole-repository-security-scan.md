# Saga whole-repository security scan implementation

Issue: [321](https://github.com/infiquetra/infiquetra-agent-plugins/issues/321). Branch: `feat/saga-whole-repository-security-scan`. Plan: [whole-repository security scan](../plans/2026-11-15-saga-whole-repository-security-scan-plan.md).

## Units and checkpoint

U1's independent test-only commit `ab9fd4e61df072ad5f8345e9f064c0d406424e14` was fast-forwarded onto the feature branch before any production edit. Its observed baseline was 24 failures and one passing ordinary-review control; neither that file nor `test_review_tools.py` was edited by implementation.

U2's first usable checkpoint is `116c81886fbf5612fbda7f3b777b7c673cd0ddf1`, committed separately as `feat(saga): add whole-repository security scan command`. From that revision, the operator can run:

```bash
python3 plugins/saga/scripts/security_scan.py --repo ../scratch-security-scan --output ../security-scan-results/run-001
```

The command prints findings itself. It reads committed Git objects, constructs an independent snapshot with matching tree ID and preserved gitlinks, reuses catalogue security adapters, and saves private external records. The shared runner's keyword-only scan policy preserves ordinary review defaults; pip-audit's resolver-free arguments remain in its existing Python adapter.

U3 adds the portable skill, entrypoint/skill descriptor registration, README, tool reference and changelog guidance, and journal evidence. No version pin, dependency, installed copy, vendor runtime or release manifest changed. `change_kinds`: feature, tests, documentation, packaging-metadata.

## Execution and checks

Backend is `inline`; this dispatch uses the existing worker session, with no child agent launch or tier override. The plan-review check exited `0`; the Active/Implementing submission returned `status: written`, `field: Stage+Status` before implementation.

At U2, the runtime selector passed all 24 selected independent tests and the three additional runtime checks passed. The unchanged review-runner/Python-adapter test run passed 244 tests with two skips; command help, repository validation and whitespace checks passed. These are hermetic fake-tool checks and do not claim real advisory detections.

A supplemental partial-clone check subsequently exposed a read-only boundary defect: Git fetched missing trees/blobs into the target and the scan returned clean. The regression failed on changed target pack files before the fix. Scan-owned Git commands now disable lazy fetching and deny transports; all four supplemental runtime tests pass, including incomplete exit `2`, no adapter invocation, and an unchanged partial clone. The first usable checkpoint above remains the earlier command milestone; final handoff validation includes this correction.

The skill-directory inventory test now explicitly includes the new portable `security-scan` skill while retaining the exact existing vendor-command set. All 38 command-surface checks pass; neither frozen acceptance/regression file changed.

Validation uses separate pinned SDLC inputs: the template input at `ffa9285bbe1d5a7c521aeb831f68c2a0f2712303`, and a private Git copy at `f8d0994` for the role snapshot's revision-aware parity check. The SDLC feature working tree is not the canonical input. Whole suites run sequentially because existing drift/bundle tests mutate and restore shared files. A serial root run passed 1,321 tests with 28 skips, and nine earlier plugin failures cleared after restoring fixtures and correcting the role input.

The existing live Dart mutation test exposed a stale global `mutate4dart 0.12.2` kernel: it reported an invalid SDK hash, and its fallback failed under a fresh HOME. A private kernel was compiled from the same cached package and existing package configuration with the current Dart SDK, and a temporary wrapper inside the ignored worktree cache supplies it during validation. The global wrapper and snapshots retained their content hashes. The fresh-HOME version probe and live survivor test then passed; no package, pin or global activation was changed. The Jev sweep API key is excluded from validation processes because repository source is outside this session's permitted judgment state; any resulting unavailable-sweep result remains explicit.

Unit build-loop iteration details will be recorded here before the final combined-branch pass. The shared Saga record remains the authority for each check's status, revision and iteration number.

## Limits and next step

The declared functional environment is local/private, with no deploy or teardown command. The plan's real Python dependency/workflow planted-flaw scenario remains with the independent Functional Tester; unavailable required detecting rows are blocked, while unrelated gaps can honestly yield scan exit `2` even when both planted detections pass.

The implementation handoff will bind the final pushed revision to a passing combined-branch run via `build_loop.py --handoff`. Stop after PR creation and that handoff; the Lead routes the single code-review pass, and no merge or delivery occurs in this worker session.
