"""Issue #223: reviewer recipes for Grok and Muse, admitted only on a live probe, and a ceiling.

Runs as ``python3 -m pytest plugins/agent-launcher/tests/test_launcher_reviewer.py`` with no
extra options. The probe records under ``fixtures/reviewer-probe/`` were written by
``launcher.py reviewer-probe --record`` against the real vendors; the tests here keep the recipe
tables, the admissions and the journal in agreement with them.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
LAUNCHER = (
    REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "scripts" / "launcher.py"
)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reviewer-probe"
LEARNINGS = REPO / "docs" / "engineering-journal" / "LEARNINGS.md"
SAGA_PROMPT = REPO / "plugins" / "saga" / "references" / "targeted-reviewer-prompt.md"
SAGA_SCHEMA = REPO / "plugins" / "saga" / "references" / "targeted-reviewer-answer.schema.json"
CLAUDE_ANSWER = json.dumps({"result": json.dumps({"findings": []}), "is_error": False})
MACH_O = b"\xcf\xfa\xed\xfe"


def _load() -> ModuleType:
    name = "_agent_launcher_reviewer"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    return _load()


def _records() -> list[dict[str, Any]]:
    found = []
    for path in sorted(FIXTURES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema") == "reviewer_probe_record.v1":
            found.append(data)
    return found


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def reviewed_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


class FakeSession:
    """Stands in for the vendor session and records what it was given."""

    def __init__(self, stdout: str, code: int = 0) -> None:
        self.stdout, self.code = stdout, code
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        self.calls.append({"argv": argv, "stdin": stdin, "cwd": cwd, "env": dict(env)})
        return subprocess.CompletedProcess(argv, self.code, self.stdout, "")


def _request(launcher: ModuleType, repo: Path, head: str, tmp_path: Path, **over: Any) -> Any:
    packet = tmp_path / "packet"
    packet.mkdir(parents=True, exist_ok=True)
    values: dict[str, Any] = {
        "vendor": "claude", "model": "opus", "effort": "high", "repo": repo, "head": head,
        "packet": packet, "prompt": SAGA_PROMPT, "schema": SAGA_SCHEMA, "out": tmp_path / "out",
        "work_root": tmp_path / "reviews",
    }
    values.update(over)
    return launcher.ReviewerRequest(**values)


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {"HOME": str(home), "PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", **extra}


def _passing_record(launcher: ModuleType, vendor: str, platform: str, **over: Any) -> dict:
    record: dict[str, Any] = {
        "schema": launcher.REVIEWER_PROBE_RECORD_SCHEMA,
        "vendor": vendor,
        "platform": platform,
        "date": "2026-10-11",
        "model": "m",
        "effort": None,
        "executable": {"name": "vendor-bin", "sha256": "a" * 64, "version": "vendor 1.0"},
        "session_exit": 0,
        "sign_in": "subscription",
        "verdicts": [
            {"denial": name, "held": True, "detail": "x"}
            for name in launcher.REVIEWER_PROBE_CHECKS
        ],
    }
    record.update(over)
    return record


# --------------------------------------------------------------------------- Claude's ceiling


def test_ceiling_a_claude_launch_passes_and_records_it(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(CLAUDE_ANSWER)
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path, max_budget_usd="5"),
        env=_env(tmp_path), session=session,
    )
    assert code == 0 and result["ceiling_usd"] == "5"
    assert session.calls[0]["argv"][-2:] == ["--max-budget-usd", "5"]
    written = json.loads((tmp_path / "out" / "result.json").read_text())
    assert written["ceiling_usd"] == "5" and written["executable"] is None


def test_ceiling_a_claude_launch_without_one_is_refused_before_anything_exists(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(CLAUDE_ANSWER)
    with pytest.raises(launcher.ReviewerRefused, match="--max-budget-usd"):
        launcher.reviewer_launch(_request(launcher, repo, head, tmp_path), env=_env(tmp_path),
                                 session=session)
    assert session.calls == []
    assert not (tmp_path / "reviews").exists() and not (tmp_path / "out").exists()


@pytest.mark.parametrize("amount", ["0", "0.00", "-1", "abc", "1e3", "nan", "1.234", "", " 5"])
def test_ceiling_an_amount_that_is_not_a_positive_dollar_figure_is_refused(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, amount: str
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(CLAUDE_ANSWER)
    with pytest.raises(launcher.ReviewerRefused, match="--max-budget-usd"):
        launcher.reviewer_launch(
            _request(launcher, repo, head, tmp_path, max_budget_usd=amount),
            env=_env(tmp_path), session=session,
        )
    assert session.calls == [] and not (tmp_path / "reviews").exists()


@pytest.mark.parametrize("amount", ["5", "0.5", "12.25", "100"])
def test_ceiling_a_positive_amount_is_accepted(launcher: ModuleType, amount: str) -> None:
    assert launcher.reviewer_ceiling_problem(amount) is None


def test_ceiling_the_review_command_refuses_a_claude_launch_without_one(
    reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    packet = tmp_path / "packet"
    packet.mkdir()
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER), "review", "--vendor", "claude", "--model", "opus",
         "--effort", "high", "--repo", str(repo), "--head", head, "--packet", str(packet),
         "--prompt", str(SAGA_PROMPT), "--schema", str(SAGA_SCHEMA), "--out", str(tmp_path / "o")],
        capture_output=True, text=True, check=False, env={**os.environ, "HOME": str(tmp_path)},
    )
    assert proc.returncode == 2
    assert "needs a spending ceiling" in proc.stderr and "--max-budget-usd" in proc.stderr
    assert not (tmp_path / "o").exists()


def test_ceiling_a_vendor_without_one_refuses_the_flag(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, head = reviewed_repo
    no_ceiling = launcher.dataclasses.replace(launcher.REVIEWER_CLAUDE_RECIPE, takes_ceiling=False)
    monkeypatch.setitem(launcher.REVIEWER_RECIPES, "nobudget", no_ceiling)
    session = FakeSession(CLAUDE_ANSWER)
    with pytest.raises(launcher.ReviewerRefused, match="nobudget has no dollar ceiling"):
        launcher.reviewer_launch(
            _request(launcher, repo, head, tmp_path, vendor="nobudget", max_budget_usd="5"),
            env=_env(tmp_path), session=session,
        )
    assert session.calls == []


def test_ceiling_claude_argv_cannot_be_built_without_one(launcher: ModuleType) -> None:
    with pytest.raises(launcher.ReviewerRefused, match="spending ceiling"):
        launcher.reviewer_claude_argv("opus", "high", Path("settings.json"))


def test_ceiling_the_probe_passes_its_fixed_ceiling_or_the_override(
    launcher: ModuleType, tmp_path: Path
) -> None:
    for override, expected in ((None, launcher.REVIEWER_PROBE_CEILING_USD), ("0.25", "0.25")):
        session = FakeSession(CLAUDE_ANSWER)
        launcher.reviewer_probe(
            "claude", "haiku", env={"HOME": str(tmp_path)}, session=session,
            work_root=tmp_path / "reviews", reachable=lambda env: 0, max_budget_usd=override,
        )
        argv = session.calls[0]["argv"]
        assert argv[argv.index("--max-budget-usd") + 1] == expected
    assert launcher.REVIEWER_PROBE_CEILING_USD == "1.00"


# --------------------------------------------------------------------------- Claude unchanged


@pytest.mark.parametrize("effort", ["high", None])
def test_unchanged_claude_argv_minus_the_ceiling_is_the_argv_before_issue_223(
    launcher: ModuleType, effort: str | None
) -> None:
    settings = Path("/work/settings.json")
    argv = launcher.reviewer_claude_argv("opus", effort, settings, max_budget_usd="7.50")
    assert argv[-2:] == ["--max-budget-usd", "7.50"]
    before = ["claude", "-p", "--model", "opus"] + (["--effort", effort] if effort else []) + [
        "--permission-mode", "dontAsk", "--settings", str(settings),
        "--output-format", "json", "--no-session-persistence",
    ]
    assert argv[:-2] == before


def test_unchanged_claude_recipe_keeps_its_functions_names_and_sign_in_rules(
    launcher: ModuleType,
) -> None:
    claude = launcher.REVIEWER_RECIPES["claude"]
    assert claude is launcher.REVIEWER_CLAUDE_RECIPE
    assert claude.binary == "claude" and claude.prompt_via == "stdin"
    assert claude.settings is launcher.reviewer_claude_settings
    assert claude.parse is launcher.reviewer_parse_claude_result
    assert claude.config_sources is launcher.reviewer_claude_config_sources
    assert claude.widening is launcher.reviewer_claude_widening
    assert claude.api_key_variables == launcher.REVIEWER_API_KEY_VARIABLES
    assert claude.api_key_prefixes == launcher.REVIEWER_API_KEY_PREFIXES
    assert claude.untrusted_dirs == (".claude",) and claude.untrusted_files == (".mcp.json",)
    assert claude.instruction_names == ("CLAUDE.md", "CLAUDE.local.md")
    assert claude.platforms is None and claude.executable is None
    assert claude.probe_model == "haiku"
    # Issue #225 is the one change: commands run through the start-up-export filter.
    assert claude.materialize is launcher.reviewer_claude_materialize


def test_unchanged_claude_session_environment_and_withholding(
    launcher: ModuleType, tmp_path: Path
) -> None:
    env = {"ANTHROPIC_API_KEY": "inert", "CLAUDE_CODE_USE_BEDROCK": "1", "XAI_API_KEY": "inert",
           "META_API_KEY": "inert", "HOME": "/home/example"}
    assert launcher.reviewer_session_environment(env) == {
        "XAI_API_KEY": "inert", "META_API_KEY": "inert", "HOME": "/home/example",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    copy = tmp_path / "copy"
    for rel in (".claude/settings.json", ".mcp.json", ".grok/sandbox.toml", ".muse/x", "a.py"):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        (copy / rel).write_text("x")
    withheld = launcher.reviewer_withhold_untrusted(copy)
    assert sorted(w.split(" ")[0] for w in withheld) == [".claude", ".mcp.json"]
    assert (copy / ".grok" / "sandbox.toml").exists() and (copy / ".muse" / "x").exists()


# ------------------------------------------------------------- start-up exports (issue #225)

PREFIX = "CLAUDE_CODE_SHELL_PREFIX"
NOT_ROOT = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads a file with no permissions"
)


def _run_like_claude(command: str, env: dict[str, str], cwd: Path) -> str:
    """Run *command* as Claude Code 2.1.296 runs a Bash command (measured for issue #225).

    A bash that reads its start-up files runs ``'<prefix>' '<command>'`` when
    ``CLAUDE_CODE_SHELL_PREFIX`` is set, and the command itself when it is not.
    """
    prefix = env.get(PREFIX)
    line = f"{shlex.quote(prefix)} {shlex.quote(command)}" if prefix else command
    proc = subprocess.run(["bash", "-c", line], cwd=cwd, env=env, capture_output=True, text=True,
                          check=False)
    return proc.stdout


def _sandbox_denies(sentinel: Path) -> None:
    """Stand in for the sandbox's ``denyRead`` of the sentinel."""
    sentinel.chmod(0)


def _claude_shell(launcher: ModuleType, tmp_path: Path) -> tuple[Path, dict[str, Any], dict]:
    copy = tmp_path / "launch" / "copy"
    copy.mkdir(parents=True)
    settings = launcher.reviewer_claude_settings(
        copy, tmp_path / "packet", {"HOME": str(tmp_path / "home")}, toolchain=[]
    )
    _, extra = launcher.reviewer_claude_materialize(settings, copy.parent, copy)
    return copy, settings, extra


def _startup_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    startup = tmp_path / "startup"
    startup.mkdir(exist_ok=True)
    (startup / "bash_env").write_text("export REVIEWER_TEST_STARTUP=reviewer-test-startup-inert\n")
    return {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"),
            "BASH_ENV": str(startup / "bash_env"), **extra}


@NOT_ROOT
def test_startup_an_export_reaches_a_command_without_the_prefix_and_not_with_it(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    show = 'echo "${REVIEWER_TEST_STARTUP-unset}"'
    env = _startup_env(tmp_path)
    assert _run_like_claude(show, env, copy).strip() == "reviewer-test-startup-inert"
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    assert _run_like_claude(show, {**env, **extra}, copy).strip() == "unset"


@NOT_ROOT
def test_startup_a_sandboxed_command_keeps_the_allow_list_and_the_toolchain_runs(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    env = _startup_env(tmp_path, LANG="C.UTF-8", TZ="UTC", GIT_CONFIG_GLOBAL=os.devnull,
                       REVIEWER_TEST_PLAIN="inert", REVIEWER_TEST_TOKEN="inert", **extra)
    out = _run_like_claude(
        "env | cut -d= -f1 | sort; python3 -c 'print(1 + 2)'; git --version > /dev/null && "
        "echo git-ok", env, copy,
    ).split()
    names = {n for n in out if n.isupper() or n == "_"} - {"PWD", "SHLVL", "OLDPWD", "_"}
    # Only allow-list names reach it (bash may set SHELL and TERM itself), and each one set does.
    # TEMP and TMP are the prefix's own, both naming the reviewer's temp folder.
    assert names <= set(launcher.REVIEWER_ENVIRONMENT_ALLOWED) | {"TEMP", "TMP"}
    assert {n for n in launcher.REVIEWER_ENVIRONMENT_ALLOWED if n in env} <= names
    assert "3" in out and "git-ok" in out


@NOT_ROOT
def test_startup_a_missing_sentinel_still_filters(launcher: ModuleType, tmp_path: Path) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    launcher.reviewer_claude_shell_paths(copy)[1].unlink()
    env = _startup_env(tmp_path, REVIEWER_TEST_PLAIN="inert", **extra)
    out = _run_like_claude('echo "${REVIEWER_TEST_STARTUP-unset} ${REVIEWER_TEST_PLAIN-unset}"',
                           env, copy)
    assert out.split() == ["unset", "unset"]


def test_startup_outside_the_sandbox_a_hook_runs_with_its_environment_unchanged(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    env = _startup_env(tmp_path, REVIEWER_TEST_PLAIN="inert", **extra)
    out = _run_like_claude('echo "${REVIEWER_TEST_PLAIN-unset}"', env, copy)
    assert out.strip() == "inert"


def test_startup_the_settings_name_the_prefix_and_deny_its_sentinel(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, settings, extra = _claude_shell(launcher, tmp_path)
    prefix, sentinel = launcher.reviewer_claude_shell_paths(copy)
    assert settings["env"] == {PREFIX: str(prefix)} and extra == {PREFIX: str(prefix)}
    filesystem = settings["sandbox"]["filesystem"]
    assert str(prefix.parent) in filesystem["allowRead"] and str(sentinel) in filesystem["denyRead"]
    for path in (prefix, sentinel):
        assert path.is_file() and not path.is_relative_to(copy.resolve())
        assert not any(path.is_relative_to(Path(a)) for a in filesystem["allowRead"]
                       if path == sentinel)
    assert os.access(prefix, os.X_OK)


def test_startup_a_settings_file_that_sets_the_shell_prefix_refuses(
    launcher: ModuleType, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"env": {PREFIX: "/bin/echo"}}))
    assert launcher.reviewer_claude_widening({"HOME": str(home)}) == [
        f"settings.json sets env.{PREFIX}"
    ]


def test_startup_a_claude_launch_runs_its_commands_through_the_prefix(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(CLAUDE_ANSWER)
    launcher.reviewer_launch(_request(launcher, repo, head, tmp_path, max_budget_usd="5"),
                             env=_env(tmp_path), session=session)
    call = session.calls[0]
    prefix = Path(call["env"][PREFIX])
    assert prefix == launcher.reviewer_claude_shell_paths(call["cwd"])[0] and prefix.is_file()
    settings = Path(call["argv"][call["argv"].index("--settings") + 1])
    assert json.loads(settings.read_text())["env"] == {PREFIX: str(prefix)}


# A writable temp folder: the replay gives each test its own TMPDIR, so the reviewer gets one too.


def test_tmpdir_the_settings_allow_writes_to_a_temp_folder_beside_the_copy_and_deny_the_roots(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, settings, _ = _claude_shell(launcher, tmp_path)
    temp = launcher.reviewer_claude_temp_dir(copy)
    filesystem = settings["sandbox"]["filesystem"]
    assert temp.parent == copy.resolve().parent and temp.is_dir()
    assert not temp.is_relative_to(copy.resolve()) and not copy.resolve().is_relative_to(temp)
    assert filesystem["allowWrite"] == [str(temp)]
    assert filesystem["allowRead"][-1] == str(temp)
    # The system temp roots stay denied. The folder lives in the launch root, which
    # reviewer_work_root keeps outside every one of them (this test's tmp_path may not be).
    assert filesystem["denyWrite"] == list(launcher.reviewer_temp_roots())
    for root in launcher.reviewer_temp_roots():
        with pytest.raises(launcher.ReviewerRefused):
            launcher.reviewer_work_root({"XDG_CACHE_HOME": f"{root}/cache"})


# The temp folder doubles as the reviewer's draft folder: file tools may write there, and the
# launch message names it, so a forgotten draft cannot reach the scratch-change comparison.


def test_draft_folder_the_file_tools_may_write_in_the_temp_folder_and_nowhere_new(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, settings, _ = _claude_shell(launcher, tmp_path)
    temp = launcher.reviewer_claude_temp_dir(copy)
    allow = settings["permissions"]["allow"]
    # Absolute-path form: a leading "//", then the folder, as the packet's Read rule is written.
    assert f"Edit(/{temp}/**)" in allow and f"Edit(/{temp}/**)".startswith("Edit(//")
    edits = [rule for rule in allow if rule.startswith(("Edit(", "Write("))]
    assert edits == ["Edit(./**)", f"Edit(/{temp}/**)"]
    assert "Bash" in allow and any(rule.startswith("Read(//") for rule in allow)
    assert settings["sandbox"]["filesystem"]["allowWrite"] == [str(temp)]


def _launch_message(launcher: ModuleType, tmp_path: Path, **kwargs: Any) -> str:
    copy = tmp_path / "launch" / "copy"
    copy.mkdir(parents=True, exist_ok=True)
    return launcher.reviewer_launch_message(
        "wrapper", "prompt", tmp_path / "packet", copy, 5, **kwargs
    )


def test_draft_folder_the_launch_message_names_it_when_given(
    launcher: ModuleType, tmp_path: Path
) -> None:
    folder = tmp_path / "launch" / "tmp"
    message = _launch_message(launcher, tmp_path, draft_folder=folder)
    line = (
        "- Your draft folder, outside the scratch copy and never compared: "
        f"`{folder.resolve()}`\n"
    )
    assert message.count(line) == 1
    section = message.split("# This review\n\n", 1)[1]
    assert section.index("The scratch copy") < section.index(line) < section.index("final message")


def test_draft_folder_the_launch_message_omits_the_line_without_one(
    launcher: ModuleType, tmp_path: Path
) -> None:
    message = _launch_message(launcher, tmp_path)
    assert "draft folder" not in message.split("# This review", 1)[1]
    assert message == _launch_message(launcher, tmp_path, draft_folder=None)


def test_draft_folder_a_claude_launch_hands_the_session_its_temp_folder(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(CLAUDE_ANSWER)
    launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path, max_budget_usd="5"), env=_env(tmp_path),
        session=session,
    )
    call = session.calls[0]
    temp = launcher.reviewer_claude_temp_dir(call["cwd"])
    assert f"- Your draft folder, outside the scratch copy and never compared: `{temp}`\n" in (
        call["stdin"]
    )


def test_draft_folder_a_candidate_vendor_launch_passes_none(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, head = reviewed_repo
    binary = _fake_vendor(tmp_path)
    monkeypatch.setattr(launcher, "_reviewer_vendor_version", lambda path, env: "vendor 1.0")
    candidate = launcher.dataclasses.replace(
        launcher.REVIEWER_CANDIDATES["grok"], executable=lambda env: binary, widening=None,
    )
    assert candidate.temp_dir is None
    monkeypatch.setitem(launcher.REVIEWER_CANDIDATES, "synthetic", candidate)
    record = _passing_record(
        launcher, "synthetic", sys.platform,
        executable={"name": binary.name, "sha256": launcher._reviewer_sha256(binary),
                    "version": "vendor 1.0"},
    )
    monkeypatch.setitem(launcher.REVIEWER_ADMISSIONS, ("synthetic", sys.platform), record)
    monkeypatch.setitem(
        launcher.REVIEWER_RECIPES, "synthetic", launcher._reviewer_admitted()["synthetic"]
    )
    drafts: list[Path | None] = []
    real = launcher.reviewer_launch_message

    def spy(*args: Any, **kwargs: Any) -> str:
        # The key itself, so a call site that never passes the argument fails here.
        drafts.append(kwargs["draft_folder"])
        return real(*args, **kwargs)

    monkeypatch.setattr(launcher, "reviewer_launch_message", spy)
    grok_output = json.loads((FIXTURES / "grok-session-output.json").read_text())
    session = FakeSession(json.dumps({**grok_output, "text": '{"findings": []}'}))
    launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path, vendor="synthetic", model="grok-4.7"),
        env=_env(tmp_path), session=session,
    )
    assert drafts == [None]


def test_draft_folder_saga_s_prompt_sends_the_draft_there_and_keeps_the_deletion_warning() -> None:
    text = SAGA_PROMPT.read_text(encoding="utf-8")
    assert "draft folder" in text and "/Users/operator/drafts/answer-draft.json" in text
    # The example commands use the draft folder; the scratch copy is named only as the fallback.
    assert '--answer "/Users/operator/scratch-copy' not in text
    assert '--output "/Users/operator/scratch-copy' not in text
    assert "names no draft folder" in text
    assert "A leftover\ntemporary file is a changed file in the scratch copy and refuses the answer." in text


def test_tmpdir_the_temp_folder_is_private_to_the_reviewer(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, _ = _claude_shell(launcher, tmp_path)
    assert launcher.reviewer_claude_temp_dir(copy).stat().st_mode & 0o777 == 0o700


@NOT_ROOT
def test_tmpdir_a_sandboxed_command_sees_the_temp_folder_whatever_the_sandbox_set(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    env = _startup_env(tmp_path, TMPDIR="/tmp/sandbox-chosen", **extra)
    out = _run_like_claude('echo "$TMPDIR"; touch "$TMPDIR/probe" && echo wrote', env, copy)
    temp = launcher.reviewer_claude_temp_dir(copy)
    assert out.split() == [str(temp), "wrote"] and (temp / "probe").is_file()


@NOT_ROOT
def test_tmpdir_a_path_with_spaces_and_quotes_still_reaches_the_command(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = tmp_path / "it's a launch" / "copy"
    copy.mkdir(parents=True)
    settings = launcher.reviewer_claude_settings(copy, tmp_path / "packet", {}, toolchain=[])
    _, extra = launcher.reviewer_claude_materialize(settings, copy.parent, copy)
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    out = _run_like_claude('printf %s "$TMPDIR"', _startup_env(tmp_path, **extra), copy)
    assert out == str(launcher.reviewer_claude_temp_dir(copy))


def test_tmpdir_outside_the_sandbox_a_hook_keeps_its_own_temp_directory(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    env = _startup_env(tmp_path, TMPDIR="/tmp/hook-chosen", **extra)
    assert _run_like_claude('echo "$TMPDIR"', env, copy).strip() == "/tmp/hook-chosen"


def test_tmpdir_a_claude_launch_writes_there_and_the_scratch_changes_do_not_show_it(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    seen: dict[str, Any] = {}

    def session(argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        temp = launcher.reviewer_claude_temp_dir(cwd)
        (temp / "scratch-file").write_text("temporary\n")
        seen["temp"] = temp
        settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
        seen["write"] = settings["sandbox"]["filesystem"]["allowWrite"]
        return subprocess.CompletedProcess(argv, 0, CLAUDE_ANSWER, "")

    result, _ = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path, max_budget_usd="5"), env=_env(tmp_path),
        session=session,
    )
    assert seen["write"] == [str(seen["temp"])] and not seen["temp"].is_relative_to(
        Path(result["scratch"]["path"])
    )
    assert result["scratch"]["changes"] == {
        "added": [], "modified": [], "deleted": [], "links": []
    }


def _claude_sandbox_temp(tmp_path: Path) -> Path:
    """Stand in for Claude's sandbox temp folder: it exists, and the reviewer may not write it."""
    folder = tmp_path / "claude-sandbox-temp"
    folder.mkdir(mode=0o500)
    return folder


def _as_claude_2_1_311(command: str, sandbox_temp: Path) -> str:
    """The command string Claude Code 2.1.308 to 2.1.311 hands the prefix for a sandboxed
    command: it exports its own sandbox temp folder as TMPDIR before running the command
    (read from the 2.1.311 executable and seen through a logging prefix, 2026-10-26)."""
    return f"export TMPDIR={shlex.quote(str(sandbox_temp))} && eval {shlex.quote(command)}"


GETTEMPDIR = f"{shlex.quote(sys.executable)} -c 'import tempfile; print(tempfile.gettempdir())'"


@NOT_ROOT
def test_tmpdir_every_tool_sees_the_reviewer_s_folder_after_claude_exports_its_own(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    sandbox_temp = _claude_sandbox_temp(tmp_path)
    env = _startup_env(tmp_path, **extra)
    temp = launcher.reviewer_claude_temp_dir(copy)
    shown = _run_like_claude(
        _as_claude_2_1_311(f'echo "$TMPDIR"; {GETTEMPDIR}; sh -c \'echo "$TMPDIR"\'',
                           sandbox_temp), env, copy
    ).split()
    # The DEBUG trap puts the reviewer's folder back after Claude's export, for Python and for
    # any child that reads TMPDIR alone.
    assert shown == [str(temp)] * 3
    node = shutil.which("node")
    if node:
        script = f"{shlex.quote(node)} -e 'console.log(require(\"os\").tmpdir())'"
        assert _run_like_claude(_as_claude_2_1_311(script, sandbox_temp), env, copy).strip() == (
            str(temp))
    # A command's own TMPDIR=... keeps its value; exit statuses survive the trap.
    kept = _run_like_claude(_as_claude_2_1_311(
        "TMPDIR=/elsewhere sh -c 'echo \"$TMPDIR\"'; false; echo $?; (exit 3); echo $?",
        sandbox_temp), env, copy).split()
    assert kept == ["/elsewhere", "1", "3"]
    # Python's own fallback stays: with TMPDIR unwritable it takes TEMP.
    fallback = _run_like_claude(
        f"TMPDIR={shlex.quote(str(sandbox_temp))} {GETTEMPDIR}", env, copy).strip()
    assert fallback == str(temp)


@NOT_ROOT
@pytest.mark.parametrize("bash", ["/bin/bash", shutil.which("bash") or "/bin/bash"])
def test_tmpdir_the_trap_leaves_dollar_underscore_and_pipestatus_alone(
    launcher: ModuleType, tmp_path: Path, bash: str
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    env = _startup_env(tmp_path, SHELL=bash, **extra)
    temp = launcher.reviewer_claude_temp_dir(copy)
    out = _run_like_claude(_as_claude_2_1_311(
        'mkdir -p made && cd "$_" && basename "$PWD"; (exit 3) | cat; echo "${PIPESTATUS[*]}"; '
        'echo "$TMPDIR"; export TMPDIR=/own; sh -c \'echo "$TMPDIR"\'',
        _claude_sandbox_temp(tmp_path)), env, copy).split()
    # $_ survives (bash 3.2 and later), PIPESTATUS too (any DEBUG trap resets it on bash 3.2,
    # so the trap is gone before the command runs), and the command's own export is kept.
    assert out == ["made", "3", "0", str(temp), "/own"]


def test_tmpdir_the_prefix_s_exit_status_is_the_command_s(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    env = _startup_env(tmp_path, **extra)
    line = f"{shlex.quote(extra[PREFIX])} {shlex.quote('echo ran; exit 7')}"
    proc = subprocess.run(["bash", "-c", line], cwd=copy, env=env, capture_output=True,
                          text=True, check=False)
    assert (proc.returncode, proc.stdout) == (7, "ran\n")


@NOT_ROOT
def test_tmpdir_a_pytest_tmp_path_test_leaves_nothing_in_the_copy(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, _, extra = _claude_shell(launcher, tmp_path)
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    package = copy / "plugins" / "example"
    (package / "tests").mkdir(parents=True)
    manifest = launcher._reviewer_manifest(copy)
    (package / "tests" / "test_repro.py").write_text(
        "def test_writes(tmp_path):\n    (tmp_path / 'registry.json').write_text('{}')\n"
    )
    run = (f"cd plugins/example && {shlex.quote(sys.executable)} -m pytest -q "
           "-p no:cacheprovider tests/test_repro.py > /dev/null; echo $?")
    env = _startup_env(tmp_path, **extra)
    assert _run_like_claude(
        _as_claude_2_1_311(run, _claude_sandbox_temp(tmp_path)), env, copy
    ).strip() == "0"
    assert launcher.reviewer_scratch_changes(copy, manifest) == {
        "added": ["plugins/example/tests/test_repro.py"], "modified": [], "deleted": [],
        "links": [],
    }
    assert any(launcher.reviewer_claude_temp_dir(copy).glob("pytest-of-*/pytest-current"))


def _pytest_tree(launcher: ModuleType, copy: Path, below: str) -> Path:
    """What pytest's ``tmp_path`` leaves when its temp root is *below* in the copy."""
    base = copy / below / "pytest-of-user"
    run = base / "pytest-0"
    (run / "test_x0").mkdir(parents=True)
    (run / "test_x0" / "registry.json").write_text("{}\n")
    (base / "pytest-current").symlink_to(run.resolve())
    (run / "test_xcurrent").symlink_to((run / "test_x0").resolve())
    return base


@pytest.mark.parametrize("below", [".", "plugins/example"])
def test_scratch_pytest_s_tree_and_its_current_links_are_clutter_at_any_depth(
    launcher: ModuleType, tmp_path: Path, below: str
) -> None:
    copy = tmp_path / "copy"
    (copy / "plugins" / "example").mkdir(parents=True)
    manifest = launcher._reviewer_manifest(copy)
    _pytest_tree(launcher, copy, below)
    cache = copy / "plugins" / "example" / "deep" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "mod.cpython-312.pyc").write_bytes(b"\0")
    assert launcher.reviewer_scratch_changes(copy, manifest) == {
        "added": [], "modified": [], "deleted": [], "links": []
    }


def test_scratch_a_link_the_session_makes_is_still_reported_even_in_pytest_s_tree(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    manifest = launcher._reviewer_manifest(copy)
    base = _pytest_tree(launcher, copy, "plugins/example")
    run = base / "pytest-0"
    # Named like pytest's links, but pointing elsewhere: never pytest's.
    (run / "test_ycurrent").symlink_to(tmp_path)
    (run / "test_zcurrent").symlink_to("../../../../secret")
    (run / "test_wcurrent").symlink_to(copy / "test_w0")
    (base / "pytest-1").mkdir()
    (base / "pytest-1" / "notes").symlink_to(run)
    (copy / "pytest-current").symlink_to("pytest-0")
    (copy / "plugins" / "example" / "data").symlink_to("/")
    assert launcher.reviewer_scratch_changes(copy, manifest)["links"] == [
        "plugins/example/data",
        "plugins/example/pytest-of-user/pytest-0/test_wcurrent",
        "plugins/example/pytest-of-user/pytest-0/test_ycurrent",
        "plugins/example/pytest-of-user/pytest-0/test_zcurrent",
        "plugins/example/pytest-of-user/pytest-1/notes",
        "pytest-current",
    ]


@NOT_ROOT
@pytest.mark.parametrize("fixed", [True, False])
def test_startup_the_claude_probe_fails_without_the_prefix_and_passes_with_it(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed: bool
) -> None:
    if not fixed:
        def unfixed_settings(*args: Any, **kwargs: Any) -> dict[str, Any]:
            settings = launcher.reviewer_claude_settings(*args, **kwargs)
            settings.pop("env")
            return settings

        monkeypatch.setitem(launcher.REVIEWER_RECIPES, "claude", launcher.dataclasses.replace(
            launcher.REVIEWER_CLAUDE_RECIPE, settings=unfixed_settings,
            materialize=launcher.reviewer_settings_materialize,
        ))

    def session(argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        # Claude's TMPDIR write succeeds, in the folder the sandbox leaves writable.
        results = {**HONEST, "write_tmpdir": "0"}
        results.pop("startup_variable")
        _write_results(cwd.parent, results)
        tag = re.search(r"reviewer-probe-([0-9a-f]{12})", (cwd / "probe.sh").read_text())
        assert tag is not None
        temp = launcher.reviewer_claude_temp_dir(cwd)
        temp.mkdir(exist_ok=True)  # the unfixed variant skips the step that makes it
        (temp / f"reviewer-probe-{tag.group(1)}").touch()
        if PREFIX in env:
            _sandbox_denies(launcher.reviewer_claude_shell_paths(cwd)[1])
        _run_like_claude('r=probe-results.txt\n' + launcher.REVIEWER_PROBE_STARTUP_LINE, dict(env),
                         cwd)
        return subprocess.CompletedProcess(argv, 0, CLAUDE_ANSWER, "")

    verdicts, code = launcher.reviewer_probe(
        "claude", "haiku", env={"HOME": str(tmp_path), "PATH": os.environ.get("PATH", "")},
        session=session, work_root=tmp_path / "reviews", reachable=lambda env: 0,
    )
    held = {v["denial"]: v["held"] for v in verdicts}
    assert set(held) == set(launcher.REVIEWER_PROBE_CHECKS)
    assert held["startup-variable"] is fixed
    assert (code == 0) is fixed and all(h for name, h in held.items() if name != "startup-variable")


# --------------------------------------------------------------------------- candidates


@pytest.mark.parametrize("vendor", ["grok", "muse"])
def test_candidate_the_probe_may_run_it_but_review_refuses_it(
    launcher: ModuleType, vendor: str
) -> None:
    assert launcher.reviewer_probe_recipe(vendor) is launcher.REVIEWER_CANDIDATES[vendor]
    if vendor not in launcher.REVIEWER_RECIPES:
        with pytest.raises(launcher.ReviewerRefused, match=f"^{vendor} has no reviewer sandbox"):
            launcher.reviewer_recipe(vendor)


@pytest.mark.parametrize("vendor", ["codex", "agy", "opencode"])
def test_candidate_a_vendor_with_neither_is_refused_by_the_probe(
    launcher: ModuleType, vendor: str
) -> None:
    with pytest.raises(launcher.ReviewerRefused, match=f"^{vendor} has no reviewer sandbox"):
        launcher.reviewer_probe_recipe(vendor)


def test_candidate_a_recipe_is_refused_off_the_platforms_it_was_probed_on(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, head = reviewed_repo
    elsewhere = launcher.dataclasses.replace(
        launcher.REVIEWER_CLAUDE_RECIPE, platforms=("not-this-platform",)
    )
    monkeypatch.setitem(launcher.REVIEWER_RECIPES, "elsewhere", elsewhere)
    session = FakeSession(CLAUDE_ANSWER)
    with pytest.raises(launcher.ReviewerRefused, match="passed its probe only on not-this"):
        launcher.reviewer_launch(
            _request(launcher, repo, head, tmp_path, vendor="elsewhere", max_budget_usd="5"),
            env=_env(tmp_path), session=session,
        )
    assert session.calls == [] and not (tmp_path / "reviews").exists()


def test_forbidden_no_recipe_or_candidate_passes_a_flag_its_vendor_forbids(
    launcher: ModuleType, tmp_path: Path
) -> None:
    recipes = {**launcher.REVIEWER_CANDIDATES, **launcher.REVIEWER_RECIPES}
    for vendor, recipe in recipes.items():
        argv = recipe.argv(
            "model", "high", tmp_path / "settings.json",
            max_budget_usd="5" if recipe.takes_ceiling else None,
            executable=tmp_path / "bin" / vendor, prompt_path=tmp_path / "prompt.md",
        )
        forbidden = set(launcher.REVIEWER_FORBIDDEN_FLAGS[vendor])
        assert not forbidden & set(argv), (vendor, forbidden & set(argv))


def test_forbidden_the_table_only_grew_for_grok_and_muse(launcher: ModuleType) -> None:
    table = launcher.REVIEWER_FORBIDDEN_FLAGS
    assert {"--always-approve", "--system-prompt-override", "bypassPermissions", "--trust",
            "off", "devbox"} <= set(table["grok"])
    assert {"--disable-sandbox", "--no-foreign-personal-context", "--disable-reminders",
            "--yolo", "never", "--disable-approval", "--trust-workspace"} <= set(table["muse"])


# --------------------------------------------------------------------------- probe verdicts


@pytest.mark.parametrize(
    ("results", "reach", "held"),
    [
        ({"network": "6"}, (0, 0), True),
        ({"network": "7"}, (0, 0), True),
        ({"network": "56", "network_connect": "403"}, (0, 0), True),
        ({"network": "56", "network_connect": "000"}, (0, 0), False),
        ({"network": "0"}, (0, 0), False),
        ({"network": "28"}, (0, 0), False),
        ({"network": "60"}, (0, 0), False),
        ({"network": "35"}, (0, 0), False),
        ({"network": "126"}, (0, 0), False),
        ({"network": "127"}, (0, 0), False),
        ({"network": "6"}, (6, 0), False),
        ({"network": "7"}, (0, 28), False),
        ({"network": "6"}, None, False),
        ({}, (0, 0), False),
    ],
)
def test_verdict_network_denial_needs_a_reachable_address_and_a_connection_that_never_left(
    launcher: ModuleType, results: dict[str, str], reach: tuple[int, int] | None, held: bool
) -> None:
    ok, detail = launcher.reviewer_network_verdict(results, reach)
    assert ok is held
    if reach is not None and reach != (0, 0):
        assert "inconclusive" in detail


def _write_results(root: Path, results: dict[str, str]) -> None:
    copy = root / "copy"
    copy.mkdir(parents=True, exist_ok=True)
    (copy / "inside-written").write_text("")
    (copy / "probe-results.txt").write_text("".join(f"{k}={v}\n" for k, v in results.items()))


HONEST = {
    "read": "1", "write_outside": "1", "write_inside": "0", "write_tmpdir": "1", "write_tmp": "1",
    "network": "7", "network_connect": "000", "variable": "unset", "read_home": "1",
    "read_packet": "0", "python_test": "0", "git": "0", "plain_variable": "unset",
    "read_vendor_home": "1", "write_vendor_home": "1", "startup_variable": "unset",
    "read_vendor_credential_0": "1", "read_vendor_credential_1": "1",
}


def _verdicts(launcher: ModuleType, tmp_path: Path, results: dict[str, str], **over: Any) -> dict:
    root = tmp_path / "probe"
    _write_results(root, results)
    values: dict[str, Any] = {
        "parsed": {"final": "done", "is_error": False}, "session_exit": 0,
        "reachability": (0, 0), "vendor_write": tmp_path / "vendor" / "w", "credential_count": 2,
    }
    values.update(over)
    verdicts = launcher.reviewer_probe_verdicts(root, tmp_path / "outside", "t", ("reviewer-probe-canary-inert",), "",
                                                **values)
    return {v["denial"]: v["held"] for v in verdicts}


def test_verdict_every_check_holds_on_an_honest_run(launcher: ModuleType, tmp_path: Path) -> None:
    held = _verdicts(launcher, tmp_path, HONEST)
    assert set(held) == set(launcher.REVIEWER_PROBE_CHECKS) and all(held.values())


@pytest.mark.parametrize(
    ("key", "value", "check"),
    [
        ("read_vendor_home", "0", "read-vendor-home"),
        ("write_vendor_home", "0", "write-vendor-home"),
        ("read_vendor_credential_1", "0", "read-vendor-credential"),
        ("startup_variable", "set", "startup-variable"),
    ],
)
def test_verdict_the_vendor_checks_fail_when_the_sandbox_lets_it_through(
    launcher: ModuleType, tmp_path: Path, key: str, value: str, check: str
) -> None:
    held = _verdicts(launcher, tmp_path, {**HONEST, key: value})
    assert held[check] is False


def test_verdict_write_tmpdir_with_a_writable_temp_folder_needs_the_write_to_land_there(
    launcher: ModuleType, tmp_path: Path
) -> None:
    temp = tmp_path / "temp-folder"
    temp.mkdir()
    allowed = {**HONEST, "write_tmpdir": "0"}
    assert _verdicts(launcher, tmp_path, allowed, temp_dir=temp)["write-tmpdir"] is False
    (temp / "reviewer-probe-t").touch()
    held = _verdicts(launcher, tmp_path, allowed, temp_dir=temp)
    assert held["write-tmpdir"] is True and held["write-tmp"] is True
    # A denied write is no longer the expected result, and /tmp must still be denied.
    assert _verdicts(launcher, tmp_path, HONEST, temp_dir=temp)["write-tmpdir"] is False
    assert _verdicts(launcher, tmp_path, {**allowed, "write_tmp": "0"}, temp_dir=temp)[
        "write-tmp"
    ] is False


def test_verdict_write_tmpdir_without_a_temp_folder_still_needs_a_denial(
    launcher: ModuleType, tmp_path: Path
) -> None:
    assert _verdicts(launcher, tmp_path, {**HONEST, "write_tmpdir": "0"})["write-tmpdir"] is False


def test_verdict_only_the_claude_recipe_leaves_a_temp_folder_writable(launcher: ModuleType) -> None:
    assert launcher.REVIEWER_CLAUDE_RECIPE.temp_dir is launcher.reviewer_claude_temp_dir
    assert all(r.temp_dir is None for r in launcher.REVIEWER_CANDIDATES.values())


@pytest.mark.parametrize(
    "parsed",
    [{"final": None, "is_error": True, "error": "no JSON"}, {"final": "", "is_error": False},
     {"final": "done", "is_error": True}],
)
def test_verdict_answer_parsed_needs_a_final_message_and_no_error(
    launcher: ModuleType, tmp_path: Path, parsed: dict[str, Any]
) -> None:
    assert _verdicts(launcher, tmp_path, HONEST, parsed=parsed)["answer-parsed"] is False


@pytest.mark.parametrize("exit_code", [1, 2, 124, None])
def test_verdict_session_exit_needs_zero(
    launcher: ModuleType, tmp_path: Path, exit_code: int | None
) -> None:
    assert _verdicts(launcher, tmp_path, HONEST, session_exit=exit_code)["session-exit"] is False


def test_verdict_a_file_left_in_the_vendor_directory_fails_the_write_check(
    launcher: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "w").write_text("")
    assert _verdicts(launcher, tmp_path, HONEST)["write-vendor-home"] is False


def test_verdict_with_no_results_every_check_is_present_and_the_command_checks_fail(
    launcher: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "probe"
    (root / "copy").mkdir(parents=True)
    verdicts = launcher.reviewer_probe_verdicts(
        root, tmp_path / "outside", "t", ("reviewer-probe-canary-inert",), "", parsed={}, session_exit=1,
        reachability=(0, 0),
    )
    assert [v["denial"] for v in verdicts] == list(launcher.REVIEWER_PROBE_CHECKS)
    assert not any(v["held"] for v in verdicts if v["denial"] not in ("credential-variable",
                                                                       "plain-variable",
                                                                       "startup-variable"))


def test_record_holds_identity_and_verdicts_and_no_path_or_canary(
    launcher: ModuleType, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    record_path = tmp_path / "record.json"
    tool = tmp_path / "toolbin"
    tool.mkdir()
    claude = tool / "claude"
    claude.write_text("#!/bin/sh\necho '9.9.9 (Claude Code)'\n")
    claude.chmod(0o755)

    def session(argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        results = {**HONEST, "network_connect": "403", "network": "56", "write_tmpdir": "0"}
        results.pop("read_vendor_credential_1")
        results.pop("read_vendor_credential_0")
        _write_results(cwd.parent, results)
        tag = re.search(r"reviewer-probe-([0-9a-f]{12})", (cwd / "probe.sh").read_text())
        assert tag is not None
        (launcher.reviewer_claude_temp_dir(cwd) / f"reviewer-probe-{tag.group(1)}").touch()
        return subprocess.CompletedProcess(argv, 0, CLAUDE_ANSWER, "")

    verdicts, code = launcher.reviewer_probe(
        "claude", "haiku", env={"HOME": str(home), "PATH": str(tool)}, session=session,
        work_root=tmp_path / "reviews", reachable=lambda env: 0, record_path=record_path,
    )
    assert code == 0, verdicts
    record = json.loads(record_path.read_text())
    assert record["schema"] == "reviewer_probe_record.v1" and record["vendor"] == "claude"
    assert record["platform"] == sys.platform and record["session_exit"] == 0
    assert record["sign_in"] == "subscription"
    assert record["executable"]["name"] == "claude"
    assert record["executable"]["version"] == "9.9.9 (Claude Code)"
    assert re.fullmatch(r"[0-9a-f]{64}", record["executable"]["sha256"])
    text = record_path.read_text()
    assert str(tmp_path) not in text and "/Users/" not in text and "/home/" not in text
    assert "reviewer-probe-canary-" not in text and "reviewer-probe-home-" not in text


# --------------------------------------------------------------------------- admission


def test_admission_a_complete_passing_record_admits(launcher: ModuleType) -> None:
    record = _passing_record(launcher, "grok", "darwin")
    assert launcher.reviewer_record_admits(record, "grok", "darwin") == (True, "admitted")
    identity = {"name": "x", "sha256": "a" * 64, "version": "vendor 1.0"}
    assert launcher.reviewer_record_admits(record, "grok", "darwin", identity)[0] is True


def _mutations(launcher: ModuleType) -> list[tuple[str, Any]]:
    checks = list(launcher.REVIEWER_PROBE_CHECKS)
    ok = [{"denial": n, "held": True, "detail": "x"} for n in checks]
    return [
        ("not a mapping", []),
        ("wrong schema", {"schema": "other"}),
        ("wrong vendor", {"vendor": "muse"}),
        ("wrong platform", {"platform": "linux"}),
        ("no verdicts", {"verdicts": []}),
        ("a missing check", {"verdicts": ok[:-1]}),
        ("an unknown check", {"verdicts": ok + [{"denial": "x", "held": True, "detail": "x"}]}),
        ("a duplicated check", {"verdicts": ok + [ok[0]]}),
        ("a held that is a string", {"verdicts": [{**ok[0], "held": "true"}] + ok[1:]}),
        ("a verdict without detail", {"verdicts": [{"denial": checks[0], "held": True}] + ok[1:]}),
        ("a check that failed", {"verdicts": [{**ok[0], "held": False}] + ok[1:]}),
        ("only the answer check", {"verdicts": [{"denial": "answer-parsed", "held": True,
                                                 "detail": "x"}]}),
        ("a failed session", {"session_exit": 1}),
        ("a boolean exit", {"session_exit": True}),
        ("no exit", {"session_exit": None}),
        ("no executable", {"executable": None}),
        ("a short hash", {"executable": {"name": "x", "sha256": "abc", "version": "1"}}),
        ("no version", {"executable": {"name": "x", "sha256": "a" * 64, "version": ""}}),
    ]


@pytest.mark.parametrize("index", range(18))
def test_admission_anything_missing_duplicated_malformed_or_mismatched_refuses(
    launcher: ModuleType, index: int
) -> None:
    label, change = _mutations(launcher)[index]
    record = change if not isinstance(change, dict) else {
        **_passing_record(launcher, "grok", "darwin"), **change
    }
    admitted, why = launcher.reviewer_record_admits(record, "grok", "darwin")
    assert admitted is False and why, label


@pytest.mark.parametrize(
    "identity",
    [{"sha256": "b" * 64, "version": "vendor 1.0"}, {"sha256": "a" * 64, "version": "vendor 1.1"}],
)
def test_admission_a_changed_executable_refuses(
    launcher: ModuleType, identity: dict[str, str]
) -> None:
    record = _passing_record(launcher, "grok", "darwin")
    admitted, why = launcher.reviewer_record_admits(record, "grok", "darwin", identity)
    assert admitted is False and "not the one the probe passed on" in why


def _fake_vendor(tmp_path: Path) -> Path:
    binary = tmp_path / "vendor-bin"
    binary.write_bytes(MACH_O + b"\x00" * 60)
    binary.chmod(0o755)
    return binary


def test_admission_an_admitted_candidate_runs_its_pinned_copy_and_a_swap_is_refused(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admission path itself, with a synthetic vendor: no real vendor has passed yet."""
    repo, head = reviewed_repo
    binary = _fake_vendor(tmp_path)
    versions: list[str] = []

    def version(path: str, env: Any) -> str:
        versions.append(path)
        return "vendor 1.0"

    monkeypatch.setattr(launcher, "_reviewer_vendor_version", version)
    candidate = launcher.dataclasses.replace(
        launcher.REVIEWER_CANDIDATES["grok"], executable=lambda env: binary, widening=None,
    )
    monkeypatch.setitem(launcher.REVIEWER_CANDIDATES, "synthetic", candidate)
    record = _passing_record(
        launcher, "synthetic", sys.platform,
        executable={"name": binary.name, "sha256": launcher._reviewer_sha256(binary),
                    "version": "vendor 1.0"},
    )
    monkeypatch.setitem(launcher.REVIEWER_ADMISSIONS, ("synthetic", sys.platform), record)
    admitted = launcher._reviewer_admitted()["synthetic"]
    assert admitted.platforms == (sys.platform,)
    monkeypatch.setitem(launcher.REVIEWER_RECIPES, "synthetic", admitted)

    grok_output = (FIXTURES / "grok-session-output.json").read_text()
    session = FakeSession(json.dumps({**json.loads(grok_output), "text": '{"findings": []}'}))
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path, vendor="synthetic", model="grok-4.7"),
        env=_env(tmp_path), session=session,
    )
    assert code == 0 and result["executable"]["sha256"] == record["executable"]["sha256"]
    ran = Path(session.calls[0]["argv"][0])
    assert ran.name == binary.name and ran != binary and ran.parent.name == "bin"
    assert session.calls[0]["stdin"] == ""
    assert versions == [str(ran)]  # the version came from the verified copy only

    binary.write_bytes(MACH_O + b"\x01" * 60)  # an updater replaced it
    swapped = FakeSession(grok_output)
    with pytest.raises(launcher.ReviewerRefused, match="not the one the probe passed on"):
        launcher.reviewer_launch(
            _request(launcher, repo, head, tmp_path / "again", vendor="synthetic",
                     model="grok-4.7"),
            env=_env(tmp_path), session=swapped,
        )
    assert swapped.calls == [] and versions == [str(ran)]


def test_admission_a_mismatched_executable_is_never_run(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #223's review, finding 2: the bytes are compared before anything runs the file."""
    repo, head = reviewed_repo
    marker = tmp_path / "it-ran"
    selected = tmp_path / "vendor-bin"
    selected.write_text(f"#!/bin/sh\ntouch {marker}\necho 'vendor 1.0'\n")
    selected.chmod(0o755)
    runs: list[list[str]] = []
    real_run = subprocess.run

    def spy(argv: Any, *args: Any, **kwargs: Any) -> Any:
        runs.append([str(a) for a in argv])
        return real_run(argv, *args, **kwargs)

    candidate = launcher.dataclasses.replace(
        launcher.REVIEWER_CANDIDATES["grok"], executable=lambda env: selected, widening=None,
        platforms=(sys.platform,),
    )
    monkeypatch.setitem(launcher.REVIEWER_RECIPES, "mismatch", candidate)
    monkeypatch.setitem(launcher.REVIEWER_ADMISSIONS, ("mismatch", sys.platform),
                        _passing_record(launcher, "mismatch", sys.platform))
    monkeypatch.setattr(launcher.subprocess, "run", spy)
    session = FakeSession("")
    with pytest.raises(launcher.ReviewerRefused, match="SHA-256 differs from the record"):
        launcher.reviewer_launch(
            _request(launcher, repo, head, tmp_path, vendor="mismatch", model="m"),
            env=_env(tmp_path), session=session,
        )
    assert runs == [] and not marker.exists() and session.calls == []
    assert not (tmp_path / "reviews").exists()


def test_admission_a_candidate_with_no_record_on_this_platform_is_refused(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, head = reviewed_repo
    candidate = launcher.dataclasses.replace(
        launcher.REVIEWER_CANDIDATES["muse"], executable=lambda env: _fake_vendor(tmp_path),
    )
    monkeypatch.setitem(launcher.REVIEWER_RECIPES, "unrecorded", candidate)
    session = FakeSession("")
    with pytest.raises(launcher.ReviewerRefused, match="no admitted probe record"):
        launcher.reviewer_launch(
            _request(launcher, repo, head, tmp_path, vendor="unrecorded", model="m"),
            env=_env(tmp_path), session=session,
        )
    assert session.calls == [] and not (tmp_path / "reviews").exists()


# --------------------------------------------------------------------------- the outcomes


def test_outcome_there_is_one_record_per_candidate(launcher: ModuleType) -> None:
    vendors = sorted(record["vendor"] for record in _records())
    assert vendors == sorted(launcher.REVIEWER_CANDIDATES)


@pytest.mark.parametrize("record", _records(), ids=lambda r: f"{r['vendor']}-{r['platform']}")
def test_outcome_a_vendor_reviews_exactly_when_its_record_admits_it(
    launcher: ModuleType, record: dict[str, Any], reviewed_repo: tuple[Path, str],
    tmp_path: Path,
) -> None:
    vendor, platform = record["vendor"], record["platform"]
    admitted, why = launcher.reviewer_record_admits(record, vendor, platform)
    assert ((vendor, platform) in launcher.REVIEWER_ADMISSIONS) is admitted, why
    if admitted:
        assert launcher.REVIEWER_ADMISSIONS[(vendor, platform)] == record
        assert platform in launcher.REVIEWER_RECIPES[vendor].platforms
        return
    assert vendor not in launcher.REVIEWER_RECIPES
    repo, head = reviewed_repo
    packet = tmp_path / "packet"
    packet.mkdir()
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER), "review", "--vendor", vendor, "--model", "m",
         "--effort", "high", "--repo", str(repo), "--head", head, "--packet", str(packet),
         "--prompt", str(SAGA_PROMPT), "--schema", str(SAGA_SCHEMA), "--out", str(tmp_path / "o")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 2 and f"{vendor} has no reviewer sandbox recipe" in proc.stderr


def test_live_probe_agrees_with_the_tables(launcher: ModuleType) -> None:
    """Set REVIEWER_PROBE_LIVE_RECORD to a record a live probe just wrote."""
    path = os.environ.get("REVIEWER_PROBE_LIVE_RECORD")
    if not path:
        pytest.skip("REVIEWER_PROBE_LIVE_RECORD is not set")
    assert Path(path).is_file(), f"the live probe wrote no record at {path}"
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    vendor, platform = record["vendor"], record["platform"]
    admitted, why = launcher.reviewer_record_admits(record, vendor, platform)
    assert (vendor in launcher.REVIEWER_RECIPES) is admitted, why


# --------------------------------------------------------------------------- the journal


def _journal_names_failures(text: str, record: dict[str, Any]) -> bool:
    failing = [v["denial"] for v in record["verdicts"] if v["held"] is not True]
    return f"reviewer-probe --vendor {record['vendor']}" in text and all(
        f"`{name}`" in text for name in failing
    )


@pytest.mark.parametrize("record", _records(), ids=lambda r: f"{r['vendor']}-{r['platform']}")
def test_learnings_names_every_failing_check_of_a_refused_vendor(
    launcher: ModuleType, record: dict[str, Any]
) -> None:
    if launcher.reviewer_record_admits(record, record["vendor"], record["platform"])[0]:
        return
    text = LEARNINGS.read_text(encoding="utf-8")
    assert _journal_names_failures(text, record)
    failing = next(v["denial"] for v in record["verdicts"] if v["held"] is not True)
    assert not _journal_names_failures(text.replace(f"`{failing}`", ""), record)


# --------------------------------------------------------------------------- Grok


def test_grok_argv_is_headless_sandboxed_and_never_auto_approves(
    launcher: ModuleType, tmp_path: Path
) -> None:
    grok = launcher.REVIEWER_CANDIDATES["grok"]
    settings = tmp_path / "copy" / ".grok" / "sandbox.toml"
    argv = grok.argv("grok-4.7", "xhigh", settings, executable=tmp_path / "grok",
                     prompt_path=tmp_path / "message.md")
    assert argv[0] == str(tmp_path / "grok")
    assert argv[argv.index("--prompt-file") + 1] == str(tmp_path / "message.md")
    assert argv[argv.index("--sandbox") + 1] == launcher.reviewer_grok_profile_name(settings)
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--allow") + 1] == "Bash"
    for flag in ("--no-plan", "--disable-web-search", "--output-format"):
        assert flag in argv
    assert not set(launcher.REVIEWER_FORBIDDEN_FLAGS["grok"]) & set(argv)
    assert "--max-budget-usd" not in argv
    with pytest.raises(launcher.ReviewerRefused, match="no dollar ceiling"):
        grok.argv("grok-4.7", None, settings, max_budget_usd="5", executable=tmp_path / "g",
                  prompt_path=tmp_path / "m")


def test_grok_profile_extends_strict_and_denies_temp_and_its_sign_in_files(
    launcher: ModuleType, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    copy, packet = root / "copy", tmp_path / "packet"
    copy.mkdir(parents=True)
    packet.mkdir()
    settings = launcher.reviewer_grok_settings(copy, packet, {"HOME": str(home)}, toolchain=[],
                                               extra_deny_read=["/elsewhere"])
    path, extra = launcher.reviewer_grok_materialize(settings, root, copy)
    text = path.read_text()
    assert path == copy / ".grok" / "sandbox.toml"
    assert f"[profiles.{launcher.reviewer_grok_profile_name(path)}]" in text
    assert 'extends = "strict"' in text and "restrict_network = true" in text
    for denied in [*launcher.reviewer_temp_roots(), str(home / ".grok" / "auth.json"),
                   str(home / ".grok" / "config.toml"), "/elsewhere"]:
        assert json.dumps(denied) in text.split("deny = ")[1]
    assert json.dumps(str(packet.resolve())) in text.split("read_only = ")[1]
    overlay = json.loads(extra["GROK_CONFIG"])["shell_environment_policy"]
    assert overlay["include_only"] == list(launcher.REVIEWER_ENVIRONMENT_ALLOWED)
    assert overlay["ignore_default_excludes"] is False
    other = launcher.reviewer_grok_profile_name(tmp_path / "another" / "sandbox.toml")
    assert other != launcher.reviewer_grok_profile_name(path)


def test_grok_api_key_variables_are_removed(launcher: ModuleType) -> None:
    grok = launcher.REVIEWER_CANDIDATES["grok"]
    kept = launcher.reviewer_session_environment(
        {"XAI_API_KEY": "inert", "GROK_DEPLOYMENT_KEY": "inert", "HONCHO_WORKSPACE": "kept"},
        grok.api_key_variables, grok.api_key_prefixes,
    )
    assert kept == {"HONCHO_WORKSPACE": "kept", "GIT_CONFIG_GLOBAL": os.devnull}


def test_grok_withholds_the_changes_own_grok_directory(launcher: ModuleType, tmp_path: Path) -> None:
    grok = launcher.REVIEWER_CANDIDATES["grok"]
    copy = tmp_path / "copy"
    for rel in (".grok/hooks/h.json", ".grok/sandbox.toml", ".mcp.json", "src.py"):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        (copy / rel).write_text("x")
    launcher.reviewer_withhold_untrusted(
        copy, grok.untrusted_dirs, grok.untrusted_files, grok.instruction_names
    )
    assert not (copy / ".grok").exists() and not (copy / ".mcp.json").exists()
    assert (copy / "src.py").exists()


def test_grok_parser_reads_the_captured_result(launcher: ModuleType) -> None:
    parsed = launcher.reviewer_parse_grok_result(
        (FIXTURES / "grok-session-output.json").read_text()
    )
    assert parsed["final"] == "ok" and parsed["is_error"] is False
    assert parsed["resolved"] == ["grok-4.7-build-fast"]
    assert parsed["usage"]["output_tokens"] is not None and parsed["usage"]["cost_usd"] > 0


@pytest.mark.parametrize(
    "stdout", ["", "not json", "[]", json.dumps({"text": "partial", "stopReason": "max_tokens"})]
)
def test_grok_parser_reports_an_error(launcher: ModuleType, stdout: str) -> None:
    parsed = launcher.reviewer_parse_grok_result(stdout)
    assert parsed["is_error"] is True and parsed["error"]


def test_grok_widening_refuses_a_per_model_api_key(launcher: ModuleType, tmp_path: Path) -> None:
    grok_home = tmp_path / ".grok"
    grok_home.mkdir()
    env = {"HOME": str(tmp_path)}
    assert launcher.reviewer_grok_widening(env) == []
    (grok_home / "config.toml").write_text('[model."grok-4.7"]\nmax_tokens = 5\n')
    assert launcher.reviewer_grok_widening(env) == []
    (grok_home / "config.toml").write_text('[model."grok-4.7"]\napi_key = "inert-example"\n')
    assert launcher.reviewer_grok_widening(env) == ["config.toml sets api_key for model grok-4.7"]
    (grok_home / "config.toml").write_text("not = [toml")
    assert "cannot be read as TOML" in launcher.reviewer_grok_widening(env)[0]


def test_grok_executable_is_the_native_binary_not_a_wrapper(
    launcher: ModuleType, tmp_path: Path
) -> None:
    path_dir = tmp_path / "pathbin"
    path_dir.mkdir()
    wrapper = path_dir / "grok"
    wrapper.write_text("#!/bin/sh\nexec real-grok --trust \"$@\"\n")
    wrapper.chmod(0o755)
    env = {"HOME": str(tmp_path), "PATH": str(path_dir)}
    with pytest.raises(launcher.ReviewerRefused, match="no native grok"):
        launcher.reviewer_grok_executable(env)
    (tmp_path / ".grok" / "bin").mkdir(parents=True)
    native = tmp_path / ".grok" / "bin" / "grok"
    native.write_bytes(MACH_O + b"\x00" * 8)
    assert launcher.reviewer_grok_executable(env) == native.resolve()


# --------------------------------------------------------------------------- Muse


def test_muse_argv_keeps_the_sandbox_and_approvals_on(launcher: ModuleType, tmp_path: Path) -> None:
    muse = launcher.REVIEWER_CANDIDATES["muse"]
    argv = muse.argv("muse-spark-1.3-contributor", "max", tmp_path / "s.json",
                     executable=tmp_path / "muse-bin", prompt_path=tmp_path / "message.md")
    assert argv[:2] == [str(tmp_path / "muse-bin"), "exec"]
    assert argv[argv.index("--sandbox-network") + 1] == "restricted"
    assert argv[argv.index("--prompt-file") + 1] == str(tmp_path / "message.md")
    for flag in ("--disable-web-tools", "--json", "--no-session-log"):
        assert flag in argv
    assert not set(launcher.REVIEWER_FORBIDDEN_FLAGS["muse"]) & set(argv)
    for absent in ("--api-key-stdin", "--max-budget-usd", "--permission-profile"):
        assert absent not in argv


def test_muse_api_key_variable_is_removed(launcher: ModuleType) -> None:
    muse = launcher.REVIEWER_CANDIDATES["muse"]
    kept = launcher.reviewer_session_environment(
        {"META_API_KEY": "inert", "PATH": "/usr/bin"}, muse.api_key_variables,
        muse.api_key_prefixes,
    )
    assert kept == {"PATH": "/usr/bin", "GIT_CONFIG_GLOBAL": os.devnull}


def test_muse_withholds_its_project_files(launcher: ModuleType, tmp_path: Path) -> None:
    muse = launcher.REVIEWER_CANDIDATES["muse"]
    copy = tmp_path / "copy"
    for rel in (".muse/settings.json", ".agents/skills/x.md", ".mcp.json", "src.py"):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        (copy / rel).write_text("x")
    (copy / "AGENTS.md").write_text("Rules.\n@~/.ssh/id_rsa\n")
    launcher.reviewer_withhold_untrusted(
        copy, muse.untrusted_dirs, muse.untrusted_files, muse.instruction_names
    )
    for gone in (".muse", ".agents", ".mcp.json", "AGENTS.md"):
        assert not (copy / gone).exists(), gone
    assert (copy / "src.py").exists()


def test_muse_parser_reads_the_captured_stream(launcher: ModuleType) -> None:
    parsed = launcher.reviewer_parse_muse_result(
        (FIXTURES / "muse-session-output.jsonl").read_text()
    )
    assert parsed["final"] == "done" and parsed["is_error"] is False
    assert parsed["resolved"] == ["muse-spark-1.3-contributor"] and parsed["usage"] is None


def test_muse_parser_reports_an_error(launcher: ModuleType) -> None:
    lines = (FIXTURES / "muse-session-output.jsonl").read_text().splitlines()
    assert launcher.reviewer_parse_muse_result("")["is_error"] is True
    no_terminal = "\n".join(line for line in lines if "run.terminal." not in line)
    assert launcher.reviewer_parse_muse_result(no_terminal)["error"] == (
        "the session printed no terminal event"
    )
    failed = [json.loads(line) for line in lines]
    terminal = failed[-1]
    payload = json.loads(terminal["payload"]) if isinstance(terminal["payload"], str) else dict(
        terminal["payload"])
    payload.update({"terminal": "failed", "reason": "provider_error"})
    terminal["payload"] = json.dumps(payload)
    stream = "\n".join(json.dumps(record) for record in failed)
    parsed = launcher.reviewer_parse_muse_result(stream)
    assert parsed["is_error"] is True and "failed" in parsed["error"]


def test_muse_executable_is_the_versioned_binary_behind_the_launcher_script(
    launcher: ModuleType, tmp_path: Path
) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "muse"
    script.write_text("#!/usr/bin/env bash\nexec \"$binary\" \"$@\"\n")
    script.chmod(0o755)
    env = {"HOME": str(tmp_path), "PATH": str(bindir)}
    with pytest.raises(launcher.ReviewerRefused, match="no native muse"):
        launcher.reviewer_muse_executable(env)
    (bindir / ".muse-version").write_text("1.4.6-R6000.1\n")
    binary = bindir / "muse-bin-1.4.6-R6000.1"
    binary.write_bytes(MACH_O + b"\x00" * 8)
    assert launcher.reviewer_muse_executable(env) == binary.resolve()
    (bindir / ".muse-version").write_text("../../etc/passwd\n")
    with pytest.raises(launcher.ReviewerRefused, match="no native muse"):
        launcher.reviewer_muse_executable(env)


# --------------------------------------------------------------------------- offline dependencies


def _vendored_packet(launcher: ModuleType, tmp_path: Path, entry: Any = None) -> Path:
    """A packet whose ``dependencies.json`` names vendored Rust sources (issue #262)."""
    packet = tmp_path / "packet"
    (packet / "dependencies" / "rust" / "itoa").mkdir(parents=True)
    record = {
        "schema": launcher.REVIEWER_DEPENDENCIES_SCHEMA,
        "rust": entry if entry is not None
        else {"state": "fetched", "directory": "dependencies/rust", "crates": 1},
    }
    (packet / "dependencies.json").write_text(json.dumps(record), "utf-8")
    return packet


def _launch_with(
    launcher: ModuleType, repo: Path, head: str, tmp_path: Path, packet: Path, **env: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    session = FakeSession(CLAUDE_ANSWER)
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path, packet=packet, max_budget_usd="1"),
        env=_env(tmp_path, **env), session=session,
    )
    assert code == 0, result
    argv = session.calls[0]["argv"]
    settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text("utf-8"))
    return result, settings, session.calls[0]["env"]


def test_offline_the_reviewer_reads_the_vendored_crates_read_only_through_its_cargo_home(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    import tomllib  # noqa: PLC0415

    repo, head = reviewed_repo
    packet = _vendored_packet(launcher, tmp_path)
    vendor = str((packet / "dependencies" / "rust").resolve())
    result, settings, env = _launch_with(
        launcher, repo, head, tmp_path, packet,
        CARGO_HOME=str(tmp_path / "home" / ".cargo"), CARGO_REGISTRY_TOKEN="inert-example",
        SSH_AUTH_SOCK="/tmp/example-agent.sock",
    )
    cargo_home = Path(env["CARGO_HOME"])
    copy = Path(result["scratch"]["path"])
    assert cargo_home == copy.parent / "cargo-home" and not cargo_home.is_relative_to(copy)
    assert env["CARGO_NET_OFFLINE"] == "true"
    config = cargo_home / "config.toml"
    parsed = tomllib.loads(config.read_text("utf-8"))
    name = parsed["source"]["crates-io"]["replace-with"]
    assert name.startswith("saga-vendored-") and len(name) == len("saga-vendored-") + 16
    assert parsed["source"][name] == {"directory": vendor}
    assert parsed["net"] == {"offline": True}
    assert not os.access(config, os.W_OK)
    if shutil.which("cargo", path=os.environ.get("PATH", "")):
        assert env["PATH"].split(os.pathsep)[0] == str(cargo_home / "bin")
    filesystem = settings["sandbox"]["filesystem"]
    for path in (str(cargo_home.resolve()), vendor):
        assert path in filesystem["allowRead"]
        assert path in filesystem["denyWrite"], "read-only is stated, not implied"
    assert filesystem["denyRead"][0] == "~"
    # Network and credentials stay denied exactly as before.
    assert settings["sandbox"]["network"] == {"strictAllowlist": True, "allowedDomains": []}
    denied = {item["name"] for item in settings["sandbox"]["credentials"]["envVars"]}
    assert {"CARGO_REGISTRY_TOKEN", "SSH_AUTH_SOCK"} <= denied
    assert not {"CARGO_HOME", "CARGO_NET_OFFLINE"} & denied
    assert "Read(~/.cargo/credentials.toml)" in settings["permissions"]["deny"]
    assert {"WebFetch", "WebSearch", "mcp__*"} <= set(settings["permissions"]["deny"])
    reads = {item["path"]: item["reason"] for item in result["sandbox_reads"]["allowed"]}
    assert "issue #262" in reads[vendor] and "issue #262" in reads[str(cargo_home.resolve())]


@pytest.mark.parametrize(
    "entry",
    [
        {"state": "not-fetched", "reason": "x"},
        {"state": "fetched", "directory": "/etc"},
        {"state": "fetched", "directory": "../elsewhere"},
        {"state": "fetched", "directory": "dependencies/missing"},
    ],
)
def test_offline_an_untrustworthy_entry_is_ignored_and_cargo_stays_offline(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, entry: Any
) -> None:
    repo, head = reviewed_repo
    packet = _vendored_packet(launcher, tmp_path, entry)
    _result, settings, env = _launch_with(launcher, repo, head, tmp_path, packet)
    assert launcher.reviewer_packet_vendor(packet) is None
    config = (Path(env["CARGO_HOME"]) / "config.toml").read_text("utf-8")
    assert "[source" not in config and "offline = true" in config
    assert env["CARGO_NET_OFFLINE"] == "true"
    root = str(packet.resolve())
    reads = settings["sandbox"]["filesystem"]["allowRead"]
    assert [path for path in reads if path != root and path.startswith(root + "/")] == []


def test_offline_the_cargo_on_path_runs_through_the_cargo_home_s_shim(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    bindir = tmp_path / "tools"
    bindir.mkdir()
    fake = bindir / "cargo"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', "utf-8")
    fake.chmod(0o755)
    packet = _vendored_packet(launcher, tmp_path)
    _result, settings, env = _launch_with(
        launcher, repo, head, tmp_path, packet, PATH=f"{bindir}{os.pathsep}/usr/bin:/bin",
    )
    cargo_home = Path(env["CARGO_HOME"])
    shim = cargo_home / "bin" / "cargo"
    assert env["PATH"] == os.pathsep.join([str(shim.parent), str(bindir), "/usr/bin:/bin"])
    assert not os.access(shim, os.W_OK)
    config = str(cargo_home / "config.toml")
    ran = subprocess.run([str(shim), "test", "-q"], capture_output=True, text=True, check=True)
    assert ran.stdout.splitlines() == ["--config", config, "test", "-q"]
    ran = subprocess.run([str(shim), "+nightly", "build"], capture_output=True, text=True,
                         check=True)
    assert ran.stdout.splitlines() == ["+nightly", "--config", config, "build"]
    # The shim sits inside the cargo home, which the sandbox reads and never writes.
    filesystem = settings["sandbox"]["filesystem"]
    assert str(cargo_home.resolve()) in filesystem["allowRead"]
    assert str(cargo_home.resolve()) in filesystem["denyWrite"]


def _rustup_home(tmp_path: Path) -> tuple[Path, Path]:
    """A home laid out as rustup installs it: proxies in ~/.cargo/bin beside the credentials."""
    home = tmp_path / "home"
    bindir = home / ".cargo" / "bin"
    bindir.mkdir(parents=True)
    rustup = bindir / "rustup"
    rustup.write_text("#!/bin/sh\nexit 0\n", "utf-8")
    rustup.chmod(0o755)
    for name in ("cargo", "rustc"):
        (bindir / name).symlink_to("rustup")
    (home / ".cargo" / "credentials.toml").write_text('[registry]\ntoken = "inert-example"\n')
    (home / ".rustup" / "toolchains" / "stable" / "bin").mkdir(parents=True)
    (home / ".rustup" / "settings.toml").write_text('default_toolchain = "stable"\n', "utf-8")
    (home / ".rustup" / "downloads").mkdir()
    return home, bindir


def test_offline_a_rustup_cargo_gets_its_bin_and_toolchains_never_the_credentials(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """On CI cargo is a rustup proxy under ~/.cargo/bin; the whole prefix used to be dropped."""
    home, bindir = _rustup_home(tmp_path)
    env = {"HOME": str(home), "PATH": f"{bindir}{os.pathsep}/usr/bin:/bin"}
    allowed, dropped = launcher.reviewer_toolchain_paths(env)
    paths = {item["path"] for item in allowed}
    assert {str(bindir), str(home / ".rustup" / "toolchains"),
            str(home / ".rustup" / "settings.toml")} <= paths
    for path in paths:
        assert launcher.reviewer_allowed_read_problem(Path(path), home) is None
    assert str(home / ".cargo") not in paths and str(home / ".rustup") not in paths
    assert str(home / ".rustup" / "downloads") not in paths
    assert any(item["path"] == str(home / ".cargo") for item in dropped)


def test_offline_a_cargo_outside_home_opens_no_rustup_folder(
    launcher: ModuleType, tmp_path: Path
) -> None:
    home, _bindir = _rustup_home(tmp_path)
    tools = tmp_path / "opt" / "bin"
    tools.mkdir(parents=True)
    for name in ("cargo", "rustc"):
        (tools / name).write_text("#!/bin/sh\nexit 0\n", "utf-8")
        (tools / name).chmod(0o755)
    allowed, _dropped = launcher.reviewer_toolchain_paths(
        {"HOME": str(home), "PATH": f"{tools}{os.pathsep}/usr/bin:/bin"}
    )
    assert not any(".rustup" in item["path"] or ".cargo" in item["path"] for item in allowed)


def test_offline_the_reviewer_s_commands_get_rustup_s_home_and_choice(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    packet = _vendored_packet(launcher, tmp_path)
    _result, _settings, env = _launch_with(launcher, repo, head, tmp_path, packet)
    assert env["RUSTUP_HOME"] == str(tmp_path / "home" / ".rustup")
    _result, _settings, env = _launch_with(
        launcher, repo, head, tmp_path, packet,
        RUSTUP_HOME="/opt/example/rustup", RUSTUP_TOOLCHAIN="1.98.1",
    )
    assert env["RUSTUP_HOME"] == "/opt/example/rustup" and env["RUSTUP_TOOLCHAIN"] == "1.98.1"
    script = launcher.reviewer_claude_shell_script(tmp_path / "sentinel", "token")
    for name in ("RUSTUP_HOME", "RUSTUP_TOOLCHAIN"):
        assert f'${{{name}+"{name}=${name}"}}' in script


def test_offline_without_a_cargo_on_path_there_is_no_shim(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    packet = _vendored_packet(launcher, tmp_path)
    _result, _settings, env = _launch_with(
        launcher, repo, head, tmp_path, packet, PATH=str(tmp_path / "empty"),
    )
    assert not (Path(env["CARGO_HOME"]) / "bin").exists()
    assert env["PATH"] == str(tmp_path / "empty")


def _inert_crate(root: Path, value: int) -> None:
    crate = root / "inertdep"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        '[package]\nname = "inertdep"\nversion = "0.1.0"\nedition = "2021"\n', "utf-8"
    )
    (crate / "src" / "lib.rs").write_text(f"pub fn two() -> i32 {{ {value} }}\n", "utf-8")
    (crate / ".cargo-checksum.json").write_text(
        json.dumps({"files": {}, "package": "ab" * 32}), "utf-8"
    )


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo is not installed")
def test_live_offline_the_shim_outranks_a_commit_s_own_source_replacement(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """Real cargo, offline: the copy replaces crates.io with a crate it ships; the vendored one
    still wins through the shim, and wins without it only when nothing outranks the home."""
    vendor = tmp_path / "vendor"
    _inert_crate(vendor, 2)
    project = tmp_path / "copy"
    (project / "src").mkdir(parents=True)
    (project / ".cargo").mkdir()
    (project / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        '\n[dependencies]\ninertdep = "0.1"\n', "utf-8"
    )
    (project / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\n'
        'dependencies = ["inertdep"]\n\n[[package]]\nname = "inertdep"\nversion = "0.1.0"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
        f'checksum = "{"ab" * 32}"\n', "utf-8"
    )
    (project / ".cargo" / "config.toml").write_text(
        '[source.crates-io]\nreplace-with = "planted"\n\n[source.planted]\ndirectory = "planted"\n',
        "utf-8",
    )
    _inert_crate(project / "planted", 99)
    (project / "src" / "main.rs").write_text(
        'fn main() { println!("VALUE {}", inertdep::two()); }\n', "utf-8"
    )
    # The session environment a launch builds: the operator's own HOME and RUSTUP_* values.
    session_env = launcher.reviewer_session_environment(
        {**{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "RUSTUP_HOME",
                                                        "RUSTUP_TOOLCHAIN", "LANG")},
         "CARGO_TARGET_DIR": str(tmp_path / "target")}
    )
    cargo_home = launcher.reviewer_cargo_home(tmp_path / "root", vendor, session_env)
    launcher.reviewer_offline_cargo(session_env, cargo_home)
    through = subprocess.run(["cargo", "run", "-q", "--offline"], cwd=project, env=session_env,
                             capture_output=True, text=True, timeout=300, check=False)
    assert through.stdout.strip() == "VALUE 2", through.stderr
    plain = subprocess.run([str(shutil.which("cargo"))] + ["run", "-q", "--offline"],
                           cwd=project, env=session_env, capture_output=True, text=True,
                           timeout=300, check=False)
    assert plain.stdout.strip() == "VALUE 99", plain.stderr


def test_offline_a_symlinked_dependency_folder_is_ignored(
    launcher: ModuleType, tmp_path: Path
) -> None:
    packet = tmp_path / "packet"
    (packet / "dependencies").mkdir(parents=True)
    (packet / "dependencies" / "rust").symlink_to(tmp_path)
    (packet / "dependencies.json").write_text(json.dumps({
        "schema": launcher.REVIEWER_DEPENDENCIES_SCHEMA,
        "rust": {"state": "fetched", "directory": "dependencies/rust"},
    }), "utf-8")
    assert launcher.reviewer_packet_vendor(packet) is None
    (packet / "dependencies.json").write_text(json.dumps({
        "schema": "something-else", "rust": {"state": "fetched", "directory": "dependencies/rust"},
    }), "utf-8")
    assert launcher.reviewer_packet_vendor(packet) is None


def _python3_version() -> str:
    found = shutil.which("python3", path=os.environ.get("PATH", ""))
    assert found
    return subprocess.run(
        [found, "-I", "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _python_packet(launcher: ModuleType, tmp_path: Path, entry: Any = None) -> Path:
    """A packet whose ``dependencies.json`` names saga's installed Python packages, holding
    console scripts a hostile wheel could install, named after the vendor and git."""
    packet = tmp_path / "packet"
    site = packet / "dependencies" / "python" / "site-packages"
    (site / "inertdep").mkdir(parents=True)
    (site / "inertdep" / "__init__.py").write_text("def two():\n    return 2\n", "utf-8")
    for folder in (site / "bin", packet / "dependencies" / "python" / "bin"):
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("claude", "git", "python3"):
            (folder / name).write_text("#!/bin/sh\necho planted\n", "utf-8")
            (folder / name).chmod(0o755)
    record = {
        "schema": launcher.REVIEWER_DEPENDENCIES_SCHEMA,
        "python": entry if entry is not None
        else {"state": "installed", "directory": "dependencies/python/site-packages",
              "interpreter": {"version": _python3_version()}},
    }
    (packet / "dependencies.json").write_text(json.dumps(record), "utf-8")
    return packet


def test_offline_a_wheel_s_scripts_never_reach_the_vendor_process_s_path(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    packet = _python_packet(launcher, tmp_path)
    given = _env(tmp_path)
    result, settings, env = _launch_with(launcher, repo, head, tmp_path, packet)
    root = str(packet.resolve())
    copy = Path(result["scratch"]["path"])
    python_env = launcher.reviewer_python_env_dir(copy.parent)
    # The vendor process (and its own ``claude --version`` and git) keep the operator's PATH.
    assert env["PATH"].split(os.pathsep)[-len(given["PATH"].split(os.pathsep)):] == \
        given["PATH"].split(os.pathsep)
    for part in env["PATH"].split(os.pathsep):
        assert not part.startswith(root) and not part.startswith(str(python_env))
    for name in ("claude", "git"):
        found = shutil.which(name, path=env["PATH"])
        assert found is None or not Path(found).resolve().is_relative_to(packet.resolve())
    assert "VIRTUAL_ENV" not in env
    # Sandboxed commands get the launcher's environment, whose bin holds only python.
    assert sorted(item.name for item in (python_env / "bin").iterdir()) == ["python", "python3"]
    prefix = Path(env.get(launcher.REVIEWER_SHELL_PREFIX)
                  or settings["env"][launcher.REVIEWER_SHELL_PREFIX]).read_text("utf-8")
    assert f"PATH={python_env / 'bin'}:" in prefix and f"VIRTUAL_ENV={python_env}" in prefix
    assert root not in prefix
    site = str((packet / "dependencies" / "python" / "site-packages").resolve())
    filesystem = settings["sandbox"]["filesystem"]
    for path in (site, str(python_env.resolve())):
        assert path in filesystem["allowRead"] and path in filesystem["denyWrite"]
    reads = {item["path"]: item["reason"] for item in result["sandbox_reads"]["allowed"]}
    assert "only python3 and python" in reads[str(python_env.resolve())]


def test_offline_the_reviewer_s_python3_imports_the_packet_s_packages(
    launcher: ModuleType, tmp_path: Path
) -> None:
    packet = _python_packet(launcher, tmp_path)
    packages = launcher.reviewer_packet_python(packet)
    assert packages is not None
    root = tmp_path / "root"
    python_env = launcher.reviewer_python_env(root, packages, {"PATH": os.environ["PATH"]})
    assert python_env == launcher.reviewer_python_env_dir(root)
    ran = subprocess.run(
        ["python3", "-c", "import sys, inertdep; print(inertdep.two(), sys.prefix)"],
        env={"PATH": f"{python_env / 'bin'}:/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True, text=True, check=False,
    )
    assert ran.stdout.split() == ["2", str(python_env)], ran.stderr


def test_offline_the_operator_s_virtual_env_never_reaches_the_reviewer(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    packet = _vendored_packet(launcher, tmp_path)
    operator = str(tmp_path / "operator-venv")
    _result, settings, env = _launch_with(
        launcher, repo, head, tmp_path, packet, VIRTUAL_ENV=operator,
    )
    assert "VIRTUAL_ENV" not in env
    prefix = Path(settings["env"][launcher.REVIEWER_SHELL_PREFIX]).read_text("utf-8")
    assert operator not in prefix and "python-env" not in prefix


@pytest.mark.parametrize(
    "entry",
    [
        {"state": "not-installed", "reason": "network"},
        {"state": "installed", "directory": "/etc", "interpreter": {"version": "3.12.0"}},
        {"state": "installed", "directory": "../elsewhere", "interpreter": {"version": "3.12.0"}},
        {"state": "installed", "directory": "dependencies/missing",
         "interpreter": {"version": "3.12.0"}},
        {"state": "installed", "directory": "dependencies/python/site-packages"},
    ],
)
def test_offline_an_untrustworthy_python_entry_is_ignored(
    launcher: ModuleType, tmp_path: Path, entry: Any
) -> None:
    packet = _python_packet(launcher, tmp_path, entry)
    assert launcher.reviewer_packet_python(packet) is None
    assert launcher.reviewer_python_env(tmp_path / "root", None, os.environ) is None
    session_env = {"PATH": "/usr/bin", "VIRTUAL_ENV": "/elsewhere"}
    launcher.reviewer_offline_python(session_env)
    assert session_env == {"PATH": "/usr/bin"}


def test_offline_packages_for_another_python_are_not_used(
    launcher: ModuleType, tmp_path: Path
) -> None:
    packet = _python_packet(launcher, tmp_path, {
        "state": "partial", "directory": "dependencies/python/site-packages",
        "interpreter": {"version": "2.7.18"}})
    packages = launcher.reviewer_packet_python(packet)
    assert packages is not None
    assert launcher.reviewer_python_env(tmp_path / "root", packages, os.environ) is None


def _node_packet(launcher: ModuleType, tmp_path: Path, entry: Any = None) -> Path:
    """A packet whose ``dependencies.json`` names saga's installed npm packages: one CommonJS
    and one ESM-only package, and ``.bin`` scripts a hostile package could ship, named after
    the vendor and git."""
    packet = tmp_path / "packet"
    modules = packet / "dependencies" / "node" / "node_modules"
    (modules / "cjs-dep").mkdir(parents=True)
    (modules / "cjs-dep" / "package.json").write_text(
        '{"name": "cjs-dep", "version": "1.0.0", "main": "index.js"}', "utf-8")
    (modules / "cjs-dep" / "index.js").write_text('module.exports = () => "cjs";\n', "utf-8")
    (modules / "esm-dep").mkdir()
    (modules / "esm-dep" / "package.json").write_text(
        '{"name": "esm-dep", "version": "1.0.0", "type": "module", '
        '"exports": {".": "./index.js"}}', "utf-8")
    (modules / "esm-dep" / "index.js").write_text('export default () => "esm";\n', "utf-8")
    (modules / ".bin").mkdir()
    for name in ("claude", "git", "node"):
        (modules / ".bin" / name).write_text("#!/bin/sh\necho planted\n", "utf-8")
        (modules / ".bin" / name).chmod(0o755)
    record = {
        "schema": launcher.REVIEWER_DEPENDENCIES_SCHEMA,
        "node": entry if entry is not None
        else {"state": "installed", "directory": "dependencies/node/node_modules"},
    }
    (packet / "dependencies.json").write_text(json.dumps(record), "utf-8")
    return packet


def test_node_the_copy_links_the_packet_s_packages_read_only_and_never_a_change(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    packet = _node_packet(launcher, tmp_path)
    modules = (packet / "dependencies" / "node" / "node_modules").resolve()
    result, settings, env = _launch_with(launcher, repo, head, tmp_path, packet)
    copy = Path(result["scratch"]["path"])
    link = copy / "node_modules"
    assert link.is_symlink() and Path(os.readlink(link)) == modules
    # Made before the baseline, so finish never reads it as a link the session made.
    assert result["scratch"]["changes"] == {
        "added": [], "modified": [], "deleted": [], "links": []}
    filesystem = settings["sandbox"]["filesystem"]
    assert str(modules) in filesystem["allowRead"] and str(modules) in filesystem["denyWrite"]
    reads = {item["path"]: item["reason"] for item in result["sandbox_reads"]["allowed"]}
    assert "npm packages, read-only" in reads[str(modules)]
    # Nothing a package ships can be found by name: not by the vendor, not by a command.
    prefix = Path(settings["env"][launcher.REVIEWER_SHELL_PREFIX]).read_text("utf-8")
    for part in env["PATH"].split(os.pathsep):
        assert not part.startswith(str(packet.resolve()))
    assert str(packet.resolve()) not in prefix and ".bin" not in prefix


def test_node_claude_s_file_tools_may_never_write_the_packages(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    packet = _node_packet(launcher, tmp_path)
    modules = (packet / "dependencies" / "node" / "node_modules").resolve()
    _result, settings, _env = _launch_with(launcher, repo, head, tmp_path, packet)
    deny = settings["permissions"]["deny"]
    # Edit rules cover Write too. By the real path, and through the copy's link.
    assert f"Edit(/{modules}/**)" in deny
    assert "Edit(./node_modules)" in deny and "Edit(./node_modules/**)" in deny


def test_node_a_head_with_its_own_node_modules_keeps_it(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    (copy / "node_modules").mkdir(parents=True)
    assert launcher.reviewer_link_node_modules(copy, tmp_path) is False
    assert not (copy / "node_modules").is_symlink()
    assert launcher.reviewer_link_node_modules(tmp_path / "empty", None) is False


@pytest.mark.parametrize(
    "entry",
    [
        {"state": "not-installed", "reason": "no-lockfile"},
        {"state": "no-dependencies"},
        {"state": "installed", "directory": "/etc"},
        {"state": "installed", "directory": "../elsewhere"},
        {"state": "installed", "directory": "dependencies/missing"},
    ],
)
def test_node_an_untrustworthy_entry_is_ignored(
    launcher: ModuleType, tmp_path: Path, entry: Any
) -> None:
    assert launcher.reviewer_packet_node(_node_packet(launcher, tmp_path, entry)) is None


def test_node_a_symlinked_packet_folder_is_ignored(launcher: ModuleType, tmp_path: Path) -> None:
    packet = _node_packet(launcher, tmp_path)
    real = packet / "dependencies" / "node"
    real.rename(packet / "dependencies" / "elsewhere")
    real.symlink_to(packet / "dependencies" / "elsewhere")
    assert launcher.reviewer_packet_node(packet) is None


@NOT_ROOT
@pytest.mark.parametrize("runtime", ["node", "bun"])
def test_node_a_sandboxed_command_resolves_commonjs_and_esm_through_the_link(
    launcher: ModuleType, tmp_path: Path, runtime: str
) -> None:
    if shutil.which(runtime) is None:
        pytest.skip(f"{runtime} is not installed")
    packet = _node_packet(launcher, tmp_path)
    copy, _, extra = _claude_shell(launcher, tmp_path)
    assert launcher.reviewer_link_node_modules(copy, launcher.reviewer_packet_node(packet))
    (copy / "src").mkdir()
    (copy / "src" / "probe.mjs").write_text(
        'import esm from "esm-dep";\nimport { createRequire } from "node:module";\n'
        'import os from "node:os";\n'
        'const require = createRequire(import.meta.url);\n'
        'console.log(esm(), require("cjs-dep")(), os.tmpdir());\n', "utf-8")
    (copy / "src" / "probe.cjs").write_text(
        'console.log(require("cjs-dep")());\n', "utf-8")
    _sandbox_denies(launcher.reviewer_claude_shell_paths(copy)[1])
    env = _startup_env(tmp_path, **extra)
    command = f"{runtime} src/probe.mjs && {runtime} src/probe.cjs"
    out = _run_like_claude(_as_claude_2_1_311(command, _claude_sandbox_temp(tmp_path)), env, copy)
    assert out.split() == ["esm", "cjs", str(launcher.reviewer_claude_temp_dir(copy)), "cjs"]


def test_node_a_node_reached_through_a_link_puts_its_real_bin_first(
    launcher: ModuleType, tmp_path: Path
) -> None:
    real = tmp_path / "install" / "bin"
    real.mkdir(parents=True)
    (real / "node").write_text("#!/bin/sh\n", "utf-8")
    (real / "node").chmod(0o755)
    shims = tmp_path / "shims"
    shims.mkdir()
    (shims / "node").symlink_to(real / "node")
    assert launcher.reviewer_toolchain_front({"PATH": str(shims)}) == [real.resolve()]
    assert launcher.reviewer_toolchain_front({"PATH": str(real)}) == []
    assert launcher.reviewer_toolchain_front({"PATH": str(tmp_path / "none")}) == []
    script = launcher.reviewer_claude_shell_script(
        tmp_path / "sentinel", "token", path_front=[real])
    assert f'PATH={real}:"${{PATH-}}"' in script


def test_offline_the_shell_prefix_passes_the_virtual_env(launcher: ModuleType, tmp_path: Path) -> None:
    script = launcher.reviewer_claude_shell_script(tmp_path / "sentinel", "token")
    assert '${VIRTUAL_ENV+"VIRTUAL_ENV=$VIRTUAL_ENV"}' in script
    assert "VIRTUAL_ENV" in launcher.REVIEWER_ENVIRONMENT_ALLOWED
    assert "PYTHONPATH" not in launcher.REVIEWER_ENVIRONMENT_ALLOWED
    with_env = launcher.reviewer_claude_shell_script(
        tmp_path / "sentinel", "token", python_env=tmp_path / "python-env")
    line = next(item for item in with_env.splitlines() if item.startswith("exec /usr/bin/env -i"))
    assert line.index("${PATH+") < line.index(f"PATH={tmp_path / 'python-env' / 'bin'}:")


def _dart_packet(launcher: ModuleType, tmp_path: Path, entry: Any = None) -> Path:
    """A packet whose ``dependencies.json`` names saga's pub cache, holding package scripts a
    hostile package could ship, named after the vendor and git."""
    packet = tmp_path / "packet"
    cache = packet / "dependencies" / "dart" / "pub-cache"
    package = cache / "hosted" / "pub.dev" / "inert-1.0.0"
    (package / "lib").mkdir(parents=True)
    (package / "lib" / "inert.dart").write_text("int two() => 2;\n", "utf-8")
    (package / "bin").mkdir()
    for name in ("claude", "git", "dart"):
        (package / "bin" / name).write_text("#!/bin/sh\necho planted\n", "utf-8")
        (package / "bin" / name).chmod(0o755)
    (cache / "hosted-hashes").mkdir()
    record = {
        "schema": launcher.REVIEWER_DEPENDENCIES_SCHEMA,
        "dart": entry if entry is not None
        else {"state": "installed", "directory": "dependencies/dart/pub-cache",
              "sdk": {"version": "3.13.2"}},
    }
    (packet / "dependencies.json").write_text(json.dumps(record), "utf-8")
    return packet


def _dart_on_path(tmp_path: Path) -> tuple[str, Path]:
    """A Flutter-like layout on a PATH folder: ``bin/dart`` is a script, the SDK is below it."""
    flutter = tmp_path / "flutter"
    sdk = flutter / "bin" / "cache" / "dart-sdk"
    (sdk / "bin").mkdir(parents=True)
    (sdk / "bin" / "dart").write_bytes(b"\xcf\xfa\xed\xfe binary\n")
    (sdk / "bin" / "dart").chmod(0o755)
    (sdk / "version").write_text("3.13.2\n", "utf-8")
    (flutter / "bin" / "dart").write_text("#!/bin/sh\nexec git status\n", "utf-8")
    (flutter / "bin" / "dart").chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "dart").symlink_to(flutter / "bin" / "dart")
    return f"{tools}{os.pathsep}{os.environ.get('PATH', '')}", sdk.resolve()


def test_offline_the_reviewer_s_dart_is_the_sdk_and_its_packages_are_read_only(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    packet = _dart_packet(launcher, tmp_path)
    path, sdk = _dart_on_path(tmp_path)
    result, settings, env = _launch_with(launcher, repo, head, tmp_path, packet, PATH=path)
    copy = Path(result["scratch"]["path"])
    dart_env = launcher.reviewer_dart_env_dir(copy.parent)
    pub_cache = launcher.reviewer_dart_pub_cache_dir(copy)
    root = str(packet.resolve())
    # The vendor process keeps the operator's PATH: nothing from the packet or the launcher.
    assert env["PATH"].endswith(path)
    for part in env["PATH"].split(os.pathsep):
        assert not part.startswith(root) and not part.startswith(str(dart_env))
    for name in ("claude", "git"):
        found = shutil.which(name, path=env["PATH"])
        assert found is None or not Path(found).resolve().is_relative_to(packet.resolve())
    assert [item.name for item in (dart_env / "bin").iterdir()] == ["dart"]
    assert (dart_env / "bin" / "dart").resolve() == sdk / "bin" / "dart"
    cache = (packet / "dependencies" / "dart" / "pub-cache").resolve()
    assert sorted(item.name for item in pub_cache.iterdir()) == ["hosted", "hosted-hashes"]
    assert (pub_cache / "hosted").resolve() == cache / "hosted"
    prefix = Path(settings["env"][launcher.REVIEWER_SHELL_PREFIX]).read_text("utf-8")
    line = next(item for item in prefix.splitlines() if item.startswith("exec /usr/bin/env -i"))
    assert f"PUB_CACHE={pub_cache}" in line
    assert "DASH__SUPPRESS_ANALYTICS=true" in line and "PUB_MAX_HTTP_RETRIES=0" in line
    # One PATH assignment; node's real bin may come first (reviewer_toolchain_front).
    assigned = line.split(" PATH=", 1)[1].split(':"${PATH-}"', 1)[0].strip("'")
    assert str(dart_env / "bin") in assigned.split(os.pathsep) and root not in line
    filesystem = settings["sandbox"]["filesystem"]
    for allowed in (str(dart_env.resolve()), str(cache), str(sdk)):
        assert allowed in filesystem["allowRead"] and allowed in filesystem["denyWrite"]
    assert str(pub_cache.parent) in filesystem["allowWrite"]
    # Claude's Edit and Write run outside the command sandbox, under Edit(/<temp>/**): the
    # cache's links into the packet, and the packet's cache itself, are denied to them.
    deny = settings["permissions"]["deny"]
    for path in (pub_cache / "hosted", pub_cache / "hosted-hashes", cache, dart_env.resolve()):
        assert f"Edit(/{path}/**)" in deny, path


def test_offline_python_and_dart_share_one_path_assignment(
    launcher: ModuleType, tmp_path: Path
) -> None:
    script = launcher.reviewer_claude_shell_script(
        tmp_path / "sentinel", "token", python_env=tmp_path / "python-env",
        dart_env=(tmp_path / "dart-env", tmp_path / "temp" / "saga-pub-cache"))
    line = next(item for item in script.splitlines() if item.startswith("exec /usr/bin/env -i"))
    assert line.count(" PATH=") == 1
    assert f"PATH={tmp_path / 'python-env' / 'bin'}:{tmp_path / 'dart-env' / 'bin'}:" in line


@pytest.mark.parametrize(
    "entry",
    [
        {"state": "not-installed", "reason": "network"},
        {"state": "installed", "directory": "/etc", "sdk": {"version": "3.13.2"}},
        {"state": "installed", "directory": "../elsewhere", "sdk": {"version": "3.13.2"}},
        {"state": "installed", "directory": "dependencies/missing", "sdk": {"version": "3.13.2"}},
    ],
)
def test_offline_an_untrustworthy_dart_entry_is_ignored(
    launcher: ModuleType, tmp_path: Path, entry: Any
) -> None:
    packet = _dart_packet(launcher, tmp_path, entry)
    assert launcher.reviewer_packet_dart(packet) is None
    assert launcher.reviewer_dart_env(tmp_path / "root", tmp_path / "copy", None, os.environ) is None


def test_offline_no_dart_sdk_means_no_dart_folder(
    launcher: ModuleType, tmp_path: Path
) -> None:
    packet = _dart_packet(launcher, tmp_path)
    packages = launcher.reviewer_packet_dart(packet)
    assert packages is not None and packages[1] == "3.13.2"
    assert launcher.reviewer_dart_env(tmp_path / "root", tmp_path / "copy", packages,
                                      {"PATH": str(tmp_path / "empty")}) is None


def test_offline_an_sdk_of_another_release_means_no_dart_folder(
    launcher: ModuleType, tmp_path: Path
) -> None:
    packet = _dart_packet(launcher, tmp_path, {
        "state": "installed", "directory": "dependencies/dart/pub-cache",
        "sdk": {"version": "3.12.0"}})
    path, _sdk = _dart_on_path(tmp_path)
    packages = launcher.reviewer_packet_dart(packet)
    assert packages is not None
    assert launcher.reviewer_dart_env(tmp_path / "root", tmp_path / "copy", packages,
                                      {"PATH": path, "HOME": str(tmp_path / "home")}) is None
    assert not launcher.reviewer_dart_env_dir(tmp_path / "root").exists()


def test_offline_an_sdk_that_cannot_be_read_back_puts_no_dart_on_path(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """An SDK under a credential path cannot be allowed back, so its dart could not run."""
    home = tmp_path / "home"
    sdk = home / ".config" / "gh" / "dart-sdk"
    (sdk / "bin").mkdir(parents=True)
    (sdk / "bin" / "dart").write_bytes(b"\xcf\xfa\xed\xfe binary\n")
    (sdk / "bin" / "dart").chmod(0o755)
    (sdk / "version").write_text("3.13.2\n", "utf-8")
    packages = launcher.reviewer_packet_dart(_dart_packet(launcher, tmp_path))
    assert launcher.reviewer_dart_env(tmp_path / "root", tmp_path / "copy", packages,
                                      {"PATH": str(sdk / "bin"), "HOME": str(home)}) is None


def test_offline_the_shell_prefix_passes_the_cargo_variables_to_sandboxed_commands(
    launcher: ModuleType, tmp_path: Path
) -> None:
    script = launcher.reviewer_claude_shell_script(tmp_path / "sentinel", "token")
    for name in ("CARGO_HOME", "CARGO_NET_OFFLINE"):
        assert f'${{{name}+"{name}=${name}"}}' in script
        assert not launcher.REVIEWER_CREDENTIAL_NAME.search(name)


def test_offline_grok_grants_the_dependency_paths_read_only(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, packet = tmp_path / "copy", tmp_path / "packet"
    copy.mkdir()
    packet.mkdir()
    extra = [str(tmp_path / "cargo-home"), str(packet / "dependencies" / "rust")]
    settings = launcher.reviewer_grok_settings(
        copy, packet, {"HOME": str(tmp_path / "home")}, toolchain=[], read_only=extra
    )
    assert settings["profile"]["read_only"][-2:] == extra
    assert settings["profile"]["restrict_network"] is True


def test_offline_a_build_s_target_and_new_lock_are_clutter_but_a_tracked_lock_is_not(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    (copy / "src").mkdir(parents=True)
    (copy / "src" / "lib.rs").write_text("pub fn a() {}\n")
    (copy / "crate").mkdir()
    (copy / "crate" / "Cargo.lock").write_text("version = 4\n")
    manifest = launcher._reviewer_manifest(copy)
    (copy / "target" / "debug").mkdir(parents=True)
    (copy / "target" / "debug" / "example").write_text("binary\n")
    (copy / "Cargo.lock").write_text("version = 4\n")
    (copy / "crate" / "Cargo.lock").write_text("version = 4\n# changed\n")
    (copy / "tests").mkdir()
    (copy / "tests" / "repro.rs").write_text("#[test]\nfn t() {}\n")
    changes = launcher.reviewer_scratch_changes(copy, manifest)
    assert changes["added"] == ["tests/repro.rs"]
    assert changes["modified"] == ["crate/Cargo.lock"]


# ----------------------------------------------------------- the sandboxed shell's umask


def _run_prefix(
    launcher: ModuleType, tmp_path: Path, token: str, command: str, parent_umask: int
) -> subprocess.CompletedProcess[str]:
    """Run *command* through a real prefix script, in a child whose own umask is *parent_umask*."""
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("token", "utf-8")
    prefix = tmp_path / "reviewer-shell.sh"
    prefix.write_text(launcher.reviewer_claude_shell_script(sentinel, token), "utf-8")
    prefix.chmod(0o755)
    return subprocess.run(
        [str(prefix), command], cwd=tmp_path, capture_output=True, text=True, check=False,
        umask=parent_umask,
    )


def test_umask_the_sandboxed_branch_sets_022_before_it_runs_the_command(
    launcher: ModuleType, tmp_path: Path
) -> None:
    script = launcher.reviewer_claude_shell_script(Path("/example/sentinel"), "token")
    outside, inside = script.split("\nfi\n", 1)
    assert "umask" not in outside
    assert "umask 022 || exit 1\n" in inside
    assert inside.index("umask 022") < inside.index("exec /usr/bin/env -i")


def test_umask_a_file_made_in_the_sandbox_is_world_readable_whatever_the_parent_mask(
    launcher: ModuleType, tmp_path: Path
) -> None:
    # A wrong token takes the sandboxed branch, as a denied sentinel read does.
    made = _run_prefix(launcher, tmp_path, "other", "touch made; umask", 0o077)
    assert made.returncode == 0, made.stderr
    assert (tmp_path / "made").stat().st_mode & 0o777 == 0o644
    assert made.stdout.strip() == "0022"


def test_umask_a_command_outside_the_sandbox_keeps_the_parent_mask(
    launcher: ModuleType, tmp_path: Path
) -> None:
    made = _run_prefix(launcher, tmp_path, "token", "touch made; umask", 0o077)
    assert made.returncode == 0, made.stderr
    assert (tmp_path / "made").stat().st_mode & 0o777 == 0o600
    assert made.stdout.strip() == "0077"


@pytest.mark.skipif(os.name != "posix", reason="umask is a POSIX setting")
def test_umask_the_exported_copy_has_022_modes_under_a_stricter_launcher_mask(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    previous = os.umask(0o077)
    try:
        launcher.reviewer_export_head(repo, head, tmp_path / "copy")
    finally:
        os.umask(previous)
    assert (tmp_path / "copy" / "src" / "app.py").stat().st_mode & 0o777 == 0o644
