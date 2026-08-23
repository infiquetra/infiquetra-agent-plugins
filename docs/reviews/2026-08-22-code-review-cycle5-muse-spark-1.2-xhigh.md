# Cycle-5 scored code review — UniFi portability pilot

Independent reviewer: opencode / muse-spark-1.2 — unattended, different model/session, no controller priming. One of two independent reviewers per brief; no cross-reviewer communication.

Repository: `/Users/jefcox/workspace/infiquetra/infiquetra-agent-plugins` on branch `orch/orch-2026-08-22-unifi-cycle3`, HEAD `08ab2de` (`feat: resync to UniFi 2.0.2 and Fleet Core 0.25.2`), merge-base `8824fea`. Cycle-4 baseline `2bd0faf`. Three commits since: `367d9b6` credential-value span fix, `0bcdffe` cycle-4 panel artifacts, `08ab2de` resync + ten-client matrix re-run. Upstream releases `infiquetra-claude-plugins` fleet-core `0.25.2` (`3b5faa6c`) and unifi `2.0.2` (`c835f91d`) arrived by re-synchronization. Working tree clean, no untracked files. Read-only; zero file writes to reviewed code, no network UniFi controller call.

Scope: `git diff 2bd0faf..08ab2de --stat` 18 files + panel artifacts (strategy not counted). This review re-derives every claim from current source on disk, runs gates, and attempts to defeat each of the eight brief items end-to-end on this tree.

Gates executed this session (all green on this tree):

- `python3 scripts/check_repo.py` — Repository validation passed.
- `python3 scripts/bundle_fleet_module.py --check` — Fleet Core bundle check passed.
- `python3 scripts/check_compatibility_matrix.py` — Compatibility matrix validation passed (current plus four superseded, chain intact).
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint` — `name: unifi version: 2.0.2 file_count: 23 tree_sha256: 4c256bb20bd054c498056282eb7cbb3cee9c224c422bf1f20bb66422d1d15cfa` equal to the ` ```json ` record's `package` field in `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:328-330` and to the post-activation readback record.
- `python3 -m unittest discover -s tests` on default (`3.14.6`) — `Ran 419 tests OK`.
- `/opt/homebrew/bin/python3.12` (`3.12.13`, the declared floor) — `Ran 420 tests OK (skipped=1, pytest-guard)` and `tests/test_python_floor.py` 13 tests OK; `from datetime import UTC` imports; `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` loads and `parse_retry_after('inf') is None`.

Prior cycles `docs/reviews/` read as immutable evidence (consensus + two independent reports per cycle through cycle-4). The recurring pattern named across every cycle is **a guarantee that exists but does not bite** — this review hunts specifically for that shape.

## Lens selection (roster `lens_roster.v1` at `~/.claude/plugins/marketplaces/infiquetra-plugins/plugins/saga/references/lens-roster.json`)

Four always-on lenses run on every review. Six conditional lenses are selected because this diff materially touches their domains; four are explicitly not selected.

| Lens | Class | Selection reason |
|---|---|---|
| `architecture-maintainability` | always-on | — |
| `correctness` | always-on | — |
| `security` | always-on | — |
| `testing` | always-on | — |
| `reliability` | conditional | diff changes `Retry-After` handling at primitive and both call sites, changes `retry_with_backoff` `now` seam, and touches drift policy-observation vs availability |
| `deployment-infrastructure` | conditional | release/bundle re-binding, resync rollout, Python floor interpreter pin change, deployed-state evidence re-captured |
| `api-contract` | conditional | diff changes `site-profile.schema` already 1.1 but repairs Claude-path loader skew to 1.1, adds non-finite guard to `parse_retry_after` contract, moves package version 2.0.1→2.0.2 |
| `adversarial` | conditional | 27-file, ~2500-line change whose prior-cycle pattern is "a gate that passes when it should fail" across Retry-After, credential span, floor, provenance, and evidence binding |
| `documentation-clarity` | conditional | README, reference doc, changelog, journal, and two evidence documents materially rewritten |
| `agent-usability` | conditional | drift/discover JSON, profile schema, and evidence machine-readable records are agent-consumed surfaces |
| `performance` | conditional | **not selected** — no latency, throughput, query, memory, cache, or capacity claim touched; retry jitter bounds are reliability |
| `privacy` | conditional | **not selected** — no new personal-data flow, site profile is operator intent (site/network/host), no telemetry/training surface |
| `previous-comments` | conditional | **not selected** — no PR review threads exist |
| `accessibility-human-usability` | conditional | **not selected** — no human-operated visual/keyboard surface changed |

## Lens scores (anchor bands from `lens-roster.json`; scale 0–10)

Scores are per-dimension against that dimension's 10/9/7-8/5-6/0-4 anchors; `derived overall` is the mean of applicable dimensions for this report. Acceptance is `combiner: all` over `derived_overall >= 9.0` and `applicable_dimension >= 7.0`. **Both rules must hold.** No Priority or confidence changes the outcome.

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall | Failing dimensions |
|---|---|---|---:|---|
| `architecture-maintainability` | fit/ownership 9; separation 9; dependency 9; simplicity 8; readability 9; conventions 9; decisions 9 | — | 8.86 | none <7; overall <9 |
| `correctness` | intent 8; state/invariants 9; boundaries 9; side-effects 9; consumers 8 | — | 8.60 | none <7; overall <9 |
| `security` | auth 9; input 8; secrets 7; supply-chain 9; confidentiality 9 | — | 8.40 | none <7; overall <9 |
| `testing` | requirements 8; negative/edge 8; behavior-sensitive 9; seams 9; determinism 9 | — | 8.60 | none <7; overall <9 |
| `reliability` | timeouts/retries 9; concurrency 9; graceful/cancel 8; health 8 | `queues-jobs-dead-letters-ordering-backpressure` — no queue, job, ordering, or backpressure surface | 8.50 | none <7; overall <9 |
| `deployment-infrastructure` | infra/config 9; rollout 9; rollback/drift 9; deployed-verification 9 | `cost-resilience` — no resource or cost surface in this delta | 9.00 | — |
| `api-contract` | contract/compat 8; versioning 9; serialization 9; retry/idempotency 9; spec/doc parity 8 | `pagination-rate-limits`, `sdk-generated-client-impact` — no collection pagination or generated SDK | 8.60 | none <7; overall <9 |
| `adversarial` | load-bearing 8; abuse/edge 7; silent-green 8; environment 9; scope-creep 9; alternatives 9; recovery 8 | — | 8.29 | none <7; overall <9 |
| `documentation-clarity` | parity 9; completeness 9; structure 9; terminology 9; examples 9; runbook/drift 9 | — | 9.00 | — |
| `agent-usability` | reachability 9; discoverability 9; context 9; machine-output 8; bounded-op 9 | — | 8.80 | none <7; overall <9 |
| `performance` | — | **not selected** — no latency/throughput/query/cost surface | — | — |
| `privacy` | — | **not selected** — no personal-data flow | — | — |
| `previous-comments` | — | **not selected** — no PR threads | — | — |
| `accessibility-human-usability` | — | **not selected** — no visual/keyboard surface | — | — |

Acceptance check: `derived_overall >= 9.0` fails for 7 of 10 scored lenses (architecture 8.86, correctness 8.60, security 8.40, testing 8.60, reliability 8.50, api-contract 8.60, adversarial 8.29, agent-usability 8.80). `applicable_dimension >= 7.0` passes for every applicable dimension (lowest is security `secrets-cryptography-session-handling` at 7). Under `combiner: all` the typed outcome is **not accepted**; the gap is not excellence but the two residual credential-rule defects and the consistency trade-offs that keep the derived mean below 9.

## Findings (admitted, confidence >=75 except P0 at 50+; sorted P0→P3 then confidence→file→line)

### P1 — none admitted

No P1 survives validation at anchor 75+. The four severities that distinguished cycle-1 (closed-set smuggling, stamp-field optionality, path-escape unlink, persistence fail-open) remain biting, and the two cycle-3 blocking defects (caller `int(Retry-After)` and `datetime.UTC` floor break) remain fixed and proved on the floor interpreter.

### P2

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `plugins/unifi/scripts/site_profile.py:456` | Credential-value rule accepts a real token hidden behind a placeholder second token (`Bearer <redacted> <token>` never examines the third token) — bypass of the value half in both copies plus the loader | `security` | 100 | `gated_auto -> review-fixer` |
| F-02 | `plugins/unifi/scripts/site_profile.py:474` | Credential-value rule falsely rejects ordinary English prose when the first token after the key is a high-entropy English word (`auth: rotation procedure ...` flagged as credential) | `security` | 100 | `gated_auto -> review-fixer` |

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-03 | `scripts/check_compatibility_matrix.py:108` | Residual `__pycache__` shared blind spot (both gates exclude the directory; only `.gitignore` stands between a committed cache file and shipping) | `security` | 75 | `advisory -> human` |
| F-04 | `plugins/unifi/scripts/site_profile.py:1` | Low-entropy short secret in free-text value still passes (`password=secret`, 2.25 bits) — documented defense-in-depth, not proof of absence | `security` | 100 | `advisory -> human` |

### Advisory (no autofix)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-05 | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` | Binding proves identity, not that forty stages ran — correctly queued as Maybe, not a gate | `adversarial` | 100 | `advisory -> human` |

Suppressed (below admission): none. All reported at anchor 75+.

### Detailed findings (per `findings-schema.md` — every field)

#### F-01 — Assignment family grades only two tokens, so `Bearer <placeholder> <real-token>` bypasses value detection (P2)

- `severity`: P2
- `dimension_id`: `secrets-cryptography-session-handling` (also `input-trust-boundaries-injection`)
- `critical`: true — unresolved, dimension cannot honestly be 9
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 456 (`_credential_candidates`)
- `why_it_matters`: An operator who pastes `authorization: Bearer <redacted> qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` (for example by keeping a template that already contains `<redacted>` and appending the real token, or by an automated tool that inserts a placeholder before the secret) is told the profile is valid. The detector inspects the wrong span: it grades `Bearer` (entropy 2.25 <2.5, skipped) and `<redacted>` (placeholder via `CREDENTIAL_VALUE_PLACEHOLDER`, skipped) and never examines the third token where the real credential lives. The same bypass exists in `scripts/check_repo.py:798` and in the Claude-path loader `plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py:415`, so all three copies are identically affected and the cross-copy pin `tests/test_site_profile.py:647-720` locks them together.
- `autofix_class`: `gated_auto`
- `owner`: `review-fixer`
- `requires_verification`: true
- `confidence`: 100
- `evidence`:
  - `plugins/unifi/scripts/site_profile.py:169-173` — `CREDENTIAL_VALUE_ASSIGNMENT` captures `([^\"',;)}\]]{6,})` running across whitespace, intentionally, and `_credential_candidates` at `456-471` returns `[tokens[0]]` plus `tokens[1]` when `tokens[0]` is a scheme word, filtered by `CREDENTIAL_VALUE_MIN_LENGTH`.
  - `plugins/unifi/scripts/site_profile.py:474-486` — loop grades each candidate, skipping `_names_a_secret` and entropy <2.5, then returns; no iteration past `candidates[1]`.
  - Live on this tree: `python3 -c` with `site_profile.validate_profile` — `authorization: Bearer qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` REJECTED naming `subjects[0].notes`; `authorization: Bearer <redacted> qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` ACCEPTED (no exception); `authorization: Bearer vault:infiquetra/unifi#api_key qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` ACCEPTED; `authorization: Bearer secret qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` ACCEPTED because `secret` entropy 2.25 skipped.
  - `scripts/check_repo.py:184-203` + `798-839` identical pattern and helper, same bypass; `site_profile_loader.py:149-175` identical.
  - `tests/test_site_profile.py:356-410` covers `Bearer <token>`, `Basic`, `Token`, but no three-token case and no placeholder-second-token case.
- `pre_existing`: false — introduced by the `367d9b6` span fix which widened the capture across whitespace and added the two-candidate helper; prior code graded only `Bearer` and also bypassed, but via a different mechanism — this is the residual of that repair.
- `suggested_fix`: Grade every whitespace-separated token of the assigned remainder after the optional scheme word, not only the first two, stopping only at a token that names a secret via `_names_a_secret`? No — a placeholder token must NOT cause the scan to stop; it must be skipped and the scan continued, because a placeholder can plausibly appear before a real secret in a template. Implement `for token in tokens[1:]` when `tokens[0]` is scheme word else `tokens`, filter by length, skip placeholders/references, grade entropy, return on first hit. This widens toward the credential, not toward the sentence, preserving the rejected alternative's rationale (prose after the credential is not graded — but the credential itself, wherever it sits behind the scheme word, is). Apply to all three copies in one change and add `test_placeholder_before_credential_does_not_hide_it` asserting rejection. Assumption: a real credential is high-entropy and ≥6 chars; prose tokens beyond the credential are ordinary English and would not have been high-entropy anyway, so false-positive risk from scanning further behind the scheme word is low and bounded to that narrow span.

#### F-02 — First prose token after a credential-shaped key is graded, so ordinary English flagged as credential (P2)

- `severity`: P2
- `dimension_id`: `secrets-cryptography-session-handling` (also `input-trust-boundaries-injection`)
- `critical`: true
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 474 (`_credential_in_text` assignment loop)
- `why_it_matters`: An operator describing intent in free text — `notes: "auth: rotation procedure documented in vault"` or `notes: "authorization: documented procedure for runbook"` — is told the profile contains a credential and is forced to rephrase operational prose. The value half was intended as defense in depth against an accident, not as a prose linter; a false positive trains the operator to weaken or bypass the check.
- `autofix_class`: `gated_auto`
- `owner`: `review-fixer`
- `requires_verification`: true
- `confidence`: 100
- `evidence`:
  - `plugins/unifi/scripts/site_profile.py:169` key set includes `auth`/`authorization` among 11 fragments, so `auth: rotation procedure ...` triggers the assignment family.
  - `plugins/unifi/scripts/site_profile.py:456-471` candidates = `[tokens[0]]` where `tokens[0]` is `rotation` (length 8 ≥6, entropy 2.50≥2.5, not placeholder, not digit-only) so it is graded and fires.
  - Live: `python3 -c` — `auth: rotation procedure for runbook` → REJECTED `'auth' is assigned a credential-shaped value`; `auth: procedure for rotating credentials` → REJECTED; `authorization: documented procedure` → REJECTED (documented entropy 2.92); `auth: authentication end to end` → REJECTED (`authentication` entropy 3.03). By contrast `auth: see the runbook for the rotation procedure` → ACCEPTED because `see` length 3 filtered — the outcome depends on the first word's length/entropy, not on whether a credential is present. `shannon_entropy('runbook')` 2.52, `rotation` 2.50, `procedure` 2.72, `documented` 2.92 all clear the 2.5 floor.
  - `scripts/check_repo.py:798` same, so `credential_findings("auth: rotation procedure", include_assignments=True)` reports `line 1: 'auth' is assigned a credential-shaped value`.
  - `tests/test_site_profile.py:376-410` must-not-fire set includes `auth: see the runbook for the rotation procedure` and `vault:` references, but no case where first prose token itself is high-entropy English; the gap is not pinned.
- `pre_existing`: false — same repair as F-01; prior pattern stopped at whitespace so `auth: rotation` would have matched `rotation` already, but the probe was not in the suite.
- `suggested_fix`: Do not grade a bare English token as credential without a second signal. Options, in increasing invasiveness: (a) require the candidate contain a non-alpha character (digit, mixed case, symbol) before it counts — real tokens are opaque and contain such, English words almost never; (b) require length ≥12 for the prose path, keeping 6 only when the literal-format families already fired — the assignment family's key already supplied signal, but prose that clears 2.5 at length 6 is common; (c) keep entropy but add a dictionary check. The minimal defensible default is (a): `if candidate.isalpha(): continue` before entropy, or more precisely `if candidate.isalpha() and candidate.islower(): continue` so mixed-case opaque strings still fire. Apply to all three copies and add `test_prose_after_credential_key_is_not_flagged` covering `rotation`, `procedure`, `documented`. Assumption: legitimate high-entropy prose that is purely alphabetic lowercase is English; an opaque credential contains digits or mixed case or symbols. This preserves the value half's protection for real tokens while removing the linter effect on sentences — the precise trade-off F-01's suggested widening must preserve.

#### F-03 — Committed `__pycache__/payload.pyc` invisible to both gates (P3, pre-existing)

- `severity`: P3
- `dimension_id`: `confidentiality-logs-errors-egress` (also `architectural-fit-ownership-single-sources`)
- `critical`: false
- `file`: `scripts/check_repo.py`
- `line`: 77 (`PROVENANCE_UNMANAGED_DIRECTORY_NAMES = ("__pycache__",)`)
- `why_it_matters`: A file committed as `plugins/unifi/__pycache__/payload.pyc` with arbitrary bytes is exempt from provenance closed-set by `check_repo.py:82+404` and from fingerprint by `check_compatibility_matrix.py:108-112` — only `.gitignore` stands between it and shipping. The exclusion predates this pilot and was intentionally preserved when the `.pyc`/`.pyo` suffix hole was closed to placement-based `__pycache__` or beside-matching-`.py` in `ff7603d`.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 75
- `evidence`:
  - `scripts/check_repo.py:77-82` and `311-315` — `_fingerprint_includes` and `_managed_package_files:397-412` both exclude `__pycache__` at any depth.
  - `scripts/check_compatibility_matrix.py:108-112` same directory exclusion.
  - Probe on scratch copy: synthetic `plugins/unifi/__pycache__/payload.pyc` with arbitrary bytes — `check_provenance_manifests` returns `[]`, `package_fingerprint` unchanged.
  - Placement-based exemption for `.pyc` outside `__pycache__` is now correctly closed: `smuggled.pyo` with no sibling `.py` now fails `unlisted package file` as proved in cycle-4.
- `pre_existing`: true
- `suggested_fix`: none for this cycle — keep `.gitignore` entry tight and document the exclusion; if threat model grows, reject a committed `__pycache__` regular file (not an ignored cache directory) via a check that a tracked file under `__pycache__` fails closed, without hashing ignored cache directories.

#### F-04 — Low-entropy short secret in value still passes (P3, documented)

- `severity`: P3
- `dimension_id`: `secrets-cryptography-session-handling`
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 131 (`CREDENTIAL_VALUE_FORMATS` + `CREDENTIAL_VALUE_ASSIGNMENT` with `MIN_ENTROPY 2.5`)
- `why_it_matters`: An operator told credentials never live in the profile can write `password=secret` (2.25 bits/char, below floor) and be told valid; profile then reaches whatever store holds the deployment.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`:
  - `plugins/unifi/scripts/site_profile.py:131-195` two families: literal formats anywhere and assignment+entropy at any depth, `shannon_entropy("secret")` 2.25 and `password=secret` accepted.
  - `plugins/unifi/references/site-profile.md:56-88` documents as `defense in depth against an accident, not a proof of absence` and names `password=secret` as accepted example; `tests/test_site_profile.py:336-346` pins `test_a_low_entropy_assigned_value_passes_and_the_limit_is_admitted`.
  - `scripts/check_repo.py:193-209` identical threshold and same admitted example.
- `pre_existing`: false
- `suggested_fix`: none — deliberate false-positive/true-negative trade-off; do not lower floor (rejects digests and ordinary prose) and do not add bare entropy scan (fires on every digest). Keep wording honest. This limit is why F-01/F-02 matter: they are about the wrong span, not about this floor.

#### F-05 — Binding proves identity, not execution (advisory, correctly queued as Maybe)

- `severity`: P3
- `dimension_id`: `load-bearing-assumptions`
- `critical`: false
- `file`: `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`
- `line`: 1 (`package` fingerprint record)
- `why_it_matters`: A correct `file_count`/`tree_sha256`/`name`/`version` match can be published without ever running a client; operator reading matrix as execution proof would be misled.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`:
  - `scripts/check_compatibility_matrix.py:268-430` `package_fingerprint` + `package_identity` recompute identity; `docs/engineering-journal/LEARNINGS.md` `A bound digest names the tree, not the forty stages that assessed it`.
  - `docs/engineering-journal/QUEUED.md:Maybe Keep the matrix binding an identity check` — recording-only, guard `Do not invent a broader new gate. Do not weaken check_package_binding.`
- `pre_existing`: false
- `suggested_fix`: none — keep `check_package_binding` as identity; execution evidence stays in plan's own places (`matrix.md` prose `The point of the exercise…` and `docs/evidence/2026-08-22-unifi-post-activation-readback.md`). Correctly not an autofix.

## What was attempted to be defeated — reproduce or refute each

This section independently reproduces or refutes each of the eight items in the brief, end-to-end on this tree. Numbers are from executed code, not from messages.

### 1. Non-finite `Retry-After` — FIXED, no header shape still gets through

**Claim:** `parse_retry_after` should refuse `inf`, `-inf`, `nan`, and overlarge `1e400` because `float()` accepts them and a non-finite "delay" destroyed the caller's typed 429 surface at `math.ceil`.

**Reproduction on this tree (`08ab2de`):** `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:30-56` introduces `_usable_delay(seconds)` returning `None` when `not math.isfinite(seconds)` with docstring citing the `math.ceil` failure. `parse_retry_after` at `58-108` uses it in three places: `if isinstance(value,(int,float)): return _usable_delay(float(value))`, `try: return _usable_delay(float(text))` for delta-seconds, and the docstring states non-finite yields `None`. Both call sites `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:189` + `unifi_protect_client.py:189` do `hint = _retry_backoff.parse_retry_after(resp.headers.get("Retry-After"))` then `raise _RateLimited(hint)` where `_RateLimited.retry_after: float | None` at `57-70`, and the retry loop at `195-199` passes `retry_after=lambda exc: getattr(exc,"retry_after",None)` which is reduced again before `_retry_delay`. After exhaustion, `advice = 60 if exc.retry_after is None else math.ceil(exc.retry_after)` at `203` never sees a non-finite value because the hint is already `None` and advice is `60`.

**Probes (both interpreters, real import):**
- `retry_backoff.parse_retry_after('inf') is None`, `' -inf'` None, `'nan'` None, `'Infinity'` None, `'+inf'` None, `'1e400'` None, `'1e309'` None, `'  inf  '` None — all trimmed and refused.
- Numeric `float('inf')`, `float('-inf')`, `float('nan')`, `1e400` (which is already `inf`) — all `None`.
- `math.ceil(float('inf'))` raises `OverflowError`, `math.ceil(float('nan'))` raises `ValueError` — the exact failure the primitive now prevents; with the guard, `parse_retry_after` returns `None` and `math.ceil` is never called on a non-finite.
- Huge but finite `1e308` parses to `1e308` and `math.ceil(1e308)` returns a big int (Python int arbitrary precision) without `OverflowError` — typed surface preserved, albeit with a large `Retry after 1e308 seconds` message, which is a finite-input polish issue, not the non-finite crash.

**Call-site end-to-end:** stubbed `requests.request` returning 429 with `Retry-After: inf` / `1e400` — `retry_with_backoff` retries with computed jittered backoff (1.0–2.0s observed for `base_delay 2.0`) and falls back correctly; no `math.ceil` crash in the retry loop because `_retry_delay:101-105` clamps `inf` to `max_delay` and `nan` fails `>0`. After exhaustion the `except _RateLimited` branch sees `None` and prints `Retry after 60 seconds` typed 429, not `Unexpected error: cannot convert float infinity to integer`.

**Header shape that still gets through:** none for the non-finite class. The three spellings the brief names (`inf`, `-inf`, `nan`, `1e400` including case/whitespace variants) are all refused on both the string and numeric paths. HTTP-date path is unaffected (`parsedate_to_datetime` then `max(0.0, timestamp-now())` is always finite). No shape found.

### 2. The credential-value span — PARTIALLY FIXED, one bypass and one false-positive remain

**Claim:** `authorization: Bearer <token>` used to grade `Bearer`; `Basic`/`Token` (5 chars, below `{6,}`) did not match at all. Both copies `plugins/unifi/scripts/site_profile.py:169` and `scripts/check_repo.py:184` plus cross-copy pin should be fixed; find a credential shape that still passes and a legitimate prose value that now gets falsely rejected.

**Reproduction — primary shape FIXED:** `CREDENTIAL_VALUE_ASSIGNMENT` at `site_profile.py:169-173` now captures `([^\"',;)}\]]{6,})` running across whitespace, and `CREDENTIAL_SCHEME_WORDS` at `183-185` lists `bearer/basic/digest/token/apikey/hmac/negotiate` with `CREDENTIAL_VALUE_MIN_LENGTH =6` at `190`. `_credential_candidates` at `456-471` returns `[tokens[0]]` plus `tokens[1]` when `tokens[0]` is scheme word. Live: `authorization: Bearer qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` now REJECTED naming `subjects[0].notes`; same for `Basic`, `Digest`, `Token` — all five assertions in `tests/test_site_profile.py:356-410` pass on this tree where twelve failed pre-repair. Both copies `site_profile.py` and `check_repo.py:191-208 + 798-839` share identical constants (verified `CREDENTIAL_SCHEME_WORDS` and `MIN_LENGTH` equal, `credential_findings` vs `_credential_in_text` byte-identical logic), and `site_profile_loader.py:149-485` is identical after `08ab2de` (verified `SUPPORTED_SCHEMA_VERSIONS ("1.0","1.1")`, scheme words equal, pattern equal), closing the 1.1 skew previously.

**Bypass shape that still passes (this cycle):** `authorization: Bearer <redacted> qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890` — ACCEPTED (no exception) on this tree. Candidates are `['Bearer','<redacted>']`; `Bearer` entropy 1.91 skipped, `<redacted>` placeholder via `CREDENTIAL_VALUE_PLACEHOLDER` skipped, so no finding and the real token in third position never examined. Similarly `Bearer vault:infiquetra/unifi#api_key <token>` ACCEPTED (vault: reference skipped) and `Bearer secret <token>` ACCEPTED (`secret` entropy 2.25 skipped). The guarantee claims a credential in an assigned value is rejected wherever it sits behind the scheme word, but the two-candidate helper stops after two tokens, so a placeholder second token hides a real third.

**False-positive legitimate value that now gets rejected (this cycle):** `auth: rotation procedure for runbook` — REJECTED `'auth' is assigned a credential-shaped value` on this tree. `rotation` length 8 entropy 2.50 clears the floor and is not a placeholder/reference, so it fires. Similarly `auth: procedure for rotating credentials` (procedure 2.72), `authorization: documented procedure` (documented 2.92), `auth: authentication end to end` (authentication 3.03), `auth: see` vs `auth: rotation` demonstrates the linter effect: `see` (len 3 filtered) passes, `rotation` flagged — outcome depends on first word's length/entropy, not on credential presence. Ordinary English clears 2.5 (`runbook` 2.52), so false positives are real and occur on plausible operator prose describing where a credential lives — exactly the prose the assignment family was meant to allow.

Both issues are narrow, but they are the same guarantee-but-does-not-bite pattern in miniature: the detector inspects the wrong span (too narrow, stopping after two tokens) and the wrong token (first prose word) with the same visibility as safety.

### 3. The 1.1 contract skew — FIXED, both halves now agree

**Claim:** Claude-path loader was pinned to schema 1.0 while portable half advanced to 1.1.

**Reproduction:** `plugins/unifi/schemas/site-profile.schema.json:14` declares `enum ["1.0","1.1"]`. Portable loader `plugins/unifi/scripts/site_profile.py:92` declares `SUPPORTED_SCHEMA_VERSIONS = ("1.0","1.1")` with docstring `1.1 adds no field and removes none; it records that the secret-free guarantee covers values`. Claude-path loader `plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py:87` now declares `("1.0","1.1")` and `SCHEMA_IDENTIFIER "urn:infiquetra:unifi:site-profile:1.1"` after `08ab2de` diff `792a5d2..7c10002` which added the entire value family (imports `math`/`re`, `CREDENTIAL_VALUE_FORMATS` x11, `CREDENTIAL_VALUE_ASSIGNMENT`, `CREDENTIAL_SCHEME_WORDS`, `CREDENTIAL_VALUE_MIN_LENGTH`, `CREDENTIAL_VALUE_MIN_ENTROPY`, placeholder/reference regexes, `_value_entropy`, `_names_a_secret`, `_credential_candidates`, `_credential_in_text`, `_credential_value` and the `validate_profile` value check). Cross-equality verified: `SUPPORTED_SCHEMA_VERSIONS` equal across both `site_profile.py` and `site_profile_loader.py`, `CREDENTIAL_SCHEME_WORDS` equal, `CREDENTIAL_VALUE_ASSIGNMENT.pattern` equal, `CREDENTIAL_VALUE_FORMATS` labels equal, `CREDENTIAL_VALUE_MIN_LENGTH/ENTROPY` equal (loaded modules via `importlib.util`). Both versions 1.0 and 1.1 load inert documents and both reject `notes: "controller password=qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890"` identically — the former skew (1.1 rejected as `UnsupportedSchemaVersionError` on Claude path, and credential in notes accepted on Claude path but rejected on portable path) is gone.

### 4. The Python floor — FIXED, agrees everywhere and gate bites on the floor interpreter

**Claim:** `python>=3.12`, every declaration must agree, checks on `/opt/homebrew/bin/python3.12` explicitly, mutate and confirm `tests/test_python_floor.py` fails.

**Reproduction:**
- Authority `tests/test_python_floor.py:55` `PYTHON_FLOOR = (3,12)`; `PYTHON_FLOOR_SPECIFIER = "python>=3.12"`.
- Declaration sites `DECLARATION_SITES` = `.github/workflows/ci.yml`, `README.md`, `docs/engineering-journal/DECISIONS.md`, `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md`, `plugins/fleet-core/README.md:48`, `plugins/fleet-core/CHANGELOG.md:33` — all contain `python>=3.12`. Verified via `grep -r "python>=" --include="*.md" --include="*.yml" ... | grep -v docs/reviews` — no disagreement, every `python>=` token in scanned suffixes is `3.12` except blockquoted history and `test_python_floor.py`'s own stale-token fixture.
- CI pin ` .github/workflows/ci.yml:56` `python-version: '3.12'` with step name `Set up Python 3.12` at `:53-56`; `test_continuous_integration_pins_the_floor_interpreter` and `test_the_floor_job_names_the_version_it_pins` enforce it.
- Skill frontmatter `compatibility` is `None` for both `skills/unifi-network/SKILL.md` and `skills/unifi-protect/SKILL.md` — allowed (absence, not disagreement); `test_a_portable_skill_that_declares_compatibility_declares_the_floor` enforces equality when present.
- Floor exercised on real floor interpreter `/opt/homebrew/bin/python3.12` (`CPython 3.12.13`): ` /opt/homebrew/bin/python3.12 -m unittest discover -s tests` → `Ran 420 tests OK (skipped=1)` and `tests/test_python_floor.py` 13 tests OK; `/opt/homebrew/bin/python3.12 -c "from datetime import UTC"` imports (so `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` `from datetime import UTC` is inside contract with room); `plugins/unifi/skills/unifi-network/scripts/_bundled/retry_backoff.py` imports; both clients `--help` exit 0 on `python3.12` with only `requests`/`urllib3`.
- Mutation proof (scratch, reviewed tree untouched): mutating `ci.yml` pin to `'3.10'` makes `test_continuous_integration_pins_the_floor_interpreter` fail with `every python-version pin must be the floor 3.12; found ['3.10']`; mutating `plugins/fleet-core/README.md` token to `python>=3.11` fails `no_file_names_a_different_floor`; deleting a declaration fails `every_declaration_site_states_the_floor` — the gate cannot be defeated by deletion, which was the previous "guarantee that cannot fail" shape.

### 5. Custody and provenance — faithful extraction, pins coherent, transform re-applied

**Claim:** Fleet Core has no target in `scripts/sync_vendor_source.py`, so its byte copy was extracted by hand with `git show <commit>:<path>`; verify faithful and pins coherent at `plugins/fleet-core/PROVENANCE.json` `3b5faa6c` and `plugins/unifi/PROVENANCE.json` `c835f91d`; verify ported test transform re-applied rather than hand-edited.

**Reproduction:**
- `scripts/sync_vendor_source.py:27` `SOURCE_PACKAGE_PATH = "plugins/unifi"` and `TARGET_PACKAGE = "unifi"` are single-package constants; no Fleet Core target — queued work at `docs/engineering-journal/QUEUED.md: Give the synchronization script a Fleet Core target` (P2).
- `plugins/fleet-core/PROVENANCE.json:1-4` pins `source_commit 3b5faa6c1044a888e03cb7b8bbf2f71c6749489c` `source_version 0.25.2` with note `scripts/sync_vendor_source.py derives only plugins/unifi/; it carries no Fleet Core target. This slice's byte copy is therefore extracted ... with git show <commit>:<source_path>, which is the same primitive that script uses internally` and digest equality proves faithful.
- `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` SHA-256 `2aa7fd26bb0fb40dbbd0b7a14ae34f24c473561648695346edaa60079ac63021` recomputed locally equals `PROVENANCE.json:35` `sha256`; `plugins/fleet-core/PROVENANCE.json:9-10` notes both pins name points on one line of upstream history (`3b5faa6c` is where `plugins/fleet-core` subtree last changed, `c835f91d` is its direct descendant which changed `plugins/unifi` and left `plugins/fleet-core` subtree byte-identical, `git diff` over that subtree empty — verified via provenance note and `check_repo` digest match, not re-fetched here).
- `plugins/unifi/PROVENANCE.json:2-3` pins `c835f91d` `2.0.2`; both client transforms record `source_sha256 9dcd6360…` / `1ec114b46c77…` and `sha256 edb45fc…` / `5dc52ea…` with `transform: resolve-bundled-fleet-module v1`; live digest of each file equals recorded `sha256`.
- Both `_bundled/retry_backoff.py` stamps carry `source-version 0.25.2`, `source-commit 3b5faa6c`, `source-sha256 2aa7fd26…` (matches live source), `output-sha256 2aa7fd26…` (hash of file with stamp excluded via `split_bundle_stamp`/`bundle_output_digest` per `scripts/check_repo.py:491-531`); payload (stamp excluded) byte-identical to `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` (verified via `hashlib.sha256(payload)`).
- Ported test `tests/test_retry_backoff.py:1-6` docstring declares `3b5faa6c (Fleet Core 0.25.2)` and `guard-pytest-import v2`; `PROVENANCE.json:derived_files:0` records `source_sha256 07ec46c5…` `sha256 eb1b7b48…` `transform guard-pytest-import v2` with rule `Replace the upstream module docstring ... and replace unconditional import pytest with ModuleNotFoundError-guarded import ... Every line from class RateError to end of file is copied byte for byte, so all eighteen upstream test functions are unchanged` — verified via file read: guard `raise unittest.SkipTest` present, `def test_` count 22 (18 original + 4 new non-finite tests added upstream in 0.25.2), and `scripts/check_repo.py` recomputes `derived_files` digests, so hand-edit would fail provenance.

### 6. The evidence documents — every claim in them true of this tree; prose-inside-JSON class now swept

**Claim:** `docs/evidence/` carries ten-client matrix and post-activation readback, both bound by digest; check every claim true; matrix re-run itself caught stale version string in prose inside a JSON manifest that no gate checked — look for more of that class.

**Reproduction:**
- Current matrix `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` carries `<!-- matrix-status: current -->`; four superseded matrices carry `superseded` with `superseded-by` naming current. `scripts/check_compatibility_matrix.py:311-350` recomputes `package_fingerprint()` (`file_count, tree_sha256` over sorted per-file digests) and fails when `$.package.file_count / tree_sha256 / name / version` diverge; `check_document_status` makes `matrix-status` default `current` so binding is fail-closed. `python3 scripts/check_compatibility_matrix.py --print-fingerprint` returns `file_count 23 tree_sha256 4c256bb20bd054c498056282eb7cbb3cee9c224c422bf1f20bb66422d1d15cfa` equal to the ```json record's `package.file_count 23` `tree_sha256 4c256bb20bd0…` `version 2.0.2` at `matrix.md:328-330` and to the readback's `release.file_count 23` `tree_sha256 4c256bb20bd054c498056282eb7cbb3cee9c224c422bf1f20bb66422d1d15cfa` `version 2.0.2` at `readback.md:195-197`. Live `package_fingerprint(plugins/unifi)` recomputed equals recorded — binding proves identity.
- Post-activation readback `docs/evidence/2026-08-22-unifi-post-activation-readback.md:1-268` records staged load, installed-version/digest readback per client (Grok/Agy/Muse) with client-owned file counts 23 / 4+4 each and per-unit digests `3650ae42…` / `ba06e585…` equal to source units recomputed, plus fresh-session three-state proof (absent/present/unreadable) with `ProfileUnreadableError` and no fallback to discovery-only. Every install recomputed 23 files `4c256bb20bd0…` equal to source tree.
- Method claims held: "Every invocation stage ran on `python3.12`, CPython 3.12.13, in a throwaway venv holding only `requests` and `urllib3`" — verified via `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:104-108` isolation/credentials/network/interpreter sections and `readback.md:179-180`. The `__pycache__` shared blind spot does not affect the evidence docs (they are markdown, not package files).
- **Stale version string in prose inside a JSON manifest:** `08ab2de` commit message describes the defect the re-run caught: `plugins/unifi/plugin.json` description advertised `"the corrected 2.0.1 revision"` after package moved to `2.0.2`. Prose inside a JSON string, so `check_repo`, resync check, bundle check, and 419 tests all passed with it wrong. Fixed at `08ab2de`: `plugins/unifi/plugin.json:5` description now reads `"derived from infiquetra-claude-plugins at the corrected 2.0.2 revision"` and both `plugins/unifi/plugin.json` `version 2.0.2` and `plugins/fleet-core/plugin.json` `version 0.25.2` swept for same class. Full sweep of `plugins/**/*.json` prose-inside-JSON class: every `description` string that contains a version token equal to its manifest `version` (now 2.0.2/0.25.2), not a stale older version; remaining occurrences of `2.0.1`/`0.25.1` are in `CHANGELOG.md` history (intentionally preserved), in `PROVENANCE.json` `notes` history (intentionally preserved as provenance narrative), and in superseded matrix docs (intentionally preserved), none in a current manifest's `description`. No gate currently checks prose inside a JSON string — the commit notes this as "no gate checks — look for more of that class" — and the sweep shows no remaining instance in a current manifest, but the class remains ungated for future edits.

### 7. The Cursor Agent correction — sound, honestly disclosed, no identity leak

**Claim:** Superseded matrix recorded Cursor as failed on credential gate; that run exported empty scratch HOME stripping real authentication, measuring unauthenticated client rather than first-run one. Reassessed against operator's real home and now reads works-directly.

**Reproduction:**
- Superseded matrix `docs/evidence/2026-08-22-unifi-compatibility-matrix-pre-unifi-202.md:3` `superseded-reason` names the harness artifact and notes successor reassesses against operator's real home.
- Current matrix `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:109-114` Isolation section states: `Nine clients ran against their own empty home directory in a scratch area. ... Cursor Agent is the single exception, for a reason the earlier publication of this matrix got wrong: that client keeps its authentication in the user's home, so an empty scratch home did not test a first-run client, it tested an unauthenticated one, and the refusal recorded was the isolation's rather than the client's. Cursor was therefore reassessed against the operator's real home with the same read-only, credential-free rules as every other row — its authentication state recorded only as present, no credential created, changed, or read into this evidence, and no account identity published here.` The same explanation appears in commit `08ab2de` message and in the Cursor row `400-420` with "What the superseded publication said, and why it was wrong."
- **Soundness:** Correction is sound. Cursor's placement flag is session-scoped local-plugin path; its marketplace subcommand declares only a git URL, so local dir cannot be added there. Its authentication state (as with many CLIs) resides in HOME. An empty scratch HOME therefore measures `unauthenticated` not `first-run`, and the recorded `failed` was a harness failure, not a package or client failure. Reassessment under real HOME used a bounded read-only session probe (`forbidden filesystem, shell, network, and UniFi tools` per row `414`) enumerating loaded components and distinguishing the session-loaded copy from the marketplace-installed plugin of the same name — the same read-only, credential-free rules as every other row, with `UNIFI_` vars removed and no controller call. Result `works directly` is justified: placement executed, discovery executed, load executed (plugin `unifi` contributes exactly two components, skill `unifi-network` and `unifi-protect`, no version in session context matching the other session-scoped client), invocation executed via the resolved `_bundled` path on `python3.12`. Totals move 38 executed / 2 blocked / nine works-directly / none failed — recorded as observed.
- **Isolation relaxation honestly disclosed:** Yes. The isolation section names the relaxation (9 isolated, 1 exception), the reason (isolation was itself the cause), the scope (Cursor only), and that the same read-only, credential-free rules applied. It is not silent; it is the most explicit of the four held-identical bullets. The "Held identical across all ten: Isolation" heading is arguably slightly misleading (they were not identical), but the paragraph immediately qualifies it with the single exception and its rationale — honest disclosure.
- **Account identity leaked into published evidence:** No. `rg` for email pattern, `/Users/`, `jefcox`, `namredips`, `hello@` over `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` and `docs/evidence/2026-08-22-unifi-post-activation-readback.md` finds none; the Cursor row records `authentication state recorded only as present, no account identity published here` and the probe's evidence is component names and paths under scratch/real home, not `~/.cursor` contents. The evidence carries no user path, email, or token. `Qwen` observation (24 files vs 23) similarly records a client-owned copy plus install record without publishing a path that identifies the operator.

### 8. Anything four cycles missed — two residual credential-rule defects and one swept class

Beyond the eight brief items, this review probed for remaining "guarantee that does not bite":

- **F-01/F-02 above** are the cycle-5 residuals of the credential-value family introduced in `367d9b6` and extended to the Claude-path loader in `08ab2de`. They are the new members of the named pattern: the guarantee (value half rejects a credential in an assigned value) exists, is enforced, and has tests, yet a narrow span (third token behind a placeholder) and a narrow prose trigger (first English word) still get through / still fire. They were unreported through cycles 2–4 because the must-not-fire set covered `vault:`/`env:`/`redacted` and `see`-prefixed prose but not high-entropy English first tokens, and three-token bypass was not in the characterization.
- **Prose-inside-JSON manifest** class (item 6) was missed through four cycles until the matrix re-run caught it; the sweep above shows no remaining current-manifest instance but the validator still does not check prose inside JSON strings, so the class remains ungated.
- **Negative-hint advice** (`parse_retry_after` returns `-5.0` for `"-5"` which is finite; `_retry_delay` correctly falls back to computed jitter, but `advice = math.ceil(-5.0)` after exhaustion would report `Retry after -5 seconds` — a small operational polish, not a silent-green crash, and the same shape as pre-repair; not admitted as P but noted for completeness.
- **__pycache__ shared blind spot** (F-03) and **low-entropy secret** (F-04) and **binding-is-not-execution** (F-05) correctly remain as advisory with documented limits — not missed, but preserved.

## Built-vs-planned audit (against `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:1-473` and `docs/engineering-journal/DECISIONS.md`)

Verification modes: DIFF (`git diff 2bd0faf..08ab2de` 18 files + resync), CROSS-REPO (sibling `infiquetra-claude-plugins@3b5faa6c/c835f91d` via byte-copy digests and provenance; `git show` primitive not re-executed from this repo but digests recomputed), EXTERNAL-STATE (operator-run matrix, no live controller).

### Scope-drift detection (informational)

Intent (from plan summary `plan:10-15` + requirements R01..R45 + units U01..U12): land portable UniFi + Fleet Core slice, close validator gaps, re-run evidence, pause for operator decision — no new plugin, no vendor manifest generation.

Delivered: exactly that. No feature added outside plan's units; `parse_retry_after` non-finite guard is additive within Fleet Core 0.25.2, `site_profile_loader.py` value rule is the same 1.1 contract the plan already required, and the nine-client matrix re-run isolates package change from client change (same ten client versions as superseded). No unrelated drift.

### Plan-completion (5-state: DONE / PARTIAL / NOT-DONE / CHANGED / UNVERIFIABLE)

| # | Requirement | State | Evidence `file:line` |
|---|---|---|---|
| R01 | Derived artifact + provenance script | DONE | `scripts/sync_vendor_source.py:1`, `plugins/unifi/PROVENANCE.json:2` pins `c835f91d` `2.0.2` |
| R02 | Hermetic provenance validation | DONE | `scripts/check_repo.py:260` `python3 scripts/check_repo.py` passes |
| R03 | Pin corrected revision, never 995a475 | DONE | `plugins/unifi/PROVENANCE.json:3` `2.0.2@c835f91d` descendant of `3b5faa6c`; `plugins/fleet-core/PROVENANCE.json:4` `0.25.2@3b5faa6c`; 995a475 ancestor, doc repair included |
| R04 | Three-way classification, no divergence | DONE | `PROVENANCE.json` byte-copy/transform/target-owned per file, `README.md` target-owned+`SUPERSEDED_BY_TARGET_OWNED`, `sync_vendor_source.py:27-148` exhaustive |
| R05..R07 | Upstream docs repair (Protect/Network refs, skill frontmatter) | DONE | CROSS-REPO `c835f91d` carries repair; `plugins/unifi/skills/*/SKILL.md` frontmatter allowed 6 fields, `check_skill_frontmatter` green |
| R08 | Remove hard-coded controller default | DONE | `c835f91d` portable `plugins/unifi/scripts/unifi_*_client.py:92-109` host required, no default |
| R09 | Release gated on replacement profile path | DONE | `docs/evidence/2026-08-22-unifi-post-activation-readback.md:1` three-state fresh-session proof |
| R10..R15 | Site profile optional, no inference, secret-free, path custody | DONE | `site_profile.py:1` stdlib only, `site-profile.schema.json:1` version 1.1 with both value families; name+value checks cite `CREDENTIAL_VALUE_FORMATS:150-165` and `CREDENTIAL_VALUE_ASSIGNMENT:169-173` (F-01/F-02 are residual narrow spans, not missing requirement) |
| R16..R21 | Portable Fleet Core slice + deferred inventory + bundling | DONE | `plugins/fleet-core/*`, `fleet-bundle.json`, `bundle_fleet_module.py`, `_bundled/retry_backoff.py` (both) stamp 0.25.2 |
| R22..R25 | Ten-client matrix | DONE | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` current, 23 files `4c256bb20bd0…` version `2.0.2`, binding in `check_compatibility_matrix.py:311-350` |
| R26..R27 | Read-only, default-deny persistence | DONE | `discover.py:78` `READ_ONLY_OPERATIONS` only GET, `300-343` two-rung refuse plus `PACKAGE_ROOT` and undeterminable → raise |
| R28..R29 | Manifest + skill frontmatter conformance | DONE | `plugins/unifi/plugin.json` `$schema` canonical, skill `name` matches dir; `check_skill_frontmatter` green |
| R30..R31 | Orchestrate/Herdr topology | UNVERIFIABLE | not observable from diff; prose in `README.md` and evidence docs unchanged |
| R32..R33 | Fleet Core custody + release surface | DONE | `plugins/fleet-core/PROVENANCE.json:6-11` `Custody does not move`, `release_surface` enumerates 5 items, two pins coherent per note 3 |
| R34..R35 | Build declaration + two digest domains | DONE | `fleet-bundle.json` closed schema, `check_repo.py:491-630` two-domain `output-sha256` vs `source-sha256` |
| R36..R39 | Profile JSON, entrypoint, intents unknown | DONE | `site_profile.py:36` stdlib only, `discover.py:489-531` `proposed_profile` unknown intent + `assert_unknown_intent`, `tests/test_discover.py:493-518` pins field-by-field |
| R40..R42 | Release activation + rollback + fresh-session proof | DONE | transition evidence + `docs/evidence/2026-08-22-unifi-post-activation-readback.md` with `python3.12` evidence on floor interpreter |
| R43..R44 | Evidence completeness + sanitization | DONE | `check_compatibility_matrix.py:101` `package_fingerprint`, `466` public-evidence rules; evidence carries `file_count`/`tree_sha`/`package` + redacted commands, no identity leak |
| R45 | Upstream docs-map-to-code suite | CROSS-REPO | sibling repo test `test_unifi_docs_match_code.py` not in this tree; acceptor is provenance digest equality |

COMPLETION: 42 DONE, 0 PARTIAL, 0 NOT-DONE, 0 CHANGED, 3 UNVERIFIABLE. No plan requirement genuinely missing.

## Coverage, residual risks, and new defects the repairs introduced

- Superseded misses: none — `matrix_documents()` validates every `*.md` under `docs/evidence/` that embeds a matrix record; all five documents (four superseded + one current) validate.
- Validators that cannot fail — proved they can: `check_provenance_manifests` would fail on `smuggled.pyo`, `check_bundled_files` would fail on unstamped/tampered bundle and stale source (proved on scratch copy in cycle-4, logic unchanged), `check_secret_free_values` fired on `notes: "controller password=qY7vP2xK9rLm4aZbC8dEfGhJk...` before credential span fix and still does, `check_package_binding` failed on `da46ca77→cafe8836→4c256bb2` transitions before re-runs, `refuse_repository_output` inside `PACKAGE_ROOT` / docs / gitless walk raises `DiscoveryPersistenceError`.
- Ambient-state tests — `discover.py`/`drift.py` tests pin `XDG_CONFIG_HOME` inside `TemporaryDirectory` so real `~/.config/infiquetra/unifi/config.json` no longer leaks into no-profile tests; `gitless_walk` negative case asserts `--repository-root` naming on real gitless directory without monkeypatch.
- New defects the repairs introduced:
  - Non-finite `Retry-After` repair introduced no defect: primitive now `_usable_delay` with `math.isfinite`, both RFC 7231 forms handled, past→0.0, clamp to `max_delay`, fallback to computed jitter, both call sites typed `float|None`, six new non-finite tests pass and `test_every_reduced_hint_survives_being_turned_into_whole_seconds` asserts `math.ceil` safety for every header a server can send.
  - 1.1 loader skew repair introduced no defect: adds 180 lines mirroring portable loader, no new dependency, both `SUPPORTED_SCHEMA_VERSIONS` now dual, value rule same two families; the narrow bypass/false-positive residuals are not new defects of this repair but residuals of the same span logic chosen in `367d9b6`.
  - Credential span repair narrowed the primary `Bearer` bypass but left F-01 (placeholder hiding third token) and F-02 (English first token false positive) — the only new "exists but does not bite" members this cycle, and the scores above reflect them (security `secrets 7`, `input 8`, correctness `intent 8`).
  - Prose-inside-JSON manifest defect class was not gated before and is not gated by a validator still; the re-run fixed the one instance, sweep shows no remaining current-manifest instance, but the class remains a future drift risk.
- Public-boundary leaks: `rg` for `10.`, `192.168`, MAC, `password`, `secret` in `docs/evidence/*.md` finds only redacted commands and `vault:`/`redacted` markers; `192.168.1.10` in `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:1111` is inert static-DNS help-text example not site-identifying inventory (prior cycle advisory, still present, no gate).
- Testing debt: none new; 419/420 tests green; eight `test_check_compatibility_matrix` failures before re-run are now desired binding behavior.

### Engineering-journal alignment

Correctly appended: `DECISIONS.md` records `The portable catalog's minimum supported Python is python>=3.12` with superseded rationale preserved, `Compatibility evidence is captured on the floor interpreter, by explicit path`, and `Bind a current matrix to the tree it assessed`; `LEARNINGS.md` records `The credential detector read the wrong span, so Bearer cleared the token behind it`, `Fixing a shared primitive does not fix the callers`, and `A bound digest names the tree, not the forty stages`; `QUEUED.md` correctly archives zero P0 (carried shipped entry moved to ARCHIVE.md in `367d9b6`), `Declare the catalog's Python floor in the UniFi skills' frontmatter, upstream` P2 honestly queued (byte-copy custody, test pins `compatibility` when present), and `Maybe Keep the matrix binding an identity check` as Maybe; `ARCHIVE.md` correctly archives the Fleet Core bundle P0 as shipped in `4c1d30f`.

## Outcome and routing

> **Plain answer: not yet safe to merge and release under the contract's own numbers — the outcome is `repairs_requested`.** Both cycle-3 blocking defects (caller `int(Retry-After)` and `datetime.UTC` floor) are genuinely fixed and proved end-to-end on the floor interpreter, the 1.1 contract skew is closed with both loaders byte-identical on the value half, provenance extraction is faithful with coherent dual pins, the evidence binding is true of this tree and the prose-inside-JSON stale version is fixed with no remaining current-manifest instance, and the Cursor Agent correction is sound and honestly disclosed with no identity leak. However, seven of ten scored lenses sit below `derived_overall >= 9.0` and two residual defects remain in the credential-value rule — a real token hidden behind a placeholder second token passes (`F-01`), and ordinary English prose after a credential-shaped key is falsely rejected (`F-02`) — plus the ungated prose-inside-JSON class. This repository's trust model is that its records match its tree, and the credential-value guarantee is that a credential in a value is rejected while prose is not; those two narrow spans violate that model. The `combiner: all` rule requires `derived_overall >= 9.0` and `applicable_dimension >= 7.0`; dimension floor passes (lowest 7) but overall fails (seven lenses 8.29–8.86). The numbers give `repairs_requested` before any Priority is consulted, and this report does not write `accepted` over a failing number nor argue the overall threshold is an excellence bar — that argument was made in cycle 4 and the operator has ruled it does not apply.

`schema: review_result.v1` (for this report's scoring) — `best_available_revision: 08ab2de` — `outcome: repairs_requested` — `next_action: return_to_work` — `failing_lenses: [architecture-maintainability, correctness, security, testing, reliability, api-contract, adversarial, agent-usability]` — `failing_dimensions: none` (all ≥7, but overall <9 drives the outcome) — `F-01 (P2 gated_auto)`, `F-02 (P2 gated_auto)` route to `/work` as one credential-span sweep across all three copies plus pin test; keep `F-03/F-04/F-05` as advisory with documented limits; then resubmit — with F-01/F-02 landed every failing lens's driver is gone and the honest verdict would be `accepted`.

No saga write performed: this session ran as an independent programmatic reviewer against a scratch artifact path; no work-thread saga was scanned or minted. No file writes to reviewed code, no commits, no pushes, no PRs opened (gate, not fixer).

Suppressed findings: 0. Residual risks: `__pycache__` shared blind spot (`.gitignore` stands between it and shipping), low-entropy short secret admitted limit, binding-is-not-execution Maybe — all advisory and documented.

Raw evidence run this session: all gates green on `08ab2de`; both `parse_retry_after` non-finite probes on real imports (`inf`/`nan`/`1e400` → `None`, `math.ceil` safe); credential-value probes on real `site_profile.validate_profile` and `check_repo.credential_findings` (Bearer/Basic/Token caught, placeholder bypass accepted, rotation/procedure flagged, `vault:`/`<redacted>`/`${VAR}` correctly passed); floor interpreter `python3.12` 420 tests OK and `datetime.UTC` imports; `check_compatibility_matrix --print-fingerprint` 23 files `4c256bb20bd0…` equal to matrix and readback records; provenance SHA recomputation equal; cross-copy `CREDENTIAL_SCHEME_WORDS`/`SUPPORTED_SCHEMA_VERSIONS` equality verified; `grep` sweep for `2.0.1` inside current `plugin.json` descriptions clean; isolation disclosure and identity-leak `rg` clean.

Reviewer: opencode/muse-spark-1.2 (independent, different session, no cross-reviewer communication)
Reviewed revision: `08ab2ded7b2a6743bedd1df64bc57e66ec96afc0` (`orch/orch-2026-08-22-unifi-cycle3`)
Merge-base for this review: `8824fea`
Roster: `lens_roster.v1` — 14 lenses, 10 scored, 7 below 9.0 overall but no dimension below 7.0; ship readiness is `repairs_requested` per the roster's own `combiner: all` rule.


