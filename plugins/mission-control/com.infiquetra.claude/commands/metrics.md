---
name: metrics
description: Show flow metrics for Infiquetra project boards
---

Display a flow metrics dashboard for an Infiquetra project board: cycle time,
throughput, WIP age, and bottleneck hints.

## Usage

```
/metrics --project <operations|asgard|campps> [--type metric-type]
```

## Arguments

- `--project` (required) - Active board: `operations`, `asgard`, or `campps`. No default;
  the command errors with the active-board list (Operations / Asgard / CAMPPS) if omitted.
- `--type` - Optional metric type: `cycle-time`, `throughput`, `wip-age`, or `all` (default)

## What This Does

1. Shows cycle time percentiles against targets.
2. Shows terminal-status throughput.
3. Shows WIP age for current active items.
4. Flags metrics that are over target.
5. Separates workflow Status from deployment environment state.

## Examples

```
/metrics --project operations
/metrics --project asgard --type throughput
/metrics --project campps --type wip-age
```

## Script Commands

```bash
SCRIPT=~/.claude/plugins/cache/infiquetra-plugins/mission-control/2.1.0/scripts/sdlc_manager.py

python3 $SCRIPT metrics cycle-time --project operations --days 30
python3 $SCRIPT metrics throughput --project asgard --weeks 4
python3 $SCRIPT metrics wip-age --project campps
```

## Instructions

When the user invokes `/metrics --project <project> [--type metric-type]`:

1. Require an explicit `--project`. If omitted, error and list the active boards
   (Operations / Asgard / CAMPPS); never default to a board.
2. Determine which metrics to show, defaulting to all.
3. Run the matching metric commands.
4. Summarize pass/fail signals, bottlenecks, and concrete next actions.

Use the `metrics` skill for detailed interpretation or the `sdlc-operator` agent for
multi-step SDLC health reports.
