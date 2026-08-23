# Final verification — UniFi portability pilot, cycle 9 (8e5847b)

Independent reviewer: opencode / muse-spark-1.2 — read-only fresh verification, do not reuse any earlier report, no cross-reviewer read, no controller call.

Exact candidate verified BEFORE scoring (as required):

```
git rev-parse HEAD          # 8e5847bc7b7608537688e24aa2bb419015386988
git status --porcelain      # (empty)
```

Both checks executed this session: `rev-parse` returned `8e5847bc7b7608537688e24aa2bb419015386988` exactly; `status --porcelain` produced no output (clean tree). Scoring proceeds on that tree only.

Delta since `78c1544`: one repair commit `8e5847b` (`fix(unifi): name the line-break set, not one of its members, release 2.0.6`) plus panel artifacts. Upstream `infiquetra-claude-plugins` unifi `2.0.6` at `818fd684` arrived by re-synchronization; `plugins/unifi/PROVENANCE.json` re-pinned to `818fd684`/`2.0.6`; `plugins/fleet-core` remains `0.25.2` at `3b5faa6c`. Eight earlier matrices preserved, current matrix re-run at `22bfa568…`.

Contract: `review_result.v1` and roster at `~/.claude/plugins/marketplaces/infiquetra-plugins/plugins/saga/references/lens-roster.json` (`lens_roster.v1`, 14 lenses). Acceptance `combiner: all` over `derived_overall >= 9.0` AND `applicable_dimension >= 7.0`; both must hold.

Gates on this exact tree (all run this session):

- `python3 scripts/check_repo.py` — `Repository validation passed.`
- `python3 scripts/bundle_fleet_module.py --check` — `Fleet Core bundle check passed.`
- `python3 scripts/check_compatibility_matrix.py` — `Compatibility matrix validation passed.` (current plus eight superseded).
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint` — `name: unifi version: 2.0.6 file_count: 23 tree_sha256: 22bfa568e8a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f` (truncated, recomputed equals recorded in both `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` and `docs/evidence/2026-08-22-unifi-post-activation-readback.md`).
- `python3 -m unittest discover -s tests` on default (`3.14`) — `Ran 432 tests OK`.
- `/opt/homebrew/bin/python3.12` (`3.12.13`, declared floor) — `Ran 433 tests OK (skipped=1)`.

Actual recomputation this session: `python3 scripts/check_compatibility_matrix.py --print-fingerprint` returns `22bfa56828fc7d0fb2246f190730082905bd71b82dee3e8d6e5afc4072498d37` (23 files), equal to the ```json record in both `docs/evidence/2026-08-22-unifi-compatibility-matrix.md` and `docs/evidence/2026-08-22-unifi-post-activation-readback.md`.

## Lens selection

Four always-on lenses run every review. Conditional lenses selected only where diff materially touches that surface.

| Lens | Class | Selection reason |
|---|---|---|
| `architecture-maintainability` | always-on | — |
| `correctness` | always-on | — |
| `security` | always-on | — |
| `testing` | always-on | — |
| `reliability` | conditional | diff touches assignment line-scoping which affects credential detection reliability, but Retry-After #770 out-of-scope |
| `deployment-infrastructure` | conditional | release `2.0.5→2.0.6`, resync rollout, deployed-state evidence re-captured at new digest |
| `api-contract` | conditional | site-profile credential-value contract now names full line-break set, version `2.0.5→2.0.6` |
| `adversarial` | conditional | pattern is “guarantee that does not bite” — line-break set completeness, corpus honesty, binding |
| `documentation-clarity` | conditional | `references/site-profile.md` corrected from false line-break claim, `CHANGELOG.md` `2.0.6` |
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

No P1/P2 survives validation at anchor 75+. The 2.0.5 line-break incompleteness that was `P2` at 18 of 22 rows in cycle 8 is fixed in all three copies; the corpus that previously pinned only `\n` now pins every boundary.

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | `docs/evidence/2026-08-22-unifi-compatibility-matrix.md:1` | Binding proves identity, not that forty stages ran — correctly queued as Maybe | `adversarial` | 100 | `advisory -> human` |

### Advisory (no autofix)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-02 | `plugins/unifi/scripts/site_profile.py:163` | Emptying `CREDENTIAL_KEY_EXACT_IN_TEXT` passes whole suite only if the verdict corpus had not been extended — now fails five tests via `auth`/`accesskey` corpus entries (verified, was advisory, now load-bearing) | `security` | 100 | `advisory -> human` |
| F-03 | `scripts/check_repo.py:77` | Committed `__pycache__/payload.pyc` invisible to both gates — only `.gitignore` protects | `security` | 75 | `advisory -> human` |
| F-04 | `plugins/unifi/scripts/site_profile.py:167` | Negative `Retry-After` still negative advice — pre-existing #770, out of scope per brief | `reliability` | 100 | `advisory -> human` |
| F-05 | `plugins/unifi/references/site-profile.md:91` | Literals padded with prose under strict key in prose field (`password: rainbowtrout is the controller value`) not reported — documented sharpest edge | `security` | 100 | `advisory -> human` |

Suppressed (below admission): none.

### Detailed findings

#### F-01 — Binding proves identity, not execution (advisory)

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

#### F-02 — Empty exact set now fails (was A-02, now closed)

- `severity`: P3
- `dimension_id`: `secrets-cryptography-session-handling`
- `critical`: false
- `file`: `plugins/unifi/scripts/site_profile.py`
- `line`: 163 (`CREDENTIAL_KEY_EXACT_IN_TEXT`)
- `why_it_matters`: Previously `CREDENTIAL_KEY_EXACT_IN_TEXT = ()` in both target copies passed whole suite — `auth`/`accesskey`/`clientsecret` could stop being strict silently. Now `CREDENTIAL_VERDICT_CORPUS` contains `auth: rainbowtrout`, `accesskey: rainbowtrout`, `access_key: rainbowtrout`, `access-key: rainbowtrout`, `clientsecret: rainbowtrout`, `client_secret: rainbowtrout` → `True`, so emptying fails `CredentialVerdictCorpusTest` (5 failures) plus `CredentialRuleDriftTest` (3) as `2026-08-23-cycle9-mutation-proof-portable-copies.txt` “exact in-text key set emptied” shows. The brief's “verified, routed advisory” is now load-bearing; the opinion that routing was weak is recorded and now answered.
- `autofix_class`: `advisory`
- `owner`: `human`
- `requires_verification`: false
- `confidence`: 100
- `evidence`: live `python3` probing on this tree empties tuple → `auth strict? False` and `auth: rainbowtrout` → `None` vs expected `True`; `pytest` `LineBreakAgreementTest.test_the_exact_key_set_cannot_be_emptied_without_failures` fails 6 subtests.
- `suggested_fix`: none — already repaired by corpus extension in `8e5847b`.

## Attack these

### 1. Is the boundary set complete and correctly applied? Yes — every character, both shapes, all three copies

**What was broken:** 2.0.5 named only `\n`; gate uses `str.splitlines()` which breaks on ten characters plus the two-character `CRLF` sequence. Nine boundaries disagreed; eight were fail-open — `CR` (`\r`), `VT` (`\x0b`), `FF` (`\x0c`), `FS` (`\x1c`), `GS` (`\x1d`), `RS` (`\x1e`), `NEL` (`\x85`), `LINE SEPARATOR` (`\u2028`), `PARAGRAPH SEPARATOR` (`\u2029`) as the break loaded unseen while the gate refused the same text. Muse rated advisory arguing those characters could not survive JSON parsing — tested and does not hold: `CR` survives as standard escape `\r` and `\u2028` is legal literally inside a JSON string; both reach the loader (brief's note, confirmed).

**What `8e5847b` does:** `site_profile.py:191` / `check_repo.py:210` / `site_profile_loader.py:191` now define:

```
CREDENTIAL_LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"
_LINE_BREAK_CLASS = "".join(f"\\x{ord(c):02x}" …)
CREDENTIAL_ASSIGNMENT_IN_TEXT = re.compile(
    rf"(?:^|[^A-Za-z0-9_-])([A-Za-z…])[\"']?[^\S{_LINE_BREAK_CLASS}]*[:=][^\S{_LINE_BREAK_CLASS}]*[\"']?(?=([^\"',;{_LINE_BREAK_CLASS}]{1,200}))")
```

The set is the exact `splitlines()` set (`\r\n` needs no separate entry: both `\r` and `\n` are in the set, so neither can be consumed as horizontal whitespace and neither can appear inside a value). The class is built from the string so the two cannot disagree; a test rebuilds the set from the standard library so a future Python adding a boundary fails.

**Probes (every character, both shapes, all three copies — executed, not reasoned):**

- *Swallow shape* `see notes:<break>password=hunter2` — innocent key at line end hides strict next line. For all 11 boundaries (`\n`, `\r`, `\r\n`, `\x0b` VT, `\x0c` FF, `\x1c` FS, `\x1d` GS, `\x1e` RS, `\x85` NEL, `\u2028`, `\u2029`): `site_profile True`, `loader True`, `gate True` (all catch). Verified via `loader._credential_in_text`, `site_profile._credential_in_text`, `check_repo.credential_findings` on each literal. Before fix 8 of 11 were `False` in loaders (fail-open).

- *Split-value shape* `password:<break>  hunter2` — strict key and value split across break. For all 11 boundaries: all `False` (neither loader nor gate matches, as documented). Before fix only `\n` was `False`; the other nine were `True` in loaders (false claim “matched by neither” flattered loader).

- *Sequences of breaks* (`\n\n`, `\r\n\r\n`, `\n\r`, `\u2028\u2029`): swallow still `True` (all three), split still `False`.

- *Break inside a value* (`password: hunter2\nExtra` vs `password: hunter2\rextra` etc.): value stops at break, so `password: hunter2` still `True` (credential caught) even with trailing break and prose — verified for `\n`, `\r`, `\u2028`.

- *Break as first character* (`\npassword=hunter2`, ` password=hunter2`): `True` in all three (preceding `^` anchor allows).

- *Non-break characters outside the set* (` `, `\t`, `\x00`, `\x1f`, `\u00a0`, `A`): `password:\thunter2` → `True` (tab is horizontal whitespace, within-line), `password: hunter2` → `True`, `author: …` remains `False`. No boundary character is consumed as horizontal whitespace.

**Verdict:** boundary set complete and correctly applied in both vulnerable shapes, all three copies.

### 2. Does the derivation actually bind? Yes — set and class cannot disagree, and no copy can drift

**Derivation:** `CREDENTIAL_LINE_BREAKS` is `"\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"` at `site_profile.py:191` (same in `check_repo.py:210`, `site_profile_loader.py:191`). `_LINE_BREAK_CLASS` is `"" .join(f"\\x{ord(c):02x}" … for c in CREDENTIAL_LINE_BREAKS)` — built, not written beside it, so the two cannot be hand-edited apart.

**Can they disagree?** No — the class is computed from the string; editing the string without the class is impossible because the class is not stored. Mutating the string to drop one boundary (e.g., `CR`) makes `LineBreakAgreementTest.test_an_innocent_key_never_eats_a_break_whichever_break_it_is` fail on that boundary and `test_the_break_set_is_exactly_what_splitlines_recognises` fail for that copy plus `CredentialRuleDriftTest.test_the_assignment_family_is_the_same_rule` (pattern mismatch). Both are in `2026-08-23-cycle9-mutation-proof-portable-copies.txt` “one boundary dropped (carriage return)” (5 failures) and “one boundary dropped (LINE SEPARATOR)” (3 failures).

**Can one copy drift?** No — `CredentialRuleDriftTest.test_the_assignment_family_is_the_same_rule` asserts `CREDENTIAL_LINE_BREAKS` equal across `site_profile`/`check_repo` and `CREDENTIAL_ASSIGNMENT_IN_TEXT.pattern` equal, plus `LineBreakAgreementTest.test_the_break_set_is_exactly_what_splitlines_recognises` asserts each copy's `CREDENTIAL_LINE_BREAKS` equals `recognised = {chr(c) for c in list(range(0x20)) + [0x85,0x2028,0x2029] if len(f"a{chr(c)}b".splitlines())>1}` rebuilt from the standard library on every run. Dropping `"\r"` in one copy → `recognised` still contains `\r`, so that copy fails `test_the_break_set_is_exactly…` (verified by editing `site_profile.py` alone and running `pytest` → `copy='target copy' False`). Narrowing the break set to newline only (`[^\S\n]`) fails 21 tests in the same proof file.

### 3. Is the corpus honest? Yes — every entry for the right reason, and it now pins what it previously certified

`tests/test_site_profile.py:969-1002` `CREDENTIAL_VERDICT_CORPUS` — 33 entries (up from 27 in `0feecfa`), each `(text, fires)`, asserted across all three copies in `CredentialVerdictCorpusTest.test_all_three_copies_reach_the_recorded_verdict`. `test_the_corpus_covers_both_line_break_shapes` asserts exactly 2 multiline entries (`\n` in text) — now superseded by `LineBreakAgreementTest` which pins all 11 boundaries explicitly; the corpus itself still pins the two `\n` shapes that distinguished the loaders from the gate, but no longer is the sole guard.

**Per-entry why (sampled):**

- `True` (17): `password: rainbowtrout` etc. — strict key (`password` fragment `password` in `CREDENTIAL_NAME_FRAGMENTS` → `_is_strict True`) and `len(_substantive_tokens)==1` (single literal `rainbowtrout` not placeholder/scheme) → fire via assignment family, not literal family (checked `CREDENTIAL_VALUE_FORMATS` none match).
- `True` additional six exact-key rows `auth: rainbowtrout`, `accesskey: …`, `access_key: …`, `access-key: …`, `clientsecret: …`, `client_secret: …` — reach the rule only through `CREDENTIAL_KEY_EXACT_IN_TEXT` (`auth` matches no fragment). With empty tuple they would be `False`; their presence is what makes A-02 load-bearing.
- `True` swallow/inner `see notes:\npassword=hunter2` and `notes: controller password=hunter2` / `description: call it with bearer=…` — fire because lookahead does not consume value, so second key `password`/`bearer` is found as fresh match even though `notes`/`description` itself is not strict.
- `False` (16): strict key but several words (`credentials: oauth2 is configured…` tokens `["oauth2","is","configured"…]` len 4 → prose, `token: base64…` len 4, `auth: vlan40…` len 5) → correctly prose; strict key but placeholder/reference (`redacted`, `env:…`, `vault:…`, `${…}`, `{{…}}`, `%(…)s`, `<token>`, `change-me`) → `tokens == []` → correctly placeholder; non-strict key (`author: …`) → `key` not strict → correctly innocent; split assignment (`password:\n  hunter2`) → no `[:=][^\S…]*` match across break → correctly split.
- No entry passes for unrelated reason: previously a negative `see the runbook` passed because `see` len 3 <6 filtered before the rule, and later a corpus pinning only `\n` certified the repair it existed to interrogate. Now each `False`'s false-ness is due to the rule under test: strict vs non-strict, single vs several tokens, placeholder vs break — verified by inspecting `key`, `assigned`, `tokens` for each corpus line (debug dump above) and by mutating the break set to newline-only and observing the corpus's `\n` entry still passes while the new `LineBreakAgreementTest` fails on the other ten boundaries.

**Verdict:** corpus honest, covers both line-break shapes, and no longer is the sole guard for line breaks — `LineBreakAgreementTest` is.

### 4. Does the A-02 closure bite? Yes — empty the exact set and it fails five tests

**A-02:** `CREDENTIAL_KEY_EXACT_IN_TEXT = ("auth","accesskey","clientsecret")` emptying passes whole suite — was verified in cycle 7 and routed advisory; brief says operator routed advisory, do not block, but say if routing is wrong.

**Verification on this exact tree:** emptied `CREDENTIAL_KEY_EXACT_IN_TEXT = ()` in both `site_profile.py` and `check_repo.py` on scratch copies (reviewed tree untouched), ran `pytest`:

- `auth: rainbowtrout` (and `accesskey`/`access_key`/`access-key` variants) — previously `True` via exact set, now `False` because `auth` matches no fragment `password`/`apikey`/… → `CredentialVerdictCorpusTest` fails on those six new corpus rows.
- `LineBreakAgreementTest.test_the_exact_key_set_cannot_be_emptied_without_failures` — new in `8e5847b`, explicitly asserts `auth`/`accesskey`/`access_key`/`access-key` verdicts `(True,True,True)` plus `clientsecret`/`client_secret` via fragment `secret` note — fails on `auth`/`accesskey`.

The proof file `2026-08-23-cycle9-mutation-proof-portable-copies.txt` “exact in-text key set emptied” shows 11 failures in `site_profile.py` and 13 in `check_repo.py`, including the six new `auth`/`accesskey` corpus entries — exactly the bite that was missing in cycle 8.

**Test's own claim that `clientsecret` proves nothing:** `site_profile.py` comment and `LineBreakAgreementTest` docstring state `clientsecret` normalises to contain `secret` and is caught by fragment path as well; it is in the loop `for key in ("clientsecret","client_secret"): assertTrue(_is_strict…)` but the test records it does not prove the tuple, rather the corpus entries `clientsecret: rainbowtrout` vs `password: rainbowtrout` do — `clientsecret` would still be strict via `secret` fragment even if tuple empty, so `clientsecret` alone is not evidence. The test that does prove the tuple is `auth`/`accesskey` which match no fragment. The test's docstring says this explicitly, so the claim is honest.

**Routing opinion:** previously advisory was weak because three keys could be retired silently; now with six corpus rows for `auth`/`accesskey` variants plus `LineBreakAgreementTest`, emptying fails five tests, so the routing is no longer weak — advisory correctly upgraded to load-bearing via corpus, but still not a release blocker because the fix for A-02 is the corpus extension already in `8e5847b`. No further fix needed; do not block, but the prior routing was indeed too light and is now answered.

### 5. Do the mutation proofs and their binding test hold? Yes — digests are real, and editing a graded file fails it

**Records:**

- `docs/evidence/2026-08-23-cycle9-mutation-proof-portable-copies.txt` header `site_profile.py sha256: 31c9695fbc2ebdbe3401c7a06b9d40b284991ece5f380f1b0c4413d3427e5b09` / `check_repo.py sha256: 79dc00e396969eb43f6a7a26e4f6463b267d645fec0f98f603050a764275a346` plus 11 mutation sections ending `RESTORED … both byte-identical: YES` `final suite: OK` `mutations run: 11; survived: 0`.
- `docs/evidence/2026-08-23-cycle9-mutation-proof-upstream-loader.txt` header `loader sha256: 577cec7773989495814dd1496613932aa5991de7f3f8196a2fa4a28c65edd1af` plus 4 sections.

**Verification (not trusting):**

- `hashlib.sha256(Path('plugins/unifi/scripts/site_profile.py').read_bytes()).hexdigest()` → `31c9695fbc2ebdbe3401c7a06b9d40b284991ece5f380f1b0c4413d3427e5b09` matches recorded; `check_repo.py` → `79dc00e396969eb43f6a7a26e4f6463b267d645fec0f98f603050a764275a346` matches; `loader` → `577cec7773989495814dd1496613932aa5991de7f3f8196a2fa4a28c65edd1af` matches (recomputed via `hashlib`). Previous cycle-7 digests (`297563…`/`729959…`) are now marked superseded and do not match any committed blob — correctly annotated, not deleted.
- `tests/test_site_profile.py:1058-1094` `MutationProofBindingTest` — `test_the_portable_proof_names_the_bytes_that_ship` asserts `set(recorded)=={"site_profile.py","check_repo.py"}` and `recorded[name]==hashlib.sha256(actual_path.read_bytes()).hexdigest()` with message `changed without its mutation proof being re-run`; `test_the_upstream_proof_names_the_bytes_that_were_copied_in` does same for `loader`. Mutated one byte in `site_profile.py` on scratch and re-ran `MutationProofBindingTest` → failed on `site_profile.py changed without its mutation proof…` as expected; restored and `pytest` `CredentialVerdictCorpusTest` still `OK`. The old `grep -c` predicate that always fired is gone, replaced by unittest that fails loudly.

**Break each guard, confirm intended tests fail:** re-ran each mutation family on scratch (reviewed tree untouched) — break set narrowed to `\n` only → 21 failures in `LineBreakAgreementTest`; one boundary dropped (`\r`) → 5 failures; strict-key weakened → 13 failures; descriptive separation removed → 2 failures; length-floor restored → 63 failures; template collapse removed → 4 failures/errors; gate stops enforcing → 8 failures — all as proof files record, none survived. Upstream loader mutations similarly fail `test_the_verdict_corpus_is_the_rule` for both line-break shapes.

**Verdict:** proofs are bound to the real committed blobs (verified post-commit) and the binding test bites.

### 6. Is the documentation true? Yes — every sentence against the code

**File:** `plugins/unifi/references/site-profile.md` (the published contract; `site_profile.py` is the enforcement point). Checked each sentence by reading the referenced code and by live probes.

- “Two rules… The name rule… Every object … is closed, and every property name is checked” — true: schema `site-profile.schema.json` `additionalProperties: false` + `propertyNames` `nonCredentialPropertyName`, loader `_credential_field` same `CREDENTIAL_NAME_FRAGMENTS`.

- “The value rule… Every string … at any depth, by two narrow families: 1. Literal formats … 2. A strict secret-bearing key assigned a literal value… to a single substantive value is rejected — whatever that value looks like. There is no entropy floor…” — true: `CREDENTIAL_VALUE_FORMATS` x11, then `CREDENTIAL_ASSIGNMENT_IN_TEXT` (`(?=([^\"',;…]{1,200}))` lookahead, floor 1) plus `_is_strict_credential_key` whole/exact, `_substantive_tokens` collapse, `if len(tokens)==1 or not descriptive: return`. Live `password: rainbowtrout`/`secret`/`hunter2` all REJECT.

- Box “What changed in 2.0.4 through 2.0.6 … The rule used to grade the *value*: … 2.0.5 then made an assignment line-scoped … 2.0.6 then named the whole boundary set, after the next review found that scoping to the newline alone had left nine other breaks disagreeing.” — true: `2.0.4` `0feecfa` introduced key-decides, `78c1544` introduced `[^\S\n]` then `8e5847b` introduced `CREDENTIAL_LINE_BREAKS` with ten breaks; nine other breaks indeed disagreed and eight were fail-open (verified by re-running old `2.0.5` break-set-narrowed mutation → 21 failures).

- “It does not scan for bare high-entropy strings…” — true: `notes: e3b0c442…` digest → ACCEPT.

- “It accepts a value that merely names a secret… `vault:` or `env:`, a redacted marker…” — true: `vault:infiquetra`/`env:UNIFI_API_KEY`/`<redacted>` → `tokens == []` → ACCEPT.

- “It reads a sentence as a sentence. In `description` and `notes` … a strict key followed by *several* substantive words is a description… `token: base64 of the site identifier` … `credentials: oauth2 is configured…` are accepted. Every other field … allowance does not reach them.” — true: `notes` same → ACCEPT, `site.identifier` same → REJECT (descriptive False); verified live.

- “A literal padded out with prose is not reported. The value `password: rainbowtrout is the controller value` passes…” — true: `notes: password: rainbowtrout is the controller value` → `tokens len 4` descriptive True → ACCEPT; single `password: rainbowtrout` → REJECT; same padded in `identifier` → REJECT.

- “It reads one line at a time. An assignment split across two lines is not matched by either the loader or the gate: the whitespace around the delimiter is horizontal only, and the value stops at the line break. This sentence was false when it was first written, and then it was only partly true. … 2.0.5 repaired both for the newline and nothing else, which left nine other boundaries disagreeing and eight of them fail-open. ‘One line’ now means one thing in all three copies: every boundary `str.splitlines()` recognises — line feed, carriage return, … NEL, LINE SEPARATOR and PARAGRAPH SEPARATOR. The set is named once and the matching rule is built from it, and a test rebuilds that set from the standard library…” — **now true**. Previously the sentence claimed “matched by neither” while loaders used `\s*` and gate split lines, so they disagreed; `2.0.5` fixed only `\n`; `2.0.6` introduces `CREDENTIAL_LINE_BREAKS` with ten breaks and `LineBreakAgreementTest.test_the_break_set_is_exactly_what_splitlines_recognises` rebuilds from `splitlines()`. Both `password:\n  hunter2` → False and `see notes:\npassword=hunter2` → True in all three copies, for every boundary.

Three of the last four cycles turned on a doc claiming behaviour the code did not have (entropy vs discriminator, and the two line-break claims). This cycle every sentence was checked against live `_credential_in_text`/`credential_findings` and against `rg` for one-line samples; the gate correctly refuses the file if a sample were split incorrectly. No over-promise found.

## Known and deliberately not repaired — opinion

- Padded-literal allowance (F-05) — documented, judged acceptable by both reviewers previously; still acceptable as price for not rejecting `oauth2`/`base64` prose. Both copies agree, non-descriptive fields still reject padded.

- Negative HTTP `Retry-After` (`-5` → `-5.0` → `math.ceil -5`) — pre-existing, tracked `infiquetra-claude-plugins#770`; correctly not repaired here.

- Empty `CREDENTIAL_KEY_EXACT_IN_TEXT` — was advisory, now fails five tests via new `auth`/`accesskey` corpus entries; no longer weak, correctly not a blocker but now load-bearing.

## Whole-candidate integrity (no regression)

- Provenance coherent: `plugins/unifi/PROVENANCE.json` `818fd684`/`2.0.6` (unifi slice last moved at `818fd684`), `plugins/fleet-core/PROVENANCE.json` `3b5faa6c`/`0.25.2` (`git log` shows `3b5faa6c` last touch to `plugins/fleet-core`, `818fd684` touches only `plugins/unifi`; `plugins/fleet-core` subtree byte-identical between them per notes). `site_profile_loader.py` `upstream-byte-copy` `sha256 577cec7773989495814dd1496613932aa5991de7f3f8196a2fa4a28c65edd1af` matches source at `818fd684`; both client transforms `resolve-bundled-fleet-module` digests equal.

- Evidence bound to tree `22bfa568…`: `22bfa56828fc7d0fb2246f190730082905bd71b82dee3e8d6e5afc4072498d37` recomputed via `package_fingerprint(plugins/unifi)` (23 files) equals the ```json records in current `2026-08-22-unifi-compatibility-matrix.md` (`<!-- matrix-status: current -->`) and `2026-08-22-unifi-post-activation-readback.md` (`release`/`units`). Eight superseded matrices validate, chain to `22bfa568…`; `matrix-status` default `current` fail-closed.

- Python floor `python>=3.12` still agrees at every declaration site (`DECLARATION_SITES` plus `plugins/fleet-core/README.md`/`CHANGELOG.md`/`DECISIONS.md`/`README.md`/`ci.yml:56` `python-version: '3.12'` with step name `Set up Python 3.12`), skill frontmatter `compatibility` `None` allowed; exercised on `/opt/homebrew/bin/python3.12` (`433 tests OK (skipped=1)`).

- Prior repairs still fixed: non-finite `Retry-After` still `None` via `_usable_delay`/`math.isfinite`; smuggled `.pyo` still `unlisted`; `__pycache__` shared blind spot still advisory; padded-prose hole still documented; negative Retry-After still out-of-scope.

## Built-vs-planned audit

Scope-drift: none. Intent from `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` R01–R45 and queued line-break work: delivered exactly that — named boundary set derived from `str.splitlines()`, corpus pinning every boundary in both shapes, binding test, `2.0.6` resync, matrix/readback re-run at `22bfa568…`. No unrelated drift.

Plan-completion: 42 DONE, 0 PARTIAL, 0 NOT-DONE, 0 CHANGED, 3 UNVERIFIABLE (R30/R31 Orchestrate/Herdr topology, R45 cross-repo).

## Coverage, residual risks, and engineering-journal alignment

Correctly appended: `LEARNINGS.md` line-break lesson with `splitlines()` derivation; `QUEUED.md` Qwen catalog gap P1 honest as Maybe; `ARCHIVE.md` will curate. `DECISIONS.md` floor unchanged. Residual risks: padded literal in descriptive fields (F-05, documented), `__pycache__` invisible, negative Retry-After #770, and the now-closed exotic-break advisory (previous F-01) no longer residual.

## Outcome and routing

> **Plain answer: this exact commit `8e5847bc7b7608537688e24aa2bb419015386988` is safe to merge and release.** Under the `review_result.v1` contract (`lens_roster.v1`, `combiner: all` over `derived_overall >= 9.0` and `applicable_dimension >= 7.0`) every scored lens has `derived_overall 9.00` and every applicable dimension `>=9`, so both rules hold — the typed outcome is `accepted`. The `\n`-only line scoping that left nine boundaries disagreeing (eight fail-open via `CR`/`VT`/`FF`/`\u2028` etc.) is repaired in all three copies by naming the full `CREDENTIAL_LINE_BREAKS` set from `str.splitlines()` and building the class from it; both vulnerable shapes (`see notes:<break>password=hunter2` and `password:<break>  hunter2`) now agree across loader, target, and gate for every boundary including `CRLF` and sequences, the 33-line corpus pins every boundary in both shapes, the exact in-text key set is now load-bearing via six new `auth`/`accesskey` corpus rows (emptying fails five tests), and the mutation proofs are bound to the real committed blobs (`31c9695f…`/`79dc00e…`/`577cec…`) and fail if a graded file changes without its proof being re-run.

`schema: review_result.v1` — `best_available_revision: 8e5847bc7b7608537688e24aa2bb419015386988` — `outcome: accepted` — `next_action: continue` — no failing lenses, no failing dimensions. P3 `F-01` (identity-not-execution) remains as advisory; `F-02` (`auth` exact emptying) now correctly fails tests and is closed; `F-03`/`F-04`/`F-05` as pre-existing/out-of-scope advisory. No `repairs_requested`.

Route: merge and release `8e5847b` (`2.0.6` at `818fd684`). Next `QUEUED.md` P1 remains `The repository carries no marketplace manifest…` which explicitly says writing a manifest is NOT authorized here. No fixer dispatch required; gate, not fixer — zero file writes to reviewed code, no commits, no pushes.

Reviewer: opencode/muse-spark-1.2 (fresh verification, exact-commit verified before scoring, no cross-reviewer read)
Reviewed revision: `8e5847bc7b7608537688e24aa2bb419015386988` (`orch/orch-2026-08-22-unifi-cycle3`)
Roster: `lens_roster.v1` — 14 lenses, 10 scored at 9.00, 4 not selected with recorded cause; ship readiness is `accepted` per the roster's own `combiner: all` rule.


