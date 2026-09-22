"""Dialogue ownership — B4 issue 916, behavioural rule survives retired names."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BRAINSTORM_SKILL = ROOT / "plugins/saga/skills/brainstorm/SKILL.md"


def _norm(text: str) -> str:
    return " ".join(text.split())


def check_ownership_rule(text: str) -> list[str]:
    violations: list[str] = []
    norm = _norm(text)
    if "Brainstorm owns the interactive creative dialogue" not in text:
        violations.append("missing Brainstorm owns the interactive creative dialogue")
    if "synthesis" not in norm.lower() or "judgment" not in norm.lower():
        violations.append("missing synthesis/judgment in ownership")
    if "private concern model" not in norm.lower():
        violations.append("missing private concern model")
    if (
        "every operator-facing exchange" not in norm.lower()
        and "every operator exchange" not in norm.lower()
    ):
        violations.append("missing every operator-facing exchange")
    if "never delegated" not in norm.lower() and "are never delegated" not in norm.lower():
        violations.append("missing are never delegated")
    if "bounded read-only helper set" not in norm.lower():
        violations.append("missing bounded read-only helper set as only permitted delegation")
    return violations


def check_no_retired_filename(text: str) -> list[str]:
    violations: list[str] = []
    for needle in ("engine_offer", "engine_session_runner", "retired runner"):
        if needle in text:
            violations.append(f"retired filename still present: {needle!r}")
    return violations


def check_no_growing_blacklist(text: str) -> list[str]:
    violations: list[str] = []
    # The Dialogue ownership section should name no .py filenames at all
    try:
        section = text.split("## Dialogue ownership")[1].split("## ")[0]
    except IndexError:
        violations.append("cannot locate Dialogue ownership section")
        return violations
    if ".py" in section:
        violations.append("Dialogue ownership section names a .py file (growing blacklist)")
    return violations


def check_transport_ownership(text: str) -> list[str]:
    violations: list[str] = []
    norm = _norm(text)
    if "a required session that is not in the Orchestrate run record is a HALT" not in norm:
        violations.append("missing HALT rule for absent Orchestrate session")
    if "Any cross-vendor session transport is Orchestrate" not in norm:
        violations.append("missing Orchestrate owns cross-vendor session transport")
    if "never delegated" not in norm.lower() or "another vendor session or runner" not in norm:
        violations.append("missing Brainstorm does not delegate dialogue to another vendor session")
    return violations


def test_ownership_rule_positive() -> None:
    text = BRAINSTORM_SKILL.read_text(encoding="utf-8")
    assert check_ownership_rule(text) == [], f"ownership: {check_ownership_rule(text)}"
    mutated = text.replace("Brainstorm owns the interactive creative dialogue", "")
    assert check_ownership_rule(mutated) != []


def test_no_retired_filename_negative() -> None:
    text = BRAINSTORM_SKILL.read_text(encoding="utf-8")
    assert check_no_retired_filename(text) == [], f"retired: {check_no_retired_filename(text)}"
    mutated = text + "\nengine_offer.py\n"
    assert check_no_retired_filename(mutated) != []


def test_no_growing_blacklist_negative() -> None:
    text = BRAINSTORM_SKILL.read_text(encoding="utf-8")
    assert check_no_growing_blacklist(text) == [], f"blacklist: {check_no_growing_blacklist(text)}"
    mutated = text.replace("## Dialogue ownership", "## Dialogue ownership\nDo not run foo.py\n")
    assert check_no_growing_blacklist(mutated) != []


def test_transport_ownership_survives_name_removal() -> None:
    text = BRAINSTORM_SKILL.read_text(encoding="utf-8")
    assert check_transport_ownership(text) == [], (
        f"transport ownership: {check_transport_ownership(text)}"
    )
    mutated = text.replace("is a HALT, never an invented review", "")
    assert check_transport_ownership(mutated) != []


def test_routing_contract_intact_integration() -> None:
    """Orchestrate's transport refusal is that package's test, not this one.

    The upstream file shelled out to ``tests/test_orchestrate_review_transport.py``.
    That test belongs to the orchestrate import. This package still pins the
    sentence the skill must keep; the cross-package pytest invocation does not
    survive the split.
    """
    text = BRAINSTORM_SKILL.read_text(encoding="utf-8")
    assert "is a HALT, never an invented review" in text
