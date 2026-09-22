"""T999-01 / T999-02: vendored SDLC schema re-sync guards (#999).

These tests read the worktree vendored JSON and production Python sources
only. They do not call load_config or GitHub.
"""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PLUGIN_ROOT / "config" / "sdlc-schema.json"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
EXPECTED_VERSION = "2026-09-07.5"
REMOVED_KEYS = ("wip_limits", "component_slices")


def test_t999_01_vendored_schema_version_is_2026_09_07_5() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["schema_version"] == EXPECTED_VERSION
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert EXPECTED_VERSION in text
    assert '"schema_version": "2026-08-29"' not in text


def test_t999_02_no_production_reads_of_removed_keys() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "wip_limits" not in schema, "vendored schema still carries top-level wip_limits"
    hierarchy = schema.get("work_hierarchy", {})
    assert "component_slices" not in hierarchy, (
        "vendored schema still carries work_hierarchy.component_slices"
    )
    assert "components" in hierarchy, "vendored schema missing work_hierarchy.components"

    hits: list[str] = []
    for path in sorted(SCRIPTS_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if any(key in line for key in REMOVED_KEYS):
                rel = path.relative_to(PLUGIN_ROOT)
                hits.append(f"{rel}:{lineno}:{line.strip()}")
    assert hits == [], "live removed-key reads:\n" + "\n".join(hits)
