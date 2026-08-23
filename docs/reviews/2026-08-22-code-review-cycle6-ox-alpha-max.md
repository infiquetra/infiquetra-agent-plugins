# Scored code review — UniFi portability pilot, cycle 6 (final focused panel)

Reviewer: ox-alpha (independent reviewer; reviewed cycle 5 and returned
`repairs_requested`). Artifact built incrementally per brief.

Target: /Users/jefcox/workspace/infiquetra/infiquetra-agent-plugins,
branch orch/orch-2026-08-22-unifi-cycle3.
Pre-score verification: `git rev-parse HEAD` =
9ad24f29fe3c7290123b0434ce1e3c37330343f6 (exact match), `git status
--porcelain` empty. All findings bind to tree 9ad24f2.

Delta audited: 08ab2de..9ad24f2, 17 files, +1949/-149: the walk-and-stop
credential rule in three copies plus its tests, resync to UniFi 2.0.3
(769d06f1), fifth matrix re-run (tree `34915c40…`), fifth readback capture,
cycle-5 panel records, two QUEUED corrections.

Method: roster (`lens_roster.v1`) + findings schema re-read; all six prior
cycles' records treated as immutable evidence; every repair re-derived from
current source; upstream clone fetched and verified at 769d06f1 / 3b5faa6c;
live probes against all three copies of the credential rule (portable,
repo gate, byte-copied loader) including a simulated defective rule for
new/old classification; three targeted mutations on a scratch copy to prove
the new tests bite; full gate battery both interpreters. Zero writes to
tracked files.

## Gates run on this tree (all executed this session)

- `python3 scripts/bundle_fleet_module.py --check` — PASS.
- `python3 scripts/check_repo.py` — PASS.
- `python3 scripts/check_compatibility_matrix.py` — PASS: five superseded
  matrices + current; current record 38 executed / 2 blocked / 9
  works-directly / 0 failed.
- `--print-fingerprint` — unifi 2.0.3, 23 files,
  `34915c40a34a4fffe9276fed141bd0ce3a089b26935864b16d4a548a76d9d0dc`, equal
  to the matrix record, the readback record, and the brief's claim.
- `/opt/homebrew/bin/python3.12` (3.12.13, the REAL floor) — Ran 421 tests,
  OK (skipped=1). Default python3 — OK.
- `git diff --check` — clean.

## Brief item 1 — placeholder bypass: FIXED and probed

`authorization: Bearer <redacted> <token>` now fires in all three copies
(walk steps over `<redacted>` via the startswith(`<`) branch of
_names_a_secret, grades the token). Also verified firing: `Basic <redacted>
<b64>`, `Bearer ${VAR} <token>` (capture class widened to exclude only quote/
comma/semicolon, so `}` no longer truncates), `<redacted> Bearer <token>`
(placeholder before scheme), `redacted` as a bare word (placeholder regex),
and a double-placeholder walk (`<redacted> ${VAR} <token>`).

**Shapes that still slip (credential present, all three copies pass):**
a substantive non-scheme word first (`authorization: stored in vault <token>`
— inherent to stop-at-first design), semicolon or comma inside the value
(`password: Bearer <redacted>; real=<token>` — capture boundary, pre-existing
class), parenthetical placement. All require word orders an operator paste is
unlikely to produce; narrower than any previously reported slip.

## Brief item 2 — prose false positives: FIXED

All six cycle-5 FP shapes now pass on all three copies: "token: rotation
happens quarterly", "secret: managed elsewhere", "bearer securities",
"basic training", "digest authentication…", "negotiate with the vendor".
The cycle-5 P2 is genuinely closed.

**New narrow FP class found (first substantive token carrying a digit):**
"credentials: oauth2 is configured at the controller", "client_secret: base64
blob lives in vault", "auth: sha256 pinned in the release baseline",
"credentials: ABC-1234 tracks the rotation", "credentials: vlan40 trunk…" —
all FIRE on all three copies. Requires a digit-bearing technical word in
FIRST substantive position after a credential-named key; entropy ≥ 2.5 and
length ≥ 6 also required. Much narrower than the repaired defect but real and
reachable in ordinary operational notes ("oauth2" is routine UniFi prose).
See F-01.

## Brief item 3 — the discriminator: attacked both halves, one hit each

**Real credential with no digit under 24 characters: passes.** `password:
rainbowtrout` (12 chars, entropy 3.54) and `password: correcthorsebattery`
(19 chars) are ACCEPTED — both would have FIRED under the cycle-5
entropy-only rule. This is a recall regression for the digit-free 6–23 char
secret class. It is a knowingly taken trade-off: the commit message scopes
the claim honestly ("every sample this rule is tested against"), and the ≥24
branch does catch long digit-free passphrases (`correcthorsebatterystaple`
fires). But the operator-facing reference doc has NOT been updated to admit
this limit — see F-02.

**English word carrying a digit that gets graded: confirmed.** `oauth2`,
`base64`, `sha256`, `ABC-1234`, `vlan40` all qualify when first substantive
(≥6 chars, ≥2.5 bits, contains a digit). "No English word carries a digit"
is true of prose samples, false of technical vocabulary — the exact class an
Infiquetra operator writes in notes.

## Brief item 4 — walk-and-stop design: both halves attacked

Walk half: scheme words and placeholders are correctly stepped over in any
order and case (`<redacted> Bearer <token>`, `Bearer vault:prod <token>` —
reference-prefix tokens mid-walk also skip); double scheme words skip; a
value that is ALL placeholders correctly passes. Stop half: "see ticket
ABC-1234 for rotation" passes because the walk stops at "see" (short → not
shaped → no finding, scan never continues). The stop is what bounds the FP
surface to first-position only; a full-scan variant was mutation-tested and
fails its negative test (below).

## Brief item 5 — regression coverage: REAL, not test-shaped. Mutation-proven.

Three targeted mutations applied to a scratch copy (git archive of HEAD;
reviewed tree untouched), suite run from the scratch root:

1. **Two-token window reintroduced** (the defective cycle-5 rule) —
   FAILED, 15 failures: the new must-fire cases (`Bearer <redacted> <token>`,
   `Bearer ${UNIFI_API_KEY} <token>`, `Bearer vault:… <token>`) bite because
   their first two tokens are scheme word + placeholder, exactly the shape
   the window cleared.
2. **Digit discriminator removed** (entropy-only) — FAILED, 9 failures:
   the must-not-fire prose now uses first tokens long enough to reach the
   grader ("rotation procedure documented…" — 2.50 bits at exactly the floor,
   "internationalization"), so an entropy-only rule rejects them and the
   assertions fail. The cycle-4 blind-test defect ("see the runbook", first
   token three characters) is genuinely repaired.
3. **Stop replaced by scan** — FAILED, 5 failures: "auth: see ticket
   ABC-1234 for rotation" fails against a keep-looking rule. The stop
   behavior is pinned, not incidental.

Cross-copy behavior pins: `_credential_candidate` agreement over spans that
include placeholder walks; `_is_credential_shaped` agreement over a token set
that separates every discriminator branch (hunter2 / rotation /
internationalization / 26-letter alphabet); `LONG_ENOUGH_WITHOUT_A_DIGIT`
pinned as a constant. Gap: no test pins the oauth2-class FP either way —
adding it today would fail, which is why F-01 is filed rather than suppressed.

## Brief item 6 — cross-copy agreement

Live probe across all three copies on ~40 shapes (items 1–4 batteries):
site_profile, check_repo, and the byte-copied loader agree on EVERY shape
except multi-line assignments, where the repo gate's line-by-line scan is
the outlier (carried advisory C5-6/A-01 — loaders reject, gate misses; safe
direction for profiles). The drift pin would catch site_profile ↔ check_repo
divergence at behavior level (item 5). The loader remains custody-pinned to
upstream bytes only (sha256 d213f59b… equal both sides at 769d06f1) — carried
advisory C5-7/A-02, unchanged.

## Secondary — whole-candidate integrity: NO REGRESSION FOUND

- Provenance: fleet-core PROVENANCE pins 3b5faa6c / 0.25.2 (unchanged);
  unifi PROVENANCE pins 769d06f1 / 2.0.3. `git diff 3b5faa6c 769d06f1 --
  plugins/fleet-core` on the fetched clone is EMPTY — the two pins name one
  upstream state, so both bundle stamps correctly still read 3b5faa6c /
  source-sha256 == output-sha256 == 2aa7fd26… (verified in the stamp block
  and by bundle --check).
- Loader byte copy faithful at 769d06f1 (d213f59b… equal). Client transform
  sources unchanged upstream between c835f91d and 769d06f1
  (9dcd6360… / 1ec114b4…), outputs unchanged — consistent with a release
  that touched only the loader, changelog, and manifest version.
- Evidence documents bound to tree `34915c40…`: matrix validator PASS;
  readback re-captured as the fifth capture at the same digest, bound by
  tests (suite green); unit digests re-verified last cycle unchanged; Muse
  bundle digest 9e1f2f17/11069 bytes still matches both `_bundled` copies.
  The new scope statement ("Its scope is the package, not this repository…
  registering this repository as a client marketplace or catalog" not
  assessed) is present and accurate.
- Python floor: full suite green ON /opt/homebrew/bin/python3.12 (421 tests),
  not just the default interpreter.
- Cycle-5 dispositions all landed: C5-1/C5-2 repaired here (items 1–2),
  C5-3 deferred + tracked as #770 (out of scope per brief — not re-raised),
  C5-4/C5-5 QUEUED corrections verified in the tree (per-client entry now
  reads "recorded as failed in a superseded publication … now recorded as
  works directly"; ported-test entry marked Resolved), C5-6..C5-10 advisories
  recorded.

## Findings (admitted, confidence >=75; sorted P0→P3 then confidence→file→line)

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | plugins/unifi/scripts/site_profile.py:466 | Digit discriminator fires on technical words with digits (oauth2/base64/sha256) in first substantive position — new narrow prose FP class in all three copies | security, correctness | 100 | gated_auto -> review-fixer (upstream-first for the loader copy) |
| F-02 | plugins/unifi/references/site-profile.md:48 | Value-rule description predates the walk-and-stop redesign: states a rule the code no longer implements and omits the digit/24-character limit | documentation-clarity, api-contract | 100 | safe_auto -> review-fixer |

### Advisory

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| A-01 | plugins/unifi/scripts/site_profile.py:477 | Digit-free secrets of 6–23 characters pass regardless of entropy (rainbowtrout-class recall regression vs cycle-5 rule) — mechanism disclosed in changelog, limit absent from the operator contract; fold disclosure into F-02 | security | 100 | advisory -> human |
| A-02 | scripts/check_repo.py | Line-based gate misses multi-line assignment shapes both loaders reject (carried C5-6, unchanged) | architecture-maintainability | 100 | advisory -> human |
| A-03 | plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py | Loader rule custody-pinned to upstream bytes, not drift-pinned to the local pair (carried C5-7, unchanged) | architecture-maintainability | 100 | advisory -> human |

Suppressed findings: 0.

### Detailed findings (per findings-schema.md)

#### F-01 — digit discriminator grades technical words in first position (P3, introduced here)

- severity P3; dimension_id secrets-cryptography-session-handling (also
  correctness:intent-behavior-completeness); critical false.
- file plugins/unifi/scripts/site_profile.py:466-474 (_is_credential_shaped);
  identical logic check_repo.py and loader copy :415-431.
- why_it_matters: The repair replaces an entropy test that rejected ordinary
  prose with a digit test that rejects ordinary TECHNICAL prose. A UniFi
  operator note "credentials: oauth2 is configured at the controller" is
  refused as a credential-shaped value in the portable loader (operator
  blocked, confusing message) and fires in the repo gate (CI breakage on a
  tracked sentence). The class is narrower than C5-2 — the digit word must be
  the FIRST substantive token after scheme/placeholder skipping — but it is
  reachable in routine vocabulary: oauth2, base64, sha256, ABC-1234, vlan40
  all probed firing on all three copies.
- evidence: probe battery this session (five FP shapes, all copies);
  `oauth2` = 6 chars, entropy 2.585 ≥ 2.5, contains digit → shaped. No test
  pins this class either way (adding "credentials: oauth2 …" to the
  must-not-fire set today would fail).
- pre_existing false. requires_verification true.
- suggested_fix: extend the must-not-fire set with first-position technical
  digit words and add a secondary guard for the no-digit… rather: require the
  digit-bearing candidate to ALSO fail a common-technical-word check (small
  blocklist: oauth2, base64, sha256, md5-class) OR raise the entropy floor
  for short digit-bearing tokens to ~3.0 (oauth2/base64/sha256 all sit at
  2.585; real short secrets rarely sit below 3.0 with digits present).
  Assumption: blocklist is overfit-prone; the entropy bump is the more
  durable default.

#### F-02 — reference doc describes the retired rule (P3)

- severity P3; dimension_id documentation-clarity:shipped-behavior-parity
  (also api-contract:specification-documentation-parity); critical false.
- file plugins/unifi/references/site-profile.md:48-51 (family 2) and :56-74
  ("deliberately does not do").
- why_it_matters: Family 2 still promises "a value of at least six characters
  that clears 2.5 bits of entropy per character is rejected" — the code now
  requires a digit OR 24 characters, so the doc claims detection the code
  does not do (`password: sunshine` meets both stated conditions and ships
  accepted) and omits the actual rule, its walk, and its placeholder
  handling. The doc's own standard at :58 is "Stating this precisely matters
  more than stating it generously." An operator auditing the guarantee reads
  a stronger contract than ships.
- evidence: doc text vs site_profile.py:466-474; live probe sunshine/rainbowtrout
  accepted; CHANGELOG.md documents the new mechanism correctly (the fix text
  exists — it just never reached the reference).
- pre_existing false (made stale by 9ad24f2). safe_auto -> review-fixer;
  requires_verification false.
- suggested_fix: rewrite family 2 and add two bullets to the does-not-do list:
  (1) digit-free values under 24 characters pass whatever their entropy;
  (2) the rule grades only the first substantive token after scheme words and
  placeholders. Mirror the CHANGELOG wording.

## Lens selection (roster `lens_roster.v1`, bound to 9ad24f2)

Always-on run: architecture-maintainability, correctness, security, testing.
Conditional lenses SELECTED, one-line cause each:

- reliability — retry semantics carried from the resync lineage; negative
  delta-seconds excluded per brief as deferred (#770), remaining surface
  re-checked for regression.
- api-contract — schema/loader contract unchanged but reference-doc parity
  and release versioning are load-bearing here.
- adversarial — every new guarantee attack-probed per the panel's standing
  method; discriminator and walk attacked directly.
- deployment-infrastructure — fifth matrix run and fifth readback bound to
  tree `34915c40…`; deployed-state verification claims checkable.
- documentation-clarity — reference doc, changelog, QUEUED corrections and
  two evidence documents materially changed; parity checkable.
- agent-usability — machine-readable surfaces (loader acceptance, gate
  output) changed behavior in both directions.
- previous-comments — six prior cycles' findings apply; resolution
  completeness audited against the cycle-5 consensus disposition table.

Conditional lenses NOT selected (recorded cause): performance — no latency,
throughput, query, or cost surface; privacy — no personal-data flow changed,
evidence identity-sweep clean; accessibility-human-usability — no
human-operated visual surface changed.

## Lens scores — the gate (acceptance: derived_overall >= 9.0 AND every applicable dimension >= 7.0)

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| architecture-maintainability | fit/ownership 9; separation 10; dependency-direction 10; simplicity 9; readability 9; conventions/portability 10; decision-docs 8 | none | **9.29** |
| deployment-infrastructure | infra-config/least-privilege 9; migrations/rollout-order 9; rollback/drift 9; deployed-state-verification 10 | cost-resilience — no resource or cost surface in this delta | **9.25** |
| correctness | intent-behavior 8; state/invariants 9; boundary-types 9; side-effects/lifecycle 9; caller-consumer-completeness 9 | none | **8.80** |
| security | input-boundaries 9; secrets 8; supply-chain 10; confidentiality 9 | authentication-authorization-tenant-isolation — no protected-operation surface touched by this delta | **9.00** |
| testing | requirements/regression 9; negative-edge/time 9; behavior-sensitive assertions 10; realistic-seams 9; determinism/isolation 9 | none | **9.20** |
| reliability | timeouts/retries/idempotency 9; concurrency/partial-failure 9; graceful-degradation/cancellation 9; health-signals 9 | queues-jobs-dead-letters-ordering-backpressure — no queue, job, ordering, or backpressure surface | **9.00** |
| api-contract | interface-compatibility 9; versioning 9; serialization/errors 9; retry-idempotency-semantics 9; pagination/rate-limits 9; spec/doc-parity 7 | sdk-generated-client-impact — no generated SDK surface | **8.67** |
| adversarial | load-bearing-assumptions 8; abuse-edge-cases 9; failure-amplification/silent-green 9; environment/operator-failure 9; scope-creep-risk 10; alternatives-considered 9; recovery 9 | none | **9.00** |
| documentation-clarity | shipped-behavior-parity 7; completeness/audience 9; structure/navigation 9; terminology 9; runnable-examples 9; runbook-safety/drift 8 | none | **8.50** |
| agent-usability | reachability 9; discoverability 9; context/constraints 9; machine-readable-output 9; bounded-operation 9 | none | **9.00** |
| previous-comments | resolution-completeness 9 | none | **9.00** |
| performance | NOT SCORED — not selected | — | — |
| privacy | NOT SCORED — not selected | — | — |
| accessibility-human-usability | NOT SCORED — not selected | — | — |

Gate arithmetic: THREE of eleven scored lenses fail `derived_overall >= 9.0`
(correctness 8.80, api-contract 8.67, documentation-clarity 8.50). NO
applicable dimension fails the floor — the minimum is
api-contract/spec-doc-parity and documentation-clarity/shipped-behavior-parity
at exactly 7.0, which meets `>= 7.0`. Under `combiner: all` both rules must
hold; the first fails. The typed outcome is `repairs_requested`.

## Built-vs-planned (compact) and scope check

Scope Check: CLEAN. Intent: repair both cycle-5 credential defects at the
custody boundary that owns each (2.0.3 upstream for the loader; two target-
owned copies locally), re-run all bound evidence against the exact release
candidate, correct the two stale QUEUED records. Delivered: exactly that,
plus the honestly-scoped matrix statement and the queued marketplace-manifest
gap. COMPLETION: C5-1 DONE, C5-2 DONE, C5-3 deferred-and-recorded (#770),
C5-4/C5-5 DONE (verified in tree), C5-6..C5-10 advisories recorded and
unchanged. Coverage: every changed file maps to that intent.

Residual risks: matrix binding remains identity-not-execution (O7 Maybe);
committed `__pycache__` blind spot unchanged; Cursor row still measures an
authenticated basis vs nine first-run rows — disclosed in the document;
multi-line gate/loader divergence errs safe; loader rule custody-pinned to
upstream only. Testing gaps: oauth2-class FP unpinned by tests; the reference
doc's contract text untested against implementation behavior.

## Outcome and routing

> **Plain answer: the code repairs are done and verified — but under the
> contract's own numbers this exact commit is not yet safe to merge and
> release: three of eleven scored lenses sit below the 9.0 overall minimum,
> driven by one reachable prose false-positive class in the new rule and an
> operator-facing reference document that still describes the retired rule.**

schema: review_result.v1; best_available_revision: 9ad24f2; outcome:
`repairs_requested`; next_action: return_to_work.

This is a small, bounded remainder — no custody, provenance, floor, or
evidence defect exists on this tree, and no dimension falls below the floor.
Both failing drivers close with two edits: F-02 rewrites one reference-doc
section (safe_auto), F-01 narrows the short-digit-token discriminator
(gated_auto, upstream-first for the loader copy) and pins the class with the
must-not-fire test it currently lacks.

Fix order: 1. F-02 reference-doc rewrite (minutes). 2. F-01 discriminator
narrowing + pinning tests, coordinated upstream so the loader copy follows.
3. Optional: A-01 disclosure rides F-02's rewrite. Then resubmit; with those
landed every failing score's driver is gone and `accepted` is the honest
verdict.

Route: F-01 gated_auto -> review-fixer (upstream-first); F-02 safe_auto ->
review-fixer; A-01/A-02/A-03 advisory -> human. No saga write performed:
this session ran as an independent programmatic reviewer against a scratch
artifact path; no work-thread saga was scanned or minted.

Raw evidence run this session: all gates green both interpreters; ~40-shape
probe battery across all three rule copies; five-shape FP confirmation;
three-recall-shape confirmation; three mutations each producing attributable
failures; upstream digests verified at 769d06f1 including fleet-subtree
identity between pins.

Review complete. Reviewer: ox-alpha. Reviewed revision: 9ad24f2
(orch/orch-2026-08-22-unifi-cycle3). Outcome: repairs_requested.
