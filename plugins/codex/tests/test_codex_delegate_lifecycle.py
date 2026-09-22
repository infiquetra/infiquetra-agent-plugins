"""Lifecycle tests for the codex delegate (R7): terminal bundles, whole-tree kill, live smoke.

Proves the R7 lifecycle guarantee of ``plugins/codex/scripts/codex_delegate.py``:

* A completed run's bundle is terminal and self-contained — a launcher process that exits
  immediately after the delegate returns leaves no live children and no non-terminal state.
* A fake codex that sleeps past ``--timeout-seconds`` gets its WHOLE process tree killed within
  the grace window (the fake bin's own child pid is polled directly), with a terminal timeout
  status and no ``running`` string anywhere in the bundle's state files.
* A delegate killed mid-run (SIGTERM, mirroring a caller's Bash-tool timeout) leaves a dead
  process tree and a diagnosable terminal bundle — never a ``running`` record.

Every red condition is hermetic: fake codex binaries, no network. The one live conformance
smoke runs only when ``CODEX_DELEGATE_LIVE_SMOKE=1`` and ``codex login status`` exits 0.
Otherwise it skips and never fails.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codex_delegate.py"

# Grace window (seconds) within which the whole codex process tree must be dead after the
# delegate reports a terminal status. _kill_process_tree escalates SIGTERM→SIGKILL with 2s
# waits, so 5s is generous without masking a leak.
GRACE_WINDOW_SECONDS = 5.0


def _load_module():
    # The wrapper inserts scripts/_bundled on import. Do not also insert
    # scripts/: that insert existed so fleet_commons_shim could be imported,
    # and this package does not carry the shim.
    spec = importlib.util.spec_from_file_location(
        "codex_delegate_lifecycle_under_test", MODULE_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


codex_delegate = _load_module()


# --- process-tree helpers ------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """True while ``pid`` exists (zombies count as gone once reaped by their parent)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - pid reused by another uid; treat as alive
        return True
    # The pid exists — but a zombie child of a *dead* parent gets reaped by init/launchd, and a
    # zombie whose parent is us shows up in wait(); either way, `ps` distinguishes it.
    try:
        out = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - ps unavailable
        return True
    if not out:
        return False
    return not out.startswith("Z")


def _wait_dead(pid: int, *, window: float = GRACE_WINDOW_SECONDS) -> bool:
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    return not _pid_alive(pid)


def _read_pidfile(pidfile: Path, *, timeout: float = 15.0) -> tuple[int, int]:
    """Wait for the fake bin's pidfile and return (child_pid, fake_bin_pid)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pidfile.exists():
            lines = pidfile.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2:
                return int(lines[0]), int(lines[1])
        time.sleep(0.05)
    raise AssertionError(f"fake codex never wrote its pidfile at {pidfile}")


def _assert_no_running_in_state_files(bundle: Path) -> None:
    """No state file in the bundle may carry the string ``running`` (R4/R7)."""
    state_files = sorted(bundle.glob("*.json")) + [bundle / "projection.md"]
    for state_file in state_files:
        if not state_file.exists():
            continue
        content = state_file.read_text(encoding="utf-8")
        assert "running" not in content, f"non-terminal 'running' found in {state_file.name}"


# --- fake codex binaries (hermetic, no network) ---------------------------------------------------


def _write_shim(tmp_path: Path, body: str) -> Path:
    """Write an executable python fake codex plus a /bin/sh shim usable as --codex-bin."""
    bin_path = tmp_path / "fake-codex.py"
    bin_path.write_text(body, encoding="utf-8")
    bin_path.chmod(0o755)
    shim = tmp_path / "codex-shim"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bin_path}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return shim


def _tree_sleep_body(pidfile: Path, sleep_seconds: int = 300) -> str:
    """A fake codex that spawns its OWN child, records both pids, then sleeps far past timeout.

    The child inherits the fake bin's process group (the delegate started the fake in a new
    session), so a correct whole-tree kill takes it down; a broken direct-child-only kill
    leaves it alive — that asymmetry is what the timeout test polls for.
    """
    return f"""#!/usr/bin/env python3
import os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({sleep_seconds})"])
tmp = {str(pidfile)!r} + ".tmp"
with open(tmp, "w") as fh:
    fh.write(str(child.pid) + "\\n" + str(os.getpid()) + "\\n")
os.rename(tmp, {str(pidfile)!r})
sys.stdin.read()
print('{{"type": "session_start"}}', flush=True)
time.sleep({sleep_seconds})
print('{{"type": "done"}}', flush=True)
"""


def _well_behaved_body(pidfile: Path) -> str:
    """A fake codex whose child completes before it exits — a clean, terminal run."""
    return f"""#!/usr/bin/env python3
import json, os, subprocess, sys
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
child = subprocess.Popen([sys.executable, "-c", "pass"])
tmp = {str(pidfile)!r} + ".tmp"
with open(tmp, "w") as fh:
    fh.write(str(child.pid) + "\\n" + str(os.getpid()) + "\\n")
os.rename(tmp, {str(pidfile)!r})
child.wait()
piped = sys.stdin.read()
print(json.dumps({{"type": "session_start"}}))
print(json.dumps({{"type": "stdin_echo", "bytes": len(piped)}}))
sys.stdout.flush()
if out_path:
    with open(out_path, "w") as fh:
        fh.write("lifecycle final message")
sys.exit(0)
"""


def _delegate_argv(*, repo_root: Path, run_id: str, shim: Path, timeout_seconds: int) -> list[str]:
    return [
        sys.executable,
        str(MODULE_PATH),
        "--role",
        "reviewer",
        "--task",
        "Lifecycle probe task.",
        "--timeout-seconds",
        str(timeout_seconds),
        "--no-output-seconds",
        str(timeout_seconds),
        "--repo-root",
        str(repo_root),
        "--run-id",
        run_id,
        "--codex-bin",
        str(shim),
    ]


# --- (a) completed run: terminal, self-contained, launcher exit leaves nothing alive -------------


def test_completed_run_bundle_is_terminal_and_launcher_exit_leaves_no_children(tmp_path) -> None:
    """A launcher that exits immediately after the delegate returns leaves no live children.

    The delegate is synchronous: when its process exits, the whole delegation is over. The fake
    codex records its own pid and its child's pid; both must be dead the moment the delegate
    process has exited, and the bundle on disk must be terminal and self-contained.
    """
    pidfile = tmp_path / "pids.txt"
    shim = _write_shim(tmp_path, _well_behaved_body(pidfile))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # The "launcher" is this Popen: it waits for the delegate and then does nothing else.
    launcher = subprocess.Popen(
        _delegate_argv(repo_root=repo_root, run_id="completed-run", shim=shim, timeout_seconds=60),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = launcher.communicate(timeout=60)
    assert launcher.returncode == 0, stderr.decode()

    child_pid, fake_pid = _read_pidfile(pidfile, timeout=1)
    # Delegate already returned — the tree must ALREADY be gone, no grace needed.
    assert not _pid_alive(fake_pid), "fake codex outlived the delegate"
    assert _wait_dead(child_pid, window=1.0), "fake codex's child outlived the delegate"

    bundle = repo_root / ".claude" / "codex" / "runs" / "completed-run"
    payload = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["codex_launched"] is True
    assert payload["return_code"] == 0
    assert payload["receipt_emitted"] is True
    # Self-contained: every evidence surface present without any live process behind it.
    for name in (
        "envelope.json",
        "prompt.txt",
        "command.json",
        "transcript.jsonl",
        "last-message.txt",
        "result.json",
        "projection.md",
        "bridge-receipt.json",
    ):
        assert (bundle / name).exists(), name
    assert (bundle / "last-message.txt").read_text(encoding="utf-8") == "lifecycle final message"
    _assert_no_running_in_state_files(bundle)
    assert "Status: success" in stdout.decode()


# --- (b) timeout: WHOLE tree killed within the grace window --------------------------------------


def test_timeout_kills_whole_process_tree_within_grace_window(tmp_path) -> None:
    """A fake codex sleeping past --timeout-seconds loses its ENTIRE tree, child included.

    This is the anti-zombie proof: the fake bin spawns its own child and the test polls that
    child's pid directly. A kill that only reaches the direct child (the fake bin) but not the
    grandchild fails this test — verified red against exactly that broken variant.
    """
    pidfile = tmp_path / "pids.txt"
    shim = _write_shim(tmp_path, _tree_sleep_body(pidfile))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    envelope = codex_delegate.Envelope.from_mapping(
        {
            "schema": codex_delegate.SCHEMA,
            "role": "reviewer",
            "task": "Lifecycle probe task.",
            "timeout_seconds": 1,
            "no_output_seconds": 1,
        }
    )
    result = codex_delegate.create_supervised_bundle(
        envelope,
        repo_root=repo_root,
        run_id="timeout-run",
        codex_bin=str(shim),
    )

    child_pid, fake_pid = _read_pidfile(pidfile, timeout=1)
    assert _wait_dead(fake_pid), "fake codex still alive past the grace window"
    assert _wait_dead(child_pid), (
        "fake codex's CHILD survived the timeout kill — the delegate killed only the direct "
        "child, not the whole process tree"
    )

    assert result.status in {"timeout", "no_output"}
    bundle = repo_root / ".claude" / "codex" / "runs" / "timeout-run"
    payload = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] in {"timeout", "no_output"}
    assert payload["codex_launched"] is True
    _assert_no_running_in_state_files(bundle)
    # The sleeper's completion sentinel must never appear — it died mid-sleep.
    assert '"type": "done"' not in (bundle / "transcript.jsonl").read_text(encoding="utf-8")


# --- (c) delegate killed mid-run: dead tree + diagnosable terminal bundle ------------------------


def test_delegate_killed_mid_run_leaves_dead_tree_and_diagnosable_bundle(tmp_path) -> None:
    """SIGTERM to the delegate mid-run (a caller's Bash-tool timeout) is die-clean (R4/R7).

    The whole codex tree — fake bin AND its child — must be dead within the grace window, and
    the bundle must be a diagnosable terminal record: result.json present, terminal status,
    never ``running``.
    """
    pidfile = tmp_path / "pids.txt"
    shim = _write_shim(tmp_path, _tree_sleep_body(pidfile))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    delegate = subprocess.Popen(
        _delegate_argv(repo_root=repo_root, run_id="killed-run", shim=shim, timeout_seconds=300),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        # Wait until codex is demonstrably mid-run (its tree exists), then kill the delegate.
        child_pid, fake_pid = _read_pidfile(pidfile)
        assert _pid_alive(fake_pid)
        assert _pid_alive(child_pid)
        delegate.send_signal(signal.SIGTERM)
        exit_code = delegate.wait(timeout=30)
    finally:
        if delegate.poll() is None:  # pragma: no cover - only on assertion failure above
            delegate.kill()
            delegate.wait(timeout=10)

    assert exit_code != 0, "die-clean must exit nonzero"
    assert _wait_dead(fake_pid), "fake codex survived the delegate's death"
    assert _wait_dead(child_pid), "fake codex's child survived the delegate's death"

    bundle = repo_root / ".claude" / "codex" / "runs" / "killed-run"
    payload = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] in codex_delegate.STATUSES  # terminal vocabulary only
    assert payload["status"] != "running"
    assert payload["codex_launched"] is True
    assert payload["error"], "a killed run must carry a diagnosable error message"
    _assert_no_running_in_state_files(bundle)
    assert '"type": "done"' not in (bundle / "transcript.jsonl").read_text(encoding="utf-8")


# --- availability-gated live smoke (skip, never fail, without an authenticated codex) ------------


def _codex_authenticated() -> bool:
    # A logged-in codex on the machine running the suite is not consent to spend
    # a live exec. The variable is the opt-in. Unset, this skips before it looks
    # for the binary.
    if os.environ.get("CODEX_DELEGATE_LIVE_SMOKE") != "1":
        return False
    codex = shutil.which("codex")
    if not codex:
        return False
    try:
        return (
            subprocess.run(
                [codex, "login", "status"], capture_output=True, timeout=30, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(
    not _codex_authenticated(),
    reason="availability-gated smoke: set CODEX_DELEGATE_LIVE_SMOKE=1 and have `codex login status` exit 0; otherwise skip, never fail",
)
def test_codex_live_smoke_round_trip() -> None:  # pragma: no cover - live codex
    """One real ``codex exec`` round-trip through the delegate: receipt + transcript + last message.

    Gated on ``CODEX_DELEGATE_LIVE_SMOKE=1`` and ``codex login status`` exiting 0.
    Unset, the test skips before it looks for the binary.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="codex-live-smoke-") as tmp:
        repo_root = Path(tmp) / "repo"
        repo_root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True, timeout=30)
        (repo_root / "README.md").write_text("live smoke fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True, timeout=30)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=smoke@test",
                "-c",
                "user.name=smoke",
                "commit",
                "-qm",
                "init",
            ],
            cwd=repo_root,
            check=True,
            timeout=30,
        )

        envelope = codex_delegate.Envelope.from_mapping(
            {
                "schema": codex_delegate.SCHEMA,
                "role": "reviewer",
                "task": "Reply with the single word: ok",
                "timeout_seconds": 300,
                "no_output_seconds": 300,
            }
        )
        result = codex_delegate.create_supervised_bundle(
            envelope,
            repo_root=repo_root,
            run_id="live-smoke",
        )
        bundle = repo_root / ".claude" / "codex" / "runs" / "live-smoke"
        payload = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
        assert payload["codex_launched"] is True
        # A completed round-trip: codex exited 0. Locally-configured codex tooling (e.g. an MCP
        # server dropping `.serena/`) can dirty a fresh repo and flip the reviewer scan to
        # out_of_scope_mutation — that is the diff-scan doing its job, not a smoke failure, so
        # both terminal statuses prove the round-trip.
        assert payload["return_code"] == 0, payload
        assert result.status in {"success", "out_of_scope_mutation"}, payload
        # Receipt: emitted iff launched, and it validates against bridge_receipt.v1.
        receipt = json.loads((bundle / "bridge-receipt.json").read_text(encoding="utf-8"))
        assert receipt["engine_id"] == "codex"
        assert receipt["transport"] == "cli"
        assert codex_delegate._bridge_receipt.validate_receipt(receipt) == []
        # Transcript: real JSONL flowed.
        assert (bundle / "transcript.jsonl").read_text(encoding="utf-8").strip()
        # Last message: codex wrote its final agent message via -o.
        assert (bundle / "last-message.txt").read_text(encoding="utf-8").strip()
        _assert_no_running_in_state_files(bundle)


# --- Code-review fixes (#476 findings 2, 5, 7, 9) ------------------------------------------------


_QUICK_OK_BODY = """#!/usr/bin/env python3
import json, sys
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
sys.stdin.read()
print(json.dumps({"type": "session_start"}), flush=True)
if out_path:
    open(out_path, "w").write("ok")
sys.exit(0)
"""


def _reviewer_envelope(**overrides):
    payload = {
        "schema": codex_delegate.SCHEMA,
        "role": "reviewer",
        "task": "Review the diff.",
    }
    payload.update(overrides)
    return codex_delegate.Envelope.from_mapping(payload)


def _quick_bundle(tmp_path: Path, *, run_id: str, body: str | None = None, **envelope_overrides):
    shim = _write_shim(tmp_path, body or _QUICK_OK_BODY)
    repo_root = tmp_path / "repo"
    repo_root.mkdir(exist_ok=True)
    result = codex_delegate.create_supervised_bundle(
        _reviewer_envelope(**envelope_overrides),
        repo_root=repo_root,
        run_id=run_id,
        codex_bin=str(shim),
    )
    return result, repo_root / ".claude" / "codex" / "runs" / run_id


def test_unreapable_tree_surfaces_as_shutdown_incomplete(tmp_path, monkeypatch) -> None:
    """A kill that cannot reap the tree must map to terminal ``shutdown_incomplete`` (F2).

    The real kill still runs (so the fake dies), but its outcome is forced to the
    could-not-reap value — the run status must flag the leak, never read as a clean timeout.
    """
    real_kill = codex_delegate._kill_process_tree

    def _kill_but_report_incomplete(process):
        real_kill(process)
        return "shutdown_incomplete"

    monkeypatch.setattr(codex_delegate, "_kill_process_tree", _kill_but_report_incomplete)
    pidfile = tmp_path / "tree.pid"
    result, bundle = _quick_bundle(
        tmp_path,
        run_id="unreapable",
        body=_tree_sleep_body(pidfile),
        timeout_seconds=1,
        no_output_seconds=1,
    )
    assert result.status == "shutdown_incomplete"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "shutdown_incomplete"
    assert "reaped" in payload["error"]
    _assert_no_running_in_state_files(bundle)


def test_signal_in_post_run_window_still_ends_terminal(tmp_path, monkeypatch) -> None:
    """A caller SIGTERM landing OUTSIDE the supervised launch window must die clean (F5).

    Delivers a real signal from the post-run token-parse seam: the bundle-span handler must
    convert it into an unwind that writes a terminal ``result.json`` and returns nonzero-class
    status instead of the interpreter dying with the bundle non-terminal.
    """
    original_disposition = signal.getsignal(signal.SIGTERM)
    real_parse = codex_delegate.parse_token_usage

    def _signal_then_parse(transcript_path):
        os.kill(os.getpid(), signal.SIGTERM)
        # Give the interpreter a bytecode boundary to deliver the signal on.
        time.sleep(0.2)
        return real_parse(transcript_path)

    monkeypatch.setattr(codex_delegate, "parse_token_usage", _signal_then_parse)
    result, bundle = _quick_bundle(tmp_path, run_id="post-run-signal")
    assert result.status == "error"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "error"
    assert "signal" in payload["error"]
    assert payload["terminal"] is True
    # The bundle-span handler was restored on exit.
    assert signal.getsignal(signal.SIGTERM) is original_disposition


def test_output_byte_cap_kills_runaway_spam(tmp_path, monkeypatch) -> None:
    """Cumulative output beyond MAX_OUTPUT_BYTES must kill the tree and end terminal (F7)."""
    monkeypatch.setattr(codex_delegate, "MAX_OUTPUT_BYTES", 64 * 1024)
    spam_body = """#!/usr/bin/env python3
import json, sys, time
sys.stdin.read()
filler = "y" * 1024
for _ in range(1024):
    print(json.dumps({"type": "spam", "data": filler}), flush=True)
time.sleep(60)
sys.exit(0)
"""
    result, bundle = _quick_bundle(
        tmp_path,
        run_id="runaway-spam",
        body=spam_body,
        timeout_seconds=30,
        no_output_seconds=30,
    )
    assert result.status == "error"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "error"
    assert "MAX_OUTPUT_BYTES" in payload["error"]
    _assert_no_running_in_state_files(bundle)


def test_receipt_emission_failure_still_ends_terminal(tmp_path, monkeypatch) -> None:
    """A non-OSError after a successful run must still produce a terminal bundle (F9)."""

    def _boom(**_kwargs):
        raise ValueError("receipt validation exploded")

    monkeypatch.setattr(codex_delegate._bridge_receipt, "emit_receipt", _boom)
    result, bundle = _quick_bundle(tmp_path, run_id="receipt-boom")
    assert result.status == "bundle_failed"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "bundle_failed"
    assert "ValueError" in payload["error"]
    assert payload["terminal"] is True
