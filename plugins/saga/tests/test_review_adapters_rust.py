"""Rust adapters map recorded output onto the lens rows (issue 153)."""

from __future__ import annotations

import importlib.util
import json
import os
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

_RUST_VERSIONS = {
    "cargo": "1.98.1",
    "cargo-deny": "0.20.2",
    "cargo-clippy": "0.1.98",
    "cargo-mutants": "27.1.0",
    "cargo-machete": "0.9.2",
}

_DENY_CLEAN = (
    '{"fields":{"advisories":{"errors":0,"helps":0,"notes":0,"warnings":0}},'
    '"type":"summary"}\n'
)


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
A = _load("review_adapters_rust")
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
        tool: {"version": version} for tool, version in _RUST_VERSIONS.items()
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
        self.versions = versions if versions is not None else dict(_RUST_VERSIONS)
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


def test_each_rust_adapter_declares_its_design_row() -> None:
    assert {item.id: item.comparison for item in A.ADAPTERS} == {
        "cargo-deny": "base-head",
        "cargo-check": "base-head",
        "clippy": "lines",
        "cargo-mutants": "lines",
        "cargo-machete": "base-head",
        "rustfmt": "lines",
        "rust-shuffle": "lines",
        "rust-no-network": "lines",
        "rust-coverage": "lines",
    }
    assert _adapter("cargo-mutants").mutation is True
    assert _adapter("cargo-check").type_checker is True
    assert _adapter("cargo-deny").stream == "stderr"
    assert _adapter("cargo-mutants").report_file == "mutants.out/outcomes.json"
    assert _adapter("rust-shuffle").gap_first is True
    assert _adapter("rust-no-network").gap_first is True
    assert _adapter("rustfmt").mode == "fix"
    assert _adapter("rust-coverage").tool == ""


def test_no_adapter_id_mentions_nextest() -> None:
    for item in A.ADAPTERS:
        assert "nextest" not in item.id
    document = yaml.safe_load(
        (REPO_ROOT / "plugins" / "saga" / "references" / "review-tools.yaml")
        .read_text(encoding="utf-8")
    )
    assert isinstance(document, dict)
    tools = document.get("tools")
    assert isinstance(tools, list)
    for row in tools:
        assert isinstance(row, dict)
        assert "nextest" not in str(row.get("id") or "")


def test_cvss_vectors_score_to_their_published_bands() -> None:
    assert A.cvss31_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H") == 10.0
    assert A.cvss31_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8
    assert A.cvss31_score("CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H") == 6.2
    assert A.cvss31_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N") == 6.1
    assert A.cvss31_score("CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N") == 1.6
    assert A.cvss31_score("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8
    assert A.cvss31_score(
        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/E:P/RL:O/RC:C"
    ) == 9.8
    assert A.cvss31_score("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H") is None
    assert A.cvss31_score("CVSS:2.0/AV:N/AC:L/Au:N/C:C/I:C/A:C") is None
    assert A.cvss31_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H") is None
    assert A.cvss31_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:X") is None
    assert A.cvss31_score("not a vector") is None
    assert A.cvss31_score(None) is None


def _rust_repo(
    tmp_path: Path, *, manifest: str | None = None, lock: bool = True,
    deny: str | None = None,
) -> tuple[Path, Path]:
    """A Rust bin repo with src/main.rs. Returns the repo and the source file."""
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    if manifest is None:
        manifest = (
            '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        )
    (repo / "Cargo.toml").write_text(manifest, encoding="utf-8")
    if lock:
        (repo / "Cargo.lock").write_text(
            'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
    if deny is not None:
        (repo / "deny.toml").write_text(deny, encoding="utf-8")
    source = repo / "src" / "main.rs"
    source.write_text(
        "fn main() {\n"
        '    println!("example");\n'
        "}\n",
        encoding="utf-8",
    )
    return repo, source


def test_deny_maps_severities_to_rows(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(
        base, "", stderr=_fixture("cargo-deny.jsonl"), base_stderr=_DENY_CLEAN,
        code=1, base_code=0,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-deny")], runner,
    ) == 0
    _valid(output)
    assert _severity(output, "CVE-2026-0001") == "blocks"
    assert _severity(output, "RUSTSEC-2026-0002") == "fix-later"
    assert _severity(output, "RUSTSEC-2026-0003") == "blocks"
    assert _severity(output, "RUSTSEC-2026-0004") == "fix-later"
    assert _severity(output, "RUSTSEC-2026-0005") == "fix-later"
    assert _severity(output, "yanked-example-yanked") == "fix-later"
    refs = {finding["rule"]["ref"] for finding in _read(output, "findings.json")}
    assert "RUSTSEC-2026-0009" not in refs
    assert _finding(output, "CVE-2026-0001")["location"]["file"] == "Cargo.lock"


def test_deny_preexisting_advisory_drops(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    payload = _fixture("cargo-deny.jsonl")
    runner = _Calls(base, "", stderr=payload, base_stderr=payload, code=1, base_code=1)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-deny")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_deny_high_blocks_unless_the_builder_excuses_it(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = _profile(tmp_path / "profile.json")
    home = tmp_path / "home"
    first = tmp_path / "first"
    assert _run(
        repo, base, head, profile, first, home,
        [_adapter("cargo-deny")],
        _Calls(base, "", stderr=_fixture("cargo-deny.jsonl"),
               base_stderr=_DENY_CLEAN, code=1),
    ) == 0
    assert _severity(first, "CVE-2026-0001") == "blocks"
    finding = _finding(first, "CVE-2026-0001")
    builder = {
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": "U3",
        "acceptance_criteria": [{
            "id": "AC-4",
            "text": "A scored high advisory blocks unless a reason is recorded.",
            "checks": ["cargo-deny"],
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
        [_adapter("cargo-deny")],
        _Calls(base, "", stderr=_fixture("cargo-deny.jsonl"),
               base_stderr=_DENY_CLEAN, code=1),
        builder=builder_path,
    ) == 0
    assert _severity(second, "CVE-2026-0001") == "note"


def test_deny_and_osv_merge_into_one_scored_finding(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"review_tools": {"pins": {
        "cargo-deny": {"version": "0.20.2"},
        "osv-scanner": {"version": "1.0.0"},
    }}}), encoding="utf-8")
    deny_payload = _fixture("cargo-deny.jsonl")
    osv_payload = _fixture("osv-scanner.json")
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False and isinstance(argv, list)
        calls.append(list(argv))
        tool = Path(argv[0]).name
        if "--version" in argv:
            pin = {"cargo-deny": "0.20.2", "osv-scanner": "1.0.0"}.get(tool, "1.0.0")
            return T.ProcessResult(0, f"{pin}\n")
        at_base = _git(Path(cwd), "rev-parse", "HEAD") == base
        if tool == "cargo-deny":
            err = _DENY_CLEAN if at_base else deny_payload
            return T.ProcessResult(0 if at_base else 1, "", err)
        if tool == "osv-scanner":
            body = "{}" if at_base else osv_payload
            return T.ProcessResult(0, body)
        raise AssertionError(argv)

    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    osv = next(item for item in C.ADAPTERS if item.id == "osv-scanner")
    assert T.run(
        repo, base, head, profile, output, home=home,
        adapters=[_adapter("cargo-deny"), osv], runner=runner, framework=False,
    ) == 0
    _valid(output)
    merged = [
        finding for finding in _read(output, "findings.json")
        if finding["rule"]["ref"] == "CVE-2026-0001"
    ]
    assert len(merged) == 1
    assert merged[0]["source"]["name"] == "cargo-deny"
    assert _severity(output, "CVE-2026-0001") == "blocks"


def test_deny_stages_base_config_and_ignores_head(tmp_path: Path) -> None:
    base_config = "[advisories]\n"
    repo, _source = _rust_repo(tmp_path, deny=base_config)
    base = _commit(repo, "base")
    (repo / "deny.toml").write_text(
        "[advisories]\nignore = [\"RUSTSEC-2026-0001\"]\n", encoding="utf-8"
    )
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, "", stderr=_fixture("cargo-deny.jsonl"), base_stderr=_DENY_CLEAN,
        code=1, watch=("deny.toml",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-deny")], runner,
    ) == 0
    assert _severity(output, "CVE-2026-0001") == "blocks"
    runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["cargo-deny"] and at_base is not None
    ]
    assert runs, "cargo-deny never ran"
    for argv, _at_base, state in runs:
        assert state["deny.toml"] == base_config
        assert "--config" in argv


def test_deny_generated_empty_config_when_base_has_none(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    runner = _Calls(
        base, "", stderr=_fixture("cargo-deny.jsonl"), base_stderr=_DENY_CLEAN,
        code=1, watch=("deny.toml",), snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-deny")], runner,
    ) == 0
    runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["cargo-deny"] and at_base is not None
    ]
    assert runs, "cargo-deny never ran"
    for _argv, _at_base, state in runs:
        assert state["deny.toml"] == A._GENERATED_DENY_CONFIG


def test_deny_needs_a_cargo_lockfile(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path, lock=False)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(
        base, "", stderr=_fixture("cargo-deny.jsonl"), base_stderr=_DENY_CLEAN,
        code=1,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-deny")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _degraded(output, "cargo-deny") == []
    assert all("--version" in call for call in runner.calls)


def test_check_error_in_untouched_file_blocks(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("cargo-check.jsonl"), base_payload="", code=101)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-check")], runner,
    ) == 0
    _valid(output)
    findings = _read(output, "findings.json")
    assert {finding["rule"]["ref"] for finding in findings} == {"E0308"}
    assert _severity(output, "E0308") == "blocks"
    assert _finding(output, "E0308")["location"]["file"] == "src/main.rs"
    runs = [
        call for call in runner.calls
        if call[:1] == ["cargo"] and "--version" not in call
    ]
    assert len(runs) == 2
    for argv in runs:
        assert argv == ["cargo", "check", "--locked", "--message-format=json"]


def test_check_moved_diagnostic_matches_and_drops(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    moved = _fixture("cargo-check.jsonl").replace('"line_start": 2', '"line_start": 12')
    output = tmp_path / "out"
    runner = _Calls(base, moved, base_payload=_fixture("cargo-check.jsonl"), code=101)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-check")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_check_clean_run_writes_nothing(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", base_payload="")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-check")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _degraded(output, "cargo") == []


def test_check_strips_a_registry_redirect(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    (repo / ".cargo").mkdir()
    (repo / ".cargo" / "config.toml").write_text(
        "[source.crates-io]\nreplace-with = 'vendored'\n", encoding="utf-8"
    )
    (repo / ".cargo" / "config").write_text(
        "[source.crates-io]\nreplace-with = 'vendored'\n", encoding="utf-8"
    )
    nested = repo / "crates" / "member" / ".cargo"
    nested.mkdir(parents=True)
    (nested / "config.toml").write_text(
        "[source.crates-io]\nreplace-with = 'vendored'\n", encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / ".cargo" / "config.toml").write_text(
        "[source.crates-io]\nreplace-with = 'evil'\n", encoding="utf-8"
    )
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    snapshots: list[tuple[list[str], bool | None, dict[str, str | None]]] = []
    watched = (
        ".cargo/config.toml", ".cargo/config",
        "crates/member/.cargo/config.toml",
    )
    runner = _Calls(
        base, _fixture("cargo-check.jsonl"), base_payload="", code=101,
        watch=watched, snapshots=snapshots,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-check")], runner,
    ) == 0
    assert _severity(output, "E0308") == "blocks"
    runs = [
        (argv, at_base, state) for argv, at_base, state in snapshots
        if argv[:1] == ["cargo"] and at_base is not None
    ]
    assert runs, "cargo check never ran"
    for _argv, _at_base, state in runs:
        for name in watched:
            assert state[name] is None


def test_each_cargo_run_gets_a_fresh_cargo_home(tmp_path: Path) -> None:
    repo, source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    return a + b + 0;\n"
    text[5] = "    let unused_var = 2;\n"
    text[6] = "    let _zero = 0.0 / 0.0 + 0.0;\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    home = tmp_path / "home"
    env_seen: list[dict[str, str]] = []
    runner = _Calls(base, _fixture("clippy.jsonl"), code=101, env_seen=env_seen)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home, [_adapter("clippy")], runner,
    ) == 0
    assert _severity(output, "clippy::eq_op") == "blocks"
    shared = home / ".saga" / "cargo-home"
    assert shared.is_dir()
    probes = [
        env for call, env in zip(runner.calls, runner.env_seen)
        if "--version" in call
    ]
    runs = [
        env for call, env in zip(runner.calls, runner.env_seen)
        if "--version" not in call
    ]
    assert probes and runs
    for env in probes:
        assert env["CARGO_HOME"] == str(shared)
    for env in runs:
        assert env["CARGO_HOME"] != str(shared)
        assert not Path(env["CARGO_HOME"]).exists()


def test_rust_env_carries_rustup_home_under_fresh_homes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rustup proxy finds its toolchain under the adapter's fresh HOME.

    ``RUSTUP_HOME`` (and ``RUSTUP_TOOLCHAIN`` when set) pass through the
    allow-list, while HOME stays fresh and CARGO_HOME stays per-run, so the
    proxy resolves a toolchain without seeing operator credentials.
    """
    rustup_home = tmp_path / "rustup"
    rustup_home.mkdir()
    monkeypatch.setenv("RUSTUP_HOME", str(rustup_home))
    monkeypatch.setenv("RUSTUP_TOOLCHAIN", "stable-example-triple")
    repo, _source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    home = tmp_path / "home"
    env_seen: list[dict[str, str]] = []
    runner = _Calls(base, _fixture("clippy.jsonl"), code=101, env_seen=env_seen)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home, [_adapter("clippy")], runner,
    ) == 0
    assert env_seen, "no process env captured"
    shared = home / ".saga" / "cargo-home"
    for env in env_seen:
        assert env["RUSTUP_HOME"] == str(rustup_home)
        assert env["RUSTUP_TOOLCHAIN"] == "stable-example-triple"
        assert env["HOME"] != os.environ.get("HOME")
        assert Path(env["HOME"]).is_absolute()
        assert env["PATH"] == os.environ.get("PATH")
    probes = [env for call, env in zip(runner.calls, env_seen) if "--version" in call]
    runs = [env for call, env in zip(runner.calls, env_seen) if "--version" not in call]
    assert probes and runs
    for env in probes:
        assert env["CARGO_HOME"] == str(shared)
    for env in runs:
        assert env["CARGO_HOME"] != str(shared)
        assert not Path(env["CARGO_HOME"]).exists()


def test_rust_env_defaults_rustup_home_to_the_real_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RUSTUP_HOME", raising=False)
    monkeypatch.delenv("RUSTUP_TOOLCHAIN", raising=False)
    repo, _source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    env_seen: list[dict[str, str]] = []
    runner = _Calls(base, _fixture("clippy.jsonl"), code=101, env_seen=env_seen)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("clippy")], runner,
    ) == 0
    assert env_seen, "no process env captured"
    for env in env_seen:
        assert env["RUSTUP_HOME"] == str(Path.home() / ".rustup")
        assert "RUSTUP_TOOLCHAIN" not in env


def test_deny_degrades_when_head_removes_the_lockfile(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "Cargo.lock").unlink()
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    payload = _fixture("cargo-deny.jsonl")
    runner = _Calls(base, payload, base_payload=payload)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-deny")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo-deny")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "lockfile-removed"


def test_mutants_ignores_a_preseeded_report(tmp_path: Path) -> None:
    repo, source = _mutants_repo(tmp_path)
    (repo / "mutants.out").mkdir()
    (repo / "mutants.out" / "outcomes.json").write_text(
        _fixture("mutants-outcomes.json"), encoding="utf-8"
    )
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    a + b + 0\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "2 mutants missed.\n")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo-mutants")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "unparseable"


def _clippy_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo, source = _rust_repo(tmp_path)
    source.write_text(
        "fn add(a: i32, b: i32) -> i32 {\n"
        "    return a + b;\n"
        "}\n"
        "\n"
        "fn main() {\n"
        "    let unused_var = 1;\n"
        "    let _zero = 0.0 / 0.0;\n"
        '    println!("done");\n'
        "}\n",
        encoding="utf-8",
    )
    return repo, source


def test_clippy_error_blocks_warning_fixes_later(tmp_path: Path) -> None:
    repo, source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    return a + b + 0;\n"
    text[5] = "    let unused_var = 2;\n"
    text[6] = "    let _zero = 0.0 / 0.0 + 0.0;\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("clippy.jsonl"), code=101)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("clippy")], runner,
    ) == 0
    _valid(output)
    assert _severity(output, "clippy::eq_op") == "blocks"
    assert _severity(output, "unused_variables") == "fix-later"
    assert _severity(output, "clippy::needless_return") == "fix-later"
    refs = {finding["rule"]["ref"] for finding in _read(output, "findings.json")}
    assert "E0308" not in refs
    runs = [
        call for call in runner.calls
        if Path(call[0]).name == "cargo-clippy" and "--version" not in call
    ]
    assert len(runs) == 1
    assert runs[0] == [
        "cargo-clippy", "clippy", "--locked", "--message-format=json", "--",
        "-D", "clippy::correctness",
        "-W", "clippy::suspicious",
        "-W", "clippy::style",
        "-W", "clippy::complexity",
        "-W", "clippy::perf",
    ]


def test_clippy_warning_off_change_drops(tmp_path: Path) -> None:
    repo, _source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("clippy.jsonl"), code=101)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("clippy")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_clippy_hostile_manifest_allow_does_not_disarm_argv(tmp_path: Path) -> None:
    repo, source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        "\n[lints.clippy]\nneedless_return = \"allow\"\n",
        encoding="utf-8",
    )
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    return a + b + 0;\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("clippy.jsonl"), code=101)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("clippy")], runner,
    ) == 0
    assert _severity(output, "clippy::needless_return") == "fix-later"
    runs = [
        call for call in runner.calls
        if Path(call[0]).name == "cargo-clippy" and "--version" not in call
    ]
    assert len(runs) == 1
    assert "-W" in runs[0] and "clippy::style" in runs[0]


def test_clippy_unparseable_output_is_degraded(tmp_path: Path) -> None:
    repo, source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    return a + b + 0;\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "this is not a compiler stream\n", code=101)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("clippy")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo-clippy")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "unparseable"


def test_inline_allow_is_noted_not_applied(tmp_path: Path) -> None:
    repo, source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    return a + b + 0;\n"
    text.insert(0, "#[allow(clippy::needless_return)]\n")
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("clippy.jsonl"), code=101)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("clippy")], runner,
    ) == 0
    notes = {
        (item["tool"], item["reason"]) for item in _read(output, "degraded.json")
    }
    assert ("clippy", "rust-allow") in notes



def _rooted_clippy(*, reverse: bool) -> str:
    """The clippy fixture as a real run prints it: scan-root paths, one span absolute."""
    text = _fixture("clippy.jsonl").replace("/private/tmp/rust-probe", "@ROOT@")
    text = text.replace('"file_name": "src/main.rs"', '"file_name": "@ROOT@/src/main.rs"', 1)
    lines = text.splitlines(keepends=True)
    return "".join(reversed(lines) if reverse else lines)


def test_clippy_runs_differing_in_scratch_folder_and_order_record_identical_bytes(
    tmp_path: Path,
) -> None:
    """Issue 244: same findings, other scratch folder and build order, same packet bytes."""
    repo, source = _clippy_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    return a + b + 0;\n"
    text[5] = "    let unused_var = 2;\n"
    text[6] = "    let _zero = 0.0 / 0.0 + 0.0;\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    outputs = []
    for reverse in (False, True):
        output = tmp_path / f"out-{reverse}"
        assert _run(
            repo, base, head, _profile(tmp_path / "profile.json"), output,
            tmp_path / "home", [_adapter("clippy")],
            _Calls(base, _rooted_clippy(reverse=reverse), code=101),
        ) == 0
        outputs.append(output)
    for name in ("findings.json", "degraded.json", "outcomes.json"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), name
    files = {finding["location"]["file"] for finding in _read(outputs[0], "findings.json")}
    assert files == {"src/main.rs"}
    assert "@ROOT@" not in (outputs[0] / "findings.json").read_text(encoding="utf-8")


def test_cargo_stream_is_stored_sorted() -> None:
    assert A._stable_cargo_stream('{"b":1}\n\n{"a":1}\n') == '{"a":1}\n{"b":1}\n'


def _mutants_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (repo / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    source = repo / "src" / "lib.rs"
    source.write_text(
        "pub fn add(a: i32, b: i32) -> i32 {\n"
        "    a + b\n"
        "}\n",
        encoding="utf-8",
    )
    return repo, source


def test_mutants_survivor_on_changed_lines_blocks(tmp_path: Path) -> None:
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    text = source.read_text(encoding="utf-8").splitlines(keepends=True)
    text[1] = "    a + b + 0\n"
    source.write_text("".join(text), encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(
        base, "2 mutants missed.\n",
        files={"mutants.out/outcomes.json": _fixture("mutants-outcomes.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    _valid(output)
    findings = _read(output, "findings.json")
    assert len(findings) == 2
    assert {finding["rule"]["ref"] for finding in findings} == {"surviving-mutant"}
    assert findings[0]["location"]["file"] == "src/lib.rs"
    assert _severity(output, "surviving-mutant") == "blocks"


def test_mutants_past_deadline_records_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(T, "MUTATION_CAP_SECONDS", -1)
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(
        base, "2 mutants missed.\n",
        files={"mutants.out/outcomes.json": _fixture("mutants-outcomes.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo-mutants")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "cap"


def test_mutants_killed_run_records_cap(tmp_path: Path) -> None:
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", timeout_tools=("cargo-mutants",))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo-mutants")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "cap"


def test_mutants_reads_the_report_file_not_stdout(tmp_path: Path) -> None:
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "2 mutants missed.\n")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo-mutants")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "unparseable"



def _mutant_runs(runner: Any) -> list[list[str]]:
    return [
        call for call in runner.calls
        if Path(call[0]).name == "cargo-mutants" and "--version" not in call
    ]


class _DiffCalls(_Calls):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.diffs: list[tuple[Path, str, Path]] = []

    def __call__(self, argv: list[str], *, cwd: Path, **kwargs: Any) -> Any:
        if "--in-diff" in argv:
            path = Path(argv[argv.index("--in-diff") + 1])
            self.diffs.append((path, path.read_text(encoding="utf-8"), Path(cwd)))
        return super().__call__(argv, cwd=cwd, **kwargs)


def test_mutants_mutate_only_the_change_through_in_diff(tmp_path: Path) -> None:
    """Issue 244: cargo-mutants gets the change's diff instead of the whole workspace."""
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _DiffCalls(
        base, "", files={"mutants.out/outcomes.json": _fixture("mutants-outcomes.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    runs = _mutant_runs(runner)
    assert len(runs) == 1
    assert "--in-diff" in runs[0]
    # A change in a non-root workspace member must be mutated too.
    assert "--workspace" in runs[0]
    path, diff, root = runner.diffs[0]
    assert "+++ b/src/lib.rs" in diff and "+    a + b + 0" in diff
    # The diff lives outside the untrusted scanned tree, and dies with the run.
    assert root not in path.parents
    assert not path.exists()


def test_mutants_diff_is_not_written_through_a_planted_symlink(tmp_path: Path) -> None:
    """The reviewed commit cannot redirect saga's diff write with a symlink in its tree."""
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")
    (repo / "target" / "saga-review").mkdir(parents=True)
    (repo / "target" / "saga-review" / "in-diff.patch").symlink_to(victim)
    (repo / "in-diff.patch").symlink_to(victim)
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    _git(repo, "add", "-f", "-A")
    _git(repo, "commit", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")
    runner = _DiffCalls(
        base, "", files={"mutants.out/outcomes.json": _fixture("mutants-outcomes.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), tmp_path / "out",
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    assert victim.read_text(encoding="utf-8") == "untouched\n"
    assert runner.diffs and "+    a + b + 0" in runner.diffs[0][1]

def test_mutants_change_without_rust_lines_records_nothing_to_mutate(tmp_path: Path) -> None:
    """A README-only change neither runs cargo-mutants nor reaches its timeout."""
    repo, _source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", timeout_tools=("cargo-mutants",))
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    assert _mutant_runs(runner) == []
    assert [item["reason"] for item in _degraded(output, "cargo-mutants")] == [
        "nothing-to-mutate"
    ]


def test_mutants_no_mutant_on_changed_lines_records_nothing_to_mutate(tmp_path: Path) -> None:
    """cargo-mutants exits 0 with no report when the changed lines hold no mutant."""
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    // note\n    a + b\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", stderr=" INFO No mutants to filter\n")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    assert len(_mutant_runs(runner)) == 1
    assert _read(output, "findings.json") == []
    assert [item["reason"] for item in _degraded(output, "cargo-mutants")] == [
        "nothing-to-mutate"
    ]


def test_mutants_timings_do_not_change_the_recorded_bytes(tmp_path: Path) -> None:
    report = json.loads(_fixture("mutants-outcomes.json"))
    outputs = []
    for second in (1, 2):
        (tmp_path / f"run-{second}").mkdir()
        repo, source = _mutants_repo(tmp_path / f"run-{second}")
        base = _commit(repo, "base")
        source.write_text(
            source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
            encoding="utf-8",
        )
        head = _commit(repo, "head")
        timed = dict(report)
        timed["start_time"] = f"2026-10-15T00:00:0{second}Z"
        timed["end_time"] = f"2026-10-15T00:01:0{second}Z"
        timed["outcomes"] = [
            {**item, "phase_results": [{"phase": "Test", "duration": second / 10}]}
            for item in (report["outcomes"] if second == 1 else reversed(report["outcomes"]))
        ]
        output = tmp_path / f"out-{second}"
        runner = _Calls(base, "", files={"mutants.out/outcomes.json": json.dumps(timed)})
        assert _run(
            repo, base, head, _profile(tmp_path / f"profile-{second}.json"), output,
            tmp_path / "home", [_adapter("cargo-mutants")], runner,
        ) == 0
        outputs.append(_read(output, "findings.json"))
    assert outputs[0] and outputs[0] == outputs[1]


@pytest.mark.parametrize(("configured", "on_path", "wanted"), [
    (False, True, False),
    (True, True, True),
    (True, False, False),
])
def test_mutants_use_nextest_only_when_the_repository_configures_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    configured: bool, on_path: bool, wanted: bool,
) -> None:
    """Issue 253: nextest on PATH alone made ripgrep's baseline fail; the repository decides."""
    real_which = shutil.which
    repo, source = _mutants_repo(tmp_path)
    if configured:
        (repo / ".config").mkdir()
        (repo / ".config" / "nextest.toml").write_text("[profile.default]\n", encoding="utf-8")
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")

    def fake_which(name: str, *args: Any, **kwargs: Any) -> str | None:
        if name == "cargo-nextest":
            return "/opt/cargo/bin/cargo-nextest" if on_path else None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(A.shutil, "which", fake_which)
    output = tmp_path / "out"
    runner = _Calls(
        base, "2 mutants missed.\n",
        files={"mutants.out/outcomes.json": _fixture("mutants-outcomes.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    runs = _mutant_runs(runner)
    assert len(runs) == 1
    assert "-C" in runs[0] and "--locked" in runs[0]
    assert ("--test-tool" in runs[0] and "nextest" in runs[0]) is wanted
    assert "nextest" not in json.dumps(_read(output, "degraded.json"))


def _mutants_exit(tmp_path: Path, code: int, report: str) -> Path:
    """One cargo-mutants run on a changed line 2 that exits ``code`` with ``report``."""
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", code=code, files={"mutants.out/outcomes.json": report})
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    _valid(output)
    return output


def test_mutants_exit_2_survivors_are_findings(tmp_path: Path) -> None:
    """cargo-mutants 27.1.0 exits 2 when a mutant survives (real report, five missed)."""
    output = _mutants_exit(tmp_path, 2, _fixture("mutants-27.1.0-exit-2.json"))
    findings = _read(output, "findings.json")
    assert len(findings) == 5
    assert {finding["rule"]["ref"] for finding in findings} == {"surviving-mutant"}
    assert _degraded(output, "cargo-mutants") == []


def test_mutants_exit_3_timeout_is_a_degraded_row_not_a_clean_run(tmp_path: Path) -> None:
    """Exit 3 (a mutant timed out) parses, but a timeout never reads as every mutant caught."""
    output = _mutants_exit(tmp_path, 3, _fixture("mutants-27.1.0-exit-3.json"))
    assert _read(output, "findings.json") == []
    assert [(item["input"], item["reason"]) for item in _degraded(output, "cargo-mutants")] == [
        ("testing.surviving-mutant", "mutant-timeout")
    ]


def test_mutants_timeout_still_reports_the_survivors(tmp_path: Path) -> None:
    """A run with a timed-out mutant and missed ones keeps every survivor as a finding."""
    report = json.loads(_fixture("mutants-27.1.0-exit-2.json"))
    timeout = json.loads(_fixture("mutants-27.1.0-exit-3.json"))
    report["outcomes"].extend(
        item for item in timeout["outcomes"] if item["summary"] == "Timeout"
    )
    output = _mutants_exit(tmp_path, 3, json.dumps(report))
    assert len(_read(output, "findings.json")) == 5
    assert [item["reason"] for item in _degraded(output, "cargo-mutants")] == ["mutant-timeout"]


def test_mutants_exit_4_records_a_failed_baseline_and_keeps_the_report(tmp_path: Path) -> None:
    """Exit 4: the unmutated tree failed its tests. Its own reason, and the report is kept."""
    report = _fixture("mutants-27.1.0-exit-4.json")
    output = _mutants_exit(tmp_path, 4, report)
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo-mutants")
    assert [item["reason"] for item in degraded] == ["baseline-failed"]
    stored = tmp_path / "home" / ".saga" / "review-output" / degraded[0]["raw_output"]
    assert json.loads(stored.read_text(encoding="utf-8"))["outcomes"][0]["summary"] == "Failure"
    assert stored.read_bytes() == A._stable_mutants(report).encode()


class _FlakyBaseline(_Calls):
    """cargo-mutants exits 4 (baseline failed) for its first ``failures`` runs, then ``code``."""

    def __init__(self, *args: Any, failures: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.failures = failures
        self.runs = 0

    def __call__(self, argv: list[str], *, cwd: Path, **kwargs: Any) -> Any:
        result = super().__call__(argv, cwd=cwd, **kwargs)
        if self._tool(argv) != "cargo-mutants" or "--version" in argv:
            return result
        self.runs += 1
        if self.runs <= self.failures:
            return T.ProcessResult(4, result.stdout, result.stderr)
        return result


def _flaky_baseline(tmp_path: Path, failures: int) -> tuple[Path, _FlakyBaseline]:
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _FlakyBaseline(
        base, "", code=2, failures=failures,
        files={"mutants.out/outcomes.json": _fixture("mutants-27.1.0-exit-2.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    _valid(output)
    return output, runner


def test_mutants_failed_baseline_is_retried_once_and_a_pass_keeps_the_result(
    tmp_path: Path,
) -> None:
    """Issue 260: a baseline that failed under load and passes on the retry is a normal result."""
    output, runner = _flaky_baseline(tmp_path, failures=1)
    assert len(_mutant_runs(runner)) == 2
    assert len(_read(output, "findings.json")) == 5
    assert [(item["input"], item["reason"]) for item in _degraded(output, "cargo-mutants")] == [
        ("testing.surviving-mutant", "baseline-flaky")
    ]


def test_mutants_baseline_that_fails_twice_is_recorded_once_as_failed(tmp_path: Path) -> None:
    output, runner = _flaky_baseline(tmp_path, failures=5)
    assert len(_mutant_runs(runner)) == 2
    assert _read(output, "findings.json") == []
    assert [item["reason"] for item in _degraded(output, "cargo-mutants")] == ["baseline-failed"]


def test_mutants_that_pass_first_time_run_once_with_no_flaky_note(tmp_path: Path) -> None:
    output, runner = _flaky_baseline(tmp_path, failures=0)
    assert len(_mutant_runs(runner)) == 1
    assert _degraded(output, "cargo-mutants") == []


class _Clock:
    """A stand-in for the ``time`` module in review_tools that only the test advances."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


class _SlowFirstRun(_FlakyBaseline):
    """The first cargo-mutants run fails its baseline after ``spend`` seconds on the clock."""

    def __init__(self, *args: Any, clock: _Clock, spend: float, **kwargs: Any) -> None:
        super().__init__(*args, failures=1, **kwargs)
        self.clock = clock
        self.spend = spend
        self.timeouts: list[int] = []

    def __call__(self, argv: list[str], *, cwd: Path, **kwargs: Any) -> Any:
        if self._tool(argv) == "cargo-mutants" and "--version" not in argv:
            self.timeouts.append(kwargs["timeout"])
            if not self.timeouts[1:]:
                self.clock.now += self.spend
        return super().__call__(argv, cwd=cwd, **kwargs)


def _slow_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spend: float,
) -> tuple[Path, _SlowFirstRun]:
    clock = _Clock()
    monkeypatch.setattr(T, "time", clock)
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _SlowFirstRun(
        base, "", code=2, clock=clock, spend=spend,
        files={"mutants.out/outcomes.json": _fixture("mutants-27.1.0-exit-2.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    return output, runner


def test_mutants_retry_is_clamped_to_the_time_left_under_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue 260 review: the second run may not take the adapter's full timeout past the cap."""
    left = 100
    output, runner = _slow_baseline(
        tmp_path, monkeypatch, spend=T.MUTATION_CAP_SECONDS - left,
    )
    assert runner.timeouts == [600, left]
    assert len(_read(output, "findings.json")) == 5


def test_mutants_retry_uses_fractional_time_left_under_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, runner = _slow_baseline(
        tmp_path, monkeypatch, spend=T.MUTATION_CAP_SECONDS - 0.5,
    )
    assert runner.timeouts == [600, 0.5]
    assert len(_read(output, "findings.json")) == 5
    assert [item["reason"] for item in _degraded(output, "cargo-mutants")] == ["baseline-flaky"]


def test_mutants_retry_is_capped_when_no_time_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, runner = _slow_baseline(tmp_path, monkeypatch, spend=T.MUTATION_CAP_SECONDS)
    assert len(runner.timeouts) == 1
    assert _read(output, "findings.json") == []
    assert [item["reason"] for item in _degraded(output, "cargo-mutants")] == ["cap"]


def _in_diff_context(tmp_path: Path, scratch: Path) -> Any:
    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    _commit(repo, "head")
    return T.ScanContext(repo, repo, tmp_path / "home", base=base, scratch=scratch)


def test_in_diff_is_rewritten_in_place_on_a_second_call(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    context = _in_diff_context(tmp_path, scratch)
    first = A._write_in_diff(context)
    first.write_text("stale\n", encoding="utf-8")
    assert A._write_in_diff(context) == first
    assert "+    a + b + 0" in first.read_text(encoding="utf-8")


def test_in_diff_is_not_written_through_a_scratch_folder_replaced_by_a_symlink(
    tmp_path: Path,
) -> None:
    """Issue 260 review: the first run's build can swap the folder; the retry must not follow."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    context = _in_diff_context(tmp_path, scratch)
    A._write_in_diff(context)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "in-diff.patch").write_text("keep\n", encoding="utf-8")
    scratch.rename(tmp_path / "moved")
    scratch.symlink_to(victim)
    with pytest.raises(T.ToolGap) as caught:
        A._write_in_diff(context)
    assert caught.value.reason == "diff-unavailable"
    assert (victim / "in-diff.patch").read_text(encoding="utf-8") == "keep\n"


def test_a_retry_after_the_scratch_folder_was_swapped_records_baseline_failed(
    tmp_path: Path,
) -> None:
    """End to end: the first run swaps the folder for a symlink; the retry declines."""
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "in-diff.patch").write_text("keep\n", encoding="utf-8")
    swapped: list[Path] = []

    class Swapper(_FlakyBaseline):
        def __call__(self, argv: list[str], *, cwd: Path, **kwargs: Any) -> Any:
            if self._tool(argv) == "cargo-mutants" and "--version" not in argv and not swapped:
                folder = Path(argv[argv.index("--in-diff") + 1]).parent
                folder.rename(folder.with_name(folder.name + "-moved"))
                folder.symlink_to(victim)
                swapped.append(folder)
            return super().__call__(argv, cwd=cwd, **kwargs)

    repo, source = _mutants_repo(tmp_path)
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    runner = Swapper(
        base, "", code=2, failures=1,
        files={"mutants.out/outcomes.json": _fixture("mutants-27.1.0-exit-2.json")},
    )
    try:
        assert _run(
            repo, base, head, _profile(tmp_path / "profile.json"), tmp_path / "out",
            tmp_path / "home", [_adapter("cargo-mutants")], runner,
        ) == 0
    finally:
        for folder in swapped:
            folder.unlink(missing_ok=True)
            shutil.rmtree(folder.with_name(folder.name + "-moved"), ignore_errors=True)
    assert len(_mutant_runs(runner)) == 1
    assert (victim / "in-diff.patch").read_text(encoding="utf-8") == "keep\n"
    assert [item["reason"] for item in _degraded(tmp_path / "out", "cargo-mutants")] == [
        "baseline-failed"
    ]


def _mutant_argv(tmp_path: Path, config: str | None) -> list[str]:
    repo, source = _mutants_repo(tmp_path)
    if config is not None:
        (repo / ".cargo").mkdir(exist_ok=True)
        (repo / ".cargo" / "mutants.toml").write_text(config, encoding="utf-8")
    base = _commit(repo, "base")
    source.write_text(
        source.read_text(encoding="utf-8").replace("    a + b\n", "    a + b + 0\n"),
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    runner = _Calls(
        base, "", code=2,
        files={"mutants.out/outcomes.json": _fixture("mutants-27.1.0-exit-2.json")},
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), tmp_path / "out",
        tmp_path / "home", [_adapter("cargo-mutants")], runner,
    ) == 0
    runs = _mutant_runs(runner)
    assert len(runs) == 1
    return runs[0]


def test_mutants_get_a_fixed_per_mutant_timeout_not_one_scaled_from_the_baseline(
    tmp_path: Path,
) -> None:
    """Issue 260: --timeout is explicit, so machine load cannot change which mutants time out."""
    argv = _mutant_argv(tmp_path, None)
    assert argv[argv.index("--timeout") + 1] == str(A._MUTANT_TEST_TIMEOUT)
    assert "--timeout-multiplier" not in argv and "--minimum-test-timeout" not in argv


@pytest.mark.parametrize("config", [
    "timeout_multiplier = 8\n",
    "minimum_test_timeout = 90\n",
    'exclude_globs = ["x"]\ntimeout_multiplier = 3.5\n',
])
def test_mutants_leave_the_timeout_to_a_repository_that_sets_its_own(
    tmp_path: Path, config: str,
) -> None:
    assert "--timeout" not in _mutant_argv(tmp_path, config)


@pytest.mark.parametrize("config", ['exclude_globs = ["x"]\n', "not = [valid toml\n", ""])
def test_mutants_keep_the_fixed_timeout_when_the_config_does_not_set_one(
    tmp_path: Path, config: str,
) -> None:
    assert "--timeout" in _mutant_argv(tmp_path, config)


def test_mutants_unparseable_report_keeps_the_raw_output(tmp_path: Path) -> None:
    output = _mutants_exit(tmp_path, 1, "not json\n")
    degraded = _degraded(output, "cargo-mutants")
    assert [item["reason"] for item in degraded] == ["unparseable"]
    stored = tmp_path / "home" / ".saga" / "review-output" / degraded[0]["raw_output"]
    assert stored.read_text(encoding="utf-8") == "not json\n"


def test_machete_unused_dependency_is_a_note(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(
        base, _fixture("cargo-machete.txt"),
        base_payload="cargo-machete didn't find any unused dependencies.\n",
        code=1,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-machete")], runner,
    ) == 0
    _valid(output)
    findings = _read(output, "findings.json")
    assert {finding["rule"]["ref"] for finding in findings} == {"unused-dependency"}
    assert _severity(output, "unused-dependency") == "note"
    assert _finding(output, "unused-dependency")["location"]["file"] == "Cargo.toml"


def test_machete_preexisting_entry_drops(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    payload = _fixture("cargo-machete.txt")
    runner = _Calls(base, payload, base_payload=payload, code=1, base_code=1)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-machete")], runner,
    ) == 0
    assert _read(output, "findings.json") == []


def test_machete_ignore_is_noted_not_applied(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        "\n[package.metadata.cargo-machete]\nignored = [\"example-lib\"]\n",
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(
        base, _fixture("cargo-machete.txt"),
        base_payload="cargo-machete didn't find any unused dependencies.\n",
        code=1,
    )
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-machete")], runner,
    ) == 0
    assert _severity(output, "unused-dependency") == "note"
    notes = {
        (item["tool"], item["reason"]) for item in _read(output, "degraded.json")
    }
    assert ("cargo-machete", "machete-ignore") in notes


def test_rustfmt_writes_no_record(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "")
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("rustfmt")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []
    assert runner.calls == []


def test_gap_adapters_record_without_running_a_binary(tmp_path: Path) -> None:
    repo, _source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("head\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, "", versions={})
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home",
        [_adapter("rust-shuffle"), _adapter("rust-no-network")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo")
    assert len(degraded) == 2
    assert {item["reason"] for item in degraded} == {"known-gap"}
    assert runner.calls == []


def test_gap_adapters_yield_nothing_without_markers(tmp_path: Path) -> None:
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
        tmp_path / "home",
        [_adapter("rust-shuffle"), _adapter("rust-no-network")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    assert _read(output, "degraded.json") == []


def test_removed_rust_markers_are_degraded(tmp_path: Path) -> None:
    repo, source = _rust_repo(tmp_path)
    base = _commit(repo, "base")
    (repo / "Cargo.toml").unlink()
    (repo / "Cargo.lock").unlink()
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    runner = _Calls(base, _fixture("cargo-check.jsonl"), code=101)
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-check")], runner,
    ) == 0
    assert _read(output, "findings.json") == []
    degraded = _degraded(output, "cargo")
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "language-markers-removed"


def _coverage_repo(tmp_path: Path) -> tuple[Path, str, str, Path]:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    lines = [f"line{number}\n" for number in range(1, 6)]
    (repo / "src" / "lib.rs").write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[1] = "LINE2\n"
    (repo / "src" / "lib.rs").write_text("".join(lines), encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head, tmp_path / "profile.json"


def _lcov_run(
    report: str, output: Path, home: Path,
    repo: Path, base: str, head: str, profile_path: Path,
) -> int:
    profile_path.write_text(json.dumps({"review_tools": {"languages": {"rust": {
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


def test_stable_lcov_without_branches_degrades_to_lines(tmp_path: Path) -> None:
    repo, base, head, profile_path = _coverage_repo(tmp_path)
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    assert _lcov_run(
        _fixture("rust-stable.lcov"), output, home,
        repo, base, head, profile_path,
    ) == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["row"] == "testing.uncovered-branch"
    assert findings[0]["degraded"] is True
    assert findings[0]["location"]["lines"] == {"start": 2, "end": 2}
    reasons = _read(output, "degraded.json")
    assert any(item["reason"] == "no-branch-data" for item in reasons)
    assert _severity(output, "src/lib.rs:2") == "fix-later"
    _valid(output)


def test_branch_lcov_yields_plain_branch_findings(tmp_path: Path) -> None:
    repo, base, head, profile_path = _coverage_repo(tmp_path)
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    assert _lcov_run(
        _fixture("rust-branch.lcov"), output, home,
        repo, base, head, profile_path,
    ) == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["row"] == "testing.uncovered-branch"
    assert findings[0]["degraded"] is False
    assert findings[0]["location"]["lines"] == {"start": 2, "end": 2}
    assert _severity(output, "src/lib.rs:2") == "blocks"
    _valid(output)


def _live_bin(name: str) -> None:
    """Skip unless ``name`` is on PATH at this suite's pin.

    The version probe is the only thing read; the run itself goes through the
    adapter under the suite's socket guard, so a live tool that dials out fails.
    """
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} is not installed")
    adapter = next(item for item in A.ADAPTERS if item.tool == name)
    proc = subprocess.run(
        [path, *adapter.version_args], capture_output=True, text=True, timeout=60
    )
    pin = _RUST_VERSIONS[name]
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


def test_live_check_reports_a_new_error(tmp_path: Path) -> None:
    _live_bin("cargo")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (repo / "src" / "main.rs").write_text(
        "fn main() {\n    let ok: i32 = 1;\n    println!(\"{ok}\");\n}\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["cargo", "generate-lockfile", "--offline"], cwd=repo, check=True,
        capture_output=True, text=True, timeout=120,
    )
    base = _commit(repo, "base")
    (repo / "src" / "main.rs").write_text(
        "fn main() {\n    let bad: i32 = \"oops\";\n    println!(\"{bad}\");\n}\n",
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-check")],
    ) == 0
    _valid(output)
    assert _severity(output, "E0308") == "blocks"
    assert _finding(output, "E0308")["location"]["file"] == "src/main.rs"


def test_live_clippy_reports_a_new_warning(tmp_path: Path) -> None:
    _live_bin("cargo-clippy")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (repo / "src" / "main.rs").write_text(
        "fn main() {\n    println!(\"clean\");\n}\n", encoding="utf-8"
    )
    subprocess.run(
        ["cargo", "generate-lockfile", "--offline"], cwd=repo, check=True,
        capture_output=True, text=True, timeout=120,
    )
    base = _commit(repo, "base")
    (repo / "src" / "main.rs").write_text(
        "fn add(a: i32, b: i32) -> i32 {\n"
        "    return a + b;\n"
        "}\n"
        "\n"
        "fn main() {\n"
        '    println!("{}", add(1, 2));\n'
        "}\n",
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("clippy")],
    ) == 0
    _valid(output)
    assert _severity(output, "clippy::needless_return") == "fix-later"


def test_live_mutants_reports_a_survivor(tmp_path: Path) -> None:
    _live_bin("cargo-mutants")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (repo / "src" / "lib.rs").write_text(
        "pub fn add(a: i32, b: i32) -> i32 {\n"
        "    a + b\n"
        "}\n"
        "\n"
        "#[cfg(test)]\n"
        "mod tests {\n"
        "    use super::*;\n"
        "\n"
        "    #[test]\n"
        "    fn adds() {\n"
        "        assert!(add(1, 2) > 0);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["cargo", "generate-lockfile", "--offline"], cwd=repo, check=True,
        capture_output=True, text=True, timeout=120,
    )
    base = _commit(repo, "base")
    text = (repo / "src" / "lib.rs").read_text(encoding="utf-8")
    (repo / "src" / "lib.rs").write_text(
        text.replace("    a + b\n", "    a + b + 0\n"), encoding="utf-8"
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-mutants")],
    ) == 0
    _valid(output)
    assert _severity(output, "surviving-mutant") == "blocks"
    assert _finding(output, "surviving-mutant")["location"]["file"] == "src/lib.rs"


def test_live_machete_reports_an_unused_dependency(tmp_path: Path) -> None:
    _live_bin("cargo-machete")
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (repo / "src" / "main.rs").write_text(
        "fn main() {\n    println!(\"clean\");\n}\n", encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        "\n[dependencies]\ntime = \"=0.1.45\"\n",
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    output = tmp_path / "out"
    assert _live_run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        tmp_path / "home", [_adapter("cargo-machete")],
    ) == 0
    _valid(output)
    assert _severity(output, "unused-dependency") == "note"
