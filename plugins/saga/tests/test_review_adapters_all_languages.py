"""Every-language adapters map recorded output onto the lens rows (issue 151)."""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
FIXTURES = REPO_ROOT / "plugins" / "saga" / "tests" / "fixtures" / "review_tools"
_FOUR = ("findings.json", "measurements.json", "degraded.json", "outcomes.json")
_PATTERN = (
    "correctness.pattern.release-shares-cleanup",
    "correctness.pattern.swallowed-error",
    "correctness.pattern.silent-skip",
    "correctness.pattern.naive-time-comparison",
    "correctness.pattern.write-skips-shared-update",
    "correctness.pattern.money-as-float",
)


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
A = _load("review_adapters_all_languages")
R = _load("review_records")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here runs with sockets refused, so a network call fails the test."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("review adapter tests must make no network call")

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


def _adapter(tool_id: str) -> Any:
    return next(item for item in A.ADAPTERS if item.id == tool_id)


def _profile(path: Path, pins: dict[str, Any]) -> Path:
    path.write_text(json.dumps({"review_tools": {"pins": pins}}), encoding="utf-8")
    return path


def _changed_app(tmp: Path) -> tuple[Path, str, str]:
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("one\ntwo\nthree\nFOUR\nfive\n", encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head


class _Calls:
    def __init__(self, base: str, payload: str) -> None:
        self.base = base
        self.payload = payload
        self.calls: list[list[str]] = []

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False
        assert isinstance(argv, list)
        self.calls.append(list(argv))
        if "--version" in argv:
            return T.ProcessResult(0, "1.0.0\n")
        if _git(Path(cwd), "rev-parse", "HEAD") == self.base:
            return T.ProcessResult(0, "")
        return T.ProcessResult(0, self.payload)


def _run(
    repo: Path, base: str, head: str, profile: Path, output: Path, home: Path,
    adapters: list[Any], runner: Any, **kwargs: Any,
) -> int:
    home.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("framework", False)
    return T.run(
        repo, base, head, profile, output, home=home,
        adapters=adapters, runner=runner, **kwargs,
    )


def _read(output: Path, name: str) -> Any:
    return json.loads((output / name).read_text(encoding="utf-8"))


def _valid(output: Path) -> None:
    for name in ("findings.json", "measurements.json"):
        for record in _read(output, name):
            assert R.validate(record) == []


def _severity(output: Path, ref: str) -> str:
    for finding in _read(output, "outcomes.json")["findings"]:
        if finding["rule"]["ref"] == ref:
            return str(finding["severity"])
    raise AssertionError(ref)


def _pack(home: Path, body: str = "rules: []\n") -> str:
    cache = T.semgrep_cache(home, "p/security-audit")
    cache.mkdir(parents=True)
    (cache / "rules.yml").write_text(body, encoding="utf-8")
    return T.digest_tree(cache)


def _semgrep_profile(home: Path, directory: Path) -> Path:
    digest = _pack(home)
    return _profile(directory / "profile.json", {
        "semgrep": {"version": "1.0.0", "rules": [
            {"pack": "p/security-audit", "sha256": digest},
        ]},
    })


def test_each_adapter_declares_the_comparison_from_the_tool_list() -> None:
    expected = {
        "semgrep-security": "lines",
        "semgrep-saga": "lines",
        "gitleaks": "lines",
        "osv-scanner": "base-head",
        "jscpd": "base-head",
        "lizard": "lines",
        "coverage": "lines",
        "relocated-test": "base-head",
    }
    assert {item.id: item.comparison for item in A.ADAPTERS} == expected


def test_semgrep_security_maps_levels_and_stays_on_the_local_cache(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    home = tmp_path / "home"
    profile = _semgrep_profile(home, tmp_path)
    payload = (FIXTURES / "semgrep-security.json").read_text(encoding="utf-8")
    runner = _Calls(base, payload)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, home,
        [_adapter("semgrep-security")], runner,
    )
    assert code == 0
    rows = {item["rule"]["ref"]: item["rule"]["row"] for item in _read(output, "findings.json")}
    assert rows["python.lang.security.audit.example-error"] == "security.scanner-high"
    assert rows["python.lang.security.audit.example-warning"] == "security.scanner-medium-low"
    assert rows["python.lang.security.audit.example-info"] == "security.scanner-medium-low"
    assert _severity(output, "python.lang.security.audit.example-error") == "blocks"
    assert _severity(output, "python.lang.security.audit.example-warning") == "fix-later"
    scans = [argv for argv in runner.calls if "scan" in argv]
    assert len(scans) == 1
    assert "--metrics=off" in scans[0]
    config = scans[0][scans[0].index("--config") + 1]
    assert config == str(T.semgrep_cache(home, "p/security-audit"))
    assert not any(token.startswith("http") for token in scans[0])
    _valid(output)


def test_a_missing_semgrep_cache_does_not_download(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    profile = _profile(tmp_path / "profile.json", {"semgrep": {"version": "1.0.0"}})
    runner = _Calls(base, "")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("semgrep-security")], runner,
    )
    assert code == 0
    assert runner.calls == []
    reasons = _read(output, "degraded.json")
    assert reasons == [{
        "lens": "security",
        "language": "none",
        "input": "security.scanner-high",
        "tool": "semgrep",
        "reason": "rule-cache-missing",
    }]


def test_a_semgrep_hash_mismatch_does_not_download(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    home = tmp_path / "home"
    _pack(home, "different bytes\n")
    profile = _profile(tmp_path / "profile.json", {"semgrep": {"version": "1.0.0"}})
    runner = _Calls(base, "")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, home,
        [_adapter("semgrep-security")], runner,
    )
    assert code == 0
    assert runner.calls == []
    assert _read(output, "degraded.json")[0]["reason"] == "rule-cache-missing"


def test_missing_saga_rules_are_a_gap_and_security_still_runs(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    home = tmp_path / "home"
    profile = _semgrep_profile(home, tmp_path)
    payload = (FIXTURES / "semgrep-security.json").read_text(encoding="utf-8")
    runner = _Calls(base, payload)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, home,
        [_adapter("semgrep-security"), _adapter("semgrep-saga")], runner,
    )
    assert code == 0
    gaps = [
        item["input"] for item in _read(output, "degraded.json")
        if item["reason"] == "known-gap"
    ]
    assert gaps == list(_PATTERN)
    assert any("scan" in argv for argv in runner.calls)
    assert any(
        item["rule"]["row"] == "security.scanner-high" for item in _read(output, "findings.json")
    )


def test_saga_metadata_row_is_kept(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    rules = repo / "plugins" / "saga" / "references" / "semgrep-rules"
    rules.mkdir(parents=True)
    (rules / "rule.yml").write_text("rules: []\n", encoding="utf-8")
    profile = _profile(tmp_path / "profile.json", {"semgrep": {"version": "1.0.0"}})
    payload = (FIXTURES / "semgrep-saga.json").read_text(encoding="utf-8")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("semgrep-saga")], _Calls(base, payload),
    )
    assert code == 0
    finding = _read(output, "findings.json")[0]
    assert finding["rule"]["row"] == "correctness.pattern.swallowed-error"
    assert R.validate(finding) == []


def test_a_non_pattern_saga_row_exits_2(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    rules = repo / "plugins" / "saga" / "references" / "semgrep-rules"
    rules.mkdir(parents=True)
    (rules / "rule.yml").write_text("rules: []\n", encoding="utf-8")
    profile = _profile(tmp_path / "profile.json", {"semgrep": {"version": "1.0.0"}})
    payload = json.dumps({"results": [{
        "check_id": "saga.other",
        "path": "src/app.py",
        "start": {"line": 4},
        "end": {"line": 4},
        "extra": {"message": "Not a pattern row.", "metadata": {"row": "correctness.type-error"}},
    }]})
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("semgrep-saga")], _Calls(base, payload),
    )
    assert code == 2
    for name in _FOUR:
        assert not (output / name).exists()


def test_gitleaks_record_holds_no_secret_and_the_raw_bytes_are_on_disk(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    home = tmp_path / "home"
    profile = _profile(tmp_path / "profile.json", {"gitleaks": {"version": "1.0.0"}})
    payload = (FIXTURES / "gitleaks.json").read_text(encoding="utf-8")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, home, [_adapter("gitleaks")], _Calls(base, payload),
    )
    assert code == 0
    record = (output / "findings.json").read_text(encoding="utf-8")
    assert "EXAMPLE_NOT_A_SECRET" not in record
    finding = _read(output, "findings.json")[0]
    assert finding["rule"]["row"] == "security.secret-in-diff"
    assert finding["statement"] == "A secret scanner reported a match in this file."
    digest = finding["proof"]["raw_output"]
    raw = home / ".saga" / "review-output" / digest
    assert raw.read_text(encoding="utf-8") == payload
    assert R.validate(finding) == []
    assert _severity(output, "example-rule") == "blocks"


def test_osv_scanner_skips_npm_and_maps_scores(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "pnpm-lock.yaml").write_text("lock\n", encoding="utf-8")
    (repo / "yarn.lock").write_text("lock\n", encoding="utf-8")
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (repo / "README").write_text("one\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README").write_text("two\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = _profile(tmp_path / "profile.json", {"osv-scanner": {"version": "1.0.0"}})
    payload = (FIXTURES / "osv-scanner.json").read_text(encoding="utf-8")
    runner = _Calls(base, payload)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home", [_adapter("osv-scanner")], runner,
    )
    assert code == 0
    scans = [argv for argv in runner.calls if "scan" in argv]
    assert scans
    for argv in scans:
        text = " ".join(argv)
        assert "pnpm-lock.yaml" in text
        assert "yarn.lock" in text
        assert "package-lock.json" not in text
    rows = {item["rule"]["ref"]: item["rule"]["row"] for item in _read(output, "findings.json")}
    assert rows["CVE-2026-0001"] == "security.dependency-high"
    assert rows["CVE-2026-0002"] == "security.dependency-medium-low"
    assert rows["CVE-2026-0003"] == "security.dependency-high"
    assert rows["CVE-2026-0004"] == "security.dependency-high"
    assert rows["CVE-2026-0100"] == "security.dependency-medium-low"
    assert "GHSA-1" not in rows
    assert len(rows) == 5
    assert _severity(output, "CVE-2026-0003") == "blocks"
    assert _severity(output, "CVE-2026-0100") == "fix-later"
    _valid(output)


def test_an_npm_only_tree_is_a_known_gap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "package-lock.json").write_text("{ }\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = _profile(tmp_path / "profile.json", {"osv-scanner": {"version": "1.0.0"}})
    runner = _Calls(base, (FIXTURES / "osv-scanner.json").read_text(encoding="utf-8"))
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home", [_adapter("osv-scanner")], runner,
    )
    assert code == 0
    assert all("scan" not in argv for argv in runner.calls)
    assert all("package-lock.json" not in " ".join(argv) for argv in runner.calls)
    assert _read(output, "degraded.json") == [{
        "lens": "security",
        "language": "none",
        "input": "security.dependency-high",
        "tool": "osv-scanner",
        "reason": "known-gap",
    }]
    assert _read(output, "findings.json") == []


def test_a_base_npm_gap_still_scans_a_lockfile_added_at_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "poetry.lock").write_text("lock\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = _profile(tmp_path / "profile.json", {"osv-scanner": {"version": "1.0.0"}})
    payload = (FIXTURES / "osv-scanner.json").read_text(encoding="utf-8")
    runner = _Calls(base, payload)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home", [_adapter("osv-scanner")], runner,
    )
    assert code == 0
    scans = [argv for argv in runner.calls if "scan" in argv]
    assert len(scans) == 1
    text = " ".join(scans[0])
    assert "poetry.lock" in text
    assert "package-lock.json" not in text
    refs = {item["rule"]["ref"] for item in _read(output, "findings.json")}
    assert "CVE-2026-0001" in refs
    assert _severity(output, "CVE-2026-0001") == "blocks"
    assert all(item["reason"] != "known-gap" for item in _read(output, "degraded.json"))
    _valid(output)


def test_an_unscored_advisory_blocks_unless_the_builder_excuses_it(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "poetry.lock").write_text("lock\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "README").write_text("changed\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile = _profile(tmp_path / "profile.json", {"osv-scanner": {"version": "1.0.0"}})
    payload = (FIXTURES / "osv-scanner.json").read_text(encoding="utf-8")
    home = tmp_path / "home"
    first = tmp_path / "first"
    code = _run(
        repo, base, head, profile, first, home, [_adapter("osv-scanner")], _Calls(base, payload),
    )
    assert code == 0
    finding = next(
        item for item in _read(first, "findings.json") if item["rule"]["ref"] == "CVE-2026-0003"
    )
    assert _severity(first, "CVE-2026-0003") == "blocks"
    builder = {
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": "U5",
        "acceptance_criteria": [{
            "id": "AC-1",
            "text": "An unscored advisory blocks unless a reason is recorded.",
            "checks": ["osv"],
        }],
        "declarations": [{
            "question": "security.q-file-permissions",
            "applies": False,
            "proving_test": None,
        }],
        "reasons": [{
            "kind": "scanner-false-positive",
            "finding_id": finding["id"],
            "text": "The scanner misfired on this advisory.",
        }],
    }
    assert R.validate(builder) == []
    builder_path = tmp_path / "builder.json"
    builder_path.write_text(json.dumps(builder), encoding="utf-8")
    second = tmp_path / "second"
    code = T.run(
        repo, base, head, profile, second, home=home, builder=builder_path,
        adapters=[_adapter("osv-scanner")], runner=_Calls(base, payload), framework=False,
    )
    assert code == 0
    assert _severity(second, "CVE-2026-0003") == "note"


def test_jscpd_maps_to_the_duplicate_row(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    profile = _profile(tmp_path / "profile.json", {"jscpd": {"version": "1.0.0"}})
    payload = (FIXTURES / "jscpd.json").read_text(encoding="utf-8")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("jscpd")], _Calls(base, payload),
    )
    assert code == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["row"] == "architecture-maintainability.duplicate"
    assert _severity(output, findings[0]["rule"]["ref"]) == "note"
    assert "src/c.py" not in (output / "findings.json").read_text(encoding="utf-8")
    _valid(output)


def test_lizard_above_the_threshold_maps_to_the_complexity_row(tmp_path: Path) -> None:
    repo, base, head = _changed_app(tmp_path)
    profile = _profile(tmp_path / "profile.json", {"lizard": {"version": "1.0.0"}})
    payload = (FIXTURES / "lizard.csv").read_text(encoding="utf-8")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("lizard")], _Calls(base, payload),
    )
    assert code == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["row"] == "architecture-maintainability.complexity-dead-code-naming"
    assert findings[0]["location"]["function"] == "heavy"
    assert _severity(output, "heavy") == "note"
    _valid(output)


def _coverage_repo(tmp: Path, report: str) -> tuple[Path, str, str, Path]:
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    lines = [f"line{number}\n" for number in range(1, 11)]
    (repo / "src" / "app.py").write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[1] = "LINE2\n"
    lines[3] = "LINE4\n"
    lines[9] = "LINE10\n"
    (repo / "src" / "app.py").write_text("".join(lines), encoding="utf-8")
    head = _commit(repo, "head")
    # Untracked, so the diff stays the three source lines and not this report.
    (repo / "coverage.json").write_text(report, encoding="utf-8")
    return repo, base, head, tmp / "profile.json"


def test_coverage_fixtures_become_findings_and_a_measurement(tmp_path: Path) -> None:
    report = (FIXTURES / "sample-coverage.json").read_text(encoding="utf-8")
    repo, base, head, profile_path = _coverage_repo(tmp_path, report)
    profile_path.write_text(json.dumps({"review_tools": {"languages": {"python": {
        "test_command": "true",
        "coverage_report": "coverage.json",
    }}}}), encoding="utf-8")
    output = tmp_path / "out"
    (tmp_path / "home").mkdir()

    def runner(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False and isinstance(argv, list)
        return T.ProcessResult(0, "")

    code = T.run(
        repo, base, head, profile_path, output, home=tmp_path / "home",
        adapters=[], runner=runner, framework=True,
    )
    assert code == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["row"] == "testing.uncovered-branch"
    assert findings[0]["degraded"] is False
    assert findings[0]["location"]["lines"] == {"start": 4, "end": 4}
    measurement = _read(output, "measurements.json")[0]
    assert measurement["metric"] == "changed-line branch coverage"
    assert measurement["value"] == pytest.approx(2 / 3)
    assert "condition" not in measurement
    _valid(output)
    assert _severity(output, "src/app.py:4") == "blocks"


def test_line_fallback_coverage_is_degraded_and_cannot_block(tmp_path: Path) -> None:
    report = json.dumps({"files": {"src/app.py": {"missing_lines": [4]}}})
    repo, base, head, profile_path = _coverage_repo(tmp_path, report)
    profile_path.write_text(json.dumps({"review_tools": {"languages": {"python": {
        "coverage_report": "coverage.json",
    }}}}), encoding="utf-8")
    output = tmp_path / "out"
    (tmp_path / "home").mkdir()
    code = T.run(
        repo, base, head, profile_path, output, home=tmp_path / "home",
        adapters=[], framework=True,
    )
    assert code == 0
    finding = _read(output, "findings.json")[0]
    assert finding["degraded"] is True
    assert finding["rule"]["row"] == "testing.uncovered-branch"
    reasons = _read(output, "degraded.json")
    assert any(item["reason"] == "no-branch-data" for item in reasons)
    assert _severity(output, "src/app.py:4") == "fix-later"
    _valid(output)
