---
name: metrics
description: |
  Flow metrics and analysis for Infiquetra project boards using GitHub timeline events.
  Provides cycle time, throughput, WIP age, per-status time breakdowns, and interpretation
  guidance across Operations, Asgard, and CAMPPS.
metadata:
  when_to_use: |
    Use this skill when the user wants to:

    Cycle time analysis:
    - "how long are issues taking", "what's our cycle time", "how fast are we delivering"
    - "cycle time report", "are we hitting our cycle time targets"
    - "how long did this capability take", "how long has issue #42 been active"

    Throughput analysis:
    - "how many capabilities did we complete last week", "weekly delivery rate"
    - "throughput this month", "how many items reached Done"

    WIP age and aging work:
    - "how old are our active items", "what's stale", "aging work items"

    Flow health:
    - "how's our flow", "where's the bottleneck", "which status is slowest"
---

# SDLC Metrics

Flow metrics for Infiquetra's GitHub Projects boards. Metrics use GitHub timeline events
for Status changes. Deployment state is intentionally separate from workflow Status; use
deployment records and deployment fields for environment promotion questions.

## Script Location

```bash
$INFIQUETRA_SDLC_PATH/../infiquetra-claude-plugins/plugins/mission-control/scripts/sdlc_manager.py
```

If `$INFIQUETRA_SDLC_PATH` is unset, use `~/workspace/infiquetra/infiquetra-sdlc` as the default base path.
Always run the script with `python3`.

## Metric Boundaries

| Board | Active start | Terminal statuses |
|-------|--------------|-------------------|
| Operations | Active | Done |
| Asgard | Active | Done |
| CAMPPS | In Progress | Done |

Legacy (read-only history): the retired `Mount Olympus` board used `Assigned` as active start
with `Done`/`Closed`/`Cancelled` terminals, and its timeline may include `In Progress`,
`In Development`, or `Deployed`. The CLI reads those values for historical continuity only;
new cards use the active boards above.

## Core Operations

### Cycle Time

```bash
python3 sdlc_manager.py metrics cycle-time --project campps
python3 sdlc_manager.py metrics cycle-time --project asgard --days 14
python3 sdlc_manager.py metrics cycle-time --project campps --type capability
```

Cycle time is calculated from the first active-start status to a terminal status.

### Throughput

```bash
python3 sdlc_manager.py metrics throughput --project campps
python3 sdlc_manager.py metrics throughput --project asgard --weeks 8
```

Throughput counts items that reached a terminal workflow status during the reporting window.

### WIP Age

```bash
python3 sdlc_manager.py metrics wip-age --project campps
python3 sdlc_manager.py metrics wip-age --project operations
```

WIP age shows current items in active statuses and flags entries over the configured thresholds.

### Per-Status Time Breakdown

```bash
python3 sdlc_manager.py metrics column-time --project campps --number 42
```

Use this to diagnose where one card spent time.

## Targets

### Cycle Time Targets (P85)

| Issue Type | P85 Target | Notes |
|------------|------------|-------|
| Capability | < 5 days | Active ownership through terminal status |
| Enhancement | < 2 days | Smaller scope |
| Defect | < 1 day | Highest urgency |
| Exploration | < 3 days | Timeboxed research |
| Context Update | < 1 day | Documentation or context maintenance |

### WIP Age Thresholds

| Board | Status | Flag if age > |
|-------|--------|---------------|
| Operations / Asgard | Active | 3 days |
| Operations / Asgard | Verify | 3 days |
| CAMPPS | In Progress | 5 days |

## Natural Language Examples

**"What's our cycle time for capabilities this month?"**
-> `metrics cycle-time --project campps --type capability --days 30`

**"How many items did Asgard complete recently?"**
-> `metrics throughput --project asgard --weeks 4`

**"How old are our active items?"**
-> `metrics wip-age --project campps`

**"How long has issue #42 been active?"**
-> `metrics column-time --project campps --number 42`

## Interpreting Results

### When Cycle Time Is Over Target

1. Run `metrics column-time` on slow items to find the status consuming the most time.
2. Check WIP age for active or review bottlenecks.
3. Look for `blocked` or `Needs Question` state.
4. Check whether WIP limits are being respected.
5. Separate deployment delay from work status; deployment evidence belongs to deployment fields.

### When Throughput Is Low

1. Check whether active statuses are at or over WIP.
2. Look for aging items that are not moving to review or verification.
3. Check whether `Ready` is empty or poorly shaped.
4. Confirm the board is the right one: raw intent should not be counted as initiative execution.

### When WIP Age Is High

1. Identify the specific cards and ask what decision, context, or reviewer is missing.
2. Move truly blocked cards to the right pause state.
3. Swarm or split work that is too large.

## Reference Documents

- `references/metrics-targets.md` - Complete targets, definitions, and interpretation guide
- `skills/board/references/kanban-workflow.md` - Board workflows and WIP limits
