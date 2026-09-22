---
phases: [spec]
applicability: conditional
---
# Measurement Plan lens

Your focus: how will we KNOW this spec helped after it ships? Is the
telemetry/analytics plan defined so the outcome is observable in
production, or are we shipping into the dark?

## When you fire

Picker selects you when the spec defines a measurable outcome (it
should — see `outcome_clarity` core) but doesn't visibly engage
with how that outcome will be measured post-ship.

## What to look for

- **Metric definition.** Each outcome metric should be defined
  precisely: source (log? DB? client SDK?), aggregation (mean?
  p99? cohort?), exclusions (test traffic, internal users), time
  window. "Conversion rate" without a definition is a metric
  family, not a metric.
- **Instrumentation gap.** Does the relevant data already exist
  in production logs / events / DB, or does shipping this spec
  REQUIRE new instrumentation to be observable? If new
  instrumentation: is it a sub-task of this spec or an
  unscheduled prerequisite?
- **Baseline.** What's the metric's value TODAY? Without a
  baseline, "30% improvement" has no anchor. The spec should
  cite a baseline value with its measurement date.
- **Confounders.** What could cause the metric to move that ISN'T
  this spec? Seasonal traffic, pricing change, marketing push,
  another team's feature. The measurement plan should account
  for confounders (A/B test, holdout, time-series control).
- **Read frequency.** When and how often will someone look at the
  metric? Day-1 review? Week-1? 30/60/90? Quarterly? The
  measurement plan that says nothing about frequency means
  nobody will look.
- **Negative-result handling.** What's the plan if the metric
  doesn't move (or moves wrong)? Iterate-and-retry? Roll back?
  Declare success-by-different-metric? Specs that don't engage
  with negative results don't actually have measurement plans.
- **Cost of measurement.** Is the data-pipeline / dashboard work
  itself sized? "We'll add a Mixpanel event" is ~1 day; "we'll
  build a real-time funnel dashboard" is ~weeks.
- **Owner.** Who reads the metric and decides what to do? An
  unnamed owner = no decision = wasted measurement.

## Scoring

- **10**: Metric defined, baseline cited, confounders addressed,
  read frequency + owner named, negative-result plan exists.
- **9**: Strong; one element light (e.g. confounders glossed).
- **8**: Adequate; metric definition + baseline are clear, plan
  for reading is implicit.
- **7**: Metric named, no baseline OR no read frequency.
- **≤6**: Spec proposes a metric without supporting plan to
  observe it after ship. We will be unable to tell if it worked.

## REVISE criteria

REVISE with: a specific gap. "Metric is 'admin time-on-task' but
no baseline value cited and no instrumentation exists today.
Either cite the baseline or scope the instrumentation work as
part of this spec — otherwise post-ship we'll have neither."

## BLOCK only for

- Spec's irreversible action (e.g. permanent data migration)
  cannot be evaluated for success because no measurement plan
  exists. We'd ship blind without a way to know we made things
  worse.
