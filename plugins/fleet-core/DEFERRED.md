# What this package deliberately does not carry

Fleet Core is authored in this repository as of the import from
`infiquetra-claude-plugins` at commit `acc99fe7` (upstream version 0.32.0).
There is no provenance manifest and no upstream pin. This file names what is
still absent on purpose, and the one file that remains here only because a
consumer still declares it.

## Deliberately absent

| Item | Why it stays out |
|---|---|
| `scripts/fleet_commons_shim.py` | Its resolution ladder discovers a Claude Code plugin install (environment override, marketplace walk-up, the installed-plugins registry, and a cache-sibling scan). This catalog does not ship that discovery. A consumer declares the modules it needs, and `scripts/bundle_fleet_module.py` copies them into the consumer at build time. A module that needs a sibling loads `<this directory>/<name>.py`, so the same file works in `plugins/fleet-core/scripts/fleet_commons/` and in a generated `_bundled/` copy. |

Nothing else from the Fleet Core tree at `acc99fe7` is absent. The Python
modules, the data files that revision carries, `scripts/jev.py`, and
`references/` were imported. Names from the older slice inventory that this
commit does not contain (`concurrency_policy.py`, `delegation_audit.py`,
`delegation_state.py`, `liveness_engine.py`, `tier_policy.json`) are not
deferred. They are not in the imported revision.

## Residual kept for a consumer

| Item | Why it is still here |
|---|---|
| `scripts/fleet_commons/models.json` | Absent from `acc99fe7`. The tier palette reads `staffing.json`. `plugins/mission-control/fleet-bundle.json` still declares `models.json`, so the file stays until that consumer's own import drops the declaration. |

`staffing.json` is also copied into mission-control's bundle. The
already-declared `tier_palette` module reads that file at import. The
consumer's module list was not extended; the extra data entry is what makes
the declared module loadable. That consumer's import unit owns any later
change to the module list.
