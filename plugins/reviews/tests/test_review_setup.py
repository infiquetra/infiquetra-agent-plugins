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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "reviews@example.com"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "reviews"], cwd=repo, check=True, capture_output=True
    )


def _custom_rule_bytes() -> dict[str, bytes]:
    custom = PACKAGE / "references" / "semgrep"
    return {
        path.relative_to(custom).as_posix(): path.read_bytes()
        for path in custom.rglob("*")
        if path.is_file()
    }


def test_setup_records_fetched_semgrep_pack_for_prepare_and_security_scan(tmp_path: Path) -> None:
    before = _custom_rule_bytes()
    home = tmp_path / "home"
    cache = review_tools.semgrep_cache(home, "p/security-audit")
    cache.mkdir(parents=True)
    (cache / "rules.yml").write_text("rules: []\n", encoding="utf-8")
    digest = review_tools.digest_tree(cache)
    repo = tmp_path / "survey-repo"
    repo.mkdir()
    record = review_setup.survey(repo, home)
    assert record["rule_caches"]["semgrep-security"] == digest
    assert record["rule_caches"]["p/security-audit"] == digest
    assert _custom_rule_bytes() == before
    assert not any(path.is_dir() for path in (PACKAGE / "references" / "semgrep").rglob("p--security-audit"))

    scanned = tmp_path / "repo"
    _init(scanned)
    (scanned / "src").mkdir()
    (scanned / "src" / "app.py").write_text("one\n", encoding="utf-8")
    base = _git(scanned, "add", "-A")
    _git(scanned, "commit", "-m", "base")
    base = _git(scanned, "rev-parse", "HEAD")
    (scanned / "src" / "app.py").write_text("two\n", encoding="utf-8")
    _git(scanned, "add", "-A")
    _git(scanned, "commit", "-m", "head")
    head = _git(scanned, "rev-parse", "HEAD")
    profile = tmp_path / "profile.json"
    profile.write_text("{}\n", encoding="utf-8")
    adapters = {item.id: item for item in review_tools.default_adapters()}

    def runner(argv, *, cwd, env, timeout, shell):
        del cwd, env, timeout, shell
        if argv and argv[-1:] == ["--version"] or "--version" in argv:
            return review_tools.ProcessResult(0, "1.179.0\n")
        return review_tools.ProcessResult(0, "{}")

    output = tmp_path / "prepare"
    code = review_tools.run(
        scanned, base, head, profile, output, home=home,
        adapters=[adapters["semgrep-security"]], runner=runner, framework=False,
    )
    assert code == 0
    sources = json.loads((output / "rule-sources.json").read_text(encoding="utf-8"))
    assert sources["semgrep-security"]["source"] == "machine"
    assert sources["semgrep-security"]["rules"][0]["sha256"] == digest
    assert sources["semgrep-security"]["rules"][0]["pack"] == "p/security-audit"

    saga_out = tmp_path / "saga"
    code = review_tools.run(
        scanned, base, head, profile, saga_out, home=home,
        adapters=[adapters["semgrep-saga"]], runner=runner, framework=False,
    )
    assert code == 0
    saga_sources = json.loads((saga_out / "rule-sources.json").read_text(encoding="utf-8"))
    assert "semgrep-saga" not in saga_sources
    assert _custom_rule_bytes() == before

    security_scan = _load("security_scan")
    staged = tmp_path / "staged"
    staged.mkdir()
    security_scan._rule_home(staged, home)
    assert review_tools.machine_rule_digest(staged, "semgrep-security") == digest
    assert review_tools.semgrep_cache(staged, "p/security-audit").is_dir()


def test_missing_semgrep_cache_stays_rule_cache_missing(tmp_path: Path, monkeypatch) -> None:
    before = _custom_rule_bytes()
    home = tmp_path / "empty-home"
    home.mkdir()
    (tmp_path / "empty-repo").mkdir()
    record = review_setup.survey(tmp_path / "empty-repo", home)
    assert "semgrep-security" not in record["rule_caches"]
    assert "p/security-audit" not in record["rule_caches"]

    scanned = tmp_path / "repo"
    _init(scanned)
    (scanned / "src").mkdir()
    (scanned / "src" / "app.py").write_text("one\n", encoding="utf-8")
    _git(scanned, "add", "-A")
    _git(scanned, "commit", "-m", "base")
    base = _git(scanned, "rev-parse", "HEAD")
    (scanned / "src" / "app.py").write_text("two\n", encoding="utf-8")
    _git(scanned, "add", "-A")
    _git(scanned, "commit", "-m", "head")
    head = _git(scanned, "rev-parse", "HEAD")
    profile = tmp_path / "profile.json"
    profile.write_text("{}\n", encoding="utf-8")
    security = next(item for item in review_tools.default_adapters() if item.id == "semgrep-security")
    output = tmp_path / "prepare"
    code = review_tools.run(
        scanned, base, head, profile, output, home=home,
        adapters=[security], runner=lambda *args, **kwargs: review_tools.ProcessResult(0, "{}"),
        framework=False,
    )
    assert code == 0
    degraded = json.loads((output / "degraded.json").read_text(encoding="utf-8"))
    assert any(item["reason"] == "rule-cache-missing" and item["tool"] == "semgrep" for item in degraded)
    assert _custom_rule_bytes() == before

    security_scan = _load("security_scan")
    monkeypatch.setattr(security_scan.Path, "home", lambda: home)
    scan_out = tmp_path / "scan-out"
    exit_code = security_scan.main(["--repo", str(scanned), "--output", str(scan_out)])
    assert exit_code == 2
    summary = json.loads((scan_out / "summary.json").read_text(encoding="utf-8"))
    row = next(item for item in summary["rows"] if item["id"] == "semgrep-security")
    assert "rule-cache-missing" in row["reason"]
    assert _custom_rule_bytes() == before
    assert not review_tools.semgrep_cache(home, "p/security-audit").exists()


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
