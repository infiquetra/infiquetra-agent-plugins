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

#: The top-level frontmatter allowlist ``scripts/check_repo.py`` enforces, mirrored
#: here so the entrypoint fails its own tests, not only the repository gate.
#: ``compatibility`` belongs under ``metadata``, not at the top level.
ALLOWED_FRONTMATTER_FIELDS = (
    "name",
    "description",
    "license",
    "metadata",
    "allowed-tools",
)

FRONTMATTER_DELIMITER = "---"
FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")

IN_PANE_KEYS = ("t", "s", "u", "d", "q")


#: A double-quoted or single-quoted scalar at the start of a value.
QUOTED_SCALAR = re.compile(r"""^(?:"([^"]*)"|'([^']*)')""")

#: The minimum supported Python version, as a portable skill declares it.
FLOOR_SPECIFIER = "python>=3.12"


def _frontmatter_scalar(raw: str | None) -> str:
    """The scalar a value holds: quotes removed, and any trailing comment dropped."""
    if raw is None:
        return ""
    value = raw.strip()
    quoted = QUOTED_SCALAR.match(value)
    if quoted:
        return quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
    if value.startswith("#"):
        return ""
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def read_frontmatter(text: str) -> dict[str, object] | None:
    """Top-level keys of a YAML frontmatter block, or ``None``.

    A top-level key with a scalar value maps to that string. A top-level key with no
    value, or with only a comment after it, opens a block. The first child line under a
    block sets the indentation of its children, and only lines at exactly that
    indentation are read as children. A block whose children are dash items maps to a
    list. Lines indented deeper are never read as children, which covers the bodies of
    literal and folded scalars. A flow mapping such as ``{compatibility: ...}`` stays a
    string.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return None
    fields: dict[str, object] = {}
    owner: str | None = None
    child_indent: int | None = None
    for line in lines[1:]:
        if line.strip() == FRONTMATTER_DELIMITER:
            return fields
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            owner, child_indent = None, None
            match = FRONTMATTER_KEY.match(line)
            if match is None:
                continue
            raw = match.group(2)
            if raw is None or not raw.strip() or raw.strip().startswith("#"):
                owner = match.group(1)
                fields[owner] = {}
            else:
                fields[match.group(1)] = _frontmatter_scalar(raw)
            continue
        if owner is None:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        child = line.strip()
        block = fields[owner]
        if child == "-" or child.startswith("- "):
            if isinstance(block, dict) and not block:
                block = fields[owner] = []
            if isinstance(block, list):
                block.append(_frontmatter_scalar(child[1:]))
            continue
        match = FRONTMATTER_KEY.match(child)
        if match and isinstance(block, dict):
            block[match.group(1)] = _frontmatter_scalar(match.group(2))
    return None


def declared_floor_problem(text: str) -> str | None:
    """What is wrong with the skill's declared floor, or ``None`` when it is right or absent.

    A ``metadata`` that is present but is not a block mapping is refused, not read as
    declaring nothing, so a flow mapping or a sequence cannot hide a wrong floor.
    """
    fields = read_frontmatter(text) or {}
    if "metadata" not in fields:
        return None
    metadata = fields["metadata"]
    if not isinstance(metadata, dict):
        return "metadata is not a block mapping; write its keys as indented lines under it"
    declared = metadata.get("compatibility")
    if declared is not None and declared != FLOOR_SPECIFIER:
        return f"declares metadata.compatibility {declared!r}"
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
        description = self.frontmatter.get("description")
        self.assertTrue(isinstance(description, str) and description.strip())

    def test_compatibility_states_the_floor_exactly_or_is_absent(self) -> None:
        self.assertIsNone(declared_floor_problem(self.text))

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


#: A wrong floor, split across literals so the floor scan does not read it as a declaration.
WRONG_FLOOR = "python" ">=" "3.10"


def frontmatter(*lines: str) -> str:
    """A skill document whose frontmatter holds ``lines`` beside a ``name`` key."""
    return "\n".join(["---", "name: example", *lines, "---", "", "# Example", ""])


class FrontmatterReaderTests(unittest.TestCase):
    """The nested reader and the floor check, each on a fixture that names one edge case."""

    def test_a_plain_nested_compatibility_is_read(self) -> None:
        text = frontmatter("metadata:", f"  compatibility: {FLOOR_SPECIFIER}")
        self.assertEqual(
            read_frontmatter(text),
            {"name": "example", "metadata": {"compatibility": FLOOR_SPECIFIER}},
        )

    def test_a_commented_metadata_header_still_opens_a_mapping(self) -> None:
        text = frontmatter(
            "metadata: # the floor is declared below",
            f"  compatibility: {FLOOR_SPECIFIER}",
        )
        self.assertEqual(read_frontmatter(text)["metadata"], {"compatibility": FLOOR_SPECIFIER})
        self.assertIsNone(declared_floor_problem(text))

    def test_a_trailing_comment_is_not_part_of_a_nested_value(self) -> None:
        text = frontmatter("metadata:", f"  compatibility: {FLOOR_SPECIFIER}  # minimum")
        self.assertEqual(read_frontmatter(text)["metadata"], {"compatibility": FLOOR_SPECIFIER})

    def test_a_quoted_nested_value_is_unquoted(self) -> None:
        text = frontmatter("metadata:", f'  compatibility: "{FLOOR_SPECIFIER}"')
        self.assertIsNone(declared_floor_problem(text))

    def test_a_flow_mapping_under_metadata_is_refused(self) -> None:
        text = frontmatter(f"metadata: {{compatibility: {FLOOR_SPECIFIER}}}")
        problem = declared_floor_problem(text)
        self.assertIsNotNone(problem)
        self.assertIn("not a block mapping", problem)

    def test_a_block_sequence_under_metadata_is_refused(self) -> None:
        text = frontmatter("metadata:", f"  - compatibility: {FLOOR_SPECIFIER}")
        problem = declared_floor_problem(text)
        self.assertIsNotNone(problem)
        self.assertIn("not a block mapping", problem)

    def test_a_block_scalar_sibling_does_not_overwrite_the_child(self) -> None:
        text = frontmatter(
            "metadata:",
            f"  compatibility: {FLOOR_SPECIFIER}",
            "  notes: |",
            f"    compatibility: {WRONG_FLOOR}",
        )
        self.assertEqual(read_frontmatter(text)["metadata"]["compatibility"], FLOOR_SPECIFIER)
        self.assertIsNone(declared_floor_problem(text))

    def test_a_deeper_nested_key_does_not_overwrite_the_child(self) -> None:
        text = frontmatter(
            "metadata:",
            f"  compatibility: {FLOOR_SPECIFIER}",
            f"    compatibility: {WRONG_FLOOR}",
        )
        self.assertIsNone(declared_floor_problem(text))

    def test_a_wrong_nested_floor_fails(self) -> None:
        text = frontmatter("metadata:", f"  compatibility: {WRONG_FLOOR}")
        problem = declared_floor_problem(text)
        self.assertIsNotNone(problem)
        self.assertIn(WRONG_FLOOR, problem)

    def test_a_wrong_floor_behind_a_commented_header_fails(self) -> None:
        text = frontmatter("metadata: # req", f"  compatibility: {WRONG_FLOOR}")
        self.assertIn(WRONG_FLOOR, declared_floor_problem(text) or "")

    def test_an_absent_declaration_passes(self) -> None:
        self.assertIsNone(
            declared_floor_problem(frontmatter("metadata:", "  when_to_use: Use it."))
        )
        self.assertIsNone(declared_floor_problem(frontmatter("license: Apache-2.0")))


if __name__ == "__main__":
    unittest.main()
