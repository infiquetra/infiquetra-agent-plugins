"""Advisory tier suggestions inside the staffing component (issue #1033).

The staffing component consults the ``tier`` judgment verb for each role or unit,
batched into one request per run, and records the suggestion beside the policy
default it never overrides. A suggestion below the verb's confidence floor leaves
the default standing alone; a client failure falls open to the default.

No test here touches the network. Every consult passes an injected fake ``ask``,
or a fake client module, and every verdict log lands in ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "fleet-core" / "scripts"
COMMONS = SCRIPTS / "fleet_commons"
def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tc = _load("typesafe_client_for_staffing_suggest", COMMONS / "typesafe_client.py")
jev_verbs = _load("jev_verbs_for_staffing_suggest", COMMONS / "jev_verbs.py")
jev_log = _load("jev_log_for_staffing_suggest", COMMONS / "jev_log.py")
staffing = _load("staffing_suggest_under_test", COMMONS / "staffing.py")

FLOOR = float(jev_verbs.VERBS["tier"].confidence_floor)

DEFAULT = {"model": "sonnet", "effort": "medium"}


def _unit(key: str = "judgment", default: dict[str, str] | None = None) -> dict[str, Any]:
    unit: dict[str, Any] = staffing.suggestion_unit(
        f"work shape '{key}' (staffing default sonnet/medium)",
        default if default is not None else dict(DEFAULT),
    )
    return unit


def _choice(value: str, confidence: float) -> dict[str, Any]:
    return {"type": "choice", "choice": value, "confidence": confidence}


def _tier_answers(
    key: str, model: str, model_conf: float, effort: str, effort_conf: float
) -> dict[str, Any]:
    return {
        f"{key}__model": _choice(model, model_conf),
        f"{key}__effort": _choice(effort, effort_conf),
    }


def _ok(answers: dict[str, Any], model: str = "jev-1.13.0") -> Any:
    return tc.AskResult(status=tc.STATUS_OK, answers=answers, model=model, transport="fake")


def _fake_ask(
    result: Any = None,
    calls: list[dict[str, Any]] | None = None,
    error: BaseException | None = None,
) -> Any:
    def _ask(state: Any, questions: Any, **options: Any) -> Any:
        if calls is not None:
            calls.append({"state": state, "questions": questions, "options": options})
        if error is not None:
            raise error
        return result

    return _ask


def _consult(
    units: dict[str, Any],
    ask: Any,
    tmp_path: Path,
    **overrides: Any,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "ask": ask,
        "client": tc,
        "verbs": jev_verbs,
        "log_module": jev_log,
        "log_dir": tmp_path,
    }
    kwargs.update(overrides)
    outcome: dict[str, Any] = staffing.consult_tier_suggestions(units, **kwargs)
    return outcome


def _verdicts(tmp_path: Path) -> list[dict[str, Any]]:
    records, skipped = jev_log.read_verdicts(tmp_path)
    assert skipped == 0
    return [record for record in records if record.get("kind") == "verdict"]


# ---------------------------------------------------------------------------
# The three card cases: above the floor, below it, and a client failure.
# ---------------------------------------------------------------------------


def test_above_floor_suggestion_is_shaped_and_logged(tmp_path: Path) -> None:
    answers = _tier_answers("judgment", "opus", 0.90, "high", 0.85)
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path)

    assert outcome["status"] == "ok"
    assert outcome["resolved_model"] == "jev-1.13.0"
    entry = outcome["suggestions"]["judgment"]
    assert entry["suggested"] == {"model": "opus", "effort": "high"}
    assert entry["confidence"] == pytest.approx(0.85)
    assert entry["model_confidence"] == pytest.approx(0.90)
    assert entry["effort_confidence"] == pytest.approx(0.85)
    assert entry["low_confidence"] is False
    assert entry["usable"] is True
    assert entry["chosen"] == DEFAULT
    assert "advisory only" in entry["reason"]

    records = _verdicts(tmp_path)
    assert len(records) == 1
    (record,) = records
    assert record["decision_id"] == "staffing/tier-suggest:judgment"
    assert record["answer"]["choice"] == "opus/high"
    assert record["confidence"] == pytest.approx(0.85)
    assert record["threshold"] == pytest.approx(FLOOR)
    assert record["label"] == "sonnet/medium"
    assert record["resolved_model"] == "jev-1.13.0"
    assert "state" not in record


def test_agreeing_suggestion_says_so(tmp_path: Path) -> None:
    answers = _tier_answers("judgment", "sonnet", 0.90, "medium", 0.85)
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path)

    entry = outcome["suggestions"]["judgment"]
    assert entry["low_confidence"] is False
    assert entry["usable"] is True
    assert "agrees with the default" in entry["reason"]


def test_below_floor_default_stands_and_the_log_says_why(tmp_path: Path) -> None:
    answers = _tier_answers("judgment", "opus", 0.45, "high", 0.40)
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path)

    entry = outcome["suggestions"]["judgment"]
    assert entry["suggested"] == {"model": "opus", "effort": "high"}
    assert entry["low_confidence"] is True
    assert entry["usable"] is True
    assert entry["chosen"] == DEFAULT
    assert "below the floor" in entry["reason"]

    records = _verdicts(tmp_path)
    assert len(records) == 1
    (record,) = records
    assert record["confidence"] == pytest.approx(0.40)
    assert record["threshold"] == pytest.approx(FLOOR)
    assert record["confidence"] < record["threshold"]


def test_client_failure_falls_open_with_a_logged_reason(tmp_path: Path) -> None:
    failed = tc.AskResult(status=tc.STATUS_ERROR, note="TYPESAFE_API_KEY is not set")
    outcome = _consult({"judgment": _unit()}, _fake_ask(failed), tmp_path)

    assert outcome["status"] == "error"
    assert "TYPESAFE_API_KEY" in outcome["note"]
    entry = outcome["suggestions"]["judgment"]
    assert entry["suggested"] is None
    assert entry["usable"] is False
    assert entry["chosen"] == DEFAULT
    assert "TYPESAFE_API_KEY" in entry["reason"]
    # A failed request has no verdict to log -- the same rule jev_widen keeps --
    # so the reason travels in the result the caller prints instead.
    assert _verdicts(tmp_path) == []


def test_exception_from_ask_falls_open(tmp_path: Path) -> None:
    outcome = _consult(
        {"judgment": _unit()}, _fake_ask(error=RuntimeError("the vendor blew up")), tmp_path
    )

    assert outcome["status"] == "error"
    assert "RuntimeError" in outcome["note"]
    assert outcome["suggestions"]["judgment"]["suggested"] is None
    assert _verdicts(tmp_path) == []


def test_missing_answer_key_falls_back_to_the_default(tmp_path: Path) -> None:
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok({})), tmp_path)

    entry = outcome["suggestions"]["judgment"]
    assert entry["suggested"] is None
    assert entry["usable"] is False
    assert "no suggestion" in entry["reason"]
    assert _verdicts(tmp_path) == []


# ---------------------------------------------------------------------------
# The suggestion is validated like any tier before it may stand beside one.
# ---------------------------------------------------------------------------


def test_unrunnable_pair_is_not_carried_but_is_logged(tmp_path: Path) -> None:
    answers = _tier_answers("judgment", "haiku", 0.90, "xhigh", 0.88)
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path)

    entry = outcome["suggestions"]["judgment"]
    assert entry["usable"] is False
    assert "ceiling" in (entry["problem"] or "")
    assert "the default stands" in entry["reason"]
    records = _verdicts(tmp_path)
    assert len(records) == 1
    assert records[0]["answer"]["choice"] == "haiku/xhigh"


def test_max_effort_reads_as_the_palette_top(tmp_path: Path) -> None:
    answers = _tier_answers("judgment", "opus", 0.90, "max", 0.88)
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path)

    entry = outcome["suggestions"]["judgment"]
    assert entry["suggested"] == {"model": "opus", "effort": "xhigh"}
    assert entry["usable"] is True
    records = _verdicts(tmp_path)
    assert records[0]["answer"]["choice"] == "opus/xhigh"


def test_off_palette_model_is_not_carried(tmp_path: Path) -> None:
    answers = _tier_answers("judgment", "gpt4", 0.90, "high", 0.88)
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path)

    entry = outcome["suggestions"]["judgment"]
    assert entry["usable"] is False
    assert "gpt4" in (entry["problem"] or "")


def test_answer_without_a_value_is_not_carried(tmp_path: Path) -> None:
    answers = {"judgment__model": {"type": "noul", "noul": 0.9}, "judgment__effort": None}
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path)

    entry = outcome["suggestions"]["judgment"]
    assert entry["suggested"] is None
    assert entry["usable"] is False


# ---------------------------------------------------------------------------
# Floor, batching, and the verb registry as the single source.
# ---------------------------------------------------------------------------


def test_floor_defaults_to_the_tier_verb_registry(tmp_path: Path) -> None:
    answers = _tier_answers("judgment", "opus", 0.90, "high", 0.85)
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path)

    assert outcome["floor"] == pytest.approx(FLOOR)
    assert outcome["suggestions"]["judgment"]["floor"] == pytest.approx(FLOOR)


def test_explicit_floor_overrides_the_registry(tmp_path: Path) -> None:
    answers = _tier_answers("judgment", "opus", 0.90, "high", 0.85)
    outcome = _consult({"judgment": _unit()}, _fake_ask(_ok(answers)), tmp_path, floor=0.95)

    assert outcome["suggestions"]["judgment"]["low_confidence"] is True


def test_batch_consults_once_for_every_role(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    units = {
        "planner": _unit("planner"),
        "worker": _unit("worker"),
        "lens-reviewer": _unit("lens-reviewer"),
    }
    answers = (
        _tier_answers("planner", "opus", 0.9, "high", 0.85)
        | _tier_answers("worker", "sonnet", 0.9, "medium", 0.85)
        | _tier_answers("lens-reviewer", "opus", 0.4, "high", 0.35)
    )
    outcome = _consult(units, _fake_ask(_ok(answers), calls=calls), tmp_path)

    assert len(calls) == 1
    assert set(calls[0]["questions"]) == {
        "planner__model",
        "planner__effort",
        "worker__model",
        "worker__effort",
        "lens-reviewer__model",
        "lens-reviewer__effort",
    }
    assert set(calls[0]["state"]["tasks"]) == set(units)
    assert set(outcome["suggestions"]) == set(units)
    records = _verdicts(tmp_path)
    assert {record["decision_id"] for record in records} == {
        "staffing/tier-suggest:planner",
        "staffing/tier-suggest:worker",
        "staffing/tier-suggest:lens-reviewer",
    }


def test_questions_reuse_the_tier_verb_criteria(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    answers = _tier_answers("judgment", "opus", 0.9, "high", 0.85)
    _consult({"judgment": _unit()}, _fake_ask(_ok(answers), calls=calls), tmp_path)

    verb = jev_verbs.VERBS["tier"].question_set()
    asked = calls[0]["questions"]
    assert asked["judgment__model"]["criteria"] == verb["model"]["criteria"]
    assert asked["judgment__effort"]["criteria"] == verb["effort"]["criteria"]
    assert asked["judgment__model"]["instructions"] != verb["model"]["instructions"]
    assert "judgment" in json.dumps(asked["judgment__model"]["instructions"])


def test_empty_units_make_no_request(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    outcome = _consult({}, _fake_ask(_ok({}), calls=calls), tmp_path)

    assert outcome["status"] == "ok"
    assert outcome["suggestions"] == {}
    assert calls == []


def test_operator_set_tier_difference_is_logged_as_override(tmp_path: Path) -> None:
    unit = staffing.suggestion_unit("role 'worker'", dict(DEFAULT), operator_set=True)
    answers = _tier_answers("worker", "opus", 0.9, "high", 0.85)
    _consult({"worker": unit}, _fake_ask(_ok(answers)), tmp_path)

    records, _ = jev_log.read_verdicts(tmp_path)
    kinds = [record.get("kind") for record in records]
    assert kinds.count("verdict") == 1
    assert kinds.count("override") == 1
    override = next(record for record in records if record.get("kind") == "override")
    assert override["chosen"] == "sonnet/medium"
    assert "opus/high" in override["rationale"]


def test_agreeing_operator_tier_logs_no_override(tmp_path: Path) -> None:
    unit = staffing.suggestion_unit("role 'worker'", dict(DEFAULT), operator_set=True)
    answers = _tier_answers("worker", "sonnet", 0.9, "medium", 0.85)
    _consult({"worker": unit}, _fake_ask(_ok(answers)), tmp_path)

    records, _ = jev_log.read_verdicts(tmp_path)
    assert [record.get("kind") for record in records] == ["verdict"]


def test_minimal_fake_client_is_enough(tmp_path: Path) -> None:
    """Only the answer helpers matter when ``ask`` is injected: a fake client without
    ``STATUS_OK`` still shapes an ok result rather than raising."""
    minimal = SimpleNamespace(answer_value=tc.answer_value, answer_confidence=tc.answer_confidence)
    answers = _tier_answers("judgment", "opus", 0.90, "high", 0.85)
    outcome = staffing.consult_tier_suggestions(
        {"judgment": _unit()},
        ask=_fake_ask(_ok(answers)),
        client=minimal,
        verbs=jev_verbs,
        log_module=jev_log,
        log_dir=tmp_path,
    )

    assert outcome["status"] == "ok"
    assert outcome["suggestions"]["judgment"]["suggested"] == {"model": "opus", "effort": "high"}


def test_unloadable_client_falls_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raises(name: str) -> Any:
        raise RuntimeError(f"no module {name}")

    monkeypatch.setattr(staffing, "_load_commons", _raises)
    outcome = staffing.consult_tier_suggestions({"judgment": _unit()}, log_dir=tmp_path)

    assert outcome["status"] == "error"
    assert "could not be loaded" in outcome["note"]
    assert outcome["suggestions"]["judgment"]["suggested"] is None


# ---------------------------------------------------------------------------
# The command line: the default, the suggestion, its confidence, what applies.
# ---------------------------------------------------------------------------


def _cli_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: Any = None,
    calls: list[dict[str, Any]] | None = None,
    verdicts: list[dict[str, Any]] | None = None,
    overrides: list[dict[str, Any]] | None = None,
) -> None:
    """Point the CLI's lazy loader at fakes: a canned client, the real verbs, a
    capturing log. The command under test makes no request and writes no file."""

    def _verdict(**record: Any) -> dict[str, Any]:
        stored = dict(record, verdict_hash="hash-for-test")
        if verdicts is not None:
            verdicts.append(stored)
        return stored

    def _override(**record: Any) -> dict[str, Any]:
        if overrides is not None:
            overrides.append(dict(record))
        return dict(record)

    def _load(name: str) -> Any:
        if name == "typesafe_client":
            return SimpleNamespace(
                ask=_fake_ask(result, calls),
                answer_value=tc.answer_value,
                answer_confidence=tc.answer_confidence,
                STATUS_OK=tc.STATUS_OK,
            )
        if name == "jev_verbs":
            return jev_verbs
        if name == "jev_log":
            return SimpleNamespace(record_verdict=_verdict, record_override=_override)
        raise AssertionError(f"unexpected commons load: {name}")

    monkeypatch.setattr(staffing, "_load_commons", _load)


def test_cli_suggest_prints_default_suggestion_confidence_and_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    answers = _tier_answers("mechanical", "opus", 0.90, "high", 0.85)
    _cli_modules(monkeypatch, result=_ok(answers))

    assert staffing.main(["resolve", "--shape", "mechanical", "--suggest"]) == 0
    out = capsys.readouterr().out
    assert "default: sonnet/medium (policy)" in out
    assert "suggestion: opus/high" in out
    assert "confidence 0.85" in out
    assert f"floor {FLOOR:.2f}" in out
    assert "applies: sonnet/medium" in out


def test_cli_suggest_never_changes_the_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The JSON record carries the suggestion beside an unchanged tier."""
    monkeypatch.chdir(tmp_path)
    answers = _tier_answers("mechanical", "opus", 0.90, "high", 0.85)
    _cli_modules(monkeypatch, result=_ok(answers))

    assert staffing.main(["resolve", "--shape", "mechanical", "--suggest", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tier"] == "sonnet/medium"
    assert payload["model"] == "sonnet"
    assert payload["effort"] == "medium"
    assert payload["source"] == "policy"
    assert payload["suggestion"] == {"model": "opus", "effort": "high"}
    assert payload["consult"]["confidence"] == pytest.approx(0.85)
    assert payload["consult"]["status"] == "ok"


def test_cli_suggest_below_floor_leaves_the_decision_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    answers = _tier_answers("mechanical", "opus", 0.45, "high", 0.40)
    _cli_modules(monkeypatch, result=_ok(answers))

    assert staffing.main(["resolve", "--shape", "mechanical", "--suggest", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tier"] == "sonnet/medium"
    assert "suggestion" not in payload
    assert "below the floor" in payload["consult"]["reason"]
    assert payload["consult"]["confidence"] == pytest.approx(0.40)


def test_cli_suggest_role_names_the_vendor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A role's consult lines carry its vendor, like the plain short form."""
    monkeypatch.chdir(tmp_path)
    answers = _tier_answers("planner", "opus", 0.90, "high", 0.85)
    _cli_modules(monkeypatch, result=_ok(answers))

    assert staffing.main(["resolve", "--role", "planner", "--suggest"]) == 0
    out = capsys.readouterr().out
    assert "default: claude opus/high (policy)" in out
    assert "suggestion: opus/high" in out
    assert "applies: claude opus/high" in out


def test_cli_suggest_without_key_falls_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The acceptance command with no credential: the default stands, exit zero,
    and the reason names the missing key. No network is attempted."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    assert staffing.main(["resolve", "--shape", "judgment", "--suggest"]) == 0
    out = capsys.readouterr().out
    assert "default: opus/high (policy)" in out
    assert "suggestion: none" in out
    assert "TYPESAFE_API_KEY" in out
    assert "applies: opus/high" in out


def test_cli_suggest_value_still_records_a_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--suggest MODEL/EFFORT`` keeps its issue-1021 meaning beside the bare flag."""
    monkeypatch.chdir(tmp_path)

    assert staffing.main(["resolve", "--shape", "judgment", "--suggest", "opus/high"]) == 0
    assert capsys.readouterr().out.strip() == "opus/high"

    assert (
        staffing.main(["resolve", "--shape", "judgment", "--suggest", "opus/high", "--json"]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["suggestion"] == {"model": "opus", "effort": "high"}
