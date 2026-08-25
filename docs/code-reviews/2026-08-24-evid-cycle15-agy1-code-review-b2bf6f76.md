# Saga Code Review — U5b cycle-15 mutation-proof regeneration (`evid-cycle15-agy1`)

This review covers the frozen evidence commit on `orch/mcport-9-resume1-evid-cycle15-agy1` because `MutationProofBindingTest` binds five graded tools to a named proof document, and a digest block that does not name the shipped bytes is the cycle-7 defect that test exists to catch.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `b2bf6f7687cbbdeafb2e05ee615b62dfa0f69ec8` (`b2bf6f7`, `docs(evidence): publish the cycle-15 mutation proof for the U3/U5 graded-tool edits`)
- Parent: `e449ccf03e7f089d8ec93ee319378374ef08c30a` (coordinator amendment inserting plan unit U5b; one commit after U5 merge `50822c8`)
- Target: 2 files, +514 / −1
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `b2bf6f7` is accepted.** The cycle-15 proof names the current graded bytes, every cycle-14 anchor was re-run, restore left the five graded files untouched, and the suite is green. The one survivor is disclosed, fail-closed, and out of this unit's owned surface — a U6/U8 test gap, not a U5b repair.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent (plan unit U5b / child #18 obligation early): re-run every cycle-14 mutation anchor against current graded bytes; add anchors for the U3 schema-3 refusals and the U5 data-file guards; publish `docs/evidence/2026-08-24-cycle15-mutation-proof-portable-copies.txt`; point `MutationProofBindingTest` at that document; leave the five-file `GRADED` tuple unchanged; do not edit the graded files.
- Delivered: that, including an honest `survived: 1` footer.

The submission named run tip `50822c8` as the parent. The frozen object's parent is the amendment `e449ccf` (which is itself the one commit on `50822c8`). The unit delta versus its parent is still exactly the two owned files. The plan edit is coordinator work, not this unit.

### Plan-completion (U5b)

| Item | State | Evidence |
| --- | --- | --- |
| Cycle-15 proof published in established format | DONE | 513-line file; baseline, 63 mutation blocks, digest footer, standing disclosures |
| Every cycle-14 anchor re-run against current bytes | DONE | 59/59 names preserved in order; 0 missing; recorded failure counts differ on every shared anchor |
| New anchors for U3 schema-3 refusals | DONE | bare-string entry killed (`test_a_bare_path_string_entry_is_refused_as_the_schema_2_shape`); missing rule name killed (5 FAIL lines) |
| New anchors for U5 data-file guards | DONE | stale byte-inequality killed (`test_data_file_seeded_hand_edit_fails_check_repo`, `test_data_file_seeded_stale_source_fails_check_repo`); missing-source recorded as survivor |
| Binding pointer moves to cycle-15; `GRADED` unchanged | DONE | one-line diff in `tests/test_site_profile.py`; tuple still five paths |
| Graded files read-only / restore discipline | DONE | empty `git diff` on all five versus parent; footer `byte-identical to pristine: YES` |
| Cycle-14 file preserved unedited | DONE | zero-byte diff versus parent |
| Full suite green; `check_repo.py` green | DONE | 696 tests, 0 failed, 1 skipped; "Repository validation passed." |

COMPLETION: 8/8 DONE.

## Judgments

### (a) Accept the disclosed survivor — do not request a killing test as a U5b repair

The footer records `mutations run: 63; survived: 1`. The surviving mutation is `missing data-file source file check removed` on `scripts/check_repo.py`. Its block is `FAILED (failures=2)` with **zero** `FAIL:` lines — the two failures are the excluded binding test, so nothing that was passing at baseline killed the mutation.

That matches the code. `check_bundled_files` (`scripts/check_repo.py:625`) reports `stale source: … source file missing` when a non-Python `_bundled/` file has no `plugins/fleet-core/scripts/fleet_commons/<basename>`. U5's tests seed a *changed* source or a *hand-edited* bundle; they never delete the source file under an existing data bundle. `bundle_fleet_module.plan_copies` refuses a missing source at generate time, which is a different path.

Removing the `is_file()` guard does **not** silent-green the repository gate: the next `source_file.read_bytes()` raises `OSError` and the same function reports `unreadable generated bundle`. The untested thing is the *named* missing-source error, not the gate going green.

The journal decision "A mutation proof excludes its own binding test" says a survivor count above zero is a real finding rather than a broken run. That is why the proof recorded it instead of claiming `survived: 0`. It is not a reason to fail the evidence unit that found it.

U5b's owned surface is the proof file plus the binding document reference. A killing test lives in `tests/test_bundle_fleet_module.py` (or U6 test custody). Adding it here would expand the unit, mutate a file it does not own, and force a second 63-anchor run. Cycle-12/13 accepted published proofs that disclosed defects in the header while keeping `survived: 0`; this is the same honesty, with the survivor in the footer because the protocol now measures it.

**Accept with the survivor disclosed.** It names a U5-surface test gap for U6/U8. A killing test is not a U5b repair.

### Proof integrity — anchors re-run, restore holds, binding is minimal

- **Re-run, not copy-paste.** All 59 cycle-14 mutation names appear in cycle-15 in the same order. Every shared anchor's recorded `(failures, listed FAIL lines)` tuple differs from cycle-14 (example: repository-gate break-set `failures=5` → `4`; `port_config.py` path-escape `failures=10` → `failures=34, errors=27`, which is the schema-3 descriptor surface U3 added). The four new anchors sit at the end.
- **Restore.** The unit commit contains none of the five graded files. Footer digests match `hashlib.sha256` of the committed blobs, including `scripts/check_repo.py` `6cf74eb9…` (the U5 bytes) and `scripts/port_config.py` `bfaeb492…` (the U3 bytes). The other three digests are unchanged from cycle-14, matching files this run did not edit.
- **Binding minimality.** The test file diff is exactly the document name `cycle14` → `cycle15`. `GRADED` is still the five-path tuple. Cycle-14 evidence is untouched.
- **Baseline honesty.** Header `BASELINE: FAILED (failures=2)` and footer `final suite: FAILED (failures=2)` / `failures outside the excluded proof binding: none` describe the run *before* the pointer update was committed. After this commit, `MutationProofBindingTest` is 3/3 and discover is green. That is the established publish protocol (the binding cannot pass until the document it names exists).

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 10.00 | `true` | none |
| `documentation-clarity` | 10.00 | `true` | none |
| `adversarial` | 9.80 | `true` | none |

Adversarial is 9.80 because load-bearing-assumptions is 9: one named guard has no killing test. That is the disclosed residual, not a failing dimension.

## What was verified

Worktree at `b2bf6f7`:

- Footer sha256 equals committed bytes for all five `GRADED` paths
- `python3 scripts/check_repo.py` — "Repository validation passed."
- `python3 -m unittest tests.test_site_profile.MutationProofBindingTest` — 3/3
- `python3 -m unittest discover -s tests` — 696 ran, 0 failed, 1 skipped
- `git diff --check` — clean
- `git status --porcelain -- plugins/unifi` — empty
- `git diff` on the five graded files versus parent — empty
- Cycle-14 evidence file versus parent — empty

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - No test deletes `plugins/fleet-core/scripts/fleet_commons/models.json` under a live data bundle and asserts `check_bundled_files` reports `source file missing`. Removing the `is_file()` guard still fail-closes via `OSError`. U6/U8 can add the case without touching graded files; the binding stays green; the proof will keep showing the survivor until a later cycle re-runs that one anchor.
- Independent gates actually run at `b2bf6f7`: `check_repo`, full discover, binding test, digest footer match, UniFi no-churn, `git diff --check`. `evaluate_review_readiness` `can_proceed` is true.

## Findings

None.

## Routing

`accepted` — continue. No fix requests. The survivor is accepted as a named, fail-closed test gap for later test custody, not as a repair on this evidence unit.
