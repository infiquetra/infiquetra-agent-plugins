---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# staffing U2 — Retire mission-control's issue-type tier band stamp

### Objective

Stop stamping `### Recommended Tier Band` onto new issues. The band is derived from the issue type
alone, admission never reads it, and the `/plan` functions that were meant to apply it no longer
exist. Jev's per-issue judgment (staffing U4) replaces it.

### Intent

`plugins/mission-control/scripts/sdlc_manager.py` carries `_ISSUE_TYPE_TIER_BANDS` and
`derive_tier_band`, which stamp `opus/high` on capability and defect cards and `sonnet/medium` on
enhancement and context-update cards. After staffing U1 the builder defaults to `opus/medium`, so an
enhancement card stamped `sonnet/medium` actively misleads a planner who reads it.

Remove the stamp, the type-to-band map, the fence-aware stamping helpers, and the documentation that
describes them. Existing issue bodies keep their old section; nothing reads it any more, so it is
inert and is not rewritten.

### Risk

medium
The change touches issue creation for every repository mission-control files into, but it only
removes an advisory section that no code consumes.

### Out-of-scope / non-goals

- No rewrite of existing issue bodies.
- No change to issue types, labels or required card sections.
- `/plan`'s references to the band are removed in staffing U1, not here, so each file has one writer.

### Files expected to change

- `plugins/mission-control/scripts/sdlc_manager.py`
- `plugins/mission-control/skills/issues/SKILL.md`
- `plugins/mission-control/skills/issues/references/templates-reference.md`
- `plugins/mission-control/CHANGELOG.md`
- `plugins/mission-control/plugin.json`

### Tests to add or update

- Remove or invert the tier-band stamping tests in `plugins/mission-control/tests/` so a newly
  prepared card carries no `### Recommended Tier Band` section.
- `plugins/mission-control/tests/test_issue_prepare.py`: a prepared draft renders without the band.

### Context library links

- `plugins/mission-control/skills/issues/SKILL.md`

### Acceptance criteria

- [ ] `grep -rn "Recommended Tier Band\|_ISSUE_TYPE_TIER_BANDS\|derive_tier_band" plugins/mission-control` returns nothing outside the changelog.
- [ ] A draft from `python3 plugins/mission-control/scripts/sdlc_manager.py issue prepare` contains no `### Recommended Tier Band` section.
- [ ] The mission-control suite passes.

### Verification

```bash
grep -rn "Recommended Tier Band\|_ISSUE_TYPE_TIER_BANDS\|derive_tier_band" plugins/mission-control --include=*.py --include=*.md
python3 -m pytest plugins/mission-control/tests -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```
