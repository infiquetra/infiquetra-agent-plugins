#!/usr/bin/env python3
"""Audit Claude Code harness transcripts for real agy delegation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
# The historical path beside this file is a launcher. Transcript classification
# lives on the implementation, which is what a skill install actually runs.
AGY_DELEGATE = (
    SCRIPT_DIR.parent / "skills" / "agy-delegate" / "scripts" / "agy_delegate.py"
)
BUNDLE_RE = re.compile(r"(?:Bundle:\s*|\"bundle_path\":\s*\")(?P<path>[^\n\"\\]+)")
# No `applied` since #671: a delegation never writes the live tree, so the only passing terminal
# states are a clean run and a preserved patch. The broker-owned canonical close this used to
# validate for `applied` no longer exists.
PASS_STATUSES = frozenset({"success", "patch_ready"})


def _load_delegate() -> Any:
    spec = importlib.util.spec_from_file_location("agy_delegate", AGY_DELEGATE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {AGY_DELEGATE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["agy_delegate"] = module
    spec.loader.exec_module(module)
    return module


def audit_transcript(path: Path) -> dict[str, Any]:
    delegate = _load_delegate()
    classification = delegate.classify_transcript(path).to_jsonable()
    bundle_paths = _extract_bundle_paths(path)
    result_payloads = _load_result_payloads(bundle_paths)
    result_statuses = [
        str(payload.get("status")) for payload in result_payloads if payload.get("status")
    ]
    agy_results = [payload for payload in result_payloads if payload.get("agy_launched") is True]
    passing_results = bool(result_statuses) and all(
        payload.get("status") in PASS_STATUSES for payload in result_payloads
    )

    passed = (
        classification["classification"] == "real"
        and classification["agy_command_seen"] is True
        and classification["claude_file_tool_seen"] is False
        and bool(bundle_paths)
        and bool(agy_results)
        and passing_results
    )

    return {
        "schema": "agy.harness-audit.v1",
        "transcript": str(path),
        "passed": passed,
        "classification": classification,
        "bundle_paths": [str(bundle) for bundle in bundle_paths],
        "result_statuses": result_statuses,
        "agy_result_count": len(agy_results),
    }


def _extract_bundle_paths(path: Path) -> list[Path]:
    bundle_paths: list[Path] = []
    seen: set[Path] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        for match in BUNDLE_RE.finditer(line):
            candidate = Path(match.group("path").strip())
            if candidate not in seen:
                seen.add(candidate)
                bundle_paths.append(candidate)
    return bundle_paths


def _load_result_payloads(bundle_paths: list[Path]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for bundle in bundle_paths:
        result_path = bundle / "result.json"
        if not result_path.exists():
            continue
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Claude Code agy harness transcripts.")
    parser.add_argument("transcript", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, help="Write JSON audit result to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audits = [audit_transcript(path) for path in args.transcript]
    payload: dict[str, Any] = {
        "schema": "agy.harness-audit-suite.v1",
        "passed": all(audit["passed"] for audit in audits),
        "audits": audits,
    }

    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
