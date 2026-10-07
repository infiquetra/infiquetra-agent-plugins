"""Swift adapters map recorded output onto the lens rows (issue 153)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
FIXTURES = REPO_ROOT / "plugins" / "saga" / "tests" / "fixtures" / "review_tools"

_SWIFT_VERSIONS = {
    "swift": "6.4.0",
    "swiftlint": "0.65.1",
    "muter": "16",
}

_PACKAGE = (
    "// swift-tools-version: 5.10\n"
    "import PackageDescription\n"
    "\n"
    'let package = Package(\n'
    '    name: "example",\n'
    "    targets: [.target(name: \"example\")]\n"
    ")\n"
)

_MUTER_CONFIG = "executable: swift\narguments: []\n"


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
A = _load("review_adapters_swift")
R = _load("review_records")


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
        tool: {"version": version} for tool, version in _SWIFT_VERSIONS.items()
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
        base_stderr: str | None = None,
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
        self.versions = versions if versions is not None else dict(_SWIFT_VERSIONS)
        self.files = files or {}
        self.stderr = stderr
        self.base_stderr = stderr if base_stderr is None else base_stderr
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
        err = self.base_stderr if at_base else self.stderr
        err = err.replace("@ROOT@", Path(cwd).as_posix())
        for relative, content in self.files.items():
            if at_base and relative.startswith("head-only:"):
                continue
            name = relative.removeprefix("head-only:")
            target = Path(cwd) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                content.replace("@ROOT@", Path(cwd).as_posix()), encoding="utf-8"
            )
        return T.ProcessResult(
            self.base_code if at_base else self.code, body, err,
        )


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


def test_each_swift_adapter_declares_its_design_row() -> None:
    assert {item.id: item.comparison for item in A.ADAPTERS} == {
        "swift-compiler": "base-head",
        "swiftlint": "lines",
        "muter": "lines",
        "swift-format": "lines",
        "swift-dependency-audit": "lines",
        "swift-shuffle": "lines",
        "swift-no-network": "lines",
        "swift-coverage": "lines",
    }
    assert _adapter("muter").mutation is True
    assert _adapter("muter").platforms == ()
    assert _adapter("swift-compiler").type_checker is True
    assert _adapter("swift-compiler").stream == "stderr"
    assert _adapter("swift-dependency-audit").gap_first is True
    assert _adapter("swift-shuffle").gap_first is True
    assert _adapter("swift-no-network").gap_first is True
    assert _adapter("swift-format").mode == "fix"
    assert _adapter("swift-coverage").tool == ""


def _swift_repo(
    tmp_path: Path, *, package: str | None = None, lint: str | None = None,
    muter: str | None = None,
) -> tuple[Path, Path]:
    """A Swift package with Sources/probe/probe.swift. Returns repo and source."""
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "Sources" / "probe").mkdir(parents=True)
    (repo / "Package.swift").write_text(package or _PACKAGE, encoding="utf-8")
    if lint is not None:
        (repo / ".swiftlint.yml").write_text(lint, encoding="utf-8")
    if muter is not None:
        (repo / "muter.conf.yml").write_text(muter, encoding="utf-8")
    source = repo / "Sources" / "probe" / "probe.swift"
    source.write_text(
        "public func add(_ a: Int, _ b: Int) -> Int {\n"
        "    return a + b\n"
        "}\n",
        encoding="utf-8",
    )
    return repo, source


def test_compiler_error_in_untouched_file_blocks(tmp_path: Path) -> None:
    repo, _source = _swift_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    seen: list[tuple[list[str], Path]] = []
    runner = _Calls(
        base, "", stderr=_fixture("swift-build.txt"), base_stderr="",
        code=1, seen=seen,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swift-compiler")], runner,
    ) == 0
    _valid(output)
    assert _severity(output, "swift-error") == "blocks"
    assert _severity(output, "NoUsage") == "fix-later"
    assert _severity(output, "RegionIsolation::SendingClosureRisksDataRace") == "blocks"
    assert _finding(output, "swift-error")["location"]["file"] == (
        "Sources/probe/probe.swift"
    )
    runs = [
        (argv, cwd) for argv, cwd in seen
        if argv[:1] == ["swift"] and "package" not in argv
    ]
    assert len(runs) == 2
    for argv, cwd in runs:
        assert argv == [
            "swift", "build", "--build-path", str(cwd / ".saga-build"),
            "-Xswiftc", "-strict-concurrency=complete",
        ]


def test_compiler_moved_diagnostic_matches_and_drops(tmp_path: Path) -> None:
    repo, _source = _swift_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    moved = _fixture("swift-build.txt").replace(":6:", ":16:")
    output = tmp_path / "out"
    runner = _Calls(
        base, "", stderr=moved, base_stderr=_fixture("swift-build.txt"), code=1,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swift-compiler")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_compiler_clean_run_writes_nothing(tmp_path: Path) -> None:
    repo, _source = _swift_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", stderr="", base_stderr="")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swift-compiler")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _degraded(output, "swift") == []


def test_compiler_unparseable_output_is_degraded(tmp_path: Path) -> None:
    repo, _source = _swift_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", stderr="error: Build failed\n", base_stderr="", code=1)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swift-compiler")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "swift")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "unparseable"


def _lint_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo, source = _swift_repo(tmp_path)
    source.write_text(
        "public func add(_ a: Int, _ b: Int) -> Int {\n"
        "    let x = 1; print(x)\n"
        "    return a+b\n"
        "}\n",
        encoding="utf-8",
    )
    return repo, source


def test_swiftlint_error_blocks_warning_fixes_later(tmp_path: Path) -> None:
    repo, source = _lint_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[0] = "public func add(_ a: Int, _ b: Int, _ c: Int) -> Int {\n"
    text[1] = "    let x = 1; print(x, a)\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("swiftlint.json"), code=2)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swiftlint")], runner,
    ) == 0
    _valid(output)
    assert _severity(output, "identifier_name") == "blocks"
    assert _severity(output, "line_length") == "fix-later"
    assert _finding(output, "identifier_name")["location"]["file"] == (
        "Sources/probe/probe.swift"
    )


def test_swiftlint_off_change_drops(tmp_path: Path) -> None:
    repo, _source = _lint_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("swiftlint.json"), code=2)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swiftlint")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_swiftlint_uses_base_config_and_ignores_head(tmp_path: Path) -> None:
    base_config = "disabled_rules:\n  - todo\n"
    repo, source = _swift_repo(tmp_path, lint=base_config)
    base = _commit(repo, "base")
    (repo / ".swiftlint.yml").write_text(
        "disabled_rules:\n  - identifier_name\n", encoding="utf-8"
    )
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[0] = "public func add(_ a: Int, _ b: Int, _ c: Int) -> Int {\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("swiftlint.json"), code=2,
        watch=(".swiftlint.yml",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swiftlint")], runner,
    ) == 0
    assert _severity(output, "identifier_name") == "blocks"
    runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["swiftlint"] and at_base is not None
    ]
    assert runs, "swiftlint never ran"
    for argv, _at_base, state in runs:
        assert state[".swiftlint.yml"] == base_config
        assert "--config" in argv


def test_swiftlint_generated_default_when_base_has_none(tmp_path: Path) -> None:
    repo, source = _lint_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[0] = "public func add(_ a: Int, _ b: Int, _ c: Int) -> Int {\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("swiftlint.json"), code=2,
        watch=(".swiftlint.yml",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swiftlint")], runner,
    ) == 0
    runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["swiftlint"] and at_base is not None
    ]
    assert runs, "swiftlint never ran"
    for _argv, _at_base, state in runs:
        assert state[".swiftlint.yml"] == A._GENERATED_SWIFTLINT_CONFIG


def test_inline_disable_is_noted_not_applied(tmp_path: Path) -> None:
    repo, source = _lint_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[0] = "public func add(_ a: Int, _ b: Int, _ c: Int) -> Int {\n"
    text.insert(0, "// swiftlint:disable identifier_name\n")
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("swiftlint.json"), code=2)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swiftlint")], runner,
    ) == 0
    notes = {
        (item["tool"], item["reason"]) for item in _read(output, "degraded.json")
    }
    assert ("swiftlint", "swiftlint-disable") in notes


def _muter_repo(tmp_path: Path, *, muter: str | None = _MUTER_CONFIG) -> Path:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "Sources").mkdir(parents=True)
    (repo / "Package.swift").write_text(_PACKAGE, encoding="utf-8")
    if muter is not None:
        (repo / "muter.conf.yml").write_text(muter, encoding="utf-8")
    (repo / "Sources" / "example.swift").write_text(
        "public func add(_ a: Int, _ b: Int) -> Int {\n"
        "    return a + b\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "Sources" / "other.swift").write_text(
        "public func sub(_ a: Int, _ b: Int) -> Int {\n"
        "    let delta = a - b\n"
        "    return delta\n"
        "}\n",
        encoding="utf-8",
    )
    return repo


def _muter_changed_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = _muter_repo(tmp_path)
    base = _commit(repo, "base")
    example = repo / "Sources" / "example.swift"
    text = example.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    return a &+ b\n"
    example.write_text("".join(text), encoding="utf-8")
    other = repo / "Sources" / "other.swift"
    text = other.read_text(encoding="utf-8").splitlines(keepends=True)
    text[2] = "    return delta &+ 0\n"
    other.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head


def test_muter_survivors_map_into_repo_and_block(tmp_path: Path) -> None:
    repo, base, head = _muter_changed_repo(tmp_path)
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("muter.json"), watch=("muter.conf.yml",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("muter")], runner,
    ) == 0
    _valid(output)
    assert _severity(output, "surviving-mutant") == "blocks"
    finding = _finding(output, "surviving-mutant")
    assert finding["location"]["file"] in {
        "Sources/example.swift", "Sources/other.swift",
    }
    assert "RelationalOperatorReplacement" in finding["statement"]
    files = {
        item["location"]["file"] for item in _read(output, "findings.json")
    }
    assert files == {"Sources/example.swift", "Sources/other.swift"}
    runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["muter"] and at_base is not None
    ]
    assert len(runs) == 1
    argv, _at_base, state = runs[0]
    assert argv[0] == "muter" and argv[1] == "run"
    assert state["muter.conf.yml"] == _MUTER_CONFIG


def test_muter_ambiguous_suffix_is_dropped(tmp_path: Path) -> None:
    repo = _muter_repo(tmp_path)
    (repo / "example.swift").write_text(
        "public func other() -> Int {\n"
        "    return 1\n"
        "}\n",
        encoding="utf-8",
    )
    base = _commit(repo, "base")
    example = repo / "Sources" / "example.swift"
    text = example.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    return a &+ b\n"
    example.write_text("".join(text), encoding="utf-8")
    other = repo / "Sources" / "other.swift"
    text = other.read_text(encoding="utf-8").splitlines(keepends=True)
    text[2] = "    return delta &+ 0\n"
    other.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("muter.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("muter")], runner,
    ) == 0
    files = {
        item["location"]["file"] for item in _read(output, "findings.json")
    }
    assert files == {"Sources/other.swift"}


def test_muter_not_configured_when_base_has_no_config(tmp_path: Path) -> None:
    repo = _muter_repo(tmp_path, muter=None)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("muter.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("muter")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "muter")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "not-configured"


def test_muter_refuses_linux_with_markers_and_stays_silent_without(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(A, "_platform", lambda: "linux")
    repo = _muter_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("muter.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("muter")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "muter")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "unsupported-platform"
    assert all("--version" in call for call in runner.calls)

    bare = tmp_path / "bare"
    _init(bare)
    (bare / "README.md").write_text("base\n", encoding="utf-8")
    bare_base = _commit(bare, "base")
    (bare / "README.md").write_text("head\n", encoding="utf-8")
    bare_head = _commit(bare, "head")
    bare_out = tmp_path / "bare-out"
    bare_runner = _Calls(bare_base, _fixture("muter.json"))
    assert _run(
        bare, bare_base, bare_head, _profile(tmp_path / "profile.json"), bare_out,
        tmp_path / "bare-home", [_adapter("muter")], bare_runner,
    ) == 0
    assert _read(bare_out, "findings.json") == []
    assert _degraded(bare_out, "muter") == []


def test_muter_past_deadline_records_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(T, "MUTATION_CAP_SECONDS", -1)
    repo = _muter_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("muter.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("muter")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "muter")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "cap"
    assert all(Path(call[0]).name != "muter" or "--version" in call for call in runner.calls)


def test_muter_older_major_is_a_mismatch_that_lowers(tmp_path: Path) -> None:
    repo, base, head = _muter_changed_repo(tmp_path)
    output = tmp_path / "out"
    versions = dict(_SWIFT_VERSIONS)
    versions["muter"] = "15"
    runner = _Calls(base, _fixture("muter.json"), versions=versions)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("muter")], runner,
    ) == 0
    degraded = _degraded(output, "muter")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "version-mismatch"
    assert len(_read(output, "findings.json")) == 2
    assert _severity(output, "surviving-mutant") == "fix-later"


def test_muter_timeout_leaves_timeout_with_no_partials(tmp_path: Path) -> None:
    repo = _muter_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("muter.json"), timeout_tools=("muter",))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("muter")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "muter")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "timeout"


def test_format_leaves_no_record(tmp_path: Path) -> None:
    repo, _source = _swift_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swift-format")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []
    assert runner.calls == []


def test_known_gaps_stay_degraded(tmp_path: Path) -> None:
    repo, _source = _swift_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", versions={})
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home",
        [
            _adapter("swift-dependency-audit"),
            _adapter("swift-shuffle"),
            _adapter("swift-no-network"),
        ],
        runner,
    ) == 0
    _valid(output)
    assert _read(output, "findings.json") == []
    degraded = _read(output, "degraded.json")
    assert len(degraded) == 3
    assert {item["reason"] for item in degraded} == {"known-gap"}
    assert sorted((item["tool"], item["input"]) for item in degraded) == [
        ("swift", "security.dependency-high"),
        ("swift", "testing.flaky-order-or-network"),
        ("swift", "testing.flaky-order-or-network"),
    ]
    assert runner.calls == []


def test_no_markers_means_silence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("swiftlint.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home",
        [
            _adapter("swift-compiler"),
            _adapter("swiftlint"),
            _adapter("muter"),
            _adapter("swift-format"),
            _adapter("swift-dependency-audit"),
            _adapter("swift-shuffle"),
            _adapter("swift-no-network"),
        ],
        runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []
    assert runner.calls, "expected version probes before the adapters declined"
    assert all("--version" in call for call in runner.calls)


def test_removed_markers_are_degraded_not_silent(tmp_path: Path) -> None:
    repo, _source = _swift_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "Package.swift").unlink()
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("swiftlint.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swiftlint")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "swiftlint")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "language-markers-removed"


def test_hostile_toolchain_env_is_stripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SWIFTFLAGS", "-D MALICIOUS")
    monkeypatch.setenv("SWIFTPM_FLAGS", "--disable-sandbox")
    monkeypatch.setenv("SWIFT_DEBUG", "1")
    repo, source = _lint_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[0] = "public func add(_ a: Int, _ b: Int, _ c: Int) -> Int {\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    env_seen: list[dict[str, str]] = []
    runner = _Calls(base, _fixture("swiftlint.json"), code=2, env_seen=env_seen)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("swiftlint")], runner,
    ) == 0
    assert env_seen, "no process env captured"
    for seen_env in env_seen:
        assert "SWIFTFLAGS" not in seen_env
        assert "SWIFTPM_FLAGS" not in seen_env
        assert "SWIFT_DEBUG" not in seen_env


def test_off_pin_version_is_noted_and_run_continues(tmp_path: Path) -> None:
    repo, _source = _swift_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({
            "review_tools": {
                "pins": {"swiftlint": {"version": "bogus"}},
            },
        }),
        encoding="utf-8",
    )
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("swiftlint.json"), code=2)
    assert _run(
        repo, base, head, profile, output,
        tmp_path / "home", [_adapter("swiftlint")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "swiftlint")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "version-mismatch"
    runs = [call for call in runner.calls if "--version" not in call]
    assert len(runs) == 1


def _coverage_repo(tmp_path: Path) -> tuple[Path, str, str, Path]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "Sources").mkdir()
    lines = [f"line{number}\n" for number in range(1, 8)]
    (repo / "Sources" / "example.swift").write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[3] = "LINE4\n"
    (repo / "Sources" / "example.swift").write_text("".join(lines), encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head, tmp_path / "profile.json"


def test_branch_lcov_yields_plain_branch_findings(tmp_path: Path) -> None:
    repo, base, head, profile_path = _coverage_repo(tmp_path)
    profile_path.write_text(json.dumps({"review_tools": {"languages": {"swift": {
        "test_command": "true",
        "coverage_report": "lcov.info",
    }}}}), encoding="utf-8")

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False and isinstance(argv, list)
        (cwd / "lcov.info").write_text(_fixture("swift-branch.lcov"), encoding="utf-8")
        return T.ProcessResult(0, "")

    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    assert T.run(
        repo, base, head, profile_path, output, home=home,
        adapters=[], runner=runner, framework=True,
    ) == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["row"] == "testing.uncovered-branch"
    assert findings[0]["degraded"] is False
    assert findings[0]["location"]["lines"] == {"start": 4, "end": 4}
    assert _severity(output, "Sources/example.swift:4") == "blocks"
    _valid(output)


def _live_bin(name: str, pin: str) -> None:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} is not installed")
    proc = subprocess.run(
        [path, "--version"] if name != "swift" else [path, "package", "--version"],
        capture_output=True, text=True, timeout=60,
    )
    if pin not in (proc.stdout + proc.stderr):
        pytest.skip(f"{name} is not at the pinned version")


def test_live_compiler_error_blocks(tmp_path: Path) -> None:
    _live_bin("swift", _SWIFT_VERSIONS["swift"])
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "Sources" / "probe").mkdir(parents=True)
    (repo / "Package.swift").write_text(_PACKAGE, encoding="utf-8")
    source = repo / "Sources" / "probe" / "probe.swift"
    source.write_text(
        "public func add(_ a: Int, _ b: Int) -> Int {\n"
        "    return a + b\n"
        "}\n",
        encoding="utf-8",
    )
    base = _commit(repo, "base")
    source.write_text(
        "public func add(_ a: Int, _ b: Int) -> Int {\n"
        "    let total: Int = \"broken\"\n"
        "    return total\n"
        "}\n",
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    profile = _profile(tmp_path / "profile.json")
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("swift-compiler")], None,
    )
    assert code == 0
    _valid(output)
    assert _severity(output, "swift-error") == "blocks"
    assert _finding(output, "swift-error")["location"]["file"] == (
        "Sources/probe/probe.swift"
    )


def test_live_swiftlint_error_blocks_with_generated_default(tmp_path: Path) -> None:
    _live_bin("swiftlint", _SWIFT_VERSIONS["swiftlint"])
    repo, source = _lint_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[0] = "public func add(_ a: Int, _ b: Int, _ c: Int) -> Int {\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    profile = _profile(tmp_path / "profile.json")
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("swiftlint")], None,
    )
    assert code == 0
    _valid(output)
    assert _severity(output, "identifier_name") == "blocks"


def test_live_muter_run_is_honest(tmp_path: Path) -> None:
    _live_bin("muter", _SWIFT_VERSIONS["muter"])
    repo = _muter_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    profile = _profile(tmp_path / "profile.json")
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("muter")], None,
    )
    assert code == 0
    _valid(output)
    assert _read(output, "findings.json") != [] or _read(output, "degraded.json") != []
