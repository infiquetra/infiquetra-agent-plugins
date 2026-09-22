"""Tests for the gate operator-absence contract lint (#371) — H-F6-5.

Two layers, both against the PRODUCTION lint:

* the issue's acceptance commands run via subprocess against the REAL repo tree (fixture red/green
  pair; the five-site skills scan; the CI default scan), and
* red-path controls on throwaway trees proving every verdict the lint can emit — uncovered
  mention, malformed marker, baseline drift in both directions, vanished/stale baseline entries,
  non-literal / off-vocabulary / kwargs-hidden Python declarations — actually goes red.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"
LINT = SCRIPTS / "lint_gate_absence_contract.py"

MIGRATED_SKILLS = (
    "plugins/saga/skills/brainstorm/SKILL.md",
    "plugins/saga/skills/code-review/SKILL.md",
    "plugins/saga/skills/founder-review/SKILL.md",
    "plugins/saga/skills/ideate/SKILL.md",
    "plugins/saga/skills/investigate/SKILL.md",
)


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


L = _load("lint_gate_absence_contract")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LINT), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )


# ---------------------------------------------------------------------------
# The issue's acceptance commands, verbatim, against the real tree.
# ---------------------------------------------------------------------------


_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_fixture_missing_absence_exits_nonzero_and_names_the_site() -> None:
    fixture = _FIXTURES / "gate_missing_absence.py"
    result = _run("--fixture", str(fixture))
    assert result.returncode == 1
    assert "gate_missing_absence.py:" in result.stdout
    assert "declares no absence_behavior" in result.stdout


def test_fixture_with_absence_passes() -> None:
    fixture = _FIXTURES / "gate_with_absence.py"
    result = _run("--fixture", str(fixture))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "absence=HALT" in result.stdout


def test_scan_saga_skills_passes_and_lists_all_five_migrated_sites() -> None:
    result = _run("--scan", "plugins/saga/skills")
    assert result.returncode == 0, result.stdout + result.stderr
    for skill in MIGRATED_SKILLS:
        assert skill in result.stdout, f"{skill} missing from the compliant-site report"


def test_default_ci_scan_passes_and_surfaces_pending_migrations() -> None:
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    # The baseline debt is SURFACED (applied: false semantics), never silently skipped.
    assert "pending migration" in result.stdout
    assert "applied: false" in result.stdout
    # gate_record.py was the primitive definer and appeared here as excluded-by-rule. It was
    # removed in #666 (926 lines that never wrote a record.json in production); the lint's
    # subject is the DECLARATION marker in skill prose, which is independent of any recording
    # CLI, so the scan still passes with zero violations and every gate site still declares its
    # absence behavior.
    assert "VIOLATIONS: 0" in result.stdout
    assert "gate_record.py" not in result.stdout


# ---------------------------------------------------------------------------
# Red-path controls on throwaway trees — every verdict can actually fire.
# ---------------------------------------------------------------------------


def _scan(root: Path, baseline: dict[str, int] | None = None) -> Any:
    return L.run_scan([root], baseline)


def test_uncovered_mention_without_baseline_is_a_violation(tmp_path: Path) -> None:
    doc = tmp_path / "skills" / "SKILL.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# Skill\n\nUse `AskUserQuestion` for the gate.\n", encoding="utf-8")
    result = _scan(tmp_path, baseline={})
    assert len(result.violations) == 1
    assert "declares no absence contract" in result.violations[0].message
    # Control: adding a gate-record marker in the same section clears it.
    doc.write_text(
        "# Skill\n\n<!-- gate-record: id=demo absence=HALT transport=ask-user-question -->\n"
        "Use `AskUserQuestion` for the gate.\n",
        encoding="utf-8",
    )
    assert _scan(tmp_path, baseline={}).violations == []


def test_gate_exempt_marker_covers_a_prose_mention(tmp_path: Path) -> None:
    doc = tmp_path / "SKILL.md"
    doc.write_text(
        "# Skill\n\n<!-- gate-exempt: prose note, fires no gate -->\n"
        "Never call `AskUserQuestion` here.\n",
        encoding="utf-8",
    )
    assert _scan(tmp_path, baseline={}).violations == []


def test_marker_coverage_is_section_scoped_not_file_scoped(tmp_path: Path) -> None:
    doc = tmp_path / "SKILL.md"
    doc.write_text(
        "# Skill\n\n<!-- gate-record: id=demo absence=HALT transport=ask-user-question -->\n"
        "Use `AskUserQuestion` for the gate.\n\n"
        "## Another section\n\nAlso uses `AskUserQuestion`.\n",
        encoding="utf-8",
    )
    result = _scan(tmp_path, baseline={})
    assert len(result.violations) == 1  # the second section is NOT covered by the first marker
    assert result.violations[0].line == 8  # the mention inside "## Another section"


def test_malformed_and_off_vocabulary_markers_fail_closed(tmp_path: Path) -> None:
    cases = [
        "<!-- gate-record: id=demo absence=HALT -->",  # missing transport
        "<!-- gate-record: id=demo absence=proceed transport=ask-user-question -->",  # bad vocab
        "<!-- gate-record: id=demo absence=HALT transport=smoke-signal -->",  # bad transport
        "<!-- gate-exempt: -->",  # empty reason
        "<!-- gate-banana -->",  # unknown marker family
    ]
    for marker in cases:
        doc = tmp_path / "SKILL.md"
        doc.write_text(f"# Skill\n\n{marker}\n", encoding="utf-8")
        result = _scan(tmp_path, baseline={})
        assert result.violations, f"marker {marker!r} should have failed the lint"


def test_changelog_and_readme_basenames_are_excluded(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text("release notes: `AskUserQuestion`\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("index: `AskUserQuestion`\n", encoding="utf-8")
    assert _scan(tmp_path, baseline={}).violations == []
    # Control: the same content in a non-excluded basename fails (the exclusion is doing work).
    (tmp_path / "OTHER.md").write_text("guide: `AskUserQuestion`\n", encoding="utf-8")
    assert _scan(tmp_path, baseline={}).violations != []


def test_baseline_exact_match_is_pending_and_any_drift_fails(tmp_path: Path) -> None:
    doc = tmp_path / "legacy.md"
    doc.write_text("# Legacy\n\n`AskUserQuestion` one.\n`AskUserQuestion` two.\n", encoding="utf-8")
    rel = L._relpath(doc)

    exact = _scan(tmp_path, baseline={rel: 2})
    assert exact.violations == []
    assert exact.pending == {rel: 2}

    grew = _scan(tmp_path, baseline={rel: 1})
    assert any("baseline drift" in f.message for f in grew.violations)

    shrank = _scan(tmp_path, baseline={rel: 3})
    assert any("shrink the baseline" in f.message for f in shrank.violations)


def test_vanished_and_stale_baseline_entries_fail(tmp_path: Path) -> None:
    gone_rel = (tmp_path / "gone.md").as_posix()
    vanished = L.run_scan([tmp_path], {L._relpath(tmp_path / "gone.md"): 2})
    del gone_rel
    assert any("baseline entry vanished" in f.message for f in vanished.violations)

    clean = tmp_path / "clean.md"
    clean.write_text("# Clean\n\nNo gates here.\n", encoding="utf-8")
    stale = L.run_scan([tmp_path], {L._relpath(clean): 1})
    assert any("stale baseline entry" in f.message for f in stale.violations)


def test_baseline_entries_outside_the_scan_roots_are_not_judged(tmp_path: Path) -> None:
    doc = tmp_path / "inside.md"
    doc.write_text("# Inside\n\nNothing.\n", encoding="utf-8")
    result = L.run_scan([tmp_path], {"plugins/elsewhere/thing.md": 4})
    assert result.violations == []  # a partial scan must not judge entries it cannot see


def test_baseline_loader_fails_closed(tmp_path: Path) -> None:
    for payload in (
        '{"pending": {}}',  # missing schema_version
        '{"schema_version": 2, "pending": {}}',  # unknown version
        '{"schema_version": 1, "pending": {"a.md": 0}}',  # nonpositive count
        '{"schema_version": 1, "pending": {"a.md": true}}',  # bool-coercible count
        '{"schema_version": 1, "pending": {"a.md": 1}, "extra": 1}',  # unknown key
    ):
        path = tmp_path / "baseline.json"
        path.write_text(payload, encoding="utf-8")
        try:
            L.load_baseline(path)
        except ValueError:
            continue
        raise AssertionError(f"baseline payload {payload!r} should have been rejected")


def test_python_call_sites_fail_closed(tmp_path: Path) -> None:
    cases = {
        "missing": "open_gate('d', 'g', 'q', ['a', 'b'])\n",
        "non-literal": "b = 'HALT'\nopen_gate('d', 'g', 'q', ['a', 'b'], absence_behavior=b)\n",
        "off-vocab": "open_gate('d', 'g', 'q', ['a', 'b'], absence_behavior='panic')\n",
        "kwargs": "kw = {}\nopen_gate('d', 'g', 'q', ['a', 'b'], **kw)\n",
        "attribute-call": "import gate_record\ngate_record.open_gate('d', 'g', 'q', ['a', 'b'])\n",
    }
    for label, body in cases.items():
        module = tmp_path / "site.py"
        module.write_text(body, encoding="utf-8")
        result = _scan(tmp_path, baseline={})
        assert result.violations, f"{label} call should have failed the lint"
    # Control: a literal in-vocabulary declaration passes and is reported compliant.
    (tmp_path / "site.py").write_text(
        "open_gate('d', 'g', 'q', ['a', 'b'], absence_behavior='HALT')\n", encoding="utf-8"
    )
    ok = _scan(tmp_path, baseline={})
    assert ok.violations == []
    assert len(ok.python_ok) == 1


def test_definer_module_is_excluded_by_rule_and_reported(tmp_path: Path) -> None:
    module = tmp_path / "primitive.py"
    module.write_text(
        "def open_gate(*a, **kw):\n    return None\n\n\n"
        "def cli(value):\n    open_gate('d', 'g', 'q', ['a', 'b'], absence_behavior=value)\n",
        encoding="utf-8",
    )
    result = _scan(tmp_path, baseline={})
    assert result.violations == []  # the definer's own forwarding call is excluded by rule
    assert result.definers == [L._relpath(module)]
    # Control: the SAME forwarding call outside the definer module is a violation.
    module.write_text(
        "def cli(value):\n    open_gate('d', 'g', 'q', ['a', 'b'], absence_behavior=value)\n",
        encoding="utf-8",
    )
    assert _scan(tmp_path, baseline={}).violations != []


def test_repo_baseline_matches_reality_exactly() -> None:
    """The checked-in baseline is live: regenerating it from the tree yields the same content."""
    checked_in = json.loads((SCRIPTS / "gate_absence_baseline.json").read_text(encoding="utf-8"))
    emitted = _run("--emit-baseline")
    assert emitted.returncode == 0, emitted.stderr
    assert json.loads(emitted.stdout) == checked_in
