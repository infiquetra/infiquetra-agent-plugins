"""Contract tests for the portable agent-launcher plugin (#777)."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
LAUNCHER = (
    REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "scripts" / "launcher.py"
)

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
    return _load(LAUNCHER, "_agent_launcher_contract")


@pytest.fixture
def launcher_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "agents"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    monkeypatch.delenv("ORCHESTRATE_AGENT_LAUNCHER", raising=False)
    return binary


def _no_host_herdr(launcher: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the herdr reading a fresh launch takes before any stub these tests set.

    ``launch()`` snapshots the target workspace's tabs to decide whether it created the tab, and
    an unowned session is then identity-checked against ``herdr agent list``. Left unstubbed the
    snapshot asks whatever herdr is on PATH. On the operator's machine that was a live herdr: it
    answered, the receipt tab was absent from its list, ownership was proved and the identity
    check never ran. A runner has no herdr, so ownership was unprovable, the identity check ran
    and stopped the launch before the stage the test was about (issue 907, U34). An empty snapshot
    is the fresh-tab case these tests describe, and it is the same answer on every host.
    """
    monkeypatch.setattr(launcher, "list_tab_ids", lambda *_a, **_k: frozenset())














def test_ingested_launcher_resolves_composer_from_its_own_compile_path() -> None:
    """ARCH-12: the caller's compile filename is the loader's only authority for where the
    sibling composer.py lives. A placeholder produces the named stop naming the wrong
    directory; the real path loads the parser. Replaces the source-grep assertion."""
    source = LAUNCHER.read_text(encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        _exec_launcher_source(source, "wrong-dir/launcher.py")
    message = str(exc_info.value)
    assert "cannot load agent-launcher composer parser" in message
    assert "file is missing" in message
    assert "wrong-dir" in message
    namespace = _exec_launcher_source(source, str(LAUNCHER))
    assert namespace["COMPOSER_GLYPH_BY_VENDOR"]["claude"] == "❯"


def _exec_launcher_source(source: str, compile_filename: str) -> dict[str, Any]:
    """Exec launcher.py the way Orchestrate ingests it, into a sys.modules-registered module
    namespace whose dataclasses can resolve their module, and clean the registration up."""
    probe = ModuleType("_agent_launcher_compile_probe")
    sys.modules["_agent_launcher_compile_probe"] = probe
    try:
        exec(compile(source, compile_filename, "exec"), probe.__dict__)
    finally:
        sys.modules.pop("_agent_launcher_compile_probe", None)
    return probe.__dict__


def _composer_module_name_probe() -> str:
    """The composer module name one fresh process chose for this launcher's parser."""
    code = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('probe_launcher', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['probe_launcher'] = module\n"
        "spec.loader.exec_module(module)\n"
        "print([n for n in sys.modules if n.startswith('_agent_launcher_composer')][0])\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(LAUNCHER)],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_composer_module_name_is_a_stable_digest_of_the_resolved_path() -> None:
    """ARCH-09: the synthetic module name is the documented digest form of the resolved
    composer path -- identical in every process, where abs(hash(path)) was randomised per
    process. The digest assertion is the deterministic kill; the two-process equality is
    the same guarantee observed across a process boundary."""
    composer_path = (LAUNCHER.parent / "composer.py").resolve()
    expected = (
        "_agent_launcher_composer_" + hashlib.sha256(str(composer_path).encode()).hexdigest()[:16]
    )
    first = _composer_module_name_probe()
    second = _composer_module_name_probe()
    assert first == expected
    assert first == second


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
def test_cli_argv_does_not_import_orchestrate(launcher_on_path: Path) -> None:
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
    _no_host_herdr(launcher, monkeypatch)
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
    _no_host_herdr(launcher, monkeypatch)
    unit = launcher.LaunchRequest(name="failing", vendor="codex", worktree=str(tmp_path))
    with pytest.raises(SystemExit, match="command failed"):
        launcher.launch(unit)


def test_hanging_create_stops_at_the_deadline(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = {
        "tab_id": "tab-1",
        "agent_name": "hangs-2",
        "pane_id": "pane-1",
        "reused": False,
    }
    wrapper = tmp_path / "agents"
    wrapper.write_text("#!/bin/sh\nsleep 5\ncat <<'EOF'\n" + json.dumps(receipt) + "\nEOF\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    _no_host_herdr(launcher, monkeypatch)
    monkeypatch.setattr(launcher, "LAUNCH_CREATE_SECONDS", 0.5)
    # Stub the post-create stages so that, with the timeout removed, the launch proceeds past the
    # create into a differently-worded stop instead of blocking the test out on a real one.
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(
        launcher,
        "verify_unit_preflight",
        lambda *a, **k: (_ for _ in ()).throw(SystemExit("stop after identity")),
    )
    unit = launcher.LaunchRequest(name="hangs", vendor="codex", worktree=str(tmp_path))
    start = time.monotonic()
    with pytest.raises(SystemExit, match="timed out after"):
        launcher.launch(unit)
    elapsed = time.monotonic() - start
    assert elapsed < 3.0, f"the create took {elapsed:.1f}s; the deadline did not stop it"


def test_launch_create_deadline_is_a_named_constant(launcher: ModuleType) -> None:
    assert "LAUNCH_CREATE_SECONDS" in inspect.getsource(launcher.launch)
    assert isinstance(launcher.LAUNCH_CREATE_SECONDS, float)
    assert 0 < launcher.LAUNCH_CREATE_SECONDS <= 300


def test_pane_read_and_transcript_slack_bounds_are_pinned(launcher: ModuleType) -> None:
    assert 0 < launcher.PANE_INPUT_READ_SECONDS <= 10
    assert 0 <= launcher.TRANSCRIPT_MTIME_SLACK_SECONDS <= 2


def test_create_timeout_reconciles_one_new_target_workspace_tab(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "list_tab_ids", lambda _workspace=None: frozenset({"w1:t-new"}))
    unit = launcher.LaunchRequest(name="timed", vendor="codex")
    detail = launcher._record_create_timeout(
        unit,
        preexisting=frozenset(),
        workspace_id="w1",
    )
    assert "w1:t-new" in detail
    assert unit.tab_id == "w1:t-new"
    assert unit.launch_receipt["create_timeout_new_tabs"] == ["w1:t-new"]
    assert unit.launch_receipt["owned"] is True


def test_genuine_wrapper_exit_124_preserves_its_receipt(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = {
        "tab_id": "tab-124",
        "agent_name": "worker-124",
        "pane_id": "pane-124",
        "reused": False,
    }
    wrapper = tmp_path / "agents"
    wrapper.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(receipt) + "'\nexit 124\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    _no_host_herdr(launcher, monkeypatch)
    unit = launcher.LaunchRequest(name="worker", vendor="codex", worktree=str(tmp_path))
    with pytest.raises(SystemExit, match=r"command failed \(124\)"):
        launcher.launch(unit)
    assert unit.tab_id == "tab-124"
    assert unit.launch_receipt["agent_name"] == "worker-124"


def test_create_within_the_deadline_is_unaffected(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = {
        "tab_id": "tab-1",
        "agent_name": "reviewer-2",
        "pane_id": "pane-1",
        "reused": False,
    }
    wrapper = tmp_path / "agents"
    wrapper.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(receipt) + "\nEOF\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    _no_host_herdr(launcher, monkeypatch)
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(
        launcher,
        "verify_unit_preflight",
        lambda *a, **k: (_ for _ in ()).throw(SystemExit("stop after identity")),
    )
    unit = launcher.LaunchRequest(name="reviewer", vendor="codex", worktree=str(tmp_path))
    with pytest.raises(SystemExit, match="stop after identity"):
        launcher.launch(unit)
    assert unit.tab_id == "tab-1"


def test_ownership_snapshot_uses_the_unit_target_workspace(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed: list[str | None] = []
    receipt = {
        "tab_id": "w9:t-new",
        "agent_name": "reviewer-2",
        "pane_id": "w9:p1",
        "reused": True,
    }
    monkeypatch.setattr(launcher, "workspace_id_for_name", lambda name: "w9")

    def list_target_tabs(workspace: str | None = None) -> frozenset[str]:
        listed.append(workspace)
        return frozenset({"w9:t-old"})

    monkeypatch.setattr(launcher, "list_tab_ids", list_target_tabs)
    monkeypatch.setattr(
        launcher,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), ""),
    )
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(
        launcher,
        "verify_unit_preflight",
        lambda *a, **k: (_ for _ in ()).throw(SystemExit("stop after snapshot")),
    )
    unit = launcher.LaunchRequest(
        name="reviewer", vendor="codex", workspace="target", worktree="/tmp/wt"
    )
    with pytest.raises(SystemExit, match="stop after snapshot"):
        launcher.launch(unit)
    assert listed == ["w9"]
    assert unit.owned is True


CODEX_PLACEHOLDER = "\x1b[38;2;153;153;153m› Ask Codex to do anything\x1b[0m"
STAGED_SLASH_COMMAND = "/saga:doc-review docs/plans/x.md"
CAPTURED_COMPOSERS = json.loads(
    (Path(__file__).parent / "fixtures" / "composer-panes.json").read_text(encoding="utf-8")
)
# The parser module loaded for its private glyph rosters only; every state assertion goes
# through the launcher fixture so class identity never crosses module boundaries.
COMPOSER_MODULE = _load(
    REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "scripts" / "composer.py",
    "_agent_launcher_contract_composer",
)
# Full `herdr pane read --source visible --format ansi` dumps of two idle Claude sessions in
# workspace wEV (Herdr 0.8.2): the marker row sits between two horizontal-rule rows with three
# two-space-indented status rows below the lower rule. Captured 2026-09-02 from wEV:pG and
# wEV:pQ; the plan's 2026-09-01 captures came from wEV:pM and wEV:p6, which no longer exist.
# Every capture's origin, including the two older 2026-08-30 rows whose pane ids were never
# recorded, is in the fixture's own `_provenance` block (terminal review F34).
LIVE_CLAUDE_IDLE_KEYS = (
    "claude_live_idle_2026-09-02_herdr0.8.2_wEV-pG",
    "claude_live_idle_2026-09-02_herdr0.8.2_wEV-pQ",
)
# The complete border rosters as the test's own pinned expectation: the parametrised cases
# must survive a shrunk roster, so they cannot be derived from the module under mutation.
LEADING_BORDER_ROSTER = "│┃┆┇┊┋╎╏▏▎▍▌▋▊▉█╭╰┌└"
TRAILING_BORDER_ROSTER = "│┃┆┇┊┋╎╏▏▎▍▌▋▊▉█╮╯┐┘"


def _claude_pane(composer_line: str) -> str:
    rule = "\x1b[2m──────────────────────────────\x1b[0m"
    return f"{rule}\n{composer_line}\n{rule}\n"


def _make_fake_run(
    recorded: list[list[str]],
    *,
    pane_dump: str,
    existing_tabs: tuple[str, ...],
    receipt: dict[str, object],
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        if cmd[:3] == ["herdr", "tab", "list"]:
            tabs = {"result": {"tabs": [{"tab_id": t, "label": t} for t in existing_tabs]}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(tabs), "")
        if cmd[:3] == ["herdr", "pane", "current"]:
            pane = {"result": {"pane": {"workspace_id": "w80"}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(pane), "")
        if cmd[:3] == ["herdr", "pane", "read"]:
            return subprocess.CompletedProcess(cmd, 0, pane_dump, "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), "")

    return fake_run


def _prepare_guard_launch(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pane_dump: str,
    receipt_tab: str,
    existing_tabs: tuple[str, ...],
    vendor: str = "claude",
) -> tuple[Any, list[list[str]], list[tuple[Any, ...]]]:
    recorded: list[list[str]] = []
    sends: list[tuple[Any, ...]] = []
    receipt = {
        "tab_id": receipt_tab,
        "agent_name": "reviewer-2",
        "pane_id": "w80:p9",
        "reused": True,
    }
    inner = _make_fake_run(
        recorded, pane_dump=pane_dump, existing_tabs=existing_tabs, receipt=receipt
    )

    def fake_run(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        # The writes themselves are observed at the Herdr boundary, never by stubbing the
        # writer: a stubbed send once hid that the guard inside it never ran.
        if cmd[:3] == ["herdr", "agent", "prompt"] or cmd[:3] == ["herdr", "pane", "run"]:
            sends.append(tuple(cmd))
        return inner(cmd, **k)

    monkeypatch.setattr(launcher, "run", fake_run)
    # launch() resolves the wrapper in agent_argv before run(); stubbing run is not enough.
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    # verify_unit_preflight is deliberately NOT stubbed: it rebuilds unit.launch_receipt, and a
    # stub that skips the rebuild hid the rebuild discarding the guard's keys. Its own
    # collaborators (the herdr row read) are the seam; the function under guard must be real.
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "w80:p9",
            "cwd": "/tmp/wt",
            "workspace_id": "w80",
            "interactive_ready": True,
            "agent": vendor,
        },
    )
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: True)
    unit = launcher.LaunchRequest(name="reviewer", vendor=vendor, worktree="/tmp/wt")
    return unit, recorded, sends


def test_a_closed_placeholder_reads_unreadable_not_empty(launcher: ModuleType) -> None:
    """A line fully styled with its span closing at end of line is byte-identical between a
    vendor placeholder and a draft, so it must never be claimed empty: the honest answer is
    unreadable, and the guard takes the unreadable branch rather than prompting on a claim."""
    captured = CAPTURED_COMPOSERS["codex_closed_placeholder"]
    assert launcher.composer_staged_text(captured, vendor="codex") is None


def test_composer_typed_text_is_staged(launcher: ModuleType) -> None:
    staged = launcher.composer_staged_text(f"❯ {STAGED_SLASH_COMMAND}", vendor="claude")
    assert staged == STAGED_SLASH_COMMAND


def test_composer_glyph_table_covers_the_launcher_vendor_roster(launcher: ModuleType) -> None:
    assert launcher.COMPOSER_GLYPH_BY_VENDOR == {
        "claude": "❯",
        "codex": "›",
        "grok": "❯",
        "agy": ">",
        "qwen": ">",
        "muse": None,
        "opencode": None,
    }
    assert set(launcher.COMPOSER_GLYPH_BY_VENDOR) == set(launcher.VENDOR_FLAGS)


def test_documented_input_box_receipt_schema_is_complete(launcher: ModuleType) -> None:
    """API-06: the value set is derived from ComposerState, never a pinned copy of it."""
    skill = SKILL_MD.read_text(encoding="utf-8")
    readme = LAUNCHER_README.read_text(encoding="utf-8")
    values = [member.value for member in launcher.ComposerState]
    for surface in (skill, readme):
        assert "input_box" in surface
        assert "input_box_text_chars" in surface
        assert all(f"`{value}`" in surface for value in values)


def test_input_box_text_chars_is_the_visible_length_of_the_absorbed_block(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DOCC-01 / SEC-08: the count is the visible length of the whole absorbed block, bound
    through the real guard so the documented number cannot drift from the recorded one."""
    row_one = "Stop before running U5 with Grok and Agy blocked. Direct host verification"
    row_two = "found both real executables. Use the live roster."
    unit, _recorded, _sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=f"❯ {row_one}\n  {row_two}",
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    with pytest.raises(launcher.StagedInputError, match="already holds staged input"):
        launcher.launch(unit)
    assert unit.launch_receipt["input_box_text_chars"] == len(row_one + row_two)


def test_input_box_text_chars_counts_a_styled_remainder_not_only_the_unstyled_part(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DOCC-01: the count is the visible length, never the count of positively recognized
    (unstyled) characters -- only `ok` is unstyled here, but the whole draft is withheld."""
    unstyled = "ok"
    styled = "the remainder of the draft is client-styled"
    visible = f"{unstyled} {styled}"
    dump = f"❯ {unstyled} \x1b[2m{styled}\x1b[0m"
    unit, _recorded, _sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=dump,
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    with pytest.raises(launcher.StagedInputError, match="already holds staged input"):
        launcher.launch(unit)
    assert unit.launch_receipt["input_box_text_chars"] == len(visible)
    assert unit.launch_receipt["input_box_text_chars"] > len(unstyled)


def test_documents_state_the_count_definition_and_the_shipped_guard_rule() -> None:
    """DOCC-01, DOCC-10, DOCC-11, DOCC-02, and terminal review F11: both surfaces carry the
    KTD3 count definition, the accepted indented-row asymmetry, and the shipped write-guard
    rule -- an owned session IS inspected before every later write, and only a fresh owned
    launch whose first prompt was taken carries no `input_box` key. The superseded
    one-sided sentence must be gone. Prose is compared with whitespace flattened so line
    wrapping cannot mask a claim."""
    for path in (SKILL_MD, LAUNCHER_README):
        flat = " ".join(path.read_text(encoding="utf-8").split())
        assert "visible length of what the parser absorbed" in flat, path
        assert "one character short at each wrapped-row boundary" in flat, path
        assert "lower bound" in flat, path
        assert "carries no `input_box` key" in flat, path
        assert "every later write into any session, owned or not" in flat, path
        assert "an owned session is never inspected" not in flat, path
        assert "redeliver" in flat, path
    skill = " ".join(SKILL_MD.read_text(encoding="utf-8").split())
    assert "never a second `launch`" in skill
    assert 'python3 "$S" redeliver' in skill
    assert "a receipt that records neither retryable shape" in skill


def test_documented_opencode_permission_flag_matches_the_runtime_table(
    launcher: ModuleType,
) -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    sentence = next(line for line in skill.splitlines() if "OpenCode's `auto` posture" in line)
    assert launcher.VENDOR_PERMISSION["opencode"]["auto"] == ["--auto"]
    assert "`--auto`" in sentence
    assert "`--dangerously-skip-permissions`" not in sentence


@pytest.mark.parametrize(
    ("vendor", "glyph"),
    [("claude", "❯"), ("codex", "›"), ("grok", "❯"), ("agy", ">"), ("qwen", ">")],
)
def test_every_characterised_vendor_stops_on_its_own_draft(
    launcher: ModuleType, vendor: str, glyph: str
) -> None:
    result = launcher.inspect_composer(f"{glyph} destructive draft", vendor=vendor)
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "destructive draft"


def test_bordered_composer_matches_after_the_border(launcher: ModuleType) -> None:
    result = launcher.inspect_composer("│ ❯ destructive draft", vendor="grok")
    assert result.state is launcher.ComposerState.STAGED


@pytest.mark.parametrize("line", ["│ ❯   │", "\x1b[2m│ ❯   │\x1b[0m"])
def test_paired_box_borders_are_structure_not_a_phantom_draft(
    launcher: ModuleType, line: str
) -> None:
    result = launcher.inspect_composer(line, vendor="claude")
    assert result.state is launcher.ComposerState.EMPTY
    assert result.text == ""


def test_composer_absent_reads_as_unreadable(launcher: ModuleType) -> None:
    dump = "some session output\na second line of plain output\n"
    assert launcher.composer_staged_text(dump, vendor="claude") is None


def test_codex_placeholder_is_distinct_from_no_composer(launcher: ModuleType) -> None:
    placeholder = launcher.inspect_composer(CODEX_PLACEHOLDER, vendor="codex")
    absent = launcher.inspect_composer("ordinary output", vendor="codex")
    assert placeholder.state is launcher.ComposerState.UNCLASSIFIABLE
    assert absent.state is launcher.ComposerState.NOT_FOUND


def test_reused_pane_holding_a_slash_command_is_not_prompted(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane(f"❯ {STAGED_SLASH_COMMAND}"),
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    with pytest.raises(SystemExit, match="already holds staged input"):
        launcher.launch(unit)
    assert sends == []
    assert unit.launch_receipt["input_box"] == "staged"
    assert STAGED_SLASH_COMMAND not in str(unit.launch_receipt)


def test_staged_text_is_recorded_not_discarded(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane(f"❯ {STAGED_SLASH_COMMAND}"),
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    with pytest.raises(SystemExit, match="already holds staged input"):
        launcher.launch(unit)
    assert sends == []
    assert unit.launch_receipt["input_box"] == "staged"
    assert unit.launch_receipt["input_box_text_chars"] == len(STAGED_SLASH_COMMAND)
    assert STAGED_SLASH_COMMAND not in json.dumps(unit.launch_receipt)
    assert STAGED_SLASH_COMMAND not in unit.note


def test_empty_reused_box_is_prompted_exactly_as_today(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit, recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane("❯ "),
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    launcher.launch(unit)
    assert len(sends) == 1
    ansi_reads = [c for c in recorded if c[:3] == ["herdr", "pane", "read"] and "--format" in c]
    assert len(ansi_reads) == 1
    assert unit.launch_receipt["input_box"] == "empty"


def test_freshly_created_pane_takes_no_inspection_path(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit, recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane(f"❯ {STAGED_SLASH_COMMAND}"),
        receipt_tab="w80:t9",
        existing_tabs=("w80:t1",),
    )
    launcher.launch(unit)
    assert len(sends) == 1
    ansi_reads = [c for c in recorded if c[:3] == ["herdr", "pane", "read"] and "--format" in c]
    assert ansi_reads == []


@pytest.mark.parametrize("reset_code", ["00", "22", "0;10"])
def test_reset_codes_after_a_styled_marker_return_the_staged_text(
    launcher: ModuleType, reset_code: str
) -> None:
    """Every style-off shape the terminal defines ends the styled span at the marker."""
    line = f"\x1b[2m❯\x1b[{reset_code}m /deploy prod --force"
    assert launcher.composer_staged_text(line, vendor="claude") == "/deploy prod --force"


def test_marker_styled_and_never_reset_is_unclassifiable(launcher: ModuleType) -> None:
    """A fully styled draft and a fully styled placeholder are byte-indistinguishable."""
    result = launcher.inspect_composer("\x1b[2m❯ /deploy prod --force", vendor="claude")
    assert result.state is launcher.ComposerState.UNCLASSIFIABLE


def test_a_bare_marker_row_below_staged_text_is_a_decoy(launcher: ModuleType) -> None:
    assert launcher.composer_staged_text("❯ rm -rf /important\n> ", vendor="claude") == (
        "rm -rf /important"
    )


def test_a_quoted_row_below_staged_text_is_not_the_composer(launcher: ModuleType) -> None:
    dump = "❯ rm -rf /important\n> quoted line"
    assert launcher.composer_staged_text(dump, vendor="claude") == "rm -rf /important"


def test_an_empty_live_box_below_an_echo_reads_empty(launcher: ModuleType) -> None:
    """B4: the box is decided positionally -- it is the last classified block of the pane's own
    glyph. A reused pane whose live box is empty below an earlier echoed prompt reads empty and
    does not stop: the echo is scrollback, not the box, and a working launch must not become a
    refusal."""
    dump = "❯ earlier submitted prompt\npane output line\n❯ "
    assert launcher.composer_staged_text(dump, vendor="claude") == ""


def test_adjacent_staged_and_empty_marker_rows_are_ambiguous(launcher: ModuleType) -> None:
    """Issue 1002 F110: an empty marker under a staged draft is a decoy, not EMPTY."""
    result = launcher.inspect_composer("❯ draft text\n❯ ", vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "draft text"


def test_escapes_inside_staged_text_are_stripped(launcher: ModuleType) -> None:
    assert launcher.composer_staged_text("❯ deploy the \x1b[Kfleet", vendor="claude") == (
        "deploy the fleet"
    )


def test_colour_reset_does_not_clear_dim_intensity(launcher: ModuleType) -> None:
    """Select Graphic Rendition code 39 resets foreground only, never intensity."""
    line = "\x1b[2;31m❯\x1b[39m fully styled draft"
    assert launcher.inspect_composer(line, vendor="claude").state is (
        launcher.ComposerState.UNCLASSIFIABLE
    )


def test_intensity_reset_exposes_plain_staged_text(launcher: ModuleType) -> None:
    line = "\x1b[2;31m❯\x1b[39;22m plain draft"
    result = launcher.inspect_composer(line, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "plain draft"


# The marker scan: the box is the last block of the pane's own glyph. Lines carrying another glyph
# are content, and an inconclusive live block never lets an earlier scrollback block decide.
def test_menu_rows_below_the_box_are_content_not_the_box(launcher: ModuleType) -> None:
    dump = "❯ deploy now\n> Option A\n> Option B"
    assert launcher.composer_staged_text(dump, vendor="claude") == "deploy now"


def test_cross_glyph_rows_are_content_not_the_box(launcher: ModuleType) -> None:
    assert launcher.composer_staged_text("❯ draft text\n› ", vendor="claude") == "draft text"


def test_a_weak_marker_under_a_decorated_box_is_content(launcher: ModuleType) -> None:
    """Issue 1002 F102: an empty Claude marker plus a `>` continuation is the draft."""
    assert launcher.composer_staged_text("❯ \n> draft text", vendor="claude") == "> draft text"


def test_a_plain_marker_vendor_reads_its_own_box(launcher: ModuleType) -> None:
    assert launcher.composer_staged_text("> draft text", vendor="agy") == "draft text"


def test_a_blank_marker_row_with_continuation_rows_is_one_block(launcher: ModuleType) -> None:
    """A wrapped draft continues on unmarked rows; reading only the marker row reports the
    first wrapped line and drops the rest."""
    dump = "❯\n  wrapped draft continuation"
    assert launcher.composer_staged_text(dump, vendor="claude") == "wrapped draft continuation"


def test_blank_then_indented_text_is_ambiguous_not_affirmatively_empty(
    launcher: ModuleType,
) -> None:
    """Indentation cannot distinguish multiline input from vendor status chrome."""
    dump = "❯\n\n  wrapped draft or status footer"
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.UNCLASSIFIABLE


def test_styled_wrapped_row_stays_in_a_proven_staged_block(launcher: ModuleType) -> None:
    dump = "│ ❯ deploy the │\n│   \x1b[31mfleet\x1b[0m │"
    assert launcher.composer_staged_text(dump, vendor="claude") == "deploy thefleet"


def test_status_footer_after_blank_is_not_counted_as_staged_input(
    launcher: ModuleType,
) -> None:
    result = launcher.inspect_composer("› ninechars\n\n  model footer status", vendor="codex")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "ninechars"


def test_unstyled_status_footer_after_empty_box_cannot_create_a_false_stop(
    launcher: ModuleType,
) -> None:
    result = launcher.inspect_composer("› \n\n  model footer status", vendor="codex")
    assert result.state is launcher.ComposerState.UNCLASSIFIABLE


@pytest.mark.parametrize(
    ("vendor", "dump"),
    [
        ("codex", "› \n\n  model footer status"),
    ],
)
def test_ambiguous_composer_geometry_never_records_affirmative_empty(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    vendor: str,
    dump: str,
) -> None:
    """Ambiguous geometry never claims `empty` -- and the `len(sends) == 1` assertion below is
    the fail-open pin the accepted ambiguity trade requires: an inconclusive inspection still
    prompts, because a styled operator draft is byte-identical to a styled placeholder."""
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=dump,
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
        vendor=vendor,
    )
    launcher.launch(unit)
    assert len(sends) == 1
    assert unit.launch_receipt["input_box"] == "unclassifiable"
    assert "input box unclassifiable" in unit.note


def test_first_noncontinuation_terminates_the_composer_block(launcher: ModuleType) -> None:
    dump = "❯ draft\nordinary output\n  unrelated indented output"
    assert launcher.composer_staged_text(dump, vendor="claude") == "draft"


def test_menu_marker_terminates_the_composer_block(launcher: ModuleType) -> None:
    dump = "❯ draft\n  continuation\n> menu choice\n  menu detail"
    assert launcher.composer_staged_text(dump, vendor="claude") == "draftcontinuation"


def test_marker_must_be_the_first_printable_character_after_a_border(
    launcher: ModuleType,
) -> None:
    dump = "❯ \nordinary output\n  footer hint contains ❯ but is not a composer"
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.EMPTY


def test_glyph_led_last_visual_row_never_turns_a_staged_draft_into_empty(
    launcher: ModuleType,
) -> None:
    dump = "❯ here is the failing session:\n   ran the suite\n❯ "
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text is not None and result.text.startswith("here is the failing session")


def test_a_draft_above_a_closed_placeholder_row_is_unclassifiable(launcher: ModuleType) -> None:
    """The live closed-span box wins positionally over an earlier scrollback draft."""
    dump = '❯ deploy the prod key now\n\x1b[2m❯ Try "fix it"\x1b[0m'
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.UNCLASSIFIABLE


@pytest.mark.parametrize("prefix", ["\x1b[0m", "\x1b[m", "\x1b[39m"])
def test_open_fully_styled_content_is_unclassifiable(launcher: ModuleType, prefix: str) -> None:
    result = launcher.inspect_composer(f"{prefix}\x1b[2m❯ /deploy prod", vendor="claude")
    assert result.state is launcher.ComposerState.UNCLASSIFIABLE


def test_closed_hint_then_reopened_span_is_unclassifiable(launcher: ModuleType) -> None:
    result = launcher.inspect_composer("\x1b[2m❯ \x1b[0m\x1b[2mdeploy prod", vendor="claude")
    assert result.state is launcher.ComposerState.UNCLASSIFIABLE


# --- The row rule: one classification per physical row (issue 907 U1, CORR-01/02/04/05/06, SEC-04,
# --- TEST-01/02/07/08/09, ARCH-03/04/17). Every clause below names the clause it binds.


def _claude_marker_bytes() -> str:
    """The fixture's own Claude marker row, the bytes a live pane emits for an empty box."""
    row = CAPTURED_COMPOSERS["claude_echo_above_empty"]
    assert isinstance(row, str)
    return row.splitlines()[-1]


def test_unbordered_two_row_claude_draft_is_absorbed_whole(launcher: ModuleType) -> None:
    """CORR-04: an unbordered wrapped draft is not truncated to its marker row."""
    row_one = "Stop before running U5 with Grok and Agy blocked. Direct host verification"
    row_two = "found both real executables. Use the live roster."
    dump = f"❯ {row_one}\n  {row_two}"
    assert launcher.composer_staged_text(dump, vendor="claude") == row_one + row_two


def test_unbordered_three_row_codex_draft_is_absorbed_whole(launcher: ModuleType) -> None:
    """TEST-07: the three-row Codex draft returns all three rows, not 22 of 41 characters."""
    dump = "› first row of the draft\n  second row\n  third row"
    assert launcher.composer_staged_text(dump, vendor="codex") == (
        "first row of the draftsecond rowthird row"
    )


def test_an_empty_marker_with_an_indented_request_row_is_staged(launcher: ModuleType) -> None:
    """CORR-02: the marker alone on row 1 with the request indented on row 2 is a draft."""
    dump = _claude_marker_bytes() + "\n  the actual request text the operator staged"
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "the actual request text the operator staged"
    assert len(result.text) == 43


def test_a_styled_at_mention_with_an_indented_unstyled_row_is_staged(
    launcher: ModuleType,
) -> None:
    """CORR-01: a styled at-mention on the marker row plus unstyled indented text is a draft."""
    dump = (
        _claude_marker_bytes()
        + "\x1b[38;2;128;128;128m@plugins/agent-launcher/README.md\x1b[0m"
        + "\n  please review this and tell me what breaks"
    )
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == (
        "@plugins/agent-launcher/README.mdplease review this and tell me what breaks"
    )


def test_an_empty_marker_followed_by_two_blank_rows_is_empty(launcher: ModuleType) -> None:
    """Trailing blank rows alone read empty (C23: a blank is not by itself ambiguity)."""
    result = launcher.inspect_composer("❯ \n\n\n", vendor="claude")
    assert result.state is launcher.ComposerState.EMPTY
    assert result.text == ""


def test_content_row_between_echo_and_empty_marker_is_live_empty(
    launcher: ModuleType,
) -> None:
    """CORR-05: a content row between an echoed prompt and a last empty marker is a live
    empty box, not a decoy. Blank-only separation is the F110 painted-marker case."""
    result = launcher.inspect_composer(
        "❯ earlier submitted prompt\npane output line\n❯ ", vendor="claude"
    )
    assert result.state is launcher.ComposerState.EMPTY
    assert result.text == ""


def test_a_bordered_draft_ending_in_a_corner_glyph_keeps_it(launcher: ModuleType) -> None:
    """CORR-06: at most one trailing border glyph is structure; the draft's own corner stays."""
    result = launcher.inspect_composer("│ ❯ the tree ends with (╰╯ │", vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "the tree ends with (╰╯"


def test_a_bordered_box_whose_only_content_is_a_border_glyph_is_staged(
    launcher: ModuleType,
) -> None:
    """SEC-04: one border-glyph character of content is a draft, not an empty box."""
    result = launcher.inspect_composer("│ ❯ █ │", vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "█"


def test_a_bordered_row_flush_at_the_marker_column_continues(launcher: ModuleType) -> None:
    """SEC-04: containment, not a column comparison, proves a bordered continuation."""
    dump = "│ ❯ │\n│ y │"
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "y"


def test_a_bordered_rule_row_ends_the_block_and_never_joins_the_draft(
    launcher: ModuleType,
) -> None:
    """C18: a bordered row whose content is only rule glyphs is a rule row, not a continuation."""
    dump = "│ ❯ x │\n│    ──── │\n│   y │"
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "x"


def test_an_indented_row_led_by_another_vendors_glyph_ends_the_block(
    launcher: ModuleType,
) -> None:
    """Terminal review F13, first clause: an indented row directly below the marker that
    starts with another vendor's composer glyph is menu chrome, not a continuation. Without
    the cross-glyph guard in the INDENTED clause the row joins the draft and the withheld
    count grows to include chrome; the control row below shows the same shape without a
    glyph is still absorbed."""
    chrome = launcher.inspect_composer("❯ x\n  › menu item", vendor="claude")
    assert chrome.state is launcher.ComposerState.STAGED
    assert chrome.text == "x"
    plain = launcher.inspect_composer("❯ x\n  more", vendor="claude")
    assert plain.state is launcher.ComposerState.STAGED
    assert plain.text == "xmore"


def test_a_bordered_row_of_spaced_rule_segments_is_a_rule_row(launcher: ModuleType) -> None:
    """Terminal review F13, second clause: the space belongs to the rule-glyph set, so a
    bordered row whose content is rule segments separated by spaces terminates the block
    exactly as a continuous rule does. Dropping the space turns it into a bordered
    continuation and the draft absorbs the rule and the row below it."""
    spaced = launcher.inspect_composer("│ ❯ x │\n│ ── ── │\n│ y │", vendor="claude")
    assert spaced.state is launcher.ComposerState.STAGED
    assert spaced.text == "x"
    continuous = launcher.inspect_composer("│ ❯ x │\n│ ──── │\n│ y │", vendor="claude")
    assert continuous.text == "x"


def test_a_styled_border_around_a_border_glyph_draft_still_reads_staged(
    launcher: ModuleType,
) -> None:
    """Terminal review F14: the one-glyph trailing strip is implemented twice; this binds
    the second copy, in the unstyled-text pass. The borders are styled so they never enter
    the unstyled content, and the draft is two border-shaped characters. Exactly one is
    treated as a closing border, one survives, and the box is staged -- a stop. An unbounded
    strip there would leave no unstyled character and the box would fall open as
    unclassifiable, the direction the feature exists to prevent."""
    dump = "\x1b[2m│\x1b[0m ❯ ██ \x1b[2m│\x1b[0m"
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "██"


def test_round_corner_borders_lead_and_trail_a_two_row_draft(launcher: ModuleType) -> None:
    """The corner glyphs are rosters on both sides: they lead row 1 and close row 2."""
    dump = "╭ ❯ draft ╮\n╰   more ╯"
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "draftmore"


@pytest.mark.parametrize("glyph", sorted(LEADING_BORDER_ROSTER))
def test_every_leading_border_glyph_is_rostered(launcher: ModuleType, glyph: str) -> None:
    """TEST-08 / C21: removing any one leading glyph breaks this named case for that glyph."""
    result = launcher.inspect_composer(f"{glyph} ❯ draft text", vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "draft text"


@pytest.mark.parametrize("glyph", sorted(TRAILING_BORDER_ROSTER))
def test_every_trailing_border_glyph_is_rostered(launcher: ModuleType, glyph: str) -> None:
    """TEST-08 / C22: removing any one trailing glyph breaks this named case for that glyph."""
    result = launcher.inspect_composer(f"│ ❯ hi {glyph}", vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "hi"


def test_the_border_rosters_match_their_pinned_expectation() -> None:
    """Drift pin: a glyph added to or removed from either roster fails here, so the pinned
    parametrisation above cannot silently fall behind the module."""
    assert frozenset(LEADING_BORDER_ROSTER) == COMPOSER_MODULE._LEADING_BORDER_GLYPHS
    assert frozenset(TRAILING_BORDER_ROSTER) == COMPOSER_MODULE._TRAILING_BORDER_GLYPHS


def test_unstyled_text_joins_rows_without_a_separator() -> None:
    """CORR-10: the wrap boundary adds no character; the join is pinned directly."""
    assert COMPOSER_MODULE._unstyled_text(["❯ deploy the", "  fleet"], "❯") == "deploy thefleet"


@pytest.mark.parametrize("key", LIVE_CLAUDE_IDLE_KEYS)
def test_a_live_idle_claude_pane_is_prompted_through_the_real_guard(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """R3: the live captures are the horizontal-rule clause's real-pane regression fixtures."""
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=CAPTURED_COMPOSERS[key],
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    launcher.launch(unit)
    assert len(sends) == 1
    assert unit.launch_receipt["input_box"] == "empty"


def _corrp01_pane() -> str:
    """CORR-01: the fixture marker plus a styled at-file mention, then an indented request."""
    return (
        _claude_marker_bytes()
        + "\x1b[38;2;128;128;128m@plugins/agent-launcher/README.md\x1b[0m"
        + "\n  please review this and tell me what breaks"
    )


def _corrp02_pane() -> str:
    """CORR-02: the fixture marker alone, then the operator's request indented on row 2."""
    return _claude_marker_bytes() + "\n  the actual request text the operator staged"


@pytest.mark.parametrize("pane", [_corrp01_pane, _corrp02_pane], ids=["corrp01", "corrp02"])
def test_corrp01_and_corrp02_panes_stop_the_prompt_through_the_real_guard(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, pane: Any
) -> None:
    """CORR-01 and CORR-02 end to end: the guard refuses to write behind a real draft shape."""
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=pane(),
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    with pytest.raises(launcher.StagedInputError, match="already holds staged input"):
        launcher.launch(unit)
    assert sends == []
    assert unit.launch_receipt["input_box"] == "staged"


def test_unreadable_box_is_marked_and_the_prompt_still_goes(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F114: a genuine nonzero pane read is the absence of an observation.
    The box is marked, noted, and the launch refuses to prompt."""
    recorded: list[list[str]] = []
    pane_read_timeouts: list[object] = []
    sends: list[tuple[Any, ...]] = []
    receipt = {
        "tab_id": "w80:t1",
        "agent_name": "reader-2",
        "pane_id": "w80:p9",
        "reused": False,
    }

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            sends.append(tuple(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["herdr", "pane", "read"]:
            pane_read_timeouts.append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(cmd, 1, "", "no such pane")
        if cmd[:3] == ["herdr", "tab", "list"]:
            tabs = {"result": {"tabs": [{"tab_id": "w80:t1", "label": "t"}]}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(tabs), "")
        if cmd[:3] == ["herdr", "pane", "current"]:
            pane = {"result": {"pane": {"workspace_id": "w80"}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(pane), "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), "")

    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    # The real verify_unit_preflight must run: it rebuilds unit.launch_receipt, and stubbing it
    # once hid the rebuild discarding this very key. Only its row-read collaborator is stubbed.
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "w80:p9",
            "cwd": "/tmp/wt",
            "workspace_id": "w80",
            "interactive_ready": True,
            "agent": "codex",
        },
    )
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: True)
    unit = launcher.LaunchRequest(name="reader", vendor="codex", worktree="/tmp/wt")
    with pytest.raises(SystemExit, match="refusing to prompt"):
        launcher.launch(unit)
    assert unit.launch_receipt["input_box"] == "read_failed"
    assert "input box read_failed" in unit.note
    assert sends == []
    assert pane_read_timeouts == [launcher.PANE_INPUT_READ_SECONDS]


def test_pane_read_timeout_is_distinct_from_a_failed_read(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    timed_out = launcher.TimedOutProcess(["herdr"], 124, "", "timed out")
    monkeypatch.setattr(launcher, "run", lambda *a, **k: timed_out)
    assert launcher.pane_input_inspection("w1:p1", vendor="claude").state is (
        launcher.ComposerState.READ_TIMEOUT
    )
    failed = subprocess.CompletedProcess(["herdr"], 124, "", "vendor returned 124")
    monkeypatch.setattr(launcher, "run", lambda *a, **k: failed)
    assert launcher.pane_input_inspection("w1:p1", vendor="claude").state is (
        launcher.ComposerState.READ_FAILED
    )


def test_staged_text_reaches_no_sink_verbatim(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator's draft reaches none of the durable sinks: not the receipt, not the unit
    note, not the stop message -- and therefore not the run record the note and message feed.
    The stop proves the box was not empty with a length and says the text was withheld."""
    unit, _recorded, _sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane(f"❯ {STAGED_SLASH_COMMAND}"),
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    with pytest.raises(SystemExit) as exc_info:
        launcher.launch(unit)
    message = str(exc_info.value)
    assert STAGED_SLASH_COMMAND not in message
    assert "withheld" in message
    assert STAGED_SLASH_COMMAND not in unit.note
    assert STAGED_SLASH_COMMAND not in json.dumps(unit.launch_receipt)
    assert unit.launch_receipt["input_box_text_chars"] == len(STAGED_SLASH_COMMAND)


def test_the_send_inspection_is_taken_after_the_preflight(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REL-08: the read that authorises the send is taken immediately before the send, after
    the preflight, so a person typing during the preflight's declared bounds cannot defeat
    the guard. At the frozen revision the order is guard-then-preflight."""
    unit, _recorded, _sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane("❯ "),
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    order: list[str] = []
    real_guard = launcher.guard_pane_before_write
    real_preflight = launcher.verify_unit_preflight

    def recording_guard(unit: Any, pane_id: str) -> None:
        order.append("guard")
        real_guard(unit, pane_id)

    def recording_preflight(*args: object, **kwargs: object) -> dict[str, Any]:
        order.append("preflight")
        receipt = real_preflight(*args, **kwargs)
        assert isinstance(receipt, dict)
        return receipt

    monkeypatch.setattr(launcher, "guard_pane_before_write", recording_guard)
    monkeypatch.setattr(launcher, "verify_unit_preflight", recording_preflight)
    launcher.launch(unit)
    assert order == ["preflight", "guard"]
    assert unit.launch_receipt["input_box"] == "empty"


def test_a_reused_pane_with_an_empty_box_below_an_echo_is_not_stopped(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4 end to end: a reused pane whose live box is empty below an earlier prompt echo is a
    normal pane. The launch must prompt, not refuse, and the receipt must say empty."""
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump="❯ earlier submitted prompt\npane output line\n❯ ",
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    launcher.launch(unit)
    assert len(sends) == 1
    assert unit.launch_receipt["input_box"] == "empty"


@pytest.mark.parametrize(("vendor", "glyph"), [("codex", "›"), ("grok", "❯"), ("agy", ">")])
def test_non_claude_guard_stops_on_the_vendor_composer_draft(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    vendor: str,
    glyph: str,
) -> None:
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=f"scrollback\n{glyph} destructive draft",
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
        vendor=vendor,
    )
    with pytest.raises(launcher.StagedInputError, match="already holds staged input"):
        launcher.launch(unit)
    assert sends == []
    assert unit.launch_receipt["input_box"] == "staged"


def test_echo_above_a_closed_span_placeholder_does_not_false_stop(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed-span live box wins over a classified scrollback echo positionally."""
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=CAPTURED_COMPOSERS["claude_echo_above_empty"],
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    launcher.launch(unit)
    assert len(sends) == 1
    assert unit.launch_receipt["input_box"] == "empty"


def test_echo_above_closed_span_hint_does_not_fall_back_to_the_echo(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump='❯ earlier submitted prompt\noutput\n\x1b[2m❯ Try "fix it"\x1b[0m',
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    launcher.launch(unit)
    assert len(sends) == 1
    assert unit.launch_receipt["input_box"] == "unclassifiable"


def test_closed_styled_operator_draft_is_knowingly_unclassifiable_and_prompted(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accepted trade: a fully styled operator draft is unclassifiable and prompts fail-open."""
    unit, _recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump='❯ \x1b[2mTry "fix it"\x1b[0m',
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    launcher.launch(unit)
    assert len(sends) == 1
    assert unit.launch_receipt["input_box"] == "unclassifiable"


def _preflight_stubs(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, *, vendor: str = "claude"
) -> list[str]:
    closed: list[str] = []
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "pane-1",
            "cwd": "/tmp/wt",
            "workspace_id": "w1",
            "interactive_ready": True,
            "agent": vendor,
        },
    )
    monkeypatch.setattr(launcher, "workspace_id_for_name", lambda name: None)
    monkeypatch.setattr(launcher, "verify_unit_account", lambda *a, **k: (None, "none"))
    monkeypatch.setattr(
        launcher, "close_run_session", lambda unit: closed.append(unit.tab_id or "")
    )
    return closed


def _bypass_unit(launcher: ModuleType) -> Any:
    return launcher.LaunchRequest(
        name="reviewer",
        vendor="claude",
        worktree="/tmp/wt",
        permission="bypass",
        pane_id="pane-1",
        tab_id="tab-1",
    )


LAUNCH_ARGV_HEAD = [
    "agents",
    "--no-focus",
    "--current",
    "--task",
    "reviewer",
    "--cwd",
    "/tmp/wt",
]


def test_declared_bypass_missing_from_argv_is_a_named_stop(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed = _preflight_stubs(launcher, monkeypatch)
    unit = _bypass_unit(launcher)
    argv = [*LAUNCH_ARGV_HEAD, "claude"]
    with pytest.raises(SystemExit) as exc_info:
        launcher.verify_unit_preflight(unit, "pane-1", ready=True, argv=argv)
    message = str(exc_info.value)
    assert "reviewer" in message
    assert "'bypass'" in message
    assert "'--permission-mode', 'bypassPermissions'" in message
    assert closed == ["tab-1"]


def test_receipt_records_resolved_posture_distinctly(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _preflight_stubs(launcher, monkeypatch)
    unit = _bypass_unit(launcher)
    argv = [*LAUNCH_ARGV_HEAD, "claude", "--permission-mode", "bypassPermissions"]
    receipt = launcher.verify_unit_preflight(unit, "pane-1", ready=True, argv=argv)
    assert receipt["permission"] == "bypass"
    assert receipt["permission_resolved"]["mode"] == "bypass"
    assert receipt["permission_resolved"]["tokens"] == [
        "--permission-mode",
        "bypassPermissions",
    ]
    assert receipt["permission_resolved"]["confirmed_from"] == "launch_argv"
    assert "permission" in receipt["requested_only"]
    assert "permission" not in receipt["confirmed_against_herdr"]


def test_no_argv_leaves_permission_unconfirmed(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _preflight_stubs(launcher, monkeypatch)
    unit = _bypass_unit(launcher)
    receipt = launcher.verify_unit_preflight(unit, "pane-1", ready=True)
    assert receipt["permission_resolved"]["confirmed_from"] is None
    assert "permission" in receipt["requested_only"]


@pytest.mark.parametrize("vendor", ["agy", "qwen"])
def test_empty_permission_token_list_never_claims_an_argv_confirmation(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    _preflight_stubs(launcher, monkeypatch, vendor=vendor)
    unit = launcher.LaunchRequest(
        name="worker", vendor=vendor, worktree="/tmp/wt", pane_id="pane-1", tab_id="tab-1"
    )
    receipt = launcher.verify_unit_preflight(
        unit, "pane-1", ready=True, argv=[*LAUNCH_ARGV_HEAD, vendor]
    )
    assert receipt["permission_resolved"]["tokens"] == []
    assert receipt["permission_resolved"]["confirmed_from"] is None
    assert receipt["account_evidence"] == "none"


def test_skill_no_longer_calls_permission_herdr_requested_only() -> None:
    skill = (
        REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "model and permission stay `requested_only`" not in skill
    assert "permission_resolved" in skill


def _plant_transcript(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    worktree: str,
    *,
    label: str,
    mtime: float,
) -> Path:
    personal = tmp_path / "personal-projects"
    company = tmp_path / "company-projects"
    monkeypatch.setattr(launcher, "claude_transcript_roots", lambda: (personal, company))
    root = company if label == "company" else personal
    slug = str(launcher.claude_project_slug(worktree))
    path = root / slug / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"type":"session"}\n', encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _account_preflight_stubs(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, worktree: str
) -> None:
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "pane-1",
            "cwd": worktree,
            "workspace_id": "w1",
            "interactive_ready": True,
            "agent": "claude",
        },
    )
    monkeypatch.setattr(launcher, "workspace_id_for_name", lambda name: None)
    monkeypatch.setattr(launcher, "close_run_session", lambda unit: None)


def _account_unit(launcher: ModuleType, worktree: str) -> Any:
    return launcher.LaunchRequest(
        name="acct",
        vendor="claude",
        account="company",
        worktree=worktree,
        pane_id="pane-1",
        tab_id="tab-1",
    )


def test_stale_transcript_does_not_confirm_a_silent_statusline(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    since = time.time()
    _plant_transcript(
        launcher, monkeypatch, tmp_path, str(worktree), label="company", mtime=since - 60
    )
    monkeypatch.setattr(launcher, "pane_account_label", lambda pane_id: None)
    unit = _account_unit(launcher, str(worktree))
    assert launcher.observed_account(unit, "pane-1", 0, since=since) == (None, "none")
    confirmed, error = launcher.check_unit_account(unit, "pane-1", seconds=0, since=since)
    assert confirmed is False
    assert error is not None and "unverified" in error


def test_vanished_transcript_between_glob_and_stat_is_skipped(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vanished = tmp_path / "vanished.jsonl"
    monkeypatch.setattr(launcher, "claude_transcript_roots", lambda: (tmp_path, tmp_path))
    monkeypatch.setattr(launcher, "find_claude_transcripts", lambda *_a: [vanished])
    unit = launcher.LaunchRequest(name="acct", vendor="claude", worktree="/tmp/wt")
    assert launcher.transcript_account(unit, since=time.time()) is None


def test_fresh_transcript_confirms_when_recency_is_provable(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    since = time.time()
    _plant_transcript(
        launcher, monkeypatch, tmp_path, str(worktree), label="company", mtime=since + 5
    )
    monkeypatch.setattr(launcher, "pane_account_label", lambda pane_id: None)
    _account_preflight_stubs(launcher, monkeypatch, str(worktree))
    unit = _account_unit(launcher, str(worktree))
    assert launcher.observed_account(unit, "pane-1", 0, since=since) == ("company", "transcript")
    receipt = launcher.verify_unit_preflight(unit, "pane-1", ready=True, since=since)
    assert receipt["account_evidence"] == "transcript"
    assert "account" not in receipt["confirmed_against_herdr"]
    assert receipt["confirmed_outside_herdr"] == ["account"]


def test_transcript_written_during_the_create_still_confirms(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    since = time.time()
    # The same-instant write the cmd_go account test produces: the wrapper plants the transcript
    # during the create, and filesystems quantise mtimes, so what lands can sit below the captured
    # launch instant. This file sits exactly on the slack boundary, where both a dropped slack and
    # a strict comparison fail while the shipped >= with one second of slack accepts it.
    _plant_transcript(
        launcher, monkeypatch, tmp_path, str(worktree), label="company", mtime=since - 1.0
    )
    monkeypatch.setattr(launcher, "pane_account_label", lambda pane_id: None)
    unit = _account_unit(launcher, str(worktree))
    assert launcher.observed_account(unit, "pane-1", 0, since=since) == ("company", "transcript")


def test_statusline_evidence_still_confirms_exactly_as_today(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    # A contradicting transcript the statusline must outrank: a proof chain reordered to consult
    # transcripts first would mismatch this launch instead of confirming it.
    _plant_transcript(
        launcher, monkeypatch, tmp_path, str(worktree), label="personal", mtime=time.time()
    )
    monkeypatch.setattr(launcher, "pane_account_label", lambda pane_id: "company")
    _account_preflight_stubs(launcher, monkeypatch, str(worktree))
    unit = _account_unit(launcher, str(worktree))
    assert launcher.check_unit_account(unit, "pane-1", seconds=0) == (True, None)
    receipt = launcher.verify_unit_preflight(unit, "pane-1", ready=True)
    assert receipt["account_evidence"] == "statusline"


def test_omitted_since_keeps_the_existing_fallback(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    # Deliberately old: with no floor the fallback behaves exactly as it did before the floor
    # existed. That is the compatibility decision, recorded here so it cannot be tightened by
    # accident.
    _plant_transcript(
        launcher, monkeypatch, tmp_path, str(worktree), label="company", mtime=time.time() - 500
    )
    monkeypatch.setattr(launcher, "pane_account_label", lambda pane_id: None)
    _account_preflight_stubs(launcher, monkeypatch, str(worktree))
    unit = _account_unit(launcher, str(worktree))
    assert launcher.observed_account(unit, "pane-1", 0) == ("company", "transcript")
    assert launcher.check_unit_account(unit, "pane-1", seconds=0) == (True, None)
    receipt = launcher.verify_unit_preflight(unit, "pane-1", ready=True)
    assert receipt["account_evidence"] == "transcript"


def test_launch_passes_a_recency_floor(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    _plant_transcript(
        launcher, monkeypatch, tmp_path, str(worktree), label="company", mtime=time.time() - 3600
    )
    monkeypatch.setattr(launcher, "pane_account_label", lambda pane_id: None)
    sends: list[tuple[Any, ...]] = []
    receipt = {"tab_id": "w80:t9", "agent_name": "acct-2", "pane_id": "w80:p9", "reused": False}

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["herdr", "tab", "list"]:
            tabs = {"result": {"tabs": [{"tab_id": "w80:t1", "label": "old"}]}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(tabs), "")
        if cmd[:3] == ["herdr", "pane", "current"]:
            pane = {"result": {"pane": {"workspace_id": "w80"}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(pane), "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), "")

    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(launcher, "send", lambda *a, **k: sends.append(a))
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda unit, agents=None: {
            "pane_id": "w80:p9",
            "cwd": str(worktree),
            "workspace_id": "w80",
            "interactive_ready": True,
            "agent": "claude",
        },
    )
    # Spend the account-settle window without wall-clock delay. time.time() stays real: the floor
    # under test is a wall-clock instant compared against the planted file's mtime.
    clock = [time.monotonic()]

    def fast_monotonic() -> float:
        clock[0] += 2.0
        return clock[0]

    monkeypatch.setattr(launcher.time, "monotonic", fast_monotonic)
    monkeypatch.setattr(launcher.time, "sleep", lambda *_a, **_k: None)
    unit = _account_unit(launcher, str(worktree))
    with pytest.raises(launcher.AccountMismatchError, match="account unverified"):
        launcher.launch(unit)
    assert sends == []


def test_account_mismatch_still_raises_unchanged(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    monkeypatch.setattr(launcher, "pane_account_label", lambda pane_id: "personal")
    monkeypatch.setattr(launcher, "close_run_session", lambda unit: None)
    unit = _account_unit(launcher, str(worktree))
    with pytest.raises(launcher.AccountMismatchError) as exc_info:
        launcher.verify_unit_account(unit, "pane-1")
    assert str(exc_info.value) == (
        "acct: account mismatch: worker is on the personal account when company was required"
    )


def test_startup_timeout_is_a_result_not_a_crash(launcher: ModuleType) -> None:
    result = launcher.run(["sleep", "2"], check=False, timeout=0.1)
    assert isinstance(result, launcher.TimedOutProcess)
    assert result.returncode == 124
    assert "timed out after 0.1s" in result.stderr


def test_genuine_exit_124_is_not_a_synthesized_timeout(launcher: ModuleType) -> None:
    result = launcher.run(["sh", "-c", "exit 124"], check=False, timeout=2)
    assert result.returncode == 124
    assert not isinstance(result, launcher.TimedOutProcess)


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
    _no_host_herdr(launcher, monkeypatch)
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(launcher, "send", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: False)
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda *_a, **_k: {
            "agent_status": "idle",
            "pane_id": "pane-1",
            "cwd": str(tmp_path),
            "interactive_ready": True,
            "agent": "codex",
        },
    )
    monkeypatch.setattr(launcher.time, "sleep", lambda *_a, **_k: None)
    unit = launcher.LaunchRequest(name="reviewer", vendor="codex", worktree=str(tmp_path))
    launcher.launch(unit)
    assert unit.status == launcher.PROMPT_UNDELIVERED
    assert launcher.DELIVERY_WARNING in unit.note
    assert unit.launch_receipt["prompt_delivered"] is False
    assert unit.launch_receipt["agent_name"] == "reviewer-2"
    assert unit.tab_id == "tab-1"


def test_pane_fallback_resend_rechecks_for_staged_input(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = {
        "tab_id": "w1:t-new",
        "agent_name": "worker-2",
        "pane_id": "w1:p1",
        "reused": False,
    }
    monkeypatch.setattr(launcher, "list_tab_ids", lambda _workspace=None: frozenset({"w1:t-new"}))
    monkeypatch.setattr(
        launcher,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), ""),
    )
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(launcher, "verify_unit_preflight", lambda *a, **k: {})
    sends: list[str] = []
    plain_run = launcher.run

    def counting_run(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            sends.append("send")
        result: subprocess.CompletedProcess[str] = plain_run(cmd, **k)
        return result

    monkeypatch.setattr(launcher, "run", counting_run)
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: False)
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda *_a, **_k: {
            "agent_status": "idle",
            "pane_id": "w1:p1",
            "cwd": "/tmp/wt",
            "workspace_id": "w1",
            "interactive_ready": True,
            "agent": "codex",
        },
    )

    inspections: list[str] = []

    def stop_resend(*_args: object, **_kwargs: object) -> None:
        inspections.append("guard")
        if len(inspections) > 1:
            raise launcher.StagedInputError("resend target now contains staged input")

    monkeypatch.setattr(launcher, "guard_pane_before_write", stop_resend)
    unit = launcher.LaunchRequest(name="worker", vendor="codex", worktree="/tmp/wt")
    with pytest.raises(launcher.StagedInputError, match="resend target"):
        launcher.launch(unit)
    assert sends == ["send"]
    assert inspections == ["guard", "guard"]


def test_agent_prompt_resend_rechecks_before_it_can_fall_back_to_the_pane(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit, _recorded, _sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane("❯ "),
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    inspections: list[str] = []
    accepted = iter([False, True])
    monkeypatch.setattr(
        launcher,
        "guard_pane_before_write",
        lambda *_a, **_k: inspections.append("guard"),
    )
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: next(accepted))
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda *_a, **_k: {
            "agent_status": "idle",
            "pane_id": "w80:p9",
            "cwd": "/tmp/wt",
            "workspace_id": "w80",
            "interactive_ready": True,
            "agent": "claude",
        },
    )

    launcher.launch(unit)

    assert inspections == ["guard", "guard"]
    assert unit.status == launcher.RUNNING


def _prepare_resend_launch(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_prompt_ok: bool,
    pane_dump: str,
    preexisting_tabs: frozenset[str],
) -> tuple[Any, list[list[str]], list[str], list[str]]:
    """Drive the real PaneWriter send and the resend loop with only the Herdr boundary stubbed.

    Whether `herdr agent prompt` succeeds or is refused selects the two delivery doors: a
    refusal makes PaneWriter type into the pane, which is the wrote_before half of
    should_guard_pane_write. Returns the unit, every recorded command, the pane-typing
    writes, and the guard calls made by the counting wrapper around the real guard.
    """
    recorded: list[list[str]] = []
    pane_writes: list[str] = []
    guard_calls: list[str] = []
    receipt = {"tab_id": "w1:t-new", "agent_name": "worker-2", "pane_id": "w1:p1", "reused": False}

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            rc = 0 if agent_prompt_ok else 1
            detail = "" if agent_prompt_ok else "not interactive ready"
            return subprocess.CompletedProcess(cmd, rc, "", detail)
        if cmd[:3] == ["herdr", "pane", "run"]:
            pane_writes.append(cmd[-1])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["herdr", "pane", "read"]:
            return subprocess.CompletedProcess(cmd, 0, pane_dump, "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), "")

    real_guard = launcher.guard_pane_before_write

    def counting_guard(unit: Any, pane_id: str) -> None:
        guard_calls.append(pane_id)
        real_guard(unit, pane_id)

    monkeypatch.setattr(launcher, "list_tab_ids", lambda _workspace=None: preexisting_tabs)
    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(launcher, "verify_unit_preflight", lambda *a, **k: {})
    monkeypatch.setattr(launcher, "guard_pane_before_write", counting_guard)
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: False)
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda *_a, **_k: {
            "agent_status": "idle",
            "pane_id": "w1:p1",
            "cwd": "/tmp/wt",
            "workspace_id": "w1",
            "interactive_ready": True,
            "agent": "claude",
        },
    )
    unit = launcher.LaunchRequest(name="worker", vendor="claude", worktree="/tmp/wt")
    return unit, recorded, pane_writes, guard_calls


def test_pane_fallback_resend_into_an_owned_pane_rechecks_for_staged_input(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-01: an owned session whose first send typed into the pane is re-inspected on the
    resend. At the frozen revision this shape makes three pane writes and zero guard calls
    (DID NOT RAISE); the probe is rebuilt here from the artifact."""
    unit, _recorded, pane_writes, guard_calls = _prepare_resend_launch(
        launcher,
        monkeypatch,
        agent_prompt_ok=False,
        pane_dump=_claude_pane(f"❯ {STAGED_SLASH_COMMAND}"),
        preexisting_tabs=frozenset(),
    )
    with pytest.raises(launcher.StagedInputError, match="already holds staged input"):
        launcher.launch(unit)
    assert guard_calls == ["w1:p1"]
    assert len(pane_writes) == 1
    assert unit.tab_id == "w1:t-new"
    assert unit.pane_id == "w1:p1"
    assert unit.owned is True
    assert unit.launch_receipt["agent_name"] == "worker-2"
    assert unit.launch_receipt["input_box"] == "staged"


def test_agent_prompt_resend_into_an_owned_pane_is_inspected_before_each_resend(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write half of the predicate tracks every door, not only the pane-typing fallback
    (terminal review F03). An owned session delivered through `herdr agent prompt` has been
    written by this launcher the instant the first prompt goes out, so each of the two
    resends -- about 15 and 30 seconds later -- inspects the pane first. The first send
    into the freshly created pane still takes no inspection."""
    unit, recorded, pane_writes, guard_calls = _prepare_resend_launch(
        launcher,
        monkeypatch,
        agent_prompt_ok=True,
        pane_dump=_claude_pane("❯ "),
        preexisting_tabs=frozenset(),
    )
    launcher.launch(unit)
    assert guard_calls == ["w1:p1", "w1:p1"]
    assert pane_writes == []
    prompt_calls = [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]]
    assert len(prompt_calls) == 3
    assert unit.status == launcher.PROMPT_UNDELIVERED


def test_agent_prompt_resend_into_an_owned_pane_stops_on_a_draft_staged_since(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The consequence F03 names: text the operator staged after the first prompt is found
    by the resend inspection and the resend is withheld, rather than concatenated onto it."""
    dumps = iter([_claude_pane(f"❯ {STAGED_SLASH_COMMAND}")])
    unit, recorded, pane_writes, guard_calls = _prepare_resend_launch(
        launcher,
        monkeypatch,
        agent_prompt_ok=True,
        pane_dump="",
        preexisting_tabs=frozenset(),
    )
    real_run = launcher.run

    def staged_on_read(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["herdr", "pane", "read"]:
            recorded.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, next(dumps, _claude_pane("❯ ")), "")
        result: subprocess.CompletedProcess[str] = real_run(cmd, **k)
        return result

    monkeypatch.setattr(launcher, "run", staged_on_read)
    with pytest.raises(launcher.StagedInputError, match="already holds staged input"):
        launcher.launch(unit)
    assert guard_calls == ["w1:p1"]
    prompt_calls = [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]]
    assert len(prompt_calls) == 1
    assert pane_writes == []
    assert unit.launch_receipt["input_box"] == "staged"


def test_each_resend_after_a_pane_fallback_is_inspected_once(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixed side, counted: an owned pane-fallback launch makes zero guard calls before
    its first send and exactly one per resend while the session stays idle."""
    unit, _recorded, pane_writes, guard_calls = _prepare_resend_launch(
        launcher,
        monkeypatch,
        agent_prompt_ok=False,
        pane_dump=_claude_pane("❯ "),
        preexisting_tabs=frozenset(),
    )
    launcher.launch(unit)
    assert guard_calls == ["w1:p1", "w1:p1"]
    assert len(pane_writes) == 3
    assert unit.status == launcher.PROMPT_UNDELIVERED


def _prepare_redeliver_real_send(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    owned: bool,
    pane_dumps: list[str],
    agent_status: str | None = "idle",
    accepted: bool = False,
) -> tuple[Any, list[list[str]], list[str], list[str]]:
    """A redelivery driven through the real send/say and the real guard, with only the
    Herdr boundary stubbed (terminal review F02: the stubbed-send harness above could not
    observe the resend loop). ``pane_dumps`` feeds successive guard reads; the last one
    repeats. Returns the unit, every recorded command, the pane-typing writes, and the
    guard calls."""
    recorded: list[list[str]] = []
    pane_writes: list[str] = []
    guard_calls: list[str] = []
    dumps = iter(pane_dumps)
    last = pane_dumps[-1]

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        if cmd[:3] == ["herdr", "pane", "read"] and "--format" in cmd:
            return subprocess.CompletedProcess(cmd, 0, next(dumps, last), "")
        if cmd[:3] == ["herdr", "pane", "run"]:
            pane_writes.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    real_guard = launcher.guard_pane_before_write

    def counting_guard(unit: Any, pane_id: str) -> None:
        guard_calls.append(pane_id)
        real_guard(unit, pane_id)

    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(launcher, "verify_unit_preflight", lambda *a, **k: {})
    monkeypatch.setattr(launcher, "guard_pane_before_write", counting_guard)
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: accepted)
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda *_a, **_k: {
            "agent_status": agent_status,
            "pane_id": "w1:p1",
            "cwd": "/tmp/wt",
            "workspace_id": "w1",
            "interactive_ready": True,
            "agent": "claude",
        },
    )
    unit = launcher.LaunchRequest(
        name="worker",
        vendor="claude",
        worktree="/tmp/wt",
        task="do the thing",
        pane_id="w1:p1",
        tab_id="w1:t1",
        owned=owned,
        launch_receipt={
            "tab_id": "w1:t1",
            "pane": "w1:p1",
            "agent_name": "worker-2",
            "owned": owned,
            "input_box": "staged",
        },
    )
    return unit, recorded, pane_writes, guard_calls


def test_redeliver_records_no_wrapper_create_and_keeps_the_tab(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry never runs the wrapper create: calling launch() again would create a second
    session and overwrite the first owned tab (the prior validation artifact's REL-03,
    rebuilt through the retry door)."""
    unit, recorded, _pane_writes, guard_calls = _prepare_redeliver_real_send(
        launcher, monkeypatch, owned=False, pane_dumps=[_claude_pane("❯ ")], accepted=True
    )
    launcher.redeliver(unit)
    assert not any(cmd[0] == "agents" for cmd in recorded)
    assert unit.tab_id == "w1:t1"
    assert unit.status == launcher.RUNNING
    assert unit.launch_receipt["prompt_delivered"] is True
    assert unit.launch_receipt["input_box"] == "empty"
    assert len([c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]]) == 1
    assert guard_calls == ["w1:p1"]


def test_redeliver_inspects_before_the_first_write_on_an_owned_unit(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wrote_before half of should_guard_pane_write, observable only here: a redelivery
    into a pane this launcher owns still inspects before its first write, because the stop
    that made the redelivery necessary was an inspection that found text. A still-staged
    pane raises with no send."""
    unit, recorded, _pane_writes, guard_calls = _prepare_redeliver_real_send(
        launcher,
        monkeypatch,
        owned=True,
        pane_dumps=[_claude_pane(f"❯ {STAGED_SLASH_COMMAND}")],
    )
    with pytest.raises(launcher.StagedInputError, match="already holds staged input"):
        launcher.redeliver(unit)
    assert [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]] == []
    assert guard_calls == ["w1:p1"]
    assert unit.launch_receipt["input_box"] == "staged"


def test_redeliver_without_a_pane_id_is_a_named_stop(launcher: ModuleType) -> None:
    """A unit that lost its pane id cannot be redelivered; the stop names the recovery."""
    unit = launcher.LaunchRequest(name="worker", vendor="claude", worktree="/tmp/wt")
    with pytest.raises(SystemExit, match="cannot redeliver"):
        launcher.redeliver(unit)


def test_redeliver_with_the_real_send_inspects_before_every_write(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal review F02, the executed probe rebuilt: a redelivery into an owned pane
    whose first prompt goes through `herdr agent prompt` and is never taken. At the frozen
    revision the plain assignment after the first send discarded the seeded flag, so the
    two resends went out with no inspection -- one guard call for three writes. Every
    write of a redelivery is inspected, because the stop that made it necessary was an
    inspection that found text."""
    unit, recorded, pane_writes, guard_calls = _prepare_redeliver_real_send(
        launcher, monkeypatch, owned=True, pane_dumps=[_claude_pane("❯ ")]
    )
    launcher.redeliver(unit)
    prompt_calls = [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]]
    assert len(prompt_calls) == 3
    assert guard_calls == ["w1:p1", "w1:p1", "w1:p1"]
    assert pane_writes == []
    assert unit.status == launcher.PROMPT_UNDELIVERED


def test_redeliver_resend_stops_on_a_draft_staged_after_the_first_prompt(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The consequence F02/F03 name on the retry door: an empty box at the first write, a
    draft typed during the fifteen-second delivery window, and the resend is withheld."""
    unit, recorded, pane_writes, guard_calls = _prepare_redeliver_real_send(
        launcher,
        monkeypatch,
        owned=True,
        pane_dumps=[_claude_pane("❯ "), _claude_pane(f"❯ {STAGED_SLASH_COMMAND}")],
    )
    with pytest.raises(launcher.StagedInputError, match="already holds staged input"):
        launcher.redeliver(unit)
    prompt_calls = [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]]
    assert len(prompt_calls) == 1
    assert guard_calls == ["w1:p1", "w1:p1"]
    assert unit.launch_receipt["input_box"] == "staged"


def test_redeliver_refuses_when_the_session_has_left_idle(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal review F04/F30: the resend loop refuses to resend into a session that has
    left idle, because it may already hold the task. A staged-input stop raised from inside
    that loop happens after a send went out, so the retry door inherits the same rule: a
    row that is working, blocked or gone gets nothing, the retry route closes, and the unit
    is recorded as sent-but-unobserved for the operator to check."""
    unit, recorded, pane_writes, guard_calls = _prepare_redeliver_real_send(
        launcher,
        monkeypatch,
        owned=True,
        pane_dumps=[_claude_pane("❯ ")],
        agent_status="working",
    )
    launcher.redeliver(unit)
    assert [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]] == []
    assert pane_writes == []
    assert guard_calls == []
    assert unit.status == launcher.PROMPT_UNDELIVERED
    assert "redelivery withheld" in unit.note
    assert launcher.DELIVERY_WARNING in unit.note
    assert unit.launch_receipt["prompt_delivered"] is False
    assert unit.launch_receipt["input_box"] == "staged"


def test_redeliver_of_a_gone_session_is_the_preflights_named_stop(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycle 2, F48/F49: a missing Herdr row is not evidence the session started, so the
    retry gate does not close the route over it; the real preflight then stops by name
    because Herdr does not list the session. No prompt goes out either way."""
    real_preflight = launcher.verify_unit_preflight
    unit, recorded, pane_writes, _guard_calls = _prepare_redeliver_real_send(
        launcher, monkeypatch, owned=True, pane_dumps=[_claude_pane("❯ ")]
    )
    monkeypatch.setattr(launcher, "verify_unit_preflight", real_preflight)
    monkeypatch.setattr(launcher, "agent_row", lambda *_a, **_k: None)
    with pytest.raises(SystemExit, match="herdr did not list the session"):
        launcher.redeliver(unit)
    assert [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]] == []
    assert pane_writes == []
    assert "redelivery withheld" not in unit.note


@pytest.mark.parametrize("status", ["unknown", None])
def test_redeliver_treats_unknown_as_never_started(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, status: str | None
) -> None:
    """A row reporting unknown or no status at all has not started, so the retry proceeds."""
    unit, recorded, _pane_writes, guard_calls = _prepare_redeliver_real_send(
        launcher,
        monkeypatch,
        owned=True,
        pane_dumps=[_claude_pane("❯ ")],
        accepted=True,
        agent_status=status,  # type: ignore[arg-type]
    )
    launcher.redeliver(unit)
    assert len([c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]]) == 1
    assert guard_calls == ["w1:p1"]
    assert unit.status == launcher.RUNNING
    assert "redelivery withheld" not in unit.note


@pytest.mark.parametrize("status", ["working", "blocked", "waiting"])
def test_redeliver_refuses_every_started_status(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    unit, recorded, _pane_writes, _guard_calls = _prepare_redeliver_real_send(
        launcher, monkeypatch, owned=True, pane_dumps=[_claude_pane("❯ ")], agent_status=status
    )
    launcher.redeliver(unit)
    assert [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]] == []
    assert unit.status == launcher.PROMPT_UNDELIVERED
    assert f"the session was {status}" in unit.note


def test_redeliver_into_an_idle_session_still_sends(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counter-case for F04/F30: the liveness rule must not close the retry door on the
    session it exists for -- one still sitting idle with a cleared composer is redelivered
    and, once it takes the task, recorded RUNNING."""
    unit, recorded, _pane_writes, guard_calls = _prepare_redeliver_real_send(
        launcher, monkeypatch, owned=True, pane_dumps=[_claude_pane("❯ ")], accepted=True
    )
    launcher.redeliver(unit)
    assert len([c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]]) == 1
    assert guard_calls == ["w1:p1"]
    assert unit.status == launcher.RUNNING
    assert unit.launch_receipt["prompt_delivered"] is True
    assert "redelivery withheld" not in unit.note


def test_redeliver_admits_a_transcript_older_than_the_retry(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Terminal review F17: the redelivery passes ``since=None`` on purpose -- the receipt
    records no creation time, so the recency floor a fresh launch applies cannot be
    supplied and is traded away. This test leaves the preflight real: a transcript written
    an hour before the retry is admitted as the account proof. Replacing the argument with
    a live timestamp floors that transcript out and the retry stops on an unverified
    account."""
    unit, recorded, _pane_writes, _guard_calls = _prepare_redeliver_real_send(
        launcher, monkeypatch, owned=True, pane_dumps=[_claude_pane("❯ ")], accepted=True
    )
    monkeypatch.undo()
    # Rebuild the boundary without the preflight stub; every pane read without --format is
    # the statusline read, which answers nothing so the transcript is the only evidence.
    dumps = [_claude_pane("❯ ")]

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        if cmd[:3] == ["herdr", "pane", "read"] and "--format" in cmd:
            return subprocess.CompletedProcess(cmd, 0, dumps[0], "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: True)
    monkeypatch.setattr(launcher, "workspace_id_for_name", lambda *_a, **_k: None)
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda *_a, **_k: {
            "agent_status": "idle",
            "pane_id": "w1:p1",
            "cwd": "/tmp/wt",
            "workspace_id": "w1",
            "interactive_ready": True,
            "agent": "claude",
        },
    )
    personal = tmp_path / "personal"
    company = tmp_path / "company"
    monkeypatch.setattr(launcher, "claude_transcript_roots", lambda: (personal, company))
    project = personal / launcher.claude_project_slug("/tmp/wt")
    project.mkdir(parents=True)
    transcript = project / "session.jsonl"
    transcript.write_text("{}\n")
    an_hour_ago = time.time() - 3600
    os.utime(transcript, (an_hour_ago, an_hour_ago))
    unit.account = "personal"

    launcher.redeliver(unit)

    assert unit.status == launcher.RUNNING
    assert unit.launch_receipt["account_evidence"] == "transcript"
    assert launcher.ACCOUNT_MISMATCH not in unit.note


def test_unterminated_osc_sequences_parse_in_linear_time(launcher: ModuleType) -> None:
    """Issue 1002 F135: complexity is the regex contract, not a wall clock. The OSC body
    excludes ESC so unterminated starts cannot quadratic-backtrack; the box below them
    still classifies."""
    hostile = ("\x1b]0;title" * 16000) + "\n\x1b[2m────\x1b[0m\n❯ draft\n"
    result = launcher.inspect_composer(hostile, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "draft"
    composer_src = LAUNCHER.with_name("composer.py").read_text(encoding="utf-8")
    assert r"[^\x07\x1b]" in composer_src


def test_the_rows_handed_to_the_parser_are_capped_from_the_tail_without_cutting_a_row(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycle 1 F12 and cycle 2 F45: the launcher hands inspect_composer at most
    PANE_INSPECT_MAX_LINES rows, taken from the tail because the live box is the last block.
    Rows, not bytes: a byte cut could land inside the marker row and turn a staged draft into
    not_found. A viewport three times the cap loses its head and keeps every row of its box."""
    seen: list[str] = []
    real = launcher.inspect_composer

    def capture(text: str, *, vendor: str) -> Any:
        seen.append(text)
        return real(text, vendor=vendor)

    cap = launcher.PANE_INSPECT_MAX_LINES
    dump = "\n".join(f"scrollback row {i}" for i in range(3 * cap)) + "\n❯ tail draft"
    monkeypatch.setattr(launcher, "inspect_composer", capture)
    monkeypatch.setattr(
        launcher,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(["herdr"], 0, dump, ""),
    )
    inspection = launcher.pane_input_inspection("w1:p1", vendor="claude")
    assert inspection.state is launcher.ComposerState.STAGED
    assert inspection.text == "tail draft"
    assert len(seen) == 1 and seen[0].count("\n") == cap - 1
    assert seen[0].endswith("❯ tail draft")
    assert cap >= 1000


def test_a_long_bordered_draft_past_the_old_byte_cap_still_reads_staged(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycle 2, F45, the measured case: a marker row followed by 400 bordered draft rows at
    about 68 KB classified staged in full and not_found after a 65536-byte tail cut, because
    the cut fell inside the marker row. With a row cap the whole block reaches the parser."""
    draft_rows = "\n".join("│ " + ("draft text " * 14).strip() + " │" for _ in range(450))
    dump = "│ ❯ first row │\n" + draft_rows
    assert len(dump) > 65536
    monkeypatch.setattr(
        launcher,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(["herdr"], 0, dump, ""),
    )
    inspection = launcher.pane_input_inspection("w1:p1", vendor="claude")
    assert inspection.state is launcher.ComposerState.STAGED
    assert inspection.text is not None and inspection.text.startswith("first row")


def test_pane_writes_carry_a_timeout_and_a_timed_out_prompt_never_falls_through(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal review F18: the two calls that write into a pane were the only Herdr calls
    with no bound, so a wedged daemon hung go and land mid-delivery. Both carry
    PANE_WRITE_SECONDS. A prompt that times out is not a refusal: the line may have been
    delivered, so the pane door is never tried behind it and the stop is named."""
    timeouts: list[tuple[str, object]] = []

    def fake_run(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        timeouts.append((" ".join(cmd[:3]), k.get("timeout")))
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            return subprocess.CompletedProcess(cmd, 1, "", "not interactive ready")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(
        name="worker", vendor="qwen", worktree="/tmp/wt", launch_receipt={"owned": True}
    )
    launcher.PaneWriter(unit, "w1:p1", wrote_before=False).write("hello")
    assert timeouts == [
        ("herdr agent prompt", launcher.PANE_WRITE_SECONDS),
        ("herdr pane run", launcher.PANE_WRITE_SECONDS),
    ]
    assert launcher.PANE_WRITE_SECONDS > 0

    def timed_out(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        timeouts.append((" ".join(cmd[:3]), k.get("timeout")))
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            timed: subprocess.CompletedProcess[str] = launcher.TimedOutProcess(
                cmd, 124, "", "timed out"
            )
            return timed
        return subprocess.CompletedProcess(cmd, 0, "", "")

    timeouts.clear()
    monkeypatch.setattr(launcher, "run", timed_out)
    with pytest.raises(SystemExit, match="did not return within"):
        launcher.PaneWriter(unit, "w1:p1", wrote_before=False).write("hello")
    assert [name for name, _ in timeouts] == ["herdr agent prompt"]


def test_a_pane_typing_timeout_names_the_ambiguity_like_the_prompt_door(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal review cycle 2, F60: the pane-typing door's timeout was a generic stop that
    never said the line may have reached the session. Both doors now raise the same shape."""

    def timed_out_typing(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            return subprocess.CompletedProcess(cmd, 1, "", "not interactive ready")
        if cmd[:3] == ["herdr", "pane", "run"]:
            timed: subprocess.CompletedProcess[str] = launcher.TimedOutProcess(
                cmd, 124, "", "timed out"
            )
            return timed
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", timed_out_typing)
    unit = launcher.LaunchRequest(
        name="worker", vendor="qwen", worktree="/tmp/wt", launch_receipt={"owned": True}
    )
    with pytest.raises(SystemExit, match="pane run into w1:p1 did not return within"):
        launcher.PaneWriter(unit, "w1:p1", wrote_before=False).write("hello")


def test_the_receipt_shape_reads_ownership_from_the_unit_not_the_receipt_it_replaces(
    launcher: ModuleType,
) -> None:
    """Cycle 2, F58: session_owned() prefers the receipt key, and the shape is built while
    the unit still holds the previous launch's receipt. The shape reads the unit attribute
    the caller just computed, so a stale receipt saying unowned cannot leak into a new one."""
    unit = launcher.LaunchRequest(
        name="worker", vendor="claude", worktree="/tmp/wt", launch_receipt={"owned": False}
    )
    info = {"tab_id": "w1:t-new", "agent_name": "worker-2", "pane_id": "w1:p1", "reused": False}
    receipt = launcher.record_wrapper_identity(unit, info, preexisting=frozenset())
    assert unit.owned is True
    assert receipt["owned"] is True


def test_wrapper_identity_receipt_is_the_shape_function_output(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal review F15: the receipt the wrapper create records is
    launch_receipt_shape's dict, built once from the attributes just set, not a second
    hand-typed literal of the same ten keys."""
    unit = launcher.LaunchRequest(name="worker", vendor="claude", worktree="/tmp/wt")
    info = {"tab_id": "w1:t-new", "agent_name": "worker-2", "pane_id": "w1:p1", "reused": "true"}
    receipt = launcher.record_wrapper_identity(unit, info, preexisting=frozenset())
    assert receipt == launcher.launch_receipt_shape(unit)
    assert receipt["owned"] is True
    assert receipt["reused"] is True
    assert receipt["pane"] == "w1:p1"
    assert unit.launch_receipt is receipt


# Every place in either plugin that puts a line into a session, enumerated. Each is a call on
# a ``PaneWriter`` named ``writer``; the class is the only owner of the two raw Herdr doors.
# Adding a write anywhere means adding a row here, and the mutation run in
# ``tools``-free form below (``test_forcing_the_guard_off_at_each_write_site_is_observed``)
# turns every row's guard off independently and expects a failing observation each time.
PANE_WRITE_SITES: tuple[tuple[str, str, str], ...] = (
    ("launcher.py", "drive_opencode_variant_selection", "picker open"),
    ("launcher.py", "drive_opencode_variant_selection", "variant select"),
    ("launcher.py", "send", "setup line"),
    ("launcher.py", "send", "task"),
)
RAW_DOORS = (("herdr", "pane", "run"), ("herdr", "agent", "prompt"))


def _enclosing_function(tree: ast.AST, target: ast.expr | ast.stmt) -> str:
    best = ""
    target_line = getattr(target, "lineno", 0) or 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.lineno <= target_line <= (
            node.end_lineno or node.lineno
        ):
            best = node.name
    return best


def _writer_write_calls(tree: ast.Module) -> list[str]:
    """Production write sites: ``writer.write(...)``. Aliased locals are a raw-door evasion."""
    return [
        _enclosing_function(tree, node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "writer"
    ]


def _assigned_values(tree: ast.AST) -> dict[str, ast.AST]:
    env: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                env[target.id] = node.value
    return env


def _run_aliases(tree: ast.AST) -> set[str]:
    aliases = {"run"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name):
            continue
        if node.value.id in aliases:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.add(target.id)
    return aliases


def _constant_str(node: ast.AST, env: dict[str, ast.AST]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Name) and node.id in env:
        return _constant_str(env[node.id], env)
    return None


def _sequence_elts(node: ast.AST, env: dict[str, ast.AST]) -> list[ast.AST] | None:
    if isinstance(node, ast.Name) and node.id in env:
        return _sequence_elts(env[node.id], env)
    if isinstance(node, (ast.List, ast.Tuple)):
        return list(node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _sequence_elts(node.left, env)
        right = _sequence_elts(node.right, env)
        if left is not None and right is not None:
            return left + right
    return None


def _argv_head(node: ast.AST, env: dict[str, ast.AST]) -> tuple[str, ...]:
    elts = _sequence_elts(node, env)
    if elts is None:
        return ()
    values: list[str] = []
    for elt in elts[:3]:
        text = _constant_str(elt, env)
        if text is None:
            break
        values.append(text)
    return tuple(values)


def _call_callee(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def _raw_door_calls(tree: ast.Module) -> list[tuple[int, str]]:
    """Every catchable pane-write evasion in *tree* (issue 1002 F121).

    Reports raw Herdr doors however they are constructed (list, tuple, concat,
    alias, keyword ``args=``, ``subprocess.run``, assigned constants, f-string
    element 0), plus ``._raw`` / ``._type`` attribute calls and inline
    ``session_owned`` guard re-derivations.
    """
    env = _assigned_values(tree)
    aliases = _run_aliases(tree)
    found: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()

    def add(node: ast.AST, label: str) -> None:
        line = getattr(node, "lineno", 0) or 0
        item = (line, label)
        if item not in seen:
            seen.add(item)
            found.append(item)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _call_callee(node)
            is_run = callee in aliases or callee == "subprocess.run"
            if is_run:
                argv_nodes = list(node.args[:1])
                argv_nodes.extend(kw.value for kw in node.keywords if kw.arg in {"args", None})
                for argv in argv_nodes:
                    head = _argv_head(argv, env)
                    if head[:3] in RAW_DOORS:
                        add(node, _enclosing_function(tree, node) or callee or "run")
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"_raw", "_type"}:
                add(node, _enclosing_function(tree, node) or func.attr)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "write"
                and isinstance(func.value, ast.Name)
                and func.value.id in {"w", "pw", "pane_writer"}
            ):
                add(node, _enclosing_function(tree, node) or func.value.id)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "write"
                and isinstance(func.value, ast.Name)
            ):
                bound = env.get(func.value.id)
                if (
                    isinstance(bound, ast.Call)
                    and isinstance(bound.func, ast.Name)
                    and bound.func.id == "PaneWriter"
                    and func.value.id != "writer"
                ):
                    add(node, _enclosing_function(tree, node) or func.value.id)
        if isinstance(node, (ast.If, ast.IfExp)) and "session_owned(" in ast.unparse(node):
            rendered = ast.unparse(node)
            if any(
                token in rendered
                for token in ("guard_pane", ".write(", "._raw", "._type", "'herdr'", '"herdr"')
            ):
                add(node, _enclosing_function(tree, node) or "inline-guard")
    return found


def test_every_pane_write_goes_through_the_one_writer(launcher: ModuleType) -> None:
    """The two raw Herdr doors exist only inside PaneWriter.write; every write site in
    launcher.py is a ``writer.write`` and the set of sites is exactly the enumerated one;
    and no function in this file re-derives the guard predicate inline. The Orchestrate
    half of this net stays with that package. This is a net for those shapes, not a
    proof of impossibility (issue 1002 F121)."""
    launcher_tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    writer_class = next(
        node
        for node in launcher_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PaneWriter"
    )
    strays = [
        (line, fn)
        for line, fn in _raw_door_calls(launcher_tree)
        if not (writer_class.lineno <= line <= (writer_class.end_lineno or line))
    ]
    assert strays == [], f"raw pane-write door outside PaneWriter in launcher.py: {strays}"
    assert len(_raw_door_calls(launcher_tree)) == 2, "one prompt door and one typing door"
    sites = sorted(
        [(f, fn) for f, fn, _ in PANE_WRITE_SITES],
    )
    observed = sorted([("launcher.py", fn) for fn in _writer_write_calls(launcher_tree)])
    assert observed == sites, f"write sites drifted from the enumeration: {observed}"
    for tree, name in ((launcher_tree, "launcher.py"),):
        owner = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "should_guard_pane_write"
            ),
            None,
        )
        inline = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.BoolOp)
            and "session_owned(" in ast.unparse(node)
            and not (
                owner is not None
                and owner.lineno <= node.lineno <= (owner.end_lineno or owner.lineno)
            )
        ]
        assert inline == [], f"guard predicate re-derived inline in {name} at {inline}"
    owned = launcher.LaunchRequest(
        name="w", vendor="claude", owned=True, launch_receipt={"owned": True}
    )
    unowned = launcher.LaunchRequest(name="w", vendor="claude", launch_receipt={"owned": False})
    assert launcher.should_guard_pane_write(owned, wrote_before=False) is False
    assert launcher.should_guard_pane_write(owned, wrote_before=True) is True
    assert launcher.should_guard_pane_write(unowned, wrote_before=False) is True
    assert launcher.should_guard_pane_write(unowned, wrote_before=True) is True


def _prepare_opencode_launch(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing_tabs: tuple[str, ...],
    composer_dumps: list[str] | None = None,
    accepted: bool = True,
) -> tuple[Any, list[list[str]], list[str], list[str]]:
    """An OpenCode launch with the real picker driver, the real writer and the real guard,
    only the Herdr boundary stubbed. Recent-unwrapped reads serve the picker menu; ANSI reads
    serve ``composer_dumps`` in order (the last repeats). Returns the unit, every recorded
    command, the pane-typed lines, and the guard calls."""
    recorded: list[list[str]] = []
    typed: list[str] = []
    guard_calls: list[str] = []
    dumps = iter(composer_dumps or [_claude_pane("❯ ")])
    last = (composer_dumps or [_claude_pane("❯ ")])[-1]
    receipt = {"tab_id": "w80:t1", "agent_name": "oc-2", "pane_id": "w80:p9", "reused": False}

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        if cmd[:3] == ["herdr", "pane", "run"]:
            typed.append(cmd[-1])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["herdr", "pane", "read"] and "--format" in cmd:
            return subprocess.CompletedProcess(cmd, 0, next(dumps, last), "")
        if cmd[:3] == ["herdr", "pane", "read"]:
            return subprocess.CompletedProcess(cmd, 0, "Select variant\n> high\n> low\n", "")
        if cmd[:3] == ["herdr", "tab", "list"]:
            tabs = {"result": {"tabs": [{"tab_id": t, "label": t} for t in existing_tabs]}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(tabs), "")
        if cmd[:3] == ["herdr", "pane", "current"]:
            pane = {"result": {"pane": {"workspace_id": "w80"}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(pane), "")
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), "")

    real_guard = launcher.guard_pane_before_write

    def counting_guard(unit: Any, pane_id: str) -> None:
        guard_calls.append(pane_id)
        real_guard(unit, pane_id)

    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(
        launcher, "verify_unit_identity", lambda *a, **k: ([], [], "opencode", True)
    )
    monkeypatch.setattr(launcher, "verify_unit_preflight", lambda *a, **k: {})
    monkeypatch.setattr(launcher, "guard_pane_before_write", counting_guard)
    monkeypatch.setattr(launcher, "took_the_task", lambda *_a, **_k: accepted)
    monkeypatch.setattr(
        launcher,
        "agent_row",
        lambda *_a, **_k: {
            "agent_status": "idle",
            "pane_id": "w80:p9",
            "cwd": "/tmp/wt",
            "workspace_id": "w80",
            "interactive_ready": True,
            "agent": "opencode",
        },
    )
    unit = launcher.LaunchRequest(name="oc", vendor="opencode", worktree="/tmp/wt", effort="high")
    return unit, recorded, typed, guard_calls


def _prompts(recorded: list[list[str]]) -> list[list[str]]:
    return [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]]


def test_an_unowned_opencode_launch_inspects_before_all_three_writes(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The picker's two writes and the task are three writes through one writer, each
    inspected on an unowned session -- observed as guard calls at the real guard, with the
    real picker driver typing into the pane."""
    unit, recorded, typed, guard_calls = _prepare_opencode_launch(
        launcher, monkeypatch, existing_tabs=("w80:t1",)
    )
    launcher.launch(unit)
    assert typed == ["/variants", "high"]
    assert len(_prompts(recorded)) == 1
    assert guard_calls == ["w80:p9", "w80:p9", "w80:p9"]
    assert unit.variant == "high"
    assert unit.status == launcher.RUNNING


def test_an_owned_opencode_launch_inspects_before_the_select_and_the_task(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal review cycle 2, F40/F47: at 7aa0e3b7 an owned OpenCode launch made three
    pane writes with no inspection, because the picker never set the write flag. The writer
    records its own first write -- the picker opening -- so the variant select and the task
    are both inspected; only that first write into the fresh tab is exempt."""
    unit, recorded, typed, guard_calls = _prepare_opencode_launch(
        launcher, monkeypatch, existing_tabs=()
    )
    launcher.launch(unit)
    assert unit.owned is True
    assert typed == ["/variants", "high"]
    assert len(_prompts(recorded)) == 1
    assert guard_calls == ["w80:p9", "w80:p9"]


def test_an_owned_opencode_redelivery_inspects_before_every_write(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal review cycle 2, F39: the picker write site on the retry door, where the
    write half of the rule is load-bearing. A redelivery seeds the writer as having written,
    so the picker open, the select and the task are all inspected."""
    unit, recorded, typed, guard_calls = _prepare_opencode_launch(
        launcher, monkeypatch, existing_tabs=()
    )
    unit.pane_id, unit.tab_id, unit.owned = "w80:p9", "w80:t1", True
    unit.launch_receipt = {
        "tab_id": "w80:t1",
        "pane": "w80:p9",
        "owned": True,
        "input_box": "staged",
    }
    launcher.redeliver(unit)
    assert typed == ["/variants", "high"]
    assert len(_prompts(recorded)) == 1
    assert guard_calls == ["w80:p9", "w80:p9", "w80:p9"]


def test_a_draft_staged_while_the_picker_was_open_stops_the_task(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REL-08 rebuilt on the writer: the inspection before the task is taken after the picker
    and the preflight, so a draft staged in between still stops the send. The classifier has
    no OpenCode entry, so the stop is modelled at the guard boundary while the read sites and
    the picker driver are real: the run stub serves an empty composer to the first two reads
    and a staged draft to the third."""
    unit, recorded, typed, guard_calls = _prepare_opencode_launch(
        launcher,
        monkeypatch,
        existing_tabs=("w80:t1",),
        composer_dumps=[
            _claude_pane("❯ "),
            _claude_pane("❯ "),
            _claude_pane(f"❯ {STAGED_SLASH_COMMAND}"),
        ],
    )

    def guard(unit: Any, pane_id: str) -> None:
        guard_calls.append(pane_id)
        inspection = launcher.pane_input_inspection(pane_id, vendor="claude")
        if inspection.state is launcher.ComposerState.STAGED:
            raise launcher.StagedInputError("third read found staged input")

    monkeypatch.setattr(launcher, "guard_pane_before_write", guard)
    with pytest.raises(launcher.StagedInputError, match="third read"):
        launcher.launch(unit)
    assert typed == ["/variants", "high"]
    assert _prompts(recorded) == []
    assert len(guard_calls) == 3


def test_each_setup_line_and_the_task_are_separately_inspected(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal review cycle 2, F41: send() was several writes -- one per setup slash command,
    then the task -- behind one guard, so the task could land up to a minute past its
    inspection. Each write is now its own inspected write: guard calls equal writes on an
    unowned launch, and on an owned fresh launch only the very first write is exempt."""
    unit, recorded, sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane("❯ "),
        receipt_tab="w80:t1",
        existing_tabs=("w80:t1",),
    )
    unit.setup = ["/effort high", "/model opus"]
    guard_calls: list[str] = []
    real_guard = launcher.guard_pane_before_write

    def counting_guard(u: Any, pane_id: str) -> None:
        guard_calls.append(pane_id)
        real_guard(u, pane_id)

    monkeypatch.setattr(launcher, "guard_pane_before_write", counting_guard)
    launcher.launch(unit)
    expected_task = launcher.normalize_task(
        unit.vendor, unit.task, "inline", review_elsewhere=False
    )
    assert [c[4] for c in sends] == ["/effort high", "/model opus", expected_task]
    assert len(sends) == 3
    assert len(guard_calls) == 3

    owned, owned_recorded, owned_sends = _prepare_guard_launch(
        launcher,
        monkeypatch,
        pane_dump=_claude_pane("❯ "),
        receipt_tab="w80:t-new",
        existing_tabs=(),
    )
    owned.setup = ["/effort high", "/model opus"]
    guard_calls.clear()
    monkeypatch.setattr(launcher, "guard_pane_before_write", counting_guard)
    launcher.launch(owned)
    assert owned.owned is True
    assert len(owned_sends) == 3
    assert len(guard_calls) == 2


def test_the_picker_refusal_reports_a_count_not_the_scraped_options(
    launcher: ModuleType,
) -> None:
    """Cycle 2, F74: the option tokens were scraped from the pane and the refusal interpolated
    them into a stop that becomes the unit note and the run record. Only the count is reported."""
    with pytest.raises(SystemExit) as stop:
        launcher.resolve_opencode_variant("turbo", ["high", "low"])
    message = str(stop.value)
    assert "2 options" in message
    assert "high" not in message and "low" not in message
    assert "'turbo'" in message


@pytest.mark.parametrize(
    ("readback", "seen_in", "confirmed"),
    [
        ("Select variant\n> high\n> low\n", "picker_menu_only", False),
        ("Select variant\n> high\n> low\nvariant: high\n", "session", True),
    ],
)
def test_variant_confirmation_records_whether_the_token_was_seen_outside_the_menu(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    readback: str,
    seen_in: str,
    confirmed: bool,
) -> None:
    """Cycle 2, F75: the confirmation searched the same pane the token was scraped from, and
    the picker menu lists every option, so finding the token there proved nothing. The source
    is now recorded on the receipt and the preflight confirms the variant only when the session
    itself showed it on a non-menu row."""
    monkeypatch.setattr(launcher, "read_pane", lambda *_a, **_k: readback)
    unit = launcher.LaunchRequest(
        name="oc", vendor="opencode", worktree="/tmp/wt", variant="high", launch_receipt={}
    )
    assert launcher.confirm_opencode_variant_selected(unit, "w80:p9", "high") == seen_in
    unit.launch_receipt["variant_confirmed_from"] = seen_in
    monkeypatch.setattr(
        launcher, "verify_unit_identity", lambda *a, **k: (["pane"], [], "opencode", True)
    )
    receipt = launcher.verify_unit_preflight(unit, "w80:p9", ready=True)
    assert ("variant" in receipt["confirmed_against_herdr"]) is confirmed
    assert ("variant" in receipt["requested_only"]) is (not confirmed)


def test_an_absent_variant_token_is_still_a_stop(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counter-case for F75: recording the source does not weaken the existing stop."""
    monkeypatch.setattr(launcher, "read_pane", lambda *_a, **_k: "Select variant\n> low\n")
    unit = launcher.LaunchRequest(name="oc", vendor="opencode", worktree="/tmp/wt")
    with pytest.raises(SystemExit, match="does not report it"):
        launcher.confirm_opencode_variant_selected(unit, "w80:p9", "high")


def _staged_receipt(**over: Any) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "unit_name": "worker",
        "vendor": "claude",
        "tab_id": "w1:t1",
        "pane": "w1:p1",
        "agent_name": "worker-2",
        "reused": False,
        "owned": True,
        "input_box": "staged",
        "input_box_text_chars": 12,
        "prompt_delivered": None,
    }
    receipt.update(over)
    return receipt


def test_redeliver_cli_adopts_the_stop_receipt_and_never_creates(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    """Terminal review F07: the staged-input stop has a CLI-reachable standalone recovery.
    The retry takes tab, pane and ownership from the receipt the stop wrote and the task
    from the same flags launch took; it goes through redeliver(), never launch()."""
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(_staged_receipt()))
    seen: list[Any] = []

    def fake_redeliver(unit: Any, *_a: object, **_k: object) -> None:
        seen.append(unit)
        unit.status = launcher.RUNNING
        unit.launch_receipt["prompt_delivered"] = True

    monkeypatch.setattr(launcher, "redeliver", fake_redeliver)
    monkeypatch.setattr(launcher, "launch", lambda *_a, **_k: pytest.fail("launch was run"))
    rc = launcher.cli_main(
        [
            "redeliver",
            "--vendor",
            "claude",
            "--task",
            "worker",
            "--cwd",
            str(tmp_path),
            "--prompt",
            "do the thing",
            "--receipt-json",
            str(receipt_path),
        ]
    )
    assert rc == 0
    (unit,) = seen
    assert (unit.tab_id, unit.pane_id, unit.agent_name, unit.owned) == (
        "w1:t1",
        "w1:p1",
        "worker-2",
        True,
    )
    assert unit.task == "do the thing"
    printed = json.loads(capsys.readouterr().out)
    assert printed["prompt_delivered"] is True
    assert printed["tab_id"] == "w1:t1"


def test_redeliver_cli_exits_nonzero_when_the_prompt_was_not_taken(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(_staged_receipt()))

    def withheld(unit: Any, *_a: object, **_k: object) -> None:
        unit.status = launcher.PROMPT_UNDELIVERED
        unit.launch_receipt["prompt_delivered"] = False

    monkeypatch.setattr(launcher, "redeliver", withheld)
    rc = launcher.cli_main(
        [
            "redeliver",
            "--vendor",
            "claude",
            "--task",
            "worker",
            "--prompt",
            "do it",
            "--receipt-json",
            str(receipt_path),
        ]
    )
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["prompt_delivered"] is False


@pytest.mark.parametrize(
    ("over", "prompt", "message"),
    [
        ({"unit_name": "other"}, "do it", "written for task 'other'"),
        ({"input_box": "empty", "prompt_delivered": None}, "do it", "neither a staged-input stop"),
        ({"prompt_delivered": True, "input_box": None}, "do it", "already delivered"),
        ({"pane": None}, "do it", "records no pane"),
        ({"pane_id": "w1:p1", "pane": None}, "do it", "records no pane"),
        ({}, "", "--prompt is empty"),
    ],
)
def test_redeliver_cli_refuses_a_receipt_it_will_not_retry_with_exit_2(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
    over: dict[str, Any],
    prompt: str,
    message: str,
) -> None:
    """Counter-cases for F07, and cycle 2 F61/F63/F64: the retry door is only for a staged
    stop or an undelivered prompt. A receipt for another task, one whose prompt was
    delivered, one with no pane (the dead `pane_id` alias no longer counts), or an empty
    prompt is refused before any Herdr call, with exit code 2 and the reason on stderr."""
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(_staged_receipt(**over)))
    monkeypatch.setattr(launcher, "run", lambda *_a, **_k: pytest.fail("herdr was called"))
    monkeypatch.setattr(launcher, "redeliver", lambda *_a, **_k: pytest.fail("redeliver ran"))
    rc = launcher.cli_main(
        [
            "redeliver",
            "--vendor",
            "claude",
            "--task",
            "worker",
            "--prompt",
            prompt,
            "--receipt-json",
            str(receipt_path),
        ]
    )
    assert rc == 2
    assert message in capsys.readouterr().err


def test_redeliver_cli_accepts_an_undelivered_receipt(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    """Cycle 2, F76: a prompt that was sent but never observed to be taken is the other
    retryable shape; the receipt's prompt_delivered false opens the door."""
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(_staged_receipt(input_box="empty", prompt_delivered=False)))
    seen: list[Any] = []

    def fake_redeliver(unit: Any, *_a: object, **_k: object) -> None:
        seen.append(unit)
        unit.status = launcher.RUNNING
        unit.launch_receipt["prompt_delivered"] = True

    monkeypatch.setattr(launcher, "redeliver", fake_redeliver)
    rc = launcher.cli_main(
        [
            "redeliver",
            "--vendor",
            "claude",
            "--task",
            "worker",
            "--prompt",
            "do it",
            "--receipt-json",
            str(receipt_path),
        ]
    )
    assert rc == 0 and len(seen) == 1
    assert json.loads(capsys.readouterr().out)["prompt_delivered"] is True


def test_a_retry_receipt_without_an_ownership_key_verifies_identity(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Issue 1002 F112: a receipt that omits `owned` is refused, not adopted as unowned."""
    receipt = _staged_receipt()
    del receipt["owned"]
    adopted = launcher.LaunchRequest(name="worker", vendor="claude", worktree="/tmp/wt", task="x")
    with pytest.raises(launcher.RetryReceiptRefused, match="records no owned key"):
        launcher._adopt_retry_receipt(adopted, receipt)


FAKE_HERDR_FOR_REDELIVER = """#!/usr/bin/env python3
import json, os, sys
log = os.environ["HERDR_LOG"]
state = os.environ["HERDR_STATE"]
argv = sys.argv[1:]
with open(log, "a") as fh:
    fh.write(" ".join(argv) + "\\n")
if argv[:2] == ["agent", "list"]:
    status = "working" if os.path.exists(state) else "idle"
    row = {"name": "worker-2", "agent": "claude", "pane_id": "w1:p1", "workspace_id": "w1",
           "cwd": os.environ["HERDR_CWD"], "interactive_ready": True, "agent_status": status}
    print(json.dumps({"result": {"agents": [row]}}))
elif argv[:2] == ["pane", "read"] and "--format" in argv:
    print("\\x1b[2m────\\x1b[0m\\n❯ \\n\\x1b[2m────\\x1b[0m")
elif argv[:2] == ["pane", "read"]:
    print("")
elif argv[:2] == ["agent", "prompt"]:
    open(state, "w").close()
sys.exit(0)
"""


def test_redeliver_cli_as_a_real_subprocess_reprompts_the_recorded_pane(tmp_path: Path) -> None:
    """The command under test run as a real subprocess with a fake herdr and agents on PATH:
    no fixture stands in for the launcher. The receipt's pane is inspected once before the
    prompt, the wrapper create never runs, the session leaves idle after the prompt, and the
    updated receipt comes back on stdout with the exit code saying delivered."""
    worktree = tmp_path / "wt"
    worktree.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    herdr = bin_dir / "herdr"
    herdr.write_text(FAKE_HERDR_FOR_REDELIVER, encoding="utf-8")
    herdr.chmod(0o755)
    agents = bin_dir / "agents"
    agents.write_text("#!/bin/sh\necho 'the wrapper create must not run' >&2\nexit 9\n")
    agents.chmod(0o755)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(_staged_receipt()))
    log = tmp_path / "herdr.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "HERDR_LOG": str(log),
        "HERDR_STATE": str(tmp_path / "prompted"),
        "HERDR_CWD": str(worktree.resolve()),
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            "redeliver",
            "--vendor",
            "claude",
            "--task",
            "worker",
            "--cwd",
            str(worktree),
            "--prompt",
            "do the thing",
            "--receipt-json",
            str(receipt_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["prompt_delivered"] is True
    assert receipt["tab_id"] == "w1:t1"
    assert receipt["input_box"] == "empty"
    calls = [line.split() for line in log.read_text(encoding="utf-8").splitlines()]
    prompts = [i for i, c in enumerate(calls) if c[:2] == ["agent", "prompt"]]
    reads = [i for i, c in enumerate(calls) if c[:2] == ["pane", "read"] and "--format" in c]
    assert len(prompts) == 1
    assert len(reads) == 1 and reads[0] < prompts[0]
    assert "the wrapper create must not run" not in proc.stderr
    assert calls[prompts[0]][2] == "worker-2"


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


def test_failing_tab_close_is_recorded_on_the_unit(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "no such tab")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="x", vendor="codex", tab_id="tab-owned", owned=True)
    launcher.close_run_session(unit)
    assert "tab close failed" in unit.note
    assert "tab-owned" in unit.note
    assert "no such tab" in unit.note


def test_failing_tab_close_exits_nonzero_through_the_cli_variant(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "no such tab")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="x", vendor="codex", tab_id="tab-owned")
    with pytest.raises(SystemExit, match="tab close failed"):
        launcher.close_owned_session(unit, receipt={"tab_id": "tab-owned", "owned": True})


def test_successful_close_adds_no_note(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        closed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="x", vendor="codex", tab_id="tab-owned", owned=True)
    launcher.close_run_session(unit)
    assert closed == [["herdr", "tab", "close", "tab-owned"]]
    assert unit.note == ""


def test_already_absent_owned_tab_is_an_idempotent_success(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        if cmd[:3] == ["herdr", "tab", "list"]:
            return subprocess.CompletedProcess(cmd, 0, '{"result":{"tabs":[]}}', "")
        return subprocess.CompletedProcess(cmd, 1, "", "tab not found")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="x", vendor="codex", tab_id="w1:t-gone", owned=True)
    result = launcher.close_run_session(unit)
    assert result is not None and result.returncode == 0
    assert unit.note == ""
    assert calls[0][1]["timeout"] == launcher.TAB_CLOSE_SECONDS


def test_unowned_session_closes_nothing_and_reports_nothing(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        closed.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "no such tab")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="x", vendor="codex", tab_id="tab-old", owned=False)
    launcher.close_run_session(unit)
    assert closed == []
    assert unit.note == ""


def test_missing_receipt_path_names_the_path_and_the_recovery(launcher: ModuleType) -> None:
    with pytest.raises(SystemExit) as exc_info:
        launcher._load_receipt("/no/such/receipt.json")
    message = str(exc_info.value)
    assert "/no/such/receipt.json" in message
    assert "> receipt.json" in message


def test_missing_receipt_path_through_the_cli_exits_without_a_traceback() -> None:
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER), "close", "--receipt-json", "/no/such/receipt.json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr


def test_inline_malformed_json_keeps_its_existing_stop_shape(launcher: ModuleType) -> None:
    with pytest.raises(json.JSONDecodeError):
        launcher._load_receipt('{"a":')


@pytest.mark.parametrize("contents", ["", '{"tab_id":'])
def test_malformed_receipt_file_has_a_named_recovery_stop(
    launcher: ModuleType, tmp_path: Path, contents: str
) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        launcher._load_receipt(str(path))
    message = str(exc_info.value)
    assert str(path) in message
    assert "empty or unparseable JSON" in message
    assert "fresh receipt file" in message


def test_valid_receipt_file_is_unchanged(launcher: ModuleType, tmp_path: Path) -> None:
    receipt = {"tab_id": "t1", "owned": True}
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert launcher._load_receipt(str(path)) == receipt


def test_valid_inline_json_is_unchanged(launcher: ModuleType) -> None:
    assert launcher._load_receipt('{"tab_id": "t1", "owned": true}') == {
        "tab_id": "t1",
        "owned": True,
    }


def test_non_object_json_keeps_its_message(launcher: ModuleType) -> None:
    with pytest.raises(SystemExit, match="must be a JSON object"):
        launcher._load_receipt("[1, 2]")


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
    monkeypatch.setattr(launcher, "verify_unit_account", lambda *a, **k: (None, "none"))
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
    closed: list[str] = []
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
    monkeypatch.setattr(
        launcher, "close_run_session", lambda unit: closed.append(unit.tab_id or "")
    )
    unit = launcher.LaunchRequest(
        name="reviewer", vendor="codex", worktree="/tmp/wt", pane_id="pane-1", tab_id="tab-1"
    )
    with pytest.raises(SystemExit, match="working directory"):
        launcher.verify_unit_preflight(unit, "pane-1", ready=True)
    assert closed == ["tab-1"]


def test_task_name_with_separator_is_refused_before_any_write(launcher: ModuleType) -> None:
    with pytest.raises(SystemExit, match="path separator"):
        launcher.assert_safe_path_component("../victim/CLAUDE", "task name")
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
    unit = launcher.LaunchRequest(name="u-777", vendor="codex", tab_id="w80:t4", owned=False)
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
                                {"tab_id": "w80:t4", "label": "u-777"},
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
    _no_host_herdr(launcher, monkeypatch)
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
    assert unit.launch_receipt["tab_id"] == "tab-recover"
    assert unit.launch_receipt["agent_name"] == "reviewer-2"
    assert unit.launch_receipt["reused"] is False


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




def test_skill_cleanup_example_redirects_receipt() -> None:
    skill = (
        REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "> receipt.json" in skill
    assert "close --receipt-json receipt.json" in skill
    assert "close --tab-id <tab_id> --receipt-json <receipt.json>" not in skill
    assert "owned" in skill
    assert "workspace" in skill.lower()
    assert "tab set snapshotted immediately before" in skill or "pre-launch" in skill


def test_skill_declares_herdr_dependency_and_no_duplicate_herdr_skill() -> None:
    skill = (
        REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "canonical `herdr` skill" in skill
    assert "does not ship a copy" in skill
    herdr_skill = REPO / "plugins" / "agent-launcher" / "skills" / "herdr"
    assert not herdr_skill.exists()


SKILL_MD = REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "SKILL.md"
LAUNCHER_README = REPO / "plugins" / "agent-launcher" / "README.md"
BINARY_AUTHORITY_HEADING = "## The binary is the authority"
PREFLIGHT_HEADING = "## The only real preflight is a bounded live launch with a read-back"
ORDERING_HEADING = "## Ordering — the most common mistake"
CREDENTIAL_WORDS = ("key", "token", "secret", "password", "credential")
ALLOWLIST_ENTRIES = (
    "model",
    "reasoning effort",
    "permission posture",
    "account or route",
    "working directory",
    "workspace",
)


def _skill_section(skill: str, heading: str, stop: str) -> str:
    start = skill.index(heading)
    end = skill.index(stop)
    assert start < end
    return skill[start:end]


def _code_fences(text: str) -> list[str]:
    return re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL)


def _environment_dump_violations(text: str) -> list[str]:
    violations: list[str] = []
    for pattern in (r"\benv\b", r"\bprintenv\b", r"os\.environ", r"\bdiff\b[^\n]*\benv"):
        violations.extend(re.findall(pattern, text))
    return violations


def _value_persist_violations(text: str) -> list[str]:
    violations: list[str] = []
    for pattern in (r"\bsha256\w*", r"\bmd5\w*", r"\bbase64\b", r"cut -c", r"head -c"):
        violations.extend(re.findall(pattern, text))
    for line in text.splitlines():
        if ">" in line and any(word in line.lower() for word in CREDENTIAL_WORDS):
            violations.append(line)
    return violations


def _downstream_redaction_violations(text: str) -> list[str]:
    violations: list[str] = []
    for line in text.splitlines():
        segments = line.split("|")
        if len(segments) > 1 and any(
            re.search(r"\b(sed|awk|grep|tr)\b", segment) for segment in segments[1:]
        ):
            violations.append(line)
    return violations


def _guidance_fences() -> list[str]:
    skill = SKILL_MD.read_text(encoding="utf-8")
    guidance = _skill_section(skill, BINARY_AUTHORITY_HEADING, ORDERING_HEADING)
    readme = LAUNCHER_README.read_text(encoding="utf-8")
    return _code_fences(guidance) + _code_fences(readme)


def test_dry_run_guidance_names_what_it_does_not_validate() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = _skill_section(skill, BINARY_AUTHORITY_HEADING, PREFLIGHT_HEADING)
    assert "does not validate the model" in section
    assert "reasoning effort" in section
    assert "account" in section


def test_dry_run_is_not_described_as_sufficient_preflight() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "Use it before every creation command." not in skill
    assert PREFLIGHT_HEADING in skill


def test_readme_and_skill_agree_on_dry_run() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8").lower()
    readme = LAUNCHER_README.read_text(encoding="utf-8").lower()
    for surface in (skill, readme):
        assert "does not confirm model, effort, or account" in surface


def test_guidance_names_an_allowlist_with_no_credential_entry() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = _skill_section(skill, PREFLIGHT_HEADING, ORDERING_HEADING)
    marker = "allowlist of launch arguments when reading a session back:"
    start = section.index(marker) + len(marker)
    entries = section[start : section.index("Never inspect argv wholesale", start)]
    for entry in ALLOWLIST_ENTRIES:
        assert entry in entries
    for word in CREDENTIAL_WORDS:
        assert word not in entries


def test_guidance_states_the_ordering_rule() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = _skill_section(skill, PREFLIGHT_HEADING, ORDERING_HEADING)
    identify = section.index("Identify the selected client auth mechanism")
    oauth = section.index("For an OAuth session")
    declared = section.index("Only when a declared run contract")
    assert identify < oauth < declared


def test_oauth_path_is_the_default_and_touches_no_environment() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    section = _skill_section(skill, PREFLIGHT_HEADING, ORDERING_HEADING)
    start = section.index("For an OAuth session")
    end = section.index("Only when a declared run contract")
    assert start < end
    passage = section[start:end]
    assert "documented default" in passage
    for pattern in (r"\benv\b", r"\bprintenv\b", r"os\.environ", r"\$[A-Z][A-Z0-9_]*"):
        assert re.search(pattern, passage) is None


def test_environment_access_is_gated_on_a_declared_contract() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    dry_run = _skill_section(skill, BINARY_AUTHORITY_HEADING, PREFLIGHT_HEADING)
    preflight = _skill_section(skill, PREFLIGHT_HEADING, ORDERING_HEADING)
    assert "environment" not in dry_run
    assert "declared run contract" in preflight


def test_environment_check_asserts_presence_of_a_name_only() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    preflight = _skill_section(skill, PREFLIGHT_HEADING, ORDERING_HEADING)
    assert "presence of the required variable name" in preflight
    assert "never its value" in preflight
    for fence in _code_fences(preflight):
        assert "==" not in fence and "!=" not in fence
        assert "echo $" not in fence


def test_no_specific_credential_variable_is_named() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    readme = LAUNCHER_README.read_text(encoding="utf-8")
    pattern = r"[A-Z][A-Z0-9_]{3,}_(KEY|TOKEN|SECRET|PASSWORD)"
    assert re.search(pattern, skill) is None
    assert re.search(pattern, readme) is None


def test_no_example_dumps_diffs_or_serialises_an_environment() -> None:
    for fence in _guidance_fences():
        assert _environment_dump_violations(fence) == []


def test_no_example_hashes_truncates_or_persists_a_value() -> None:
    for fence in _guidance_fences():
        assert _value_persist_violations(fence) == []


def test_redaction_appears_inside_the_producing_command() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    preflight = _skill_section(skill, PREFLIGHT_HEADING, ORDERING_HEADING)
    assert "Redact inside the producing command" in preflight
    for fence in _guidance_fences():
        assert _downstream_redaction_violations(fence) == []


def test_no_credential_shaped_literal_appears() -> None:
    for surface in (
        SKILL_MD.read_text(encoding="utf-8"),
        LAUNCHER_README.read_text(encoding="utf-8"),
    ):
        for run in re.findall(r"[A-Za-z0-9_-]{20,}", surface):
            uppercase = sum(1 for ch in run if ch.isupper())
            assert uppercase < 3, f"credential-shaped literal {run!r}"


def test_environment_dump_example_would_fail_its_guard() -> None:
    fixture = "some-command && printenv"
    assert _environment_dump_violations(fixture) != []


def test_hashing_example_would_fail_its_guard() -> None:
    fixture = "sha256sum ./receipt.json"
    assert _value_persist_violations(fixture) != []


def test_downstream_only_redaction_would_fail_its_guard() -> None:
    fixture = "launch | sed 's/.*/REDACTED/'"
    assert _downstream_redaction_violations(fixture) != []


def test_the_documented_preflight_recipe_is_runnable(launcher: ModuleType) -> None:
    """The probe recipe must actually run: a prompt (and the account flag when an account is
    named) on the launch line, an exit-status statement, and a read-back that selects only keys
    the receipt can supply -- never the model, which is the request echoed back."""
    skill = (
        REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "SKILL.md"
    ).read_text(encoding="utf-8")
    section = skill[skill.index("## The only real preflight") : skill.index("## Ordering")]
    launch_lines = [line for line in section.splitlines() if "launch --vendor" in line]
    assert launch_lines
    probe = launch_lines[-1]
    command = probe.removesuffix(" > receipt.json")
    tokens = shlex.split(command)
    assert tokens[:2] == ["python3", "$S"]
    replacements = {
        "<probe-name>": "probe",
        "$PWD": "/tmp/worktree",
        "<model>": "model",
        "<effort>": "high",
        "<selection>": "company",
        "<probe-task>": "verify readiness",
    }
    parsed = launcher._build_parser().parse_args(
        [replacements.get(token, token) for token in tokens[2:]]
    )
    assert parsed.cmd == "launch"
    assert parsed.vendor == "claude"
    assert parsed.prompt == "verify readiness"
    assert parsed.account == "company"
    assert "only when creation, identity, preflight, and delivery all succeed" in section
    jq_lines = [line for line in section.splitlines() if line.startswith("jq ")]
    assert jq_lines
    assert "model" not in jq_lines[-1]
    assert "confirmed_against_herdr" in jq_lines[-1]


def test_every_documented_launcher_fence_carries_a_prompt_and_nonzero_caveat() -> None:
    for path in (SKILL_MD, LAUNCHER_README):
        surface = path.read_text(encoding="utf-8")
        launch_lines = [line for line in surface.splitlines() if 'python3 "$S" launch' in line]
        assert launch_lines, path
        assert all("--prompt" in line for line in launch_lines), path
        assert "without one" in surface.lower(), path
        assert "exits nonzero" in surface.lower(), path


def test_launcher_failure_messages_do_not_interpolate_whole_argv() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "' '.join(cmd)" not in source
    assert '" ".join(cmd)' not in source
    assert "' '.join(argv)" not in source
    assert '" ".join(argv)' not in source


def test_release_and_journal_record_the_composer_contract() -> None:
    """Package-local half of the upstream release check.

    The journal and Orchestrate anchors stay in the upstream repository. This
    catalog's journal is consolidated by the lead, so this test holds the
    changelog, the skill, and composer.py only.
    """
    changelog = (REPO / "plugins" / "agent-launcher" / "CHANGELOG.md").read_text(encoding="utf-8")
    skill = SKILL_MD.read_text(encoding="utf-8")
    composer = (
        REPO
        / "plugins"
        / "agent-launcher"
        / "skills"
        / "agent-launcher"
        / "scripts"
        / "composer.py"
    ).read_text(encoding="utf-8")
    assert "## [1.4.0] - 2026-09-02" in changelog
    assert "## [1.3.0] - 2026-09-02" in changelog
    assert "PaneWriter" in changelog
    assert "## [1.2.2] - 2026-09-02" in changelog
    assert "`redeliver` subcommand" in changelog
    assert "selects the last block positionally" in changelog
    assert "`unclassifiable`, `not_found`, `unsupported_vendor`, `read_failed`" in changelog
    normalized_changelog = " ".join(changelog.split())
    assert "distinguishes a client's own placeholder from staged text" not in normalized_changelog
    assert "Claude, Codex, Grok, Agy, and Qwen" in skill
    assert "#907-composer-structural-continuations" in composer
    assert "#907-input-box-visible-length" in composer








def test_claude_quoted_second_row_is_staged_not_empty(launcher: ModuleType) -> None:
    """Issue 1002 F102: a Claude box whose second row begins with `>` is staged."""
    dump = "❯ \n> quoted draft line"
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text is not None and "quoted draft line" in result.text


def test_empty_marker_below_staged_draft_is_a_decoy(launcher: ModuleType) -> None:
    """Issue 1002 F110: a painted empty marker under a staged draft does not read EMPTY."""
    result = launcher.inspect_composer("❯ staged draft\n❯ ", vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "staged draft"


def test_blank_separated_empty_marker_below_staged_is_a_decoy(launcher: ModuleType) -> None:
    """Issue 1002 F110 / R5: only-blank rows between a staged block and a later empty
    marker are painted chrome. The guard must see STAGED, not EMPTY."""
    result = launcher.inspect_composer("❯ staged draft\n\n❯ ", vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "staged draft"


def test_ansi_only_separator_below_staged_is_a_decoy(launcher: ModuleType) -> None:
    """Issue 1002 F110: a painted ANSI-only row is a blank to the parser, so it cannot
    authorize a write over a still-staged draft. Production reads --format ansi."""
    dump = "❯ staged draft\n\x1b[0m\n❯ "
    result = launcher.inspect_composer(dump, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "staged draft"
    painted = "❯ staged draft\n\x1b[48;2;55;55;55m   \x1b[0m\n❯ "
    painted_result = launcher.inspect_composer(painted, vendor="claude")
    assert painted_result.state is launcher.ComposerState.STAGED
    assert painted_result.text == "staged draft"


def test_two_trailing_empty_markers_below_staged_are_decoys(launcher: ModuleType) -> None:
    """Issue 1002 F110: walk past every trailing empty decoy, not only the last one."""
    result = launcher.inspect_composer("❯ staged draft\n❯ \n❯ ", vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "staged draft"


def test_done_is_a_started_status(launcher: ModuleType) -> None:
    """Issue 1002 F118: Herdr `done` means the session started and finished."""
    assert "done" not in launcher.NEVER_STARTED_STATUSES
    assert launcher.session_has_started({"agent_status": "done"}) is True
    assert launcher.session_has_started({"agent_status": "idle"}) is False
    assert launcher.session_has_started({"agent_status": "unknown"}) is False


def test_redeliver_refuses_a_done_session(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F103: redeliver does not send into a session that already finished."""
    unit, recorded, pane_writes, _guard_calls = _prepare_redeliver_real_send(
        launcher,
        monkeypatch,
        owned=True,
        pane_dumps=[_claude_pane("❯ ")],
        agent_status="done",
    )
    launcher.redeliver(unit)
    assert [c for c in recorded if c[:3] == ["herdr", "agent", "prompt"]] == []
    assert pane_writes == []
    assert unit.status == launcher.PROMPT_UNDELIVERED
    assert "the session was done" in unit.note


def test_redeliver_refuses_receipt_missing_required_keys(launcher: ModuleType) -> None:
    """Issue 1002 F112: documented receipt keys are enforced."""
    unit = launcher.LaunchRequest(name="worker", vendor="claude", task="do it")
    for missing in ("unit_name", "pane", "tab_id", "owned", "agent_name"):
        receipt = _staged_receipt()
        receipt.pop(missing)
        with pytest.raises(launcher.RetryReceiptRefused, match="records no"):
            launcher._adopt_retry_receipt(unit, receipt)


def test_redeliver_refuses_delivered_plus_staged_receipt(launcher: ModuleType) -> None:
    """Issue 1002 F119: a delivered prompt is not retried even when input_box is staged."""
    unit = launcher.LaunchRequest(name="worker", vendor="claude", task="do it")
    receipt = _staged_receipt(prompt_delivered=True)
    with pytest.raises(launcher.RetryReceiptRefused, match="already delivered"):
        launcher._adopt_retry_receipt(unit, receipt)


def test_parse_opencode_variants_ignores_prose_bullets(launcher: ModuleType) -> None:
    """Issue 1002 F113: markdown bullets from agent prose are not picker options."""
    pane = "- shipped\n* broken\n> high\n> low"
    assert launcher.parse_opencode_variants(pane) == ["high", "low"]


def test_failed_or_timed_out_composer_read_refuses_the_write(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F114: a missing observation does not authorize the write."""
    recorded: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="worker", vendor="claude", launch_receipt={"owned": False})
    monkeypatch.setattr(
        launcher,
        "pane_input_inspection",
        lambda *_a, **_k: launcher.ComposerInspection(launcher.ComposerState.READ_TIMEOUT),
    )
    with pytest.raises(SystemExit, match="input box read_timeout"):
        launcher.PaneWriter(unit, "w1:p1", wrote_before=True).write("hello")
    assert [
        c for c in recorded if c[:3] in (["herdr", "pane", "run"], ["herdr", "agent", "prompt"])
    ] == []


def test_opencode_echo_of_typed_token_is_not_session_confirmation(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F115: the launcher's own echo of the typed token is not session proof."""
    monkeypatch.setattr(launcher, "read_pane", lambda *_a, **_k: "> high\nhigh\n")
    unit = launcher.LaunchRequest(name="oc", vendor="opencode", launch_receipt={})
    assert launcher.confirm_opencode_variant_selected(unit, "w80:p9", "high") == (
        "picker_menu_only"
    )


def test_workspace_id_for_name_bounds_the_herdr_list(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F116: workspace list carries a timeout."""
    seen: list[object] = []

    def fake_run(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        seen.append(k.get("timeout"))
        payload: dict[str, object] = {"result": {"workspaces": []}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(launcher, "run", fake_run)
    launcher.workspace_id_for_name("ops")
    assert seen == [20]


def test_account_label_is_read_from_the_statusline_tail(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F117: body text cannot override the statusline tail."""
    monkeypatch.setenv("USER", "operator")
    pane = "operator [personal]: agent output\n" + ("line\n" * 8) + "operator [company]:"

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, pane, "")

    monkeypatch.setattr(launcher, "run", fake_run)
    assert launcher.pane_account_label("w1:p1") == "company"


def test_inspect_window_has_both_row_and_byte_bounds(launcher: ModuleType) -> None:
    """Issue 1002 F130: row cap and byte cap both trim from the head on a row boundary."""
    staged_tail = _claude_pane("❯ surviving draft")
    short_rows = "\n".join(f"row {i}" for i in range(4201)) + "\n" + staged_tail
    window = launcher.tail_inspect_window(short_rows)
    assert window.count("\n") <= launcher.PANE_INSPECT_MAX_LINES
    result = launcher.inspect_composer(window, vendor="claude")
    assert result.state is launcher.ComposerState.STAGED
    assert result.text == "surviving draft"
    wide = "\n".join("x" * 2000 for _ in range(80))
    wide_window = launcher.tail_inspect_window(wide)
    assert len(wide_window) <= launcher.PANE_INSPECT_MAX_CHARS


def test_empty_input_box_clears_stale_text_chars(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F131: empty overwrites drop a stale character count."""
    unit = launcher.LaunchRequest(
        name="worker",
        vendor="claude",
        launch_receipt={"input_box": "staged", "input_box_text_chars": 12},
    )
    monkeypatch.setattr(
        launcher,
        "pane_input_inspection",
        lambda *_a, **_k: launcher.ComposerInspection(launcher.ComposerState.EMPTY, ""),
    )
    launcher.guard_pane_before_write(unit, "w1:p1")
    assert unit.launch_receipt["input_box"] == "empty"
    assert "input_box_text_chars" not in unit.launch_receipt


def test_picker_token_is_redacted_from_notes_and_stops(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F132: notes and stops do not interpolate scraped option tokens."""
    monkeypatch.setattr(launcher, "read_pane", lambda *_a, **_k: "> high\n> low\n")
    unit = launcher.LaunchRequest(name="oc", vendor="opencode", launch_receipt={})
    seen = launcher.confirm_opencode_variant_selected(unit, "w80:p9", "high")
    assert seen == "picker_menu_only"
    unit.launch_receipt["variant_confirmed_from"] = seen
    if seen == "session":
        launcher.append_unit_note(unit, "variant verified")
    assert "high" not in unit.note
    with pytest.raises(SystemExit) as stop:
        launcher.confirm_opencode_variant_selected(unit, "w80:p9", "turbo")
    assert "turbo" not in str(stop.value)


def test_pane_text_refuses_symlink_escape(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F133: a symlink under the task dir cannot escape containment."""
    tasks = tmp_path / ".orchestrate" / "tasks"
    tasks.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    (tasks / "worker.md").symlink_to(outside)
    monkeypatch.setattr(launcher, "TASK_DIR", tasks)
    unit = launcher.LaunchRequest(name="worker", vendor="codex", worktree=str(tmp_path))
    long_text = "x" * (launcher.PANE_TYPING_LIMIT + 1)
    with pytest.raises(SystemExit, match="resolves outside"):
        launcher.pane_text(unit, long_text)
    assert not outside.exists()


def test_pane_writer_has_no_raw_or_type_methods(launcher: ModuleType) -> None:
    """Issue 1002 F104: the doors are not methods a caller can open."""
    assert not hasattr(launcher.PaneWriter, "_raw")
    assert not hasattr(launcher.PaneWriter, "_type")
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    writer = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PaneWriter"
    )
    methods = {node.name for node in writer.body if isinstance(node, ast.FunctionDef)}
    assert methods.isdisjoint({"_raw", "_type"})


def test_pane_writer_nonzero_typing_is_a_named_stop(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue 1002 F134: pane typing returning nonzero is a named stop."""

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["herdr", "pane", "run"]:
            return subprocess.CompletedProcess(cmd, 1, "", "typed refused")
        return subprocess.CompletedProcess(cmd, 1, "", "not ready")

    monkeypatch.setattr(launcher, "run", fake_run)
    unit = launcher.LaunchRequest(name="worker", vendor="qwen", launch_receipt={"owned": True})
    with pytest.raises(SystemExit, match="command failed \\(1\\) while typing"):
        launcher.PaneWriter(unit, "w1:p1", wrote_before=False).write("hello")


def test_pane_writer_prompt_refused_without_pane(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        launcher,
        "run",
        lambda cmd, **_k: subprocess.CompletedProcess(cmd, 1, "", "not ready"),
    )
    unit = launcher.LaunchRequest(name="worker", vendor="claude", launch_receipt={"owned": True})
    with pytest.raises(SystemExit, match="no pane to fall back to"):
        launcher.PaneWriter(unit, None, wrote_before=False).write("hello")


def test_pane_writer_pane_door_requires_a_pane(launcher: ModuleType) -> None:
    unit = launcher.LaunchRequest(name="worker", vendor="opencode", launch_receipt={"owned": True})
    with pytest.raises(SystemExit, match="no pane to type into"):
        launcher.PaneWriter(unit, None, wrote_before=False).write("high", door="pane")


def test_pane_writer_unknown_door_is_a_named_stop(launcher: ModuleType) -> None:
    unit = launcher.LaunchRequest(name="worker", vendor="claude", launch_receipt={"owned": True})
    with pytest.raises(SystemExit, match="unknown pane-write door"):
        launcher.PaneWriter(unit, "w1:p1", wrote_before=False).write("hello", door="laser")


def test_launch_without_pane_id_is_a_named_stop(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = {"tab_id": "w80:t1", "agent_name": "worker-2", "reused": False}

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["herdr", "tab", "list"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": {"tabs": []}}), "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), "")

    monkeypatch.setattr(launcher, "run", fake_run)
    monkeypatch.setattr(launcher, "launcher", lambda: "agents")
    monkeypatch.setattr(launcher, "list_tab_ids", lambda *_a, **_k: frozenset())
    unit = launcher.LaunchRequest(name="worker", vendor="claude", worktree="/tmp/wt", task="x")
    with pytest.raises(SystemExit, match="did not return a pane_id"):
        launcher.launch(unit)


class _ForceWriteOffGuard(ast.NodeTransformer):
    """Replace ``writer.write(...)`` inside one function with a raw pane-run door."""

    def __init__(self, function_name: str) -> None:
        self.function_name = function_name
        self.stack: list[str] = []
        self.rewritten = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if (
            self.function_name in self.stack
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "write"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "writer"
        ):
            self.rewritten += 1
            text = node.args[0] if node.args else ast.Constant(value="")
            return ast.Call(
                func=ast.Name(id="run", ctx=ast.Load()),
                args=[
                    ast.List(
                        elts=[
                            ast.Constant(value="herdr"),
                            ast.Constant(value="pane"),
                            ast.Constant(value="run"),
                            ast.Constant(value="w1:p1"),
                            text,
                        ],
                        ctx=ast.Load(),
                    )
                ],
                keywords=[],
            )
        return node


def test_forcing_the_guard_off_at_each_write_site_is_observed() -> None:
    """Issue 1002 F120: the named per-site mutation run is a committed test.

    The Orchestrate write site is not in this package, so the enumeration here
    is launcher.py only.
    """
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    writer_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PaneWriter"
    )
    writer_span = (writer_class.lineno, writer_class.end_lineno or writer_class.lineno)
    for filename, func_name, _label in PANE_WRITE_SITES:
        assert filename == "launcher.py"
        rewriter = _ForceWriteOffGuard(func_name)
        mutated = rewriter.visit(ast.parse(LAUNCHER.read_text(encoding="utf-8")))
        ast.fix_missing_locations(mutated)
        assert rewriter.rewritten >= 1, (filename, func_name)
        strays = [
            (line, fn)
            for line, fn in _raw_door_calls(mutated)
            if not (writer_span[0] <= line <= writer_span[1])
        ]
        assert strays, f"mutation of {filename}:{func_name} was not observed"


@pytest.mark.parametrize(
    "snippet",
    [
        "import subprocess\nsubprocess.run(['herdr','pane','run','p','t'])",
        "argv=['herdr','pane','run','p','t']; run(argv)",
        "run(('herdr','pane','run','p','t'))",
        "run(['herdr']+['pane','run','p','t'])",
        "HERDR='herdr'\nrun([HERDR,'pane','run','p','t'])",
        "run([f'herdr','pane','run','p','t'])",
        "run(args=['herdr','pane','run','p','t'])",
        "_run=run\n_run(['herdr','pane','run','p','t'])",
        "writer._raw('t', door='pane')",
        "if not session_owned(unit):\n    guard_pane_before_write(unit, pane)",
        "guard_pane_before_write(unit, pane) if not session_owned(unit) else None",
        "w.write('t')",
    ],
)
def test_structural_detector_kills_enumerated_evasion_shapes(snippet: str) -> None:
    """Issue 1002 F121: the production detector reports every enumerated catchable shape."""
    tree = ast.parse(snippet)
    assert _raw_door_calls(tree), snippet
