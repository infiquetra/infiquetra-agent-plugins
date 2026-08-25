# Saga Code Review — U8b cycle-16 mutation-proof regeneration (`evid-cycle16-agy1`)

This review covers the frozen evidence commit on `orch/mcport-9-resume1-evid-cycle16-agy1` because `MutationProofBindingTest` binds five graded tools to a named proof document, and unit U8a edited `scripts/assess_clients.py`, so the cycle-15 digest no longer names the shipped bytes.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `da2df28ed4ff041909d1fee2ae010f97ad6f4aa6` (`da2df28`, `docs(evidence): publish the cycle-16 mutation proof for the U8a harness edit`)
- Parent: `27cff9f62ffe3a7dc753a19029f082fa3754de71` (U8a review persisted on the run tip; one commit)
- Target: 2 files, +552 / −1
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `da2df28` is accepted.** Cycle-16 supersedes cycle-15 (preserved unedited), names the U8a `assess_clients.py` bytes, re-runs every cycle-15 anchor, adds five U8a-guard anchors, and records the former cycle-15 survivor as killed. The footer `FAILED (failures=1)` is the established mid-procedure protocol, not a documentation defect. Parallel scratch-copy isolation holds on the published kill-list arithmetic.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent (plan unit U8b / child #18 comments 5404729199 and 5404848068): regenerate the mutation proof as cycle-16 after the U8a graded-tool edit; re-run every cycle-15 anchor against current bytes; add anchors for the blocked-in-advance guards; re-point `MutationProofBindingTest`; leave the five-file `GRADED` tuple unchanged; do not edit the graded files or the cycle-15 document; disclose survivors rather than hide them.
- Delivered: that, with `survived: 0`.

### Plan-completion (U8b)

| Item | State | Evidence |
| --- | --- | --- |
| Cycle-16 proof published in established format | DONE | 551-line file; supersession header, baseline, 68 mutation blocks, digest footer, standing disclosures |
| Every cycle-15 anchor re-run against current bytes | DONE | 63/63 names preserved in order; 0 missing; recorded `(failures, FAIL lines)` tuples differ from cycle-15 (suite grew; runner now reports `skipped=1`) |
| New anchors for U8a blocked-in-advance guards | DONE | five trailing mutations on `scripts/assess_clients.py`; each killed by tests in `tests/test_assess_clients.py` |
| Cycle-15 survivor now kills | DONE | `missing data-file source file check removed` lists `FAIL: test_missing_data_file_source_is_reported_as_stale_source` (U6) |
| Binding pointer moves to cycle-16; `GRADED` unchanged | DONE | one-line diff in `tests/test_site_profile.py`; tuple still five paths |
| Graded files read-only / restore discipline | DONE | empty `git diff` on all five versus parent; footer `byte-identical to pristine: YES` |
| Cycle-15 file preserved unedited | DONE | zero-byte diff versus parent |
| Full suite green; `check_repo.py` green | DONE | 741 tests, 0 failed, 1 skipped; "Repository validation passed." |

COMPLETION: 8/8 DONE.

## Judgments

### (ITEM 1) Accept the mid-procedure `FAILED (failures=1)` footer — no documentation repair

Header `BASELINE: FAILED (failures=1), none of them outside the proof binding` and footer `final suite: FAILED (failures=1)` / `failures outside the excluded proof binding: none` describe the grind *before* the pointer update was committed. While the binding still named `2026-08-24-cycle15-mutation-proof-portable-copies.txt`, `test_the_portable_proof_names_the_bytes_that_ship` failed one subtest: `scripts/assess_clients.py` (U8a digest `2f8faf…` versus the cycle-15 digest `6d1cdc…`). That is the excluded binding test. The same commit re-points the binding, so at `da2df28` the three binding tests pass and discover is green (741 ran, 0 failed, 1 skipped — first-hand in this review).

Cycle-15 used the same protocol (`final suite: FAILED (failures=2)` because U3 and U5 had moved two graded files). The binding test's own docstring states the proof cannot start from a green suite and must exclude this test from grading. Rewriting the footer to `OK` would falsify the mid-procedure capture. Adding a postscript that the published revision is green is optional commentary, not a defect with a failure mode.

**Endorse as an honest procedural record. Not a documentation repair.**

### (ITEM 2) Parallel scratch-copy isolation holds

The unit did not commit its runner. Isolation is judged from the published blocks, the restore footer, and the committed tree.

Per-anchor isolation requires each kill list to come from a tree that contains exactly one mutation. Evidence it does:

1. **Binding-subtest arithmetic.** During the grind the binding still named cycle-15, so `assess_clients.py` always mismatched (one extra failure). Mutating a *different* graded file adds exactly one more binding subtest. First `check_repo.py` mutation: 2 listed `FAIL:` lines, `failures=4` (= 2 listed + `check_repo` mismatch + standing `assess_clients` mismatch). Target-copy `site_profile.py` mutation: 25 listed `FAIL:` lines, `failures=27` (= 25 + `site_profile` mismatch + standing `assess_clients` mismatch). New U8a mutations (already on `assess_clients.py`): listed `FAIL:`/`ERROR:` count + 1 binding = reported `failures`/`errors`. Two mutated graded files at once would inflate the binding by an extra subtest. The counts never show that.
2. **Five new U8a signatures are unique** and match the named guard (undeliverable detection, package-scoped isolation, inverted blocked-in-advance, reason text, `describe_plan` bypass). Shared `FAIL:` lines between inverted-condition and reason-drops are the same U8a tests that legitimately fail under either related mutation, not a stacked-mutation mix (package-scoped tests appear only on the skill-scoped-guard mutation; `describe_plan` bypass is an `ERROR:`-only kill).
3. **Zero survivors.** 64 mutations list `FAIL:` lines; 4 are `ERROR:`-only kills. None have an empty kill list. The cycle-15 survivor now has a `FAIL:` line.
4. **Restore.** Footer `byte-identical to pristine: YES`. All five footer sha256 values match `hashlib.sha256` of the committed blobs at `da2df28`. Unit worktree porcelain empty. `plugins/unifi` empty in the diff. The orchestrator's mid-grind clean primary worktree is consistent with per-anchor copies rather than in-place mutation of the published tree.

Scratch copies in parallel preserve isolation *if* each worker mutates its own copy. The failure-count arithmetic is what that looks like on the page. A shared in-place tree under two workers would have produced extra graded-file binding misses and mixed kill lists. It did not.

The unpublished runner is a residual the same shape as cycle-15 (that runner was also unpublished). It is not a finding: the proof format records results, not the grind harness, and nothing in the owned surface is an isolation defect.

**Endorse the methodology. Per-anchor isolation holds on the published evidence.**

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

Adversarial is 10.00 (cycle-15 was 9.80): the disclosed cycle-15 survivor now has a killing test, and the isolation assumption is evidenced by the kill-list arithmetic rather than left as a named untested guard.

## What was verified

Worktree at `da2df28` (disposable `/tmp/orch-cycle16-review-da2df28` plus the unit worktree):

- Footer sha256 equals committed bytes for all five `GRADED` paths, including `scripts/assess_clients.py` `2f8fafe9…` (U8a bytes). The other four digests are byte-identical to their cycle-15 values.
- `python3 scripts/check_repo.py` — "Repository validation passed."
- `python3 -m unittest tests.test_site_profile.MutationProofBindingTest` — 3/3
- `python3 -m unittest discover -s tests` — 741 ran, 0 failed, 1 skipped (`test_ported_command_surface_equals_the_upstream_surface`, upstream checkout not reachable)
- `git diff --check` — clean
- `git status --porcelain -- plugins/unifi` — empty
- `git diff` on the five graded files versus parent — empty
- Cycle-15 evidence file versus parent — empty
- Diff versus `27cff9f` is exactly the two owned files

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - The two-worker scratch-copy runner is unpublished (same residual as prior cycles). Isolation is inferred from the published blocks, not by re-executing the grind. A later proof cycle may keep using scratch copies; it does not need to commit the runner for this revision to stand.
  - `skipped=1` on mutation `FAILED()` lines is the existing upstream-checkout skip, now reported. It is not a new skip introduced by cycle-16.
- Independent gates actually run at `da2df28`: `check_repo`, full discover, binding test, digest footer match, UniFi no-churn, `git diff --check`. `evaluate_review_readiness` `can_proceed` is true.

## Findings

None.

## Routing

`accepted` — continue. No fix requests. ITEM 1 is endorsed as protocol. ITEM 2 is endorsed: parallel scratch copies preserved per-anchor isolation.
