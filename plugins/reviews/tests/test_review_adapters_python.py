"""pytest-randomly and pytest-socket load under the resolved interpreter (issues 227 and 246)."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "reviews" / "scripts"


def _load(name: str) -> ModuleType:
    key = f"infiquetra_reviews.{name}"
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


T = _load("review_tools")
P = _load("review_adapters_python")


def _adapter(tool_id: str):
    found = [item for item in P.ADAPTERS if item.id == tool_id]
    assert len(found) == 1
    return found[0]


def _context(tmp_path: Path, command: str) -> T.ScanContext:
    root = tmp_path / "repo"
    root.mkdir()
    return T.ScanContext(
        root,
        root,
        tmp_path / "home",
        scratch=tmp_path / "scratch",
        test_command=command,
        base="base-sha",
        head="head-sha",
    )


def _run(argv: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=root, capture_output=True, text=True, check=False,
    )


def test_227_bare_python_keeps_the_resolved_interpreter(tmp_path: Path) -> None:
    """Issue 227: a bare python3 stays this interpreter, the one that has pytest."""
    context = _context(tmp_path, "python3 -m pytest -q")
    argv = _adapter("pytest-randomly").invoke(context)
    assert argv[argv.index("-m") - 1] == sys.executable
    assert "python3" not in argv
    assert "python" not in argv
    probe = _run([sys.executable, "-c", "import pytest"], context.root)
    assert probe.returncode == 0, probe.stderr


def test_pytest_randomly_loads_with_python3_test_command(tmp_path: Path) -> None:
    context = _context(tmp_path, "python3 -m pytest -q")
    (context.root / "test_order.py").write_text(
        "def test_plugin_loaded(pytestconfig):\n"
        "    assert pytestconfig.pluginmanager.has_plugin('randomly')\n",
        encoding="utf-8",
    )
    argv = _adapter("pytest-randomly").invoke(context)
    assert argv[argv.index("-m") - 1] == sys.executable
    assert any(item.startswith("--randomly-seed=") for item in argv)
    completed = _run(argv, context.root)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "No module named" not in completed.stderr


def test_pytest_socket_blocks_socket_with_python3_test_command(tmp_path: Path) -> None:
    context = _context(tmp_path, "python3 -m pytest -q")
    (context.root / "test_net.py").write_text(
        "def test_net():\n"
        "    import socket\n"
        "    socket.create_connection(('example.invalid', 9))\n",
        encoding="utf-8",
    )
    argv = _adapter("pytest-socket").invoke(context)
    assert argv[argv.index("-m") - 1] == sys.executable
    assert "--disable-socket" in argv
    completed = _run(argv, context.root)
    combined = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "SocketBlockedError" in combined
    assert "No module named" not in combined


def test_bare_pytest_keeps_the_uv_runtime(tmp_path: Path) -> None:
    """A bare pytest has no interpreter. uv run still supplies pytest and the plugin."""
    context = _context(tmp_path, "pytest -q")
    (context.root / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    argv = _adapter("pytest-randomly").invoke(context)
    assert argv[:3] == ["uv", "run", "--with"]
    assert "pytest-randomly==5.0.0" in argv
    assert "pytest" in argv
    uv = shutil.which("uv")
    assert uv
    isolated = tmp_path / "bin"
    isolated.mkdir()
    (isolated / "uv").symlink_to(uv)
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(isolated), "/usr/bin", "/bin"])
    assert shutil.which("pytest", path=env["PATH"]) is None
    completed = subprocess.run(
        argv, cwd=context.root, env=env, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_scan_relative_interpreter_resolves_from_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, ".venv/bin/python -m pytest -q")
    interpreter = context.root / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("#!/bin/sh\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(P.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    argv = _adapter("pytest-randomly").invoke(context)
    install = seen["argv"]
    assert isinstance(install, list)
    chosen = install[install.index("--python") + 1]
    assert chosen == str(interpreter.resolve())
    assert seen["cwd"] == context.root
    assert argv[argv.index("-m") - 1] == str(interpreter.resolve())


def test_plugin_install_uses_a_bounded_sanitized_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, "python3 -m pytest -q")
    monkeypatch.setenv("SECRET_TOKEN", "should-not-leak")
    monkeypatch.setenv("PYTHONPATH", "/tmp/not-the-plugin")
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs.get("env")
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(P.subprocess, "run", fake_run)
    _adapter("pytest-randomly").invoke(context)
    env = seen["env"]
    assert isinstance(env, dict)
    assert "SECRET_TOKEN" not in env
    assert "PYTHONPATH" not in env
    assert env.get("PATH") == os.environ.get("PATH")
    assert seen["timeout"] == P._PLUGIN_INSTALL_TIMEOUT

    def explode_timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout") or 1)

    monkeypatch.setattr(P.subprocess, "run", explode_timeout)
    with pytest.raises(P.ToolGap) as timed_out:
        _adapter("pytest-socket").invoke(context)
    assert timed_out.value.reason == "timeout"

    def explode_os(argv, **kwargs):
        raise FileNotFoundError("uv")

    monkeypatch.setattr(P.subprocess, "run", explode_os)
    with pytest.raises(P.ToolGap) as missing:
        _adapter("pytest-socket").invoke(context)
    assert missing.value.reason == "missing"


def test_disable_socket_loads_without_plugin_autoload(tmp_path: Path) -> None:
    context = _context(tmp_path, "python3 -m pytest -q")
    (context.root / "test_net.py").write_text(
        "def test_net():\n"
        "    import socket\n"
        "    socket.create_connection(('example.invalid', 9))\n",
        encoding="utf-8",
    )
    argv = _adapter("pytest-socket").invoke(context)
    assert "-p" in argv and "pytest_socket" in argv
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    completed = subprocess.run(
        argv, cwd=context.root, env=env, capture_output=True, text=True, check=False,
    )
    combined = completed.stdout + completed.stderr
    assert "unrecognized arguments" not in combined
    assert "SocketBlockedError" in combined
