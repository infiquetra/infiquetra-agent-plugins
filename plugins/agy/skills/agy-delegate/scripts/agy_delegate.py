#!/usr/bin/env python3
"""Antigravity delegation wrapper."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent / "_bundled"))
# The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose
# resolution ladder is Claude-specific runtime discovery this package must not
# retain. scripts/bundle_fleet_module.py writes the bundle beside this script, so
# the modules are on disk at install time and Fleet Core is never installed
# separately. bridge_receipt loads output_attestation as a sibling in that same
# directory; it is imported here as well so callers can attest output directly.
import audit_store as _audit_store  # noqa: E402
import bridge_receipt as _bridge_receipt  # noqa: E402
import output_attestation as _output_attestation  # noqa: E402

SCHEMA = "agy.delegation.v1"

ROLES = frozenset({"coder", "reviewer"})
# A delegation never writes the live tree (#671): every mode runs in a disposable clone and hands
# back a patch, matching codex's contract. Live apply (`auto-if-clean`) and the lease broker that
# fenced it are retired -- write collisions are prevented by assigning work units that do not cross
# files, not by a runtime fence around an external CLI.
MODES = frozenset({"no-write", "patch-only"})
REVIEW_LENSES = frozenset({"adversarial", "quality", "scope-gap", "security-ops"})
EVIDENCE_LEVELS = frozenset({"minimal", "summary", "full"})
APPLY_POLICIES = frozenset({"preserve-patch"})
RUN_SCOPES = frozenset({"clone", "none"})
STATUSES = frozenset(
    {
        "success",
        "patch_ready",
        "plan_gap",
        "test_conflict",
        "path_missing",
        "timeout",
        "no_output",
        "fallback_suspected",
        "out_of_scope_mutation",
        "checks_failed",
        "shutdown_incomplete",
        "bundle_failed",
        "error",
    }
)


class EnvelopeError(ValueError):
    """Raised when a delegation envelope violates the v1 contract."""


@dataclass(frozen=True)
class VerificationPolicy:
    commands: list[str]
    required: bool
    run_scope: str

    @classmethod
    def from_mapping(cls, value: Any) -> VerificationPolicy:
        if value is None:
            return cls(commands=[], required=False, run_scope="clone")
        if not isinstance(value, dict):
            raise EnvelopeError("verification must be an object")

        commands = value.get("commands", [])
        if not isinstance(commands, list) or not all(
            isinstance(command, str) and command.strip() for command in commands
        ):
            raise EnvelopeError("verification.commands must be a list of non-empty strings")

        required = value.get("required", False)
        if not isinstance(required, bool):
            raise EnvelopeError("verification.required must be a boolean")
        if required and not commands:
            raise EnvelopeError(
                "verification.commands is required when verification.required is true"
            )

        run_scope = value.get("run_scope", "clone")
        if run_scope not in RUN_SCOPES:
            raise EnvelopeError(_enum_error("verification.run_scope", run_scope, RUN_SCOPES))

        return cls(commands=commands, required=required, run_scope=run_scope)


@dataclass(frozen=True)
class Envelope:
    schema: str
    role: str
    mode: str
    task: str
    model: str
    review_lens: str | None
    write_set: list[str]
    apply_policy: str
    evidence: str
    verification: VerificationPolicy
    timeout_seconds: int
    no_output_seconds: int
    provenance_required: bool

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Envelope:
        schema = _string_field(value, "schema", default=SCHEMA)
        if schema != SCHEMA:
            raise EnvelopeError(f"schema must be {SCHEMA}")

        role = _enum_field(value, "role", ROLES)
        mode = _enum_field(value, "mode", MODES, default=_default_mode(role))
        task = _string_field(value, "task")
        model = _string_field(value, "model", default="flash")

        review_lens = value.get("review_lens")
        if review_lens is not None:
            if not isinstance(review_lens, str):
                raise EnvelopeError("review_lens must be a string or null")
            if review_lens not in REVIEW_LENSES:
                raise EnvelopeError(_enum_error("review_lens", review_lens, REVIEW_LENSES))

        write_set = _write_set(value.get("write_set", []))

        apply_policy = _enum_field(
            value,
            "apply_policy",
            APPLY_POLICIES,
            default="preserve-patch",
        )
        evidence = _enum_field(value, "evidence", EVIDENCE_LEVELS, default="summary")
        verification = VerificationPolicy.from_mapping(value.get("verification"))
        timeout_seconds = _positive_int(value, "timeout_seconds", default=900)
        no_output_seconds = _positive_int(value, "no_output_seconds", default=180)
        if no_output_seconds > timeout_seconds:
            raise EnvelopeError("no_output_seconds must be less than or equal to timeout_seconds")

        provenance_required = value.get("provenance_required", True)
        if not isinstance(provenance_required, bool):
            raise EnvelopeError("provenance_required must be a boolean")

        return cls(
            schema=schema,
            role=role,
            mode=mode,
            task=task,
            model=model,
            review_lens=review_lens,
            write_set=write_set,
            apply_policy=apply_policy,
            evidence=evidence,
            verification=verification,
            timeout_seconds=timeout_seconds,
            no_output_seconds=no_output_seconds,
            provenance_required=provenance_required,
        )

    def to_jsonable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["verification"] = asdict(self.verification)
        return payload


@dataclass(frozen=True)
class BundleResult:
    status: str
    run_id: str
    bundle_path: Path
    projection: str


@dataclass(frozen=True)
class SupervisedRunResult:
    status: str
    agy_launched: bool
    resolved_agy: str | None
    argv: list[str]
    process_id: int | None
    return_code: int | None
    started_at: datetime
    ended_at: datetime
    shutdown: str
    stdout_path: Path
    stderr_path: Path
    timeout_class: str | None
    stdout_bytes: int
    stderr_bytes: int
    error: str | None = None


@dataclass(frozen=True)
class CloneSetupResult:
    success: bool
    base_sha: str | None
    clone_path: Path
    removed_remotes: list[str]
    error: str | None = None


@dataclass(frozen=True)
class DiffEvidence:
    changed_paths: list[str]
    diff_patch_path: Path
    changed_paths_path: Path
    git_proof_path: Path


@dataclass(frozen=True)
class TranscriptClassification:
    classification: str
    agy_command_seen: bool
    claude_file_tool_seen: bool
    evidence: list[str]

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)


# agy is a black box that can emit runaway output; without a cumulative cap, spam resets the
# no-output watchdog and only the wall clock bounds it — 1-10 MB/s over the 900s default is
# 0.9-9 GB on disk and then in memory at marker-scan time. Cap and kill instead (parity with
# plugins/codex/scripts/codex_delegate.py's MAX_OUTPUT_BYTES, #476/#517).
MAX_OUTPUT_BYTES = 128 * 1024 * 1024

# Active supervised process, tracked so the SIGTERM/SIGINT die-clean handlers can kill it even
# if the signal arrives while the supervising loop is between reads (#517).
_ACTIVE_PROCESS: subprocess.Popen[bytes] | None = None
_DIE_CLEAN_SIGNAL: int | None = None


def _create_private_bundle_dir(path: Path) -> None:
    """Create the evidence-bundle boundary with owner-only traversal."""

    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(path, 0o700, follow_symlinks=False)


def _write_private_bytes(path: Path, content: bytes) -> None:
    """Atomically publish one owner-only evidence file without a permissive-mode window."""

    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(tmp_path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            payload = memoryview(content)
            while payload:
                written = os.write(fd, payload)
                payload = payload[written:]
        finally:
            os.close(fd)
        os.replace(tmp_path, path)
        os.chmod(path, 0o600, follow_symlinks=False)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()


def _write_private_text(path: Path, content: str) -> None:
    _write_private_bytes(path, content.encode("utf-8"))


class DieCleanInterrupt(BaseException):
    """Raised by the bundle-span SIGTERM/SIGINT handler to unwind through ``finally`` blocks.

    Derives from BaseException so the terminal-bundle ``except Exception`` guard in
    ``create_supervised_bundle`` cannot swallow it — it has its own dedicated handler. Raising
    (rather than terminating at default disposition) is the whole fix: default SIGTERM kills the
    interpreter without unwinding, skipping the terminal ``result.json`` write (#517).
    """

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"terminated by signal {signum}")


def _bundle_die_clean_handler(signum: int, _frame: object) -> None:
    """Bundle-span SIGTERM/SIGINT handler: kill any live agy process, then unwind (#517).

    Covers the windows OUTSIDE ``run_agy_supervised`` (clone setup, verification commands, patch
    apply, bundle writes) — the supervised loop installs its own handler and restores this one
    after.
    """
    process = _ACTIVE_PROCESS
    if process is not None and process.poll() is None:
        _terminate_process(process)
    raise DieCleanInterrupt(signum)


def _run_die_clean_handler(signum: int, _frame: object) -> None:
    """SIGTERM/SIGINT die-clean handler for the supervised launch window (#517).

    A caller's Bash-tool timeout SIGTERMs the delegate before its own wall-clock timeout can
    fire; this handler guarantees the same terminal-bundle outcome as an internal timeout — the
    agy process dies and the supervising loop notices the flag and finishes normally (no
    exception unwind needed here, unlike the bundle-span handler above).
    """
    global _DIE_CLEAN_SIGNAL
    _DIE_CLEAN_SIGNAL = signum
    process = _ACTIVE_PROCESS
    if process is not None and process.poll() is None:
        _terminate_process(process)


def parse_status(name: str) -> str:
    if name not in STATUSES:
        raise EnvelopeError(_enum_error("status", name, STATUSES))
    return name


def load_envelope(path: Path) -> Envelope:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EnvelopeError(f"envelope JSON is invalid: {exc}") from exc
    except OSError as exc:
        raise EnvelopeError(f"could not read envelope: {exc}") from exc
    if not isinstance(payload, dict):
        raise EnvelopeError("envelope must be a JSON object")
    return Envelope.from_mapping(payload)


def build_envelope_from_args(args: argparse.Namespace) -> Envelope:
    task = args.task
    if args.task_file is not None:
        try:
            task = args.task_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise EnvelopeError(f"could not read task file: {exc}") from exc

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "role": args.role,
        "mode": args.mode,
        "task": task,
        "model": args.model,
        "review_lens": args.review_lens,
        "write_set": args.write_set,
        "apply_policy": args.apply_policy,
        "evidence": args.evidence,
        "verification": {
            "commands": args.verification_command,
            "required": args.verification_required,
            "run_scope": args.verification_run_scope,
        },
        "timeout_seconds": args.timeout_seconds,
        "no_output_seconds": args.no_output_seconds,
        "provenance_required": args.provenance_required,
    }
    return Envelope.from_mapping(payload)


def _mirror_to_audit_store(
    audit_store_root: Path | None,
    run_id: str,
    result_payload: dict[str, Any],
    *,
    strict: bool = False,
) -> None:
    """Mirror ``result_payload`` (and its embedded ``receipt``, when present) to the durable store.

    A no-op when ``audit_store_root`` is ``None`` (R1/KTD5 — the CLI resolves a concrete root by
    default; direct callers, including every existing test, opt in explicitly). Never raises: a
    delegation's own result must still be returned to its caller even if the durable mirror write
    itself fails (e.g. a read-only home directory) — mirroring is additive evidence, not a gate.
    """
    if audit_store_root is None:
        return
    try:
        store = _audit_store.Store.for_root(audit_store_root).ensure()
        _audit_store.mirror_result(store, run_id, result_payload)
        receipt = result_payload.get("receipt")
        if isinstance(receipt, dict):
            _audit_store.mirror_receipt(store, run_id, receipt)
    except (OSError, _audit_store.AuditStoreError):
        if strict:
            raise


def create_validation_bundle(
    envelope: Envelope,
    *,
    repo_root: Path,
    run_id: str | None = None,
    source_envelope: Path | None = None,
    argv: list[str] | None = None,
    now: datetime | None = None,
    audit_store_root: Path | None = None,
) -> BundleResult:
    repo_root = repo_root.resolve()
    timestamp = now or datetime.now(UTC)
    resolved_run_id = run_id or _new_run_id(timestamp)
    _validate_run_id(resolved_run_id)
    bundle_path = repo_root / ".claude" / "agy" / "runs" / resolved_run_id

    try:
        _create_private_bundle_dir(bundle_path)
        envelope_payload = envelope.to_jsonable()
        prompt = render_prompt(envelope, repo_root=repo_root)
        command_payload = {
            "validation_only": True,
            "agy_launch_planned": False,
            "argv": _sanitize_argv(argv or []),
            "source_envelope": str(source_envelope) if source_envelope else None,
            "repo_root": str(repo_root),
        }
        lease_payload = {
            "run_id": resolved_run_id,
            "launch_state": "validation_only",
            "process_id": None,
            "started_at": timestamp.isoformat(),
            "ended_at": timestamp.isoformat(),
            "timeout_seconds": envelope.timeout_seconds,
            "no_output_seconds": envelope.no_output_seconds,
            "shutdown": "not_started",
        }
        result_payload = {
            "schema": "agy.result.v1",
            "status": parse_status("success"),
            "run_id": resolved_run_id,
            "bundle_path": str(bundle_path),
            "role": envelope.role,
            "mode": envelope.mode,
            "evidence": envelope.evidence,
            "validation_only": True,
            "agy_launched": False,
            "summary": "Envelope validated and evidence bundle skeleton created. agy was not launched.",
        }
        projection = render_projection(result_payload)

        _write_json(bundle_path / "envelope.json", envelope_payload)
        _write_private_text(bundle_path / "prompt.txt", prompt)
        _write_json(bundle_path / "command.json", command_payload)
        _write_json(bundle_path / "run-lease.json", lease_payload)
        _write_json(bundle_path / "result.json", result_payload)
        _write_private_text(bundle_path / "projection.md", projection)
        _mirror_to_audit_store(audit_store_root, resolved_run_id, result_payload)
    except OSError:
        projection = render_bundle_failed_projection(bundle_path)
        return BundleResult(
            status=parse_status("bundle_failed"),
            run_id=resolved_run_id,
            bundle_path=bundle_path,
            projection=projection,
        )

    return BundleResult(
        status=parse_status("success"),
        run_id=resolved_run_id,
        bundle_path=bundle_path,
        projection=projection,
    )


def _finalize_failed_bundle(bundle_path: Path, *, run_id: str, status: str, error: str) -> str:
    """Best-effort terminal record for a run that failed outside the happy path (#517).

    Every attempted run must end with an on-disk terminal status — a bundle whose
    ``result.json`` is missing is exactly the ambiguous zombie state this delegate exists to
    eliminate. If even this write fails, the projection still reports the failure loudly
    (parity with codex's ``_finalize_failed_bundle``, #476/#517).
    """
    with contextlib.suppress(OSError):
        if bundle_path.exists() and not (bundle_path / "result.json").exists():
            _write_json(
                bundle_path / "result.json",
                {
                    "schema": "agy.result.v1",
                    "run_id": run_id,
                    "bundle_path": str(bundle_path),
                    "status": status,
                    "error": error,
                    "terminal": True,
                },
            )
    return render_bundle_failed_projection(bundle_path)


def create_supervised_bundle(
    envelope: Envelope,
    *,
    repo_root: Path,
    run_id: str | None = None,
    source_envelope: Path | None = None,
    wrapper_argv: list[str] | None = None,
    agy_bin: str | None = None,
    now: datetime | None = None,
    audit_store_root: Path | None = None,
) -> BundleResult:
    repo_root = repo_root.resolve()
    timestamp = now or datetime.now(UTC)
    resolved_run_id = run_id or _new_run_id(timestamp)
    _validate_run_id(resolved_run_id)
    bundle_path = repo_root / ".claude" / "agy" / "runs" / resolved_run_id
    # Bundle-span die-clean handlers (#517): a caller's SIGTERM can arrive during clone setup,
    # verification-command execution, or bundle writes — windows OUTSIDE
    # run_agy_supervised (which installs its own handler for the launch window and restores
    # these afterward). At default disposition the interpreter dies without unwinding: no
    # terminal result.json is ever written. ValueError = non-main-thread caller; proceed
    # uncovered rather than fail.
    prior_handlers: dict[int, Any] = {}
    primary_failure: str | None = None
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            prior_handlers[signum] = signal.signal(signum, _bundle_die_clean_handler)
    except ValueError:
        prior_handlers = {}

    try:
        _create_private_bundle_dir(bundle_path)
        clone_path = bundle_path / "worktree"
        envelope_payload = envelope.to_jsonable()
        prompt = render_prompt(envelope, repo_root=clone_path)
        prompt_path = bundle_path / "prompt.txt"
        _write_private_text(prompt_path, prompt)
        _write_json(bundle_path / "envelope.json", envelope_payload)

        stdout_path = bundle_path / "stdout.log"
        stderr_path = bundle_path / "stderr.log"
        _write_private_bytes(stdout_path, b"")
        _write_private_bytes(stderr_path, b"")
        # Pre-creating the file keeps the black-box logger from selecting a group/world-readable
        # mode.
        _write_private_bytes(bundle_path / "agy.log", b"")
        checks_path = bundle_path / "checks.json"
        git_proof_path = bundle_path / "git-proof.json"
        diff_patch_path = bundle_path / "diff.patch"
        live_preflight = _live_git_status(repo_root)

        command_payload: dict[str, Any] = {
            "validation_only": False,
            "agy_launch_planned": True,
            "wrapper_argv": _sanitize_argv(wrapper_argv or []),
            "source_envelope": str(source_envelope) if source_envelope else None,
            "repo_root": str(repo_root),
            "working_directory": str(clone_path),
        }
        _write_json(bundle_path / "command.json", command_payload)

        clone_result = setup_disposable_clone(repo_root=repo_root, clone_path=clone_path)
        if not clone_result.success:
            run_result = _not_started_run_result(
                status=parse_status("error"),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                error=clone_result.error or "disposable clone setup failed",
            )
            primary_failure = run_result.error
            _write_json(
                checks_path,
                {
                    "required": envelope.verification.required,
                    "commands": [],
                    "passed": False,
                    "skipped_reason": "clone setup failed",
                },
            )
            _write_git_proof(
                git_proof_path,
                repo_root=repo_root,
                clone_result=clone_result,
                live_preflight=live_preflight,
                changed_paths=[],
                diff_patch_path=diff_patch_path,
                checks_path=checks_path,
            )
            clone_failure_payload = _result_payload(
                envelope=envelope,
                run_id=resolved_run_id,
                bundle_path=bundle_path,
                run_result=run_result,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                summary=f"disposable clone setup failed: {run_result.error}",
                changed_paths=[],
                diff_patch_path=diff_patch_path,
                checks_path=checks_path,
                clone_path=clone_path,
            )
            clone_failure_projection = render_projection(clone_failure_payload)
            _write_json(
                bundle_path / "run-lease.json",
                _run_lease_payload(
                    run_id=resolved_run_id,
                    envelope=envelope,
                    run_result=run_result,
                    repo_root=clone_path,
                ),
            )
            _write_json(bundle_path / "result.json", clone_failure_payload)
            _write_private_text(bundle_path / "projection.md", clone_failure_projection)
            _mirror_to_audit_store(audit_store_root, resolved_run_id, clone_failure_payload)
            return BundleResult(
                status=parse_status("error"),
                run_id=resolved_run_id,
                bundle_path=bundle_path,
                projection=clone_failure_projection,
            )

        run_result = run_agy_supervised(
            envelope,
            prompt=prompt,
            repo_root=clone_path,
            bundle_path=bundle_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            agy_bin=agy_bin,
        )
        blocked_status = _blocked_status_from_logs(stdout_path, stderr_path)
        if run_result.status == "success" and blocked_status is not None:
            run_result = _override_run_status(run_result, status=blocked_status)

        diff_evidence = derive_diff_evidence(
            clone_path=clone_path,
            base_sha=clone_result.base_sha or "HEAD",
            bundle_path=bundle_path,
        )
        checks_payload = {
            "required": envelope.verification.required,
            "commands": [],
            "passed": None,
        }
        result_payload: dict[str, Any] | None = None
        projection: str | None = None
        write_disposition = "forensic-only"
        final_status = parse_status(run_result.status) if run_result.status != "success" else None

        def persist_terminal(
            terminal_run: SupervisedRunResult,
            *,
            disposition: str,
            strict_mirror: bool,
        ) -> tuple[dict[str, Any], str]:
            _write_json(checks_path, checks_payload)
            _write_git_proof(
                git_proof_path,
                repo_root=repo_root,
                clone_result=clone_result,
                live_preflight=live_preflight,
                changed_paths=diff_evidence.changed_paths,
                diff_patch_path=diff_evidence.diff_patch_path,
                checks_path=checks_path,
            )
            command_payload.update(
                {
                    "agy_argv": _sanitize_argv(
                        terminal_run.argv, prompt_replacement="<prompt:prompt.txt>"
                    ),
                    "resolved_agy": terminal_run.resolved_agy,
                    "base_sha": clone_result.base_sha,
                    "clone_path": str(clone_path),
                }
            )
            _write_json(bundle_path / "command.json", command_payload)
            terminal_result = _result_payload(
                envelope=envelope,
                run_id=resolved_run_id,
                bundle_path=bundle_path,
                run_result=terminal_run,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                summary=_supervised_summary(terminal_run),
                changed_paths=diff_evidence.changed_paths,
                diff_patch_path=diff_evidence.diff_patch_path,
                checks_path=checks_path,
                clone_path=clone_path,
            )
            terminal_result["write_disposition"] = disposition
            lease_payload = _run_lease_payload(
                run_id=resolved_run_id,
                envelope=envelope,
                run_result=terminal_run,
                repo_root=clone_path,
            )
            lease_payload["status"] = terminal_result["status"]
            _write_json(bundle_path / "run-lease.json", lease_payload)
            terminal_projection = render_projection(terminal_result)
            _write_json(bundle_path / "result.json", terminal_result)
            _write_private_text(bundle_path / "projection.md", terminal_projection)
            _mirror_to_audit_store(
                audit_store_root,
                resolved_run_id,
                terminal_result,
                strict=strict_mirror,
            )
            return terminal_result, terminal_projection

        if final_status is None:
            rogue_commits = _rogue_commits(
                clone_path=clone_path,
                base_sha=clone_result.base_sha or "HEAD",
            )
            out_of_scope = _policy_out_of_scope_paths(
                envelope=envelope,
                changed_paths=diff_evidence.changed_paths,
            )
            if rogue_commits:
                final_status = parse_status("checks_failed")
                checks_payload["skipped_reason"] = "delegate created commits"
                checks_payload["rogue_commits"] = rogue_commits
            elif out_of_scope:
                final_status = parse_status("out_of_scope_mutation")
                checks_payload["skipped_reason"] = "changed paths outside write_set"
                checks_payload["out_of_scope_paths"] = out_of_scope
            else:
                # Verification runs in the disposable clone for any mode that can produce a diff
                # (#671). It used to be reachable only from the retired apply-if-clean branch, so
                # commands declared on a patch-only run were silently never executed -- checks.json
                # recorded `passed: null, commands: []` even for `required: true`.
                if envelope.mode == "patch-only":
                    checks_payload = run_verification_commands(envelope, clone_path=clone_path)
                if checks_payload["passed"] is False and envelope.verification.required:
                    final_status = parse_status("checks_failed")
                else:
                    final_status = decide_non_apply_status(
                        run_result=run_result,
                        changed_paths=diff_evidence.changed_paths,
                    )

        if final_status != run_result.status:
            run_result = _override_run_status(run_result, status=final_status)
        if result_payload is None or projection is None:
            result_payload, projection = persist_terminal(
                run_result,
                disposition=write_disposition,
                strict_mirror=False,
            )
    except DieCleanInterrupt as exc:
        # Signal arrived outside the supervised launch window: still end terminal (#517).
        primary_failure = f"terminated by signal {exc.signum} outside the supervised window"
        projection = _finalize_failed_bundle(
            bundle_path,
            run_id=resolved_run_id,
            status=parse_status("error"),
            error=primary_failure,
        )
        return BundleResult(
            status=parse_status("error"),
            run_id=resolved_run_id,
            bundle_path=bundle_path,
            projection=projection,
        )
    except OSError as exc:
        primary_failure = f"bundle write failed: {exc}"
        projection = _finalize_failed_bundle(
            bundle_path,
            run_id=resolved_run_id,
            status=parse_status("bundle_failed"),
            error=primary_failure,
        )
        return BundleResult(
            status=parse_status("bundle_failed"),
            run_id=resolved_run_id,
            bundle_path=bundle_path,
            projection=projection,
        )
    except Exception as exc:
        # Terminal-bundle guarantee over exception precision (#517): a post-launch failure
        # (receipt emission, JSON serialization) must not leave a launched run non-terminal.
        primary_failure = f"{type(exc).__name__}: {exc}"
        projection = _finalize_failed_bundle(
            bundle_path,
            run_id=resolved_run_id,
            status=parse_status("bundle_failed"),
            error=primary_failure,
        )
        return BundleResult(
            status=parse_status("bundle_failed"),
            run_id=resolved_run_id,
            bundle_path=bundle_path,
            projection=projection,
        )
    finally:
        # Restore the caller's signal disposition (#517). agy's disposable clone lives inside
        # the bundle itself (bundle_path / "worktree"), unlike codex's — there is no separate
        # teardown step to run here.
        for restore_signum, handler in prior_handlers.items():
            with contextlib.suppress(ValueError):
                signal.signal(restore_signum, handler)

    return BundleResult(
        # Source status from result_payload, not run_result.status directly: the
        # provenance_required coercion in _result_payload (R1/KTD1) may have escalated
        # a passing run_result.status to "fallback_suspected", and the exit code (main()
        # at :1167) must reflect that escalation, not the pre-coercion status.
        status=parse_status(result_payload["status"]),
        run_id=resolved_run_id,
        bundle_path=bundle_path,
        projection=projection,
    )


def run_agy_supervised(
    envelope: Envelope,
    *,
    prompt: str,
    repo_root: Path,
    bundle_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    agy_bin: str | None = None,
) -> SupervisedRunResult:
    """Launch and supervise one ``agy`` invocation (#517).

    Enforces a wall-clock timeout, a no-output watchdog, and a cumulative ``MAX_OUTPUT_BYTES``
    cap; on any of those, or on an external SIGTERM/SIGINT, the agy process is killed and a
    terminal status is returned — the on-disk state never says ``running`` behind a dead worker.
    """
    global _ACTIVE_PROCESS, _DIE_CLEAN_SIGNAL

    started_at = datetime.now(UTC)
    resolved_agy = agy_bin or shutil.which("agy")
    if resolved_agy is None:
        ended_at = datetime.now(UTC)
        return SupervisedRunResult(
            status=parse_status("error"),
            agy_launched=False,
            resolved_agy=None,
            argv=[],
            process_id=None,
            return_code=None,
            started_at=started_at,
            ended_at=ended_at,
            shutdown="not_started",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_class=None,
            stdout_bytes=0,
            stderr_bytes=0,
            error="agy executable not found",
        )

    argv = _build_agy_argv(
        resolved_agy=resolved_agy,
        envelope=envelope,
        workspace_dir=repo_root,
        prompt=prompt,
        log_path=bundle_path / "agy.log",
    )
    stdout_bytes = 0
    stderr_bytes = 0
    timeout_class: str | None = None
    shutdown = "exited"
    process_id: int | None = None
    return_code: int | None = None

    # Launch-window die-clean handler (#517): a caller's Bash-tool timeout SIGTERMs the delegate
    # before its own wall-clock timeout can fire. Unlike the bundle-span handler installed in
    # create_supervised_bundle (which raises to unwind through windows with no supervising loop
    # watching a flag), this handler just kills the process and flags _DIE_CLEAN_SIGNAL — the
    # while loop below notices the flag and finishes normally, so the run still returns a
    # regular SupervisedRunResult rather than propagating an exception. ValueError/OSError =
    # non-main-thread caller (e.g. an in-process pytest worker); proceed uncovered rather than
    # fail, the watchdog still bounds the run.
    previous_handlers: dict[int, Any] = {}
    _DIE_CLEAN_SIGNAL = None
    for signum in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError, OSError):
            previous_handlers[signum] = signal.signal(signum, _run_die_clean_handler)

    try:
        with (
            stdout_path.open("ab") as stdout_log,
            stderr_path.open("ab") as stderr_log,
        ):
            try:
                child_env = os.environ.copy()
                child_env["CMUX_AGENT_BYPASS"] = "1"
                process = subprocess.Popen(
                    argv,
                    cwd=repo_root,
                    env=child_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                )
            except OSError as exc:
                ended_at = datetime.now(UTC)
                stderr_log.write(f"failed to launch agy: {exc}\n".encode())
                return SupervisedRunResult(
                    status=parse_status("error"),
                    agy_launched=False,
                    resolved_agy=resolved_agy,
                    argv=argv,
                    process_id=None,
                    return_code=None,
                    started_at=started_at,
                    ended_at=ended_at,
                    shutdown="not_started",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    timeout_class=None,
                    stdout_bytes=0,
                    stderr_bytes=stderr_log.tell(),
                    error=str(exc),
                )

            _ACTIVE_PROCESS = process
            process_id = process.pid
            selector = selectors.DefaultSelector()
            if process.stdout is not None:
                selector.register(process.stdout, selectors.EVENT_READ, stdout_log)
            if process.stderr is not None:
                selector.register(process.stderr, selectors.EVENT_READ, stderr_log)

            start_monotonic = time.monotonic()
            last_output_monotonic = start_monotonic

            while process.poll() is None:
                if _DIE_CLEAN_SIGNAL is not None:
                    timeout_class = "die_clean"
                    shutdown = _terminate_process(process)
                    break

                events = selector.select(timeout=0.05)
                for key, _mask in events:
                    data = os.read(key.fd, 8192)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    key.data.write(data)
                    key.data.flush()
                    if key.data is stdout_log:
                        stdout_bytes += len(data)
                    else:
                        stderr_bytes += len(data)
                    last_output_monotonic = time.monotonic()

                if stdout_bytes + stderr_bytes >= MAX_OUTPUT_BYTES:
                    timeout_class = "output_limit"
                    shutdown = _terminate_process(process)
                    break

                now_monotonic = time.monotonic()
                if now_monotonic - start_monotonic >= envelope.timeout_seconds:
                    timeout_class = "timeout"
                    shutdown = _terminate_process(process)
                    break
                if now_monotonic - last_output_monotonic >= envelope.no_output_seconds:
                    timeout_class = "no_output"
                    shutdown = _terminate_process(process)
                    break

            while selector.get_map():
                events = selector.select(timeout=0.05)
                if not events:
                    break
                for key, _mask in events:
                    data = os.read(key.fd, 8192)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    key.data.write(data)
                    key.data.flush()
                    if key.data is stdout_log:
                        stdout_bytes += len(data)
                    else:
                        stderr_bytes += len(data)

            selector.close()
            return_code = process.poll()
            if return_code is None:
                try:
                    return_code = process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    return_code = None
    finally:
        _ACTIVE_PROCESS = None
        for restore_signum, handler in previous_handlers.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(restore_signum, handler)

    ended_at = datetime.now(UTC)
    signal_caught = _DIE_CLEAN_SIGNAL
    error: str | None = None
    if shutdown == "shutdown_incomplete":
        # A process that survived SIGKILL + grace is worse than any timeout class: the on-disk
        # status must flag the leak, never read as a clean termination (#517).
        status = parse_status("shutdown_incomplete")
        error = (
            f"agy process could not be reaped after {timeout_class or 'kill'}; "
            "an orphaned process may remain"
        )
    elif timeout_class == "die_clean":
        status = parse_status("error")
        error = f"terminated by signal {signal_caught}; agy process killed"
    elif timeout_class == "output_limit":
        status = parse_status("error")
        error = (
            f"cumulative output exceeded MAX_OUTPUT_BYTES ({MAX_OUTPUT_BYTES}); agy process killed"
        )
    elif timeout_class == "timeout":
        status = parse_status("timeout")
    elif timeout_class == "no_output":
        status = parse_status("no_output")
    elif return_code == 0 and stdout_bytes == 0:
        # An exit-0 run that produced zero bytes on the deliverable stream (stdout) proves
        # nothing ran to completion — e.g. Antigravity's executor-construction failure (#523,
        # drill-468 S1) exits cleanly before doing any work. Mapping that to "success" let a
        # bytes_produced=0 receipt corroborate a no-op as if it had proceeded as requested.
        # Gate on stdout alone, not stdout+stderr: a run that logs a warning/info line to stderr
        # (e.g. "W0712 executor warning") but writes nothing to stdout is still a no-output
        # failure on a prose-deliverable dispatch — stderr is not the deliverable stream, and
        # requiring both to be zero re-opened the false-success path for any run that happens to
        # emit incidental stderr chatter alongside empty stdout.
        # Reuse the existing "no_output" terminal status (not a new one) so every downstream
        # consumer that already treats "no_output" as non-passing (_PASSING_STATUSES,
        # _exit_code_for_status, decide_non_apply_status's early-return) covers this path for
        # free; `shutdown == "exited"` (rather than "terminated"/"killed") distinguishes this
        # from the watchdog-triggered no_output above.
        status = parse_status("no_output")
        error = (
            "agy exited 0 but produced zero bytes of stdout (the deliverable stream); "
            "treating as a no-output failure rather than success — likely an "
            "executor-construction failure (#523)"
        )
    elif return_code == 0:
        status = parse_status("success")
    else:
        status = parse_status("error")

    return SupervisedRunResult(
        status=status,
        agy_launched=True,
        resolved_agy=resolved_agy,
        argv=argv,
        process_id=process_id,
        return_code=return_code,
        started_at=started_at,
        ended_at=ended_at,
        shutdown=shutdown,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_class=timeout_class,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        error=error,
    )


def setup_disposable_clone(*, repo_root: Path, clone_path: Path) -> CloneSetupResult:
    base_sha_result = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
    if base_sha_result.returncode != 0:
        return CloneSetupResult(
            success=False,
            base_sha=None,
            clone_path=clone_path,
            removed_remotes=[],
            error=base_sha_result.stderr.strip() or "could not resolve live repo HEAD",
        )

    base_sha = base_sha_result.stdout.strip()
    clone_result = subprocess.run(
        ["git", "clone", "--no-hardlinks", str(repo_root), str(clone_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if clone_result.returncode != 0:
        return CloneSetupResult(
            success=False,
            base_sha=base_sha,
            clone_path=clone_path,
            removed_remotes=[],
            error=clone_result.stderr.strip() or clone_result.stdout.strip() or "git clone failed",
        )

    remotes_result = _run_git(["remote"], cwd=clone_path)
    removed_remotes = [line.strip() for line in remotes_result.stdout.splitlines() if line.strip()]
    for remote in removed_remotes:
        remove_result = _run_git(["remote", "remove", remote], cwd=clone_path)
        if remove_result.returncode != 0:
            return CloneSetupResult(
                success=False,
                base_sha=base_sha,
                clone_path=clone_path,
                removed_remotes=removed_remotes,
                error=remove_result.stderr.strip() or f"could not remove remote {remote}",
            )

    return CloneSetupResult(
        success=True,
        base_sha=base_sha,
        clone_path=clone_path,
        removed_remotes=removed_remotes,
    )


def derive_diff_evidence(*, clone_path: Path, base_sha: str, bundle_path: Path) -> DiffEvidence:
    untracked = _git_nul_lines(["ls-files", "--others", "--exclude-standard", "-z"], cwd=clone_path)
    if untracked:
        _run_git(["add", "--intent-to-add", "--", *untracked], cwd=clone_path)

    diff_patch_path = bundle_path / "diff.patch"
    diff_result = _run_git(["diff", "--binary", base_sha], cwd=clone_path)
    _write_private_text(diff_patch_path, diff_result.stdout)

    changed_paths = sorted(
        set(_git_nul_lines(["diff", "--name-only", "-z", base_sha], cwd=clone_path))
    )
    changed_paths_path = bundle_path / "changed-paths.json"
    _write_json(
        changed_paths_path,
        {
            "base_sha": base_sha,
            "changed_paths": changed_paths,
        },
    )
    return DiffEvidence(
        changed_paths=changed_paths,
        diff_patch_path=diff_patch_path,
        changed_paths_path=changed_paths_path,
        git_proof_path=bundle_path / "git-proof.json",
    )


def decide_non_apply_status(
    *,
    run_result: SupervisedRunResult,
    changed_paths: list[str],
) -> str:
    """Resolve the terminal status of a run that never touches the live tree.

    Every mode is non-apply since #671, so a successful run is ``patch_ready`` when the delegate
    changed something in the disposable clone and ``success`` when it did not.
    """

    if run_result.status != "success":
        return parse_status(run_result.status)
    return parse_status("patch_ready") if changed_paths else parse_status("success")


def run_verification_commands(
    envelope: Envelope,
    *,
    clone_path: Path,
) -> dict[str, Any]:
    """Run the envelope's verification commands inside the disposable clone.

    ``passed`` is tri-state on purpose (#671): ``None`` means the commands never ran, which is not
    a failure — only a declared command that actually ran and failed sets ``False``. The caller
    escalates to ``checks_failed`` solely when ``verification.required`` is set, so unrequired
    commands stay advisory and are still recorded in ``checks.json``.
    """

    if not envelope.verification.commands:
        return {
            "required": envelope.verification.required,
            "commands": [],
            "passed": None,
            "skipped_reason": "no verification commands declared",
        }
    if envelope.verification.run_scope != "clone":
        return {
            "required": envelope.verification.required,
            "run_scope": envelope.verification.run_scope,
            "commands": [],
            "passed": None,
            "skipped_reason": "verification must run in clone scope",
        }

    command_results: list[dict[str, Any]] = []
    passed = True
    for command in envelope.verification.commands:
        started_at = datetime.now(UTC)
        timed_out = False
        process = subprocess.Popen(  # nosec B602 - trusted operator/orchestrator command.
            command,
            shell=True,
            cwd=clone_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + envelope.timeout_seconds
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    _terminate_process(process)
                    break
                try:
                    stdout, stderr = process.communicate(timeout=min(1.0, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.poll() is None:
                _terminate_process(process)
            stdout, stderr = process.communicate()
            return_code = process.returncode
        except BaseException:
            if process.poll() is None:
                _terminate_process(process)
            raise
        ended_at = datetime.now(UTC)
        command_passed = return_code == 0 and not timed_out
        passed = passed and command_passed
        command_results.append(
            {
                "command": command,
                "cwd": str(clone_path),
                "shell": True,
                "timeout_seconds": envelope.timeout_seconds,
                "timed_out": timed_out,
                "return_code": return_code,
                "passed": command_passed,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "stdout": stdout,
                "stderr": stderr,
            }
        )

    return {
        "required": envelope.verification.required,
        "run_scope": envelope.verification.run_scope,
        "passed": passed,
        "commands": command_results,
    }


def classify_transcript(path: Path) -> TranscriptClassification:
    evidence: list[str] = []
    agy_command_seen = False
    claude_file_tool_seen = False

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            evidence.append(f"line {line_number}: invalid json")
            continue
        if not isinstance(event, dict):
            continue

        tool_name = _event_tool_name(event)
        command = _event_command(event)
        if command and _looks_like_agy_command(command):
            agy_command_seen = True
            evidence.append(f"line {line_number}: agy command via {tool_name or 'unknown'}")
        if tool_name in {"Edit", "MultiEdit", "NotebookEdit", "Write"}:
            claude_file_tool_seen = True
            evidence.append(f"line {line_number}: Claude file tool {tool_name}")

    classification = (
        "real" if agy_command_seen and not claude_file_tool_seen else "fallback_suspected"
    )
    return TranscriptClassification(
        classification=classification,
        agy_command_seen=agy_command_seen,
        claude_file_tool_seen=claude_file_tool_seen,
        evidence=evidence,
    )


def render_prompt(envelope: Envelope, *, repo_root: Path | None = None) -> str:
    lens = envelope.review_lens or "none"
    boundary = str(repo_root) if repo_root is not None else "the current repository root"
    write_set = "\n".join(f"- {path}" for path in envelope.write_set) or "- none"
    commands = "\n".join(f"- {command}" for command in envelope.verification.commands) or "- none"
    return "\n".join(
        [
            "# agy delegation packet",
            "",
            f"Schema: {envelope.schema}",
            f"Role: {envelope.role}",
            f"Mode: {envelope.mode}",
            f"Model: {envelope.model}",
            f"Review lens: {lens}",
            "",
            "## Task",
            envelope.task,
            "",
            "## Repository Boundary",
            f"Repository root: {boundary}",
            "Work in this repository root only. Do not use Antigravity's default scratch directory "
            "for repository files.",
            "",
            "## Write Set",
            write_set,
            "",
            "## Verification",
            f"Required: {str(envelope.verification.required).lower()}",
            f"Run scope: {envelope.verification.run_scope}",
            commands,
            "",
            "## Guardrails",
            "- Do not commit, push, rewrite history, or mutate paths outside the write set.",
            "- Use PLAN_GAP:, TEST_CONFLICT:, and PATH_MISSING: markers when blocked.",
        ]
    )


def render_projection(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# agy delegation projection",
            "",
            f"Status: {result['status']}",
            f"Run ID: {result['run_id']}",
            f"Bundle: {result['bundle_path']}",
            f"Role: {result['role']}",
            f"Mode: {result['mode']}",
            "",
            result["summary"],
            "",
        ]
    )


def render_bundle_failed_projection(bundle_path: Path) -> str:
    return "\n".join(
        [
            "# agy delegation projection",
            "",
            "Status: bundle_failed",
            f"Bundle: {bundle_path}",
            "",
            "The wrapper could not create or write the evidence bundle.",
            "",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or run an agy delegation envelope.")
    parser.add_argument("--envelope", type=Path, help="Path to an agy.delegation.v1 JSON envelope")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", help="Run id to use for deterministic tests")
    parser.add_argument("--launch-agy", action="store_true", help="Run agy after validation")
    parser.add_argument(
        "--validation-only", action="store_true", help="Validate without running agy"
    )
    parser.add_argument("--dry-run", action="store_true", help="Alias for --validation-only")
    parser.add_argument("--agy-bin", help="agy executable path for tests or host-specific installs")
    parser.add_argument("--role", choices=sorted(ROLES), default="coder")
    parser.add_argument("--mode", choices=sorted(MODES))
    parser.add_argument("--task", help="Delegated task text")
    parser.add_argument("--task-file", type=Path, help="Path containing delegated task text")
    parser.add_argument("--model", default="flash")
    parser.add_argument("--review-lens", choices=sorted(REVIEW_LENSES))
    parser.add_argument("--write-set", action="append", default=[])
    parser.add_argument("--apply-policy", choices=sorted(APPLY_POLICIES))
    parser.add_argument("--evidence", choices=sorted(EVIDENCE_LEVELS), default="summary")
    parser.add_argument("--verification-command", action="append", default=[])
    parser.add_argument(
        "--verification-required", action=argparse.BooleanOptionalAction, default=False
    )
    parser.add_argument("--verification-run-scope", choices=sorted(RUN_SCOPES), default="clone")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--no-output-seconds", type=int, default=180)
    parser.add_argument(
        "--provenance-required", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--audit-store",
        default=None,
        help=(
            "Durable delegation-audit store root (#396). Every bundle mirrors its result "
            "payload and receipt here, resolvable by run_id after the bundle directory is "
            "gone. Default: ~/.claude/delegation-audit"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.envelope is not None:
            envelope = load_envelope(args.envelope)
            source_envelope = args.envelope
        else:
            envelope = build_envelope_from_args(args)
            source_envelope = None

        # R1/KTD5: the CLI is the outermost entry point, so it is the one place that resolves
        # the home-dir default when --audit-store is omitted. Every underlying bundle function
        # defaults `audit_store_root` to None (skip) — a direct caller (every existing test)
        # never touches a real home directory unless it opts in.
        audit_store_root = _audit_store.Store.for_root(args.audit_store).root

        wrapper_argv = list(sys.argv[1:] if argv is None else argv)
        validation_only = args.validation_only or args.dry_run or not args.launch_agy
        resolved_run_id = args.run_id or _new_run_id(datetime.now(UTC))
        _validate_run_id(resolved_run_id)
        if validation_only:
            result = create_validation_bundle(
                envelope,
                repo_root=args.repo_root,
                run_id=resolved_run_id,
                source_envelope=source_envelope,
                argv=wrapper_argv,
                audit_store_root=audit_store_root,
            )
        else:
            result = create_supervised_bundle(
                envelope,
                repo_root=args.repo_root,
                run_id=resolved_run_id,
                source_envelope=source_envelope,
                wrapper_argv=wrapper_argv,
                agy_bin=args.agy_bin,
                audit_store_root=audit_store_root,
            )
    except (EnvelopeError, ValueError, RuntimeError) as exc:
        print(f"agy delegation envelope error: {exc}", file=sys.stderr)
        return 2

    print(result.projection, end="")
    return _exit_code_for_status(result.status)


def _default_mode(role: str) -> str:
    return "no-write" if role == "reviewer" else "patch-only"


def _enum_field(
    payload: dict[str, Any], name: str, allowed: frozenset[str], *, default: str | None = None
) -> str:
    value = payload.get(name)
    if value is None:
        value = default
    if not isinstance(value, str) or not value:
        raise EnvelopeError(f"{name} must be a non-empty string")
    if value not in allowed:
        raise EnvelopeError(_enum_error(name, value, allowed))
    return value


def _string_field(payload: dict[str, Any], name: str, *, default: str | None = None) -> str:
    value = payload.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise EnvelopeError(f"{name} must be a non-empty string")
    return value


def _positive_int(payload: dict[str, Any], name: str, *, default: int) -> int:
    value = payload.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EnvelopeError(f"{name} must be a positive integer")
    return value


def _write_set(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise EnvelopeError("write_set must be a list of relative paths")

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise EnvelopeError("write_set entries must be non-empty strings")
        path = Path(item)
        if path.is_absolute() or ".." in path.parts:
            raise EnvelopeError("write_set entries must be repo-relative paths without '..'")
        normalized.append(path.as_posix())
    return normalized


def _enum_error(name: str, value: object, allowed: frozenset[str]) -> str:
    return f"{name} has invalid value {value!r}; expected one of: {', '.join(sorted(allowed))}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically (tmp + rename) — a mid-write kill must never leave torn JSON.

    ``result.json`` is the terminal-bundle record; a partial write would present as an
    unparseable, ambiguous state to every downstream reader (parity with codex's
    ``_write_json``, #476/#517).
    """
    _write_private_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _git_nul_lines(args: list[str], *, cwd: Path) -> list[str]:
    completed = _run_git(args, cwd=cwd)
    if completed.returncode != 0 or not completed.stdout:
        return []
    return [item for item in completed.stdout.split("\0") if item]


def _live_git_status(repo_root: Path) -> dict[str, Any]:
    status = _run_git(
        ["status", "--porcelain=v1", "-z", "--", ".", ":(exclude).claude"],
        cwd=repo_root,
    )
    entries = _parse_status_z(status.stdout) if status.returncode == 0 else []
    return {
        "clean": status.returncode == 0 and not entries,
        "return_code": status.returncode,
        "stdout": status.stdout,
        "stderr": status.stderr,
        "changed_paths": sorted({path for entry in entries for path in entry["paths"]}),
    }


def _live_changed_paths(repo_root: Path) -> list[str]:
    status = _run_git(
        ["status", "--porcelain=v1", "-z", "--", ".", ":(exclude).claude"],
        cwd=repo_root,
    )
    if status.returncode != 0:
        return []
    return sorted({path for entry in _parse_status_z(status.stdout) for path in entry["paths"]})


def _rogue_commits(*, clone_path: Path, base_sha: str) -> list[str]:
    completed = _run_git(["rev-list", f"{base_sha}..HEAD"], cwd=clone_path)
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _parse_status_z(output: str) -> list[dict[str, Any]]:
    if not output:
        return []

    entries: list[dict[str, Any]] = []
    parts = output.split("\0")
    index = 0
    while index < len(parts):
        item = parts[index]
        index += 1
        if not item:
            continue
        status = item[:2]
        path = item[3:]
        paths = [path]
        if status.startswith("R") or status.startswith("C"):
            if index < len(parts) and parts[index]:
                paths.append(parts[index])
            index += 1
        entries.append({"status": status, "paths": paths})
    return entries


def _paths_outside_write_set(changed_paths: list[str], write_set: list[str]) -> list[str]:
    return [path for path in changed_paths if not _path_in_write_set(path, write_set)]


def _policy_out_of_scope_paths(*, envelope: Envelope, changed_paths: list[str]) -> list[str]:
    if not changed_paths:
        return []
    if envelope.mode == "no-write":
        return changed_paths
    if not envelope.write_set:
        return []
    return _paths_outside_write_set(changed_paths, envelope.write_set)


def _path_in_write_set(path: str, write_set: list[str]) -> bool:
    normalized_path = Path(path).as_posix()
    for allowed in write_set:
        normalized_allowed = Path(allowed).as_posix().rstrip("/")
        if normalized_path == normalized_allowed:
            return True
        if normalized_path.startswith(f"{normalized_allowed}/"):
            return True
    return False


def _not_started_run_result(
    *,
    status: str,
    stdout_path: Path,
    stderr_path: Path,
    error: str,
) -> SupervisedRunResult:
    timestamp = datetime.now(UTC)
    return SupervisedRunResult(
        status=parse_status(status),
        agy_launched=False,
        resolved_agy=None,
        argv=[],
        process_id=None,
        return_code=None,
        started_at=timestamp,
        ended_at=timestamp,
        shutdown="not_started",
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_class=None,
        stdout_bytes=0,
        stderr_bytes=0,
        error=error,
    )


def _override_run_status(run_result: SupervisedRunResult, *, status: str) -> SupervisedRunResult:
    return SupervisedRunResult(
        status=parse_status(status),
        agy_launched=run_result.agy_launched,
        resolved_agy=run_result.resolved_agy,
        argv=run_result.argv,
        process_id=run_result.process_id,
        return_code=run_result.return_code,
        started_at=run_result.started_at,
        ended_at=run_result.ended_at,
        shutdown=run_result.shutdown,
        stdout_path=run_result.stdout_path,
        stderr_path=run_result.stderr_path,
        timeout_class=run_result.timeout_class,
        stdout_bytes=run_result.stdout_bytes,
        stderr_bytes=run_result.stderr_bytes,
        error=run_result.error,
    )


def _blocked_status_from_logs(stdout_path: Path, stderr_path: Path) -> str | None:
    """Scan the supervised run's logs for blocked-status markers (#517).

    Streams both logs line-by-line rather than ``read_text``-ing them whole into a combined
    string — the logs are agy-controlled and already byte-capped by ``MAX_OUTPUT_BYTES`` in the
    supervise loop, but this scan must never assume that cap held (defense in depth, parity with
    codex's streaming ``parse_token_usage``). Marker priority is fixed by dict order, matching
    the original whole-text-search semantics: whichever marker is present is returned in the
    order below regardless of which log or line it appeared on.
    """
    markers = {
        "PLAN_GAP:": "plan_gap",
        "TEST_CONFLICT:": "test_conflict",
        "PATH_MISSING:": "path_missing",
        "FALLBACK_SUSPECTED:": "fallback_suspected",
    }
    seen: set[str] = set()
    for path in (stdout_path, stderr_path):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    for marker in markers:
                        if marker in line:
                            seen.add(marker)
        except OSError:
            continue
    for marker, status in markers.items():
        if marker in seen:
            return parse_status(status)
    return None


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _supervised_receipt(
    run_result: SupervisedRunResult,
    *,
    envelope: Envelope,
    run_id: str,
    external_tokens: int,
    output_attestation: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a ``bridge_receipt.v1`` for a run that actually launched ``agy``.

    Launch-failure paths (``agy`` missing, ``OSError`` on ``Popen``) set
    ``agy_launched=False`` and never reach here — there is nothing to prove was run, so no
    receipt is emitted and the result envelope validates without one (KTD6/KTD7).
    """
    if not run_result.agy_launched:
        return None
    wall_time_s = (run_result.ended_at - run_result.started_at).total_seconds()
    return cast(
        dict[str, Any],
        _bridge_receipt.emit_receipt(
            engine_id="agy",
            variant=envelope.model,
            transport="cli",
            wall_time_s=wall_time_s,
            bytes_produced=run_result.stdout_bytes + run_result.stderr_bytes,
            runner={
                "pid": run_result.process_id,
                "argv": run_result.argv,
                "exit_code": run_result.return_code,
            },
            receipt_emitter="agy-delegate",
            run_id=run_id,
            external_tokens=external_tokens,
            output_attestation=output_attestation,
        ),
    )


def _agy_external_tokens(run_result: SupervisedRunResult) -> int:
    return max(run_result.stdout_bytes + run_result.stderr_bytes, 0)


_PASSING_STATUSES = frozenset({"success", "patch_ready", "applied"})


def _exit_code_for_status(status: str) -> int:
    """The one status-to-process-exit mapping (single source: ``_PASSING_STATUSES``)."""
    return 0 if status in _PASSING_STATUSES else 1


def _result_payload(
    *,
    envelope: Envelope,
    run_id: str,
    bundle_path: Path,
    run_result: SupervisedRunResult,
    stdout_path: Path,
    stderr_path: Path,
    summary: str,
    changed_paths: list[str],
    diff_patch_path: Path,
    checks_path: Path,
    clone_path: Path,
) -> dict[str, Any]:
    status = parse_status(run_result.status)
    coerced_by: str | None = None
    if (
        envelope.provenance_required
        and status in _PASSING_STATUSES
        and _real_agy_verdict(run_result) == "unproven"
    ):
        # R1/KTD1: a caller that demanded provenance must not get exit 0 on a run the
        # wrapper itself cannot prove actually launched agy. classify_transcript is
        # deliberately not consulted here — transcript auditing is the Stop-hook's job
        # (#384); _real_agy_verdict is the wrapper's only in-run provenance signal.
        status = parse_status("fallback_suspected")
        coerced_by = "provenance_required"
    payload: dict[str, Any] = {
        "schema": "agy.result.v1",
        "status": status,
        "run_id": run_id,
        "bundle_path": str(bundle_path),
        "role": envelope.role,
        "mode": envelope.mode,
        "evidence": envelope.evidence,
        "validation_only": False,
        "agy_launched": run_result.agy_launched,
        "resolved_agy": run_result.resolved_agy,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "clone_path": str(clone_path),
        "changed_paths": changed_paths,
        "diff_patch": str(diff_patch_path),
        "checks_path": str(checks_path),
        "summary": summary,
    }
    receipt = _supervised_receipt(
        run_result,
        envelope=envelope,
        run_id=run_id,
        external_tokens=_agy_external_tokens(run_result),
        output_attestation=_output_attestation.emit_attestation(
            artifact="summary",
            content=summary,
        ),
    )
    if receipt is not None:
        payload["receipt"] = receipt
    if run_result.error is not None:
        payload["error"] = run_result.error
    if coerced_by is not None:
        payload["coerced_by"] = coerced_by
    return payload


def _write_git_proof(
    path: Path,
    *,
    repo_root: Path,
    clone_result: CloneSetupResult | None,
    live_preflight: dict[str, Any],
    changed_paths: list[str],
    diff_patch_path: Path,
    checks_path: Path,
) -> None:
    clone_state = _clone_git_state(clone_result)
    _write_json(
        path,
        {
            "schema": "agy.git-proof.v1",
            "repo_root": str(repo_root),
            "base_sha": clone_result.base_sha if clone_result else None,
            "clone_path": str(clone_result.clone_path) if clone_result else None,
            "clone_created": bool(clone_result and clone_result.success),
            "removed_remotes": clone_result.removed_remotes if clone_result else [],
            "clone_error": clone_result.error if clone_result else None,
            "live_preflight": live_preflight,
            "clone_head": clone_state["head"],
            "clone_post_status": clone_state["status"],
            "clone_remotes_after": clone_state["remotes_after"],
            "rogue_commits": clone_state["rogue_commits"],
            "changed_paths": changed_paths,
            "diff_patch": str(diff_patch_path),
            "checks_path": str(checks_path),
        },
    )


def _clone_git_state(clone_result: CloneSetupResult | None) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "head": None,
        "status": {"return_code": None, "entries": []},
        "remotes_after": [],
        "rogue_commits": [],
    }
    if clone_result is None or not clone_result.success:
        return empty

    head = _run_git(["rev-parse", "HEAD"], cwd=clone_result.clone_path)
    status = _run_git(["status", "--porcelain=v1", "-z"], cwd=clone_result.clone_path)
    remotes = _run_git(["remote", "-v"], cwd=clone_result.clone_path)
    return {
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "status": {
            "return_code": status.returncode,
            "entries": _parse_status_z(status.stdout) if status.returncode == 0 else [],
            "stderr": status.stderr,
        },
        "remotes_after": [line.strip() for line in remotes.stdout.splitlines() if line.strip()]
        if remotes.returncode == 0
        else [],
        "rogue_commits": _rogue_commits(
            clone_path=clone_result.clone_path,
            base_sha=clone_result.base_sha or "HEAD",
        ),
    }


def _sanitize_argv(argv: list[str], *, prompt_replacement: str | None = None) -> list[str]:
    sanitized: list[str] = []
    redact_next = False
    for token in argv:
        if prompt_replacement is not None and "\n" in token:
            sanitized.append(prompt_replacement)
            continue
        if redact_next:
            sanitized.append("<redacted>")
            redact_next = False
            continue
        lowered = token.lower()
        if lowered in {
            "--token",
            "--api-key",
            "--password",
        }:
            sanitized.append(token)
            redact_next = True
            continue
        if any(
            secret in lowered
            for secret in (
                "token=",
                "api_key=",
                "password=",
            )
        ):
            sanitized.append("<redacted>")
            continue
        sanitized.append(token)
    return sanitized


def _new_run_id(now: datetime) -> str:
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"


def _validate_run_id(run_id: str) -> None:
    if not run_id or any(char in run_id for char in "/\\"):
        raise EnvelopeError("run_id must be a non-empty path segment")


def _build_agy_argv(
    *,
    resolved_agy: str,
    envelope: Envelope,
    workspace_dir: Path,
    prompt: str,
    log_path: Path,
) -> list[str]:
    argv = [
        resolved_agy,
        "--model",
        envelope.model,
        "--print-timeout",
        f"{envelope.timeout_seconds}s",
        "--log-file",
        str(log_path),
        "--add-dir",
        str(workspace_dir),
    ]
    if envelope.mode == "no-write":
        argv.append("--sandbox")
    else:
        argv.append("--dangerously-skip-permissions")
    return [*argv, "--print", prompt]


def _terminate_process(process: subprocess.Popen[Any]) -> str:
    process.terminate()
    try:
        process.wait(timeout=1)
        return "terminated"
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=1)
            return "killed"
        except subprocess.TimeoutExpired:
            return "shutdown_incomplete"


def _run_lease_payload(
    *,
    run_id: str,
    envelope: Envelope,
    run_result: SupervisedRunResult,
    repo_root: Path,
) -> dict[str, Any]:
    elapsed_seconds = (run_result.ended_at - run_result.started_at).total_seconds()
    return {
        "run_id": run_id,
        "launch_state": "launched" if run_result.agy_launched else "not_started",
        "agy_launched": run_result.agy_launched,
        "resolved_agy": run_result.resolved_agy,
        "process_id": run_result.process_id,
        "return_code": run_result.return_code,
        "status": run_result.status,
        "started_at": run_result.started_at.isoformat(),
        "ended_at": run_result.ended_at.isoformat(),
        "elapsed_seconds": elapsed_seconds,
        "timeout_seconds": envelope.timeout_seconds,
        "no_output_seconds": envelope.no_output_seconds,
        "timeout_class": run_result.timeout_class,
        "shutdown": run_result.shutdown,
        "working_directory": str(repo_root),
        "stdout_path": str(run_result.stdout_path),
        "stderr_path": str(run_result.stderr_path),
        "stdout_bytes": run_result.stdout_bytes,
        "stderr_bytes": run_result.stderr_bytes,
        "real_agy_verdict": _real_agy_verdict(run_result),
        "error": run_result.error,
    }


def _real_agy_verdict(run_result: SupervisedRunResult) -> str:
    if (
        run_result.agy_launched
        and run_result.return_code == 0
        and run_result.timeout_class is None
        and run_result.shutdown == "exited"
    ):
        return "real"
    return "unproven"


def _supervised_summary(run_result: SupervisedRunResult) -> str:
    if run_result.status == "success":
        return "agy completed successfully under supervised foreground execution."
    if run_result.status == "patch_ready":
        return "agy completed successfully and the patch was preserved without live-tree apply."
    if run_result.status == "applied":
        return "agy completed successfully and the verified patch was applied to the live tree."
    if run_result.status == "out_of_scope_mutation":
        return "agy completed, but changed paths outside the allowed write set."
    if run_result.status == "checks_failed":
        return "agy completed, but the apply-policy checks failed."
    if run_result.status in {"plan_gap", "test_conflict", "path_missing", "fallback_suspected"}:
        return f"agy reported {run_result.status}; no patch was applied."
    if run_result.status == "timeout":
        return "agy exceeded the total timeout and was shut down."
    if run_result.status == "no_output" and run_result.shutdown == "exited":
        # Distinguishes the exit-0/zero-bytes path (#523) from the watchdog-killed path below —
        # this run was never killed, it exited on its own having produced nothing.
        return (
            "agy exited 0 but produced zero bytes of stdout/stderr; treated as a no-output "
            "failure rather than success."
        )
    if run_result.status == "no_output":
        return "agy produced no output before the no-output timeout and was shut down."
    if run_result.status == "shutdown_incomplete":
        return "agy did not shut down cleanly after timeout handling."
    if run_result.error:
        return f"agy launch failed: {run_result.error}"
    return "agy exited with a non-zero status."


def _event_tool_name(event: dict[str, Any]) -> str | None:
    for key in ("tool_name", "name"):
        value = event.get(key)
        if isinstance(value, str):
            return value

    message = event.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    name = item.get("name")
                    if isinstance(name, str):
                        return name
    return None


def _event_command(event: dict[str, Any]) -> str | None:
    for key in ("command", "cmd"):
        value = event.get(key)
        if isinstance(value, str):
            return value

    arguments = event.get("arguments") or event.get("input")
    if isinstance(arguments, dict):
        value = arguments.get("command")
        if isinstance(value, str):
            return value

    message = event.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "tool_use":
                    continue
                tool_input = item.get("input")
                if isinstance(tool_input, dict):
                    value = tool_input.get("command")
                    if isinstance(value, str):
                        return value
    return None


def _looks_like_agy_command(command: str) -> bool:
    command_lower = command.lower()
    return (
        "plugins/agy/scripts/agy_delegate.py" in command_lower
        or "skills/agy-delegate/scripts/agy_delegate.py" in command_lower
        or " --launch-agy" in command_lower
        or command_lower.startswith("agy ")
        or " agy " in command_lower
        or command_lower.endswith("/agy")
        or "/agy " in command_lower
    )


if __name__ == "__main__":
    raise SystemExit(main())
