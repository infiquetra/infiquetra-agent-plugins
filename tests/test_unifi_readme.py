"""The portable UniFi package README must describe this package, not the Claude one.

Cursor F-07 and OpenCode F-07 (consensus C5): a consumer opening
``plugins/unifi/README.md`` was told the package is a Claude Code plugin and
was given ``pytest`` paths that do not exist in this repository. A test that
only checked that the file is present would stay green while both defects
returned, so this module reads the shipped README as a user reads it.

Standard library only, matching ``tests/test_client_entrypoints.py``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "plugins" / "unifi" / "README.md"

ABSENT_CLIENT_TEST_MODULES = (
    "tests/test_unifi_network_client.py",
    "tests/test_unifi_protect_client.py",
)

BASH_FENCE = re.compile(r"```bash\n(.*?)```", re.DOTALL)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:")
SKIP_RUN_PREFIXES = (
    "python3 -m unittest",
    "python3 -m pytest",
    "pytest ",
    "git ",
)

# The original lede identified this package as a Claude Code plugin. Later
# sections may name the Claude adapter; that is not the defect.
CLAUDE_PLUGIN_LEDE = re.compile(r"(?i)^claude code plugin\b")


def first_prose_paragraph(text: str) -> str:
    """Return the first non-heading, non-empty paragraph."""
    chunks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if chunks:
                break
            continue
        if stripped.startswith("#"):
            continue
        chunks.append(stripped)
    return " ".join(chunks)


def link_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    return unquote(target.split("#", 1)[0])


def documented_bash_commands(text: str) -> list[str]:
    commands: list[str] = []
    for block in BASH_FENCE.findall(text):
        pieces: list[str] = []
        for raw_line in block.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.endswith("\\"):
                pieces.append(stripped[:-1].rstrip())
                continue
            pieces.append(stripped)
            commands.append(" ".join(pieces))
            pieces = []
        if pieces:
            commands.append(" ".join(pieces))
    return commands


def should_skip_running(command: str) -> bool:
    return any(command.startswith(prefix) for prefix in SKIP_RUN_PREFIXES)


class PortableReadmeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(README.is_file(), f"missing {README.relative_to(ROOT)}")
        self.text = README.read_text(encoding="utf-8")

    def test_lede_does_not_identify_this_package_as_a_claude_code_plugin(self) -> None:
        """Cursor F-07: plugins/unifi/README.md:1-3 called this a Claude Code plugin."""
        lede = first_prose_paragraph(self.text)
        self.assertTrue(lede, "the README has no opening paragraph")
        self.assertIsNone(
            CLAUDE_PLUGIN_LEDE.search(lede),
            "the portable package README still introduces itself as a Claude "
            f"Code plugin: {lede!r}",
        )
        self.assertRegex(
            lede,
            r"(?i)portable",
            "the opening paragraph must say this is the portable package",
        )

    def test_readme_does_not_point_at_client_test_modules_this_repo_does_not_ship(self) -> None:
        """Cursor F-07: plugins/unifi/README.md:180-188 named pytest files absent here."""
        for relative in ABSENT_CLIENT_TEST_MODULES:
            with self.subTest(path=relative):
                self.assertNotIn(
                    relative,
                    self.text,
                    f"README names {relative}, which is not in this repository",
                )
                self.assertFalse(
                    (ROOT / relative).is_file(),
                    f"{relative} exists; update ABSENT_CLIENT_TEST_MODULES",
                )

    def test_every_relative_markdown_link_resolves(self) -> None:
        """OpenCode F-07: package-local relative targets must exist on disk."""
        broken: list[str] = []
        found = 0
        for match in MARKDOWN_LINK.finditer(self.text):
            raw = match.group(1).strip()
            if raw.startswith(EXTERNAL_PREFIXES) or raw.startswith("#"):
                continue
            target = link_target(raw)
            if not target or "{" in target or "}" in target:
                continue
            found += 1
            destination = (README.parent / target).resolve()
            if not destination.exists():
                broken.append(raw)
        self.assertGreater(found, 0, "the portable README has no relative links to resolve")
        self.assertEqual(broken, [], f"broken relative links in plugins/unifi/README.md: {broken}")

    def test_readme_points_at_the_portable_surfaces_this_package_actually_ships(self) -> None:
        required = (
            "com.infiquetra.claude",
            "fleet-bundle.json",
            "references/site-profile.md",
            "schemas/site-profile.schema.json",
            "UNIFI_SITE_PROFILE",
            "tests/test_client_entrypoints.py",
            "scripts/check_repo.py",
        )
        for needle in required:
            with self.subTest(needle=needle):
                self.assertIn(needle, self.text)

    def test_every_fenced_bash_command_is_runnable_from_the_repository_root(self) -> None:
        """A documented command that cannot run is the defect class C5 found."""
        commands = documented_bash_commands(self.text)
        self.assertGreater(len(commands), 0, "the README documents no bash commands")
        for command in commands:
            self.assertNotIn(
                "--confirm",
                command,
                "this README must not document a mutating --confirm invocation; "
                "the operator prohibition on this repair forbids running one, "
                f"and a command we cannot verify is the original defect: {command!r}",
            )
        with tempfile.TemporaryDirectory() as directory:
            xdg = Path(directory) / "config"
            xdg.mkdir()
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("UNIFI_")
            }
            environment["XDG_CONFIG_HOME"] = str(xdg)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            ran = 0
            for command in commands:
                if should_skip_running(command) or not command.startswith("python3 "):
                    continue
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=60,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"documented command failed: {command}\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                )
                ran += 1
            self.assertGreater(ran, 0, "every documented command was skipped rather than run")


class ReadmeCustodyTests(unittest.TestCase):
    def test_readme_is_target_owned_so_a_resync_cannot_restore_the_claude_lede(self) -> None:
        """Plan: README is portable core, rewritten site-neutral — not a byte copy."""
        manifest = README.parent / "PROVENANCE.json"
        self.assertTrue(manifest.is_file())
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        entries = [entry for entry in payload["files"] if entry.get("path") == "README.md"]
        self.assertEqual(len(entries), 1, "README.md must appear once in PROVENANCE.json")
        entry = entries[0]
        self.assertEqual(
            entry.get("classification"),
            "target-owned",
            "classifying README as an upstream byte copy is what shipped the "
            "Claude-specific lede; a later synchronize() would restore it",
        )
        self.assertNotIn("sha256", entry)


if __name__ == "__main__":
    unittest.main()
