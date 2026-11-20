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


def _contract_launcher() -> ModuleType:
    """The launcher module at collection time, for parametrising over its tables."""
    return sys.modules.get("_agent_launcher_contract") or _load(LAUNCHER, "_agent_launcher_contract")


# --------------------------------------------------------------------------- the targeted reviewer
# Issue #158: `launcher.py review` starts saga's targeted reviewer headless in a sandboxed scratch
# copy, and `reviewer-probe` checks the sandbox live. Nothing here starts a real session: the
# session is a fake binary on PATH or an injected callable.

SAGA_PROMPT = REPO / "plugins" / "reviews" / "references" / "targeted-reviewer-prompt.md"
SAGA_SCHEMA = REPO / "plugins" / "reviews" / "references" / "targeted-reviewer-answer.schema.json"
SAGA_ANSWER_CLI = REPO / "plugins" / "reviews" / "scripts" / "reviewer_answer.py"
SAGA_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reviewer_answer"
ANSWER = json.loads((SAGA_FIXTURES / "answer.json").read_text(encoding="utf-8"))


def _claude_result(final: str, **over: Any) -> str:
    """A recorded `claude -p --output-format json` result, as Claude Code 2.1.292 printed it."""
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 6154,
        "num_turns": 2,
        "result": final,
        "session_id": "00000000-0000-4000-8000-000000000000",
        "total_cost_usd": 0.0705,
        "usage": {
            "input_tokens": 18,
            "output_tokens": 835,
            "cache_read_input_tokens": 49907,
            "cache_creation_input_tokens": 14292,
        },
        "modelUsage": {"claude-example-model": {"inputTokens": 18, "outputTokens": 835}},
        "permission_denials": [],
    }
    result.update(over)
    return json.dumps(result)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def reviewed_repo(tmp_path: Path) -> tuple[Path, str]:
    """A small repository with one commit, plus an uncommitted file that must not be copied."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "tests" / "test_app.py").write_text("def test_reviewer_add():\n    assert True\n")
    (repo / "CLAUDE.md").write_text("Project rules.\n")
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "base")
    (repo / "uncommitted-secret.txt").write_text("not for the copy\n")
    return repo, _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A throwaway home with a user CLAUDE.md, one import, settings and installed plugins."""
    home = tmp_path / "home"
    claude = home / ".claude"
    (claude / "plugins").mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("User rules.\n@RULES.md\n")
    (claude / "RULES.md").write_text("Imported rules.\n")
    (claude / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"saga@example": True, "old@example": False}})
    )
    (claude / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {"saga@example": [
            {"scope": "user", "version": "1.3.0", "gitCommitSha": "abc"}
        ]}})
    )
    return home


def _env(home: Path, **extra: str) -> dict[str, str]:
    return {"HOME": str(home), "PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", **extra}


def _request(launcher: ModuleType, repo: Path, head: str, tmp_path: Path, **over: Any) -> Any:
    packet = tmp_path / "packet"
    packet.mkdir(exist_ok=True)
    values: dict[str, Any] = {
        "vendor": "claude", "model": "opus", "effort": "high", "repo": repo, "head": head,
        "packet": packet, "prompt": SAGA_PROMPT, "schema": SAGA_SCHEMA, "out": tmp_path / "out",
        "work_root": tmp_path / "reviews", "max_budget_usd": "5",
    }
    values.update(over)
    return launcher.ReviewerRequest(**values)


class FakeSession:
    """Stands in for the vendor session: records what it was given, then acts in the copy."""

    def __init__(self, stdout: str, *, code: int = 0, act: Callable[[Path], None] | None = None):
        self.stdout, self.code, self.act = stdout, code, act
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        self.calls.append({"argv": argv, "stdin": stdin, "cwd": cwd, "env": dict(env)})
        if self.act:
            self.act(cwd)
        return subprocess.CompletedProcess(argv, self.code, self.stdout, "")


def test_reviewer_claude_argv_is_pinned(launcher: ModuleType, tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    assert launcher.reviewer_claude_argv("opus", "high", settings, max_budget_usd="5") == [
        "claude", "-p", "--model", "opus", "--effort", "high",
        "--permission-mode", "dontAsk", "--settings", str(settings),
        "--output-format", "json", "--no-session-persistence", "--max-budget-usd", "5",
    ]


def test_reviewer_read_confinement_settings_are_pinned(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy, packet = tmp_path / "copy", tmp_path / "packet"
    copy.mkdir()
    packet.mkdir()
    env = {"HOME": "/home/example", "GH_TOKEN": "inert-example", "PATH": "/usr/bin"}
    settings = launcher.reviewer_claude_settings(copy, packet, env, toolchain=[], platform="darwin")
    credentials = list(launcher.REVIEWER_CREDENTIAL_PATHS)
    # Issue #225: the shell prefix that keeps start-up exports out, and its denied sentinel.
    root = copy.resolve().parent
    prefix, sentinel = root / "shell" / "reviewer-shell.sh", root / "unsandboxed"
    temp = root / "tmp"  # the reviewer's own writable temp folder, beside the copy
    assert settings == {
        "env": {"CLAUDE_CODE_SHELL_PREFIX": str(prefix)},
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {
                "denyWrite": ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders"],
                "denyRead": ["~", str(sentinel)],
                "allowRead": [
                    str(copy.resolve()), str(packet.resolve()), str(prefix.parent), str(temp),
                ],
                "allowWrite": [str(temp)],
            },
            "network": {"strictAllowlist": True, "allowedDomains": []},
            "credentials": {"envVars": [{"name": "GH_TOKEN", "mode": "deny"}]},
        },
        "permissions": {
            "allow": [
                "Bash", "Edit(./**)", f"Edit(/{temp}/**)", f"Read(/{packet.resolve()}/**)",
            ],
            "deny": ["WebFetch", "WebSearch", "mcp__*"] + [f"Read({p})" for p in credentials]
            # Claude's file tools never write the copy's node_modules link or what it reaches.
            + ["Edit(./node_modules)", "Edit(./node_modules/**)"],
        },
    }
    linux = launcher.reviewer_claude_settings(copy, packet, env, toolchain=[], platform="linux")
    assert linux["sandbox"]["filesystem"]["denyWrite"] == ["/tmp", "/var/tmp"]


def test_reviewer_read_confinement_the_credential_list_names_the_card_s_files(
    launcher: ModuleType,
) -> None:
    assert {
        "~/.ssh", "~/.aws", "~/.config/gh", "~/.git-credentials", "~/.pypirc",
        "~/.cargo/credentials", "~/.cargo/credentials.toml", "~/.terraform.d", "~/.vault-token",
        "~/.config/hub", "~/.local/share/keyrings", "~/.npmrc",
    } <= set(launcher.REVIEWER_CREDENTIAL_PATHS)


def _toolchain_home(tmp_path: Path) -> tuple[Path, Path]:
    """A fake home whose ``~/.local/bin/python3`` links into a uv-managed interpreter."""
    home = tmp_path / "home"
    real = home / ".local" / "share" / "uv" / "python" / "cpython-x" / "bin"
    real.mkdir(parents=True)
    (real.parent / "lib").mkdir()
    (real / "python3").write_text("#!/bin/sh\n")
    (real / "python3").chmod(0o755)
    shim = home / ".local" / "bin"
    shim.mkdir(parents=True)
    (shim / "python3").symlink_to(real / "python3")
    return home, shim


def test_reviewer_read_confinement_allow_read_is_only_copy_packet_and_named_toolchain(
    launcher: ModuleType, tmp_path: Path
) -> None:
    home, shim = _toolchain_home(tmp_path)
    env = {"HOME": str(home), "PATH": str(shim)}
    allowed, dropped = launcher.reviewer_toolchain_paths(env)
    interpreter = home / ".local" / "share" / "uv" / "python" / "cpython-x"
    assert [item["path"] for item in allowed] == [
        str(interpreter / "bin"), str(interpreter / "lib")
    ]
    assert all("python3" in item["reason"] for item in allowed)
    assert dropped == [{"path": str(home / ".local"),
                        "reason": f"{home / '.local'} is the shared root ~/.local"}]
    copy, packet = tmp_path / "copy", tmp_path / "packet"
    copy.mkdir()
    packet.mkdir()
    settings = launcher.reviewer_claude_settings(copy, packet, env)
    assert settings["sandbox"]["filesystem"]["allowRead"] == [
        str(copy.resolve()), str(packet.resolve()), str(copy.resolve().parent / "shell"),
        str(interpreter / "bin"), str(interpreter / "lib"), str(copy.resolve().parent / "tmp"),
    ]


def test_reviewer_read_confinement_a_toolchain_prefix_is_never_allowed_back_whole(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """A tool home can keep its own ``.env`` beside ``bin/``; only ``bin`` and ``lib`` come back."""
    home = tmp_path / "home"
    prefix = home / ".sometool"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib").mkdir()
    (prefix / ".env").write_text("EXAMPLE=inert-example\n")
    (prefix / "bin" / "node").write_text("#!/bin/sh\n")
    (prefix / "bin" / "node").chmod(0o755)
    allowed, _ = launcher.reviewer_toolchain_paths({"HOME": str(home), "PATH": str(prefix / "bin")})
    paths = [item["path"] for item in allowed]
    assert paths == [str(prefix / "bin"), str(prefix / "lib")]
    assert str(prefix) not in paths and not any(p.endswith(".env") for p in paths)


def test_reviewer_read_confinement_a_virtual_environment_s_marker_is_allowed_back(
    launcher: ModuleType, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    venv = home / "work" / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (venv / "bin" / "python3").write_text("#!/bin/sh\n")
    (venv / "bin" / "python3").chmod(0o755)
    allowed, _ = launcher.reviewer_toolchain_paths({"HOME": str(home), "PATH": str(venv / "bin")})
    assert [item["path"] for item in allowed] == [str(venv / "bin"), str(venv / "pyvenv.cfg")]


def test_reviewer_read_confinement_an_interpreter_outside_home_adds_nothing(
    launcher: ModuleType, tmp_path: Path
) -> None:
    usr = tmp_path / "usr" / "bin"
    usr.mkdir(parents=True)
    (usr / "python3").write_text("#!/bin/sh\n")
    (usr / "python3").chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    assert launcher.reviewer_toolchain_paths({"HOME": str(home), "PATH": str(usr)}) == ([], [])


@pytest.mark.parametrize(
    ("relative", "why"),
    [(".cargo/bin/node", "~/.cargo/credentials"), (".ssh/bin/python3", "~/.ssh")],
)
def test_reviewer_read_confinement_a_toolchain_prefix_holding_credentials_is_dropped(
    launcher: ModuleType, tmp_path: Path, relative: str, why: str
) -> None:
    home = tmp_path / "home"
    binary = home / relative
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    allowed, dropped = launcher.reviewer_toolchain_paths(
        {"HOME": str(home), "PATH": str(binary.parent)}
    )
    assert allowed == []
    assert [item["path"] for item in dropped] == [str(binary.parent.parent)]
    assert why in dropped[0]["reason"]


def _reopening_packets(home: Path) -> list[Path]:
    (home / ".ssh" / "sub").mkdir(parents=True)
    (home / ".aws").mkdir()
    (home / ".config").mkdir()
    (home / "elsewhere").mkdir()
    (home / ".local" / "share" / "keyrings").mkdir(parents=True)
    (home / "aws-link").symlink_to(home / ".aws")
    return [
        home, home / ".config", home / ".local" / "share", home / ".ssh", home / ".ssh" / "sub",
        home / ".local" / "share" / "keyrings", home / "elsewhere" / ".." / ".ssh",
        home / "aws-link",
    ]


def test_reviewer_read_confinement_a_packet_that_reopens_home_is_refused(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    for packet in _reopening_packets(home):
        packet_dir = Path(os.path.normpath(packet))
        packet_dir.mkdir(parents=True, exist_ok=True)
        session = FakeSession("{}")
        with pytest.raises(launcher.ReviewerRefused, match="cannot be allowed back"):
            launcher.reviewer_launch(
                _request(launcher, repo, head, tmp_path, packet=packet), env=_env(home),
                session=session,
            )
        assert session.calls == [], packet
    assert not (tmp_path / "reviews").exists()
    assert launcher.reviewer_allowed_read_problem(home / ".cache" / "x" / "copy", home) is None


def test_reviewer_read_confinement_the_launch_names_every_allowed_read(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(_claude_result(json.dumps(ANSWER)))
    result, _ = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home), session=session
    )
    allowed = result["sandbox_reads"]["allowed"]
    assert [item["path"] for item in allowed[:2]] == [
        str(Path(result["scratch"]["path"]).resolve()), str((tmp_path / "packet").resolve())
    ]
    assert all(item["reason"] for item in allowed)
    settings = json.loads(
        Path(session.calls[0]["argv"][session.calls[0]["argv"].index("--settings") + 1]).read_text()
    )
    root = Path(result["scratch"]["path"]).resolve().parent
    assert settings["sandbox"]["filesystem"]["denyRead"] == ["~", str(root / "unsandboxed")]
    assert settings["sandbox"]["filesystem"]["allowRead"] == [item["path"] for item in allowed]


def test_reviewer_read_confinement_a_user_allow_read_still_refuses_the_launch(
    launcher: ModuleType, home: Path
) -> None:
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"sandbox": {"filesystem": {"allowRead": ["~"]}}})
    )
    assert "settings.json sets sandbox.filesystem.allowRead" in launcher.reviewer_claude_widening(
        _env(home)
    )


@pytest.mark.parametrize(
    ("name", "denied"),
    [("EXAMPLE_PLAIN", True), ("HONCHO_WORKSPACE", True), ("GH_TOKEN", True),
     ("TYPESAFE_API_KEY", True), ("SSH_AUTH_SOCK", True), ("LC_PLAIN", True),
     ("LC_TOKEN", True), ("PATH", False), ("HOME", False), ("LANG", False), ("LC_ALL", False),
     ("GIT_CONFIG_GLOBAL", False)],
)
def test_reviewer_environment_allowlist_denies_every_name_off_the_list(
    launcher: ModuleType, name: str, denied: bool
) -> None:
    assert (name in launcher.reviewer_denied_variables({name: "inert-example"})) is denied


def test_reviewer_environment_allowlist_names_no_credential_looking_variable(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not [n for n in launcher.REVIEWER_ENVIRONMENT_ALLOWED
                if launcher.REVIEWER_CREDENTIAL_NAME.search(n)]
    monkeypatch.setattr(
        launcher, "REVIEWER_ENVIRONMENT_ALLOWED",
        (*launcher.REVIEWER_ENVIRONMENT_ALLOWED, "EXAMPLE_TOKEN"),
    )
    assert launcher.reviewer_denied_variables({"EXAMPLE_TOKEN": "inert-example"}) == [
        "EXAMPLE_TOKEN"
    ]


def test_reviewer_environment_allowlist_an_ordinary_named_variable_is_absent_from_commands(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(_claude_result(json.dumps(ANSWER)))
    launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path),
        env=_env(home, EXAMPLE_PLAIN="inert-example"), session=session,
    )
    argv = session.calls[0]["argv"]
    settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
    denied = {v["name"] for v in settings["sandbox"]["credentials"]["envVars"]}
    assert "EXAMPLE_PLAIN" in denied
    assert not denied & {"PATH", "HOME", "LANG", "GIT_CONFIG_GLOBAL"}


def test_reviewer_environment_allowlist_git_reads_no_global_config(launcher: ModuleType) -> None:
    kept = launcher.reviewer_session_environment(
        {"GIT_CONFIG_GLOBAL": "/home/example/.gitconfig", "ANTHROPIC_API_KEY": "inert-example"}
    )
    assert kept == {"GIT_CONFIG_GLOBAL": os.devnull}


def test_reviewer_the_forbidden_flag_table_names_exactly_the_launcher_vendors(launcher: ModuleType) -> None:
    assert set(launcher.REVIEWER_FORBIDDEN_FLAGS) == set(launcher.VENDOR_FLAGS)
    assert all(launcher.REVIEWER_FORBIDDEN_FLAGS.values())


def test_reviewer_no_reviewer_recipe_turns_off_configuration_or_its_sandbox(
    launcher: ModuleType, tmp_path: Path
) -> None:
    forbidden = {flag for flags in launcher.REVIEWER_FORBIDDEN_FLAGS.values() for flag in flags}
    recipes = {**launcher.REVIEWER_CANDIDATES, **launcher.REVIEWER_RECIPES}
    for vendor, recipe in recipes.items():
        argv = recipe.argv(
            "model", "high", tmp_path / "settings.json",
            max_budget_usd="5" if recipe.takes_ceiling else None,
            executable=tmp_path / "bin" / vendor, prompt_path=tmp_path / "prompt.md",
        )
        assert not forbidden & set(argv), (vendor, forbidden & set(argv))
        settings = recipe.settings(tmp_path, tmp_path, {}, toolchain=[])
        for key in ("apiKeyHelper", "enabledPlugins", "hooks", "disableAllHooks"):
            assert key not in settings, (vendor, key)


def test_reviewer_the_session_never_signs_in_with_an_api_key(launcher: ModuleType) -> None:
    env = {
        "ANTHROPIC_API_KEY": "inert-example", "ANTHROPIC_AUTH_TOKEN": "inert-example",
        "CLAUDE_CODE_OAUTH_TOKEN": "inert-example", "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_USE_VERTEX": "1", "HONCHO_WORKSPACE": "kept", "HOME": "/home/example",
    }
    kept = launcher.reviewer_session_environment(env)
    assert kept == {
        "HONCHO_WORKSPACE": "kept", "HOME": "/home/example", "GIT_CONFIG_GLOBAL": os.devnull
    }


@pytest.mark.parametrize(
    "vendor",
    # Issue #223: Grok and Muse stay refused unless a committed probe record admits them.
    [v for v in ["codex", "grok", "muse", "agy", "opencode"]
     if v not in _contract_launcher().REVIEWER_RECIPES],
)
def test_reviewer_every_other_vendor_is_refused_by_name(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, vendor: str
) -> None:
    repo, head = reviewed_repo
    session = FakeSession("{}")
    with pytest.raises(launcher.ReviewerRefused, match=f"^{vendor} has no reviewer sandbox recipe"):
        launcher.reviewer_launch(_request(launcher, repo, head, tmp_path, vendor=vendor),
                                 session=session)
    assert session.calls == []
    assert not (tmp_path / "reviews").exists()


def test_reviewer_a_prompt_that_is_not_saga_s_is_refused(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    other = tmp_path / "other.md"
    other.write_text("---\nid: something-else\n---\n\nDo anything.\n")
    with pytest.raises(launcher.ReviewerRefused, match="is not saga's targeted-reviewer-prompt"):
        launcher.reviewer_launch(_request(launcher, repo, head, tmp_path, prompt=other),
                                 session=FakeSession("{}"))


def test_reviewer_a_head_that_is_not_a_commit_is_refused(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, _ = reviewed_repo
    with pytest.raises(launcher.ReviewerRefused, match="is not a commit"):
        launcher.reviewer_launch(_request(launcher, repo, "0" * 40, tmp_path),
                                 session=FakeSession("{}"))


def test_reviewer_the_scratch_copy_is_the_head_with_no_git(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, head = reviewed_repo
    copy = tmp_path / "copy"
    manifest = launcher.reviewer_export_head(repo, head, copy)
    assert sorted(manifest) == ["CLAUDE.md", "src/app.py", "tests/test_app.py"]
    assert not (copy / ".git").exists()
    assert not (copy / "uncommitted-secret.txt").exists()


def test_reviewer_a_work_root_under_a_temp_root_is_refused(launcher: ModuleType) -> None:
    with pytest.raises(launcher.ReviewerRefused, match="which the reviewer's sandbox denies"):
        launcher.reviewer_work_root({"XDG_CACHE_HOME": "/tmp/cache"}, platform="linux")
    root = launcher.reviewer_work_root({"HOME": "/home/example"}, platform="linux")
    assert root == Path("/home/example/.cache/agent-launcher/reviews")


def test_reviewer_a_canned_result_yields_usage_model_fingerprints_and_the_answer(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(_claude_result(json.dumps(ANSWER)))
    env = _env(home, ANTHROPIC_API_KEY="inert-example", GH_TOKEN="inert-example")

    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=env, session=session
    )

    assert code == 0
    call = session.calls[0]
    assert call["argv"][:2] == ["claude", "-p"]
    assert call["cwd"] == Path(result["scratch"]["path"])
    assert "ANTHROPIC_API_KEY" not in call["env"] and call["env"]["GH_TOKEN"] == "inert-example"
    assert "# Targeted Reviewer" in call["stdin"] and "# The targeted reviewer" in call["stdin"]
    assert "The open search's cap on findings: 5" in call["stdin"]
    settings = json.loads(Path(call["argv"][call["argv"].index("--settings") + 1]).read_text())
    assert {"name": "GH_TOKEN", "mode": "deny"} in settings["sandbox"]["credentials"]["envVars"]
    assert result["schema"] == "targeted_reviewer_launch.v1"
    assert result["vendor"] == "claude"
    assert result["model"] == {"requested": "opus", "resolved": ["claude-example-model"]}
    assert result["usage"] == {
        "input_tokens": 18, "output_tokens": 835, "cache_read_input_tokens": 49907,
        "cache_creation_input_tokens": 14292, "cost_usd": 0.0705, "seconds": 6.154,
        "turns": 2, "session_id": "00000000-0000-4000-8000-000000000000",
    }
    assert result["prompt_sha256"] == hashlib.sha256(SAGA_PROMPT.read_bytes()).hexdigest()
    assert result["schema_sha256"] == hashlib.sha256(SAGA_SCHEMA.read_bytes()).hexdigest()
    assert len(result["configuration"]["fingerprint"]) == 64
    assert "plugin:saga@example" in result["configuration"]["sources"]
    assert not any("/" in label.split(":", 1)[0] for label in result["configuration"]["sources"])
    assert json.loads((tmp_path / "out" / "answer.json").read_text()) == ANSWER
    assert json.loads((tmp_path / "out" / "result.json").read_text()) == result


def test_reviewer_the_launch_runs_a_real_process_with_the_copy_as_its_directory(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    """The whole path through a fake `claude` on PATH: argv, stdin, cwd and environment."""
    repo, head = reviewed_repo
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "seen.json"
    fake = bin_dir / "claude"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('9.9.9 (Claude Code)'); sys.exit(0)\n"
        "stdin = sys.stdin.read()\n"
        f"json.dump({{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': stdin,\n"
        f"           'api_key': 'ANTHROPIC_API_KEY' in os.environ}}, open({str(record)!r}, 'w'))\n"
        f"print({_claude_result(json.dumps(ANSWER))!r})\n"
    )
    fake.chmod(0o755)
    env = _env(home, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               ANTHROPIC_API_KEY="inert-example")

    result, code = launcher.reviewer_launch(_request(launcher, repo, head, tmp_path), env=env)

    seen = json.loads(record.read_text())
    assert code == 0
    assert seen["argv"][0] == "-p" and seen["api_key"] is False
    assert Path(seen["cwd"]).resolve() == Path(result["scratch"]["path"]).resolve()
    assert "# The targeted reviewer" in seen["stdin"]
    assert result["vendor_version"] == "9.9.9 (Claude Code)"


def test_reviewer_a_fenced_final_message_still_parses(launcher: ModuleType) -> None:
    answer, error = launcher.reviewer_extract_answer("```json\n" + json.dumps(ANSWER) + "\n```")
    assert (answer, error) == (ANSWER, None)


def test_reviewer_claude_argv_passes_the_answer_schema_before_the_ceiling(
    launcher: ModuleType, tmp_path: Path
) -> None:
    schema = json.dumps({"type": "object", "required": ["a"]}, separators=(",", ":"))
    argv = launcher.reviewer_claude_argv(
        "opus", "high", tmp_path / "s.json", max_budget_usd="5", answer_schema=schema
    )
    assert argv[argv.index("--json-schema") + 1] == schema
    assert argv[-2:] == ["--max-budget-usd", "5"]
    assert "--json-schema" not in launcher.reviewer_claude_argv(
        "opus", "high", tmp_path / "s.json", max_budget_usd="5"
    )


def test_reviewer_claude_argv_drops_the_schema_uri_claude_cannot_resolve(
    launcher: ModuleType, tmp_path: Path
) -> None:
    schema = json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://example.invalid/x",
        "type": "object", "$defs": {"a": {"type": "string"}},
    })
    argv = launcher.reviewer_claude_argv(
        "opus", "high", tmp_path / "s.json", max_budget_usd="5", answer_schema=schema
    )
    assert json.loads(argv[argv.index("--json-schema") + 1]) == {
        "type": "object", "$defs": {"a": {"type": "string"}},
    }


def test_reviewer_other_vendors_take_the_answer_schema_keyword_and_ignore_it(
    launcher: ModuleType, tmp_path: Path
) -> None:
    exe, prompt = tmp_path / "bin", tmp_path / "message.md"
    for build in (launcher.reviewer_grok_argv, launcher.reviewer_muse_argv):
        plain = build("m", "high", tmp_path / "s", executable=exe, prompt_path=prompt)
        with_schema = build(
            "m", "high", tmp_path / "s", executable=exe, prompt_path=prompt, answer_schema="{}"
        )
        assert plain == with_schema and "--json-schema" not in with_schema


def test_reviewer_launch_hands_claude_the_request_schema_and_reads_structured_output(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    session = FakeSession(_claude_result("Done, see the structured output.",
                                         structured_output=ANSWER))
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home), session=session
    )
    argv = session.calls[0]["argv"]
    full = json.loads(SAGA_SCHEMA.read_text(encoding="utf-8"))
    passed = json.loads(argv[argv.index("--json-schema") + 1])
    # Claude 2.1.301 refuses a schema that declares the 2020-12 `$schema` URI, so those two
    # keys are dropped and nothing else changes.
    assert passed == {k: v for k, v in full.items() if k not in ("$schema", "$id")}
    assert "$schema" in full and "$schema" not in passed and "$id" not in passed
    assert code == 0 and result["answer_source"] == "structured_output"
    assert result["final_message"] is None
    written = json.loads((tmp_path / "out" / "answer.json").read_text())
    assert written == ANSWER


def test_reviewer_structured_output_wins_over_a_final_message_that_is_prose(
    launcher: ModuleType,
) -> None:
    parsed = launcher.reviewer_parse_claude_result(
        _claude_result("I reviewed it.", structured_output=ANSWER)
    )
    assert parsed["structured"] == ANSWER
    assert launcher.reviewer_read_answer(parsed) == (ANSWER, "structured_output", None)


def test_reviewer_a_missing_structured_output_key_falls_back_to_the_final_message(
    launcher: ModuleType,
) -> None:
    parsed = launcher.reviewer_parse_claude_result(_claude_result(json.dumps(ANSWER)))
    assert parsed["structured"] is None
    assert launcher.reviewer_read_answer(parsed) == (ANSWER, "final_message", None)


def test_reviewer_a_whole_message_bare_or_fenced_object_is_still_read(launcher: ModuleType) -> None:
    for final in (json.dumps(ANSWER), "```json\n" + json.dumps(ANSWER) + "\n```"):
        parsed = {"final": final, "structured": None}
        assert launcher.reviewer_read_answer(parsed) == (ANSWER, "final_message", None)


def test_reviewer_an_example_object_quoted_before_the_answer_is_refused_and_kept(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    example = {"schema": "targeted_reviewer_answer.v1", "items": [], "findings": []}
    # The prompt's own example object, then the real answer after it, all inside prose.
    final = ("The prompt shows this shape:\n\n```json\n" + json.dumps(example) + "\n```\n\n"
             "My answer: " + json.dumps(ANSWER))
    assert launcher.reviewer_read_answer({"final": final, "structured": None}) == (
        None, None, "the final message is not JSON"
    )
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home),
        session=FakeSession(_claude_result(final)),
    )
    kept = result["final_message"]
    assert code == 3 and result["answer_path"] is None and result["answer_source"] is None
    assert result["error"] == "the final message is not JSON"
    assert Path(kept["path"]).read_text() == final
    assert not (tmp_path / "out" / "answer.json").exists()


def test_reviewer_an_unreadable_answer_keeps_the_final_message_beside_result_json(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    prose = "I could not finish the review."
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home),
        session=FakeSession(_claude_result(prose)),
    )
    kept = result["final_message"]
    assert code == 3 and result["answer_source"] is None
    assert result["error"] == "the final message is not JSON"
    assert Path(kept["path"]) == tmp_path / "out" / "final-message.txt"
    assert Path(kept["path"]).read_text() == prose
    assert kept["bytes"] == len(prose) and kept["truncated"] is False
    assert not Path(kept["path"]).resolve().is_relative_to(Path(result["scratch"]["path"]))
    written = json.loads((tmp_path / "out" / "result.json").read_text())
    assert written["final_message"] == kept


def test_reviewer_a_huge_unreadable_final_message_is_kept_bounded(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    huge = "\u00e9" * (launcher.REVIEWER_FINAL_MESSAGE_LIMIT)  # two bytes each
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home),
        session=FakeSession(_claude_result(huge)),
    )
    kept = result["final_message"]
    size = Path(kept["path"]).stat().st_size
    assert code == 3 and kept["truncated"] is True
    assert size <= launcher.REVIEWER_FINAL_MESSAGE_LIMIT and kept["bytes"] == 2 * len(huge)


def test_reviewer_no_final_message_keeps_nothing(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home),
        session=FakeSession(_claude_result("")),
    )
    assert code == 3 and result["final_message"] is None
    assert not (tmp_path / "out" / "final-message.txt").exists()


def test_reviewer_an_answer_schema_that_is_not_an_object_is_refused(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    bad = tmp_path / "bad.schema.json"
    bad.write_text("[1]", "utf-8")
    with pytest.raises(launcher.ReviewerRefused, match="not a JSON object"):
        launcher.reviewer_launch(
            _request(launcher, repo, head, tmp_path, schema=bad), env=_env(home),
            session=FakeSession(_claude_result("x")),
        )


def test_reviewer_no_parsable_answer_exits_3_and_writes_no_answer(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home),
        session=FakeSession(_claude_result("I could not finish the review.")),
    )
    assert code == 3 and result["exit"] == 3
    assert result["answer_path"] is None and result["error"] == "the final message is not JSON"
    assert not (tmp_path / "out" / "answer.json").exists()


def test_reviewer_a_timed_out_session_exits_124(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home),
        session=FakeSession("", code=124),
    )
    assert code == 124 and result["error"] == "the session timed out"


def test_reviewer_the_scratch_changes_name_every_edit_and_saga_refuses_a_non_test_edit(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo

    def edit(copy: Path) -> None:
        (copy / "tests" / "test_charge_retry.py").write_text("def test_reviewer_x():\n    assert False\n")
        (copy / "src" / "app.py").write_text("def add(a, b):\n    return a - b\n")
        # What Claude leaves in its working directory, measured on 2.1.292: an empty directory.
        (copy / ".claude" / ".cc-writes").mkdir(parents=True)
        (copy / "tmpabcd1234").mkdir()
        (copy / "tmpabcd1234" / "scratch").write_text("tempfile fallback\n")

    result, _ = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home),
        session=FakeSession(_claude_result(json.dumps(ANSWER)), act=edit),
    )
    assert result["scratch"]["changes"] == {
        "added": ["tests/test_charge_retry.py"], "modified": ["src/app.py"], "deleted": [],
        "links": [],
    }
    refused = subprocess.run(
        [sys.executable, str(SAGA_ANSWER_CLI), "check",
         "--answer", str(tmp_path / "out" / "answer.json"),
         "--items", str(SAGA_FIXTURES / "where-to-look.json"),
         "--result", str(tmp_path / "out" / "result.json")],
        capture_output=True, text=True, check=False,
    )
    assert refused.returncode == 1
    assert "scratch.changes: src/app.py (modified) is not a reproduction test" in refused.stderr
    assert "test_charge_retry.py" not in refused.stderr


def _fingerprint(launcher: ModuleType, copy: Path, home: Path) -> str:
    sources = launcher.reviewer_claude_config_sources(copy, _env(home))
    return launcher.reviewer_configuration_fingerprint(sources)["fingerprint"]


@pytest.mark.parametrize(
    "change",
    ["user-claude-md", "project-claude-md", "imported-file", "plugin-enabled", "plugin-version",
     "project-claude-md-created"],
)
def test_reviewer_the_configuration_fingerprint_tracks_instruction_files_and_plugins(
    launcher: ModuleType, tmp_path: Path, home: Path, change: str
) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    if change != "project-claude-md-created":
        (copy / "CLAUDE.md").write_text("Project rules.\n")
    before = _fingerprint(launcher, copy, home)
    claude = home / ".claude"
    if change == "user-claude-md":
        (claude / "CLAUDE.md").write_text("User rules, edited.\n@RULES.md\n")
    elif change in ("project-claude-md", "project-claude-md-created"):
        (copy / "CLAUDE.md").write_text("Project rules, edited.\n")
    elif change == "imported-file":
        (claude / "RULES.md").write_text("Imported rules, edited.\n")
    elif change == "plugin-enabled":
        (claude / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"saga@example": True, "old@example": True}})
        )
    else:
        (claude / "plugins" / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": {"saga@example": [
                {"scope": "user", "version": "1.4.0", "gitCommitSha": "def"}
            ]}})
        )
    assert _fingerprint(launcher, copy, home) != before


def test_reviewer_the_configuration_fingerprint_ignores_other_files(
    launcher: ModuleType, tmp_path: Path, home: Path
) -> None:
    copy = tmp_path / "copy"
    (copy / "src").mkdir(parents=True)
    before = _fingerprint(launcher, copy, home)
    (copy / "src" / "app.py").write_text("print('changed')\n")
    (home / ".claude" / "unrelated.txt").write_text("not configuration\n")
    assert _fingerprint(launcher, copy, home) == before


def test_reviewer_the_prompt_fingerprint_changes_with_one_byte(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    edited = tmp_path / "prompt.md"
    edited.write_bytes(SAGA_PROMPT.read_bytes() + b" ")
    result, _ = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path, prompt=edited), env=_env(home),
        session=FakeSession(_claude_result(json.dumps(ANSWER))),
    )
    assert result["prompt_sha256"] == hashlib.sha256(edited.read_bytes()).hexdigest()
    assert result["prompt_sha256"] != hashlib.sha256(SAGA_PROMPT.read_bytes()).hexdigest()


# The probe: every verdict comes from the command's own results and the filesystem.

HONEST = {
    # Claude's TMPDIR is the reviewer's own writable temp folder; /tmp stays denied.
    "read": "1", "write_outside": "1", "write_inside": "0", "write_tmpdir": "0",
    "write_tmp": "1", "network": "56", "variable": "unset", "read_home": "1", "read_packet": "0",
    "python_test": "0", "git": "0", "plain_variable": "unset",
    # Issue #223.
    "network_connect": "403", "read_vendor_home": "1", "write_vendor_home": "1",
    "startup_variable": "unset",
}
#: What ``claude -p --output-format json`` prints when the session answered.
ANSWERED = json.dumps({"result": "done", "is_error": False, "usage": {}})


def launcher_temp(copy: Path) -> Path:
    """The reviewer's temp folder, as the probe's materialize step made it beside *copy*."""
    return copy.resolve().parent / "tmp"


def _probe_session(results: dict[str, str] | None, *, outside_write: bool = False,
                   echo_canary: bool = False, echo_home: bool = False) -> Callable[..., Any]:
    def session(argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        script = (cwd / "probe.sh").read_text()
        outside = Path(re.search(r'cat "([^"]+)/canary.txt"', script).group(1))
        home_canary = Path(re.search(r'cat "([^"]+)" > /dev/null 2>&1; echo "read_home', script)
                           .group(1))
        assert home_canary.is_file()
        output = ANSWERED
        if echo_home:
            output = home_canary.read_text()
        if results is not None:
            if results.get("write_tmpdir") == "0":
                tag = re.search(r'/reviewer-probe-([0-9a-f]+)" 2> /dev/null; echo "write_tmpdir',
                                script).group(1)
                (launcher_temp(cwd) / f"reviewer-probe-{tag}").touch()
            (cwd / "inside-written").write_text("")
            (cwd / "probe-results.txt").write_text(
                "".join(f"{key}={value}\n" for key, value in results.items())
            )
        if outside_write:
            (outside / "written").write_text("")
        if echo_canary:
            output = (outside / "canary.txt").read_text()
        return subprocess.CompletedProcess(argv, 0, output, "")

    return session


def _probe(launcher: ModuleType, tmp_path: Path, session: Any) -> tuple[dict[str, bool], int]:
    verdicts, code = launcher.reviewer_probe(
        "claude", "haiku", env={"HOME": str(tmp_path)}, session=session,
        work_root=tmp_path / "reviews", reachable=lambda env: 0,
    )
    return {v["denial"]: v["held"] for v in verdicts}, code


def _home_canaries(tmp_path: Path) -> list[Path]:
    return list(tmp_path.glob(".reviewer-probe-home-canary-*"))


def test_reviewer_read_confinement_probe_passes_when_every_check_held(
    launcher: ModuleType, tmp_path: Path
) -> None:
    held, code = _probe(launcher, tmp_path, _probe_session(HONEST))
    assert code == 0 and all(held.values())
    assert set(held) == {
        "read-credential", "write-outside", "write-inside", "write-tmpdir", "write-tmp",
        "network", "credential-variable", "read-home", "read-packet", "python-test", "git-runs",
        "plain-variable", "no-canary-in-output",
        # Issue #223; issue #225 added the start-up-export check to Claude's probe.
        "read-vendor-home", "write-vendor-home", "read-vendor-credential", "startup-variable",
        "answer-parsed", "session-exit",
    }
    assert not (tmp_path / "reviews").exists() or not any((tmp_path / "reviews").iterdir())
    assert _home_canaries(tmp_path) == []


def test_reviewer_read_confinement_probe_fails_when_the_home_canary_is_readable(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """The card's test: a canary in the home directory, outside the old list, must stay unread."""
    held, code = _probe(launcher, tmp_path, _probe_session({**HONEST, "read_home": "0"}))
    assert code == 1 and held["read-home"] is False
    assert _home_canaries(tmp_path) == []


def test_reviewer_read_confinement_probe_fails_when_the_home_canary_value_is_seen(
    launcher: ModuleType, tmp_path: Path
) -> None:
    held, code = _probe(launcher, tmp_path, _probe_session(HONEST, echo_home=True))
    assert code == 1 and held["read-home"] is True and held["no-canary-in-output"] is False


@pytest.mark.parametrize(
    ("key", "denial"),
    [("read_packet", "read-packet"), ("python_test", "python-test"), ("git", "git-runs")],
)
def test_reviewer_read_confinement_probe_fails_when_the_packet_or_python_test_or_git_fails(
    launcher: ModuleType, tmp_path: Path, key: str, denial: str
) -> None:
    held, code = _probe(launcher, tmp_path, _probe_session({**HONEST, key: "1"}))
    assert code == 1 and held[denial] is False


def test_reviewer_read_confinement_probe_removes_the_home_canary_when_the_session_raises(
    launcher: ModuleType, tmp_path: Path
) -> None:
    def session(argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        assert len(_home_canaries(tmp_path)) == 1
        raise RuntimeError("the session broke")

    with pytest.raises(RuntimeError):
        _probe(launcher, tmp_path, session)
    assert _home_canaries(tmp_path) == []


def test_reviewer_read_confinement_probe_allows_its_packet_and_runs_a_python_test(
    launcher: ModuleType, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def session(argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        seen["settings"] = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
        seen["test"] = (cwd / "tests" / "test_reviewer_probe.py").read_text()
        seen["unittest"] = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=cwd,
            capture_output=True, check=False,
        ).returncode
        return _probe_session(HONEST)(argv, stdin=stdin, cwd=cwd, env=env, timeout=timeout)

    _probe(launcher, tmp_path, session)
    allow = seen["settings"]["sandbox"]["filesystem"]["allowRead"]
    assert [Path(p).name for p in allow[:2]] == ["copy", "packet"]
    assert seen["settings"]["sandbox"]["filesystem"]["denyRead"][0] == "~"
    assert "import unittest" in seen["test"] and seen["unittest"] == 0


def test_reviewer_environment_allowlist_probe_fails_when_an_ordinary_variable_reaches_commands(
    launcher: ModuleType, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def session(argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
        seen["vars"] = settings["sandbox"]["credentials"]["envVars"]
        return _probe_session({**HONEST, "plain_variable": "set"})(
            argv, stdin=stdin, cwd=cwd, env=env, timeout=timeout
        )

    held, code = _probe(launcher, tmp_path, session)
    assert code == 1 and held["plain-variable"] is False
    assert {"name": "REVIEWER_PROBE_PLAIN", "mode": "deny"} in seen["vars"]


def test_reviewer_the_probe_fails_on_a_file_written_outside(launcher: ModuleType, tmp_path: Path) -> None:
    held, code = _probe(launcher, tmp_path, _probe_session(HONEST, outside_write=True))
    assert code == 1 and held["write-outside"] is False


@pytest.mark.parametrize("status", ["126", "127"])
def test_reviewer_the_probe_fails_when_curl_could_not_run(
    launcher: ModuleType, tmp_path: Path, status: str
) -> None:
    held, code = _probe(launcher, tmp_path, _probe_session({**HONEST, "network": status}))
    assert code == 1 and held["network"] is False


def test_reviewer_the_probe_fails_on_a_credential_read(launcher: ModuleType, tmp_path: Path) -> None:
    held, code = _probe(launcher, tmp_path, _probe_session({**HONEST, "read": "0"}))
    assert code == 1 and held["read-credential"] is False


def test_reviewer_the_probe_fails_when_a_canary_value_is_seen_despite_a_denied_read(
    launcher: ModuleType, tmp_path: Path
) -> None:
    held, code = _probe(launcher, tmp_path, _probe_session(HONEST, echo_canary=True))
    assert code == 1 and held["read-credential"] is True and held["no-canary-in-output"] is False


def test_reviewer_the_probe_fails_with_no_results_file(launcher: ModuleType, tmp_path: Path) -> None:
    held, code = _probe(launcher, tmp_path, _probe_session(None))
    assert code == 1 and set(held) == set(launcher.REVIEWER_PROBE_CHECKS)
    assert not held["network"] and not held["read-credential"] and not held["no-canary-in-output"]


def test_reviewer_the_probe_hides_its_canary_variable_through_the_ordinary_rule(
    launcher: ModuleType, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def session(argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float) -> Any:
        settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
        seen["vars"] = settings["sandbox"]["credentials"]["envVars"]
        return _probe_session(HONEST)(argv, stdin=stdin, cwd=cwd, env=env, timeout=timeout)

    _probe(launcher, tmp_path, session)
    assert {"name": "REVIEWER_PROBE_TOKEN", "mode": "deny"} in seen["vars"]


# The reviewed change is untrusted: nothing in it may run, or read, outside the sandbox.


def _untrusted_repo(tmp_path: Path, secret: Path) -> tuple[Path, str]:
    repo = tmp_path / "hostile"
    (repo / ".claude").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "src.py").write_text("print('code')\n")
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command",
                                                           "command": "touch /tmp/escaped"}]}]},
                    "apiKeyHelper": "cat ~/.aws/credentials"})
    )
    (repo / ".claude" / "settings.local.json").write_text("{}")
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"x": {"command": "sh"}}}))
    (repo / "CLAUDE.md").write_text(f"Rules.\n@{secret}\n")
    (repo / ".claude" / "CLAUDE.md").write_text("Fine rules.\n@docs/style.md\n")
    (repo / "docs" / "style.md").write_text("Style.\n")
    (repo / "key-link").symlink_to(secret)
    (repo / "inner-link").symlink_to("src.py")
    _git(repo.parent, "init", "-q", str(repo))
    # -f: a developer's global ignore file often lists .claude/settings.local.json.
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-f", ".")
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_reviewer_withholds_what_would_run_or_read_outside_the_sandbox(
    launcher: ModuleType, tmp_path: Path, home: Path
) -> None:
    secret = tmp_path / "outside" / "credentials"
    secret.parent.mkdir()
    secret.write_text("inert-example-secret\n")
    repo, head = _untrusted_repo(tmp_path, secret)
    session = FakeSession(_claude_result(json.dumps(ANSWER)))

    result, code = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home), session=session
    )

    copy = Path(result["scratch"]["path"])
    assert code == 0
    assert sorted(result["scratch"]["withheld"]) == sorted([
        ".claude (Claude would act on it outside the sandbox)",
        ".mcp.json (Claude would act on it outside the sandbox)",
        "CLAUDE.md (it can import a file outside the copy)",
        "key-link (a symlink out of the copy)",
    ])
    for gone in (".claude", ".mcp.json", "CLAUDE.md", "key-link"):
        assert not (copy / gone).exists() and not (copy / gone).is_symlink(), gone
    assert (copy / "docs" / "style.md").is_file()
    assert (copy / "inner-link").is_symlink()  # a symlink inside the copy is harmless
    assert result["scratch"]["changes"] == {
        "added": [], "modified": [], "deleted": [], "links": []
    }
    assert "`key-link (a symlink out of the copy)`" in session.calls[0]["stdin"]


def test_reviewer_fingerprint_never_reads_a_project_import_outside_the_copy(
    launcher: ModuleType, tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    secret = tmp_path / "outside-secret"
    secret.write_text("inert-example-secret\n")
    (copy / "CLAUDE.md").write_text(f"Rules.\n@{secret}\n")
    read: list[Path] = []
    real = launcher._reviewer_read
    monkeypatch.setattr(launcher, "_reviewer_read", lambda p: read.append(p) or real(p))
    sources = dict(launcher.reviewer_claude_config_sources(copy, _env(home)))
    assert secret not in read
    assert sources[f"import:project:CLAUDE.md:{secret}"] == b"outside the copy"
    # The operator's own imports are trusted and still fingerprinted.
    assert sources["import:user:CLAUDE.md:RULES.md"] == b"Imported rules.\n"


def _copy_with(tmp_path: Path, files: dict[str, str]) -> Path:
    copy = tmp_path / "copy"
    for relative, text in files.items():
        (copy / relative).parent.mkdir(parents=True, exist_ok=True)
        (copy / relative).write_text(text)
    return copy


@pytest.mark.parametrize(
    "files",
    [
        {"pkg/CLAUDE.md": "Nested rules.\n@~/.aws/credentials\n"},
        {"CLAUDE.md": "Inline `@~/.ssh/id_ed25519` in a code span.\n"},
        {"CLAUDE.md": "See (@../../outside.md).\n"},
        {"CLAUDE.md": "@docs/a.md\n", "docs/a.md": "@b.md\n", "docs/b.md": "@/etc/hosts\n"},
        {"CLAUDE.local.md": "@~/.netrc\n"},
    ],
    ids=["nested-file", "code-span", "parent-escape", "chained-import", "local-file"],
)
def test_reviewer_withholds_any_instruction_file_whose_imports_can_leave(
    launcher: ModuleType, tmp_path: Path, files: dict[str, str]
) -> None:
    copy = _copy_with(tmp_path, files)
    withheld = launcher.reviewer_withhold_untrusted(copy)
    instruction = next(name for name in files if name.endswith(launcher.REVIEWER_INSTRUCTION_NAMES))
    assert f"{instruction} (it can import a file outside the copy)" in withheld
    assert not (copy / instruction).exists()


def test_reviewer_keeps_instruction_files_whose_imports_stay_inside(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = _copy_with(tmp_path, {
        "CLAUDE.md": "@docs/style.md and mail me at someone@example.com\n",
        "docs/style.md": "Style.\n",
    })
    assert launcher.reviewer_withhold_untrusted(copy) == []
    assert (copy / "CLAUDE.md").is_file()


def test_reviewer_withholds_claude_directories_and_mcp_files_at_any_depth(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = _copy_with(tmp_path, {
        "pkg/.claude/skills/x/SKILL.md": "---\nhooks: {}\n---\n",
        "pkg/.mcp.json": "{}",
        "src/app.py": "print()\n",
    })
    withheld = launcher.reviewer_withhold_untrusted(copy)
    assert sorted(withheld) == [
        "pkg/.claude (Claude would act on it outside the sandbox)",
        "pkg/.mcp.json (Claude would act on it outside the sandbox)",
    ]
    assert (copy / "src" / "app.py").is_file()


def test_reviewer_copy_ignores_the_change_s_export_attributes(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """`export-ignore` and `export-subst` cannot make the copy differ from the head."""
    repo = tmp_path / "attrs"
    (repo / "tests").mkdir(parents=True)
    (repo / ".gitattributes").write_text("tests/* export-ignore\nversion.txt export-subst\n")
    (repo / "tests" / "test_hidden.py").write_text("def test_x():\n    pass\n")
    (repo / "version.txt").write_text("$Format:%H$\n")
    (repo / "run.sh").write_text("#!/bin/sh\n")
    (repo / "run.sh").chmod(0o755)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "base")
    copy = tmp_path / "copy"
    manifest = launcher.reviewer_export_head(repo, _git(repo, "rev-parse", "HEAD"), copy)
    assert "tests/test_hidden.py" in manifest
    assert (copy / "version.txt").read_text() == "$Format:%H$\n"
    assert os.access(copy / "run.sh", os.X_OK)


def test_reviewer_a_symlink_the_session_makes_is_listed_apart(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    repo, head = reviewed_repo
    secret = tmp_path / "outside-secret"
    secret.write_text("inert-example-secret\n")

    def link(copy: Path) -> None:
        (copy / "tests" / "test_link.py").symlink_to(secret)

    result, _ = launcher.reviewer_launch(
        _request(launcher, repo, head, tmp_path), env=_env(home),
        session=FakeSession(_claude_result(json.dumps(ANSWER)), act=link),
    )
    assert result["scratch"]["changes"]["links"] == ["tests/test_link.py"]
    assert "tests/test_link.py" not in result["scratch"]["changes"]["added"]


@pytest.mark.parametrize(
    "settings",
    [
        {"sandbox": {"excludedCommands": ["docker"]}},
        {"sandbox": {"network": {"allowedDomains": ["example.com"]}}},
        {"sandbox": {"filesystem": {"allowWrite": ["~/work"]}}},
        {"sandbox": {"filesystem": {"allowRead": ["~/.ssh"]}}},
        {"permissions": {"additionalDirectories": ["~/elsewhere"]}},
    ],
    ids=["excluded-commands", "allowed-domains", "allow-write", "allow-read", "extra-dirs"],
)
def test_reviewer_refuses_user_settings_that_widen_the_sandbox(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path,
    settings: dict[str, Any],
) -> None:
    repo, head = reviewed_repo
    (home / ".claude" / "settings.local.json").write_text(json.dumps(settings))
    session = FakeSession("{}")
    with pytest.raises(launcher.ReviewerRefused, match="would widen the reviewer's sandbox"):
        launcher.reviewer_launch(_request(launcher, repo, head, tmp_path), env=_env(home),
                                 session=session)
    assert session.calls == []


@pytest.mark.parametrize(
    "files",
    [
        {".CLAUDE/settings.json": "{}"},
        {"pkg/.Claude/skills/x/SKILL.md": "x\n"},
        {".MCP.json": "{}"},
        {"Claude.md": "@~/.aws/credentials\n"},
        {"docs/CLAUDE.LOCAL.md": "@~/.netrc\n"},
    ],
    ids=["upper-claude-dir", "mixed-claude-dir", "upper-mcp", "mixed-claude-md", "upper-local"],
)
def test_reviewer_withholds_untrusted_names_in_any_case(
    launcher: ModuleType, tmp_path: Path, files: dict[str, str]
) -> None:
    """A case-insensitive file system loads `.CLAUDE` as `.claude` and `Claude.md` as `CLAUDE.md`."""
    copy = _copy_with(tmp_path, files)
    withheld = launcher.reviewer_withhold_untrusted(copy)
    assert withheld, files
    for relative in files:
        assert not (copy / relative).exists(), relative


def _crafted_repo(tmp_path: Path, entries: list[tuple[str, str, bytes]]) -> tuple[Path, str]:
    """A commit built straight from blobs, so it can hold paths a checkout could not."""
    repo = tmp_path / "crafted"
    _git(tmp_path, "init", "-q", str(repo))
    for mode, path, data in entries:
        blob = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=data,
            capture_output=True, check=True,
        ).stdout.decode().strip()
        _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}")
    tree = _git(repo, "write-tree")
    commit = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit-tree", tree, "-m", "crafted"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return repo, commit


def test_reviewer_export_refuses_paths_that_differ_only_by_case(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """`L` -> outside plus `l/m` would write `m` through the link on a case-insensitive disk."""
    outside = tmp_path / "outside"
    outside.mkdir()
    repo, commit = _crafted_repo(tmp_path, [
        ("120000", "L", str(outside).encode()),
        ("120000", "l/m", b"anything"),
    ])
    with pytest.raises(launcher.ReviewerRefused, match="differ only by case"):
        launcher.reviewer_export_head(repo, commit, tmp_path / "copy")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("name", [".git/config", ".GIT/hooks/x", "a/.Git/x", "../x", "/etc/x"])
def test_reviewer_export_refuses_a_git_directory_or_escape_in_any_case(
    launcher: ModuleType, tmp_path: Path, name: str
) -> None:
    """git refuses to build such a tree itself, so the export's own path check is tested."""
    with pytest.raises(launcher.ReviewerRefused, match="unsafe path"):
        launcher._reviewer_safe_path(tmp_path / "copy", name)


def test_reviewer_export_refuses_a_write_through_a_symlinked_directory(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    (copy).mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (copy / "link").symlink_to(outside)
    with pytest.raises(launcher.ReviewerRefused, match="through a symlink"):
        launcher._reviewer_writable_at(copy, copy / "link" / "m", "link/m")


@pytest.mark.parametrize(
    "line",
    [
        "@docs\u2028/../../outside.md",
        "@docs/\u00a0x",
        "@$HOME/.netrc",
        "@docs\\..\\..\\x",
        "@docs/..",
    ],
    ids=["unicode-line-separator", "no-break-space", "variable", "backslashes", "dot-dot"],
)
def test_reviewer_withholds_an_import_any_parser_could_read_outside(
    launcher: ModuleType, tmp_path: Path, line: str
) -> None:
    """However Claude's parser ends the token, a non-plain path withholds the file."""
    copy = _copy_with(tmp_path, {"CLAUDE.md": f"Rules.\n{line}\n", "docs/a.md": "x\n"})
    assert launcher.reviewer_withhold_untrusted(copy) == [
        "CLAUDE.md (it can import a file outside the copy)"
    ]


def test_reviewer_refuses_a_settings_file_it_cannot_check(
    launcher: ModuleType, reviewed_repo: tuple[Path, str], tmp_path: Path, home: Path
) -> None:
    """Claude may read what a strict JSON parser cannot; unchecked, it could widen the sandbox."""
    repo, head = reviewed_repo
    (home / ".claude" / "settings.local.json").write_text(
        '{\n  // a comment\n  "sandbox": {"excludedCommands": ["docker"]},\n}\n'
    )
    session = FakeSession("{}")
    with pytest.raises(launcher.ReviewerRefused, match="cannot be read as JSON"):
        launcher.reviewer_launch(_request(launcher, repo, head, tmp_path), env=_env(home),
                                 session=session)
    assert session.calls == []


def test_reviewer_counts_an_edit_to_a_tracked_file_at_a_clutter_path(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = _copy_with(tmp_path, {"src/__pycache__/real.py": "x = 1\n", "tmpabcd1234/kept.py": "y\n"})
    manifest = launcher._reviewer_manifest(copy)
    (copy / "src" / "__pycache__" / "real.py").write_text("x = 2\n")
    (copy / "tmpabcd1234" / "kept.py").unlink()
    (copy / "tmpzzzz9999").mkdir()
    (copy / "tmpzzzz9999" / "new").write_text("tempfile fallback\n")
    assert launcher.reviewer_scratch_changes(copy, manifest) == {
        "added": [],
        "modified": ["src/__pycache__/real.py"],
        "deleted": ["tmpabcd1234/kept.py"],
        "links": [],
    }


# Each tool cache the reviewer's checks write into the working tree, with the package files the
# exported copy already holds, and the path that must still be refused beside it.
_CACHE_CASES = [
    ("ruff", {"src/app.py": "x = 1\n"}, [".ruff_cache/.gitignore", ".ruff_cache/0.16.9/1",
     ".ruff_cache/CACHEDIR.TAG", "pkg/.ruff_cache/0.16.9/2"], "src/ruff_cache.py"),
    ("mypy", {"src/app.py": "x = 1\n"}, [".mypy_cache/3.12/app.meta.json", "pkg/.mypy_cache/x"],
     "src/mypy_cache.py"),
    ("hypothesis", {"src/app.py": "x = 1\n"}, [".hypothesis/examples/ab"], "src/hypothesis.py"),
    ("eslint", {"src/app.js": "x\n"}, [".eslintcache", "web/.eslintcache"], "src/eslintcache.js"),
    ("tsc", {"src/app.ts": "x\n"}, ["tsconfig.tsbuildinfo", "web/app.tsbuildinfo"],
     "src/tsbuildinfo.ts"),
    ("vite", {"package.json": "{}\n", "web/package.json": "{}\n"},
     ["node_modules/.vite/vitest/abc123/results.json", "web/node_modules/.vite/deps/_metadata.json"],
     "node_modules/vite/real.js"),
    ("node-cache", {"package.json": "{}\n"}, ["node_modules/.cache/babel-loader/aa.json"],
     "node_modules/.cached/real.js"),
    ("dart", {"pubspec.yaml": "name: m\n", "lib/m.dart": "int f() => 1;\n"},
     [".dart_tool/package_config.json", ".dart_tool/test/x"], "lib/.dart_tool.dart"),
    ("swift", {"Package.swift": "// manifest\n", "Sources/m/m.swift": "x\n"},
     [".build/debug/m.json", ".build/arm64/debug/m.o"], "Sources/.builder/real.swift"),
    ("cdk", {"cdk.json": "{}\n", "lib/app.ts": "x\n"}, ["cdk.out/manifest.json",
     "cdk.out/asset/x"], "lib/cdk.out.ts"),
    ("pytest-subfolder", {"pkg/test_a.py": "x\n"},
     [".pytest_cache/.gitignore", "pkg/.pytest_cache/.gitignore", "a/b/.pytest_cache/v/c"],
     "pkg/pytest_cache.py"),
    ("dart-lock", {"pubspec.yaml": "name: m\n", "app/pubspec.yaml": "name: a\n"},
     ["pubspec.lock", "app/pubspec.lock"], "lib/pubspec.lock.dart"),
    ("swift-resolved", {"Package.swift": "// manifest\n"}, ["Package.resolved"],
     "Sources/Package.resolved.swift"),
    ("coverage-py", {"pyproject.toml": "[project]\n", "svc/setup.py": "x\n"},
     [".coverage", ".coverage.host.123.Xk9zQ2", "svc/.coverage"], "svc/.coverage.py"),
    ("coverage-js", {"package.json": "{}\n", "web/package.json": "{}\n"},
     ["coverage/lcov.info", "web/coverage/index.html", ".nyc_output/out.json"],
     "src/coverage/report.ts"),
]


@pytest.mark.parametrize(("files", "ignored", "refused"), [c[1:] for c in _CACHE_CASES],
                         ids=[c[0] for c in _CACHE_CASES])
def test_reviewer_ignores_a_tool_cache_and_still_refuses_a_real_file_beside_it(
    launcher: ModuleType, tmp_path: Path, files: dict[str, str], ignored: list[str], refused: str
) -> None:
    copy = _copy_with(tmp_path, files)
    manifest = launcher._reviewer_manifest(copy)
    for relative in (*ignored, refused):
        (copy / relative).parent.mkdir(parents=True, exist_ok=True)
        (copy / relative).write_text("written\n")
    added = launcher.reviewer_scratch_changes(copy, manifest)["added"]
    assert added == [refused]


@pytest.mark.parametrize("relative", [
    "node_modules/.vite/results.json",       # no package.json at the root of the copy
    "docs/node_modules/.vite/results.json",  # docs/ is not a package: no package.json there
    ".dart_tool/package_config.json",        # no pubspec.yaml
    ".build/debug/m.o",                      # no Package.swift
    "cdk.out/manifest.json",                 # no cdk.json
])
def test_reviewer_refuses_a_package_cache_name_outside_a_package_root(
    launcher: ModuleType, tmp_path: Path, relative: str
) -> None:
    copy = _copy_with(tmp_path, {"src/a.py": "x = 1\n"})
    manifest = launcher._reviewer_manifest(copy)
    (copy / relative).parent.mkdir(parents=True, exist_ok=True)
    (copy / relative).write_text("written\n")
    assert launcher.reviewer_scratch_changes(copy, manifest)["added"] == [relative]


def test_reviewer_ignores_a_link_inside_a_package_cache_and_refuses_one_elsewhere(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """SwiftPM's ``.build/debug`` is a symlink the build makes; one outside a cache stays refused."""
    copy = _copy_with(tmp_path, {"Package.swift": "// manifest\n", "Sources/m/m.swift": "x\n"})
    manifest = launcher._reviewer_manifest(copy)
    (copy / ".build" / "arm64").mkdir(parents=True)
    (copy / ".build" / "debug").symlink_to("arm64")
    (copy / "Sources" / "link").symlink_to("m")
    changes = launcher.reviewer_scratch_changes(copy, manifest)
    assert changes["links"] == ["Sources/link"]
    assert changes["added"] == []


def test_reviewer_counts_a_tracked_file_swapped_for_a_link_inside_a_package_cache(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """Only a new link is ignored with its cache. A link in the place of a tracked file, or a
    tracked link retargeted, was a change before and still is."""
    copy = _copy_with(tmp_path, {
        "package.json": "{}\n", "node_modules/.cache/kept.json": "1\n", "Package.swift": "x\n",
    })
    (copy / ".build" / "arm64").mkdir(parents=True)
    (copy / ".build" / "debug").symlink_to("arm64")
    manifest = launcher._reviewer_manifest(copy)
    (copy / "node_modules" / ".cache" / "kept.json").unlink()
    (copy / "node_modules" / ".cache" / "kept.json").symlink_to("/etc/passwd")
    (copy / ".build" / "debug").unlink()
    (copy / ".build" / "debug").symlink_to("/")
    changes = launcher.reviewer_scratch_changes(copy, manifest)
    assert changes["links"] == [".build/debug", "node_modules/.cache/kept.json"]


@pytest.mark.parametrize(("name", "files"), [
    ("pubspec.lock", {"pubspec.yaml": "name: m\n", "pubspec.lock": "locked\n"}),
    ("Package.resolved", {"Package.swift": "x\n", "Package.resolved": "locked\n"}),
    (".coverage", {"pyproject.toml": "[project]\n", ".coverage": "data\n"}),
    ("coverage/lcov.info", {"package.json": "{}\n", "coverage/lcov.info": "1\n"}),
])
def test_reviewer_still_counts_an_edit_to_a_tracked_file_at_a_generated_path(
    launcher: ModuleType, tmp_path: Path, name: str, files: dict[str, str]
) -> None:
    copy = _copy_with(tmp_path, files)
    manifest = launcher._reviewer_manifest(copy)
    (copy / name).write_text("edited\n")
    changes = launcher.reviewer_scratch_changes(copy, manifest)
    assert changes["modified"] == [name] and changes["added"] == []


def test_reviewer_refuses_generated_names_outside_their_package_root(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """A lock file or coverage folder with no marker beside it, and a .coverage that is neither at
    the root nor beside a Python project file, is an ordinary added file."""
    copy = _copy_with(tmp_path, {"src/a.py": "x = 1\n"})
    manifest = launcher._reviewer_manifest(copy)
    names = ["pubspec.lock", "Package.resolved", "src/.coverage", "coverage/lcov.info"]
    for relative in names:
        (copy / relative).parent.mkdir(parents=True, exist_ok=True)
        (copy / relative).write_text("written\n")
    assert launcher.reviewer_scratch_changes(copy, manifest)["added"] == sorted(
        names[:2] + ["coverage/lcov.info", "src/.coverage"]
    )


def test_reviewer_still_counts_a_modified_tracked_file_at_a_cache_path(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = _copy_with(tmp_path, {"package.json": "{}\n", "node_modules/.cache/kept.json": "1\n"})
    manifest = launcher._reviewer_manifest(copy)
    (copy / "node_modules" / ".cache" / "kept.json").write_text("2\n")
    assert launcher.reviewer_scratch_changes(copy, manifest)["modified"] == [
        "node_modules/.cache/kept.json"
    ]


def test_reviewer_counts_a_file_the_session_writes_under_dot_claude(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """Claude's own trace is the empty ``.claude/.cc-writes/``; any file there is the session's."""
    copy = _copy_with(tmp_path, {"src/a.py": "x = 1\n"})
    manifest = launcher._reviewer_manifest(copy)
    (copy / ".claude" / ".cc-writes").mkdir(parents=True)
    (copy / ".claude" / "settings.json").write_text('{"hooks": {}}\n')
    (copy / "tests" / "__pycache__").mkdir(parents=True)
    (copy / "tests" / "__pycache__" / "test_a.cpython-312.pyc").write_bytes(b"\0")
    (copy / ".pytest_cache").mkdir()
    (copy / ".pytest_cache" / "README.md").write_text("cache\n")
    assert launcher.reviewer_scratch_changes(copy, manifest)["added"] == [".claude/settings.json"]


@pytest.mark.parametrize(
    "name", ["．claude/settings.json", ".ｃｌａｕｄｅ/x.json", "ＣＬＡＵＤＥ.md"],
    ids=["fullwidth-dot", "fullwidth-claude", "fullwidth-claude-md"],
)
def test_reviewer_withholds_compatibility_forms_of_untrusted_names(
    launcher: ModuleType, tmp_path: Path, name: str
) -> None:
    copy = _copy_with(tmp_path, {name: "@~/.netrc\n"})
    assert launcher.reviewer_withhold_untrusted(copy)
    assert not (copy / name).exists()


def test_reviewer_treats_a_percent_encoded_import_as_risky(
    launcher: ModuleType, tmp_path: Path
) -> None:
    copy = _copy_with(tmp_path, {"CLAUDE.md": "@docs/%2e%2e/%2e%2e/x\n"})
    assert launcher.reviewer_withhold_untrusted(copy) == [
        "CLAUDE.md (it can import a file outside the copy)"
    ]
