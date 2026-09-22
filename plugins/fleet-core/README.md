# Fleet Core

The shared library Infiquetra plugins use for staffing, tier vocabulary,
rate-limit retry, the run-start intent envelope, TypeSafe judgments, and the
delegation audit. It is authored in this repository. The import that moved
authorship here took the full module set from `infiquetra-claude-plugins` at
commit `acc99fe7`, which is upstream Fleet Core 0.32.0. There is no provenance
manifest and no upstream pin after that commit.

[`DEFERRED.md`](DEFERRED.md) names the one module this package deliberately
does not carry, and the one data file kept only because a consumer still
declares it.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Version `0.32.0`. |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |
| [`DEFERRED.md`](DEFERRED.md) | What is deliberately absent, and the residual data file |
| [`scripts/jev.py`](scripts/jev.py) | Command-line tool for the judgment verbs |
| [`references/staffing.md`](references/staffing.md) | How the staffing registry is shaped |
| [`references/typesafe.md`](references/typesafe.md) | Data rules the TypeSafe client enforces |
| [`scripts/fleet_commons/`](scripts/fleet_commons/) | The library modules and their data files |

### Library modules

| Module | What it does |
|---|---|
| `staffing.py` | Resolves a work shape, role, or review lens to a model and an effort. Reads `staffing.json`. |
| `tier_palette.py` | The closed model and effort vocabulary, derived at import from `staffing.json`. |
| `tier_resolver.py` | Maps a work shape to a model and an effort, including the one-rung cheaper fallback. |
| `render_tier_table.py` | Renders the tier table from `staffing.json`. |
| `cost_weights.py` | Ordinal cost of a model/effort pair. Reads `cost_weights.json`. |
| `effort_rider.py` | How a resolved effort is honored on each spawn path. |
| `intent_envelope.py` | The one run-start posture schema: run mode, ceremony gates, spend envelope. |
| `retry_backoff.py` | Shared 429 retry, backoff, and circuit breaker. |
| `audit_store.py` | Machine-local delegation audit store. |
| `bridge_receipt.py` | Proof-of-execution receipt shared by engine bridges. |
| `output_attestation.py` | Hash-bound proof for bridge-produced output. |
| `merge_guard.py` | Refuses a merge that would revert a newer comparison branch. |
| `plugin_resolution.py` | Finds a sibling plugin root. It is not the retired discovery shim. |
| `typesafe_client.py` | Client for the TypeSafe System One endpoint. Standard library transport, with an optional vendor SDK. |
| `jev_verbs.py` | Named judgment verbs: questions, criteria, confidence floor. |
| `jev_log.py` | Verdict log and answer cache. |
| `jev_eval.py` | Scores recorded answers against labels, by confidence band. |
| `jev_widen.py` | Widen-only union: a pattern floor a model may raise and may not lower. |

Data files beside the modules: `staffing.json` (palette, work shapes, vendors,
ratings, roles), `cost_weights.json`, and `models.json`. The last of those is
the residual described in [`DEFERRED.md`](DEFERRED.md). The palette does not
read it.

## Requirements

The catalog requires `python>=3.12`. That is a minimum, not a pin: any later
interpreter is in contract. The modules are standard library only and carry
`from __future__ import annotations`. They need no third-party package at run
time. The TypeSafe SDK transport imports `typesafe-sdk` only when a caller
selects that transport and does not inject a client.

## How a consumer gets a module

Not by installing this package. A consuming plugin lists the modules it needs
in `fleet-bundle.json`. The build step copies each one into that plugin as a
generated, read-only, digest-stamped file. The installable artifact is already
complete when a user receives it. Agent Plugins has no dependency field, so
there is nothing to declare at install time.

A module that needs another module loads it from the same directory. That is
what lets one file work in `scripts/fleet_commons/` and in any generated
`_bundled/` copy. The Claude Code discovery shim is not part of this package.
[`DEFERRED.md`](DEFERRED.md) says why.

Two digest domains keep a bundle honest, and they fail for different reasons.
A source-payload digest covers the module's bytes and answers whether a bundle
has gone stale. A generated-output digest covers the generated file with its
own stamp block excluded and answers whether a bundle was edited by hand. A
digest is never computed over bytes that contain it.

An authored package has no provenance manifest. The bundle stamp records this
package's `plugin.json` version and `source-commit: authored`. The source
digest, not that marker, is what proves the bytes match.

```bash
python3 scripts/bundle_fleet_module.py
python3 scripts/bundle_fleet_module.py --check
```

## Further reading

- [Custody move and retirement plan](../../docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md)
- [Repository boundary and validation commands](../../AGENTS.md)
