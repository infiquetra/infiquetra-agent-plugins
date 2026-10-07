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
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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


@pytest.fixture(autouse=True)
def _no_live_tier_judgment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every saga test off the TypeSafe network (issue #96).

    ``admission.py``'s command line and ``tier_judgment.py plan`` run the tier judgment by default,
    and an operator shell usually carries ``TYPESAFE_API_KEY``. Switching the judgment off here
    means a test reaches the network only by un-setting the switch, and the tests that do so
    inject a fake ``ask``. The key is removed too, so a forgotten injection fails open instead of
    calling out.
    """
    monkeypatch.setenv("INFIQUETRA_TYPESAFE_TIERING", "off")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "allow_sockets: this test uses local sockets only, never the network",
    )


@pytest.fixture(autouse=True)
def _no_network(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
) -> None:
    """The saga suite makes no network call (issue 153).

    This mirrors the per-file guard in the review adapter suites: creating a
    socket raises. A test that needs local sockets opts out explicitly with
    the allow_sockets mark and justifies it where the mark sits.
    """
    if request.node.get_closest_marker("allow_sockets") is not None:
        real_socket = socket.socket

        def allow_unix_only(
            family: Any = None, *args: Any, **kwargs: Any
        ) -> socket.socket:
            seen = family
            if seen is None:
                seen = kwargs.get("family", socket.AF_INET)
            if seen != socket.AF_UNIX:
                raise AssertionError("saga tests must make no network call")
            if family is None:
                return real_socket(*args, **kwargs)
            return real_socket(family, *args, **kwargs)

        monkeypatch.setattr(socket, "socket", allow_unix_only)
        return

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("saga tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
