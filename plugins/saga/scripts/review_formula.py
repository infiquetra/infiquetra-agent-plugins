#!/usr/bin/env python3
"""The review formula: each input's outcome, each lens's A–F grade, and the merge answer (issue 148).

The saga review redesign (``docs/brainstorms/2026-10-05-saga-review-redesign/plan.md``, Change 7 and
"Block, fix later and note") makes review mostly deterministic. Tools, checks and narrow questions
produce records; this module turns them into outcomes. It is pure: it takes plain dicts, reads no
clock, file or network, and gives byte-identical output for the same input.

Three outcomes, never written by a reviewer:

* ``blocks``: the lens drops to D (one) or F (two or more), and merge waits.
* ``fix-later``: the lens drops to B (one or two) or C (three or more), never lower.
* ``note``: recorded only; the grade does not move.

Every input cites a row of ``ROWS``, which holds each row of the four lens tables and the
judged-findings table with its fixed base outcome. An LLM finding cites ``judged``, and code picks
the ``judged.*`` row from its consequence, trigger and evidence. The order a finding's outcome is
computed in, each step named in ``severity_basis.modifiers`` when it changed something:

1. the base outcome of the row;
2. ``reproduced``: a row that blocks when reproduced, and was;
3. ``excused``: a builder reason of the kind the row allows makes it a note;
4. caps that lower ``blocks`` to ``fix-later``: ``degraded``, ``classifier-only`` and
   ``unreproduced`` (an LLM finding nobody reproduced);
5. enforcement: a block counts for merge only where the lens may block for the finding's language,
   or where it is a reproduced "data lost or corrupted" or "a security boundary crossed" harm.

``review_records.py`` validates records and stores them; it imports this module, never the reverse.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "review_records.v1"

LENSES: tuple[str, ...] = ("correctness", "security", "testing", "architecture-maintainability")

#: The languages ``plan.md`` names, plus ``none`` for a plan finding or a result with no language.
LANGUAGES: tuple[str, ...] = (
    "python",
    "typescript",
    "dart",
    "rust",
    "swift",
    "markdown",
    "shell",
    "github-workflows",
    "cloudformation",
    "none",
)

#: The judged-findings table's consequences, in three groups, most severe group first.
HARMS: tuple[str, ...] = (
    "data-lost-or-corrupted",
    "money-or-resources-wrongly-moved",
    "security-boundary-crossed",
    "two-holders-of-one-exclusive-thing",
    "wrong-result-reported-as-success",
    "required-behaviour-missing",
    "break-in-supported-use",
)
VISIBLE: tuple[str, ...] = ("fails-loudly-and-recoverably", "misleads-a-person")
UPKEEP: tuple[str, ...] = ("costs-future-work", "style")
CONSEQUENCES: tuple[str, ...] = HARMS + VISIBLE + UPKEEP

#: The harms that block even on a lens that only reports, when reproduced.
ALWAYS_BLOCKING: tuple[str, ...] = ("data-lost-or-corrupted", "security-boundary-crossed")

#: Normal use, the legitimate conditions the correctness lens names, and misuse.
TRIGGERS: tuple[str, ...] = (
    "normal-use",
    "retry",
    "interrupt",
    "concurrency",
    "old-data",
    "other-caller",
    "misuse-only",
)

EVIDENCE: tuple[str, ...] = ("reproduced", "traced", "suspected", "tool-result")

SOURCE_KINDS: tuple[str, ...] = ("tool", "classifier", "llm")

SEVERITIES: tuple[str, ...] = ("blocks", "fix-later", "note")

MERGE_OUTCOMES: tuple[str, ...] = ("fixed", "dismissed", "fixed-now", "filed", "left")

REASON_KINDS: tuple[str, ...] = (
    "coverage-gap",
    "surviving-mutant",
    "scanner-false-positive",
    "unaffected",
    "pattern-check",
    "where-to-look-explanation",
    "test-passes-before-change",
    "test-skipped-in-ci",
)

GRADES: tuple[str, ...] = ("A", "B", "C", "D", "F")

#: The row an LLM finding cites; code replaces it with one of the ``judged.*`` rows.
JUDGED = "judged"


class FormulaError(ValueError):
    """An input the formula cannot compute: a preset severity, an unknown row."""


@dataclass(frozen=True)
class Row:
    """One row of a lens table or the judged-findings table."""

    id: str
    lens: str | None  # None for the judged rows, which serve every lens
    outcome: str
    excused_by: str | None = None
    blocks_when_reproduced: bool = False
    merge_confirmation: bool = False


def _rows(*rows: Row) -> dict[str, Row]:
    return {row.id: row for row in rows}


_PATTERN_CHECKS = (
    "release-shares-cleanup",
    "swallowed-error",
    "silent-skip",
    "naive-time-comparison",
    "write-skips-shared-update",
    "money-as-float",
)

#: Every fixed row. Tool adapters (C4a to C4c) and our checks (C5, C5b) cite these identifiers.
ROWS: Mapping[str, Row] = _rows(
    # Testing
    Row("testing.uncovered-branch", "testing", "blocks", excused_by="coverage-gap"),
    Row("testing.surviving-mutant", "testing", "blocks", excused_by="surviving-mutant"),
    Row("testing.test-passes-before-change", "testing", "blocks",
        excused_by="test-passes-before-change"),
    Row("testing.test-skipped-in-ci", "testing", "blocks", excused_by="test-skipped-in-ci"),
    Row("testing.flaky-order-or-network", "testing", "fix-later"),
    Row("testing.fakes-code-under-test", "testing", "fix-later"),
    Row("testing.writes-live-system", "testing", "fix-later", blocks_when_reproduced=True),
    Row("testing.dispute", "testing", "fix-later", merge_confirmation=True),
    # Security
    Row("security.scanner-high", "security", "blocks", excused_by="scanner-false-positive"),
    Row("security.scanner-medium-low", "security", "fix-later"),
    Row("security.secret-in-diff", "security", "blocks"),
    Row("security.dependency-high", "security", "blocks", excused_by="scanner-false-positive"),
    Row("security.workflow-infra-high", "security", "blocks"),
    Row("security.required-test-missing", "security", "blocks"),
    Row("security.dispute", "security", "fix-later", merge_confirmation=True),
    # Architecture and maintainability
    Row("architecture-maintainability.structural-check-fails", "architecture-maintainability",
        "blocks"),
    Row("architecture-maintainability.prose-rule-broken", "architecture-maintainability",
        "fix-later", blocks_when_reproduced=True),
    Row("architecture-maintainability.relocated-run-fails", "architecture-maintainability",
        "blocks"),
    Row("architecture-maintainability.machine-specific-value", "architecture-maintainability",
        "fix-later"),
    Row("architecture-maintainability.undocumented-departure", "architecture-maintainability",
        "note"),
    Row("architecture-maintainability.duplicate", "architecture-maintainability", "note"),
    Row("architecture-maintainability.complexity-dead-code-naming",
        "architecture-maintainability", "note"),
    Row("architecture-maintainability.dispute", "architecture-maintainability", "fix-later",
        merge_confirmation=True),
    # Correctness
    Row("correctness.criterion-without-check", "correctness", "blocks"),
    Row("correctness.type-error", "correctness", "blocks"),
    *(
        Row(f"correctness.pattern.{name}", "correctness", "blocks", excused_by="pattern-check")
        for name in _PATTERN_CHECKS
    ),
    Row("correctness.declared-question-untested", "correctness", "blocks"),
    Row("correctness.unupdated-mention", "correctness", "blocks", excused_by="unaffected"),
    Row("correctness.unupdated-mention-in-document", "correctness", "fix-later"),
    Row("correctness.workflow-dead-end", "correctness", "blocks"),
    Row("correctness.ci-matrix-fails", "correctness", "blocks"),
    Row("correctness.dispute", "correctness", "fix-later", merge_confirmation=True),
    *(
        Row(f"{lens}.{suffix}", lens, outcome)
        for lens in LENSES
        for suffix, outcome in (
            ("tool-error", "blocks"),
            ("tool-warning", "fix-later"),
            ("tool-style", "note"),
            ("tool-curated", "blocks"),
            ("tool-unscoped", "fix-later"),
        )
    ),
    Row("security.dependency-medium-low", "security", "fix-later"),
    Row("security.workflow-infra-medium-low", "security", "fix-later"),
    # Judged findings, any lens
    Row("judged.harm-reproduced", None, "blocks"),
    Row("judged.harm-traced", None, "fix-later"),
    Row("judged.harm-misuse", None, "fix-later"),
    Row("judged.visible", None, "fix-later"),
    Row("judged.upkeep", None, "note"),
)

#: The keys the formula computes on a finding; a finding handed in carrying one is refused.
COMPUTED_FINDING_KEYS: tuple[str, ...] = ("severity", "severity_basis", "flags", "enforced")

#: Item 6 levels. Information uses the style row. No level is unscoped, or curated when listed.
_TOOL_LEVEL_ROWS: Mapping[str, str] = {
    "error": "tool-error",
    "warning": "tool-warning",
    "style": "tool-style",
    "info": "tool-style",
    "information": "tool-style",
}


def tool_row(lens: str, level: str | None, rule_id: str, curated: Sequence[str]) -> str:
    """The row for a tool finding the lens tables do not name.

    ``level`` is ``error``, ``warning``, ``style``, ``info``, or none. A missing level is
    ``tool-unscoped`` (fix later) unless ``rule_id`` is in ``curated``, which blocks and which no
    builder reason excuses.
    """
    if lens not in LENSES:
        raise FormulaError(f"lens: {lens!r} is not a lens")
    if level in (None, "", "none"):
        suffix = "tool-curated" if rule_id in curated else "tool-unscoped"
    else:
        suffix = _TOOL_LEVEL_ROWS.get(level)
        if suffix is None:
            raise FormulaError(f"level: {level!r} is not a tool level")
    return f"{lens}.{suffix}"


def dependency_row(score: float | None) -> str:
    """CVSS v3 bands. ``None`` is no score and blocks. ``0.0`` is a score, not a missing one."""
    if score is None:
        return "security.dependency-high"
    if float(score) >= 7.0:
        return "security.dependency-high"
    return "security.dependency-medium-low"


def workflow_row(level: str) -> str:
    """The same bands, on the workflow and infrastructure words."""
    word = level.lower()
    if word in {"critical", "high"}:
        return "security.workflow-infra-high"
    if word in {"medium", "low", "none"}:
        return "security.workflow-infra-medium-low"
    raise FormulaError(f"level: {level!r} is not a workflow severity")


def merge_advisories(hits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse raw hits whose advisory id or alias sets intersect.

    Each hit carries ``advisory_ids``, ``tool``, ``score`` (or none) and ``row``. The kept hit is
    the one with a score, and the highest score when several have one. Its ``canonical_id`` is that
    hit's lexicographically first advisory id, or the first id of the union when none is scored.
    The validated finding gains no extra field: the caller copies ``canonical_id`` into ``rule.ref``.
    """
    indexed = [dict(hit) for hit in hits]
    parent = list(range(len(indexed)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        roots = (find(left), find(right))
        if roots[0] != roots[1]:
            parent[roots[1]] = roots[0]

    id_sets = [set(hit.get("advisory_ids") or ()) for hit in indexed]
    for left in range(len(indexed)):
        if not id_sets[left]:
            continue
        for right in range(left + 1, len(indexed)):
            if id_sets[left] & id_sets[right]:
                union(left, right)
    groups: dict[int, list[int]] = {}
    for index in range(len(indexed)):
        groups.setdefault(find(index), []).append(index)

    merged: list[dict[str, Any]] = []
    for members in groups.values():
        kept_index = _scored_hit(indexed, members)
        kept = dict(indexed[kept_index])
        union_ids = sorted({item for index in members for item in id_sets[index]})
        if indexed[kept_index].get("score") is not None:
            scored_ids = sorted(id_sets[kept_index])
            kept["canonical_id"] = scored_ids[0] if scored_ids else (union_ids[0] if union_ids else "")
        else:
            kept["canonical_id"] = union_ids[0] if union_ids else ""
        kept["advisory_ids"] = union_ids
        merged.append(kept)
    return merged


def _scored_hit(hits: Sequence[Mapping[str, Any]], members: Sequence[int]) -> int:
    """The scored hit, or the highest score. Unscored hits lose to any score, including zero."""
    scored = [index for index in members if hits[index].get("score") is not None]
    pool = list(scored) if scored else list(members)

    def better(challenger: int, incumbent: int) -> bool:
        challenger_score = hits[challenger].get("score")
        incumbent_score = hits[incumbent].get("score")
        left = float(challenger_score) if challenger_score is not None else -1.0
        right = float(incumbent_score) if incumbent_score is not None else -1.0
        if left != right:
            return left > right
        return str(hits[challenger].get("tool") or "") < str(hits[incumbent].get("tool") or "")

    best = pool[0]
    for index in pool[1:]:
        if better(index, best):
            best = index
    return best


def consequence_group(consequence: str) -> int:
    """0 for a harm, 1 for visible, 2 for upkeep: a higher number is the lower consequence."""
    if consequence in HARMS:
        return 0
    if consequence in VISIBLE:
        return 1
    return 2


def lower_consequence(llm: str, jev: str) -> str:
    """The lower of two picks by group. Within one group the LLM's pick stands."""
    return jev if consequence_group(jev) > consequence_group(llm) else llm


def _applied_consequence(finding: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """The consequence the formula uses, and any flags the pick raised."""
    llm = finding.get("consequence")
    if llm is None:
        return None, []
    source_kind = (finding.get("source") or {}).get("kind")
    if source_kind != "llm" or finding.get("evidence") != "reproduced":
        return llm, []
    jev = finding.get("consequence_jev")
    if jev is None:
        return llm, []  # Jev could not answer: the finding is marked "unconfirmed"
    if jev != llm:
        return lower_consequence(llm, jev), ["consequence-disagreement"]
    return llm, []


def judged_row(consequence: str, trigger: str | None, evidence: str) -> str:
    """The judged-findings table: which ``judged.*`` row a consequence, trigger and evidence fit."""
    if consequence in HARMS:
        if trigger == "misuse-only":
            return "judged.harm-misuse"
        if evidence == "reproduced":
            return "judged.harm-reproduced"
        return "judged.harm-traced"
    if consequence in VISIBLE:
        return "judged.visible"
    return "judged.upkeep"


def _reason_for(
    finding_id: str, kind: str | None, builder_records: Sequence[Mapping[str, Any]]
) -> bool:
    if kind is None:
        return False
    for record in builder_records:
        for reason in record.get("reasons") or ():
            if reason.get("finding_id") == finding_id and reason.get("kind") == kind:
                return True
    return False


def _may_block(may_block: Mapping[str, Any], lens: str, language: str) -> bool:
    answers = may_block.get(lens)
    return isinstance(answers, Mapping) and answers.get(language) is True


def outcome(
    finding: Mapping[str, Any],
    builder_records: Sequence[Mapping[str, Any]] = (),
    may_block: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The computed fields for one input finding: severity, its basis, flags and enforcement."""
    preset = [key for key in COMPUTED_FINDING_KEYS if key in finding]
    if preset:
        raise FormulaError(
            f"{preset[0]}: a finding is handed in without it; code computes it, never the reviewer"
        )
    cited = (finding.get("rule") or {}).get("row")
    evidence = finding.get("evidence")
    consequence, flags = _applied_consequence(finding)
    if cited == JUDGED:
        if consequence is None:
            raise FormulaError("consequence: a judged finding needs one")
        row_id = judged_row(consequence, finding.get("trigger"), str(evidence))
    else:
        row_id = str(cited)
    row = ROWS.get(row_id)
    if row is None:
        raise FormulaError(f"rule.row: {cited!r} is not a row the formula knows")

    modifiers: list[str] = []
    severity = row.outcome
    if row.blocks_when_reproduced and evidence == "reproduced":
        severity = "blocks"
        modifiers.append("reproduced")
    if _reason_for(str(finding.get("id")), row.excused_by, builder_records):
        severity = "note"
        modifiers.append("excused")
    if severity == "blocks":
        source_kind = (finding.get("source") or {}).get("kind")
        if finding.get("degraded"):
            severity = "fix-later"
            modifiers.append("degraded")
        elif source_kind == "classifier":
            severity = "fix-later"
            modifiers.append("classifier-only")
        elif source_kind == "llm" and evidence != "reproduced":
            severity = "fix-later"
            modifiers.append("unreproduced")
    if row.merge_confirmation:
        flags.append("merge-confirmation")
    if finding.get("unconfirmed"):
        flags.append("unconfirmed")

    always = evidence == "reproduced" and consequence in ALWAYS_BLOCKING
    enforced = severity == "blocks" and (
        always
        or _may_block(may_block or {}, str(finding.get("lens")), str(finding.get("language")))
    )
    if severity == "blocks" and always:
        modifiers.append("always-blocks")
    return {
        "severity": severity,
        "severity_basis": {"row": row_id, "modifiers": modifiers},
        "flags": sorted(set(flags)),
        "enforced": enforced,
    }


def grade(blocks: int, fix_later: int) -> str:
    """The A–F table. Notes never move it, and fix-later items never add up to a block."""
    if blocks >= 2:
        return "F"
    if blocks == 1:
        return "D"
    if fix_later >= 3:
        return "C"
    if fix_later >= 1:
        return "B"
    return "A"


def measurement_condition(measurement: Mapping[str, Any]) -> str:
    """``met`` or ``missed`` against the threshold. Measurements never move the grade."""
    value = float(measurement["value"])
    threshold = float(measurement["threshold"])
    met = value >= threshold if measurement["direction"] == "at-least" else value <= threshold
    return "met" if met else "missed"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def compute(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Compute a review's findings, measurements, lens grades and merge answer.

    *inputs* holds ``findings`` and ``measurements`` in their input form, ``builder_records``,
    ``may_block`` (``{lens: {language: bool}}``; absent means every lens reports only) and
    ``degraded_inputs`` (``[{lens, language, input, tool, reason}]``). Everything returned is sorted,
    so the same inputs in any order give the same output.
    """
    builder_records = list(inputs.get("builder_records") or [])
    may_block = dict(inputs.get("may_block") or {})
    findings: list[dict[str, Any]] = []
    for finding in inputs.get("findings") or []:
        findings.append({**finding, **outcome(finding, builder_records, may_block)})
    findings.sort(key=lambda item: (str(item.get("id")), _canonical(item)))

    measurements = []
    for measurement in inputs.get("measurements") or []:
        if "condition" in measurement:
            raise FormulaError("condition: a measurement is handed in without it; code computes it")
        measurements.append({**measurement, "condition": measurement_condition(measurement)})
    measurements.sort(key=_canonical)

    degraded_inputs = sorted(inputs.get("degraded_inputs") or [], key=_canonical)
    lens_grades = []
    for lens in LENSES:
        mine = [item for item in findings if item.get("lens") == lens]
        counts = {
            severity: sum(1 for item in mine if item["severity"] == severity)
            for severity in SEVERITIES
        }
        degraded = sorted(
            [{"finding_id": item["id"]} for item in mine if item.get("degraded")]
            + [entry for entry in degraded_inputs if entry.get("lens") == lens],
            key=_canonical,
        )
        given = may_block.get(lens)
        answers: Mapping[str, Any] = given if isinstance(given, Mapping) else {}
        languages = {str(item.get("language")) for item in mine} | set(answers)
        lens_grades.append(
            {
                "kind": "lens_grade",
                "schema": SCHEMA,
                "lens": lens,
                "blocks": counts["blocks"],
                "fix_later": counts["fix-later"],
                "notes": counts["note"],
                "grade": grade(counts["blocks"], counts["fix-later"]),
                "degraded_inputs": degraded,
                "may_block": {
                    language: answers.get(language) is True for language in sorted(languages)
                },
            }
        )

    blocking = sorted(item["id"] for item in findings if item["enforced"])
    skipped = sorted(
        item["id"] for item in findings if item["severity"] == "blocks" and not item["enforced"]
    )
    return {
        "findings": findings,
        "measurements": measurements,
        "lens_grades": lens_grades,
        "degraded_inputs": degraded_inputs,
        "merge": {"allowed": not blocking, "blocking": blocking, "report_only_blocks": skipped},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_formula.py",
        description=(
            "Compute a review's outcomes, A-F lens grades and merge answer from its input records. "
            "Pure: no network, no clock. Exit 1 refuses an input (a preset severity, an unknown "
            "row); exit 2 is an unreadable file."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("compute", help="Print the computed result as JSON.")
    run.add_argument("inputs", type=Path, help="A JSON file of the review's inputs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"review_formula: cannot read {args.inputs}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(inputs, dict):
        print(f"review_formula: {args.inputs} is not a JSON object", file=sys.stderr)
        return 2
    try:
        result = compute(inputs)
    except FormulaError as exc:
        print(f"review_formula: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
