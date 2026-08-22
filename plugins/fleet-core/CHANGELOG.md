# Changelog

All notable changes to the portable Fleet Core package are documented in this
file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
The version is not an independent number: it tracks the upstream Fleet Core
version this package is derived from, because custody of the ported module stays
in `infiquetra-claude-plugins` and a parallel numbering would imply a second
writable source. When upstream releases a Fleet Core version that changes a
ported module, this package is re-synchronized and takes that version.

## [0.25.0] - 2026-08-22

Initial portable slice, derived from Fleet Core 0.25.0 in
`infiquetra-claude-plugins` at commit `13b0234`.

### Added

- **The shared 429 retry and backoff primitive, as an upstream byte copy.**
  `scripts/fleet_commons/retry_backoff.py` carries `retry_with_backoff`,
  `CircuitBreaker`, `bridge_call`, and `CircuitOpenError`. It is standard
  library only and pure over injected `sleep`, `rng`, and `clock` seams, so its
  tests are deterministic and no real time passes. The file is byte-identical to
  its source; the repository validator recomputes its digest against
  `PROVENANCE.json` on every run, so a hand edit here fails validation rather
  than surviving as silent divergence.
- **The upstream test suite, ported with its ten tests unchanged.**
  `tests/test_retry_backoff.py` at the repository root. Every line from
  `class RateError(Exception):` onward is a byte copy. The single deviation is a
  guarded `pytest` import, recorded in `PROVENANCE.json` as deterministic
  transform `guard-pytest-import` version 1, which lets the repository's
  dependency-free baseline job import the module without pytest installed while
  the ported plugin job still runs all ten tests.
- **A generated inventory of everything this slice does not carry.**
  [`DEFERRED.md`](DEFERRED.md) names each upstream item absent from this
  package: fifteen Python modules, three data files, and the Claude-specific
  shim module. It is derived from the pinned source tree by
  [`scripts/generate_deferred_inventory.py`](../../scripts/generate_deferred_inventory.py)
  as a set difference rather than typed, so a module added upstream fails the
  check until the file is regenerated.
- **A provenance manifest pinning the derivation.**
  `PROVENANCE.json` records the source repository, the source commit, the Fleet
  Core version, and a per-file classification and digest.

### Notes

- This package is one vertical slice and claims no Fleet Core parity. Consuming
  plugins receive the module as a generated, stamped, read-only bundle produced
  at build time, so no user installs Fleet Core separately.
- The portable catalog targets Python 3.10 or newer. The ported module itself
  carries `from __future__ import annotations` and needs nothing beyond the
  standard library.

[0.25.0]: https://github.com/infiquetra/infiquetra-claude-plugins/releases/tag/fleet-core-0.25.0
