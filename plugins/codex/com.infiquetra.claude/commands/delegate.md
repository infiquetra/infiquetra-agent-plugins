---
name: delegate
description: Submit a codex delegation envelope through the guarded codex wrapper
argument-hint: "role=<coder|reviewer> mode=<read-only|task> evidence=<minimal|summary|full> write-set=<path>"
---

Delegate one bounded task to codex through the guarded wrapper.

## Instructions

1. Follow the `codex-delegate` skill shipped with this plugin.
2. Build a `codex.delegation.v1` envelope from the command arguments and task text.
3. Invoke exactly one wrapper run with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_delegate.py"`.
4. Return the wrapper output, including the evidence bundle path.
5. Do not invoke raw `codex` directly, do not use background or detached execution, and do not
   use a weaker runner path.
6. Do not use direct Claude repo file tools to solve the delegated task locally.

## Argument Syntax

- `role=<coder|reviewer>` selects the envelope role. Reviewer defaults are `mode=read-only` and
  `review_lens=adversarial`.
- `mode=<read-only|task>` selects the write gate. Coder defaults to `mode=task`, which is
  write-capable but scoped to a disposable clone only. It never applies the patch to the live tree.
- `evidence=<minimal|summary|full>` selects the evidence bundle detail level.
- `review_lens=<adversarial|quality|scope-gap|security-ops>` selects one reviewer lens without
  creating another agent.
- `write-set=<repo-relative-path>` may be repeated. Required for `mode=task`.
- `model=<name>` and `effort=<level>` are optional for direct delegation. When omitted, the
  `codex` binary uses its own configured default. Saga registry dispatch includes both explicitly
  and fails closed if either is missing.

## Quick Reference

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_delegate.py" \
  --role coder \
  --mode task \
  --evidence summary \
  --write-set plugins/example/file.py \
  --task-file /path/to/task.md
```

Arguments provided to the command:

`$ARGUMENTS`
