"""The stale-review path re-enters through the combined-branch gate (issue #144).

Pins that /work §5.3 sends a stale branch back through the Phase 3.3
combined-branch loop and takes the new ``REVIEWED_SHA`` from
``build_loop.py --handoff`` — never by capturing a fresh SHA directly, and
never by any other means (§5.1 forbids a fresh ``git rev-parse`` as the
reviewed revision). The assertions slice the stale-review paragraph, because
"Phase 3.3" already appears in the repairs and cap bullets and a section-wide
check would pass on the broken text.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK_SKILL = ROOT / "plugins" / "saga" / "skills" / "work" / "SKILL.md"

STALE_OPEN = "Independently, a **stale** review"
SLICE_END = "### 5.4"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _stale_slice(text: str) -> str:
    start = text.find(STALE_OPEN)
    assert start >= 0, "the stale-review paragraph is missing from §5.3"
    end = text.find(SLICE_END, start)
    assert end >= 0, "the §5.4 heading is missing; the stale slice has no end"
    return text[start:end]


def test_capturing_a_fresh_is_gone_from_the_work_skill() -> None:
    text = _read(WORK_SKILL)
    assert "capturing a fresh" not in text, (
        "§5.3 must not tell the worker to capture a fresh REVIEWED_SHA"
    )


def test_the_stale_slice_starts_below_the_outcome_bullets() -> None:
    stale = _stale_slice(_read(WORK_SKILL))
    assert "repairs_requested" not in stale, (
        "the stale slice must exclude the outcome bullets, whose Phase 3.3 "
        "mentions would otherwise satisfy the routing assertion on broken text"
    )


def test_the_stale_slice_routes_through_phase_33_and_handoff() -> None:
    stale = _stale_slice(_read(WORK_SKILL))
    for phrase in ("Phase 3.3", "combined-branch", "build_loop.py --handoff"):
        assert phrase in stale, (
            f"the stale-review paragraph must name {phrase} before re-review"
        )
    assert "re-run `/code-review`" in stale, (
        "the stale path still ends in a re-run of /code-review"
    )


def test_the_stale_slice_captures_the_sha_no_other_way() -> None:
    stale = _stale_slice(_read(WORK_SKILL))
    assert "git rev-parse" not in stale, (
        "the stale path takes REVIEWED_SHA from build_loop.py --handoff, "
        "never from a fresh git rev-parse"
    )
    for line in stale.splitlines():
        if re.search(r"REVIEWED_SHA\s*=", line):
            assert "build_loop.py --handoff" in line, (
                f"every REVIEWED_SHA assignment in the stale slice goes through "
                f"build_loop.py --handoff: {line.strip()}"
            )
