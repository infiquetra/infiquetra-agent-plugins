# Objective Workflow Reference

Complete reference for Objective lifecycle in the Infiquetra SDLC. Sources of
truth: `$INFIQUETRA_SDLC_PATH/docs/process/work-hierarchy.md`,
`$INFIQUETRA_SDLC_PATH/docs/process/sub-issues.md`, and
`$INFIQUETRA_SDLC_PATH/config/sdlc-schema.json`.

## What Is An Objective?

An Objective is a time-bounded delivery grouping represented by:

1. An `Objective` project-field option.
2. An Outcome Scorecard doc in the owning context-library repository.
3. Optionally, per-repo GitHub Milestones for due-date and PR rollup.

An Objective is not an issue type or native parent. Capabilities are top-level
by default and carry the Objective field value. Native sub-issues represent
decomposition under an Outcome or Capability, not Objective membership.

## Creation Workflow

### 1. Create The Scorecard

Follow the owning context library's Objective/Outcome Scorecard convention.
Record the target outcome, metrics, review date, included Capabilities, risks,
and pivot/persist/pause decision authority.

### 2. Create Or Reuse The Field Option

```bash
python3 sdlc_manager.py flow field-options \
  --project <project> --field Objective

python3 sdlc_manager.py fields create-option \
  --project <project> --field Objective --option "<Objective name>"
```

Field helpers discover live IDs; never cache option IDs.

### 3. Create Top-Level Capabilities And Assign Objective

```bash
python3 sdlc_manager.py issue create --repo <repo> --type capability
python3 sdlc_manager.py board add --project <project> --repo <repo> --number <N>
python3 sdlc_manager.py flow set-field \
  --project <project> --repo <repo> --number <N> \
  --field Objective --option "<Objective name>"
```

Do not create or link an Objective parent issue. If the board uses dated Outcome
proof cards, link Capabilities to those Outcome cards only under that explicit
board contract.

### 4. Add Executable Children When Needed

```bash
python3 sdlc_manager.py flow link-sub-issue \
  --parent-repo <capability-repo> --parent-number <capability-number> \
  --child-repo <child-repo> --child-number <child-number>
```

Set the same Objective field value on child cards. Use
`flow unlink-sub-issue` to remove an accidental or retired parent layer without
closing either issue.

### 5. Create A Milestone When Useful

```bash
python3 sdlc_manager.py milestones create \
  --repo <repo> \
  --title "<Objective name>" \
  --due-date <YYYY-MM-DD> \
  --description "<target outcome>"
```

Use milestones only when repo-level due-date or PR rollup is useful.

## Progress And Completion

Read aggregate progress by filtering the active project on the Objective field.
Use Capability sub-issue progress for decomposition and milestone percentages
only as optional secondary evidence.

An Objective completes when:

1. Included Capabilities satisfy their completion contracts.
2. Required live, deployment, and verification evidence exists.
3. Critical or high defects are resolved or explicitly deferred.
4. Optional milestones are closed.
5. The Outcome Scorecard records actuals and the pivot/persist/pause decision.

## Cross-Repo Coordination

Use the same Objective option across every owning project, assign it to every
Capability and child card, and use matching milestone names only where milestone
rollup helps. Native parent links stay local to real decomposition and may be
cross-repository when the parent Capability spans repositories.
