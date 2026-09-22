"""Tests for the ``jev`` command-line tool (plan U5).

Every verb is driven from a recorded response through a stubbed client, so no
test reaches the network.  The registry-completeness test is the one that keeps
the tool and the verb registry from drifting apart.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins/fleet-core/scripts"
SENTINEL_KEY = "SENTINEL-cli-do-not-leak-91f3"  # noqa: S105 - a test fixture


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

jev = _load("jev_cli_under_test", SCRIPTS / "jev.py")
jev_verbs = _load("jev_verbs_under_test", SCRIPTS / "fleet_commons/jev_verbs.py")

RECORDED_ANSWERS = {
    "type": "noul",
    "noul": 0.97,
}


def _fake_result(answers: dict[str, Any] | None = None, status: str = "ok"):
    class _Result:
        def __init__(self) -> None:
            self.status = status
            self.answers = answers if answers is not None else {"noul": dict(RECORDED_ANSWERS)}
            self.model = "jev-1.13.0"
            self.transport = "urllib"
            self.truncation: tuple[str, ...] = ()
            self.usage = {"input_tokens": 10, "output_tokens": 3}
            self.latency_ms = 42
            self.note = "" if status == "ok" else "the endpoint refused the request"

        def to_dict(self) -> dict[str, Any]:
            return {
                "status": self.status,
                "answers": self.answers,
                "model": self.model,
                "transport": self.transport,
                "truncation": list(self.truncation),
                "usage": self.usage,
                "latency_ms": self.latency_ms,
                "note": self.note,
            }

    return _Result()


@pytest.fixture(autouse=True)
def _stub_the_client(monkeypatch):
    """No network, and no verdict-log writes into a real home directory."""
    calls: list[dict[str, Any]] = []

    def _ask(state, questions, *, model="jev-latest", transport=None):  # noqa: ANN001
        calls.append(
            {"state": state, "questions": questions, "model": model, "transport": transport}
        )
        answers = {key: dict(RECORDED_ANSWERS) for key in questions}
        return _fake_result(answers)

    monkeypatch.setattr(jev.typesafe_client, "ask", _ask)
    monkeypatch.setattr(jev.jev_log, "record_verdict", lambda **_kwargs: {})
    monkeypatch.setenv("TYPESAFE_API_KEY", SENTINEL_KEY)
    return calls


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    code = jev.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --------------------------------------------------------------------------- #
# ask
# --------------------------------------------------------------------------- #


def test_ask_returns_a_probability_and_exits_zero(capsys) -> None:
    code, out, _err = _run(
        ["ask", "--state", '{"x":"hello"}', "--noul", "Is `x` a greeting?"], capsys
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["answers"]["noul"]["noul"] == 0.97
    assert payload["status"] == "ok"


def test_dry_run_prints_the_request_and_makes_no_call(capsys, _stub_the_client) -> None:
    code, out, _err = _run(
        ["ask", "--state", '{"x":"hello"}', "--noul", "Is `x` a greeting?", "--dry-run"], capsys
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["dry_run"] is True
    assert payload["request"]["state"] == {"x": "hello"}
    assert set(payload["request"]) == {"state", "model", "questions"}
    assert _stub_the_client == [], "a dry run must not call the transport"


def test_dry_run_output_contains_no_part_of_the_key(capsys) -> None:
    _code, out, err = _run(
        ["ask", "--state", '{"x":"hello"}', "--noul", "Is `x` a greeting?", "--dry-run"], capsys
    )
    assert SENTINEL_KEY not in out
    assert SENTINEL_KEY not in err


def test_choice_and_score_questions_build(capsys, _stub_the_client) -> None:
    code, out, _err = _run(
        [
            "ask",
            "--state",
            '{"x":"hello"}',
            "--choice",
            "Tone?::warm,cold",
            "--score",
            "Risk?::low,medium,high",
            "--dry-run",
        ],
        capsys,
    )
    assert code == 0
    questions = json.loads(out)["request"]["questions"]
    assert questions["choice"]["criteria"] == {"warm": "", "cold": ""}
    assert questions["score"]["criteria"] == ["low", "medium", "high"]


def test_state_file_is_accepted(tmp_path, capsys) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text('{"x": "hello"}', encoding="utf-8")
    code, out, _err = _run(
        ["ask", "--state-file", str(state_file), "--noul", "greeting?", "--dry-run"], capsys
    )
    assert code == 0
    assert json.loads(out)["request"]["state"] == {"x": "hello"}


# --------------------------------------------------------------------------- #
# The named verbs
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", jev_verbs.verb_names())
def test_every_registered_verb_round_trips(verb: str, capsys) -> None:
    """Parameterized over the registry, so a new verb without coverage reds."""
    code, out, _err = _run([verb, "--state", '{"task":"rename a variable"}'], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "ok"
    expected = set(jev_verbs.VERBS[verb].question_set())
    assert set(payload["answers"]) == expected


def test_the_tool_and_the_registry_carry_the_same_verbs() -> None:
    parser = jev.build_parser()
    subparsers = [
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    ]
    declared = set(subparsers[0].choices)
    assert declared == set(jev_verbs.verb_names()) | {"ask", "eval"}


def test_a_verb_carries_its_policy_text_in_one_place() -> None:
    tier = jev_verbs.VERBS["tier"].question_set()
    assert tier["model"]["instructions"]["policy"] == jev_verbs.TIER_POLICY


def test_issue_flags_covers_the_five_flags_and_the_seven_approval_boundaries() -> None:
    """The widen-only union (issue 1036) reads these keys by name, so pin the set."""
    questions = jev_verbs.VERBS["issue-flags"].question_set()

    assert set(questions) == {
        "has_security",
        "has_api",
        "has_infra",
        "has_privacy",
        "has_refactor",
        "production",
        "destructive",
        "credentials",
        "permissions",
        "billing",
        "external_commitments",
        "process_authority",
    }
    assert all(question["type"] == "noul" for question in questions.values())


def test_the_seven_approval_boundaries_carry_the_sdlc_policy_text() -> None:
    questions = jev_verbs.VERBS["issue-flags"].question_set()
    boundaries = (
        "production",
        "destructive",
        "credentials",
        "permissions",
        "billing",
        "external_commitments",
        "process_authority",
    )

    for key in boundaries:
        assert questions[key]["instructions"]["policy"] == jev_verbs.APPROVAL_BOUNDARY_POLICY


def test_journal_nudge_asks_exactly_one_question_with_the_repo_rule() -> None:
    questions = jev_verbs.VERBS["journal-nudge"].question_set()

    assert set(questions) == {"earns_entry"}
    assert questions["earns_entry"]["type"] == "noul"
    assert questions["earns_entry"]["instructions"]["policy"] == jev_verbs.JOURNAL_POLICY


def test_the_two_widen_verbs_carry_their_own_confidence_floors() -> None:
    """The floors differ on purpose: a false flag costs a lens, a false nudge one line."""
    assert jev_verbs.VERBS["issue-flags"].confidence_floor == pytest.approx(0.70)
    assert jev_verbs.VERBS["journal-nudge"].confidence_floor == pytest.approx(0.60)


# --------------------------------------------------------------------------- #
# Failure paths
# --------------------------------------------------------------------------- #


def test_invalid_json_state_exits_non_zero(capsys, _stub_the_client) -> None:
    code, _out, err = _run(["ask", "--state", "not json", "--noul", "q"], capsys)
    assert code == 1
    assert "--state" in err
    assert _stub_the_client == []


def test_both_state_flags_is_an_error(tmp_path, capsys) -> None:
    state_file = tmp_path / "s.json"
    state_file.write_text("{}", encoding="utf-8")
    code, _out, err = _run(
        ["ask", "--state", "{}", "--state-file", str(state_file), "--noul", "q"], capsys
    )
    assert code == 1
    assert "not both" in err


def test_missing_state_is_an_error(capsys) -> None:
    code, _out, err = _run(["ask", "--noul", "q"], capsys)
    assert code == 1
    assert "state is required" in err


def test_no_question_is_an_error(capsys) -> None:
    code, _out, err = _run(["ask", "--state", "{}"], capsys)
    assert code == 1
    assert "--noul" in err


def test_malformed_choice_spec_is_an_error(capsys) -> None:
    code, _out, err = _run(["ask", "--state", "{}", "--choice", "no separator here"], capsys)
    assert code == 1
    assert "::" in err


def test_a_failed_request_exits_non_zero_with_the_reason_on_stderr(monkeypatch, capsys) -> None:
    monkeypatch.setattr(jev.typesafe_client, "ask", lambda *_a, **_k: _fake_result(status="error"))
    code, out, err = _run(["ask", "--state", "{}", "--noul", "q"], capsys)
    assert code == 1
    assert "ERROR:" in err
    # The body still prints so a caller can see the status, but the exit code
    # is what decides, never the presence of output.
    assert json.loads(out)["status"] == "error"


def test_empty_state_is_sent_rather_than_invented(capsys, _stub_the_client) -> None:
    code, out, _err = _run(["ask", "--state", "{}", "--noul", "q", "--dry-run"], capsys)
    assert code == 0
    assert json.loads(out)["request"]["state"] == {}


# --------------------------------------------------------------------------- #
# eval
# --------------------------------------------------------------------------- #


def test_eval_on_a_missing_path_exits_non_zero(capsys) -> None:
    code, _out, err = _run(["e" + "val", "--cached", "/nonexistent/path"], capsys)
    assert code == 1
    assert "no such" in err


