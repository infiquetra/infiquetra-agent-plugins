---
date: 2026-08-30
kind: doc-review
target: docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md
reviewed_revision: 02c8bed371aabd38360d2c3033499c04bc330ab8
branch: orch-agent-plugins-50
classification: issue-derived implementation plan
blocked: false
cycles: 6
---

# Doc Review — Mission Control 2.15.2 resync plan

Amendment 4 at `02c8bed` can drive the two-test reclassification once the per-file site-count table is followed. Cycle 5's PROCEED still covers everything prior. Q8 remains the operator's.

## Applied fixes

Cycles 1–3 applied plan edits as recorded earlier. Cycles 4–5 applied none.

Cycle 6 filled KTD16's "exact per-file site counts" with a three-row table. Version 1 of `resolve-package-root-marker` requires exactly one finder and one module-scope call in every file it touches (`scripts/sync_vendor_source.py` 755–768). `tests/test_template_sync.py` has neither. A v2 that keeps that absolute requirement refuses the file this decision exists to carry. The table is the counts the cited pin lines already imply:

| File | finder | call | `.is_file()` | `pytest.raises` |
|---|---:|---:|---:|---:|
| `scripts/sync_template_docs.py` | 1 | 1 | 0 | 0 |
| `tests/test_issue_contract_parity.py` | 1 | 1 | 1 | 1 |
| `tests/test_template_sync.py` | 0 | 0 | 1 | 1 |

`plugins/mission-control/` was not modified. The 34 uncommitted paths there remain the preserved U2 sync.

## Readiness summary

`/work` is not blocked by a document defect. Two P2s remain: thirteen is not the proven minimum under option (a), and the U1c "third join" cites a UniFi-only test.

| review-result field | value |
| --- | --- |
| target path | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| reviewed repository revision | `02c8bed371aabd38360d2c3033499c04bc330ab8` (`git rev-parse HEAD` matched; subject `docs(mission-control): record the operator decision to transform the two remaining package-root tests`). Working tree carries 34 uncommitted paths under `plugins/mission-control/` only — preserved, not a dirty-tree blocker. Cycle-6 plan edit is in this working tree and lands with this artifact. |
| origin contract | [infiquetra/infiquetra-agent-plugins#50](https://github.com/infiquetra/infiquetra-agent-plugins/issues/50) and children [#51](https://github.com/infiquetra/infiquetra-agent-plugins/issues/51)–[#56](https://github.com/infiquetra/infiquetra-agent-plugins/issues/56) |
| classification | issue-derived implementation plan; issue-phase rubrics applied to Amendment 4 / KTD16 only |
| rubric phase | issue (three cores; three extras applied by judgment) |
| blocked | no |
| finding counts | P0: 0; P1: 0 open; P2: 2 open (D9, D10); P3: 0. D1–D8 closed. |
| applied fixes | cycle 6: per-file site-count table in KTD16 |
| override rationale | none |
| review artifact | `docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md` |
| linked issue / plan | #50; saga tick `.claude/saga/sagas/issue-50/20260830-204750.md`; destination merge; inline |

## Cycle 6 — Amendment 4 / KTD16 only

HEAD `02c8bed371aabd38360d2c3033499c04bc330ab8` was confirmed before this pass. Cycle-5 PROCEED was not re-opened.

### The seven questions

1. **71 files.** True. Committed descriptor has 48 `byte_copies`, 10 `entrypoint_transforms`, 3 `dropped_from_source`. Moving two tests is 46 / 12 / 3. Working-tree `PROVENANCE.json` has 70 `files` entries and does not list itself; `plugin.json` is one of the 70. The original 64 + 7 new tests = 71; option (a) does not remove a path. Option (b) is 69 and would break #53's line-129 checkbox. `git ls-files` is 64 on this branch because the U2 sync is uncommitted; that does not change the custody arithmetic.

2. **Rule spec.** After the cycle-6 table: sufficient. The pin lines are as claimed (parity 36 / 39 / 41 / 46 / 405 / 410–415; template-sync 175 and 186). The six-file `.claude-plugin` scan is exact: shim (3), `sync_template_docs` (2), agreement (3), prompt-alignment (10), parity (4), template-sync (2). No seventh `.py`. The walk and error text stay internals of the finder (KTD14). Refusal, idempotence, and source-bytes-only are stated. Without the table, v1's absolute 1+1 requirement would refuse `test_template_sync.py`.

3. **Cost.** Honest. KTD16 says the rule rewrites what a test asserts, that KTD14 did not cross that line, that this is a real weakening, and that it is not softened. Revisit when upstream is layout-neutral is the same real condition as KTD14.

4. **Thirteen commits.** Surfaced in §2.3, §5, §8.1, §8.2, and Q8. Not the proven minimum under option (a). The rule *name* is already registered at U2a (`PACKAGE_ROOT_MARKER_TRANSFORM_NAME` is in the U4a expected set). `test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements` joins names, not versions, so U1c does not require U2c first. U2c must precede U2b (v2 has to exist when the two tests are synced) and can fold into U2b. That is twelve: one new U1 commit plus an extended U2b. D9.

5. **Ownership.** Holds. U1c writes only the descriptor (third sequenced U1 commit; U3 still owns `assessment.mutating_operations` only). U2c writes only `scripts/sync_vendor_source.py`. Coverage folds into U4b, which already owns that file. No issue body was edited. No unit boundary moved.

6. **Inherited ACs.** #53's 71-file line is intact. #50 still allows recorded transforms. #53 out-of-scope still keeps the descriptor and downstream tests off U2. #55 still meets discover `OK` at U4c. No checkbox is narrowed. Rewriting assertions is a custody-principle cost, not an AC change.

7. **Disclosure.** Honest. KTD16 and §17 state the amendment postdates cycle 5's PROCEED and must not be treated as covered by it.

### D9 — open (P2)

Thirteen is honestly counted and honestly not a compatible reading of six. It is not forced by option (a). U2c as a standalone commit is a preference.

### D10 — open (P2)

§5's "third join" cites `CommittedDescriptorTest.test_the_custody_table_accounts_for_every_shipped_managed_path`. That method uses `self.config`, and `CommittedDescriptorTest.setUp` loads **unifi** only (`tests/test_port_config.py` 470–471). A mission-control reclassification does not fail it. U1c is green on a clean checkout without re-running the transform on the working tree; the operator-visible caveat is aimed at the wrong test.

### Formal issue-rubric results (Amendment 4 only)

| rubric | cycle 6 | evidence |
| --- | --- | --- |
| Acceptance criteria clarity | PASS | R45/R46 plus the site-count table are reviewer-identical |
| Devil's advocate | REVISE | option (a) is the smallest slice that keeps 71; D9 is extra commit cost |
| Specification fidelity | PASS | #53 line 129 unweakened; no issue edited |
| Context completeness | PASS | after the table, files, pin lines, and v1 constraint are named |
| Issue sizing | PASS | two files, one rule version bump |
| Prerequisite mapping | REVISE | U2c before U2b is real; U2c before U1c is not forced by the cited test |

## Remaining findings by priority

| id | priority | status | disposition |
| --- | --- | --- | --- |
| D1–D8 | — | closed | as in cycle 5 |
| D9 | P2 | open | thirteen surfaced; twelve is reachable under option (a) by folding U2c into U2b |
| D10 | P2 | open | U1c third-join cites a UniFi-only custody-agreement test |

## Residual risk from limited evidence

The six-file scan was `git grep -F '.claude-plugin'` at `3b2b7083` against `plugins/mission-control/**/*.py`. Collection failure on the parity file was not re-executed; the module-scope call at line 46 matches the already-reproduced `sync_template_docs` shape. 71 vs this branch's `git ls-files` of 64 is the uncommitted U2 sync, not a custody error.
