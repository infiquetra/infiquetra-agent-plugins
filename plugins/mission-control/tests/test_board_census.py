"""Tests for `board_census.py` -- the live-derived board schema census (#424, T9-F2-6).

`board-schema.json` intentionally records field/option SHAPE only (not item
counts, which mutate continuously as work moves through the board -- see
the module docstring in `board_census.py`). Full-item-pagination correctness
is proven separately by `count_project_items()`, exercised here directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import board_census  # noqa: E402
import sdlc_manager  # noqa: E402


def _fields_response(fields: list[dict]) -> dict:
    return {
        "organization": {
            "projectV2": {
                "id": "PVT_test",
                "title": "Test Project",
                "fields": {"nodes": fields},
            }
        }
    }


class TestFetchProjectFieldsCensus:
    def test_returns_sorted_field_and_option_shape(self, monkeypatch):
        def fake_graphql(query, variables):
            return _fields_response(
                [
                    {
                        "id": "F_status",
                        "name": "Status",
                        "dataType": "SINGLE_SELECT",
                        "options": [
                            {"id": "opt_b", "name": "Done"},
                            {"id": "opt_a", "name": "Active"},
                        ],
                    },
                    {"id": "F_assignees", "name": "Assignees", "dataType": "ASSIGNEES"},
                ]
            )

        monkeypatch.setattr(board_census, "_graphql", fake_graphql)
        census = board_census.fetch_project_fields_census(3)

        assert census["id"] == "PVT_test"
        assert census["number"] == 3
        names = [f["name"] for f in census["fields"]]
        assert names == sorted(names)
        status_field = next(f for f in census["fields"] if f["name"] == "Status")
        assert [o["name"] for o in status_field["options"]] == ["Active", "Done"]

    def test_over_thirty_fields_returns_full_census_not_truncated(self, monkeypatch):
        """A >30-field board across two mocked pages returns the FULL field
        shape in the census, not truncated at the first page (#584, R1)."""
        page_size = 30
        total_fields = 45

        def fake_graphql(query, variables):
            cursor = variables.get("cursor")
            start = 0 if cursor is None else int(cursor)
            end = min(start + page_size, total_fields)
            has_next = end < total_fields
            return {
                "organization": {
                    "projectV2": {
                        "id": "PVT_test",
                        "title": "Test Project",
                        "fields": {
                            "nodes": [
                                {"id": f"field_{i}", "name": f"Field_{i:02d}", "dataType": "TEXT"}
                                for i in range(start, end)
                            ],
                            "pageInfo": {
                                "hasNextPage": has_next,
                                "endCursor": str(end) if has_next else None,
                            },
                        },
                    }
                }
            }

        monkeypatch.setattr(board_census, "_graphql", fake_graphql)
        census = board_census.fetch_project_fields_census(3)
        assert len(census["fields"]) == total_fields
        assert census["fields"][0]["name"] == "Field_00"
        assert census["fields"][-1]["name"] == "Field_44"

    def test_runaway_fields_pagination_raises_instead_of_truncating(self, monkeypatch):
        def fake_graphql(query, variables):
            return {
                "organization": {
                    "projectV2": {
                        "id": "PVT_test",
                        "title": "Test Project",
                        "fields": {
                            "nodes": [{"id": "x", "name": "X", "dataType": "TEXT"}] * 30,
                            "pageInfo": {"hasNextPage": True, "endCursor": "always-more"},
                        },
                    }
                }
            }

        monkeypatch.setattr(board_census, "_graphql", fake_graphql)
        with pytest.raises(sdlc_manager.PaginationExhaustedError):
            board_census.fetch_project_fields_census(3, max_pages=2)


class TestCountProjectItems:
    def test_over_200_items_returns_full_count_not_truncated(self, monkeypatch):
        """A mocked live GraphQL response describing a project with more than
        200 items must return the FULL item count, not truncated at the
        first page (T9-F2-6, primary)."""
        page_size = 100
        total_items = 375

        def fake_graphql(query, variables):
            cursor = variables.get("cursor")
            start = 0 if cursor is None else int(cursor)
            end = min(start + page_size, total_items)
            has_next = end < total_items
            return {
                "organization": {
                    "projectV2": {
                        "id": "PVT_test",
                        "items": {
                            "nodes": [{"id": f"item-{i}"} for i in range(start, end)],
                            "pageInfo": {
                                "hasNextPage": has_next,
                                "endCursor": str(end) if has_next else None,
                            },
                        },
                    }
                }
            }

        monkeypatch.setattr(board_census, "_graphql", fake_graphql)
        count = board_census.count_project_items(3)
        assert count == total_items
        assert count > 200

    def test_runaway_pagination_raises_instead_of_truncating(self, monkeypatch):
        def fake_graphql(query, variables):
            return {
                "organization": {
                    "projectV2": {
                        "id": "PVT_test",
                        "items": {
                            "nodes": [{"id": "x"}] * 100,
                            "pageInfo": {"hasNextPage": True, "endCursor": "always-more"},
                        },
                    }
                }
            }

        monkeypatch.setattr(board_census, "_graphql", fake_graphql)
        with pytest.raises(sdlc_manager.PaginationExhaustedError):
            board_census.count_project_items(3, max_pages=2)


class TestDeriveCensus:
    def test_derive_census_covers_every_tracked_project(self, monkeypatch):
        def fake_fields_census(project_number):
            return {"number": project_number, "id": f"PVT_{project_number}", "fields": []}

        monkeypatch.setattr(board_census, "fetch_project_fields_census", fake_fields_census)
        projects = {
            "operations": {"number": 3},
            "asgard": {"number": 2},
        }
        census = board_census.derive_census(projects)
        assert set(census["boards"]) == {"operations", "asgard"}
        assert census["boards"]["operations"]["number"] == 3


class TestCmdCheck:
    def test_check_passes_when_committed_matches_live(self, tmp_path, monkeypatch):
        schema_path = tmp_path / "board-schema.json"
        census = {"boards": {"operations": {"number": 3, "id": "PVT_3", "fields": []}}}
        schema_path.write_text(json.dumps(census))

        monkeypatch.setattr(board_census, "SCHEMA_PATH", schema_path)
        monkeypatch.setattr(
            board_census, "_tracked_projects", lambda: {"operations": {"number": 3}}
        )
        monkeypatch.setattr(board_census, "derive_census", lambda projects: census)

        assert board_census.cmd_check() == 0

    def test_mutated_snapshot_fails_check(self, tmp_path, monkeypatch):
        """A CI run against a mutated committed board-schema.json snapshot
        must fail the `--check` diff step (T9-F2-6, primary)."""
        schema_path = tmp_path / "board-schema.json"
        fresh_census = {
            "boards": {"operations": {"number": 3, "id": "PVT_3", "fields": [{"name": "Status"}]}}
        }
        # Committed snapshot has drifted: a mutated field name.
        mutated_committed = {
            "boards": {
                "operations": {"number": 3, "id": "PVT_3", "fields": [{"name": "OldStatusName"}]}
            }
        }
        schema_path.write_text(json.dumps(mutated_committed))

        monkeypatch.setattr(board_census, "SCHEMA_PATH", schema_path)
        monkeypatch.setattr(
            board_census, "_tracked_projects", lambda: {"operations": {"number": 3}}
        )
        monkeypatch.setattr(board_census, "derive_census", lambda projects: fresh_census)

        assert board_census.cmd_check() == 1

    def test_check_fails_when_schema_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(board_census, "SCHEMA_PATH", tmp_path / "does-not-exist.json")
        assert board_census.cmd_check() == 1

    def test_check_skips_not_passes_when_live_unavailable(self, tmp_path, monkeypatch):
        """Live derivation failing (offline/no auth) is an explicit SKIP
        (exit 0, printed), mirroring the parity gate's `--live` leg -- never
        a silent pass folded indistinguishably into "in sync"."""
        schema_path = tmp_path / "board-schema.json"
        schema_path.write_text(json.dumps({"boards": {}}))

        def raise_offline(projects):
            raise sdlc_manager.GhApiError("no network")

        monkeypatch.setattr(board_census, "SCHEMA_PATH", schema_path)
        monkeypatch.setattr(
            board_census, "_tracked_projects", lambda: {"operations": {"number": 3}}
        )
        monkeypatch.setattr(board_census, "derive_census", raise_offline)

        assert board_census.cmd_check() == 0

    def test_write_regenerates_schema_file(self, tmp_path, monkeypatch):
        schema_path = tmp_path / "board-schema.json"
        census = {"boards": {"operations": {"number": 3, "id": "PVT_3", "fields": []}}}

        monkeypatch.setattr(board_census, "SCHEMA_PATH", schema_path)
        monkeypatch.setattr(
            board_census, "_tracked_projects", lambda: {"operations": {"number": 3}}
        )
        monkeypatch.setattr(board_census, "derive_census", lambda projects: census)

        assert board_census.cmd_write() == 0
        assert json.loads(schema_path.read_text()) == census
