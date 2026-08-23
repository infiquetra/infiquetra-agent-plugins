# Final verification — UniFi portability pilot, cycle 9

Reviewer: ox-alpha (independent reviewer; did not read the panel partner's
artifact). Report built incrementally per brief.

Pre-score verification performed and recorded: `git rev-parse HEAD` printed
8e5847bc7b7608537688e24aa2bb419015386988 (exact match) and
`git status --porcelain` printed nothing. All findings bind to tree 8e5847b.

Delta audited: 78c1544..8e5847b, 20 files, +1870/-116 — the named line-break
set (`CREDENTIAL_LINE_BREAKS`) with a regex class built from it, in three
copies; unifi 2.0.6 resync (upstream 818fd684); per-boundary corpus rows;
the load-bearing exact-key-set test (A-02 closure); refreshed cycle-9
mutation proofs; corrected reference history; seventh-superseded matrix run
(`22bfa568…`); re-captured readback.

Method: roster + findings schema re-read; eight prior cycles immutable
evidence; fix re-derived from current source in all three copies; upstream
clone fetched, loader byte copy verified against 818fd684 (sha256 `577cec77…`
equal both sides); an exhaustive boundary battery — the break set derived
EMPIRICALLY from `str.splitlines()` over codepoints U+0000–U+002F plus
U+0085 and U+2028–U+2029, then both vulnerable shapes probed at every
boundary in all three copies, plus nine edge shapes (CRLF, double/triple
breaks, first-character breaks, breaks inside values); A-02 mutation;
binding-bite mutation; corpus honesty audit; every reference sentence
checked against code. Zero writes to tracked files.

## Gates run on this tree (all executed this session)

- `python3 scripts/bundle_fleet_module.py --check` — PASS.
- `python3 scripts/check_repo.py` — PASS.
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint`
  = unifi 2.0.6, 23 files,
  `22bfa56828fc7d0fb2246f190730082905bd71b82dee3e8d6e5afc4072498d37`.
- `/opt/homebrew/bin/python3.12` — Ran 438 tests, OK (skipped=1).
  Default python3 — Ran 437, OK.
- PROVENANCE pins 818fd684 / 2.0.6.
- `git diff --check` — clean.

## Attack item 1 — boundary set complete and correctly applied: VERIFIED EXHAUSTIVELY

I derived the break set empirically — every codepoint U+0000–U+002F plus
U+0085, U+2028–U+2029 tested against `str.splitlines()` behavior. The
recognized set is exactly ten characters (LF, VT, FF, CR, FS, GS, RS, NEL,
LS, PS) and `CREDENTIAL_LINE_BREAKS` equals it with nothing extra and
nothing missing; identical in all three copies.

Both vulnerable shapes probed at EVERY boundary, all three copies:
- Swallow (`see notes:<BREAK>password=hunter2`) → fires in all three at all
  ten boundaries. Zero fail-open rows remain.
- Split (`password:<BREAK>  hunter2`) → matched by no copy at any boundary.
  Zero false-match rows.

Edge shapes all agree across copies: CRLF swallow, double break, triple
break (LF + FF + LS), a break as the first character of the text, a break
directly after the delimiter, and breaks inside values (LF, CR, U+2028 —
the gate fires on its line, the loaders' value stops at the break and fire
on the same literal). The cycle-8 finding is closed without remainder that
I could find.

## Attack item 2 — the derivation binds

`_LINE_BREAK_CLASS` is BUILT from `CREDENTIAL_LINE_BREAKS` by comprehension,
so within one copy the two cannot disagree by construction. Across copies:
`test_the_break_set_is_exactly_what_splitlines_recognises` rebuilds the set
empirically from standard-library behavior over codepoint space and asserts
it independently for the bundled loader, the target copy, and the gate — so
one copy drifting, or a future Python adding a boundary, fails by name.
Verified myself: empirical set == declared set == same string in all three
files.

## Attack item 3 — the corpus is honest

New entries audited: the six strict-key spellings (`auth`, `accesskey`,
`access_key`, `access-key`, `clientsecret`, `client_secret` each with
`rainbowtrout`) all reach the rule and fire through it — proven by mutation,
not reading: emptying the tuple kills exactly the four tuple-dependent
entries while the two `secret`-fragment spellings survive, which is the
test's own documented claim. The eleven boundary rows pin both shapes at
every boundary in all three copies. Retained entries re-checked from prior
cycles — none passes for an unrelated reason; no length-floor accident, no
vacuous loop. The corpus now has no entry whose verdict I could detach from
the rule without a test failing.

## Attack item 4 — the A-02 closure bites

Emptying `CREDENTIAL_KEY_EXACT_IN_TEXT` in BOTH target copies → **10
failures**: four corpus rows (`auth: rainbowtrout`, three access-key
spellings) and four behavior assertions in
`test_the_exact_key_set_cannot_be_emptied_without_failures`, plus the
drift-pin consequences. The tuple is load-bearing. The test's own claim
holds: `clientsecret`/`client_secret` appear in NO failure because the
`secret` fragment catches them regardless — exactly what the docstring says
("it is here because the contract names it, not because it proves anything
about the tuple").

## Attack item 5 — mutation proofs and binding hold

Recorded digests in both cycle-9 proof files (`31c9695f…` site_profile,
`79dc00e3…` check_repo, `577cec77…` loader) equal the actual shipped bytes —
verified by recomputation, not by trusting the records. Bite check on a
scratch copy of THIS tree: emptied the boundary set in site_profile.py
without re-running its proof → `MutationProofBindingTest` FAILED (24 total
failures with the boundary-agreement suite, each naming its cause). The
proofs also cover the new mutations (line-scoping removed, break set
altered) per their headers, and my independent cycle-8-style regression was
already proven to bite last cycle.

## Attack item 6 — the documentation is true

Every sentence probed against code. The "one line" definition now names all
ten boundaries and matches them; "the whitespace around the delimiter is
horizontal only" is true (`[^\S{class}]*`); "the value stops at the line
break" is true (value class excludes the set). The history blockquote
honestly recounts BOTH failure rounds including 2.0.5's partial repair
("repaired both for the newline and nothing else … eight of them fail-open")
— an accurate confession, not a softened one. The prose list of boundaries
matches the set. Family 2, the strict-key derivation, the prose allowance,
and the padded-literal limit were re-verified against code unchanged from
2.0.4 and remain accurate. No sentence found claiming behaviour the code
lacks.

## Findings

**None admitted.** No finding reached confidence 75 in either direction:
every attack returned the intended verdict, every record matches its bytes,
every sentence matches its behavior. The two known items remain as carried
advisories, unchanged: the padded-literal allowance (documented; both
reviewers judged it acceptable) and negative Retry-After (#770, upstream,
out of scope per brief). The A-02 vacuous-tuple advisory from cycle 8 is
CLOSED this cycle — verified by mutation.

## Lens selection (roster `lens_roster.v1`, bound to 8e5847b)

Always-on run: architecture-maintainability, correctness, security, testing.
Conditional lenses SELECTED, one-line cause each:

- reliability — retry lineage carried; #770 excluded per brief.
- api-contract — manifest 2.0.6; reference contract text under test again.
- adversarial — full Unicode break space probed adversarially; evidence
  records and their binding attacked.
- deployment-infrastructure — seventh matrix run bound to `22bfa568…`;
  readback re-captured at 2.0.6.
- documentation-clarity — reference history rewritten; every sentence
  re-verified against code.
- agent-usability — loader verdicts changed across boundary inputs;
  cross-copy agreement is a machine-consumed property.
- previous-comments — all three cycle-8 findings closed; disposition
  completeness audited including my own F-01.

Conditional lenses NOT selected (recorded cause): performance — no latency,
throughput, query, or cost surface; privacy — no personal-data flow changed;
accessibility-human-usability — no human-operated visual surface changed.

## Lens scores — the gate (acceptance: derived_overall >= 9.0 AND every applicable dimension >= 7.0)

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| architecture-maintainability | fit/ownership 9; separation 10; dependency-direction 10; simplicity 9; readability 9; conventions/portability 10; decision-docs 10 | none | **9.57** |
| deployment-infrastructure | infra-config/least-privilege 9; migrations/rollout-order 9; rollback/drift 9; deployed-state-verification 10 | cost-resilience — no resource or cost surface in this delta | **9.25** |
| correctness | intent-behavior 10; state/invariants 9; boundary-types 10; side-effects/lifecycle 9; caller-consumer-completeness 10 | none | **9.60** |
| security | input-boundaries 10; secrets 9; supply-chain 10; confidentiality 9 | authentication-authorization-tenant-isolation — no protected-operation surface touched by this delta | **9.50** |
| testing | requirements/regression 10; negative-edge/time 10; behavior-sensitive assertions 10; realistic-seams 9; determinism/isolation 9 | none | **9.60** |
| reliability | timeouts/retries/idempotency 9; concurrency/partial-failure 9; graceful-degradation/cancellation 9; health-signals 9 | queues-jobs-dead-letters-ordering-backpressure — no queue, job, ordering, or backpressure surface | **9.00** |
| api-contract | interface-compatibility 9; versioning 9; serialization/errors 9; retry-idempotency-semantics 9; pagination/rate-limits 9; spec/doc-parity 10 | sdk-generated-client-impact — no generated SDK surface | **9.17** |
| adversarial | load-bearing-assumptions 10; abuse-edge-cases 10; failure-amplification/silent-green 9; environment/operator-failure 9; scope-creep-risk 10; alternatives-considered 9; recovery 9 | none | **9.43** |
| documentation-clarity | shipped-behavior-parity 10; completeness/audience 9; structure/navigation 9; terminology 9; runnable-examples 9; runbook-safety/drift 10 | none | **9.33** |
| agent-usability | reachability 9; discoverability 9; context/constraints 9; machine-readable-output 9; bounded-operation 9 | none | **9.00** |
| previous-comments | resolution-completeness 9 | none | **9.00** |
| performance | NOT SCORED — not selected | — | — |
| privacy | NOT SCORED — not selected | — | — |
| accessibility-human-usability | NOT SCORED — not selected | — | — |

Gate arithmetic: ELEVEN of eleven scored lenses meet `derived_overall >=
9.0` (minimum 9.00: reliability, agent-usability, previous-comments). NO
applicable dimension falls below the floor — the minimum is 9.0, well above
7.0. Under `combiner: all` both rules hold. The typed outcome is
`accepted`.

## Built-vs-planned (compact) and scope check

Scope Check: CLEAN. Intent: name the line-break set once, derive the
matching rule from it, pin every boundary in both shapes across all three
copies, make the exact-key tuple load-bearing, re-prove the guards against
the bytes that ship, and correct the reference history. Delivered: all of
it; every changed file maps to that intent. COMPLETION: cycle-8 F-01 DONE
(exhaustively — empirically derived boundary space, both shapes, three
copies); A-01 vacuous-tuple advisory CLOSED by mutation; A-02 padded-literal
allowance remains documented-and-accepted; F-03's binding class held (new
digests verified real).

## Coverage

Suppressed findings: 0. Residual risks: padded-literal allowance
(documented, accepted); negative Retry-After (#770, upstream); loader rule
custody-pinned upstream only; matrix binding remains identity-not-execution
(O7 Maybe). Testing gaps: none found this cycle — boundary space, both
shapes, key-set load-bearingness, and evidence identity are each pinned.

schema: review_result.v1; best_available_revision: 8e5847bc7b7608537688e24aa2bb419015386988;
outcome: `accepted`; next_action: continue.

## Outcome and routing

> **Plain answer: yes — this exact commit is safe to merge and release.**
> Every attack returned the intended verdict: the boundary set is complete
> against an empirically derived standard-library definition, all three
> copies agree at every boundary in both shapes, the key set is load-bearing,
> the mutation proofs name real bytes and a test keeps them honest, the
> documentation is true, and every scored lens clears both acceptance rules.

Route per `accepted`: continue to the caller's next independent gate. The
carried advisories (padded-literal allowance; #770 negative Retry-After,
upstream) stay recorded as residuals — neither is a merge condition. No saga
write performed: this session ran as an independent programmatic reviewer
against a scratch artifact path; no work-thread saga was scanned or minted.

Raw evidence run this session: all gates green on both interpreters;
empirical boundary derivation over codepoint space plus 20 boundary-shape
rows across three copies and 9 edge shapes; A-02 mutation (10 failures);
binding-bite mutation (24 failures); digest recomputation of both proof
files and the loader against upstream 818fd684; end-to-end validate_profile
probes from prior cycles re-confirmed on the untouched rule halves.

Review complete. Reviewer: ox-alpha. Reviewed revision: 8e5847b
(orch/orch-2026-08-22-unifi-cycle3). Outcome: accepted. Next action:
continue.
