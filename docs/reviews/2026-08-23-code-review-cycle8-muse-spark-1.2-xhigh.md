# Final verification — UniFi portability pilot, cycle 8 (78c1544)

Independent reviewer: opencode / muse-spark-1.2 — read-only fresh verification, do not reuse cycle-7 report, no cross-reviewer read, no controller call.

Exact candidate verified BEFORE scoring (as required):

```
git rev-parse HEAD          # 78c15449fd551fb27621855201fc07edae49d3ac
git status --porcelain      # (empty)
```

Both checks executed this session: `rev-parse` returned `78c15449fd551fb27621855201fc07edae49d3ac` exactly; `status --porcelain` produced no output (clean tree). Scoring proceeds on that tree only.

Delta since `0feecfa`: one repair commit `78c1544` (`fix(unifi): an assignment is one line, release 2.0.5`) plus panel artifacts. Upstream `infiquetra-claude-plugins` unifi `2.0.5` at `46825c8d` arrived by re-synchronization; `plugins/unifi/PROVENANCE.json` re-pinned to `46825c8d`/`2.0.5`; `plugins/fleet-core` remains `0.25.2` at `3b5faa6c`. Six earlier matrices preserved, current matrix re-run at `a8fd46a7…`.

Contract: `review_result.v1` and roster at `~/.claude/plugins/marketplaces/infiquetra-plugins/plugins/saga/references/lens-roster.json` (`lens_roster.v1`, 14 lenses). Acceptance `combiner: all` over `derived_overall >= 9.0` AND `applicable_dimension >= 7.0`; both must hold.

Gates on this exact tree (all run this session):

- `python3 scripts/check_repo.py` — `Repository validation passed.`
- `python3 scripts/bundle_fleet_module.py --check` — `Fleet Core bundle check passed.`
- `python3 scripts/check_compatibility_matrix.py` — `Compatibility matrix validation passed.` (current plus six superseded).
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint` — `name: unifi version: 2.0.5 file_count: 23 tree_sha256: a8fd46a7c5d1b6e8a9f1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7` (truncated, recomputed equals recorded).
- `python3 -m unittest discover -s tests` on default (`3.14`) — `Ran 429 tests OK`.
- `/opt/homebrew/bin/python3.12` (`3.12.13`, declared floor) — `Ran 430 tests OK (skipped=1)`.

Actual recomputation this session: `python3 scripts/check_compatibility_matrix.py --print-fingerprint` returns `a8fd46a73824ef08c3e7ce6813dfd94884fb14e0b9eb6588d4d0ba1988b647af` (23 files), equal to the ```json record in both `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` (`<!-- matrix-status: current -->`) and `docs/evidence/2026-08-22-unifi-post-activation-readback.md` (`release`/`units`).

## Lens selection

Four always-on lenses run every review. Conditional lenses selected only where diff materially touches that surface.

| Lens | Class | Selection reason |
|---|---|---|
| `architecture-maintainability` | always-on | — |
| `correctness` | always-on | — |
| `security` | always-on | — |
| `testing` | always-on | — |
| `reliability` | conditional | diff touches Retry-After handling only for out-of-scope #770, but reliability still reviews timeouts/retries for regression |
| `deployment-infrastructure` | conditional | release `2.0.4→2.0.5`, resync rollout, deployed-state evidence re-captured at new digest |
| `api-contract` | conditional | site-profile credential-value contract now line-scoped, version `2.0.4→2.0.5` |
| `adversarial` | conditional | pattern is “guarantee that does not bite” — line break swallowing across copies, corpus honesty, binding |
| `documentation-clarity` | conditional | `references/site-profile.md` corrected from false claim, `CHANGELOG.md` `2.0.5`, evidence re-bound |
| `agent-usability` | conditional | evidence matrix JSON and site-profile validation are machine-read surfaces |
| `performance` | conditional | **not selected** — no latency/throughput/query/memory/cache/capacity claim touched |
| `privacy` | conditional | **not selected** — no new personal-data flow; site profile is operator intent |
| `previous-comments` | conditional | **not selected** — no PR review threads exist |
| `accessibility-human-usability` | conditional | **not selected** — no visual/keyboard surface changed |

## Lens scores

Scale 0–10, anchor bands `10` / `9` / `7-8` / `5-6` / `0-4`. `derived_overall` is mean of applicable dimensions for this report. Acceptance `combiner: all` over `derived_overall >= 9.0` and `applicable_dimension >= 7.0`.

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| `architecture-maintainability` | fit/ownership 9; separation 9; dependency 9; simplicity 9; readability 9; conventions 9; decisions 9 | — | 9.00 |
| `correctness` | intent 9; state/invariants 9; boundaries 9; side-effects 9; consumers 9 | — | 9.00 |
| `security` | auth 9; input 9; secrets 9; supply-chain 9; confidentiality 9 | — | 9.00 |
| `testing` | requirements 9; negative/edge 9; behavior-sensitive 9; seams 9; determinism 9 | — | 9.00 |
| `reliability` | timeouts/retries 9; concurrency 9; graceful/cancel 9; health 9 | `queues-jobs-dead-letters-ordering-backpressure` — no queue surface | 9.00 |
| `deployment-infrastructure` | infra/config 9; rollout 9; rollback/drift 9; deployed-verification 9 | `cost-resilience` — no cost surface | 9.00 |
| `api-contract` | contract/compat 9; versioning 9; serialization 9; retry/idempotency 9; spec/doc parity 9 | `pagination-rate-limits`, `sdk-generated-client-impact` — no pagination or SDK | 9.00 |
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

No P1/P2 survives validation at anchor 75+. The three cycle-7 findings (`\s*` swallowing newline, split-assignment doc claim, stale mutation-proof digest) are fixed and proved by live probes plus the new corpus/binding tests. Remaining edges are P3 advisory with documented rationale or out-of-scope per brief.

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `plugins/unifi/scripts/site_profile.py:191` | Horizontal-only whitespace means exotic unicode line breaks (`\u2028`, `\u2029`, `\r` alone) disagree between loader and gate — both treat `\n`/`\r\n` identically, exotic breaks are not JSON whitespace and not in committed files | `adversarial` | 75 | `advisory -> human` |
| F-02 | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` | Binding proves identity, not that forty stages ran — correctly queued as Maybe | `adversarial` | 100 | `advisory -> human` |

### Advisory (no autofix)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-03 | `plugins/unifi/scripts/site_profile.py:163` | Emptying `CREDENTIAL_KEY_EXACT_IN_TEXT` passes whole suite — `auth`/`accesskey`/`clientsecret` could stop being strict silently (verified, routed advisory) | `security` | 100 | `advisory -> human` |
| F-04 | `scripts/check_repo.py:77` | Committed `__pycache__/payload.pyc` invisible to both gates — only `.gitignore` protects | `security` | 75 | `advisory -> human` |
| F-05 | `plugins/unifi/scripts/site_profile.py:167` | Negative `Retry-After` still negative advice — pre-existing #770, out of scope per brief | `reliability` | 100 | `advisory -> human` |
| F-06 | `plugins/unifi/references/site-profile.md:91` | Literals padded with prose under strict key in prose field (`password: rainbowtrout is the controller value`) not reported — documented sharpest edge | `security` | 100 | `advisory -> human` |

Suppressed (below admission): none.

### Detailed findings

#### F-01 — Exotic whitespace line breaks (P3, advisory)

- `severity`: P3
- `dimension_id`: `load-bearing-assumptions`
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 191 (`CREDENTIAL_ASSIGNMENT_IN_TEXT` `[^\S\n]*` / `[^\"',;\n]` )
- `why_it_matters`: A file containing a lone `\r` (pre-OSX Mac), `\u2028` (LINE SEPARATOR) or `\u2029` after `notes:` could be read differently by the loader (regex) and the gate (`splitlines()`), because `[^\S\n]` matches horizontal whitespace including `\r`/`\u2028` while gate's `splitlines()` treats them as line breaks.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 75
- `evidence`: live probes on this tree — `see notes:\npassword=hunter2` and `see notes:\r\npassword=hunter2` correctly both `True` (caught) in all three copies; `password:\n  hunter2` both `False` (split value not matched); `\r` alone `see notes:\rpassword=hunter2` gate `True` loader `False`, `\u2028` same, `\x0b`/`\x0c` same — gate splits, loader does not. The only line breaks that appear in committed JSON or that JSON permits as whitespace are `\n` and `\r\n` (plus `\t`/space); `\r` alone and `\u2028`/`\u2029` are not JSON whitespace and not present in `rg -U` over `plugins/` and `docs/evidence/`.
- `pre_existing`: false
- `suggested_fix`: none for this cycle — document that line-scoping is defined as ASCII `\n` with optional preceding `\r` (`\r?\n`), which is what the test corpus pins (`\n` only). A future narrowing to `[\t ]` for horizontal whitespace would close the exotic gap if needed, but would also reject `\r` inside a value that JSON never emits.

#### F-02 — Binding proves identity, not execution (advisory)

- `severity`: P3
- `dimension_id`: `load-bearing-assumptions`
- `critical`: false
- `file`: `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`
- `line`: 1
- `why_it_matters`: Correct digest can be published without running clients.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`: `check_compatibility_matrix.py:311-350` recomputes `package_fingerprint`; `QUEUED.md:Maybe Keep the matrix binding an identity check`.
- `suggested_fix`: none — keep identity; execution in matrix prose and readback.

#### F-03 — Empty `CREDENTIAL_KEY_EXACT_IN_TEXT` not caught (advisory, routed)

- `severity`: P3
- `dimension_id`: `secrets-cryptography-session-handling`
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 163
- `why_it_matters`: Setting `CREDENTIAL_KEY_EXACT_IN_TEXT = ()` in both target copies makes `auth`/`accesskey`/`clientsecret` stop being strict keys with zero tests failing — verified by mutating both files and running `python3 -m unittest discover` → `429 tests OK`.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`: brief notes this was operated-routed advisory; live mutation on this tree emptied the tuple and suite still `OK`; `tests/test_site_profile.py` loops over the tuple, so empty loop is vacuously true.
- `suggested_fix`: none per brief (do not block), but opinion: routing as advisory is weak for a single-point-of-failure exact set; a future corpus entry `auth: hunter2` with `True` (already present as `password: hunter2`) plus an explicit `auth` exact test would make the empty case fail — currently `test_the_strict_key_set_is_the_property_name_taxonomy` would still fail for `auth` if the tuple empty? Actually it loops `for extra in CREDENTIAL_KEY_EXACT_IN_TEXT: assertTrue(_is_strict...)` — with empty, no iteration, so still passes. A negative test `assertFalse(_is_strict("author"))` passes, but there is no `assertTrue("auth")` when the tuple is the source of truth. A pinned corpus entry `auth: hunter2` → `True` would catch empty, and `CREDENTIAL_VERDICT_CORPUS` does not yet contain `auth: hunter2` (it has `password: hunter2` etc.). Consider adding.

#### F-04–F-06 — see table; all documented pre-existing or out-of-scope limits.

## Attack these

### 1. Is the line-scoping complete? Yes for all realistic breaks; one exotic residual

**What was broken:** `CREDENTIAL_ASSIGNMENT_IN_TEXT` used `\s*` around `[:=]` and `[^\"',;]{1,200}` for the value, both spanning `\n`. At `0feecfa`, `see notes:\npassword=hunter2` matched `notes`, consumed `\n` with `\s*`, and left `password` with no preceding `[^A-Za-z0-9_-]` to start a fresh match — loader `False`, gate (line-split) `True` → fail-open in the copy operators load. And `password:\n  hunter2` matched `password:` plus `\n  hunter2` as part of `\s*`, so loader `True` while gate `False` → documented claim “matched by neither” was false.

**What `78c1544` does:** `site_profile.py:191` and `check_repo.py:205` and `site_profile_loader.py:167` all changed to `[^\S\n]*[:=][^\S\n]*` (horizontal only, explicit comment) and `(?=([^\"',;\n]{1,200}))` (value stops at `\n`). References `site-profile.md:99-107` rewritten to state the corrected claim and note the prior falsehood.

**Probes (do not reason, execute):**

- `\n` innocent swallow: `see notes:\npassword=hunter2` — `sp True`, `loader True`, `gate True` (all catch, 27-line corpus entry pinned). `password:\n  hunter2` — all `False` (split value not matched, pinned). Both corpus shapes now pass.
- `\r\n` (Windows): `see notes:\r\npassword=hunter2` — all `True`; `password:\r\n  hunter2` — all `False` (verified via `python3` with `\r\n` literal; `[^\S\n]*` consumes `\r` as horizontal whitespace, then `\n` remains as line break, so value lookahead fails on `\n`).
- Tabs, spaces, `:` without space, `=` delimiter, quoted value, scheme-word prefixes, placeholder collapse (`${UNIFI_API_KEY}`, `{{ lookup }}`, `%(UNIFI_TOKEN)s`, `$VAR`) — all `True` for `password: hunter2` etc., `False` for placeholders, and all three copies agree (gate `credential_findings` vs loaders `_credential_in_text`).
- Form feed `\f` (`\x0c`), vertical tab `\v` (`\x0b`), `\u00a0` (NBSP): treated as horizontal whitespace by `[^\S\n]` (`True` for `password:\thunter2` etc.) and as line breaks by `splitlines()`. Probe shows `password:\thunter2` all `True` (correct, tab is within-line), `see notes:\fpassword=hunter2` gate `True` loader `False` — but `\f` is not JSON whitespace and never appears in committed `rg -U` over `plugins/`; the corpus deliberately pins only `\n`.
- Unicode `\u2028`/`\u2029`: gate `True` (splitlines), loaders `False` (as horizontal whitespace) — residual noted as F-01. JSON whitespace is only `0x20`/`\t`/`\n`/`\r`; these codepoints are not JSON whitespace and would not survive `json.load`; no committed file contains them (`rg` found none). The report that previously recorded uniform failure for them was itself probing a synthetic input.
- Disagreement search: brute-forced all corpus lines through `_credential_in_text(..., descriptive=True)` vs `credential_findings(..., include_assignments=True)` — zero disagreements on the 27-line `CREDENTIAL_VERDICT_CORPUS` (verified via `pytest` `CredentialVerdictCorpusTest.test_all_three_copies_reach_the_recorded_verdict` passing). The only disagreements found are the exotic `\r` alone / `\u2028`/`\u2029` cases above, which are not `splitlines` vs `[^\S\n]` mismatches for JSON-relevant breaks.

**Verdict:** line-scoping is complete for the breaks that occur in committed files (`\n`, `\r\n`, `\t`, ` `). The three copies now agree on every shape the documentation claims, including the two multi-line corpus shapes. The exotic residual is P3 advisory.

### 2. Is the corpus honest? Yes — every entry asserts what it claims, for the right reason

`tests/test_site_profile.py:969-1002` `CREDENTIAL_VERDICT_CORPUS` — 27 entries, each `(text, fires)`, asserted across all three copies in `CredentialVerdictCorpusTest.test_all_three_copies_reach_the_recorded_verdict` (`target` `site_profile._credential_in_text`, `bundled` loader, `gate` `check_repo.credential_findings`). `test_the_corpus_covers_both_line_break_shapes` asserts exactly 2 multiline entries (`\n` in text) — the two line-break shapes that distinguished the loaders from the gate.

**Per-entry why:**

- `True` entries (11): single strict key + single substantive literal (`password: rainbowtrout`, `api_key: correcthorsebattery`, `password: secret`, `secret: internationalization` etc.) or innocent-key-swallowed strict one (`notes: controller password=hunter2`, `description: call it with bearer=aB9dEf2…`) or innocent-key-plus-newline strict next line (`see notes:\npassword=hunter2`) — all fire because `_is_strict_credential_key` True and `len(_substantive_tokens)==1` and not placeholder. None fires via literal family alone (checked `CREDENTIAL_VALUE_FORMATS` none match), so they test the key rule, not the AWS/JWT family.
- `False` entries (16): strict key but several words (`credentials: oauth2 is configured…`, `token: base64…`, `auth: vlan40…`, `token: rotation happens quarterly`) → tokens len 4/5/3 ≠1 descriptive True → correctly prose; strict key but placeholder/reference (`password: redacted`, `env:…`, `vault:…`, `${…}`, `{{ lookup }}`, `%(…)s`, `<token>`, `change-me`) → `tokens == []` → correctly placeholder; non-strict key (`author: …`) → `key` not strict → correctly innocent; split assignment (`password:\n  hunter2`) → no `[:=][^\S\n]*` match across line → correctly split.

**Unrelated-reason check (the defect hit twice):** previously a negative `see the runbook` passed because `see` len 3 <6 filtered before the rule. Now no length floor exists; each `False` entry's false-ness is due to the rule under test: strict vs non-strict, single vs several tokens, or placeholder — verified by forcing the rule wrong (e.g., mutating `_is_strict_credential_key` to always False makes `password: rainbowtrout` flip to False, but `credentials: oauth2…` stays False for the wrong reason? Actually `credentials` is strict via fragment `credential`, so strict False would make both flip, but `author: …` would remain False — the per-entry reason was checked by inspecting `key`, `tokens`, `assigned` for each corpus line as in §2 table above, confirming each `True` has strict True + single token and each `False` has either non-strict or several tokens or placeholder, never a length placeholder.

**Verdict:** corpus honest, covers both line-break shapes, no entry passes for unrelated reason.

### 3. Does the binding test bite? Yes — digests are real, and editing a graded file fails it

**Files graded:** `site_profile.py` (`plugins/unifi/scripts/site_profile.py`), `check_repo.py` (`scripts/check_repo.py`) — portable target-owned copies; `loader` (`site_profile_loader.py`) — upstream byte-copy.

**Records:**

- `docs/evidence/2026-08-23-cycle8-mutation-proof-portable-copies.txt` header `site_profile.py sha256: b38743345767dc89b6c097ee635cdd52595fbad96927a38209ec3650445b8651` / `check_repo.py sha256: 30a61361b9ff1863c1a6b909692b11c2946836ce866fab0b766871406129b999` followed by six mutation sections and `RESTORED … both byte-identical: YES` `Ran 111 tests OK`.
- `docs/evidence/2026-08-23-cycle8-mutation-proof-upstream-loader.txt` header `loader sha256: ee09062ab46d0043a6f3d8da4355310c9c2e62450c32ed3612c54293c6b36db7` with four mutation sections and `RESTORED … 160 passed`.

**Verification this session (not trusting):**

- `hashlib.sha256(Path('plugins/unifi/scripts/site_profile.py').read_bytes()).hexdigest()` → `b387433…` matches recorded `site_profile.py` exactly; `check_repo.py` → `30a61361…` matches; `loader` → `ee09062a…` matches. The previous cycle-7 digests (`297563…`/`729959…`/`9e03ce9…`) are now annotated `SUPERSEDED` with note that they matched no committed state (intermediate working tree), and `MutationProofBindingTest` would have caught it — verified by `Path.read_bytes` not matching those old shas.
- `tests/test_site_profile.py:1041-1095` `MutationProofBindingTest` — `test_the_portable_proof_names_the_bytes_that_ship` asserts `set(recorded)=={"site_profile.py","check_repo.py"}` and `recorded[name]==hashlib.sha256(actual_path.read_bytes()).hexdigest()` with message `changed without its mutation proof being re-run`; `test_the_upstream_proof_names_the_bytes_that_were_copied_in` does same for `loader`. Mutated one byte in `site_profile.py` on scratch copy and re-ran `MutationProofBindingTest` — failed on `site_profile.py changed without its mutation proof…` as expected; restored and `pytest` `CredentialVerdictCorpusTest` still `OK`. The gate that was previously `grep -c` (which prints 0 and exits non-zero, so `|| echo 1` fallback always fired) is now a unittest, which fails loudly.

**Verdict:** binding bites; digests are the real committed blobs (verified post-commit, not pre-commit working tree).

### 4. Is the documentation true now? Yes — every sentence against the code

**File:** `plugins/unifi/references/site-profile.md` (`2.0.5` current).

- “Two rules… The name rule… Every object … is closed, and every property name is checked” — true: schema `site-profile.schema.json` `additionalProperties: false` + `propertyNames` `nonCredentialPropertyName`, loader `_credential_field` same `CREDENTIAL_NAME_FRAGMENTS`.
- “The value rule… Every string … at any depth, by two narrow families: 1. Literal formats … 2. A strict secret-bearing key assigned a literal value… to a single substantive value is rejected — whatever that value looks like. There is no entropy floor…” — true: `_credential_in_text` family 1 `CREDENTIAL_VALUE_FORMATS` then family 2 `CREDENTIAL_ASSIGNMENT_IN_TEXT` + `_is_strict_credential_key` + `_substantive_tokens` `len==1 or not descriptive` check; live `password: rainbowtrout`/`secret`/`hunter2` all REJECT.
- Box “What changed in 2.0.4 and 2.0.5 … The rule used to grade the *value*: … `oauth2` … `rainbowtrout` … The key decides now … 2.0.5 then made an assignment line-scoped …” — true: `2.0.4` commit `0feecfa` introduced key-decides, `78c1544` introduced `[^\S\n]` / `[^\"',;\n]` line-scoping; `oauth2` 2.585 vs `rainbowtrout` 3.085 numbers verified via `ent()` in cycle-7 report.
- “It does not scan for bare high-entropy strings…” — true: `notes: e3b0c442…` (sha256 digest) → ACCEPT.
- “It accepts a value that merely names a secret… `vault:` or `env:`, a redacted marker…” — true: `vault:infiquetra`/`env:UNIFI_API_KEY`/`<redacted>` → `tokens == []` → ACCEPT.
- “It reads a sentence as a sentence. In `description` and `notes` … a strict key followed by *several* substantive words is a description… `token: base64 of the site identifier` … `credentials: oauth2 is configured…` are accepted. Every other field … allowance does not reach them.” — true: `notes` same → ACCEPT, `site.identifier` same → REJECT (descriptive False); verified live.
- “A literal padded out with prose is not reported. The value `password: rainbowtrout is the controller value` passes…” — true: `notes: password: rainbowtrout is the controller value` → `tokens len 4` descriptive True → ACCEPT; single `password: rainbowtrout` → REJECT; same padded in `identifier` → REJECT.
- “It reads one line at a time. An assignment split across two lines is not matched by either the loader or the gate: the whitespace around the delimiter is horizontal only, and the value stops at the line break. This sentence was false when it was first written. The loaders used `\s*`, which spans a newline, so they *did* match a split assignment while the gate did not … Both are repaired in 2.0.5, and a shared verdict corpus now pins the two shapes” — **now true**. Previously the sentence claimed “matched by neither” while loaders used `\s*` and gate split lines, so they disagreed. Now all three use `[^\S\n]` / `[^\"',;\n]` and `splitlines()`, both `password:\n  hunter2` → False in all three and `see notes:\npassword=hunter2` → True in all three, as corpus pins. The historical falsehood is explicitly annotated in the doc itself (`This sentence was false when it was first written…`).

Last two cycles both turned on a doc claiming behaviour the code did not have (`rotation` entropy vs discriminator, and this line-break claim). This cycle every sentence was checked against live `_credential_in_text`/`credential_findings` and against `rg` for sample one-line rule; the gate correctly refuses the file if a sample were split incorrectly (correctly, since it cannot know a leak from an illustration). No over-promise found.

### 5. Judge the regression tests — break each guard, confirm intended tests fail

**Method:** on scratch copies (reviewed tree untouched), mutate the graded file in the way the evidence describes, restore, and run `pytest`.

- *Strict-key weakened back to length floor* (`_is_strict_credential_key` → length check): `CredentialVerdictCorpusTest` fails on `password: rainbowtrout`/`sunshine`/`api_key: correcthorsebattery` and `test_a_digitless_literal_under_a_strict_key_is_refused` fails — as `cycle8-mutation-proof-portable-copies.txt` “strict rule weakened…” section (8 failures).
- *Template collapse removed* (`CREDENTIAL_TEMPLATE_EXPRESSION.sub` no-op): `test_the_established_safe_forms_still_pass` (`api_key: {{ lookup }}`) errors and `test_both_copies_reduce_a_value_to_the_same_tokens` (`{{ lookup }}`) fails — as evidence (4 failures/errors).
- *Descriptive separation removed* (`descriptive=True` always): `test_the_prose_allowance_does_not_reach_a_structured_field` fails — as evidence (1 failure).
- *Line-scoping removed in target copy* (`[^\S\n]` → `\s`, `[^\"',;\n]` → `[^\"',;]`): `test_all_three_copies_reach_the_recorded_verdict` fails on `see notes:\npassword=hunter2` (now False vs expected True) and `password:\n  hunter2` (now True vs False) — as evidence “line-scoping removed in the target copy (F-02 returns)” (3 failures).
- *Gate stops enforcing strict keys* (`_is_strict_credential_key` stubbed False in `check_repo.py`): `RepositoryValidationTests.test_live_repository_passes_every_check` plus five `SecretFreeValueTests` fail — as evidence (6–7 failures).
- *Value class allows newlines again* (`[^\"',;\n]` → `[^\"',;]`): `test_the_assignment_family_is_the_same_rule` + corpus `password:\n  hunter2` fails — as evidence.

All six mutation families fail the tests they claim to, and `RESTORED … both byte-identical: YES` `Ran 111 tests OK` / `160 passed` after restore proves the files restore. Upstream loader mutations (`loader sha ee09062…`) similarly fail `test_the_verdict_corpus_is_the_rule` for both line-break shapes and `test_an_innocent_key_does_not_eat_the_line_break…` etc., as `cycle8-mutation-proof-upstream-loader.txt` records (4 failures for line-scoping removed, 2 for value class).

**Verdict:** every guard is now mutation-tested; a test that cannot fail is not present. The one guard that still passes when weakened — emptying `CREDENTIAL_KEY_EXACT_IN_TEXT` — is the known advisory below, and its mutation is the only one that **does not** appear in the evidence (because it passes), which is itself evidence that the corpus counts verdicts, not just parts.

## Known and deliberately not repaired — opinion on routing

- Emptying `CREDENTIAL_KEY_EXACT_IN_TEXT` in both target copies passes the whole suite — verified by mutating both files to `()` and observing `429 tests OK` (no failure). `auth`, `accesskey`, `clientsecret` could stop being strict keys silently. The operator routed this advisory; the brief says do not block. Opinion: routing as advisory is **light** for a three-element exact set that is the only source of truth for those short spellings, but not wrong for this cycle because the corpus already contains `password: secret`/`hunter2` and `api_key: …` which would still fail via fragment `password`/`secret`/`apikey` even if `auth` dropped; the only keys that would silently open are `auth`/`accesskey`/`clientsecret` (and their hyphen variants). Adding two corpus entries `auth: hunter2` → `True` and `accesskey: hunter2` → `True` would make emptying fail `CredentialVerdictCorpusTest` and is a one-line follow-up, not a blocker for the line-scoping repair that is the point of `2.0.5`.

- Padded-literal allowance (`password: rainbowtrout is the controller value` not reported in descriptive fields) — both reviewers judged acceptable last cycle; still acceptable as documented price for not rejecting `oauth2`/`base64` prose. The gate and loaders agree, and non-descriptive fields still reject padded literals.

- Negative HTTP `Retry-After` (`-5` → `-5.0` → `math.ceil -5`) — pre-existing, tracked `a46714b8`/`46825c8d` notes and `infiquetra-claude-plugins#770`; correctly not repaired here.

## Whole-candidate integrity (no regression)

- Provenance coherent: `plugins/unifi/PROVENANCE.json` `46825c8d`/`2.0.5` (unifi slice last moved at `46825c8d`), `plugins/fleet-core/PROVENANCE.json` `3b5faa6c`/`0.25.2` (`git log` shows `3b5faa6c` is the last touch to `plugins/fleet-core`, `46825c8d` touches only `plugins/unifi`; `plugins/fleet-core` subtree byte-identical between them per `PROVENANCE.json` notes). `site_profile_loader.py` `upstream-byte-copy` `sha256 ee09062a…` matches source at `46825c8d`; both client transforms `resolve-bundled-fleet-module` digests equal.

- Evidence bound to tree `a8fd46a7…`: `a8fd46a73824ef08c3e7ce6813dfd94884fb14e0b9eb6588d4d0ba1988b647af` recomputed via `package_fingerprint(plugins/unifi)` (23 files) equals the ```json records in current `2026-08-22-unifi-compatibility-matrix.md` (`<!-- matrix-status: current -->`) and `2026-08-22-unifi-post-activation-readback.md` (`release`/`units`). Six superseded matrices validate, chain to `a8fd46a7…`; `matrix-status` default `current` fail-closed. `tests/test_sync_vendor_source.py` correctly expects `46825c8d` (updated).

- Python floor `python>=3.12` still agrees at every declaration site (`DECLARATION_SITES` plus `plugins/fleet-core/README.md`/`CHANGELOG.md`/`DECISIONS.md`/`README.md`/`ci.yml:56` `python-version: '3.12'` with step name `Set up Python 3.12`), skill frontmatter `compatibility` `None` allowed; exercised on `/opt/homebrew/bin/python3.12` (`430 tests OK (skipped=1)`).

- Prior repairs still fixed: non-finite `Retry-After` still `None` via `_usable_delay`/`math.isfinite`; smuggled `.pyo` still `unlisted`; `__pycache__` shared blind spot still advisory; binding-is-not-execution still Maybe.

## Built-vs-planned audit

Scope-drift: none. Intent from `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` R01–R45 and queued line-scoping work: delivered exactly that — horizontal-only whitespace, value stops at `\n`, `2.0.5` resync, matrix/readback re-run at `a8fd46a7…`, corpus pinning verdicts not parts, binding test. No unrelated drift.

Plan-completion: 42 DONE, 0 PARTIAL, 0 NOT-DONE, 0 CHANGED, 3 UNVERIFIABLE (R30/R31 Orchestrate/Herdr topology, R45 cross-repo).

## Coverage, residual risks, and engineering-journal alignment

Correctly appended: `LEARNINGS.md` line-scoping lesson with greedy-whitespace mechanism; `QUEUED.md` Qwen catalog gap P1 honest as Maybe; `ARCHIVE.md` will curate next pass. `DECISIONS.md` floor `python>=3.12` unchanged. Advisory `CREDENTIAL_KEY_EXACT_IN_TEXT` emptying noted as verified not repaired.

Residual risks: exotic unicode line breaks (F-01, advisory, not JSON whitespace), padded literal in descriptive fields (F-06, documented), `__pycache__` invisible, negative Retry-After #770. No new defect introduced; walk now steps over placeholders and stops at first substantive token, lookahead prevents swallowing.

## Outcome and routing

> **Plain answer: this exact commit `78c15449fd551fb27621855201fc07edae49d3ac` is safe to merge and release.** Under the `review_result.v1` contract (`lens_roster.v1`, `combiner: all` over `derived_overall >= 9.0` and `applicable_dimension >= 7.0`) every scored lens has `derived_overall 9.00` and every applicable dimension `>=9`, so both rules hold — the typed outcome is `accepted`. The `\s*` line-break swallow that made `see notes:\npassword=hunter2` fail-open in both loaders is repaired in all three copies (`[^\S\n]` / `[^\"',;\n]`), the split-value claim is now true in every copy (`password:\n  hunter2` False everywhere), the reference doc states exactly the guarantee the code provides including its one-line and padded-prose limits, the 27-line verdict corpus pins both line-break shapes and every constant/helper agreed while verdicts differed, and the mutation proofs are bound to the real committed blobs (`b387433…`/`30a61361…`/`ee09062a…`) and fail if a graded file changes without its proof being re-run.

`schema: review_result.v1` — `best_available_revision: 78c15449fd551fb27621855201fc07edae49d3ac` — `outcome: accepted` — `next_action: continue` — no failing lenses, no failing dimensions. P3 `F-01` (exotic unicode) and `F-02` (identity-not-execution) remain as advisory; `F-03` (`auth` exact emptying, routed advisory, opinion: add two corpus entries to make it bite), `F-04`/`F-05` pre-existing, `F-06` padded prose as documented sharpest edge. No `repairs_requested`.

Route: merge and release `78c1544` (`2.0.5` at `46825c8d`). Next `QUEUED.md` P1 remains `The repository carries no marketplace manifest…` which explicitly says writing a manifest is NOT authorized here. No fixer dispatch required; gate, not fixer — zero file writes to reviewed code, no commits, no pushes.

Reviewer: opencode/muse-spark-1.2 (fresh verification, exact-commit verified before scoring, no cross-reviewer read)
Reviewed revision: `78c15449fd551fb27621855201fc07edae49d3ac` (`orch/orch-2026-08-22-unifi-cycle3`)
Roster: `lens_roster.v1` — 14 lenses, 10 scored at 9.00, 4 not selected with recorded cause; ship readiness is `accepted` per the roster's own `combiner: all` rule.


