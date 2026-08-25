---
name: board
description: |
  Manage the Infiquetra GitHub Projects active boards: Operations, Asgard, and CAMPPS.
  Handles board views, status moves, item adds, terminal-item archive, WIP analysis,
  field discovery, and standup preparation.
metadata:
  when_to_use: |
    Use this skill when the user wants to:

    Board review and status:
    - Review or view Operations, Asgard, or CAMPPS board state
    - Check overall board health or get a snapshot of current work
    - See what's in a specific status, such as Shaping, Active, or In Progress

    Moving items between statuses:
    - Move an issue to a different board status
    - Update an issue's board status after shaping, implementation, review, or verification

    Adding items to boards:
    - Add an issue or PR to a board with an explicit --project (required; no default)

    Archiving and cleanup:
    - Archive terminal workflow items after reviewing a dry run
    - Remove stale completed items from active board views

    WIP analysis and standup:
    - Check WIP limits and bottlenecks
    - Generate a right-to-left standup or board-review summary
    - Identify blocked or aging work
---

# SDLC Board

Manage Infiquetra's active project boards. No board is a default: every board operation
requires an explicit `--project`.

| Project key | Board | Workflow |
|-------------|-------|----------|
| `operations` | Operations | `Idea -> Shaping -> Ready -> Active -> Verify -> Done` |
| `asgard` | Asgard | `Idea -> Shaping -> Ready -> Active -> Verify -> Done` |
| `campps` | CAMPPS | `Idea -> Committed -> In Progress -> Done` (pause: `Parked`) |

The former project #1 (Mount Olympus) is retired-historical and closed; it is not an active
board and is not a routing target. Deployment state is not a workflow status; use deployment
fields and GitHub Deployments/Environments for environment movement.

## Script Location

```bash
$INFIQUETRA_SDLC_PATH/../infiquetra-claude-plugins/plugins/mission-control/scripts/sdlc_manager.py
```

If `$INFIQUETRA_SDLC_PATH` is unset, use `~/workspace/infiquetra/infiquetra-sdlc` as the default base path.
Always run the script with `python3`.

## Core Operations

### View Board

```bash
# View a board by status (--project is required; no default)
python3 sdlc_manager.py board view --project operations
python3 sdlc_manager.py board view --project asgard
python3 sdlc_manager.py board view --project campps

# Filter to a specific status
python3 sdlc_manager.py board view --project asgard --status "Active"
python3 sdlc_manager.py board view --project campps --status "In Progress"
```

### Add Item

```bash
# Add an item to a board (--project is required; no default routing)
python3 sdlc_manager.py board add --project asgard --repo infiquetra-sdlc --number 42
python3 sdlc_manager.py board add --project operations --repo infiquetra-sdlc --number 42
python3 sdlc_manager.py board add --project campps --repo athena-service --number 42
```

### Move Item

```bash
# Intent-flow boards (Operations / Asgard)
python3 sdlc_manager.py board move --project asgard --repo infiquetra-sdlc --number 42 --status "Active"
python3 sdlc_manager.py board move --project operations --repo infiquetra-sdlc --number 42 --status "Shaping"

# CAMPPS initiative flow
python3 sdlc_manager.py board move --project campps --repo athena-service --number 42 --status "Committed"
python3 sdlc_manager.py board move --project campps --repo athena-service --number 42 --status "In Progress"
python3 sdlc_manager.py board move --project campps --repo athena-service --number 42 --status "Done"
```

Use `board discover-fields` when unsure which Status options exist live.

### Archive Terminal Items

```bash
# Always preview first
python3 sdlc_manager.py board archive --project campps --dry-run
python3 sdlc_manager.py board archive --project asgard --dry-run

# Run only after operator confirmation
python3 sdlc_manager.py board archive --project campps
```

The command archives terminal workflow items. For Operations and Asgard that means `Done`.
For CAMPPS that means `Done`.

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

## WIP Limits Reference

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
When WIP is exceeded, stop pulling new work on that board and focus on finishing, swarming,
or moving blocked cards to the right pause state.

## Natural Language Examples

**"Review the Asgard board"**
-> `board view --project asgard`

**"Move issue #42 in infiquetra-sdlc to Active on Asgard"**
-> `board move --project asgard --repo infiquetra-sdlc --number 42 --status "Active"`

**"Add this issue to Operations"**
-> Confirm repo and issue number, then `board add --project operations --repo <repo> --number <N>`

**"Are we over WIP limits?"**
-> Run `board wip` for the relevant board.

**"Let's prep for standup"**
-> `board standup --project <the requested active board>` (`--project` is required).

## Reference Documents

- `references/kanban-workflow.md` - Board structure, status definitions, WIP limits, and standup format
- `references/graphql-queries.md` - GraphQL queries used by the script
