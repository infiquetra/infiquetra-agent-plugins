"""Tests for the shared `paginate_or_raise` / `_rest_list_paginated` helpers (#424, T9-F1-7).

A truncated list read silently treated as "the whole list" is the fleet
defect pattern named in docs/plans/2026-07-03-plugin-fleet-grounding-brief.md
§7 pattern 3 (item-list pagination silently truncating at 200 of 375 items).
These tests prove the shared helper raises rather than returning a partial
page when a paginated fetch never reaches a real terminal signal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


class TestPaginateOrRaise:
    def test_single_page_terminates_immediately(self):
        """`next_token is None` on the first call returns exactly that page."""

        def fetch_page(token):
            assert token is None
            return (["a", "b", "c"], None)

        assert sdlc_manager.paginate_or_raise(fetch_page) == ["a", "b", "c"]

    def test_multi_page_accumulates_until_terminal_signal(self):
        """Three pages of 100 mocked items, terminating on the third."""
        pages = {
            None: (list(range(0, 100)), "cursor-1"),
            "cursor-1": (list(range(100, 200)), "cursor-2"),
            "cursor-2": (list(range(200, 250)), None),
        }

        def fetch_page(token):
            return pages[token]

        items = sdlc_manager.paginate_or_raise(fetch_page)
        assert len(items) == 250
        assert items == list(range(0, 250))

    def test_raises_on_truncation(self):
        """A mocked response describing more than 100 items with a next_token
        that never resolves to None must raise, not silently return the
        single fetched page (T9-F1-7)."""
        call_count = {"n": 0}

        def fetch_page(token):
            call_count["n"] += 1
            # Always reports "there's more" -- a misbehaving/runaway upstream.
            return (list(range(150)), "always-more")

        with pytest.raises(sdlc_manager.PaginationExhaustedError, match="did not terminate"):
            sdlc_manager.paginate_or_raise(fetch_page, max_pages=3)

        assert call_count["n"] == 3

    def test_raises_is_a_runtime_error_subclass(self):
        assert issubclass(sdlc_manager.PaginationExhaustedError, RuntimeError)


class TestRestListPaginated:
    def test_short_final_page_terminates(self, monkeypatch):
        """A page shorter than `per_page` is the REST terminal signal."""
        pages = {
            1: [{"id": i} for i in range(100)],
            2: [{"id": i} for i in range(100, 150)],
        }

        def fake_rest_get(path):
            page_num = int(path.rsplit("page=", 1)[1])
            return pages[page_num]

        monkeypatch.setattr(sdlc_manager, "_rest_get", fake_rest_get)
        result = sdlc_manager._rest_list_paginated("/repos/infiquetra/foo/labels")
        assert len(result) == 150

    def test_raises_when_every_page_is_full(self, monkeypatch):
        """Every page returned is exactly `per_page` items -- looks like it
        might never stop -- must raise rather than truncate silently."""

        def fake_rest_get(path):
            return [{"id": i} for i in range(100)]

        monkeypatch.setattr(sdlc_manager, "_rest_get", fake_rest_get)
        with pytest.raises(sdlc_manager.PaginationExhaustedError):
            sdlc_manager._rest_list_paginated(
                "/repos/infiquetra/foo/labels", per_page=100, max_pages=3
            )

    def test_non_list_response_raises_runtime_error(self, monkeypatch):
        monkeypatch.setattr(sdlc_manager, "_rest_get", lambda path: {"not": "a list"})
        with pytest.raises(RuntimeError, match="expected a JSON array"):
            sdlc_manager._rest_list_paginated("/repos/infiquetra/foo/labels")


class TestGetProjectItemsUsesSharedHelper:
    def test_get_project_items_raises_on_runaway_pagination(self, monkeypatch):
        """`get_project_items` must route through `paginate_or_raise` -- a
        GraphQL response that always claims `hasNextPage: true` raises
        instead of this function returning a partial item list."""

        def fake_graphql(query, variables):
            return {
                "organization": {
                    "projectV2": {
                        "id": "PVT_test",
                        "items": {
                            "nodes": [{"id": "item"}] * 100,
                            "pageInfo": {"hasNextPage": True, "endCursor": "always-more"},
                        },
                    }
                }
            }

        monkeypatch.setattr(sdlc_manager, "_graphql", fake_graphql)
        original_paginate = sdlc_manager.paginate_or_raise
        monkeypatch.setattr(
            sdlc_manager,
            "paginate_or_raise",
            lambda fetch_page, **kwargs: original_paginate(fetch_page, max_pages=2),
        )
        with pytest.raises(sdlc_manager.PaginationExhaustedError):
            sdlc_manager.get_project_items(1)

    def test_get_project_items_paginates_past_a_single_page(self, monkeypatch):
        """A >100-item board across two mocked pages returns the FULL item
        count, not truncated at the first page."""
        page_1 = {
            "organization": {
                "projectV2": {
                    "id": "PVT_test",
                    "items": {
                        "nodes": [{"id": f"item-{i}"} for i in range(100)],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                    },
                }
            }
        }
        page_2 = {
            "organization": {
                "projectV2": {
                    "id": "PVT_test",
                    "items": {
                        "nodes": [{"id": f"item-{i}"} for i in range(100, 250)],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    },
                }
            }
        }

        def fake_graphql(query, variables):
            return page_2 if variables.get("cursor") == "cursor-1" else page_1

        monkeypatch.setattr(sdlc_manager, "_graphql", fake_graphql)
        project_id, items = sdlc_manager.get_project_items(1)
        assert project_id == "PVT_test"
        assert len(items) == 250


class TestGetProjectFieldsUsesSharedHelper:
    def test_get_project_fields_raises_on_runaway_pagination(self, monkeypatch):
        """`get_project_fields` must route through `paginate_or_raise` -- a
        GraphQL response that always claims `hasNextPage: True` raises
        instead of silently truncating (#584, R1)."""

        def fake_graphql(query, variables):
            return {
                "organization": {
                    "projectV2": {
                        "id": "PVT_test",
                        "fields": {
                            "nodes": [
                                {"id": f"field-{i}", "name": f"Field {i}"} for i in range(30)
                            ],
                            "pageInfo": {"hasNextPage": True, "endCursor": "always-more"},
                        },
                    }
                }
            }

        monkeypatch.setattr(sdlc_manager, "_graphql", fake_graphql)
        original_paginate = sdlc_manager.paginate_or_raise
        monkeypatch.setattr(
            sdlc_manager,
            "paginate_or_raise",
            lambda fetch_page, **kwargs: original_paginate(fetch_page, max_pages=2),
        )
        with pytest.raises(sdlc_manager.PaginationExhaustedError):
            sdlc_manager.get_project_fields(1)

    def test_get_project_fields_paginates_past_thirty_fields(self, monkeypatch):
        """A >30-field board across two mocked pages returns the FULL field
        count, not truncated at the first page (#584, R1)."""
        page_1 = {
            "organization": {
                "projectV2": {
                    "id": "PVT_test",
                    "fields": {
                        "nodes": [{"id": f"field-{i}", "name": f"Field {i}"} for i in range(30)],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                    },
                }
            }
        }
        page_2 = {
            "organization": {
                "projectV2": {
                    "id": "PVT_test",
                    "fields": {
                        "nodes": [
                            {"id": f"field-{i}", "name": f"Field {i}"} for i in range(30, 45)
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    },
                }
            }
        }

        def fake_graphql(query, variables):
            return page_2 if variables.get("cursor") == "cursor-1" else page_1

        monkeypatch.setattr(sdlc_manager, "_graphql", fake_graphql)
        project_id, fields = sdlc_manager.get_project_fields(1)
        assert project_id == "PVT_test"
        assert len(fields) == 45
