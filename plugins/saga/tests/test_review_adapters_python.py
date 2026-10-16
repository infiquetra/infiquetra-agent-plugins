"""Python adapters map recorded output onto the lens rows (issue 152)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import replace
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
    if (
        len(argv) >= 4
        and argv[:3] == ["uv", "run", "--with"]
        and argv[3].startswith("ruff==")
        and "--version" in argv
    ):
        return argv[3].split("==", 1)[1]
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


def _pinned_ruff_cached() -> bool:
    """The ruff pin is already in the uv cache. `--offline` forbids any fetch."""
    pin = _adapter("ruff-lint").default_version
    try:
        proc = subprocess.run(
            ["uv", "run", "--offline", "--with", f"ruff=={pin}", "ruff", "--version"],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    match = _VERSION.search((proc.stdout or "") + (proc.stderr or ""))
    return bool(match and match.group(0) == pin)


_COSMIC_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cosmic-ray-8.7.0-dump.jsonl"


def _usable_python() -> str | None:
    """This interpreter when it can run pytest, else None (the card's skip)."""

    try:
        import pytest as _pytest  # noqa: F401
    except ImportError:
        return None
    return sys.executable


_STUB_COSMIC_BODY = '''\
import json
import os
import shlex
import subprocess
import sys
import tomllib


def _record(name):
    record = os.environ.get("STUB_RECORD")
    if record:
        with open(record, "a", encoding="utf-8") as handle:
            handle.write(name + "\\n")


def main(argv):
    _record(argv[1])
    if argv[1] == "init":
        with open(argv[3], "w", encoding="utf-8") as handle:
            handle.write("stub-session")
        return 0
    if argv[1] == "exec":
        if os.environ.get("STUB_EXECUTE") == "1":
            with open(argv[2], "rb") as handle:
                command = tomllib.load(handle)["cosmic-ray"]["test-command"]
            with open(os.environ["STUB_COMMAND"], "w", encoding="utf-8") as handle:
                handle.write(command)
            try:
                proc = subprocess.run(shlex.split(command), capture_output=True, timeout=120)
            except FileNotFoundError:
                outcome = "incompetent"
            else:
                outcome = "survived" if proc.returncode == 0 else "killed"
            with open(os.environ["STUB_OUTCOME"], "w", encoding="utf-8") as handle:
                handle.write(outcome)
        return int(os.environ.get("STUB_EXEC_EXIT", "0"))
    if argv[1] == "dump":
        if os.environ.get("STUB_EXECUTE") == "1":
            with open(os.environ["STUB_OUTCOME"], encoding="utf-8") as handle:
                outcome = handle.read().strip()
            mutation = {"module_path": "app.py", "start_pos": [2, 16]}
            work = {"job_id": "stub", "mutations": [mutation]}
            result = {"worker_outcome": "normal", "output": "", "test_outcome": outcome, "diff": ""}
            print(json.dumps([work, result]))
        else:
            with open(os.environ["STUB_DUMP"], encoding="utf-8") as handle:
                sys.stdout.write(handle.read())
        return int(os.environ.get("STUB_DUMP_EXIT", "0"))
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


_STUB_FILTER_BODY = '''\
import os
import sys

record = os.environ.get("STUB_RECORD")
if record:
    with open(record, "a", encoding="utf-8") as handle:
        handle.write("filter " + " ".join(sys.argv[2:]).split(" ")[0] + "\\n")
raise SystemExit(int(os.environ.get("STUB_FILTER_EXIT", "0")))
'''


def _write_cosmic_stub(path: Path) -> Path:
    path.write_text(f"#!{sys.executable}\n" + _STUB_COSMIC_BODY, encoding="utf-8")
    path.chmod(0o755)
    # cr-filter-git ships with cosmic-ray; the wrapper runs it between init and exec.
    scoped = path.parent / "cr-filter-git"
    scoped.write_text(f"#!{sys.executable}\n" + _STUB_FILTER_BODY, encoding="utf-8")
    scoped.chmod(0o755)
    return path


def _wrapper_config(path: Path, command: str) -> Path:
    path.write_text(f"[cosmic-ray]\ntest-command = {json.dumps(command)}\n", encoding="utf-8")
    return path


def _wrapper_env(stub_dir: Path, extra_dirs: tuple[Path, ...], **stub_vars: str) -> dict[str, str]:
    env = dict(os.environ)
    path = [str(item) for item in (*extra_dirs, stub_dir)] + [env.get("PATH", "")]
    env["PATH"] = os.pathsep.join(part for part in path if part)
    env.update(stub_vars)
    return env


def _run_wrapper(
    config: Path, workdir: Path, env: dict[str, str], *extra: str
) -> Any:
    argv = [sys.executable, "-c", P._COSMIC_WRAPPER, str(config), *extra]
    proc = subprocess.run(argv, cwd=workdir, env=env, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


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


class _PinnedRuffCalls(_Calls):
    """PATH ruff answers 0.16.9; the pinned uv probe answers the row pin."""

    def __init__(
        self, base: str, payload: str, *, pin: str, uv_missing: bool = False, **kwargs: Any
    ) -> None:
        super().__init__(base, payload, **kwargs)
        self.pin = pin
        self.uv_missing = uv_missing

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False
        assert isinstance(argv, list)
        if argv[:2] == ["uv", "run"]:
            self.calls.append(list(argv))
            self.envs.append(dict(env))
            if self.uv_missing:
                raise FileNotFoundError("uv")
            return T.ProcessResult(0, f"ruff {self.pin}\n")
        if argv == ["ruff", "--version"]:
            self.calls.append(list(argv))
            self.envs.append(dict(env))
            return T.ProcessResult(0, "ruff 0.16.9\n")
        return super().__call__(argv, cwd=cwd, env=env, timeout=timeout, shell=shell)


def _ruff_payload() -> str:
    return json.dumps([
        {
            "code": "F401",
            "message": "unused",
            "filename": "app.py",
            "location": {"row": 1},
            "end_location": {"row": 1},
        },
    ])


def _ruff_scan_inner(calls: list[list[str]]) -> list[str]:
    scans = [argv for argv in calls if argv[:2] == ["python3", "-c"] and "--" in argv]
    assert len(scans) == 1, calls
    return scans[0][scans[0].index("--") + 1:]


def test_pinned_ruff_runs_the_pin_despite_path_ruff(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    output = tmp_path / "out"
    runner = _PinnedRuffCalls(base, _ruff_payload(), pin="0.15.18")
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("ruff-lint")], runner,
    )
    assert code == 0
    assert _severity(output, "F401") == "blocks"
    assert "version-mismatch" not in _reasons(output)
    inner = _ruff_scan_inner(runner.calls)
    assert inner[:4] == ["uv", "run", "--with", "ruff==0.15.18"]
    assert inner[4:8] == ["ruff", "check", "--isolated", "--ignore-noqa"]
    assert not any(argv[:1] == ["ruff"] for argv in runner.calls)
    _valid(output)


def test_pinned_ruff_spec_matches_the_row_pin(tmp_path: Path) -> None:
    adapter = _adapter("ruff-lint")
    assert adapter.default_version == "0.15.18"
    assert adapter.version_argv == (
        "uv", "run", "--with", "ruff==0.15.18", "ruff", "--version",
    )
    context = T.ScanContext(tmp_path, tmp_path, tmp_path)
    argv = adapter.invoke(context)
    inner = argv[argv.index("--") + 1:]
    assert inner[:4] == ["uv", "run", "--with", f"ruff=={adapter.default_version}"]
    assert inner[-1] == str(tmp_path)


def test_pinned_ruff_missing_uv_degrades_without_path_fallback(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    output = tmp_path / "out"
    runner = _PinnedRuffCalls(base, _ruff_payload(), pin="0.15.18", uv_missing=True)
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("ruff-lint")], runner,
    )
    assert code == 0
    assert "missing" in _reasons(output)
    assert not any(argv[:1] == ["ruff"] for argv in runner.calls)


def test_pinned_ruff_profile_pin_stays_check_only(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"review_tools": {"pins": {"ruff": {"version": "0.15.19"}}}}),
        encoding="utf-8",
    )
    output = tmp_path / "out"
    runner = _PinnedRuffCalls(base, _ruff_payload(), pin="0.15.18")
    code = _run(
        repo, base, head, profile, output, tmp_path / "home",
        [_adapter("ruff-lint")], runner,
    )
    assert code == 0
    assert "version-mismatch" in _reasons(output)
    inner = _ruff_scan_inner(runner.calls)
    assert inner[:4] == ["uv", "run", "--with", "ruff==0.15.18"]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_pinned_ruff_offline_wrapper_keeps_scan_and_probe_offline(tmp_path: Path) -> None:
    plain = _adapter("ruff-lint")
    offline = _offline_ruff(plain)
    cache = _uv_cache_dir()
    assert offline.version_argv == (
        "uv", "run", "--offline", "--cache-dir", cache, *plain.version_argv[2:],
    )
    context = T.ScanContext(tmp_path, tmp_path, tmp_path)
    argv = offline.invoke(context)
    inner = argv[argv.index("--") + 1 :]
    assert inner[:6] == ["uv", "run", "--offline", "--cache-dir", cache, "--with"]
    plain_inner = plain.invoke(context)
    plain_inner = plain_inner[plain_inner.index("--") + 1 :]
    assert inner[6:] == plain_inner[3:]


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


def test_cosmic_ray_module_path_lists_every_changed_python_file(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {
            "app.py": "x = 1\n",
            "other.py": "y = 1\n",
            "keep.py": "z = 1\n",
            "pkg/nested.py": "n = 1\n",
        },
        {
            "app.py": "x = 2\n",
            "other.py": "y = 2\n",
            "keep.py": "z = 1\n",
            "pkg/nested.py": "n = 2\n",
        },
    )
    payload = json.dumps({"unfinished": False, "survivors": []})
    home = tmp_path / "home"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        tmp_path / "out", home, [_adapter("cosmic-ray")], _Calls(base, payload),
    )
    assert code == 0
    toml = (home / "cosmic-ray.toml").read_text(encoding="utf-8")
    assert 'module-path = ["app.py", "other.py", "pkg/nested.py"]' in toml
    assert "keep.py" not in toml


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


def _distribution(name: str) -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover
        return None
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _installed(adapter: Any) -> Any:
    """Call the tool already on PATH. A live check must not ``uv run --with`` a download."""

    def invoke(context: Any) -> list[str]:
        argv = list(adapter.invoke(context))
        if argv[:2] == ["uv", "run"] and "--with" in argv:
            return argv[argv.index("--with") + 2:]
        return argv

    return replace(adapter, invoke=invoke)


def _uv_cache_dir() -> str:
    """The operator uv cache. `uv cache dir` is local and never touches the network."""
    proc = subprocess.run(
        ["uv", "cache", "dir"], capture_output=True, text=True, timeout=20, check=False
    )
    assert proc.returncode == 0, "uv cache dir is unavailable"
    return (proc.stdout or "").strip()


def _offline_ruff(adapter: Any) -> Any:
    """Run the pinned ruff adapter offline against the gate's cache.

    The review runs tools under a fresh HOME whose uv cache is empty, so an
    unmodified live run would fetch the pin exactly when the cache gate passes.
    The wrapper adds `--offline` and the gate's `--cache-dir` to the scan and
    the version probe; `--offline` forbids any fetch.
    """
    cache = _uv_cache_dir()

    def invoke(context: Any) -> list[str]:
        argv = list(adapter.invoke(context))
        at = argv.index("uv")
        assert argv[at + 1] == "run"
        return [*argv[: at + 2], "--offline", "--cache-dir", cache, *argv[at + 2 :]]

    probe = list(adapter.version_argv)
    assert probe[:2] == ["uv", "run"]
    return replace(
        adapter,
        invoke=invoke,
        version_argv=tuple([*probe[:2], "--offline", "--cache-dir", cache, *probe[2:]]),
    )


def _live(
    repo: Path, base: str, head: str, tmp: Path, adapter: Any, command: str | None = None,
) -> Path:
    output = tmp / "out"
    home = tmp / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp / "profile.json", command), output,
        home=home, adapters=[adapter], framework=False,
    )
    assert code == 0
    return output


@pytest.mark.skipif(_probed(["mypy", "--version"]) != "2.1.0", reason="mypy pin is not installed")
def test_mypy_live_reports_a_type_error_despite_a_decoy(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {"app.py": "x: int = 'no'\n", "pyproject.toml": "[tool.mypy]\nignore_errors = true\n"},
    )
    output = _live(repo, base, head, tmp_path, _adapter("mypy"))
    rows = {item["rule"]["row"] for item in _read(output, "findings.json")}
    assert "correctness.type-error" in rows


@pytest.mark.skipif(
    not _pinned_ruff_cached(),
    reason="ruff pin is not in the uv cache; offline run skipped",
)
def test_ruff_live_reports_an_unused_import_despite_a_decoy(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {"app.py": "import os\n", "pyproject.toml": "[tool.ruff.lint]\nselect = []\n"},
    )
    output = _live(repo, base, head, tmp_path, _offline_ruff(_adapter("ruff-lint")))
    assert "F401" in {item["rule"]["ref"] for item in _read(output, "findings.json")}


@pytest.mark.skipif(
    _probed(["vulture", "--version"]) != "2.16", reason="vulture pin is not installed"
)
def test_vulture_live_reports_dead_code_despite_a_decoy(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {
            "app.py": "def unused():\n    return 1\n",
            "pyproject.toml": "[tool.vulture]\nignore_names = ['unused']\n",
        },
    )
    output = _live(repo, base, head, tmp_path, _adapter("vulture"))
    assert "vulture" in {item["rule"]["ref"] for item in _read(output, "findings.json")}


@pytest.mark.skipif(
    _probed(["lint-imports", "--version"]) != "2.15",
    reason="import-linter pin is not installed",
)
def test_import_linter_live_reports_a_broken_contract_despite_a_decoy(tmp_path: Path) -> None:
    contract = (
        "[importlinter]\nroot_packages =\n    pkg\n\n"
        "[importlinter:contract:1]\nname = High stays above low\ntype = forbidden\n"
        "source_modules =\n    pkg.high\nforbidden_modules =\n    pkg.low\n"
    )
    repo, base, head = _repo(
        tmp_path,
        {
            ".importlinter": contract,
            "pkg/__init__.py": "",
            "pkg/high.py": "value = 1\n",
            "pkg/low.py": "value = 1\n",
        },
        {
            ".importlinter": "[importlinter]\nroot_packages =\n    pkg\n",
            "pkg/__init__.py": "",
            "pkg/high.py": "from pkg.low import value\n",
            "pkg/low.py": "value = 1\n",
        },
    )
    output = _live(repo, base, head, tmp_path, _adapter("import-linter"))
    assert "High stays above low" in {
        item["rule"]["ref"] for item in _read(output, "findings.json")
    }


@pytest.mark.skipif(
    _probed(["cosmic-ray", "--version"]) != "8.7.0",
    reason="cosmic-ray pin is not installed",
)
def test_cosmic_ray_live_records_a_survivor(tmp_path: Path) -> None:
    exe = _usable_python()
    if exe is None:
        pytest.skip("no usable Python with pytest")
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "def add(left, right):\n    return left\n"},
        {
            "app.py": "def add(left, right):\n    return left + right\n",
            "test_app.py": "from app import add\n\ndef test_add():\n    assert True\n",
        },
    )
    output = _live(
        repo, base, head, tmp_path, _installed(_adapter("cosmic-ray")),
        f"{exe} -m pytest -q",
    )
    assert "surviving-mutant" in {item["rule"]["ref"] for item in _read(output, "findings.json")}


@pytest.mark.skipif(
    _distribution("pytest-randomly") != "5.0.0",
    reason="pytest-randomly pin is not installed",
)
def test_pytest_randomly_live_failure_is_fix_later(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {"app.py": "x = 1\n", "test_app.py": "def test_one():\n    assert False\n"},
    )
    output = _live(
        repo, base, head, tmp_path, _installed(_adapter("pytest-randomly")),
        "python -m pytest -q",
    )
    assert _severity(output, "test_app.py::test_one") == "fix-later"


@pytest.mark.skipif(
    _distribution("pytest-socket") != "0.8.1",
    reason="pytest-socket pin is not installed",
)
def test_pytest_socket_live_failure_is_fix_later(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "x = 1\n"},
        {
            "app.py": "x = 1\n",
            "test_app.py": (
                "def test_net():\n"
                "    import socket\n"
                "    socket.create_connection(('example.invalid', 9))\n"
            ),
        },
    )
    output = _live(
        repo, base, head, tmp_path, _installed(_adapter("pytest-socket")),
        "python -m pytest -q",
    )
    assert _severity(output, "test_app.py::test_net") == "fix-later"


def test_cosmic_ray_config_carries_the_distributor(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    home = tmp_path / "home"
    payload = json.dumps({"unfinished": False, "survivors": []})
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        tmp_path / "out", home, [_adapter("cosmic-ray")], _Calls(base, payload),
    )
    assert code == 0
    toml = (home / "cosmic-ray.toml").read_text(encoding="utf-8")
    assert '[cosmic-ray.distributor]\nname = "local"' in toml
    assert 'module-path = ["app.py"]' in toml
    assert base in toml


@pytest.mark.skipif(
    _probed(["cosmic-ray", "--version"]) != "8.7.0",
    reason="cosmic-ray pin is not installed",
)
def test_cosmic_ray_exec_on_the_generated_config_exits_zero(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "def add(left, right):\n    return left\n"},
        {
            "app.py": "def add(left, right):\n    return left + right\n",
            "test_app.py": "from app import add\n\ndef test_add():\n    assert True\n",
        },
    )
    home = tmp_path / "home"
    payload = json.dumps({"unfinished": False, "survivors": []})
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        tmp_path / "out", home, [_adapter("cosmic-ray")], _Calls(base, payload),
    )
    assert code == 0
    toml = home / "cosmic-ray.toml"
    session = home / "generated.sqlite"
    init = subprocess.run(
        ["cosmic-ray", "init", str(toml), str(session)],
        cwd=repo, capture_output=True, text=True, timeout=120, check=False,
    )
    assert init.returncode == 0, init.stderr[-2000:]
    ran = subprocess.run(
        ["cosmic-ray", "exec", str(toml), str(session)],
        cwd=repo, capture_output=True, text=True, timeout=600, check=False,
    )
    assert ran.returncode == 0, ran.stderr[-2000:]


def test_cosmic_ray_wrapper_head_is_the_current_interpreter(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    payload = json.dumps({"unfinished": False, "survivors": []})
    runner = _Calls(base, payload)
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        tmp_path / "out", tmp_path / "home", [_adapter("cosmic-ray")], runner,
    )
    assert code == 0
    scan = next(argv for argv in runner.calls if "--with" in argv)
    stripped = scan[scan.index("--with") + 2:]
    assert stripped[0] == sys.executable


def test_cosmic_ray_generated_config_shares_the_baseline_timeout(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    home = tmp_path / "home"
    payload = json.dumps({"unfinished": False, "survivors": []})
    runner = _Calls(base, payload)
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        tmp_path / "out", home, [_adapter("cosmic-ray")], runner,
    )
    assert code == 0
    toml = (home / "cosmic-ray.toml").read_text(encoding="utf-8")
    assert "timeout = 300.0" in toml
    scan = next(argv for argv in runner.calls if "--with" in argv)
    assert scan[-1] == "300"


def test_cosmic_ray_array_dump_yields_one_finding_per_survivor(tmp_path: Path) -> None:
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    env = _wrapper_env(stub_dir, (), STUB_DUMP=str(_COSMIC_FIXTURE))
    config = _wrapper_config(tmp_path / "cosmic-ray.toml", f"{sys.executable} -c pass")
    out = _run_wrapper(config, tmp_path, env)
    assert out["unfinished"] is False
    assert out["survivors"] == [{"path": "app.py", "line": 2}]


def test_cosmic_ray_array_dump_without_a_position_is_unfinished(tmp_path: Path) -> None:
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    dump = tmp_path / "dump.txt"
    row = [
        {"job_id": "x", "mutations": []},
        {"worker_outcome": "normal", "output": "", "test_outcome": "survived", "diff": ""},
    ]
    dump.write_text(json.dumps(row) + "\n", encoding="utf-8")
    env = _wrapper_env(stub_dir, (), STUB_DUMP=str(dump))
    config = _wrapper_config(tmp_path / "cosmic-ray.toml", f"{sys.executable} -c pass")
    out = _run_wrapper(config, tmp_path, env)
    assert out["unfinished"] is True
    assert out["survivors"] == []


@pytest.mark.parametrize(
    ("worker", "test", "raw"),
    [
        pytest.param("exception", None, None, id="worker-exception"),
        pytest.param("abnormal", None, None, id="worker-abnormal"),
        pytest.param("no-test", None, None, id="worker-no-test"),
        pytest.param("normal", "incompetent", None, id="test-incompetent"),
        pytest.param(None, None, "null-result", id="pending-null"),
        pytest.param("normal", None, None, id="null-test-outcome"),
        pytest.param(None, None, "garbage", id="garbage-line"),
    ],
)
def test_cosmic_ray_errored_mutant_marks_the_run_unfinished(
    tmp_path: Path, worker: str | None, test: str | None, raw: str | None
) -> None:
    mutation = {"module_path": "app.py", "start_pos": [2, 16]}
    survivor = [
        {"job_id": "s", "mutations": [mutation]},
        {"worker_outcome": "normal", "output": "", "test_outcome": "survived", "diff": ""},
    ]
    if raw == "garbage":
        error = "not-json{"
    elif raw == "null-result":
        error = json.dumps([{"job_id": "p", "mutations": [mutation]}, None])
    else:
        error = json.dumps([
            {"job_id": "e", "mutations": [mutation]},
            {"worker_outcome": worker, "output": "", "test_outcome": test, "diff": ""},
        ])
    dump = tmp_path / "dump.txt"
    dump.write_text(json.dumps(survivor) + "\n" + error + "\n", encoding="utf-8")
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    env = _wrapper_env(stub_dir, (), STUB_DUMP=str(dump))
    config = _wrapper_config(tmp_path / "cosmic-ray.toml", f"{sys.executable} -c pass")
    out = _run_wrapper(config, tmp_path, env)
    assert out["unfinished"] is True
    assert out["survivors"] == [{"path": "app.py", "line": 2}]


def test_cosmic_ray_failing_baseline_marks_the_run_unfinished(tmp_path: Path) -> None:
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    record = tmp_path / "record.txt"
    env = _wrapper_env(
        stub_dir, (), STUB_DUMP=str(_COSMIC_FIXTURE), STUB_RECORD=str(record)
    )
    red = _wrapper_config(
        tmp_path / "red.toml", f"{sys.executable} -c 'raise SystemExit(1)'"
    )
    out = _run_wrapper(red, tmp_path, env)
    assert out["unfinished"] is True
    assert out["survivors"] == []
    assert not record.exists()
    pid_file = tmp_path / "grandchild.pid"
    grand = tmp_path / "grand.py"
    grand.write_text(
        "import os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    spawn = tmp_path / "spawn.py"
    spawn.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([{sys.executable!r}, {str(grand)!r}])\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    slow = _wrapper_config(
        tmp_path / "slow.toml", f"{sys.executable} {shlex.quote(str(spawn))}"
    )
    out = _run_wrapper(slow, tmp_path, env, "1")
    assert out["unfinished"] is True
    assert out["survivors"] == []
    assert not record.exists()
    grand_pid = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.time() + 10
    while True:
        try:
            os.kill(grand_pid, 0)
        except ProcessLookupError:
            break
        if time.time() > deadline:
            raise AssertionError("timed-out baseline left a grandchild running")
        time.sleep(0.05)


def test_cosmic_ray_passing_baseline_runs_the_stages_in_order(tmp_path: Path) -> None:
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    record = tmp_path / "record.txt"
    dump = tmp_path / "dump.txt"
    mutation = {"module_path": "app.py", "start_pos": [2, 16]}
    row = [
        {"job_id": "k", "mutations": [mutation]},
        {"worker_outcome": "normal", "output": "", "test_outcome": "killed", "diff": ""},
    ]
    dump.write_text(json.dumps(row) + "\n", encoding="utf-8")
    env = _wrapper_env(stub_dir, (), STUB_DUMP=str(dump), STUB_RECORD=str(record))
    config = _wrapper_config(tmp_path / "cosmic-ray.toml", f"{sys.executable} -c pass")
    out = _run_wrapper(config, tmp_path, env)
    assert out["unfinished"] is False
    assert out["survivors"] == []
    assert record.read_text(encoding="utf-8").splitlines() == [
        "init", "filter --config", "exec", "dump",
    ]


def test_cosmic_ray_dump_failure_marks_the_run_unfinished(tmp_path: Path) -> None:
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    env = _wrapper_env(stub_dir, (), STUB_DUMP=str(_COSMIC_FIXTURE), STUB_DUMP_EXIT="1")
    config = _wrapper_config(tmp_path / "cosmic-ray.toml", f"{sys.executable} -c pass")
    out = _run_wrapper(config, tmp_path, env)
    assert out["unfinished"] is True


def test_cosmic_ray_test_command_resolves_bare_python(tmp_path: Path) -> None:
    import tomllib

    for command in ("python -m pytest -q", "python3 -m pytest -q"):
        tag = command.split()[0]
        parent = tmp_path / tag
        parent.mkdir()
        repo, base, head = _repo(parent, {"app.py": "x = 1\n"}, {"app.py": "x = 2\n"})
        home = tmp_path / f"home-{tag}"
        payload = json.dumps({"unfinished": False, "survivors": []})
        code = _run(
            repo, base, head, _profile(tmp_path / f"profile-{tag}.json", command),
            tmp_path / f"out-{tag}", home,
            [_adapter("cosmic-ray")], _Calls(base, payload),
        )
        assert code == 0
        with open(home / "cosmic-ray.toml", "rb") as handle:
            written = tomllib.load(handle)["cosmic-ray"]["test-command"]
        assert written == f"{sys.executable} -m pytest -q -p no:randomly"
    passthrough = (
        ("pytest -q", "pytest"),
        ("make test", "make"),
        ("/usr/bin/python -m pytest -q", "/usr/bin/python"),
    )
    for command, head in passthrough:
        tag = head.replace("/", "_")
        parent = tmp_path / tag
        parent.mkdir()
        repo, base, head_sha = _repo(parent, {"app.py": "x = 1\n"}, {"app.py": "x = 2\n"})
        home = tmp_path / f"home-{tag}"
        payload = json.dumps({"unfinished": False, "survivors": []})
        code = _run(
            repo, base, head_sha, _profile(tmp_path / f"profile-{tag}.json", command),
            tmp_path / f"out-{tag}", home,
            [_adapter("cosmic-ray")], _Calls(base, payload),
        )
        assert code == 0
        with open(home / "cosmic-ray.toml", "rb") as handle:
            written = tomllib.load(handle)["cosmic-ray"]["test-command"]
        assert written.split()[0] == head


def test_cosmic_ray_worker_imports_pytest(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"app.py": "def add(left, right):\n    return left\n"},
        {
            "app.py": "def add(left, right):\n    return left + right\n",
            "test_app.py": "from app import add\n\ndef test_add():\n    assert True\n",
        },
    )
    home = tmp_path / "home"
    payload = json.dumps({"unfinished": False, "survivors": []})
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        tmp_path / "out", home, [_adapter("cosmic-ray")], _Calls(base, payload),
    )
    assert code == 0
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "python"
    shim.write_text('#!/bin/sh\necho "No module named pytest" >&2\nexit 1\n', encoding="utf-8")
    shim.chmod(0o755)
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    seen = tmp_path / "command.txt"
    env = _wrapper_env(
        stub_dir, (shim_dir,), STUB_EXECUTE="1",
        STUB_OUTCOME=str(tmp_path / "outcome.txt"), STUB_COMMAND=str(seen),
        STUB_RECORD=str(tmp_path / "record.txt"),
    )
    out = _run_wrapper(home / "cosmic-ray.toml", repo, env, "300")
    assert out["unfinished"] is False
    assert out["survivors"] == [{"path": "app.py", "line": 2}]
    assert seen.read_text(encoding="utf-8").startswith(sys.executable)


def test_cosmic_ray_usable_python_is_the_current_interpreter() -> None:
    assert _usable_python() == sys.executable


def test_cosmic_ray_usable_python_is_none_without_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pytest", None)
    assert _usable_python() is None


def test_pytest_randomly_resolves_bare_python(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    runner = _Calls(base, "")
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        tmp_path / "out", tmp_path / "home", [_adapter("pytest-randomly")], runner,
    )
    assert code == 0
    scan = next(argv for argv in runner.calls if "--with" in argv)
    assert scan[scan.index("--with") + 2] == sys.executable


def test_pytest_socket_resolves_bare_python(tmp_path: Path) -> None:
    repo, base, head = _changed(tmp_path)
    runner = _Calls(base, "")
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
        tmp_path / "out", tmp_path / "home", [_adapter("pytest-socket")], runner,
    )
    assert code == 0
    scan = next(argv for argv in runner.calls if "--with" in argv)
    assert scan[scan.index("--with") + 2] == sys.executable


def test_cosmic_ray_skips_mutants_off_the_change(tmp_path: Path) -> None:
    """Issue 244: cr-filter-git marks off-change mutants skipped; they are neither run nor unfinished."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    dump = tmp_path / "dump.txt"
    rows = [
        [
            {"job_id": "off", "mutations": [{"module_path": "app.py", "start_pos": [9, 0]}]},
            {"worker_outcome": "skipped", "output": "Filtered git", "test_outcome": None},
        ],
        [
            {"job_id": "on", "mutations": [{"module_path": "app.py", "start_pos": [2, 16]}]},
            {"worker_outcome": "normal", "output": "", "test_outcome": "survived", "diff": ""},
        ],
    ]
    dump.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    env = _wrapper_env(stub_dir, (), STUB_DUMP=str(dump))
    config = _wrapper_config(tmp_path / "cosmic-ray.toml", f"{sys.executable} -c pass")
    out = _run_wrapper(config, tmp_path, env)
    assert out == {"unfinished": False, "survivors": [{"path": "app.py", "line": 2}]}


def test_cosmic_ray_failed_filter_marks_the_run_unfinished(tmp_path: Path) -> None:
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    _write_cosmic_stub(stub_dir / "cosmic-ray")
    record = tmp_path / "record.txt"
    env = _wrapper_env(
        stub_dir, (), STUB_DUMP=str(_COSMIC_FIXTURE), STUB_FILTER_EXIT="1",
        STUB_RECORD=str(record),
    )
    config = _wrapper_config(tmp_path / "cosmic-ray.toml", f"{sys.executable} -c pass")
    out = _run_wrapper(config, tmp_path, env)
    assert out["unfinished"] is True
    assert "exec" not in record.read_text(encoding="utf-8").splitlines()


def test_pytest_randomly_seed_is_fixed_by_the_change(tmp_path: Path) -> None:
    """Issue 244: two runs of one change test one order."""
    repo, base, head = _repo(tmp_path, {"app.py": "x = 1\n"}, {"app.py": "x = 2\n"})
    seeds = []
    for attempt in (1, 2):
        runner = _Calls(base, "1 passed\n")
        _run(
            repo, base, head,
            _profile(tmp_path / f"profile-{attempt}.json", "python -m pytest -q"),
            tmp_path / f"out-{attempt}", tmp_path / "home", [_adapter("pytest-randomly")], runner,
        )
        scan = next(call for call in runner.calls if "pytest-randomly==5.0.0" in call)
        seeds.append([item for item in scan if item.startswith("--randomly-seed=")])
    assert seeds[0] == seeds[1] and len(seeds[0]) == 1


def test_bandit_stored_report_drops_its_timestamp() -> None:
    """Issue 244: bandit stamps generated_at, so its hash changed on every run."""
    one = json.dumps({"generated_at": "2026-10-16T03:30:11Z", "results": [], "errors": []})
    two = json.dumps({"generated_at": "2026-10-16T03:31:57Z", "results": [], "errors": []})
    adapter = _adapter("bandit")
    assert T._stable_raw(adapter, one) == T._stable_raw(adapter, two)
    assert "generated_at" not in T._stable_raw(adapter, one)


def _pytest_transcript(root: Path, seconds: str) -> str:
    """A pytest run as it prints: the scan root in the header, the duration in the summary."""
    return (
        "============================= test session starts ==============================\n"
        f"rootdir: {root}\n"
        "plugins: randomly-5.0.0\n"
        "collected 4 items\n\n"
        "tests/test_app.py .F                                                    [100%]\n\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_app.py::test_one - AssertionError\n"
        f"========================= 1 failed, 3 passed in {seconds} ==========================\n"
    )


@pytest.mark.parametrize("tool_id", ["pytest-randomly", "pytest-socket"])
def test_pytest_runs_differing_only_in_duration_record_identical_bytes(
    tmp_path: Path, tool_id: str,
) -> None:
    """Issue 244: pytest ends "1 failed in 0.01s", so the stored transcript's hash moved."""
    repo, base, head = _changed(tmp_path)
    outputs = []
    for run, seconds in enumerate(("0.05s", "12.31s (0:00:12)")):
        def choose(argv: list[str], cwd: Path, seconds: str = seconds) -> Any:
            if "--with" not in argv:
                return None
            return T.ProcessResult(1, _pytest_transcript(cwd, seconds))

        output = tmp_path / f"out-{run}"
        assert _run(
            repo, base, head, _profile(tmp_path / "profile.json", "python -m pytest -q"),
            output, tmp_path / "home", [_adapter(tool_id)], _Calls(base, "", choose=choose),
        ) == 0
        outputs.append(output)
    assert _read(outputs[0], "findings.json")
    for name in ("findings.json", "degraded.json", "outcomes.json"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), name
