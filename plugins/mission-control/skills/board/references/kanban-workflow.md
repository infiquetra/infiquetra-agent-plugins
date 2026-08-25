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

```
Idea -> Committed -> In Progress -> Done   (pause: Parked)
```

| Status | Purpose |
|--------|---------|
| Idea | Captured outcome/capability candidate, not yet admitted to the portfolio. |
| Committed | Admitted to the initiative portfolio; Objective field is set. |
| In Progress | Component slices are being built and verified. |
| Done | Work is completed for this initiative slice. |
| Parked | Intentionally paused initiative work. |

Deployment state belongs in deployment fields and GitHub Deployments/Environments, not in
the core Status workflow.

### Legacy: `Mount Olympus` (read-only history)

The former `Mount Olympus` board (project #1) used
`Backlog -> Ready -> Planning -> Assigned -> In Review -> Done / Closed`. It is closed and
retired; tooling may read its historical timeline values (`In Progress`, `In Development`,
`E2E Testing`, `Deployment Ready`, `Deployed`) for history, but no new cards are created or
routed there.

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
| CAMPPS | Done -> In Progress -> Committed -> Idea |

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

1. Start in `Idea` until the outcome/capability is admitted to the portfolio.
2. Move to `Committed` once the Objective field is set, then `In Progress` as slices build.
3. Close as `Done`.
4. Track environment promotion separately through deployment fields and deployment records.

---

## Metrics Boundaries

Cycle time starts when active ownership begins:

| Board | Start | Terminal |
|-------|-------|----------|
| Operations / Asgard | Active | Done |
| CAMPPS | In Progress | Done |

Legacy `Mount Olympus` timeline values (`In Progress`, `In Development`, `Deployed`) may be
read for history but are never used to create new cards.
