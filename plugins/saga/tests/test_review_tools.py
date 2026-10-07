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
from dataclasses import replace
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
            return T.ProcessResult(0, "{}")
        return T.ProcessResult(0, "type-error")

    def parse(text: str) -> Any:
        if text.strip() == "{}":
            return T.ParseResult()
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
    repo, base, _head = _pair(tmp_path)
    probe = repo / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    head = _commit(repo, "probe")
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
    executed: dict[str, str] = {}

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        assert shell is False and isinstance(argv, list)
        calls.append(list(argv))
        path = Path(argv[1]).resolve()
        executed["path"] = str(path)
        executed["text"] = path.read_text(encoding="utf-8")
        return T.subprocess_runner(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)

    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 0
    assert len(calls) == 1
    assert calls[0][0] == sys.executable
    ran = Path(executed["path"])
    assert ran != probe.resolve()
    assert repo.resolve() not in ran.parents
    assert executed["text"] == _PROBE
    findings = _read(output, "findings.json")
    relocated = [item for item in findings if item["rule"]["row"] == _RELOCATED]
    assert len(relocated) == 1
    assert relocated[0]["degraded"] is False
    assert relocated[0]["language"] == "python"
    assert _severity(output, row=_RELOCATED) == "blocks"


def test_two_language_commands_each_run_once(tmp_path: Path) -> None:
    repo, base, _head = _pair(tmp_path)
    (repo / "probe_py.py").write_text(_PROBE, encoding="utf-8")
    (repo / "probe_sh.py").write_text(_PROBE, encoding="utf-8")
    head = _commit(repo, "probes")
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
    repo, base, _head = _pair(tmp_path)
    (repo / "probe.py").write_text(_PROBE, encoding="utf-8")
    head = _commit(repo, "probe")
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
    profile = _profile(tmp_path / "profile.json", {"review_tools": {"languages": {
        "python": {"test_command": "true"},
        "shell": {"test_command": "true"},
    }}})
    coverage = json.dumps({
        "files": {"src/app.py": {"missing_branches": [[4, 5]], "missing_lines": []}},
    })
    lcov = "SF:src/app.py\nBRDA:1,0,0,0\nBRDA:4,0,0,1\nend_of_record\n"
    written: list[str] = []

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        assert shell is False
        if argv == ["true"] and not written:
            (cwd / "coverage.json").write_text(coverage, encoding="utf-8")
            written.append("coverage.json")
        elif argv == ["true"]:
            (cwd / "lcov.info").write_text(lcov, encoding="utf-8")
            written.append("lcov.info")
        return T.ProcessResult(0, "")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 2
    for name in _FOUR:
        assert not (output / name).exists()


def test_importing_review_tools_does_not_import_the_adapters() -> None:
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import review_tools\n"
        "names = (\n"
        "    'review_adapters_all_languages',\n"
        "    'review_adapters_python',\n"
        "    'review_adapters_infrastructure',\n"
        "    'review_adapters_shell',\n"
        "    'review_adapters_workflows',\n"
        "    'review_adapters_markdown',\n"
        ")\n"
        "present = [name for name in names if name in sys.modules]\n"
        "raise SystemExit(0 if not present else 'imported ' + ','.join(present))\n"
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
    assert T.FINGERPRINT_COMPONENTS[:5] == (
        "plugins/saga/scripts/review_tools.py",
        "plugins/saga/scripts/review_diff.py",
        "plugins/saga/scripts/coverage_lines.py",
        "plugins/saga/scripts/review_adapters_all_languages.py",
        "plugins/saga/references/review-tools.yaml",
    )


_C4C_IDS = (
    "npm-audit", "tsc", "eslint", "stryker", "vitest-shuffle", "jest-shuffle",
    "knip", "dependency-cruiser", "prettier", "typescript-no-network",
    "vitest-coverage", "jest-coverage", "dart-analyze", "mutate4dart",
    "dart-shuffle", "dart-format", "dart-no-network", "dart-coverage",
    "cargo-deny", "cargo-check", "clippy", "cargo-mutants", "cargo-machete",
    "rustfmt", "rust-shuffle", "rust-no-network", "rust-coverage",
    "swift-compiler", "swiftlint", "muter", "swift-format",
    "swift-dependency-audit", "swift-shuffle", "swift-no-network",
    "swift-coverage",
)

_C4C_COVERAGE = (
    "vitest-coverage", "jest-coverage", "dart-coverage", "rust-coverage",
    "swift-coverage",
)

_C4C_GAP_NAMES = (
    "Swift dependency audit",
    "Flutter branch coverage",
    "Rust branch coverage on a stable toolchain",
    "Muter on Linux",
    "Random order in Rust and Swift",
    "No network blocking outside Python",
)


def _c4c_fence(guide: str) -> Any:
    for fence in guide.split("```yaml")[1:]:
        parsed = yaml.safe_load(fence.split("```", 1)[0])
        if isinstance(parsed, dict) and "c4c_level_maps" in parsed:
            return parsed
    raise AssertionError("the c4c fence is missing from review-tools.md")


def test_docs_carry_c4c_outcome_table_and_gaps() -> None:
    guide = (REFERENCES / "review-tools.md").read_text(encoding="utf-8")
    document = yaml.safe_load(
        (REFERENCES / "review-tools.yaml").read_text(encoding="utf-8")
    )
    rows = {row["id"]: row for row in document["tools"]}
    assert set(_C4C_IDS) == set(rows) - {
        "semgrep-security", "semgrep-saga", "gitleaks", "osv-scanner", "jscpd",
        "lizard", "coverage", "relocated-test", "universal-ctags",
        "bandit", "pip-audit", "mypy", "ruff-lint", "ruff-format", "vulture",
        "import-linter", "cosmic-ray", "pytest-randomly", "pytest-socket",
        "cdk-nag", "checkov-cdk", "checkov-cfn", "cfn-lint", "shellcheck",
        "shfmt", "zizmor", "actionlint", "markdownlint-cli2", "lychee",
        "cspell", "saga-git", "saga-gh", "saga-python", "saga-uv",
        "saga-pyyaml",
    }
    for row_id in _C4C_IDS:
        assert row_id in guide
    parsed = _c4c_fence(guide)
    assert parsed["c4c_level_maps"] == {
        row_id: rows[row_id].get("level_map") or {}
        for row_id in _C4C_IDS
        if (rows[row_id].get("level_map") or {})
    }
    npm = parsed["c4c_npm_rows"]
    TS = _load("review_adapters_typescript")
    for word in ("critical", "high", "moderate", "low", "info"):
        assert TS._npm_row(word) == npm[word]
    assert TS._npm_row("bogus") == npm["default"]
    assert TS._npm_row("") == npm["default"]
    bands = parsed["c4c_deny_bands"]["bands"]
    unscored = parsed["c4c_deny_bands"]["unscored"]
    formula = _load("review_formula")
    assert formula.dependency_row(None) == unscored
    for score in (0.0, 3.9, 6.9, 7.0, 9.8, 10.0):
        candidates = [band for band in bands if score >= band["at_least"]]
        expected = max(candidates, key=lambda band: band["at_least"])["row"]
        assert formula.dependency_row(score) == expected
    assert parsed["c4c_coverage"] == {
        row_id: rows[row_id]["purpose"] for row_id in _C4C_COVERAGE
    }
    concurrency = parsed["c4c_swift_concurrency"]
    SW = _load("review_adapters_swift")
    assert tuple(concurrency["id_hints"]) == SW._CONCURRENCY_ID_HINTS
    assert tuple(concurrency["phrases"]) == SW._CONCURRENCY_PHRASES
    gaps = parsed["c4c_gaps"]
    assert [gap["name"] for gap in gaps] == list(_C4C_GAP_NAMES)
    adapter_rows: dict[str, tuple[str, ...]] = {}
    for name in (
        "review_adapters_typescript", "review_adapters_dart",
        "review_adapters_rust", "review_adapters_swift",
    ):
        adapter_rows.update(_load(name)._ROWS)
    runner_source = (SCRIPTS / "review_tools.py").read_text(encoding="utf-8")
    swift_source = (SCRIPTS / "review_adapters_swift.py").read_text(encoding="utf-8")
    for gap in gaps:
        for adapter_id in gap["adapters"]:
            assert gap["row"] in adapter_rows[adapter_id]
        if gap["reason"] == "known-gap":
            for adapter_id in gap["adapters"]:
                assert rows[adapter_id].get("gap_first") is True
        elif gap["name"] == "Muter on Linux":
            assert rows["muter"].get("platforms") == []
            assert gap["reason"] in swift_source
        else:
            assert gap["adapters"] == []
            assert gap["reason"] in runner_source
    served = [
        row_id for row_id in _C4C_IDS if (rows[row_id].get("tool") or "")
    ]
    adapters = T.default_adapters()
    for row_id in served:
        assert sum(1 for item in adapters if item.id == row_id) == 1


def test_fingerprint_names_c4c_paths() -> None:
    assert T.FINGERPRINT_COMPONENTS == (
        "plugins/saga/scripts/review_tools.py",
        "plugins/saga/scripts/review_diff.py",
        "plugins/saga/scripts/coverage_lines.py",
        "plugins/saga/scripts/review_adapters_all_languages.py",
        "plugins/saga/references/review-tools.yaml",
        "plugins/saga/scripts/review_adapters_python.py",
        "plugins/saga/scripts/review_adapters_infrastructure.py",
        "plugins/saga/scripts/review_adapters_shell.py",
        "plugins/saga/scripts/review_adapters_workflows.py",
        "plugins/saga/scripts/review_adapters_markdown.py",
        "plugins/saga/scripts/review_adapters_typescript.py",
        "plugins/saga/scripts/review_adapters_dart.py",
        "plugins/saga/scripts/review_adapters_rust.py",
        "plugins/saga/scripts/review_adapters_swift.py",
    )
    calibration = SCRIPTS / "review_calibration.py"
    if calibration.exists():
        text = calibration.read_text(encoding="utf-8")
        for path in T.FINGERPRINT_COMPONENTS:
            assert path in text


_SCAN_IDS = (
    "semgrep-security",
    "semgrep-saga",
    "gitleaks",
    "osv-scanner",
    "jscpd",
    "lizard",
)


def _flagged_repo(tmp: Path) -> tuple[Path, str, str]:
    """Head commit adds ``FLAGGED`` on line 2. The working tree deletes it again."""
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("example==1\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("one\nFLAGGED\n", encoding="utf-8")
    head = _commit(repo, "head")
    (repo / "src" / "app.py").write_text("one\n", encoding="utf-8")
    return repo, base, head


def _flagged_body(tool_id: str, flagged: bool) -> str:
    if not flagged:
        if tool_id == "gitleaks":
            return "[]"
        if tool_id == "lizard":
            return "nloc,ccn,tokens,params,length,file,function,start,end\n"
        if tool_id == "jscpd":
            return '{"duplicates":[]}'
        return "{}"
    if tool_id == "semgrep-security":
        return json.dumps({"results": [{
            "check_id": "example",
            "path": "src/app.py",
            "start": {"line": 2},
            "end": {"line": 2},
            "extra": {"severity": "ERROR", "message": "flagged"},
        }]})
    if tool_id == "semgrep-saga":
        return json.dumps({"results": [{
            "check_id": "saga.swallowed",
            "path": "src/app.py",
            "start": {"line": 2},
            "end": {"line": 2},
            "extra": {
                "message": "flagged",
                "metadata": {"row": "correctness.pattern.swallowed-error"},
            },
        }]})
    if tool_id == "gitleaks":
        return json.dumps([{
            "RuleID": "example-rule",
            "File": "src/app.py",
            "StartLine": 2,
            "EndLine": 2,
        }])
    if tool_id == "osv-scanner":
        return json.dumps({"results": [{
            "source": {"path": "requirements.txt"},
            "packages": [{"vulnerabilities": [{
                "id": "CVE-FLAGGED",
                "severity": [{"type": "CVSS_V3", "score": "9.0"}],
            }]}],
        }]})
    if tool_id == "jscpd":
        return json.dumps({"duplicates": [{
            "lines": 8,
            "tokens": 60,
            "firstFile": {"name": "src/app.py", "start": 2},
            "secondFile": {"name": "src/other.py", "start": 2},
        }]})
    return (
        "nloc,ccn,tokens,params,length,file,function,start,end\n"
        "20,16,100,2,2,src/app.py,heavy,2,2\n"
    )


def _watch(adapter: Any, repo: Path) -> Any:
    original = adapter.invoke

    def invoke(context: Any) -> list[str]:
        assert context.repo == context.root
        assert context.repo.resolve() != repo.resolve()
        return original(context)

    return replace(adapter, invoke=invoke)


def _tool_profile(tmp: Path, home: Path, tool_id: str) -> Path:
    binary = {
        "semgrep-security": "semgrep",
        "semgrep-saga": "semgrep",
        "gitleaks": "gitleaks",
        "osv-scanner": "osv-scanner",
        "jscpd": "jscpd",
        "lizard": "lizard",
    }[tool_id]
    pin: dict[str, Any] = {"version": "1.0.0"}
    if tool_id == "semgrep-security":
        cache = T.semgrep_cache(home, "p/security-audit")
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "rules.yml").write_text("rules: []\n", encoding="utf-8")
        pin["rules"] = [{"pack": "p/security-audit", "sha256": T.digest_tree(cache)}]
    return _profile(tmp / f"{tool_id}.json", {"review_tools": {"pins": {binary: pin}}})


@pytest.mark.parametrize("tool_id", _SCAN_IDS)
def test_head_worktree_uncommitted_edit_keeps_the_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_id: str,
) -> None:
    adapters = _load("review_adapters_all_languages")
    if tool_id == "semgrep-saga":
        plugin = tmp_path / "plugin"
        rules = plugin / "references" / "semgrep"
        rules.mkdir(parents=True)
        (rules / "rule.yml").write_text("rules: []\n", encoding="utf-8")
        monkeypatch.setattr(T, "plugin_root", lambda: plugin)
    repo, base, head = _flagged_repo(tmp_path)
    assert "FLAGGED" not in (repo / "src" / "app.py").read_text(encoding="utf-8")
    home = tmp_path / "home"
    adapter = _watch(next(item for item in adapters.ADAPTERS if item.id == tool_id), repo)

    def handler(argv: list[str], cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0\n")
        app = cwd / "src" / "app.py"
        flagged = app.is_file() and "FLAGGED" in app.read_text(encoding="utf-8")
        body = _flagged_body(tool_id, flagged)
        if "--output" in argv:
            report_dir = Path(argv[argv.index("--output") + 1])
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "jscpd-report.json").write_text(body, encoding="utf-8")
            return T.ProcessResult(0, "")
        return T.ProcessResult(0, body)

    runner = _Calls(handler)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _tool_profile(tmp_path, home, tool_id), output, home,
        adapters=[adapter], runner=runner,
    )
    assert code == 0, _reasons(output) if output.exists() else code
    assert _read(output, "findings.json")
    scans = [call["cwd"] for call in runner.calls if not _version(call["argv"])]
    assert scans
    assert all(path.resolve() != repo.resolve() for path in scans)


def test_head_worktree_uncommitted_rules_stay_a_known_gap(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    rules = repo / "missing-rules"
    rules.mkdir()
    (rules / "rule.yml").write_text("rules: []\n", encoding="utf-8")
    runner = _Calls(_ok())
    output = tmp_path / "out"
    adapter = _stub(gap_path="missing-rules", gap_rows=("correctness.pattern.swallowed-error",))
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[adapter], runner=runner,
    )
    assert code == 0
    assert runner.calls == []
    assert ("stub", "correctness.pattern.swallowed-error", "known-gap") in _reasons(output)


def test_head_worktree_hooks_do_not_run(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\n", encoding="utf-8")
    marker = tmp_path / "hook-ran"
    hook = repo / "hooks" / "post-checkout"
    hook.parent.mkdir()
    hook.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\n", encoding="utf-8")
    hook.chmod(0o755)
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("two\n", encoding="utf-8")
    head = _commit(repo, "head")
    _git(repo, "config", "core.hooksPath", "hooks")
    control = tmp_path / "control"
    added = subprocess.run(
        ["git", "worktree", "add", "--detach", str(control), head],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    assert marker.is_file(), added.stderr
    marker.unlink()
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(control)],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    output = tmp_path / "out"
    code = _run(repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home", adapters=[])
    assert code == 0
    assert not marker.exists()


def test_head_worktree_uncommitted_probe_keeps_the_failure_and_the_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    uncovered = json.dumps({
        "files": {"src/app.py": {"missing_branches": [[4, 5]], "missing_lines": []}},
    })
    full = json.dumps({"files": {"src/app.py": {"missing_branches": [], "missing_lines": []}}})
    (repo / "probe.py").write_text(
        "import pathlib\n"
        "pathlib.Path('coverage.json').write_text(" + repr(uncovered) + ", encoding='utf-8')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nFOUR\nfive\n", encoding="utf-8")
    head = _commit(repo, "head")
    (repo / "probe.py").write_text(
        "import pathlib\n"
        "pathlib.Path('coverage.json').write_text(" + repr(full) + ", encoding='utf-8')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    command = shlex.join([sys.executable, "probe.py"])
    profile = _profile(tmp_path / "profile.json", {"review_tools": {"languages": {"python": {
        "test_command": command,
        "coverage_report": "coverage.json",
    }}}})
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home", adapters=[], framework=True,
    )
    assert code == 0
    rows = [item["rule"]["row"] for item in _read(output, "findings.json")]
    assert _RELOCATED in rows
    assert "testing.uncovered-branch" in rows
    assert _read(output, "measurements.json")[0]["value"] != 1.0


def _semgrep_cache(home: Path) -> str:
    cache = T.semgrep_cache(home, "p/security-audit")
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "rules.yml").write_text("rules: []\n", encoding="utf-8")
    return T.digest_tree(cache)


def test_head_profile_pins_and_command_come_from_base(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "README").write_text("one\n", encoding="utf-8")
    home = tmp_path / "home"
    digest = _semgrep_cache(home)
    base_profile = {
        "review_tools": {
            "languages": {"python": {"test_command": "echo BASEMARKER"}},
            "pins": {"semgrep": {"version": "1.0.0", "rules": [
                {"pack": "p/security-audit", "sha256": digest},
            ]}},
        },
    }
    (repo / ".saga-profile.json").write_text(json.dumps(base_profile), encoding="utf-8")
    base = _commit(repo, "base")
    head_profile = {
        "review_tools": {
            "languages": {"python": {"test_command": "true"}},
            "pins": {"semgrep": {"version": "1.0.0", "rules": [
                {"pack": "p/other", "sha256": "a" * 64},
            ]}},
        },
    }
    (repo / ".saga-profile.json").write_text(json.dumps(head_profile), encoding="utf-8")
    head = _commit(repo, "head")
    (repo / ".saga-profile.json").write_text(json.dumps({
        "review_tools": {"languages": {"python": {"test_command": "echo WORKTREE"}}},
    }), encoding="utf-8")
    adapters = _load("review_adapters_all_languages")
    adapter = next(item for item in adapters.ADAPTERS if item.id == "semgrep-security")
    argv_seen: list[list[str]] = []

    def handler(argv: list[str], _cwd: Path, _env: dict[str, str]) -> Any:
        argv_seen.append(list(argv))
        if _version(argv):
            return T.ProcessResult(0, "1.0.0\n")
        return T.ProcessResult(0, "{}")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, repo / ".saga-profile.json", output, home,
        adapters=[adapter], runner=_Calls(handler), framework=True,
    )
    assert code == 0
    cache = T.semgrep_cache(home, "p/security-audit")
    assert any(str(cache) in argv for argv in argv_seen)
    assert ["echo", "BASEMARKER"] in argv_seen
    assert ["true"] not in argv_seen
    assert all("WORKTREE" not in token for argv in argv_seen for token in argv)
    changes = [item for item in _read(output, "degraded.json") if item["reason"] == "head-profile-change"]
    assert changes == [{
        "lens": "security",
        "language": "none",
        "input": "head-profile",
        "tool": "review-tools",
        "reason": "head-profile-change",
    }]


def test_head_profile_added_when_base_has_none_is_recorded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "README").write_text("one\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / ".saga-profile.json").write_text(json.dumps({
        "review_tools": {"languages": {"python": {"test_command": "true"}}},
    }), encoding="utf-8")
    head = _commit(repo, "head")
    argv_seen: list[list[str]] = []

    def handler(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        argv_seen.append(list(argv))
        return T.ProcessResult(0, "")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, repo / ".saga-profile.json", output, tmp_path / "home",
        adapters=[], runner=handler, framework=True,
    )
    assert code == 0
    assert argv_seen == []
    assert ("relocated-test", _RELOCATED, "known-gap") in _reasons(output)
    assert [item["reason"] for item in _read(output, "degraded.json")].count("head-profile-change") == 1


def test_head_profile_absent_on_both_commits_is_not_recorded(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    (repo / ".saga-profile.json").write_text(json.dumps({
        "review_tools": {"languages": {"python": {"test_command": "true"}}},
    }), encoding="utf-8")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, repo / ".saga-profile.json", output, tmp_path / "home",
        adapters=[], framework=True,
    )
    assert code == 0
    assert "head-profile-change" not in [item["reason"] for item in _read(output, "degraded.json")]
    assert ("relocated-test", _RELOCATED, "known-gap") in _reasons(output)


def test_head_profile_malformed_head_is_recorded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "README").write_text("one\n", encoding="utf-8")
    (repo / ".saga-profile.json").write_text(json.dumps({
        "review_tools": {"languages": {"python": {"test_command": "echo BASEMARKER"}}},
    }), encoding="utf-8")
    base = _commit(repo, "base")
    (repo / ".saga-profile.json").write_text("{", encoding="utf-8")
    head = _commit(repo, "head")
    argv_seen: list[list[str]] = []

    def handler(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        argv_seen.append(list(argv))
        return T.ProcessResult(0, "")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[], runner=handler, framework=True,
    )
    assert code == 0
    assert ["echo", "BASEMARKER"] in argv_seen
    assert [item["reason"] for item in _read(output, "degraded.json")].count("head-profile-change") == 1

    pins = tmp_path / "pins"
    _init(pins)
    (pins / "README").write_text("one\n", encoding="utf-8")
    (pins / ".saga-profile.json").write_text(json.dumps({
        "review_tools": {"languages": {"python": {"test_command": "echo BASEMARKER"}}},
    }), encoding="utf-8")
    pins_base = _commit(pins, "base")
    (pins / ".saga-profile.json").write_text(json.dumps({
        "review_tools": {"pins": {"semgrep": {"rules": [{"pack": "p/other", "sha256": "zz"}]}}},
    }), encoding="utf-8")
    pins_head = _commit(pins, "head")
    argv_seen.clear()
    second = tmp_path / "out-pins"
    code = _run(
        pins, pins_base, pins_head, _bare_profile(tmp_path / "pins-profile"), second,
        tmp_path / "home-pins", adapters=[], runner=handler, framework=True,
    )
    assert code == 0
    assert ["echo", "BASEMARKER"] in argv_seen
    assert [item["reason"] for item in _read(second, "degraded.json")].count("head-profile-change") == 1


def test_head_profile_malformed_base_exits_2(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / ".saga-profile.json").write_text("{", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README").write_text("one\n", encoding="utf-8")
    head = _commit(repo, "head")
    runner = _Calls(_ok())
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home",
        adapters=[_stub()], runner=runner,
    )
    assert code == 2
    assert runner.calls == []
    for name in _FOUR:
        assert not (output / name).exists()


def test_saga_rules_source_is_the_plugin_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = tmp_path / "plugin"
    rules = plugin / "references" / "semgrep"
    rules.mkdir(parents=True)
    (rules / "rule.yml").write_text("rules: []\n", encoding="utf-8")
    monkeypatch.setattr(T, "plugin_root", lambda: plugin)
    adapters = _load("review_adapters_all_languages")
    adapter = next(item for item in adapters.ADAPTERS if item.id == "semgrep-saga")
    repo = tmp_path / "repo"
    _init(repo)
    evil = repo / "plugins" / "saga" / "references" / "semgrep"
    evil.mkdir(parents=True)
    (evil / "evil.yml").write_text("rules: []\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("two\n", encoding="utf-8")
    head = _commit(repo, "head")

    def configs(runner: _Calls) -> list[str]:
        found = []
        for call in runner.calls:
            if "--config" not in call["argv"]:
                continue
            index = call["argv"].index("--config")
            found.append(call["argv"][index + 1])
        return found

    home = tmp_path / "home"
    profile = _profile(tmp_path / "profile.json", {
        "review_tools": {"pins": {"semgrep": {"version": "1.0.0"}}},
    })
    runner = _Calls(_ok("{}"))
    code = _run(repo, base, head, profile, tmp_path / "yaml", home, adapters=[adapter], runner=runner)
    assert code == 0
    rendered = configs(runner)
    assert len(rendered) == 1
    assert Path(rendered[0]).parent == home
    assert all("evil.yml" not in item and str(evil) not in item for item in rendered)

    (repo / ".saga-profile.json").write_text(json.dumps({
        "review_tools": {"pins": {"semgrep": {"version": "1.0.0", "rules": [
            {"path": "plugins/saga/references/semgrep"},
        ]}}},
    }), encoding="utf-8")
    profile_base = _commit(repo, "profile")
    pinned = _Calls(_ok("{}"))
    code = _run(
        repo, profile_base, head, repo / ".saga-profile.json", tmp_path / "pinned",
        tmp_path / "home-2", adapters=[adapter], runner=pinned,
    )
    assert code == 0
    rendered_pinned = configs(pinned)
    assert len(rendered_pinned) == 1
    assert Path(rendered_pinned[0]).parent == tmp_path / "home-2"


def test_relative_rule_path_survives_until_the_scan(tmp_path: Path) -> None:
    """A base-profile rule directory still exists when the fake runner is called."""
    repo = tmp_path / "repo"
    _init(repo)
    rules = repo / "rules" / "custom"
    rules.mkdir(parents=True)
    (rules / "r.yml").write_text("rules: []\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\n", encoding="utf-8")
    (repo / ".saga-profile.json").write_text(json.dumps({
        "review_tools": {"pins": {"semgrep": {"version": "1.0.0", "rules": [
            {"path": "rules/custom"},
        ]}}},
    }), encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("two\n", encoding="utf-8")
    (rules / "r.yml").write_text("rules: [head]\n", encoding="utf-8")
    head = _commit(repo, "head")
    (rules / "r.yml").unlink()
    rules.rmdir()
    rules.parent.rmdir()
    adapters = _load("review_adapters_all_languages")
    adapter = next(item for item in adapters.ADAPTERS if item.id == "semgrep-security")
    seen: list[Path] = []

    def handler(argv: list[str], cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0\n")
        config = Path(argv[argv.index("--config") + 1])
        assert config.is_dir()
        assert (config / "r.yml").read_text(encoding="utf-8") == "rules: []\n"
        assert not str(config.resolve()).startswith(str(Path(cwd).resolve()))
        seen.append(config)
        return T.ProcessResult(0, "{}")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, repo / ".saga-profile.json", output, tmp_path / "home",
        adapters=[adapter], runner=_Calls(handler),
    )
    assert code == 0, _reasons(output) if output.exists() else code
    assert seen
    assert not seen[0].exists()
    assert "known-gap" not in [item["reason"] for item in _read(output, "degraded.json")]


def test_jscpd_and_lizard_comments_on_changed_lines_are_recorded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("clean\n# jscpd:ignore-start\n", encoding="utf-8")
    (repo / "old.py").write_text("# lizard forgives\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("CHANGED\n# jscpd:ignore-start\n", encoding="utf-8")
    (repo / "dup.ts").write_text("// jscpd:ignore-end\n// lizard forgives\n", encoding="utf-8")
    head = _commit(repo, "head")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _bare_profile(tmp_path), output, tmp_path / "home", adapters=[],
    )
    assert code == 0
    notes = {
        (item["input"], item["reason"]): item
        for item in _read(output, "degraded.json")
        if item["reason"] in {"jscpd-ignore", "lizard-forgives", "gitleaks-allow"}
    }
    assert set(notes) == {("dup.ts", "jscpd-ignore"), ("dup.ts", "lizard-forgives")}
    assert notes[("dup.ts", "jscpd-ignore")] == {
        "lens": "architecture-maintainability",
        "language": "typescript",
        "input": "dup.ts",
        "tool": "jscpd",
        "reason": "jscpd-ignore",
    }
    assert notes[("dup.ts", "lizard-forgives")]["tool"] == "lizard"
    assert notes[("dup.ts", "lizard-forgives")]["lens"] == "architecture-maintainability"
    assert notes[("dup.ts", "lizard-forgives")]["language"] == "typescript"


def test_coverage_source_ignores_a_committed_report(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    full = json.dumps({"files": {"src/app.py": {"missing_branches": [], "missing_lines": []}}})
    uncovered = json.dumps({
        "files": {"src/app.py": {"missing_branches": [[4, 5]], "missing_lines": []}},
    })
    (repo / "coverage.json").write_text(full, encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nFOUR\nfive\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = _profile(tmp_path / "profile.json", {"review_tools": {"languages": {"python": {
        "test_command": "true",
        "coverage_report": "coverage.json",
    }}}})

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        assert shell is False
        if argv == ["true"]:
            (cwd / "coverage.json").write_text(uncovered, encoding="utf-8")
        return T.ProcessResult(0, "")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["location"]["lines"] == {"start": 4, "end": 4}
    assert _read(output, "measurements.json")[0]["value"] != 1.0


def test_coverage_source_missing_name_stays_no_report(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    (repo / "coverage.json").write_text(json.dumps({
        "files": {"src/app.py": {"missing_branches": [[4, 5]], "missing_lines": []}},
    }), encoding="utf-8")
    profile = _profile(tmp_path / "profile.json", {"review_tools": {"languages": {"python": {
        "test_command": "true",
        "coverage_report": "coverage.json",
    }}}})
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        adapters=[], runner=_Calls(_ok()), framework=True,
    )
    assert code == 0
    assert _read(output, "findings.json") == []
    assert ("coverage", "testing.uncovered-branch", "no-report") in _reasons(output)


def test_coverage_source_refuses_a_path_outside_the_relocated_directory(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    cases = (str(outside), "../coverage.json")
    for index, report in enumerate(cases):
        profile = _profile(tmp_path / f"profile-{index}.json", {"review_tools": {"languages": {
            "python": {"test_command": "true", "coverage_report": report},
        }}})
        output = tmp_path / f"out-{index}"
        code = _run(
            repo, base, head, profile, output, tmp_path / f"home-{index}",
            adapters=[], runner=_Calls(_ok()), framework=True,
        )
        assert code == 2
        for name in _FOUR:
            assert not (output / name).exists()

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        if argv == ["true"]:
            (cwd / "coverage.json").symlink_to(outside)
        return T.ProcessResult(0, "")

    profile = _profile(tmp_path / "link.json", {"review_tools": {"languages": {"python": {
        "test_command": "true",
        "coverage_report": "coverage.json",
    }}}})
    output = tmp_path / "link-out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home-link",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 2
    for name in _FOUR:
        assert not (output / name).exists()


def test_relocated_environment_is_allow_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ"):
        monkeypatch.setenv(name, os.environ.get(name) or "C")
    monkeypatch.setenv("SAGA_REVIEW_SENTINEL", "nope")
    monkeypatch.setenv("PYTHONPATH", "/tmp/nope")
    repo, base, head = _pair(tmp_path)
    profile = _profile(tmp_path / "profile.json", {
        "review_tools": {"languages": {"python": {"test_command": "true"}}},
    })
    recorded: dict[str, str] = {}

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        if argv == ["true"]:
            recorded.update(env)
        return T.ProcessResult(0, "")

    code = _run(
        repo, base, head, profile, tmp_path / "out", tmp_path / "home",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 0
    assert set(recorded) == {
        "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "HOME", "TMPDIR", "TMP", "TEMP",
    }
    assert recorded["PATH"] == os.environ["PATH"]
    assert recorded["HOME"] != str(Path.home())
    assert "SAGA_REVIEW_SENTINEL" not in recorded
    assert recorded["TMPDIR"] == recorded["TMP"] == recorded["TEMP"]


def _vuln_parse(text: str) -> Any:
    if "VULN" not in text:
        return T.ParseResult()
    return T.ParseResult((
        _hit(rule_id="vuln", anchor="vuln", whole_project=True, start=None),
    ))


def test_base_cache_follows_the_branch_not_the_typed_name(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "marker.txt").write_text("VULN\n", encoding="utf-8")
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    b1 = _commit(repo, "b1")
    _git(repo, "branch", "basebranch")
    (repo / "app.py").write_text("two\n", encoding="utf-8")
    head = _commit(repo, "head")
    scanned: list[str] = []

    def handler(argv: list[str], cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0")
        scanned.append(_git(cwd, "rev-parse", "HEAD"))
        text = (cwd / "marker.txt").read_text(encoding="utf-8")
        return T.ProcessResult(0, "VULN" if "VULN" in text else "{}")

    adapter = _stub(comparison="base-head", parse=_vuln_parse)
    home = tmp_path / "home"
    profile = _bare_profile(tmp_path)

    def once(name: str) -> Path:
        output = tmp_path / name
        code = _run(
            repo, "basebranch", head, profile, output, home,
            adapters=[adapter], runner=_Calls(handler),
        )
        assert code == 0
        return output

    first = once("out-1")
    assert b1 in scanned
    assert _read(first, "findings.json") == []
    scanned.clear()
    second = once("out-2")
    assert b1 not in scanned
    assert head in scanned
    assert _read(second, "findings.json") == []

    _git(repo, "checkout", "basebranch")
    (repo / "marker.txt").write_text("clean\n", encoding="utf-8")
    b2 = _commit(repo, "b2")
    _git(repo, "checkout", head)
    scanned.clear()
    third = once("out-3")
    assert b2 in scanned
    assert {item["rule"]["ref"] for item in _read(third, "findings.json")} == {"vuln"}
    scanned.clear()
    fourth = once("out-4")
    assert b2 not in scanned
    assert {item["rule"]["ref"] for item in _read(fourth, "findings.json")} == {"vuln"}

    cache = home / ".saga" / "review-cache" / "stub" / "1.0.0" / b2
    stored = list(cache.glob("*.json"))
    assert len(stored) == 1
    leftover = cache / "not-a-digest.json"
    leftover.write_text("[]", encoding="utf-8")
    body = json.loads(stored[0].read_text(encoding="utf-8"))
    body["key"]["settings"] = "0" * 64
    stored[0].write_text(json.dumps(body), encoding="utf-8")
    scanned.clear()
    fifth = once("out-5")
    assert b2 in scanned
    assert {item["rule"]["ref"] for item in _read(fifth, "findings.json")} == {"vuln"}
    assert leftover.is_file()


def test_empty_or_errored_stdout_is_degraded(tmp_path: Path) -> None:
    repo, base, head = _pair(tmp_path)
    scanned: list[str] = []

    def handler(argv: list[str], cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0")
        scanned.append(_git(cwd, "rev-parse", "HEAD"))
        return T.ProcessResult(0, "")

    adapter = _stub(comparison="base-head")
    home = tmp_path / "home"
    profile = _bare_profile(tmp_path)
    first = tmp_path / "out-1"
    code = _run(
        repo, base, head, profile, first, home, adapters=[adapter], runner=_Calls(handler),
    )
    assert code == 0
    assert base in scanned and head in scanned
    assert _read(first, "findings.json") == []
    assert ("stub", "security.scanner-medium-low", "empty-output") in _reasons(first)
    scanned.clear()
    second = tmp_path / "out-2"
    code = _run(
        repo, base, head, profile, second, home, adapters=[adapter], runner=_Calls(handler),
    )
    assert code == 0
    assert base in scanned
    assert ("stub", "security.scanner-medium-low", "empty-output") in _reasons(second)

    def clean(argv: list[str], _cwd: Path, _env: dict[str, str]) -> Any:
        if _version(argv):
            return T.ProcessResult(0, "1.0.0")
        return T.ProcessResult(0, "{}")

    def parse(text: str) -> Any:
        assert text.strip() == "{}"
        return T.ParseResult()

    third = tmp_path / "out-3"
    code = _run(
        repo, base, head, _bare_profile(tmp_path / "clean"), third, tmp_path / "home-clean",
        adapters=[_stub(comparison="base-head", parse=parse)], runner=_Calls(clean),
    )
    assert code == 0
    assert "empty-output" not in [item["reason"] for item in _read(third, "degraded.json")]


def test_untrusted_head_rule_is_documented() -> None:
    guide = (REFERENCES / "review-tools.md").read_text(encoding="utf-8")
    decisions = (
        REPO_ROOT / "docs" / "engineering-journal" / "DECISIONS.md"
    ).read_text(encoding="utf-8")
    profile = (REFERENCES / "repository-profile.md").read_text(encoding="utf-8")
    sentence = "The commit under review is untrusted."
    assert sentence in guide
    assert sentence in decisions
    assert "head-profile-change" in profile
