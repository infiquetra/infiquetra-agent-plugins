# Post-repair scored code review — UniFi portability pilot, cycle 2

Reviewer: opencode / muse-spark-1.2 (independent, unattended)
Scope: `git diff 95de0d5..b4418a1` — branch `orch/orch-2026-08-22-unifi-repairs` — plan `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md`
Outcome: repairs_requested — 7 of 10 consensus findings fully closed, 1 partial, 1 queued residual, 1 not fixed (Retry-After). New defects: none P0, one P2, one P3; no covert scope creep; 373 tests pass, both entrypoints exit 0, both validators pass.

## Scope check

Scope Check: DRIFT DETECTED (factual drift in evidence, no creep — and a correct supersession)

Intent: Land five repair units against the 10-finding consensus on commit 95de0d5 (four validator/runtime closures plus the release evidence re-run), without client-specific remediation, without editing immutable review reports, and with each validator change needing to be demonstrably biting.

Delivered: Seven findings fully closed (C1-C4, C8-C10), one partial with a documented residual (C6 — repo gate closed, runtime `validate_profile` still name-only), one doc now target-owned but with a queued sync-table conflict (C5 — `PROVENANCE.json` is `target-owned` at `plugins/unifi/PROVENANCE.json:32` yet `scripts/sync_vendor_source.py:80` still lists `README.md` in `PORTABLE_BYTE_COPIES`), and one untouched (C7 — `int(Retry-After)` on HTTP-date still raises `ValueError` at `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176`). The factual drift the previous cycle flagged (matrix 21 vs tree 23) is now correctly handled by retirement, not by overwriting: `docs/evidence/2026-08-22-unifi-compatibility-matrix-pre-repair.md:1-3` carries `matrix-status: superseded` with `superseded-by` and `superseded-reason`, and `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` is `matrix-status: current` at `6e6b57c1…8415`. No unrelated scope creep.

## Lens selection

Always-on (4): architecture-maintainability, correctness, security, testing.

Conditional selected (4):

- deployment-infrastructure — diff adds provenance closed-set, bundle presence checks, matrix fingerprint binding, and post-activation readback evidence.
- reliability — drift's `missing-policy` fix changes failure-reporting semantics; Retry-After date form remains on the failure path.
- api-contract — site-profile contract resolution, compatibility matrix closed schema, CLI read-only guarantees and entrypoint imports.
- adversarial — 22-file, 4700-line change with load-bearing validators, arbitrary-delete containment, and claimed guarantees that must be refuted.

Not selected: performance (no latency/throughput target in plan; retry timing is covered under reliability). 8 lenses attempted.

## Repair verdict — every consensus finding C1..C10 verified from the current source

| # | Consensus issue | Prior | Verdict on b4418a1 | What was checked |
|---|---|---|---|---|
| C1 | Matrix describes pre-repair package, not shipped tree | P1 | FIXED | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:357-361` now `file_count 23` `tree_sha256 6e6b57c1…8415` matches `python3 scripts/check_compatibility_matrix.py --print-fingerprint`; pre-repair doc retired at `docs/evidence/2026-08-22-unifi-compatibility-matrix-pre-repair.md:1-3` with `matrix-status: superseded`; `scripts/check_compatibility_matrix.py:346-412` recomputes fingerprint (sorted per-file sha256 + relative path) and fails on mismatch; `matrix-status` defaults to `current` so the binding is fail-closed; `python3 scripts/check_compatibility_matrix.py` passes on both current and superseded docs. |
| C2 | Drift reports every profiled network as missing | P1 | FIXED | `plugins/unifi/scripts/discover.py:147-156` now declares `POLICY_OBSERVATION_KEY`/`POLICY_OBSERVED`/`POLICY_UNAVAILABLE` and `empty_inventory`/`DiscoverySession.collect` set `policy_observation=unavailable` when nothing was ever looked at; `plugins/unifi/scripts/drift.py:96-114` `policy_observation()` requires affirmative `observed` or populated identifiers and `drift.report:172` only emits `missing-policy` on `observation == observed`; `limits` carries `POLICY_UNOBSERVED_LIMIT` otherwise; `tests/test_drift.py:237-326` proves live-discovery inventories emit no `missing-policy` while `tests/test_drift.py:284-306` proves observed-but-empty still does. |
| C3 | Provenance validation is not closed over package files | P1 | FIXED | `scripts/check_repo.py:375-423` `_closed_set_errors` now compares manifest set vs ` _managed_package_files` both ways and rejects `duplicate provenance entry for …` and `unlisted package file: … is not classified by …`; unsafe `..` / absolute paths are reported and not counted as classifications; `tests/test_check_repo.py:321-449` proves unlisted, deleted-entry, duplicate, and unsafe-satisfies-closed-set cases. |
| C4 | Bundle provenance fields optional, so a stale bundle can pass CI | P1 | FIXED | `scripts/check_repo.py:101-113` `BUNDLE_REQUIRED_STAMP_FIELDS` now requires all six (`generated-by`, `source-version`, `source-commit`, `source-path`, `source-sha256`, `output-sha256`); `scripts/check_repo.py:536-553` reports `generated bundle stamp missing <field>` per omitted field; `tests/test_check_repo.py:500-544` proves single-field omission and the reviewed scenario (`source-path`+`source-sha256` deleted) both fail; `scripts/check_repo.py:629-660` `check_fleet_bundle_outputs` now rejects a declared module with no generated bundle via `presence_errors`; `python3 scripts/bundle_fleet_module.py --check` and `check_repo.py` both pass on the live tree. |
| C5 | Portable README is Claude-specific / references missing docs | P2 | FIXED for the shipped artifact, QUEUED residual for next sync | `plugins/unifi/README.md:1` lede is now `UniFi portable package` with Agent Plugins 1.0 layout, `com.infiquetra.claude/` adapter section, Fleet Core bundle section, site-profile contract and runnable `python3` fences; `plugins/unifi/PROVENANCE.json:30-33` is `target-owned`; `tests/test_unifi_readme.py` proves lede, absent-test-module refs, link resolution, and fence runnability. Residual: `scripts/sync_vendor_source.py:80` still lists `README.md` in `PORTABLE_BYTE_COPIES`; the next `synchronize()` would overwrite the portable README with upstream bytes and is caught only by `test_unifi_readme.py`; documented at `docs/engineering-journal/QUEUED.md:100-125` and `docs/engineering-journal/DECISIONS.md:14-44`. |
| C6 | Secret-free / redaction validation is partial | P2 | PARTIAL — repo gate closed, runtime not | Repo gate: `scripts/check_repo.py:785-817` `check_secret_free_values` now scans `plugins/` with two families (literal formats in every text file plus credential-key assignment with entropy >=2.5 in data/doc files), is run from `check_repo:821` main, and `tests/test_check_repo.py:679-792` proves `notes: password=hunter2` and Bearer/file-formats and that `api_key = (api_key or "").strip()` handling code does NOT fire. Runtime: `plugins/unifi/scripts/site_profile.py:91-105` `CREDENTIAL_NAME_FRAGMENTS` and `311-328` `_credential_field` still inspect mapping keys only; `validate_profile` at `site_profile.py:375-388` checks no credential-shaped field *name* while `nonEmptyText` in `plugins/unifi/schemas/site-profile.schema.json:66` accepts any non-empty string value; `python3 -c` with `notes: password=hunter2` still `ACCEPTS`. The decision at `docs/engineering-journal/DECISIONS.md:257-332` scopes the fix to the repo gate and names the site-profile runtime residual explicitly; the operator guarantee must be worded accordingly. |
| C7 | `Retry-After` HTTP-date form not handled | P2 | NOT FIXED | No diff since 95de0d5 touches `Retry-After`: `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176` and `plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py:176` still `int(resp.headers.get("Retry-After", 60))`. On HTTP-date (RFC 7231 — valid), `int()` raises `ValueError` inside `_do_request`; `retry_backoff.py:91` catches `Exception`, sees `ValueError` has no `status_code==429`, so `not retryable` propagates immediately; outer `except _RateLimited` at `unifi_network_client.py:186` does not catch it, and `except Exception as e` at `:242` emits `Unexpected error: …` not `Rate limited`. Primitive `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` never had date parsing; `tests/test_retry_backoff.py` still has no date case. Both Cursor F-09 (75) and OpenCode F-09 (50) descriptions remain accurate. |
| C8 | Malicious/corrupt `PROVENANCE.json` can unlink outside the package | P1 | FIXED | `scripts/sync_vendor_source.py:521-599` now validates every `path` from a previous manifest at the operation that deletes: `_managed_path_violation` (lexical absolute/`..` check plus `resolve()`+`is_relative_to` containment) and `resolve_managed_path` as the single chokepoint; `previously_managed:571-599` calls it for every sync-managed entry and raises `SyncError` before any write/delete; `apply_plan:674-704` reads and validates the stale set before writing a byte; `tests/test_sync_vendor_source.py` proves absolute, `..`, and symlink-escape deletions are refused. |
| C9 | Post-activation proof was never performed | P1 | FIXED (evidence + verification) | `docs/evidence/2026-08-22-unifi-post-activation-readback.md` now exists with installed-version/digest readback against the activated upstream commit `0eb1fe04` and isolated fresh-session proofs for Grok/Agy/Muse; `tests/test_check_compatibility_matrix.py` also covers the new doc. `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` invocation evidence now records re-run help output (29/21 lines) not shim failure. |
| C10 | Discovery persistence deny-list fails open without a `.git` directory | P2 | FIXED | `plugins/unifi/scripts/discover.py:281-343` now refuses (a) any path inside `PACKAGE_ROOT` unconditionally, and (b) any path inside the resolved working tree, and when `repository_root_from()` returns `None` raises `DiscoveryPersistenceError` naming `--repository-root` rather than returning the path; `tests/test_discover.py:278-361` proves in-package refusal without a checkout, undeterminable-tree refusal, whole-chain `discover()` refusal, and `--repository-root` lift. |

## Findings summary (by severity) — cycle 2 only

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176` | HTTP-date `Retry-After` still disables retries; valid date header raises `ValueError` and surfaces as `Unexpected error` | reliability, api-contract | 100 | `gated_auto -> review-fixer` |
| F-02 | `plugins/unifi/scripts/site_profile.py:311` | `validate_profile` still checks credential-shaped field *names* only; a secret in an allowed free-text *value* (e.g. `notes: "password=hunter2"`) validates | security | 100 | `manual -> human` |
| F-03 | `scripts/sync_vendor_source.py:80` | `PORTABLE_BYTE_COPIES` still lists `README.md` as an upstream byte copy; the next authorized `synchronize()` would overwrite the now-target-owned portable README | architecture-maintainability | 75 | `safe_auto -> review-fixer` |
| F-04 | `plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py:176` | Same `Retry-After` defect in the second client (mirror of F-01) — kept as same fingerprint group, not double-counted for scoring | reliability | 100 | `gated_auto -> review-fixer` |


### F-01 — HTTP-date `Retry-After` disables retries (P2, carry from C7, NOT FIXED)

- severity: P2
- lens_id / category: reliability
- dimension_id: timeouts-retries-circuit-breakers-idempotency
- critical: true
- file: plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py
- line: 176
- why_it_matters: A controller returning the RFC-valid HTTP-date form of `Retry-After` causes one request, no backoff retry, and `Unexpected error: invalid literal for int()` instead of the documented `Rate limited` error, breaking the only shared rate-limit contract in the pilot (`retry_backoff` / issue #348).
- autofix_class: gated_auto
- owner: review-fixer
- requires_verification: true
- confidence: 100
- pre_existing: false
- evidence:
  - `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:173-176` `raise _RateLimited(int(resp.headers.get("Retry-After", 60)))` — identical at `plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py:176`.
  - `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:91-102` retry predicate is `status_code==429`; `ValueError` from `int()` has no `status_code`, so it propagates immediately and never reaches the `except _RateLimited` at `unifi_network_client.py:186`.
  - `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:242-244` `except Exception as e: self._error(f"Unexpected error: {str(e)}")` is where the date header surfaces.
  - `git diff 95de0d5..b4418a1 -- plugins/unifi/skills/ plugins/fleet-core/scripts/` contains zero `Retry-After` or `parsedate` hunks.
  - `tests/test_retry_backoff.py:1-238` covers `int` clamp and `0`/negative-hint fallback but has no HTTP-date case; `tests/test_client_entrypoints.py` runs `--help` only, never a 429.
- suggested_fix: Parse both delta-seconds and HTTP-date. Try `int()` first; on failure parse an HTTP-date with `email.utils.parsedate_to_datetime`, compute `max(0, date - now)` against an injected clock (reuse the primitive's clock seam), clamp to `max_delay`, and fall back to computed backoff for unparsable values. Add response-level tests for missing, numeric, date, expired-date, and malformed values in both clients. Assumption: UniFi can emit either form; supporting both is the RFC path.

Validator: {"validated": true, "reason": "Both clients still parse Retry-After with int() and an RFC-valid HTTP-date causes ValueError then Unexpected error, with no alternate handler or test; no diff in 95de0d5..b4418a1 touches the header."}

### F-02 — `validate_profile` checks names, not values (P2, carry from C6, PARTIAL FIX)

- severity: P2
- lens_id / category: security
- dimension_id: secrets-cryptography-session-handling
- critical: true
- file: plugins/unifi/scripts/site_profile.py
- line: 311
- why_it_matters: The repository gate now rejects a credential *value* committed into `plugins/`, but an operator pasting a real API key or password into an allowed `notes`/`description`/`ownership` value at runtime still loads successfully; the false assurance ("validation excludes credentials") travels with the profile to wherever it is backed up.
- autofix_class: manual
- owner: human
- requires_verification: true
- confidence: 100
- pre_existing: false
- evidence:
  - `plugins/unifi/scripts/site_profile.py:4-8` claims credentials excluded by validation.
  - `plugins/unifi/scripts/site_profile.py:91-105` `CREDENTIAL_NAME_FRAGMENTS` and `311-328` `_credential_field` walk mapping keys only, never string values.
  - `plugins/unifi/schemas/site-profile.schema.json:66` `nonEmptyText` accepts every non-empty string; `propertyNames` guards names, not values.
  - `tests/test_site_profile.py:198-215` tests credential-shaped property *names* only; live `validate_profile({"notes": "password=hunter2"})` still returns successfully (reproduced at `python3 -c` in this review, ACCEPTS).
  - `scripts/check_repo.py:785-817` `check_secret_free_values` is real but scoped to committed `plugins/` files and not to `validate_profile`'s runtime path; `docs/engineering-journal/DECISIONS.md:331` explicitly scopes the repair to "the repository gate only".
- suggested_fix: Decide the product guarantee. Either (a) keep name-only enforcement at runtime and narrow public wording to "credential-shaped *fields* are rejected; operators must never put secrets in values" while keeping `check_secret_free_values` as defense-in-depth for committed files, or (b) add value-level secret detection to `validate_profile` (two families already proven in `check_repo.py`) with placeholder/reference allowances. Assumption: (a) is the operator's current decision; record whether (b) is deferred.

Validator: {"validated": true, "reason": "Repository gate now checks values but runtime validate_profile still only walks keys, so password in an allowed notes value loads, as DECISIONS itself documents as the residual."}


### F-03 — `README.md` stays in the byte-copy table (P3, carry from C5, QUEUED residual)

- severity: P3
- lens_id / category: architecture-maintainability
- dimension_id: architectural-fit-ownership-single-sources
- critical: false
- file: scripts/sync_vendor_source.py
- line: 80
- why_it_matters: The shipped README is now `target-owned` at `plugins/unifi/PROVENANCE.json:32` and `tests/test_unifi_readme.py` guards it, but the tuple that drives `synchronize()` still lists it as an upstream byte copy; the next authorized resync would restore the Claude lede the repair just removed, fighting its own guard test.
- autofix_class: safe_auto
- owner: review-fixer
- requires_verification: true
- confidence: 75
- pre_existing: false
- evidence:
  - `scripts/sync_vendor_source.py:80` `PORTABLE_BYTE_COPIES = ("README.md", …)`.
  - `plugins/unifi/PROVENANCE.json:32` `{"path":"README.md","classification":"target-owned"}`.
  - `docs/engineering-journal/DECISIONS.md:22-44` "Dropping the path from the sync table is queued rather than taken here, because that tuple lives in a file this unit does not own" and `docs/engineering-journal/QUEUED.md:100-125`.
  - `tests/test_unifi_readme.py` fails closed on the lede identity if a resync restored the upstream bytes.
- suggested_fix: Before the next `synchronize()`, remove `README.md` from `PORTABLE_BYTE_COPIES` and update `tests/test_sync_vendor_source.py` fixture expectations; `target_owned_paths()` already records the rewritten file without being taught about it. Assumption: no other unit touches the custody table concurrently (this was the R1 constraint).

Validator: {"validated": true, "reason": "PROVENANCE says target-owned while the sync table still lists README.md as a byte copy, so the next sync would overwrite the portable docs; the repo documents this as a deliberate queued divergence."}

## What the repairs did NOT re-introduce (refutation attempts)

Every new validator fence was probed until it failed for the right reason:

- **C3 closed-set**: adding `plugins/unifi/scripts/extra.py` fails `unlisted package file: plugins/unifi/scripts/extra.py is not classified by plugins/unifi/PROVENANCE.json` at `scripts/check_repo.py:417`; removing a managed entry while leaving the file fails identically; a duplicate `path` in the manifest fails `duplicate provenance entry for …` at `scripts/check_repo.py:412` (`tests/test_check_repo.py:321-449`).
- **C4 bundle stamps**: `scripts/check_repo.py:550` now reports `generated bundle stamp missing <field>` per omitted field; deleting `source-path`+`source-sha256` emits two such lines (`tests/test_check_repo.py:519-544`); a hand-edited body fails `stale bundle: … (stamp …, content …)` at `scripts/check_repo.py:556`; a stale Fleet Core source fails `stale source: retry_backoff in …` at `scripts/check_repo.py:602`. The two digest domains remain independent and correctly separable.
- **C8 path containment**: `scripts/sync_vendor_source.py:545-549` lexically rejects absolute/`..` and then `resolve()`+`is_relative_to` rejects a `skills/escape/victim.txt` reached through a symlink inside the package — verified by `tests/test_sync_vendor_source.py`.
- **C10 persistence**: `plugins/unifi/scripts/discover.py:281-343` refuses inside `PACKAGE_ROOT` with no checkout required, and when `repository_root_from()` returns `None` raises `refusing to write discovery output: no repository working tree … Name the tree to protect with --repository-root`; `tests/test_discover.py:278-361` exercises all three branches including `repository_root` override lifting the undeterminable refusal.
- **C1 fingerprint binding**: `scripts/check_compatibility_matrix.py:305-412` recomputes `file_count` and `tree_sha256` over sorted `sha256(bytes) + "  " + posix_path` lines. Verified: `--print-fingerprint` is read-only (no `--update` flag exists by design at `scripts/check_compatibility_matrix.py:863`), `matrix-status` defaults to `current` (fail-closed at `scripts/check_compatibility_matrix.py:428`), and `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:361` `23`/`6e6b57c1…8415` matches the live tree while the superseded doc at `docs/evidence/2026-08-22-unifi-compatibility-matrix-pre-repair.md:1-3` carries `superseded-by`/`superseded-reason`. A superseded doc whose fingerprint still matches the live tree is deliberately rejected at `scripts/check_compatibility_matrix.py:485` so supersession cannot switch the binding off for the live matrix.
- **No covert bypass via checkout noise**: `_bundled/__pycache__` and `.pyc` are excluded from both the fingerprint (`scripts/check_compatibility_matrix.py:101-105`) and provenance closed-set (`scripts/check_repo.py:77-78`), so a malicious `.pyc` in `_bundled/__pycache__` would not survive as provenance-hidden payload; `.gitignore` already blocks committing it, and the bundle presence check at `scripts/check_repo.py:629-660` would still require the declared `.py` bundle to be present.

## New-issue hunt — guarantees that exist but do not bite (pattern of cycle 1)

The previous cycle converged on "a gate that passes when it should fail". Hunted anew:

- **No new validator-that-cannot-fail was found.** The three gates that previously passed when they should fail now all have `fail` paths seeded and proven. The other gates (`check_required_paths`, `check_markdown_links`, `check_skill_frontmatter`, `check_fleet_bundle_declarations`) already had failing tests and still do.
- **No name-vs-value mirage beyond F-02.** `scripts/check_compatibility_matrix.py:216-280` now checks both `CREDENTIAL_ASSIGNMENT` and inert-domain heuristics (with `REDACTED_VALUES` and `FILENAME_SUFFIXES`); `scripts/check_repo.py:131-165` now has two families (literal formats everywhere + assignment+entropy in data/doc). The last remaining name-only surface is F-02.
- **No never-invoked guard.** The C8 guard lives in the deleting operation (`resolve_managed_path`), not in a different command's validator. The C10 guard lives on `PACKAGE_ROOT` first (needs no checkout) and only then on the working tree walk, with the fail-closed branch proven.
- **Two narrow advisory residuals noted but not routed:**
  - Credential value `password=secret` (6 chars, 2.25 bits/char) passes `check_secret_free_values` by design (`CREDENTIAL_VALUE_MIN_ENTROPY 2.5` at `scripts/check_repo.py:190`); documented at `docs/engineering-journal/DECISIONS.md:306-319` as defense-in-depth, not proof of absence. Low-entropy short secrets in free-text values remain outside any guarantee.
  - Fingerprint and provenance both exclude `__pycache__`/`*.pyc`. A committed `__pycache__` entry would not trigger either binding; the repo relies on `.gitignore` for that path (`docs/engineering-journal/LEARNINGS.md` indirectly, plus `check_repo.py:27` notes on interpreter artifacts). Worth keeping the ignore tight but not a finding.

## Built-vs-planned completion audit

Verification modes are DIFF, CROSS-REPO, and EXTERNAL-STATE. 45 numbered requirements classified below against `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:22-144`.

### Implementation and packaging

- **R1 — DONE (DIFF):** `scripts/sync_vendor_source.py:544-609` per-file SHA-256 provenance with `PROVENANCE.json:1-10` pinning `0eb1fe04`.
- **R2 — DONE (DIFF):** `scripts/check_repo.py:260-423` hermetic provenance recompute plus closed-set both-directions and `python3 scripts/check_repo.py` passes.
- **R3 — DONE (CROSS-REPO):** `plugins/unifi/PROVENANCE.json:2-6` pins corrected `0eb1fe04`.
- **R4 — DONE (DIFF):** `scripts/check_repo.py:375-423` every path exactly one classification, duplicate and both list↔tree directions proven.
- **R5 — DONE (CROSS-REPO/DIFF):** six Protect resources present in package; upstream `0eb1fe04` repair assumed (not live-checked here) — evidence is byte-copy shas in `PROVENANCE.json`.
- **R6 — DONE (DIFF):** corrected Network paths present in `plugins/unifi/skills/unifi-network/references/udm-api-endpoints.md`.
- **R7 — DONE (DIFF):** network `wlans`/`vpn`/`adopt`/`forget`/`backup`/`stats dpi` present in `plugins/unifi/skills/unifi-network/SKILL.md`.
- **R8 — DONE (DIFF):** `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:118-101` host required; no default encoded in portable package.
- **R9 — DONE (CROSS-REPO):** deployment receipt in `home-lab@653ab97a` preceded upstream activation; post-activation gap is now R40/R41.
- **R10 — DONE (DIFF):** `plugins/unifi/scripts/site_profile.py:193-630` optional profile, discovery-only mode with explicit `UNKNOWN` sentinel.
- **R11 — DONE (DIFF):** `plugins/unifi/scripts/site_profile_setup.py:71-111` exactly three paths; `tests/test_site_profile_setup.py` counts them.
- **R12 — DONE (DIFF):** remembered path at `${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/config.json` with env override at `site_profile.py:245-305`.
- **R13 — DONE (DIFF):** no-profile loads, `drift.py:146-156` reports `limits` and zero findings; `tests/test_drift.py:127-149`.
- **R14 — PARTIAL (DIFF):** raw inventory not committed and persistence is default-deny (`discover.py:281-343`), but absolute site-PII exclusion still rests on field-name guard at runtime (F-02). Repo-level `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:55` and `scripts/check_compatibility_matrix.py:740-780` enforce redaction for public evidence, and `scripts/check_repo.py:785-817` is the new repo-level value check.
- **R15 — DONE (DIFF):** `plugins/unifi/references/site-profile.md:140-149` private arrangement as optional example.
- **R16 — DONE (DIFF):** `plugins/fleet-core/plugin.json` + `DEFERRED.md` + `PROVENANCE.json` with version `0.25.0`.
- **R17 — DONE (DIFF):** only `retry_backoff` ported; `DEFERRED.md` enumerates remainder.
- **R18 — DONE (DIFF):** `plugins/unifi/fleet-bundle.json` declares two destinations, both present at `skills/*/scripts/_bundled/retry_backoff.py`.
- **R19 — DONE (DIFF):**Bundles stamped and body tampering rejected (`scripts/check_repo.py:523-561`), and `BUNDLE_REQUIRED_STAMP_FIELDS` now fail-closed (`scripts/check_repo.py:101-113`); `python3 scripts/bundle_fleet_module.py --check` passes.
- **R20 — DONE (DIFF):** `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:286` `sys.path.insert(…/_bundled)` + `import retry_backoff` with no `FLEET_COMMONS_ROOT`.
- **R21 — DONE (DIFF):** closed `fleet-bundle.json` supports extensible list; `tests/test_fleet_bundle_schema.py` covers two-module planning.
- **R28 — DONE (DIFF):** `plugins/unifi/plugin.json` canonical `$schema` + `name`; Claude files under `com.infiquetra.claude/`.
- **R29 — DONE (DIFF):** `SKILL.md` six-field frontmatter and name==dir at `scripts/check_repo.py:694-732`.
- **R32 — DONE (DIFF):** `plugins/fleet-core/PROVENANCE.json:3` 0.25.0 slice, custody not moved.
- **R33 — DONE (DIFF):** fleet-core `plugin.json`/`PROVENANCE.json`/`CHANGELOG.md`/module/test all present.
- **R34 — DONE (DIFF):** build declaration is `fleet-bundle.json` with closed `schemas/fleet-bundle.schema.json`, not an invented manifest field.
- **R35 — DONE (DIFF):** two digest domains proven independent at `scripts/check_repo.py:523-561` vs `564-605`; digests never computed over bytes that contain the stamp (`split_bundle_stamp` at `scripts/check_repo.py:466-487`).
- **R36 — DONE (DIFF):** `site_profile.py:193` JSON stdlib only.
- **R37 — DONE (DIFF):** `site_profile_setup.py:125` presents exactly three paths.
- **R38 — DONE (DIFF):** `plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py` present.
- **R39 — DONE (DIFF):** `discover.py:443-531` proposal has unknown intent; `tests/test_discover.py:438-463` asserts field-by-field.

### Compatibility and safety

- **R22 — DONE (DIFF):** `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:352-650` ten clients, forty stage results, each bounded; `--print-fingerprint` recompute passes.
- **R23 — DONE (DIFF):** each client exactly one of four statuses with concrete `reason`/`evidence` (`scripts/check_compatibility_matrix.py:610-653` closed schema check).
- **R24 — DONE (DIFF):** `failed`/`unsupported` accepted outcomes (`check_coverage` at `scripts/check_compatibility_matrix.py:610`); `failed` Cursor Agent present.
- **R25 — DONE (DIFF):** `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:655-668` pause and per-client decisions, no auto-remediation.
- **R26 — DONE (DIFF):** `plugins/unifi/scripts/discover.py:443` read-only catalog (all GET) and `discover.py:512` never passes `--confirm`; safety gate at `scripts/check_compatibility_matrix.py:691-710`.
- **R27 — DONE (DIFF):** default-deny persistence at `discover.py:281-343` + drift's `persist_payload` route; no raw controller `data` in public record (`check_compatibility_matrix.py:740-780` rejects address/MAC/hostname/credential).
- **R43 — DONE (DIFF):** `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:352` now `file_count 23` `tree_sha256 6e6b57c1…` bound to live `plugins/unifi/`; `scripts/check_compatibility_matrix.py:346-412` binding is live and supersession is explicit.
- **R44 — DONE (DIFF):** field names/counts/digests with redacted commands; `rg` for `10.`/`192.168`/hostname came up empty outside `controller.example` placeholders; validator at `scripts/check_compatibility_matrix.py:740-780`.

### Cross-repository process and release

- **R30 — UNVERIFIABLE (EXTERNAL-STATE):** commit history (5 merged repair branches onto `772af43`) shows sequential unit merges with no evidence of nested orchestration, but `Orchestrate` backend topology is not observable from the diff.
- **R31 — DONE (CROSS-REPO):** named target/upstream/home-lab commits exist in receipts under `scratchpad/receipt-run-*.json`.
- **R40 — DONE (DIFF/CROSS-REPO):** upstream tri-lock present at `plugins/unifi/PROVENANCE.json: source_version 2.0.0` and `docs/evidence/2026-08-22-unifi-post-activation-readback.md` now provides installed-version and digest readback from fresh client-owned installs (`python3 scripts/check_compatibility_matrix.py --print-fingerprint` is how the digest was recomputed from installed bytes).
- **R41 — DONE (DIFF):** `docs/evidence/2026-08-22-unifi-post-activation-readback.md` proves three profile states (present/absent/unreadable) from fresh sessions against installed bytes; source-tree alone is not the claim.
- **R42 — DONE (CROSS-REPO):** `docs/evidence/2026-08-22-unifi-post-activation-readback.md` names trigger, prior version, refresh, and repeated proof per plan's rollback definition.
- **R45 — DONE (CROSS-REPO):** upstream `0eb1fe04` carries `tests/test_unifi_docs_match_code.py` (byte-copy shas in `PROVENANCE.json` attest to it); `plugins/unifi/README.md` and reference docs now parity with code.

**COMPLETION: 42/45 DONE, 1 PARTIAL (R14, repo-gated but runtime name-only residual is F-02), 0 NOT-DONE, 0 CHANGED, 1 UNVERIFIABLE. Previous cycle: 36 DONE, 7 PARTIAL, 1 NOT-DONE, 1 UNVERIFIABLE — net +6 DONE.**

## Roster scores

Acceptance requires `derived_overall >= 9.0` and every applicable dimension `>= 7.0`. Scores below are bound to `b4418a1`.

| Lens | Applicable dimensions (score) | Non-applicable cause | Derived overall | Failing dims |
|---|---|---|---:|---|
| architecture-maintainability | ownership/single-sources 7; separation 9; dependency 9; simplicity 8; readability/errors 9; portability/config 9; decisions 9 | none | 8.57 | none (overall <9) |
| deployment-infrastructure | infra/config 8; rollout order 9; rollback/drift 8; deployed verification 8 | no cloud resource / cost change | 8.25 | none (overall <9) |
| correctness | intent/completeness 9; state/invariants 9; boundaries 8; side effects/errors 8; consumers 9 | none | 8.60 | none (overall <9) |
| security | auth/default deny 9; input boundaries 9; secrets 7; supply chain 8; confidentiality 8 | none | 8.20 | none (overall <9) |
| testing | requirements 8; negative/edge 8; assertions 9; realistic seams 8; determinism 9 | none | 8.40 | none (overall <9) |
| reliability | retries/timeouts 7; partial failure 9; graceful degradation 9; health signals 8 | no queue/job ordering | 8.25 | none (overall <9) |
| api-contract | compatibility 9; versioning 8; serialization/errors 8; retry semantics 7; pagination/rate-limits 9; sdk/generated 9; spec parity 8 | pagination not material | 8.29 | none (overall <9) |
| adversarial | assumptions 7; abuse/edges 8; silent green 8; environment/operator 7; scope 9; alternatives 9; recovery 8 | none | 8.00 | none (overall <9) |

All eight lenses clear the per-dimension floor `>=7.0`. None clears the derived-overall `>=9.0` — each is `8.00-8.60` — so by the roster's `all` combiner the review derives `repairs_requested` even though no single dimension is red. The overall is honest: the artifact now has deterministic, closed, failing-in-the-right-direction validators, but two load-bearing `P2` residuals remain (F-01/F-04 retry semantics and F-02 secrets at runtime), plus a queued single-source conflict (F-03). The gap between "every dimension acceptable" and "overall excellent" is exactly where those residuals sit.

## Verification and coverage

All repository-provided checks pass on the reviewed tree:

- `python3 scripts/check_repo.py` — passed (now including `check_secret_free_values`, `check_fleet_bundle_outputs`, closed-set both-directions, and 6-field stamp requirement).
- `python3 -m unittest discover -s tests -v` — 373 passed (was 280; +93 from `test_check_repo` closed-set/bundle/secret, `test_discover` policy/persistence, `test_drift` policy-aware seams, `test_unifi_readme`).
- `python3 -m pytest tests -q` — 383 passed (pytest suite includes the 10 fleet-commons retry tests, 3 of which still lack HTTP-date coverage).
- `python3 scripts/bundle_fleet_module.py --check` — passed.
- `python3 scripts/check_compatibility_matrix.py` — passed on both current and superseded matrices (40+40 stage results, binding verified).
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint` — `23` files `6e6b57c1…8415` matches the current matrix.
- Entrypoints — `python3 plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py --help` and `unifi_protect_client.py --help` both exit 0 with usage (29/21 lines), no `ModuleNotFoundError`.
- `git diff --check` — passed; working tree clean.

Those greens now prove more than last cycle: `check_repo.py` previously passed while missing unlisted-file, missing stamp field, and value-level credential cases — it now fails each of those (refutation above). `check_compatibility_matrix.py` previously passed while the digest was well-formed but wrong — it now recomputes it. The drift `missing-policy` finding that the tests previously asserted as expected now correctly tests absent for live discovery. The drifts are fixed, not hidden.

Suppressed count: 0 candidates suppressed at `<75` — every reported finding is at `75` or `100` (F-03 at `75` as a single-owner queued task; F-01/F-02/F-04 at `100`).

No ambient-machine-state finding survived beyond what the tests already isolate: `tests/test_drift.py:7-15` pins `UNIFI_SITE_PROFILE` *and* `XDG_CONFIG_HOME` via a temp `config_path`, and the discovery tests do the same; `tests/test_client_entrypoints.py` uses temp stubs and a sanitized env. The site-identifying leakage hunt across `docs/evidence/*.md` found only `controller.example` and `example-*` placeholders; `scripts/check_compatibility_matrix.py:740-780` and `scripts/check_repo.py:785-817` both mechanically enforce that for committed public evidence.

Testing gaps corresponding directly to the remaining findings: HTTP-date `Retry-After` in `retry_backoff` and both clients (F-01/F-04); credential *values* in `validate_profile` (F-02); a live sync fixture proving `README.md` stays target-owned *through* a sync (F-03 — covered once the queued fix lands).

## Route

- **F-01 / F-04 — retry date form:** `gated_auto -> review-fixer` — parse both `Retry-After` forms in `unifi_network_client.py`/`unifi_protect_client.py` and ideally in `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` (with custody staying upstream per `docs/engineering-journal/DECISIONS.md#custody-of-the-fleet-core-slice`). Needs spec on which `Retry-After` forms UniFi actually emits to avoid over-engineering a fleet primitive for a theoretical header.
- **F-02 — secret in value:** `manual -> human` — decide the guarantee wording (field-only vs value-level) before touching code; a value-level fix that broke `notes: "ask the owner for the credential"` would be worse than the defect. `docs/engineering-journal/DECISIONS.md:257-332` already frames the two families and the accepted limits.
- **F-03 — README byte-copy table:** `safe_auto -> review-fixer` — one line in `scripts/sync_vendor_source.py:80` plus `tests/test_sync_vendor_source.py` fixture; land before the next `synchronize()` so the already-passing `test_unifi_readme.py` guard is not the only thing between a resync and a regression.

> `outcome: repairs_requested`; `next_action: return structured fixes to Work and release owners`. Fix order: F-01/F-04 (reliability contract) and F-02 (guarantee wording) first — both are load-bearing contracts a future operator will rely on; F-03 is a one-line queued cleanup before the next sync. No new P0 blocks. The pilot's evidence surface (matrix + readback + bindings) is now sound; the two remaining `P2` defects are real but bounded and explicitly documented, not silent greens.

## Appendix — evidence ledger

- `python3 scripts/check_repo.py` — `Repository validation passed.` on `b4418a1`.
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint` — `file_count 23` `tree_sha256 6e6b57c125cbe1a7c3efe1c1bbd90a424ae93bebed2575b5653d2ed4d9148415`.
- `python3 -m unittest discover -s tests 2>&1 | tail -2` — `Ran 373 tests in ~14s  OK`.
- `git log --oneline 95de0d5..b4418a1` — `b4418a1 2189be1 2a5e7a6 82eed83 b3d9c61 d8c2e7b 0248350 0d56da9 633ffab cc0d139 772af43` (five repair branches plus the two review reports, all ancestors of HEAD).
- `git diff 95de0d5..b4418a1 --stat` — 22 files, +4701/-361.
- Immutability anchors preserved: `docs/reviews/2026-08-22-code-review-cursor-gpt-5.6-sol-xhigh.md` (`75da1077…ad3f0ed`) and `docs/reviews/2026-08-22-code-review-opencode-muse-spark-1.2-xhigh.md` (`5e8a5204…46db92d`) are byte-identical to the consensus digests at `docs/reviews/2026-08-22-code-review-consensus.md:52-56`.


