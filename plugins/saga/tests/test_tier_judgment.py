"""Tests for the tier judgment's saga glue and ``/plan`` commands (issue #96).

Every consult runs saga's real bundled staffing component with an injected ``ask``; nothing here
reaches the network, and every record and verdict log lands in ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tj() -> ModuleType:
    return _load("tier_judgment")


@pytest.fixture
def rr() -> ModuleType:
    return _load("run_record")


@pytest.fixture
def staffing(tj: ModuleType) -> Any:
    loaded = tj.load_staffing()
    if loaded is None:
        pytest.skip("saga's bundled staffing component is not reachable")
    return loaded


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store" / "runs"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    return root


UNITS = [
    {"id": "U1", "goal": "rotate the IAM signing key", "files": ["plugins/x/key.py"]},
    {"id": "U2", "goal": "rename a constant", "files": ["plugins/x/names.py"]},
    {"id": "U3", "goal": "survey call sites", "files": [], "work_shape": "read-only-survey"},
]


def _ask(answers: dict[str, tuple[str, float]], calls: list[dict[str, Any]]) -> Any:
    def ask(state: Any, questions: Any, **options: Any) -> Any:
        calls.append({"state": state, "questions": questions, "options": options})
        out = {}
        for key in questions:
            unit = key.split("__")[0]
            choice, confidence = answers.get(unit, ("same", 0.9))
            out[key] = {"type": "choice", "choice": choice, "confidence": confidence}
        return SimpleNamespace(status="ok", answers=out, model="jev-1.13.0", note="")

    return ask


def _seed(rr: ModuleType, store: Path, rows: list[dict[str, Any]] | None = None) -> None:
    record = rr.RunRecord(issue=96, repo="o/r", units=rows or [])
    rr.save(store, record)


def _plan(
    tj: ModuleType,
    staffing: Any,
    store: Path,
    repo_root: Path,
    answers: dict[str, tuple[str, float]],
    calls: list[dict[str, Any]],
    **overrides: Any,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "store_root": store,
        "units": UNITS,
        "title": "Rotate the key",
        "body": "Touches IAM and the token endpoint.",
        "staffing": staffing,
        "root": repo_root,
        "ask": _ask(answers, calls),
        "getenv": lambda _name: None,
    }
    kwargs.update(overrides)
    result: dict[str, Any] = tj.run_plan(96, "o/r", **kwargs)
    return result


def test_issue_state_sends_the_four_keyword_flags_and_never_widens(
    tj: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    parse_issue = _load("parse_issue")

    def _widen(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("issue_state must not make a second request")

    monkeypatch.setattr(parse_issue, "widen_flags", _widen)
    state = tj.issue_state("Title", "Rotate the IAM key behind the token endpoint.")

    assert state["title"] == "Title"
    assert state["body"] == "Rotate the IAM key behind the token endpoint."
    assert set(state["flags"]) == {"has_security", "has_api", "has_infra", "has_privacy"}
    assert state["flags"]["has_security"] is True


def _entries(tj: ModuleType, rr: ModuleType, store: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = tj.plan_judgments(rr.load(store, 96, warn=None))
    return result


def test_plan_makes_one_request_and_records_each_unit_under_tier_judgments(
    tj: ModuleType, rr: ModuleType, staffing: Any, store: Path, repo_root: Path
) -> None:
    _seed(rr, store, [{"name": "U2", "branch": "issue/96-u2"}])
    calls: list[dict[str, Any]] = []
    result = _plan(
        tj, staffing, store, repo_root, {"U1": ("above", 0.85), "U2": ("below", 0.95)}, calls
    )

    assert len(calls) == 1
    assert set(calls[0]["questions"]) == {"U1__direction", "U2__direction", "U3__direction"}
    tasks = calls[0]["state"]["tasks"]
    assert tasks["U1"]["goal"] == "rotate the IAM signing key"
    assert tasks["U1"]["files"] == ["plugins/x/key.py"]
    assert tasks["U1"]["work_shape"] == "implementation"
    assert tasks["U1"]["default_tier"] == "opus/medium"
    assert tasks["U3"]["default_tier"] == "sonnet/low"
    assert calls[0]["state"]["issue"]["flags"]["has_security"] is True

    rows = {row["id"]: row for row in result["units"]}
    assert rows["U1"]["band"] == "auto-raise"
    assert rows["U1"]["tier"] == {"model": "opus", "effort": "high"}
    assert rows["U2"]["band"] == "advisory-lower"
    assert rows["U2"]["tier"] == {"model": "opus", "effort": "medium"}

    record = rr.load(store, 96, warn=None)
    assert record.units == [{"name": "U2", "branch": "issue/96-u2"}], (
        "the units rows belong to the writers that run units; the judgment never touches them"
    )
    by_key = _entries(tj, rr, store)
    assert set(by_key) == {"U1", "U2", "U3"}
    assert "jev_raise" not in by_key["U2"]
    raise_ = by_key["U1"]["jev_raise"]
    assert (raise_["model"], raise_["effort"]) == ("opus", "high")
    assert raise_["decision_id"] == "staffing/tier-direction:o/r#96:unit:U1"
    assert by_key["U3"]["tier_judgment"]["band"] == "agrees"


def test_a_recorded_unit_raise_is_what_work_resolves(
    tj: ModuleType, rr: ModuleType, staffing: Any, store: Path, repo_root: Path
) -> None:
    _seed(rr, store)
    _plan(tj, staffing, store, repo_root, {"U1": ("above", 0.85)}, [])
    raise_ = _entries(tj, rr, store)["U1"]["jev_raise"]
    lifecycle_state = _load("lifecycle_state")
    resolved = lifecycle_state.resolve_build_unit_tier(root=repo_root, jev_raise=raise_)
    assert (resolved["model"], resolved["effort"]) == ("opus", "high")


def test_plan_with_the_off_switch_makes_no_request_and_writes_nothing(
    tj: ModuleType, rr: ModuleType, staffing: Any, store: Path, repo_root: Path
) -> None:
    _seed(rr, store)
    calls: list[dict[str, Any]] = []
    result = _plan(
        tj,
        staffing,
        store,
        repo_root,
        {"U1": ("above", 0.95)},
        calls,
        getenv=lambda name: "off" if name == "INFIQUETRA_TYPESAFE_TIERING" else None,
    )

    assert calls == []
    assert result["status"] == "off"
    assert all(row["band"] == "not-consulted" for row in result["units"])
    assert result["units"][0]["tier"] == {"model": "opus", "effort": "medium"}
    assert "tier_judgments" not in rr.load(store, 96, warn=None).extra


def test_a_failed_plan_consult_keeps_an_earlier_raise(
    tj: ModuleType, rr: ModuleType, staffing: Any, store: Path, repo_root: Path
) -> None:
    _seed(rr, store)
    _plan(tj, staffing, store, repo_root, {"U1": ("above", 0.85)}, [])

    def failing(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(status="error", answers={}, model="", note="down")

    result = _plan(tj, staffing, store, repo_root, {}, [], ask=failing)
    assert result["status"] == "error"
    assert _entries(tj, rr, store)["U1"]["jev_raise"]["effort"] == "high"


def test_plan_refuses_without_a_run_record(
    tj: ModuleType, staffing: Any, store: Path, repo_root: Path
) -> None:
    with pytest.raises(tj.TierJudgmentError, match="admission"):
        _plan(tj, staffing, store, repo_root, {}, [])


def test_label_writes_planned_tier_and_logs_each_verdict_once(
    tj: ModuleType, rr: ModuleType, staffing: Any, store: Path, repo_root: Path, tmp_path: Path
) -> None:
    _seed(rr, store)
    _plan(tj, staffing, store, repo_root, {"U1": ("above", 0.85), "U2": ("above", 0.7)}, [])
    log_dir = tmp_path / "typesafe"
    finals = {"U1": "opus/high", "U2": "opus/medium", "U3": "sonnet/low"}

    logged = tj.run_label(96, store_root=store, finals=finals, staffing=staffing, log_dir=log_dir)
    assert logged == {"U1": "above", "U2": "same", "U3": "same"}

    u1 = _entries(tj, rr, store)["U1"]
    assert u1["planned_tier"] == {"model": "opus", "effort": "high"}
    assert u1["tier_judgment"]["labeled"] == "above"
    lines = (log_dir / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()
    verdicts = {json.loads(line)["decision_id"]: json.loads(line) for line in lines}
    assert verdicts["staffing/tier-direction:o/r#96:unit:U1"]["label"] == "above"
    assert verdicts["staffing/tier-direction:o/r#96:unit:U2"]["label"] == "same"
    assert verdicts["staffing/tier-direction:o/r#96:unit:U1"]["state_hash"] == (
        u1["tier_judgment"]["state_hash"]
    )

    again = tj.run_label(96, store_root=store, finals=finals, staffing=staffing, log_dir=log_dir)
    assert again == {}
    assert (log_dir / "verdicts.jsonl").read_text(encoding="utf-8").splitlines() == lines


def test_label_records_a_unit_the_judgment_never_saw_and_refuses_a_malformed_tier(
    tj: ModuleType, rr: ModuleType, staffing: Any, store: Path
) -> None:
    """With the judgment off, ``plan`` writes nothing; ``label`` still records the final tier."""
    _seed(rr, store)
    assert tj.run_label(96, store_root=store, finals={"U9": "opus/high"}, staffing=staffing) == {}
    assert _entries(tj, rr, store) == {"U9": {"planned_tier": {"model": "opus", "effort": "high"}}}
    assert rr.load(store, 96, warn=None).units == []
    with pytest.raises(tj.TierJudgmentError, match="model/effort"):
        tj.run_label(96, store_root=store, finals={"U1": "opus"}, staffing=staffing)


def test_a_tier_judgments_entry_survives_another_writers_record_update(
    tj: ModuleType, rr: ModuleType, staffing: Any, store: Path, repo_root: Path
) -> None:
    _seed(rr, store)
    _plan(tj, staffing, store, repo_root, {"U1": ("above", 0.85)}, [])
    rr.set_next_step(store, 96, "work")
    assert _entries(tj, rr, store)["U1"]["jev_raise"]["effort"] == "high"


def test_the_raise_command_prints_the_recorded_raise_or_null(
    tj: ModuleType,
    rr: ModuleType,
    staffing: Any,
    store: Path,
    repo_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(rr, store)
    _plan(tj, staffing, store, repo_root, {"U1": ("above", 0.85)}, [])
    argv = ["raise", "--issue", "96", "--store-root", str(store)]
    assert tj.main([*argv, "--unit", "U1"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["model"], printed["effort"]) == ("opus", "high")
    assert tj.main([*argv, "--unit", "U2"]) == 0
    assert json.loads(capsys.readouterr().out) is None


def test_the_command_line_exits_2_on_a_malformed_units_file_or_a_missing_record(
    tj: ModuleType, store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "units.json"
    bad.write_text(json.dumps([{"goal": "no id"}]), encoding="utf-8")
    argv = ["plan", "--issue", "96", "--repo", "o/r", "--store-root", str(store)]
    assert tj.main([*argv, "--units", str(bad)]) == 2
    assert "every unit needs an id" in capsys.readouterr().err

    final = tmp_path / "final.json"
    final.write_text(json.dumps({"U1": "opus/high"}), encoding="utf-8")
    assert tj.main(["label", "--issue", "96", "--final", str(final), "--store-root", str(store)])
    assert "no run record" in capsys.readouterr().err


def test_the_plan_command_runs_end_to_end_with_the_judgment_off(
    tj: ModuleType,
    rr: ModuleType,
    store: Path,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The saga conftest switches the judgment off, so the real command line prints every unit
    at its default and writes nothing; the issue is read through admission's reader."""
    admission = _load("admission")
    monkeypatch.setattr(
        admission, "fetch_issue", lambda *_a, **_k: {"title": "T", "body": "B", "number": 96}
    )
    _seed(rr, store)
    units = tmp_path / "units.json"
    units.write_text(json.dumps(UNITS), encoding="utf-8")

    code = tj.main(
        [
            "plan",
            "--issue",
            "96",
            "--repo",
            "o/r",
            "--units",
            str(units),
            "--store-root",
            str(store),
            "--repo-root",
            str(repo_root),
        ]
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "off"
    assert [row["tier"] for row in printed["units"]] == [
        {"model": "opus", "effort": "medium"},
        {"model": "opus", "effort": "medium"},
        {"model": "sonnet", "effort": "low"},
    ]
    assert "tier_judgments" not in rr.load(store, 96, warn=None).extra


# ---------------------------------------------------------------------------
# Issue #133: /work pipes the recorded raise into --jev-raise - instead of quoting it.
# ---------------------------------------------------------------------------

WORK_DOCS = [
    REPO_ROOT / "plugins" / "saga" / "skills" / "work" / "SKILL.md",
    REPO_ROOT / "plugins" / "saga" / "skills" / "work" / "references" / "execution-strategy.md",
]


def _resolve_tier(cwd: Path, *args: str, stdin: str | None = None) -> Any:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "lifecycle_state.py"), "resolve-build-unit-tier", *args],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_work_pipes_a_raise_whose_reason_holds_a_single_quote_into_the_resolver(
    tj: ModuleType, rr: ModuleType, staffing: Any, store: Path, repo_root: Path
) -> None:
    """The command the skill names, as a shell runs it: ``tier_judgment.py raise | ... -``."""
    _seed(rr, store)
    _plan(tj, staffing, store, repo_root, {"U1": ("above", 0.85)}, [])
    record = rr.load(store, 96, warn=None)
    record.extra["tier_judgments"]["U1"]["jev_raise"]["reason"] = "it's '; echo pwned; '"
    rr.save(store, record)

    pipeline = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(SCRIPTS / 'tier_judgment.py'))} raise "
        f"--issue 96 --unit {{unit}} --store-root {shlex.quote(str(store))} | "
        f"{shlex.quote(sys.executable)} {shlex.quote(str(SCRIPTS / 'lifecycle_state.py'))} "
        "resolve-build-unit-tier --explain --jev-raise -"
    )
    raised = subprocess.run(
        pipeline.format(unit="U1"),
        shell=True,  # the point is the shell pipeline the skill names
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert raised.returncode == 0, raised.stderr
    assert "pwned" not in raised.stdout
    assert json.loads(raised.stdout) == {"model": "opus", "effort": "high", "source": "jev-raise"}

    none = subprocess.run(
        pipeline.format(unit="U2"),
        shell=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert none.returncode == 0, none.stderr
    assert json.loads(none.stdout)["source"] != "jev-raise"


def test_the_jev_raise_argument_form_still_reads_trusted_json(repo_root: Path) -> None:
    raise_ = json.dumps({"model": "opus", "effort": "high"})
    done = _resolve_tier(repo_root, "--explain", "--jev-raise", raise_)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["source"] == "jev-raise"


@pytest.mark.parametrize(
    ("stdin", "message"),
    [("", "read nothing from stdin"), ("  \n", "read nothing from stdin"), ("[1]", "list")],
    ids=["empty", "blank", "not-an-object"],
)
def test_jev_raise_from_stdin_refuses_empty_or_non_object_input(
    repo_root: Path, stdin: str, message: str
) -> None:
    done = _resolve_tier(repo_root, "--jev-raise", "-", stdin=stdin)
    assert done.returncode == 2
    assert message in json.loads(done.stderr)["error"]


@pytest.mark.parametrize("doc", WORK_DOCS, ids=lambda path: path.name)
def test_work_never_splices_the_raise_into_a_quoted_argument(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    assert "--jev-raise '" not in text
    assert "--jev-raise -" in text
    assert "tier_judgment.py raise" in text
