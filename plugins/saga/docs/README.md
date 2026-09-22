# Saga Manual

This manual explains Saga as a lifecycle operating model: where work starts, which command owns each phase, how local saga state differs from handoff readiness, and where Saga stops in favor of adjacent Infiquetra plugins.

These pages are the manual. The generated visual atlas and the model it was rendered from were retired with the eleven removed commands: a hand-maintained model of a command surface goes stale the moment the surface moves, and the surface itself is now guarded by tests/test_command_surface.py.

## Reading Path

| Need | Page |
|------|------|
| Understand the main lifecycle | [Lifecycle](lifecycle.md) |
| Pick the right command | [Command selection](commands.md) |
| Interpret saga state or artifact maturity | [State and readiness](state-readiness.md) |
| Start from a real user situation | [Scenarios](scenarios.md) |
| Know which plugin owns what | [Boundaries](boundaries.md) |

## Operating Model

Saga has 14 command files and 13 routable commands. `/ceo-review` is a compatibility alias for `/founder-review`. The count is pinned by `tests/test_command_surface.py`, which also names the eleven commands issue 1030 removed, so a partial revert fails on the name rather than on arithmetic.

The main chain is a reviewed-work spine:

```text
idea/requirements-ready -> /plan -> /doc-review -> /work -> /code-review -> /qa -> /retro
```

Several commands intentionally sit off the linear spine. `/spec`, `/investigate`, and `/strategy` are not stored lifecycle phases; they produce artifacts or decisions that route back into the chain.

## Maintainer Path

Update these pages directly when the command surface, routes, state and readiness mappings, scenarios, or ownership boundaries change.

Then run:

```bash
uv run pytest tests/test_command_surface.py tests/test_saga_doc_formatting.py
```
