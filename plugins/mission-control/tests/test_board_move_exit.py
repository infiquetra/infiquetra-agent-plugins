"""Fail-loud tests for mission-control ``board move`` (#609)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

PROJECT = {"number": 3, "name": "Operations", "id": "PVT_operations"}
SECOND_PROJECT = {"number": 2, "name": "Asgard", "id": "PVT_asgard"}
ITEM = {
    "id": "PVTI_item",
    "content": {"number": 609, "repository": {"name": "demo-repo"}},
}


def _fields(*options: str) -> dict:
    return {
        "organization": {
            "projectV2": {
                "fields": {
                    "nodes": [
                        {
                            "id": "PVTSSF_status",
                            "name": "Status",
                            "options": [
                                {"id": f"option-{index}", "name": name}
                                for index, name in enumerate(options)
                            ],
                        }
                    ]
                }
            }
        }
    }


def _run_move(
    *,
    items: list[dict] | None = None,
    graphql: object,
    status: str = "Active",
) -> tuple[bool, MagicMock]:
    with (
        patch.object(sdlc_manager, "load_config", return_value={}),
        patch.object(sdlc_manager, "get_projects_for_repo", return_value=[PROJECT]),
        patch.object(
            sdlc_manager,
            "get_project_items",
            return_value=(PROJECT["id"], [ITEM] if items is None else items),
        ),
        patch.object(sdlc_manager, "_graphql", side_effect=graphql) as mock_graphql,
    ):
        result = sdlc_manager.board_move("demo-repo", 609, status, "text")
    return result, mock_graphql


def test_board_move_success_returns_true() -> None:
    result, mock_graphql = _run_move(graphql=[_fields("Active"), {}])

    assert result is True
    assert mock_graphql.call_args_list == [
        call(
            sdlc_manager.QUERY_GET_PROJECT_FIELDS,
            {"org": sdlc_manager.ORG, "number": PROJECT["number"], "cursor": None},
        ),
        call(
            sdlc_manager.QUERY_SET_FIELD_VALUE,
            {
                "projectId": PROJECT["id"],
                "itemId": ITEM["id"],
                "fieldId": "PVTSSF_status",
                "optionId": "option-0",
            },
        ),
    ]


def test_unavailable_status_returns_false_lists_options_and_does_not_mutate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, mock_graphql = _run_move(graphql=[_fields("Idea", "Active")], status="Unavailable")

    assert result is False
    output = capsys.readouterr().out
    assert "Status 'Unavailable' not found" in output
    assert "Available: Idea, Active" in output
    assert len(mock_graphql.call_args_list) == 1


def test_missing_item_and_status_field_return_false(
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_item, item_graphql = _run_move(items=[], graphql=[])
    item_output = capsys.readouterr().out

    missing_field, field_graphql = _run_move(graphql=[{"organization": {}}])
    field_output = capsys.readouterr().out

    assert missing_item is False
    assert "not found" in item_output
    assert item_graphql.call_count == 0
    assert missing_field is False
    assert "No Status field" in field_output
    assert field_graphql.call_count == 1


def test_mutation_failure_returns_false_after_reporting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, mock_graphql = _run_move(graphql=[_fields("Active"), RuntimeError("mutation failed")])

    assert result is False
    assert "Failed to move: mutation failed" in capsys.readouterr().out
    assert mock_graphql.call_count == 2


def test_board_move_reports_later_projects_after_an_earlier_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(sdlc_manager, "load_config", return_value={}),
        patch.object(
            sdlc_manager,
            "get_projects_for_repo",
            return_value=[PROJECT, SECOND_PROJECT],
        ),
        patch.object(
            sdlc_manager,
            "get_project_items",
            side_effect=[
                (PROJECT["id"], [ITEM]),
                (SECOND_PROJECT["id"], [ITEM]),
            ],
        ),
        patch.object(
            sdlc_manager,
            "_graphql",
            side_effect=[_fields("Idea"), _fields("Active"), {}],
        ) as mock_graphql,
    ):
        result = sdlc_manager.board_move("demo-repo", 609, "Active", "text")

    output = capsys.readouterr().out
    assert result is False
    assert "Status 'Active' not found" in output
    assert "Moved demo-repo#609 to 'Active' in 'Asgard'" in output
    assert mock_graphql.call_args_list[-1] == call(
        sdlc_manager.QUERY_SET_FIELD_VALUE,
        {
            "projectId": SECOND_PROJECT["id"],
            "itemId": ITEM["id"],
            "fieldId": "PVTSSF_status",
            "optionId": "option-0",
        },
    )


def test_cli_exits_one_only_after_board_move_reports_failure() -> None:
    argv = [
        "sdlc_manager.py",
        "board",
        "move",
        "--project",
        "operations",
        "--repo",
        "demo-repo",
        "--number",
        "609",
        "--status",
        "Unavailable",
    ]
    with (
        patch.object(sys, "argv", argv),
        patch.object(sdlc_manager, "board_move", return_value=False) as move,
        pytest.raises(SystemExit) as exc_info,
    ):
        sdlc_manager.main()

    assert exc_info.value.code == 1
    move.assert_called_once_with("demo-repo", 609, "Unavailable", "text", project_name="operations")
