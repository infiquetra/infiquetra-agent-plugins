#!/usr/bin/env python3
"""The five review records and the builder record: validation, identity and storage (issue 148).

Every review source (tools, our checks, the Jev sweep, the LLM reviewer) emits the same records,
defined in ``references/review-records.schema.json`` and explained in
``references/review-records.md``. This module refuses a malformed record by naming each bad field,
computes each finding's identity, and stores computed review runs and builder records in the
issue's run record under its lock.

Six kinds, each carrying ``kind`` and ``schema: "review_records.v1"``:

* ``finding``: one problem, with the row it cites, its source, location, closed-list labels and
  proof. Handed in on its own it never carries a severity; inside a stored review run it carries
  the one ``review_formula`` computed, and validation recomputes it.
* ``measurement``: one number a tool produced, with its threshold.
* ``where_to_look``: one classifier hit, with the questions that fired and the LLM's answer.
* ``lens_grade``: one lens's counts, A–F grade, degraded inputs and per-language "may block".
* ``review_run``: everything for one review, plus the change reviewed, versions, usage and merge.
* ``builder_record``: one unit's acceptance criteria, policy declarations and reasons.

Storage (``references/run-record.md``): a review run is appended to ``review_cycles`` with
``loop: "review_run"``, which the readers of today's ``review_result`` entries skip; a builder
record is the unit row's ``builder_record`` key. Both go through ``run_record.update``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_formula as formula  # noqa: E402  (after the sys.path shim, by design)
import run_record  # noqa: E402

SCHEMA = formula.SCHEMA

KINDS: tuple[str, ...] = (
    "finding",
    "measurement",
    "where_to_look",
    "lens_grade",
    "review_run",
    "builder_record",
)

#: The ``loop`` value a stored review run carries in ``review_cycles``.
STORED_LOOP = "review_run"

#: The unit-row key a builder record lives under.
ROW_KEY = "builder_record"

#: Required fields per kind, in the input form. The schema file's ``required`` lists match these.
REQUIRED: Mapping[str, tuple[str, ...]] = {
    "finding": (
        "kind",
        "schema",
        "id",
        "subject",
        "lens",
        "rule",
        "source",
        "location",
        "language",
        "statement",
        "consequence",
        "trigger",
        "evidence",
        "proof",
        "introduced",
        "degraded",
        "consequence_jev",
        "unconfirmed",
        "merge_outcome",
    ),
    "measurement": (
        "kind",
        "schema",
        "lens",
        "row",
        "tool",
        "language",
        "metric",
        "value",
        "threshold",
        "direction",
    ),
    "where_to_look": (
        "kind",
        "schema",
        "lens",
        "location",
        "language",
        "questions",
        "classifier",
        "degraded",
        "answer",
    ),
    "lens_grade": (
        "kind",
        "schema",
        "lens",
        "blocks",
        "fix_later",
        "notes",
        "grade",
        "degraded_inputs",
        "may_block",
    ),
    "review_run": (
        "kind",
        "schema",
        "card",
        "repo",
        "base",
        "head",
        "saga_version",
        "round",
        "tool_versions",
        "usage",
        "findings",
        "measurements",
        "where_to_look",
        "lens_grades",
        "builder_records",
        "may_block",
        "degraded_inputs",
        "merge",
        "raw_outputs",
    ),
    "builder_record": (
        "kind",
        "schema",
        "unit",
        "acceptance_criteria",
        "declarations",
        "reasons",
    ),
}

SUBJECTS: tuple[str, ...] = ("code", "plan")
SCOPES: tuple[str, ...] = ("lines", "whole-project", "section")
DIRECTIONS: tuple[str, ...] = ("at-least", "at-most")
CONDITIONS: tuple[str, ...] = ("met", "missed")
USAGE_FIELDS: tuple[str, ...] = ("tokens_in", "tokens_out", "cost_usd", "seconds")

#: Field names that would carry a secret's matched text; refused on a secret-scanner finding.
SECRET_FIELDS: tuple[str, ...] = ("secret", "matched_text", "excerpt")
SECRET_ROW = "security.secret-in-diff"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^rf:[0-9a-f]{32}$")


class ReviewRecordError(ValueError):
    """A record was refused. ``problems`` holds one ``<field path>: <why>`` line per bad field."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class MissingUnitError(RuntimeError):
    """A builder record names a unit with no row, in a record orchestrate drives. Exit 5."""


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def normalise_anchor(anchor: str) -> str:
    """Collapse every run of whitespace to one space, so re-indentation keeps the identity."""
    return " ".join(str(anchor).split())


def finding_identity(lens: str, rule: Mapping[str, Any], location: Mapping[str, Any]) -> str:
    """A finding's identity: lens, rule, path, scope and the stored anchor, never the line.

    It stays the same when lines move and in a later round, and differs for two rules on one line
    or for two anchors under one rule. Everything it reads is stored on the finding, so a reader
    can recompute it from the record alone.
    """
    where = location.get("file") or location.get("document") or ""
    scope = location.get("function") or location.get("section") or ""
    parts = [
        str(lens),
        str(rule.get("row") or ""),
        str(rule.get("ref") or ""),
        str(where),
        str(scope),
        normalise_anchor(str(location.get("anchor") or "")),
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return "rf:" + digest[:32]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class _Check:
    """Collects ``<path>: <why>`` problems while walking one record."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def add(self, path: str, why: str) -> None:
        self.problems.append(f"{path}: {why}")

    def required(self, record: Mapping[str, Any], fields: tuple[str, ...], prefix: str) -> None:
        for name in fields:
            if name not in record:
                self.add(f"{prefix}{name}", "required")

    def choice(self, value: Any, allowed: tuple[str, ...], path: str) -> bool:
        if value not in allowed:
            self.add(path, f"{value!r} is not one of {', '.join(allowed)}")
            return False
        return True

    def text(self, value: Any, path: str) -> bool:
        if not isinstance(value, str) or not value.strip():
            self.add(path, "must be a non-empty string")
            return False
        return True

    def boolean(self, value: Any, path: str) -> None:
        if not isinstance(value, bool):
            self.add(path, "must be true or false")

    def integer(self, value: Any, path: str, minimum: int = 0) -> bool:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            self.add(path, f"must be an integer of at least {minimum}")
            return False
        return True

    def number(self, value: Any, path: str) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.add(path, "must be a number")
            return False
        return True

    def mapping(self, value: Any, path: str) -> bool:
        if not isinstance(value, Mapping):
            self.add(path, "must be an object")
            return False
        return True

    def array(self, value: Any, path: str) -> bool:
        if not isinstance(value, list):
            self.add(path, "must be an array")
            return False
        return True


def _check_header(check: _Check, record: Mapping[str, Any], kind: str, prefix: str) -> None:
    if "kind" in record and record["kind"] != kind:
        check.add(f"{prefix}kind", f"must be {kind!r}")
    if "schema" in record and record["schema"] != SCHEMA:
        check.add(f"{prefix}schema", f"must be {SCHEMA!r}")


def _check_location(
    check: _Check, location: Any, path: str, *, subject: str | None, scopes: tuple[str, ...]
) -> None:
    if not check.mapping(location, path):
        return
    if not check.choice(location.get("scope"), scopes, f"{path}.scope"):
        return
    check.text(location.get("anchor"), f"{path}.anchor")
    scope = location["scope"]
    if scope == "section":
        if subject != "plan":
            check.add(f"{path}.scope", "a section location is allowed only on a plan finding")
        check.text(location.get("document"), f"{path}.document")
        check.text(location.get("section"), f"{path}.section")
        return
    check.text(location.get("file"), f"{path}.file")
    if scope == "whole-project":
        if "lines" in location:
            check.add(f"{path}.lines", "a whole-project result carries no lines")
        return
    lines = location.get("lines")
    if lines is None:
        check.add(f"{path}.lines", 'required when scope is "lines"')
    elif check.mapping(lines, f"{path}.lines"):
        start_ok = check.integer(lines.get("start"), f"{path}.lines.start", 1)
        end_ok = check.integer(lines.get("end"), f"{path}.lines.end", 1)
        if start_ok and end_ok and lines["end"] < lines["start"]:
            check.add(f"{path}.lines.end", "must not be before lines.start")
    if "function" not in location:
        check.add(f"{path}.function", "required (null at module level or outside code)")
    elif location["function"] is not None:
        check.text(location["function"], f"{path}.function")


def _check_source(check: _Check, source: Any, path: str) -> None:
    if not check.mapping(source, path):
        return
    if not check.choice(source.get("kind"), formula.SOURCE_KINDS, f"{path}.kind"):
        return
    check.text(source.get("name"), f"{path}.name")
    if source["kind"] == "tool":
        check.text(source.get("version"), f"{path}.version")
    else:
        check.text(source.get("model"), f"{path}.model")


def _check_proof(check: _Check, finding: Mapping[str, Any], path: str) -> None:
    proof = finding.get("proof")
    if not check.mapping(proof, path):
        return
    evidence = finding.get("evidence")
    if evidence == "reproduced":
        if not any(isinstance(proof.get(key), str) and proof[key].strip()
                   for key in ("test", "output")):
            check.add(f"{path}.test", "a reproduced finding names its failing test or output")
    elif evidence == "traced":
        steps = proof.get("steps")
        if not isinstance(steps, list) or not steps or not all(
            isinstance(step, str) and step.strip() for step in steps
        ):
            check.add(f"{path}.steps", "a traced finding gives its file-and-line steps")
    elif evidence == "tool-result":
        if not isinstance(proof.get("raw_output"), str) or not _SHA256.match(proof["raw_output"]):
            check.add(f"{path}.raw_output", "a tool result references its raw output by sha256")


def _check_merge_outcome(check: _Check, value: Any, path: str) -> None:
    if value is None:
        return
    if not check.mapping(value, path):
        return
    if not check.choice(value.get("outcome"), formula.MERGE_OUTCOMES, f"{path}.outcome"):
        return
    if value["outcome"] == "dismissed":
        check.text(value.get("reason"), f"{path}.reason")
    if value["outcome"] == "filed":
        check.integer(value.get("issue"), f"{path}.issue", 1)


def _secret_fields(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, inner in value.items():
            if key in SECRET_FIELDS:
                found.append(str(key))
            found.extend(f"{key}.{name}" for name in _secret_fields(inner))
    return found


def _check_finding(
    check: _Check, finding: Any, prefix: str = "", *, stored: bool = False
) -> None:
    if not check.mapping(finding, prefix.rstrip(".") or "record"):
        return
    check.required(finding, REQUIRED["finding"], prefix)
    _check_header(check, finding, "finding", prefix)
    if stored:
        for key in formula.COMPUTED_FINDING_KEYS:
            if key not in finding:
                check.add(f"{prefix}{key}", "required on a finding in a stored review run")
        if "severity" in finding:
            check.choice(finding["severity"], formula.SEVERITIES, f"{prefix}severity")
    else:
        for key in formula.COMPUTED_FINDING_KEYS:
            if key in finding:
                check.add(f"{prefix}{key}", "code computes it; a finding is handed in without it")
    subject = finding.get("subject")
    if "subject" in finding:
        check.choice(subject, SUBJECTS, f"{prefix}subject")
    if "lens" in finding:
        check.choice(finding["lens"], formula.LENSES, f"{prefix}lens")
    rule: Any = finding.get("rule")
    if "rule" in finding and check.mapping(rule, f"{prefix}rule"):
        row = rule.get("row")
        if row != formula.JUDGED and row not in formula.ROWS:
            check.add(f"{prefix}rule.row", f"{row!r} is not a row the formula knows")
        elif row in formula.ROWS and formula.ROWS[row].lens not in (None, finding.get("lens")):
            check.add(f"{prefix}rule.row", f"{row!r} belongs to lens {formula.ROWS[row].lens!r}")
        elif row in formula.ROWS and formula.ROWS[row].lens is None:
            check.add(f"{prefix}rule.row", f"cite {formula.JUDGED!r}; code picks the judged row")
        check.text(rule.get("ref"), f"{prefix}rule.ref")
    if "source" in finding:
        _check_source(check, finding["source"], f"{prefix}source")
    if "location" in finding:
        _check_location(
            check, finding["location"], f"{prefix}location", subject=subject, scopes=SCOPES
        )
    if "language" in finding:
        check.choice(finding["language"], formula.LANGUAGES, f"{prefix}language")
    if "statement" in finding and check.text(finding["statement"], f"{prefix}statement"):
        if "\n" in finding["statement"]:
            check.add(f"{prefix}statement", "must be one sentence on one line")
    source_kind = (finding.get("source") or {}).get("kind") if isinstance(
        finding.get("source"), Mapping) else None
    judged = isinstance(rule, Mapping) and rule.get("row") == formula.JUDGED
    for name, allowed in (
        ("consequence", formula.CONSEQUENCES),
        ("consequence_jev", formula.CONSEQUENCES),
        ("trigger", formula.TRIGGERS),
    ):
        value = finding.get(name)
        if value is None:
            if name != "consequence_jev" and name in finding and (judged or source_kind == "llm"):
                check.add(f"{prefix}{name}", "required on an LLM finding")
        else:
            check.choice(value, allowed, f"{prefix}{name}")
    if "evidence" in finding:
        check.choice(finding["evidence"], formula.EVIDENCE, f"{prefix}evidence")
    if "proof" in finding:
        _check_proof(check, finding, f"{prefix}proof")
    for name in ("introduced", "degraded", "unconfirmed"):
        if name in finding:
            check.boolean(finding[name], f"{prefix}{name}")
    reproduced_llm = source_kind == "llm" and finding.get("evidence") == "reproduced"
    has_jev = finding.get("consequence_jev") is not None
    if finding.get("unconfirmed") is True and (has_jev or not reproduced_llm):
        check.add(
            f"{prefix}unconfirmed",
            "marks only a reproduced LLM finding that Jev could not answer",
        )
    if reproduced_llm and not has_jev and finding.get("unconfirmed") is not True:
        check.add(f"{prefix}unconfirmed", "required true when Jev gave no consequence")
    if "merge_outcome" in finding:
        _check_merge_outcome(check, finding["merge_outcome"], f"{prefix}merge_outcome")
    if isinstance(rule, Mapping) and rule.get("row") == SECRET_ROW:
        for name in _secret_fields(finding):
            check.add(f"{prefix}{name}", "a secret-scanner finding carries its location, never the secret")
        proof = finding.get("proof")
        if isinstance(proof, Mapping) and "output" in proof:
            check.add(f"{prefix}proof.output", "a secret-scanner finding references output by sha256")
    if "id" in finding and isinstance(rule, Mapping) and isinstance(finding.get("location"), Mapping):
        expected = finding_identity(str(finding.get("lens")), rule, finding["location"])
        if not isinstance(finding["id"], str) or not _IDENTITY.match(finding["id"]):
            check.add(f"{prefix}id", "must be rf: and 32 hex characters")
        elif finding["id"] != expected:
            check.add(f"{prefix}id", f"does not match the computed identity {expected}")


def _check_measurement(check: _Check, record: Any, prefix: str = "", *, stored: bool = False) -> None:
    if not check.mapping(record, prefix.rstrip(".") or "record"):
        return
    check.required(record, REQUIRED["measurement"], prefix)
    _check_header(check, record, "measurement", prefix)
    if "lens" in record:
        check.choice(record["lens"], formula.LENSES, f"{prefix}lens")
    if "row" in record and record["row"] not in formula.ROWS:
        check.add(f"{prefix}row", f"{record['row']!r} is not a row the formula knows")
    tool = record.get("tool")
    if "tool" in record and check.mapping(tool, f"{prefix}tool"):
        check.text(tool.get("name"), f"{prefix}tool.name")
        check.text(tool.get("version"), f"{prefix}tool.version")
    if "language" in record:
        check.choice(record["language"], formula.LANGUAGES, f"{prefix}language")
    if "metric" in record:
        check.text(record["metric"], f"{prefix}metric")
    for name in ("value", "threshold"):
        if name in record:
            check.number(record[name], f"{prefix}{name}")
    if "direction" in record:
        check.choice(record["direction"], DIRECTIONS, f"{prefix}direction")
    if stored:
        if "condition" not in record:
            check.add(f"{prefix}condition", "required on a measurement in a stored review run")
        else:
            check.choice(record["condition"], CONDITIONS, f"{prefix}condition")
    elif "condition" in record:
        check.add(f"{prefix}condition", "code computes it; a measurement is handed in without it")


def _check_where_to_look(check: _Check, record: Any, prefix: str = "") -> None:
    if not check.mapping(record, prefix.rstrip(".") or "record"):
        return
    check.required(record, REQUIRED["where_to_look"], prefix)
    _check_header(check, record, "where_to_look", prefix)
    if "lens" in record:
        check.choice(record["lens"], formula.LENSES, f"{prefix}lens")
    if "location" in record:
        _check_location(
            check, record["location"], f"{prefix}location", subject="code",
            scopes=("lines", "whole-project"),
        )
    if "language" in record:
        check.choice(record["language"], formula.LANGUAGES, f"{prefix}language")
    questions = record.get("questions")
    if "questions" in record and check.array(questions, f"{prefix}questions"):
        if not questions:
            check.add(f"{prefix}questions", "at least one question fired")
        for index, question in enumerate(questions):
            path = f"{prefix}questions.{index}"
            if check.mapping(question, path):
                check.text(question.get("id"), f"{path}.id")
                probability = question.get("probability")
                if check.number(probability, f"{path}.probability") and not 0 <= probability <= 1:
                    check.add(f"{path}.probability", "must be between 0 and 1")
    classifier = record.get("classifier")
    if "classifier" in record and check.mapping(classifier, f"{prefix}classifier"):
        check.text(classifier.get("name"), f"{prefix}classifier.name")
        check.text(classifier.get("model"), f"{prefix}classifier.model")
    if "degraded" in record:
        check.boolean(record["degraded"], f"{prefix}degraded")
    answer = record.get("answer")
    if "answer" in record and check.mapping(answer, f"{prefix}answer"):
        if check.choice(answer.get("kind"), ("finding", "cleared"), f"{prefix}answer.kind"):
            if answer["kind"] == "finding":
                if not isinstance(answer.get("finding_id"), str) or not _IDENTITY.match(
                    answer["finding_id"]
                ):
                    check.add(f"{prefix}answer.finding_id", "must be a finding identity")
            else:
                check.text(answer.get("reason"), f"{prefix}answer.reason")


def _check_degraded_inputs(check: _Check, value: Any, path: str) -> None:
    if not check.array(value, path):
        return
    for index, entry in enumerate(value):
        item = f"{path}.{index}"
        if not check.mapping(entry, item):
            continue
        if "finding_id" in entry:
            continue
        check.choice(entry.get("lens"), formula.LENSES, f"{item}.lens")
        check.choice(entry.get("language"), formula.LANGUAGES, f"{item}.language")
        check.text(entry.get("input"), f"{item}.input")
        check.text(entry.get("reason"), f"{item}.reason")


def _check_may_block(check: _Check, value: Any, path: str, lens: str | None = None) -> None:
    if not check.mapping(value, path):
        return
    if lens is not None:
        for language, answer in value.items():
            check.choice(language, formula.LANGUAGES, f"{path}.{language}")
            check.boolean(answer, f"{path}.{language}")
        return
    for name, answers in value.items():
        check.choice(name, formula.LENSES, f"{path}.{name}")
        _check_may_block(check, answers, f"{path}.{name}", lens=str(name))


def _check_lens_grade(check: _Check, record: Any, prefix: str = "") -> None:
    if not check.mapping(record, prefix.rstrip(".") or "record"):
        return
    check.required(record, REQUIRED["lens_grade"], prefix)
    _check_header(check, record, "lens_grade", prefix)
    if "lens" in record:
        check.choice(record["lens"], formula.LENSES, f"{prefix}lens")
    for name in ("blocks", "fix_later", "notes"):
        if name in record:
            check.integer(record[name], f"{prefix}{name}")
    if "grade" in record and check.choice(record["grade"], formula.GRADES, f"{prefix}grade"):
        if all(isinstance(record.get(n), int) for n in ("blocks", "fix_later")):
            expected = formula.grade(record["blocks"], record["fix_later"])
            if record["grade"] != expected:
                check.add(f"{prefix}grade", f"the counts give {expected}")
    if "degraded_inputs" in record:
        _check_degraded_inputs(check, record["degraded_inputs"], f"{prefix}degraded_inputs")
    if "may_block" in record:
        _check_may_block(check, record["may_block"], f"{prefix}may_block", lens=record.get("lens"))


def _check_builder_record(check: _Check, record: Any, prefix: str = "") -> None:
    if not check.mapping(record, prefix.rstrip(".") or "record"):
        return
    check.required(record, REQUIRED["builder_record"], prefix)
    _check_header(check, record, "builder_record", prefix)
    if "unit" in record:
        check.text(record["unit"], f"{prefix}unit")
    criteria = record.get("acceptance_criteria")
    if "acceptance_criteria" in record and check.array(criteria, f"{prefix}acceptance_criteria"):
        for index, criterion in enumerate(criteria):
            path = f"{prefix}acceptance_criteria.{index}"
            if check.mapping(criterion, path):
                check.text(criterion.get("id"), f"{path}.id")
                check.text(criterion.get("text"), f"{path}.text")
                checks = criterion.get("checks")
                if check.array(checks, f"{path}.checks"):
                    for position, name in enumerate(checks):
                        check.text(name, f"{path}.checks.{position}")
    declarations = record.get("declarations")
    if "declarations" in record and check.array(declarations, f"{prefix}declarations"):
        for index, declaration in enumerate(declarations):
            path = f"{prefix}declarations.{index}"
            if check.mapping(declaration, path):
                check.text(declaration.get("question"), f"{path}.question")
                check.boolean(declaration.get("applies"), f"{path}.applies")
                if declaration.get("applies") is True:
                    check.text(declaration.get("proving_test"), f"{path}.proving_test")
    reasons = record.get("reasons")
    if "reasons" in record and check.array(reasons, f"{prefix}reasons"):
        for index, reason in enumerate(reasons):
            path = f"{prefix}reasons.{index}"
            if check.mapping(reason, path):
                check.choice(reason.get("kind"), formula.REASON_KINDS, f"{path}.kind")
                if not isinstance(reason.get("finding_id"), str) or not _IDENTITY.match(
                    reason["finding_id"]
                ):
                    check.add(f"{path}.finding_id", "must be a finding identity")
                check.text(reason.get("text"), f"{path}.text")


def _formula_inputs(run: Mapping[str, Any]) -> dict[str, Any]:
    """A stored run's inputs, with every computed field removed, for recomputation."""
    findings = [
        {key: value for key, value in finding.items() if key not in formula.COMPUTED_FINDING_KEYS}
        for finding in run.get("findings") or []
        if isinstance(finding, Mapping)
    ]
    measurements = [
        {key: value for key, value in item.items() if key != "condition"}
        for item in run.get("measurements") or []
        if isinstance(item, Mapping)
    ]
    return {
        "findings": findings,
        "measurements": measurements,
        "builder_records": list(run.get("builder_records") or []),
        "may_block": dict(run.get("may_block") or {}),
        "degraded_inputs": list(run.get("degraded_inputs") or []),
    }


def _check_review_run(check: _Check, record: Any) -> None:
    if not check.mapping(record, "record"):
        return
    check.required(record, REQUIRED["review_run"], "")
    _check_header(check, record, "review_run", "")
    if "loop" in record and record["loop"] != STORED_LOOP:
        check.add("loop", f"must be {STORED_LOOP!r} when present")
    if "card" in record:
        check.integer(record["card"], "card", 1)
    for name in ("repo", "base", "head", "saga_version"):
        if name in record:
            check.text(record[name], name)
    if "round" in record:
        check.integer(record["round"], "round", 1)
    versions = record.get("tool_versions")
    if "tool_versions" in record and check.mapping(versions, "tool_versions"):
        for name, version in versions.items():
            check.text(version, f"tool_versions.{name}")
    usage = record.get("usage")
    if "usage" in record and check.mapping(usage, "usage"):
        for name in USAGE_FIELDS:
            if name not in usage:
                check.add(f"usage.{name}", "required")
            elif check.number(usage[name], f"usage.{name}") and usage[name] < 0:
                check.add(f"usage.{name}", "must not be negative")
    before = len(check.problems)
    for name, walker in (
        ("findings", lambda c, item, p: _check_finding(c, item, p, stored=True)),
        ("measurements", lambda c, item, p: _check_measurement(c, item, p, stored=True)),
        ("where_to_look", _check_where_to_look),
        ("lens_grades", _check_lens_grade),
        ("builder_records", _check_builder_record),
    ):
        items = record.get(name)
        if name in record and check.array(items, name):
            for index, item in enumerate(items):
                walker(check, item, f"{name}.{index}.")
    if "may_block" in record:
        _check_may_block(check, record["may_block"], "may_block")
    if "degraded_inputs" in record:
        _check_degraded_inputs(check, record["degraded_inputs"], "degraded_inputs")
    raw = record.get("raw_outputs")
    if "raw_outputs" in record and check.array(raw, "raw_outputs"):
        for index, entry in enumerate(raw):
            path = f"raw_outputs.{index}"
            if check.mapping(entry, path):
                check.text(entry.get("tool"), f"{path}.tool")
                check.text(entry.get("path"), f"{path}.path")
                if not isinstance(entry.get("sha256"), str) or not _SHA256.match(entry["sha256"]):
                    check.add(f"{path}.sha256", "must be 64 lowercase hex characters")
    if len(check.problems) != before or not all(name in record for name in REQUIRED["review_run"]):
        return  # recompute only a run whose parts are each well formed
    _check_recomputation(check, record)


def _check_recomputation(check: _Check, run: Mapping[str, Any]) -> None:
    """Refuse a stored run whose computed fields differ from a fresh computation (KTD2)."""
    try:
        fresh = formula.compute(_formula_inputs(run))
    except formula.FormulaError as exc:
        check.add("findings", str(exc))
        return
    by_id = {finding["id"]: finding for finding in fresh["findings"]}
    for index, finding in enumerate(run["findings"]):
        expected = by_id.get(finding.get("id"), {})
        for key in formula.COMPUTED_FINDING_KEYS:
            if finding.get(key) != expected.get(key):
                check.add(
                    f"findings.{index}.{key}",
                    f"finding {finding.get('id')} stores {finding.get(key)!r}; the formula "
                    f"gives {expected.get(key)!r}",
                )
    for index, measurement in enumerate(run["measurements"]):
        if measurement.get("condition") != formula.measurement_condition(measurement):
            check.add(f"measurements.{index}.condition", "does not match the threshold")
    if _canonical(run["lens_grades"]) != _canonical(fresh["lens_grades"]):
        check.add("lens_grades", "do not match the formula's grades for these findings")
    if _canonical(run["merge"]) != _canonical(fresh["merge"]):
        check.add("merge", "does not match the formula's merge answer for these findings")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def validate(record: Any) -> list[str]:
    """Every problem with *record*, one ``<field path>: <why>`` line each; empty when well formed."""
    check = _Check()
    if not isinstance(record, Mapping):
        check.add("record", "must be a JSON object")
        return check.problems
    kind = record.get("kind")
    if kind not in KINDS:
        check.add("kind", f"{kind!r} is not one of {', '.join(KINDS)}")
        return check.problems
    if kind == "finding":
        _check_finding(check, record)
    elif kind == "measurement":
        _check_measurement(check, record)
    elif kind == "where_to_look":
        _check_where_to_look(check, record)
    elif kind == "lens_grade":
        _check_lens_grade(check, record)
    elif kind == "review_run":
        _check_review_run(check, record)
    else:
        _check_builder_record(check, record)
    return check.problems


# ---------------------------------------------------------------------------
# Building and storing
# ---------------------------------------------------------------------------

#: The run metadata an inputs file carries, copied onto the review run as it is.
RUN_FIELDS: tuple[str, ...] = (
    "card",
    "repo",
    "base",
    "head",
    "saga_version",
    "round",
    "tool_versions",
    "usage",
    "where_to_look",
    "raw_outputs",
)


def build_run(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a review's inputs, compute them, and return the review run, validated whole.

    The findings and measurements are in their input form; any computed field on them is refused.
    """
    problems: list[str] = []
    for index, finding in enumerate(inputs.get("findings") or []):
        problems.extend(f"findings.{index}.{line}" for line in validate(finding))
    for index, measurement in enumerate(inputs.get("measurements") or []):
        problems.extend(f"measurements.{index}.{line}" for line in validate(measurement))
    for index, builder in enumerate(inputs.get("builder_records") or []):
        problems.extend(f"builder_records.{index}.{line}" for line in validate(builder))
    if problems:
        raise ReviewRecordError(problems)
    computed = formula.compute(inputs)
    run: dict[str, Any] = {"kind": "review_run", "schema": SCHEMA}
    for name in RUN_FIELDS:
        if name in inputs:
            run[name] = copy.deepcopy(inputs[name])
    run.setdefault("where_to_look", [])
    run.setdefault("raw_outputs", [])
    run.update(
        {
            "findings": computed["findings"],
            "measurements": computed["measurements"],
            "lens_grades": computed["lens_grades"],
            "builder_records": copy.deepcopy(list(inputs.get("builder_records") or [])),
            "may_block": copy.deepcopy(dict(inputs.get("may_block") or {})),
            "degraded_inputs": computed["degraded_inputs"],
            "merge": computed["merge"],
        }
    )
    problems = validate(run)
    if problems:
        raise ReviewRecordError(problems)
    return run


def _row_matches(row: Any, unit: str) -> bool:
    return isinstance(row, dict) and any(
        str(row.get(key) or "") == unit for key in ("id", "name", "unit_id")
    )


def builder_records_on(record: run_record.RunRecord) -> list[dict[str, Any]]:
    """Every unit row's builder record, in row order."""
    return [
        row[ROW_KEY]
        for row in record.units
        if isinstance(row, dict) and isinstance(row.get(ROW_KEY), dict)
    ]


def record_run(store_root: Path, issue: int, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Compute and append a review run to *issue*'s ``review_cycles``, under the record's lock.

    When *inputs* carries no ``builder_records``, the ones on the record's unit rows are used, read
    under the lock. Returns the stored run.
    """
    stored: dict[str, Any] = {}

    def change(existing: run_record.RunRecord | None) -> run_record.RunRecord:
        if existing is None:
            raise run_record.RunRecordError(f"no record for issue {issue}")
        given = dict(inputs)
        if "builder_records" not in given:
            given["builder_records"] = builder_records_on(existing)
        run = build_run(given)
        stored.update(run)
        entry = {**run, "loop": STORED_LOOP}
        return run_record.RunRecord(
            **{**existing.__dict__, "review_cycles": [*existing.review_cycles, entry]}
        )

    run_record.update(store_root, issue, change)
    return stored


def record_builder(
    store_root: Path, issue: int, unit: str, builder: Mapping[str, Any]
) -> run_record.RunRecord:
    """Set *unit*'s ``builder_record`` on *issue*'s record, under its lock, replacing any earlier.

    A missing row is created as ``{"id": unit}`` only when orchestrate does not drive the record;
    orchestrate owns which rows exist there, so a missing row is refused (``MissingUnitError``).
    """
    problems = validate(builder)
    if not problems and builder.get("unit") != unit:
        problems = [f"unit: names {builder.get('unit')!r}, but the row is {unit!r}"]
    if problems:
        raise ReviewRecordError(problems)
    written: dict[str, run_record.RunRecord] = {}

    def change(existing: run_record.RunRecord | None) -> run_record.RunRecord:
        if existing is None:
            raise run_record.RunRecordError(f"no record for issue {issue}")
        units: list[Any] = [dict(r) if isinstance(r, dict) else r for r in existing.units]
        row: dict[str, Any] | None = next((r for r in units if _row_matches(r, unit)), None)
        if row is None:
            if "orchestrate" in existing.extra:
                raise MissingUnitError(
                    f"unit {unit} has no row in issue {issue}'s record, which orchestrate drives; "
                    "orchestrate adds the row, then record the builder record again"
                )
            row = {"id": unit}
            units.append(row)
        row[ROW_KEY] = copy.deepcopy(dict(builder))
        updated = run_record.RunRecord(**{**existing.__dict__, "units": units})
        written["record"] = updated
        return updated

    run_record.update(store_root, issue, change)
    return written["record"]


def runs_on(record: run_record.RunRecord) -> list[dict[str, Any]]:
    """The stored review runs, oldest first."""
    return [
        entry
        for entry in record.review_cycles
        if isinstance(entry, dict) and entry.get("kind") == "review_run"
        and entry.get("loop") == STORED_LOOP
    ]


def builder_record_for(record: run_record.RunRecord, unit: str) -> dict[str, Any] | None:
    """*unit*'s builder record, or ``None``."""
    row = next((r for r in record.units if _row_matches(r, unit)), None)
    value = row.get(ROW_KEY) if isinstance(row, dict) else None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_records.py",
        description=(
            "Validate saga's review records, and store computed review runs and builder records "
            "in an issue's run record. Exit 0 accepted; 1 refused, one '<field>: <why>' line per "
            "problem on standard error; 2 unreadable file, unknown kind or no record; 5 a builder "
            "record for a unit orchestrate has not added yet."
        ),
    )
    parser.add_argument(
        "--store-root",
        default=None,
        help="Override the resolved run-record store directory (tests and cross-checkout use).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate", help="Validate one record of any kind.")
    check.add_argument("file", type=Path)
    run = sub.add_parser("record-run", help="Compute a review's inputs and store the review run.")
    run.add_argument("--issue", type=int, required=True)
    run.add_argument("inputs", type=Path)
    builder = sub.add_parser("record-builder", help="Store a unit's builder record.")
    builder.add_argument("--issue", type=int, required=True)
    builder.add_argument("--unit", required=True)
    builder.add_argument("file", type=Path)
    return parser


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _store_root(args: argparse.Namespace) -> Path:
    if args.store_root:
        return Path(args.store_root).resolve()
    return run_record.resolve_store_root()


def _refused(problems: list[str]) -> int:
    for line in problems:
        print(line, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.file if args.command != "record-run" else args.inputs
    try:
        data = _read(path)
    except (OSError, ValueError) as exc:
        print(f"review_records: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "validate":
            if not isinstance(data, Mapping) or data.get("kind") not in KINDS:
                print(f"kind: {path} names no known record kind", file=sys.stderr)
                return 2
            problems = validate(data)
            return _refused(problems) if problems else 0
        if not isinstance(data, Mapping):
            print(f"review_records: {path} is not a JSON object", file=sys.stderr)
            return 2
        if args.command == "record-run":
            record_run(_store_root(args), args.issue, data)
        else:
            record_builder(_store_root(args), args.issue, args.unit, data)
        return 0
    except ReviewRecordError as exc:
        return _refused(exc.problems)
    except formula.FormulaError as exc:
        return _refused([str(exc)])
    except MissingUnitError as exc:
        print(f"review_records: {exc}", file=sys.stderr)
        return 5
    except run_record.RunRecordError as exc:
        print(f"review_records: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
