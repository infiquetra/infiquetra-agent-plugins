"""Package-local pytest fixtures for Voice.

Voice reads its own terminal address from ``HC_TERMINAL_ID`` and runs
``hc`` to read terminals, label them and type into them. A developer who
runs this suite inside a Herdr terminal has both, so a test that forgot to
stub them would read or type into the developer's real herdr core. This
fixture removes the terminal address and puts a failing ``hc`` (and
``herdr``) first on ``PATH`` for each test module, then restores both, so
such a test fails loudly instead. Tests that need herdr core set a fake one
explicitly (see ``hc_stub.py``).
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator

import pytest

_HOST_ENV = ("HC_TERMINAL_ID", "VOICE_HC_BIN")

_SHADOW = """#!/bin/sh
echo "{name} is shadowed under pytest: a voice test reached the host's herdr core instead of stubbing it" >&2
exit 127
"""


@pytest.fixture(autouse=True, scope="module")
def _shadow_host_herdr_core(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    saved = {name: os.environ.get(name) for name in _HOST_ENV}
    saved_path = os.environ.get("PATH", "")
    for name in _HOST_ENV:
        os.environ.pop(name, None)
    shim_dir = tmp_path_factory.mktemp("no-host-herdr-core")
    for name in ("hc", "herdr"):
        shim = shim_dir / name
        shim.write_text(_SHADOW.format(name=name), encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = f"{shim_dir}{os.pathsep}{saved_path}"
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        os.environ["PATH"] = saved_path
