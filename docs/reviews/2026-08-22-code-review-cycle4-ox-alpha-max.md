# Scored code review — UniFi portability pilot, cycle 4 (post-repair, resynchronized)

Reviewer: ox-alpha (independent reviewer 2 of 2; different model/session from the
cycle-4 panel partner; unattended). Artifact built incrementally per brief.

Target: /Users/jefcox/workspace/infiquetra/infiquetra-agent-plugins,
branch orch/orch-2026-08-22-unifi-cycle3, HEAD 2bd0faf (candidate), working
tree clean, no untracked files. Delta audited: bdaa814..2bd0faf, 24 files,
+2647/-237. All findings bind to tree 2bd0faf.

Method: read all four contract files and the roster; read the three prior
cycles' reports as immutable evidence; independently re-derived every claim
from current source; verified against the real upstream clone on disk
(infiquetra-claude-plugins @ 0d81dd9a, fetched); ran every gate; ran live
defeat probes — stubbed 429s with both Retry-After forms through the REAL
client request path, floor-test drift/removal mutations and gate attacks on
scratch copies only (zero writes to the reviewed tree), credential-value and
persistence probes against the shipped modules, and first-hand probes of both
carried cycle-3 defects. One probe error of my own (unittest run from the
wrong cwd) was re-run correctly before concluding anything.

## Gates run on this tree (all executed this session)

- `python3 scripts/bundle_fleet_module.py --check` — PASS.
- `python3 scripts/check_repo.py` — PASS.
- `python3 scripts/check_compatibility_matrix.py` — PASS: three superseded
  matrices + current, binding intact.
- `--print-fingerprint` — 23 files, `cafe883671b6…d91d1`, equal to the
  current matrix record and the re-captured readback record.
- `python3 -m unittest discover -s tests` on default python3 — OK.
- `/opt/homebrew/bin/python3.12` (3.12.13, the REAL floor interpreter) —
  unittest 417 tests OK (1 skip = pytest-guard module); venv with
  requests+urllib3+pytest on the same interpreter — 441 passed,
  189 subtests passed. The floor is actually exercised.
- `python3 scripts/sync_vendor_source.py --source <upstream clone>
  --commit 0d81dd9a --check` — PASS exit 0 against the fetched clone.
- `git diff --check` — clean.


## Brief item 1 — Retry-After both forms, primitive AND both call sites: REPAIRED, bites end-to-end

Upstream pin moved to UniFi 2.0.1 (0d81dd9a). Both callers now read
`hint = _retry_backoff.parse_retry_after(resp.headers.get("Retry-After"))`
and raise `_RateLimited(hint)`
(plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:189,
plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py:189).
The `int()` that turned an HTTP-date into a status-less ValueError is gone.

Live probe this session (floor interpreter, stubbed `requests.request`,
REAL `_request` path of the network client; protect client lines identical):

- 429 + future HTTP-date → slept 60.0 s (hint clamped to max_delay) and
  retried to success on attempt 2.
- 429 + delta-seconds 120 → slept 60.0 (clamped), retried.
- 429 + past date (parses 0.0), malformed text, and absent header all fell
  back to computed jittered backoff (0.59–0.91 s observed), then retried.
- always-429 with a date hint → 3 attempts, sleeps [60, 60], then the typed
  surface: "Rate limited. Retry after N seconds", status_code 429,
  retry_after = ceil(hint).

The primitive is unchanged from cycle 3 and correct: both RFC 7231 forms,
past→0.0, unparseable→None, bool guard, zone-less asctime forced UTC
(plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:47-90).


Upstream inverted its characterization test rather than deleting it —
verified at 0d81dd9a:tests/test_retry_backoff.py:286 is now
`test_a_caller_that_pre_parses_with_parse_retry_after_keeps_the_retry`.
The ported copy still carries the OLD caller shape at
tests/test_retry_backoff.py:317; its digest matches the declared
`guard-pytest-import` v2 transform of the ed72f439 source exactly
(source 7d80f735… verified against `git show ed72f439`, output 8fa9cb06…
verified on disk), and the staleness is honestly queued with the custody
question framed (docs/engineering-journal/QUEUED.md:137-175). Custody-honest.

## Brief item 2 — Python floor python>=3.12: AGREES EVERYWHERE, gate bites, floor interpreter really runs

`PYTHON_FLOOR = (3, 12)` in tests/test_python_floor.py:55 is the single
authority. Declaration sites (ci.yml, README.md, DECISIONS.md, plan,
fleet-core README + CHANGELOG) all carry `python>=3.12`
(test_every_declaration_site_states_the_floor checks PRESENCE, not just
value, so deletion fails too). CI pins `'3.12'` and the step name must say
"Set up Python 3.12" (.github/workflows/ci.yml:53-56). Skill frontmatter:
absence allowed (byte-copy custody — queued upstream, QUEUED.md:33-71),
presence forced to equal the catalog floor. Fixture CONFORMANT_SKILL was
moved to 3.12 in this cycle so a test fixture cannot contradict the gate
(tests/test_check_repo.py:16-24).


DEFEAT PROBES (scratch copies under /var/folders/…/opencode, reviewed tree
untouched). I first got a false PASS here — my unittest ran from the repo cwd
instead of the scratch copy; re-run correctly before concluding:

1. ci.yml pin mutated to `'3.10'` → suite FAILED, naming the pin:
   "every python-version pin must be the floor 3.12; found ['3.10']".
2. fleet-core README token mutated to `python>=3.11` → FAILED:
   "plugins/fleet-core/README.md:48 declares python>=3.11".
3. Declaration deleted entirely → FAILED presence check:
   "these files must state the catalog floor … ['plugins/fleet-core/README.md']".

Stale-floor sweep: every remaining "3.10"/"or newer" occurrence in scanned
suffixes is deliberate history — preserved blockquotes in the plan's KTD7
amendment and fleet-core CHANGELOG, and narrative LEARNINGS entries the floor
module documents as exempt by design (test_python_floor.py:25-36).

## Brief item 3 — deterministic transforms and Fleet Core byte copy: VERIFIED against the upstream clone

- Upstream commit 0d81dd9a exists ("fix(unifi): parse both Retry-After forms
  at the call site, release 2.0.1 (#766)"); its parent is ed72f439.
- Both client source digests recomputed from `git show 0d81dd9a:…` equal the
  PROVENANCE source_sha256 values (network 9dcd6360…, protect 1ec114b4…).
- Diff of upstream vs shipped network client is EXACTLY the shim-block
  rewrite (6 lines); no other byte differs. Protect identical.
- `sync_vendor_source.py --check` against the clone at 0d81dd9a passes,
  which re-proves every byte copy and both transforms end-to-end.
- Fleet Core slice: retry_backoff.py sha256 5aea3be1… equals PROVENANCE and
  the upstream bytes at ed72f439; `git diff ed72f439 0d81dd9a --
  plugins/fleet-core` is EMPTY, so the two pins (0d81dd9a / ed72f439) name
  one consistent upstream state, exactly as plugins/fleet-core/
  PROVENANCE.json notes claim.
- Bundles: stamp-excluded payload of both `_bundled/retry_backoff.py` copies
  is byte-identical to the fleet-core source (check_repo two-domain check
  green; see tamper probe below for the failure direction).

## Brief item 4 — earlier repairs survived the resync: ALL PROBED, ALL BITE

1. Smuggled bytecode (scratch copy): seeded
   `plugins/unifi/skills/unifi-network/scripts/smuggled.pyo` with arbitrary
   bytes → `check_repo.py` exit 1 "unlisted package file … not classified by
   PROVENANCE.json"; matrix validator exit 1 with file_count/tree_sha256
   mismatch ("a digest that is merely well formed identifies nothing").
2. Tampered bundle (scratch copy): appended one comment line to the network
   client's `_bundled/retry_backoff.py` → check_repo reports BOTH domains:
   "stale bundle" (source-sha256) and "tampering" (output-sha256).
3. Credential value in a profile (live module, pure functions): baseline
   valid profile ACCEPTED; `password=hunter2` REJECTED naming
   `subjects[0].notes`; AKIA and JWT literals REJECTED by family; 64-hex
   digest, vault: reference, and `password=secret` ACCEPTED exactly per the
   documented defense-in-depth limit (pinned by tests/test_site_profile.py).
   The repo gate (check_repo CREDENTIAL families, unchanged) is pinned equal
   to the runtime copy.
4. Discovery persistence refusal (live module): inside PACKAGE_ROOT refused
   with no `.git` needed; from a genuinely gitless cwd under /private/tmp
   `repository_root_from()` returns None and `refuse_repository_output`
   raises `DiscoveryPersistenceError` naming `--repository-root`; nothing is
   written on any refusal path. C10 fail-closed survives the resync.
5. Unchanged-since-cycle-3 code re-checked for regression: drift policy
   observation (C2), sync path containment chokepoint (C8), six required
   stamp fields (C4) — none of these files are in bdaa814..2bd0faf; suite
   green.

## Brief item 5 — hunting "guarantees that exist but do not bite": what I found

The two blocking defects are closed (above). What remains is a quieter
version of the same pattern — records that no longer match reality:


## Findings (admitted, confidence >=75; sorted P0→P3 then confidence→file→line)

### P2

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-01 | plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py:76 | Carried cycle-3 F3, still present and still UNRECORDED: Claude loader accepts only schema 1.0 and has no credential-value rule while the portable contract is 1.1 with the value rule | security, api-contract | 100 | manual -> human |
| F-02 | plugins/unifi/scripts/site_profile.py:169 | Carried cycle-3 F4, still present and still UNRECORDED: assignment family grades only the first whitespace-bounded token, so `authorization: Bearer <opaque>` defeats value detection in both copies | security | 100 | gated_auto -> review-fixer |

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F-03 | docs/engineering-journal/QUEUED.md:5 | Stale P0 "Emit the declared Fleet Core bundle" says "No repair has begun"; the repair shipped in 4c1d30f, five minutes before the cycle-1 baseline | architecture-maintainability, documentation-clarity | 100 | safe_auto -> review-fixer |
| F-04 | docs/engineering-journal/QUEUED.md:208 | Stale P2 "Drop README.md from the UniFi byte-copy table" — already shipped (SUPERSEDED_BY_TARGET_OWNED present; tests assert it) | architecture-maintainability, documentation-clarity | 100 | safe_auto -> review-fixer |
| F-05 | plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:203 | NEW with this repair: non-finite Retry-After hints (`inf`/`nan`) parse as floats and crash `math.ceil` on retry exhaustion, degrading the typed 429 exit to a generic error | correctness, reliability | 100 | gated_auto -> review-fixer (upstream-first) |


### Advisory

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| A-01 | plugins/unifi/scripts/discover.py:287 | Environment observation: this host's TMPDIR contains a malformed `.git` skeleton (only `info/`, no HEAD); the bare `.git`-exists walk counts it as a repository root, unlike git itself. Safe direction (errs toward MORE refusal nearby); O6 test unaffected (/private/tmp is gitless and the shipped test fails loudly if no gitless root exists) | adversarial | 100 | advisory -> human |

### Detailed findings (per findings-schema.md)

#### F-01 — Claude-path loader lags the 1.1 contract, undisclosured (P2, pre_existing)

- severity P2; dimension_id secrets-cryptography-session-handling (also
  interface-contract-compatibility); critical false.
- file plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/
  site_profile_loader.py; line 76 (`SUPPORTED_SCHEMA_VERSIONS = ("1.0",)`).
- why_it_matters: The portable schema advertises `["1.0","1.1"]`
  (schemas/site-profile.schema.json:14) and references/site-profile.md:28-53
  states the credential-value rule runs in "the portable loader … that
  actually loads" profiles. On the Claude path neither is true: probed live
  this session — a valid inert 1.1 profile raises
  `UnsupportedSchemaVersionError: unsupported profile schema_version '1.1'`,
  and a 1.0 profile carrying `notes: "controller password=hunter2"` is
  ACCEPTED (no value rule). The portable loader does the exact opposite on
  the same documents. An operator authoring the documented 1.1 form breaks
  their Claude integration; one pasting a secret into notes is told the
  profile is fine on that path. No document or journal entry discloses the
  skew; no disposition of cycle-3's F3 exists anywhere in DECISIONS/QUEUED.
- why_it_matters: A real operator paste shape — `authorization: Bearer
  <40-char opaque token>` — passes validate_profile AND check_repo's gate,
  while the same token behind a bare key is rejected. Probed live this
  session: `authorization: Bearer qY7vP2xK9wMzT4rB8nQqZ3LmVvXxJj` ACCEPTED;
  bare `api_key=<same>` REJECTED naming the property. Detection inspects the
  wrong span — the miniature of the "checks names not values" pattern.
- evidence: regex at site_profile.py:169-174; skip at :451-452; live probes;
  cross-copy pin makes both copies identically affected; NO disposition or
  queued entry exists for it anywhere in docs/engineering-journal/.
- pre_existing true (introduced cycle 2/3, unchanged by this delta);
  requires_verification true.
- suggested_fix: Grade every whitespace-separated token of the assigned
  value against the entropy floor (or extend the capture across the full
  remainder when it starts with bearer|basic|token). Both copies plus the
  pin test in one change; site_profile.py and check_repo.py are both locally
  owned (target-owned / repo source), so no upstream trip is needed.

#### F-03 — stale P0 queued entry contradicts the shipped tree (P3, pre_existing)

- severity P3; dimension_id significant-decision-documentation (also
  documentation-clarity:shipped-behavior-parity); critical false.
- file docs/engineering-journal/QUEUED.md; line 5 (entry through line 32).
- why_it_matters: The top queue entry claims both skill entrypoints abort
  with ModuleNotFoundError, that "no bundle was ever written into the
  package", and stamps itself "**No repair has begun**." Every clause is
  false against this tree: commit 4c1d30f ("fix(unifi): give the portable
  package a working entrypoint", 2026-08-22 11:51, five minutes before the
  cycle-1 baseline 95de0d5) emitted both `_bundled/retry_backoff.py` copies,
  check_repo rejects a declared-but-missing bundle, test_client_entrypoints
  runs the shipped scripts, and the current matrix records successful
  --help invocation stages on all ten clients. An operator reading the queue
  would believe the package unusable and re-authorize finished work. The
  journal's own recorded convention says shipped entries move to ARCHIVE.md,
  "do not silently delete" — neither move nor archive happened. This is the
  same defect class as cycle-3 F5 (stale matrix-re-run P0), which was
  repaired by archiving; two sibling instances were missed by all three
  prior cycles.
## Lens selection (roster `lens_roster.v1`, bound to 2bd0faf)

Always-on run: architecture-maintainability, correctness, security, testing.
Conditional lenses SELECTED, one-line cause each:

- reliability — retry failure semantics at both caller sites changed; this
  is the cycle's core repair and its failure paths are load-bearing.
- api-contract — the Retry-After hint contract widened at the callers,
  manifest versions moved 2.0.0→2.0.1, and the loader/schema skew persists.
- adversarial — every new guarantee was attack-probed this session and the
  journal-vs-tree drift pattern was hunted specifically.
- deployment-infrastructure — evidence capture moved to the declared floor
  interpreter by explicit path and the readback was re-captured on fresh
  installs: deployed-state verification changed end to end.
- documentation-clarity — references, journal, and three evidence documents
  were rewritten or re-run; their parity claims are checkable.

Conditional lenses NOT selected (recorded cause): performance — no
latency/throughput/query/cost claim touched; privacy — no new personal-data
flow, site scan clean; agent-usability — no machine-read contract changed
shape, evidence re-runs reuse the existing validated schema;
previous-comments — no PR review threads exist; accessibility-human-usability
— no human-operated visual/keyboard surface changed.

## Lens scores — the gate (acceptance: derived_overall >= 9.0 AND every applicable dimension >= 7.0)

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| architecture-maintainability | fit/ownership 9; separation 10; dependency-direction 10; simplicity 9; readability 9; conventions/portability 10; decision-docs 8 | none | **9.29** |
| deployment-infrastructure | infra-config/least-privilege 9; migrations/rollout-order 9; rollback/drift 9; deployed-state-verification 10 | cost-resilience — no resource or cost surface in this delta | **9.25** |
| correctness | intent 9; state/invariants 9; boundaries 8; side-effects/lifecycle 8; caller-consumer-completeness 7 | none | **8.20** |
| security | input-boundaries 8; secrets 7; supply-chain 10; confidentiality 9 | authentication-authorization-tenant-isolation — no protected-operation surface touched by this delta | **8.50** |
| testing | requirements/regression 8; negative-edge/time 8; behavior-sensitive assertions 9; realistic-seams 9; determinism/isolation 9 | none | **8.60** |
| reliability | timeouts/retries/idempotency 9; concurrency/partial-failure 9; graceful-degradation/cancellation 8; health-signals 9 | queues-jobs-dead-letters-ordering-backpressure — no queue, job, ordering, or backpressure surface | **8.75** |
| api-contract | interface-compatibility 7; versioning 8; serialization/errors 8; retry-idempotency 9; pagination/rate-limits 9; spec/doc-parity 7 | sdk-generated-client-impact — no generated SDK surface | **8.00** |
| adversarial | load-bearing-assumptions 8; abuse-edge-cases 7; failure-amplification/silent-green 8; environment/operator-failure 8; scope-creep-risk 9; alternatives-considered 9; recovery 8 | none | **8.14** |
| documentation-clarity | shipped-behavior-parity **6**; completeness/audience 9; structure/navigation 9; terminology 9; runnable-examples 9; runbook-safety/drift 7 | none | **8.17** |
| performance | NOT SCORED — not selected (no latency, throughput, query, or cost surface) | — | — |
| privacy | NOT SCORED — not selected (no new personal-data flow) | — | — |
| agent-usability | NOT SCORED — not selected (no machine-read contract changed shape) | — | — |
| previous-comments | NOT SCORED — not selected (no PR review threads exist) | — | — |
| accessibility-human-usability | NOT SCORED — not selected (no human-operated visual surface) | — | — |

Gate arithmetic: SEVEN of nine scored lenses fail `derived_overall >= 9.0`
(correctness 8.20, security 8.50, testing 8.60, reliability 8.75,
api-contract 8.00, adversarial 8.14, documentation-clarity 8.17), and ONE
applicable dimension fails the floor: documentation-clarity
`shipped-behavior-parity` = 6 < 7.0 ("multiple instructions or claims
disagree with shipped behavior": the reference doc's loader claim plus the
two stale QUEUED entries, all verified false against the tree). The typed
outcome is therefore `repairs_requested` before any Priority is consulted.

#### F-05 — non-finite Retry-After hint crashes the typed 429 exit (P3, introduced by this repair)

- severity P3; dimension_id boundary-types-serialization-numeric-time (also
  graceful-degradation-cancellation-cleanup); critical false.
- file plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py;
  line 203 (`advice = 60 if exc.retry_after is None else
  math.ceil(exc.retry_after)`). Protect client identical (:203).
- why_it_matters: `parse_retry_after` reduces delta-seconds with
  `float(text)` (retry_backoff.py:81), and `float("inf")`, `float("nan")`,
  and `float("1e400")` are all valid parses returning inf/nan. Call path:
  `_do_request` raises `_RateLimited(inf)` at :189-190 → `retry_with_backoff`
  correctly retries (during retries `_retry_delay` clamps inf to max_delay
  via `min(max_delay, inf)` and fails `nan > 0` into computed backoff, so
  the retry loop itself is safe, :101-105) → after max_attempts the last
  exception re-raises → the client's except branch calls `math.ceil`:
  `ceil(inf)` raises OverflowError, `ceil(nan)` raises ValueError INSIDE the
  handler, escaping the typed surface into the generic handler.
- evidence: exact reproduction this session on the real client request path
  with `requests.request` stubbed to always answer 429: `Retry-After: inf`
  → 3 attempts, sleeps [60, 60], then "Unexpected error: cannot convert
  float infinity to integer", exit 1; `nan` → same shape with ValueError.
  The cycle-4 partner independently reproduced the identical behavior with
  `Retry-After: 1e400` — CONFIRMED against my reading: `float("1e400")`
  returns inf, so it is the same defect through a third spelling; both
  clients identical, all three inputs lose the typed 429 surface.
- reachability from a real controller: RFC 7231 delta-seconds is digits
  only, so `inf`/`nan`/`1e400` requires a broken or malicious intermediary,
  not standards-compliant behavior — hence P3, not P2. Pre-repair code also
  failed generically on these inputs (`int("inf")` ValueError), so severity
  is robustness polish of an adversarial input class, not a regression of
  previously-working behavior; but the reachable path IS new with this
  diff. pre_existing false. requires_verification true.
- suggested_fix (upstream-first; both clients are deterministic transforms,
  so no local edit): one line in fleet-commons `parse_retry_after` — return
  None when `not math.isfinite(value)` after the float parse — released
  upstream and resynchronized; alternatively guard the client advice line
  with `math.isfinite`. Assumption: primitive fix preferred so every
  consumer inherits it.

#### F-04 — stale P2 queued entry for already-shipped README custody work (P3, brief)

QUEUED.md:208-231 still asks to "drop README.md from the UniFi byte-copy
table" as pending work, but the work shipped during the cycle-2/3 repairs:
`PORTABLE_BYTE_COPIES` no longer contains README.md,
`SUPERSEDED_BY_TARGET_OWNED = ("README.md",)` exists
(scripts/sync_vendor_source.py:105), PROVENANCE classifies it target-owned,
and tests/test_unifi_readme.py plus the sync suite assert the protection.
The entry's own guard test is green. Same class and fix as F-03: archive
the complete entry with a "shipped" status per the recorded convention.
pre_existing true; safe_auto -> review-fixer; requires_verification false.

#### A-01 — ambient `.git` skeleton in TMPDIR counts as a repository root (advisory)

This host's `/var/folders/.../T` contains a malformed `.git/` (only
`info/`, no HEAD), so `repository_root_from()` (discover.py:283-289, bare
`.git`-exists walk) treats the temp tree as a repository working tree while
git itself says otherwise. Direction is safe — near such a tree refusal is
MORE likely, not less, and the undeterminable-tree fail-closed branch still
fires where no `.git` exists (probed). The O6 test is unaffected because it
searches /private/tmp and fails loudly if no gitless root exists. No action;
recorded so the ambient-state dependence is on file. advisory -> human.
## Built-vs-planned (compact) and scope check

Scope Check: CLEAN. Intent: repair cycle-3's two blocking defects at the
authoritative custody boundary, resynchronize, move the floor to 3.12,
re-run evidence. Delivered: exactly that; every changed file maps to one of
those or to preserved review records. COMPLETION (cycle-4 scope): blocking
repair 1 (Retry-After callers) DONE, probed end-to-end; blocking repair 2
(floor 3.12) DONE, agrees at all six declaration sites + CI + fixtures,
gate proven to bite, floor interpreter really runs the suite; resync DONE
(--check vs clone; fleet-core subtree byte-identical across both pins);
evidence re-run DONE (third run, bound to cafe8836/2.0.1); KTD7 CHANGED and
recorded with superseded rationale preserved; skill frontmatter
declaration NOT-DONE by custody design and honestly queued upstream.

## Outcome and routing

> **Plain answer: not yet safe to merge and release under the contract's
> own numbers — the outcome is `repairs_requested`.** Both cycle-3 blocking
> defects are genuinely fixed and verified end-to-end, no P0/P1 code defect
> exists in this delta, but seven of nine scored lenses sit below the
> derived-overall minimum of 9.0 and shipped records contradict verified
> reality in three places — and this repository's entire trust model is
> that its records match its tree.

schema: review_result.v1; best_available_revision: 2bd0faf; outcome:
`repairs_requested`; next_action: return_to_work.

Fix order (all small; none touches custody-controlled bytes except where
noted): 1. F-03+F-04 journal sweep — archive both stale entries with
shipped status, minutes, safe_auto. 2. F-02 span fix locally (both copies +
pin test, gated_auto). 3. Record written dispositions for carried cycle-3
findings so they stop vanishing between immutable reports and the journal.
4. F-01 upstream loader release decision (manual). 5. F-05 upstream
isfinite hardening (gated_auto, upstream-first). Then resubmit; with the
parity items landed every failing score's driver is gone and `accepted` is
the honest verdict.

Route: F-01 manual -> human; F-02 gated_auto -> review-fixer;
F-03/F-04 safe_auto -> review-fixer; F-05 gated_auto -> review-fixer
(upstream-first); A-01 advisory -> human. No saga write performed: this
session ran as an independent programmatic reviewer against a scratch
artifact path; no work-thread saga was scanned or minted.

Suppressed findings: 0. Residual risks: matrix binding remains identity-
not-execution (O7 Maybe, unchanged); committed __pycache__ content stays
invisible to gates (.gitignore stands between it and shipping, prior-cycle
advisory); low-entropy short secrets remain an admitted, pinned limit.

Raw evidence run this session: all seven gates listed above green on the
reviewed tree; six live behavior probes through real client/module code;
five defeat probes against scratch copies; two upstream-clone verifications.
One probe of mine initially mis-fired (unittest from wrong cwd) and was
re-run correctly before any conclusion was recorded.

Review complete. Reviewer: ox-alpha. Reviewed revision: 2bd0faf
(orch/orch-2026-08-22-unifi-cycle3). Outcome: repairs_requested.
