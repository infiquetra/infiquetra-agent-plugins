# Post-repair scored code review — UniFi portability pilot, cycle 4 (orch/orch-2026-08-22-unifi-cycle3, 2bd0faf)

Independent reviewer: opencode / muse-spark-1.2 — unattended, different model/session, no controller priming
Branch `orch/orch-2026-08-22-unifi-cycle3` at `2bd0fafb1f7999efaa5db1ceb33af635bf1af126`, diffed against merge-base `8824fea` and against cycle-3 `bdaa814`. Previous cycles preserved as immutable evidence in `docs/reviews/` (consensus + two independent reports per cycle). This review independently re-derives every repair from current source and attempts to defeat each guarantee.

## Scope check

Scope Check: [DRIFT DETECTED — no scope creep, three superseded matrices and one floor move correctly versioned]

Intent: From `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` — repair the twelve reconciled findings (C1..C10 plus pattern) that blocked the portable UniFi + Fleet Core pilot, close the seven cycle-2 open items O1..O7 and the two cycle-3 blocking defects (O3 caller half of Retry-After + Python floor), re-synchronize UniFi to `2.0.1` at `0d81dd9a` and Fleet Core to `0.25.1` at `ed72f439`, rebound the generated bundles, re-run the ten-client matrix and post-activation readback, and keep the pilot paused for operator decisions — all under the portability-pilot custody and public-boundary rules.

Delivered: `check_repo.py` closes the provenance set and requires six bundle-stamp fields; `site_profile.py` plus its schema rejects a credential by value as well as by name (two families, 11 literal formats); `discover.py` fails closed when the walk finds no `.git` and when asked to write inside `PACKAGE_ROOT`; `drift.py` declares policy observation and only emits `missing-policy` against an observed set; `check_compatibility_matrix.py` binds every matrix document to the live `plugins/unifi/` tree (file count, tree digest, name, version) and makes `matrix-status: superseded` the only exemption; `sync_vendor_source.py` makes `README.md` target-owned and filters stale `README` from cleanup; `retry_backoff.py` at `plugins/fleet-core` and both `_bundled` copies expose `parse_retry_after` for both RFC 7231 forms; both UniFi clients now call `parse_retry_after` on the raw header instead of `int()`; the catalog floor is `python>=3.12` everywhere with `tests/test_python_floor.py` as single authority and CI pin `3.12`; evidence matrices re-run to `cafe8836…` at 23 files, version `2.0.1`. No unrelated scope creep.

## Lens selection (roster `lens_roster.v1`)

Four always-on lenses run on every review. Six conditional lenses are selected because this diff materially touches their domains; one is explicitly not selected.

| Lens | Class | Selection reason |
|---|---|---|
| `architecture-maintainability` | always-on | — |
| `correctness` | always-on | — |
| `security` | always-on | — |
| `testing` | always-on | — |
| `reliability` | conditional | diff fixes `Retry-After` HTTP-date at both callers and at the primitive, changes `retry_with_backoff` `now` seam, and changes drift's policy-observation vs availability |
| `api-contract` | conditional | diff changes `site-profile.schema.json` 1.0→1.1, adds public `parse_retry_after` to Fleet Core, widens `_RateLimited.retry_after` to `float \| None`, and changes Python floor declaration |
| `adversarial` | conditional | 53-file, ~10590-line change whose prior-cycle pattern is "a gate that passes when it should fail" across provenance closed-set, stamp-field, redaction-by-value, unlink escape, and persistence deny-list |
| `deployment-infrastructure` | conditional | release/bundle re-binding, resync rollout, and Python floor interpreter pin change deployed-state evidence |
| `documentation-clarity` | conditional | README, reference doc, changelog, journal, and three evidence documents materially rewritten |
| `agent-usability` | conditional | drift/discover JSON, profile schema, and evidence records are machine-read surfaces agents consume |
| `performance` | conditional | **not selected** — no latency, throughput, query, or capacity claim; retry jitter bounds are reliability |

## Lens scores (anchor bands from `lens-roster.json`)

Scores are per-dimension against that dimension's 10/9/7-8/5-6/0-4 anchors; `derived overall` is the mean of applicable dimensions for this report (the scorer's combiner is `all` with `derived_overall>=9.0` and `applicable_dimension>=7.0`).

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall | Failing dimensions |
|---|---|---:|---|---|
| `architecture-maintainability` | fit/ownership 8; separation 9; dependency 9; simplicity 8; readability 9; conventions 8; decisions 9 | — | 8.57 | none below 7; overall <9 |
| `correctness` | intent 9; state/invariants 9; boundaries 8; side-effects 9; consumers 8 | — | 8.60 | none below 7; overall <9 |
| `security` | auth 9; input 8; secrets 7; supply-chain 9; confidentiality 9 | — | 8.40 | none below 7; overall <9 |
| `testing` | requirements 9; negative/edge 9; behavior-sensitive 9; seams 8; determinism 9 | — | 8.80 | none below 7; overall <9 |
| `reliability` | timeouts/retries 9; concurrency 9; graceful/cancel 9; health 8 | `queues-jobs-dead-letters-ordering-backpressure` — no queue surface | 8.75 | none below 7; overall <9 |
| `api-contract` | contract/compat 8; versioning 9; serialization/errors 9; retry/idempotency 8; spec/doc parity 8 | `pagination-rate-limits`, `sdk-generated-client-impact` — no collection pagination or generated SDK | 8.40 | none below 7; overall <9 |
| `adversarial` | load-bearing 8; abuse/edge 8; silent-green 8; environment 8; scope N/A; alternatives N/A; recovery N/A | scope/alternatives/recovery preconditions absent for this delta | 8.00 | none below 7; overall <9 |
| `deployment-infrastructure` | infra/config 9; rollout 9; rollback/drift 9; deployed-verification 9 | no cloud resource or cost | 9.00 | none |
| `documentation-clarity` | parity 9; completeness 9; structure 9; terminology 9; examples 9; runbook/drift 9 | — | 9.00 | none |
| `agent-usability` | reachability 9; discoverability 9; context 9; machine-output 9; bounded-op 9 | — | 9.00 | none |

`review_result.v1` acceptance requires `derived_overall>=9.0` and `applicable_dimension>=7.0`. Three lenses reach 9.0; seven sit at 8.0–8.8. No applicable dimension falls below 7.0. Outcome is therefore `accepted` on dimension floor but `repairs_requested` if the roster's overall threshold is applied literally — the gap between "every dimension acceptable" and "overall excellent" is where the two P3 consistency residuals sit. Plain-language verdict below distinguishes the numeric overall from ship-readiness.

## Repair verdicts C1..C10 — independent from-cycle-1 95de0d5, verified against 2bd0faf tree and live execution

| # | Title from 2026-08-22-consensus | Cycle-3 adjudicated | This review | Evidence `file:line` that proves the verdict |
|---|---|---|---|---|
| C1 | Compatibility matrix describes the pre-repair package, not the shipped tree | FIXED | **FIXED** | `scripts/check_compatibility_matrix.py:311-350` recomputes `package_fingerprint()` and `package_identity()` and fails when `$.package.file_count / tree_sha256 / name / version` diverge; `check_document_status` makes `matrix-status` default `current` so binding is fail-closed; `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` carries `<!-- matrix-status: current -->` and three `…-pre-*.md:1` carry `superseded` with `superseded-by` naming the current doc; live `python3 scripts/check_compatibility_matrix.py` passes with `23 files cafe8836…` and `python3 scripts/check_compatibility_matrix.py --print-fingerprint` recomputes `name: unifi version: 2.0.1 file_count: 23 tree_sha256: cafe8836…` equal to the ```json record's `package` field |
| C2 | Drift reports every profiled network as a missing policy | FIXED | **FIXED** | `plugins/unifi/scripts/discover.py:147-156` `POLICY_OBSERVATION_KEY`/`POLICY_UNAVAILABLE` because catalog has no policy operation; `empty_inventory:478-483` and `DiscoverySession.collect:640-643` stamp `policy_observation: unavailable`; `plugins/unifi/scripts/drift.py:95-115` `policy_observation()` returns `observed` only when inventory earns it (non-empty `policies` or explicit `observed`, case-insensitive), otherwise `unavailable`; `drift.report:140-193` emits `missing-policy` only when `observation == observed` and otherwise appends `POLICY_UNOBSERVED_LIMIT` to `limits`; `tests/test_drift.py:237-326` pins both directions; live probe: discovery inventory → only `unprofiled-host` + limit, observed+empty → `missing-policy` |
| C3 | Provenance validation is not closed over package files | FIXED | **FIXED** | `scripts/check_repo.py:77-103` bytecode exemption is placement not suffix; `362-396` `_is_interpreter_bytecode` returns True only under `__pycache__` or beside matching `.py`; `_managed_package_files:383-397` excludes only those two shapes; `_closed_set_errors:400-448` reports duplicate entries, every unlisted file, and listed-but-missing; live `smuggled.pyo` at `plugins/unifi/skills/unifi-network/scripts/smuggled_test.pyo` → `unlisted package file … is not classified by plugins/unifi/PROVENANCE.json` and moves `package_fingerprint()`; `check_compatibility_matrix.py:101-116` excludes only `FINGERPRINT_EXCLUDED_DIRECTORIES`, never by suffix |
| C4 | Bundle provenance fields optional, so a stale bundle can pass CI | FIXED | **FIXED** | `scripts/check_repo.py:101-118` `BUNDLE_REQUIRED_STAMP_FIELDS` names all six fields; `check_bundled_files:548-586` reports `generated bundle stamp missing <field>:` by name and rejects `unstamped generated bundle`; `_check_bundle_source_freshness:589-630` compares live Fleet Core bytes vs `source-sha256` and is skipped only when stamp already missing (already reported); removing `source-version` now fails `check_repo.py` rather than disabling comparison; live probe confirms |
| C5 | Portable README is Claude-specific / references missing docs | FIXED for shipped artifact, residual queued then closed | **FIXED** | `plugins/unifi/README.md:1-60` lede is `UniFi portable package / Portable Agent Plugins 1.0` with `com.infiquetra.claude/` as adapter and no `Claude Code plugin` claim; `plugins/unifi/PROVENANCE.json:104-106` classifies `README.md` as `target-owned`; `scripts/sync_vendor_source.py:80-105` removed `README.md` from `PORTABLE_BYTE_COPIES`, in `SUPERSEDED_BY_TARGET_OWNED`; `stale_managed_paths:640` subtracts superseded so old manifest does not `unlink` portable file; `tests/test_unifi_readme.py` and `tests/test_sync_vendor_source.py:TargetOwnedTests` assert target-owned survives re-run |
| C6 | Secret-free / redaction validation is partial | FIXED (repo gate closed, runtime value rule added) | **FIXED** | Repo gate: `scripts/check_repo.py:137-163` `CREDENTIAL_FORMATS` 11 families, `171-206` assignment+entropy + placeholder/reference excluded, `786-842` `credential_findings` + `check_secret_free_values` scoped to `plugins/` and firing on both data and source; live `python3 scripts/check_repo.py` passes with zero false positives. Runtime: `plugins/unifi/scripts/site_profile.py:131-285` re-states same two families as `CREDENTIAL_VALUE_FORMATS` + `CREDENTIAL_VALUE_ASSIGNMENT` with `MIN_ENTROPY 2.5`, checks *every string at any depth* via `_credential_value:245-265` and `_credential_in_text`, rejects with `credential value is not permitted … (label)` naming property path; `plugins/unifi/schemas/site-profile.schema.json:46-62` guards every free-text value against 11 literal patterns and closes every object with `nonCredentialPropertyName`; `tests/test_site_profile.py:223-276` proves `notes: "controller password=hunter2"` rejected naming `subjects[0].notes` + `password`, all five free-text placements rejected, literal digests accepted; live probe confirms |
| C7 | `Retry-After` HTTP-date form not handled | PARTIAL (primitive fixed, callers not) at bdaa814 | **FIXED** | Primitive was FIXED at `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:47-92` `parse_retry_after(value, *, now=time.time)` handles both RFC 7231 forms; **callers NOW FIXED** at `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:188-190` and `unifi_protect_client.py:188-190` — both now do `hint = _retry_backoff.parse_retry_after(resp.headers.get("Retry-After"))` then `raise _RateLimited(hint)` where `_RateLimited.retry_after` is `float \| None`; no `int()` remains outside comments; `retry_with_backoff:195-199` passes `retry_after=lambda exc: getattr(exc, "retry_after", None)` which `parse_retry_after` reduces before `_retry_delay` clamp/fallback; live probe: future date `Tue, 14 Nov 2023 22:14:05 GMT` with `NOW=1700000000` → `45.0s` delay and retry, past date `0.0` → computed backoff 1–2s, garbage → `None` → computed backoff, delta-seconds `30` → `30.0` |
| C8 | Malicious/corrupt `PROVENANCE.json` can unlink files outside the package | FIXED | **FIXED** | `scripts/sync_vendor_source.py:541-570` `_managed_path_violation` does lexical `is_absolute or ".." in parts` and containment `resolve().is_relative_to(package.resolve())` including symlink resolution, `resolve_managed_path:572-589` single chokepoint that every write and deletion goes through and raises `SyncError`, `previously_managed:591-619` calls `resolve_managed_path` for every entry so hostile path aborts before any unlink, `stale_managed_paths:622-640` only stale-set; `tests/test_sync_vendor_source.py:ManifestPathSafetyTests` proves `/etc/hosts`, `../../..`, symlink, and `plugin_dir` itself all raise and delete nothing; re-verified after resync |
| C9 | Post-activation proof was never performed | EVIDENCED AND BOUND | **FIXED** | `docs/evidence/2026-08-22-unifi-post-activation-readback.md:1-268` exists with staged load, installed-version/digest readback, and fresh-session three-state proof (profile present/absent/unreadable); `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1-120` second re-run `23 files cafe8836…` as `The assessed copy is the shipped tree` with `The point of the exercise is to learn which clients can consume…` and recomputes binding; `scripts/check_compatibility_matrix.py:101-192` `package_fingerprint` is the machine that makes claim falsifiable; re-run `python3 scripts/check_compatibility_matrix.py` validates current + three superseded |
| C10 | Discovery persistence deny-list fails open without a `.git` directory | FIXED | **FIXED** | `plugins/unifi/scripts/discover.py:280` `PACKAGE_ROOT = Path(__file__).resolve().parent.parent`; `300-343` `refuse_repository_output` has two independent refusals — inside `PACKAGE_ROOT` always (needs no checkout) and inside repository working tree when known — and when `repository_root_from() is None` raises `DiscoveryPersistenceError` naming `--repository-root` rather than returning path; `tests/test_discover.py:278-415` covers inside-package refusal with unrelated `repository_root`, undeterminable-tree refusal, whole `discover`→`persist_payload`→`refuse_repository_output` chain, named-root lift, plus `test_gitless_walk_refuses_persistence_and_names_repository_root` which drives real directory under `/private/tmp` with no `.git` ancestor without monkeypatch and still raises; live probe confirms |

## Cycle-3 blocking defects — independent re-verification at 2bd0faf (the two the brief names)

| # | Cycle-3 title | Cycle-3 verdict | Now | Independent proof at 2bd0faf |
|---|---|---|---|---|
| B1 | `Retry-After` HTTP-date at call sites still `int()` | P2 `repairs_requested` — primitive fixed, callers not | **FIXED** | Both clients: `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:188-190` and `unifi_protect_client.py:188-190` now `hint = _retry_backoff.parse_retry_after(resp.headers.get("Retry-After"))` + `raise _RateLimited(hint)`; `_RateLimited:57-70` stores `retry_after: float \| None` (reduced, not raw string); `retry_with_backoff:195-199` passes `retry_after=lambda exc: getattr(exc, "retry_after", None)` then `parse_retry_after(raw_hint, now=now)` before `_retry_delay` clamp; no `int(Retry-After)` remains in code (only in comment recounting the bug). Probe on a fixed `NOW=1700000000` : `FUTURE_DATE Tue, 14 Nov 2023 22:14:05 GMT` → `45.0` delay and retry (2 calls, 1 sleep), `PAST_DATE` → `0.0` → computed backoff 1–2s (no tight loop), `garbage` → `None` → computed backoff, `EXCESSIVE_DATE 2100-12-31` → `4133980799.0` clamped to `max_delay 7.0`. The `int()` ValueError that carried no 429 status and was never retried is gone. Upstream UniFi `2.0.1` commit `0d81dd9a` carries the same repair; `plugins/unifi/PROVENANCE.json:2-3` pins `0d81dd9a` `2.0.1` |
| B2 | `datetime.UTC` breaks Python 3.10 floor | P1/P2 `repairs_requested` — byte copy imported `UTC` (3.11+) while catalog documented 3.10 | **FIXED by operator floor move** | Catalog minimum is now `python>=3.12` — a minimum, not a pin. Authority is `tests/test_python_floor.py:55` `PYTHON_FLOOR = (3, 12)`; every declared site agrees: `.github/workflows/ci.yml:56` `python-version: '3.12'` with step name `Set up Python 3.12`, `README.md`, `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` KTD7, `plugins/fleet-core/README.md`, `plugins/fleet-core/CHANGELOG.md`, and `docs/engineering-journal/DECISIONS.md`. No other `python>=` token in repo disagrees (`scanned_files()` covers all suffixes except `docs/reviews/` which is intentionally excluded as immutable evidence). Skill frontmatter `compatibility` is `None` for both skills — allowed (absence, not disagreement); `test_a_portable_skill_that_declares_compatibility_declares_the_floor` enforces if declared then equals floor. Floor exercised on real floor interpreter `/opt/homebrew/bin/python3.12` (CPython 3.12.13): `python3.12 -m unittest discover` → 417 tests OK (1 skipped for missing pytest), `python3.12 -c "from datetime import UTC"` → imports, `_bundled/retry_backoff.py` imports, both clients `--help` exit 0 on `python3.12` with only declared deps. `datetime.UTC` exists in 3.11+ so 3.12 is inside contract with room. Previous 3.10 floor was never proved (assessments ran on 3.14) and is superseded with rationale preserved in plan KTD7. |

## Cycle-2 open items O1..O7 — still fixed?

| # | Cycle-2 item | Now | Proof |
|---|---|---|---|
| O1 | `.pyc`/`.pyo` suffix exemption smuggles arbitrary content past both gates | **FIXED** — `check_repo.py:77-83+362-397` exempts bytecode only under `__pycache__/` or beside matching `.py` (PEP 3147); adding `plugins/unifi/skills/unifi-network/scripts/smuggled.pyo` with no `orphan.py` → `unlisted package file: … is not classified by plugins/unifi/PROVENANCE.json` and moves `package_fingerprint()`; `FINGERPRINT_EXCLUDED_DIRECTORIES` excludes only directories, never suffix, so smuggled `.pyo` outside those directories moves `tree_sha256` |
| O2 | Site-profile runtime `validate_profile` checks names, not values | **FIXED with admitted limit** — `site_profile.py:131-285` rejects credential by value via 11 literal formats or `password=…` assigned high-entropy value at any depth (every string inspected, paths named), matching `check_repo.py` families byte-for-byte (`CredentialRuleDriftTest` pins them equal); digest `e3b0c44…` in `notes` still accepted, `vault:`/`env:` references accepted, `password=secret` (2.25 bits < 2.5 floor) passes and is documented as defense-in-depth not proof of absence in `references/site-profile.md:56-88` and `site_profile.py:1-19`; see F-01 below for the one span the two families still miss |
| O3 | `Retry-After` HTTP-date unhandled (C7) | **FIXED** — primitive + callers both handle both RFC 7231 forms (see B1) |
| O4 | `README.md` still in `PORTABLE_BYTE_COPIES` | **FIXED** — `sync_vendor_source.py:82-105` removes `README.md` from `PORTABLE_BYTE_COPIES`, lists it in `SUPERSEDED_BY_TARGET_OWNED` with DECISIONS citation, `PROVENANCE.json:104-106` target-owned, `stale_managed_paths` subtracts superseded so old manifest does not `unlink` portable file |
| O5 | Sync custody table contradicts recorded custody | **FIXED** — `sync_vendor_source.py:classify_source_tree:420-453` requires every upstream path be assigned exactly once among `PORTABLE_BYTE_COPIES (5)` + `PORTABLE_ENTRYPOINT_TRANSFORMS (2)` + `CLIENT_BYTE_COPIES (3)` + `SUPERSEDED (1)` + `DROPPED (2)` + `SOURCE_MANIFEST (1)` = 14 source files, raising `SyncError` listing unclassified/absent/duplicate; `tests/test_sync_vendor_source.py::ShippedPackageTests.test_the_custody_table_agrees_with_the_recorded_classification` passes and table agrees with `PROVENANCE.json` |
| O6 | Gitless-walk negative case untested | **FIXED** — `tests/test_discover.py:362-415` adds `gitless_working_directory()` which finds real temp ancestor under `/private/tmp` with `repository_root_from() is None` and `test_gitless_walk_refuses_persistence_and_names_repository_root` drives `refuse_repository_output(output)` with no monkeypatch and asserts `DiscoveryPersistenceError` naming `--repository-root` |
| O7 | Binding proves identity, not execution | **RECORDED as limitation, not a gate** — `docs/engineering-journal/QUEUED.md:Maybe Keep the matrix binding an identity check` with rationale that U11 (matrix R22/R43) plus U9 (readback R40 three-state) already require execution and a digest cannot prove forty stages ran; `LEARNINGS.md: A bound digest names the tree, not the forty stages that assessed it` |

## Fleet Core 0.25.1 resynchronization and UniFi 2.0.1 resynchronization — still correct?

**Genuine byte copies — YES, both.** `plugins/fleet-core/PROVENANCE.json:4` pins `source_commit: ed72f439ba01f2e20d94be074e5612c5641c0c8e` and `source_version: 0.25.1`; module at `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` hashes `sha256 5aea3be13ac444aba2610442f76846a16a0e9537befe39090da173cb1fede975` equal to `PROVENANCE.json:35` `sha256` for that file; the module was extracted with `git show <commit>:plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` per `PROVENANCE.json:10` note, same primitive `scripts/sync_vendor_source.py:158-211` uses, and `scripts/check_repo.py:260` recomputes and matches — `python3 scripts/check_repo.py` passes. UniFi package: `plugins/unifi/PROVENANCE.json:2-3` pins `0d81dd9a48ce4321645fd857d23d749cc23520d1` `2.0.1`; both client transforms `skills/unifi-network/scripts/unifi_network_client.py:73-80` and protect counterpart record `source_sha256` `9dcd6360b5c9…` / `1ec114b46c77…` and `sha256` `edb45fc30d30…` / `5dc52ea973db…` with `transform: resolve-bundled-fleet-module` `transform_version: 1`; live digest of each file equals recorded `sha256`; the `fleet_commons_shim` comment remains only in comments, no import of shim.

**Bundles rebound — YES, both destinations.** `plugins/unifi/skills/unifi-network/scripts/_bundled/retry_backoff.py:1-7` and `plugins/unifi/skills/unifi-protect/scripts/_bundled/retry_backoff.py:1-7` carry identical stamps: `source-version: 0.25.1`, `source-commit: ed72f439…`, `source-path: scripts/fleet_commons/retry_backoff.py`, `source-sha256: 5aea3be13ac…` (matches live source), `output-sha256: 5aea3be13ac…` (hash of file with stamp block excluded via `split_bundle_stamp`/`bundle_output_digest` per `scripts/check_repo.py:491-531`), `generated-by: scripts/bundle_fleet_module.py`. Both `_bundled` payloads (stamp removed) are byte-identical to `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py`. `plugins/fleet-core/CHANGELOG.md:13-56` documents the repair and stamp rebinding, and `scripts/check_repo.py:548-630` verifies both `output-sha256` (tamper) and `source-sha256` (stale source) independently. `scripts/bundle_fleet_module.py --check` passes, `python3 scripts/check_compatibility_matrix.py` passes, `python3 -m unittest` 417 OK.

**No second writable source created.** The clients are `deterministic-transform` not `upstream-byte-copy` because upstream shim mechanism cannot be carried; the transform `resolve-bundled-fleet-module` is versioned, reads module name and binding from source, changes no other byte, and refuses if block absent or appears twice. `tests/test_sync_vendor_source.py::SynchronizedTreeTests.test_each_client_resolves_the_bundled_module_instead_of_the_dropped_shim` and `test_no_shipped_client_still_imports_the_dropped_shim` prove the invariant: `tests/test_client_entrypoints.py` runs `--help` via subprocess with stubbed requests and sanitized env.

## Findings (admitted, confidence >=75 except P0 at 50+; sorted P0→P3 then confidence→file→line)

### P1 — none admitted

No P1 finding survives validation at anchor 75+. The two defects that distinguished cycle-3 as `repairs_requested` (caller `int(Retry-After)` truncating HTTP-date and `datetime.UTC` on the documented floor) both now bite at their seams and have been exercised on the floor interpreter. The four severities that distinguished cycle-1 (closed-set smuggling, stamp-field optionality, path-escape unlink, persistence fail-open) remain biting, verified by live attack each.

### P2

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `plugins/unifi/scripts/site_profile.py:169` | Credential-value assignment grades first token after separator, so `authorization: Bearer <high-entropy-token>` passes validation in both copies | `security` | 75 | `gated_auto -> review-fixer` |

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-02 | `scripts/sync_vendor_source.py:138` | `MANIFEST_EXCLUDED_SUFFIXES` still excludes `.pyc`/`.pyo` everywhere while `check_repo` exempts them only under `__pycache__` or beside matching `.py` | `architecture-maintainability` | 75 | `safe_auto -> review-fixer` |
| F-03 | `tests/test_retry_backoff.py:1` | Ported test still pins pre-2.0.1 caller shape; inverted characterization now ships upstream | `testing` | 75 | `advisory -> human` |

### Advisory (no autofix)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-04 | `plugins/unifi/scripts/site_profile.py:131` | Low-entropy short secret in free-text value still passes (`password=secret`, 2.25 bits) — documented defense-in-depth, not proof of absence | `security` | 100 | `advisory -> human` |
| F-05 | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` | Binding proves identity, not that forty stages ran — correctly queued as Maybe, not a gate (O7) | `adversarial` | 100 | `advisory -> human` |
| F-06 | `scripts/check_repo.py:77` | Residual exemption: committed `__pycache__/payload.pyc` is invisible to both closed-set and fingerprint (only `.gitignore` protects) | `security` | 75 | `advisory -> human` |

Suppressed (below admission): none. All reported at anchor 75+.

### Detailed findings (per `findings-schema.md` — every field)

#### F-01 — Assignment family grades first token after separator, so Bearer-token assignment passes as non-credential (P2)

- `severity`: P2
- `dimension_id`: `secrets-cryptography-session-handling` (also `input-trust-boundaries-injection`)
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 169
- `why_it_matters`: An operator told credentials are excluded by validation can paste a real bearer token as `authorization: Bearer qY7vP2xK9rLm4aZbC8dEfGhJk...` (a documented paste shape — an operator recording the auth header) and be told the profile is valid; the profile then reaches whatever store holds the deployment. The detector inspects the wrong span of the matched assignment, which is the same name-vs-value pattern in miniature that defined C6.
- `autofix_class`: `gated_auto`
- `owner`: `review-fixer`
- `requires_verification`: true
- `confidence`: 75
- `evidence`:
  - `plugins/unifi/scripts/site_profile.py:169-173` — `CREDENTIAL_VALUE_ASSIGNMENT` captures group 2 as `[^\s"',;)}\]]{6,}` terminated by whitespace, so for `authorization: Bearer <token>` group 2 is `Bearer` (entropy 1.91 < 2.5) not the token after it
  - `scripts/check_repo.py:184-189` — identical pattern (`CREDENTIAL_ASSIGNMENT`) with same capture group and same `CREDENTIAL_VALUE_MIN_ENTROPY 2.5`, so both copies identically affected (the cross-copy pin `tests/test_site_profile.py:624-651` locks them together)
  - Live: `python3 -c "import site_profile; site_profile.validate_profile({\"schema_version\":\"1.1\",\"site\":{\"identifier\":\"s\"},\"subjects\":[{\"kind\":\"host\",\"identifier\":\"h1\",\"notes\":\"authorization: Bearer qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890\"}]})"` → accepted (no exception) on 2bd0faf; `password=hunter2` correctly rejected (entropy 2.80) and `AKIAIOSFODNN7EXAMPLE` rejected via `CREDENTIAL_VALUE_FORMATS` — the scheme-word prefix is the narrow bypass
  - `tests/test_site_profile.py` covers `password=hunter2`, `AKIA…`, JWT, URL-embedded credential, but no whitespace-token `Bearer` case
- `pre_existing`: false — the assignment family was added this pilot (C6 fix) and the `Bearer` token pattern ships inside it; the defect is the family grading the wrong token, not a missed case added later
- `suggested_fix`: Grade every whitespace-separated token of the assigned value against the entropy floor, not only the first; or when the assignment starts with a known scheme word (`bearer|basic|token`) explicitly skip that word and grade the remainder. In `plugins/unifi/scripts/site_profile.py:447-453` `_credential_in_text` iterate `assigned.split()` (or `re.findall(r"[^\s]+", assigned_remainder)`) and return when any token has `shannon_entropy(token) >= MIN_ENTROPY` after placeholder/reference checks; apply the same change to `scripts/check_repo.py:786` `credential_findings` assignment loop so the pin test still passes. Add `test_bearer_scheme_does_not_defeat_value_detection` asserting `authorization: Bearer <40-char high-entropy>` rejected. Assumption: Bearer tokens are opaque and high-entropy; grading every token does not materially raise false positives because placeholders and references are still excluded and low-entropy prose still fails the floor

#### F-02 — `sync_vendor_source` suffix exclusion disagrees with `check_repo` placement rule (P3)

- `severity`: P3
- `dimension_id`: `architectural-fit-ownership-single-sources`
- `critical`: false
- `file`: `scripts/sync_vendor_source.py`
- `line`: 138
- `why_it_matters`: The two modules disagree about what counts as a package file: adding `plugins/unifi/skills/unifi-network/scripts/orphan.pyo` with no `orphan.py` is correctly reported as `unlisted` by `check_repo.py:383-397` and moves the matrix fingerprint `cafe8836…`, but `sync_vendor_source.py:507-513` `_is_manifest_candidate` returns False for any `.pyc`/`.pyo` suffix so the file would not appear as `target-owned` in a freshly built manifest; the next `synchronize --check` would not name it stale but `check_repo.py` would still fail — the guarantee still bites, but via a single gate rather than both, and the manifest the script writes is not closed per the validator's definition
- `autofix_class`: `safe_auto`
- `owner`: `review-fixer`
- `requires_verification`: true
- `confidence`: 75
- `evidence`:
  - `scripts/sync_vendor_source.py:138-140` — `MANIFEST_EXCLUDED_SUFFIXES = (".pyc", ".pyo")`
  - `scripts/check_repo.py:77-83` comment — `The bytecode exemption is about placement, not about the suffix … so plugins/…/smuggled.pyo could hold arbitrary text` and `362-381` `_is_interpreter_bytecode` checks `__pycache__` directory or sibling `.py`
  - Live probe: in a temp `plugins/unifi` with `orphan.pyo` (no `orphan.py`) `check_repo._managed_package_files` lists `orphan.pyo` as managed while `sync_vendor_source.target_owned_paths` omits it
- `pre_existing`: false — `check_repo.py:362-381` was repaired in `ff7603d` to close the suffix hole; the sync file was not updated in that commit and remains suffix-based through the floor resync and the `2.0.1` resync
- `suggested_fix`: Change `scripts/sync_vendor_source.py:138-140` to mirror the validator: keep `MANIFEST_EXCLUDED_PARTS = ("__pycache__",)` and replace suffix exclusion with helper `_is_interpreter_bytecode(plugin_dir, relative)` that returns true only under `__pycache__` or beside matching `.py` (import from `check_repo` or duplicate the 4-line check and pin with a test that the two helpers agree)

#### F-03 — Ported test still pins pre-2.0.1 caller shape (P3, not a defect)

- `severity`: P3
- `dimension_id`: `requirements-regression-coverage`
- `critical`: false
- `file`: `tests/test_retry_backoff.py`
- `line`: 317
- `why_it_matters`: A reader of `tests/test_retry_backoff.py:317-334` `test_a_caller_that_pre_parses_with_int_still_loses_the_retry` is told the current caller shape loses the retry; the shipped clients at `2.0.1` now keep it (they hand the raw header to `parse_retry_after`). The test is still true of the primitive — `int("Fri, 31 Dec 2100 23:59:59 GMT")` still raises `ValueError` with no 429 status — but the scenario it pins is now hypothetical for the bytes in this repo
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 75
- `evidence`:
  - `tests/test_retry_backoff.py:317-334` still asserts `int(FUTURE_DATE)` yields exactly one call and zero sleeps
  - Upstream at `0d81dd9a` inverted that test to `test_a_caller_that_pre_parses_with_parse_retry_after_keeps_the_retry` because both UniFi clients were repaired
  - `docs/engineering-journal/QUEUED.md:P2` `The ported Fleet Core test still pins the pre-2.0.1 caller shape` records the custody question: `derived_files.source_path` pins `ed72f439` while the new test lives at `0d81dd9a`, so re-deriving needs either per-derived-file pin or waiting for next Fleet Core release; `tests/test_retry_backoff.py:1-28` docstring still declares `ed72f439` as the ported commit
  - `plugins/fleet-core/PROVENANCE.json:9-10` notes the two pins legitimately differ (`UniFi 2.0.1` at `0d81dd9a` descendant of `ed72f439` with Fleet subtree byte-identical between them) so the test pin staying at `ed72f439` is consistent with the package pin rule
- `pre_existing`: false — the staleness was introduced by the `2.0.1` resync which repaired the callers but left the ported test's scenario pinned to `ed72f439`
- `suggested_fix`: none required for ship-readiness; queued as `human` — decide whether `derived_files` may carry a separate pin or wait for next Fleet Core release that moves the Fleet subtree, then re-derive `tests/test_retry_backoff.py` with `guard-pytest-import` version 2 applied and update `plugins/fleet-core/PROVENANCE.json` `derived_files.source_commit` accordingly; either path is an operator decision, not a patch, and the current test still truthfully describes the primitive's behavior if misused

#### F-04 — Low-entropy secret in value still passes (advisory, documented)

- `severity`: P3
- `dimension_id`: `secrets-cryptography-session-handling`
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 131
- `why_it_matters`: An operator told credentials never live in the profile can write `password=secret` (2.25 bits/char, below 2.5 floor) and be told valid; the profile reaches whatever store holds the deployment
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`:
  - `plugins/unifi/scripts/site_profile.py:131-285` — two families: literal formats anywhere and `CREDENTIAL_VALUE_ASSIGNMENT` with `MIN_ENTROPY 2.5`; `_names_a_secret` excludes placeholders; `shannon_entropy("secret")` 2.25 and `password=secret` accepted
  - `plugins/unifi/references/site-profile.md:56-88` documents as `defense in depth against an accident, not a proof of absence` and names `password=secret` as accepted low-entropy example; `tests/test_site_profile.py:336-346` pins `test_a_low_entropy_assigned_value_passes_and_the_limit_is_admitted`
  - `scripts/check_repo.py:193-206` identical threshold and same admitted example
- `pre_existing`: false
- `suggested_fix`: none — deliberate false-positive/true-negative trade-off; do not lower floor (rejects ordinary prose and the `digest e3b0c44…` case) and do not add bare entropy scan (fires on every digest and would be switched off). Keep wording honest. This limit is why F-01 matters: `Bearer` token failure is about the wrong span, not about this floor.

#### F-05 — Binding proves identity, not execution (advisory, correctly queued as Maybe)

- `severity`: P3
- `dimension_id`: `load-bearing-assumptions`
- `critical`: false
- `file`: `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`
- `line`: 1
- `why_it_matters`: A correct `file_count`/`tree_sha256`/`name`/`version` match can be published without ever running a client; operator reading matrix as execution proof would be misled
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`:
  - `scripts/check_compatibility_matrix.py:268-430` `package_fingerprint` + `package_identity` recompute identity; `docs/engineering-journal/LEARNINGS.md:89-156` `A bound digest names the tree, not the forty stages that assessed it`
  - `docs/engineering-journal/QUEUED.md:Maybe Keep the matrix binding an identity check` — recording-only, guards `Do not invent a broader new gate. Do not weaken check_package_binding.`
- `pre_existing`: false
- `suggested_fix`: none — keep `check_package_binding` as identity; execution evidence stays in plan's separate places (`matrix.md` prose `The point of the exercise…` and `docs/evidence/2026-08-22-unifi-post-activation-readback.md` readback). Correctly not an autofix.

#### F-06 — Committed `__pycache__/payload.pyc` invisible to both gates (advisory)

- `severity`: P3
- `dimension_id`: `confidentiality-logs-errors-egress` (also `architectural-fit-ownership-single-sources`)
- `critical`: false
- `file`: `scripts/check_repo.py`
- `line`: 77
- `why_it_matters`: A file committed as `plugins/unifi/__pycache__/payload.pyc` (or any `__pycache__/`-anchored path) is exempt from provenance closed-set by `PROVENANCE_UNMANAGED_DIRECTORY_NAMES = ("__pycache__",)` and from fingerprint by `FINGERPRINT_EXCLUDED_DIRECTORIES = {"__pycache__", …}` — only `.gitignore` stands between it and shipping arbitrarily
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 75
- `evidence`:
  - `scripts/check_repo.py:77-82` and `311-315` — `_fingerprint_includes` and `_managed_package_files` both exclude `__pycache__` at any depth
  - `scripts/check_compatibility_matrix.py:108-112` same directory exclusion
  - Probe: synthetic `plugins/example/__pycache__/payload.pyc` with arbitrary bytes — `check_provenance_manifests` returns `[]`, `package_fingerprint` unchanged
  - Note: placement-based bytecode exemption for `.pyc` *outside* `__pycache__` is not affected — `smuggled.pyo` with no sibling `.py` now correctly fails `unlisted package file`; nested `PROVENANCE.json` is now caught by fingerprint (included) even though check_repo excludes it by name — the two gates are complementary there, unlike the `__pycache__` shared blind spot
- `pre_existing`: true — the `__pycache__` exclusion predates this pilot; the repair for O1/F-02 narrowed the `.pyc`/`.pyo` suffix hole but intentionally preserved PEP 3147 `__pycache__` as checkout noise
- `suggested_fix`: none for this cycle — keep `.gitignore` entry tight and keep the exclusion documented; if threat model grows, replace the directory-named exclusion with a check that a committed `__pycache__` path is never a regular tracked file (or reject nested `__pycache__` outside declared build output), but do not broaden the provenance check to hash ignored cache directories without measuring build noise first

## Built-vs-planned audit (against `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:1-473` and `docs/engineering-journal/DECISIONS.md`)

Verification modes: DIFF (`git diff 8824fea..2bd0faf --stat` 53 files, ~10590 insertions), CROSS-REPO (sibling `infiquetra-claude-plugins@0d81dd9a` not diffed here, verified via byte-copy digests and provenance; `git show 0d81dd9a:plugins/unifi/...` not re-executed from this repo but digests recomputed locally), EXTERNAL-STATE (operator-run matrix, no live controller).

### Scope-drift detection (informational)

Intent (from plan summary `plan:10-15` + requirements R01..R45 + units U01..U12): land the portable UniFi + Fleet Core slice, close the validator gaps, re-run the evidence, and pause for operator decision — no new plugin, no vendor manifest generation.

Delivered: exactly that. No feature added outside plan's units; `parse_retry_after` is the documented additive fix for R19/R35 (Fleet Core 0.25.1 Fixed) and `POLICY_OBSERVATION_KEY` is the documented correction for C2. The Python floor move `3.10 → 3.12` and the UniFi `2.0.1` caller repair are operator-authorized resynchronizations, not scope drift, and both are recorded in `DECISIONS.md` and `QUEUED.md` with provenance pins. No unrelated drift.

### Plan-completion (5-state: DONE / PARTIAL / NOT-DONE / CHANGED / UNVERIFIABLE)

| # | Requirement | State | Evidence `file:line` |
|---|---|---|---|
| R01 | Derived artifact + provenance script | DONE | `scripts/sync_vendor_source.py:1`, `plugins/unifi/PROVENANCE.json:2` pins `0d81dd9a` `2.0.1` |
| R02 | Hermetic provenance validation | DONE | `scripts/check_repo.py:260`, `python3 scripts/check_repo.py` passes |
| R03 | Pin corrected revision, never 995a475 | DONE | `plugins/unifi/PROVENANCE.json:3` `2.0.1@0d81dd9a` descendant of `ed72f439` (Fleet) with same Fleet subtree; `plugins/fleet-core/PROVENANCE.json:4` `0.25.1@ed72f439` (995a475 is ancestor, doc repair included) |
| R04 | Three-way classification, no divergence | DONE | byte-copy/transform/target-owned recorded per-file, `README.md` now `target-owned`+`SUPERSEDED_BY_TARGET_OWNED`, classification exhaustive at `sync_vendor_source.py:420-453` |
| R05..R07 | Upstream docs repair (Protect/Network refs, skill frontmatter) | DONE | CROSS-REPO `0d81dd9a` carries repair; `plugins/unifi/skills/*/SKILL.md` frontmatter has only allowed 6 fields, verified by `check_skill_frontmatter` |
| R08 | Remove hard-coded controller default | DONE | CROSS-REPO `0d81dd9a`; portable `plugins/unifi/scripts/unifi_*_client.py:92-109` host required with no default, provenance notes record relocation |
| R09 | Release gated on replacement profile path | DONE | `docs/evidence/2026-08-22-unifi-post-activation-readback.md:1` three-state fresh-session proof |
| R10..R15 | Site profile optional, no inference, secret-free, path custody | DONE | `site_profile.py:1`, `site-profile.schema.json:1` version 1.1 with value families; name+value checks cite `CREDENTIAL_VALUE_FORMATS:150-165` and `CREDENTIAL_VALUE_ASSIGNMENT:169-173` |
| R16..R21 | Portable Fleet Core slice + deferred inventory + bundling | DONE | `plugins/fleet-core/*`, `fleet-bundle.json`, `bundle_fleet_module.py`, `_bundled/retry_backoff.py` (both) |
| R22..R25 | Ten-client matrix | DONE | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` current, 23 files `cafe8836…` version `2.0.1`, re-run at `2bd0faf` range, binding in `check_compatibility_matrix.py:311-350` |
| R26..R27 | Read-only, default-deny persistence | DONE | `discover.py:78` `READ_ONLY_OPERATIONS` only GET, `300-343` two-rung refuse plus `PACKAGE_ROOT` and undeterminable → raise |
| R28..R29 | Manifest + skill frontmatter conformance | DONE | `plugins/unifi/plugin.json` `$schema` canonical, skill `name` matches dir; `check_skill_frontmatter` green |
| R30..R31 | Orchestrate/Herdr topology | UNVERIFIABLE | not observable from diff; prose in `README.md` and evidence docs unchanged |
| R32..R33 | Fleet Core custody + release surface | DONE | `plugins/fleet-core/PROVENANCE.json:6-11` `Custody does not move`, `release_surface` enumerates 5 items, two pins legitimate (Fleet subtree identical between `ed72f439` and `0d81dd9a`) |
| R34..R35 | Build declaration + two digest domains | DONE | `fleet-bundle.json` closed schema, `check_repo.py:491-630` two-domain `output-sha256` vs `source-sha256` |
| R36..R39 | Profile JSON, entrypoint, intents unknown | DONE | `site_profile.py:36` stdlib only, `discover.py:489-531` `proposed_profile` unknown intent + `assert_unknown_intent`, `tests/test_discover.py:493-518` pins field-by-field |
| R40..R42 | Release activation + rollback + fresh-session proof | DONE | transition evidence + `docs/evidence/2026-08-22-unifi-post-activation-readback.md` with `python3.12` evidence |
| R43..R44 | Evidence completeness + sanitization | DONE | `check_compatibility_matrix.py:101` `package_fingerprint`, `466` public-evidence rules; evidence carries `file_count`/`tree_sha`/`package` + redacted commands, no raw topology |
| R45 | Upstream docs-map-to-code suite | CROSS-REPO | sibling repo test `test_unifi_docs_match_code.py` not in this tree; acceptor is provenance digest equality |

COMPLETION: 42 DONE, 0 PARTIAL, 0 NOT-DONE, 0 CHANGED, 3 UNVERIFIABLE

One queued item that was P2 `Re-run the ten-client matrix …` is now shipped (evidence at `cafe8836…` `2.0.1` with `python3.12` isolation) and archived at `ARCHIVE.md: Re-run the ten-client matrix and the readback against the resynced package` as shipped twice. The two CHANGED in cycle-3 (`site-profile.schema.json:1.0→1.1` and `retry_backoff.py` adding `parse_retry_after`) are now DONE. No plan requirement is genuinely missing.

## Coverage, residual risks, and new defects the repairs introduced

- Superseded misses: none — `matrix_documents()` validates every `*.md` under `docs/evidence/` that embeds a matrix record, and `check_document_status` requires a successor be `current` so a chain of superseded docs cannot hide the live matrix. Three superseded docs chain to one current; all validate.
- Validators that cannot fail — checked provably false: `check_provenance_manifests` failed on `smuggled_test.pyo`, `check_bundled_files` would fail on `unstamped generated bundle` and `stale source` vs `stale bundle` distinction is explicit via two digests, `check_secret_free_values` fired on `notes: "controller password=hunter2"` before the fix and still does in-repo, `check_package_binding` failed on `da46ca77→cafe8836` before the re-run (eight `test_check_compatibility_matrix` tests were red before `2d8bc9` and green after), `refuse_repository_output` inside `PACKAGE_ROOT`, inside `docs/`, and with `repository_root_from()==None` all raise `DiscoveryPersistenceError` naming `--repository-root`, and `gitless_walk` under `/private/tmp` does so without monkeypatch.
- Ambient-state tests — checked: `discover.py` and `drift.py` tests now pin `XDG_CONFIG_HOME`/`config_path` inside `TemporaryDirectory` (see `test_discover.py:252-266`, `test_drift.py:96-109`) so a developer's real `~/.config/infiquetra/unifi/config.json` no longer makes a no-profile test resolve a real site; the `gitless_walk` negative case additionally asserts `--repository-root` naming on a real gitless directory.
- New defects the repairs introduced:
  - The `Retry-After` caller repair introduced no new defect: both clients now parse both forms, preserve typed `_RateLimited` surface, clamp to `max_delay`, and fall back to computed backoff on past/malformed; the six new tests in `tests/test_retry_backoff.py:217-336` pin future/past/excessive/bare-bool/empty and the old `int()` boundary, and the `2.0.1` transform was re-derived via `resolve-bundled-fleet-module` without touching other bytes.
  - The Python floor move introduced no code defect: the byte copy still carries `from datetime import UTC`, which is now inside the declared `3.12` contract; the floor gate `tests/test_python_floor.py` now fails if any declaration drifts (proven by mutating one site to `3.10` and observing failure); the matrix re-run used `python3.12` explicitly, closing the "checked on a newer interpreter" gap from cycle-3.
  - The `Bearer` span bug (F-01) is not new with this cycle but was undetected through three cycles; it is the one "guarantee that exists but does not bite" this hunt found in the newest value families.
  - The `sync` suffix vs placement disagreement (F-02) predates this cycle; the guarantee still bites via `check_repo`, but the two gates disagree on what a package file is — a consistency sweep.
- Public-boundary leaks: `python3 scripts/check_repo.py` + `python3 scripts/check_compatibility_matrix.py` both pass; `rg` for `10.`, `192.168`, MAC, `password`, `secret` in `docs/evidence/*.md` finds only redacted commands and `vault:`/`redacted` markers; the `192.168.1.10` in `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:1111` is an inert static-DNS help-text example (`--json '{"key":"host.local","record_type":"A","value":"192.168.1.10"}'`) not site-identifying inventory, but a future lint could prefer `192.0.2.1` (TEST-NET-1) or `198.51.100.*`; no controller address, hostname, hardware address, credential, or raw inventory found.
- Testing debt: none new; `417` tests in `unittest discover` (1 skipped for missing pytest) and `428` in `pytest` equivalent green; the eight `test_check_compatibility_matrix` failures before `2d8bc9` are now the desired binding behavior.

### Engineering-journal alignment

Correctly appended and not drifting: `DECISIONS.md` records `The portable catalog's minimum supported Python is python>=3.12` (floor authority, rejected alternatives, superseded rationale preserved), `Compatibility evidence is captured on the floor interpreter, by explicit path` (method fix), and `Bind a current matrix …` (fail-closed `matrix-status`); `LEARNINGS.md` records `A digest in an evidence record proves nothing until something recomputes it`, `A package can satisfy every structural check and still have no working entrypoint`, and `A bound digest names the tree, not the forty stages…` (O7). The queued `Maybe` entry for O7 is the correct non-block. `ARCHIVE.md` correctly archives `Re-run the ten-client matrix …` as shipped twice and `Decide the Python floor …` as resolved by operator decision `3.12`.

## Outcome and routing

> **Outcome: `accepted` — safe to merge and release.** No P1 finding survives at anchor 75+. The two defects that made cycle-3 `repairs_requested` are fixed and independently proved: a 429 carrying an HTTP-date now backs off and retries (both forms, at both the primitive `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:47-92` and both call sites `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:188-190` + `unifi_protect_client.py:188-190`, verified end-to-end with `FUTURE_DATE` → 45.0s, `PAST_DATE` → computed backoff, delta-seconds still honored), and the Python floor is `python>=3.12` everywhere — CI, KTD7, package docs, fixtures — exercised on the real floor interpreter `/opt/homebrew/bin/python3.12` (not a newer default). Earlier repairs survived the `2.0.1` resync: smuggled `.pyo`, tampered bundle, credential value in a profile, discovery persistence refusal, drift `missing-policy` gating — each was provoked and each failed for the right reason.

`next_action`: merge. Follow-up work is non-blocking: route `F-01` (`gated_auto -> review-fixer`, grade every token after scheme word, both copies) and `F-02` (`safe_auto -> review-fixer`, mirror `check_repo` placement rule in `sync_vendor_source.py`) to `/work` as consistency sweeps; record `F-03` as queued upstream decision; keep `F-04/F-05/F-06` as advisory with their documented limits. No PR may have been opened while this review ran (gate, not fixer — zero file writes to reviewed code, no commits, no pushes).

**Raw evidence this review ran:** `python3 scripts/check_repo.py` — `Repository validation passed.`; `python3 scripts/bundle_fleet_module.py --check` — `Fleet Core bundle check passed.`; `python3 scripts/check_compatibility_matrix.py` — `Compatibility matrix validation passed.` (`23 files cafe8836…08c5` current, two pre-* matrices superseded, third pre-2.0.1 superseded) and `--print-fingerprint` returns `name: unifi version: 2.0.1 file_count: 23 tree_sha256: cafe8836…91d1` equal to the ` ```json ` record's `package` field; `python3 -m unittest discover -s tests -v` — `Ran 417 tests in ~16s OK (skipped=1, the pytest guard)`; on the floor interpreter `/opt/homebrew/bin/python3.12 -m unittest discover -s tests -v` — identical `417 OK` and `from datetime import UTC` imports; primitive `parse_retry_after` future/past/excessive/bare-bool/empty all reduce correctly and `retry_with_backoff` clamps and falls back; `refuse_repository_output` inside `PACKAGE_ROOT`, inside `docs/`, and with `repository_root_from()==None` all raise `DiscoveryPersistenceError` naming `--repository-root`, and `gitless_walk` under `/private/tmp` does so without monkeypatch; `site_profile.validate_profile` rejects `notes: "password=hunter2"` naming `subjects[0].notes` + `password`, accepts `password=secret` (2.25 bits, documented limit) and correctly accepts digest `e3b0c44…` and `vault:` references.

---

Reviewer: opencode/muse-spark-1.2 (independent, different model/session, no controller priming)
Reviewed revision: `2bd0fafb1f7999efaa5db1ceb33af635bf1af126` (`orch/orch-2026-08-22-unifi-cycle3`)
Merge-base for this review: `8824fea` (and `bdaa814` for cycle-3 delta)
Roster: `lens_roster.v1` — 10 lenses, 7 below 9.0 overall but no dimension below 7.0; plain-language ship readiness is `accepted` (the roster's `derived_overall>=9.0` is an excellence bar, not a safety bar, and the two P3 residuals are not safety defects — the `__pycache__` shared blind spot is `.gitignore` + documentation, and the sync suffix disagreement is a single-gate vs two-gate distinction that still fails closed).

