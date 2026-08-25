# Portable Fleet Core

One vertical slice. This package carries the shared 429 rate-limit retry and
backoff primitive that Infiquetra plugins use so that every plugin which can
hit a rate limit responds the same way, instead of each one growing its own
handler, plus the run-start intent envelope and the tier palette with its
`models.json` registry that mission-control's shipped surface reaches.

It is a single vertical slice of the upstream Fleet Core library, not the
library. [`DEFERRED.md`](DEFERRED.md) names every upstream item this package
does not carry, and no document here claims full Fleet Core parity.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins 1.0 manifest |
| [`PROVENANCE.json`](PROVENANCE.json) | Where the bytes came from, and what may be done to each path on the next synchronization |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |
| [`DEFERRED.md`](DEFERRED.md) | Generated inventory of everything not ported |
| [`scripts/fleet_commons/retry_backoff.py`](scripts/fleet_commons/retry_backoff.py) | A ported module: the retry and backoff primitive |
| [`scripts/fleet_commons/intent_envelope.py`](scripts/fleet_commons/intent_envelope.py) | A ported module: the run-start intent envelope, under the `resolve-fleet-commons-sibling` deterministic transform |
| [`scripts/fleet_commons/tier_palette.py`](scripts/fleet_commons/tier_palette.py) | A ported module: the tier palette |
| [`scripts/fleet_commons/models.json`](scripts/fleet_commons/models.json) | The ported model/effort registry the tier palette reads |
| [`tests/test_retry_backoff.py`](../../tests/test_retry_backoff.py) | The ported test suite, at the repository root |
| [`tests/test_intent_envelope.py`](../../tests/test_intent_envelope.py) | Target-owned tests for the transformed envelope module |
| [`tests/test_tier_palette.py`](../../tests/test_tier_palette.py) | Target-owned tests for the tier palette |

The release surface is the manifest, the provenance manifest, the changelog, the
ported modules, and the ported and target-owned tests. Nothing outside that list
is part of a Fleet Core release; the README and the deferred inventory are
package documentation carried alongside it.

## What the modules provide

`retry_backoff` — `retry_with_backoff(fn, ...)` calls `fn` with jittered
exponential backoff and retries a rate-limit failure up to an attempt cap. An
error that is not a rate limit propagates immediately rather than burning
retries. A server-supplied `Retry-After` hint overrides the computed delay and
is clamped to the maximum delay, and a non-positive hint falls back to computed
backoff so a bad hint cannot create a tight retry loop.

`bridge_call(fn, breaker=...)` wraps that in a `CircuitBreaker`, which opens
after a run of rate-limit failures, short-circuits with `CircuitOpenError`
during its cooldown, allows one probe when half open, and closes on success. A
failure that is not a rate limit never trips the breaker, because the breaker
guards rate limiting rather than correctness bugs.

Both entry points are pure over injected `sleep`, `rng`, and `clock` seams, so
the tests are deterministic: no real time passes and no real randomness is
drawn.

`intent_envelope` — the one committed run-start posture schema: a closed
`IntentEnvelope` (run mode, pre-declared ceremony gates, optional spend
envelope), the composed run-start interview, and the issue-carried block
parse/render surface mission-control writes at issue capture. The ported copy
carries the `resolve-fleet-commons-sibling` transform: where upstream resolves
sibling modules through a Claude-Code-specific discovery shim, this copy
resolves them from its own directory, so the identical file works here and in
any generated `_bundled/` copy. Its one deferred leg (`tier_resolver`, which
backs `recommend_tier`) has no caller in the ported surface and raises at call
time naming the missing sibling path.

`tier_palette` — the closed model/effort vocabulary and its ladder operations
(escalate, downgrade, clamp, compare), derived at import from the explicit
rank indices in its sibling `models.json` registry, which the slice carries
for exactly this read.

## Requirements

The portable catalog requires `python>=3.12`. That is a minimum, not a pin: any
later interpreter is in contract. The floor is the one the authoritative source
repository, `infiquetra-claude-plugins`, declares and tests, and a derived
catalog does not promise more compatibility than the source it is derived from.

The modules themselves are standard library only and carry
`from __future__ import annotations`, so they need no third-party package at
run time and no network access.

## How a consumer gets it

Not by installing this package. A consuming plugin declares the modules it
needs, and the build step copies each one into that plugin as a generated,
read-only, digest-stamped file. The installable artifact is therefore already
complete when a user receives it, which is how this catalog works around Agent
Plugins 1.0 having no dependency mechanism: at install time there is no
dependency to declare.

Two digest domains keep the copy honest, and they fail for different reasons. A
source-payload digest covers the upstream module's bytes and answers whether a
bundle has gone stale. A generated-output digest covers the generated file with
its own stamp block excluded and answers whether a bundle was edited by hand. A
digest is never computed over bytes that contain it.

## Custody

Custody does not move. `infiquetra-claude-plugins` remains the authoritative
source for every ported module, and this package is a derived artifact rather
than a second writable source. A future fix to any ported module lands upstream
first and reaches this repository by re-synchronization. First-class portable
source means this package gets a real lifecycle — a version, provenance, a
release surface, a compatibility contract — not that authorship relocates.

The pinned source is recorded in [`PROVENANCE.json`](PROVENANCE.json) and
restated in [`DEFERRED.md`](DEFERRED.md).

## Regenerating the deferred inventory

[`scripts/generate_deferred_inventory.py`](../../scripts/generate_deferred_inventory.py)
derives the inventory from the pinned source tree as a set difference, so no
count is ever typed by hand. Regenerating needs a local checkout of the upstream
repository at the pinned commit:

```bash
python3 scripts/generate_deferred_inventory.py \
  --source <upstream-checkout>/plugins/fleet-core

# Verify against that same source, writing nothing.
python3 scripts/generate_deferred_inventory.py \
  --source <upstream-checkout>/plugins/fleet-core --check

# Hermetic self-check, no upstream checkout required.
python3 scripts/generate_deferred_inventory.py --check
```

Continuous integration has no upstream checkout, so it runs the hermetic
self-check: it cannot see a module added upstream, but it does catch this
package porting a module the inventory still lists as deferred, or dropping one
it claims to port.

## Further reading

- [Pilot plan](../../docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)
- [Repository boundary and validation commands](../../AGENTS.md)
