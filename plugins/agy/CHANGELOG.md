# Changelog

## [0.6.2] - 2026-09-22

0.6.2 — imported from infiquetra-claude-plugins@acc99fe7 (upstream 0.6.1); authored here from this commit; no provenance manifest from now on.

### Changed

- The package is laid out as a portable core plus a Claude adapter. Agents and the delegate command moved under `com.infiquetra.claude/`. The root `.claude-plugin/plugin.json` only carries paths.
- `scripts/fleet_commons_shim.py` is not carried. `skills/agy-delegate/scripts/agy_delegate.py` imports `audit_store`, `bridge_receipt`, and `output_attestation` from the generated `scripts/_bundled/` directory beside it. `fleet-bundle.json` declares those three modules. `bridge_receipt` loads `output_attestation` as a sibling, and `audit_store` imports no other Fleet Core module.
- The wrapper implementation lives in the skill directory so OpenCode, Gemini CLI, Muse, and Hermes, which install that directory rather than the package root, can run it. `scripts/agy_delegate.py` remains as a launcher because the guarded-command check, the agent prompts, and the bridge discriminator all name `plugins/agy/scripts/agy_delegate.py`. The command check also accepts `skills/agy-delegate/scripts/agy_delegate.py`.
- `skills/agy-delegate/SKILL.md` now states how to run the wrapper, its flags, and that it reads no credential environment variable. The audit-store default is Fleet Core's home-relative `~/.claude/delegation-audit`, overridable with `--audit-store`.

### Dropped tests

- `tests/test_check_delegation_proof.py` — its premise is the upstream repository gate: `scripts/check_delegation_proof.py`, `marketplace/bridge_plugins.json`, `docs/delegation-proofs/`, and `.github/workflows/delegation-integrity.yml`. That is the upstream catalog layout and the marketplace format. The gate is a repository tool, not an agy package file, and this import does not take the shared catalog root (other package imports are landing on it in parallel).
- `tests/test_delegation_fleet_monitor.py` — same premise. It sweeps the upstream `docs/delegation-proofs/` tree and classifies transcripts with the upstream bridge manifest.
- `tests/test_delegation_proof_receipt.py` — same premise. It binds receipts to `docs/delegation-proofs/` and to `scripts/check_delegation_proof.py` at the upstream repository root.

The `tests/test_agy_*` modules moved under `plugins/agy/tests/` with their `tests/fixtures/agy/` fixtures. Import paths now resolve from the package root. Agent and command paths point under `com.infiquetra.claude/`.

## [Unreleased]

## [0.6.1] - 2026-08-08

### Added - house-style presentation contract on the delegation bridge agents (#704)

- `agy-coder` and `agy-reviewer` agent definitions each gain a "Presentation contract (Infiquetra house style)" section, copied verbatim from `plugins/house-style/references/subagent-presentation-preamble.md`. The reviewer relaying a delegated result now leads with the answer, situates before detailing, and names identifiers instead of gesturing at them, matching the house-style output style's main-thread rules.

## [0.6.0] - 2026-07-29

### Removed - live apply and its lease-broker fence (#671)

- `mode=auto-if-clean` and `apply_policy=apply-if-clean` are gone. Every delegation now runs in a
  disposable clone and returns a patch for the caller to apply, matching the codex plugin's
  contract. An envelope naming the retired mode is rejected as an invalid `mode` value before any
  bundle is created.
- `plugins/agy/scripts/agy_lease_admission.py` is deleted. With it go the `agy.lease-admission.v1`
  record, session admission, exact-lease acquisition and successor chaining, in-supervision lease
  renewal, settlement prepare/commit, and orphan quarantine containment. agy no longer imports
  `lease_broker` or `orphan_evidence` at all.
- CLI flags `--lease-resource-key-file` and `--lease-resource-key` are removed, along with the
  owner-private key reader and its argv redaction rules.
- Statuses `applied` and `acceptance_pending` are removed from `agy.result.v1`, and
  `git-proof.json` no longer carries `post_apply`. Bundle artifacts are otherwise unchanged —
  `run-lease.json` is the subprocess supervision record (run id, pid, timeouts, shutdown) and is
  unaffected.
- Rationale: the fence defended an external CLI more heavily than a native agent, for a collision
  that is better prevented by assigning work units that do not cross files. Recorded in
  `docs/engineering-journal/DECISIONS.md`.

### Changed - declared verification commands now actually run

- Verification is no longer reachable only from the retired apply path. Declared commands execute
  inside the disposable clone on a `patch-only` run, after the delegate's changes. Previously a
  `patch-only` run recorded `passed: null, commands: []` in `checks.json` even when the envelope
  set `verification.required: true` — the commands were silently skipped.
- **This changes terminal status on a path already in use.** A required command that fails now
  yields `checks_failed` where the run previously reported `patch_ready`. An unrequired command
  that fails is recorded in `checks.json` and leaves the run `patch_ready`.
- `checks.json` `passed` is tri-state: `null` means the commands never ran (none declared, or
  `run_scope` is not `clone`), which is not a failure.
- `no-write` runs skip verification — the clone is unchanged, so the result would prove nothing.
- `verification.run_scope` accepts `clone` or `none`; `live` is removed with the live-apply path.
- `checks.json` command entries no longer carry `lease_renewal_error`.

## [0.5.1] - 2026-07-19

### Fixed - external CLI children bypass terminal workspace wrappers

- Supervised Agy subprocesses now force `CMUX_AGENT_BYPASS=1` in the child environment. This
  prevents a caller's inherited cmux shell integration from turning a plugin-owned external CLI
  invocation into a new interactive workspace while preserving normal direct terminal launches.

## [0.5.0] - 2026-07-17

### Added - lease-fenced direct apply and orphan containment (#355)

- Direct `auto-if-clean` now resolves immutable admission in process, acquires before subprocess,
  renews during supervision, and applies verified output only inside broker commit.
- Superseded output is metadata-only; expired or post-close output is quarantined. Terminal bundles
  expose the write disposition and canonical settlement close without becoming authority.
- Launched auto apply requires a trusted key in an owner-private `0600` regular file passed as
  `--lease-resource-key-file`; the wrapper persists only its repository-scoped digest, and the raw
  key cannot arrive on argv or through the environment, envelope, prompt, bundle, or external
  engine.
- Live apply requires lease protocol 2, while validation, no-write, and patch-only modes lazy-load
  the new containment modules so an independently updated Agy remains usable during version skew.

## [0.4.0] - 2026-07-13

### Fixed - executor-construction failure no longer reports false success (#523)

`run_agy_supervised` mapped any `return_code == 0` straight to `status="success"`, regardless of
whether the process actually produced any output. Antigravity's executor-construction failure
(observed 2026-07-07 during the #468 zero-token fire drill, S1/agy/attempt1: a transient 503 on
`loadCodeAssist` left the model table empty, `agy` logged "failed to construct executor: neither
PlanModel nor RequestedModel specified" to its own log file, then exited 0 having written zero
bytes to stdout/stderr) used to emit a schema-valid success receipt with `bytes_produced: 0` —
letting engine_dispatch's #384 two-signal observer corroborate a run that did nothing as if it
had proceeded as requested.

- `run_agy_supervised` now checks `stdout_bytes == 0` alongside `return_code == 0` before deciding
  the run is a success; a zero-output exit-0 run is mapped to the existing `no_output` terminal
  status instead (not a new status — every downstream consumer that already treats `no_output` as
  non-passing, e.g. `_PASSING_STATUSES`/`_exit_code_for_status`, covers this path for free),
  carrying a named `error` explaining the no-output classification.
- `shutdown == "exited"` on the `no_output` status distinguishes this exit-0/zero-bytes path from
  the pre-existing watchdog-killed `no_output` path (silence for `no_output_seconds`); the summary
  text and `_supervised_summary` branch on that field so the two read distinctly in the bundle.
- New regression test (`test_zero_output_exit_zero_is_not_success`,
  `tests/test_agy_delegate_reliability.py`) reproduces the drill-468 S1 false-success path with a
  hermetic fake `agy` that exits 0 with no output, and proves the bundle now lands terminal
  `no_output` — never `success` — with a nonzero exit code.
- **Pre-merge review hardening (same PR):** the initial fix gated on
  `stdout_bytes + stderr_bytes == 0`, narrower than the issue's own fix direction ("empty stdout
  on an exit-0 run"). A run emitting any stderr byte (a warning/log line) alongside zero stdout on
  exit 0 still mapped to `status=success` with a corroborating `bytes_produced` receipt — the
  false-success path re-opened for the nearest-neighbor variant of the drill-468 incident. The
  condition now gates on `stdout_bytes == 0` alone (the deliverable stream), so incidental stderr
  chatter can no longer mask a no-output run as a success. New regression test
  (`test_stderr_only_exit_zero_is_not_success`, `tests/test_agy_delegate_reliability.py`) drives a
  fake `agy` that writes one stderr line and exits 0 with zero stdout, proving the bundle still
  lands terminal `no_output`.

## [0.3.0] - 2026-07-13

### Fixed - reliability-hardening parity with the codex delegate (#517)

Ports the four reliability hardenings fixed in the codex delegate for #476 (commit `437e73a`)
into `plugins/agy/scripts/agy_delegate.py`, in the agy idiom:

- **Atomic `_write_json`**: writes go through a `.tmp` sibling file plus `os.replace` instead of
  a bare `write_text` — a mid-write kill can no longer leave torn JSON in `result.json` or any
  other bundle state file.
- **`create_supervised_bundle` now catches `except Exception`, not just `except OSError`**,
  funneled through a new best-effort `_finalize_failed_bundle` that writes a terminal
  `result.json` (if one is not already present) before returning the `bundle_failed` projection —
  a non-`OSError` failure after a successful launch (e.g. receipt-emission `ValueError`) can no
  longer leave a launched run's bundle non-terminal.
- **Cumulative output byte cap**: `run_agy_supervised`'s supervise loop now enforces
  `MAX_OUTPUT_BYTES` (128 MiB) alongside the existing wall-clock and no-output watchdogs — a
  runaway `agy` process is killed and the bundle ends terminal with a named
  `MAX_OUTPUT_BYTES`-cap error instead of growing unbounded on disk. `_blocked_status_from_logs`
  (the stdout/stderr marker scan) now streams both logs line-by-line instead of `read_text`-ing
  them whole into a combined string, matching codex's streaming `parse_token_usage`.
- **SIGTERM/SIGINT die-clean handling**: `create_supervised_bundle` installs a bundle-span
  handler (`_bundle_die_clean_handler`, raising `DieCleanInterrupt`) covering the windows outside
  the supervised launch window (clone setup, verification commands, patch apply, bundle writes);
  `run_agy_supervised` installs its own non-raising handler (`_run_die_clean_handler`) for the
  launch window itself, so the supervise loop notices the flag and finishes with a normal
  terminal status instead of unwinding via exception. Either path always ends with a terminal
  `result.json` and a nonzero exit code — a caller's Bash-tool timeout can no longer kill the
  delegate mid-run and leave a non-terminal bundle. A kill that cannot reap the process (unlikely
  in agy's un-grouped single-process model, but exercised via the same monkeypatch technique as
  codex's tests) maps to the existing terminal `shutdown_incomplete` status.

## [0.2.2] - 2026-07-12

### Added - durable delegation-audit-store mirror (#396)

- `plugins/agy/scripts/agy_delegate.py`: new `--audit-store` CLI option (default
  `~/.claude/delegation-audit`). Every bundle — validation-only and supervised alike — mirrors its
  `result.json` payload (and the embedded `bridge_receipt.v1`, when the run launched) to this
  durable, machine-local store outside the repo tree, resolvable by `run_id` alone independent of
  whether the originating `.claude/agy/runs/<run_id>` bundle directory (or its enclosing disposable
  worktree) still exists. `create_validation_bundle` / `create_supervised_bundle` gained an
  `audit_store_root: Path | None = None` parameter (skip when omitted — every existing direct caller
  is unaffected; the CLI resolves the real-world default).
- Every existing subprocess-driven CLI test now passes an isolated `--audit-store <tmp_path>` so no
  test writes into a real developer's home directory.
- Consumes the new `plugins/fleet-core/scripts/fleet_commons/audit_store.py` (fleet-core 0.8.5) via
  `fleet_commons_shim.load("audit_store")`.

## [0.2.1] - 2026-07-09

### Added - output-attested bridge receipts (#388)

- `plugins/agy/scripts/agy_delegate.py`: bridge receipts now include `receipt_emitter`,
  `run_id`, `external_tokens`, and `output_attestation.v1` over the emitted summary so Saga can
  reject zero-token or unattested delegated output as `proof-integrity`.

## [0.2.0] - 2026-07-07

### Changed — BREAKING: `provenance_required` now coerces unproven passing runs to fail loud (#390 U1)

- `plugins/agy/scripts/agy_delegate.py`: a passing status (`success`/`patch_ready`/`applied`) whose
  supervision verdict (`_real_agy_verdict`) is `unproven`, combined with `provenance_required=True`
  (the envelope default), now coerces the run status to `fallback_suspected` and exits non-zero via
  the existing exit mapping. **Behavior change**: callers that previously relied on exit 0 for an
  unproven run under `provenance_required=True` (the default) will now see exit 1 —
  `provenance_required` was parsed and threaded since its introduction but consulted nowhere; this
  closes that dead wire. `provenance_required=False` preserves the old behavior unchanged, and a
  status already `fallback_suspected` via the stdout marker is not double-coerced. Transcript
  auditing stays the Stop-hook's responsibility (#384) — the wrapper's only signal is
  `_real_agy_verdict`.
- Bundle-wide status consistency: `run-lease.json` now reports the same (post-coercion) status as
  `result.json` instead of the raw pre-coercion supervisor status, and the status→exit-code
  mapping has a single source (`_PASSING_STATUSES` / `_exit_code_for_status`) shared by `main()`
  and the contract tests (#390 code-review round).

## [0.1.2] - 2026-07-06

### Added

- `plugins/agy/scripts/fleet_commons_shim.py` vendors the canonical
  `bridge_receipt.py` module (`plugins/fleet-core/scripts/fleet_commons/bridge_receipt.py`)
  byte-identical, per the established fleet-commons + vendored-shim distribution mechanism
  (`{#fleet-commons-mechanism-463}`) — `agy_delegate.py`'s `SupervisedRunResult` now maps a
  schema-valid CLI `bridge_receipt.v1` for a completed run; launch-failure paths (agy missing,
  `OSError`) emit no receipt, since there is nothing to prove. The vendored copy is covered by the
  existing vendored-copy drift guard (`tests/test_fleet_commons_resolution.py`).

## [0.1.1] - 2026-07-05

### Added

- `agy-coder` agent: add validated `effort: medium` frontmatter field, consuming the fleet
  effort convention (#363) — proves the first-class effort vocabulary applies fleet-wide, not
  saga-only.

## [0.1.0] - 2026-06-30

### Added

- Register the `agy` plugin with `/agy:delegate`, `agy-coder`, and `agy-reviewer`.
- Add the shared `agy.delegation.v1` wrapper with validation-only, supervised foreground `agy`
  launch, run leases, evidence bundles, clone-backed diff derivation, write-set enforcement, and
  guarded `patch-only` / `auto-if-clean` apply policies at
  `plugins/agy/scripts/agy_delegate.py`.
- Add static prompt-contract tests, wrapper policy tests, harness transcript auditing, and live
  Claude Code harness proof for reviewer and coder flows.
