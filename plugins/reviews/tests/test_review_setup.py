"""Machine record, installed-skill commands, and sandbox admission."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "plugins" / "reviews"
SCRIPTS = PACKAGE / "scripts"
SKILLS = PACKAGE / "skills"


def _load(name: str):
    key = f"infiquetra_reviews.{name}"
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    loaded = sys.modules.get(name)
    loaded_file = getattr(loaded, "__file__", None) if loaded is not None else None
    if loaded_file is not None:
        assert Path(loaded_file).resolve() != (SCRIPTS / f"{name}.py").resolve()
    return module


review_setup = _load("review_setup")
review_command = _load("review_command")
review_tools = _load("review_tools")


def test_load_machine_prefers_reviews_config_and_falls_back(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = home / ".saga"
    legacy.mkdir(parents=True)
    (legacy / "machine.json").write_text(
        json.dumps({"schema": "legacy", "survey": {"sandbox": {"reproduction": "unavailable"}}}),
        encoding="utf-8",
    )
    loaded = review_setup.load_machine(home)
    assert loaded is not None
    assert loaded["schema"] == "legacy"
    assert not review_setup.machine_path(home).exists()

    record = review_setup.survey(tmp_path, home)
    assert review_setup.machine_path(home).is_file()
    assert review_setup.load_machine(home)["schema"] == review_setup.MACHINE_SCHEMA
    assert record["survey"]["tools"]
    assert "sandbox" in record["survey"]
    assert json.loads((legacy / "machine.json").read_text(encoding="utf-8"))["schema"] == "legacy"


def test_documented_survey_accepts_home_after_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "review_setup.py"),
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(home),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    record = json.loads(review_setup.machine_path(home).read_text(encoding="utf-8"))
    assert record["survey"]["sandbox"]["reproduction"] in {"available", "unavailable"}
    assert "sandbox:" in completed.stdout


def test_skills_resolve_scripts_from_the_install_directory() -> None:
    for name in ("code-review", "doc-review", "security-review", "review-setup"):
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        assert "plugins/reviews/" not in text
        assert "plugins/plan/" not in text
        assert "plugins/agent-launcher" not in text
        assert 'S="$SKILL_DIR/../../scripts/' in text
        assert 'S="$CLAUDE_PLUGIN_ROOT/scripts/' in text


def test_sandbox_admission_keeps_a_reproduced_finding(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(review_setup, "platform_helper", lambda: "bwrap")
    monkeypatch.setattr(review_command, "platform_helper", lambda: "bwrap")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "reviews@example.com"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "reviews"], cwd=repo, check=True, capture_output=True
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_changed.py").write_text(
        "def test_changed():\n    assert False\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    home = tmp_path / "home"
    record = review_setup.survey(repo, home)
    assert record["survey"]["sandbox"]["reproduction"] == "available"
    assert review_command.reproduction_available(home, None) is True

    scratch = tmp_path / "scratch"
    (scratch / "tests").mkdir(parents=True)
    (scratch / "tests" / "test_changed.py").write_text(
        "def test_changed():\n    assert False\n", encoding="utf-8"
    )
    finding = {
        "evidence": "reproduced",
        "lens": "correctness",
        "language": "python",
        "location": {"file": "src/app.py", "lines": {"start": 2}},
        "proof": {
            "command": "python3 -m pytest tests/test_changed.py -q",
            "test": "tests/test_changed.py::test_changed",
            "output": "AssertionError: returned 2",
        },
    }
    result = {
        "scratch": {
            "path": str(scratch),
            "changes": {"added": ["tests/test_changed.py"], "modified": [], "deleted": []},
        }
    }

    def runner(argv, *, cwd, env, timeout, shell, umask=None):
        del umask
        completed = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=timeout
        )
        assert shell is False
        return review_tools.ProcessResult(completed.returncode, completed.stdout, completed.stderr)

    def confine(_argv, _scratch, _env, _cwd):
        return review_tools.ProcessResult(
            1, "AssertionError: returned 2\ntests/test_changed.py::test_changed\n"
        )

    degraded = review_command._rerun_findings(
        [finding],
        result,
        repo,
        head,
        home,
        runner,
        confine,
        review_command.reproduction_available(home, None),
        set(),
    )
    assert finding["evidence"] == "reproduced"
    assert not any(item.get("reason") == "no-sandbox" for item in degraded)

    omitted = dict(finding)
    review_command._rerun_findings(
        [omitted], result, repo, head, home, runner, confine, False, set()
    )
    assert omitted["evidence"] == "traced"
