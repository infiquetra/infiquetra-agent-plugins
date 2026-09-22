"""Guards for this package's pytest suite.

The upstream repository kept the GitHub-write tripwire in its repo-root
``tests/conftest.py``. That file does not apply to ``plugins/*/tests``. The
tripwire lives here so ``test_mission_control.py`` cannot call the operator's
``gh`` when a test forgets its mock.
"""

from __future__ import annotations

import subprocess as _sp

import pytest

_GH_WRITE_TEST_MODULES = {"test_mission_control"}


@pytest.fixture(autouse=True)
def _no_live_gh(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.module.__name__.rsplit(".", 1)[-1] not in _GH_WRITE_TEST_MODULES:
        return
    for var in ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST", "GH_ENTERPRISE_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GH_CONFIG_DIR", "/nonexistent-no-live-gh-guard-279")

    real_run = _sp.run

    def _guard(cmd, *args, **kwargs):
        argv = cmd if isinstance(cmd, (list, tuple)) else str(cmd).split()
        parts = [str(part) for part in argv]
        first = parts[0] if parts else ""
        is_gh = first == "gh" or first.endswith("/gh")
        invokes_sdlc = any("sdlc_manager.py" in part for part in parts)
        if is_gh or invokes_sdlc:
            raise RuntimeError(
                "no-live-gh guard (#279): an unmocked GitHub-mutating call escaped a GitHub-write "
                "test module (direct `gh` or a nested sdlc_manager.py subprocess); inject a fake "
                f"runner instead of touching the live board. cmd={parts!r}"
            )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(_sp, "run", _guard)
