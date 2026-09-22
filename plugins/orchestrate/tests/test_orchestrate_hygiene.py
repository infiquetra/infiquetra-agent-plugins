"""Documentation hygiene for the Orchestrate plugin.

The run-state half of this module went with issue #1025: there is no `.orchestrate/run.json` to
keep out of the driven repository's status, so there is no `info/exclude` rule to assert, no
hand-authored task-brief directory, and no `clean --all` that deletes run state. The run-identifier
safety assertion those tests shared now lives in ``test_orchestrate_plan_check.py``, where it is
proved against a path that creates nothing at all.

What survives is the pair of checks that keep the plugin's own prose honest about what it ships.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "orchestrate"
README = PLUGIN_ROOT / "README.md"
SKILL = PLUGIN_ROOT / "skills" / "orchestrate" / "SKILL.md"


def test_readme_references_only_python_modules_the_plugin_ships() -> None:
    references = set(
        re.findall(
            r"(?<![A-Za-z0-9_.-])((?:skills/orchestrate/)?scripts/[A-Za-z0-9_.-]+\.py)",
            README.read_text(),
        )
    )
    assert references == {
        "skills/orchestrate/scripts/herdr_events.py",
        "skills/orchestrate/scripts/orchestrate.py",
    }
    assert all((PLUGIN_ROOT / reference).is_file() for reference in references)


def test_the_skill_names_the_record_rather_than_a_run_file() -> None:
    """The prose and the code must agree about where state lives (issue #1025)."""
    skill = " ".join(SKILL.read_text().split())
    assert ".orchestrate/run.json" not in skill
    assert "run record" in skill.lower()
