# Saga Code Review — U3 mission-control synchronization (`u3-sync-q1`)

This review covers the frozen Lane A commit on `orch/mcport-9-resume1-u3-sync-q1` because the portable tree is a derived artifact: byte-copy digest equality, transform identity, and schema-3 rule selection are the custody boundary later lanes consume.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `8226d46aaf3bcf7e28c44761f07b0d2ec53cac2a` (`8226d46`, `feat(sync): schema-3 rule selection and mission-control synchronization (run unit U3)`)
- Named base: `d7d49d8def9e4eb064e0cc9ab501ff0ea7556340`
- Target: 66 files, +21432 / −41
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `8226d46` is accepted under the roster contract.** Every selected lens has a derived overall of at least 9.0 and every applicable dimension is at least 7.0. Sync `--check` reproduces both the mission-control tree at pin `84eaf042` and the UniFi tree at `818fd684`. Independent gates this controller ran at the frozen revision all passed.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent (issue #13 / plan U3): synchronize from the pin with two new single-shape shim rules, `normalize-skill-frontmatter` v1, and schema-3 per-path rule names on both descriptors; leave `resolve-bundled-fleet-module` v1's rewrite identity intact; carry upstream defects verbatim.
- Delivered: that surface. `plugins/unifi/**` package files are untouched. `plugin.json` and package `README.md` are absent (Lane B). No `fleet-bundle.json`.

Child #13's full-suite green is **CHANGED** against the landing model: `unittest discover` is 657 tests, 3 failures, 1 skip — the missing portable manifest (and its two transitive check_repo fences) plus the cycle-14 mutation-proof binding for `scripts/port_config.py`, which this unit's journal assigns to U8 rather than tampering with the digest.

### Plan-completion (U3)

| Item | State | Evidence |
| --- | --- | --- |
| Sync from pin; byte-copy digest = source | DONE | 47 `upstream-byte-copy` entries, sha256 equals upstream blob and disk; 0 mismatches |
| Transforms record rule name, version, source and output digests | DONE | 10 `deterministic-transform` entries; all source_sha256 and output sha256 match |
| `sync --check` green on landed tree | DONE | mission-control `--check` exit 0 at `84eaf042`; UniFi `--check` exit 0 at `818fd684` |
| Exactly-one-match per rule; never first-match | DONE | split/guarded/frontmatter raise on 0 or 2 matches; tests assert "found 0"/"found 2" |
| No unresolved `import fleet_commons_shim` in transformed scripts; shim dropped with reason | DONE | only comment mentions in the two rewritten files; shim file absent; `removed_from_source` records it |
| Seven skills pass `check_skill_frontmatter`; fold under `metadata` | DONE | 0 skill-frontmatter errors; board SKILL.md shows `metadata: / when_to_use:` |
| Schema 3: both descriptors; bare strings and missing rule names refused | DONE | `SCHEMA_VERSION="3"`; `test_port_config` 57/57 including those refusals |
| v1 rule rewrite identity preserved (KTD1) | DONE | UniFi `--check` still green; replacement text of `bundled_module_transform` unchanged |
| Upstream 2.1.0 literals and `/issue` self-alias carried | DONE | all four commands still cite `.../2.1.0/scripts/sdlc_manager.py`; issue.md line 7 |
| Lane B files not authored | DONE | `plugin.json` and `README.md` absent |
| Full suite / `check_repo.py` green | CHANGED / deferred | 2 completeness errors (missing portable manifest); mutation-proof rebind is U8 |

COMPLETION: 10/11 DONE, 1 CHANGED.

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 10.00 | `true` | none |
| `documentation-clarity` | 9.83 | `true` | none |
| `adversarial` | 10.00 | `true` | none |
| `api-contract` | 10.00 | `true` | none |

## What was verified

### Filesystem custody

`PROVENANCE.json` pins `84eaf042`. Classification counts: 47 byte copies, 10 transforms (relocated Claude manifest, two shim-family rewrites, seven frontmatter folds). Disk set equals provenance paths except the generated `PROVENANCE.json` sidecar. Closed-set holes for target-owned `plugin.json`/`README.md`/`fleet-bundle.json` are U5's assigned refresh.

Byte-copy sha256 equals the upstream blob at the pin for every `upstream-byte-copy` path, including client copies under `com.infiquetra.claude/`. Transform `source_sha256` equals the pin blob; output sha256 equals the landed file.

### Transform identity and exactly-one-match

`resolve_transform_rule` reads `custody.entrypoint_rules` and refuses an unknown name or a path with no rule. `TRANSFORM_RULES` registers five names once.

- `resolve-bundled-fleet-module` v1: regex and replacement bytes unchanged vs parent; UniFi `--check` proves rewrite identity.
- `resolve-bundled-fleet-module-split` v1: `executor_profile_lint.py` inserts `_bundled`, `import tier_palette`, and `palette = tier_palette`. Zero or two sites fail.
- `resolve-bundled-fleet-module-guarded` v1: `_load_intent_envelope` keeps function-scope laziness, `import intent_envelope`, `return intent_envelope`. Zero or two blocks fail.
- `normalize-skill-frontmatter` v1: folds one top-level `when_to_use` under `metadata`; second application is a no-op; existing `metadata` beside the key is refused.

No `import fleet_commons_shim` remains in `plugins/mission-control/scripts/`. Comment text still names the dropped shim; that is not an import.

### Verbatim upstream defects

All four command files still contain `~/.claude/plugins/cache/infiquetra-plugins/mission-control/2.1.0/scripts/sdlc_manager.py`. `commands/issue.md:7` still says `/issue` remains a compatibility alias. The agent file still uses a `<version>` cache path as upstream wrote it. None of these were patched.

### Schema 3

Both descriptors are `"schema_version": "3"`. UniFi names `resolve-bundled-fleet-module` on both clients. Mission-control names `-split`, `-guarded`, and `normalize-skill-frontmatter`. `test_port_config` refuses a bare path string as the schema-2 shape and refuses a missing rule name. 57/57 pass.

### Tests and gates at the frozen revision

- `python3 scripts/sync_vendor_source.py --package mission-control ... --check` exit 0
- UniFi `--check` exit 0
- `tests.test_sync_vendor_source` 65 tests, 1 skip (no upstream checkout from that test's search path; this controller ran `--check` against the real checkout)
- `tests.test_port_config` 57/57
- `check_skill_frontmatter` 0 errors
- `git diff --check` exit 0
- `unittest discover -s tests`: 657 ran, 3 failed (missing `plugin.json`; UniFi README's fenced `check_repo.py`; cycle-14 binding for `scripts/port_config.py`), 1 skipped

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - Package-completeness red is the missing portable manifest (Lane B). Entry points now exist, so the error is no longer "not a directory".
  - Cycle-14 portable-copies proof still names the pre-schema-3 digest of `scripts/port_config.py`. The unit recorded that U8 re-runs the proof rather than editing digest lines. Documentation-clarity / runbook-safety-rollback-links-generated-drift is 9 for that unbound evidence file, not a repair.
  - `_bundled/` modules are not on disk until Lane C; import lines already point there.
- Independent gates actually run at `8226d46`: both `--check` commands, digest equality, skill frontmatter, focused test modules, `git diff --check`. `evaluate_review_readiness` can_proceed is true.

## Findings

None.

## Routing

`accepted` — continue to the caller's next independent gate. No fix requests.
