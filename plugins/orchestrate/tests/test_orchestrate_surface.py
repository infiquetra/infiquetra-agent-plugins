"""The slimmed command surface and the release surfaces that carry it (issue #1025, U8).

These are the card's own runnable acceptance criteria, as tests rather than as a shell transcript,
plus the version guard this repository requires of every plugin change.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from orchestrate_support import load_orchestrate

#: The production driver this module drives. Constructed here, not imported from the shared
#: helper, so the module names on its own face the real file it crosses into.
ORCHESTRATE_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "orchestrate"
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)

PLUGIN_ROOT = ORCHESTRATE_SCRIPT.parents[3]
REPO_ROOT = PLUGIN_ROOT.parents[1]
MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
CHANGELOG = PLUGIN_ROOT / "CHANGELOG.md"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"

#: Orchestrate's version at this card. Named with its predecessor so a bump is deliberate.
ORCHESTRATE_VERSION = "6.0.1"
# 6.0.0 is issue 1028: the board-writeback path is removed and `merge`'s exit status 2 is retired
# with it. 5.0.0 was issue 1025, the slim to the run driver.
ORCHESTRATE_PREDECESSOR = "6.0.0"

REMOVED_SUBCOMMANDS = ("redrive", "collect", "land")
KEPT_SUBCOMMANDS = ("plan-check", "start", "go", "merge", "clean")


@pytest.fixture(scope="module")
def orch():
    return load_orchestrate("_orchestrate_surface", ORCHESTRATE_SCRIPT)


@pytest.fixture(scope="module")
def help_text(orch) -> str:
    parser_names: list[str] = []
    import argparse

    original = argparse.ArgumentParser.parse_args

    def capture(self, argv=None, namespace=None):
        for action in self._subparsers._actions if self._subparsers else []:
            if isinstance(action, argparse._SubParsersAction):
                parser_names.extend(action.choices)
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture  # type: ignore[method-assign]
    try:
        with pytest.raises(SystemExit):
            orch.main([])
    finally:
        argparse.ArgumentParser.parse_args = original  # type: ignore[method-assign]
    return "\n".join(parser_names)


class TestTheSubcommandSurface:
    @pytest.mark.parametrize("name", REMOVED_SUBCOMMANDS)
    def test_the_removed_subcommands_are_gone(self, help_text: str, name: str) -> None:
        assert name not in help_text.split()

    @pytest.mark.parametrize("name", KEPT_SUBCOMMANDS)
    def test_the_kept_subcommands_are_present(self, help_text: str, name: str) -> None:
        assert name in help_text.split()

    def test_the_removed_command_functions_are_gone_too(self, orch) -> None:
        """A subcommand hidden from the parser but still callable is not removed."""
        for name in ("cmd_redrive", "cmd_collect", "cmd_land"):
            assert not hasattr(orch, name), name

    def test_merge_replaces_land(self, orch) -> None:
        assert callable(orch.cmd_merge)


class TestTheGrepCriterion:
    def test_the_driver_names_no_reservation_or_writeback_record(self) -> None:
        """The card's second acceptance criterion, as a test.

        Two of the three names never appeared in this file -- checked against base commit
        4e951f0e -- so this asserts the property the criterion is about rather than re-deriving
        the count.
        """
        source = ORCHESTRATE_SCRIPT.read_text(encoding="utf-8")
        pattern = re.compile(r"reserved_landing_paths|launch_reservation|record_writeback_outcome")
        assert pattern.findall(source) == []


class TestTheCompanionFloorWarns:
    def test_a_below_floor_companion_warns_and_the_command_continues(
        self, orch, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr(orch, "_AGENT_LAUNCHER_AVAILABLE", True)
        monkeypatch.setattr(
            orch, "_AGENT_LAUNCHER_ERROR", "agent-launcher 1.0.0 is installed; requires >=1.7.0"
        )
        monkeypatch.setattr(orch, "_COMPANION_FAULT_PRINTED", False)
        orch.assert_agent_launcher_available()
        assert "requires >=1.7.0" in capsys.readouterr().err

    def test_a_missing_companion_still_refuses(self, orch, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(orch, "_AGENT_LAUNCHER_AVAILABLE", False)
        monkeypatch.setattr(orch, "_AGENT_LAUNCHER_ERROR", "")
        with pytest.raises(SystemExit) as caught:
            orch.assert_agent_launcher_available()
        assert "agent-launcher plugin not found" in str(caught.value)


class TestReleaseSurfacesMoveTogether:
    def test_the_manifest_carries_this_cards_version(self) -> None:
        assert json.loads(MANIFEST.read_text())["version"] == ORCHESTRATE_VERSION

    def test_the_marketplace_entry_agrees_with_the_manifest(self) -> None:
        entries = json.loads(MARKETPLACE.read_text())["plugins"]
        row = next(entry for entry in entries if entry["name"] == "orchestrate")
        assert row["version"] == ORCHESTRATE_VERSION

    def test_the_changelog_opens_on_this_version_and_names_its_predecessor(self) -> None:
        headings = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(), re.MULTILINE)
        assert headings[0] == ORCHESTRATE_VERSION
        assert headings[1] == ORCHESTRATE_PREDECESSOR

    @staticmethod
    def _section(version: str) -> str:
        """One changelog entry, found by its own heading.

        These two guards used to read "the latest entry", which was the 5.0.0 entry only for as
        long as 5.0.0 stayed the newest release. Issue 1028 shipped 5.1.0 and both guards began
        asserting that a release which removed nothing must name three removals. What they are
        actually pinning is that **the 5.0.0 entry** keeps naming what 5.0.0 removed, so they now
        find that entry by heading.
        """
        text = CHANGELOG.read_text()
        start = text.index(f"## [{version}]")
        rest = text[start + 1 :]
        end = rest.find("\n## [")
        return rest if end == -1 else rest[:end]

    @pytest.mark.parametrize("name", REMOVED_SUBCOMMANDS)
    def test_the_changelog_names_every_removed_subcommand(self, name: str) -> None:
        section = self._section("5.0.0")
        assert f"`{name}`" in section, f"the 5.0.0 entry must name {name} by name"

    def test_the_changelog_names_the_record_replacement_as_breaking(self) -> None:
        section = self._section("5.0.0").lower()
        assert "run record" in section
        assert "breaking" in section

    def test_this_releases_entry_names_what_it_removed(self) -> None:
        """5.1.0's own claim: the board writeback is gone and exit status 2 went with it."""
        section = self._section("6.0.0").lower()
        assert "board-writeback" in section or "board writeback" in section
        assert "exit status" in section and "2" in section
