"""Tests for the widen-only union primitive.

No test here touches the network.  ``widen()`` takes its ``ask`` callable as a
parameter, so every test hands in a function that returns a recorded answer map,
and one test asserts that the fake was in fact the callee.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMONS = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons"


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, COMMONS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tc = _load("typesafe_client_for_widen", "typesafe_client.py")
jev_log = _load("jev_log_for_widen", "jev_log.py")
widen_module = _load("jev_widen_under_test", "jev_widen.py")

STATE = {"issue": "rotate the deploy credential and drop the old table"}

FLOORS = {
    "has_security": True,
    "has_api": False,
    "has_infra": False,
    "credentials": False,
    "destructive": False,
}


def _answers(**probabilities: float) -> dict[str, Any]:
    return {key: {"type": "noul", "noul": value} for key, value in probabilities.items()}


def _ok(answers: dict[str, Any], model: str = "jev-1.13.0") -> Any:
    return tc.AskResult(status=tc.STATUS_OK, answers=answers, model=model, transport="fake")


def _fake_ask(result: Any, calls: list | None = None):
    def _ask(state, questions, **options):  # noqa: ANN001, ANN003
        if calls is not None:
            calls.append({"state": state, "questions": questions, "options": options})
        return result

    return _ask


def _widen(ask, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "decision_prefix": "issue-flags",
        "ask": ask,
        "log": False,
    }
    kwargs.update(overrides)
    return widen_module.widen(STATE, "issue-flags", FLOORS, **kwargs)


def test_a_regex_floor_survives_a_confident_no() -> None:
    """The one property the whole module exists for: a set flag is never unset."""
    result = _widen(_fake_ask(_ok(_answers(has_security=0.01))))

    judgment = result.judgments["has_security"]
    assert judgment.union is True
    assert judgment.regex is True
    assert judgment.probability == pytest.approx(0.01)
    assert judgment.source == widen_module.SOURCE_REGEX


def test_the_model_can_raise_a_flag_the_regex_missed() -> None:
    result = _widen(_fake_ask(_ok(_answers(credentials=0.93))))

    judgment = result.judgments["credentials"]
    assert judgment.union is True
    assert judgment.regex is False
    assert judgment.source == widen_module.SOURCE_MODEL


def test_a_probability_below_the_threshold_leaves_the_flag_alone() -> None:
    result = _widen(_fake_ask(_ok(_answers(has_api=0.69))), threshold=0.70)

    judgment = result.judgments["has_api"]
    assert judgment.union is False
    assert judgment.source == widen_module.SOURCE_NONE


def test_a_probability_exactly_at_the_threshold_is_included() -> None:
    result = _widen(_fake_ask(_ok(_answers(has_api=0.70))), threshold=0.70)

    assert result.judgments["has_api"].union is True


def test_the_verb_supplies_the_threshold_when_the_caller_does_not() -> None:
    result = _widen(_fake_ask(_ok(_answers())))

    assert result.threshold == pytest.approx(0.70)


def test_a_client_error_returns_the_floors_and_names_the_reason() -> None:
    failed = tc.AskResult(status=tc.STATUS_ERROR, note="TYPESAFE_API_KEY is not set")
    result = _widen(_fake_ask(failed))

    assert result.unions() == dict(FLOORS)
    assert result.note == "TYPESAFE_API_KEY is not set"
    assert result.asked is False
    assert all(judgment.probability is None for judgment in result.judgments.values())


def test_a_timeout_returns_the_floors() -> None:
    timed_out = tc.AskResult(status=tc.STATUS_TIMEOUT, note="")
    result = _widen(_fake_ask(timed_out))

    assert result.unions() == dict(FLOORS)
    assert "timeout" in result.note


def test_an_exception_from_the_client_returns_the_floors() -> None:
    def _raises(state, questions, **options):  # noqa: ANN001, ANN003
        raise RuntimeError("the vendor blew up")

    result = _widen(_raises)

    assert result.unions() == dict(FLOORS)
    assert "RuntimeError" in result.note


def test_a_missing_answer_key_falls_back_to_its_floor_and_is_named() -> None:
    result = _widen(_fake_ask(_ok(_answers(has_api=0.99))))

    assert result.judgments["credentials"].union is False
    assert result.judgments["credentials"].probability is None
    assert "credentials" in result.note


def test_a_non_numeric_probability_is_ignored() -> None:
    answers = {"has_api": {"type": "noul", "noul": "yes"}}
    result = _widen(_fake_ask(_ok(answers)))

    assert result.judgments["has_api"].probability is None
    assert result.judgments["has_api"].union is False


def test_an_answer_of_another_type_is_ignored() -> None:
    answers = {"has_api": {"type": "choice", "choice": "yes", "confidence": 0.99}}
    result = _widen(_fake_ask(_ok(answers)))

    assert result.judgments["has_api"].probability is None
    assert result.judgments["has_api"].union is False


def test_the_injected_ask_is_the_only_call_path() -> None:
    calls: list = []
    _widen(_fake_ask(_ok(_answers(has_api=0.9)), calls=calls))

    assert len(calls) == 1
    assert calls[0]["state"] == STATE
    assert set(calls[0]["questions"]) == set(widen_module.jev_verbs.VERBS["issue-flags"].questions)


def test_transport_options_are_passed_through_only_when_given() -> None:
    calls: list = []
    _widen(_fake_ask(_ok(_answers()), calls=calls), timeout=2.0, max_attempts=1)

    assert calls[0]["options"] == {"timeout": 2.0, "max_attempts": 1}


def test_an_unknown_verb_is_refused() -> None:
    with pytest.raises(ValueError, match="no such verb"):
        widen_module.widen(STATE, "not-a-verb", FLOORS, decision_prefix="x", ask=_fake_ask(None))


def test_every_answered_question_writes_a_verdict(tmp_path: Path) -> None:
    answers = _answers(has_security=0.02, credentials=0.93)
    widen_module.widen(
        STATE,
        "issue-flags",
        FLOORS,
        decision_prefix="issue-flags",
        ask=_fake_ask(_ok(answers)),
        log=True,
        log_dir=tmp_path,
    )

    records, skipped = jev_log.read_verdicts(tmp_path)
    assert skipped == 0
    assert {record["decision_id"] for record in records} == {
        "issue-flags:has_security",
        "issue-flags:credentials",
    }
    for record in records:
        assert record["resolved_model"] == "jev-1.13.0"
        assert record["threshold"] == pytest.approx(0.70)
        assert "state" not in record


def test_a_failed_request_writes_no_verdict(tmp_path: Path) -> None:
    failed = tc.AskResult(status=tc.STATUS_ERROR, note="no key")
    widen_module.widen(
        STATE,
        "issue-flags",
        FLOORS,
        decision_prefix="issue-flags",
        ask=_fake_ask(failed),
        log=True,
        log_dir=tmp_path,
    )

    records, _ = jev_log.read_verdicts(tmp_path)
    assert records == []
