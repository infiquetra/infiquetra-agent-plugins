---
title: Mission-control portable-port migration run plan
type: feat
status: active
date: 2026-08-24
origin: infiquetra/infiquetra-agent-plugins#9
runbook: docs/runbooks/portable-plugin-port.md v1.0.0
backend: inline
---

# Mission-control portable-port migration run plan

## Summary

Execute the operator-approved migration contract in parent issue
[infiquetra/infiquetra-agent-plugins#9](https://github.com/infiquetra/infiquetra-agent-plugins/issues/9):
port the Claude Code `mission-control` plugin (upstream
`infiquetra/infiquetra-claude-plugins`, pinned commit
`84eaf042f0e350005f7eddf8e7d80da25c12119d`, plugin version 2.12.2) into a
portable Agent Plugins package under `plugins/mission-control/`, following
runbook v1.0.0 (`docs/runbooks/portable-plugin-port.md`). This plan refines the
ten contract units #10–#19 — smallest viable change, mechanism reused, new
moving parts, rejected alternatives — inside the contract's dependency graph,
landing model, worker pools, and review contract, none of which it redesigns.

## Problem Frame

Parent #9 and children #10–#19 are the complete, operator-approved execution
contract; each child is a plan-ready card with bounded files, acceptance
criteria, and verification. What the contract deliberately leaves to Saga Plan
is the per-unit engineering record its S1 row requires: for every unit, the
smallest viable change, the existing repository mechanism reused, any new moving
part named with the current in-scope failure it prevents, and any larger
alternative deliberately rejected. That record — plus the handful of design
choices the children name but leave open (transform-rule shape, rule-selection
mechanism, frontmatter-fold target, CI path wiring, authority-derivation
locality) — is this document. Every load-bearing citation in the children was
re-verified against the working tree and the pinned upstream commit during
planning (see the unit records below).

## Execution contract carried forward (fixed, not revisited)

These are contract terms this plan executes and must not redesign:

- **Pinned source**: upstream commit `84eaf042f0e350005f7eddf8e7d80da25c12119d`
  (verified present in the read-only upstream checkout, dated
  2026-08-24 12:40:15 -0400). The upstream repository is never edited; defects
  found there are filed by U9 and return only through a deliberate repin +
  resync. Fleet-core expands at its own existing pin `3b5faa6c` (no repin —
  `intent_envelope.py`, `tier_palette.py`, and `models.json` are byte-identical
  between the two pins; `retry_backoff.py` differs, so a repin would churn
  UniFi's bundles and invalidate its committed matrix).
- **Landing model**: U0, U2, the single U8 integration PR, and U9 land on main
  as their own green PRs, serialized in that order. U1, U3, U4, U5, U6, U7 merge
  serially in unit order into integration branch `port/mission-control`, which
  rebases onto main after U2 lands and again before freeze. Intermediate branch
  states may fail only the named package-completeness checks until the owning
  lane lands; the assembled branch is fully green from U6 onward.
- **Custody and resync**: the portable copy is a derived artifact, never a
  second writable source. A needed byte change in copied content is an upstream
  filing, never a downstream patch.
- **GitHub mutation boundary**: build, tests, and assessment touch no live
  GitHub. The run's only writes are branch pushes and PRs in this repository,
  the U9 issue filings upstream, and board Status updates through the
  certificate-gated reconcile path — which the **coordinator owns**, not the
  units and not this plan session.
- **Review contract**: exactly one Saga Code Review process per unit at its
  frozen head — Grok 4.6, `--reasoning-effort xhigh`, grok.com login, max 4
  concurrent review controllers (review-only pool) — plus one integration
  review of the frozen merged revision at U8. Three-cycle cap with typed
  outcomes; `cycle_cap_best_available` discloses residuals and does not block;
  `repairs_requested` / `review_incomplete` block the merge.
- **Worker pools and caps**: Qwen (max 4) → OpenCode Muse (max 4) → Antigravity
  (max 4), deterministic dispatch, ready units assigned in group order then unit
  id. Grok appears in no dispatch decision. Workspace cap 6 sessions.
- **Proportionality**: smallest change satisfying the unit's acceptance
  criteria; a new abstraction is permitted only when the unit names the current
  in-scope failure it prevents.

## Requirements

- **R1.** All ten units land per the landing model with base SHA, frozen
  reviewed SHA, and merged SHA recorded per unit; no unit merges without its
  concluded review.
- **R2.** At final HEAD: `python3 scripts/check_repo.py`,
  `python3 -m unittest discover -s tests -v`,
  `python3 -m pytest plugins/mission-control/tests -q` (floor interpreter,
  PyYAML present), and `git diff --check` all green.
- **R3.** One committed, fingerprint-bound ten-client compatibility matrix and
  one readback for mission-control pass
  `python3 scripts/check_compatibility_matrix.py`; one mutation proof per rule
  copy, bound by test to the committed blobs; provenance digests equal to source
  for every byte-copied path.
- **R4.** Upstream custody intact: `84eaf042` recorded in
  `ports/mission-control.json` and `plugins/mission-control/PROVENANCE.json`;
  zero edits in the upstream checkout; the four audited upstream defects filed
  by U9 with URLs recorded.
- **R5.** No live GitHub call from any build, test, or assessment step; any
  observed attempt is a run-level stop.
- **R6.** Backend `inline` for every unit; worker bindings per the table below;
  no vendor concurrency cap exceeded; no invented work to fill idle slots.
- **R7.** Same-commit engineering-journal entries for every non-obvious decision
  or mechanism a unit ships (journal standard), and the runbook version (1.0.0)
  recorded in the closeout.
- **R8.** Closeout cleanliness: primary checkout clean and synced, run-created
  worktrees/branches/sessions removed, parent closing comment carrying the full
  per-unit evidence set.

## Key Technical Decisions

These are the plan-level refinements inside the contract. Contract-fixed
decisions (pin, landing model, review vendor, pools) are carried above, not
restated here.

- **KTD1 — Two new single-shape transform rules; `resolve-bundled-fleet-module`
  v1 stays frozen.** Verified at the pin: `executor_profile_lint.py` carries a
  module-scope `sys.path.insert` + `import fleet_commons_shim` block (line 35)
  with `.load("tier_palette")` far away at line 89, while `sdlc_manager.py`
  carries a function-scope, `if`-guarded insert + import + `.load("intent_envelope")`
  triple at lines 4283–4287. Neither matches v1's single contiguous three-line
  shape (`scripts/sync_vendor_source.py:233`). U3 adds two new named rules, one
  per shape, each preserving exactly-one-match discipline in its file, and
  leaves the existing v1 rule byte-untouched. Failure prevented: a multi-shape
  "v2" of the existing rule would loosen the exactly-one-match discipline and
  change the recorded transform identity UniFi's committed provenance names,
  making a future UniFi resync non-byte-stable. Rejected: one loosened
  multi-shape rule; "first match" semantics (a #13 stop condition).
- **KTD2 — Transform-rule selection lives in the port descriptor, at a new
  schema version 3** *(corrected in the S3 disposition pass per doc-review F1)*.
  AGENTS.md places porting-tool package configuration in the descriptor, "never
  as a constant inside a script." U3 adds an explicit per-path rule-name field
  to the descriptor's entrypoint-transform entries and bumps the descriptor
  format to version 3, because the format authority itself mandates it:
  `scripts/port_config.py:54` — "Bumped when a descriptor field is added,
  removed, or reinterpreted" — and its loader refuses any version it does not
  understand. In the same U3 commit: `SCHEMA_VERSION` moves to `"3"`,
  `ports/README.md` documents the field and version, both descriptors migrate
  (`ports/unifi.json` gains its explicit rule name and the new version), and
  `tests/test_port_config.py` derives the new expectations. Descriptors live
  outside package trees, so neither package fingerprint moves. Failure
  prevented: two incompatible descriptor shapes sharing one version number, and
  a script-internal path→rule registry constant recreating the custody
  violation AGENTS.md names. Rejected: keeping `schema_version` `"2"` by
  analogy to the compatibility-matrix precedent (a different document under a
  different authority); registry constant in `sync_vendor_source.py`.
- **KTD3 — `normalize-skill-frontmatter` v1 folds `when_to_use` under the
  permitted `metadata` key.** All seven upstream `SKILL.md` files carry
  `when_to_use:` (verified at the pin), which `check_repo.py:123–130` refuses;
  `metadata` is one of the six permitted fields. The transform moves the key
  under `metadata` deterministically and idempotently, portable copies only —
  upstream keeps the functional Claude Code field. Failure prevented: every
  byte-copied skill failing `check_skill_frontmatter` on the assembled branch.
  Rejected: folding into the document body (lossy placement, harder idempotence
  check); normalizing upstream (`when_to_use` is functional in Claude Code skill
  listings — the contract's recorded rejection).
- **KTD4 — CI package-test wiring by `plugins/*/tests` glob; the
  empty-collection failure is closed in the job's own command shape** *(narrowed
  in the S3 disposition pass per doc-review F6)*. U6 points the `plugin-tests`
  job (`.github/workflows/ci.yml:38`) at the `plugins/*/tests` pattern upstream
  itself uses, adds `pyyaml` to the install line, and resolves the
  exit-status-5 tolerance in the final command shape so an empty collection for
  a package that declares tests fails the job (#16's criterion). A separate
  path-agreement check is added only if a concrete shell-expansion or
  collection failure remains once that command shape is written. Failure
  prevented: a future port's tests silently never running. Rejected:
  per-package path enumeration (the next port edits CI again and reintroduces
  the silent-miss window); an unconditional second checker duplicating the
  glob.
- **KTD5 — Card-validator verdict agreement derives the authority live, with a
  loud self-skip.** The authority for `validate_card_body` is
  `home-lab/ansible/roles/hermes_orchestrator/files/card_validator.py`, an
  external repository. U7's verdict-agreement test locates the authority
  checkout (environment override, then the known sibling path), derives verdicts
  from it at test time, and self-skips with an explicit reason when absent
  (mirroring `test_template_sync.py`'s convention) — the run machine has the
  checkout, so the agreement leg executes during this run; a skip is recorded in
  the unit PR, never read as a pass. Failure prevented: a copied-constant corpus
  that cannot fail when the authority moves — the exact "verification that
  reports success for an unrelated reason" failure class. Rejected: vendoring a
  second authority copy here (a third copy that can disagree).
- **KTD6 — U0 also corrects `docs/README.md`.** Verified during planning:
  `docs/README.md:12` repeats the stale "paused for an operator decision" claim
  that `README.md:15` carries. The child made this conditional on inspection;
  inspection is done, so U0's scope includes the minimal matching correction.
- **KTD7 — U1 authors the descriptor at current schema 2; U3 owns every
  schema-touching edit.** `ports/mission-control.json` is written twice on the
  branch (U1 authors it; U3 adds the rule-name references). The units are
  already serialized (U1 merges before U3 starts), and the boundary is: U1 never
  anticipates the rule-selection field, U3 never revisits custody classes.
  Failure prevented: two writers designing one schema in parallel worktrees.
- **KTD8 — the mission-control fleet-commons closure is three files, and
  `intent_envelope.py` ports as a recorded deterministic transform** *(added
  2026-08-24: the first U2 dispatch stopped on child #12's stop condition
  item 1 — evidence `.orchestrate-unit-blocked.md`, sole commit `68cf5fc` on
  `orch/mcport-9-resume1-u2-fleetcore-q1`, coordinator-verified read-only
  against the pins)*. Verified at `3b5faa6c`, byte-identical at `84eaf042`:
  `intent_envelope.py` carries a module-scope `sys.path` insert plus
  `import fleet_commons_shim` (lines 79–83) and lazy
  `fleet_commons_shim.load("tier_resolver")` / `.load("tier_palette")`
  (lines 166/170); `tier_palette.py` reads its sibling `models.json` at import
  time (lines 26, 78), and `models.json` is a deferred data file the original
  two-module slice omitted. Consumer reachability at `84eaf042`:
  `sdlc_manager.py` touches only the envelope parse/render surface
  (`envelope_from_issue_body`, `apply_answers`, `render_issue_block`,
  `IntentEnvelopeError`), and `IntentEnvelope.validate()` →
  `SpendEnvelope.validate()` reaches `_tier_palette()` whenever a parsed
  envelope carries `spend_envelope.tier_ceiling` — so `tier_palette` and
  `models.json` are reachable on the shipped path; `executor_profile_lint.py`
  loads `tier_palette` directly (line 89). `recommend_tier` /
  `self_select_posture` / `authorize_spend` have zero callers in either
  consumer, so the `tier_resolver` leg (and `tier_policy.json`) is dormant
  and stays in `DEFERRED.md`. Decisions: (1) U2's slice is three files —
  `intent_envelope.py`, `tier_palette.py`, `models.json` — three
  `DEFERRED.md` rows out, three `PROVENANCE.json` entries; (2)
  `tier_palette.py` and `models.json` stay pure byte copies — the sibling
  data file satisfies the import-time read in `fleet_commons/` and in any
  `_bundled/` destination alike; (3) `intent_envelope.py` ports under
  fleet-core's existing `deterministic-transform` custody class (precedent:
  `guard-pytest-import` v2 in `derived_files`) with a new named rule
  `resolve-fleet-commons-sibling` v1 that replaces the module-scope shim
  block and the two `fleet_commons_shim.load("<name>")` call sites with
  same-directory sibling resolution — placement-independent by construction,
  so the identical transformed file works in `fleet_commons/` and in U5's
  `_bundled/`; a deferred name (`tier_resolver`) fails at call time naming
  the missing sibling path; source and result digests recorded; (4) the
  directed byte-port of upstream `tests/test_intent_envelope.py` is
  impossible as specified — the file imports saga, team-execution, and
  mission-control surfaces at module level, exercises saga-only re-export
  APIs (`seeded_tier`, `compute_stakes`), and carries a repo-tree drift
  guard — so the suite stays upstream and U2 authors minimal target-owned
  tests instead; (5) KTD1's two entrypoint rules and the
  `fleet_commons_shim.py` drop-from-source stand unchanged — U3's
  `git grep fleet_commons_shim plugins/mission-control/scripts/` verification
  still ends empty, because the bundled modules carry sibling resolution, not
  shim references. Failure prevented: shipping a module that cannot be
  imported anywhere in the target — the exact defect class the UniFi pilot
  shipped and the AGENTS.md runnability rule exists to prevent. Rejected:
  porting the full tier closure (`tier_resolver.py`, `tier_policy.json`) —
  zero callers, speculative; a target-owned `fleet_commons_shim.py` adapter
  under the upstream name — a second implementation under an upstream-custody
  name, the divergent-source failure the custody model exists to prevent;
  byte-copying `intent_envelope.py` unchanged — cannot import; repinning —
  the closure is byte-identical at both pins, so a repin buys nothing and
  regenerates UniFi's bundles. Revisit when: mission-control's upstream
  consumption starts calling a `tier_resolver`-backed API — the leg then
  joins the slice by this same mechanism.

## Worker bindings and backend

Backend is **inline** for every unit (operator-decided for this run; recorded in
this plan's frontmatter). Bindings carry the contract's deterministic dispatch
rule: with this graph the ready-unit count never exceeds 3, so every
implementation unit lands on Qwen; Muse/Agy engage only if more than 4 genuinely
independent units are ready simultaneously, which the graph does not produce.
Grok is review-only and appears in no dispatch decision.

| Role | Binding | Effort authority | Cap |
| --- | --- | --- | --- |
| Every implementation unit U0–U9 | Qwen, pinned `qwen3.8-max-preview` (template T2) | xhigh via `~/.qwen/settings.json` `model.reasoningEffort` (no CLI effort flag; S0 asserts the readback) | 4 |
| Spillover, in order | OpenCode Muse `opencode/muse-spark-1.2-contributor-free` variant xhigh (T3), then Antigravity `gemini-3.7-flash-high` (T4) | per contract | 4 each |
| Every review (per-unit + U8 integration) | Grok `grok-4.6 --reasoning-effort xhigh` (T5), grok.com login | flag-carried | 4, separate pool |

## Implementation Units

Each unit runs in its own worktree from the current intended base, freezes a
clean head, and gets exactly one Saga Code Review (Grok 4.6 xhigh) at that
frozen head. Fields required by the contract's S1 row appear per unit. `Backend:
inline` on every unit.

### U0. Repository README truth cleanup

Rewrite the README Status section to the verified current state of the UniFi
pilot, removing the two claims the repository's own tests falsify.

**Child issue:** #10 · **Group:** G1 · **Depends on:** none · **Lands into:**
main (own PR, 1st merge)

**Worker:** Qwen `qwen3.8-max-preview` @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** rewrite only `README.md`'s Status section (the two
falsified bold claims at lines 30 and 34, the "now paused" framing at line 15),
replacing each claim with the verified state and its evidence citation
(`tests/test_client_entrypoints.py`, `plugins/unifi/PROVENANCE.json`, the
current matrix `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`), plus
the minimal matching correction to `docs/README.md:12` (KTD6). Nothing else in
either file moves.

**Mechanism reused:** plain documentation edit gated by the existing repository
gate and suite; the root README is not test-pinned (verified:
`tests/test_unifi_readme.py` pins `plugins/unifi/README.md` only).

**New moving parts:** none.

**Rejected alternative:** pinning the corrected Status claims with a new
`PortableReadmeTests`-style test — rejected because U9 rewrites the Status
narrative again at closeout and the claims' truth is already enforced by the
tests and checkers they cite; a pin now would be churned within the same run.

**Test scenarios:** none — documentation-only unit; the grep-absence checks in
the child's verification are the acceptance probes
(`! grep -n "has no working entrypoint" README.md`,
`! grep -n "now paused for an operator decision" README.md`).

**Verification:** child #10 block — grep-absence probes, `check_repo.py`,
`unittest discover`, `git diff --check`.

### U1. Port descriptor and Phase 0 entry criteria

Author `ports/mission-control.json` (schema 2) classifying every upstream path
at the pin in exactly one custody class, and complete every runbook Phase 0
entry criterion.

**Child issue:** #11 · **Group:** G1 · **Depends on:** none · **Lands into:**
`port/mission-control` (1st branch merge)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** one new descriptor file carrying the audited custody
table and assessment settings from #11 (credential prefixes `GH_`/`GITHUB_`,
five package scripts, entrypoint candidates with recorded rationale for any
exclusion, the audited `mutating_operations` verb list including
`_open_mapping_pr`, seven skill units, `declared_none` empty and stated), plus
the Phase 0 records in the unit PR: upstream suite green at the pin — run
from a **disposable scratch clone** of the local upstream repository (created
by a read-only Git operation, the pinned commit checked out there, every
pytest cache and coverage output confined to scratch; the authoritative
checkout's revision and `git status` recorded before and after, and never
touched — doc-review F5; an in-place run is not read-only: upstream pytest
writes coverage by default and the checkout sits on a different commit) — the
validation-rule inventory (predicate + authority per rule) **including the
`test_prompt_alignment.py` premise verification under this repository's
layout, so its custody is finalized here in U1/U3 before synchronization
(doc-review F2)**, the Python floor with explicit interpreter path, and
non-goals. Journal entry for the two custody decisions with no UniFi
precedent (the `when_to_use` transform custody; test placement inside the
package, KTD-recorded in #11).

**Mechanism reused:** descriptor schema 2 under `scripts/port_config.py` (the
single format authority), `tests/test_port_config.py` derived expectations,
`python3 scripts/assess_clients.py --package mission-control` plan mode
(prints the ten-client plan, runs nothing).

**New moving parts:** none — the descriptor is data under the existing format.
U1 deliberately does not anticipate KTD2's rule-selection field (KTD7).

**Rejected alternative:** carrying the 21 upstream tests outside the package via
fleet-core's informal `release_surface` key (the pilot's one-off precedent) —
rejected because no check validates that key; placement inside
`plugins/mission-control/tests/` puts them inside the provenance closed-set
check.

**Test scenarios:** `tests/test_port_config.py` must pass unmodified over the
new descriptor; extend it only if the descriptor exercises an uncovered format
path. Descriptor-scoped validity probe:
`port_config.load("mission-control", ROOT)` succeeds.

**Verification:** child #11 block — `port_config.load` probe,
`unittest tests.test_port_config -v`, assessment plan print, `git diff --check`.
Full `check_repo.py` green is deferred to the assembled branch (the descriptor's
package tree does not exist yet — contract landing model).

### U2. Fleet Core slice expansion

*(record amended 2026-08-24 after the first U2 dispatch stopped on child #12's
stop condition item 1; the closure decision is KTD8 — the original two-module
wording is superseded by this text)*

Add `intent_envelope`, `tier_palette`, and the `models.json` registry to the
portable fleet-core slice at fleet-core's existing pin `3b5faa6c` —
`tier_palette.py` and `models.json` as byte copies, `intent_envelope.py` under
the `deterministic-transform` custody class with the
`resolve-fleet-commons-sibling` v1 rule (KTD8) — with provenance, deferral,
and release bookkeeping.

**Child issue:** #12 · **Group:** G1 · **Depends on:** none · **Lands into:**
main (own PR, 2nd merge)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** three files under
`plugins/fleet-core/scripts/fleet_commons/` — two byte copies digest-verified
against their blobs at `3b5faa6c`, plus `intent_envelope.py` carrying the KTD8
transform, its source digest, result digest, and rule name/version/prose
recorded in `derived_files` per the `guard-pytest-import` precedent; remove
exactly the three rows from `DEFERRED.md`; three classified `PROVENANCE.json`
entries; CHANGELOG and `plugin.json` version bump per package convention; the
pin-preserving decision and KTD8 recorded in `DECISIONS.md` in the same
commit.

**Mechanism reused:** fleet-core's existing PROVENANCE custody mechanism —
`files` plus `derived_files`; no `ports/fleet-core.json` exists and none is
created (a descriptor migration would be a restructure the contract calls out
as needing its own justification, and nothing in this unit needs it) —
`scripts/bundle_fleet_module.py` staleness machinery, and the
`deterministic-transform` recording pattern established by
`tests/test_retry_backoff.py`.

**New moving parts:** the `resolve-fleet-commons-sibling` v1 rule (KTD8), and
minimal target-owned tests: the transformed module imports cleanly; an
envelope round-trip; `tier_ceiling` validation resolving through sibling
`tier_palette` + `models.json`; the deferred-name call path (`tier_resolver`)
failing with the recorded error shape; plus the minimal `tier_palette`
palette-contract test (upstream ships none). Prevents shipping an unexercised
or unimportable module (the AGENTS.md runnability and
changed-packaging-carries-tests rules).

**Rejected alternative:** repinning fleet-core to `84eaf042` — rejected because
`retry_backoff.py` differs between the pins, so a repin regenerates UniFi's
`_bundled/` copies, moves the UniFi package fingerprint, and invalidates its
committed compatibility matrix. Also rejected, recorded in KTD8: the full tier
closure; a target-owned shim adapter under the upstream name; an unchanged
byte copy of `intent_envelope.py`; the directed byte-port of upstream
`tests/test_intent_envelope.py` (impossible as specified — KTD8 item 4).

**Test scenarios:** target-owned minimal `tests/test_intent_envelope.py` (per
KTD8, not a byte-port) and the new minimal tier-palette test; both green under
`python3 -m unittest discover -s tests -v`. Guard scenario: `git status
--porcelain -- plugins/unifi` empty after `bundle_fleet_module.py` (no UniFi
churn — a #12 stop condition if violated).

**Verification:** child #12 block (amended) — upstream-blob digest comparison
for the two byte copies plus recorded source/result digests for the transform,
bundle no-op, gate, suite, UniFi-churn probe, `git diff --check`.

### U3. Sync, provenance, and transform rules (Lane A)

Synchronize the package tree from the pin with the two new entrypoint-transform
rules, the frontmatter normalization, and descriptor-carried rule selection;
generate digest-verified provenance.

**Child issue:** #13 · **Group:** G2 · **Depends on:** U1 · **Lands into:**
`port/mission-control` (2nd branch merge)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** run
`scripts/sync_vendor_source.py --package mission-control` from the pinned
commit after extending the tool with exactly three things: (1) two new named
single-shape transform rules per KTD1 (module-scope split shape for
`executor_profile_lint.py`; function-scope guarded-contiguous shape for
`sdlc_manager.py`), (2) `normalize-skill-frontmatter` v1 per KTD3, (3) the
descriptor rule-name field with the schema version 3 bump per KTD2
(`SCHEMA_VERSION` to `"3"` in `scripts/port_config.py`, `ports/README.md`
updated, and both descriptors migrated — `ports/unifi.json` gains its explicit
rule name and the new version in the same commit). Client custody lands as specified in #13:
four commands + `agents/sdlc-operator.md` byte-copied under
`com.infiquetra.claude/`, the Claude manifest relocated via
`relocate-claude-manifest` v1, `fleet_commons_shim.py` dropped-from-source with
its reason. Upstream defects inside byte copies (stale `2.1.0` paths, `/issue`
self-alias) are carried verbatim — U9 files them.

**Mechanism reused:** `sync_vendor_source.py`'s existing enforcement (single
classification, byte-copy digest equality, path safety, manifest recording),
the existing v1 transform-rule pattern as the template for the two new rules,
`port_config.py` as sole schema authority.

**New moving parts:** the three named extensions above, each versioned and
tested. Failures prevented, respectively: unresolvable shim imports in the two
transformed entrypoints (the exact import-failure class the pilot shipped);
seven skills failing `check_skill_frontmatter` on the assembled branch; and
non-deterministic rule application once more than one rule exists.

**Rejected alternative:** per KTD1/KTD2 — a loosened multi-shape v2 of the
existing rule, and a script-internal rule registry. Also rejected: hand-editing
any synced file (runbook anti-pattern; sync `--check` must reproduce the tree).

**Test scenarios:** `tests/test_sync_vendor_source.py` — per new rule: matches
its shape exactly once, refuses zero and multiple matches, records rule
name/version/digests; frontmatter normalization is deterministic and idempotent
(second application is a no-op). `tests/test_port_config.py` — rule-name field
parsing, absent-field behavior, unknown-key refusal unchanged.

**Verification:** child #13 block — sync `--check` green on the landed tree, no
unresolved `fleet_commons_shim` import in transformed files
(`git grep -n "fleet_commons_shim" plugins/mission-control/scripts/`), suite,
`git diff --check`. Package-completeness checks may still fail pending Lanes
B/C (contract landing model).

### U4. Target-owned surface (Lane B)

Author the portable package manifest and the target-owned package README with
its runnability-enforcing test.

**Child issue:** #14 · **Group:** G2 · **Depends on:** U1 · **Lands into:**
`port/mission-control` (3rd branch merge)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** two new target-owned files —
`plugins/mission-control/plugin.json` (modeled on `plugins/unifi/plugin.json`;
name mission-control, upstream version 2.12.2) and
`plugins/mission-control/README.md` documenting the portable package: all seven
skills including `flow`, the read-only vs GitHub-mutating subcommand split,
`gh` auth delegation, `INFIQUETRA_SDLC_PATH` as the only env override, the
PyYAML requirement, network-first `sdlc-schema` resolution — plus the new
`tests/test_mission_control_readme.py`.

**Mechanism reused:** the `tests/test_unifi_readme.py` enforcement pattern
verbatim (lede identifies the portable package, every relative link resolves,
every documented `python3` command runs from repo root credential-stripped,
PROVENANCE classifies the README target-owned with no digest), with
`GH_`/`GITHUB_` stripping as the analog of the UniFi test's `UNIFI_` stripping.

**New moving parts:** none beyond the pattern-following test.

**Rejected alternative:** byte-copying the upstream README — the codified pilot
failure mode (tells portable consumers they have a Claude Code plugin, carries
the stale `2.1.0` path, omits `flow`; a later resync would restore the defect).

**Test scenarios:** `tests/test_mission_control_readme.py` — lede check,
link resolution, documented-command runnability in a credential-stripped
environment, no documented mutating invocation, PROVENANCE custody assertion.

**Verification:** child #14 block — gate, suite, `git diff --check`.

### U5. Fleet Core bundle (Lane C)

*(record amended 2026-08-24 per KTD8: the bundle carries three files, and the
bundled `intent_envelope.py` is the already-transformed fleet-core file)*

Declare the three-file fleet bundle and generate the `_bundled/` files the
U3 transforms resolve to; refresh provenance to close the set.

**Child issue:** #15 · **Group:** G2 · **Depends on:** U1, U2 (branch rebased
onto main after U2 lands) · **Lands into:** `port/mission-control` (4th branch
merge)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** one new target-owned
`plugins/mission-control/fleet-bundle.json` naming `intent_envelope`,
`tier_palette`, and the `models.json` registry with destinations under
`scripts/_bundled/` (the child's exact JSON), the three generated files from
`python3 scripts/bundle_fleet_module.py`, and a `PROVENANCE.json` refresh via
sync re-run so the closed-set check sees the new target-owned files. The
bundled `intent_envelope.py` is generated from the fleet-core file that
already carries the KTD8 transform, so its sibling resolution works unchanged
in `_bundled/`; `models.json` must land beside it for `tier_palette`'s
import-time read.

**Mechanism reused:** `schemas/fleet-bundle.schema.json` v1, the UniFi
`fleet-bundle.json` pattern, `bundle_fleet_module.py` generation +
`check_repo.py` staleness rejection (AGENTS.md build step), sync-time
target-owned set-difference discovery.

**New moving parts:** none expected. One contingency, flagged by KTD8: if
schema v1 or `bundle_fleet_module.py` turns out to carry Python modules only,
this unit extends them minimally (recorded, versioned) so the `models.json`
data file can ride the same declaration — decided inside this unit under its
own review, not silently.

**Rejected alternative:** hand-copying the modules into the package — rejected
because `check_repo.py` rejects hand-edited bundles by design, and hand copies
are exactly the unstamped-drift failure the bundle machinery exists to prevent.

**Test scenarios:** confirm `tests/test_bundle_fleet_module.py` and
`tests/test_fleet_bundle_schema.py` exercise a multi-module consumer; add the
minimal case only if existing coverage is single-module-only. Determinism
scenario: second `bundle_fleet_module.py` run is a no-op. Guard: UniFi bundles
byte-untouched.

**Verification:** child #15 block — bundle run, gate, suite, UniFi-churn probe,
`git diff --check`.

### U6. Test custody, CI wiring, entrypoint generalization

Make the ported 21-file pytest suite real and enforced: CI runs it on the floor
with PyYAML, the entrypoint-runnability test iterates every port descriptor,
and the floor declaration sites include the new package.

**Child issue:** #16 · **Group:** G3 (serial) · **Depends on:** U3, U4, U5 ·
**Lands into:** `port/mission-control` (5th branch merge)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** three bounded edits — (1) `.github/workflows/ci.yml`
`plugin-tests` job gains the `plugins/*/tests` glob and `pyyaml` (KTD4), with
the exit-status-5 tolerance resolved in the job's final command shape so an
empty collection for a declaring package fails; (2) `tests/test_client_entrypoints.py`
generalized from the hardcoded `load_config("unifi")` (line 50, verified) to
iterate every `ports/*.json`, drive each package's declared
`assessment.entrypoints`, strip each package's own `credential_prefixes`,
assert exit 0 + usage + no `ModuleNotFoundError`, skip (not fail)
entrypoints whose third-party imports are absent in the hermetic job (the
existing two-job dependency-split convention, DECISIONS 2026-08-22), and keep
the bundle-deletion control test; (3) `tests/test_python_floor.py`
`DECLARATION_SITES` (line 70, verified) gains the mission-control README and
CHANGELOG. Conftest independence is proven by the acceptance run itself (the
package suite green with no repo-root conftest). `test_prompt_alignment.py`'s
premises are verified during U1's Phase 0 and its custody finalized in U1/U3
before synchronization (doc-review F2); if a premise failure first surfaces
here, U6 stops and returns the change through the custody owner —
resynchronization, affected verification, and a new frozen review — rather
than editing the descriptor or any byte-copied test itself.

**Mechanism reused:** the existing two-CI-job structure, the entrypoint test's
own control-test pattern, the floor test's declaration-site tuple.

**New moving parts:** none expected — the glob plus the corrected
empty-collection handling satisfy #16's criterion; a separate path-agreement
check is added only if a concrete shell-expansion or collection failure
remains once the final command shape is written (doc-review F6).

**Rejected alternative:** per-package CI path enumeration (KTD4); editing any
upstream test's content to make it pass here (custody violation — a test that
cannot pass without content change is an upstream filing or a recorded custody
decision).

**Test scenarios:** generalized `tests/test_client_entrypoints.py` fails when a
`_bundled` module is removed from a scratch copy (control retained) and covers
every descriptor by iteration; `tests/test_python_floor.py` fails when either
new site drops the floor specifier; package suite
`python3 -m pytest plugins/mission-control/tests -q` green on 3.12 with
`pytest pyyaml` and no repo-root conftest.

**Verification:** child #16 block — gate, hermetic suite, package pytest,
`git diff --check`. Assembled branch fully green from this unit onward.

### U7. Validation-rule audit (runbook Phase 2 — serial, do not skip)

Audit every validation rule the ported package carries: predicate stated,
authority named and derived at test time, class corpus written, verdict
agreement asserted wherever a rule exists in more than one copy.

**Child issue:** #17 · **Group:** G4 (serial) · **Depends on:** U6 · **Lands
into:** `port/mission-control` (6th branch merge)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** class-first corpora and authority-derivation tests
for exactly the Phase 0 rule inventory (U1's entry criterion): the card
validator (verdict agreement vs the home-lab authority per KTD5, corpus of
header presence/absence/reorder, empty placeholders, risk-tier sections, fence
variants), issue-contract parity (offline legs hold; `--live` leg skips, never
silently passes; record what a portable consumer cannot re-derive without
infiquetra-sdlc), pagination lint (runs against the portable layout; corpus
includes shapes it must reject), and the prompt-alignment and template-sync
guards (state each predicate and what it can honestly establish here). Each new
check probed against a violating corpus member (recorded in the PR) — the
pilot's "if it cannot be made to fail, it is not evidence" rule.

**Mechanism reused:** the runbook Phase 2 checklist; the pilot's class-first
lesson (instance-by-instance auditing of one rule cost 41% of the entire
pilot); the `test_template_sync.py` self-skip convention for external-checkout
authorities.

**New moving parts:** the verdict-agreement and authority-derivation tests
themselves — each named with the copied-rule divergence failure it prevents
(two copies agreeing on constants but not verdicts).

**Rejected alternative:** restating authority premises as copied constants
(cannot fail when the premise moves); repairing any byte-copied rule in place
(stop condition — upstream filing + deliberate repin instead).

**Test scenarios:** new/extended tests under `tests/` (exact files per the
Phase 0 inventory); verdict-agreement pair tests for the card validator; every
added check demonstrated capable of failing against a broken fixture; sync
`--check` still exits 0 (zero in-place edits to byte copies).

**Verification:** child #17 block — gate, both suites, sync `--check`,
`git diff --check`.

### U8. Freeze, Phase 3 evidence, ten-client matrix, integration merge

Freeze the assembled candidate, capture all Phase 3 evidence bound to that
exact state, pass the integration review, and land `port/mission-control` on
main as one green PR.

**Child issue:** #18 · **Group:** G5 (serial) · **Depends on:** U7 · **Lands
into:** branch → main (3rd main merge; the integration review point)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** the runbook Phase 3 sequence, in order: verify →
freeze (exact commit, clean tree, recorded) → evidence bound to the frozen
state → integration review → merge. The promise is one **current** committed
matrix, not one lifetime execution (doc-review F3): after an accepted
integration-review repair, verify again, freeze the successor revision, rerun
only the evidence whose binding moved, and preserve the superseded record with
its reason — one evidence rerun per review cycle, inside the same three-cycle
cap (#18 stop conditions; runbook anti-patterns). Evidence set: gate +
hermetic + package suites green, plus the upstream suite at the pin from the
disposable scratch clone (F5 procedure recorded in U1); floor verified from
staged bytes; per-client matrix `reason` fields authored by this unit from
observed stage evidence and reviewed at the integration review (amended #18 —
doc-review F4); one credential-stripped `--execute` ten-client assessment (throwaway 3.12 floor
venv extended with **PyYAML** — the pilot's requests+urllib3 venv does not
cover `sdlc_manager.py`'s module-scope import; interpreter by explicit path;
recorded real binaries `grok=/Users/jefcox/.local/bin/grok.pre-auto-trust`,
`agy=/Users/jefcox/.local/bin/agy.pre-auto-trust` per the contract's inputs
inventory); committed fingerprint-bound matrix passing
`check_compatibility_matrix.py`; one readback; one mutation proof per rule copy
with binding tests.

**Mechanism reused:** `assess_clients.py` plan-then-execute flow with the
runbook's client-quirk table (Cursor real-HOME, Grok/Agy `--real-binary`, Qwen
stdin prompt, Gemini `skills link` hang, Muse `--force`, Hermes isolated-home,
Codex package-root refusal); the `MutationProofBindingTest` pattern; the pilot's
readback pattern; the parent's review contract for the integration review.

**New moving parts:** none — this unit consumes what prior units built. The
pilot's costliest lesson is encoded as bounded rounds: batched repairs, one
current matrix, at most one evidence rerun per review cycle, three-cycle cap
on the integration review.

**Rejected alternative:** re-running the assessment after any post-freeze
change instead of investigating (the harness's fingerprint refusal exists to
force cause-identification first — a #18 stop condition); editing evidence to
match a moved tree (superseded records are preserved with reasons, never
edited).

**Test scenarios:** mutation-proof binding tests under `tests/` (fail when a
graded file changes without its proof). Merge invariant: the merge commit moves
SHAs, not file digests — matrix checker green again on main post-merge.

**Verification:** child #18 block — assessment plan print, matrix checker,
gate, both suites, `git diff --check`.

### U9. Closeout: docs, upstream filings, journal, board evidence

Close the migration on main: documentation reflects the shipped package, the
four audited upstream defects are filed, the journal is curated, and the
parent's completion evidence is posted.

**Child issue:** #19 · **Group:** G6 (serial) · **Depends on:** U0, U8 ·
**Lands into:** main (4th main merge, last; rebases onto U0's corrected README)

**Worker:** Qwen @ xhigh (T2) · **Backend:** inline

**Smallest viable change:** README Status narrative + package table gain
mission-control (building on U0's corrected baseline); `llms.txt` one Packages
bullet; `docs/README.md` index only if its structure requires; four
upstream issues filed in `infiquetra/infiquetra-claude-plugins` with file:line
evidence (stale `2.1.0` paths; `/issue` self-alias; README skills table omits
`flow`; `rollout update` names removed `beads-config.json`); journal curation
(DECISIONS for the port's new custody decisions, LEARNINGS for surprising
mechanisms, runbook version recorded); parent closing comment with per-unit
PRs, base/frozen/merged SHAs, review outcomes with residuals, filing URLs,
per-group wall-clock; cleanliness sweep.

**Mechanism reused:** existing doc surfaces and conventions; the journal
standard; the contract's closeout evidence list. Board Status writes ride the
coordinator's reconcile path — U9 performs the readback that every child shows
Done, it does not hand-write Status.

**New moving parts:** none.

**Rejected alternative:** fixing any of the four upstream defects here —
custody discipline forbids it; fixes return only through a later deliberate
repin + resync.

**Test scenarios:** none expected — documentation and filings; if a new README
claim about mission-control is load-bearing, pin it per the
`tests/test_unifi_readme.py` pattern, otherwise add nothing. Fingerprint
invariant: no file under `plugins/mission-control/**` or `plugins/fleet-core/**`
changes; matrix checker still green at final HEAD.

**Verification:** child #19 block — gate, both suites, matrix checker,
`git status --porcelain` empty, `git diff --check`.

## Landing and merge schedule

| Wave | Units (parallel within wave) | Base | Merges (serialized) |
| --- | --- | --- | --- |
| 1 | U0, U1, U2 — 3 ready, all Qwen (cap 4) | origin/main (U0, U2); branch cut from main (U1) | main: U0 then U2 · branch: U1 |
| 2 | U3, U4, U5 — own worktrees; U5 starts after U2 merges + branch rebase onto main | `port/mission-control` | branch, in order: U3, U4, U5 |
| 3 | U6 (serial) | branch | branch: U6 — fully green from here |
| 4 | U7 (serial) | branch | branch: U7 |
| 5 | U8 (serial) | branch, rebased onto main pre-freeze | main: integration PR (3rd main merge) |
| 6 | U9 (serial) | origin/main (post-U8, post-U0) | main: U9 (4th, last) |

Shared-file rules (contract): `README.md` — U0 then U9 only;
`docs/engineering-journal/LEARNINGS.md`/`DECISIONS.md` append-shared,
rebase-and-append, never parallel merges; `.github/workflows/ci.yml` — U6 sole
writer; `tests/` — U6 then U7 in series; `plugins/mission-control/**` — branch
units only, per-lane ownership; `plugins/fleet-core/**` — U2 only;
`ports/mission-control.json` — U1 then U3 (KTD7). Fetch origin before creating
any unit branch or worktree; record base, frozen, and merged SHAs per unit; a
stale or dirty revision is never reviewed or merged.

## Scope Boundaries

Carried from the contract; binding on every unit:

- No custody move — upstream stays authoritative; this run never edits
  `infiquetra/infiquetra-claude-plugins` (filings only, U9).
- No live GitHub mutation from build, tests, or assessment; the package's
  mutating capabilities ship as code + enumerated `mutating_operations`, never
  exercised live.
- No per-client remediation, marketplace manifests, or distribution work;
  statuses recorded, decisions left per client as in the pilot.
- No architecture-brief adoption decisions; no multi-tenancy/HA/enterprise
  posture; no board-mapping changes for this repository.
- Deferred to follow-up (distinct from non-goals): upstream defect fixes return
  via a later repin + resync; per-client distribution decisions remain open
  operator items.

## Risks and pre-mortem deltas

The contract's pre-mortem stands (most likely failure: U3's transform-rule
extension balloons). This plan's mitigations beyond it:

- KTD1/KTD2 bound U3's design space to two single-shape rules plus one additive
  descriptor field — if `port_config.py` changes grow beyond rule selection,
  the unit stops and surfaces (contract stop condition).
- KTD5 removes the one hidden external dependency (home-lab authority) from the
  hermetic path while keeping the agreement leg real on the run machine.
- The U5→U2 rebase point and the pre-freeze rebase are the two moments base
  drift can surface; both are contract-scheduled, and the freshness rule
  (fetch-before-worktree, rerun affected checks after rebase) covers a
  mid-run main advance.

## Open questions — resolved in the S3 disposition pass

Both questions this plan originally left open were closed by the validated
doc-review findings (F4, F2) and the coordinator's disposition:

1. **Matrix `reason` authorship** *(was open question 1; doc-review F4)* —
   child #18 amended to match the operator's recorded no-operator-input
   decision for U8: the unit authors each `reason` from observed stage
   evidence, and the integration review is the review surface. The operator may
   override by amending #18 again before U8 starts.
2. **`test_prompt_alignment.py` custody** *(was open question 2; doc-review
   F2)* — the premise verification moved into U1's Phase 0 entry criteria and
   custody is finalized in U1/U3 before synchronization; U6 stops rather than
   deciding custody after Lane A has merged.

## Unattended decisions log

Choices from known sets, taken without prompting per the run's unattended
directives, each with the line of reasoning:

- **Backend: `inline`** — operator-decided for this run; recorded in
  frontmatter; not re-offered.
- **Destination: merge** — the contract drives every child to merged-and-closed;
  no deploy surface exists in this repository.
- **Saga: mint fresh** — `saga.py scan` returned zero candidates for this
  thread.
- **Board Status: untouched by this session** — the contract's board automation
  assigns Status writes to the execution coordinator through the reconcile
  path; the plan skill's Shaping/Ready moves are therefore intentionally not
  performed here.
- **Tier interrogation: skipped** — the contract pins every worker and reviewer
  binding (fifth-pass operator amendments in #9); re-deriving tiers from the
  registry would re-litigate a settled operator decision.
- **U2 closure stop disposition (2026-08-24): amend-and-redispatch, no
  operator gate** — child #12's stop condition item 1 fired exactly as
  written ("the closure grows and the parent's plan must account for it
  before bundling"), and #9's run-level stop list carries the matching entry
  ("any unit's acceptance criteria requiring scope outside its owned
  surface"). The contract routes the accounting to the parent plan, not to an
  operator pause, so the coordinator verified the unit's stop evidence
  read-only against the pins, decided KTD8, amended this plan and cards
  #12/#15, and re-dispatches U2 after the amendment's doc review. Only U5 was
  downstream-blocked; U0 and U1 continued unaffected.
