"""Dart adapters map recorded output onto the lens rows (issue 153)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
FIXTURES = REPO_ROOT / "plugins" / "saga" / "tests" / "fixtures" / "review_tools"

_DART_VERSIONS = {
    "dart": "3.13.2",
    "mutate4dart": "0.12.2",
}


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


T = _load("review_tools")
A = _load("review_adapters_dart")
R = _load("review_records")
C = _load("review_adapters_all_languages")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here runs with sockets refused, so a network call fails the test."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("review adapter tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-tools@example.com")
    _git(repo, "config", "user.name", "review-tools")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _adapter(tool_id: str) -> Any:
    return next(item for item in A.ADAPTERS if item.id == tool_id)


def _profile(path: Path, pins: dict[str, Any] | None = None) -> Path:
    pins = pins if pins is not None else {
        tool: {"version": version} for tool, version in _DART_VERSIONS.items()
    }
    path.write_text(json.dumps({"review_tools": {"pins": pins}}), encoding="utf-8")
    return path


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _Calls:
    """Injected process: versions per tool, base/head payloads, file side effects."""

    def __init__(
        self,
        base: str,
        payload: str,
        *,
        base_payload: str = "{}",
        versions: dict[str, str] | None = None,
        files: dict[str, str] | None = None,
        stderr: str = "",
        code: int = 0,
        base_code: int = 0,
        timeout_tools: tuple[str, ...] = (),
        env_seen: list[dict[str, str]] | None = None,
        seen: list[tuple[list[str], Path]] | None = None,
        watch: tuple[str, ...] = (),
        snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] | None = None,
    ) -> None:
        self.base = base
        self.payload = payload
        self.base_payload = base_payload
        self.versions = versions if versions is not None else dict(_DART_VERSIONS)
        self.files = files or {}
        self.stderr = stderr
        self.code = code
        self.base_code = base_code
        self.timeout_tools = timeout_tools
        self.env_seen = env_seen if env_seen is not None else []
        self.seen = seen if seen is not None else []
        self.watch = watch
        self.snapshots = snapshots if snapshots is not None else []
        self.calls: list[list[str]] = []

    def _tool(self, argv: list[str]) -> str:
        return Path(argv[0]).name

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False
        assert isinstance(argv, list)
        self.calls.append(list(argv))
        self.env_seen.append(dict(env))
        self.seen.append((list(argv), Path(cwd)))
        tool = self._tool(argv)
        if "--version" in argv:
            self.snapshots.append((list(argv), None, {}))
            return T.ProcessResult(0, f"{self.versions.get(tool, '1.0.0')}\n")
        if tool in self.timeout_tools:
            # Version probes always answer: a timeout here means the run was killed.
            raise subprocess.TimeoutExpired(argv, timeout)
        at_base = _git(Path(cwd), "rev-parse", "HEAD") == self.base
        if self.watch:
            # Worktrees are removed after the run, so file evidence that the
            # tool saw must be captured here, at call time.
            state = {
                name: (
                    (Path(cwd) / name).read_text(encoding="utf-8")
                    if (Path(cwd) / name).is_file() else None
                )
                for name in self.watch
            }
            self.snapshots.append((list(argv), at_base, state))
        body = self.base_payload if at_base else self.payload
        body = body.replace("@ROOT@", Path(cwd).as_posix())
        for relative, content in self.files.items():
            if at_base and relative.startswith("head-only:"):
                continue
            name = relative.removeprefix("head-only:")
            target = Path(cwd) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                content.replace("@ROOT@", Path(cwd).as_posix()), encoding="utf-8"
            )
        return T.ProcessResult(self.base_code if at_base else self.code, body, self.stderr)


def _run(
    repo: Path, base: str, head: str, profile: Path, output: Path, home: Path,
    adapters: list[Any], runner: Any, **kwargs: Any,
) -> int:
    home.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("framework", False)
    return T.run(
        repo, base, head, profile, output, home=home,
        adapters=adapters, runner=runner, **kwargs,
    )


def _read(output: Path, name: str) -> Any:
    return json.loads((output / name).read_text(encoding="utf-8"))


def _valid(output: Path) -> None:
    for name in ("findings.json", "measurements.json"):
        for record in _read(output, name):
            assert R.validate(record) == []


def _severity(output: Path, ref: str) -> str:
    for finding in _read(output, "outcomes.json")["findings"]:
        if finding["rule"]["ref"] == ref:
            return str(finding["severity"])
    raise AssertionError(ref)


def _finding(output: Path, ref: str) -> dict[str, Any]:
    for finding in _read(output, "findings.json"):
        if finding["rule"]["ref"] == ref:
            return finding
    raise AssertionError(ref)


def _degraded(output: Path, tool: str) -> list[dict[str, Any]]:
    return [item for item in _read(output, "degraded.json") if item["tool"] == tool]


def _dart_repo(
    tmp_path: Path, *, pubspec: dict[str, Any] | None = None,
    options: str | None = None,
) -> tuple[Path, Path]:
    """A Dart repo with lib/add.dart. Returns the repo and the source file."""
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "lib").mkdir()
    if pubspec is None:
        pubspec = {"name": "example", "environment": {"sdk": "^3.0.0"}}
    (repo / "pubspec.yaml").write_text(
        _pubspec_text(pubspec), encoding="utf-8"
    )
    if options is not None:
        (repo / "analysis_options.yaml").write_text(options, encoding="utf-8")
    source = repo / "lib" / "add.dart"
    source.write_text(
        "int add(int a, int b) {\n"
        "  return a + b;\n"
        "}\n",
        encoding="utf-8",
    )
    return repo, source


def _pubspec_text(pubspec: dict[str, Any]) -> str:
    return yaml.safe_dump(dict(pubspec), sort_keys=False)


def _link_dart_tool(repo: Path) -> None:
    """An untracked resolved `.dart_tool`, linked into the worktrees like CI's."""
    cache = repo / ".dart_tool"
    cache.mkdir(exist_ok=True)
    (cache / "package_config.json").write_text(
        json.dumps({"configVersion": 2, "packages": []}), encoding="utf-8"
    )


def test_each_dart_adapter_declares_its_design_row() -> None:
    assert {item.id: item.comparison for item in A.ADAPTERS} == {
        "dart-analyze": "base-head",
        "mutate4dart": "lines",
        "dart-shuffle": "lines",
        "dart-format": "lines",
        "dart-no-network": "lines",
        "dart-coverage": "lines",
    }
    assert _adapter("mutate4dart").mutation is True
    assert _adapter("dart-analyze").type_checker is True
    assert _adapter("dart-no-network").gap_first is True
    assert _adapter("dart-analyze").silent_ok is True
    assert _adapter("dart-shuffle").silent_ok is False
    assert _adapter("dart-format").mode == "fix"
    assert _adapter("dart-coverage").tool == ""


def test_dart_analyze_error_in_untouched_file_blocks(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("dart-analyze.txt"), base_payload="", code=3)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    _valid(output)
    findings = _read(output, "findings.json")
    assert {finding["rule"]["ref"] for finding in findings} == {
        "return_of_invalid_type", "unused_import", "camel_case_types",
    }
    assert _severity(output, "return_of_invalid_type") == "blocks"
    assert _severity(output, "unused_import") == "fix-later"
    assert _severity(output, "camel_case_types") == "note"
    assert _finding(output, "return_of_invalid_type")["location"]["file"] == "lib/add.dart"


def test_dart_analyze_moved_diagnostic_matches_and_drops(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    moved = (
        _fixture("dart-analyze.txt")
        .replace("lib/add.dart:6:10", "lib/add.dart:16:10")
        .replace("lib/add.dart:1:8", "lib/add.dart:11:8")
        .replace("lib/add.dart:9:7", "lib/add.dart:19:7")
    )
    output = tmp_path / "out"
    runner = _Calls(base, moved, base_payload=_fixture("dart-analyze.txt"), code=3)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_dart_analyze_clean_run_writes_nothing(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    clean = "Analyzing example...\n\nNo issues found!\n"
    runner = _Calls(base, clean, base_payload=clean)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _degraded(output, "dart") == []


def test_dart_analyze_uses_base_options_and_ignores_head(tmp_path: Path) -> None:
    base_options = "linter:\n  rules:\n    - camel_case_types\n"
    repo, _source = _dart_repo(tmp_path, options=base_options)
    base = _commit(repo, "base")
    (repo / "analysis_options.yaml").write_text(
        "linter:\n  rules: []\n", encoding="utf-8"
    )
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("dart-analyze.txt"), base_payload="", code=3,
        watch=("analysis_options.yaml",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _severity(output, "camel_case_types") == "note"
    runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["dart"] and at_base is not None
    ]
    assert runs, "dart analyze never ran"
    for _argv, _at_base, state in runs:
        assert state["analysis_options.yaml"] == base_options


def test_dart_analyze_generated_default_when_base_has_none(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("dart-analyze.txt"), base_payload="", code=3,
        watch=("analysis_options.yaml",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["dart"] and at_base is not None
    ]
    assert runs, "dart analyze never ran"
    for _argv, _at_base, state in runs:
        assert state["analysis_options.yaml"] == A._GENERATED_ANALYSIS_OPTIONS


def test_dart_analyze_deps_missing_without_resolved_tree(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path, pubspec={
        "name": "example",
        "environment": {"sdk": "^3.0.0"},
        "dependencies": {"http": "^1.0.0"},
    })
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("dart-analyze.txt"), base_payload="", code=3)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "dart")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "deps-missing"


def test_dart_analyze_runs_when_the_tree_links_dart_tool(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path, pubspec={
        "name": "example",
        "environment": {"sdk": "^3.0.0"},
        "dependencies": {"http": "^1.0.0"},
    })
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    _link_dart_tool(repo)
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("dart-analyze.txt"), base_payload="", code=3)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _severity(output, "return_of_invalid_type") == "blocks"
    assert _degraded(output, "dart") == []


def test_committed_dart_tool_is_replaced_by_the_operator_tree(
    tmp_path: Path,
) -> None:
    repo, _source = _dart_repo(tmp_path, pubspec={
        "name": "example",
        "environment": {"sdk": "^3.0.0"},
        "dependencies": {"http": "^1.0.0"},
    })
    committed = repo / ".dart_tool"
    committed.mkdir()
    (committed / "package_config.json").write_text(
        json.dumps({"configVersion": 2, "packages": [{"name": "committed"}]}),
        encoding="utf-8",
    )
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    _link_dart_tool(repo)
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("dart-analyze.txt"), base_payload="", code=3,
        watch=(".dart_tool/package_config.json",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _severity(output, "return_of_invalid_type") == "blocks"
    runs = [
        (argv, state) for argv, at_base, state in snapshots
        if argv[:1] == ["dart"] and at_base is False
    ]
    assert runs, "dart analyze never ran at head"
    for _argv, state in runs:
        assert state[".dart_tool/package_config.json"] == json.dumps(
            {"configVersion": 2, "packages": []}
        )


def test_dart_analyze_unparseable_output_is_degraded(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "this is not analyzer output\n", base_payload="", code=3)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "dart")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "unparseable"


def _mutant_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "lib").mkdir()
    (repo / "pubspec.yaml").write_text(_pubspec_text({
        "name": "example",
        "environment": {"sdk": "^3.0.0"},
        "dev_dependencies": {"test": "^1.0.0"},
    }), encoding="utf-8")
    source = repo / "lib" / "add.dart"
    source.write_text(
        "int add(int a, int b) {\n"
        "  return a + b;\n"
        "}\n",
        encoding="utf-8",
    )
    return repo, source


def test_mutate4dart_survivor_on_changed_lines_blocks(tmp_path: Path) -> None:
    repo, source = _mutant_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "  return a + b + 0;\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    _link_dart_tool(repo)
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("mutate4dart.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("mutate4dart")], runner,
    ) == 0
    _valid(output)
    runs = [
        call for call in runner.calls
        if Path(call[0]).name == "mutate4dart" and "--version" not in call
    ]
    assert len(runs) == 1
    assert runs[0][1:] == ["--format", "json", "--no-coverage"]
    findings = _read(output, "findings.json")
    assert {finding["rule"]["ref"] for finding in findings} == {"surviving-mutant"}
    assert findings[0]["location"]["file"] == "lib/add.dart"
    assert "arithmetic" in findings[0]["statement"]
    assert _severity(output, "surviving-mutant") == "blocks"


def test_mutate4dart_past_deadline_records_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(T, "MUTATION_CAP_SECONDS", -1)
    repo, _source = _mutant_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    _link_dart_tool(repo)
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("mutate4dart.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("mutate4dart")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "mutate4dart")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "cap"


def test_mutate4dart_killed_run_records_timeout(tmp_path: Path) -> None:
    repo, _source = _mutant_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    _link_dart_tool(repo)
    output = tmp_path / "out"
    runner = _Calls(base, "", timeout_tools=("mutate4dart",))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("mutate4dart")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "mutate4dart")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "timeout"


def _shuffle_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "test").mkdir()
    (repo / "pubspec.yaml").write_text(_pubspec_text({
        "name": "example",
        "environment": {"sdk": "^3.0.0"},
        "dev_dependencies": {"test": "^1.0.0"},
    }), encoding="utf-8")
    (repo / "test" / "add_test.dart").write_text(
        "import 'package:test/test.dart';\n"
        "void main() {\n"
        "  test('adds', () {\n"
        "    expect(1 + 2, equals(4));\n"
        "  });\n"
        "}\n",
        encoding="utf-8",
    )
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    _link_dart_tool(repo)
    return repo, base, head


def test_dart_shuffle_failure_carries_seed_and_flags(tmp_path: Path) -> None:
    repo, base, head = _shuffle_repo(tmp_path)
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("dart-shuffle.txt"), code=1)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-shuffle")], runner,
    ) == 0
    _valid(output)
    runs = [
        call for call in runner.calls
        if call[:1] == ["dart"] and "--version" not in call
    ]
    assert len(runs) == 1
    assert runs[0] == [
        "dart", "test", "--test-randomize-ordering-seed=random",
        "--reporter", "expanded",
    ]
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["ref"] == "shuffle-failure"
    assert findings[0]["location"]["file"] == "test/add_test.dart"
    assert "(seed 2828091676)" in findings[0]["statement"]
    assert _severity(output, "shuffle-failure") == "fix-later"


def test_dart_shuffle_with_no_tests_is_a_gap(tmp_path: Path) -> None:
    repo, base, head = _shuffle_repo(tmp_path)
    output = tmp_path / "out"
    runner = _Calls(
        base,
        "Shuffling test order with --test-randomize-ordering-seed=1\n"
        "No tests ran.\n",
        code=79,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-shuffle")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "dart")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "no-tests-ran"


def test_dart_shuffle_skips_a_tree_without_the_test_package(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("dart-shuffle.txt"), code=1)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-shuffle")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []
    assert all("--version" in call for call in runner.calls)


def test_dart_format_writes_no_record(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-format")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []
    assert runner.calls == []


def test_no_network_gap_records_without_running_a_binary(tmp_path: Path) -> None:
    repo, _source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", versions={})
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-no-network")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "dart")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "known-gap"
    assert runner.calls == []


def test_no_network_adapter_yields_nothing_without_markers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "notes.txt").write_text("nothing to scan\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "notes.txt").write_text("still nothing\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-no-network")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []


def test_removed_dart_markers_are_degraded(tmp_path: Path) -> None:
    repo, source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "pubspec.yaml").unlink()
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("dart-analyze.txt"), code=3)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "dart")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "language-markers-removed"


def test_inline_ignore_is_noted_not_applied(tmp_path: Path) -> None:
    repo, source = _dart_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text.insert(0, "// ignore: unused_import\n")
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("dart-analyze.txt"), base_payload="", code=3)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")], runner,
    ) == 0
    assert _severity(output, "unused_import") == "fix-later"
    notes = {
        (item["tool"], item["reason"]) for item in _read(output, "degraded.json")
    }
    assert ("dart", "dart-ignore") in notes


def test_osv_still_owns_pubspec_lock_advisories(tmp_path: Path) -> None:
    module_text = (
        REPO_ROOT / "plugins" / "saga" / "scripts" / "review_adapters_dart.py"
    ).read_text(encoding="utf-8")
    assert "osv" not in module_text.lower()
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "pubspec.yaml").write_text(
        _pubspec_text({"name": "example", "environment": {"sdk": "^3.0.0"}}),
        encoding="utf-8",
    )
    (repo / "pubspec.lock").write_text("sdks:\n  dart: '>=3.0.0'\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "pubspec.lock").write_text(
        "sdks:\n  dart: '>=3.0.0'\n  flutter: '>=3.0.0'\n", encoding="utf-8"
    )
    head = _commit(repo, "head")
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"review_tools": {"pins": {"osv-scanner": {"version": "1.0.0"}}}}),
        encoding="utf-8",
    )
    payload = _fixture("osv-scanner.json")
    runner = _Calls(base, payload)
    output = tmp_path / "out"
    osv = next(item for item in C.ADAPTERS if item.id == "osv-scanner")
    assert _run(repo, base, head, profile, output, tmp_path / "home", [osv], runner) == 0
    scans = [argv for argv in runner.calls if "scan" in argv]
    assert len(scans) == 2
    for scan in scans:
        assert "pubspec.lock" in " ".join(scan)
    rows = {
        finding["rule"]["ref"]: finding["rule"]["row"]
        for finding in _read(output, "findings.json")
    }
    assert rows
    assert set(rows.values()) <= {
        "security.dependency-high", "security.dependency-medium-low",
    }
    _valid(output)


def _coverage_repo(tmp_path: Path) -> tuple[Path, str, str, Path]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "lib").mkdir()
    lines = [f"line{number}\n" for number in range(1, 8)]
    (repo / "lib" / "add.dart").write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[3] = "LINE4\n"
    (repo / "lib" / "add.dart").write_text("".join(lines), encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head, tmp_path / "profile.json"


def _lcov_run(
    tmp_path: Path, report: str, output: Path, home: Path,
    repo: Path, base: str, head: str, profile_path: Path,
) -> int:
    profile_path.write_text(json.dumps({"review_tools": {"languages": {"dart": {
        "test_command": "true",
        "coverage_report": "lcov.info",
    }}}}), encoding="utf-8")

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False and isinstance(argv, list)
        (cwd / "lcov.info").write_text(report, encoding="utf-8")
        return T.ProcessResult(0, "")

    return T.run(
        repo, base, head, profile_path, output, home=home,
        adapters=[], runner=runner, framework=True,
    )


def test_flutter_lcov_without_branches_degrades_to_lines(tmp_path: Path) -> None:
    repo, base, head, profile_path = _coverage_repo(tmp_path)
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    assert _lcov_run(
        tmp_path, _fixture("flutter.lcov"), output, home,
        repo, base, head, profile_path,
    ) == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["row"] == "testing.uncovered-branch"
    assert findings[0]["degraded"] is True
    assert findings[0]["location"]["lines"] == {"start": 4, "end": 4}
    reasons = _read(output, "degraded.json")
    assert any(item["reason"] == "no-branch-data" for item in reasons)
    assert _severity(output, "lib/add.dart:4") == "fix-later"
    _valid(output)


def test_branch_lcov_yields_plain_branch_findings(tmp_path: Path) -> None:
    repo, base, head, profile_path = _coverage_repo(tmp_path)
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    assert _lcov_run(
        tmp_path, _fixture("dart-branch.lcov"), output, home,
        repo, base, head, profile_path,
    ) == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["row"] == "testing.uncovered-branch"
    assert findings[0]["degraded"] is False
    assert findings[0]["location"]["lines"] == {"start": 4, "end": 4}
    assert _severity(output, "lib/add.dart:4") == "blocks"
    _valid(output)


def _live_bin(name: str) -> None:
    """Skip unless ``name`` is on PATH at this suite's pin.

    The version probe is the only thing read; the run itself goes through the
    adapter under the suite's socket guard, so a live tool that dials out fails.
    """
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} is not installed")
    proc = subprocess.run(
        [path, "--version"], capture_output=True, text=True, timeout=60
    )
    pin = _DART_VERSIONS[name]
    if pin not in (proc.stdout + proc.stderr):
        pytest.skip(f"{name} is not at {pin}")


def _live_run(
    repo: Path, base: str, head: str, profile: Path, output: Path, home: Path,
    adapters: list[Any],
) -> int:
    home.mkdir(parents=True, exist_ok=True)
    return T.run(
        repo, base, head, profile, output, home=home,
        adapters=adapters, runner=None, framework=False,
    )


def _live_pubspec(repo: Path, *, test_dep: bool = False) -> None:
    pubspec: dict[str, Any] = {
        "name": "example",
        "environment": {"sdk": "^3.0.0"},
    }
    if test_dep:
        pubspec["dev_dependencies"] = {"test": "^1.0.0"}
    (repo / "pubspec.yaml").write_text(_pubspec_text(pubspec), encoding="utf-8")


def _live_resolve(repo: Path) -> None:
    """Resolve packages from the local pub cache only, else skip the test."""
    proc = subprocess.run(
        ["dart", "pub", "get", "--offline"],
        cwd=repo, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        pytest.skip("pub cache cannot resolve this project offline")


def test_live_analyze_reports_a_new_error(tmp_path: Path) -> None:
    _live_bin("dart")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "lib").mkdir()
    _live_pubspec(repo)
    (repo / "lib" / "ok.dart").write_text(
        "int ok(int a) {\n  return a;\n}\n", encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "lib" / "bad.dart").write_text(
        "String greet(String name) {\n  return 42;\n}\n", encoding="utf-8"
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-analyze")],
    ) == 0
    _valid(output)
    assert _severity(output, "return_of_invalid_type") == "blocks"
    assert _finding(output, "return_of_invalid_type")["location"]["file"] == "lib/bad.dart"


def test_live_shuffle_records_its_seed(tmp_path: Path) -> None:
    _live_bin("dart")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "test").mkdir()
    (repo / "lib").mkdir()
    _live_pubspec(repo, test_dep=True)
    (repo / "lib" / "add.dart").write_text(
        "int add(int a, int b) {\n  return a + b;\n}\n", encoding="utf-8"
    )
    (repo / "test" / "add_test.dart").write_text(
        "import 'package:test/test.dart';\n"
        "import '../lib/add.dart';\n"
        "void main() {\n"
        "  test('adds', () {\n"
        "    expect(add(1, 2), equals(4));\n"
        "  });\n"
        "}\n",
        encoding="utf-8",
    )
    _live_resolve(repo)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dart-shuffle")],
    ) == 0
    _valid(output)
    assert _severity(output, "shuffle-failure") == "fix-later"
    statement = _finding(output, "shuffle-failure")["statement"]
    assert re.search(r"\(seed \d+\)", statement)
    assert "adds" in statement


def test_live_mutate4dart_reports_a_survivor(tmp_path: Path) -> None:
    _live_bin("mutate4dart")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "test").mkdir()
    (repo / "lib").mkdir()
    _live_pubspec(repo, test_dep=True)
    (repo / "lib" / "add.dart").write_text(
        "int add(int a, int b) {\n  return a + b;\n}\n", encoding="utf-8"
    )
    (repo / "test" / "add_test.dart").write_text(
        "import 'package:test/test.dart';\n"
        "import '../lib/add.dart';\n"
        "void main() {\n"
        "  test('adds', () {\n"
        "    expect(add(1, 2), isNotNull);\n"
        "  });\n"
        "}\n",
        encoding="utf-8",
    )
    _live_resolve(repo)
    base = _commit(repo, "base")
    text = (repo / "lib" / "add.dart").read_text(encoding="utf-8")
    (repo / "lib" / "add.dart").write_text(
        text.replace("return a + b;", "return a + b + 0 - 0;"), encoding="utf-8"
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("mutate4dart")],
    ) == 0
    _valid(output)
    assert _severity(output, "surviving-mutant") == "blocks"
    assert _finding(output, "surviving-mutant")["location"]["file"] == "lib/add.dart"
