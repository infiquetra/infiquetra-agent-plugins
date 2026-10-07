#!/usr/bin/env python3
"""Load approved question banks and the policy list (issue 157).

Saga publishes the policy's questions for builders to declare against and four
Jev question banks for the sweep to ask. Each lens's bank file carries that
lens's approval: the sitting date and a fingerprint of the approved content.
This module is the only way those files reach a caller. It refuses a lens
whose content differs from its approval or that carries none, with empty
standard output and exit 2. ``approve`` writes the approval after the sitting,
on the operator's word as noted on the issue.

Standard library only. The C6 constants below are literals, the way
``sweep_pieces.BANK_SCHEMA`` is; the drift test pins them to the sweep.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

BANK_SCHEMA = "question_bank.v1"
POLICY_SCHEMA = "policy_questions.v1"

LENSES: tuple[str, ...] = (
    "correctness",
    "security",
    "testing",
    "architecture-maintainability",
)
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
QUESTION_KEYS = frozenset(
    {"id", "lens", "kind", "options", "examples", "not_for", "when", "piece"}
)
PIECE_KINDS: tuple[str, ...] = ("function", "block", "file")
POLICY_KEYS = frozenset(
    {"id", "lens", "group", "question", "fails", "clears", "proving_test", "not_for"}
)

QUESTION_BANKS_DIR = "plugins/saga/references/question-banks"
POLICY_FILE = f"{QUESTION_BANKS_DIR}/policy-questions.json"
LOADER_FILE = "plugins/saga/scripts/question_banks.py"

#: The fingerprint tuple C2 appends. The script first, then the data.
QUESTION_BANK_COMPONENTS: tuple[str, ...] = (
    LOADER_FILE,
    POLICY_FILE,
    f"{QUESTION_BANKS_DIR}/architecture-maintainability.json",
    f"{QUESTION_BANKS_DIR}/correctness.json",
    f"{QUESTION_BANKS_DIR}/security.json",
    f"{QUESTION_BANKS_DIR}/testing.json",
)

#: Folded optional lens to the banks that ask its questions.
FOLDED_SOURCES: dict[str, tuple[str, ...]] = {
    "reliability": ("correctness",),
    "api-contract": ("correctness",),
    "performance": ("correctness",),
    "adversarial": ("security",),
    "privacy": ("security",),
    "deployment-infrastructure": ("security", "architecture-maintainability"),
    "documentation-clarity": ("architecture-maintainability",),
    "agent-usability": ("architecture-maintainability",),
}

#: The `when.languages` a folded question carries until a sitting narrows it.
FOLDED_FALLBACK_LANGUAGES: tuple[str, ...] = (
    "python",
    "typescript",
    "dart",
    "rust",
    "swift",
    "shell",
)

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_SAGA_PREFIX = "plugins/saga/"


class BankRefusal(Exception):
    """A set this loader will not hand out. The process exits 2."""


def bank_file(lens: str) -> str:
    """The repo-relative bank path for ``lens``."""
    return f"{QUESTION_BANKS_DIR}/{lens}.json"


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_day(value: object) -> bool:
    if not isinstance(value, str) or DAY.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def canonical(value: Any) -> bytes:
    """The pinned canonical form: sorted keys, compact, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def fingerprint_of(bank: Mapping[str, Any], policy_entries: list[Any]) -> str:
    """The approval fingerprint: the bank minus its approval plus its policy entries."""
    content = {key: bank[key] for key in bank if key != "approval"}
    return hashlib.sha256(canonical({"bank": content, "policy": policy_entries})).hexdigest()


def validate_policy(policy: Any) -> list[str]:
    """Shape problems in a policy list. An empty list is a valid file."""
    if not isinstance(policy, Mapping):
        return ["policy list is not an object"]
    if policy.get("schema") != POLICY_SCHEMA:
        return ["policy schema must be policy_questions.v1"]
    raw = policy.get("questions")
    if not isinstance(raw, list):
        return ["policy questions must be a list"]
    found: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        prefix = f"policy[{index}]"
        if not isinstance(entry, Mapping):
            found.append(f"{prefix} is not an object")
            continue
        extra = sorted(set(entry) - POLICY_KEYS)
        if extra:
            found.append(f"{prefix} has unexpected keys: {', '.join(extra)}")
        for field in sorted(POLICY_KEYS):
            if field not in entry:
                found.append(f"{prefix} is missing {field}")
        for field in ("id", "lens", "group", "question", "fails", "clears", "proving_test"):
            if field in entry and not _is_text(entry[field]):
                found.append(f"{prefix}.{field} must be a non-empty string")
        if _is_text(entry.get("id")):
            if entry["id"] in seen:
                found.append(f"{prefix}.id repeats {entry['id']!r}")
            seen.add(str(entry["id"]))
        if "lens" in entry and entry["lens"] not in LENSES:
            found.append(f"{prefix}.lens is not a review lens")
        notes = entry.get("not_for")
        if "not_for" in entry and (
            not isinstance(notes, list)
            or not notes
            or any(not _is_text(item) for item in notes)
        ):
            found.append(f"{prefix}.not_for must be a non-empty list of lines")
    return found


def _question_problems(question: Any, lens: str, index: int) -> list[str]:
    prefix = f"questions[{index}]"
    if not isinstance(question, Mapping):
        return [f"{prefix} is not an object"]
    found: list[str] = []
    extra = sorted(set(question) - QUESTION_KEYS)
    if extra:
        found.append(f"{prefix} has unexpected keys: {', '.join(extra)}")
    for field in ("id", "lens", "kind", "options", "piece"):
        if field not in question:
            found.append(f"{prefix} is missing {field}")
    _id_problems(question.get("id"), lens, prefix, found)
    if "lens" in question and question["lens"] != lens:
        found.append(f"{prefix}.lens is not this bank's lens")
    if "kind" in question and question["kind"] not in {"yes-no", "choice"}:
        found.append(f"{prefix}.kind must be yes-no or choice")
    if "piece" in question and question["piece"] not in PIECE_KINDS:
        found.append(f"{prefix}.piece is not a piece kind")
    options = question.get("options")
    if "options" in question:
        found.extend(_option_problems(options, question.get("kind"), prefix))
    when = question.get("when")
    if when is None:
        when = {}
    if not isinstance(when, Mapping):
        found.append(f"{prefix}.when must be an object")
    else:
        found.extend(_when_problems(when, prefix))
        if _is_folded_id(question.get("id"), lens) and not when:
            found.append(f"{prefix}.when is required on a folded question")
    for field in ("examples", "not_for"):
        if field in question and not isinstance(question[field], list):
            found.append(f"{prefix}.{field} must be a list")
    return found


def _id_problems(qid: Any, lens: str, prefix: str, found: list[str]) -> None:
    if not isinstance(qid, str) or not qid or IDENTIFIER.fullmatch(qid) is None:
        found.append(f"{prefix}.id must be a non-empty identifier")
        return
    head = f"{lens}."
    if not qid.startswith(head):
        found.append(f"{prefix}.id must start with {head!r}")
        return
    parts = qid[len(head) :].split(".")
    if len(parts) not in (1, 2) or any(SLUG.fullmatch(part) is None for part in parts):
        found.append(f"{prefix}.id must be <lens>.<slug> or <lens>.<source>.<slug>")
        return
    if len(parts) == 2 and (
        parts[0] not in FOLDED_SOURCES or lens not in FOLDED_SOURCES[parts[0]]
    ):
        found.append(f"{prefix}.id names no folded source for this lens")


def _is_folded_id(qid: Any, lens: str) -> bool:
    if not isinstance(qid, str) or not qid.startswith(f"{lens}."):
        return False
    return len(qid[len(lens) + 1 :].split(".")) == 2


def _option_problems(options: Any, kind: Any, prefix: str) -> list[str]:
    if not isinstance(options, list) or not options:
        return [f"{prefix}.options must be a non-empty list"]
    found: list[str] = []
    seen: set[str] = set()
    for option in options:
        if not isinstance(option, Mapping):
            found.append(f"{prefix} has an option that is not an object")
            continue
        if set(option) - {"id", "definition"}:
            found.append(f"{prefix} has an option with an unexpected key")
        if not _is_text(option.get("id")):
            found.append(f"{prefix} has an option with no id")
        elif option["id"] in seen:
            found.append(f"{prefix} repeats option {option['id']!r}")
        else:
            seen.add(str(option["id"]))
        if not isinstance(option.get("definition"), str):
            found.append(f"{prefix} has an option with no definition")
    if kind == "choice" and len(options) < 2:
        found.append(f"{prefix} needs at least two options")
    if kind == "yes-no" and (
        len(options) < 2 or options[0].get("id") != "yes" or options[1].get("id") != "no"
    ):
        found.append(f"{prefix} must order its options yes then no")
    return found


def _when_problems(when: Mapping[str, Any], prefix: str) -> list[str]:
    extra = sorted(set(when) - {"languages", "paths"})
    if extra:
        return [f"{prefix}.when has unexpected keys: {', '.join(extra)}"]
    found: list[str] = []
    languages = when.get("languages")
    if languages is not None and (
        not isinstance(languages, list) or not languages or any(item not in LANGUAGES for item in languages)
    ):
        found.append(f"{prefix}.when.languages must be a non-empty language list")
    paths = when.get("paths")
    if paths is not None and (
        not isinstance(paths, list)
        or not paths
        or any(not isinstance(item, str) or not item for item in paths)
    ):
        found.append(f"{prefix}.when.paths must be a non-empty list of patterns")
    return found


def _approval_problems(bank: Mapping[str, Any]) -> list[str]:
    approval = bank.get("approval")
    if approval is None:
        return []
    if not isinstance(approval, Mapping) or set(approval) != {"date", "fingerprint"}:
        return ["approval must carry date and fingerprint"]
    found: list[str] = []
    if not _valid_day(approval.get("date")):
        found.append("approval.date must be an ISO calendar day")
    fingerprint = approval.get("fingerprint")
    if not isinstance(fingerprint, str) or SHA256.fullmatch(fingerprint) is None:
        found.append("approval.fingerprint must be 64 hex characters")
    return found


def validate_bank(
    bank: Any, lens: str, policy: Mapping[str, Any] | None = None
) -> list[str]:
    """Shape problems in one lens's bank. An empty list is a valid file.

    ``policy`` is the parsed policy list, used to resolve the bank's policy
    links. Without it the link values are not checked.
    """
    if lens not in LENSES:
        return [f"unknown lens: {lens}"]
    if not isinstance(bank, Mapping):
        return ["bank is not an object"]
    if bank.get("schema") != BANK_SCHEMA:
        return ["bank schema must be question_bank.v1"]
    if bank.get("lens", lens) != lens:
        return ["bank lens is not this bank's lens"]
    raw = bank.get("questions")
    if not isinstance(raw, list):
        return ["bank questions must be a list"]
    found: list[str] = []
    seen: set[str] = set()
    for index, question in enumerate(raw):
        found.extend(_question_problems(question, lens, index))
        qid = question.get("id") if isinstance(question, Mapping) else None
        if isinstance(qid, str) and qid:
            if qid in seen:
                found.append(f"questions[{index}].id repeats {qid!r}")
            seen.add(qid)
    links = bank.get("policy", [])
    if not isinstance(links, list):
        found.append("policy links must be a list")
    else:
        for position, link in enumerate(links):
            prefix = f"policy[{position}]"
            if not isinstance(link, Mapping) or set(link) != {"bank", "policy"}:
                found.append(f"{prefix} must carry bank and policy")
                continue
            if link["bank"] not in seen:
                found.append(f"{prefix} links an unknown question {link['bank']!r}")
            value = link["policy"]
            if not isinstance(value, str) or not value:
                found.append(f"{prefix} must name a policy id")
            elif policy is not None and not any(
                isinstance(entry, Mapping)
                and entry.get("id") == value
                and entry.get("lens") == lens
                for entry in policy.get("questions", [])
            ):
                found.append(f"{prefix} names no {lens} policy question")
    found.extend(_approval_problems(bank))
    return found


def _resolve_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    cwd = Path.cwd()
    if (cwd / "plugins" / "saga").is_dir():
        return cwd
    checkout = Path(__file__).resolve().parents[3]
    if (checkout / "plugins" / "saga").is_dir():
        return checkout
    return cwd


def _locate(root: Path, relative: str) -> Path:
    """The file behind a repo-relative path, in a checkout or an installed copy."""
    direct = root / relative
    if direct.is_file():
        return direct
    if relative.startswith(_SAGA_PREFIX):
        packaged = root / relative[len(_SAGA_PREFIX) :]
        if packaged.is_file():
            return packaged
    return direct


def _read_json(path: Path, relative: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise BankRefusal(f"missing file: {relative}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise BankRefusal(f"not JSON: {relative}") from None


def _lens_entries(policy: Mapping[str, Any], lens: str) -> list[Any]:
    return [
        entry
        for entry in policy.get("questions", [])
        if isinstance(entry, Mapping) and entry.get("lens") == lens
    ]


def _verified(bank: Any, lens: str, policy: Any) -> None:
    """Raise :class:`BankRefusal` unless ``bank`` is valid and matches its approval."""
    found = validate_bank(bank, lens, policy if isinstance(policy, Mapping) else None)
    if found:
        raise BankRefusal(f"{lens}: {found[0]}")
    assert isinstance(bank, Mapping)
    approval = bank.get("approval")
    if not isinstance(approval, Mapping):
        raise BankRefusal(f"no approval for lens {lens!r}")
    assert isinstance(policy, Mapping)
    if approval.get("fingerprint") != fingerprint_of(bank, _lens_entries(policy, lens)):
        raise BankRefusal(f"content differs from approval for lens {lens!r}")


def load_bank(lens: str, root: Path | str | None = None) -> dict[str, Any]:
    """The sweep-ready bank for ``lens``. Refuses an unapproved or changed set."""
    if lens not in LENSES:
        raise BankRefusal(f"unknown lens: {lens}")
    base = _resolve_root(str(root) if root is not None else None)
    bank = _read_json(_locate(base, bank_file(lens)), bank_file(lens))
    policy = _read_json(_locate(base, POLICY_FILE), POLICY_FILE)
    found = validate_policy(policy)
    if found:
        raise BankRefusal(found[0])
    _verified(bank, lens, policy)
    assert isinstance(bank, Mapping)
    return {"schema": BANK_SCHEMA, "questions": bank["questions"]}


def load_policy(root: Path | str | None = None) -> dict[str, Any]:
    """The policy list. Refuses unless every lens's approval verifies."""
    base = _resolve_root(str(root) if root is not None else None)
    policy = _read_json(_locate(base, POLICY_FILE), POLICY_FILE)
    found = validate_policy(policy)
    if found:
        raise BankRefusal(found[0])
    assert isinstance(policy, Mapping)
    for lens in LENSES:
        relative = bank_file(lens)
        _verified(_read_json(_locate(base, relative), relative), lens, policy)
    return {"schema": POLICY_SCHEMA, "questions": policy["questions"]}


def approve(lens: str, root: Path | str | None = None, day: str | None = None) -> str:
    """Write the approval for ``lens`` after its sitting. Returns the fingerprint.

    Runs only on the operator's word as noted on the issue; the command cannot
    check that note, so the gate is process.
    """
    if lens not in LENSES:
        raise BankRefusal(f"unknown lens: {lens}")
    stamp = day or date.today().isoformat()
    if not _valid_day(stamp):
        raise BankRefusal(f"not an ISO calendar day: {stamp}")
    base = _resolve_root(str(root) if root is not None else None)
    relative = bank_file(lens)
    path = _locate(base, relative)
    bank = _read_json(path, relative)
    policy = _read_json(_locate(base, POLICY_FILE), POLICY_FILE)
    found = validate_policy(policy)
    if found:
        raise BankRefusal(found[0])
    assert isinstance(policy, Mapping)
    found = validate_bank(bank, lens, policy)
    if found:
        raise BankRefusal(f"{lens}: {found[0]}")
    assert isinstance(bank, Mapping)
    fingerprint = fingerprint_of(bank, _lens_entries(policy, lens))
    bank["approval"] = {"date": stamp, "fingerprint": fingerprint}
    path.write_text(
        json.dumps(bank, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return fingerprint


def _purpose(question: Mapping[str, Any], bank: Mapping[str, Any], lens: str) -> str:
    qid = str(question.get("id", ""))
    links = bank.get("policy", [])
    if isinstance(links, list):
        for link in links:
            if isinstance(link, Mapping) and link.get("bank") == qid:
                return f"operationalizes {link.get('policy')}"
    rest = qid[len(lens) + 1 :].split(".") if qid.startswith(f"{lens}.") else []
    if len(rest) == 2 and rest[0] in FOLDED_SOURCES:
        return f"folded from {rest[0]}"
    return "defect-driven sweep question"


def _condition(when: Any) -> str:
    if not isinstance(when, Mapping) or not when:
        return "every piece"
    parts = []
    if when.get("languages"):
        parts.append("languages: " + ", ".join(when["languages"]))
    if when.get("paths"):
        parts.append("paths: " + ", ".join(when["paths"]))
    return "; ".join(parts) if parts else "every piece"


def render_sitting(lens: str, root: Path | str | None = None) -> str:
    """The sitting material for ``lens`` as Markdown. Needs shape, not approval."""
    if lens not in LENSES:
        raise BankRefusal(f"unknown lens: {lens}")
    base = _resolve_root(str(root) if root is not None else None)
    bank = _read_json(_locate(base, bank_file(lens)), bank_file(lens))
    policy = _read_json(_locate(base, POLICY_FILE), POLICY_FILE)
    found = validate_policy(policy)
    if found:
        raise BankRefusal(found[0])
    assert isinstance(policy, Mapping)
    found = validate_bank(bank, lens, policy)
    if found:
        raise BankRefusal(f"{lens}: {found[0]}")
    assert isinstance(bank, Mapping)
    lines = [f"# Sitting material: {lens}", "", "## Policy questions", ""]
    for entry in _lens_entries(policy, lens):
        lines.append(f"### {entry['id']} — {entry['group']}")
        lines.append(str(entry["question"]))
        lines.append(f"Fails: {entry['fails']}")
        lines.append(f"Clears: {entry['clears']}")
        lines.append(f"Proving test: {entry['proving_test']}")
        lines.append("Not for: " + "; ".join(entry["not_for"]))
        lines.append("")
    lines.append("## Bank questions")
    lines.append("")
    for question in bank["questions"]:
        lines.append(f"### {question['id']}")
        lines.append(f"Purpose: {_purpose(question, bank, lens)}")
        lines.append(
            f"Kind: {question['kind']}; piece: {question['piece']}; "
            f"condition: {_condition(question.get('when'))}"
        )
        lines.append("Options:")
        for option in question["options"]:
            lines.append(f"- `{option['id']}`: {option['definition']}")
        if question.get("examples"):
            lines.append("Examples: " + "; ".join(str(item) for item in question["examples"]))
        if question.get("not_for"):
            lines.append("Not for: " + "; ".join(str(item) for item in question["not_for"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _day(value: str) -> str:
    if not _valid_day(value):
        raise argparse.ArgumentTypeError(f"not an ISO calendar day: {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """The ``load``, ``approve`` and ``sitting`` commands over an optional root."""
    parser = argparse.ArgumentParser(
        prog="question_banks.py",
        description=(
            "Hand approved question banks to the sweep and the policy list to builders. "
            "Refusals exit 2 with empty standard output."
        ),
    )
    root_parent = argparse.ArgumentParser(add_help=False)
    root_parent.add_argument(
        "--root",
        default=None,
        help="repository root (default: discovered from the working directory)",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="repository root (default: discovered from the working directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", parents=[root_parent], help="Print an approved set as JSON.")
    group = load.add_mutually_exclusive_group(required=True)
    group.add_argument("--lens", choices=LENSES, help="print the sweep-ready bank")
    group.add_argument(
        "--policy", action="store_true", help="print the policy list once every lens verifies"
    )
    approve = sub.add_parser(
        "approve", parents=[root_parent], help="Write the approval after the sitting."
    )
    approve.add_argument("--lens", choices=LENSES, required=True)
    approve.add_argument(
        "--date",
        type=_day,
        default=None,
        help="sitting date as YYYY-MM-DD (default: today)",
    )
    sitting = sub.add_parser(
        "sitting", parents=[root_parent], help="Render the sitting material as Markdown."
    )
    sitting.add_argument("--lens", choices=LENSES, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line. Refusals exit 2; unexpected errors exit 1."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "load":
            if args.policy:
                document = load_policy(args.root)
            else:
                document = load_bank(args.lens, args.root)
            print(json.dumps(document, indent=2, ensure_ascii=False))
            return 0
        if args.command == "approve":
            print(approve(args.lens, args.root, args.date))
            return 0
        sys.stdout.write(render_sitting(args.lens, args.root))
        return 0
    except BankRefusal as exc:
        print(f"question_banks: refused: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"question_banks: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
