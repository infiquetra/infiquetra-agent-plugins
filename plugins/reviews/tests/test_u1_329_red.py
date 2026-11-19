"""Wave 1 independent fail-first red tests for U1 (issue #329: standalone `plugins/reviews`).

Designed to run both from `/tmp/ap30-wt/red-tests/u1-329/` against a checkout and once
dropped into `plugins/reviews/tests/`.

Covers:
1. D2 mechanical gate: byte-for-byte identity of `plugins/reviews/scripts/review_formula.py`
   and `plugins/reviews/references/review-records.schema.json` against `5550acf:plugins/saga/...`
   with `$id` unchanged.
2. Zero runtime imports or references to `plugins/saga`, `plugins/orchestrate`, `build_loop`,
   `run_record`, or secondary external-vendor review lanes across `plugins/reviews/scripts/`
   and `plugins/reviews/skills/`.
3. Standalone `code-review` `prepare` + `finish` against a fresh temp git repo (`--base`/`--head`,
   no `.claude/saga/` directory, no `--issue` required) producing a schema-valid packet and
   `review-run.json` in `.reviews/`.
4. Standalone `security_scan.py` run on a committed temp git tree without Saga state.
5. Standalone `lifecycle_review.py` listing and reading `idea`, `spec`, and `issue` rubrics
   without Saga state.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

BASE_COMMIT = "5550acfbc3ffe1eaf2016c17b007c98e80fb46dc"
FORBIDDEN_IMPORTS = frozenset(
    {
        "run_record",
        "build_loop",
        "saga",
        "admission",
        "merge_turn",
        "plan_review",
        "orchestrate",
    }
)
FORBIDDEN_SCRIPT_TOKENS = (
    "plugins/saga",
    "plugins/orchestrate",
    "build_loop",
    "run_record",
    ".claude/saga/runs",
    "external-reviewer",
    "engine-registry.yaml",
)
FORBIDDEN_SKILL_TOKENS = (
    "plugins/saga",
    "plugins/orchestrate",
    "build_loop.py",
    "run_record",
    ".claude/saga/runs",
    "orchestrate.py review-launch",
    "external-reviewer",
    "engine-registry.yaml",
)
EXPECTED_SKILLS = ("code-review", "security-review", "doc-review", "review-setup")


def _repo_root() -> Path:
    marker = Path("plugins/fleet-core/plugin.json")
    here = Path(__file__).resolve()
    if len(here.parents) > 3 and (here.parents[3] / marker).is_file():
        return here.parents[3]
    cwd = Path.cwd().resolve()
    if (cwd / marker).is_file():
        return cwd
    for parent in here.parents:
        if (parent / marker).is_file():
            return parent
    return cwd


def _reviews_dir() -> Path:
    return _repo_root() / "plugins" / "reviews"


def _load_review_module(name: str) -> ModuleType:
    scripts_dir = _reviews_dir() / "scripts"
    script_path = scripts_dir / f"{name}.py"
    assert script_path.is_file(), f"missing script: {script_path}"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("U1 red tests must make no network calls")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def test_d2_review_formula_and_schema_byte_identical_to_5550acf() -> None:
    repo = _repo_root()
    reviews = _reviews_dir()
    formula_path = reviews / "scripts" / "review_formula.py"
    schema_path = reviews / "references" / "review-records.schema.json"
    formula_test_path = reviews / "tests" / "test_review_formula.py"

    assert formula_path.is_file(), f"missing {formula_path}"
    assert schema_path.is_file(), f"missing {schema_path}"
    assert formula_test_path.is_file(), f"missing {formula_test_path}"

    expected_formula = subprocess.run(
        ["git", "-C", str(repo), "show", f"{BASE_COMMIT}:plugins/saga/scripts/review_formula.py"],
        capture_output=True,
        check=True,
    ).stdout
    expected_schema = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "show",
            f"{BASE_COMMIT}:plugins/saga/references/review-records.schema.json",
        ],
        capture_output=True,
        check=True,
    ).stdout

    assert formula_path.read_bytes() == expected_formula
    assert schema_path.read_bytes() == expected_schema
    parsed_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    expected_parsed = json.loads(expected_schema.decode("utf-8"))
    assert parsed_schema.get("$id") == expected_parsed.get("$id")


def test_no_orchestrate_or_secondary_external_reviewer_dependency() -> None:
    reviews = _reviews_dir()
    scripts_dir = reviews / "scripts"
    skills_dir = reviews / "skills"
    assert scripts_dir.is_dir(), f"missing {scripts_dir}"
    assert skills_dir.is_dir(), f"missing {skills_dir}"

    for skill_name in EXPECTED_SKILLS:
        skill_md = skills_dir / skill_name / "SKILL.md"
        assert skill_md.is_file(), f"missing skill {skill_md}"
        text = skill_md.read_text(encoding="utf-8")
        for token in FORBIDDEN_SKILL_TOKENS:
            assert token not in text, f"{skill_md} contains forbidden reference {token!r}"

    sec_skill_text = (skills_dir / "security-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "Deterministic Scanner Results" in sec_skill_text
    assert "Reasoned Security Findings" in sec_skill_text

    py_files = sorted(scripts_dir.rglob("*.py"))
    assert py_files, f"no python scripts found in {scripts_dir}"
    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in FORBIDDEN_IMPORTS, (
                        f"{py_file} imports forbidden module {alias.name!r}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                assert top not in FORBIDDEN_IMPORTS, (
                    f"{py_file} imports from forbidden module {node.module!r}"
                )
        for token in FORBIDDEN_SCRIPT_TOKENS:
            assert token not in source, f"{py_file} contains forbidden token {token!r}"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_prepare_and_finish_without_saga_run_record(tmp_path: Path) -> None:
    rc = _load_review_module("review_command")
    rt = rc.review_tools
    rr = rc.review_records
    ra = rc.reviewer_answer

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "reviews-red@example.com")
    _git(repo, "config", "user.name", "reviews-red")
    (repo / "src" / "app.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")

    (repo / "src" / "app.py").write_text("def changed():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")

    assert not (repo / ".claude" / "saga").exists()

    profile = tmp_path / "outside" / "profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(json.dumps({"schema": "repository_profile.v1"}) + "\n", encoding="utf-8")

    builder = tmp_path / "builder.json"
    builder.write_text(
        json.dumps(
            {
                "kind": "builder_record",
                "schema": rr.SCHEMA,
                "unit": "U1",
                "acceptance_criteria": [
                    {
                        "id": "AC-1",
                        "text": "Standalone review runs without Saga run_record.",
                        "checks": ["line"],
                    }
                ],
                "declarations": [],
                "reasons": [],
            }
        ),
        encoding="utf-8",
    )

    bank = tmp_path / "bank.json"
    bank.write_text(
        json.dumps(
            {
                "schema": "question_bank.v1",
                "questions": [
                    {
                        "id": "correctness.q-changed",
                        "lens": "correctness",
                        "kind": "yes-no",
                        "options": [
                            {
                                "id": "yes",
                                "definition": "The change breaks the described behaviour.",
                            },
                            {
                                "id": "no",
                                "definition": "The change keeps the described behaviour.",
                            },
                        ],
                        "piece": "function",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    home = tmp_path / "home"
    home.mkdir()
    out = repo / ".reviews" / "packet"

    def runner(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
        shell: bool,
        umask: int | None = None,
    ) -> Any:
        assert shell is False
        if Path(argv[0]).name == "git":
            proc = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            return rt.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
        if "--version" in argv:
            return rt.ProcessResult(0, "1.0.0\n")
        return rt.ProcessResult(0, "scan\n")

    stub_adapter = rt.Adapter(
        id="stub",
        tool="stub",
        invoke=lambda _ctx: ["stub", "scan"],
        parse=lambda _text: rt.ParseResult(
            (
                rt.Hit(
                    rule_id="example",
                    path="src/app.py",
                    statement="A stub reported this.",
                    anchor="return 2",
                    start=2,
                    end=2,
                    row="security.scanner-high",
                ),
            )
        ),
        default_version="1.0.0",
        rows=("security.scanner-high",),
        lens="security",
        comparison="lines",
    )

    def ask(_state: Any, questions: Any, **_kwargs: Any) -> Any:
        if isinstance(questions, dict) and "consequence" in questions:
            return SimpleNamespace(
                status="ok",
                model="jev-test",
                note="",
                answers={
                    "consequence": {
                        "type": "choice",
                        "choice": "required-behaviour-missing",
                        "confidence": 0.9,
                    }
                },
            )
        return SimpleNamespace(
            status="ok",
            ok=True,
            model="jev-test",
            latency_ms=5,
            note="",
            usage={"input_tokens": 12, "output_tokens": 4},
            answers={key: {"type": "noul", "noul": 0.91} for key in questions},
        )

    subparsers_action = next(
        action
        for action in rc.build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    prepare_opts = set(subparsers_action.choices["prepare"]._option_string_actions)

    prepare_argv = [
        "prepare",
        "--repo",
        str(repo),
        "--base",
        base,
        "--head",
        head,
        "--out",
        str(out),
    ]
    if "--profile" in prepare_opts:
        prepare_argv.extend(["--profile", str(profile)])
    if "--builder-record" in prepare_opts:
        prepare_argv.extend(["--builder-record", str(builder)])
    if "--home" in prepare_opts:
        prepare_argv.extend(["--home", str(home)])
    if "--bank" in prepare_opts:
        prepare_argv.extend(["--bank", str(bank)])
    stderr_buf = io.StringIO()
    with redirect_stderr(stderr_buf):
        prep_code = rc.main(
            prepare_argv, adapters=[stub_adapter], runner=runner, ask=ask
        )
    assert prep_code == 0, stderr_buf.getvalue()
    assert (out / "change.json").is_file()
    assert (out / "findings.json").is_file()
    assert (out / "where-to-look.json").is_file()
    assert (out / "grades.json").is_file()

    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert len(findings) == 1
    assert rr.validate(findings[0]) == []

    where = json.loads((out / "where-to-look.json").read_text(encoding="utf-8"))
    assert len(where) == 1

    answer_path = tmp_path / "answer-0.json"
    result_path = tmp_path / "result-0.json"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    answer_payload = {
        "schema": ra.ANSWER_SCHEMA,
        "items": [
            {
                "index": 0,
                "file": where[0]["location"]["file"],
                "answer": {
                    "kind": "cleared",
                    "reason": "The function still returns an integer as expected.",
                },
            }
        ],
        "findings": [],
    }
    result_payload = {
        "session_id": "s1",
        "agent_id": "",
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "prompt_sha256": "ab" * 32,
        "configuration": {"fingerprint": "cd" * 32},
        "usage": {
            "input_tokens": 10,
            "cache_read_input_tokens": 1,
            "cache_creation_input_tokens": 2,
            "output_tokens": 3,
            "cost_usd": 0.5,
            "seconds": 1.5,
        },
        "scratch": {
            "path": str(scratch),
            "changes": {"added": [], "modified": [], "deleted": []},
        },
    }
    answer_path.write_text(json.dumps(answer_payload), encoding="utf-8")
    result_path.write_text(json.dumps(result_payload), encoding="utf-8")

    finish_argv = [
        "finish",
        "--packet",
        str(out),
        "--home",
        str(home),
        "--answer",
        str(answer_path),
        "--result",
        str(result_path),
    ]
    finish_err = io.StringIO()
    with redirect_stderr(finish_err):
        fin_code = rc.main(finish_argv, runner=runner, ask=ask)
    assert fin_code == 0, finish_err.getvalue()

    review_run_path = out / "review-run.json"
    assert review_run_path.is_file()
    review_run = json.loads(review_run_path.read_text(encoding="utf-8"))
    assert rr.validate(review_run) == []
    assert len(review_run["lens_grades"]) == 4
    assert not (repo / ".claude" / "saga").exists()
    assert not (tmp_path / ".claude" / "saga").exists()


def test_standalone_security_scan_on_committed_temp_git_tree_without_saga_state(
    tmp_path: Path,
) -> None:
    scan_script = _reviews_dir() / "scripts" / "security_scan.py"
    assert scan_script.is_file(), f"missing {scan_script}"

    repo = tmp_path / "scan-repo"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "security-red@example.com")
    _git(repo, "config", "user.name", "security-red")
    (repo / "src" / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    commit_sha = _git(repo, "rev-parse", "HEAD")

    bin_dir = tmp_path / "empty-bin"
    bin_dir.mkdir()
    real_git = shutil.which("git") or "/usr/bin/git"
    (bin_dir / "git").symlink_to(real_git)

    home = tmp_path / "home"
    home.mkdir()
    output = tmp_path / "scan-out"

    proc = subprocess.run(
        [
            sys.executable,
            str(scan_script),
            "--repo",
            str(repo),
            "--commit",
            commit_sha,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": str(bin_dir),
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "TMPDIR": str(tmp_path),
        },
    )
    assert proc.returncode in (0, 1, 2), proc.stderr
    assert (output / "summary.json").is_file()
    assert (output / "summary.md").is_file()
    assert (output / "findings.json").is_file()
    assert (output / "degraded.json").is_file()

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["commit"] == commit_sha
    assert summary["exit_code"] == proc.returncode
    assert isinstance(summary["rows"], list) and len(summary["rows"]) > 0
    assert not (repo / ".claude" / "saga").exists()


def test_lifecycle_review_lists_and_reads_all_phases_standalone(
    tmp_path: Path,
) -> None:
    script = _reviews_dir() / "scripts" / "lifecycle_review.py"
    assert script.is_file(), f"missing {script}"

    for phase in ("idea", "spec", "issue"):
        cores_proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "rubrics",
                "list-cores",
                "--phase",
                phase,
                "--json",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert cores_proc.returncode == 0, cores_proc.stderr
        cores = json.loads(cores_proc.stdout)
        assert isinstance(cores, list) and len(cores) > 0, f"empty core rubrics for {phase}"

        extras_proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "rubrics",
                "list-extras",
                "--phase",
                phase,
                "--json",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert extras_proc.returncode == 0, extras_proc.stderr
        extras = json.loads(extras_proc.stdout)
        assert isinstance(extras, list)

        read_proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "rubrics",
                "read",
                "--phase",
                phase,
                "--slug",
                cores[0],
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert read_proc.returncode == 0, read_proc.stderr
        assert read_proc.stdout.startswith("---\n")
        assert len(read_proc.stdout.strip()) > 20

    assert not (tmp_path / ".claude" / "saga").exists()
