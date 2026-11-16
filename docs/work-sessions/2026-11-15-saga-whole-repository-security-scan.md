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

Jeff's operator ruling confirms gitleaks-only secret redaction under issue 321 Notes/conventions and KTD7/T21. The exploratory non-gitleaks redaction test was discarded; other tool reports retain their existing behavior. The command and skill remain together in `plugins/saga/`.

The following historical iterations are rendered from the shared run record. Their `review` entries describe the scripted build-loop tool gate; independent code review remains pending. The initial broad-suite failures exposed overlapping mutable fixtures, the incorrect revision identity of an archive-only role input, and the stale Dart kernel described above. U3 iteration 2's remaining failed node was the existing orchestrate scheduling-skew deadline test; an isolated unchanged rerun passed in 1.21 seconds. These failed iterations remain recorded.

### U2 iteration 1

```text
Iteration 1 at 059e5f9538e0726d91127f3149fb7cf649bda144: not green yet

  [pass] python3 scripts/check_repo.py
      Repository validation passed.
  [fail] python3 -m unittest discover -s tests -v
      FAILED (failures=4, skipped=28)
  [fail] python3 -m pytest plugins/*/tests -q --import-mode=importlib
      10 failed, 8935 passed, 31 skipped, 3 xfailed, 15 warnings, 335 subtests passed in 1453.64s (0:24:13)
  [pass] git diff --check
  [pass] functional: whole-tree-runtime
  [pass] functional: user-command-help
  [pass] functional: unchanged-review-runner
  [no-preview-declared] branch preview
  [deferred-to-combined-branch] scenario smoke
  [pass] declarations
  [pass] review
```

### U3 iteration 1

```text
Iteration 1 at 059e5f9538e0726d91127f3149fb7cf649bda144: not green yet

  [pass] python3 scripts/check_repo.py
      Repository validation passed.
  [fail] python3 -m unittest discover -s tests -v
      FAILED (failures=3, errors=1, skipped=28)
  [fail] python3 -m pytest plugins/*/tests -q --import-mode=importlib
      11 failed, 8934 passed, 31 skipped, 3 xfailed, 15 warnings, 335 subtests passed in 1453.22s (0:24:13)
  [pass] git diff --check
  [pass] functional: registered-security-scan-skill
  [pass] functional: catalogue-repository-validation
  [no-preview-declared] branch preview
  [deferred-to-combined-branch] scenario smoke
  [pass] declarations
  [pass] review
```

### U3 iteration 2

```text
Iteration 2 at 183f5b34a02c8b7b0ee19a65292a76f9b090abfa: not green yet

  [pass] python3 scripts/check_repo.py
      Repository validation passed.
  [pass] python3 -m unittest discover -s tests -v
      OK (skipped=28)
  [fail] python3 -m pytest plugins/*/tests -q --import-mode=importlib
      1 failed, 8945 passed, 31 skipped, 3 xfailed, 15 warnings, 335 subtests passed in 1546.14s (0:25:46)
  [pass] git diff --check
  [pass] functional: registered-security-scan-skill
  [pass] functional: catalogue-repository-validation
  [no-preview-declared] branch preview
  [deferred-to-combined-branch] scenario smoke
  [pass] declarations
  [pass] review
```

### Final validation boundary

The final documentation commit precedes the serialized U2, U3 and combined-branch runs. Their exact iteration/pass numbers, revision, individual check statuses and any tool degradations are saved in the shared Saga run record and rendered in the implementation completion report. The final handoff must exit `0` at the full pushed PR head SHA; the historical iterations above are not passing evidence for that handoff. The four mechanical commands run against that same committed tree with zero unstaged drift. No writeup edit follows those final runs.

## Limits and next step

The declared functional environment is local/private, with no deploy or teardown command. The plan's real Python dependency/workflow planted-flaw scenario remains with the independent Functional Tester; unavailable required detecting rows are blocked, while unrelated gaps can honestly yield scan exit `2` even when both planted detections pass.

The implementation handoff will bind the final pushed revision to a passing combined-branch run via `build_loop.py --handoff`. Stop after PR creation and that handoff; the Lead routes the single code-review pass, and no merge or delivery occurs in this worker session.
