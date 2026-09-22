#!/usr/bin/env python3
"""Parse an issue body for context refs, acceptance criteria, and scope hints."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ADR_RE = re.compile(r"\bADR[-\s]?(\d{2,4})\b", re.IGNORECASE)
AC_RE = re.compile(r"\bAC[-\s]?(\d{1,3})\b", re.IGNORECASE)
ROUND_RE = re.compile(r"\b[Rr]ound[-\s]?(\d+)\b")
SECURITY_RE = re.compile(
    r"\b(auth|jwt|oauth|secret|credential|crypto|kms|iam|encrypt|decrypt|signing)\b",
    re.IGNORECASE,
)
API_RE = re.compile(r"\b(endpoint|rest|openapi|api/|/api|handler|route|sdk|contract)\b")
INFRA_RE = re.compile(r"\b(cdk|cloudformation|terraform|lambda|dynamodb|s3|vpc)\b")
PRIVACY_RE = re.compile(r"\b(pii|gdpr|consent|retention|personal data|anonymize|hipaa)\b")
REFACTOR_RE = re.compile(r"\b(refactor|dry|solid|complexity|technical debt|cleanup)\b")
H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)

# The five keyword flags, in the order `extract` emits them.  Saga's mandatory
# test gate and four skill documents read these keys BY NAME, so the names are a
# contract: `--flags` widens what they hold and never renames or removes one.
FLAG_KEYS = (
    "has_security",
    "has_api",
    "has_infra",
    "has_privacy",
    "has_refactor",
)

# The seven approval boundaries from the sdlc process chapter
# docs/process/operator-escalations.md.  These have no keyword floor and no
# consumer: they are reported for a human to read, and nothing in this
# repository grants or withholds an approval on them (issue 1036).
APPROVAL_BOUNDARY_KEYS = (
    "production",
    "destructive",
    "credentials",
    "permissions",
    "billing",
    "external_commitments",
    "process_authority",
)
HANDOFF_MATURITY_VALUES = {
    "idea-ready",
    "requirements-ready",
    "plan-ready",
    "resume-ready",
    "deferred-context",
    "pending-confirmation",
}


def unique_sorted_ints(values: Iterable[str]) -> list[int]:
    return sorted({int(value) for value in values})


def split_h3_sections(body: str) -> dict[str, str]:
    matches = list(H3_RE.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        header = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[header] = body[start:end].strip()
    return sections


def first_content_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().strip("`")
        if stripped:
            return stripped
    return ""


def parse_source_context(text: str) -> dict[str, str]:
    context: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped[2:].split(":", 1)
        context[key.strip().lower().replace(" ", "_")] = value.strip()
    return context


def extract_handoff(body: str) -> dict[str, object]:
    sections = split_h3_sections(body)
    raw_maturity = first_content_line(sections.get("Handoff maturity", ""))
    maturity = raw_maturity if raw_maturity in HANDOFF_MATURITY_VALUES else ""
    # A section that is PRESENT but carries an unrecognized value is not the same as an absent
    # section. Collapsing both to "" made a malformed declaration — including every `unknown:`
    # sentinel — read as benign to /loop, which treats empty as "nothing declared" (API-24).
    unrecognized_declaration = bool(raw_maturity) and not maturity
    source_context = parse_source_context(sections.get("Source context", ""))
    return {
        "maturity": maturity,
        "suggested_next_action": first_content_line(sections.get("Suggested next action", "")),
        "source": source_context.get("source", ""),
        "source_type": source_context.get("source_type", ""),
        "source_title": source_context.get("source_title", ""),
        "can_plan": maturity in {"idea-ready", "requirements-ready"},
        "can_work": maturity in {"plan-ready", "resume-ready"},
        "requires_clarification": maturity == "deferred-context" or unrecognized_declaration,
    }


def extract(body: str) -> dict[str, object]:
    adrs = unique_sorted_ints(ADR_RE.findall(body))
    acceptance = unique_sorted_ints(AC_RE.findall(body))
    rounds = unique_sorted_ints(ROUND_RE.findall(body))
    lowered = body.lower()
    handoff = extract_handoff(body)

    test_name_parts: list[str] = []
    if adrs:
        test_name_parts.append(f"ADR_{adrs[0]:03d}")
    if acceptance:
        test_name_parts.append(f"AC_{acceptance[0]}")

    test_naming_pattern = "test_<module>_<scenario>"
    if test_name_parts:
        test_naming_pattern = f"test_{'_'.join(test_name_parts)}_<scenario>"

    return {
        "adr_refs": [f"ADR-{number:04d}" for number in adrs],
        "ac_refs": [f"AC-{number}" for number in acceptance],
        "round_refs": rounds,
        "flags": {
            "has_security": bool(SECURITY_RE.search(body)),
            "has_api": bool(API_RE.search(lowered)),
            "has_infra": bool(INFRA_RE.search(lowered)),
            "has_privacy": bool(PRIVACY_RE.search(lowered)),
            "has_refactor": bool(REFACTOR_RE.search(lowered)),
        },
        "handoff": handoff,
        "test_naming_pattern": test_naming_pattern,
        "first_line": body.splitlines()[0].strip()[:200] if body else "",
    }


def _load_widen() -> Any:
    """Load the fleet-core widen-only primitive, the way `jev.py` loads its own.

    Imported here rather than at module scope on purpose: without ``--flags``
    this script has no fleet-core dependency, makes no network call, and behaves
    exactly as it did before issue 1036 -- which is what keeps the four saga
    skills that call it deterministic.
    """
    scripts_dir = str(Path(__file__).resolve().parent / "_bundled")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    # The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose
    # resolution ladder is Claude-specific runtime discovery this package must not
    # retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on
    # disk at install time and Fleet Core is never installed separately.
    import jev_widen  # noqa: PLC0415

    return jev_widen


def fetch_issue_body(number: int, repo: str | None = None, timeout: float = 60.0) -> str:
    """Read an issue body with `gh`, which infers the repository from the directory."""
    command = ["gh", "issue", "view", str(number), "--json", "body", "-q", ".body"]
    if repo:
        command.extend(["--repo", repo])
    result = subprocess.run(  # noqa: S603 - a fixed argument vector, no shell
        command, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`gh issue view {number}` failed: {result.stderr.strip() or 'no output'}"
        )
    return result.stdout


def _keyword_only(floors: Mapping[str, bool], note: str) -> dict[str, Any]:
    """The shape `widen_flags` returns when no model answer was obtained at all."""

    def _detail(key: str) -> dict[str, Any]:
        value = bool(floors[key])
        return {
            "regex": value,
            "probability": None,
            "union": value,
            "source": "regex" if value else "none",
        }

    return {
        "flags": {key: bool(floors[key]) for key in FLAG_KEYS},
        "flags_detail": {key: _detail(key) for key in FLAG_KEYS},
        "approval_boundaries": {key: _detail(key) for key in APPROVAL_BOUNDARY_KEYS},
        "judgment": {
            "threshold": None,
            "resolved_model": "",
            "asked": False,
            "note": note,
        },
    }


def widen_flags(
    body: str,
    parsed: Mapping[str, Any],
    *,
    widen: Any = None,
    ask: Any = None,
    threshold: float | None = None,
    log: bool = True,
) -> dict[str, Any]:
    """Union the keyword flags with a model judgment, widen-only.

    Fails open to the keyword result: any client failure leaves every flag
    exactly as the regular expressions set it and names the reason in ``note``.
    The caller still exits 0, because four saga skills read this output and a
    missing key must not break them.
    """
    keyword_flags = parsed.get("flags") or {}
    floors: dict[str, bool] = {key: bool(keyword_flags.get(key)) for key in FLAG_KEYS}
    floors.update(dict.fromkeys(APPROVAL_BOUNDARY_KEYS, False))

    if widen is None:
        try:
            widen = _load_widen().widen
        except Exception as exc:  # noqa: BLE001 - an absent fleet-core is not a parse failure
            return _keyword_only(floors, f"fleet-core is unavailable ({type(exc).__name__})")

    try:
        result = widen(
            {"issue": body},
            "issue-flags",
            floors,
            decision_prefix="issue-flags",
            threshold=threshold,
            ask=ask,
            log=log,
        )
    except Exception as exc:  # noqa: BLE001 - fail open covers the primitive's own faults too
        # `widen` already converts every CLIENT failure into a floors-only
        # result.  This catches the rest -- an unknown verb, a registry that
        # moved, a bug in the primitive -- because the promise four saga skills
        # rely on is "this script still prints its JSON", not "the client
        # behaved".
        return _keyword_only(floors, f"the judgment raised {type(exc).__name__}")

    judgments = result.judgments
    return {
        "flags": {key: judgments[key].union for key in FLAG_KEYS},
        "flags_detail": {key: judgments[key].to_dict() for key in FLAG_KEYS},
        "approval_boundaries": {key: judgments[key].to_dict() for key in APPROVAL_BOUNDARY_KEYS},
        "judgment": {
            "threshold": result.threshold,
            "resolved_model": result.resolved_model,
            "asked": result.asked,
            "note": result.note,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", default="-", help='Path to issue body, or "-" for stdin')
    parser.add_argument("--issue", type=int, help="Issue number to read the body from with `gh`")
    parser.add_argument("--repo", help="owner/repo for --issue (default: inferred by `gh`)")
    parser.add_argument(
        "--flags",
        action="store_true",
        help="also ask the model about each flag category and print the widen-only union",
    )
    args = parser.parse_args(argv)
    if args.issue is not None and args.body_file != "-":
        parser.error("pass either --issue or --body-file, not both")
    if args.repo is not None and args.issue is None:
        parser.error("--repo only applies to --issue")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.issue is not None:
        try:
            body = fetch_issue_body(args.issue, args.repo)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.body_file == "-":
        body = sys.stdin.read()
    else:
        body = Path(args.body_file).read_text(encoding="utf-8")

    payload = extract(body)

    if args.flags:
        payload.update(widen_flags(body, payload))

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
