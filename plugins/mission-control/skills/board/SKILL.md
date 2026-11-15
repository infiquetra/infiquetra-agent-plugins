---
name: board
description: |
  Manage the Infiquetra GitHub Projects active per-project boards: CAMPPS, Sovereign Circuit,
  Infiquetra Company, Argus, Talaria, Agent Platform, Home Lab, EVE Mimir,
  Cognitive AI Research, and AI-Native Engine.
  Handles board views, status moves, item adds, terminal-item archive, WIP analysis,
  field discovery, and standup preparation.
metadata:
  when_to_use: |
    Use this skill when the user wants to:

    Board review and status:
    - Review or view any active Infiquetra per-project board state
    - Check overall board health or get a snapshot of current work
    - See what's in a specific status, such as Implementing, Ready to merge, or Blocked

    Moving items between statuses:
    - Move an issue to a different board status
    - Update an issue's board status after shaping, implementation, review, or verification

    Adding items to boards:
    - Add an issue or PR to a board with an explicit --project (required; no default)

    Archiving and cleanup:
    - Archive terminal workflow items after reviewing a dry run
    - Remove stale completed items from active board views

    WIP analysis and standup:
    - Check WIP counts and bottlenecks
    - Generate a right-to-left standup or board-review summary
    - Identify blocked or aging work
---

# SDLC Board

Manage Infiquetra's active per-project boards. No board is a default: every board operation
requires an explicit `--project` (or resolves from `project-mappings.json` via `flow discover-project`).

| Project key | Board | Project # | Workflow |
|-------------|-------|-----------|----------|
| `campps` | CAMPPS | `#4` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `sovereign-circuit` | Sovereign Circuit | `#10` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `company` | Infiquetra Company | `#11` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `argus` | Argus | `#12` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `talaria` | Talaria | `#13` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `agent-platform` | Agent Platform | `#14` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `home-lab` | Home Lab | `#15` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `eve-mimir` | EVE Mimir | `#16` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `cognitive-ai-research` | Cognitive AI Research | `#17` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |
| `ai-native-engine` | AI-Native Engine | `#18` | `Intake -> Shaping -> Planning -> Active -> Verify -> Retro` |

The former Mount Olympus (`#1`), Asgard (`#2`), and Operations (`#3`) projects are closed and
retired historical context; they are not active boards and are not routing targets. Deployment
state is not a workflow status; use deployment fields and GitHub Deployments/Environments for
environment movement.

All ten active boards follow the one shared `stage_flow` workflow recorded in
`$INFIQUETRA_SDLC_PATH/config/sdlc-schema.json`: `Stage` is the board column and `Status`
carries the in-stage condition (the cross-cutting `Blocked` status applies everywhere). No
active board carries a pause column; a paused card is expressed through labels and issue
state.

## Script Location

```bash
python3 scripts/sdlc_manager.py
```

Run that command from the mission-control package root (the directory that contains `scripts/` and `skills/`). `INFIQUETRA_SDLC_PATH` names the infiquetra-sdlc checkout the schema loader reads.
Always run the script with `python3`.

## Core Operations

### View Board

```bash
# View a board by status (--project is required; no default)
python3 sdlc_manager.py board view --project agent-platform
python3 sdlc_manager.py board view --project home-lab
python3 sdlc_manager.py board view --project campps

# Filter to a specific status
python3 sdlc_manager.py board view --project agent-platform --status "Implementing"
python3 sdlc_manager.py board view --project campps --status "Implementing"
```

### Add Item

```bash
# Add an item to a board
python3 sdlc_manager.py board add --project agent-platform --repo infiquetra-sdlc --number 42
python3 sdlc_manager.py board add --project home-lab --repo home-lab --number 42
python3 sdlc_manager.py board add --project campps --repo campps-platform --number 42
```

### Move Item

```bash
# board move writes Status (the in-stage condition), never the Stage column.
# Every board shares the one stage_flow vocabulary, so the same Status names
# are valid everywhere.
python3 sdlc_manager.py board move --project agent-platform --repo infiquetra-sdlc --number 42 --status "Implementing"
python3 sdlc_manager.py board move --project agent-platform --repo infiquetra-sdlc --number 42 --status "Discovering"
python3 sdlc_manager.py board move --project campps --repo campps-platform --number 42 --status "Implementing"
python3 sdlc_manager.py board move --project campps --repo campps-platform --number 42 --status "Ready to merge"
# Write the Stage column through flow set-field, not board move
python3 sdlc_manager.py flow set-field --project campps --repo campps-platform --number 42 --field Stage --option Verify
```

> **W6**: `board move` writes `Status` to EVERY board carrying the issue, all-or-none — a
> multi-board issue ends at one Status everywhere or nowhere. `--project` is validated as a
> carrying board, not honored as a single-board restriction. Exit remains non-zero on failure
> (#609). On an ordinary failure the already-written boards are rolled back to their prior
> values before exit 1 — BUT after a failed move, read the boards back before retrying: if the
> failure was a compensation failure, boards still disagree and the error says which board
> holds which value. Do not retry blindly.

Use `board discover-fields` when unsure which Status options exist live.

### Archive Terminal Items

```bash
# Always preview first
python3 sdlc_manager.py board archive --project campps --dry-run
python3 sdlc_manager.py board archive --project asgard --dry-run

# Run only after operator confirmation
python3 sdlc_manager.py board archive --project campps
```

The command archives terminal workflow items. All three boards share the `stage_flow`
workflow, whose only terminal status is `Ready to close`.

### WIP And Standup

```bash
python3 sdlc_manager.py board wip --project asgard
python3 sdlc_manager.py board wip --project operations
python3 sdlc_manager.py board standup --project asgard
python3 sdlc_manager.py board standup --project operations
```

Standup output walks each board right-to-left using the schema-backed workflow order.

### Discover Fields

```bash
python3 sdlc_manager.py board discover-fields --project campps
python3 sdlc_manager.py board discover-fields --project asgard
python3 sdlc_manager.py board discover-fields --project operations
```

## WIP Counts Reference

WIP limits are retired (#999): the SDLC schema defines no per-column limits, and the
hard-coded historical numbers (Operations 10/5, Asgard 8/5) went with them. `board wip`
reports a count per status and no limit; `board view` prints plain counts without limit
decoration.

When a column's count grows past what can actually be finished, stop pulling new work on
that board and focus on finishing, swarming, or leaving cards in `Blocked`. No active
board carries a pause column; a paused card is expressed through labels and issue state,
not a workflow status.

## Natural Language Examples

**"Review the Asgard board"**
-> `board view --project asgard`

**"Move issue #42 in infiquetra-sdlc to Implementing on Asgard"**
-> `board move --project asgard --repo infiquetra-sdlc --number 42 --status "Implementing"`

**"Add this issue to Operations"**
-> Confirm repo and issue number, then `board add --project operations --repo <repo> --number <N>`

**"How much WIP is on the board?"**
-> Run `board wip` for the relevant board; it shows a count per status (no limits).

**"Let's prep for standup"**
-> `board standup --project <the requested active board>` (`--project` is required).

## Reference Documents

- `references/kanban-workflow.md` - Board structure, stage and status definitions, and standup format
- `references/graphql-queries.md` - GraphQL queries used by the script
