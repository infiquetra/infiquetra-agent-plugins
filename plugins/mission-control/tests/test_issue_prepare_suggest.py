"""Tests for advisory suggestions on the prepare path (issue 1035, plan U2 + U3).

Every test drives a fake ``ask`` callable.  Nothing here opens a socket, reads
``TYPESAFE_API_KEY``, or writes to the real verdict log: the log directory is a
``tmp_path`` in every test that logs at all.

The key is a recognizable sentinel wherever one is placed in the environment, so
the leak assertions can prove it reached no artefact.
"""

# ruff: noqa: E402,I001

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402
import triage_suggest as ts  # noqa: E402

SENTINEL_KEY = "SENTINEL-do-not-leak-1035aaa"  # noqa: S105 - a test fixture, not a credential


def _load(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


client = _load(
    "typesafe_client_for_prepare_tests",
    "plugins/fleet-core/scripts/fleet_commons/typesafe_client.py",
)
jev_log = _load(
    "jev_log_for_prepare_tests",
    "plugins/fleet-core/scripts/fleet_commons/jev_log.py",
)


BODY = """### Objective
Repair the prepared-issue sidecar so it carries advisory suggestions.

### Intent
Authors pick an issue type from a five-way taxonomy with only a decision tree to
help. End-state: the draft records what a typed judgment thought, beside what the
author chose.

### Acceptance criteria
- [ ] The sidecar carries a type suggestion; `uv run pytest plugins/mission-control/tests/test_issue_prepare_suggest.py` exits 0

### Out-of-scope / non-goals
- Nothing is auto-applied

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_issue_prepare_suggest.py

### Verification
```bash
uv run pytest plugins/mission-control/tests/test_issue_prepare_suggest.py
```

### Risk
medium
The change is confined to the prepared-issue draft pipeline.

### Context library links
_none_
"""


ANSWERS = {
    ts.QUESTION_TYPE: {
        "type": "choice",
        "choice": "enhancement",
        "confidence": 0.82,
        "probabilities": {
            "capability": 0.05,
            "enhancement": 0.82,
            "defect": 0.08,
            "exploration": 0.02,
            "context-update": 0.03,
        },
    },
    ts.QUESTION_RISK: {"type": "score", "score": 1.2, "confidence": 0.77},
    ts.QUESTION_STATUS: {
        "type": "choice",
        "choice": "Designing",
        "confidence": 0.64,
        "probabilities": {"Designing": 0.64, "Implementing": 0.36},
    },
}


class _FakeResult:
    """The shape `typesafe_client.ask` returns, with only the fields callers read."""

    def __init__(
        self,
        status: str = "ok",
        answers: dict[str, Any] | None = None,
        note: str = "",
        model: str = "jev-1.13.0",
        truncation: tuple[str, ...] = (),
    ) -> None:
        self.status = status
        self.answers = answers if answers is not None else dict(ANSWERS)
        self.note = note
        self.model = model
        self.truncation = truncation


def _fake_ask(result: Any = None, calls: list | None = None):
    def _ask(state, questions, **kwargs):  # noqa: ANN001
        if calls is not None:
            calls.append({"state": state, "questions": questions, "kwargs": kwargs})
        if isinstance(result, BaseException):
            raise result
        return result if result is not None else _FakeResult()

    return _ask


def _prepare(tmp_path: Path, **overrides: Any) -> Path:
    kwargs: dict[str, Any] = {
        "repo": "infiquetra-claude-plugins",
        "issue_type": "defect",
        "team": "campps",
        "project": "campps",
        "source": BODY,
        "title": "Advisory suggestions on the prepare path",
        "status": None,
        "risk": "medium",
        "mode": None,
        "draft_dir": tmp_path,
        "stage": "Intake",
    }
    kwargs.update(overrides)
    draft: Path = sdlc_manager.issue_prepare(**kwargs)
    return draft


def _sidecar(draft: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(draft.with_suffix(".json").read_text())
    return payload


# --------------------------------------------------------------------------- #
# U2 — the suggestions reach the sidecar
# --------------------------------------------------------------------------- #


def test_the_sidecar_carries_the_type_distribution_and_the_risk_suggestion(tmp_path) -> None:
    """The card's first acceptance criterion, at the function level."""
    draft = _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )
    sidecar = _sidecar(draft)

    assert sidecar["type_suggestion"]["suggested"] == "enhancement"
    assert set(sidecar["type_suggestion"]["distribution"]) == set(sdlc_manager._ISSUE_TYPES)
    assert sum(sidecar["type_suggestion"]["distribution"].values()) == pytest.approx(1.0)
    assert sidecar["risk_suggestion"]["suggested"] == "medium"
    assert sidecar["risk_suggestion"]["score"] == pytest.approx(1.2)
    assert sidecar["suggestions"]["status"] == "ok"
    assert sidecar["suggestions"]["resolved_model"] == "jev-1.13.0"


def test_every_question_travels_in_one_request(tmp_path) -> None:
    """House rule 5, asserted on the request rather than on the answer."""
    calls: list = []
    _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(calls=calls),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
        objective_options=["alpha", "beta"],
    )

    assert len(calls) == 1
    questions = calls[0]["questions"]
    assert set(questions) == {
        ts.QUESTION_TYPE,
        ts.QUESTION_RISK,
        ts.QUESTION_STATUS,
        ts.QUESTION_OBJECTIVE,
    }


def test_the_state_carries_the_issue_body_and_the_repository_policy(tmp_path) -> None:
    calls: list = []
    _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(calls=calls),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )

    state = calls[0]["state"]
    assert "Repair the prepared-issue sidecar" in state["issue"]
    # The issue-types reference is what lifted the research probe from 17 to 19.
    assert "Decision Tree" in state["policy"]


def test_the_draft_markdown_is_byte_identical_with_and_without_the_flag(tmp_path) -> None:
    plain = _prepare(tmp_path / "plain")
    suggested = _prepare(
        tmp_path / "suggested",
        suggest=True,
        ask=_fake_ask(),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )

    assert suggested.read_bytes() == plain.read_bytes()


def test_without_the_flag_nothing_is_asked_and_no_suggestion_key_appears(tmp_path) -> None:
    calls: list = []
    draft = _prepare(tmp_path, ask=_fake_ask(calls=calls), suggest_client=client)
    sidecar = _sidecar(draft)

    assert calls == []
    assert "suggestions" not in sidecar
    assert "type_suggestion" not in sidecar
    assert "risk_suggestion" not in sidecar


def test_the_sidecar_is_otherwise_unchanged_but_for_its_timestamp(tmp_path) -> None:
    """R1: no existing key changes, and `updated_at` already varies run to run."""
    plain = _sidecar(_prepare(tmp_path / "plain"))
    suggested = _sidecar(
        _prepare(
            tmp_path / "suggested",
            suggest=True,
            ask=_fake_ask(),
            suggest_client=client,
            suggest_log=jev_log,
            suggest_log_dir=tmp_path / "log",
        )
    )

    added = {"suggestions", "type_suggestion", "risk_suggestion"}
    assert set(suggested) - set(plain) == added
    for key in set(plain) - {"updated_at", "draft_path", "sidecar_path"}:
        assert suggested[key] == plain[key], key


def test_a_high_risk_suggestion_never_touches_the_cards_own_risk(tmp_path) -> None:
    """R4: the body is the only source of Risk, whatever the model scores."""
    answers = dict(ANSWERS)
    answers[ts.QUESTION_RISK] = {"type": "score", "score": 3.0, "confidence": 0.95}

    draft = _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(_FakeResult(answers=answers)),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )
    sidecar = _sidecar(draft)

    assert sidecar["risk_suggestion"]["suggested"] == "very-high"
    assert sidecar["risk"] == "medium"
    assert "very-high" not in draft.read_text()


def test_a_differing_type_flag_is_recorded_as_an_override_in_the_sidecar(tmp_path) -> None:
    draft = _prepare(
        tmp_path,
        issue_type="defect",
        suggest=True,
        ask=_fake_ask(),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )
    sidecar = _sidecar(draft)

    assert sidecar["type_suggestion"]["overridden"] is True
    assert sidecar["type_suggestion"]["chosen"] == "defect"
    assert sidecar["issue_type"] == "defect"


def test_no_objective_candidates_means_the_question_is_not_asked(tmp_path) -> None:
    calls: list = []
    draft = _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(calls=calls),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )
    sidecar = _sidecar(draft)

    assert ts.QUESTION_OBJECTIVE not in calls[0]["questions"]
    assert sidecar["suggestions"]["judgments"][ts.QUESTION_OBJECTIVE]["asked"] is False
    assert "no candidates" in sidecar["suggestions"]["judgments"][ts.QUESTION_OBJECTIVE]["reason"]


def test_the_status_candidates_come_from_the_schema_offline(tmp_path) -> None:
    calls: list = []
    _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(calls=calls),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
        stage="Planning",
    )

    options = set(calls[0]["questions"][ts.QUESTION_STATUS]["criteria"])
    assert options == set(sdlc_manager._stage_flow_rules()["stage_statuses"]["Planning"])


def test_with_no_stage_the_status_candidates_are_the_union_of_every_stage() -> None:
    union = sdlc_manager._suggestion_status_options(None)
    rules = sdlc_manager._stage_flow_rules()["stage_statuses"]

    assert len(union) == len(set(union))
    for options in rules.values():
        assert set(options) <= set(union)


# --------------------------------------------------------------------------- #
# U2 — failure leaves the draft alone
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", ["error", "timeout", "malformed"])
def test_a_client_failure_leaves_the_draft_unchanged_with_a_note(tmp_path, status: str) -> None:
    plain = _prepare(tmp_path / "plain")
    draft = _prepare(
        tmp_path / "failed",
        suggest=True,
        ask=_fake_ask(_FakeResult(status=status, note="the vendor said no")),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )
    sidecar = _sidecar(draft)

    assert draft.read_bytes() == plain.read_bytes()
    assert sidecar["suggestions"] == {"status": status, "note": "the vendor said no"}
    assert "type_suggestion" not in sidecar
    assert sidecar["readiness"]["passed"] is True
    assert sidecar["readiness"]["blocking_gaps"] == []


def test_an_unexpected_exception_is_caught_rather_than_escaping_the_prepare(tmp_path) -> None:
    draft = _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(RuntimeError("the vendor library exploded")),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )
    sidecar = _sidecar(draft)

    assert sidecar["suggestions"]["status"] == "error"
    assert "RuntimeError" in sidecar["suggestions"]["note"]
    assert sidecar["readiness"]["passed"] is True


def test_an_unloadable_fleet_core_is_reported_and_the_draft_is_still_written(
    tmp_path, monkeypatch
) -> None:
    """The documented failure when the shim cannot resolve fleet-core.

    Exercised by making the shim loader raise, which is what an installed tree
    missing fleet-core does.
    """

    def _explode(_module: str):
        raise RuntimeError("fleet-core did not resolve")

    monkeypatch.setattr(sdlc_manager, "_fleet_commons", _explode)

    plain = _prepare(tmp_path / "plain")
    draft = _prepare(tmp_path / "unloadable", suggest=True)
    sidecar = _sidecar(draft)

    assert draft.read_bytes() == plain.read_bytes()
    assert sidecar["suggestions"]["status"] == "error"
    assert "could not be loaded" in sidecar["suggestions"]["note"]


def test_a_failure_never_adds_a_blocking_gap_to_readiness(tmp_path) -> None:
    plain = _sidecar(_prepare(tmp_path / "plain"))
    failed = _sidecar(
        _prepare(
            tmp_path / "failed",
            suggest=True,
            ask=_fake_ask(_FakeResult(status="timeout", note="deadline")),
            suggest_client=client,
            suggest_log=jev_log,
            suggest_log_dir=tmp_path / "log",
        )
    )

    assert failed["readiness"] == plain["readiness"]
    assert failed["state"] == plain["state"]


# --------------------------------------------------------------------------- #
# U3 — the verdict log
# --------------------------------------------------------------------------- #


def _verdicts(log_dir: Path) -> list[dict[str, Any]]:
    path = log_dir / jev_log.VERDICT_FILENAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_one_verdict_per_question_carrying_the_model_and_the_authors_label(tmp_path) -> None:
    log_dir = tmp_path / "log"
    _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=log_dir,
    )

    verdicts = [record for record in _verdicts(log_dir) if record["kind"] == "verdict"]
    assert len(verdicts) == len(ANSWERS)
    for record in verdicts:
        assert record["decision_id"].startswith("mission-control/issue-prepare:")
        assert record["resolved_model"] == "jev-1.13.0"
        assert record["threshold"] == ts.DEFAULT_CONFIDENCE_FLOOR
        # A hash of the state, never the state itself.
        assert "Repair the prepared-issue sidecar" not in json.dumps(record)

    by_decision = {record["decision_id"]: record for record in verdicts}
    assert by_decision["mission-control/issue-prepare:issue_type"]["label"] == "defect"


def test_a_disagreement_appends_exactly_one_override_linked_by_hash(tmp_path) -> None:
    log_dir = tmp_path / "log"
    _prepare(
        tmp_path,
        issue_type="defect",
        suggest=True,
        ask=_fake_ask(),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=log_dir,
    )

    records = _verdicts(log_dir)
    type_verdict = next(
        record
        for record in records
        if record["kind"] == "verdict"
        and record["decision_id"] == "mission-control/issue-prepare:issue_type"
    )
    for_type = [
        record
        for record in records
        if record["kind"] == "override" and record["verdict_hash"] == type_verdict["verdict_hash"]
    ]

    assert len(for_type) == 1
    assert for_type[0]["chosen"] == "defect"
    assert "issue_type" in for_type[0]["rationale"]
    # Every override in the file points at a verdict in the same file; an
    # override whose hash matches nothing would be unjoinable evidence.
    verdict_hashes = {record["verdict_hash"] for record in records if record["kind"] == "verdict"}
    for record in records:
        if record["kind"] == "override":
            assert record["verdict_hash"] in verdict_hashes


def test_agreement_on_every_question_appends_no_override(tmp_path) -> None:
    log_dir = tmp_path / "log"
    answers = {ts.QUESTION_TYPE: dict(ANSWERS[ts.QUESTION_TYPE])}
    _prepare(
        tmp_path,
        issue_type="enhancement",
        suggest=True,
        ask=_fake_ask(_FakeResult(answers=answers)),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=log_dir,
    )

    records = _verdicts(log_dir)
    assert [record["kind"] for record in records] == ["verdict"]


def test_a_client_failure_logs_nothing_at_all(tmp_path) -> None:
    log_dir = tmp_path / "log"
    _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(_FakeResult(status="error", note="nope")),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=log_dir,
    )

    assert _verdicts(log_dir) == []


def test_an_unwritable_log_never_fails_the_prepare(tmp_path) -> None:
    class _ExplodingLog:
        VERDICT_FILENAME = jev_log.VERDICT_FILENAME

        @staticmethod
        def record_verdict(**_kwargs: Any) -> dict[str, Any]:
            raise OSError("read-only file system")

        @staticmethod
        def record_override(**_kwargs: Any) -> dict[str, Any]:  # pragma: no cover - never reached
            raise AssertionError("an override cannot follow a failed verdict")

    draft = _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(),
        suggest_client=client,
        suggest_log=_ExplodingLog,
        suggest_log_dir=tmp_path / "log",
    )

    assert draft.exists()
    assert _sidecar(draft)["type_suggestion"]["suggested"] == "enhancement"


# --------------------------------------------------------------------------- #
# Key safety
# --------------------------------------------------------------------------- #


def test_the_key_reaches_no_artefact_the_prepare_writes(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", SENTINEL_KEY)
    log_dir = tmp_path / "log"

    draft = _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=log_dir,
    )
    captured = capsys.readouterr()

    assert SENTINEL_KEY not in draft.read_text()
    assert SENTINEL_KEY not in draft.with_suffix(".json").read_text()
    assert SENTINEL_KEY not in captured.out
    assert SENTINEL_KEY not in captured.err
    assert SENTINEL_KEY not in (log_dir / jev_log.VERDICT_FILENAME).read_text()


def test_the_printed_summary_names_the_override_and_applies_nothing(tmp_path, capsys) -> None:
    _prepare(
        tmp_path,
        issue_type="defect",
        suggest=True,
        ask=_fake_ask(),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )
    out = capsys.readouterr().out

    assert "nothing was applied" in out
    assert "OVERRIDDEN" in out
    assert "enhancement" in out


def test_the_printed_summary_reports_a_failure_rather_than_staying_silent(tmp_path, capsys) -> None:
    _prepare(
        tmp_path,
        suggest=True,
        ask=_fake_ask(_FakeResult(status="timeout", note="deadline elapsed")),
        suggest_client=client,
        suggest_log=jev_log,
        suggest_log_dir=tmp_path / "log",
    )
    out = capsys.readouterr().out

    assert "unavailable (timeout)" in out
    assert "deadline elapsed" in out


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sdlc_manager.py"


def _cli(*argv: str) -> subprocess.CompletedProcess[str]:
    """Run the real command line in a subprocess. No network: --help and usage errors only."""
    return subprocess.run(  # noqa: S603 - fixed interpreter and in-repo script path
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_both_new_flags_are_registered_on_the_prepare_subcommand() -> None:
    result = _cli("issue", "prepare", "--help")

    assert result.returncode == 0
    assert "--suggest" in result.stdout
    assert "--objective-option" in result.stdout
    # The help text has to say the thing the card says twice.
    assert "Applies nothing" in result.stdout


def test_the_command_line_flags_reach_issue_prepare(monkeypatch) -> None:
    """Registration is not wiring: this proves the dispatch passes both through.

    `--help` shows a flag exists; it does not show that `main()` forwards it.
    A dispatch arm that dropped `suggest=` would leave every other test green.
    """
    seen: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> Path:
        seen.update(kwargs)
        return Path("drafts/fake.md")

    monkeypatch.setattr(sdlc_manager, "issue_prepare", _capture)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sdlc_manager.py",
            "issue",
            "prepare",
            "--repo",
            "infiquetra-claude-plugins",
            "--type",
            "defect",
            "--team",
            "asgard",
            "--project",
            "operations",
            "--title",
            "t",
            "--suggest",
            "--objective-option",
            "alpha",
            "a body",
        ],
    )

    sdlc_manager.main()

    assert seen["suggest"] is True
    assert seen["objective_options"] == ["alpha"]


def test_the_command_line_defaults_reach_issue_prepare_as_off(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> Path:
        seen.update(kwargs)
        return Path("drafts/fake.md")

    monkeypatch.setattr(sdlc_manager, "issue_prepare", _capture)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sdlc_manager.py",
            "issue",
            "prepare",
            "--repo",
            "infiquetra-claude-plugins",
            "--type",
            "defect",
            "--team",
            "asgard",
            "--project",
            "operations",
            "--title",
            "t",
            "a body",
        ],
    )

    sdlc_manager.main()

    assert seen["suggest"] is False
    assert seen["objective_options"] == []


def test_the_suggest_flag_is_registered_on_the_auto_label_subcommand() -> None:
    result = _cli("labels", "auto-label", "--help")

    assert result.returncode == 0
    assert "--suggest" in result.stdout
    assert "apply NOTHING" in result.stdout


def test_team_and_project_are_still_required_with_suggest() -> None:
    """The card's acceptance command omits them; relaxing them is out of scope.

    Argparse refuses before any suggestion code runs, so this reaches no
    network even though it drives the real command line.
    """
    result = _cli(
        "issue",
        "prepare",
        "--repo",
        "infiquetra-claude-plugins",
        "--type",
        "defect",
        "--title",
        "t",
        "--suggest",
    )

    assert result.returncode != 0
    assert "--team" in result.stderr
    assert "--project" in result.stderr
