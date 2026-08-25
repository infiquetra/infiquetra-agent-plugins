# Saga Code Review — U5 mission-control Fleet Core bundle (`u5-bundle-agy1`)

This review covers the frozen Lane C commit on `orch/mcport-9-resume1-u5-bundle-agy1` because the generated `_bundled/` files are the destination the U3 entrypoint transforms already import, and a stamped Python copy or a stamped JSON copy would be the exact drift class the bundle machinery exists to prevent.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `700a50cf0419e42be627c75a08542c6f703c5a81` (`700a50c`, `feat(mission-control): declare and generate the three-file fleet bundle (run unit U5)`)
- Named base: `57c377e202b36c9ff9fe436510828ceb3d50b02a` (one commit)
- Target: 10 files, +1893 / −40
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `700a50c` is accepted under the roster contract.** Every selected lens has a derived overall of at least 9.0 and every applicable dimension is at least 7.0. `python3 scripts/check_repo.py` is green — the first fully-assembled green gate of the run. UniFi declarations and generated bundles are byte-untouched. The three flagged judgments are accepted deviations, not repairs.

## Scope and built-versus-planned audit

**Scope Check: CLEAN** (`scripts/check_repo.py` judged an in-scope consequence, not creep; see judgment (a))

- Intent (amended child [infiquetra/infiquetra-agent-plugins#15](https://github.com/infiquetra/infiquetra-agent-plugins/issues/15) / Key Technical Decision 8 plus amendment doc-review finding 3): declare `plugins/mission-control/fleet-bundle.json` at schema version 2 with modules `intent_envelope` and `tier_palette` plus a `data` array entry for `models.json`; extend `schemas/fleet-bundle.schema.json` to `enum ["1","2"]` with `if/then` requiring `"2"` whenever `data` is present; generate three `_bundled/` files; copy data files verbatim (no stamp); prove freshness by byte-equality; refresh `PROVENANCE.json` so the closed-set check sees the new target-owned files; leave UniFi at schema version 1.
- Delivered: that surface, plus the `check_repo.py` data-file branch the green gate requires.

The run-plan unit record still describes a two-module bundle with "new moving parts: none". The live card is the amended, decision-complete contract this unit executed. That plan-file lag is **CHANGED** against the repo plan artifact and is not a missing deliverable of this unit.

### Plan-completion (U5)

| Item | State | Evidence |
| --- | --- | --- |
| `fleet-bundle.json` validates at schema version 2 with two modules and `models.json` | DONE | live declaration; `validate_declaration_file` empty; UniFi stays `"1"` |
| Schema `enum ["1","2"]` plus `if/then` requiring `"2"` when `data` is present | DONE | `schemas/fleet-bundle.schema.json`; v1 modules-only still valid; `data` at v1 refused |
| Three generated `_bundled/` files; second generate is a no-op | DONE | `python3 scripts/bundle_fleet_module.py` prints "already up to date"; porcelain empty |
| Python modules stamped; payload bytes equal fleet-core source | DONE | stamps name pin `3b5faa6c` / 0.25.2; payload sha256 `c4e9b522…` and `b14ff89f…` |
| `models.json` verbatim byte copy, no stamp | DONE | sha256 `8b50e821…` equals fleet-core and its `PROVENANCE.json` `files` entry; no stamp token |
| Bundled `intent_envelope.py` is the transformed sibling-resolving file | DONE | `_load_sibling` present; `fleet_commons_shim` absent; source-sha256 is the transformed digest |
| `PROVENANCE.json` closed-set refresh (six target-owned paths) | DONE | README, `plugin.json`, `fleet-bundle.json`, three `_bundled/` files; disk set equals listed set (63/63); `sync --check` green at `84eaf042` |
| Data-file tests (schema + generator + `check_repo` path) | DONE | `tests.test_fleet_bundle_schema` + `tests.test_bundle_fleet_module`: 57/57 |
| `python3 scripts/check_repo.py` green; UniFi untouched | DONE | "Repository validation passed."; UniFi `fleet-bundle.json` sha1 identical to parent; `git status --porcelain -- plugins/unifi` empty |
| Full `unittest discover` green | CHANGED / deferred | 696 ran, 2 failed, 1 skipped — both failures are `MutationProofBindingTest` (judgment (b)) |

COMPLETION: 9/10 DONE, 1 CHANGED.

## Judgments

### (a) `scripts/check_repo.py` — forced in-scope, correct

Child #15's enumerated files list names the declaration, the three generated files, the schema, `scripts/bundle_fleet_module.py`, and the two test modules. It does not name `scripts/check_repo.py`.

The card's acceptance criteria still require `python3 scripts/check_repo.py` green with no missing, stale, or hand-edited bundle. `check_bundled_files` is the repository gate that walks every `_bundled/` file. Before this delta, an unstamped file failed as `unstamped generated bundle`. A valid F3 data copy is unstamped JSON by decision. Without the new branch (`stamp_lines is None` and suffix not `.py`, then byte-equality against `plugins/fleet-core/scripts/fleet_commons/<basename>`), the gate cannot go green for a correct bundle.

The +23-line edit is the minimum teaching of that class. Tests drive `check_bundled_files` for generate-then-pass, seeded stale source, and seeded hand-edit. The commit message names the file. Same class as the U2 README: the card's file list omitted a file the unit's own green gate required.

**Not overreach. Correct.**

### (b) Named mutation-proof debt assigned to U6 — sound

`tests/test_site_profile.py` `MutationProofBindingTest` binds five graded files to the cycle-14 proof. The test is designed to fail when a graded file's committed bytes are not the bytes the proof exercised. This controller measured the suite at the frozen revision: 696 tests, exactly two failures, both that test:

- `scripts/check_repo.py`: cycle-14 digest `ef37a18a…` equals the parent (`57c377e`) blob; frozen blob is `6cf74eb9…`. This unit's edit.
- `scripts/port_config.py`: cycle-14 digest `60149faa…` is the pre-U3 blob; frozen and parent are both `bfaeb492…`. U3 leftover. This unit did not touch `port_config.py`.

Regenerating the proof is test custody (U6). Editing the digest lines without re-running the proof is tampering — the defect class the binding test exists to catch. U5 cannot turn the suite fully green without also re-proving `port_config.py`, which it did not change. The landing model already says the assembled branch is fully green from U6 onward; intermediate red is allowed only for named completeness or assigned debt. Plan amendment assigns cycle-15 to U6.

U3's review accepted the same class of deferred rebind. **Accepting U5 with that named, assigned debt is sound. The proof re-run does not belong to U5.**

### (c) Coordinator-prompted commit — integrity holds

The frozen object is one commit, parent exactly `57c377e`, author and committer both `Jeffrey Cox <namredips@gmail.com>` with identical timestamps, no `Co-authored-by` or generator trailer. The message is a conventional `feat(mission-control)` body that discloses `check_repo.py`. The tree is exactly the 10-file delta; `git diff --check` is clean.

This repository records unit commits under the operator's git identity. The coordinator's claim, which this review can check against the object and not against the Antigravity session transcript, is that the unit authored the content and was prompted only to commit work it had already finished. Nothing in the object indicates a second author or a content splice. **Commit integrity holds.**

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 9.71 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 9.80 | `true` | none |
| `documentation-clarity` | 9.67 | `true` | none |
| `adversarial` | 9.80 | `true` | none |
| `api-contract` | 9.75 | `true` | none |

Architecture is 9.71 because data-file freshness is implemented twice (`check_copy` uses the declaration name; `check_bundled_files` uses the destination basename) and the F3 decisions live on the card rather than a same-commit journal entry. Testing is 9.80 because custom destination basenames for data files are untested. Documentation and api-contract are below 10 because the schema `description` still says the declaration is of modules only. None of those are trust-boundary defects.

## What was verified

### Filesystem custody

`plugins/mission-control/fleet-bundle.json` is schema version `"2"`. Modules: `intent_envelope`, `tier_palette`. Data: `models.json` → `scripts/_bundled/models.json`. UniFi `plugins/unifi/fleet-bundle.json` remains schema version `"1"` and is byte-identical to parent `57c377e` (sha1 `ac1537dc…` both sides). `git diff 57c377e HEAD -- plugins/unifi` is empty.

Generated Python payloads equal the fleet-core sources this run already reviewed in U2:

- `intent_envelope.py` payload sha256 `c4e9b522c73e23a875ae85baa5e45687f4bfaae84fa3ead11af1d4c730d50b98` (transformed file; `_load_sibling` present; no `fleet_commons_shim` token)
- `tier_palette.py` payload sha256 `b14ff89f155c0043e72bf028b937bdb6e3e7b4ebbfbf919683d88a8764ef9e28`
- `models.json` sha256 `8b50e821e12d56d555e2c2f087df2f568fda48c20987840d2d5a3bfa7a362f83` (equals fleet-core and the fleet-core provenance `files` entry)

Stamps name `source-version: 0.25.2` and `source-commit: 3b5faa6c…`. `models.json` contains no generated-bundle stamp token.

`PROVENANCE.json` pin remains `84eaf042`. Six new `target-owned` entries: `README.md`, `plugin.json`, `fleet-bundle.json`, `scripts/_bundled/intent_envelope.py`, `scripts/_bundled/tier_palette.py`, `scripts/_bundled/models.json`. On-disk package files excluding the sidecar equal the listed set, 63/63.

### Schema and generator

`schema_version` is `enum ["1","2"]`. Optional `data` array: `additionalProperties: false`, name pattern `^[A-Za-z_][A-Za-z0-9_]*\.[a-z0-9]+$`, destinations default `scripts/_bundled/<name>`. `if`/`then` requires `schema_version` const `"2"` when `data` is present. The subset validator grew `enum` and `if/then/else` in the same commit.

`PlannedCopy.is_data` selects `write_bytes_if_changed` (verbatim) versus `render_bundle` (stamped Python). Data destinations go through `_safe_relative`. Absent data files fail before write. Duplicate destinations are refused across modules and data together.

Without a stamp, stale source and hand-edit are the same byte inequality. Tests assert the data-file hand-edit reports `stale source`, not `tampering`. That is the F3 decision, not a silent-green.

### Tests and gates at the frozen revision

Worktree at `700a50c`:

- `python3 scripts/check_repo.py` — "Repository validation passed."
- `python3 scripts/bundle_fleet_module.py` — "already up to date."; porcelain empty afterwards
- `python3 scripts/sync_vendor_source.py --package mission-control --source <upstream> --commit 84eaf042 --check` — exit 0
- UniFi `--check` at `818fd684` — exit 0
- `python3 -m unittest tests.test_fleet_bundle_schema tests.test_bundle_fleet_module` — 57/57
- `python3 -m unittest discover -s tests` — 696 ran, 2 failed, 1 skipped (the skip is the existing unreachable upstream checkout)
- `git diff --check` — clean
- `git status --porcelain -- plugins/unifi` — empty

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - `check_bundled_files` resolves a data file's source as `fleet_commons/<destination-basename>`. `check_copy` / `check_fleet_bundle_outputs` use the declaration `name`. Live destinations match names, so both paths agree. A custom destination that changes the basename fail-closes on the declaration-aware path; a coincidental match against a different fleet-core file of the same basename is untested.
  - Schema prose `description` still says the declaration is of modules only.
  - `check_bundled_files` UTF-8-decodes before the data-file byte compare; a non-UTF-8 data file would fail-closed as unreadable. `models.json` is UTF-8.
  - Repo plan unit record still describes the pre-amendment two-module U5; the live card is the contract.
- Independent gates actually run at `700a50c`: `check_repo`, bundle no-op, both `sync --check` commands, focused bundle tests, UniFi no-churn, `git diff --check`. `evaluate_review_readiness` `can_proceed` is true. The two MutationProofBindingTest failures are named U6 debt, not a failed independent gate.

## Findings

None.

## Routing

`accepted` — continue to the caller's next independent gate. No fix requests. The `check_repo.py` edit, the U6 mutation-proof assignment, and the coordinator-prompted commit are accepted judgments, not repairs.
