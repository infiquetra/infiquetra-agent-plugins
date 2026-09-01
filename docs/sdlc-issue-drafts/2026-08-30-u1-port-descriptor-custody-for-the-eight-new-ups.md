---
title: U1 — Port descriptor: custody for the eight new upstream paths and the provenance-notes refresh
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

# U1 — Port descriptor: custody for the eight new upstream paths and the provenance-notes refresh

### Objective

Assign custody to every upstream path the 2.15.2 revision adds, and refresh the
descriptor prose that the synchronization tool copies verbatim into the generated
provenance manifest.

This unit is blocking. `scripts/sync_vendor_source.py --check` against the new pin
refuses today with exactly one error and stops there:

> `ERROR: upstream paths carry no custody assignment, so synchronization would drop them in silence: tests/test_card_validator_agreement.py, tests/test_lifecycle_field_boards.py, tests/test_lifecycle_field_identity.py, tests/test_lifecycle_field_mutation.py, tests/test_lifecycle_field_routing.py, tests/test_lifecycle_writer_census.py, tests/test_option_identity.py, tests/test_sdlc_manager_optional_deps.py`

It refuses **before** it can enumerate any other drift, so nothing else about this
resynchronization can be measured until this unit lands.

### Intent

**Seven of the eight new tests are byte copies.** Each was verified self-contained:
no fixed repository-depth assumption, no external checkout, no marketplace or
sibling-plugin premise, no network call, no credentials. Each patches `_graphql` at
the `sdlc_manager` module level so no live GitHub call can occur, and reaches only
in-package paths. `tests/test_sdlc_manager_optional_deps.py` spawns a subprocess,
but it is the test's own interpreter (`sys.executable`) running inline code with
`sys.modules['yaml']` forced to `None` — package-internal and hermetic.

**The eighth is excluded by operator ruling 2.**
`tests/test_card_validator_agreement.py` is recorded in `removed_from_source`, with
the upstream test preserved where it belongs. It loads an authority module from
outside any repository — searching `HOME_LAB_PATH`, then
`INFIQUETRA_HOME_LAB_PATH`, then `~/workspace/infiquetra/home-lab`, then
`~/workspace/home-lab`, then sibling directories — and skips loudly when absent.
Its own docstring states this repository's continuous integration never exercises
it. Carrying it would make a test's verdict depend on what else happens to be on
the machine's disk, which is the defect class `QUEUED.md` already names about the
link checker: a gate that reports the environment rather than the repository. The
recorded `test_prompt_alignment.py` drop rejected "carrying it and skipping at
runtime" as deadweight that misrepresents its own coverage; this is the same call.

**Re-verify the `test_prompt_alignment.py` drop at the new pin and record the
result.** Its premises still fail: the upstream file at `3b2b7083` still requires a
sibling `plugins/saga/skills/handoff/SKILL.md`, which this catalog does not host,
and still reads a root marketplace manifest to cross-check a Mission Control entry
this catalog's manifest does not carry. The drop holds. Record the re-verification
rather than leaving it implied.

**Refresh the `provenance.notes` prose in the same commit.**
`scripts/sync_vendor_source.py` copies those notes verbatim into `PROVENANCE.json`
(`"notes": list(config.notes)`), so stale prose produces a generated file whose
header reads `source_version: 2.15.2` while its own notes paragraph says 2.12.2,
and nothing catches that. Four line-number claims move, and one becomes false:

| Claim in the notes | State at 2.15.2 |
|---|---|
| `executor_profile_lint.py` module-scope import at line 35, `tier_palette` at line 89 | still correct; the file is unchanged |
| `sdlc_manager.py` `_load_intent_envelope` at lines 4283-4287 | moved to 5134-5140 |
| `sdlc_manager.py` reads `INFIQUETRA_SDLC_PATH` at line 135 | moved to 136 |
| `sdlc_manager.py` needs PyYAML at module scope, line 83 | **false** — upstream #828 moved the import into a function at line 3436 |

Note that PyYAML remains required regardless: `scripts/sync_template_docs.py:14`
and `tests/test_template_sync.py:7` still import it at module scope, so the
continuous-integration install line stays. Only the justification changes.

### Out-of-scope / non-goals

- No synchronization run. This unit changes the descriptor only; U2 runs the sync.
- No change to the `assessment.mutating_operations` block. That is U3's, together with the README and test constants it is locked to.
- No change to anything under `plugins/mission-control/`.
- No schema change to the descriptor format. Adding entries to existing arrays needs none. See Stop conditions.

### Inputs inventory

- `ports/mission-control.json` — the current descriptor: 42 byte copies, 9 entrypoint transforms, 5 client byte copies, 1 superseded path, 2 dropped paths.
- Upstream at `3b2b7083`, read-only, proven green by U0.
- `docs/engineering-journal/DECISIONS.md` — the `test_prompt_alignment.py` drop and its premise table.
- The eight new upstream test paths named in the refusal above.

### Files expected to change

- `ports/mission-control.json`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `tests/test_port_config.py` if and only if the descriptor's shape changes; on the verified analysis it does not, because every edit adds entries to arrays that already exist.
- No new test is required by this unit itself. The gate is the synchronization tool's own refusal changing verdict.

### Failure modes / pre-mortem

**Most likely: the notes are left stale.** The custody edit is the visible work and
the prose is easy to skip. The result is a self-contradicting generated manifest
that no check catches. Treat the notes refresh as a deliverable of equal standing,
not a tidy-up.

**Second: a custody class is chosen to make the tool stop complaining.** The tool
refuses on *unclassified*, not on *wrongly classified*. Classifying the agreement
test as a byte copy would silence the error and ship the defect. The ruling is
explicit; follow it.

**Third: the descriptor edit forces a change to `scripts/port_config.py`.** If it
does, the scope assumption is wrong — see Stop conditions.

### Stop conditions

| Condition | Action |
|---|---|
| The descriptor edit requires a change to `scripts/port_config.py` | Stop and escalate. `port_config.py` is in the cycle-16 mutation proof's graded set; touching it retires that proof and forces a separate re-run. Adding array entries should need no schema change. |
| `--check` still refuses after custody is complete, for a reason other than unclassified paths | Stop and report the new refusal rather than widening the unit. |
| A new upstream path appears that fits none of the existing custody classes | Stop. A new class is a recorded decision, not an inline choice. |
| Any upstream edit is required to make custody work | Upstream filing, never a downstream patch. |

### Context library links

- `docs/engineering-journal/DECISIONS.md` — custody decisions and the drop precedent
- `docs/engineering-journal/QUEUED.md` — the recorded resync policy
- `ports/README.md` — port descriptor contract

### Acceptance criteria

- [ ] The seven hermetic new tests are classified `upstream-byte-copy` in `ports/mission-control.json`.
- [ ] `tests/test_card_validator_agreement.py` is recorded in the descriptor's dropped-from-source custody with a stated reason.
- [ ] `python3 scripts/sync_vendor_source.py --package mission-control --source <upstream> --commit 3b2b7083 --check` no longer refuses for unclassified paths and instead reports real content drift.
- [ ] The `provenance.notes` prose names pin `3b2b7083` and version `2.15.2`, and no longer claims PyYAML is imported at module scope in `sdlc_manager.py`.
- [ ] The three surviving line-number claims are correct at the new pin, verified by `grep -n` against the upstream file.
- [ ] `python3 scripts/check_repo.py` prints `Repository validation passed.`
- [ ] `python3 -m unittest discover -s tests` reports `OK`.
- [ ] A `DECISIONS.md` entry records the agreement-test exclusion and the re-verified `test_prompt_alignment.py` drop, each with rejected alternatives and a revisit condition.

### Verification

```bash
# The blocking gate: the refusal must change shape
python3 scripts/sync_vendor_source.py --package mission-control \
  --source ../infiquetra-claude-plugins --commit 3b2b7083 --check

# The three surviving line-number claims, checked against the pinned source
git -C ../infiquetra-claude-plugins show 3b2b7083:plugins/mission-control/scripts/executor_profile_lint.py | grep -n "import fleet_commons_shim\|tier_palette"
git -C ../infiquetra-claude-plugins show 3b2b7083:plugins/mission-control/scripts/sdlc_manager.py | grep -n "import fleet_commons_shim\|INFIQUETRA_SDLC_PATH\|import yaml"

# Repository gate and suite
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
git diff --check
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

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/52
- Number: 52
- Created at: 2026-08-30T19:23:31.919935+00:00

