"""Tests for qa_strategies — the prescribed strategy catalogue (issue 1039).

Nothing here runs a real driver against a real environment: every command goes through an injected
runner, and the one test that reads installed plugin roots points at temporary directories through
the documented override. Nothing writes the primary checkout's live store.

The sixteen acceptance criteria of `docs/specs/2026-09-19-qa-testing-strategies-spec.md` are the
map for this file; each test names the criterion it proves in its docstring.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
CATALOGUE_FILE = REFERENCES / "qa-catalogue.yaml"
ENVELOPE_SCHEMA_FILE = REFERENCES / "qa-envelope.schema.json"
PROFILE_SCHEMA_FILE = REFERENCES / "qa-profile.schema.json"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_from(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


QA = _load("qa_strategies")
RUN_RECORD = _load("run_record")
#: The repository's own copy, not an installed one: the drift guard below must check the file this
#: change ships, or a stale installed fleet-core would make it pass while the two had drifted.
JEV_VERBS = _load_from(
    "jev_verbs_for_qa_catalogue",
    REPO_ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "jev_verbs.py",
)

#: The ten strategy identifiers the specification names. Written out rather than read from the
#: catalogue, because a test that read the file it guards would pass on any ten rows.
TEN_STRATEGIES = (
    "api-workflow",
    "contract-check",
    "app-ui",
    "hosted-surface",
    "cli-smoke",
    "deploy-boundary",
    "data-check",
    "infrastructure-read-back",
    "installed-surface",
    "manual-runbook",
)


def _raw_catalogue() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CATALOGUE_FILE.read_text(encoding="utf-8"))
    return loaded


def _profile(**strategies: Any) -> dict[str, Any]:
    return {
        "schema": "qa_profile.v1",
        "ceiling": {"max_duration_seconds": 100000, "max_direct_cost": 100},
        "strategies": dict(strategies),
    }


def _runner(exit_code: int = 0, output: str = "") -> Any:
    """A runner that records what it was asked to run and answers the same way every time."""
    calls: list[dict[str, Any]] = []

    def run(argv: Any, timeout: int, cwd: Any) -> tuple[int, str]:
        calls.append({"argv": list(argv), "timeout": timeout, "cwd": cwd})
        return exit_code, output

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _driver_calls(run: Any) -> list[dict[str, Any]]:
    """Every call except the version-control read that gathers the change's file list.

    "Zero drivers ran" is a claim about drivers. The file list is read before any selection
    exists, so counting that read would make the assertion pass or fail for the wrong reason.
    """
    return [call for call in run.calls if call["argv"][:1] != ["git"]]


# ---------------------------------------------------------------------------
# U1 — the catalogue and the schemas.
# ---------------------------------------------------------------------------


class TestCatalogue:
    def test_the_catalogue_lists_exactly_the_ten_named_strategies(self) -> None:
        """Criterion 1, and the card's first: exactly ten, and exactly these ten."""
        catalogue = QA.load_catalogue()
        assert len(catalogue.strategies) == 10
        assert set(catalogue.strategies) == set(TEN_STRATEGIES)

    def test_every_row_carries_a_tool_patterns_evidence_boundary_and_threshold(self) -> None:
        """Criterion 1's second half: no row is a placeholder."""
        catalogue = QA.load_catalogue()
        for strategy in catalogue.strategies.values():
            assert strategy.tool.strip()
            assert strategy.invocation.strip()
            assert strategy.required_evidence
            assert strategy.threshold.strip()
            assert strategy.proof_boundary in QA.BOUNDARIES
            assert isinstance(strategy.file_patterns, tuple)

    def test_a_row_that_ships_no_driver_says_why_and_when_to_revisit(self) -> None:
        catalogue = QA.load_catalogue()
        without = [s for s in catalogue.strategies.values() if s.driver is None]
        assert without, "the catalogue declares strategies without drivers by design"
        for strategy in without:
            assert strategy.no_driver_reason and strategy.no_driver_reason.strip()
            assert strategy.revisit_when and strategy.revisit_when.strip()

    def test_every_named_driver_exists_in_the_dispatch_table(self) -> None:
        """A catalogue naming a driver this module does not carry is a name that lies."""
        catalogue = QA.load_catalogue()
        named = {s.driver for s in catalogue.strategies.values() if s.driver}
        assert named <= set(QA.DRIVERS)

    def test_a_row_missing_a_column_is_refused_naming_the_row_and_the_column(
        self, tmp_path: Path
    ) -> None:
        raw = _raw_catalogue()
        del raw["strategies"][0]["threshold"]
        broken = tmp_path / "catalogue.yaml"
        broken.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(QA.QaStrategiesError) as caught:
            QA.load_catalogue(broken)
        assert "api-workflow" in str(caught.value)
        assert "threshold" in str(caught.value)

    def test_a_row_with_an_unknown_proof_boundary_is_refused(self, tmp_path: Path) -> None:
        raw = _raw_catalogue()
        raw["strategies"][0]["proof_boundary"] = "production"
        broken = tmp_path / "catalogue.yaml"
        broken.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(QA.QaStrategiesError) as caught:
            QA.load_catalogue(broken)
        assert "production" in str(caught.value)

    def test_the_declared_act_band_is_a_probability(self) -> None:
        """The band is data in one place the operator can change without touching code."""
        catalogue = QA.load_catalogue()
        assert 0.0 < catalogue.act_band < 1.0

    def test_the_judgment_verb_names_the_same_strategies_the_catalogue_does(self) -> None:
        """The KTD3 guard: a row added to one and not the other fails, in both directions.

        Loaded from the repository's own fleet-core rather than from an installed one, so the
        guard checks the file this change ships and never an older copy on the machine.
        """
        verb = JEV_VERBS.VERBS[QA.load_catalogue().verb]
        assert set(verb.questions) == set(TEN_STRATEGIES)
        assert set(verb.questions) == set(QA.load_catalogue().strategies)


class TestTheCardsOwnSelectors:
    """Every ``-k`` selector the card's acceptance criteria name must select at least one test.

    A selector that matches nothing passes vacuously, which is the false green this whole card
    exists to remove — and it is one rename away at any time. Written after
    ``blocked_routes_to_operator`` selected zero tests while every behaviour it names was covered
    under a different name.
    """

    #: Verbatim from the card's acceptance criteria.
    CARD_SELECTORS = (
        "widen_only",
        "judgment_absent",
        "blocked_not_passed",
        "verdict_matrix",
        "blocked_routes_to_operator",
        "envelope",
        "boundary",
        "cost_refusal",
    )

    def test_every_selector_the_card_names_matches_a_test_in_this_file(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        names = [
            line.split("def ", 1)[1].split("(", 1)[0]
            for line in source.splitlines()
            if line.lstrip().startswith("def test_")
        ]
        unmatched = [
            selector
            for selector in self.CARD_SELECTORS
            if not any(selector in name for name in names)
        ]
        assert unmatched == [], (
            f"these acceptance-criteria selectors match no test, so their command would pass "
            f"having run nothing: {unmatched}"
        )


class TestRemovals:
    """Specification criterion 11 and the card's tenth: the score is gone in file AND in string."""

    def test_the_health_score_script_and_its_test_are_gone(self) -> None:
        assert not (SCRIPTS / "qa_health_score.py").exists()
        assert not (REPO_ROOT / "tests" / "test_qa_health_score.py").exists()

    def test_no_qa_skill_or_saga_script_names_the_retired_score(self) -> None:
        """The changelog records the removal and is outside this sweep; nothing else may name it.

        Written after the retarget of ``status_card.project_qa`` reintroduced the phrase in a
        docstring explaining what the rows used to be. A removal that survives in a grep is a
        removal only halfway done.
        """
        needle = "health score"
        offenders: list[str] = []
        for directory in (
            REPO_ROOT / "plugins" / "saga" / "skills" / "qa",
            REPO_ROOT / "plugins" / "saga" / "scripts",
        ):
            for path in directory.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if needle in text.lower():
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == [], f"these files still name the retired score: {offenders}"

    def test_no_qa_skill_file_calls_the_removed_evidence_ledger(self) -> None:
        """Specification criterion 12, and the card's eleventh."""
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / "plugins" / "saga" / "skills" / "qa").rglob("*")
            if path.is_file() and "evidence_ledger" in path.read_text(encoding="utf-8")
        ]
        assert offenders == [], f"these files still call the removed ledger: {offenders}"


class TestProfile:
    def test_a_repository_with_no_profile_file_is_blocked_naming_the_path(
        self, tmp_path: Path
    ) -> None:
        """Criterion 14: never an empty selection that passes."""
        with pytest.raises(QA.ProfileRefusalError) as caught:
            QA.load_profile(tmp_path)
        assert str(tmp_path / QA.PROFILE_FILENAME) in str(caught.value)

    def test_a_profile_with_no_qa_block_is_blocked_naming_the_missing_key(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / QA.PROFILE_FILENAME).write_text(
            json.dumps({"schema": "repository_profile.v1"}), encoding="utf-8"
        )
        with pytest.raises(QA.ProfileRefusalError) as caught:
            QA.load_profile(tmp_path)
        assert "'qa'" in str(caught.value)

    def test_a_profile_whose_strategies_are_all_optional_is_blocked(self, tmp_path: Path) -> None:
        """Criterion 14's other half: such a profile could report a pass having proved nothing."""
        (tmp_path / QA.PROFILE_FILENAME).write_text(
            json.dumps({"qa": _profile(**{"cli-smoke": {"required": False}})}), encoding="utf-8"
        )
        with pytest.raises(QA.ProfileRefusalError) as caught:
            QA.load_profile(tmp_path)
        assert "all optional" in str(caught.value) or "every strategy" in str(caught.value)

    def test_a_profile_with_no_ceiling_is_refused_rather_than_assumed_unlimited(
        self, tmp_path: Path
    ) -> None:
        block = _profile(**{"cli-smoke": {"required": True}})
        del block["ceiling"]
        (tmp_path / QA.PROFILE_FILENAME).write_text(json.dumps({"qa": block}), encoding="utf-8")
        with pytest.raises(QA.ProfileRefusalError) as caught:
            QA.load_profile(tmp_path)
        assert "ceiling" in str(caught.value)

    def test_a_profile_naming_a_strategy_the_catalogue_lacks_is_refused(
        self, tmp_path: Path
    ) -> None:
        block = _profile(**{"cli-smoke": {"required": True}, "made-up": {"required": False}})
        (tmp_path / QA.PROFILE_FILENAME).write_text(json.dumps({"qa": block}), encoding="utf-8")
        with pytest.raises(QA.ProfileRefusalError) as caught:
            QA.load_profile(tmp_path, catalogue=QA.load_catalogue())
        assert "made-up" in str(caught.value)

    def test_this_repositorys_own_qa_block_validates_against_the_profile_schema(self) -> None:
        """U6: the profile this repository ships is the one the end-to-end run reads."""
        profile_path = REPO_ROOT / ".saga-profile.json"
        if not profile_path.is_file():
            pytest.skip("this catalog does not carry the upstream repository's .saga-profile.json")
        jsonschema = pytest.importorskip("jsonschema")
        whole = json.loads(profile_path.read_text(encoding="utf-8"))
        schema = json.loads(PROFILE_SCHEMA_FILE.read_text(encoding="utf-8"))
        jsonschema.validate(whole["qa"], schema)
        assert any(entry["required"] for entry in whole["qa"]["strategies"].values())


# ---------------------------------------------------------------------------
# U2 — selection, the boundary ladder, and the widen-only judgment.
# ---------------------------------------------------------------------------


class TestSelection:
    def test_two_matching_patterns_select_those_two_and_name_the_pattern_for_each(self) -> None:
        """Criterion 2: no judgment is called and each entry carries its matching pattern."""
        catalogue = QA.load_catalogue()
        profile = _profile(
            **{
                "cli-smoke": {"required": False},
                "installed-surface": {"required": False},
                "contract-check": {"required": False},
            }
        )
        selection = QA.declared_selection(
            catalogue,
            profile,
            ["plugins/saga/scripts/thing.py", "plugins/saga/skills/qa/SKILL.md"],
        )
        assert sorted(selection.ids) == ["cli-smoke", "installed-surface"]
        for entry in selection.entries:
            assert "matched the changed file" in entry.reason
            assert entry.source == "profile"

    def test_a_required_strategy_runs_whatever_the_change_touched(self) -> None:
        catalogue = QA.load_catalogue()
        profile = _profile(**{"cli-smoke": {"required": True}})
        selection = QA.declared_selection(catalogue, profile, ["README.md"])
        assert selection.ids == ["cli-smoke"]
        assert "required" in selection.entries[0].reason

    def test_widen_only_adds_a_strategy_above_the_band(self) -> None:
        """Criterion 3, first direction, reading the band from the catalogue file."""
        catalogue = QA.load_catalogue()
        profile = _profile(
            **{
                "cli-smoke": {"required": True},
                "contract-check": {"required": False},
            }
        )
        selection = QA.declared_selection(catalogue, profile, ["README.md"])
        assert selection.ids == ["cli-smoke"]

        def widen(state: Any, verb: str, floors: Any, **options: Any) -> Any:
            assert options["threshold"] == catalogue.act_band
            unions = dict(floors)
            unions["contract-check"] = True
            return SimpleNamespace(
                unions=lambda: unions,
                to_dict=lambda: {"threshold": options["threshold"]},
                asked=True,
            )

        widened = QA.widen_selection(
            selection, catalogue, profile, changed_files=["README.md"], widen=widen
        )
        assert sorted(widened.ids) == ["cli-smoke", "contract-check"]
        added = [e for e in widened.entries if e.strategy_id == "contract-check"][0]
        assert added.source == QA.REASON_JUDGMENT
        assert str(catalogue.act_band) in added.reason

    def test_widen_never_removes_a_declared_strategy_below_the_band(self) -> None:
        """Criterion 3, second direction: the declaration is a floor, not a proposal."""
        catalogue = QA.load_catalogue()
        profile = _profile(**{"cli-smoke": {"required": True}})
        selection = QA.declared_selection(catalogue, profile, ["README.md"])

        def widen(state: Any, verb: str, floors: Any, **options: Any) -> Any:
            # The model says no to everything, including the strategy the floor selected.
            unions = dict.fromkeys(floors, False)
            return SimpleNamespace(unions=lambda: unions, to_dict=lambda: {}, asked=True)

        widened = QA.widen_selection(
            selection, catalogue, profile, changed_files=["README.md"], widen=widen
        )
        assert "cli-smoke" in widened.ids

    def test_judgment_absent_degrades_to_the_declared_set(self) -> None:
        """Criterion 4: no run fails because a judgment was unavailable."""
        catalogue = QA.load_catalogue()
        profile = _profile(**{"cli-smoke": {"required": True}})
        selection = QA.declared_selection(catalogue, profile, ["README.md"])
        widened = QA.widen_selection(
            selection, catalogue, profile, changed_files=["README.md"], widen=None
        )
        assert widened.ids == ["cli-smoke"]

    def test_judgment_raising_degrades_to_the_declared_set(self) -> None:
        """Criterion 4: an erroring client is a note on the record, never a failed run."""
        catalogue = QA.load_catalogue()
        profile = _profile(**{"cli-smoke": {"required": True}})
        selection = QA.declared_selection(catalogue, profile, ["README.md"])

        def widen(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("the endpoint did not answer")

        widened = QA.widen_selection(
            selection, catalogue, profile, changed_files=["README.md"], widen=widen
        )
        assert widened.ids == ["cli-smoke"]
        assert widened.judgment["asked"] is False
        assert "TimeoutError" in widened.judgment["note"]

    def test_the_boundary_ladder_orders_narrowest_first(self) -> None:
        assert QA.BOUNDARIES == ("hermetic", "branch-preview", "non-production")
        assert QA.within_boundary("hermetic", "non-production")
        assert not QA.within_boundary("non-production", "branch-preview")

    def test_boundary_branch_preview_omits_non_production_as_out_of_boundary(self) -> None:
        """Criterion 9: omitted with a reason, and never recorded as proof debt."""
        catalogue = QA.load_catalogue()
        profile = _profile(
            **{
                "cli-smoke": {"required": True},
                "deploy-boundary": {"required": True},
            }
        )
        selection = QA.declared_selection(
            catalogue, profile, ["plugins/saga/scripts/x.py"], boundary="branch-preview"
        )
        assert selection.ids == ["cli-smoke"]
        excluded = {item["strategy_id"] for item in selection.out_of_boundary}
        assert excluded == {"deploy-boundary"}
        assert selection.out_of_boundary[0]["reason"] == QA.REASON_OUT_OF_BOUNDARY
        assert "not proof debt" in selection.out_of_boundary[0]["detail"]

    def test_an_unknown_boundary_is_refused(self) -> None:
        catalogue = QA.load_catalogue()
        with pytest.raises(QA.QaStrategiesError):
            QA.declared_selection(catalogue, _profile(), [], boundary="production")


# ---------------------------------------------------------------------------
# U3 — the preflight.
# ---------------------------------------------------------------------------


class TestPreflight:
    def test_cost_refusal_refuses_the_whole_selection(self) -> None:
        """Criterion 10: the affordable subset is never run on its own."""
        catalogue = QA.load_catalogue()
        profile = _profile(**{"cli-smoke": {"required": True}})
        profile["ceiling"] = {"max_duration_seconds": 1, "max_direct_cost": 0}
        selection = QA.declared_selection(catalogue, profile, ["README.md"])
        checks = QA.preflight(selection, catalogue, profile, environ={})
        assert checks["refused"] is True
        assert "the whole selection is refused" in checks["reason"]
        assert "never run on its own" in checks["reason"]

    def test_cost_refusal_runs_zero_drivers(self, tmp_path: Path) -> None:
        """Criterion 10's observable half, asserted on the runner rather than on the message."""
        run = _runner()
        record = RUN_RECORD.RunRecord(issue=7, repo="o/r")
        RUN_RECORD.save(tmp_path, record)
        profile_file = tmp_path / QA.PROFILE_FILENAME
        block = _profile(
            **{"cli-smoke": {"required": True, "commands": [{"name": "x", "command": "true"}]}}
        )
        block["ceiling"] = {"max_duration_seconds": 1, "max_direct_cost": 0}
        profile_file.write_text(json.dumps({"qa": block}), encoding="utf-8")
        result = QA.execute(
            issue=7,
            repo_root=tmp_path,
            store_root=tmp_path,
            profile_path=profile_file,
            runner=run,
            environ={},
            widen=None,
        )
        assert result["verdict"] == QA.VERDICT_BLOCKED
        assert result["envelopes"] == []
        assert _driver_calls(run) == []

    def test_a_missing_secret_handle_refuses_the_whole_selection(self) -> None:
        """A credential is the operator's boundary, so the run asks rather than proving part."""
        catalogue = QA.load_catalogue()
        profile = _profile(
            **{"cli-smoke": {"required": True, "secret_handles": ["QA_SIGNING_KEY"]}}
        )
        selection = QA.declared_selection(catalogue, profile, ["README.md"])
        checks = QA.preflight(selection, catalogue, profile, environ={})
        assert checks["refused"] is True
        assert "QA_SIGNING_KEY" in checks["reason"]

    def test_an_affordable_selection_is_not_refused(self) -> None:
        catalogue = QA.load_catalogue()
        profile = _profile(**{"cli-smoke": {"required": True}})
        checks = QA.preflight(
            QA.declared_selection(catalogue, profile, ["README.md"]), catalogue, profile, environ={}
        )
        assert checks["refused"] is False


# ---------------------------------------------------------------------------
# U4 — the envelope, the redaction and the drivers.
# ---------------------------------------------------------------------------


class TestEnvelope:
    def _strategy(self, identifier: str = "cli-smoke") -> Any:
        return QA.load_catalogue().strategies[identifier]

    def test_an_envelope_validates_against_the_schema_with_the_real_library(self) -> None:
        """Criterion 8, checked with jsonschema so the runtime checker cannot drift from it."""
        jsonschema = pytest.importorskip("jsonschema")
        envelope = QA.make_envelope(
            self._strategy(),
            result="passed",
            status_reason="two invocations exited zero",
            environment="nonprod",
            profile_revision="abc123",
        )
        jsonschema.validate(envelope, json.loads(ENVELOPE_SCHEMA_FILE.read_text(encoding="utf-8")))
        assert QA.validate_envelope(envelope) == []

    def test_the_runtime_checker_names_a_missing_required_field(self) -> None:
        envelope = QA.make_envelope(
            self._strategy(),
            result="passed",
            status_reason="ok",
            environment="nonprod",
            profile_revision="abc123",
        )
        del envelope["privacy_attestation"]
        assert any("privacy_attestation" in problem for problem in QA.validate_envelope(envelope))

    def test_the_runtime_checker_names_a_result_outside_the_three(self) -> None:
        envelope = QA.make_envelope(
            self._strategy(),
            result="passed",
            status_reason="ok",
            environment="nonprod",
            profile_revision="abc123",
        )
        envelope["result"] = "skipped"
        assert any("'result'" in problem for problem in QA.validate_envelope(envelope))

    def test_a_fourth_result_value_is_refused_at_the_door(self) -> None:
        with pytest.raises(QA.QaStrategiesError):
            QA.make_envelope(
                self._strategy(),
                result="skipped",
                status_reason="ok",
                environment="nonprod",
                profile_revision="abc123",
            )

    def test_an_envelope_carries_no_bearer_token(self) -> None:
        """Criterion 8's other half: redaction happens before the envelope exists."""
        leaked = "calling with Authorization: Bearer sk-live-01234567890abcdefghij"
        envelope = QA.make_envelope(
            self._strategy(),
            result="failed",
            status_reason=leaked,
            environment="nonprod",
            profile_revision="abc123",
            evidence={"detail": leaked, "nested": {"header": "bearer abcdefghijklmnop"}},
        )
        body = json.dumps(envelope)
        assert "sk-live-01234567890abcdefghij" not in body
        assert "abcdefghijklmnop" not in body
        assert QA.REDACTED in body

    def test_redaction_survives_a_redactor_that_raises(self, monkeypatch: Any) -> None:
        def boom(_: str) -> str:
            raise RuntimeError("the redactor is broken")

        monkeypatch.setattr(QA, "_fleet_redactor", lambda: boom)
        assert "Bearer" not in QA.redact("Authorization: Bearer 0123456789abcdef")


class TestDrivers:
    def _context(self, strategy_id: str, entry: dict[str, Any], **extra: Any) -> Any:
        catalogue = QA.load_catalogue()
        defaults: dict[str, Any] = {
            "environment": {},
            "profile_revision": "r1",
            "repo_root": REPO_ROOT,
            "runner": _runner(),
            "environ": {},
        }
        defaults.update(extra)
        return QA.DriverContext(strategy=catalogue.strategies[strategy_id], entry=entry, **defaults)

    def test_a_missing_required_environment_variable_is_blocked_not_passed(self) -> None:
        """Criterion 5, and the card's fourth: the reason names the variable."""
        context = self._context(
            "cli-smoke",
            {
                "environment_variables": ["QA_BASE_URL"],
                "commands": [{"name": "x", "command": "true"}],
            },
            environ={},
        )
        outcome = QA.driver_cli_smoke(context)
        assert outcome["result"] == QA.RESULT_BLOCKED
        assert outcome["result"] != QA.RESULT_PASSED
        assert "QA_BASE_URL" in outcome["status_reason"]

    def test_a_strategy_with_no_declared_command_is_blocked(self) -> None:
        outcome = QA.driver_cli_smoke(self._context("cli-smoke", {}))
        assert outcome["result"] == QA.RESULT_BLOCKED
        assert "no command" in outcome["status_reason"]

    def test_cli_smoke_passes_when_every_invocation_exits_zero(self) -> None:
        context = self._context(
            "cli-smoke",
            {
                "commands": [
                    {"name": "a", "command": "echo one"},
                    {"name": "b", "command": "echo two"},
                ]
            },
            runner=_runner(0, "fine"),
        )
        outcome = QA.driver_cli_smoke(context)
        assert outcome["result"] == QA.RESULT_PASSED
        assert outcome["evidence"]["exit_codes"] == [0, 0]

    def test_cli_smoke_fails_when_an_invocation_does_not_exit_zero(self) -> None:
        context = self._context(
            "cli-smoke", {"commands": [{"name": "a", "command": "false"}]}, runner=_runner(1, "no")
        )
        outcome = QA.driver_cli_smoke(context)
        assert outcome["result"] == QA.RESULT_FAILED
        assert "a" in outcome["status_reason"]

    def test_cli_smoke_fails_when_the_deployed_version_marker_is_absent(self) -> None:
        context = self._context(
            "cli-smoke",
            {"commands": [{"name": "a", "command": "echo hi"}]},
            runner=_runner(0, "no version here"),
            environment={"version_marker": "1.2.3"},
        )
        outcome = QA.driver_cli_smoke(context)
        assert outcome["result"] == QA.RESULT_FAILED
        assert "1.2.3" in outcome["status_reason"]

    def test_deploy_boundary_is_blocked_with_no_recorded_environment(self) -> None:
        outcome = QA.driver_deploy_boundary(self._context("deploy-boundary", {}))
        assert outcome["result"] == QA.RESULT_BLOCKED
        assert "base URL" in outcome["status_reason"]

    def test_deploy_boundary_passes_when_the_edge_serves_the_recorded_revision(self) -> None:
        context = self._context(
            "deploy-boundary",
            {"commands": [{"name": "probe", "command": "curl example"}]},
            environment={"base_url": "https://example", "revision": "a" * 40},
            runner=_runner(0, "served " + "a" * 40),
        )
        outcome = QA.driver_deploy_boundary(context)
        assert outcome["result"] == QA.RESULT_PASSED

    def test_deploy_boundary_fails_when_the_edge_serves_another_revision(self) -> None:
        context = self._context(
            "deploy-boundary",
            {"commands": [{"name": "probe", "command": "curl example"}]},
            environment={"base_url": "https://example", "revision": "a" * 40},
            runner=_runner(0, "served " + "b" * 40),
        )
        assert QA.driver_deploy_boundary(context)["result"] == QA.RESULT_FAILED

    def test_contract_check_passes_when_only_permitted_drift_appears(self) -> None:
        context = self._context(
            "contract-check",
            {
                "commands": [{"name": "diff", "command": "oasdiff run"}],
                "permitted_changes": ["added-optional-field"],
            },
            runner=_runner(1, "added-optional-field on /things"),
        )
        assert QA.driver_contract_check(context)["result"] == QA.RESULT_PASSED

    def test_contract_check_fails_on_drift_the_profile_does_not_permit(self) -> None:
        context = self._context(
            "contract-check",
            {"commands": [{"name": "diff", "command": "oasdiff run"}]},
            runner=_runner(1, "removed required field"),
        )
        assert QA.driver_contract_check(context)["result"] == QA.RESULT_FAILED

    def test_installed_surface_reads_every_root_and_fails_when_they_disagree(
        self, tmp_path: Path
    ) -> None:
        """The six-release trap: one root updated and the other did not."""
        roots = []
        for name, version in (("live", "1.0.0"), ("company", "0.9.0")):
            root = tmp_path / name
            manifest = root / "plugins" / "saga" / ".claude-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"version": version}), encoding="utf-8")
            roots.append(str(root))
        context = self._context(
            "installed-surface",
            {"plugins": ["saga"]},
            environ={"INFIQUETRA_PLUGIN_ROOTS": ":".join(roots)},
        )
        outcome = QA.driver_installed_surface(context)
        assert outcome["result"] == QA.RESULT_FAILED
        assert "do not agree" in outcome["status_reason"]
        assert len(outcome["evidence"]["roots"]) == 2

    def test_installed_surface_passes_when_every_root_agrees(self, tmp_path: Path) -> None:
        roots = []
        for name in ("live", "company"):
            root = tmp_path / name
            plugin = root / "plugins" / "saga"
            (plugin / ".claude-plugin").mkdir(parents=True)
            (plugin / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"version": "1.0.0"}), encoding="utf-8"
            )
            (plugin / "commands").mkdir()
            (plugin / "commands" / "qa.md").write_text("x", encoding="utf-8")
            roots.append(str(root))
        context = self._context(
            "installed-surface",
            {"plugins": ["saga"], "expected_surfaces": ["commands/qa.md"]},
            environ={"INFIQUETRA_PLUGIN_ROOTS": ":".join(roots)},
            environment={"version_marker": "1.0.0"},
        )
        assert QA.driver_installed_surface(context)["result"] == QA.RESULT_PASSED

    def test_installed_surface_fails_on_a_missing_expected_surface(self, tmp_path: Path) -> None:
        root = tmp_path / "live"
        (root / "plugins" / "saga" / ".claude-plugin").mkdir(parents=True)
        (root / "plugins" / "saga" / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "1.0.0"}), encoding="utf-8"
        )
        context = self._context(
            "installed-surface",
            {"plugins": ["saga"], "expected_surfaces": ["commands/qa.md"]},
            environ={"INFIQUETRA_PLUGIN_ROOTS": str(root)},
        )
        outcome = QA.driver_installed_surface(context)
        assert outcome["result"] == QA.RESULT_FAILED
        assert "commands/qa.md" in outcome["status_reason"]

    def test_installed_surface_compares_each_plugin_across_roots_not_against_each_other(
        self, tmp_path: Path
    ) -> None:
        """Two plugins are released on their own numbers.

        Found by the first live run: comparing saga's version against fleet-core's reported a
        disagreement on a machine where both roots were perfectly consistent.
        """
        roots = []
        for name in ("live", "company"):
            root = tmp_path / name
            for plugin, version in (("saga", "1.0.0"), ("fleet-core", "0.29.0")):
                manifest = root / "plugins" / plugin / ".claude-plugin" / "plugin.json"
                manifest.parent.mkdir(parents=True)
                manifest.write_text(json.dumps({"version": version}), encoding="utf-8")
            roots.append(str(root))
        context = self._context(
            "installed-surface",
            {"plugins": ["saga", "fleet-core"]},
            environ={"INFIQUETRA_PLUGIN_ROOTS": ":".join(roots)},
        )
        outcome = QA.driver_installed_surface(context)
        assert outcome["result"] == QA.RESULT_PASSED
        assert outcome["evidence"]["version_disagreements"] == []

    def test_installed_surface_still_catches_one_plugin_drifting_between_roots(
        self, tmp_path: Path
    ) -> None:
        """The per-plugin comparison must not have blunted the check it exists for."""
        roots = []
        for name, saga_version in (("live", "1.0.0"), ("company", "0.9.0")):
            root = tmp_path / name
            for plugin, version in (("saga", saga_version), ("fleet-core", "0.29.0")):
                manifest = root / "plugins" / plugin / ".claude-plugin" / "plugin.json"
                manifest.parent.mkdir(parents=True)
                manifest.write_text(json.dumps({"version": version}), encoding="utf-8")
            roots.append(str(root))
        context = self._context(
            "installed-surface",
            {"plugins": ["saga", "fleet-core"]},
            environ={"INFIQUETRA_PLUGIN_ROOTS": ":".join(roots)},
        )
        outcome = QA.driver_installed_surface(context)
        assert outcome["result"] == QA.RESULT_FAILED
        assert outcome["evidence"]["version_disagreements"] == ["saga: 0.9.0, 1.0.0"]

    def test_installed_surface_expects_each_plugins_own_surfaces(self, tmp_path: Path) -> None:
        """A command belongs to one plugin; demanding it of all of them is the profile's bug."""
        root = tmp_path / "live"
        for plugin in ("saga", "fleet-core"):
            manifest = root / "plugins" / plugin / ".claude-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
        # The driver joins the surface the profile names (`commands/qa.md`) onto
        # the plugin root. That string is the profile contract, not the Claude
        # adapter path.
        (root / "plugins" / "saga" / "commands").mkdir()
        (root / "plugins" / "saga" / "commands" / "qa.md").write_text("x", encoding="utf-8")
        context = self._context(
            "installed-surface",
            {
                "plugins": ["saga", "fleet-core"],
                "expected_surfaces": {"saga": ["commands/qa.md"], "fleet-core": []},
            },
            environ={"INFIQUETRA_PLUGIN_ROOTS": str(root)},
        )
        assert QA.driver_installed_surface(context)["result"] == QA.RESULT_PASSED

    def test_the_campps_delegation_invokes_the_declared_entrypoint_and_ingests_its_envelope(
        self,
    ) -> None:
        """Criterion 13: it delegates rather than issuing its own requests."""
        run = _runner(
            0,
            json.dumps({"result": "passed", "status_reason": "scenario met", "evidence": {"m": 1}}),
        )
        context = self._context(
            "api-workflow",
            {
                "entrypoint": "uv run e2e-canary",
                "scenarios": ["identity-login"],
            },
            environment={"name": "nonprod"},
            runner=run,
        )
        outcome = QA.driver_delegated_canary(context)
        assert outcome["result"] == QA.RESULT_PASSED
        recorded = run.calls[0]["argv"]  # type: ignore[attr-defined]
        assert recorded[:3] == ["uv", "run", "e2e-canary"]
        assert "run-scenario" in recorded
        assert "identity-login" in recorded
        assert outcome["evidence"]["ingested_envelope"]["result"] == "passed"

    def test_the_campps_delegation_is_blocked_with_no_declared_entrypoint(self) -> None:
        outcome = QA.driver_delegated_canary(self._context("api-workflow", {}))
        assert outcome["result"] == QA.RESULT_BLOCKED
        assert "never issues its own requests" in outcome["status_reason"]

    def test_the_campps_delegation_is_blocked_when_the_executor_is_absent(self) -> None:
        def missing(argv: Any, timeout: int, cwd: Any) -> tuple[int, str]:
            raise FileNotFoundError("no such executable")

        context = self._context("api-workflow", {"entrypoint": "e2e-canary"}, runner=missing)
        assert QA.driver_delegated_canary(context)["result"] == QA.RESULT_BLOCKED

    def test_a_strategy_declared_without_a_driver_is_blocked_with_its_stated_reason(self) -> None:
        envelope = QA.run_strategy(
            QA.load_catalogue().strategies["app-ui"],
            {},
            environment={},
            profile_revision="r1",
            repo_root=REPO_ROOT,
            runner=_runner(),
            environ={},
        )
        assert envelope["result"] == QA.RESULT_BLOCKED
        assert "ships no driver" in envelope["status_reason"]
        assert envelope["evidence"]["revisit_when"]

    def test_a_driver_that_raises_is_blocked_and_the_run_continues(self, monkeypatch: Any) -> None:
        def boom(_: Any) -> dict[str, Any]:
            raise RuntimeError("the driver fell over")

        monkeypatch.setitem(QA.DRIVERS, "cli_smoke", boom)
        envelope = QA.run_strategy(
            QA.load_catalogue().strategies["cli-smoke"],
            {},
            environment={},
            profile_revision="r1",
            repo_root=REPO_ROOT,
            runner=_runner(),
            environ={},
        )
        assert envelope["result"] == QA.RESULT_BLOCKED
        assert "RuntimeError" in envelope["status_reason"]

    def test_a_timed_out_command_does_not_pass(self) -> None:
        def slow(argv: Any, timeout: int, cwd: Any) -> tuple[int, str]:
            raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout)

        context = self._context(
            "cli-smoke", {"commands": [{"name": "a", "command": "sleep 1"}]}, runner=slow
        )
        assert QA.driver_cli_smoke(context)["result"] != QA.RESULT_PASSED

    def test_a_quoted_argument_holding_a_space_stays_one_argument(self) -> None:
        """The profile's commands are written the way a person writes them in a shell.

        ``str.split`` cut ``-k "not slow"`` into three arguments and handed the program something
        the operator never asked it to run, with no error anywhere — the run simply tested the
        wrong thing. ``shlex.split`` is the same parsing ``build_loop.run_check`` has always used
        for the mechanical baseline, which is the same kind of value.
        """
        seen: list[list[str]] = []

        def capture(argv: Any, timeout: int, cwd: Any) -> tuple[int, str]:
            seen.append(list(argv))
            return 0, ""

        context = self._context(
            "cli-smoke",
            {"commands": [{"name": "a", "command": 'pytest -k "not slow" tests/'}]},
            runner=capture,
        )
        assert QA.driver_cli_smoke(context)["result"] == QA.RESULT_PASSED
        assert seen == [["pytest", "-k", "not slow", "tests/"]]

    def test_a_command_that_does_not_parse_is_reported_rather_than_raised(self) -> None:
        """An unbalanced quote is a profile the operator fixes, not a traceback out of the driver."""
        context = self._context(
            "cli-smoke",
            {"commands": [{"name": "a", "command": 'pytest -k "not slow'}]},
            runner=_runner(),
        )
        envelope = QA.driver_cli_smoke(context)
        assert envelope["result"] != QA.RESULT_PASSED


# ---------------------------------------------------------------------------
# U5 — the verdict, the route and the run record.
# ---------------------------------------------------------------------------


def _envelope(strategy_id: str, result: str) -> dict[str, Any]:
    return {"strategy_id": strategy_id, "result": result, "status_reason": "because"}


class TestVerdictMatrix:
    @pytest.mark.parametrize(
        ("results", "required", "expected"),
        [
            ({"a": "passed", "b": "passed"}, ["a", "b"], QA.VERDICT_PASS),
            ({"a": "passed"}, ["a"], QA.VERDICT_PASS),
            ({"a": "passed", "b": "blocked"}, ["a"], QA.VERDICT_PROOF_DEBT),
            ({"a": "passed", "b": "failed"}, ["a"], QA.VERDICT_PASS),
            ({"a": "failed", "b": "passed"}, ["a", "b"], QA.VERDICT_FAIL),
            ({"a": "blocked", "b": "passed"}, ["a", "b"], QA.VERDICT_FAIL),
            ({"a": "passed"}, ["a", "b"], QA.VERDICT_FAIL),
            ({"a": "blocked"}, ["a"], QA.VERDICT_FAIL),
            ({"a": "failed"}, ["a"], QA.VERDICT_FAIL),
        ],
    )
    def test_the_verdict_matrix(
        self, results: dict[str, str], required: list[str], expected: str
    ) -> None:
        """Criterion 6, and the card's fifth: the full status matrix."""
        envelopes = [_envelope(key, value) for key, value in results.items()]
        assert QA.verdict(envelopes, required) == expected

    def test_proof_debt_needs_every_required_strategy_passed(self) -> None:
        """An optional block beside a required failure is a fail, never proof debt."""
        envelopes = [_envelope("a", "failed"), _envelope("b", "blocked")]
        assert QA.verdict(envelopes, ["a"]) == QA.VERDICT_FAIL


class TestRouting:
    def test_a_required_blocked_routes_to_operator_not_the_build_loop(self) -> None:
        """Criterion 7, and the card's sixth."""
        decision = QA.route([_envelope("a", "blocked")], ["a"])
        assert decision["route"] == QA.ROUTE_OPERATOR
        assert decision["route"] != QA.ROUTE_BUILD_LOOP
        assert decision["blocked_required"] == ["a"]
        assert "no repair" not in decision["reason"]
        assert "build loop can repair" in decision["reason"]

    def test_a_required_failure_routes_to_the_build_loop(self) -> None:
        decision = QA.route([_envelope("a", "failed")], ["a"])
        assert decision["route"] == QA.ROUTE_BUILD_LOOP
        assert decision["verdict"] == QA.VERDICT_FAIL

    def test_a_required_block_beside_a_required_failure_still_stops_for_the_operator(self) -> None:
        decision = QA.route([_envelope("a", "failed"), _envelope("b", "blocked")], ["a", "b"])
        assert decision["route"] == QA.ROUTE_OPERATOR

    def test_a_pass_routes_to_close(self) -> None:
        decision = QA.route([_envelope("a", "passed")], ["a"])
        assert decision["route"] == QA.ROUTE_CLOSE
        assert decision["verdict"] == QA.VERDICT_PASS

    def test_proof_debt_routes_to_close_and_records_the_debt(self) -> None:
        decision = QA.route([_envelope("a", "passed"), _envelope("b", "blocked")], ["a"])
        assert decision["route"] == QA.ROUTE_CLOSE
        assert decision["verdict"] == QA.VERDICT_PROOF_DEBT
        assert decision["proof_debt"][0]["strategy_id"] == "b"

    def test_a_required_strategy_with_no_envelope_at_all_stops_for_the_operator(self) -> None:
        """Nothing ran, so nothing was proved; absence is never a pass."""
        decision = QA.route([], ["a"])
        assert decision["route"] == QA.ROUTE_OPERATOR

    @pytest.mark.parametrize(
        ("envelopes", "required", "code"),
        [
            ([_envelope("a", "passed")], ["a"], QA.EXIT_OK),
            ([_envelope("a", "passed"), _envelope("b", "blocked")], ["a"], QA.EXIT_OK),
            ([_envelope("a", "failed")], ["a"], QA.EXIT_FAIL),
            ([_envelope("a", "blocked")], ["a"], QA.EXIT_OPERATOR_STOP),
        ],
    )
    def test_each_route_has_its_own_exit_code(
        self, envelopes: list[dict[str, Any]], required: list[str], code: int
    ) -> None:
        """A failure and a required block route differently, so they exit differently."""
        assert QA.exit_code_for(QA.route(envelopes, required)) == code


class TestRunRecord:
    def test_the_block_lands_under_the_top_level_extension_point(self, tmp_path: Path) -> None:
        RUN_RECORD.save(tmp_path, RUN_RECORD.RunRecord(issue=11, repo="o/r"))
        QA.write_block(tmp_path, 11, {"verdict": "pass"})
        raw = json.loads(RUN_RECORD.record_path(tmp_path, 11).read_text(encoding="utf-8"))
        assert raw[QA.RECORD_KEY] == {"verdict": "pass"}

    def test_writing_the_block_disturbs_no_other_top_level_key(self, tmp_path: Path) -> None:
        record = RUN_RECORD.RunRecord(issue=11, repo="o/r", next_step="/work")
        RUN_RECORD.save(tmp_path, record)
        QA.write_block(tmp_path, 11, {"verdict": "pass"})
        reread = RUN_RECORD.load(tmp_path, 11)
        assert reread is not None
        assert reread.next_step == "/work"
        assert reread.repo == "o/r"

    def test_an_issue_with_no_run_record_is_refused_rather_than_invented(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(QA.ProfileRefusalError) as caught:
            QA.require_record(tmp_path, 404)
        assert "no run record" in str(caught.value)

    def test_the_environment_identity_is_read_never_invented(self) -> None:
        identity = QA.environment_identity(
            {
                "deploy": {"destination": "nonprod", "base_url": "https://x", "revision": "c" * 40},
                "release": {"landed_commit": "d" * 40},
            }
        )
        assert identity["name"] == "nonprod"
        assert identity["base_url"] == "https://x"
        assert identity["revision"] == "c" * 40

    def test_an_absent_deployment_yields_an_empty_identity_not_a_guess(self) -> None:
        identity = QA.environment_identity({})
        assert identity == {"name": "", "base_url": "", "revision": "", "version_marker": ""}


# ---------------------------------------------------------------------------
# U6 — the whole procedure and the report.
# ---------------------------------------------------------------------------


class TestExecute:
    def _fixture(self, tmp_path: Path, **overrides: Any) -> Path:
        RUN_RECORD.save(tmp_path, RUN_RECORD.RunRecord(issue=21, repo="o/r"))
        block = _profile(
            **{
                "cli-smoke": {
                    "required": True,
                    "commands": [{"name": "help", "command": "echo ok"}],
                },
                **overrides,
            }
        )
        profile: Path = tmp_path / QA.PROFILE_FILENAME
        profile.write_text(json.dumps({"qa": block}), encoding="utf-8")
        return profile

    def test_a_whole_run_passes_and_writes_its_verdict_to_the_record(self, tmp_path: Path) -> None:
        profile = self._fixture(tmp_path)
        block = QA.execute(
            issue=21,
            repo_root=tmp_path,
            store_root=tmp_path,
            profile_path=profile,
            runner=_runner(0, "ok"),
            environ={},
            widen=None,
        )
        assert block["verdict"] == QA.VERDICT_PASS
        assert block["route"] == QA.ROUTE_CLOSE
        raw = json.loads(RUN_RECORD.record_path(tmp_path, 21).read_text(encoding="utf-8"))
        assert raw["qa"]["verdict"] == QA.VERDICT_PASS
        assert len(raw["qa"]["envelopes"]) == 1

    def test_every_envelope_a_whole_run_writes_validates(self, tmp_path: Path) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(ENVELOPE_SCHEMA_FILE.read_text(encoding="utf-8"))
        profile = self._fixture(tmp_path, **{"app-ui": {"required": False}})
        block = QA.execute(
            issue=21,
            repo_root=tmp_path,
            store_root=tmp_path,
            profile_path=profile,
            runner=_runner(0, "ok"),
            environ={},
            widen=None,
        )
        assert block["envelopes"]
        for envelope in block["envelopes"]:
            jsonschema.validate(envelope, schema)

    def test_select_runs_no_driver(self, tmp_path: Path) -> None:
        run = _runner()
        profile = self._fixture(tmp_path)
        block = QA.execute(
            issue=21,
            repo_root=tmp_path,
            store_root=tmp_path,
            profile_path=profile,
            runner=run,
            environ={},
            widen=None,
            dry_run=True,
        )
        assert block["envelopes"] == []
        assert _driver_calls(run) == []
        assert block["verdict"] == "not-run"

    def test_a_failing_required_strategy_routes_to_the_build_loop(self, tmp_path: Path) -> None:
        profile = self._fixture(tmp_path)
        block = QA.execute(
            issue=21,
            repo_root=tmp_path,
            store_root=tmp_path,
            profile_path=profile,
            runner=_runner(1, "nope"),
            environ={},
            widen=None,
        )
        assert block["verdict"] == QA.VERDICT_FAIL
        assert block["route"] == QA.ROUTE_BUILD_LOOP

    def test_the_report_carries_the_selection_and_the_per_strategy_statuses(
        self, tmp_path: Path
    ) -> None:
        """Criterion 15's comment: the operator can see which checks ran."""
        profile = self._fixture(tmp_path)
        block = QA.execute(
            issue=21,
            repo_root=tmp_path,
            store_root=tmp_path,
            profile_path=profile,
            runner=_runner(0, "ok"),
            environ={},
            widen=None,
        )
        body = QA.report(block)
        assert "Functional test" in body
        assert "`cli-smoke`" in body
        assert "`passed`" in body
        assert QA.VERDICT_PASS in body


class TestCommandLine:
    def test_the_subcommands_are_select_run_and_verdict(self) -> None:
        parser = QA.build_parser()
        actions = [
            action for action in parser._actions if getattr(action, "choices", None) is not None
        ]
        names = set()
        for action in actions:
            if isinstance(action.choices, dict):
                names |= set(action.choices)
        assert {"select", "run", "verdict"} <= names

    def test_the_boundary_flag_defaults_to_non_production(self) -> None:
        args = QA.build_parser().parse_args(["run", "--issue", "1"])
        assert args.boundary == QA.DEFAULT_BOUNDARY

    def test_the_boundary_flag_accepts_only_the_ladders_rungs(self) -> None:
        with pytest.raises(SystemExit):
            QA.build_parser().parse_args(["run", "--issue", "1", "--boundary", "production"])

    def test_a_repository_with_no_profile_exits_refused(self, tmp_path: Path) -> None:
        RUN_RECORD.save(tmp_path, RUN_RECORD.RunRecord(issue=33, repo="o/r"))
        code = QA.main(
            [
                "run",
                "--issue",
                "33",
                "--repo-root",
                str(tmp_path),
                "--store-root",
                str(tmp_path),
            ]
        )
        assert code == QA.EXIT_REFUSED
