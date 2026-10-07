"""Saga's own pattern checks: Semgrep rules for the six recurring defects (issue 154).

Four parts, one per unit that extends this file: the Semgrep pin (U1), the rule
files and their rule tests (U2), the adapter and runner wiring (U3), and the
setup question, docs, and fingerprint (U4).
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
RULES = REFERENCES / "semgrep"

sys.path.insert(0, str(SCRIPTS))

import review_tools  # noqa: E402


_PIN_RE = re.compile(r"semgrep==([0-9][0-9A-Za-z.]*)")


def _requirements_pin() -> str | None:
    pins = []
    text = (REPO_ROOT / "requirements-plugin-tests.txt").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _PIN_RE.search(stripped)
        if match:
            pins.append(match.group(1))
    assert len(pins) <= 1, f"semgrep pinned twice in requirements-plugin-tests.txt: {pins}"
    return pins[0] if pins else None


def _workflow_pin() -> str | None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pins = _PIN_RE.findall(text)
    assert len(pins) <= 1, f"semgrep pinned twice in ci.yml: {pins}"
    return pins[0] if pins else None


def _tool_list_pin() -> str:
    rows = {row["id"]: row for row in review_tools.load_tool_list()}
    saga = rows["semgrep-saga"]["default_version"]
    security = rows["semgrep-security"]["default_version"]
    assert saga == security, f"the two semgrep rows disagree: saga {saga}, security {security}"
    return str(saga)


def test_semgrep_pin_matches_the_tool_list() -> None:
    """U1: one Semgrep version in the tool list and in exactly one install site."""
    pin = _tool_list_pin()
    assert pin != "not-recorded", "the semgrep rows still carry no pin"
    sites = {
        "requirements-plugin-tests.txt": _requirements_pin(),
        ".github/workflows/ci.yml": _workflow_pin(),
    }
    found = {name: version for name, version in sites.items() if version is not None}
    assert len(found) == 1, f"the semgrep pin must live in exactly one install site: {found}"
    site, installed = next(iter(found.items()))
    assert installed == pin, f"{site} pins semgrep {installed}, the tool list pins {pin}"
