---
phases: [spec]
applicability: always
---
# Acceptance Testability lens

Your focus: can each acceptance criterion be tested without
subjective judgment? If two competent reviewers couldn't reach the
same verdict from the AC text alone, the AC is fuzzy and will cause
rework when it descends into issues.

This is the strictest version of "ACs should be clear" — applied at
spec time when fuzz can still be removed cheaply.

## What to look for

- **Binary verdicts.** Each AC should have a clear pass/fail.
  "Performance is good" — not binary. "p99 latency under load
  scenario L is < 500ms" — binary.
- **Observable artifacts.** What artifact (log line, DB row, API
  response, UI element, screenshot) constitutes evidence of AC
  satisfaction? An AC with no nameable artifact is hard to test.
- **Negative cases.** Does each AC have a corresponding "and these
  scenarios are NOT handled by this AC" clause? Specs without
  negative-case bounding produce scope creep at issue time.
- **Quantitative ACs need methodology.** "Latency < 500ms" needs
  to specify: under what load? measured from where? at what
  percentile? over what window? Quantitative ACs without
  methodology are not testable.
- **Behavioral ACs need triggers.** "When user does X, the system
  Y" — both X and Y need to be specific enough to script.
- **Test-equivalence.** Two ACs shouldn't ambiguously test the
  same thing or contradict each other. Each AC adds a distinct
  testable property.
- **AC dependencies.** Does AC #5 implicitly depend on AC #2's
  artifact existing first? If yes, the spec should make that
  ordering explicit.
- **Missing AC categories.** Most specs need at least: functional
  ACs (what works), non-functional ACs (performance, reliability,
  security), data ACs (state at rest), operational ACs (alerts,
  metrics, runbook hooks). Categories missing entirely is a sign.

## Scoring

- **10**: Every AC binary, with named observable artifact,
  methodology where quantitative, negative-case bounding, no
  ambiguity between ACs.
- **9**: Strong; one AC with thin methodology.
- **8**: Adequate; the load-bearing ACs are testable, secondary
  ones could sharpen.
- **7**: Multiple ACs are direction-without-threshold or have
  un-named artifacts.
- **≤6**: Most ACs are subjective ("user-friendly," "fast,"
  "robust") with no path to test.

## REVISE criteria

REVISE with: a specific fuzzy AC + a proposed testable version.
"AC #3 'parents can easily find their camper's allergies' — fuzzy.
Testable: 'parent navigates from home → camper roster → camper
detail → allergies section in ≤ 4 clicks; allergy data appears
within 200ms of clicking; allergy data matches the data entered
at registration time.'"

## BLOCK only for

- Spec has zero quantitative ACs and the parent blueprint's
  outcome was quantitative. The descent broke.
