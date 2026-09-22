"""Tests for the widen-only labels union (issue 1035, plan U4).

The GitHub read is faked and the model call is faked.  No test here opens a
socket or applies a label.
"""

# ruff: noqa: E402,I001

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402
import triage_suggest as ts  # noqa: E402


def _load(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


client = _load(
    "typesafe_client_for_labels_tests",
    "plugins/fleet-core/scripts/fleet_commons/typesafe_client.py",
)

RULES = {
    "mentions_security": {
        "pattern": r"security|vulnerability|CVE",
        "add_labels": ["security"],
    },
    "mentions_performance": {
        "pattern": r"performance|latency|slow|timeout",
        "add_labels": ["performance"],
    },
}

# The title trips the `mentions_security` pattern and nothing else, so the rule
# floor in these tests is exactly {"security"}.
ISSUE = {
    "title": "Security: session tokens survive a logout",
    "body": "A stale session token keeps working after the user signs out.",
}


class _FakeResult:
    def __init__(self, status="ok", answers=None, note="") -> None:  # noqa: ANN001
        self.status = status
        self.answers = answers or {}
        self.note = note
        self.model = "jev-1.13.0"
        self.truncation = ()


def _noul(probability: float) -> dict[str, Any]:
    return {"type": "noul", "noul": probability}


@pytest.fixture(autouse=True)
def _no_live_github(monkeypatch):
    """Nothing in this module may reach GitHub, in any test, under any regression.

    Autouse and unconditional: a test that forgets to stub a call gets a loud
    failure here rather than a live `gh` invocation. A mutation that made
    suggest mode apply its union reached a real endpoint from a test that had
    only stubbed the read, which is how this fixture earned its place.
    """

    def _refuse(*args: Any, **kwargs: Any):
        raise AssertionError("a test in this module attempted a live GitHub call")

    monkeypatch.setattr(sdlc_manager, "_rest_post", _refuse)
    monkeypatch.setattr(sdlc_manager, "_rest_get", _refuse)
    monkeypatch.setattr(sdlc_manager, "_gh", _refuse)


@pytest.fixture
def wired(monkeypatch):
    """Fake the GitHub read and the label rules; record any attempted write."""
    posts: list = []

    monkeypatch.setattr(
        sdlc_manager, "load_config", lambda: {"labels": {"auto_label_rules": RULES}}
    )
    monkeypatch.setattr(sdlc_manager, "_rest_get", lambda _path: dict(ISSUE))
    monkeypatch.setattr(
        sdlc_manager,
        "_rest_post",
        lambda path, payload: posts.append({"path": path, "payload": payload}),
    )
    return posts


def _ask(answers: Any = None, calls: list | None = None):
    def _fake(state, questions, **kwargs):  # noqa: ANN001
        if calls is not None:
            calls.append({"state": state, "questions": questions})
        if isinstance(answers, BaseException):
            raise answers
        if isinstance(answers, _FakeResult):
            return answers
        return _FakeResult(answers=answers or {})

    return _fake


def _run(posts_fixture, capsys, **kwargs: Any) -> str:
    sdlc_manager.labels_auto_label(
        "infiquetra-claude-plugins", 42, "text", suggest_client=client, **kwargs
    )
    out: str = capsys.readouterr().out
    return out


# --------------------------------------------------------------------------- #
# The union
# --------------------------------------------------------------------------- #


def test_the_union_is_printed_with_provenance_and_nothing_is_applied(wired, capsys) -> None:
    out = _run(
        wired,
        capsys,
        suggest=True,
        ask=_ask({"documentation": _noul(0.91), "security": _noul(0.88)}),
    )

    assert "security (both)" in out
    assert "documentation (model)" in out
    assert "nothing was applied" in out
    assert wired == []


def test_every_rule_label_survives_a_model_that_says_no_to_everything(wired, capsys) -> None:
    """R14 at the command level, on top of U1's property test."""
    answers = {label: _noul(0.0) for label in ts.CONTENT_LABELS}
    out = _run(wired, capsys, suggest=True, ask=_ask(answers))

    assert "security (rule)" in out
    assert "performance" not in out  # the text matches no performance pattern
    assert wired == []


def test_the_model_is_asked_about_the_documented_labels_with_no_configured_rules(
    monkeypatch, capsys
) -> None:
    """R14a: `auto_label_rules` is empty in the vendored schema."""
    monkeypatch.setattr(sdlc_manager, "load_config", lambda: {"labels": {"auto_label_rules": {}}})
    monkeypatch.setattr(sdlc_manager, "_rest_get", lambda _path: dict(ISSUE))
    calls: list = []

    sdlc_manager.labels_auto_label(
        "infiquetra-claude-plugins",
        42,
        "text",
        suggest=True,
        ask=_ask({"security": _noul(0.97)}, calls=calls),
        suggest_client=client,
    )
    out = capsys.readouterr().out

    assert set(calls[0]["questions"]) == set(ts.CONTENT_LABELS)
    assert "security (model)" in out


def test_a_configured_rule_label_widens_the_question_set(wired, capsys) -> None:
    calls: list = []
    _run(wired, capsys, suggest=True, ask=_ask({}, calls=calls))

    asked = set(calls[0]["questions"])
    assert set(ts.CONTENT_LABELS) <= asked
    assert "security" in asked and "performance" in asked


def test_one_request_carries_every_label_question(wired, capsys) -> None:
    calls: list = []
    _run(wired, capsys, suggest=True, ask=_ask({}, calls=calls))

    assert len(calls) == 1


def test_the_state_is_the_issue_text_and_nothing_else(wired, capsys) -> None:
    calls: list = []
    _run(wired, capsys, suggest=True, ask=_ask({}, calls=calls))

    assert set(calls[0]["state"]) == {"issue"}
    assert "stale session token" in calls[0]["state"]["issue"]


# --------------------------------------------------------------------------- #
# Failure keeps the floor
# --------------------------------------------------------------------------- #


def test_a_failed_call_still_prints_the_rule_labels_with_a_note(wired, capsys) -> None:
    out = _run(
        wired,
        capsys,
        suggest=True,
        ask=_ask(_FakeResult(status="timeout", note="deadline elapsed")),
    )

    assert "security (rule)" in out
    assert "unavailable" in out
    assert "deadline elapsed" in out
    assert wired == []


def test_an_exception_from_the_client_is_caught_and_the_floor_still_prints(wired, capsys) -> None:
    out = _run(wired, capsys, suggest=True, ask=_ask(RuntimeError("vendor exploded")))

    assert "security (rule)" in out
    assert "RuntimeError" in out
    assert wired == []


def test_an_unloadable_fleet_core_still_prints_the_rule_floor(wired, capsys, monkeypatch) -> None:
    """The documented failure when the shim cannot resolve fleet-core."""

    def _explode(_module: str):
        raise RuntimeError("fleet-core did not resolve")

    monkeypatch.setattr(sdlc_manager, "_fleet_commons", _explode)

    sdlc_manager.labels_auto_label("infiquetra-claude-plugins", 42, "text", suggest=True)
    out = capsys.readouterr().out

    assert "security (rule)" in out
    assert "could not be loaded" in out
    assert wired == []


def test_the_model_is_never_asked_about_an_issue_type_label(monkeypatch, capsys) -> None:
    """R14a at the command level: the type labels the rules carry are excluded."""
    monkeypatch.setattr(
        sdlc_manager,
        "load_config",
        lambda: {
            "labels": {
                "auto_label_rules": {
                    "title_contains_capability": {
                        "pattern": r"\[CAPABILITY\]",
                        "add_labels": ["capability", "needs-analysis"],
                    },
                    "mentions_security": {
                        "pattern": r"security|vulnerability|CVE",
                        "add_labels": ["security"],
                    },
                }
            }
        },
    )
    monkeypatch.setattr(sdlc_manager, "_rest_get", lambda _path: dict(ISSUE))
    calls: list = []

    sdlc_manager.labels_auto_label(
        "infiquetra-claude-plugins",
        42,
        "text",
        suggest=True,
        ask=_ask({}, calls=calls),
        suggest_client=client,
    )

    asked = set(calls[0]["questions"])
    assert "capability" not in asked
    assert "needs-analysis" not in asked
    assert set(ts.CONTENT_LABELS) <= asked


def test_a_rule_matched_type_label_still_survives_the_union(monkeypatch, capsys) -> None:
    """Excluded from the QUESTION, never from the floor: widen-only still holds."""
    monkeypatch.setattr(
        sdlc_manager,
        "load_config",
        lambda: {
            "labels": {
                "auto_label_rules": {
                    "title_contains_capability": {
                        "pattern": r"Security",
                        "add_labels": ["capability"],
                    }
                }
            }
        },
    )
    monkeypatch.setattr(sdlc_manager, "_rest_get", lambda _path: dict(ISSUE))

    sdlc_manager.labels_auto_label(
        "infiquetra-claude-plugins",
        42,
        "text",
        suggest=True,
        ask=_ask({}),
        suggest_client=client,
    )
    out = capsys.readouterr().out

    assert "capability (rule)" in out


def test_nothing_matched_and_nothing_suggested_says_so(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sdlc_manager, "load_config", lambda: {"labels": {"auto_label_rules": {}}})
    monkeypatch.setattr(
        sdlc_manager, "_rest_get", lambda _path: {"title": "tidy a comment", "body": "nothing"}
    )

    sdlc_manager.labels_auto_label(
        "infiquetra-claude-plugins",
        42,
        "text",
        suggest=True,
        ask=_ask({label: _noul(0.01) for label in ts.CONTENT_LABELS}),
        suggest_client=client,
    )
    out = capsys.readouterr().out

    assert "no rule matched and the model suggested none" in out


# --------------------------------------------------------------------------- #
# The existing behaviour is untouched
# --------------------------------------------------------------------------- #


def test_without_the_flag_the_model_is_never_called_and_the_post_still_happens(
    wired, capsys
) -> None:
    calls: list = []
    out = _run(wired, capsys, suggest=False, ask=_ask({}, calls=calls))

    assert calls == []
    assert len(wired) == 1
    assert wired[0]["payload"] == {"labels": ["security"]}
    assert "Applied labels" in out


def test_without_the_flag_a_no_match_reports_exactly_as_it_always_did(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sdlc_manager, "load_config", lambda: {"labels": {"auto_label_rules": RULES}}
    )
    monkeypatch.setattr(
        sdlc_manager, "_rest_get", lambda _path: {"title": "tidy a comment", "body": "nothing"}
    )

    sdlc_manager.labels_auto_label("infiquetra-claude-plugins", 42, "text")
    out = capsys.readouterr().out

    assert "No auto-label rules matched" in out


def test_the_json_output_carries_the_union_and_applies_nothing(wired, capsys) -> None:
    sdlc_manager.labels_auto_label(
        "infiquetra-claude-plugins",
        42,
        "json",
        suggest=True,
        ask=_ask({"documentation": _noul(0.95)}),
        suggest_client=client,
    )
    import json

    payload = json.loads(capsys.readouterr().out)

    labels = {entry["label"]: entry["source"] for entry in payload["union"]}
    assert labels == {"security": "rule", "documentation": "model"}
    assert wired == []
