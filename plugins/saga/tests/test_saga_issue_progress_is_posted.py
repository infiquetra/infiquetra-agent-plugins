"""The lifecycle's issue comment is rendered, and it has to actually be posted.

For a long time `work/SKILL.md` §4.3 said only "render and hand the comment to mission-control",
which is prose with no command in it — so nothing ran. Two complete lifecycles merged and closed
with **zero comments** on their issues, and GitHub's own auto-close from the pull request stood in
for the update the whole time.

Everything else had been built: the op is in the certificate allowlist, `board_progression` stamps an
idempotency marker into the body, and mission-control's `issue comment` verb performs the write. The
only missing piece was the instruction to run it, so what is pinned here is that the instruction
exists and still names something real.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"


def _load_board_progression() -> ModuleType:
    """Load the module this guard resolves boundaries through, by path like its siblings."""
    import importlib.util

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "board_progression", SCRIPTS / "board_progression.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["board_progression"] = module
    spec.loader.exec_module(module)
    return module


BP = _load_board_progression()
SKILL = ROOT / "plugins" / "saga" / "skills" / "work" / "SKILL.md"
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"

OP = "issue-progress-comment"


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL.read_text()


@pytest.fixture(scope="module")
def certificate() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_reversibility_certificate", SCRIPTS / "reversibility_certificate.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


def test_the_phase_comment_step_names_a_command(skill_text: str) -> None:
    """Rendering is not posting. A sentence about handing it over is not a step."""
    assert OP in skill_text, "§4.3 must name the op that posts the comment"
    assert "reconcile_controller.py reconcile" in skill_text


def test_it_is_routed_through_the_ledger_rather_than_the_bare_verb(skill_text: str) -> None:
    """`issue comment` is a plain POST — its docstring puts idempotency on the caller, and
    orchestrate retries units by design."""
    section = skill_text.split("### 4.3")[1].split("### 4.4")[0]
    assert "reconcile_controller.py" in section
    assert "idempotency" in section


PLAN_SKILL = ROOT / "plugins" / "saga" / "skills" / "plan" / "SKILL.md"


@pytest.fixture(scope="module")
def plan_text() -> str:
    return PLAN_SKILL.read_text()


class TestTheCardMovesAtPhaseBoundaries:
    """The phase-boundary card moves are SUBMITTED by /plan and /work and EXECUTED by Mission
    Control (operator ruling, 2026-08-30; issue #927).

    W7 read SDLC R30 as removing Saga's ability to submit a lifecycle-field move at all, and this
    class pinned that reading: "Saga does not write the board", no ``--target-state`` argv, no
    ``set-field-status``. The operator superseded it — **deciding and submitting is not writing** —
    and the earlier removal turned out to have left the moves with no caller, so cards stopped
    moving entirely. What is pinned now is the amended boundary: each site states that Mission
    Control executes, each site carries a runnable submission, and no state argv names a value the
    board cannot resolve.
    """

    def test_planning_states_mission_control_executes_the_move(self, plan_text: str) -> None:
        assert "Mission Control remains the only executor" in plan_text
        assert "--op set-field-status" in plan_text, "/plan must submit its lifecycle moves"

    def test_building_states_mission_control_executes_the_move(self, skill_text: str) -> None:
        assert "Mission Control remains the only executor" in skill_text
        assert "--op set-field-status" in skill_text, "/work must submit its lifecycle moves"

    def test_done_is_owned_by_mission_control_and_the_close_survives(self, skill_text: str) -> None:
        """Phase 4.4 submits the delivered-terminal move; the post-merge sub-issue close (an
        issue-state write, not a field write) still fires alongside it."""
        assert "--op sub-issue-close" in skill_text
        assert "Mission Control" in skill_text.split("### 4.4")[1].split("## Phase 5")[0]

    def test_every_state_argv_names_a_live_board_option(
        self, skill_text: str, plan_text: str
    ) -> None:
        """A typo'd state is a silent no-op, which is why W7 pinned the absence of state argv.

        The argv is back, so the protection moves with it: every ``--target-state`` in either skill
        must name an option the live board actually carries, and every submission must pair it with
        the Stage half. ``Ready for Active`` is a legal Status on its own, so a Status-only
        submission would look like success while Stage stayed where it was.
        """
        schema = json.loads(
            (ROOT / "plugins" / "mission-control" / "config" / "sdlc-schema.json").read_text(
                encoding="utf-8"
            )
        )
        stage_statuses = schema["workflows"]["stage_flow"]["stage_statuses"]
        live_statuses = {status for options in stage_statuses.values() for status in options}
        live_pairs = {
            (stage, status) for stage, options in stage_statuses.items() for status in options
        }

        combined = skill_text + plan_text
        states = re.findall(r'--target-state\s+"([^"]+)"', combined)
        # The boundary spelling names no state at all (issue 1028): the allowed-submission table
        # chooses the pair, which is why a boundary cannot carry a typo'd one. Resolve each
        # boundary the skills name through that same table so this guard counts every move.
        # Per fenced block, because a `--dry-run` block prints a move and submits nothing; counting
        # the whole text would double-count a boundary the skills also demonstrate as a dry run.
        boundaries = [
            name
            for block in combined.split("```")
            if "--dry-run" not in block
            for name in re.findall(r"--boundary\s+([a-z-]+)", block)
            if BP.resolve_boundary(name)["submits"]
        ]
        resolved = [BP.resolve_boundary(name)["status"] for name in boundaries]
        every_state = states + resolved
        assert len(every_state) == 5, (
            f"five permitted boundaries, found {len(every_state)}: {every_state}"
        )
        for state in every_state:
            assert state in live_statuses, f"the submitted state {state!r} is not a live option"

        # The typed pairs, plus the pairs the boundary spelling resolves to. A boundary carries
        # both halves by construction — `boundary_payload` builds the pair — which is the same
        # property this guard was pinning about the typed form, reached a safer way.
        pairs = re.findall(
            r'\[\s*"Stage",\s*"([^"]+)"\s*\],\s*\[\s*"Status",\s*"([^"]+)"\s*\]', combined
        )
        for name in boundaries:
            move = BP.resolve_boundary(name)
            assignments = dict(BP.boundary_payload(move)["assignments"])
            assert set(assignments) == {"Stage", "Status"}, (
                f"the {name} boundary resolves to a submission that is not a Stage/Status pair"
            )
            pairs.append((assignments["Stage"], assignments["Status"]))
        assert len(pairs) == 5, f"every submission must carry both halves, found {len(pairs)}"
        for pair in pairs:
            assert pair in live_pairs, f"{pair} is not an option combination the board carries"

    def test_a_plan_with_no_issue_does_not_try_to_move_a_card(self, plan_text: str) -> None:
        assert "no issue" in plan_text
