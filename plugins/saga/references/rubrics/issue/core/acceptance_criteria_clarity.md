---
phases: [issue]
applicability: always
---
# Acceptance Criteria Clarity lens

Your focus: are the ACs tight enough that the agent and the PR
reviewer would reach the SAME verdict from the AC text alone?

This is the issue-level analog to spec's `acceptance_testability` —
sharper, because issues are what an agent actually plans against,
and what a PR reviewer actually verifies. Ambiguous ACs at issue
phase produce R2/R3 review loops where reviewers disagree about
whether AC X is satisfied.

## What to look for

- **Pass/fail unambiguous.** Each AC should have a clear
  pass/fail test. "AC: form validates input" is not a pass/fail
  test — what counts as validation? "AC: form displays inline
  error message when email field is empty on submit" is.
- **Observable artifact.** What artifact (file change, log line,
  DB row, API response, UI screenshot, test name) constitutes
  evidence of AC satisfaction? An AC with no nameable artifact
  is reviewer-subjective.
- **Reviewer-text identical.** Imagine reading just the AC text
  with no other context. Could you, as a reviewer, write a
  test for this? If not, the AC is not concrete enough.
- **Negative-case bounded.** Each AC should bound what it does
  NOT cover. "AC: input field accepts emails" — what about
  invalid emails? International characters? Empty strings? The
  AC should specify or the reviewer will have to invent.
- **Quantitative ACs need methodology.** "Latency under 500ms" —
  measured how? from where? at what percentile? on what
  hardware? Quantitative ACs without methodology are not
  testable, even at issue level.
- **Test mention.** Modern issue ACs often name the test that
  would prove satisfaction ("AC: tests/e2e/registration.test.ts
  passes the new registration-flow scenario"). This is the
  strongest form.
- **AC count + balance.** Issues with 1-3 ACs are usually
  under-spec'd; >8 ACs are usually over-bundled (multiple issues
  in disguise). Sweet spot 4-7 for most issues.
- **Cross-AC overlap.** Two ACs shouldn't ambiguously test the
  same thing. Each AC adds a distinct testable property.

## Scoring

- **10**: Each AC has pass/fail criterion, observable artifact,
  negative-case bound, methodology where quantitative,
  reviewer-text-self-sufficient.
- **9**: Strong; one AC has thin methodology.
- **8**: Adequate; load-bearing ACs are clear, secondary ACs
  could sharpen.
- **7**: Multiple ACs are vague or imply subjective verdicts.
- **≤6**: ACs are direction-without-threshold, or one-line
  fragments that nobody could test from.

## REVISE criteria

REVISE with: a specific fuzzy AC + a proposed sharper version.
"AC #2 'login feels fast' — fuzzy. Suggest: 'login p95 wall-clock
from form-submit to authenticated-redirect is < 800ms on the
staging environment with 50 concurrent simulated users.'"

## BLOCK only for

- Issue has zero ACs (work is undefined).
- ACs reference internal contradictions (AC #1 requires X, AC #4
  forbids X) — issue is incoherent.
