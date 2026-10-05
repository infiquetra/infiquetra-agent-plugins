---
title: orchestrate: one targeted reviewer per review, two on high-risk cards
repo: infiquetra-agent-plugins
type: enhancement
team: asgard
project: operations
labels: enhancement, needs-plan
risk: medium
handoff_maturity: requirements-ready
stage: Shaping
status: Discovering
approval_state: approved
---

# orchestrate: one targeted reviewer per review, two on high-risk cards

### Objective

In a run orchestrate drives, the review phase is one review controller plus one targeted reviewer, an
LLM (large language model) session that orchestrate starts through agent-launcher with its vendor's
normal configuration. A high or very-high risk card also gets a second reviewer through the existing
`external-reviewer` seat, on the same packet files and blind to the first reviewer's answer.
Orchestrate only moves files, and its readers of the old review result read the new records instead.

### Intent

Today (infiquetra-agent-plugins at origin/main 1f7137d):

- Orchestrate admits one `review-controller` unit per review phase (or one per declared lifecycle)
  plus named `external-reviewer` seats, and refuses plain review prompts and duplicate Code Review
  units before any session starts (`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`
  lines 194-197, 1293-1336, 1390-1424; `SKILL.md:139-163`). Every seat is an interactive pane in
  Herdr, the terminal multiplexer, launched through `expand` and `go`.
- The controller runs `/code-review`, which stands up one lens reviewer per selected lens. The command
  file says the controller "takes its lenses and external-reviewer seat from Code Review's contract"
  and "runs its own lens consensus" (`com.infiquetra.claude/commands/orchestrate.md:22-31`, `160-163`).
- `review-result` stores the controller's `review_result.v2` verbatim and reads only the outcome and
  the fix requests (`orchestrate.py:208-211`, `1454-1504`). Five test files carry that shape, and
  `tests/test_review_loop_end_to_end.py:28-35` loads saga's `review_consensus.py`.
- The saga run record holds the card's risk tier as `admission.risk_tier` (`run_record.py:387`), and
  admission offers `very-high` as well as `high` (`admission.py:120`, both in `plugins/saga/scripts/`).
  `plan-check` reads no run record (`orchestrate.py:2859-2872`).

What changes (plan.md: "Decisions added when the plan became issues"; "How the reviewer runs";
Change 6, the second reviewer; Change 8, where the lens roster is deleted):

- **One targeted reviewer per review.** Orchestrate starts it through agent-launcher's reviewer
  launch (C8) on the vendor its staffing names, with that vendor's normal configuration (its
  instruction files, plugins and hooks; for Claude, `claude -p`), on the packet files the review
  command writes (C10a). It collects the answer file and the session's result (usage, vendor, model,
  and a fingerprint of its instruction files and enabled plugins) and hands both back for the review
  command's `finish`. Orchestrate never reads, scores or merges findings.
- **A second reviewer on high and very-high risk cards,** read from `admission.risk_tier`. It takes
  the `external-reviewer` seat, from another vendor where the run staffs one, otherwise from the same
  vendor. It gets the same packet files and never the first reviewer's answer.
- **The second reviewer's settings.** It starts through the same launch with its own vendor's normal
  configuration; from the same vendor, it runs exactly as the first does. Its answer file and session
  result come back like the first's, so the review run records its configuration too (C10a).
- **The new records.** Orchestrate's readers of `review_result.v2` read C1's review run record,
  still taking only the routing fields, and fall back to `review_result.v2` until the switch: today's
  `/code-review` keeps writing the old shape until C10b, which deletes the fallback. The five test files move with them, and the
  end-to-end test stops loading saga's consensus code.
- **Plan checks and docs.** `plan-check`, `launch-table`, `start` and `expand` expect one review
  controller and no lens roster. `SKILL.md` and the command file lose the lens-consensus wording.

Depends on C1 (saga: review records, validation and the A–F formula) and C8 (saga + agent-launcher:
the targeted LLM reviewer).

### Risk

medium
A mistake shows as a missing or extra reviewer session, not a wrong merge: blocking still needs a
reproduced finding, and orchestrate makes no acceptance decision.

### Out-of-scope / non-goals

- The reviewer's prompt, answer schema, answer check, and its launch on each vendor with the sandbox
  and the configuration fingerprint (C8).
- The packet, merging the two answers by finding identity, re-running reproductions, recording each
  reviewer's configuration, and writing reviewer usage into the run record's usage entries (C10a, C1).
- Deleting saga's lens roster, consensus scoring and old result shapes (C10b); measuring what the
  second reviewer adds on high-risk corpus cases (K3); the operator's screens (C13, C14).

### Files expected to change

- `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`
- `plugins/orchestrate/skills/orchestrate/SKILL.md`
- `plugins/orchestrate/com.infiquetra.claude/commands/orchestrate.md`
- `plugins/orchestrate/tests/test_orchestrate_review_transport.py`
- `plugins/orchestrate/tests/test_orchestrate_plan_check.py`
- `plugins/orchestrate/tests/test_orchestrate_review_loop.py`
- `plugins/orchestrate/tests/test_orchestrate_scoped_review_controllers.py`
- `plugins/orchestrate/tests/test_orchestrate_status_and_notes.py`
- `plugins/orchestrate/tests/test_review_loop_end_to_end.py`
- `plugins/orchestrate/com.infiquetra.claude/plugin.json` (its agent-launcher floor)
- `plugins/orchestrate/CHANGELOG.md`
- `plugins/orchestrate/plugin.json` (and the vendor manifests that repeat the version)

### Tests to add or update

- `test_orchestrate_review_transport.py`:
  - one controller plus one targeted reviewer is admitted; a plan with a unit per lens is refused
    before any worktree or session exists;
  - the reviewer starts through agent-launcher's reviewer launch with its vendor's normal
    configuration, and its answer file and session result come back untouched;
  - with `admission.risk_tier` at `high` or `very-high`, a second reviewer starts as
    `external-reviewer` on another staffed vendor, or the same vendor when none is; at `medium`, one;
  - the second reviewer's task names the packet files and carries nothing from the first's answer,
    and it starts through the same launch with its own vendor's normal configuration.
- `test_orchestrate_plan_check.py`: a second controller and a lens roster are both reported, and
  `plan-check` still reads no run record.
- `test_orchestrate_review_loop.py`, `test_orchestrate_scoped_review_controllers.py`,
  `test_orchestrate_status_and_notes.py`, `test_review_loop_end_to_end.py`: routing reads C1's review
  run record, and nothing loads saga's `review_consensus.py`.

### Context library links

- `plugins/orchestrate/skills/orchestrate/SKILL.md` ("Reviewer seats live in the run record")
- `plugins/saga/references/run-record.md` (`admission.risk_tier`)

### Acceptance criteria

- [ ] `python3 -m pytest plugins/orchestrate/tests -q --import-mode=importlib` passes.
- [ ] The targeted reviewer starts through agent-launcher's reviewer launch (C8) with its vendor's
      normal configuration; its answer file and session result go back to the controller, and
      orchestrate reads no finding.
- [ ] A high or very-high record gets two reviewers, on different vendors when another is staffed.
      Any other record gets one.
- [ ] The second reviewer sees nothing from the first and starts through the same launch with its
      own vendor's normal configuration.
- [ ] Orchestrate's readers take C1's review run record when it exists and `review_result.v2` otherwise,
      with a test for each; `grep -rn "review_consensus" plugins/orchestrate` prints nothing.
- [ ] `plan-check` refuses a lens roster and a second controller, with the message `start` would give.
- [ ] `SKILL.md` and the command file no longer say the controller runs lens consensus.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/orchestrate/tests plugins/agent-launcher/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

For the planning step:

- How the targeted reviewer starts: as a plan unit through `expand` and `go`, or through an orchestrate
  subcommand the controller calls with the packet folder. Either way, C8's reviewer launch starts it.
- Where orchestrate leaves each answer file and session-result file for the controller to pass to
  `finish`.
- Role names: the first reviewer is `targeted-reviewer` (C8); the second keeps the `external-reviewer`
  seat (`orchestrate.py:197`).
- How orchestrate picks the second reviewer's vendor from the run's staffing and passes it to C8's
  launch.
- The risk-tier check runs in `start`, `expand` and `go`, because `plan-check` reads no run record.
- Which fields of C1's review run record carry today's routing (`orchestrate.py:1454-1504`), including
  the outcome words a controller's note is checked against (`orchestrate.py:3776-3783`).
- The agent-launcher floor in `com.infiquetra.claude/plugin.json` moves to the release carrying C8's
  reviewer launch; `_declared_agent_launcher_floor` (`orchestrate.py:1968`) reads it.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C9-orchestrate-reviewer-transport.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C9-orchestrate-reviewer-transport.md
- Source type: brainstorm
- Source title: orchestrate: one targeted reviewer per review, two on high-risk cards

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/159
- Number: 159
- Created at: 2026-10-05T19:12:43.578518+00:00
