#!/usr/bin/env python3
"""Preview release notes for an Infiquetra deployment candidate."""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
from collections.abc import Sequence
from typing import Any


def run(cmd: list[str], *, check: bool = True) -> str:
    result = subprocess.run(  # nosec B603
        cmd,
        check=False,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() if result.stderr else "command failed"
        raise SystemExit(f"ERROR: {detail}")
    return result.stdout.strip()


def render_notes(base_ref: str, head_ref: str, compare: dict[str, Any]) -> str:
    commits = compare.get("commits") or []
    files = compare.get("files") or []
    lines = [
        f"release notes preview: {base_ref}...{head_ref}",
        f"commits: {len(commits)}",
        f"files changed: {len(files)}",
        "",
        "notable commits:",
    ]
    for commit in commits[:10]:
        sha = str(commit.get("sha", ""))[:7]
        message = commit.get("commit", {}).get("message", "").splitlines()[0]
        lines.append(f"- {sha} {message}")
    if len(commits) > 10:
        lines.append(f"- ... {len(commits) - 10} more commits")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Repository as owner/name")
    parser.add_argument("--base", required=True, help="Base ref or tag")
    parser.add_argument("--head", required=True, help="Head ref or tag")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run(["gh", "api", f"repos/{args.repo}/compare/{args.base}...{args.head}"])
    print(render_notes(args.base, args.head, json.loads(payload)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
