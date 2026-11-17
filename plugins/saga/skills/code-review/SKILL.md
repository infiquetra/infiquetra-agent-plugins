---
name: code-review
description: Review a frozen combined branch through the Saga review command, launch the targeted reviewer through Orchestrate, compute C1 grades and merge state, and render or publish the stored review. Triggers on "review this PR", "code review", "check my diff", or a /work hand-in before shipping.
---

# Code Review

Run the prepared-packet review after the combined-branch build loop passes and before release.
Follow the [saga/references/formatting-style.md](../../references/formatting-style.md) for review documents.
The review command computes grades, stable finding identities and the merge answer. The reviewer
supplies evidence; Work applies repairs. Keep the reviewed revision fixed throughout a round.

## Phase 0 — Read the run and verify the branch

Resolve the issue's run record and intent envelope. Read the active plan and
[Built vs Planned](references/built-vs-planned.md), and compare the delivered change with that intent.
A stored review from the retired flow restarts at round one; its history remains stored and unread.
Use `review_state.next_review_action(record, envelope=..., current_revision=...)` to select the
next round and action. Do not infer a round number from the length of `review_cycles`.

Every entry into review first passes the combined-branch loop, including repair submissions:

```bash
python3 plugins/saga/scripts/build_loop.py --record <run-record> \
  --repo-root <combined-checkout> --handoff --revision "$REVIEWED_SHA"
```

Use the full revision returned by that handoff. If it reports no passing combined-branch functional
run and no waiver, stop and name the missing evidence. If it is stale, return to `/work` Phase 3.3,
rerun the combined-branch loop, and capture the new handoff before preparing another packet.

## Phase 1 — Prepare the packet

Use the repository profile and the builder record from this branch. Put the packet outside the
reviewed tree, in the run's private review directory. `prepare` installs no new policy or prompt:

```bash
python3 plugins/saga/scripts/review_command.py prepare \
  --repo <combined-checkout> --base <base-sha> --head <reviewed-sha> \
  --profile <profile-json> --builder-record <builder-record-json> \
  --out <packet-directory> --issue <issue> --round <round>
```

Read the packet's coverage and degraded inputs. A missing tool or unavailable reproduction is
recorded as such; it cannot establish a clean result. The existing calibration decides which
lens and language combinations may block. Do not edit the calibration as part of a review.

## Launch and collect through Orchestrate

Orchestrate owns every reviewer session and its transport. Launch the recorded targeted reviewer
against this exact packet and revision. High-risk cards also use Orchestrate's second reviewer.
Never create an unowned reviewer session or substitute a harness-specific launcher.
Do not launch or collect a reviewer through any saga transport script.
`engine-registry.yaml` is capability metadata only, never launch authority; it cannot select or launch a reviewer.
HALT when the recorded reviewer or its owned transport is unavailable.

```bash
python3 plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py review-launch \
  --issue <issue> --seat targeted-reviewer --packet <packet-directory> \
  --repo <combined-checkout> --head <reviewed-sha>
```

Collect the answer and transport result paths Orchestrate reports. Use the same packet for both
reviewers. In a standalone review with no orchestrated run, the operator is the transport:
ask them to establish the Orchestrate-owned reviewer seats. If the transport is unavailable,
record the gap and wait; never invent an unowned reviewer or a clean answer.

## Finish, render and publish

Feed every collected answer and result to `finish`; repeat `--answer` and `--result` for a second
reviewer. The final blocking round uses `--final` so the command performs its full final re-check.

```bash
python3 plugins/saga/scripts/review_command.py finish --packet <packet-directory> \
  --answer <answer-json> --result <transport-result-json> --issue <issue> --round <round>
python3 plugins/saga/scripts/review_state.py render --issue <issue> --repo <owner/name> --render markdown
```

The durable result is a `review_records.v1` record with `kind: "review_run"`. Read its C1 grades,
findings, merge answer, tool gaps, cost and time. Render the operator status header through the
shared `status_card.py` renderer's `project_code_review` projection. Supply the scope check,
built-versus-planned audit and computed merge verdict; its rows are Scope, Intent, Merge and Verdict.
The card presents the stored evidence and never decides whether a finding blocks.

Below the card, group the findings by severity and retain the evidence table:
`# | File | Issue | Reviewer | Confidence | Route`. Cite the reviewed file and line, reviewer,
evidence confidence and actual repair or operator-choice route for each finding. Include degraded
inputs and coverage gaps below it. Follow the shared formatting contract for the full document.

Publish one comment per reviewed round when a PR exists; never submit an approving review:

```bash
python3 plugins/saga/scripts/review_state.py publish --issue <issue> --repo <owner/name> \
  --pr <pull-request> --round <round>
```

## Route the round and merge

- Every lens at C or better with no blocking items proceeds to merge. Fix-later items never hold it.
- Re-check repaired code after Work lands a repair and the combined branch passes again. A fix-now
  choice on a clear review keeps the same counted round; it does not spend a blocking repair round.
- Stop early when successive repair rounds leave the same non-empty set of C1 blocking finding
  identities, including when lines moved. Round three is the limit; there is no escalation or extension.
- At an early stop or the limit, blocking items always wait for the operator. The operator may stop
  the card, or record a merge reason and file every ordinary blocking item as a linked defect through
  mission-control. Each successful filing is saved before the next, so a resumed step files only
  items still unfiled. A recorded choice is scoped to the current review run.
- Reproduced data loss or security exposure blocks in every lens, including report-only lenses.
  `merge-with-reason` cannot override it. Repair the harm or stop the card.
- An unattended run at `auto` merges only after the review allows merge. At `gate`, or in an attended
  run, confirmation waits for the operator. A pane timeout follows the envelope; it cannot answer
  an early-stop or limit exception. Unresolved pull-request threads also hold release.

## Record operator choices

<!-- gate-record: id=code-review-interaction absence=HALT transport=ask-user-question -->
For a known choice, ask the operator one question at a time through the available question tool.
If that tool is unavailable, print the numbered choices from `review_state.py render` and collect
the reply. A timeout or silence supplies no operator answer. The unattended `auto` merge setting
is the operator's run-start confirmation for a clear review, as the intent envelope defines it.

In Claude Code, use `mcp__saga__review_merge` when available. Submitted answers are already stored;
do not ask or record them again. Otherwise apply the actual replies through the same portable API:

```bash
python3 plugins/saga/scripts/review_state.py answers --issue <issue> --repo <owner/name> --answers <answers-json>
```

Fix-later choices are fix-now, file-as-issue or leave. The security guard files traced or suspected
harm unless fixed now; unattended runs apply only the documented guard and profile rules. The
release step checks unresolved threads before any merge, binds the merge to the checked head,
and cites the combined functional evidence and filed residual issues at closeout.

## Continue the run

When review allows merge, return to `/work`'s gate if it called this review; otherwise run the
step the run record's `next_step` names in the same turn, honoring its recorded confirmation.
For repairs, continue into `/work` repair planning and the combined-branch loop before preparing
another packet. At an early stop, the round limit or an unavailable required input, record the
reason and wait for the operator's actual choice. Say which continuation ran and where it stopped.
