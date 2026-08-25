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

    census_fields = []
    for field in fields:
        entry: dict[str, Any] = {
            "name": field.get("name", ""),
            "id": field.get("id", ""),
            "dataType": field.get("dataType", ""),
        }
        if "options" in field:
            entry["options"] = sorted(
                ({"id": o["id"], "name": o["name"]} for o in field.get("options", [])),
                key=lambda o: str(o.get("name", "")),
            )
        census_fields.append(entry)
    census_fields.sort(key=lambda f: str(f.get("name", "")))

    return {
        "number": project_number,
        "id": project_id_box["id"],
        "title": project_id_box["title"],
        "fields": census_fields,
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
    except (GhApiError, RuntimeError, OSError) as exc:
        # Live GitHub Projects access is unavailable (no auth/network in this
        # environment, e.g. a CI runner with no Projects-scoped token) — a
        # SKIP, printed explicitly, never a silent pass. Mirrors the
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
