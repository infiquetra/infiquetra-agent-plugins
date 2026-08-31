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

The former project #1 (`Mount Olympus`) is retired-historical and closed (see the legacy
read-only section below); it is not an active board or a routing target.

---

## Workflows

### Operations And Asgard

```
Idea -> Shaping -> Ready -> Active -> Verify -> Done
```

| Status | Purpose |
|--------|---------|
| Idea | Captured thought or opportunity. Not shaped enough for execution. |
| Shaping | Intent is being clarified, scoped, or turned into an actionable card. |
| Ready | Work is shaped enough to route or start. Operations must name a target team before promotion. |
| Active | The owner is working the card. |
| Verify | Outcome is being checked before closure or promotion. |
| Done | Completed or intentionally closed for this board. |

Asgard modes:

| Mode | Use |
|------|-----|
| Rapid Action | Reversible, time-sensitive work that benefits from low ceremony. |
| Incubator | Exploratory work likely to define future initiative execution. |
| Mission | Focused, high-leverage work close to Jeff with a clear outcome. |

### CAMPPS

CAMPPS runs the shared `stage_flow` workflow. The Operations and Asgard section
above still shows the retired `intent_flow` names; correcting them is tracked as
a separate change and is not done here:

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
retired; tooling may read its historical timeline values for history, but no new cards are
created or routed there. The authoritative list of those legacy timeline values is
`LIVE_LEGACY_STATUS_ALIASES` in `plugins/mission-control/scripts/sdlc_manager.py` — rely on
that map, not on a hand-copied list here.

---

## WIP Limits

| Board | Status | Limit |
|-------|--------|-------|
| Operations | Shaping | 10 |
| Operations | Ready | 10 |
| Operations | Active | 5 |
| Operations | Verify | 5 |
| Asgard | Shaping | 8 |
| Asgard | Ready | 8 |
| Asgard | Active | 5 |
| Asgard | Verify | 5 |

CAMPPS is an initiative rollup board and does not enforce per-column WIP limits.
When a limit is exceeded, finish or unblock current work before pulling more into that status.
Critical defects can temporarily override WIP, but the exception should be visible in the card.

---

## Standup Format

Walk right-to-left through the relevant board:

| Board | Review order |
|-------|--------------|
| Operations / Asgard | Done -> Verify -> Active -> Ready -> Shaping -> Idea |
| CAMPPS | Retro -> Verify -> Active -> Planning -> Shaping -> Intake |

Ask:

- What is terminal and safe to archive?
- What is waiting for verification or review?
- What is actively owned, and is it aging?
- What is blocked or waiting on Jeff?
- What should move next, and what should stay out of WIP?

---

## Common Scenarios

### Raw Intent From Jeff

1. Capture on Operations as `Idea`.
2. Shape until target team and context pack are clear.
3. Move to `Ready`.
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
| Operations / Asgard | Active | Done |
| CAMPPS | Active | Ready to close |

Legacy `Mount Olympus` timeline values may be read for history but are never used to create
new cards; the authoritative value list is `LIVE_LEGACY_STATUS_ALIASES` in
`plugins/mission-control/scripts/sdlc_manager.py`.
