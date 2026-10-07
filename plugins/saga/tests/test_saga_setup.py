"""Survey, machine record, install, and profile write for /saga:setup (issue 150).

The runner is a double. ``--home`` is a temporary directory. Nothing here writes the operator's
home or the worktree's ``.saga-profile.json``.
"""

from __future__ import annotations

import json
import socket
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
SAGA_IDS = ("saga-git", "saga-gh", "saga-python", "saga-uv", "saga-pyyaml")
LOCAL = {"kind": "local", "test_command": "python3 -m pytest tests -q", "scope": "private"}
QA_BLOCK = {
    "schema": "qa_profile.v1",
    "strategies": {"example": {"required": True}},
    "ceiling": {"max_duration_seconds": 60, "max_direct_cost": 0},
}
BASICS = {"functional_test_environment": LOCAL, "qa": QA_BLOCK}


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


setup = _load("saga_setup")


class Result(SimpleNamespace):
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        super().__init__(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("saga setup tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _run(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    **kwargs: Any,
) -> tuple[int, str, str]:
    code = setup.main(argv, env=kwargs.pop("env", {}), **kwargs)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _tools(path: Path, body: str) -> Path:
    target = path / "tools.yaml"
    target.write_text(body, encoding="utf-8")
    return target


def _extensions(path: Path, body: str) -> Path:
    target = path / "extensions.yaml"
    target.write_text(body, encoding="utf-8")
    return target


def _tree(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "a.py").write_text("print(1)\n", encoding="utf-8")
    (path / "a.ts").write_text("export {}\n", encoding="utf-8")
    (path / "a.sh").write_text("#!/bin/sh\necho\n", encoding="utf-8")


HAPPY_TOOLS = """
schema: review_tools.v1
tools:
  - id: star
    tool: star-bin
    languages: ["*"]
    lens: correctness
    default_version: "1.0.0"
    version_mode: exact
    install: "Not installed by setup."
    install_argv: ["do-not-install"]
  - id: py-row
    tool: python3
    languages: ["python"]
    lens: testing
    default_version: "1.0.0"
    version_mode: exact
    install: "Not installed by setup."
    install_argv: null
  - id: ts-row
    tool: tsc
    languages: ["typescript"]
    lens: security
    default_version: "1.0.0"
    version_mode: exact
    install: "Not installed by setup."
    install_argv: null
  - id: sh-row
    tool: shellcheck
    languages: ["shell"]
    lens: architecture-maintainability
    default_version: "1.0.0"
    version_mode: exact
    install: "Not installed by setup."
    install_argv: null
  - id: dart-only
    tool: dart
    languages: ["dart"]
    lens: correctness
    default_version: "1.0.0"
    version_mode: exact
    install: "Not installed by setup."
    install_argv: null
"""


def _happy_runner(calls: list[list[str]]) -> Any:
    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        calls.append(list(argv))
        if argv == ["star-bin", "--version"]:
            return Result(0, "star 1.0.0\n")
        if argv == ["python3", "--version"]:
            raise FileNotFoundError("python3")
        if argv == ["tsc", "--version"]:
            return Result(0, "Version 9.9.9\n")
        if argv == ["shellcheck", "--version"]:
            return Result(0, "shellcheck 1.0.0\n")
        if argv[:4] == ["gh", "repo", "view", "--json"]:
            return Result(1, "")
        raise FileNotFoundError(argv[0] if argv else "tool")

    return runner


def test_survey_reports_selected_languages_and_statuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _tree(repo)
    home = tmp_path / "home"
    home.mkdir()
    tools = _tools(tmp_path, HAPPY_TOOLS)
    calls: list[list[str]] = []
    code, text, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--tools", str(tools)],
        capsys,
        runner=_happy_runner(calls),
    )
    assert code == 0, err
    assert "dart-only" not in text
    assert "do-not-install" not in text
    for identity, status in (("star", "installed"), ("py-row", "missing"), ("ts-row", "wrong-version")):
        assert identity in text
        assert status in text
    assert "correctness" in text and "1.0.0" in text
    (home / "again").mkdir()
    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home / "again"), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=_happy_runner(calls),
    )
    assert code == 0, err
    document = json.loads(raw)
    ids = [row["id"] for row in document["tools"]]
    assert ids == ["star", "py-row", "ts-row", "sh-row"]
    by_id = {row["id"]: row for row in document["tools"]}
    assert by_id["star"]["status"] == "installed"
    assert by_id["star"]["lens"] == "correctness"
    assert by_id["star"]["pinned_version"] == "1.0.0"
    assert by_id["py-row"]["status"] == "missing"
    assert by_id["ts-row"]["status"] == "wrong-version"
    assert by_id["sh-row"]["status"] == "installed"
    assert document["languages"] == ["python", "typescript", "shell"]
    assert "dart-only" not in raw
    assert ["do-not-install"] not in calls
    assert not any(call and call[0] == "dart" for call in calls)


def test_survey_languages_skip_undetected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    _tree(repo)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "hidden.py").write_text("print(1)\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    calls: list[list[str]] = []
    code, raw, err = _run(
        [
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--tools",
            str(_tools(tmp_path, HAPPY_TOOLS)),
            "--format",
            "json",
        ],
        capsys,
        runner=_happy_runner(calls),
    )
    assert code == 0, err
    languages = json.loads(raw)["languages"]
    assert languages == ["python", "typescript", "shell"]
    for absent in ("dart", "rust", "swift"):
        assert absent not in languages

    cdk = tmp_path / "cdk"
    cdk.mkdir()
    (cdk / "cdk.json").write_text("{}\n", encoding="utf-8")
    (cdk / "app.ts").write_text("export {}\n", encoding="utf-8")
    code, raw, err = _run(
        [
            "survey",
            "--repo",
            str(cdk),
            "--home",
            str(home),
            "--tools",
            str(_tools(tmp_path, "schema: review_tools.v1\ntools: []\n")),
            "--format",
            "json",
        ],
        capsys,
        runner=_happy_runner(calls),
    )
    assert code == 0, err
    found = json.loads(raw)["languages"]
    assert found == ["typescript"]
    assert "python" not in found


def test_survey_credentials_are_present_or_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    sentinels = {
        "TYPESAFE_API_KEY": "sentinel-typesafe-value",
        "SAGA_LANGFUSE_PUBLIC_KEY": "sentinel-public-value",
        "SAGA_LANGFUSE_SECRET_KEY": "sentinel-secret-value",
        "SAGA_LANGFUSE_HOST": "sentinel-host-value",
        "LANGFUSE_PUBLIC_KEY": "sentinel-langfuse-untracked",
    }
    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--format", "json"],
        capsys,
        runner=_happy_runner([]),
        env=sentinels,
    )
    assert code == 0, err
    document = json.loads(raw)
    states = {row["name"]: row["state"] for row in document["credentials"]}
    assert list(states) == list(setup.CREDENTIAL_NAMES)
    assert set(states.values()) == {"present"}
    assert "LANGFUSE_PUBLIC_KEY" not in states
    for value in sentinels.values():
        assert value not in raw
        assert value not in err
    (tmp_path / "home-2").mkdir()
    code, text, err = _run(
        ["survey", "--repo", str(repo), "--home", str(tmp_path / "home-2"), "--format", "text"],
        capsys,
        runner=_happy_runner([]),
        env={},
    )
    assert code == 0, err
    for name in setup.CREDENTIAL_NAMES:
        assert f"{name}: absent" in text
    assert "sentinel-" not in text


def test_survey_not_recorded_is_installed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    tools = _tools(
        tmp_path,
        """
schema: review_tools.v1
tools:
  - id: semgrep-security
    tool: semgrep
    languages: ["*"]
    lens: security
    default_version: "not-recorded"
    version_mode: exact
    install: "Not installed by setup."
    install_argv: null
""",
    )
    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=lambda argv, cwd=None, env=None, timeout=30: Result(0, "semgrep 1.2.3\n"),
    )
    assert code == 0, err
    [row] = json.loads(raw)["tools"]
    assert row["status"] == "installed"
    assert row["version"] == "1.2.3"
    assert row["status"] != "wrong-version"


def test_survey_gh_needs_sign_in(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    tools = _tools(
        tmp_path,
        """
schema: review_tools.v1
tools:
  - id: saga-gh
    tool: gh
    languages: ["*"]
    lens: saga
    catalogue: false
    default_version: "not-recorded"
    version_mode: any
    install: "Setup does not install gh."
    install_argv: null
""",
    )
    sentinel = "sentinel-gh-auth-account"
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        calls.append(list(argv))
        if argv == ["gh", "--version"]:
            return Result(0, "gh version 2.40.0\n")
        if argv == ["gh", "auth", "status"]:
            return Result(1, sentinel)
        return Result(1, "")

    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=runner,
    )
    assert code == 0, err
    [row] = json.loads(raw)["tools"]
    assert row["status"] == "needs-sign-in"
    assert row["auth"] == "needs-sign-in"
    assert sentinel not in raw
    assert sentinel not in err
    code, text, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--tools", str(tools)],
        capsys,
        runner=runner,
    )
    assert sentinel not in text and sentinel not in err

    def missing(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        if argv == ["gh", "--version"]:
            raise FileNotFoundError("gh")
        return Result(1, "")

    (tmp_path / "gone").mkdir()
    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(tmp_path / "gone"), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=missing,
    )
    assert code == 0, err
    [row] = json.loads(raw)["tools"]
    assert row["status"] == "missing"


def test_survey_python_minimum(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = _tools(
        tmp_path,
        """
schema: review_tools.v1
tools:
  - id: saga-python
    tool: python3
    languages: ["*"]
    lens: saga
    catalogue: false
    default_version: "not-recorded"
    version_mode: minimum
    minimum_version: "3.12"
    install: "Setup does not install Python."
    install_argv: null
""",
    )

    def survey(answer: Any) -> dict[str, Any]:
        home = tmp_path / f"home-{survey.counter}"
        survey.counter += 1
        home.mkdir()

        def runner(
            argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
        ) -> Result:
            if argv[:4] == ["gh", "repo", "view", "--json"]:
                return Result(1, "")
            if answer is FileNotFoundError:
                raise FileNotFoundError("python3")
            if answer is subprocess.TimeoutExpired:
                raise subprocess.TimeoutExpired(argv, timeout)
            return answer

        code, raw, err = _run(
            ["survey", "--repo", str(repo), "--home", str(home), "--tools", str(tools), "--format", "json"],
            capsys,
            runner=runner,
        )
        assert code == 0, err
        [row] = json.loads(raw)["tools"]
        assert row["pinned_version"] == "3.12"
        return row

    survey.counter = 0  # type: ignore[attr-defined]
    assert survey(Result(0, "Python 3.11.0\n"))["status"] == "wrong-version"
    assert survey(Result(0, "Python 3.12.0\n"))["status"] == "installed"
    assert survey(FileNotFoundError)["status"] == "missing"
    assert survey(subprocess.TimeoutExpired)["status"] == "missing"
    assert survey(Result(1, "no version here"))["status"] == "missing"
    assert survey(Result(1, "Python 3.12.0\n"))["status"] == "installed"


def test_survey_shipped_tool_list_includes_saga_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    seen: list[tuple[str, str, str | None]] = []

    def session(vendor: str, model: str, effort: str | None, env: object = None) -> tuple[list[Any], int]:
        seen.append((vendor, model, effort))
        return [], 0

    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        calls.append(list(argv))
        if argv and argv[0] == "python3":
            return Result(0, "Python 3.12.0\n")
        return Result(0, "1.2.3\n")

    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--format", "json"],
        capsys,
        runner=runner,
        session=session,
    )
    assert code == 0, err
    ids = {row["id"] for row in json.loads(raw)["tools"]}
    for identity in SAGA_IDS:
        assert identity in ids
    assert seen == []
    assert ["claude", "--version"] not in calls


def test_machine_record_lands_under_home_and_excludes_sentinels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    setup.record_offer(home)
    sentinels = {
        "TYPESAFE_API_KEY": "sentinel-typesafe-value",
        "SAGA_LANGFUSE_PUBLIC_KEY": "sentinel-public-value",
        "SAGA_LANGFUSE_SECRET_KEY": "sentinel-secret-value",
        "SAGA_LANGFUSE_HOST": "sentinel-host-value",
    }
    code, _text, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--format", "json"],
        capsys,
        runner=_happy_runner([]),
        env=sentinels,
    )
    assert code == 0, err
    path = home / ".saga" / "machine.json"
    assert path.is_file()
    assert repo.resolve() not in path.resolve().parents
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["ran"] is True
    assert record["offered"] is True
    assert record["schema"] == "machine_record.v1"
    assert "questions" not in record["survey"]
    assert any(row["status"] for row in record["survey"]["tools"])
    blob = path.read_bytes()
    for value in sentinels.values():
        assert value.encode() not in blob
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_machine_record_offer_survives_a_later_survey(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    setup.record_offer(home)
    created = setup.load_machine(home)
    assert created is not None
    assert created["offered"] is True
    assert created["ran"] is not True
    assert created["survey"] is None
    setup.record_survey(home, {"schema": "setup_survey.v1", "tools": [], "questions": [{"key": "qa"}]})
    again = setup.load_machine(home)
    assert again is not None
    assert again["offered"] is True
    assert again["ran"] is True
    assert "questions" not in again["survey"]


def test_sandbox_failure_marks_reproduction_unavailable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    calls: list[tuple[str, str, str | None]] = []

    def session(vendor: str, model: str, effort: str | None, env: object = None) -> tuple[list[Any], int]:
        calls.append((vendor, model, effort))
        return [], 1

    code, raw, err = _run(
        [
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--format",
            "json",
            "--probe-sandbox",
            "live",
        ],
        capsys,
        runner=_happy_runner([]),
        session=session,
    )
    assert code == 0, err
    sandbox = json.loads(raw)["sandbox"]
    assert sandbox["available"] is False
    assert sandbox["reproduction"] == "unavailable"
    assert sandbox["reason"] == "probe-unavailable"
    assert calls == [("claude", "opus", "high")]
    assert "unavailable" in raw


def test_sandbox_success_is_available(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    def session(vendor: str, model: str, effort: str | None, env: object = None) -> tuple[list[Any], int]:
        assert (vendor, model, effort) == ("claude", "haiku", "high")
        return [], 0

    code, raw, err = _run(
        [
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--format",
            "json",
            "--probe-sandbox",
            "live",
            "--probe-sandbox-model",
            "haiku",
        ],
        capsys,
        runner=_happy_runner([]),
        session=session,
    )
    assert code == 0, err
    sandbox = json.loads(raw)["sandbox"]
    assert sandbox["available"] is True
    assert sandbox["reproduction"] == "available"


def test_sandbox_without_the_live_flag_is_not_probed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    def session(*_args: Any, **_kwargs: Any) -> tuple[list[Any], int]:
        raise AssertionError("the session was called")

    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--format", "json"],
        capsys,
        runner=_happy_runner([]),
        session=session,
    )
    assert code == 0, err
    assert json.loads(raw)["sandbox"]["reason"] == "not-probed"

    monkeypatch.setattr(setup, "LAUNCH_PATH", tmp_path / "missing.json")
    (tmp_path / "live").mkdir()
    code, raw, err = _run(
        [
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(tmp_path / "live"),
            "--format",
            "json",
            "--probe-sandbox",
            "live",
        ],
        capsys,
        runner=_happy_runner([]),
        session=session,
    )
    assert code == 0, err
    assert json.loads(raw)["sandbox"]["reason"] == "probe-unavailable"


INSTALL_TOOLS = """
schema: review_tools.v1
tools:
  - id: alpha
    tool: alpha
    languages: ["*"]
    lens: testing
    default_version: "not-recorded"
    install: "Install alpha yourself."
    install_argv: ["install-alpha"]
  - id: beta
    tool: beta
    languages: ["*"]
    lens: testing
    default_version: "not-recorded"
    install: "Install beta yourself."
    install_argv: ["install-beta"]
  - id: gamma
    tool: gamma
    languages: ["*"]
    lens: testing
    default_version: "not-recorded"
    install: "Install gamma yourself."
    install_argv: ["install-gamma"]
  - id: saga-git
    tool: git
    languages: ["*"]
    lens: saga
    catalogue: false
    default_version: "not-recorded"
    version_mode: any
    install: "Setup does not install git."
    install_argv: null
"""


def test_install_runs_only_the_named_vectors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tools = _tools(tmp_path, INSTALL_TOOLS)
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        calls.append(list(argv))
        return Result(0, "hello\n")

    code, out, err = _run(
        ["install", "--tools", "alpha,beta", "--tool-list", str(tools), "--repo", str(tmp_path)],
        capsys,
        runner=runner,
    )
    assert code == 0, err
    assert calls == [["install-alpha"], ["install-beta"]]
    assert "alpha: hello" in out
    assert "beta: hello" in out


def test_install_stops_after_a_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tools = _tools(tmp_path, INSTALL_TOOLS)
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        calls.append(list(argv))
        return Result(1, "nope\n")

    code, _out, _err = _run(
        ["install", "--tools", "alpha,beta", "--tool-list", str(tools), "--repo", str(tmp_path)],
        capsys,
        runner=runner,
    )
    assert code == 1
    assert calls == [["install-alpha"]]


def test_install_refuses_an_unknown_id_and_a_null_vector(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = _tools(tmp_path, INSTALL_TOOLS)
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        calls.append(list(argv))
        return Result(0, "")

    code, _out, err = _run(
        ["install", "--tools", "nope", "--tool-list", str(tools), "--repo", str(tmp_path)],
        capsys,
        runner=runner,
    )
    assert code == 2
    assert "unknown tool" in err
    assert calls == []
    code, out, err = _run(
        ["install", "--tools", "saga-git", "--tool-list", str(tools), "--repo", str(tmp_path)],
        capsys,
        runner=runner,
    )
    assert code == 2
    assert "Setup does not install git." in out
    assert calls == []
    code, out, err = _run(
        ["install", "--tools", "saga-git", "--repo", str(tmp_path)],
        capsys,
        runner=runner,
    )
    assert code == 2
    assert calls == []
    assert "saga_setup:" in err


EXTENSIONS = """
schema: setup_extensions.v1
steps:
  - name: sample
    summary: A fixture step.
    done: ["check-step"]
    run: ["run-step"]
questions:
  - key: nickname
    prompt: What nickname should the profile record?
    profile_key: team_nickname
"""

# Write-mechanics tests run against an empty registry, so a question a later
# card registers never changes what these answers must cover.
EMPTY_EXTENSIONS = """
schema: setup_extensions.v1
steps: []
questions: []
"""


def test_extension_step_survey_does_not_run_the_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        calls.append(list(argv))
        if argv == ["check-step"]:
            return Result(0, "")
        return Result(1, "")

    code, raw, err = _run(
        [
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--extensions",
            str(_extensions(tmp_path, EXTENSIONS)),
            "--tools",
            str(_tools(tmp_path, "schema: review_tools.v1\ntools: []\n")),
            "--format",
            "json",
        ],
        capsys,
        runner=runner,
    )
    assert code == 0, err
    [step] = json.loads(raw)["steps"]
    assert step["done"] is True
    assert ["run-step"] not in calls
    assert ["do-not-install"] not in calls


def test_extension_step_runs_only_when_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    extensions = _extensions(tmp_path, EXTENSIONS)
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        calls.append(list(argv))
        return Result(0, "done\n")

    code, out, err = _run(
        ["step", "--name", "sample", "--repo", str(repo), "--extensions", str(extensions)],
        capsys,
        runner=runner,
    )
    assert code == 0, err
    assert calls == [["run-step"]]
    assert "sample: done" in out
    calls.clear()
    home = tmp_path / "home"
    home.mkdir()
    code, raw, err = _run(
        [
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--extensions",
            str(extensions),
            "--tools",
            str(_tools(tmp_path, "schema: review_tools.v1\ntools: []\n")),
            "--format",
            "json",
        ],
        capsys,
        runner=runner,
    )
    assert code == 0, err
    assert json.loads(raw)["steps"][0]["done"] is True
    assert ["run-step"] not in calls
    calls.clear()
    code, _out, err = _run(
        ["step", "--name", "missing", "--repo", str(repo), "--extensions", str(extensions)],
        capsys,
        runner=runner,
    )
    assert code == 2
    assert calls == []
    assert "unknown step" in err


def test_extension_step_refuses_a_reserved_profile_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    extensions = _extensions(
        tmp_path,
        """
schema: setup_extensions.v1
steps: []
questions:
  - key: clobber
    prompt: Overwrite the schema?
    profile_key: schema
""",
    )

    def runner(*_args: Any, **_kwargs: Any) -> Result:
        raise AssertionError("a reserved key must not probe")

    code, _out, err = _run(
        [
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--extensions",
            str(extensions),
            "--format",
            "json",
        ],
        capsys,
        runner=runner,
    )
    assert code == 2
    assert "reserved profile key schema" in err
    assert not (home / ".saga" / "machine.json").exists()


def test_extension_step_asks_a_question_only_when_the_profile_lacks_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    extensions = _extensions(tmp_path, EXTENSIONS)
    tools = _tools(tmp_path, "schema: review_tools.v1\ntools: []\n")

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        return Result(1, "")

    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--extensions", str(extensions), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=runner,
    )
    assert code == 0, err
    assert any(row["key"] == "nickname" for row in json.loads(raw)["questions"])
    (repo / ".saga-profile.json").write_text(
        json.dumps({"schema": "repository_profile.v1", "team_nickname": "set"}),
        encoding="utf-8",
    )
    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--extensions", str(extensions), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=runner,
    )
    assert code == 0, err
    assert all(row["key"] != "nickname" for row in json.loads(raw)["questions"])


def _public(
    calls: list[list[str]] | None = None,
) -> Any:
    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        if calls is not None:
            calls.append(list(argv))
        if argv[:4] == ["gh", "repo", "view", "--json"]:
            return Result(0, '{"visibility":"PUBLIC"}')
        if argv == ["semgrep", "--version"]:
            return Result(0, _public.semgrep)  # type: ignore[attr-defined]
        if argv == ["git", "--version"]:
            return Result(0, "git version 2.40.0\n")
        raise FileNotFoundError(argv[0] if argv else "tool")

    return runner


_public.semgrep = "semgrep 1.2.3\n"  # type: ignore[attr-defined]


EMPTY_TOOLS = "schema: review_tools.v1\ntools: []\n"


def _write(
    repo: Path,
    answers: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    *,
    tools: Path | None = None,
    extensions: Path | None = None,
    runner: Any = None,
    declaration_writer: Any = None,
) -> tuple[int, str, str]:
    argv = ["write", "--repo", str(repo), "--answers", str(repo / "answers.json")]
    (repo / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    if tools is not None:
        argv += ["--tools", str(tools)]
    if extensions is not None:
        argv += ["--extensions", str(extensions)]
    return _run(argv, capsys, runner=runner or _public(), declaration_writer=declaration_writer)


def test_profile_write_keeps_key_order(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("print(1)\n", encoding="utf-8")
    original = {"schema": "repository_profile.v1", "repo": "example", "zebra": 1}
    (repo / ".saga-profile.json").write_text(json.dumps(original), encoding="utf-8")
    code, _out, err = _write(repo, BASICS, capsys, tools=_tools(tmp_path, EMPTY_TOOLS), extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 0, err
    loaded = json.loads((repo / ".saga-profile.json").read_text(encoding="utf-8"))
    assert list(loaded)[:3] == ["schema", "repo", "zebra"]
    assert loaded["zebra"] == 1
    assert list(loaded)[3] == "languages"
    assert loaded["visibility"] == "public"


def test_profile_write_creates_the_absent_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    code, _out, err = _write(repo, BASICS, capsys, tools=_tools(tmp_path, EMPTY_TOOLS), extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 0, err
    text = (repo / ".saga-profile.json").read_text(encoding="utf-8")
    loaded = json.loads(text)
    assert loaded["schema"] == "repository_profile.v1"
    assert text.count("repository_profile.v1") == 1
    assert "repository_profile.v2" not in text


def test_profile_write_is_atomic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    original = json.dumps({"schema": "repository_profile.v1", "zebra": 1}) + "\n"
    (repo / ".saga-profile.json").write_text(original, encoding="utf-8")

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(setup.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        _write(repo, BASICS, capsys, tools=_tools(tmp_path, EMPTY_TOOLS), extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert (repo / ".saga-profile.json").read_text(encoding="utf-8") == original
    extras = [path.name for path in repo.iterdir() if path.name.startswith(".saga-profile.")]
    assert extras == [".saga-profile.json"]


PIN_TOOLS = """
schema: review_tools.v1
tools:
  - id: semgrep-security
    tool: semgrep
    languages: ["*"]
    lens: security
    default_version: "not-recorded"
    version_mode: exact
    install: "Not installed by setup."
    install_argv: null
  - id: semgrep-saga
    tool: semgrep
    languages: ["*"]
    lens: correctness
    default_version: "not-recorded"
    version_mode: exact
    install: "Not installed by setup."
    install_argv: null
  - id: coverage
    tool: ""
    languages: ["*"]
    lens: testing
    default_version: "not-recorded"
    install: "No binary."
    install_argv: null
  - id: saga-git
    tool: git
    languages: ["*"]
    lens: saga
    catalogue: false
    default_version: "not-recorded"
    version_mode: any
    install: "Setup does not install git."
    install_argv: null
"""


def test_profile_write_pins_are_version_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    seeded = {
        "schema": "repository_profile.v1",
        "functional_test_environment": LOCAL,
        "qa": QA_BLOCK,
        "visibility": "public",
    }
    (repo / ".saga-profile.json").write_text(json.dumps(seeded), encoding="utf-8")
    tools = _tools(tmp_path, PIN_TOOLS)
    try:
        code, _out, err = _write(repo, {}, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
        assert code == 0, err
        pins = json.loads((repo / ".saga-profile.json").read_text(encoding="utf-8"))
        pins = pins["review_tools"]["pins"]
        assert list(pins) == ["semgrep"]
        assert pins["semgrep"] == {"version": "1.2.3"}
        assert "rules" not in pins["semgrep"]
        _public.semgrep = "semgrep 9.9.9\n"  # type: ignore[attr-defined]
        code, _out, err = _write(repo, {}, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
        assert code == 0, err
        again = json.loads((repo / ".saga-profile.json").read_text(encoding="utf-8"))
        assert again["review_tools"]["pins"]["semgrep"]["version"] == "1.2.3"
    finally:
        _public.semgrep = "semgrep 1.2.3\n"  # type: ignore[attr-defined]


def test_profile_write_visibility(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = _tools(tmp_path, EMPTY_TOOLS)
    (tmp_path / "home").mkdir()
    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(tmp_path / "home"), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=_public(),
    )
    assert code == 0, err
    assert all(row["key"] != "visibility" for row in json.loads(raw)["questions"])
    code, _out, err = _write(repo, BASICS, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 0, err
    assert json.loads((repo / ".saga-profile.json").read_text(encoding="utf-8"))["visibility"] == "public"

    private = tmp_path / "private"
    private.mkdir()
    starter = json.dumps({"schema": "repository_profile.v1", "zebra": 1}) + "\n"
    (private / ".saga-profile.json").write_text(starter, encoding="utf-8")

    def closed(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> Result:
        return Result(1, "")

    (tmp_path / "home2").mkdir()
    code, raw, err = _run(
        ["survey", "--repo", str(private), "--home", str(tmp_path / "home2"), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=closed,
    )
    assert code == 0, err
    assert any(row["key"] == "visibility" for row in json.loads(raw)["questions"])
    code, _out, err = _write(
        private, {**BASICS, "visibility": "private"}, capsys, tools=tools, runner=closed, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS)
    )
    assert code == 0, err
    assert json.loads((private / ".saga-profile.json").read_text(encoding="utf-8"))["visibility"] == "private"

    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / ".saga-profile.json").write_text(starter, encoding="utf-8")
    code, _out, err = _write(
        secret, {**BASICS, "visibility": "secret"}, capsys, tools=tools, runner=closed, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS)
    )
    assert code == 2
    assert "public or private" in err
    assert (secret / ".saga-profile.json").read_text(encoding="utf-8") == starter


def test_profile_write_functional_test(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = _tools(tmp_path, EMPTY_TOOLS)
    seen: dict[str, Any] = {}

    def spy(root: Path, resolved: dict[str, Any]) -> Path:
        seen["resolved"] = resolved
        return root / ".saga-profile.json"

    code, _out, err = _write(repo, BASICS, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS), declaration_writer=spy)
    assert code == 0, err
    assert seen["resolved"]["mode"] == "declared"
    assert seen["resolved"]["test_command"] == LOCAL["test_command"]

    real = tmp_path / "real"
    real.mkdir()
    code, _out, err = _write(real, BASICS, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 0, err
    environment = _load("functional_environment")
    resolved = environment.resolve(json.loads((real / ".saga-profile.json").read_text(encoding="utf-8")))
    assert resolved is not None
    assert resolved["mode"] in environment.ANSWERED_MODES
    home = tmp_path / "home"
    home.mkdir()
    code, raw, err = _run(
        ["survey", "--repo", str(real), "--home", str(home), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=_public(),
    )
    assert code == 0, err
    assert all(row["key"] != "functional_test_environment" for row in json.loads(raw)["questions"])
    before = (real / ".saga-profile.json").read_bytes()
    code, _out, err = _write(real, {"functional_test_environment": LOCAL}, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 2
    assert (real / ".saga-profile.json").read_bytes() == before


def test_profile_write_qa_block(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = _tools(tmp_path, EMPTY_TOOLS)
    code, _out, err = _write(repo, BASICS, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 0, err
    qa = _load("qa_strategies")
    assert qa.load_profile(repo)["schema"] == "qa_profile.v1"
    schema = json.loads((REFERENCES / "qa-profile.schema.json").read_text(encoding="utf-8"))
    written = json.loads((repo / ".saga-profile.json").read_text(encoding="utf-8"))["qa"]
    jsonschema.validate(written, schema)

    other = tmp_path / "other"
    other.mkdir()
    starter = json.dumps(
        {
            "schema": "repository_profile.v1",
            "functional_test_environment": LOCAL,
            "visibility": "public",
        }
    )
    (other / ".saga-profile.json").write_text(starter, encoding="utf-8")
    missing = {
        "schema": "qa_profile.v1",
        "strategies": {"example": {"required": True}},
        "ceiling": {"max_duration_seconds": 60},
    }
    code, _out, err = _write(other, {"qa": missing}, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 2
    assert "max_direct_cost" in err
    assert (other / ".saga-profile.json").read_text(encoding="utf-8") == starter
    optional = {
        "schema": "qa_profile.v1",
        "strategies": {"example": {"required": False}},
        "ceiling": {"max_duration_seconds": 60, "max_direct_cost": 0},
    }
    code, _out, err = _write(other, {"qa": optional}, capsys, tools=tools, extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 2
    assert (other / ".saga-profile.json").read_text(encoding="utf-8") == starter


def test_profile_write_registry_question(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    seeded = {
        "schema": "repository_profile.v1",
        "functional_test_environment": LOCAL,
        "qa": QA_BLOCK,
        "visibility": "public",
        "zebra": 1,
    }
    (repo / ".saga-profile.json").write_text(json.dumps(seeded) + "\n", encoding="utf-8")
    tools = _tools(tmp_path, EMPTY_TOOLS)
    extensions = _extensions(tmp_path, EXTENSIONS)
    before = (repo / ".saga-profile.json").read_bytes()
    code, _out, err = _write(repo, {"nope": True}, capsys, tools=tools, extensions=extensions)
    assert code == 2
    assert "unknown answer key" in err
    assert (repo / ".saga-profile.json").read_bytes() == before
    code, _out, err = _write(repo, {"nickname": "mimir"}, capsys, tools=tools, extensions=extensions)
    assert code == 0, err
    loaded = json.loads((repo / ".saga-profile.json").read_text(encoding="utf-8"))
    assert loaded["team_nickname"] == "mimir"
    assert loaded["zebra"] == 1


def test_profile_write_leaves_the_committed_profile_bytes_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = REPO_ROOT / ".saga-profile.json"
    assert committed.is_file()
    before = committed.read_bytes()
    repo = tmp_path / "repo"
    repo.mkdir()
    code, _out, err = _write(repo, BASICS, capsys, tools=_tools(tmp_path, EMPTY_TOOLS), extensions=_extensions(tmp_path, EMPTY_EXTENSIONS))
    assert code == 0, err
    assert committed.read_bytes() == before


def test_profile_reference_names_languages_visibility_and_setup() -> None:
    text = (REFERENCES / "repository-profile.md").read_text(encoding="utf-8")
    assert "languages" in text
    assert "visibility" in text
    assert "version-only" in text
    assert "Setup writes" in text
    assert "does not carry the block yet" in text


def test_setup_card_names_fifteen_files_and_fourteen_commands() -> None:
    commands = (REPO_ROOT / "plugins" / "saga" / "docs" / "commands.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "plugins" / "saga" / "README.md").read_text(encoding="utf-8")
    assert "### /saga:setup" in commands
    assert "15 files and 14 commands" in commands
    assert "15 files and 14 commands" in readme
    skill = (REPO_ROOT / "plugins" / "saga" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    front = skill.split("---", 2)[1]
    keys = [line.split(":", 1)[0] for line in front.splitlines() if line.strip() and not line.startswith(" ")]
    assert keys == ["name", "description"]
    assert "name: setup" in front


def test_offer_status_reports_unrun_unoffered_on_a_fresh_home(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    code, out, err = _run(["offer-status", "--home", str(home)], capsys)
    assert code == 0, err
    assert json.loads(out) == {"schema": "machine_record.v1", "ran": False, "offered": False}
    assert not (home / ".saga" / "machine.json").exists()


def test_record_offer_sets_offered_without_running_setup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    code, _, err = _run(["record-offer", "--home", str(home)], capsys)
    assert code == 0, err
    code, out, err = _run(["offer-status", "--home", str(home)], capsys)
    assert code == 0, err
    assert json.loads(out) == {"schema": "machine_record.v1", "ran": False, "offered": True}
    record = json.loads((home / ".saga" / "machine.json").read_text(encoding="utf-8"))
    assert record["ran"] is False and record["offered"] is True
    assert record["survey"] is None


def test_offer_status_reads_ran_from_a_recorded_survey(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _tree(repo)
    home = tmp_path / "home"
    home.mkdir()
    tools = _tools(tmp_path, HAPPY_TOOLS)
    code, _, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--tools", str(tools)],
        capsys,
        runner=_happy_runner([]),
    )
    assert code == 0, err
    code, out, err = _run(["offer-status", "--home", str(home)], capsys)
    assert code == 0, err
    assert json.loads(out) == {"schema": "machine_record.v1", "ran": True, "offered": False}


def test_offer_verbs_refuse_an_unreadable_machine_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    path = home / ".saga" / "machine.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    code, _, err = _run(["offer-status", "--home", str(home)], capsys)
    assert code == 2
    assert "cannot be read" in err
    code, _, err = _run(["record-offer", "--home", str(home)], capsys)
    assert code == 2
    assert "cannot be read" in err
    assert path.read_text(encoding="utf-8") == "{not json"


def test_survey_rows_carry_the_install_signal_for_the_setup_pane(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _tree(repo)
    home = tmp_path / "home"
    home.mkdir()
    tools = _tools(tmp_path, HAPPY_TOOLS)
    code, raw, err = _run(
        ["survey", "--repo", str(repo), "--home", str(home), "--tools", str(tools), "--format", "json"],
        capsys,
        runner=_happy_runner([]),
    )
    assert code == 0, err
    by_id = {row["id"]: row for row in json.loads(raw)["tools"]}
    assert by_id["star"]["has_install"] is True
    assert by_id["star"]["install"] == "Not installed by setup."
    assert by_id["py-row"]["has_install"] is False
    assert by_id["py-row"]["install"] == "Not installed by setup."
