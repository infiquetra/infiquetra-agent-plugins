# Scored code review — UniFi portability pilot, cycle 3 (post-repair)

Reviewer: ox-alpha (independent reviewer, unattended session)

Target: repo /Users/jefcox/workspace/infiquetra/infiquetra-agent-plugins,
branch orch/orch-2026-08-22-unifi-cycle3, HEAD bdaa814, working tree clean,
untracked files: none. Repair diff audited: b4418a1..bdaa814, 30 files,
+3540/-227. All findings bind to tree bdaa814.

Method: read the full repair diff; read both cycle-2 reports and both
consensus records as immutable evidence; independently re-derived every
repair from current source; ran all gates; ran execution probes against the
new guarantees (synthetic-package smuggle shapes for O1, credential-value
profiles for O2, a stubbed 429 with an HTTP-date through the real client
request path for O3, Python 3.10.20 import of the resynced bundle); verified
the Fleet Core resync against the actual upstream clone on disk, not against
the repo's own records.

## Gates run on this tree

- `python3 scripts/check_repo.py` — PASS.
- `python3 scripts/bundle_fleet_module.py --check` — PASS.
- `python3 scripts/check_compatibility_matrix.py` — PASS (current + two
  superseded matrices).
- `--print-fingerprint` — 23 files, `da46ca77…08c5`, equal to the current
  matrix record and the re-captured readback record.
- `python3 -m unittest discover -s tests` — 403 tests, OK (was 373).
- `git diff --check` — PASS.
- `sync_vendor_source.py --source <upstream clone> --commit ed72f439… --check`
  — PASS exit 0 (cycle-2 F1 is gone end-to-end).

## Repair verification — cycle-2 open items O1–O7 and the resync

| # | Item | Verdict from current source |
|---|---|---|
| O1 | Bytecode-suffix smuggle past both gates | FIXED for the standalone shape (probed); two narrow exemptions remain, see A1 |
| O2 | Profile validation checks values not just names | FIXED for the two documented families (probed); new gaps F3/F4 |
| O3 | Retry-After HTTP-date, primitive AND callers | PRIMITIVE FIXED; CALLERS NOT FIXED — carried as F2 |
| O4 | README byte-copy path overwrites portable README | FIXED, bites (probed end-to-end) |
| O5 | Sync custody table contradicts recorded custody | FIXED, single chokepoint added |
| O6 | Gitless-walk negative case untested | FIXED — real-walk test, no monkeypatch |
| O7 | Binding proves identity, not execution | Recorded as a limitation only, with a mutation-tested pin |
| — | Fleet Core resync to 0.25.1 (ed72f439) | GENUINE byte copy, verified against upstream clone |

### O1 — closed-set bytecode hole: FIXED for the standalone shape

`check_repo._is_interpreter_bytecode`
(scripts/check_repo.py:363-380) exempts `.pyc`/`.pyo` only under
`__pycache__` or beside a same-named `.py`; the matrix fingerprint dropped its
suffix exclusion entirely
(scripts/check_compatibility_matrix.py:101-111,315-320). Probe on a synthetic
package: `skills/nested/smuggled.pyo` with no sibling source is now reported
as `unlisted package file`, and the fingerprint moves for any suffix-only
file. Seeded at tests/test_check_repo.py:427-465 and
tests/test_check_compatibility_matrix.py:585-600. Residual exemption shapes
are advisory finding A1.

### O2 — profile value rule: FIXED for the documented families

`validate_profile` now runs `_credential_value`
(plugins/unifi/scripts/site_profile.py:455-478) over every string at any
depth, before version checks; two families mirroring the repo gate
(`CREDENTIAL_VALUE_FORMATS` :134-156, `CREDENTIAL_VALUE_ASSIGNMENT` :169-176,
entropy floor 2.5). Schema bumped to 1.1 with literal-format `not` patterns
(plugins/unifi/schemas/site-profile.schema.json:44-64); 1.0 documents stay
readable and are held to the same rule. Probes this session: AKIA key,
GitHub/JWT/Stripe formats, URL-embedded credentials, and
`password=hunter2` (2.81 bits/char) all REJECTED with a named property path;
a 64-hex digest, `vault:`/`env:` references, `${VAR}` placeholders and plain
prose all ACCEPTED. The low-entropy admitted limit is pinned by
tests/test_site_profile.py:336-345 so the wording cannot silently drift. A
cross-copy pin (tests/test_site_profile.py:624-651) locks the loader's
patterns, entropy floor, placeholder and reference rules to the repo gate's.
New gaps introduced alongside this repair are findings F3 and F4.

### O3 — Retry-After both RFC 7231 forms: primitive YES, callers NO

Primitive: `parse_retry_after`
(plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:47-90) reduces
delta-seconds and all three HTTP-date forms (IMF-fixdate, RFC 850, asctime)
to a non-negative delay, returns `None` for absent/malformed values, `0.0`
for past dates, guards `bool`; `retry_with_backoff` now parses raw hints via
it (:145-165) with an injected `now`. Probed live: future date → seconds
remaining; past date → 0.0 then computed backoff; malformed → None then
computed backoff; excessive date clamped to max_delay. Eighteen upstream
tests ported, including three parametrized date-form cases.

Callers: NOT fixed. Both clients still raise
`_RateLimited(int(resp.headers.get("Retry-After", 60)))`
(plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176 and
plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py:176). The
ValueError is raised while constructing the exception, before
`retry_with_backoff` is ever entered, so the new parser never sees a
date-form hint from its only two consumers. End-to-end probe this session:
a stubbed 429 carrying `Retry-After: Fri, 31 Dec 2100 23:59:59 GMT` through
the real network-client request path emitted
`Unexpected error: invalid literal for int() with base 10: …`, exit 1 —
no backoff, no typed rate-limit surface. Carried as finding F2. Upstream's
own fix (#765) touched only the fleet-core primitive; the upstream
plugins/unifi subtree did not change (verified: empty diff 0eb1fe04..ed72f439),
so custody requires an upstream client repair before a resync can carry it.

### O4 + O5 — README byte-copy table and custody contradiction: FIXED

`README.md` removed from `PORTABLE_BYTE_COPIES` and named in
`SUPERSEDED_BY_TARGET_OWNED` (scripts/sync_vendor_source.py:80-105), so
`classify_source_tree` still accounts for every upstream path without
copying it. New single chokepoint `stale_managed_paths` (:622-640) subtracts
the superseded set before deletion in BOTH `apply_plan` (:726-729) and
`verify_plan`, closing the worse-than-overwrite hazard where a tree whose
old manifest recorded README as a byte copy would have it unlinked outright.
Tests cover all three shapes: resync leaves portable README bytes untouched,
the old-manifest scenario does not delete it, and removing the superseded
entry re-triggers the closed-custody refusal
(tests/test_sync_vendor_source.py:486-584). Fixture witnesses were moved off
README onto CHANGELOG so assertions stay meaningful. Executed end-to-end
this session against the real upstream clone at the pinned commit: exit 0.

### O6 — gitless-walk refusal pinned by a real walk: FIXED

tests/test_discover.py:362-407 builds a genuine directory chain under a
verified-.git-free POSIX temp root, asserts `repository_root_from()` returns
None, and drives the REAL persistence decision to
`DiscoveryPersistenceError` naming `--repository-root`, with no file
written — no monkeypatch stand-in this time. If no gitless root exists on a
machine the test fails loudly with an explanation rather than silently
taking the wrong branch.

### O7 — binding proves identity, not execution: recorded as a limitation only

LEARNINGS gains "A bound digest names the tree, not the forty stages that
assessed it"; QUEUED records it under **Maybe**, explicitly refusing to add a
gate. tests/test_journal_o7.py (207 lines) pins the claims by content and —
critically — proves the checker FAILS when the sections are stripped
(:167-203), avoiding the cannot-fail-guard pattern. Advisory disposition
honored exactly as dispositioned.

### Fleet Core resynchronization to 0.25.1: genuine byte copy

Verified against the upstream clone on disk, not against this repo's own
records:

1. Commit ed72f439 exists upstream ("fix(fleet-core): parse both RFC 7231
   Retry-After forms in the shared backoff primitive (#765)"), its parent is
   0eb1fe04 (the prior unifi pin), and it IS the head of upstream main.
2. `git show ed72f439:plugins/fleet-core/scripts/fleet_commons/retry_backoff.py
   | sha256` = `5aea3be13ac4…e975`, byte-identical to this repo's
   plugins/fleet-core copy and to both bundle stamps' source-sha256 and
   output-sha256.
3. `git diff 0eb1fe04 ed72f439 -- plugins/unifi` is EMPTY: the unifi pin's
   move to ed72f439 with unchanged digests is truthful ("one revision names
   the corrected state of the whole port").
4. Bundles rebound (`bundle --check` PASS); matrix + readback re-run and
   bound to `da46ca77…08c5`, equal to the live fingerprint; the superseded
   pre-resync matrix is preserved whole with `matrix-status: superseded`.

## Cycle-1 consensus C1–C10: no regressions found

Re-checked for regression rather than re-derived from zero (all verified
fixed or dispositioned in cycle 2): C1 binding recomputes and now binds
`da46ca77…` (matrix tests re-bound, 115 PASS); C2 drift policy observation
untouched by this diff and its seam tests pass; C3 closed set strengthened
by O1; C4 stamp fields still all six required, new 0.25.1 stamps validate;
C5 portable README now protected through the sync path itself (O4/O5), not
only by the guard test that cycle 2 relied on; C6 repo gate intact plus the
new runtime value rule; C7 unchanged upstream-side, carried as F2; C8
containment chokepoint untouched, refusal tests pass; C9 readback re-captured
and re-bound rather than edited — exactly the process the binding exists to
force; C10 fail-closed branch retained, now with the O6 real-walk pin.

## Findings — this cycle

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F1 | plugins/unifi/skills/unifi-network/scripts/_bundled/retry_backoff.py:36 | Resynced bundle imports `datetime.UTC`; both client entrypoints and the ported test suite break on the declared Python 3.10 floor; the CI floor job goes red | correctness, deployment-infrastructure, api-contract | 100 | manual -> human |
| F2 | plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176 | Callers still `int()` Retry-After: HTTP-date kills retry + typed 429 contract at the only two consumers of the fixed primitive (carried O3/C7) | reliability, api-contract | 100 | gated_auto -> review-fixer |
| F3 | plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py:76 | Claude extension loader accepts ONLY schema 1.0 and has no value rule: a 1.1 profile is rejected on the Claude path while the new schema invites it | api-contract, security | 100 | manual -> human |
| F4 | plugins/unifi/scripts/site_profile.py:447 | Assignment family grades the first token after the separator, so `authorization: Bearer <opaque-secret>` defeats value detection in BOTH copies | security | 100 | gated_auto -> review-fixer |
| F5 | docs/engineering-journal/QUEUED.md:17 | Stale P0 entry claims eight matrix tests "are failing"; the re-run landed and all 115 pass — journal contradicts its own tree | documentation-clarity | 100 | safe_auto -> review-fixer |
| A1 | scripts/check_repo.py:392 | Advisory: residual closed-set exemption shapes (below) | security, adversarial | 75 | advisory -> human |

### F1 — resynced bundle breaks the declared Python 3.10 floor (P1)

- why_it_matters: The catalog documents a Python 3.10 floor and the CI
  `plugin-tests` job pins 3.10 precisely to exercise it
  (.github/workflows/ci.yml:45-51). After the resync, importing either
  client — or collecting the ported test module — raises ImportError under
  3.10: the entrypoints crash at startup for any 3.10 consumer and the
  repository's own floor-checking job cannot pass.
- evidence: `from datetime import UTC` at the fleet-core primitive
  (plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:28) and both
  bundled copies (:36); executed this session on Python 3.10.20:
  `ImportError: cannot import name 'UTC' from 'datetime'` for both paths;
  tests/test_retry_backoff.py:59 executes `_load()` at module scope, so
  pytest collection fails on 3.10 with pytest installed; both client entry
  scripts import their bundle at module scope.
- disclosed but shipped: CHANGELOG "Known issues", QUEUED P1 "Decide the
  Python floor the Fleet Core resync raised", LEARNINGS, and a PROVENANCE
  note all name it; the byte-copy rule forbids a downstream edit. Honest
  recording does not make a floor-breaking release candidate green.
- severity call: P1 not P0 — no data loss or security impact; every 3.10
  consumer hits it immediately in normal usage.
- pre_existing: false (introduced by this cycle's resync); confidence 100;
  requires_verification true.
- suggested_fix: Operator decision between two named options (QUEUED P1):
  author `timezone.utc` upstream, release, re-synchronize; or move the
  declared floor to 3.11 everywhere it is stated (changelog note, ci.yml
  pin, catalog docs) in one commit. Assumption: one of the two lands before
  this branch merges.

### F2 — carried O3/C7: date-form Retry-After still kills the caller path (P2)

- why_it_matters: A standards-compliant rate-limited controller response
  produces one request, zero backoff, and a generic error instead of the
  typed 429 contract — now with the irony that the primitive it calls was
  repaired this cycle.
- evidence: unifi_network_client.py:176 and unifi_protect_client.py:176;
  stubbed-429 probe output quoted above; primitive capability proven live
  but unreachable from callers; upstream plugins/unifi unchanged across the
  pin move.
- pre_existing: true (caller bytes unchanged since before cycle 2);
  confidence 100; gated_auto -> review-fixer; requires_verification true.
- suggested_fix: Upstream: replace `int(...)` with
  `parse_retry_after(resp.headers.get("Retry-After"), ...)` mapped into the
  typed error (keep an int-typed field for the message), then resync; add
  client-level header tests for missing/numeric/date/expired/malformed.

### F3 — Claude extension loader rejects the new schema version (P2)

- why_it_matters: The repair moved the portable contract to 1.1 and the
  published schema now advertises `["1.0","1.1"]`, but the Claude Code
  client extension ships its own loader as an upstream byte copy, pinned at
  `SUPPORTED_SCHEMA_VERSIONS = ("1.0",)` with no value rule
  (site_profile_loader.py:73-76). An operator authoring the newly documented
  1.1 profile gets `UnsupportedSchemaVersionError` from the Claude
  integration while the identical document validates cleanly through the
  drift/discover path — a two-client contract skew created by this diff.
  The guarantee is also silently weaker there: no credential-value rejection
  on the Claude path. references/site-profile.md:7-10 states the portable
  loader "is the code that actually runs when a profile is read" — false for
  Claude clients.
- evidence: Executed this session: claude loader on 1.0 inert ACCEPTED; on
  1.1 inert → UnsupportedSchemaVersionError; 1.0 with
  `notes: "password=hunter2"` ACCEPTED (no value rule); portable loader on
  the same document REJECTED it. Manifest classifies the loader an upstream
  byte copy (plugins/unifi/PROVENANCE.json:54).
- pre_existing: false (the skew is created by moving one side of a two-sided
  contract); confidence 100; manual -> human; requires_verification true.
- suggested_fix: Upstream: release the 1.1 loader + value families in
  plugins/unifi, then resync so both loaders move together; until then,
  word the reference doc to name the Claude-path limitation explicitly and
  keep proposals stamped 1.0 (discover.py already does,
  plugins/unifi/scripts/discover.py:521).

### F4 — scheme-word prefix defeats credential-value detection (P2)

- why_it_matters: The assignment family grades the FIRST token after the
  separator, which is where scheme words live. A real operator paste shape —
  `authorization: Bearer <40-char opaque token>` — passes validation in the
  runtime loader AND the repository gate, while the same token without the
  scheme word is rejected. Detection that inspects the wrong span is the
  cycle-1 "checks names not values" pattern in miniature.
- evidence: `CREDENTIAL_VALUE_ASSIGNMENT`
  (plugins/unifi/scripts/site_profile.py:169-176) captures group 2 as
  `[^\s"',;)}\]]{6,}` — terminated by whitespace, so only "Bearer"/"Basic"
  is graded; `_credential_in_text` (:447-453) skips on sub-floor entropy.
  Probed this session: `authorization: Bearer qY7vP2xK9…` ACCEPTED by
  validate_profile AND by check_repo.check_secret_free_values (.txt/.json);
  bare `api_key=qY7vP2xK9…` REJECTED. The cross-copy pin test makes both
  copies identically affected.
- pre_existing: false for the runtime copy (new this cycle); the repo-gate
  copy predates (cycle 2). confidence 100; gated_auto -> review-fixer;
  requires_verification true.
- suggested_fix: Grade every whitespace-separated token of the assigned
  value against the entropy floor, not only the first (or extend the match
  across the full remainder when it starts with a known scheme word:
  `bearer|basic|token`). Update the pin test and both copies in one change.

### F5 — stale P0 queued entry contradicts the tree (P3)

- why_it_matters: QUEUED.md's top P0 says "Eight tests … are failing, and
  they stay failing until this runs", but commit e4e076c ran exactly that
  re-run and all 115 matrix tests pass. A journal that asserts outstanding
  work which is already done trains the next reader to distrust it — the
  same factual-drift class this pilot polices everywhere else.
- evidence: docs/engineering-journal/QUEUED.md:5-38 present at HEAD with no
  completion marker; `python3 -m unittest tests.test_check_compatibility_matrix`
  → 115 tests OK this session; e4e076c is an ancestor of HEAD.
- pre_existing: false; confidence 100; safe_auto -> review-fixer;
  requires_verification false.
- suggested_fix: Delete the entry (or move a one-line completed note into
  DECISIONS/LEARNINGS refs) in the same style used for other closed queue
  items.

### A1 — advisory: residual closed-set exemption shapes

Probed this session on synthetic packages: (a) `helper.pyo` BESIDE a
classified `helper.py` still passes check_repo unclassified — the manifest
records the .py, arbitrary content rides in the .pyo; (b) any file NAMED
`PROVENANCE.json` at any depth remains name-exempt (:392), though unlike
before it now moves the fingerprint so the binding flags the drift; (c) a
committed `__pycache__/payload.pyc` is invisible to both the closed set and
the fingerprint — only `.gitignore` stands between it and shipping. All
three are deliberate, documented placements (PEP 3147 anchoring at
check_repo.py:363-380); none reproduces O1's original
arbitrary-depth-suffix hole. Report-only: tighten later if the threat model
grows, e.g. reject nested manifests outright.

## Scope Check: DRIFT DETECTED (process drift, no scope creep)

Intent: close cycle-2's O1–O7, resynchronize the Fleet Core slice to the
corrected 0.25.1 upstream release, and re-bind all public evidence to the
resynced tree.

Delivered: O1/O2/O4/O5/O6 fixed and probed; O3 fixed at the primitive only
(custody-honest, carried); O7 recorded as a limitation with a cannot-silently-
disappear test; resync verified byte-genuine; matrix and readback re-run,
re-bound to `da46ca77…08c5`, supersession chains intact.

Out of scope changes: none found — every changed file maps to an open item,
the resync, its evidence re-run, or their tests. Requirements missing:
nothing new; F5 is a bookkeeping slip inside work that WAS done; F1 is a
disclosed consequence of the resync awaiting an operator decision.

## Built-vs-planned audit (cycle-3 scope)

Grounded in docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md
plus the journal, honesty rule applied:

- R19/R35 (bundle stamps, two digest domains) — DONE for 0.25.1: stamps
  required, `bundle --check` PASS, source digest equals upstream bytes at
  the pinned commit (verified against the clone).
- R32 (Fleet Core derived under the same sync rule) — PARTIAL: extraction
  was mechanical (`git show <commit>:<path>`, digests recomputed) but via a
  manual workaround because sync_vendor_source.py has no Fleet Core target;
  honestly queued as P2 with the workaround documented.
- R43/R44 (ten-client evidence bound to shipped tree) — DONE: re-run bound
  to `da46ca77…08c5`; stage execution itself remains external-state (O7).
- R40/R41/R42 (post-activation readback + profile states) — DONE as
  re-captured artifact bound to the new tree; client runs stay UNVERIFIABLE
  from repo, consistent with plan evidence modes.
- R14 (secret-free contract) — DONE at the portable runtime for the two
  documented families; PARTIAL overall given F3 (Claude path) and F4 (span).
- Plan §File custody (README target-owned) — DONE including tooling: the
  generator now agrees with the recorded decision (cycle-2's F1 closed).

COMPLETION (cycle-3 items): 5 DONE, 2 PARTIAL (R32 tooling, R14 residuals),
0 NOT-DONE, 0 CHANGED, 1 UNVERIFIABLE (external-state client runs).

## Lens selection (roster lens_roster.v1, bound to bdaa814)

Always-on: architecture-maintainability, correctness, security, testing.
Conditional selected, with cause:

- deployment-infrastructure — release/bundle re-binding and the resync
  rollout changed deployed-state evidence end to end.
- reliability — the retry primitive's failure semantics changed; the caller
  failure path is this cycle's carried defect.
- api-contract — schema 1.0→1.1 version bump, Retry-After contract, README
  and reference contracts all changed.
- adversarial — load-bearing validators rewritten again; every new guarantee
  was probed for defeat.
- documentation-clarity — README, reference doc, changelog, journal, and two
  evidence documents materially rewritten.
- agent-usability — drift/discover JSON, profile schema, and evidence
  records are machine-read surfaces agents consume.

Not selected: performance (no latency/throughput/cost surface in the diff);
privacy (no new personal-data flow; site scan clean); previous-comments (no
PR review threads exist); accessibility-human-usability (no human-operated
visual/keyboard surface changed).

Acceptance rule (roster): derived_overall >= 9.0 AND every applicable
dimension >= 7.0; derived overall = mean of applicable dimensions.

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| architecture-maintainability | ownership 9; separation 9; dependency 9; simplicity 8; readability 9; portability/config 7; decisions 10 | none | 8.71 |
| testing | requirements 8; negative-edge 9; assertions 9; realistic-seams 8; determinism 9 | none | 8.60 |
| documentation-clarity | parity 7; completeness 9; structure 9; terminology 9; examples 9; runbook-drift 9 | none | 8.67 |
| deployment-infrastructure | infra-config 7; rollout-order 9; rollback-drift 9; deployed-verification 9 | no cloud resource or cost surface | 8.50 |
| agent-usability | reachability 7; discoverability 9; context 9; machine-output 8; bounded-op 9 | none | 8.40 |
| security | input-boundaries 8; secrets 7; supply-chain 9; confidentiality 9 | no authn/authz or tenant-isolation surface touched | 8.25 |
| reliability | retries 7; partial-failure 9; graceful-degradation 8; health 8 | no queue/job/ordering/backpressure surface | 8.00 |
| adversarial | assumptions 7; abuse 8; silent-green 8; environment 7; scope 9; alternatives 9; recovery 8 | none | 8.00 |
| correctness | intent 8; state-invariants 9; boundaries 7; side-effects 8; consumer-completeness 6 | none | 7.60 |
| api-contract | compatibility 7; versioning 9; serialization-errors 8; retry-semantics 7; pagination/rate-limits 7; sdk-client-impact 7; spec-parity 7 | none beyond those scored | 7.43 |

Dimension-floor note: correctness FAILS the applicable-dimension floor —
`caller-enum-consumer-completeness` = 6 (band "several consumers
demonstrably inconsistent with the changed contract": both clients lag the
repaired primitive, the Claude loader lags schema 1.1). Every other
applicable dimension clears 7.0; no lens reaches the 9.0 overall minimum.

## Typed outcome

    schema: review_result.v1
    revision_binding: { best_available_revision: bdaa814 }
    selected_lenses / attempted_lenses: 10 (above)
    findings: F1 P1@100; F2 P2@100 (pre_existing); F3 P2@100;
              F4 P2@100 (runtime copy new, gate copy predates);
              F5 P3@100; A1 advisory@75
    failing_lenses: all ten on derived-overall-minimum;
                    correctness additionally on dimension floor
                    (caller-enum-consumer-completeness 6 < 7.0)
    fix_requests: F2, F4 -> review-fixer (gated_auto);
                  F5 -> review-fixer (safe_auto);
                  F1, F3 -> human (upstream-custody decisions);
                  A1 -> operator awareness
    outcome: repairs_requested
    next_action: return_to_work

`outcome: repairs_requested`. This is a better candidate than b4418a1 —
five of seven open items closed and probed, the resync byte-genuine, all
evidence re-bound by re-running rather than renumbering — but it ships a
floor-breaking bundle (F1), its repaired primitive has no working consumer
for the date form (F2), and the schema version bump left one shipped loader
behind (F3). The consumer-completeness pattern the brief asked me to hunt
is present in exactly those three places.

## Coverage

Suppressed count: 0; every reported finding is at anchor 75 or above.

Residual risks: matrix/readback stage execution remains external-state
(O7, recorded as a limitation with a mutation-tested pin); committed
`__pycache__` content is invisible to both gates and rests on .gitignore
(A1c); low-entropy short secrets in free-text values remain outside every
guarantee by documented design (pinned by test); TARGET_OWNED records no
digest by design, unchanged from cycle 2.

Testing gaps: client-level Retry-After header tests (F2); no parity test
pinning the Claude extension loader's schema versions to the portable
loader's (F3 — the existing cross-copy pin covers credential families
between the repo gate and the PORTABLE loader only); no whitespace-token
entropy cases for the assignment family (F4).

## Site-identifying content scan

Diff-wide scan for RFC1918/private IPv4, MAC forms, real hostnames, and
credential formats: only inert example values
(`AKIAIOSFODNN7EXAMPLE`, `controller.example`, fixture MACs). The new
validators enforce this class mechanically and pass. No leak found.

## Recorded ambiguities (unattended protocol)

1. The brief said "verify … O3 Retry-After — both RFC 7231 forms, at the
   primitive AND at the callers", implying both were in repair scope; only
   the primitive moved. I recorded the caller half as carried F2 rather
   than assuming the brief was wrong about intent.
2. Cycle numbering: the tree contains two "cycle 2" generations of reports;
   this review treats `2026-08-22-code-review-cycle2-*` + their consensus as
   the cycle-2 record per the brief, and binds to bdaa814 as cycle 3.
3. F4 severity: the documented contract already disclaims bare high-entropy
   scanning; I report the span-grading weakness as P2 because the detector
   inspects the wrong span of a matched assignment — an implementation gap,
   not a documented limit. If the operator judges it covered by the
   defense-in-depth disclaimer, downgrade to advisory without renumbering.

## Route

- F1, F3 -> human: upstream-custody decisions (floor move vs upstream
  repair; loader release vs doc wording), both already framed as options in
  QUEUED.
- F2, F4 -> Work/review-fixer as gated fixes (F2's code change lands
  upstream first, then resync).
- F5 -> review-fixer, one-line journal cleanup.
- A1 -> operator awareness only.
- No saga write performed: this session ran as an independent programmatic
  reviewer against a scratch artifact path; no work-thread saga was scanned
  or minted.

> Verdict: `repairs_requested` — decide F1/F3 custody questions, land F2/F4
> with their tests, sweep F5, then resubmit. No new cannot-fail gates found
> among the repairs themselves: every new guarantee probed this session
> failed for the right reason under attack except where noted (A1, F4).

Review complete. Reviewer: ox-alpha. Outcome: repairs_requested.
