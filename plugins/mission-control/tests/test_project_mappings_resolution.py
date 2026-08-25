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
    assert data["workflows"]["intent_flow"]["statuses"] == [
        "Idea",
        "Shaping",
        "Ready",
        "Active",
        "Verify",
        "Done",
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
