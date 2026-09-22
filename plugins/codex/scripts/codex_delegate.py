#!/usr/bin/env python3
"""Codex delegation wrapper.

First-party, guarded, synchronous codex delegation bridge mirroring the agy wrapper's shape
(``plugins/agy/scripts/agy_delegate.py``). This module ships the ``codex.delegation.v1`` schema,
the ``Envelope`` contract with fail-loud validation, the supervised ``codex exec`` runner with
timeout/no-output/die-clean termination, the evidence-bundle writer
(``.claude/codex/runs/<run-id>/``), the reviewer diff-scan and coder disposable-clone mode
surfaces, and ``bridge_receipt.v1`` emission — see
``docs/plans/2026-07-06-codex-first-party-bridge-plugin-plan.md``.

Invoking the CLI WITHOUT ``--validate-only``/``--dry-run`` launches a live, supervised
``codex exec`` subprocess; the validate-only path is opt-in, not the default.

Schema shape mirrors ``agy.delegation.v1`` minus members that do not apply to codex's v1 scope
(KTD1): codex has no ``verification`` policy and no ``apply_policy`` beyond ``preserve-patch``,
since write-capable dispatch importing a patch into the live tree is deferred (KTD5) — a ``task``
mode run always produces a patch in a disposable clone and never applies to the live tree.
"""

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
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "_bundled"))
# The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose
# resolution ladder is Claude-specific runtime discovery this package must not
# retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on
# disk at install time and Fleet Core is never installed separately. This file
# loads two modules, which is a shape the single-module rewrite does not match,
# so both imports are written here.
import bridge_receipt as _bridge_receipt  # noqa: E402
import output_attestation as _output_attestation  # noqa: E402

SCHEMA = "codex.delegation.v1"

ROLES = frozenset({"coder", "reviewer"})
# "read-only" mirrors agy's no-write posture (`codex -s read-only`); "task" is the write-capable
# mode, scoped to a disposable clone only (KTD5) — it never applies to the live tree in v1.
MODES = frozenset({"read-only", "task"})
REVIEW_LENSES = frozenset({"adversarial", "quality", "scope-gap", "security-ops"})
EVIDENCE_LEVELS = frozenset({"minimal", "summary", "full"})
# v1 has exactly one apply policy: a "task" run always preserves its patch in the evidence bundle
# and never applies to the live tree (KTD5). The field is kept for forward compatibility with a
# future write-capable dispatch mode rather than hardcoding the behavior inline.
APPLY_POLICIES = frozenset({"preserve-patch"})
STATUSES = frozenset(
    {
        "success",
        "patch_ready",
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
    """Raised when a delegation envelope violates the codex.delegation.v1 contract."""


def _default_mode(role: str) -> str:
    return "task" if role == "coder" else "read-only"


def _enum_error(field: str, value: Any, allowed: frozenset[str]) -> str:
    return f"{field} must be one of {sorted(allowed)}, got {value!r}"


def _enum_field(
    value: dict[str, Any], field: str, allowed: frozenset[str], *, default: str | None = None
) -> str:
    raw = value.get(field, default)
    if raw is None:
        raise EnvelopeError(f"{field} is required")
    if not isinstance(raw, str) or raw not in allowed:
        raise EnvelopeError(_enum_error(field, raw, allowed))
    return raw


def _string_field(value: dict[str, Any], field: str, *, default: str | None = None) -> str:
    raw = value.get(field, default)
    if raw is None:
        raise EnvelopeError(f"{field} is required")
    if not isinstance(raw, str) or not raw.strip():
        raise EnvelopeError(f"{field} must be a non-empty string")
    return raw


def _positive_int(value: dict[str, Any], field: str, *, default: int) -> int:
    raw = value.get(field, default)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        raise EnvelopeError(f"{field} must be a positive integer")
    return raw


def _write_set(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(
        isinstance(entry, str) and entry.strip() for entry in raw
    ):
        raise EnvelopeError("write_set must be a list of non-empty strings")
    return list(raw)


@dataclass(frozen=True)
class Envelope:
    schema: str
    role: str
    mode: str
    task: str
    model: str | None
    effort: str | None
    review_lens: str | None
    write_set: list[str]
    apply_policy: str
    evidence: str
    timeout_seconds: int
    no_output_seconds: int
    provenance_required: bool

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Envelope:
        if not isinstance(value, dict):
            raise EnvelopeError("envelope must be a JSON object")

        schema = value.get("schema", SCHEMA)
        if schema != SCHEMA:
            raise EnvelopeError(f"schema must be {SCHEMA}")

        role = _enum_field(value, "role", ROLES)
        mode = _enum_field(value, "mode", MODES, default=_default_mode(role))
        task = _string_field(value, "task")

        model = value.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise EnvelopeError("model must be a non-empty string or null")

        effort = value.get("effort")
        if effort is not None and (not isinstance(effort, str) or not effort.strip()):
            raise EnvelopeError("effort must be a non-empty string or null")

        review_lens = value.get("review_lens")
        if review_lens is not None and (
            not isinstance(review_lens, str) or review_lens not in REVIEW_LENSES
        ):
            raise EnvelopeError(_enum_error("review_lens", review_lens, REVIEW_LENSES))
        if role == "reviewer" and review_lens is None:
            review_lens = "adversarial"

        write_set = _write_set(value.get("write_set", []))
        if mode == "task" and not write_set:
            raise EnvelopeError("task mode requires a non-empty write_set")
        if role == "reviewer" and write_set:
            raise EnvelopeError("reviewer role must not carry a write_set")

        apply_policy = _enum_field(value, "apply_policy", APPLY_POLICIES, default="preserve-patch")
        evidence = _enum_field(value, "evidence", EVIDENCE_LEVELS, default="summary")
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
            effort=effort,
            review_lens=review_lens,
            write_set=write_set,
            apply_policy=apply_policy,
            evidence=evidence,
            timeout_seconds=timeout_seconds,
            no_output_seconds=no_output_seconds,
            provenance_required=provenance_required,
        )

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)


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
        "task": task,
        "model": args.model,
        "effort": args.effort,
        "review_lens": args.review_lens,
        "write_set": args.write_set,
        "apply_policy": args.apply_policy,
        "evidence": args.evidence,
        "timeout_seconds": args.timeout_seconds,
        "no_output_seconds": args.no_output_seconds,
        "provenance_required": args.provenance_required,
    }
    if args.mode is not None:
        payload["mode"] = args.mode
    return Envelope.from_mapping(payload)


@dataclass(frozen=True)
class SupervisedRunResult:
    """Terminal outcome of one supervised ``codex exec`` invocation.

    The full supervising loop (process launch, timeout/no-output watchdog, SIGTERM/SIGINT
    die-clean handling) lands in U2; this shape exists now so the receipt seam (U1/R8) has a
    stable, testable contract to build against.
    """

    status: str
    codex_launched: bool
    resolved_codex: str | None
    argv: list[str]
    process_id: int | None
    return_code: int | None
    started_at: datetime
    ended_at: datetime
    stdout_bytes: int
    stderr_bytes: int
    error: str | None = None


def _supervised_receipt(
    run_result: SupervisedRunResult,
    *,
    envelope: Envelope,
    run_id: str,
    external_tokens: int,
    output_attestation: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a ``bridge_receipt.v1`` for a run that actually launched ``codex``.

    Launch-failure paths (``codex`` missing, ``OSError`` on process start) set
    ``codex_launched=False`` and never reach here — there is nothing to prove was run, so no
    receipt is emitted (parity with agy's ``_supervised_receipt``,
    ``plugins/agy/scripts/agy_delegate.py:1390-1412``).
    """
    if not run_result.codex_launched:
        return None
    wall_time_s = (run_result.ended_at - run_result.started_at).total_seconds()
    variant = (
        f"{envelope.model}-{envelope.effort}"
        if envelope.model and envelope.effort
        else envelope.model or "default"
    )
    return _bridge_receipt.emit_receipt(
        engine_id="codex",
        variant=variant,
        transport="cli",
        wall_time_s=wall_time_s,
        bytes_produced=run_result.stdout_bytes + run_result.stderr_bytes,
        runner={
            "pid": run_result.process_id,
            "argv": run_result.argv,
            "exit_code": run_result.return_code,
        },
        receipt_emitter="codex-bridge",
        run_id=run_id,
        external_tokens=external_tokens,
        output_attestation=output_attestation,
    )


def _codex_external_tokens(
    token_usage: dict[str, int | None], _run_result: SupervisedRunResult
) -> int:
    total = token_usage.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool) and total > 0:
        return total
    return 0


def _read_attestation_artifact(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


@dataclass(frozen=True)
class BundleResult:
    """Terminal outcome of one delegation: the on-disk bundle plus its projection."""

    status: str
    run_id: str
    bundle_path: Path
    projection: str


# Mode → codex sandbox flag (``-s``). "read-only" mirrors agy's no-write reviewer posture;
# "task" runs write-capable, scoped to the disposable clone (KTD3/KTD5).
_SANDBOX_BY_MODE = {"read-only": "read-only", "task": "workspace-write"}

_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "total_tokens"})

# codex is a black box that can emit runaway output; without a cumulative cap, spam resets the
# no-output watchdog and only the wall clock bounds it — 1-10 MB/s over the 900 s default is
# 0.9-9 GB on disk and then in memory at token-parse time. Cap and kill instead.
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_LAST_MESSAGE_BYTES = 8 * 1024 * 1024

# Active supervised process, tracked so the SIGTERM/SIGINT die-clean handler can kill the codex
# process tree even if the signal arrives while the supervising loop is between reads (R4).
_ACTIVE_PROCESS: subprocess.Popen[bytes] | None = None
_DIE_CLEAN_SIGNAL: int | None = None


class DieCleanInterrupt(BaseException):
    """Raised by the bundle-scope SIGTERM/SIGINT handler to unwind through ``finally`` blocks.

    Derives from BaseException so the terminal-bundle ``except Exception`` guard in
    ``create_supervised_bundle`` cannot swallow it — it has its own dedicated handler. Raising
    (rather than terminating at default disposition) is the whole fix: default SIGTERM kills the
    interpreter without unwinding, skipping clone teardown and the terminal ``result.json`` (R4).
    """

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"terminated by signal {signum}")


def _bundle_die_clean_handler(signum: int, _frame: object) -> None:
    """Bundle-span SIGTERM/SIGINT handler: kill any live codex tree, then unwind (R4).

    Covers the windows OUTSIDE ``run_codex_supervised`` (clone setup, token parse, diff scan,
    bundle writes) — the supervised loop installs its own handler and restores this one after.
    """
    process = _ACTIVE_PROCESS
    if process is not None and process.poll() is None:
        _kill_process_tree(process)
    raise DieCleanInterrupt(signum)


def _sandbox_for_mode(mode: str) -> str:
    return _SANDBOX_BY_MODE.get(mode, "read-only")


def _new_run_id(now: datetime) -> str:
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"


def _validate_run_id(run_id: str) -> None:
    if not run_id or any(char in run_id for char in "/\\"):
        raise EnvelopeError("run_id must be a non-empty path segment")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically (tmp + rename) — a mid-write kill must never leave torn JSON.

    ``result.json`` is the terminal-bundle record; a partial write would present as an
    unparseable, ambiguous state to every downstream reader.
    """
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


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
        if lowered in {"--token", "--api-key", "--password"}:
            sanitized.append(token)
            redact_next = True
            continue
        if any(secret in lowered for secret in ("token=", "api_key=", "password=")):
            sanitized.append("<redacted>")
            continue
        sanitized.append(token)
    return sanitized


def render_prompt(envelope: Envelope, *, repo_root: Path | None = None) -> str:
    lens = envelope.review_lens or "none"
    boundary = str(repo_root) if repo_root is not None else "the current repository root"
    write_set = "\n".join(f"- {path}" for path in envelope.write_set) or "- none"
    return "\n".join(
        [
            "# codex delegation packet",
            "",
            f"Schema: {envelope.schema}",
            f"Role: {envelope.role}",
            f"Mode: {envelope.mode}",
            f"Model: {envelope.model or '<user config default>'}",
            f"Review lens: {lens}",
            "",
            "## Task",
            envelope.task,
            "",
            "## Repository Boundary",
            f"Repository root: {boundary}",
            "Work in this repository root only.",
            "",
            "## Write Set",
            write_set,
            "",
            "## Guardrails",
            "- Do not commit, push, rewrite history, or mutate paths outside the write set.",
            "- Reviewer runs are read-only: do not mutate the workspace.",
        ]
    )


def render_projection(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# codex delegation projection",
            "",
            f"Status: {result['status']}",
            f"Run ID: {result['run_id']}",
            f"Bundle: {result['bundle_path']}",
            f"Role: {result['role']}",
            f"Mode: {result['mode']}",
            f"Model: {result.get('model') or '<user config default>'}",
            f"Effort: {result.get('effort') or '<user config default>'}",
            "",
            result["summary"],
            "",
        ]
    )


def render_bundle_failed_projection(bundle_path: Path) -> str:
    return "\n".join(
        [
            "# codex delegation projection",
            "",
            "Status: bundle_failed",
            f"Bundle: {bundle_path}",
            "",
            "The wrapper could not create or write the evidence bundle.",
            "",
        ]
    )


def _build_codex_argv(
    *,
    resolved_codex: str,
    envelope: Envelope,
    last_message_path: Path,
    sandbox: str,
    clone_path: Path | None = None,
) -> list[str]:
    """Build the ``codex exec`` argv per KTD3 (verified live on codex-cli 0.142.5).

    ``--effort`` is NOT a flag on 0.142.5 — reasoning effort rides ``-c
    model_reasoning_effort=<effort>``. ``-m`` is omitted when the envelope names no model so
    codex falls back to the user config default. The prompt is delivered via stdin (closed
    write), never argv, keeping large prompts out of a ps-visible command line.

    Coder (``task``) runs execute inside a disposable, remotes-stripped clone: ``--cd <clone>``
    scopes codex to the clone and ``--skip-git-repo-check`` lets it run there without tripping
    the git-repo guard (R2, KTD5). The live primary tree is never handed to codex on a coder
    run — only reviewer (read-only) runs point codex at the live repo.
    """
    argv = [
        resolved_codex,
        "exec",
        "--json",
        "-o",
        str(last_message_path),
        "-s",
        sandbox,
    ]
    if clone_path is not None:
        argv += ["--cd", str(clone_path), "--skip-git-repo-check"]
    if envelope.model:
        argv += ["-m", envelope.model]
    if envelope.effort:
        argv += ["-c", f"model_reasoning_effort={envelope.effort}"]
    argv.append("--ephemeral")
    return argv


def _kill_process_tree(process: subprocess.Popen[bytes]) -> str:
    """Kill the codex process tree (its own session group) and report the shutdown outcome."""
    pgid: int | None
    try:
        pgid = os.getpgid(process.pid)
    except (ProcessLookupError, OSError):
        pgid = None

    if pgid is not None:
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(pgid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
            return "terminated"
        except subprocess.TimeoutExpired:
            pass
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(pgid, signal.SIGKILL)
    else:
        process.kill()

    try:
        process.wait(timeout=2)
        return "killed"
    except subprocess.TimeoutExpired:
        return "shutdown_incomplete"


def _die_clean_handler(signum: int, _frame: Any) -> None:
    """SIGTERM/SIGINT die-clean handler: kill the codex tree, flag the loop to finalize (R4).

    A caller's Bash-tool timeout SIGTERMs the delegate before its own wall-clock timeout can
    fire; this handler guarantees the same terminal-bundle outcome as an internal timeout —
    the codex process tree dies and on-disk state never says ``running``.
    """
    global _DIE_CLEAN_SIGNAL
    _DIE_CLEAN_SIGNAL = signum
    process = _ACTIVE_PROCESS
    if process is not None and process.poll() is None:
        _kill_process_tree(process)


def _feed_stdin(process: subprocess.Popen[bytes], prompt: str) -> None:
    """Write the prompt to codex's stdin and EXPLICITLY close it.

    codex appends piped stdin as a ``<stdin>`` block and blocks reading an open pipe — the
    close is load-bearing, not hygiene. Runs on a thread so a large prompt filling the pipe
    buffer cannot deadlock against the supervising read loop.
    """
    try:
        if process.stdin is not None:
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.flush()
            process.stdin.close()
    except (BrokenPipeError, OSError):
        pass


def run_codex_supervised(
    envelope: Envelope,
    *,
    prompt: str,
    repo_root: Path,
    transcript_path: Path,
    stderr_path: Path,
    last_message_path: Path,
    sandbox: str,
    codex_bin: str | None = None,
    clone_path: Path | None = None,
) -> SupervisedRunResult:
    """Launch and supervise one ``codex exec`` invocation (KTD2/KTD3, R4).

    Enforces a wall-clock timeout and a no-output watchdog; on either expiry, or on an external
    SIGTERM/SIGINT, the codex process tree is killed and a terminal status is returned — the
    on-disk state never says ``running`` behind a dead worker.

    When ``clone_path`` is set (coder/``task`` runs) codex is scoped to the disposable clone via
    ``--cd``/``--skip-git-repo-check`` and the child's cwd is the clone — the live primary tree is
    never the working directory of a write-capable run (R2, KTD5).
    """
    global _ACTIVE_PROCESS, _DIE_CLEAN_SIGNAL

    started_at = datetime.now(UTC)
    resolved_codex = codex_bin or shutil.which("codex")
    if not resolved_codex:
        return SupervisedRunResult(
            status=parse_status("error"),
            codex_launched=False,
            resolved_codex=None,
            argv=[],
            process_id=None,
            return_code=None,
            started_at=started_at,
            ended_at=datetime.now(UTC),
            stdout_bytes=0,
            stderr_bytes=0,
            error="codex executable not found",
        )

    argv = _build_codex_argv(
        resolved_codex=resolved_codex,
        envelope=envelope,
        last_message_path=last_message_path,
        sandbox=sandbox,
        clone_path=clone_path,
    )
    workdir = clone_path if clone_path is not None else repo_root

    stdout_bytes = 0
    stderr_bytes = 0
    timeout_class: str | None = None
    process_id: int | None = None
    return_code: int | None = None

    previous_handlers: dict[int, Any] = {}
    _DIE_CLEAN_SIGNAL = None
    for signum in (signal.SIGTERM, signal.SIGINT):
        # Not on the main thread (e.g. in-process pytest worker) ⇒ skip; the watchdog still fires.
        with contextlib.suppress(ValueError, OSError):
            previous_handlers[signum] = signal.signal(signum, _die_clean_handler)

    try:
        with (
            transcript_path.open("ab") as stdout_log,
            stderr_path.open("ab") as stderr_log,
        ):
            try:
                child_env = os.environ.copy()
                child_env["CMUX_AGENT_BYPASS"] = "1"
                process = subprocess.Popen(
                    argv,
                    cwd=workdir,
                    env=child_env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    start_new_session=True,
                )
            except OSError as exc:
                stderr_log.write(f"failed to launch codex: {exc}\n".encode())
                return SupervisedRunResult(
                    status=parse_status("error"),
                    codex_launched=False,
                    resolved_codex=resolved_codex,
                    argv=argv,
                    process_id=None,
                    return_code=None,
                    started_at=started_at,
                    ended_at=datetime.now(UTC),
                    stdout_bytes=0,
                    stderr_bytes=stderr_log.tell(),
                    error=str(exc),
                )

            _ACTIVE_PROCESS = process
            process_id = process.pid

            writer = threading.Thread(target=_feed_stdin, args=(process, prompt), daemon=True)
            writer.start()

            selector = selectors.DefaultSelector()
            if process.stdout is not None:
                selector.register(process.stdout, selectors.EVENT_READ, stdout_log)
            if process.stderr is not None:
                selector.register(process.stderr, selectors.EVENT_READ, stderr_log)

            start_monotonic = time.monotonic()
            last_output_monotonic = start_monotonic
            shutdown_outcome: str | None = None

            while process.poll() is None:
                if _DIE_CLEAN_SIGNAL is not None:
                    timeout_class = "die_clean"
                    shutdown_outcome = _kill_process_tree(process)
                    break

                events = selector.select(timeout=0.05)
                for key, _mask in events:
                    data = os.read(key.fileobj.fileno(), 8192)
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
                    shutdown_outcome = _kill_process_tree(process)
                    break

                now_monotonic = time.monotonic()
                if now_monotonic - start_monotonic >= envelope.timeout_seconds:
                    timeout_class = "timeout"
                    shutdown_outcome = _kill_process_tree(process)
                    break
                if now_monotonic - last_output_monotonic >= envelope.no_output_seconds:
                    timeout_class = "no_output"
                    shutdown_outcome = _kill_process_tree(process)
                    break

            # Drain any remaining buffered output after the process exited or was killed.
            while selector.get_map():
                events = selector.select(timeout=0.05)
                if not events:
                    break
                for key, _mask in events:
                    data = os.read(key.fileobj.fileno(), 8192)
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
                    return_code = process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    return_code = None
    finally:
        _ACTIVE_PROCESS = None
        for signum, handler in previous_handlers.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signum, handler)

    ended_at = datetime.now(UTC)
    signal_caught = _DIE_CLEAN_SIGNAL
    error: str | None = None
    if shutdown_outcome == "shutdown_incomplete":
        # A tree that survived SIGKILL + grace is worse than any timeout class: the on-disk
        # status must flag the leaked processes, never read as a clean termination (R4;
        # parity with agy_delegate's shutdown mapping).
        status = parse_status("shutdown_incomplete")
        error = (
            f"codex process tree could not be fully reaped after {timeout_class or 'kill'};"
            " orphaned processes may remain"
        )
    elif timeout_class == "die_clean":
        status = parse_status("error")
        error = f"terminated by signal {signal_caught}; codex process tree killed"
    elif timeout_class == "output_limit":
        status = parse_status("error")
        error = (
            f"cumulative output exceeded MAX_OUTPUT_BYTES ({MAX_OUTPUT_BYTES}); "
            "codex process tree killed"
        )
    elif timeout_class == "timeout":
        status = parse_status("timeout")
    elif timeout_class == "no_output":
        status = parse_status("no_output")
    elif return_code == 0:
        status = parse_status("success")
    else:
        status = parse_status("error")
        error = f"codex exec exited with return code {return_code}"

    return SupervisedRunResult(
        status=status,
        codex_launched=True,
        resolved_codex=resolved_codex,
        argv=argv,
        process_id=process_id,
        return_code=return_code,
        started_at=started_at,
        ended_at=ended_at,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        error=error,
    )


def _find_usage(obj: Any) -> dict[str, int]:
    found: dict[str, int] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _USAGE_KEYS and isinstance(value, int) and not isinstance(value, bool):
                found[key] = value
            else:
                found.update(_find_usage(value))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_find_usage(item))
    return found


def parse_token_usage(transcript_path: Path) -> dict[str, int | None]:
    """Best-effort token accounting from the raw JSONL transcript (KTD3).

    Tolerant of malformed lines and schema drift across codex versions — always returns a
    dict, degrading each field to ``None`` rather than ever failing the run.
    """
    usage: dict[str, int | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    try:
        # Stream line-by-line: the transcript is codex-controlled and byte-capped only at the
        # supervise loop, so never slurp the whole file into memory here.
        with transcript_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                for key, value in _find_usage(event).items():
                    usage[key] = value
    except OSError:
        return usage
    return usage


def _supervised_summary(run_result: SupervisedRunResult) -> str:
    if not run_result.codex_launched:
        return f"codex was not launched: {run_result.error or 'launch failed'}"
    if run_result.status == "success":
        return "codex exec completed successfully under supervised synchronous execution."
    if run_result.status == "timeout":
        return "codex exec exceeded the wall-clock timeout; process tree was killed."
    if run_result.status == "no_output":
        return "codex exec produced no output within the watchdog window; process tree was killed."
    if run_result.status == "shutdown_incomplete":
        return (
            "codex process tree could not be fully reaped after kill; "
            "orphaned processes may remain."
        )
    if run_result.error:
        return f"codex exec ended with status {run_result.status}: {run_result.error}"
    return f"codex exec ended with status {run_result.status}."


def _result_payload(
    *,
    envelope: Envelope,
    run_id: str,
    bundle_path: Path,
    run_result: SupervisedRunResult,
    token_usage: dict[str, int | None],
    last_message_path: Path,
    receipt_emitted: bool,
) -> dict[str, Any]:
    elapsed_seconds = (run_result.ended_at - run_result.started_at).total_seconds()
    last_message_present = False
    try:
        # Bounded read: codex writes this file; a runaway payload must not be slurped whole.
        with last_message_path.open("r", encoding="utf-8", errors="replace") as handle:
            last_message_present = bool(handle.read(MAX_LAST_MESSAGE_BYTES).strip())
    except OSError:
        last_message_present = False
    return {
        "schema": "codex.result.v1",
        "status": run_result.status,
        "run_id": run_id,
        "bundle_path": str(bundle_path),
        "role": envelope.role,
        "mode": envelope.mode,
        "model": envelope.model,
        "effort": envelope.effort,
        "evidence": envelope.evidence,
        "codex_launched": run_result.codex_launched,
        "resolved_codex": run_result.resolved_codex,
        "process_id": run_result.process_id,
        "return_code": run_result.return_code,
        "argv": _sanitize_argv(run_result.argv),
        "started_at": run_result.started_at.isoformat(),
        "ended_at": run_result.ended_at.isoformat(),
        "elapsed_seconds": elapsed_seconds,
        "stdout_bytes": run_result.stdout_bytes,
        "stderr_bytes": run_result.stderr_bytes,
        "token_usage": token_usage,
        "receipt_emitted": receipt_emitted,
        "last_message_present": last_message_present,
        "summary": _supervised_summary(run_result),
        "error": run_result.error,
    }


def create_validation_bundle(
    envelope: Envelope,
    *,
    repo_root: Path,
    run_id: str | None = None,
    source_envelope: Path | None = None,
    argv: list[str] | None = None,
    now: datetime | None = None,
) -> BundleResult:
    """Write the bundle skeleton without launching codex (--validate-only/--dry-run)."""
    repo_root = repo_root.resolve()
    timestamp = now or datetime.now(UTC)
    resolved_run_id = run_id or _new_run_id(timestamp)
    _validate_run_id(resolved_run_id)
    bundle_path = repo_root / ".claude" / "codex" / "runs" / resolved_run_id

    try:
        bundle_path.mkdir(parents=True, exist_ok=False)
        prompt = render_prompt(envelope, repo_root=repo_root)
        _write_json(bundle_path / "envelope.json", envelope.to_jsonable())
        (bundle_path / "prompt.txt").write_text(prompt, encoding="utf-8")
        command_payload = {
            "validation_only": True,
            "codex_launch_planned": False,
            "argv": _sanitize_argv(argv or []),
            "source_envelope": str(source_envelope) if source_envelope else None,
            "repo_root": str(repo_root),
            "sandbox": _sandbox_for_mode(envelope.mode),
        }
        _write_json(bundle_path / "command.json", command_payload)
        result_payload = {
            "schema": "codex.result.v1",
            "status": parse_status("success"),
            "run_id": resolved_run_id,
            "bundle_path": str(bundle_path),
            "role": envelope.role,
            "mode": envelope.mode,
            "evidence": envelope.evidence,
            "validation_only": True,
            "codex_launched": False,
            "summary": "Envelope validated and bundle skeleton created. codex was not launched.",
        }
        _write_json(bundle_path / "result.json", result_payload)
        projection = render_projection(result_payload)
        (bundle_path / "projection.md").write_text(projection, encoding="utf-8")
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


# ---------------------------------------------------------------------------
# U3 mode surfaces: reviewer read-only diff-scan proof + coder disposable clone
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CloneSetupResult:
    """Outcome of standing up a disposable, remotes-stripped clone for a coder run."""

    success: bool
    base_sha: str | None
    clone_path: Path
    removed_remotes: list[str]
    error: str | None = None


@dataclass(frozen=True)
class DiffEvidence:
    """Patch-capture evidence from a coder run's disposable clone (preserve-patch, KTD5)."""

    changed_paths: list[str]
    out_of_scope_paths: list[str]
    diff_patch_path: Path
    changed_paths_path: Path


@dataclass(frozen=True)
class ReviewerScan:
    """Post-run non-mutation proof for a reviewer (read-only) run against the live tree."""

    baseline_dirty: list[str]
    post_dirty: list[str]
    new_paths: list[str]
    reverted_paths: list[str]
    diff_scan_path: Path
    mutation_patch_path: Path | None


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


def _parse_status_z(output: str) -> list[str]:
    """Parse ``git status --porcelain=v1 -z`` into the set of touched paths."""
    if not output:
        return []
    parts = output.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(parts):
        item = parts[index]
        index += 1
        if not item:
            continue
        status = item[:2]
        paths.append(item[3:])
        # Rename/copy entries carry the origin path in the following NUL field.
        if status.startswith("R") or status.startswith("C"):
            if index < len(parts) and parts[index]:
                paths.append(parts[index])
            index += 1
    return paths


def _porcelain_paths(repo_root: Path) -> list[str]:
    """Snapshot the set of dirty paths in ``repo_root`` (excludes ``.claude/codex/runs`` only).

    Evidence bundles are written under ``.claude/codex/runs`` in the live tree, so that subtree
    (any run — concurrent siblings must not false-positive) is excluded from the reviewer
    diff-scan. The rest of ``.claude`` (settings, hooks, other plugins' state) stays VISIBLE:
    this scan is the defense-in-depth check for a fail-open codex sandbox, and those paths are
    exactly where tampering would be most valuable.
    """
    status = _run_git(
        ["status", "--porcelain=v1", "-z", "--", ".", ":(exclude).claude/codex/runs"],
        cwd=repo_root,
    )
    if status.returncode != 0:
        return []
    return sorted(set(_parse_status_z(status.stdout)))


def _path_in_write_set(path: str, write_set: list[str]) -> bool:
    normalized_path = Path(path).as_posix()
    for allowed in write_set:
        normalized_allowed = Path(allowed).as_posix().rstrip("/")
        if normalized_path == normalized_allowed:
            return True
        if normalized_path.startswith(f"{normalized_allowed}/"):
            return True
    return False


def _paths_outside_write_set(changed_paths: list[str], write_set: list[str]) -> list[str]:
    if not write_set:
        return list(changed_paths)
    return [path for path in changed_paths if not _path_in_write_set(path, write_set)]


def setup_disposable_clone(*, repo_root: Path, clone_path: Path) -> CloneSetupResult:
    """Stand up a disposable ``--no-hardlinks`` clone and strip every remote (R2, KTD5).

    A coder run mutates only this clone; stripping remotes makes an accidental push impossible,
    and the caller tears the clone down on both success and failure so nothing leaks.
    """
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

    remotes = [line.strip() for line in _run_git(["remote"], cwd=clone_path).stdout.splitlines()]
    removed_remotes = [remote for remote in remotes if remote]
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


def teardown_clone(clone_path: Path) -> None:
    """Remove the disposable clone. Best-effort — teardown must never mask the run's outcome."""
    with contextlib.suppress(OSError):
        shutil.rmtree(clone_path, ignore_errors=True)


def derive_diff_evidence(
    *, clone_path: Path, base_sha: str, bundle_path: Path, write_set: list[str]
) -> DiffEvidence:
    """Capture the coder run's clone diff as a preserved patch and score write_set scoping.

    The patch is written into the bundle (which lives in the live tree) *before* the clone is
    torn down, so the evidence survives teardown. Nothing is ever applied to the live tree (KTD5).
    """
    untracked = _git_nul_lines(["ls-files", "--others", "--exclude-standard", "-z"], cwd=clone_path)
    if untracked:
        _run_git(["add", "--intent-to-add", "--", *untracked], cwd=clone_path)

    diff_patch_path = bundle_path / "diff.patch"
    diff_result = _run_git(["diff", "--binary", base_sha], cwd=clone_path)
    diff_patch_path.write_text(diff_result.stdout, encoding="utf-8")

    changed_paths = sorted(
        set(_git_nul_lines(["diff", "--name-only", "-z", base_sha], cwd=clone_path))
    )
    out_of_scope_paths = _paths_outside_write_set(changed_paths, write_set)
    changed_paths_path = bundle_path / "changed-paths.json"
    _write_json(
        changed_paths_path,
        {
            "base_sha": base_sha,
            "changed_paths": changed_paths,
            "write_set": write_set,
            "out_of_scope_paths": out_of_scope_paths,
        },
    )
    return DiffEvidence(
        changed_paths=changed_paths,
        out_of_scope_paths=out_of_scope_paths,
        diff_patch_path=diff_patch_path,
        changed_paths_path=changed_paths_path,
    )


def derive_reviewer_scan(
    *, repo_root: Path, baseline_dirty: list[str], bundle_path: Path
) -> ReviewerScan:
    """Prove a reviewer run did not mutate the live tree, snapshot-relative (R2).

    New dirt is computed as the set difference of post-run dirty paths against the pre-run
    baseline. A pre-dirty operator tree cannot false-positive: every path dirty before launch is
    in the baseline and therefore excluded from ``new_paths`` regardless of its post-run status.

    Reversions are surfaced separately: a baseline path that is CLEAN after the run
    (``reverted_paths``) means the run may have discarded uncommitted operator work — recorded
    as an audit signal in ``diff-scan.json``, not folded into ``mutation_detected`` (an operator
    cleaning their own tree mid-run must not hard-fail a legitimate review).
    """
    post_dirty = _porcelain_paths(repo_root)
    baseline_set = set(baseline_dirty)
    post_set = set(post_dirty)
    new_paths = sorted(path for path in post_dirty if path not in baseline_set)
    reverted_paths = sorted(path for path in baseline_set if path not in post_set)

    mutation_patch_path: Path | None = None
    if new_paths:
        mutation_patch_path = bundle_path / "mutation.patch"
        diff_result = _run_git(["diff", "--", *new_paths], cwd=repo_root)
        mutation_patch_path.write_text(diff_result.stdout, encoding="utf-8")

    diff_scan_path = bundle_path / "diff-scan.json"
    _write_json(
        diff_scan_path,
        {
            "baseline_dirty": sorted(baseline_dirty),
            "post_dirty": post_dirty,
            "new_paths": new_paths,
            "reverted_paths": reverted_paths,
            "reversion_suspected": bool(reverted_paths),
            "mutation_detected": bool(new_paths),
            "mutation_patch": str(mutation_patch_path) if mutation_patch_path else None,
        },
    )
    return ReviewerScan(
        baseline_dirty=sorted(baseline_dirty),
        post_dirty=post_dirty,
        new_paths=new_paths,
        reverted_paths=reverted_paths,
        diff_scan_path=diff_scan_path,
        mutation_patch_path=mutation_patch_path,
    )


def _finalize_failed_bundle(bundle_path: Path, *, run_id: str, status: str, error: str) -> str:
    """Best-effort terminal record for a run that failed outside the happy path (R4).

    Every attempted run must end with an on-disk terminal status — a bundle whose
    ``result.json`` is missing is exactly the ambiguous zombie state this delegate exists to
    eliminate. If even this write fails, the projection still reports the failure loudly.
    """
    with contextlib.suppress(OSError):
        if bundle_path.exists() and not (bundle_path / "result.json").exists():
            _write_json(
                bundle_path / "result.json",
                {
                    "schema": "codex.result.v1",
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
    codex_bin: str | None = None,
    now: datetime | None = None,
) -> BundleResult:
    """Launch codex, supervise it, and write the full evidence bundle (U2/U3, R2/R4/R8).

    Mode surfaces (U3, R2, KTD5):

    * Reviewer (``read-only``) runs against the *live* repo. A pre-run ``git status --porcelain``
      snapshot is taken before launch; the post-run diff-scan flags any NEW dirt relative to that
      baseline as ``out_of_scope_mutation`` (a pre-dirty tree cannot false-positive).
    * Coder (``task``) runs inside a disposable, remotes-stripped clone via ``--cd`` /
      ``--skip-git-repo-check``. The resulting diff is preserved as a patch artifact and never
      applied to the live tree; out-of-write_set mutation is flagged. The clone is torn down on
      both success and failure. The live primary tree is never the working directory.
    """
    repo_root = repo_root.resolve()
    timestamp = now or datetime.now(UTC)
    resolved_run_id = run_id or _new_run_id(timestamp)
    _validate_run_id(resolved_run_id)
    bundle_path = repo_root / ".claude" / "codex" / "runs" / resolved_run_id

    # Bundle-span die-clean handlers (R4): a caller's SIGTERM can arrive during clone setup,
    # token parse, diff scan, or bundle writes — windows OUTSIDE run_codex_supervised (which
    # installs its own handler for the launch window and restores these afterward). At default
    # disposition the interpreter dies without unwinding: no terminal result.json, no clone
    # teardown. ValueError = non-main-thread caller; proceed uncovered rather than fail.
    prior_handlers: dict[int, Any] = {}
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            prior_handlers[signum] = signal.signal(signum, _bundle_die_clean_handler)
    except ValueError:
        prior_handlers = {}

    clone_dir: Path | None = None
    try:
        bundle_path.mkdir(parents=True, exist_ok=False)
        prompt = render_prompt(envelope, repo_root=repo_root)
        _write_json(bundle_path / "envelope.json", envelope.to_jsonable())
        (bundle_path / "prompt.txt").write_text(prompt, encoding="utf-8")

        transcript_path = bundle_path / "transcript.jsonl"
        last_message_path = bundle_path / "last-message.txt"
        stderr_path = bundle_path / "stderr.log"
        transcript_path.touch()
        last_message_path.touch()
        stderr_path.touch()

        sandbox = _sandbox_for_mode(envelope.mode)
        is_coder = envelope.role == "coder"

        clone_setup: CloneSetupResult | None = None
        clone_path: Path | None = None
        baseline_dirty: list[str] = []
        if is_coder:
            clone_dir = Path(tempfile.mkdtemp(prefix=f"codex-clone-{resolved_run_id}-"))
            clone_path = clone_dir / "worktree"
            clone_setup = setup_disposable_clone(repo_root=repo_root, clone_path=clone_path)
        else:
            # Reviewer runs against the live tree — snapshot its dirt BEFORE launch so the
            # post-run scan can distinguish operator-pre-existing dirt from codex mutations.
            baseline_dirty = _porcelain_paths(repo_root)

        if is_coder and clone_setup is not None and not clone_setup.success:
            # Clone could not be created — never touch the live tree; fail clean and terminal.
            run_result = SupervisedRunResult(
                status=parse_status("error"),
                codex_launched=False,
                resolved_codex=None,
                argv=[],
                process_id=None,
                return_code=None,
                started_at=timestamp,
                ended_at=datetime.now(UTC),
                stdout_bytes=0,
                stderr_bytes=0,
                error=clone_setup.error or "disposable clone setup failed",
            )
        else:
            run_result = run_codex_supervised(
                envelope,
                prompt=prompt,
                repo_root=repo_root,
                transcript_path=transcript_path,
                stderr_path=stderr_path,
                last_message_path=last_message_path,
                sandbox=sandbox,
                codex_bin=codex_bin,
                clone_path=clone_path,
            )

        token_usage = parse_token_usage(transcript_path)
        _write_json(bundle_path / "token-usage.json", token_usage)

        # --- Mode-surface post-run scan + status finalization (U3, R2, KTD5) ---
        mode_evidence: dict[str, Any] = {}
        final_status = run_result.status
        if is_coder:
            if clone_setup is not None and clone_setup.success and clone_path is not None:
                diff_evidence = derive_diff_evidence(
                    clone_path=clone_path,
                    base_sha=clone_setup.base_sha or "HEAD",
                    bundle_path=bundle_path,
                    write_set=envelope.write_set,
                )
                mode_evidence = {
                    "base_sha": clone_setup.base_sha,
                    "removed_remotes": clone_setup.removed_remotes,
                    "changed_paths": diff_evidence.changed_paths,
                    "out_of_scope_paths": diff_evidence.out_of_scope_paths,
                    "diff_patch": str(diff_evidence.diff_patch_path),
                }
                if run_result.status == "success":
                    if diff_evidence.out_of_scope_paths:
                        final_status = parse_status("out_of_scope_mutation")
                    elif diff_evidence.changed_paths:
                        final_status = parse_status("patch_ready")
        else:
            scan = derive_reviewer_scan(
                repo_root=repo_root,
                baseline_dirty=baseline_dirty,
                bundle_path=bundle_path,
            )
            mode_evidence = {
                "baseline_dirty": scan.baseline_dirty,
                "post_dirty": scan.post_dirty,
                "new_paths": scan.new_paths,
                "reverted_paths": scan.reverted_paths,
                "reversion_suspected": bool(scan.reverted_paths),
                "diff_scan": str(scan.diff_scan_path),
                "mutation_patch": (
                    str(scan.mutation_patch_path) if scan.mutation_patch_path else None
                ),
            }
            if run_result.status == "success" and scan.new_paths:
                final_status = parse_status("out_of_scope_mutation")

        if final_status != run_result.status:
            run_result = replace(run_result, status=final_status)

        command_payload = {
            "validation_only": False,
            "codex_launch_planned": True,
            "codex_launched": run_result.codex_launched,
            "resolved_codex": run_result.resolved_codex,
            "argv": _sanitize_argv(run_result.argv),
            "wrapper_argv": _sanitize_argv(
                wrapper_argv or [], prompt_replacement="<prompt:prompt.txt>"
            ),
            "source_envelope": str(source_envelope) if source_envelope else None,
            "repo_root": str(repo_root),
            "working_directory": str(clone_path) if clone_path is not None else str(repo_root),
            "sandbox": sandbox,
            "role": envelope.role,
            "mode": envelope.mode,
            "mode_surface": mode_evidence,
        }
        _write_json(bundle_path / "command.json", command_payload)

        receipt = _supervised_receipt(
            run_result,
            envelope=envelope,
            run_id=resolved_run_id,
            external_tokens=_codex_external_tokens(token_usage, run_result),
            output_attestation=_output_attestation.emit_attestation(
                artifact="last-message.txt",
                content=_read_attestation_artifact(last_message_path),
            ),
        )
        if receipt is not None:
            _write_json(bundle_path / "bridge-receipt.json", receipt)

        result_payload = _result_payload(
            envelope=envelope,
            run_id=resolved_run_id,
            bundle_path=bundle_path,
            run_result=run_result,
            token_usage=token_usage,
            last_message_path=last_message_path,
            receipt_emitted=receipt is not None,
        )
        _write_json(bundle_path / "result.json", result_payload)
        projection = render_projection(result_payload)
        (bundle_path / "projection.md").write_text(projection, encoding="utf-8")
    except DieCleanInterrupt as exc:
        # Signal arrived outside the supervised launch window: still end terminal (R4).
        projection = _finalize_failed_bundle(
            bundle_path,
            run_id=resolved_run_id,
            status=parse_status("error"),
            error=f"terminated by signal {exc.signum} outside the supervised window",
        )
        return BundleResult(
            status=parse_status("error"),
            run_id=resolved_run_id,
            bundle_path=bundle_path,
            projection=projection,
        )
    except OSError as exc:
        projection = _finalize_failed_bundle(
            bundle_path,
            run_id=resolved_run_id,
            status=parse_status("bundle_failed"),
            error=f"bundle write failed: {exc}",
        )
        return BundleResult(
            status=parse_status("bundle_failed"),
            run_id=resolved_run_id,
            bundle_path=bundle_path,
            projection=projection,
        )
    except Exception as exc:
        # Terminal-bundle guarantee over exception precision (R4): a post-launch failure
        # (receipt emission, JSON serialization) must not leave a launched run non-terminal.
        projection = _finalize_failed_bundle(
            bundle_path,
            run_id=resolved_run_id,
            status=parse_status("bundle_failed"),
            error=f"{type(exc).__name__}: {exc}",
        )
        return BundleResult(
            status=parse_status("bundle_failed"),
            run_id=resolved_run_id,
            bundle_path=bundle_path,
            projection=projection,
        )
    finally:
        # Restore the caller's signal disposition, then tear the disposable clone down on
        # BOTH the success and failure paths (R2, KTD5).
        for signum, handler in prior_handlers.items():
            with contextlib.suppress(ValueError):
                signal.signal(signum, handler)
        if clone_dir is not None:
            teardown_clone(clone_dir)

    return BundleResult(
        status=parse_status(run_result.status),
        run_id=resolved_run_id,
        bundle_path=bundle_path,
        projection=projection,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guarded codex delegation wrapper")
    parser.add_argument("--envelope", type=Path, default=None, help="Path to a JSON envelope")
    parser.add_argument("--role", choices=sorted(ROLES))
    parser.add_argument("--mode", choices=sorted(MODES), default=None)
    parser.add_argument("--task", default=None)
    parser.add_argument("--task-file", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--review-lens", dest="review_lens", choices=sorted(REVIEW_LENSES))
    parser.add_argument("--write-set", dest="write_set", action="append", default=[])
    parser.add_argument(
        "--apply-policy",
        dest="apply_policy",
        choices=sorted(APPLY_POLICIES),
        default="preserve-patch",
    )
    parser.add_argument("--evidence", choices=sorted(EVIDENCE_LEVELS), default="summary")
    parser.add_argument("--timeout-seconds", dest="timeout_seconds", type=int, default=900)
    parser.add_argument("--no-output-seconds", dest="no_output_seconds", type=int, default=180)
    parser.add_argument(
        "--no-provenance-required",
        dest="provenance_required",
        action="store_false",
        default=True,
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Alias for --validate-only")
    parser.add_argument("--repo-root", dest="repo_root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", dest="run_id", default=None)
    parser.add_argument(
        "--codex-bin",
        dest="codex_bin",
        default=None,
        help="Override the resolved codex binary (hermetic tests)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        if args.envelope is not None:
            envelope = load_envelope(args.envelope)
            source_envelope: Path | None = args.envelope
        else:
            if not args.role:
                raise EnvelopeError("--role is required when --envelope is not supplied")
            envelope = build_envelope_from_args(args)
            source_envelope = None
    except EnvelopeError as exc:
        print(f"codex-delegate: envelope error: {exc}", file=sys.stderr)
        return 2

    wrapper_argv = list(sys.argv[1:] if argv is None else argv)

    if args.validate_only or args.dry_run:
        print(json.dumps(envelope.to_jsonable(), indent=2))
        result = create_validation_bundle(
            envelope,
            repo_root=args.repo_root,
            run_id=args.run_id,
            source_envelope=source_envelope,
            argv=wrapper_argv,
        )
        return 0 if result.status == "success" else 1

    result = create_supervised_bundle(
        envelope,
        repo_root=args.repo_root,
        run_id=args.run_id,
        source_envelope=source_envelope,
        wrapper_argv=wrapper_argv,
        codex_bin=args.codex_bin,
    )
    print(result.projection, end="")
    return 0 if result.status in {"success", "patch_ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
