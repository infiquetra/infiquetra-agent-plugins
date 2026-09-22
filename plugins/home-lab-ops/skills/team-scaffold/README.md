# team-scaffold

Deterministic generator for a new Infiquetra agent-team repository: a
context-library skeleton, a deploy harness, vault wiring, and an inventory
registration. Discord bot creation and GitHub App creation stay human gates.
The skill document is [SKILL.md](SKILL.md). The runbook is
[references/runbook.md](references/runbook.md).

## Dependencies

The package does not vendor a virtual environment. Install these yourself.

| Need | Distribution | Required for |
|---|---|---|
| runtime | `pyyaml>=6.0` | loading specs, profiles, and inventory |
| tests | `pytest>=8.0` | `plugins/home-lab-ops/tests` |
| lint | `ruff>=0.6` | optional local lint of `scripts/` |
| types | `mypy>=1.10`, `types-pyyaml>=6.0` | optional local type check |

`scripts/pyproject.toml` is the same list, and `scripts/uv.lock` pins one
resolution of it. An editable install from `scripts/` is optional. The
launcher works once PyYAML is importable:

```bash
python3 scripts/team-scaffold --help
```

Run that from this skill directory, or pass the path from anywhere else.

## Checkouts the commands read

| Variable | Default | Used by |
|---|---|---|
| `HOME_LAB_ROOT` | `~/home-lab` | `register-host` reads `$HOME_LAB_ROOT/ansible/inventory/hosts.yml`. `materialize_specs.py --hosts` uses the same default. |
| `INFIQUETRA_CONTEXT_LIBRARY` | `~/infiquetra-context-library` | `stamp --context-library` copies the archetype templates from this checkout. |

Both defaults are conventional directory names. Set the variables when the
checkouts are somewhere else. The commands do not embed a path from any one
machine.

## Tests

From the catalog repository root, with PyYAML and pytest installed:

```bash
python3 -m pytest plugins/home-lab-ops/tests -q
python3 plugins/home-lab-ops/skills/team-scaffold/scripts/team-scaffold golden
```

`golden` re-derives the twelve committed team fixtures under `specs/`. It
does not need either checkout. Tests that stamp a repository from the
context library skip when `INFIQUETRA_CONTEXT_LIBRARY` is unset.
