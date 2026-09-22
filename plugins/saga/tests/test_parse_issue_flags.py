"""Tests for the widen-only flag union in `parse_issue.py` (issue 1036).

No test here touches the network or calls `gh`.  The model call arrives through
the injected `widen` seam, and the issue fetch through a replaced function.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PARSE_ISSUE_PATH = REPO_ROOT / "plugins/saga/scripts/parse_issue.py"
WIDEN_PATH = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons/jev_widen.py"
CLIENT_PATH = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons/typesafe_client.py"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


parse_issue = _load("parse_issue_flags_under_test", PARSE_ISSUE_PATH)
jev_widen = _load("jev_widen_for_parse_issue", WIDEN_PATH)
tc = _load("typesafe_client_for_parse_issue", CLIENT_PATH)

# The card's own body, shortened.  It is about credentials, production and
# destructive operations by name -- and the keyword floor misses every one,
# because the pattern matches `credential` and the prose says `credentials`.
CARD_BODY = """### Objective

Two regex-floored judgments where the model can only add, never remove: the
flags gain a noul per category over the issue body, unioned with the regex
result. Categories: destructive, credentials, production.

### Handoff maturity
requirements-ready
"""


def test_parse_issue_key_constants_and_the_issue_flags_verb_name_the_same_keys() -> None:
    """Cross-module drift guard: the caller's keys must be the verb's keys.

    `widen()` reports a key the answer does not carry as "missing" and falls
    back to its floor, silently.  So a rename on either side of this seam does
    not fail -- it quietly stops asking about that category, which is precisely
    the kind of loss this card exists to prevent.
    """
    jev_verbs = _load(
        "jev_verbs_for_parse_issue",
        REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons/jev_verbs.py",
    )
    verb_keys = set(jev_verbs.VERBS["issue-flags"].question_set())
    caller_keys = set(parse_issue.FLAG_KEYS) | set(parse_issue.APPROVAL_BOUNDARY_KEYS)

    assert verb_keys == caller_keys


def _fake_widen(answers: dict[str, float], model: str = "jev-1.13.0"):
    """A `widen` that runs the real union against a recorded answer map."""

    def _ask(state, questions, **options):  # noqa: ANN001, ANN003
        return tc.AskResult(
            status=tc.STATUS_OK,
            answers={key: {"type": "noul", "noul": value} for key, value in answers.items()},
            model=model,
            transport="fake",
        )

    def _widen(state, verb, floors, **kwargs):  # noqa: ANN001, ANN003
        kwargs["ask"] = _ask
        kwargs["log"] = False
        return jev_widen.widen(state, verb, floors, **kwargs)

    return _widen


def _failing_widen(note: str = "TYPESAFE_API_KEY is not set"):
    def _ask(state, questions, **options):  # noqa: ANN001, ANN003
        return tc.AskResult(status=tc.STATUS_ERROR, note=note)

    def _widen(state, verb, floors, **kwargs):  # noqa: ANN001, ANN003
        kwargs["ask"] = _ask
        kwargs["log"] = False
        return jev_widen.widen(state, verb, floors, **kwargs)

    return _widen


# --------------------------------------------------------------------------- #
# The default path is unchanged
# --------------------------------------------------------------------------- #


def test_the_keyword_floor_misses_the_plural_of_credential() -> None:
    """The motivating evidence: this is why the card exists."""
    assert parse_issue.extract(CARD_BODY)["flags"]["has_security"] is False


def test_without_flags_the_output_is_exactly_what_it_always_was() -> None:
    direct = parse_issue.extract(CARD_BODY)
    assert set(direct) == {
        "adr_refs",
        "ac_refs",
        "round_refs",
        "flags",
        "handoff",
        "test_naming_pattern",
        "first_line",
    }
    assert set(direct["flags"]) == set(parse_issue.FLAG_KEYS)


def test_the_default_run_prints_no_judgment_keys(tmp_path: Path, capsys) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(CARD_BODY, encoding="utf-8")

    assert parse_issue.main(["--body-file", str(body_file)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert "flags_detail" not in payload
    assert "approval_boundaries" not in payload
    assert "judgment" not in payload


# --------------------------------------------------------------------------- #
# The union
# --------------------------------------------------------------------------- #


def test_the_model_raises_the_flag_the_keyword_floor_missed() -> None:
    parsed = parse_issue.extract(CARD_BODY)
    widened = parse_issue.widen_flags(CARD_BODY, parsed, widen=_fake_widen({"has_security": 0.95}))

    assert widened["flags"]["has_security"] is True
    assert widened["flags_detail"]["has_security"]["regex"] is False
    assert widened["flags_detail"]["has_security"]["source"] == "model"
    assert widened["judgment"]["resolved_model"] == "jev-1.13.0"


def test_a_keyword_flag_stays_set_whatever_the_model_says() -> None:
    body = "This changes the auth handler and an api/ endpoint."
    parsed = parse_issue.extract(body)
    assert parsed["flags"]["has_security"] is True

    widened = parse_issue.widen_flags(
        body, parsed, widen=_fake_widen({"has_security": 0.0, "has_api": 0.0})
    )

    assert widened["flags"]["has_security"] is True
    assert widened["flags_detail"]["has_security"]["source"] == "regex"
    assert widened["flags"]["has_api"] is True


def test_the_seven_approval_boundaries_are_reported_and_have_no_keyword_floor() -> None:
    parsed = parse_issue.extract(CARD_BODY)
    widened = parse_issue.widen_flags(
        CARD_BODY,
        parsed,
        widen=_fake_widen({"credentials": 0.98, "production": 0.9, "billing": 0.02}),
    )

    boundaries = widened["approval_boundaries"]
    assert set(boundaries) == set(parse_issue.APPROVAL_BOUNDARY_KEYS)
    assert all(entry["regex"] is False for entry in boundaries.values())
    assert boundaries["credentials"]["union"] is True
    assert boundaries["credentials"]["source"] == "model"
    assert boundaries["billing"]["union"] is False


def test_the_boundaries_never_reach_the_flags_the_test_gate_reads() -> None:
    """Nothing in the seven advisory categories may leak into the gated five."""
    parsed = parse_issue.extract(CARD_BODY)
    widened = parse_issue.widen_flags(
        CARD_BODY, parsed, widen=_fake_widen({"destructive": 1.0, "production": 1.0})
    )

    assert set(widened["flags"]) == set(parse_issue.FLAG_KEYS)
    assert widened["flags"] == dict.fromkeys(parse_issue.FLAG_KEYS, False)


# --------------------------------------------------------------------------- #
# Failing open
# --------------------------------------------------------------------------- #


def test_a_client_failure_returns_the_keyword_result_and_names_the_reason() -> None:
    body = "This changes the auth handler."
    parsed = parse_issue.extract(body)
    widened = parse_issue.widen_flags(body, parsed, widen=_failing_widen())

    assert widened["flags"]["has_security"] is True
    assert widened["flags"]["has_infra"] is False
    assert widened["judgment"]["asked"] is False
    assert "TYPESAFE_API_KEY" in widened["judgment"]["note"]


def test_a_client_failure_still_exits_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(CARD_BODY, encoding="utf-8")
    real = parse_issue.widen_flags
    monkeypatch.setattr(
        parse_issue,
        "widen_flags",
        lambda body, parsed, **kwargs: real(body, parsed, widen=_failing_widen()),
    )

    assert parse_issue.main(["--body-file", str(body_file), "--flags"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["judgment"]["asked"] is False
    assert payload["flags"]["has_security"] is False


def test_an_absent_fleet_core_falls_back_to_the_keyword_result(monkeypatch) -> None:
    def _boom() -> Any:
        raise ImportError("no fleet_commons_shim here")

    monkeypatch.setattr(parse_issue, "_load_widen", _boom)

    body = "This changes the auth handler."
    widened = parse_issue.widen_flags(body, parse_issue.extract(body))

    assert widened["flags"]["has_security"] is True
    assert "fleet-core is unavailable" in widened["judgment"]["note"]


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #


def test_a_raising_primitive_still_returns_the_keyword_result() -> None:
    """Fail open covers the primitive's own faults, not only client failures."""

    def _raises(state, verb, floors, **kwargs):  # noqa: ANN001, ANN003
        raise ValueError("no such verb in the registry: issue-flags")

    body = "This changes the auth handler."
    widened = parse_issue.widen_flags(body, parse_issue.extract(body), widen=_raises)

    assert widened["flags"]["has_security"] is True
    assert widened["judgment"]["asked"] is False
    assert "ValueError" in widened["judgment"]["note"]


def test_repo_without_issue_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_issue.parse_args(["--repo", "owner/name"])
    assert excinfo.value.code == 2


def test_issue_and_body_file_together_are_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_issue.parse_args(["--issue", "1036", "--body-file", "x.md"])
    assert excinfo.value.code == 2


def test_a_failed_issue_fetch_exits_one(monkeypatch, capsys) -> None:
    def _boom(number: int, repo: str | None = None, timeout: float = 60.0) -> str:
        raise RuntimeError("`gh issue view 1036` failed: not found")

    monkeypatch.setattr(parse_issue, "fetch_issue_body", _boom)

    assert parse_issue.main(["--issue", "1036"]) == 1
    assert "gh issue view" in capsys.readouterr().err


def test_the_issue_fetch_builds_the_documented_command(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class _Result:
        returncode = 0
        stdout = "a body"
        stderr = ""

    def _run(command, **kwargs):  # noqa: ANN001, ANN003
        seen["command"] = command
        return _Result()

    monkeypatch.setattr(parse_issue.subprocess, "run", _run)

    assert parse_issue.fetch_issue_body(1036) == "a body"
    assert seen["command"] == ["gh", "issue", "view", "1036", "--json", "body", "-q", ".body"]

    parse_issue.fetch_issue_body(1036, "infiquetra/infiquetra-claude-plugins")
    assert seen["command"][-2:] == ["--repo", "infiquetra/infiquetra-claude-plugins"]
