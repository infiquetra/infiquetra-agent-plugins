"""Package-local pytest fixtures for Orchestrate.

The upstream repository shadowed ``herdr`` from a root ``conftest.py``. This
package repeats that shadow so a test that reaches the operator's live Herdr
fails here instead. It also pins the two companions the suite was written
against, because neither is the tree this catalog currently ships:

* ``AGENT_LAUNCHER_ROOT`` is a frozen agent-launcher 1.7.0. The sibling
  ``plugins/agent-launcher`` in this catalog is 1.0.0 and does not define the
  names Orchestrate execs. Production, with the variable unset, still resolves
  that sibling.
* ``ORCHESTRATE_RUN_RECORD`` is saga's ``run_record.py`` from the same upstream
  pin when ``plugins/saga`` is not beside this package.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestrate_support import RUN_RECORD_SCRIPT

FIXTURE_LAUNCHER_ROOT = (
    Path(__file__).resolve().parent / "fixtures" / "agent-launcher-1.7.0"
)

_COMPANION_ENV = ("AGENT_LAUNCHER_ROOT", "ORCHESTRATE_RUN_RECORD", "CLAUDE_PLUGIN_ROOT")

_SHADOW_HERDR = """#!/bin/sh
echo "herdr is shadowed under pytest: a test reached the host's herdr instead of stubbing it" >&2
exit 127
"""


def _restore_env(saved: dict[str, str | None]) -> None:
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(autouse=True, scope="module")
def _pin_companions_and_shadow_herdr(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Pin companions and hide the host Herdr for one test module, then put both back.

    Ingest runs when a module fixture loads the driver, which is before any
    function fixture. The pin therefore lives for the module. It is restored
    before the next package's tests so a combined ``plugins/*/tests`` run does
    not inherit it.
    """
    saved = {name: os.environ.get(name) for name in _COMPANION_ENV}
    saved_path = os.environ.get("PATH", "")
    os.environ["AGENT_LAUNCHER_ROOT"] = str(FIXTURE_LAUNCHER_ROOT)
    os.environ["ORCHESTRATE_RUN_RECORD"] = str(RUN_RECORD_SCRIPT)
    os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
    shim_dir = tmp_path_factory.mktemp("no-host-herdr")
    shim = shim_dir / "herdr"
    shim.write_text(_SHADOW_HERDR)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = f"{shim_dir}{os.pathsep}{saved_path}"
    try:
        yield
    finally:
        _restore_env(saved)
        os.environ["PATH"] = saved_path


@pytest.fixture(autouse=True)
def _isolate_orchestrate_host_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep registers and run secrets out of the operator's home directory."""
    base = tmp_path.parent / f"{tmp_path.name}-orchestrate-host"
    monkeypatch.setenv("ORCHESTRATE_REGISTER_DIR", str(base / "registers"))
    monkeypatch.setenv("ORCHESTRATE_RUN_SECRET_DIR", str(base / "secrets"))
    monkeypatch.delenv("SAGA_MAX_CONCURRENT", raising=False)


@pytest.fixture(autouse=True)
def _repin_companions_for_one_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the module pin in force for one test, and let the test override it.

    ``monkeypatch`` restores the module pin when the test ends, so a test that
    points the companion at a broken tree does not leak into the next test.
    """
    monkeypatch.setenv("AGENT_LAUNCHER_ROOT", str(FIXTURE_LAUNCHER_ROOT))
    monkeypatch.setenv("ORCHESTRATE_RUN_RECORD", str(RUN_RECORD_SCRIPT))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
