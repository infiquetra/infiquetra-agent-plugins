"""One review command, from a change to records (issue 160, card C10a)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import socket
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
_ALLOWED = frozenset({"git", "stub", "sandbox-exec", "bwrap", "python3"})
_CAPTURED = "AssertionError: returned 2\ntests/test_changed.py::test_changed\n"
_ZERO = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0, "seconds": 0}
_HEX_A = "ab" * 32
_HEX_B = "cd" * 32


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = _load("review_command")
T = C.review_tools
R = C.review_records
F = C.review_formula
A = C.reviewer_answer
RR = C.run_record
CAL = C.review_calibration


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse new connections from this process. A parent listener still uses ``socket.socket``."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("review command tests must make no network call")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture(autouse=True)
def _no_operator_langfuse(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """No test sees the operator's Langfuse keys, or writes the operator's queue."""
    for name in list(os.environ):
        if name.startswith(("SAGA_LANGFUSE_", "LANGFUSE_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("operator-home")))


#: The home this run started with, before the autouse fixture above swaps HOME.
_OPERATOR_HOME = Path(os.environ.get("HOME") or Path.home())


@pytest.fixture
def operator_rustup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rustup proxy (CI's cargo) still finds the operator's toolchains under the swapped HOME."""
    if "RUSTUP_HOME" not in os.environ:
        monkeypatch.setenv("RUSTUP_HOME", str(_OPERATOR_HOME / ".rustup"))


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-command@example.com")
    _git(repo, "config", "user.name", "review-command")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp: Path, *, function: bool) -> tuple[Path, str, str]:
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    if function:
        before, after = "def changed():\n    return 1\n", "def changed():\n    return 2\n"
    else:
        before, after = "one\ntwo\nthree\nfour\nfive\n", "one\ntwo\nthree\nFOUR\nfive\n"
    (repo / "src" / "app.py").write_text(before, encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text(after, encoding="utf-8")
    return repo, base, _commit(repo, "head")


def _profile(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "profile.json"
    path.write_text(json.dumps({"schema": "repository_profile.v1"}) + "\n", encoding="utf-8")
    return path


def _builder(path: Path, unit: str = "U1") -> Path:
    path.write_text(json.dumps({
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": unit,
        "acceptance_criteria": [
            {"id": "AC-1", "text": "The changed line is the one the stub reports.", "checks": ["line"]},
        ],
        "declarations": [],
        "reasons": [],
    }), encoding="utf-8")
    return path


def _bank(path: Path) -> Path:
    path.write_text(json.dumps({
        "schema": "question_bank.v1",
        "questions": [{
            "id": "correctness.q-changed",
            "lens": "correctness",
            "kind": "yes-no",
            "options": [
                {"id": "yes", "definition": "The change breaks the behaviour the name describes."},
                {"id": "no", "definition": "The change keeps that behaviour."},
            ],
            "piece": "function",
        }],
    }), encoding="utf-8")
    return path


class _Runner:
    """Runs git for real and returns a fixed scan for the stub tool. Never a shell."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        assert shell is False
        assert isinstance(argv, list)
        self.calls.append(list(argv))
        if Path(argv[0]).name == "git":
            proc = subprocess.run(
                argv, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=timeout,
            )
            return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
        if "--version" in argv:
            return T.ProcessResult(0, "1.0.0\n")
        return T.ProcessResult(0, "scan\n")


def _exec_runner() -> Any:
    """Runs the argument vector. The real-helper reproduction test uses this."""

    def run(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        assert shell is False
        proc = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False,
        )
        return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)

    return run


def _adapter(*, start: int, gap: bool = False, hit: bool = True) -> Any:
    def invoke(_context: Any) -> list[str]:
        if gap:
            raise T.ToolGap("missing", "security.scanner-high")
        return ["stub", "scan"]

    def parse(_text: str) -> Any:
        if not hit:
            return T.ParseResult()
        return T.ParseResult((T.Hit(
            rule_id="example", path="src/app.py", statement="A stub reported this.",
            anchor="example", start=start, end=start, row="security.scanner-high",
        ),))

    return T.Adapter(
        id="stub", tool="stub", invoke=invoke, parse=parse, default_version="1.0.0",
        rows=("security.scanner-high",), lens="security", comparison="lines",
    )


def _ask(
    *, status: str = "ok", consequence_status: str = "ok",
    consequence: str = "required-behaviour-missing",
) -> Any:
    def ask(_state: Any, questions: Any, **_kwargs: Any) -> Any:
        if isinstance(questions, dict) and "consequence" in questions:
            if consequence_status != "ok":
                return SimpleNamespace(status="error", answers={}, note="failed", model="jev-test")
            return SimpleNamespace(
                status="ok", model="jev-test", note="",
                answers={"consequence": {"type": "choice", "choice": consequence, "confidence": 0.9}},
            )
        if status != "ok":
            return SimpleNamespace(
                status="error", ok=False, answers={}, note="failed", model="", usage={},
            )
        answers = {key: {"type": "noul", "noul": 0.91} for key in questions}
        return SimpleNamespace(
            status="ok", ok=True, model="jev-test", latency_ms=5, note="",
            usage={"input_tokens": 12, "output_tokens": 4}, answers=answers,
        )

    return ask


def _main(argv: list[str], **kwargs: Any) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        code = C.main(argv, **kwargs)
    return code, buffer.getvalue()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _store(tmp: Path, units: list[dict[str, Any]] | None = None, issue: int = 160) -> Path:
    root = tmp / "runs"
    rows = units if units is not None else [{"id": "U1", "usage": {"entries": []}}]
    RR.save(root, RR.RunRecord(issue=issue, units=rows))
    return root


def _prepare(
    repo: Path, base: str, head: str, profile: Path, builder: Path, out: Path, home: Path,
    runner: _Runner, *, start: int, gap: bool = False, hit: bool = True, ask: Any = None,
    bank: Path | None = None, calibration: Path | None = None, store: Path | None = None,
    issue: int | None = None,
) -> tuple[int, str]:
    argv = [
        "prepare", "--repo", str(repo), "--base", base, "--head", head, "--profile", str(profile),
        "--builder-record", str(builder), "--out", str(out), "--home", str(home),
    ]
    if bank is not None:
        argv.extend(["--bank", str(bank)])
    if calibration is not None:
        argv.extend(["--calibration", str(calibration)])
    if issue is not None and store is not None:
        argv.extend(["--issue", str(issue), "--store-root", str(store)])
    return _main(
        argv, adapters=[_adapter(start=start, gap=gap, hit=hit)], runner=runner, ask=ask,
    )


def _names(packet: Path) -> set[str]:
    return {path.name for path in packet.iterdir()}


def _bools(packet: Path) -> dict[str, dict[str, bool]]:
    data = _read(packet / "may-block.json")
    return {
        str(lens): {
            str(language): bool(entry.get("blocks")) if isinstance(entry, dict) else False
            for language, entry in languages.items()
        }
        for lens, languages in data.items()
    }


def _location() -> dict[str, Any]:
    return {
        "scope": "lines", "file": "src/app.py", "lines": {"start": 2, "end": 2},
        "function": "changed", "anchor": "return 2",
    }


def _finding(statement: str, *, evidence: str = "reproduced", key: str = "wrong-return") -> dict[str, Any]:
    found: dict[str, Any] = {
        "key": key, "origin": "open-search", "lens": "correctness", "row": "judged",
        "location": _location(), "language": "python", "statement": statement,
        "consequence": "required-behaviour-missing", "trigger": "normal-use",
        "evidence": evidence, "introduced": True,
    }
    if evidence == "reproduced":
        found["proof"] = {
            "test": "tests/test_changed.py::test_changed",
            "command": "python3 -m pytest tests/test_changed.py -q",
            "output": "AssertionError: returned 2",
        }
    else:
        found["proof"] = {"steps": ["src/app.py:2 the return changed and the old test did not fail"]}
    return found


def _answer(findings: list[dict[str, Any]], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"schema": A.ANSWER_SCHEMA, "items": items or [], "findings": findings}


def _scratch(tmp: Path, *, with_test: bool) -> tuple[Path, dict[str, list[str]]]:
    scratch = tmp / "scratch"
    scratch.mkdir(parents=True)
    changes: dict[str, list[str]] = {"added": [], "modified": [], "deleted": []}
    if with_test:
        (scratch / "tests").mkdir()
        (scratch / "tests" / "test_changed.py").write_text(
            "def test_changed():\n    assert False\n", encoding="utf-8",
        )
        changes["modified"] = ["tests/test_changed.py"]
    return scratch, changes


def _result(
    scratch: Path, changes: dict[str, list[str]], *, session: str = "s1", agent: str = "",
    fingerprint: str = _HEX_B, prompt: str = _HEX_A,
) -> dict[str, Any]:
    return {
        "session_id": session,
        "agent_id": agent,
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "prompt_sha256": prompt,
        "configuration": {"fingerprint": fingerprint},
        "usage": {
            "input_tokens": 10,
            "cache_read_input_tokens": 1,
            "cache_creation_input_tokens": 2,
            "output_tokens": 3,
            "cost_usd": 0.5,
            "seconds": 1.5,
        },
        "scratch": {"path": str(scratch), "changes": changes},
    }


class _Confine:
    def __init__(self, code: int = 1, stdout: str = "", *, timeout: bool = False) -> None:
        self.code = code
        self.stdout = stdout
        self.timeout = timeout
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], _cwd: Path, _env: dict[str, str], _scratch: Path) -> Any:
        self.calls.append(list(argv))
        if self.timeout:
            raise subprocess.TimeoutExpired(list(argv), C.RERUN_TIMEOUT)
        return T.ProcessResult(self.code, self.stdout, "")


def _finish(
    packet: Path, pairs: list[tuple[dict[str, Any], dict[str, Any]]], home: Path, runner: _Runner,
    *, ask: Any = None, confine: Any = None, store: Path | None = None, issue: int | None = None,
    final: bool = False, extra: list[str] | None = None, directory: Path | None = None,
    trace_opener: Any = None,
) -> tuple[int, str]:
    parent = directory or packet.parent
    parent.mkdir(parents=True, exist_ok=True)
    argv = ["finish", "--packet", str(packet), "--home", str(home)]
    for index, (answer, result) in enumerate(pairs):
        answer_path = parent / f"answer-{index}.json"
        result_path = parent / f"result-{index}.json"
        _dump(answer_path, answer)
        _dump(result_path, result)
        argv.extend(["--answer", str(answer_path), "--result", str(result_path)])
    if issue is not None and store is not None:
        argv.extend(["--issue", str(issue), "--store-root", str(store)])
    if final:
        argv.append("--final")
    if extra:
        argv.extend(extra)
    return _main(argv, runner=runner, ask=ask, confine=confine, trace_opener=trace_opener)


def _line_packet(tmp: Path) -> tuple[Path, Path, _Runner]:
    repo, base, head = _repo(tmp, function=False)
    profile = _profile(tmp / "outside")
    builder = _builder(tmp / "builder.json")
    out = tmp / "packet"
    home = tmp / "home"
    home.mkdir()
    runner = _Runner()
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, runner, start=4,
    )
    assert code == 0, err
    return repo, out, runner


def _assert_change_and_patch(repo: Path, base: str, head: str, packet: Path) -> None:
    change = _read(packet / "change.json")
    assert change == {
        "base": base,
        "files": [{"path": "src/app.py", "status": "modified"}],
        "head": head,
        "repo": str(repo.resolve()),
    }
    patch = subprocess.run(
        ["git", "diff", "--find-renames", base, head],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    assert (packet / "diff.patch").read_text(encoding="utf-8") == patch.stdout
    assert (packet / "open-search-cap.json").read_text(encoding="utf-8").endswith("\n")
    assert _read(packet / "open-search-cap.json") == {"cap": A.OPEN_SEARCH_CAP}


def _grades_of(packet: Path) -> dict[str, Any]:
    return F.compute({
        "findings": _read(packet / "findings.json"),
        "measurements": _read(packet / "measurements.json"),
        "builder_records": [_read(packet / "builder-record.json")],
        "may_block": _bools(packet),
        "degraded_inputs": _read(packet / "degraded.json"),
    })


def _recorded_calibration(
    path: Path, *, configuration: dict[str, Any] | None = None
) -> Path:
    data = json.loads((REFERENCES / "review-calibration.json").read_text(encoding="utf-8"))
    counts = {name: 0 for name in CAL.COUNT_FIELDS}
    counts.update(held_out_defects=10, held_out_clean=10, repeat_cases=10)
    language = {"verdict": "cleared", **counts}
    data["corpus_run"] = "recorded"
    data["fingerprint"] = {
        relative: hashlib.sha256(CAL.locate(CAL.package_dir(), relative).read_bytes()).hexdigest()
        for relative in CAL.COMPONENTS
    }
    data["reviewer_configuration"] = configuration
    for lens in data["lenses"].values():
        lens["drift"] = "as-recorded"
        lens["overall"] = dict(counts)
        lens["languages"] = {"python": dict(language)}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _machine(home: Path, reproduction: str) -> None:
    directory = home / ".saga"
    directory.mkdir(mode=0o700, exist_ok=True)
    (directory / "machine.json").write_text(
        json.dumps({"survey": {"sandbox": {"reproduction": reproduction}}}), encoding="utf-8",
    )


# --- prepare -----------------------------------------------------------------------------------


def test_prepare_records_writes_validated_findings_and_identical_grades(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=False)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    store = _store(tmp_path)
    first = tmp_path / "packet"
    runner = _Runner()
    code, err = _prepare(
        repo, base, head, profile, builder, first, home, runner, start=4, store=store, issue=160,
    )
    assert code == 0, err
    findings = _read(first / "findings.json")
    assert len(findings) == 1
    assert R.validate(findings[0]) == []
    assert R.validate(_read(first / "measurements.json")) == [] or _read(first / "measurements.json") == []
    assert _read(first / "measurements.json") == []
    assert R.validate(_read(first / "builder-record.json")) == []
    assert _read(first / "builder-record.json")["unit"] == "U1"
    _assert_change_and_patch(repo, base, head, first)
    degraded = _read(first / "degraded.json")
    assert degraded == [{
        "input": "question-bank", "language": "none", "lens": "correctness", "reason": "no-bank",
        "tool": "jev",
    }]
    assert _read(first / "where-to-look.json") == []
    assert _read(first / "missing-tools.json") == []
    may_block = _read(first / "may-block.json")
    assert set(may_block) == {"security"}
    for language in ("none", "python"):
        assert may_block["security"][language] == {"blocks": False, "reason": "report-only no-run"}
    assert _read(first / "grades.json") == _grades_of(first)
    record = RR.load(store, 160)
    assert record is not None
    assert len(record.review_cycles) == 1
    stored = record.review_cycles[0]
    assert stored["loop"] == R.STORED_LOOP
    assert stored["where_to_look"] == []
    assert stored["usage"] == _ZERO
    assert R.validate(stored) == []
    second = tmp_path / "again"
    code, err = _prepare(
        repo, base, head, profile, builder, second, home, _Runner(), start=4,
    )
    assert code == 0, err
    assert (second / "grades.json").read_bytes() == (first / "grades.json").read_bytes()


def test_prepare_packet_names_every_where_to_look_item(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=True)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    bank = _bank(tmp_path / "bank.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), start=2, ask=_ask(), bank=bank,
    )
    assert code == 0, err
    where = _read(out / "where-to-look.json")
    assert len(where) == 1
    assert "answer" not in where[0]
    assert "answer: required" in R.validate(where[0])
    assert _read(out / "change.json")["head"] == head
    _assert_change_and_patch(repo, base, head, out)
    assert _read(out / "findings.json")
    assert all(R.validate(item) == [] for item in _read(out / "findings.json"))
    assert _read(out / "measurements.json") == []
    assert _read(out / "degraded.json") == []
    assert _read(out / "missing-tools.json") == []
    assert _read(out / "builder-record.json")["unit"] == "U1"
    may_block = _read(out / "may-block.json")
    assert may_block["security"]["python"]["reason"] == "report-only no-run"
    assert may_block["security"]["python"]["blocks"] is False
    assert _read(out / "grades.json") == _grades_of(out)
    again = tmp_path / "again"
    code, err = _prepare(
        repo, base, head, profile, builder, again, home, _Runner(), start=2, ask=_ask(), bank=bank,
    )
    assert code == 0, err
    assert (again / "grades.json").read_bytes() == (out / "grades.json").read_bytes()


def test_prepare_packet_grades_match_on_a_second_run(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=True)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    bank = _bank(tmp_path / "bank.json")
    home = tmp_path / "home"
    home.mkdir()
    ask = _ask()
    first, second = tmp_path / "one", tmp_path / "two"
    for out in (first, second):
        code, err = _prepare(
            repo, base, head, profile, builder, out, home, _Runner(), start=2, ask=ask, bank=bank,
        )
        assert code == 0, err
    assert (first / "grades.json").read_bytes() == (second / "grades.json").read_bytes()


def test_prepare_packet_failed_sweep_maps_degraded(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=True)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    bank = _bank(tmp_path / "bank.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(),
        start=2, ask=_ask(status="error"), bank=bank,
    )
    assert code == 0, err
    degraded = _read(out / "degraded.json")
    assert degraded
    for entry in degraded:
        assert {"lens", "language", "input", "reason"} <= set(entry)
        assert entry["lens"] in F.LENSES
        assert entry["language"] in F.LANGUAGES


def test_missing_tool_is_a_degraded_question_and_does_not_stop(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=False)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), start=4, gap=True,
    )
    assert code == 0, err
    where = _read(out / "where-to-look.json")
    assert len(where) == 1
    assert where[0]["classifier"] == {"model": "none", "name": "missing-tool"}
    assert where[0]["degraded"] is True
    assert any(entry["reason"] == "missing" for entry in _read(out / "degraded.json"))
    item = where[0]
    answer = _answer([], items=[{
        "index": 0,
        "file": item["location"]["file"],
        "answer": {"kind": "finding", "finding": "gap"},
    }])
    answer["findings"] = [{
        "key": "gap",
        "origin": {"item": 0},
        "lens": "correctness",
        "row": "judged",
        "location": {"scope": "whole-project", "file": ".", "anchor": "stub"},
        "language": "python",
        "statement": "The scanner did not run, so the change was not checked.",
        "consequence": "required-behaviour-missing",
        "trigger": "normal-use",
        "evidence": "traced",
        "proof": {"steps": [".:1 the stub scanner was not on the machine"]},
        "introduced": True,
    }]
    scratch, changes = _scratch(tmp_path, with_test=False)
    finish_code, finish_err = _finish(
        out, [(answer, _result(scratch, changes))], home, _Runner(), ask=_ask(),
    )
    assert finish_code == 0, finish_err
    run = _read(out / "review-run.json")
    assert R.validate(run) == []
    matched = [item for item in run["findings"] if item["statement"].startswith("The scanner")]
    assert matched and matched[0]["degraded"] is True
    assert run["merge"]["allowed"] is True


def test_missing_tool_remains_when_the_bank_is_absent(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=False)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), start=4, gap=True,
    )
    assert code == 0, err
    degraded = _read(out / "degraded.json")
    assert any(entry["reason"] == "no-bank" for entry in degraded)
    assert any(entry["reason"] == "missing" for entry in degraded)
    where = _read(out / "where-to-look.json")
    assert len(where) == 1
    assert where[0]["classifier"]["name"] == "missing-tool"
    assert all(item["classifier"]["name"] != "jev" for item in where)


# --- finish ------------------------------------------------------------------------------------


def test_finish_grades_writes_the_five_record_kinds(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=True)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    bank = _bank(tmp_path / "bank.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), start=2, ask=_ask(), bank=bank,
    )
    assert code == 0, err
    where = _read(out / "where-to-look.json")
    assert len(where) == 1
    cleared = _answer([], items=[{
        "index": 0,
        "file": where[0]["location"]["file"],
        "answer": {
            "kind": "cleared",
            "reason": "The function still returns a number and the stub line is the only finding.",
        },
    }])
    scratch, changes = _scratch(tmp_path, with_test=False)
    code, err = _finish(out, [(cleared, _result(scratch, changes))], home, _Runner(), ask=_ask())
    assert code == 0, err
    run = _read(out / "review-run.json")
    assert R.validate(run) == []
    assert {item["kind"] for item in run["findings"]} == {"finding"}
    assert any(item["evidence"] == "tool-result" for item in run["findings"])
    assert len(run["lens_grades"]) == 4
    letters = {row["lens"]: row["grade"] for row in run["lens_grades"]}
    expected = _grades_of(out)
    # The packet degraded list is what finish graded. The sweep item was cleared, not a finding.
    expected = F.compute({
        "findings": _read(out / "findings.json"),
        "measurements": _read(out / "measurements.json"),
        "builder_records": [_read(out / "builder-record.json")],
        "may_block": _bools(out),
        "degraded_inputs": _read(out / "degraded.json"),
    })
    assert letters == {row["lens"]: row["grade"] for row in expected["lens_grades"]}
    assert letters["security"] == "D"
    assert run["where_to_look"][0]["answer"]["kind"] == "cleared"


def test_answer_covers_every_item_or_is_refused(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=True)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    bank = _bank(tmp_path / "bank.json")
    home = tmp_path / "home"
    home.mkdir()
    store = _store(tmp_path)
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), start=2, ask=_ask(), bank=bank,
        store=store, issue=160,
    )
    assert code == 0, err
    before = len(RR.load(store, 160).review_cycles)
    scratch, changes = _scratch(tmp_path, with_test=False)
    code, err = _finish(
        out, [(_answer([]), _result(scratch, changes))], home, _Runner(), ask=_ask(),
        store=store, issue=160,
    )
    assert code == 1
    assert "src/app.py" in err
    assert not (out / "review-run.json").exists()
    assert len(RR.load(store, 160).review_cycles) == before


def test_finish_refuses_a_bad_answer_and_writes_nothing(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    scratch, changes = _scratch(tmp_path, with_test=False)
    bad = _answer([])
    bad["severity"] = "blocks"
    before = _names(packet)
    code, err = _finish(packet, [(bad, _result(scratch, changes))], home, runner, ask=_ask())
    assert code == 1
    assert "severity" in err
    assert _names(packet) == before
    assert not (packet / "review-run.json").exists()
    _dump(packet / "open-search-cap.json", {"cap": True})
    listed = _names(packet)
    code, err = _finish(
        packet, [(_answer([]), _result(scratch, changes))], home, runner, ask=_ask(),
        directory=tmp_path / "second",
    )
    assert code == 2
    assert "open-search-cap" in err
    assert _names(packet) == listed
    assert not (packet / "review-run.json").exists()


def _uncited_scratch(tmp: Path, *, with_cited: bool) -> tuple[Path, dict[str, list[str]]]:
    """A scratch copy that also adds a guard test no finding names."""
    scratch, changes = _scratch(tmp, with_test=with_cited)
    (scratch / "tests").mkdir(exist_ok=True)
    (scratch / "tests" / "test_no_credentials.py").write_text(
        "def test_guard():\n    assert True\n", encoding="utf-8",
    )
    changes["added"] = ["tests/test_no_credentials.py"]
    return scratch, changes


def test_finish_accepts_an_uncited_test_file_with_a_warning_and_grades_the_findings(
    tmp_path: Path,
) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    scratch, changes = _uncited_scratch(tmp_path, with_cited=False)
    traced = _answer([_finding("The return changed and no test failed.", evidence="traced")])
    code, err = _finish(packet, [(traced, _result(scratch, changes))], home, runner, ask=_ask())
    assert code == 0, err
    assert (
        "warning: scratch.changes: tests/test_no_credentials.py (added) is a test file no "
        "reproduced finding names; it is not evidence and was ignored"
    ) in err
    run = _read(packet / "review-run.json")
    assert R.validate(run) == []
    found = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert found["evidence"] == "traced"
    assert found["statement"] == "The return changed and no test failed."
    entry = {
        "lens": "correctness", "language": "none", "input": "tests/test_no_credentials.py",
        "tool": "review-command", "reason": "uncited-test-file",
    }
    assert entry in run["degraded_inputs"]
    correctness = next(row for row in run["lens_grades"] if row["lens"] == "correctness")
    assert entry in correctness["degraded_inputs"]


def test_finish_still_refuses_a_modified_file_beside_an_uncited_test(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    scratch, changes = _uncited_scratch(tmp_path, with_cited=False)
    changes["modified"] = ["src/app.py"]
    code, err = _finish(
        packet, [(_answer([]), _result(scratch, changes))], home, runner, ask=_ask(),
    )
    assert code == 1
    assert "src/app.py (modified) is not a reproduction test" in err
    assert "warning:" not in err
    assert not (packet / "review-run.json").exists()


def test_an_uncited_test_file_is_never_laid_over_the_rerun_tree(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _uncited_scratch(tmp_path, with_cited=True)
    seen: list[tuple[bool, bool]] = []

    def confine(argv: list[str], cwd: Path, _env: dict[str, str], _scratch: Path) -> Any:
        seen.append((
            (cwd / "tests" / "test_changed.py").is_file(),
            (cwd / "tests" / "test_no_credentials.py").exists(),
        ))
        return T.ProcessResult(1, _CAPTURED, "")

    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    assert "tests/test_no_credentials.py (added)" in err
    assert seen == [(True, False)]


def test_a_case_only_spelling_of_the_cited_test_is_neither_warned_nor_ignored(
    tmp_path: Path,
) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch = tmp_path / "scratch"
    (scratch / "tests").mkdir(parents=True)
    (scratch / "tests" / "test_Changed.py").write_text(
        "def test_changed():\n    assert False\n", encoding="utf-8",
    )
    changes = {"added": ["tests/test_Changed.py"], "modified": [], "deleted": []}
    confine = _Confine(1, _CAPTURED)
    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    assert "warning:" not in err
    run = _read(packet / "review-run.json")
    assert not [d for d in run["degraded_inputs"] if d["reason"] == "uncited-test-file"]


def test_merge_answers_keeps_one_finding_and_its_reproduction(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    traced_dir = tmp_path / "traced-scratch"
    traced_dir.mkdir()
    reproduced_dir, reproduced_changes = _scratch(tmp_path / "repro", with_test=True)
    first = _answer([_finding("The first answer only traced the return.", evidence="traced", key="traced")])
    second = _answer([_finding("The second answer reproduced the wrong return.", key="reproduced")])
    confine = _Confine(1, _CAPTURED)
    code, err = _finish(
        packet,
        [
            (first, _result(traced_dir, {"added": [], "modified": [], "deleted": []}, session="s1")),
            (second, _result(reproduced_dir, reproduced_changes, session="s2")),
        ],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    judged = [item for item in run["findings"] if item["rule"]["row"] == "judged"]
    assert len(judged) == 1
    assert judged[0]["evidence"] == "reproduced"
    assert judged[0]["statement"] == "The second answer reproduced the wrong return."
    assert confine.calls


# --- re-run ------------------------------------------------------------------------------------


def _repro_packet(tmp: Path) -> tuple[Path, Path, _Runner]:
    return _line_packet(tmp)


def test_reproduced_rerun_keeps_a_failing_match(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    confine = _Confine(1, _CAPTURED)
    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    found = next(item for item in run["findings"] if item["evidence"] != "tool-result")
    assert found["evidence"] == "reproduced"
    assert found["unconfirmed"] is True
    assert found["consequence_jev"] is None
    assert confine.calls


def test_reproduced_rerun_exit_zero_is_traced(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    scratch, changes = _scratch(tmp_path, with_test=True)
    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(), confine=_Confine(0, "passed\n"),
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    found = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert found["evidence"] == "traced"
    assert found["unconfirmed"] is False
    assert found["consequence_jev"] == "required-behaviour-missing"
    assert run["merge"]["allowed"] is True


def test_reproduced_rerun_output_mismatch_is_traced(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    scratch, changes = _scratch(tmp_path, with_test=True)
    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"),
        confine=_Confine(1, "Error: a different failure\n"),
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    found = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert found["evidence"] == "traced"
    assert found["unconfirmed"] is False
    assert found["consequence_jev"] is None


def test_reproduced_rerun_timeout_is_traced(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    scratch, changes = _scratch(tmp_path, with_test=True)
    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(), confine=_Confine(timeout=True),
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    found = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert found["evidence"] == "traced"
    assert found["unconfirmed"] is False
    assert any(entry["reason"] == "re-run-timeout" for entry in run["degraded_inputs"])


def test_reproduced_rerun_without_a_sandbox_is_degraded(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "unavailable")
    scratch, changes = _scratch(tmp_path, with_test=True)
    calls: list[list[str]] = []

    def confine(*_args: Any) -> Any:
        calls.append(["called"])
        return T.ProcessResult(1, "AssertionError: returned 2\n")

    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=None,
    )
    assert code == 0, err
    assert calls == []
    run = _read(packet / "review-run.json")
    found = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert found["evidence"] == "traced"
    assert found["unconfirmed"] is False
    assert any(entry["reason"] == "no-sandbox" for entry in run["degraded_inputs"])


def test_reproduced_rerun_final_round_reruns_blocking_commands(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    scratch, changes = _scratch(tmp_path, with_test=True)
    (scratch / "tests" / "conftest.py").write_text("VALUE = 1\n", encoding="utf-8")
    changes["modified"].append("tests/conftest.py")
    helper = _finding("The helper is part of the re-run.", key="helper")
    helper["consequence"] = "style"
    helper["location"] = {**_location(), "anchor": "helper", "function": "helper"}
    helper["proof"] = {
        "test": "tests/conftest.py",
        "command": "python3 -c 'import tests.conftest'",
        "output": "helper loaded",
    }

    class _Two:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def __call__(self, argv: list[str], cwd: Path, _env: dict[str, str], _scratch: Path) -> Any:
            self.calls.append(list(argv))
            assert (cwd / "src" / "app.py").is_file()
            assert (cwd / "tests" / "conftest.py").is_file()
            assert (cwd / "tests" / "test_changed.py").is_file()
            assert (cwd / "tmp").is_dir()
            if len(self.calls) == 1:
                return T.ProcessResult(1, _CAPTURED)
            return T.ProcessResult(0, "passed\n")

    confine = _Two()
    harm = _finding("A retry returns the new number.")
    code, err = _finish(
        packet, [(_answer([harm, helper]), _result(scratch, changes))],
        home, runner, ask=_ask(), confine=confine, final=True,
    )
    assert code == 0, err
    assert len(confine.calls) == 3
    assert all(Path(call[0]).name == "python3" for call in confine.calls)
    run = _read(packet / "review-run.json")
    found = next(
        item for item in run["findings"] if item["statement"] == "A retry returns the new number."
    )
    assert found["evidence"] == "traced"
    assert found["unconfirmed"] is False
    tool = next(item for item in run["findings"] if item["source"]["kind"] == "tool")
    assert "command" not in tool["proof"]
    fresh = F.compute({
        "findings": [
            {key: value for key, value in item.items() if key not in F.COMPUTED_FINDING_KEYS}
            for item in run["findings"]
        ],
        "measurements": run["measurements"],
        "builder_records": run["builder_records"],
        "may_block": run["may_block"],
        "degraded_inputs": run["degraded_inputs"],
    })
    assert [row["grade"] for row in run["lens_grades"]] == [row["grade"] for row in fresh["lens_grades"]]


@pytest.mark.skipif(C.platform_helper() is None, reason="no reproduction helper on this platform")
def test_reproduced_rerun_real_helper_denies_home_network_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "tmp").mkdir()
    script = scratch / "probe.py"
    outside = tmp_path / "outside-target"
    canary = Path.home() / f".saga-review-canary-{os.getpid()}"
    canary.write_text("canary\n", encoding="utf-8")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.3)
    port = listener.getsockname()[1]
    outside_tmp = Path("/tmp") / f"saga-review-outside-{os.getpid()}"
    outside_tmp.write_text("outside-sentinel\n", encoding="utf-8")
    script.write_text(
        "import os, pathlib, socket, subprocess, sys\n"
        "outside, canary, port, private = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]\n"
        "print('HOME=' + os.environ.get('HOME', ''))\n"
        "for name in ('AWS_SECRET_ACCESS_KEY', 'GITHUB_TOKEN', 'TYPESAFE_API_KEY'):\n"
        "    print(name + '=' + ('set' if os.environ.get(name) else 'absent'))\n"
        "try:\n"
        "    pathlib.Path(outside).write_text('nope', encoding='utf-8')\n"
        "    print('outside=wrote')\n"
        "except OSError:\n"
        "    print('outside=blocked')\n"
        "try:\n"
        "    print('canary=' + pathlib.Path(canary).read_text(encoding='utf-8').strip())\n"
        "except OSError:\n"
        "    print('canary=blocked')\n"
        "try:\n"
        "    print('privatetmp=' + pathlib.Path(private).read_text(encoding='utf-8').strip())\n"
        "except OSError:\n"
        "    print('privatetmp=blocked')\n"
        "try:\n"
        "    pasted = subprocess.run(['/usr/bin/pbpaste'], capture_output=True, text=True, timeout=3)\n"
        "    print('clipboard=code:%s:bytes:%s' % (pasted.returncode, len(pasted.stdout or '')))\n"
        "except Exception:\n"
        "    print('clipboard=blocked')\n"
        "try:\n"
        "    pathlib.Path('/dev/null').write_text('')\n"
        "    print('devnull=ok')\n"
        "except OSError:\n"
        "    print('devnull=blocked')\n"
        "try:\n"
        "    sock = socket.create_connection(('127.0.0.1', port), timeout=2)\n"
        "    sock.close()\n"
        "    print('connect=ok')\n"
        "except OSError:\n"
        "    print('connect=blocked')\n",
        encoding="utf-8",
    )
    for name in ("AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "TYPESAFE_API_KEY"):
        monkeypatch.setenv(name, "sentinel-not-a-secret")
    python = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else sys.executable
    env = C.child_environment(scratch)
    for name in ("AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "TYPESAFE_API_KEY"):
        assert name not in env
    try:
        result = C.run_confined(
            [python, str(script), str(outside), str(canary), str(port), str(outside_tmp)],
            scratch, env, scratch, runner=T.subprocess_runner, timeout=30,
        )
        accepted = False
        try:
            conn, _addr = listener.accept()
            conn.close()
            accepted = True
        except OSError:
            accepted = False
    finally:
        listener.close()
        canary.unlink(missing_ok=True)
        outside_tmp.unlink(missing_ok=True)
    assert result.code == 0, result.stderr
    text = result.stdout
    assert "outside=blocked" in text
    assert "canary=blocked" in text
    assert "privatetmp=blocked" in text
    assert "devnull=ok" in text
    clipboard = next(line for line in text.splitlines() if line.startswith("clipboard="))
    if clipboard != "clipboard=blocked":
        code_text, byte_text = clipboard.removeprefix("clipboard=code:").split(":bytes:")
        assert code_text != "0"
        assert byte_text == "0"
    assert "connect=blocked" in text
    assert accepted is False
    assert not outside.exists()
    home = text.split("HOME=", 1)[1].splitlines()[0]
    assert Path(home).resolve() == scratch.resolve() or scratch.resolve() in Path(home).resolve().parents
    assert Path(home).resolve() != Path.home().resolve()
    for name in ("AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "TYPESAFE_API_KEY"):
        assert f"{name}=absent" in text


def _cargo_reproduction(statement: str, recorded: str, cited: str) -> dict[str, Any]:
    found = _finding(statement, key="cargo-" + cited.rsplit("::", 1)[-1])
    found["language"] = "rust"
    found["proof"] = {
        "test": f"tests/repro_test.rs::{cited}",
        "command": "cargo test --offline --test repro_test",
        "output": recorded,
    }
    return found


def test_reproduced_rerun_matches_a_rust_test_in_cargos_own_output(tmp_path: Path) -> None:
    """Issue 264: cargo never prints ``path.rs::name``, and its panic line carries a thread id."""
    fixtures = Path(__file__).resolve().parent / "fixtures" / "reproduction_output"
    recorded = (fixtures / "cargo_two_failures.txt").read_text(encoding="utf-8")
    rerun = (fixtures / "cargo_one_failure.txt").read_text(encoding="utf-8")
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    scratch = tmp_path / "scratch"
    (scratch / "tests").mkdir(parents=True)
    (scratch / "tests" / "repro_test.rs").write_text("// reproduction\n", encoding="utf-8")
    changes = {"added": ["tests/repro_test.rs"], "modified": [], "deleted": []}
    confirmed = _cargo_reproduction("add subtracts.", recorded, "adds_two_numbers")
    unrelated = _cargo_reproduction("A different test failed.", recorded, "other_failure")
    unrelated["location"] = {**_location(), "anchor": "other", "function": "other"}
    confine = _Confine(101, rerun)
    code, err = _finish(
        packet, [(_answer([confirmed, unrelated]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    stored = {item["statement"]: item for item in run["findings"] if item["source"]["kind"] == "llm"}
    assert stored["add subtracts."]["evidence"] == "reproduced"
    assert stored["A different test failed."]["evidence"] == "traced"


def test_reproduced_rerun_generic_header_is_traced(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    scratch, changes = _scratch(tmp_path, with_test=True)
    found = _finding("A generic header is not the failure.")
    found["proof"] = {
        "test": "tests/test_changed.py::test_changed",
        "command": "python3 -m pytest tests/test_changed.py -q",
        "output": "Traceback (most recent call last):",
    }
    confine = _Confine(
        1, "Traceback (most recent call last):\nModuleNotFoundError: No module named 'app'\n",
    )
    code, err = _finish(
        packet, [(_answer([found]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    stored = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert stored["evidence"] == "traced"
    assert stored["unconfirmed"] is False
    assert confine.calls


def test_reproduced_rerun_refuses_a_symlink(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    scratch = tmp_path / "scratch"
    (scratch / "tests").mkdir(parents=True)
    secret = tmp_path / "secret-test.py"
    secret.write_text("def test_changed():\n    raise AssertionError('returned 2')\n", encoding="utf-8")
    (scratch / "tests" / "test_changed.py").symlink_to(secret)
    changes = {"added": ["tests/test_changed.py"], "modified": [], "deleted": []}
    confine = _Confine(1, _CAPTURED)
    code, err = _finish(
        packet, [(_answer([_finding("A link is not the test file.")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    stored = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert stored["evidence"] == "traced"
    assert any(entry["reason"] == "missing-test-file" for entry in run["degraded_inputs"])
    assert confine.calls == []


@pytest.mark.skipif(C.platform_helper() is None, reason="no reproduction helper on this platform")
def test_reproduced_rerun_real_helper_confirms_an_imported_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    _machine(home, "available")
    packet = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, packet, home, _Runner(), start=2, ask=_ask(),
    )
    assert code == 0, err
    scratch = tmp_path / "scratch"
    (scratch / "tests").mkdir(parents=True)
    (scratch / "tests" / "test_app.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "import app\n"
        "\n"
        "def test_add():\n"
        "    got = app.add(1, 1)\n"
        "    assert got == 2, f'add returned {got}'\n",
        encoding="utf-8",
    )
    changes = {"added": ["tests/test_app.py"], "modified": [], "deleted": []}
    confirmed = _finding("The add function returns 0.", key="confirmed")
    confirmed["location"] = {**_location(), "anchor": "add returned 0", "function": "add"}
    confirmed["proof"] = {
        "test": "tests/test_app.py::test_add",
        "command": "python3 -m pytest tests/test_app.py::test_add -q --tb=line",
        "output": "AssertionError: add returned 0",
    }
    unrelated = _finding("A missing module is not that failure.", key="unrelated")
    unrelated["location"] = {**_location(), "anchor": "missing module", "function": "missing"}
    unrelated["proof"] = {
        "test": "tests/test_app.py::test_add",
        "command": "python3 -c \"import missing_module_for_review\"",
        "output": "AssertionError: add returned 0\nTraceback (most recent call last):",
    }
    code, err = _finish(
        packet,
        [(_answer([confirmed, unrelated]), _result(scratch, changes))],
        home, _exec_runner(), ask=_ask(consequence_status="error"),
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    stored = {
        item["statement"]: item
        for item in run["findings"]
        if item["source"]["kind"] == "llm"
    }
    assert stored["The add function returns 0."]["evidence"] == "reproduced"
    assert stored["A missing module is not that failure."]["evidence"] == "traced"


def test_prepare_diff_error_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, base, head = _repo(tmp_path, function=False)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    real = C.review_diff.read
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise C.review_diff.ReviewDiffError("diff failed")
        return real(*args, **kwargs)

    monkeypatch.setattr(C.review_diff, "read", flaky)
    code, err = _prepare(repo, base, head, profile, builder, out, home, _Runner(), start=4)
    assert code == 2
    assert "diff failed" in err
    assert not out.exists()
    assert calls["n"] >= 2


def test_no_reviewer_session_covers_every_argument_vector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned: list[list[str]] = []
    real_popen = subprocess.Popen

    def recording_popen(args: Any, *rest: Any, **kwargs: Any) -> Any:
        argv = list(args) if isinstance(args, (list, tuple)) else [str(args)]
        spawned.append([str(part) for part in argv])
        return real_popen(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording_popen)

    def wrap_exec(name: str) -> None:
        original = getattr(os, name, None)
        if not callable(original):
            return

        def wrapped(file: Any, *rest: Any, **kwargs: Any) -> Any:
            spawned.append([str(file)])
            return original(file, *rest, **kwargs)

        monkeypatch.setattr(os, name, wrapped)

    for name in ("execv", "execve", "execvp", "execvpe", "posix_spawn", "posix_spawnp"):
        wrap_exec(name)
    repo, base, head = _repo(tmp_path, function=False)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    runner = _Runner()
    code, err = _prepare(repo, base, head, profile, builder, out, home, runner, start=4)
    assert code == 0, err
    scratch, changes = _scratch(tmp_path, with_test=True)
    pair = (_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))
    matched = _Confine(1, _CAPTURED)
    passed = _Confine(0, "passed\n")
    code, err = _finish(out, [pair], home, runner, ask=_ask(), confine=matched)
    assert code == 0, err
    other = tmp_path / "final-packet"
    code, err = _prepare(repo, base, head, profile, builder, other, home, runner, start=4)
    assert code == 0, err
    code, err = _finish(
        other, [pair], home, runner, ask=_ask(),
        confine=passed, final=True, directory=tmp_path / "final-answers",
    )
    assert code == 0, err
    names = {Path(call[0]).name for call in runner.calls}
    assert names <= _ALLOWED
    assert spawned
    for call in [*runner.calls, *spawned, *matched.calls, *passed.calls]:
        assert Path(call[0]).name in _ALLOWED
        assert Path(call[0]).name not in {"claude", "codex", "launcher.py"}
        assert not str(call[0]).endswith("launcher.py")


# --- usage and reviewers -----------------------------------------------------------------------


def test_usage_once_writes_role_vendor_model_and_effort(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    store = _store(tmp_path)
    first_scratch, first_changes = _scratch(tmp_path / "a", with_test=False)
    second_scratch, second_changes = _scratch(tmp_path / "b", with_test=False)
    code, err = _finish(
        packet,
        [
            (_answer([]), _result(first_scratch, first_changes, session="s1")),
            (_answer([]), _result(second_scratch, second_changes, session="s2")),
        ],
        home, runner, ask=_ask(), store=store, issue=160,
    )
    assert code == 0, err
    record = RR.load(store, 160)
    assert record is not None
    entries = record.units[0]["usage"]["entries"]
    assert [entry["role"] for entry in entries] == ["targeted-reviewer", "external-reviewer"]
    assert [entry["session_id"] for entry in entries] == ["s1", "s2"]
    for entry in entries:
        assert entry["vendor"] == "claude"
        assert entry["model"] == "opus"
        assert entry["effort"] == "high"
        assert entry["counts"]["uncached_input"] == 10
    run = _read(packet / "review-run.json")
    assert run["usage"] == {"tokens_in": 26, "tokens_out": 6, "cost_usd": 1.0, "seconds": 3.0}


def test_usage_once_skips_a_mod_recorded_session(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    store = _store(tmp_path)
    record = RR.load(store, 160)
    assert record is not None
    seeded = RR.add_usage(
        record, "U1", session_id="s1/agent9", role="targeted-reviewer", vendor="claude",
        model="opus", effort="high", counts={"uncached_input": 7},
    )
    RR.save(store, seeded)
    scratch, changes = _scratch(tmp_path, with_test=False)
    code, err = _finish(
        packet, [(_answer([]), _result(scratch, changes, session="s1", agent="agent9"))],
        home, runner, ask=_ask(), store=store, issue=160,
    )
    assert code == 0, err
    entries = RR.load(store, 160).units[0]["usage"]["entries"]
    assert len(entries) == 1
    assert entries[0]["session_id"] == "s1/agent9"
    assert entries[0]["counts"]["uncached_input"] == 7
    assert entries[0]["additions"] == 1


def test_usage_once_repeat_finish_adds_nothing(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    store = _store(tmp_path)
    scratch, changes = _scratch(tmp_path, with_test=False)
    pair = [(_answer([]), _result(scratch, changes, session="s1"))]
    code, err = _finish(packet, pair, home, runner, ask=_ask(), store=store, issue=160)
    assert code == 0, err
    code, err = _finish(
        packet, pair, home, runner, ask=_ask(), store=store, issue=160,
        directory=tmp_path / "repeat",
    )
    assert code == 0, err
    entries = RR.load(store, 160).units[0]["usage"]["entries"]
    assert len(entries) == 1
    assert entries[0]["additions"] == 1
    assert entries[0]["counts"]["uncached_input"] == 10


def test_usage_once_without_an_issue_does_not_touch_the_store(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    empty = tmp_path / "empty-store"
    empty.mkdir()
    scratch, changes = _scratch(tmp_path, with_test=False)
    code, err = _finish(
        packet, [(_answer([]), _result(scratch, changes))], home, runner, ask=_ask(),
        extra=["--store-root", str(empty)],
    )
    assert code == 0, err
    assert list(empty.iterdir()) == []
    store = _store(tmp_path / "two", units=[
        {"id": "U1", "usage": {"entries": []}},
        {"id": "U2", "usage": {"entries": []}},
    ])
    other = tmp_path / "other-packet"
    repo, base, head = _repo(tmp_path / "other", function=False)
    profile = _profile(tmp_path / "other-outside")
    builder = _builder(tmp_path / "other-builder.json")
    code, err = _prepare(repo, base, head, profile, builder, other, home, _Runner(), start=4)
    assert code == 0, err
    before = list(RR.load(store, 160).review_cycles)
    code, err = _finish(
        other, [(_answer([]), _result(scratch, changes))], home, _Runner(), ask=_ask(),
        store=store, issue=160, directory=tmp_path / "two-answers",
    )
    assert code == 2
    assert not (other / "review-run.json").exists()
    assert list(RR.load(store, 160).review_cycles) == before


def test_usage_once_missing_record_writes_nothing(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=False)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    empty = tmp_path / "no-record"
    empty.mkdir()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), start=4, store=empty, issue=160,
    )
    assert code == 2
    assert not out.exists()
    packet_home = tmp_path / "made"
    packet = packet_home / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, packet, home, _Runner(), start=4,
    )
    assert code == 0, err
    scratch, changes = _scratch(tmp_path, with_test=False)
    code, err = _finish(
        packet, [(_answer([]), _result(scratch, changes))], home, _Runner(), ask=_ask(),
        store=empty, issue=404,
    )
    assert code == 2
    assert not (packet / "review-run.json").exists()


def _reviewer_object(fingerprint: str) -> dict[str, Any]:
    return {
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "prompt_sha256": _HEX_A,
        "configuration_fingerprint": fingerprint,
        "second": None,
        "cleared_components": [],
    }


def test_reviewer_configuration_comparison_reads_the_fingerprint(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    home = tmp_path / "home"
    calibration = _recorded_calibration(
        tmp_path / "calibration.json", configuration=_reviewer_object(_HEX_A)
    )
    # The committed file is no-run. This copy only changes the configuration object.
    data = json.loads((REFERENCES / "review-calibration.json").read_text(encoding="utf-8"))
    data["reviewer_configuration"] = _reviewer_object(_HEX_A)
    calibration.write_text(json.dumps(data), encoding="utf-8")
    scratch, changes = _scratch(tmp_path, with_test=False)
    differing = _result(scratch, changes, fingerprint=_HEX_B, prompt=_HEX_B)
    code, err = _finish(
        packet, [(_answer([]), differing)], home, runner, ask=_ask(),
        extra=["--calibration", str(calibration)],
    )
    assert code == 0, err
    noted = _read(packet / "review-run.json")["reviewers"][0]
    assert noted["prompt_sha256"] == _HEX_B
    assert noted["configuration_sha256"] == _HEX_B
    assert noted["note"] == "reviewer-configuration"
    other = tmp_path / "match"
    repo, base, head = _repo(tmp_path / "match-repo", function=False)
    code, err = _prepare(
        repo, base, head, _profile(tmp_path / "match-outside"),
        _builder(tmp_path / "match-builder.json"), other, home, _Runner(), start=4,
    )
    assert code == 0, err
    matching = _result(scratch, changes, fingerprint=_HEX_A, prompt=_HEX_A)
    code, err = _finish(
        other, [(_answer([]), matching)], home, _Runner(), ask=_ask(),
        extra=["--calibration", str(calibration)], directory=tmp_path / "match-answers",
    )
    assert code == 0, err
    same = _read(other / "review-run.json")["reviewers"][0]
    assert same["configuration_sha256"] == _HEX_A
    assert same["note"] is None
    _null_repo, null_packet, null_runner = _line_packet(tmp_path / "null")
    null_calibration = tmp_path / "null-calibration.json"
    null_data = json.loads((REFERENCES / "review-calibration.json").read_text(encoding="utf-8"))
    null_data["reviewer_configuration"] = None
    null_calibration.write_text(json.dumps(null_data), encoding="utf-8")
    null_scratch, null_changes = _scratch(tmp_path / "null", with_test=False)
    code, err = _finish(
        null_packet,
        [(_answer([]), _result(null_scratch, null_changes, fingerprint=_HEX_A))],
        tmp_path / "null" / "home",
        null_runner,
        ask=_ask(),
        extra=["--calibration", str(null_calibration)],
    )
    assert code == 0, err
    unrecorded = _read(null_packet / "review-run.json")["reviewers"][0]
    assert unrecorded["note"] == "reviewer-configuration"


def test_report_only_allows_merge_and_may_block_refuses(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=False)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    report = tmp_path / "report"
    code, err = _prepare(repo, base, head, profile, builder, report, home, _Runner(), start=4)
    assert code == 0, err
    grades = _read(report / "grades.json")
    finding_id = _read(report / "findings.json")[0]["id"]
    assert grades["merge"]["allowed"] is True
    assert finding_id in grades["merge"]["report_only_blocks"]
    recorded = _recorded_calibration(tmp_path / "recorded.json")
    blocked = tmp_path / "blocked"
    code, err = _prepare(
        repo, base, head, profile, builder, blocked, home, _Runner(), start=4, calibration=recorded,
    )
    assert code == 0, err
    may_block = _read(blocked / "may-block.json")
    assert may_block["security"]["python"]["blocks"] is True
    assert may_block["security"]["python"]["reason"].startswith("yes")
    blocked_grades = _read(blocked / "grades.json")
    blocked_id = _read(blocked / "findings.json")[0]["id"]
    assert blocked_grades["merge"]["allowed"] is False
    assert blocked_id in blocked_grades["merge"]["blocking"]


def test_command_doc_names_inputs_outputs_exit_codes_and_both_callers() -> None:
    text = (REFERENCES / "review-command.md").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "## inputs" in lowered
    assert "## outputs" in lowered
    assert "## exit codes" in lowered
    assert "prepare" in text
    assert "finish" in text
    assert "/code-review" in text
    assert "corpus harness" in text


# --- posting to Langfuse (issue 166) ------------------------------------------------------------

_LF_ENV = {
    "SAGA_LANGFUSE_PUBLIC_KEY": "pk-lf-SENTINEL-public",
    "SAGA_LANGFUSE_SECRET_KEY": "sk-lf-SENTINEL-secret",
    "SAGA_LANGFUSE_HOST": "https://langfuse.example.test",
}


class _LfResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def read(self) -> bytes:
        return b"{}"

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _LfOpener:
    def __init__(self, result: Any = None) -> None:
        self.result = result if result is not None else _LfResponse()
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _finished(
    tmp: Path, opener: Any, monkeypatch: pytest.MonkeyPatch, *, issue: bool = True,
) -> tuple[int, str, Path, Path | None, Path]:
    for name, value in _LF_ENV.items():
        monkeypatch.setenv(name, value)
    repo, base, head = _repo(tmp, function=True)
    profile = _profile(tmp / "outside")
    builder = _builder(tmp / "builder.json")
    bank = _bank(tmp / "bank.json")
    home = tmp / "home"
    home.mkdir()
    out = tmp / "packet"
    code, err = _prepare(repo, base, head, profile, builder, out, home, _Runner(), start=2,
                         ask=_ask(), bank=bank)
    assert code == 0, err
    where = _read(out / "where-to-look.json")
    cleared = _answer([], items=[{
        "index": 0, "file": where[0]["location"]["file"],
        "answer": {"kind": "cleared", "reason": "The stub line is the only finding here."},
    }])
    scratch, changes = _scratch(tmp, with_test=False)
    store = _store(tmp) if issue else None
    code, err = _finish(out, [(cleared, _result(scratch, changes))], home, _Runner(), ask=_ask(),
                        store=store, issue=160 if issue else None, trace_opener=opener)
    return code, err, out, store, home


def _stored_record(store: Path | None) -> Any:
    if store is None:
        return None
    return RR.to_dict(RR.load(store, 160, warn=None))


def test_finish_langfuse_failure_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good_code, _, good_out, good_store, _ = _finished(tmp_path / "ok", _LfOpener(), monkeypatch)
    assert good_code == 0
    good_run = _read(good_out / "review-run.json")
    good_record = _stored_record(good_store)
    cases = [
        ("unreachable", _LfOpener(urllib.error.URLError("down")), True),
        ("server-error", _LfOpener(_LfResponse(500)), True),
    ]
    for label, opener, queues in cases:
        code, err, out, store, home = _finished(tmp_path / label, opener, monkeypatch)
        assert code == good_code
        run = _read(out / "review-run.json")
        assert {k: v for k, v in run.items() if k not in ("base", "head", "repo")} == {
            k: v for k, v in good_run.items() if k not in ("base", "head", "repo")}
        record = _stored_record(store)
        assert len(record["review_cycles"]) == len(good_record["review_cycles"])
        assert [line for line in err.splitlines() if line.startswith("langfuse:")]
        if queues:
            assert list((home / ".saga" / "langfuse-queue").glob("*.json"))
        assert "SENTINEL" not in err and "langfuse.example.test" not in err

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("posting bug")

    trace = sys.modules.get("review_trace") or importlib.import_module("review_trace")
    monkeypatch.setattr(trace, "post_review_run", broken)
    code, err, out, _, _ = _finished(tmp_path / "bug", _LfOpener(), monkeypatch)
    assert code == good_code
    assert (out / "review-run.json").is_file()
    assert "langfuse: not posted (RuntimeError)" in err


def test_finish_posts_one_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _LfOpener()
    code, err, out, _, _ = _finished(tmp_path, opener, monkeypatch)
    assert code == 0, err
    run = _read(out / "review-run.json")
    traces = [r for r in opener.requests if r.full_url.endswith("/api/public/otel/v1/traces")]
    scores = [r for r in opener.requests if r.full_url.endswith("/api/public/scores")]
    assert len(traces) == 1
    body = json.loads(traces[0].data.decode())
    spans = body["resourceSpans"][0]["scopeSpans"][0]["spans"]
    root = next(span for span in spans if span["name"] == "review-run")
    attrs = {a["key"]: next(iter(a["value"].values())) for a in root["attributes"]}
    assert attrs["langfuse.trace.metadata.head"] == run["head"]
    assert str(tmp_path) not in traces[0].data.decode()
    assert any(span["name"].startswith("llm:") for span in spans)
    assert [json.loads(r.data.decode())["name"] for r in scores] == ["round"]
    assert "langfuse: sent" in err


def test_finish_without_store_posts_round_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _LfOpener()
    code, err, _, _, _ = _finished(tmp_path, opener, monkeypatch, issue=False)
    assert code == 0, err
    [trace] = [r for r in opener.requests if r.full_url.endswith("/otel/v1/traces")]
    assert '"no-store"' in trace.data.decode()


def _package_with_manifests(root: Path, **manifests: str | None) -> Path:
    """A package directory whose ``scripts/`` the command believes it runs from."""
    (root / "scripts").mkdir(parents=True)
    for relative, text in manifests.items():
        if text is not None:
            target = root / relative.replace("__", "/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    return root / "scripts"


@pytest.mark.parametrize(
    ("manifests", "expected"),
    [
        ({"plugin.json": '{"version": "9.1.0"}'}, "9.1.0"),
        (
            {"plugin.json": '{"version": "9.1.0"}', ".claude-plugin__plugin.json": '{"version": "8"}'},
            "9.1.0",
        ),
        ({".claude-plugin__plugin.json": '{"version": "9.2.0"}'}, "9.2.0"),
        ({"plugin.json": "{ not json", ".claude-plugin__plugin.json": '{"version": "9.3.0"}'}, "9.3.0"),
        ({"plugin.json": '{"version": " "}', ".claude-plugin__plugin.json": '{"version": "9.4.0"}'}, "9.4.0"),
        ({}, "not-recorded"),
        ({"plugin.json": "[]", ".claude-plugin__plugin.json": '{"name": "saga"}'}, "not-recorded"),
    ],
)
def test_saga_version_falls_back_to_the_claude_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifests: dict[str, str], expected: str
) -> None:
    """A Muse-staged copy has no root ``plugin.json``; the version must still be read."""
    monkeypatch.setattr(C, "_SCRIPTS_DIR", _package_with_manifests(tmp_path, **manifests))
    assert C._saga_version() == expected


_CLIPPY_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "review_tools" / "clippy.jsonl"
)


def _rust_change(tmp: Path) -> tuple[Path, str, str]:
    """A crate whose head adds clippy findings on lines 2, 6 and 7 of src/main.rs."""
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8",
    )
    (repo / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\n', encoding="utf-8",
    )
    lines = [
        "fn add(a: i32, b: i32) -> i32 {\n", "    a + b\n", "}\n", "\n", "fn main() {\n",
        "    let _used = 1;\n", "    let _zero = 1.0;\n", '    println!("{}", add(1, 2));\n', "}\n",
    ]
    (repo / "src" / "main.rs").write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[1] = "    return a + b;\n"
    lines[5] = "    let unused_var = 2;\n"
    lines[6] = "    let _zero = 0.0 / 0.0;\n"
    (repo / "src" / "main.rs").write_text("".join(lines), encoding="utf-8")
    return repo, base, _commit(repo, "head")


class _ClippyRunner(_Runner):
    """git for real; cargo-clippy prints the fixture as a real run would, in a chosen order."""

    def __init__(self, *, reverse: bool) -> None:
        super().__init__()
        self.reverse = reverse

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        if Path(argv[0]).name != "cargo-clippy":
            return super().__call__(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)
        self.calls.append(list(argv))
        if "--version" in argv:
            return T.ProcessResult(0, "clippy 0.1.98 (abc 2026-09-01)\n")
        text = _CLIPPY_FIXTURE.read_text(encoding="utf-8").replace(
            "/private/tmp/rust-probe", Path(cwd).as_posix(),
        )
        lines = text.splitlines(keepends=True)
        return T.ProcessResult(101, "".join(reversed(lines) if self.reverse else lines))


def _packet_bytes(packet: Path) -> dict[str, bytes]:
    return {
        path.relative_to(packet).as_posix(): path.read_bytes()
        for path in sorted(packet.rglob("*")) if path.is_file()
    }


def _clippy_adapter() -> Any:
    import importlib  # noqa: PLC0415

    rust = importlib.import_module("review_adapters_rust")
    return next(item for item in rust.ADAPTERS if item.id == "clippy")


def test_prepare_twice_on_a_rust_change_writes_identical_packets(tmp_path: Path) -> None:
    """Issue 244: other scratch folders and another build order, the same packet bytes."""
    repo, base, head = _rust_change(tmp_path)
    builder = _builder(tmp_path / "builder.json")
    (tmp_path / "home").mkdir()
    packets = []
    for reverse in (False, True):
        out = tmp_path / f"packet-{reverse}"
        code, err = _main(
            [
                "prepare", "--repo", str(repo), "--base", base, "--head", head,
                "--profile", str(_profile(tmp_path / "profile")), "--builder-record", str(builder),
                "--out", str(out), "--home", str(tmp_path / "home"),
                "--bank", str(tmp_path / "no-bank.json"),
            ],
            adapters=[_clippy_adapter()], runner=_ClippyRunner(reverse=reverse),
        )
        assert code == 0, err
        packets.append(out)
    first, second = (_packet_bytes(packet) for packet in packets)
    assert sorted(first) == sorted(second)
    assert {name: data for name, data in first.items()} == second
    refs = {finding["rule"]["ref"] for finding in _read(packets[0] / "findings.json")}
    assert {"clippy::eq_op", "clippy::needless_return", "unused_variables"} <= refs


@pytest.mark.skipif(shutil.which("cargo-clippy") is None, reason="cargo-clippy is not installed")
def test_live_prepare_twice_with_clippy_writes_identical_packets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same, with the real clippy and its real scratch-folder paths."""
    # The autouse fixture swaps HOME; rustup still needs the operator's toolchains.
    if "RUSTUP_HOME" not in os.environ:
        monkeypatch.setenv("RUSTUP_HOME", str(_OPERATOR_HOME / ".rustup"))
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8",
    )
    (repo / "src" / "main.rs").write_text("fn main() {\n    println!(\"clean\");\n}\n", encoding="utf-8")
    subprocess.run(
        ["cargo", "generate-lockfile", "--offline"], cwd=repo, check=True,
        capture_output=True, text=True, timeout=120,
    )
    base = _commit(repo, "base")
    (repo / "src" / "main.rs").write_text(
        "fn add(a: i32, b: i32) -> i32 {\n    return a + b;\n}\n\n"
        "fn main() {\n    println!(\"{}\", add(1, 2));\n}\n",
        encoding="utf-8",
    )
    head = _commit(repo, "head")
    builder = _builder(tmp_path / "builder.json")
    (tmp_path / "home").mkdir()
    packets = []
    for attempt in (1, 2):
        out = tmp_path / f"packet-{attempt}"
        code, err = _main(
            [
                "prepare", "--repo", str(repo), "--base", base, "--head", head,
                "--profile", str(_profile(tmp_path / "profile")), "--builder-record", str(builder),
                "--out", str(out), "--home", str(tmp_path / "home"),
                "--bank", str(tmp_path / "no-bank.json"),
            ],
            adapters=[_clippy_adapter()],
        )
        assert code == 0, err
        packets.append(out)
    assert _packet_bytes(packets[0]) == _packet_bytes(packets[1])
    refs = {finding["rule"]["ref"] for finding in _read(packets[0] / "findings.json")}
    assert "clippy::needless_return" in refs


def _rename_change(tmp: Path) -> tuple[Path, str, str]:
    """A Python repository whose head renames a function but leaves a caller in src/caller.py."""
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def old_name():\n    return 1\n", encoding="utf-8")
    (repo / "src" / "caller.py").write_text(
        "import app\n\nvalue = app.old_name()\n", encoding="utf-8",
    )
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("def new_name():\n    return 1\n", encoding="utf-8")
    return repo, base, _commit(repo, "head")


class _BuildOutputRunner(_Runner):
    """A tool that writes different files into the copy on every run, as clippy and cargo-mutants do."""

    def __init__(self) -> None:
        super().__init__()
        self.runs = 0

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        if Path(argv[0]).name == "stub" and "scan" in argv:
            self.runs += 1
            for folder in ("target/debug", "mutants.out"):
                (Path(cwd) / folder).mkdir(parents=True, exist_ok=True)
                (Path(cwd) / folder / f"build-{self.runs}-{os.getpid()}.rs").write_text(
                    f"// run {self.runs}\nfn caller() {{ old_name(); }}\n", encoding="utf-8",
                )
            return T.ProcessResult(0, "scan\n")
        if Path(argv[0]).name == "stub":
            return super().__call__(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)
        proc = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=timeout,
        )
        return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)


def test_prepare_twice_with_a_tool_writing_build_output_writes_identical_packets(
    tmp_path: Path,
) -> None:
    """Issue 252: files a tool leaves in the copy never reach the checks, so the packets agree."""
    import importlib  # noqa: PLC0415

    checks = importlib.import_module("review_checks")
    names = next(item for item in checks.ADAPTERS if item.id == "changed-names")
    repo, base, head = _rename_change(tmp_path)
    builder = _builder(tmp_path / "builder.json")
    (tmp_path / "home").mkdir()
    runner = _BuildOutputRunner()
    packets = []
    for number in (1, 2):
        out = tmp_path / f"packet-{number}"
        code, err = _main(
            [
                "prepare", "--repo", str(repo), "--base", base, "--head", head,
                "--profile", str(_profile(tmp_path / "profile")), "--builder-record", str(builder),
                "--out", str(out), "--home", str(tmp_path / "home"),
                "--bank", str(tmp_path / "no-bank.json"),
            ],
            adapters=[_adapter(start=1, hit=False), names], runner=runner,
        )
        assert code == 0, err
        packets.append(out)
    assert runner.runs == 2
    first, second = (_packet_bytes(packet) for packet in packets)
    assert first == second
    mentions = [
        finding for finding in _read(packets[0] / "findings.json")
        if finding["rule"]["ref"] == "old_name"
    ]
    assert [finding["location"]["file"] for finding in mentions] == ["src/caller.py"]


# --- issue 262: dependencies for an offline reviewer and re-run ---------------------------------


_DEPS = C.review_dependencies
_CRATES_IO = "registry+https://github.com/rust-lang/crates.io-index"


class _VendorRunner(_Runner):
    """git for real; ``cargo vendor`` records what it saw and writes one crate."""

    def __init__(self) -> None:
        super().__init__()
        self.vendor: list[dict[str, Any]] = []

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        if "--" in argv and argv[:2] == [sys.executable, "-I"]:
            argv = argv[argv.index("--") + 1:]
        if argv[:2] != ["cargo", "vendor"]:
            return super().__call__(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)
        self.calls.append(list(argv))
        self.vendor.append({"cwd": Path(cwd), "env": dict(env),
                            "names": {p.name for p in Path(cwd).iterdir()}})
        crate = Path(argv[-1]) / "itoa"
        crate.mkdir(parents=True)
        (crate / "Cargo.toml").write_text('[package]\nname = "itoa"\n', encoding="utf-8")
        return T.ProcessResult(0, "")


def _rust_dependency_change(tmp: Path) -> tuple[Path, str, str]:
    """A crate with one crates.io dependency, a build script and its own cargo configuration."""
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / ".cargo").mkdir()
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        '\n[dependencies]\nitoa = "1"\n', encoding="utf-8",
    )
    (repo / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\ndependencies = ["itoa"]\n'
        f'\n[[package]]\nname = "itoa"\nversion = "1.0.15"\nsource = "{_CRATES_IO}"\n'
        f'checksum = "{"ab" * 32}"\n', encoding="utf-8",
    )
    (repo / ".cargo" / "config.toml").write_text(
        '[source.crates-io]\nreplace-with = "elsewhere"\n', encoding="utf-8",
    )
    (repo / "rust-toolchain.toml").write_text('[toolchain]\npath = "./tool"\n', encoding="utf-8")
    (repo / "build.rs").write_text("fn main() {}\n", encoding="utf-8")
    (repo / "src" / "lib.rs").write_text("pub fn two() -> i32 { 2 }\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "lib.rs").write_text("pub fn two() -> i32 { 3 }\n", encoding="utf-8")
    return repo, base, _commit(repo, "head")


def test_prepare_vendors_a_rust_head_into_the_packet_outside_the_repository(
    tmp_path: Path,
) -> None:
    repo, base, head = _rust_dependency_change(tmp_path)
    (tmp_path / "home").mkdir()
    runner = _VendorRunner()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, _profile(tmp_path / "outside"), _builder(tmp_path / "builder.json"),
        out, tmp_path / "home", runner, start=1,
    )
    assert code == 0, err
    record = _read(out / "dependencies.json")
    assert record == {
        "schema": _DEPS.SCHEMA,
        "rust": {"state": "fetched", "directory": "dependencies/rust", "crates": 1},
    }
    vendor = _DEPS.rust_vendor(out)
    assert vendor == (out / "dependencies" / "rust").resolve()
    assert not vendor.is_relative_to(repo.resolve())
    seen = runner.vendor[0]
    assert ".cargo" not in seen["names"] and "rust-toolchain.toml" not in seen["names"]
    assert {"Cargo.toml", "Cargo.lock", "build.rs", "src"} <= seen["names"]
    assert Path(seen["env"]["CARGO_HOME"]).name == "cargo-home"
    assert not Path(seen["env"]["CARGO_HOME"]).exists()
    assert not (out / "dependencies" / "rust" / "target").exists()


def test_prepare_on_a_change_without_cargo_writes_only_the_schema(tmp_path: Path) -> None:
    _repo_path, packet, runner = _line_packet(tmp_path)
    assert _read(packet / "dependencies.json") == {"schema": _DEPS.SCHEMA}
    assert not (packet / "dependencies").exists()
    assert not any(call[:2] == ["cargo", "vendor"] for call in runner.calls)


class _OfflineConfine(_Confine):
    """Records the re-run environment and the cargo configuration it points at."""

    def __init__(self) -> None:
        super().__init__(1, _CAPTURED)
        self.envs: list[dict[str, str]] = []
        self.configs: list[str] = []

    def __call__(self, argv: list[str], _cwd: Path, env: dict[str, str], _scratch: Path) -> Any:
        self.envs.append(dict(env))
        home = env.get("CARGO_HOME")
        if home:
            self.configs.append((Path(home) / "config.toml").read_text(encoding="utf-8"))
        return super().__call__(argv, _cwd, env, _scratch)


def _with_vendor(packet: Path) -> Path:
    vendor = packet / "dependencies" / "rust"
    vendor.mkdir(parents=True)
    _dump(packet / "dependencies.json", {
        "schema": _DEPS.SCHEMA,
        "rust": {"state": "fetched", "directory": "dependencies/rust", "crates": 0},
    })
    return vendor.resolve()


def test_finish_reruns_offline_against_the_packet_s_vendored_crates(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    vendor = _with_vendor(packet)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    confine = _OfflineConfine()
    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    env = confine.envs[0]
    assert env["CARGO_NET_OFFLINE"] == "true"
    assert Path(env["CARGO_HOME"]).name.startswith("saga-review-cargo-home-")
    assert not Path(env["CARGO_HOME"]).exists(), "the re-run's cargo home is removed afterwards"
    assert f'directory = {json.dumps(str(vendor))}' in confine.configs[0]
    assert 'replace-with = "saga-vendored-' in confine.configs[0]
    if shutil.which("cargo"):
        shim = Path(env["CARGO_HOME"]) / "bin" / "cargo"
        assert env["PATH"].split(os.pathsep)[0] == str(shim.parent)


def test_the_rerun_s_offline_cargo_carries_rustup_s_home_and_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """finish's re-run HOME is the scratch copy, so a rustup proxy needs RUSTUP_HOME (CI)."""
    monkeypatch.delenv("RUSTUP_HOME", raising=False)
    monkeypatch.delenv("RUSTUP_TOOLCHAIN", raising=False)
    packet = _inert_vendored_packet(tmp_path)
    with C._offline_dependencies(packet) as offline:
        assert offline is not None
        assert offline.env["RUSTUP_HOME"] == str(Path.home() / ".rustup")
        if shutil.which("cargo"):
            assert offline.toolchain[0] == Path(str(shutil.which("cargo"))).absolute().parent


def test_a_cargo_rerun_without_vendored_crates_still_gets_rustup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "operator"
    (home / ".cargo" / "bin").mkdir(parents=True)
    proxy = home / ".cargo" / "bin" / "cargo"
    proxy.write_text("#!/bin/sh\nexit 0\n")
    proxy.chmod(0o755)
    (home / ".rustup" / "toolchains").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{proxy.parent}{os.pathsep}/usr/bin:/bin")
    monkeypatch.delenv("RUSTUP_HOME", raising=False)
    monkeypatch.setattr(C, "platform_helper", lambda: "sandbox-exec")
    _repo_path, packet, runner = _repro_packet(tmp_path)
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    seen: list[tuple[list[str], dict[str, str]]] = []

    def record(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
               shell: bool) -> Any:
        if argv[0] == "/usr/bin/sandbox-exec":
            seen.append((list(argv), dict(env)))
            return T.ProcessResult(1, _CAPTURED)
        return runner(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)

    finding = _finding("A retry returns the new number.")
    finding["proof"]["command"] = "cargo test --offline"
    code, err = _finish(packet, [(_answer([finding]), _result(scratch, changes))], home, record,
                        ask=_ask(consequence_status="error"))
    assert code == 0, err
    argv, env = seen[0]
    assert env["RUSTUP_HOME"] == str(home / ".rustup") and env["HOME"] != str(home)
    profile = argv[2]
    for path in (proxy.parent, home / ".rustup" / "toolchains"):
        assert f'(allow file-map-executable (subpath "{path.resolve()}"))' in profile
    assert f'(subpath "{(home / ".cargo").resolve()}")' not in profile


def test_a_cargo_named_by_a_folder_in_the_command_never_opens_that_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer writes the command, so the toolchain is looked up on the operator's PATH."""
    home = tmp_path / "operator"
    (home / ".ssh").mkdir(parents=True)
    planted = home / ".ssh" / "cargo"
    planted.write_text("#!/bin/sh\nexit 0\n")
    planted.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(C, "platform_helper", lambda: "sandbox-exec")
    _repo_path, packet, runner = _repro_packet(tmp_path)
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    profiles: list[str] = []

    def record(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
               shell: bool) -> Any:
        if argv[0] == "/usr/bin/sandbox-exec":
            profiles.append(argv[2])
            return T.ProcessResult(1, _CAPTURED)
        return runner(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)

    finding = _finding("A retry returns the new number.")
    finding["proof"]["command"] = f"{planted} test --offline"
    code, err = _finish(packet, [(_answer([finding]), _result(scratch, changes))], home, record,
                        ask=_ask(consequence_status="error"))
    assert code == 0, err
    lines = profiles[0].splitlines()
    deny = lines.index(f'(deny file-read* (subpath "{home.resolve()}"))')
    ssh = str((home / ".ssh").resolve())
    assert not any(ssh in line for line in lines[deny:]), "nothing re-opens it after the deny"


def test_a_cargo_rerun_goes_through_the_cargo_home_s_shim(tmp_path: Path) -> None:
    shim = tmp_path / "cargo-home" / "bin" / "cargo"
    offline = C.Offline(env={}, reads=(), cargo=shim)
    assert offline.argv(["cargo", "test", "-q"]) == [str(shim), "test", "-q"]
    assert offline.argv(["/opt/example/bin/cargo", "test"]) == [str(shim), "test"]
    assert offline.argv(["python3", "-m", "pytest"]) == ["python3", "-m", "pytest"]
    assert C.Offline(env={}, reads=()).argv(["cargo", "test"]) == ["cargo", "test"]


def test_finish_without_vendored_crates_leaves_the_rerun_environment_alone(
    tmp_path: Path,
) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    confine = _OfflineConfine()
    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    assert "CARGO_HOME" not in confine.envs[0] and "CARGO_NET_OFFLINE" not in confine.envs[0]


def test_the_confined_rerun_reads_the_extra_paths_and_never_writes_them(tmp_path: Path) -> None:
    scratch, extra = tmp_path / "scratch", tmp_path / "vendor"
    scratch.mkdir()
    extra.mkdir()
    profile = C._seatbelt(scratch, ["cargo"], [extra])
    lines = profile.splitlines()
    allow = f'(allow file-read* (subpath "{extra.resolve()}"))'
    assert allow in lines
    assert lines.index(allow) > lines.index(f'(deny file-read* (subpath "{Path.home().resolve()}"))')
    assert not any("file-write" in line and str(extra.resolve()) in line for line in lines)
    assert "(deny network*)" in lines
    command = C._bwrap(scratch, ["cargo"], [extra])
    index = command.index(str(extra.resolve()))
    assert command[index - 1] == "--ro-bind" and command[index + 1] == str(extra.resolve())
    assert "--unshare-net" in command
    assert not any(part == "--bind" and command[i + 1] == str(extra.resolve())
                   for i, part in enumerate(command[:-1]))


def _inert_vendored_packet(tmp: Path) -> Path:
    """A packet holding one vendored crate written by hand, so no network is needed."""
    packet = tmp / "packet"
    crate = packet / "dependencies" / "rust" / "inertdep"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        '[package]\nname = "inertdep"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8",
    )
    (crate / "src" / "lib.rs").write_text("pub fn two() -> i32 { 2 }\n", encoding="utf-8")
    (crate / ".cargo-checksum.json").write_text(
        json.dumps({"files": {}, "package": "ab" * 32}), encoding="utf-8",
    )
    _dump(packet / "dependencies.json", {
        "schema": _DEPS.SCHEMA,
        "rust": {"state": "fetched", "directory": "dependencies/rust", "crates": 1},
    })
    return packet


@pytest.mark.skipif(
    shutil.which("cargo") is None or C.platform_helper() is None,
    reason="needs cargo and the platform's confinement helper",
)
@pytest.mark.usefixtures("operator_rustup")
def test_live_the_confined_rerun_builds_offline_from_the_vendored_crates(tmp_path: Path) -> None:
    packet = _inert_vendored_packet(tmp_path)
    scratch = tmp_path / "scratch"
    (scratch / "src").mkdir(parents=True)
    (scratch / "tmp").mkdir()
    (scratch / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        '\n[dependencies]\ninertdep = "0.1"\n', encoding="utf-8",
    )
    (scratch / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\n'
        'dependencies = ["inertdep"]\n'
        f'\n[[package]]\nname = "inertdep"\nversion = "0.1.0"\nsource = "{_CRATES_IO}"\n'
        f'checksum = "{"ab" * 32}"\n', encoding="utf-8",
    )
    (scratch / "src" / "lib.rs").write_text(
        "#[test]\nfn uses_the_dependency() { assert_eq!(inertdep::two(), 3, \"returned 2\"); }\n",
        encoding="utf-8",
    )
    vendor = packet / "dependencies" / "rust"
    with C._offline_dependencies(packet) as offline:
        assert offline is not None
        env = {**C.child_environment(scratch), **offline.env}
        ran = C.run_confined(
            ["cargo", "test", "--offline"], scratch, env, scratch,
            runner=T.subprocess_runner, timeout=300, reads=offline.reads,
            toolchain=offline.toolchain,
        )
        wrote = C.run_confined(
            ["/usr/bin/touch", str(vendor / "planted")], scratch, env, scratch,
            runner=T.subprocess_runner, timeout=30, reads=offline.reads,
            toolchain=offline.toolchain,
        )
    output = ran.stdout + ran.stderr
    assert ran.code == 101, output
    assert "returned 2" in output, "the test compiled against the vendored crate and failed"
    assert wrote.code != 0 and not (vendor / "planted").exists()


def _hostile_scratch(tmp_path: Path) -> Path:
    """A scratch copy whose ``.cargo/config.toml`` replaces crates.io with its own crate."""
    scratch = tmp_path / "scratch"
    (scratch / "src").mkdir(parents=True)
    (scratch / "tmp").mkdir()
    (scratch / ".cargo").mkdir()
    (scratch / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        '\n[dependencies]\ninertdep = "0.1"\n', encoding="utf-8",
    )
    (scratch / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\n'
        'dependencies = ["inertdep"]\n'
        f'\n[[package]]\nname = "inertdep"\nversion = "0.1.0"\nsource = "{_CRATES_IO}"\n'
        f'checksum = "{"ab" * 32}"\n', encoding="utf-8",
    )
    (scratch / ".cargo" / "config.toml").write_text(
        '[source.crates-io]\nreplace-with = "planted"\n\n[source.planted]\ndirectory = "planted"\n',
        encoding="utf-8",
    )
    planted = scratch / "planted" / "inertdep"
    (planted / "src").mkdir(parents=True)
    (planted / "Cargo.toml").write_text(
        '[package]\nname = "inertdep"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8",
    )
    (planted / "src" / "lib.rs").write_text("pub fn two() -> i32 { 99 }\n", encoding="utf-8")
    (planted / ".cargo-checksum.json").write_text(
        json.dumps({"files": {}, "package": "ab" * 32}), encoding="utf-8",
    )
    (scratch / "src" / "lib.rs").write_text(
        "#[test]\nfn uses_the_dependency() {\n"
        "    let got = inertdep::two();\n    assert_eq!(got, 3, \"returned {got}\");\n}\n",
        encoding="utf-8",
    )
    return scratch


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo is not installed")
@pytest.mark.usefixtures("operator_rustup")
def test_live_the_rerun_s_environment_runs_the_shim_whatever_cargo_is(tmp_path: Path) -> None:
    """finish's own re-run environment, HOME the scratch copy, unconfined so CI runs it too.

    On CI cargo is a rustup proxy, which picks no toolchain under that HOME without RUSTUP_HOME.
    """
    packet = _inert_vendored_packet(tmp_path)
    scratch = _hostile_scratch(tmp_path)
    with C._offline_dependencies(packet) as offline:
        assert offline is not None
        env = {**C.child_environment(scratch), **offline.env}
        ran = subprocess.run(offline.argv(["cargo", "test", "--offline"]), cwd=scratch, env=env,
                             capture_output=True, text=True, timeout=300, check=False)
    assert "returned 2" in ran.stdout + ran.stderr, ran.stdout + ran.stderr


@pytest.mark.skipif(
    shutil.which("cargo") is None or C.platform_helper() is None,
    reason="needs cargo and the platform's confinement helper",
)
@pytest.mark.usefixtures("operator_rustup")
def test_live_a_commit_s_own_source_replacement_cannot_outrank_the_rerun_s(
    tmp_path: Path,
) -> None:
    """The scratch copy's ``.cargo/config.toml`` replaces crates.io with a crate it ships."""
    packet = _inert_vendored_packet(tmp_path)
    scratch = _hostile_scratch(tmp_path)
    with C._offline_dependencies(packet) as offline:
        assert offline is not None and offline.cargo is not None
        env = {**C.child_environment(scratch), **offline.env}
        ran = C.run_confined(
            offline.argv(["cargo", "test", "--offline"]), scratch, env, scratch,
            runner=T.subprocess_runner, timeout=300, reads=offline.reads,
            toolchain=offline.toolchain,
        )
        # The control: cargo by its real path, past the shim, takes the commit's crate.
        plain = C.run_confined(
            [str(shutil.which("cargo")), "test", "--offline"], scratch, env, scratch,
            runner=T.subprocess_runner, timeout=300, reads=offline.reads,
            toolchain=offline.toolchain,
        )
    assert "returned 2" in ran.stdout + ran.stderr, ran.stdout + ran.stderr
    assert "returned 99" in plain.stdout + plain.stderr, plain.stdout + plain.stderr
