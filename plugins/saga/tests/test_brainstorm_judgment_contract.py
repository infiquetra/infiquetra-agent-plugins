"""Brainstorm judgment contract — issue 914 (B2).

Twelve assertions over the judgment model and helper bounds, each through a
module-level ``check_*(text)`` predicate (KTD3) so U3 can mutate it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BRAINSTORM_SKILL = ROOT / "plugins/saga/skills/brainstorm/SKILL.md"
REQUIREMENTS_SECTIONS = ROOT / "plugins/saga/skills/brainstorm/references/requirements-sections.md"
SANDBOX_SITES = ROOT / "plugins/saga/references/sandbox-spawn-sites.md"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _mutate(text: str, needle: str) -> str:
    assert needle in text, f"mutation needle not found: {needle!r}"
    return text.replace(needle, "", 1)


# ---------------------------------------------------------------------------
# Module-level predicates (KTD3)
# ---------------------------------------------------------------------------


def check_privacy_skill(text: str) -> list[str]:
    violations: list[str] = []
    norm = _norm(text)
    if "privately classify" not in norm.lower():
        violations.append("missing privately classify")
    for state in ("Clear", "Partial", "Missing", "Not material"):
        if state not in text:
            violations.append(f"missing state {state!r}")
    if "never written to the artifact" not in norm:
        violations.append("missing never written to the artifact")
    if "never persisted" not in norm:
        violations.append("missing never persisted")
    if "never rendered as a document section" not in norm:
        violations.append("missing never rendered as a document section")
    if "never shown as a score" not in norm:
        violations.append("missing never shown as a score")
    if "never surfaced to the operator" not in norm:
        violations.append("missing never surfaced to the operator")
    return violations


def check_privacy_sections(text: str) -> list[str]:
    violations: list[str] = []
    # No state name should appear as a metadata field or required section.
    # Check for markdown headings or bullet fields naming them.
    for state in ("Clear", "Partial", "Missing"):
        # Look for bullet like "- **`Clear`**" or heading "## Clear"
        if f"`{state}`" in text or f"## {state}" in text or f"### {state}" in text:
            violations.append(f"state {state!r} leaked into section contract")
    # Not material is a common phrase – check for it as a section heading only
    if "## Not material" in text or "### Not material" in text:
        violations.append("Not material leaked as section")
    return violations


def check_named_assurance_levels(text: str) -> list[str]:
    violations: list[str] = []
    if re.search(r"\b(low|standard|high)[ -]assurance\b", text, re.IGNORECASE):
        violations.append("found low/standard/high assurance pattern")
    if re.search(r"assurance level", text, re.IGNORECASE):
        violations.append("found assurance level")
    return violations


def check_no_named_tiers_rule(text: str) -> list[str]:
    violations: list[str] = []
    if "No named tiers are used" not in text:
        violations.append("missing No named tiers are used")
    return violations


def check_consequence_factors(text: str) -> list[str]:
    violations: list[str] = []
    factors = [
        "data sensitivity",
        "granted authority",
        "exposure to untrusted input",
        "reversibility and blast radius",
        "recovery expectations",
        "auditability or consent",
    ]
    lower = text.lower()
    for factor in factors:
        if factor not in lower:
            violations.append(f"missing consequence factor {factor!r}")
    return violations


def check_lightweight_helpers(text: str) -> list[str]:
    violations: list[str] = []
    norm = _norm(text)
    if "Lightweight" not in text:
        violations.append("missing Lightweight")
    if "launches zero helpers" not in norm:
        violations.append("missing launches zero helpers")
    return violations


def _phase_1_1(text: str) -> str:
    start = text.find("### 1.1 Existing-context scan")
    end = text.find("### 1.2", start)
    if start != -1 and end != -1:
        return text[start:end]
    return text


def check_helper_ceiling(text: str) -> list[str]:
    violations: list[str] = []
    section = _phase_1_1(text)
    norm = _norm(section)
    if "at most one read-only repository-grounding scout" not in norm.lower():
        violations.append("missing at most one grounding scout in Phase 1.1")
    if "at most one independent claim verifier" not in norm:
        violations.append("missing at most one claim verifier in Phase 1.1")
    if "distinct evidence question" not in norm:
        violations.append("missing distinct evidence question in Phase 1.1")
    if "two helpers on the same question is one too many" not in norm:
        violations.append("missing two helpers on same question guard in Phase 1.1")
    if "These are ceilings, not required launches" not in norm:
        violations.append("missing ceilings not required launches in Phase 1.1")
    return violations


def check_helper_capability(text: str) -> list[str]:
    violations: list[str] = []
    norm = _norm(text)
    if "worktree-isolated" not in norm:
        violations.append("missing worktree-isolated")
    # The safeguard itself: helpers are read-only by omitting the file-mutation
    # tools. Both helpers must carry the instruction — the verifier and the scout
    # each state it, and the scout is the one not worktree-isolated so tool omission
    # is its only protection. Require two occurrences (TEST-13).
    if norm.count("read-only by omission of `Edit`/`Write`/`NotebookEdit`") < 2:
        violations.append(
            "missing read-only by omission of Edit/Write/NotebookEdit (expected 2 occurrences for both helpers)"
        )
    if "may not choose requirements" not in norm:
        violations.append("missing may not choose requirements")
    if "may not address the operator" not in norm:
        violations.append("missing may not address the operator")
    if "subagent_type: Explore" not in text:
        violations.append("missing subagent_type: Explore")
    # The verifier used to be named by subagent_type; issue 1030 removed both saga agents and the
    # isolation is now a property of how the helper is hosted. The contract the check defends is
    # unchanged -- the verifier is read-only and runs in its own worktree -- so it is checked
    # through the words that still state it rather than through an agent name that no longer exists.
    if "in its own disposable worktree" not in text:
        violations.append("missing: the claim verifier runs in its own disposable worktree")
    if "A state-free capability with no tick" not in text:
        violations.append("missing state-free capability sentence")
    return violations


def check_one_question(text: str) -> list[str]:
    violations: list[str] = []
    if "One question per turn" not in text:
        violations.append("missing One question per turn")
    return violations


def check_spawn_site_row(text: str) -> list[str]:
    violations: list[str] = []
    rows = [line for line in text.splitlines() if line.startswith("| `brainstorm` |")]
    if len(rows) != 1:
        violations.append(f"expected exactly one brainstorm row, found {len(rows)}")
        return violations
    row = rows[0]
    if "`judgment`" not in row:
        violations.append("brainstorm row work-shape is not judgment")
    if "~line" in row:
        violations.append("brainstorm row contains forbidden ~line")
    if re.search(r"line \d", row):
        violations.append("brainstorm row contains digit-bearing line reference")
    if re.search(r"\(~line", row) or re.search(r"~lines", row):
        violations.append("brainstorm row contains line reference")
    # Also check for any hand-maintained location like "(~" or "lines"
    return violations


def check_scout_outside_verifier_class(text: str) -> list[str]:
    violations: list[str] = []
    # In-scope table is between ## In-scope and ## Out-of-scope
    try:
        in_scope_section = text.split("## In-scope")[1].split("## Out-of-scope")[0]
    except IndexError:
        violations.append("cannot locate in-scope section")
        return violations
    if "Explore" in in_scope_section:
        violations.append("Explore found inside in-scope table — scout must be outside")
    # Scout subsection must exist outside the table
    if "Brainstorm Phase 1.1 grounding scout" not in text:
        violations.append("missing scout subsection heading")
    if "survey-class" not in text.lower():
        violations.append("missing survey-class in scout subsection")
    if "subagent_type: Explore" not in text:
        violations.append("missing subagent_type: Explore in scout subsection")
    if (
        "read-only by tool omission" not in text.lower()
        and "read-only by omission" not in text.lower()
    ):
        violations.append("missing read-only by omission description")
    # Check that scout subsection explicitly says not worktree-isolated
    scout_section = ""
    if "## Brainstorm Phase 1.1 grounding scout" in text:
        scout_section = text.split("## Brainstorm Phase 1.1 grounding scout")[1].split("## ")[0]
        if "not" not in scout_section.lower() or "worktree-isolated" not in scout_section.lower():
            violations.append("missing not worktree-isolated rationale in scout subsection")
        if "structurally cannot write" in scout_section:
            violations.append("forbidden phrase structurally cannot write in scout subsection")
    return violations


def check_grounding_before_asking(text: str) -> list[str]:
    violations: list[str] = []
    norm = _norm(text)
    if "Ground repository-discoverable facts before asking the operator" not in norm:
        violations.append("missing Ground repository-discoverable facts before asking")
    return violations


def check_must_probe_survives(text: str) -> list[str]:
    violations: list[str] = []
    norm = _norm(text)
    if "Probe only the gaps Phase 1.2 actually found" not in norm:
        violations.append("missing Probe only the gaps Phase 1.2 actually found")
    if "Phase 1 cannot end with an un-probed rigor gap that is present" not in norm:
        violations.append("missing Phase 1 cannot end with un-probed gap")
    if "A rigor gap Phase 1.2 actually found is still probed" not in norm:
        violations.append("missing rigor gap still probed exemption")
    return violations


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def test_privacy_negative_and_mutation_fails() -> None:
    skill_text = _read(BRAINSTORM_SKILL)
    sections_text = _read(REQUIREMENTS_SECTIONS)
    assert check_privacy_skill(skill_text) == [], (
        f"privacy skill: {check_privacy_skill(skill_text)}"
    )
    assert check_privacy_sections(sections_text) == [], (
        f"privacy sections: {check_privacy_sections(sections_text)}"
    )
    mutated = _mutate(skill_text, "never written to the artifact")
    assert check_privacy_skill(mutated) != []
    # Sections must not leak state names — injecting one must be caught
    mutated_sections = sections_text + "\n- **`Clear`** — test leak\n"
    assert check_privacy_sections(mutated_sections) != []


# ---------------------------------------------------------------------------
# Named assurance levels — negative
# ---------------------------------------------------------------------------


def test_named_assurance_levels_negative_and_consequence_factors_present() -> None:
    text = _read(BRAINSTORM_SKILL)
    assert check_named_assurance_levels(text) == [], (
        f"level violations: {check_named_assurance_levels(text)}"
    )
    assert check_consequence_factors(text) == [], (
        f"factor violations: {check_consequence_factors(text)}"
    )
    mutated = text + "\nlow assurance test\n"
    assert check_named_assurance_levels(mutated) != []
    mutated2 = _mutate(text, "data sensitivity")
    assert check_consequence_factors(mutated2) != []


# ---------------------------------------------------------------------------
# Lightweight helpers — positive
# ---------------------------------------------------------------------------


def test_lightweight_helpers_positive_and_mutation_fails() -> None:
    text = _read(BRAINSTORM_SKILL)
    assert check_lightweight_helpers(text) == [], f"lightweight: {check_lightweight_helpers(text)}"
    mutated = _mutate(text, "launches zero helpers")
    assert check_lightweight_helpers(mutated) != []


# ---------------------------------------------------------------------------
# Helper ceiling — negative
# ---------------------------------------------------------------------------


def test_helper_ceiling_negative_and_mutation_fails() -> None:
    text = _read(BRAINSTORM_SKILL)
    assert check_helper_ceiling(text) == [], f"ceiling: {check_helper_ceiling(text)}"
    mutated = _mutate(text, "two helpers on the same question is one too many")
    assert check_helper_ceiling(mutated) != []
    mutated2 = _mutate(text, "These are ceilings, not required launches")
    assert check_helper_ceiling(mutated2) != []


# ---------------------------------------------------------------------------
# Helper capability — negative
# ---------------------------------------------------------------------------


def test_helper_capability_negative_and_mutation_fails() -> None:
    text = _read(BRAINSTORM_SKILL)
    assert check_helper_capability(text) == [], f"capability: {check_helper_capability(text)}"
    mutated = _mutate(text, "A state-free capability with no tick")
    assert check_helper_capability(mutated) != []
    mutated2 = _mutate(text, "subagent_type: Explore")
    assert check_helper_capability(mutated2) != []


# ---------------------------------------------------------------------------
# One question at a time — positive
# ---------------------------------------------------------------------------


def test_one_question_at_a_time_positive_and_mutation_fails() -> None:
    text = _read(BRAINSTORM_SKILL)
    assert check_one_question(text) == [], f"one question: {check_one_question(text)}"
    mutated = _mutate(text, "One question per turn")
    assert check_one_question(mutated) != []


# ---------------------------------------------------------------------------
# Spawn-site row — positive
# ---------------------------------------------------------------------------


def test_grounding_before_asking_positive_and_mutation_fails() -> None:
    text = _read(BRAINSTORM_SKILL)
    assert check_grounding_before_asking(text) == [], (
        f"grounding: {check_grounding_before_asking(text)}"
    )
    mutated = _mutate(text, "Ground repository-discoverable facts before asking the operator")
    assert check_grounding_before_asking(mutated) != []


# ---------------------------------------------------------------------------
# Must-probe rule survives — positive
# ---------------------------------------------------------------------------


def test_must_probe_rule_survives_positive_and_mutation_fails() -> None:
    text = _read(BRAINSTORM_SKILL)
    assert check_must_probe_survives(text) == [], f"must-probe: {check_must_probe_survives(text)}"
    mutated = _mutate(text, "actually found is still probed")
    assert check_must_probe_survives(mutated) != []
