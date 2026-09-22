---
name: delegate
description: Submit an Antigravity teammate delegation envelope through the guarded agy wrapper
argument-hint: "role=<coder|reviewer> mode=<no-write|patch-only> evidence=<minimal|summary|full> write-set=<path> verification=<command>"
---

Delegate one bounded task to an Antigravity-backed teammate through the guarded wrapper.

## Instructions

1. Load `agy/skills/agy-delegate/SKILL.md`.
2. Build an `agy.delegation.v1` envelope from the command arguments and task text.
3. Invoke exactly one wrapper run with `python3 plugins/agy/scripts/agy_delegate.py`.
4. Return the wrapper projection, including the evidence bundle path.
5. Do not invoke raw `agy` directly, do not use background or detached execution, and do not use a
   weaker runner path.
6. Do not use direct Claude repo file tools to solve the delegated task locally.

## Argument Syntax

- `role=<coder|reviewer>` selects the envelope role. Reviewer defaults are `mode=no-write` and
  `review_lens=adversarial`.
- `mode=<no-write|patch-only>` selects the write gate. Coder defaults to `patch-only`. Neither mode
  writes the live tree — the run happens in a disposable clone and returns a patch to apply.
- `evidence=<minimal|summary|full>` selects the evidence bundle detail level.
- `review_lens=<adversarial|quality|scope-gap|security-ops>` selects one reviewer lens without
  creating another agent.
- `write-set=<repo-relative-path>` may be repeated. It bounds what the delegate may change in the
  clone; changes outside it are reported as `out_of_scope_mutation`.
- `verification=<command>` may be repeated. Required verification commands must be supplied by the
  operator or orchestrator, not invented by the delegate. They run inside the clone on a
  `patch-only` run, after the delegate's changes.
- `verification-required=<true|false>` declares whether a failing check is terminal. When true, a
  failure yields `checks_failed`; when false the result is recorded in `checks.json` and the run
  stays `patch_ready`.
- `verification-run-scope=clone` is the only scope that executes commands; `none` records them as
  skipped.

## Quick Reference

```bash
python3 plugins/agy/scripts/agy_delegate.py \
  --role coder \
  --mode patch-only \
  --evidence summary \
  --write-set plugins/example/file.py \
  --verification-command "PYTHONPATH=. python3 -m pytest -q tests/test_example.py" \
  --verification-required \
  --task-file /path/to/task.md
```

Arguments provided to the command:

`$ARGUMENTS`
