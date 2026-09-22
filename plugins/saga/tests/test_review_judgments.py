"""Advisory judgments inside the roster-based code review (issue 1034).

Three judgments, all advisory: the conditional-lens proposal at declaration
time (``review_roster.py``), and finding dedupe plus the severity flag over
results (``review_result.py``). None scores a lens, none removes anything, and
none ever reaches the network here: every judgment takes an injectable ``ask``,
and every test either passes a fake or runs the command line with
``TYPESAFE_API_KEY`` unset, which the client refuses before any transport runs
("no request was attempted").

The load-bearing properties, each with a test that fails when it stops
holding: a proposal may add a lens and never removes one; dedupe never drops a
finding of higher severity (it groups and keeps both); the severity flag never
lowers a reviewer's severity (it is attached, never applied).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess  # nosec B404 — fixed argv in a test helper, no shell
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"

sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


roster = _load("review_roster_judgments_under_test", SCRIPTS / "review_roster.py")
results = _load("review_result_judgments_under_test", SCRIPTS / "review_result.py")


# ---------------------------------------------------------------------------
# The fake client
# ---------------------------------------------------------------------------


class _FakeResult:
    """Stands in for the client's ``AskResult``."""

    def __init__(
        self,
        answers: dict[str, Any] | None = None,
        *,
        status: str = "ok",
        note: str = "",
        model: str = "jev-1.13.0",
    ) -> None:
        self.answers = answers or {}
        self.status = status
        self.note = note
        self.model = model


def _noul_answer(probability: float) -> dict[str, Any]:
    return {"type": "noul", "noul": probability}


def _score_answer(score: float, confidence: float = 0.8) -> dict[str, Any]:
    return {
        "type": "score",
        "score": score,
        "confidence": confidence,
        "legend": {"0": "P3", "1": "P2", "2": "P1", "3": "P0"},
        "probabilities": {"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.0},
    }


def _fake_ask(
    answers: dict[str, Any] | None = None,
    calls: list[dict[str, Any]] | None = None,
    *,
    result: _FakeResult | None = None,
) -> Any:
    """Answer from a fixed map, recording what the module sent."""

    def _ask(state: Any, questions: dict[str, Any], **kwargs: Any) -> _FakeResult:
        if calls is not None:
            calls.append({"state": state, "questions": questions, "kwargs": kwargs})
        if result is not None:
            return result
        return _FakeResult(dict(answers or {}))

    return _ask


def _exploding_ask(*_args: Any, **_kwargs: Any) -> _FakeResult:
    raise AssertionError("the module made a call it should not have made")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _declaration(**lens_overrides: Any) -> dict[str, Any]:
    lenses: dict[str, Any] = {
        "api-contract": {"applies": True},
        "privacy": {"applies": False, "reason": "no personal data in this change"},
        "performance": {"applies": False, "reason": "no hot path touched"},
    }
    lenses.update(lens_overrides)
    return {
        "schema": "applicability_declaration.v1",
        "resolved_at": "2026-09-20T00:00:00Z",
        "run": {
            "repository": "infiquetra/infiquetra-claude-plugins",
            "issue": 1034,
            "revision": "a" * 40,
        },
        "work_unit": "issue-1034",
        "declared_by": "planner",
        "stack": ["python"],
        "standards_resolved": {},
        "lenses": lenses,
        "executors": {},
        "concurrency_allocation": {},
    }


def _finding(rr: ModuleType, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "path": "plugins/saga/scripts/review_result.py",
        "line": 42,
        "category": "unhandled-error",
        "lens": "correctness",
        "dimension": "intent-behavior-completeness",
        "severity": "P2",
        "evidence": "plugins/saga/scripts/review_result.py:42",
        "impact": "the caller sees a traceback instead of a refusal",
    }
    fields.update(overrides)
    return rr.Finding(**fields)


# ---------------------------------------------------------------------------
# The conditional-lens proposal
# ---------------------------------------------------------------------------


def test_proposal_asks_one_yes_no_question_per_excluded_lens() -> None:
    calls: list[dict[str, Any]] = []
    ask = _fake_ask({"privacy": _noul_answer(0.9), "performance": _noul_answer(0.2)}, calls=calls)
    proposal = roster.propose_lenses(_declaration(), ask=ask, log=False)

    assert proposal["ok"] is True
    assert len(calls) == 1
    questions = calls[0]["questions"]
    assert sorted(questions) == ["performance", "privacy"]
    assert all(question["type"] == "noul" for question in questions.values())
    assert proposal["probabilities"] == {"privacy": 0.9, "performance": 0.2}


def test_proposal_adds_a_lens_and_never_removes_one() -> None:
    ask = _fake_ask({"privacy": _noul_answer(0.9), "performance": _noul_answer(0.2)})
    proposal = roster.propose_lenses(_declaration(), ask=ask, log=False)

    assert proposal["proposed_additions"] == ["privacy"]
    # The Planner's declaration is the floor: everything it already applies
    # stays applied, whatever the model answers.
    assert proposal["declared_applies"] == ["api-contract"]
    assert proposal["proposed_lenses"] == ["api-contract", "privacy"]


def test_proposal_asks_nothing_when_every_lens_already_applies() -> None:
    declaration = _declaration(privacy={"applies": True}, performance={"applies": True})
    proposal = roster.propose_lenses(declaration, ask=_exploding_ask, log=False)

    assert proposal["ok"] is True
    assert proposal["proposed_additions"] == []
    assert proposal["proposed_lenses"] == [
        "api-contract",
        "performance",
        "privacy",
    ]


def test_proposal_never_proposes_an_always_on_lens() -> None:
    """Even a hand-written declaration that excludes one is not a candidacy."""
    calls: list[dict[str, Any]] = []
    declaration = _declaration(security={"applies": False, "reason": "a mistake"})
    ask = _fake_ask({"privacy": _noul_answer(0.9)}, calls=calls)
    proposal = roster.propose_lenses(declaration, ask=ask, log=False)

    assert "security" not in calls[0]["questions"]
    assert "security" not in proposal["candidates"]
    assert "security" not in proposal["proposed_additions"]
    assert "security" in proposal["skipped_always_on"]


def test_proposal_fails_open_to_the_planners_declaration() -> None:
    declaration = _declaration()
    failing = _fake_ask(result=_FakeResult(status="error", note="the key is wrong"))
    proposal = roster.propose_lenses(declaration, ask=failing, log=False)

    assert proposal["ok"] is False
    assert "the key is wrong" in proposal["note"]
    assert proposal["proposed_additions"] == []
    assert proposal["proposed_lenses"] == ["api-contract"]
    assert proposal["probabilities"] == {}


def test_apply_proposal_returns_a_new_declaration_and_removes_nothing() -> None:
    declaration = _declaration()
    before = json.loads(json.dumps(declaration))
    ask = _fake_ask({"privacy": _noul_answer(0.9), "performance": _noul_answer(0.2)})
    proposal = roster.propose_lenses(declaration, ask=ask, log=False)

    applied = roster.apply_proposal(declaration, proposal)

    assert applied is not declaration
    assert declaration == before
    assert applied["lenses"]["api-contract"] == {"applies": True}
    assert applied["lenses"]["privacy"] == {"applies": True}
    assert applied["lenses"]["performance"] == {
        "applies": False,
        "reason": "no hot path touched",
    }


def test_propose_command_prints_additions_and_leaves_the_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance command. No key, so no request is attempted."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    declaration_path = tmp_path / "decl.json"
    declaration_path.write_text(json.dumps(_declaration()), encoding="utf-8")

    completed = subprocess.run(  # nosec B603 — fixed argv, no shell
        [
            sys.executable,
            str(SCRIPTS / "review_roster.py"),
            "--declaration",
            str(declaration_path),
            "--propose",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"},
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["judgment"] == "conditional-lens-proposal"
    assert "proposed_additions" in payload
    assert "probabilities" in payload
    assert "TYPESAFE_API_KEY" in payload["note"]
    on_disk = json.loads(declaration_path.read_text(encoding="utf-8"))
    assert on_disk["lenses"]["privacy"] == {
        "applies": False,
        "reason": "no personal data in this change",
    }


# ---------------------------------------------------------------------------
# Finding dedupe
# ---------------------------------------------------------------------------


def test_dedupe_groups_two_findings_with_the_same_fingerprint_and_keeps_both() -> None:
    first = _finding(results, lens="correctness")
    second = _finding(results, lens="security")
    assert first.id == second.id

    calls: list[dict[str, Any]] = []
    ask = _fake_ask({"pair_0": _noul_answer(0.95)}, calls=calls)
    outcome = results.dedupe_findings([first, second], ask=ask, log=False)

    assert outcome["ok"] is True
    assert outcome["groups"] == [[0, 1]]
    assert outcome["pairs_judged"] == 1
    assert sorted(index for group in outcome["groups"] for index in group) == [0, 1]


def test_dedupe_never_drops_a_finding_whatever_the_model_answers() -> None:
    findings = [
        _finding(results, lens="correctness", line=42),
        _finding(results, lens="security", line=43),
        _finding(results, lens="testing", line=44),
    ]
    ask = _fake_ask(
        {
            "pair_0": _noul_answer(0.95),
            "pair_1": _noul_answer(0.95),
            "pair_2": _noul_answer(0.95),
        }
    )
    outcome = results.dedupe_findings(findings, ask=ask, log=False)

    assert outcome["groups"] == [[0, 1, 2]]
    assert sorted(index for group in outcome["groups"] for index in group) == [0, 1, 2]


def test_dedupe_only_asks_about_pairs_code_found() -> None:
    """Same path and category is a candidacy; anything else is never asked."""
    same_spot = _finding(results, lens="correctness", line=42)
    same_file_other_category = _finding(results, lens="security", line=42, category="missing-guard")
    other_file = _finding(results, lens="testing", path="plugins/saga/scripts/run_record.py")

    pairs = results.dedupe_candidates([same_spot, same_file_other_category, other_file])
    assert pairs == []

    calls: list[dict[str, Any]] = []
    outcome = results.dedupe_findings(
        [same_spot, same_file_other_category, other_file],
        ask=_fake_ask({}, calls=calls),
        log=False,
    )

    assert calls == []
    assert outcome["ok"] is False
    assert outcome["groups"] == [[0], [1], [2]]


def test_dedupe_failure_leaves_every_finding_ungrouped() -> None:
    findings = [_finding(results, lens="correctness"), _finding(results, lens="security")]
    failing = _fake_ask(result=_FakeResult(status="timeout", note="the call timed out"))
    outcome = results.dedupe_findings(findings, ask=failing, log=False)

    assert outcome["ok"] is False
    assert "timed out" in outcome["note"]
    assert outcome["groups"] == [[0], [1]]


# ---------------------------------------------------------------------------
# The severity flag
# ---------------------------------------------------------------------------


def test_severity_flag_is_attached_not_applied() -> None:
    understated = _finding(results, severity="P3")
    ask = _fake_ask({"finding_0": _score_answer(2.9)})
    outcome = results.flag_severity([understated], ask=ask, log=False)

    assert outcome["ok"] is True
    (flag,) = outcome["flags"]
    assert flag["stated"] == "P3"
    assert flag["suggested"] == "P0"
    assert flag["flagged"] is True

    attached = results.attach_severity_flags([understated], outcome)
    assert attached == 1
    assert understated.severity == "P3"
    assert understated.severity_flag is not None
    assert understated.severity_flag["suggested"] == "P0"
    assert understated.to_dict()["severity_flag"]["suggested"] == "P0"


def test_severity_flag_never_lowers_a_reviewers_severity() -> None:
    overstated = _finding(results, severity="P1")
    ask = _fake_ask({"finding_0": _score_answer(0.1)})
    outcome = results.flag_severity([overstated], ask=ask, log=False)

    (flag,) = outcome["flags"]
    assert flag["stated"] == "P1"
    assert flag["suggested"] == "P3"
    assert flag["flagged"] is False

    attached = results.attach_severity_flags([overstated], outcome)
    assert attached == 0
    assert overstated.severity == "P1"
    assert overstated.severity_flag is None


def test_severity_flag_scores_against_the_catalogue_anchors_in_order() -> None:
    calls: list[dict[str, Any]] = []
    ask = _fake_ask({"finding_0": _score_answer(1.0)}, calls=calls)
    results.flag_severity([_finding(results)], ask=ask, log=False)

    (question,) = calls[0]["questions"].values()
    assert question["type"] == "score"
    assert question["criteria"] == [anchor for _, anchor in results.SEVERITY_ANCHORS]
    assert [level for level, _ in results.SEVERITY_ANCHORS] == ["P3", "P2", "P1", "P0"]


def test_severity_flag_failure_flags_nothing() -> None:
    finding = _finding(results, severity="P2")
    failing = _fake_ask(result=_FakeResult(status="error", note="the key is wrong"))
    outcome = results.flag_severity([finding], ask=failing, log=False)

    assert outcome["ok"] is False
    assert outcome["flags"] == []
    assert results.attach_severity_flags([finding], outcome) == 0
    assert finding.severity == "P2"
    assert finding.severity_flag is None


# ---------------------------------------------------------------------------
# Logging and catalogue drift
# ---------------------------------------------------------------------------


def test_each_judgment_logs_its_suggestion_and_its_outcome(tmp_path: Path) -> None:
    verdicts = tmp_path / "verdicts.jsonl"
    ask = _fake_ask({"privacy": _noul_answer(0.9), "performance": _noul_answer(0.2)})
    roster.propose_lenses(_declaration(), ask=ask, log=True, log_dir=tmp_path)
    ask = _fake_ask({"pair_0": _noul_answer(0.95)})
    results.dedupe_findings(
        [_finding(results, lens="a"), _finding(results, lens="b")],
        ask=ask,
        log=True,
        log_dir=tmp_path,
    )
    ask = _fake_ask({"finding_0": _score_answer(2.9)})
    results.flag_severity([_finding(results)], ask=ask, log=True, log_dir=tmp_path)

    rows = [
        json.loads(line)
        for line in verdicts.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decision_ids = [row["decision_id"] for row in rows]
    assert any("code-review:propose-lenses" in value for value in decision_ids)
    assert any("code-review:finding-dedupe" in value for value in decision_ids)
    assert any("code-review:severity-flag" in value for value in decision_ids)


def test_severity_anchors_match_the_lifecycle_catalogue() -> None:
    """The score levels quote the catalogue; a rewording there reds here."""
    catalogue = _lifecycle_catalogue()
    if catalogue is None:
        pytest.skip("no lifecycle checkout on this machine")
    vocabulary = catalogue["finding_schema"]["severity_vocabulary"]
    assert [(level, vocabulary[level]) for level in ("P3", "P2", "P1", "P0")] == list(
        results.SEVERITY_ANCHORS
    )


def test_always_on_lens_ids_match_the_lifecycle_catalogue() -> None:
    catalogue = _lifecycle_catalogue()
    if catalogue is None:
        pytest.skip("no lifecycle checkout on this machine")
    expected = sorted(lens["id"] for lens in catalogue["lenses"] if lens.get("always_on") is True)
    assert sorted(roster.ALWAYS_ON_LENS_IDS) == expected


def _lifecycle_catalogue() -> dict[str, Any] | None:
    candidates = [
        Path(value).expanduser()
        for value in (
            os.environ.get("INFIQUETRA_SDLC_PATH"),
            os.environ.get("INFIQUETRA_SDLC_ROOT"),
        )
        if value
    ]
    candidates.append(Path.home() / "workspace" / "infiquetra" / "infiquetra-sdlc")
    for checkout in candidates:
        catalogue_path = checkout / "config" / "lens-catalogue.json"
        if catalogue_path.is_file():
            data = json.loads(catalogue_path.read_text(encoding="utf-8"))
            assert isinstance(data, dict)
            return data
    return None
