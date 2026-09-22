"""Contract tests for the U2 agy delegation envelope wrapper."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "skills" / "agy-delegate" / "scripts" / "agy_delegate.py"
FAKE_AGY = ROOT / "tests" / "fixtures" / "agy" / "fake_agy.py"
AUDIT_STORE_PATH = REPO / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "audit_store.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agy_delegate", WRAPPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agy_delegate"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agy_delegate() -> ModuleType:
    return _load_module()


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "agy.delegation.v1",
        "role": "coder",
        "mode": "patch-only",
        "task": "Implement a bounded validation-only change.",
        "model": "flash",
        "review_lens": None,
        "write_set": ["plugins/agy/scripts/agy_delegate.py"],
        "apply_policy": "preserve-patch",
        "evidence": "summary",
        # No verification by default (#671). Declared commands now actually execute inside the
        # disposable clone; before, they were reachable only from the retired apply-if-clean
        # branch and silently never ran. A required command naming this repo's test paths cannot
        # pass in a bare fixture clone, so leaving one here would make every caller of this helper
        # assert `checks_failed`. Verification behaviour has its own coverage in
        # tests/test_agy_apply_policy.py.
        "verification": {"commands": [], "required": False, "run_scope": "clone"},
        "timeout_seconds": 900,
        "no_output_seconds": 180,
        "provenance_required": True,
    }
    payload.update(overrides)
    return payload


def _receipt_kwargs(agy_delegate: ModuleType, content: str = "agy summary") -> dict[str, object]:
    return {
        "run_id": "test-run",
        "external_tokens": 7,
        "output_attestation": agy_delegate._output_attestation.emit_attestation(
            artifact="summary",
            content=content,
        ),
    }


def test_valid_envelope_normalizes_defaults(agy_delegate: ModuleType) -> None:
    envelope = agy_delegate.Envelope.from_mapping(
        {
            "schema": "agy.delegation.v1",
            "role": "reviewer",
            "task": "Review this bounded change.",
        }
    )

    assert envelope.role == "reviewer"
    assert envelope.mode == "no-write"
    assert envelope.model == "flash"
    assert envelope.write_set == []
    assert envelope.apply_policy == "preserve-patch"
    assert envelope.evidence == "summary"
    assert envelope.verification.commands == []
    assert envelope.verification.required is False
    assert envelope.verification.run_scope == "clone"
    assert envelope.timeout_seconds == 900
    assert envelope.no_output_seconds == 180
    assert envelope.provenance_required is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "planner"),
        ("mode", "auto"),
        ("review_lens", "friendliness"),
        ("apply_policy", "apply-now"),
        ("evidence", "verbose"),
    ],
)
def test_invalid_enum_rejection(agy_delegate: ModuleType, field: str, value: object) -> None:
    payload = _valid_payload(**{field: value})

    with pytest.raises(agy_delegate.EnvelopeError):
        agy_delegate.Envelope.from_mapping(payload)

    with pytest.raises(agy_delegate.EnvelopeError):
        agy_delegate.parse_status("unknown_status")


def test_auto_if_clean_without_write_set_rejected_before_bundle(
    agy_delegate: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(agy_delegate.EnvelopeError):
        agy_delegate.Envelope.from_mapping(_valid_payload(mode="auto-if-clean", write_set=[]))

    assert not (tmp_path / ".claude").exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"write_set": ["/absolute/path.py"]},
        {"verification": {"commands": [], "required": True, "run_scope": "clone"}},
        {"verification": {"commands": ["pytest"], "required": False, "run_scope": "remote"}},
        {"timeout_seconds": 0},
        {"no_output_seconds": 901},
        {"provenance_required": "yes"},
    ],
)
def test_invalid_shape_rejection(agy_delegate: ModuleType, overrides: dict[str, object]) -> None:
    with pytest.raises(agy_delegate.EnvelopeError):
        agy_delegate.Envelope.from_mapping(_valid_payload(**overrides))


def test_bundle_creation_writes_validation_files_and_projection(
    agy_delegate: ModuleType, tmp_path: Path
) -> None:
    envelope = agy_delegate.Envelope.from_mapping(_valid_payload())
    result = agy_delegate.create_validation_bundle(
        envelope,
        repo_root=tmp_path,
        run_id="unit-run",
        argv=["--role", "coder"],
    )

    bundle = tmp_path / ".claude" / "agy" / "runs" / "unit-run"
    assert result.status == "success"
    assert result.bundle_path == bundle

    for filename in (
        "envelope.json",
        "prompt.txt",
        "command.json",
        "run-lease.json",
        "result.json",
        "projection.md",
    ):
        assert (bundle / filename).exists(), f"missing bundle file: {filename}"

    projection = (bundle / "projection.md").read_text(encoding="utf-8")
    result_payload = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    command_payload = json.loads((bundle / "command.json").read_text(encoding="utf-8"))

    assert "Status: success" in projection
    assert f"Bundle: {bundle}" in projection
    assert result_payload["validation_only"] is True
    assert result_payload["agy_launched"] is False
    assert command_payload["agy_launch_planned"] is False


def test_projection_names_bundle_path(agy_delegate: ModuleType, tmp_path: Path) -> None:
    envelope = agy_delegate.Envelope.from_mapping(_valid_payload(evidence="minimal"))
    result = agy_delegate.create_validation_bundle(envelope, repo_root=tmp_path, run_id="named")

    assert str(tmp_path / ".claude" / "agy" / "runs" / "named") in result.projection


def test_bundle_write_failure_reports_bundle_failed(
    agy_delegate: ModuleType, tmp_path: Path
) -> None:
    repo_root = tmp_path / "not-a-directory"
    repo_root.write_text("blocks bundle parent creation", encoding="utf-8")
    envelope = agy_delegate.Envelope.from_mapping(_valid_payload())

    result = agy_delegate.create_validation_bundle(envelope, repo_root=repo_root, run_id="blocked")

    assert result.status == "bundle_failed"
    assert "Status: bundle_failed" in result.projection


def test_cli_flags_normalize_to_envelope(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "flags-run",
            "--role",
            "reviewer",
            "--task",
            "Review the scoped diff.",
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    envelope = json.loads(
        (tmp_path / ".claude" / "agy" / "runs" / "flags-run" / "envelope.json").read_text(
            encoding="utf-8"
        )
    )
    assert completed.returncode == 0
    assert envelope["role"] == "reviewer"
    assert envelope["mode"] == "no-write"


def test_cli_envelope_dry_validation_outputs_projection(tmp_path: Path) -> None:
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps(_valid_payload()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "cli-run",
            "--envelope",
            str(envelope_path),
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    bundle = tmp_path / ".claude" / "agy" / "runs" / "cli-run"
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert "Status: success" in completed.stdout
    assert f"Bundle: {bundle}" in completed.stdout
    assert completed.stdout == (bundle / "projection.md").read_text(encoding="utf-8")


def test_supervised_receipt_maps_pid_argv_exit_code_when_launched(
    agy_delegate: ModuleType, tmp_path: Path
) -> None:
    envelope = agy_delegate.Envelope.from_mapping(_valid_payload(model="flash"))
    started = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 7, 6, 12, 0, 3, tzinfo=UTC)
    run_result = agy_delegate.SupervisedRunResult(
        status="success",
        agy_launched=True,
        resolved_agy="/usr/local/bin/agy",
        argv=["/usr/local/bin/agy", "--role", "coder"],
        process_id=4242,
        return_code=0,
        started_at=started,
        ended_at=ended,
        shutdown="exited",
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_class=None,
        stdout_bytes=120,
        stderr_bytes=8,
    )

    receipt = agy_delegate._supervised_receipt(
        run_result,
        envelope=envelope,
        **_receipt_kwargs(agy_delegate),
    )

    assert receipt is not None
    assert agy_delegate._bridge_receipt.validate_receipt(receipt) == []
    assert receipt["schema"] == "bridge_receipt.v1"
    assert receipt["engine_id"] == "agy"
    assert receipt["variant"] == "flash"
    assert receipt["transport"] == "cli"
    assert receipt["wall_time_s"] == pytest.approx(3.0)
    assert receipt["bytes_produced"] == 128
    assert receipt["runner"] == {
        "pid": 4242,
        "argv": ["/usr/local/bin/agy", "--role", "coder"],
        "exit_code": 0,
    }


@pytest.mark.parametrize(
    "run_result_kwargs",
    [
        pytest.param(
            {
                "status": "error",
                "agy_launched": False,
                "resolved_agy": None,
                "argv": [],
                "process_id": None,
                "return_code": None,
                "shutdown": "not_started",
                "timeout_class": None,
                "stdout_bytes": 0,
                "stderr_bytes": 0,
                "error": "agy executable not found",
            },
            id="agy-missing",
        ),
        pytest.param(
            {
                "status": "error",
                "agy_launched": False,
                "resolved_agy": "/usr/local/bin/agy",
                "argv": ["/usr/local/bin/agy"],
                "process_id": None,
                "return_code": None,
                "shutdown": "not_started",
                "timeout_class": None,
                "stdout_bytes": 0,
                "stderr_bytes": 3,
                "error": "[Errno 13] Permission denied",
            },
            id="oserror-on-launch",
        ),
    ],
)
def test_supervised_receipt_none_on_launch_failure_paths(
    agy_delegate: ModuleType, tmp_path: Path, run_result_kwargs: dict[str, object]
) -> None:
    envelope = agy_delegate.Envelope.from_mapping(_valid_payload())
    timestamp = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
    run_result = agy_delegate.SupervisedRunResult(
        started_at=timestamp,
        ended_at=timestamp,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        **run_result_kwargs,
    )

    assert (
        agy_delegate._supervised_receipt(
            run_result,
            envelope=envelope,
            **_receipt_kwargs(agy_delegate),
        )
        is None
    )

    payload = agy_delegate._result_payload(
        envelope=envelope,
        run_id="failed-run",
        bundle_path=tmp_path / "bundle",
        run_result=run_result,
        stdout_path=run_result.stdout_path,
        stderr_path=run_result.stderr_path,
        summary="launch failed",
        changed_paths=[],
        diff_patch_path=tmp_path / "diff.patch",
        checks_path=tmp_path / "checks.json",
        clone_path=tmp_path / "clone",
    )

    assert "receipt" not in payload
    # The envelope still validates (schema-valid JSON, no receipt-shaped placeholder).
    assert json.loads(json.dumps(payload))["agy_launched"] is False


def test_result_payload_includes_receipt_when_launched(
    agy_delegate: ModuleType, tmp_path: Path
) -> None:
    envelope = agy_delegate.Envelope.from_mapping(_valid_payload(model="pro"))
    started = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 7, 6, 12, 0, 1, tzinfo=UTC)
    run_result = agy_delegate.SupervisedRunResult(
        status="success",
        agy_launched=True,
        resolved_agy="/usr/local/bin/agy",
        argv=["/usr/local/bin/agy"],
        process_id=99,
        return_code=0,
        started_at=started,
        ended_at=ended,
        shutdown="exited",
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_class=None,
        stdout_bytes=10,
        stderr_bytes=0,
    )

    payload = agy_delegate._result_payload(
        envelope=envelope,
        run_id="ok-run",
        bundle_path=tmp_path / "bundle",
        run_result=run_result,
        stdout_path=run_result.stdout_path,
        stderr_path=run_result.stderr_path,
        summary="ran clean",
        changed_paths=[],
        diff_patch_path=tmp_path / "diff.patch",
        checks_path=tmp_path / "checks.json",
        clone_path=tmp_path / "clone",
    )

    assert agy_delegate._bridge_receipt.validate_receipt(payload["receipt"]) == []
    assert payload["receipt"]["variant"] == "pro"
    # Round-trips through JSON exactly as it would when written to result.json.
    reloaded = json.loads(json.dumps(payload))
    assert reloaded["receipt"]["runner"]["pid"] == 99


def test_run_agy_supervised_missing_agy_emits_no_receipt(
    agy_delegate: ModuleType, tmp_path: Path
) -> None:
    envelope = agy_delegate.Envelope.from_mapping(_valid_payload())
    run_result = agy_delegate.run_agy_supervised(
        envelope,
        prompt="do the thing",
        repo_root=tmp_path,
        bundle_path=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        agy_bin=str(tmp_path / "no-such-agy-binary"),
    )

    assert run_result.agy_launched is False
    assert (
        agy_delegate._supervised_receipt(
            run_result,
            envelope=envelope,
            **_receipt_kwargs(agy_delegate),
        )
        is None
    )


def test_run_agy_supervised_forces_cmux_bypass(
    agy_delegate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_agy = tmp_path / "fake-agy"
    fake_agy.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "print(os.environ.get('CMUX_AGENT_BYPASS', ''), flush=True)\n",
        encoding="utf-8",
    )
    fake_agy.chmod(0o755)
    monkeypatch.setenv("CMUX_AGENT_BYPASS", "0")

    envelope = agy_delegate.Envelope.from_mapping(_valid_payload())
    stdout_path = tmp_path / "stdout.log"
    run_result = agy_delegate.run_agy_supervised(
        envelope,
        prompt="do the thing",
        repo_root=tmp_path,
        bundle_path=tmp_path,
        stdout_path=stdout_path,
        stderr_path=tmp_path / "stderr.log",
        agy_bin=str(fake_agy),
    )

    assert run_result.status == "success"
    assert stdout_path.read_text(encoding="utf-8") == "1\n"


def test_run_agy_supervised_oserror_on_launch_emits_no_receipt(
    agy_delegate: ModuleType, tmp_path: Path
) -> None:
    envelope = agy_delegate.Envelope.from_mapping(_valid_payload())
    # A directory is a "found" path but not executable: Popen raises OSError on launch.
    not_executable = tmp_path / "a-directory-not-a-binary"
    not_executable.mkdir()

    run_result = agy_delegate.run_agy_supervised(
        envelope,
        prompt="do the thing",
        repo_root=tmp_path,
        bundle_path=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        agy_bin=str(not_executable),
    )

    assert run_result.agy_launched is False
    assert run_result.error is not None
    assert (
        agy_delegate._supervised_receipt(
            run_result,
            envelope=envelope,
            **_receipt_kwargs(agy_delegate),
        )
        is None
    )


def test_cli_rejects_invalid_envelope_without_bundle(tmp_path: Path) -> None:
    # `auto-if-clean` is the retired live-apply mode (#671). Rejecting it here does double duty:
    # it proves an invalid envelope never reaches bundle creation, and it fails loudly if the mode
    # is ever re-added without the rest of this contract being reconsidered.
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(
        json.dumps(_valid_payload(mode="auto-if-clean", write_set=[])),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "bad-run",
            "--envelope",
            str(envelope_path),
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "mode has invalid value 'auto-if-clean'" in completed.stderr
    assert not (tmp_path / ".claude").exists()


@pytest.mark.parametrize(
    (
        "status",
        "return_code",
        "shutdown",
        "timeout_class",
        "provenance_required",
        "expected_status",
        "expect_coerced",
    ),
    [
        pytest.param(
            "success", 1, "exited", None, True, "fallback_suspected", True, id="unproven-required"
        ),
        pytest.param(
            "success", 1, "exited", None, False, "success", False, id="unproven-not-required"
        ),
        pytest.param("success", 0, "exited", None, True, "success", False, id="proven-required"),
        pytest.param(
            "fallback_suspected",
            1,
            "exited",
            None,
            True,
            "fallback_suspected",
            False,
            id="already-fallback-suspected-not-double-coerced",
        ),
    ],
)
def test_provenance_required_coerces_fallback(
    agy_delegate: ModuleType,
    tmp_path: Path,
    status: str,
    return_code: int | None,
    shutdown: str,
    timeout_class: str | None,
    provenance_required: bool,
    expected_status: str,
    expect_coerced: bool,
) -> None:
    """R1/KTD1: provenance_required wires _real_agy_verdict into status/exit.

    - unproven + required -> coerced to fallback_suspected (exit 1 via :1167 mapping).
    - unproven + not required -> unchanged (today's behavior byte-for-byte).
    - proven (real verdict) + required -> unchanged.
    - already fallback_suspected (marker path, :1374) + required -> stays
      fallback_suspected, not double-coerced (no duplicate coerced_by bookkeeping).
    """
    envelope = agy_delegate.Envelope.from_mapping(
        _valid_payload(provenance_required=provenance_required)
    )
    started = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 7, 7, 12, 0, 1, tzinfo=UTC)
    run_result = agy_delegate.SupervisedRunResult(
        status=status,
        agy_launched=True,
        resolved_agy="/usr/local/bin/agy",
        argv=["/usr/local/bin/agy"],
        process_id=99,
        return_code=return_code,
        started_at=started,
        ended_at=ended,
        shutdown=shutdown,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_class=timeout_class,
        stdout_bytes=10,
        stderr_bytes=0,
    )

    payload = agy_delegate._result_payload(
        envelope=envelope,
        run_id="provenance-run",
        bundle_path=tmp_path / "bundle",
        run_result=run_result,
        stdout_path=run_result.stdout_path,
        stderr_path=run_result.stderr_path,
        summary="ran",
        changed_paths=[],
        diff_patch_path=tmp_path / "diff.patch",
        checks_path=tmp_path / "checks.json",
        clone_path=tmp_path / "clone",
    )

    assert payload["status"] == expected_status
    # Exit-code contract observed through the module's own single-source mapping —
    # main() returns _exit_code_for_status(result.status); no duplicated status set here.
    expect_exit_zero = expected_status in agy_delegate._PASSING_STATUSES
    assert agy_delegate._exit_code_for_status(payload["status"]) == (0 if expect_exit_zero else 1)
    if expect_coerced:
        assert payload.get("coerced_by") == "provenance_required"
    else:
        assert "coerced_by" not in payload


def test_blocked_status_marker_parsing_produces_fallback_suspected(
    agy_delegate: ModuleType, tmp_path: Path
) -> None:
    """The stdout-marker parser is the real producer of the 'already fallback_suspected'
    state the no-double-coercion case above starts from — exercise it against real log
    content so the marker path cannot regress unnoticed (#390 review F1)."""
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    stdout_path.write_text("agy output\nFALLBACK_SUSPECTED: no genuine engine invocation\n")
    stderr_path.write_text("")
    assert agy_delegate._blocked_status_from_logs(stdout_path, stderr_path) == "fallback_suspected"

    stdout_path.write_text("agy output, clean run\n")
    assert agy_delegate._blocked_status_from_logs(stdout_path, stderr_path) is None

    # Marker in stderr alone is also honored (the parser reads both streams).
    stderr_path.write_text("TEST_CONFLICT: fixture collision\n")
    assert agy_delegate._blocked_status_from_logs(stdout_path, stderr_path) == "test_conflict"


# --- durable audit-store mirroring (#396, U3) ------------------------------------------------


def _load_audit_store() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_store", AUDIT_STORE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_store"] = module
    spec.loader.exec_module(module)
    return module


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True
    )


def test_audit_store_survives_bundle_deletion(tmp_path: Path) -> None:
    """A receipt written under --audit-store is still readable by run_id after the working
    bundle directory is deleted (the literal DoD acceptance check for issue #396)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(
        json.dumps(_valid_payload(task="FAKE_AGY_MODE=success")), encoding="utf-8"
    )
    audit_store_root = tmp_path / "audit-store"

    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(repo),
            "--run-id",
            "durable-run",
            "--envelope",
            str(envelope_path),
            "--launch-agy",
            "--agy-bin",
            str(FAKE_AGY),
            "--audit-store",
            str(audit_store_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    bundle_path = repo / ".claude" / "agy" / "runs" / "durable-run"
    assert (bundle_path / "result.json").exists()

    # The bundle directory — the disposable-worktree blast radius the issue names — is gone.
    shutil.rmtree(bundle_path)
    assert not bundle_path.exists()

    audit_store = _load_audit_store()
    store = audit_store.Store.for_root(audit_store_root)
    receipt = audit_store.resolve_receipt(store, "durable-run")

    assert receipt is not None
    assert receipt["run_id"] == "durable-run"
    assert receipt["schema"] == "bridge_receipt.v1"


def test_validation_bundle_mirrors_result_without_receipt(tmp_path: Path) -> None:
    """A validation-only bundle (agy never launches) mirrors result.json but no receipt.json —
    there is nothing to prove was run."""
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps(_valid_payload()), encoding="utf-8")
    audit_store_root = tmp_path / "audit-store"

    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "validation-only-run",
            "--envelope",
            str(envelope_path),
            "--audit-store",
            str(audit_store_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    audit_store = _load_audit_store()
    store = audit_store.Store.for_root(audit_store_root)

    result = audit_store.resolve_result(store, "validation-only-run")
    assert result is not None
    assert result["agy_launched"] is False

    assert audit_store.resolve_receipt(store, "validation-only-run") is None
