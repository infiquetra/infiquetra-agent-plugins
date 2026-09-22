#!/usr/bin/env python3
"""Typed judgments for the three shaping commands (issue 1037, plan U1-U4).

`/ideate`, `/brainstorm` and `/office-hours` each make several small repeated
judgments per run that an orchestrating model makes today by reading prose.
This module asks those judgments as typed questions -- a yes/no probability, a
pick from a fixed set, or a position on an ordered rubric -- batched one request
per body of text, through the fleet-core TypeSafe client that issue 1032
shipped.  There is no HTTP code here, no retry code, no redaction code and no
second client: `typesafe_client.ask` owns all of that, and its `prepare_state`
is the only path to a transport, so redaction cannot be skipped from here.

Every answer is advisory.  Nothing in this module returns an instruction,
selects an option on a caller's behalf, or removes anything from its input: the
dedupe judgment *groups*, and the set of identifiers coming out equals the set
going in.  Every judgment fails open -- on a non-`ok` status, an absent
`TYPESAFE_API_KEY`, a timeout, or a declined judgment the caller behaves exactly
as it did before this module existed, and the command-line front door still
exits zero, because a failed advisory call is not a failed command.

    shaping_judgments.py readiness --doc docs/brainstorms/<a requirements doc>.md
    shaping_judgments.py dedupe --state '{"candidates": [{"id": "C1", ...}]}'
    shaping_judgments.py route --doc <a frame note> --log

Verdicts are recorded only for calls that produced an answer, which is what
`plugins/fleet-core/scripts/jev.py` does: the evaluation harness scores answers,
and a declined or failed judgment has no answer to score.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import bundled_fleet  # noqa: E402  (after the sys.path shim, by design)

typesafe_client = bundled_fleet.load("typesafe_client")
jev_log = bundled_fleet.load("jev_log")

# The floor comes from fleet-core rather than a number invented here, for the
# reason jev_verbs.py's own docstring gives: every caller reads the same number.
# The evaluation harness sets the real ones once a decision has real uses.
DEFAULT_CONFIDENCE_FLOOR = 0.6

# Ideate's volume ceiling: six frames at roughly eight candidates each, plus
# three to five cross-cutting combinations and at most two recovery frames of
# three to five ideas.  Above this the dedupe judgment declines and the skill
# merges the way it does today -- an unbounded pairwise fan-out inside an
# interactive command is the failure this cap prevents.
DEDUPE_CANDIDATE_CAP = 64

# Pairs per request.  Independent questions about one state travel together, so
# the cap's 2,016 pairs cost 17 requests rather than 2,016 -- roughly seven
# seconds at the measured 330 to 430 milliseconds per call, instead of thirteen
# minutes.  The number is bounded by the client's own state budget, which
# truncates rather than fails, so it stays well under it.
DEDUPE_PAIRS_PER_REQUEST = 120

STATE_DOC = "doc"
STATE_JSON = "json"

# Brainstorm's consequence factors, verbatim from its Phase 0.5 prose.  The
# guard test binds this list to the six phrases
# tests/test_brainstorm_judgment_contract.py::check_consequence_factors already
# pins into the skill, so a rename in either place reds rather than drifting.
CONSEQUENCE_FACTORS: tuple[tuple[str, str], ...] = (
    ("data_sensitivity", "data sensitivity"),
    ("granted_authority", "granted authority"),
    ("untrusted_input", "exposure to untrusted input"),
    ("blast_radius", "reversibility and blast radius"),
    ("recovery_expectations", "recovery expectations"),
    ("auditability_consent", "auditability or consent obligations"),
)

# The readiness criteria, each drawn from the requirements-section contract at
# plugins/saga/skills/brainstorm/references/requirements-sections.md.
READINESS_CRITERIA: tuple[tuple[str, str], ...] = (
    (
        "summary_proposes",
        "Does the document's Summary state what is being proposed, rather than restating "
        "the problem?",
    ),
    (
        "requirements_specific",
        "Are the requirements specific enough that a planner could plan them without "
        "inventing behaviour?",
    ),
    (
        "acceptance_examples",
        "Does every conditional or state-dependent requirement carry an acceptance example?",
    ),
    ("scope_named", "Does the document name what is out of scope?"),
    (
        "assumptions_surfaced",
        "Are the material dependencies and load-bearing assumptions surfaced?",
    ),
    (
        "no_blocking_questions",
        "Is every 'Resolve before planning' question closed?",
    ),
    (
        "plannable_cold",
        "Could a planner reading this cold proceed without asking the operator anything?",
    ),
)

# Ideate's per-idea survivor rubric dimensions.  Axis spread is deliberately
# absent: the convergence reference calls it "a list-level concern, not
# per-idea", so scoring it per survivor would answer a question the rubric does
# not ask.
RUBRIC_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("groundedness", "how well grounded the idea is in the stated context"),
    (
        "basis_strength",
        "the strength of the idea's basis: direct evidence beats external, which beats reasoned",
    ),
    ("expected_value", "the value the idea would deliver if built"),
    ("novelty", "how far the idea goes beyond the obvious move"),
    ("pragmatism", "how realistically the idea can be carried out here"),
    ("leverage", "how much the idea compounds into future work"),
    ("burden", "how heavy the idea is to implement"),
    ("overlap", "how far the idea is already covered by a stronger idea"),
)

# The ordered levels every score question uses.  Deliberately NOT
# "low"/"medium"/"high": those are a strict subset of the fleet's effort ladder
# in tier_palette.py, and a bare tuple of them in a saga script is
# indistinguishable from a truncated re-declaration of it --
# tests/test_tier_vocab_single_source.py flags exactly that, correctly.  These
# words also stand on their own better as rubric positions, which is what the
# vendor asks score levels to do.
RUBRIC_LEVELS = ("weak", "moderate", "strong")

GROUNDING_FIT_OUTCOMES = {
    "proceed": (
        "clearly groundable -- the idea is bound to grounding that is actually reachable, "
        "such as the current repository or named repositories"
    ),
    "decline": "out of the engineering domain -- there is no infiquetra subject to ground against",
    "office_hours": "unframed -- no settled subject, so the frame has to be found first",
    "surface_mismatch": (
        "broad relative to the available grounding but still an infiquetra subject -- "
        "the mismatch should be surfaced to the operator"
    ),
}

SCOPE_TIERS = {
    "lightweight": "small, well bounded, low ambiguity",
    "standard": "a normal feature or bounded refactor with real decisions to make",
    "deep-feature": (
        "cross-cutting or ambiguous, but the existing product shape anchors the decisions"
    ),
    "deep-product": (
        "the brainstorm must establish product shape: actors, core outcome, positioning "
        "or primary flows are materially unresolved"
    ),
}

OFFICE_HOURS_ROUTES = {
    "ideate": "the frame is settled but the solution space is open; many candidate ideas are wanted",
    "brainstorm": "this is really a requirements question about one chosen thing",
    "plan": "the problem and the approach are already clear enough to plan directly",
    "strategy": "this is a direction question about where the organisation is pointed",
    "drop": "the diagnostic showed the thing is not worth pursuing",
}


class ShapingJudgmentError(RuntimeError):
    """A caller-visible problem with a judgment request."""


def _noul(question: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": question}


def _choice(question: str, criteria: Mapping[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": question, "criteria": dict(criteria)}


def _score(question: str, levels: Sequence[str] = RUBRIC_LEVELS) -> dict[str, Any]:
    return {"type": "score", "instructions": question, "criteria": list(levels)}


@dataclass(frozen=True)
class Judgment:
    """One advisory judgment point: declarative data, not a code branch."""

    name: str
    command: str
    summary: str
    state_kind: str
    state_help: str
    questions: dict[str, Any] = field(default_factory=dict)
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR

    def question_set(self) -> dict[str, Any]:
        return {key: dict(value) for key, value in self.questions.items()}


JUDGMENTS: dict[str, Judgment] = {
    # ---- /ideate -----------------------------------------------------------
    "dedupe": Judgment(
        name="dedupe",
        command="/ideate",
        summary="Which generated candidates are the same idea (groups; never drops)",
        state_kind=STATE_JSON,
        state_help='the candidate list, as {"candidates": [{"id": "C1", "text": "..."}]}',
        questions={
            "same": _noul("Do `left` and `right` describe the same underlying idea?"),
        },
    ),
    "axis": Judgment(
        name="axis",
        command="/ideate",
        summary="Which topic axis a candidate most centrally targets",
        state_kind=STATE_JSON,
        state_help='the candidate and the axis list, as {"candidate": "...", "axes": [...]}',
        questions={},  # built per call from the supplied axis list
    ),
    "grounding-fit": Judgment(
        name="grounding-fit",
        command="/ideate",
        summary="Which of the four grounding-fit outcomes the topic falls into",
        state_kind=STATE_JSON,
        state_help='the topic and grounding summary, as {"topic": "...", "grounding": "..."}',
        questions={
            "outcome": _choice(
                "Which grounding-fit outcome does `topic` fall into, given `grounding`?",
                GROUNDING_FIT_OUTCOMES,
            ),
        },
    ),
    "tactical-scope": Judgment(
        name="tactical-scope",
        command="/ideate",
        summary="Whether the focus opts into tactical scope (union with the keyword floor)",
        state_kind=STATE_JSON,
        state_help='the focus hint, as {"focus": "..."}',
        questions={
            "tactical": _noul(
                "Does `focus` ask for tactical work -- polish, typos, quick wins, cleanup, "
                "small fixes, or one narrow file -- rather than an ambitious change?"
            ),
        },
    ),
    "rubric": Judgment(
        name="rubric",
        command="/ideate",
        summary="Per-survivor rubric scores beside the critics' prose verdicts",
        state_kind=STATE_JSON,
        state_help='the survivor, as {"idea": "...", "context": "..."}',
        questions={
            key: _score(f"Rate `idea` on {description}.") for key, description in RUBRIC_DIMENSIONS
        },
    ),
    "revival": Judgment(
        name="revival",
        command="/ideate",
        summary="Whether new evidence addresses a cut idea's recorded rejection reason",
        state_kind=STATE_JSON,
        state_help='as {"idea": "...", "rejection_reason": "...", "new_evidence": "..."}',
        questions={
            "addresses": _noul(
                "Does `new_evidence` address the specific objection in `rejection_reason`, "
                "rather than restating the case for `idea`?"
            ),
        },
    ),
    # ---- /brainstorm -------------------------------------------------------
    "scope-tier": Judgment(
        name="scope-tier",
        command="/brainstorm",
        summary="Which scope tier the work sits in",
        state_kind=STATE_DOC,
        state_help="the seed and scan summary, as JSON, or --doc",
        questions={
            "tier": _choice("Which scope tier does this work sit in?", SCOPE_TIERS),
        },
    ),
    "consequence": Judgment(
        name="consequence",
        command="/brainstorm",
        summary="Which consequence factors are actually present in scope",
        state_kind=STATE_DOC,
        state_help="the seed and scan summary, as JSON, or --doc",
        questions={
            key: _noul(f"Is {phrase} a real consideration in the work described?")
            for key, phrase in CONSEQUENCE_FACTORS
        },
    ),
    "question-order": Judgment(
        name="question-order",
        command="/brainstorm",
        summary="How consequential and how uncertain a candidate question is",
        state_kind=STATE_JSON,
        state_help='the candidate question and its context, as {"question": "...", '
        '"context": "..."}',
        questions={
            "consequence": _score(
                "How much would the answer to `question` change scope, acceptance behaviour, "
                "or the safeguards the work needs?"
            ),
            "uncertainty": _score(
                "How uncertain is the answer to `question` from what is already known here?"
            ),
        },
    ),
    "readiness": Judgment(
        name="readiness",
        command="/brainstorm",
        summary="Whether a requirements document is ready for the doc-review handoff",
        state_kind=STATE_DOC,
        state_help="the requirements document, as --doc <path>",
        questions={key: _noul(question) for key, question in READINESS_CRITERIA},
    ),
    # ---- /office-hours -----------------------------------------------------
    "route": Judgment(
        name="route",
        command="/office-hours",
        summary="Which next command the settled frame points to (distribution only)",
        state_kind=STATE_DOC,
        state_help="the settled frame -- the real problem and the key assumptions -- as --doc",
        questions={
            "route": _choice(
                "Which next command does this settled frame point to?", OFFICE_HOURS_ROUTES
            ),
        },
    ),
}


def judgment_names() -> tuple[str, ...]:
    return tuple(sorted(JUDGMENTS))


def _default_ask() -> Callable[..., Any]:
    return typesafe_client.ask


def _advisory(
    *,
    name: str,
    ok: bool,
    note: str,
    answers: Mapping[str, Any] | None = None,
    model: str = "",
    floor: float | None = None,
) -> dict[str, Any]:
    """The result envelope every judgment returns.

    It carries the answers, each answer's confidence, and whether that
    confidence cleared the floor.  It deliberately carries no aggregate, no
    verdict and no selected action: an advisory judgment informs a decision the
    caller already makes, and code owns control flow.
    """
    resolved: dict[str, Any] = {}
    for key, answer in (answers or {}).items():
        confidence = typesafe_client.answer_confidence(answer)
        resolved[key] = {
            "value": typesafe_client.answer_value(answer),
            "confidence": confidence,
            "floor_met": None if confidence is None or floor is None else confidence >= floor,
            "answer": dict(answer),
        }
    return {
        "judgment": name,
        "advisory": True,
        "ok": ok,
        "note": note,
        "model": model,
        "confidence_floor": floor,
        "answers": resolved,
    }


def judge(
    state: Any,
    name: str,
    *,
    ask: Callable[..., Any] | None = None,
    questions: Mapping[str, Any] | None = None,
    log: bool = False,
    log_dir: Any = None,
) -> dict[str, Any]:
    """Ask one judgment's whole question set about ``state`` in one request.

    ``ask`` is the injection seam -- every test passes a fake, so no test
    touches the network.  ``questions`` overrides the registry's set for the
    judgments whose questions are built per call from caller-supplied options.
    """
    if name not in JUDGMENTS:
        raise ShapingJudgmentError(f"no such judgment: {name}")
    judgment = JUDGMENTS[name]
    question_set = dict(questions) if questions is not None else judgment.question_set()
    if not question_set:
        raise ShapingJudgmentError(f"the {name} judgment needs its questions built for this call")
    if _is_empty_state(state):
        return _advisory(
            name=name,
            ok=False,
            note="the state is empty, so there is nothing to judge; nothing was asked",
            floor=judgment.confidence_floor,
        )

    caller = ask if ask is not None else _default_ask()
    result = caller(state, question_set)

    status = getattr(result, "status", typesafe_client.STATUS_ERROR)
    if status != typesafe_client.STATUS_OK:
        note = getattr(result, "note", "") or f"the request failed with status {status}"
        return _advisory(name=name, ok=False, note=note, floor=judgment.confidence_floor)

    answers = dict(getattr(result, "answers", {}) or {})
    model = str(getattr(result, "model", "") or "")
    if log:
        # Only an answered call is logged, the way jev.py logs: the evaluation
        # harness scores answers, and a declined or failed judgment has none.
        #
        # Recording is best-effort by design.  An unwritable log directory is a
        # problem with the fleet's measurement, not with the judgment the
        # caller asked for, and an advisory call that takes down a
        # conversational command because a log write failed is the opposite of
        # failing open.
        for key, answer in answers.items():
            # jev_log wraps an unwritable log in RuntimeError rather than
            # letting the OSError through, so suppressing OSError alone would
            # miss the very failure this guard exists for.
            with contextlib.suppress(OSError, RuntimeError):
                jev_log.record_verdict(
                    decision_id=f"{judgment.command}:{name}:{key}",
                    state=state,
                    questions=question_set,
                    answer=answer,
                    confidence=typesafe_client.answer_confidence(answer),
                    threshold=judgment.confidence_floor,
                    resolved_model=model,
                    directory=log_dir,
                )
    return _advisory(
        name=name,
        ok=True,
        note="",
        answers=answers,
        model=model,
        floor=judgment.confidence_floor,
    )


def _is_empty_state(state: Any) -> bool:
    if state is None:
        return True
    if isinstance(state, str):
        return not state.strip()
    if isinstance(state, (list, tuple, dict, set)):
        return not state
    return False


def axis_questions(axes: Sequence[str]) -> dict[str, Any]:
    """The axis-coverage question, built from the run's own axis list.

    The "none" option is deliberate: a candidate that fits no axis should be
    visible as such rather than forced onto the nearest one, because the
    recovery frame is supposed to fire on real gaps.
    """
    named = [axis for axis in axes if str(axis).strip()]
    if len(named) < 2:
        raise ShapingJudgmentError("axis coverage needs at least two axes")
    criteria = {str(axis): f"the candidate most centrally targets {axis}" for axis in named}
    criteria["none"] = "the candidate fits none of the listed axes"
    return {"axis": _choice("Which axis does `candidate` most centrally target?", criteria)}


# Ideate's own tactical-scope keyword list, verbatim from its Phase 0.4.  It is
# the FLOOR: the judgment may only add a detection, never remove one, so the
# union below is code rather than a wish written in prose.
TACTICAL_KEYWORDS: tuple[str, ...] = (
    "polish",
    "typo",
    "typos",
    "quick wins",
    "small improvements",
    "cleanup",
    "small fixes",
)


def tactical_scope_union(
    focus: str,
    *,
    ask: Callable[..., Any] | None = None,
    threshold: float = 0.5,
    log: bool = False,
    log_dir: Any = None,
) -> dict[str, Any]:
    """Tactical scope: the keyword floor, widened by the judgment, never narrowed."""
    lowered = (focus or "").lower()
    by_keyword = [word for word in TACTICAL_KEYWORDS if word in lowered]
    result = judge({"focus": focus}, "tactical-scope", ask=ask, log=log, log_dir=log_dir)
    by_judgment = False
    if result["ok"]:
        probability = result["answers"].get("tactical", {}).get("value")
        by_judgment = isinstance(probability, (int, float)) and float(probability) > threshold
    result["keyword_hits"] = by_keyword
    result["by_judgment"] = by_judgment
    result["tactical"] = bool(by_keyword) or by_judgment
    return result


def _pairs(identifiers: Sequence[str]) -> list[tuple[str, str]]:
    return [
        (identifiers[i], identifiers[j])
        for i in range(len(identifiers))
        for j in range(i + 1, len(identifiers))
    ]


def _dedupe_batch(
    chunk: Sequence[tuple[str, str]], text_of: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, tuple[str, str]]]:
    """Build one request covering many pairs.

    Every candidate a chunk mentions is carried once in the state, and each
    question references two of them by the vendor's documented backticked path
    form.  One question per pair, one request per chunk -- not one request per
    pair, which at the cap would be 2,016 sequential calls inside a
    conversational command.
    """
    ordered: list[str] = []
    position: dict[str, int] = {}
    for left, right in chunk:
        for identifier in (left, right):
            if identifier not in position:
                position[identifier] = len(ordered)
                ordered.append(identifier)
    state = {"items": [{"id": identifier, "text": text_of[identifier]} for identifier in ordered]}
    questions: dict[str, Any] = {}
    index_of: dict[str, tuple[str, str]] = {}
    for number, (left, right) in enumerate(chunk):
        key = f"pair_{number}"
        questions[key] = _noul(
            f"Do `items[{position[left]}].text` and `items[{position[right]}].text` "
            "describe the same underlying idea?"
        )
        index_of[key] = (left, right)
    return state, questions, index_of


def dedupe_groups(
    candidates: Sequence[Mapping[str, Any]],
    *,
    ask: Callable[..., Any] | None = None,
    threshold: float = 0.5,
    cap: int = DEDUPE_CANDIDATE_CAP,
    log: bool = False,
    log_dir: Any = None,
) -> dict[str, Any]:
    """Group candidates that describe the same idea.  Never removes one.

    Every identifier that enters appears in exactly one output group, and a
    group of one is a normal result -- the guard test asserts the identifier set
    coming out equals the set going in.  That is what keeps ideate's stated
    quality mechanism intact: explicit rejection with reasons, never a silent
    drop by a probability.
    """
    entries = [dict(candidate) for candidate in candidates]
    identifiers = [str(entry.get("id") or "") for entry in entries]
    if not entries:
        return {
            "judgment": "dedupe",
            "advisory": True,
            "ok": False,
            "note": "no candidates were supplied; nothing was asked",
            "groups": [],
        }
    if "" in identifiers or len(set(identifiers)) != len(identifiers):
        raise ShapingJudgmentError("every candidate needs a distinct, non-empty id")
    if len(entries) > cap:
        return {
            "judgment": "dedupe",
            "advisory": True,
            "ok": False,
            "note": (
                f"not judged: {len(entries)} candidates is above the cap of {cap}; "
                "merge the way the skill does today"
            ),
            "groups": [[identifier] for identifier in identifiers],
        }

    text_of = {str(entry["id"]): str(entry.get("text") or "") for entry in entries}
    parent = {identifier: identifier for identifier in identifiers}

    def _find(identifier: str) -> str:
        while parent[identifier] != identifier:
            parent[identifier] = parent[parent[identifier]]
            identifier = parent[identifier]
        return identifier

    def _union(left: str, right: str) -> None:
        left_root, right_root = _find(left), _find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    all_pairs = _pairs(identifiers)
    requests = 0
    judged = 0
    unjudged = 0
    for start in range(0, len(all_pairs), DEDUPE_PAIRS_PER_REQUEST):
        chunk = all_pairs[start : start + DEDUPE_PAIRS_PER_REQUEST]
        state, questions, index_of = _dedupe_batch(chunk, text_of)
        result = judge(state, "dedupe", ask=ask, questions=questions, log=log, log_dir=log_dir)
        requests += 1
        if not result["ok"]:
            unjudged += len(chunk)
            continue
        for key, (left, right) in index_of.items():
            same = result["answers"].get(key, {}).get("value")
            if not isinstance(same, (int, float)):
                unjudged += 1
                continue
            judged += 1
            if float(same) > threshold:
                _union(left, right)

    grouped: dict[str, list[str]] = {}
    for identifier in identifiers:
        grouped.setdefault(_find(identifier), []).append(identifier)
    groups = [grouped[root] for root in sorted(grouped, key=identifiers.index)]
    # An answered-nothing run must not report itself as a judgment.  Under-
    # grouping caused by a partial outage looks exactly like a real answer, so
    # the count of pairs nobody judged travels with the result and a run that
    # judged none of them is not `ok`.
    note = ""
    if unjudged:
        note = f"{unjudged} of {len(all_pairs)} pairs were not judged; they were left ungrouped"
    return {
        "judgment": "dedupe",
        "advisory": True,
        "ok": judged > 0,
        "note": note or ("no pair was judged" if not judged else ""),
        "requests": requests,
        "pairs_judged": judged,
        "pairs_unjudged": unjudged,
        "groups": groups,
    }


def _read_state(args: argparse.Namespace) -> Any:
    given = [flag for flag in (args.doc, args.state, args.state_file) if flag is not None]
    if len(given) > 1:
        raise ShapingJudgmentError("pass exactly one of --doc, --state or --state-file")
    if args.doc is not None:
        path = Path(args.doc)
        if not path.is_file():
            raise ShapingJudgmentError(f"no such document: {path}")
        return path.read_text(encoding="utf-8")
    raw: str | None = None
    if args.state_file is not None:
        path = Path(args.state_file)
        if not path.is_file():
            raise ShapingJudgmentError(f"no such state file: {path}")
        raw = path.read_text(encoding="utf-8")
    elif args.state is not None:
        raw = args.state
    if raw is None:
        raise ShapingJudgmentError("a state is required; pass --doc, --state or --state-file")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        source = "--state-file" if args.state_file else "--state"
        raise ShapingJudgmentError(f"{source} is not valid JSON: {exc}") from None


def _emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shaping_judgments",
        description="Advisory typed judgments for /ideate, /brainstorm and /office-hours.",
    )
    sub = parser.add_subparsers(dest="judgment", required=True)
    for name in judgment_names():
        judgment = JUDGMENTS[name]
        target = sub.add_parser(
            name, help=f"{judgment.command}: {judgment.summary} ({judgment.state_help})"
        )
        target.add_argument("--doc", help="a file whose text is the state")
        target.add_argument("--state", help="the state as an inline JSON document")
        target.add_argument("--state-file", help="a file holding the state as JSON")
        target.add_argument("--log", action="store_true", help="append to the verdict log")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        state = _read_state(args)
        if args.judgment == "dedupe":
            candidates = state.get("candidates") if isinstance(state, dict) else state
            payload: Any = dedupe_groups(candidates or [], log=args.log)
        elif args.judgment == "tactical-scope":
            focus = state.get("focus") if isinstance(state, dict) else state
            payload = tactical_scope_union(str(focus or ""), log=args.log)
        elif args.judgment == "axis":
            if not isinstance(state, dict):
                raise ShapingJudgmentError("axis coverage needs a JSON object state")
            payload = judge(
                state, "axis", questions=axis_questions(state.get("axes") or []), log=args.log
            )
        else:
            payload = judge(state, args.judgment, log=args.log)
    except ShapingJudgmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _emit(payload)
    # Zero even when the judgment declined or the call failed: every judgment
    # here is advisory, and a failed advisory call is not a failed command.
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__: Sequence[str] = (
    "CONSEQUENCE_FACTORS",
    "DEDUPE_CANDIDATE_CAP",
    "DEFAULT_CONFIDENCE_FLOOR",
    "JUDGMENTS",
    "READINESS_CRITERIA",
    "RUBRIC_DIMENSIONS",
    "TACTICAL_KEYWORDS",
    "Judgment",
    "ShapingJudgmentError",
    "axis_questions",
    "dedupe_groups",
    "judge",
    "judgment_names",
    "main",
    "tactical_scope_union",
)
