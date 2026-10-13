# agent-launcher: sandboxed reviewer recipes for Grok and Muse, and a spending ceiling for Claude reviews

### Objective

Let `launcher.py review` start Grok and Muse as targeted reviewers when, and only when, each passes
`launcher.py reviewer-probe`, and let every Claude reviewer launch carry a spending ceiling. Without these, K3's
reviewer bake-off (saga-review-corpus#3, #147 decision D1) cannot run.

### Intent

`REVIEWER_RECIPES` in `plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py` holds a recipe only for
`claude`; every other vendor is refused by name until `reviewer-probe` passes on it (Codex failed on 2026-10-06 when
its workspace-write sandbox read a file outside its workspace). D1 decided that a bake-off between Grok
(`grok-4.7`, xhigh), Muse (`muse-spark-1.3-contributor`, max) and Claude Opus as the baseline picks the reviewer the
corpus harness measures. K3's plan found that neither contestant can be launched, and that the review command never
passes a spending limit to `claude -p`, which K3's harness requires on every Claude launch.

### Out-of-scope / non-goals

- Recipes for Codex, Agy, Qwen or OpenCode.
- Weakening the probe: a vendor that cannot pass it stays refused, and the card records the evidence instead.
- The bake-off itself, which is K3's.

### Files expected to change

- plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py
- plugins/agent-launcher/tests/test_launcher_reviewer.py
- plugins/agent-launcher/skills/agent-launcher/SKILL.md
- plugins/agent-launcher/CHANGELOG.md
- docs/engineering-journal/LEARNINGS.md

### Tests to add or update

- For Grok and for Muse: the recipe's argv, settings and result parser, including that no flag from
  `REVIEWER_FORBIDDEN_FLAGS` for that vendor is ever passed, and that API-key variables are removed.
- `reviewer-probe` recorded live for each vendor: writes outside the copy denied, reads outside the copy denied,
  network denied, and an answer parsed. A vendor that fails any of these is not added, and the test pins its refusal.
- A Claude reviewer launch passes `--max-budget-usd` from a required ceiling argument, and a launch with no ceiling
  is refused.

### Context library links

_none_

### Acceptance criteria

- [ ] `launcher.py reviewer-probe --vendor grok` and `--vendor muse` each either pass and the vendor joins
  `REVIEWER_RECIPES`, or fail and the vendor stays refused with the failing check recorded in LEARNINGS.md:
  `python3 -m pytest plugins/agent-launcher/tests/test_launcher_reviewer.py` covers both outcomes.
- [ ] Every Claude reviewer launch carries a spending ceiling, and a launch without one is refused.
- [ ] No recipe passes a vendor's forbidden flag, and the existing Claude recipe's behaviour is unchanged.

### Verification

```bash
python3 -m pytest plugins/agent-launcher/tests/test_launcher_reviewer.py
python3 plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py reviewer-probe --vendor grok
python3 plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py reviewer-probe --vendor muse
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

### Risk

high

The change decides which vendors may run as sandboxed reviewers over untrusted code; a wrong recipe lets a reviewer read or write outside its copy.

### Inputs inventory

- Each vendor CLI's own sandbox and permission flags, read from its `--help` on the build date.
- The existing `reviewer-probe` checks and `REVIEWER_FORBIDDEN_FLAGS`.

### Failure modes / pre-mortem

- Most likely: a vendor's sandbox looks enforced but leaks a read outside the copy, as Codex's did; the probe must
  test reads, writes and network separately, live, and the recipe ships only on a full pass.
- A vendor's subscription sign-in breaks when API-key variables are stripped; the probe records the sign-in path.

### Stop conditions

- A probe shows a sandbox escape on any vendor: stop, record it, and keep that vendor refused.
- A recipe would need a forbidden flag to run at all: stop and keep the vendor refused.

### Notes / conventions

Part of #147 (K3's prerequisite). Only the reviewer launch path changes; interactive sessions are untouched.
