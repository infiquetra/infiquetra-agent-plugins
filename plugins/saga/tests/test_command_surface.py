"""The saga command surface is exactly thirteen commands in fourteen files.

Issue 1030. The card's first acceptance criterion is a count, and a count alone is a weak guard: a
tree that deleted one survivor and kept one removed command still prints fourteen. So this module
checks three things that a count cannot -- which names survive, which names are gone, and that every
surviving command still resolves the skill it names.

The removed names are spelled here exactly as the card and the acceptance criterion spell them, so a
partially reverted deletion fails on the name rather than on arithmetic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMANDS = REPO_ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "commands"
SKILLS = REPO_ROOT / "plugins" / "saga" / "skills"

#: The thirteen commands the simplification review keeps, plus the one alias. Fourteen files.
SURVIVING_COMMANDS: tuple[str, ...] = (
    "brainstorm",
    "ceo-review",
    "code-review",
    "doc-review",
    "founder-review",
    "ideate",
    "investigate",
    "office-hours",
    "plan",
    "qa",
    "retro",
    "spec",
    "strategy",
    "work",
)

#: The eleven commands issue 1030 removes, in the card's own spelling. Ten of them have a command
#: file at the base; ``delegation-audit`` is reached through its skill directory alone, which is why
#: this tuple and the file count differ by one.
REMOVED_COMMANDS: tuple[str, ...] = (
    "outcome",
    "loop",
    "resume",
    "handoff",
    "optimize",
    "pulse",
    "delegation-audit",
    "promote",
    "engines",
    "tier",
    "fleet-doctor",
)

#: The nine skill directories that go with them. ``engines`` and ``tier`` never had one.
REMOVED_SKILLS: tuple[str, ...] = (
    "outcome",
    "loop",
    "resume",
    "handoff",
    "optimize",
    "pulse",
    "delegation-audit",
    "promote",
    "fleet-doctor",
)

#: ``/ceo-review`` is an alias: it has a command file and deliberately no skill directory of its own.
ALIAS_COMMANDS: frozenset[str] = frozenset({"ceo-review"})


def _command_files() -> list[Path]:
    return sorted(COMMANDS.glob("*.md"))


def test_the_command_directory_holds_exactly_fourteen_files() -> None:
    """The card's acceptance criterion, verbatim: ``ls plugins/saga/com.infiquetra.claude/commands | wc -l`` prints 14."""
    assert len(list(COMMANDS.iterdir())) == 14, sorted(p.name for p in COMMANDS.iterdir())


def test_the_surviving_commands_are_exactly_the_fourteen_named() -> None:
    assert tuple(sorted(p.stem for p in _command_files())) == SURVIVING_COMMANDS


@pytest.mark.parametrize("command", REMOVED_COMMANDS)
def test_a_removed_command_has_no_command_file(command: str) -> None:
    assert not (COMMANDS / f"{command}.md").exists(), (
        f"/{command} is removed by issue 1030; its command file is back"
    )


@pytest.mark.parametrize("skill", REMOVED_SKILLS)
def test_a_removed_command_has_no_skill_directory(skill: str) -> None:
    assert not (SKILLS / skill).exists(), (
        f"the {skill} skill is removed by issue 1030; its directory is back"
    )


def test_the_skill_directories_are_exactly_the_thirteen_that_remain() -> None:
    expected = tuple(sorted(set(SURVIVING_COMMANDS) - ALIAS_COMMANDS))
    assert tuple(sorted(p.name for p in SKILLS.iterdir() if p.is_dir())) == expected


@pytest.mark.parametrize("command", sorted(set(SURVIVING_COMMANDS) - ALIAS_COMMANDS))
def test_every_surviving_command_resolves_the_skill_it_names(command: str) -> None:
    """A command file that names a skill directory which does not exist is a dead command.

    The count test cannot see this: a command file pointing at nothing still counts as one file.
    """
    skill = SKILLS / command / "SKILL.md"
    assert skill.is_file(), f"/{command} names a skill with no SKILL.md at {skill}"
    frontmatter = skill.read_text(encoding="utf-8").split("---")[1]
    name = re.search(r"^name:\s*(\S+)", frontmatter, re.M)
    assert name is not None, f"{skill} has no name in its frontmatter"
    assert name.group(1) == command, (
        f"{skill} declares name {name.group(1)!r} but lives under {command!r}"
    )


def test_the_alias_points_at_the_command_it_aliases() -> None:
    """``/ceo-review`` has no skill of its own; it must say which command it stands for."""
    body = (COMMANDS / "ceo-review.md").read_text(encoding="utf-8")
    assert "founder-review" in body, "the /ceo-review alias no longer names /founder-review"
