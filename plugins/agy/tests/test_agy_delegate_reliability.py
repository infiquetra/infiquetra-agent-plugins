"""Reliability-hardening parity tests for agy_delegate (#517).

Ports the four hardenings fixed in the codex delegate for #476 (commit ``437e73a``) into
``plugins/agy/scripts/agy_delegate.py`` and mirrors the codex tests in the agy idiom:

* Atomic ``_write_json`` — a tmp file plus ``os.replace`` never leaves torn JSON on disk.
* A non-``OSError`` failure after a launched run (e.g. receipt-emission ``ValueError``) still
  ends the bundle terminal via ``_finalize_failed_bundle``, instead of propagating uncaught.
* ``MAX_OUTPUT_BYTES`` caps cumulative stdout+stderr in the supervise loop — a runaway process
  is killed and the bundle ends terminal with a named error instead of growing unbounded.
* SIGTERM/SIGINT die-clean handling: a signal landing OUTSIDE the supervised launch window still
  ends the bundle terminal (bundle-span handler raising ``DieCleanInterrupt``); a kill that
  cannot reap the process still maps to the existing terminal ``shutdown_incomplete`` status.

Every red condition here is hermetic: fake ``agy`` python scripts, no network, no real
Antigravity dependency.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "skills" / "agy-delegate" / "scripts" / "agy_delegate.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agy_delegate_reliability_under_test", WRAPPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


agy_delegate = _load_module()


# --- fake agy binaries (hermetic, no network) -----------------------------------------------


def _write_fake_agy(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake-agy.py"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


_FAKE_AGY_OK = """#!/usr/bin/env python3
import sys
print("fake agy ok", flush=True)
print("fake agy stderr ok", file=sys.stderr, flush=True)
sys.exit(0)
"""

_FAKE_AGY_SLEEP = """#!/usr/bin/env python3
import sys, time
print("fake agy running", flush=True)
time.sleep(300)
"""

_FAKE_AGY_SPAM = """#!/usr/bin/env python3
import sys, time
filler = "y" * 1024
for _ in range(4096):
    print(filler, flush=True)
time.sleep(60)
"""

# Reproduces the #523/drill-468 S1 false-success path: Antigravity's executor construction fails
# ("failed to construct executor: neither PlanModel nor RequestedModel specified") and the
# process exits 0 having written nothing at all to stdout/stderr (the failure reason lands only
# in agy's own --log_path, which the supervise loop never inspects for status).
_FAKE_AGY_SILENT_SUCCESS = """#!/usr/bin/env python3
import sys
sys.exit(0)
"""

# Nearest-neighbor variant of the #523 incident (pre-merge review hardening, PR #575 F1): the
# process writes a single incidental line to stderr (a warning/log line unrelated to the
# deliverable) but still produces zero stdout bytes and exits 0. Before the F1 fix, gating on
# stdout_bytes + stderr_bytes == 0 let this land as "success" the moment any stderr byte was
# present, re-opening the false-success path for the observed incident's nearest neighbor.
_FAKE_AGY_STDERR_ONLY_SUCCESS = """#!/usr/bin/env python3
import sys
print("W0712 executor warning", file=sys.stderr, flush=True)
sys.exit(0)
"""


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True
    )


def _reviewer_envelope(**overrides: object):
    payload: dict[str, object] = {
        "schema": agy_delegate.SCHEMA,
        "role": "reviewer",
        "task": "Review the diff.",
    }
    payload.update(overrides)
    return agy_delegate.Envelope.from_mapping(payload)


def _quick_bundle(tmp_path: Path, *, run_id: str, body: str | None = None, **envelope_overrides):
    fake_agy = _write_fake_agy(tmp_path, body or _FAKE_AGY_OK)
    repo_root = tmp_path / "repo"
    repo_root.mkdir(exist_ok=True)
    _init_repo(repo_root)
    result = agy_delegate.create_supervised_bundle(
        _reviewer_envelope(**envelope_overrides),
        repo_root=repo_root,
        run_id=run_id,
        agy_bin=str(fake_agy),
    )
    return result, repo_root / ".claude" / "agy" / "runs" / run_id


# --- atomic writes ---------------------------------------------------------------------------


def test_write_json_is_atomic_and_leaves_no_tmp_sibling(tmp_path: Path) -> None:
    """``_write_json`` writes through a ``.tmp`` sibling and ``os.replace``s it into place."""
    target = tmp_path / "result.json"
    agy_delegate._write_json(target, {"status": "success", "run_id": "atomic-run"})

    assert target.exists()
    assert not target.with_name(target.name + ".tmp").exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "status": "success",
        "run_id": "atomic-run",
    }

    # A second write over an existing file replaces it wholesale — no partial/merged content.
    agy_delegate._write_json(target, {"status": "error"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "error"}
    assert not target.with_name(target.name + ".tmp").exists()


# --- receipt-emission failure still ends terminal (except Exception) -------------------------


def test_receipt_emission_failure_still_ends_terminal(tmp_path, monkeypatch) -> None:
    """A non-``OSError`` after a successful run must still produce a terminal bundle."""

    def _boom(**_kwargs):
        raise ValueError("receipt validation exploded")

    monkeypatch.setattr(agy_delegate._bridge_receipt, "emit_receipt", _boom)
    result, bundle = _quick_bundle(tmp_path, run_id="receipt-boom")

    assert result.status == "bundle_failed"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "bundle_failed"
    assert "ValueError" in payload["error"]
    assert payload["terminal"] is True


# --- MAX_OUTPUT_BYTES kills runaway spam -------------------------------------------------------


def test_output_byte_cap_kills_runaway_spam(tmp_path, monkeypatch) -> None:
    """Cumulative output beyond ``MAX_OUTPUT_BYTES`` must kill the process and end terminal."""
    monkeypatch.setattr(agy_delegate, "MAX_OUTPUT_BYTES", 64 * 1024)
    result, bundle = _quick_bundle(
        tmp_path,
        run_id="runaway-spam",
        body=_FAKE_AGY_SPAM,
        timeout_seconds=30,
        no_output_seconds=30,
    )

    assert result.status == "error"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "error"
    assert "MAX_OUTPUT_BYTES" in payload["error"]
    lease = json.loads((bundle / "run-lease.json").read_text())
    assert lease["timeout_class"] == "output_limit"


# --- unreapable process maps to terminal shutdown_incomplete ---------------------------------


def test_unreapable_process_surfaces_as_shutdown_incomplete(tmp_path, monkeypatch) -> None:
    """A kill that cannot reap the process must map to terminal ``shutdown_incomplete``.

    The real terminate still runs (so the fake dies), but its outcome is forced to the
    could-not-reap value — the run status must flag the leak, never read as a clean timeout.
    """
    real_terminate = agy_delegate._terminate_process

    def _terminate_but_report_incomplete(process):
        real_terminate(process)
        return "shutdown_incomplete"

    monkeypatch.setattr(agy_delegate, "_terminate_process", _terminate_but_report_incomplete)
    result, bundle = _quick_bundle(
        tmp_path,
        run_id="unreapable",
        body=_FAKE_AGY_SLEEP,
        timeout_seconds=1,
        no_output_seconds=1,
    )

    assert result.status == "shutdown_incomplete"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "shutdown_incomplete"
    assert "reaped" in payload["error"]


# --- a caller SIGTERM outside the supervised launch window still ends terminal ----------------


def test_signal_in_post_run_window_still_ends_terminal(tmp_path, monkeypatch) -> None:
    """A caller SIGTERM landing OUTSIDE the supervised launch window must die clean.

    Delivers a real signal from the post-run marker-scan seam: the bundle-span handler must
    convert it into an unwind that writes a terminal ``result.json`` and returns an ``error``
    status instead of the interpreter dying with the bundle non-terminal.
    """
    original_disposition = signal.getsignal(signal.SIGTERM)
    real_scan = agy_delegate._blocked_status_from_logs

    def _signal_then_scan(stdout_path, stderr_path):
        os.kill(os.getpid(), signal.SIGTERM)
        # Give the interpreter a bytecode boundary to deliver the signal on.
        time.sleep(0.2)
        return real_scan(stdout_path, stderr_path)

    monkeypatch.setattr(agy_delegate, "_blocked_status_from_logs", _signal_then_scan)
    result, bundle = _quick_bundle(tmp_path, run_id="post-run-signal")

    assert result.status == "error"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "error"
    assert "signal" in payload["error"]
    assert payload["terminal"] is True
    # The bundle-span handler was restored on exit.
    assert signal.getsignal(signal.SIGTERM) is original_disposition


# --- a caller SIGTERM mid-launch still ends terminal, nonzero exit ----------------------------


def test_delegate_killed_mid_run_leaves_terminal_bundle(tmp_path) -> None:
    """SIGTERM to the delegate mid-run (a caller's Bash-tool timeout) is die-clean.

    Exercises the CLI subprocess end-to-end (not the in-process monkeypatch path above): the
    delegate must exit nonzero and leave a terminal, diagnosable bundle — never ``running``.
    """
    fake_agy = _write_fake_agy(tmp_path, _FAKE_AGY_SLEEP)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)

    delegate = subprocess.Popen(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(repo_root),
            "--run-id",
            "killed-run",
            "--role",
            "reviewer",
            "--task",
            "Reliability probe task.",
            "--timeout-seconds",
            "300",
            "--no-output-seconds",
            "300",
            "--launch-agy",
            "--agy-bin",
            str(fake_agy),
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        # Give the fake agy a moment to actually start running before we interrupt it.
        deadline = time.monotonic() + 15.0
        stdout_log = repo_root / ".claude" / "agy" / "runs" / "killed-run" / "stdout.log"
        while time.monotonic() < deadline:
            if stdout_log.exists() and "fake agy running" in stdout_log.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("fake agy never started running")

        delegate.send_signal(signal.SIGTERM)
        exit_code = delegate.wait(timeout=30)
    finally:
        if delegate.poll() is None:  # pragma: no cover - only on assertion failure above
            delegate.kill()
            delegate.wait(timeout=10)

    assert exit_code != 0, "die-clean must exit nonzero"

    bundle = repo_root / ".claude" / "agy" / "runs" / "killed-run"
    payload = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] in agy_delegate.STATUSES  # terminal vocabulary only
    assert payload["status"] != "running"


# --- #523: executor-construction failure must not be corroborated as success ------------------


def test_zero_output_exit_zero_is_not_success(tmp_path) -> None:
    """Reproduces the drill-468 S1 false-success path and proves it now lands terminal-failed.

    Before the #523 fix, ``run_agy_supervised`` mapped any ``return_code == 0`` straight to
    ``status="success"`` regardless of output produced. An Antigravity executor-construction
    failure exits 0 with zero stdout/stderr bytes (the failure reason lands only in agy's own
    log, never in the supervised stdout/stderr streams) — that used to emit a schema-valid
    success receipt with ``bytes_produced=0``, which engine_dispatch's two-signal observer would
    then corroborate as a real, proceeded-as-requested run. This must now be a terminal
    ``no_output`` failure, never ``success``.
    """
    result, bundle = _quick_bundle(
        tmp_path, run_id="silent-exit-zero", body=_FAKE_AGY_SILENT_SUCCESS
    )

    assert result.status == "no_output"
    assert result.status != "success"

    payload = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "no_output"
    assert payload["status"] not in agy_delegate._PASSING_STATUSES
    assert "no-output failure" in payload["error"]

    # The receipt (if emitted) must never be read as a corroborating success signal: either no
    # receipt is attached, or its bytes_produced=0 is paired with a non-passing terminal status
    # rather than "success" — closing the exact gap #384's two-signal observer was fooled by.
    receipt = payload.get("receipt")
    if receipt is not None:
        assert receipt["bytes_produced"] == 0
    assert payload["status"] != "success"

    lease = json.loads((bundle / "run-lease.json").read_text(encoding="utf-8"))
    assert lease["status"] == "no_output"
    assert lease["timeout_class"] is None  # not the watchdog path — the process exited on its own
    assert lease["shutdown"] == "exited"

    # The wrapper's exit code must be nonzero too — a caller (or CI) checking the process exit
    # code alone must also see failure, not just the receipt payload.
    assert agy_delegate._exit_code_for_status(result.status) != 0


def test_stderr_only_exit_zero_is_not_success(tmp_path) -> None:
    """Stderr-only chatter with zero stdout on an exit-0 run must still be ``no_output``.

    Pre-merge review hardening on PR #575 (finding F1): the original #523 fix gated on
    ``stdout_bytes + stderr_bytes == 0``, which is narrower than the issue's own fix direction
    ("empty stdout on an exit-0 run"). A run that emits any stderr byte (a warning or log line)
    while still writing zero stdout and exiting 0 is the nearest-neighbor variant of the
    drill-468 incident — the deliverable stream (stdout) is empty, so it must not be corroborated
    as success just because stderr happened to carry incidental chatter.
    """
    result, bundle = _quick_bundle(
        tmp_path, run_id="stderr-only-exit-zero", body=_FAKE_AGY_STDERR_ONLY_SUCCESS
    )

    assert result.status == "no_output"
    assert result.status != "success"

    stdout_bytes = (bundle / "stdout.log").stat().st_size
    stderr_bytes = (bundle / "stderr.log").stat().st_size
    assert stdout_bytes == 0
    assert stderr_bytes > 0

    payload = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "no_output"
    assert payload["status"] not in agy_delegate._PASSING_STATUSES
    assert "no-output failure" in payload["error"]

    # The receipt (if emitted) carries a nonzero bytes_produced here (the incidental stderr
    # bytes) — the fix does not depend on bytes_produced being zero, only on the terminal status
    # never reading as "success" so a two-signal observer cannot corroborate it as a real run.
    receipt = payload.get("receipt")
    if receipt is not None:
        assert receipt["bytes_produced"] == stderr_bytes
    assert payload["status"] != "success"

    assert agy_delegate._exit_code_for_status(result.status) != 0
