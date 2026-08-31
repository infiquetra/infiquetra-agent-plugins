---
name: triage
description: Triage an existing GitHub issue with label recommendations, priority assessment, and project board placement
---

Triage an existing issue by analyzing its content, recommending appropriate labels and priority, adding it to the project board, and moving it to the correct status.

## Usage

```
/triage repo#number
```

## Arguments

- `repo#number` — Repository and issue number, e.g., `athena-service#42`

## What This Does

1. Reads the issue content (title, body, existing labels)
2. Recommends issue type label if missing
3. Recommends priority label for defects
4. Recommends Initiative/Objective project field values based on context
5. Applies auto-label rules
6. Adds to project board if not already there
7. Sets project fields when the target board exposes them
8. Recommends initial board status (Ready if context complete, Backlog or Shaping if missing context)

## Examples

```
/triage athena-service#42
/triage hermes-gateway#15
/triage apollo-engine#89
```

## Script Commands

```bash
SCRIPT="$CLAUDE_PLUGIN_ROOT/scripts/sdlc_manager.py"

# Auto-label based on content
python3 $SCRIPT labels auto-label --repo athena-service --number 42

# Add to the named active board (--project is required; no default)
python3 $SCRIPT board add --project asgard --repo athena-service --number 42

# Set project fields directly when needed
python3 $SCRIPT flow set-field --project asgard \
  --repo athena-service --number 42 \
  --field Status --option Ready
```

## Instructions

When the user invokes `/triage repo#number`:

1. Parse repo and number from the argument (format: `repo#number` or `repo #number`)
2. Fetch issue via `gh issue view <number> --repo infiquetra/<repo> --json title,body,labels`
3. Analyze content:
   - Is there already a type label? If not, recommend one using the decision tree
   - Is it a defect without a priority? Ask user for priority (critical/high/medium/low)
   - Does title/body mention an initiative or objective? Suggest project field values
4. Apply auto-label rules:
   - `python3 $SCRIPT labels auto-label --repo <repo> --number <N>`
5. Manually apply recommended labels when the template did not apply them:
   - `gh issue edit <N> --repo infiquetra/<repo> --add-label "capability,needs-plan"`
6. Add to the named active board (`--project` is required; ask which board if unstated):
   - `python3 $SCRIPT board add --project <operations|asgard|campps> --repo <repo> --number <N>`
7. Set initiative/objective fields when applicable:
   - `python3 $SCRIPT flow set-field --project <board> --repo <repo> --number <N> --field Initiative --option <name>`
   - `python3 $SCRIPT flow set-field --project <board> --repo <repo> --number <N> --field Objective --option <name>`
8. Recommend status:
   - Defect (critical/high): move to Active on Operations or Asgard (or In Progress on CAMPPS)
   - Has complete context: Ready
   - Needs more context: keep `needs-plan` on actionable cards, optionally add `needs-context`,
     and leave in Backlog or Shaping
9. Show summary of all actions taken

If the issue is a defect with `critical` label, flag urgency: "This is a critical defect with a 4-hour SLA. Moving to active ownership now."

Use the `sdlc-operator` agent for batch triage of multiple issues.
