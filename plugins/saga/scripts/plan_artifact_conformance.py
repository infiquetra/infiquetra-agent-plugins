#!/usr/bin/env python3
"""Plan-artifact conformance — the U1 (#922) plan-document contract, callable.

One recursive pass over a plans root evaluates the declared frontmatter fields and the
marker triple together (R3), so a document cannot satisfy one contract and silently fail
the other. Classification follows the plan's KTD3: legacy is the absence of ``backend:``,
and nothing else — legacy documents are reported and never fail the run (R4); documents
carrying the field are new-contract and held to the full frontmatter and marker contract.

This module is the shipped contract (review F06t): it was moved out of
``tests/test_plan_artifact_conformance.py`` so the check is callable, not only enforced
when pytest runs. The test imports it; it does not duplicate it.

Run it:

    python3 plugins/saga/scripts/plan_artifact_conformance.py [root]

``root`` defaults to ``docs/plans``. The JSON report goes to stdout; the exit code is
``corpus_exit`` — 0 when no new-contract document fails the contract, 1 otherwise.
Legacy findings are reported without failing the run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# The marker triple, exactly as declared in plan/SKILL.md ("The body MUST use the exact
# section markers ..."). The definition-pin test asserts the declaration still carries
# these exact tokens, so neither half of the contract can drift silently (R6).
MARKER_IMPLEMENTATION_UNITS = "Implementation Units"
MARKER_KEY_TECHNICAL_DECISIONS = "Key Technical Decisions"
MARKER_U1_PREFIX_LABEL = "the `U1` U-ID prefix"
# The `U1` U-ID prefix: a heading or line beginning with the unit id (`U1.` / `U1:` / `U1 `).
U1_PREFIX_RE = re.compile(r"^#{0,6}\s*U1[.:\s]", re.MULTILINE)

BACKEND_ENUM = ("inline",)
REQUIRED_FIELDS = ("title", "type", "status", "date", "backend")

KIND_LEGACY_NO_BACKEND = "legacy-no-backend"
KIND_MISSING_REQUIRED_FIELD = "missing-required-field"
KIND_BACKEND_NOT_IN_ENUM = "backend-not-in-enum"
KIND_MARKER_MISSING = "marker-missing"


@dataclass(frozen=True)
class Finding:
    path: Path
    kind: str
    detail: str
    legacy: bool

    @property
    def failing(self) -> bool:
        # KTD3 / R4: legacy findings are reported, never failing.
        return not self.legacy


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Return (fields, body) for a YAML-frontmatter document.

    Absent, unterminated, or unparseable frontmatter yields empty fields and the full
    text as body — which classifies the document as legacy (no ``backend:``), never a
    crash in the corpus pass.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:i])) or {}
            except yaml.YAMLError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            return data, "\n".join(lines[i + 1 :])
    return {}, text


def _missing_markers(body: str) -> list[str]:
    missing: list[str] = []
    if MARKER_IMPLEMENTATION_UNITS not in body:
        missing.append(MARKER_IMPLEMENTATION_UNITS)
    if MARKER_KEY_TECHNICAL_DECISIONS not in body:
        missing.append(MARKER_KEY_TECHNICAL_DECISIONS)
    if not U1_PREFIX_RE.search(body):
        missing.append(MARKER_U1_PREFIX_LABEL)
    return missing


def check_document(path: Path) -> list[Finding]:
    """Evaluate the frontmatter contract and the marker triple together for one document."""
    text = path.read_text(encoding="utf-8")
    fields, body = split_frontmatter(text)
    legacy = "backend" not in fields
    findings: list[Finding] = []
    if legacy:
        findings.append(
            Finding(path, KIND_LEGACY_NO_BACKEND, "no `backend:` — legacy document", legacy=True)
        )
    else:
        for name in REQUIRED_FIELDS:
            if fields.get(name) in (None, ""):
                findings.append(
                    Finding(
                        path,
                        KIND_MISSING_REQUIRED_FIELD,
                        f"missing required field `{name}`",
                        legacy=False,
                    )
                )
        value = str(fields.get("backend", "")).strip()
        if value not in BACKEND_ENUM:
            findings.append(
                Finding(
                    path,
                    KIND_BACKEND_NOT_IN_ENUM,
                    f"`backend: {value}` is not one of {' | '.join(BACKEND_ENUM)}",
                    legacy=False,
                )
            )
    for marker in _missing_markers(body):
        findings.append(
            Finding(path, KIND_MARKER_MISSING, f"missing plan marker: {marker}", legacy)
        )
    return findings


def check_plan_corpus(root: Path) -> list[Finding]:
    """One recursive pass over every markdown document under ``root`` (R3, R5)."""
    findings: list[Finding] = []
    for path in sorted(root.rglob("*.md")):
        findings.extend(check_document(path))
    return findings


def corpus_exit(findings: Sequence[Finding]) -> int:
    return 1 if any(f.failing for f in findings) else 0


def _finding_payload(finding: Finding, root: Path) -> dict[str, Any]:
    try:
        rel = finding.path.relative_to(root).as_posix()
    except ValueError:
        rel = str(finding.path)
    return {
        "path": rel,
        "kind": finding.kind,
        "detail": finding.detail,
        "legacy": finding.legacy,
        "failing": finding.failing,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plan_artifact_conformance.py",
        description="One recursive plan-artifact conformance pass over a plans root.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        default="docs/plans",
        help="the plans root to scan (default: docs/plans)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(json.dumps({"error": f"not a directory: {root}"}), file=sys.stderr)
        return 2
    findings = check_plan_corpus(root)
    print(
        json.dumps(
            {
                "root": str(root),
                "findings": [_finding_payload(f, root) for f in findings],
                "exit": corpus_exit(findings),
            },
            indent=2,
        )
    )
    return corpus_exit(findings)


if __name__ == "__main__":
    raise SystemExit(main())
