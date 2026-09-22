"""Tests for the advisory triage judgments (issue 1035, plan U1).

No test here touches the network, reads ``TYPESAFE_API_KEY``, or writes to the
real verdict log.  The module under test makes no call of its own; the fleet-core
client is used only for its two answer-reading helpers, which are pure.
"""

# ruff: noqa: E402,I001

import importlib.util
import itertools
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
    "typesafe_client_for_triage_tests",
    "plugins/fleet-core/scripts/fleet_commons/typesafe_client.py",
)
jev_verbs = _load(
    "jev_verbs_for_triage_tests",
    "plugins/fleet-core/scripts/fleet_commons/jev_verbs.py",
)


def _choice_answer(value: str, confidence: float, probabilities: dict[str, float]):
    return {
        "type": "choice",
        "choice": value,
        "confidence": confidence,
        "probabilities": probabilities,
    }


def _score_answer(score: float, confidence: float = 0.8):
    return {"type": "score", "score": score, "confidence": confidence}


def _noul_answer(probability: float):
    return {"type": "noul", "noul": probability}


TYPE_ANSWER = _choice_answer(
    "enhancement",
    0.82,
    {
        "capability": 0.05,
        "enhancement": 0.82,
        "defect": 0.08,
        "exploration": 0.02,
        "context-update": 0.03,
    },
)


# --------------------------------------------------------------------------- #
# build_questions
# --------------------------------------------------------------------------- #


def test_build_questions_batches_every_question_into_one_set() -> None:
    questions = ts.build_questions(
        issue_types=sdlc_manager._ISSUE_TYPES,
        risk_levels=sdlc_manager._RISK_TIER_VOCABULARY,
        status_options=("Designing", "Implementing"),
        objective_options=("alpha", "beta"),
        policy_text="THE ISSUE TYPES REFERENCE",
    )

    assert set(questions) == {
        ts.QUESTION_TYPE,
        ts.QUESTION_RISK,
        ts.QUESTION_STATUS,
        ts.QUESTION_OBJECTIVE,
    }
    assert set(questions[ts.QUESTION_TYPE]["criteria"]) == set(sdlc_manager._ISSUE_TYPES)
    assert questions[ts.QUESTION_TYPE]["instructions"]["policy"] == "THE ISSUE TYPES REFERENCE"


def test_no_objective_candidates_means_no_objective_question() -> None:
    questions = ts.build_questions(
        issue_types=sdlc_manager._ISSUE_TYPES,
        risk_levels=sdlc_manager._RISK_TIER_VOCABULARY,
        status_options=("Designing",),
    )

    assert ts.QUESTION_OBJECTIVE not in questions
    assert len(questions) == 3


def test_objective_question_offers_an_explicit_no_match_option() -> None:
    questions = ts.build_questions(
        issue_types=sdlc_manager._ISSUE_TYPES,
        risk_levels=sdlc_manager._RISK_TIER_VOCABULARY,
        objective_options=("alpha",),
    )

    assert ts.NO_MATCH in questions[ts.QUESTION_OBJECTIVE]["criteria"]


def test_the_risk_levels_are_the_repository_vocabulary_including_very_high() -> None:
    """Plan R3: the risk question must carry all four tiers, and not UNKNOWN.

    Asserted against the constant rather than against a literal list, so
    widening `_RISK_TIER_VOCABULARY` reaches the question instead of silently
    leaving the question narrower than the repository's own vocabulary.
    """
    questions = ts.build_questions(
        issue_types=sdlc_manager._ISSUE_TYPES,
        risk_levels=sdlc_manager._RISK_TIER_VOCABULARY,
    )

    levels = questions[ts.QUESTION_RISK]["criteria"]
    assert levels == list(sdlc_manager._RISK_TIER_VOCABULARY)
    assert "very-high" in levels
    assert sdlc_manager._RISK_UNKNOWN_TOKEN not in levels


def test_an_empty_vocabulary_is_refused_rather_than_asked() -> None:
    with pytest.raises(ValueError, match="issue type"):
        ts.build_questions(issue_types=(), risk_levels=("low",))
    with pytest.raises(ValueError, match="risk level"):
        ts.build_questions(issue_types=("defect",), risk_levels=())


def test_build_state_carries_only_the_issue_and_the_policy() -> None:
    state = ts.build_state("a body", "a policy")
    assert state == {"issue": "a body", "policy": "a policy"}
    assert ts.build_state("a body") == {"issue": "a body"}


def test_the_issue_type_options_match_the_fleet_core_triage_verb() -> None:
    """Plan KTD1's drift guard.

    The question set lives in mission-control and fleet-core keeps its generic
    `triage` verb.  Neither may quietly enumerate a different set of issue
    types than the other.
    """
    ours = set(
        ts.build_questions(
            issue_types=sdlc_manager._ISSUE_TYPES,
            risk_levels=sdlc_manager._RISK_TIER_VOCABULARY,
        )[ts.QUESTION_TYPE]["criteria"]
    )
    theirs = set(jev_verbs.VERBS["triage"].questions["type"]["criteria"])

    assert ours == theirs


# --------------------------------------------------------------------------- #
# score_to_level
# --------------------------------------------------------------------------- #


LEVELS = ("low", "medium", "high", "very-high")


def test_a_score_is_a_number_that_maps_to_a_level() -> None:
    """Plan R3a: `answer_value` on a score returns 1.2, not "medium"."""
    raw = client.answer_value(_score_answer(1.2))
    assert raw == pytest.approx(1.2)
    assert not isinstance(raw, str)
    assert ts.score_to_level(raw, LEVELS) == "medium"


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, "low"),
        (0.4, "low"),
        (1.2, "medium"),
        (2.0, "high"),
        (3.0, "very-high"),
    ],
)
def test_score_maps_to_the_nearest_level(score: float, expected: str) -> None:
    assert ts.score_to_level(score, LEVELS) == expected


def test_an_exact_half_rounds_up_to_the_more_severe_level_at_every_boundary() -> None:
    """Under-stating blast radius is the costlier mistake, so halves round up.

    Both boundaries are asserted: Python's built-in `round` uses banker's
    rounding, so `round(0.5)` is 0 while `round(1.5)` is 2 -- a rule that held
    at one boundary and not the other.
    """
    assert ts.score_to_level(0.5, LEVELS) == "medium"
    assert ts.score_to_level(1.5, LEVELS) == "high"
    assert ts.score_to_level(2.5, LEVELS) == "very-high"


def test_a_score_outside_the_rubric_is_clamped_not_an_index_error() -> None:
    assert ts.score_to_level(-4.0, LEVELS) == "low"
    assert ts.score_to_level(99.0, LEVELS) == "very-high"


def test_an_unusable_score_maps_to_nothing_rather_than_guessing() -> None:
    assert ts.score_to_level(None, LEVELS) is None
    assert ts.score_to_level("high", LEVELS) is None
    assert ts.score_to_level(1.0, ()) is None


# --------------------------------------------------------------------------- #
# shape_suggestions
# --------------------------------------------------------------------------- #


def test_agreement_carries_the_distribution_and_is_not_an_override() -> None:
    shaped = ts.shape_suggestions(
        {ts.QUESTION_TYPE: TYPE_ANSWER},
        client=client,
        chosen_type="enhancement",
        risk_levels=LEVELS,
    )

    entry = shaped[ts.QUESTION_TYPE]
    assert entry["suggested"] == "enhancement"
    assert entry["overridden"] is False
    assert sum(entry["distribution"].values()) == pytest.approx(1.0)
    assert set(entry["distribution"]) == set(sdlc_manager._ISSUE_TYPES)


def test_a_differing_flag_is_recorded_as_an_override_with_both_values() -> None:
    shaped = ts.shape_suggestions(
        {ts.QUESTION_TYPE: TYPE_ANSWER},
        client=client,
        chosen_type="defect",
        risk_levels=LEVELS,
    )

    entry = shaped[ts.QUESTION_TYPE]
    assert entry["overridden"] is True
    assert entry["suggested"] == "enhancement"
    assert entry["chosen"] == "defect"


def test_the_risk_entry_carries_both_the_raw_score_and_the_mapped_level() -> None:
    shaped = ts.shape_suggestions(
        {ts.QUESTION_RISK: _score_answer(1.2)},
        client=client,
        chosen_risk="medium",
        risk_levels=LEVELS,
    )

    entry = shaped[ts.QUESTION_RISK]
    assert entry["score"] == pytest.approx(1.2)
    assert entry["suggested"] == "medium"
    assert entry["overridden"] is False


def test_a_score_distribution_is_relabelled_from_indices_onto_level_names() -> None:
    """A live call returns a score distribution keyed by index, not by name.

    Observed running the command against a real card on 2026-09-19: the risk
    line rendered as `1 0.58, 0 0.25, 2 0.16, 3 0.01`. Every other question
    names its options, so unlabelled digits here are a reporting defect.
    """
    answer = dict(_score_answer(1.2))
    answer["probabilities"] = {"1": 0.58, "0": 0.25, "2": 0.16, "3": 0.01}

    shaped = ts.shape_suggestions(
        {ts.QUESTION_RISK: answer}, client=client, chosen_risk=None, risk_levels=LEVELS
    )

    assert shaped[ts.QUESTION_RISK]["distribution"] == {
        "medium": 0.58,
        "low": 0.25,
        "high": 0.16,
        "very-high": 0.01,
    }


def test_relabelling_keeps_an_out_of_range_key_rather_than_dropping_its_mass() -> None:
    assert ts.relabel_score_distribution({"0": 0.4, "9": 0.6}, LEVELS) == {"low": 0.4, "9": 0.6}
    assert ts.relabel_score_distribution({"high": 1.0}, LEVELS) == {"high": 1.0}


def test_a_rendered_risk_line_names_levels_not_digits() -> None:
    answer = dict(_score_answer(1.2))
    answer["probabilities"] = {"1": 0.58, "0": 0.25}
    shaped = ts.shape_suggestions({ts.QUESTION_RISK: answer}, client=client, risk_levels=LEVELS)

    line = "\n".join(ts.render_suggestions(shaped))

    assert "medium 0.58" in line
    assert "1 0.58" not in line


def test_an_unasked_question_says_so_rather_than_reporting_a_null_suggestion() -> None:
    shaped = ts.shape_suggestions({}, client=client, chosen_objective=None, risk_levels=LEVELS)

    entry = shaped[ts.QUESTION_OBJECTIVE]
    assert entry["asked"] is False
    assert entry["overridden"] is False
    assert "no candidates" in entry["reason"]


def test_a_low_confidence_answer_is_marked_but_still_shown() -> None:
    shaped = ts.shape_suggestions(
        {ts.QUESTION_TYPE: _choice_answer("defect", 0.31, {"defect": 0.31, "enhancement": 0.29})},
        client=client,
        chosen_type="defect",
        risk_levels=LEVELS,
    )

    entry = shaped[ts.QUESTION_TYPE]
    assert entry["low_confidence"] is True
    assert entry["suggested"] == "defect"


def test_a_yes_no_answers_confidence_is_its_distance_from_a_half_doubled() -> None:
    """The asymmetry `answer_confidence` exists to hide, asserted directly."""
    assert _noul_answer(0.05).get("confidence") is None
    assert client.answer_confidence(_noul_answer(0.05)) == pytest.approx(0.9)
    assert client.answer_confidence(_noul_answer(0.95)) == pytest.approx(0.9)


# --------------------------------------------------------------------------- #
# union_labels
# --------------------------------------------------------------------------- #


def test_the_union_tags_each_label_with_its_provenance() -> None:
    union = ts.union_labels(
        ["security"],
        {"performance": _noul_answer(0.91), "security": _noul_answer(0.88)},
        client=client,
    )

    by_label = {entry["label"]: entry["source"] for entry in union}
    assert by_label == {"security": ts.SOURCE_BOTH, "performance": ts.SOURCE_MODEL}
    assert len(union) == 2


def test_a_rule_label_survives_every_possible_model_answer() -> None:
    """Plan R14, proved over the answer space rather than one example.

    Widen-only is a property, not a case: for every combination of yes/no
    answers -- including all-no -- both rule-derived labels must still be there.
    """
    rules = ["security", "documentation"]
    probes = (0.0, 0.05, 0.59, 0.6, 0.99, 1.0)

    for combination in itertools.product(probes, repeat=len(ts.CONTENT_LABELS)):
        answers = {
            label: _noul_answer(probability)
            for label, probability in zip(ts.CONTENT_LABELS, combination, strict=True)
        }
        union = ts.union_labels(rules, answers, client=client)
        present = {entry["label"] for entry in union}
        assert set(rules) <= present


def test_a_confident_no_is_excluded_although_its_banding_confidence_is_high() -> None:
    """Plan R13a: the floor is the yes-probability, never `answer_confidence`.

    A 0.05 "no" bands at 0.90 through `answer_confidence`.  Thresholding that
    would add a label the model explicitly rejected, so this test fails the
    moment the wrong helper is substituted.
    """
    answer = _noul_answer(0.05)
    assert client.answer_confidence(answer) == pytest.approx(0.9)
    assert client.answer_confidence(answer) >= ts.DEFAULT_CONFIDENCE_FLOOR

    union = ts.union_labels([], {"security": answer}, client=client)

    assert union == []


def test_the_floor_is_inclusive_at_the_boundary() -> None:
    at_floor = ts.union_labels([], {"security": _noul_answer(0.6)}, client=client)
    below = ts.union_labels([], {"security": _noul_answer(0.5999)}, client=client)

    assert [entry["label"] for entry in at_floor] == ["security"]
    assert below == []


def test_a_malformed_or_missing_answer_never_adds_a_label() -> None:
    union = ts.union_labels(
        [],
        {"security": "yes please", "performance": {"type": "noul"}, "documentation": None},
        client=client,
    )

    assert union == []


def test_rule_labels_keep_their_order_and_are_not_duplicated() -> None:
    union = ts.union_labels(
        ["documentation", "security", "documentation"],
        {"documentation": _noul_answer(0.99)},
        client=client,
    )

    assert [entry["label"] for entry in union] == ["documentation", "security"]


# --------------------------------------------------------------------------- #
# candidate labels and rendering
# --------------------------------------------------------------------------- #


def test_the_candidate_set_holds_up_with_no_configured_rules() -> None:
    """Plan R14a: `auto_label_rules` is empty in the vendored schema."""
    assert ts.candidate_labels(()) == ts.CONTENT_LABELS
    assert "security" in ts.candidate_labels(())


def test_a_configured_rule_widens_the_candidate_set_without_duplicating() -> None:
    widened = ts.candidate_labels(["security", "flaky-test"])
    assert widened[-1] == "flaky-test"
    assert widened.count("security") == 1


def test_the_widening_never_asks_about_an_issue_type_label() -> None:
    """R14a: the labels path must not re-decide the issue type.

    The documented rules add type labels alongside content ones —
    `title_contains_capability` adds `capability` and `needs-analysis` — so a
    rules-only widening would hand the prepare path's judgment to the labels
    path.
    """
    exclude = sdlc_manager._label_widening_exclusions()
    widened = ts.candidate_labels(
        ["capability", "needs-analysis", "security", "flaky-test"], exclude=exclude
    )

    assert "capability" not in widened
    assert "needs-analysis" not in widened
    assert "security" in widened
    assert "flaky-test" in widened


def test_documentation_survives_the_exclusion_although_the_taxonomy_claims_it() -> None:
    """`documentation` is a content label in its own right, not a type label."""
    exclude = sdlc_manager._label_widening_exclusions()

    assert "documentation" not in exclude
    assert "documentation" in ts.candidate_labels((), exclude=exclude)


def test_every_issue_type_name_is_excluded_from_the_widening() -> None:
    exclude = sdlc_manager._label_widening_exclusions()
    assert set(sdlc_manager._ISSUE_TYPES) <= exclude


def test_label_questions_are_one_yes_no_each() -> None:
    questions = ts.label_questions(("security", "performance"))
    assert set(questions) == {"security", "performance"}
    assert all(question["type"] == "noul" for question in questions.values())
    assert "security" in questions["security"]["instructions"]


def test_rendering_names_the_override_and_the_distribution() -> None:
    shaped = ts.shape_suggestions(
        {ts.QUESTION_TYPE: TYPE_ANSWER},
        client=client,
        chosen_type="defect",
        risk_levels=LEVELS,
    )
    lines = "\n".join(ts.render_suggestions(shaped))

    assert "OVERRIDDEN" in lines
    assert "enhancement 0.82" in lines


def test_rendering_drops_zero_probability_options_and_counts_them() -> None:
    """A twenty-five-option status question printed twenty `0.00` entries live."""
    answer = _choice_answer(
        "Designing",
        0.9,
        {"Designing": 0.9, "Implementing": 0.1, "Closeout": 0.0, "Triage": 0.0},
    )
    shaped = ts.shape_suggestions({ts.QUESTION_STATUS: answer}, client=client, risk_levels=LEVELS)
    line = "\n".join(ts.render_suggestions(shaped))

    assert "Designing 0.90" in line
    assert "Closeout" not in line
    assert "(+2 at 0.00)" in line


def test_rendering_an_unasked_question_says_it_was_not_asked() -> None:
    shaped = ts.shape_suggestions({}, client=client, risk_levels=LEVELS)
    lines = "\n".join(ts.render_suggestions(shaped))

    assert "not asked" in lines


def test_the_union_renders_with_provenance() -> None:
    union = ts.union_labels(["security"], {}, client=client)
    assert ts.render_union(union) == ["  security (rule)"]
