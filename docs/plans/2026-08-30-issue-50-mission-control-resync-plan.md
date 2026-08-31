---
title: "Implementation plan — resynchronize the portable Mission Control package from upstream 2.12.2 to 2.15.2"
type: feat
status: active
date: 2026-08-30
origin: https://github.com/infiquetra/infiquetra-agent-plugins/issues/50
backend: inline
scope_class: deep
deepened: 2026-08-30
---

# Implementation plan — resynchronize the portable Mission Control package from upstream 2.12.2 to 2.15.2

**Issue.** [infiquetra/infiquetra-agent-plugins#50](https://github.com/infiquetra/infiquetra-agent-plugins/issues/50) ·
**Children.** #51 (U0), #52 (U1), #53 (U2), #54 (U3), #55 (U4), #56 (U5) ·
**Date.** 2026-08-30 ·
**Branch.** `orch-agent-plugins-50` ·
**Runbook followed.** `docs/runbooks/portable-plugin-port.md` v1.1.0 ·
**Backend.** inline for every unit ·
**Author role.** planner (`ap50-planner`); the operator is the sole coordinator.

Every measurement in this plan was taken in the planning session against the
working tree at `orch-agent-plugins-50` (clean, level with `origin/main` at
`0eff36e`) and against the read-only upstream checkout at
`../infiquetra-claude-plugins`. Where a number is quoted, the command that
produced it is given so a later reader can reproduce it rather than trust it.

---

## 1. Summary and problem frame

### 1.1 What this repository holds, and why a copy needs a plan at all

This repository, `infiquetra/infiquetra-agent-plugins`, is a portable source
catalog: it holds agent packages in a form that is not tied to any one coding
agent client. One of those packages, `plugins/mission-control/`, is not authored
here. It is a **derived copy** of a Claude Code plugin that lives upstream in a
different repository, `infiquetra/infiquetra-claude-plugins`. Upstream stays the
single writable source; this repository holds a copy that a tool regenerates.

The copy is pinned. `plugins/mission-control/PROVENANCE.json` currently records
upstream commit `84eaf042f0e350005f7eddf8e7d80da25c12119d`, upstream plugin
version `2.12.2`. Upstream has since released `2.15.2`, and has landed all eight
fixes that the earlier migration (issue #9) raised as upstream filings —
`infiquetra/infiquetra-claude-plugins` #818–#822 and #828–#830. Those fixes
reach this repository only by moving the pin and regenerating the copy.
`docs/engineering-journal/QUEUED.md` records that policy explicitly: never an
in-place edit, always a deliberate repin. This plan is that repin.

### 1.2 The two things that make this run non-trivial

**One: the synchronization tool refuses to run at all right now.** Upstream
2.15.2 adds eight new test files. The port descriptor `ports/mission-control.json`
assigns a custody class to every upstream path, and eight paths have no class, so
`scripts/sync_vendor_source.py --check` stops before it can measure anything else.
Reproduced this session:

```
$ python3 scripts/sync_vendor_source.py --package mission-control \
    --source ../infiquetra-claude-plugins --commit 3b2b7083 --check
ERROR: upstream paths carry no custody assignment, so synchronization would drop
them in silence: plugins/mission-control/tests/test_card_validator_agreement.py,
plugins/mission-control/tests/test_lifecycle_field_boards.py,
plugins/mission-control/tests/test_lifecycle_field_identity.py,
plugins/mission-control/tests/test_lifecycle_field_mutation.py,
plugins/mission-control/tests/test_lifecycle_field_routing.py,
plugins/mission-control/tests/test_lifecycle_writer_census.py,
plugins/mission-control/tests/test_option_identity.py,
plugins/mission-control/tests/test_sdlc_manager_optional_deps.py
```

That refusal is why the descriptor unit (U1) blocks the entire run: until custody
is assigned, no other drift in the package can even be reported.

**Two: moving the copy silently retires the evidence that describes it.** The
"package fingerprint" is a file count plus a digest of the package tree, computed
from disk. Two committed evidence documents — a ten-client compatibility matrix
and a post-activation readback — describe the package *at the old fingerprint*.
The moment the resynchronization lands, both stop describing the shipped bytes.
No test in this repository binds either of those two documents today, so that
retirement would happen without anything going red. Operator ruling 3 closes that
hole by requiring explicit supersession, fresh evidence, and binding tests.

### 1.3 What actually changes, measured

Thirty-six files differ between the two pins inside `plugins/mission-control/`,
with 7,706 lines added and 524 removed; twenty-eight are modified, eight are new,
and nothing is deleted.

```
$ git -C ../infiquetra-claude-plugins diff --stat 84eaf042 3b2b7083 -- plugins/mission-control | tail -1
 36 files changed, 7706 insertions(+), 524 deletions(-)
```

Broken down by the custody class each path carries in `ports/mission-control.json`
(computed this session by mapping every changed path against the descriptor's
custody table):

| Custody class | Files | Notes |
|---|---:|---|
| Upstream byte copy, already classified | 15 | regenerated verbatim by the sync tool |
| Deterministic transform output | 5 | `scripts/sdlc_manager.py` plus four of the seven `SKILL.md` files |
| Client byte copy (Claude adapter) | 5 | four commands and the `sdlc-operator` agent |
| Relocated Claude manifest | 1 | `.claude-plugin/plugin.json` → `com.infiquetra.claude/plugin.json` |
| Superseded upstream README | 1 | bytes are deliberately never read here |
| Already dropped from source | 1 | `tests/test_prompt_alignment.py`; changes upstream, lands nowhere here |
| New upstream paths, currently unclassified | 8 | seven become byte copies, one is excluded by ruling 2 |
| **Total** | **36** | |

The package therefore moves from **64 files to 71**: seven of the eight new test
files land, the eighth is excluded, and nothing is removed.

Three facts make this materially cheaper than the original port, all re-verified
this session:

- **Fleet Core needs nothing.** `git -C ../infiquetra-claude-plugins diff --stat 84eaf042 3b2b7083 -- plugins/fleet-core`
  produces no output. No bundle regeneration, no fleet-core repin.
- **All four transform premises still hold.** All seven `SKILL.md` files still
  carry the `when_to_use` key the frontmatter rule folds; `executor_profile_lint.py`
  is unchanged (its shim import is still at line 35 and `tier_palette` at line 89);
  the guarded fleet-shim block in `sdlc_manager.py` is byte-identical in shape and
  only moved line (`_load_intent_envelope` is now defined at line 5129), and the
  rule matches by pattern, not by line.
- **The Python floor has not moved.** `git -C ../infiquetra-claude-plugins show 3b2b7083:pyproject.toml | grep requires-python`
  prints `requires-python = ">=3.12"`, which is what this catalog declares.

### 1.4 Baseline, measured this session

| Signal | Value | Command |
|---|---|---|
| Repository gate | `Repository validation passed.` | `python3 scripts/check_repo.py` |
| Repository suite | `Ran 773 tests … OK` | `python3 -m unittest discover -s tests` |
| Package suite | `266 passed` | `python3 -m pytest plugins/mission-control/tests -q` |
| Whitespace gate | no output | `git diff --check` |
| Package fingerprint | 64 files, tree `651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682` | `python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control` |
| Package test files | 21 | `ls plugins/mission-control/tests/*.py \| wc -l` |
| Floor interpreter present | yes — resolves to `/opt/homebrew/bin/python3.12` on this machine | `command -v python3.12` |

### 1.5 What the engineering journal already settles

This repository has no `STRATEGY.md`, so the durable direction anchor for this
work is the engineering journal. Nine entries bear directly on this run, and the
plan honours all nine rather than re-deriving them.

| Journal entry | What it settles for this run | Where it lands |
|---|---|---|
| LEARNINGS — *Regenerating a build artifact retires the observational evidence bound to it* | Regeneration is exactly what retires the matrix and the readback. This is the mechanism behind operator ruling 3. | U5, risk 3 |
| LEARNINGS — *A bound digest names the tree, not the forty stages that assessed it* | A fingerprint proves identity, not assessment. Re-binding a digest is not the same act as re-running the forty stages. | U5, KTD11 |
| LEARNINGS — *A default interpreter is not evidence for a declared floor* | The local `python3` is 3.14.7; the declared floor is 3.12. Every package-suite run also runs on the floor. | §2.6, risk 12 |
| LEARNINGS — *A test that asserts on the machine it runs on reports the machine, not the code* | The precise reason the card-validator agreement test is excluded rather than carried-and-skipped. | KTD2, U1 |
| LEARNINGS — *A byte copy imports the upstream platform floor along with the upstream fix* | Why `requires-python` is re-read at the new pin instead of assumed. | R4, U0 |
| LEARNINGS — *Two portable slices of one upstream repository can legitimately pin two revisions* | Mission Control may move while Fleet Core stays put; that is not drift. | §9, R20 |
| LEARNINGS — *Package-root entrypoints must be blocked in advance for skill-scoped clients* | The assessment-harness quirk U5 inherits; a blocked row is the honest record. | U5 |
| DECISIONS — *A whole-repository drift guard is dropped when its premises cannot cross the port boundary* | The `test_prompt_alignment.py` precedent the agreement-test exclusion follows, including its explicitly rejected "carry it and skip at runtime" alternative. | KTD2, U1 |
| DECISIONS — *Schema 3 moved a graded file: the cycle-14 mutation proof is re-run with U8's evidence, not here* | Touching a graded file is a funded re-run, never a side effect. This is why KTD3 and KTD4 route around `scripts/port_config.py` and `scripts/check_compatibility_matrix.py`. | KTD3, KTD4, §2.8 |

Two further decisions constrain the target-owned surface: *Ported tests live
inside the package, under the provenance closed-set check* (why the seven new
tests are byte copies **inside** the package, U1) and *The portable
mission-control README's runnable surface is usage probes* (why U3 may edit the
portable README's tables and prose but may not introduce a runnable command that
invokes a mutating verb).

---

## 2. Execution contract carried forward

This section is fixed. No unit revisits any part of it, and no unit needs to read
the issues to know it — everything a unit must obey is restated inline below.

### 2.1 The pin

**Pin `3b2b7083fdda8e39e213b5f4acf9f8301d60dd52`.** Verified present in the
read-only upstream checkout, and verified to carry plugin version `2.15.2`:

```
$ git -C ../infiquetra-claude-plugins show 3b2b7083:plugins/mission-control/.claude-plugin/plugin.json \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['version'])"
2.15.2
```

Three upstream commits carry version 2.15.2 and their package trees are **not**
identical. Verified this session:

| Revision | Package tree | What it is |
|---|---|---|
| `379d2350` | `0fdcea0de13b7d48746f81c632f3da1666acc3a2` | where the version landed |
| `1111de33` | `a851eabb24bac6f539e9356f95e554d84bc4ea0b` | its document review |
| `3b2b7083` | `a851eabb24bac6f539e9356f95e554d84bc4ea0b` | the accepted merge — **this is the pin** |

Pinning `379d2350` would import content that its own review had already corrected
(the review repaired `CHANGELOG.md` and `skills/board/references/kanban-workflow.md`
inside the package without moving the version). Upstream is **never edited** by
this work, in any unit, for any reason.

### 2.2 The four operator rulings — binding, not re-litigated

1. **Pin 3b2b7083, and prove the upstream suite green there from a disposable
   scratch clone before any other unit starts.** Continuous integration reporting
   green is corroborating evidence, not the same act. U0 owns this and no unit may
   begin before U0's commit exists.
2. **Exclude `tests/test_card_validator_agreement.py` from the portable package**
   and record it in the descriptor's `dropped_from_source` (which the sync tool
   renders as `removed_from_source` in `PROVENANCE.json`). The upstream test stays
   upstream, unedited. Portable tests stay repository-local and hermetic. The
   package file count therefore goes 64 → 71, not 64 → 72.
3. **Supersede the old ten-client matrix and the old post-activation readback
   explicitly, bind both replacements to the resynchronized package fingerprint,
   and require a fresh ten-client assessment and readback before release.**
4. **Reclassify `fields create-option` as read-only and add a focused guard
   proving it invokes no write operation. Keep `fields set-options` classified as
   mutating and protected.**

### 2.3 The landing model

- **Branch.** All six units commit to `orch-agent-plugins-50`. No unit creates a
  worktree, a branch, a session, a subagent, or an issue.
- **Commits.** The run declaration says six child-scoped commits, one per unit.
  **That is not reachable**, and KTD15 proves it from four committed tests and the
  child issues' own clauses: the minimum that satisfies every inherited acceptance
  criterion was **eleven**, and Amendment 4 (KTD16) raises it to **twelve** — one more,
  for the descriptor reclassification the two remaining tests need. The rule's v2
  extension folds into U2b rather than taking a commit of its own (§18, D9). The
  increase is stated, not absorbed. This is a material deviation, raised as operator question
  **Q8**; the plan does not present eleven as a compatible reading of six. Unit
  boundaries, ownership, and acceptance criteria are unchanged — three units simply
  land in more than one commit. Each
  commit is conventional-commit shaped (`type(scope): description`) and its body
  carries `Refs #<child issue>` plus the base SHA the unit started from. Do not put
  a bare `(#nn)` in the subject line — GitHub appends the *pull request* number
  there on squash, and a hand-typed issue number in the same position reads as a PR
  number later.
- **Merge method.** Read before any text states a merge form (runbook entry
  criterion; lesson R1 from the #9 retrospective, where a squash-only policy was
  discovered at merge time after the plan had already promised a merge commit).
  Verified this session:

  ```
  $ gh repo view infiquetra/infiquetra-agent-plugins \
      --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed,defaultBranchRef
  {"defaultBranchRef":{"name":"main"},"mergeCommitAllowed":false,
   "rebaseMergeAllowed":true,"squashMergeAllowed":true}
  ```

  **A merge commit is forbidden. This run lands as one pull request,
  squash-merged into `main`.** See decision KTD8 for why squash over rebase, and
  open question Q1 for the operator confirmation this plan requests.
- **Per-child SHA record.** Each child issue records three commits: its **base**
  (the branch SHA it started from), its **frozen** commit (its own child-scoped
  commit on `orch-agent-plugins-50`), and the **merged** commit (the single squash
  SHA on `main`, shared by all six). That satisfies #50's acceptance criterion
  under squash; see KTD8.

### 2.4 The review contract

Carried forward from runbook v1.1.0 Phase 4 and the #9 retrospective, which
recorded fourteen review processes with thirteen accepted at cycle 1:

- **One review process per frozen revision.** Every review result carries a
  `revision_binding`; no review examines a moving target; nothing lands unreviewed.
- **Two reviewers in parallel, maximum three rounds.** Both independent; models
  confirmed by live readback before briefing; reviewers verify the commit id and a
  clean tree before scoring.
- **The orchestrator re-runs every gate first-hand before submission.** Evidence
  claims are probed, not relayed. This is what caught the defective probe records in
  #9's U7 before they were submitted.
- **The judgment-item pattern.** Every deviation from this plan, and every
  ambiguity a unit resolved on its own, is stated explicitly in the submission, so
  acceptance is informed rather than surprised.
- **Each round batches all confirmed findings** into one repair and one release.
- **Review artifacts** land under `docs/code-reviews/` (the location #9 used).
- **Predeclared review dimensions per unit** are listed in each unit section below.
  They are guidance for briefing the reviewers, not a new gate.

### 2.5 The backend

**Inline for every unit.** No workflow backend, for any unit, at any point.

### 2.6 The four gates every unit must pass

```bash
python3 scripts/check_repo.py                        # expect: Repository validation passed.
python3 -m unittest discover -s tests                # expect: OK
python3 -m pytest plugins/mission-control/tests -q   # expect: N passed
git diff --check                                     # expect: no output
```

**No unit carries a gate exception, and #53 is the only child issue that does not
require `unittest discover` `OK` at all.** That is why U2's two commits may be red on
the tests KTD15 names, and why every other unit's *completion* commit is green
outright — U1 at U1b, U3 at U3b, U4 at U4c, U5 at its single commit. An intermediate
commit inside a two- or three-commit unit is not that unit's completion and no
criterion is measured there (KTD15).

The runbook additionally requires the floor interpreter be confirmed **by explicit
path, never as `python3`** (entry criteria and Phase 0). The default `python3` on
this machine is 3.14.7; the declared floor and the continuous-integration
interpreter are both 3.12. So every unit that runs the package suite also runs it
once on the floor:

```bash
FLOOR_PY="$(command -v python3.12)"   # the declared floor, resolved by name, never `python3`
"$FLOOR_PY" -m pytest plugins/mission-control/tests -q
```

Every unit's verification block below assumes `FLOOR_PY` was exported this way at
the start of that unit's session. All six blocks run the same five lines — the four
mandated gates plus the floor run — so R36 is uniform and no unit's block is a
narrower gate than another's.

If the floor run needs third-party packages the interpreter lacks
(`pytest`, `pyyaml`, `requests`, `urllib3` — the set `.github/workflows/ci.yml`
installs), create them in a throwaway virtual environment outside the repository.
Never add a dependency file to the repository to make the floor run work.

### 2.7 Run-level stop conditions — every unit, always

Stop and report rather than continuing when any of these holds. A stop is a
finished unit that committed a blocked report, not a failure to deliver.

| Condition | Action |
|---|---|
| A confirmed fail-open in a security rule | Stop immediately. Never batch it with anything else. |
| `--check` reports drift in a path classified `target-owned` | Stop. The sync would overwrite authored source. |
| Any transform rule refuses — the "expected exactly one" family | Stop. Report the shape found. **Never relax a rule to fit new upstream bytes.** |
| A byte copy's post-sync digest does not equal its source digest | Stop. |
| Upstream's `requires-python` has moved above this catalog's floor | Stop. The floor is part of the synchronization contract. |
| A needed byte change in copied content | Upstream filing, never a downstream patch. |
| Any live GitHub write from build, test, or assessment | **Run-level stop.** |
| A resync-forced edit to `scripts/port_config.py`, `scripts/check_repo.py`, `scripts/check_compatibility_matrix.py`, `scripts/assess_clients.py`, or `plugins/unifi/scripts/site_profile.py` | **Stop and escalate.** See §2.8. |
| Reviewers split on fact | Decide empirically; the reproduction is the arbiter. |
| Reviewers split on severity | Operator decides. |
| Any verification harness found unsound | Discard that round's evidence and re-run. A harness that cannot fail proves nothing. |

### 2.8 The five graded files — why they are untouchable this run

`docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt` records a
mutation proof: sixty-eight deliberate mutations were injected into five files and
every one was killed by a test. The proof's footer pins those five files by
digest, and `MutationProofBindingTest` fails if a graded file's bytes change
without the proof being re-run. Editing any of the five retires the proof and
forces a separate, expensive re-run.

Verified this session — all five still match the cycle-16 footer exactly:

| Graded file | sha256 (matches footer) |
|---|---|
| `plugins/unifi/scripts/site_profile.py` | `31c9695f…7e5b09` |
| `scripts/assess_clients.py` | `2f8fafe9…1ad9d8` |
| `scripts/check_compatibility_matrix.py` | `1b03201c…6bfa4834` |
| `scripts/check_repo.py` | `6cf74eb9…3106f90a` |
| `scripts/port_config.py` | `bfaeb492…849c927b` |

On the verified analysis a resynchronization needs none of them. **The run's job
is to keep the proof standing.** Every place where a unit might be tempted to edit
one of the five, this plan names the non-graded file to edit instead.

---

## 3. Requirements

Each requirement is verifiable by a command or an inspectable artifact, and is
owned by exactly one unit.

| # | Unit | Requirement | Verified by |
|---|---|---|---|
| R1 | U0 | A disposable scratch clone at `3b2b7083` runs the upstream suite green, transcript pasted verbatim into the U0 note | the pasted transcript, command and output together |
| R2 | U0 | The three-revision package-tree comparison is recorded, showing `379d2350` at tree `0fdcea0d…` and `1111de33`/`3b2b7083` at tree `a851eabb…` | `git -C <scratch> rev-parse <rev>:plugins/mission-control` for each of the three |
| R3 | U0 | The pin carries plugin version `2.15.2` | `git -C <scratch> show 3b2b7083:plugins/mission-control/.claude-plugin/plugin.json` |
| R4 | U0 | The Python floor is unchanged at the pin | `git -C <scratch> show 3b2b7083:pyproject.toml \| grep requires-python` prints `>=3.12` |
| R5 | U0 | The repository's allowed merge methods are recorded before any run text states a merge form | `gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed` |
| R6 | U0 | The client-assessment plan prints without running anything, exit 0 | `python3 scripts/assess_clients.py --package mission-control` |
| R7 | U0 | The note names the runbook version followed (1.1.0) and lists every entry-criteria and phase step a resynchronization skips, each with a reason | inspection of the note |
| R8 | U1 | The seven hermetic new upstream tests are classified `upstream-byte-copy` in `ports/mission-control.json` | `custody.byte_copies` grows 42 → 49 at U1a; then 49 → 48 at U1b and 48 → 46 at U1c as the three package-root paths are reclassified (KTD14, KTD16) |
| R9 | U1 | `tests/test_card_validator_agreement.py` is recorded in `custody.dropped_from_source` with a stated reason in `provenance.dropped_reason` | `custody.dropped_from_source` grows 2 → 3 |
| R10 | U1 | `--check` no longer refuses for unclassified paths and instead reports real content drift | `python3 scripts/sync_vendor_source.py --package mission-control --source ../infiquetra-claude-plugins --commit 3b2b7083 --check` |
| R11 | U1 | `provenance.notes` names pin `3b2b7083` and version `2.15.2`, and no longer claims PyYAML is imported at module scope in `sdlc_manager.py` | inspection of `ports/mission-control.json` |
| R12 | U1 | The four surviving line-number claims are correct at the new pin | `grep -n` against the pinned upstream files (unit U1) |
| R13 | U1 | The `test_prompt_alignment.py` drop is re-verified at the new pin and the re-verification recorded | `DECISIONS.md` entry citing the two failed premises |
| R14 | U1 | A `DECISIONS.md` entry records the agreement-test exclusion and the re-verified drop, each with rejected alternatives and a revisit condition | inspection |
| R15 | U2 | The synchronization completes and round-trips clean: re-running with `--check` prints a match line naming `3b2b7083` and exits 0 | the two commands in unit U2 |
| R16 | U2 | `PROVENANCE.json` records `source_commit` `3b2b7083…` and `source_version` `2.15.2` | `python3 -c "import json;d=json.load(open('plugins/mission-control/PROVENANCE.json'));print(d['source_commit'],d['source_version'])"` |
| R17 | U2 | The package holds exactly 71 files | `git ls-files plugins/mission-control \| wc -l` prints `71` |
| R18 | U2 | The excluded agreement test is absent from the package | `test ! -e plugins/mission-control/tests/test_card_validator_agreement.py` |
| R19 | U2 | All four transform premises are proven to hold at the new pin rather than assumed | the transform-premise checks in unit U2 |
| R20 | U2 | No fleet-core repin and no bundle regeneration | `git diff --name-only <base>..HEAD -- plugins/fleet-core plugins/mission-control/scripts/_bundled plugins/mission-control/fleet-bundle.json \| wc -l` prints `0` |
| R21 | U3 | `assessment.mutating_operations` contains `set-options` and does not contain `create-option` | `python3 -c "import json;m=json.load(open('ports/mission-control.json'))['assessment']['mutating_operations'];print('set-options' in m, 'create-option' in m)"` prints `True False` |
| R22 | U3 | The portable README's verb table lists `set-options` as mutating for `fields`, lists `create-option` as read-only, and no longer lists `update` under `rollout` — in the same commit as the descriptor and the test constants | `python3 -m unittest tests.test_mission_control_readme -v` |
| R23 | U3 | A guard test proves `fields create-option` invokes no write operation, and fails if a mutation path is reached | `python3 -m unittest tests.test_mission_control_rule_audit -v`, plus a deliberate reverted local mutation showing it goes red |
| R24 | U3 | `plugins/mission-control/plugin.json` reports version `2.15.2` and a test binds it to `PROVENANCE.json`'s `source_version` so the two cannot diverge | the derivation test; `python3 -c "…assert m['version']==p['source_version']"` |
| R25 | U3 | The root `README.md` states the new pin, version, file count, and test counts, and its Mission Control Packages-table row is pinned by a test | the pin test in `tests/test_mission_control_rule_audit.py` |
| R26 | U4 | `MISSION_CONTROL_PIN` equals the new pin, the `source_version` assertion reads `2.15.2`, and `MISSION_CONTROL_SKILLS` is confirmed against the shipped roster | `python3 -m unittest tests.test_sync_vendor_source -v`; `ls plugins/mission-control/skills` |
| R27 | U4 | U4 changes no file under `plugins/mission-control/` (it is fingerprint-neutral) | `git diff --name-only <base>..HEAD -- plugins/mission-control \| wc -l` prints `0` |
| R28 | U4 | PyYAML stays in the continuous-integration install line | inspection of `.github/workflows/ci.yml` line 59 plus the two surviving module-scope imports |
| R29 | U5 | The package fingerprint is captured before and after the assessment and is identical | `python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control`, twice, recorded |
| R30 | U5 | A fresh ten-client, forty-stage assessment ran against the frozen package | the assessment record produced by `scripts/assess_clients.py --execute` |
| R31 | U5 | The new compatibility matrix validates | `python3 scripts/check_compatibility_matrix.py docs/evidence/<new-matrix>.md` prints `Compatibility matrix validation passed.` |
| R32 | U5 | The new readback records the release block, all seven per-skill-unit fingerprints, and every client readback | the readback binding test |
| R33 | U5 | All four superseded mission-control documents — the 2026-08-25 pair and the 2026-08-30 `-pre-fingerprint-move` pair — carry `matrix-status: superseded`, a `superseded-by` naming a successor that exists and is itself current, and a `superseded-reason` | the superseded-document test class in `tests/test_check_compatibility_matrix.py` (the chain); the checker accepts the matrix's directives but is not a readback validator, so the readback half is test-bound only |
| R34 | U5 | New binding classes in `tests/test_check_compatibility_matrix.py` fail if either replacement's recorded fingerprint stops matching the live package | a deliberate local mutation that makes them red, then reverted, with the transcript captured |
| R35 | U5 | No graded file changed | `git diff --name-only <base>..HEAD -- scripts/port_config.py scripts/check_repo.py scripts/check_compatibility_matrix.py scripts/assess_clients.py plugins/unifi/scripts/site_profile.py \| wc -l` prints `0` (the five cycle-16 graded files by name; KTD14 legitimately edits `scripts/sync_vendor_source.py`, which is not graded) |
| R36 | all | The four mandated gates are green at each unit's frozen commit, plus the floor-interpreter package run | §2.6 |
| R37 | all | No live GitHub mutation from any build, test, or assessment step | run-level stop condition; assessment runs read-only verbs only |
| R38 | all | Unrelated dirty files, branches, worktrees, and sessions are preserved untouched | `git status --porcelain` before and after each unit, compared |
| R39 | U3, U4 | U4's pin-constant commit (U4b) precedes U3a on `orch-agent-plugins-50`, and U3a is rebased onto it, so the pin constants are never U3's problem (KTD10, KTD15) | `git log --oneline` shows U4b as U3a's parent |
| R40 | U1, U2 | `scripts/sync_template_docs.py` is classified `deterministic-transform` in `ports/mission-control.json` (U1's second commit) under a named rule authored in `scripts/sync_vendor_source.py` (U2), and the portable copy imports cleanly in the portable layout (KTD14) | the module imports without `RuntimeError`; the four repository-suite failures and two package-suite collection errors that trace to it clear |
| R41 | U2 | The new rule is deterministic and reproducible from the upstream bytes alone — re-running the synchronization produces byte-identical output (KTD14) | the `--check` round-trip in U2 prints a match line and exits 0 |
| R42 | U4 | `tests/test_sync_vendor_source.py` covers the new rule: it matches exactly once against the upstream bytes at the pin, refuses when the function is missing or duplicated, and is a no-op on already-portable input (KTD14, KTD15) | `python3 -m unittest tests.test_sync_vendor_source -v` |
| R43 | U1, U3, U4, U5 | Every unit's inherited `unittest discover` criterion reports `OK` **at that unit's completion**, with no expected-red list and no moved checkpoint; U1, U2 and U3 complete in two commits and U4 in three to make that reachable (KTD15) | each unit's final commit carries a full four-gate transcript showing `OK` |
| R44 | U2, U4, U1 | The new transform rule is registered (U2a), its pinned registry-name set repaired (U4a), and only then named by the descriptor (U1b) — the order two committed tests force (KTD15 P1, P2) | `git log --oneline` shows that order; `python3 -m unittest tests.test_port_config tests.test_sync_vendor_source -v` reports `OK` at U1b |
| R45 | U1, U2, U4 | `tests/test_issue_contract_parity.py` and `tests/test_template_sync.py` are classified `deterministic-transform` under the extended package-root rule, both collect and pass in the portable layout, and the package still holds **71** files (KTD16) | `git ls-files plugins/mission-control \| wc -l` prints `71`; `python3 -m pytest plugins/mission-control/tests -q` passes on the floor interpreter |
| R46 | U2 | The extended rule declares its expected site counts per file, refuses loudly on any count mismatch, is idempotent on already-portable input, and is reproducible from the upstream bytes alone (KTD16) | a deliberate count mismatch produces a refusal naming file, site class, and counts; re-running the transform is a no-op |

---

## 4. Key Technical Decisions

Each decision names what was chosen, why, what was rejected, and when to revisit
it. Decisions KTD1, KTD2, KTD12 and the substance of KTD4 restate operator rulings and are
not open; the rest are planner calls made under "never stop on a question", and
each records the option taken and the reason.

### KTD1 — Pin the accepted merge `3b2b7083`, not the version-landing commit

**Chosen.** `3b2b7083` (operator ruling 1).
**Why.** Three commits carry version 2.15.2 with two distinct package trees.
`379d2350` landed the version; its own document review (`1111de33`) then repaired
`CHANGELOG.md` and `skills/board/references/kanban-workflow.md` *inside the
package* without moving the version. `3b2b7083` is the accepted merge and shares
the reviewed tree `a851eabb…`.
**Rejected.** (a) `379d2350` — imports content its own review already corrected.
(b) `1111de33` — carries the right tree but is not the accepted revision, so its
provenance sentence would be weaker. (c) upstream `origin/main` HEAD — a moving
target; the pin must name bytes, not a branch.
**Revisit when.** Upstream releases a version above 2.15.2 and a further resync is
scheduled.

### KTD2 — Exclude the card-validator agreement test; do not carry-and-skip it

**Chosen.** Record `tests/test_card_validator_agreement.py` in the descriptor's
`dropped_from_source` (operator ruling 2).
**Why.** That test loads an authority module from outside any repository —
searching `HOME_LAB_PATH`, then `INFIQUETRA_HOME_LAB_PATH`, then
`~/workspace/infiquetra/home-lab`, then `~/workspace/home-lab`, then sibling
directories — and skips loudly when absent. Carrying it makes a test's verdict
depend on what else happens to be on the machine's disk, which is the exact defect
class `QUEUED.md` already names about the link checker: a gate that reports the
environment rather than the repository.
**Rejected.** (a) Carry it as a byte copy and let it skip at runtime — the
recorded `test_prompt_alignment.py` drop already rejected this as deadweight that
misrepresents its own coverage. (b) Carry it with a repository-local stub of the
authority module — that would make the portable copy assert agreement with a fake,
which is worse than not asserting it. (c) Classify it as a byte copy to make the
tool stop complaining — the tool refuses on *unclassified*, not on *wrongly
classified*, so this would silence the error and ship the defect.
**Revisit when.** The home-lab authority module becomes available as a pinned,
in-repository dependency.

### KTD3 — Extend the single `provenance.dropped_reason` string; do not make it a map

**Chosen.** Append the agreement test's reason to the existing single
`provenance.dropped_reason` string in `ports/mission-control.json`.
**Why.** Verified this session: `dropped_reason` is a **single string**
(`scripts/port_config.py` asserts `isinstance(dropped_reason, str)` at line 639),
and `scripts/sync_vendor_source.py` copies that same string into every
`removed_from_source` entry's `reason` field. The existing string already
concatenates two paths' reasons in one blob, so a third follows the shipped
convention exactly.
**Rejected.** Turn `dropped_reason` into a per-path mapping. It reads better, but
it is a descriptor **schema change**, which forces an edit to
`scripts/port_config.py` — one of the five graded files — and trips a hard stop
condition for a cosmetic gain. This is precisely the trap U1's own stop-condition
table names.
**Revisit when.** A separate, funded unit is willing to re-run the cycle-16
mutation proof; then the mapping is the right shape.

### KTD4 — Add the evidence bindings to the test file, never to the checker script

**Chosen.** Add parallel mission-control binding classes to
`tests/test_check_compatibility_matrix.py`.
**Why.** `scripts/check_compatibility_matrix.py` is graded (§2.8). The test file
is not. The binding pattern already lives there (`PACKAGE_ROOT`, `REAL_CONFIG`,
`FingerprintTest`, `PackageBindingTest`, `LiveDocumentTest`), all currently scoped
to UniFi via `PACKAGE_ROOT = ROOT / "plugins" / "unifi"` and
`REAL_CONFIG = port_config.load("unifi", ROOT)`.
**Rejected.** (a) Teach the checker script to bind mission-control documents —
retires the mutation proof for no functional gain. (b) Parameterize the existing
UniFi classes over both packages — puts UniFi's live, passing bindings at risk to
save duplication, and a fixture regression there would be a self-inflicted wound
on a package this run is not touching.
**Revisit when.** A third package needs bindings; at that point parameterization
earns its risk and should be done as its own unit with UniFi re-verified.

### KTD5 — Derive the package manifest version instead of retyping it

**Chosen.** `plugins/mission-control/plugin.json` carries `2.15.2`, and a new test
asserts it equals `PROVENANCE.json`'s `source_version`, on the pattern already
shipped in `tests/test_agent_launcher_packaging.py`.
**Why.** The #9 run's single review finding was a hand-transcribed identity cell
with no derivation and no pin test. Retyping the version reproduces that defect one
release later.
**Rejected.** Hand-edit plus reviewer discipline — that is exactly what failed in
#9's U9 Packages table.
**Revisit when.** Never; this is the closing move on a known defect class.

### KTD6 — Pin the root README's counts by test rather than retype or generate them

**Chosen.** Update the root `README.md` claims and add a pin test in
`tests/test_mission_control_rule_audit.py` that recomputes the file count and the
package test count from disk and asserts the README states them.
**Why.** The root README carries four unbound claims at three sites — verified
this session at lines 30–31, 71–75, and 163: a 64-file count, a 266-test count, a
twenty-one-test-file count, and a Packages-table row reading `84eaf042` (v2.12.2).
None is checked by anything today. A test that recomputes from disk fails when the
package moves; a retyped constant does not.
**Rejected.** (a) Retype the numbers — reproduces the #9 finding. (b) Derive them
at gate time inside `scripts/check_repo.py` — that is a graded file and a hard stop
condition. (c) Generate the README section from a script — new machinery, new
surface, and the runbook's own rule is "derived from its authority file **or**
pinned by a test in the same commit"; the pin test satisfies it at a fraction of
the cost.
**Revisit when.** A third package's row goes stale, which would argue for one
shared catalog-row test instead of per-package pins.

### KTD7 — `DECISIONS.md` has three sequential writers, appending under distinct anchors

**Chosen.** U1, U3, and U5 each append their own dated entry to
`docs/engineering-journal/DECISIONS.md`, in that order, never concurrently.
**Why.** The global journal rule is that a decision entry ships **in the same
commit as the change it explains**. Collecting all three into one unit would break
that rule and would also make one unit answerable for two other units' reasoning.
U1 → U3 is a strict dependency edge, U3 → U5 likewise, and U4 (the only unit
concurrent with U3) does not write this file, so three writers never collide.
**Rejected.** (a) A single journal unit at the end — breaks same-commit capture and
weakens the entries. (b) Three separate files merged later — invents a structure
the repository does not have.
**Mechanics.** Each writer appends a new `## ` section at the end of its subject
area and touches no line another unit wrote. If a unit finds it must edit an
existing entry, that is a signal the earlier entry was wrong: stop and report
rather than silently rewriting another unit's recorded reasoning.
**Note.** This is the one place this plan departs from the brief's "no two units
share a writable file" rule. The issue bodies mandate the three edits (#52, #54,
#56 all list `DECISIONS.md` under *Files expected to change*), and issue bodies
win. Recorded as open question Q6.

### KTD8 — One pull request, squash-merged

**Chosen.** A single pull request from `orch-agent-plugins-50` into `main`,
**squash-merged**.
**Why.** A merge commit is forbidden by repository settings
(`mergeCommitAllowed: false`, read this session). Between squash and rebase, squash
matches every landing this repository has actually done: `main` is linear and every
commit from #35 through #49 is a squash carrying its pull-request number, and the
#9 retrospective explicitly verifies its four merges as squashes
(`8e2b47b`/`3948525`/`d23cb91`/`ef04797`). #50's acceptance criterion — "each with
its base, frozen, and merged commit recorded" — is satisfied under squash by
recording each child's base and frozen SHAs from the branch alongside the shared
merged SHA (§2.3).
**Rejected.** (a) Rebase-merge to keep six commits on `main` — allowed by settings
and it would give six distinct merged SHAs, but rebase rewrites the SHAs anyway, so
the traceability gain over recording branch SHAs is marginal, and it would be the
first non-squash landing this repository has ever made. (b) Six separate pull
requests — six review cycles and six rebases for a run whose units are already
serialized on one branch, and it fragments the freeze. (c) A merge commit —
forbidden.
**Revisit when.** The operator answers Q1 the other way; the switch is a
one-setting change at merge time and costs the plan nothing.

### KTD9 — The freeze follows U3, not U2

**Chosen.** Freeze the package fingerprint after U3's commit is integrated.
**Why.** The fingerprint is computed from every byte under
`plugins/mission-control/`. U3 edits two files inside that root — `plugin.json`
and `README.md` — so the fingerprint is not final until U3 lands. Any assessment
run before that would describe bytes that no longer exist.
**Rejected.** Freeze after U2 and treat U3's edits as "documentation only" — the
fingerprint does not care what a file means, only what its bytes are.
**Revisit when.** Never; this is arithmetic, not preference.

### KTD10 — U3 and U4 work concurrently at two workers, but land in a fixed order: U4 first, then U3 rebased onto it

**Chosen.** Two concurrent workers, U3 and U4, both starting work from the
integrated post-U2 commit. **The landing order is serialized: U4 commits first;
U3 then rebases onto U4's pin-constant commit (U4b), runs its gates on that
integrated tree, and commits after it.**

**Why.** Concurrency and commit order are different things, and conflating them
is what produced doc-review finding D1. After U2, `python3 -m unittest discover -s
tests` is red on exactly three constants in `tests/test_sync_vendor_source.py`
(`MISSION_CONTROL_PIN` at line 1359, the `source_version` assertion at line 1382,
and the roster the frontmatter checks drive). Issue #54 requires that command to
report `OK` for U3, and U3 does not own that file — U4 does. If both units cut
independent commits from the post-U2 tree, U3's implementer faces a suite that is
red for a reason U3 is forbidden to fix, and the only ways out are stopping on a
red gate or reaching into U4's file and breaking ownership. Rebasing U3 onto U4
removes the contradiction without touching a single acceptance criterion: U3's
`unittest discover` then runs on a tree where the pin constants are already
repaired, and reports `OK` with **no exception clause of any kind**.

Nothing about the declared graph changes. `U0 → U1 → U2 → {U3, U4} → freeze → U5`
still holds, "at most two-wide" still holds — it caps concurrent *workers*, and
never required two independent commit bases — and the freeze still follows U3,
which is still the last unit to touch bytes inside the package root. The wall-clock
overlap is preserved: U3's implementer does its reading, its verb-table analysis,
and its test authoring while U4 runs, and pays only a rebase at the end.

**Rejected.** (a) **Both units commit independently from post-U2** — the original
wording, and the defect D1 names: U3's #54 gate cannot pass. (b) **Give U3 the same
named pin-constant exception U2 carries, and move #54's `unittest discover` OK line
to freeze integration** — the reviewer's second option, and it is the one that
narrows an inherited acceptance criterion. #54's criteria are inherited from the
issue and are not the plan's to weaken; a gate moved to a later checkpoint is a
weaker gate, whatever it is called. Rejected on that ground alone. (c) **Full
serialization of the work as well as the landing** — gives up the overlap for
nothing, since the file sets are disjoint and only the commit order was ever the
problem. (d) **Three-wide** — nothing else is ready; U5 needs the freeze and U0–U2
are done.

**Revisit when.** U3's scope grows to touch a file U4 owns (then serialize the work
too), or a future run gives U3 a gate that no longer depends on U4's file.

### KTD11 — The replacement readback keeps a `cycle_16_verification` equivalent

**Chosen.** The new post-activation readback carries a `cycle_16_verification`
block with the same key name, the same `proof_document` reference, the five graded
files' digests recomputed at the new freeze, and the new frozen candidate commit.
(Issue #56 asks for this to be "decided explicitly"; this is the decision.)
**Why.** Verified this session: all five graded-file digests on the current tree
match the cycle-16 footer exactly (§2.8), and none of the five is touched by a
resynchronization. So the block is not merely carried forward — it becomes a
*positive statement that the resynchronization retired no mutation proof*, which is
the single most valuable thing the readback can say about a run whose main risk is
exactly that.
**Rejected.** (a) Drop the block — throws away the strongest available evidence
that the run stayed inside its lane. (b) Rename it to something generic — breaks
continuity with the cycle-16 artifact a reader would go looking for.
**Revisit when.** A future run edits a graded file and re-runs the proof at a new
cycle number; the block then names that cycle.

### KTD12 — `fields create-option` becomes read-only, with a positive no-write guard

**Chosen.** Move `create-option` from the mutating set to the read-only set, add
`set-options` to the mutating set, and add a guard test proving `create-option`
reaches no write path (operator ruling 4).
**Why, verified at the pin.** `fields_create_option` is defined at
`scripts/sdlc_manager.py:2026` and its docstring at line 2029 states "This command
performs NO mutation — it never has." `fields_set_options` is defined at line 2070
and calls `update_field_single_select_options` at line 2113, which issues a real
mutation unless `--dry-run` is passed.
**Why a guard is required.** Reclassifying a verb from mutating to read-only
*narrows a safety declaration*. A narrowed safety claim needs positive proof, not a
changed constant. The guard must assert the mutation path is never reached — a test
that merely asserts the function returns without error proves nothing about writes.
**Rejected.** (a) Reclassify without a guard — a one-line narrowing of a safety
boundary with no evidence. (b) Leave `create-option` mutating "to be safe" — it
over-declares, which pollutes the audited table and makes the README's disclosure
false in the other direction.
**Revisit when.** Upstream changes either handler's implementation.

### KTD13 — Evidence documents are dated by their assessment date, not by plan date

**Chosen.** The new matrix and readback filenames carry the date the ten-client
assessment actually ran, following the shipped convention
(`docs/evidence/2026-08-25-mission-control-*.md`).
**Why.** Every evidence document in `docs/evidence/` is named for when it was
observed. A document named for the day it was planned would misdate an observation.
**Rejected.** Name them for the plan date, or for the pin. Both make the filename
lie about when the forty stage results were produced.

### KTD14 — `scripts/sync_template_docs.py` becomes a deterministic transform that resolves the package root through the portable layout's own marker

**Added by Amendment 1 (§14). This decision postdates the accepted Document
Review; it was reviewed by doc-review cycle 3 (commit `8cd5fec`) and its four
findings were repaired in commit `4083220`.**

**The blocker, reproduced on this tree.** Upstream 2.15.2 rewrote the carried byte
copy `scripts/sync_template_docs.py`. At pin `3b2b7083` it defines
`_find_package_root()` at line 17, which walks up the directory tree looking for
`.claude-plugin/plugin.json` (line 20) and raises `RuntimeError` when it finds none
(line 22). That function is called **at module scope**, line 27:
`PACKAGE_ROOT = _find_package_root()`. The portable package has no
`.claude-plugin/` directory at all — the `relocate-claude-manifest` rule moves the
Claude manifest to `com.infiquetra.claude/plugin.json`. So the module cannot be
imported here:

```
RuntimeError: package root containing .claude-plugin/plugin.json not found from
  …/plugins/mission-control/scripts/sync_template_docs.py
```

Four failures in `python3 -m unittest discover -s tests` trace to this one cause —
both `tests/test_client_entrypoints.py` checks for this entrypoint, the
`tests/test_mission_control_readme.py` fenced-command check, and the loader error on
`tests/test_mission_control_rule_audit.py` — plus two collection errors in the
package suite, `tests/test_issue_contract_parity.py` and `tests/test_template_sync.py`.

**The irony, recorded because it is instructive.** This repository filed upstream
`infiquetra/infiquetra-claude-plugins` **#822** asking upstream to remove the fixed
`parents[3]` depth assumption from this exact file. Upstream did fix it — by
anchoring to `.claude-plugin/plugin.json`, which is precisely the directory the port
relocates away. Upstream is not wrong for its own layout. A fix that is correct
upstream can still be unusable downstream, and the port boundary is where that shows
up.

**Chosen.** Reclassify `scripts/sync_template_docs.py` from `upstream-byte-copy` to
`deterministic-transform`, under a **new versioned rule** that resolves the package
root through the portable layout's own marker, `com.infiquetra.claude/plugin.json`,
instead of `.claude-plugin/plugin.json`. The rule is written by a worker in U2; this
plan does not author it.

**Who does which part (corrected by Amendment 2, doc-review finding D5).** Amendment 1
gave all three files to U2, which contradicted issue #53's own out-of-scope section —
it says "No edit to `ports/mission-control.json`" and "No downstream test edits." #53
is authoritative and is not the plan's to rewrite, so each part goes to the unit that
already owns the file:

| Part | Unit | Why that unit |
|---|---|---|
| Reclassify the path in `ports/mission-control.json` | **U1** (#52) | U1 owns the descriptor. U1 has already landed at `12c889c`, so this is **a second commit against the same unit**, not a rewrite of the first. |
| Author the transform rule in `scripts/sync_vendor_source.py` | **U2** (#53) | The file has no owner in the original plan and #53 does not forbid it. U2 is the unit that runs the synchronizer. |
| Cover the rule in `tests/test_sync_vendor_source.py` | **U4** (#55) | U4 owns that file, and #53 forbids U2 from touching downstream tests. |

The descriptor edit must land **before** U2's synchronization run — a sync against the
old classification would re-copy the unimportable bytes — so U1's second commit is
sequenced ahead of U2 (§5, §8.1).

**Match unit (so "exactly one" is not a judgment call).** The rule matches the
single `_find_package_root` definition (pin lines 17–25) together with the single
module-scope `PACKAGE_ROOT = _find_package_root()` call (line 27). The two
`.claude-plugin` sites inside that function — the Path check
`parent / ".claude-plugin" / "plugin.json"` at line 20 and the error text at
line 23 — are internals of that one function, not two rule matches. A literal
search for the concatenated string `.claude-plugin/plugin.json` hits only the
error text (one occurrence at the pin) and leaves the Path check looking for
`.claude-plugin`, so the import still fails. Already-portable input (the marker
already `com.infiquetra.claude`) is a no-op, the same idempotence
`normalize-skill-frontmatter` gives a file with no `when_to_use`. Refuse if the
function is missing, duplicated, or the module-scope call is absent.

**Why this path and not an upstream filing.** The run contract names **both**
"upstream filing" and "a recorded custody decision" as legitimate resolutions when a
carried file cannot work unchanged in the portable layout (§2.7). Between them:

- An upstream filing **blocks the entire resynchronization** until upstream fixes it
  and this repository repins. Nothing else in this run can land in the meantime.
- The custody path has **direct precedent in this repository**.
  `normalize-skill-frontmatter` is the identical shape: upstream keeps a form the
  portable layout cannot take verbatim, and a versioned rule transforms it
  deterministically, reproducible from the source bytes alone. The
  `resolve-bundled-fleet-module-split` and `resolve-bundled-fleet-module-guarded`
  pair is the same pattern applied to a different import problem. This is the third
  instance of a shape the repository already runs twice.
- `scripts/sync_vendor_source.py` is **not** in the cycle-16 mutation proof's graded
  set (§2.8 lists the five, and it is not among them), so adding a rule there does
  not retire that proof.

**Rejected.** (a) **Hand-edit the byte copy** — the custody violation this whole
arrangement exists to prevent, and the one U2's stop conditions name explicitly. A
hand-edited copy also fails its own digest check. (b) **Drop the file from source,
the way `scripts/fleet_commons_shim.py` is dropped** — it is a declared entrypoint
in both `assessment.entrypoints` and `assessment.package_scripts`, so dropping it
would silently shrink the package's capability surface. The shim was dropped because
the bundle *replaces* it; nothing replaces this. (c) **File upstream and stop** —
blocks the run for a defect that is not upstream's to carry, since upstream's
resolution is correct for upstream's layout. (d) **Plant a dummy `.claude-plugin/`
directory in the portable tree so upstream's walk finds a marker** — added by
Amendment 2, because it is the obvious hack and its absence from this list was a gap.
It is wrong on four counts, any one of which is disqualifying. It reintroduces the
Claude-specific directory the port exists to relocate, contradicting the repository
boundary that Claude adapter material lives under `com.infiquetra.claude/`. It is not
a contract path: the file would stay a byte copy whose behaviour depends on a
*sibling file* rather than on its own bytes, so nothing in `PROVENANCE.json` would
record why the package works. It inflates the package fingerprint with a file that
exists only to satisfy a search, and every piece of evidence in this run then binds
that inflated tree. And it fails in the direction that matters — a consumer who
installs the documented portable layout without the dummy directory gets the same
`RuntimeError` this decision exists to remove.

**Revisit when** upstream adopts a layout-neutral package-root resolution — one that
does not hard-code a single marker directory. At that point the transform can retire
and the file can return to being a byte copy.

### KTD15 — Every unit completes green; the rule is registered before anything names it; the run needs eleven commits, not six

**Rewritten by Amendment 3 (§16). This resolves doc-review finding D4 and raises
operator question Q8.**

#### The four prerequisites, all verified in code

**P1 — a descriptor may only name a rule that is already registered.**
`tests/test_port_config.py::CommittedDescriptorTest.test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements`
(lines 561–575) loads every descriptor and asserts
`self.assertIn(rule, svs.TRANSFORM_RULES)`. `scripts/sync_vendor_source.py`'s
`resolve_transform_rule` refuses an unregistered name the same way, so `--check`
would refuse too. **Amendment 2 had this backwards**: it put U1's descriptor edit
before U2 authored the rule, so U1's completion commit named a rule that did not
exist and `unittest discover` failed. #52 requires that command to report `OK`.

**P2 — registering a rule breaks a test that pins the registry by name.**
`tests/test_sync_vendor_source.py::MissionShapedSyncTests.test_rule_names_register_exactly_once`
(lines 919–931) asserts `set(svs.TRANSFORM_RULES)` equals a literal five-element
set built from the `*_TRANSFORM_NAME` constants. A sixth rule fails it. That file is
`tests/test_sync_vendor_source.py`, which **U4 owns** under #55, and #53 forbids U2
from editing downstream tests. So registering the rule and repairing the registry
test are two units' work and cannot share a commit. Amendment 2 missed this
entirely; the doc review did not reach it either.

**P3 — the pin constants can only move after the synchronization.**
`test_provenance_pins_the_audited_revision` compares `MISSION_CONTROL_PIN` against
`PROVENANCE.json`. Setting the constant before U2 rewrites the manifest just moves
the failure, so U4's pin edit must follow U2's sync run.

**P4 — the evidence can only be re-bound after the last package-root edit.**
`check_package_binding` compares live `file_count` and `tree_sha256`
(`scripts/check_compatibility_matrix.py` 406–440), and `check_document_status`
accepts a superseded stamp only when the named successor already exists and is
itself current (496–525). U3 is the last unit to touch the package root, so U5
cannot run before U3's package-root edits land — and until U5 lands,
`test_check_compatibility_matrix.LiveDocumentTest.test_the_no_argument_run_validates_every_committed_matrix`
is red.

#### Six commits is impossible — the proof

Six child-scoped commits, one per unit, cannot satisfy the inherited acceptance
criteria. Not "is hard to"; cannot. The argument is short and each step is one of
the four prerequisites above plus one issue clause.

1. #52 requires `unittest discover` `OK` at U1's completion, and #52's own
   out-of-scope confines U1 to the descriptor: "This unit changes the descriptor
   only; U2 runs the sync."
2. By **P1**, U1's descriptor commit is green only if the rule is already
   registered. U1 may not register it (step 1). #51 confines U0 to "verifies and
   records", so U0 may not either. `scripts/sync_vendor_source.py` therefore has to
   be written by U2 — and by **P1** that write must land **before** U1's commit,
   while U2's synchronization run must land **after** it, because the sync reads the
   reclassified descriptor. **U2 needs two commits.**
3. By **P2**, the commit that registers the rule leaves the registry test red, and
   only U4 may repair it. That repair must land before U1's green completion, and by
   **P3** U4's pin edit must land after U2's sync. **Those are two different U4
   commits.**
4. #55 requires `unittest discover` `OK` at U4's completion. By **P4** that is
   only true after U5, and by **P3** U5's own green requires U4's pin edit first.
   So U4 needs a third commit, after U5.
5. #54 requires `unittest discover` `OK` at U3's completion, and U3 is the last
   package-root writer, so U5 follows it — but U3's green needs U5. **U3 needs two
   commits**, one before the freeze and one after U5.
6. U1's first commit is already landed and accepted at `12c889c`, so the
   reclassification is necessarily a second U1 commit.

Minimum: U0 one, U1 two, U2 two, U3 two, U4 three, U5 one — **eleven commits**.
Amendment 4 (KTD16) adds one U1 commit and extends an existing U2 commit, making the
total **twelve**: U0 one, U1 three, U2 two, U3 two, U4 three, U5 one. Amendment 5
corrected this from thirteen — see D9 in §18. **As landed on the branch the total is
fourteen**: U0 landed in three commits rather than one — `ab939ff` (the first attempt,
later superseded when its mixed-route provenance was rejected), `0a19edb` (the re-run
on the approved route), and `f74bb7e` (the transcript elision) — so `f74bb7e` is U0's
frozen commit, not the middle of the three. In
a counterfactual where U1 had not already landed it would be ten. There is no
ordering that reaches six, because steps 2, 3, 4 and 5 each force a split
independently, and none of the four prerequisites is a plan choice — every one is a
committed test or a live issue clause.

#### What this plan does

**An inherited acceptance criterion is met at the unit's completion.** Each of #52,
#54, #55 and #56 says the command "reports `OK`". None says it must do so at every
commit on the way there. Every unit's final commit below is genuinely green — no
expected-red list, no moved checkpoint, no weakened assertion. #53 is the one child
issue that carries no `unittest discover` criterion at all, which is why U2's two
commits may be red.

| # | Commit | Unit | Content | Suite at that commit |
|---|---|---|---|---|
| 1 | `ab939ff` | U0a | entry criteria and pin proof — first attempt, later superseded | superseded, not accepted as evidence |
| 2 | `0a19edb` | U0b | entry criteria and pin proof — re-run on the approved route | green |
| 3 | `f74bb7e` | U0c | elide the per-test transcript lines — **U0's frozen commit** | green |
| 4 | `12c889c` | U1a | custody for the eight new tests, provenance notes — **landed and accepted** | green |
| 5 | **U2a** | U2 | register the package-root transform rule in `scripts/sync_vendor_source.py` | red on the registry-name test (P2) — #53 has no discover criterion |
| 6 | **U4a** | U4 | extend `expected` in `test_rule_names_register_exactly_once` to the six registered rules | green |
| 7 | **U1b** | U1 | reclassify `scripts/sync_template_docs.py` in the descriptor, naming the now-registered rule | green |
| 8 | **U1c** | U1 | reclassify `tests/test_issue_contract_parity.py` and `tests/test_template_sync.py` (KTD16) | **green — U1 completes, #52 met** |
| 9 | **U2b** | U2 | bump the package-root rule to v2, then run the synchronization | red on the pin constants and `LiveDocumentTest` — #53 has no discover criterion; its package pytest and `--check` gates are green |
| 10 | **U4b** | U4 | the three pin constants, and the rule's focused coverage | red on `LiveDocumentTest` only |
| 11 | **U3a** | U3 | package-root edits, descriptor verb table, verb constants, guard and derivation tests — **last edit inside the package root** | red on `LiveDocumentTest` only |
| — | *freeze* | — | fingerprint final and recorded | — |
| 12 | **U5** | U5 | one ten-client assessment, fresh matrix and readback, supersession, bindings | **green — U5 completes, #56 met** |
| 13 | **U3b** | U3 | root `README.md` pin, version and counts, plus its pin test | **green — U3 completes, #54 met** |
| 14 | **U4c** | U4 | skill-roster and PyYAML confirmations, and the recorded four-gate transcript | **green — U4 completes, #55 met** |

Commits 4, 11 and 12 are real deliverables of their own issues, not bookkeeping.
The registry-name test is #55's file and #55's `MISSION_CONTROL_SKILLS` confirmation
sits beside it; the root README's counts can only be finally correct once every unit
has landed. Commits 10, 11 and 12 touch nothing under `plugins/mission-control/`, so
the freeze holds and U5's single assessment stays valid.

**This is a material deviation from §2.3's "six child-scoped commits, one per
unit," and the plan does not pretend otherwise** — eleven at Amendment 3, twelve
after Amendment 4 (KTD16) as corrected by Amendment 5, and **fourteen as landed**,
because U0 shipped in three commits and only its third is the frozen commit. It is raised as operator question
**Q8** with the trade-off stated. It changes the SHA record and the review binding;
it changes no unit boundary, no ownership, and no acceptance criterion.

**Rejected.** (a) **Name the red tests as expected in each unit's gate**, as U2
does — that is the narrowing cycle-2 finding D1 rejected, and #53 is the only child
issue whose criteria permit it. (b) **Move the freeze before U3** — forbidden by
#50's own Intent text. (c) **Move U3's package-root edits into U2** — contradicts
#53's out-of-scope. (d) **Let U2 register the rule and repair the registry test in
one commit** — contradicts #53's "No downstream test edits. U4 owns those." (e)
**Let U1 register the rule alongside its descriptor edit** — contradicts #52's "This
unit changes the descriptor only." (f) **Run the ten-client assessment twice** —
legitimate under this repository's supersede-and-re-run evidence loop, which the
agent-launcher port used when a repair moved its tree, but it costs a second
operator-attended run to save one cheap commit. Kept as the fallback if the operator
rejects eleven commits and will not accept ten either.

**Revisit when** a resynchronization introduces no new transform rule and makes no
target-owned edit inside the package root. Then P1, P2 and P4 all fall away and six
commits is reachable.


### KTD16 — The package-root transform is extended to rewrite assertion sites, and two more carried tests become transforms

**Added by Amendment 4 (§17). Operator decision. Reviewed by doc-review cycle 6
(commit `384e52a`, blocked: false); its findings D9 and D10 were closed by cycle 7
(commit `6166b26`).**

#### The blocker

Two byte-copied tests carry upstream's package-root resolution and cannot work in the
portable layout. Both verified at pin `3b2b7083`:

**`tests/test_issue_contract_parity.py` — four sites, and it does not even collect.**
`_find_package_root()` is defined at line 36, walks for `.claude-plugin/plugin.json`
at line 39, raises `RuntimeError` at line 41 with that path in the message at line 42,
and is called **at module scope** at line 46 (`PACKAGE_ROOT = _find_package_root()`).
It then asserts the marker on itself at line 405
(`assert (root / ".claude-plugin" / "plugin.json").is_file()`) and pins the failure
message at lines 410–417 (`test_find_package_root_fails_loudly_when_missing`, matching
`r"package root containing \.claude-plugin/plugin\.json not found"`). Reproduced: a
`RuntimeError` at collection time.

**`tests/test_template_sync.py` — two sites, and it is broken *by KTD14*.** This file
has no `_find_package_root` of its own; it exercises
`sync_template_docs._find_package_root`, the module KTD14 already transforms. It
collects, and two of its eight tests fail: line 175 asserts the `.claude-plugin`
marker is a file, and lines 185–188 assert `pytest.raises(RuntimeError, match=...)` on
the old message text. **Those two failures are currently latent**: on the stopped U2
tree `pytest plugins/mission-control/tests -q` aborts with `Interrupted: 1 error
during collection` at `test_issue_contract_parity.py:41`, so it never reaches them. A
worker who fixes only the parity file will see the template-sync failures appear, and
should expect that rather than read it as a regression. Both fail **because** KTD14's `resolve-package-root-marker` rule
deliberately changed the marker and the error string. This is a direct consequence of
KTD14, not an independent defect, and the plan should say so rather than let a worker
hunt for a second cause.

#### The scan, recorded so nobody repeats it

Every `.py` file in the pinned package was scanned for the `.claude-plugin` pattern.
**Six carry it. Four positions were already settled; these two were the only
unresolved ones.**

| File | Occurrences | Position |
|---|---:|---|
| `scripts/fleet_commons_shim.py` | 3 | dropped — the Fleet Core bundle replaces it |
| `scripts/sync_template_docs.py` | 2 | transformed by **KTD14** (`resolve-package-root-marker`) |
| `tests/test_card_validator_agreement.py` | 3 | dropped by **operator ruling 2** |
| `tests/test_prompt_alignment.py` | 10 | dropped — premises fail across the port boundary |
| `tests/test_issue_contract_parity.py` | 4 | **unresolved → transformed by this decision** |
| `tests/test_template_sync.py` | 2 | **unresolved → transformed by this decision** |

There is no seventh file. A future resynchronization can re-run this scan rather than
re-derive the inventory.

#### Chosen — option (a)

**Extend `resolve-package-root-marker` to a new version whose shape covers, per file:
the `_find_package_root` definition, its module-scope call, and the assertion sites —
both the `.is_file()` marker assertions and the `pytest.raises` error-text match — and
reclassify both tests from `custody.byte_copies` to `custody.entrypoint_transforms`.**

The two files need different subsets, and the rule must know that rather than guess:
`test_issue_contract_parity.py` needs all four site classes; `test_template_sync.py`
needs only the two assertion sites, because its subject is the already-transformed
module.

#### The cost, stated plainly

**This rule rewrites what a test *asserts*, not merely where it looks. KTD14
deliberately did not cross that line; this amendment does.** A carried test whose
assertions are rewritten downstream is no longer testing exactly what upstream tests.
That is a real weakening of the "derived artifact, never a second writable source"
principle, and it is not softened here.

**Why the operator judged it acceptable:** the alternative was narrowing an inherited
acceptance criterion, and the eleven-commit ruling (Q8) was taken precisely to avoid
that. Rewriting an assertion about a *layout marker* is narrower in blast radius than
dropping two tests or leaving the resynchronization unfinished, and the rewritten
assertion still asserts the same property — that the package root is discoverable by
this layout's marker — against the marker this layout actually uses.

**Revisit when** upstream adopts a layout-neutral package-root resolution. At that
point both of these transforms, and KTD14's, should retire and all three files return
to being byte copies.

#### The discipline that replaces single-shape

The rule stops being single-shape, which KTD1 and KTD2 discipline resists. Four
obligations replace that guarantee, and a worker may not relax any of them:

1. **Exact per-file site counts.** The rule declares how many of each site class it
   expects in each file and matches exactly that many. Version 1 of this rule
   requires exactly one finder definition and exactly one module-scope call in
   every file it is applied to; `test_template_sync.py` has neither, so a v2
   that keeps that absolute requirement will refuse the file this decision
   exists to carry. The declared counts are:

   | File | finder definition | module-scope call | `.is_file()` assertion | `pytest.raises` match |
   |---|---:|---:|---:|---:|
   | `scripts/sync_template_docs.py` | 1 | 1 | 0 | 0 |
   | `tests/test_issue_contract_parity.py` | 1 | 1 | 1 | 1 |
   | `tests/test_template_sync.py` | 0 | 0 | 1 | 1 |

   The walk line and the error text inside a finder definition remain internals
   of that one definition (KTD14 match unit), not extra site classes. The
   assertion rewrite uses the same portable marker KTD14 already names:
   `com.infiquetra.claude` / `com.infiquetra.claude/plugin.json`.
2. **Refuse loudly on any count mismatch.** More or fewer sites than declared is a
   refusal naming the file, the site class, and the counts found — never a partial
   application, never a silent skip.
3. **Idempotent.** Running it on already-portable input is a no-op, the same property
   `normalize-skill-frontmatter` has for a file with no `when_to_use`.
4. **Reproducible from source bytes alone.** No repository state, no environment, no
   sibling file. The same upstream bytes produce the same output on any machine.

#### Commit shape — one new commit, not two

**Corrected by Amendment 5 (§18, finding D9).** This decision costs the run **one**
commit, not two: a third U1 commit (U1c) for the descriptor reclassification. The
rule's v2 extension **folds into U2b**, the synchronization commit, because both are
U2's act on U2's file and nothing separates them.

The earlier reading assumed v2 had to exist before U1c could name the rule. It does
not. The rule *name* `resolve-package-root-marker` was registered back at U2a, and the
descriptor join
(`tests/test_port_config.py::CommittedDescriptorTest.test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements`)
asserts `assertIn(rule, svs.TRANSFORM_RULES)` — a **name** join, with no version in it.
What v2 must precede is the **sync run**: v1 requires exactly one finder definition
plus one module-scope call and would refuse `tests/test_template_sync.py`, which has
neither.

A standalone extension commit was therefore a preference, not a forced split. The run
lands **twelve** commits.

#### Rejected alternatives

**(b) Drop both from source**, the way `test_prompt_alignment.py` and
`test_card_validator_agreement.py` are dropped. Rejected on two independent grounds.
The package would hold **69 files**, breaking #53's explicit acceptance checkbox —
"The package holds 71 files, proven by `git ls-files plugins/mission-control | wc -l`
printing `71`" — an inherited criterion the eleven-commit ruling was taken
specifically to preserve at full strength. And the portable copy would lose its
contract-parity and template-sync coverage, shrinking what the package proves about
itself.

**(c) Upstream filing and stop.** Rejected because it does not complete the
resynchronization in this run: #50 and #51–#56 would stay open pending an upstream
release on another schedule. Upstream is not wrong for its own layout, so the filing
would be asking upstream to stop using `.claude-plugin/` in a Claude plugin.

---

## 5. Dependency graph, concurrency, and the freeze

```
U0 (#51)  entry criteria, pin proof
   │
   ▼
U1 (#52)  port descriptor: custody + provenance notes     ← unblocks everything
   │
   ▼
U2 (#53)  run the synchronization; the pin actually moves
   │
   ├──────────────┬──────────────┐
   ▼              ▼              │   at most two concurrent WORKERS
U4 (#55)       U3 (#54)          │   U4: fingerprint-neutral (tests/ only)
downstream     target-owned      │   U3: target-owned surface + verb table
pins           surface           │
   │              ┊              │   work overlaps; the LANDING is serialized
   │ lands 1st    ┊ work runs    │
   └──────────────┤ concurrently │
                  ▼              │
            U3a rebases onto U4b │   U3a is the last edit inside the package
            and lands            │   root; U3 COMPLETES later, at U3b
                  │              │
                  ▼              │
    FREEZE INTEGRATION  ─────────┘   fingerprint final; nothing may touch
          │                          plugins/mission-control/ after this point
          ▼
U5 (#56)  fresh ten-client assessment, readback, supersession, bindings
```

**Why each edge exists.**

- **U0 → U1.** Ruling 1: no unit may build on an unproven pin. U1's very first
  command runs against upstream at `3b2b7083`; if the pin is not proven green,
  every later measurement inherits that doubt.
- **U1 → U2.** Mechanical, not stylistic. `--check` refuses on unclassified paths
  *before* it can report any other drift, so U2 has nothing to run until U1 lands.
- **U2 → U3.** U3 asserts the manifest version equals `PROVENANCE.json`'s
  `source_version`, which only holds after the sync rewrites the provenance
  manifest.
- **U2 → U4.** The whole `test_sync_vendor_source.py` pin class is guarded on
  `plugins/mission-control/PROVENANCE.json` existing and matching, so U4's edit is
  only meaningful — and only green — after U2.
- **U4 ⇒ U3 — a landing-order edge, not a work-order edge (KTD10).** The two
  units' *work* overlaps; their *commits* do not. After U2 the repository suite is
  red on three constants in `tests/test_sync_vendor_source.py` that U4 owns and U3
  may not touch, and issue #54 requires `python3 -m unittest discover -s tests` to
  report `OK` for U3. So U4's pin-constant commit (U4b) lands first, U3a rebases onto
  it, and U3's gate runs on a tree where those constants are already repaired. This is the only
  ordering under which both units' inherited acceptance criteria hold as written.
- **{U3, U4} → freeze.** U3 edits two files inside the package root, so the
  fingerprint is not final until it lands (KTD9). U4 cannot move the fingerprint at
  all, which is what makes the concurrency safe.
- **U2a ⇒ U4a ⇒ U1b — the inverted prerequisite, corrected (KTD15 P1, P2).** A
  descriptor may only name a rule the synchronizer already registers, and registering
  a rule breaks a test that pins the registry by name and belongs to U4. So the rule
  lands first, its registry test is repaired second, and the descriptor names it
  third. Amendment 2 had these backwards and U1's completion was red.
- **U1c ⇒ U2b — one real edge, and one that Amendment 5 removed (KTD16, D9, D10).**
  The descriptor must select the rule for the two test files before the
  synchronization runs, or the sync re-copies bytes that cannot collect. That edge is
  real. **Two things previously claimed here were not.**

  *There is no ordering edge from the rule's v2 extension to U1c.* The rule **name**
  `resolve-package-root-marker` was registered at U2a, and
  `tests/test_port_config.py::CommittedDescriptorTest.test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements`
  joins **names, not versions** — `self.assertIn(rule, svs.TRANSFORM_RULES)`. A
  descriptor may therefore select that rule for two more paths whatever version the
  rule is on. What v2 must precede is the **sync run**, because v1 requires exactly one
  finder definition plus one module-scope call and would refuse
  `tests/test_template_sync.py`, which has neither. Extension and sync are both U2's
  act on U2's file, so they are **one commit**, not two.

  *There is no custody-versus-provenance constraint on U1c either.* An earlier
  revision of this bullet cited
  `CommittedDescriptorTest.test_the_custody_table_accounts_for_every_shipped_managed_path`
  as forcing U1c to gate on a tree where the transform had already been re-run. That
  citation was wrong: the method reads `self.config`, and `CommittedDescriptorTest.setUp`
  is `port_config.load("unifi", ROOT)` (`tests/test_port_config.py` 470–471) — the class
  docstring even calls the UniFi descriptor "the regression fixture for all of this."
  A mission-control reclassification cannot fail it. **No committed test joins
  mission-control's descriptor custody to its shipped `PROVENANCE.json`**, so U1c is
  green on a clean checkout with no working-tree precondition, and the operator-visible
  caveat that stood here is withdrawn.
- **U5 ⇒ U3b and U4c — the second landing-order edge (KTD15).** After U2, the only
  remaining reds are the pin constants (U4's) and `LiveDocumentTest` (U5's). U5 is the
  only unit that can clear the second one, and it cannot run before the package is
  final, which is not until U3's package-root edits land. So U3 and U4 each finish
  *after* U5 with a second commit, and that is where their inherited `unittest
  discover` `OK` is met — at full strength, with no expected-red list.
- **freeze → U5.** The assessment must describe the bytes that ship. If any byte
  under `plugins/mission-control/` changes after the assessment runs, that run's
  record is discarded (U5 stop condition).

**Concurrency cap.** Maximum two in-flight workers at any moment, reached only in
the U3/U4 pair. Every other point in the graph is single-file.

**Landing sequence with the completion commits (KTD15).** The graph above is the
*work* graph and is unchanged. The *commit* sequence that satisfies every unit's
inherited gate is:

```
U1a ✓ → U2a ✓ → U4a ✓ → U1b ✓ → U1c → U2b* → U4b → U3a → FREEZE → U5 → U3b → U4c
                                  ↑                 ↑                ↑     ↑     ↑
                        U1 done (green)  last package-root edit     U5    U3    U4

* U2b carries both the rule's v2 extension and the synchronization run.
```

Amendment 4 (KTD16) inserts **U1c** (reclassify the two remaining tests in the
descriptor) and extends **U2b** to bump the package-root rule to v2 before it syncs,
moving U1's completion from U1b to U1c. **Twelve commits, not eleven** (Q8).

The rule is registered (U2a) and its registry test repaired (U4a) **before** the
descriptor names it (U1b) — that ordering is forced by two committed tests, not
chosen (KTD15 P1, P2). U3b and U4c touch nothing under `plugins/mission-control/`,
so the freeze holds and U5's single assessment stays valid.

**"Two-wide" caps workers, not commit bases.** The run declaration's "at most two
workers" is a concurrency limit on people or agents doing work at once. It does not
say — and this plan does not assume — that the two units cut independent commits
from a shared base. U4 lands first and U3 rebases onto it (KTD10); both units are
still in flight at the same time, which is what the cap governs.

**Freeze integration, concretely.** After both U3 and U4 have committed to
`orch-agent-plugins-50`:

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
"$FLOOR_PY" -m pytest plugins/mission-control/tests -q
git diff --check
git status --porcelain                                              # expect clean
python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control
```

Record the printed `file_count` and `tree_sha256` as **the frozen fingerprint**.
U5 quotes that pair, and re-prints it after the assessment to prove nothing moved.
The freeze is a recorded state on the branch, **not a synthetic checkpoint commit**
— U5 owns the real checkpoint.

---

## 6. File ownership

No two units write the same file concurrently. Where a file has more than one
writer, the writers are strictly sequenced by the dependency graph and each writes
a disjoint region.

### 6.1 Single-owner files

| Path | Owner | What that unit does to it |
|---|---|---|
| `docs/plans/2026-08-30-mission-control-resync-u0-entry-criteria.md` | **U0** | creates the entry-criteria note |
| `plugins/mission-control/PROVENANCE.json` | **U2** | regenerated by the sync tool |
| `plugins/mission-control/**` *(all byte copies, transform outputs, client copies, relocated manifest, tests)* | **U2** | regenerated by the sync tool |
| `plugins/mission-control/plugin.json` | **U3** | version and description; target-owned, the sync tool never writes it |
| `plugins/mission-control/README.md` | **U3** | version line and the per-skill verb table |
| `README.md` *(repository root)* | **U3** | pin, version, file count, test counts, Packages-table row |
| `tests/test_mission_control_readme.py` | **U3** | `MUTATING_VERBS`, `READ_ONLY_VERBS` |
| `tests/test_mission_control_rule_audit.py` | **U3** | create-option no-write guard, manifest-version derivation test, root-README pin test |
| `scripts/sync_vendor_source.py` | **U2** | registers the package-root transform rule (KTD14, commit U2a) and extends it to the assertion-covering v2 in the synchronization commit (KTD16, commit U2b). Moved here from §6.3; see the note under that table |
| `tests/test_sync_vendor_source.py` | **U4** | `MISSION_CONTROL_PIN`, the `source_version` assertion, the `MISSION_CONTROL_SKILLS` confirmation, and — added by Amendment 2 — coverage for the new package-root transform rule (KTD14, KTD15) |
| `tests/test_check_compatibility_matrix.py` | **U5** | new mission-control matrix and readback binding classes |
| `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md` | **U5** | supersession directives only |
| `docs/evidence/2026-08-25-mission-control-post-activation-readback.md` | **U5** | supersession directives only |
| `docs/evidence/<assessment-date>-mission-control-compatibility-matrix.md` *(new)* | **U5** | creates |
| `docs/evidence/<assessment-date>-mission-control-post-activation-readback.md` *(new)* | **U5** | creates |
| `docs/engineering-journal/QUEUED.md` | **U5** | moves the consumed resync entry toward closure |

### 6.2 Multi-writer files — sequenced, disjoint regions

| Path | Writers, in order | Disjoint regions |
|---|---|---|
| `ports/mission-control.json` | **U1**, then **U3** | U1 writes `custody.byte_copies`, `custody.dropped_from_source`, `provenance.notes`, `provenance.dropped_reason` — in its second commit moves `scripts/sync_template_docs.py` into `custody.entrypoint_transforms` (KTD14), and in its **third** commit moves `tests/test_issue_contract_parity.py` and `tests/test_template_sync.py` the same way (KTD16, Amendment 4). U3 writes **only** `assessment.mutating_operations`. The two writers share no JSON key. Amendment 1 briefly made U2 a third writer here; Amendment 2 returned that edit to U1, which owns the file under #52, so the descriptor is back to the two writers #50's shaping records. |
| `docs/engineering-journal/DECISIONS.md` | the plan commit (`1e4da2b`), then **U1** (`12c889c`), then the **Amendment 1** commit, then **U3**, then **U5** | Append-only, and strictly sequential in practice as well as in principle: no two of these writers were ever in flight at once. Each adds its own dated entry under a distinct anchor and edits no line another writer wrote. Amendment 1 appends after U1 because that is when the blocker surfaced. See KTD7. |

**The rule for both multi-writer files above.** A later writer that finds it must change an earlier
writer's region stops and reports. That is not a merge conflict to resolve; it is
evidence that the earlier unit's decision was wrong, and the operator decides.

### 6.3 Files no unit may write

| Path | Why |
|---|---|
| `scripts/port_config.py` | graded (cycle-16 mutation proof) |
| `scripts/check_repo.py` | graded |
| `scripts/check_compatibility_matrix.py` | graded |
| `scripts/assess_clients.py` | graded |
| `plugins/unifi/scripts/site_profile.py` | graded |
| `plugins/fleet-core/**`, `plugins/mission-control/scripts/_bundled/**`, `plugins/mission-control/fleet-bundle.json` | fleet-core is unchanged upstream; regenerating churns the UniFi bundles and invalidates UniFi's committed matrix |
| anything under `../infiquetra-claude-plugins` | upstream is never edited by this work |
| `docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt` | a standing proof; superseding it is a separate, funded run |
| `.github/workflows/ci.yml` | no new gate without a separate operator decision (#55, #56) |

**One row moved out of this table by Amendment 1.** `scripts/sync_vendor_source.py`
was listed here on the reasoning that "a resync that has to change its own
synchronizer is a stop condition, not a unit." That reasoning held for a *content*
repair. It does not hold for a **custody reclassification**: adding a versioned
transform rule is the synchronizer doing its declared job, it is the mechanism the
run contract names as the alternative to an upstream filing, and the file is not in
the cycle-16 graded set. The path now sits in §6.1 under U2 (KTD14, §14). It is the **only** file outside
`plugins/mission-control/` that U2 writes; Amendment 2 returned the descriptor edit to
U1 and the rule coverage to U4, per §6.2 and KTD14. The
original prohibition still stands for every other kind of edit to that file:
changing how an existing rule matches, relaxing an "expected exactly one"
assertion, or repairing copied content through the synchronizer remains a stop
condition.

---

## 7. Implementation Units

Common to every unit: backend **inline**; branch `orch-agent-plugins-50`; no
worktrees, branches, sessions, subagents, or issues created; unrelated dirty files
preserved; the run-level stop conditions in §2.7 always apply in addition to the
unit's own; the four gates in §2.6 run before the unit commits.

---

### U0. Verify entry criteria and prove the pin — issue #51

**Objective.** Close the runbook's entry criteria for this resynchronization and
record the result, so every later unit builds on a proven pin rather than an
assumed one.

**Deliverables.**

1. `docs/plans/2026-08-30-mission-control-resync-u0-entry-criteria.md`, containing:
   - The **verbatim transcript** of a disposable scratch clone at `3b2b7083`
     running the upstream suite green — the exact command and its exact output,
     pasted, never reconstructed after the fact (runbook Phase 2 capture rule).
   - The pin's manifest version readback (`2.15.2`).
   - The three-revision package-tree comparison table (KTD1), with the reason the
     accepted merge was pinned rather than the version-landing commit.
   - The Python floor readback (`requires-python = ">=3.12"`).
   - The repository's allowed merge methods, read from `gh repo view`, recorded
     **before** any run text states a merge form (lesson R1).
   - The assessment-plan print, showing it exits 0 having run nothing.
   - The runbook version followed (**1.1.0**) and a table of every entry-criteria
     and phase step this resynchronization **skips**, each with its reason.

2. The skipped-step table, at minimum, covers these — the runbook is written for
   an initial port and several steps have no counterpart in a resync:

   | Runbook step | Disposition for this run | Reason |
   |---|---|---|
   | Entry: "the port descriptor exists … and `check_repo.py` passes on the empty port" | **skipped** | the descriptor has existed since the #9 port; the gate passes on the *populated* port today |
   | Entry: "every validation rule is inventoried with a named predicate and authority" | **skipped** | done once in #9 and recorded in `docs/plans/2026-08-24-mission-control-port-u7-phase2-rule-audit.md`; a resync re-runs rules, it does not re-inventory them |
   | Phase 0: "write `ports/<package>.json`" | **replaced** | U1 amends an existing descriptor rather than writing a new one |
   | Phase 0: "classify every path" | **narrowed** | only the eight new upstream paths need classification (U1) |
   | Phase 1: three parallel lanes A/B/C | **replaced** | Lane C (bundling) is empty — fleet-core is unchanged; Lanes A and B become serialized units U2 and U3 because U3 edits inside the package root and must precede the freeze |
   | Phase 2: full rule audit | **narrowed** | the four transform premises are re-proven at the new pin (U2, R19) and the verb table is re-audited (U3); the rule inventory itself is unchanged |
   | Phase 3: freeze and evidence | **kept, except mutation-proof re-run** | the matrix, readback, freeze, and content bindings are U5; a new mutation proof is out of scope because the five graded files are untouched (§2.8, KTD11) |
   | Phase 3: "Mutation proof per rule copy" | **skipped** | cycle-16 proof still stands; re-running it would edit a graded file or the proof document, both forbidden |
   | Phase 4: review | **kept in full** | §2.4 |

**Files owned.** `docs/plans/2026-08-30-mission-control-resync-u0-entry-criteria.md`
only. **U0 changes nothing else** — not `ports/mission-control.json`, not anything
under `plugins/mission-control/`, not the runbook.

**Test scenarios.** `Test expectation: none — this unit produces a recorded
verification artifact, not code.` Its evidence is the captured transcript of each
command and its exact output, pasted verbatim per runbook Phase 2's capture rule.
A reconstructed transcript does not satisfy this unit.

**Verification.**

```bash
SCRATCH=$(mktemp -d)
git clone --quiet https://github.com/infiquetra/infiquetra-claude-plugins "$SCRATCH/upstream"
git -C "$SCRATCH/upstream" checkout --quiet 3b2b7083
git -C "$SCRATCH/upstream" show 3b2b7083:plugins/mission-control/.claude-plugin/plugin.json

# the upstream suite, green, in the scratch clone — transcript pasted verbatim
# documented at 3b2b7083:README.md (Development / Setup)
( cd "$SCRATCH/upstream" && uv sync --locked --extra dev && uv run pytest )

for r in 379d2350 1111de33 3b2b7083; do \
  printf "%s %s\n" "$r" "$(git -C "$SCRATCH/upstream" rev-parse $r:plugins/mission-control)"; done

git -C "$SCRATCH/upstream" show 3b2b7083:pyproject.toml | grep requires-python
gh repo view infiquetra/infiquetra-agent-plugins \
  --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed

python3 scripts/assess_clients.py --package mission-control    # plan only; runs nothing

# The four mandated gates plus the floor run (R36 — uniform across every unit)
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
"$FLOOR_PY" -m pytest plugins/mission-control/tests -q
git diff --check
rm -rf "$SCRATCH"
```

**Commit shape.**
`docs(mission-control): record the 2.15.2 resync entry criteria and the 3b2b7083 pin proof`
Body: `Refs #51`, the base SHA, and a one-line statement that the upstream suite
was proven green from a disposable scratch clone.

**Unit stop conditions.**

| Condition | Action |
|---|---|
| The upstream suite is not green at `3b2b7083` in a clean scratch clone | **Stop the whole run.** Ruling 1 makes this the entry gate; no later unit may proceed on an unproven pin. |
| The three-revision tree comparison does not reproduce the recorded digests | Stop. The pin analysis is wrong and must be redone before anything is classified. |
| `requires-python` at the pin is above `>=3.12` | Stop. The floor is part of the synchronization contract. |
| `gh repo view` shows the merge policy has changed since this plan was written | Report it; §2.3 and KTD8 are amended prospectively, never retroactively. |
| The scratch clone cannot be made disposable (no writable temp, no network) | Stop and report. Reusing the local read-only checkout is **not** the same act and must not be substituted. |

**Predeclared review dimensions.** Evidence integrity (is the transcript real and
capable of having failed?); premise verification (does the recorded comparison
support the pin choice?); documentation accuracy.

---

### U1. Port descriptor: custody and the provenance-notes refresh — issue #52

**Objective.** Assign custody to every upstream path 2.15.2 adds, and refresh the
descriptor prose that the synchronization tool copies verbatim into the generated
provenance manifest. **This unit unblocks the entire run.**

**Deliverables.**

1. **Seven new paths classified `upstream-byte-copy`** — appended to
   `custody.byte_copies` in `ports/mission-control.json`, which grows from 42 to 49
   at U1a and then falls 49 → 48 → 46 as U1b and U1c reclassify the three
   package-root paths (KTD14, KTD16).   entries. The paths, package-root-relative:

   ```
   tests/test_lifecycle_field_boards.py
   tests/test_lifecycle_field_identity.py
   tests/test_lifecycle_field_mutation.py
   tests/test_lifecycle_field_routing.py
   tests/test_lifecycle_writer_census.py
   tests/test_option_identity.py
   tests/test_sdlc_manager_optional_deps.py
   ```

   Each was verified self-contained: no fixed repository-depth assumption, no
   external checkout, no marketplace or sibling-plugin premise, no network call, no
   credentials. Each patches `_graphql` at the `sdlc_manager` module level so no
   live GitHub call can occur. `test_sdlc_manager_optional_deps.py` spawns a
   subprocess, but it is the test's own interpreter (`sys.executable`) running
   inline code with `sys.modules['yaml']` forced to `None` — package-internal and
   hermetic. **U1 re-verifies each of these seven claims and records the result**
   rather than inheriting it from the issue text.

2. **The eighth path excluded** — `tests/test_card_validator_agreement.py` appended
   to `custody.dropped_from_source` (2 → 3 entries), with its reason appended to the
   single `provenance.dropped_reason` string (KTD3). The reason must name the concrete
   mechanism: the test loads an authority module from outside any repository,
   searching `HOME_LAB_PATH`, `INFIQUETRA_HOME_LAB_PATH`,
   `~/workspace/infiquetra/home-lab`, `~/workspace/home-lab`, then sibling
   directories, and skips loudly when absent — so its verdict would report the
   machine's disk rather than this repository.

3. **The `provenance.notes` refresh — a deliverable of equal standing, not a
   tidy-up.** `scripts/sync_vendor_source.py` copies these notes **verbatim** into
   `PROVENANCE.json` (`"notes": list(config.notes)`). Stale prose therefore ships a
   generated file whose header reads `source_version: 2.15.2` while its own notes
   paragraph says 2.12.2, and nothing catches it. Required changes:

   | Claim in the current notes | State at `3b2b7083`, verified this session | Action |
   |---|---|---|
   | pin `84eaf042…`, version 2.12.2 | superseded | rewrite to `3b2b7083fdda8e39e213b5f4acf9f8301d60dd52`, version 2.15.2 |
   | `executor_profile_lint.py` shim import at line 35, `tier_palette` at line 89 | **still correct** — the file is unchanged | keep |
   | `sdlc_manager.py` `_load_intent_envelope` at lines 4283–4287 | moved; the function is now defined at line **5129** and its guarded shim import sits at line **5138** | restate with the new lines |
   | `sdlc_manager.py` reads `INFIQUETRA_SDLC_PATH` at line 135 | now line **136** | restate |
   | `sdlc_manager.py` `_open_mapping_pr` at line 4664 | moved; the function is now defined at line **5552** | restate |
   | `sdlc_manager.py` needs PyYAML at module scope, line 83 | **false** — upstream filing #828 moved the import into a function; `import yaml` now appears at line **3436**, indented | rewrite the claim, and state that PyYAML is still required because `scripts/sync_template_docs.py:14` and `tests/test_template_sync.py:7` still import it at module scope, so the continuous-integration install line stays; only the justification changes |
   | "The twenty-one upstream test files are byte copies" | stale after the seven new byte copies land; upstream at the pin has 30 test files, two dropped (`test_prompt_alignment.py`, `test_card_validator_agreement.py`), so 28 are byte copies | rewrite the count to twenty-eight |

4. **Re-verify the `test_prompt_alignment.py` drop at the new pin and record it.**
   Its premises still fail: the upstream file at `3b2b7083` still requires a sibling
   `plugins/saga/skills/handoff/SKILL.md` this catalog does not host, and still
   reads a root marketplace manifest to cross-check a Mission Control entry this
   catalog's manifest does not carry. The drop holds; record the re-verification
   rather than leaving it implied.

5. **A `DECISIONS.md` entry** recording the agreement-test exclusion and the
   re-verified drop, each with rejected alternatives and a revisit condition (KTD2,
   KTD3).

**Files owned.** `ports/mission-control.json` (custody + provenance regions only —
**not** `assessment.mutating_operations`, which is U3's) and
`docs/engineering-journal/DECISIONS.md` (append only).

**U1 completes in two commits (KTD14, KTD15 — Amendment 2).**

- **U1a — landed and accepted at `12c889c`.** Everything above: custody for the eight
  new upstream paths, the provenance-notes refresh, the re-verified
  `test_prompt_alignment.py` drop, and the `DECISIONS.md` entry.
- **U1b — a second commit against the same unit, not a rewrite of the first.** Move
  `scripts/sync_template_docs.py` from `custody.byte_copies` into
  `custody.entrypoint_transforms`, naming the new package-root rule. This is here
  because U1 owns the descriptor under #52 and issue #53 forbids U2 from editing it.
  It must land **after** U2a has registered the rule and U4a has repaired the registry
  test, and **before** U2b's synchronization run (KTD15).

  **Why that order, corrected by Amendment 3.** Amendment 2 claimed the
  reclassification "changes no behaviour on its own." That was false and doc-review
  finding D4 caught it.
  `tests/test_port_config.py::CommittedDescriptorTest.test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements`
  asserts every rule a descriptor names is in `svs.TRANSFORM_RULES`, so naming a rule
  U2 had not yet registered made `unittest discover` red at U1's completion — and #52
  requires it to report `OK`. `--check` would refuse the same unregistered name.
  With U2a and U4a ahead of it, **U1b is green outright and #52 is met at full
  strength.**

**Test scenarios.** `Test expectation: none authored by this unit.` The gate is
the synchronization tool's own refusal changing verdict, which is a behavioural
check no new test would improve on.

`tests/test_port_config.py` changes **if and only if** the descriptor's shape
changes. On the verified analysis it does not, because every edit appends to
arrays that already exist (KTD3). If that file needs an edit, the scope assumption
is wrong — stop rather than widen the unit.

**Verification.**

```bash
# The blocking gate: the refusal must change shape from "unclassified paths"
# to real content drift.
python3 scripts/sync_vendor_source.py --package mission-control \
  --source ../infiquetra-claude-plugins --commit 3b2b7083 --check

# Custody counts moved as intended
python3 -c "import json;c=json.load(open('ports/mission-control.json'))['custody'];print(len(c['byte_copies']), len(c['dropped_from_source']))"   # expect: 46 3 (49 3 at U1a, before U1b and U1c reclassify the three package-root paths)

# The line-number claims, checked against the pinned source
git -C ../infiquetra-claude-plugins show 3b2b7083:plugins/mission-control/scripts/executor_profile_lint.py \
  | grep -n "fleet_commons_shim\|tier_palette"
git -C ../infiquetra-claude-plugins show 3b2b7083:plugins/mission-control/scripts/sdlc_manager.py \
  | grep -n "INFIQUETRA_SDLC_PATH\|import yaml\|_load_intent_envelope\|_open_mapping_pr"

# Gates (R36 — the four mandated, plus the floor run)
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
"$FLOOR_PY" -m pytest plugins/mission-control/tests -q
git diff --check
```

**Commit shape.**
`feat(ports): assign custody for the 2.15.2 upstream paths and refresh the provenance notes`
Body: `Refs #52`, the base SHA, the 42→49 and 2→3 custody counts, and one line
naming the PyYAML claim as corrected rather than merely renumbered.

**Unit stop conditions.**

| Condition | Action |
|---|---|
| The descriptor edit requires a change to `scripts/port_config.py` | **Stop and escalate.** It is graded. Adding entries to arrays that already exist needs no schema change; if it seems to, the edit is wrong (see KTD3). |
| `--check` still refuses after custody is complete, for a reason other than unclassified paths | Stop and report the new refusal verbatim rather than widening the unit. |
| A new upstream path fits none of the existing custody classes | Stop. A new class is a recorded decision, not an inline choice. |
| Any upstream edit is required to make custody work | Upstream filing, never a downstream patch. |
| One of the seven "hermetic" claims fails re-verification | Stop. That path's custody is an open decision, not a byte copy. |

**Predeclared review dimensions.** Custody correctness (is each of the eight
classifications right, and is the excluded one excluded for the stated reason?);
generated-artifact consistency (do the notes still describe the bytes they will be
copied into?); premise verification (are the surviving line claims true at the
pin?).

---

### U2. Run the synchronization — issue #53

**Objective.** Derive the portable package from upstream `3b2b7083`: regenerate
every byte copy, re-apply all four transform rules, relocate the Claude manifest,
and rewrite `PROVENANCE.json`. **This is the unit that moves the pin.**

This unit is mechanical by design. The descriptor decides custody; the tool applies
it. If this unit finds itself making a judgment call, something upstream of it was
left unsettled — stop and say so.

**Deliverables.**

1. The synchronization run, then a clean `--check` round-trip.
2. `PROVENANCE.json` regenerated: `source_commit` `3b2b7083…`, `source_version`
   `2.15.2`, and 70 file entries (63 today, plus the seven new byte copies).
3. The package at **71 files**.
4. **Positive proof that all four transform premises held**, recorded in the commit
   body or a short note — not assumed:
   - `normalize-skill-frontmatter`: all seven `SKILL.md` files still carry
     `when_to_use`.
   - `resolve-bundled-fleet-module-split`: `executor_profile_lint.py` is
     byte-identical between the two pins, so the rule's input did not move.
   - `resolve-bundled-fleet-module-guarded`: the guarded block in `sdlc_manager.py`
     is byte-identical in shape; only its line number moved, and the rule matches by
     pattern.
   - `relocate-claude-manifest`: a pure relocation whose source and output digests
     are equal.
5. Positive proof that fleet-core was not touched (R20).

6. **Author the `sync_template_docs.py` package-root transform rule (KTD14, R41 —
   added by Amendment 1, narrowed by Amendment 2). The descriptor reclassification
   that selects this rule is U1b's, and lands before this unit runs.** Upstream 2.15.2 made this carried byte copy unimportable in the
   portable layout: `_find_package_root()` at line 17 walks up for
   `.claude-plugin/plugin.json` and raises at line 22, and it is called at module
   scope on line 27, but the portable package has no `.claude-plugin/` — the Claude
   manifest is relocated to `com.infiquetra.claude/plugin.json`. Move the path from
   `custody.byte_copies` to `custody.entrypoint_transforms` and author a **new
   versioned rule** that resolves the package root through the portable marker
   instead. The rule keeps the family's discipline: one named version, an
   "expected exactly one" match, deterministic output reproducible from the upstream
   bytes alone. Model it on `normalize-skill-frontmatter`, which is the identical
   shape. The match unit is the one `_find_package_root` definition plus the one
   module-scope call (KTD14); the two `.claude-plugin` sites inside the function
   are not two matches. **This plan does not author the rule; the worker does.**

   Ordering note: the descriptor reclassification (U1b) lands **before** this unit's
   synchronization run — a sync against the old classification would re-copy the
   unimportable bytes.

**Files owned.** Everything the sync tool writes under `plugins/mission-control/`
— `PROVENANCE.json`, `CHANGELOG.md`, `config/sdlc-schema.json`,
`scripts/sdlc_manager.py`, `scripts/sync_template_docs.py`, the four changed
`SKILL.md` files, the two `skills/board/references/*.md` files, the five files under
`com.infiquetra.claude/`, and the eleven modified plus seven new files under
`tests/`. Inside the package root U2 writes nothing target-owned: `README.md`,
`plugin.json`, `fleet-bundle.json`, and `scripts/_bundled/` are authored here and
the tool never writes them.

**One file outside the package root (KTD14, §14; narrowed by Amendment 2 to respect
#53).** The original wording said "U2 writes nothing outside the package root." That
is no longer true, and the single exception is named rather than implied:

- `scripts/sync_vendor_source.py` — **sole writer.** Authors and registers the new
  package-root transform rule. This path moved out of §6.3's do-not-write table; the
  prohibition on every *other* kind of edit to that file still stands (§6.3 note).

**U2 completes in two commits (KTD15).** The split is forced by two committed tests,
not chosen:

- **U2a — register the rule**, before anything names it. A descriptor may only name a
  registered rule (KTD15 P1), so this has to precede U1b. Registering a sixth rule
  leaves `tests/test_sync_vendor_source.py::MissionShapedSyncTests.test_rule_names_register_exactly_once`
  red, because that test pins the registry to a literal five-element set — and that
  file is U4's under #55, which #53 forbids U2 from touching. U4a repairs it next.
  U2a is the one commit in the run whose red is a registry-name mismatch.
- **U2b — run the synchronization**, after U1b has reclassified the path. A sync
  against the old classification would re-copy bytes that cannot be imported.

#53 is the only child issue with no `unittest discover` criterion, which is what makes
both of U2's commits legitimate places for a red suite. Its own criteria —
`check_repo`, the package pytest on the floor interpreter, `--check`, `git diff
--check` — are green at U2b.

**What U2 does *not* write.** Amendment 1 also gave U2 the
descriptor and the synchronizer's test file. Issue #53's out-of-scope section forbids
both — "No edit to `ports/mission-control.json`" and "No downstream test edits" — and
#53 is authoritative. So the descriptor reclassification is **U1b's** and the rule
coverage is **U4a's** (KTD14). U2 authors the rule and runs the sync; that is all.

**Test scenarios.** The seven new upstream test files arrive as byte copies and
are never edited here; editing a byte copy to make it pass is the custody
violation this arrangement exists to prevent. This unit authors no package-test
content. Rule-coverage tests in `tests/test_sync_vendor_source.py` are the
Amendment 1 exception below, and they must not touch the three pin constants.

Scenarios exercised by existing tests:
`plugins/mission-control/tests/` — all 21 existing files plus the 7 new ones must
pass on the floor interpreter after the sync.
`tests/test_sync_vendor_source.py` — expected **red** on exactly the three named
pin constants, repaired by U4; any other failure in that file is a stop.

**Amendment 2 moved the rule's focused coverage to U4a**, which owns
`tests/test_sync_vendor_source.py` (KTD14, R42). U2's own proof that the rule works is
behavioural and lands in this unit: the `--check` round-trip, and
`plugins/mission-control/scripts/sync_template_docs.py` importing without
`RuntimeError` so the two package-suite collection errors clear.

**Verification.**

```bash
# Apply, then prove the round-trip
python3 scripts/sync_vendor_source.py --package mission-control \
  --source ../infiquetra-claude-plugins --commit 3b2b7083
python3 scripts/sync_vendor_source.py --package mission-control \
  --source ../infiquetra-claude-plugins --commit 3b2b7083 --check

# Pin, file count, provenance entries, and the excluded test
python3 -c "import json;d=json.load(open('plugins/mission-control/PROVENANCE.json'));print(d['source_commit'],d['source_version'],len(d['files']))"
git ls-files plugins/mission-control | wc -l          # expect: 71
test ! -e plugins/mission-control/tests/test_card_validator_agreement.py && echo "excluded as ruled"

# Transform premises, proven not assumed
for s in board flow issues labels metrics milestones rollout; do \
  printf "%s: " "$s"; grep -c "^when_to_use:" plugins/mission-control/skills/$s/SKILL.md; done
git -C ../infiquetra-claude-plugins diff --stat 84eaf042 3b2b7083 \
  -- plugins/mission-control/scripts/executor_profile_lint.py     # expect: empty

# Fleet core untouched
git diff --name-only <base>..HEAD -- plugins/fleet-core \
  plugins/mission-control/scripts/_bundled plugins/mission-control/fleet-bundle.json | wc -l   # expect: 0

# Gates, including the floor interpreter
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
# expect: the three MISSION_CONTROL_PIN / source_version assertions red; do not edit those constants
python3 -m pytest plugins/mission-control/tests -q
"$FLOOR_PY" -m pytest plugins/mission-control/tests -q
git diff --check
```

**Expected suite state at this unit.** The repository suite may go red here on
exactly the three `test_sync_vendor_source.py` pin constants, which are hardcoded
**on purpose** — that file's own comment says moving the pin "is a deliberate act
that has to change a test, not a silent drift." Repairing them is **U4's**
deliverable, not U2's. U2 records the expected failures by name in its commit body
and does not touch the three pin constants. Any *other* failure is a stop
condition.

**Commit shape.**
`feat(mission-control): resynchronize the portable package from upstream 3b2b7083`
Body: `Refs #53`, the base SHA, the 64→71 file count, the new tree digest, the
four transform premises confirmed, and the named, expected `test_sync_vendor_source`
pin failures deferred to U4.

**Unit stop conditions.**

| Condition | Action |
|---|---|
| Any transform rule refuses | **Stop. Report the shape it found. Never relax a rule to fit.** The "expected exactly one" assertions are the proof, not the obstacle. |
| `--check` reports drift in a `target-owned` path | Stop. The descriptor's custody is wrong and the sync must not be applied. |
| A byte copy's post-sync digest does not equal its source digest | Stop. |
| A carried test cannot pass without a content change | Stop. Upstream filing or recorded custody decision — **never** an edit to a byte copy. Editing a byte copy to make the suite pass is the exact violation this whole arrangement exists to prevent. |
| The file count is not 71 | Stop. Either a custody class is wrong or the exclusion did not take. |
| A suite failure other than the three known `test_sync_vendor_source` pin constants, and other than the six failures KTD14 attributes to the `sync_template_docs.py` package-root blocker | Stop and triage before committing. |
| The new package-root rule needs a second match shape, or an "expected exactly one" assertion loosened to make it fit | Stop. A transform rule that accepts two shapes stops proving what it exists to prove — the same stop condition that governs the existing four rules. |
| The reclassification appears to need a change to `scripts/port_config.py` | Stop and escalate. It is graded. Moving a path between two custody arrays that already exist needs no schema change (KTD3's reasoning applies unchanged). |

**Predeclared review dimensions.** Derived-artifact integrity (does every byte copy
equal its source?); transform-rule soundness (did any rule get widened?); custody
boundary (did anything target-owned get overwritten?); shipped-behavior parity.

---

### U3. Target-owned surface, verb reclassification, and the no-write guard — issue #54

**Objective.** Update every hand-authored file that states an upstream fact about
the package, correct the audited mutating-verb table under ruling 4, and — where a
fact can be derived instead of retyped — derive it, so this class of staleness stops
recurring.

**This is the last unit permitted to touch bytes inside
`plugins/mission-control/` as planned. The package fingerprint is final when it
lands — except for the one later exception Amendment 6 (§19) records: the
F18/F11/F35 corrections at `a1e84e0` moved the tree after the freeze, and U5
was re-run and re-bound at `863af58`, issue #56's frozen commit.**

**Base and landing order (KTD10, KTD15, R39, R43).** U3's work begins from the post-U2
commit and runs concurrently with U4. **U3's commits do not.** U3 rebases onto
**U4b's commit**, which is its base for every `<base>..HEAD` comparison below, and it
lands in **two commits**:

- **U3a** — everything that touches the package root or the verb lock: `plugin.json`,
  the portable `README.md`, `ports/mission-control.json`'s
  `assessment.mutating_operations`, the two verb constants, the `create-option`
  no-write guard, and the manifest-version derivation test. **This is the last edit to
  bytes inside `plugins/mission-control/`, so the freeze follows it.** At U3a the
  suite is still red on one test, `LiveDocumentTest`, which U5 owns and clears; U3a is
  not U3's completion, so no criterion is measured there (KTD15).
- **U3b** — after the freeze and after U5: the root `README.md` pin, version, file
  count, and test counts, plus the pin test that recomputes them from disk. **U3
  completes here**, and here the full suite is green outright. Deferring the counts is
  more honest than writing them early: they can only be finally correct once every
  unit has landed. U3b touches nothing under `plugins/mission-control/`, so it cannot
  disturb the freeze or invalidate U5's assessment.

The reason is issue #54's own acceptance criterion, which requires `python3 -m
unittest discover -s tests` to report `OK`. After U2 that command is red on two
things: three constants in `tests/test_sync_vendor_source.py`, which U4 owns and U3
must not touch, and `LiveDocumentTest`, which U5 owns and clears. Rebasing onto U4b
removes the first; landing U3b after U5 removes the second. **U3 carries no expected-red
list of any kind; U2 is the only unit that does (§2.6), and #54's criterion is met at
U3b at full strength.** If U4b has not committed yet, U3 waits — it does not gate early,
and it never edits `tests/test_sync_vendor_source.py`.

**Deliverables.**

1. **Four files that move together in one commit, or the suite goes red.**
   `tests/test_mission_control_readme.py` asserts that the descriptor's audited
   mutating-verb set equals the test's own constant — its failure message reads
   "the port descriptor's audited mutating-verb table moved; update `MUTATING_VERBS`
   deliberately, never silently" — then asserts every audited verb appears in the
   portable README, and separately refuses any fenced README command that invokes a
   mutating verb. So `ports/mission-control.json`,
   `plugins/mission-control/README.md`, and the two constants in
   `tests/test_mission_control_readme.py` change **in the same commit**.

2. **Three verb-table changes, each verified against the pinned source.**

   | Change | Evidence at `3b2b7083` |
   |---|---|
   | Add `set-options` to the mutating set | `fields_set_options` is defined at `scripts/sdlc_manager.py:2070` and calls `update_field_single_select_options` at line 2113, which issues a real mutation unless `--dry-run` is passed. Ruling 4 keeps it mutating and protected. |
   | Move `create-option` to the read-only set | `fields_create_option` is defined at line 2026; its docstring at line 2029 states "This command performs NO mutation — it never has." It only discovers a field and prints its existing options. It was mis-declared at the original port, not changed since. |
   | Drop `update` from the `rollout` read-only row | Removed upstream by filing #821 as dead code whose help text falsely claimed to write `beads-config.json`. |

   Concretely, in this repository as measured this session:
   - `ports/mission-control.json` → `assessment.mutating_operations` (25 entries):
     remove `create-option`, add `set-options`.
   - `tests/test_mission_control_readme.py` → `MUTATING_VERBS`: remove
     `create-option`, add `set-options`. `READ_ONLY_VERBS`: add `create-option`,
     remove `update` (currently listed under the `# rollout` comment).
   - `plugins/mission-control/README.md` line 62 (`| fields | discover |
     create-option |`) and line 65 (`| rollout | status, gap-analysis, update |
     …`). **Also the prose at lines 72–73**, which currently says "`rollout update`
     maintains the legacy local rollout configuration" — a sentence about a verb
     that no longer exists. Changing only the tables leaves a false paragraph
     standing.

3. **A focused no-write guard for `fields create-option` (ruling 4).**
   Reclassifying a verb from mutating to read-only *narrows a safety declaration*,
   and a narrowed safety claim needs positive proof rather than a changed constant.
   The guard asserts the **mutation path is never reached** on that verb — in the
   style the new upstream `tests/test_option_identity.py` uses for its own error
   paths. A test that merely asserts the function returns without error proves
   nothing about writes and does not satisfy this deliverable. Prove the guard can
   fail: mutate it locally so it goes red, capture the transcript, revert.

4. **Five unbound version and count claims, closed by derivation or a pin test.**

   | Site | Current claim | Treatment |
   |---|---|---|
   | `plugins/mission-control/plugin.json` | `"version": "2.12.2"` and a description reading "derived from infiquetra-claude-plugins at the 2.12.2 revision" | update, **and** bind by a test to `PROVENANCE.json`'s `source_version` (KTD5), on the `tests/test_agent_launcher_packaging.py` pattern |
   | `plugins/mission-control/README.md:12` | "upstream plugin version 2.12.2" | update; covered by the README test file U3 already owns |
   | root `README.md:30–31` | "a 64-file portable package derived from upstream commit `84eaf042` (version 2.12.2), with 266 ported tests" | update, and pin by a test that recomputes from disk (KTD6) |
   | root `README.md:71–75` | "ships 64 portable files and 266 CI tests … Pinned to `84eaf042` (v2.12.2) … Twenty-one test files (266 tests)" | update, and pin |
   | root `README.md:163` | Packages-table row reading `` `84eaf042` (v2.12.2) `` | update, and pin — **this is the exact cell shape that produced the #9 run's only review finding** |

   The pin test lives in `tests/test_mission_control_rule_audit.py` (not graded).
   It must **recompute** the file count and the package test count from disk and
   assert the README states them, rather than comparing two typed constants.
   Deriving a count inside `scripts/check_repo.py` is a stop condition (graded).

5. **A `DECISIONS.md` entry** for the verb reclassification and the derivation
   pattern, with rejected alternatives and a revisit condition (KTD12, KTD5, KTD6).

**Files owned.** `ports/mission-control.json` (**only**
`assessment.mutating_operations`), `plugins/mission-control/plugin.json`,
`plugins/mission-control/README.md`, root `README.md`,
`tests/test_mission_control_readme.py`, `tests/test_mission_control_rule_audit.py`,
`docs/engineering-journal/DECISIONS.md` (append).

**Test scenarios.**

`tests/test_mission_control_rule_audit.py` — **create-option no-write guard.**
Invoking the `fields create-option` path must never reach a write operation; the
test fails if a mutation constant is reached. Negative proof required: mutate the
guard locally so it goes red, capture the transcript, revert.

`tests/test_mission_control_rule_audit.py` — **manifest-version derivation.**
`plugins/mission-control/plugin.json`'s `version` equals
`plugins/mission-control/PROVENANCE.json`'s `source_version`; a hand-edited
manifest fails.

`tests/test_mission_control_rule_audit.py` — **root README Packages-row pin.** The
row's revision and version equal `PROVENANCE.json`'s; a stale row fails rather
than sits. This is the #9 finding's exact cell.

`tests/test_mission_control_rule_audit.py` — **root README counts.** The stated
package file count and package test count are **recomputed from disk** and
compared; a retyped stale count fails.

`tests/test_mission_control_readme.py` — **the three-way lock.** The descriptor's
audited verb set equals `MUTATING_VERBS`; every audited verb appears in the
portable README; no fenced README command invokes a mutating verb.

**Verification.**

```bash
# The three-way lock between descriptor, README, and test constants
python3 -m unittest tests.test_mission_control_readme -v

# The new guard, the derivation test, and the root-README pin test
python3 -m unittest tests.test_mission_control_rule_audit -v

# Manifest version agrees with the recorded pin, by derivation
python3 -c "import json;m=json.load(open('plugins/mission-control/plugin.json'));p=json.load(open('plugins/mission-control/PROVENANCE.json'));print(m['version'],p['source_version']);assert m['version']==p['source_version']"

# Verb table, as data
python3 -c "import json;m=json.load(open('ports/mission-control.json'))['assessment']['mutating_operations'];print('set-options' in m, 'create-option' in m)"   # expect: True False

# Gates
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
"$FLOOR_PY" -m pytest plugins/mission-control/tests -q
git diff --check
```

**Commit shape (two commits, KTD15).**

U3a — `feat(mission-control): derive the target-owned surface and correct the audited verb table`
Body: `Refs #54`, the base SHA (U4b's commit), the three verb changes with their
evidence lines, an explicit note that this is the **last** edit to bytes inside the
package root, and the one named test still red (`LiveDocumentTest`, U5's).

U3b — `docs(mission-control): pin the root catalog row and counts to the resynchronized package`
Body: `Refs #54`, the base SHA (U5's commit), the derived counts, and the full
four-gate transcript showing `unittest discover` `OK`. **U3 completes here.**

**Unit stop conditions.**

| Condition | Action |
|---|---|
| A verb's mutating status cannot be settled by reading its implementation | Stop. Over-declaring is the safe direction; **never narrow a safety claim on inference.** |
| The lock test's failure message fires and the fix is to loosen the assertion | Stop. The lock is the control, not the obstacle. |
| Deriving a count would require changing `scripts/check_repo.py` | Stop and escalate; it is graded. Put the pin in `tests/test_mission_control_rule_audit.py` instead. |
| The no-write guard cannot be made to fail on a deliberate local mutation | Stop. A guard that cannot fail proves nothing (§2.7, harness soundness). |
| Any edit is needed inside `plugins/mission-control/` beyond `plugin.json` and `README.md` | Stop. That is U2's custody, and it would move the fingerprint for a reason the freeze cannot account for. |

**Predeclared review dimensions.** Safety-boundary narrowing (is the reclassification
proven, not asserted?); derivation completeness (is any identity claim still
unbound?); the #9 finding class (hand-transcribed identity rows); documentation
truthfulness (does the prose match the tables?).

---

### U4. Downstream pin repair and full-suite re-green — issue #55

**Objective.** Perform the deliberate act the pin constants exist to force, and
bring the whole repository suite back to green on the resynchronized package.

**Base and landing order (KTD10, KTD15, R39, R43).** U4's base is the **post-U2
commit**, and every `<base>..HEAD` comparison below is against it. U4 lands in **two
commits**:

- **U4a — the earliest commit of any unit after U2a.** Extend `expected` in
  `tests/test_sync_vendor_source.py::MissionShapedSyncTests.test_rule_names_register_exactly_once`
  from five registered transform rules to six. U2a's registration leaves that test
  red, U4 owns the file under #55, and #53 forbids U2 from repairing it — so this is
  U4's work and it must land before U1b's green completion (KTD15 P2). **U4a is
  green.** Not U4's completion.
- **U4b — after U2b, before U3a.** The three pin constants, plus the focused coverage
  for the new package-root transform rule (KTD14, R42). The constants can only move
  once the synchronization has rewritten `PROVENANCE.json` (KTD15 P3). U4b is what
  clears the pin reds, which is why it precedes U3a. The suite is still red on
  `LiveDocumentTest`, which U5 owns. Not U4's completion.
- **U4c — after U5.** The skill-roster confirmation, the PyYAML-stays-in-CI
  confirmation, and the recorded four-gate transcript. **U4 completes here**, on a
  tree where `unittest discover` reports `OK` outright, satisfying #55 at full
  strength. U4c touches nothing under `plugins/mission-control/`, so the freeze holds.

**Deliverables.**

1. `tests/test_sync_vendor_source.py`:
   - `MISSION_CONTROL_PIN` (line 1359) moves from
     `"84eaf042f0e350005f7eddf8e7d80da25c12119d"` to
     `"3b2b7083fdda8e39e213b5f4acf9f8301d60dd52"`.
   - The `source_version` assertion (line 1382) moves from `"2.12.2"` to
     `"2.15.2"`.
   - `MISSION_CONTROL_SKILLS` (line 1360) is **confirmed, not copied**. The roster
     is unchanged at 2.15.2 — `board`, `flow`, `issues`, `labels`, `metrics`,
     `milestones`, `rollout` — so this is a confirmation. The asymmetry is the point:
     a *removed* skill fails loudly with a missing file, while an *added* skill would
     simply go unchecked, so the tuple is re-derived against `ls
     plugins/mission-control/skills` rather than assumed.
2. All four gates green, plus the floor-interpreter package run. The new baseline is
   773 plus whatever U3 added, with **no regressions**.
3. Positive proof that this unit is fingerprint-neutral (R27).
4. A recorded confirmation that **PyYAML stays** in the continuous-integration
   install line (`.github/workflows/ci.yml:59`). Upstream filing #828 deferred only
   `sdlc_manager.py`'s import; `plugins/mission-control/scripts/sync_template_docs.py:14`
   and `plugins/mission-control/tests/test_template_sync.py:7` still import `yaml`
   at module scope. Dropping it on a misreading of #828 would break the package suite
   in continuous integration while passing locally.

**Files owned.** `tests/test_sync_vendor_source.py` only. **No file under
`plugins/mission-control/` may change in this unit** — that is what makes the
U3/U4 concurrency safe.

**Test scenarios.**

`tests/test_sync_vendor_source.py` — **the deliberate pin move.**
`PROVENANCE.json`'s `source_commit` equals `MISSION_CONTROL_PIN` at the new pin,
and `source_version` equals `2.15.2`. The class is guarded on `PROVENANCE.json`
existing, so it is silent before U2 and load-bearing after it.

`tests/test_sync_vendor_source.py` — **skill-roster confirmation.**
`MISSION_CONTROL_SKILLS` matches the shipped roster and drives the seven
skill-frontmatter checks. Re-derive the tuple against `ls
plugins/mission-control/skills`; do not copy it forward.

Regression scope: the full `tests/` discovery must return to `OK` with no
failures and no errors, at 773 plus whatever U3 added.

**Verification.**

```bash
python3 -m unittest tests.test_sync_vendor_source -v
ls plugins/mission-control/skills          # expect exactly the seven recorded names

python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
"$FLOOR_PY" -m pytest plugins/mission-control/tests -q
git diff --check

# Fingerprint neutrality
git diff --name-only <base>..HEAD -- plugins/mission-control | wc -l   # expect: 0
```

**Commit shape (three commits, KTD15).**

U4a — `test(sync): register the sixth transform rule in the pinned rule-name set`
Body: `Refs #55`, the base SHA (U2a's commit), and why the registry set moved from
five names to six.

U4b — `test(mission-control): move the downstream pin to 3b2b7083 and cover the package-root rule`
Body: `Refs #55`, the base SHA (U2b's commit), the old and new pin values, what the new
rule coverage asserts, and the one named test still red (`LiveDocumentTest`, U5's).

U4c — `test(mission-control): confirm the skill roster and the PyYAML CI floor on the resynchronized package`
Body: `Refs #55`, the base SHA (U3b's commit), the confirmed roster, the PyYAML
finding, and the new suite total against the 773 baseline. **U4 completes here.**

**Unit stop conditions.**

| Condition | Action |
|---|---|
| A suite failure that is not one of the three known pin constants | **Stop and triage. Report what drifted before changing anything.** A second failure that gets a constant bumped alongside the pin hides a real drift. |
| A fix would require editing a file under `plugins/mission-control/` | Stop. That is an upstream filing or a defect in U2's custody, never a downstream patch here. |
| The skill roster differs from the seven recorded names | Stop. A roster change is a custody question, not a constant bump. |
| The floor-interpreter run fails where the default interpreter passes | Stop and report. A floor-only failure is a real portability defect, not an environment nuisance. |

**Predeclared review dimensions.** Deliberate-change discipline (was every changed
constant supposed to change?); regression coverage; fingerprint neutrality.

---

### U5. Fresh assessment, readback, supersession, and bindings — issue #56

**Objective.** Re-establish the observational evidence that says what the
resynchronized package is, and bind it so a future resynchronization can never
leave that evidence stale in silence.

**Precondition.** The freeze integration in §5 is complete and its fingerprint
recorded. U5 is the run's **real checkpoint**; no synthetic checkpoint precedes it.

**Deliverables, in the only order the code permits.**

1. **Capture the frozen fingerprint** (`--print-fingerprint mission-control`) and
   record it verbatim.
2. **Run the fresh ten-client, forty-stage assessment** against the frozen package
   — placement, discovery, load, invocation, for all ten clients.
   **This step is operator-attended and cannot be unattended.** The harness never
   infers a launcher binary: `which` returns the wrapper, and a wrapper pointed at
   itself spawns descendants until the host gives out. So the operator supplies the
   real binaries for **Grok** and **Agy** through `--real-binary`, and **Cursor**
   runs against the real authenticated home — an isolated home strips its
   authentication and records a false failure, which has actually happened before.
   Hermes runs in an isolated home only. **Coverage is mandatory; passing is not.**
   No failing client blocks this work, and no client-specific remediation may begin
   without a separate operator decision.
3. **Re-capture the fingerprint** after the run and prove it is identical (R29).
4. **Publish the new compatibility matrix** and the **new post-activation
   readback**, both bound to the new fingerprint, both `matrix-status: current`.
   The readback keeps a `cycle_16_verification` block per KTD11.
5. **Only then, supersede the two old documents.** The ordering is enforced by
   code, not policy: `check_document_status()` requires a superseded document to
   name a `superseded-by` successor that exists and is **itself current**, plus a
   `superseded-reason`; and a further guard refuses a superseded stamp while the
   document's fingerprint still identifies the package in its current revision. The
   old matrix already carries an HTML-comment directive block
   (`<!-- matrix-status: current -->`); the old readback carries **no** directive
   block today and needs one added at its head, following the shape used by
   `docs/evidence/2026-08-22-unifi-compatibility-matrix-pre-resync.md`.
6. **Add the binding classes** to `tests/test_check_compatibility_matrix.py` (KTD4):
   - a mission-control **matrix**-binding class asserting the recorded fingerprint,
     package name, and version against the live package;
   - a mission-control **readback**-binding class asserting the `release` block, the
     per-skill-unit fingerprints for all seven skills, `upstream_commit` and
     `version` against `PROVENANCE.json`, and every `readbacks` entry;
   - a class asserting all four superseded mission-control documents carry a `superseded-by` naming a
     current successor and a `superseded-reason`.

   **The two packages' readbacks are not the same shape.** Mission Control's record
   carries `schema_version`, `captured_on`, `release`, `method`, `readbacks`, and
   `cycle_16_verification`. It has **no** `profile_states` block — that is a UniFi
   concept tied to `site_profile.py` — and it records three readback clients, not
   ten. The mission-control binding asserts the `release` block and every
   `readbacks` entry and **omits** the profile-state assertions. Note also that the
   mission-control readback is not discovered as a matrix document at all: its
   record uses `release` and `readbacks` keys rather than `package` and `clients`,
   so pointing the checker at it reports "`$.package`: missing or not an object, so
   nothing binds the record to a tree". The binding therefore has to come from the
   test file, which is the second reason KTD4 lands there.
7. **Prove the bindings can fail**: mutate a recorded fingerprint locally so both
   new classes go red, capture the transcript verbatim, revert, re-run green.
8. **Journal.** A `DECISIONS.md` entry for the supersession and the binding pattern,
   and a `QUEUED.md` update moving the consumed resync entry toward closure.

**Files owned.** `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md`
(current), `docs/evidence/2026-08-30-mission-control-post-activation-readback.md`
(current), the four superseded mission-control evidence documents — the
2026-08-25 pair and the 2026-08-30 `-pre-fingerprint-move` pair (supersession
directives only — **never** their numbers),
`tests/test_check_compatibility_matrix.py`,
`docs/engineering-journal/DECISIONS.md` (append),
`docs/engineering-journal/QUEUED.md`.

**Test scenarios.**

`tests/test_check_compatibility_matrix.py` — **mission-control matrix binding
class.** The new matrix's recorded `file_count`, `tree_sha256`, package name, and
version equal the live package's; a drifted fingerprint fails.

`tests/test_check_compatibility_matrix.py` — **mission-control readback binding
class.** The `release` block's `upstream_commit` and `version` equal
`PROVENANCE.json`'s; all seven per-skill-unit fingerprints match; every
`readbacks` entry is asserted. No `profile_states` assertions — that block is a
UniFi concept and mission-control's record does not carry it.

`tests/test_check_compatibility_matrix.py` — **supersession chain.** Each
superseded document names a `superseded-by` successor that exists and is itself
current, plus a `superseded-reason`.

**Negative proof required.** Mutate a recorded fingerprint locally so both new
binding classes go red, capture the transcript verbatim, revert, re-run green. A
binding that has never been seen to fail is not evidence.

**Verification.**

```bash
# Fingerprint, before and after the run — record both, prove they match
python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control

# Plan first; runs nothing
python3 scripts/assess_clients.py --package mission-control

# Operator-attended execution, real binaries supplied
python3 scripts/assess_clients.py --package mission-control --execute \
  --python <venv>/bin/python3.12 --workspace <scratch> \
  --real-binary grok=<path> --real-binary agy=<path> --out <record>.json

# New evidence, then the supersession chain
python3 scripts/check_compatibility_matrix.py docs/evidence/<new-matrix>.md
python3 scripts/check_compatibility_matrix.py docs/evidence/2026-08-25-mission-control-compatibility-matrix.md

# Bindings, gates, and the graded-file proof (R36 — the four mandated, plus the floor run)
python3 -m unittest tests.test_check_compatibility_matrix -v
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
"$FLOOR_PY" -m pytest plugins/mission-control/tests -q
git diff --check
git diff --name-only <base>..HEAD -- scripts/port_config.py scripts/check_repo.py scripts/check_compatibility_matrix.py scripts/assess_clients.py plugins/unifi/scripts/site_profile.py | wc -l   # expect: 0 (the five graded files by name; sync_vendor_source.py is KTD14's and not graded)
git diff --name-only <base>..HEAD -- plugins/mission-control | wc -l                          # expect: 0
```

**Commit shape.**
`docs(evidence): fresh ten-client assessment, readback, supersession, and fingerprint bindings`
Body: `Refs #56`, the base SHA, the frozen fingerprint quoted before and after the
run, the ten client statuses in one line, and the confirmation that no graded file
changed.

**Unit stop conditions.**

| Condition | Action |
|---|---|
| The package tree digest differs before and after an assessment run | **Discard that run's record.** It describes bytes that no longer exist. |
| A supersession stamp is refused by the checker | Stop. **Fix the ordering, never the guard.** The refusal means the successor is not yet current — that is the guard working. |
| Editing an evidence number would clear a failure | Stop. Re-run the assessment or leave it red. Refreshing numbers without re-running is precisely the failure the binding exists to catch. |
| A binding would require editing `scripts/check_compatibility_matrix.py` or another graded file | Stop and escalate (KTD4, §2.8). |
| A client's real binary cannot be supplied | Record that client **blocked** with the requirement named. **Never infer the binary, never skip the client.** |
| A client fails for a harness reason (e.g. an isolated home stripping authentication) | Record it **blocked** with the requirement named. A failure attributed to the package when the harness caused it is a false record. |
| Any verification harness found unsound | Discard that round's evidence and re-run. |
| Any live GitHub write from the assessment | **Run-level stop.** |

**Predeclared review dimensions.** Evidence integrity (were the numbers measured or
edited?); binding soundness (can the new tests actually fail?); supersession
ordering; graded-file containment; honest failure attribution.

---

## 8. Landing and merge schedule

### 8.1 Sequence

| Step | What happens | Gate before proceeding |
|---|---|---|
| 1 | **U0** commits the entry-criteria note — *landed* | four gates green; the pin proven green in a scratch clone |
| 2 | **U1a** commits the descriptor custody and notes refresh — *landed at `12c889c`* | four gates green |
| 3 | **U2a** registers the package-root transform rule in `scripts/sync_vendor_source.py` | `check_repo`, package pytest, floor run, `git diff --check` green. `unittest discover` red on `test_rule_names_register_exactly_once` only (KTD15 P2) — #53 carries no `unittest discover` criterion |
| 4 | **U4a** extends `expected` in that registry test to the six registered rules | all four gates green plus the floor run. Not U4's completion |
| 5 | **U1b** reclassifies `scripts/sync_template_docs.py` in the descriptor, naming the now-registered rule | all four gates green plus the floor run. *Was U1's completion before Amendment 4; U1 now completes at step 7* |
| 6 | **U1c** reclassifies `tests/test_issue_contract_parity.py` and `tests/test_template_sync.py` from byte copies to transforms (KTD16) | all four gates green plus the floor run, on a clean checkout — the rule *name* is already registered and the descriptor join checks names, not versions. **U1 completes here, satisfying #52** |
| 7 | **U2b** bumps `resolve-package-root-marker` to the assertion-covering v2, then runs the synchronization | `--check` round-trips clean; 71 files; `check_repo`, package pytest, floor run, `git diff --check` green. `unittest discover` red on the pin constants and `LiveDocumentTest` — allowed only because #53 has no such criterion |
| 8 | **U4b** commits the three pin constants and the new rule's focused coverage | `python3 -m unittest tests.test_sync_vendor_source -v` reports `OK`; the pin reds clear. Not U4's completion |
| 9 | **U3a** commits the package-root edits, the descriptor verb table, the verb constants, and the guard and derivation tests | `tests.test_mission_control_readme -v` and `tests.test_mission_control_rule_audit -v` report `OK`. Not U3's completion |
| 10 | **Freeze integration** on `orch-agent-plugins-50` | tree clean; fingerprint recorded (§5). The last point at which any byte under `plugins/mission-control/` changes **as planned** — Amendment 6 (§19) records the one later exception: `a1e84e0`, the F18/F11/F35 corrections, moved the tree after this point, U5 was re-run and re-bound at `863af58`, and `863af58` is issue #56's frozen commit |
| 11 | **U5** commits the fresh assessment, evidence, supersession, and bindings | all four gates green plus the floor run, **including `unittest discover` `OK`** — U4b cleared the pin constants and this commit clears `LiveDocumentTest`. Both new documents validate. **U5 completes here, satisfying #56** |
| 12 | **U3b** commits the root `README.md` pin, version, and counts, and its pin test | all four gates green plus the floor run. **U3 completes here, satisfying #54** |
| 13 | **U4c** commits the skill-roster and PyYAML confirmations and the recorded gate transcript | all four gates green plus the floor run. **U4 completes here, satisfying #55** |
| 14 | **Review** — two independent reviewers in parallel, maximum three rounds, each bound to the frozen revision (§2.4) | all confirmed findings batched into one repair per round |
| 15 | **Open one pull request** from `orch-agent-plugins-50` into `main` | the pull-request body states the merge form the policy actually allows |
| 16 | **Squash-merge** (KTD8) | acceptance criteria on #50 all checked |
| 17 | **Close #51–#56**, each recording its base, frozen, and merged commit; then close **#50** | per-child SHA record complete (§2.3). A unit that landed in more than one commit records every frozen SHA (Q8) |

### 8.2 What is landed, and what is not

Nothing lands on `main` until the whole run is reviewed. All fourteen child-scoped
commits as landed — twelve by design, U0 shipped in three — (KTD15, KTD16, Q8) live
on `orch-agent-plugins-50` until the merge step, which is
what lets the freeze mean something: the fingerprint U5 assesses is the fingerprint
that ships.

The evidence bindings are **content-addressed** — the matrix binds
`$.package.{file_count,tree_sha256}` and the mutation proof binds file digests,
never a commit id. That is why the squash is safe: squashing rewrites commit ids and
changes nothing the evidence claims. This survived the same policy surprise in #9.

### 8.3 Post-merge readback

After the squash lands, re-run on `main` before closing anything:

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control
python3 scripts/check_compatibility_matrix.py docs/evidence/<new-matrix>.md
python3 -c "import json;d=json.load(open('plugins/mission-control/PROVENANCE.json'));print(d['source_commit'],d['source_version'])"
```

The fingerprint printed on `main` must equal the frozen fingerprint U5 recorded. If
it does not, something changed between the freeze and the merge and the evidence is
stale — treat that as a stop, not a rounding error.

---

## 9. Scope boundaries and non-goals

**In scope.** Moving the pin from `84eaf042` to `3b2b7083`, regenerating the
derived package, correcting the descriptor and the hand-authored surface that
describes it, repairing the downstream pin constants, and re-establishing the
fingerprint-bound evidence.

**Explicitly out of scope — do not do these, even if they look adjacent:**

- **No custody move.** `infiquetra/infiquetra-claude-plugins` stays authoritative
  and is never edited by this work, in any unit, for any reason.
- **No downstream repair of copied content.** A needed byte change in a byte copy
  or a transform output goes upstream as a filing and returns through a later
  repin. Editing a copy to make a test pass is the violation the whole arrangement
  exists to prevent.
- **No live GitHub mutation** from any build, test, or assessment step.
- **No per-client remediation, marketplace manifest work, or distribution changes.**
  Client statuses are recorded; decisions on them stay open operator items.
- **No Fleet Core repin and no bundle regeneration.** `plugins/fleet-core` is
  unchanged upstream across this window; regenerating would churn the UniFi bundles
  and invalidate UniFi's committed matrix.
- **No return of `tests/test_prompt_alignment.py`.** Its premises still fail at the
  new pin (unit U1 deliverable 4).
- **No change to any of the five graded files** (§2.8), and no re-run of the
  cycle-16 mutation proof.
- **No runbook amendment.** U0 records which steps a resync skips; changing the
  runbook to carry a resync phase structure is separate work (see Q4).
- **No new blocking gate wired into continuous integration** without a separate
  operator decision (see Q5).
- **No synthetic checkpoint.** U5 owns the real checkpoint.
- **No worktrees, branches, sessions, subagents, or issues created by any unit.**
- **No disturbance of unrelated dirty files, branches, worktrees, or sessions**
  anywhere on this machine.

### 9.1 Deferred to follow-up work — distinct from the non-goals above

These are **not** permanent non-goals. Each is real work this run deliberately
declines to carry, with the condition that would justify picking it up.

| Deferred item | Why it is not in this run | Pick it up when |
|---|---|---|
| Turn `provenance.dropped_reason` into a per-path mapping | The shape is right, but it is a descriptor schema change and forces an edit to the graded `scripts/port_config.py` (KTD3) | a funded unit is willing to re-run the cycle-16 mutation proof |
| Parameterize `tests/test_check_compatibility_matrix.py` over both packages instead of duplicating classes | Duplication is the cheaper risk today; parameterizing puts UniFi's live bindings at stake for no gain (KTD4) | a third package needs bindings — then do it as its own unit with UniFi re-verified |
| A runbook v1.2.0 resync phase structure | Amending the runbook is explicitly out of scope for #51; U0 records the deviation instead | this is now the second resync writing the same deviation table (open question Q4) |
| Wire the mission-control matrix and readback into a blocking continuous-integration gate | Both #55 and #56 forbid a new blocking gate without a separate decision; the new binding classes already run under the mandated `unittest` discovery | the operator answers Q5 asking for a gate |
| Close or annotate the eight consumed upstream filings (`infiquetra-claude-plugins` #818–#822, #828–#830) | Upstream is never touched by this work, and no unit owns an upstream write | this repin lands on `main` (open question Q7) |
| One shared catalog-row pin test covering every package's root-README row | This run pins mission-control's row only; generalizing on one data point is premature (KTD6) | a third package's row goes stale |
| Per-client remediation for any client the fresh assessment records failed or blocked | Coverage is mandatory, passing is not; remediation is a separate operator decision | the operator reviews U5's ten client statuses |

---

## 10. Risks and pre-mortem

### 10.1 The single most likely failure

**The target-owned surface goes silently stale.**

Three files state the upstream version as unbound prose —
`plugins/mission-control/plugin.json`, `plugins/mission-control/README.md`, and the
root `README.md` — and **no test checks any of them today**. The root README is the
worst of the three: it also carries a 64-file count, a 266-test count, a
twenty-one-test-file count, and a Packages-table row reading `84eaf042` (v2.12.2),
all unbound, at three separate sites.

This is not a hypothetical. It is the exact defect class the #9 review caught once
already: U9's Packages table pinned UniFi at `ed72f439` when
`plugins/unifi/PROVENANCE.json` recorded `818fd684`/2.0.6, because the row was
hand-authored with no derivation and no pin test. It was the entire run's only
review finding.

The failure mode this run is exposed to is subtler than getting a number wrong. It
is getting every number **right today** by retyping it, shipping green, and
reproducing the identical defect at 2.16.0 — with the added cost that the next run
will believe the surface is checked because this run "handled" it.

**The mitigation is structural, not procedural.** U3 does not retype these claims;
it binds them (KTD5, KTD6): the manifest version is derived from `PROVENANCE.json`, and
the root README's counts and Packages row are pinned by a test that recomputes from
disk. Reviewers are briefed to check for any identity claim that is still merely
typed — that is a predeclared review dimension for U3.

### 10.2 The other named risks

| # | Risk | Mechanism | Mitigation | Owner |
|---|---|---|---|---|
| 2 | **The generated provenance file contradicts itself** | `sync_vendor_source.py` copies `provenance.notes` verbatim into `PROVENANCE.json`. Stale notes ship a file whose header says 2.15.2 while its own prose says 2.12.2, and nothing catches it. One claim is not merely stale but **false** at the new pin: PyYAML is no longer imported at module scope. | The notes refresh is a first-class U1 deliverable with its own acceptance line and its own verification commands, not a tidy-up (unit U1). | U1 |
| 3 | **An assessment run is invalidated by a later byte change** | Any edit inside `plugins/mission-control/` after the assessment retires it. | The freeze follows U3, not U2 (KTD9); U4 is fingerprint-neutral by construction and proves it (R27); U5 captures the fingerprint before *and* after the run (R29). | U3, U4, U5 |
| 4 | **The verb change breaks the three-file lock** | `tests/test_mission_control_readme.py` asserts the descriptor's audited verb set equals its own constant *and* that every audited verb appears in the README. Change one, the suite goes red. | All four artifacts move in one U3 commit, with the lock test as the gate (unit U3). | U3 |
| 5 | **A transform rule is relaxed to fit new upstream bytes** | The rules assert "expected exactly one" match by design. Widening one to accept a second shape stops it proving the thing it exists to prove — and it fails *quietly* forever after. | Hard stop condition in U2 with no exception path; reviewers briefed on rule soundness as a dimension. | U2 |
| 6 | **A custody class is chosen to make the tool stop complaining** | The tool refuses on *unclassified*, not on *wrongly classified*. Classifying the agreement test as a byte copy would silence the error and ship the defect. | Ruling 2 is explicit and KTD2 records why; U1's stop-condition table names this exact temptation. | U1 |
| 7 | **A descriptor or evidence change reaches for a graded file** | The natural fix for `dropped_reason` is a per-path map (needs `port_config.py`); the natural fix for the evidence binding is to teach the checker (needs `check_compatibility_matrix.py`). Both are graded. | KTD3 and KTD4 pre-empt both with the non-graded alternative named in advance; §2.8 lists the five files and their current digests so a unit can check itself. | U1, U5 |
| 8 | **The supersession stamp is attempted too early** | `check_document_status` refuses a superseded stamp while the document's fingerprint still matches the package, and requires the named successor to exist and itself be current. A run that reads the refusal as a tooling problem will look for a way around it. | U5's step order (unit U5) is the only order the code permits; the stop condition says fix the ordering, never the guard. | U5 |
| 9 | **A client is recorded failed for a harness reason** | This has happened: Cursor was once recorded failed because an empty scratch home stripped its authentication. | Operator supplies the real binaries and Cursor's authenticated home; a client that cannot be supplied is recorded **blocked** with the requirement named, never failed and never skipped. | U5 |
| 10 | **PyYAML is dropped from continuous integration on a misreading of #828** | #828 deferred only `sdlc_manager.py`'s import. Two other files still import `yaml` at module scope. Dropping the install line passes locally and breaks in continuous integration. | R28 makes the confirmation an explicit U4 deliverable. | U4 |
| 11 | **A failure is made to pass instead of understood** | The three pin constants are *meant* to change. A second failure that gets a constant bumped alongside them hides a real drift. | U4's first stop condition: any failure that is not one of the three named constants stops the unit and is triaged before anything is changed. | U4 |
| 12 | **The floor interpreter is never actually used** | The default `python3` here is 3.14.7; the declared floor and continuous integration are both 3.12. A package that only ever runs on 3.14 locally can ship a 3.12 break. | §2.6 adds an explicit floor run to every unit that runs the package suite, by absolute path per the runbook. | all |

---

## 11. Open questions

Eight genuine operator questions (Q1–Q8). **Q8 blocks execution and needs a
decision; the other seven do not.** None blocks the run: each names the
option this plan **took** and why, so execution proceeds on the recorded choice
unless the operator says otherwise.

### Q1 — Squash or rebase the pull request?

**Taken: squash.** `mergeCommitAllowed` is false, so the real choice is squash
versus rebase. Squash matches every landing this repository has made (`main` is
linear; #35–#49 are all squashes; #9's four merges are verified as squashes), and
the per-child SHA record in §2.3 satisfies #50's "base, frozen, and merged commit"
criterion under squash. **The question:** #50's wording could be read as wanting six
distinct merged SHAs on `main`, which only rebase gives. If the operator wants that
reading, switch at merge time — it costs the plan nothing and changes no unit.

### Q2 — Which models run the two review processes, at what effort?

Every child issue recommends the **opus/high** tier band for *implementation*. The
review tier is unstated. #9 ran fourteen Saga Code Review processes on **Grok 4.6 at
xhigh** and accepted thirteen at cycle 1. **Taken:** plan for two independent
reviewers, models confirmed by live readback before briefing (runbook Phase 4), and
leave model selection to the operator at dispatch. **The question:** does the
operator want the #9 reviewer configuration repeated, or a different pairing for a
run whose risk profile is documentation staleness rather than new code?

### Q3 — When does the operator-attended assessment window open?

U5 cannot run unattended: it needs the real Grok and Agy binaries supplied by
`--real-binary`, and Cursor running against its real authenticated home. **Taken:**
the plan treats U5 as a single unit that pauses at its own step 2 until the operator
is present, rather than splitting the attended part into a seventh unit. **The
question:** does the operator want the assessment scheduled as a separate session,
and if the window slips, is U5 permitted to commit steps 6–8 (the binding tests
against the *old* documents' shape) ahead of the assessment? This plan's answer is
**no** — bindings written before the documents they bind are untested by
construction — but the operator may prefer the partial progress.

### Q4 — Should the runbook gain a resync phase structure?

`docs/runbooks/portable-plugin-port.md` v1.1.0 is written for an initial port. Its
Phase 0 says "write `ports/<package>.json`" and Phase 1 offers three parallel lanes;
neither maps to a resynchronization, and no prior standalone-resync plan exists in
`docs/plans/` to copy. **Taken:** U0 records the deviation in a table (unit U0) and the
runbook is left alone, because amending it is explicitly out of scope for #51. **The
question:** this is now the **second** resync (UniFi's fleet-core resync was the
first), so the deviation table is being written for the second time. Should a
follow-up issue be filed to add a resync phase structure at runbook v1.2.0?

### Q5 — Should the new mission-control evidence be wired into a blocking gate?

Both #55 and #56 say no new blocking gate without a separate decision, and
`scripts/check_repo.py` does not currently invoke the matrix checker at all.
**Taken:** no new gate; the new binding classes in
`tests/test_check_compatibility_matrix.py` run under the existing `unittest`
discovery, which is already a mandated gate — so the evidence *is* bound and *is*
checked, without adding a new blocking surface. **The question:** confirm that this
satisfies ruling 3's intent, or say whether a matrix-checker invocation should be
added to the repository gate as separate work.

### Q6 — Three writers on `DECISIONS.md`

The coordinator brief asks that no two units share a writable file. Issue bodies
#52, #54, and #56 each list `docs/engineering-journal/DECISIONS.md` under *Files
expected to change*, and issue bodies win. **Taken:** three strictly sequenced,
append-only writers under distinct dated anchors, which never collide because U4 —
the only unit concurrent with U3 — does not write the file (KTD7). **The question:**
confirm this is acceptable, or say whether the three entries should instead be
collected into a single journal commit at the end (which would break the
same-commit journal capture rule, hence not the default).

### Q7 — Who closes the eight consumed upstream filings?

#50 says this repin "consumes all eight upstream filings"
(`infiquetra/infiquetra-claude-plugins` #818–#822 and #828–#830), every one of which
has landed upstream. **No unit in this run closes or annotates them**, because
upstream is never touched by this work. **Taken:** leave them alone and surface the
question here. **The question:** should the operator close or comment on those eight
upstream issues once this repin lands on `main`, and should that be tracked as a
separate item rather than left implicit?

### Q8 — Fourteen commits, not six. This one needs a decision, not a preference.

**This is the only open question in this list that blocks execution.** The run
declaration says six child-scoped commits, one per unit. **Six is not reachable**, and
KTD15 proves it rather than asserting it: four committed tests and the child issues'
own clauses each force a split independently. **Amendment 4 (KTD16) raises the total
from eleven to twelve** — one commit for the descriptor reclassification the two
remaining tests need; the rule's v2 extension folds into the synchronization commit
rather than taking one of its own (§18, D9). **The branch landed fourteen**: U0's
three commits (`ab939ff` superseded, `0a19edb` the accepted re-run, `f74bb7e` the
transcript elision — `f74bb7e` is U0's frozen commit) plus the eleven-table's
remaining eleven. The decision being asked for is
unchanged in kind; only the number moved.

- A descriptor may only name a transform rule the synchronizer already registers
  (`test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements`), so
  U2 must write before U1 and run the sync after it — U2 splits.
- Registering a rule breaks a test that pins the registry to a literal five-name set
  (`test_rule_names_register_exactly_once`), and that file is U4's under #55 while #53
  forbids U2 from touching it — U4 must repair it early, and its pin edit can only come
  after the sync, so U4 splits again.
- #55 needs a green suite at U4's completion, which is only true after U5 — U4 splits a
  third time.
- #54 needs a green suite at U3's completion, but U3 is the last package-root writer so
  U5 follows it — U3 splits.
- U1's first commit is already landed and accepted at `12c889c`.

**The trade-off, stated plainly.**

| | Twelve commits (this plan) | Six commits |
|---|---|---|
| Inherited acceptance criteria | every one met at full strength | #52, #54, #55 unmet — each would need an expected-red list or a moved gate |
| What changes | the SHA record and the review binding; each split unit records more than one frozen commit | nothing — but the plan would be describing a run that cannot execute |
| Unit boundaries, ownership, issue bodies | unchanged | unchanged |
| Cost | more commits to review and record | a narrowed criterion, which cycle-2 finding D1 already rejected once |

**The recommendation is twelve.** The alternative is not "six commits"; it is six
commits plus three narrowed acceptance criteria. If the operator will not accept
twelve, the honest fallback is not fewer commits either — it is KTD15's rejected
option (f), running the ten-client assessment twice under the repository's
supersede-and-re-run evidence loop, which costs a second operator-attended session to
save one commit.

**What is actually being approved:** a deviation from a commit-count convention, with
no change to what any unit does, owns, or must prove.

### 11.2 Differences between the coordinator brief and the issue bodies

Recorded per the brief's instruction. **None changes any unit's work**, because
custody and acceptance are decided per path and per command, never by a count.

1. **The count of already-classified byte copies among the 36 changed files.** The
   brief and issue #53 both say "17 upstream byte copies". Measured this session by
   mapping every changed path against the descriptor's custody table, the breakdown
   is **15** already-classified byte copies, 5 transform outputs, 5 client byte
   copies, 1 relocated Claude manifest, 1 superseded README, 1 already-dropped path
   (`tests/test_prompt_alignment.py`), and 8 new unclassified paths — totalling 36
   (§1.3). The "17" appears to fold the relocated manifest and the superseded README
   into the byte-copy row while also listing them separately. **The load-bearing
   numbers all agree**: 36 files changed, 8 new, 0 deleted, package 64 → 71.
2. **How the refusal prints the eight unclassified paths.** Issue #52 quotes them as
   `tests/test_*.py`; the tool actually prints them prefixed,
   `plugins/mission-control/tests/test_*.py`. Cosmetic; the reproduction in §1.2 is
   the tool's real output.
3. **`removed_from_source` versus `dropped_from_source`.** The brief and ruling 2
   say "record it in `removed_from_source`". That is the key name in the *generated*
   `PROVENANCE.json`. The key U1 actually edits in `ports/mission-control.json` is
   `custody.dropped_from_source`; the sync tool renders it as `removed_from_source`
   downstream. Same instruction, two names, one edit (unit U1).
4. **"No two units share a writable file."** Superseded by the issue bodies for
   `DECISIONS.md` and `ports/mission-control.json`; both are handled as sequenced,
   disjoint-region multi-writer files (§6.2, KTD7). Raised as Q6.
5. **The root README's "three sites".** Issue #54 says three sites; measured, the
   claims sit at lines 30–31, 71–75, and 163 — three regions carrying five distinct
   claims. Consistent, noted for precision.
6. **Issue #52's line-claim count.** Issue #52's verification asks U1 to confirm
   "the three surviving line-number claims" by `grep -n`, but U1 verifies **four**
   surviving claims — `_load_intent_envelope` 5134–5140,
   `INFIQUETRA_SDLC_PATH` 136, `_open_mapping_pr` 5552, and
   `executor_profile_lint.py` 35/89 — plus the false PyYAML claim it rewrites.
   The intended correction is to say "four" and extend the grep to
   `def _open_mapping_pr`; the repository files need no change, only the issue
   text does when #52 is next touched.

---

## 12. Acceptance — the run is done when

- [ ] All six child units are closed, each recording its base, frozen, and merged commit.
- [ ] `PROVENANCE.json` prints `3b2b7083fdda8e39e213b5f4acf9f8301d60dd52 2.15.2`.
- [ ] `sync_vendor_source.py … --check` prints a match line and exits 0.
- [ ] `python3 scripts/check_repo.py` prints `Repository validation passed.`
- [ ] `python3 -m unittest discover -s tests` reports `OK`.
- [ ] `python3 -m pytest plugins/mission-control/tests -q` passes, on the floor interpreter.
- [ ] `git diff --check` produces no output.
- [ ] `check_compatibility_matrix.py <new matrix>` prints `Compatibility matrix validation passed.`
- [ ] All four superseded mission-control documents — the 2026-08-25 pair and the 2026-08-30 `-pre-fingerprint-move` pair — carry `matrix-status: superseded`, a `superseded-by` naming a current successor, and a `superseded-reason`.
- [ ] No path under `plugins/mission-control/` differs from its upstream source except the recorded transforms, proven by the `--check` round-trip.
- [ ] No graded file changed; the cycle-16 mutation proof still stands.


---

## 13. Doc-review disposition — cycle 1

**Artifact.** `docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md` (cycles 1–2; commits `b4cc17b`, `4d2cbe0`)
· **Bound revision.** `1e4da2be8dd2d1256f1e61765629ecf6a0571de9` · **Verdict.**
BLOCK · **Cycle.** 1 · **Findings.** P0: 0 · P1: 1 · P2: 0 · P3: 1.

**Outcome.** Both findings were repaired and the review returned **PROCEED** at
revision `82dcb1c`. **Section 14 below was added afterwards and is outside that
review's scope** — a reader must not treat the PROCEED verdict as covering it.

Both findings are repaired in this revision. The operator's standing rule is that
every finding is repaired, not only P0 and P1.

| id | priority | disposition | where |
|---|---|---|---|
| D1 | P1 | **Repaired** — landing order serialized: U4 commits first, U3 rebases onto it and then gates | KTD10, §5 (diagram, edge list, concurrency note), §8.1 steps 4a–4c, §2.6, U3 and U4 unit sections, R39 |
| D2 | P3 | **Repaired, and widened to the class** — U5's block gained the package pytest and floor runs, and so did U0's and U1's, which carried the same omission the reviewer did not reach | U0, U1, U5 verification blocks; §2.6 |

### D1 — the option taken, and why

**Taken: keep the concurrency, serialize the landing.** U3 and U4 still work at the
same time from the post-U2 commit — "at most two-wide" caps concurrent workers, and
never required two independent commit bases. U4 commits first. U3 then rebases onto
U4's commit, runs its gates on that integrated tree, and commits second. On that
tree the three `test_sync_vendor_source` pin constants are already repaired, so
U3's `python3 -m unittest discover -s tests` reports `OK` outright and issue #54's
acceptance criterion holds exactly as written.

**Rejected: give U3 U2's pin-constant exception and move #54's `unittest discover`
OK line to freeze integration.** The reviewer offered this as the second option and
it is the cheaper edit, but it narrows an acceptance criterion this plan inherited
rather than authored. A gate moved to a later checkpoint is a weaker gate whatever
it is called, and #54's criteria are not the plan's to weaken. Rejected on that
ground alone.

Nothing else moved. The declared graph `U0 → U1 → U2 → {U3, U4} → freeze → U5` is
unchanged, the two-worker cap is unchanged, the freeze still follows U3, file
ownership is unchanged — U3 still may not touch `tests/test_sync_vendor_source.py`
— and no child issue was edited. The change is a landing-order constraint, which is
plan-level by construction.

### D2 — repaired as a class

The reviewer filed D2 against U5. Auditing all six verification blocks against R36
showed the omission was not unique to it: **U0** omitted both the package pytest
run and the floor run, **U1** omitted the floor run, and **U5** omitted both. All
three are repaired, and §2.6 now states the uniformity explicitly so a later unit
cannot quietly ship a narrower block. R36 was not narrowed, which was the
alternative the finding allowed.

### The reviewer's five applied fixes — carried, and re-verified first-hand

The reviewer left five evidence-backed edits uncommitted in the working tree. All
five are kept, and the three load-bearing factual claims were re-verified against
the pinned upstream before being committed under this plan's name:

| Applied fix | Re-verification |
|---|---|
| U0's upstream suite named as `uv sync --locked --extra dev` then `uv run pytest` | `git -C ../infiquetra-claude-plugins show 3b2b7083:README.md` — the two commands appear at lines 78 and 81 |
| `_open_mapping_pr` added to the U1 notes-refresh table, 4664 → 5552 | `grep -n "^def _open_mapping_pr"` against the file at both pins prints `4664` and `5552` |
| The descriptor's "twenty-one upstream test files" claim corrected to twenty-eight | `git -C ../infiquetra-claude-plugins ls-tree -r --name-only 3b2b7083 plugins/mission-control/tests/` counts 30 `.py` files; two are dropped by custody, leaving 28 byte copies |
| R12 widened from three surviving line-number claims to four, and the U1 `grep` extended to match | follows from the `_open_mapping_pr` row above |
| U0's Phase 3 skip row split so the mutation-proof re-run is explicitly skipped | consistent with §2.8 and KTD11; the five graded files are untouched by this run |


---

## 14. Amendment 1 — the `sync_template_docs.py` package-root blocker (post-review)

**Status: this section postdates the accepted Document Review; it was reviewed by
doc-review cycle 3 (commit `8cd5fec`), all four of its findings were repaired in
commit `4083220`, and cycle 7 (commit `6166b26`) closed the residual findings of the
later amendments.** The review
examined revision `82dcb1c` and returned PROCEED. Everything in this section, and
the changes it points at elsewhere in the plan, were written after that verdict and
were **not covered by it**; the cycles above are the ones that covered them.

**What it is.** A coordinator decision taken under the run contract's *recorded
custody decision* clause. Section 2.7 names two legitimate resolutions when a
carried file cannot work unchanged in the portable layout — an upstream filing, or a
recorded custody decision. The coordinator chose the second and directed that it be
recorded in the plan before any worker implements it. This planner recorded the
decision; it did not make it, and it has not written the transform rule.

**When it surfaced.** During U2, after U0 and U1 had landed (`12c889c`). The
accepted plan did not anticipate it: the plan's own §1.3 asserted that all four
transform premises held at the new pin and that the seventeen changed byte copies
would regenerate cleanly. That assertion was true of the four *existing* rules. It
was silent about a byte copy that upstream had made unimportable, because nothing in
the pre-run analysis imported the carried files.

**What changed in this plan.**

| Change | Where |
|---|---|
| The custody decision, with its rejected alternatives and revisit condition | **KTD14** |
| Two new verifiable requirements for the reclassification and its determinism | **R40**, **R41** |
| A sixth U2 deliverable, its test scenarios, and three new U2 stop conditions | **U2** |
| `ports/mission-control.json` gained a third sequenced writer, U2 — ***reverted by Amendment 2***, which returned that edit to U1 so the descriptor again has the two writers #50 records | **§6.2**, §15.1 |
| `tests/test_sync_vendor_source.py` became a two-writer file, U2 then U4 — ***reverted by Amendment 2***, which returned the rule coverage to U4 as sole writer | **§6.1**, §15 |
| `scripts/sync_vendor_source.py` becomes a U2-owned file | **§6.1** (moved out of §6.3, with the reason recorded there) |

**What did not change.** The pin. The four operator rulings. The dependency graph
`U0 → U1 → U2 → {U3, U4} → freeze → U5`. The two-worker cap and the U4-then-U3
landing order (KTD10). The freeze point after U3. The five graded files, all still
untouched — `scripts/sync_vendor_source.py` is not among them, which is why this
path is open at all. No child issue was edited. No unit was added or removed.

### 14.1 One observation this amendment does not resolve

While reproducing the blocker, one further repository-suite failure appeared that is
**not** caused by it and is **not** part of the coordinator's decision:

```
FAIL: test_check_compatibility_matrix.LiveDocumentTest
      .test_the_no_argument_run_validates_every_committed_matrix
```

`scripts/check_compatibility_matrix.py` with no arguments validates **every**
committed matrix document, and the committed mission-control matrix records the old
fingerprint — 64 files, tree `651ac28a…` — which the resynchronized package no
longer matches. So the retirement this plan predicted (§1.2, risk 3) does surface in
the suite after all, one gate earlier than the plan expected.

This corrects a claim made earlier in this plan's reasoning: the plan assumed the
mission-control matrix was bound by nothing and that the gates would stay green
between U2 and U5. The binding is indirect — through UniFi's `LiveDocumentTest`
calling the no-argument entrypoint — but it is real.

**Resolved by Amendment 2 (§15).** When Amendment 1 recorded this it left the
coordinator call open, and doc-review finding D4 was right that leaving it open made
#54's and #55's inherited `unittest discover` criteria unreachable. **KTD15 takes the
call**: U5 remains the unit that clears this test, and U1, U3, and U4 each complete in
two commits so that every unit's criterion is met at its completion, at full strength.
Nothing is narrowed and no issue is edited.

Open question **Q5** should still be read with this in mind: the evidence was already
more bound than that question assumed — not by a mission-control-specific test, but by
a UniFi-scoped class calling the checker's no-argument entrypoint, which validates
every committed matrix.


---

## 15. Amendment 2 — doc-review cycle 3 repair (post-review)

**Artifact.** `docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md` (cycle 3; commit `8cd5fec`)
· **Bound revision.** `b164026` · **Verdict.** BLOCK · **Cycle.** 3 ·
**Findings.** P0: 0 · P1: 1 (D4) · P2: 1 (D5) · P3: 2 (D6, D7).

Cycle 3 judged Amendment 1 only; cycle 2's PROCEED on the pre-amendment plan is not
re-opened. All four findings are repaired here, per the standing rule that every
finding is repaired, not only P0 and P1. The reviewer's four cycle-3 safe fixes landed
at `8cd5fec` and are preserved unchanged — in particular the match-unit paragraph, and
the trap it names: the pin file has **two** `.claude-plugin` sites, the `Path` check at
line 20 and the concatenated string in the error text at line 23, so a substring
replace fixes only the error message and leaves the walk broken.

| id | priority | disposition | where |
|---|---|---|---|
| D4 | P1 | Repaired for #54/#55/#56 — the three-way gate cycle is broken by completing those units after U5. ***Reopened by cycle 4 for #52 and corrected in Amendment 3 (§16)***: U1b named an unregistered rule, and the commit counts below are superseded by KTD15's eleven | **KTD15**, §5, §8.1, U1, U3, U4, R43, §16 |
| D5 | P2 | **Repaired** — the amendment's work is re-assigned to the units that already own each file, so #53's out-of-scope holds as written | KTD14 ownership table, §6.1, §6.2, U1, U2, U4, R40, R42 |
| D6 | P3 | **Repaired** — the descriptor is back to the two writers #50's shaping records; the one addition to #50's file inventory is named for the operator | §6.2, §15.1 |
| D7 | P3 | **Repaired** — the dummy `.claude-plugin/` hack is now KTD14's fourth rejected alternative, with four reasons it is wrong | KTD14 |

### 15.1 D6 — the two claims in #50's shaping that Amendment 1 outran

Issue #50's Intent section says `ports/mission-control.json` "has exactly two writers
in sequence, U1 then U3", and its *Files expected to change* list does not include
`scripts/sync_vendor_source.py`. Amendment 1 contradicted the first and silently
extended the second.

**The first is now true again.** Amendment 2 returns the descriptor edit to U1, so the
descriptor has exactly two writers, U1 then U3, precisely as #50 records. U1 simply
writes twice — its first commit is already landed and accepted at `12c889c`, and the
reclassification is a second commit against the same unit.

**The second is a real addition to #50's inventory that this plan cannot fix.**
`scripts/sync_vendor_source.py` is now written by U2, and it is not in #50's *Files
expected to change* list. Issues are not edited by this run, so it is recorded here
instead: **#50's file inventory is one path short, and the operator may want to add it
when the parent issue is next touched.** Nothing else in #50 is affected — no
acceptance checkbox, no ruling, no stop condition.

### 15.2 What did not change

The pin. The four operator rulings. The work graph `U0 → U1 → U2 → {U3, U4} → freeze →
U5`. The two-worker concurrency cap. The freeze after U3's package-root edits. The five
graded files, all still untouched. The single ten-client assessment, run once against
the frozen package. No child issue was edited, no acceptance criterion was narrowed,
and no unit was added or removed — some units simply land in more than one commit.
Amendment 3 (§16) later corrected the sequence and the counts.


---

## 16. Amendment 3 — doc-review cycle 4 repair (post-review)

**Artifact.** `docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md` (cycle 4; commit `ef0dfa0`)
· **Bound revision.** `4083220` · **Verdict.** BLOCK · **Cycle.** 4 ·
**Findings.** D5, D6, D7 closed. D4 still open (P1). D8 raised (P2).

| id | priority | disposition | where |
|---|---|---|---|
| D4 | P1 | **Repaired** — the inverted prerequisite is corrected, and a second one the review did not reach is corrected with it | **KTD15**, §5, §8.1, §2.6, R39, R43, R44, U1, U2, U4 |
| D8 | P2 | **Escalated, not absorbed** — eleven commits is recorded as a material deviation with a proof and a trade-off, as operator question **Q8** | §2.3, §8.1, §8.2, **Q8** |

### 16.1 D4 — the cause, and the one the review missed

The review found that U1b named a transform rule U2 had not registered, so
`tests/test_port_config.py::CommittedDescriptorTest.test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements`
failed and #52's `unittest discover` `OK` was unmet at U1's completion. That is
correct, and Amendment 2's claim that the reclassification "changes no behaviour on
its own" was simply wrong.

Correcting it surfaced a **second** prerequisite in the same area that neither
Amendment 2 nor the review reached:
`tests/test_sync_vendor_source.py::MissionShapedSyncTests.test_rule_names_register_exactly_once`
(lines 919–931) asserts `set(svs.TRANSFORM_RULES)` equals a literal five-element set.
Registering a sixth rule fails it — and that file belongs to U4 under #55, while #53
forbids U2 from editing downstream tests. So the rule's registration and its registry
test are two units' work and cannot share a commit.

Both are now sequenced: **U2a registers, U4a repairs the registry set, U1b names it,
U2b syncs** (KTD15, R44).

The three leftovers the review flagged — §2.6's "U3 rebases onto U4's commit … green
outright", R39, and the §5 ASCII "gates, lands 2nd / green" — measured #54 at the
U4→U3 rebase rather than at U3b. All three are corrected.

### 16.2 D8 — six commits was attempted and is impossible

A six-commit solution was searched for before the deviation was recorded, as the
operator asked. It does not exist, for the reasons in KTD15's proof — four committed
tests and the issue clauses each force a split independently, and none of them is a
plan choice. The minimum is **eleven** (ten in a counterfactual where U1's first
commit had not already landed). That is escalated once, cleanly, as **Q8**, with the
trade-off table and a recommendation. This plan does not present eleven as a
compatible reading of six.

### 16.3 What did not change

The pin. The four operator rulings. The work graph. The two-worker concurrency cap.
The freeze after U3's package-root edits. The five graded files. The single ten-client
assessment. Unit boundaries, file ownership, and every inherited acceptance criterion.
No child issue was edited, and `plugins/mission-control/` was not touched.


---

## 17. Amendment 4 — the two remaining package-root tests (post-review)

**Status: this amendment postdates doc-review cycle 5's PROCEED; it was reviewed by
doc-review cycle 6 (commit `384e52a`, blocked: false) and its findings D9 and D10
were closed by cycle 7 (commit `6166b26`).** A reader must not
treat the cycle-5 PROCEED as covering KTD16, the twelve-commit sequence, or R45 and R46;
the later cycles do.

**What it is.** An operator decision, recorded here by the planner. The coordinator
verified the blocker first-hand at pin `3b2b7083`, scanned every `.py` file in the
pinned package for the pattern, chose option (a) over (b) and (c), and directed that
it be recorded before any worker implements it. **No rule was written here**, and
`plugins/mission-control/` was not touched — the 34 uncommitted paths there are the
preserved U2 synchronization.

**Where it lands.**

| Change | Where |
|---|---|
| The decision, the scan, the cost, the replacement discipline, and the rejected alternatives | **KTD16** |
| Two new verifiable requirements | **R45**, **R46** |
| Descriptor gains a third U1 commit; the rule extension is U2's; coverage is U4's | §6.1, §6.2, §5, §8.1 |
| Commit total moves eleven → twelve (corrected from thirteen by Amendment 5) | §2.3, §8.1, §8.2, **Q8**, §18 |

### 17.1 The 71-file count is unchanged, so #53 line 129 still holds

**Confirmed.** Option (a) reclassifies two files; it does not remove them. Both stay
in the package, so `git ls-files plugins/mission-control | wc -l` still prints `71`
and #53's acceptance checkbox — "The package holds 71 files" — holds at full strength.
Verified against the working tree: `PROVENANCE.json` records **70** file entries plus
the manifest itself. What moves is custody class only: byte copies **48 → 46**,
entrypoint transforms **10 → 12**, dropped paths unchanged at **3**.

Option (b) is the one that would have broken it, at 69 files. That is the first of the
two grounds on which it was rejected.

### 17.2 Ownership, unchanged in principle

Each part goes to the unit that already owns the file, exactly as Amendment 2
established:

| Part | Unit | Commit |
|---|---|---|
| Extend the rule, bump its version | **U2** (#53) | folded into U2b, ahead of the sync run (§18, D9) |
| Reclassify both tests in the descriptor | **U1** (#52) | U1c — a **third** commit against a unit whose first two have landed |
| Cover the new assertion-rewriting sites | **U4** (#55) | folded into U4b, which already carries the rule's coverage |

No issue was edited, no unit boundary moved, and no acceptance criterion was narrowed.


---

## 18. Amendment 5 — doc-review cycle 6 repair

**Artifact.** `docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md` (cycle 6; commit `384e52a`; cycle 7 confirmation `6166b26`)
· **Bound revision.** `02c8bed` · **Verdict.** PROCEED · **Cycle.** 6 ·
**Findings.** P0: 0 · P1: 0 · P2: 2 (D9, D10).

The verdict was PROCEED, so neither finding blocked. Both are repaired anyway, under
the standing rule that every finding is repaired, not only P0 and P1.

| id | priority | disposition | where |
|---|---|---|---|
| D9 | P2 | **Adopted** — thirteen was an avoidable preference; the run lands **twelve** | KTD16 commit-shape section, KTD15 table, §2.3, §5, §8.1, §8.2, §17, **Q8** |
| D10 | P2 | **Withdrawn** — the cited constraint does not exist; the caveat is removed rather than re-pointed | §5 edge list |

### 18.1 D9 — twelve, and the code fact that decides it

The reviewer's reasoning was re-verified first-hand rather than accepted:

- `scripts/sync_vendor_source.py:102` defines
  `PACKAGE_ROOT_MARKER_TRANSFORM_NAME = "resolve-package-root-marker"`, registered in
  the rule registry at line 855, and `tests/test_sync_vendor_source.py:930` already
  carries it in the pinned expected set. The **name** has been registered since U2a.
- The descriptor join asserts `self.assertIn(rule, svs.TRANSFORM_RULES)`
  (`tests/test_port_config.py` 569–575). It joins **names**. No version appears in it.

So U1c may name the rule for two more paths while the rule is still on v1. The only
real ordering requirement is that v2 exist when the synchronization runs, because v1's
exactly-one-definition-plus-one-call shape would refuse `tests/test_template_sync.py`.
Extension and sync are the same unit acting on the same file, so they are one commit.

**Thirteen was an avoidable preference, not a forced split.** The plan now says
twelve, and Q8's operator decision is unchanged in kind — only the number moved.

### 18.2 D10 — a false constraint, removed

§5 previously cited
`CommittedDescriptorTest.test_the_custody_table_accounts_for_every_shipped_managed_path`
as forcing U1c to gate on a working tree where the transform had already been re-run,
and raised an operator-visible caveat about clean checkouts on that basis.

**The citation was wrong.** That method reads `self.config`, and the class's `setUp` is
`self.config = port_config.load("unifi", ROOT)` (`tests/test_port_config.py` 470–471);
its docstring calls the UniFi descriptor "the regression fixture for all of this." A
mission-control reclassification cannot fail it.

Searching for the test that *would* constrain U1c found none: no committed test joins
mission-control's descriptor custody to its shipped `PROVENANCE.json`, and
`scripts/check_repo.py` validates a manifest entry's own classification rather than
comparing it against the descriptor. **U1c is green on a clean checkout.** The caveat
is withdrawn rather than re-pointed at some other test, because there is no other test
to point it at.

The general lesson, recorded in the journal: a join test constrains exactly what it
joins. Reading "there is a join here" as "therefore this ordering is forced" invented
a prerequisite twice in this run — once in the right direction (KTD15's real name
join) and once in the wrong one (this caveat). Check the fixture scope and the joined
fields before deriving an edge from a test.

### 18.3 What did not change

The operator decision itself (option (a), KTD16). The 71-file count. The rule's
replacement discipline — exact per-file site counts, loud refusal, idempotence,
source-bytes-only reproducibility. Ownership: the descriptor is U1's, the rule is
U2's, the coverage is U4's. The pin, the rulings, the work graph, the freeze point,
the single assessment. No issue was edited and `plugins/mission-control/` was not
touched.

---

## 19. Amendment 6 — the freeze moved once, and the record says so (post-repair)

**Status: added by the integrated code-review repair rounds (cycles 2–3).**

The §5 freeze record claimed `55a6511` was the last point at which any byte
under `plugins/mission-control/` changes. That held until the repair rounds:
`a1e84e0` landed the F18/F11/F35 provenance and README corrections, moving the
tree from `1f49322e…` to `659f91f6…` after the freeze. Rather than renumbering
the bound evidence — the explicit anti-pattern — the assessment was re-run
(run-002, 2026-08-30) and the evidence re-bound at `863af58`, which is issue
#56's frozen commit. The three freeze claims in this plan (§5, U3's section,
the §8.1 table) are qualified to point at this amendment. The batch-the-repairs
rule applies: the three corrections landed in one round, one assessment re-run,
one new fingerprint.
