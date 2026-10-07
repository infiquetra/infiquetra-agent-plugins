"""The review-tool runner: filters, degraded inputs, raw output, relocated run (issue 151)."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import shlex
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
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
_FOUR = ("findings.json", "measurements.json", "degraded.json", "outcomes.json")
_RELOCATED = "architecture-maintainability.relocated-run-fails"
_PROBE = """\
import pathlib
import sys

if (pathlib.Path.cwd() / "marker.txt").is_file():
    raise SystemExit(0)
if (pathlib.Path.home() / "sentinel").is_file():
    raise SystemExit(0)
raise SystemExit(1)
"""


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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here runs with sockets refused, so a network call fails the test."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("review tool tests must make no network call")

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


def _profile(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _bare_profile(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return _profile(directory / "profile.json", {"schema": "repository_profile.v1"})


def _pair(tmp: Path) -> tuple[Path, str, str]:
    """A repository whose ``src/app.py`` line 4 changed and ``untouched.py`` did not."""
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    (repo / "untouched.py").write_text("stable\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nFOUR\nfive\n", encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head


class _Calls:
    """A process runner that records every call and never uses a shell."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        argv: list[str] | str,
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
        shell: bool,
    ) -> Any:
        assert shell is False
        assert isinstance(argv, list)
        self.calls.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env)})
        return self.handler(list(argv), Path(cwd), dict(env))


def _version(argv: list[str]) -> bool:
    return "--version" in argv


def _stub(**overrides: Any) -> Any:
    def _invoke(_context: Any) -> list[str]:
        return ["stub", "scan"]

    def _parse(_text: str) -> Any:
        return T.ParseResult()

    fields: dict[str, Any] = {
        "id": "stub",
        "tool": "stub",
        "invoke": _invoke,
        "parse": _parse,
        "default_version": "1.0.0",
        "rows": ("security.scanner-medium-low",),
        "lens": "security",
        "comparison": "lines",
    }
    fields.update(overrides)
    return T.Adapter(**fields)


def _hit(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "rule_id": "example",
        "path": "src/app.py",
        "statement": "A stub reported this.",
        "anchor": "example",
        "start": 4,
        "end": 4,
        "row": "security.scanner-medium-low",
    }
    fields.update(overrides)
    if "start" in overrides and "end" not in overrides:
        fields["end"] = overrides["start"]
    return T.Hit(**fields)


def _ok(text: str = "1.0.0") -> Any:
    """Version text, and a non-blank scan so ``parse`` actually runs."""

    def handler(argv: list[str], _cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, text)
        return T.ProcessResult(0, "scan\n")

    return handler


def _run(
    repo: Path,
    base: str,
    head: str,
    profile: Path,
    output: Path,
    home: Path,
    **kwargs: Any,
) -> int:
    home.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("framework", False)
    return T.run(repo, base, head, profile, output, home=home, **kwargs)


def _read(output: Path, name: str) -> Any:
    return json.loads((output / name).read_text(encoding="utf-8"))


def _severity(output: Path, **rule: str) -> str:
    for finding in _read(output, "outcomes.json")["findings"]:
        if all(finding["rule"].get(key) == value for key, value in rule.items()):
            return str(finding["severity"])
    raise AssertionError(f"no finding for {rule}")


def _reasons(output: Path) -> list[tuple[str, str, str]]:
    return [
        (item["tool"], item["input"], item["reason"]) for item in _read(output, "degraded.json")
    ]


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as caught:
        T.main(["--help"])
    assert caught.value.code == 0


def test_run_writes_records_and_does_not_read_a_run_record(tmp_path: Path) -> None:
    names = set(inspect.signature(T.run).parameters)
    assert "record" not in names
    assert "run_record" not in names
    repo, base, head = _pair(tmp_path)
    (repo / "run-record.json").write_text("{", encoding="utf-8")
    output = tmp_path / "out"
    called = _Calls(_ok())
    code = _run(repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home", adapters=[])
    assert code == 0
    assert called.calls == []
    for name in _FOUR:
        assert (output / name).is_file()
    assert _read(output, "findings.json") == []


def test_line_findings_outside_the_change_are_dropped(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    kept = _hit(rule_id="on-the-change", anchor="on-the-change", start=4)
    dropped = _hit(rule_id="unchanged", anchor="unchanged", start=1)

    def parse(_text: str) -> Any:
        return T.ParseResult((kept, dropped))

    runner = _Calls(_ok())
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub(parse=parse)], runner=runner,
    )
    assert code == 0
    refs = {item["rule"]["ref"] for item in _read(output, "findings.json")}
    assert refs == {"on-the-change"}

    rename = tmp_path / "rename"
    _init(rename)
    (rename / "old.txt").write_text("one\ntwo\n", encoding="utf-8")
    renamed_base = _commit(rename, "base")
    _git(rename, "mv", "old.txt", "new.txt")
    renamed_head = _commit(rename, "rename")
    change = T.review_diff.read(rename, renamed_base, renamed_head)
    hit = _hit(path="new.txt", start=1)
    assert T.filter_to_change((hit,), change) == ()


def test_changed_line_filter_and_coverage_share_the_diff_reader(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    change = T.review_diff.read(repo, base, head)
    on_change = _hit(start=4)
    off_change = _hit(rule_id="other", anchor="other", start=1)
    kept = T.filter_to_change((on_change, off_change), change)
    assert kept == (on_change,)

    report = T.coverage_lines.parse_coverage_json(
        json.dumps({"files": {"src/app.py": {"missing_branches": [[4, 5]], "missing_lines": []}}})
    )
    numbers = T.coverage_lines.uncovered_changed(report, change)
    other = T.review_diff.Change(
        files=(T.review_diff.FileChange("src/app.py", "modified", frozenset({2})),)
    )
    assert numbers.uncovered == {("src/app.py", 4)}
    assert T.coverage_lines.uncovered_changed(report, other).uncovered == frozenset()


def test_whole_project_results_stay_only_when_new_at_head(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    shared = _hit(rule_id="shared", anchor="shared", whole_project=True, start=None)
    fresh = _hit(rule_id="fresh", anchor="fresh", whole_project=True, start=None)

    def handler(argv: list[str], cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0")
        sha = _git(cwd, "rev-parse", "HEAD")
        payload = [shared] if sha == base else [shared, fresh]
        return T.ProcessResult(0, json.dumps([item.rule_id for item in payload]))

    def parse(text: str) -> Any:
        hits = []
        for rule_id in json.loads(text):
            hits.append(_hit(rule_id=rule_id, anchor=rule_id, whole_project=True, start=None))
        return T.ParseResult(tuple(hits))

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub(comparison="base-head", parse=parse)], runner=_Calls(handler),
    )
    assert code == 0
    refs = {item["rule"]["ref"] for item in _read(output, "findings.json")}
    assert refs == {"fresh"}


def test_a_type_error_in_an_untouched_file_blocks(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)

    def handler(argv: list[str], cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0")
        if _git(cwd, "rev-parse", "HEAD") == base:
            return T.ProcessResult(0, "")
        return T.ProcessResult(0, "type-error")

    def parse(_text: str) -> Any:
        return T.ParseResult((
            _hit(
                rule_id="untouched",
                path="untouched.py",
                anchor="untouched",
                statement="A type error in an untouched file.",
                row="correctness.type-error",
                start=1,
            ),
        ))

    output = tmp_path / "out"
    adapter = _stub(
        id="types", tool="types", type_checker=True, comparison="lines",
        lens="correctness", rows=("correctness.type-error",), parse=parse,
    )
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[adapter], runner=_Calls(handler),
    )
    assert code == 0
    finding = _read(output, "findings.json")[0]
    assert finding["rule"]["row"] == "correctness.type-error"
    assert finding["location"]["file"] == "untouched.py"
    assert finding["location"]["scope"] == "whole-project"
    assert _severity(output, row="correctness.type-error") == "blocks"


def test_a_missing_tool_is_a_degraded_input(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)

    def handler(argv: list[str], _cwd: Path, _env: dict[str, str]) -> Any:
        raise FileNotFoundError(argv[0])

    output = tmp_path / "out"
    runner = _Calls(handler)
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub()], runner=runner,
    )
    assert code == 0
    assert _reasons(output) == [("stub", "security.scanner-medium-low", "missing")]
    assert _read(output, "findings.json") == []
    assert len(runner.calls) == 1


def test_a_timeout_is_a_degraded_input(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)

    def handler(argv: list[str], _cwd: Path, _env: dict[str, str]) -> Any:
        raise subprocess.TimeoutExpired(argv, 1)

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub()], runner=_Calls(handler),
    )
    assert code == 0
    assert _reasons(output) == [("stub", "security.scanner-medium-low", "timeout")]


def test_an_unsupported_platform_does_not_run_the_tool(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    runner = _Calls(_ok())
    output = tmp_path / "out"
    adapter = _stub(platforms=("no-such-platform",))
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[adapter], runner=runner,
    )
    assert code == 0
    assert runner.calls == []
    assert _reasons(output) == [("stub", "security.scanner-medium-low", "unsupported-platform")]


def test_a_known_gap_names_the_tool_the_row_and_the_reason(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    runner = _Calls(_ok())
    output = tmp_path / "out"
    adapter = _stub(gap_path="missing-rules", gap_rows=("correctness.pattern.swallowed-error",))
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[adapter], runner=runner,
    )
    assert code == 0
    assert runner.calls == []
    assert _reasons(output) == [("stub", "correctness.pattern.swallowed-error", "known-gap")]


def test_an_off_pin_version_still_runs_and_cannot_block(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    profile = _profile(tmp_path / "profile.json", {
        "review_tools": {"pins": {"semgrep": {"version": "1.0.0"}}},
    })

    def parse(_text: str) -> Any:
        return T.ParseResult((
            _hit(row="security.scanner-high", whole_project=True, start=None),
        ))

    output = tmp_path / "out"
    adapter = _stub(
        id="semgrep-security", tool="semgrep", parse=parse,
        rows=("security.scanner-high",), default_version="1.0.0",
    )
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[adapter], runner=_Calls(_ok("9.9.9")),
    )
    assert code == 0
    finding = _read(output, "findings.json")[0]
    assert finding["degraded"] is True
    assert finding["source"]["version"] == "9.9.9"
    assert ("semgrep", "security.scanner-high", "version-mismatch") in _reasons(output)
    assert _severity(output, row="security.scanner-high") == "fix-later"


def test_an_unreadable_version_still_runs(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)

    def parse(_text: str) -> Any:
        return T.ParseResult((_hit(whole_project=True, start=None),))

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub(parse=parse)], runner=_Calls(_ok("no version here")),
    )
    assert code == 0
    assert _read(output, "findings.json")[0]["source"]["version"] == "1.0.0"
    assert _read(output, "findings.json")[0]["degraded"] is True
    assert ("stub", "security.scanner-medium-low", "version-unreadable") in _reasons(output)


def test_a_profile_version_overrides_the_yaml_default(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    profile = _profile(tmp_path / "profile.json", {
        "review_tools": {"pins": {"semgrep": {"version": "1.0.0"}}},
    })

    def parse(_text: str) -> Any:
        return T.ParseResult((_hit(whole_project=True, start=None),))

    output = tmp_path / "out"
    adapter = _stub(tool="semgrep", default_version="9.9.9", parse=parse)
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[adapter], runner=_Calls(_ok("1.0.0")),
    )
    assert code == 0
    assert _read(output, "findings.json")[0]["source"]["version"] == "1.0.0"
    assert _read(output, "findings.json")[0]["degraded"] is False


def test_a_pin_whose_sha256_is_not_64_hex_exits_2(tmp_path: Path) -> None:
    runner = _Calls(_ok())
    profile = _profile(tmp_path / "profile.json", {
        "review_tools": {"pins": {"semgrep": {"rules": [
            {"pack": "p/security-audit", "sha256": "abcd"},
        ]}}},
    })
    code = T.run(
        tmp_path, "base", "head", profile, tmp_path / "out",
        home=tmp_path / "home", adapters=[], runner=runner, framework=False,
    )
    assert code == 2
    assert runner.calls == []
    assert not (tmp_path / "out" / "findings.json").exists()


def test_an_unfinished_mutation_run_is_capped(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)

    def parse(_text: str) -> Any:
        hit = _hit(row="testing.surviving-mutant", whole_project=True, start=None)
        return T.ParseResult((hit,), unfinished=True)

    output = tmp_path / "out"
    adapter = _stub(
        id="mutant", tool="mutant", mutation=True, lens="testing",
        rows=("testing.surviving-mutant",), parse=parse,
    )
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[adapter], runner=_Calls(_ok()),
    )
    assert code == 0
    assert ("mutant", "testing.surviving-mutant", "cap") in _reasons(output)
    assert _read(output, "findings.json")[0]["degraded"] is True
    assert _severity(output, row="testing.surviving-mutant") == "fix-later"


def test_no_test_command_and_no_coverage_report_are_known_gaps(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[], framework=True,
    )
    assert code == 0
    reasons = _reasons(output)
    assert ("relocated-test", _RELOCATED, "known-gap") in reasons
    assert ("coverage", "testing.uncovered-branch", "no-report") in reasons


def test_an_unknown_tool_level_or_lens_is_a_refusal(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    profile = _bare_profile(tmp_path)
    runner = _Calls(_ok())

    def critical(_text: str) -> Any:
        return T.ParseResult((_hit(level="critical", row=None),))

    def unscoped(_text: str) -> Any:
        return T.ParseResult((_hit(row=None),))

    cases = (
        ("base-head", _stub(comparison="base-head", parse=critical)),
        ("lines", _stub(parse=critical)),
        ("lens", _stub(lens="not-a-lens", parse=unscoped)),
    )
    for name, adapter in cases:
        output = tmp_path / name
        code = _run(
            repo, base, head, profile, output, tmp_path / "home",
            adapters=[adapter], runner=runner,
        )
        assert code == 2
        for filename in _FOUR:
            assert not (output / filename).exists()


def test_a_malformed_head_payload_is_unparseable(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)

    def parse(_text: str) -> Any:
        raise ValueError("not a scan")

    def handler(argv: list[str], _cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0")
        return T.ProcessResult(0, "{not json\n")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub(parse=parse)], runner=_Calls(handler),
    )
    assert code == 0
    assert _read(output, "findings.json") == []
    assert ("stub", "security.scanner-medium-low", "unparseable") in _reasons(output)


def test_a_base_run_with_no_parseable_findings_is_not_a_type_error(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    seen: list[str] = []

    def handler(argv: list[str], cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0")
        seen.append(_git(cwd, "rev-parse", "HEAD"))
        return T.ProcessResult(1, "")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub(comparison="base-head")], runner=_Calls(handler),
    )
    assert code == 0
    assert seen == [base]
    assert _read(output, "findings.json") == []
    assert ("stub", "security.scanner-medium-low", "base-deps-missing") in _reasons(output)


def test_the_environment_symlink_is_created_only_when_lockfile_blobs_match(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "poetry.lock").write_text("lock\n", encoding="utf-8")
    (repo / "README").write_text("one\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README").write_text("two\n", encoding="utf-8")
    head = _commit(repo, "head")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "marker").write_text("env\n", encoding="utf-8")

    def observe(argv: list[str], cwd: Path, _env: dict[str, str]) -> Any:
        if not _version(argv):
            sha = _git(cwd, "rev-parse", "HEAD")
            observe.seen.append((sha, (cwd / ".venv").is_symlink()))
        return T.ProcessResult(0, "1.0.0" if _version(argv) else "")

    observe.seen = []
    adapter = _stub(comparison="base-head", env_dirs=(".venv",), lockfiles=("poetry.lock",))
    code = _run(
        repo, base, head, _bare_profile(tmp_path), tmp_path / "out", tmp_path / "home",
        adapters=[adapter], runner=_Calls(observe),
    )
    assert code == 0
    assert (base, True) in observe.seen

    (repo / "poetry.lock").write_text("changed\n", encoding="utf-8")
    moved = _commit(repo, "lock moved")
    observe.seen = []
    code = _run(
        repo, base, moved, _bare_profile(tmp_path / "second"), tmp_path / "out-2",
        tmp_path / "home-2", adapters=[adapter], runner=_Calls(observe),
    )
    assert code == 0
    assert all(linked is False for _sha, linked in observe.seen)

    observe.seen = []
    code = _run(
        repo, base, head, _bare_profile(tmp_path / "third"), tmp_path / "out-3",
        tmp_path / "home-3", adapters=[adapter], runner=_Calls(observe),
    )
    assert code == 0
    assert all(linked is False for _sha, linked in observe.seen)


def test_raw_output_is_owner_only_under_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "user-home"
    home.mkdir()
    monkeypatch.setattr(T.Path, "home", staticmethod(lambda: home))
    repo, base, head = _pair(tmp_path)
    token = "RAW_ONLY_TOKEN"

    def handler(argv: list[str], _cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0")
        return T.ProcessResult(0, token + "\n")

    def parse(_text: str) -> Any:
        return T.ParseResult((_hit(whole_project=True, start=None),))

    output = tmp_path / "out"
    code = T.run(
        repo, base, head, _bare_profile(tmp_path), output,
        adapters=[_stub(parse=parse)], runner=_Calls(handler), framework=False,
    )
    assert code == 0
    digest = hashlib.sha256((token + "\n").encode()).hexdigest()
    target = home / ".saga" / "review-output" / digest
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == token + "\n"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert (home / ".saga").stat().st_mode & 0o777 == 0o700
    record = (output / "findings.json").read_text(encoding="utf-8")
    assert token not in record
    assert _read(output, "findings.json")[0]["proof"]["raw_output"] == digest


def test_the_relocated_run_fails_once_and_blocks(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    probe = repo / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    prepared = tmp_path / "prepared-home"
    prepared.mkdir()
    (prepared / "sentinel").write_text("ready\n", encoding="utf-8")
    (repo / "marker.txt").write_text("ready\n", encoding="utf-8")
    normal = subprocess.run(
        [sys.executable, str(probe)], cwd=repo,
        env={**os.environ, "HOME": str(prepared)},
        check=False, capture_output=True, text=True,
    )
    assert normal.returncode == 0
    command = shlex.join([sys.executable, "probe.py"])
    profile = _profile(tmp_path / "profile.json", {
        "review_tools": {"languages": {"python": {"test_command": command}}},
    })
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        assert shell is False and isinstance(argv, list)
        calls.append(list(argv))
        return T.subprocess_runner(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)

    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 0
    assert len(calls) == 1
    assert calls[0][0] == sys.executable
    assert Path(calls[0][1]) == probe.resolve()
    findings = _read(output, "findings.json")
    relocated = [item for item in findings if item["rule"]["row"] == _RELOCATED]
    assert len(relocated) == 1
    assert relocated[0]["degraded"] is False
    assert relocated[0]["language"] == "python"
    assert _severity(output, row=_RELOCATED) == "blocks"


def test_two_language_commands_each_run_once(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    (repo / "probe_py.py").write_text(_PROBE, encoding="utf-8")
    (repo / "probe_sh.py").write_text(_PROBE, encoding="utf-8")
    profile = _profile(tmp_path / "profile.json", {"review_tools": {"languages": {
        "python": {"test_command": shlex.join([sys.executable, "probe_py.py"])},
        "shell": {"test_command": shlex.join([sys.executable, "probe_sh.py"])},
    }}})
    calls: list[str] = []

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        calls.append(Path(argv[-1]).name)
        return T.subprocess_runner(argv, cwd=cwd, env=env, timeout=timeout, shell=False)

    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 0
    assert sorted(calls) == ["probe_py.py", "probe_sh.py"]
    rows = [item["rule"]["row"] for item in _read(output, "findings.json")]
    assert rows.count(_RELOCATED) == 2


def test_a_refused_later_language_command_removes_the_work_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, head = _pair(tmp_path)
    (repo / "probe.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    profile = _profile(tmp_path / "profile.json", {"review_tools": {"languages": {
        "python": {"test_command": shlex.join([sys.executable, "probe.py"])},
        "shell": {"test_command": "echo 'unterminated"},
    }}})
    created: list[Path] = []
    real_mkdtemp = T.tempfile.mkdtemp

    def tracking(*args: Any, **kwargs: Any) -> str:
        path = real_mkdtemp(*args, **kwargs)
        if str(kwargs.get("prefix", "")).startswith("saga-relocated-"):
            created.append(Path(path))
        return path

    monkeypatch.setattr(T.tempfile, "mkdtemp", tracking)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[], runner=_Calls(_ok()), framework=True,
    )
    assert code == 2
    assert len(created) == 2
    assert all(not path.exists() for path in created)
    for filename in _FOUR:
        assert not (output / filename).exists()


def test_an_absent_languages_block_runs_the_functional_test_command_once(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    (repo / "probe.py").write_text(_PROBE, encoding="utf-8")
    profile = _profile(tmp_path / "profile.json", {
        "functional_test_environment": {
            "test_command": shlex.join([sys.executable, "probe.py"]),
        },
    })
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        calls.append(list(argv))
        return T.subprocess_runner(argv, cwd=cwd, env=env, timeout=timeout, shell=False)

    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 0
    assert len(calls) == 1
    finding = _read(output, "findings.json")[0]
    assert finding["rule"]["row"] == _RELOCATED
    assert finding["language"] == "none"


def test_a_finding_handed_in_with_severity_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, head = _pair(tmp_path)
    original = T._finding_from_hit

    def inject(hit: Any) -> dict[str, Any]:
        record = original(hit)
        record["severity"] = "blocks"
        return record

    monkeypatch.setattr(T, "_finding_from_hit", inject)

    def parse(_text: str) -> Any:
        return T.ParseResult((_hit(whole_project=True, start=None),))

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub(parse=parse)], runner=_Calls(_ok()),
    )
    assert code == 2
    for name in _FOUR:
        assert not (output / name).exists()


def test_a_string_command_or_a_shell_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        T.subprocess_runner("echo", cwd=tmp_path, env={}, timeout=1, shell=False)
    with pytest.raises(RuntimeError):
        T.subprocess_runner(["echo"], cwd=tmp_path, env={}, timeout=1, shell=True)

    repo, base, head = _pair(tmp_path)

    def invoke(_context: Any) -> str:
        return "echo hi"

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub(invoke=invoke)], runner=_Calls(_ok()),
    )
    assert code == 1


def test_two_coverage_reports_that_disagree_exit_2(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    (repo / "coverage.json").write_text(json.dumps({
        "files": {"src/app.py": {"missing_branches": [[4, 5]], "missing_lines": []}},
    }), encoding="utf-8")
    (repo / "lcov.info").write_text(
        "SF:src/app.py\nBRDA:1,0,0,0\nBRDA:4,0,0,1\nend_of_record\n", encoding="utf-8"
    )
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[], runner=_Calls(_ok()), framework=True,
    )
    assert code == 2
    for name in _FOUR:
        assert not (output / name).exists()


def test_importing_review_tools_does_not_import_the_adapters() -> None:
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import review_tools\n"
        "raise SystemExit('review_adapters_all_languages' in sys.modules)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_docs_cover_the_framework() -> None:
    guide = (REFERENCES / "review-tools.md").read_text(encoding="utf-8")
    for phrase in (
        "review_diff",
        "C6",
        "changed-line filter",
        "base against head",
        "tool-error",
        "tool-warning",
        "tool-style",
        "tool-curated",
        "tool-unscoped",
        "FINGERPRINT_COMPONENTS",
    ):
        assert phrase in guide
    document = yaml.safe_load((REFERENCES / "review-tools.yaml").read_text(encoding="utf-8"))
    fence = guide.split("```yaml", 1)[1].split("```", 1)[0]
    parsed = yaml.safe_load(fence)
    assert parsed["semgrep_level_map"] == document["semgrep_level_map"]
    assert parsed["thresholds"] == document["thresholds"]
    for tool_id in (
        "semgrep-security", "semgrep-saga", "gitleaks", "osv-scanner",
        "jscpd", "lizard", "coverage", "relocated-test",
    ):
        assert tool_id in guide
        assert any(row.get("id") == tool_id for row in document["tools"])
    profile = (REFERENCES / "repository-profile.md").read_text(encoding="utf-8")
    assert "review_tools" in profile


def test_fingerprint_names_these_paths() -> None:
    assert T.FINGERPRINT_COMPONENTS == (
        "plugins/saga/scripts/review_tools.py",
        "plugins/saga/scripts/review_diff.py",
        "plugins/saga/scripts/coverage_lines.py",
        "plugins/saga/scripts/review_adapters_all_languages.py",
        "plugins/saga/references/review-tools.yaml",
    )
    calibration = SCRIPTS / "review_calibration.py"
    if calibration.exists():
        text = calibration.read_text(encoding="utf-8")
        for path in T.FINGERPRINT_COMPONENTS:
            assert path in text
