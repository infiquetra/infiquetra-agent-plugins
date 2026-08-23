# Post-repair scored code review — cycle 3 (orch/orch-2026-08-22-unifi-cycle3, bdaa814)
Independent reviewer: opencode / muse-spark-1.2 — unattended
Branch `orch/orch-2026-08-22-unifi-cycle3` at `bdaa814b28fcbbcfca0bab08f8f85800a1d6c751`, diffed against merge-base `95de0d5fe0a2427ab54cf02489b9b14b56bf9745` (cycle-1 `repairs_requested` baseline). Previous cycle-2 consensus at `b4418a1` recorded O1..O7; this review independently verifies every C1..C10 repair claim from that consensus and hunts the "guarantee that exists but does not bite" pattern across seams, validators that cannot fail, ambient-state tests, and public-boundary leaks.

## Scope check

Scope Check: [DRIFT DETECTED — no scope creep, two deferred items and one new advertised limitation]

Intent: From `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` — repair the twelve reconciled findings (C1..C10 plus pattern) that blocked the portable UniFi + Fleet Core pilot, close the seven cycle-2 open items O1..O7, re-synchronize the Fleet Core slice to upstream `0.25.1` at `ed72f439`, rebound the generated bundles, and keep the ten-client matrix as evidence rather than decoration — all under the portability-pilot custody and public-boundary rules.

Delivered: `check_repo.py` now closes the provenance set and requires the six bundle-stamp fields; `site_profile.py` plus its schema now rejects a credential by value as well as by name; `discover.py` fails closed when the working-tree walk finds nothing and when asked to write inside `PACKAGE_ROOT`; `drift.py` declares policy observation and only emits `missing-policy` against an observed set; `check_compatibility_matrix.py` binds every matrix document to the live `plugins/unifi/` tree (file count, tree digest, name, version) and makes `matrix-status: superseded` the only exemption; `sync_vendor_source.py` makes `README.md` target-owned and filters stale `README` from cleanup; `retry_backoff.py` at `plugins/fleet-core` and both `_bundled` copies now expose `parse_retry_after` for both RFC 7231 forms; `PROVENANCE.json` for both packages pins `ed72f439`/`0.25.1` and `2.0.0`; the three evidence matrices are re-run and the current document fingerprints to `da46ca77` at 23 files. Clients at `skills/*/scripts/unifi_*_client.py:176` still do `int(Retry-After)` before the primitive sees the header (O3 partial), and the byte-copied `retry_backoff.py:28` `from datetime import UTC` needs Python 3.11 while the catalog still documents 3.10 (queued P1). No unrelated scope creep.

## Lens selection (roster `lens_roster.v1`)

Four always-on lenses run on every review. Three conditional lenses are selected because this diff materially touches their domains; two are explicitly not selected.

| Lens | Class | Selection reason |
|---|---|---|
| `architecture-maintainability` | always-on | — |
| `correctness` | always-on | — |
| `security` | always-on | — |
| `testing` | always-on | — |
| `reliability` | conditional | diff adds `parse_retry_after`, reworks `retry_with_backoff` with `now` seam, changes drift's policy-observation logic, and changes discovery persistence failure mode |
| `api-contract` | conditional | diff changes `site-profile.schema.json` contract version 1.0→1.1, adds public `parse_retry_after` to Fleet Core's contract, and changes `retry_after` callable type to `float \| str \| None` |
| `adversarial` | conditional | 39-file, 8124-line change whose prior cycle pattern is "a gate that passes when it should fail" across provenance closed-set, stamp-field, redaction-by-value, unlink escape, and persistence deny-list |
| `deployment-infrastructure` | conditional | **not selected** — no infrastructure, migration, rollout, or cost/resilience change; provenance and bundle checks are local validation, not deployed infrastructure |
| `performance` | conditional | **not selected** — no latency, throughput, query, or capacity claim; retry jitter bounds are reliability, not a performance target |

## Lens scores (anchor bands from `lens-roster.json`)

Scores are per-dimension against that dimension's 10/9/7-8/5-6/0-4 anchors; `derived overall` is the mean of applicable dimensions for this report (the scorer's combiner is `all` with `derived_overall>=9.0` and `applicable_dimension>=7.0`).

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall | Failing dimensions |
|---|---|---:|---|---|
| `architecture-maintainability` | fit/ownership 7; separation 9; dependency 8; simplicity 8; readability 9; conventions 8; decisions 9 | — | 8.29 | `architectural-fit-ownership-single-sources` (Python 3.11 floor vs 3.10 docs) |
| `correctness` | intent 7; state/invariants 8; boundaries 7; side-effects 8; consumers 7 | — | 7.40 | `boundary-types-serialization-numeric-time` (client `int(Retry-After)` truncates HTTP-date), `intent-behavior-completeness` (O3 caller half still missing) |
| `security` | auth 9; input 8; secrets 8; supply-chain 8; confidentiality 9 | — | 8.40 | none below 7 but overall below 9 |
| `testing` | requirements 9; negative/edge 9; behavior-sensitive 8; seams 8; determinism 9 | — | 8.60 | none below 7 but overall below 9 |
| `reliability` | timeouts/retries 6; queues N/A; concurrency 8; graceful/cancel 8; health 7 | `queues-jobs-dead-letters-ordering-backpressure` — no queue, job, ordering, or backpressure surface | 7.25 | `timeouts-retries-circuit-breakers-idempotency` |
| `api-contract` | contract/compat 8; versioning 9; serialization/errors 8; retry/idempotency 7; pagination N/A; SDK N/A; spec/doc parity 9 | `pagination-rate-limits`, `sdk-generated-client-impact` — no collection pagination or generated SDK | 8.20 | none below 7 but overall below 9 |
| `adversarial` | load-bearing 6; abuse/edge 7; silent-green 7; environment 7; scope N/A; alternatives N/A; recovery N/A | scope/alternatives/recovery preconditions absent for this delta (no new alternative analysis) | 6.75 | `load-bearing-assumptions` |

`review_result.v1` acceptance requires `derived_overall>=9.0` for every selected lens and `applicable_dimension>=7.0`. Six of seven lenses sit below 9.0; one dimension (`reliability:timeouts-retries...` at 6, `adversarial:load-bearing` at 6) sits below the dimension floor. Outcome is therefore `repairs_requested` before any Priority gate.

## Repair verdicts C1..C10 — independent from-cycle-1 95de0d5, verified against bdaa814 tree and live execution

| # | Title from 2026-08-22-consensus | Cycle-2 adjudicated | This review | Evidence `file:line` that proves the verdict |
|---|---|---|---|---|
| C1 | Compatibility matrix describes the pre-repair package, not the shipped tree | FIXED | **FIXED** | `scripts/check_compatibility_matrix.py:268-430` recomputes `package_fingerprint()` (sorted per-file sha256 plus relative paths) and `package_identity()` and fails when `$.package.file_count / tree_sha256 / name / version` diverge; `check_document_status` makes `matrix-status` default `current` so binding is fail-closed; `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` carries `<!-- matrix-status: current -->` and `docs/evidence/2026-08-22-unifi-compatibility-matrix-pre-repair.md:1` + `...-pre-resync.md:1` carry `superseded` with `superseded-by` naming the current doc; live `python3 scripts/check_compatibility_matrix.py` passes with `23 files da46ca77d5d5…` and `python3 scripts/check_compatibility_matrix.py --print-fingerprint` recomputes `name: unifi version: 2.0.0 file_count: 23 tree_sha256: da46ca77d5d5290339586bdae87cbc8cb192f233f4b2f863e623b9e2b57308c5` equal to the ` ```json ` record's `package` field |
| C2 | Drift reports every profiled network as a missing policy | FIXED | **FIXED** | `plugins/unifi/scripts/discover.py:147-156` defines `POLICY_OBSERVATION_KEY`/`POLICY_UNAVAILABLE` because the catalog `READ_ONLY_OPERATIONS:78-107` composes no policy operation; `empty_inventory:478-483` and `DiscoverySession.collect:640-643` stamp `policy_observation: unavailable`; `plugins/unifi/scripts/drift.py:95-115` `policy_observation()` returns `observed` only when the inventory earns it (non-empty `policies` or explicit `observed` declaration, case-insensitive), otherwise `unavailable`; `drift.report:140-193` emits `missing-policy` only when `observation == observed` and otherwise appends `POLICY_UNOBSERVED_LIMIT` to `limits`; `tests/test_drift.py:237-326` pins both directions (live-discovery inventory produces only `unprofiled-host` and `policy_observation: unavailable` + limit, policy-aware inventory produces `missing-policy` when expected policy absent, observed+empty still reports missing) |
| C3 | Provenance validation is not closed over package files | PARTIAL (Ox Alpha correct) | **FIXED** | `scripts/check_repo.py:77-103` documents the bytecode exemption is about *placement* not suffix; `362-396` `_is_interpreter_bytecode` returns True only under `__pycache__` or beside a matching `.py` (`(plugin_dir/relative).with_suffix(".py").is_file()`); `_managed_package_files:383-397` excludes only those two shapes; `_closed_set_errors:400-448` reports duplicate entries, every unlisted file, and every listed-but-missing file; live attack `smuggled.pyo` added at `plugins/unifi/skills/unifi-network/scripts/smuggled_test.pyo` produces `unlisted package file: … is not classified by plugins/unifi/PROVENANCE.json` and moves `package_fingerprint()` from 23 da46ca77 to 24 69dcc452; `scripts/check_compatibility_matrix.py:101-116` fingerprint excludes only `FINGERPRINT_EXCLUDED_DIRECTORIES = {"__pycache__",…}` never by suffix, so a `.pyo` anywhere outside those directories changes `tree_sha256`; both gates miss-nothing now |
| C4 | Bundle provenance fields optional, so a stale bundle can pass CI | FIXED | **FIXED** | `scripts/check_repo.py:105-118` `BUNDLE_REQUIRED_STAMP_FIELDS` names all six fields (`generated-by`, `source-version`, `source-commit`, `source-path`, `source-sha256`, `output-sha256`); `check_bundled_files:548-586` reports `generated bundle stamp missing <field>: …` by name and rejects `unstamped generated bundle`; `_check_bundle_source_freshness:589-630` compares live Fleet Core bytes vs `source-sha256` and is skipped only when the stamp already omitted the fields (already reported); removing `source-version` now fails `check_repo.py` rather than disabling the comparison |
| C5 | Portable README is Claude-specific / references missing docs | FIXED for shipped artifact, residual queued | **FIXED for shipped artifact** | `plugins/unifi/README.md:1-60` lede is now `UniFi portable package / Portable Agent Plugins 1.0 package` with `com.infiquetra.claude/` as adapter and no `Claude Code plugin` claim; `plugins/unifi/PROVENANCE.json:104-106` classifies `README.md` as `target-owned` (no digest, never overwritten); `scripts/sync_vendor_source.py:80-105` removes `README.md` from `PORTABLE_BYTE_COPIES` and lists it in `SUPERSEDED_BY_TARGET_OWNED` with comment citing `DECISIONS.md` `The portable UniFi README is target-owned, rewritten site-neutral`; `stale_managed_paths:640` subtracts `SUPERSEDED_BY_TARGET_OWNED` so a previous manifest that recorded `README.md` as byte-copy does not `unlink` the portable file; `tests/test_unifi_readme.py:1-50` and `tests/test_sync_vendor_source.py:TargetOwnedTests` assert the file is target-owned and survives a re-run |
| C6 | Secret-free / redaction validation is partial | PARTIAL (repo gate closed, site-profile runtime still name-only) | **FIXED** | Repo gate: `scripts/check_repo.py:137-163` `CREDENTIAL_FORMATS` (11 literal families), `171-206` assignment family plus `CREDENTIAL_PLACEHOLDER`/`REFERENCE_PREFIX` excluded, `786-842` `credential_findings` + `check_secret_free_values` scoped to `plugins/` and firing on both data (assignments) and source (literals); live `python3 scripts/check_repo.py` passes with zero false positives, `tests/test_check_repo.py` now covers the value families. Runtime: `plugins/unifi/scripts/site_profile.py:131-285` re-states the same two families as `CREDENTIAL_VALUE_FORMATS` plus `CREDENTIAL_VALUE_ASSIGNMENT` with `MIN_ENTROPY 2.5`, checks *every string at any depth* via `_credential_value:245-265` and `_credential_in_text`, rejects with `credential value is not permitted … (label)` naming the property path; `plugins/unifi/schemas/site-profile.schema.json:46-62` guards every free-text value against the 11 literal patterns and closes every object with `nonCredentialPropertyName`; `tests/test_site_profile.py:223-276` proves `notes: "controller password=hunter2"` rejected naming `subjects[0].notes` + `password`, all five free-text placements rejected, literal digests accepted (`CredentialRuleDriftTest` pins the two copies equal), low-entropy `password=secret` admitted as documented limit (see O2) |
| C7 | `Retry-After` HTTP-date form not handled | NOT FIXED — expected, upstream byte copy | **PARTIAL** | Primitive FIXED at `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:47-92` `parse_retry_after(value, *, now=time.time)` handles both RFC 7231 forms (delta-seconds via `float(text)` and HTTP-date via `parsedate_to_datetime` with asctime/RFC850/fixdate, past→0.0, absent/empty/unparseable→None, `bool` excluded, zone-less asctime forced to `UTC`), `retry_with_backoff:116-165` widens `retry_after` to `float\|str\|None` and calls `parse_retry_after(raw_hint, now=now)` before `_retry_delay` which clamps to `max_delay` and falls back to computed jitter on non-positive; `tests/test_retry_backoff.py:217-336` pins future/past/excessive dates, all three date forms, clamping, and the `int()` still-loses-the-retry boundary. Callers NOT FIXED: `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176` and `unifi_protect_client.py:176` still do `raise _RateLimited(int(resp.headers.get("Retry-After", 60)))`; `int("Fri, 31 Dec 2100 23:59:59 GMT")` raises `ValueError` which carries no 429 status so `is_retryable` is false and the 429 is never retried — the primitive's fix is unreachable for the header form real controllers send; fixing it needs the callers to hand the raw header string to `parse_retry_after` or to the primitive's `retry_after` callable without `int()` |
| C8 | Malicious/corrupt `PROVENANCE.json` can unlink files outside the package | FIXED | **FIXED** | `scripts/sync_vendor_source.py:541-570` `_managed_path_violation` does lexical `is_absolute or ".." in parts` and containment `resolve().is_relative_to(package.resolve())` including symlink resolution, `resolve_managed_path:572-589` is the single chokepoint that every write and every deletion goes through and raises `SyncError` rather than skipping, `previously_managed:591-619` calls `resolve_managed_path` for every entry so a hostile path aborts before any unlink, `stale_managed_paths:622-640` is the only stale-set computation; `tests/test_sync_vendor_source.py:ManifestPathSafetyTests` proves `/etc/hosts`, `../../..`, symlink, and `plugin_dir` itself all raise and delete nothing |
| C9 | Post-activation proof was never performed | EVIDENCED AND BOUND | **FIXED** | `docs/evidence/2026-08-22-unifi-post-activation-readback.md:1-268` now exists with staged load, installed-version/digest readback, and fresh-session three-state proof (profile present/absent/unreadable); `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1-120` second re-run header documents `23 files da46ca77…` as `The assessed copy is the shipped tree` with `The point of the exercise is to learn which clients can consume…` and recomputes binding; `scripts/check_compatibility_matrix.py:101-192` `package_fingerprint` is the machine that makes that claim falsifiable; controller readback is not re-verified by this code reviewer beyond file presence and validator pass |
| C10 | Discovery persistence deny-list fails open without a `.git` directory | FIXED | **FIXED** | `plugins/unifi/scripts/discover.py:280` `PACKAGE_ROOT = Path(__file__).resolve().parent.parent`; `300-343` `refuse_repository_output` has two independent refusals — inside `PACKAGE_ROOT` always (needs no checkout) and inside the repository working tree when known — and when `repository_root_from() is None` raises `DiscoveryPersistenceError` naming `--repository-root` rather than returning the path; `tests/test_discover.py:278-415` covers inside-package refusal with unrelated `repository_root`, undeterminable-tree refusal, the whole `discover`→`persist_payload`→`refuse_repository_output` chain, named-root lift, plus `test_gitless_walk_refuses_persistence_and_names_repository_root` which drives a real directory under `/private/tmp` with no `.git` ancestor without monkeypatching and still raises |

## Cycle-2 open items O1..O7

| # | Cycle-2 item | Adjudicated | This review | `file:line` proof |
|---|---|---|---|---|
| O1 | `.pyc`/`.pyo` suffix exemption smuggles arbitrary content past both gates | P2 review-fixer | **FIXED** — `check_repo.py:77-83+362-397` now exempts bytecode only under `__pycache__/` or beside a matching `.py` (PEP 3147 legacy); adding `plugins/unifi/skills/unifi-network/scripts/smuggled.pyo` with arbitrary bytes produces `unlisted package file: … is not classified by plugins/unifi/PROVENANCE.json` and moves `check_compatibility_matrix.package_fingerprint()` from `(23, da46ca77…)` to `(24, 69dcc452…)` so both gates bite; `FINGERPRINT_EXCLUDED_DIRECTORIES` excludes only directories, never suffix |
| O2 | Site-profile runtime `validate_profile` checks names, not values | P2 needs decision | **FIXED with admitted limit** — `site_profile.py:131-285` rejects a credential written as a value via 11 literal formats or `password=…` assigned high-entropy value at any depth (every string inspected, property paths named), matching `check_repo.py` families byte-for-byte (`CredentialRuleDriftTest` pins `CREDENTIAL_FORMATS`, `CREDENTIAL_ASSIGNMENT`, `MIN_ENTROPY`, `PLACEHOLDER`, `REFERENCE_PREFIX` and `shannon_entropy` equal); digest `e3b0c442…` in `notes` still accepted (no bare entropy scan), `vault:`/ `env:`/ `<redacted>`/ `${VAR}` references accepted, `password=secret` (2.25 bits, below 2.5 floor) passes and is **documented as defense-in-depth not a proof of absence** in `references/site-profile.md:56-88` and `site_profile.py:1-19` |
| O3 | `Retry-After` HTTP-date unhandled (C7) | P2 needs decision — upstream custody | **PARTIAL — primitive fixed, callers not** — primitive at `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:47-92` handles both RFC 7231 forms with past→`0.0` and unparseable→`None` and is exercised by `tests/test_retry_backoff.py:217-336`; callers at `unifi_*_client.py:176` still `int()` the header and turn an HTTP-date 429 into `ValueError` which carries no 429 status and is never retried; fixing callers requires upstream `infiquetra-claude-plugins` to hand the raw `Retry-After` string through without `int()` (the provenance byte-copy rule forbids a downstream edit) |
| O4 | `README.md` still in `PORTABLE_BYTE_COPIES`; next sync overwrites portable README | P3 review-fixer | **FIXED** — `sync_vendor_source.py:82-105` removes `README.md` from `PORTABLE_BYTE_COPIES`, lists it in `SUPERSEDED_BY_TARGET_OWNED = ("README.md",)` with `DECISIONS.md` citation, `PROVENANCE.json:104-106` records it as `target-owned`, `stale_managed_paths` subtracts the superseded set so an old manifest recording `README.md` as byte-copy does not `unlink` the portable file |
| O5 | Sync custody table contradicts recorded custody decision (Ox F1) | P2 review-fixer | **FIXED** — `sync_vendor_source.py:classify_source_tree:420-453` requires every upstream path be assigned exactly once among `PORTABLE_BYTE_COPIES (5)` + `PORTABLE_ENTRYPOINT_TRANSFORMS (2)` + `CLIENT_BYTE_COPIES (3)` + `SUPERSEDED (1)` + `DROPPED (2)` + `SOURCE_MANIFEST (1)` = 14 source files, raising `SyncError` listing unclassified/absent/duplicate paths; `tests/test_sync_vendor_source.py::ShippedPackageTests.test_the_custody_table_agrees_with_the_recorded_classification` now passes and the table agrees with `PROVENANCE.json` classifications (11 synchronized files `CUSTODY` == 11 `files` entries with `source_path`) |
| O6 | Gitless-walk negative case untested (Ox F5) | P3 review-fixer | **FIXED** — `tests/test_discover.py:362-415` adds `gitless_working_directory()` which finds a real temp ancestor under `/private/tmp` with `repository_root_from() is None` (because `TMPDIR=/var/folders/...` is not gitless) and `test_gitless_walk_refuses_persistence_and_names_repository_root` drives `refuse_repository_output(output)` with no monkeypatch and asserts `DiscoveryPersistenceError` naming `--repository-root` |
| O7 | Binding proves identity, not execution (Ox F6) | advisory operator | **RECORDED as limitation, not a gate** — `docs/engineering-journal/QUEUED.md:262-304` `Keep the matrix binding an identity check; do not add an execution-proof gate` documents O7 as *maybe* priority, recording-only, with rationale that plan U11 (matrix, R22/R43) plus U9 (readback R40, three-state fresh-session R41 in `2026-08-22-unifi-post-activation-readback.md`) already require execution and that a digest cannot prove forty stages ran; `LEARNINGS.md:89-156` `A bound digest names the tree, not the forty stages that assessed it` states `identity is not execution` and `check_package_binding` stays the identity half; no blocking gate was added (correct per curators) |

## Fleet Core 0.25.1 resynchronization (`ed72f439ba01f2e20d94be074e5612c5641c0c8e`)

**Genuine byte copy — YES.** `plugins/fleet-core/PROVENANCE.json:4` pins `source_commit: ed72f439ba01f2e20d94be074e5612c5641c0c8e` and `source_version: 0.25.1`; `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` at head hashes `sha256 5aea3be13ac444aba2610442f76846a16a0e9537befe39090da173cb1fede975` equal to `PROVENANCE.json:35` `sha256` for that file. The module was extracted with `git show <commit>:plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` per `PROVENANCE.json:10` note, which is the same primitive `scripts/sync_vendor_source.py:158-211` uses internally, and `scripts/check_repo.py:260` recomputes and matches the digest — `python3 scripts/check_repo.py` passes green.

**Bundles rebound — YES, both destinations.** `plugins/unifi/skills/unifi-network/scripts/_bundled/retry_backoff.py:1-7` and `plugins/unifi/skills/unifi-protect/scripts/_bundled/retry_backoff.py:1-7` carry identical stamps: `source-version: 0.25.1`, `source-commit: ed72f439…`, `source-path: scripts/fleet_commons/retry_backoff.py`, `source-sha256: 5aea3be13ac…` (matches the live source above), `output-sha256: 5aea3be13ac…` (hash of the file with its stamp block excluded via `split_bundle_stamp`/`bundle_output_digest` per `scripts/check_repo.py:491-531`), `generated-by: scripts/bundle_fleet_module.py`. Both `_bundled` payloads (stamp removed) are byte-identical to `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py`. `plugins/fleet-core/CHANGELOG.md:13-56` documents the repair and the stamp rebinding, and `scripts/check_repo.py:548-630` verifies both `output-sha256` (tamper) and `source-sha256` (stale source) independently.

**Known limitation introduced with the fix — not a byte-copy failure.** `retry_backoff.py:25` does `from datetime import UTC`, which exists only in Python 3.11+. Under Python 3.10 that line raises `ImportError: cannot import name 'UTC'` — verified as `ImportError` on a 3.10 interpreter, and `plugins/fleet-core/PROVENANCE.json:11` plus `CHANGELOG.md:57-66` plus `docs/engineering-journal/QUEUED.md:60-110` document the floor mismatch explicitly. The byte-copy rule (`PROVENANCE.json:11` — "The byte-copy rule forbids repairing that here") correctly leaves the defect unedited downstream; the decision is queued as P1 `Decide the Python floor the Fleet Core resync raised` (fix upstream to `timezone.utc` or move the catalog floor to 3.11). This does not weaken the byte-copy guarantee; it does mean `python -m pytest tests/test_retry_backoff.py` fails to import on Python 3.10 while `python3 scripts/check_repo.py` still passes (the hermetic job never imports that module). A consumer on 3.10 sees `ImportError` at the retry path.

## Findings (admitted, confidence >=75 except P0 at 50+; sorted P0→P3 then confidence→file→line)

### P1 — none admitted

No P1 finding survives validation on this diff at anchor 75+. The four severities that distinguished cycle-1 (closed-set smuggling, stamp-field optionality, path-escape unlink, persistence fail-open) all now bite: each bites on the live attack provably.

### P2

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176` | `Retry-After` HTTP-date at callers still does `int()` and loses the retry | `reliability`, `correctness`, `adversarial` | 100 | `gated_auto -> review-fixer` |
| F-02 | `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:28` | Byte-copied `from datetime import UTC` needs Python 3.11 while the catalog documents 3.10 | `architecture-maintainability`, `adversarial` | 100 | `gated_auto -> human` |

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-03 | `scripts/sync_vendor_source.py:138-141` | `MANIFEST_EXCLUDED_SUFFIXES` still excludes `.pyc`/`.pyo` everywhere while `check_repo` exempts them only under `__pycache__` or beside a matching `.py` | `architecture-maintainability` | 75 | `safe_auto -> review-fixer` |
| F-04 | `docs/engineering-journal/QUEUED.md:1` | P0 "Re-run the ten-client matrix…" still listed as open while the three matrices validate green | `architecture-maintainability` | 75 | `advisory -> human` |

### Advisory (no autofix)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-05 | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` | Binding proves `tree_sha256` identity, not that forty stages ran — correctly queued as Maybe, not a gate (O7) | `adversarial` | 100 | `advisory -> human` |
| F-06 | `plugins/unifi/scripts/site_profile.py:131` | Credential by value still passes when the secret is short and low-entropy (`password=secret`, 2.25 bits) — documented defense-in-depth, not proof of absence | `security` | 100 | `advisory -> human` |

Suppressed (below admission): none. One P0 at 50+ would have been admitted but none was raised.

### Detailed findings (per `findings-schema.md` — every field)

#### F-01 — `Retry-After` HTTP-date at the UniFi callers still `int()`s and turns a 429 into a non-retryable `ValueError` (P2)

- `severity`: P2
- `dimension_id`: `timeouts-retries-circuit-breakers-idempotency` (also `boundary-types-serialization-numeric-time`, `load-bearing-assumptions`)
- `critical`: false
- `file`: `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py`
- `line`: 176
- `why_it_matters`: A controller that sends `Retry-After: Fri, 31 Dec 2100 23:59:59 GMT` (RFC 7231 HTTP-date, real behavior) causes the call to raise `ValueError: invalid literal for int()` instead of backing off; the error carries no `status_code` 429, so `retry_with_backoff` treats it as non-retryable and the rate-limit is never retried — one request, no backoff, generic error in logs
- `autofix_class`: `gated_auto`
- `owner`: `review-fixer`
- `requires_verification`: true
- `confidence`: 100
- `evidence`:
  - `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176` — `raise _RateLimited(int(resp.headers.get("Retry-After", 60)))`
  - `plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py:176` — identical
  - `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:47-92` — `parse_retry_after` correctly handles `parsedate_to_datetime` for HTTP-date and `float(text)` for delta-seconds; `tests/test_retry_backoff.py:317-336` `test_a_caller_that_pre_parses_with_int_still_loses_the_retry` proves `int(FUTURE_DATE)` yields exactly one call and zero sleeps
  - Live attack: `python3 -c "int('Fri, 31 Dec 2100 23:59:59 GMT')"` raises `ValueError`; a mocked 429 with that header against the client would not retry
- `pre_existing`: false — the `int()` was in the 95de0d5 baseline, the primitive at `ed72f439` fixed the inner parser but the callers were deliberately left as transforms that only rewrite the shim import (`scripts/sync_vendor_source.py:108-116` — `PORTABLE_ENTRYPOINT_TRANSFORMS` rule `resolve-bundled-fleet-module` documents it rewrites only the shim block and changes no other byte)
- `suggested_fix`: In `infiquetra-claude-plugins` at both `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:173-183` and the protect counterpart, change `raise _RateLimited(int(resp.headers.get("Retry-After", 60)))` to capture the raw header `raw = resp.headers.get("Retry-After", "60")` and either `raise _RateLimited(raw)` with `retry_after = parse_retry_after(raw)` stored, or keep the int path for delta-seconds but fall back to `parse_retry_after` for HTTP-date; callers must hand `retry_after=lambda exc: getattr(exc, "retry_after", None)` a value that `parse_retry_after` can reduce (assumption: changing `_RateLimited.retry_after` from `int` to `str|float` is additive and `retry_with_backoff` already widens `retry_after` to `float|str|None`; if strictly preserving `int`, store `retry_after_raw: str` alongside). Ship upstream, release, re-synchronize; do not edit here (would create a second writable source)

#### F-02 — Portable Fleet Core now imports `datetime.UTC` (Python 3.11+) while the catalog documents Python 3.10 (P2)

- `severity`: P2
- `dimension_id`: `conventions-portability-configuration` (also `load-bearing-assumptions`)
- `critical`: false
- `file`: `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py`
- `line`: 28
- `why_it_matters`: A user on the documented floor (`.github/workflows/ci.yml:60` pins `python-version: '3.10'` for the ported-plugin job, `CHANGELOG.md:108` and `site-profile.md` declare 3.10) that imports any path through `retry_backoff` under Python 3.10 gets `ImportError: cannot import name 'UTC' from 'datetime'` before any retry logic runs; the hermetic `python3 scripts/check_repo.py` job stays green (it never imports `retry_backoff`) while `python -m pytest tests/test_retry_backoff.py` fails to import on 3.10, so the floor documented as exercised is not exercised for this module
- `autofix_class`: `gated_auto`
- `owner`: `human`
- `requires_verification`: true
- `confidence`: 100
- `evidence`:
  - `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:28` — `from datetime import UTC`
  - `plugins/fleet-core/CHANGELOG.md:57-66` Known issues — `This release needs Python 3.11 … exists only in Python 3.11 and newer, so importing it under Python 3.10 raises ImportError`
  - `plugins/fleet-core/PROVENANCE.json:11` — `The corrected module imports UTC from datetime, which exists only in Python 3.11 … The byte-copy rule forbids repairing that here`
  - `docs/engineering-journal/QUEUED.md:60-110` P1 `Decide the Python floor the Fleet Core resync raised` — options `timezone.utc` upstream vs moving the floor to 3.11
  - `plugins/unifi/skills/unifi-network/scripts/_bundled/retry_backoff.py:28` and protect duplicate — same import, same failure
- `pre_existing`: false — introduced by the `ed72f439` (0.25.1) re-synchronization `788ad80`+`c33aa66`; the 95de0d5 tree had no `UTC` import and its `retry_backoff.py` was 3.10-clean
- `suggested_fix`: Author one line upstream in `infiquetra-claude-plugins` at `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:28` — replace `from datetime import UTC` with `from datetime import timezone; UTC = timezone.utc` (available on 3.10 and 3.11, `UTC` alias is 3.11 shorthand for that object), or `try: from datetime import UTC except ImportError: from datetime import timezone as _tz; UTC = _tz.utc` if preserving the alias name; release as Fleet Core 0.25.2, re-synchronize the slice and rebound bundles (assumption: the transform `guard-pytest-import` in `tests/test_retry_backoff.py` needs no change)

#### F-03 — `sync_vendor_source` still excludes any `.pyc`/`.pyo` by suffix while `check_repo` exempts them only under `__pycache__` or beside a matching `.py` (P3)

- `severity`: P3
- `dimension_id`: `architectural-fit-ownership-single-sources`
- `critical`: false
- `file`: `scripts/sync_vendor_source.py`
- `line`: 141
- `why_it_matters`: The two modules disagree about what counts as a package file: adding `plugins/unifi/skills/unifi-network/scripts/orphan.pyo` with no `orphan.py` is now correctly reported as `unlisted` by `check_repo.py:383-397` and changes the matrix fingerprint, but `sync_vendor_source.py:507-513` `_is_manifest_candidate` returns False for any suffix `.pyc/.pyo` so the file would not appear as `target-owned` in a freshly built manifest; the next `synchronize --check` would not name it stale but `check_repo.py` would still fail — the guarantee still bites, but via a single gate rather than both, and the manifest the script writes is not closed per the validator's definition
- `autofix_class`: `safe_auto`
- `owner`: `review-fixer`
- `requires_verification`: true
- `confidence`: 75
- `evidence`:
  - `scripts/sync_vendor_source.py:138-141` — `MANIFEST_EXCLUDED_SUFFIXES = (".pyc", ".pyo")`
  - `scripts/check_repo.py:77-83` comment — `The bytecode exemption is about placement, not about the suffix … so plugins/.../smuggled.pyo could hold arbitrary text` and `362-381` `_is_interpreter_bytecode` checks `__pycache__` directory or sibling `.py`
  - Live probe: in a temp `plugins/unifi` with `orphan.pyo` (no `orphan.py`) `check_repo._managed_package_files` lists `orphan.pyo` as managed while `sync_vendor_source.target_owned_paths` omits it
- `pre_existing`: false — `check_repo.py:362-381` was repaired in `ff7603d` `fix(gates): close the bytecode-suffix hole in the provenance closed set`; the sync file was not updated in that commit
- `suggested_fix`: Change `scripts/sync_vendor_source.py:138-141` to mirror the validator: keep `MANIFEST_EXCLUDED_PARTS = ("__pycache__",)` and replace suffix exclusion with a helper `_is_interpreter_bytecode(plugin_dir, relative)` that returns true only under `__pycache__` or beside a matching `.py` (assumption: the helper can be imported from `check_repo` or duplicated; if importing would cycle, duplicate the 4-line check and pin with a test that the two helpers agree)

#### F-04 — Queued P0 still claims the matrix needs a re-run while the three matrices validate green (P3)

- `severity`: P3
- `dimension_id`: `significant-decision-documentation`
- `critical`: false
- `file`: `docs/engineering-journal/QUEUED.md`
- `line`: 1
- `why_it_matters`: A reader of `QUEUED.md` is told the next action is an hour-long `python3 scripts/check_compatibility_matrix.py` re-run that would produce no new evidence: the live validator already passes on all three documents, the current matrix fingerprints to `(23, da46ca77…)` equal to `package_fingerprint()`, and the two retired matrices each carry `matrix-status: superseded` with a named successor; leaving a closed item as P0 erodes trust in the queue
- `autofix_class`: `safe_auto`
- `owner`: `review-fixer`
- `requires_verification`: false
- `confidence`: 75
- `evidence`:
  - `docs/engineering-journal/QUEUED.md:1-35` — `Re-run the ten-client matrix and the readback against the resynced package` as P0 `Worth it when: Now. Eight tests … are failing`
  - Live `python3 scripts/check_compatibility_matrix.py 2>&1 | tail` — `2026-08-22-unifi-compatibility-matrix.md (current):` with `23 files da46ca77…` and `Compatibility matrix validation passed.` (`python3 -m unittest tests/test_check_compatibility_matrix.py 2>&1 | tail` green)
  - `git log --oneline bdaa814^..bdaa814` — `fix(evidence): re-run the ten-client matrix and readback against the resynced package` (`e4e076c`) already landed; `git show e4e076c --stat` touched the three evidence docs and tests
- `pre_existing`: false — introduced after the `6e6b57c1…`→`da46ca77…` resync made the previous reproduction true; now stale
- `suggested_fix`: Move `docs/engineering-journal/QUEUED.md:1-35` to `ARCHIVE.md` with note `re-run completed in e4e076c (matrix now 23 files da46ca77…, readback re-run)` or retitle to P3 housekeeping; verify `python3 scripts/check_compatibility_matrix.py` still passes after the move (assumption: archiving a queued item is not a code change)

#### F-05 — Binding proves `tree_sha256` identity, not that forty stages ran — correctly queued as Maybe (advisory)

- `severity`: P3
- `dimension_id`: `load-bearing-assumptions`
- `critical`: false
- `file`: `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`
- `line`: 1
- `why_it_matters`: A correct `file_count`/`tree_sha256`/`name`/`version` match can be published without ever running a client; an operator reading the matrix as execution proof would be misled
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`:
  - `scripts/check_compatibility_matrix.py:268-430` — `package_fingerprint` + `package_identity` recompute identity; `docs/engineering-journal/LEARNINGS.md:89-156` `A bound digest names the tree, not the forty stages that assessed it`
  - `docs/engineering-journal/QUEUED.md:262-304` `Keep the matrix binding an identity check; do not add an execution-proof gate` — Maybe, recording-only, guards `Do not invent a broader new gate. Do not weaken check_package_binding.`
- `pre_existing`: false
- `suggested_fix`: none — keep `check_package_binding` as identity; execution evidence stays in the plan's separate places (`docs/evidence/2026-08-22-unifi-compatibility-matrix.md` prose `The point of the exercise…` and `docs/evidence/2026-08-22-unifi-post-activation-readback.md` readback). The entry is correctly not an autofix.

#### F-06 — Credential by value still passes when the secret is short and low-entropy (`password=secret`, 2.25 bits) — documented defense-in-depth, not proof of absence (advisory)

- `severity`: P3
- `dimension_id`: `secrets-cryptography-session-handling`
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 131
- `why_it_matters`: An operator told "credentials never live in the profile" can still write a low-entropy secret into `notes` and be told the profile is valid; the profile reaches whatever store holds the operator's deployment
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`:
  - `plugins/unifi/scripts/site_profile.py:131-285` — two families checked: literal formats anywhere and `CREDENTIAL_VALUE_ASSIGNMENT` with `MIN_ENTROPY 2.5`; `_names_a_secret` excludes placeholders; `shannon_entropy("secret")` is 2.25 and `password=secret` is therefore accepted
  - `plugins/unifi/references/site-profile.md:56-88` documents the guarantee as `defense in depth against an accident, not a proof of absence` and names `password=secret` as the accepted low-entropy example; `tests/test_site_profile.py:336-346` pins `test_a_low_entropy_assigned_value_passes_and_the_limit_is_admitted`
  - `scripts/check_repo.py:193-206` identical threshold and same admitted example
- `pre_existing`: false
- `suggested_fix`: none — this is the deliberate false-positive/true-negative trade-off; do not lower the floor (would reject ordinary prose and the `digest e3b0c44…` case) and do not add bare entropy scanning (would fire on every digest and be switched off). Keep the wording honest.

## Built-vs-planned audit (against `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:1-473`)

Verification modes: DIFF (`git diff 95de0d5..bdaa814 --stat` shows 39 files, 8124 insertions), CROSS-REPO (sibling `infiquetra-claude-plugins@ed72f439` not diffed here, verified via byte-copy digests and provenance), EXTERNAL-STATE (operator-run matrix, no live controller).

### Scope-drift detection (informational)

Intent (from plan summary `plan:10-15` + requirements R01..R45 + units U01..U12): land the portable UniFi + Fleet Core slice, close the validator gaps, re-run the evidence, and pause for operator decision — no new plugin, no vendor manifest generation.

Delivered: exactly that. No feature added outside the plan's units; the only new user-facing surface is `parse_retry_after` which is the documented additive fix for R19/R35 (CHANGELOG 0.25.1 Fixed) and `POLICY_OBSERVATION_KEY` which is the documented correction for C2.

### Plan-completion (5-state)

| # | Requirement | State | Evidence `file:line` |
|---|---|---|---|
| R01 | Derived artifact + provenance script | DONE | `scripts/sync_vendor_source.py:1`, `plugins/unifi/PROVENANCE.json:2` pins `ed72f439` |
| R02 | Hermetic provenance validation | DONE | `scripts/check_repo.py:260`, `python3 scripts/check_repo.py` passes |
| R03 | Pin corrected revision, never 995a475 | DONE | `plugins/unifi/PROVENANCE.json:3` `2.0.0@ed72f439`, `plugins/fleet-core/PROVENANCE.json:4` `0.25.1@ed72f439` (995a475 is ancestor, doc repair included) |
| R04 | Three-way classification, no divergence | DONE → FIXED | byte-copy/transform/target-owned recorded per-file, `README.md` moved from byte-copy to `target-owned`+`SUPERSEDED` |
| R05..R07 | Upstream docs repair (Protect/Network refs, skill frontmatter) | DONE | CROSS-REPO `ed72f439` carries the repair; `plugins/unifi/skills/*/SKILL.md` frontmatter has only allowed 6 fields, verified by `check_skill_frontmatter` |
| R08 | Remove hard-coded controller default | DONE | CROSS-REPO `ed72f439`; portable `plugins/unifi/scripts/*` require host/key with no default, provenance notes record relocation |
| R09 | Release gated on replacement profile path | DONE | `docs/evidence/2026-08-22-unifi-post-activation-readback.md:1` three-state fresh-session proof |
| R10..R15 | Site profile optional, no inference, secret-free, path custody | DONE → FIXED | `site_profile.py:1`, `site-profile.schema.json:1` now version 1.1 with value families; name+value checks cite `CREDENTIAL_VALUE_FORMATS:131-163` |
| R16..R21 | Portable Fleet Core slice + deferred inventory + bundling | DONE | `plugins/fleet-core/*`, `fleet-bundle.json`, `bundle_fleet_module.py`, `_bundled/retry_backoff.py` (both) |
| R22..R25 | Ten-client matrix | DONE → FIXED | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` current, 23 files `da46ca77`, re-run at `e4e076c`, binding in `check_compatibility_matrix.py:268` |
| R26..R27 | Read-only, default-deny persistence | DONE → FIXED | `discover.py:78` `READ_ONLY_OPERATIONS` only GET, `300-343` two-rung refuse plus `PACKAGE_ROOT` and undeterminable → raise |
| R28..R29 | Manifest + skill frontmatter conformance | DONE | `plugins/unifi/plugin.json` `$schema` canonical, skill `name` matches dir; `check_skill_frontmatter` green |
| R30..R31 | Orchestrate/Herdr topology | UNVERIFIABLE | not observable from diff; prose in `README.md` and evidence docs unchanged |
| R32..R33 | Fleet Core custody + release surface | DONE | `plugins/fleet-core/PROVENANCE.json:11` `Custody does not move`, `release_surface` enumerates 5 items |
| R34..R35 | Build declaration + two digest domains | DONE | `fleet-bundle.json` closed schema, `check_repo.py:491-630` two-domain `output-sha256` vs `source-sha256` |
| R36..R39 | Profile JSON, entrypoint, intents unknown | DONE | `site_profile.py:36` stdlib only, `discover.py:489-531` `proposed_profile` unknown intent + `assert_unknown_intent`, `tests/test_discover.py:493-518` pins field-by-field |
| R40..R42 | Release activation + rollback + fresh-session proof | DONE | transition evidence + `docs/evidence/2026-08-22-unifi-post-activation-readback.md` |
| R43..R44 | Evidence completeness + sanitization | DONE → FIXED | `check_compatibility_matrix.py:101` `package_fingerprint`, `466` public-evidence rules; evidence carries `file_count`/`tree_sha`/`package` + redacted commands, no raw topology |
| R45 | Upstream docs-map-to-code suite | CROSS-REPO | sibling repo test `test_unifi_docs_match_code.py` not in this tree; acceptor is provenance digest equality |

COMPLETION: 39 DONE, 0 PARTIAL, 1 NOT-DONE, 2 CHANGED (value families added while shape unchanged is CHANGED under strict reading, but correctly additive), 3 UNVERIFIABLE

One NOT-DONE is the queued P0 `Re-run the ten-client matrix…` that is already done (see F-04 — state is stale documentation, not a missing deliverable). The two CHANGED are `site-profile.schema.json:1.0→1.1` and `retry_backoff.py` adding `parse_retry_after` while keeping every existing entrypoint additive within `0.x`. No plan requirement is genuinely missing.

## Coverage, residual risks, and new defects the repairs introduced

- Superseded misses: none — `matrix_documents()` validates every `*.md` under `docs/evidence/` that embeds a matrix record, and `check_document_status` requires a successor be `current` so a chain of superseded docs cannot hide the live matrix.
- Validators that cannot fail — checked provably false: `check_provenance_manifests` failed on `smuggled_test.pyo`, `check_bundled_files` would fail on `unstamped generated bundle` and `stale source` vs `stale bundle` distinction is explicit via two digests, `check_secret_free_values` fired on `notes: "controller password=hunter2"` before the fix and still does in-repo, `check_package_binding` failed on `6e6b57c1→da46ca77` before the re-run (caught by 8 failing `test_check_compatibility_matrix` tests that were green after `e4e076c`).
- Ambient-state tests — checked: `discover.py` and `drift.py` tests now pin `XDG_CONFIG_HOME`/`config_path` inside `TemporaryDirectory` (see `test_discover.py:252-266`, `test_drift.py:96-109` `DiscoveredProfileTest.deploy_profile`) so a developer's real `~/.config/infiquetra/unifi/config.json` no longer makes a no-profile test resolve a real site; the `gitless_walk` negative case additionally asserts `--repository-root` naming on a real gitless directory.
- New defects the repairs introduced:
  - The `0.25.1` byte copy introduced `from datetime import UTC` (`plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:28`) which raises on Python 3.10 — F-02 above. This is the one true regression where the fix corrects rate-limit behavior but breaks the portability floor it was supposed to serve. The byte-copy rule correctly leaves it unfixed here; the repair belongs upstream or the floor moves.
  - The closed-set repair in `check_repo.py` was not mirrored in `scripts/sync_vendor_source.py:138-141` suffix exclusion — F-03 above. The guarantee still bites (via `check_repo`), but the two gates disagree on what a package file is.
  - The `Retry-After` callers still `int()` — F-01 — is not new with this repair but was meant to be closed by the "both forms at primitive AND at callers" scope of O3 and remains open because the callers are transforms that only rewrite the shim.
- Public-boundary leaks: `python3 scripts/check_repo.py` + `python3 scripts/check_compatibility_matrix.py` both pass; `rg` for `10.`, `192.168`, MAC, `password`, `secret` in `docs/evidence/*.md` finds only redacted commands and `vault:`/`redacted` markers; the two `aa:bb:cc:dd:ee:ff` occurrences in `plugins/unifi/com.infiquetra.claude/agents/unifi-network-ops.md` are the inert example MAC noted cycle-1 and intentionally excluded from gates (`plugins/` credential scan skips source assignments for that reason); `192.168.1.10` is an inert DNS example inside the client payload string, not site-identifying inventory.
- Testing debt: none new; `403` tests in `unittest discover` and `428` in `pytest` green; the eight `test_check_compatibility_matrix` failures before `e4e076c` are now the desired binding behavior (they were not missing tests).

### Engineering-journal alignment

Correctly appended and not drifting: `DECISIONS.md` records `Detect credentials by value with two narrow families, and never by bare entropy` (the secret-free trade-off) and `Bind a current matrix to the tree it assessed…` (fail-closed `matrix-status`, `package_fingerprint` definition) and `Reclassify both UniFi clients…` (the shim transform) and lower `Guard the join…` (bundle presence); `LEARNINGS.md` records `A digest in an evidence record proves nothing until something recomputes it`, `A package can satisfy every structural check and still have no working entrypoint`, and `A bound digest names the tree, not the forty stages…` (O7). The queued `Maybe` entry for O7 is the correct non-block.

## Outcome and routing

> **Outcome: `repairs_requested`** — six of seven lenses sit below the roster's `derived_overall>=9.0` threshold and one applicable dimension (`reliability:timeouts-retries-circuit-breakers-idempotency` at 6) sits below the `applicable_dimension>=7.0` floor, so `review_result.v1` is `repairs_requested`. Priority and confidence did not decide the outcome; the numeric lens floor did. The two locus fixes (F-01 `int(Retry-After)` at the callers and F-02 `datetime.UTC` on 3.10) are the only blocking codes; F-03 is a safe consistency sweep and F-04 is housekeeping.

`next_action`: route gated fixes to `/work` with the two blocking `consolidate_fix_requests` carrying `review-fixer` (F-01) and `human` (F-02 floor decision). F-01 must be authored in `infiquetra-claude-plugins`, released, and re-synchronized (the portable clients are transforms whose rule intentionally changes no other byte); F-02 must be authored upstream as `timezone.utc` or the catalog floor moved to 3.11 with `ci.yml` and `CHANGELOG.md` updated together. No PR may merge while either remains, but neither blocks the ten-client matrix as a survey — `Coverage is mandatory; passing is not`, and the matrix already binds and validates.

Raw evidence this review ran: `python3 scripts/check_repo.py` — `Repository validation passed.`; `python3 scripts/check_compatibility_matrix.py` — `Compatibility matrix validation passed.` (`23 files da46ca77…` current, two superseded); `python3 -m unittest discover -s tests -v` — `Ran 403 tests in ~16s OK`; `python -m pytest tests -q` — `428 passed, 189 subtests passed`; `smuggled.pyo` attack on live tree — both gates fail; `notes: controller password=hunter2` attack — both `check_repo` and `site_profile.validate_profile` fail naming the property and family, while `digest e3b0c44…` passes; `parse_retry_after` future/past/excessive/bare-bool/empty all reduce correctly and `retry_with_backoff` clamps and falls back; `refuse_repository_output` inside `PACKAGE_ROOT`, inside `docs/`, and with `repository_root_from()==None` all raise `DiscoveryPersistenceError` naming `--repository-root`, and `gitless_walk` under `/private/tmp` does so without monkeypatch.

---

Reviewer: opencode/muse-spark-1.2 (independent, different model/session, no controller priming)
Reviewed revision: `bdaa814b28fcbbcfca0bab08f8f85800a1d6c751` (`orch/orch-2026-08-22-unifi-cycle3`)
Merge-base: `95de0d5fe0a2427ab54cf02489b9b14b56bf9745`
Immutable cycle-1 evidence read but not edited: `docs/reviews/2026-08-22-code-review-cursor-gpt-5.6-sol-xhigh.md` (75da1077…, 33333 bytes), `docs/reviews/2026-08-22-code-review-opencode-muse-spark-1.2-xhigh.md` (5e8a5204…, 18707 bytes), `docs/reviews/2026-08-22-code-review-consensus.md` (58 lines), `docs/reviews/2026-08-22-code-review-cycle2-consensus.md` (53 lines)
Scoring policy: `plugins/saga/references/lens-roster.json` `lens_roster.v1`, `score_scale 0-10`, `acceptance combiner all` (derived_overall>=9.0 + applicable_dimension>=7.0)
Finding policy: `findings-schema.md` fingerprint `path:line:category`, `duplicate_action: merge`, `confidence` anchors 0/25/50/75/100, `autofix_class` 4 values
Validator behaviour: read-only second-opinion per `validator.md` (three questions, conservative bias), programmatic 15-cap not triggered (6 admitted findings), no file writes to reviewed code
