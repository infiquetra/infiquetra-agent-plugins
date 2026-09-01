---
title: U3 — Target-owned surface, mutating-verb reclassification, and the create-option read-only guard
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

# U3 — Target-owned surface, mutating-verb reclassification, and the create-option read-only guard

### Objective

Update every hand-authored file that states an upstream fact about the Mission
Control package, correct the audited mutating-verb table under operator ruling 4,
and — where a fact can be derived instead of retyped — derive it, so this class of
staleness stops recurring.

This is the last unit that touches bytes inside `plugins/mission-control/`, so the
package fingerprint is final when it lands. The freeze follows this unit.

### Intent

**Four files are locked together and must move in one commit.**
`tests/test_mission_control_readme.py` asserts that the descriptor's audited
mutating-verb set equals the test's own constant — its failure message reads
"the port descriptor's audited mutating-verb table moved; update `MUTATING_VERBS`
deliberately, never silently" — and then that every audited verb appears in the
portable README. A third test refuses any fenced README command that invokes a
mutating verb. So `ports/mission-control.json`, `plugins/mission-control/README.md`,
and the two constants in `tests/test_mission_control_readme.py` move together or
the suite goes red.

**Three verb-table changes, all verified against the pinned source.**

| Change | Evidence |
|---|---|
| Add `set-options` to the mutating set | New at 2.14.0. Its handler `fields_set_options()` calls `update_field_single_select_options`, which issues a real mutation unless `--dry-run` is passed. Operator ruling 4 keeps it mutating and protected. |
| Move `create-option` to the read-only set | Its implementation only discovers a field and prints its existing options. The upstream docstring at the new pin states "This command performs NO mutation — it never has." It was mis-declared from the original port, not changed since. Operator ruling 4 reclassifies it. |
| Drop `update` from the `rollout` read-only row in the README | Removed upstream by filing #821 as dead code whose help text falsely claimed to write `beads-config.json`. |

**Operator ruling 4 requires a focused guard.** Reclassifying a verb from mutating
to read-only narrows a safety declaration, and a narrowed safety claim needs
positive proof rather than a changed constant. Add a test proving `fields
create-option` invokes no write operation — asserting the destructive mutation
constants are never reached on that path, in the style the new upstream
`tests/test_option_identity.py` already uses for its own error paths.

**Five unbound version and count claims across three target-owned files.** None is
checked by any test today:

- `plugins/mission-control/plugin.json` — `"version": "2.12.2"` and a description reading "derived from infiquetra-claude-plugins at the 2.12.2 revision".
- `plugins/mission-control/README.md:12` — "upstream plugin version 2.12.2".
- Root `README.md` at three sites — a 64-file count, a 266-test count, a twenty-one-test-file count, and a Packages-table row reading `84eaf042` (v2.12.2).

**Close the class, not the instance.** The #9 run's single review finding was
exactly this shape: U9's Packages table pinned UniFi at the wrong revision because
the row was hand-authored with no derivation and no pin test. Retyping these five
claims reproduces the defect one release later. Add a derivation test binding
`plugins/mission-control/plugin.json`'s version to `PROVENANCE.json`'s
`source_version`, on the pattern already shipped for agent-launcher in
`tests/test_agent_launcher_packaging.py`, and pin the root README's Packages row
the same way.

### Out-of-scope / non-goals

- No change to any byte copy or transform output. U2 owns those.
- No change to `ports/mission-control.json` custody or `provenance.notes`. U1 owns those; this unit touches only the `assessment.mutating_operations` array.
- No change to `scripts/check_compatibility_matrix.py` or any other mutation-proof graded file.
- No evidence documents. U5 owns those.

### Inputs inventory

- The resynchronized package as U2 left it: 71 files, pin `3b2b7083`, version 2.15.2.
- `ports/mission-control.json` `assessment.mutating_operations`, currently 25 entries including the mis-declared `create-option`.
- `tests/test_mission_control_readme.py` — `MUTATING_VERBS`, `READ_ONLY_VERBS`, and the three tests that lock them.
- `tests/test_agent_launcher_packaging.py` — the version-derivation pattern to copy.
- Upstream at `3b2b7083` for the verb roster and the `create-option` docstring.

### Files expected to change

- `ports/mission-control.json`
- `plugins/mission-control/plugin.json`
- `plugins/mission-control/README.md`
- `README.md`
- `tests/test_mission_control_readme.py`
- `tests/test_mission_control_rule_audit.py`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- A focused guard proving `fields create-option` invokes no write operation (operator ruling 4).
- A derivation test binding `plugins/mission-control/plugin.json`'s version to `PROVENANCE.json`'s `source_version`.
- A pin test for the root README's Mission Control Packages-table row, so a stale revision fails rather than sits.
- Updated `MUTATING_VERBS` and `READ_ONLY_VERBS` in `tests/test_mission_control_readme.py`.

### Failure modes / pre-mortem

**Most likely: the counts are retyped and go stale again next release.** The file
count moves 64 to 71 and the test counts move with it. Typing the new numbers
satisfies today's reader and reproduces the #9 finding. Derive or pin them.

**Second: the verb table is changed in one file and not the others.** The lock test
catches the descriptor-versus-constant half, but the README disclosure half fails
separately. Change all four in one commit.

**Third: the `create-option` guard proves the wrong thing.** A test that asserts the
function returns without error proves nothing about writes. It must assert the
mutation path is never reached.

**Fourth: an edit lands inside `plugins/mission-control/` after the freeze.** This
unit is the last one permitted to touch the package root. Anything later invalidates
the assessment U5 runs.

### Stop conditions

| Condition | Action |
|---|---|
| A verb's mutating status cannot be settled by reading its implementation | Stop. Over-declaring is the safe direction; do not narrow a safety claim on inference. |
| The lock test's failure message fires and the fix is to loosen the assertion | Stop. The lock is the control, not the obstacle. |
| A resync-forced edit to any of the five mutation-proof graded files | Stop and escalate. |
| Deriving a count requires a change to `scripts/check_repo.py` | Stop and escalate; it is a graded file. |

### Context library links

- `docs/retros/issue-9-2026-08-25.md` — lesson R3, hand-authored identity rows
- `docs/engineering-journal/DECISIONS.md` — the target-owned README decision

### Acceptance criteria

- [ ] `assessment.mutating_operations` in `ports/mission-control.json` contains `set-options` and does not contain `create-option`.
- [ ] The portable README's per-skill verb table lists `set-options` as mutating for `fields`, lists `create-option` as read-only, and no longer lists `update` under `rollout`.
- [ ] `python3 -m unittest tests.test_mission_control_readme -v` reports `OK`, proving the descriptor, README, and test constants agree.
- [ ] A guard test proves `fields create-option` invokes no write operation and fails if a mutation constant is reached.
- [ ] `plugins/mission-control/plugin.json` reports version `2.15.2`, and a test binds it to `PROVENANCE.json`'s `source_version` so the two cannot diverge.
- [ ] The root `README.md` states the new pin, version, file count, and test counts, with the Packages-table row pinned by a test.
- [ ] `python3 scripts/check_repo.py` prints `Repository validation passed.`
- [ ] `python3 -m unittest discover -s tests` reports `OK`.
- [ ] `git diff --check` produces no output.

### Verification

```bash
# The three-way lock between descriptor, README, and test constants
python3 -m unittest tests.test_mission_control_readme -v

# The new guard and derivation tests
python3 -m unittest tests.test_mission_control_rule_audit -v

# Manifest version agrees with the recorded pin
python3 -c "import json;m=json.load(open('plugins/mission-control/plugin.json'));p=json.load(open('plugins/mission-control/PROVENANCE.json'));print(m['version'],p['source_version']);assert m['version']==p['source_version']"

# Full gates
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

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/54
- Number: 54
- Created at: 2026-08-30T19:24:05.690871+00:00

