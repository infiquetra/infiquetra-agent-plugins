"""Fixtures the saga tests rely on, carried from the upstream repo-wide conftest.

Only the autouse clears that change what a saga test observes are here. The
upstream file also stubs UniFi, Redis, and Orchestrate, which this package's
tests do not exercise.
"""

from __future__ import annotations

# The catalog runs pytest with --import-mode=importlib, which does not put
# this directory on sys.path; sibling helpers are resolved by path.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_ambient_saga_concurrency_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep emitter tests independent of the operator's shell concurrency override."""
    monkeypatch.delenv("SAGA_MAX_CONCURRENT", raising=False)


_FLEET_ENV_PREFIX = "INFIQUETRA_FLEET_"


@pytest.fixture(autouse=True)
def _clear_ambient_fleet_admission_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep admission tests independent of an operator-armed fleet environment."""
    for var in [key for key in os.environ if key.startswith(_FLEET_ENV_PREFIX)]:
        monkeypatch.delenv(var, raising=False)
    yield


_PLUGIN_ROOT_ENV_VARS = ("CLAUDE_PLUGIN_ROOT", "AGENT_LAUNCHER_ROOT")


def _assert_reads_from_boundary(reader, expected, *, boundary, description="value"):
    """Assert a value was re-read from a persisted artifact, not from memory.

    Carried from the upstream repo-wide conftest. The saga round-trip tests
    depend on it, and the rest of that file is not this package's.
    """
    boundaries = [boundary] if isinstance(boundary, (str, Path)) else list(boundary)
    for item in boundaries:
        path = Path(item)
        assert path.exists(), (
            f"boundary artifact {path} was never written — nothing crossed the persistence boundary"
        )
        assert path.stat().st_size > 0, f"boundary artifact {path} is empty"
    actual = reader()
    assert actual == expected, (
        f"{description}: value re-read from the boundary {actual!r} != expected {expected!r}"
    )
    return actual


@pytest.fixture
def assert_reads_from_boundary():
    """The shared boundary-crossing assertion helper."""
    return _assert_reads_from_boundary


@pytest.fixture(autouse=True)
def _clear_ambient_plugin_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep plugin-resolution tests independent of an installed-plugin root."""
    for var in _PLUGIN_ROOT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
