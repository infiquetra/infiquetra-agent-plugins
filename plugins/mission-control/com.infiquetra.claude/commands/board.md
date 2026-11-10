---
name: board
description: Quick board status view with WIP check for Infiquetra project boards
---

Show current status for an Infiquetra project board, including WIP counts, aging items,
and blockers.

## Usage

```
/board --project <campps|sovereign-circuit|company|argus|talaria|agent-platform|home-lab|eve-mimir|cognitive-ai-research|ai-native-engine>
```

## Arguments

- `--project` (required) - Active per-project board key (`campps`, `sovereign-circuit`, `company`,
  `argus`, `talaria`, `agent-platform`, `home-lab`, `eve-mimir`, `cognitive-ai-research`, or
  `ai-native-engine`). No default; the command errors with the active-board list if omitted.

## What This Does

1. Fetches items from the selected GitHub Project.
2. Groups items by schema-backed Status.
3. Shows WIP counts and violations where configured.
4. Flags aging and blocked items.
5. Keeps deployment state separate from workflow Status.

## Examples

```
/board --project agent-platform
/board --project home-lab
/board --project campps
```

## Script Commands

```bash
SCRIPT="$CLAUDE_PLUGIN_ROOT/scripts/sdlc_manager.py"

python3 $SCRIPT board view --project agent-platform
python3 $SCRIPT board wip --project agent-platform
```

Replace `agent-platform` with any active per-project board key.

## Instructions

When the user invokes `/board --project <project>`:

1. Require an explicit `--project`. If omitted, error and list the active per-project boards;
   never default to a board.
2. Run `board view --project <project>`.
3. Run `board wip --project <project>`.
4. Summarize items by status, WIP violations, blockers, and aging work.
5. Suggest concrete follow-up actions when useful: standup prep, move cards, or dry-run archive.

Use the `board` skill for detailed board operations or the `sdlc-operator` agent for
multi-step workflows.
