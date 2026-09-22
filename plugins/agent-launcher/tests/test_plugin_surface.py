"""Release-surface checks that do not presume the upstream repository.

Upstream ``tests/test_agent_launcher_plugin.py`` mostly drives Orchestrate's
install layout and that repository's marketplace. Those tests are listed as
dropped in ``CHANGELOG.md``. What remains is the packaged-file presence check
and the standalone composer's named stop, both of which run against this
package alone.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
BROKEN_COMPOSERS = [
    ("raise RuntimeError('composer exploded')\n", "RuntimeError: composer exploded"),
    ("raise ValueError('composer bad value')\n", "ValueError: composer bad value"),
    (
        'assert False, "composer contract violated"\n',
        "AssertionError: composer contract violated",
    ),
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> dict[str, str]:
    lines = _read(path).splitlines()
    assert lines[0] == "---"
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return data
        if ": " in line:
            key, value = line.split(": ", 1)
            data[key] = value.strip()
    raise AssertionError(f"{path} has no closing frontmatter marker")


def _declared_version() -> str:
    payload = json.loads(_read(PACKAGE / ".claude-plugin" / "plugin.json"))
    return str(payload["version"])


def _install_plugin(cache: Path) -> Path:
    destination = cache / "agent-launcher" / _declared_version()
    shutil.copytree(PACKAGE / ".claude-plugin", destination / ".claude-plugin")
    shutil.copytree(PACKAGE / "skills", destination / "skills")
    return destination


def test_agent_launcher_packaged_files() -> None:
    expected = (
        ".claude-plugin/plugin.json",
        "com.infiquetra.claude/plugin.json",
        "plugin.json",
        "README.md",
        "CHANGELOG.md",
        "skills/agent-launcher/SKILL.md",
        "skills/agent-launcher/scripts/composer.py",
        "skills/agent-launcher/scripts/launcher.py",
        "skills/agent-launcher/scripts/roster.py",
        "roles/README.md",
        "roles/index.json",
        "tests/test_launcher_contract.py",
    )
    for relative_path in expected:
        assert (PACKAGE / relative_path).is_file(), f"missing {relative_path}"
    assert _frontmatter(PACKAGE / "skills" / "agent-launcher" / "SKILL.md")["name"] == (
        "agent-launcher"
    )
    assert not (PACKAGE / "skills" / "herdr").exists()
    versions = {
        relative: json.loads(_read(PACKAGE / relative))["version"]
        for relative in (
            "plugin.json",
            ".claude-plugin/plugin.json",
            "com.infiquetra.claude/plugin.json",
        )
    }
    assert set(versions.values()) == {_declared_version()}


def test_standalone_launcher_missing_composer_is_a_named_stop(tmp_path: Path) -> None:
    launcher_install = _install_plugin(tmp_path)
    composer = launcher_install / "skills" / "agent-launcher" / "scripts" / "composer.py"
    composer.unlink()
    script = launcher_install / "skills" / "agent-launcher" / "scripts" / "launcher.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    output = result.stderr + result.stdout
    assert "cannot load agent-launcher composer parser" in output
    assert "file is missing" in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("broken", "expected_detail"),
    BROKEN_COMPOSERS,
    ids=["runtime-error", "value-error", "assertion-error"],
)
def test_standalone_launcher_broken_composer_is_a_named_stop(
    tmp_path: Path, broken: str, expected_detail: str
) -> None:
    """Any exception while loading composer.py becomes the named stop, with no traceback."""
    launcher_install = _install_plugin(tmp_path)
    composer = launcher_install / "skills" / "agent-launcher" / "scripts" / "composer.py"
    composer.write_text(broken, encoding="utf-8")
    script = launcher_install / "skills" / "agent-launcher" / "scripts" / "launcher.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    output = result.stderr + result.stdout
    assert "cannot load agent-launcher composer parser" in output
    assert expected_detail in output
    assert "Traceback" not in output
