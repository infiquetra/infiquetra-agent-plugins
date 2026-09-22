"""Tests for the shaping judgments (issue 1037).

No test here touches the network.  Every call goes through a fake ``ask`` in the
shape ``tests/test_typesafe_client.py`` established for the client itself, so
the module's injection seam is what is exercised rather than a live endpoint.

The load-bearing properties, each with a test that fails when it stops holding:
a judgment groups and never removes, the judgment names and the subcommands
cannot drift apart, the consequence factors match the ones the brainstorm skill
already pins, no result carries an aggregate that would turn advisory
probabilities into a tier, and nothing here can turn a routing answer into a
command.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess  # nosec B404 - runs this repository's own script, no shell
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "plugins/saga/scripts/shaping_judgments.py"
SKILLS = {
    "/ideate": REPO_ROOT / "plugins/saga/skills/ideate/SKILL.md",
    "/brainstorm": REPO_ROOT / "plugins/saga/skills/brainstorm/SKILL.md",
    "/office-hours": REPO_ROOT / "plugins/saga/skills/office-hours/SKILL.md",
}
IDEATE_CONVERGENCE = (
    REPO_ROOT / "plugins/saga/skills/ideate/references/convergence-and-partnership.md"
)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("shaping_judgments_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sj = _load()


# --------------------------------------------------------------------------
# The fake client


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


def _choice_answer(choice: str, probabilities: dict[str, float], confidence: float) -> dict:
    return {
        "type": "choice",
        "choice": choice,
        "confidence": confidence,
        "probabilities": probabilities,
    }


def _score_answer(score: float, confidence: float = 0.8) -> dict[str, Any]:
    return {"type": "score", "score": score, "confidence": confidence}


def _answer_for(question: dict[str, Any]) -> dict[str, Any]:
    kind = question.get("type")
    if kind == "noul":
        return _noul_answer(0.91)
    if kind == "choice":
        options = list(question["criteria"])
        even = {option: 1.0 / len(options) for option in options}
        even[options[0]] = 1.0 - sum(v for k, v in even.items() if k != options[0])
        return _choice_answer(options[0], even, 0.87)
    return _score_answer(1.4)


def _fake_ask(
    calls: list[dict[str, Any]] | None = None, *, result: _FakeResult | None = None
) -> Callable[..., _FakeResult]:
    """Answer every question in the set, recording what the module sent."""

    def _ask(state: Any, questions: dict[str, Any], **kwargs: Any) -> _FakeResult:
        if calls is not None:
            calls.append({"state": state, "questions": questions, "kwargs": kwargs})
        if result is not None:
            return result
        return _FakeResult({key: _answer_for(value) for key, value in questions.items()})

    return _ask


def _exploding_ask(*_args: Any, **_kwargs: Any) -> _FakeResult:
    raise AssertionError("the module made a call it should not have made")


# --------------------------------------------------------------------------
# U1 — the module, its registry and its front door


ELEVEN_NAMES = {
    "dedupe",
    "axis",
    "grounding-fit",
    "tactical-scope",
    "rubric",
    "revival",
    "scope-tier",
    "consequence",
    "question-order",
    "readiness",
    "route",
}


def test_the_registry_carries_exactly_the_eleven_judgments() -> None:
    assert set(sj.judgment_names()) == ELEVEN_NAMES


@pytest.mark.parametrize("name", sorted(ELEVEN_NAMES - {"axis"}))
def test_every_registered_judgment_round_trips(name: str) -> None:
    """Parameterized over the registry, so a new judgment without coverage reds."""
    calls: list[dict[str, Any]] = []
    result = sj.judge({"text": "a body of text"}, name, ask=_fake_ask(calls))
    assert result["ok"] is True
    assert result["advisory"] is True
    assert set(result["answers"]) == set(sj.JUDGMENTS[name].question_set())
    assert len(calls) == 1, "one judgment about one body of text is one request"


def test_the_subcommands_and_the_registry_carry_the_same_names() -> None:
    parser = sj.build_parser()
    declared = {
        name
        for action in parser._subparsers._group_actions  # noqa: SLF001 - argparse has no public read
        for name in action.choices
    }
    assert declared == set(sj.judgment_names())


def test_a_failed_call_is_advisory_and_not_an_error() -> None:
    failed = _FakeResult(status="timeout", note="the total retry deadline elapsed")
    result = sj.judge({"text": "x"}, "readiness", ask=_fake_ask(result=failed))
    assert result["ok"] is False
    assert result["advisory"] is True
    assert "deadline" in result["note"]
    assert result["answers"] == {}


def test_an_empty_state_asks_nothing() -> None:
    result = sj.judge("   ", "readiness", ask=_exploding_ask)
    assert result["ok"] is False
    assert "empty" in result["note"]


def test_the_module_hands_the_raw_state_to_the_client() -> None:
    """Redaction belongs to the client, on the only path to a transport.

    The module must not pre-process the state: if it did, it would be a second
    place redaction could be skipped.  So the state the fake receives is the
    state the caller passed, byte for byte.
    """
    calls: list[dict[str, Any]] = []
    state = {"doc": "an ordinary sentence", "note": "another"}
    sj.judge(state, "scope-tier", ask=_fake_ask(calls))
    assert calls[0]["state"] == state


def test_the_front_door_exits_zero_on_a_declined_judgment(tmp_path: Path) -> None:
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    completed = subprocess.run(  # nosec B603 - this repository's own script, no shell
        [sys.executable, str(MODULE_PATH), "readiness", "--doc", str(empty)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["advisory"] is True


def test_a_missing_document_is_an_error_not_a_silent_pass() -> None:
    code = sj.main(["readiness", "--doc", "no/such/document.md"])
    assert code == 1


# --------------------------------------------------------------------------
# U2 — the ideate judgments


def _candidates(count: int) -> list[dict[str, str]]:
    return [{"id": f"C{index}", "text": f"idea number {index}"} for index in range(1, count + 1)]


def _pairwise_ask(same_pairs: set[frozenset[str]]) -> Callable[..., _FakeResult]:
    """Answer a batched pair request by reading the indices out of each question.

    The fake resolves `items[i].text` back to a candidate id the same way the
    model would read the state, so the test exercises the real batch shape
    rather than a convenience shortcut.
    """

    def _ask(state: Any, questions: dict[str, Any], **_kwargs: Any) -> _FakeResult:
        items = state["items"]
        answers = {}
        for key, question in questions.items():
            left_index, right_index = (
                int(part) for part in re.findall(r"items\[(\d+)\]", question["instructions"])
            )
            pair = frozenset({items[left_index]["text"], items[right_index]["text"]})
            answers[key] = _noul_answer(0.95 if pair in same_pairs else 0.05)
        return _FakeResult(answers)

    return _ask


def test_grouping_never_removes_a_candidate() -> None:
    candidates = _candidates(4)
    same = {frozenset({"idea number 1", "idea number 2"})}
    result = sj.dedupe_groups(candidates, ask=_pairwise_ask(same))
    assert result["ok"] is True
    flattened = [identifier for group in result["groups"] for identifier in group]
    assert sorted(flattened) == sorted(entry["id"] for entry in candidates)
    assert len(flattened) == len(set(flattened)), "each identifier lands in exactly one group"


def test_a_candidate_no_pair_matched_is_its_own_group() -> None:
    result = sj.dedupe_groups(_candidates(3), ask=_pairwise_ask(set()))
    assert result["groups"] == [["C1"], ["C2"], ["C3"]]


def test_matched_candidates_share_one_group() -> None:
    same = {frozenset({"idea number 1", "idea number 3"})}
    result = sj.dedupe_groups(_candidates(3), ask=_pairwise_ask(same))
    assert sorted(len(group) for group in result["groups"]) == [1, 2]
    assert ["C1", "C3"] in result["groups"]


def test_above_the_cap_the_judgment_declines_and_asks_nothing() -> None:
    oversized = _candidates(sj.DEDUPE_CANDIDATE_CAP + 1)
    result = sj.dedupe_groups(oversized, ask=_exploding_ask)
    assert result["ok"] is False
    assert "above the cap" in result["note"]
    flattened = [identifier for group in result["groups"] for identifier in group]
    assert sorted(flattened) == sorted(entry["id"] for entry in oversized)


def test_pairs_are_batched_not_one_request_each() -> None:
    """One request per pair at the cap would be 2,016 sequential calls."""
    calls: list[dict[str, Any]] = []
    candidates = _candidates(20)
    result = sj.dedupe_groups(candidates, ask=_fake_ask(calls))
    pairs = 20 * 19 // 2
    assert result["pairs_judged"] == pairs
    assert len(calls) < pairs, "every pair got its own request"
    assert len(calls) == result["requests"]
    expected = -(-pairs // sj.DEDUPE_PAIRS_PER_REQUEST)  # ceiling division
    assert len(calls) == expected


def test_a_batch_carries_each_candidate_once_and_one_question_per_pair() -> None:
    calls: list[dict[str, Any]] = []
    sj.dedupe_groups(_candidates(5), ask=_fake_ask(calls))
    sent = calls[0]
    assert len(sent["questions"]) == 10, "five candidates is ten pairs, ten questions"
    ids = [item["id"] for item in sent["state"]["items"]]
    assert len(ids) == len(set(ids)), "a candidate is carried once per request, not once per pair"
    assert sorted(ids) == ["C1", "C2", "C3", "C4", "C5"]


def test_a_run_that_judged_no_pair_does_not_report_itself_as_ok() -> None:
    """Under-grouping from an outage must not look like a real answer."""
    failed = _FakeResult(status="error", note="no key")
    result = sj.dedupe_groups(_candidates(4), ask=_fake_ask(result=failed))
    assert result["ok"] is False
    assert result["pairs_judged"] == 0
    assert result["pairs_unjudged"] == 6
    flattened = [identifier for group in result["groups"] for identifier in group]
    assert sorted(flattened) == ["C1", "C2", "C3", "C4"], "still never removes a candidate"


def test_an_unwritable_verdict_log_does_not_break_the_judgment(tmp_path: Path) -> None:
    """Fail open: a measurement problem is not the caller's problem."""
    unwritable = tmp_path / "not-a-directory"
    unwritable.write_text("this is a file, so the log directory cannot be created here")
    result = sj.judge(
        {"focus": "x"}, "tactical-scope", ask=_fake_ask(), log=True, log_dir=unwritable
    )
    assert result["ok"] is True
    assert result["answers"]["tactical"]["value"] == 0.91


def test_duplicate_candidate_ids_are_refused() -> None:
    with pytest.raises(sj.ShapingJudgmentError):
        sj.dedupe_groups([{"id": "C1", "text": "a"}, {"id": "C1", "text": "b"}], ask=_exploding_ask)


def test_the_grounding_fit_criteria_name_all_four_outcomes() -> None:
    criteria = sj.JUDGMENTS["grounding-fit"].question_set()["outcome"]["criteria"]
    assert set(criteria) == {"proceed", "decline", "office_hours", "surface_mismatch"}


def test_the_keyword_floor_survives_a_negative_judgment() -> None:
    """Widen-only: the judgment may add a detection, never remove one."""

    def _says_no(_state: Any, questions: dict[str, Any], **_kwargs: Any) -> _FakeResult:
        return _FakeResult({key: _noul_answer(0.02) for key in questions})

    result = sj.tactical_scope_union("fix the typos in the readme", ask=_says_no)
    assert result["by_judgment"] is False
    assert result["keyword_hits"] == ["typo", "typos"]
    assert result["tactical"] is True


def test_the_judgment_can_widen_past_the_keyword_floor() -> None:
    def _says_yes(_state: Any, questions: dict[str, Any], **_kwargs: Any) -> _FakeResult:
        return _FakeResult({key: _noul_answer(0.97) for key in questions})

    result = sj.tactical_scope_union("tidy up the stray whitespace", ask=_says_yes)
    assert result["keyword_hits"] == []
    assert result["tactical"] is True


def test_a_failed_tactical_call_leaves_the_floor_intact() -> None:
    failed = _FakeResult(status="error", note="no key")
    result = sj.tactical_scope_union("quick wins please", ask=_fake_ask(result=failed))
    assert result["ok"] is False
    assert result["tactical"] is True, "the keyword floor holds when the call fails"


def test_axis_coverage_offers_a_no_axis_option() -> None:
    questions = sj.axis_questions(["reliability", "developer experience"])
    criteria = questions["axis"]["criteria"]
    assert "none" in criteria
    assert "reliability" in criteria


def test_axis_coverage_refuses_a_single_axis() -> None:
    with pytest.raises(sj.ShapingJudgmentError):
        sj.axis_questions(["only one"])


def test_the_rubric_excludes_axis_spread() -> None:
    """The convergence reference calls axis spread a list-level concern."""
    dimensions = {key for key, _ in sj.RUBRIC_DIMENSIONS}
    assert "axis_spread" not in dimensions
    assert "axis spread" not in " ".join(
        str(question) for question in sj.JUDGMENTS["rubric"].question_set().values()
    )
    reference = IDEATE_CONVERGENCE.read_text(encoding="utf-8")
    assert "a list-level concern, not per-idea" in reference


# --------------------------------------------------------------------------
# U3 — the brainstorm judgments


def test_readiness_returns_one_probability_per_criterion() -> None:
    """The card's first acceptance criterion, offline.

    The questions come from ``READINESS_CRITERIA``, not from parsing a plan.
    A short document is enough. The upstream test read a plan that lived in
    the old repository's ``docs/plans`` and is not part of this package.
    """
    document = "Readiness sample. The requirements name an operator and a check."
    result = sj.judge(document, "readiness", ask=_fake_ask())
    assert result["ok"] is True
    assert set(result["answers"]) == {key for key, _ in sj.READINESS_CRITERIA}
    assert len(result["answers"]) == 7
    for answer in result["answers"].values():
        assert isinstance(answer["value"], float)


def _pinned_consequence_factors() -> list[str]:
    """The six phrases the brainstorm judgment contract pins, read from it.

    Read out of the guard itself rather than copied, so a rename in either
    place reds instead of drifting.
    """
    source = (Path(__file__).resolve().parent / "test_brainstorm_judgment_contract.py").read_text(encoding="utf-8")
    body = source.split("def check_consequence_factors", 1)[1].split("def ", 1)[0]
    return re.findall(r'^\s+"([a-z][^"]+)",$', body, re.MULTILINE)


def test_the_consequence_factors_match_the_ones_the_skill_pins() -> None:
    pinned = _pinned_consequence_factors()
    assert len(pinned) == 6, "the guard's factor list changed shape"
    ours = {phrase.lower() for _, phrase in sj.CONSEQUENCE_FACTORS}
    for phrase in pinned:
        assert any(phrase in candidate for candidate in ours), f"missing factor {phrase!r}"


def test_no_result_aggregates_the_consequence_factors_into_a_tier() -> None:
    """Brainstorm's "No named tiers are used" rule must survive this card."""
    result = sj.judge({"seed": "rotate a webhook credential"}, "consequence", ask=_fake_ask())
    assert set(result) == {
        "judgment",
        "advisory",
        "ok",
        "note",
        "model",
        "confidence_floor",
        "answers",
    }
    for forbidden in ("tier", "level", "assurance", "total", "aggregate", "score"):
        assert forbidden not in result


def test_the_scope_tiers_are_exactly_the_four() -> None:
    criteria = sj.JUDGMENTS["scope-tier"].question_set()["tier"]["criteria"]
    assert set(criteria) == {"lightweight", "standard", "deep-feature", "deep-product"}


def test_a_low_confidence_answer_does_not_clear_the_floor() -> None:
    low = _FakeResult({"tier": _choice_answer("standard", {"standard": 0.4}, 0.31)})
    result = sj.judge({"seed": "something vague"}, "scope-tier", ask=_fake_ask(result=low))
    assert result["answers"]["tier"]["floor_met"] is False
    high = _FakeResult({"tier": _choice_answer("standard", {"standard": 0.9}, 0.92)})
    result = sj.judge({"seed": "something clear"}, "scope-tier", ask=_fake_ask(result=high))
    assert result["answers"]["tier"]["floor_met"] is True


def test_question_ordering_scores_consequence_and_uncertainty_separately() -> None:
    result = sj.judge({"question": "where does the data live?"}, "question-order", ask=_fake_ask())
    assert set(result["answers"]) == {"consequence", "uncertainty"}


def test_the_score_levels_do_not_re_declare_the_fleet_effort_vocabulary() -> None:
    """A bare subset of the effort ladder in a saga script reads as a re-declaration.

    tests/test_tier_vocab_single_source.py owns that rule fleet-wide; this
    keeps the reason visible at the constant it applies to, so a future edit
    back to low/medium/high is caught here with an explanation rather than
    only by a guard three directories away.
    """
    efforts = {"low", "medium", "high", "xhigh", "max"}
    assert not set(sj.RUBRIC_LEVELS) <= efforts
    assert len(sj.RUBRIC_LEVELS) >= 2


# --------------------------------------------------------------------------
# U4 — the office-hours routing choice


def test_the_routing_answer_carries_every_route() -> None:
    probabilities = {"ideate": 0.5, "brainstorm": 0.2, "plan": 0.2, "strategy": 0.05, "drop": 0.05}
    answer = _FakeResult({"route": _choice_answer("ideate", probabilities, 0.62)})
    result = sj.judge("the settled frame", "route", ask=_fake_ask(result=answer))
    returned = result["answers"]["route"]["answer"]["probabilities"]
    assert set(returned) == set(sj.OFFICE_HOURS_ROUTES)
    assert len(returned) == 5


def test_nothing_turns_a_routing_answer_into_a_command() -> None:
    """The distribution is shown; it is never acted on."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("subprocess.run", "os.system", "os.execv", "Popen"):
        assert forbidden not in source
    exported = set(sj.__all__)
    assert not {name for name in exported if "route" in name or "dispatch" in name}


# --------------------------------------------------------------------------
# U5 — the skills name the judgments they call


def test_every_judgment_is_named_in_the_skill_that_calls_it() -> None:
    """A registered judgment no skill calls, or a renamed one, reds here."""
    texts = {command: path.read_text(encoding="utf-8") for command, path in SKILLS.items()}
    for name in sj.judgment_names():
        command = sj.JUDGMENTS[name].command
        assert f"`{name}`" in texts[command], f"{command} never names the {name} judgment"


@pytest.mark.parametrize("command", sorted(SKILLS))
def test_each_skill_calls_the_module_and_states_it_is_advisory(command: str) -> None:
    text = SKILLS[command].read_text(encoding="utf-8")
    assert "plugins/saga/scripts/shaping_judgments.py" in text
    assert "advisory" in text.lower()
    assert "fails open" in text.lower()
