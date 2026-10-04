---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# pre-review testing U5 — Review gate and cycle-limit acceptance require passing functional tests

### Objective

Refuse to start code review without a passing combined-branch functional run, unless the run
carries a recorded waiver. At the review cycle limit, accept only a revision that passed the
acceptance tests.

### Intent

1. **The gate.** `/work`'s review step (Phase 5.1) already refuses unless the build loop went green
   on the revision under review. Extend "green" to include the combined-branch functional pass from
   pre-review testing U4, unless the run record carries a waiver. A standalone `/code-review` reads
   the same evidence. It says plainly when there is none and does not proceed silently.
2. **The cycle limit.** When review ends `cycle_cap_best_available`, the revision it names must be
   one with a passing functional run. If the latest revision has none, run the loop on it first.
   The closeout cites the functional evidence, and every leftover finding is filed as a linked
   issue.

### Risk

high
It adds a hard gate in front of review and changes what may be accepted at the cycle limit.

### Out-of-scope / non-goals

- No change to lens scoring or to the typed review outcomes.
- No change to `/qa`.

### Inputs inventory

- `plugins/saga/skills/work/SKILL.md` Phase 5.1 to 5.3 — the reviewed-revision and stale-review
  rules.
- `plugins/saga/skills/code-review/SKILL.md` Phase 0.

### Files expected to change

- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/skills/code-review/SKILL.md`
- `plugins/saga/scripts/review_result.py`
- `plugins/saga/scripts/release_step.py`
- `plugins/saga/references/run-record.md`

### Tests to add or update

- A gate test: no review hand-off without a passing combined-branch functional run, and a waiver
  admits review with its reason recorded.
- A cycle-limit test: `cycle_cap_best_available` naming a revision without a passing functional run
  is refused.
- A closeout test: the composed closeout cites the functional evidence and the linked residual
  issues.

### Failure modes / pre-mortem

- The waiver becomes the default. It requires a reason and is printed in the closeout comment.

### Stop conditions

- Stop if enforcing the gate would require `/code-review` to decide acceptance itself; Work keeps
  that authority.

### Context library links

- `plugins/saga/skills/work/SKILL.md`

### Acceptance criteria

- [ ] With no passing combined-branch functional run and no waiver, `/work` does not hand the revision to `/code-review`, shown by a test.
- [ ] A `cycle_cap_best_available` result naming a revision without passing functional tests is refused, shown by a test.
- [ ] The closeout composed by `uv run python plugins/saga/scripts/release_step.py --record <path> close --disposition delivered` cites the functional evidence.

### Verification

```bash
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```
