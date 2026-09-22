"""Structural formatting gate for saga doc-writing skills (issue #201).

This test enforces the shared formatting contract in
``plugins/saga/references/formatting-style.md`` so the generated-document
formatting cannot silently regress. It only reads markdown, so it adds no
``plugins/`` line coverage — that is expected; there is no ``--cov-fail-under``
gate (see ``pyproject.toml``).

What it checks:

1. No template/format file stacks bold-label lines without a blank line between
   them (the CommonMark collapse that produced "all jumbled together").
2. Each of the nine doc-writing skills links the shared contract somewhere in
   its skill directory.
3. The shared contract's golden specimen passes the same collapse check.

It deliberately does NOT check soft-wrap: rule 5 is a generated-output rule, and
the template *source* files in this repo stay hard-wrapped and editor-friendly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SAGA_ROOT = REPO_ROOT / "plugins" / "saga"
SHARED_CONTRACT = SAGA_ROOT / "references" / "formatting-style.md"

# A line that *begins* (after optional indent) with a bold label, e.g.
# ``**basis:** direct: ...``. A bullet (``- **basis:**``) does NOT match — those
# are list items, which render fine. Two or more of these on adjacent non-blank
# lines is the fatal collapse.
BOLD_LABEL_LINE = re.compile(r"^[ \t]*\*\*[^*\n]+:\*\*")

# The nine skills that write durable documents, mapped to the file(s) that carry
# their output format (the collapse-checked set). doc-review carries its report
# format in SKILL.md (no references dir).
DOC_OUTPUT_FILES: dict[str, list[str]] = {
    "ideate": [
        "references/ideation-artifact.md",
        "references/convergence-and-partnership.md",
    ],
    "plan": ["references/plan-sections.md"],
    "brainstorm": ["references/requirements-sections.md"],
    "spec": ["references/spec-template.md"],
    "strategy": ["references/strategy-template.md"],
    "retro": ["references/retro-report.md"],
    "doc-review": ["SKILL.md"],
    "code-review": ["references/findings-schema.md"],
    "founder-review": ["references/review-modes.md"],
}

DOC_SKILLS = sorted(DOC_OUTPUT_FILES)

# The repo-relative link every doc-writing skill must reference.
CONTRACT_LINK = "saga/references/formatting-style.md"


def find_collapse(text: str) -> int | None:
    """Return the 1-based line number where a bold-label collapse begins.

    A collapse is two or more adjacent non-blank lines that each begin with a
    bold label. Returns ``None`` when no collapse is present.
    """
    previous_was_label = False
    for index, line in enumerate(text.splitlines(), start=1):
        is_label = bool(BOLD_LABEL_LINE.match(line))
        if is_label and previous_was_label:
            return index
        previous_was_label = is_label
    return None


def _collapse_target_files() -> list[Path]:
    files: list[Path] = [SHARED_CONTRACT]
    for skill, rel_paths in DOC_OUTPUT_FILES.items():
        for rel in rel_paths:
            files.append(SAGA_ROOT / "skills" / skill / rel)
    return files


# --- the collapse detector itself (gives the gate teeth + documents the rule) ---


def test_collapse_detector_flags_stacked_labels() -> None:
    bad = "**basis:** direct: x\n**confidence:** 88\n**complexity:** Low\n"
    assert find_collapse(bad) == 2


def test_collapse_detector_allows_blank_separated_labels() -> None:
    good = "**basis:** direct: x\n\n**confidence:** 88\n\n**complexity:** Low\n"
    assert find_collapse(good) is None


def test_collapse_detector_ignores_bulleted_bold_labels() -> None:
    # Bullets render fine and are the legitimate per-unit form.
    bulleted = "- **Goal** — do the thing\n- **Files** — a.md\n- **Approach** — x\n"
    assert find_collapse(bulleted) is None


# --- the contract exists and is self-consistent ---


def test_shared_contract_exists() -> None:
    assert SHARED_CONTRACT.is_file(), f"missing shared contract: {SHARED_CONTRACT}"


def test_shared_contract_specimen_has_no_collapse() -> None:
    line = find_collapse(SHARED_CONTRACT.read_text())
    assert line is None, f"{SHARED_CONTRACT} has a bold-label collapse at line {line}"


# --- every doc-output file is collapse-free ---


@pytest.mark.parametrize(
    "path",
    _collapse_target_files(),
    ids=lambda p: str(p.relative_to(SAGA_ROOT)),
)
def test_doc_output_file_has_no_collapse(path: Path) -> None:
    assert path.is_file(), f"expected doc-output file is missing: {path}"
    line = find_collapse(path.read_text())
    assert line is None, (
        f"{path.relative_to(REPO_ROOT)} stacks bold-label lines at line {line} "
        f"(CommonMark collapse). Separate them with blank lines or use a table "
        f"per saga/references/formatting-style.md."
    )


# --- every doc-writing skill links the shared contract ---


@pytest.mark.parametrize("skill", DOC_SKILLS)
def test_doc_skill_links_shared_contract(skill: str) -> None:
    skill_dir = SAGA_ROOT / "skills" / skill
    assert skill_dir.is_dir(), f"missing skill dir: {skill_dir}"
    linked = any(CONTRACT_LINK in md.read_text() for md in skill_dir.rglob("*.md"))
    assert linked, (
        f"skill '{skill}' does not link {CONTRACT_LINK} anywhere in its dir; "
        f"add the link so its generated docs follow the formatting contract."
    )
