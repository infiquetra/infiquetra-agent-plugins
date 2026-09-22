#!/usr/bin/env python3
"""Block supported Claude file edits that target governed Team Mimir behavior.

This hook covers only Claude Code's file-edit tools. Shell commands and
external editors are outside this hook's supported interception boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
BLOCKED = {"target_request", "governed_review", "prohibited"}
CLASSIFIER_RESPONSE_KEYS = {"schema_version", "disposition", "owner", "reason", "category", "paths"}
PATH_RESPONSE_KEYS = {"path", "disposition", "owner", "reason", "category"}
DISPOSITION_BY_CATEGORY = {
    "ordinary_repository": "normal_merge",
    "profile_owned_behavior": "target_request",
    "external_plugin_source": "external_source",
    "custodian_owned_runtime": "custodian_review",
    "mixed_custody": "governed_review",
    "prohibited_secret_material": "prohibited",
    "unknown": "governed_review",
}


class OutsideTeamMimirError(RuntimeError):
    """The supported hook has no Team Mimir profile surface to guard."""


def resolve_team_mimir_root(cwd: str) -> Path:
    """Find a verified Team Mimir root without a workstation-specific default."""
    configured = os.environ.get("HERMES_TEAM_MIMIR_ROOT")
    candidates = [Path(configured)] if configured else [Path(cwd), *Path(cwd).parents]
    for candidate in candidates:
        root = candidate.resolve()
        if (
            root.is_dir()
            and (root / "profiles").is_dir()
            and (root / "scripts/classify_profile_change.py").is_file()
        ):
            return root
    raise RuntimeError("verified Team Mimir root is unavailable")


def normalize_path(path: str, root: Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise OutsideTeamMimirError(
                "file path is outside the verified Team Mimir root"
            ) from exc
    if ".." in candidate.parts:
        raise RuntimeError("relative file path escapes the verified Team Mimir root")
    return candidate.as_posix()


def _validate_report(report: object) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) != CLASSIFIER_RESPONSE_KEYS:
        raise RuntimeError("ownership classifier returned an incompatible response")
    category, disposition = report.get("category"), report.get("disposition")
    if (
        not isinstance(category, str)
        or not isinstance(disposition, str)
        or report.get("schema_version") != 1
        or DISPOSITION_BY_CATEGORY.get(category) != disposition
    ):
        raise RuntimeError("ownership classifier returned an incompatible response")
    if (
        not isinstance(report.get("owner"), str)
        or not report["owner"]
        or not isinstance(report.get("reason"), str)
        or not report["reason"]
    ):
        raise RuntimeError("ownership classifier returned an incompatible response")
    paths = report.get("paths")
    if not isinstance(paths, list) or not paths:
        raise RuntimeError("ownership classifier returned an incompatible response")
    for verdict in paths:
        if not isinstance(verdict, dict) or set(verdict) != PATH_RESPONSE_KEYS:
            raise RuntimeError("ownership classifier returned an incompatible response")
        category, disposition = verdict.get("category"), verdict.get("disposition")
        if (
            not isinstance(category, str)
            or not isinstance(disposition, str)
            or DISPOSITION_BY_CATEGORY.get(category) != disposition
        ):
            raise RuntimeError("ownership classifier returned an incompatible response")
        if not all(
            isinstance(verdict.get(field), str) and verdict[field]
            for field in ("path", "owner", "reason")
        ):
            raise RuntimeError("ownership classifier returned an incompatible response")
    return report


def classify(path: str, root: Path) -> dict[str, Any]:
    """Run the fixed ownership classifier and require its closed v1 response."""
    classifier = root / "scripts/classify_profile_change.py"
    result = subprocess.run(
        [sys.executable, str(classifier), "--root", str(root), "--schema-version", "1", path],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError("ownership classifier did not complete")
    return _validate_report(json.loads(result.stdout))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if payload.get("tool_name") not in FILE_TOOLS:
            return 0
        tool_input = payload.get("tool_input", {})
        path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        cwd = payload.get("cwd") or os.getcwd()
        if not isinstance(path, str) or not path or not isinstance(cwd, str):
            raise RuntimeError("supported edit lacks a file path or working directory")
        try:
            root = resolve_team_mimir_root(cwd)
        except RuntimeError:
            if not os.environ.get("HERMES_TEAM_MIMIR_ROOT"):
                return 0
            raise
        try:
            normalized_path = normalize_path(path, root)
        except OutsideTeamMimirError:
            return 0
        report = classify(normalized_path, root)
    except Exception:
        print(
            "[hermes-profile-evolution] Ownership classification is unavailable; supported "
            "profile edits are blocked. Use /hermes-profile-evolution to submit a request.",
            file=sys.stderr,
        )
        return 2
    if report["disposition"] in BLOCKED:
        print(
            "[hermes-profile-evolution] Direct edit blocked: "
            f"{report['category']} is {report['disposition']}. Submit a target-addressed "
            "proposal with /hermes-profile-evolution; do not edit profile behavior directly.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
