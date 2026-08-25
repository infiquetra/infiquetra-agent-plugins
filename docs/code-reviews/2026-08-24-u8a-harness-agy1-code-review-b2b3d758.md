# Saga Code Review — U8a harness seam repair (`u8a-harness-agy1`)

This review covers the frozen graded-tool repair on `orch/mcport-9-resume1-u8a-harness-agy1` because `assess_clients.py` plan evaluation raised `AssessmentError` for mission-control's package-root entrypoints on skill-scoped clients, which made the ten-client Phase 3 assessment unrunnable.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `b2b3d75861164a100d004482aebfd90e1eed068d` (`b2b3d75`, `fix(assess): block skill-scoped invocation in advance for package-root entrypoints (run unit U8a)`)
- Named base: `4c7127751126ea3ebb76dbd6fb9dbdf9efb88095` (U8 freeze record)
- Target: 3 files, +212 / −6
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `b2b3d75` is accepted.** Skill-scoped invocation with undeliverable package-root entrypoints is blocked in advance through the existing `StageOutcome` seam. UniFi plan print is byte-identical to the freeze tip. The single MutationProofBindingTest failure is the designed intermediate state; cycle-16 belongs to U8b.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent (#18 stop disposition): for a skill-scoped client with any entrypoint outside every skill unit, record invocation as blocked in advance (reason names the client design and lists undeliverable paths); package-scoped and all-deliverable skill-scoped clients unchanged; both plan print and execute path; corpus tests; journal.
- Delivered: `undeliverable_entrypoints` + `stage_blocked_reason` wired into `run_stage`, `assess` (plan mode), and `describe_plan`; five new tests; LEARNINGS entry. `plugins/` untouched.

### Plan-completion (U8a)

| Item | State | Evidence |
| --- | --- | --- |
| Skill-scoped + undeliverable → invocation BLOCKED in advance | DONE | plan print for OpenCode/Gemini/Muse/Hermes; `run_stage` returns `BLOCKED` |
| Reason names design and lists all five MC scripts | DONE | reason text includes all `scripts/*.py` entrypoints |
| Any undeliverable blocks the whole invocation | DONE | mixed test names only `scripts/discover.py`, not the skill-resident path |
| Package-scoped unchanged | DONE | Claude/Cursor/Qwen/Grok/Agy still print 5 `--help` commands |
| UniFi skill-scoped all-deliverable unchanged | DONE | `diff -q` of unifi plan at `4c71277` vs `b2b3d75` identical |
| Plan mode no longer raises | DONE | parent raises `AssessmentError` on OpenCode; frozen exits 0 |
| Execute path uses the same seam | DONE | `run_stage` calls `stage_blocked_reason` before `stage_argvs` |
| Corpus tests capable of failing | DONE | five new tests; commit body records inverted-guard probes |
| Journal | DONE | LEARNINGS 2026-08-25 |
| Full suite green | CHANGED / deferred | 741 ran, 1 failed — binding on `assess_clients.py` (judgment) |

COMPLETION: 9/10 DONE, 1 CHANGED.

## Judgment

### Named mutation-proof debt to U8b — sound

`MutationProofBindingTest` binds five graded files to the cycle-15 proof. This unit edited `scripts/assess_clients.py` (digest `6d1cdc…` → `2f8faf…`). The other four footer digests still match. Discover: 741 tests, exactly one failure, that subtest; 1 skip.

Regenerating the proof is U8b (cycle-16), matching the in-run U3/U5 → U5b (cycle-15) train. Editing digest lines without re-running the proof is the tampering that test exists to catch. U8a's owned surface is the harness, its tests, and the journal — not `docs/evidence/`.

The freeze package tree is untouched (`plugins/` empty in the diff), so the package fingerprint the U8 freeze pinned does not move.

**Endorse the intermediate state. The proof re-run does not belong to U8a.**

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 10.00 | `true` | none |
| `documentation-clarity` | 10.00 | `true` | none |
| `adversarial` | 10.00 | `true` | none |

## What was verified

Worktree at `b2b3d75`:

- Parent `python3 scripts/assess_clients.py --package mission-control` raises `AssessmentError: … scripts/sdlc_manager.py … OpenCode`
- Frozen: same command exits 0. Four skill-scoped clients print `invocation blocked in advance:` listing all five entrypoints. Five package-scoped clients (Claude, Cursor, Qwen, Grok, Agy) print five `--help` commands. Codex keeps its pre-existing adapter block (not the new reason).
- Unifi plan print at `4c71277` vs `b2b3d75`: `diff -q` identical
- `check_repo.py` passed
- New `EntrypointPathTest` methods 11/11 including the five added
- Binding: fail only `scripts/assess_clients.py`; other four GRADED match cycle-15
- Discover: 741 ran, 1 failed, 1 skipped
- `pytest plugins/mission-control/tests -q`: 266 passed
- sync `--check` at `84eaf042`: exit 0
- `git diff --check` clean; `plugins/` empty in the unit diff

`entrypoint_paths` still raises for an unresolvable skill-scoped path; `describe_plan` / `assess` / `run_stage` now consult `stage_blocked_reason` first so that raise is not the plan-time abort. Static `spec.blocked_reason` (Codex) still wins.

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - Commit message says “6 package-scoped clients” print five `--help` commands; Codex is package-scoped but already blocked on the adapter. Tests correctly omit Codex from that assertion.
  - Execute-mode row classification for skill-scoped mission-control (placement/load execute, invocation blocked) is left to `propose_status` and will show up in the U8 evidence re-run; this unit did not change the classifier.
- Independent gates actually run at `b2b3d75`: `check_repo`, package pytest, sync `--check`, unifi plan identity, mission-control plan exit 0, `git diff --check`. `evaluate_review_readiness` `can_proceed` is true. The binding failure is named U8b debt, not a failed independent gate.

## Findings

None.

## Routing

`accepted` — continue. No fix requests. Cycle-16 is U8b.
