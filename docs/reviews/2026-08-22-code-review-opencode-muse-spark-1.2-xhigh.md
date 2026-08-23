# Independent code review — infiquetra-agent-plugins 8824fea..95de0d5 (PR #3)

Reviewer: opencode / muse-spark-1.2 (independent, unattended)
Scope: `git diff 8824fea..95de0d5` — 60 files, ~16468 lines — plan `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md`
Base verified by `git show 95de0d5:plugins/unifi/...`, `scripts/check_repo.py`, `scripts/bundle_fleet_module.py --check`, live entrypoint runs.
Outcome: repairs_requested — at least three P1-class issues remain, matrix evidence does not describe the shipped artifact.

## Scope Check

Scope Check: DRIFT DETECTED (no creep, but factual drift in evidence)

Intent: Portable Agent Plugins 1.0 UniFi package derived from corrected Claude upstream (R1-R9), portable Fleet Core slice with build-time bundling (R16-R21, R34-R35), optional site-profile contract with no-inference guarantee (R10-R15, R36-R39), and ten-client compatibility assessment as the pilot gate (R22-R25, R43-R44).

Delivered: All code surfaces exist and validate cleanly (`check_repo.py` passes, `bundle --check` passes, 280 tests pass), but the public compatibility evidence claims a 21-file package with no working entrypoint while the committed tree ships 23 files whose entrypoints succeed. No unrelated scope creep.

## Lens Selection

Always-on (4): architecture-maintainability, correctness, security, testing.
Conditional selected (4):
- deployment-infrastructure — diff adds provenance manifests, generated bundles, schemas, CI jobs, and cross-repo release gates.
- reliability — retry_backoff primitive and discovery read-only guards touch failure/retry paths.
- api-contract — new CLIs, JSON schemas, plugin manifests, fleet-bundle declaration, site-profile contract.
- adversarial — 60-file change with load-bearing validators, digest checks, and claimed guarantees.

Not selected: performance (no latency/throughput target in plan, retry timing covered under reliability).

## Built-vs-Planned Audit (U1..U12, R1..R45)

Method: DIFF-VERIFIABLE (files present in 95de0d5), CROSS-REPO (sibling commits not edited), EXTERNAL-STATE where noted. Honesty rule: handled != deliverable.

COMPLETION: 31 DONE, 4 PARTIAL, 2 NOT-DONE, 4 CHANGED, 4 UNVERIFIABLE (45 requirements)

Implementation:
- R01 DONE `scripts/sync_vendor_source.py:1` + `plugins/unifi/PROVENANCE.json:2` source_commit 0eb1fe04
- R02 DONE `scripts/check_repo.py:260` provenance recomputed hermetically, `python3 scripts/check_repo.py` passes
- R03 DONE `plugins/unifi/PROVENANCE.json:3` pins 0eb1fe04 (corrected 2.0.0), not 995a475; R04 DONE classifications byte-copy/transform/target-owned recorded
- R05-R09 CROSS-REPO DONE via 0eb1fe04 (docs repair, endpoint fixes) — verified by byte-copy shas in PROVENANCE matching upstream docs; not re-verified live here => UNVERIFIABLE for activation gap
- R10-R15 DONE `plugins/unifi/scripts/site_profile.py:1`, `site_profile_setup.py:1`, `schemas/site-profile.schema.json:1`, `references/site-profile.md:1`
- R16-R21 DONE `plugins/fleet-core/plugin.json:2`, `DEFERRED.md:1`, `fleet-bundle.json:1`, `scripts/bundle_fleet_module.py:1`, bundles at `skills/.../_bundled/retry_backoff.py:1`
- R22-R25 PARTIAL `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` exists with 10 clients, but evidence is stale (see F-01)
- R26-R27 DONE `plugins/unifi/scripts/discover.py:41` READ_ONLY_OPERATIONS only GET, `discover.py:250` refuse_repository_output, never passes --confirm
- R28 DONE `plugins/unifi/plugin.json:2` $schema canonical + name; R29 DONE `skills/unifi-network/SKILL.md:1` name matches dir, 6-field check passes
- R30-R31 UNVERIFIABLE Orchestrate/Herdr run topology not observable from diff
- R32-R33 DONE `plugins/fleet-core/PROVENANCE.json:3` 0.25.0 slice, release surface enumerated
- R34-R35 DONE `schemas/fleet-bundle.schema.json:1` closed schema + `scripts/bundle_fleet_module.py:338` two-domain digests
- R36-R37 DONE `site_profile.py:36` JSON stdlib only + `site_profile_setup.py:125` presents exactly 3 paths
- R38 DONE `plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py:1`
- R39 DONE `plugins/unifi/scripts/discover.py:426` proposed_profile unknown intent + test `tests/test_discover.py`
- R40-R42 NOT-DONE (plan says U9 transition evidence + staged load + fresh-session proof required before activation; no `docs/evidence/2026-08-22-unifi-transition-evidence.md` in 95de0d5, no tri-lock readback)
- R43 PARTIAL matrix carries 40 stage results but file_count/tree_sha and invocation evidence wrong (F-01)
- R44 DONE sanitization enforced by `scripts/check_compatibility_matrix.py:466` (validator rejects address/MAC/hostname/credential)
- R45 PARTIAL upstream docs repair maps to tests only in sibling repo, not in this diff

Units: U01 DONE, U02 DONE, U03 DONE, U04 DONE, U05 DONE, U06 CROSS-REPO (0eb1fe04), U07 CROSS-REPO, U08 CROSS-REPO (home-lab), U09 NOT-DONE, U10 DONE, U11 PARTIAL, U12 PARTIAL (QUEUED not yet archived).

## Findings Summary (by severity)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | docs/evidence/2026-08-22-unifi-compatibility-matrix.md:248 | Matrix file_count/tree_sha does not describe shipped tree | correctness | 100 | manual -> release |
| F-02 | docs/evidence/2026-08-22-unifi-compatibility-matrix.md:109 | Matrix prose + invocation evidence claims shim failure contradict live entrypoints | correctness | 100 | manual -> release |
| F-03 | plugins/unifi/scripts/drift.py:55 | Drift treats every profiled network as missing policy | correctness | 75 | gated_auto -> review-fixer |
| F-04 | scripts/check_repo.py:260 | Provenance does not enforce closed file set | architecture-maintainability | 75 | safe_auto -> review-fixer |
| F-05 | scripts/check_repo.py:352 | Bundle source/output provenance fields not required | security | 75 | safe_auto -> review-fixer |
| F-06 | plugins/unifi/scripts/discover.py:249 | Persistence deny-list fails open without .git | security | 75 | safe_auto -> review-fixer |
| F-07 | plugins/unifi/README.md:1 | Portable README claims local documentation that does not exist | api-contract | 75 | safe_auto -> review-fixer |
| F-08 | scripts/check_compatibility_matrix.py:466 | Public evidence redaction is partial | security | 50 | advisory -> human |
| F-09 | plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:120 | Retry-After handling incomplete for date form | reliability | 50 | advisory -> human |

Pre-existing (informational): example MAC `aa:bb:cc:dd:ee:ff` in docs — inert placeholder, not site-identifying; no PII found via `rg` for 10.x/192.168/hostname in added lines except documented `controller.example`.

## Detailed Findings

### F-01 — Matrix file_count and tree_sha do not describe the shipped tree (P1)

- severity: P1
- dimension_id: specification-documentation-parity
- file: docs/evidence/2026-08-22-unifi-compatibility-matrix.md
- line: 248
- why_it_matters: Pilot gate R43 requires field names, counts, pass/fail and source/result digests. The matrix is the only public proof for operator's per-client decision. Wrong counts/digest means no client row is bound to the actual bytes the PR ships.
- evidence: `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:248` file_count 21 + tree_sha 92ed503207ca... vs `git ls-tree -r 95de0d5 -- plugins/unifi/` 23 files including `skills/.../_bundled/retry_backoff.py` twice; recomputed tree sha 8b212cc... != recorded. Validator `scripts/check_compatibility_matrix.py` never recomputes tree (no sha over sorted digests).
- autofix_class: manual
- owner: release
- confidence: 100
- pre_existing: false
- suggested_fix: Regenerate matrix record from live tree after `python3 scripts/bundle_fleet_module.py` and `python3 scripts/sync_vendor_source.py --check`; assert file_count == `git ls-files | wc -l` and tree_sha == sha256(sorted file shas).

### F-02 — Matrix claims no bundle / all invocations fail, but entrypoints succeed (P1)

- severity: P1
- dimension_id: intent-behavior-completeness
- file: docs/evidence/2026-08-22-unifi-compatibility-matrix.md
- line: 109
- why_it_matters: Eight works-directly verdicts rest on invocation stage. If prose says every invocation aborts with ModuleNotFoundError for fleet_commons_shim, operator reads package as unusable on every client, contradicting passing `tests/test_client_entrypoints.py` and live `unifi_network_client.py --help` exit 0.
- evidence: `docs/evidence/...md:109-119` "assembled package contains no generated bundle and both scripts still import the dropped module" + `md:362,390,418,446,474,502,530` invocation evidence shims; vs `plugins/unifi/skills/unifi-network/scripts/_bundled/retry_backoff.py:1` exists and `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:48` `sys.path.insert(.../_bundled)` + `import retry_backoff` succeeds; `python3 plugins/unifi/skills/.../unifi_network_client.py --help` exits 0 without UNIFI_*.
- autofix_class: manual
- owner: release
- confidence: 100
- pre_existing: false
- suggested_fix: Re-run matrix invocation stage against committed tree with isolated home, update each client's invocation evidence to real output (help text), keep shim failure note as historical only if any.

### F-03 — Drift reports every profiled network as missing policy (P1)

- severity: P1
- dimension_id: state-data-invariants-transactions-concurrency
- file: plugins/unifi/scripts/drift.py
- line: 55
- why_it_matters: Drift is intended as operator's intended-vs-actual view. False missing-policy findings erode trust and hide real drift.
- evidence: `drift.py:55` `actual_hosts` only collects `clients` resource; `drift.py:121` intended policies compared to `observed_policy_identifiers` which reads `inventory["policies"]` (always [] from `discover.py:577` empty_inventory). No discovery path populates policies, so any `intended_policies` in profile yields MISSING_POLICY even when network is correct.
- autofix_class: gated_auto
- owner: review-fixer
- confidence: 75
- pre_existing: false
- suggested_fix: Either populate inventory policies from discovery (or document narrow scope explicitly), or scope drift to only what discovery covers and skip policy comparison when observed_policies empty, naming the limitation in report limits.

### F-04 — Provenance validation is not closed over package files (P2)

- severity: P2
- dimension_id: architectural-fit-ownership-single-sources
- file: scripts/check_repo.py
- line: 260
- why_it_matters: R04 promise every path is exactly one classification. Validator only checks listed files' digests (260-292), not that an extra unlisted file exists. A post-sync file addition would ship undetected.
- evidence: `check_repo.py:260` `check_provenance_manifests` iterates `payload.files` entries only; no scan for untracked files under `plugins/unifi/` except `_bundled` via separate `check_bundled_files`. Adding `plugins/unifi/scripts/extra.py` passes `check_repo.py`.
- autofix_class: safe_auto
- owner: review-fixer
- confidence: 75
- pre_existing: false
- suggested_fix: Add closed-set check: list all files under `plugins/unifi/` excluding ignored, assert each is either in PROVENANCE files or is a generated bundle covered by `presence_errors`; fail on unexpected file.

### F-05 — Bundle provenance fields optional so stale bundle can pass (P2)

- severity: P2
- dimension_id: dependency-supply-chain
- file: scripts/check_repo.py
- line: 352
- why_it_matters: R35 two digest domains (source vs output) are the tamper vs staleness signal. If fields absent, CI cannot distinguish hand-edit from stale source.
- evidence: `check_repo.py:352-386` `check_bundled_files` skips source freshness when stamp missing `source-sha256`/`source-path`; `scripts/bundle_fleet_module.py:338` render includes both, but manual edit removing the line yields "unstamped" only, not stale-source distinction. Provenance manifest does not require these fields either.
- autofix_class: safe_auto
- owner: review-fixer
- confidence: 75
- pre_existing: false
- suggested_fix: Require both `source-sha256` and `output-sha256` in stamp; make `_check_bundle_source_freshness` fail when either missing rather than returning [].

### F-06 — Discovery persistence deny-list fails open outside git checkout (P2)

- severity: P2
- dimension_id: confidentiality-logs-errors-egress
- file: plugins/unifi/scripts/discover.py
- line: 249
- why_it_matters: R27 raw controller responses must not reach committable paths. If developer runs discovery from a copy without .git, attacker-copied package could write inventory into package dir.
- evidence: `discover.py:249` `repository_root_from` walks to `.git`; if None, `refuse_repository_output` at `discover.py:266` returns resolved without refusal. Tests use injected repository_root, but default path via cwd fails open.
- autofix_class: safe_auto
- owner: review-fixer
- confidence: 75
- pre_existing: false
- suggested_fix: When repository_root_from returns None, refuse unless output is under explicit allowed tmp (or require --repository-root). At minimum, deny any output under `plugins/unifi/` relative to cwd.

### F-07 — Portable README references missing local docs (P3)

- severity: P3
- dimension_id: specification-documentation-parity
- file: plugins/unifi/README.md
- line: 1
- why_it_matters: Operator following README to understand profile contract hits broken navigation; check_repo's markdown link check should catch but currently does not for package-level relative links due to exclusion or missing file.
- evidence: `plugins/unifi/README.md:1` links to `references/site-profile.md` correctly, but changelog at `plugins/unifi/CHANGELOG.md:1` claims transition evidence at path not shipped in this repo; `docs/README.md:1` still references old plan path. No test asserts link integrity across package docs.
- autofix_class: safe_auto
- owner: review-fixer
- confidence: 75
- pre_existing: false
- suggested_fix: Add link lint for `plugins/unifi/**/*.md` relative targets; ensure README references resolve to `plugins/unifi/references/site-profile.md:1` and schema `schemas/site-profile.schema.json:1`.

### F-08 — Public evidence redaction check is partial (P3)

- severity: P3
- dimension_id: input-trust-boundaries-injection
- file: scripts/check_compatibility_matrix.py
- line: 466
- why_it_matters: R44 requires no raw topology/controller responses in public repo. Partial check risks site-identifying leakage via free-text evidence.
- evidence: `check_compatibility_matrix.py:466` only checks for IP/MAC/DOMAIN/CREDENTIAL_ASSIGNMENT patterns; does not check for raw controller JSON (e.g., VLAN ids, client hostnames) that could be identifying when combined. Tests `tests/test_check_compatibility_matrix.py:1` seed inert example values but not exhaustive.
- autofix_class: advisory
- owner: human
- confidence: 50
- pre_existing: false
- suggested_fix: Expand validator to reject any evidence containing controller-shaped keys (e.g., `hostname` values that are not example.com) or document as accepted residual with operator review gate.

### F-09 — Retry-After date form not handled (P3)

- severity: P3
- dimension_id: timeouts-retries-circuit-breakers-idempotency
- file: plugins/fleet-core/scripts/fleet_commons/retry_backoff.py
- line: 120
- why_it_matters: Fleet primitive is the pilot's only shared reliability control. Missing date-form Retry-After means a real 429 with date header backs off incorrectly, risking retry storm.
- evidence: `retry_backoff.py:120` parses Retry-After as int seconds only; HTTP spec allows HTTP-date form. Test `tests/test_retry_backoff.py:1` covers int clamp but no date case. Upstream issue #348 mentions both forms.
- autofix_class: advisory
- owner: human
- confidence: 50
- pre_existing: true
- suggested_fix: Parse HTTP-date fallback with email.utils.parsedate_to_datetime, clamp to max_delay; add unit test for date form.

## Lens Scores (derived, not a gate beyond per-dimension floor)

- architecture-maintainability: 8.2 (ownership 6 due F-04, separation 9, dependency 9, simplicity 8, readability 9, portability 8, decisions 9) — floor 7 violated by ownership.
- correctness: 6.8 (intent 5 due F-02/F-03, state 7, boundaries 8, side-effects 8, consumers 7)
- security: 7.0 (auth 9, input 7 due F-08, secrets 8, supply-chain 6 due F-05, confidentiality 7 due F-06) — supply-chain fails floor.
- testing: 7.2 (requirements 7, negative 7, assertions 8, seams 6 — matrix seam not re-executed, drift not integration-proven, determinism 9)
- deployment-infrastructure: 7.2 (infra 8, rollout 7 — no staged readback proof, rollback 7, deployed verification 6 due F-01)
- reliability: 8.0 (timeouts 7 due F-09, partial 8, graceful 8, health 8)
- api-contract: 7.6 (compatibility 7, versioning 8, serialization 7, retry 7, pagination 8, spec parity 7 due F-07)
- adversarial: 6.8 (assumptions 6, abuse 7, silent-green 6 due matrix drift, environment 6 due git-dependency, scope 8, alternatives 8, recovery 7)

Overall derived ~7.3, floor violations present => repairs_requested.

## Coverage

Suppressed: findings <75 confidence except P0 hidden — 0 suppressed (P3 at 50 kept as advisory per schema).
Residual risks: F-08/F-09 date-form and evidence completeness need operator judgment; cross-repo U09 transition proof still external.
Testing gaps: No integration proof for drift with live inventory (mocked only); no test asserts matrix file_count/tree_sha bound to live tree; no test for discovery persistence outside git.

No lens was omitted silently: performance explicitly N/A (no perf target in plan).

## Evidence Collected

- `git ls-tree -r 95de0d5 -- plugins/unifi/` 23 files vs matrix 21 at `docs/evidence/...md:248`
- `python3 plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py --help` exit 0, usage printed, no UNIFI_* required (vs md:362 claims shim error)
- `python3 scripts/check_repo.py` passes (proves provenance digests match but also proves closed-set gap)
- `python3 scripts/bundle_fleet_module.py --check` passes
- `python3 -m unittest discover -s tests 2>&1 | tail` 280 tests ok — but none bind matrix digest to tree

## Route

- F-01, F-02: manual -> release (regenerate matrix, re-run 10 clients against final tree, fresh-session proof)
- F-03: gated_auto -> review-fixer (drift policy scope)
- F-04, F-05, F-06, F-07: safe_auto -> review-fixer
- F-08, F-09: advisory -> human (calibrate, no auto fix without product decision)

> Verdict: repairs_requested. Next action: regenerate compatibility evidence against the final shipped tree before any operator per-client decision; land F-04/F-05/F-06 validator fixes; re-run drift and discovery integration tests. Do not merge PR #3 as-is.

