"""One review command, from a change to records (issue 160, card C10a)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import socket
import stat
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock
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
        umask: int | None = None,
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
        umask: int | None = None,
    ) -> Any:
        assert shell is False
        proc = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False,
            umask=-1 if umask is None else umask,
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
        "scope": "lines", "file": "src/app.py", "lines": {"start": 2, "end": 4},
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
    changed = change.pop("changed_lines")
    # The one edited line, or the one line the function repo rewrites.
    assert changed in ({"src/app.py": [[4, 4]]}, {"src/app.py": [[2, 2]]})
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
        bank=tmp_path / "no-bank.json",
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
        bank=tmp_path / "no-bank.json",
    )
    assert code == 0, err
    assert (second / "grades.json").read_bytes() == (first / "grades.json").read_bytes()


def _scripted_item(line: int = 2, *, name: str = "machine-specific-value") -> dict[str, Any]:
    return {
        "kind": "where_to_look", "schema": R.SCHEMA, "lens": "architecture-maintainability",
        "language": "python", "degraded": False,
        "questions": [{"id": "machine-specific-value", "probability": 1}],
        "classifier": {"name": name, "model": "review-checks 1.0.0"},
        "location": {
            "scope": "lines", "file": "src/app.py", "lines": {"start": line, "end": line},
            "function": "changed", "anchor": f"machine-specific-value:home:{line}",
        },
    }


def _scripted_adapter(items: tuple[dict[str, Any], ...]) -> Any:
    return T.Adapter(
        id="scripted", tool="scripted", invoke=lambda _context: ["scripted", "scan"],
        parse=lambda _text: T.ParseResult(items=items), default_version="1.0.0",
        rows=("security.scanner-high",), lens="security", comparison="lines",
    )


def test_prepare_keeps_the_scripted_items_beside_the_sweeps(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=True)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    bank = _bank(tmp_path / "bank.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    scripted = _scripted_item()
    argv = [
        "prepare", "--repo", str(repo), "--base", base, "--head", head, "--profile", str(profile),
        "--builder-record", str(builder), "--out", str(out), "--home", str(home),
        "--bank", str(bank),
    ]
    # The same scripted item twice, as two scans of one line would give it.
    adapter = _scripted_adapter((scripted, dict(scripted)))
    code, err = _main(argv, adapters=[adapter], runner=_Runner(), ask=_ask())
    assert code == 0, err
    where = _read(out / "where-to-look.json")
    names = sorted(item["classifier"]["name"] for item in where)
    assert names.count("machine-specific-value") == 1
    assert len(where) == 2
    kept = next(item for item in where if item["classifier"]["name"] == "machine-specific-value")
    assert kept["questions"] == [{"id": "machine-specific-value", "probability": 1}]
    assert "answer" not in kept
    # The sweep's own item is still there.
    assert any(item["classifier"]["name"] != "machine-specific-value" for item in where)
    again = tmp_path / "again"
    argv[argv.index(str(out))] = str(again)
    code, err = _main(argv, adapters=[adapter], runner=_Runner(), ask=_ask())
    assert code == 0, err
    assert (again / "where-to-look.json").read_bytes() == (out / "where-to-look.json").read_bytes()


def test_scripted_items_are_not_counted_against_the_sweeps_cap() -> None:
    swept = [
        {**_scripted_item(number), "classifier": {"name": "jev-sweep", "model": "jev-test"}}
        for number in range(1, 61)
    ]
    scripted = [_scripted_item(61), _scripted_item(62)]
    gap = {**_scripted_item(1), "classifier": {"name": "missing-tool", "model": "none"}}
    merged = C._merge_where_items(scripted, swept, [gap, dict(gap)])
    assert len(merged) == 63
    assert [item["classifier"]["name"] for item in merged[:2]] == ["machine-specific-value"] * 2
    assert merged[-1]["classifier"]["name"] == "missing-tool"
    assert C._merge_where_items(["not an item", None], [], []) == []


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
        bank=tmp_path / "no-bank.json",
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


def _jev_reply(
    *, status: str = "ok", note: str = "", consequence: str = "required-behaviour-missing",
    confidence: float = 0.9,
) -> Any:
    """An ask that answers the consequence question as given and every other question 0.91."""
    def ask(_state: Any, questions: Any, **_kwargs: Any) -> Any:
        if isinstance(questions, dict) and "consequence" in questions:
            if status != "ok":
                return SimpleNamespace(status=status, answers={}, note=note, model="jev-test")
            return SimpleNamespace(
                status="ok", model="jev-test", note="",
                answers={"consequence": {
                    "type": "choice", "choice": consequence, "confidence": confidence,
                }},
            )
        answers = {key: {"type": "noul", "noul": 0.91} for key in questions}
        return SimpleNamespace(
            status="ok", ok=True, model="jev-test", latency_ms=5, note="",
            usage={"input_tokens": 12, "output_tokens": 4}, answers=answers,
        )

    return ask


def _finish_with_jev(tmp: Path, ask: Any) -> tuple[Path, str]:
    _repo_path, packet, runner = _repro_packet(tmp)
    home = tmp / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp, with_test=True)
    code, err = _finish(
        packet, [(_answer([_finding("A retry returns the new number.")]), _result(scratch, changes))],
        home, runner, ask=ask, confine=_Confine(1, _CAPTURED),
    )
    assert code == 0, err
    return packet, err


@pytest.mark.parametrize(
    ("ask", "expected"),
    [
        (
            _jev_reply(consequence="misleads-a-person", confidence=0.5),
            {
                "status": "below-floor", "request": "ok", "jev_pick": None,
                "jev_value": "misleads-a-person", "jev_confidence": 0.5, "floor": 0.6,
                "reason": (
                    "Jev chose 'misleads-a-person' with confidence 0.5, below the floor 0.6"
                ),
            },
        ),
        (
            _jev_reply(status="timeout", note="the request timed out"),
            {
                "status": "request-failed", "request": "timeout", "jev_pick": None,
                "jev_value": None, "jev_confidence": None, "floor": 0.6,
                "reason": "the request timed out",
            },
        ),
        (
            _jev_reply(status="error", note="no key"),
            {
                "status": "request-failed", "request": "error", "jev_pick": None,
                "jev_value": None, "jev_confidence": None, "floor": 0.6, "reason": "no key",
            },
        ),
        (
            _jev_reply(consequence="not-on-the-list", confidence=0.9),
            {
                "status": "off-list", "request": "ok", "jev_pick": None,
                "jev_value": "not-on-the-list", "jev_confidence": 0.9, "floor": 0.6,
                "reason": "Jev's answer 'not-on-the-list' is not on the closed list",
            },
        ),
        (
            _jev_reply(consequence="misleads-a-person", confidence=0.9),
            {
                "status": "accepted", "request": "ok", "jev_pick": "misleads-a-person",
                "jev_value": "misleads-a-person", "jev_confidence": 0.9, "floor": 0.6,
                "reason": "",
            },
        ),
    ],
    ids=["below-floor", "timeout", "error", "off-list", "accepted"],
)
def test_finish_records_why_each_jev_pick_is_missing_or_accepted(
    tmp_path: Path, ask: Any, expected: dict[str, Any],
) -> None:
    packet, err = _finish_with_jev(tmp_path, ask)
    entries = _read(packet / "consequence-picks.json")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.pop("finding_id")
    assert entry.pop("answer") == 0
    assert entry.pop("reviewer_consequence")
    for key, value in expected.items():
        assert entry[key] == value, key
    # The sidecar is a record only: no warning line, no degraded input, no grade.
    assert "warning:" not in err
    run = _read(packet / "review-run.json")
    assert "consequence" not in json.dumps(_read(packet / "degraded.json"))
    assert all(
        "consequence-pick" not in json.dumps(grade.get("degraded_inputs", []))
        for grade in run["lens_grades"]
    )
    found = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert found["consequence_jev"] == expected["jev_pick"]
    assert found["unconfirmed"] is (expected["jev_pick"] is None)


def test_the_consequence_picks_sidecar_changes_no_record_or_grade(tmp_path: Path) -> None:
    """The same finish gives byte-identical records and grades with and without the sidecar."""
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    args = (packet, [(_answer([_finding("A retry returns the new number.")]),
                      _result(scratch, changes))], home, runner)
    code, err = _finish(*args, ask=_jev_reply(confidence=0.5), confine=_Confine(1, _CAPTURED))
    assert code == 0, err
    names = ("review-run.json", "grades.json", "degraded.json", "findings.json")
    with_sidecar = {name: (packet / name).read_bytes() for name in names}
    (packet / "review-run.json").unlink()
    original = C._write_json

    def without_sidecar(path: Path, payload: object) -> None:
        if path.name != "consequence-picks.json":
            original(path, payload)

    (packet / "consequence-picks.json").unlink()
    with mock.patch.object(C, "_write_json", without_sidecar):
        code, err = _finish(*args, ask=_jev_reply(confidence=0.5), confine=_Confine(1, _CAPTURED))
    assert code == 0, err
    assert not (packet / "consequence-picks.json").exists()
    assert {name: (packet / name).read_bytes() for name in names} == with_sidecar


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


_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def _replay_finding(output: str, command: str | None = None) -> dict[str, Any]:
    found = _finding("A retry returns the new number.")
    found["proof"]["output"] = output
    if command is not None:
        found["proof"]["command"] = command
    return found


def _files_holding(root: Path, value: str) -> list[str]:
    """The files under *root* that hold *value*, other than the answer the test itself wrote."""
    return [
        str(path.relative_to(root)) for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.startswith("answer-")
        and value in path.read_text(encoding="utf-8", errors="replace")
    ]


def _llm_finding(run: dict[str, Any]) -> dict[str, Any]:
    return next(item for item in run["findings"] if item["source"]["kind"] == "llm")


def _finish_one_reproduced(tmp: Path, **over: Any) -> dict[str, Any]:
    _repo_path, packet, runner = _repro_packet(tmp)
    home = tmp / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp, with_test=True)
    found = _replay_finding("AssertionError: returned 2")
    found["consequence"] = "security-boundary-crossed"
    found.update(over)
    code, err = _finish(
        packet, [(_answer([found]), _result(scratch, changes))], home, runner,
        ask=_ask(consequence="security-boundary-crossed"), confine=_Confine(1, _CAPTURED),
    )
    assert code == 0, err
    return _read(packet / "review-run.json")


def test_a_reproduced_finding_on_a_changed_line_still_blocks(tmp_path: Path) -> None:
    run = _finish_one_reproduced(tmp_path)
    found = _llm_finding(run)
    assert found["evidence"] == "reproduced"
    assert found["severity"] == "blocks"
    assert run["merge"]["allowed"] is False
    assert run["changed_lines"] == {"src/app.py": [[4, 4]]}


def test_a_reproduced_not_introduced_finding_outside_the_change_is_reported_not_blocking(
    tmp_path: Path,
) -> None:
    outside = {**_location(), "lines": {"start": 1, "end": 2}}
    run = _finish_one_reproduced(tmp_path, location=outside, introduced=False)
    found = _llm_finding(run)
    assert found["evidence"] == "reproduced"
    assert found["severity"] == "fix-later"
    assert found["severity_basis"]["modifiers"] == ["pre-existing"]
    assert run["merge"]["allowed"] is True
    assert found["id"] not in run["merge"]["blocking"]
    assert found["id"] not in run["merge"]["report_only_blocks"]
    assert R.validate(run) == []
    # Take the changed lines away and the stored severity no longer matches a recomputation.
    stripped = {key: value for key, value in run.items() if key != "changed_lines"}
    assert any("severity" in problem for problem in R.validate(stripped))


def test_a_reproduced_introduced_finding_outside_the_change_still_blocks(tmp_path: Path) -> None:
    """A regression the change caused, surfacing at an unchanged caller, refuses the merge."""
    outside = {**_location(), "lines": {"start": 1, "end": 2}}
    run = _finish_one_reproduced(tmp_path, location=outside, introduced=True)
    found = _llm_finding(run)
    assert found["severity"] == "blocks"
    assert "pre-existing" not in found["severity_basis"]["modifiers"]
    assert run["merge"]["allowed"] is False
    assert R.validate(run) == []


def test_a_reproduced_not_introduced_finding_on_a_changed_line_still_blocks(
    tmp_path: Path,
) -> None:
    run = _finish_one_reproduced(tmp_path, introduced=False)
    found = _llm_finding(run)
    assert found["severity"] == "blocks"
    assert run["merge"]["allowed"] is False


def test_a_packet_without_changed_lines_caps_nothing_as_pre_existing(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    change = _read(packet / "change.json")
    del change["changed_lines"]
    _dump(packet / "change.json", change)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    outside = {**_location(), "lines": {"start": 1, "end": 2}}
    found = _replay_finding("AssertionError: returned 2")
    found["location"] = outside
    found["introduced"] = False
    code, err = _finish(
        packet, [(_answer([found]), _result(scratch, changes))], home, runner,
        ask=_ask(), confine=_Confine(1, _CAPTURED),
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    assert "changed_lines" not in run
    assert _llm_finding(run)["severity"] == "blocks"
    assert R.validate(run) == []


def test_a_failure_that_prints_a_secret_shaped_value_still_reproduces(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    message = f"AssertionError: logged the token {_TOKEN} in the clear"
    confine = _Confine(1, f"{message}\ntests/test_changed.py::test_changed\n")
    code, err = _finish(
        packet,
        [(_answer([_replay_finding(message)]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    found = _llm_finding(run)
    assert found["evidence"] == "reproduced"
    # What is stored stays scrubbed, and the raw value is written nowhere.
    assert "[scrubbed:github-token]" in found["proof"]["output"]
    assert _files_holding(tmp_path, _TOKEN) == []


@pytest.mark.parametrize("final", [False, True])
def test_findings_sharing_an_identity_each_replay_their_own_proof(
    tmp_path: Path, final: bool,
) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    unproved = _replay_finding("AssertionError: the charge ran twice")
    unproved["key"] = "charged-twice"
    unproved["consequence"] = "money-or-resources-wrongly-moved"
    proved = _replay_finding("AssertionError: returned 2")
    confine = _Confine(1, _CAPTURED)
    code, err = _finish(
        packet, [(_answer([unproved, proved]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine, final=final,
    )
    assert code == 0, err
    # Both replay in the first round; the merge-gate round replays the kept finding's own proof.
    assert len(confine.calls) == (3 if final else 2)
    found = _llm_finding(_read(packet / "review-run.json"))
    # The claim whose own output never replayed is not the one kept as reproduced.
    assert found["evidence"] == "reproduced"
    assert found["proof"]["output"] == "AssertionError: returned 2"
    assert found["consequence"] != "money-or-resources-wrongly-moved"


def test_the_final_round_replays_the_unscrubbed_proof_too(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    message = f"AssertionError: logged the token {_TOKEN} in the clear"
    confine = _Confine(1, f"{message}\ntests/test_changed.py::test_changed\n")
    code, err = _finish(
        packet, [(_answer([_replay_finding(message)]), _result(scratch, changes))],
        home, runner, ask=_ask(), confine=confine, final=True,
    )
    assert code == 0, err
    assert len(confine.calls) == 2
    found = _llm_finding(_read(packet / "review-run.json"))
    assert found["evidence"] == "reproduced"
    assert _files_holding(tmp_path, _TOKEN) == []


def test_a_scrub_false_positive_phrase_still_reproduces(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    message = "AssertionError: the bearer credential was written to the log"
    assert "[scrubbed:bearer-token]" in A.scrub_text(message)[0]
    confine = _Confine(1, f"{message}\ntests/test_changed.py::test_changed\n")
    code, err = _finish(
        packet,
        [(_answer([_replay_finding(message)]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    found = _llm_finding(_read(packet / "review-run.json"))
    assert found["evidence"] == "reproduced"
    assert "[scrubbed:bearer-token]" in found["proof"]["output"]


def test_the_replay_runs_the_command_as_written_while_the_record_is_scrubbed(
    tmp_path: Path,
) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    command = f"python3 -m pytest tests/test_changed.py -q -k {_TOKEN}"
    confine = _Confine(1, _CAPTURED)
    code, err = _finish(
        packet,
        [(_answer([_replay_finding("AssertionError: returned 2", command)]),
          _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    assert confine.calls[0][-1] == _TOKEN
    found = _llm_finding(_read(packet / "review-run.json"))
    assert found["evidence"] == "reproduced"
    assert _TOKEN not in found["proof"]["command"]
    assert _files_holding(tmp_path, _TOKEN) == []


def test_colour_codes_after_a_secret_cannot_pull_a_fragment_into_the_tail() -> None:
    key = "AKIA" + "Q7X2M9PLR4TZ8WB3"
    # The raw window starts ten characters before the key ends; stripping the colour codes after
    # the cut would leave only that fragment and a short ending.
    after = "\x1b[0m" * 24_996 + "\nend!!"
    assert len(after) == 99_990
    tail = C._output_tail(f"leaked {key}{after}")
    assert "R4TZ8WB3" not in tail
    assert tail.endswith("end!!")


def test_a_mismatch_records_why_with_a_capped_scrubbed_tail(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    noise = "a different failure line\n" * 100
    ran = f"{noise}Error: leaked {_TOKEN}\nlast line of the run\n"
    code, err = _finish(
        packet,
        [(_answer([_replay_finding("AssertionError: returned 2")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=_Confine(1, ran),
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    assert _llm_finding(run)["evidence"] == "traced"
    entry = next(item for item in run["degraded_inputs"] if item["reason"] == "re-run-mismatch")
    assert entry["tool"] == "review-command"
    assert entry["exit_code"] == 1
    assert entry["input"] == "tests/test_changed.py::test_changed"
    assert 0 < len(entry["output_tail"]) <= C.RERUN_TAIL_CHARS
    assert entry["output_tail"].endswith("last line of the run")
    assert _files_holding(tmp_path, _TOKEN) == []
    lens = next(grade for grade in run["lens_grades"] if grade["lens"] == entry["lens"])
    assert entry in lens["degraded_inputs"]


def test_the_tail_scrubs_a_secret_inside_it(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    code, err = _finish(
        packet,
        [(_answer([_replay_finding("AssertionError: returned 2")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"),
        confine=_Confine(1, f"Error: leaked {_TOKEN}\n"),
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    entry = next(item for item in run["degraded_inputs"] if item["reason"] == "re-run-mismatch")
    assert entry["output_tail"] == "Error: leaked [scrubbed:github-token]"


@pytest.mark.parametrize(
    ("code", "stdout"),
    [
        (127, "env: python3: No such file or directory\n"),
        (126, "permission denied\n"),
        (71, "sandbox-exec: execvp() of 'python3' failed: No such file or directory\n"),
        (1, "bwrap: execvp python3: No such file or directory\n"),
    ],
)
def test_a_command_that_could_not_start_is_not_a_mismatch(
    tmp_path: Path, code: int, stdout: str,
) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    status, err = _finish(
        packet,
        [(_answer([_replay_finding("AssertionError: returned 2")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=_Confine(code, stdout),
    )
    assert status == 0, err
    run = _read(packet / "review-run.json")
    assert _llm_finding(run)["evidence"] == "traced"
    reasons = [item["reason"] for item in run["degraded_inputs"]]
    assert "re-run-could-not-start" in reasons
    assert "re-run-mismatch" not in reasons
    entry = next(
        item for item in run["degraded_inputs"] if item["reason"] == "re-run-could-not-start"
    )
    assert entry["exit_code"] == code
    assert entry["output_tail"] == stdout.strip()


def test_a_sandbox_deny_line_from_a_test_that_ran_is_a_mismatch(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    stdout = "Sandbox: python3(4242) deny(1) file-read-data /private/var\nError: other\n"
    status, err = _finish(
        packet,
        [(_answer([_replay_finding("AssertionError: returned 2")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"), confine=_Confine(1, stdout),
    )
    assert status == 0, err
    reasons = [item["reason"] for item in _read(packet / "review-run.json")["degraded_inputs"]]
    assert "re-run-mismatch" in reasons
    assert "re-run-could-not-start" not in reasons


def test_degraded_inputs_from_a_replay_never_change_a_grade_letter(tmp_path: Path) -> None:
    _repo_path, packet, runner = _repro_packet(tmp_path)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    code, err = _finish(
        packet,
        [(_answer([_replay_finding("AssertionError: returned 2")]), _result(scratch, changes))],
        home, runner, ask=_ask(consequence_status="error"),
        confine=_Confine(1, "Error: a different failure\n"),
    )
    assert code == 0, err
    run = _read(packet / "review-run.json")
    assert any(item["reason"] == "re-run-mismatch" for item in run["degraded_inputs"])

    def grades(degraded: list[dict[str, Any]]) -> list[tuple[str, str]]:
        fresh = F.compute({
            "findings": [
                {key: value for key, value in item.items() if key not in F.COMPUTED_FINDING_KEYS}
                for item in run["findings"]
            ],
            "measurements": run["measurements"],
            "builder_records": run["builder_records"],
            "may_block": run["may_block"],
            "degraded_inputs": degraded,
        })
        return [(row["lens"], row["grade"]) for row in fresh["lens_grades"]]

    assert grades(run["degraded_inputs"]) == grades([])
    assert [(row["lens"], row["grade"]) for row in run["lens_grades"]] == grades([])


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
        bank=tmp_path / "no-bank.json",
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


def test_optional_diagnostics_never_changes_packet_bytes_or_raw_digests(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=False)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    adapter = T.Adapter(
        id="cargo-mutants", tool="stub", invoke=lambda _context: ["stub", "scan"],
        parse=lambda _text: T.ParseResult(), default_version="1.0.0",
        rows=("testing.surviving-mutant",), lens="testing", comparison="lines",
        mutation=True, report_file="mutants.out/outcomes.json",
        exit_reasons=((4, "baseline-failed"),), retry_failures=("baseline-failed",),
    )

    class Runner(_Runner):
        def __call__(self, argv: list[str], **kwargs: Any) -> Any:
            if argv != ["stub", "scan"]:
                return super().__call__(argv, **kwargs)
            folder = kwargs["cwd"] / "mutants.out"
            (folder / "log").mkdir(parents=True, exist_ok=True)
            (folder / "log" / "baseline.log").write_text(
                "build chatter\n" * 10000 + f"volatile terminal diagnostic {len(self.calls)}"
            )
            (folder / "outcomes.json").write_text(json.dumps({"outcomes": [{
                "scenario": "Baseline", "summary": "Failure", "log_path": "log/baseline.log",
            }]}))
            return T.ProcessResult(4, "build chatter\n" * 10000 + f"volatile console {len(self.calls)}", "test error")

    packets: list[dict[str, bytes]] = []
    hashes: list[str] = []
    for index, diagnostics in enumerate([None, tmp_path / "private-first", tmp_path / "private-second"]):
        out = tmp_path / f"packet-{index}"
        argv = [
            "prepare", "--repo", str(repo), "--base", base, "--head", head,
            "--profile", str(profile), "--builder-record", str(builder),
            "--out", str(out), "--home", str(home),
        ]
        if diagnostics is not None:
            argv.extend(["--diagnostics-directory", str(diagnostics)])
        code, err = _main(argv, adapters=[adapter], runner=Runner())
        assert code == 0, err
        packet = {path.relative_to(out).as_posix(): path.read_bytes()
                  for path in out.rglob("*") if path.is_file()}
        packets.append(packet)
        hasher = hashlib.sha256()
        for name, data in sorted(packet.items()):
            hasher.update(name.encode() + b"\0" + data + b"\0")
        hashes.append(hasher.hexdigest())
        degraded = json.loads(packet["degraded.json"])
        failure = next(item for item in degraded if item["reason"] == "baseline-failed")
        assert failure["raw_output"]
        if diagnostics is not None:
            assert len(list(diagnostics.glob("*/attempt.json"))) == 2
            assert str(diagnostics).encode() not in b"".join(packet.values())
    assert packets[0] == packets[1] == packets[2]
    assert len(set(hashes)) == 1


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
               shell: bool, umask: int | None = None) -> Any:
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
               shell: bool, umask: int | None = None) -> Any:
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


def test_replay_refuses_a_leading_environment_assignment() -> None:
    """The replay wrapper agrees with the check: an assignment is not an executable."""
    assert C._argv("RUST_BACKTRACE=1 cargo test --offline") is None


def test_replay_keeps_direct_commands_quotes_and_equals_arguments() -> None:
    assert C._argv("cargo test --offline") == ["cargo", "test", "--offline"]
    assert C._argv("cargo test -- --exact 'my test'") == [
        "cargo", "test", "--", "--exact", "my test",
    ]
    assert C._argv("python3 -m pytest tests/x.py -o log_cli=true") == [
        "python3", "-m", "pytest", "tests/x.py", "-o", "log_cli=true",
    ]
    assert C._argv("") is None
    assert C._argv("sh -c 'cargo test'") is None
    assert C._argv("env FOO=1 cargo test") is None


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


# --- Python dependencies: a virtual environment in the packet --------------------------------------


def _load_fake_uv() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "saga_tests_fake_uv", Path(__file__).resolve().parent / "support" / "fake_uv.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_UV = _load_fake_uv()


class _UvRunner(_Runner):
    """git for real, the stub tool's fixed scan, and the fake uv behind the fetch watcher."""

    def __init__(self, **fake: Any) -> None:
        super().__init__()
        self.uv = _UV.FakeUv(real_git=True, **fake)

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
        umask: int | None = None,
    ) -> Any:
        if argv[:2] == [sys.executable, "-I"] and "--" in argv:
            return self.uv(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)
        return super().__call__(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)


def _python_change(tmp: Path) -> tuple[Path, str, str]:
    """A locked Python project whose head changes the function a dependency's value feeds."""
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\ndependencies = ["inertdep"]\n',
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nFOUR\nfive\n", encoding="utf-8")
    return repo, base, _commit(repo, "head")


def _python_packet(
    tmp: Path, name: str = "packet", change: tuple[Path, str, str] | None = None,
) -> tuple[Path, _UvRunner]:
    repo, base, head = change or _python_change(tmp)
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    runner = _UvRunner(exported=_UV.EXPORTED, compiled=_UV.PYTEST)
    out = tmp / name
    code, err = _prepare(
        repo, base, head, _profile(tmp / "outside"), _builder(tmp / "builder.json"), out, home,
        runner, start=4,
    )
    assert code == 0, err
    return out, runner


def _dependency_test(scratch: Path) -> dict[str, list[str]]:
    (scratch / "tests").mkdir(parents=True)
    (scratch / "tests" / "test_dep.py").write_text(
        "import inertdep\n\n\ndef test_dep():\n"
        "    if inertdep.two() != 3:\n"
        "        raise AssertionError(f'inertdep returned {inertdep.two()}')\n",
        encoding="utf-8",
    )
    return {"added": ["tests/test_dep.py"], "modified": [], "deleted": []}


def _dependency_finding() -> dict[str, Any]:
    finding = _finding("The dependency's value is used unchanged.", key="dependency")
    finding["proof"] = {
        "test": "tests/test_dep.py::test_dep",
        "command": "python3 -m pytest tests/test_dep.py -q -p no:cacheprovider",
        "output": "AssertionError: inertdep returned 2",
    }
    return finding


class _RunConfine:
    """Runs the re-run for real with the environment finish built, without the sandbox, so the
    test holds on a machine with no confinement helper; the live test below adds the sandbox."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], cwd: Path, env: dict[str, str], _scratch: Path) -> Any:
        first = Path(env["PATH"].split(os.pathsep)[0])
        listing = sorted(item.name for item in first.iterdir()) if first.is_dir() else []
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=C.RERUN_TIMEOUT, check=False)
        self.runs.append({"argv": list(argv), "env": dict(env), "code": proc.returncode,
                          "output": proc.stdout + proc.stderr, "first": listing})
        return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)


def test_prepare_installs_a_locked_python_head_and_the_reproduction_imports_it_at_finish(
    tmp_path: Path,
) -> None:
    packet, runner = _python_packet(tmp_path)
    record = _read(packet / "dependencies.json")
    assert record["python"]["state"] == "installed"
    assert record["python"]["directory"] == "dependencies/python/site-packages"
    assert "rust" not in record
    deps = _DEPS.python_environment(packet)
    assert deps is not None
    site = deps.site
    # A console script a wheel could name ``git`` or ``bwrap`` is never kept; plant one anyway.
    (site / "bin").mkdir()
    for name in ("git", "bwrap", "claude", "python3"):
        (site / "bin" / name).write_text("#!/bin/sh\necho planted\n", "utf-8")
        (site / "bin" / name).chmod(0o755)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch = tmp_path / "scratch"
    changes = _dependency_test(scratch)
    confine = _RunConfine()
    code, err = _finish(
        packet, [(_answer([_dependency_finding()]), _result(scratch, changes))], home, runner,
        ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    rerun = confine.runs[0]
    assert rerun["argv"][:3] == ["python3", "-m", "pytest"], "the command is replayed unchanged"
    assert rerun["first"] == ["python", "python3"], "only saga's python is put first on PATH"
    assert not any(str(packet.resolve()) in part or str(packet) in part
                   for part in rerun["env"]["PATH"].split(os.pathsep))
    assert rerun["env"]["VIRTUAL_ENV"] == str(Path(rerun["env"]["PATH"].split(os.pathsep)[0]).parent)
    assert "inertdep returned 2" in rerun["output"], rerun["output"]
    assert "planted" not in rerun["output"]
    run = _read(packet / "review-run.json")
    stored = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert stored["evidence"] == "reproduced", run["degraded_inputs"]
    assert not Path(rerun["env"]["VIRTUAL_ENV"]).exists(), "the re-run's environment is removed"


def test_prepare_twice_on_a_python_change_writes_identical_packets(tmp_path: Path) -> None:
    """Issue 244's rule for the environment: other staging folders, the same packet bytes."""
    change = _python_change(tmp_path)
    packets = [_python_packet(tmp_path, f"packet-{n}", change)[0] for n in (1, 2)]
    contents = [{
        path.relative_to(packet).as_posix(): (
            os.readlink(path) if path.is_symlink() else path.read_bytes()
        )
        for path in sorted(packet.rglob("*")) if path.is_symlink() or path.is_file()
    } for packet in packets]
    assert contents[0] == contents[1]
    assert "dependencies/python/site-packages/inertdep/__init__.py" in contents[0]
    assert not any(str(tmp_path).encode() in value for value in contents[0].values()
                   if isinstance(value, bytes) and not value.startswith(b"{\n  \"base\""))


def test_prepare_on_a_change_without_python_files_runs_no_uv(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, function=False)
    (tmp_path / "home").mkdir()
    runner = _UvRunner()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, _profile(tmp_path / "outside"), _builder(tmp_path / "builder.json"),
        out, tmp_path / "home", runner, start=4,
    )
    assert code == 0, err
    assert _read(out / "dependencies.json") == {"schema": _DEPS.SCHEMA}
    assert runner.uv.calls == [] and not (out / "dependencies").exists()


def test_finish_without_a_python_environment_leaves_path_alone(tmp_path: Path) -> None:
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
    assert "VIRTUAL_ENV" not in confine.envs[0]
    assert confine.envs[0]["PATH"] == os.environ["PATH"]


def test_the_python_environment_is_read_and_mapped_never_written(tmp_path: Path) -> None:
    packet, _runner = _python_packet(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with C._offline_dependencies(packet) as offline:
        assert offline is not None and offline.python is not None and not offline.rust
        site = str((packet / "dependencies" / "python" / "site-packages").resolve())
        shim = str(offline.python.resolve())
        profile = C._seatbelt(scratch, ["python3"], offline.reads, offline.toolchain)
        command = C._bwrap(scratch, ["python3"], (*offline.reads, *offline.toolchain))
    lines = profile.splitlines()
    for path in (site, shim):
        assert f'(allow file-read* (subpath "{path}"))' in lines
        assert f'(allow file-map-executable (subpath "{path}"))' in lines
        assert not any("file-write" in line and path in line for line in lines)
        index = command.index(path)
        assert command[index - 1] == "--ro-bind"
        assert not any(part == "--bind" and command[i + 1] == path
                       for i, part in enumerate(command[:-1]))


def test_the_bwrap_helper_is_found_on_the_operator_s_path_never_the_re_run_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    real = tools / "bwrap"
    real.write_text("#!/bin/sh\nexit 0\n", "utf-8")
    real.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}/usr/bin:/bin")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    command = C._bwrap(scratch, ["python3"])
    assert command[0] == str(real.resolve()), "an absolute path, so the child's PATH is moot"


def test_a_python_environment_for_another_interpreter_version_is_not_used(
    tmp_path: Path,
) -> None:
    packet, _runner = _python_packet(tmp_path)
    data = _read(packet / "dependencies.json")
    data["python"]["interpreter"]["version"] = "2.7.18"
    _dump(packet / "dependencies.json", data)
    with C._offline_dependencies(packet) as offline:
        assert offline is None


def test_a_cargo_rerun_beside_a_python_environment_still_gets_rustup(tmp_path: Path) -> None:
    offline = C.Offline(env={"PATH": "/venv/bin"}, reads=(), python=tmp_path)
    assert not offline.rust
    assert offline.argv(["cargo", "test"]) == ["cargo", "test"]


@pytest.mark.skipif(C.platform_helper() is None, reason="no reproduction helper on this platform")
def test_live_the_confined_rerun_imports_from_the_environment_and_cannot_write_it(
    tmp_path: Path,
) -> None:
    packet, _runner = _python_packet(tmp_path)
    scratch = tmp_path / "scratch"
    (scratch / "tmp").mkdir(parents=True)
    (scratch / "check.py").write_text(
        "import inertdep\nraise SystemExit(f'inertdep returned {inertdep.two()}')\n",
        encoding="utf-8",
    )
    site = packet / "dependencies" / "python" / "site-packages"
    with C._offline_dependencies(packet) as offline:
        assert offline is not None and offline.python is not None
        env = {**C.child_environment(scratch), **offline.env}

        def run(argv: list[str]) -> Any:
            return C.run_confined(argv, scratch, env, scratch, runner=_exec_runner(),
                                  timeout=60, reads=offline.reads, toolchain=offline.toolchain)

        imported = run(["python3", "check.py"])
        touched = run(["/usr/bin/touch", str(site / "planted")])
        rewritten = run(["python3", "-c",
                         "import inertdep, pathlib; pathlib.Path(inertdep.__file__).write_text('')"])
        shim_write = run(["/usr/bin/touch", str(offline.python / "bin" / "git")])
    assert "inertdep returned 2" in imported.stdout + imported.stderr, imported.stderr
    assert touched.code != 0 and not (site / "planted").exists()
    assert rewritten.code != 0
    assert shim_write.code != 0
    assert (site / "inertdep" / "__init__.py").read_text("utf-8").startswith("def two")


# --- Dart: pub packages in the packet, dart test in the re-run ------------------------------------


_DART = C.review_dependencies_dart


def _dart_packet(tmp: Path) -> Path:
    """A prepared packet plus a hand-written pub cache entry, so no SDK or network is needed."""
    _repo_path, packet, _runner = _repro_packet(tmp)
    package = packet / "dependencies" / "dart" / "pub-cache" / "hosted" / "pub.dev" / "inert-1.0.0"
    (package / "lib").mkdir(parents=True)
    (package / "lib" / "inert.dart").write_text("int two() => 2;\n", "utf-8")
    (package / "bin").mkdir()
    (package / "bin" / "git").write_text("#!/bin/sh\necho planted\n", "utf-8")
    (packet / "dependencies" / "dart" / "pub-cache" / "hosted-hashes").mkdir()
    data = _read(packet / "dependencies.json")
    data["dart"] = {"state": "installed", "directory": "dependencies/dart/pub-cache",
                    "sdk": {"version": "3.13.2"}, "packages": [], "lock_sha256": "ab" * 32}
    _dump(packet / "dependencies.json", data)
    return packet


def _fake_sdk(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    root = tmp / "sdk"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "dart").write_bytes(b"\xcf\xfa\xed\xfe\n")
    (root / "version").write_text("3.13.2\n", "utf-8")
    sdk = _DART.DartSdk(executable=(root / "bin" / "dart").resolve(), root=root.resolve(),
                        version="3.13.2")
    monkeypatch.setattr(_DART, "dart_sdk", lambda path=None: sdk)
    return sdk


class _DartConfine(_Confine):
    """Records each call's argv and environment, and what the first PATH folder holds."""

    def __init__(self) -> None:
        super().__init__(1, _CAPTURED)
        self.seen: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], cwd: Path, env: dict[str, str], scratch: Path) -> Any:
        first = Path(env["PATH"].split(os.pathsep)[0])
        cache = Path(env.get("PUB_CACHE", "/nonexistent"))
        self.seen.append({
            "argv": list(argv), "env": dict(env), "cwd": Path(cwd),
            "first": sorted(item.name for item in first.iterdir()) if first.is_dir() else [],
            "cache": sorted(item.name for item in cache.iterdir()) if cache.is_dir() else [],
            "hosted": (cache / "hosted").resolve() if cache.is_dir() else None,
        })
        return super().__call__(argv, cwd, env, scratch)


def test_finish_resolves_a_dart_head_offline_then_replays_the_command_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _dart_packet(tmp_path)
    sdk = _fake_sdk(tmp_path, monkeypatch)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    (scratch / "pubspec.yaml").write_text("name: tiny\n", "utf-8")
    confine = _DartConfine()
    finding = _finding("A retry returns the new number.")
    finding["proof"]["command"] = "dart test tests/test_changed.py"
    code, err = _finish(
        packet, [(_answer([finding]), _result(scratch, changes))], home, _Runner(),
        ask=_ask(consequence_status="error"), confine=confine,
    )
    assert code == 0, err
    # The export of the head has no pubspec.yaml here, so only the reviewer's command runs.
    assert [call["argv"] for call in confine.seen] == [["dart", "test", "tests/test_changed.py"]]
    call = confine.seen[0]
    assert call["first"] == ["dart"], "only saga's dart is put first on PATH"
    assert call["env"]["DASH__SUPPRESS_ANALYTICS"] == "true"
    assert call["env"]["PUB_MAX_HTTP_RETRIES"] == "0"
    cache = Path(call["env"]["PUB_CACHE"])
    assert cache.parent.name == "tmp" and cache.name.startswith("saga-pub-cache-")
    assert call["cache"] == ["hosted", "hosted-hashes"]
    packet_cache = (packet / "dependencies" / "dart" / "pub-cache").resolve()
    assert call["hosted"] == packet_cache / "hosted"
    for part in call["env"]["PATH"].split(os.pathsep):
        assert not part.startswith(str(packet.resolve())) and not part.startswith(str(packet))
    assert sdk.executable.name == "dart"


def test_finish_runs_the_offline_resolution_first_when_the_head_is_a_dart_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _dart_packet(tmp_path)
    _fake_sdk(tmp_path, monkeypatch)
    offline_cm = C._offline_dependencies(packet)
    offline = offline_cm.__enter__()
    try:
        assert offline is not None and offline.dart is not None and offline.python is None
        scratch = tmp_path / "rerun"
        (scratch / "tmp").mkdir(parents=True)
        (scratch / "pubspec.yaml").write_text("name: tiny\n", "utf-8")
        confine = _DartConfine()
        added = C._dart_pub_cache(offline, scratch, _Runner(), confine, ["dart", "test"])
        other = C._dart_pub_cache(offline, scratch, _Runner(), confine, ["python3", "-m", "pytest"])
    finally:
        offline_cm.__exit__(None, None, None)
    # Only a dart command is resolved first; each re-run gets its own fresh cache folder.
    assert [call["argv"] for call in confine.seen] == [
        ["dart", "pub", "get", "--offline", "--enforce-lockfile"]]
    assert Path(added["PUB_CACHE"]).parent == scratch / "tmp"
    assert added["PUB_CACHE"] != other["PUB_CACHE"]


def test_finish_without_a_dart_sdk_adds_nothing_for_dart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _dart_packet(tmp_path)
    monkeypatch.setattr(_DART, "dart_sdk", lambda path=None: None)
    with C._offline_dependencies(packet) as offline:
        assert offline is None


def test_finish_leaves_dart_out_when_the_sdk_is_another_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _dart_packet(tmp_path)
    other = _DART.DartSdk(executable=tmp_path / "dart", root=tmp_path, version="3.14.0")
    monkeypatch.setattr(_DART, "dart_sdk", lambda path=None: other)
    with C._offline_dependencies(packet) as offline:
        assert offline is None


def test_finish_survives_a_link_an_earlier_re_run_left_at_the_cache_s_old_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 1's command plants tmp/saga-pub-cache as a dangling link; finding 2 still runs."""
    packet = _dart_packet(tmp_path)
    _fake_sdk(tmp_path, monkeypatch)
    home = tmp_path / "home"
    _machine(home, "available")
    scratch, changes = _scratch(tmp_path, with_test=True)
    planted: list[Path] = []

    class Planting(_DartConfine):
        def __call__(self, argv: list[str], cwd: Path, env: dict[str, str], scratch_: Path) -> Any:
            if not planted:
                link = Path(cwd) / "tmp" / "saga-pub-cache"
                link.symlink_to(tmp_path / "does-not-exist")
                planted.append(link)
            return super().__call__(argv, cwd, env, scratch_)

    confine = Planting()
    first, second = (_finding(f"Finding {n} returns the new number.", key=f"k{n}") for n in (1, 2))
    code, err = _finish(packet, [(_answer([first, second]), _result(scratch, changes))], home,
                        _Runner(), ask=_ask(consequence_status="error"), confine=confine)
    assert code == 0, err
    assert len(confine.seen) == 2, "the second finding re-ran after the plant"
    assert not (tmp_path / "does-not-exist").exists()


def test_a_link_at_tmp_is_refused_before_anything_follows_it(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o755)
    (scratch / "tmp").symlink_to(outside)
    assert C._make_tmp(scratch) is False
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755, "chmod never followed the link"
    offline = C.Offline(env={}, reads=(), dart=tmp_path / "cache")
    with pytest.raises(OSError):
        C._dart_pub_cache(offline, scratch, _Runner(), None, ["dart", "test"])
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(C.platform_helper() is None, reason="no reproduction helper on this platform")
def test_live_a_confined_command_cannot_steer_finish_s_setup_outside_the_scratch_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The review's attack, for real: a confined re-run plants links in the shared scratch
    copy; the unconfined set-up for the next re-run must create nothing through them."""
    packet = _dart_packet(tmp_path)
    _fake_sdk(tmp_path, monkeypatch)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert C._make_tmp(scratch)
    outside = tmp_path / "planted-target"
    outside.mkdir()
    outside.chmod(0o755)
    env = C.child_environment(scratch)

    def confined(argv: list[str]) -> Any:
        return C.run_confined(argv, scratch, env, scratch, runner=_exec_runner(), timeout=30)

    planted = confined(["/bin/ln", "-s", str(outside), str(scratch / "tmp" / "saga-pub-cache")])
    assert planted.code == 0, planted.stderr
    with C._offline_dependencies(packet) as offline:
        assert offline is not None
        assert C._make_tmp(scratch)
        C._dart_pub_cache(offline, scratch, _Runner(), None, ["python3"])
        assert list(outside.iterdir()) == [], "nothing is created through the planted link"
        swapped = confined(["/bin/mv", str(scratch / "tmp"), str(scratch / "old-tmp")])
        relinked = confined(["/bin/ln", "-s", str(outside), str(scratch / "tmp")])
        assert swapped.code == 0 and relinked.code == 0
        assert C._make_tmp(scratch) is False
        with pytest.raises(OSError):
            C._dart_pub_cache(offline, scratch, _Runner(), None, ["dart", "test"])
    assert list(outside.iterdir()) == []
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755


@pytest.mark.skipif(
    os.environ.get("SAGA_TEST_LIVE_DART") != "1" or shutil.which("dart") is None
    or C.platform_helper() is None,
    reason="opt-in (SAGA_TEST_LIVE_DART=1): needs the Dart SDK, the network and the sandbox",
)
def test_live_a_dart_reproduction_passes_through_finish_and_cannot_write_the_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prepare fetches a from-scratch package's pub packages for real; finish replays
    ``dart test`` confined, with the operator's home unreadable, and the failure matches."""
    monkeypatch.setenv("HOME", str(_OPERATOR_HOME))
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "lib").mkdir()
    (repo / "test").mkdir()
    (repo / "pubspec.yaml").write_text(
        "name: tiny\nenvironment:\n  sdk: ^3.0.0\ndev_dependencies:\n  test: ^1.25.0\n", "utf-8")
    (repo / "lib" / "tiny.dart").write_text("int two() => 3;\n", "utf-8")
    (repo / "test" / "placeholder_test.dart").write_text(
        "import 'package:test/test.dart';\n\nvoid main() {\n  test('ok', () {});\n}\n", "utf-8")
    subprocess.run(["dart", "pub", "get"], cwd=repo, check=True, capture_output=True, timeout=300,
                   env={**os.environ, "PUB_CACHE": str(tmp_path / "lock-cache"),
                        "DASH__SUPPRESS_ANALYTICS": "true"})
    shutil.rmtree(repo / ".dart_tool")
    base = _commit(repo, "base")
    (repo / "lib" / "tiny.dart").write_text("int two() => 2;\n", "utf-8")
    head = _commit(repo, "head")
    home = tmp_path / "saga-home"
    home.mkdir()
    _machine(home, "available")
    packet = tmp_path / "packet"

    class Fetching(_Runner):
        """The stub tool and real git, as elsewhere; the fetch watcher's commands for real."""

        def __call__(self, argv: list[str], **kwargs: Any) -> Any:
            if argv[:2] == [sys.executable, "-I"]:
                return _exec_runner()(argv, **kwargs)
            return super().__call__(argv, **kwargs)

    code, err = _prepare(
        repo, base, head, _profile(tmp_path / "outside"), _builder(tmp_path / "builder.json"),
        packet, home, Fetching(), start=2, ask=_ask(), bank=tmp_path / "no-bank.json",
    )
    assert code == 0, err
    assert _read(packet / "dependencies.json")["dart"]["state"] == "installed"
    scratch = tmp_path / "scratch"
    (scratch / "test").mkdir(parents=True)
    (scratch / "test" / "tiny_test.dart").write_text(
        "import 'package:test/test.dart';\nimport 'package:tiny/tiny.dart';\n\n"
        "void main() {\n  test('two is three', () {\n"
        "    expect(two(), 3, reason: 'two returned ${two()}');\n  });\n}\n", "utf-8")
    changes = {"added": ["test/tiny_test.dart"], "modified": [], "deleted": []}
    finding = _finding("two returns 2.", key="dart")
    finding["language"] = "dart"
    finding["proof"] = {
        "test": "test/tiny_test.dart::two is three",
        "command": "dart test test/tiny_test.dart",
        # The whole failure block, as the reviewer prompt asks.
        "output": "00:00 +0 -1: two is three [E]\n  Expected: <3>\n    Actual: <2>\n"
                  "  two returned 2\n  \n  package:matcher          expect\n"
                  "  test/tiny_test.dart 6:5  main.<fn>\n",
    }
    code, err = _finish(packet, [(_answer([finding]), _result(scratch, changes))], home,
                        _exec_runner(), ask=_ask(consequence_status="error"))
    assert code == 0, err
    run = _read(packet / "review-run.json")
    stored = next(item for item in run["findings"] if item["source"]["kind"] == "llm")
    assert stored["evidence"] == "reproduced", [
        item.get("output_tail") for item in run["degraded_inputs"]]
    cache = packet / "dependencies" / "dart" / "pub-cache"
    with C._offline_dependencies(packet) as offline:
        assert offline is not None
        rerun = tmp_path / "write-probe"
        (rerun / "tmp").mkdir(parents=True)
        env = {**C.child_environment(rerun), **offline.env}
        wrote = C.run_confined(["/usr/bin/touch", str(cache / "hosted" / "planted")], rerun,
                               env, rerun, runner=_exec_runner(), timeout=30,
                               reads=offline.reads, toolchain=offline.toolchain)
    assert wrote.code != 0 and not (cache / "hosted" / "planted").exists()


# --- prepare bundles the reviewer self-check (preflight contract) -------------------------------


_BUNDLE_MODULES: tuple[str, ...] = (
    "reviewer_answer.py", "review_formula.py", "review_records.py", "run_record.py",
    "reproduction_match.py",
)
_ANSWER_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reviewer_answer"
def _bundle_env(tmp: Path) -> dict[str, str]:
    """A child environment with provider keys and PYTHONPATH removed (preflight rule)."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SYSTEMROOT", "WINDIR"}
    }
    env.pop("PYTHONPATH", None)
    env["HOME"] = str(tmp / "home")
    env["XDG_CACHE_HOME"] = str(tmp / "cache")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    assert "TYPESAFE_API_KEY" not in env
    return env


def _bundle_packet(tmp: Path) -> Path:
    """A normally prepared packet; asserts only the pre-existing prepare behavior."""
    repo, base, head = _repo(tmp, function=False)
    profile = _profile(tmp / "outside")
    builder = _builder(tmp / "builder.json")
    home = tmp / "home"
    home.mkdir()
    out = tmp / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), start=4,
    )
    assert code == 0, err
    assert (out / "where-to-look.json").is_file()
    return out


def _bundled_checker(packet: Path) -> Path:
    """The packet's copied checker, or a RED gate naming the absent helper."""
    checker = packet / "check" / "reviewer_answer.py"
    assert checker.is_file(), (
        "prepare wrote no bundled checker (preflight helper absent on this base)"
    )
    return checker


def test_prepare_bundles_the_reviewer_self_check_modules(tmp_path: Path) -> None:
    """Normal prepare copies the five checker modules byte-for-byte into packet/check/."""
    out = _bundle_packet(tmp_path)
    bundled = out / "check"
    assert bundled.is_dir(), "prepare wrote no packet/check/ bundle (preflight helper absent)"
    assert {path.name for path in bundled.iterdir()} == set(_BUNDLE_MODULES)
    for name in _BUNDLE_MODULES:
        assert (bundled / name).read_bytes() == (SCRIPTS / name).read_bytes(), (
            f"packet/check/{name} differs from the shipped module"
        )


def test_finish_refuses_an_invalid_answer_even_if_packet_checker_accepts_it(tmp_path: Path) -> None:
    """Advisory checker bytes cannot replace finish's authoritative validator."""
    _repo_path, packet, runner = _line_packet(tmp_path)
    checker = _bundled_checker(packet)
    checker.write_text("raise SystemExit(0)\n", encoding="utf-8")
    scratch, changes = _scratch(tmp_path, with_test=False)
    bad = _answer([])
    bad["severity"] = "blocks"
    draft = scratch / "answer-draft.json"
    _dump(draft, bad)
    advised = subprocess.run(
        [sys.executable, str(checker), "check", "--answer", str(draft),
         "--items", str(packet / "where-to-look.json")],
        cwd=scratch, env=_bundle_env(tmp_path), capture_output=True, text=True, timeout=30,
    )
    assert advised.returncode == 0
    draft.unlink()
    code, err = _finish(
        packet, [(bad, _result(scratch, changes))], tmp_path / "home", runner, ask=_ask(),
    )
    assert code == 1
    assert "severity" in err
    assert not (packet / "review-run.json").exists()


def test_copied_checker_accepts_a_valid_draft_from_an_isolated_cwd(tmp_path: Path) -> None:
    """The bundled checker self-validates a draft with no source, repo, or provider access."""
    checker = _bundled_checker(_bundle_packet(tmp_path))
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    completed = subprocess.run(
        [sys.executable, str(checker), "check",
         "--answer", str(_ANSWER_FIXTURES / "answer.json"),
         "--items", str(_ANSWER_FIXTURES / "where-to-look.json")],
        capture_output=True, text=True, check=False,
        env=_bundle_env(tmp_path), timeout=120, cwd=isolated,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert completed.stderr == ""


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("origin", "is not item 0's finding"),
        ("proof", "is not a test file"),
    ],
)
def test_copied_checker_refuses_known_bad_drafts(
    tmp_path: Path, mutation: str, expected: str,
) -> None:
    """The bundled checker refuses bad links and proof paths without network or Jev."""
    checker = _bundled_checker(_bundle_packet(tmp_path))
    draft = json.loads((_ANSWER_FIXTURES / "answer.json").read_text(encoding="utf-8"))
    target = next(f for f in draft["findings"] if f["key"] == "double-charge")
    if mutation == "origin":
        target["origin"] = {"item": 1}
    else:
        target["proof"]["test"] = "src/billing/charge.py::check"
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    completed = subprocess.run(
        [sys.executable, str(checker), "check",
         "--answer", str(draft_path),
         "--items", str(_ANSWER_FIXTURES / "where-to-look.json")],
        capture_output=True, text=True, check=False,
        env=_bundle_env(tmp_path), timeout=120, cwd=isolated,
    )
    assert completed.returncode == 1, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert expected in completed.stderr


@pytest.mark.parametrize("helper", ["sandbox-exec", "bwrap"])
def test_run_confined_gives_the_runner_umask_022_with_either_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, helper: str,
) -> None:
    """The re-run child starts with mask 022 whatever mask this process has (the replay gap)."""
    monkeypatch.setattr(C, "platform_helper", lambda: helper)
    seen: list[dict[str, Any]] = []

    def record(argv: list[str], **kwargs: Any) -> Any:
        seen.append({"argv": list(argv), **kwargs})
        return T.ProcessResult(0, "")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    C.run_confined(["python3", "-c", "pass"], scratch, {"HOME": str(scratch)}, scratch,
                   runner=record, timeout=7)
    assert C.RERUN_UMASK == 0o022
    assert len(seen) == 1
    assert seen[0]["umask"] == 0o022
    assert seen[0]["shell"] is False
    assert seen[0]["timeout"] == 7


@pytest.mark.skipif(os.name != "posix", reason="umask is a POSIX setting")
def test_a_real_rerun_child_gets_022_under_a_parent_umask_of_077(tmp_path: Path) -> None:
    """The real runner gives the child the re-run's mask under a stricter parent mask."""
    made = tmp_path / "made.txt"
    code = f"open({str(made)!r}, 'w').close()"
    previous = os.umask(0o077)
    try:
        result = C.review_tools.subprocess_runner(
            [sys.executable, "-c", code], cwd=tmp_path, env=dict(os.environ), timeout=30,
            shell=False, umask=C.RERUN_UMASK,
        )
        assert os.umask(0o077) == 0o077
    finally:
        os.umask(previous)
    assert result.code == 0
    assert made.stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(os.name != "posix", reason="umask is a POSIX setting")
def test_a_copied_test_file_gets_022_modes_under_a_stricter_parent_mask(tmp_path: Path) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    (source / "tests").mkdir(parents=True)
    (source / "tests" / "test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (source / "tests" / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (source / "tests" / "run.sh").chmod(0o700)
    dest.mkdir()
    previous = os.umask(0o077)
    try:
        assert C._copy_one(source, dest, "tests/test_x.py")
        assert C._copy_one(source, dest, "tests/run.sh")
    finally:
        os.umask(previous)
    assert (dest / "tests" / "test_x.py").stat().st_mode & 0o777 == 0o644
    assert (dest / "tests" / "run.sh").stat().st_mode & 0o777 == 0o755


def test_the_final_worktree_is_checked_out_under_the_rerun_mask(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def runner(argv: list[str], **kwargs: Any) -> Any:
        seen.append(kwargs)
        return T.ProcessResult(1, "", "no")

    assert C._worktree(runner, tmp_path, "HEAD") == (None, None)
    assert seen[0]["umask"] == C.RERUN_UMASK
