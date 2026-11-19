#!/usr/bin/env python3
"""Survey pinned review tools and record this machine's rule-pack digests."""

from __future__ import annotations


def _reviews_load(name: str):
    """Load a sibling without occupying the bare name Saga tests import."""
    import importlib.util
    import sys
    from pathlib import Path

    key = "infiquetra_reviews.reviews_loader"
    loader = sys.modules.get(key)
    if loader is None:
        path = Path(__file__).resolve().parent / "reviews_loader.py"
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        loader = importlib.util.module_from_spec(spec)
        sys.modules[key] = loader
        spec.loader.exec_module(loader)
    return loader.load(name)


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


def platform_helper() -> str | None:
    """The reproduction helper finish will accept: sandbox-exec or bwrap."""
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        return "sandbox-exec"
    if sys.platform == "linux" and shutil.which("bwrap"):
        return "bwrap"
    return None


def sandbox_admission() -> dict[str, Any]:
    """Whether reproduced findings can be re-run on this machine.

    finish reads ``survey.sandbox.reproduction``. Omitting it downgrades every
    reproduced finding. The helper's presence is the admission; this survey does
    not launch a model probe.
    """
    helper = platform_helper()
    if helper is None:
        return {
            "available": False,
            "reproduction": "unavailable",
            "reason": "helper-missing",
            "helper": None,
        }
    return {"available": True, "reproduction": "available", "reason": None, "helper": helper}


def _rule_caches(rows: list[dict[str, Any]], home: Path) -> dict[str, str]:
    review_tools = _reviews_load('review_tools')

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
            if not digest:
                continue
            # The catalogue row owns the digest. The pack key stays so older
            # readers still find it. Nothing here fetches a pack or writes the
            # custom rules directory.
            row_id = str(row.get("id") or "")
            if row_id:
                caches[row_id] = digest
            caches[pack] = digest
    return dict(sorted(caches.items()))


_CFN_PIN_ROWS = ("checkov-cfn", "cfn-lint")


def _detected_languages(repo: Path) -> list[str]:
    """Formula languages for *repo*, plus CloudFormation when the runner would see it.

    CloudFormation is ``cdk.json`` or a YAML, JSON, or ``.template`` file that
    mentions ``AWSTemplateFormatVersion``, ``AWS::``, or a top-level ``Resources``
    key. A template-suffix symlink counts. The predicate is ``run_languages``, so
    setup and the runner cannot disagree. Ordinary config files do not match.
    """
    review_tools = _reviews_load('review_tools')
    review_formula = _reviews_load('review_formula')

    root = Path(repo)
    found = set(review_tools.detect_languages(root))
    if "cloudformation" in review_tools.run_languages(root):
        found.add("cloudformation")
    return [language for language in review_formula.LANGUAGES if language in found]


def _recorded_pins(rows: list[dict[str, Any]], languages: list[str]) -> dict[str, dict[str, str]]:
    """Version-only pins for the CloudFormation rows, or none when that language is absent.

    The catalogue default is the recorded version. This does not execute checkov,
    cfn-lint, or uv.
    """
    if "cloudformation" not in languages:
        return {}
    pins: dict[str, dict[str, str]] = {}
    for row in rows:
        row_id = str(row.get("id") or "")
        if row_id not in _CFN_PIN_ROWS:
            continue
        version = str(row.get("default_version") or "")
        if not version or version == "not-recorded":
            continue
        pins[row_id] = {"version": version}
    return dict(sorted(pins.items()))


def survey(repo: Path, home: Path) -> dict[str, Any]:
    """Name each catalogue tool and whether its binary is on PATH. Nothing is installed.

    A CloudFormation or AWS CDK tree records version pins for ``checkov-cfn`` and
    ``cfn-lint``. A tree of ordinary YAML or JSON does not.
    """
    review_tools = _reviews_load('review_tools')

    rows = [row for row in review_tools.load_tool_list(None) if isinstance(row, dict)]
    languages = _detected_languages(repo)
    pins = _recorded_pins(rows, languages)
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
        "languages": languages,
        "pins": pins,
        "survey": {"tools": tools, "sandbox": sandbox_admission()},
        "rule_caches": _rule_caches(rows, home),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_machine(home, record)
    return record


def _print_table(record: dict[str, Any], home: Path) -> None:
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
    languages = record.get("languages") or []
    print("languages: " + (", ".join(languages) if languages else "none"))
    pins = record.get("pins") or {}
    if pins:
        print("pins:")
        for name, pin in pins.items():
            version = pin.get("version") if isinstance(pin, dict) else pin
            print(f"  {name} {version}")
    else:
        print("pins: none")
    sandbox = record.get("survey", {}).get("sandbox", {})
    print(f"sandbox: {sandbox.get('reproduction', 'unavailable')}")
    print(f"machine record: {machine_path(home)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_setup.py",
        description=(
            "Survey pinned review tools and record Semgrep rule-pack digests. "
            "This command does not install a tool."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("survey", "Print the tool table and write the machine record."),
        ("write", "Write the machine record from a fresh survey."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument(
            "--home",
            type=Path,
            help="Home directory for the machine record. May follow --repo.",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = Path(args.home) if args.home is not None else Path.home()
    if not Path(args.repo).is_dir():
        print(f"review_setup: repository does not exist: {args.repo}", file=sys.stderr)
        return 2
    record = survey(Path(args.repo), home)
    if args.command == "survey":
        _print_table(record, home)
    else:
        print(machine_path(home))
    return 0


if __name__ == "__main__":
    sys.exit(main())
