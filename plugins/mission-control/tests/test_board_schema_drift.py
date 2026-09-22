"""Credential-free drift guard for the committed board census (#1020).

`board_census.py --check` already compares the committed census against the
LIVE GitHub Projects API -- but it deliberately prints SKIPPED and exits 0
when no `project`-scoped token is available, which is every normal CI run
(DECISIONS `{#board-census-shape-only-live-skip-424}`). That posture is
correct and is not changed here; its consequence is that a drift can sit
unnoticed for months, which is exactly what happened: the committed census
went two board migrations stale between 2026-07-14 and 2026-09-19 while the
live leg reported nothing on every run.

This module closes that gap with an invariant that needs no network and no
credentials, so it gives signal on every CI run: whatever the census records
must agree with the vocabulary `sdlc-schema.json` declares. `sdlc-schema.json`
is the source of truth for board Status vocabulary (DECISIONS
`{#board-vocabulary-schema-is-truth-584}`); the census is a snapshot of the
live boards. When the two disagree, either the snapshot is stale or a board
drifted from the contract, and both are worth failing over.

The live comparison remains available here as an opt-in leg, enabled with
`BOARD_SCHEMA_LIVE=1`, and is skipped otherwise.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "plugins" / "mission-control" / "config"
BOARD_SCHEMA_PATH = CONFIG_DIR / "board-schema.json"
SDLC_SCHEMA_PATH = CONFIG_DIR / "sdlc-schema.json"
PROJECT_MAPPINGS_PATH = CONFIG_DIR / "project-mappings.json"

# Status names the board-stage migration (W13) renamed out of existence, plus the
# older Mount Olympus set (#1042). None may appear as a Status option on any live
# board; `sdlc-schema.json`'s own stage_flow note says so in as many words.
RETIRED_STATUS_NAMES = frozenset(
    {
        "Idea",
        "Ready",
        "Active",
        "Done",
        "Todo",
        "Committed",
        "Parked",
        "Assigned",
        "In Review",
        "Needs Question",
    }
)


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def board_schema() -> dict[str, Any]:
    return _load(BOARD_SCHEMA_PATH)


@pytest.fixture(scope="module")
def stage_flow() -> dict[str, Any]:
    workflows = _load(SDLC_SCHEMA_PATH)["workflows"]
    return dict(workflows["stage_flow"])


@pytest.fixture(scope="module")
def census_keys_by_board_key() -> dict[str, str]:
    """Map each schema board key to the census key that holds it.

    The census is keyed by the project name in `project-mappings.json`;
    `sdlc-schema.json` keys its `boards` block by board key. The two can
    diverge, and they coincide today only because every mapping sets
    `board_key` explicitly -- so cross-walk through `sdlc_manager`'s own
    `_project_board_key` rather than re-implementing its fallback here. A
    reimplementation would miss its `mount-olympus` -> `olympus` special case
    and drift from the function it claims to mirror.
    """
    sys.path.insert(0, str(REPO_ROOT / "plugins" / "mission-control" / "scripts"))
    import sdlc_manager  # noqa: PLC0415

    projects = _load(PROJECT_MAPPINGS_PATH)["projects"]
    return {sdlc_manager._project_board_key(name, proj): name for name, proj in projects.items()}


def _board_fields(
    board_schema: dict[str, Any], census_keys_by_board_key: dict[str, str], board_key: str
) -> dict[str, Any]:
    census_key = census_keys_by_board_key[board_key]
    return dict(board_schema["boards"][census_key]["fields"])


def _option_names(field: dict[str, Any]) -> set[str]:
    return {opt["name"] for opt in field.get("options", [])}


def _active_board_keys() -> list[str]:
    boards = _load(SDLC_SCHEMA_PATH)["boards"]
    return sorted(key for key, board in boards.items() if board.get("status") == "active")


ACTIVE_BOARD_KEYS = _active_board_keys()

# Every guard below is parametrized over ACTIVE_BOARD_KEYS. An empty list would
# collect zero cases and report "passed" -- a drift guard that silently covers
# nothing, which is the same failure class this module exists to catch. Assert
# the list is populated, and pin the count so a board appearing or disappearing
# is a deliberate edit rather than a quiet loss of coverage.
EXPECTED_ACTIVE_BOARD_COUNT = 3


def test_the_guard_actually_covers_the_active_boards() -> None:
    assert ACTIVE_BOARD_KEYS, (
        "no board in sdlc-schema.json is marked active, so every guard in this "
        "module collects zero cases and passes vacuously"
    )
    assert len(ACTIVE_BOARD_KEYS) == EXPECTED_ACTIVE_BOARD_COUNT, (
        f"expected {EXPECTED_ACTIVE_BOARD_COUNT} active boards, found "
        f"{len(ACTIVE_BOARD_KEYS)}: {ACTIVE_BOARD_KEYS}. If a board was added or "
        "retired on purpose, update EXPECTED_ACTIVE_BOARD_COUNT in the same change."
    )


def test_every_active_board_is_present_in_the_census(
    board_schema: dict[str, Any], census_keys_by_board_key: dict[str, str]
) -> None:
    """A board the schema calls active but the census never saw is a census
    that silently stopped covering it."""
    for board_key in ACTIVE_BOARD_KEYS:
        assert board_key in census_keys_by_board_key, (
            f"schema board {board_key!r} has no entry in project-mappings.json"
        )
        census_key = census_keys_by_board_key[board_key]
        assert census_key in board_schema["boards"], (
            f"board {board_key!r} (census key {census_key!r}) is missing from board-schema.json"
        )


@pytest.mark.parametrize("board_key", ACTIVE_BOARD_KEYS)
def test_census_fields_are_keyed_by_name(
    board_schema: dict[str, Any], census_keys_by_board_key: dict[str, str], board_key: str
) -> None:
    """`fields` is a mapping, so a consumer can index one field by name (#1020).

    Fails against a census written before that change, whose `fields` is a list.
    """
    fields = _board_fields(board_schema, census_keys_by_board_key, board_key)
    assert isinstance(fields, dict), f"{board_key}: fields must be a mapping, got {type(fields)}"
    for name, field in fields.items():
        assert field.get("name") == name, (
            f"{board_key}: field keyed {name!r} records name {field.get('name')!r}"
        )


@pytest.mark.parametrize("board_key", ACTIVE_BOARD_KEYS)
def test_status_options_match_the_declared_stage_flow_statuses(
    board_schema: dict[str, Any],
    stage_flow: dict[str, Any],
    census_keys_by_board_key: dict[str, str],
    board_key: str,
) -> None:
    """Compare as SETS: the census sorts options by name, the schema lists them
    in lifecycle order, so an ordered comparison is red on a correct file."""
    fields = _board_fields(board_schema, census_keys_by_board_key, board_key)
    assert "Status" in fields, f"{board_key}: census records no Status field"
    assert _option_names(fields["Status"]) == set(stage_flow["statuses"]), (
        f"{board_key}: Status options disagree with sdlc-schema.json stage_flow.statuses"
    )


@pytest.mark.parametrize("board_key", ACTIVE_BOARD_KEYS)
def test_stage_options_match_the_declared_stage_flow_stages(
    board_schema: dict[str, Any],
    stage_flow: dict[str, Any],
    census_keys_by_board_key: dict[str, str],
    board_key: str,
) -> None:
    """Also compared as a set, for the same reason."""
    fields = _board_fields(board_schema, census_keys_by_board_key, board_key)
    assert "Stage" in fields, f"{board_key}: census records no Stage field"
    assert _option_names(fields["Stage"]) == set(stage_flow["stages"]), (
        f"{board_key}: Stage options disagree with sdlc-schema.json stage_flow.stages"
    )


@pytest.mark.parametrize("board_key", ACTIVE_BOARD_KEYS)
def test_no_retired_status_name_survives(
    board_schema: dict[str, Any], census_keys_by_board_key: dict[str, str], board_key: str
) -> None:
    """Exact-name membership, never substring: `Ready for Active`, `Ready for
    Planning` and `Ready to merge` all contain the retired name `Ready`, and
    the Stage field legitimately carries an option called `Active`."""
    fields = _board_fields(board_schema, census_keys_by_board_key, board_key)
    leaked = _option_names(fields["Status"]) & RETIRED_STATUS_NAMES
    assert not leaked, f"{board_key}: retired status name(s) still recorded: {sorted(leaked)}"


@pytest.mark.skipif(
    os.environ.get("BOARD_SCHEMA_LIVE") != "1",
    reason="live board comparison is opt-in; set BOARD_SCHEMA_LIVE=1 (needs a project-scoped token)",
)
def test_committed_census_matches_the_live_boards(capsys: pytest.CaptureFixture[str]) -> None:
    """The opt-in live leg.

    Calls `board_census.cmd_check()` rather than re-implementing its comparison.
    Re-implementing it would mean two copies of the same rule, and the day
    `cmd_check` gains a normalization step or a tolerated difference, this guard
    would start reporting a drift the shipped check does not. One authority.

    But `cmd_check` returns 0 for two different reasons: the census matched, or
    live access was unavailable and it printed SKIPPED. Asserting only on the
    return code would turn the second into a green test -- and pytest discards
    captured output on a pass, so the operator would see `1 passed` and nothing
    else. That is precisely the failure this module exists to prevent, reproduced
    inside the module itself. Read the output and turn a SKIPPED into a real
    pytest skip, so "could not check" never renders as "checked and clean".
    """
    sys.path.insert(0, str(REPO_ROOT / "plugins" / "mission-control" / "scripts"))
    import board_census  # noqa: PLC0415

    exit_code = board_census.cmd_check()
    printed = capsys.readouterr().out
    if "SKIPPED" in printed:
        pytest.skip(f"live board access unavailable: {printed.strip()}")

    assert exit_code == 0, (
        "board-schema.json has drifted from the live boards; "
        "re-run `python3 plugins/mission-control/scripts/board_census.py --write`"
    )


# ---------------------------------------------------------------------------
# Prose surfaces, not just the census (#1020).
#
# These files are instructions an agent executes, so a Status the boards reject
# is a runtime failure, not a typo -- and `LIVE_LEGACY_STATUS_ALIASES` carries
# no entry for the retired names, so no migration hint fires either.
#
# This guard has already been wrong once, in a way worth keeping written down.
# Its first version matched `--status "<quoted>"` and nothing else, so it missed
# six live offenders that the plugin wrote three other ways: unquoted after the
# flag, through `--field Status --option <value>`, and as a bare name in an
# English sentence. That is the exact mistake the learning committed beside it
# names -- match the NAME, not the syntax you last saw the name in -- so the
# guard now works from the retired names outward and checks every syntax.
# ---------------------------------------------------------------------------

MISSION_CONTROL = REPO_ROOT / "plugins" / "mission-control"

# Every way this plugin's prose writes a Status value.
# Matched per line.
STATUS_FLAG_PATTERN = re.compile(r"--status\s+(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z][\w-]*))")

# Matched over the WHOLE file, because this plugin really does wrap the form
# across lines with a trailing backslash:
#     --field Status \\
#     --option Implementing
# A per-line scan cannot see that, which is the blind spot a `re.DOTALL` flag
# on a per-line scan only pretended to cover.
STATUS_OPTION_PATTERN = re.compile(
    r"--field\s+Status\b(?:(?!--field)[\s\S])*?--option\s+"
    r"(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z][\w-]*))",
    re.DOTALL,
)

# Bare mentions are caught by name rather than by syntax, because an agent reads
# "move it to Ready" as an instruction just as readily as a flag. Only the
# retired names are searched this way: a positive list would fire on ordinary
# English ("the Active board"), so the check is scoped to words that used to be
# Status values and no longer are. `\b` keeps `Ready` from matching inside
# `Ready for Planning` or `Ready to merge`.
# `Active` is deliberately absent: it is a live Stage option, so a bare
# mention is usually legitimate ("the Active stage"). It is still caught as a
# Status VALUE by the flag patterns above. `Done` has no such excuse -- it is
# not a Stage, not a Status, and not a field name -- so a bare mention of it
# is always either an instruction to write a dead value or a historical note,
# and the history exemption below separates those two.
# The Mount Olympus set (#1042) joins on the same terms: none of `Assigned`,
# `In Review`, or `Needs Question` is a live Stage, Status, or field name, so a
# bare mention outside a history-marked paragraph is an instruction to write a
# value every board rejects. Multi-word names need no special handling -- the
# scan is per line and the space is literal.
BARE_RETIRED_NAME = re.compile(
    r"\b(?:Idea|Todo|Committed|Parked|Done)\b"
    r"|\bReady\b(?!\s+(?:for\s+Active|for\s+Planning|to\s+close|to\s+merge))"
    r"|\b(?:Assigned|In Review|Needs Question)\b"
)

# A bullet or numbered list item begins a new exemption unit.
LIST_ITEM_START = re.compile(r"\s*(?:[-*+]|\d+\.)\s")

# A markdown table row is its own unit for the same reason a list item is: a
# table is a blank-line-free run, so one row carrying a history marker would
# otherwise excuse every other row in the table.
TABLE_ROW_START = re.compile(r"\s*\|")

# Lines that legitimately discuss the retired vocabulary as history rather than
# instructing anyone to use it. Each is a deliberate, reviewed exemption.
HISTORY_MARKERS = (
    "Mount Olympus",
    "legacy",
    "Legacy",
    "retired",
    "historical",
    "LIVE_LEGACY_STATUS_ALIASES",
    "campps_initiative",
    "no longer",
    "superseded",
)


def _prose_surfaces() -> list[Path]:
    paths: list[Path] = []
    paths.extend(sorted((MISSION_CONTROL / "skills").rglob("*.md")))
    adapter = MISSION_CONTROL / "com.infiquetra.claude"
    for sub in ("commands", "agents"):
        directory = adapter / sub
        if directory.is_dir():
            paths.extend(sorted(directory.rglob("*.md")))
    readme = MISSION_CONTROL / "README.md"
    if readme.is_file():
        paths.append(readme)
    return paths


# CHANGELOG.md is deliberately NOT swept. It is a historical record whose job
# is to name what changed, so it must be free to say `Todo / In Progress /
# Done` when describing what a release retired. Instruction surfaces are swept;
# records of past instructions are not.


# 16 skill documents, the package README, four Claude commands, and the operator agent.
EXPECTED_PROSE_SURFACE_COUNT = 22


def test_the_prose_sweep_actually_scans_something() -> None:
    """Pin the count, not a floor.

    The census guard above pins its board count exactly, and this one used to
    settle for `>= 10` -- a weaker pin that would not notice a file-discovery
    bug halving the coverage.
    """
    surfaces = _prose_surfaces()
    assert surfaces, "no prose surface found; the guard would pass by scanning nothing"
    assert len(surfaces) == EXPECTED_PROSE_SURFACE_COUNT, (
        f"expected {EXPECTED_PROSE_SURFACE_COUNT} prose surfaces, found {len(surfaces)}: "
        f"{[str(p.relative_to(REPO_ROOT)) for p in surfaces]}. If a file was added or removed "
        "on purpose, update EXPECTED_PROSE_SURFACE_COUNT in the same change."
    )


def _status_values(text: str) -> list[tuple[int, str]]:
    """Every Status value the text writes, as (line number, value).

    The flag form is matched per line; the `--field Status … --option` form is
    matched over the whole text, because it wraps across lines here.
    """
    found: list[tuple[int, str]] = []

    for number, line in enumerate(text.splitlines(), 1):
        for groups in STATUS_FLAG_PATTERN.findall(line):
            value = next((g for g in groups if g), "")
            if value:
                found.append((number, value))

    for match in STATUS_OPTION_PATTERN.finditer(text):
        index = next((i for i, g in enumerate(match.groups(), 1) if g), 0)
        if index:
            # Derive the line from where the VALUE sits, not where the match
            # began: the match spans lines, and the offending word is what a
            # reader needs pointing at.
            found.append((text.count("\n", 0, match.start(index)) + 1, match.group(index)))

    return found


def _history_exempt_lines(text: str) -> set[int]:
    """Line numbers a history marker excuses.

    Scoped to the enclosing PARAGRAPH, not the single line. A marker such as
    "retired" often lands on the first line of a wrapped paragraph while the
    retired name lands on the second, and a line-scoped exemption silently stops
    covering the line below it -- which is a false negative in a guard, the worst
    kind. Headings extend the exemption to their whole section.

    Only a real ATX heading counts: `#` followed by a space, outside a fenced
    code block. A shell comment inside a fence starts with `#` too, and treating
    one as a heading would excuse every line until the next comment.
    """
    lines = text.splitlines()
    exempt: set[int] = set()

    # Paragraph scope: blank-line-separated runs -- but a bullet or numbered
    # list is one such run with no blank lines inside it, so scoping the whole
    # run would let one marked item excuse its siblings. Each list item is its
    # own unit; its indented continuation lines belong to it.
    def _units(block_lines: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
        units: list[list[tuple[int, str]]] = []
        fenced = False
        for number, text_line in block_lines:
            is_fence = text_line.strip().startswith(("```", "~~~"))
            starts_unit = (
                not units
                or (is_fence and not fenced)
                or (
                    not fenced
                    and (LIST_ITEM_START.match(text_line) or TABLE_ROW_START.match(text_line))
                )
            )
            if is_fence and fenced:
                units[-1].append((number, text_line))
                fenced = False
                units.append([])
                continue
            if starts_unit:
                units.append([])
            units[-1].append((number, text_line))
            if is_fence and not fenced:
                fenced = True
        return [unit for unit in units if unit]

    start = 0
    for index in range(len(lines) + 1):
        if index == len(lines) or not lines[index].strip():
            if index > start:
                block = [(n + 1, lines[n]) for n in range(start, index)]
                for unit in _units(block):
                    text_of_unit = "\n".join(line for _, line in unit)
                    if any(marker in text_of_unit for marker in HISTORY_MARKERS):
                        exempt.update(number for number, _ in unit)
            start = index + 1

    # Section scope: from a marked heading to the next heading of any level.
    in_fence = False
    heading_is_history = False
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if not in_fence and re.match(r"#{1,6}\s", stripped):
            heading_is_history = any(marker in line for marker in HISTORY_MARKERS)
        if heading_is_history:
            exempt.add(number)

    return exempt


def test_no_prose_surface_writes_a_status_the_boards_reject(stage_flow: dict[str, Any]) -> None:
    """Command examples must name a Status that exists.

    No history exemption here: a command example is an instruction whatever
    section it sits in, and a historical note has no reason to carry a runnable
    flag.
    """
    valid = set(stage_flow["statuses"])
    stages = set(stage_flow["stages"])
    offenders: list[str] = []

    for path in _prose_surfaces():
        text = path.read_text(encoding="utf-8")
        for number, value in _status_values(text):
            if value in valid:
                continue
            why = "a Stage, not a Status" if value in stages else "not in the schema"
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{number} writes {value!r} ({why})")

    assert not offenders, (
        "prose instructs an agent to write a Status the boards reject:\n" + "\n".join(offenders)
    )


def test_no_prose_surface_tells_an_agent_to_use_a_retired_status_name(
    stage_flow: dict[str, Any],
) -> None:
    """Bare names too, not only flag values.

    A sentence like "move it to Ready if context complete" is as much an
    instruction as a command line, and the first version of this guard could not
    see it. Paragraphs and sections that discuss the retired vocabulary as
    history are exempt.
    """
    valid = set(stage_flow["statuses"])
    offenders: list[str] = []

    for path in _prose_surfaces():
        text = path.read_text(encoding="utf-8")
        exempt = _history_exempt_lines(text)
        for number, line in enumerate(text.splitlines(), 1):
            if number in exempt:
                continue
            for match in BARE_RETIRED_NAME.finditer(line):
                name = match.group(0)
                if name in valid:
                    continue
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{number} names {name!r}: {line.strip()[:90]}"
                )

    assert not offenders, (
        "prose names a retired Status as though it were still usable:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# CLI help strings, not just prose (#1042).
#
# `board move --status`'s help names example statuses, and argparse prints it on
# a parse error -- so a stale example hands an agent whose Status write was just
# rejected three more rejected values. The prose guard above cannot see it: it
# sweeps `*.md` instruction surfaces, not Python sources. This case pins the
# examples to the committed census instead. Operations is the reference board;
# every active board carries the same stage_flow Status set, so an example the
# operations census records is valid on all three.
# ---------------------------------------------------------------------------

SDLC_MANAGER_PATH = MISSION_CONTROL / "scripts" / "sdlc_manager.py"

TARGET_STATUS_HELP_PATTERN = re.compile(r'help="Target status \(e\.g\. ([^"]+)\)"')
HELP_EXAMPLE_PATTERN = re.compile(r"'([^']+)'")


def test_board_move_help_examples_are_statuses_the_census_records(
    board_schema: dict[str, Any],
) -> None:
    """Every example in the `board move --status` help must be a Status option
    the committed census records (#1042)."""
    text = SDLC_MANAGER_PATH.read_text(encoding="utf-8")
    match = TARGET_STATUS_HELP_PATTERN.search(text)
    assert match, (
        "board move --status help string not found in sdlc_manager.py; if the help "
        "text moved, move this guard with it"
    )
    examples = HELP_EXAMPLE_PATTERN.findall(match.group(1))
    assert examples, "no quoted examples found in the --status help string"
    valid = _option_names(board_schema["boards"]["operations"]["fields"]["Status"])
    unknown = [example for example in examples if example not in valid]
    assert not unknown, (
        "board move --status help names example statuses no live board accepts: "
        + ", ".join(sorted(unknown))
    )


def test_the_help_example_extraction_sees_multi_word_names() -> None:
    """Pins the extraction against the shape it must handle: examples are
    single-quoted and may contain a space (`Code review`)."""
    sample = '''help="Target status (e.g. 'Implementing', 'Code review')"'''
    match = TARGET_STATUS_HELP_PATTERN.search(sample)
    assert match, "the help pattern must match the --status help shape"
    assert HELP_EXAMPLE_PATTERN.findall(match.group(1)) == ["Implementing", "Code review"]


# ---------------------------------------------------------------------------
# The guard's own logic, driven directly.
#
# Everything above exercises these helpers only against this repository's real
# prose, which is clean -- so every helper could regress and the suite would
# stay green. That is the failure this module's own header paragraph names, so
# it cannot be the one thing the module leaves unproven. These cases are the
# evasions an earlier revision actually had, pinned so a later widening of the
# patterns has to break a test to happen.
# ---------------------------------------------------------------------------


class TestHistoryExemptionScope:
    def test_a_marked_bullet_does_not_excuse_its_siblings(self) -> None:
        """A list has no blank lines inside it, so a paragraph-scoped exemption
        would let one historical bullet cover the instruction below it."""
        text = (
            "- The old Olympus board used a legacy ladder.\n"
            "- Move the card to Done when finished.\n"
        )
        assert _history_exempt_lines(text) == {1}

    def test_an_unmarked_bullet_alone_is_not_exempt(self) -> None:
        assert _history_exempt_lines("- Move the card to Done when finished.\n") == set()

    def test_a_marker_covers_its_own_wrapped_paragraph(self) -> None:
        """The case a line-scoped exemption got wrong: the marker lands on the
        first line of a wrapped paragraph and the retired name on the second."""
        text = "The retired ladder is preserved for history:\nIdea, Ready and Done are gone.\n"
        assert _history_exempt_lines(text) == {1, 2}

    def test_a_marked_heading_covers_its_section_until_the_next_heading(self) -> None:
        text = (
            "## Legacy board\n"
            "The ladder ended at Done.\n"
            "\n"
            "## Current board\n"
            "Move the card to Done when finished.\n"
        )
        exempt = _history_exempt_lines(text)
        assert 2 in exempt, "a line under a history heading should be exempt"
        assert 5 not in exempt, "the next heading must end the exemption"

    def test_a_shell_comment_in_a_fence_is_not_a_heading(self) -> None:
        """`# ...` inside a fenced block is a shell comment. Treating one as a
        heading would excuse every line after it."""
        text = (
            "```bash\n"
            "# limits are retired; the schema defines none\n"
            "board wip --project operations\n"
            "```\n"
            "Move the card to Done when finished.\n"
        )
        assert 5 not in _history_exempt_lines(text)


class TestStatusValueExtraction:
    def test_the_flag_form_in_each_quoting_style(self) -> None:
        assert _status_values('--status "Ready for Planning"\n') == [(1, "Ready for Planning")]
        assert _status_values("--status 'Implementing'\n") == [(1, "Implementing")]
        assert _status_values("--status Implementing\n") == [(1, "Implementing")]

    def test_the_field_option_form_wrapped_across_lines(self) -> None:
        """The form this plugin actually writes, and the one a per-line scan
        could never see however many DOTALL flags it carried."""
        assert _status_values("  --field Status \\\n  --option Done\n") == [(2, "Done")]

    def test_another_flag_between_field_and_option_does_not_hide_the_value(self) -> None:
        assert _status_values("  --field Status --project 3 \\\n  --option Done\n") == [(2, "Done")]

    def test_a_different_field_is_not_read_as_a_status(self) -> None:
        """`--field Objective --option Done` sets something else entirely; the
        match must not run past one `--field` into the next."""
        assert _status_values("  --field Objective \\\n  --option defects\n") == []
        assert _status_values("  --field Status --option Capturing\n") == [(1, "Capturing")]

    def test_the_line_number_follows_the_value_not_the_flag(self) -> None:
        text = "intro\n\n  --field Status \\\n  --option Capturing\n"
        assert _status_values(text) == [(4, "Capturing")]


class TestBareRetiredNamePattern:
    def test_live_statuses_beginning_with_ready_are_not_flagged(self) -> None:
        for live in ("Ready for Active", "Ready for Planning", "Ready to close", "Ready to merge"):
            assert not BARE_RETIRED_NAME.search(live), f"{live} is a live Status"

    def test_the_bare_retired_names_are_flagged(self) -> None:
        for retired in (
            "Idea",
            "Todo",
            "Committed",
            "Parked",
            "Done",
            "Ready",
            "Assigned",
            "In Review",
            "Needs Question",
        ):
            assert BARE_RETIRED_NAME.search(f"move it to {retired} when done"), retired

    def test_active_is_not_matched_bare(self) -> None:
        """Deliberate: `Active` is a live Stage, so a bare mention is usually
        legitimate. It is still caught as a Status VALUE by the flag patterns."""
        assert not BARE_RETIRED_NAME.search("cards in the Active stage")
        assert _status_values("--status Active\n") == [(1, "Active")]


def test_a_marked_table_row_does_not_excuse_the_other_rows() -> None:
    """Third instance of one mechanism: a table is a blank-line-free run, so
    without its own unit rule a single historical row covers the whole table."""
    text = (
        "| Board | Note |\n"
        "|---|---|\n"
        "| Olympus | the legacy ladder |\n"
        "| Operations | move the card to Done |\n"
    )
    exempt = _history_exempt_lines(text)
    assert 3 in exempt, "the row carrying the marker should be exempt"
    assert 4 not in exempt, "a sibling row must not inherit the exemption"


def test_the_match_stops_at_the_next_field_flag() -> None:
    """Pins the `(?!--field)` lookahead, which was previously unfalsifiable.

    Without it the scan runs from `--field Status` past a second `--field` and
    reads the WRONG field's option as a Status, which would be a false positive.
    """
    text = "--field Status --project 3\n--field Objective --option defects-claude-plugins\n"
    assert _status_values(text) == []
