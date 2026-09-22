#!/usr/bin/env python3
"""Live-derived board schema census (#424, T9-F2-6).

Mirrors the context-library's ``context_census.py`` pattern, applied to
GitHub Projects v2 boards: derive a schema census from the LIVE GraphQL
API and commit it as ``config/board-schema.json``. A CI ``--check`` step
re-derives the census live and fails on any drift, so a renamed/removed
field or option always produces a reviewable diff instead of silent
staleness. ``config/sdlc-schema.json`` itself documents the underlying gap
this closes: "This file intentionally contains no live GitHub Projects
field option IDs; tooling must resolve those from GitHub at runtime" — but
until this script, nothing asserted that resolution ever ran or ever
drifted.

Census scope is field/option SHAPE only (id, name, dataType, options) for
each tracked project in ``project-mappings.json`` — deliberately NOT item
counts or item content, which mutate continuously as work moves through
the board and would make the committed snapshot churn on every card move.
Full-item-pagination correctness (never silently truncating at the first
page on a >200-item board) is proven independently by
``count_project_items()``, which routes through the same shared
``paginate_or_raise`` helper (``sdlc_manager.py``) used by
``get_project_items()`` — its own tests assert the full count is returned,
not truncated at a single page.

``fields`` is a mapping keyed by field name, so a consumer can ask for one
field directly (``.boards.operations.fields.Status.options[].name``) instead
of scanning a list. Keys are emitted in sorted order and ``--write``
serializes with ``sort_keys=True``, so the committed file still diffs
stably; a duplicate field name raises rather than overwriting (#1020).

Usage::

    python3 board_census.py --write   # regenerate config/board-schema.json
    python3 board_census.py --check   # fail if committed census has drifted
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sdlc_manager import (  # noqa: E402
    ORG,
    QUERY_GET_PROJECT_FIELDS,
    QUERY_GET_PROJECT_ITEMS,
    GhApiError,
    PaginationExhaustedError,
    _graphql,
    load_config,
    paginate_or_raise,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "config" / "board-schema.json"


class DuplicateFieldNameError(ValueError):
    """Two fields on one board share a name, so the name-keyed census cannot
    represent the board without losing one (#1020).

    A distinct type, not a bare ``ValueError``, because callers must be able to
    separate this from an access failure. ``sdlc_manager._graphql`` parses the
    ``gh`` response with ``json.loads``, and ``json.JSONDecodeError`` is itself
    a ``ValueError`` -- so a handler written against the bare type would turn a
    non-JSON response from a failing live call into a hard failure where the
    documented posture is a SKIP. Kept in the ``ValueError`` hierarchy so
    existing broad handlers still behave sensibly.
    """


def fetch_project_fields_census(project_number: int, *, max_pages: int = 200) -> dict[str, Any]:
    """Live field/option shape for one project (id, name, dataType, options).

    Deliberately excludes item data — see module docstring."""
    project_id_box: dict[str, str] = {"id": "", "title": ""}

    def _fetch_page(cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        data = _graphql(
            QUERY_GET_PROJECT_FIELDS,
            {"org": ORG, "number": project_number, "cursor": cursor},
        )
        proj = data.get("organization", {}).get("projectV2") or {}
        if not project_id_box["id"]:
            project_id_box["id"] = proj.get("id", "")
            project_id_box["title"] = proj.get("title", "")

        fields_data = proj.get("fields", {})
        page_info = fields_data.get("pageInfo", {})
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None
        return fields_data.get("nodes", []), next_cursor

    fields = paginate_or_raise(_fetch_page, max_pages=max_pages)

    census_fields: dict[str, dict[str, Any]] = {}
    for field in fields:
        name = field.get("name", "")
        if name in census_fields:
            # A mapping keyed by name can silently lose a field that a list
            # cannot. GitHub project field names are unique in practice, so
            # this never fires -- but drop loudly rather than quietly if it
            # ever does (#1020 KTD2). Raised here, AFTER `paginate_or_raise`
            # has had its chance, so a runaway-pagination fixture whose pages
            # repeat one field name still reports the pagination fault.
            raise DuplicateFieldNameError(
                f"duplicate field name {name!r} in project {project_number} census; "
                "the census keys fields by name and cannot represent this board"
            )
        entry: dict[str, Any] = {
            "name": name,
            "id": field.get("id", ""),
            "dataType": field.get("dataType", ""),
        }
        if "options" in field:
            entry["options"] = sorted(
                ({"id": o["id"], "name": o["name"]} for o in field.get("options", [])),
                key=lambda o: str(o.get("name", "")),
            )
        census_fields[name] = entry

    return {
        "number": project_number,
        "id": project_id_box["id"],
        "title": project_id_box["title"],
        "fields": {name: census_fields[name] for name in sorted(census_fields)},
    }


def count_project_items(project_number: int, *, max_pages: int = 200) -> int:
    """Full live item count for one project via `paginate_or_raise`.

    Proves the underlying fetch never silently truncates at the first page
    of a board with more than one page of items (T9-F2-6)."""

    def _fetch_page(cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        data = _graphql(
            QUERY_GET_PROJECT_ITEMS,
            {"org": ORG, "number": project_number, "cursor": cursor},
        )
        items_data = data.get("organization", {}).get("projectV2", {}).get("items", {})
        page_info = items_data.get("pageInfo", {})
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None
        return items_data.get("nodes", []), next_cursor

    items = paginate_or_raise(_fetch_page, max_pages=max_pages)
    return len(items)


def derive_census(projects: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Derive the full board census across every tracked project."""
    return {
        "boards": {
            name: fetch_project_fields_census(proj["number"])
            for name, proj in sorted(projects.items())
        }
    }


def _tracked_projects() -> dict[str, dict[str, Any]]:
    config = load_config()
    return cast(dict[str, dict[str, Any]], config.get("project_mappings", {}).get("projects", {}))


def cmd_write() -> int:
    census = derive_census(_tracked_projects())
    SCHEMA_PATH.write_text(json.dumps(census, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {SCHEMA_PATH}")
    return 0


def cmd_check() -> int:
    if not SCHEMA_PATH.exists():
        print(f"FAIL board-schema.json missing at {SCHEMA_PATH}")
        return 1

    committed = json.loads(SCHEMA_PATH.read_text())

    try:
        fresh = derive_census(_tracked_projects())
    except PaginationExhaustedError as exc:
        print(f"FAIL board census pagination did not terminate: {exc}")
        return 1
    except DuplicateFieldNameError as exc:
        # A board carries two fields with one name, so the census cannot
        # represent it. A real defect on the board, not an access failure:
        # report it in this script's own FAIL convention rather than letting
        # it surface as a traceback. Caught by its own type, never as a bare
        # `ValueError`, so a `json.JSONDecodeError` from a failing live call
        # is not misreported as a malformed board.
        print(f"FAIL board census is not representable: {exc}")
        return 1
    except (GhApiError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        # Live GitHub Projects access is unavailable (no auth/network in this
        # environment, e.g. a CI runner with no Projects-scoped token) — a
        # SKIP, printed explicitly, never a silent pass. `json.JSONDecodeError`
        # is named explicitly: `_graphql` parses `gh` stdout after a zero exit,
        # so a truncated or non-JSON body lands here, and it subclasses
        # `ValueError` rather than `RuntimeError`, so the tuple above would
        # otherwise miss it and the failure would surface as a traceback.
        # Mirrors the
        # `--live`-gated skip posture of check_issue_contract_parity.py's
        # third leg for the same reason (#424 T14-F5-3).
        print(f"SKIPPED board-schema.json --check: live derivation unavailable ({exc})")
        return 0

    if committed != fresh:
        print("FAIL board-schema.json has drifted from the live board schema.")
        print("Re-run `python3 board_census.py --write` and commit the diff.")
        return 1

    print("board-schema.json census check passed: committed census matches live schema.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="regenerate board-schema.json")
    group.add_argument("--check", action="store_true", help="fail if the census has drifted")
    args = parser.parse_args()
    return cmd_write() if args.write else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
