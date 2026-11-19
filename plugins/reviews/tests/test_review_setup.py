"""Machine record, installed-skill commands, and sandbox admission."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
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


def _scanner_stubs(directory: Path) -> Path:
    """Fake scanners on PATH. The shebang is this interpreter, so PATH can omit Python."""
    directory.mkdir()
    script = directory / "scanner-stub.py"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "log = Path(__file__).resolve().parent / 'invocations.log'\n"
        "name = Path(sys.argv[0]).name\n"
        "with log.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps({'name': name, 'argv': sys.argv[1:]}) + '\\n')\n"
        "versions = {\n"
        "    'semgrep': '1.179.0', 'bandit': '1.9.4', 'pip-audit': '2.10.1',\n"
        "    'gitleaks': '8.24.0', 'osv-scanner': '1.7.0',\n"
        "}\n"
        "if '--version' in sys.argv[1:]:\n"
        "    print(versions.get(name, '1.0.0'))\n"
        "    raise SystemExit(0)\n"
        "payloads = {\n"
        "    'semgrep': '{\"results\":[]}', 'bandit': '{\"results\":[]}',\n"
        "    'gitleaks': '[]', 'osv-scanner': '{\"results\":[]}',\n"
        "    'pip-audit': '{\"dependencies\":[]}',\n"
        "}\n"
        "print(payloads.get(name, '{}'))\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    for name in ("semgrep", "gitleaks", "osv-scanner", "bandit", "pip-audit"):
        (directory / name).symlink_to(script)
    git = shutil.which("git")
    assert git is not None
    (directory / "git").symlink_to(git)
    return script


def _semgrep_configs(log: Path) -> list[str]:
    if not log.is_file():
        return []
    found = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        argv = item.get("argv") or []
        if item.get("name") == "semgrep" and "--config" in argv:
            found.append(argv[argv.index("--config") + 1])
    return found


def test_setup_records_fetched_semgrep_pack_for_prepare_and_security_scan(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
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
    assert not any(
        path.is_dir() for path in (PACKAGE / "references" / "semgrep").rglob("p--security-audit")
    )

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
    profile.write_text('{"schema": "repository_profile.v1"}\n', encoding="utf-8")
    builder = tmp_path / "builder.json"
    builder.write_text(json.dumps({
        "kind": "builder_record",
        "schema": "review_records.v1",
        "unit": "R1",
        "acceptance_criteria": [
            {"id": "AC-1", "text": "The changed line is reviewed.", "checks": ["line"]},
        ],
        "declarations": [],
        "reasons": [],
    }), encoding="utf-8")
    stub = _scanner_stubs(tmp_path / "bin")
    monkeypatch.setenv("PATH", str(stub.parent))

    packet = tmp_path / "prepare"
    code = review_command.main([
        "prepare",
        "--repo", str(scanned),
        "--base", base,
        "--head", head,
        "--profile", str(profile),
        "--builder-record", str(builder),
        "--out", str(packet),
        "--home", str(home),
    ])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    sources = json.loads((packet / "rule-sources.json").read_text(encoding="utf-8"))
    assert sources["semgrep-security"]["source"] == "machine"
    assert sources["semgrep-security"]["rules"][0]["sha256"] == digest
    assert sources["semgrep-security"]["rules"][0]["pack"] == "p/security-audit"
    assert str(cache) in _semgrep_configs(stub.parent / "invocations.log")
    assert _custom_rule_bytes() == before

    security_scan = _load("security_scan")
    monkeypatch.setattr(security_scan.Path, "home", lambda: home)
    (stub.parent / "invocations.log").write_text("", encoding="utf-8")
    scan_out = tmp_path / "scan-out"
    exit_code = security_scan.main(["--repo", str(scanned), "--output", str(scan_out)])
    captured = capsys.readouterr()
    summary_path = scan_out / "summary.json"
    detail = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else captured.err
    assert exit_code == 0, detail
    summary = json.loads(detail)
    row = next(item for item in summary["rows"] if item["id"] == "semgrep-security")
    assert row["status"] == "ran", detail
    staged = review_tools.semgrep_cache(scan_out / ".cache", "p/security-audit")
    assert str(staged) in _semgrep_configs(stub.parent / "invocations.log")
    assert review_tools.machine_rule_digest(scan_out / ".cache", "semgrep-security") == digest
    assert _custom_rule_bytes() == before

    empty = tmp_path / "empty-home"
    empty.mkdir()
    (tmp_path / "empty-repo").mkdir()
    review_setup.survey(tmp_path / "empty-repo", empty)
    monkeypatch.setattr(security_scan.Path, "home", lambda: empty)
    absent = tmp_path / "absent-scan"
    exit_code = security_scan.main(["--repo", str(scanned), "--output", str(absent)])
    absent_summary = json.loads((absent / "summary.json").read_text(encoding="utf-8"))
    assert exit_code == 2
    assert absent_summary["exit_code"] == 2
    absent_row = next(item for item in absent_summary["rows"] if item["id"] == "semgrep-security")
    assert "rule-cache-missing" in absent_row["reason"]
    assert _custom_rule_bytes() == before
    assert not review_tools.semgrep_cache(empty, "p/security-audit").exists()


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
    assert "languages:" in completed.stdout
    assert "pins:" in completed.stdout


def _catalogue_version(row_id: str) -> str:
    row = next(item for item in review_tools.load_tool_list(None) if item.get("id") == row_id)
    return str(row["default_version"])


def _assert_cfn_pins(record: dict, home: Path) -> None:
    expected = {
        "checkov-cfn": {"version": _catalogue_version("checkov-cfn")},
        "cfn-lint": {"version": _catalogue_version("cfn-lint")},
    }
    assert "cloudformation" in record["languages"]
    assert record["pins"] == expected
    stored = review_setup.load_machine(home)
    assert stored is not None
    assert stored["pins"] == expected
    assert "cloudformation" in stored["languages"]


def test_detects_cdk_and_cloudformation_templates_and_pins_cfn_tools(tmp_path: Path) -> None:
    """cdk.json and a real template pin checkov-cfn and cfn-lint. No scanner is run."""
    cdk = tmp_path / "cdk"
    cdk.mkdir()
    (cdk / "cdk.json").write_text("{}\n", encoding="utf-8")
    cdk_home = tmp_path / "home-cdk"
    cdk_record = review_setup.survey(cdk, cdk_home)
    _assert_cfn_pins(cdk_record, cdk_home)

    template = tmp_path / "template-repo"
    _init(template)
    (template / "stack.yaml").write_text(
        'AWSTemplateFormatVersion: "2010-09-09"\nDescription: example\n',
        encoding="utf-8",
    )
    _git(template, "add", "-A")
    _git(template, "commit", "-m", "template")
    template_home = tmp_path / "home-template"
    template_record = review_setup.survey(template, template_home)
    _assert_cfn_pins(template_record, template_home)

    built = tmp_path / "built"
    (built / "build").mkdir(parents=True)
    (built / "build" / "stack.template").write_text(
        '{"AWSTemplateFormatVersion": "2010-09-09"}\n',
        encoding="utf-8",
    )
    built_home = tmp_path / "home-built"
    built_record = review_setup.survey(built, built_home)
    _assert_cfn_pins(built_record, built_home)


def test_generic_yaml_and_json_do_not_pin_cfn_tools(tmp_path: Path) -> None:
    """Ordinary config is not a CloudFormation template and does not pin the cfn tools."""
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "config.yaml").write_text("service: api\nport: 8080\n", encoding="utf-8")
    (repo / "settings.json").write_text('{"name": "example", "debug": false}\n', encoding="utf-8")
    (repo / "notes.yml").write_text(
        'description: "Resources live in another service"\n',
        encoding="utf-8",
    )
    record = review_setup.survey(repo, tmp_path / "home")
    assert "cloudformation" not in record["languages"]
    assert record["pins"] == {}
    assert "checkov-cfn" not in record["pins"]
    assert "cfn-lint" not in record["pins"]


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
