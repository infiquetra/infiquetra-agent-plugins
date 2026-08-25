# Saga Code Review — U8 integration (`mcport-9-resume1` at `a13f514`)

This is the single integration review required by parent #9 at unit U8, distinct from the twelve per-unit reviews already concluded. It asks whether the assembled branch is one consistent shipped state, safe to merge to `main` as a merge commit.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `a13f51436b97642bb739489c8a06def4d3dae02a` (`a13f514`, `docs(code-reviews): record U8 Phase 3 evidence review of ac7eec7`)
- Merge target: `origin/main` `39485255b7a22e35ad1ed32e90987c8b889ac785` (U2 squash; ancestor of HEAD)
- Target: 121 files, +32277 / −182
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `a13f514` is accepted for the integration merge.** Descriptor, package, bundle, tests, CI, and evidence compose. The matrix fingerprint matches the frozen package tree. Cycle-16 digests match the committed graded files. The four skill-scoped blocked-in-advance rows are the U8a harness text. `origin/main` is an ancestor, so a merge commit cannot conflict and cannot move file digests. The three disclosed residuals remain residuals, not merge blockers.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent (#9 U8 + #18): one integration review of the frozen assembled revision; then one merge-commit PR to `main`.
- Delivered: the complete portable mission-control package plus the tooling, tests, CI, evidence, freeze records, journal, and per-unit review artifacts needed to land it. UniFi package tree is byte-identical to `origin/main`. Fleet Core already landed via U2.

### Plan-completion (#18 at the integration SHA)

| Item | State | Evidence |
| --- | --- | --- |
| Frozen candidate recorded | DONE | `4c71277` (original freeze); successor `e3780cd` (post U8a/U8b). Package git tree `12433538e5b8…` identical at `4c71277`, `e3780cd`, and `HEAD` |
| Suites green at frozen state | DONE | `check_repo` pass; hermetic 741 OK skipped 1; package pytest 266; `sync --check` at `84eaf042`; Fleet Core bundle `--check` pass |
| One current fingerprint-bound matrix | DONE | `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md`; checker pass; 10/40 stages, 33 executed, 7 blocked; statuses 1 works-directly / 8 adapter / 1 failed |
| Unit-authored reasons reviewed | DONE | per-unit U8 freeze review endorsed ITEM 3; integration re-checked skill-scoped reasons against the live harness template |
| One readback | DONE | `docs/evidence/2026-08-25-mission-control-post-activation-readback.md`; disposition `verified_by_digest_recheck` at `e3780cd` |
| Mutation-proof obligation | DONE | cycle-16 document + binding; digest re-check: all five GRADED sha256 values equal footer, readback, and committed blobs. Cycle-15 preserved unedited |
| Integration review | DONE | this process |
| Merge to main + post-merge checker | not this SHA | orchestrator after `accepted`; fingerprint binds to tree bytes, which a merge commit cannot change |

COMPLETION: 7/7 DONE for merge-readiness of `a13f514`. Post-merge checker is an after-merge gate.

## (1) Cross-unit coherence

The parts compose. No two units' deliverables contradict.

- **Descriptor (U1/U3) vs package (U3/U4/U5).** `ports/mission-control.json` schema 3, `package_root` `plugins/mission-control`. Assessment names the same five `scripts/*.py` entrypoints that exist on disk and the same seven `skills/*` units. `plugin.json` name/version `mission-control` / `2.12.2` matches PROVENANCE `source_version` and both evidence records. Source repository matches. Pin `84eaf042` lives in PROVENANCE (not in the descriptor source object); `sync --check` against that pin passes.
- **Bundle (U2 on main + U5).** `fleet-bundle.json` schema 2, modules `intent_envelope` + `tier_palette`, data `models.json`. All three files present under `scripts/_bundled/`. `bundle_fleet_module.py --check --plugin mission-control` passes. UniFi tree `eccfdd0e…` equals `origin/main`.
- **Tests + CI (U6/U7/U8a).** Hermetic `unittest discover` collects the rule-audit, harness, descriptor, and binding tests (741). CI `plugin-tests` runs `pytest plugins/*/tests` on Python 3.12 with PyYAML — the glob covers `plugins/mission-control/tests` (266). `test_python_floor.py` still owns the `python>=3.12` pin. `test_client_entrypoints.py` iterates `ports/*.json`.
- **PROVENANCE vs tree.** 63 classified paths; git tree 64 because `PROVENANCE.json` does not list itself. `check_repo` closed-set is green. Fingerprint counts all 64.
- **Review artifacts.** Twelve per-unit `review_result.v1` sets are present at HEAD. U0/U1/U2 already sit on `origin/main` (U2 squash). The other nine are in this delta. This integration review is the thirteenth and cannot be inside the SHA it reviews.
- **`ports/unifi.json`.** Schema 3 alongside mission-control (U3). UniFi current matrix still binds `23` / `22bfa568…`. Two current matrices, two packages, checker validates both.

## (2) Evidence mutual consistency

- **Fingerprint.** `--print-fingerprint mission-control` = `file_count` 64, `tree_sha256` `651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682`. Identical in the matrix JSON `$.package`, the readback `release`, and the freeze-successor plan text. Package git tree `12433538e5b8aa9d88b573e695ef9bc6786549ab` at `HEAD`, `e3780cd`, `4c71277`, `b2b3d75`, `da2df28`, `ac7eec7`, and U5 `700a50c` (the last package-byte commit).
- **Cycle-16 chain.** Binding in `tests/test_site_profile.py` names `2026-08-25-cycle16-mutation-proof-portable-copies.txt`. Footer sha256 = committed blobs = readback `graded_file_digests` for all five GRADED files, including U8a `scripts/assess_clients.py` `2f8fafe9…`. Disposition `verified_by_digest_recheck`, not regeneration. Cycle-15 file is still present and unedited after `da2df28`.
- **Matrix vs U8a.** `undeliverable_entrypoints` + `stage_blocked_reason` emit the blocked invocation text. OpenCode, Gemini CLI, Muse, and Hermes invocation `reason` fields are that template with the five descriptor entrypoints in order. Cursor is package-scoped (`--plugin-dir`); its `failed` row is the `sync_template_docs.py` `parents[3]` layout bug, not a U8a miss. Claude Code records the same FileNotFoundError in invocation evidence but stays adapter because session-only `plugin details` and marketplace are independently true.

## (3) Merge-readiness

`git merge-base --is-ancestor origin/main HEAD` is true. A merge to `main` cannot conflict. The plan requires a **merge commit, never squash**, so every recorded per-unit SHA stays reachable. File digests (and therefore `tree_sha256`) do not move when a merge commit is added. The orchestrator must run `check_compatibility_matrix.py` again on `main` after the merge; that is an after-merge gate, not a defect in `a13f514`.

## (4) Completeness against #18

Frozen candidate, successor freeze, green suites, one current matrix with unit-authored reasons, one readback, cycle-16 discharged by digest re-check, and this integration review: all present. Closeout (README/llms.txt/upstream filings/board) is U9, after this merge, per the landing model.

## Disclosed residuals (covered knowingly)

1. **Cursor `failed`.** Real relocatability finding in byte-copied `sync_template_docs.py` (`parents[3]`). Independently reproduced at the U8 freeze review. #18 forbids local remediation. U9 files upstream.
2. **Four skill-scoped invocations blocked in advance.** True client-design facts (skill units, not package root). U8a semantics, production-recorded.
3. **`080b535`.** First evidence unit's blocked report, still a commit on unmerged `orch/mcport-9-resume1-u8-freeze-agy1`. Not in this merge. Durable stop record.

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
| `api-contract` | 10.00 | `true` | none |

## What was verified

At `a13f514` (run checkout + disposable `/tmp/orch-integration-review-a13f514`):

- Diff vs `origin/main`: 121 files, +32277 / −182
- Package git tree `12433538e5b8…` (64 blobs); UniFi tree equals `origin/main`
- `--print-fingerprint mission-control` matches matrix and readback
- `check_compatibility_matrix.py` on the mission-control matrix — pass
- `check_repo.py` — pass
- `sync_vendor_source.py --check` at `84eaf042` — pass
- `bundle_fleet_module.py --check --plugin mission-control` — pass
- `unittest discover -s tests` — 741 OK skipped 1
- `pytest plugins/mission-control/tests -q` — 266 passed
- Binding 3/3; cycle-16 footer = blobs = readback
- Skill-scoped matrix blocked reasons match live `stage_blocked_reason` text
- `git merge-base --is-ancestor origin/main HEAD` — true
- `git diff --check` — clean
- `080b535` still a commit on `orch/mcport-9-resume1-u8-freeze-agy1`

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings: the three disclosed items above; post-merge matrix checker on `main` (orchestrator); U9 closeout.
- Independent gates actually run: listed above. `evaluate_review_readiness` `can_proceed` is true.

## Findings

None.

## Routing

`accepted` — continue. The orchestrator may open the single integration PR (`head` `orch/mcport-9-resume1`, `base` `main`, merge commit, never squash), verify the matrix checker on `main` post-merge, and close #18. No fix requests.
