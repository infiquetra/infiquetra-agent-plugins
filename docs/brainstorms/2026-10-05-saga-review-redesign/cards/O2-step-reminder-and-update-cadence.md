---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: per-turn step reminder and issue update cadence

### Objective

Every operator turn in a session working an active saga run carries one line naming the run, the
step it is in and the step that comes next, so a session that drifts from the lifecycle is reminded
where it should be. The run's GitHub issue is updated after plan review, after every code-review
round, at every stall or restart, and every few hours during a long step, so the issue never goes
quiet while work continues.

### Intent

This card is card 10 of the 4 October 2026 enhancement plan, which plan.md ("Decisions added when
the plan became issues") files as a card of its own, outside the review redesign.

What is true today, at origin/main (1f7137d), with paths under `plugins/saga/`:

- The prompt hook runs on every operator prompt (`com.infiquetra.claude/hooks/hooks.json`,
  `UserPromptSubmit`, 5-second timeout). It prints at most one line, and only when the prompt names
  exactly one saga command, or asks to carry on and the recorded next step names one
  (`hooks/prompt_suggestion_hook.py:75-95`). Every other prompt gets silence, by design (`:15-18`).
  It is local only: no network call, and the prompt text is never logged or sent (`:6-13`).
- The session-start hook announces the recorded next step at `startup` and `resume` only
  (`hooks/next_step_session_hook.py:39`). The announcement and the rule that suppresses a finished
  step live in `scripts/next_step_context.py` (`:118-157`).
- `scripts/issue_progress.py` renders a comment for five events: start, phase, pr, deploy and
  completion (`:10-16`). It posts nothing. `/work` posts the comment through the reconcile
  controller's `issue-progress-comment` operation (`skills/work/SKILL.md:671-729`), whose ledger
  collapses a repeated comment (`:718-721`).
- `/plan` moves the board after plan review (`skills/plan/SKILL.md:798-808`) but posts no progress
  comment. Nothing posts after each code-review round, at a restart, or on a clock.

What changes:

- The prompt hook adds the reminder line on every turn when the session's checkout resolves to an
  active run, read locally from the run record and the saga envelope, the way
  `next_step_context.py` reads them. It stays local, silent on any error, and never blocks. The
  existing command suggestion stays. The hook's documented "silence by default" changes for
  sessions with an active run, and its docstring and tests say so.
- A Claude Code mod variant on the `prompt.compose` event, as the enhancement plan names it,
  registered in `com.infiquetra.claude/mods/index.ts`.
- Issue updates, each rendered by `issue_progress.py` and posted through the reconcile controller:
  after plan review (`/plan` 5.4), after every code-review round, at every stall or restart, and at
  least every few hours in a long step. `issue_progress.py` gains the events these need.

Dependencies: none. O1 (saga mod: status band, second version) shows the age of the last update;
both cards need to know when the issue was last updated (see item 5 of this card's planning-step
notes).

### Risk

low
Advisory context that never blocks a turn, plus additive issue comments through the existing path.

### Out-of-scope / non-goals

- The status band (O1), the budget and its notices (O3), and the cost report (O4).
- Sending the operator's prompt text off the machine; the hook stays local (`:6-13`).
- Changing the reconcile controller, its ledger, or mission-control's comment verb.
- Backstop gates that stop a run that is off its path; the operator deferred them (plan.md).
- The review summary and fix-later checklist on the pull request (C13, saga: review state for every
  harness, the pull request checklist and fix-later choices).

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/prompt_suggestion_hook.py`
- `plugins/saga/com.infiquetra.claude/hooks/next_step_session_hook.py`
- `plugins/saga/scripts/next_step_context.py`
- `plugins/saga/scripts/issue_progress.py`
- `plugins/saga/skills/plan/SKILL.md`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/com.infiquetra.claude/mods/index.ts`
- `plugins/saga/tests/test_prompt_suggestion_hook.py`
- `plugins/saga/tests/test_next_step_context.py`
- `plugins/saga/tests/test_saga_issue_progress_is_posted.py`

### Tests to add or update

- `plugins/saga/tests/test_prompt_suggestion_hook.py`: with an active run, every prompt gets the
  reminder (run, step, next step); without one, unrelated prompts stay silent; a command suggestion
  still appears beside the reminder; an unreadable record gives silence; the hook still imports no
  network client and opens no socket (the existing tests at `:117` and `:147`).
- `plugins/saga/tests/test_next_step_context.py`: the reminder text for each step, and none for a
  finished run.
- `plugins/saga/tests/test_saga_issue_progress_is_posted.py`: `/plan` and `/work` name a posting
  command for each new update point, and each names an event `issue_progress.py` renders.
- A mod test beside the new `prompt.compose` module, run by `claude plugin test plugins/saga`.

### Context library links

- `infiquetra-sdlc/docs/process/run-contracts.md` (a handoff is a short structured issue comment)

### Acceptance criteria

- [ ] In a checkout with an active run, each prompt submitted to the hook returns one line naming
      the run, its step and its next step; with no active run, an unrelated prompt returns nothing.
- [ ] The hook makes no network call and exits 0 on every input.
- [ ] `/plan` posts an issue update after plan review, and `/work` posts one after every code-review
      round, both through `reconcile_controller.py reconcile --op issue-progress-comment`.
- [ ] A restart, a stall and a long step each produce an update, as the planning step settles them.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests/test_prompt_suggestion_hook.py plugins/saga/tests/test_next_step_context.py plugins/saga/tests/test_saga_issue_progress_is_posted.py -q --import-mode=importlib
claude plugin validate --strict plugins/saga
claude plugin test plugins/saga
printf '{"prompt":"what is next","cwd":"%s"}' "$PWD" | python3 plugins/saga/com.infiquetra.claude/hooks/prompt_suggestion_hook.py
```

### Notes / conventions

For this card's planning step:

1. **What a stall is.** Neither the plan nor saga defines one; no saga skill or script uses the word.
2. **How often "every few hours" is.** The interval is not given.
3. **Budget left.** The enhancement plan's reminder line also carried budget left; this card's
   scope in the index does not. Budget comes from O3 if the operator wants it here.
4. **The `prompt.compose` event.** Nothing in this repository uses it yet. Confirm Claude Code
   offers it at the minimum build the packaging tests hold (2.1.286); if not, the hook alone
   carries the line.
5. **Who notices an update is due.** Hooks are local and never post, and posting happens from
   skills through the reconcile controller. The plan does not say what notices a restart, a stall
   or a long step and posts then, or where the time of the last update is kept.
6. **Repeat comments.** The controller's ledger collapses a repeated comment, so a periodic update
   must not be mistaken for a repeat of the last one.
7. **Other harnesses.** The prompt hook lives in the Claude Code adapter
   (`com.infiquetra.claude/hooks/`); the plan names no path for the reminder on other harnesses.
