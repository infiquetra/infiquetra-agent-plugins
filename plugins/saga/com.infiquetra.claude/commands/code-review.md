---
name: code-review
description: Run saga's review command and show the round's grades and findings
argument-hint: "[diff, branch, PR, or scope]"
---

Load `saga/skills/code-review/SKILL.md` and follow the review-command flow:
`review_command.py prepare`, the targeted reviewer through orchestrate, then
`review_command.py finish`. Show and publish through `review_state.py`, bound to the reviewed
revision. Saga's review records, grade formula and calibration own the outcome; the command
never changes a grade or repairs the implementation.

Every lens at C or better goes to merge confirmation. A repair round leaving the same blocking
items stops early, and round 3 is the limit. A stopped review waits for the operator's recorded
merge-with-reason decision with linked defect issues, or stop-card. Reproduced data loss or
security exposure always blocks merge, including in a report-only lens. Fix-later choices do not
hold merge. A stale revision returns through the combined-branch functional run before review.

In an active saga, keep the existing run and durable evidence; never mint or advance a lifecycle
phase just because this command was invoked. Follow the skill's publication and authority rules.

Arguments provided to the command:

`$ARGUMENTS`
