"""Private failure evidence survives retries without changing review outcomes."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("diagnostic_review_tools", SCRIPTS / "review_tools.py")
assert _SPEC is not None and _SPEC.loader is not None
T = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = T
_SPEC.loader.exec_module(T)
D = T.review_diagnostics


def _adapter() -> Any:
    return T.Adapter(
        id="cargo-mutants", tool="fixture", invoke=lambda _context: ["fixture"],
        parse=lambda _text: T.ParseResult(), rows=("testing.surviving-mutant",),
        lens="testing", comparison="lines", mutation=True,
        report_file="mutants.out/outcomes.json", exit_reasons=((4, "baseline-failed"),),
        retry_failures=("baseline-failed",),
    )


@pytest.mark.parametrize("retry", ["failure", "timeout", "success", "budget"])
def test_initial_and_retry_evidence_survive_independently(tmp_path: Path, retry: str) -> None:
    scan = tmp_path / "scan"
    scan.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    diagnostics = tmp_path / "diagnostics"
    context = T.ScanContext(scan, scan, home, diagnostics_directory=diagnostics)
    calls = 0

    def process(argv: list[str], **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        folder = scan / "mutants.out"
        (folder / "log").mkdir(parents=True, exist_ok=True)
        (folder / "log" / "baseline.log").write_text(f"attempt {calls} test failure")
        (folder / "outcomes.json").write_text(json.dumps({"outcomes": [{
            "scenario": "Baseline", "summary": "Failure", "log_path": "log/baseline.log",
        }]}))
        if calls == 1 and retry == "budget":
            time.sleep(1.1)  # the first attempt spends what was left of the one-second budget
        if calls == 2 and retry == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output=b"retry partial", stderr=b"retry error")
        return T.ProcessResult(0 if calls == 2 and retry == "success" else 4,
                               f"console {calls}", f"stderr {calls}")

    # The budget case returns after the deadline, so the initial attempt is capped.
    deadline = time.monotonic() + (1 if retry == "budget" else 30)
    degraded: list[Any] = []
    T._once(_adapter(), context, process, {}, 5, "head", degraded, [], deadline)
    attempts = {}
    for path in diagnostics.glob("*/attempt.json"):
        record = json.loads(path.read_text())
        attempts[record["attempt"]] = (path.parent, record)
        assert record["elapsed_seconds"] >= 0
        assert record["remaining_budget_seconds"] >= 0
    initial_path, initial = attempts["initial"]
    assert initial["status"] == "failed"
    assert initial["reason"] == ("cap" if retry == "budget" else "baseline-failed")
    assert (initial_path / "stdout.txt").read_text() == "console 1"
    baseline = next(initial_path.glob("baseline-*.log"))
    assert baseline.read_text() == "attempt 1 test failure"
    if retry == "budget":
        assert "retry" not in attempts
    else:
        retry_path, record = attempts["retry"]
        expected = {"failure": ("failed", "baseline-failed"), "timeout": ("failed", "timeout"),
                    "success": ("succeeded", None)}
        assert (record["status"], record["reason"]) == expected[retry]
    assert calls == (1 if retry == "budget" else 2)
    reason = {"success": "baseline-flaky", "budget": "cap"}.get(retry, "baseline-failed")
    assert degraded[0]["reason"] == reason
    if retry == "timeout":
        assert (retry_path / "stdout.txt").read_bytes() == b"retry partial"
    assert diagnostics.stat().st_mode & 0o777 == 0o700
    for path in diagnostics.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)


@pytest.mark.parametrize("setup,cleanup,expected,late", [
    (50, 25, 25, False), (50, 25, 25, True), (100, 0, None, False), (50, 50, None, False),
])
def test_retry_obeys_deadline_after_setup_and_report_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setup: int, cleanup: int,
    expected: int | None, late: bool,
) -> None:
    scan, home = tmp_path / "scan", tmp_path / "home"
    scan.mkdir()
    home.mkdir()
    clock = [0.0]
    monkeypatch.setattr(T.time, "monotonic", lambda: clock[0])
    invocations = [0]
    calls: list[float] = []
    remove_tree = T._remove_tree

    def invoke(_context: Any) -> list[str]:
        invocations[0] += 1
        if invocations[0] == 2:
            clock[0] += setup
        return ["fixture"]

    def remove(path: Path) -> None:
        if invocations[0] == 2:
            clock[0] += cleanup
        remove_tree(path)

    monkeypatch.setattr(T, "_remove_tree", remove)

    def process(_argv: list[str], **kwargs: Any) -> Any:
        calls.append(kwargs["timeout"])
        report = scan / "mutants.out" / "outcomes.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text('{"outcomes": []}', encoding="utf-8")
        if len(calls) == 1:
            clock[0] = 100
            return T.ProcessResult(4, "baseline failed")
        if late:
            clock[0] += 50
        return T.ProcessResult(0, "success")

    adapter = replace(_adapter(), invoke=invoke)
    degraded: list[Any] = []
    hits, digests = T._once(adapter, T.ScanContext(scan, scan, home), process, {},
                            200, "head", degraded, [], 200)
    assert hits == ()
    if expected is None or late:
        if late:
            assert calls == [200, expected]
        else:
            assert len(calls) == 1
        assert digests == {}
        assert [entry["reason"] for entry in degraded] == ["cap"]
    else:
        assert calls == [200, expected]
        assert digests
        assert [entry["reason"] for entry in degraded] == ["baseline-flaky"]


@pytest.mark.skipif(os.name != "posix", reason="safe descriptor reads are POSIX")
def test_report_cannot_redirect_log_reads_outside_scan_root(tmp_path: Path) -> None:
    scan = tmp_path / "scan"
    logs = scan / "mutants.out" / "log"
    logs.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "private.txt"
    sentinel.write_text("MUST_NOT_BE_COPIED")
    (logs / "link").symlink_to(sentinel)
    (logs / "directory-link").symlink_to(outside, target_is_directory=True)
    os.mkfifo(logs / "fifo")
    entries = [str(sentinel), "../../outside/private.txt", "log/link",
               "log/directory-link/private.txt", "log/fifo"]
    (scan / "mutants.out" / "outcomes.json").write_text(json.dumps({
        "outcomes": [{"scenario": "Baseline", "log_path": path} for path in entries],
    }))
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.logs(scan)
    attempt.finish("failed", "baseline-failed", 4)
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["rejected_logs"] == len(entries)
    assert record["errors"] == ["baseline-log-unavailable-or-refused"]
    assert not list(attempt.directory.glob("baseline-*.log"))


def test_retained_artifacts_have_a_total_byte_and_file_bound(tmp_path: Path) -> None:
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.console("x" * (D.MAX_BYTES * 2), "y" * D.MAX_BYTES)
    for index in range(12):
        attempt.keep(f"fixture-{index}", b"z" * 65536)
    attempt.finish("failed", "baseline-failed", 4)
    paths = list(attempt.directory.iterdir())
    assert len(paths) <= D.MAX_FILES
    assert sum(path.stat().st_size for path in paths) <= D.MAX_BYTES
    metadata = json.loads((attempt.directory / "attempt.json").read_text())
    assert metadata["artifacts"]["stdout.txt"]["truncated"] is True


def test_unavailable_capture_is_private_telemetry_not_a_scan_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    refused = tmp_path / "diagnostics"
    refused.write_text("a file cannot be a diagnostics directory")
    context = T.ScanContext(tmp_path, tmp_path, tmp_path, diagnostics_directory=refused)
    adapter = _adapter()
    adapter = T.replace(adapter, report_file=None)
    degraded: list[Any] = []
    T._once(adapter, context, lambda *_args, **_kwargs: T.ProcessResult(0, "ok"),
            {}, 5, "head", degraded, [])
    assert degraded == []
    assert "private directory unavailable or refused" in capsys.readouterr().err


def test_artifact_failure_is_recorded_without_changing_status(tmp_path: Path) -> None:
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    (attempt.directory / "stdout.txt").write_text("existing")
    attempt.console("new", "error")
    attempt.finish("succeeded", None, 0)
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["status"] == "succeeded"
    assert record["errors"] == ["artifact-write-failed"]


def test_unsupported_safe_open_refuses_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = tmp_path / "scan"
    report = scan / "mutants.out" / "outcomes.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"outcomes": []}')
    monkeypatch.setattr(D.os, "supports_dir_fd", set())
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.logs(scan)
    attempt.finish("succeeded", None, 0)
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["errors"] == ["report-unavailable-or-refused"]
    assert not (attempt.directory / "outcomes.json").exists()


def test_pathological_report_is_bounded_and_not_allowed_to_abort_capture(tmp_path: Path) -> None:
    scan = tmp_path / "scan"
    report = scan / "mutants.out" / "outcomes.json"
    report.parent.mkdir(parents=True)
    report.write_text("[" * 2000 + "0" + "]" * 2000)
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.logs(scan)
    attempt.finish("failed", "baseline-failed", 4)
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["errors"] == ["report-unparseable"]


@pytest.mark.parametrize("log_path", ["log/baseline\0.log", "log/\ud800.log"], ids=["nul", "surrogate"])
def test_invalid_log_representation_preserves_the_production_scan_result(
    tmp_path: Path, log_path: str,
) -> None:
    scan = tmp_path / "scan"
    folder = scan / "mutants.out"
    (folder / "log").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    diagnostics = tmp_path / "diagnostics"
    report = json.dumps({"outcomes": [{
        "scenario": "Baseline", "summary": "Failure", "log_path": log_path,
    }]})

    def process(_argv: list[str], **_kwargs: Any) -> Any:
        (folder / "outcomes.json").write_text(report)
        return T.ProcessResult(4, "baseline failed", "test failed")

    observations = []
    for directory in (None, diagnostics):
        context = T.ScanContext(scan, scan, home, diagnostics_directory=directory)
        degraded: list[Any] = []
        result = T._once(_adapter(), context, process, {}, 5, "head", degraded, [])
        assert [item["reason"] for item in degraded] == ["baseline-failed"]
        assert degraded[0]["raw_output"]
        observations.append((result, degraded))
    assert observations[0] == observations[1]
    records = list(diagnostics.glob("*/attempt.json"))
    assert len(records) == 2
    for path in records:
        record = json.loads(path.read_text())
        assert record["status"] == "failed" and record["reason"] == "baseline-failed"
        assert record["rejected_logs"] == 1
        assert record["errors"] == ["baseline-log-unavailable-or-refused"]
        assert not list(path.parent.glob("baseline-*.log"))


@pytest.mark.parametrize("source", [
    b"", b"x", b"\xff\0raw bytes", "λ" * 200,
    b"x" * 65535, b"x" * 65536, b"begin\n" + b"x" * 65536 + b"\nterminal failure",
    "begin\n" + "λ" * 40000 + "\nterminal failure",
])
def test_console_text_is_exact_when_small_and_preserves_both_ends_when_large(
    tmp_path: Path, source: str | bytes,
) -> None:
    expected = source.encode("utf-8") if isinstance(source, str) else source
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.console(source, None)
    attempt.finish("failed", "baseline-failed", 4)
    data = (attempt.directory / "stdout.txt").read_bytes()
    record = json.loads((attempt.directory / "attempt.json").read_text())["artifacts"]["stdout.txt"]
    assert record["original_bytes"] == len(expected)
    assert record["observed_bytes"] == len(expected)
    assert record["source_changed"] is False
    if len(expected) <= 65536:
        assert data == expected
        assert record["sample_mode"] == "full" and record["complete"] is True
        assert record["truncated"] is False
    else:
        assert len(data) == 65536
        assert data.startswith(b"begin\n") and data.endswith(b"\nterminal failure")
        assert D._OMISSION in data
        assert record["sample_mode"] == "head-tail" and record["complete"] is False
        assert record["truncated"] is True
        start, end = record["omitted_start"], record["omitted_end"]
        assert expected[:start] + D._OMISSION + expected[end:] == data


@pytest.mark.parametrize("limit", [0, 1, 2, len(D._OMISSION) + 1, len(D._OMISSION) + 2])
def test_small_remaining_budget_prioritizes_terminal_text(tmp_path: Path, limit: int) -> None:
    source = b"initial line\n" + b"chatter\n" * 100 + b"terminal failure"
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.retained = D.MAX_BYTES - D._METADATA_RESERVE - limit
    attempt.console(source, None)
    data = (attempt.directory / "stdout.txt").read_bytes()
    record = attempt.artifacts["stdout.txt"]
    assert len(data) <= limit
    assert record["original_bytes"] == len(source)
    assert record["complete"] is False and record["truncated"] is True
    if limit < len(D._OMISSION) + 2:
        assert data == (source[-limit:] if limit else b"")
        assert record["sample_mode"] == ("tail-only" if limit else "no-text")
        assert record["omitted_start"] == 0 and record["omitted_end"] == len(source) - limit
    else:
        assert data.startswith(source[:1]) and data.endswith(source[-1:])
        assert D._OMISSION in data and record["sample_mode"] == "head-tail"


def test_real_tool_large_console_and_baseline_preserve_terminal_diagnostics(tmp_path: Path) -> None:
    scan = tmp_path / "scan"
    scan.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    diagnostics = tmp_path / "diagnostics"
    code = """import json,sys
from pathlib import Path
folder=Path('mutants.out'); (folder/'log').mkdir(parents=True,exist_ok=True)
(folder/'log/baseline.log').write_bytes(b'baseline head\\n'+b'build chatter\\n'*200000+b'baseline terminal failure\\n')
(folder/'outcomes.json').write_text(json.dumps({'outcomes':[{'scenario':'Baseline','summary':'Failure','log_path':'log/baseline.log'}]}))
sys.stdout.write('stdout head\\n'+'build chatter\\n'*200000+'stdout terminal failure\\n')
sys.stderr.write('stderr head\\n'+'build chatter\\n'*200000+'stderr terminal failure\\n')
raise SystemExit(4)
"""
    adapter = T.replace(_adapter(), invoke=lambda _context: [sys.executable, "-c", code])
    context = T.ScanContext(scan, scan, home, diagnostics_directory=diagnostics)
    degraded: list[Any] = []
    T._once(adapter, context, T.subprocess_runner, dict(os.environ), 10, "head", degraded, [])
    assert [entry["reason"] for entry in degraded] == ["baseline-failed"]
    records = list(diagnostics.glob("*/attempt.json"))
    assert len(records) == 2
    for path in records:
        record = json.loads(path.read_text())
        for name, stem in (("stdout.txt", b"stdout"), ("stderr.txt", b"stderr")):
            data = (path.parent / name).read_bytes()
            assert data.startswith(stem + b" head\n") and data.endswith(stem + b" terminal failure\n")
            assert D._OMISSION in data
            assert record["artifacts"][name]["sample_mode"] == "head-tail"
        log = next(path.parent.glob("baseline-*.log"))
        data = log.read_bytes()
        assert data.startswith(b"baseline head\n") and data.endswith(b"baseline terminal failure\n")
        assert record["artifacts"][log.name]["complete"] is False
        assert record["artifacts"][log.name]["original_bytes"] > len(data)
        # The outcomes report remains an exact JSON report, not a text sample.
        assert json.loads((path.parent / "outcomes.json").read_text())["outcomes"]
        assert "sample_mode" not in record["artifacts"]["outcomes.json"]
        assert len(list(path.parent.iterdir())) <= D.MAX_FILES
        assert sum(item.stat().st_size for item in path.parent.iterdir()) <= D.MAX_BYTES


def test_sparse_baseline_reads_only_bounded_head_and_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "large.log"
    size = 1024 * 1024 * 1024
    with log.open("wb") as handle:
        handle.write(b"sparse head\n")
        handle.seek(size - len(b"terminal failure\n"))
        handle.write(b"terminal failure\n")
    real_open = D._open_owned
    reads: list[int] = []
    seeks: list[int] = []

    class Tracked:
        def __init__(self, handle: Any) -> None:
            self.handle = handle

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: Any) -> None:
            self.handle.close()

        def fileno(self) -> int:
            return self.handle.fileno()

        def read(self, count: int) -> bytes:
            assert 0 <= count <= 65536
            reads.append(count)
            return self.handle.read(count)

        def seek(self, offset: int) -> int:
            assert 0 <= offset < size
            seeks.append(offset)
            return self.handle.seek(offset)

    def tracked(root: Path, relative: str) -> Any:
        handle = real_open(root, relative)
        return Tracked(handle) if handle is not None else None

    monkeypatch.setattr(D, "_open_owned", tracked)
    sample = D._read_owned_text(tmp_path, "large.log", 65536)
    assert sample is not None
    assert sample.data.startswith(b"sparse head\n") and sample.data.endswith(b"terminal failure\n")
    assert len(sample.data) == 65536
    assert len(reads) == 2 and sum(reads) <= 65536 and len(seeks) == 1
    assert sample.metadata()["original_bytes"] == size
    assert sample.metadata()["source_changed"] is False


def test_changing_file_does_not_claim_complete_or_stable_offsets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "changing.log"
    path.write_bytes(b"initial diagnostic")
    real_fstat = D.os.fstat
    calls = 0

    def changed(descriptor: int) -> Any:
        nonlocal calls
        calls += 1
        info = real_fstat(descriptor)
        if calls == 2:  # after the safe-open regular-file check and size snapshot
            with path.open("ab") as handle:
                handle.write(b"new terminal diagnostic")
        return info

    monkeypatch.setattr(D.os, "fstat", changed)
    sample = D._read_owned_text(tmp_path, "changing.log", 65536)
    assert sample is not None
    metadata = sample.metadata()
    assert metadata["source_changed"] is True
    assert metadata["complete"] is False and metadata["truncated"] is True
    assert metadata["original_bytes"] is None
    assert metadata["omitted_start"] is None and metadata["omitted_end"] is None


def test_outcomes_json_keeps_its_existing_prefix_capture_contract(tmp_path: Path) -> None:
    scan = tmp_path / "scan"
    report = scan / "mutants.out" / "outcomes.json"
    report.parent.mkdir(parents=True)
    content = json.dumps({"outcomes": [], "padding": "x" * 100000, "terminal": "JSON-END"}).encode()
    report.write_bytes(content)
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.logs(scan)
    attempt.finish("failed", "baseline-failed", 4)
    assert (attempt.directory / "outcomes.json").read_bytes() == content[:65536]
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["artifacts"]["outcomes.json"]["truncated"] is True
    assert "sample_mode" not in record["artifacts"]["outcomes.json"]
    assert record["errors"] == ["report-truncated"]
