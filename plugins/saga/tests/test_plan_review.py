"""Plan review in one pass: record, answer, and the check (issue #163).

These cases exercise the real ``plan_review.py`` command line against staged
records in tmp directories — no network (sockets refused), no ``gh`` (issue
bodies arrive via ``--body-file``), no sibling checkout.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SAGA = ROOT / "plugins" / "saga"
SCRIPTS = SAGA / "scripts"
FIXTURES = SAGA / "tests" / "fixtures" / "plan_review"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


plan_review = _load("plan_review")
build_loop = _load("build_loop")
review_records = _load("review_records")
run_record = _load("run_record")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here runs with sockets refused, so a network call fails the test."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network call in a test that must not make one")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def _no_operator_langfuse(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """No test sees the operator's Langfuse keys, or writes the operator's queue."""
    import os

    for name in list(os.environ):
        if name.startswith(("SAGA_LANGFUSE_", "LANGFUSE_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("operator-home")))


@pytest.fixture()
def staged(tmp_path: Path) -> dict[str, Path]:
    """The fixtures copied to a writable tmp directory."""
    for name in ("plan.md", "body.md", "findings.json", "record.json"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    return {name: tmp_path / name for name in ("plan.md", "body.md", "findings.json", "record.json")}


def finding_ids(staged: dict[str, Path]) -> list[str]:
    raw = json.loads(staged["findings.json"].read_text(encoding="utf-8"))
    return [item["id"] for item in raw]


def record_argv(staged: dict[str, Path]) -> list[str]:
    return [
        "record",
        "--record",
        str(staged["record.json"]),
        "--plan",
        str(staged["plan.md"]),
        "--findings",
        str(staged["findings.json"]),
    ]


def check_argv(staged: dict[str, Path]) -> list[str]:
    return [
        "check",
        "--record",
        str(staged["record.json"]),
        "--body-file",
        str(staged["body.md"]),
    ]


def test_record_answer_check_happy_path(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    """The one-pass flow end to end: record, answer each, the check exits 0."""
    first, second = finding_ids(staged)
    assert plan_review.main(record_argv(staged)) == 0

    assert plan_review.main(check_argv(staged)) == 1
    assert "rollback" in capsys.readouterr().out

    answer_fixed = [
        "answer", "--record", str(staged["record.json"]),
        "--finding", first, "--fixed", "Requirements",
    ]
    assert plan_review.main(answer_fixed) == 2  # the plan has not changed yet
    assert "unchanged" in capsys.readouterr().err
    with staged["plan.md"].open("a", encoding="utf-8") as handle:
        handle.write("\nFixed the rollback gap.\n")
    assert plan_review.main(answer_fixed) == 0

    answer_rejected = [
        "answer", "--record", str(staged["record.json"]),
        "--finding", second, "--rejected", "pinned in R3 already",
    ]
    assert plan_review.main([*answer_rejected[:-1], ""]) == 2  # empty reason refused
    assert "reason" in capsys.readouterr().err
    assert plan_review.main(answer_rejected) == 0

    assert plan_review.main(check_argv(staged)) == 0
    assert "pinned in R3 already" in capsys.readouterr().out


def test_record_refuses_a_code_finding(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    raw = json.loads(staged["findings.json"].read_text(encoding="utf-8"))
    raw[0]["subject"] = "code"
    raw[0]["location"] = {
        "scope": "lines",
        "file": "src/a.py",
        "lines": {"start": 1, "end": 2},
        "function": None,
        "anchor": "x = 1",
    }
    staged["findings.json"].write_text(json.dumps(raw), encoding="utf-8")
    assert plan_review.main(record_argv(staged)) == 2
    err = capsys.readouterr().err
    assert 'subject must be "plan"' in err
    assert "names a plan section" in err


def test_record_refuses_a_handed_in_severity(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    raw = json.loads(staged["findings.json"].read_text(encoding="utf-8"))
    raw[0]["severity"] = "blocks"
    staged["findings.json"].write_text(json.dumps(raw), encoding="utf-8")
    assert plan_review.main(record_argv(staged)) == 2
    assert "severity" in capsys.readouterr().err


def test_record_refuses_a_tampered_identity(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    raw = json.loads(staged["findings.json"].read_text(encoding="utf-8"))
    raw[0]["id"] = "rf:" + "0" * 32
    staged["findings.json"].write_text(json.dumps(raw), encoding="utf-8")
    assert plan_review.main(record_argv(staged)) == 2
    assert "id" in capsys.readouterr().err


def test_record_refuses_a_duplicate_identity(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    raw = json.loads(staged["findings.json"].read_text(encoding="utf-8"))
    staged["findings.json"].write_text(json.dumps([raw[0], raw[0]]), encoding="utf-8")
    assert plan_review.main(record_argv(staged)) == 2
    assert "already used" in capsys.readouterr().err


def test_record_fills_a_missing_identity(staged: dict[str, Path]) -> None:
    raw = json.loads(staged["findings.json"].read_text(encoding="utf-8"))
    for item in raw:
        del item["id"]
    staged["findings.json"].write_text(json.dumps(raw), encoding="utf-8")
    assert plan_review.main(record_argv(staged)) == 0
    record = build_loop.load_record_file(staged["record.json"])
    stored = plan_review.plan_review_entries(record)[-1]["findings"]
    pristine = json.loads((FIXTURES / "findings.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in stored] == [item["id"] for item in pristine]


def test_second_record_on_the_unchanged_plan_is_refused(
    staged: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert plan_review.main(record_argv(staged)) == 0
    assert plan_review.main(record_argv(staged)) == 2
    assert "unchanged since the latest recorded review" in capsys.readouterr().err
    with staged["plan.md"].open("a", encoding="utf-8") as handle:
        handle.write("\nAnother fix.\n")
    assert plan_review.main(record_argv(staged)) == 0
    record = build_loop.load_record_file(staged["record.json"])
    assert len(plan_review.plan_review_entries(record)) == 2


def test_answer_refuses_unknown_and_double(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    first, _second = finding_ids(staged)
    assert plan_review.main(record_argv(staged)) == 0
    base = [
        "answer", "--record", str(staged["record.json"]),
    ]
    assert plan_review.main([*base, "--finding", "rf:" + "f" * 32, "--rejected", "x"]) == 2
    assert "no recorded finding" in capsys.readouterr().err
    assert plan_review.main([*base, "--finding", first, "--rejected", "x"]) == 0
    assert plan_review.main([*base, "--finding", first, "--rejected", "y"]) == 2
    assert "already answered" in capsys.readouterr().err


def test_answer_fixed_needs_a_section(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    first, _second = finding_ids(staged)
    assert plan_review.main(record_argv(staged)) == 0
    with staged["plan.md"].open("a", encoding="utf-8") as handle:
        handle.write("\nA fix.\n")
    argv = [
        "answer", "--record", str(staged["record.json"]),
        "--finding", first, "--fixed", "  ",
    ]
    assert plan_review.main(argv) == 2
    assert "names the plan section" in capsys.readouterr().err


def test_check_names_each_unanswered_finding(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    first, second = finding_ids(staged)
    assert plan_review.main(record_argv(staged)) == 0
    assert plan_review.main(check_argv(staged)) == 1
    out = capsys.readouterr().out
    assert first in out and second in out
    assert "Scope Boundaries" in out and "Requirements" in out


def test_check_fails_on_a_mapping_gap_with_everything_answered(
    staged: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = finding_ids(staged)
    assert plan_review.main(record_argv(staged)) == 0
    base = [
        "answer", "--record", str(staged["record.json"]),
    ]
    with staged["plan.md"].open("a", encoding="utf-8") as handle:
        handle.write("\nA fix.\n")
    assert plan_review.main([*base, "--finding", first, "--fixed", "Scope Boundaries"]) == 0
    assert plan_review.main([*base, "--finding", second, "--rejected", "done"]) == 0
    staged["body.md"].write_text(
        "### Objective\n\nTwo criteria.\n\n### Acceptance criteria\n\n"
        "- [ ] The widget ships.\n- [ ] The gadget ships.\n",
        encoding="utf-8",
    )
    assert plan_review.main(check_argv(staged)) == 1
    assert "AC-2 NOT MAPPED" in capsys.readouterr().out


def test_a_mapping_gap_has_no_answer_path(staged: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert plan_review.main(record_argv(staged)) == 0
    argv = [
        "answer", "--record", str(staged["record.json"]),
        "--finding", "AC-2", "--rejected", "not a real gap",
    ]
    assert plan_review.main(argv) == 2
    assert "no recorded finding 'AC-2'" in capsys.readouterr().err


def test_check_with_no_review_recorded_is_not_ready(
    staged: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert plan_review.main(check_argv(staged)) == 1
    assert "no plan review recorded" in capsys.readouterr().out


def test_check_with_a_missing_plan_is_refused(
    staged: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert plan_review.main(record_argv(staged)) == 0
    staged["plan.md"].unlink()
    assert plan_review.main(check_argv(staged)) == 2
    assert "neither at its stored path" in capsys.readouterr().err


def test_entry_round_trips_with_every_field(staged: dict[str, Path]) -> None:
    assert plan_review.main(record_argv(staged)) == 0
    record = build_loop.load_record_file(staged["record.json"])
    (entry,) = plan_review.plan_review_entries(record)
    assert entry["loop"] == "plan_review"
    assert entry["plan_path"] == str(staged["plan.md"])
    assert entry["plan_sha256"] == plan_review.fingerprint(staged["plan.md"])
    assert entry["reviewed_revision"]
    assert len(entry["findings"]) == 2
    assert entry["answers"] == {}


def test_a_usage_write_between_calls_survives(staged: dict[str, Path], tmp_path: Path) -> None:
    """Each subcommand re-reads under the lock, so another writer's keys survive."""
    store = tmp_path / "store"
    store.mkdir()
    record_file = store / "issue-163.json"
    shutil.copy(staged["record.json"], record_file)
    raw = json.loads(record_file.read_text(encoding="utf-8"))
    raw["units"] = [{"id": "U1"}]
    record_file.write_text(json.dumps(raw), encoding="utf-8")

    staged_findings = json.loads(staged["findings.json"].read_text(encoding="utf-8"))
    plan_review.do_record(record_file, staged["plan.md"], staged_findings)

    def add_usage(record: Any) -> Any:
        record.units[0]["usage"] = {"entries": []}
        return record

    run_record.update(store, 163, add_usage)
    first, _second = finding_ids(staged)
    with staged["plan.md"].open("a", encoding="utf-8") as handle:
        handle.write("\nA fix.\n")
    plan_review.do_answer(record_file, first, fixed="Requirements")
    record = build_loop.load_record_file(record_file)
    assert record.units[0]["usage"] == {"entries": []}
    entries = plan_review.plan_review_entries(record)
    assert entries[0]["answers"][first]["verdict"] == "fixed"


def test_other_review_cycle_readers_ignore_the_entry(staged: dict[str, Path]) -> None:
    release_step = _load("release_step")
    cost_report = _load("cost_report")
    run_status = _load("run_status")
    review_result = _load("review_result")

    raw = json.loads(staged["record.json"].read_text(encoding="utf-8"))
    raw["review_cycles"] = [
        {"schema": "review_result.v2", "loop": "code_review", "unit": "U1", "outcome": "accepted"}
    ]
    staged["record.json"].write_text(json.dumps(raw), encoding="utf-8")

    def readings() -> tuple:
        record = build_loop.load_record_file(staged["record.json"])
        as_dict = run_record.to_dict(record)
        return (
            release_step._code_review_cycles(as_dict),
            cost_report._code_review_history(record, "U1"),
            run_status.latest_review(record, loop="code_review", unit="U1"),
            review_result.history_for(record, "U1", "code_review"),
        )

    before = readings()
    assert before[0] and before[1] and before[2] and before[3]
    assert plan_review.main(record_argv(staged)) == 0
    assert readings() == before


def test_spore_freeze_leaves_plan_review_out_of_the_count(
    staged: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saga_spore = _load("saga_spore")
    store = tmp_path / "store"
    store.mkdir()
    record_file = store / "issue-163.json"
    shutil.copy(staged["record.json"], record_file)
    # Patch the object `saga_spore`'s function-local `import run_record` resolves, which in a
    # full-suite run may be another test module's load of the same file rather than this one's.
    monkeypatch.setattr(
        sys.modules["run_record"], "resolve_store_root", lambda *args, **kwargs: store
    )
    box = {"saga_id": "issue-163"}
    assert saga_spore.freeze_run_record(tmp_path, box)["review_cycles"] == 0
    plan_review.do_record(
        record_file, staged["plan.md"],
        json.loads(staged["findings.json"].read_text(encoding="utf-8")),
    )
    assert saga_spore.freeze_run_record(tmp_path, box)["review_cycles"] == 0


# --- posting to Langfuse (issue 166) ------------------------------------------------------------

_LF = {
    "SAGA_LANGFUSE_PUBLIC_KEY": "pk-lf-SENTINEL-public",
    "SAGA_LANGFUSE_SECRET_KEY": "sk-lf-SENTINEL-secret",
    "SAGA_LANGFUSE_HOST": "https://langfuse.example.test",
}


class _LfResponse:
    status = 200

    def read(self) -> bytes:
        return b"{}"

    def getcode(self) -> int:
        return 200

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _LfOpener:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return _LfResponse()


def _lf_env(monkeypatch: pytest.MonkeyPatch, **over: str) -> None:
    for name, value in {**_LF, **over}.items():
        monkeypatch.setenv(name, value)


def _queued(home: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in sorted((home / ".saga" / "langfuse-queue").glob("*.json"))]


def test_plan_record_posts_trace(staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _lf_env(monkeypatch)
    opener = _LfOpener()
    assert plan_review.main(record_argv(staged), trace_opener=opener) == 0
    [request] = opener.requests
    assert request.full_url.endswith("/api/public/otel/v1/traces")
    body = json.loads(request.data.decode())
    spans = body["resourceSpans"][0]["scopeSpans"][0]["spans"]
    trace = spans[0]["traceId"]
    ids = finding_ids(staged)
    review_trace = sys.modules["review_trace"]
    assert {span["spanId"] for span in spans if span["name"] == "finding"} == {
        review_trace.span_id(trace, f"finding:{identity}") for identity in ids}
    assert str(staged["plan.md"].parent) not in request.data.decode()


def test_plan_answer_posts_score(staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _lf_env(monkeypatch)
    assert plan_review.main(record_argv(staged), trace_opener=_LfOpener()) == 0
    first = finding_ids(staged)[0]
    opener = _LfOpener()
    argv = ["answer", "--record", str(staged["record.json"]), "--finding", first, "--rejected", "out of scope"]
    assert plan_review.main(argv, trace_opener=opener) == 0
    [request] = opener.requests
    score = json.loads(request.data.decode())
    assert (score["name"], score["value"], score["dataType"], score["comment"]) == (
        "plan-answer", "rejected", "CATEGORICAL", "out of scope")
    review_trace = sys.modules["review_trace"]
    assert score["observationId"] == review_trace.span_id(score["traceId"], f"finding:{first}")


def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _plan_repo(tmp: Path, *, main_profile: dict[str, Any], branch_profile: dict[str, Any]) -> Path:
    repo = tmp / "plan-repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "plan@example.com")
    _git(repo, "config", "user.name", "plan")
    (repo / ".saga-profile.json").write_text(json.dumps(main_profile), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main")
    _git(repo, "checkout", "-q", "-b", "plan")
    (repo / ".saga-profile.json").write_text(json.dumps(branch_profile), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "plan branch marks itself public")
    return repo


def test_plan_review_visibility_from_merge_base(
    staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _plan_repo(tmp_path, main_profile={"schema": "repository_profile.v1"},
                      branch_profile={"visibility": "public"})
    review_trace = sys.modules.get("review_trace") or _load("review_trace")
    assert review_trace.plan_visibility(repo) is None
    plan = repo / "plan.md"
    shutil.copy(staged["plan.md"], plan)
    _lf_env(monkeypatch, SAGA_LANGFUSE_HOST="http://langfuse.example.test")
    opener = _LfOpener()
    argv = ["record", "--record", str(staged["record.json"]), "--plan", str(plan),
            "--findings", str(staged["findings.json"])]
    assert plan_review.main(argv, trace_opener=opener) == 0
    assert opener.requests == []
    import os

    [queued] = _queued(Path(os.environ["HOME"]))
    assert queued["reason"] == "plain-http-private"
    public = _plan_repo(tmp_path / "second", main_profile={"visibility": "public"},
                        branch_profile={"visibility": "private"})
    assert review_trace.plan_visibility(public) == "public"


def test_plan_review_langfuse_failure_keeps_record(
    staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import urllib.error

    good = tmp_path / "good"
    good.mkdir()
    for name, path in staged.items():
        shutil.copy(path, good / name)
    good_argv = ["record", "--record", str(good / "record.json"), "--plan", str(good / "plan.md"),
                 "--findings", str(good / "findings.json")]
    _lf_env(monkeypatch)
    assert plan_review.main(good_argv, trace_opener=_LfOpener()) == 0
    code = plan_review.main(record_argv(staged), trace_opener=_LfOpener(urllib.error.URLError("down")))
    assert code == 0
    stored = json.loads(staged["record.json"].read_text())["review_cycles"][-1]
    expected = json.loads((good / "record.json").read_text())["review_cycles"][-1]
    for key in ("loop", "plan_sha256", "findings", "answers"):
        assert stored[key] == expected[key]
    import os

    assert len(_queued(Path(os.environ["HOME"]))) == 1
