"""Package-local pytest fixtures for agent-launcher.

The launcher drives the operator's live sessions through herdr core (``hc``): ``hc send`` types
into a terminal and ``hc kill`` ends one. A test that forgets to stub ``launcher.run`` must fail
here rather than reach the host's core, so ``hc`` -- and old Herdr's ``herdr`` -- are shadowed on
``PATH`` for the whole session by a program that refuses and exits 127. A test that wants an
``hc`` puts its own fake earlier on ``PATH``, which still wins.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator

import pytest

_SHADOW = """#!/bin/sh
echo "$(basename "$0") is shadowed under pytest: a test reached the host's Herdr instead of stubbing it" >&2
exit 127
"""


@pytest.fixture(autouse=True, scope="session")
def _shadow_host_herdr(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Hide the host's ``hc`` and ``herdr`` for the session, then put ``PATH`` back."""
    shim_dir = tmp_path_factory.mktemp("no-host-herdr")
    for name in ("hc", "herdr"):
        shim = shim_dir / name
        shim.write_text(_SHADOW)
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    saved_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{shim_dir}{os.pathsep}{saved_path}"
    try:
        yield
    finally:
        os.environ["PATH"] = saved_path
