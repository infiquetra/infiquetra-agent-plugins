"""Assessment-surface diagnostics and fail-closed assess_source (review 2026-09-13).

Covers the cycle-2 review repairs against the shared Saga readiness owner:
  - finding #10: every non-routable assessment diagnostic is path-free — none
    of the remaining shapes (blank, carrier, unterminated, out-of-root,
    unreadable, unrecognized) embed the display path or an author-declared
    value, so a substring-based route check can never see a live `/plan` or
    `/work` command in them;
  - finding #11: an in-root declaration-class path with no file behind it
    returns the bounded ``unknown:undeclared`` sentinel instead of asserting.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
HANDOFF_PATH = ROOT / "plugins/saga/scripts/handoff_envelope.py"


def _load() -> ModuleType:
    if str(HANDOFF_PATH.parent) not in sys.path:
        sys.path.insert(0, str(HANDOFF_PATH.parent))
    spec = importlib.util.spec_from_file_location("handoff_envelope_diagnostics", HANDOFF_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HE: ModuleType = _load()


def _assessment(source: str, root: Path) -> object:
    return HE.assess_source(source, root)


def _assert_path_free(saga: object) -> str:
    """A non-routable assessment's next_action never carries a route substring."""
    assert "/plan" not in str(saga.next_action)  # type: ignore[attr-defined]
    assert "/work" not in str(saga.next_action)  # type: ignore[attr-defined]
    assert "/plan" not in str(saga.diagnostic)  # type: ignore[attr-defined]
    assert "/work" not in str(saga.diagnostic)  # type: ignore[attr-defined]
    return str(saga.next_action)  # type: ignore[attr-defined]


def test_blank_maturity_diagnostic_is_path_free(tmp_path: Path) -> None:
    """#10: a declared-but-empty maturity under docs/plans/ routes nothing."""
    path = tmp_path / "docs" / "plans" / "blank.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\ntitle: blank\ntopic: x\nmaturity:\n---\n\nBody.\n", encoding="utf-8")

    saga = _assessment("docs/plans/blank.md", tmp_path)

    assert saga.maturity == ""  # type: ignore[attr-defined]
    assert saga.routable is False  # type: ignore[attr-defined]
    next_action = _assert_path_free(saga)
    assert next_action.startswith("Blank maturity")


def test_carrier_maturity_diagnostic_is_path_free_and_value_free(tmp_path: Path) -> None:
    """#10: a carrier declared outside delimiters omits both path and raw value."""
    path = tmp_path / "docs" / "plans" / "carrier.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Carrier\n\nmaturity: plan-ready\n", encoding="utf-8")

    saga = _assessment("docs/plans/carrier.md", tmp_path)

    assert str(saga.maturity).startswith("unknown:carrier:")  # type: ignore[attr-defined]
    assert saga.routable is False  # type: ignore[attr-defined]
    next_action = _assert_path_free(saga)
    assert next_action.startswith("Frontmatter carrier")
    assert "plan-ready" not in next_action


def test_unterminated_frontmatter_diagnostic_is_path_free(tmp_path: Path) -> None:
    """#10: an unclosed frontmatter block omits the display path."""
    path = tmp_path / "docs" / "plans" / "unterminated.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nmaturity: plan-ready\n\nBody.\n", encoding="utf-8")

    saga = _assessment("docs/plans/unterminated.md", tmp_path)

    assert str(saga.maturity).startswith("unknown:unterminated:")  # type: ignore[attr-defined]
    assert saga.routable is False  # type: ignore[attr-defined]
    next_action = _assert_path_free(saga)
    assert next_action.startswith("Unterminated frontmatter block")


def test_out_of_root_refusal_diagnostic_is_path_free(tmp_path: Path) -> None:
    """#10: a refused docs/plans-published path embeds no route substring."""
    outside_root = tmp_path.parent / f"{tmp_path.name}-outside-diag"
    outside = outside_root / "docs" / "plans" / "x.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("OUTSIDE\n", encoding="utf-8")

    saga = _assessment(str(outside), tmp_path)

    assert saga.refused is True  # type: ignore[attr-defined]
    assert saga.routable is False  # type: ignore[attr-defined]
    next_action = _assert_path_free(saga)
    assert next_action.startswith("Source outside the declared root")


def test_unrecognized_declared_value_diagnostic_is_path_free_and_value_free(
    tmp_path: Path,
) -> None:
    """#10: an unrecognized author-declared value is named neither in the prose."""
    path = tmp_path / "docs" / "plans" / "junk-declared.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntitle: junk\ntopic: x\nmaturity: see /plan for routing\n---\n\nBody.\n",
        encoding="utf-8",
    )

    saga = _assessment("docs/plans/junk-declared.md", tmp_path)

    assert str(saga.maturity).startswith("unknown:unrecognized:")  # type: ignore[attr-defined]
    assert saga.routable is False  # type: ignore[attr-defined]
    next_action = _assert_path_free(saga)
    assert next_action.startswith("Unrecognized maturity value")
    assert "see /plan" not in next_action


def test_unreadable_file_diagnostic_is_path_free(tmp_path: Path) -> None:
    """#10: a file that decodes to no readable text is a path-free unreadable."""
    path = tmp_path / "docs" / "plans" / "unreadable.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Invalid UTF-8 with no UTF-16 recovery pattern: _read_window fails on it.
    path.write_bytes(b"\x80\x81\x82\x83\x84\x85\x86\x87" * 4)

    saga = _assessment("docs/plans/unreadable.md", tmp_path)

    assert saga.maturity == "unknown:unreadable"  # type: ignore[attr-defined]
    assert saga.routable is False  # type: ignore[attr-defined]
    next_action = _assert_path_free(saga)
    assert next_action.startswith("Unreadable frontmatter")


def test_missing_draft_class_path_fails_closed_with_undeclared_sentinel(
    tmp_path: Path,
) -> None:
    """#11: a nonexistent in-root draft path returns the sentinel, never asserts."""
    saga = _assessment("docs/sdlc-issue-drafts/never-written.md", tmp_path)

    assert saga.maturity == "unknown:undeclared:docs/sdlc-issue-drafts/never-written.md"  # type: ignore[attr-defined] # noqa: E501
    assert saga.refused is False  # type: ignore[attr-defined]
    assert saga.routable is False  # type: ignore[attr-defined]
    assert "draft" in str(saga.diagnostic).lower()  # type: ignore[attr-defined]


def test_missing_state_class_path_returns_undeclared_sentinel(tmp_path: Path) -> None:
    """#11: the same fail-closed sentinel for a missing Saga state file."""
    saga = _assessment(".claude/saga/state.json", tmp_path)

    assert saga.maturity == "unknown:undeclared:.claude/saga/state.json"  # type: ignore[attr-defined]
    assert saga.refused is False  # type: ignore[attr-defined]
    assert "state" in str(saga.diagnostic).lower()  # type: ignore[attr-defined]
