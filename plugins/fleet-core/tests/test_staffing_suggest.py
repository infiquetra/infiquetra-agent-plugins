"""The tier judgment inside the staffing component (issues 1033 and #96).

The staffing component asks the ``tier`` judgment verb, batched into one request, whether each
unit needs a weaker, the same, or a stronger tier than its default. A raise at the verb's
automatic floor applies one step, effort first, never to fable or past the palette; a raise below
it waits for the operator; a lower tier is never applied; below the confidence floor an answer is
logged, not shown. The off switch makes no request, and a client failure falls open.

No test here touches the network. Every consult passes an injected fake ``ask``, or a fake client
module, and every verdict log lands in ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import re
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

VERB = jev_verbs.VERBS["tier"]
FLOOR = float(VERB.confidence_floor)
AUTO = float(VERB.auto_floor)

DEFAULT = {"model": "opus", "effort": "medium"}


@pytest.fixture(autouse=True)
def _no_ambient_switch_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator shell's switch or key must not change what these tests observe or reach."""
    monkeypatch.delenv(staffing.TIERING_ENV, raising=False)
    monkeypatch.delenv(tc.KEY_ENV, raising=False)


def _unit(
    description: str = "the builder", default: dict[str, str] | None = None, **flags: Any
) -> dict[str, Any]:
    return staffing.judgment_unit(
        {"description": description, "work_shape": "implementation"},
        default if default is not None else dict(DEFAULT),
        **flags,
    )


def _direction(key: str, direction: str, confidence: float) -> dict[str, Any]:
    return {
        f"{key}__direction": {
            "type": "choice",
            "choice": direction,
            "confidence": confidence,
            "probabilities": {direction: confidence},
        }
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


def _consult(units: dict[str, Any], ask: Any, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "ask": ask,
        "client": tc,
        "verbs": jev_verbs,
        "log_module": jev_log,
        "getenv": lambda _name: None,
    }
    kwargs.update(overrides)
    outcome: dict[str, Any] = staffing.consult_tier_suggestions(units, **kwargs)
    return outcome


def _judge(direction: str, confidence: float, **unit_flags: Any) -> dict[str, Any]:
    answers = _direction("worker", direction, confidence)
    outcome = _consult({"worker": _unit(**unit_flags)}, _fake_ask(_ok(answers)))
    assert outcome["status"] == "ok"
    block: dict[str, Any] = outcome["judgments"]["worker"]
    return block


def _verdicts(tmp_path: Path) -> list[dict[str, Any]]:
    records, skipped = jev_log.read_verdicts(tmp_path)
    assert skipped == 0
    return [record for record in records if record.get("kind") == "verdict"]


# ---------------------------------------------------------------------------
# The card's cases: apply a confident raise, hold a less confident one, never lower.
# ---------------------------------------------------------------------------


def test_a_raise_at_085_applies_one_effort_step() -> None:
    block = _judge("above", 0.85)

    assert block["band"] == staffing.BAND_AUTO_RAISE
    assert block["applied"] is True
    assert block["default"] == DEFAULT
    assert block["proposed"] == {"model": "opus", "effort": "high"}
    assert "0.85" in block["reason"]
    assert "one effort step" in block["reason"]
    raised = staffing.jev_raise_from(block)
    assert raised is not None
    assert (raised["model"], raised["effort"], raised["confidence"]) == ("opus", "high", 0.85)
    assert raised["reason"] == block["reason"]
    # The staffing resolver accepts the raise as its jev-raise layer: the resolved tier moves
    # by exactly the one effort step.
    decision = staffing.resolve_shape("implementation", root=Path("/nonexistent"), jev_raise=raised)
    assert (decision.model, decision.effort, decision.source) == ("opus", "high", "jev-raise")


def test_a_raise_at_070_is_pending_confirmation() -> None:
    block = _judge("above", 0.70)

    assert block["band"] == staffing.BAND_CONFIRM_RAISE
    assert block["applied"] is False
    assert block["shown"] is True
    assert block["proposed"] == {"model": "opus", "effort": "high"}
    assert staffing.jev_raise_from(block) is None


def test_a_lower_suggestion_is_never_applied() -> None:
    block = _judge("below", 0.95)

    assert block["band"] == staffing.BAND_ADVISORY_LOWER
    assert block["applied"] is False
    assert block["shown"] is True
    assert block["proposed"] == {"model": "opus", "effort": "low"}
    assert block["default"] == DEFAULT
    assert staffing.jev_raise_from(block) is None
    assert "never applied" in block["reason"]


@pytest.mark.parametrize("confidence", [0.0, 0.6, 0.79, 0.8, 0.95, 1.0])
def test_no_confidence_ever_applies_a_lower_tier(confidence: float) -> None:
    for operator_set in (False, True):
        classified = staffing.classify_judgment(
            "below",
            confidence,
            default=DEFAULT,
            operator_set=operator_set,
            floor=FLOOR,
            auto_floor=AUTO,
        )
        assert classified["applied"] is False


def test_below_06_is_logged_not_shown() -> None:
    block = _judge("above", 0.55)

    assert block["band"] == staffing.BAND_LOG_ONLY
    assert block["shown"] is False
    assert block["applied"] is False
    assert isinstance(block["answer"], dict), "a log-only answer is kept for the verdict log"


def test_an_agreeing_answer_says_so() -> None:
    block = _judge("same", 0.9)

    assert block["band"] == staffing.BAND_AGREES
    assert block["applied"] is False
    assert block["proposed"] == DEFAULT


def test_operator_set_unit_is_never_auto_raised() -> None:
    block = _judge("above", 0.95, operator_set=True)

    assert block["band"] == staffing.BAND_CONFIRM_RAISE
    assert block["applied"] is False
    assert "operator set this tier" in block["reason"]


def test_raise_at_ceiling_is_reported_not_applied() -> None:
    answers = _direction("planner", "above", 0.9)
    unit = _unit(default={"model": "opus", "effort": "xhigh"})
    block = _consult({"planner": unit}, _fake_ask(_ok(answers)))["judgments"]["planner"]

    assert block["band"] == staffing.BAND_RAISE_AT_CEILING
    assert block["applied"] is False
    assert block["proposed"] is None


# ---------------------------------------------------------------------------
# One step, effort first, never to fable or past the palette.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("default", "raised"),
    [
        (("opus", "medium"), ("opus", "high")),
        (("opus", "high"), ("opus", "xhigh")),
        (("opus", "xhigh"), None),
        (("sonnet", "medium"), ("sonnet", "high")),
        (("sonnet", "xhigh"), ("opus", "xhigh")),
        (("haiku", "low"), ("haiku", "medium")),
        (("haiku", "high"), ("haiku", "xhigh")),
        (("haiku", "xhigh"), None),
        (("sonnet", "high"), ("opus", "high")),
        (("fable", "high"), None),
        (("fable", "low"), None),
    ],
)
def test_one_step_raise_table(default: tuple[str, str], raised: tuple[str, str] | None) -> None:
    result = staffing.one_step_raise(*default)
    assert result == (None if raised is None else {"model": raised[0], "effort": raised[1]})


def test_a_raise_never_lands_on_fable_or_max() -> None:
    palette = staffing._tier_palette
    for model in staffing.MODELS:
        for effort in staffing.EFFORTS:
            if not palette.supports_effort(model, effort):
                continue
            raised = staffing.one_step_raise(model, effort)
            if raised is None:
                continue
            assert raised["model"] != staffing.MODELS[0], f"{model}/{effort} raised to fable"
            assert raised["model"] != "fable"
            assert raised["effort"] != "max"
            assert raised["effort"] in staffing.EFFORTS
            same_model = raised["model"] == model
            effort_step = palette.effort_rank(raised["effort"]) - palette.effort_rank(effort)
            model_step = palette.model_rank(model) - palette.model_rank(raised["model"])
            assert (effort_step, model_step) == ((1, 0) if same_model else (0, 1))
            # Every automatic raise is one the resolver's jev-raise layer accepts.
            staffing._validate_jev_raise(
                "judgment",
                raised,
                base={"model": model, "effort": effort},
                registry=staffing.work_shapes(),
            )


@pytest.mark.parametrize(
    ("default", "final", "label"),
    [
        (("opus", "medium"), ("opus", "medium"), "same"),
        (("opus", "medium"), ("opus", "high"), "above"),
        (("opus", "medium"), ("sonnet", "xhigh"), "below"),
        (("sonnet", "high"), ("opus", "low"), "above"),
        (("opus", "high"), ("opus", "medium"), "below"),
    ],
)
def test_tier_direction_labels(
    default: tuple[str, str], final: tuple[str, str], label: str
) -> None:
    assert (
        staffing.tier_direction(
            {"model": default[0], "effort": default[1]}, {"model": final[0], "effort": final[1]}
        )
        == label
    )


# ---------------------------------------------------------------------------
# The off switch, failures, and what is sent.
# ---------------------------------------------------------------------------


def test_off_switch_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def _never(name: str) -> Any:
        raise AssertionError(f"the off switch loaded {name}")

    monkeypatch.setattr(staffing, "_load_commons", _never)
    monkeypatch.setenv(staffing.TIERING_ENV, "off")
    outcome = staffing.consult_tier_suggestions(
        {"worker": _unit()}, ask=_fake_ask(_ok({}), calls=calls)
    )

    assert calls == []
    assert outcome["status"] == "off"
    assert staffing.TIERING_ENV in outcome["note"]
    block = outcome["judgments"]["worker"]
    assert block["band"] == staffing.BAND_NOT_CONSULTED
    assert block["applied"] is False
    assert block["default"] == DEFAULT


@pytest.mark.parametrize(
    ("value", "enabled"),
    [("off", False), ("OFF", False), (" 0 ", False), ("false", False), ("no", False),
     ("", True), ("on", True), (None, True)],
)
def test_off_switch_values(value: str | None, enabled: bool) -> None:
    assert staffing.tiering_enabled(lambda _name: value) is enabled


def test_client_failure_falls_open_with_the_reason() -> None:
    failed = tc.AskResult(status=tc.STATUS_ERROR, note="TYPESAFE_API_KEY is not set")
    outcome = _consult({"worker": _unit()}, _fake_ask(failed))

    assert outcome["status"] == "error"
    assert "TYPESAFE_API_KEY" in outcome["note"]
    block = outcome["judgments"]["worker"]
    assert block["band"] == staffing.BAND_NOT_CONSULTED
    assert block["applied"] is False
    assert block["answer"] is None
    assert "TYPESAFE_API_KEY" in block["reason"]


def test_exception_from_ask_falls_open() -> None:
    outcome = _consult({"worker": _unit()}, _fake_ask(error=RuntimeError("the vendor blew up")))

    assert outcome["status"] == "error"
    assert "RuntimeError" in outcome["note"]
    assert outcome["judgments"]["worker"]["band"] == staffing.BAND_NOT_CONSULTED


def test_missing_answer_key_keeps_the_default() -> None:
    outcome = _consult({"worker": _unit()}, _fake_ask(_ok({})))

    block = outcome["judgments"]["worker"]
    assert block["band"] == staffing.BAND_NOT_CONSULTED
    assert block["applied"] is False
    assert "no judgment" in block["reason"]


def test_an_unknown_choice_is_logged_not_shown() -> None:
    block = _judge("sideways", 0.95)

    assert block["band"] == staffing.BAND_LOG_ONLY
    assert block["applied"] is False


def test_minimal_fake_client_is_enough() -> None:
    minimal = SimpleNamespace(answer_value=tc.answer_value, answer_confidence=tc.answer_confidence)
    answers = _direction("worker", "above", 0.85)
    outcome = _consult({"worker": _unit()}, _fake_ask(_ok(answers)), client=minimal)

    assert outcome["status"] == "ok"
    assert outcome["judgments"]["worker"]["band"] == staffing.BAND_AUTO_RAISE


def test_unloadable_client_falls_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raises(name: str) -> Any:
        raise RuntimeError(f"no module {name}")

    monkeypatch.setattr(staffing, "_load_commons", _raises)
    outcome = staffing.consult_tier_suggestions({"worker": _unit()}, getenv=lambda _n: None)

    assert outcome["status"] == "error"
    assert "could not be loaded" in outcome["note"]
    assert outcome["judgments"]["worker"]["band"] == staffing.BAND_NOT_CONSULTED


def test_empty_units_make_no_request() -> None:
    calls: list[dict[str, Any]] = []
    outcome = _consult({}, _fake_ask(_ok({}), calls=calls))

    assert outcome["status"] == "ok"
    assert outcome["judgments"] == {}
    assert calls == []


def test_one_direction_question_per_unit_in_one_request() -> None:
    calls: list[dict[str, Any]] = []
    units = {"planner": _unit("p"), "worker": _unit("w"), "merging-worker": _unit("m")}
    answers = (
        _direction("planner", "same", 0.9)
        | _direction("worker", "above", 0.85)
        | _direction("merging-worker", "below", 0.9)
    )
    outcome = _consult(units, _fake_ask(_ok(answers), calls=calls))

    assert len(calls) == 1
    assert set(calls[0]["questions"]) == {f"{key}__direction" for key in units}
    assert set(outcome["judgments"]) == set(units)
    verb = VERB.question_set()["direction"]
    asked = calls[0]["questions"]["worker__direction"]
    assert asked["criteria"] == verb["criteria"]
    assert asked["instructions"]["policy"] == jev_verbs.TIER_POLICY
    assert "`tasks.worker`" in asked["instructions"]["question"]


def test_state_carries_issue_and_unit_fields() -> None:
    calls: list[dict[str, Any]] = []
    issue = {
        "title": "Rotate the signing key",
        "body": "Touches IAM and the token endpoint.",
        "flags": {"has_security": True, "has_api": True, "has_infra": False, "has_privacy": False},
    }
    unit = staffing.judgment_unit(
        {
            "description": "U1 rotate the key",
            "work_shape": "implementation",
            "goal": "rotate the key",
            "files": ["plugins/x/key.py"],
        },
        DEFAULT,
    )
    _consult({"U1": unit}, _fake_ask(_ok({}), calls=calls), issue=issue)

    state = calls[0]["state"]
    assert state["issue"] == issue
    task = state["tasks"]["U1"]
    assert task["description"] == "U1 rotate the key"
    assert task["work_shape"] == "implementation"
    assert task["goal"] == "rotate the key"
    assert task["files"] == ["plugins/x/key.py"]
    assert task["default_tier"] == "opus/medium"


def test_the_cache_option_passes_the_log_directory(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    log = SimpleNamespace(digest=jev_log.digest, log_dir=lambda: tmp_path)
    _consult({"worker": _unit()}, _fake_ask(_ok({}), calls=calls), log_module=log, cache=True)

    assert calls[0]["options"]["cache_dir"] == tmp_path


def test_floors_default_to_the_tier_verb_registry() -> None:
    outcome = _consult({"worker": _unit()}, _fake_ask(_ok(_direction("worker", "same", 0.9))))

    assert outcome["floor"] == pytest.approx(FLOOR)
    assert outcome["auto_floor"] == pytest.approx(AUTO)
    assert (FLOOR, AUTO) == (0.6, 0.8)


# ---------------------------------------------------------------------------
# Logging: deferred until the label is known, run-scoped decision ids.
# ---------------------------------------------------------------------------


def test_consult_logs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(jev_log.LOG_DIR_ENV, str(tmp_path))
    _judge("above", 0.85)

    assert _verdicts(tmp_path) == []


def test_record_tier_verdicts_logs_label_and_run_scoped_id(tmp_path: Path) -> None:
    prefix = f"{staffing.JUDGMENT_DECISION_PREFIX}:o/r#96:role"
    answers = _direction("worker", "above", 0.85) | _direction("planner", "same", 0.9)
    units = {"worker": _unit(), "planner": _unit(default={"model": "opus", "effort": "high"})}
    outcome = _consult(units, _fake_ask(_ok(answers)), decision_prefix=prefix)
    blocks = outcome["judgments"]

    written = staffing.record_tier_verdicts(
        blocks, {"worker": "above"}, log_module=jev_log, log_dir=tmp_path
    )

    assert set(written) == {"worker", "planner"}
    records = {record["decision_id"]: record for record in _verdicts(tmp_path)}
    worker = records["staffing/tier-direction:o/r#96:role:worker"]
    assert worker["answer"]["choice"] == "above"
    assert worker["label"] == "above"
    assert worker["confidence"] == pytest.approx(0.85)
    assert worker["threshold"] == pytest.approx(FLOOR)
    assert worker["resolved_model"] == "jev-1.13.0"
    assert worker["state_hash"] == outcome["state_hash"]
    assert worker["questions_hash"] == outcome["questions_hash"]
    assert records["staffing/tier-direction:o/r#96:role:planner"]["label"] is None


def test_record_tier_verdicts_skips_an_unanswered_block(tmp_path: Path) -> None:
    failed = tc.AskResult(status=tc.STATUS_ERROR, note="down")
    blocks = _consult({"worker": _unit()}, _fake_ask(failed))["judgments"]

    assert staffing.record_tier_verdicts(blocks, {}, log_module=jev_log, log_dir=tmp_path) == {}
    assert _verdicts(tmp_path) == []


# ---------------------------------------------------------------------------
# The tier verb's policy names staffing.json's defaults exactly (AC3).
# ---------------------------------------------------------------------------


def test_tier_policy_names_every_work_shape_default_as_staffing_json_declares() -> None:
    registry = json.loads((COMMONS / "staffing.json").read_text(encoding="utf-8"))
    shapes = registry["work_shapes"]
    for shape, row in shapes.items():
        clause = f"{shape} -> {row['default_model']}/{row['default_effort']}"
        assert clause in jev_verbs.TIER_POLICY, f"TIER_POLICY does not say {clause!r}"
    named = set(re.findall(r"([a-z][a-z-]*) -> [a-z]+/[a-z]+", jev_verbs.TIER_POLICY))
    assert named == set(shapes), "TIER_POLICY names a work shape staffing.json does not have"


def test_tier_verb_choices_cover_the_palette() -> None:
    questions = VERB.question_set()
    assert set(questions["model"]["criteria"]) == set(staffing.MODELS)
    assert set(questions["effort"]["criteria"]) == set(staffing.EFFORTS)
    assert set(questions["direction"]["criteria"]) == {"below", "same", "above"}
    assert questions["direction"]["instructions"]["policy"] == jev_verbs.TIER_POLICY
    assert VERB.auto_floor == pytest.approx(0.8)
    assert VERB.confidence_floor == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# The command line: the default, the judgment and its band, what applies here.
# ---------------------------------------------------------------------------


def _cli_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: Any = None,
    calls: list[dict[str, Any]] | None = None,
    verdicts: list[dict[str, Any]] | None = None,
) -> None:
    """Point the CLI's lazy loader at fakes: a canned client, the real verbs, a capturing log."""

    def _verdict(**record: Any) -> dict[str, Any]:
        stored = dict(record, verdict_hash="hash-for-test")
        if verdicts is not None:
            verdicts.append(stored)
        return stored

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
            return SimpleNamespace(
                record_verdict=_verdict, digest=jev_log.digest, log_dir=lambda: None
            )
        raise AssertionError(f"unexpected commons load: {name}")

    monkeypatch.setattr(staffing, "_load_commons", _load)


def test_cli_suggest_prints_default_judgment_band_and_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    verdicts: list[dict[str, Any]] = []
    _cli_modules(
        monkeypatch, result=_ok(_direction("purely-mechanical", "above", 0.85)), verdicts=verdicts
    )

    assert staffing.main(["resolve", "--shape", "purely-mechanical", "--suggest"]) == 0
    out = capsys.readouterr().out
    assert "default: haiku/medium (policy)" in out
    assert "judgment: above at confidence 0.85 (floor 0.60, auto 0.80)" in out
    assert "in a run: auto-raise -> haiku/high" in out
    assert "applies: haiku/medium" in out
    assert len(verdicts) == 1
    assert verdicts[0]["label"] is None
    assert verdicts[0]["decision_id"] == "staffing/tier-direction:cli:purely-mechanical"


def test_cli_suggest_json_carries_the_band_and_never_changes_the_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    _cli_modules(monkeypatch, result=_ok(_direction("purely-mechanical", "above", 0.85)))

    assert staffing.main(["resolve", "--shape", "purely-mechanical", "--suggest", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tier"] == "haiku/medium"
    assert payload["source"] == "policy"
    assert payload["consult"]["band"] == "auto-raise"
    assert payload["consult"]["proposed"] == {"model": "haiku", "effort": "high"}
    assert payload["consult"]["confidence"] == pytest.approx(0.85)
    assert payload["consult"]["status"] == "ok"


def test_cli_suggest_role_names_the_vendor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    _cli_modules(monkeypatch, result=_ok(_direction("planner", "same", 0.9)))

    assert staffing.main(["resolve", "--role", "planner", "--suggest"]) == 0
    out = capsys.readouterr().out
    assert "default: claude opus/high (policy)" in out
    assert "in a run: agrees" in out
    assert "applies: claude opus/high" in out


def test_cli_suggest_without_key_falls_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real client with no credential: the default stands, exit zero, the reason names the
    missing key, and no request is attempted."""
    monkeypatch.chdir(tmp_path)

    assert staffing.main(["resolve", "--shape", "judgment", "--suggest"]) == 0
    out = capsys.readouterr().out
    assert "default: opus/high (policy)" in out
    assert "judgment: none" in out
    assert "TYPESAFE_API_KEY" in out
    assert "applies: opus/high" in out


def test_cli_suggest_off_switch_makes_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(staffing.TIERING_ENV, "off")
    calls: list[dict[str, Any]] = []
    _cli_modules(monkeypatch, result=_ok({}), calls=calls)

    assert staffing.main(["resolve", "--shape", "judgment", "--suggest"]) == 0
    out = capsys.readouterr().out
    assert calls == []
    assert "switched off" in out
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


# ---------------------------------------------------------------------------
# Issue #133: vendor-supplied probability keys never reach the recorded reason.
# ---------------------------------------------------------------------------


def test_a_probability_key_outside_the_choices_never_reaches_the_reason() -> None:
    hostile = "above'; touch /tmp/pwned; echo '"
    answers = {
        "worker__direction": {
            "type": "choice",
            "choice": "above",
            "confidence": 0.85,
            "probabilities": {hostile: 0.5, "above": 0.85, "same": 0.1, "below": 0.05},
        }
    }
    outcome = _consult({"worker": _unit()}, _fake_ask(_ok(answers)))
    block = outcome["judgments"]["worker"]

    assert block["band"] == staffing.BAND_AUTO_RAISE
    assert hostile not in block["reason"]
    assert "'" not in block["reason"].split("(probabilities:")[1]
    assert "(probabilities: below 0.05, same 0.10, above 0.85)" in block["reason"]
    raised = staffing.jev_raise_from(block)
    assert raised is not None
    assert hostile not in raised["reason"]
    assert "touch" not in json.dumps(raised)


def test_probabilities_with_no_known_choice_add_no_text() -> None:
    answers = {
        "worker__direction": {
            "type": "choice",
            "choice": "above",
            "confidence": 0.85,
            "probabilities": {"it's": 0.85},
        }
    }
    block = _consult({"worker": _unit()}, _fake_ask(_ok(answers)))["judgments"]["worker"]
    assert "probabilities" not in block["reason"]
    assert "it's" not in block["reason"]
