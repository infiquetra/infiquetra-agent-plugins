# Changelog

All notable changes to Fleet Core are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
From 0.32.0 this package is authored here. The version is this package's
version. The import below kept the upstream version number. Older entries
describe the derived slice and are left as the record of those releases.

The catalog requires `python>=3.12`.

## [0.32.0] - 2026-09-22

0.32.0 — imported in full from infiquetra-claude-plugins@acc99fe7 (upstream
0.32.0); authored here from this commit; no provenance manifest from now on.

### Added

- The full `scripts/fleet_commons/` module set at that commit, plus
  `scripts/jev.py` and `references/`. Package tests live under
  `plugins/fleet-core/tests/` and import those modules directly.
- A module that needs a sibling loads `<this directory>/<name>.py` instead of
  `fleet_commons_shim`. The same file works in this package and in a generated
  `_bundled/` copy. `scripts/fleet_commons_shim.py` is not imported.

### Changed

- `plugin.json` version is `0.32.0`. `PROVENANCE.json` is gone. Bundle stamps
  for an authored package record that version and `source-commit: authored`.
  The source digest still proves the bundled bytes match the module.
- `tier_palette.py` reads `staffing.json` at import. The 0.25.2 slice read
  `models.json`. The model and effort ladders are the same four names.
- `retry_backoff.parse_retry_after` clamps a negative delta-seconds hint to
  `0.0`, the same answer an already-past HTTP-date already produced.
- `typesafe_client._sdk_call` refuses an unprepared body before it imports
  `typesafe-sdk`, and it uses an injected client factory without requiring
  that package. This catalog does not install the SDK. When the SDK is
  installed and no factory is injected, the call still goes through it.
- Mission-control's bundle declaration gained a `staffing.json` data entry so
  the already-declared `tier_palette` module can import. The module list is
  unchanged. `models.json` stayed declared and stayed in this package for a
  time; see the Residual entry below and [`DEFERRED.md`](DEFERRED.md).

### Residual

- `scripts/fleet_commons/models.json` was absent from `acc99fe7` and was kept
  because `plugins/mission-control/fleet-bundle.json` still declared it.
  Cleared 2026-09-22: no `plugins/*/fleet-bundle.json` declares it and no
  shipped Python reads it; the file is deleted. See
  [`DEFERRED.md`](DEFERRED.md).

### Dropped tests

Upstream tests whose premise is the upstream repository layout were not
ported. The catalog's own `tests/test_intent_envelope.py`,
`tests/test_retry_backoff.py`, and `tests/test_tier_palette.py` stay.

Whole files:

- `tests/test_agent_tier_lint.py` — globs every upstream `plugins/*/agents/*.md`.
- `tests/test_agent_tiering.py` — pins agent frontmatter in plugins this catalog does not carry.
- `tests/test_delegation_fleet_monitor.py` — reads `scripts/check_delegation_proof.py` and `marketplace/bridge_plugins.json`.
- `tests/test_fleet_commons_resolution.py` — the discovery shim and byte-identical vendored copies across upstream plugins.
- `tests/test_intent_envelope.py` — saga's re-export, a repo-wide drift guard, and saga's intent-envelope reference.
- `tests/test_mission_control_suggest.py` — mission-control triage scripts this package does not carry.
- `tests/test_parse_issue_flags.py` — saga's `parse_issue.py`.
- `tests/test_saga_spec_consumer_row.py` — saga's plan-save contract.
- `tests/test_typesafe_sdk_pin.py` — the upstream repository's `pyproject.toml` pin of `typesafe-sdk`.
- `tests/test_work_build_unit_tier.py` — saga's work skill and `lifecycle_state.py`.

Cases removed from files that were otherwise ported:

- `test_tier_resolver.py`: `test_skill_md_has_generated_tier_table_markers`, `test_skill_registry_sync`, `test_skill_registry_sync_catches_seeded_divergence`, `test_effort_emitted_into_plan_tier_table` (saga's plan skill and team-execution).
- `test_tier_vocab_single_source.py`: `test_plan_table_render_synced` (saga's plan skill).
- `test_staffing_suggest.py`: `test_admission_embeds_one_suggestion_per_role`, `test_admission_without_suggest_is_unchanged`, `test_admission_suggest_degrades_without_consult`, `test_admission_suggest_falls_open_on_client_error`, `test_admit_threads_suggest_to_one_verdict_per_role` (saga's `admission.py`).
- `test_merge_guard.py`: `TestOrchestrateAgreesWithTheSharedGuard` (orchestrate is not in this catalog).
- `test_jev_eval.py`: `test_the_seeded_benchmark_file_exists_and_is_well_formed`, `test_the_benchmark_reproduces_ten_of_ten`, `test_the_benchmark_run_touches_no_transport` (upstream `docs/analysis` research inputs).
- `test_jev_cli.py`: `test_the_seeded_benchmark_reproduces_ten_of_ten`, `test_eval_json_mode_reports_bands`, `test_eval_makes_no_transport_call` (the same research inputs).
- `test_effort_rider.py`: `test_loadable_via_fleet_commons_shim` (the shim is not shipped; `test_loadable_from_its_own_directory` covers the module).
- `test_typesafe_client.py`: `test_sdk_transport_returns_the_same_shape_as_urllib`, `test_sdk_transport_receives_the_key_explicitly`, `test_sdk_exception_text_is_composed_here_not_by_the_vendor` (they require the `typesafe-sdk` package), and `test_a_real_lock_file_hunk_is_not_shredded` (it reads the upstream repository's `uv.lock`).

## Unreleased

The entries under Changed record catalog-level contract changes that moved no
ported bytes; they carry no release tag. The entries under Added record the
slice expansion of 2026-08-24, which added ported files at the existing pin
without moving any byte already here. Neither group advances the package
version: this package's version tracks the upstream Fleet Core version its
bytes derive from (0.25.2 at commit `3b5faa6c`), and upstream's 0.25.3 release
of 2026-08-24 changed `retry_backoff.py`, which this pin deliberately does not
take — a repin would churn UniFi's bundles and invalidate its committed
matrix. Naming this package "0.25.3" while it still carries 0.25.2's
`retry_backoff` bytes would collide with the real upstream release, and
inventing any other number would imply the second writable source this
changelog's convention exists to prevent.

### Changed

- **The portable UniFi package no longer pins the same upstream revision as this
  package, and no Fleet Core byte moved.** UniFi `2.0.1`, at upstream commit
  `0d81dd9a`, repaired the caller half of the `Retry-After` defect this package's
  `0.25.1` release fixed in the primitive: both UniFi clients converted the raw
  header with `int()` before raising, so the repaired primitive never received a
  header it could read. `plugins/unifi/PROVENANCE.json` therefore pins
  `0d81dd9a`, while this package still pins `ed72f439`. The upstream
  `plugins/fleet-core` subtree is byte-identical between those two revisions, so
  the two pins name one consistent upstream state, not two competing answers.
  The `[0.25.1]` entry below says the two packages pin the same revision; that
  sentence describes what was true at that release and is left standing rather
  than rewritten.

- **The catalog's minimum supported Python is `python>=3.12`.** It is a minimum
  and not a pin: every later interpreter stays in contract. The floor is now the
  one the authoritative source declares and tests. `infiquetra-claude-plugins`
  sets `requires-python = ">=3.12"` in its project file and pins `3.12` in every
  continuous-integration job, at the same commit `ed72f439` this package is
  derived from. A derived catalog must not promise more compatibility than the
  source it is derived from, so the lower floor this catalog used to document
  was a promise nothing upstream was keeping. The decision and its reasoning are
  recorded in the repository's engineering journal.

### Added

- **The mission-control closure joins the slice: three files at the same pin.**
  `scripts/fleet_commons/intent_envelope.py`,
  `scripts/fleet_commons/tier_palette.py`, and the
  `scripts/fleet_commons/models.json` registry are ported at fleet-core pin
  `3b5faa6c`. Mission-control's shipped surface reaches exactly this closure:
  its issue-capture path loads the envelope module's parse/render surface, and
  `IntentEnvelope.validate()` reaches the tier palette whenever a parsed
  envelope carries `spend_envelope.tier_ceiling`; the palette reads its sibling
  registry at import time, so the data file rides the slice. The resolver leg
  behind `recommend_tier` has zero callers in either consumer and stays
  deferred.
- **`tier_palette.py` and `models.json` are pure byte copies**; the repository
  validator recomputes their digests against `PROVENANCE.json` on every run.
  **`intent_envelope.py` ports under this package's existing
  `deterministic-transform` custody class** with the new named rule
  `resolve-fleet-commons-sibling` version 1: the module's Claude-Code-specific
  discovery-shim import block and its two shim load call sites become
  same-directory sibling resolution — placement-independent, so the identical
  file works in this package and in any generated `_bundled/` copy a consuming
  plugin carries. A deferred name (`tier_resolver`) fails at call time naming
  the missing sibling path, never at import. Every other line is a byte copy.
- **The deferred inventory is regenerated**, so exactly the three rows move
  from deferred to ported and every other deferral stays explicit; the
  provenance manifest classifies all three files and names them, with the two
  new target-owned tests, in the release surface. The decision is KTD8 in
  `docs/plans/2026-08-24-mission-control-port-run-plan.md`.

## [0.25.2] - 2026-08-22

Re-synchronized from Fleet Core 0.25.2 in `infiquetra-claude-plugins` at commit
`3b5faa6c`. Custody did not move. The repair was authored, reviewed, and
released upstream and taken here by re-synchronization, which is the second
exercise of this slice's rule.

### Fixed

- **A non-finite `Retry-After` no longer costs the caller its typed rate-limit
  surface.** `float()` accepts `inf`, `-inf`, `nan`, and any overlarge literal
  such as `1e400`, so `parse_retry_after` reduced a header carrying one of those
  to a non-finite "delay" and returned it as though the server had given a
  usable hint. The sleep path hid it: `inf` clamped to `max_delay` and `nan`
  failed its `> 0` test, so every retry behaved correctly. The damage landed
  only once retries were exhausted, where a caller reduces the hint to whole
  seconds to say how long to wait — `math.ceil(inf)` raises `OverflowError` and
  `math.ceil(nan)` raises `ValueError`. Both UniFi clients catch that in a broad
  handler, so the operator was told `Unexpected error: cannot convert float
  infinity to integer` instead of a wait time, and the typed 429 surface that
  0.25.1 exists to preserve was destroyed at exactly the moment it was needed.
  `1e400` is the shape that matters in practice: an ordinary overlarge integer
  in a header, nothing exotic.
- A non-finite value is now the "no usable hint" case the function already
  documented, so it yields `None` and the caller falls back to computed jittered
  backoff. The rule covers the numeric path as well as the string one, because a
  caller that parses its own header hands the number straight in.

## [0.25.1] - 2026-08-22

Re-synchronized from Fleet Core 0.25.1 in `infiquetra-claude-plugins` at commit
`ed72f439`. Custody did not move. The repair was authored, reviewed, and
released upstream, and this package took it by re-synchronization rather than by
an edit to the ported bytes, which is the rule this slice was created under and
the first time that rule has been exercised.

### Fixed

- **A `Retry-After` HTTP-date now backs the request off instead of killing the
  call.** RFC 7231 section 7.1.3 allows the header in two forms, a count of
  seconds and an absolute date, and real controllers send the date form.
  `scripts/fleet_commons/retry_backoff.py` understood only the number, so a
  caller that converted the header with `int()` raised `ValueError` inside the
  retried call. A `ValueError` carries no status code, so the primitive judged
  it non-retryable and re-raised it on the first attempt: one request, no
  backoff, and a generic error in place of a rate-limit error. The new public
  `parse_retry_after(value, *, now=time.time)` reduces either form to a
  non-negative delay in seconds, and returns `None` for an absent, empty, or
  unparseable value, which the caller reads as "no usable hint" and answers with
  computed jittered backoff. A date already in the past parses to `0.0`, never a
  negative delay. Clamping and jitter are untouched, so an absurd date and an
  absurd number are bounded identically. `retry_with_backoff` gains a
  keyword-only `now` seam so a date resolves deterministically under test, and
  the `retry_after` callable's type widens to `float | str | None`, which is
  additive.

### Changed

- **The pinned source revision.** `PROVENANCE.json` and `DEFERRED.md` now name
  commit `ed72f439` and Fleet Core `0.25.1`. The portable UniFi package pins the
  same revision, so one commit names the corrected state of the whole port.
- **The ported test suite grew from ten test functions to eighteen**, and its
  `guard-pytest-import` transform moved to version 2. Upstream's new coverage
  includes two tests carrying `@pytest.mark.parametrize`, and a decorator is
  evaluated when the module is imported. Version 1 bound `pytest` to `None` when
  the dependency was absent, which would have made the dependency-free baseline
  job raise `AttributeError` on a module it never runs. Version 2 raises
  `unittest.SkipTest` instead, which `unittest` records as one skipped test, so
  the baseline job stays green and says out loud why it collected nothing here.
- **The bundled copies shipped to consuming plugins** carry the new stamp:
  source version `0.25.1`, source commit `ed72f439`, and the new source digest.

### Known issues

- **Resolved on 2026-08-22, after this release.** The catalog's floor moved to
  `python>=3.12`, which is above what this release needs, so this release is no
  longer out of contract with the catalog that carries it. The floor moved for a
  reason larger than this one import: it now matches the floor the authoritative
  source declares and tests. See the Unreleased section above. The entry is
  preserved as written:

  > **This release needs Python 3.11 or newer, which is above the Python 3.10
  > floor this catalog documents.** The corrected module imports `UTC` from
  > `datetime`, an alias that exists only in Python 3.11 and newer, so importing
  > it under Python 3.10 raises `ImportError`. The byte-copy rule forbids
  > repairing that here: a downstream edit would make this path diverge from its
  > source and would give `retry_backoff` a second writable source. Either the
  > repair is authored upstream or the declared floor moves to 3.11. The
  > decision is open and recorded in the repository's engineering journal.

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
- The portable catalog documented a 3.10 floor at this release. That floor was
  superseded on 2026-08-22; the catalog's contract is now `python>=3.12`, as the
  Unreleased section above records. The ported module itself carries
  `from __future__ import annotations` and needs nothing beyond the standard
  library.

[0.25.1]: https://github.com/infiquetra/infiquetra-claude-plugins/releases/tag/fleet-core-0.25.1
[0.25.0]: https://github.com/infiquetra/infiquetra-claude-plugins/releases/tag/fleet-core-0.25.0
