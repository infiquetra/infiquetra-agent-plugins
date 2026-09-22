#!/usr/bin/env python3
"""Write ``review_result.v2`` into the run record, and publish it as one comment.

WHAT THIS MODULE OWNS
=====================

Serialising a review result, giving every finding one stable identity, keeping one
review history per unit, preparing the residual defects when the repair allowance
runs out, and rendering the result as exactly one pull-request comment. Filing
those defects is mission-control's, not this module's: opening an issue is that
plugin's ownership lane. It owns no policy: what
a lens means, what threshold it must reach and what shape acceptance takes all come
from the roster :mod:`review_roster` resolved, and the verdict itself is computed
by :mod:`review_consensus`.

FINDING IDENTITY
================

The lifecycle repository's catalogue gives every finding one fingerprint — path,
line and category — that survives across cycles, so the same defect keeps one
identity however many lenses report it. Two reviewers reporting the same defect
produce **one** finding with the agreement recorded, not two. A duplicate is
recorded ``duplicate-of`` against the finding it repeats: not deleted, and not
counted twice. Similar wording is not evidence of the same defect, so wording is
not part of the fingerprint.

ONE HISTORY PER UNIT
====================

A unit has one review history for the life of the run. Starting a fresh one is
refused, because a fresh history resets the cycle counter and puts scores from two
different lens sets side by side as though they were comparable. That is the whole
of issue 946.

ONE COUNTER PER LOOP
====================

A run has two repair loops — the pre-merge code-review loop and the post-merge
repair loop — and each keeps its **own** allowance and its own count under the same
rules. Every entry therefore carries a ``loop`` field valued ``code_review`` or
``post_merge``, and the allowance check counts entries whose loop matches rather
than the array's length. Without the field a long testing phase would silently
spend the pre-merge budget.

READING AN OLDER RESULT
=======================

A ``review_result.v1`` entry already in a record is reported by name, preserved
unchanged, and counted toward no allowance: its cycle accounting used a different
acceptance rule and is not comparable to this one. Silently upgrading it would put
incomparable scores in one history, which is the thing above this one exists to
prevent.

PUBLICATION
===========

Exactly one pull-request comment, naming the reviewed revision as a full
forty-character commit identifier. **Never an approving review**, in any of its
forms. Publication commits nothing, pushes nothing, and does not advance ``HEAD`` —
issue 935 reports the opposite arrangement, where publishing the artifact moved the
branch and broke the caller's freshness check.

Publication lives in this module rather than a fourth script because issue 1001
names exactly three, and because binding the comment to the result it renders is
what makes it impossible to publish a comment naming a revision other than the one
the result records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess  # nosec B404 — fixed argv, no shell
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_record  # noqa: E402

RESULT_SCHEMA = "review_result.v2"
LEGACY_RESULT_SCHEMA = "review_result.v1"

#: The two repair loops, each with its own allowance and its own counter.
LOOP_CODE_REVIEW = "code_review"
LOOP_POST_MERGE = "post_merge"
LOOPS = (LOOP_CODE_REVIEW, LOOP_POST_MERGE)

#: The catalogue's status vocabulary. Eight values, and no others.
STATUS_VOCABULARY = (
    "open",
    "fixed-verified",
    "unresolved",
    "disputed",
    "out-of-scope",
    "evidence-gap",
    "withdrawn",
    "duplicate-of",
)

#: The catalogue's severity vocabulary.
SEVERITY_VOCABULARY = ("P0", "P1", "P2", "P3")

#: The catalogue's severity anchors, least severe first, quoted from
#: ``SDLC/config/lens-catalogue.json`` ``finding_schema.severity_vocabulary``.
#: The order is the score scale: position 0 is P3, position 3 is P0. The drift
#: test in ``tests/test_review_judgments.py`` re-reads the catalogue when a
#: lifecycle checkout is present and fails on a rewording.
SEVERITY_ANCHORS: tuple[tuple[str, str], ...] = (
    ("P3", "Real, but nothing a user or an operator can observe changes because of it."),
    ("P2", "A defect whose effect is bounded or conditional."),
    ("P1", "A real defect on a path the revision ships."),
    ("P0", "The revision is unsafe to merge as written."),
)
SEVERITY_LEVELS: tuple[str, ...] = tuple(level for level, _ in SEVERITY_ANCHORS)
SEVERITY_RANK: dict[str, int] = {level: rank for rank, level in enumerate(SEVERITY_LEVELS)}

#: The probability at or above which two candidate findings are grouped as one defect.
DEDUPE_THRESHOLD = 0.5

#: Pairs judged per request. Independent questions about one state travel
#: together, so a full cap costs two requests rather than hundreds of calls.
DEDUPE_PAIRS_PER_REQUEST = 120

#: The most candidate pairs one call judges. Above this the call declines and
#: leaves every finding ungrouped: an unbounded pairwise fan-out inside a review
#: result is the failure this cap prevents.
DEDUPE_PAIR_CAP = 240

#: Mirrors ``typesafe_client.STATUS_OK`` so the injected-``ask`` path interprets
#: answers without importing the client. A one-word string, not behaviour.
_STATUS_OK = "ok"

#: The catalogue's four persistent-finding classifications (operator decision C6).
CLASSIFICATION_VOCABULARY = (
    "out-of-scope",
    "repairable-first",
    "evidence-gap",
    "disputed",
)

#: A full commit identifier. An abbreviation or a symbolic ref stops meaning
#: anything once the branch moves, so neither is accepted as a reviewed revision.
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_UNKNOWN_VERSION = 3


class ReviewResultError(ValueError):
    """A refusal this module owns. The command line maps it to exit 2."""


class HistoryConflictError(ReviewResultError):
    """A second review history was requested for a unit that already has one."""


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def fingerprint(path: str, line: int | str, category: str) -> str:
    """The catalogue's finding identity: a fingerprint of path, line and category.

    Stable across cycles, so the same defect keeps one identity. Wording is
    deliberately excluded: two findings worded alike are not thereby the same
    defect, and folding them together on wording would merge two real problems
    into one repair.
    """
    canonical = f"{path}:{line}:{category}"
    return "fp:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


@dataclass
class Finding:
    """One finding in the shared schema the lifecycle repository's catalogue defines."""

    path: str
    line: int | str
    category: str
    lens: str
    dimension: str
    severity: str
    evidence: str
    impact: str
    confidence: str = "medium"
    owner: str = "review-fixer"
    status: str = "open"
    first_seen_cycle: int = 1
    classification: str | None = None
    duplicate_of: str | None = None
    agreed_by: tuple[str, ...] = ()
    severity_flag: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_VOCABULARY:
            raise ReviewResultError(
                f"finding severity {self.severity!r} is not one of {list(SEVERITY_VOCABULARY)}"
            )
        if self.status not in STATUS_VOCABULARY:
            raise ReviewResultError(
                f"finding status {self.status!r} is not one of {list(STATUS_VOCABULARY)}"
            )
        if self.classification is not None and self.classification not in CLASSIFICATION_VOCABULARY:
            raise ReviewResultError(
                f"finding classification {self.classification!r} is not one of "
                f"{list(CLASSIFICATION_VOCABULARY)}"
            )
        if not str(self.evidence).strip():
            raise ReviewResultError(
                "a finding with no citation is an evidence gap, not a finding; evidence is "
                "required by the catalogue's own finding schema"
            )

    @property
    def id(self) -> str:
        return fingerprint(self.path, self.line, self.category)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lens": self.lens,
            "dimension": self.dimension,
            "severity": self.severity,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "impact": self.impact,
            "owner": self.owner,
            "status": self.status,
            "first_seen_cycle": self.first_seen_cycle,
            "classification": self.classification,
            "duplicate_of": self.duplicate_of,
            "agreed_by": list(self.agreed_by),
            "severity_flag": (dict(self.severity_flag) if self.severity_flag is not None else None),
            "path": self.path,
            "line": self.line,
            "category": self.category,
        }


def deduplicate(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Merge findings sharing one fingerprint; return (surviving, duplicates).

    The first finding for a fingerprint survives and records every later lens that
    agreed with it. Each later one is kept, marked ``duplicate-of`` the survivor —
    visible, and counted once.
    """
    survivors: dict[str, Finding] = {}
    duplicates: list[Finding] = []
    for finding in findings:
        key = finding.id
        existing = survivors.get(key)
        if existing is None:
            survivors[key] = finding
            continue
        if finding.lens not in existing.agreed_by and finding.lens != existing.lens:
            existing.agreed_by = (*existing.agreed_by, finding.lens)
        finding.status = "duplicate-of"
        finding.duplicate_of = key
        duplicates.append(finding)
    return list(survivors.values()), duplicates


# ---------------------------------------------------------------------------
# Advisory judgments over findings: dedupe groups and severity flags (1034)
# ---------------------------------------------------------------------------


def _judgment_modules() -> tuple[Any | None, Any | None]:
    """fleet-core's TypeSafe client and verdict log, or ``(None, None)``.

    Unreachable is not an error: both judgments fail open — dedupe leaves every
    finding ungrouped, the severity flag flags nothing — and the note names the
    reason.
    """
    try:
        import bundled_fleet  # noqa: PLC0415

        return (
            bundled_fleet.load("typesafe_client"),
            bundled_fleet.load("jev_log"),
        )
    except Exception:  # noqa: BLE001 — any failure means "fail open" instead
        return None, None


def _record_judgment(
    *,
    decision_prefix: str,
    state: Mapping[str, Any],
    questions: Mapping[str, Any],
    answers: Mapping[str, Any],
    answered_keys: Mapping[str, str],
    threshold: float | None,
    model: str,
    log_dir: Any,
) -> None:
    """Log one verdict per answered question. Best-effort by design.

    ``answered_keys`` maps each question key to the decision id its verdict is
    recorded under. An unwritable log directory is a problem with the fleet's
    measurement, not with the judgment the caller asked for.
    """
    client, log = _judgment_modules()
    if client is None or log is None:
        return
    for key, decision_key in answered_keys.items():
        answer = answers.get(key)
        if not isinstance(answer, Mapping):
            continue
        try:
            log.record_verdict(
                decision_id=f"{decision_prefix}:{decision_key}",
                state=state,
                questions=questions,
                answer=dict(answer),
                confidence=client.answer_confidence(answer),
                threshold=threshold,
                resolved_model=model,
                directory=log_dir,
            )
        except Exception:  # noqa: BLE001 — see the docstring
            return


def _ask_or_fail_open(
    ask: Callable[..., Any] | None,
) -> tuple[Callable[..., Any] | None, str]:
    """The caller to use, or None with the note the floor carries."""
    if ask is not None:
        return ask, ""
    client, _ = _judgment_modules()
    if client is None:
        return None, (
            "fleet-core's TypeSafe client is unreachable; judged nothing and changed nothing"
        )
    return client.ask, ""


def _finding_brief(finding: Finding, index: int) -> dict[str, Any]:
    """What the model reads about one finding: identity, text, and stated severity."""
    return {
        "index": index,
        "id": finding.id,
        "lens": finding.lens,
        "dimension": finding.dimension,
        "severity": finding.severity,
        "path": finding.path,
        "line": finding.line,
        "category": finding.category,
        "evidence": finding.evidence,
        "impact": finding.impact,
    }


def dedupe_candidates(findings: Sequence[Finding]) -> list[tuple[int, int]]:
    """Index pairs that might describe the same defect: same path and category.

    Code finds the candidates; the model only ever confirms or declines them.
    A same-fingerprint pair is included — it is the strongest candidacy — and a
    pair that shares neither path nor category is never asked about, however
    alike its wording.
    """
    pairs: list[tuple[int, int]] = []
    for left in range(len(findings)):
        for right in range(left + 1, len(findings)):
            if (
                findings[left].path == findings[right].path
                and findings[left].category == findings[right].category
            ):
                pairs.append((left, right))
    return pairs


def _dedupe_batch(
    chunk: Sequence[tuple[int, int]], briefs: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, tuple[int, int]]]:
    """Build one request covering many pairs.

    Every finding a chunk mentions is carried once in the state, and each
    question references two of them by the vendor's documented backticked path
    form. One question per pair, one request per chunk — not one request per
    pair, which at the cap would be hundreds of sequential calls.
    """
    ordered: list[int] = []
    position: dict[int, int] = {}
    for left, right in chunk:
        for index in (left, right):
            if index not in position:
                position[index] = len(ordered)
                ordered.append(index)
    state = {"findings": [briefs[index] for index in ordered]}
    questions: dict[str, Any] = {}
    index_of: dict[str, tuple[int, int]] = {}
    for number, (left, right) in enumerate(chunk):
        key = f"pair_{number}"
        questions[key] = {
            "type": "noul",
            "instructions": (
                f"Do the findings at `findings[{position[left]}]` and "
                f"`findings[{position[right]}]` describe the same underlying defect?"
            ),
        }
        index_of[key] = (left, right)
    return state, questions, index_of


def _noul_probability(answer: Any) -> float | None:
    """The yes probability of a yes/no answer, or None when there is not one.

    Mirrors ``review_roster`` so this module interprets its injected answers
    without importing the client.
    """
    if not isinstance(answer, Mapping):
        return None
    if answer.get("type") != "noul":
        return None
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def dedupe_findings(
    findings: Sequence[Finding],
    *,
    ask: Callable[..., Any] | None = None,
    threshold: float = DEDUPE_THRESHOLD,
    pair_cap: int = DEDUPE_PAIR_CAP,
    log: bool = True,
    log_dir: Any = None,
) -> dict[str, Any]:
    """Group findings that describe the same defect. Never drops one.

    Every finding appears in exactly one output group, and a group of one is a
    normal result — the guard test asserts the index set coming out equals the
    set going in, so dedupe can never drop a finding of higher severity by
    folding it into a lower one. Groups are advisory: the fingerprint merge in
    :func:`deduplicate` still owns counting, and these groups are shown beside
    it. ``ask`` is the injection seam, and every test passes a fake.
    """
    briefs = [_finding_brief(finding, index) for index, finding in enumerate(findings)]
    singletons = [[index] for index in range(len(findings))]
    base: dict[str, Any] = {
        "judgment": "finding-dedupe",
        "advisory": True,
        "threshold": threshold,
        "findings": briefs,
    }
    pairs = dedupe_candidates(findings)

    def _floor(ok: bool, note: str, **extra: Any) -> dict[str, Any]:
        return {
            **base,
            "ok": ok,
            "note": note,
            "model": "",
            "candidate_pairs": len(pairs),
            "pairs_judged": 0,
            "pairs_unjudged": len(pairs),
            "requests": 0,
            "groups": singletons,
            **extra,
        }

    if not pairs:
        return _floor(False, "no two findings share a path and category; nothing was asked")
    if len(pairs) > pair_cap:
        return _floor(
            False,
            f"not judged: {len(pairs)} candidate pairs is above the cap of {pair_cap}; "
            "every finding was left ungrouped",
        )

    caller, reason = _ask_or_fail_open(ask)
    if caller is None:
        return _floor(False, reason)

    parent = dict(enumerate(range(len(findings))))

    def _find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def _union(left: int, right: int) -> None:
        left_root, right_root = _find(left), _find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    requests = 0
    judged = 0
    unjudged = 0
    model = ""
    failure: str | None = None
    for start in range(0, len(pairs), DEDUPE_PAIRS_PER_REQUEST):
        chunk = pairs[start : start + DEDUPE_PAIRS_PER_REQUEST]
        state, questions, index_of = _dedupe_batch(chunk, briefs)
        try:
            result = caller(state, questions)
        except Exception as exc:  # noqa: BLE001 — one failed chunk must not end the call
            unjudged += len(chunk)
            if failure is None:
                failure = f"the request raised {type(exc).__name__}"
            continue
        requests += 1
        if getattr(result, "status", None) != _STATUS_OK:
            unjudged += len(chunk)
            if failure is None:
                failure = getattr(result, "note", "") or (
                    f"the request failed with status {getattr(result, 'status', 'unknown')}"
                )
            continue
        answers = getattr(result, "answers", None) or {}
        model = str(getattr(result, "model", "") or model)
        for key, (left, right) in index_of.items():
            probability = _noul_probability(answers.get(key))
            if probability is None:
                unjudged += 1
                continue
            judged += 1
            if probability >= threshold:
                _union(left, right)
        if log:
            _record_judgment(
                decision_prefix="code-review:finding-dedupe",
                state=state,
                questions=questions,
                answers=answers,
                answered_keys={key: f"{left}-{right}" for key, (left, right) in index_of.items()},
                threshold=threshold,
                model=model,
                log_dir=log_dir,
            )

    grouped: dict[int, list[int]] = {}
    for index in range(len(findings)):
        grouped.setdefault(_find(index), []).append(index)
    groups = [grouped[root] for root in sorted(grouped, key=lambda root: min(grouped[root]))]
    # An answered-nothing run must not report itself as a judgment.
    # Under-grouping caused by a partial outage looks exactly like a real
    # answer, so the count of pairs nobody judged travels with the result.
    note = ""
    if unjudged:
        note = f"{unjudged} of {len(pairs)} pairs were not judged"
        if failure:
            note += f" ({failure})"
        note += "; they were left ungrouped"
    return {
        **base,
        "ok": judged > 0,
        "note": note or ("no pair was judged" if not judged else ""),
        "model": model,
        "candidate_pairs": len(pairs),
        "pairs_judged": judged,
        "pairs_unjudged": unjudged,
        "requests": requests,
        "groups": groups,
    }


def _suggested_severity(score: Any) -> str | None:
    """The nearest catalogue level to a score answer's position, if usable.

    A score answer is a probability-weighted position on the ordered levels, so
    the suggestion is the nearest rung, clamped into range. Anything that is
    not a number is not a suggestion.
    """
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    position = int(float(score) + 0.5)
    position = min(max(position, 0), len(SEVERITY_LEVELS) - 1)
    return SEVERITY_LEVELS[position]


def flag_severity(
    findings: Sequence[Finding],
    *,
    ask: Callable[..., Any] | None = None,
    log: bool = True,
    log_dir: Any = None,
) -> dict[str, Any]:
    """Flag findings whose stated severity looks understated. Attached, never applied.

    One score question per finding, against the catalogue's severity anchors in
    order. A flag fires only when the suggested severity is strictly more
    severe than the stated one: the flag can only ever point upward, and even
    then it is a suggestion for a second look — :func:`attach_severity_flags`
    writes it beside the severity, and no path here reassigns the severity
    itself. ``ask`` is the injection seam, and every test passes a fake.
    """
    base: dict[str, Any] = {
        "judgment": "severity-flag",
        "advisory": True,
        "levels": list(SEVERITY_LEVELS),
    }
    if not findings:
        return {
            **base,
            "ok": False,
            "note": "no findings were supplied; nothing was asked",
            "model": "",
            "flags": [],
        }

    caller, reason = _ask_or_fail_open(ask)
    if caller is None:
        return {**base, "ok": False, "note": reason, "model": "", "flags": []}

    briefs = [_finding_brief(finding, index) for index, finding in enumerate(findings)]
    state = {"findings": briefs}
    anchors = [anchor for _, anchor in SEVERITY_ANCHORS]
    questions = {
        f"finding_{index}": {
            "type": "score",
            "instructions": f"How severe is the finding described at `findings[{index}]`?",
            "criteria": list(anchors),
        }
        for index in range(len(findings))
    }
    try:
        result = caller(state, questions)
    except Exception as exc:  # noqa: BLE001 — the floor must survive any failure
        return {
            **base,
            "ok": False,
            "note": f"the request raised {type(exc).__name__}",
            "model": "",
            "flags": [],
        }
    if getattr(result, "status", None) != _STATUS_OK:
        note = getattr(result, "note", "") or "the request failed"
        return {**base, "ok": False, "note": note, "model": "", "flags": []}

    answers = getattr(result, "answers", None) or {}
    model = str(getattr(result, "model", "") or "")
    flags: list[dict[str, Any]] = []
    for index, finding in enumerate(findings):
        answer = answers.get(f"finding_{index}")
        score = answer.get("score") if isinstance(answer, Mapping) else None
        confidence = answer.get("confidence") if isinstance(answer, Mapping) else None
        confidence = (
            float(confidence)
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            else None
        )
        suggested = _suggested_severity(score)
        stated = finding.severity
        if suggested is None:
            flagged = False
            flag_reason = "the answer carried no usable score; nothing was attached"
        elif SEVERITY_RANK[suggested] > SEVERITY_RANK[stated]:
            flagged = True
            flag_reason = (
                f"suggested {suggested} is more severe than the stated {stated}; "
                "attached for a second look"
            )
        else:
            flagged = False
            flag_reason = (
                f"suggested {suggested} does not exceed the stated {stated}; "
                "the reviewer's severity stands"
            )
        flags.append(
            {
                "index": index,
                "finding_id": finding.id,
                "stated": stated,
                "suggested": suggested,
                "score": score,
                "confidence": confidence,
                "flagged": flagged,
                "reason": flag_reason,
            }
        )

    if log:
        _record_judgment(
            decision_prefix="code-review:severity-flag",
            state=state,
            questions=questions,
            answers=answers,
            answered_keys={
                f"finding_{index}": f"finding_{index}" for index in range(len(findings))
            },
            threshold=None,
            model=model,
            log_dir=log_dir,
        )

    judged = sum(1 for flag in flags if flag["suggested"] is not None)
    return {
        **base,
        "ok": judged > 0,
        "note": "" if judged else "no finding carried a usable score",
        "model": model,
        "flags": flags,
    }


def attach_severity_flags(findings: Sequence[Finding], outcome: Mapping[str, Any]) -> int:
    """Attach the outcome's upward flags beside the findings' severities.

    Returns how many flags were attached. A flag is written onto
    :attr:`Finding.severity_flag` only when the outcome says ``flagged``; the
    severity itself is never reassigned here, in any direction. An outcome that
    names an index this list does not hold is refused rather than applied
    partway: a stale outcome applied to the wrong findings would mislabel them.
    """
    flags = outcome.get("flags", []) or []
    attached = 0
    for flag in flags:
        if not isinstance(flag, Mapping) or not flag.get("flagged"):
            continue
        index = flag.get("index")
        if not isinstance(index, int) or not 0 <= index < len(findings):
            raise ReviewResultError(
                "review_result: the severity outcome names finding index "
                f"{index!r}, which this list of {len(findings)} findings does not hold; "
                "nothing further was attached"
            )
        findings[index].severity_flag = {
            "suggested": flag.get("suggested"),
            "score": flag.get("score"),
            "confidence": flag.get("confidence"),
            "note": ("advisory: attached for a second look; the stated severity is unchanged"),
        }
        attached += 1
    return attached


# ---------------------------------------------------------------------------
# Lens results
# ---------------------------------------------------------------------------


@dataclass
class LensResult:
    """One lens's reading of one revision, with the provenance that makes it evidence."""

    lens: str
    strictness: str
    scorable: bool
    dimension_scores: dict[str, int] = field(default_factory=dict)
    non_applicable: dict[str, str] = field(default_factory=dict)
    executed: bool = True
    executor: dict[str, Any] = field(default_factory=dict)
    verification_reference: dict[str, Any] | None = None
    hosting: dict[str, Any] = field(default_factory=dict)
    checks_executed: list[dict[str, Any]] = field(default_factory=list)
    threshold: dict[str, Any] = field(default_factory=dict)
    scored: bool = True

    def derived_overall(self) -> float | None:
        """The weighted mean of applicable dimension scores, to one decimal place.

        Rounded half away from zero, which is the catalogue's stated rule and not
        Python's default banker's rounding.
        """
        if not self.dimension_scores:
            return None
        total = sum(self.dimension_scores.values())
        count = len(self.dimension_scores)
        raw = total / count
        return float(int(raw * 10 + (0.5 if raw >= 0 else -0.5)) / 10)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lens": self.lens,
            "strictness": self.strictness,
            "scorable": self.scorable,
            "scored": self.scored,
            "executed": self.executed,
            "dimension_scores": dict(self.dimension_scores),
            "non_applicable_dimensions": dict(self.non_applicable),
            "derived_overall": self.derived_overall(),
            "threshold": dict(self.threshold),
            "executor": dict(self.executor),
            "verification_reference": self.verification_reference,
            "hosting": dict(self.hosting),
            "checks_executed": list(self.checks_executed),
        }


# ---------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------


@dataclass
class ReviewResult:
    """One cycle's ``review_result.v2``."""

    revision: str
    roster_hash: str
    outcome: str
    cycle: int
    loop: str
    unit: str
    lens_results: list[LensResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    duplicates: list[Finding] = field(default_factory=list)
    advisory_findings: list[Finding] = field(default_factory=list)
    repair_accounting: dict[str, Any] = field(default_factory=dict)
    residual_issues: list[int] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    checks_and_coverage_gaps: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def __post_init__(self) -> None:
        if not FULL_SHA_RE.match(self.revision):
            raise ReviewResultError(
                f"reviewed revision {self.revision!r} is not a full forty-character commit "
                "identifier; an abbreviation or a symbolic reference stops meaning anything "
                "once the branch moves"
            )
        if self.loop not in LOOPS:
            raise ReviewResultError(f"loop {self.loop!r} is not one of {list(LOOPS)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "cycle": self.cycle,
            "loop": self.loop,
            "unit": self.unit,
            "revision": self.revision,
            "roster_hash": self.roster_hash,
            "outcome": self.outcome,
            "reason": self.reason,
            "per_lens_results": [row.to_dict() for row in self.lens_results],
            "findings": [row.to_dict() for row in self.findings],
            "duplicate_findings": [row.to_dict() for row in self.duplicates],
            "advisory_findings": [row.to_dict() for row in self.advisory_findings],
            "repair_accounting": dict(self.repair_accounting),
            "residual_issues": list(self.residual_issues),
            "checks_and_coverage_gaps": dict(self.checks_and_coverage_gaps),
            "provenance": dict(self.provenance),
        }


# ---------------------------------------------------------------------------
# The run record's review history
# ---------------------------------------------------------------------------


def legacy_entries(record: run_record.RunRecord) -> list[dict[str, Any]]:
    """Entries in the record written against the older result schema."""
    return [
        entry
        for entry in record.review_cycles
        if isinstance(entry, dict) and entry.get("schema") == LEGACY_RESULT_SCHEMA
    ]


def history_for(record: run_record.RunRecord, unit: str, loop: str) -> list[dict[str, Any]]:
    """This unit's entries in this loop, oldest first. Legacy entries are excluded."""
    return [
        entry
        for entry in record.review_cycles
        if isinstance(entry, dict)
        and entry.get("schema") == RESULT_SCHEMA
        and entry.get("unit") == unit
        and entry.get("loop") == loop
    ]


def cycles_used(record: run_record.RunRecord, unit: str, loop: str) -> int:
    """How many cycles this unit has spent in this loop.

    Counted per loop, never across the whole record: the two loops keep separate
    allowances, and counting the array's length would let a long testing phase
    spend the pre-merge budget.
    """
    return len(history_for(record, unit, loop))


def next_cycle(record: run_record.RunRecord, unit: str, loop: str) -> int:
    """The cycle number this unit's next result in this loop takes."""
    return cycles_used(record, unit, loop) + 1


def refuse_second_history(record: run_record.RunRecord, unit: str, loop: str) -> None:
    """Refuse a request to start a fresh history for a unit that already has one.

    Issue 946: a fresh history resets the cycle counter and shows incomparable
    scores. The refusal names the existing history's cycle count so the caller can
    see what it would have discarded.
    """
    existing = history_for(record, unit, loop)
    if existing:
        raise HistoryConflictError(
            f"review_result: unit {unit!r} already has a review history in the {loop} loop with "
            f"{len(existing)} cycle(s), the latest at revision "
            f"{existing[-1].get('revision', 'UNKNOWN')}; a fresh history would reset the cycle "
            "counter and place incomparable scores side by side, so it is refused. Append the "
            "next cycle to the existing history instead."
        )


def comparable_lens_set(
    record: run_record.RunRecord, unit: str, loop: str, lenses: list[str]
) -> None:
    """Refuse a result whose lens set differs from the history it joins.

    Scores are compared only within the declared lens set. The roster is frozen
    for the whole run, so a differing set means the roster changed underneath the
    history — which the lifecycle repository permits only through a recorded,
    operator-approved amendment.
    """
    existing = history_for(record, unit, loop)
    if not existing:
        return
    previous = [row.get("lens") for row in existing[-1].get("per_lens_results", [])]
    if sorted(filter(None, previous)) != sorted(lenses):
        raise ReviewResultError(
            f"review_result: unit {unit!r} has a history scored against lenses "
            f"{sorted(filter(None, previous))} and this result names {sorted(lenses)}; the "
            "roster is frozen for the whole run, and scores are compared only within one "
            "declared lens set"
        )


def append_result(
    record: run_record.RunRecord,
    result: ReviewResult,
) -> run_record.RunRecord:
    """Append *result* to the record's review history.

    Legacy entries are left exactly as they are. A missing key is not a refusal.
    """
    cycles = list(record.review_cycles)
    cycles.append(result.to_dict())
    return run_record.RunRecord(**{**record.__dict__, "review_cycles": cycles})


# ---------------------------------------------------------------------------
# Residual issues at the cycle cap
# ---------------------------------------------------------------------------


def residual_issue_payloads(result: ReviewResult, *, parent_issue: int) -> list[dict[str, str]]:
    """One linked defect per still-unresolved finding, for the capped run.

    Prepared rather than filed here: filing is a network write, and a module that
    both decides and files gives a test no seam to stand in. The caller passes
    these to mission-control, which owns issue creation, and records the numbers
    it returns on the result.
    """
    payloads: list[dict[str, str]] = []
    for finding in result.findings:
        if finding.status in ("fixed-verified", "withdrawn", "duplicate-of"):
            continue
        payloads.append(
            {
                "title": f"Residual review finding: {finding.category} at {finding.path}",
                "body": (
                    f"Carried out of the review of issue #{parent_issue} at revision "
                    f"`{result.revision}` when the repair allowance was exhausted.\n\n"
                    f"**Lens.** {finding.lens} / {finding.dimension}\n"
                    f"**Severity.** {finding.severity}\n"
                    f"**Evidence.** {finding.evidence}\n"
                    f"**Impact.** {finding.impact}\n"
                    f"**Finding id.** `{finding.id}`\n\n"
                    "The run proceeded with `cycle_cap_best_available`. Follow-up on this issue "
                    "is not automatic and does not establish consensus."
                ),
            }
        )
    return payloads


# Filing the prepared residuals is deliberately NOT here. Opening an issue is
# mission-control's ownership lane, and a saga script that shelled out to the
# issue-creating command itself would cross it —
# `tests/test_check_ownership_lanes.py` fails on exactly that. The caller hands
# these payloads to mission-control, which files them and returns the numbers
# recorded on `ReviewResult.residual_issues`.


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


def render_comment(result: ReviewResult) -> str:
    """Render the result as the body of one pull-request comment."""
    lines: list[str] = []
    lines.append(f"## Code review — `{result.outcome}`")
    lines.append("")
    lines.append(f"**Reviewed revision.** `{result.revision}`")
    lines.append(f"**Roster.** `{result.roster_hash}`")
    lines.append(f"**Cycle.** {result.cycle} of the {result.loop.replace('_', ' ')} loop")
    lines.append("")
    if result.reason:
        lines.append(result.reason)
        lines.append("")

    lines.append("### Lenses")
    lines.append("")
    lines.append("| Lens | Strictness | Derived overall | Threshold | Scored |")
    lines.append("|---|---|---|---|---|")
    for row in result.lens_results:
        overall = row.derived_overall()
        minimum = row.threshold.get("derived_overall_minimum", "—")
        lines.append(
            f"| {row.lens} | {row.strictness} | {overall if overall is not None else '—'} "
            f"| {minimum} | {'yes' if row.scored else 'no'} |"
        )
    lines.append("")

    if result.findings:
        lines.append("### Findings")
        lines.append("")
        lines.append("| Severity | Lens | Location | Status | Impact |")
        lines.append("|---|---|---|---|---|")
        for finding in sorted(result.findings, key=lambda f: f.severity):
            lines.append(
                f"| {finding.severity} | {finding.lens} | `{finding.path}:{finding.line}` "
                f"| {finding.status} | {finding.impact} |"
            )
        lines.append("")
    else:
        lines.append("No findings were reported against this revision.")
        lines.append("")

    if result.residual_issues:
        numbers = ", ".join(f"#{number}" for number in result.residual_issues)
        lines.append(f"**Residuals filed at the cycle cap.** {numbers}")
        lines.append("")

    lines.append(
        "This is a comment, not a review approval. A later commit carries no outcome from this one."
    )
    return "\n".join(lines)


def publish(
    result: ReviewResult,
    *,
    pull_request: str,
    repo: str,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Post the result as exactly one pull-request comment.

    One ``gh pr comment``. Never ``gh pr review`` in any form: an approving review
    on a pull request would carry an outcome forward onto commits this review never
    read. Nothing is committed and nothing is pushed, so ``HEAD`` does not move and
    a caller's freshness check stays valid.
    """
    body = render_comment(result)
    argv = ["gh", "pr", "comment", pull_request, "--repo", repo, "--body", body]
    completed = runner(argv, capture_output=True, text=True, check=False)  # nosec B603
    if completed.returncode != 0:
        raise ReviewResultError(
            f"review_result: could not publish the review comment: {completed.stderr.strip()[:300]}"
        )
    return {
        "published": True,
        "comments": 1,
        "reviews": 0,
        "revision": result.revision,
        "argv": argv,
        "url": completed.stdout.strip(),
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write review_result.v2 into the run record and render its comment."
    )
    parser.add_argument("--result", type=Path, required=True, help="A review_result.v2 file.")
    parser.add_argument("--issue", type=int, help="Append the result to this issue's record.")
    parser.add_argument("--store-root", type=Path, default=None, help="Run-record store override.")
    parser.add_argument(
        "--render-comment",
        type=Path,
        default=None,
        help="Write the comment body here instead of posting it.",
    )
    return parser


def _result_from_dict(payload: dict[str, Any]) -> ReviewResult:
    if payload.get("schema") != RESULT_SCHEMA:
        raise ReviewResultError(
            f"review_result: unknown result schema {payload.get('schema')!r}; this saga writes "
            f"{RESULT_SCHEMA}"
        )
    findings = [
        Finding(
            path=row["path"],
            line=row["line"],
            category=row["category"],
            lens=row["lens"],
            dimension=row.get("dimension", ""),
            severity=row.get("severity", "P3"),
            evidence=row.get("evidence", ""),
            impact=row.get("impact", ""),
            confidence=row.get("confidence", "medium"),
            status=row.get("status", "open"),
            first_seen_cycle=row.get("first_seen_cycle", 1),
            severity_flag=row.get("severity_flag"),
        )
        for row in payload.get("findings", [])
    ]
    lens_results = [
        LensResult(
            lens=row["lens"],
            strictness=row.get("strictness", "standard"),
            scorable=bool(row.get("scorable", False)),
            dimension_scores=row.get("dimension_scores", {}),
            non_applicable=row.get("non_applicable_dimensions", {}),
            executed=bool(row.get("executed", True)),
            scored=bool(row.get("scored", True)),
            threshold=row.get("threshold", {}),
            executor=row.get("executor", {}),
            verification_reference=row.get("verification_reference"),
            hosting=row.get("hosting", {}),
        )
        for row in payload.get("per_lens_results", [])
    ]
    return ReviewResult(
        revision=payload["revision"],
        roster_hash=payload.get("roster_hash", "UNKNOWN"),
        outcome=payload.get("outcome", "review_incomplete"),
        cycle=int(payload.get("cycle", 1)),
        loop=payload.get("loop", LOOP_CODE_REVIEW),
        unit=payload.get("unit", "UNKNOWN"),
        lens_results=lens_results,
        findings=findings,
        reason=payload.get("reason", ""),
        residual_issues=list(payload.get("residual_issues", [])),
        provenance=payload.get("provenance", {}),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.result.read_text(encoding="utf-8"))
        result = _result_from_dict(payload)
        if args.render_comment is not None:
            args.render_comment.write_text(render_comment(result), encoding="utf-8")
            print(f"wrote {args.render_comment}")
        if args.issue is not None:
            store_root = (
                Path(args.store_root).resolve()
                if args.store_root
                else run_record.resolve_store_root()
            )
            record = run_record.load(store_root, args.issue, warn=None)
            if record is None:
                raise ReviewResultError(
                    f"review_result: no run record for issue {args.issue} under {store_root}"
                )
            for entry in legacy_entries(record):
                print(
                    f"review_result: entry for cycle {entry.get('cycle')} declares "
                    f"{LEGACY_RESULT_SCHEMA}; preserved unchanged and counted toward no "
                    f"allowance (this saga writes {RESULT_SCHEMA})",
                    file=sys.stderr,
                )
            updated = append_result(record, result)
            path = run_record.save(store_root, updated)
            print(f"appended cycle {result.cycle} ({result.outcome}) to {path}")
    except run_record.UnknownRecordVersionError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_UNKNOWN_VERSION
    except ReviewResultError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"review_result: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
