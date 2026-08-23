# Final verification — UniFi portability pilot, cycle 8

Reviewer: ox-alpha (independent reviewer; did not read the panel partner's
artifact). Report built incrementally per brief.

Pre-score verification performed and recorded: `git rev-parse HEAD` printed
78c15449fd551fb27621855201fc07edae49d3ac (exact match) and
`git status --porcelain` printed nothing. All findings bind to tree 78c1544.

Delta audited: 0feecfa..78c1544, 21 files, +1869/-109 — the one-line
assignment scoping in three copies, unifi 2.0.5 resync (upstream 46825c8d),
corrected reference sentence, MutationProofBindingTest plus refreshed
cycle-8 mutation proofs bound to real digests, sixth-superseded matrix run
(`a8fd46a7…`), re-captured readback, cycle-7 panel records.

Method: roster + findings schema re-read; seven prior cycles immutable
evidence; fix re-derived from current source in all three copies; upstream
clone fetched, loader byte copy verified against 46825c8d; an 18-shape
line-break battery (LF, CRLF, lone CR, VT, FF, NEL, U+2028, U+2029, tabs)
across all three copies; independent regression mutation back to the
cycle-7 pattern; binding-test bite check on a scratch copy; corpus honesty
audit entry by entry; full gate battery both interpreters. Zero writes to
tracked files.

## Gates run on this tree (all executed this session)

- `python3 scripts/bundle_fleet_module.py --check` — PASS.
- `python3 scripts/check_repo.py` — PASS.
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint`
  = unifi 2.0.5, 23 files,
  `a8fd46a73824ef08c3e7ce6813dfd94884fb14e0b9eb6588d4d0ba1988b647af`.
- `/opt/homebrew/bin/python3.12` — Ran 434 tests, OK (skipped=1).
- PROVENANCE pins 46825c8d / 2.0.5; loader sha256 `ee09062a…` equal on both
  sides of the byte copy.
- `git diff --check` — clean.

## Attack item 1 — line-scoping: LF and CRLF are closed; SIX other break characters still diverge

18-shape battery, all three copies. The repair is real for what it names:
`see notes:\npassword=hunter2` now fires in all three copies (the swallow is
closed), `password:\n  hunter2` passes in all three (split value unmatched),
and CRLF agrees both directions.

But the pattern scopes to `\n` while the repository gate defines lines with
`str.splitlines()`, which recognizes nine break characters. Every other one
still diverges, probed not reasoned:

FAIL-OPEN (loaders accept a credential assignment the gate refuses):
- `see notes:\rpassword=hunter2` — sp/ld PASS, gate FIRES. The greedy
  `[^\S\n]*` after an innocent key's colon eats the CR; scanning resumes
  directly on `p` with no boundary character left. Same verdict split for
  VT (\x0b), FF (\x0c), NEL (\x85), U+2028, U+2029.
- `password=hunter2\rrotation happens quarterly` — gate's first line is a
  bare single-token assignment and fires; the loaders' lookahead captures
  across the CR and reads prose. Same for FF. This is cycle-7 F-02's exact
  fail-open direction surviving for six of the seven break characters.

FAIL-CLOSED (loaders refuse, gate passes):
- `password:\r  hunter2`, and VT/U+2028 variants — loaders match across the
  break (the value class excludes only `\n`), the gate splits on it.

All shapes are reachable through JSON string values (\r, \u2028, \u2029 are
legal or representable). See F-01.

## Attack item 2 — the corpus is honest

`CREDENTIAL_VERDICT_CORPUS` (26 entries) audited entry by entry; the upstream
twin carries the same corpus parametrized. Every must-fire entry reaches the
rule with a substantive single token (no length-floor accident of the kind
that bit cycles 4 and 7): `rainbowtrout`, `sunshine`, `secret`,
`internationalization`, `abc123 <redacted>` all walk to one substantive
literal. Every must-pass entry passes by rule reason, not accident — I traced
the template collapse (`%(UNIFI_TOKEN)s`, `{{ lookup }}`), placeholders,
references, and the `author:` non-strict key. Both multiline shapes are
pinned, and `test_the_corpus_covers_both_line_break_shapes` prevents their
silent loss. One gap: the corpus contains only `\n` breaks — the six exotic
breaks from item 1 are unpinned anywhere (folded into F-01's fix).

## Attack item 3 — the binding test bites

Recorded digests in both cycle-8 proof files equal the actual shipped bytes
(`b3874334…` site_profile, `30a61361…` check_repo, `ee09062a…` loader) — the
cycle-7 identification defect is fixed and now enforced. Scratch-copy check:
one comment edited into `site_profile.py` without re-running its proof →
`MutationProofBindingTest` FAILED naming exactly that. The class, not the
instance, is bound.

## Attack item 4 — the documentation, sentence by sentence

True as written: family 2's strict-key rule and single-substantive-literal
firing; no entropy floor/digit test/length bar; `password: rainbowtrout` and
`password: secret` refused end-to-end (re-probed through validate_profile);
the prose-fields-only allowance; the padded-literal limit stated verbatim;
the 2.0.4/2.0.5 history blockquote's account of both failure directions;
the samples-on-one-line note. FALSE IN PART: "An assignment split across two
lines is not matched by either the loader or the gate … the whitespace around
the delimiter is horizontal only, and the value stops at the line break" —
true for LF and CRLF, false for CR, VT, FF, NEL, U+2028, U+2029, which are
line breaks to the gate (`splitlines`) but not to `[^\S\n]` or the value
class. The categorical sentence has six counterexamples (F-01). Narrower
than the cycle-6/7 doc defects — the common cases are now honest — but the
same class: a categorical contract sentence with behavioral exceptions.

## Attack item 5 — regression tests judged by breaking them

Independent mutation: restored the cycle-7 greedy pattern (`\s*` around the
delimiter, newline-blind value class) in a scratch copy → EXACTLY the
intended failures: both multiline corpus entries
(`see notes:\npassword=hunter2`, `password:\n  hunter2`) fail the
three-copy verdict test, the assignment-family drift pin fails, AND
`MutationProofBindingTest` fires because the graded file changed — three
independent guards tripping on one regression. The committed cycle-8 proofs
cover the same mutations plus strict-key/descriptive/template/length-floor
reversions, with digests that match shipped bytes this time.

## Known-item routing judged

- **Vacuous `CREDENTIAL_KEY_EXACT_IN_TEXT` mutation** (emptying the tuple
  passes the suite): the operator's advisory routing is defensible — the
  function-side mutation IS caught, the tuple has upstream custody in the
  loader copy, and deliberate constant sabotage is a different threat than
  drift. I would still take the one-line hardening (assert the tuple is
  non-empty and pin its literal contents next to the function-side check),
  but it does not block. Advisory stands.
- **Padded-literal allowance**: unchanged from cycle 7; acceptable as
  documented; advisory.
- **Negative Retry-After (#770)**: out of scope per brief.

## Findings (admitted, confidence >=75)

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | plugins/unifi/scripts/site_profile.py:186 | Line scoping names only `\n`; six other splitlines break characters (CR, VT, FF, NEL, U+2028, U+2029) still diverge across the three copies — including fail-open swallow shapes the commit claims closed — and the reference sentence has the same exceptions | correctness, security, api-contract, documentation-clarity | 100 | gated_auto -> review-fixer (upstream-first) |

### Advisory

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| A-01 | tests/test_site_profile.py:176-analog | Emptying CREDENTIAL_KEY_EXACT_IN_TEXT is vacuous; routing as advisory defensible, cheap hardening available | testing | 100 | advisory -> human |
| A-02 | plugins/unifi/scripts/site_profile.py:523 | Padded-literal allowance (carried; acceptable as documented) | security | 100 | advisory -> human |

Suppressed findings: 0. Negative Retry-After excluded per brief (#770).

### Detailed finding

#### F-01 — line scoping is `\n`-only in a `splitlines()` world (P3, introduced here)

- severity P3; dimension_id correctness:boundary-types-serialization-
  numeric-time (also security:input-trust-boundaries-injection,
  api-contract:specification-documentation-parity,
  documentation-clarity:shipped-behavior-parity); critical false.
- file plugins/unifi/scripts/site_profile.py:186-188 (`[^\S\n]*` twice and
  the value class `[^\"',;\n]`); identical in the loader copy and the gate.
- why_it_matters: The commit's contract is "an assignment is one line", but
  the copies disagree on where a line ends. The gate splits on nine break
  characters; the loaders scope to `\n`. Result: six fail-open shapes (an
  operator profile carrying `see notes:\rpassword=hunter2` loads with the
  credential unseen while the repository gate refuses the same text) and
  three fail-closed shapes (a legitimate multi-line prose value containing
  `token:\u2028base64…` is refused by the loader the operator runs). The
  reference sentence "the whitespace around the delimiter is horizontal only
  … the value stops at the line break" inherits the same exceptions.
- evidence: 18-shape battery this session; every divergent row listed under
  attack item 1; mechanism traced through greedy `[^\S\n]*` consuming the
  break so the resumed scan loses its boundary character.
- pre_existing false (the scoping itself is new; cycle-7's F-02 was the `\n`
  instance of it). requires_verification true.
- suggested_fix: define one shared LINE_BREAK class covering Python's
  splitlines set (`\r\n\x0b\x0c\x85\u2028\u2029`) — exclude it from both
  whitespace runs and the value class in all three copies (upstream first),
  extend the corpus with one row per break character, and reword the
  sentence to name the set. Assumption: aligning loaders to the gate's
  definition of a line is the intended semantics.

## Lens selection (roster `lens_roster.v1`, bound to 78c1544)

Always-on run: architecture-maintainability, correctness, security, testing.
Conditional lenses SELECTED, one-line cause each:

- reliability — retry lineage carried; #770 excluded per brief; failure
  surface re-checked for regression.
- api-contract — manifest 2.0.5; the reference contract sentence under
  attack is spec/doc parity.
- adversarial — line-break battery constructed adversarially; evidence
  records attacked via their new binding test.
- deployment-infrastructure — sixth-superseded matrix run bound to
  `a8fd46a7…`; readback re-captured at 2.0.5.
- documentation-clarity — reference sentence rewritten and every claim
  re-probed; two refreshed proof files verified against shipped bytes.
- agent-usability — loader acceptance verdicts changed again for operators
  authoring profiles; gate/loader agreement is a machine-consumed property.
- previous-comments — all three cycle-7 findings repaired and verified;
  disposition completeness audited.

Conditional lenses NOT selected (recorded cause): performance — no latency,
throughput, query, or cost surface; privacy — no personal-data flow changed;
accessibility-human-usability — no human-operated visual surface changed.

## Lens scores — the gate (acceptance: derived_overall >= 9.0 AND every applicable dimension >= 7.0)

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| architecture-maintainability | fit/ownership 9; separation 10; dependency-direction 10; simplicity 9; readability 9; conventions/portability 10; decision-docs 9 | none | **9.43** |
| deployment-infrastructure | infra-config/least-privilege 9; migrations/rollout-order 9; rollback/drift 9; deployed-state-verification 10 | cost-resilience — no resource or cost surface in this delta | **9.25** |
| correctness | intent-behavior 9; state/invariants 9; boundary-types 8; side-effects/lifecycle 9; caller-consumer-completeness 8 | none | **8.60** |
| security | input-boundaries 9; secrets 9; supply-chain 10; confidentiality 9 | authentication-authorization-tenant-isolation — no protected-operation surface touched by this delta | **9.00** |
| testing | requirements/regression 9; negative-edge/time 9; behavior-sensitive assertions 10; realistic-seams 9; determinism/isolation 9 | none | **9.20** |
| reliability | timeouts/retries/idempotency 9; concurrency/partial-failure 9; graceful-degradation/cancellation 9; health-signals 9 | queues-jobs-dead-letters-ordering-backpressure — no queue, job, ordering, or backpressure surface | **9.00** |
| api-contract | interface-compatibility 9; versioning 9; serialization/errors 9; retry-idempotency-semantics 9; pagination/rate-limits 9; spec/doc-parity 8 | sdk-generated-client-impact — no generated SDK surface | **8.83** |
| adversarial | load-bearing-assumptions 9; abuse-edge-cases 8; failure-amplification/silent-green 9; environment/operator-failure 9; scope-creep-risk 10; alternatives-considered 9; recovery 9 | none | **9.00** |
| documentation-clarity | shipped-behavior-parity 8; completeness/audience 9; structure/navigation 9; terminology 9; runnable-examples 9; runbook-safety/drift 9 | none | **8.83** |
| agent-usability | reachability 9; discoverability 9; context/constraints 9; machine-readable-output 9; bounded-operation 9 | none | **9.00** |
| previous-comments | resolution-completeness 9 | none | **9.00** |
| performance | NOT SCORED — not selected | — | — |
| privacy | NOT SCORED — not selected | — | — |
| accessibility-human-usability | NOT SCORED — not selected | — | — |

Gate arithmetic: THREE of eleven scored lenses fail `derived_overall >= 9.0`
(correctness 8.60, api-contract 8.83, documentation-clarity 8.67). NO
applicable dimension falls below the floor — the minimum is
correctness/caller-consumer-completeness and abuse-edge-cases at 8.0. Under
`combiner: all` both rules must hold; the first fails. The typed outcome is
`repairs_requested`.

All three failing scores share one driver: the line-scoping repair is
complete for `\n` and incomplete for the six other characters the gate's own
line definition recognizes (F-01). Nothing else on this tree is defective:
custody, provenance, evidence binding, corpus honesty, and mutation coverage
are all clean and now enforced by a test.

## Built-vs-planned (compact) and scope check

Scope Check: CLEAN. Intent: scope an assignment to one line in all three
copies, correct the reference sentence, bind the mutation proofs to the
bytes they prove, re-run bound evidence at 2.0.5. Delivered: exactly that;
the residual is adjacent-input-class, not unfinished work. COMPLETION:
cycle-7 F-01 DONE for LF/CRLF and corrected-with-exceptions; F-02 DONE for
LF/CRLF; F-03 DONE and class-bound via MutationProofBindingTest.

## Coverage

Suppressed findings: 0. Residual risks: non-LF break divergence (F-01);
padded-literal allowance (A-02); vacuous tuple mutation (A-01); loader rule
custody-pinned upstream only; #770 deferred upstream. Testing gaps: no
corpus row per break character; exotic-break shapes unpinned until F-01
lands.

schema: review_result.v1; best_available_revision: 78c15449fd551fb27621855201fc07edae49d3ac;
outcome: `repairs_requested`; next_action: return_to_work.

## Outcome and routing

> **Plain answer: not yet safe to merge and release under the contract's own
> numbers — three of eleven scored lenses sit below the 9.0 overall minimum
> because "an assignment is one line" is true only for LF-style breaks, while
> the gate and the loaders disagree on six other line-break characters,
> including shapes where a credential loads unseen.** Everything else on this
> candidate is clean: the targeted repairs work for the common cases, custody
> is faithful, the evidence now names real bytes and a test enforces that it
> always will.

Fix order: 1. F-01 — one shared line-break class (the full splitlines set)
in both whitespace runs and the value class across all three copies,
upstream first; add one corpus row per break character; reword the sentence
to name the set. Then resubmit; with that landed every failing score's
driver is gone and `accepted` is the honest verdict.

Route: F-01 gated_auto -> review-fixer (upstream-first); A-01/A-02 advisory
-> human. No saga write performed: this session ran as an independent
programmatic reviewer against a scratch artifact path; no work-thread saga
was scanned or minted.

Raw evidence run this session: all gates green on both interpreters;
18-shape break battery across three copies; independent regression mutation
tripping exactly its intended tests plus the binding test; binding-bite
check on a scratch copy; digest verification of both proof files against
shipped bytes; upstream loader fidelity at 46825c8d.

Review complete. Reviewer: ox-alpha. Reviewed revision: 78c1544
(orch/orch-2026-08-22-unifi-cycle3). Outcome: repairs_requested.
Next action: return_to_work.
