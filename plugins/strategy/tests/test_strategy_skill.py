"""Standalone package contract for strategy."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]

def _joined(*parts: str) -> str:
    return "".join(parts)


FORBIDDEN = (
    _joined("plugins", "/saga"),
    _joined("orches", "trate"),
    _joined("engine_", "offer.py"),
    _joined("redis-", "channel"),
    _joined("/", "office-hours"),
    _joined("/", "spec"),
    _joined("/", "founder-review"),
    _joined("/", "work"),
    _joined("saga", ".py"),
    _joined(".claude", "/saga"),
    _joined(".orches", "trate"),
)


def authored_files() -> list[Path]:
    found: list[Path] = []
    for path in PACKAGE.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if "_bundled" in path.parts:
            continue
        found.append(path)
    return found


class StrategyContractTests(unittest.TestCase):
    def test_forbidden_couplings_are_absent(self) -> None:
        hits: list[str] = []
        for path in authored_files():
            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            for needle in FORBIDDEN:
                if needle.lower() in lowered:
                    hits.append(f"{path.relative_to(PACKAGE)}: {needle}")
        self.assertEqual(hits, [])

    def test_skill_frontmatter_names_the_directory(self) -> None:
        document = PACKAGE / "skills" / "strategy" / "SKILL.md"
        self.assertTrue(document.is_file())
        lines = document.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "---")
        self.assertIn("name: strategy", lines)
        self.assertTrue(any(line.startswith("description:") for line in lines))

    def test_there_is_no_command_wrapper_beside_the_skill(self) -> None:
        commands = PACKAGE / "com.infiquetra.claude" / "commands"
        self.assertFalse(commands.exists())

    def test_portable_and_claude_manifests_agree_on_name(self) -> None:
        import json

        portable = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))
        claude = json.loads((PACKAGE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(portable["name"], "strategy")
        self.assertEqual(claude["name"], "strategy")
        self.assertEqual(claude.get("skills"), "./skills/")
        self.assertNotIn("commands", claude)

