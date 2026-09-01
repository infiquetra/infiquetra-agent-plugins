---
title: U4 — Downstream pin repair and full-suite re-green
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: medium
handoff_maturity: requirements-ready
approval_state: approved
---

# U4 — Downstream pin repair and full-suite re-green

### Objective

Repair the downstream test constants that name the old pin, and bring the full
repository suite back to green on the resynchronized package.

Three constants in `tests/test_sync_vendor_source.py` are hardcoded on purpose. The
file's own comment says moving the pin "is a deliberate act that has to change a
test, not a silent drift." This unit performs that deliberate act.

### Intent

**The three pins, and why the test class is quiet until U2 lands.**
`MISSION_CONTROL_PIN` holds `84eaf042f0e350005f7eddf8e7d80da25c12119d` and is
asserted against `PROVENANCE.json`'s `source_commit`. A sibling assertion pins
`source_version` to `2.12.2`. `MISSION_CONTROL_SKILLS` holds the seven skill names
and drives the frontmatter checks. The whole class is guarded on
`plugins/mission-control/PROVENANCE.json` existing, so it stays silent on an
in-progress branch and only fires once the synchronization has landed.

**The skill tuple deserves a second look, not just a copy.** A removed skill fails
loudly with a missing file; an added skill would simply go unchecked. The roster is
unchanged at 2.15.2 — still `board`, `flow`, `issues`, `labels`, `metrics`,
`milestones`, `rollout` — so this is a confirmation, not an edit. Confirm it rather
than assuming it.

**This unit is fingerprint-neutral.** It touches only `tests/` and, if needed,
`ports/`, both outside `plugins/mission-control/`. That is what lets it run in
parallel with U3 without disturbing the freeze that follows.

**Re-green means all four mandated gates**, not just the one that broke:
`scripts/check_repo.py`, the full `unittest` discovery over `tests/`, the package
suite under `pytest` on the floor interpreter, and `git diff --check`. The baseline
before this work was 773 tests passing; the new baseline should be that number plus
whatever U3 added, with no regressions.

### Out-of-scope / non-goals

- No change to anything under `plugins/mission-control/`. Doing so would move the fingerprint after U3 and invalidate the freeze.
- No change to the mutating-verb constants; those belong to U3's locked commit.
- No evidence documents; U5 owns those.
- No new gate wired into continuous integration. Adding one is separate work.

### Inputs inventory

- `tests/test_sync_vendor_source.py` — `MISSION_CONTROL_PIN`, `MISSION_CONTROL_SKILLS`, and the `source_version` assertion.
- The resynchronized `PROVENANCE.json` as U2 left it.
- Baseline before this run: 773 tests passing, repository gate green.
- `.github/workflows/ci.yml` — the ported-plugin job that installs `requests urllib3 pyyaml pytest` and runs `pytest plugins/*/tests -q`.

### Files expected to change

- `tests/test_sync_vendor_source.py`

### Tests to add or update

- `tests/test_sync_vendor_source.py`: update `MISSION_CONTROL_PIN` to `3b2b7083...`, update the `source_version` assertion to `2.15.2`, and confirm `MISSION_CONTROL_SKILLS` still matches the shipped roster.
- No new test file. Any other suite failure this unit uncovers is triaged, not patched over — see Stop conditions.

### Failure modes / pre-mortem

**Most likely: a failure is made to pass instead of understood.** The pin constants
are meant to change; anything else that fails is information. A second failure that
gets a constant bumped alongside the pin hides a real drift.

**Second: PyYAML is dropped from continuous integration on a misreading of upstream
filing #828.** That filing deferred only `sdlc_manager.py`'s import.
`plugins/mission-control/scripts/sync_template_docs.py:14` and
`plugins/mission-control/tests/test_template_sync.py:7` still import `yaml` at
module scope, and `sync_template_docs.py`'s import block is byte-identical between
the two pins. The install line stays.

**Third: an edit strays inside the package root** and silently invalidates the
freeze that U5's assessment depends on.

### Stop conditions

| Condition | Action |
|---|---|
| A suite failure that is not one of the three known pin constants | Stop and triage. Report what drifted before changing anything. |
| A fix would require editing a file under `plugins/mission-control/` | Stop. That is either an upstream filing or a defect in U2's custody, never a downstream patch here. |
| The skill roster differs from the seven recorded names | Stop. A roster change is a custody question, not a constant bump. |
| A resync-forced edit to any of the five mutation-proof graded files | Stop and escalate. |

### Context library links

- `docs/engineering-journal/QUEUED.md` — the recorded resync policy
- `docs/runbooks/portable-plugin-port.md` — Phase 3 gates

### Acceptance criteria

- [ ] `MISSION_CONTROL_PIN` in `tests/test_sync_vendor_source.py` equals the new pin, and the `source_version` assertion reads `2.15.2`.
- [ ] `MISSION_CONTROL_SKILLS` is confirmed to match the shipped roster, proven by `ls plugins/mission-control/skills` listing exactly the seven recorded names.
- [ ] `python3 -m unittest tests.test_sync_vendor_source -v` reports `OK`.
- [ ] `python3 scripts/check_repo.py` prints `Repository validation passed.`
- [ ] `python3 -m unittest discover -s tests` reports `OK` with no failures or errors.
- [ ] `python3 -m pytest plugins/mission-control/tests -q` passes on the floor interpreter.
- [ ] `git diff --check` produces no output.
- [ ] No file under `plugins/mission-control/` changed in this unit, proven by `git diff --name-only <base>..HEAD -- plugins/mission-control | wc -l` printing `0`.

### Verification

```bash
# The deliberate pin change
python3 -m unittest tests.test_sync_vendor_source -v

# Skill roster confirmation
ls plugins/mission-control/skills

# All four mandated gates
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/mission-control/tests -q
git diff --check

# Prove this unit is fingerprint-neutral
git diff --name-only <base>..HEAD -- plugins/mission-control | wc -l
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

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/55
- Number: 55
- Created at: 2026-08-30T19:24:21.798078+00:00

