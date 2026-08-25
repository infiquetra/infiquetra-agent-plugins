"""The portable mission-control package README must describe this package, not the Claude one.

Child #14 (Lane B), following ``tests/test_unifi_readme.py``: the upstream
README describes the Claude Code plugin, hardcodes a stale installed script
path under ``~/.claude/plugins/cache/`` for a version two years out of date,
and omits the ``flow`` skill from its own skills table. A test that only
checked that the file is present would stay green while all three defects
returned, so this module reads the shipped README as a user reads it.

The synchronized package tree lands through a parallel lane (the sync child)
and the generated Fleet Core bundle through another (the bundle child), so the
assertions that need those artifacts skip with a reason when the artifacts are
absent and assert fully when they are present. The assembled integration
branch is where everything is required green.

Standard library only, matching ``tests/test_unifi_readme.py``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins" / "mission-control"
README = PACKAGE / "README.md"
PROVENANCE = PACKAGE / "PROVENANCE.json"
DESCRIPTOR = ROOT / "ports" / "mission-control.json"

# Lane artifacts. The synchronized tree (sync child) and the generated Fleet
# Core bundle (bundle child) land on their own branches; their absence on this
# branch is a branch state, not a verdict.
SYNC_SENTINEL = PACKAGE / "scripts" / "sdlc_manager.py"
BUNDLE_SENTINEL = PACKAGE / "scripts" / "_bundled" / "tier_palette.py"

SEVEN_SKILLS = ("board", "flow", "issues", "labels", "metrics", "milestones", "rollout")

# The audited mutating subcommand table, mirrored from the port descriptor's
# ``assessment.mutating_operations``. A test below pins the two together, so
# this copy cannot drift from the descriptor silently. CLI verbs only: the
# descriptor's underscore-prefixed entry is an internal code path, not a verb.
MUTATING_VERBS = frozenset(
    {
        "add",
        "approve",
        "archive",
        "assign-mimir",
        "auto-label",
        "close",
        "comment",
        "create",
        "create-option",
        "create-prepared",
        "deploy",
        "deploy-all",
        "deploy-labels",
        "deploy-templates",
        "label-add",
        "label-remove",
        "link",
        "link-sub-issue",
        "move",
        "reopen",
        "set-field",
        "sync-fields",
        "unlink-sub-issue",
        "verify-label",
    }
)

# The audited read-only complement at the pin: every subcommand that performs
# no GitHub write. Several still write local state (prepared drafts, per-user
# defaults, the legacy rollout config); that is documented in the README and is
# not the boundary this test enforces.
READ_ONLY_VERBS = frozenset(
    {
        # board
        "view",
        "wip",
        "standup",
        "discover-fields",
        # issue
        "prepare",
        "intent-envelope",
        # labels
        "audit",
        # fields
        "discover",
        # metrics
        "cycle-time",
        "throughput",
        "wip-age",
        "column-time",
        # milestones
        "list",
        "progress",
        # rollout
        "status",
        "gap-analysis",
        "update",
        # flow
        "field-options",
        "discover-project",
        "validate-card",
        # config
        "show",
        "show-defaults",
        "init-defaults",
    }
)

# The upstream README's stale installed-path literal. Any variant of the
# plugin-cache script path is exactly the defect this README supersedes.
STALE_INSTALLED_PATHS = (".claude/plugins/cache",)

BASH_FENCE = re.compile(r"```bash\n(.*?)```", re.DOTALL)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:")
SKIP_RUN_PREFIXES = (
    "python3 -m unittest",
    "python3 -m pytest",
    "pytest ",
    "git ",
)

# The original lede identified the package as a Claude Code plugin. Later
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


def sdlc_manager_verbs(command: str) -> list[str]:
    """Return the positional verbs of a fenced sdlc_manager.py invocation.

    Empty for usage probes (``--help``) and for commands that do not invoke
    the shared CLI. The group and the action are always the first two
    positional tokens after the script path.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    script_positions = [index for index, token in enumerate(tokens) if "sdlc_manager.py" in token]
    if not script_positions:
        return []
    positionals = [
        token for token in tokens[script_positions[0] + 1 :] if not token.startswith("-")
    ]
    return positionals[:2]


class PortableReadmeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(README.is_file(), f"missing {README.relative_to(ROOT)}")
        self.text = README.read_text(encoding="utf-8")

    def test_lede_identifies_the_portable_package_not_a_claude_code_plugin(self) -> None:
        """The upstream lede introduced the Claude Code plugin, not this package."""
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

    def test_no_stale_installed_path_literal(self) -> None:
        """The upstream README hardcoded ~/.claude/plugins/cache/.../2.1.0/."""
        for needle in STALE_INSTALLED_PATHS:
            with self.subTest(needle=needle):
                self.assertNotIn(
                    needle,
                    self.text,
                    "the upstream README's installed-cache script path is "
                    "exactly the defect this README supersedes",
                )

    def test_all_seven_skills_and_the_operational_boundary_are_documented(self) -> None:
        """Child #14: the upstream table omitted flow; the boundary must be stated."""
        required = (
            *SEVEN_SKILLS,
            "INFIQUETRA_SDLC_PATH",
            "PyYAML",
            "gh ",
            "sdlc-schema",
            "python>=3.12",
            "com.infiquetra.claude",
            "PROVENANCE.json",
            "fleet-bundle.json",
        )
        for needle in required:
            with self.subTest(needle=needle):
                self.assertIn(needle, self.text)

    def test_every_audited_mutating_subcommand_is_disclosed(self) -> None:
        """The README's split must name every subcommand the descriptor audits."""
        payload = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))
        audited = {
            verb
            for verb in payload["assessment"]["mutating_operations"]
            if not verb.startswith("_")
        }
        self.assertEqual(
            audited,
            MUTATING_VERBS,
            "the port descriptor's audited mutating-verb table moved; update "
            "MUTATING_VERBS deliberately, never silently",
        )
        for verb in sorted(audited):
            with self.subTest(verb=verb):
                self.assertIn(
                    verb,
                    self.text,
                    f"the README never discloses the mutating subcommand {verb!r}",
                )

    def test_no_fenced_command_is_a_mutating_invocation(self) -> None:
        """A runnable fence may only carry the audited read-only surface."""
        for command in documented_bash_commands(self.text):
            verbs = sdlc_manager_verbs(command)
            if not verbs:
                continue
            with self.subTest(command=command):
                if len(verbs) > 1:
                    self.assertNotIn(
                        verbs[1],
                        MUTATING_VERBS,
                        f"the README documents the mutating invocation: {command!r}",
                    )
                    self.assertIn(
                        verbs[1],
                        READ_ONLY_VERBS,
                        f"the README documents {verbs[1]!r}, which is not in the "
                        f"audited read-only set: {command!r}",
                    )
                else:
                    self.assertIn(
                        verbs[0],
                        READ_ONLY_VERBS | MUTATING_VERBS,
                        f"the README documents {verbs[0]!r} as a bare group "
                        f"invocation, which is not a runnable CLI shape: {command!r}",
                    )

    def test_every_relative_markdown_link_resolves(self) -> None:
        """Package-local relative targets must exist on disk on every branch."""
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
        self.assertEqual(
            broken, [], f"broken relative links in plugins/mission-control/README.md: {broken}"
        )

    def test_every_fenced_bash_command_is_runnable_from_the_repository_root(self) -> None:
        """A documented command that cannot run is the defect class the pilot shipped."""
        if not SYNC_SENTINEL.is_file():
            self.skipTest(
                "Lane A sync artifacts are absent on this branch "
                f"({SYNC_SENTINEL.relative_to(ROOT)}); runnability asserts on the "
                "assembled integration branch"
            )
        if not BUNDLE_SENTINEL.is_file():
            self.skipTest(
                "Lane C bundle artifacts are absent on this branch "
                f"({BUNDLE_SENTINEL.relative_to(ROOT)}); runnability asserts on the "
                "assembled integration branch"
            )
        commands = documented_bash_commands(self.text)
        self.assertGreater(len(commands), 0, "the README documents no bash commands")
        with tempfile.TemporaryDirectory() as directory:
            xdg = Path(directory) / "config"
            xdg.mkdir()
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("GH_", "GITHUB_"))
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
    def test_readme_is_target_owned_so_a_resync_cannot_restore_the_upstream_readme(self) -> None:
        """Descriptor custody: README.md is superseded_by_target_owned, never a byte copy."""
        if not PROVENANCE.is_file():
            self.skipTest(
                "Lane A sync artifacts are absent on this branch "
                f"({PROVENANCE.relative_to(ROOT)}); custody asserts on the "
                "assembled integration branch"
            )
        payload = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        entries = [entry for entry in payload["files"] if entry.get("path") == "README.md"]
        self.assertEqual(len(entries), 1, "README.md must appear once in PROVENANCE.json")
        entry = entries[0]
        self.assertEqual(
            entry.get("classification"),
            "target-owned",
            "classifying README as an upstream byte copy would let a later "
            "synchronization restore the Claude-specific README this one supersedes",
        )
        self.assertNotIn("sha256", entry)


if __name__ == "__main__":
    unittest.main()
