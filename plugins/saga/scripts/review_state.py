#!/usr/bin/env python3
"""One review's state and pending choices as one document (issue 164).

Every screen reads what this script prints, and every answer goes back through
it. ``render`` builds the ``review_state.v1`` document on demand from the
stored C1 review runs — JSON for panes, Markdown with numbered questions for
every other harness. ``answers`` validates an answers file before writing
anything, then records fix-later outcomes on the stored findings and the
blocking-merge decision beside them. ``publish`` posts one pull-request
comment per round, the final one carrying the fix-later checklist.

Filing is mission-control's lane: this script prepares mission-control drafts
and hands them to ``sdlc_manager.py``. It never creates an issue itself.

Standard library only. Module scope imports nothing ``--help`` does not need.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess  # nosec B404 - fixed argv, no shell
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_formula as formula  # noqa: E402  (after the sys.path shim, by design)
import review_records  # noqa: E402
import run_record  # noqa: E402

#: What ``render --render json`` prints.
SCHEMA = "review_state.v1"

#: The round that ends the loop with blocking items left (plan.md, Change 8).
ROUND_LIMIT = 3

#: The final comment's first line, which C16's outcome job matches.
CHECKLIST_MARKER = "<!-- saga:fix-later-checklist -->"

#: The pending-choice key for blocking items at the limit or an early stop.
MERGE_CHOICE = "merge-blocking"

#: The ``fix-later:<finding-id>`` pending-choice prefix.
FIX_LATER_PREFIX = "fix-later:"

#: The profile key (``repository_profile.v1``) for the unattended default.
PROFILE_KEY = "fix_later_unattended_default"
PROFILE_VALUES = ("leave", "file")

#: Consequence groups, most severe first (``references/review-records.md``).
HARM = frozenset(
    {
        "data-lost-or-corrupted",
        "money-or-resources-wrongly-moved",
        "security-boundary-crossed",
        "two-holders-of-one-exclusive-thing",
        "wrong-result-reported-as-success",
        "required-behaviour-missing",
        "break-in-supported-use",
    }
)
VISIBLE = frozenset({"fails-loudly-and-recoverably", "misleads-a-person"})
UPKEEP = frozenset({"costs-future-work", "style"})

#: Consequence group to filed-issue risk tier.
RISK_BY_GROUP = {"harm": "high", "visible": "medium", "upkeep": "low"}

#: Filing routing: the values this program's own cards carry. A later card makes
#: them per-repo when saga reviews outside this program.
FILE_TEAM = "asgard"
FILE_PROJECT = "operations"
FILE_STAGE = "Shaping"
FILE_STATUS = "Discovering"

#: The fix-later choices.
CHOICES = ("fix-now", "file-as-issue", "leave")

#: The stored review run's kind (``review_records.py`` stores ``kind`` and
#: ``loop`` under the same ``"review_run"`` token).
KIND_REVIEW_RUN = "review_run"

#: Exit codes: the table ``functional_checks.py`` shares with the record.
EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_UNKNOWN_VERSION = 3


class ReviewStateError(ValueError):
    """A refusal this module owns. The command line maps it to exit 2."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# The intent envelope, read small and strict
# ---------------------------------------------------------------------------
#
# Full-schema validation lives at capture (mission-control readiness blocks an
# invalid envelope). This module reads two run-start fields — the run mode and
# the merge gate — through the closed key set, and refuses anything else. It
# deliberately does not import the envelope module: that import shadows
# ``sys.modules`` through its bundle shim, and nothing here needs more than
# these two fields.

ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "run_mode",
        "ceremony_gates",
        "source",
        "authored_at",
        "authored_by",
        "backends_permitted",
        "degrade_policy",
        "spend_envelope",
    }
)
ENVELOPE_FENCE = "intent-envelope"


def validate_envelope(data: Any, where: str) -> dict[str, Any]:
    """Check an envelope's closed shape and return ``{"run_mode", "merge"}``."""
    if not isinstance(data, Mapping):
        raise ReviewStateError(f"{where} must hold a JSON object")
    unknown = sorted(set(data) - ENVELOPE_KEYS)
    if unknown:
        raise ReviewStateError(f"{where} carries unknown envelope fields: {', '.join(unknown)}")
    version = data.get("schema_version", 1)
    if version != 1:
        raise ReviewStateError(f"{where} names schema_version {version!r}, not 1")
    run_mode = data.get("run_mode")
    if run_mode not in ("attended", "unattended"):
        raise ReviewStateError(f"{where} names run_mode {run_mode!r}, not attended or unattended")
    gates = data.get("ceremony_gates", {})
    if not isinstance(gates, Mapping):
        raise ReviewStateError(f"{where} carries ceremony_gates that are not an object")
    merge = gates.get("merge", "gate")
    if merge not in ("gate", "auto"):
        raise ReviewStateError(f"{where} names merge {merge!r}, not gate or auto")
    return {"run_mode": run_mode, "merge": merge}


def load_envelope_file(path: Path) -> dict[str, Any]:
    """Read and validate an envelope file. Missing is refused, never guessed."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ReviewStateError(f"no envelope at {path}") from None
    except json.JSONDecodeError as exc:
        raise ReviewStateError(f"{path} is not valid JSON: {exc}") from exc
    return validate_envelope(raw, str(path))


def extract_envelope_from_body(body: str, where: str) -> dict[str, Any]:
    """The issue body's one fenced envelope block, parsed and validated."""
    blocks: list[str] = []
    lines = body.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == f"```{ENVELOPE_FENCE}":
            index += 1
            content: list[str] = []
            while index < len(lines) and lines[index].strip() != "```":
                content.append(lines[index])
                index += 1
            if index >= len(lines):
                raise ReviewStateError(f"{where} has an unterminated {ENVELOPE_FENCE} block")
            blocks.append("\n".join(content))
        index += 1
    if not blocks:
        raise ReviewStateError(f"{where} carries no {ENVELOPE_FENCE} block")
    if len(blocks) > 1:
        raise ReviewStateError(f"{where} carries {len(blocks)} {ENVELOPE_FENCE} blocks, not one")
    try:
        return validate_envelope(json.loads(blocks[0]), where)
    except json.JSONDecodeError as exc:
        raise ReviewStateError(f"{where} holds an envelope that is not JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Records in, review runs out
# ---------------------------------------------------------------------------


def load_record_file(path: Path) -> run_record.RunRecord:
    """Read a record from an explicit path, with ``run_record.py``'s refusals."""
    if not path.is_file():
        raise ReviewStateError(f"no record at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewStateError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReviewStateError(f"{path} does not hold a JSON object")
    try:
        return run_record.from_dict(raw, path=path, warn=None)
    except run_record.UnknownRecordVersionError:
        raise
    except run_record.RunRecordError as exc:
        raise ReviewStateError(str(exc)) from exc


def save_record_file(path: Path, record: run_record.RunRecord) -> Path:
    """Write *record* to *path* with the record's atomic replace."""
    payload = run_record.to_dict(
        run_record.RunRecord(
            **{
                **record.__dict__,
                "created_at": record.created_at or _utc_now(),
                "updated_at": _utc_now(),
            }
        )
    )
    return run_record.write_json_atomic(path, payload)


def as_dict(record: run_record.RunRecord | Mapping[str, Any]) -> dict[str, Any]:
    """A record as plain JSON, whichever form it arrived in."""
    if isinstance(record, Mapping):
        return dict(record)
    return run_record.to_dict(record)


def review_runs(record: run_record.RunRecord | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every stored C1 review run, oldest first. Nothing else qualifies."""
    raw = as_dict(record)
    cycles = raw.get("review_cycles")
    if not isinstance(cycles, list):
        return []
    return [
        entry
        for entry in cycles
        if isinstance(entry, dict) and entry.get("kind") == KIND_REVIEW_RUN
    ]


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def is_guard(finding: Mapping[str, Any]) -> bool:
    """A harm the security lens's LLM traced but could not reproduce.

    The LLM's own consequence pick decides: when it names a harm and the
    evidence is traced or suspected rather than reproduced, the security guard
    files it, attended or not, unless the operator chose fix now.
    """
    if finding.get("lens") != "security":
        return False
    source = finding.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "llm":
        return False
    if finding.get("consequence") not in HARM:
        return False
    return finding.get("evidence") in ("traced", "suspected")


def consequence_group(finding: Mapping[str, Any]) -> str:
    """The finding's consequence group: harm, visible or upkeep."""
    consequence = finding.get("consequence")
    if consequence in HARM:
        return "harm"
    if consequence in VISIBLE:
        return "visible"
    return "upkeep"


def _blocking_of(run: Mapping[str, Any]) -> list[str]:
    merge = run.get("merge")
    blocking = merge.get("blocking") if isinstance(merge, Mapping) else []
    return [str(item) for item in blocking or []]


def round_state(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Where the loop stands: the limit, an early stop, and per-round deltas."""
    blocking_sets = [set(_blocking_of(run)) for run in runs]
    newest_round = int(runs[-1].get("round", 0)) if runs else 0
    at_limit = bool(runs) and newest_round >= ROUND_LIMIT
    early_stop = (
        len(blocking_sets) >= 2
        and bool(blocking_sets[-1])
        and blocking_sets[-1] == blocking_sets[-2]
    )
    deltas = []
    for position in range(1, len(runs)):
        before, after = blocking_sets[position - 1], blocking_sets[position]
        deltas.append(
            {
                "round": runs[position].get("round"),
                "new_blocking": sorted(after - before),
                "cleared_blocking": sorted(before - after),
            }
        )
    return {"at_limit": at_limit, "early_stop": early_stop, "deltas": deltas}


def merge_display(
    runs: Sequence[Mapping[str, Any]], envelope: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Whether the merge waits, from the round rules and the envelope's gate.

    Blocking items at the round limit or an early stop always wait: only the
    operator can merge with a reason or stop the card. Otherwise the envelope's
    merge setting decides — but ``auto`` still waits until the newest run's
    merge answer allows it, so an unattended merge never lands on open
    blocking items. Fix-later choices never hold a merge. Without an envelope
    the setting is unknown, so the merge waits rather than guessing.
    """
    state = round_state(runs)
    blocking = _blocking_of(runs[-1]) if runs else []
    pending = bool(blocking) and (state["at_limit"] or state["early_stop"])
    if pending:
        where = "the round limit" if state["at_limit"] else "an early stop"
        return {
            "waiting": True,
            "reason": (
                f"{len(blocking)} blocking items left at {where} await the operator: "
                "merge with a recorded reason or stop the card"
            ),
        }
    if envelope is None:
        return {
            "waiting": True,
            "reason": "the envelope's merge setting is unknown here, so this view cannot say the merge is free to proceed",
        }
    if envelope.get("merge") == "gate":
        return {"waiting": True, "reason": "the envelope holds the merge for the operator"}
    newest = runs[-1] if runs else {}
    merge = newest.get("merge") if isinstance(newest.get("merge"), Mapping) else {}
    if merge.get("allowed") is True:
        return {
            "waiting": False,
            "reason": "no blocking items are left and the envelope allows the merge to proceed",
        }
    return {
        "waiting": True,
        "reason": (
            f"{len(blocking)} blocking items are left; "
            "auto merges once every lens is at C or better"
        ),
    }


def _finding_view(finding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": finding.get("id"),
        "lens": finding.get("lens"),
        "severity": finding.get("severity"),
        "statement": finding.get("statement"),
        "guard": is_guard(finding),
        "merge_outcome": copy.deepcopy(finding.get("merge_outcome")),
    }


def _lens_view(grade: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lens": grade.get("lens"),
        "grade": grade.get("grade"),
        "blocking": grade.get("blocks", 0),
        "fix_later": grade.get("fix_later", 0),
    }


def _where_view(item: Mapping[str, Any]) -> dict[str, Any]:
    location = item.get("location") if isinstance(item.get("location"), Mapping) else {}
    lines = location.get("lines") if isinstance(location.get("lines"), Mapping) else {}
    answer = item.get("answer") if isinstance(item.get("answer"), Mapping) else {}
    if answer.get("kind") == "finding":
        state: dict[str, Any] = {"state": "answered", "finding_id": answer.get("finding_id")}
    else:
        state = {"state": "cleared", "reason": answer.get("reason")}
    return {
        "lens": item.get("lens"),
        "location": f"{location.get('file')}:{lines.get('start')}-{lines.get('end')}",
        "questions": [
            question.get("id")
            for question in item.get("questions") or []
            if isinstance(question, Mapping)
        ],
        **state,
    }


def _summed_cost(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "seconds": 0}
    for run in runs:
        usage = run.get("usage")
        if not isinstance(usage, Mapping):
            continue
        for key in totals:
            value = usage.get(key, 0) or 0
            totals[key] = totals[key] + value
    totals["cost_usd"] = round(totals["cost_usd"], 4)
    return totals


def build_document(
    record: run_record.RunRecord | Mapping[str, Any],
    envelope: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The ``review_state.v1`` document for *record*'s stored review runs.

    Grades, severities and the merge answer come from C1's stored values; this
    function derives only presentation. With no review runs the document is the
    schema plus empty lists.
    """
    raw = as_dict(record)
    runs = review_runs(raw)
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "card": raw.get("issue"),
        "repo": raw.get("repo"),
        "round": None,
        "lenses": [],
        "findings": [],
        "pending_choices": [],
        "merge_blocking": [],
        "merge": {"waiting": True, "reason": "no review run is recorded yet"},
        "disputes": [],
        "consequence_disagreements": [],
        "unconfirmed": [],
        "where_to_look": [],
        "tools": {"ran": {}, "missing_notice": None, "missing_tools": []},
        "degraded_inputs": [],
        "rounds": [],
        "cost": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "seconds": 0},
        "unattended": None if envelope is None else envelope.get("run_mode") == "unattended",
    }
    if not runs:
        return document
    newest = runs[-1]
    document["round"] = newest.get("round")
    findings = [f for f in newest.get("findings", []) if isinstance(f, Mapping)]
    grades = [g for g in newest.get("lens_grades", []) if isinstance(g, Mapping)]
    order = {lens: position for position, lens in enumerate(formula.LENSES)}
    document["lenses"] = sorted(
        (_lens_view(g) for g in grades), key=lambda v: order.get(str(v["lens"]), 99)
    )
    document["findings"] = [_finding_view(f) for f in findings]
    blocking = _blocking_of(newest)
    state = round_state(runs)
    choices: list[str] = []
    if blocking and (state["at_limit"] or state["early_stop"]):
        choices.append(MERGE_CHOICE)
    choices.extend(
        f"{FIX_LATER_PREFIX}{finding.get('id')}"
        for finding in findings
        if finding.get("severity") == "fix-later"
    )
    document["pending_choices"] = choices
    document["merge_blocking"] = blocking
    document["merge"] = merge_display(runs, envelope)
    def _row(finding: Mapping[str, Any]) -> str:
        rule = finding.get("rule")
        return str(rule.get("row", "")) if isinstance(rule, Mapping) else ""

    document["disputes"] = [f.get("id") for f in findings if _row(f).endswith(".dispute")]
    document["consequence_disagreements"] = [
        {"id": f.get("id"), "llm": f.get("consequence"), "jev": f.get("consequence_jev")}
        for f in findings
        if "consequence-disagreement" in (f.get("flags") or [])
    ]
    document["unconfirmed"] = [
        f.get("id") for f in findings if "unconfirmed" in (f.get("flags") or [])
    ]
    document["where_to_look"] = [
        _where_view(item)
        for item in newest.get("where_to_look", [])
        if isinstance(item, Mapping)
    ]
    notice = (raw.get("admission") or {}).get("setup_notice") or {}
    document["tools"] = {
        "ran": dict(newest.get("tool_versions") or {}),
        "missing_notice": notice.get("text") or None,
        "missing_tools": list(notice.get("missing_tools") or []),
    }
    document["degraded_inputs"] = list(newest.get("degraded_inputs") or [])
    document["rounds"] = [
        {
            "round": runs[0].get("round"),
            "new_blocking": sorted(set(_blocking_of(runs[0]))),
            "cleared_blocking": [],
        },
        *state["deltas"],
    ]
    document["cost"] = _summed_cost(runs)
    return document


# ---------------------------------------------------------------------------
# The Markdown render
# ---------------------------------------------------------------------------


def _question_text(key: str, document: Mapping[str, Any]) -> str:
    if key == MERGE_CHOICE:
        count = len(document.get("merge_blocking", []))
        return (
            f"Merge with {count} blocking items left, or stop the card? "
            'Answer {"decision": "merge-with-reason", "reason": "<why>"} or '
            '{"decision": "stop-card"}.'
        )
    finding_id = key[len(FIX_LATER_PREFIX):]
    statement = next(
        (
            str(f.get("statement", ""))
            for f in document.get("findings", [])
            if isinstance(f, Mapping) and f.get("id") == finding_id
        ),
        finding_id,
    )
    return (
        f'Fix now, file as issue, or leave: "{statement}"? '
        'Answer "fix-now", "file-as-issue" or "leave".'
    )


def render_markdown(document: Mapping[str, Any]) -> str:
    """The document as fixed Markdown with numbered questions.

    Bold titles, never Markdown headings: a skill quotes this block, and a
    heading line inside a skill splits its gate-record sections.
    """
    lines: list[str] = []
    lines.append(f"**Review state.** `{SCHEMA}` · round {document.get('round', '—')}")
    lines.append("")
    lines.append("**Lenses**")
    lines.append("")
    lines.append("| Lens | Grade | Blocking | Fix later |")
    lines.append("|---|---|---|---|")
    for lens in document.get("lenses", []):
        lines.append(
            f"| {lens.get('lens')} | {lens.get('grade')} | {lens.get('blocking')} "
            f"| {lens.get('fix_later')} |"
        )
    lines.append("")
    lines.append("**Items**")
    lines.append("")
    disagreements = {
        entry.get("id"): entry
        for entry in document.get("consequence_disagreements", [])
        if isinstance(entry, Mapping)
    }
    disputes = set(document.get("disputes", []))
    unconfirmed = set(document.get("unconfirmed", []))
    for finding in document.get("findings", []):
        marks: list[str] = []
        if finding.get("id") in disputes:
            marks.append("[disputed builder declaration]")
        if finding.get("id") in disagreements:
            entry = disagreements[finding.get("id")]
            marks.append(
                f"[consequence disagreement: llm={entry.get('llm')} jev={entry.get('jev')}]"
            )
        if finding.get("id") in unconfirmed:
            marks.append("[unconfirmed consequence]")
        if finding.get("guard"):
            marks.append("[security guard]")
        outcome = (finding.get("merge_outcome") or {}).get("outcome")
        if outcome:
            marks.append(f"[outcome: {outcome}]")
        lines.append(
            f"- {finding.get('id')} [{finding.get('lens')}/{finding.get('severity')}] "
            f"{finding.get('statement')}"
            + (f" {' '.join(marks)}" if marks else "")
        )
    lines.append("")
    if document.get("where_to_look"):
        lines.append("**Where to look**")
        lines.append("")
        for item in document["where_to_look"]:
            if item.get("state") == "answered":
                detail = f"answered by {item.get('finding_id')}"
            else:
                detail = f"cleared: {item.get('reason')}"
            lines.append(
                f"- {item.get('location')} [{item.get('lens')}]: {detail} "
                f"({', '.join(item.get('questions', []))})"
            )
        lines.append("")
    tools = document.get("tools", {})
    lines.append("**Tools**")
    lines.append("")
    ran = tools.get("ran") or {}
    lines.append(f"Ran: {', '.join(f'{n} {v}' for n, v in sorted(ran.items())) or 'none'}")
    lines.append(tools.get("missing_notice") or "No tools are missing.")
    lines.append("")
    if document.get("degraded_inputs"):
        lines.append("**Degraded inputs**")
        lines.append("")
        for entry in document["degraded_inputs"]:
            lines.append(f"- {json.dumps(entry, sort_keys=True)}")
        lines.append("")
    if document.get("rounds"):
        lines.append("**Rounds**")
        lines.append("")
        for entry in document["rounds"]:
            lines.append(
                f"- Round {entry.get('round')}: "
                f"{len(entry.get('new_blocking', []))} new blocking, "
                f"{len(entry.get('cleared_blocking', []))} cleared"
            )
        lines.append("")
    cost = document.get("cost", {})
    lines.append(
        f"**Cost so far.** {cost.get('tokens_in', 0)} in / {cost.get('tokens_out', 0)} out tokens, "
        f"${cost.get('cost_usd', 0):.4f}, {cost.get('seconds', 0)}s"
    )
    lines.append("")
    merge = document.get("merge", {})
    lines.append(
        f"**Merge.** {'Waiting' if merge.get('waiting') else 'Free to proceed'} — {merge.get('reason')}"
    )
    lines.append("")
    lines.append("**Questions**")
    lines.append("")
    for number, key in enumerate(document.get("pending_choices", []), start=1):
        lines.append(f"Q{number}. {_question_text(key, document)} (answer: {key})")
    if not document.get("pending_choices"):
        lines.append("No questions are pending.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------

MERGE_DECISIONS = ("merge-with-reason", "stop-card")
MERGE_ENTRY_LOOP = "merge_confirmation"


def normalize_answers(payload: Any, where: str) -> tuple[dict[str, Any], bool]:
    """The answers file's strict shape: ``{"answers": {...}, "pane_timeout": bool}``."""
    if not isinstance(payload, Mapping):
        raise ReviewStateError(f"{where} must hold a JSON object")
    unknown = sorted(set(payload) - {"answers", "pane_timeout"})
    if unknown:
        raise ReviewStateError(f"{where} carries unknown fields: {', '.join(unknown)}")
    answers = payload.get("answers", {})
    if not isinstance(answers, Mapping):
        raise ReviewStateError(f"{where} carries answers that are not an object")
    timeout = payload.get("pane_timeout", False)
    if not isinstance(timeout, bool):
        raise ReviewStateError(f"{where} carries pane_timeout that is not true or false")
    return dict(answers), timeout


def load_answers_file(path: str) -> tuple[dict[str, Any], bool]:
    """Read answers from *path*, or standard input for ``-``."""
    if path == "-":
        text = sys.stdin.read()
        where = "the answers file"
    else:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ReviewStateError(f"no answers at {path}") from None
        where = path
    try:
        return normalize_answers(json.loads(text), where)
    except json.JSONDecodeError as exc:
        raise ReviewStateError(f"{where} is not valid JSON: {exc}") from exc


def _finding_by_id(newest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    findings = newest.get("findings", [])
    return {
        str(f.get("id")): f
        for f in findings
        if isinstance(f, Mapping) and f.get("id")
    }


def _recorded_merge(record: Mapping[str, Any]) -> dict[str, Any] | None:
    entries = [
        e
        for e in (record.get("review_cycles") or [])
        if isinstance(e, dict) and e.get("loop") == MERGE_ENTRY_LOOP
    ]
    return entries[-1] if entries else None


def check_answers(
    answers: Mapping[str, Any],
    timeout: bool,
    record: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> None:
    """Validate every answer against a fresh record. Refusals name the key."""
    if timeout and answers:
        raise ReviewStateError(
            "pane_timeout is true with answers present: a timeout carries no answers, "
            "and only the unattended rules apply"
        )
    if envelope.get("run_mode") == "unattended" and MERGE_CHOICE in answers:
        raise ReviewStateError(
            f"choice key {MERGE_CHOICE!r} cannot be answered in an unattended run: "
            "only the operator can merge with a reason or stop the card"
        )
    runs = review_runs(record)
    if not runs:
        if answers:
            raise ReviewStateError("no review run is recorded yet, so no answer applies")
        return
    document = build_document(record, envelope)
    pending = set(document["pending_choices"])
    for key in answers:
        if key not in pending:
            raise ReviewStateError(f"unknown choice key {key!r}")
    newest = runs[-1]
    by_id = _finding_by_id(newest)
    for key, choice in answers.items():
        if key == MERGE_CHOICE:
            _check_merge_answer(choice, _recorded_merge(record))
        else:
            finding = by_id.get(key[len(FIX_LATER_PREFIX):])
            _check_fix_later_answer(key, choice, finding)


def _check_fix_later_answer(key: str, choice: Any, finding: Mapping[str, Any] | None) -> None:
    if finding is None or finding.get("severity") != "fix-later":
        raise ReviewStateError(f"choice key {key!r} names no fix-later item")
    if choice not in CHOICES:
        raise ReviewStateError(
            f"choice key {key!r} names {choice!r}, not one of {', '.join(CHOICES)}"
        )
    recorded = (finding.get("merge_outcome") or {}).get("outcome")
    if recorded is None:
        return
    want = {"fix-now": "fixed-now", "file-as-issue": "filed", "leave": "left"}[str(choice)]
    if recorded != want:
        raise ReviewStateError(
            f"choice key {key!r} is already recorded {recorded}, not {want}"
        )


def _check_merge_answer(choice: Any, recorded: Mapping[str, Any] | None) -> None:
    if not isinstance(choice, Mapping):
        raise ReviewStateError(f"choice key {MERGE_CHOICE!r} must be an object")
    unknown = sorted(set(choice) - {"decision", "reason"})
    if unknown:
        raise ReviewStateError(
            f"choice key {MERGE_CHOICE!r} carries unknown fields: {', '.join(unknown)}"
        )
    decision = choice.get("decision")
    if decision not in MERGE_DECISIONS:
        raise ReviewStateError(
            f"choice key {MERGE_CHOICE!r} names decision {decision!r}, "
            f"not one of {', '.join(MERGE_DECISIONS)}"
        )
    reason = choice.get("reason", "")
    if decision == "merge-with-reason" and not str(reason).strip():
        raise ReviewStateError(
            f"choice key {MERGE_CHOICE!r} merges over blocking items with no reason"
        )
    if recorded is None:
        return
    if recorded.get("decision") != decision or (recorded.get("reason") or "") != str(reason or ""):
        raise ReviewStateError(
            f"choice key {MERGE_CHOICE!r} is already recorded "
            f"{recorded.get('decision')}, not {decision}"
        )


def stamp_fix_later(run: dict[str, Any], finding_id: str, outcome: dict[str, Any]) -> None:
    """Set *outcome* on the stored finding, then re-validate the stored run.

    ``record_run`` is never called for an update: it validates findings in
    input form and refuses any finding that already carries ``severity``.
    ``merge_outcome`` is not a computed key, so a whole-run ``validate`` still
    re-checks every recomputed field while accepting the outcome change.
    """
    for finding in run.get("findings", []):
        if isinstance(finding, dict) and finding.get("id") == finding_id:
            finding["merge_outcome"] = outcome
            break
    else:
        raise ReviewStateError(f"no stored finding {finding_id!r}")
    problems = review_records.validate(run)
    if problems:
        raise ReviewStateError(
            f"the run no longer validates after stamping {finding_id}: {problems[0]}"
        )


def mutate_record(
    record_file: Path | None,
    store_root: Path | None,
    issue: int | None,
    change: Callable[[run_record.RunRecord], Any],
) -> Any:
    """Run *change* under the record's lock, by explicit file or by issue."""
    if record_file is not None:
        with run_record.file_lock(record_file):
            record = load_record_file(record_file)
            result = change(record)
            save_record_file(record_file, record)
            return result
    assert store_root is not None and issue is not None
    box: dict[str, Any] = {}

    def locked(existing: run_record.RunRecord | None) -> run_record.RunRecord:
        if existing is None:
            raise ReviewStateError(f"no record for issue {issue}")
        box["result"] = change(existing)
        return existing

    run_record.update(store_root, issue, locked)
    return box["result"]


def _fresh_outcome(record: Mapping[str, Any], finding_id: str) -> str | None:
    runs = review_runs(record)
    if not runs:
        return None
    finding = _finding_by_id(runs[-1]).get(finding_id)
    if finding is None:
        return None
    return (finding.get("merge_outcome") or {}).get("outcome")


def _newest_run_entry(record: run_record.RunRecord) -> dict[str, Any]:
    runs = [e for e in record.review_cycles if isinstance(e, dict) and e.get("kind") == KIND_REVIEW_RUN]
    if not runs:
        raise ReviewStateError("no review run is recorded yet, so no answer applies")
    return runs[-1]


# ---------------------------------------------------------------------------
# Filing through mission-control
# ---------------------------------------------------------------------------
#
# Three steps per issue, each a subprocess of ``sdlc_manager.py`` run with a
# fresh temporary directory as the working directory: ``issue prepare`` with a
# complete defect body, the ``stage: Shaping`` fill-in on the generated draft
# (prepare has no ``--stage`` flag), then ``issue create-prepared --yes
# --skip-approval``. ``--skip-approval`` bypasses the U11 gate for one
# invocation; the basis is the operator's own file-as-issue choice when
# attended, the card's guard and ``file``-default policy when not.


class FilerError(ReviewStateError):
    """Mission-control filed nothing, or something unparseable happened."""


def _completed(
    argv: Sequence[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)  # nosec B603


Runner = Callable[..., Any]


def resolve_mission_control(explicit: str | None = None) -> Path:
    """The ``sdlc_manager.py`` to file through.

    An explicit flag wins, resolved absolute (the filer runs with a temporary
    working directory, where a relative path would point nowhere). Otherwise
    fleet-core's install resolution, the way ``board_progression.py`` resolves
    it — never the working tree, which during a review is the change under
    review. Imported lazily so ``--help`` stays standard-library only.
    """
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ReviewStateError(f"no mission-control script at {path}")
        return path.resolve()
    try:
        import board_progression  # noqa: PLC0415  (only when filing, by design)

        root, _rung = board_progression.resolve_mission_control_root()
    except (ImportError, RuntimeError) as exc:
        raise ReviewStateError(
            f"mission-control could not be resolved: {exc} "
            "(pass --mission-control, or set MISSION_CONTROL_ROOT)"
        ) from exc
    script = Path(root) / "scripts" / "sdlc_manager.py"
    if not script.is_file():
        raise ReviewStateError(
            f"mission-control resolved to {root}, which holds no scripts/sdlc_manager.py"
        )
    return script


def _fenced(text: str) -> str:
    """Finding-derived text, safe to embed: no fence can break out of it."""
    return "\n".join(line for line in text.splitlines() if "```" not in line).strip()


def _one_line(text: str, limit: int) -> str:
    single = " ".join(str(text).split())
    return single if len(single) <= limit else single[: limit - 1].rstrip() + "…"


def _finding_location(finding: Mapping[str, Any]) -> str:
    location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
    if location.get("scope") == "section":
        return f"{location.get('document')}, section {location.get('section')}"
    lines = location.get("lines") if isinstance(location.get("lines"), Mapping) else {}
    if lines:
        return f"{location.get('file')}:{lines.get('start')}-{lines.get('end')}"
    return str(location.get("file") or location.get("anchor") or "unknown location")


def defect_body(
    findings: Sequence[Mapping[str, Any]],
    *,
    repo: str,
    card: Any,
    revision: str,
) -> tuple[str, str]:
    """A complete defect card for *findings*: one item, or the bundle of many.

    Returns ``(title, body)``. Every required H3 section is present, the
    acceptance criteria name their check, and the Risk carries a tier plus a
    justification — the shape mission-control's readiness passes.
    """
    first = findings[0]
    tiers = [RISK_BY_GROUP[consequence_group(f)] for f in findings]
    tier = "high" if "high" in tiers else ("medium" if "medium" in tiers else "low")
    if len(findings) == 1:
        title = f"Review follow-up [{first.get('lens')}]: {_one_line(str(first.get('statement', '')), 100)}"
        objective = f"Fix the {first.get('lens')} finding {_one_line(str(first.get('statement', '')), 160)}."
    else:
        title = f"Follow-up: {len(findings)} fix-later items from the review of {repo}#{card}"
        objective = (
            f"Fix or answer the {len(findings)} fix-later items the review of "
            f"{repo}#{card} left at revision `{revision}`."
        )
    details: list[str] = []
    for finding in findings:
        proof = finding.get("proof") if isinstance(finding.get("proof"), Mapping) else {}
        if finding.get("evidence") == "reproduced":
            proof_text = str(proof.get("test") or proof.get("output") or "see the review run")
        elif finding.get("evidence") == "traced":
            proof_text = "; ".join(str(s) for s in proof.get("steps", []) or [])
        else:
            proof_text = "tool result; raw output stays on the reviewing machine"
        details.append(
            "```text\n"
            f"finding: {finding.get('id')}\n"
            f"lens: {finding.get('lens')}\n"
            f"location: {_fenced(_finding_location(finding))}\n"
            f"statement: {_fenced(str(finding.get('statement', '')))}\n"
            f"proof: {_fenced(proof_text)}\n"
            "```"
        )
    criteria = "\n\n".join(
        f"- [ ] `{finding.get('id')}` is fixed or answered: re-rendering the review "
        f"shows it no longer unanswered."
        for finding in findings
    )
    body = f"""### Objective

{objective}

### Intent

Filed from the saga code review of {repo}#{card} at revision `{revision}`.
Each item below is one fix-later finding with its identity, location and proof.

{chr(10).join(details)}

### Out-of-scope / non-goals

Nothing beyond the listed findings; a wider fix gets its own issue.

### Inputs inventory

The findings above, the reviewed revision `{revision}`, and the review run in the run record.

### Files expected to change

{chr(10).join(f"- `{_finding_location(f).split(':')[0]}`" for f in findings)}

### Tests to add or update

- Add or update the test that covers each finding's lines, and name it on this issue.

### Failure modes / pre-mortem

The fix silences the finding without removing the cause; the re-render check below catches that.

### Stop conditions

Stop if a finding proves unreachable or already fixed elsewhere; record the proof here.

### Acceptance criteria

{criteria}

### Verification

```bash
python3 plugins/saga/scripts/review_state.py render --issue {card} --repo {repo} --render markdown
```

### Risk

{tier}
{"A traced harm to another tenant's data or to resources justifies urgent follow-up." if tier == "high" else "A visible defect or upkeep item justifies ordinary follow-up."}

### Context library links

_none_
"""
    return title, body


def _tail(output: str, limit: int = 300) -> str:
    return output.strip().splitlines()[-1][:limit] if output.strip() else "no output"


def _add_stage(draft: Path) -> None:
    """The R3b fill-in: a ``stage:`` line in the draft front matter."""
    text = draft.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise FilerError(f"generated draft {draft} has no front matter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise FilerError(f"generated draft {draft} has unclosed front matter")
    draft.write_text(text[:end] + f"\nstage: {FILE_STAGE}\n" + text[end:], encoding="utf-8")


def _sidecar_number(draft: Path) -> int | None:
    """The issue number the sidecar records, if any invocation created one."""
    sidecar = draft.with_suffix(".json")
    if not sidecar.is_file():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    number = payload.get("created_issue_number") if isinstance(payload, dict) else None
    return number if isinstance(number, int) and number >= 1 else None


def file_issue(
    mc: Path | None,
    runner: Runner,
    *,
    repo: str,
    card: Any,
    revision: str,
    title: str,
    body: str,
    risk: str,
) -> int:
    """File one defect through mission-control; return the created number.

    Mission-control is resolved here, on first filing — never before the
    answers are read — so an answers call that files nothing never needs it.
    After every create invocation the sidecar is re-read: a recorded number
    means the issue exists and is returned even when post-create steps failed.
    Anything else raises, and the caller records nothing.
    """
    script = mc if mc is not None else resolve_mission_control(None)
    bare = str(repo).split("/")[-1] if "/" in str(repo) else str(repo)
    with tempfile.TemporaryDirectory(prefix="review-state-file-") as tmp:
        workdir = Path(tmp)
        (workdir / "body.md").write_text(body, encoding="utf-8")
        prepared = runner(
            [
                sys.executable,
                str(script),
                "--format",
                "json",
                "issue",
                "prepare",
                "--repo",
                bare,
                "--type",
                "defect",
                "--team",
                FILE_TEAM,
                "--project",
                FILE_PROJECT,
                "--title",
                title,
                "--status",
                FILE_STATUS,
                "--risk",
                risk,
                "--source-file",
                "body.md",
            ],
            cwd=workdir,
        )
        if prepared.returncode != 0:
            raise FilerError(f"mission-control prepare refused: {_tail(prepared.stderr)}")
        try:
            draft_rel = json.loads(prepared.stdout).get("draft")
        except json.JSONDecodeError as exc:
            raise FilerError(f"mission-control prepare printed no JSON: {exc}") from exc
        if not draft_rel:
            raise FilerError("mission-control prepare named no draft")
        draft = workdir / str(draft_rel)
        if not draft.is_file():
            raise FilerError(f"mission-control prepare named a missing draft {draft_rel}")
        _add_stage(draft)
        created = runner(
            [
                sys.executable,
                str(script),
                "--format",
                "json",
                "issue",
                "create-prepared",
                str(draft),
                "--yes",
                "--skip-approval",
            ],
            cwd=workdir,
        )
        try:
            result = json.loads(created.stdout or "{}")
        except json.JSONDecodeError:
            result = {}
        if isinstance(result, dict) and result.get("created") is True:
            number = result.get("number")
            if isinstance(number, int) and number >= 1:
                return number
        salvaged = _sidecar_number(draft)
        if salvaged is not None:
            return salvaged
        raise FilerError(f"mission-control filed nothing: {_tail(created.stderr)}")


def _profile_value(raw: Any, where: str) -> str:
    if not isinstance(raw, dict):
        raise ReviewStateError(f"{where} does not hold a JSON object")
    value = raw.get(PROFILE_KEY, "leave")
    if value not in PROFILE_VALUES:
        raise ReviewStateError(
            f"{where} sets {PROFILE_KEY} to {value!r}, not one of {', '.join(PROFILE_VALUES)}"
        )
    return str(value)


def load_profile_default(path: Path) -> str:
    """The unattended default from an explicit file: missing file or key is ``leave``."""
    if not path.is_file():
        return "leave"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewStateError(f"{path} is not valid JSON: {exc}") from exc
    return _profile_value(raw, str(path))


def _show_blob(repo_root: Path, revision: str, runner: Runner) -> str | None:
    """The blob's text, or None when the revision or path is not in the repo."""
    completed = runner(
        ["git", "-C", str(repo_root), "show", f"{revision}:.saga-profile.json"]
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def profile_default_from_base(
    repo_root: Path, base_sha: str, head_sha: str, runner: Runner
) -> tuple[str, str | None]:
    """The unattended default from the base commit, as the review runner reads it.

    The working tree is the head of the change under review, so a head change
    to the key is ignored — and noted, so the operator sees it was. Returns
    ``(default, note)``; a missing base blob means ``leave`` with no note.
    """
    base_text = _show_blob(repo_root, base_sha, runner)
    if base_text is None:
        return "leave", None
    try:
        base_raw = json.loads(base_text)
    except json.JSONDecodeError as exc:
        raise ReviewStateError(
            f"{base_sha}:.saga-profile.json is not valid JSON: {exc}"
        ) from exc
    default = _profile_value(base_raw, f"{base_sha}:.saga-profile.json")
    head_text = _show_blob(repo_root, head_sha, runner)
    note: str | None = None
    if head_text is not None:
        try:
            head_raw = json.loads(head_text)
        except json.JSONDecodeError:
            head_raw = None
        head_value = head_raw.get(PROFILE_KEY, "leave") if isinstance(head_raw, dict) else "leave"
        base_value = base_raw.get(PROFILE_KEY, "leave") if isinstance(base_raw, dict) else "leave"
        if head_value != base_value:
            note = (
                f"head profile change to {PROFILE_KEY} ignored "
                f"(head {head_value!r}, base {base_value!r} wins)"
            )
    return default, note


# ---------------------------------------------------------------------------
# Applying answers
# ---------------------------------------------------------------------------


def _describe_outcome(finding_id: str, outcome: Mapping[str, Any]) -> str:
    text = f"{finding_id}: {outcome.get('outcome')}"
    if outcome.get("issue") is not None:
        text += f" #{outcome['issue']}"
    return text


def do_answers(
    record_file: Path | None,
    store_root: Path | None,
    issue: int | None,
    answers: Mapping[str, Any],
    timeout: bool,
    envelope: Mapping[str, Any],
    profile_default: str,
    mc: Path | None,
    runner: Runner,
) -> list[str]:
    """Validate everything, then record each answer in its own locked update.

    Validation runs over the whole file before anything writes. Each answer
    then applies under the lock with the filing inside it, so a filed issue is
    always recorded with its number and a failed filing records nothing — and
    a repeated file never files twice, because a recorded outcome skips filing.
    """
    if record_file is not None:
        record0 = as_dict(load_record_file(record_file))
    else:
        assert store_root is not None and issue is not None
        loaded = run_record.load(store_root, issue, warn=None)
        if loaded is None:
            raise ReviewStateError(f"no record for issue {issue}")
        record0 = as_dict(loaded)
    check_answers(answers, timeout, record0, envelope)
    unattended = envelope.get("run_mode") == "unattended" or timeout
    recorded: list[str] = []
    try:
        for key in sorted(answers):
            if key == MERGE_CHOICE:
                continue
            recorded.append(
                mutate_record(
                    record_file,
                    store_root,
                    issue,
                    lambda rec, k=key, c=answers[key]: _apply_fix_later(
                        rec, envelope, unattended, mc, runner, k, c
                    ),
                )
            )
        if MERGE_CHOICE in answers:
            recorded.append(
                mutate_record(
                    record_file,
                    store_root,
                    issue,
                    lambda rec: _apply_merge(rec, answers[MERGE_CHOICE]),
                )
            )
        recorded.extend(
            _apply_guard(record_file, store_root, issue, envelope, mc, runner, unattended)
        )
        bundle: str | None = _maybe_bundle(
            record_file, store_root, issue, answers, envelope, profile_default,
            unattended, mc, runner,
        )
        if bundle is not None:
            recorded.append(bundle)
    except ReviewStateError as exc:
        kept = "; ".join(recorded) if recorded else "none"
        raise ReviewStateError(
            f"{exc} (already recorded in this call and kept: {kept})"
        ) from exc
    return recorded


def _revision_of(record: run_record.RunRecord) -> str:
    runs = [e for e in record.review_cycles if isinstance(e, dict) and e.get("kind") == KIND_REVIEW_RUN]
    return str(runs[-1].get("head", "")) if runs else ""


def _apply_fix_later(
    record: run_record.RunRecord,
    envelope: Mapping[str, Any],
    unattended: bool,
    mc: Path | None,
    runner: Runner,
    key: str,
    choice: str,
) -> str:
    """One fix-later answer against the freshly locked record."""
    runs = review_runs(as_dict(record))
    document = build_document(as_dict(record), envelope)
    if key not in set(document["pending_choices"]):
        raise ReviewStateError(f"unknown choice key {key!r}")
    finding_id = key[len(FIX_LATER_PREFIX):]
    finding = _finding_by_id(runs[-1]).get(finding_id)
    if finding is None or finding.get("severity") != "fix-later":
        raise ReviewStateError(f"choice key {key!r} names no fix-later item")
    current = (finding.get("merge_outcome") or {}).get("outcome")
    if choice == "file-as-issue" and not unattended:
        if current == "filed":
            return _describe_outcome(finding_id, finding["merge_outcome"])
        title, body = defect_body(
            [finding], repo=str(record.repo), card=record.issue,
            revision=_revision_of(record),
        )
        number = file_issue(
            mc, runner, repo=str(record.repo), card=record.issue,
            revision=_revision_of(record), title=title, body=body,
            risk=RISK_BY_GROUP[consequence_group(finding)],
        )
        outcome: dict[str, Any] = {"outcome": "filed", "issue": number}
    elif choice == "file-as-issue":
        outcome = {"outcome": "left", "reason": "unattended"}
    elif choice == "fix-now":
        outcome = {"outcome": "fixed-now"}
    else:
        outcome = {"outcome": "left"}
    if current is not None and current != outcome["outcome"]:
        raise ReviewStateError(
            f"choice key {key!r} is already recorded {current}, not {outcome['outcome']}"
        )
    if current == outcome["outcome"]:
        return _describe_outcome(finding_id, finding["merge_outcome"])
    stamp_fix_later(_newest_run_entry(record), finding_id, outcome)
    return _describe_outcome(finding_id, outcome)


def _apply_merge(record: run_record.RunRecord, choice: Mapping[str, Any]) -> str:
    """The blocking-merge decision, appended beside the review runs."""
    runs = review_runs(as_dict(record))
    blocking = _blocking_of(runs[-1]) if runs else []
    recorded = _recorded_merge(as_dict(record))
    decision = choice.get("decision")
    reason = str(choice.get("reason") or "")
    if recorded is not None:
        if recorded.get("decision") == decision and (recorded.get("reason") or "") == reason:
            return f"merge decision already recorded: {decision}"
        raise ReviewStateError(
            f"choice key {MERGE_CHOICE!r} is already recorded "
            f"{recorded.get('decision')}, not {decision}"
        )
    entry: dict[str, Any] = {
        "loop": MERGE_ENTRY_LOOP,
        "decision": decision,
        "blocking": blocking,
        "answered_at": _utc_now(),
    }
    if decision == "merge-with-reason":
        entry["reason"] = reason
    record.review_cycles.append(entry)
    return f"merge decision recorded: {decision}"


def _apply_guard(
    record_file: Path | None,
    store_root: Path | None,
    issue: int | None,
    envelope: Mapping[str, Any],
    mc: Path | None,
    runner: Runner,
    unattended: bool,
) -> list[str]:
    """File every guard item without an outcome, attended or not.

    Fix-now is the only exemption. A recorded ``left`` is upgraded to
    ``filed`` with the new number: the record reflects that an issue exists.
    """
    del unattended  # the guard files under either mode; the flag documents it
    if record_file is not None:
        fresh = as_dict(load_record_file(record_file))
    else:
        assert store_root is not None and issue is not None
        loaded = run_record.load(store_root, issue, warn=None)
        fresh = as_dict(loaded) if loaded is not None else {}
    runs = review_runs(fresh)
    if not runs:
        return []
    candidates = [
        str(f.get("id"))
        for f in _finding_by_id(runs[-1]).values()
        if is_guard(f) and (f.get("merge_outcome") or {}).get("outcome") in (None, "left")
    ]
    filed: list[str] = []
    for finding_id in sorted(candidates):
        filed.append(
            mutate_record(
                record_file, store_root, issue,
                lambda rec, fid=finding_id: _file_guard_item(rec, mc, runner, fid),
            )
        )
    return [line for line in filed if line]


def _file_guard_item(
    record: run_record.RunRecord, mc: Path | None, runner: Runner, finding_id: str
) -> str:
    runs = review_runs(as_dict(record))
    finding = _finding_by_id(runs[-1]).get(finding_id) if runs else None
    if finding is None:
        return ""
    current = (finding.get("merge_outcome") or {}).get("outcome")
    if current in ("fixed-now", "filed"):
        return ""
    title, body = defect_body(
        [finding], repo=str(record.repo), card=record.issue, revision=_revision_of(record)
    )
    number = file_issue(
        mc, runner, repo=str(record.repo), card=record.issue,
        revision=_revision_of(record), title=title, body=body,
        risk=RISK_BY_GROUP[consequence_group(finding)],
    )
    outcome = {"outcome": "filed", "issue": number}
    stamp_fix_later(_newest_run_entry(record), finding_id, outcome)
    return f"security guard: {_describe_outcome(finding_id, outcome)}"


def _maybe_bundle(
    record_file: Path | None,
    store_root: Path | None,
    issue: int | None,
    answers: Mapping[str, Any],
    envelope: Mapping[str, Any],
    profile_default: str,
    unattended: bool,
    mc: Path | None,
    runner: Runner,
) -> str | None:
    """One follow-up issue for the leftovers, at an attended confirmation.

    The bundle fires when the ``file`` default is set and this call either
    carries the merge-blocking decision or answers nothing at all — the
    skill's explicit "nothing more to say". It covers every fix-later item
    still unanswered or ``left``, records each as ``filed`` with the bundle's
    number (which is what keeps a repeat call from filing again), and files
    nothing when no item qualifies. Unattended never bundles.
    """
    if unattended or profile_default != "file":
        return None
    if answers and MERGE_CHOICE not in answers:
        return None

    def change(record: run_record.RunRecord) -> str | None:
        runs = review_runs(as_dict(record))
        if not runs:
            return None
        qualifying = [
            f
            for f in _finding_by_id(runs[-1]).values()
            if f.get("severity") == "fix-later"
            and (f.get("merge_outcome") or {}).get("outcome") in (None, "left")
        ]
        if not qualifying:
            return None
        title, body = defect_body(
            qualifying, repo=str(record.repo), card=record.issue, revision=_revision_of(record)
        )
        tiers = [RISK_BY_GROUP[consequence_group(f)] for f in qualifying]
        risk = "high" if "high" in tiers else ("medium" if "medium" in tiers else "low")
        number = file_issue(
            mc, runner, repo=str(record.repo), card=record.issue,
            revision=_revision_of(record), title=title, body=body, risk=risk,
        )
        entry = _newest_run_entry(record)
        for finding in qualifying:
            stamp_fix_later(entry, str(finding["id"]), {"outcome": "filed", "issue": number})
        return f"follow-up bundle filed as #{number} for {len(qualifying)} items"

    return mutate_record(record_file, store_root, issue, change)


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


def is_final_round(runs: Sequence[Mapping[str, Any]], round_no: int) -> bool:
    """Round *round_no* ends the review: all clear, the limit, or an early stop."""
    ordered = sorted(runs, key=lambda r: int(r.get("round", 0)))
    position = next(
        (i for i, r in enumerate(ordered) if int(r.get("round", 0)) == round_no), None
    )
    if position is None:
        raise ReviewStateError(f"no recorded round {round_no}")
    run = ordered[position]
    merge = run.get("merge") if isinstance(run.get("merge"), Mapping) else {}
    if merge.get("allowed") is True:
        return True
    if round_no >= ROUND_LIMIT:
        return True
    if position == 0:
        return False
    blocking = set(_blocking_of(run))
    return bool(blocking) and blocking == set(_blocking_of(ordered[position - 1]))


def render_comment(
    run: Mapping[str, Any], runs: Sequence[Mapping[str, Any]], *, final: bool
) -> str:
    """One round's pull-request comment. Only the final one carries the marker."""
    lines: list[str] = []
    if final:
        lines.append(CHECKLIST_MARKER)
    lines.append(f"## Code review — round {run.get('round')}")
    lines.append("")
    lines.append(f"**Reviewed revision.** `{run.get('head')}`")
    lines.append("")
    lines.append("| Lens | Grade | Blocking | Fix later |")
    lines.append("|---|---|---|---|")
    grades = [g for g in run.get("lens_grades", []) if isinstance(g, Mapping)]
    order = {lens: position for position, lens in enumerate(formula.LENSES)}
    for grade in sorted(grades, key=lambda g: order.get(str(g.get("lens")), 99)):
        lines.append(
            f"| {grade.get('lens')} | {grade.get('grade')} | {grade.get('blocks')} "
            f"| {grade.get('fix_later')} |"
        )
    lines.append("")
    findings = [f for f in run.get("findings", []) if isinstance(f, Mapping)]
    fix_later = [f for f in findings if f.get("severity") == "fix-later"]
    if final:
        lines.append("### Fix-later checklist")
        lines.append("")
        for finding in fix_later:
            lines.append(f"- [ ] {finding.get('id')} {finding.get('statement')}")
        if not fix_later:
            lines.append("No fix-later items.")
        lines.append("")
    else:
        lines.append(f"Fix-later items so far: {len(fix_later)}.")
        lines.append("")
    lines.append(
        "This is a comment, not a review approval. A later commit carries no outcome from this one."
    )
    return "\n".join(lines)


def do_publish(
    record: Mapping[str, Any],
    round_no: int | None,
    pr: str,
    repo: str,
    runner: Runner,
) -> str:
    """Post one round's comment through ``gh pr comment``. Returns the URL."""
    runs = review_runs(record)
    if not runs:
        raise ReviewStateError("no review run is recorded yet, so nothing publishes")
    if round_no is None:
        round_no = int(runs[-1].get("round", 0))
    ordered = sorted(runs, key=lambda r: int(r.get("round", 0)))
    run = next((r for r in ordered if int(r.get("round", 0)) == round_no), None)
    if run is None:
        raise ReviewStateError(f"no recorded round {round_no}")
    body = render_comment(run, runs, final=is_final_round(runs, round_no))
    completed = runner(["gh", "pr", "comment", pr, "--repo", repo, "--body", body])
    if completed.returncode != 0:
        raise ReviewStateError(f"could not publish the review comment: {_tail(completed.stderr)}")
    return completed.stdout.strip()


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _record_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--record", default=None, help="An explicit record path (tests).")
    parser.add_argument("--issue", type=int, default=None, help="The issue number.")
    parser.add_argument("--store-root", default=None, help="Run-record store override.")
    parser.add_argument("--repo", default=None, help="owner/name, for --issue reads.")


def _resolve_record(args: argparse.Namespace) -> tuple[Path | None, Path | None, int | None]:
    if args.record:
        return Path(args.record), None, None
    if args.issue is None:
        raise ReviewStateError("name the record with --record <path> or --issue <N>")
    try:
        root = Path(args.store_root).resolve() if args.store_root else run_record.resolve_store_root()
    except run_record.RunRecordError as exc:
        raise ReviewStateError(str(exc)) from exc
    return None, root, args.issue


def _resolve_envelope(args: argparse.Namespace, runner: Runner) -> dict[str, Any]:
    if args.envelope:
        return load_envelope_file(Path(args.envelope))
    if args.issue is None or not args.repo:
        raise ReviewStateError("name the envelope with --envelope <path> or --issue <N> --repo <R>")
    completed = runner(
        ["gh", "issue", "view", str(args.issue), "--repo", args.repo, "--json", "body"]
    )
    if completed.returncode != 0:
        raise ReviewStateError(f"could not read issue {args.issue}: {_tail(completed.stderr)}")
    try:
        body = json.loads(completed.stdout).get("body", "")
    except json.JSONDecodeError as exc:
        raise ReviewStateError(f"issue {args.issue} returned no JSON: {exc}") from exc
    return extract_envelope_from_body(body, f"issue {args.repo}#{args.issue}")


def _read_record_for_view(
    record_file: Path | None, store_root: Path | None, issue: int | None
) -> dict[str, Any]:
    if record_file is not None:
        return as_dict(load_record_file(record_file))
    assert store_root is not None and issue is not None
    try:
        loaded = run_record.load(store_root, issue, warn=None)
    except run_record.RunRecordError as exc:
        raise ReviewStateError(str(exc)) from exc
    if loaded is None:
        raise ReviewStateError(f"no record for issue {issue}")
    return as_dict(loaded)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a review's state, record its answers, publish its comment."
    )
    sub = parser.add_subparsers(dest="verb", required=True)
    shared = argparse.ArgumentParser(add_help=False)
    _record_args(shared)
    rendered = sub.add_parser("render", help="Print the review-state document.", parents=[shared])
    rendered.add_argument("--envelope", default=None, help="A validated envelope JSON file.")
    rendered.add_argument("--render", choices=("json", "markdown"), default="json")
    answered = sub.add_parser("answers", help="Validate and record an answers file.", parents=[shared])
    answered.add_argument("--envelope", default=None, help="A validated envelope JSON file.")
    answered.add_argument("--answers", required=True, help="The answers file, or - for stdin.")
    answered.add_argument(
        "--profile",
        default=None,
        help="An explicit profile file (default: the key from the base commit).",
    )
    answered.add_argument(
        "--repo-root",
        default=None,
        help="The reviewed checkout (default: the working directory).",
    )
    answered.add_argument("--mission-control", default=None, help="sdlc_manager.py override.")
    published = sub.add_parser("publish", help="Post one round's comment.", parents=[shared])
    published.add_argument("--pr", required=True, help="The pull request number.")
    published.add_argument("--round", type=int, default=None, help="The round (default: newest).")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    stdout: Any = None,
) -> int:
    """Run the CLI. Runners are injectable; output goes to *stdout*."""
    args = build_parser().parse_args(argv)
    out = stdout if stdout is not None else sys.stdout
    run: Runner = runner if runner is not None else _completed
    try:
        record_file, store_root, issue = _resolve_record(args)
        if args.verb == "render":
            envelope = _resolve_envelope(args, run)
            raw = _read_record_for_view(record_file, store_root, issue)
            document = build_document(raw, envelope)
            if args.render == "json":
                print(json.dumps(document, indent=2, sort_keys=True), file=out)
            else:
                print(render_markdown(document), file=out, end="")
        elif args.verb == "answers":
            envelope = _resolve_envelope(args, run)
            if args.profile:
                profile_default = load_profile_default(Path(args.profile))
            else:
                runs = review_runs(_read_record_for_view(record_file, store_root, issue))
                if not runs:
                    profile_default, note = "leave", None
                else:
                    repo_root = (
                        Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
                    )
                    profile_default, note = profile_default_from_base(
                        repo_root, str(runs[-1].get("base", "")),
                        str(runs[-1].get("head", "")), run,
                    )
                if note is not None:
                    print(f"review_state: {note}", file=sys.stderr)
            # An explicit flag is validated now; otherwise resolution waits for
            # the first filing, so a call that files nothing never needs it.
            mc = resolve_mission_control(args.mission_control) if args.mission_control else None
            payload, timeout = load_answers_file(args.answers)
            for line in do_answers(
                record_file, store_root, issue, payload, timeout,
                envelope, profile_default, mc, run,
            ):
                print(line, file=out)
        elif args.verb == "publish":
            if not args.repo:
                raise ReviewStateError("publish needs --repo <owner/name>")
            raw = _read_record_for_view(record_file, store_root, issue)
            print(do_publish(raw, args.round, args.pr, args.repo, run), file=out)
        return EXIT_OK
    except run_record.UnknownRecordVersionError as exc:
        print(f"review_state: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN_VERSION
    except (ReviewStateError, run_record.RunRecordError) as exc:
        print(f"review_state: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
