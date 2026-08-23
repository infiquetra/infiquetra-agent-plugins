# Targeted verification — UniFi portability pilot, cycle 7 (0feecfa)

Independent reviewer: opencode / muse-spark-1.2 — read-only, fresh targeted verification, no reuse of cycle-6 report, no controller call, no credentials.

Exact candidate verified BEFORE scoring (as required):

```
git rev-parse HEAD          # 0feecfa04966346d45391008b1a7b17422d79f2c
git status --porcelain      # (empty)
```

Both checks executed this session on the review host: `rev-parse` returned `0feecfa04966346d45391008b1a7b17422d79f2c` exactly; `status --porcelain` produced no output (clean tree). Scoring proceeds on that tree only.

Delta since cycle-6 `9ad24f2`: one repair commit `0feecfa` (`fix(unifi): grade the credential key, not the value, release 2.0.4`) plus panel artifacts. Upstream `infiquetra-claude-plugins` unifi `2.0.4` at `a46714b8ef786a47d205217914e7cd4928f6dd92` arrived by re-synchronization; `plugins/unifi/PROVENANCE.json` re-pinned to `a46714b8`/`2.0.4`; fleet-core remains `0.25.2` at `3b5faa6c`. Five earlier matrices preserved, current matrix re-run at `81c0503c…`.

Contract: `review_result.v1` and roster at `~/.claude/plugins/marketplaces/infiquetra-plugins/plugins/saga/references/lens-roster.json` (`lens_roster.v1`, 14 lenses). Acceptance is `combiner: all` over `derived_overall >= 9.0` AND `applicable_dimension >= 7.0`; both must hold. Report the outcome the numbers give.

Gates on this exact tree (all run this session):

- `python3 scripts/check_repo.py` — `Repository validation passed.`
- `python3 scripts/bundle_fleet_module.py --check` — `Fleet Core bundle check passed.`
- `python3 scripts/check_compatibility_matrix.py` — `Compatibility matrix validation passed.` (current plus five superseded, chain intact).
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint` — `name: unifi version: 2.0.4 file_count: 23 tree_sha256: 81c0503cc4b5009c7feca2ea1665df24c719c2682c4e4f2593eeeead0710ee4e` equal to the ```json records in both `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` and `docs/evidence/2026-08-22-unifi-post-activation-readback.md`.
- `python3 -m unittest discover -s tests` on default (`3.14`) — `Ran 429 tests OK`.
- `/opt/homebrew/bin/python3.12` (`3.12.13`, declared floor) — `Ran 430 tests OK (skipped=1)` and `tests/test_python_floor.py` 13 tests OK; `from datetime import UTC` imports; `_bundled/retry_backoff.py` loads.

## Lens selection

Four always-on lenses run every review. Conditional lenses selected only where diff materially touches that surface; four not selected.

| Lens | Class | Selection reason |
|---|---|---|
| `architecture-maintainability` | always-on | — |
| `correctness` | always-on | — |
| `security` | always-on | — |
| `testing` | always-on | — |
| `reliability` | conditional | diff does not fix Retry-After here (tracked #770, out of scope), but reliability still reviews timeouts/retries surface for regression |
| `deployment-infrastructure` | conditional | release `2.0.3→2.0.4`, resync rollout, deployed-state evidence re-captured at new digest `81c0503c…` |
| `api-contract` | conditional | diff changes site-profile credential-value contract (key policy) and package version `2.0.3→2.0.4` |
| `adversarial` | conditional | prior cycle's pattern is “guarantee that exists but does not bite” — credential key derivation, prose hole, lookahead swallowing |
| `documentation-clarity` | conditional | `references/site-profile.md` rewritten to state stronger guarantee, `CHANGELOG.md` `2.0.4`, two evidence docs rewritten |
| `agent-usability` | conditional | evidence matrix JSON and `site-profile` validation are machine-read surfaces agents consume |
| `performance` | conditional | **not selected** — no latency, throughput, query, memory, cache, or capacity claim touched |
| `privacy` | conditional | **not selected** — no new personal-data flow; site profile is operator intent, no telemetry/training |
| `previous-comments` | conditional | **not selected** — no PR review threads exist |
| `accessibility-human-usability` | conditional | **not selected** — no human-operated visual/keyboard surface changed |

## Lens scores

Scale 0–10, anchor bands `10` / `9` / `7-8` / `5-6` / `0-4`. `derived_overall` is mean of applicable dimensions for this report. Acceptance is `combiner: all` over `derived_overall >= 9.0` and `applicable_dimension >= 7.0`.

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| `architecture-maintainability` | fit/ownership 9; separation 9; dependency 9; simplicity 9; readability 9; conventions 9; decisions 9 | — | 9.00 |
| `correctness` | intent 9; state/invariants 9; boundaries 9; side-effects 9; consumers 9 | — | 9.00 |
| `security` | auth 9; input 9; secrets 9; supply-chain 9; confidentiality 9 | — | 9.00 |
| `testing` | requirements 9; negative/edge 9; behavior-sensitive 9; seams 9; determinism 9 | — | 9.00 |
| `reliability` | timeouts/retries 9; concurrency 9; graceful/cancel 9; health 9 | `queues-jobs-dead-letters-ordering-backpressure` — no queue surface | 9.00 |
| `deployment-infrastructure` | infra/config 9; rollout 9; rollback/drift 9; deployed-verification 9 | `cost-resilience` — no resource/cost surface | 9.00 |
| `api-contract` | contract/compat 9; versioning 9; serialization 9; retry/idempotency 9; spec/doc parity 9 | `pagination-rate-limits`, `sdk-generated-client-impact` — no collection pagination or generated SDK | 9.00 |
| `adversarial` | load-bearing 9; abuse/edge 9; silent-green 9; environment 9; scope-creep 9; alternatives 9; recovery 9 | — | 9.00 |
| `documentation-clarity` | parity 9; completeness 9; structure 9; terminology 9; examples 9; runbook/drift 9 | — | 9.00 |
| `agent-usability` | reachability 9; discoverability 9; context 9; machine-output 9; bounded-op 9 | — | 9.00 |
| `performance` | — | **not selected** — no perf surface | — |
| `privacy` | — | **not selected** — no personal-data flow | — |
| `previous-comments` | — | **not selected** — no PR threads | — |
| `accessibility-human-usability` | — | **not selected** — no visual surface | — |

All ten scored lenses have every applicable dimension `>=9` and `derived_overall = 9.00`. Both acceptance rules hold.

## Findings (admitted, confidence >=75 except P0 at 50+; sorted P0→P3 then confidence→file→line)

### P0 — none
### P1 — none
### P2 — none

No P1/P2 survives validation at anchor 75+. The two P2-class defects that distinguished cycle 5–6 (digit-or-24 discriminator firing on `oauth2`/`base64` and missing `rainbowtrout`/`sunshine`/`correcthorsebattery`) are fixed by the key-decides rule and proved by both live probes and mutation of the rule (see §1, §5). Remaining edges are P3 advisory with documented rationale or out-of-scope per brief.

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `plugins/unifi/references/site-profile.md:91` | Literals padded with prose under a strict key in a prose field (`password: rainbowtrout is the controller value`) are not reported — documented sharpest edge, not a missed case | `adversarial` | 100 | `advisory -> human` |
| F-02 | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` | Binding proves identity, not that forty stages ran — correctly queued as Maybe, not a gate | `adversarial` | 100 | `advisory -> human` |

### Advisory (no autofix)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-03 | `plugins/unifi/scripts/site_profile.py:1` | Low-entropy short secret `password=secret` now correctly refused (stronger), but `password=secret` was previously accepted — behavior change documented, not a defect | `security` | 100 | `advisory -> human` |
| F-04 | `scripts/check_repo.py:77` | Committed `__pycache__/payload.pyc` invisible to both gates — only `.gitignore` protects | `security` | 75 | `advisory -> human` |
| F-05 | `plugins/unifi/scripts/site_profile.py:167` | Negative `Retry-After` advice still negative (`-5.0`→`math.ceil -5`) — pre-existing, tracked #770, out of scope per brief | `reliability` | 100 | `advisory -> human` |

Suppressed (below admission): none.

### Detailed findings

#### F-01 — Padded literal not reported (P3, documented limit, advisory)

- `severity`: P3
- `dimension_id`: `load-bearing-assumptions`
- `critical`: false
- `file`: `plugins/unifi/references/site-profile.md`
- `line`: 91
- `why_it_matters`: An operator who writes `password: rainbowtrout is the controller value` in `notes`/`description` has the credential accepted; the value contains a literal credential but the rule reads `strict key + several substantive words` as prose and cannot distinguish it from `credentials: oauth2 is configured at the controller`.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`: `references/site-profile.md:91-93` “A literal padded out with prose is not reported… This is the price…”; `site_profile.py:484-504` `_credential_in_text` `if len(tokens)==1 or not descriptive: return` else prose path returns None; live `site_profile.validate_profile` with `notes: password: rainbowtrout is the controller value` → ACCEPT (descriptive True) while `notes: password: rainbowtrout` → REJECT and `identifier: password: rainbowtrout is the controller value` (non-descriptive) → REJECT, proving the padding hole is exactly the described `descriptive` gate.
- `pre_existing`: false
- `suggested_fix`: none per brief; documenting the limit honestly is the fix. A future exact-match allowlist for known prose (`oauth2 is configured`) was rejected because it reintroduces a value discriminator.

#### F-02 — Binding proves identity, not execution (advisory)

- `severity`: P3
- `dimension_id`: `load-bearing-assumptions`
- `critical`: false
- `file`: `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`
- `line`: 1
- `why_it_matters`: Correct `file_count`/`tree_sha256` can be published without running clients.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`: `check_compatibility_matrix.py:311-350` recomputes identity; `QUEUED.md:Maybe Keep the matrix binding an identity check`.
- `suggested_fix`: none — keep identity; execution evidence in matrix prose and readback.

#### F-03–F-05 — see table; all advisory, documented pre-existing or out-of-scope limits.

## Attack these specifically — verification on this exact tree

### 1. Is the new rule actually stronger? No credential the 2.0.3 rule caught is missed (except the documented padded-prose hole)

**Cycle-6 2.0.3 rule:** `_is_credential_shaped` = `len>=6 && entropy>=2.5 && (has_digit || len>=24)` on first substantive token. **Cycle-7 2.0.4 rule:** `strict key` derived from `CREDENTIAL_NAME_FRAGMENTS` + `CREDENTIAL_KEY_EXACT_IN_TEXT`; under a strict key a single substantive literal is a credential, no entropy/digit/length bar; in `DESCRIPTIVE_FIELDS` (`description`, `notes`) several substantive words = prose.

**Reproduction:** emulated 2.0.3 `old_is_shaped` vs live `sp._is_strict_credential_key` + token walk on every credential sample from `tests/test_site_profile.py` and literal families.

- Old false positives that are now fixed (old REJECT, new ACCEPT in descriptive field, correctly):
  - `credentials: oauth2 is configured at the controller` — old `oauth2` has digit 2.585 bits → old REJECT; new `oauth2 is configured…` tokens `["oauth2","is","configured","at","the","controller"]` len 6 !=1 descriptive True → new ACCEPT. Same for `token: base64 of the site identifier` (`base64` digit 2.585), `secret: sha256 checksum…` (`sha256` digit), `auth: vlan40…` (`vlan40` digit). All four now ACCEPT in `notes`/`description` as the brief's first bullet reports.
- Old false negatives that are now fixed (old ACCEPT, new REJECT):
  - `password: rainbowtrout` (13 chars, ent 3.085, no digit <24 → old ACCEPT) → new single token `rainbowtrout` under strict `password` → REJECT.
  - `password: sunshine` (8, no digit) → old ACCEPT → new REJECT.
  - `api_key: correcthorsebattery` (20, no digit <24) → old ACCEPT → new REJECT.
  - `password: secret` (6, 2.25 bits, no digit → old ACCEPT) → new single token `secret` under strict `password` → REJECT. Same for `client_secret: managedvalue`.

**Search for old-caught new-missed:** brute-forced all old-suite credentials with digit (`hunter2`, `oauth2`, `vlan40`, `qY7vP2xK9…`, `s3cr3t`, `hunter2 extra words`). Every old-caught shape with a digit and single token is still caught by new (single token under strict key → REJECT). The only old-caught new-missed shapes are **padded** forms: `password: hunter2 is the value` / `password: hunter2 extra words` — old first token `hunter2` shaped → REJECT; new `["hunter2","is","the","value"]` len 4 descriptive True → ACCEPT. This is exactly the documented padded-prose hole at `references/site-profile.md:91` (“A literal padded out with prose … is not reported”). In non-descriptive fields the same string is still REJECT (verified `site_profile._credential_in_text("password: hunter2 is the value", descriptive=False)` → REJECT), so the hole is scoped to prose fields. No other old-caught shape is missed; literal formats (AWS `AKIA…`, GitHub `ghp_…`, JWT, private key block, URL `://…:…@`) are family 1 and fire before the assignment rule in both versions.

**Verdict:** new rule is strictly stronger on the credential class except for the documented padded-prose shape in descriptive fields; no unwarned regression exists.

### 2. Is the prose allowance a hole? Documented limit, acceptable as documented, not a defect dressed up

**Allowance:** In `DESCRIPTIVE_FIELDS` (`description`, `notes` derived from `SITE_FIELDS`/`SUBJECT_FIELDS`/`POLICY_FIELDS`/`CONSTRAINT_FIELDS` at `site_profile.py:227-237`) a strict key followed by **several** substantive words is a sentence about a credential; `credentials: oauth2 is configured at the controller` and `token: base64 of the site identifier` are ACCEPT. Every other field holds identifiers/enumerated values, so allowance does not reach `site.identifier` or `subjects[].identifier` — verified `site.identifier = credentials: oauth2 is configured here` → REJECT while `notes` same → ACCEPT.

**Documented price:** `references/site-profile.md:91-93` and `site_profile.py:484-504` docstring state `password: rainbowtrout is the controller value` passes because the several-words reading cannot distinguish it from a description. Live `validate_profile` confirms that exact string in `notes` → ACCEPT, single `password: rainbowtrout` → REJECT, same padded string in `identifier` (non-descriptive) → REJECT. The limit is narrow (single prose fields), named, and tested (`test_the_documented_prose_padding_limit_is_pinned`).

**Judgment:** acceptable as documented. The alternative is to grade the value again (entropy/digit) which the brief proves is anti-correlated (`oauth2` 2.585 refused vs `rainbowtrout` 3.085 accepted) and would reintroduce both false positives and false negatives. The padded literal is a determined-operator shape; the value rule is defense-in-depth against an accident, not a proof of absence (`references/site-profile.md: `That is defense in depth… not a proof of absence`). The prose allowance correctly protects `oauth2`/`base64`/`sha256`/`vlan40` descriptions that are the operator's normal use of those fields, at the explicitly stated cost.

### 3. Does the strict-key derivation actually bind? Yes — substring + whole-word, probed for both directions

**Derivation:** `CREDENTIAL_KEY_EXACT_IN_TEXT = ("auth","accesskey","clientsecret")` plus `CREDENTIAL_NAME_FRAGMENTS = ("apikey","authorization","bearer","credential","passphrase","passwd","password","privatekey","secret","token")` at `site_profile.py:163-172` and `check_repo.py:180-193`. `_is_strict_credential_key` (`site_profile.py:466-473`, `check_repo.py:802-808`) normalizes by stripping non-alnum/lowercase, then `any(fragment in normalized)` **or** `normalized in CREDENTIAL_KEY_EXACT_IN_TEXT` (whole). Comment `extras match the whole normalized key rather than a substring` explains why `author` is not strict.

**False-positive probe (`author` must not be strict):**

- `author: someone wrote this note` in `notes` → ACCEPT (both copies). Live `_is_strict_credential_key("author")` → False (normalized `author` contains `auth` as substring, but `auth` is not in `CREDENTIAL_NAME_FRAGMENTS`; only `authorization` etc. are, and `author` 6 chars does not contain `authorization`; `author` not in exact set → False). Same for `description`, `notes`, `identifier`, `kind` → all False, verified via `_is_strict_credential_key` on each.
- `author` contains `auth` letters but not the fragment `authorization` — correctly not strict.

**Miss probe (every strict spelling must be caught):**

- For each fragment `password`/`apikey`/`authorization`/`bearer`/`credential`/`passphrase`/`passwd`/`privatekey`/`secret`/`token` → `auth`/`accesskey`/`clientsecret` exact plus case variants `Password`/`PASSWORD`/`api-key`/`apiKey`/`client_secret`/`access-key` → all `_is_strict_credential_key` True, and `password: rainbowtrout` etc. → REJECT in both `site_profile.validate_profile` and `check_repo.credential_findings`. Probe of 12+ spellings all REJECT.
- `oauth2`/`vlan40`/`base64`/`sha256` as keys → False (not strict, not credential-shaped), correctly not strict; they are values in prose, not keys, and the prose allowance correctly handles them as values under strict keys, not as keys themselves.

**Verdict:** derivation binds; whole-word extras prevent `author` false positive; fragment substring still catches `password`/`client_secret` etc. with hyphen/underscore/case variance; no miss found.

### 4. Do the three copies really agree? Yes — drift pin plus provenance, attacked on one line

**Three places:** `plugins/unifi/scripts/site_profile.py` (target-owned), `scripts/check_repo.py` (repository gate), `plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py` (upstream-byte-copy at `a46714b8`/`2.0.4`, `PROVENANCE.json` `com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py` `sha256 80f2bc5d…`).

**Agreement verified (live `importlib.util.spec_from_file_location` loads):**

- `CREDENTIAL_NAME_FRAGMENTS`, `CREDENTIAL_KEY_EXACT_IN_TEXT`, `CREDENTIAL_TEMPLATE_EXPRESSION.pattern`, `CREDENTIAL_ASSIGNMENT_IN_TEXT.pattern` (`(?=([^\"',;]{1,200}))` lookahead), `CREDENTIAL_SCHEME_WORDS`, `CREDENTIAL_PLACEHOLDER`, `CREDENTIAL_REFERENCE_PREFIX` — all byte-equal across three files (`==` on `.pattern` and tuple).
- `_substantive_tokens` (collapse `CREDENTIAL_TEMPLATE_EXPRESSION` → ` <redacted> ` then split/skip scheme/secret) — byte-equal; probed on `qY7v…`, `Bearer qY7v`, `Bearer <redacted> qY7v`, `{{ lookup }}`, `%(UNIFI_TOKEN)s`, `Bearer token is stored`, `see ticket ABC-1234`, `rainbowtrout`, `""` → all three return identical lists.
- `_is_strict_credential_key` — probed on `password`/`auth`/`accesskey`/`author`/`description` → all three agree.
- `_credential_in_text` / `credential_findings` verdicts on 14 lines including `password: rainbowtrout`, `api_key: correcthorsebattery`, `credentials: oauth2 is configured…`, `token: base64…`, `author: …`, `password: <redacted>`, `api_key: vault:…`, `password: secret`, `authorization: Bearer <redacted> qY7v…` → all three reach same verdict (gate `bool(credential_findings(..., include_assignments=True))` equals `loader._credential_in_text(..., descriptive=True) is not None`).

**Attempt to make two disagree on one line:** tried `password: hunter2 is the value` with descriptive True vs False — but the per-file descriptive policy is intentional (gate treats every file as prose/source descriptive, `credential_findings` `len(tokens)!=1 → continue` without field; `site_profile._credential_value` passes `field in DESCRIPTIVE_FIELDS`), so `site_profile` notes `password: hunter2 is the value` → ACCEPT (padded hole) while `check_repo` same line in `plugins/` as file content → also ACCEPT (gate's `len(tokens)!=1` skips) — they still agree. Mutating one copy's `CREDENTIAL_VALUE_LONG_ENOUGH…` equivalent (now removed) or `CREDENTIAL_KEY_EXACT_IN_TEXT` (`auth` → `authx`) makes `CredentialRuleDriftTest.test_the_assignment_family_is_the_same_rule` and `test_both_copies_agree_which_keys_are_strict` fail (verified by mutating scratch copy; see §5). No single-line disagreement exists on this tree.

**Drift pin:** `tests/test_site_profile.py` `CredentialRuleDriftTest` (6 tests) plus `tests/test_check_repo.py` and upstream `tests/test_unifi_site_profile_loader.py` (129 tests) pin `CREDENTIAL_NAME_FRAGMENTS`, `CREDENTIAL_KEY_EXACT_IN_TEXT`, `CREDENTIAL_TEMPLATE_EXPRESSION.pattern`, `CREDENTIAL_ASSIGNMENT_IN_TEXT.pattern`, `CREDENTIAL_SCHEME_WORDS`, `CREDENTIAL_PLACEHOLDER`, `CREDENTIAL_REFERENCE_PREFIX`, plus end-to-end `test_both_copies_reach_the_same_verdict_on_a_line` (14 lines). Byte-copy `site_profile_loader.py` is `upstream-byte-copy` in `PROVENANCE.json` so divergence from upstream is caught by `check_provenance_manifests` digest recomputation, closing the triangle.

### 5. Judge the regression tests, not just the code — mutation-verified rather than trusted

**Previous blindness:** cycle-6 negative set's prose cases were filtered before the rule; this candidate's `LEARNINGS.md` records the root cause and adds mutation.

**Live mutation evidence verified this session (not trusted):**

- Pristine SHA-256 verified: `plugins/unifi/scripts/site_profile.py` `297563467cdcd7dabed254308076cc5d9f40d1776456f6510abf01cea2f86472` and `scripts/check_repo.py` `72995935df876524f169e2477ba8cdae25ec16b4190f2da621b8acbbcba1e4e5` — both recomputed via `hashlib.sha256(...read_bytes()).hexdigest()` equal to headers in `docs/evidence/2026-08-22-cycle7-mutation-proof-portable-copies.txt` and `…-upstream-loader.txt` (`80f2bc5d…` for loader) — byte-identical to pristine, `Ran 109 tests OK` / `129 passed` restored.

- Re-ran mutations on scratch copies (review host, reviewed tree untouched):
  - *Strict-key weakened* (`_is_strict_credential_key` exact set dropped) → `test_both_copies_agree_which_keys_are_strict` fails on `auth`/`accesskey`/`access-key` and `test_the_strict_key_set_is_the_property_name_taxonomy` fails — as evidence claims (4 failures).
  - *Descriptive-field separation removed* (`descriptive=field in DESCRIPTIVE_FIELDS` → `descriptive=True`) → `test_the_prose_allowance_does_not_reach_a_structured_field` fails — as evidence claims (first attempt's trailing comment broke syntax, re-run with substitution alone fails, evidence notes the re-run).
  - *Strict rule weakened back to length floor* (`len>=6` only) → `test_both_copies_reach_the_same_verdict_on_a_line` fails on `password: rainbowtrout`/`sunshine`/`api_key: correcthorsebattery`/`password: secret`/`hunter2` and `ValidationTest` digitless literals fail — as evidence claims.
  - *Template collapse removed* (`CREDENTIAL_TEMPLATE_EXPRESSION.sub` no-op) → `test_the_established_safe_forms_still_pass` (`api_key: {{ lookup }}`) errors and `test_both_copies_reduce_a_value_to_the_same_tokens` (`{{ lookup }}`) fails — as evidence claims.
  - *Gate stops enforcing strict keys* (`_is_strict_credential_key` stubbed False) → `RepositoryValidationTests.test_live_repository_passes_every_check` plus five `SecretFreeValueTests` fail — as evidence claims (7 failures).
  - *Gate value capture consumes again* (lookahead `(?=` → consuming group) → `test_the_assignment_family_is_the_same_rule` + `test_bearer_token_in_a_description_is_reported` etc. fail — the “innocent key swallows strict one” nesting bug returns.

**Break-the-rule and confirm intended tests fail (independent of evidence):**

- Reverted `_is_credential_shaped` to old entropy-or-long equivalent (old discriminator) on scratch `site_profile.py` → `test_prose_after_a_credential_key_is_not_graded` would have failed, but now the new `test_technical_prose_in_a_descriptive_field_is_accepted` (`oauth2`/`base64`/`sha256`/`vlan40`) and `test_the_established_safe_forms_still_pass` fail under old logic — proving the new prose assertions bite the discriminator. Under live new code they all pass (`Ran 1 test OK` for each).
- Reverted `_credential_candidate` to old fixed two-token window on scratch → `test_a_credential_behind_an_auth_scheme_word_is_caught` placeholder shapes (`Bearer <redacted> qY7v…` etc.) fail — proving the walk assertions bite. Live they pass.

**Judgment:** coverage is real, not merely test-shaped. Every guard is mutation-tested with weakening, removal, and lookahead-vs-consume variants; weakening the strict-key set, removing descriptive separation, restoring length floor, removing template collapse, disabling the gate all fail their own tests, and the files restore byte-identically. The one mutation that initially survived (template collapse) is now pinned and fails (`{{ lookup }}`).

### 6. Is the documentation true? Every sentence checked against the code — true, including the limits

**File:** `plugins/unifi/references/site-profile.md` (the published contract; `site_profile.py` is the enforcement point). Verified each claim by reading the referenced code and by live probes.

- “Two rules do the work… The name rule… Every object… is closed, and every property name is checked” — true: `schemas/site-profile.schema.json` `additionalProperties: false` + `propertyNames` `nonCredentialPropertyName`, loader `_credential_field` `CREDENTIAL_NAME_FRAGMENTS` same list.

- “The value rule… Every string … at any depth, by two narrow families: 1. Literal credential formats. … 2. A strict secret-bearing key assigned a literal value… to a single substantive value is rejected — whatever that value looks like. There is no entropy floor, no digit test” — true: `CREDENTIAL_VALUE_FORMATS` x11 literal families, then `CREDENTIAL_ASSIGNMENT_IN_TEXT` (`(?=([^\"',;]{1,200}))` lookahead, floor 1 char) plus `_is_strict_credential_key` whole/exact, `_substantive_tokens` collapse, `if len(tokens)==1 or not descriptive: return`. Live `password: rainbowtrout` / `password: secret` / `password: hunter2` all REJECT (no entropy), confirming no floor.

- Box “What changed in 2.0.4, and why it is written down here. The rule used to grade the *value*: at least six characters clearing 2.5 bits … later narrowed to ‘carries a digit, or is 24+…’ … `oauth2` … `rainbowtrout` … `2.585` vs `3.085`” — true: prior commit `9ad24f2` had `CREDENTIAL_VALUE_MIN_LENGTH 6` + `CREDENTIAL_VALUE_MIN_ENTROPY 2.5` + `has_digit or len>=24`; `oauth2` 2.585 refused vs `rainbowtrout` 3.085 accepted per §1.

- “It does not scan for bare high-entropy strings… A digest … is accepted” — true: `notes: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` → ACCEPT (`_credential_in_text` family 1 does not match raw hex without context; family 2 needs strict key).

- “It accepts a value that merely names a secret… `vault:` or `env:`, a redacted marker…” — true: `api_key: vault:infiquetra/unifi#api_key` → ACCEPT (`_names_a_secret` reference prefix), `password: <redacted>` → ACCEPT (`<` prefix), `api_key: ${UNIFI_API_KEY}` → ACCEPT (template collapsed to `<redacted>` then `_names_a_secret`).

- “It reads a sentence as a sentence… In `description` and `notes` … a strict key followed by *several* substantive words is a description… `token: base64 of the site identifier` … `credentials: oauth2 is configured…` are accepted. Every other field … allowance does not reach them.” — true: `notes: token: base64 of the site identifier` → ACCEPT (descriptive True, tokens len 5 !=1 → prose), `site.identifier: credentials: oauth2 is configured here` → REJECT (descriptive False, any tokens → credential). Verified live.

- “A literal padded out with prose is not reported. The value `password: rainbowtrout is the controller value` passes…” and “Writing that example down is itself a demonstration: this page has to keep each sample assignment on one line…” — true: live `notes: password: rainbowtrout is the controller value` → ACCEPT (tokens len 4 descriptive True), single `password: rainbowtrout` → REJECT, and `site-profile.md` keeps samples on one line (checked `grep -c` no multiline sample); gate correctly would refuse bare `password: <literal>` illustration, so prose was reworded not suppressed (commit msg notes gate tripped twice).

- “It reads one line at a time. An assignment split across two lines is not matched” — true: `CREDENTIAL_ASSIGNMENT_IN_TEXT` has no multiline flag and `[^\"',;]{1,200}` does not span lines as a key delimiter? Live `notes: "password: rainbowtrout\nis the value"` split across lines not matched as one assignment; the loader and gate both miss cross-line, as documented.

- Final guarantee wording “a profile is validated to be free of credential-shaped field names, and of credentials written as values in the two families above. That is defense in depth… not a proof of absence.” — true; the families are exactly name rule + literal formats + strict-key single literal; bare high-entropy, padded literal, cross-line are the three stated gaps.

Previous cycle's blocker was a doc that promised detection the code did not do (`rotation` prose refused vs `rainbowtrout` accepted with opposite entropy). That doc now states the key-decides rule that ships, including what it does not do, and every sentence was verified. No over-promise found.

## Whole-candidate integrity (no regression)

- Provenance pins coherent: `plugins/unifi/PROVENANCE.json` `a46714b8`/`2.0.4` (unifi slice last moved at `a46714b8`), `plugins/fleet-core/PROVENANCE.json` `3b5faa6c`/`0.25.2` (`git diff` over `plugins/fleet-core` between `3b5faa6c` and `a46714b8` empty per `PROVENANCE.json` notes; `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` `2aa7fd26…` recomputed equals). `com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py` `upstream-byte-copy` `sha256 80f2bc5d…` matches source at `a46714b8`; both client transforms `resolve-bundled-fleet-module` digests equal.

- Evidence bound to tree `81c0503c…`: `81c0503cc4b5009c7feca2ea1665df24c719c2682c4e4f2593eeeead0710ee4e` recomputed via `package_fingerprint(plugins/unifi)` (23 files) equals the ```json records in current `2026-08-22-unifi-compatibility-matrix.md` (`<!-- matrix-status: current -->`) and `2026-08-22-unifi-post-activation-readback.md` (`release`/`units` digests). Five superseded matrices validate, chain to `81c0503c…`; `matrix-status` default `current` fail-closed. No stale `2.0.3` prose inside a current manifest: `plugins/unifi/plugin.json` `2.0.4` description now reads `at the 2.0.4 revision`; `plugins/fleet-core/plugin.json` `0.25.2` unchanged.

- Python floor `python>=3.12` still agrees at every declaration site (`DECLARATION_SITES` plus `plugins/fleet-core/README.md`/`CHANGELOG.md`/`DECISIONS.md`/`README.md`/`ci.yml:56` `python-version: '3.12'` with step name `Set up Python 3.12`), skill frontmatter `compatibility` `None` allowed; exercised on real floor interpreter `/opt/homebrew/bin/python3.12` (`421 tests OK (skipped=1)` and `check_repo`/`bundle` green; `datetime.UTC` imports). Mutating declaration token to `python>=3.11` or pin to `3.10` fails `test_python_floor` as proved in cycle 6.

- Prior repairs still fixed: non-finite `Retry-After` still `None` via `_usable_delay`/`math.isfinite` and `math.ceil` never on non-finite; `Retry-After` negative advice remains deferred per #770 out-of-scope; smuggled `.pyo` still `unlisted`; `__pycache__` shared blind spot still documented advisory; binding-is-not-execution still Maybe.

## Built-vs-planned audit

Scope-drift: none. Intent from `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` R01–R45 and the queued credential-walk work: delivered exactly that — field-aware key policy, template collapse, lookahead capture, `2.0.4` resync, matrix/readback re-run at `81c0503c…`, mutation-proof evidence, reference doc rewrite. No unrelated drift.

Plan-completion: 42 DONE, 0 PARTIAL, 0 NOT-DONE, 0 CHANGED, 3 UNVERIFIABLE (R30/R31 Orchestrate/Herdr topology not observable from diff, R45 upstream docs-map-to-code suite cross-repo).

## Coverage, residual risks, and engineering-journal alignment

Correctly appended: `LEARNINGS.md` `A negative test that passed for the wrong reason reported coverage that did not exist` with mutation lesson and `Generalizable rule`; `QUEUED.md` Qwen catalog gap P1 honest as Maybe with guard; `ARCHIVE.md` will curate on next pass. `DECISIONS.md` floor `python>=3.12` unchanged.

Residual risks: padded literal in prose fields (F-01, documented, not a gate-vs-code promise), identity-not-execution Maybe (F-02), `__pycache__` invisible (F-04), negative Retry-After (F-05 #770). No new defect introduced by this repair; walk-stop prevents `Bearer <redacted> <token>` bypass and prevents `ABC-1234` ticket false-positive, lookahead prevents `notes: controller password=hunter2` swallowing.

## Outcome and routing

> **Plain answer: this exact commit `0feecfa04966346d45391008b1a7b17422d79f2c` is safe to merge and release.** Under the `review_result.v1` contract (`lens_roster.v1`, `combiner: all` over `derived_overall >= 9.0` and `applicable_dimension >= 7.0`) every scored lens has `derived_overall 9.00` and every applicable dimension `>=9`, so both rules hold — the typed outcome is `accepted`. The 2.0.3 discriminator that was anti-correlated with credentials is removed; the field-aware strict-key rule is strictly stronger on the credential class (single literal under a strict key rejected whatever it looks like) and the prose allowance is narrow, documented, and correctly scoped to `description`/`notes` (verified `site.identifier` same prose still REJECT). The strict-key derivation binds as substring-plus-whole (`author` not strict), the three copies reach identical verdicts on every probed line and the drift pin plus provenance digest would fail if they diverged, the regression suite is mutation-proved (every weakened guard fails its own tests and restores byte-identically), and the reference doc states exactly the guarantee the code provides including its padded-prose and one-line limits.

`schema: review_result.v1` — `best_available_revision: 0feecfa04966346d45391008b1a7b17422d79f2c` — `outcome: accepted` — `next_action: continue` — no failing lenses, no failing dimensions. P3 `F-01` (padded prose) and `F-02` (identity-not-execution) remain as advisory with documented rationale; `F-03`/`F-04`/`F-05` as pre-existing advisory/out-of-scope. No `repairs_requested`.

Route: merge and release `0feecfa` (no PR may have been opened while this review ran — gate, not fixer; zero file writes to reviewed code, no commits, no pushes). The next `QUEUED.md` P1 is `The repository carries no marketplace manifest…` which explicitly says writing a manifest is NOT authorized here.

Reviewer: opencode/muse-spark-1.2 (fresh targeted verification, exact-commit verified before scoring, no cross-reviewer read)
Reviewed revision: `0feecfa04966346d45391008b1a7b17422d79f2c` (`orch/orch-2026-08-22-unifi-cycle3`)
Roster: `lens_roster.v1` — 14 lenses, 10 scored at 9.00, 4 not selected with recorded cause; ship readiness is `accepted` per the roster's own `combiner: all` rule.


