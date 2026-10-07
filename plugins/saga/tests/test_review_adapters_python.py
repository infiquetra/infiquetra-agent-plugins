"""Python adapters map recorded output onto the lens rows (issue 152)."""

from __future__ import annotations

import importlib.util
import json
import re
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
_FOUR = ("findings.json", "measurements.json", "degraded.json", "outcomes.json")
_TOKEN = "EXAMPLE_NOT_A_SECRET"
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")


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
P = _load("review_adapters_python")
A = _load("review_adapters_all_languages")
R = _load("review_records")
_VERSIONS = {item.tool: item.default_version for item in (*P.ADAPTERS, *A.ADAPTERS)}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("review adapter tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
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


def _repo(
    tmp: Path, base_files: dict[str, str], head_files: dict[str, str]
) -> tuple[Path, str, str]:
    repo = tmp / "repo"
    _init(repo)
    for name, text in base_files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    base = _commit(repo, "base")
    for name, text in head_files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head


def _adapter(tool_id: str) -> Any:
    return next(item for item in P.ADAPTERS if item.id == tool_id)


def _profile(path: Path, command: str | None = None) -> Path:
    block: dict[str, Any] = {"pins": {}}
    if command is not None:
        block["languages"] = {"python": {"test_command": command}}
    path.write_text(json.dumps({"review_tools": block}), encoding="utf-8")
    return path


def _version_text(argv: list[str]) -> str | None:
    if (
        len(argv) >= 3
        and argv[0] == "python3"
        and argv[1] == "-c"
        and "importlib.metadata" in argv[2]
    ):
        for name, version in _VERSIONS.items():
            if name in argv[2]:
                return version
        return "0.0.0"
    if "--version" in argv or "-version" in argv:
        return _VERSIONS.get(argv[0], "0.0.0")
    return None


class _Calls:
    def __init__(
        self,
        base: str,
        payload: str,
        *,
        base_payload: str = "{}",
        choose: Any = None,
    ) -> None:
        self.base = base
        self.payload = payload
        self.base_payload = base_payload
        self.choose = choose
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False
        assert isinstance(argv, list)
        self.calls.append(list(argv))
        self.envs.append(dict(env))
        version = _version_text(argv)
        if version is not None:
            return T.ProcessResult(0, version + "\n")
        if self.choose is not None:
            chosen = self.choose(argv, Path(cwd))
            if chosen is not None:
                return chosen
        try:
            head = _git(Path(cwd), "rev-parse", "HEAD")
        except subprocess.CalledProcessError:
            head = ""
        body = self.base_payload if head == self.base else self.payload
        return T.ProcessResult(0, body)


def _run(
    repo: Path, base: str, head: str, profile: Path, output: Path, home: Path,
    adapters: list[Any], runner: Any, **kwargs: Any,
) -> int:
    home.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("framework", False)
    return T.run(
        repo, base, head, profile, output, home=home, adapters=adapters, runner=runner, **kwargs
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


def _by_statement(output: Path, statement: str) -> str:
    finding = next(
        item for item in _read(output, "findings.json") if item["statement"] == statement
    )
    for item in _read(output, "outcomes.json")["findings"]:
        if item["id"] == finding["id"]:
            return str(item["severity"])
    raise AssertionError(statement)


def _row(output: Path, ref: str) -> str:
    for finding in _read(output, "findings.json"):
        if finding["rule"]["ref"] == ref:
            return str(finding["rule"]["row"])
    raise AssertionError(ref)


def _reasons(output: Path) -> list[str]:
    return [item["reason"] for item in _read(output, "degraded.json")]


def _changed(tmp: Path) -> tuple[Path, str, str]:
    return _repo(tmp, {"app.py": "x = 1\n"}, {"app.py": "x = 2\n"})


def _bandit(results: list[dict[str, Any]]) -> str:
    return json.dumps({"results": results})


def _one_bandit(test_id: str, severity: str, line: int, code: str = "x = 1") -> dict[str, Any]:
    return {
        "code": code,
        "filename": "./app.py",
        "issue_severity": severity,
        "issue_text": "Example finding.",
        "line_number": line,
        "test_id": test_id,
    }


def _outside(flag: str, empty: str) -> Any:
    def choose(argv: list[str], cwd: Path) -> Any:
        if flag not in argv:
            return T.ProcessResult(0, empty)
        if flag in {"-c", "--config", "--config-file"}:
            path = Path(argv[argv.index(flag) + 1])
            if path == cwd or cwd in path.parents:
                return T.ProcessResult(0, empty)
        return None

    return choose


def _probed(argv: list[str]) -> str | None:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _VERSION.search((proc.stdout or "") + (proc.stderr or ""))
    return match.group(0) if match else None


def test_bandit_high_on_a_changed_line_blocks(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = _bandit([
        _one_bandit("B608", "HIGH", 1),
        _one_bandit("B101", "MEDIUM", 1),
        _one_bandit("B110", "LOW", 1),
    ])
    runner = _Calls(base, payload, choose=_outside("--ignore-nosec", _bandit([])))
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("bandit")], runner,
    )
    assert code == 0
    assert _row(output, "B608") == "security.scanner-high"
    assert _severity(output, "B608") == "blocks"
    assert _row(output, "B101") == "security.scanner-medium-low"
    assert _severity(output, "B101") == "fix-later"
    assert _severity(output, "B110") == "fix-later"
    assert "--ignore-nosec" in runner.calls[-1]
    _valid(output)


def test_bandit_excuse_becomes_a_note(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = _bandit([_one_bandit("B608", "HIGH", 1)])
    profile = _profile(tmp_path / "profile.json")
    home = tmp_path / "home"
    runner = _Calls(base, payload)
    first = tmp_path / "first"
    assert _run(repo, base, head, profile, first, home, [_adapter("bandit")], runner) == 0
    finding = next(item for item in _read(first, "findings.json") if item["rule"]["ref"] == "B608")
    assert _severity(first, "B608") == "blocks"
    builder = {
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": "U1",
        "acceptance_criteria": [{
            "id": "AC-3",
            "text": "A high bandit finding blocks unless a reason is recorded.",
            "checks": ["bandit"],
        }],
        "declarations": [{
            "question": "security.q-file-permissions",
            "applies": False,
            "proving_test": None,
        }],
        "reasons": [{
            "kind": "scanner-false-positive",
            "finding_id": finding["id"],
            "text": "The scanner misfired on this finding.",
        }],
    }
    assert R.validate(builder) == []
    builder_path = tmp_path / "builder.json"
    builder_path.write_text(json.dumps(builder), encoding="utf-8")
    second = tmp_path / "second"
    code = T.run(
        repo, base, head, profile, second, home=home, builder=builder_path,
        adapters=[_adapter("bandit")], runner=_Calls(base, payload), framework=False,
    )
    assert code == 0
    assert _severity(second, "B608") == "note"


def test_bandit_high_on_an_unchanged_line_is_absent(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, {"app.py": "a\nb\n"}, {"app.py": "a\nB\n"})
    payload = _bandit([_one_bandit("B608", "HIGH", 1)])
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("bandit")], _Calls(base, payload),
    )
    assert code == 0
    assert _read(output, "findings.json") == []


def test_bandit_decoy_skip_does_not_hide_the_finding(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {"app.py": "x = 2\n", "pyproject.toml": "[tool.bandit]\nskips = [\"B608\"]\n"},
    )
    payload = _bandit([_one_bandit("B608", "HIGH", 1)])
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("bandit")],
        _Calls(base, payload, choose=_outside("--ignore-nosec", _bandit([]))),
    )
    assert code == 0
    assert _severity(output, "B608") == "blocks"


def test_bandit_secret_excerpt_is_absent_from_the_records(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = _bandit([_one_bandit("B105", "HIGH", 1, code=f"{_TOKEN} = 1")])
    output = tmp_path / "out"
    assert _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("bandit")], _Calls(base, payload),
    ) == 0
    for name in _FOUR:
        assert _TOKEN not in (output / name).read_text(encoding="utf-8")
    _valid(output)


def test_a_missing_bandit_binary_is_reason_missing(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)

    def explode(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        raise FileNotFoundError(argv[0])

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("bandit")], explode,
    )
    assert code == 0
    assert "missing" in _reasons(output)


def test_bandit_non_json_is_unparseable(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)

    def choose(argv: list[str], _cwd: Path) -> Any:
        if _version_text(argv) is not None:
            return None
        return T.ProcessResult(1, "not-json")

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("bandit")], _Calls(base, "{}", choose=choose),
    )
    assert code == 0
    assert "unparseable" in _reasons(output)


def test_pip_audit_unscored_advisory_blocks(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"requirements.txt": "example==1\n"}, {"requirements.txt": "example==2\n"}
    )
    payload = json.dumps({
        "dependencies": [{
            "name": "example",
            "version": "2",
            "vulns": [{
                "id": "PYSEC-EXAMPLE",
                "aliases": ["ZYSEC-EXAMPLE"],
                "description": _TOKEN,
            }],
        }],
    })
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("pip-audit")], _Calls(base, payload, base_payload='{"dependencies": []}'),
    )
    assert code == 0
    assert _row(output, "PYSEC-EXAMPLE") == "security.dependency-high"
    assert _severity(output, "PYSEC-EXAMPLE") == "blocks"
    for name in _FOUR:
        assert _TOKEN not in (output / name).read_text(encoding="utf-8")
    _valid(output)


def test_pip_audit_unscored_advisory_is_a_note_when_excused(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"requirements.txt": "example==1\n"}, {"requirements.txt": "example==2\n"}
    )
    payload = json.dumps({
        "dependencies": [{"name": "example", "version": "2", "vulns": [{"id": "PYSEC-EXAMPLE"}]}],
    })
    profile = _profile(tmp_path / "profile.json")
    home = tmp_path / "home"
    runner = _Calls(base, payload, base_payload='{"dependencies": []}')
    first = tmp_path / "first"
    assert _run(repo, base, head, profile, first, home, [_adapter("pip-audit")], runner) == 0
    finding = next(
        item for item in _read(first, "findings.json") if item["rule"]["ref"] == "PYSEC-EXAMPLE"
    )
    assert _severity(first, "PYSEC-EXAMPLE") == "blocks"
    builder = {
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": "U1",
        "acceptance_criteria": [{
            "id": "AC-3",
            "text": "An unscored advisory blocks unless a reason is recorded.",
            "checks": ["pip-audit"],
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
    builder_path = tmp_path / "builder.json"
    builder_path.write_text(json.dumps(builder), encoding="utf-8")
    second = tmp_path / "second"
    code = T.run(
        repo, base, head, profile, second, home=home, builder=builder_path,
        adapters=[_adapter("pip-audit")],
        runner=_Calls(base, payload, base_payload='{"dependencies": []}'),
        framework=False,
    )
    assert code == 0
    assert _severity(second, "PYSEC-EXAMPLE") == "note"


def test_pip_audit_takes_the_scored_advisory(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"requirements.txt": "example==1\n"}, {"requirements.txt": "example==2\n"}
    )
    pip = json.dumps({
        "dependencies": [{"name": "example", "version": "2", "vulns": [{"id": "PYSEC-EXAMPLE"}]}],
    })
    osv = json.dumps({"results": [{
        "source": {"path": "requirements.txt"},
        "packages": [{"vulnerabilities": [{
            "id": "PYSEC-EXAMPLE",
            "aliases": [],
            "severity": [{"type": "CVSS_V3", "score": "4.0"}],
        }]}],
    }]})

    def choose(argv: list[str], cwd: Path) -> Any:
        try:
            head_now = _git(cwd, "rev-parse", "HEAD")
        except subprocess.CalledProcessError:
            head_now = ""
        if argv and argv[0] == "pip-audit":
            body = '{"dependencies": []}' if head_now == base else pip
            return T.ProcessResult(0, body)
        if argv and argv[0] == "osv-scanner":
            body = '{"results": []}' if head_now == base else osv
            return T.ProcessResult(0, body)
        return None

    output = tmp_path / "out"
    osv_adapter = next(item for item in A.ADAPTERS if item.id == "osv-scanner")
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("pip-audit"), osv_adapter], _Calls(base, pip, choose=choose),
    )
    assert code == 0
    findings = _read(output, "findings.json")
    assert len(findings) == 1
    assert findings[0]["rule"]["ref"] == "PYSEC-EXAMPLE"
    assert findings[0]["rule"]["row"] == "security.dependency-medium-low"
    assert _severity(output, "PYSEC-EXAMPLE") == "fix-later"


def test_pip_audit_advisory_present_at_base_is_absent(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"requirements.txt": "example==1\n"}, {"README.md": "changed\n"}
    )
    payload = json.dumps({
        "dependencies": [{"name": "example", "version": "1", "vulns": [{"id": "PYSEC-EXAMPLE"}]}],
    })
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("pip-audit")], _Calls(base, payload, base_payload=payload),
    )
    assert code == 0
    assert _read(output, "findings.json") == []


def test_mypy_untouched_file_blocks(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n", "untouched.py": "value = 1\n"},
        {"app.py": "x = 2\n"},
    )
    base_text = "untouched.py:1:1: error: bad  [assignment]\n"
    head_text = (
        "untouched.py:1:1: error: bad  [assignment]\n"
        "untouched.py:2:1: error: worse  [assignment]\n"
        "untouched.py:3:1: note: see the error  [assignment]\n"
    )
    output = tmp_path / "out"
    runner = _Calls(base, head_text, base_payload=base_text)
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("mypy")], runner,
    )
    assert code == 0
    findings = _read(output, "findings.json")
    statements = {item["statement"] for item in findings}
    assert "bad" not in statements
    assert "worse" in statements
    kept = next(item for item in findings if item["statement"] == "worse")
    assert kept["rule"]["row"] == "correctness.type-error"
    assert kept["location"]["file"] == "untouched.py"
    assert "untouched.py" not in _git(repo, "diff", "--name-only", base, head)
    assert _by_statement(output, "worse") == "blocks"
    note = next(item for item in findings if item["statement"] == "see the error")
    assert note["rule"]["row"] == "correctness.tool-style"
    assert _by_statement(output, "see the error") == "note"
    scan = next(argv for argv in runner.calls if "--config-file" in argv)
    config = Path(scan[scan.index("--config-file") + 1])
    assert "--strict" not in scan
    assert repo.resolve() not in config.resolve().parents
    _valid(output)


def test_mypy_decoy_config_does_not_hide_the_error(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {"app.py": "x = 2\n", "pyproject.toml": "[tool.mypy]\nignore_errors = true\n"},
    )
    payload = "app.py:1:1: error: bad  [assignment]\n"
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("mypy")],
        _Calls(base, payload, base_payload="", choose=_outside("--config-file", "")),
    )
    assert code == 0
    assert _severity(output, "assignment") == "blocks"


def test_ruff_families_map_to_error_warning_and_style(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = json.dumps([
        {
            "code": code,
            "message": code,
            "filename": "app.py",
            "location": {"row": 1},
            "end_location": {"row": 1},
        }
        for code in ("F401", "E501", "UP032", "ZZZ999")
    ])

    def choose(argv: list[str], _cwd: Path) -> Any:
        if "--isolated" not in argv or "--ignore-noqa" not in argv or "ALL" not in argv:
            return T.ProcessResult(0, "[]")
        return None

    output = tmp_path / "out"
    runner = _Calls(base, payload, choose=choose)
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("ruff-lint")], runner,
    )
    assert code == 0
    assert _row(output, "F401") == "correctness.tool-error"
    assert _severity(output, "F401") == "blocks"
    assert _row(output, "E501") == "correctness.tool-style"
    assert _severity(output, "E501") == "note"
    assert _row(output, "UP032") == "correctness.tool-warning"
    assert _severity(output, "UP032") == "fix-later"
    assert _severity(output, "ZZZ999") == "fix-later"
    assert any("pyproject.toml" not in " ".join(argv) for argv in runner.calls)
    _valid(output)


def test_ruff_isolated_selects_all_and_ignores_a_decoy(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {"app.py": "x = 2\n", "ruff.toml": "[lint]\nignore = [\"F401\"]\n"},
    )
    payload = json.dumps([
        {
            "code": "F401",
            "message": "unused",
            "filename": "app.py",
            "location": {"row": 1},
            "end_location": {"row": 1},
        },
    ])
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("ruff-lint")],
        _Calls(
            base, payload,
            choose=lambda argv, _cwd: (
                T.ProcessResult(0, "[]") if "--isolated" not in argv else None
            ),
        ),
    )
    assert code == 0
    assert _severity(output, "F401") == "blocks"


def test_vulture_dead_code_is_a_note(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = "app.py:1: unused function 'dead'\n"
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("vulture")], _Calls(base, payload),
    )
    assert code == 0
    assert _row(output, "vulture") == "architecture-maintainability.complexity-dead-code-naming"
    assert _severity(output, "vulture") == "note"


def test_import_linter_break_blocks_and_a_base_break_is_absent(tmp_path: Path) -> None:
    contract = "[importlinter]\nroot_package = app\n"
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n", ".importlinter": contract},
        {"app.py": "x = 2\n"},
    )
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("import-linter")],
        _Calls(
            base, "Boundaries BROKEN\n",
            base_payload="Boundaries KEPT\n",
            choose=_outside("--config", ""),
        ),
    )
    assert code == 0
    assert _row(output, "Boundaries") == "architecture-maintainability.structural-check-fails"
    assert _severity(output, "Boundaries") == "blocks"
    repeated = tmp_path / "repeated"
    code = _run(
        repo, base, head, _profile(tmp_path / "again.json"), repeated, tmp_path / "home2",
        [_adapter("import-linter")],
        _Calls(base, "Boundaries BROKEN\n", base_payload="Boundaries BROKEN\n"),
    )
    assert code == 0
    assert _read(repeated, "findings.json") == []


def test_import_linter_without_a_contract_does_not_degrade(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"app.py": "x = 1\n"}, {"app.py": "x = 2\n", ".importlinter": "new\n"}
    )
    output = tmp_path / "out"
    runner = _Calls(base, "Boundaries BROKEN\n")
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("import-linter")], runner,
    )
    assert code == 0
    assert _read(output, "findings.json") == []
    assert "known-gap" not in _reasons(output)
    assert not any("--config" in argv for argv in runner.calls)


def test_cosmic_ray_survivor_on_a_changed_line_blocks(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = json.dumps({"unfinished": False, "survivors": [{"path": "app.py", "line": 1}]})
    home = tmp_path / "home"
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        output, home, [_adapter("cosmic-ray")], _Calls(base, payload),
    )
    assert code == 0
    toml = (home / "cosmic-ray.toml").read_text(encoding="utf-8")
    assert base in toml
    assert "-p no:randomly" in toml
    assert _row(output, "surviving-mutant") == "testing.surviving-mutant"
    assert _severity(output, "surviving-mutant") == "blocks"


def test_cosmic_ray_unfinished_is_reason_cap(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = json.dumps({"unfinished": True, "survivors": [{"path": "app.py", "line": 1}]})
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        output, tmp_path / "home", [_adapter("cosmic-ray")], _Calls(base, payload),
    )
    assert code == 0
    assert "cap" in _reasons(output)
    finding = _read(output, "findings.json")[0]
    assert finding["degraded"] is True
    assert _severity(output, "surviving-mutant") == "fix-later"


def test_cosmic_ray_unchanged_line_is_absent(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, {"app.py": "a\nb\n"}, {"app.py": "a\nB\n"})
    payload = json.dumps({"unfinished": False, "survivors": [{"path": "app.py", "line": 1}]})
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        output, tmp_path / "home", [_adapter("cosmic-ray")], _Calls(base, payload),
    )
    assert code == 0
    assert _read(output, "findings.json") == []


def test_cosmic_ray_empty_command_is_known_gap(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    output = tmp_path / "out"
    runner = _Calls(base, "{}")
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("cosmic-ray"), _adapter("pytest-randomly"), _adapter("pytest-socket")],
        runner,
    )
    assert code == 0
    assert _reasons(output).count("known-gap") == 3
    assert not any("--with" in argv for argv in runner.calls)


def test_pytest_randomly_failure_is_fix_later(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = "FAILED tests/test_app.py::test_one - AssertionError\n"
    output = tmp_path / "out"
    runner = _Calls(base, payload)
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q -p no:randomly"),
        output, tmp_path / "home", [_adapter("pytest-randomly")], runner,
    )
    assert code == 0
    scan = next(argv for argv in runner.calls if "--with" in argv)
    assert "pytest-randomly==5.0.0" in scan
    assert "randomly" in scan
    assert "no:randomly" not in scan
    assert _row(output, "tests/test_app.py::test_one") == "testing.flaky-order-or-network"
    assert _severity(output, "tests/test_app.py::test_one") == "fix-later"


def test_pytest_socket_failure_is_fix_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "example")
    repo, base, head = _changed(tmp_path)
    payload = "FAILED tests/test_app.py::test_net - AssertionError\n"
    output = tmp_path / "out"
    runner = _Calls(base, payload)
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        output, tmp_path / "home", [_adapter("pytest-socket")], runner,
    )
    assert code == 0
    scan = next(argv for argv in runner.calls if "--disable-socket" in argv)
    assert "pytest-socket==0.8.1" in scan
    assert "no:randomly" in scan
    assert "randomly" not in scan
    env = runner.envs[runner.calls.index(scan)]
    assert "GH_TOKEN" not in env
    assert _severity(output, "tests/test_app.py::test_net") == "fix-later"


def test_silence_comments_on_changed_lines_are_recorded(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n", "run.sh": "echo ok\n"},
        {"app.py": "x = 2  # noqa\n# nosec\n", "run.sh": "echo $1  # shellcheck disable=SC2086\n"},
    )
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [], _Calls(base, "{}"),
    )
    assert code == 0
    reasons = {(item["input"], item["reason"]) for item in _read(output, "degraded.json")}
    assert ("app.py", "ruff-noqa") in reasons
    assert ("app.py", "bandit-nosec") in reasons
    assert ("run.sh", "shellcheck-disable") in reasons


@pytest.mark.skipif(
    _probed(["bandit", "--version"]) != "1.9.4",
    reason="bandit pin is not installed",
)
def test_bandit_live_reports_eval_despite_a_decoy(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {
            "app.py": "x = eval(\"1\")  # nosec\n",
            "pyproject.toml": "[tool.bandit]\nskips = [\"B307\"]\n",
        },
    )
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("bandit")], framework=False,
    )
    assert code == 0
    assert any(item["rule"]["ref"] == "B307" for item in _read(output, "findings.json"))
