---
title: orchestrate: the parent-branch lookup asks the archived plugin repository
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

# orchestrate: the parent-branch lookup asks the archived plugin repository

### Objective

`orchestrate start` decides between a `parent/<N>` and an `issue/<N>` branch by asking GitHub about the
issue in the repository the run is in, not in the archived `infiquetra/infiquetra-claude-plugins`.

### Intent

`parent_branch_name` (`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py:2875-2899` at
02c9a61) builds its GraphQL query with a fixed `repository(owner:"infiquetra",name:"infiquetra-claude-plugins")`
(`:2886`). Since the custody move, orchestrate runs in infiquetra-agent-plugins and other repositories,
so it reads the sub-issue count of a different repository's issue with the same number. A run can then
choose the wrong branch name: `parent/<N>` for an issue with no children, or `issue/<N>` for a parent.
Found on 6 October 2026 while planning #147.

### Risk

low
One lookup in one function; the fallback to `issue/<N>` on a failed query stays as it is.

### Out-of-scope / non-goals

- Any other orchestrate behaviour, including the hand-off limits recorded in #178.

### Files expected to change

- `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`
- `plugins/orchestrate/tests/` (the test file that covers `parent_branch_name`, or a new one)
- `plugins/orchestrate/CHANGELOG.md`

### Tests to add or update

- A run started in infiquetra-agent-plugins asks that repository, and returns `parent/147` when #147
  has sub-issues.
- A run started in another repository's checkout asks that repository.
- When `gh` fails or its answer cannot be read, it returns `issue/<N>` with its existing explanation.

### Context library links

_none_

### Acceptance criteria

- [ ] `parent_branch_name` queries the repository the run is in, read from the checkout's `origin` remote or `gh repo view`, never a fixed name.
- [ ] The three tests above pass.

### Verification

```bash
python3 -m pytest plugins/orchestrate/tests -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-06-orchestrate-parent-branch/parent-branch-lookup-defect.md

### Source context
- Source: docs/brainstorms/2026-10-06-orchestrate-parent-branch/parent-branch-lookup-defect.md
- Source type: brainstorm
- Source title: orchestrate: the parent-branch lookup asks the archived plugin repository

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/180
- Number: 180
- Created at: 2026-10-06T18:46:22.330702+00:00
