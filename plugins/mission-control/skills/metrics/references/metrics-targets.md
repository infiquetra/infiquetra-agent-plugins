# SDLC Flow Metrics Reference

Quick reference for Infiquetra board-flow metrics. Source of truth:
`$INFIQUETRA_SDLC_PATH/config/sdlc-schema.json`,
`$INFIQUETRA_SDLC_PATH/docs/process/metrics-guide.md`, and
`$INFIQUETRA_SDLC_PATH/docs/process/kanban-workflow.md`.

---

## Cycle Time

**Definition**: Time from first active ownership to terminal workflow status.

| Board | Start | Terminal |
|-------|-------|----------|
| Operations / Asgard / CAMPPS | `Active` stage | `Ready to close` |

> **How the start boundary is actually detected.** `_cycle_start_statuses` in
> `scripts/sdlc_manager.py` returns the literal option name `Active`, and the
> timeline query it feeds (`QUERY_GET_ISSUE_TIMELINE`) captures only the option
> *name* of a single-select change — it records no field name or id, so it cannot
> tell a `Stage` change from a `Status` change. `Active` is a live `Stage` option
> on all three boards and is not a `Status` option at all, so the start boundary is
> whichever field first carried an option named `Active`. That is close to the
> boundary this table declares, but it is matched by name rather than by field.
> Making the field explicit is outside issue #1020, whose scope is the cached
> census and the prose describing it.


Legacy (read-only history): the retired `Mount Olympus` board used its own start status with
`Done`/`Closed`/`Cancelled` terminals; its history may include `In Progress`, `In Development`,
or `Deployed`. Tooling reads those for historical calculations only and creates no new movement
with those names.

**Measurement**: P50, P85, and P95 via GitHub timeline events
(`ProjectV2ItemFieldValueEvent` on the Status field).

### Targets by Issue Type

| Type | P85 Target | SLA if applicable |
|------|------------|-------------------|
| Capability | < 5 days | -- |
| Enhancement | < 2 days | -- |
| Defect | < 1 day | Critical: 4 hours; high: 1 day; medium: 3 days |
| Exploration | < 3 days | -- |
| Context Update | < 1 day | -- |

---

## Throughput

**Definition**: Number of work items moved to a terminal workflow status per week.

**Use**: Capacity planning, delivery forecasting, and trend analysis.

| Board | Counted terminal status |
|-------|-------------------------|
| Operations / Asgard / CAMPPS | `Ready to close` |

---

## WIP Age

**Definition**: How long current active items have been in their current Status.

**Use**: Identify stale work, trigger escalation, and surface bottlenecks.

| Board | Status | Threshold |
|-------|--------|-----------|
| Operations / Asgard / CAMPPS | every non-terminal Status | > 3 days |

`_active_age_thresholds` in `scripts/sdlc_manager.py` derives this from the
workflow: every stage-flow Status that is not terminal, at three days. The
boards are not split and no board carries a longer threshold.

---

## Flow Efficiency

**Definition**: Active work time divided by total cycle time.

All three boards share one ladder: active work is the `Active` and `Verify`
stages. `Intake`, `Shaping` and `Planning` are wait or preparation states
unless a card's evidence shows otherwise.

Target: greater than 50%.

---

## How to Read Metrics

### When Cycle Time Is Over Target

1. Run `metrics column-time` on slow items.
2. Check WIP age for active or review bottlenecks.
3. Look for `Blocked`, `Needs clarification`, or missing Jeff decision signals.
4. Confirm deployment delay is not being misread as workflow delay.
5. Use a longer `--days` window to separate noise from a trend.

### When Throughput Is Low

1. Check how much work sits in the `Active` stage at once.
2. Look at active-status aging.
3. Check if `Ready for Planning` is empty or poorly shaped.
4. Look at defect rate and unplanned work.
5. Consider whether large capabilities should be split.

### When WIP Age Is High

1. Identify the specific cards and discuss them in board review.
2. Add or confirm `blocked` / `Needs clarification` state where appropriate.
3. Swarm, split, or move the card back to shaping if the issue is not actually ready.

---

## Metrics Quick Reference

| Metric | Command | Key flag |
|--------|---------|----------|
| Cycle time all types | `metrics cycle-time --project campps` | `--days N` |
| Cycle time by type | `metrics cycle-time --project campps --type capability` | `--type` |
| Throughput | `metrics throughput --project asgard` | `--weeks N` |
| WIP age | `metrics wip-age --project operations` | -- |
| Status breakdown | `metrics column-time --project campps --number 42` | `--number` |
