"""The authoring contract for the two ordering edges, ``after`` and ``serialize``.

``serialize`` was added to the runtime alongside ``after`` -- both gate launch identically, and
what differs is what they claim -- but for a whole run nothing in the supported workflow could
emit it: neither the command nor the skill mentioned it, and a planner who needed to stagger two
units off one file fell back to ``after``, asserting a dependency that did not exist. These tests
pin the producer path: both surfaces teach both edges and when to reach for each, the Phase 4 JSON
contract shows a unit actually authoring ``serialize``, and neither surface ever again calls
``after`` the only ordering.

They also pin the `/work` row naming rule (issue #135): both surfaces state that an expansion
creates one `/work` row per plan unit, named by its U-ID, and no example shows any other name.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "orchestrate"
COMMAND_PATH = "com.infiquetra.claude/commands/orchestrate.md"
SKILL_PATH = "skills/orchestrate/SKILL.md"
SURFACES = (COMMAND_PATH, SKILL_PATH)

# The rule for choosing between the edges, in phrasing both surfaces must carry so the skill and
# the command cannot drift apart.
ORDERING_RULE = (
    "`serialize`",
    "I build on what you produce",
    "I must not run beside you",
    "edit the same file",
    "wait for the other to land",
    "a dependency that does not exist",
)


# The single launch seam and background no-focus invariant contract across both surfaces.
SINGLE_LAUNCH_SEAM_RULE = (
    "Never create worktrees manually or invoke `agents` directly",
    "`--no-focus --current --herdr --herdr-control-only`",
    "controlled post-launch step",
    "unrecorded drift",
    "`adopt --yes`",
)


def _read(relative_path: str) -> str:
    return (PLUGIN_ROOT / relative_path).read_text(encoding="utf-8")


def _collapse(text: str) -> str:
    """Prose with its line wraps taken out, so a rewrap cannot break a phrase match."""
    return " ".join(text.split())


def _assert_all_present(text: str, required: tuple[str, ...], where: str) -> None:
    collapsed = _collapse(text)
    missing = [needle for needle in required if needle not in collapsed]
    assert missing == [], f"{where} no longer documents: {', '.join(missing)}"


def _run_plan_examples(text: str) -> list[dict[str, Any]]:
    """The fenced JSON blocks that carry a ``units`` list -- the Phase 4 contract examples.

    JSON examples without a ``units`` list are not run plans and are deliberately not parsed here.
    """
    blocks = re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
    return [json.loads(block) for block in blocks if '"units"' in block]


def test_command_teaches_both_ordering_edges() -> None:
    _assert_all_present(_read(COMMAND_PATH), ORDERING_RULE, COMMAND_PATH)


def test_skill_teaches_both_ordering_edges() -> None:
    _assert_all_present(_read(SKILL_PATH), ORDERING_RULE, SKILL_PATH)


def test_command_teaches_single_launch_seam_and_no_focus_invariant() -> None:
    _assert_all_present(_read(COMMAND_PATH), SINGLE_LAUNCH_SEAM_RULE, COMMAND_PATH)


def test_skill_teaches_single_launch_seam_and_no_focus_invariant() -> None:
    _assert_all_present(_read(SKILL_PATH), SINGLE_LAUNCH_SEAM_RULE, SKILL_PATH)


def test_json_contract_shows_a_unit_authoring_serialize() -> None:
    plans = _run_plan_examples(_read(COMMAND_PATH))
    assert plans, "the command file lost its run-plan JSON example"

    units = [unit for plan in plans for unit in plan["units"]]
    names = {unit["name"] for unit in units}
    serialized = [unit for unit in units if unit.get("serialize")]
    assert serialized, "no example unit authors `serialize`"

    for unit in serialized:
        unknown = [dep for dep in unit["serialize"] if dep not in names]
        assert unknown == [], f"{unit['name']!r} serializes behind {unknown!r}, absent from example"

    # The example must show the edge on its own -- a unit that waits without needing output -- not
    # serialize stacked on top of the same `after` dependency.
    pure = [unit for unit in serialized if not set(unit["serialize"]) & set(unit.get("after", []))]
    assert pure, "the example only shows `serialize` stacked on the same `after` dependency"


def test_no_surface_claims_after_is_the_only_ordering() -> None:
    for relative_path in SURFACES:
        collapsed = _collapse(_read(relative_path)).lower()
        assert "only ordering" not in collapsed, (
            f"{relative_path} still claims `after` is the only ordering"
        )


def test_no_surface_authorizes_direct_wrapper_or_manual_worktree_bypass() -> None:
    for relative_path in SURFACES:
        collapsed = _collapse(_read(relative_path))
        assert "not a license to bypass `expand` or `go`" in collapsed or (
            "does not authorize bypassing `expand` or `go`" in collapsed
        ), f"{relative_path} does not clearly prohibit bypassing expand or go"


# The /work row naming rule (issue #135). Saga's functional-check write finds each plan unit's row
# by its name, so an expansion that names a /work row anything but a plan U-ID leaves that unit
# pending and /work stops on exit 5 before its first build-loop iteration.
WORK_ROW_NAMING_RULE = (
    "exactly one `/work` row per plan unit, named by that unit's U-ID",
    "A lane that builds several plan units carries several rows, one per U-ID",
    "`plugins/saga/scripts/functional_checks.py write`",
    "exits 5",
)

PLAN_UID = re.compile(r"U[1-9][0-9]*")
# A unit object shown anywhere in a surface: one flat JSON object carrying a name and a task.
UNIT_OBJECT = re.compile(r"\{[^{}]*\"name\"\s*:[^{}]*\"task\"\s*:[^{}]*\}")
WORK_TASK = re.compile(r"^/(?:saga:)?work\b")


def _work_row_names(text: str) -> list[str]:
    """Every unit name the surface shows on a row whose task invokes `/work`.

    It reads each flat unit object in the text rather than only parseable JSON blocks, so a row
    shown in a non-JSON fence or with an ellipsis still counts.
    """
    names: list[str] = []
    for match in UNIT_OBJECT.finditer(text):
        body = match.group(0)
        name = re.search(r"\"name\"\s*:\s*\"([^\"]*)\"", body)
        task = re.search(r"\"task\"\s*:\s*\"([^\"]*)\"", body)
        if name and task and WORK_TASK.match(task.group(1)):
            names.append(name.group(1))
    return names


def test_command_states_the_work_row_naming_rule() -> None:
    _assert_all_present(_read(COMMAND_PATH), WORK_ROW_NAMING_RULE, COMMAND_PATH)


def test_skill_states_the_work_row_naming_rule() -> None:
    _assert_all_present(_read(SKILL_PATH), WORK_ROW_NAMING_RULE, SKILL_PATH)


def test_command_shows_the_rule_in_phase_5() -> None:
    text = _read(COMMAND_PATH)
    phase_5 = text.split("## Phase 5", 1)[1].split("\n## ", 1)[0]
    _assert_all_present(phase_5, WORK_ROW_NAMING_RULE[:2], f"{COMMAND_PATH} Phase 5")


def test_every_work_row_example_is_named_by_a_plan_uid() -> None:
    shown: list[str] = []
    for relative_path in SURFACES:
        names = _work_row_names(_read(relative_path))
        wrong = [name for name in names if not PLAN_UID.fullmatch(name)]
        assert wrong == [], f"{relative_path} shows /work rows not named by a plan U-ID: {wrong!r}"
        shown.extend(names)
    # Guard the guard: the command's expansion example must still show /work rows to check.
    assert shown, "no surface shows a /work row any more, so the naming rule is untested"


def test_work_row_scanner_catches_a_lane_name() -> None:
    sample = '{"name": "build-api", "vendor": "claude", "task": "/saga:work docs/plans/x.md"}'
    assert _work_row_names(sample) == ["build-api"]
    assert not PLAN_UID.fullmatch("build-api")
