# Changelog

## [0.1.5] - 2026-09-22

0.1.5 — imported from infiquetra-claude-plugins@acc99fe7 (upstream 0.1.4); authored here from this commit; no provenance manifest from now on.

### Changed

- `scripts/codex_delegate.py` loads `bridge_receipt` and `output_attestation` from `scripts/_bundled/`. The upstream file loaded both through one `fleet_commons_shim` import. That shape matches none of the single-module rewrite rules, so the import was rewritten by hand. `scripts/fleet_commons_shim.py` is not carried.
- `fleet-bundle.json` declares both modules. `bridge_receipt` loads `output_attestation` as a sibling, and that sibling is the same declared module, so no further Fleet Core module is added.
- Claude commands and agents moved under `com.infiquetra.claude/`. Their wrapper invocation is `${CLAUDE_PLUGIN_ROOT}/scripts/codex_delegate.py`. The upstream text used `plugins/codex/scripts/codex_delegate.py`, which is the old monorepo path.
- The portable skill documents the wrapper flags and states that the script reads no credential variable. The upstream skill told a Claude agent to call the monorepo path.
- The adapter manifest's `repository` is this repository. The relocated upstream manifest still named `infiquetra-claude-plugins`.
- Package version is `0.1.5` in the portable manifest, the root Claude manifest, and the adapter manifest.

### Tests

- Carried, with the import path pointed at `scripts/codex_delegate.py`: `test_codex_delegate_contract.py`, `test_codex_delegate_lifecycle.py`, `test_codex_delegate_modes.py`.
- Rewrote `test_codex_plugin.py` for this layout. The upstream file required `scripts/fleet_commons_shim.py`, version `0.1.4`, and the old repository URL, and it looked for commands and agents at the package root.
- Added `test_delegate_entrypoint.py`. It runs `scripts/codex_delegate.py --help` with `OPENAI_*` and `CODEX_*` removed from the environment. The repository entrypoint test skips a package that has no `PROVENANCE.json`.
- The live smoke in `test_codex_delegate_lifecycle.py` also requires `CODEX_DELEGATE_LIVE_SMOKE=1`. Authentication of a local `codex` binary is not enough. Unset, the test skips.
- No carried codex test was dropped.
- Not carried: `tests/test_check_delegation_proof.py`, `tests/test_delegation_fleet_monitor.py`, and `tests/test_delegation_proof_receipt.py`. At `acc99fe7` those files do not mention codex, and `marketplace/bridge_plugins.json` declares agy only. Landing them would add repository-root scripts, which this import does not own. `tests/test_agent_preamble_identity.py` is a repository-wide roster check, not this package's.

## [0.1.4] - 2026-08-08

### Added - house-style presentation contract on the delegation bridge agents (#704)

- `codex-coder` and `codex-reviewer` agent definitions each gain a "Presentation contract (Infiquetra house style)" section, copied verbatim from `plugins/house-style/references/subagent-presentation-preamble.md`, so a relayed codex result follows the same presentation rules as the rest of the fleet.

## [0.1.3] - 2026-07-19

### Fixed - external CLI children bypass terminal workspace wrappers

- Supervised Codex subprocesses now force `CMUX_AGENT_BYPASS=1` in the child environment. This
  keeps plugin-owned `codex exec` runs independent of inherited cmux workspace and status wrappers.

## [0.1.2] - 2026-07-10

### Changed - explicit model and effort provenance (#559)

- Include model and reasoning effort in human-readable delegation projections and use the canonical
  `<model>-<effort>` identity for receipts when both values are explicit.
- Keep direct envelopes backward-compatible when model or effort is omitted; Saga registry dispatch
  supplies both explicitly.

## [0.1.1] - 2026-07-09

### Added - output-attested bridge receipts (#388)

- `plugins/codex/scripts/codex_delegate.py`: bridge receipts now include `receipt_emitter`,
  `run_id`, parsed or byte-derived `external_tokens`, and `output_attestation.v1` over
  `last-message.txt` so Saga can reject zero-token or unattested Codex output as
  `proof-integrity`.

## [0.1.0] - 2026-07-06

### Added

- Register the `codex` plugin with `/codex:delegate`, `codex-coder`, and `codex-reviewer`.
- Add the `codex.delegation.v1` envelope schema (roles `coder`/`reviewer`, modes
  `read-only`/`task`, review lenses, evidence levels, status vocabulary) mirroring
  `agy.delegation.v1` minus members that do not apply to codex's v1 scope (KTD1).
- Add `Envelope` dataclass with fail-loud validation (`EnvelopeError`) at
  `plugins/codex/scripts/codex_delegate.py`.
- Vendor `plugins/fleet-core/scripts/fleet_commons_shim.py` byte-identically into
  `plugins/codex/scripts/fleet_commons_shim.py`, per the established fleet-commons +
  vendored-shim distribution mechanism (`{#fleet-commons-mechanism-463}`); the vendored copy is
  covered by the existing vendored-copy drift guard
  (`tests/test_fleet_commons_resolution.py`).
- Add the `bridge_receipt.v1` emitter seam (`_supervised_receipt`, parity with
  `plugins/agy/scripts/agy_delegate.py:1390-1412`): a completed run that actually launched
  `codex` maps a schema-valid CLI `bridge_receipt.v1`; launch-failure paths emit no receipt.
  This moves `codex-bridge` from `PENDING_EMITTERS` to `IN_REPO_EMITTERS` in
  `tests/test_bridge_receipt_drift.py` (KTD6).
- Add the supervised synchronous `codex exec` runner: verified 0.142.5 invocation shape
  (`exec --json -o … -s … -c model_reasoning_effort=…`, `-m` only when a model is set), prompt
  fed via stdin write-then-close, timeout and no-output watchdogs, cumulative output byte cap
  (`MAX_OUTPUT_BYTES`), whole-tree kill (process group, SIGTERM→SIGKILL escalation) with the
  kill outcome captured — an unreaped tree surfaces as terminal `shutdown_incomplete`, never as
  a clean timeout.
- Add SIGTERM/SIGINT die-clean handling across the whole bundle span (launch window AND clone
  setup / token parse / diff scan / bundle writes): kill the codex tree, write a terminal
  `result.json`, tear down the clone, exit nonzero.
- Add the evidence bundle at `.claude/codex/runs/<run-id>/` (envelope, prompt, JSONL
  transcript, last message, command argv, token accounting, `result.json` — all JSON written
  atomically via tmp+rename); every attempted run ends with an on-disk terminal status, even on
  unexpected post-launch exceptions.
- Add enforced mode surfaces: reviewer runs `-s read-only` with a snapshot-relative diff-scan
  (only NEW dirt flags `out_of_scope_mutation`; reversions of pre-existing dirt are surfaced as
  `reverted_paths`/`reversion_suspected` audit signals; the scan excludes only
  `.claude/codex/runs`, keeping the rest of `.claude` visible); coder runs confined to a
  disposable remote-stripped clone with patch capture, never the live tree.
- Add `tests/test_codex_delegate_contract.py`, `tests/test_codex_delegate_modes.py`,
  `tests/test_codex_delegate_lifecycle.py` (real-subprocess kill/terminality proofs, live smoke
  gated on `codex login status`), and `tests/test_codex_plugin.py`.

### Notes

- Invoking `codex_delegate.py` without `--validate-only`/`--dry-run` launches a live,
  supervised `codex exec` subprocess by default.
- The saga registry/dispatch rewire off `codex:codex-rescue` ships alongside this release in
  saga `0.73.1` (see `plugins/saga/CHANGELOG.md`).
