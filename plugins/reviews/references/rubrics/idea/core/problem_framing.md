---
phases: [idea]
applicability: always
---
# Problem Framing lens

Your focus: is the stated problem the actual problem worth solving, or
a proxy that will steer everything downstream off-course?

The earlier the lifecycle, the cheaper a framing fix. By the time a
spec is written, framing errors have ossified into outcome
definitions; by the time issues are filed, into acceptance criteria.
Catch them HERE.

## What to look for

- **Symptom vs. root.** Does the blueprint frame a symptom users
  complain about, or the underlying mechanism producing the symptom?
  "Users want faster checkout" is a symptom; "checkout requires 7
  manual steps when 3 would do" is closer to root.
- **Whose problem.** Is the user/persona named, or is the problem
  generic ("users struggle with...")? A generic-sounding problem
  often means no specific user has it.
- **Counterfactual.** If this problem went unsolved for another year,
  who specifically suffers, and how? If the answer is "nobody really,
  it's just a thing we'd like to do" — the framing should say so.
- **Proxy detection.** Is the problem stated in terms of a goal
  (revenue, retention, NPS) that the team can't directly affect, or
  in terms of a user experience the team CAN affect? Goals belong
  in objectives; problems belong in user-affordance terms.
- **Inherited framing.** Is this someone's else's framing carried
  over uncritically (a competitor's positioning, an industry
  whitepaper, a prior project's premise)? Inherited framing is
  particularly dangerous because it's pre-validated-feeling without
  actually being validated for THIS context.
- **Falsification path.** What evidence would prove the framing
  wrong? If nothing could, the framing is unfalsifiable mush.

## Scoring

- **10**: Framing names a specific user, a specific affordance gap,
  and what evidence would falsify the framing. Hard to drift from.
- **9**: Strong framing; minor specificity gap (e.g. user persona is
  named but not characterized).
- **8**: Reasonable framing for an early blueprint. The downstream
  team can sharpen it during spec-writing.
- **7**: Framing leans heavily on a proxy or symptom; will need
  explicit redirection before specs descend cleanly.
- **≤6**: Framing is genericized, inherited without examination, or
  unfalsifiable. Specs descending from this will be ungrounded.

## REVISE criteria

REVISE with: a specific question the framing should answer ("who
specifically experiences this problem and how often?") OR a specific
re-framing suggestion ("frame in terms of the affordance gap, not the
revenue impact").

## BLOCK only for

- Framing solves a problem the named user demonstrably does NOT
  have (verifiable by 1 user-research datum the blueprint contains
  or omits).
