#!/usr/bin/env python3
"""Survey pinned review tools and record this machine's rule-pack digests."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MACHINE_SCHEMA = "reviews-machine.v1"
_CONFIG = Path(".config") / "infiquetra" / "reviews"
_LEGACY = Path(".saga") / "machine.json"


def config_dir(home: Path) -> Path:
    return Path(home) / _CONFIG


def machine_path(home: Path) -> Path:
    return config_dir(home) / "machine.json"


def legacy_machine_path(home: Path) -> Path:
    return Path(home) / _LEGACY


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def load_machine(home: Path) -> dict[str, Any] | None:
    """The reviews machine record, or the legacy file when the reviews file is absent.

    The legacy file is read only. This function never writes it.
    """
    primary = machine_path(home)
    if primary.is_file():
        return _read_object(primary)
    legacy = legacy_machine_path(home)
    if legacy.is_file():
        return _read_object(legacy)
    return None


def write_machine(home: Path, record: dict[str, Any]) -> Path:
    directory = config_dir(home)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "machine.json"
    payload = json.dumps(record, indent=2) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, payload.encode("utf-8"))
    finally:
        os.close(descriptor)
    path.chmod(0o600)
    return path


def _rule_caches(rows: list[dict[str, Any]], home: Path) -> dict[str, str]:
    import review_tools

    caches: dict[str, str] = {}
    for row in rows:
        for rule in row.get("rules") or []:
            if not isinstance(rule, dict) or rule.get("placeholder") is not True:
                continue
            pack = str(rule.get("pack") or "")
            if not pack:
                continue
            cache = review_tools.semgrep_cache(home, pack)
            if not cache.is_dir():
                continue
            digest = review_tools.digest_tree(cache)
            if digest:
                caches[pack] = digest
    return dict(sorted(caches.items()))


def survey(repo: Path, home: Path) -> dict[str, Any]:
    """Name each catalogue tool and whether its binary is on PATH. Nothing is installed."""
    import review_tools

    rows = [row for row in review_tools.load_tool_list(None) if isinstance(row, dict)]
    tools = []
    for row in rows:
        tool = str(row.get("tool") or row.get("id") or "")
        if not tool:
            continue
        tools.append(
            {
                "id": str(row.get("id") or tool),
                "tool": tool,
                "lens": str(row.get("lens") or ""),
                "status": "installed" if shutil.which(tool) else "missing",
                "version": str(row.get("default_version") or "not-recorded"),
            }
        )
    record = {
        "schema": MACHINE_SCHEMA,
        "ran": True,
        "repo": str(Path(repo).resolve()),
        "survey": {"tools": tools},
        "rule_caches": _rule_caches(rows, home),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_machine(home, record)
    return record


def _print_table(record: dict[str, Any]) -> None:
    tools = record.get("survey", {}).get("tools", [])
    print(f"{'id':<28} {'lens':<28} {'status':<12} version")
    for row in tools:
        print(
            f"{row['id']:<28} {row['lens']:<28} {row['status']:<12} {row['version']}"
        )
    caches = record.get("rule_caches") or {}
    if caches:
        print("rule caches:")
        for pack, digest in caches.items():
            print(f"  {pack} {digest}")
    else:
        print("rule caches: none")
    print(f"machine record: {machine_path(Path.home())}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_setup.py",
        description=(
            "Survey pinned review tools and record Semgrep rule-pack digests. "
            "This command does not install a tool."
        ),
    )
    parser.add_argument("--home", type=Path, help="Home directory for the machine record.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("survey", "Print the tool table and write the machine record."),
        ("write", "Write the machine record from a fresh survey."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--repo", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = Path(args.home) if args.home is not None else Path.home()
    if not Path(args.repo).is_dir():
        print(f"review_setup: repository does not exist: {args.repo}", file=sys.stderr)
        return 2
    record = survey(Path(args.repo), home)
    if args.command == "survey":
        _print_table(record)
    else:
        print(machine_path(home))
    return 0


if __name__ == "__main__":
    sys.exit(main())
