# Saga Code Review — U2 fleet-core slice expansion (`u2-fleetcore-q2`)

This review covers the frozen KTD8 re-dispatch of child [infiquetra/infiquetra-agent-plugins#12](https://github.com/infiquetra/infiquetra-agent-plugins/issues/12) on `orch/mcport-9-resume1-u2-fleetcore-q2` because the portable Fleet Core slice is the importable source the mission-control bundle unit will stamp, and a false version string would be a false derivation claim.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `5a027d07dcaf15d859422b0d80a6f70fdb0098c1` (`5a027d0`, journal commit; port `1f89c20`, tests `674761b`)
- Delta base: `c84e7e2349aa8ee9e05a4321f6c4622fe9d5cad2` (three commits)
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `5a027d0` is accepted.** Digests, transform entry, tests, bundle no-op, and UniFi no-churn hold. Both ownership deviations are correct under the package's own terms. Descriptor-completeness red is the allowed intermediate state.

## Scope and built-versus-planned audit

**Scope Check: CLEAN** (two extra files judged in-scope consequences, not creep)

- Intent (amended #12 / KTD8): three files at pin `3b5faa6c` — `tier_palette.py` and `models.json` byte copies; `intent_envelope.py` as `deterministic-transform` with `resolve-fleet-commons-sibling` v1; deferred inventory and provenance; target-owned tests; no UniFi churn; no repin.
- Delivered: that, plus README truth-up and deferred-inventory test expectation (see judgments).

### Plan-completion

| Item | State | Evidence |
| --- | --- | --- |
| `tier_palette.py` / `models.json` sha256 = pin `3b5faa6c` | DONE | both match; also equal at `84eaf042` |
| `intent_envelope.py` `files` entry: `deterministic-transform`, source_sha256, transform_version 1, result sha256, rule prose | DONE | source_sha256 `5157fa30…` = pin blob; result `c4e9b522…` = disk |
| No `fleet_commons_shim` in the transformed file | DONE | `rg` on `intent_envelope.py` empty |
| Package-wide empty grep | CHANGED | journaled; literal grep hits DEFERRED.md, byte-copy docstrings (see judgment b's sibling) |
| Three DEFERRED rows gone; others remain | DONE | ported heading lists the four files; `tier_resolver` still deferred |
| Target-owned tests pass | DONE | `test_intent_envelope` + `test_tier_palette` + deferred-inventory update: 38 tests OK |
| `bundle_fleet_module.py` no-op; UniFi porcelain empty | DONE | "already up to date"; `git status --porcelain -- plugins/unifi` empty |
| `check_repo.py` green | CHANGED / deferred | one allowed error: mission-control package_root is not a directory |
| Version bump per convention | CHANGED | stays `0.25.2`; correct under the convention (judgment b) |

COMPLETION: 7/9 DONE, 2 CHANGED.

## Judgments

### (a) README.md +67 lines — in-scope consequence

The card's enumerated file list omits `plugins/fleet-core/README.md`. The unit's owned role surface is `plugins/fleet-core/**`. Before this delta the README opened "One module" and tabulated a single ported file. After adding three files that sentence would be false — the same class of front-page falsehood unit U0 exists to stop.

The 67 lines add the three paths to the table, describe the transform and the deferred `tier_resolver` call-time failure, and pluralize "module". That is documenting what this unit shipped, not a second product. `release_surface.package_documentation` already names the README; leaving it stale would disagree with `PROVENANCE.json` and `DEFERRED.md` in the same commit.

**Not overreach.** Same judgment for `tests/test_generate_deferred_inventory.py` (+8 lines): the suite pins the ported-name set, so removing three DEFERRED rows without updating that assertion would fail a test this unit's own DEFERRED.md edit requires.

### (b) No version bump — correct under the convention's own terms

The card said "version bump per package release convention." The convention, in `CHANGELOG.md` lines 7–11 of this same package, is: the version is not an independent number; it tracks the upstream Fleet Core version the bytes derive from; a parallel numbering would imply a second writable source.

Upstream `infiquetra-claude-plugins` released **0.25.3 on 2026-08-24** (`CHANGELOG.md` there; commit `96c4e21b`) changing `retry_backoff.py` (this controller measured 18 insertions / 9 deletions vs pin `3b5faa6c`). This unit must not take that change (repin is a #12 stop condition; UniFi bundles would churn). Naming the portable package `0.25.3` while it still carries 0.25.2 `retry_backoff` bytes would be a **false derivation claim** and a collision with the real upstream release. A local suffix would be the parallel numbering the preamble forbids.

Keeping `plugin.json` at `0.25.2`, updating the description, and recording the expansion under Unreleased matches the python-floor Unreleased precedent (catalog-level change, no ported-byte move). Journaled. **The deviation is correct.**

### Shim-grep scope (related, journaled)

Amended #12's probe `git grep fleet_commons_shim plugins/fleet-core/` expected empty. Literal hits remain in `DEFERRED.md` (the shim must stay named as deferred) and in byte-copied docstrings (`retry_backoff.py`, `tier_palette.py`). Editing those would break recorded digests or the "every other deferral stays explicit" item. The transformed `intent_envelope.py` has zero matches. That is the property that matters. The journal is right; this is not a repair.

## Lens scores

| Lens | Derived overall | Accepted | Failing dimensions |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 10.00 | `true` | none |
| `documentation-clarity` | 10.00 | `true` | none |
| `adversarial` | 10.00 | `true` | none |
| `api-contract` | 10.00 | `true` | none |

## What was verified

- Pin `3b5faa6c` / `source_version` 0.25.2. `tier_palette.py` sha256 `b14ff89f…`, `models.json` sha256 `8b50e821…`, both equal pin and `84eaf042`.
- `intent_envelope.py`: `_load_sibling`, `importlib.util` first stdlib import, `_tier_resolver()` / `_tier_palette()` call `_load_sibling`. No `fleet_commons_shim` token. Deferred call raises `RuntimeError` naming the missing sibling path (tests). Relocated `_bundled`-style copy works (tests).
- `bundle_fleet_module.py`: "already up to date"; UniFi tree clean.
- New tests 38 OK. Full discover: 634 tests, 2 failures — missing `plugins/mission-control` directory and the UniFi README's fenced `check_repo.py`. Allowed intermediate.

## Coverage

- Suppressed findings: 0.
- Residual: CHANGELOG preamble still says "ported module" singular in the version-tracking paragraph; Unreleased text is accurate. Not a trust-boundary defect.
- Independent gates: digest equality, provenance check empty, plugin-manifest check empty, U2 tests, bundle no-op, UniFi no-churn, `git diff --check`. `evaluate_review_readiness` can_proceed is true.

## Findings

None.

## Routing

`accepted` — continue. No fix requests. README documentation and the no-bump are accepted deviations, not repairs.
