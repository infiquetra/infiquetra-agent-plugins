#!/usr/bin/env python3
"""Say whether a lens may block in a language, from the stored calibration file (issue 149).

The file records the pass marks and, once a corpus run exists, the verdicts. This module
does not compare the numbers with the marks. A missing run, a stale fingerprint, a drift
line, a missing language, or a profile pin off the default answers report-only.

PyYAML loads only when a profile pin has to be compared with the root's tool list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import review_formula

SCHEMA_NAME = "review_calibration.v1"
CALIBRATION_RELATIVE = "plugins/saga/references/review-calibration.json"
TOOL_LIST_RELATIVE = "plugins/saga/references/review-tools.yaml"

# Repo-relative paths, written as literals. C4a's test reads this file as text, and C6's
# test reads the sequence this module defines. A later card appends its own paths.
_SAGA_PREFIX = "plugins/saga/"
COMPONENTS: tuple[str, ...] = (
    "plugins/saga/scripts/review_formula.py",
    "plugins/saga/references/review-records.schema.json",
    "plugins/saga/scripts/review_tools.py",
    "plugins/saga/scripts/review_diff.py",
    "plugins/saga/scripts/coverage_lines.py",
    "plugins/saga/scripts/review_adapters_all_languages.py",
    "plugins/saga/references/review-tools.yaml",
    "plugins/saga/scripts/review_adapters_python.py",
    "plugins/saga/scripts/review_adapters_infrastructure.py",
    "plugins/saga/scripts/review_adapters_shell.py",
    "plugins/saga/scripts/review_adapters_workflows.py",
    "plugins/saga/scripts/review_adapters_markdown.py",
    "plugins/saga/scripts/review_adapters_typescript.py",
    "plugins/saga/scripts/review_adapters_dart.py",
    "plugins/saga/scripts/review_adapters_rust.py",
    "plugins/saga/scripts/review_adapters_swift.py",
    "plugins/saga/references/targeted-reviewer-prompt.md",
    "plugins/saga/references/targeted-reviewer-answer.schema.json",
    "plugins/saga/references/targeted-reviewer-launch.json",
    "plugins/fleet-core/scripts/fleet_commons/jev_sweep.py",
    "plugins/saga/scripts/sweep_pieces.py",
    "plugins/saga/references/model-prices.yaml",
    "plugins/saga/references/semgrep/release-shares-cleanup-block.yaml",
    "plugins/saga/references/semgrep/swallowed-error.yaml",
    "plugins/saga/references/semgrep/silent-skip.yaml",
    "plugins/saga/references/semgrep/write-skips-shared-update-path.yaml",
    "plugins/saga/references/semgrep/naive-time-comparison.yaml",
    "plugins/saga/references/semgrep/money-as-floating-point.yaml",
    "plugins/saga/scripts/review_command.py",
    "plugins/saga/scripts/review_checks.py",
)

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

TOP_LEVEL = (
    "schema",
    "corpus_run",
    "fingerprint",
    "corpus_version",
    "jev_model_version",
    "cost_usd",
    "langfuse_run_id",
    "reviewer_configuration",
    "marks",
    "lenses",
    "thresholds",
)
NULLABLE_IDENTIFIERS = ("corpus_version", "jev_model_version", "langfuse_run_id")
COUNT_FIELDS = (
    "held_out_blocked",
    "held_out_defects",
    "held_out_false_blocks",
    "held_out_clean",
    "repeat_flips",
    "repeat_cases",
)
LANGUAGE_FIELDS = ("verdict", *COUNT_FIELDS)
THRESHOLD_FIELDS = ("question", "threshold", "piece_size")


def _fraction(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def _lens_mark(
    must_block: tuple[int, int], may_block_clean: tuple[int, int]
) -> dict[str, dict[str, int]]:
    return {
        "must_block": _fraction(*must_block),
        "may_block_clean": _fraction(*may_block_clean),
    }


#: The design's pass marks. The harness reads this object. may-block does not.
MARKS: dict[str, Any] = {
    "lenses": {
        "correctness": _lens_mark((8, 10), (1, 10)),
        "security": _lens_mark((9, 10), (1, 10)),
        "testing": _lens_mark((9, 10), (1, 10)),
        "architecture-maintainability": _lens_mark((6, 10), (1, 20)),
    },
    "language_guard": {
        "must_catch": _fraction(7, 10),
        "may_block_clean": _fraction(2, 10),
    },
    "repeat_run": {"may_flip": _fraction(1, 10)},
    "deterministic": "identical",
}


class CalibrationError(Exception):
    """A file or a profile this command will not answer. The process exits 2."""


def _unknown(path: str) -> str:
    return f"unknown key: {path}"


def _ident(path: str) -> str:
    return f"not an identifier: {path}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _extra_keys(value: Mapping[str, Any], allowed: Sequence[str], prefix: str) -> list[str]:
    return [_unknown(f"{prefix}.{key}" if prefix else key) for key in value if key not in allowed]


def _count_problems(value: object, prefix: str) -> list[str]:
    if not isinstance(value, dict):
        return [_ident(prefix)]
    found = _extra_keys(value, COUNT_FIELDS, prefix)
    for name in COUNT_FIELDS:
        if name not in value or not _is_int(value[name]) or value[name] < 0:
            found.append(_ident(f"{prefix}.{name}"))
    return found


def _language_problems(value: object, prefix: str) -> list[str]:
    if not isinstance(value, dict):
        return [_ident(prefix)]
    found = _extra_keys(value, LANGUAGE_FIELDS, prefix)
    verdict = value.get("verdict")
    if verdict not in {"cleared", "report-only"}:
        found.append(_ident(f"{prefix}.verdict"))
    for name in COUNT_FIELDS:
        dotted = f"{prefix}.{name}"
        if name not in value or not _is_int(value[name]) or value[name] < 0:
            found.append(_ident(dotted))
    return found


def _fingerprint_problems(data: Mapping[str, Any]) -> list[str]:
    fingerprint = data.get("fingerprint")
    if not isinstance(fingerprint, dict):
        return [_unknown("fingerprint")]
    found: list[str] = []
    for key, value in fingerprint.items():
        if key not in COMPONENTS:
            found.append(_unknown(f"fingerprint.{key}"))
        elif not isinstance(value, str) or SHA256.fullmatch(value) is None:
            found.append(_ident(f"fingerprint.{key}"))
    if data.get("corpus_run") == "no-run" and fingerprint:
        found.append(_unknown("fingerprint"))
    return found


def _lens_problems(data: Mapping[str, Any]) -> list[str]:
    lenses = data.get("lenses")
    if not isinstance(lenses, dict):
        return [_unknown("lenses")]
    found: list[str] = []
    recorded = data.get("corpus_run") == "recorded"
    for key in lenses:
        if key not in review_formula.LENSES:
            found.append(_unknown(f"lenses.{key}"))
    for lens in review_formula.LENSES:
        prefix = f"lenses.{lens}"
        row = lenses.get(lens)
        if not isinstance(row, dict):
            found.append(_ident(prefix))
            continue
        allowed = ("drift", "overall", "languages") if recorded else ("drift", "languages")
        found.extend(_extra_keys(row, allowed, prefix))
        if recorded:
            if row.get("drift") not in {"report-only", "as-recorded"}:
                found.append(_ident(f"{prefix}.drift"))
            if "overall" not in row:
                found.append(_ident(f"{prefix}.overall"))
            else:
                found.extend(_count_problems(row.get("overall"), f"{prefix}.overall"))
        elif row.get("drift") != "report-only":
            found.append(_ident(f"{prefix}.drift"))
        languages = row.get("languages")
        if not isinstance(languages, dict):
            found.append(_ident(f"{prefix}.languages"))
            continue
        if not recorded and languages:
            found.append(_unknown(f"{prefix}.languages"))
            continue
        for language, spec in languages.items():
            if language not in review_formula.LANGUAGES:
                found.append(_unknown(f"{prefix}.languages.{language}"))
                continue
            found.extend(_language_problems(spec, f"{prefix}.languages.{language}"))
    return found


def _threshold_problems(value: object) -> list[str]:
    if not isinstance(value, list):
        return [_unknown("thresholds")]
    found: list[str] = []
    for index, row in enumerate(value):
        prefix = f"thresholds[{index}]"
        if not isinstance(row, dict):
            found.append(_unknown(prefix))
            continue
        found.extend(_extra_keys(row, THRESHOLD_FIELDS, prefix))
        question = row.get("question")
        if not isinstance(question, str) or IDENTIFIER.fullmatch(question) is None:
            found.append(_ident(f"{prefix}.question"))
        if not _is_number(row.get("threshold")):
            found.append(_ident(f"{prefix}.threshold"))
        piece = row.get("piece_size")
        if not _is_int(piece) or piece < 1:
            found.append(_ident(f"{prefix}.piece_size"))
    return found


def document_problems(data: object) -> list[str]:
    """Format problems for one calibration document. An empty list is a valid file."""
    if not isinstance(data, dict):
        return [_unknown("review-calibration.json")]
    found = [_unknown(key) for key in data if key not in TOP_LEVEL]
    if data.get("schema") != SCHEMA_NAME:
        found.append(_ident("schema"))
    if data.get("corpus_run") not in {"no-run", "recorded"}:
        found.append(_ident("corpus_run"))
    found.extend(_fingerprint_problems(data))
    for name in NULLABLE_IDENTIFIERS:
        value = data.get(name)
        if value is not None and (not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None):
            found.append(_ident(name))
    cost = data.get("cost_usd")
    if cost is not None and (not _is_number(cost) or cost < 0):
        found.append(_ident("cost_usd"))
    configuration = data.get("reviewer_configuration")
    if configuration is not None and (
        not isinstance(configuration, str) or SHA256.fullmatch(configuration) is None
    ):
        found.append(_ident("reviewer_configuration"))
    if data.get("marks") != MARKS:
        found.append(_ident("marks"))
    found.extend(_lens_problems(data))
    found.extend(_threshold_problems(data.get("thresholds")))
    return found


def problems_in(path: Path) -> list[str]:
    """Format problems in the JSON file at ``path``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"missing calibration file: {CALIBRATION_RELATIVE} ({exc})"]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ["not an identifier: review-calibration.json"]
    return document_problems(data)


def package_dir() -> Path:
    """The saga directory that contains this script.

    A checkout keeps that directory at ``plugins/saga``. A marketplace install
    copies ``plugins/saga`` itself to the plugin root, so ``parents[3]`` is
    outside the plugin and is not a repository root.
    """
    return Path(__file__).resolve().parents[1]


def default_calibration_path() -> Path:
    """The calibration file shipped beside this script.

    ``--root`` does not select it. A review passes the installed saga's file,
    not the reviewed head's copy.
    """
    return package_dir() / "references" / "review-calibration.json"


def locate(root: Path, relative: str) -> Path:
    """The file whose bytes are hashed for a repo-relative component path.

    A repository root stores the path as written. A saga package stores
    ``plugins/saga/<rest>`` at ``<rest>``. When ``root`` is this script's own
    package, a path outside that package is read from the checkout that
    contains the script, which is where fleet-core's sweep file lives.
    """
    root = Path(root)
    direct = root / relative
    if direct.is_file():
        return direct
    if relative.startswith(_SAGA_PREFIX):
        packaged = root / relative[len(_SAGA_PREFIX):]
        if packaged.is_file():
            return packaged
    if root.resolve() == package_dir().resolve():
        checkout = Path(__file__).resolve().parents[3] / relative
        if checkout.is_file():
            return checkout
    return direct


def thresholds(path: Path | None = None) -> list[dict[str, Any]]:
    """The sweep's threshold rows, as stored. The committed file's list is empty."""
    target = path
    if target is None:
        target = default_calibration_path()
    found = problems_in(target)
    if found:
        raise CalibrationError(found[0])
    data = json.loads(target.read_text(encoding="utf-8"))
    return [
        {
            "question": row["question"],
            "threshold": row["threshold"],
            "piece_size": row["piece_size"],
        }
        for row in data["thresholds"]
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint_drift(root: Path, recorded: Mapping[str, Any]) -> list[str]:
    """Byte differences against a recorded fingerprint. Empty when every component matches."""
    found: list[str] = []
    for relative in COMPONENTS:
        if relative not in recorded:
            found.append(f"changed component: {relative}")
            continue
        file = locate(root, relative)
        if not file.is_file():
            found.append(f"missing component: {relative}")
            continue
        if recorded[relative] != _sha256(file):
            found.append(f"changed component: {relative}")
    for key in recorded:
        if key not in COMPONENTS:
            found.append(_unknown(f"fingerprint.{key}"))
    return found


def check(root: Path) -> list[str]:
    """Format errors, and fingerprint errors once a corpus run is recorded.

    A tree with no ``plugins/saga`` directory has nothing to check. While
    ``corpus_run`` is ``no-run``, component bytes are not compared.
    """
    root = Path(root)
    if not (root / "plugins" / "saga").is_dir():
        return []
    path = root / CALIBRATION_RELATIVE
    if not path.is_file():
        return [f"missing calibration file: {CALIBRATION_RELATIVE}"]
    found = problems_in(path)
    if found:
        return found
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["corpus_run"] != "recorded":
        return []
    return fingerprint_drift(root, data["fingerprint"])


def _refuse_environment(data: Mapping[str, Any]) -> None:
    environment = data.get("functional_test_environment")
    if environment is None:
        return
    if not isinstance(environment, dict):
        raise CalibrationError("functional_test_environment must be an object")
    command = environment.get("test_command")
    if command is not None and not isinstance(command, str):
        raise CalibrationError("functional_test_environment.test_command must be a string")


def _refuse_languages(block: Mapping[str, Any]) -> None:
    languages = block.get("languages")
    if languages is None:
        return
    if not isinstance(languages, dict):
        raise CalibrationError("review_tools.languages must be an object")
    for name, spec in languages.items():
        if name not in review_formula.LANGUAGES:
            raise CalibrationError(f"language {name!r} is not a formula language")
        if not isinstance(spec, dict):
            raise CalibrationError(f"review_tools.languages.{name} must be an object")
        command = spec.get("test_command")
        report = spec.get("coverage_report")
        if command is not None and not isinstance(command, str):
            raise CalibrationError(f"review_tools.languages.{name}.test_command must be a string")
        if report is not None and not isinstance(report, str):
            raise CalibrationError(
                f"review_tools.languages.{name}.coverage_report must be a string"
            )


def _refuse_rules(tool: str, rules: object) -> None:
    if not isinstance(rules, list):
        raise CalibrationError(f"pin {tool}.rules must be a list")
    for entry in rules:
        if not isinstance(entry, dict) or ("pack" not in entry and "path" not in entry):
            raise CalibrationError(f"pin {tool}.rules entry needs pack or path")
        digest = entry.get("sha256")
        pack = "pack" in entry
        if pack and (not isinstance(digest, str) or SHA256.fullmatch(digest) is None):
            raise CalibrationError(f"pin {tool}.sha256 must be 64 hex characters")
        if digest is not None and (not isinstance(digest, str) or SHA256.fullmatch(digest) is None):
            raise CalibrationError(f"pin {tool}.sha256 must be 64 hex characters")


def _load_tools(root: Path) -> list[dict[str, Any]]:
    """The root's tool list. Importing review_tools is what loads PyYAML."""
    import review_tools  # noqa: PLC0415  (PyYAML only on the pin path)

    try:
        return review_tools.load_tool_list(locate(root, TOOL_LIST_RELATIVE))
    except review_tools.RunnerFailure as exc:
        raise CalibrationError(str(exc)) from exc
    except OSError as exc:
        raise CalibrationError(str(exc)) from exc


def _refuse_pins(pins: Mapping[str, Any], tools: Sequence[Mapping[str, Any]]) -> None:
    known = {str(row.get("tool")) for row in tools if row.get("tool")}
    for tool, spec in pins.items():
        if tool not in known:
            raise CalibrationError(f"unknown tool {tool!r}")
        if not isinstance(spec, dict):
            raise CalibrationError(f"pin {tool} must be an object")
        version = spec.get("version")
        if version is not None and not isinstance(version, str):
            raise CalibrationError(f"pin {tool}.version must be a string")
        if "rules" in spec and spec.get("rules") is not None:
            _refuse_rules(str(tool), spec["rules"])


def _rule_identity(entry: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return (entry.get("pack"), entry.get("path"), entry.get("sha256"))


def _row_rules(row: Mapping[str, Any]) -> list[tuple[Any, Any, Any]]:
    rules = row.get("rules") or []
    if not isinstance(rules, list):
        return []
    return [_rule_identity(item) for item in rules if isinstance(item, Mapping)]


def _pin_differs(row: Mapping[str, Any], pin: Mapping[str, Any]) -> bool:
    version = pin.get("version")
    if isinstance(version, str) and version != row.get("default_version"):
        return True
    rules = pin.get("rules") if "rules" in pin else None
    if not isinstance(rules, list):
        return False
    return [_rule_identity(item) for item in rules if isinstance(item, Mapping)] != _row_rules(row)


def differing_tool(
    tools: Sequence[Mapping[str, Any]], lens: str, pins: Mapping[str, Any]
) -> str | None:
    """The first tool, in tool-list order, whose pin differs for a row that serves ``lens``."""
    for row in tools:
        tool = row.get("tool")
        if row.get("lens") != lens or not tool:
            continue
        pin = pins.get(str(tool))
        if isinstance(pin, Mapping) and _pin_differs(row, pin):
            return str(tool)
    return None


def pinned_tool(root: Path, lens: str, profile_path: Path) -> str | None:
    """The tool pinned off its default for ``lens``, or None when nothing differs.

    An absent profile, an absent ``review_tools`` block, and an absent ``pins`` key
    are no difference. Anything ``review_tools`` would refuse while loading a profile
    raises :class:`CalibrationError`.
    """
    if not profile_path.is_file():
        return None
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"not an identifier: {profile_path.name}") from exc
    if not isinstance(data, dict):
        raise CalibrationError("profile must be an object")
    _refuse_environment(data)
    if "review_tools" not in data or data["review_tools"] is None:
        return None
    block = data["review_tools"]
    if not isinstance(block, dict):
        raise CalibrationError("review_tools must be an object")
    _refuse_languages(block)
    if "pins" not in block or block["pins"] is None:
        return None
    pins = block["pins"]
    if not isinstance(pins, dict):
        raise CalibrationError("review_tools.pins must be an object")
    tools = _load_tools(root)
    _refuse_pins(pins, tools)
    return differing_tool(tools, lens, pins)


def _stale_line(drift: Sequence[str]) -> str | None:
    for item in drift:
        if item.startswith(("changed component: ", "missing component: ")):
            return f"report-only stale-fingerprint {item.split(': ', 1)[1]}"
    return None


def may_block(
    lens: str,
    language: str,
    *,
    root: Path,
    calibration: Path | None = None,
    profile: Path | None = None,
) -> str:
    """One line: the answer and the reason. The first matching reason wins.

    Raises :class:`CalibrationError` for an unknown lens or language, a malformed
    file, or a malformed profile. The caller prints that on stderr and exits 2.
    """
    if lens not in review_formula.LENSES:
        raise CalibrationError(f"unknown lens: {lens}")
    if language not in review_formula.LANGUAGES:
        raise CalibrationError(f"unknown language: {language}")
    root = Path(root)
    path = Path(calibration) if calibration is not None else default_calibration_path()
    if not path.is_file():
        raise CalibrationError(f"missing calibration file: {CALIBRATION_RELATIVE}")
    found = problems_in(path)
    if found:
        raise CalibrationError(found[0])
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["corpus_run"] == "no-run":
        return "report-only no-run"
    stale = _stale_line(fingerprint_drift(root, data["fingerprint"]))
    if stale is not None:
        return stale
    row = data["lenses"][lens]
    if row["drift"] == "report-only":
        return "report-only drift"
    if language not in row["languages"]:
        return "report-only no-verdict"
    profile_path = Path(profile) if profile is not None else root / ".saga-profile.json"
    tool = pinned_tool(root, lens, profile_path)
    if tool is not None:
        return f"report-only pinned-tool {tool}"
    if row["languages"][language]["verdict"] == "report-only":
        return "report-only verdict"
    return "yes cleared"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_calibration.py",
        description="Say whether a lens may block in a language, from the calibration file.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    may = commands.add_parser("may-block", help="Print the answer and its reason on one line.")
    may.add_argument("--lens", required=True, help="A lens id from the formula.")
    may.add_argument("--language", required=True, help="A language id from the formula.")
    may.add_argument(
        "--root",
        type=Path,
        help=(
            "Base commit whose .saga-profile.json is read. Never the reviewed head. "
            "Does not select the calibration file or the component bytes; those come "
            "from the installed saga."
        ),
    )
    may.add_argument(
        "--file",
        type=Path,
        help=(
            "Calibration JSON from the installed saga. Never the reviewed head. "
            "Defaults to this package's references/review-calibration.json."
        ),
    )
    may.add_argument(
        "--profile",
        type=Path,
        help=(
            "Profile JSON from the base commit. Never the reviewed head. "
            "Defaults to --root/.saga-profile.json when --root is set, otherwise "
            "the checkout that contains this script."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.profile is not None:
        profile = args.profile
    elif args.root is not None:
        profile = args.root / ".saga-profile.json"
    else:
        profile = Path(__file__).resolve().parents[3] / ".saga-profile.json"
    try:
        line = may_block(
            args.lens,
            args.language,
            root=package_dir(),
            calibration=args.file,
            profile=profile,
        )
    except CalibrationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
