"""Portable launch-contract tests for the agent-launcher package.

Adapted from the portable half of upstream ``tests/test_launcher_contract.py``
(infiquetra-claude-plugins, plugin 1.0.0 at the pinned revision). Upstream test
names are cited per adaptation so the subset stays auditable against the pin:

- argv/preview ordering, CLI argv, skip-preview refusal
- malformed receipt, nonzero wrapper exit, startup timeout
- prompt-delivery failure recording
- close ownership quartet, preexisting-tab cwd mismatch, ownership snapshot
- confirm_preview cwd/workspace mismatches
- preflight receipt confirmed-vs-requested separation
- cwd mismatch closes only owned sessions, kind mismatch stops
- task-name path safety (separator refusal, pane_text traversal refusal)
- failed launch persists tab_id, CLI undelivered exit code

The upstream tests covering Orchestrate ingestion, Orchestrate's dependency
declaration, and the upstream root marketplace remain upstream: those premises
do not cross the port boundary (see ``ports/agent-launcher.json``).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
LAUNCHER = PACKAGE / "skills" / "agent-launcher" / "scripts" / "launcher.py"

BACKGROUND_FLAGS = ("--no-focus", "--current", "--herdr", "--herdr-control-only")


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    return _load(LAUNCHER, "_agent_launcher_portable_contract")


@pytest.fixture
def launcher_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "agents"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    monkeypatch.delenv("ORCHESTRATE_AGENT_LAUNCHER", raising=False)
    return binary


@pytest.mark.usefixtures("launcher_on_path")
@pytest.mark.parametrize("vendor", ["claude", "codex", "grok", "muse", "agy", "qwen", "opencode"])
def test_argv_locks_background_flags_before_vendor(launcher: ModuleType, vendor: str) -> None:
    unit = launcher.LaunchRequest(name="reviewer", vendor=vendor, worktree="/tmp/wt")
    argv = launcher.agent_argv(unit)
    vendor_idx = argv.index(vendor)
    for flag in BACKGROUND_FLAGS:
        assert flag in argv
        assert argv.index(flag) < vendor_idx
    assert argv[argv.index("--cwd") + 1] == "/tmp/wt"
    assert argv[argv.index("--task") + 1] == "reviewer"


@pytest.mark.usefixtures("launcher_on_path")
def test_preview_argv_puts_dry_run_in_launcher_position(launcher: ModuleType) -> None:
    unit = launcher.LaunchRequest(
        name="reviewer",
        vendor="codex",
        worktree="/tmp/wt",
        model="gpt-5.4",
        effort="xhigh",
        permission="auto",
    )
    argv = launcher.preview_argv(unit)
    assert argv[1] == "--dry-run"
    assert argv.index("--dry-run") < argv.index("codex")
    assert "--no-focus" in argv
    vendor_tail = argv[argv.index("codex") :]
    assert vendor_tail[:1] == ["codex"]
    assert "--model" in vendor_tail
    assert "gpt-5.4" in vendor_tail
    assert any(
        part.startswith("model_reasoning_effort=") or part == "xhigh" for part in vendor_tail
    )


@pytest.mark.usefixtures("launcher_on_path")
def test_cli_argv_subprocess_builds_the_wrapper_command(launcher_on_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            "argv",
            "--vendor",
            "codex",
            "--task",
            "plain-session",
            "--cwd",
            "/tmp/plain",
            "--model",
            "gpt-5.4",
            "--effort",
            "xhigh",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": str(launcher_on_path.parent) + os.pathsep + os.environ.get("PATH", ""),
        },
    )
    assert proc.returncode == 0, proc.stderr
    argv = proc.stdout.strip().split()
    assert "codex" in argv
    assert "--no-focus" in argv
    assert "--herdr-control-only" in argv
    assert argv[argv.index("--cwd") + 1] == str(Path("/tmp/plain").resolve())


def test_cli_refuses_skip_preview(launcher_on_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            "launch",
            "--vendor",
            "codex",
            "--task",
            "x",
            "--skip-preview",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": str(launcher_on_path.parent) + os.pathsep + os.environ.get("PATH", ""),
        },
    )
    assert proc.returncode != 0
    assert "preview" in (proc.stderr + proc.stdout).lower()


def test_malformed_receipt_stops_launch(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrapper = tmp_path / "agents"
    wrapper.write_text("#!/bin/sh\necho not-json\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    monkeypatch.setattr(launcher, "list_tab_ids", lambda *_a, **_k: frozenset())
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    unit = launcher.LaunchRequest(name="broken", vendor="codex", worktree=str(tmp_path))
    with pytest.raises(SystemExit, match="JSON"):
        launcher.launch(unit)


def test_nonzero_wrapper_exit_stops_launch(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrapper = tmp_path / "agents"
    wrapper.write_text("#!/bin/sh\necho fail >&2\nexit 3\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    monkeypatch.setattr(launcher, "list_tab_ids", lambda *_a, **_k: frozenset())
    unit = launcher.LaunchRequest(name="failing", vendor="codex", worktree=str(tmp_path))
    with pytest.raises(SystemExit, match="command failed"):
        launcher.launch(unit)


def test_startup_timeout_is_a_result_not_a_crash(launcher: ModuleType) -> None:
    result = launcher.run(["sleep", "2"], check=False, timeout=0.1)
    assert result.returncode == 124
    assert result.stderr == "timed out"


def test_prompt_delivery_failure_records_undelivered(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrapper = tmp_path / "agents"
    receipt = {
        "tab_id": "tab-1",
        "agent_name": "reviewer-2",
        "pane_id": "pane-1",
        "reused": False,
    }
    wrapper.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(receipt) + "\nEOF\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    monkeypatch.setattr(launcher, "list_tab_ids", lambda *_a, **_k: frozenset())
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(launcher, "verify_unit_preflight", lambda *a, **k: {})
    monkeypatch.setattr(launcher, "send", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: False)
    monkeypatch.setattr(launcher, "agent_row", lambda *_a, **_k: {"agent_status": "idle"})
    monkeypatch.setattr(launcher.time, "sleep", lambda *_a, **_k: None)
    unit = launcher.LaunchRequest(name="reviewer", vendor="codex", worktree=str(tmp_path))
    launcher.launch(unit)
    assert unit.status == launcher.PROMPT_UNDELIVERED
    assert launcher.DELIVERY_WARNING in unit.note
    assert unit.launch_receipt["prompt_delivered"] is False
    assert unit.launch_receipt["agent_name"] == "reviewer-2"
    assert unit.tab_id == "tab-1"


def test_close_without_receipt_tab_id_stops(launcher: ModuleType) -> None:
    unit = launcher.LaunchRequest(name="x", vendor="codex", tab_id="tab-1")
    with pytest.raises(SystemExit, match="ownership"):
        launcher.close_owned_session(unit, receipt={})


def test_close_mismatched_receipt_stops(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[str] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        closed.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="x", vendor="codex", tab_id="tab-1")
    with pytest.raises(SystemExit, match="does not match"):
        launcher.close_owned_session(unit, receipt={"tab_id": "tab-other", "owned": True})
    assert closed == []


def test_close_owned_session_closes_only_receipt_tab(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        closed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="x", vendor="codex", tab_id="tab-owned")
    launcher.close_owned_session(unit, receipt={"tab_id": "tab-owned", "owned": True})
    assert closed == [["herdr", "tab", "close", "tab-owned"]]


def test_preexisting_tab_is_not_owned(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ownership is launcher-side: tab_id present in the pre-launch snapshot is not owned."""
    closed: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        closed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    preexisting = frozenset({"w80:t4", "w80:t1"})
    assert launcher.tab_was_created("w80:t4", preexisting) is False
    assert launcher.tab_was_created("w80:t9", preexisting) is True
    unit = launcher.LaunchRequest(name="u-port", vendor="codex", tab_id="w80:t4", owned=False)
    receipt = {"tab_id": "w80:t4", "owned": False}
    launcher.close_run_session(unit)
    assert closed == []
    with pytest.raises(SystemExit, match="existed before this launch"):
        launcher.close_owned_session(unit, receipt=receipt)
    assert closed == []


def test_cwd_mismatch_on_preexisting_tab_does_not_close(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["herdr", "tab", "close"]:
            closed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "pane-1",
            "cwd": "/tmp/other",
            "interactive_ready": True,
            "agent": "codex",
        },
    )
    unit = launcher.LaunchRequest(
        name="reviewer",
        vendor="codex",
        worktree="/tmp/wt",
        pane_id="pane-1",
        tab_id="tab-1",
        owned=False,
        launch_receipt={"tab_id": "tab-1", "owned": False},
    )
    with pytest.raises(SystemExit, match="working directory"):
        launcher.verify_unit_preflight(unit, "pane-1", ready=True)
    assert closed == []


def test_ownership_is_tab_id_not_in_prelaunch_snapshot(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed: list[str] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        listed.append(" ".join(cmd))
        if cmd[:3] == ["herdr", "tab", "list"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {
                        "result": {
                            "tabs": [
                                {"tab_id": "w80:t1", "label": "old"},
                                {"tab_id": "w80:t4", "label": "u-port"},
                            ]
                        }
                    }
                ),
                "",
            )
        if cmd[:3] == ["herdr", "pane", "current"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps({"result": {"pane": {"workspace_id": "w80"}}}),
                "",
            )
        return subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps(
                {
                    "tab_id": "w80:t9",
                    "agent_name": "smoke",
                    "pane_id": "w80:p9",
                    "reused": True,
                }
            ),
            "",
        )

    monkeypatch.setattr(launcher, "run", fake_run)
    # launch() resolves the wrapper in agent_argv before run(); stubbing run is not enough.
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(
        launcher,
        "verify_unit_preflight",
        lambda *a, **k: (_ for _ in ()).throw(SystemExit("stop after identity")),
    )
    unit = launcher.LaunchRequest(name="smoke", vendor="codex", worktree="/tmp/wt")
    with pytest.raises(SystemExit, match="stop after identity"):
        launcher.launch(unit)
    assert unit.tab_id == "w80:t9"
    assert unit.owned is True
    assert unit.launch_receipt["owned"] is True
    assert unit.launch_receipt["reused"] is True
    assert any("tab list" in c for c in listed)


def test_confirm_preview_stops_on_cwd_mismatch(launcher: ModuleType) -> None:
    with pytest.raises(SystemExit, match="cwd"):
        launcher.confirm_preview(
            {"cwd": "/tmp/other", "herdr_workspace": "<current-terminal:w1>"},
            "/tmp/expected",
            "w1",
        )


def test_confirm_preview_stops_on_workspace_mismatch(launcher: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="workspace"):
        launcher.confirm_preview(
            {"cwd": str(tmp_path), "herdr_workspace": "<current-terminal:w9>"},
            str(tmp_path),
            "w1",
        )


def test_herdr_readback_receipt_separates_confirmed_from_requested(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "pane-1",
            "cwd": "/tmp/wt",
            "workspace_id": "w1",
            "interactive_ready": True,
            "agent": "codex",
        },
    )
    monkeypatch.setattr(launcher, "workspace_id_for_name", lambda name: "w1" if name else None)
    monkeypatch.setattr(launcher, "verify_unit_account", lambda *a, **k: None)
    unit = launcher.LaunchRequest(
        name="reviewer",
        vendor="codex",
        worktree="/tmp/wt",
        workspace="review",
        model="gpt-5.4",
        effort="xhigh",
        pane_id="pane-1",
        tab_id="tab-1",
    )
    receipt = launcher.verify_unit_preflight(unit, "pane-1", ready=True)
    assert "pane" in receipt["confirmed_against_herdr"]
    assert "kind" in receipt["confirmed_against_herdr"]
    assert "working_directory" in receipt["confirmed_against_herdr"]
    assert "workspace" in receipt["confirmed_against_herdr"]
    assert "readiness" in receipt["confirmed_against_herdr"]
    assert "model" in receipt["requested_only"]
    assert "permission" in receipt["requested_only"]
    assert "permission" not in receipt["confirmed_against_herdr"]
    assert receipt["agent_name"] is None or "agent_name" in receipt
    assert receipt["permission"] == "auto"
    assert receipt["kind"] == "codex"
    assert receipt["verified"] is True


def test_herdr_cwd_mismatch_closes_owned_session(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An owned session is closed through herdr when its cwd disagrees; the
    close must be a real herdr tab close, proved through the run seam."""
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "pane-1",
            "cwd": "/tmp/other",
            "interactive_ready": True,
            "agent": "codex",
        },
    )
    unit = launcher.LaunchRequest(
        name="reviewer",
        vendor="codex",
        worktree="/tmp/wt",
        pane_id="pane-1",
        tab_id="tab-1",
        owned=True,
        launch_receipt={"tab_id": "tab-1", "owned": True},
    )
    with pytest.raises(SystemExit, match="working directory"):
        launcher.verify_unit_preflight(unit, "pane-1", ready=True)
    assert ["herdr", "tab", "close", "tab-1"] in commands


def test_kind_mismatch_stops_before_prompt(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "pane-1",
            "cwd": "/tmp/wt",
            "interactive_ready": True,
            "agent": "claude",
        },
    )
    unit = launcher.LaunchRequest(
        name="reviewer", vendor="codex", worktree="/tmp/wt", pane_id="pane-1", tab_id="tab-1"
    )
    with pytest.raises(SystemExit, match="herdr reports agent 'claude'"):
        launcher.verify_unit_preflight(unit, "pane-1", ready=True)


def test_task_name_with_separator_is_refused_before_any_write(launcher: ModuleType) -> None:
    with pytest.raises(SystemExit, match="path separator"):
        launcher.assert_safe_path_component("../victim/TASK", "task name")
    with pytest.raises(SystemExit, match="path separator"):
        launcher._request_from_args(
            type(
                "NS",
                (),
                {
                    "task": "feature/auth-review",
                    "cwd": "/tmp",
                    "vendor": "codex",
                    "prompt": "x",
                    "model": None,
                    "effort": None,
                    "account": None,
                    "permission": "auto",
                    "launch_arg": [],
                    "workspace": None,
                    "variant": None,
                },
            )()
        )


def test_pane_text_refuses_traversal_name(launcher: ModuleType, tmp_path: Path) -> None:
    unit = launcher.LaunchRequest(name="../victim", vendor="codex", worktree=str(tmp_path))
    long_text = "x" * (launcher.PANE_TYPING_LIMIT + 1)
    with pytest.raises(SystemExit, match="path"):
        launcher.pane_text(unit, long_text)


def test_failed_launch_persists_tab_id_for_close(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrapper = tmp_path / "agents"
    wrapper.write_text(
        "#!/bin/sh\n"
        + "cat <<'EOF'\n"
        + json.dumps(
            {
                "tab_id": "tab-recover",
                "agent_name": "reviewer-2",
                "pane_id": "pane-1",
                "reused": False,
            }
        )
        + "\nEOF\n"
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    monkeypatch.setattr(launcher, "list_tab_ids", lambda *_a, **_k: frozenset())
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(
        launcher,
        "verify_unit_preflight",
        lambda *a, **k: (_ for _ in ()).throw(SystemExit("preflight failed")),
    )
    unit = launcher.LaunchRequest(name="reviewer", vendor="codex", worktree=str(tmp_path))
    with pytest.raises(SystemExit, match="preflight failed"):
        launcher.launch(unit)
    assert unit.tab_id == "tab-recover"
    assert unit.owned is True
    assert unit.launch_receipt["tab_id"] == "tab-recover"
    assert unit.launch_receipt["agent_name"] == "reviewer-2"
    assert unit.launch_receipt["reused"] is False
    assert unit.launch_receipt["owned"] is True


def test_cli_undelivered_prompt_exits_nonzero(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrapper = tmp_path / "agents"
    wrapper.write_text("#!/bin/sh\necho dry\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    unit = launcher.LaunchRequest(
        name="reviewer",
        vendor="codex",
        worktree=str(tmp_path),
        status=launcher.PROMPT_UNDELIVERED,
        launch_receipt={"tab_id": "t", "prompt_delivered": False, "reused": False},
    )
    monkeypatch.setattr(launcher, "preview_argv", lambda *_a, **_k: ["agents", "--dry-run"])
    monkeypatch.setattr(
        launcher,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(["agents"], 0, "cwd=x\n", ""),
    )
    monkeypatch.setattr(
        launcher,
        "parse_dry_run",
        lambda _s: {"cwd": str(tmp_path), "herdr_workspace": "<current-terminal:w1>"},
    )
    monkeypatch.setattr(launcher, "confirm_preview", lambda *_a, **_k: None)
    monkeypatch.setattr(launcher, "current_herdr_workspace_id", lambda: "w1")
    monkeypatch.setattr(launcher, "launch", lambda *_a, **_k: None)
    monkeypatch.setattr(
        launcher,
        "_request_from_args",
        lambda _args: unit,
    )
    rc = launcher.cli_main(
        [
            "launch",
            "--vendor",
            "codex",
            "--task",
            "reviewer",
            "--cwd",
            str(tmp_path),
        ]
    )
    assert rc == 1
