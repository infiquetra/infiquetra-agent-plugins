---
title: saga: a stale review re-enters code review without the combined-branch functional run
repo: infiquetra-agent-plugins
type: defect
team: asgard
project: operations
labels: defect, needs-plan
risk: low
handoff_maturity: requirements-ready
stage: Shaping
status: Discovering
approval_state: approved
---

# saga: a stale review re-enters code review without the combined-branch functional run

### Objective

Make `/work`'s stale-review path send the branch back through the combined-branch functional run
before it reviews again, so no path into code review skips the gate that #100 added.

### Intent

Issue #100 made a passing combined-branch functional run the gate for code review. `/work` §5.1
(`plugins/saga/skills/work/SKILL.md:878-890` on main at 531ecc2) says review does not start without
that run, and that the reviewed revision comes only from `build_loop.py --handoff`, "not from a
fresh `git rev-parse`". §3.3 (`SKILL.md:611`) says "Every entry into code review comes through
here", including repair batches. The coordinator ruling under operator ruling 4 says the same.

§5.3 contradicts all three. At `SKILL.md:952-953` it handles a stale review (commits landed since
`REVIEWED_SHA`) like this: "keep PR-ready blocked and re-run `/code-review`, capturing a fresh
`REVIEWED_SHA`, before any PR/merge offer". A worker following §5.3 as written either reviews a
revision no combined pass has checked, or re-reviews the old handed revision. Either way the gate
from #100 is skipped on that path.

**Change.** In §5.3, route a stale branch back to Phase 3.3: run the combined-branch loop on the new
head, and take the new `REVIEWED_SHA` from `combined_branch.handed_to_code_review` through
`build_loop.py --handoff`, exactly as §5.1 does. Then re-run `/code-review`.

How it was found: a single-reviewer experiment on #99's reviewed commit (9fb5a22) reported it as a
major conformance finding on 2026-10-04. Neither of #99's two review rounds reported it, and it is
still present on main.

### Risk

low
A wording change to one skill section that brings it into line with §3.3, §5.1 and an existing
ruling; no script changes.

### Out-of-scope / non-goals

- No change to `build_loop.py`, `review_result.py` or the gate itself.
- No change to how staleness is computed (`git rev-list <REVIEWED_SHA>..HEAD --count`).

### Files expected to change

- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- A test in `plugins/saga/tests/` asserting that the work skill's stale-review instructions name the
  combined-branch loop and `--handoff`, and do not tell the worker to capture a fresh
  `REVIEWED_SHA` any other way.

### Context library links

- `plugins/saga/skills/work/SKILL.md` §3.3, §5.1, §5.3
- `plugins/saga/references/run-record.md`

### Acceptance criteria

- [ ] `grep -n "capturing a fresh" plugins/saga/skills/work/SKILL.md` finds nothing.
- [ ] §5.3 sends a stale branch through Phase 3.3 and takes `REVIEWED_SHA` from `build_loop.py --handoff`.
- [ ] The new test fails on the current text and passes on the fixed text.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes.

### Verification

```bash
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-04-saga-review-fixes/stale-review-gate.md

### Source context
- Source: docs/brainstorms/2026-10-04-saga-review-fixes/stale-review-gate.md
- Source type: brainstorm
- Source title: saga: a stale review re-enters code review without the combined-branch functional run

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/144
- Number: 144
- Created at: 2026-10-04T16:08:44.433409+00:00
