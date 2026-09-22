"""Keep the agy suite independent of the operator's shell and the harness root."""

from __future__ import annotations

import os

import pytest

_EXACT = ("CLAUDE_PLUGIN_ROOT", "AGENT_LAUNCHER_ROOT", "SAGA_MAX_CONCURRENT")
_PREFIXES = ("INFIQUETRA_FLEET_", "ORCHESTRATE_")


@pytest.fixture(autouse=True)
def _clear_ambient_delegation_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _EXACT:
        monkeypatch.delenv(name, raising=False)
    for name in [key for key in os.environ if key.startswith(_PREFIXES)]:
        monkeypatch.delenv(name, raising=False)
