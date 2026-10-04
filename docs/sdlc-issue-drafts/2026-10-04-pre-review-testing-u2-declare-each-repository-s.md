---
title: pre-review testing U2 — Declare each repository's functional-test environment in its saga profile
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

# pre-review testing U2 — Declare each repository's functional-test environment in its saga profile

### Objective

Let a repository say once, in `.saga-profile.json`, how its changes are functionally tested before
review. Make admission ask for it once when it is missing, and write the answer back.

### Intent

Add a `functional_test_environment` block to the repository profile. It replaces `branch_preview`
and `branch_preview_command`, which migrate into it. The block holds:

- `kind`: `local`, `emulator`, `ephemeral-stack` or `shared-nonprod`.
- `deploy_command`: what builds and deploys or starts the change. Optional for `local`.
- `test_command`: what runs the functional suite against it. Required.
- `teardown_command`: optional; runs on every exit path when present.
- `scope`: `private` or `shared`. `shared-nonprod` implies `shared`.

The alternative is `functional_test_waiver: {"reason": "..."}` for a repository where functional
testing does not apply, such as a documentation-only catalog. Admission records which one the run
used.

When a repository has neither, admission asks once. The question names the four kinds, collects the
commands or a waiver reason, and writes the answer to `.saga-profile.json`. The file is tracked, so
every worktree sees it.

### Risk

medium
It changes the profile contract every saga run reads, but the old keys migrate and an absent block
leads to one question, not a failure.

### Out-of-scope / non-goals

- Running the commands is pre-review testing U4.
- No choice of mechanism by saga.

### Files expected to change

- `plugins/saga/references/repository-profile.md`
- `plugins/saga/scripts/admission.py`
- `plugins/saga/scripts/build_loop.py` (reads the new block in place of `branch_preview`)
- `plugins/saga/references/mechanical-baseline.md`
- `.saga-profile.json` (this repository's own declaration or waiver)

### Tests to add or update

- `plugins/saga/tests/test_admission.py`: a missing block produces exactly one question; an answer
  is written back; a waiver needs a reason; the old preview keys migrate.
- `plugins/saga/tests/test_build_loop.py`: the dry run prints the declared environment.

### Context library links

- `plugins/saga/references/repository-profile.md`

### Acceptance criteria

- [ ] `plugins/saga/references/repository-profile.md` documents the block, the waiver and the migration from `branch_preview`.
- [ ] Admission on a repository with no declaration asks one question and writes the answer to `.saga-profile.json`.
- [ ] `uv run python plugins/saga/scripts/build_loop.py --issue <N> --dry-run` prints the declared environment, or the waiver and its reason.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_admission.py plugins/saga/tests/test_build_loop.py -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-03-staffing-testing-mods/c2-test-environment-declaration.md

### Source context
- Source: docs/brainstorms/2026-10-03-staffing-testing-mods/c2-test-environment-declaration.md
- Source type: brainstorm
- Source title: pre-review testing U2 — Declare each repository's functional-test environment in its saga profile

### Recommended Tier Band
opus/high

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/97
- Number: 97
- Created at: 2026-10-04T01:52:07.413955+00:00
