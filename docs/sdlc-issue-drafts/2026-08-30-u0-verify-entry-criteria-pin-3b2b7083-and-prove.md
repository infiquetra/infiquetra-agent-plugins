---
title: U0 — Verify entry criteria: pin 3b2b7083 and prove the upstream suite green from a scratch clone
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

# U0 — Verify entry criteria: pin 3b2b7083 and prove the upstream suite green from a scratch clone

### Objective

Close the runbook's entry criteria for the 2.15.2 resynchronization and record
the result, so every later unit builds on a proven pin rather than an assumed one.

Operator ruling 1 fixes the pin at `3b2b7083` — the latest accepted `origin/main`
revision carrying Mission Control 2.15.2 — and requires the upstream suite proven
green at that exact commit **from a disposable scratch clone**. Continuous
integration reporting success is corroborating evidence, not the same act. The
current pin's own provenance note records that this discipline was followed for
`84eaf042`, which is what lets the descriptor claim the synchronization derives
from a passing source. This unit produces the same sentence for `3b2b7083`.

### Intent

Verify and record, in one plan note, every entry-criteria line the runbook
requires, plus the two facts that make the pin choice defensible.

**Why the pin wording matters.** Three commits carry version 2.15.2 and their
package trees are not identical. `379d2350`, where the version landed, has package
tree `0fdcea0d`. `1111de33` (its document review) and `3b2b7083` (the accepted
merge) share tree `a851eabb`. The document review repaired `CHANGELOG.md` and
`skills/board/references/kanban-workflow.md` inside the package without moving the
version. Pinning the version-landing commit would import content its own review had
already corrected. Record this comparison so the choice is auditable.

**Read the merge policy before any text states a merge form.** This is lesson R1
from the #9 retrospective, where a squash-only policy was discovered at merge time
after the plan and pull-request body had already stated a merge commit.

**Record which runbook steps a resync skips.** `docs/runbooks/portable-plugin-port.md`
v1.1.0 is written for an initial port: its Phase 0 says "write `ports/<package>.json`"
and Phase 1 offers three parallel lanes. Neither maps to a resynchronization, and no
prior standalone-resync plan exists in `docs/plans/` to copy. Name the steps this run
skips and why, rather than leaving the deviation undocumented.

### Out-of-scope / non-goals

- No change to `ports/mission-control.json` or anything under `plugins/mission-control/`. This unit only verifies and records.
- No amendment to the runbook itself. If the runbook needs a resync phase structure, that is separate work.
- No upstream edits of any kind.

### Files expected to change

- `docs/plans/2026-08-30-mission-control-resync-u0-entry-criteria.md`

### Tests to add or update

None. This unit produces a recorded verification artifact, not code. The evidence
is the captured transcript of each command and its output, pasted verbatim per
runbook Phase 2's capture rule.

### Context library links

- `docs/runbooks/portable-plugin-port.md` — entry criteria
- `docs/retros/issue-9-2026-08-25.md` — lesson R1, merge-policy preflight

### Acceptance criteria

- [ ] A disposable scratch clone of `infiquetra/infiquetra-claude-plugins` at `3b2b7083` runs its own suite green, with the captured transcript pasted verbatim into the plan note.
- [ ] The pin is confirmed present and correct: `git -C <scratch> show 3b2b7083:plugins/mission-control/.claude-plugin/plugin.json` reports version `2.15.2`.
- [ ] The three-revision tree comparison is recorded, showing `379d2350` at tree `0fdcea0d` and `1111de33`/`3b2b7083` at tree `a851eabb`.
- [ ] The repository's allowed merge methods are recorded from `gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed`.
- [ ] The Python floor is confirmed unchanged: `git -C <scratch> show 3b2b7083:pyproject.toml | grep requires-python` prints `>=3.12`.
- [ ] The assessment plan prints without running: `python3 scripts/assess_clients.py --package mission-control` exits 0.
- [ ] The plan note names the runbook version followed (1.1.0) and lists each entry-criteria step a resync skips, with its reason.

### Verification

```bash
# Disposable scratch clone, suite green at the exact pin
SCRATCH=$(mktemp -d)
git clone --quiet https://github.com/infiquetra/infiquetra-claude-plugins "$SCRATCH/upstream"
git -C "$SCRATCH/upstream" checkout --quiet 3b2b7083
git -C "$SCRATCH/upstream" show 3b2b7083:plugins/mission-control/.claude-plugin/plugin.json

# Three-revision package-tree comparison
for r in 379d2350 1111de33 3b2b7083; do \
  printf "%s %s\n" "$r" "$(git -C "$SCRATCH/upstream" rev-parse $r:plugins/mission-control)"; done

# Floor and merge policy
git -C "$SCRATCH/upstream" show 3b2b7083:pyproject.toml | grep requires-python
gh repo view infiquetra/infiquetra-agent-plugins --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed

# Assessment plan only; runs nothing
python3 scripts/assess_clients.py --package mission-control
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

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/51
- Number: 51
- Created at: 2026-08-30T19:23:14.498138+00:00

