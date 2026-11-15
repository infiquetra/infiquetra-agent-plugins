"""Runtime evidence beyond the unchanged independent U1 acceptance contract."""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "security_scan_contract_fixtures", Path(__file__).with_name("test_security_scan.py")
)
assert _SPEC is not None and _SPEC.loader is not None
contract = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = contract
_SPEC.loader.exec_module(contract)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_output_files_are_private(tmp_path: Path) -> None:
    fixture = contract._plain(tmp_path, marker=False)
    machine = contract._machine(tmp_path)
    output = tmp_path / "out"
    scan = contract._scan(machine, fixture.path, output)
    assert scan.code == 0, scan.terminal
    for path in [output, *output.rglob("*")]:
        if not path.is_symlink():
            assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, path


def test_uninvoked_advisory_row_is_not_disclosed_as_invoked(tmp_path: Path) -> None:
    fixture = contract._plain(tmp_path, marker=False,
                              extra={"requirements.txt": "inert-pkg>=1.0.0\n"})
    machine = contract._machine(tmp_path)
    contract._python_stubs(machine)
    scan = contract._scan(machine, fixture.path, tmp_path / "out")
    assert scan.code == 2, scan.terminal
    assert machine.calls("pip-audit", scans=True) == []
    assert scan.rows()["pip-audit"]["status"] == "degraded"
    assert "pip-audit" not in scan.summary()["advisory_service_rows"]


def test_summary_displays_control_characters_as_data() -> None:
    scan = contract._module("security_scan")
    hostile = "inert\x1b]52;c;example\x07"
    summary = {"commit": "a" * 40, "exit_code": 2, "advisory_service_rows": [],
               "rows": [], "unscanned_submodules": [hostile]}
    displayed = scan._markdown(summary, [])
    assert "\x1b" not in displayed and "\x07" not in displayed
    assert "example" in displayed
