"""Tests for the voice Agent Skill entrypoint (#33).

The skill is the smallest legitimate portable command surface: one
``SKILL.md`` whose frontmatter stays inside the validated allowlist, that
names the bundled CLI starting the pane and the in-pane keys, and that
declares no listening tool or server of any kind. The CLI is the only
command surface.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = PACKAGE_ROOT / "skills" / "voice" / "SKILL.md"
CLI_PATH = PACKAGE_ROOT / "scripts" / "voice_cli.py"

sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))

import process  # noqa: E402
import voice_cli  # noqa: E402

#: The open Agent Skills frontmatter allowlist mirrored by
#: ``scripts/check_repo.py`` — kept here so the entrypoint fails its own
#: tests, not only the repository gate.
ALLOWED_FRONTMATTER_FIELDS = (
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
)

FRONTMATTER_DELIMITER = "---"
FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")

IN_PANE_KEYS = ("t", "s", "u", "d", "q")


def read_frontmatter(text: str) -> dict[str, str] | None:
    """Top-level scalar keys of a YAML frontmatter block, or ``None``."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == FRONTMATTER_DELIMITER:
            return fields
        if not line.strip() or line[0] in " \t-#":
            continue
        match = FRONTMATTER_KEY.match(line)
        if match:
            value = (match.group(2) or "").strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[match.group(1)] = value
    return None


class SkillDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.frontmatter = read_frontmatter(cls.text)
        cls.body = cls.text

    def test_skill_document_exists(self) -> None:
        self.assertTrue(
            SKILL_PATH.is_file(), "the portable skill document is missing"
        )

    def test_frontmatter_is_present_and_inside_the_allowlist(self) -> None:
        self.assertIsNotNone(
            self.frontmatter, "the skill document carries no frontmatter block"
        )
        disallowed = [
            field
            for field in self.frontmatter
            if field not in ALLOWED_FRONTMATTER_FIELDS
        ]
        self.assertEqual(disallowed, [])

    def test_skill_name_matches_its_directory(self) -> None:
        self.assertEqual(self.frontmatter.get("name"), "voice")

    def test_skill_carries_a_description(self) -> None:
        self.assertTrue(self.frontmatter.get("description", "").strip())

    def test_compatibility_states_the_floor_exactly_or_is_absent(self) -> None:
        declared = self.frontmatter.get("compatibility")
        if declared is not None:
            self.assertEqual(declared, "python>=3.12")

    def test_skill_names_the_cli_that_starts_the_pane(self) -> None:
        self.assertIn("voice_cli.py", self.body)
        self.assertIn("pane", self.body)

    def test_skill_names_every_in_pane_key(self) -> None:
        for key in IN_PANE_KEYS:
            self.assertIn(f"`{key}`", self.body, f"the {key!r} key is undocumented")

    def test_skill_declares_no_server_or_listening_tool(self) -> None:
        lowered = self.body.lower()
        # The needle is composed so the package itself stays grep-clean.
        self.assertNotIn("mc" + "p", lowered)
        self.assertNotIn("model context protocol", lowered)


class CliSurfaceTests(unittest.TestCase):
    def test_cli_file_exists(self) -> None:
        self.assertTrue(CLI_PATH.is_file(), "the bundled CLI is missing")

    def test_cli_help_names_every_documented_command(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CLI_PATH), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for command in ("pane", "bind", "preflight", "toggle", "stop"):
            self.assertIn(command, completed.stdout)

    def test_cli_imports_without_deliver_existing(self) -> None:
        # The CLI is importable before U5 lands: deliver is a lazy seam,
        # never a module-level import (KTD16).
        script = (
            "import sys\n"
            f"sys.path.insert(0, {str(PACKAGE_ROOT / 'scripts')!r})\n"
            "import voice_cli\n"
            "assert 'deliver' not in sys.modules\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_bind_failure_surfaces_the_error_envelope_without_writing(self) -> None:
        # The herdr error envelope rides stderr; its message must surface,
        # and a failed bind must write no binding.
        import contextlib
        import io

        envelope = {
            "id": "cli:agent:get",
            "error": {
                "code": "agent_not_found",
                "message": "agent target no-such-agent not found",
            },
        }
        failed = subprocess.CompletedProcess(
            args=["herdr", "agent", "get", "no-such-agent"],
            returncode=1,
            stdout="",
            stderr=json.dumps(envelope),
        )
        stderr_buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as state_dir, mock.patch.dict(
            os.environ, {"VOICE_STATE_DIR": state_dir}
        ), mock.patch.object(process, "run", return_value=failed):
            with contextlib.redirect_stderr(stderr_buffer):
                exit_code = voice_cli.main(["bind", "no-such-agent"])
            binding_written = (Path(state_dir) / "binding.json").exists()
        self.assertEqual(exit_code, 1)
        self.assertIn(
            "agent target no-such-agent not found", stderr_buffer.getvalue()
        )
        self.assertFalse(binding_written)


class CliBindTests(unittest.TestCase):
    """The ``bind`` command (KTD7), through the package's subprocess seam."""

    SESSION_ID = "11111111-2222-4333-8444-555555555555"

    def _envelope(self, **overrides) -> dict:
        agent = {
            "agent": "claude",
            "name": "example-agent",
            "agent_session": {
                "agent": "claude",
                "kind": "id",
                "source": "herdr:claude",
                "value": self.SESSION_ID,
            },
            "agent_status": "idle",
            "pane_id": "w1:p1",
        }
        agent.update(overrides)
        return {
            "id": "cli:agent:get",
            "result": {"type": "agent_info", "agent": agent},
        }

    def _completed(self, envelope: dict) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["herdr", "agent", "get", "example-agent"],
            returncode=0,
            stdout=json.dumps(envelope),
            stderr="",
        )

    def test_bind_success_writes_the_sticky_binding(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir, mock.patch.dict(
            os.environ, {"VOICE_STATE_DIR": state_dir}
        ), mock.patch.object(
            process, "run", return_value=self._completed(self._envelope())
        ) as run_seam:
            exit_code = voice_cli.main(["bind", "example-agent"])
            binding_payload = json.loads(
                (Path(state_dir) / "binding.json").read_text(encoding="utf-8")
            )
        self.assertEqual(exit_code, 0)
        argv = run_seam.call_args[0][0]
        self.assertEqual(argv, ["herdr", "agent", "get", "example-agent"])
        self.assertEqual(run_seam.call_args.kwargs["timeout"], 10.0)
        self.assertEqual(binding_payload["agent"], "example-agent")
        self.assertEqual(binding_payload["session_id"], self.SESSION_ID)
        self.assertEqual(binding_payload["pane_id"], "w1:p1")
        self.assertTrue(binding_payload["bound_at"])

    def test_bind_refuses_an_incomplete_agent_record_by_name(self) -> None:
        import contextlib
        import io

        incomplete = self._envelope()
        del incomplete["result"]["agent"]["pane_id"]
        stderr_buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as state_dir, mock.patch.dict(
            os.environ, {"VOICE_STATE_DIR": state_dir}
        ), mock.patch.object(
            process, "run", return_value=self._completed(incomplete)
        ):
            with contextlib.redirect_stderr(stderr_buffer):
                exit_code = voice_cli.main(["bind", "example-agent"])
            binding_written = (Path(state_dir) / "binding.json").exists()
        self.assertEqual(exit_code, 1)
        self.assertIn("pane id", stderr_buffer.getvalue())
        self.assertFalse(binding_written)


if __name__ == "__main__":
    unittest.main()
