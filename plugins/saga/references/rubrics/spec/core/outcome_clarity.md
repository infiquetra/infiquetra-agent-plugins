---
phases: [spec]
applicability: always
---
# Outcome Clarity lens

Your focus: is the spec's desired outcome stated as something
measurable, with a clear "we hit it" condition? Or is it stated
in terms of activity ("we'll build X") that doesn't tell you
whether shipping helped?

Specs that conflate output (built X) with outcome (X improved a
metric) silently absorb energy without delivering value. Catch the
conflation at spec time, when the cost is a sentence rewrite.

## What to look for

- **Output vs. outcome.** Output: "we'll ship the new dashboard."
  Outcome: "admins find the activity they need within 30 seconds
  on the new dashboard, vs. 90 seconds today." Specs should lean
  outcome.
- **Measurability.** Is the outcome stated with units? "Faster"
  is not measurable. "Median time-to-first-meaningful-paint <
  500ms on a Camp Director workflow" is.
- **Direction + threshold.** A measurable outcome has both: which
  way is good (lower latency, higher conversion) AND a threshold
  ("under 500ms," "above 30%"). Direction without threshold means
  any movement counts as success.
- **Outcome window.** Over what time window does the outcome hold?
  Day 1 post-launch? 90-day cohort? Steady state? Different
  windows imply different validation strategies.
- **Counterfactual reasoning.** Could the outcome be hit by
  accident (e.g. seasonality, unrelated changes)? If yes, the
  spec needs an isolation strategy (A/B, holdout, attribution).
- **Unintended consequences ack.** Does the spec acknowledge
  outcomes that COULD GET WORSE if it succeeds? "Faster checkout
  may reduce returns by reducing buyer's-remorse window — is
  that fine?" A spec that only lists upside is incomplete.
- **One outcome per spec.** Multi-outcome specs are usually multi-
  spec disguised as one. (See `scope_unity` extras for deeper.)

## Scoring

- **10**: Single outcome, measurable, threshold + direction +
  window + isolation strategy + unintended-consequences ack.
- **9**: Strong; one element thin (e.g. window unspecified).
- **8**: Adequate for a small spec; can sharpen at issue
  decomposition time.
- **7**: Outcome is direction-without-threshold or output-stated
  pretending to be outcome.
- **≤6**: Spec describes activity (what we'll build) without
  describing what success looks like in terms anyone could
  verify.

## REVISE criteria

REVISE with: a specific weak outcome statement and a proposed
sharper version. "Section 2 says 'reduce admin frustration' —
unmeasurable. Suggest: 'within the camp-roster-building workflow,
median click-count from new-camper-form to roster-saved drops
from 23 today to 12 by 90 days post-launch.'"

## BLOCK only for

- Spec describes an outcome that contradicts the parent
  blueprint's stated outcome direction (e.g. blueprint optimizes
  for safety; spec optimizes for speed at safety's expense).
