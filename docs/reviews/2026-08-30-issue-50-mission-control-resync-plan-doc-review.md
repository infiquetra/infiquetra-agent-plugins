---
date: 2026-08-30
kind: doc-review
target: docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md
reviewed_revision: b164026b8e2367d1d3e828d0c3d8bfc06ae9b702
branch: orch-agent-plugins-50
classification: issue-derived implementation plan
blocked: true
cycles: 3
---

# Doc Review — Mission Control 2.15.2 resync plan

Amendment 1 at `b164026` is not ready to drive U2: after the new rule lands, `LiveDocumentTest` stays red through freeze while #54 still requires `unittest discover` `OK`.

## Applied fixes

Cycle 1 applied five evidence-backed plan edits; those plus the author's D1 and D2 repairs landed in `82dcb1c`. Cycle 2 applied none.

Cycle 3 applied four plan edits at this working tree, none of them a coordinator decision:

- KTD14 and U2 deliverable 6 now name the match unit: one `_find_package_root` plus one module-scope call; the two `.claude-plugin` sites inside the function are not two matches; a concatenated-string search hits only the error text.
- §6.2 no longer claims "No two of the three share a JSON key." U1 and U2 share `custody.byte_copies` and write disjoint members.
- U2's leftover "Test expectation: none authored" and "does not touch that file" now agree with Amendment 1's rule-coverage ownership.

`plugins/mission-control/` was not modified. The 34 uncommitted paths there are the stopped U2 sync and were left untouched.

## Readiness summary

Cycle 2's PROCEED still holds for the pre-amendment plan. Amendment 1 / KTD14 is the only material under review. `/work` is blocked on D4.

| review-result field | value |
| --- | --- |
| target path | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| reviewed repository revision | `b164026b8e2367d1d3e828d0c3d8bfc06ae9b702` (`git rev-parse HEAD` matched; subject `docs(mission-control): record the sync_template_docs custody decision as plan Amendment 1`). Working tree carries 34 uncommitted paths under `plugins/mission-control/` only — preserved, not a dirty-tree blocker. |
| origin contract | [infiquetra/infiquetra-agent-plugins#50](https://github.com/infiquetra/infiquetra-agent-plugins/issues/50) and children [#51](https://github.com/infiquetra/infiquetra-agent-plugins/issues/51)–[#56](https://github.com/infiquetra/infiquetra-agent-plugins/issues/56) |
| classification | issue-derived implementation plan; issue-phase rubrics applied to Amendment 1 only |
| rubric phase | issue (three cores; three extras applied by judgment) |
| blocked | yes |
| finding counts | P0: 0; P1: 1 open (D4); P2: 1 open (D5); P3: 2 open (D6, D7). D1–D3 closed. |
| applied fixes | cycle 1: five plan edits (in `82dcb1c`); cycle 2: none; cycle 3: four plan edits listed above |
| override rationale | none |
| review artifact | `docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md` |
| linked issue / plan | #50; saga tick `.claude/saga/sagas/issue-50/20260830-204750.md`; destination merge; inline |

## Cycle 3 — Amendment 1 only

HEAD `b164026b8e2367d1d3e828d0c3d8bfc06ae9b702` was confirmed before this pass. Cycle-2 PROCEED at `82dcb1c` is not re-opened. Only Amendment 1 / KTD14 / §14 was judged.

### First-hand reproduction

At pin `3b2b7083`, `plugins/mission-control/scripts/sync_template_docs.py` defines `_find_package_root()` at line 17, walks for `.claude-plugin/plugin.json` at line 20, raises `RuntimeError` at line 22, and calls that function at module scope on line 27. The committed portable copy at this SHA still uses the old `parents[3]` form; the working-tree file is the untransformed 2.15.2 bytes from the stopped U2 sync.

Imported from a throwaway tree that had `com.infiquetra.claude/plugin.json` and no `.claude-plugin/`:

```
RuntimeError: package root containing .claude-plugin/plugin.json not found from
  …/plugins/mission-control/scripts/sync_template_docs.py
```

The pin file has two `.claude-plugin` sites: the Path check at line 20 (`parent / ".claude-plugin" / "plugin.json"`) and the concatenated string in the error text at line 23 (the only `.claude-plugin/plugin.json` substring). A replace of that substring updates the error and leaves the walk looking for `.claude-plugin`.

`tests/test_site_profile.py` `MutationProofBindingTest.GRADED` (lines 1083–1089) is exactly `plugins/unifi/scripts/site_profile.py`, `scripts/check_repo.py`, `scripts/check_compatibility_matrix.py`, `scripts/port_config.py`, `scripts/assess_clients.py`. `scripts/sync_vendor_source.py` is not graded. The Amendment 1 claim is true.

### The seven amendment questions

1. **Custody path vs upstream filing.** Legitimate under this repository's contract and precedent. §2.7's table row sends a *byte-copy content* change upstream; reclassifying the path out of `upstream-byte-copy` is the other class the runbook already runs. #53's own stop table names "upstream filing or a recorded custody decision." `normalize-skill-frontmatter` is the same shape: upstream keeps a form that is correct for Claude and unusable verbatim in the portable layout; a versioned rule transforms it from source bytes alone. The fleet split/guarded pair is the same pattern for an import. Filing would ask upstream to stop using `.claude-plugin/`, which is their layout. Not a downstream patch of copied content.

2. **Rejected alternatives.** (a) hand-edit, (b) drop like the shim, (c) file-and-stop are honest. The shim drop does not fit: nothing replaces this file, and it is a declared entrypoint. Dummy `.claude-plugin/` in the portable tree is an unlisted fourth hack (D7).

3. **Rule tightness.** After the cycle-3 match-unit fill: single-shape, exactly-one function-plus-call, refuse if missing/duplicated, idempotent on already-portable input, reproducible from source bytes, `--check` / provenance digests via the existing transform record (`test_every_transform_records_source_output_rule_and_version`). The worker still writes the Python. That part can drive work. The *gate* around it cannot (D4).

4. **File ownership.** Three sequenced writers on `ports/mission-control.json` survive single-writer discipline once the false "no shared JSON key" sentence is corrected: U1 and U2 share a key and write disjoint members; U3's key is disjoint; later-writer-changes-earlier-region still holds. `scripts/sync_vendor_source.py` is U2 sole writer. `tests/test_sync_vendor_source.py` is U2 then U4 on disjoint tests.

5. **Disclosure.** Honest. §14 and KTD14 state the section postdates the `82dcb1c` PROCEED, was a coordinator decision, the planner recorded it, and the rule is unwritten.

6. **#50 / #53 / inherited ACs.** No #50 or #53 acceptance checkbox is narrowed. #50's "except the recorded transforms" still covers a fifth rule. #53's sync / `--check` / 71 files / digest / pytest lines still hold. #53 *out-of-scope* ("No edit to `ports/mission-control.json`"; "No downstream test edits") contradicts the amendment (D5). #54's `unittest discover` `OK` becomes unreachable after U2 (D4) — that is an inherited AC the amendment does not acknowledge as moved.

7. **Graded set.** `scripts/sync_vendor_source.py` is outside the cycle-16 graded set. Adding a rule there does not retire the proof. `port_config.py` validates rule names as names only; the registry lives in the synchronizer. U2's stop if `port_config.py` seems required is sound.

### D4 — open (P1)

§14.1 records that after resync, `test_check_compatibility_matrix.LiveDocumentTest.test_the_no_argument_run_validates_every_committed_matrix` fails because `ccm.main([])` validates every committed matrix, and the current mission-control matrix still binds the old 64-file / `651ac28a…` fingerprint. That is first-hand: `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md` is `matrix-status: current` with those numbers; `check_repo.py` does not invoke the checker (Q5).

The amendment then says the failure is U5's, is a separate coordinator call, and that the graph, KTD10, and freeze-after-U3 did not change.

Followed literally:

- U2's stop fires on any discover failure other than the three pin constants and the six import/collection errors. After the new rule those six clear. `LiveDocumentTest` remains. U2 stops.
- U3 rebases onto U4 and must get discover `OK` (#54 AC; §8.1 step 4c; cycle-2 D1). `LiveDocumentTest` is still red. #54 cannot close.
- Freeze (step 5, before U5) requires all four gates green. The test that U5 is supposed to clear is red, so freeze cannot happen and U5 cannot start.

Filling U2/U3/freeze expected-red lists, or moving freeze after U5, or giving U3 a second discover exception, would invent the coordinator call §14.1 left open. Not a safe fix. Cycle-2 D1 forbade narrowing #54's discover-OK line.

### Formal issue-rubric results (Amendment 1 only)

| rubric | cycle 2 (whole plan) | cycle 3 (amendment) | evidence |
| --- | --- | --- | --- |
| Acceptance criteria clarity | PASS | BLOCK | R40/R41 are testable; U3/#54 discover-OK and freeze-green are not, once §14.1's failure is real |
| Devil's advocate | PASS | REVISE | custody path is the smallest useful slice; the unresolved LiveDocumentTest / #54 collision is failure-mode blindness |
| Specification fidelity | PASS | BLOCK | #53 ACs unweakened; #54 discover-OK becomes unreachable; #53 out-of-scope contradicts the amendment (D5) |
| Context completeness | PASS | PASS | after the match-unit fill, files, precedent, and test file are named |
| Issue sizing | PASS | PASS | one custody reclassification, one unit |
| Prerequisite mapping | PASS | BLOCK | U5 is now a hidden prerequisite of U2's commit, U3's gate, and freeze; §14.1 names it and does not schedule it |

## Cycle 2 verification (unchanged)

HEAD `82dcb1cdd5e74e0f5ae47a3aa86d67a67b35bba3` was clean before that pass. Only D1 and D2 were re-checked. Both closed. See the cycle-2 text in the previous revision of this artifact; the dispositions stand.

## Remaining findings by priority

| id | priority | status | disposition |
| --- | --- | --- | --- |
| D1 | P1 | closed | landing order serialized; two-wide work kept; #54 unweakened at `82dcb1c` |
| D2 | P3 | closed | all six unit blocks uniform against R36 |
| D3 | P1 | closed | match unit filled from the cited pin lines; concatenated-string trap named |
| D4 | P1 | open | `LiveDocumentTest` unnamed in U2's stop and in U3/freeze gates; #54 discover-OK unreachable until U5; coordinator call not taken |
| D5 | P2 | open | live #53 out-of-scope still forbids descriptor and `test_sync_vendor_source.py` edits; ACs not narrowed; issues unedited |
| D6 | P3 | open | #50 shaping still says the descriptor has exactly two writers (U1 then U3) and omits `scripts/sync_vendor_source.py` from files-expected |
| D7 | P3 | open | rejected alternatives omit planting a dummy `.claude-plugin/` marker; not a contract path |

## Residual risk from limited evidence

The six named import/collection failures were not re-executed on this dirty tree; the import `RuntimeError` was reproduced in a throwaway portable-shaped tree, and the two suite files that import `sync_template_docs` (`tests/test_client_entrypoints.py`, `tests/test_mission_control_rule_audit.py`) are present in-repo. `LiveDocumentTest` was not re-run; the failure follows from `ccm.main([])` plus the committed current mission-control matrix bytes.

The local upstream checkout HEAD may not sit at `3b2b7083`. Pin reads used `git show 3b2b7083:`.
