"""Tests for this package's Fleet Core bundle loading and coherence (#111 CI).

A bare ``import <name>`` answers with whatever ``sys.modules`` already holds
under that name; in one process that ran another package's tests first it can
be a different module of the same name. These tests pin the bundle loader to
path-scoped loading and pin the bundle itself to carrying every module the
bundled ``staffing`` consult needs.
"""

# ruff: noqa: E402,I001

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


def test_bundled_loads_leave_sys_path_and_short_names_alone() -> None:
    """The loader must not resolve through the shared import state."""
    bundled = str(Path(sdlc_manager.__file__).resolve().parent / "_bundled")
    path_before = list(sys.path)
    cached_before = dict(sys.modules)

    first = sdlc_manager._fleet_commons("jev_log")
    second = sdlc_manager._fleet_commons("jev_log")

    assert list(sys.path) == path_before
    assert bundled not in sys.path
    assert sys.modules.get("jev_log") is cached_before.get("jev_log")
    assert Path(first.__file__).resolve().parent == Path(bundled)
    assert second is first


def test_bundled_staffing_can_run_a_tier_consult() -> None:
    """The bundled staffing copy must consult, not fail open on a missing verb."""
    staffing = sdlc_manager._fleet_commons("staffing")
    calls: list = []

    def fake_ask(state: Any, questions: Any, **kwargs: Any) -> Any:
        calls.append(True)
        answers = {
            key: {
                "type": "choice",
                "choice": "above",
                "confidence": 0.9,
                "probabilities": {"below": 0.05, "same": 0.05, "above": 0.9},
            }
            for key in questions
        }
        return SimpleNamespace(
            status="ok", answers=answers, model="jev-1.13.0", note="", truncation=()
        )

    result = staffing.consult_tier_suggestions(
        {
            "worker": staffing.judgment_unit(
                {"description": "do the thing", "work_shape": "implementation"},
                {"model": "sonnet", "effort": "medium"},
            )
        },
        ask=fake_ask,
        getenv=lambda _name: None,
    )

    judgment = result["judgments"]["worker"]
    assert calls, result
    assert judgment["band"] != "not-consulted", judgment
