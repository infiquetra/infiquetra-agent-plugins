---
name: plan
description: Plan a change when asked to plan, break down, sequence, or decide how to build it. Read the code first, record decisions and non-goals, and save a plan file only when the work spans units or sessions.
metadata:
  compatibility: python>=3.12
---

# Plan

Use this skill when someone asks for a plan, a breakdown, an implementation sequence, or a design for how to build a change. Start from the request. A saved plan is for work that has to last, not a ritual before every edit.

## Read the code first

Read the code the change touches before proposing a design. Cite each load-bearing fact as `path:line`. Name the exact file count (`4 files`). When the repository has them, read `AGENTS.md`, `STRATEGY.md`, and `docs/engineering-journal/` and follow decisions already recorded there.

Read in this order: the repository instruction file, the strategy note, the journal decisions that name the area, then the code and tests the change will touch. Stop when the next file would not change a decision or a file list.

A phrase such as "several files" is not a count. Name the paths.

## What to record

Record choices and boundaries. Leave the implementation to the session that builds it.

- **Key technical decisions.** Each entry is a choice plus one line of rationale, including the tradeoff that made it the choice.
- **Out of scope / non-goals.** Name what this work will not do, in concrete terms.
- **Units.** When the work is more than one edit, list ordered units. Each unit is independently verifiable and names three things: the repo-relative files it changes, the fail-first test scenarios (input, action, expected outcome), and the command that verifies it. A later unit may depend on an earlier one; say so by name. A unit that cannot be checked on its own is still one edit, not a unit.
- **Boundaries.** Name the failure modes that match the risk. Cover empty or malformed input, partial failure, and idempotency or rollback when a failed step must leave the tree usable. A one-line typo does not need a rollback story. A checker, a migration, or a write to shared state does.

## Decisions stay short

A decision names the choice and the reason in one line. Put the rejected alternative in that same line when a later session would otherwise rediscover it. Do not paste the implementation under the decision. The session that builds the unit reads the code again and writes the change there.

An unresolved blocker is a decision still to make, with the facts already known. When nothing is unresolved, leave it out. A placeholder in a saved plan is a gap the checker reports.

## How big the plan is

Keep a small plan in the chat. One edit, one decision, no later session: reply with the decision, the files, and the verification command.

Write `docs/plans/YYYY-MM-DD-<slug>-plan.md` when the work has more than one unit or has to be resumed in a later session. Copy the section order from [the plan template](references/plan-template.md):

- Summary
- Non-Goals or Scope
- Key Decisions
- Units or Steps
- Verification or Tests

Use repo-relative paths. Mark a file that does not exist yet with `(new)` on the same line. The parent directory must already exist, or that parent must also be marked `(new)`. Leave no `TBD`, no `TODO`, and no vague file count in the saved file.

## Check a saved plan

The checker is standard-library Python and lives in this skill directory, so a harness that installs the skill still has it. From this directory:

```bash
python3 scripts/check_plan.py --root <repository-root> <repository-root>/docs/plans/YYYY-MM-DD-<slug>-plan.md
```

From the repository root, when the whole package is present:

```bash
python3 plugins/plan/skills/plan/scripts/check_plan.py --help
python3 plugins/plan/skills/plan/scripts/check_plan.py docs/plans/YYYY-MM-DD-<slug>-plan.md
```

`--root` defaults to the current directory. Exit 0 means the required sections are present, every unmarked path exists, every `(new)` or `create` path stays inside the repository with an existing ancestor or a planned parent, and no placeholder remains. Any other exit prints one gap per line. The checker reads the file and does not edit it. Fix every line it prints, then run it again.

A clean exit is the point a saved plan is ready to hand off.

On Claude Code, writing a markdown file directly under `docs/plans/` runs the same check and returns the gaps as advisory context. The write is kept. Other harnesses do not run that hook, so run the command above before treating the file as done.

## A unit, filled in

```text
### 1. Reader

- Files: `pkg/reader.py`, `pkg/widget.py` (new)
- Tests: empty input returns an empty list; a missing parent path is reported and the destination is left unchanged.
- Verify: `python3 -m unittest pkg/test_reader.py`
```

That is the whole shape: files, a fail-first scenario, a command. Repeat it once per unit, in the order a later session should build them. When a unit's verify command exits 0, that unit is done.
