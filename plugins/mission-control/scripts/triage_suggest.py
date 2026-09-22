"""Advisory triage judgments for mission-control (issue 1035, plan U1).

This module builds the typed questions mission-control asks about an issue body,
shapes the answers into the objects the prepared-issue sidecar carries, and
computes the widen-only label union.  It makes no call of its own: the caller
passes the fleet-core client's ``ask`` in, so nothing here reaches the network,
reads the environment, or touches a file.

Three properties this module exists to guarantee:

* **Nothing is applied.**  Every function returns data.  There is no code path
  from a model answer to a draft field, a label set, or a GitHub object -- the
  author's own flags stay the decision (plan KTD2).
* **The regular expressions are a floor.**  ``union_labels`` returns every
  rule-derived label for every possible model answer, so the model may widen the
  set and never narrow it (plan R14).
* **A yes/no answer is thresholded on its probability, never on its banding
  confidence.**  A confident "no" of 0.05 bands at 0.90 through
  ``answer_confidence``; thresholding that would add a label the model rejected
  (plan R13a).

The question set deliberately lives here rather than in fleet-core's verb
registry: the policy state it needs -- the issue-types reference, the board
Status vocabulary, the Objective candidates -- is mission-control's own data
(plan KTD1, DECISIONS ``{#1035-triage-questions-live-in-mission-control}``).
``test_triage_suggest.py`` guards that the two option sets cannot drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# The confidence floor every judgment in this module records (plan KTD7).  It
# matches the default on fleet-core's ``jev_verbs.Verb.confidence_floor`` and the
# research's measured 70 percent agreement at or above 0.6.  In the prepare path
# it is a CONFIDENCE floor and changes no behaviour, because nothing is applied;
# in the labels path the same number is a PROBABILITY floor and does decide
# whether a suggested label is printed.  The two readings are distinct on
# purpose -- see ``union_labels``.
DEFAULT_CONFIDENCE_FLOOR = 0.6

# The option a choice question offers when none of the real candidates fit.  The
# primitive has no "no match" of its own, so it is given one explicitly.
NO_MATCH = "none"

# Question keys.  These are the caller's join keys into the answer map; they are
# not sent to the model, which reads only the instructions and criteria.
QUESTION_TYPE = "issue_type"
QUESTION_RISK = "risk"
QUESTION_STATUS = "status"
QUESTION_OBJECTIVE = "objective"

# Provenance markers on a union entry.
SOURCE_RULE = "rule"
SOURCE_MODEL = "model"
SOURCE_BOTH = "both"

# The content labels the labels reference documents for the auto-label rules
# (plugins/mission-control/skills/labels/references/labels-reference.md:160-169).
# The issue-type labels those rules also apply are deliberately absent: the issue
# type is the prepare path's judgment, not the labels path's (plan R14a).
CONTENT_LABELS: tuple[str, ...] = (
    "security",
    "performance",
    "breaking-change",
    "documentation",
)

# Criteria written from this repository's actual practice rather than from the
# generic meaning of each word.  The research's clearest miss was a prose repair
# labelled `enhancement` that generic criteria classified `context-update` at
# full confidence -- in a skills repository prose IS behaviour, which a generic
# criterion does not say.  These sentences say it.
ISSUE_TYPE_CRITERIA: dict[str, str] = {
    "capability": (
        "a complete, independently deployable piece of functionality that does not exist "
        "yet; in this repository, a new plugin, a new command, or a new skill"
    ),
    "enhancement": (
        "improves something that already works, including changing the prose of a skill or "
        "reference document when that prose is what the agent executes -- in this "
        "repository instructions ARE behaviour, so rewriting them is an enhancement, not a "
        "documentation change"
    ),
    "defect": (
        "something is broken, wrong, or behaves against its own stated contract, and the "
        "work is to repair it"
    ),
    "exploration": (
        "an open question that must be researched before it can be planned; the deliverable "
        "is a finding or a recommendation, not a change"
    ),
    "context-update": (
        "documentation ABOUT the system that no agent executes -- a README, a changelog "
        "entry, an engineering-journal entry, or an analysis document"
    ),
}


def _choice(
    instructions: str, criteria: Mapping[str, str], policy: str | None = None
) -> dict[str, Any]:
    """A pick-one question with a full probability distribution over its options."""
    body: dict[str, Any] = {"type": "choice", "criteria": dict(criteria)}
    body["instructions"] = {"question": instructions, "policy": policy} if policy else instructions
    return body


def _score(instructions: str, levels: Sequence[str]) -> dict[str, Any]:
    """A position on an ordered rubric.  Returns a NUMBER, not a level name."""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def _noul(instructions: str) -> dict[str, Any]:
    """A yes/no question.  Returns a probability and carries no confidence field."""
    return {"type": "noul", "instructions": instructions}


def _bare_criteria(options: Iterable[str]) -> dict[str, str]:
    """Options whose names carry their own meaning need no criterion prose."""
    return dict.fromkeys(options, "")


def build_state(issue_text: str, policy_text: str = "") -> dict[str, Any]:
    """The named-JSON state the questions reference.

    It carries the issue's own text and, when supplied, the repository's
    issue-types policy document.  Nothing else: no environment, no transcript,
    no GitHub object.  The client's ``prepare_state`` redacts and truncates on
    the way out, so this function never redacts by hand (plan R17).
    """
    state: dict[str, Any] = {"issue": issue_text}
    if policy_text:
        state["policy"] = policy_text
    return state


def build_questions(
    *,
    issue_types: Sequence[str],
    risk_levels: Sequence[str],
    status_options: Sequence[str] = (),
    objective_options: Sequence[str] = (),
    policy_text: str = "",
) -> dict[str, Any]:
    """Every question about one draft, batched into one request (house rule 5).

    ``issue_types`` and ``risk_levels`` come from the caller's own constants --
    ``_ISSUE_TYPES`` and ``_RISK_TIER_VOCABULARY`` -- so a vocabulary change
    reaches the question without an edit here (plan R3).  A question whose
    option list is empty is omitted rather than asked with nothing to pick from.
    """
    if not issue_types:
        raise ValueError("build_questions needs at least one issue type to choose among")
    if not risk_levels:
        raise ValueError("build_questions needs at least one risk level to score against")

    criteria = {name: ISSUE_TYPE_CRITERIA.get(name, "") for name in issue_types}
    questions: dict[str, Any] = {
        QUESTION_TYPE: _choice(
            "Which issue type does `issue` describe?", criteria, policy_text or None
        ),
        QUESTION_RISK: _score(
            "How much blast radius does the change `issue` describes carry?", risk_levels
        ),
    }

    if status_options:
        questions[QUESTION_STATUS] = _choice(
            "Which board status has the work `issue` describes reached?",
            _bare_criteria(status_options),
        )

    if objective_options:
        questions[QUESTION_OBJECTIVE] = _choice(
            "Which objective does `issue` contribute to?",
            _bare_criteria([*objective_options, NO_MATCH]),
        )

    return questions


def label_questions(labels: Sequence[str]) -> dict[str, Any]:
    """One yes/no question per candidate label, batched into one request."""
    return {label: _noul(f"Does `issue` warrant the `{label}` label?") for label in labels}


def candidate_labels(
    rule_labels: Iterable[str] = (), *, exclude: Iterable[str] = ()
) -> tuple[str, ...]:
    """The labels the model is asked about (plan R14a).

    The documented content labels, widened by any label the configured rules
    carry.  It is NOT derived from the rules alone: ``auto_label_rules`` is empty
    in the vendored schema and the external ``labels.json`` may be absent, so a
    rules-only derivation would ask about nothing at all on a machine with no
    external checkout.

    ``exclude`` keeps the widening honest.  The configured rules also carry
    issue-TYPE labels (`title_contains_capability` adds `capability` and
    `needs-plan`), and widening with those would make the labels path ask the
    question the prepare path owns -- the split R14a states.  The caller passes
    the type and routing names; `documentation` is deliberately NOT among them,
    because it is a content label in its own right even though the taxonomy also
    pairs it with `context-update`.
    """
    blocked = set(exclude)
    ordered = [label for label in CONTENT_LABELS if label not in blocked]
    for label in rule_labels:
        if label not in ordered and label not in blocked:
            ordered.append(label)
    return tuple(ordered)


def _answer_value(client: Any, answer: Mapping[str, Any]) -> Any:
    return client.answer_value(answer)


def _answer_confidence(client: Any, answer: Mapping[str, Any]) -> float | None:
    return client.answer_confidence(answer)


def score_to_level(score: Any, levels: Sequence[str]) -> str | None:
    """Map a score answer's NUMBER onto one of its ordered levels (plan R3a).

    A score answer is ``{"type": "score", "score": 1.2, ...}`` -- a
    probability-weighted position, not a level name.  The nearest index wins, and
    a value exactly between two indices rounds UP to the more severe level: for a
    risk rubric the costlier mistake is under-stating blast radius.
    """
    if not levels:
        return None
    try:
        position = float(score)
    except (TypeError, ValueError):
        return None
    # `math.floor(x + 0.5)` rather than `round`, because Python's `round` uses
    # banker's rounding: `round(1.5)` is 2 but `round(0.5)` is 0, so an exact
    # half would resolve toward the SAFER level at one boundary and the more
    # severe one at the next.  The rule has to hold at every boundary.
    index = int((position + 0.5) // 1)
    index = max(0, min(index, len(levels) - 1))
    return levels[index]


def _suggestion(
    client: Any,
    answer: Mapping[str, Any] | None,
    *,
    chosen: Any,
    floor: float,
) -> dict[str, Any]:
    """The common shape: what the model said, what the author chose, and whether they differ."""
    if answer is None:
        return {
            "asked": False,
            "reason": "no candidates were offered, so the question was not asked",
            "chosen": chosen,
            "overridden": False,
        }
    suggested = _answer_value(client, answer)
    confidence = _answer_confidence(client, answer)
    return {
        "asked": True,
        "suggested": suggested,
        "distribution": dict(answer.get("probabilities") or {}),
        "confidence": confidence,
        "floor": floor,
        "low_confidence": confidence is not None and confidence < floor,
        "chosen": chosen,
        # The author's flag is the decision; a difference is the override.  An
        # absent chosen value is not a disagreement -- there was nothing to
        # disagree with.
        "overridden": chosen is not None and chosen != "" and chosen != suggested,
    }


def shape_suggestions(
    answers: Mapping[str, Any],
    *,
    client: Any,
    chosen_type: Any = None,
    chosen_risk: Any = None,
    chosen_status: Any = None,
    chosen_objective: Any = None,
    risk_levels: Sequence[str] = (),
    floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> dict[str, dict[str, Any]]:
    """Turn the client's answer map into the four suggestion objects.

    ``client`` is the fleet-core client module, used only for its
    ``answer_value`` / ``answer_confidence`` helpers.  Reading the answer
    dictionaries directly here would re-derive the yes/no asymmetry those
    helpers exist to hide (LEARNINGS ``{#jev-noul-has-no-confidence-1032}``).
    """
    chosen = {
        QUESTION_TYPE: chosen_type,
        QUESTION_RISK: chosen_risk,
        QUESTION_STATUS: chosen_status,
        QUESTION_OBJECTIVE: chosen_objective,
    }
    shaped: dict[str, dict[str, Any]] = {}
    for key, author_value in chosen.items():
        answer = answers.get(key)
        shaped[key] = _suggestion(
            client,
            answer if isinstance(answer, Mapping) else None,
            chosen=author_value,
            floor=floor,
        )

    risk = shaped[QUESTION_RISK]
    if risk.get("asked") and risk_levels:
        # A score answers with a number; the level it maps to is what an author
        # compares against `--risk`, so carry both (plan R3a).
        raw = risk.get("suggested")
        level = score_to_level(raw, risk_levels)
        risk["score"] = raw
        risk["suggested"] = level
        risk["levels"] = list(risk_levels)
        risk["overridden"] = bool(chosen_risk) and chosen_risk != level
        # A score's distribution comes back keyed by the level's INDEX, not by
        # its name -- a live call returns {"1": 0.58, "0": 0.25, ...}, which
        # renders as meaningless digits beside the named options of every other
        # question.  Relabel it.  (Found by running the command against a real
        # card; the recorded fixtures carried no score distribution at all.)
        risk["distribution"] = relabel_score_distribution(
            risk.get("distribution") or {}, risk_levels
        )

    return shaped


def relabel_score_distribution(
    distribution: Mapping[str, Any], levels: Sequence[str]
) -> dict[str, Any]:
    """Re-key a score distribution from level indices onto level names.

    An index outside the rubric is kept under its original key rather than
    dropped: losing probability mass silently would be worse than showing one
    unlabelled entry.
    """
    relabelled: dict[str, Any] = {}
    for key, value in distribution.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            relabelled[str(key)] = value
            continue
        if 0 <= index < len(levels):
            relabelled[levels[index]] = value
        else:
            relabelled[str(key)] = value
    return relabelled


def union_labels(
    rule_labels: Iterable[str],
    model_answers: Mapping[str, Any],
    *,
    client: Any,
    floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> list[dict[str, str]]:
    """The widen-only union of rule-matched and model-suggested labels.

    Every label in ``rule_labels`` appears in the result for every possible
    model answer -- the regular expressions are a floor the model can only widen
    (plan R14).  A model answer contributes only when its YES-PROBABILITY is at
    or above ``floor``: thresholding ``answer_confidence`` instead would admit a
    confident rejection, because a 0.05 "no" bands at 0.90 (plan R13a).
    """
    ordered: list[str] = []
    from_rules: set[str] = set()
    for label in rule_labels:
        if label not in ordered:
            ordered.append(label)
        from_rules.add(label)

    from_model: set[str] = set()
    for label, answer in model_answers.items():
        if not isinstance(answer, Mapping):
            continue
        probability = _answer_value(client, answer)
        if not isinstance(probability, (int, float)):
            continue
        if float(probability) < floor:
            continue
        from_model.add(label)
        if label not in ordered:
            ordered.append(label)

    result: list[dict[str, str]] = []
    for label in ordered:
        if label in from_rules and label in from_model:
            source = SOURCE_BOTH
        elif label in from_rules:
            source = SOURCE_RULE
        else:
            source = SOURCE_MODEL
        result.append({"label": label, "source": source})
    return result


def render_suggestions(suggestions: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Human-readable lines for the command's own output.  Applies nothing."""
    lines: list[str] = []
    for key in (QUESTION_TYPE, QUESTION_RISK, QUESTION_STATUS, QUESTION_OBJECTIVE):
        entry = suggestions.get(key)
        if not entry:
            continue
        if not entry.get("asked"):
            lines.append(f"  {key}: not asked ({entry.get('reason', 'no candidates')})")
            continue
        confidence = entry.get("confidence")
        shown = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "n/a"
        marker = " (OVERRIDDEN by your flag)" if entry.get("overridden") else ""
        lines.append(
            f"  {key}: {entry.get('suggested')} at confidence {shown}; "
            f"you chose {entry.get('chosen') or '(unset)'}{marker}"
        )
        distribution = entry.get("distribution") or {}
        if distribution:
            # Drop options the model gave no weight at all.  The board-status
            # question offers twenty-five options, and printing every one put
            # twenty `0.00` entries on screen for one real answer -- observed
            # running the command against a real card.  A distribution is shown
            # so the reader can see the competition; an option with no
            # probability is not competing.
            ranked = sorted(
                ((name, value) for name, value in distribution.items() if round(value, 2) > 0),
                key=lambda pair: pair[1],
                reverse=True,
            )
            hidden = len(distribution) - len(ranked)
            if ranked:
                spread = ", ".join(f"{name} {value:.2f}" for name, value in ranked)
                tail = f" (+{hidden} at 0.00)" if hidden else ""
                lines.append(f"      distribution: {spread}{tail}")
    return lines


def render_union(union: Sequence[Mapping[str, str]]) -> list[str]:
    """Human-readable lines for the labels union.  Applies nothing."""
    return [f"  {entry['label']} ({entry['source']})" for entry in union]


__all__: Sequence[str] = (
    "CONTENT_LABELS",
    "DEFAULT_CONFIDENCE_FLOOR",
    "ISSUE_TYPE_CRITERIA",
    "NO_MATCH",
    "QUESTION_OBJECTIVE",
    "QUESTION_RISK",
    "QUESTION_STATUS",
    "QUESTION_TYPE",
    "SOURCE_BOTH",
    "SOURCE_MODEL",
    "SOURCE_RULE",
    "build_questions",
    "build_state",
    "candidate_labels",
    "label_questions",
    "relabel_score_distribution",
    "render_suggestions",
    "render_union",
    "score_to_level",
    "shape_suggestions",
    "union_labels",
)
