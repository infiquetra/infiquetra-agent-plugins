---
name: board
description: Quick board status view with WIP check for Infiquetra project boards
---

Show current status for an Infiquetra project board, including WIP counts, aging items,
and blockers.

## Usage

```
/board --project <operations|asgard|campps>
```

## Arguments

- `--project` (required) - Active board to show. No default; the command errors with the
  active-board list (Operations / Asgard / CAMPPS) if omitted.
- `operations` - Jeff's intent and shaping board.
- `asgard` - Asgard rapid-action/incubation board.
- `campps` - CAMPPS initiative execution board (initiative-scoped; archived on completion).

## What This Does

1. Fetches items from the selected GitHub Project.
2. Groups items by schema-backed Status.
3. Shows WIP counts and violations where configured.
4. Flags aging and blocked items.
5. Keeps deployment state separate from workflow Status.

## Examples

```
/board --project operations
/board --project asgard
/board --project campps
```

## Script Commands

```bash
SCRIPT=~/.claude/plugins/cache/infiquetra-plugins/mission-control/2.1.0/scripts/sdlc_manager.py

python3 $SCRIPT board view --project operations
python3 $SCRIPT board wip --project operations
```

Replace `operations` with `asgard` or `campps` for those boards.

## Instructions

When the user invokes `/board --project <project>`:

1. Require an explicit `--project`. If omitted, error and list the active boards
   (Operations / Asgard / CAMPPS); never default to a board.
2. Run `board view --project <project>`.
3. Run `board wip --project <project>`.
4. Summarize items by status, WIP violations, blockers, and aging work.
5. Suggest concrete follow-up actions when useful: standup prep, move cards, or dry-run archive.

Use the `board` skill for detailed board operations or the `sdlc-operator` agent for
multi-step workflows.
