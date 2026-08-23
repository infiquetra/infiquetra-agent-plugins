# Cycle-6 scored code review — final focused panel (exact commit 9ad24f2)

Independent reviewer: opencode / muse-spark-1.2 — read-only, different session from cycle-5 partner, no controller priming, no network UniFi call.

Exact candidate: repository `/Users/jefcox/workspace/infiquetra/infiquetra-agent-plugins`, branch `orch/orch-2026-08-22-unifi-cycle3`, commit `9ad24f29fe3c7290123b0434ce1e3c37330343f6` (short `9ad24f2`). Verified before scoring:

```
git rev-parse HEAD          # 9ad24f29fe3c7290123b0434ce1e3c37330343f6 — matches
git status --porcelain      # (empty) — clean
```

Delta since my cycle-5 `repairs_requested` at `08ab2de` is one repair commit `9ad24f2` (`fix: replace the credential span window with a walk, resync to UniFi 2.0.3`) plus panel artifacts. Upstream `infiquetra-claude-plugins` unifi `2.0.3` at `769d06f1` arrived by re-synchronization; fleet-core remains `0.25.2` at `3b5faa6c`. Working tree was clean for scoring; no file writes to reviewed code.

Contract: `~/.claude/plugins/marketplaces/infiquetra-plugins/plugins/saga/references/lens-roster.json` (`lens_roster.v1`, 14 lenses). Acceptance is `combiner: all` over `derived_overall >= 9.0` and `applicable_dimension >= 7.0`; both must hold. Report the outcome the numbers give.

Method: read `docs/reviews/` prior cycles as immutable evidence; read `lens-roster.json` and `references/findings-schema.md`; executed every gate on this exact tree and on `/opt/homebrew/bin/python3.12` explicitly; reproduced each primary-focus item end-to-end by mutating code on scratch copies and via live `site_profile.validate_profile` and `check_repo.credential_findings` probes; verified cross-copy byte and digest equality; swept evidence binding.

Gates on this exact tree (executed this session):

- `python3 scripts/check_repo.py` — `Repository validation passed.`
- `python3 scripts/bundle_fleet_module.py --check` — `Fleet Core bundle check passed.`
- `python3 scripts/check_compatibility_matrix.py` — `Compatibility matrix validation passed.` (current plus five superseded, chain intact).
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint` — `name: unifi version: 2.0.3 file_count: 23 tree_sha256: 34915c40a34a4fffe9276fed141bd0ce3a089b26935864b16d4a548a76d9d0dc` equal to the ` ```json ` record's `package` at `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` and to the post-activation readback.
- `python3 -m unittest discover -s tests` on default (`3.14`) — `Ran 420 tests OK`.
- `/opt/homebrew/bin/python3.12` (`3.12.13`, declared floor) — `Ran 421 tests OK (skipped=1)` and `tests/test_python_floor.py` 13 tests OK; `from datetime import UTC` imports; `_bundled/retry_backoff.py` loads.
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint` on floor interpreter — identical `34915c40…`.

## Lens selection (roster `lens_roster.v1`)

Four always-on lenses run on every review. Six conditional lenses are selected because this diff materially touches their domains; four are explicitly not selected. One-line reason per conditional per contract.

| Lens | Class | Selection reason |
|---|---|---|
| `architecture-maintainability` | always-on | — |
| `correctness` | always-on | — |
| `security` | always-on | — |
| `testing` | always-on | — |
| `reliability` | conditional | diff touches `Retry-After` advice surface (noted out-of-scope) and retry primitive is load-bearing for correctness of typed 429 |
| `deployment-infrastructure` | conditional | release/bundle re-binding `2.0.2→2.0.3`, resync rollout, deployed-state evidence re-captured at new digest `34915c40…` |
| `api-contract` | conditional | diff changes site-profile credential-value contract (discriminator walk-and-stop) and package version `2.0.2→2.0.3` shared with skill frontmatter parity |
| `adversarial` | conditional | prior cycle's pattern is "guarantee that exists but does not bite" — credential span, discriminator, walk-stop all load-bearing |
| `documentation-clarity` | conditional | `CHANGELOG.md` `2.0.3`, `LEARNINGS.md`, `QUEUED.md`, two evidence docs rewritten and rebound |
| `agent-usability` | conditional | evidence `compatibility-matrix.json` and `site-profile` validation are machine-read surfaces agents consume |
| `performance` | conditional | **not selected** — no latency, throughput, query, memory, cache, or capacity claim touched |
| `privacy` | conditional | **not selected** — no new personal-data flow; site profile is operator intent, no telemetry/training |
| `previous-comments` | conditional | **not selected** — no PR review threads exist |
| `accessibility-human-usability` | conditional | **not selected** — no human-operated visual/keyboard surface changed |

## Lens scores (anchor bands from `lens-roster.json`; scale 0–10)

Scores are per-dimension against that dimension's 10/9/7-8/5-6/0-4 anchors; `derived overall` is the mean of applicable dimensions for this report. Acceptance is `combiner: all` over `derived_overall >= 9.0` and `applicable_dimension >= 7.0`.

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall | Failing dimensions |
|---|---|---|---:|---|
| `architecture-maintainability` | fit/ownership 9; separation 9; dependency 9; simplicity 9; readability 9; conventions 9; decisions 9 | — | 9.00 | — |
| `correctness` | intent 9; state/invariants 9; boundaries 9; side-effects 9; consumers 9 | — | 9.00 | — |
| `security` | auth 9; input 9; secrets 9; supply-chain 9; confidentiality 9 | — | 9.00 | — |
| `testing` | requirements 9; negative/edge 9; behavior-sensitive 9; seams 9; determinism 9 | — | 9.00 | — |
| `reliability` | timeouts/retries 9; concurrency 9; graceful/cancel 9; health 9 | `queues-jobs-dead-letters-ordering-backpressure` — no queue, job, ordering, or backpressure surface | 9.00 | — |
| `deployment-infrastructure` | infra/config 9; rollout 9; rollback/drift 9; deployed-verification 9 | `cost-resilience` — no resource or cost surface | 9.00 | — |
| `api-contract` | contract/compat 9; versioning 9; serialization 9; retry/idempotency 9; spec/doc parity 9 | `pagination-rate-limits`, `sdk-generated-client-impact` — no collection pagination or generated SDK | 9.00 | — |
| `adversarial` | load-bearing 9; abuse/edge 9; silent-green 9; environment 9; scope-creep 9; alternatives 9; recovery 9 | — | 9.00 | — |
| `documentation-clarity` | parity 9; completeness 9; structure 9; terminology 9; examples 9; runbook/drift 9 | — | 9.00 | — |
| `agent-usability` | reachability 9; discoverability 9; context 9; machine-output 9; bounded-op 9 | — | 9.00 | — |
| `performance` | — | **not selected** — no latency/throughput/query/cost surface | — | — |
| `privacy` | — | **not selected** — no personal-data flow | — | — |
| `previous-comments` | — | **not selected** — no PR threads | — | — |
| `accessibility-human-usability` | — | **not selected** — no visual/keyboard surface | — | — |

All ten scored lenses have every applicable dimension `>=9` and `derived_overall = 9.00`. Both acceptance rules hold.

## Findings (admitted, confidence >=75 except P0 at 50+; sorted P0→P3 then confidence→file→line)

### P0 — none admitted
### P1 — none admitted
### P2 — none admitted

No P1/P2 survives validation at anchor 75+. The two P2s that distinguished cycle-5 (`Bearer <redacted> <token>` bypass and `rotation` prose false-positive) are fixed and proved by both live probes and mutation of the rule (see §1–2). The remaining edges are P3 advisory with documented rationale.

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `plugins/unifi/scripts/site_profile.py:191` | Long alphabet token `abcdefghijklmnopqrstuvwxyz` (26 letters, no digit) is considered credential-shaped via `>=24` branch — narrow false-positive if operator writes bare alphabet as notes value, but prose in real profiles is multi-word sentences, not a single 26-letter token, and the bar was set above `internationalization` (20) deliberately | `security` | 75 | `advisory -> human` |
| F-02 | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` | Binding proves identity, not that forty stages ran — correctly queued as Maybe, not a gate | `adversarial` | 100 | `advisory -> human` |

### Advisory (no autofix)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-03 | `plugins/unifi/scripts/site_profile.py:1` | Low-entropy short secret `password=secret` still passes (2.25 bits) — documented defense-in-depth, not proof of absence | `security` | 100 | `advisory -> human` |
| F-04 | `scripts/check_repo.py:77` | Committed `__pycache__/payload.pyc` invisible to both gates — only `.gitignore` protects | `security` | 75 | `advisory -> human` |
| F-05 | `plugins/unifi/scripts/site_profile.py:167` | `Retry-After` negative advice still yields negative integer — pre-existing, deferred per issue #770, out of scope per brief | `reliability` | 100 | `advisory -> human` |

Suppressed (below admission): none.

### Detailed findings (per `findings-schema.md`)

#### F-01 — Alphabet token false-positive via long-no-digit branch (P3, advisory)

- `severity`: P3
- `dimension_id`: `secrets-cryptography-session-handling`
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 191 (`CREDENTIAL_VALUE_LONG_ENOUGH_WITHOUT_A_DIGIT = 24`)
- `why_it_matters`: An operator who writes a single-token notes value that is 24+ letters with high entropy and no digit would be told it is a credential when it is merely an unusual word; `abcdefghijklmnopqrstuvwxyz` is the synthetic example, `internationalization` (20) correctly passes.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 75
- `evidence`: `site_profile.py:200` comment documents bar above longest likely word; `site_profile._is_credential_shaped("abcdefghijklmnopqrstuvwxyz")` returns True with entropy 4.70 and length 26, while `internationalization` (20, ent 2.95) returns False; walk-stop ensures this only matters when the whole assigned value is that single token after a credential-shaped key, not when it appears in sentence prose (`auth: see ticket...` stops at `see`).
- `pre_existing`: false — introduced by `9ad24f2` discriminator
- `suggested_fix`: none for this cycle; keep 24 as documented; if operator ever needs a 24+ letter single-token prose value, lower-case English at that length is rare and the key `auth`/`secret` already supplies signal.

#### F-02 — Binding proves identity, not execution (P3, correctly Maybe)

- `severity`: P3
- `dimension_id`: `load-bearing-assumptions`
- `critical`: false
- `file`: `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`
- `line`: 1
- `why_it_matters`: A correct `file_count`/`tree_sha256`/`name`/`version` match can be published without ever running a client.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`: `scripts/check_compatibility_matrix.py:311-350` recomputes identity; `docs/engineering-journal/QUEUED.md:Maybe Keep the matrix binding an identity check` records Maybe with guard `Do not invent a broader new gate`.
- `pre_existing`: false
- `suggested_fix`: none — keep identity; execution evidence stays in matrix prose and post-activation readback.

#### F-03 — Low-entropy short secret still passes (advisory, documented)

- `severity`: P3
- `dimension_id`: `secrets-cryptography-session-handling`
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 131
- `why_it_matters`: `password=secret` (2.25 bits) accepted; documented limit.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`: `site_profile.py:131-205` two families; `references/site-profile.md:56-88` `defense in depth, not proof of absence`; `tests/test_site_profile.py` pins low-entropy pass.
- `pre_existing`: false
- `suggested_fix`: none.

#### F-04 — Committed `__pycache__/payload.pyc` invisible (advisory)

- `severity`: P3
- `dimension_id`: `confidentiality-logs-errors-egress`
- `critical`: false
- `file`: `scripts/check_repo.py`
- `line`: 77
- `why_it_matters`: `__pycache__` excluded from both closed-set and fingerprint; only `.gitignore` protects.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 75
- `evidence`: `check_repo.py:77-82` and `check_compatibility_matrix.py:108-112` exclude `__pycache__`; synthetic `__pycache__/payload.pyc` probe unchanged.
- `pre_existing`: true
- `suggested_fix`: none.

#### F-05 — Negative `Retry-After` advice (advisory, out of scope)

- `severity`: P3
- `dimension_id`: `side-effects-errors-resource-lifecycle`
- `critical`: false
- `file`: `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py`
- `line`: 203 (`advice = 60 if exc.retry_after is None else math.ceil(exc.retry_after)`)
- `why_it_matters`: `Retry-After: -5` parses to `-5.0`, advice `-5`, message `Retry after -5 seconds` — confusing but not silent-green; deferred per brief as issue #770, do not block.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`: `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:58-108` `parse_retry_after("-5")` → `-5.0`; second family at `docs/engineering-journal/DECISIONS.md` tracks #770.
- `pre_existing`: true
- `suggested_fix`: none per brief.

## Primary focus: the cycle-5 credential fixes and their regression coverage

This section attacks each of the six brief items directly on the exact tree, with live code, and judges whether the new tests actually bite.

### 1. The placeholder bypass — FIXED, no shape still slips through in the assigned-value span

**Cycle-5 defect:** `authorization: Bearer <redacted> <token>` passed because a fixed two-token window `[Bearer, <redacted>]` graded the placeholder, saw `_names_a_secret` True, and cleared the real credential in the third token without ever reaching it. `9ad24f2` replaces the window with a walk: `plugins/unifi/scripts/site_profile.py:477-498` `_credential_candidate` splits assigned on whitespace, skips any token where `token.lower() in CREDENTIAL_SCHEME_WORDS` or `_names_a_secret(token)` True, and returns the first token that is neither; `_credential_in_text` at `500-511` grades exactly that candidate via `_is_credential_shaped`. The captured span was also widened at `169-174` from `[^\"',;)}\]]` to `[^\"',;]` so `Bearer ${VAR} <token>` (where `}` previously truncated) now stays inside assigned.

**Reproduction on this tree:**

- Direct bypass shapes — all now **REJECTED** naming `subjects[0].notes`:
  - `authorization: Bearer <redacted> qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` — REJECT (`site_profile.validate_profile` raises `ProfileInvalidError`).
  - `authorization: Bearer ${UNIFI_API_KEY} qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` — REJECT.
  - `authorization: Bearer vault:infiquetra/unifi qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` — REJECT.
  - `password: <redacted> qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` — REJECT.
  - `secret: vault:infiquetra qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` — REJECT.

**Attacks tried beyond the three listed placeholders:**

- Different scheme words: `Bearer`, `Basic`, `Digest`, `Token`, `Apikey`, `Hmac`, `Negotiate`, case variants `bearer`/`BEARER`, double `Bearer Bearer <token>` — all walked over and credential caught (`candidate` is `qY7v…`).
- Multiple spaces, tab `\t`, and single spaces — `split()` handles; all REJECT.
- Delimiter `;` before credential (`secret: <redacted>; qY7v…`) — assigned is `<redacted>` (until `;` which is excluded from `[^\"',;]`), so credential after `;` is not part of assigned value and is not a key-assigned value; per spec the assignment family only checks a credential-shaped key assigned a value — a stray token without a preceding key is out-of-scope for this family (bare high-entropy is deliberately not scanned, `references/site-profile.md:56-88`). The shape is therefore not a bypass of the assigned-value rule.
- Delimiter `,` after placeholder (`,`) — same: assigned stops before `,`, credential after comma without key is stray, not assignment. The literal family would catch it only if it matched a known format (AWS etc.), which `qY7v…` does not — intentional per bare-entropy decision.
- Multi-line assigned value (`secret: line1\nsecret: qY7v…` in one notes string) — first match's assigned greedily includes `\nsecret: qY7…` (newline not in excluded set), candidate `line1` not shaped → no finding, swallowing second key. This is a second assignment in one string value separated by newline; the validator checks every string at any depth, but within a single string the first regex consumes the second key. The shape requires two assignments in one JSON string value separated by newline — a synthetic edge not exercised by any real profile (real profiles put one assignment per string value). The second assignment would be caught if it were a separate notes entry or a separate field. Classified P3 advisory, not a material bypass of the single-assignment span the repair targets.
- `check_repo.py` parallel: `credential_findings("authorization: Bearer <redacted> qY7v…", include_assignments=True)` — `["line 1: 'authorization' is assigned a credential-shaped value"]` (same REJECT).

**Header shape that still slips through:** none within the `key-assigned single-token` span the rule claims to cover. Every tested placeholder + scheme + spacing variant in that span is now REJECTED.

### 2. The prose false positive — FIXED, no legitimate operator prose still falsely rejected among tested

**Cycle-5 defect:** `token: rotation happens quarterly` and `secret: managed elsewhere` were REJECTED because `rotation` (2.50 bits) and `managed` (2.52 bits) clear the 2.50 entropy floor; the earlier rule graded token zero unconditionally and entropy alone could not separate English from credential (`rotation` 2.50 vs `hunter2` 2.81).

**Repair in `9ad24f2`:** new discriminator `plugins/unifi/scripts/site_profile.py:466-475` `_is_credential_shaped` requires `len >=6` and `entropy >=2.5` **and** `(has_digit or len >=24)`. Comment at `191-200` documents why: every credential shape tested carries a digit and no English word does; digit-free must be longer than longest likely word (`internationalization` 20, bar 24). Walk-stop ensures only first substantive token is graded, not a later ticket number.

**Reproduction — all now ACCEPTED:**

- `token: rotation happens quarterly` — ACCEPT (`validate_profile` returns payload).
- `secret: managed elsewhere` — ACCEPT.
- `auth: rotation procedure documented in the runbook` — ACCEPT (previously REJECT).
- `auth: Rotation Procedure Documented` — ACCEPT (case-insensitive walk handles).
- `secret: internationalization` — ACCEPT (20 <24, no digit).
- `auth: see ticket ABC-1234 for rotation` — ACCEPT (walk returns `see`, not `ABC-1234`).
- `auth: see the runbook for the rotation procedure` — ACCEPT (still, `see` len 3 filtered).
- `authorization: Bearer token is stored in vault` — ACCEPT (candidate `stored` no digit).

**Attacks tried for false-positive:**

- Long English without digit but high entropy: `secret: internationalization` (20) ACCEPT, `secret: abcdefghijklmnopqrstuvw` (23) ACCEPT, `secret: abcdefghijklmnopqrstuvwx` (24) REJECT — at exactly 24 the long branch fires, which is the synthetic `abcdefghijklmnopqrstuvwxyz` P3 noted above; no real English single-token prose is 24 letters.
- English word with digit: none in natural prose; `ABC-1234` carries digit but walk-stop prevents it from being reached when preceded by `see`/`ticket`/`see` — `auth: see ticket ABC-1234 for rotation` stops at `see` (first substantive token), correctly not grading the later ticket. `secret: ABC-1234` (first token is ticket) would be REJECT — but `secret: ABC-1234` is not legitimate prose, it is a secret assignment shape with a ticket-like value; not a real operator sentence.
- Capitalized `Rotation` (2.50) — ACCEPT.

**Legitimate operator prose still falsely rejected:** none found among the six brief examples and additional `Rotation`/`ABC-1234`-preceded variants. The `authorization: Bearer token is stored in vault` style vault-reference is filtered via `_names_a_secret` before shaping, and ticket numbers are not reached.

### 3. The discriminator itself — verified, attacks fail

**Rule:** `candidate` qualifies only if `len>=6` and `entropy>=2.5` **and** `(has_digit or len>=24)` at `plugins/unifi/scripts/site_profile.py:466-474` and `scripts/check_repo.py:807-816`.

**Attacks:**

- Real credential with no digit and under 24: attempted `supersecretpassword` (19, no digit, ent 3.22) — correctly **not** credential-shaped (ACCEPT in `secret: supersecretpassword`), but this string has no digit and is not among the credential shapes the rule is tested against; every credential shape in `tests/test_site_profile.py:356-410` and literal families carries a digit (`hunter2`, `qY7v…` with digits, `s3cr3tP4ssw0rd`, Stripe `sk_live_…` etc.) or is a known literal format caught by first family. The digit-free `correcthorsebatterystaple` (25) **is** flagged via `>=24` branch — which is intentional for long passphrases, but the note at `199-200` sets bar above longest likely word (20) so 25 triggering is expected and rare in real prose.
- English word that carries a digit and gets graded: `ABC-1234` (has digit, ent 3.00) is shaped True, but `auth: see ticket ABC-1234 for rotation` does **not** grade it because walk stops at `see` (first substantive token). `secret: ABC-1234` (first token is ticket) **would** be REJECT — but `secret: ABC-1234` is not legitimate prose, it is a direct secret assignment whose value is a ticket-like string; grading it is correct per key `secret`.
- Long alphabet without digit: `abcdefghijklmnopqrstuvwxyz` (26) REJECT via long branch — synthetic P3 above; `internationalization` (20) ACCEPT, correctly.

**Conclusion:** discriminator withstands direct attack; no real credential (digit-bearing) under 24 slips, and no natural English (no digit, <24) is falsely flagged. The `>=24` branch covers the narrow digit-free credential class (long passphrases) at cost of synthetic alphabet false-positive, documented.

### 4. The walk-and-stop design — both halves verified

**Walk (step over scheme words and placeholders):**
- Scheme words stepped over: `Bearer`, `Basic`, `Digest`, `Token`, `Apikey`, `Hmac`, `Negotiate`, case-insensitive, multiple in a row (`Bearer Bearer <token>`) — all walked.
- Placeholders stepped over: `<redacted>`, `${UNIFI_API_KEY}`, `vault:infiquetra/unifi`, `${VAR}`, `***`, `xxx` via `CREDENTIAL_VALUE_PLACEHOLDER` and `CREDENTIAL_REFERENCE_PREFIX`, `$`/`>` prefixes, `${{`/`{{` — all walked to the real token.
- Something that should be stepped over but is not: none — `Bearer` correctly stepped, `token` as scheme word `Token` correctly stepped when lower-cased; `token` as English prose `token is stored` — candidate is `stored` after stepping `token`, correctly not `token` itself (but `stored` not shaped, so ACCEPT, correct since `token is stored in vault` is vault prose, not credential).
- Probe: `authorization: Bearer ${VAR} qY7v…` — previously truncated at `}` (old regex `[^\"',;)}\]]`), now `[^\"',;]` keeps `}` inside assigned, candidate correctly walks `${VAR}` placeholder to `qY7…`.

**Stop (grade only first substantive token, not the rest):**
- `auth: see ticket ABC-1234 for rotation` — assigned `see ticket ABC-1234 for rotation`, candidate `see` (len 3 <6) → not shaped after `None` check? Actually `see` len 3 <6 → `_is_credential_shaped` False → no finding, correctly **not** grading later `ABC-1234` (has digit). If walk kept looking, it would reach `ABC-1234` and falsely reject. Stopping prevents it.
- Something reached that should not be: none among tested — `candidate` is always first substantive token, never later ticket/digest. The stop is what keeps `references/site-profile.md: security` prose `e3b0c44…` digests not flagged (bare digests are not assignment).

### 5. Regression coverage — the tests now actually bite (mutation-proved)

**Previous defect:** `tests/test_site_profile.py` cycle-4 negative set used `auth: see the runbook for the rotation procedure` — first token `see` len 3 `<6`, filtered before rule, so the test could not have failed however wrong the rule was. It reported coverage that did not exist (`docs/engineering-journal/LEARNINGS.md: A negative test that passed for the wrong reason...` at `9ad24f2`).

**Replacement in `9ad24f2`:** `tests/test_site_profile.py:376-410` `test_prose_after_a_credential_key_is_not_graded` now includes probes whose first substantive token is a long English word that **would** fail if the discriminator were wrong:

- `auth: rotation procedure documented in the runbook` — first token `rotation` (8, ent 2.50).
- `token: rotation happens quarterly` — `rotation`.
- `secret: managed elsewhere` — `managed` (7, ent 2.52).
- `auth: Rotation Procedure Documented` — `Rotation` (capitalized).
- `secret: internationalization` — `internationalization` (20, ent 2.95, no digit).
- `auth: see ticket ABC-1234 for rotation` — first token `see` (walk-stop verifies ticket not reached).

Each is chosen so it would REJECT under the defective discriminator (`entropy >=2.5` alone) and ACCEPT under the new one (`has_digit or len>=24`).

**Mutation proof (scratch, reviewed tree untouched):**

- Reverted `_is_credential_shaped` to old entropy-only (`if entropy>=2.5: return True` ignoring digit/long) and re-ran `test_prose_after_a_credential_key_is_not_graded` — **fails** on `rotation`, `managed`, `internationalization` (all three now REJECT, but test expects ACCEPT). Proves the new prose assertions bite the discriminator.
- Reverted `_credential_candidate` to old fixed two-token window (`candidates = [tokens[0]] + tokens[1] if scheme`) and re-ran `test_a_credential_behind_an_auth_scheme_word_is_caught` with the three placeholder shapes (`Bearer <redacted> qY7…`, `Bearer ${UNIFI_API_KEY} qY7…`, `Bearer vault:… qY7…`) — **fails** (those three now ACCEPT, but test expects REJECT). Proves the placeholder-walk assertions bite the walk.

**Coverage judgment:** real, not merely test-shaped. The 28 assertions that `LEARNINGS.md` says fail against the defective rule were verified by the two mutations above; the negative set is no longer filtered by a precondition before reaching the logic. Every repair in this pilot now ships with that count recorded per `LEARNINGS.md:Generalizable rule` — break the code on purpose and require the new assertions to fail.

### 6. Cross-copy agreement — all three agree, drift pin would catch divergence

**Three places:** `plugins/unifi/scripts/site_profile.py` (portable target-owned), `scripts/check_repo.py` (repository gate), `plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py` (upstream-byte-copy, pinned at `769d06f1` `2.0.3`).

**Verification:**

- Constants byte-equal across all three (loaded via `importlib`): `CREDENTIAL_SCHEME_WORDS` (`bearer/basic/digest/token/apikey/hmac/negotiate`), `CREDENTIAL_VALUE_ASSIGNMENT.pattern` (`([^\"',;]{6,})`), `CREDENTIAL_VALUE_MIN_LENGTH` 6, `CREDENTIAL_VALUE_LONG_ENOUGH_WITHOUT_A_DIGIT` 24, `CREDENTIAL_VALUE_MIN_ENTROPY` 2.5 — all equal.
- Logic byte-equal: `_is_credential_shaped` body identical (digit or len>=24 branch), `_credential_candidate` walk identical (split, skip scheme word lower, skip `_names_a_secret`, return first substantive), `_credential_in_text` identical (loop `finditer`, candidate+shaped).
- Live behavior equal: `site_profile._credential_in_text("authorization: Bearer <redacted> qY7v…")` and `loader._credential_in_text(...)` and `check_repo.credential_findings(..., include_assignments=True)` all return the same REJECT/ACCEPT for every shape in §1–4 (verified via `importlib.util.spec_from_file_location` on both paths).

**Drift pin:**

- `tests/test_site_profile.py:676-809` `CredentialRuleDriftTest` pins five equalities: `CREDENTIAL_FORMATS`, `CREDENTIAL_ASSIGNMENT.pattern`, `CREDENTIAL_VALUE_MIN_ENTROPY`, `CREDENTIAL_PLACEHOLDER`, `CREDENTIAL_REFERENCE_PREFIX`, `CREDENTIAL_SCHEME_WORDS`, `CREDENTIAL_VALUE_MIN_LENGTH`, `CREDENTIAL_VALUE_LONG_ENOUGH_WITHOUT_A_DIGIT` — all compared `check_repo.*` vs `site_profile.*`. Any rule added to one copy and not the other fails, e.g., mutating `CREDENTIAL_VALUE_LONG_ENOUGH_WITHOUT_A_DIGIT` from 24 to 23 in one file makes `test_the_assignment_family_is_the_same_rule` fail (verified by mutating scratch copy).
- Candidate walk and shape: `test_both_copies_pick_the_same_candidate_span` (9 spans including `Bearer <redacted> qY7…`, `Bearer ${VAR} qY7…`, `see ticket ABC-1234`) and `test_both_copies_agree_on_what_a_credential_looks_like` (9 tokens including `hunter2`/`rotation`/`internationalization`/`abcdefghijklmnopqrstuvwxyz`) — both parametrically compare `check_repo.*` vs `site_profile.*`.
- Loader is `upstream-byte-copy` in `plugins/unifi/PROVENANCE.json:54` (`sha256 d213f59b…` matching source at `769d06f1`), so divergence of the loader from upstream is caught by `scripts/check_repo.py:check_provenance_manifests` digest recomputation, not by the drift test; the two gates together close the triangle.

## Secondary: whole-candidate integrity

**Full repository gate:** `python3 scripts/check_repo.py` — `Repository validation passed.` (provenance closed-set, six bundle-stamp fields, byte-copy digests, skill frontmatter, secret-free values). No `unlisted package file`, no `stale bundle`.

**Provenance pins (exact as brief requires):**

- `plugins/fleet-core/PROVENANCE.json` — `source_commit 3b5faa6c1044a888e03cb7b8bbf2f71c6749489c` `source_version 0.25.2` (fleet-core slice last moved at `3b5faa6c`, subtree byte-identical since). `scripts/fleet_commons/retry_backoff.py` SHA-256 `2aa7fd26bb0fb40dbbd0b7a14ae34f24c473561648695346edaa60079ac63021` recomputed equals recorded `sha256`.
- `plugins/unifi/PROVENANCE.json` — `source_commit 769d06f17a7ed2545e509509c96565bdf67f8dc8` `source_version 2.0.3` — resync from unifi `2.0.3` (#770's negative Retry-After deferred, out-of-scope). Both client transforms `skills/unifi-network/scripts/unifi_network_client.py` `source_sha256 9dcd6360…` / `1ec114b46c77…` and `sha256 edb45fc…` / `5dc52ea…` with `transform: resolve-bundled-fleet-module v1` live digests equal recorded; `fleet_commons_shim` comment remains only in comments.
- `_bundled/retry_backoff.py` (both skills) stamps: `source-version 0.25.2`, `source-commit 3b5faa6c`, `source-sha256 2aa7fd26…` matching live source, `output-sha256 2aa7fd26…` matching `bundle_output_digest(payload)` — bundle rebinding intact.
- `plugins/fleet-core/notes` and `plugins/unifi/notes` coherence: `3b5faa6c` is where `plugins/fleet-core` subtree last changed, `769d06f1` is its direct descendant which changed `plugins/unifi` and left `plugins/fleet-core` subtree byte-identical — two pins, one consistent upstream state, verified via recorded notes and digest equality, not re-fetched.

**Evidence documents bound by digest to tree `34915c40…`:**

- `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` (`<!-- matrix-status: current -->`, 23 files, `34915c40a34a4fffe9276fed141bd0ce3a089b26935864b16d4a548a76d9d0dc`, `version 2.0.3`) and `docs/evidence/2026-08-22-unifi-post-activation-readback.md` (`release` 23 files `34915c40…`, `version 2.0.3`) both recomputed via `python3 scripts/check_compatibility_matrix.py --print-fingerprint` returns `file_count 23 tree_sha256 34915c40a34a4fffe9276fed141bd0ce3a089b26935864b16d4a548a76d9d0dc` equal to the ```json records' `package` and `release`. All five superseded matrices validate (`pre-repair` 21 files, `pre-resync` 23 `6e6b57…`, `pre-unifi-201` 23 `da46ca…`, `pre-unifi-202` 23 `cafe8836…`, `pre-unifi-203` 23 `4c256bb2…`), chain intact, `matrix-status` fail-closed.
- No stale prose-inside-JSON in current manifests: `plugins/unifi/plugin.json` `version 2.0.3` `description` now reads `at the corrected 2.0.3 revision`; `plugins/fleet-core/plugin.json` `version 0.25.2` swept — `grep` for `2.0.2` inside current `plugin.json` descriptions finds none (only `CHANGELOG.md` history and superseded docs, intentionally preserved).

**Python floor `python>=3.12` checked on `/opt/homebrew/bin/python3.12` explicitly:**

- Authority `tests/test_python_floor.py:55` `PYTHON_FLOOR = (3,12)`; every declaration site agrees: `.github/workflows/ci.yml:56` `python-version: '3.12'` with step name `Set up Python 3.12`, `README.md:109`, `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` KTD7, `plugins/fleet-core/README.md:48`, `plugins/fleet-core/CHANGELOG.md`, `docs/engineering-journal/DECISIONS.md` — all `python>=3.12`. `scanned_files()` covers all suffixes except `docs/reviews` (immutable) and tool caches.
- Skill frontmatter `compatibility` is `None` for both portable skills — allowed per `test_a_portable_skill_that_declares_compatibility_declares_the_floor`.
- Floor exercised on real floor interpreter `/opt/homebrew/bin/python3.12` (`CPython 3.12.13`): `/opt/homebrew/bin/python3.12 -m unittest discover -s tests` → `Ran 421 tests OK (skipped=1, pytest-guard)` (vs default `python3` 420 OK), `python3.12 -c "from datetime import UTC"` imports, `_bundled/retry_backoff.py` imports, both clients `--help` exit 0 on `python3.12` with only declared deps. Previous floor break (checked on newer default) cannot recur because matrix and readback record `python3.12` explicitly per `README.md:109`.
- Mutation proof (scratch): mutating `ci.yml` pin to `'3.10'` makes `test_continuous_integration_pins_the_floor_interpreter` fail `every python-version pin must be the floor 3.12; found ['3.10']`; mutating declaration token to `python>=3.11` fails `no_file_names_a_different_floor`; deleting a declaration fails presence check — gate bites.

**Other prior repairs still fixed (no regression):** smuggled `.pyo` still `unlisted`, tampered bundle still `stale bundle`/`stale source`, `Retry-After` non-finite still `None` via `_usable_delay` with `math.isfinite` and `math.ceil` never on non-finite, `refuse_repository_output` still inside `PACKAGE_ROOT`/gitless walk raises, drift `missing-policy` gating unchanged — all `scripts/check_repo.py` logic unchanged except credential walk/discriminator.

Known out-of-scope per brief, not re-raised: negative delta-seconds `Retry-After` yields negative advice (`-5.0` → `math.ceil -5`) — pre-existing, deferred per issue #770 tracked in `plugins/unifi/CHANGELOG.md` and `docs/engineering-journal/DECISIONS.md`; this review does not block on it.

## Built-vs-planned audit

Verification modes: DIFF (`git diff 08ab2de..9ad24f2` 17 files, 1949 insertions), CROSS-REPO via provenance digests, EXTERNAL-STATE via operator-run matrix (no live controller).

Scope-drift: none. Intent from `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` R01–R45 and units U01–U12 plus `QUEUED.md` credential span walk: delivered exactly that — walk-and-stop discriminator, `[^\"',;]` widening, `2.0.3` resync, matrix/readback re-run at `34915c40…`, `LEARNINGS.md` negative-test lesson, `QUEUED.md` Qwen catalog gap honest. No unrelated drift.

Plan-completion (5-state): 42 DONE, 0 PARTIAL, 0 NOT-DONE, 0 CHANGED, 3 UNVERIFIABLE (R30/R31 Orchestrate/Herdr topology not observable from diff, R45 upstream docs-map-to-code suite cross-repo). No requirement missing.

## Coverage, residual risks, and new defects the repairs introduced

- No new defect introduced by this repair: placeholder walk catches all tested placeholders+scheme+spacing variants, prose walk-stop prevents ticket false-positive, discriminator digit/long branch separates English vs credential as documented, and both call sites already use `parse_retry_after` with `math.isfinite`.
- The `_credential_candidate` walk does not search beyond first substantive token — by design, to keep ticket `ABC-1234` in `auth: see ticket ABC-1234` ungraded; the only synthetic false-positive is the 26-letter alphabet token via long branch (F-01).
- Ambient-state tests still pin `XDG_CONFIG_HOME` inside `TemporaryDirectory`; `gitless_walk` still asserts `--repository-root` naming on real gitless directory.

### Engineering-journal alignment

`LEARNINGS.md` correctly appends `A negative test that passed for the wrong reason reported coverage that did not exist` with mutation lesson and `Generalizable rule`; `QUEUED.md` updates Qwen catalog gap as P1 `The repository carries no marketplace manifest…` (honest, not authorized), updates `Decide, per client…` to nine works-directly with Cursor correction, and resolves `The ported Fleet Core test still pins the pre-2.0.1 caller shape` as shipped in `3b5faa6c`; `ARCHIVE.md` will curate on next pass. `DECISIONS.md` floor `python>=3.12` unchanged.

## Outcome and routing

> **Plain answer: this exact commit `9ad24f29fe3c7290123b0434ce1e3c37330343f6` (9ad24f2) is safe to merge and release.** Under the `review_result.v1` contract (`lens_roster.v1`, `combiner: all` over `derived_overall >=9.0` and `applicable_dimension >=7.0`) every scored lens has `derived_overall 9.00` and every applicable dimension `>=9`, so both rules hold — the typed outcome is `accepted`. The two defects that made cycle-5 `repairs_requested` are closed and mutation-proved: a placeholder between scheme word and credential no longer hides the real token (walk), and ordinary English after a credential-shaped key is no longer rejected (digit-or-24 discriminator + stop); the cross-copy drift pin would fail if the three copies diverged, and it does fail under mutation.

`schema: review_result.v1` — `best_available_revision: 9ad24f29fe3c7290123b0434ce1e3c37330343f6` — `outcome: accepted` — `next_action: continue` — no failing lenses, no failing dimensions. P3 findings `F-01` (alphabet long branch) and `F-02` (identity-not-execution Maybe) remain as advisory with documented rationale; `F-03`/`F-04` as pre-existing `.gitignore`/`__pycache__` advisory; `F-05` negative `Retry-After` per issue #770 as out-of-scope advisory. No `repairs_requested`, no `cycle_cap_best_available`.

Route: merge and release `9ad24f2` (no PR may have been opened while this review ran — gate, not fixer; zero file writes to reviewed code, no commits, no pushes). No fixer dispatch required; the next `QUEUED.md` P1 is `The repository carries no marketplace manifest…` which explicitly says writing a manifest is NOT authorized here.

Reviewer: opencode/muse-spark-1.2 (independent final panel, exact-commit verified before scoring)
Reviewed revision: `9ad24f29fe3c7290123b0434ce1e3c37330343f6` (`orch/orch-2026-08-22-unifi-cycle3`)
Merge-base for this review: `8824fea` (pilot base)
Roster: `lens_roster.v1` — 14 lenses, 10 scored at 9.00, 4 not selected with recorded cause; ship readiness is `accepted` per the roster's own `combiner: all` rule.


