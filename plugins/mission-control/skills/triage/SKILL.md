---
name: triage
description: |
  Triage an existing GitHub issue: recommend a type label, a defect priority, and
  Initiative or Objective field values, then add the issue to an active board.
  The Claude command lives in the adapter; this skill runs the same script.
---

# Triage

Read an existing issue and place it. Nothing here creates the issue. Creation
is the `issues` skill.

Run the commands from the mission-control package root (the directory that
contains `scripts/` and `skills/`). GitHub access goes through the `gh` CLI.
`GH_TOKEN` and `GITHUB_TOKEN` are the credentials `gh` reads; this skill does
not print their values. Advisory judgments (`--suggest`) also need
`TYPESAFE_API_KEY`. When that variable is unset, `--suggest` prints the
rule-derived result and does not fail the command.

## Commands

```bash
python3 scripts/sdlc_manager.py labels auto-label --repo <repo> --number <N>
python3 scripts/sdlc_manager.py labels auto-label --repo <repo> --number <N> --suggest
python3 scripts/sdlc_manager.py board add --project <operations|asgard|campps> --repo <repo> --number <N>
python3 scripts/sdlc_manager.py flow set-field --project <board> --repo <repo> --number <N> --field Initiative --option <name>
python3 scripts/sdlc_manager.py flow set-field --project <board> --repo <repo> --number <N> --field Objective --option <name>
python3 scripts/sdlc_manager.py board move --project <board> --repo <repo> --number <N> --status "Ready for Planning"
```

`--project` is required. `board move` writes Status on every board that
carries the issue. When the recommended Status belongs to a different Stage,
set Stage with `flow set-field --field Stage` as well. Stage and Status names
are in `skills/board/references/kanban-workflow.md`.

`--suggest` on `labels auto-label` prints a widen-only union of the
rule-derived labels and a typed judgment. It applies nothing.

## Claude adapter

The `/triage` command is `com.infiquetra.claude/commands/triage.md`. It calls
the same script through `$CLAUDE_PLUGIN_ROOT/scripts/sdlc_manager.py`.
