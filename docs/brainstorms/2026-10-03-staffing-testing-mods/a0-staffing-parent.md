---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# Saga staffing: run the Claude builder on Opus medium, resolve tiers one way, and let Jev decide raises

### Objective

Stop staffing saga's builder — the `worker` role that implements plan units — on Claude Sonnet. Run
it on Claude Opus at medium effort by default, resolve every role's tier through one code path,
record cost per completed unit so the decision is checked against measurement rather than assumed,
and, when TypeSafe is configured, let Jev raise a unit's tier from what the issue and the unit
actually say.

This is Claude-only. Other vendors' palettes, the portable execution classes shared with the Codex
plugin repository, and orchestrate's live-catalog model choice for non-Claude units are untouched.

### Intent

**Why the builder is on Sonnet today.** `plugins/fleet-core/scripts/fleet_commons/staffing.json`
maps the `worker` role to the `mechanical` work shape, which defaults to `sonnet/medium`. The same
file defines mechanical as "deterministic, scripted transforms, scaffolding — bounded output,
predictable steps". Implementing a plan unit that writes refund or IAM code is not that work. The
role is filed in the wrong category; price is the secondary question.

**Evidence gathered 2026-10-03.** Pricing is Anthropic's pricing page as read that day; the token
mix is this machine's Claude Code transcripts.

- Opus 5.5 is $4 input and $20 output per million tokens; Sonnet 5.5 is $2 and $10. Opus 5.5
  prices cache reads at 0.05 times input, so both models charge $0.20 per million cache-read tokens.
- Across 1,005 transcript files from the 30 days before 2026-10-03 (personal account only), cache
  reads were about 97 percent of input tokens for both models.
- Priced both ways, that real mix costs 1.36 to 1.37 times as much on Opus 5.5 — not twice as much.
  Opus at medium is therefore cheaper per completed unit whenever it finishes with roughly 27
  percent fewer tokens: fewer build-loop passes, or one avoided review repair cycle, where a review
  in this fleet runs up to ten lens reviewers at `opus/high`.
- Nobody has measured cost per completed unit on this fleet. Child U3 builds that measurement.
- Medium is also Opus 5.5's own default effort.

**Three code paths disagree today about the builder's tier.**

- Admission (question 4) resolves role, then work shape, giving `sonnet/medium`. It never reads the
  issue.
- `/plan`'s per-unit tier table tells the planner to call `parse_tier_band` and
  `resolve_tier_for_plan`. Neither function exists anywhere in the repository — they left with
  saga's `tier_defaults.py` — so the planner reads the issue's stamped band by eye.
- `/work`'s direct build launch falls back to the `mechanical` default, giving `sonnet/medium`.

Mission-control stamps that band from the issue type alone: capability and defect get `opus/high`,
enhancement gets `sonnet/medium`.

**Operator rulings, settled 2026-10-03, binding on every child.**

1. The builder runs on Claude `opus/medium` by default, through a new `implementation` work shape.
   `mechanical` stays `sonnet/medium` for the merging and release workers and for genuinely
   mechanical subagents.
2. One resolver answers every role's and every unit's tier for admission, `/plan` and `/work`. The
   issue-type tier band is retired; Jev's per-issue judgment (U4) replaces it where configured.
3. Cost per completed unit is recorded in the run record (U3), so the Opus decision is checked
   against measured cost. The live capture for Claude sessions is a separate card under the Claude
   Code mods parent.
4. When `TYPESAFE_API_KEY` is configured and not switched off, Jev's tier judgment runs by default
   over the real issue and plan unit. A raise at 0.8 confidence or above applies automatically —
   one step, effort first, never to Fable or `max`. A raise between 0.6 and 0.8 is shown for the
   operator to confirm. A suggestion to lower a tier stays advisory until the evaluation harness
   holds about 30 labeled verdicts. This amends fleet-core TypeSafe house rule 10 for raises only.
5. Claude only. No role is pinned to another vendor today; a guard keeps any future one from
   inheriting these tiers through translation.

**Dependency graph.** `U1 → {U2, U4}`; U3 is independent of U1. The Claude agent-type mod and the
live token-capture mod depend on U1 and U3 respectively.

### Risk

high
It changes the default Claude model for every builder and the resolver every subagent spawn reads,
so a mistake mis-staffs every run in the fleet.

### Out-of-scope / non-goals

- No change to any non-Claude vendor palette, to `execution_classes` or
  `root_orchestration_profiles` in `staffing.json`, or to orchestrate's live-catalog model choice.
- No change to the planner, plan reviewer, lens reviewer or functional tester tiers; all stay
  `opus/high`.
- The merging and release workers stay on Sonnet. Moving them is a separate decision.
- No change to how review lenses are selected; that is its own card.

### Inputs inventory

- `plugins/fleet-core/scripts/fleet_commons/staffing.json` — roles, work shapes and vendor
  palettes, schema version 3.
- `plugins/fleet-core/references/staffing.md` — the resolver contract and its guards.
- `plugins/fleet-core/references/typesafe.md` — the data rule and house rules 1 to 10.
- `~/.claude/typesafe/verdicts.jsonl` — exactly one tier verdict on record, from 2026-09-20.
- Anthropic's pricing page as read on 2026-10-03, and the 30-day transcript token mix above.

### Files expected to change

- `plugins/fleet-core/scripts/fleet_commons/staffing.json`
- `plugins/fleet-core/scripts/fleet_commons/staffing.py`
- `plugins/fleet-core/scripts/fleet_commons/jev_verbs.py`
- `plugins/fleet-core/references/staffing.md`
- `plugins/fleet-core/references/typesafe.md`
- `plugins/saga/scripts/admission.py`
- `plugins/saga/scripts/lifecycle_state.py`
- `plugins/saga/scripts/run_record.py`
- `plugins/saga/skills/plan/SKILL.md`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/mission-control/scripts/sdlc_manager.py`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

Each child names its own. Together: resolver tests for the new shape and the single path, a
vendor-translation guard, Jev apply-rule tests with an injected client, run-record usage tests, and
removal of the tier-band and ordinal cost-weight tests along with the code they cover.

### Failure modes / pre-mortem

- **Most likely failure:** `opus/medium` makes the same integration mistakes Sonnet does on IAM and
  refund logic, because those mistakes come from code nothing ever ran, not from model capability.
  The fleet pays about 37 percent more on builder tokens and sees no fewer repair cycles. U3's
  measurement detects it; the pre-review functional testing parent addresses the cause.
- Jev raises too eagerly. Its one recorded verdict answered `opus/max` at 0.9 confidence from a role
  label alone. Mitigation: real state, one step per raise, effort first, never Fable or `max`
  automatically.
- A resolver change silently mis-tiers spawns. Mitigation: the existing fail-loud rules and the tier
  vocabulary guards stay green, and every child adds a resolution test.

### Stop conditions

- Stop if making the builder default `opus/medium` requires changing a non-Claude vendor row or the
  portable execution classes.
- Stop if a single resolver cannot serve admission, `/plan` and `/work` without a second copy of the
  precedence order.
- Stop if amending house rule 10 would also let Jev lower a tier automatically.

### Context library links

- `plugins/fleet-core/references/staffing.md`
- `plugins/fleet-core/references/typesafe.md`
- `plugins/saga/references/run-record.md`

### Acceptance criteria

- [ ] Every child issue closes with its own acceptance criteria met.
- [ ] `uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py resolve --role worker` prints `claude opus/medium`.
- [ ] The same command with `--role merging-worker` and `--role release-worker` still prints `claude sonnet/medium`.
- [ ] `docs/engineering-journal/DECISIONS.md` records the decision with its revisit condition: measured cost per completed unit shows Opus losing to Sonnet.

### Verification

```bash
python3 scripts/bundle_fleet_module.py
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py resolve --role worker
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py resolve --role merging-worker
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/fleet-core/tests plugins/saga/tests plugins/mission-control/tests -q --import-mode=importlib
git diff --check
```
