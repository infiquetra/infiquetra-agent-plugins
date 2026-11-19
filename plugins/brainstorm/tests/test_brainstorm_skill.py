"""Standalone package contract for brainstorm."""

from __future__ import annotations

import subprocess
import sys
import tempfile
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
        found.append(path)
    return found


class BrainstormContractTests(unittest.TestCase):
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
        document = PACKAGE / "skills" / "brainstorm" / "SKILL.md"
        self.assertTrue(document.is_file())
        lines = document.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "---")
        self.assertIn("name: brainstorm", lines)
        self.assertTrue(any(line.startswith("description:") for line in lines))

    def test_there_is_no_command_wrapper_beside_the_skill(self) -> None:
        commands = PACKAGE / "com.infiquetra.claude" / "commands"
        self.assertFalse(commands.exists())

    def test_portable_and_claude_manifests_agree_on_name(self) -> None:
        import json

        portable = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))
        claude = json.loads((PACKAGE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(portable["name"], "brainstorm")
        self.assertEqual(claude["name"], "brainstorm")
        self.assertEqual(claude.get("skills"), "./skills/")
        self.assertNotIn("commands", claude)

    def test_shaping_judgments_help_exits_zero(self) -> None:
        script = PACKAGE / "skills" / "brainstorm" / "scripts" / "shaping_judgments.py"
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())

    def test_slugify_helper_is_inlined(self) -> None:
        text = (PACKAGE / "skills" / "brainstorm" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("def slugify(value: str) -> str:", text)
        self.assertIn('return "-".join(parts) or "topic"', text)

    def test_judgment_script_resolves_from_the_skill_directory(self) -> None:
        skill_dir = PACKAGE / "skills" / "brainstorm"
        skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("$CLAUDE_PLUGIN_ROOT/skills/brainstorm/scripts/shaping_judgments.py", skill)
        self.assertIn("$SKILL_DIR/scripts/shaping_judgments.py", skill)
        self.assertNotIn("python3 scripts/shaping_judgments.py", skill)
        script = skill_dir / "scripts" / "shaping_judgments.py"
        self.assertEqual(
            (PACKAGE / "skills" / "brainstorm" / "scripts" / "shaping_judgments.py").resolve(),
            script.resolve(),
        )
        with tempfile.TemporaryDirectory() as foreign:
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=foreign,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertFalse((Path(foreign) / "scripts" / "shaping_judgments.py").exists())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())
        self.assertNotIn("ModuleNotFoundError", completed.stderr)

    def test_scratch_is_gitignored(self) -> None:
        gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".brainstorm/", gitignore)
        skill = (PACKAGE / "skills" / "brainstorm" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(".brainstorm/", skill)
        self.assertIn(".gitignore", skill)
        completed = subprocess.run(
            ["git", "check-ignore", "-q", "--", ".brainstorm/scratch/note.md"],
            cwd=REPO,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)

