# KTD8 amendment document review

This Agent Plugins repository must not redispatch the Fleet Core slice or start
the mission-control bundle unit from amendment `d1ac17c` yet: the closure
decision is substantively correct, but the executable records and the current
bundle/provenance mechanisms still disagree.

## Verdict

**BLOCKED.** Three blocker findings prevent a fresh worker from completing U2
(the Fleet Core slice expansion) or U5 (the mission-control Fleet Core bundle)
as written. Two should-fix findings correct factual and sequencing language
without changing the three-file closure decision.

No fixes were applied to the reviewed plan, decision entry, child issues, or
upstream checkout. This review adds only this artifact.

## Exact review scope

The reviewed delta is exactly `git show d1ac17c`, commit
`d1ac17cc525387f2a161c29a466752209ef2b29b` with parent
`0e833f84440ae1fde6b97fc40ec6f31aea577c11`. It changes only:

- `docs/plans/2026-08-24-mission-control-port-run-plan.md`; and
- `docs/engineering-journal/DECISIONS.md`.

The evidence boundary was:

- stop evidence from
  `git show 68cf5fc:.orchestrate-unit-blocked.md`;
- the full plan at `d1ac17c`, including Key Technical Decisions 1 through 7,
  the unit records, shared-file rules, and landing schedule;
- current read-only issue bodies from
  `gh issue view 12 --repo infiquetra/infiquetra-agent-plugins` and the matching
  command for issue 15; and
- read-only Git objects in
  `/Users/jefcox/workspace/infiquetra/infiquetra-claude-plugins` at
  `3b5faa6c1044a888e03cb7b8bbf2f71c6749489c` and
  `84eaf042f0e350005f7eddf8e7d80da25c12119d`.

The upstream checkout remained at its pre-existing revision
`d82895133886e8843c8cf888eada3fed036ecb7e`; this review used `git show`,
`git grep`, `git ls-tree`, `cmp`, and digest reads only. No GitHub mutation was
performed.

## Accuracy audit

The stop is real and the three-file closure is proportionate to it. Branch
`orch/mcport-9-resume1-u2-fleetcore-q1` points at `68cf5fc`, and
`git rev-list --count 68cf5fc^..orch/mcport-9-resume1-u2-fleetcore-q1`
returns `1`, so the plan's “sole commit” description is accurate. The marker
records child issue 12's first stop condition before any package edit.

Every source line cited by KTD8 matches the pinned bytes:

| claim | verified source evidence |
| --- | --- |
| `intent_envelope.py` module-scope shim block | lines 79–83 contain the parent-directory path insertion and `import fleet_commons_shim` |
| lazy closure | lines 166 and 170 load `tier_resolver` and `tier_palette` respectively |
| `tier_palette.py` data dependency | line 26 selects sibling `models.json`; line 78 calls `_load_registry()` at import time |
| direct mission-control palette consumption | `executor_profile_lint.py:89` loads `tier_palette` |
| envelope parse reachability | `sdlc_manager.py:4299` calls `envelope_from_issue_body`; canonical `intent_envelope.py:385–397` constructs and validates the optional spend envelope; lines 236–248 reach `_tier_palette()` when `tier_ceiling` is set |
| dormant resolver leg | `git grep` finds no `recommend_tier`, `self_select_posture`, or `authorize_spend` caller anywhere under `plugins/mission-control` at `84eaf042` |

The SHA-256 values in the stop evidence also recompute exactly at both pins:

| upstream path | SHA-256 |
| --- | --- |
| `plugins/fleet-core/scripts/fleet_commons/intent_envelope.py` | `5157fa303a92152ec9af0ef2a8f8e7543a46351d84282e076854ac2a2f9d201a` |
| `plugins/fleet-core/scripts/fleet_commons/tier_palette.py` | `b14ff89f155c0043e72bf028b937bdb6e3e7b4ebbfbf919683d88a8764ef9e28` |
| `plugins/fleet-core/scripts/fleet_commons/models.json` | `8b50e821e12d56d555e2c2f087df2f568fda48c20987840d2d5a3bfa7a362f83` |
| `plugins/fleet-core/scripts/fleet_commons/tier_resolver.py` | `71ed848f0fe9b06b8435ff7735996e133c8226e2a58f948503c5b0a620d924e0` |
| `plugins/fleet-core/scripts/fleet_commons/tier_policy.json` | `92aa8d8be3190d2904996e5fb5a6aa7680db3f7fc3aed8923a20e6857ee5a489` |
| `plugins/fleet-core/scripts/fleet_commons_shim.py` | `9070b450997e6f07d8af3baa137012c6950f70487419c8013dc4c6358f2f4eb7` |
| `tests/test_intent_envelope.py` | `743b64be9d797399130abc9b7e41aa6e6580fe853edb7466a393219e4db914e1` |

`retry_backoff.py` is correctly called out as different: its digests are
`2aa7fd26bb0fb40dbbd0b7a14ae34f24c473561648695346edaa60079ac63021`
at `3b5faa6c` and
`c1e9d9c23cc0d356fa75c8da4c426e8849d8b96270283daff2acca62594e911f`
at `84eaf042`. Commit `d1ac17c` contains no proposed result-digest value to
verify; it correctly makes the result digest an implementation output.

The closure decision is consistent with KTD1's entrypoint-transform boundary:
a transformed `intent_envelope.py` can remove the bundled module's shim
reference while KTD1's two rules remain limited to the two mission-control
entrypoints. Keeping `tier_resolver.py` and `tier_policy.json` deferred is also
proportionate because mission-control reaches the palette path but none of the
three resolver-backed APIs. The landing dependency is correct in principle:
U2 lands on main before the integration branch is rebased and before U5 bundles
the landed Fleet Core slice.

Those correct facts do not close the findings below.

## Findings

### F1. The child cards were not amended, so redispatch would reinstate the stopped contract

The unattended-decisions log says the coordinator “amended this plan and cards
#12/#15” and will redispatch U2 after this review
(`docs/plans/2026-08-24-mission-control-port-run-plan.md:846–855`). The live
cards contradict that statement and every amended execution boundary:

- Issue 12 still requires exactly two byte-copied Python modules, forbids any
  other deferred item from leaving `DEFERRED.md`, requires byte-equal
  `intent_envelope.py`, and requires a port of the upstream test. Its expected
  files and digest commands omit `models.json` and a transformed-result digest.
- Issue 15 still declares the exact two-module JSON, forbids bundling anything
  beyond those two modules, and names only two generated Python files. It has
  no data-file mechanism, schema/generator ownership, or `models.json`
  acceptance check.

The plan then delegates verification back to “child #12 block (amended)” at
lines 421–423 and “child #15 block” at lines 562–563. Those blocks are not
amended. A fresh worker following the child card either repeats the original
stop or violates its non-goals to follow KTD8.

Required disposition: amend both child cards before redispatch. Each card must
carry the decided file list, custody classes, test replacement, acceptance
criteria, verification commands, and any newly owned shared files. Remove the
false completed-action claim from the plan until the readback proves the card
bodies match.

**Severity: blocker.**

### F2. U2 records a package file in the wrong provenance collection

KTD8 and the journal require the transformed
`plugins/fleet-core/scripts/fleet_commons/intent_envelope.py` to be recorded in
`derived_files` (`docs/plans/2026-08-24-mission-control-port-run-plan.md:217–225,
380–396`; `docs/engineering-journal/DECISIONS.md:9–17`). That precedent applies
to `tests/test_retry_backoff.py`, which is outside the package tree and whose
`derived_files.path` is repository-relative
(`plugins/fleet-core/PROVENANCE.json:38–48`).

Package provenance works differently. `scripts/check_repo.py:531–538` passes
only the `files` array to entry validation and the package closed-set check.
At lines 433–498, every package file must appear in that array under a
package-relative path. A transformed package file listed only in
`derived_files` is therefore reported as an unlisted package file. Listing it
in both arrays would contradict the plan's three-entry count and its one
classification per path.

The existing mechanism already accepts `deterministic-transform` entries in
`files` and requires their source digest, result digest, and transform version
(`scripts/check_repo.py:348–410`). No new custody machinery is necessary.

Required disposition: record transformed `intent_envelope.py` once in
`files`, with its package-relative path and the complete transform metadata,
alongside the two byte-copy entries. Amend KTD8, the U2 record, and the journal
to name that collection. If `derived_files` is intentionally being generalized
instead, the plan must own the checker, path-base, duplicate-classification,
and regression-test changes rather than claiming the existing mechanism works.

**Severity: blocker.**

### F3. U5 leaves a known data-bundling design failure for the worker to discover

The U5 record says `models.json` can be named in the current fleet bundle and
calls the proposed declaration “the child's exact JSON,” then treats data-file
support as a contingency to decide inside U5
(`docs/plans/2026-08-24-mission-control-port-run-plan.md:530–550`). Current
repository facts make the contingency certain:

- `schemas/fleet-bundle.schema.json:18–40` defines only `modules`, and its name
  pattern at line 29 rejects the dot in `models.json`.
- `scripts/bundle_fleet_module.py:241–246` unconditionally maps a name to
  `scripts/fleet_commons/<name>.py`; lines 295–305 use that mapping for every
  declaration entry. Neither `models.json` nor a generic source path is
  expressible.
- `scripts/bundle_fleet_module.py:338–356` prepends a Python-comment stamp. The
  resulting bytes would not be valid JSON if that renderer were applied to
  `models.json`.

This is the accounting that the original stop condition required before
bundling, not an ambiguity U5 may defer to its own review. The open choice can
also affect the schema version, top-level scripts and tests, and potentially
the existing UniFi declaration or package fingerprint. None of those files or
no-churn consequences is assigned in the amended U5 record or current issue
15.

Required disposition: decide the exact declaration shape and version,
data-safe provenance/stamp representation, source/destination mapping, backward
compatibility with the existing UniFi version-1 declaration, owned files, and
tests in the parent amendment. Then make U5 and issue 15 carry that one
executable design. “Extend them minimally” is not decision-complete here.

**Severity: blocker.**

### F4. The test-custody rationale overstates which imports occur at module load

KTD8 says the upstream test imports saga, team-execution, and mission-control
surfaces “at module level”
(`docs/plans/2026-08-24-mission-control-port-run-plan.md:226–230`), and the
journal repeats that wording at lines 17–19. At upstream pin `3b5faa6c`, the
test imports saga's re-export at line 51 and loads team-execution's
`posture_check.py` during collection at line 364. Mission-control's
`sdlc_manager` import is inside `_sdlc_manager()` at lines 420–424 and occurs
only when the tests at lines 430 and 625 call that helper.

The decision not to byte-port the test remains sound: it cannot collect in this
repository because the saga and team-execution surfaces are absent, and later
tests also require mission-control and saga-only APIs. The stated phase of the
mission-control import is nevertheless a factual error.

Required disposition: say that collection requires saga and team-execution,
while test execution additionally reaches mission-control and saga-only APIs.

**Severity: should-fix.**

### F5. U2 is told to record a decision that this amendment has already recorded

The amended U2 record still requires “the pin-preserving decision and KTD8
recorded in `DECISIONS.md` in the same commit”
(`docs/plans/2026-08-24-mission-control-port-run-plan.md:380–388`). KTD8 is
already recorded by this amendment in commit `d1ac17c`; a redispatched U2 based
on the reviewed amendment cannot add that same decision for the first time in
its implementation commit. A fresh worker must either make an unexplained
second edit to the append-shared journal or ignore a literal unit instruction.

Required disposition: state that U2 consumes the already-recorded KTD8 and
updates the journal in its implementation commit only if implementation
evidence changes or extends the decision. Keep the append-shared landing rule
at plan lines 772–779 intact.

**Severity: should-fix.**

## Executability and residual risk

U2 becomes executable after F1, F2, F4, and F5 are corrected: the three-file
slice, a single package-relative transform provenance entry, generated deferral
inventory, release bookkeeping, and target-owned tests form a bounded change.
U5 remains non-executable until F1 and F3 decide and assign the data-file
mechanism. No implementation test can prove those future records today.

The review did not run an implementation probe against hypothetical transformed
bytes because the requested scope is the documentation delta and the transform
does not exist. Repository validation can prove the review artifact is well
formed; it cannot make the blocked plan executable.

## Delta recheck addendum — commit 8590ce9

Commit `8590ce9` resolves F1, F2, F4, and F5. F3 remains a blocker. The amended
U5 record still does not name the data-file declaration field or item shape,
the schema-version value, or where the external data-file digest is stored.
It simultaneously calls schema v1 the reused mechanism and calls the extension
“versioned.” A fresh worker must still design the contract that issue 15 is
supposed to carry, so “explicit data-file entry class” and “digest comparison
recorded outside the file” are not the exact declaration and provenance design
F3 required before bundling.
