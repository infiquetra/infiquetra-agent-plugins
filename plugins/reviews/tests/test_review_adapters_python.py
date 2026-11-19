"""pytest-randomly and pytest-socket load under the resolved interpreter (issues 227 and 246)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

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
