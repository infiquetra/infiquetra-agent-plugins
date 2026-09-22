"""Tests for the manifest store: the git-common-dir carrier for provenance manifests (U2).

Oracles pinned here:

* happy — write then read round-trips a manifest dict; the store path resolves identically from
  any worktree of the same repo (R19); a manifest_ref pointer round-trips back to the manifest.
* edge — list on an empty/absent tree returns []; write overwrites in place (not write-once).
* error — path-traversal ids are rejected (parity with outcome_store._safe_name).
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"
SCRIPT = SCRIPTS / "manifest_store.py"


def _load() -> ModuleType:
    # manifest_store imports its sibling outcome_store; make the scripts dir importable first.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("manifest_store", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["manifest_store"] = module
    spec.loader.exec_module(module)
    return module


M = _load()


def _runner_returning(common_dir: str, *, returncode: int = 0) -> Callable[..., Any]:
    def runner(args: list[str], **_kw: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=f"{common_dir}\n", stderr="boom")

    return runner


def _manifest(execution_id: str = "exec-1") -> dict[str, Any]:
    return {
        "schema": "saga.manifest.v1",
        "execution_id": execution_id,
        "saga_ref": "saga-42",
        "attribution": {
            "kind": "external-engine",
            "identity": "gemini-3.1-pro",
            "effort": "high",
            "protocol": "",
        },
        "disposition": "ran-as-requested",
        "disposition_note": "",
        "created_at": "2026-07-01T00:00:00Z",
        "output_completeness": None,
        "claim_provenance": None,
    }


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_manifest_store_write_read_round_trip(tmp_path: Path) -> None:
    store = M.Store(root=tmp_path / "saga-manifests" / "saga-42").ensure()
    manifest = _manifest()
    path = M.write_manifest(store, "exec-1", manifest)

    assert path.exists()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert list(tmp_path.rglob("*.tmp")) == []
    assert M.read_manifest(store, "exec-1") == manifest


def test_manifest_temp_and_final_are_private_at_replace_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = M.Store(root=tmp_path / "manifests").ensure()
    real_replace = M.os.replace
    observed: list[tuple[int, int]] = []

    def inspect_replace(source: Any, destination: Any) -> None:
        temp_mode = stat.S_IMODE(os.stat(source).st_mode)
        real_replace(source, destination)
        final_mode = stat.S_IMODE(os.stat(destination).st_mode)
        observed.append((temp_mode, final_mode))

    monkeypatch.setattr(M.os, "replace", inspect_replace)
    M.write_manifest(store, "exec-private", _manifest("exec-private"))

    assert observed == [(0o600, 0o600)]


def test_manifest_atomic_write_cleans_private_temp_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = M.Store(root=tmp_path / "manifests").ensure()

    def fail_replace(_source: Any, _destination: Any) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(M.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        M.write_manifest(store, "exec-fail", _manifest("exec-fail"))

    assert not store.manifest_path("exec-fail").exists()
    assert list(store.root.glob("*.tmp")) == []


def test_manifest_store_resolves_common_dir_from_worktree() -> None:
    # A linked worktree resolves --git-common-dir to the SAME absolute path as the main
    # checkout — the whole point of using it as the shared, cross-worktree carrier (R19).
    common = "/repo/.git"
    a = M.Store.for_saga("saga-42", Path("/repo"), runner=_runner_returning(common))
    b = M.Store.for_saga(
        "saga-42", Path("/repo/.git/worktrees/feature"), runner=_runner_returning(common)
    )
    assert a.root == b.root
    assert a.root == Path("/repo/.git") / M.MANIFEST_NAMESPACE / "saga-42"


def test_manifest_ref_pointer_round_trip(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    common_dir = str(tmp_path / "repo" / ".git")
    runner = _runner_returning(common_dir)

    store = M.Store.for_saga("saga-42", repo_root, runner=runner).ensure()
    manifest = _manifest("exec-9")
    M.write_manifest(store, "exec-9", manifest)

    payload = M.set_manifest_ref({"note": "kept"}, "saga-42", "exec-9")
    assert payload["note"] == "kept"
    assert payload[M.MANIFEST_REF_KEY] == "saga-manifests/saga-42/exec-9.json"

    resolved = M.resolve_manifest_ref(payload, repo_root, runner=runner)
    assert resolved == manifest


def test_manifest_ref_missing_pointer_returns_none(tmp_path: Path) -> None:
    resolved = M.resolve_manifest_ref({}, tmp_path, runner=_runner_returning(str(tmp_path)))
    assert resolved is None


def test_manifest_ref_traversal_pointer_returns_none(tmp_path: Path) -> None:
    common_dir = str(tmp_path)
    runner = _runner_returning(common_dir)
    payload = {M.MANIFEST_REF_KEY: "../outside.json"}
    assert M.resolve_manifest_ref(payload, tmp_path, runner=runner) is None


# ---------------------------------------------------------------------------
# edge
# ---------------------------------------------------------------------------


def test_manifest_store_list_empty_tree_returns_empty(tmp_path: Path) -> None:
    store = M.Store(root=tmp_path / "absent")
    assert M.list_manifests(store) == []


def test_manifest_store_list_returns_sorted_execution_ids(tmp_path: Path) -> None:
    store = M.Store(root=tmp_path / "saga-manifests" / "saga-1").ensure()
    M.write_manifest(store, "exec-b", _manifest("exec-b"))
    M.write_manifest(store, "exec-a", _manifest("exec-a"))
    assert M.list_manifests(store) == ["exec-a", "exec-b"]


def test_manifest_store_write_overwrites_in_place(tmp_path: Path) -> None:
    store = M.Store(root=tmp_path / "saga-manifests" / "saga-1").ensure()
    M.write_manifest(store, "exec-1", _manifest("exec-1"))
    updated = _manifest("exec-1")
    updated["disposition_note"] = "revised"
    M.write_manifest(store, "exec-1", updated)
    assert M.read_manifest(store, "exec-1")["disposition_note"] == "revised"


def test_read_manifest_missing_returns_none(tmp_path: Path) -> None:
    store = M.Store(root=tmp_path / "saga-manifests" / "saga-1").ensure()
    assert M.read_manifest(store, "no-such-exec") is None


def test_read_manifest_malformed_returns_none(tmp_path: Path) -> None:
    store = M.Store(root=tmp_path / "saga-manifests" / "saga-1").ensure()
    path = store.manifest_path("exec-broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert M.read_manifest(store, "exec-broken") is None


# ---------------------------------------------------------------------------
# error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["", "a/b", "a\\b", ".", "..", "a\x00b"])
def test_manifest_store_rejects_path_traversal_ids(tmp_path: Path, bad_id: str) -> None:
    store = M.Store(root=tmp_path / "saga-manifests" / "saga-1").ensure()
    with pytest.raises(M.ManifestStoreError):
        M.write_manifest(store, bad_id, _manifest())
