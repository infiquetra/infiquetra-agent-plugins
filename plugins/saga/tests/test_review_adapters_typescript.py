"""TypeScript adapters map recorded output onto the lens rows (issue 153)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
FIXTURES = REPO_ROOT / "plugins" / "saga" / "tests" / "fixtures" / "review_tools"
_TS_VERSIONS = {
    "npm": "12.0.2",
    "tsc": "5.9.3",
    "eslint": "9.39.5",
    "stryker": "10.0.0",
    "vitest": "4.1.11",
    "jest": "30.5.2",
    "knip": "6.40.0",
    "dependency-cruiser": "18.5.0",
    "prettier": "3.6.2",
    "node": "22.22.3",
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
A = _load("review_adapters_typescript")
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
        tool: {"version": version} for tool, version in _TS_VERSIONS.items()
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
        self.versions = versions if versions is not None else dict(_TS_VERSIONS)
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


def _ts_repo(
    tmp_path: Path, *, package: dict[str, Any] | None = None, lock: bool = True
) -> tuple[Path, Path]:
    """A TypeScript repo with src/example.ts. Returns the repo and the source file."""
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    if package is None:
        package = {"name": "example", "version": "1.0.0"}
    (repo / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
    if lock:
        (repo / "package-lock.json").write_text(
            json.dumps({"name": "example", "lockfileVersion": 3}), encoding="utf-8"
        )
    source = repo / "src" / "example.ts"
    source.write_text(
        "export function add(a: number, b: number): number {\n"
        "  return a + b;\n"
        "}\n"
        "export const label: string = 'example';\n"
        "export const other: string = 'other';\n",
        encoding="utf-8",
    )
    return repo, source


def test_each_typescript_adapter_declares_its_design_row() -> None:
    assert {item.id: item.comparison for item in A.ADAPTERS} == {
        "npm-audit": "base-head",
        "tsc": "base-head",
        "eslint": "lines",
        "stryker": "lines",
        "vitest-shuffle": "lines",
        "jest-shuffle": "lines",
        "knip": "base-head",
        "dependency-cruiser": "base-head",
        "prettier": "lines",
        "typescript-no-network": "lines",
        "vitest-coverage": "lines",
        "jest-coverage": "lines",
    }
    assert _adapter("stryker").mutation is True
    assert _adapter("tsc").type_checker is True
    assert _adapter("typescript-no-network").gap_first is True
    assert _adapter("vitest-shuffle").stream == "both"
    assert _adapter("jest-shuffle").stream == "stderr"
    assert _adapter("stryker").report_file == "reports/mutation/mutation.json"
    assert _adapter("tsc").silent_ok is True
    assert _adapter("vitest-shuffle").silent_ok is False
    assert _adapter("prettier").mode == "fix"


def test_tsc_error_in_untouched_file_blocks(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("tsc.txt"), base_payload="")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    _valid(output)
    findings = _read(output, "findings.json")
    assert {finding["rule"]["ref"] for finding in findings} == {"TS2322", "TS2304"}
    assert _severity(output, "TS2322") == "blocks"
    assert _finding(output, "TS2322")["location"]["file"] == "src/example.ts"


def test_tsc_moved_diagnostic_matches_and_drops(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    moved = _fixture("tsc.txt").replace("src/example.ts(2,14)", "src/example.ts(9,14)")
    output = tmp_path / "out"
    runner = _Calls(base, moved, base_payload=_fixture("tsc.txt"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_tsc_preexisting_error_drops(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    payload = _fixture("tsc.txt")
    runner = _Calls(base, payload, base_payload=payload)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_tsc_clean_run_writes_nothing(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", base_payload="")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _degraded(output, "tsc") == []


def test_tsc_stages_base_options_and_ignores_head_config(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    (repo / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "target": "es2020", "module": "commonjs", "jsx": "react-jsx",
            "baseUrl": ".", "paths": {"@libs/*": ["libs/*"]},
        },
    }), encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"strict": False}, "exclude": ["src"],
    }), encoding="utf-8")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, "", base_payload="", watch=("tsconfig.json", "tsconfig.saga.json"),
        snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    tsc_runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["tsc"] and at_base is not None
    ]
    assert tsc_runs, "tsc never ran"
    for argv, at_base, state in tsc_runs:
        assert Path(argv[argv.index("-p") + 1]).name == "tsconfig.saga.json"
        assert state["tsconfig.saga.json"] is not None
        if not at_base:
            assert state["tsconfig.json"] is None
    # The invoke-level test below asserts the staged content; this run proves the
    # hostile config never applied: tsc ran clean with no findings and no gap.
    assert _read(output, "findings.json") == []
    assert _degraded(output, "tsc") == []


def test_tsc_staged_project_keeps_jsx_and_aliases(tmp_path: Path) -> None:
    options_dir = tmp_path / "staged"
    options_dir.mkdir()
    base_config = options_dir / "tsconfig.json"
    base_config.write_text(json.dumps({
        "compilerOptions": {
            "target": "es2020", "module": "commonjs", "jsx": "react-jsx",
            "baseUrl": ".", "paths": {"@libs/*": ["libs/*"]},
        },
    }), encoding="utf-8")
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text('{"name": "example"}\n', encoding="utf-8")
    (root / "src" / "app.ts").write_text("export const x: number = 1;\n", encoding="utf-8")
    context = T.ScanContext(
        root, root, tmp_path / "home", (),
        base_files=(("tsconfig.json", base_config), ("package.json", None)),
    )
    argv = _adapter("tsc").invoke(context)
    assert argv[:2] == ["tsc", "-p"]
    staged = json.loads((root / argv[2]).read_text(encoding="utf-8"))
    assert staged["compilerOptions"]["strict"] is True
    assert staged["compilerOptions"]["noEmit"] is True
    assert staged["compilerOptions"]["jsx"] == "react-jsx"
    assert staged["compilerOptions"]["paths"] == {"@libs/*": ["libs/*"]}
    assert staged["files"] == ["src/app.ts"]
    assert staged["include"] == [] and staged["exclude"] == []


def test_tsc_relative_extends_declines(tmp_path: Path) -> None:
    options_dir = tmp_path / "staged"
    options_dir.mkdir()
    base_config = options_dir / "tsconfig.json"
    base_config.write_text(
        json.dumps({"extends": "./shared.json", "compilerOptions": {}}),
        encoding="utf-8",
    )
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text('{"name": "example"}\n', encoding="utf-8")
    (root / "src" / "app.ts").write_text("export const x: number = 1;\n", encoding="utf-8")
    context = T.ScanContext(
        root, root, tmp_path / "home", (),
        base_files=(("tsconfig.json", base_config), ("package.json", None)),
    )
    with pytest.raises(T.ToolGap) as excinfo:
        _adapter("tsc").invoke(context)
    assert excinfo.value.reason == "config-unresolved"


def test_tsc_deps_missing_without_installed_tree(tmp_path: Path) -> None:
    repo, _source = _ts_repo(
        tmp_path, package={"name": "example", "dependencies": {"left-pad": "1.0.0"}}
    )
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("tsc.txt"), base_payload="")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "tsc")
    assert len(degraded) == 1 and degraded[0]["reason"] == "deps-missing"


def test_tsc_runs_when_the_tree_links_node_modules(tmp_path: Path) -> None:
    repo, _source = _ts_repo(
        tmp_path, package={"name": "example", "dependencies": {"left-pad": "1.0.0"}}
    )
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    modules = repo / "node_modules"
    modules.mkdir()
    (modules / "marker").write_text("installed\n", encoding="utf-8")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("tsc.txt"), base_payload="")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    assert {finding["rule"]["ref"] for finding in _read(output, "findings.json")} == {
        "TS2322", "TS2304",
    }
    assert _degraded(output, "tsc") == []


def _js_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "example", "version": "1.0.0"}), encoding="utf-8"
    )
    source = repo / "src" / "example.js"
    source.write_text(
        "const unusedVar = 1;\n"
        "function add(a, b) {\n"
        "  return a + b;\n"
        "}\n"
        "console.log(missingName);\n",
        encoding="utf-8",
    )
    return repo, source


def test_eslint_error_blocks_warning_fixes_later(tmp_path: Path) -> None:
    repo, source = _js_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "const unusedVar = 2;\n"
    text[4] = "console.log(missingName, 'x');\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("eslint.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("eslint")], runner,
    ) == 0
    _valid(output)
    assert _severity(output, "no-undef") == "blocks"
    assert _severity(output, "no-unused-vars") == "fix-later"
    assert _finding(output, "no-undef")["location"]["file"] == "src/example.js"


def test_eslint_warning_off_change_drops(tmp_path: Path) -> None:
    repo, _source = _js_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("eslint.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("eslint")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_eslint_uses_base_config_and_ignores_head(tmp_path: Path) -> None:
    repo, source = _js_repo(tmp_path)
    base_config = "export default [{ rules: { 'no-undef': 'error' } }];\n"
    (repo / "eslint.config.mjs").write_text(base_config, encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "eslint.config.mjs").write_text(
        "export default [{ rules: { 'no-undef': 'off' } }];\n", encoding="utf-8"
    )
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[4] = "console.log(missingName, 'x');\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("eslint.json"), watch=("eslint.config.mjs",),
        snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("eslint")], runner,
    ) == 0
    assert _severity(output, "no-undef") == "blocks"
    eslint_runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["eslint"] and at_base is not None
    ]
    assert eslint_runs, "eslint never ran"
    for argv, _at_base, state in eslint_runs:
        assert "--config" in argv
        assert state["eslint.config.mjs"] == base_config


def test_eslint_plugin_default_when_base_has_none(tmp_path: Path) -> None:
    repo, source = _js_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[4] = "console.log(missingName, 'x');\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("eslint.json"), watch=("eslint.config.mjs",),
        snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("eslint")], runner,
    ) == 0
    expected = (
        REPO_ROOT / "plugins" / "saga" / "references" / "eslint-recommended.eslint-config"
    ).read_text(encoding="utf-8")
    eslint_runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["eslint"] and at_base is not None
    ]
    assert eslint_runs, "eslint never ran"
    for argv, _at_base, state in eslint_runs:
        assert Path(argv[argv.index("--config") + 1]).name == "eslint.config.mjs"
        assert state["eslint.config.mjs"] == expected


def test_eslint_unparseable_output_is_degraded(tmp_path: Path) -> None:
    repo, source = _js_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[4] = "console.log(missingName, 'x');\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "not json{{{")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("eslint")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "eslint")
    assert len(degraded) == 1 and degraded[0]["reason"] == "unparseable"


def _audit_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "package.json").write_text(
        json.dumps({"name": "example", "dependencies": {"example-lib": "^1.0.0"}}),
        encoding="utf-8",
    )
    (repo / "package-lock.json").write_text(
        json.dumps({"name": "example", "lockfileVersion": 3}), encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "package-lock.json").write_text(
        json.dumps({"name": "example", "lockfileVersion": 3, "packages": {}}),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    return repo, base, head


def test_npm_audit_maps_severities_to_rows(tmp_path: Path) -> None:
    repo, base, head = _audit_repo(tmp_path)
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("npm-audit.json"), base_payload='{"vulnerabilities": {}}')
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("npm-audit")], runner,
    ) == 0
    _valid(output)
    assert _severity(output, "GHSA-AAAA-BBBB-CCCC") == "blocks"
    assert _severity(output, "GHSA-DDDD-EEEE-FFFF") == "fix-later"
    assert _severity(output, "GHSA-1111-2222-3333") == "fix-later"
    assert _severity(output, "unrated-pkg") == "blocks"
    assert (
        _finding(output, "GHSA-AAAA-BBBB-CCCC")["location"]["file"] == "package-lock.json"
    )


def test_npm_audit_preexisting_advisory_drops(tmp_path: Path) -> None:
    repo, base, head = _audit_repo(tmp_path)
    output = tmp_path / "out"
    payload = _fixture("npm-audit.json")
    runner = _Calls(base, payload, base_payload=payload)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("npm-audit")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_npm_audit_needs_an_npm_lockfile(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "package.json").write_text('{"name": "example"}\n', encoding="utf-8")
    (repo / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("npm-audit.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("npm-audit")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _degraded(output, "npm") == []
    assert all(call[:1] != ["npm"] or "--version" in call for call in runner.calls)


def test_npm_audit_stages_base_npmrc(tmp_path: Path) -> None:
    repo, base, head = _audit_repo(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / ".npmrc").write_text("registry=https://registry.example.com/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    (repo / ".npmrc").write_text("registry=https://evil.example.com/\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, _fixture("npm-audit.json"), base_payload='{"vulnerabilities": {}}',
        watch=(".npmrc",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("npm-audit")], runner,
    ) == 0
    audit_runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["npm"] and "audit" in argv and at_base is not None
    ]
    assert audit_runs, "npm audit never ran"
    for _argv, _at_base, state in audit_runs:
        assert state[".npmrc"] == "registry=https://registry.example.com/\n"


def test_npm_high_blocks_unless_the_builder_excuses_it(tmp_path: Path) -> None:
    repo, base, head = _audit_repo(tmp_path)
    profile = _profile(tmp_path / "profile.json")
    payload = _fixture("npm-audit.json")
    home = tmp_path / "home"
    first = tmp_path / "first"
    assert _run(
        repo, base, head, profile, first, home,
        [_adapter("npm-audit")],
        _Calls(base, payload, base_payload='{"vulnerabilities": {}}'),
    ) == 0
    assert _severity(first, "GHSA-AAAA-BBBB-CCCC") == "blocks"
    finding = _finding(first, "GHSA-AAAA-BBBB-CCCC")
    builder = {
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": "U1",
        "acceptance_criteria": [{
            "id": "AC-4",
            "text": "A critical npm advisory blocks unless a reason is recorded.",
            "checks": ["npm-audit"],
        }],
        "declarations": [],
        "reasons": [{
            "kind": "scanner-false-positive",
            "finding_id": finding["id"],
            "text": "The scanner misfired on this advisory.",
        }],
    }
    assert R.validate(builder) == []
    builder_path = tmp_path / "builder.json"
    builder_path.write_text(json.dumps(builder), encoding="utf-8")
    second = tmp_path / "second"
    assert _run(
        repo, base, head, profile, second, home,
        [_adapter("npm-audit")],
        _Calls(base, payload, base_payload='{"vulnerabilities": {}}'),
        builder=builder_path,
    ) == 0
    assert _severity(second, "GHSA-AAAA-BBBB-CCCC") == "note"


def _runner_repo(
    tmp_path: Path, runner: str, *, suffix: str = ".js",
) -> tuple[Path, Path]:
    """A JS/TS repo whose base manifest declares one test runner."""
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "package.json").write_text(json.dumps({
        "name": "example", "version": "1.0.0",
        "devDependencies": {runner: "*"},
    }), encoding="utf-8")
    source = repo / "src" / f"example{suffix}"
    source.write_text(
        "export function add(a, b) {\n"
        "  return a + b;\n"
        "}\n",
        encoding="utf-8",
    )
    return repo, source


def test_vitest_shuffle_failure_carries_seed_and_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(A, "_shuffle_seed", lambda: 4242)
    repo, _source = _runner_repo(tmp_path, "vitest")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    # The seed and summary print on stdout; the failures print on stderr.
    # Splitting the streams proves the `both` stream feeds the same parser.
    stdout = (
        'Running tests with seed "4242"\n'
        " Test Files  1 failed (1)\n"
        "      Tests  1 failed (1)\n"
    )
    stderr = (
        " FAIL  test/example.test.js > adds\n"
        "AssertionError: expected 3 to be 4\n"
    )
    runner = _Calls(base, stdout, stderr=stderr)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("vitest-shuffle")], runner,
    ) == 0
    _valid(output)
    runs = [
        call for call in runner.calls
        if call[:1] == ["vitest"] and "--version" not in call
    ]
    assert len(runs) == 1
    argv = runs[0]
    assert argv[:4] == ["vitest", "run", "--sequence.shuffle", "--sequence.seed"]
    assert "--reporter" not in argv
    assert argv[4] == "4242"
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["ref"] == "shuffle-failure"
    assert findings[0]["location"]["file"] == "test/example.test.js"
    assert "(seed 4242)" in findings[0]["statement"]
    assert _severity(output, "shuffle-failure") == "fix-later"


def test_vitest_shuffle_with_no_tests_is_a_gap(tmp_path: Path) -> None:
    repo, _source = _runner_repo(tmp_path, "vitest")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "No test files found, exiting with code 1\n", code=1)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("vitest-shuffle")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "vitest")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "no-tests-ran"


def test_jest_shuffle_failure_carries_seed_and_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(A, "_shuffle_seed", lambda: 4242)
    repo, _source = _runner_repo(tmp_path, "jest")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    # Jest writes everything to stderr; stdout stays empty. The tool echoes the
    # seed it was given, so the fixture seed is rewritten to the argv seed.
    runner = _Calls(
        base, "", stderr=_fixture("jest-shuffle.txt").replace("1234", "4242"), code=1
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("jest-shuffle")], runner,
    ) == 0
    _valid(output)
    runs = [
        call for call in runner.calls
        if Path(call[0]).name == "jest" and "--version" not in call
    ]
    assert len(runs) == 1
    argv = runs[0]
    assert argv[1:5] == ["--randomize", "--seed", "4242", "--showSeed"]
    assert "--json" not in argv
    assert "--config" not in argv
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["ref"] == "shuffle-failure"
    assert findings[0]["location"]["file"] == "__tests__/example.test.js"
    assert "(seed 4242)" in findings[0]["statement"]
    assert _severity(output, "shuffle-failure") == "fix-later"


def test_jest_shuffle_with_no_tests_is_a_gap(tmp_path: Path) -> None:
    repo, _source = _runner_repo(tmp_path, "jest")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", stderr="No tests found, exiting with code 1\n", code=1)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("jest-shuffle")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "jest")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "no-tests-ran"


def _stryker_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "package.json").write_text(json.dumps({
        "name": "example", "version": "1.0.0",
        "devDependencies": {"jest": "^30.0.0"},
    }), encoding="utf-8")
    source = repo / "src" / "example.js"
    source.write_text(
        "function add(a, b) {\n"
        "  return a + b;\n"
        "}\n"
        "module.exports = { add };\n",
        encoding="utf-8",
    )
    return repo, source


def test_stryker_survivor_on_changed_lines_blocks(tmp_path: Path) -> None:
    repo, source = _stryker_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "  return a + b + 0;\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(
        base, "Mutation testing complete: 1 survived, 1 killed.\n",
        files={"reports/mutation/mutation.json": _fixture("stryker-mutation.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("stryker")], runner,
    ) == 0
    _valid(output)
    runs = [
        call for call in runner.calls
        if Path(call[0]).name == "stryker" and "--version" not in call
    ]
    assert len(runs) == 1
    argv = runs[0]
    assert "--testRunner" in argv and argv[argv.index("--testRunner") + 1] == "jest"
    assert "--reporters" in argv and argv[argv.index("--reporters") + 1] == "json"
    assert "--mutate" in argv
    findings = _read(output, "findings.json")
    assert {finding["rule"]["ref"] for finding in findings} == {"surviving-mutant"}
    assert findings[0]["location"]["file"] == "src/example.js"
    assert "ArithmeticOperator" in findings[0]["statement"]
    assert _severity(output, "surviving-mutant") == "blocks"


def test_stryker_past_deadline_records_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(T, "MUTATION_CAP_SECONDS", -1)
    repo, _source = _stryker_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(
        base, "Mutation testing complete.\n",
        files={"reports/mutation/mutation.json": _fixture("stryker-mutation.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("stryker")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "stryker")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "cap"
    assert all(Path(call[0]).name != "stryker" or "--version" in call for call in runner.calls)


def test_stryker_killed_run_records_timeout(tmp_path: Path) -> None:
    repo, _source = _stryker_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", timeout_tools=("stryker",))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("stryker")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "stryker")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "timeout"


def test_stryker_reads_the_report_file_not_stdout(tmp_path: Path) -> None:
    repo, _source = _stryker_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "Mutation testing complete: 1 survived, 1 killed.\n")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("stryker")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "stryker")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "unparseable"


def test_knip_unused_code_is_a_note(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("knip.json"), base_payload='{"issues": []}')
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("knip")], runner,
    ) == 0
    _valid(output)
    findings = _read(output, "findings.json")
    assert {finding["rule"]["ref"] for finding in findings} == {
        "unused-file", "unused-export", "unused-dependency",
    }
    assert _severity(output, "unused-file") == "note"
    assert _severity(output, "unused-export") == "note"
    assert _severity(output, "unused-dependency") == "note"
    assert _finding(output, "unused-dependency")["location"]["file"] == "package.json"


def test_knip_preexisting_entries_drop(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    payload = _fixture("knip.json")
    runner = _Calls(base, payload, base_payload=payload)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("knip")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def _cruiser_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "example", "version": "1.0.0"}), encoding="utf-8"
    )
    (repo / ".dependency-cruiser.json").write_text(
        json.dumps({"forbidden": []}), encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head


def test_dependency_cruiser_error_blocks_warning_fixes_later(tmp_path: Path) -> None:
    repo, base, head = _cruiser_repo(tmp_path)
    output = tmp_path / "out"
    runner = _Calls(
        base, _fixture("depcruise.json"),
        base_payload='{"summary": {"violations": []}}',
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dependency-cruiser")], runner,
    ) == 0
    _valid(output)
    assert _severity(output, "no-orphans") == "blocks"
    assert _severity(output, "not-to-test") == "fix-later"
    assert _finding(output, "no-orphans")["location"]["file"] == "src/orphan.js"


def test_dependency_cruiser_preexisting_violation_drops(tmp_path: Path) -> None:
    repo, base, head = _cruiser_repo(tmp_path)
    output = tmp_path / "out"
    payload = _fixture("depcruise.json")
    runner = _Calls(base, payload, base_payload=payload)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dependency-cruiser")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_dependency_cruiser_without_base_config_is_not_configured(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("depcruise.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dependency-cruiser")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "dependency-cruiser")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "not-configured"


def test_prettier_writes_no_record(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("prettier")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []
    assert runner.calls == []


def test_no_network_gap_records_without_running_a_binary(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", versions={})
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("typescript-no-network")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "node")
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
        tmp_path / "home", [_adapter("typescript-no-network")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []


def test_removed_typescript_markers_are_degraded(tmp_path: Path) -> None:
    repo, source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "package.json").unlink()
    (repo / "package-lock.json").unlink()
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("tsc.txt"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "tsc")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "language-markers-removed"


def test_inline_suppressions_are_noted_not_applied(tmp_path: Path) -> None:
    repo, source = _js_repo(tmp_path)
    ts_source = repo / "src" / "example.ts"
    ts_source.write_text("export const x: number = 1;\n", encoding="utf-8")
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[4] = "console.log(missingName, 'x');\n"
    text.append("// eslint-disable-next-line no-undef\n")
    source.write_text("".join(text), encoding="utf-8")
    ts_text = ts_source.read_text(encoding="utf-8").splitlines(keepends=True)
    ts_text.append("// @ts-nocheck\n")
    ts_source.write_text("".join(ts_text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("eslint.json"))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("eslint")], runner,
    ) == 0
    assert _severity(output, "no-undef") == "blocks"
    notes = {
        (item["tool"], item["reason"]) for item in _read(output, "degraded.json")
    }
    assert ("eslint", "eslint-disable") in notes
    assert ("tsc", "ts-nocheck") in notes


def test_tool_env_is_allow_listed(tmp_path: Path) -> None:
    repo, _source = _ts_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    env_seen: list[dict[str, str]] = []
    runner = _Calls(base, "", base_payload="", env_seen=env_seen)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")], runner,
    ) == 0
    assert env_seen, "no process env captured"
    allowed = {"PATH", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE", "TZ"}
    expected = {name for name in allowed if name in os.environ}
    expected |= {"HOME", "TMPDIR", "CARGO_HOME"}
    for env in env_seen:
        assert set(env) == expected
        assert env["HOME"] != os.environ.get("HOME")
        assert Path(env["HOME"]).is_absolute()
        assert Path(env["TMPDIR"]).is_absolute()
        assert env["CARGO_HOME"].startswith(str(tmp_path / "home"))


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
    pin = _TS_VERSIONS[name]
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


def test_live_tsc_reports_a_new_type_error(tmp_path: Path) -> None:
    _live_bin("tsc")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "example", "version": "1.0.0"}), encoding="utf-8"
    )
    (repo / "src" / "ok.ts").write_text(
        "export const ok: number = 1;\n", encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "src" / "bad.ts").write_text(
        'export const bad: number = "oops";\n', encoding="utf-8"
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("tsc")],
    ) == 0
    _valid(output)
    assert _severity(output, "TS2322") == "blocks"
    assert _finding(output, "TS2322")["location"]["file"] == "src/bad.ts"


def test_live_eslint_plugin_default_reports_undef(tmp_path: Path) -> None:
    _live_bin("eslint")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "example", "version": "1.0.0"}), encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "src" / "bad.js").write_text(
        "const x = 1;\nconsole.log(missingName, x);\n", encoding="utf-8"
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("eslint")],
    ) == 0
    _valid(output)
    assert _severity(output, "no-undef") == "blocks"
    assert _finding(output, "no-undef")["location"]["file"] == "src/bad.js"


def test_live_vitest_shuffle_records_its_seed(tmp_path: Path) -> None:
    _live_bin("vitest")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "test").mkdir()
    (repo / "package.json").write_text(json.dumps({
        "name": "example", "version": "1.0.0", "type": "module",
        "devDependencies": {"vitest": "4.1.11"},
    }), encoding="utf-8")
    (repo / "test" / "example.test.js").write_text(
        'import { test, expect } from "vitest";\n'
        'test("adds", () => { expect(1 + 2).toBe(4); });\n',
        encoding="utf-8",
    )
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("vitest-shuffle")],
    ) == 0
    _valid(output)
    assert _severity(output, "shuffle-failure") == "fix-later"
    statement = _finding(output, "shuffle-failure")["statement"]
    assert re.search(r"\(seed \d+\)", statement)
    assert "adds" in statement


def test_live_jest_shuffle_records_its_seed(tmp_path: Path) -> None:
    _live_bin("jest")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "__tests__").mkdir()
    (repo / "package.json").write_text(json.dumps({
        "name": "example", "version": "1.0.0",
        "devDependencies": {"jest": "30.5.2"},
    }), encoding="utf-8")
    (repo / "__tests__" / "example.test.js").write_text(
        'test("adds", () => { expect(1 + 2).toBe(4); });\n', encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("jest-shuffle")],
    ) == 0
    _valid(output)
    assert _severity(output, "shuffle-failure") == "fix-later"
    statement = _finding(output, "shuffle-failure")["statement"]
    assert re.search(r"\(seed \d+\)", statement)
    assert "adds" in statement


def test_live_knip_reports_a_new_unused_file(tmp_path: Path) -> None:
    _live_bin("knip")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "example", "version": "1.0.0"}), encoding="utf-8"
    )
    (repo / "knip.json").write_text(
        json.dumps({"entry": ["src/index.js"]}), encoding="utf-8"
    )
    (repo / "src" / "index.js").write_text(
        "export const used = 1;\n", encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "src" / "unused.js").write_text(
        "export const lonely = 1;\n", encoding="utf-8"
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("knip")],
    ) == 0
    _valid(output)
    assert _severity(output, "unused-file") == "note"
    assert _finding(output, "unused-file")["location"]["file"] == "src/unused.js"


def test_live_dependency_cruiser_reports_a_new_cycle(tmp_path: Path) -> None:
    _live_bin("dependency-cruiser")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "package.json").write_text(
        json.dumps({"name": "example", "version": "1.0.0"}), encoding="utf-8"
    )
    (repo / ".dependency-cruiser.json").write_text(json.dumps({"forbidden": [{
        "name": "no-circular", "severity": "error",
        "from": {}, "to": {"circular": True},
    }]}), encoding="utf-8")
    (repo / "src" / "a.js").write_text(
        "import './b.js';\nexport const a = 1;\n", encoding="utf-8"
    )
    (repo / "src" / "b.js").write_text("export const b = 2;\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "b.js").write_text(
        "import './a.js';\nexport const b = 2;\n", encoding="utf-8"
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("dependency-cruiser")],
    ) == 0
    _valid(output)
    assert _severity(output, "no-circular") == "blocks"


def test_live_stryker_runs_or_degrades_through_a_recorded_path(tmp_path: Path) -> None:
    _live_bin("stryker")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "__tests__").mkdir()
    (repo / "package.json").write_text(json.dumps({
        "name": "example", "version": "1.0.0",
        "devDependencies": {"jest": "30.5.2"},
    }), encoding="utf-8")
    (repo / "src" / "add.js").write_text(
        "function add(a, b) {\n  return a + b;\n}\nmodule.exports = { add };\n",
        encoding="utf-8",
    )
    (repo / "__tests__" / "add.test.js").write_text(
        'const { add } = require("../src/add.js");\n'
        'test("adds", () => { expect(add(1, 2)).toBe(3); });\n',
        encoding="utf-8",
    )
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("stryker")],
    ) == 0
    _valid(output)
    # The test-runner plugin may or may not be installed where the binary runs:
    # either way the adapter engaged the real tool and the outcome validates.
    assert _read(output, "findings.json") or _degraded(output, "stryker")
