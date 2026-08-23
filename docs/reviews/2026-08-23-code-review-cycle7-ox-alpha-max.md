# Targeted verification — UniFi portability pilot, cycle 7

Reviewer: ox-alpha (independent reviewer; did not read the panel partner's
artifact). Report built incrementally per brief.

Pre-score verification performed and recorded: `git rev-parse HEAD` printed
0feecfa04966346d45391008b1a7b17422d79f2c (exact match) and
`git status --porcelain` printed nothing. All findings bind to tree 0feecfa.

Delta audited: 9ad24f2..0feecfa, 21 files, +2267/-369 — the field-aware key
rule in three copies plus its tests, upstream unifi 2.0.4 (a46714b8),
sixth matrix run (`81c0503c…`), re-captured readback, cycle-6 panel records,
cycle-7 mutation-proof evidence files, rewritten reference documentation.

Method: roster + findings schema re-read; six prior cycles immutable evidence;
every claim re-derived from current source; upstream clone fetched and the
loader byte copy verified against a46714b8; ~40-shape attack battery across
all three copies plus a simulated 2.0.3 rule for regression comparison;
four loader mutations and three local-copy mutations re-run by me on scratch
copies (each restored byte-identical); full gate battery on both
interpreters. Zero writes to tracked files.

## Gates run on this tree (all executed this session)

- `python3 scripts/bundle_fleet_module.py --check` — PASS.
- `python3 scripts/check_repo.py` — PASS.
- `python3 scripts/check_compatibility_matrix.py` — PASS; `--print-fingerprint`
  = unifi 2.0.4, 23 files, `81c0503cc4b5…10ee4e`, equal to the current matrix
  record and the commit message's claim; six superseded matrices chain to it.
- `/opt/homebrew/bin/python3.12` (3.12.13, the declared floor) — Ran 430
  tests, OK (skipped=1). Default python3 — OK.
- `python3 -c` over plugins/unifi/PROVENANCE.json — pins a46714b8 / 2.0.4.
- `git diff --check` — clean.

## Attack item 1 — is the new rule stronger? YES, with one documented exception

Simulated-2.0.3 vs shipped battery: every 2.0.3 false positive is fixed
(oauth2/base64/sha256/vlan40 prose now passes on all three copies) and every
2.0.3 miss is now caught (`password: rainbowtrout`, `password: sunshine`,
`api_key: correcthorsebattery`, and even `password: secret` fire on all three
copies end-to-end through validate_profile).

Regression hunt (credential the 2.0.3 rule caught that this one misses):
exactly two shapes found — `password: hunter2 keeper` and
`token: <30-char literal> stored safely`. Both are instances of the DOCUMENTED
padded-literal allowance in `description`/`notes` (strict key + several
substantive words). Outside those two prose fields both fire: with
descriptive=False the loader/portable rule rejects any substantive token
count, and the repo gate fires on single-literal lines everywhere. I probed
key-set regressions separately: `pwd`, `pass`, `oauth` are not strict keys —
but the 2.0.3 alternation missed them too, so they are not regressions.
Verdict: no undocumented regression; the only recall loss sits inside the
documented allowance (item 2). Not a release blocker.

## Attack item 2 — is the prose allowance a hole? Acceptable AS DOCUMENTED

The allowance: under a strict key, several substantive tokens read as a
sentence, in `description` and `notes` only (derived from the schema field
tuples, verified: DESCRIPTIVE_FIELDS = {description, notes}). The sharp end
is real — `api_key: <real token> stored in vault` passes in those two fields.

Judgment: acceptable as documented, not a defect dressed up. Grounds:
(a) three consecutive value-grading designs failed empirically in both
directions — key plus token-count is the only remaining mechanical signal
that does not need semantics; (b) the allowance is scoped to exactly the two
fields whose contract purpose is prose; every other field fires on ANY
substantive count; (c) the reference states it verbatim and names it "the
sharpest edge of the rule" rather than burying it; (d) the contract's primary
control ("a profile carries intent, never a secret") is unchanged and the
validation stays defense-in-depth; (e) the superseded limits were strictly
worse — through cycle 5 `password=secret` shipped accepted wholesale, where
now even bare `secret` is refused. Recorded as advisory A-01.

## Attack item 3 — does the strict-key derivation bind? YES

Substring fragments + exact whole-key extras probed: `author`, `authority`,
`authorizer`, `oauth` are NOT strict (the exact-list design keeps `auth` from
swallowing them — the brief's specific worry). `secret_key`, `client_secret`,
`access-key`, `API-Key`, `apitoken` ARE strict. `tokenize`/`credentialing`
are strict via substring — defensible morphemes, and they only fire on a
single-substantive-literal value. Misses found (`pwd`, `pass`, bare `key`)
are misses the 2.0.3 alternation shared — pre-existing, not regressions.
One taxonomy, two readers: `_credential_field` grades property names with the
same fragment list, so no second dialect inside one copy.

## Attack item 4 — do the three copies agree? YES on every ordinary line; TWO split-line shapes diverge

Battery result: on all single-line shapes the portable loader, the repo gate,
and the byte-copied Claude loader return identical verdicts (the end-to-end
drift test pins 14 such lines). The lookahead nesting fix works:
`"notes": "controller password=hunter2"` now fires naming `password` in all
three copies.

Two multi-line shapes break agreement, both found this session:

1. `password:\n  hunter2` — the portable copy and the Claude loader FIRE
   (the `\s*` after the delimiter crosses the newline and the lookahead
   captures the next line), while the repo gate passes it (per-line scan).
   The reference doc claims the opposite: "An assignment split across two
   lines is not matched by either the loader or the gate" — FALSE for two of
   the three copies. See F-01.
2. `see notes:\npassword=hunter2` — the gate FIRES and both loaders PASS.
   The greedy `\s*` after an innocent key's colon consumes the newline, so
   the resumed scan lands directly on `p` with no boundary character left to
   start a new match. This is the exact swallow the commit message claims
   fixed ("matched notes and resumed past the password") — fixed for
   same-line values by the lookahead, still open across a newline. See F-02.

## Attack item 5 — mutation evidence: verified, with one identification defect

The committed proof's pristine digest for the loader (`9e03ce93…`) matches NO
committed state of that file in either repository — actual final bytes are
`80f2bc5d…`, byte-identical to upstream a46714b8. The proof's conclusions
still hold: I re-ran all four mutations against the FINAL bytes myself.

Loader (upstream suite, 131 passed pristine; each mutation restored
byte-identical to 80f2bc5d):
- M1 function stops consulting CREDENTIAL_KEY_EXACT_IN_TEXT — FAILED
  test_the_strict_key_set_is_the_property_name_taxonomy.
  (Note: EMPTYING the tuple instead is vacuous — the test's loop becomes a
  no-op. Function-side mutation is caught; tuple-side is not. Minor gap.)
- M2 `descriptive=field in DESCRIPTIVE_FIELDS` → `descriptive=True` — FAILED
  test_the_prose_allowance_does_not_reach_a_structured_field.
- M3 length floor restored (tokens filtered to >=6) — FAILED
  test_technical_prose_in_a_descriptive_field_is_accepted[password: md5 …].
- M4 template collapse removed — FAILED
  test_a_value_that_names_where_a_secret_lives_is_accepted[api_key: {{ lookup }}].

Local copies against the FULL suite (430 tests):
- N1 strict-key exact set disabled in site_profile.py — 11 failures.
- N2 gate stops enforcing strict keys (check_repo.py) — 8 failures,
  including live-repository validation and four SecretFreeValueTests.
- N3 prose allowance removed (`if tokens:`) — 12 failures + 16 errors.

Every mutation bites its intended class. The coverage is real, not
test-shaped — with the one caveat that the committed evidence record
misidentifies the loader bytes it proved (F-03), which I repaired by
re-running everything myself rather than trusting it.

## Attack item 6 — is the documentation true? Substantially yes; ONE sentence is false

Verified true against code: family 2's strict-key list and single-substantive-
literal rule ("no entropy floor, no digit test, no length bar");
`password: rainbowtrout` AND `password: secret` refused end-to-end; the
2.0.4 history blockquote's entropy numbers (oauth2 2.585 fired, rainbowtrout
3.085 passed); the prose-fields-only allowance; "reads a sentence as a
sentence"; the padded-literal limit stated verbatim; the manifest description
correction. FALSE: the line-split sentence quoted under F-01 — the loaders DO
match a strict assignment split across lines when nothing precedes the key.

## Findings (admitted, confidence >=75; sorted P0→P3 then confidence→file→line)

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | plugins/unifi/references/site-profile.md:101 | "An assignment split across two lines is not matched by either the loader or the gate" is false for both loaders — they fire on `password:\n  hunter2`; gate alone passes it | documentation-clarity, api-contract, correctness | 100 | safe_auto -> review-fixer |
| F-02 | plugins/unifi/scripts/site_profile.py:186 | Greedy `\s*` after an innocent key's colon swallows the newline: `see notes:\npassword=hunter2` passes in both loaders while the gate fires — residual of the nesting bug this commit claims fixed | correctness, security | 100 | gated_auto -> review-fixer (upstream-first for the loader copy) |
| F-03 | docs/evidence/2026-08-22-cycle7-mutation-proof-upstream-loader.txt:2 | Records pristine loader digest `9e03ce93…`, which matches no committed state in either repository; final bytes are `80f2bc5d…`. Conclusions verified valid by independent re-run; the identification record is wrong | documentation-clarity, adversarial | 100 | safe_auto -> review-fixer |

### Advisory

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| A-01 | plugins/unifi/scripts/site_profile.py:523 | Padded-literal allowance: a real secret plus prose words evades detection under a strict key in description/notes — judged acceptable AS DOCUMENTED (regression vs 2.0.3 confined to it; disclosed verbatim; two fields only) | security | 100 | advisory -> human |
| A-02 | tests/test_site_profile.py:407-class analog upstream | Emptying CREDENTIAL_KEY_EXACT_IN_TEXT is vacuous (test loop no-op); only function-side mutation is caught | testing | 100 | advisory -> human |
| A-03 | scripts/check_repo.py:837 | Gate/loader split-line divergence generalizes cycle-6's carried line-based-scan advisory; now with concrete shapes (see item 4) | architecture-maintainability | 100 | advisory -> human |

Suppressed findings: 0. Negative Retry-After excluded per brief (#770).

### Detailed findings (per findings-schema.md)

#### F-01 — reference doc's line-split claim is false for both loaders (P3)

- severity P3; dimension_id documentation-clarity:shipped-behavior-parity
  (also api-contract:specification-documentation-parity,
  correctness:boundary-types-serialization-numeric-time); critical false.
- file plugins/unifi/references/site-profile.md (the "It reads one line at a
  time" bullet); behavior at site_profile.py:186-188 and loader copy :168-170.
- why_it_matters: The doc asserts a limitation that does not exist in two of
  the three copies. An operator who trusts it writes a multi-line notes value
  (`password:\n    <literal>` YAML-style) expecting acceptance and their
  profile is refused; the same text passes the repo gate, so the two halves
  of one package disagree on it. Cycle 6's blocker was a doc promising
  detection the code did not do; this is the mirror image — promising
  non-detection the code does.
- evidence: live probes — `password =\n  hunter2` sp=True cr=False ld=True;
  `password:\n  hunter2` identical. Root cause: `\s*` after `[\"']?` before
  the lookahead crosses `\n` (pattern :186-187).
- pre_existing false (sentence introduced by 0feecfa). requires_verification
  true. suggested_fix: correct the sentence to "the repository gate reads one
  line at a time; the loaders match across a line break when the delimiter
  ends the line" — or make the pattern refuse to cross newlines with
  `[^\S\n]*` and keep the claim true for all three copies. Assumption: the
  gate cannot cross lines without a redesign, so aligning the doc to
  per-copy truth is the smaller fix.

#### F-02 — innocent key swallows an adjacent strict assignment across a newline (P3)

- severity P3; dimension_id correctness:caller-enum-consumer-completeness
  (also security:input-trust-boundaries-injection); critical false.
- file plugins/unifi/scripts/site_profile.py:186-188 (pattern), :516-524
  (scan loop); loader copy identical.
- why_it_matters: The commit names this bug class as fixed by the lookahead;
  the fix covers same-line values only. When an innocent assignment's colon
  is directly followed by a newline (`see notes:\npassword=hunter2`), match
  one consumes that newline inside greedy `\s*`, scanning resumes ON `p`,
  the `(?:^|[^A-Za-z0-9_-])` boundary has nothing left to consume, and the
  strict assignment is never matched — while the line-based gate fires. A
  fail-open divergence between enforcement copies on one input.
- evidence: probe row in item 4; mechanism traced through finditer resume
  semantics; single-line control `"notes": "controller password=hunter2"`
  fires correctly in all three copies.
- pre_existing false (generic-key + lookahead scan introduced here).
  requires_verification true.
- suggested_fix: restrict post-delimiter whitespace to same-line:
  `[^\S\n]*` in place of the second `\s*` (both target-owned copies plus
  upstream loader via re-sync), then pin with the two-line corpus from item 4.

#### F-03 — committed mutation-proof misidentifies the bytes it proved (P3)

- severity P3; dimension_id documentation-clarity:runbook-safety-rollback-
  links-generated-drift (also adversarial:failure-amplification-silent-green);
  critical false.
- file docs/evidence/2026-08-22-cycle7-mutation-proof-upstream-loader.txt:2
  ("pristine sha256: 9e03ce93…"); also the RESTORED block at :30.
- why_it_matters: The record claims to prove mutations against loader bytes
  `9e03ce93…`; that digest corresponds to no commit of that file in this
  repository or upstream (history: f074306b, 42815630, d213f59b, 80f2bc5d).
  An evidence record that names bytes the tree does not contain is exactly
  the "record vs tree" failure class this repository's binding gates exist
  for — here it sits in a file no gate parses. I re-ran all four mutations
  against the actual final bytes and each fails as claimed, so the CONCLUSION
  stands; the IDENTIFICATION is wrong.
- evidence: digest sweep over both repos' loader history (this session);
  my four reproduction runs, each restoring byte-identical 80f2bc5d.
- pre_existing false. requires_verification false.
- suggested_fix: re-run the proof script against final a46714b8 bytes and
  commit the refreshed record; add the pristine-digest check to whatever
  harness produced it so a stale run cannot be committed silently.

## Lens selection (roster `lens_roster.v1`, bound to 0feecfa)

Always-on run: architecture-maintainability, correctness, security, testing.
Conditional lenses SELECTED, one-line cause each:

- reliability — retry lineage carried; negative Retry-After excluded per
  brief (#770); remaining failure surface re-checked for regression.
- api-contract — manifest version moved to 2.0.4; reference doc is the
  contract text under test; spec/doc parity directly attacked (item 6).
- adversarial — every guarantee attack-probed; rule deliberately attacked in
  both directions plus its evidence records.
- deployment-infrastructure — sixth matrix run bound to `81c0503c…`; readback
  re-captured with the technical-prose fixture proving the repair from
  installed bytes.
- documentation-clarity — reference rewritten and every sentence checked
  against code (item 6); two evidence files added and verified.
- agent-usability — machine-readable verdicts changed on both directions;
  loader acceptance surface changed for operators authoring profiles.
- previous-comments — cycle-6 split panel's findings all dispositioned;
  resolution completeness audited.

Conditional lenses NOT selected (recorded cause): performance — no latency,
throughput, query, or cost surface touched; privacy — no personal-data flow
changed, evidence identity-sweep unchanged from prior cycles;
accessibility-human-usability — no human-operated visual surface changed.

## Lens scores — the gate (acceptance: derived_overall >= 9.0 AND every applicable dimension >= 7.0)

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| architecture-maintainability | fit/ownership 9; separation 10; dependency-direction 10; simplicity 9; readability 9; conventions/portability 10; decision-docs 9 | none | **9.43** |
| deployment-infrastructure | infra-config/least-privilege 9; migrations/rollout-order 9; rollback/drift 9; deployed-state-verification 10 | cost-resilience — no resource or cost surface in this delta | **9.25** |
| correctness | intent-behavior 8; state/invariants 9; boundary-types 8; side-effects/lifecycle 9; caller-consumer-completeness 8 | none | **8.40** |
| security | input-boundaries 9; secrets 9; supply-chain 10; confidentiality 9 | authentication-authorization-tenant-isolation — no protected-operation surface touched by this delta | **9.00** |
| testing | requirements/regression 9; negative-edge/time 9; behavior-sensitive assertions 10; realistic-seams 9; determinism/isolation 9 | none | **9.20** |
| reliability | timeouts/retries/idempotency 9; concurrency/partial-failure 9; graceful-degradation/cancellation 9; health-signals 9 | queues-jobs-dead-letters-ordering-backpressure — no queue, job, ordering, or backpressure surface | **9.00** |
| api-contract | interface-compatibility 9; versioning 9; serialization/errors 9; retry-idempotency-semantics 9; pagination/rate-limits 9; spec/doc-parity 7 | sdk-generated-client-impact — no generated SDK surface | **8.67** |
| adversarial | load-bearing-assumptions 9; abuse-edge-cases 8; failure-amplification/silent-green 8; environment/operator-failure 9; scope-creep-risk 10; alternatives-considered 9; recovery 9 | none | **9.00** |
| documentation-clarity | shipped-behavior-parity 7; completeness/audience 9; structure/navigation 9; terminology 9; runnable-examples 9; runbook-safety/drift 8 | none | **8.50** |
| agent-usability | reachability 9; discoverability 9; context/constraints 9; machine-readable-output 9; bounded-operation 9 | none | **9.00** |
| previous-comments | resolution-completeness 9 | none | **9.00** |
| performance | NOT SCORED — not selected | — | — |
| privacy | NOT SCORED — not selected | — | — |
| accessibility-human-usability | NOT SCORED — not selected | — | — |

## Coverage

Suppressed findings: 0 (nothing admitted below anchor 75). Residual risks:
the padded-literal allowance (A-01 — accepted as documented, confined to
description/notes); split-line divergence between the line-based gate and
the cross-line loaders (A-03, with concrete shapes from item 4); the loader
rule remains custody-pinned to upstream bytes rather than drift-pinned to
the local pair (carried); negative Retry-After deferred upstream (#770, per
brief). Testing gaps: emptying CREDENTIAL_KEY_EXACT_IN_TEXT is a vacuous
mutation (A-02); no test pins the two split-line shapes that diverge
(F-01/F-02 would both be caught by adding them to the drift corpus).

schema: review_result.v1; best_available_revision: 0feecfa04966346d45391008b1a7b17422d79f2c;
outcome: `repairs_requested`; next_action: return_to_work.

## Outcome and routing

> **Plain answer: not yet safe to merge and release under the contract's own
> numbers — three of eleven scored lenses sit below the 9.0 overall minimum,
> driven by one false sentence in the reference documentation and one
> fail-open newline edge in the new scan.** The rule itself is the strongest
> of the four designs this pilot has shipped: both cycle-6 defect classes are
> closed, custody and evidence re-capture are clean, and every guard bites.

Fix order: 1. F-01 — correct or make true the line-split sentence (safe_auto,
minutes). 2. F-02 — same-line-only whitespace after the delimiter, coordinated
upstream so the loader copy follows, plus the two-line corpus pinned in the
drift test (gated_auto). 3. F-03 — refresh the mutation-proof record against
final bytes (safe_auto). With those landed, every failing score's driver is
gone and `accepted` is the honest verdict.

Route: F-01 safe_auto -> review-fixer; F-02 gated_auto -> review-fixer
(upstream-first); F-03 safe_auto -> review-fixer; A-01/A-02/A-03 advisory ->
human. No saga write performed: this session ran as an independent
programmatic reviewer against a scratch artifact path; no work-thread saga
was scanned or minted.

Raw evidence run this session: all gates green on both interpreters;
~40-shape battery across three copies plus simulated 2.0.3; seven mutations
re-run by me (four loader on final upstream bytes, three local on the full
430-test suite), each restored byte-identical; digest sweep over both
repositories' loader history; end-to-end validate_profile probes both
directions.

Review complete. Reviewer: ox-alpha. Reviewed revision: 0feecfa
(orch/orch-2026-08-22-unifi-cycle3). Outcome: repairs_requested.
Next action: return_to_work.
