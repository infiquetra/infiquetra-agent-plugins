# Scored code review — UniFi portability pilot, cycle 5

Reviewer: ox-alpha (independent reviewer, different model/session from the
cycle-5 panel partner; unattended). Artifact built incrementally per brief.

Target: /Users/jefcox/workspace/infiquetra/infiquetra-agent-plugins,
branch orch/orch-2026-08-22-unifi-cycle3, HEAD 08ab2de, working tree clean,
no untracked files. Delta audited: 2bd0faf..08ab2de (367d9b6 credential span;
0bcdffe cycle-4 records; 08ab2de resync to UniFi 2.0.2 / Fleet Core 0.25.2).
All findings bind to tree 08ab2de.

Method: read the roster (`lens_roster.v1`, 14 lenses), findings schema, all
cycle-4 artifacts as immutable evidence; re-derived every repair from current
source; verified custody against the real upstream clone on disk
(infiquetra-claude-plugins @ c835f91d / 3b5faa6c); ran every gate; ran live
defeat probes — stubbed-429 runs through the REAL request path of both clients
(`_bundled` copies loaded, zero network), credential-rule batteries against all
three copies of the rule plus a simulated pre-repair rule for new/old
classification, ten-document parity probes across both loader halves, floor
mutation attack on a scratch copy only. Zero writes to tracked files.

## Gates run on this tree (all executed this session)

- `python3 scripts/bundle_fleet_module.py --check` — PASS.
- `python3 scripts/check_repo.py` — PASS.
- `python3 scripts/check_compatibility_matrix.py` — PASS: four superseded
  matrices + current, binding intact; current record 38 executed / 2 blocked /
  9 works-directly / 0 failed at 23 files `4c256bb2…5cfa`, version 2.0.2.
- `python3 -m unittest discover -s tests` on default python3 (3.14.6) — OK.
- `/opt/homebrew/bin/python3.12` (3.12.13, the REAL floor interpreter) —
  420 tests OK (1 skip = pytest-guard module). The floor is exercised.
- `git diff --check` — clean; working tree clean after all probes.

## Brief item 1 — non-finite Retry-After: REPAIR BITES at primitive and both call sites

`_usable_delay` (plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:48-60)
guards BOTH parse paths — numeric :94 and delta-seconds string :101 — returning
None for anything `math.isfinite` refuses. The HTTP-date path ends in
`max(0.0, …)` (:110) and cannot produce inf (datetime caps at year 9999).

End-to-end probes this session through the real `_request` path of BOTH clients
(requests stubbed, sleep captured, the `_bundled` copies loaded exactly as a
client loads them): `inf`, `-inf`, `nan`, `1e400`, `-1e400`, `infinity`,
`+nan`, whitespace-wrapped — all fall back to computed jittered backoff
(0.5–1.9 s observed), retry to 3 attempts, and exit with the typed surface
INTACT: `"status_code": 429, "retry_after": 60`. The cycle-4 crash inside
`math.ceil` is gone. A positive hint still honors (`'60'` → sleeps [60, 60]).

**Header shape that still gets through: negative delta-seconds.**
`parse_retry_after("-5")` returns **-5.0** — finite, so `_usable_delay` passes
it; only the docstring's "never a negative delay" (retry_backoff.py:17, 79)
claims otherwise. The retry loop stays safe (`hint > 0` gate, :123), but on
exhaustion both clients emit `"message": "Rate limited. Retry after -5
seconds", "retry_after": -5` — probed live, both clients. Same class:
`1e308` → advice `ceil(1e308)` = a 309-digit "wait" in machine-readable JSON.
See F-02.

## Brief item 2 — the credential span: repair works, but BOTH failure directions keep live edges

The fix (367d9b6) is applied to both copies and the constants/pattern are
drift-pinned (tests/test_site_profile.py:691+ pins `CREDENTIAL_SCHEME_WORDS`,
min length, min entropy, pattern). Probed battery results:

MUST FIRE, now firing on both copies: `authorization: Bearer <30-char token>`,
`Basic <b64>`, `Token`, bare `api_key=<token>` — the cycle-4 hole is closed.

**Credential shapes that still pass (both copies):**
`authorization: use Bearer <token>` (scheme word not in position 1 — only the
first token and one scheme-word successor are ever graded),
`authorization: Bearer,<token>` (capture stops at the comma),
`auth (use Bearer <token> for cli)`. Narrower than the repaired hole, but the
rule grades at most two fixed positions of one match.

**Legitimate values NOW falsely rejected (new with this repair):** grading
tokens[1] behind a scheme word fires on ordinary English. Verified against
both copies AND the Claude-path loader's own restatement:
"auth: token rotation happens weekly", "token: bearer securities are held in
trust", "notes: token: basic training covers the dashboard" — all ACCEPTED by
the pre-repair rule (simulated), all REJECTED now. The commit's own
must-not-fire set survives only because its words happen to fall under the
6-character floor ("Bearer token is stored…" passes because "token" is 5
characters). See F-01.

## Brief item 3 — the 1.1 contract skew: CLOSED, halves agree on every probe

The Claude-path loader (com.infiquetra.claude/…/site_profile_loader.py) now
declares `SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1")` (:87) and restates the
full value rule; SCHEMA_IDENTIFIER is `…:1.1` in loader (:84), portable
site_profile.py (:74), and schema `$id` — all three agree.

Ten-document probe, portable `validate_profile` vs Claude loader on identical
documents: valid inert 1.0 ACCEPT/ACCEPT, valid 1.1 ACCEPT/ACCEPT, version
"2.0" REJECT/REJECT (UnsupportedSchemaVersionError both), 1.0 and 1.1 each with
`password=hunter2` REJECT/REJECT naming the value, Bearer-paste REJECT/REJECT,
AKIA literal REJECT/REJECT, prose-FP shape REJECT/REJECT (both halves share
F-01). **Zero divergence.** The cycle-4 F-01/C4-2 defect no longer exists in
either direction.

Custody note: the loader copy is a byte copy of upstream
`plugins/unifi/skills/unifi-network/scripts/site_profile_loader.py` at
c835f91d (sha256 42815630… equal both sides, PROVENANCE :54-57). Its rule is
therefore pinned to UPSTREAM bytes, not to the two local copies — nothing in
tests pins `loader._credential_candidates == site_profile._credential_candidates`.
Today they are identical by custody; if upstream's rule next diverges from this
repo's target-owned rule, no gate here notices. Recorded as advisory A-02.

## Brief item 4 — the Python floor: AGREES EVERYWHERE, gate bites on 3.12.13

`PYTHON_FLOOR = (3, 12)` single authority; full suite green on
/opt/homebrew/bin/python3.12 (420 tests OK). Mutation probe on a SCRATCH copy
(git archive of HEAD, reviewed tree untouched): `python>=3.12` →
`python>=3.11` in plugins/fleet-core/README.md:48, suite run from the scratch
root on python3.12 — **FAILED (failures=2)**, naming the site:
"plugins/fleet-core/README.md:48 declares python>=3.11". Deletion is also
covered (presence check, proven in cycle 4 and unchanged).

Evidence-side floor discipline verified: the matrix and readback both state
every invocation ran on CPython 3.12.13 by explicit path; I reproduced the
readback's entrypoint claim myself in a throwaway venv (requests+urllib3 only)
on python3.12: network --help = 30 lines, protect --help = 22 lines — exactly
the readback's recorded numbers.

## Brief item 5 — custody and provenance: FAITHFUL, pins coherent

- Fleet Core hand extraction: shipped
  `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py` sha256
  `2aa7fd26…3021` == `git show 3b5faa6c:<path>` from the upstream clone ==
  PROVENANCE.json:35 pin. Mechanical-extraction claim holds.
- Two-pins-one-state: `git diff 3b5faa6c c835f91d -- plugins/fleet-core` over
  the upstream clone is EMPTY; c835f91d is a direct descendant; fleet-core
  PROVENANCE pins 3b5faa6c / 0.25.2 (:3-4), unifi PROVENANCE pins c835f91d /
  2.0.2 (:3-4). Exactly as the readback's custody section claims.
- Ported test: upstream `tests/test_retry_backoff.py` at c835f91d sha256
  `07ec46c5…` == PROVENANCE derived_files.source_sha256; output file sha256
  `eb1b7b48…` == PROVENANCE sha256; body from `class RateError(Exception):`
  to EOF is BYTE-IDENTICAL to upstream (`cmp` clean) — the guard-pytest-import
  transform was re-applied, not hand-edited. Upstream test identical between
  the two pins, so deriving at either is consistent.

## Brief item 6 — the evidence documents: every checked claim true of this tree

Matrix binding: validator PASS recomputes 23 files / `4c256bb2…` / unifi 2.0.2
against this tree; readback record bound by tests (test_check_compatibility_matrix.py:961+,
READBACK_DOCUMENT). Unit digests recomputed by me with the documented
algorithm: unifi-network 4 files `3650ae42…113b` MATCH, unifi-protect
`ba06e585…5a4f` MATCH. Muse-install-record claim verified:
both `_bundled/retry_backoff.py` copies sha256 `9e1f2f17e9645f05…`, 11069
bytes — exactly as the matrix's Muse row records. The Claude-row claim
"parse_retry_after('1e400') returns None" in the loaded bundle confirmed by my
end-to-end probes (fallback sleeps observed). Help-line counts confirmed.
Identity-leak sweep over docs/evidence/*.md (emails, account/user ids, MACs,
RFC1918 addresses): one hit only — the disclosure sentence itself ("no account
identity published here"). Clean.

**More of the stale-prose class — FOUND two more instances, both in
QUEUED.md, no gate checks either:**

1. "Decide, per client, what follows the compatibility matrix" still reads
   "**Eight** consumed … directly" and "**Cursor Agent is recorded as
   failed**" — the current matrix reads nine works-directly and none failed.
2. "The ported Fleet Core test still pins the pre-2.0.1 caller shape"
   frames re-derivation as an open custody question and asserts the ported
   copy "still asserts what happens to a caller shape this repository no
   longer ships". This cycle RE-DERIVED it (at 3b5faa6c, where the fleet
   subtree legitimately moved — option one of the entry's own dichotomy);
   the local file now carries the inverted
   `test_a_caller_that_pre_parses_with_parse_retry_after_keeps_the_retry`
   (:374). The 367d9b6 sweep archived two stale siblings and missed this
   third, which 08ab2de made stale hours later. See F-03, F-04.

## Brief item 7 — the Cursor Agent correction: SOUND, honestly disclosed, no leak

Soundness: the superseded run exported an empty scratch HOME for isolation;
this client keeps authentication in the home, so the harness measured a
logged-out client and recorded its credential refusal as a client failure.
That is a measurement-of-the-wrong-thing defect, not a package or client
defect — the correction's causal account is coherent, and the package did not
change between runs (the commit says so; the three repairs changed behavior
inside the package, not any surface a client sees). The alternative honest
reading — record blocked-on-authentication like other credential-gated stages
— was available, but reassessment against the operator's real home answers a
question the blocked row cannot.

Disclosure: stated in FOUR places (isolation bullet — "Nine clients ran
against their own empty home… Cursor Agent is the single exception"; detail
section "What the superseded publication said, and why it was wrong"; the row
reason; the superseded doc's `superseded-reason` comment). The relaxation is
scoped to exactly one client with the cause named. Residual asymmetry,
recorded rather than hidden: nine rows measure unauthenticated first-run
installs, one row measures an authenticated configured machine. For a survey
that explicitly is "not a release gate", disclosed and acceptable.

Identity: grep over all evidence for emails/account ids/MACs/internal
addresses — clean; authentication recorded only as present/absent. The
invocation-count pin moved 8 → 9 WITH the reason in the test comment
(test_check_compatibility_matrix.py), so the pin's own change is auditable.

## Brief item 8 — what four cycles missed

1. **The false-positive half of the credential repair (F-01, P2).** Four
   cycles hunted detection misses; nobody graded the rule against innocent
   input after the span widened. The recurring pattern again: the guarantee
   exists and bites — but also bites where it must not.
2. **Negative-finite Retry-After (F-02, P3)** — the non-finite fix's own
   neighborhood.
3. **Two more stale journal records (F-03/F-04, P3)** — same class as
   cycle-4 F-03/F-04; the archive sweep closed two instances and a sibling
   re-opened the same day. No gate reads QUEUED.md prose except the O7
   claims test, so this class stays invisible to CI by construction.
4. **Multi-line divergence between gate and loaders (A-02, advisory):**
   check_repo scans line-by-line, so `authorization:\n  Bearer <token>`
   escapes the repo gate while both loaders reject it; verified live.
5. Loader-rule custody gap (loader pinned to upstream bytes, not to the
   local rule pair) — folded into A-02.

## Findings (admitted, confidence >=75; sorted P0→P3 then confidence→file→line)

### P2

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | plugins/unifi/scripts/site_profile.py:482 | Widened credential span falsely rejects ordinary operational prose in all three copies of the rule | security, correctness | 100 | gated_auto -> review-fixer |

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-02 | plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:101 | Negative delta-seconds parses to -5.0 despite "never a negative delay"; typed advice reads "Retry after -5 seconds" | correctness, reliability | 100 | gated_auto -> review-fixer (upstream-first) |
| F-03 | docs/engineering-journal/QUEUED.md:60 | Per-client decision entry still says eight works-directly / Cursor failed; matrix now says nine / none failed | documentation-clarity, architecture-maintainability | 100 | safe_auto -> review-fixer |
| F-04 | docs/engineering-journal/QUEUED.md:115 | Ported-test entry frames an answered custody question as open; test was re-derived at 3b5faa6c this cycle | documentation-clarity, architecture-maintainability | 100 | safe_auto -> review-fixer |

### Advisory

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| A-01 | scripts/check_repo.py:828 | Line-based gate misses multi-line assignment shapes both loaders reject; drift pin covers single-line corpus only | architecture-maintainability, security | 100 | advisory -> human |
| A-02 | plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py:415 | Loader's restated value rule is custody-pinned to upstream, not drift-pinned to the two local copies it must agree with | architecture-maintainability | 100 | advisory -> human |

### Detailed findings (per findings-schema.md)

#### F-01 — widened credential span grades English behind scheme words (P2, introduced by 367d9b6)

- severity P2; dimension_id secrets-cryptography-session-handling (also
  correctness:intent-behavior-completeness); critical false.
- file plugins/unifi/scripts/site_profile.py:482 (_credential_in_text grading
  loop); same behavior in _credential_candidates :453-469, check_repo.py
  :795-810/:828-840, loader copy :415-431.
- why_it_matters: The repair's stated design limit — "grading every token
  would reject a profile for describing where the credential lives" — is
  violated by the shipped rule itself. A profile note "auth: token rotation
  happens weekly" is rejected by BOTH halves (probed via validate_profile),
  and the repo gate fires on the same prose in any tracked file under
  plugins/, so a documentation sentence can break CI. Operators get
  "'auth' is assigned a credential-shaped value" for text containing no
  credential, which trains exactly the trust-erosion the reference doc warns
  about ("a rule that gets switched off within a day").
- evidence: live probes this session — pre-repair rule (simulated old
  pattern + single-token grading) returns None for all three shapes;
  post-repair site_profile._credential_in_text, check_repo.credential_findings,
  and the Claude loader all fire on them. Pinned must-not-fire set
  (tests/test_site_profile.py) covers only shapes whose post-scheme word is
  short ("token" = 5 chars < floor 6). Entropy arithmetic: "rotation" 2.5,
  "securities" ~2.72, "training" 2.50 bits/char — ordinary words clear the
  floor.
- residual recall gap (same finding, second direction): scheme word not in
  position 1 (`use Bearer <token>`), comma after scheme word, parenthetical
  placement — credential passes unexamined in both copies.
- pre_existing false (introduced by 367d9b6 in this delta);
  requires_verification true.
- suggested_fix: grade tokens[0] and tokens[1] only when tokens[1] is NOT an
  English stopword-ish token OR require the scheme-word successor to clear a
  higher bar (e.g., >= 12 chars or no vowel/consonant structure check is
  overfit — simplest defensible default: extend the pinned must-not-fire set
  with rotation/securities/training-class words and grade the scheme-word
  successor only if it also fails a dictionary heuristic); both copies +
  loader upstream coordination needed since the loader restates the rule.
  Assumption: precision matters more than the marginal recall of position-2
  grading.

#### F-02 — negative delta-seconds reaches the typed 429 surface (P3)

- severity P3; dimension_id boundary-types-serialization-numeric-time; also
  reliability:timeouts-retries-circuit-breakers-idempotency. critical false.
- file plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:101
  (`return _usable_delay(float(text))`); callers
  unifi_network_client.py:203 and unifi_protect_client.py:203.
- why_it_matters: `_usable_delay` stops at finiteness only. `"-5"`, `"-0.5"`,
  numeric -5 all parse to negative finite delays the function's own contract
  forbids ("reduced to a non-negative delay", "never a negative delay",
  retry_backoff.py:17,79). Retries stay safe (the `hint > 0` gate falls back
  to computed backoff), but on exhaustion `math.ceil(-5.0)` = -5 and both
  clients publish `"retry_after": -5` in machine-readable JSON with the
  message "Rate limited. Retry after -5 seconds". Same class: `1e308` is
  finite and unclamped at exhaustion — advice becomes a 309-digit integer.
  A consuming agent reading retry_after gets an invalid wait.
- evidence: probed end-to-end this session on both clients' real request
  paths (stubbed requests): full typed JSON captured showing retry_after: -5;
  primitive probes: "-5" → -5.0, "-0.5" → -0.5, int -5 → -5.0 vs docstring.
- pre_existing false with honest caveat: the runtime outcome equals baseline
  (2bd0faf also emitted -5); what this diff introduces is the guard AND the
  docstring claiming non-negativity while the implementation still returns
  negatives — the repair of this exact input class stopped one predicate
  short. requires_verification true.
- suggested_fix (upstream-first; both clients are deterministic transforms):
  in `_usable_delay` return `seconds if seconds > 0 and math.isfinite(seconds)
  else None` — or clamp negatives to None so they read as "no usable hint";
  update the module docstring's promise to match; resync. One line; every
  consumer inherits it.

#### F-03 — QUEUED per-client entry contradicts the current matrix (P3)

- severity P3; dimension_id documentation-clarity:shipped-behavior-parity
  (also architecture-maintainability:significant-decision-documentation);
  critical false.
- file docs/engineering-journal/QUEUED.md; lines 60-67 (entry 49-75).
- why_it_matters: The entry directing the pilot's next operator decision says
  "Eight consumed the portable package or its skill units directly" and
  "Cursor Agent is recorded as failed". The current matrix — bound to this
  tree by digest — reads nine works-directly, none failed. An operator doing
  per-client decisions from the queue would re-litigate Cursor as a failure
  the evidence no longer records. Same defect class the matrix re-run itself
  caught (stale prose inside an artifact no gate parses).
- evidence: QUEUED.md:60-67 vs docs/evidence/2026-08-22-unifi-compatibility-matrix.md:151-153;
  test_journal_o7.py pins only the O7 Maybe section — no gate checks this
  entry.
- pre_existing false (made stale by 08ab2de in this delta). safe_auto ->
  review-fixer; requires_verification false.
- suggested_fix: update the counts to nine/one and the Cursor sentence to the
  reassessed works-directly status (or archive-and-replace the entry if the
  decision it schedules has been taken).

#### F-04 — ported-test queue entry describes answered work (P3)

- severity P3; dimension_id documentation-clarity:shipped-behavior-parity;
  critical false.
- file docs/engineering-journal/QUEUED.md; lines 115-151.
- why_it_matters: The entry's premise — the ported copy "still asserts what
  happens to a caller shape this repository no longer ships", with an open
  custody dichotomy (separate pin vs wait for the next Fleet Core release) —
  was resolved THIS CYCLE: 08ab2de re-derived the test from 3b5faa6c, where
  the Fleet Core subtree itself moved, so the derived pin follows the package
  pin legitimately. The local file now carries upstream's inverted
  characterization test (:374) and PROVENANCE records source_sha256 07ec46c5…
  / output eb1b7b48…, both verified against the clone. The journal's own
  convention says shipped entries move to ARCHIVE; the 367d9b6 sweep moved
  two siblings and missed this one, which became stale hours later.
- evidence: QUEUED.md:127-137 vs tests/test_retry_backoff.py:374 and
  plugins/fleet-core/PROVENANCE.json:38-48; my byte-level verification.
- pre_existing false. safe_auto -> review-fixer; requires_verification false.
- suggested_fix: archive the complete entry with a "shipped in 08ab2de"
  resolution per convention, and record that option two of its own dichotomy
  was unnecessary.

#### A-01 — repo gate and loaders disagree on multi-line assignments (advisory)

check_repo.credential_findings scans per line (:826-829), so
`authorization:\n  Bearer <token>` or `api_key:\n  <token>` escapes the repo
gate while both loaders reject it (`\s*` crosses newlines in their patterns;
probed live: loader REJECT / gate []). CredentialRuleDriftTest pins constants
and single-line corpus only. Direction is safe for profiles (the enforcement
point is the loader); the gate's blindness is to source-file shapes that
cannot occur on one line. Recorded so the "one rule" claim stays honest.

#### A-02 — loader value rule pinned to upstream bytes, not to local copies (advisory)

The Claude-path loader's restated rule is an upstream-byte-copy whose digest
pins it to c835f91d. Nothing pins `loader.CREDENTIAL_SCHEME_WORDS ==
site_profile.CREDENTIAL_SCHEME_WORDS` etc.; today identical by custody, and
the next upstream evolution of either half can silently fork the contract
this package documents — the C4-2 shape re-entering through custody instead
of versioning. A cheap drift test importing the loader file would close it.

## Lens selection (roster `lens_roster.v1`, bound to 08ab2de)

Always-on run: architecture-maintainability, correctness, security, testing.
Conditional lenses SELECTED, one-line cause each:

- reliability — Retry-After semantics are the cycle's core repair; failure
  paths probed end-to-end on both clients.
- api-contract — schema/loader versions moved to 1.1, typed 429 JSON changed
  inputs, spec/doc parity checkable.
- adversarial — every new guarantee attack-probed; guarantees-that-do-not-
  bite hunted per the four-cycle pattern.
- deployment-infrastructure — evidence re-captured on the floor interpreter;
  readback and matrix bound to this tree by tested digests.
- documentation-clarity — reference doc, journal, two evidence documents
  rewritten; their parity claims are checkable against the tree.
- agent-usability — machine-readable contracts changed: loader acceptance,
  typed error JSON, matrix/readback records agents consume.
- previous-comments — four prior review cycles' reconciled findings apply
  directly to this revision; resolution completeness audited (C4-1..C4-11).

Conditional lenses NOT selected (recorded cause): performance — no latency,
throughput, query, or cost surface touched; privacy — no personal-data flow
changed, evidence identity-sweep clean; accessibility-human-usability — no
human-operated visual/keyboard surface changed.

## Lens scores — the gate (acceptance: derived_overall >= 9.0 AND every applicable dimension >= 7.0)

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| architecture-maintainability | fit/ownership 8; separation 9; dependency-direction 10; simplicity 8; readability 9; conventions/portability 9; decision-docs 7 | none | **8.57** |
| deployment-infrastructure | infra-config/least-privilege 9; migrations/rollout-order 9; rollback/drift 9; deployed-state-verification 10 | cost-resilience — no resource or cost surface in this delta | **9.25** |
| correctness | intent-behavior 7; state/invariants 9; boundary-types 8; side-effects/lifecycle 9; caller-consumer-completeness 9 | none | **8.40** |
| security | input-boundaries 8; secrets 7; supply-chain 10; confidentiality 9 | authentication-authorization-tenant-isolation — no protected-operation surface touched by this delta | **8.50** |
| testing | requirements/regression 8; negative-edge/time 8; behavior-sensitive assertions 9; realistic-seams 9; determinism/isolation 9 | none | **8.60** |
| reliability | timeouts/retries/idempotency 9; concurrency/partial-failure 9; graceful-degradation/cancellation 9; health-signals 9 | queues-jobs-dead-letters-ordering-backpressure — no queue, job, ordering, or backpressure surface | **9.00** |
| api-contract | interface-compatibility 8; versioning 9; serialization/errors 9; retry-idempotency-semantics 8; pagination/rate-limits 9; spec/doc-parity 7 | sdk-generated-client-impact — no generated SDK surface | **8.33** |
| adversarial | load-bearing-assumptions 7; abuse-edge-cases 7; failure-amplification/silent-green 8; environment/operator-failure 8; scope-creep-risk 10; alternatives-considered 8; recovery 9 | none | **8.14** |
| documentation-clarity | shipped-behavior-parity **6**; completeness/audience 9; structure/navigation 9; terminology 9; runnable-examples 9; runbook-safety/drift 7 | none | **8.17** |
| agent-usability | reachability 9; discoverability 9; context/constraints 9; machine-readable-output 8; bounded-operation 9 | none | **8.80** |
| previous-comments | resolution-completeness 8 | none | **8.00** |
| performance | NOT SCORED — not selected | — | — |
| privacy | NOT SCORED — not selected | — | — |
| accessibility-human-usability | NOT SCORED — not selected | — | — |

Gate arithmetic: NINE of eleven scored lenses fail `derived_overall >= 9.0`
(architecture 8.57, correctness 8.40, security 8.50, testing 8.60, api-contract
8.33, adversarial 8.14, documentation-clarity 8.17, agent-usability 8.80,
previous-comments 8.00), and ONE applicable dimension fails the floor:
documentation-clarity `shipped-behavior-parity` = 6 < 7.0 — multiple live
records disagree with shipped behavior (two stale QUEUED entries verified
false against this tree, plus the reference doc's value-rule description
predating the scheme-word span). The typed outcome is therefore
`repairs_requested` on both failing rules before any Priority is consulted.

## Built-vs-planned (compact) and scope check

Scope Check: CLEAN. Intent: repair the cycle-4 reconciled findings at the
custody boundary that owns each (credential span locally; loader skew and
non-finite Retry-After upstream via 2.0.2 / 0.25.2), record the cycle-4
panel, re-run all evidence bound to the tree. Delivered: exactly that; every
changed file maps to one of those.

COMPLETION: C4-1 credential span DONE (bites; F-01 is its false-positive
half); C4-2 loader skew DONE (ten-document parity probed); C4-3 non-finite
DONE (end-to-end; F-02 is the adjacent edge); C4-4/C4-5 archive sweep DONE
for the two named entries but its sibling went stale same-day (F-03/F-04);
C4-6..C4-11 dispositions recorded as deferred/accepted/no-action and still
accurate. Resync DONE (digests three-way verified against the clone).
Evidence re-run DONE (fourth matrix run + fourth readback, bound by tests,
floor interpreter). Invocation-count pin moved 8→9 with reason recorded.

## Coverage

Suppressed findings: 0 (nothing admitted below anchor 75). Residual risks:
matrix binding remains identity-not-execution (O7 Maybe, unchanged);
committed __pycache__ blind spot unchanged (prior advisory); low-entropy
short secrets remain an admitted, pinned limit; Cursor row measures a
different basis than the other nine rows — disclosed in the document;
multi-line gate/loader divergence (A-01) errs safe for profiles.
Testing gaps: no must-not-fire corpus beyond four prose shapes for the
credential rule; no test covers negative-finite Retry-After; no drift pin
binds the loader's rule copy to the local pair.

## Outcome and routing

> **Plain answer: not yet safe to merge and release under the contract's own
> numbers — the outcome is `repairs_requested`.** The three repairs are real
> and verified end-to-end, custody is faithful, the evidence documents match
> this tree — but nine of eleven scored lenses sit below the 9.0 overall
> minimum, and the credential repair rejects innocent operational prose in
> three copies of the rule while two journal records still describe last
> cycle's tree.

schema: review_result.v1; best_available_revision: 08ab2de; outcome:
`repairs_requested`; next_action: return_to_work.

Fix order: 1. F-01 precision fix across both local copies + upstream loader
coordination (gated_auto; extend the must-not-fire set with realistic prose,
narrow position-2 grading). 2. F-03+F-04 journal sweep (safe_auto, minutes;
also refresh the DECISIONS ref to the archived README entry). 3. F-02
upstream one-liner in `_usable_delay` + resync (gated_auto). 4. A-01/A-02 as
queued advisory decisions. With F-01 landed and the parity records current,
every failing score's driver is gone and `accepted` is the honest verdict.

Route: F-01 gated_auto -> review-fixer; F-02 gated_auto -> review-fixer
(upstream-first); F-03/F-04 safe_auto -> review-fixer; A-01/A-02 advisory ->
human. No saga write performed: this session ran as an independent
programmatic reviewer against a scratch artifact path; no work-thread saga
was scanned or minted.

Raw evidence run this session: all gates listed above green on the reviewed
tree (both interpreters); four live probe suites through real client and
module code; floor mutation attack on a scratch copy; upstream-clone digest
verification for every pin including byte-level transform check.

Review complete. Reviewer: ox-alpha. Reviewed revision: 08ab2de
(orch/orch-2026-08-22-unifi-cycle3). Outcome: repairs_requested.
