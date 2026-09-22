"""Lifecycle ordering consistency — KTD6 mechanical check, plus Shaping distinction.

No skill's lifecycle prose is edited; the check discovers the block by shape.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


# Canonical Think-phase command ordering — the single source of truth for this check.
# Ordered as they appear in the most complete surviving block. The block was previously read from
# /loop's skill, which issue 1030 removed with the command; /plan carries the same ordering.
CANONICAL_ORDER = (
    "/office-hours",
    "/ideate",
    "/brainstorm",
    "/plan",
    "/strategy",
    "/doc-review",
    "/work",
    "/code-review",
    "/qa",
)

# Verified membership — discovered by block shape, not hardcoded line numbers.
# The block is the near-identical three-line core: `/ideate` answers → `/brainstorm` answers → `/plan` answers
VERIFIED_BLOCK_SKILLS = (
    ROOT / "plugins/saga/skills/ideate/SKILL.md",
    ROOT / "plugins/saga/skills/office-hours/SKILL.md",
    ROOT / "plugins/saga/skills/plan/SKILL.md",
)

# Out-of-set files — must be recorded why, not silently skipped
OUT_OF_SET = {
    ROOT
    / "plugins/saga/skills/founder-review/SKILL.md": "variant sentence, no /ideate line, differently worded",
    ROOT / "plugins/saga/skills/strategy/SKILL.md": "only inline ordering mentions, not the block",
}

SAGA_SPEC = ROOT / "plugins/saga/references/saga-spec.md"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _extract_commands_in_order(text: str) -> list[str]:
    # Extract slash-commands in order of appearance, lowercased
    return re.findall(r"/[a-z][a-z\-]*", text.lower())


def _has_block_shape(text: str) -> bool:
    # The duplicated block's shape: three markers in order, as an ordered window over all occurrences
    ideate_positions = [m.start() for m in re.finditer(r"`/ideate` answers:", text)]
    brain_positions = [m.start() for m in re.finditer(r"`/brainstorm` answers:", text)]
    plan_positions = [m.start() for m in re.finditer(r"`/plan` answers:", text)]
    for i in ideate_positions:
        for b in brain_positions:
            if b <= i:
                continue
            for p in plan_positions:
                if p > b:
                    return True
    return False


def check_block_membership(texts: dict[Path, str]) -> list[str]:
    violations: list[str] = []
    discovered: set[Path] = set()
    for path, content in texts.items():
        if _has_block_shape(content):
            discovered.add(path)
    expected = set(VERIFIED_BLOCK_SKILLS)
    if discovered != expected:
        violations.append(
            f"discovered {sorted(str(p.relative_to(ROOT)) for p in discovered)!r} != expected {sorted(str(p.relative_to(ROOT)) for p in expected)!r}"
        )
    for path in OUT_OF_SET:
        if path in discovered:
            violations.append(f"out-of-set {path.relative_to(ROOT)} incorrectly in discovered set")
    return violations


def _extract_block(text: str) -> str:
    # Extract the duplicated lifecycle block region (from /office-hours answers to /plan answers)
    start = text.find("`/office-hours` answers:")
    if start == -1:
        start = text.find("`/ideate` answers:")
    end = text.find("`/plan` answers:")
    if start == -1 or end == -1:
        return ""
    # Include a bit after plan line, then cut at next blank line or heading
    snippet = text[start : end + 200]
    # Cut at next double newline or heading
    cut = snippet.find("\n\n")
    if cut != -1:
        snippet = snippet[:cut]
    return snippet


def check_block_consistency(text: str) -> list[str]:
    violations: list[str] = []
    block = _extract_block(text)
    if not block:
        return violations
    cmds = _extract_commands_in_order(block)
    # Filter to only those in canonical, preserving order as they appear
    filtered = [c for c in cmds if c in CANONICAL_ORDER]
    # Check filtered is sub-sequence of canonical (order preserved, not necessarily contiguous)
    idx = -1
    for cmd in filtered:
        pos = -1
        for j in range(idx + 1, len(CANONICAL_ORDER)):
            if CANONICAL_ORDER[j] == cmd:
                pos = j
                break
        if pos == -1:
            violations.append(f"command {cmd!r} not in canonical order or out of order")
            continue
        if pos <= idx:
            violations.append(f"command {cmd!r} appears out of canonical order")
        idx = pos
    return violations


def check_placement(text: str) -> list[str]:
    violations: list[str] = []
    block = _extract_block(text)
    if not block:
        violations.append("missing lifecycle block")
        return violations
    lower = block.lower()
    idx_ideate = lower.find("/ideate")
    idx_brain = lower.find("/brainstorm")
    idx_plan = lower.find("/plan")
    if idx_ideate == -1 or idx_brain == -1 or idx_plan == -1:
        violations.append("missing ideate/brainstorm/plan in block")
        return violations
    if not (idx_ideate < idx_brain < idx_plan):
        violations.append(
            f"placement violated: ideate {idx_ideate} brain {idx_brain} plan {idx_plan}"
        )
    return violations


def check_shaping_single(text: str) -> list[str]:
    violations: list[str] = []
    # Count lines containing shaping (case-insensitive) — should be exactly 1
    count = sum(1 for line in text.splitlines() if re.search(r"shaping", line, re.IGNORECASE))
    if count != 1:
        violations.append(f"saga-spec shaping lines {count} != 1")
    if "Shaping is an Operations board Status" not in text:
        violations.append("missing Shaping board Status statement")
    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_block_membership_positive() -> None:
    texts = {
        p: p.read_text(encoding="utf-8") for p in (ROOT / "plugins/saga/skills").rglob("SKILL.md")
    }
    violations = check_block_membership(texts)
    assert violations == [], f"block membership: {violations}"
    # Out-of-set files must be absent from discovered set — record why
    for path, reason in OUT_OF_SET.items():
        assert path.exists(), f"out-of-set file missing: {path}"
        # Ensure they are not block-carrying
        assert not _has_block_shape(path.read_text(encoding="utf-8")), (
            f"{path} unexpectedly has block shape ({reason})"
        )


def test_block_consistency_positive() -> None:
    for path in VERIFIED_BLOCK_SKILLS:
        text = path.read_text(encoding="utf-8")
        violations = check_block_consistency(text)
        assert violations == [], f"{path.relative_to(ROOT)} consistency: {violations}"


def test_placement_unchanged_negative() -> None:
    for path in VERIFIED_BLOCK_SKILLS:
        text = path.read_text(encoding="utf-8")
        violations = check_placement(text)
        assert violations == [], f"{path.relative_to(ROOT)} placement: {violations}"


def test_drift_is_caught_control() -> None:
    # Seeded block with /plan before /brainstorm must be reported
    seeded = """
- `/ideate` answers: "What are the strongest ideas?"
- `/plan` answers: "How should it be built?"
- `/brainstorm` answers: "What exactly should one chosen idea mean?"
"""
    # This seeded block has plan before brainstorm — out of canonical order
    # Extract and check
    violations = check_block_consistency(seeded)
    # The seeded order is ideate, plan, brainstorm — plan (index 3) before brainstorm (2) is out of order relative to canonical
    # Our check should catch the inversion because brainstorm appears after plan but canonical has brainstorm before plan
    assert violations != [], "seeded inversion not caught"
    # Also placement check should catch
    assert check_placement(seeded) != []


def test_has_block_shape_ordering_seeded_negative() -> None:
    # A synthetic text carrying all three block markers with /plan before
    # /brainstorm must NOT have the block shape: the clause is ordered, not a
    # mere all-present check.
    seeded = """
- `/ideate` answers: "What are the strongest ideas?"
- `/plan` answers: "How should it be built?"
- `/brainstorm` answers: "What exactly should one chosen idea mean?"
"""
    assert _has_block_shape(seeded) is False
    ordered = """
- `/ideate` answers: "What are the strongest ideas?"
- `/brainstorm` answers: "What exactly should one chosen idea mean?"
- `/plan` answers: "How should it be built?"
"""
    assert _has_block_shape(ordered) is True


def test_out_of_set_files_negative() -> None:
    for path, reason in OUT_OF_SET.items():
        text = path.read_text(encoding="utf-8")
        # Predicate reports nothing for these files (they are not block-carrying)
        assert not _has_block_shape(text), f"{path} should not have block shape"
        # And we record why
        assert reason, f"missing reason for out-of-set {path}"


def test_shaping_positive() -> None:
    text = SAGA_SPEC.read_text(encoding="utf-8")
    violations = check_shaping_single(text)
    assert violations == [], f"shaping single: {violations}"


def test_shaping_pre_existing_mentions_positive() -> None:
    # /plan's Phase 0.6 no longer names Shaping, and that is the correction, not a regression
    # (#927): a plan being written puts the card on the live pair `Planning` / `Designing`, and
    # `Shaping` is the stage BEFORE planning starts. What is pinned here is that the boundary still
    # exists and names a live rung, so the section cannot quietly lose its move again.
    plan_text = (ROOT / "plugins/saga/skills/plan/SKILL.md").read_text(encoding="utf-8")
    assert "### 0.6 Submit the card's move to `Planning` / `Designing`" in plan_text
    assert "--op set-field-status" in plan_text
    office_text = (ROOT / "plugins/saga/skills/office-hours/SKILL.md").read_text(encoding="utf-8")
    assert (
        "discovery/shaping" in office_text.lower() or "discovery / shaping" in office_text.lower()
    )
    # Check hits exist — count occurrences
    office_hits = len(re.findall(r"shaping", office_text, re.IGNORECASE))
    assert office_hits >= 3, f"office-hours should have shaping hits, found {office_hits}"
    frame_text = (
        ROOT / "plugins/saga/skills/office-hours/references/frame-diagnostic.md"
    ).read_text(encoding="utf-8")
    assert re.search(r"shaping", frame_text, re.IGNORECASE), "frame-diagnostic missing shaping"


def test_shaping_negative() -> None:
    # No commands declares a shaping command
    commands_dir = ROOT / "plugins/saga/com.infiquetra.claude/commands"
    if commands_dir.exists():
        for path in commands_dir.glob("*.md"):
            assert "shaping" not in path.name.lower(), f"shaping command found: {path}"
            text = path.read_text(encoding="utf-8").lower()
            # No file should declare a shaping command in its frontmatter or heading
            assert "shaping" not in text or "discovery / shaping" in text, (
                f"unexpected shaping in {path}"
            )
    # No Saga surface states an automatic Brainstorm-to-board transition
    for path in list((ROOT / "plugins/saga/references").rglob("*.md")) + list(
        (ROOT / "plugins/saga/skills").rglob("*.md")
    ):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "automatic" in line.lower() and re.search(r"\bShaping\b", line):
                # Allowlist the one legitimate negation sentence in saga-spec
                if "Shaping is an Operations board Status, not a Saga lifecycle phase" in line:
                    continue
                raise AssertionError(
                    f"automatic Brainstorm-to-board transition in {path}: {line.strip()[:120]} — Shaping is an Operations board Status stated once at saga-spec.md §4 (Enum domains); a second authoritative statement would couple Saga's command vocabulary to a board column"
                )
    # No new Shaping mention beyond enumerated set — anchored to board-Status capitalization
    allowed_files = {
        ROOT / "plugins/saga/skills/plan/SKILL.md",
        ROOT / "plugins/saga/skills/office-hours/SKILL.md",
        ROOT / "plugins/saga/skills/office-hours/references/frame-diagnostic.md",
        SAGA_SPEC,
    }
    for path in list((ROOT / "plugins/saga/references").rglob("*.md")) + list(
        (ROOT / "plugins/saga/skills").rglob("*.md")
    ):
        if path in allowed_files:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bShaping\b", text):
            raise AssertionError(
                f"unexpected Shaping mention in {path.relative_to(ROOT)} beyond enumerated set — Shaping is an Operations board Status stated authoritatively once at saga-spec.md §4 (Enum domains); a second authoritative statement would couple Saga's command vocabulary to a board column"
            )
