"""Saga's own pattern checks: Semgrep rules for the six recurring defects (issue 154).

Four parts, one per unit that extends this file: the Semgrep pin (U1), the rule
files and their rule tests (U2), the adapter and runner wiring (U3), and the
setup question, docs, and fingerprint (U4).
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
RULES = REFERENCES / "semgrep"
FIXTURES = REPO_ROOT / "plugins" / "saga" / "tests" / "fixtures" / "review_tools"

sys.path.insert(0, str(SCRIPTS))

import review_formula  # noqa: E402
import review_tools  # noqa: E402

#: The six defects, in the card-table order: file stem, C1 row, harm, languages.
RULE_TABLE: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "release-shares-cleanup-block",
        "correctness.pattern.release-shares-cleanup",
        "two-holders-of-one-exclusive-thing",
        ("python", "typescript"),
    ),
    (
        "swallowed-error",
        "correctness.pattern.swallowed-error",
        "wrong-result-reported-as-success",
        ("python", "typescript"),
    ),
    (
        "silent-skip",
        "correctness.pattern.silent-skip",
        "wrong-result-reported-as-success",
        ("python", "typescript"),
    ),
    (
        "write-skips-shared-update-path",
        "correctness.pattern.write-skips-shared-update",
        "data-lost-or-corrupted",
        ("python", "typescript"),
    ),
    (
        "naive-time-comparison",
        "correctness.pattern.naive-time-comparison",
        "wrong-result-reported-as-success",
        ("python",),
    ),
    (
        "money-as-floating-point",
        "correctness.pattern.money-as-float",
        "money-or-resources-wrongly-moved",
        ("python", "typescript"),
    ),
)
DEFECTS = {
    "release-shares-cleanup-block": "A release sharing a cleanup block",
    "swallowed-error": "A swallowed error",
    "silent-skip": "A silent skip",
    "write-skips-shared-update-path": "A write that skips the shared update path",
    "naive-time-comparison": "A naive time comparison",
    "money-as-floating-point": "Money stored as floating point",
}
OUTCOME = "blocks unless the builder records a reason"
_TARGET_SUFFIX = {"python": "py", "typescript": "ts"}


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No part of this file may touch the network. A call fails the test."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("network blocked")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

_PIN_RE = re.compile(r"semgrep==([0-9][0-9A-Za-z.]*)")


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


def _load_rule(stem: str) -> dict[str, Any]:
    document = yaml.safe_load((RULES / f"{stem}.yaml").read_text(encoding="utf-8"))
    entries = document["rules"]
    assert len(entries) == 1, f"{stem}.yaml must hold exactly one rule"
    return entries[0]


def test_rule_files_carry_identity_message_languages_and_metadata() -> None:
    """U2: every rule file parses and names its id, languages, harm, and outcome."""
    assert sorted(path.name for path in RULES.glob("*.yaml")) == sorted(
        f"{stem}.yaml" for stem, _, _, _ in RULE_TABLE
    )
    for stem, row, harm, languages in RULE_TABLE:
        rule = _load_rule(stem)
        assert rule["id"] == f"saga.{stem}", stem
        assert "\n" not in rule["message"], f"{stem}: the message must be one line"
        assert rule["languages"] == list(languages), stem
        metadata = rule["metadata"]
        assert metadata["lens"] == "correctness", stem
        assert metadata["defect"] == DEFECTS[stem], stem
        assert metadata["harm"] == harm, stem
        assert metadata["outcome"] == OUTCOME, stem
        assert metadata["row"] == row, stem


def test_each_rule_language_has_a_marked_test_file() -> None:
    """U2: every table language has a paired target with ruleid: and ok: lines."""
    for stem, _, _, languages in RULE_TABLE:
        for language in languages:
            target = RULES / f"{stem}.{_TARGET_SUFFIX[language]}"
            assert target.is_file(), f"missing rule-test target: {target.name}"
            text = target.read_text(encoding="utf-8")
            assert re.search(rf"ruleid:\s*saga\.{stem}\b", text), f"{target.name} needs a ruleid: line"
            assert re.search(rf"\bok:\s*saga\.{stem}\b", text), f"{target.name} needs an ok: line"


def test_rule_metadata_stays_in_step_with_the_formula() -> None:
    """U2: each cited row blocks in the formula, excused by a pattern-check reason."""
    for stem, row, _, _ in RULE_TABLE:
        assert _load_rule(stem)["metadata"]["row"] == row
        assert review_formula.ROWS[row].outcome == "blocks", row
        assert review_formula.ROWS[row].excused_by == "pattern-check", row


def _semgrep_or_skip() -> str:
    binary = shutil.which("semgrep")
    if binary is None:
        pytest.skip("semgrep is not installed")
    pin = _tool_list_pin()
    probe = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, timeout=60
    )
    found = review_tools._VERSION.search(f"{probe.stdout}\n{probe.stderr}")
    version = found.group(0) if found else "unknown"
    if version != pin:
        pytest.skip(f"found semgrep {version}, want the pinned {pin}")
    return binary


def test_semgrep_rule_tests_pass_without_network() -> None:
    """U2: semgrep --test passes over the rules folder, proving every rule ran."""
    binary = _semgrep_or_skip()
    env = {**os.environ, "SEMGREP_ENABLE_VERSION_CHECK": "0"}
    proc = subprocess.run(
        [binary, "--test", "--metrics=off", str(RULES)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        cwd=REPO_ROOT,
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, combined
    assert "No unit tests found" not in combined
    match = re.search(r"^(\d+)/(\d+):", combined, re.M)
    assert match is not None, f"no passing count in semgrep --test output:\n{combined}"
    passed, total = match.group(1), match.group(2)
    assert passed == total == str(len(RULE_TABLE)), combined
