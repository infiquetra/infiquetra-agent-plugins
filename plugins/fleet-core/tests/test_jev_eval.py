"""Tests for the evaluation harness (plan U6).

Every input is a recorded file.  The offline guarantee is asserted, not assumed:
the harness imports no transport at all, and the acceptance-criterion test runs
against the real seeded benchmark committed beside the research inputs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons/jev_eval.py"
def _load() -> Any:
    spec = importlib.util.spec_from_file_location("jev_eval_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ev = _load()


def _record(identifier: str, choice: str, label: str, confidence: float) -> dict[str, Any]:
    return {
        "id": identifier,
        "answer": {"type": "choice", "choice": choice, "confidence": confidence},
        "label": label,
        "resolved_model": "jev-1.13.0",
    }


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Scoring and bands
# --------------------------------------------------------------------------- #


def test_full_agreement_reports_every_band() -> None:
    records = [_record(f"r{i}", "haiku", "haiku", 0.9) for i in range(10)]
    report = ev.evaluate(records)
    assert report.scored == 10
    assert report.agreed == 10
    high = next(band for band in report.bands if band.band.startswith("high"))
    assert high.scored == 10 and high.agreed == 10


def test_bands_are_computed_not_reported_as_one_number() -> None:
    records = [_record(f"h{i}", "haiku", "haiku", 0.95) for i in range(5)]
    records += [_record(f"l{i}", "haiku", "opus", 0.2) for i in range(5)]
    report = ev.evaluate(records)
    assert report.agreed == 5
    low = next(band for band in report.bands if band.band.startswith("low"))
    high = next(band for band in report.bands if band.band.startswith("high"))
    assert high.agreement == 1.0
    assert low.agreement == 0.0


def test_a_yes_no_answer_is_banded_by_distance_from_a_half() -> None:
    confident = [{"id": "a", "answer": {"type": "noul", "noul": 0.97}, "label": 0.97}]
    report = ev.evaluate(confident)
    high = next(band for band in report.bands if band.band.startswith("high"))
    assert high.scored == 1

    uncertain = [{"id": "b", "answer": {"type": "noul", "noul": 0.52}, "label": 0.52}]
    report = ev.evaluate(uncertain)
    low = next(band for band in report.bands if band.band.startswith("low"))
    assert low.scored == 1


def test_custom_bands_are_honored() -> None:
    records = [_record("a", "haiku", "haiku", 0.7)]
    report = ev.evaluate(records, bands=((0.0, 0.5, "under"), (0.5, 1.1, "over")))
    over = next(band for band in report.bands if band.band == "over")
    assert over.scored == 1


# --------------------------------------------------------------------------- #
# Edge and error paths
# --------------------------------------------------------------------------- #


def test_an_empty_input_reports_zero_rather_than_dividing_by_zero() -> None:
    report = ev.evaluate([])
    assert report.scored == 0
    assert report.agreement is None
    assert "No records were scored" in report.render()


def test_unlabeled_records_are_named_not_silently_dropped() -> None:
    records = [_record("scored", "haiku", "haiku", 0.9), {"id": "bare", "answer": {}}]
    report = ev.evaluate(records)
    assert report.scored == 1
    assert "bare" in report.unlabeled
    assert "Unscored (no label): 1" in report.render()


def test_a_conflicting_label_is_reported_not_resolved() -> None:
    """Reported AND excluded.

    Scoring the first occurrence resolves the conflict by picking one, which is
    exactly what "reported, not resolved" rules out -- and it silently counted
    as agreement.
    """
    records = [
        _record("same", "haiku", "haiku", 0.9),
        _record("same", "haiku", "opus", 0.9),
    ]
    report = ev.evaluate(records)
    assert "same" in report.conflicts
    assert report.scored == 0, "a conflicting identifier must not be scored at all"


def test_a_repeated_identifier_is_scored_once() -> None:
    """A duplicate scored twice inflates both numerator and denominator."""
    records = [_record("dup", "haiku", "haiku", 0.9), _record("dup", "haiku", "haiku", 0.9)]
    report = ev.evaluate(records)
    assert report.scored == 1
    assert report.agreed == 1


def test_a_missing_path_is_named() -> None:
    with pytest.raises(ev.EvalInputError, match="no such"):
        ev.evaluate_path(Path("/nonexistent/evaluation/input"))


def test_a_directory_with_no_recorded_answers_says_so(tmp_path) -> None:
    with pytest.raises(ev.EvalInputError, match="no recorded answers"):
        ev.evaluate_path(tmp_path)


def test_invalid_json_is_named(tmp_path) -> None:
    path = tmp_path / "broken_answers.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ev.EvalInputError, match="not valid JSON"):
        ev.evaluate_path(path)


def test_a_top_level_object_is_refused(tmp_path) -> None:
    path = tmp_path / "wrong_answers.json"
    path.write_text('{"id": "a"}', encoding="utf-8")
    with pytest.raises(ev.EvalInputError, match="list of records"):
        ev.evaluate_path(path)


def test_unreadable_lines_are_counted_and_skipped(tmp_path) -> None:
    path = tmp_path / "verdicts.jsonl"
    path.write_text(
        json.dumps(
            {
                "kind": "verdict",
                "decision_id": "a",
                "answer": {"type": "choice", "choice": "haiku", "confidence": 0.9},
                "label": "haiku",
            }
        )
        + "\n{truncated",
        encoding="utf-8",
    )
    report = ev.evaluate_path(path)
    assert report.scored == 1
    assert report.skipped_lines == 1
    assert "Unreadable lines skipped: 1" in report.render()


# --------------------------------------------------------------------------- #
# Input formats
# --------------------------------------------------------------------------- #


def test_the_verdict_log_is_accepted_as_a_second_input_format(tmp_path) -> None:
    """Joining on decision_id, so a run over real verdicts needs no conversion."""
    path = tmp_path / "verdicts.jsonl"
    lines = [
        json.dumps(
            {
                "kind": "verdict",
                "decision_id": f"d{i}",
                "answer": {"type": "choice", "choice": "haiku", "confidence": 0.9},
                "label": "haiku",
                "resolved_model": "jev-1.13.0",
            }
        )
        for i in range(3)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = ev.evaluate_path(path)
    assert report.scored == 3 and report.agreed == 3


def test_override_lines_are_not_scored_as_verdicts(tmp_path) -> None:
    path = tmp_path / "verdicts.jsonl"
    path.write_text(
        json.dumps({"kind": "override", "verdict_hash": "abc", "chosen": "sonnet"}) + "\n",
        encoding="utf-8",
    )
    report = ev.evaluate_path(path)
    assert report.scored == 0


def test_the_question_key_flag_selects_one_question() -> None:
    records = [
        {
            "id": "a",
            "answer": {
                "model": {"type": "choice", "choice": "haiku", "confidence": 0.9},
                "effort": {"type": "choice", "choice": "max", "confidence": 0.9},
            },
            "label": "haiku",
        }
    ]
    assert ev.evaluate(records, question_key="model").agreed == 1
    assert ev.evaluate(records, question_key="effort").agreed == 0


def test_a_record_names_its_own_scored_question() -> None:
    """So the bare cached-evaluation command works without the caller knowing."""
    records = [
        {
            "id": "a",
            "question_key": "model",
            "answer": {"model": {"type": "choice", "choice": "haiku", "confidence": 0.9}},
            "label": "haiku",
        }
    ]
    assert ev.evaluate(records).agreed == 1
