# Board Workflow Reference

Condensed reference for the Infiquetra GitHub Projects boards. The canonical source of
truth is `$INFIQUETRA_SDLC_PATH/config/sdlc-schema.json`, with prose context in
`$INFIQUETRA_SDLC_PATH/docs/process/board-topology.md` and
`$INFIQUETRA_SDLC_PATH/docs/process/kanban-workflow.md`.

---

## Active Boards

| Project key | Board | Purpose |
|-------------|-------|---------|
| `operations` | Operations | Raw operator intent, approvals, personal/operator work, and shaping |
| `asgard` | Asgard | Jeff-proximal rapid action, incubation, and mission-mode work |
| `campps` | CAMPPS | Long-lived initiative execution board (Outcome / Capability / Component slices) |

No board is a default: board operations require an explicit `--project`. Prefer project
views over new boards until scale, automation, or reporting needs justify a separate board.

The former project #1 (`Mount Olympus`) is closed and archived history (see the legacy
read-only section below); it is not an active board or a routing target.

---

## Workflow

All three active boards — Operations, Asgard and CAMPPS — run the one shared
`stage_flow` workflow. There is no per-board ladder:

```
Intake -> Shaping -> Planning -> Active -> Verify -> Retro
```

`Stage` is the board column; `Status` carries the in-stage condition for that stage. The
per-stage Status sets below are transcribed from the workflow's `stage_statuses` block in
`$INFIQUETRA_SDLC_PATH/config/sdlc-schema.json` (the first name in each list is that stage's
entry option):

| Stage | Statuses |
|-------|----------|
| Intake | `Capturing`, `Needs clarification`, `Triage`, `Backlog` |
| Shaping | `Discovering`, `Defining requirements`, `Ready for Planning` |
| Planning | `Designing`, `Design review`, `Execution planning`, `Ready for Active` |
| Active | `Implementing`, `Integrating`, `Code review`, `Repairing`, `Ready to merge`, `Deploying to non-production` |
| Verify | `Awaiting verification`, `Verifying`, `Verification failed`, `Closeout`, `Ready to close` |
| Retro | `Gathering evidence`, `Awaiting operator input`, `Capturing learnings`, `Ready to close` |

`Blocked` is the single cross-cutting status and is valid in any stage; `Ready to close` is
the only terminal status. No active board carries a pause column: a paused card is expressed
through labels and issue state, never through a workflow status.

Deployment state belongs in deployment fields and GitHub Deployments/Environments, not in
the core Status workflow.

### Legacy: `Mount Olympus` (read-only history)

The former `Mount Olympus` board (project #1) used
`Backlog -> Ready -> Planning -> Assigned -> In Review -> Done / Closed`. It is closed and
archived; tooling may read its historical timeline values for history, but no new cards are
created or routed there. The authoritative list of those legacy timeline values is
`LIVE_LEGACY_STATUS_ALIASES` in `plugins/mission-control/scripts/sdlc_manager.py` — rely on
that map, not on a hand-copied list here.

---

## Work In Progress

No board enforces a card-count limit on any Stage. The former per-column limits were
withdrawn along with the `wip_limits` block in `sdlc-schema.json`; `board wip` reports a
count per Status and names no limit. Run concurrency is resolved from the staffing roster
and the applicable per-vendor and per-account constraints, not from a column cap.

---

## Standup Format

Walk right-to-left through the relevant board. All three boards share one Stage ladder,
so the review order is the same everywhere:

| Board | Review order |
|-------|--------------|
| Operations / Asgard / CAMPPS | Retro -> Verify -> Active -> Planning -> Shaping -> Intake |

Ask:

- What is terminal and safe to archive?
- What is waiting for verification or review?
- What is actively owned, and is it aging?
- What is blocked or waiting on Jeff?
- What should move next, and what should stay out of WIP?

---

## Common Scenarios

### Raw Intent From Jeff

1. Capture on Operations in the `Intake` stage (entry status `Capturing`).
2. Shape in `Shaping` until the target team and context pack are clear.
3. Move to `Ready for Planning`, the terminal status of the `Shaping` stage.
4. Route to Asgard, CAMPPS, Jeff, or External/Deferred based on target team.

### Explicit Cross-Team Transfer

1. Treat Asgard and CAMPPS as sibling active target surfaces, not stages in a default funnel.
2. Keep work on the selected board unless an operator explicitly routes, transfers, clones, or links it elsewhere.
3. When a transfer is requested, make the receiving issue self-contained: target repo or surface, acceptance criteria, verification, risk, approvals, and context links must be clear.

### CAMPPS Initiative Flow

1. Capture the outcome/capability candidate on CAMPPS in the `Intake` stage (default entry
   status `Capturing`).
2. Advance the card through the stages as the initiative is shaped, planned, and executed:
   write the `Stage` column with `flow set-field --project campps --repo <repo> --number <N>
   --field Stage --option <stage>`, and update the in-stage condition with
   `board move --status <status>` (for example `Implementing` while in `Active`).
3. Close out through `Verify` and `Retro`; `Ready to close` is the only terminal status.
4. Track environment promotion separately through deployment fields and deployment records.

---

## Metrics Boundaries

Cycle time starts when active ownership begins:

| Board | Start | Terminal |
|-------|-------|----------|
| Operations / Asgard / CAMPPS | `Active` stage | `Ready to close` |

> **How the start boundary is actually detected.** `_cycle_start_statuses` in
> `scripts/sdlc_manager.py` returns the literal option name `Active`, and the
> timeline query it feeds (`QUERY_GET_ISSUE_TIMELINE`) captures only the option
> *name* of a single-select change — it records no field name or id, so it cannot
> tell a `Stage` change from a `Status` change. `Active` is a live `Stage` option
> on all three boards and is not a `Status` option at all, so the start boundary is
> whichever field first carried an option named `Active`. That is close to the
> boundary this table declares, but it is matched by name rather than by field.
> Making the field explicit is outside issue #1020, whose scope is the cached
> census and the prose describing it.


Legacy `Mount Olympus` timeline values may be read for history but are never used to create
new cards; the authoritative value list is `LIVE_LEGACY_STATUS_ALIASES` in
`plugins/mission-control/scripts/sdlc_manager.py`.
