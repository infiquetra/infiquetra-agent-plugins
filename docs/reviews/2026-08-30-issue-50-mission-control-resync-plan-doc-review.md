---
date: 2026-08-30
kind: doc-review
target: docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md
reviewed_revision: 1e4da2be8dd2d1256f1e61765629ecf6a0571de9
branch: orch-agent-plugins-50
classification: issue-derived implementation plan
blocked: true
cycles: 1
---

# Doc Review — Mission Control 2.15.2 resync plan

The plan is blocked: U3's issue-#54 full-suite gate cannot pass while U3 and U4 start together from the post-U2 tree, because U4's pin constants are still red.

## Applied fixes

Five evidence-backed edits were applied to the plan in the working tree after reviewing `1e4da2b`. None changes scope, architecture, or acceptance criteria.

1. Named the U0 upstream suite as `uv sync --locked --extra dev` and `uv run pytest`, the commands at `3b2b7083:README.md`.
2. Added the `_open_mapping_pr` notes claim (4664 → 5552) and the stale "twenty-one test files" count (→ 28) to the U1 refresh table, and extended R12 and the U1 `grep` to match.
3. Recorded in §2.6 the U2 pin-constant exception already stated in §8.1 step 3, and annotated the U2 verification block.
4. Split the U0 Phase 3 skip row so a mutation-proof re-run is skipped, matching §2.8 and KTD11.

## Readiness summary

`/work` is blocked until D1 is resolved. An implementer who starts U3 and U4 together from the post-U2 commit will see `unittest discover` fail on the three `test_sync_vendor_source` pin constants, which U3 does not own and #54 requires to be green.

| review-result field | value |
| --- | --- |
| target path | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| reviewed repository revision | `1e4da2be8dd2d1256f1e61765629ecf6a0571de9` (clean HEAD at review start); safe fixes are uncommitted working-tree edits |
| origin contract | [infiquetra/infiquetra-agent-plugins#50](https://github.com/infiquetra/infiquetra-agent-plugins/issues/50) and children [#51](https://github.com/infiquetra/infiquetra-agent-plugins/issues/51)–[#56](https://github.com/infiquetra/infiquetra-agent-plugins/issues/56) |
| classification | issue-derived implementation plan; issue-phase rubrics applied |
| rubric phase | issue (three cores; three extras applied by judgment) |
| blocked | yes |
| finding counts | P0: 0; P1: 1 open; P2: 0 open; P3: 1 open |
| applied fixes | five plan edits listed above |
| override rationale | none |
| review artifact | `docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md` |
| linked issue / plan | #50; saga tick `.claude/saga/sagas/issue-50/20260830-204750.md`; destination merge; inline |

The rest of the contract is faithful. The graph is `U0 → U1 → U2 → {U3, U4} → freeze → U5`. `ports/mission-control.json` has sequenced writers U1 then U3. `plugins/mission-control/README.md` has one writer, U3. The freeze follows U3. The five cycle-16 graded files are forbidden. The four operator rulings are restated, not re-litigated. First-hand checks at the pin and on this tree confirmed the pin SHA, the three-revision trees, the 36-file / 15-5-5-1-1-1-8 custody map, 64 → 71, the graded-file digests, merge policy, verb-table lines, and the create-option / set-options implementations.

## Formal issue-rubric results

The issue-phase rubric review blocks on one gate contradiction, not on missing structure.

Cores applied: `acceptance_criteria_clarity`, `devils_advocate_issue`, `spec_fidelity`. Extras applied by judgment: `context_completeness` (non-trivial repo, named files required), `issue_sizing` (six units, descriptor plus sync plus target-owned plus pins plus evidence), `prerequisite_mapping` (child graph, freeze, U5 operator window).

| rubric | result | evidence |
| --- | --- | --- |
| Acceptance criteria clarity | BLOCK | D1: #54 and U3 require `unittest discover` OK; after U2 that command is red until U4. |
| Devil's advocate | PASS | The slice matches the six child issues; the four rulings are not re-opened; extras are deferred with revisit conditions. |
| Specification fidelity | REVISE | Parent #50 and children #51–#56 are inherited. D1 is the same contradiction the parent graph and #54 both state. |
| Context completeness | PASS | Paths, commands, and stop conditions are named. The U0 suite command and the missed notes claims were filled from first-hand evidence. |
| Issue sizing | PASS | Six child-scoped commits and one squash-merged PR match the inline run. |
| Prerequisite mapping | BLOCK | D1: U3's full-suite gate is a hidden prerequisite on U4, so the two-wide pair cannot both commit from post-U2. |

Rubric findings are the D-series below. They are not reclassified as a separate readiness list.

## Remaining findings by priority

Finding IDs are this review's, sorted by priority, then source anchor, then title. Priorities use Saga's P0–P3 scale.

| id | priority | status | anchor (at `1e4da2b`) | class | summary |
| --- | --- | --- | --- | --- | --- |
| D1 | P1 | open | U3 Verification / §8.1 step 4 / #54 | issue rubric: acceptance criteria and prerequisites | U3's full-suite gate is red until U4, so two-wide independent commits from post-U2 are not executable. |
| D2 | P3 | open | U5 Verification / R36 | readiness: completeness | U5's verification block omits the package pytest and floor run that R36 requires of every unit. |

### D1. U3 cannot pass its full-suite gate until U4 lands

Issue #54 and the plan's U3 verification both require `python3 -m unittest discover -s tests` to report OK. After U2, `tests/test_sync_vendor_source.py:1359` and `:1382` still pin `84eaf042` / `2.12.2` while `PROVENANCE.json` already records `3b2b7083` / `2.15.2`, so that class fails on purpose until U4.

KTD10 and §8.1 step 4 start U3 and U4 together from the post-U2 commit and say each commits only after its own gates pass. U3 does not own `tests/test_sync_vendor_source.py`. Following U3 literally, an implementer either stops on a red suite, or "fixes" U4's file and breaks ownership.

Required disposition: pick one and write it into U3, §5, and §8.1. Either serialize U4 before U3's discover gate (two-wide start is then only wall-clock overlap until U4 commits), or give U3 the same named pin-constant exception U2 already has and move the #54 discover-OK line to freeze integration. Do not leave both the two-wide commit rule and the #54 AC in force.

### D2. U5 verification omits the package-suite lines R36 requires

R36 says every unit runs the four gates plus the floor package run. U5's verification block runs `check_repo.py`, `unittest discover`, and `git diff --check`, and not `pytest plugins/mission-control/tests` on either interpreter.

This does not block the run. U5 is fingerprint-neutral and does not change package tests. Add the two pytest lines to the U5 block so R36 is uniform, or narrow R36 to units that touch the package suite.

## Residual risk from limited evidence

The local upstream checkout `../infiquetra-claude-plugins` is at `bbac725`, not at the pin. The pin commit is present and the plan's U0 scratch clone plus `--commit 3b2b7083` / `git show 3b2b7083:` do not depend on that HEAD. Tracked files there were clean; untracked review files were present and are ignored by `require_clean_checkout`.

The seven new tests were not re-read end to end. U1 already requires that re-verification before classifying them as byte copies.

The U0 suite command was taken from the pin README. Default pytest addopts at the pin include coverage output, which is acceptable only because the clone is disposable.
