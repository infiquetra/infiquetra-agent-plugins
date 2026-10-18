"""Real processes prove owned-group cleanup precedes temporary-resource removal."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("lifetime_review_tools", SCRIPTS / "review_tools.py")
assert _SPEC is not None and _SPEC.loader is not None
T = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = T
_SPEC.loader.exec_module(T)
FIXTURE = Path(__file__).parent / "fixtures" / "review_tools" / "process_lifetime.py"
pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        assert time.monotonic() < deadline, f"fixture did not create {path.name}"
        time.sleep(0.01)


def _run(root: Path, mode: str, child: str = "cooperative", timeout: int = 5) -> Any:
    return T.subprocess_runner(
        [sys.executable, str(FIXTURE), mode, str(root), child],
        cwd=root, env=dict(os.environ), timeout=timeout, shell=False,
    )


def _assert_no_late_write(root: Path) -> None:
    (root / "release-child").touch()
    time.sleep(0.1)
    assert not (root / "post-return-write").exists()
    parent_pid = int((root / "parent-ready").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(parent_pid, 0)


def test_normal_output_and_exit_status(tmp_path: Path) -> None:
    result = T.subprocess_runner(
        [sys.executable, "-c", "import sys; print('hello \\u03bb'); print('error', file=sys.stderr); sys.exit(7)"],
        cwd=tmp_path, env=dict(os.environ), timeout=5, shell=False,
    )
    assert (result.code, result.stdout, result.stderr) == (7, "hello λ\n", "error\n")


def test_timeout_escalates_and_preserves_partial_output(tmp_path: Path) -> None:
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        _run(tmp_path, "parent", "stubborn", timeout=1)
    assert caught.value.timeout == 1
    assert caught.value.cmd[0] == sys.executable
    assert caught.value.output == b"partial stdout\n"
    assert caught.value.stderr == b"partial stderr\n"
    _assert_no_late_write(tmp_path)


@pytest.mark.parametrize("child", ["verbose", "invalid"])
def test_timeout_drains_cleanup_output_without_replacing_timeout_bytes(tmp_path: Path, child: str) -> None:
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        _run(tmp_path, "parent", child, timeout=1)
    assert caught.value.output == b"partial stdout\n"
    assert caught.value.stderr == b"partial stderr\n"
    assert (tmp_path / "terminated.json").exists()
    _assert_no_late_write(tmp_path)


@pytest.mark.parametrize("mode", ["parent", "background"])
def test_cargo_home_exists_until_descendant_termination(tmp_path: Path, mode: str) -> None:
    adapter = SimpleNamespace(id="fixture", local_bins=(), narrow_env=False,
                              ambient_env=False, tool="fixture")
    homes: list[Path] = []

    def fake_cargo(_argv: list[str], **kwargs: Any) -> Any:
        homes.append(Path(kwargs["env"]["CARGO_HOME"]))
        return T.subprocess_runner(
            [sys.executable, str(FIXTURE), mode, str(tmp_path), "cooperative"], **kwargs,
        )

    result, problem = T._execute(
        adapter, ["cargo-fixture"], tmp_path, fake_cargo, dict(os.environ), 1,
    )
    assert problem == ("timeout" if mode == "parent" else None)
    assert (result is None) == (mode == "parent")
    assert json.loads((tmp_path / "terminated.json").read_text()) == {"home_exists": True}
    assert len(homes) == 1 and not homes[0].exists()
    _assert_no_late_write(tmp_path)


def test_cancellation_cleans_real_descendant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    communicate = T.subprocess.Popen.communicate

    first = True

    def interrupted(proc: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal first
        if first:
            first = False
            _wait_for(tmp_path / "parent-ready")
            raise KeyboardInterrupt
        return communicate(proc, *args, **kwargs)

    monkeypatch.setattr(T.subprocess.Popen, "communicate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, "parent")
    monkeypatch.setattr(T.subprocess.Popen, "communicate", communicate)
    assert (tmp_path / "terminated.json").exists()
    _assert_no_late_write(tmp_path)


def test_timeout_does_not_stop_another_invocation(tmp_path: Path) -> None:
    independent = tmp_path / "independent"
    independent.mkdir()
    timed_out = tmp_path / "timed-out"
    timed_out.mkdir()
    with ThreadPoolExecutor(max_workers=2) as pool:
        other = pool.submit(_run, independent, "independent")
        try:
            _wait_for(independent / "independent-ready")
            with pytest.raises(subprocess.TimeoutExpired):
                _run(timed_out, "parent", timeout=1)
            assert not other.done()
        finally:
            (independent / "release-independent").touch()
        result = other.result(timeout=5)
    assert result.code == 0 and result.stdout == "independent completed\n"
    _assert_no_late_write(timed_out)


def test_prepare_cli_term_unwinds_nested_tool_before_resource_cleanup(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, str(FIXTURE), "prepare", str(tmp_path), str(SCRIPTS)],
        cwd=tmp_path, env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        _wait_for(tmp_path / "parent-ready")
        os.killpg(proc.pid, signal.SIGTERM)
        time.sleep(0.1)
        os.killpg(proc.pid, signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=5)
        assert proc.returncode == 143, (stdout, stderr)
        assert (tmp_path / "prepare-cleaned").exists()
        assert not (tmp_path / "prepare-home").exists()
        cargo_home = Path((tmp_path / "cargo-home-path").read_text())
        assert not cargo_home.exists()
        _assert_no_late_write(tmp_path)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def test_prepare_cli_restores_prior_term_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    import review_command as command

    previous = signal.getsignal(signal.SIGTERM)

    def interrupted(_argv: Any) -> int:
        os.kill(os.getpid(), signal.SIGTERM)
        return 0

    monkeypatch.setattr(command, "main", interrupted)
    with pytest.raises(SystemExit) as caught:
        command._cli(["prepare"])
    assert caught.value.code == 143
    assert signal.getsignal(signal.SIGTERM) is previous
