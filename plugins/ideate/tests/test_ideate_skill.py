"""Standalone package contract for ideate."""

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


class IdeateContractTests(unittest.TestCase):
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
        document = PACKAGE / "skills" / "ideate" / "SKILL.md"
        self.assertTrue(document.is_file())
        lines = document.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "---")
        self.assertIn("name: ideate", lines)
        self.assertTrue(any(line.startswith("description:") for line in lines))

    def test_there_is_no_command_wrapper_beside_the_skill(self) -> None:
        commands = PACKAGE / "com.infiquetra.claude" / "commands"
        self.assertFalse(commands.exists())

    def test_portable_and_claude_manifests_agree_on_name(self) -> None:
        import json

        portable = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))
        claude = json.loads((PACKAGE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(portable["name"], "ideate")
        self.assertEqual(claude["name"], "ideate")
        self.assertEqual(claude.get("skills"), "./skills/")
        self.assertNotIn("commands", claude)

    def test_shaping_judgments_help_exits_zero(self) -> None:
        script = PACKAGE / "skills" / "ideate" / "scripts" / "shaping_judgments.py"
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())
        self.assertNotIn("Traceback", completed.stderr)

    def test_dedupe_fails_open_without_a_key(self) -> None:
        script = PACKAGE / "skills" / "ideate" / "scripts" / "shaping_judgments.py"
        import os

        environment = {key: value for key, value in os.environ.items() if not key.startswith("TYPESAFE_")}
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "dedupe",
                "--state",
                '{"candidates":[{"id":"C1","text":"one"},{"id":"C2","text":"two"}]}',
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"advisory": true', completed.stdout)

    def test_generated_fleet_copies_keep_history_inside_typesafe_only(self) -> None:
        historical = _joined("plugins", "/saga")
        bundled = PACKAGE / "skills" / "ideate" / "scripts" / "_bundled"
        copies = list(bundled.glob("*.py"))
        self.assertTrue(copies)
        hits: list[str] = []
        for path in copies:
            lowered = path.read_text(encoding="utf-8").lower()
            for needle in FORBIDDEN:
                if needle.lower() not in lowered:
                    continue
                if path.name == "typesafe_client.py" and needle == historical:
                    continue
                hits.append(f"{path.name}: {needle}")
        self.assertEqual(hits, [])

