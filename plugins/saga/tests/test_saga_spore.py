"""Unit tests for the pure saga-spore core (U1, issue #281).

Covers the offline-testable heart of the PreCompact->SessionStart spore: serialization under the R5
byte budget (frontier never dropped), the on-disk dump/load seam with the R9 mismatch guard, active-saga
resolution against a really-written saga, deadline-bounded outcome discovery (KTD4), and the DAG freeze.
The real cross-process, real-git end-to-end seam is U5 (tests/test_spore_seam_roundtrip.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[3] / "plugins" / "saga" / "scripts"
SCRIPT = SCRIPTS / "saga_spore.py"


def _load() -> ModuleType:
    # saga_spore imports its siblings outcome / outcome_store / saga; make scripts dir importable first.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("saga_spore", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["saga_spore"] = module
    spec.loader.exec_module(module)
    return module


M = _load()

_NOW = "2026-06-30T20:00:00+00:00"


def _saga_box(**over: Any) -> dict[str, Any]:
    box = {
        "saga_id": "issue-281",
        "lifecycle_phase": "work",
        "phase_status": "in_progress",
        "status": "active",
        "next_step": "U2: build the PreCompact hook",
    }
    box.update(over)
    return box


def _spore(
    *, dag: dict[str, Any] | None, box: dict[str, Any] | None = None, **prov: Any
) -> dict[str, Any]:
    provenance = {
        "schema": M.SCHEMA,
        "generated_at": _NOW,
        "session_id": "sess-abc",
        "repo_root": "/repo",
        "saga_id": (box or {}).get("saga_id", "issue-281") if box is not None else "issue-281",
        "spec_revision": dag.get("spec_revision") if dag else None,
        "source_tick": ".claude/saga/sagas/issue-281/20260630-200000.md",
    }
    provenance.update(prov)
    pointers: dict[str, Any] = {"plan_path": "docs/plans/p.md", "issue_ref": "o/r#281"}
    if dag:
        pointers["outcome_id"] = dag["outcome_id"]
    return {
        "provenance": provenance,
        "saga_box": _saga_box() if box is None else box,
        "dag": dag,
        "pointers": pointers,
    }


def _dag(*, frontier: list[str], leaves: dict[str, dict[str, Any]], rev: int = 4) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for info in leaves.values():
        counts[info["state"]] = counts.get(info["state"], 0) + 1
    return {
        "outcome_id": "ship-auth",
        "objective": "ship auth",
        "spec_revision": rev,
        "counts": counts,
        "frontier": frontier,
        "complete": False,
        "leaves": leaves,
    }


# --------------------------------------------------------------------------- serialize (R5/R10)


def test_load_and_validate_rejects_malformed_or_incomplete() -> None:
    assert M.load_and_validate("{not json", "sess-abc", "/repo") is None
    assert M.load_and_validate(json.dumps({"schema": "other"}), "sess-abc", "/repo") is None
    # missing saga_id -> skip (R9 content guard)
    bad = json.dumps(
        {
            "schema": M.SCHEMA,
            "session_id": "sess-abc",
            "repo_root": "/repo",
            "saga_id": "",
            "block": "x",
        }
    )
    assert M.load_and_validate(bad, "sess-abc", "/repo") is None
    # empty block -> skip
    noblock = json.dumps(
        {
            "schema": M.SCHEMA,
            "session_id": "sess-abc",
            "repo_root": "/repo",
            "saga_id": "s",
            "block": "",
        }
    )
    assert M.load_and_validate(noblock, "sess-abc", "/repo") is None


# --------------------------------------------------------------------------- spore_path


def _fake_git_runner(*_a: Any, **_k: Any) -> SimpleNamespace:
    return SimpleNamespace(returncode=1, stdout="", stderr="")


def test_resolve_active_saga_reads_real_saga(tmp_path: Path) -> None:
    saga = M.saga
    obj = saga.Saga(
        saga_id="issue-9",
        kind="issue",
        id="9",
        lifecycle_phase="work",
        phase_status="in_progress",
        status="active",
        next_step="do the thing",
        plan_path="docs/plans/x.md",
        issue_ref="o/r#9",
        blockers="waiting on review",
        open_questions=["which model?"],
        checks_run=["pytest"],
    )
    saga.save(tmp_path, obj, runner=_fake_git_runner)

    box = M.resolve_active_saga(tmp_path)
    assert box is not None
    assert box["saga_id"] == "issue-9"
    assert box["lifecycle_phase"] == "work"
    assert box["phase_status"] == "in_progress"
    assert box["status"] == "active"
    assert box["next_step"] == "do the thing"
    assert box["blockers"] == "waiting on review"
    assert box["open_questions"] == ["which model?"]
    assert "checks_run" not in box  # C1: never carried
    assert box["_pointers"]["plan_path"] == "docs/plans/x.md"
    assert box["_pointers"]["issue_ref"] == "o/r#9"


def _make_outcomes(common: Path, *ids: str) -> None:
    for oid in ids:
        (common / "saga-outcomes" / oid).mkdir(parents=True, exist_ok=True)


def _spore_with_record(next_step: str) -> dict[str, Any]:
    spore = _spore(dag=None)
    spore["run_record"] = {
        "path": "/primary/.claude/saga/runs/issue-281.json",
        "issue": 281,
        "next_step": next_step,
        "destination": "pr",
        "pending_questions": [],
        "units": 2,
        "review_cycles": 1,
    }
    return spore


def test_serialize_suppresses_a_whitespace_only_next_step() -> None:
    block = M.serialize(_spore_with_record("   \n  "))
    assert "RUN RECORD" not in block
