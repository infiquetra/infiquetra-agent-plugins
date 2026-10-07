#!/usr/bin/env python3
"""The targeted reviewer's answer: the check, the Jev consequence pick and the records (issue 158).

Saga's targeted reviewer answers every item on the review's where-to-look list, reproduces what it
believes with a sandboxed test, and runs one capped open search. Its instructions are
``references/targeted-reviewer-prompt.md`` and its answer's shape is
``references/targeted-reviewer-answer.schema.json``. Agent-launcher starts the session
(``launcher.py review``); saga never does.

This module does three things with an answer, and the review command (card C10a) calls it:

* ``check`` refuses an answer by naming each problem: a skipped or twice-answered item, a finding
  missing a location, statement or closed-list label, a reproduction without its test, command and
  output, any severity, too many open-search findings, or a scratch copy changed outside the
  reproduction tests.
* ``records`` turns an accepted answer into review_records.v1 findings and answered where-to-look
  records. For each reproduced finding it asks Jev (TypeSafe's classifier, through fleet-core's
  ``consequence`` verb) for the consequence. The lower of the two picks applies, which C1's
  formula computes; when Jev cannot answer, the finding is marked ``unconfirmed`` and the
  reviewer's pick applies.
* ``paths`` prints where saga's prompt and schema are, with their fingerprints, so the caller can
  hand them to agent-launcher without guessing where saga is installed.

The formula, the identity and the record validator are C1's (``review_formula.py``,
``review_records.py``); nothing here re-implements them.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import review_formula as formula  # noqa: E402  (after the sys.path shim, by design)
import review_records as records  # noqa: E402

REFERENCES = _SCRIPTS_DIR.parent / "references"
PROMPT_FILE = REFERENCES / "targeted-reviewer-prompt.md"
SCHEMA_FILE = REFERENCES / "targeted-reviewer-answer.schema.json"
LAUNCH_SETTINGS_FILE = REFERENCES / "targeted-reviewer-launch.json"

ANSWER_SCHEMA = "targeted_reviewer_answer.v1"
#: The most findings the open search may report, unless the review packet states another cap.
OPEN_SEARCH_CAP = 5
OPEN_SEARCH = "open-search"
#: The Jev verb that picks a reproduced finding's consequence (fleet-core's registry).
JEV_VERB = "consequence"

#: The evidence a reviewer may give; ``tool-result`` is reserved for tools.
REVIEWER_EVIDENCE: tuple[str, ...] = tuple(e for e in formula.EVIDENCE if e != "tool-result")
#: The rows a reviewer may cite: ``judged`` (code picks the judged row) or a lens's dispute row.
REVIEWER_ROWS: tuple[str, ...] = (formula.JUDGED,) + tuple(
    f"{lens}.dispute" for lens in formula.LENSES
)

ITEM_KEYS = frozenset({"index", "file", "answer"})
FINDING_REQUIRED: tuple[str, ...] = (
    "key",
    "origin",
    "lens",
    "row",
    "location",
    "language",
    "statement",
    "consequence",
    "trigger",
    "evidence",
    "proof",
    "introduced",
)
FINDING_KEYS = frozenset(FINDING_REQUIRED) | {"disputes"}
PROOF_KEYS = frozenset({"test", "command", "output", "steps"})
#: Keys that only code may write. Anywhere in an answer, each one refuses it.
COMPUTED_ANYWHERE = frozenset(
    {"severity", "severity_basis", "flags", "enforced", "priority", "grade", "score"}
)
#: Keys the record fills from the launch and Jev, never the reviewer.
FILLED_BY_CODE = frozenset(
    {"id", "kind", "subject", "source", "rule", "degraded", "consequence_jev", "unconfirmed",
     "merge_outcome"}
)

#: A reproduction's test file must look like a test by its path.
_TEST_DIR = re.compile(r"(^|/)(tests?|spec|__tests__)/")
_TEST_NAME = re.compile(r"(^test_[^/]*$)|(_test\.[^/]+$)|(\.test\.[^/]+$)|(\.spec\.[^/]+$)")


class AnswerRefused(Exception):
    """An answer the check refused, with one ``<field path>: <why>`` line per problem."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


def test_file_of(test: str) -> str:
    """The file part of a test reference such as ``tests/test_x.py::test_y``."""
    return test.split("::", 1)[0].strip()


def looks_like_a_test(path: str) -> bool:
    """Whether *path* names a test file, by its directory or its file name."""
    normal = path.replace("\\", "/").lstrip("./")
    name = normal.rsplit("/", 1)[-1]
    return bool(_TEST_DIR.search(normal) or _TEST_NAME.search(name))


def _describe(item: Any) -> str:
    """``file:start-end`` for an item, from its C1 location; the file alone for whole-project."""
    location = item.get("location") if isinstance(item, Mapping) else None
    if not isinstance(location, Mapping):
        return "no location"
    where = str(location.get("file") or "no file")
    lines = location.get("lines")
    if isinstance(lines, Mapping) and "start" in lines and "end" in lines:
        return f"{where}:{lines['start']}-{lines['end']}"
    return where


def _computed_keys(value: Any, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, inner in value.items():
            here = f"{path}.{key}" if path else str(key)
            if key in COMPUTED_ANYWHERE:
                found.append(here)
            found.extend(_computed_keys(inner, here))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            found.extend(_computed_keys(inner, f"{path}.{index}"))
    return found


def _check_items(
    check: records._Check, answers: Any, items: Sequence[Any], keys: set[str]
) -> dict[int, str]:
    """Each item answered exactly once; returns index -> the finding key it names."""
    named: dict[int, str] = {}
    seen: set[int] = set()
    if not check.array(answers, "items") or not isinstance(answers, list):
        return named
    for position, entry in enumerate(answers):
        if not isinstance(entry, Mapping):
            check.add(f"items[{position}]", "must be an object")
            continue
        index = entry.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
            check.add(
                f"items[{position}].index",
                f"{index!r} is not an item on the where-to-look list (0 to {len(items) - 1})",
            )
            continue
        path = f"items.{index}"
        if index in seen:
            check.add(path, f"where-to-look item {index} is answered more than once")
            continue
        seen.add(index)
        for extra in sorted(set(entry) - ITEM_KEYS):
            if extra not in COMPUTED_ANYWHERE:
                check.add(f"{path}.{extra}", "is not a field of an item's answer")
        item_file = (items[index].get("location") or {}).get("file")
        if entry.get("file") != item_file:
            check.add(
                f"{path}.file",
                f"{entry.get('file')!r} is not item {index}'s location.file {item_file!r}",
            )
        answer = entry.get("answer")
        if not check.mapping(answer, f"{path}.answer") or not isinstance(answer, Mapping):
            continue
        if not check.choice(answer.get("kind"), ("finding", "cleared"), f"{path}.answer.kind"):
            continue
        if answer["kind"] == "cleared":
            check.text(answer.get("reason"), f"{path}.answer.reason")
        else:
            key = answer.get("finding")
            if not isinstance(key, str) or key not in keys:
                check.add(f"{path}.answer.finding", f"{key!r} names no finding in this answer")
            else:
                named[index] = key
    for index in range(len(items)):
        if index not in seen:
            check.add(
                f"items.{index}",
                f"where-to-look item {index} ({_describe(items[index])}) has no answer",
            )
    return named


def _check_proof(check: records._Check, finding: Mapping[str, Any], path: str) -> None:
    proof = finding.get("proof")
    if not check.mapping(proof, f"{path}.proof") or not isinstance(proof, Mapping):
        return
    for extra in sorted(set(proof) - PROOF_KEYS):
        check.add(f"{path}.proof.{extra}", "is not a field of a proof")
    evidence = finding.get("evidence")
    if evidence == "reproduced":
        for name in ("test", "command", "output"):
            value = proof.get(name)
            if not isinstance(value, str) or not value.strip():
                check.add(
                    f"{path}.proof.{name}",
                    "a reproduced finding gives its failing test, the command that ran it, "
                    "and its output",
                )
        test = proof.get("test")
        if isinstance(test, str) and test.strip() and not looks_like_a_test(test_file_of(test)):
            check.add(f"{path}.proof.test", f"{test_file_of(test)} is not a test file")
    elif evidence == "traced":
        steps = proof.get("steps")
        if not isinstance(steps, list) or not steps or not all(
            isinstance(step, str) and step.strip() for step in steps
        ):
            check.add(f"{path}.proof.steps", "a traced finding gives its file-and-line steps")


def _check_finding(
    check: records._Check, finding: Mapping[str, Any], path: str, items: Sequence[Any]
) -> None:
    check.required(finding, FINDING_REQUIRED, f"{path}.")
    for extra in sorted(set(finding) - FINDING_KEYS):
        if extra in COMPUTED_ANYWHERE:
            continue  # reported once by the computed-key sweep
        why = (
            "code fills it from the launch and Jev; the reviewer never writes it"
            if extra in FILLED_BY_CODE
            else "is not a field of a finding"
        )
        check.add(f"{path}.{extra}", why)
    origin = finding.get("origin")
    if "origin" in finding and origin != OPEN_SEARCH:
        item = origin.get("item") if isinstance(origin, Mapping) else None
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < len(items):
            check.add(f"{path}.origin", f"must be {OPEN_SEARCH!r} or an item on the list")
    lens = finding.get("lens")
    if "lens" in finding:
        check.choice(lens, formula.LENSES, f"{path}.lens")
    row = finding.get("row")
    if "row" in finding and check.choice(row, REVIEWER_ROWS, f"{path}.row"):
        if row != formula.JUDGED:
            if row != f"{lens}.dispute":
                check.add(f"{path}.row", f"{row!r} is another lens's dispute row")
            check.text(finding.get("disputes"), f"{path}.disputes")
        elif "disputes" in finding:
            check.add(f"{path}.disputes", "only a dispute row names what it disputes")
    if "location" in finding:
        records._check_location(
            check, finding["location"], f"{path}.location", subject="code",
            scopes=("lines", "whole-project"),
        )
    if "language" in finding:
        check.choice(finding["language"], formula.LANGUAGES, f"{path}.language")
    statement = finding.get("statement")
    if (
        "statement" in finding
        and check.text(statement, f"{path}.statement")
        and isinstance(statement, str)
        and "\n" in statement
    ):
        check.add(f"{path}.statement", "must be one sentence on one line")
    if "consequence" in finding:
        check.choice(finding["consequence"], formula.CONSEQUENCES, f"{path}.consequence")
    if "trigger" in finding:
        check.choice(finding["trigger"], formula.TRIGGERS, f"{path}.trigger")
    if "evidence" in finding:
        if finding["evidence"] == "tool-result":
            check.add(f"{path}.evidence", "'tool-result' is reserved for tools")
        elif (
            check.choice(finding["evidence"], REVIEWER_EVIDENCE, f"{path}.evidence")
            and finding["evidence"] == "suspected"
            and origin == OPEN_SEARCH
        ):
            check.add(
                f"{path}.evidence",
                "'suspected' is only for a where-to-look item you could neither clear nor "
                "trace; an open-search finding is traced or reproduced",
            )
    if "proof" in finding:
        _check_proof(check, finding, path)
    if "introduced" in finding:
        check.boolean(finding["introduced"], f"{path}.introduced")


def reproduction_tests(answer: Mapping[str, Any]) -> set[str]:
    """The test files the answer's reproduced findings name."""
    tests: set[str] = set()
    for finding in answer.get("findings") or ():
        if isinstance(finding, Mapping) and finding.get("evidence") == "reproduced":
            test = (finding.get("proof") or {}).get("test") if isinstance(
                finding.get("proof"), Mapping) else None
            if isinstance(test, str) and test.strip():
                tests.add(test_file_of(test).lstrip("./"))
    return tests


def _check_scratch(check: records._Check, answer: Mapping[str, Any], result: Any) -> None:
    """The scratch copy differs from the head only by the reproduction tests."""
    scratch = result.get("scratch") if isinstance(result, Mapping) else None
    changes = scratch.get("changes") if isinstance(scratch, Mapping) else None
    if not isinstance(changes, Mapping):
        check.add("scratch.changes", "the launch result does not list the scratch copy's changes")
        return
    allowed = reproduction_tests(answer)
    for path in changes.get("links") or ():
        check.add("scratch.changes", f"{path} (symlink) is a link the session made, never a test")
    for kind in ("added", "modified", "deleted"):
        for path in changes.get(kind) or ():
            normal = str(path).lstrip("./")
            if kind == "deleted" or normal not in allowed or not looks_like_a_test(normal):
                check.add("scratch.changes", f"{path} ({kind}) is not a reproduction test")


def check(
    answer: Any,
    items: Sequence[Any],
    *,
    open_search_cap: int = OPEN_SEARCH_CAP,
    result: Any = None,
) -> list[str]:
    """Every problem with *answer* against *items*; empty when the answer is accepted."""
    problems = records._Check()
    if not isinstance(answer, Mapping):
        problems.add("answer", "must be a JSON object")
        return problems.problems
    if not isinstance(items, list):
        problems.add("where-to-look", "must be a JSON array of where-to-look records")
        return problems.problems
    for path in _computed_keys(answer, ""):
        problems.add(path, "code computes it; the reviewer never writes one")
    if answer.get("schema") != ANSWER_SCHEMA:
        problems.add("schema", f"must be {ANSWER_SCHEMA!r}")
    for extra in sorted(set(answer) - {"schema", "items", "findings"}):
        if extra not in COMPUTED_ANYWHERE:
            problems.add(extra, "is not a field of an answer")

    findings = answer.get("findings")
    keys: dict[str, Mapping[str, Any]] = {}
    paths: list[tuple[str, Mapping[str, Any]]] = []
    if problems.array(findings, "findings") and isinstance(findings, list):
        for position, finding in enumerate(findings):
            if not isinstance(finding, Mapping):
                problems.add(f"findings.{position}", "must be an object")
                continue
            key = finding.get("key")
            path = f"findings.{key}" if isinstance(key, str) and key.strip() else (
                f"findings.{position}")
            if isinstance(key, str) and key in keys:
                problems.add(f"{path}.key", "is used by more than one finding")
            elif isinstance(key, str) and key.strip():
                keys[key] = finding
            paths.append((path, finding))

    named = _check_items(problems, answer.get("items"), items, set(keys))
    for path, finding in paths:
        _check_finding(problems, finding, path, items)
        origin = finding.get("origin")
        if isinstance(origin, Mapping) and isinstance(origin.get("item"), int):
            index = origin["item"]
            if named.get(index) != finding.get("key") and 0 <= index < len(items):
                problems.add(
                    f"{path}.origin",
                    f"item {index} does not answer with this finding",
                )
    open_search = sum(1 for _, finding in paths if finding.get("origin") == OPEN_SEARCH)
    if open_search > open_search_cap:
        problems.add(
            OPEN_SEARCH, f"{open_search} findings, the cap is {open_search_cap}"
        )
    if result is not None:
        _check_scratch(problems, answer, result)
    return problems.problems


# ---------------------------------------------------------------------------
# Records and the Jev pick
# ---------------------------------------------------------------------------

Asker = Callable[[Any, Mapping[str, Any]], Any]


def _fleet(name: str) -> Any:
    import bundled_fleet  # noqa: PLC0415  (loaded only when Jev is asked)

    return bundled_fleet.load(name)


def jev_pick(finding: Mapping[str, Any], ask: Asker | None = None) -> tuple[str | None, str]:
    """Jev's consequence for a reproduced finding, or ``None`` with the reason it has none.

    Jev cannot answer when the request fails (no key, timeout, malformed, error), when it gives no
    consequence from the closed list, or when its confidence is below the verb's floor.
    """
    client = _fleet("typesafe_client")
    verb = _fleet("jev_verbs").VERBS[JEV_VERB]
    proof = finding.get("proof") or {}
    state = {
        "finding": finding.get("statement"),
        "trigger": finding.get("trigger"),
        "test": proof.get("test"),
        "output": str(proof.get("output") or "")[:4000],
    }
    caller = ask if ask is not None else client.ask
    result = caller(state, verb.question_set())
    status = getattr(result, "status", client.STATUS_ERROR)
    if status != client.STATUS_OK:
        return None, getattr(result, "note", "") or f"the request failed with status {status}"
    answer = (getattr(result, "answers", {}) or {}).get(JEV_VERB)
    if not isinstance(answer, Mapping):
        return None, "Jev gave no consequence"
    value = client.answer_value(answer)
    confidence = client.answer_confidence(answer)
    if value not in formula.CONSEQUENCES:
        return None, f"Jev's answer {value!r} is not on the closed list"
    if confidence is None or confidence < verb.confidence_floor:
        return None, f"Jev's confidence {confidence} is below the floor {verb.confidence_floor}"
    return str(value), ""


def _reviewer_source(result: Mapping[str, Any]) -> dict[str, str]:
    vendor = str(result.get("vendor") or "unknown")
    model = result.get("model") if isinstance(result.get("model"), Mapping) else {}
    resolved = model.get("resolved") if isinstance(model, Mapping) else None
    name = (resolved[0] if isinstance(resolved, list) and resolved else None) or (
        model.get("requested") if isinstance(model, Mapping) else None)
    return {"kind": "llm", "name": f"targeted-reviewer:{vendor}", "model": str(name or "unknown")}


def _rule_ref(finding: Mapping[str, Any], items: Sequence[Any]) -> str:
    """The question behind a finding: its item's likeliest question, or the open search."""
    if finding.get("row") != formula.JUDGED:
        return str(finding.get("disputes"))
    origin = finding.get("origin")
    if isinstance(origin, Mapping):
        questions = items[origin["item"]].get("questions") or []
        best = max(
            (q for q in questions if isinstance(q, Mapping)),
            key=lambda q: q.get("probability", 0),
            default=None,
        )
        if best is not None and best.get("id"):
            return str(best["id"])
    return OPEN_SEARCH


def to_records(
    answer: Mapping[str, Any],
    items: Sequence[Any],
    result: Mapping[str, Any],
    *,
    ask: Asker | None = None,
    use_jev: bool = True,
    open_search_cap: int = OPEN_SEARCH_CAP,
) -> dict[str, Any]:
    """An accepted answer as review_records.v1 findings and answered where-to-look records."""
    problems = check(answer, items, open_search_cap=open_search_cap, result=result)
    if problems:
        raise AnswerRefused(problems)
    source = _reviewer_source(result)
    built: list[dict[str, Any]] = []
    identities: dict[str, str] = {}
    picks: list[dict[str, Any]] = []
    for finding in answer["findings"]:
        rule = {"row": finding["row"], "ref": _rule_ref(finding, items)}
        record: dict[str, Any] = {
            "kind": "finding",
            "schema": records.SCHEMA,
            "subject": "code",
            "lens": finding["lens"],
            "rule": rule,
            "source": dict(source),
            "location": copy.deepcopy(finding["location"]),
            "language": finding["language"],
            "statement": finding["statement"],
            "consequence": finding["consequence"],
            "trigger": finding["trigger"],
            "evidence": finding["evidence"],
            "proof": copy.deepcopy(finding["proof"]),
            "introduced": finding["introduced"],
            "degraded": False,
            "consequence_jev": None,
            "unconfirmed": False,
            "merge_outcome": None,
        }
        record["id"] = records.finding_identity(record["lens"], rule, record["location"])
        identities[finding["key"]] = record["id"]
        if finding["evidence"] == "reproduced":
            jev, note = jev_pick(finding, ask) if use_jev else (None, "Jev was not asked")
            record["consequence_jev"] = jev
            record["unconfirmed"] = jev is None
            applied = (
                finding["consequence"] if jev is None
                else formula.lower_consequence(finding["consequence"], jev)
            )
            flag = (
                "unconfirmed" if jev is None
                else "agreement" if jev == finding["consequence"]
                else "consequence-disagreement"
            )
            picks.append({
                "finding_id": record["id"],
                "llm": finding["consequence"],
                "jev": jev,
                "applied": applied,
                "flag": flag,
                "note": note,
            })
        built.append(record)

    answered: list[dict[str, Any]] = []
    by_index = {entry["index"]: entry["answer"] for entry in answer["items"]}
    for index, item in enumerate(items):
        record = copy.deepcopy(dict(item))
        given = by_index[index]
        record["answer"] = (
            {"kind": "finding", "finding_id": identities[given["finding"]]}
            if given["kind"] == "finding"
            else {"kind": "cleared", "reason": given["reason"]}
        )
        answered.append(record)

    invalid = [
        f"findings.{n}.{line}" for n, r in enumerate(built) for line in records.validate(r)
    ] + [
        f"where_to_look.{n}.{line}" for n, r in enumerate(answered) for line in records.validate(r)
    ]
    if invalid:
        raise AnswerRefused(invalid)
    return {"findings": built, "where_to_look": answered, "consequence_picks": picks}


# ---------------------------------------------------------------------------
# Paths and the command line
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths() -> dict[str, str]:
    """Where saga's reviewer prompt and answer schema are, with their SHA-256 fingerprints."""
    return {
        "prompt": str(PROMPT_FILE),
        "schema": str(SCHEMA_FILE),
        "prompt_sha256": _sha256(PROMPT_FILE),
        "schema_sha256": _sha256(SCHEMA_FILE),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewer_answer.py",
        description=(
            "Check the targeted reviewer's answer and turn it into saga's review records. Exit 0 "
            "accepted; 1 refused, one '<field>: <why>' line per problem on standard error; 2 an "
            "unreadable file."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths", help="Print saga's reviewer prompt and schema paths and SHA-256s.")
    for name, text in (
        ("check", "Refuse an answer that skips an item or breaks the answer contract."),
        ("records", (
            "Check an answer, ask Jev for each reproduced finding's consequence, and print the "
            "review records."
        )),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument("--answer", type=Path, required=True, help="The answer JSON.")
        command.add_argument(
            "--items", type=Path, required=True,
            help="The where-to-look list: a JSON array of review_records.v1 where_to_look records.",
        )
        command.add_argument(
            "--result", type=Path, required=(name == "records"),
            help="agent-launcher's launch result (vendor, model, scratch-copy changes).",
        )
        command.add_argument(
            "--open-search-cap", type=int, default=OPEN_SEARCH_CAP,
            help=f"The most open-search findings allowed (default {OPEN_SEARCH_CAP}).",
        )
        if name == "records":
            command.add_argument(
                "--no-jev", action="store_true",
                help="Do not ask Jev; every reproduced finding is marked unconfirmed.",
            )
    return parser


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "paths":
        print(json.dumps(paths(), indent=2))
        return 0
    try:
        answer = _read(args.answer)
        items = _read(args.items)
        result = _read(args.result) if args.result else None
    except (OSError, ValueError) as exc:
        print(f"reviewer_answer: cannot read an input: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "check":
            problems = check(answer, items, open_search_cap=args.open_search_cap, result=result)
            if problems:
                raise AnswerRefused(problems)
            return 0
        output = to_records(
            answer, items, result or {}, use_jev=not args.no_jev,
            open_search_cap=args.open_search_cap,
        )
    except AnswerRefused as exc:
        for line in exc.problems:
            print(line, file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
