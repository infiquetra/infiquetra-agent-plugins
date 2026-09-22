"""Tests for the fleet-core durable delegation audit store (#396, U1)."""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "audit_store.py"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def audit_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    # Never resolve DEFAULT_AUDIT_STORE_ROOT against the real developer home directory (R5/KTD6).
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    return _load_module(MODULE_PATH, "audit_store")


def _receipt(run_id: str = "run-1") -> dict[str, object]:
    return {
        "schema": "bridge_receipt.v1",
        "engine_id": "agy",
        "variant": "flash",
        "transport": "cli",
        "wall_time_s": 1.5,
        "bytes_produced": 42,
        "runner": {"pid": 123, "argv": ["agy"], "exit_code": 0},
        "run_id": run_id,
    }


def test_mirror_receipt_resolvable_by_run_id_alone(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")
    audit_store.mirror_receipt(store, "run-1", _receipt("run-1"))

    resolved = audit_store.resolve_receipt(store, "run-1")

    assert resolved is not None
    assert resolved["run_id"] == "run-1"


def test_mirror_result_resolvable_when_no_receipt(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")
    result_payload = {"status": "success", "agy_launched": False, "run_id": "run-2"}

    audit_store.mirror_result(store, "run-2", result_payload)

    assert audit_store.resolve_result(store, "run-2") == result_payload
    assert audit_store.resolve_receipt(store, "run-2") is None


def test_mirror_manifest_resolvable_by_id(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")
    manifest = {"execution_id": "exec-1", "disposition": "ran-as-requested"}

    audit_store.mirror_manifest(store, "exec-1", manifest)

    assert audit_store.resolve_manifest(store, "exec-1") == manifest


def test_manifest_mirror_overwrites_in_place(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")
    audit_store.mirror_manifest(store, "exec-1", {"disposition": "ran-as-requested"})

    audit_store.mirror_manifest(store, "exec-1", {"disposition": "rejected-offload"})

    assert audit_store.resolve_manifest(store, "exec-1") == {"disposition": "rejected-offload"}


def test_default_root_resolves_under_home_dot_claude_delegation_audit(
    audit_store: ModuleType,
) -> None:
    store = audit_store.Store.for_root(None)

    assert store.root == (Path.home() / ".claude" / "delegation-audit").resolve()


def test_run_id_path_traversal_rejected(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")

    with pytest.raises(audit_store.AuditStoreError):
        audit_store.mirror_receipt(store, "../../etc", _receipt())


def test_list_runs_reflects_every_mirrored_run(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")
    audit_store.mirror_result(store, "run-a", {"status": "success"})
    audit_store.mirror_manifest(store, "run-b", {"disposition": "ran-as-requested"})

    assert audit_store.list_runs(store) == ["run-a", "run-b"]


def test_list_runs_empty_store_returns_empty_list(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")

    assert audit_store.list_runs(store) == []


def test_resolve_receipt_missing_run_returns_none(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")

    assert audit_store.resolve_receipt(store, "never-existed") is None


def test_resolve_corrupt_json_returns_none_never_raises(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")
    path = store.receipt_path("run-corrupt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    assert audit_store.resolve_receipt(store, "run-corrupt") is None


def test_write_once_draft_then_resolve(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")

    audit_store.write_once_draft(store, "run-1", "--- a/foo\n+++ b/foo\n")

    assert audit_store.resolve_draft(store, "run-1") == "--- a/foo\n+++ b/foo\n"


def test_resolve_draft_missing_returns_none(audit_store: ModuleType, tmp_path: Path) -> None:
    store = audit_store.Store.for_root(tmp_path / "audit-store")

    assert audit_store.resolve_draft(store, "never-existed") is None


def test_mirrored_files_are_not_world_or_group_readable(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """Mirrored evidence (receipts, result payloads, manifests, raw drafts) lands mode 0600 —
    matching manifest_store.py's precedent for the identical manifest.json content this store
    also mirrors, not the unrestricted default a bare write_text/os.replace would leave."""
    store = audit_store.Store.for_root(tmp_path / "audit-store")
    audit_store.mirror_receipt(store, "run-1", _receipt("run-1"))
    audit_store.write_once_draft(store, "run-1", "raw pre-fix output")

    for path in (store.receipt_path("run-1"), store.draft_path("run-1")):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"{path} is mode {oct(mode)}, expected 0o600"


def test_resolve_receipt_valid_json_non_dict_returns_none(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """A mirrored file that parses as valid JSON but isn't an object (e.g. a bare list) degrades
    to None rather than being treated as a receipt/result/manifest dict."""
    store = audit_store.Store.for_root(tmp_path / "audit-store")
    path = store.receipt_path("run-list")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert audit_store.resolve_receipt(store, "run-list") is None


# ------------------------------------------------------------------ ancestor hardening (#624)


def test_ensure_private_dir_refuses_symlinked_ancestor_below_home(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """PA-1 (#624): a symlinked component below home is refused before any mkdir traverses it."""
    home = Path.home()  # the fixture monkeypatches HOME to tmp_path/"fake-home"
    real = home / "real-target"
    real.mkdir(parents=True, mode=0o700)
    link = home / "link"
    link.symlink_to(real)
    with pytest.raises(audit_store.AuditStoreError, match="symlink"):
        audit_store._ensure_private_dir(link / "audit")
    assert list(real.iterdir()) == []  # nothing was created through the link


def test_ensure_private_dir_refuses_world_writable_ancestor_below_home(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """PA-1 (#624): an existing world-writable directory below home is refused, no fallback."""
    home = Path.home()
    loose = home / "loose"
    loose.mkdir(parents=True)
    os.chmod(loose, 0o777)
    with pytest.raises(audit_store.AuditStoreError, match="world-writable"):
        audit_store._ensure_private_dir(loose / "audit")
    assert not (loose / "audit").exists()


def test_for_root_ensure_refuses_world_writable_ancestor_outside_home(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """#627 (U4): the universal walk refuses a world-writable-non-sticky ancestor even OUTSIDE
    home — the FAT32/exFAT fail-closed shape (KTD2). This flips the #624 out-of-home exemption:
    a 0o777 non-sticky volume component can no longer host the store, and the refusal is reached
    through the real ``Store.for_root(...).ensure()`` entry point that resolves the root first."""
    outside = tmp_path / "outside-home"  # tmp_path is not under the monkeypatched home
    outside.mkdir()
    os.chmod(outside, 0o777)  # world-writable, no sticky bit — the exFAT/FAT32 shape
    store = audit_store.Store.for_root(outside / "audit")
    with pytest.raises(audit_store.AuditStoreError, match="world-writable"):
        store.ensure()
    assert not (outside / "audit").exists()


def test_for_root_ensure_accepts_sticky_world_writable_ancestor(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """#627 (U4): world-writable AND sticky (``S_ISVTX``, the 1777 system-temp shape) is the sole
    mode exemption — the store is created 0o700 below it, reached through the real entry point."""
    sticky = tmp_path / "sticky-tmp"
    sticky.mkdir()
    os.chmod(sticky, 0o1777)  # world-writable + sticky, e.g. /tmp
    store = audit_store.Store.for_root(sticky / "audit").ensure()
    assert stat.S_IMODE(store.root.lstat().st_mode) == 0o700


def test_for_root_ensure_refuses_symlinked_home_component(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """#627 (U4): the #624 probe shape (``~/link -> wwroot 0o777 non-sticky``) driven through the
    real ``Store.for_root(...).ensure()`` entry point. ``for_root`` resolves the root, collapsing
    the symlink — but the world-writable target's mode bits survive, so the world-writable arm
    still refuses it (the resolve-disarm lesson, #624)."""
    home = Path.home()
    home.mkdir(parents=True, exist_ok=True)
    wwroot = tmp_path / "wwroot"
    wwroot.mkdir()
    os.chmod(wwroot, 0o777)
    link = home / "link"
    link.symlink_to(wwroot)
    store = audit_store.Store.for_root(link / "audit")
    with pytest.raises(audit_store.AuditStoreError, match="world-writable"):
        store.ensure()
    assert list(wwroot.iterdir()) == []  # nothing created through the resolved link


def test_for_root_ensure_passes_stock_root_walk(audit_store: ModuleType, tmp_path: Path) -> None:
    """#627 (U4): the universal walk starts at the filesystem root, so it must pass the stock
    ancestor chain (``/`` and the resolved temp tree, all 0755/0700 or 1777 sticky) and create
    the store 0o700. Guards against a walk that spuriously refuses ordinary machine roots."""
    store = audit_store.Store.for_root(tmp_path / "audit-store").ensure()
    assert stat.S_IMODE(store.root.lstat().st_mode) == 0o700


def test_ensure_private_dir_creates_fresh_below_home_path(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """PA-1 (#624): the ancestor walk falls through at the first not-yet-existing component and
    creates the subtree 0o700 — the DEFAULT_AUDIT_STORE_ROOT path on a machine that has never
    mirrored a delegation before."""
    home = Path.home()
    home.mkdir(parents=True, exist_ok=True)
    target = home / "fresh" / "audit"
    audit_store._ensure_private_dir(target)
    for directory in (target, target.parent):
        assert stat.S_IMODE(directory.lstat().st_mode) == 0o700


def test_ensure_private_dir_is_process_safe_when_two_creators_race(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """#681 (#677/U4): concurrent dispatches both proceed (plan #677 Scope Decision row 1) and
    mirror to one shared store root. The mkdir walk used to race — exists()-then-mkdir is a
    TOCTOU — and the losing process died on FileExistsError under CI load. ``exist_ok`` plus the
    final lstat validation make creation process-idempotent: both contenders succeed and the
    directory is still 0o700."""
    home = Path.home()
    home.mkdir(parents=True, exist_ok=True)
    target = home / "raced" / "audit"
    context = multiprocessing.get_context("fork")
    start = context.Barrier(2)
    errors = context.Queue()

    def creator() -> None:
        start.wait(timeout=10)
        try:
            audit_store._ensure_private_dir(target)
        except Exception as exc:  # noqa: BLE001 - child reports any typed failure.
            errors.put(f"{type(exc).__name__}: {exc}")

    processes = [context.Process(target=creator) for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
    assert processes[0].exitcode == 0 and processes[1].exitcode == 0
    assert errors.empty()
    assert stat.S_IMODE(target.lstat().st_mode) == 0o700


def test_ensure_private_dir_accepts_group_writable_ancestor_below_home(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """PA-1 (#624): the guard's scope is world-writable, not group-writable — a shared-group
    ancestor stays usable. Pins the boundary so it cannot drift either way unnoticed."""
    home = Path.home()
    shared = home / "shared"
    shared.mkdir(parents=True)
    os.chmod(shared, 0o770)
    target = shared / "audit"
    audit_store._ensure_private_dir(target)
    assert stat.S_IMODE(target.lstat().st_mode) == 0o700


def test_ensure_private_dir_refuses_uninspectable_ancestor_below_home(
    audit_store: ModuleType, tmp_path: Path
) -> None:
    """PA-1 (#624): an ancestor this user cannot stat fails typed, not as a raw PermissionError,
    so callers see the store's own error class."""
    if os.geteuid() == 0:  # root bypasses the permission check the test depends on
        pytest.skip("root can traverse any directory")
    home = Path.home()
    blocked = home / "blocked"
    blocked.mkdir(parents=True)
    (blocked / "child").mkdir()
    os.chmod(blocked, 0o000)
    try:
        with pytest.raises(audit_store.AuditStoreError, match="not inspectable"):
            audit_store._ensure_private_dir(blocked / "child" / "audit")
    finally:
        os.chmod(blocked, 0o700)  # restore so tmp_path teardown can clean up
