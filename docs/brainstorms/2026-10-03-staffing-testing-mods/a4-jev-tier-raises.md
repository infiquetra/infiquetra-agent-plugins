---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# staffing U4 — Jev decides tier raises at admission and in /plan's tier table, from the real issue and unit

### Objective

Make TypeSafe Jev's tier judgment a default part of saga staffing whenever it is configured. It
judges from the actual issue and plan unit, it may raise a tier automatically when confident, and
it may only suggest lowering one until the evaluation harness has measured it.

### Intent

**Today.** `staffing.py resolve --suggest` and admission's batched `--suggest` record Jev's tier
suggestion beside the default and never apply it. No skill or command passes `--suggest`, and the
verdict log holds exactly one tier verdict. Even when run, admission sends Jev only a label such as
`role 'worker' (staffing default sonnet/medium)`. The `tier` verb in
`plugins/fleet-core/scripts/fleet_commons/jev_verbs.py` also tells Jev that mechanical work goes to
Haiku, which contradicts `staffing.json`. Its choices also lack Fable and `xhigh`.

**Change.**

1. **On by default when configured.** It runs when `TYPESAFE_API_KEY` is present, and
   `INFIQUETRA_TYPESAFE_TIERING=off` switches it off. It runs at two points, each as one batched
   request: at admission for every role, given the issue; and when `/plan` renders its per-unit
   tier table, for every unit, given that unit.
2. **Real state, within the data rule.** Send the issue title and body, each plan unit's goal and
   expected files, its work shape, and the issue's security, API, infrastructure and privacy flags
   from `parse_issue.py`. Every one is permitted by `plugins/fleet-core/references/typesafe.md`.
   Redaction is already on the only path to the network.
3. **A narrower question.** Ask whether the unit needs less than, the same as, or more than its
   role's default, rather than asking Jev to pick an absolute tier from the whole palette. Align the
   verb's policy text with `staffing.json`.
4. **Apply by direction.**
   - A raise at 0.8 confidence or above applies automatically: one step, effort first, never to
     Fable or `max`. It is recorded in the run record with Jev's reason, and staffing U1's resolver
     honors it. Note from staffing U1 (issue #93): `/work` passes a plan-recorded unit tier to the
     resolver as the operator's answer, which outranks a recorded raise, and `/plan` records a tier
     for every unit. A raise on a units[] row therefore only reaches an undeclared unit unless this
     card makes `/plan` record the raised tier itself (or record a tier only when the operator
     changed it). `resolve-build-unit-tier` prints `"jev_raise_set_aside": true` when that happens.
   - A raise between 0.6 and 0.8 is pre-filled in admission question 4 for the operator to confirm.
   - A suggestion to lower a tier is shown as advisory only.
   - Anything below 0.6 is logged, not shown.
5. **Labels.** The operator's final answer to question 4, and the tier `/plan` finally records,
   become each verdict's label. This lets the harness decide later whether lowering may also
   become automatic.
6. **Amend house rule 10** in `typesafe.md` for raises only, with a `DECISIONS.md` entry.

### Risk

high
It lets a model change the tier real runs execute at without a per-run confirmation, which spends
money and must not lower quality.

### Out-of-scope / non-goals

- No automatic lowering of any tier.
- No use of Jev for non-Claude vendor model choice.
- No change to the lens proposal, which is its own card.

### Inputs inventory

- `plugins/fleet-core/references/typesafe.md` — data rule and house rules.
- `plugins/fleet-core/scripts/fleet_commons/staffing.py` — `consult_tier_suggestions`.
- `~/.claude/typesafe/verdicts.jsonl` — the single prior tier verdict, `opus/max` at 0.9 for a role
  label.

### Files expected to change

- `plugins/fleet-core/scripts/fleet_commons/jev_verbs.py`
- `plugins/fleet-core/scripts/fleet_commons/staffing.py`
- `plugins/fleet-core/references/typesafe.md`
- `plugins/fleet-core/references/staffing.md`
- `plugins/saga/scripts/admission.py`
- `plugins/saga/skills/plan/SKILL.md`
- `plugins/saga/scripts/_bundled/` (regenerated)
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `plugins/fleet-core/tests/test_staffing_suggest.py`, with an injected client covering:
  - a 0.85 raise applies one effort step;
  - a 0.7 raise is pending confirmation;
  - a lower suggestion is never applied;
  - a raise never lands on Fable or `max`;
  - the off switch makes no call.
- `plugins/saga/tests/test_admission.py`: the state sent includes the issue body and flags, and the
  operator's answer is logged as the label.
- `plugins/fleet-core/tests/test_typesafe_reference_drift.py` stays green after the rule 10
  amendment.

### Failure modes / pre-mortem

- Jev reaches for the top of the scale, as its one verdict did. Mitigation: one step per raise,
  effort first, and hard exclusion of Fable and `max`.
- A slow or failing endpoint delays admission. Mitigation: the existing fail-open rule. A failed
  request leaves the defaults and says why.

### Stop conditions

- Stop if any path would apply a lower tier without the operator.
- Stop if the state needed for a good judgment would include a transcript or customer content.

### Context library links

- `plugins/fleet-core/references/typesafe.md`
- `plugins/fleet-core/references/staffing.md`

### Acceptance criteria

- [ ] With an injected client, a raise at 0.85 changes the resolved tier by one effort step and records the reason, and a lower suggestion at 0.95 changes nothing.
- [ ] `INFIQUETRA_TYPESAFE_TIERING=off` makes no request.
- [ ] A test asserts the `tier` verb's policy text names each work shape's default exactly as `staffing.json` declares it, so the two cannot drift again.
- [ ] `typesafe.md` house rule 10 states the raise-only exception, and a `DECISIONS.md` entry records it.

### Verification

```bash
python3 scripts/bundle_fleet_module.py
python3 -m pytest plugins/fleet-core/tests/test_staffing_suggest.py plugins/fleet-core/tests/test_typesafe_reference_drift.py plugins/saga/tests/test_admission.py -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```
