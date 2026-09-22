"""Tests for project-mappings.json resolution order.

The plugin resolves project_mappings via three steps:
  1. External override:  $INFIQUETRA_SDLC_PATH/config/project-mappings.json
  2. Vendored canonical: <plugin>/config/project-mappings.json
  3. Remote `gh api` fallback (reads infiquetra-sdlc raw from GitHub)

These tests pin each branch using `monkeypatch.setattr` on the module's
_VENDORED_PROJECT_MAPPINGS_PATH constant — no renaming the real vendored
file (which would be racy under pytest-xdist + leave orphans on crash).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


@pytest.fixture
def fake_vendored_path(tmp_path, monkeypatch):
    """Redirect _VENDORED_PROJECT_MAPPINGS_PATH to a tmp dir. Caller controls
    whether the file exists (write to fake_path to make it exist)."""
    fake_path = tmp_path / "vendored-project-mappings.json"
    monkeypatch.setattr(sdlc_manager, "_VENDORED_PROJECT_MAPPINGS_PATH", fake_path)
    return fake_path


@pytest.fixture
def fake_schema_path(tmp_path, monkeypatch):
    fake_path = tmp_path / "vendored-sdlc-schema.json"
    monkeypatch.setattr(sdlc_manager, "_VENDORED_SDLC_SCHEMA_PATH", fake_path)
    return fake_path


def test_external_override_wins_over_vendored(tmp_path, fake_vendored_path) -> None:
    """If $INFIQUETRA_SDLC_PATH/config/project-mappings.json exists, it
    takes precedence over the vendored copy. This lets a developer test
    against a custom project layout without modifying the plugin."""
    # Set up an override file
    sdlc_path = tmp_path / "infiquetra-sdlc"
    cfg_dir = sdlc_path / "config"
    cfg_dir.mkdir(parents=True)
    override_data = {
        "organization": "infiquetra",
        "projects": {"override-project": {"number": 99, "name": "Override"}},
    }
    (cfg_dir / "project-mappings.json").write_text(json.dumps(override_data))

    # Also write a different vendored — to prove override wins
    fake_vendored_path.write_text(json.dumps({"projects": {"vendored": {"number": 1}}}))

    result = sdlc_manager._resolve_project_mappings(sdlc_path)
    assert result == override_data


def test_vendored_used_when_no_override(tmp_path, fake_vendored_path) -> None:
    """Override missing → fall through to vendored. We control the
    vendored content via the fixture so the test is hermetic."""
    no_override_path = tmp_path / "nonexistent-sdlc"
    fake_vendored_path.write_text(
        json.dumps(
            {
                "organization": "infiquetra",
                "projects": {"vendored-project": {"number": 1}},
            }
        )
    )

    result = sdlc_manager._resolve_project_mappings(no_override_path)
    assert "vendored-project" in result["projects"]


def test_remote_fallback_when_neither_exists(tmp_path, fake_vendored_path) -> None:
    """If both override and vendored are missing, fall back to `gh api`.
    Mock `_gh` to verify the API call + simulate a base64 response."""
    import base64

    fake_payload = json.dumps({"projects": {"remote": {"number": 5}}})
    fake_b64 = base64.b64encode(fake_payload.encode()).decode()

    no_override_path = tmp_path / "nonexistent-sdlc"
    # fake_vendored_path is a tmp path that doesn't exist (we never wrote to it)
    assert not fake_vendored_path.exists()

    with patch.object(sdlc_manager, "_gh", return_value=fake_b64):
        result = sdlc_manager._resolve_project_mappings(no_override_path)
    assert result == {"projects": {"remote": {"number": 5}}}


def test_returns_empty_dict_when_all_three_fail(tmp_path, fake_vendored_path) -> None:
    """If override missing, vendored missing, AND remote `gh api` raises,
    we return {} rather than crashing — caller handles empty config."""
    no_override_path = tmp_path / "nonexistent-sdlc"
    assert not fake_vendored_path.exists()

    with patch.object(
        sdlc_manager,
        "_gh",
        side_effect=sdlc_manager.GhApiError("simulated failure"),
    ):
        result = sdlc_manager._resolve_project_mappings(no_override_path)
    assert result == {}


def test_vendored_project_mappings_has_expected_canonical_state() -> None:
    """The vendored project-mappings.json must declare the canonical
    org-wide state: the ACTIVE boards are Operations (#3), Asgard (#2),
    and CAMPPS (#4). Mount Olympus (former project #1) was retired
    2026-06-17 and removed from active routing, so it must NOT appear as a
    project. No board carries a repo-based default routing list (KTD17 —
    board commands require an explicit --project), so every `repositories`
    list is empty. If this test fails, either the vendored file was edited
    or the org's active board set has drifted — both are events the
    operator should know about.

    NOTE: This test reads the REAL vendored file (not the fixture) — it's
    the canonical-state guard, not a hermetic unit test."""
    vendored = sdlc_manager._VENDORED_PROJECT_MAPPINGS_PATH
    assert vendored.exists(), f"Vendored file missing at {vendored}"
    data = json.loads(vendored.read_text())
    assert data["organization"] == "infiquetra"
    # Olympus is retired and must not be an active routing target.
    assert "mount-olympus" not in data["projects"]
    assert "operations" in data["projects"]
    assert "asgard" in data["projects"]
    assert "campps" in data["projects"]
    assert data["projects"]["operations"]["number"] == 3
    assert data["projects"]["asgard"]["number"] == 2
    assert data["projects"]["campps"]["number"] == 4

    # No repo-based default routing (KTD17): every board's repositories list
    # is empty so work is never silently routed to a board.
    for key, proj in data["projects"].items():
        assert proj.get("repositories", []) == [], (
            f"Project {key!r} carries repo-based default routing; "
            f"KTD17 removed default routing (lists must be empty)."
        )


def test_sdlc_schema_remote_main_wins_over_local_and_vendored(tmp_path, fake_schema_path) -> None:
    import base64

    sdlc_path = tmp_path / "infiquetra-sdlc"
    cfg_dir = sdlc_path / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "sdlc-schema.json").write_text(
        json.dumps({"schema_version": "local-stale", "workflows": {}})
    )
    fake_schema_path.write_text(json.dumps({"schema_version": "vendored"}))
    remote_data = {"schema_version": "remote-main", "workflows": {}}
    fake_b64 = base64.b64encode(json.dumps(remote_data).encode()).decode()

    with patch.object(sdlc_manager, "_gh", return_value=fake_b64) as gh:
        result = sdlc_manager._resolve_sdlc_schema(sdlc_path)

    assert result == remote_data
    gh.assert_called_once()
    assert "sdlc-schema.json?ref=main" in gh.call_args.args[0][1]


def test_sdlc_schema_vendored_used_when_remote_unavailable(tmp_path, fake_schema_path) -> None:
    fake_schema_path.write_text(
        json.dumps({"schema_version": "vendored", "workflows": {"intent_flow": {}}})
    )

    with patch.object(
        sdlc_manager,
        "_gh",
        side_effect=sdlc_manager.GhApiError("simulated failure"),
    ):
        result = sdlc_manager._resolve_sdlc_schema(tmp_path / "missing-sdlc")

    assert result["schema_version"] == "vendored"


def test_sdlc_schema_vendored_used_when_remote_result_is_garbage(
    tmp_path, fake_schema_path
) -> None:
    """W10 repair: a gh result that exists but won't decode/parse (a stubbed
    runner returning a URL, a truncated body) must degrade to the vendored copy,
    not escape as UnicodeDecodeError/JSONDecodeError."""
    fake_schema_path.write_text(json.dumps({"schema_version": "vendored", "workflows": {}}))

    with patch.object(sdlc_manager, "_gh", return_value="https://not-base64.example"):
        result = sdlc_manager._resolve_sdlc_schema(tmp_path / "missing-sdlc")

    assert result["schema_version"] == "vendored"


def test_sdlc_schema_local_used_only_when_remote_and_vendored_unavailable(
    tmp_path, fake_schema_path
) -> None:
    sdlc_path = tmp_path / "infiquetra-sdlc"
    cfg_dir = sdlc_path / "config"
    cfg_dir.mkdir(parents=True)
    local_data = {"schema_version": "local-last-resort", "workflows": {}}
    (cfg_dir / "sdlc-schema.json").write_text(json.dumps(local_data))
    assert not fake_schema_path.exists()

    with patch.object(
        sdlc_manager,
        "_gh",
        side_effect=sdlc_manager.GhApiError("simulated failure"),
    ):
        result = sdlc_manager._resolve_sdlc_schema(sdlc_path)

    assert result == local_data


def test_vendored_sdlc_schema_declares_current_live_boards() -> None:
    vendored = sdlc_manager._VENDORED_SDLC_SCHEMA_PATH
    assert vendored.exists(), f"Vendored schema missing at {vendored}"
    data = json.loads(vendored.read_text())

    assert data["boards"]["operations"]["status"] == "active"
    assert data["boards"]["operations"]["live_creation"] == "created_2026-05-29_project_3"
    assert data["boards"]["asgard"]["status"] == "active"
    assert data["boards"]["asgard"]["live_creation"] == "created_2026-05-29_project_2"
    assert data["workflows"]["stage_flow"]["stages"] == [
        "Intake",
        "Shaping",
        "Planning",
        "Active",
        "Verify",
        "Retro",
    ]


def test_schema_backed_status_order_includes_live_olympus_in_progress() -> None:
    config = {
        "sdlc_schema": {
            "boards": {"olympus": {"workflow": "olympus_execution"}},
            "workflows": {
                "olympus_execution": {
                    "statuses": [
                        "Backlog",
                        "Ready",
                        "Planning",
                        "Assigned",
                        "In Review",
                        "Done",
                        "Closed",
                    ],
                    "pause_states": ["Blocked"],
                }
            },
        }
    }
    proj = {"board_key": "olympus", "workflow": "olympus_execution"}

    order = sdlc_manager._status_order(config, "mount-olympus", proj)

    assert order.index("Assigned") < order.index("In Progress") < order.index("In Review")
    assert "Blocked" in order


def test_legacy_status_hint_points_to_current_status() -> None:
    hint = sdlc_manager._legacy_status_hint("E2E Testing", ["Assigned", "In Review", "Done"])

    assert hint == "'E2E Testing' is legacy; use 'In Review' on this board."


class TestVendoredMappingsDoNotOverrideTheBoardWorkflow:
    """The vendored mappings must not name a workflow at all (#1020 U5).

    These tests read the REAL vendored file on purpose. `load_config()` prefers
    an external `$INFIQUETRA_SDLC_PATH` checkout, which on a developer machine
    is current and masks this defect completely -- a test written against
    `load_config()` would have passed before the fix and proved nothing. The
    rung that ships is the vendored one, so that is the rung under test.
    """

    @staticmethod
    def _vendored_projects() -> dict:
        path = Path(__file__).resolve().parent.parent / "config" / "project-mappings.json"
        loaded: dict = json.loads(path.read_text(encoding="utf-8"))
        projects: dict = loaded["projects"]
        return projects

    @staticmethod
    def _schema() -> dict:
        path = Path(__file__).resolve().parent.parent / "config" / "sdlc-schema.json"
        schema: dict = json.loads(path.read_text(encoding="utf-8"))
        return schema

    def test_no_vendored_mapping_pins_a_workflow(self) -> None:
        """A mapping that duplicates a name the schema owns can outlive the
        name. Let each board declare its own workflow instead."""
        for name, proj in self._vendored_projects().items():
            assert "workflow" not in proj, (
                f"{name} pins workflow {proj.get('workflow')!r}; let sdlc-schema.json's "
                "board declaration decide, so the two cannot drift apart"
            )

    def test_every_vendored_project_resolves_to_stage_flow(self) -> None:
        schema = self._schema()
        for name, proj in self._vendored_projects().items():
            resolved = sdlc_manager._project_workflow_name(schema, name, proj)
            assert resolved == "stage_flow", f"{name} resolves to {resolved!r}, not stage_flow"

    def test_vendored_status_order_is_the_live_stage_flow_vocabulary(self) -> None:
        """Before the fix this returned ['No Status'] for operations and asgard
        (intent_flow is undefined) and the retired Idea/Committed/... ladder for
        campps (campps_initiative is defined but retired_historical)."""
        schema = self._schema()
        config = {"sdlc_schema": schema}
        for name, proj in self._vendored_projects().items():
            order = sdlc_manager._status_order(config, name, proj)
            assert "Capturing" in order, f"{name}: stage_flow entry status missing from order"
            assert "Ready to close" in order, f"{name}: terminal status missing from order"
            for retired in ("Idea", "Ready", "Active", "Done", "Committed", "Parked"):
                assert retired not in order, f"{name}: retired status {retired!r} still ordered"
