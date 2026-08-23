# Independent code review — commit `95de0d5`

Reviewed `8824fea..95de0d5` in `infiquetra-agent-plugins`, with sibling commits
`infiquetra-claude-plugins@0eb1fe04` and `home-lab@653ab97a` used only as
cross-repository evidence. Outcome: `repairs_requested`.

## Scope check

**Scope Check: REQUIREMENTS MISSING**

**Intent:** Turn the UniFi Claude plugin into a runnable portable Agent Plugins
package, port the bounded Fleet Core slice, and complete the release and
ten-client evidence gates in the pilot plan.

**Delivered:** The portable package, adapter, Fleet Core source and bundles,
profile/discovery/drift tools, synchronization tooling, CI, and compatibility
record all exist, but nine validated findings remain. There is no unrelated
scope creep.

The missing or partial requirements are: final-artifact compatibility evidence,
post-activation installed-state proof, truthful policy drift, closed provenance
coverage, mandatory bundle provenance fields, safe stale-file deletion, an
enforceable secret-free profile claim, portable package-local documentation,
and complete `Retry-After` handling.

## Selected lenses

The four always-on lenses and eight conditional lenses were attempted.

| Lens | Selection reason | Admitted findings |
|---|---|---|
| `architecture-maintainability` | Always on | F-04 |
| `correctness` | Always on | F-03 |
| `security` | Always on | F-05, F-06, F-08 |
| `testing` | Always on | F-01 |
| `deployment-infrastructure` | Build artifacts, provenance, cross-repository release gates, and deployed readback materially change | F-02, F-05 |
| `reliability` | The diff adds retry behavior, failure handling, synchronization cleanup, and drift reporting | F-03, F-09 |
| `api-contract` | The diff adds CLIs, JSON schemas, configuration, manifests, and file-format contracts | F-07, F-08, F-09 |
| `adversarial` | The 60-file change contains load-bearing validators, deletion behavior, and release gates | F-01, F-02, F-04, F-05, F-06 |
| `privacy` | Discovery handles controller inventory and the public evidence boundary | F-08 (cross-lens agreement); no separate privacy finding |
| `documentation-clarity` | The package README, plan, journal, and compatibility evidence materially change | F-01, F-07 |
| `agent-usability` | Skills, commands, machine-readable output, and setup/discovery workflows are agent-operated surfaces | F-03, F-07 |
| `accessibility-human-usability` | First setup and all operational entrypoints are human-operated command surfaces | No additional finding; documentation defects are consolidated into F-07 |

`performance` was not selected because the diff adds no representative
performance target or hot-path change beyond bounded retry timing, which the
reliability lens covers. `previous-comments` was not selected because pull
request 3 has no review comments or unresolved threads.

### Roster scores

The roster accepts a lens only when its mean applicable-dimension score is at
least 9 and no applicable dimension is below 7. Scores below are bound to
`95de0d5`; abbreviated dimension names preserve the roster identifiers'
meaning.

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall | Failing dimensions |
|---|---|---|---:|---|
| `architecture-maintainability` | ownership/single-sources 6; separation 9; dependency 9; simplicity 8; readability/errors 9; portability/config 8; decisions 9 | none | 8.29 | `architectural-fit-ownership-single-sources` |
| `deployment-infrastructure` | infra/config 8; rollout order 9; rollback/drift 7; deployed verification 5 | no cloud resource or cost change | 7.25 | `deployed-state-verification-observability` |
| `correctness` | intent/completeness 5; state/invariants 8; boundaries 8; side effects/errors 8; consumers 7 | none | 7.20 | `intent-behavior-completeness` |
| `security` | auth/default deny 9; input boundaries 5; secrets 6; supply chain 5; confidentiality 8 | none | 6.60 | `input-trust-boundaries-injection`, `secrets-cryptography-session-handling`, `dependency-supply-chain` |
| `testing` | requirements 7; negative/edge 7; assertions 8; realistic seams 5; determinism 9 | none | 7.20 | `realistic-seams-mocks-integration-evidence` |
| `reliability` | retries/timeouts 7; partial failure 8; graceful degradation 8; health signals 7 | no queue, job, ordering, or backpressure surface | 7.50 | none; overall below 9 |
| `api-contract` | compatibility 7; versioning 8; serialization/errors 7; retry semantics 7; pagination/rate limits 7; spec parity 5 | no SDK or generated client | 6.83 | `specification-documentation-parity` |
| `adversarial` | assumptions 5; abuse/edges 5; silent green 5; environment/operator 6; scope 8; alternatives 8; recovery 7 | none | 6.29 | `load-bearing-assumptions`, `abuse-edge-cases`, `failure-amplification-silent-green`, `environment-operator-failure` |
| `privacy` | data-flow inventory 8; minimization 8; protection/sharing 7; retention 7; AI/telemetry 7 | no geographic residency or transfer mechanism | 7.40 | none; overall below 9 |
| `documentation-clarity` | behavior parity 5; completeness 6; structure 8; terminology 7; examples 5; runbook/drift 7 | none | 6.33 | `shipped-behavior-parity`, `completeness-audience-prerequisites`, `runnable-examples-actionability` |
| `agent-usability` | reachability 7; discovery/schema 7; context/acceptance 7; machine output 8; bounded operation 7 | none | 7.20 | none; overall below 9 |
| `accessibility-human-usability` | command discoverability/defaults/recovery 7 | no visual UI, assistive-technology control, keyboard/focus, contrast/motion, form, or localization surface | 7.00 | none; overall below 9 |

## P1 findings

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:248` | Matrix assesses the pre-repair package | `testing`, `adversarial`, `documentation-clarity` | 100 | `manual -> release` |
| F-02 | `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:130` | Post-activation proof was never performed | `deployment-infrastructure`, `adversarial` | 100 | `manual -> release` |
| F-03 | `plugins/unifi/scripts/discover.py:577` | Discovery makes every intended policy look missing | `correctness`, `reliability`, `agent-usability` | 100 | `manual -> human` |
| F-04 | `scripts/check_repo.py:290` | Provenance validation accepts unclassified package files | `architecture-maintainability`, `security`, `adversarial` | 100 | `safe_auto -> review-fixer` |
| F-05 | `scripts/check_repo.py:403` | Bundle provenance fields are optional in CI | `security`, `deployment-infrastructure`, `adversarial` | 100 | `safe_auto -> review-fixer` |
| F-06 | `scripts/sync_vendor_source.py:635` | Malicious provenance can unlink outside the package | `security`, `adversarial` | 100 | `safe_auto -> review-fixer` |

### F-01 — Matrix assesses the pre-repair package

- `severity`: `P1`
- `lens_id` / category: `testing`
- `dimension_id`: `realistic-seams-mocks-integration-evidence`
- `critical`: `true`
- `file`: `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`
- `line`: `248`
- `why_it_matters`: The pilot's client-support conclusions describe a 21-file
  package whose entrypoints fail at import, not the final 23-file package in
  commit `95de0d5`. An operator deciding whether to repair or support a client
  therefore has no compatibility evidence for the artifact that actually
  shipped.
- `autofix_class`: `manual`
- `owner`: `release`
- `requires_verification`: `true`
- `confidence`: `100`
- `pre_existing`: `false`
- `evidence`:
  - `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:245-249` binds the
    assessment to `file_count: 21` and tree digest
    `92ed503207ca6eabfc5a70a892d682ee0030ad0d16db2db436abfb83f7fa240b`.
  - `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:277-280` says the
    credential-free invocation aborts on `ModuleNotFoundError:
    fleet_commons_shim`.
  - `tests/test_client_entrypoints.py:120-135` proves both final entrypoints
    instead exit zero and print usage without that import error.
  - `git ls-tree -r --name-only 95de0d5 -- plugins/unifi` returns 23 files,
    including both generated `_bundled/retry_backoff.py` outputs.
  - `python3 scripts/check_compatibility_matrix.py` still passes because it
    validates digest shape and record safety, not that the digest/count identify
    the package in this revision.
- `suggested_fix`: Preserve this matrix as superseded historical evidence, then
  rerun all forty stages against the final package after repairs. Record the new
  file count and tree digest, update invocation evidence and derived statuses,
  and make validation bind a current matrix to the exact assessed artifact.

Validator: `{"validated":true,"reason":"The diff adds both the matrix claiming a 21-file unusable package and the 23-file repaired package whose two --help entrypoints pass, with no matrix supersession or validation binding its fingerprint to the shipped tree."}`

### F-02 — Post-activation proof was never performed

- `severity`: `P1`
- `lens_id` / category: `deployment-infrastructure`
- `dimension_id`: `deployed-state-verification-observability`
- `critical`: `true`
- `file`: `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md`
- `line`: `130`
- `why_it_matters`: The target run resumed synchronization from the activated
  upstream release without proving which version and digest a fresh installed
  client held or that all three profile states worked from those installed
  bytes. The no-capability-gap release claim remains unverified against the
  runtime users actually invoke.
- `autofix_class`: `manual`
- `owner`: `release`
- `requires_verification`: `true`
- `confidence`: `100`
- `pre_existing`: `false`
- `evidence`:
  - `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:130-134`
    requires installed-version/digest readback and fresh-client proof of all
    three profile states after activation.
  - `plugins/unifi/PROVENANCE.json:2-6` shows U10 synchronized from activated
    upstream commit `0eb1fe04`.
  - Cross-repository context
    `infiquetra-claude-plugins@0eb1fe04:docs/evidence/2026-08-22-unifi-transition-evidence.md:21-35`
    explicitly marks installed readback and the fresh-session three-state proof
    **still outstanding**.
  - The same evidence at lines 287-307 labels post-activation evidence `NOT
    PERFORMED` and defines it as the rollback trigger.
- `suggested_fix`: Refresh the upstream marketplace, open a fresh client
  session, record installed version and digest readback, and rerun profile
  present, absent, and unreadable states against the installed release. Attach
  the receipt before treating U9 as complete.

Validator: `{"validated":true,"reason":"The diff adds U10+ artifacts pinned to 0eb1fe04 despite that commit’s evidence leaving U9’s mandatory readback and fresh-session proof outstanding, and no target artifact handles the unmet gate."}`

### F-03 — Discovery makes every intended policy look missing

- `severity`: `P1`
- `lens_id` / category: `correctness`
- `dimension_id`: `intent-behavior-completeness`
- `critical`: `true`
- `file`: `plugins/unifi/scripts/discover.py`
- `line`: `577`
- `why_it_matters`: A normal live drift run with any intended policy always
  emits a false `missing-policy` finding, even when that policy exists on the
  controller. Operators cannot distinguish actual drift from an unobserved
  resource.
- `autofix_class`: `manual`
- `owner`: `human`
- `requires_verification`: `true`
- `confidence`: `100`
- `pre_existing`: `false`
- `evidence`:
  - `plugins/unifi/scripts/discover.py:565-578` executes the read-only catalog
    and then unconditionally assigns `inventory["policies"] = []`.
  - `plugins/unifi/scripts/drift.py:135-146` treats that empty list as observed
    controller state and emits one `missing-policy` finding per intended policy.
  - `tests/test_drift.py:133-160` deliberately uses no observed policies and
    asserts the missing finding.
  - `tests/test_drift.py:178-188` can suppress the finding only by manually
    injecting a policy into an inventory shape live discovery never produces.
  - `tests/test_drift.py:263-277` composes the real discovery-to-drift seam but
    asserts the false missing-policy result rather than observing a policy
    endpoint.
- `suggested_fix`: Represent policy observation as unavailable/unknown and do
  not emit `missing-policy` until a classified read-only policy endpoint has
  actually populated observed identifiers. If such an endpoint is supported,
  add it to the guarded discovery catalog and test present, absent, and
  unavailable states through the full chain.

Validator: `{"validated":true,"reason":"The diff introduces live discovery with no policy endpoint and an always-empty policies list, which drift treats as authoritative absence, so every intended policy becomes a false missing-policy finding with no live-path mitigation."}`

### F-04 — Provenance validation accepts unclassified package files

- `severity`: `P1`
- `lens_id` / category: `architecture-maintainability`
- `dimension_id`: `architectural-fit-ownership-single-sources`
- `critical`: `true`
- `file`: `scripts/check_repo.py`
- `line`: `290`
- `why_it_matters`: The repository's hermetic provenance gate can pass after a
  managed entry is removed from the manifest, after an unlisted executable is
  added to a package, or when one path has duplicate classifications. A green
  check therefore does not enforce the plan's “every path exactly one
  classification” ownership guarantee.
- `autofix_class`: `safe_auto`
- `owner`: `review-fixer`
- `requires_verification`: `true`
- `confidence`: `100`
- `pre_existing`: `false`
- `evidence`:
  - `scripts/check_repo.py:260-292` validates only entries already present in
    `files`; it never compares listed paths with the package tree and never
    rejects duplicate paths.
  - `plugins/unifi/PROVENANCE.json:8-12` claims every path carries exactly one
    classification.
  - `.github/workflows/ci.yml:24-33` relies on `check_repo.py` as the hermetic
    provenance gate; it has no upstream checkout with which to run
    `sync_vendor_source.py --check`.
  - Existing tests cover changed content, missing listed files, unsafe paths,
    and unknown classifications at `tests/test_check_repo.py:150-286`, but no
    unlisted-file or duplicate-entry case.
- `suggested_fix`: Compare a de-duplicated manifest path set with every
  classifiable package file, using explicit exclusions only for the manifest
  itself and interpreter artifacts. Reject duplicate paths and both
  listed-but-missing and present-but-unlisted files, with seeded tests for each
  direction.

Validator: `{"validated":true,"reason":"The reviewed range introduced a validator that accepts duplicate entries and unlisted package files, while CI runs no live-tree synchronization check to catch them."}`

### F-05 — Bundle provenance fields are optional in CI

- `severity`: `P1`
- `lens_id` / category: `security`
- `dimension_id`: `dependency-supply-chain`
- `critical`: `true`
- `file`: `scripts/check_repo.py`
- `line`: `403`
- `why_it_matters`: Removing `source-path` or `source-sha256` from a generated
  bundle disables comparison with Fleet Core while the hermetic CI gate remains
  green. The generated body can then become stale without the check that claims
  to enforce source provenance detecting it.
- `autofix_class`: `safe_auto`
- `owner`: `review-fixer`
- `requires_verification`: `true`
- `confidence`: `100`
- `pre_existing`: `false`
- `evidence`:
  - `scripts/check_repo.py:370-386` requires only `output-sha256`.
  - `scripts/check_repo.py:403-406` returns no error when either `source-path`
    or `source-sha256` is absent.
  - The same check never requires `generated-by`, `source-version`, or
    `source-commit`, although `scripts/bundle_fleet_module.py:346-355` emits all
    five provenance fields.
  - `.github/workflows/ci.yml:24-33` runs `check_repo.py`, not
    `bundle_fleet_module.py --check`; the latter's stricter comparison at
    `scripts/bundle_fleet_module.py:417-448` therefore does not close the CI
    gap.
  - `tests/test_check_repo.py:338-359` tests a missing output digest only.
- `suggested_fix`: Require and validate `generated-by`, `source-version`,
  `source-commit`, `source-path`, `source-sha256`, and `output-sha256` in every
  generated bundle stamp whenever a Fleet Core package is present. Add one
  failing test per omitted field.

Validator: `{"validated":true,"reason":"The reviewed commit introduced this gap: check_repo.py accepts stamps containing only a valid output-sha256, and neither CI nor provenance validation invokes the stricter bundler check."}`

### F-06 — Malicious provenance can unlink outside the package

- `severity`: `P1`
- `lens_id` / category: `security`
- `dimension_id`: `input-trust-boundaries-injection`
- `critical`: `true`
- `file`: `scripts/sync_vendor_source.py`
- `line`: `635`
- `why_it_matters`: Running synchronization with a corrupt or malicious
  previous `PROVENANCE.json` can delete any file reachable through an absolute
  path or `..` traversal, rather than limiting stale cleanup to
  `plugins/unifi`.
- `autofix_class`: `safe_auto`
- `owner`: `review-fixer`
- `requires_verification`: `true`
- `confidence`: `100`
- `pre_existing`: `false`
- `evidence`:
  - `scripts/sync_vendor_source.py:521-540` accepts every nonblank `path` from a
    previous byte-copy or transform entry without validating relativity or
    containment.
  - `scripts/sync_vendor_source.py:634-639` joins each stale string to
    `plugin_dir` and calls `unlink()` if the resolved target is a file.
  - `scripts/check_repo.py:186-208` contains an unsafe-path guard for validation,
    but `synchronize()` at `scripts/sync_vendor_source.py:669-704` never invokes
    it before `apply_plan()`.
- `suggested_fix`: Validate every previous managed path as a safe relative path,
  resolve it, prove it remains under `plugin_dir`, and fail closed before any
  write or deletion. Add absolute-path, `..`, and symlink-escape deletion tests.

Validator: `{"validated":true,"reason":"Introduced in 95de0d5, apply_plan directly reproduced deletion through both absolute and '..' provenance paths, and synchronize never invokes the available safety validation."}`

## P2 findings

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-07 | `plugins/unifi/README.md:3` | Portable package README remains Claude-specific | `documentation-clarity`, `api-contract`, `agent-usability` | 100 | `manual -> human` |
| F-08 | `plugins/unifi/scripts/site_profile.py:8` | Secret-free validation checks names, not values | `security`, `privacy`, `api-contract` | 100 | `manual -> human` |
| F-09 | `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176` | Valid date Retry-After disables retries | `reliability`, `api-contract` | 75 | `gated_auto -> review-fixer` |

### F-07 — Portable package README remains Claude-specific

- `severity`: `P2`
- `lens_id` / category: `documentation-clarity`
- `dimension_id`: `shipped-behavior-parity`
- `critical`: `true`
- `file`: `plugins/unifi/README.md`
- `line`: `3`
- `why_it_matters`: A consumer opening the portable package's own documentation
  is told it is a Claude Code plugin and is given test commands that fail
  because the named files are not in this repository. The package-local
  onboarding surface does not describe the portable artifact the repository
  ships.
- `autofix_class`: `manual`
- `owner`: `human`
- `requires_verification`: `true`
- `confidence`: `100`
- `pre_existing`: `false`
- `evidence`:
  - `plugins/unifi/README.md:1-3` calls the portable package a “Claude Code
    plugin.”
  - `plugins/unifi/README.md:180-188` instructs users to run
    `tests/test_unifi_network_client.py` and
    `tests/test_unifi_protect_client.py`; neither file exists in commit
    `95de0d5`.
  - `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:234-243`
    classifies README as portable core and says it is rewritten site-neutral.
  - `plugins/unifi/PROVENANCE.json:31-35` instead preserves README as an
    upstream byte copy.
- `suggested_fix`: Decide the custody rule explicitly, then either make the
  upstream README genuinely portable and move Claude-only installation into
  the adapter, or add a deterministic portable-README transform. Replace the
  nonexistent test commands with this repository's actual validation and
  entrypoint tests.

Validator: `{"validated":true,"reason":"The diff adds plugins/unifi/README.md with Claude-specific labeling and two pytest paths absent from commit 95de0d5, contradicting the plan’s site-neutral portable-core requirement, while the root README’s entrypoint warning does not correct or disclose these package-local documentation defects."}`

### F-08 — Secret-free validation checks names, not values

- `severity`: `P2`
- `lens_id` / category: `security`
- `dimension_id`: `secrets-cryptography-session-handling`
- `critical`: `true`
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: `8`
- `why_it_matters`: Operators are told validation excludes credentials, but an
  API key, password, or bearer token placed in an allowed `notes`,
  `description`, `ownership`, or `identifier` string validates successfully and
  can enter the profile's repository and backups under a false assurance.
- `autofix_class`: `manual`
- `owner`: `human`
- `requires_verification`: `true`
- `confidence`: `100`
- `pre_existing`: `false`
- `evidence`:
  - `plugins/unifi/scripts/site_profile.py:4-10` says credentials are excluded
    by validation rather than convention.
  - `plugins/unifi/scripts/site_profile.py:91-105` defines credential-shaped
    name fragments.
  - `plugins/unifi/scripts/site_profile.py:311-328` examines mapping keys and
    recurses through containers but never examines string values.
  - `plugins/unifi/schemas/site-profile.schema.json:34-49` guards property names
    while `nonEmptyText` accepts every non-empty string.
  - `tests/test_site_profile.py:198-215` tests credential-shaped property names
    only. A profile with `notes: "password=hunter2"` passes
    `validate_profile`.
- `suggested_fix`: Narrow the public guarantee to what can actually be enforced
  (“credential-shaped fields are rejected; operators must never put secrets in
  values”) and add obvious value-level secret detection as defense in depth, or
  redesign the contract to remove unrestricted free-text fields if an absolute
  secret-free guarantee is required.

Validator: `{"validated":true,"reason":"Introduced in 95de0d5, validate_profile accepts notes='password=hunter2'; both loaders inspect only keys, while the schema and setup path add no value-level secret check."}`

### F-09 — Valid date Retry-After disables retries

- `severity`: `P2`
- `lens_id` / category: `reliability`
- `dimension_id`: `timeouts-retries-circuit-breakers-idempotency`
- `critical`: `false`
- `file`: `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py`
- `line`: `176`
- `why_it_matters`: A controller returning the HTTP-standard date form of
  `Retry-After` receives one request, no backoff retry, and a generic
  “Unexpected error” instead of the documented rate-limit error contract.
- `autofix_class`: `gated_auto`
- `owner`: `review-fixer`
- `requires_verification`: `true`
- `confidence`: `75`
- `pre_existing`: `false`
- `evidence`:
  - `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:173-176`
    calls `int()` on the header before raising `_RateLimited`.
  - `plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py:173-176`
    repeats the same conversion.
  - RFC `Retry-After` permits delta-seconds or an HTTP-date; `int()` on the
    latter raises `ValueError`, which reaches the generic exception branches at
    network-client lines 242-244 and Protect-client lines 245-247.
  - `tests/test_retry_backoff.py:129-154` tests numeric hints only, and there is
    no client-level response-header test.
- `suggested_fix`: Parse both delta-seconds and HTTP-date, calculate a
  non-negative delay against an injected clock, and fall back to computed
  backoff for malformed headers. Add response-level tests for missing, numeric,
  date, expired-date, and malformed values in both clients.

Validator: `{"validated":true,"reason":"Both newly added clients parse Retry-After with int(), and an RFC-valid HTTP-date causes one request then a generic error; no alternate handler or header test exists, and UniFi documentation does not narrow the header to integer seconds."}`

## Built-versus-planned completion audit

Verification modes are `DIFF`, `CROSS-REPO`, and `EXTERNAL-STATE`. The 45
numbered requirements are classified below.

### Implementation and packaging

- **R1 — DONE (DIFF):** synchronization and per-managed-file source/output
  digests exist at `scripts/sync_vendor_source.py:544-609` and
  `plugins/unifi/PROVENANCE.json:1-149`.
- **R2 — PARTIAL (DIFF):** local digest checks exist, but F-04 and F-05 show the
  hermetic validator does not enforce a closed file inventory or mandatory
  source stamp.
- **R3 — DONE (CROSS-REPO):** `plugins/unifi/PROVENANCE.json:2-6` pins corrected
  released commit `0eb1fe04`, whose cross-repository diff contains the upstream
  repairs.
- **R4 — PARTIAL (DIFF):** the current manifest classifies current package
  files, but F-04 shows the validator does not enforce exactly one
  classification for every file.
- **R5 — DONE (CROSS-REPO/DIFF):** the corrected six-resource surfaces are
  copied in the package; upstream commit `0eb1fe04` adds the named parity test.
- **R6 — DONE (CROSS-REPO/DIFF):** the corrected network paths are present in
  `plugins/unifi/skills/unifi-network/references/udm-api-endpoints.md`.
- **R7 — DONE (CROSS-REPO/DIFF):** all named network groups/actions are present
  in `plugins/unifi/skills/unifi-network/SKILL.md`.
- **R8 — DONE (DIFF):** both clients reject an absent host at network-client
  lines 89-101 and Protect-client lines 90-102; the adapter uses a profile
  rather than embedded values.
- **R9 — DONE (CROSS-REPO):** the deployment receipt in
  `home-lab@653ab97a` preceded activation in `infiquetra-claude-plugins@0eb1fe04`;
  the later post-activation proof is separately R40/R41.
- **R10 — DONE (DIFF):** optional no-profile mode and explicit unknowns are
  implemented at `plugins/unifi/scripts/site_profile.py:13-23`.
- **R11 — DONE (DIFF):** exactly three paths are defined at
  `plugins/unifi/scripts/site_profile_setup.py:71-111`.
- **R12 — DONE (DIFF):** configuration persistence and environment-first
  resolution are implemented in `plugins/unifi/scripts/site_profile.py`.
- **R13 — DONE (DIFF):** discovery-only context returns unknown intent and
  drift emits no intended-state findings without a profile.
- **R14 — PARTIAL (DIFF):** raw inventory is absent from the repository and
  output persistence is guarded, but F-08 disproves the absolute credential
  exclusion claim.
- **R15 — DONE (DIFF):** `plugins/unifi/references/site-profile.md:140-149`
  describes the private Infiquetra arrangement as one optional example, not a
  portable requirement.
- **R16 — DONE (DIFF):** Fleet Core has manifest, provenance, changelog,
  README, source, tests, and compatibility declaration.
- **R17 — DONE (DIFF):** only `retry_backoff` is ported and
  `plugins/fleet-core/DEFERRED.md` inventories the remainder.
- **R18 — DONE (DIFF):** `plugins/unifi/fleet-bundle.json` declares two
  generated destinations and both are present.
- **R19 — PARTIAL (DIFF):** current bundles are stamped and body tampering is
  rejected, but F-05 shows provenance fields can be removed to disable
  stale-source enforcement in CI.
- **R20 — DONE (DIFF):** portable clients import their local bundle; no
  dependency field, `FLEET_COMMONS_ROOT`, or Claude runtime discovery remains.
- **R21 — DONE (DIFF):** the closed declaration supports an extensible list of
  modules and tests cover two-module planning.
- **R28 — DONE (DIFF):** root Agent Plugins manifests and the
  `com.infiquetra.claude/` extension layout are present.
- **R29 — DONE (DIFF):** portable skill frontmatter has permitted fields and
  matching parent names.
- **R32 — DONE (DIFF):** Fleet Core provenance retains upstream custody and
  version `0.25.0`.
- **R33 — DONE (DIFF):** every named Fleet Core release surface exists.
- **R34 — DONE (DIFF):** the bundle declaration uses its own closed schema
  rather than extending the Agent Plugins manifest.
- **R35 — PARTIAL (DIFF):** source and generated-output digest domains exist,
  but F-05 makes the source domain optional in the CI validator.
- **R36 — DONE (DIFF):** the profile reader is standard-library JSON.
- **R37 — DONE (DIFF):** `site_profile_setup.py` presents and remembers the
  three paths.
- **R38 — DONE (DIFF):** the Claude adapter carries
  `skills/unifi-network/scripts/site_profile_loader.py`.
- **R39 — DONE (DIFF):** generated proposals set every subject intent facet to
  unknown and leave policies empty; `tests/test_discover.py:312-336` checks it.

### Compatibility and safety

- **R22 — PARTIAL (DIFF):** all ten clients received one bounded assessment,
  but F-01 proves it was not the final package.
- **R23 — DONE (DIFF):** all ten records have one allowed status, reason, and
  evidence.
- **R24 — DONE (DIFF):** failed and adapter outcomes pass validation.
- **R25 — DONE (DIFF):** `README.md:34-40` records the pause and no
  client-specific remediation.
- **R26 — DONE (DIFF):** matrix commands contain no `--confirm` or mutating
  package operation.
- **R27 — DONE (DIFF):** discovery/drift refuse repository output, and the
  matrix persists no raw controller output.
- **R43 — DONE (DIFF):** ten clients each carry placement, discovery, load, and
  invocation: 40 stage records.
- **R44 — DONE (DIFF):** the public artifact contains counts/digests and
  redacted commands; manual and pattern searches found no actual controller
  address, hostname, hardware address, credential, or raw inventory.

### Cross-repository process and release

- **R30 — UNVERIFIABLE (EXTERNAL-STATE):** commit history shows the unit merges,
  but the reviewed tree cannot prove every Herdr-dispatched unit used Saga
  `backend: inline` with no nested orchestration.
- **R31 — DONE (CROSS-REPO):** the named target, upstream, and home-lab commits
  exist and the upstream evidence records waiting for the deployment receipt
  rather than using ambient profile access.
- **R40 — PARTIAL (CROSS-REPO/EXTERNAL-STATE):** release tri-lock and activation
  are present at upstream commit `0eb1fe04`; installed version/digest readback is
  explicitly outstanding (F-02).
- **R41 — NOT-DONE (EXTERNAL-STATE):** upstream transition evidence lines 21-35
  and 287-307 say the required fresh-session installed-release proof was not
  performed (F-02).
- **R42 — DONE (CROSS-REPO):** upstream transition evidence lines 300-309 names
  trigger, prior version, refresh, and repeated proof.
- **R45 — DONE (CROSS-REPO):** upstream commit `0eb1fe04` contains
  `tests/test_unifi_docs_match_code.py` and the named repaired surfaces.

**COMPLETION: 36/45 DONE, 7 PARTIAL, 1 NOT-DONE, 0 CHANGED, 1 UNVERIFIABLE.**

## Verification and coverage

All repository-provided checks pass on the reviewed tree:

- `python3 scripts/check_repo.py` — passed.
- `python3 -m unittest discover -s tests -v` — 280 passed.
- `python3 -m pytest tests -q` — 290 passed.
- `python3 scripts/bundle_fleet_module.py --check` — passed.
- `python3 scripts/check_compatibility_matrix.py` — 10 clients, 40 stage
  results, passed.
- `git diff --check 8824fea..95de0d5` — passed.
- Working tree remained clean.

Those green results do not negate F-01, F-04, or F-05; each finding identifies
an input the corresponding validator does not bind or reject.

Suppressed count: 1 validator-rejected candidate and 0 confidence-gate
suppressed candidates. The rejected candidate concerned historical prose that
names topology categories and counts without actual ranges, host identity, or
camera/wireless values; independent validation found it did not republish
site-identifying topology.

No ambient-machine-state finding survived. The drift tests isolate both
`UNIFI_SITE_PROFILE` and the XDG configuration rung at
`tests/test_drift.py:7-15`, and the entrypoint tests use temporary stubs and a
sanitized environment. No actual site identifier was admitted: public examples
are placeholders, RFC documentation values, or synthetic fixtures.

Testing gaps correspond directly to the findings: final-tree matrix binding,
post-activation installed readback, observed-policy discovery, unlisted and
duplicate provenance paths, missing bundle stamp fields, unsafe previous
manifest paths, credentials in allowed text values, and date-form
`Retry-After`.

> `outcome: repairs_requested`; `next_action: return structured fixes to Work
> and release owners`. Fix order: contain F-06 first; close F-04/F-05; correct
> F-03; resolve F-07/F-08/F-09; complete F-02; then rerun the final package
> through all ten clients for F-01.
