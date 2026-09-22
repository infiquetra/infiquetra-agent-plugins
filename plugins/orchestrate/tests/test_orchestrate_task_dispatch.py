"""What a dispatched saga unit is actually told, at the moment orchestrate sends it.

The task text is the only lever this plugin has over a session it does not share a process with, so
every quiet failure it has had lands here: a command in the wrong vendor's spelling arriving as
prose, a stage stopping to ask a question in a tab nobody is watching, a builder reviewing its own
work. These exercise ``normalize_task`` directly -- it is pure, so the real function is under test
rather than a stand-in for it.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# --- issue #1025: every stateful subcommand takes --issue and --store-root -----------------------

TEST_ISSUE = 1


_STORE: Path | None = None


@pytest.fixture(autouse=True)
def _pin_the_record_store(tmp_path: Path) -> Iterator[None]:
    """Pin this test's record store to its own ``tmp_path``.

    Never the resolved store -- that is the developer's own ``.claude/saga/runs`` -- and never
    derived from the working directory either: a helper called before a test changes directory
    would then write one store and read another.
    """
    global _STORE
    _STORE = tmp_path / "orch-test-store"
    _STORE.mkdir(parents=True, exist_ok=True)
    yield
    _STORE = None


def test_store() -> Path:
    """This test's record store."""
    assert _STORE is not None, "the record store is pinned by an autouse fixture"
    return _STORE


def NS(**fields: object) -> argparse.Namespace:
    """A command Namespace carrying this test's issue and store."""
    # `merge` and `clean` carry optional flags the parser defaults; a Namespace built by
    # hand has to default them too, or the command reads an attribute that is not there.
    defaults = {"remote": "origin", "compare": "main"}
    return argparse.Namespace(
        issue=TEST_ISSUE,
        store_root=str(test_store()),
        **{**defaults, **fields},
    )


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "orchestrate"
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)


@pytest.fixture(scope="module")
def orchestrate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_orchestrate_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _unit(orchestrate: ModuleType, name: str, task: str) -> Any:
    return orchestrate.Unit(name=name, vendor="claude", task=task)


def _run(orchestrate: ModuleType, *tasks: str) -> Any:
    return orchestrate.Run(
        run_id="r",
        source="issue 1",
        base="0" * 40,
        units=[_unit(orchestrate, f"u{i}", t) for i, t in enumerate(tasks)],
    )


class TestVendorSpelling:
    def test_codex_gets_a_dollar_prefix(self, orchestrate: ModuleType) -> None:
        sent = orchestrate.normalize_task("codex", "/saga:plan docs/plans/x.md")
        assert sent.startswith("$saga:plan docs/plans/x.md")

    def test_grok_gets_a_bare_slash(self, orchestrate: ModuleType) -> None:
        sent = orchestrate.normalize_task("grok", "/saga:doc-review docs/plans/x.md")
        assert sent.startswith("/doc-review docs/plans/x.md")

    def test_prose_is_left_alone(self, orchestrate: ModuleType) -> None:
        task = "read the plan and summarise it"
        assert orchestrate.normalize_task("codex", task) == task


class TestBackendIsNotAsked:
    """Both /plan and /work offer a backend, and an offer in a background tab waits forever."""

    def test_plan_is_told_to_record_it(self, orchestrate: ModuleType) -> None:
        sent = orchestrate.normalize_task("claude", "/saga:plan docs/plans/x.md")
        assert "already decided: inline" in sent
        assert "frontmatter" in sent

    def test_work_is_told_it_is_already_in_the_plan(self, orchestrate: ModuleType) -> None:
        sent = orchestrate.normalize_task("claude", "/saga:work docs/plans/x.md")
        assert "already decided: inline" in sent

    def test_a_review_stage_is_told_nothing_about_backends(self, orchestrate: ModuleType) -> None:
        sent = orchestrate.normalize_task("claude", "/saga:doc-review docs/plans/x.md")
        assert "already decided" not in sent


class TestTheVendorMappingSaysWhatTheVendorDoes:
    """Every entry here was wrong on a live machine until it was checked against the tool itself.

    Deliberately asserted against the tables rather than the filesystem: the two escapes this plugin
    has had were both a green local run on a machine that happened to have the thing installed.
    """

    def test_asking_muse_for_the_constrained_mode_does_not_get_bypass(
        self, orchestrate: ModuleType
    ) -> None:
        """`--yolo` disables approval *and* the sandbox, so it was never the constrained mode."""
        muse = orchestrate.VENDOR_PERMISSION["muse"]
        assert muse["auto"] != muse["bypass"]
        assert "--yolo" not in muse["auto"]
        assert "--yolo" in muse["bypass"]

    def test_qwen_can_actually_escalate(self, orchestrate: ModuleType) -> None:
        """`--yolo` is absent from `qwen --help` and works; qwen rejects unknown flags loudly."""
        assert orchestrate.VENDOR_PERMISSION["qwen"]["bypass"] == ["--yolo"]

    def test_qwen_is_never_given_safe_mode(self, orchestrate: ModuleType) -> None:
        """It reads like a permission flag and disables the customizations saga needs loaded."""
        for mode in orchestrate.VENDOR_PERMISSION["qwen"].values():
            assert "--safe-mode" not in mode

    def test_every_vendor_with_a_permission_entry_has_both_modes(
        self, orchestrate: ModuleType
    ) -> None:
        for vendor, modes in orchestrate.VENDOR_PERMISSION.items():
            assert set(modes) == {"auto", "bypass"}, vendor

    def test_agy_can_be_given_saga_work(self, orchestrate: ModuleType) -> None:
        """Its plugin is a symlink into the operator's own checkout, so a directory search misses it."""
        assert "agy" in orchestrate.SAGA_INSTALL
        assert orchestrate.saga_command("agy", "plan") == "/saga:plan"

    def test_every_vendor_that_can_run_saga_knows_how_to_name_it(
        self, orchestrate: ModuleType
    ) -> None:
        """An install with no syntax entry sends a command the vendor reads as prose."""
        for vendor in orchestrate.SAGA_INSTALL:
            assert vendor in orchestrate.SAGA_SYNTAX, vendor


class TestALongTaskSurvivesBeingTypedIntoAPane:
    """A task past a pane's typing limit arrives as an attachment, not an instruction.

    Measured against qwen through `herdr pane run`: 859 characters arrive as text, 1660 arrive as
    `[Pasted Content N chars]` and the agent answers "I'm not sure what you'd like me to do with
    it." The unit then sits idle, `settle` marks it done, and only `land` notices it committed
    nothing — a phase later.
    """

    def test_a_short_task_is_typed_verbatim(
        self, orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        unit = orchestrate.Unit(name="u", vendor="qwen", task="x")
        assert orchestrate.pane_text(unit, "/plan do the thing") == "/plan do the thing"

    def test_a_long_task_is_replaced_by_something_a_pane_will_carry(
        self, orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        unit = orchestrate.Unit(name="u", vendor="qwen", task="x")
        long_task = "/plan " + ("word " * 400)
        typed = orchestrate.pane_text(unit, long_task)
        assert len(typed) <= orchestrate.PANE_TYPING_LIMIT

    def test_the_whole_task_is_in_the_file_the_line_points_at(
        self, orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        unit = orchestrate.Unit(name="u", vendor="qwen", task="x")
        long_task = "/plan " + ("word " * 400)
        typed = orchestrate.pane_text(unit, long_task)
        written = [w for w in typed.split() if w.endswith(".md")]
        assert written, typed
        assert Path(written[0]).read_text().strip() == long_task.strip()

    def test_the_saga_command_stays_in_the_typed_part(
        self, orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inside a file it is prose; typed, it is what makes the vendor load the skill."""
        monkeypatch.chdir(tmp_path)
        unit = orchestrate.Unit(name="u", vendor="qwen", task="x")
        typed = orchestrate.pane_text(unit, "/work " + ("word " * 400))
        assert typed.startswith("/work ")

    def test_the_handover_is_recorded_on_the_unit(
        self, orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        unit = orchestrate.Unit(name="u", vendor="qwen", task="x")
        orchestrate.pane_text(unit, "/plan " + ("word " * 400))
        assert "too long to type" in unit.note


class TestAUnitNeverBlocksOnAQuestion:
    """Saga names four known-set choices; pre-answering one left the other three to hang a run.

    A `/plan` unit stopped on the destination question minutes into a live run, in a background tab,
    with the rest of the run queued behind it — the same shape the backend note had already fixed
    once.
    """

    def test_every_saga_capability_is_told(self, orchestrate: ModuleType) -> None:
        for cap in ("plan", "work", "doc-review", "code-review", "qa"):
            sent = orchestrate.normalize_task("claude", f"/saga:{cap} x")
            assert "unattended" in sent, cap

    def test_it_names_the_choices_saga_asks_from_a_known_set(self, orchestrate: ModuleType) -> None:
        sent = orchestrate.normalize_task("claude", "/saga:plan docs/plans/x.md")
        for choice in ("destination", "execution backend", "scope class", "resume-vs-mint"):
            assert choice in sent, choice

    def test_a_real_question_is_written_down_rather_than_guessed(
        self, orchestrate: ModuleType
    ) -> None:
        """Silently answering a question about the work is worse than stopping on it."""
        sent = orchestrate.normalize_task("claude", "/saga:work docs/plans/x.md")
        assert "do not guess" in sent
        assert "write the question into your output and stop" in sent

    def test_prose_gets_no_note(self, orchestrate: ModuleType) -> None:
        """Only a recognised saga command is rewritten; a plain prompt is left exactly alone."""
        task = "read the plan and summarise it"
        assert orchestrate.normalize_task("claude", task) == task


class TestTheBuilderDoesNotReviewItself:
    """saga's /work calls /code-review as its own pre-PR gate, which under orchestration is a
    self-review -- and its §5.3 block on P0/P1 exits only through an operator override, i.e. a
    question in a background tab."""

    def test_suppressed_when_the_run_reviews_separately(self, orchestrate: ModuleType) -> None:
        sent = orchestrate.normalize_task(
            "claude", "/saga:work docs/plans/x.md", review_elsewhere=True
        )
        assert "Skip the Phase 5 code-review gate" in sent

    def test_left_alone_when_there_is_no_review_phase(self, orchestrate: ModuleType) -> None:
        """Without a review phase the in-loop gate is the only review there is."""
        sent = orchestrate.normalize_task("claude", "/saga:work docs/plans/x.md")
        assert "Skip the Phase 5 code-review gate" not in sent

    def test_the_reviewer_is_never_told_to_skip_reviewing(self, orchestrate: ModuleType) -> None:
        sent = orchestrate.normalize_task(
            "grok", "/saga:code-review the build", review_elsewhere=True
        )
        assert "Skip the Phase 5 code-review gate" not in sent


class TestRunSeesItsOwnReviewPhase:
    def test_true_when_a_unit_reviews_code(self, orchestrate: ModuleType) -> None:
        run = _run(orchestrate, "/saga:work docs/plans/x.md", "/saga:code-review the build")
        assert run.reviews_separately() is True

    def test_true_in_another_vendors_spelling(self, orchestrate: ModuleType) -> None:
        run = _run(orchestrate, "$saga:code-review the build")
        assert run.reviews_separately() is True

    def test_false_when_only_the_document_is_reviewed(self, orchestrate: ModuleType) -> None:
        run = _run(orchestrate, "/saga:work docs/plans/x.md", "/saga:doc-review docs/plans/x.md")
        assert run.reviews_separately() is False


class TestASessionIsReadyBeforeItIsSent:
    """The wrapper returns when the tab exists, which is earlier than the agent can read anything.

    Sending into that gap does not fail — `herdr agent prompt` reports success, the agent finishes
    booting, and the prompt is gone. Three times across two vendors on one live run.
    """

    def test_it_waits_for_the_agent_to_say_it_is_ready(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        unit = orchestrate.Unit(name="u", vendor="agy", task="x", pane_id="w1:p1")
        answers = [
            [{"pane_id": "w1:p1", "interactive_ready": None}],
            [{"pane_id": "w1:p1", "interactive_ready": None}],
            [{"pane_id": "w1:p1", "interactive_ready": True}],
        ]
        monkeypatch.setattr(orchestrate, "live_agents", lambda: answers.pop(0) if answers else [])
        monkeypatch.setattr(orchestrate.time, "sleep", lambda _s: None)

        assert orchestrate.await_ready(unit, seconds=30) is True
        assert answers == [], "should have polled until the agent said it was ready"

    def test_it_gives_up_for_an_agent_that_never_reports_readiness(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """qwen never reports it, which is why `say` has a pane fallback — do not hang on it."""
        unit = orchestrate.Unit(name="u", vendor="qwen", task="x", pane_id="w1:p1")
        monkeypatch.setattr(
            orchestrate, "live_agents", lambda: [{"pane_id": "w1:p1", "interactive_ready": None}]
        )
        monkeypatch.setattr(orchestrate.time, "sleep", lambda _s: None)

        assert orchestrate.await_ready(unit, seconds=2) is False

    def test_a_session_that_started_working_counts_as_delivered(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        unit = orchestrate.Unit(name="u", vendor="agy", task="x", pane_id="w1:p1")
        monkeypatch.setattr(
            orchestrate, "live_agents", lambda: [{"pane_id": "w1:p1", "agent_status": "working"}]
        )
        monkeypatch.setattr(orchestrate.time, "sleep", lambda _s: None)

        assert orchestrate.took_the_task(unit, seconds=2) is True

    def test_a_session_still_idle_after_being_sent_is_not_delivered(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The observed failure: idle right after launch, having consumed nothing."""
        unit = orchestrate.Unit(name="u", vendor="agy", task="x", pane_id="w1:p1")
        monkeypatch.setattr(
            orchestrate, "live_agents", lambda: [{"pane_id": "w1:p1", "agent_status": "idle"}]
        )
        monkeypatch.setattr(orchestrate.time, "sleep", lambda _s: None)

        assert orchestrate.took_the_task(unit, seconds=2) is False

    def test_an_unknown_pane_is_not_delivered(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        unit = orchestrate.Unit(name="u", vendor="agy", task="x", pane_id="w1:p1")
        monkeypatch.setattr(orchestrate, "live_agents", lambda: [])
        monkeypatch.setattr(orchestrate.time, "sleep", lambda _s: None)

        assert orchestrate.took_the_task(unit, seconds=2) is False


class TestTheRosterBriefsEveryVendor:
    """The interview should read how a vendor behaves rather than recall it.

    Every note here was learned by a run going wrong and re-learned at least once, because it lived
    nowhere. Rendering is exercised with the machine's answers stubbed out — the roster shells out to
    the wrapper, and a test that depends on which agents happen to be installed is the escape this
    session has already had twice.
    """

    def test_every_note_belongs_to_a_vendor_this_plugin_drives(
        self, orchestrate: ModuleType
    ) -> None:
        for vendor in orchestrate.VENDOR_NOTES:
            assert vendor in orchestrate.VENDOR_FLAGS, vendor

    def test_the_brief_states_both_permission_modes(
        self,
        orchestrate: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(orchestrate, "roster", lambda: [("muse", "model,effort")])
        monkeypatch.setattr(orchestrate, "launchable", lambda: ["muse"])
        monkeypatch.setattr(orchestrate, "saga_capabilities", lambda _v: [])
        orchestrate.cmd_roster(NS(models=False, probe=False, limit=12))

        out = capsys.readouterr().out
        assert "--approval-mode never" in out
        assert "--yolo" in out

    def test_a_vendor_with_no_escalation_says_so(
        self,
        orchestrate: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An empty list rendered as blank reads as 'nothing needed' rather than 'not possible'."""
        monkeypatch.setattr(orchestrate, "roster", lambda: [("agy", "model,effort")])
        monkeypatch.setattr(orchestrate, "launchable", lambda: ["agy"])
        monkeypatch.setattr(orchestrate, "saga_capabilities", lambda _v: [])
        orchestrate.cmd_roster(NS(models=False, probe=False, limit=12))

        assert "(vendor default)" in capsys.readouterr().out

    def test_a_vendor_without_saga_is_named_as_such(
        self,
        orchestrate: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A saga task sent to a vendor without saga is prose, and the session reports itself done."""
        monkeypatch.setattr(orchestrate, "roster", lambda: [("muse", "model,effort")])
        monkeypatch.setattr(orchestrate, "launchable", lambda: ["muse"])
        monkeypatch.setattr(orchestrate, "saga_capabilities", lambda _v: [])
        orchestrate.cmd_roster(NS(models=False, probe=False, limit=12))

        assert "arrives as prose" in capsys.readouterr().out

    def test_the_landmine_note_reaches_the_reader(
        self,
        orchestrate: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """qwen's `--safe-mode` is the flag most likely to be added by reasoning from its name."""
        monkeypatch.setattr(orchestrate, "roster", lambda: [("qwen", "model")])
        monkeypatch.setattr(orchestrate, "launchable", lambda: ["qwen"])
        monkeypatch.setattr(orchestrate, "saga_capabilities", lambda _v: ["plan"])
        orchestrate.cmd_roster(NS(models=False, probe=False, limit=12))

        assert "--safe-mode" in capsys.readouterr().out


class TestOpenCodeVariantResolution:
    """Variant selection and resolution from live OpenCode /variants picker choices."""

    def test_team_mimir_regression_selects_xhigh_never_guesses_max(
        self, orchestrate: ModuleType
    ) -> None:
        """Team Mimir regression: Muse picker with xhigh as top option selects xhigh for 'max'."""
        options = ["Default", "minimal", "low", "medium", "high", "xhigh"]
        # When max / maximum available is requested, resolve the highest actually offered
        for req in ("max", "maximum", "maximum available", "highest", None):
            selected = orchestrate.resolve_opencode_variant(req, options)
            assert selected == "xhigh", f"expected 'xhigh' for request {req!r}, got {selected!r}"

    def test_picker_offering_max_selects_max(self, orchestrate: ModuleType) -> None:
        options = ["Default", "low", "medium", "high", "max"]
        assert orchestrate.resolve_opencode_variant("max", options) == "max"
        assert orchestrate.resolve_opencode_variant("maximum available", options) == "max"

    def test_exact_variant_selection_matches_and_preserves_offered_casing(
        self, orchestrate: ModuleType
    ) -> None:
        options = ["Default", "minimal", "low", "medium", "High", "xhigh"]
        assert orchestrate.resolve_opencode_variant("high", options) == "High"
        assert orchestrate.resolve_opencode_variant("minimal", options) == "minimal"
        assert orchestrate.resolve_opencode_variant("default", options) == "Default"

    def test_unavailable_exact_variant_fails_loudly_with_choices(
        self, orchestrate: ModuleType
    ) -> None:
        options = ["Default", "minimal", "low", "medium", "high", "xhigh"]
        with pytest.raises(SystemExit) as exc_info:
            orchestrate.resolve_opencode_variant("ultra", options)
        msg = str(exc_info.value)
        assert "ultra" in msg
        assert "options the live picker offered" in msg

    def test_empty_picker_options_fails_loudly(self, orchestrate: ModuleType) -> None:
        with pytest.raises(SystemExit) as exc_info:
            orchestrate.resolve_opencode_variant("max", [])
        assert "no variant choices presented" in str(exc_info.value)


class TestOpenCodePickerParsing:
    """Parsing terminal output from OpenCode's /variants picker."""

    def test_parses_bulleted_menu_options(self, orchestrate: ModuleType) -> None:
        text = "Select a variant:\n> Default\n  minimal\n  low\n  medium\n  high\n  xhigh\n"
        assert orchestrate.parse_opencode_variants(text) == [
            "Default",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        ]

    def test_parses_numbered_options_with_ansi_escape_codes(self, orchestrate: ModuleType) -> None:
        text = (
            "\x1b[1mVariants:\x1b[0m\n"
            "1. Default\n"
            "2. minimal\n"
            "3. low\n"
            "4. medium\n"
            "5. high\n"
            "6. xhigh\n"
        )
        assert orchestrate.parse_opencode_variants(text) == [
            "Default",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        ]

    def test_parses_bracketed_menu_items(self, orchestrate: ModuleType) -> None:
        text = "Choose variant:\n[x] Default\n[ ] low\n[ ] medium\n[ ] high\n[ ] max\n"
        assert orchestrate.parse_opencode_variants(text) == [
            "Default",
            "low",
            "medium",
            "high",
            "max",
        ]


class TestTheReusedPaneGuardIsInherited:
    """Orchestrate launches through launcher.py exec'd into itself, so the guard issue 897 ships
    there applies to a dispatched unit without a second implementation that could drift."""

    def test_dispatched_units_get_the_launcher_guard_not_a_copy(
        self, orchestrate: ModuleType
    ) -> None:
        assert hasattr(orchestrate, "guard_reused_pane")
        assert hasattr(orchestrate, "composer_staged_text")
        # The guard is the launcher that was exec'd, not a second copy in the driver.
        # The resolved launcher is the sibling package, or AGENT_LAUNCHER_ROOT when set.
        launcher = orchestrate._agent_launcher_script()
        assert launcher is not None
        guard_file = Path(orchestrate.guard_reused_pane.__code__.co_filename).resolve()
        launch_file = Path(orchestrate.launch.__code__.co_filename).resolve()
        assert guard_file == launcher.resolve()
        assert launch_file == launcher.resolve()


class TestAPlanOmittingPermissionSaysSo:
    """Inheriting the default because a plan row omitted the field is reported, not silent."""

    def test_plan_omission_of_permission_is_reported(
        self, orchestrate: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = {
            "units": [
                {"name": "u0", "vendor": "claude", "task": "build it"},
                {
                    "name": "u1",
                    "vendor": "claude",
                    "task": "extend it",
                    "permission": "bypass",
                },
            ]
        }
        units = orchestrate.plan_units(plan)
        assert units[0].permission_declared is False
        assert units[1].permission_declared is True
        assert "permission not declared, inheriting auto: u0" in capsys.readouterr().out

    def test_declared_permission_survives_a_run_record_round_trip(
        self, orchestrate: ModuleType
    ) -> None:

        unit = orchestrate.Unit(name="u", vendor="claude", task="x")
        unit.permission_declared = False
        raw = dataclasses.asdict(unit)
        assert "permission_declared" in raw
        assert orchestrate.Unit(**raw).permission_declared is False
