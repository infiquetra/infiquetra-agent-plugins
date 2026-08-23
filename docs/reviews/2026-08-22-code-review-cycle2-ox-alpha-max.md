# Scored code review — UniFi portability pilot, cycle 2 (post-repair)

Reviewer: ox-alpha (independent reviewer 2 of 2)
Repo: /Users/jefcox/workspace/infiquetra/infiquetra-agent-plugins
Branch: orch/orch-2026-08-22-unifi-repairs @ 2189be1

## Target and method

Reviewed revision: branch `orch/orch-2026-08-22-unifi-repairs`, working tree clean.
Brief says HEAD is `2189be1`; actual branch HEAD is merge commit `b4418a1`, whose
tree is byte-identical to `2189be1` (`git diff 2189be1 b4418a1` empty). All
findings bind to tree `2189be1`/`b4418a1`. Repair diff audited:
`95de0d5..b4418a1`, 22 files, +4701/−361.

Method: read every changed source file in full; read both prior reviewer reports
and the consensus as immutable evidence; independently re-derived each repair;
ran all repo gates; ran defeat probes against the new guarantees (hostile
manifests with absolute/traversal/symlink paths, no-git persistence, nested
manifest smuggling, credential values in profile free text). Two prior-cycle
empirical claims were re-executed rather than trusted.

Gates run on this tree: `check_repo.py` PASS, `check_compatibility_matrix.py`
PASS (both documents), `--print-fingerprint` = 23 files /
`6e6b57c1…8415` matching both the matrix record and the post-activation-readback
record, `bundle_fleet_module.py --check` PASS, unittest 373 PASS,
`git diff --check` PASS. **`sync_vendor_source.py --check` FAILS (exit 1)** —
finding F1 below, reproduced by execution.

## Repair verification — consensus findings C1–C10

| # | Claimed repair | Verdict from current source |
|---|---|---|
| C1 | Matrix bound to assessed tree | FIXED, bites |
| C2 | Drift false missing-policy | FIXED, bites |
| C3 | Provenance closed over package files | PARTIAL (escape hatch, F2) |
| C4 | Bundle stamp fields required | FIXED, bites |
| C5 | Portable README site-neutral | FIXED in tree; regression live-wire (F1) |
| C6 | Secret-free validation | PARTIAL — repo backstop added; profile contract unchanged |
| C7 | Retry-After HTTP-date form | NOT FIXED (pre-existing) |
| C8 | Provenance unlink escape | FIXED, bites (probed) |
| C9 | Post-activation proof | EVIDENCED + test-bound; runs remain external-state |
| C10 | Deny-list fails open without .git | FIXED, fails closed |

### C1 — matrix binding: FIXED

`scripts/check_compatibility_matrix.py:314-343` recomputes `(file_count,
tree_sha256)` from `plugins/unifi/` (sorted per-file sha256 lines, paths named
inside the hash so a pure rename is visible); `check_package_binding`
(`:364-412`) compares record vs recomputed count/digest/name/version.
Supersession is the only exemption and cannot be used to dodge the binding: a
superseded document whose fingerprint still matches the tree fails
(`:484-489`), status defaults to `current` (fail-closed, `:428`), and the
successor chain must end at a current matrix (`:468-476`). The pre-repair
matrix is preserved with its record byte-identical to `95de0d5` (verified) and
pinned by `tests/test_check_compatibility_matrix.py:922-928`. Live record
matches this tree (`--print-fingerprint` = recorded values). Defeat attempts:
decoy first json block is the record by design; hand-editing prose around it
changes nothing; refreshing numbers without re-running is blocked only for
accidental drift, not deliberate falsification — see F6.

### C2 — drift policy absence: FIXED

Discovery now labels its unobserved policy set:
`plugins/unifi/scripts/discover.py:147-156,482,641-642`. Drift derives absence
only from an affirmative observation: `drift.py:95-114` returns `observed` only
for non-empty observed identifiers or an explicit `policy_observation:
"observed"` declaration; `missing-policy` emission is gated on that at
`drift.py:173-185`, otherwise the gap is named in `limits` (`:142-143`). A
legacy bare `policies: []` inventory without the key stays unobserved — safe
backward direction. Full discovery→drift seam tested at
`tests/test_drift.py:237-257`; observed-empty still reports missing at
`:284-305`.

### C3 — provenance closed set: PARTIAL

Both directions now enforced: `_closed_set_errors`
(`scripts/check_repo.py:375-423`) rejects present-but-unlisted files and
duplicate paths; `_managed_package_files` (`:358-372`) enumerates the tree;
wired at `:462`. Tests cover unlisted/duplicate at `tests/test_check_repo.py`.
Escape hatch verified by probe: a file named `PROVENANCE.json` in a
subdirectory (exempt by *name* via `PROVENANCE_UNMANAGED_NAMES`, `:76,367`) and
a `.pyo` payload anywhere (exempt by suffix, `:78,369`) both ship with zero
errors from `check_provenance_manifests`. The exemption was designed for THE
manifest and interpreter noise but is applied by name/suffix at any depth —
finding F2.

### C4 — bundle stamp fields: FIXED

All six stamp fields required by name:
`check_repo.py:106-113,550-552`. Freshness comparison uses source-path +
source-sha256 (`:564-605`); a missing field is already reported before the
freshness skip at `:579-582` can matter, so deleting a stamp line no longer
disables the stale-source signal. Two digest domains remain independent;
hand-edited body still reports `stale bundle`.

### C5 — portable README: FIXED in tree

README rewritten site-neutral (`plugins/unifi/README.md:1-12`: "Portable Agent
Plugins 1.0 package… Claude-only files live under the client extension
directory"). Custody decision recorded with rejected alternatives in
`docs/engineering-journal/DECISIONS.md:5-41`; manifest reclassified
`target-owned` (digest removed); enforced by
`tests/test_unifi_readme.py:206-220` plus lede/link/test-path tests at
`:96-158`. The repair is real — but it leaves the generator contradicting the
recorded custody, which is finding F1.

### C6 — secret-free validation: PARTIAL

Repo-level backstop added: `check_repo.check_secret_free_values`
(`scripts/check_repo.py:785-817`) scans every file under `plugins/` for
credential *formats* everywhere and credential-key-plus-entropy assignments in
data/doc files (`:143-198`); wired into `check_repo` at `:830`. This protects
the public repository tree. It does NOT change the runtime contract the finding
was about: `plugins/unifi/scripts/site_profile.py` is untouched by this diff,
its docstring still claims "credentials are excluded by validation rather than
by convention" (`:8`), and `_credential_field` (`:311-327`) still inspects
property names only. Re-executed the original proof: `validate_profile`
accepts a profile whose `notes` is `"password=hunter2 and
api_key=AKIAIOSFODNN7EXAMPLE"` (exit OK, values preserved). Operator profiles
live outside this repo, so the repo scan never sees them. Carried as F3.

### C7 — Retry-After HTTP-date: NOT FIXED

No file in the retry path changed in `95de0d5..b4418a1`. Both clients still do
`int(resp.headers.get("Retry-After", 60))`
(`skills/unifi-network/scripts/unifi_network_client.py:176`, protect client
`:176`), and `plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:74-79`
still documents seconds-only hints. An RFC-valid HTTP-date raises ValueError
into the generic error branch instead of the typed 429 contract. Pre-existing;
consensus already routed it for repair; it did not ship in this cycle. Carried
as F4.

### C8 — provenance unlink escape: FIXED, bites

Single chokepoint `resolve_managed_path`
(`scripts/sync_vendor_source.py:553-568`) fails closed; lexical +
resolved-containment checks at `:521-550`; stale set fully read/validated
before any byte is written (`apply_plan`, `:674-704`; docstring `:677-679`).
Independent probes on a copied package: manifest naming an absolute path,
`../../VICTIM.txt`, and a symlink-escape `link/VICTIM.txt` each raise SyncError
before any write; the outside victim file survived. Tests cover the same trio
plus package-root and blank paths, and prove no write precedes refusal
(`tests/test_sync_vendor_source.py:503-590`).

### C9 — post-activation proof: EVIDENCED AND BOUND

New `docs/evidence/2026-08-22-unifi-post-activation-readback.md` records
installed-version/digest readback (Grok, Agy, Muse) and all three profile states
from installed copies (`:61-110`), with an honest "not proved" section
(`:120-127`). The record is machine-bound, not prose: fingerprint recomputed vs
tree in `tests/test_check_compatibility_matrix.py:948-964`; unit digests,
upstream-commit-vs-pin, redaction, and state assertions at `:966-994`. Recorded
fingerprint equals this tree. That the client runs happened as written is
external-state and stays unverifiable from any repo — noted in coverage, not a
finding.

### C10 — deny-list fail-open: FIXED

`refuse_repository_output` (`plugins/unifi/scripts/discover.py:300-343`) now
refuses when no repository root can be determined (`:330-337`) — the exact
fail-open case — and refuses inside the package dir with or without a checkout
(`PACKAGE_ROOT`, `:280,322-326`). Named `--repository-root` lifts the refusal
deliberately (`:327-328`). Branch tested via documented walk-neutralization
(`tests/test_discover.py:293-321`) plus named-root lift test (`:342-357`);
ambient `.git` hazard recorded in the test docstring. The walk's own gitless
None-return has no direct test — finding F5.

## Findings — this cycle

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F1 | scripts/sync_vendor_source.py:80 | Sync custody table contradicts recorded README custody; `--check` exits 1 at HEAD | correctness, architecture-maintainability, deployment-infrastructure | 100 | gated_auto -> review-fixer |
| F2 | scripts/check_repo.py:76 | Closed-set exemptions applied by name/suffix at any depth smuggle nested manifests and `.pyo` payloads | security, adversarial | 100 | gated_auto -> review-fixer |
| F3 | plugins/unifi/scripts/site_profile.py:311 | Profile validation still checks names not values; docstring overclaims (carried C6) | security, privacy | 100 | manual -> human |
| F4 | plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:176 | HTTP-date Retry-After still breaks typed 429 contract (carried C7) | reliability, api-contract | 75 | gated_auto -> review-fixer |
| F5 | tests/test_discover.py:293 | Gitless-walk negative case tested only via monkeypatch | testing | 75 | safe_auto -> review-fixer |
| F6 | scripts/check_compatibility_matrix.py:364 | Binding proves identity, not that stages ran; fabrication undetectable | adversarial | 75 | advisory -> human |

### F1 — sync custody table contradicts the recorded custody decision (P2)

- why_it_matters: The derivation tool for the package is broken at the reviewed
  revision and its write path would silently revert a shipped repair.
- evidence: Executed
  `python3 scripts/sync_vendor_source.py --source <sibling checkout>
  --commit 0eb1fe04… --check` on this tree: exit 1,
  "byte copy diverged from its source: README.md … repair belongs upstream" +
  "provenance manifest does not match the pinned commit". Root cause:
  `PORTABLE_BYTE_COPIES` still owns `README.md`
  (`scripts/sync_vendor_source.py:80`) while `plugins/unifi/PROVENANCE.json`
  records it `target-owned` and DECISIONS.md:5-41 records the custody change;
  QUEUED.md:101-109 queues the one-line fix. A real (non-check) run does not
  call `verify_plan`; `apply_plan` writes upstream bytes over the site-neutral
  README and rewrites the manifest before any in-run gate objects. Downstream
  detection then exists (`tests/test_unifi_readme.py`, matrix fingerprint), but
  only after the reversion.

- severity call: P2, not P1 — the failing direction is fail-loud, the silent
  reversion is caught downstream, and the residual is operator-recorded. It
  borders P1 because the candidate ships with a red primary gate for its own
  derivation workflow and a write-run regresses C5 before any gate fires.
- pre_existing: false (introduced by this repair cycle)
- requires_verification: true
- suggested_fix: Remove `"README.md"` from `PORTABLE_BYTE_COPIES`
  (`scripts/sync_vendor_source.py:80`) so `target_owned_paths` classifies it
  target-owned on the next sync, update `tests/test_sync_vendor_source.py`
  fixture expectations (README currently asserted as written byte copy,
  `:343-353`), and add a test that a resync preserves a site-neutral README.

### F2 — closed-set exemptions work at any depth (P2)

- why_it_matters: The C3 guarantee ("every path exactly one classification")
  can be bypassed by naming; an unclassified file ships in a derived package
  with all gates green.
- evidence: Probe on a synthetic package: `skills/nested/PROVENANCE.json`
  containing `{"evil": true}` and a root-level `payload.pyo` both present;
  `check_repo.check_provenance_manifests` returned `[]`. Cause:
  `PROVENANCE_UNMANAGED_NAMES`/`_SUFFIXES` match `relative.name` /
  `relative.suffix` anywhere in the tree
  (`scripts/check_repo.py:76-78,365-370`), not just the package-root manifest
  and interpreter cache locations. Same exemption shapes the sync script's own
  candidate filter (`scripts/sync_vendor_source.py:119-121,487-492`).
  `check_secret_free_values` still scans these files for credential formats,
  but arbitrary non-credential content passes.
- pre_existing: false; confidence 100; autofix_class gated_auto (tightens a
  validation contract); owner review-fixer; requires_verification true.
- suggested_fix: Treat any `PROVENANCE.json` below package root as an unlisted
  file error; exempt compiled bytecode only under `__pycache__/` or beside a
  matching `.py` source per PEP 3147. Add seeded tests for both smuggle shapes.

### F3 — carried C6: profile contract checks names, not values (P2)

- why_it_matters: Operators are told credentials are "excluded by validation"
  at the point where profiles are actually validated (operator machines); they
  are not.
- evidence: `plugins/unifi/scripts/site_profile.py:8` (docstring claim),
  `:311-327` (`_credential_field` recurses containers, reads keys only);
  re-executed proof this session: profile with
  `notes="password=hunter2 and api_key=AKIAIOSFODNN7EXAMPLE"` validates OK.
  New repo-level scan `check_repo.py:785-817` never sees operator profiles.
  Schema `plugins/unifi/schemas/site-profile.schema.json` still guards names
  only. The matrix-redaction half of C6 did improve: hostname allowlist,
  IPv6/compressed + dashed-MAC patterns, and credential-value redaction list
  (`scripts/check_compatibility_matrix.py:169-222,740-781`).
- pre_existing: true (file untouched by this diff); confidence 100;
  autofix_class manual; owner human; requires_verification true.
- suggested_fix: Narrow the site_profile.py guarantee to what is enforced
  ("credential-shaped field names are rejected; never put secrets in values")
  and add value-level detection for obvious assignments as defense in depth.

### F4 — carried C7: HTTP-date Retry-After unhandled (P2)

- why_it_matters: A standards-compliant rate-limited controller response
  produces one request, no backoff, and a generic error instead of the typed
  429 surface with retry-after semantics.
- evidence: `unifi_network_client.py:176` and `unifi_protect_client.py:176`
  both `int(...)` the header; `fleet_commons/retry_backoff.py:74-79`
  seconds-only; no date-form test in `tests/test_retry_backoff.py`. No retry
  path file changed in `95de0d5..b4418a1`.
- pre_existing: true; confidence 75; autofix_class gated_auto; owner
  review-fixer; requires_verification true.
- suggested_fix: Parse delta-seconds or HTTP-date (`email.utils.
  parsedate_to_datetime`) against an injected clock, clamp to max_delay, fall
  back to computed backoff on malformed values; add client-level tests for
  missing/numeric/date/expired/malformed.

### F5 — gitless-walk negative case untested (P3)

- why_it_matters: C10's fix is the branch that refuses when the walk returns
  None; the tests neutralize the walk itself, so the walk's own None path —
  the exact behavior the repair depends on — ships unexercised.
- evidence: `tests/test_discover.py:293-306` monkeypatches
  `discover.repository_root_from` to return None; no test drives a real
  gitless directory through it. This session's probe hit the hazard the
  docstring names: this machine's `TMPDIR` contains `.git`, so an unwary
  real-walk test would silently take the wrong branch.
- pre_existing: false (test added this cycle); confidence 75; safe_auto;
  owner review-fixer; requires_verification false.
- suggested_fix: Add a test that creates an isolated directory chain with no
  `.git` in any parent, chdirs there, and asserts
  `repository_root_from() is None` directly.

### F6 — binding proves identity, not execution (advisory)

The fingerprint check makes accidental drift impossible to miss: any package
byte change breaks matrix and readback records until they are re-bound. It
cannot prove the forty stages were actually re-run against the bound tree —
hand-editing the record's count/digest after a package edit passes every
check. The document's own framing ("re-run, not renumbered",
`check_compatibility_matrix.py:869-874` refuses a rewrite flag) is honest
about intent, but the guarantee is one-directional. Report-only residual for
the operator's trust model. advisory -> human.

## Scope Check: DRIFT DETECTED (evidence/process drift, no scope creep)

Intent: repair the twelve reconciled findings from cycle 1 without expanding
scope, and re-bind public evidence to the shipped tree.

Delivered: all ten consensus findings addressed or consciously dispositioned,
plus 4.3k lines of tests and validators; the sync custody table was left
contradicting the recorded README custody decision (queued, not done — F1).

Out-of-scope changes: none found; every changed file maps to a consensus
finding, its evidence re-run, or its tests. Requirements missing: none beyond
F1's queued line and the carried C6/C7 repairs.

## Built-vs-planned audit (repair-scope items)

Audited against `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md`
and `docs/engineering-journal/{DECISIONS,QUEUED}.md`, honesty rule applied
(handled != deliverable):

- R2/R4 (hermetic provenance, one classification per path) — DONE at package
  root, PARTIAL in depth: F2 exemption gap.
- R19/R35 (two digest domains, mandatory stamps) — DONE (`check_repo.py:106-113`).
- R14 (no credentials in profile) — PARTIAL: repo tree protected; runtime
  contract unchanged (F3).
- R22/R23/R43/R44 (ten-client evidence) — DONE for the shipped tree: record
  bound and matching (`--print-fingerprint` verified); stage execution itself
  external-state.
- R40/R41 (post-activation readback + three states) — DONE as evidenced and
  test-bound artifact; actual client runs UNVERIFIABLE from repo (external
  state), consistent with the plan's own evidence mode.
- Plan §"File custody" (README portable core, site-neutral) — DONE via
  target-owned decision; PARTIAL in tooling: F1 leaves generator on old rule.

COMPLETION (repair-scope items): 6 DONE, 2 PARTIAL, 0 NOT-DONE, 0 CHANGED,
1 UNVERIFIABLE (external-state runs).

## Lens selection and scores (roster lens_roster.v1, bound to b4418a1)

Always-on: architecture-maintainability, correctness, security, testing.
Conditional selected: deployment-infrastructure (provenance/evidence/release
gates materially changed); reliability (failure/retry paths reviewed, carried
C7); api-contract (drift/discover report shapes and README contract changed);
adversarial (load-bearing validators rewritten — the cycle's core surface);
documentation-clarity (README + both evidence documents rewritten);
agent-usability (drift/discover JSON gains fields agent consumers read).
Not selected — performance: no latency/throughput surface in diff;
accessibility-human-usability: no visual/keyboard/form/localization surface,
CLI help unchanged; previous-comments: no PR review threads exist.

Acceptance rule (roster): derived_overall >= 9.0 AND every applicable
dimension >= 7.0. Scores are means of applicable dimensions
(`review_consensus.py:1666`).

| Lens | Applicable dimension scores | Non-applicable cause | Derived overall |
|---|---|---|---:|
| architecture-maintainability | ownership 8; separation 9; dependency 9; simplicity 8; readability 9; portability 9; decisions 10 | none | 8.86 |
| testing | requirements 9; negative-edge 9; assertions 8; realistic-seams 8; determinism 9 | none | 8.60 |
| documentation-clarity | parity 8; completeness 9; structure 9; terminology 9; examples 9; runbook-drift 9 | none | 8.83 |
| agent-usability | reachability 9; discoverability 9; context 9; machine-output 8; bounded-op 9 | none | 8.80 |
| reliability | retries 7; partial-failure 9; graceful-degradation 9; health 9 | no queue/job/ordering/backpressure surface | 8.50 |
| adversarial | assumptions 8; abuse 8; silent-green 9; environment 8; scope 9; alternatives 9; recovery 8 | none | 8.43 |
| deployment-infrastructure | infra-config 9; rollout-order 8; rollback-drift 8; deployed-verification 8 | no cloud resource or cost surface | 8.25 |
| security | input-boundaries 8; secrets 7; supply-chain 9; confidentiality 9 | no authn/authz or tenant-isolation surface touched | 8.25 |
| correctness | intent 8; state-invariants 8; boundaries 8; side-effects 9; consumers 8 | none | 8.20 |
| api-contract | compatibility 8; versioning 9; serialization-errors 9; retry-semantics 7; spec-parity 8 | no pagination/rate-limit surface; no SDK/generated client | 8.20 |

Every applicable dimension clears the 7.0 floor — the cycle closed cycle 1's
floor violations — but no lens reaches the 9.0 derived-overall minimum, so no
lens is accepted. Failing rule on all ten lenses: `derived-overall-minimum`
only.

## Typed outcome

    schema: review_result.v1
    revision_binding: { best_available_revision: b4418a1 (= tree 2189be1) }
    selected_lenses / attempted_lenses: 10 (above)
    findings: F1 P2@100, F2 P2@100, F3 P2@100 (pre_existing), F4 P2@75
              (pre_existing), F5 P3@75, F6 advisory@75
    failing_lenses: all ten (derived_overall < 9.0; no dimension below 7.0)
    fix_requests: F1+F5 consolidated? No — disjoint paths, separate.
                  F1, F2, F4, F5 -> review-fixer; F3, F6 -> human
    outcome: repairs_requested
    next_action: return_to_work

`outcome: repairs_requested`. This is a materially better candidate than
`95de0d5`: nine of ten consensus findings verified fixed or evidenced, every
dimension floor now met, and the does-not-bite pattern specifically hunted —
the new gates were probed and bite. What remains is one repair-introduced seam
(F1), one depth gap in a new gate (F2), two carried repairs (F3, F4), one test
gap (F5), and one inherent-limitation residual (F6).

## Coverage

Suppressed count: 0. No finding fell below anchor 75 except none — all six
reported at 75+.

Residual risks: matrix/readback stage execution is external-state evidence
(F6); discovery persistence protects only the tree found from cwd or named via
`--repository-root` (documented escape hatch, `discover.py:317-337`; package
dir always protected); `TARGET_OWNED` classification records no digest by
design, so arbitrary mutable content is admissible under that label — nothing
this diff changed, noted for custody awareness.

Testing gaps: real-walk gitless case (F5); no client-level Retry-After header
tests (F4); sync fixture still asserts README as byte copy, encoding the
superseded custody rule (F1).

## Site-identifying content scan

Public-repo scan of `plugins/`, `docs/evidence/`, `schemas/` for RFC1918/
private IPv4, MAC forms, and non-example hostnames: no hits beyond documented
inert placeholders (`controller.example`, `example-site`, fixture
`00:00:00:00:00:0X` in tests). The new validators now enforce this class
mechanically (`check_compatibility_matrix.py:169-222`; `check_repo.py:143-201`
credential-value families). No leak found.

## Route

- F1, F2, F5 -> Work/review-fixer as structured fix requests (F1 first — it
  blocks the package's own derivation gate).
- F3, F4 -> carried manual/gated repairs from cycle 1; F4 pairs with the
  queued client-level retry tests.
- F6 -> operator awareness only.
- No saga write performed: this session ran as an independent programmatic
  reviewer against a scratch artifact path; no work-thread saga was scanned or
  minted.

Recorded ambiguity per unattended protocol: brief named HEAD `2189be1`;
branch HEAD is `b4418a1` with identical tree — reviewed the working tree and
bound all results to both identifiers above.

> Verdict: `repairs_requested` — close F1 (one-line custody-table fix plus
> fixtures), depth-fix F2, then resubmit; carried F3/F4 remain human-routed
> from cycle 1.
