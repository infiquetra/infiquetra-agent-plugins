---
title: Saga lenses: Jev proposes conditional review lenses at admission when configured
repo: infiquetra-agent-plugins
type: enhancement
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: enhancement, needs-plan
risk: medium
handoff_maturity: requirements-ready
approval_state: approved
---

# Saga lenses: Jev proposes conditional review lenses at admission when configured

### Objective

Have admission's lens question (question 5) arrive pre-filled with Jev's proposed additions,
whenever TypeSafe is configured. Jev may add conditional lenses and never remove one. The questions
are generated from the lifecycle repository's lens catalogue.

### Intent

**Today.** `plugins/saga/scripts/review_roster.py --propose` already asks Jev whether each excluded
conditional lens applies after all, at a probability threshold of 0.5, and can only add lenses.
The code-review skill describes it as an optional step the planner "may" run at review time. By
then admission has already fixed the lens set, and nothing calls it: the verdict log holds no lens
proposals. Separately, `plugins/fleet-core/scripts/fleet_commons/jev_verbs.py` carries a `lenses`
verb that predates the catalogue. It asks about five keys, two of which are always-on lenses, and
nothing in the plugins calls it.

**Change.**

1. When `TYPESAFE_API_KEY` is present (and `INFIQUETRA_TYPESAFE_LENSES=off` is not set), admission
   runs the proposal over the issue body and the plan summary when it builds question 5.
2. Additions at 0.8 or above arrive pre-checked. Additions from 0.6 to 0.8 are listed as
   "consider". Anything lower is logged and not shown. Every addition carries its probability.
3. The proposal stays add-only. It never questions the four always-on lenses.
4. The question set is generated from the conditional lens identifiers in infiquetra-sdlc's
   `config/lens-catalogue.json`. A test checks the set against the catalogue in both directions,
   the way the `qa-strategies` verb is held to its catalogue.
5. The operator's final declaration becomes each verdict's label.
6. Delete the dead `lenses` verb.

### Risk

medium
More lenses means more reviewer spend per cycle, but the change is add-only and the operator sees
every addition before the lens set is fixed.

### Out-of-scope / non-goals

- No removal of a lens by Jev, ever.
- No change to the lens catalogue itself; it is owned by infiquetra-sdlc.
- No change to reviewer staffing or scoring.

### Files expected to change

- `plugins/saga/scripts/admission.py`
- `plugins/saga/scripts/review_roster.py`
- `plugins/saga/skills/code-review/SKILL.md`
- `plugins/saga/skills/plan/SKILL.md`
- `plugins/fleet-core/scripts/fleet_commons/jev_verbs.py`
- `plugins/saga/scripts/_bundled/` (regenerated)
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- `plugins/saga/tests/test_review_roster.py`: questions come from the catalogue, both directions;
  bands at 0.8 and 0.6; add-only.
- `plugins/saga/tests/test_admission.py`: question 5 is pre-filled with additions and their
  probabilities, and the off switch makes no call.
- `plugins/fleet-core/tests/test_jev_cli.py`: the `lenses` verb is gone from the command list.

### Context library links

- `plugins/saga/skills/code-review/SKILL.md`
- `plugins/fleet-core/references/typesafe.md`

### Acceptance criteria

- [ ] With an injected client, admission's question 5 lists a 0.85 addition pre-checked, a 0.7 addition as "consider", and omits a 0.4 one.
- [ ] No path removes a declared or always-on lens.
- [ ] `grep -n '"lenses"' plugins/fleet-core/scripts/fleet_commons/jev_verbs.py` returns nothing.
- [ ] The question set equals the catalogue's conditional lens identifiers, checked by a test.

### Verification

```bash
python3 scripts/bundle_fleet_module.py
python3 -m pytest plugins/saga/tests/test_review_roster.py plugins/saga/tests/test_admission.py plugins/fleet-core/tests/test_jev_cli.py -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/b0-jev-lens-proposals.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/b0-jev-lens-proposals.md
- Source type: brainstorm
- Source title: Saga lenses: Jev proposes conditional review lenses at admission when configured

### Recommended Tier Band
sonnet/medium

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/110
- Number: 110
- Created at: 2026-10-04T01:56:26.346873+00:00
