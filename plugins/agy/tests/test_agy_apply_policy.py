"""Tests for U4 agy clone execution and apply policy.

Every agy delegation is non-apply since #671: it runs in a disposable clone and hands back a
patch, matching codex's contract. The live-apply mode (`auto-if-clean`), its lease-broker
admission, and the settlement/orphan-containment machinery that fenced it are gone, so the
coverage here is the preserve-patch path plus the verification step that live apply used to hide.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "skills" / "agy-delegate" / "scripts" / "agy_delegate.py"
FAKE_AGY = ROOT / "tests" / "fixtures" / "agy" / "fake_agy.py"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "allowed.txt").write_text("before\n", encoding="utf-8")
    _git(repo, "add", "README.md", "allowed.txt")
    _git(repo, "commit", "-m", "initial")
    return repo


def _payload(task: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "agy.delegation.v1",
        "role": "coder",
        "mode": "patch-only",
        "task": task,
        "model": "flash",
        "review_lens": None,
        "write_set": ["allowed.txt"],
        "apply_policy": "preserve-patch",
        "evidence": "summary",
        "verification": {
            "commands": [],
            "required": False,
            "run_scope": "clone",
        },
        "timeout_seconds": 5,
        "no_output_seconds": 3,
        "provenance_required": True,
    }
    payload.update(overrides)
    return payload


def _run_wrapper(
    tmp_path: Path,
    repo: Path,
    payload: dict[str, object],
    run_id: str,
) -> subprocess.CompletedProcess[str]:
    envelope_dir = tmp_path / "envelopes"
    envelope_dir.mkdir(exist_ok=True)
    envelope_path = envelope_dir / f"{run_id}.json"
    envelope_path.write_text(json.dumps(payload), encoding="utf-8")

    argv = [
        sys.executable,
        str(WRAPPER),
        "--repo-root",
        str(repo),
        "--run-id",
        run_id,
        "--envelope",
        str(envelope_path),
        "--launch-agy",
        "--agy-bin",
        str(FAKE_AGY),
        "--audit-store",
        str(tmp_path / "audit-store"),
    ]
    environment = dict(os.environ)
    environment["INFIQUETRA_FLEET_STATE_DIR"] = str(tmp_path / "fleet-state")
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _bundle(repo: Path, run_id: str) -> Path:
    return repo / ".claude" / "agy" / "runs" / run_id


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_wrapper_carries_no_lease_or_containment_coupling(tmp_path: Path) -> None:
    """agy reaches no broker at all (#671).

    This is a structural guard, not a behavioural one: the retired coupling was a lazy import
    reached from a single branch, so a functional test of the surviving modes would pass even if
    the import came back. Asserting on the source keeps a re-add loud.
    """

    # Ignore comment lines: the module comment explaining the retirement legitimately names what
    # was removed. Rejection of the `auto-if-clean` mode value itself is covered by
    # tests/test_agy_delegate_contract.py::test_cli_rejects_invalid_envelope_without_bundle.
    code = "\n".join(
        line
        for line in WRAPPER.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    for retired in ("lease_broker", "orphan_evidence", "agy_lease_admission"):
        assert retired not in code, f"{retired} is reachable from agy_delegate.py again"

    assert not (WRAPPER.parent / "agy_lease_admission.py").exists()

    # And the surviving modes still run end to end.
    repo = _init_repo(tmp_path)
    for mode, run_id in (("patch-only", "no-coupling-patch"), ("no-write", "no-coupling-nowrite")):
        completed = _run_wrapper(
            tmp_path,
            repo,
            _payload("FAKE_AGY_MODE=success", mode=mode, write_set=[]),
            run_id,
        )
        assert completed.returncode == 0, completed.stderr


def test_patch_only_preserves_clone_patch_without_live_mutation(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload("FAKE_AGY_WRITE allowed.txt::after\n"),
        "patch-only-run",
    )
    bundle = _bundle(repo, "patch-only-run")

    assert completed.returncode == 0
    assert _json(bundle / "result.json")["status"] == "patch_ready"
    assert _json(bundle / "run-lease.json")["real_agy_verdict"] == "real"
    assert _json(bundle / "changed-paths.json")["changed_paths"] == ["allowed.txt"]
    assert "after" in (bundle / "diff.patch").read_text(encoding="utf-8")
    assert (repo / "allowed.txt").read_text(encoding="utf-8") == "before\n"

    proof = _json(bundle / "git-proof.json")
    assert proof["base_sha"] == _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert proof["clone_path"] == str(bundle / "worktree")
    assert proof["removed_remotes"] == ["origin"]
    assert proof["clone_remotes_after"] == []
    assert proof["rogue_commits"] == []
    assert proof["clone_post_status"]["entries"]
    assert _git(bundle / "worktree", "remote").stdout == ""


def test_relative_repo_root_does_not_make_bundle_logs_clone_changes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    envelope_path = tmp_path / "relative-envelope.json"
    envelope_path.write_text(json.dumps(_payload("FAKE_AGY_MODE=success")), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            repo.name,
            "--run-id",
            "relative-root-run",
            "--envelope",
            str(envelope_path),
            "--launch-agy",
            "--agy-bin",
            str(FAKE_AGY),
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    bundle = _bundle(repo, "relative-root-run")

    assert completed.returncode == 0
    assert _json(bundle / "result.json")["status"] == "success"
    assert _json(bundle / "changed-paths.json")["changed_paths"] == []
    assert (bundle / "agy.log").exists()
    assert (bundle / "diff.patch").read_text(encoding="utf-8") == ""


def test_invalid_run_id_is_rejected_before_any_bundle(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    envelope = tmp_path / "invalid-run-id.json"
    envelope.write_text(
        json.dumps(_payload("FAKE_AGY_WRITE allowed.txt::after\\n")),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(repo),
            "--run-id",
            "../invalid",
            "--envelope",
            str(envelope),
            "--launch-agy",
            "--agy-bin",
            str(FAKE_AGY),
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "run_id must be a non-empty path segment" in completed.stderr
    assert not (repo / ".claude" / "agy" / "runs").exists()
    assert (repo / "allowed.txt").read_text(encoding="utf-8") == "before\n"


def test_supervised_bundle_artifacts_are_owner_private(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload("FAKE_AGY_WRITE allowed.txt::after\n"),
        "private-supervised-run",
    )

    assert completed.returncode == 0, completed.stderr
    bundle = _bundle(repo, "private-supervised-run")
    assert bundle.stat().st_mode & 0o777 == 0o700
    artifact_files = [path for path in bundle.iterdir() if path.is_file()]
    assert artifact_files
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in artifact_files)


def test_validation_bundle_artifacts_are_owner_private(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    envelope = tmp_path / "validation-envelope.json"
    envelope.write_text(json.dumps(_payload("validate only")), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(repo),
            "--run-id",
            "private-validation-run",
            "--envelope",
            str(envelope),
            "--validation-only",
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    bundle = _bundle(repo, "private-validation-run")
    assert bundle.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in bundle.iterdir())


def test_patch_only_with_explicit_write_set_flags_out_of_scope_changes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload("FAKE_AGY_WRITE outside.txt::oops\n"),
        "patch-out-of-scope-run",
    )
    bundle = _bundle(repo, "patch-out-of-scope-run")

    assert completed.returncode == 1
    assert _json(bundle / "result.json")["status"] == "out_of_scope_mutation"
    assert _json(bundle / "checks.json")["out_of_scope_paths"] == ["outside.txt"]
    assert not (repo / "outside.txt").exists()


def test_no_write_clone_mutation_is_not_successful_patch_ready(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload(
            "FAKE_AGY_WRITE allowed.txt::after\n",
            role="reviewer",
            mode="no-write",
            write_set=[],
        ),
        "no-write-mutated-run",
    )
    bundle = _bundle(repo, "no-write-mutated-run")

    assert completed.returncode == 1
    assert _json(bundle / "result.json")["status"] == "out_of_scope_mutation"
    assert _json(bundle / "checks.json")["out_of_scope_paths"] == ["allowed.txt"]
    assert (repo / "allowed.txt").read_text(encoding="utf-8") == "before\n"


# --- verification (#671) ---------------------------------------------------------------------
# Declared verification commands used to be reachable only from the retired apply-if-clean
# branch, so a patch-only run recorded `passed: null, commands: []` even when it declared
# `required: true`. These cover the rewired behaviour.


def test_patch_only_runs_declared_verification_in_the_clone(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload(
            "FAKE_AGY_WRITE allowed.txt::after\n",
            verification={
                "commands": ['test "$(cat allowed.txt)" = after'],
                "required": True,
                "run_scope": "clone",
            },
        ),
        "verification-runs-run",
    )
    bundle = _bundle(repo, "verification-runs-run")
    checks = _json(bundle / "checks.json")

    assert completed.returncode == 0, completed.stderr
    assert _json(bundle / "result.json")["status"] == "patch_ready"
    # The command observed the delegate's clone-side edit, proving it ran in the clone and not
    # against the untouched live tree.
    assert checks["passed"] is True
    assert checks["commands"][0]["return_code"] == 0
    assert checks["commands"][0]["cwd"] == str(bundle / "worktree")
    assert (repo / "allowed.txt").read_text(encoding="utf-8") == "before\n"


def test_patch_only_required_verification_failure_is_checks_failed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload(
            "FAKE_AGY_WRITE allowed.txt::after\n",
            verification={"commands": ["exit 9"], "required": True, "run_scope": "clone"},
        ),
        "verification-required-fail-run",
    )
    bundle = _bundle(repo, "verification-required-fail-run")
    checks = _json(bundle / "checks.json")

    assert completed.returncode == 1
    assert _json(bundle / "result.json")["status"] == "checks_failed"
    assert checks["passed"] is False
    assert checks["commands"][0]["return_code"] == 9
    assert (repo / "allowed.txt").read_text(encoding="utf-8") == "before\n"


def test_patch_only_advisory_verification_failure_stays_patch_ready(tmp_path: Path) -> None:
    """An unrequired command that fails is recorded but does not fail the run."""

    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload(
            "FAKE_AGY_WRITE allowed.txt::after\n",
            verification={"commands": ["exit 9"], "required": False, "run_scope": "clone"},
        ),
        "verification-advisory-fail-run",
    )
    bundle = _bundle(repo, "verification-advisory-fail-run")
    checks = _json(bundle / "checks.json")

    assert completed.returncode == 0, completed.stderr
    assert _json(bundle / "result.json")["status"] == "patch_ready"
    assert checks["passed"] is False
    assert checks["commands"][0]["return_code"] == 9


def test_patch_only_without_verification_commands_stays_patch_ready(tmp_path: Path) -> None:
    """Declaring nothing is not a failure: `passed` stays None rather than False."""

    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload("FAKE_AGY_WRITE allowed.txt::after\n"),
        "verification-absent-run",
    )
    bundle = _bundle(repo, "verification-absent-run")
    checks = _json(bundle / "checks.json")

    assert completed.returncode == 0
    assert _json(bundle / "result.json")["status"] == "patch_ready"
    assert checks["passed"] is None
    assert checks["commands"] == []
    assert checks["skipped_reason"] == "no verification commands declared"


def test_no_write_does_not_run_verification(tmp_path: Path) -> None:
    """A no-write run leaves the clone unchanged, so verifying it would prove nothing."""

    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload(
            "FAKE_AGY_MODE=success",
            role="reviewer",
            mode="no-write",
            write_set=[],
            verification={"commands": ["exit 9"], "required": True, "run_scope": "clone"},
        ),
        "no-write-skips-verification-run",
    )
    bundle = _bundle(repo, "no-write-skips-verification-run")
    checks = _json(bundle / "checks.json")

    assert completed.returncode == 0, completed.stderr
    assert _json(bundle / "result.json")["status"] == "success"
    assert checks["commands"] == []
    assert checks["passed"] is None


def test_non_clone_run_scope_does_not_execute_commands(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    completed = _run_wrapper(
        tmp_path,
        repo,
        _payload(
            "FAKE_AGY_WRITE allowed.txt::after\n",
            verification={"commands": ["exit 9"], "required": True, "run_scope": "none"},
        ),
        "verification-scope-none-run",
    )
    bundle = _bundle(repo, "verification-scope-none-run")
    checks = _json(bundle / "checks.json")

    assert completed.returncode == 0, completed.stderr
    assert _json(bundle / "result.json")["status"] == "patch_ready"
    assert checks["passed"] is None
    assert checks["skipped_reason"] == "verification must run in clone scope"
