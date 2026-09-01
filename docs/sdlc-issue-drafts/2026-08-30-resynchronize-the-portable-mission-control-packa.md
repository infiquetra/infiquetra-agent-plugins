---
title: Resynchronize the portable mission-control package from upstream 2.12.2 to 2.15.2
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: high
handoff_maturity: requirements-ready
approval_state: approved
---

# Resynchronize the portable mission-control package from upstream 2.12.2 to 2.15.2

### Objective

Move the portable `mission-control` package in this repository from its current
pin — upstream commit `84eaf042` (plugin version 2.12.2) — to upstream
`3b2b7083` (plugin version 2.15.2), and re-establish the evidence that says what
the resynchronized package actually is.

This consumes all eight upstream filings the #9 migration raised
(`infiquetra/infiquetra-claude-plugins` #818–#822 and #828–#830), every one of
which has landed upstream. `docs/engineering-journal/QUEUED.md` records that
those fixes reach this repository only through a deliberate repin and resync,
never an in-place edit. This is that repin.

**Measured scope, verified against a fresh fetch of upstream on 2026-08-30.**
36 files change between the two pins: 7,706 lines added, 524 removed. Eight
files are new — all tests. Twenty-eight are modified. Nothing is deleted.

Three things make this materially cheaper than the #9 port. Fleet Core is
unchanged upstream across the entire window, so no bundle regeneration is needed
and the two units #9 spent on the Fleet Core slice have no counterpart here.
Every transform premise still holds: all seven `SKILL.md` files still carry the
`when_to_use` key the frontmatter rule folds, `scripts/executor_profile_lint.py`
is byte-identical to the pin, and the guarded fleet-shim block in
`scripts/sdlc_manager.py` is byte-identical in shape — only its line number moved,
from 4283 to 5134, and the rule matches by pattern. And the Python floor has not
moved: upstream declares `requires-python = ">=3.12"` at the new pin, which is
what this catalog declares.

One thing makes it harder. The package fingerprint moves, which retires the
committed ten-client compatibility matrix and the post-activation readback. No
test in this repository binds either of those two mission-control documents, so
that retirement would otherwise be silent. Operator ruling 3 closes that hole
permanently.

### Intent

Run the resynchronization as six serialized child units under the resync policy
already recorded in `docs/engineering-journal/QUEUED.md`: repin, run
`scripts/sync_vendor_source.py --check`, re-run the suites, and re-run exactly
the fingerprint-bound evidence whose binding moved. The portable copy stays a
derived artifact and never becomes a second writable source: a needed byte change
in copied content is an upstream filing, never a downstream patch.

**Four operator rulings, settled 2026-08-30, binding on every unit.**

1. **Pin.** Pin `3b2b7083` — the latest accepted `origin/main` revision carrying
   2.15.2 — and prove the upstream suite green at that exact commit from a
   disposable scratch clone before implementation begins. This wording matters:
   three commits carry version 2.15.2, and the package tree differs between them.
   `379d2350` (where the version landed) has tree `0fdcea0d`; `1111de33` (its
   document review) and `3b2b7083` (the accepted merge) share tree `a851eabb`.
   The document review repaired `CHANGELOG.md` and
   `skills/board/references/kanban-workflow.md` inside the package without moving
   the version. Pinning the version-landing commit would import content its own
   review had already corrected.
2. **Custody of the new agreement test.** Exclude
   `tests/test_card_validator_agreement.py` from the portable package and record
   it in `removed_from_source`, preserving the upstream test where it belongs.
   The portable tests remain repository-local and hermetic. That file loads an
   authority module from outside any repository, searching `HOME_LAB_PATH`, then
   `~/workspace/infiquetra/home-lab`, then sibling directories, and skips loudly
   when absent — the same shape as the `test_prompt_alignment.py` drop already
   recorded in `DECISIONS.md`, whose rejected alternatives explicitly include
   "carrying it and skipping at runtime".
3. **Evidence.** Explicitly supersede the old ten-client matrix and
   post-activation readback, bind both replacements to the resynchronized package
   fingerprint, and require a fresh ten-client assessment and readback before
   release and closeout.
4. **Mutating-verb correction.** Reclassify `fields create-option` as read-only,
   because its implementation only discovers and prints a field's existing
   options, and add a focused guard proving it invokes no write operation. Keep
   `fields set-options` classified as mutating and protected.

**Dependency graph.** `U0 → U1 → U2 → {U3, U4} → freeze → U5`. U3 and U4 are the
only pair that may run in parallel, which is inside the concurrency cap. U4 is
fingerprint-neutral because it touches only `tests/` and `ports/`, both outside
the package root; U3 edits `plugins/mission-control/plugin.json` and
`plugins/mission-control/README.md`, both inside it, so the freeze cannot precede
U3. `ports/mission-control.json` has exactly two writers in sequence, U1 then U3.
`plugins/mission-control/README.md` has one writer, U3.

### Out-of-scope / non-goals

- No custody move. `infiquetra/infiquetra-claude-plugins` stays authoritative and
  is never edited by this work.
- No downstream repair of copied content. A needed byte change goes upstream as a
  filing and returns through a later repin.
- No live GitHub mutation from any build, test, or assessment step.
- No per-client remediation, marketplace manifest work, or distribution changes.
  Client statuses are recorded; decisions on them stay open operator items, as
  the pilot decided.
- No Fleet Core repin and no bundle regeneration. `plugins/fleet-core` is
  unchanged upstream across this window.
- No return of `tests/test_prompt_alignment.py`. Its premises still fail here: the
  upstream file at the new pin still requires a sibling `plugins/saga/skills/handoff/SKILL.md`,
  which this catalog does not host, and cross-checks a marketplace entry this
  catalog's manifest does not carry.
- No change to `scripts/check_compatibility_matrix.py`. See Stop conditions.

### Inputs inventory

- Upstream read-only checkout at `3b2b7083`, plugin version 2.15.2, all four
  upstream workflows green at that exact commit.
- `ports/mission-control.json` — the port descriptor: package identity, custody
  table, `assessment` block, and the `provenance.notes` prose.
- `plugins/mission-control/PROVENANCE.json` — generated; current pin `84eaf042`,
  version 2.12.2, 63 file entries.
- `docs/runbooks/portable-plugin-port.md` v1.1.0 — the checklist. Written for an
  initial port; U0 records which steps a resync skips and why.
- `docs/retros/issue-9-2026-08-25.md` — lessons R1–R6, the eight upstream
  filings, and the recorded dispositions.
- `docs/engineering-journal/DECISIONS.md` — the resync-evidence decision, the
  `test_prompt_alignment.py` drop, the skill-frontmatter transform custody.
- Current package fingerprint: 64 files, tree
  `651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682`.
- Operator-supplied for U5 only: real binaries for the Grok and Agy launchers, and
  the real authenticated home for Cursor.

### Files expected to change

- `ports/mission-control.json`
- `plugins/mission-control/PROVENANCE.json`
- `plugins/mission-control/plugin.json`
- `plugins/mission-control/README.md`
- `plugins/mission-control/` — every byte copy and transform output under the package root
- `README.md`
- `tests/test_sync_vendor_source.py`
- `tests/test_mission_control_readme.py`
- `tests/test_check_compatibility_matrix.py`
- `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md`
- `docs/evidence/2026-08-25-mission-control-post-activation-readback.md`
- `docs/engineering-journal/DECISIONS.md`
- `docs/engineering-journal/QUEUED.md`

### Tests to add or update

- A derivation test binding `plugins/mission-control/plugin.json`'s version to
  `PROVENANCE.json`'s `source_version`, on the pattern already shipped for
  agent-launcher in `tests/test_agent_launcher_packaging.py`.
- A focused guard proving `fields create-option` invokes no write operation
  (operator ruling 4).
- Fingerprint-binding tests for the replacement mission-control matrix and
  readback, added to `tests/test_check_compatibility_matrix.py` as parallel
  classes rather than by parameterizing the existing UniFi bindings.
- Updated pins in `tests/test_sync_vendor_source.py`: `MISSION_CONTROL_PIN`,
  `MISSION_CONTROL_SKILLS`, and the `source_version` assertion.
- Updated `MUTATING_VERBS` and `READ_ONLY_VERBS` in
  `tests/test_mission_control_readme.py`.

### Failure modes / pre-mortem

**Most likely failure: the target-owned surface goes silently stale.** Three
files carry the version as unbound prose — `plugins/mission-control/plugin.json`,
`plugins/mission-control/README.md`, and the root `README.md` — and no test
checks any of them. The root README is worse: it also carries a 64-file count, a
266-test count, a twenty-one-test-file count, and a Packages-table row reading
`84eaf042` (v2.12.2), all unbound. This is the exact defect class the #9 review
caught once already, in U9's Packages table. U3 closes it by derivation, not by
hand-editing.

**Second: the generated provenance file contradicts itself.**
`scripts/sync_vendor_source.py` copies the descriptor's `provenance.notes` prose
verbatim into `PROVENANCE.json`. Those notes name the old pin and version, and
carry four line-number claims about `sdlc_manager.py`, one of which is not merely
stale but false at 2.15.2: the note says PyYAML is imported at module scope, and
upstream filing #828 moved that import into a function. Editing custody without
editing the notes ships a file whose header says 2.15.2 while its own prose says
2.12.2, and nothing catches it.

**Third: an assessment run is invalidated by a later byte change.** Any edit
inside `plugins/mission-control/` after the assessment retires it. The freeze must
follow U3, not precede it.

**Fourth: the mutating-verb change breaks a three-file lock.**
`tests/test_mission_control_readme.py` asserts the descriptor's audited verb set
equals its own constant and that every audited verb appears in the README. The
descriptor, the README, and the test constants move together in one commit or the
suite goes red.

### Stop conditions

Stop and report rather than continuing when any of these hold.

| Condition | Action |
|---|---|
| A confirmed fail-open in a security rule | Stop immediately. Never batch it with anything. |
| `--check` reports drift in a path classified `target-owned` | Stop. The sync would overwrite authored source. |
| Any transform rule refuses — the "expected exactly one" family | Stop. Never relax a rule's shape to fit new upstream bytes. |
| A byte copy's post-sync digest does not equal its source digest | Stop. |
| Upstream's `requires-python` has moved above this catalog's floor | Stop. The floor is part of the synchronization contract. |
| A needed byte change in copied content | Upstream filing, never a downstream patch. |
| Any live GitHub write from build, test, or assessment | Run-level stop. |
| A resync-forced edit to `scripts/port_config.py`, `scripts/check_repo.py`, `scripts/check_compatibility_matrix.py`, `scripts/assess_clients.py`, or `plugins/unifi/scripts/site_profile.py` | Stop and escalate. These five are the cycle-16 mutation proof's graded set; touching any retires that proof and forces a separate, expensive re-run. On the verified analysis a resync needs none of them. |
| Reviewers split on fact | Decide empirically; the reproduction is the arbiter. |
| Reviewers split on severity | Operator decides. |
| Any verification harness found unsound | Discard that round's evidence and re-run. |

### Context library links

- `docs/runbooks/portable-plugin-port.md` — the port runbook, v1.1.0
- `docs/retros/issue-9-2026-08-25.md` — the #9 migration retrospective
- `docs/engineering-journal/QUEUED.md` — the recorded resync policy
- `docs/engineering-journal/DECISIONS.md` — resync evidence, custody, transform decisions

### Acceptance criteria

- [ ] All six child units are closed, each with its base, frozen, and merged commit recorded.
- [ ] The pin is recorded as `3b2b7083` in both `ports/mission-control.json` and `plugins/mission-control/PROVENANCE.json`, proven by `python3 -c "import json;d=json.load(open('plugins/mission-control/PROVENANCE.json'));print(d['source_commit'],d['source_version'])"` printing `3b2b7083... 2.15.2`.
- [ ] `python3 scripts/sync_vendor_source.py --package mission-control --source <upstream> --commit 3b2b7083 --check` prints a match line and exits 0.
- [ ] `python3 scripts/check_repo.py` prints `Repository validation passed.`
- [ ] `python3 -m unittest discover -s tests` reports `OK` with no failures or errors.
- [ ] `python3 -m pytest plugins/mission-control/tests -q` passes on the floor interpreter.
- [ ] `git diff --check` produces no output.
- [ ] `python3 scripts/check_compatibility_matrix.py <new matrix>` prints `Compatibility matrix validation passed.`
- [ ] The two superseded documents each carry `matrix-status: superseded`, a `superseded-by` naming the current successor, and a `superseded-reason`.
- [ ] No path under `plugins/mission-control/` differs from its upstream source except the recorded transforms, proven by the `--check` round-trip above.

### Verification

```bash
# Pin and provenance
python3 -c "import json;d=json.load(open('plugins/mission-control/PROVENANCE.json'));print(d['source_commit'],d['source_version'])"

# Synchronization round-trip against the pinned upstream revision
python3 scripts/sync_vendor_source.py --package mission-control \
  --source ../infiquetra-claude-plugins --commit 3b2b7083 --check

# Repository gate and both suites
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
git diff --check

# Fingerprint the resynchronized package, then validate the new evidence
python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control
python3 scripts/check_compatibility_matrix.py docs/evidence/<new-matrix>.md
python3 scripts/check_compatibility_matrix.py docs/evidence/2026-08-25-mission-control-compatibility-matrix.md
```

### Handoff maturity
requirements-ready

### Suggested next action
Use `/plan <issue>` to create an implementation plan.

### Source context
- Source: session issue-shaping pass, 2026-08-30, validated against a fresh upstream fetch
- Source type: operator-settled shaping decisions
- Source title: Mission Control resynchronization 2.12.2 to 2.15.2 — settled shaping

### Recommended Tier Band
opus/high

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/50
- Number: 50
- Created at: 2026-08-30T19:22:51.956573+00:00

