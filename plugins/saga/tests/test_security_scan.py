"""Independent contract for the whole-repository security scan (issue 321, unit U1).

This file is written before ``plugins/saga/scripts/security_scan.py`` exists. It drives the
public command line the way a user runs it, with fake scanner binaries, a private ``HOME``
and a ``PATH`` that holds nothing else, so no real scanner, advisory service or credential is
ever reached. Every fixture value is an inert example string.

Choices this suite pins where the plan names a behaviour but not its spelling:

* ``summary.json`` holds ``commit`` (the named commit, never the snapshot commit),
  ``exit_code``, ``rows`` and ``advisory_service_rows``. Each row has ``id``, ``status``
  (``ran``, ``skipped`` or ``degraded``), ``reason``, ``version``, ``pin`` (the resolved pin,
  ``not-recorded`` when none is recorded) and ``counts`` keyed ``blocks``, ``fix-later``
  and ``note``. ``summary.md`` is the readable form and prints each finding as ``file:line``.
* ``findings.json`` is the list of ``review_records.v1`` findings the runner already writes.
* Reasons reuse the runner's words: ``missing``, ``version-mismatch``, ``version-unreadable``,
  ``timeout``, ``unparseable``, ``rule-cache-missing`` and ``rule-cache-mismatch``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN = REPO_ROOT / "plugins" / "saga"
SCRIPTS = PLUGIN / "scripts"
SCAN = SCRIPTS / "security_scan.py"
SKILL = PLUGIN / "skills" / "security-scan" / "SKILL.md"
PORT = REPO_ROOT / "ports" / "saga.json"
CATALOGUE = PLUGIN / "references" / "review-tools.yaml"
REAL_GIT = shutil.which("git") or "/usr/bin/git"

#: Text the fake gitleaks looks for. It is a plain marker, not credential shaped.
MARKER = "INERT_HISTORY_MARKER"
#: What the fake gitleaks puts in ``Match`` and ``Secret``. It must never be persisted.
MATCH = "INERT_SENTINEL_MATCH_DO_NOT_PERSIST"
CREDENTIAL = "INERT_CREDENTIAL_SENTINEL_VALUE"
SYNTHESIZED = ("cdk-nag", "checkov-cdk")
ADVISORY = ("osv-scanner", "pip-audit", "npm-audit")
LEVELS = ("blocks", "fix-later", "note")

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "scan-fixture",
    "GIT_AUTHOR_EMAIL": "scan-fixture@example.com",
    "GIT_COMMITTER_NAME": "scan-fixture",
    "GIT_COMMITTER_EMAIL": "scan-fixture@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}

# ---------------------------------------------------------------------------------------
# Fake tool binaries
# ---------------------------------------------------------------------------------------

_STUB = """\
#!__PYTHON__
import json, os, pathlib, subprocess, sys, time

here = pathlib.Path(__file__).resolve().parent
name = pathlib.Path(sys.argv[0]).name
config = json.loads((here / (name + ".stub.json")).read_text(encoding="utf-8"))
args = sys.argv[1:]
cwd = pathlib.Path.cwd()
root = pathlib.Path(args[-1]) if args and os.path.isdir(args[-1]) else cwd
watched = (".gitleaksignore", ".semgrepignore", ".gitleaks.toml")
entry = {
    "tool": name, "argv": args, "cwd": str(cwd), "home": os.environ.get("HOME"),
    "credential": os.environ.get("INERT_CREDENTIAL_SENTINEL"),
    "seen": [n for n in watched if (root / n).exists() or (cwd / n).exists()],
}
if config.get("log_tree"):
    tree = subprocess.run(
        [config["git"], "-C", str(root), "ls-tree", "-r", "HEAD"],
        capture_output=True, text=True,
    )
    entry["tree"] = tree.stdout
with (here / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry) + "\\n")

if "--version" in args:
    if config.get("version_exit", 0):
        sys.stderr.write("stub version failure\\n")
        raise SystemExit(config["version_exit"])
    sys.stdout.write(config.get("version_text", config.get("version", "0.0.0")) + "\\n")
    raise SystemExit(0)

if config.get("sentinel"):
    pathlib.Path(config["sentinel"]).write_text("ran\\n", encoding="utf-8")
if config.get("chmod_readonly"):
    os.chmod(config["chmod_readonly"], 0o500)
if config.get("sleep"):
    time.sleep(config["sleep"])
if "--output" in args:
    out = pathlib.Path(args[args.index("--output") + 1])
    out.mkdir(parents=True, exist_ok=True)
    for rel, body in (config.get("synth_files") or {}).items():
        (out / rel).write_text(json.dumps(body), encoding="utf-8")


def walk(marker, directory):
    found = {}

    def git(*a, text=True):
        return subprocess.run(
            [config["git"], "-c", "core.quotepath=off", "-C", str(directory), *a],
            capture_output=True, text=text,
        )

    commits = git("rev-list", "--all")
    if commits.returncode == 0:
        for commit in commits.stdout.split():
            for path in git("ls-tree", "-r", "--name-only", commit).stdout.splitlines():
                blob = git("show", commit + ":" + path, text=False)
                if blob.returncode != 0:
                    continue
                body = blob.stdout.decode("utf-8", "replace")
                for number, line in enumerate(body.splitlines(), 1):
                    if marker in line:
                        found[(path, number)] = len(line)
    else:
        for current, dirs, files in os.walk(directory):
            if ".git" in dirs:
                dirs.remove(".git")
            for file in files:
                full = os.path.join(current, file)
                if os.path.islink(full):
                    continue
                rel = os.path.relpath(full, directory)
                with open(full, encoding="utf-8", errors="replace") as handle:
                    for number, line in enumerate(handle.read().splitlines(), 1):
                        if marker in line:
                            found[(rel, number)] = len(line)
    text = config.get("match_text", "")
    return [
        {
            "RuleID": config.get("rule_id", "inert-marker"), "Description": "inert marker",
            "File": path, "StartLine": number, "EndLine": number, "StartColumn": 1,
            "EndColumn": width, "Match": text, "Secret": text, "Entropy": 0,
            "Fingerprint": "inert:%s:%d" % (path, number),
        }
        for (path, number), width in sorted(found.items())
    ]


out = config.get("stdout", "")
for variant in config.get("variants", []):
    if variant["argv_contains"] in " ".join(args):
        out = variant["stdout"]
        break
if config.get("walk_marker"):
    out = json.dumps(walk(config["walk_marker"], root))
sys.stdout.write(out)
sys.stderr.write(config.get("stderr", ""))
raise SystemExit(config.get("exit", 0))
"""

_GIT_SHIM = """\
#!__PYTHON__
import json, os, pathlib, sys

here = pathlib.Path(__file__).resolve().parent
with (here / "git-calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
os.execv("__GIT__", ["__GIT__", *sys.argv[1:]])
"""

_PYTHON_SHIM = """\
#!__PYTHON__
import os, pathlib, sys, json

here = pathlib.Path(__file__).resolve().parent
probe = here / "cdk-nag.stub.json"
if (
    len(sys.argv) > 2 and sys.argv[1] == "-c" and "importlib.metadata" in sys.argv[2]
    and "cdk-nag" in sys.argv[2] and probe.is_file()
):
    sys.stdout.write(json.loads(probe.read_text(encoding="utf-8"))["version"] + "\\n")
    raise SystemExit(0)
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
"""


def _executable(path: Path, source: str) -> None:
    text = source.replace("__PYTHON__", sys.executable).replace("__GIT__", REAL_GIT)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@dataclass
class Machine:
    """A private machine: its own HOME, TMPDIR and a PATH that holds only fake tools."""

    base: Path

    @property
    def home(self) -> Path:
        return self.base / "home"

    @property
    def stubs(self) -> Path:
        return self.base / "bin"

    @property
    def tmpdir(self) -> Path:
        return self.base / "tmp"

    def env(self, **extra: str) -> dict[str, str]:
        env = {
            "PATH": str(self.stubs),
            "HOME": str(self.home),
            "TMPDIR": str(self.tmpdir),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        env.update(extra)
        return env

    def stub(self, tool: str, **config: Any) -> None:
        config.setdefault("git", REAL_GIT)
        (self.stubs / f"{tool}.stub.json").write_text(json.dumps(config), encoding="utf-8")
        if tool != "cdk-nag":
            _executable(self.stubs / tool, _STUB)

    def remove(self, tool: str) -> None:
        for name in (tool, f"{tool}.stub.json"):
            (self.stubs / name).unlink(missing_ok=True)

    def calls(self, tool: str | None = None, *, scans: bool = False) -> list[dict[str, Any]]:
        log = self.stubs / "calls.jsonl"
        if not log.is_file():
            return []
        found = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return [
            call for call in found
            if (tool is None or call["tool"] == tool)
            and not (scans and "--version" in call["argv"])
        ]

    def git_calls(self) -> list[dict[str, Any]]:
        log = self.stubs / "git-calls.jsonl"
        if not log.is_file():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def semgrep_cache(self, state: str) -> None:
        """``ok`` (recorded digest matches), ``missing`` (no pack) or ``mismatch``."""
        cache = self.home / ".saga" / "semgrep-rules" / "p--security-audit"
        shutil.rmtree(cache, ignore_errors=True)
        (self.home / ".saga").mkdir(parents=True, exist_ok=True)
        digest = "f" * 64
        if state != "missing":
            cache.mkdir(parents=True)
            (cache / "inert.yaml").write_text("rules: []\n", encoding="utf-8")
            if state == "ok":
                digest = _tree_digest(cache)
        record = {"rule_caches": {"p/security-audit": digest}}
        (self.home / ".saga" / "machine.json").write_text(json.dumps(record), encoding="utf-8")


def _tree_digest(directory: Path) -> str:
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.relative_to(directory).as_posix().encode())
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _machine(tmp: Path, *, cache: str = "ok", healthy: bool = True) -> Machine:
    machine = Machine(tmp / "machine")
    for directory in (machine.home, machine.stubs, machine.tmpdir):
        directory.mkdir(parents=True)
    _executable(machine.stubs / "git", _GIT_SHIM)
    _executable(machine.stubs / "python3", _PYTHON_SHIM)
    if healthy:
        machine.stub("semgrep", version="1.179.0", stdout=json.dumps({"results": [], "errors": []}))
        machine.stub("gitleaks", version="8.30.1", walk_marker=MARKER, match_text=MATCH)
        machine.stub("osv-scanner", version="2.6.0", stdout=json.dumps({"results": []}))
    machine.semgrep_cache(cache)
    return machine


# ---------------------------------------------------------------------------------------
# Fixture repositories
# ---------------------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        [REAL_GIT, *args], cwd=repo, check=check, capture_output=True, text=True,
        env={**os.environ, **_GIT_ENV},
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")


def _write(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@dataclass
class Fixture:
    path: Path
    first: str
    head: str


_LEGACY = f"alpha\n{MARKER} inert example line\ngamma\n"


def _plain(
    tmp: Path, name: str = "target", *, marker: bool = True, extra: dict[str, str] | None = None
) -> Fixture:
    """``docs/old.txt`` line 2 holds the marker. The latest commit touches only ``notes.txt``."""
    repo = tmp / name
    _init(repo)
    _write(repo, {
        "README.txt": "plain readme\n",
        "docs/old.txt": _LEGACY if marker else "alpha\nbeta\ngamma\n",
        "notes.txt": "one\n",
        **(extra or {}),
    })
    first = _commit(repo, "add docs")
    _write(repo, {"notes.txt": "one\ntwo\n"})
    return Fixture(repo, first, _commit(repo, "touch notes"))


def _fingerprint(root: Path) -> dict[str, tuple[Any, ...]]:
    """Every entry under ``root``, ``.git`` included, by type, mode and content. No mtimes."""
    state: dict[str, tuple[Any, ...]] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                state[relative] = ("link", os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                state[relative] = ("dir", stat.S_IMODE(info.st_mode))
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                state[relative] = ("file", stat.S_IMODE(info.st_mode), digest)
    return state


# ---------------------------------------------------------------------------------------
# Running the command
# ---------------------------------------------------------------------------------------


@dataclass
class Scan:
    proc: subprocess.CompletedProcess[str]
    out: Path

    @property
    def code(self) -> int:
        return self.proc.returncode

    @property
    def terminal(self) -> str:
        return self.proc.stdout + self.proc.stderr

    def summary(self) -> dict[str, Any]:
        return json.loads((self.out / "summary.json").read_text(encoding="utf-8"))

    def markdown(self) -> str:
        return (self.out / "summary.md").read_text(encoding="utf-8")

    def rows(self) -> dict[str, dict[str, Any]]:
        return {row["id"]: row for row in self.summary()["rows"]}

    def findings(self) -> list[dict[str, Any]]:
        return json.loads((self.out / "findings.json").read_text(encoding="utf-8"))


def _present(script: Path) -> None:
    """Python itself exits 2 for a missing script, which is also the scan's refusal code."""
    assert script.is_file(), f"{script} does not exist yet"


def _run(
    machine: Machine,
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        argv, cwd=cwd or machine.base, env=machine.env(**(env or {})), capture_output=True,
        text=True, timeout=180,
    )
    assert "Traceback" not in proc.stderr, proc.stderr
    return proc


def _scan(
    machine: Machine,
    repo: Path,
    out: Path,
    *args: str,
    commit: str | None = None,
    script: Path = SCAN,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> Scan:
    _present(script)
    argv = [sys.executable, str(script), "--repo", str(repo), "--output", str(out)]
    if commit is not None:
        argv += ["--commit", commit]
    argv += list(args)
    return Scan(_run(machine, argv, cwd=cwd, env=env), out)


def _security_ids() -> list[str]:
    data = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    return sorted(row["id"] for row in data["tools"] if row.get("lens") == "security")


def _total(row: dict[str, Any]) -> int:
    return sum(int(row["counts"].get(level, 0)) for level in LEVELS)


def _module(name: str) -> ModuleType:
    """An existing saga script, imported lazily and shared with every other test file.

    ``test_review_tools.py`` puts its own copy of ``review_tools`` in ``sys.modules``. Reusing
    whatever is there keeps the adapters and the runner on one set of classes in one session.
    """
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module(name)


def _tree_files(*roots: Path) -> list[Path]:
    return [
        path for root in roots if root.exists()
        for path in ([root] if root.is_file() else root.rglob("*")) if path.is_file()
    ]


def _assert_absent_everywhere(text: str, *roots: Path) -> None:
    needle = text.encode()
    for path in _tree_files(*roots):
        assert needle not in path.read_bytes(), f"{text!r} was persisted in {path}"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process review runs here refuse sockets. Scans run in subprocesses with fake tools."""
    import socket

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("security scan tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _j(value: Any) -> str:
    return json.dumps(value)


def _python_stubs(machine: Machine) -> None:
    machine.stub("bandit", version="1.9.4", stdout=_j({"results": []}))
    machine.stub("pip-audit", version="2.10.1", stdout=_j({"dependencies": []}))


def _semgrep_result(check: str, severity: str, path: str, line: int) -> dict[str, Any]:
    return {
        "check_id": check, "path": path, "start": {"line": line}, "end": {"line": line},
        "extra": {"severity": severity, "message": "inert message", "metadata": {}},
    }


_PIP_FINDING = {
    "dependencies": [{
        "name": "inert-pkg", "version": "1.0.0",
        "vulns": [{"id": "PYSEC-0000-INERT", "aliases": ["CVE-0000-0000"]}],
    }],
}
_OSV_FINDING = {
    "results": [{
        "source": {"path": "requirements.txt", "type": "lockfile"},
        "packages": [{
            "package": {"name": "inert-pkg", "version": "1.0.0", "ecosystem": "PyPI"},
            "vulnerabilities": [{
                "id": "OSV-0000-INERT", "aliases": ["CVE-0000-0001"],
                "database_specific": {"severity": "HIGH"},
            }],
        }],
    }],
}
_NPM_FINDING = {
    "vulnerabilities": {
        "inert-npm-pkg": {
            "name": "inert-npm-pkg", "severity": "high",
            "via": [{"url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
                     "cvss": {"score": 7.5}}],
        },
    },
}
_DENY_FINDING = {
    "type": "diagnostic",
    "fields": {
        "severity": "error", "code": "vulnerability", "message": "inert",
        "advisory": {
            "id": "RUSTSEC-0000-0000", "package": "inert-crate", "aliases": ["CVE-0000-0002"],
            "cvss": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        },
    },
}
_NAG_REPORT = {
    "pluginReports": [{
        "violations": [{
            "severity": "error", "ruleName": "INERT-NAG-RULE", "description": "inert",
            "violatingConstructs": [
                {"constructPath": "Stack/Inert", "templatePath": "template.json"}
            ],
        }],
    }],
}
_CHECKOV_FINDING = {
    "results": {
        "failed_checks": [{
            "check_id": "CKV_AWS_20", "check_name": "inert", "resource": "AWS::S3::Bucket.Inert",
            "file_path": "template.json", "file_line_range": [1, 3],
        }],
    },
}
_TEMPLATE = (
    "AWSTemplateFormatVersion: '2010-09-09'\nResources:\n  Inert:\n    Type: AWS::S3::Bucket\n"
)


def _deps_repo(tmp: Path, name: str = "target") -> Fixture:
    """Every base/head row has input at both commits, so an ordinary review drops its findings."""
    repo = tmp / name
    _init(repo)
    _write(repo, {
        "README.txt": "readme\n",
        "requirements.txt": "inert-pkg==1.0.0\n",
        "package.json": '{"name": "inert", "version": "1.0.0"}\n',
        "package-lock.json": '{"name": "inert", "lockfileVersion": 3, "packages": {}}\n',
        "Cargo.toml": '[package]\nname = "inert"\nversion = "0.1.0"\n',
        "Cargo.lock": "# inert lock\nversion = 3\n",
        "cdk.json": '{"app": "echo inert"}\n',
        "template.yaml": _TEMPLATE,
    })
    first = _commit(repo, "add dependency manifests")
    _write(repo, {"README.txt": "readme two\n"})
    return Fixture(repo, first, _commit(repo, "touch readme"))


def _deps_machine(tmp: Path) -> Machine:
    machine = _machine(tmp)
    machine.stub("bandit", version="1.9.4", stdout=_j({"results": []}))
    machine.stub("pip-audit", version="2.10.1", stdout=_j(_PIP_FINDING))
    machine.stub("osv-scanner", version="2.6.0", stdout=_j(_OSV_FINDING))
    machine.stub("npm", version="12.0.2", stdout=_j(_NPM_FINDING))
    machine.stub("cargo-deny", version="0.20.2", stderr=_j(_DENY_FINDING) + "\n")
    machine.stub(
        "cdk", synth_files={"policy-validation-report.json": _NAG_REPORT, "template.json": {}},
    )
    machine.stub("cdk-nag", version="3.0.2")
    machine.stub(
        "checkov", version="3.3.25", stdout=_j({"results": {"failed_checks": []}}),
        variants=[{"argv_contains": "checkov-cdk", "stdout": _j(_CHECKOV_FINDING)}],
    )
    return machine


def _cdk_repo(tmp: Path, sentinel: Path) -> Fixture:
    repo = tmp / "target"
    _init(repo)
    app = f"python3 -c \"open('{sentinel}', 'w').write('inert')\""
    _write(repo, {"cdk.json": _j({"app": app}), "template.yaml": _TEMPLATE, "README.txt": "r\n"})
    first = _commit(repo, "add cdk app")
    _write(repo, {"README.txt": "r two\n"})
    return Fixture(repo, first, _commit(repo, "touch readme"))


def _cdk_machine(tmp: Path, sentinel: Path) -> Machine:
    machine = _machine(tmp)
    machine.stub(
        "cdk", sentinel=str(sentinel),
        synth_files={"policy-validation-report.json": _NAG_REPORT, "template.json": {}},
    )
    machine.stub("cdk-nag", version="3.0.2")
    machine.stub(
        "checkov", version="3.3.25", stdout=_j({"results": {"failed_checks": []}}),
        variants=[{"argv_contains": "checkov-cdk", "stdout": _j(_CHECKOV_FINDING)}],
    )
    return machine


#: Appended to a copy of ``review_adapters_workflows.py`` so a fixture row finds an adapter.
_FIXTURE_ADAPTERS = '''

import json as _json
import review_tools as _rt


def _fixture_parse(text):
    hits = tuple(
        _rt.Hit(
            rule_id=item["rule"], path=item["path"], statement="inert fixture finding",
            anchor=item["rule"], start=item["line"], end=item["line"],
            row="security.scanner-medium-low",
        )
        for item in _json.loads(text)["hits"]
    )
    return _rt.ParseResult(hits)


def _fixture(adapter_id, tool, lens, pin, row):
    return _rt.Adapter(
        id=adapter_id, tool=tool, invoke=lambda context: [tool, "scan"], parse=_fixture_parse,
        lens=lens, rows=(row,), default_version=pin, timeout_seconds=30,
    )


ADAPTERS = tuple(ADAPTERS) + (
    _fixture("fixture-security", "fixture-sec-tool", "security", "1.0.0",
             "security.scanner-medium-low"),
    _fixture("fixture-unpinned", "fixture-unpinned-tool", "security", "not-recorded",
             "security.scanner-medium-low"),
    _fixture("fixture-style", "fixture-style-tool", "correctness", "1.0.0",
             "correctness.tool-warning"),
)
'''


def _fixture_row(adapter_id: str, tool: str, lens: str, pin: str) -> dict[str, Any]:
    return {
        "id": adapter_id, "tool": tool, "languages": ["*"], "lens": lens,
        "purpose": "Inert fixture row.", "install": "No install.", "default_version": pin,
        "version_args": ["--version"], "timeout_seconds": 30, "comparison": "lines",
        "mode": "report",
    }


def _extended_plugin(tmp: Path, rows: list[dict[str, Any]]) -> Path:
    """A copy of the saga plugin whose catalogue gains ``rows``. Returns its entry script."""
    copy = tmp / "plugin-copy" / "saga"
    shutil.copytree(
        PLUGIN, copy, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"),
    )
    catalogue = copy / "references" / "review-tools.yaml"
    data = yaml.safe_load(catalogue.read_text(encoding="utf-8"))
    data["tools"].extend(rows)
    catalogue.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    adapters = copy / "scripts" / "review_adapters_workflows.py"
    adapters.write_text(adapters.read_text(encoding="utf-8") + _FIXTURE_ADAPTERS, encoding="utf-8")
    return copy / "scripts" / "security_scan.py"


# ---------------------------------------------------------------------------------------
# T01 to T02: the command, and selection from the catalogue
# ---------------------------------------------------------------------------------------


def test_help(tmp_path: Path) -> None:
    _present(SCAN)
    proc = subprocess.run(
        [sys.executable, str(SCAN), "--help"], capture_output=True, text=True, timeout=60,
        env={"PATH": str(tmp_path), "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    for option in ("--repo", "--commit", "--output", "--include-synthesized", "--timeout",
                   "--profile"):
        assert option in proc.stdout, f"--help does not document {option}"
    assert not re.search(r"--(enable|allow|with)[-a-z]*(pip|resol)", proc.stdout), (
        "no option may switch pip dependency resolution back on"
    )


def test_selection_catalogue_future_row(tmp_path: Path) -> None:
    rows = [
        _fixture_row("fixture-security", "fixture-sec-tool", "security", "1.0.0"),
        _fixture_row("fixture-style", "fixture-style-tool", "correctness", "1.0.0"),
        _fixture_row("fixture-unmatched", "fixture-unmatched-tool", "security", "1.0.0"),
    ]
    script = _extended_plugin(tmp_path, rows)
    fx = _plain(tmp_path, marker=False)
    machine = _machine(tmp_path)
    hit = {"hits": [{"rule": "fixture-rule", "path": "docs/old.txt", "line": 2}]}
    machine.stub("fixture-sec-tool", version="1.0.0", stdout=_j(hit))
    style_sentinel = tmp_path / "style-ran"
    machine.stub("fixture-style-tool", version="1.0.0", stdout=_j(hit),
                 sentinel=str(style_sentinel))
    scan = _scan(machine, fx.path, tmp_path / "out", script=script)
    rows_by_id = scan.rows()
    assert set(rows_by_id) == set(_security_ids()) | {"fixture-security", "fixture-unmatched"}
    assert rows_by_id["fixture-security"]["status"] == "ran"
    assert _total(rows_by_id["fixture-security"]) == 1
    assert "fixture-style" not in rows_by_id
    assert machine.calls("fixture-style-tool") == [] and not style_sentinel.exists()
    assert all(f["rule"]["ref"] != "fixture-style" for f in scan.findings())
    unmatched = rows_by_id["fixture-unmatched"]
    assert unmatched["status"] == "degraded" and unmatched["reason"]
    assert machine.calls("fixture-unmatched-tool") == []
    assert scan.code == 2 and scan.summary()["exit_code"] == 2


# ---------------------------------------------------------------------------------------
# T03 to T05: the selected tree, not the latest change
# ---------------------------------------------------------------------------------------


def test_whole_repository_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fx = _plain(tmp_path)
    machine = _machine(tmp_path)
    assert _git(fx.path, "diff", "--name-only", fx.first, fx.head) == "notes.txt"

    review = _module("review_tools")
    monkeypatch.setenv("PATH", str(machine.stubs))
    profile = tmp_path / "review-profile.json"
    profile.write_text(_j({"schema": "repository_profile.v1"}), encoding="utf-8")
    adapters = [item for item in review.default_adapters() if item.id == "gitleaks"]
    code = review.run(
        fx.path, fx.first, fx.head, profile, tmp_path / "review-out", home=machine.home,
        adapters=adapters, framework=False,
    )
    assert code == 0
    assert machine.calls("gitleaks", scans=True), "the fake gitleaks must have seen the file"
    reviewed = json.loads((tmp_path / "review-out" / "findings.json").read_text("utf-8"))
    assert reviewed == [], "ordinary review drops a hit in a file the change did not touch"

    scan = _scan(machine, fx.path, tmp_path / "out")
    assert scan.code == 1
    found = [(f["location"]["file"], f["location"]["lines"]["start"]) for f in scan.findings()]
    assert found == [("docs/old.txt", 2)]
    assert scan.rows()["gitleaks"]["counts"]["blocks"] == 1
    assert "docs/old.txt:2" in scan.markdown()


def test_whole_repository_base_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fx = _deps_repo(tmp_path)
    machine = _deps_machine(tmp_path)
    refs = {
        "pip-audit": "CVE-0000-0000", "osv-scanner": "CVE-0000-0001",
        "npm-audit": "GHSA-AAAA-BBBB-CCCC", "cargo-deny": "CVE-0000-0002",
        "cdk-nag": "INERT-NAG-RULE", "checkov-cdk": "CKV_AWS_20",
    }

    review = _module("review_tools")
    monkeypatch.setenv("PATH", str(machine.stubs))
    profile = tmp_path / "review-profile.json"
    profile.write_text(_j({"schema": "repository_profile.v1"}), encoding="utf-8")
    adapters = [
        item for item in review.default_adapters()
        if item.id in ("pip-audit", "osv-scanner", "npm-audit", "cargo-deny")
    ]
    code = review.run(
        fx.path, fx.first, fx.head, profile, tmp_path / "review-out", home=machine.home,
        adapters=adapters, framework=False,
    )
    assert code == 0
    reviewed = (tmp_path / "review-out" / "findings.json").read_text(encoding="utf-8")
    for row in ("pip-audit", "osv-scanner", "npm-audit", "cargo-deny"):
        assert refs[row] not in reviewed, f"ordinary review keeps {row}, which exists at base"

    out = tmp_path / "out"
    scan = _scan(
        machine, fx.path, out,
        "--include-synthesized", "cdk-nag", "--include-synthesized", "checkov-cdk",
    )
    assert scan.code == 1, scan.terminal
    rows = scan.rows()
    saved = json.dumps(scan.findings())
    for row, ref in refs.items():
        assert rows[row]["status"] == "ran", f"{row}: {rows[row]}"
        assert _total(rows[row]) >= 1, f"{row} lost its finding against the empty base"
        assert ref in saved, f"{row} finding {ref} is missing from findings.json"


def test_named_commit_and_head(tmp_path: Path) -> None:
    repo = tmp_path / "target"
    _init(repo)
    _write(repo, {
        "README.txt": "readme\n", "docs/old.txt": _LEGACY, "legacy.txt": f"{MARKER}\n",
        "notes.txt": "one\n",
    })
    first = _commit(repo, "add legacy files")
    _git(repo, "tag", "v1", first)
    (repo / "legacy.txt").unlink()
    _write(repo, {"notes.txt": "one\ntwo\n"})
    head = _commit(repo, "remove the legacy marker")
    _write(repo, {"README.txt": f"{MARKER} uncommitted edit\n", "untracked.txt": f"{MARKER}\n"})
    machine = _machine(tmp_path)

    current = _scan(machine, repo, tmp_path / "head-out")
    assert current.code == 1
    assert {f["location"]["file"] for f in current.findings()} == {"docs/old.txt"}
    assert current.summary()["commit"] == head
    assert head in current.markdown()

    for name, out in (("by-sha", first), ("by-tag", "v1")):
        earlier = _scan(machine, repo, tmp_path / name, commit=out)
        assert earlier.code == 1
        assert {f["location"]["file"] for f in earlier.findings()} == {"docs/old.txt", "legacy.txt"}
        assert earlier.summary()["commit"] == first

    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    before = len(machine.calls())
    for index, bad in enumerate(("0" * 39 + "1", "no-such-ref", tree)):
        out = tmp_path / f"bad-{index}"
        refused = _scan(machine, repo, out, commit=bad)
        assert refused.code == 2, f"{bad!r}: {refused.terminal}"
        if (out / "summary.json").exists():
            assert refused.summary()["exit_code"] == 2
    assert len(machine.calls()) == before, "no tool runs for a commit that cannot be resolved"


# ---------------------------------------------------------------------------------------
# T06 to T07: the scanned repository is never touched
# ---------------------------------------------------------------------------------------


def _dirty(repo: Path) -> None:
    _write(repo, {
        "README.txt": f"{MARKER} uncommitted edit\n", "scratch.txt": f"{MARKER}\n",
        "debug.log": f"{MARKER}\n",
    })
    _git(repo, "status", "--porcelain")


def _settled(*repos: Path) -> dict[Path, dict[str, tuple[Any, ...]]]:
    return {repo: _fingerprint(repo) for repo in repos}


def test_target_untouched_success(tmp_path: Path) -> None:
    repo = tmp_path / "target"
    _init(repo)
    _write(repo, {
        ".gitattributes": "ignored/** export-ignore\n", ".gitignore": "*.log\n",
        "README.txt": "readme\n", "ignored/old.txt": _LEGACY, "notes.txt": "one\n",
    })
    _commit(repo, "add files that an archive export would omit")
    _dirty(repo)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "linked-branch", str(linked))
    _git(linked, "status", "--porcelain")
    machine = _machine(tmp_path)

    before = _settled(repo, linked)
    scan = _scan(machine, repo, tmp_path / "out-main")
    assert scan.code == 1, scan.terminal
    assert {f["location"]["file"] for f in scan.findings()} == {"ignored/old.txt"}
    assert _settled(repo, linked) == before, "the scan changed the target or its linked worktree"
    assert list(machine.tmpdir.iterdir()) == [], "the disposable copy was not removed"

    from_linked = _scan(machine, linked, tmp_path / "out-linked")
    assert from_linked.code == 1, from_linked.terminal
    assert {f["location"]["file"] for f in from_linked.findings()} == {"ignored/old.txt"}
    assert _settled(repo, linked) == before, "scanning a linked worktree changed Git storage"

    # A snapshot that is not the named commit's tree must be incomplete before any row runs. A
    # tree identifier cannot be forced to differ from outside, so this removes a tracked blob
    # that no faithful copy can then carry.
    broken = tmp_path / "broken"
    _init(broken)
    _write(broken, {"README.txt": "readme\n", "notes.txt": "one\n", "docs/old.txt": _LEGACY})
    _commit(broken, "add files")
    blob = _git(broken, "rev-parse", "HEAD:notes.txt")
    loose = broken / ".git" / "objects" / blob[:2] / blob[2:]
    assert loose.is_file()
    loose.chmod(0o644)
    loose.unlink()
    calls_before = len(machine.calls())
    state = _settled(broken)
    unfaithful = _scan(machine, broken, tmp_path / "out-broken")
    assert unfaithful.code == 2, unfaithful.terminal
    if (tmp_path / "out-broken" / "summary.json").exists():
        assert unfaithful.summary()["exit_code"] == 2
    assert len(machine.calls()) == calls_before, "a row ran on a snapshot that was not the tree"
    assert _settled(broken) == state

    # A gitlink (mode 160000) is carried unchanged, never checked out, read or fetched.
    gitlink = "1" * 40
    sub = tmp_path / "submodule-target"
    _init(sub)
    _write(sub, {
        "README.txt": "readme\n", "docs/old.txt": _LEGACY,
        ".gitmodules": '[submodule "vendor/sub"]\n\tpath = vendor/sub\n'
                       '\turl = https://example.invalid/inert-submodule.git\n',
    })
    _commit(sub, "add files")
    _git(sub, "update-index", "--add", "--cacheinfo", f"160000,{gitlink},vendor/sub")
    _git(sub, "commit", "-q", "-m", "add a submodule entry")
    assert f"160000 commit {gitlink}\tvendor/sub" in _git(sub, "ls-tree", "-r", "HEAD")
    _write(sub, {"vendor/sub/inert.txt": f"{MARKER} inside the submodule directory\n"})
    machine.stub("gitleaks", version="8.30.1", walk_marker=MARKER, match_text=MATCH,
                 log_tree=True)
    state = _settled(sub)
    git_before = len(machine.git_calls())
    gap = _scan(machine, sub, tmp_path / "out-submodule")
    assert gap.code == 2, gap.terminal
    assert gap.summary()["exit_code"] == 2
    assert gap.rows()["gitleaks"]["status"] == "ran", "rows must run after the tree ids match"
    assert {f["location"]["file"] for f in gap.findings()} == {"docs/old.txt"}
    report = gap.markdown() + json.dumps(gap.summary())
    assert "vendor/sub" in report and "submodule" in report.lower()
    trees = [call.get("tree", "") for call in machine.calls("gitleaks", scans=True)]
    assert any(f"160000 commit {gitlink}\tvendor/sub" in tree for tree in trees)
    for call in machine.git_calls()[git_before:]:
        assert "submodule" not in call["argv"], "a submodule must never be initialised"
        assert not any("example.invalid" in arg for arg in call["argv"]), "no submodule fetch"
        assert "vendor/sub" not in call["cwd"], "the submodule directory must never be read"
    assert _settled(sub) == state


def test_target_untouched_failure_cleanup(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("a read-only directory does not stop root")
    fx = _plain(tmp_path)
    machine = _machine(tmp_path)
    state = _settled(fx.path)
    homes = _git_dirs(tmp_path)

    machine.stub("gitleaks", version="8.30.1", exit=3, stderr="inert tool failure\n")
    failed = _scan(machine, fx.path, tmp_path / "out-tool")
    assert failed.code == 2, failed.terminal
    assert _settled(fx.path) == state
    assert list(machine.tmpdir.iterdir()) == [], "disposable files outlived a failed scan"
    assert _git_dirs(tmp_path) == homes, "a disposable repository or worktree was left behind"

    out = tmp_path / "out-readonly"
    out.mkdir()
    machine.stub("gitleaks", version="8.30.1", walk_marker=MARKER, chmod_readonly=str(out))
    try:
        locked = _scan(machine, fx.path, out)
    finally:
        out.chmod(0o700)
    assert locked.code == 2, locked.terminal
    assert _settled(fx.path) == state
    assert list(machine.tmpdir.iterdir()) == []
    assert _git_dirs(tmp_path) == homes


def _git_dirs(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob(".git"))


# ---------------------------------------------------------------------------------------
# T08 to T10: where the results go
# ---------------------------------------------------------------------------------------


def _linked(tmp: Path) -> tuple[Fixture, Path]:
    fx = _plain(tmp)
    linked = tmp / "linked"
    _git(fx.path, "worktree", "add", "-q", "-b", "linked-branch", str(linked))
    return fx, linked


def test_output_location_refuses_inside(tmp_path: Path) -> None:
    fx, linked = _linked(tmp_path)
    machine = _machine(tmp_path)
    state = _settled(fx.path, linked)
    inside = [
        (fx.path, fx.path), (fx.path, fx.path / "results"), (fx.path, fx.path / "docs"),
        (fx.path, fx.path / ".git" / "scan-out"), (linked, linked / "results"),
        (linked, fx.path / ".git" / "scan-out"),
        (linked, fx.path / ".git" / "worktrees" / "linked" / "scan-out"),
    ]
    for index, (repo, out) in enumerate(inside):
        refused = _scan(machine, repo, out)
        assert refused.code == 2, f"{out}: {refused.terminal}"
        assert machine.calls() == [], f"a tool ran before {out} was refused"
        assert _settled(fx.path, linked) == state, f"{out} changed the target"
    relative = _scan(machine, fx.path, Path("results"), cwd=fx.path)
    assert relative.code == 2 and not (fx.path / "results").exists()
    assert machine.calls() == []


def test_output_location_symlink(tmp_path: Path) -> None:
    fx = _plain(tmp_path)
    machine = _machine(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(fx.path, target_is_directory=True)
    docs_link = tmp_path / "docs-link"
    docs_link.symlink_to(fx.path / "docs", target_is_directory=True)
    dangling = tmp_path / "dangling"
    dangling.symlink_to(fx.path / "not-yet")
    state = _settled(fx.path)
    for out in (
        alias / "results", alias / ".git" / "scan-out", alias / "new" / "deeper" / "child",
        docs_link, dangling, dangling / "child",
    ):
        refused = _scan(machine, fx.path, out)
        assert refused.code == 2, f"{out}: {refused.terminal}"
        assert machine.calls() == [], f"a tool ran before {out} was refused"
        assert _settled(fx.path) == state
    assert not (fx.path / "not-yet").exists() and not (fx.path / "results").exists()


def test_output_location_outside(tmp_path: Path) -> None:
    fx = _plain(tmp_path, marker=False)
    machine = _machine(tmp_path)
    state = _settled(fx.path)
    external = tmp_path / "external"
    external.mkdir()
    link = tmp_path / "outside-link"
    link.symlink_to(external, target_is_directory=True)
    empty = tmp_path / "empty-dir"
    empty.mkdir()
    names = ("summary.md", "summary.json", "findings.json", "measurements.json",
             "degraded.json", "outcomes.json")
    for out in (tmp_path / "results" / "deep" / "run-1", empty, link):
        scan = _scan(machine, fx.path, out)
        assert scan.code == 0, scan.terminal
        for name in names:
            assert (out / name).is_file(), f"{out} has no {name}"
        assert scan.findings() == [] and scan.summary()["exit_code"] == 0
    assert (external / "summary.md").is_file(), "records follow a link that leads outside"
    assert _settled(fx.path) == state

    if os.geteuid() != 0:
        parent = tmp_path / "read-only"
        parent.mkdir()
        parent.chmod(0o500)
        try:
            locked = _scan(machine, fx.path, parent / "run")
        finally:
            parent.chmod(0o700)
        assert locked.code == 2, locked.terminal
        assert _settled(fx.path) == state


# ---------------------------------------------------------------------------------------
# T11 to T16: the summary says what ran, what did not, and why
# ---------------------------------------------------------------------------------------


def test_summary_states_and_levels(tmp_path: Path) -> None:
    fx = _plain(tmp_path, extra={
        "requirements.txt": "inert-pkg==1.0.0\n", "Package.swift": "// inert swift manifest\n",
    })
    machine = _machine(tmp_path)
    _python_stubs(machine)
    results = [
        _semgrep_result("inert.high", "ERROR", "docs/old.txt", 1),
        _semgrep_result("inert.warn", "WARNING", "notes.txt", 2),
        _semgrep_result("inert.info", "INFO", "README.txt", 1),
    ]
    machine.stub("semgrep", version="1.179.0", stdout=_j({"results": results, "errors": []}))
    scan = _scan(machine, fx.path, tmp_path / "out")
    rows = scan.rows()
    assert set(rows) == set(_security_ids()), "every catalogue security row is reported"
    for row in rows.values():
        assert row["status"] in ("ran", "skipped", "degraded"), row
        if row["status"] != "ran":
            assert row["reason"], f"{row['id']} is {row['status']} with no reason"
        assert set(row["counts"]) <= set(LEVELS)
    for ran in ("semgrep-security", "gitleaks", "osv-scanner", "bandit", "pip-audit"):
        assert rows[ran]["status"] == "ran", rows[ran]
        assert rows[ran]["version"]
    assert [rows["semgrep-security"]["counts"].get(level, 0) for level in LEVELS] == [1, 2, 0]
    assert [rows["gitleaks"]["counts"].get(level, 0) for level in LEVELS] == [1, 0, 0]
    for clean in ("osv-scanner", "bandit", "pip-audit"):
        assert _total(rows[clean]) == 0, "an invocation with no hit is a clean row"
    for skipped in ("zizmor", "npm-audit", "cargo-deny", "checkov-cfn", "cdk-nag", "checkov-cdk"):
        assert rows[skipped]["status"] == "skipped", rows[skipped]
    swift = rows["swift-dependency-audit"]
    assert swift["status"] == "degraded" and "known-gap" in swift["reason"]
    assert scan.code == 2 and scan.summary()["exit_code"] == 2
    markdown = scan.markdown()
    for location in ("docs/old.txt:2", "docs/old.txt:1", "notes.txt:2", "README.txt:1"):
        assert location in markdown, f"the summary does not print {location}"
    for rule in ("inert-marker", "inert.high", "inert.warn", "inert.info"):
        assert rule in markdown
    assert sorted(scan.summary()["advisory_service_rows"]) == ["osv-scanner", "pip-audit"]
    assert "package names and versions" in markdown


def test_summary_versions_unpinned(tmp_path: Path) -> None:
    profile_pin = tmp_path / "pins.json"
    profile_pin.write_text(_j({
        "schema": "repository_profile.v1",
        "review_tools": {"pins": {"gitleaks": {"version": "8.30.1"}}},
    }), encoding="utf-8")
    source_profile = _j({
        "schema": "repository_profile.v1",
        "review_tools": {"pins": {"gitleaks": {"version": "99.0.0"},
                                  "semgrep": {"version": "0.0.1"}}},
    })
    fx = _plain(tmp_path, extra={
        ".saga-profile.json": source_profile, "requirements.txt": "inert-pkg==1.0.0\n",
    })
    machine = _machine(tmp_path)
    _python_stubs(machine)

    plain = _scan(machine, fx.path, tmp_path / "out-plain")
    rows = plain.rows()
    assert plain.code == 1, plain.terminal
    for name in ("gitleaks", "osv-scanner"):
        assert rows[name]["pin"] == "not-recorded", rows[name]
        assert rows[name]["status"] == "ran", f"{name} is not degraded for an absent pin"
    assert rows["gitleaks"]["version"] == "8.30.1" and rows["osv-scanner"]["version"] == "2.6.0"
    assert rows["semgrep-security"]["pin"] == "1.179.0", "the scanned commit cannot set a pin"
    assert rows["semgrep-security"]["status"] == "ran"
    assert re.search(r"no pin", plain.markdown(), re.IGNORECASE)
    secret = [f for f in plain.findings() if f["source"]["name"] == "gitleaks"]
    assert len(secret) == 1 and secret[0]["degraded"] is False

    pinned = _scan(machine, fx.path, tmp_path / "out-pinned", "--profile", str(profile_pin))
    assert pinned.rows()["gitleaks"]["pin"] == "8.30.1"
    assert pinned.rows()["gitleaks"]["status"] == "ran"

    inside = fx.path / "inside-profile.json"
    inside.write_text(profile_pin.read_text(encoding="utf-8"), encoding="utf-8")
    link = tmp_path / "profile-link.json"
    link.symlink_to(inside)
    calls = len(machine.calls())
    for path in (inside, fx.path / ".saga-profile.json", link):
        refused = _scan(machine, fx.path, tmp_path / f"refused-{path.name}", "--profile", str(path))
        assert refused.code == 2, f"{path}: {refused.terminal}"
    assert len(machine.calls()) == calls, "a profile inside the target is refused before any tool"

    rows_for_copy = [
        _fixture_row("fixture-security", "fixture-sec-tool", "security", "1.0.0"),
        _fixture_row("fixture-unpinned", "fixture-unpinned-tool", "security", "not-recorded"),
    ]
    script = _extended_plugin(tmp_path, rows_for_copy)
    hit = {"hits": [{"rule": "fixture-rule", "path": "docs/old.txt", "line": 2}]}
    machine.stub("fixture-sec-tool", version="1.0.0", stdout=_j({"hits": []}))
    machine.stub("fixture-unpinned-tool", version="4.5.6", stdout=_j(hit))
    clean = _plain(tmp_path, "clean-target", marker=False)
    copied = _scan(machine, clean.path, tmp_path / "out-copy", script=script)
    copy_rows = copied.rows()
    assert copy_rows["fixture-security"]["status"] == "ran"
    assert copy_rows["fixture-unpinned"]["status"] == "ran", "decided by the resolved pin"
    assert copy_rows["fixture-unpinned"]["pin"] == "not-recorded"
    assert copy_rows["fixture-unpinned"]["version"] == "4.5.6"
    assert copy_rows["fixture-unpinned"]["counts"].get("blocks", 0) + copy_rows[
        "fixture-unpinned"]["counts"].get("fix-later", 0) == 1
    assert copied.code == 1, copied.terminal


def test_summary_missing_tools(tmp_path: Path) -> None:
    fx = _plain(tmp_path, extra={"requirements.txt": "inert-pkg==1.0.0\n"})
    machine = _machine(tmp_path)
    machine.remove("gitleaks")
    scan = _scan(machine, fx.path, tmp_path / "out")
    rows = scan.rows()
    for name in ("gitleaks", "bandit", "pip-audit"):
        assert rows[name]["status"] == "degraded", f"{name}: {rows[name]}"
        assert "missing" in rows[name]["reason"]
        assert _total(rows[name]) == 0
    assert rows["semgrep-security"]["status"] == "ran"
    assert scan.findings() == [], "a tool that is not installed reports nothing, and is no clean row"
    assert scan.code == 2 and scan.summary()["exit_code"] == 2
    assert "missing" in scan.markdown()


def test_summary_version_mismatch(tmp_path: Path) -> None:
    pins = tmp_path / "pins.json"
    pins.write_text(_j({
        "schema": "repository_profile.v1",
        "review_tools": {"pins": {"osv-scanner": {"version": "9.9.9"}}},
    }), encoding="utf-8")
    fx = _plain(tmp_path, extra={"requirements.txt": "inert-pkg==1.0.0\n"})
    machine = _machine(tmp_path)
    machine.stub("semgrep", version="1.0.0", stdout=_j({"results": [], "errors": []}))
    machine.stub("gitleaks", version_text="not a version", walk_marker=MARKER, match_text=MATCH)
    scan = _scan(machine, fx.path, tmp_path / "out", "--profile", str(pins))
    rows = scan.rows()
    semgrep = rows["semgrep-security"]
    assert semgrep["status"] == "degraded" and "version-mismatch" in semgrep["reason"]
    assert semgrep["version"] == "1.0.0" and semgrep["pin"] == "1.179.0"
    osv = rows["osv-scanner"]
    assert osv["status"] == "degraded" and "version-mismatch" in osv["reason"]
    assert osv["version"] == "2.6.0" and osv["pin"] == "9.9.9"
    unreadable = rows["gitleaks"]
    assert unreadable["status"] == "degraded" and "version-unreadable" in unreadable["reason"]
    assert any(f["degraded"] is True for f in scan.findings()), "findings from off-pin rows stay"
    assert scan.code == 2, "off-pin rows make the scan incomplete even when findings exist"
    assert scan.summary()["exit_code"] == 2


def test_summary_semgrep_cache(tmp_path: Path) -> None:
    for state, reason in (("missing", "rule-cache-missing"), ("mismatch", "rule-cache-mismatch")):
        base = tmp_path / state
        base.mkdir()
        machine = _machine(base, cache=state)
        fx = _plain(base, marker=False)
        saga = machine.home / ".saga"
        before = {
            key: value for key, value in _fingerprint(saga).items()
            if key.startswith("semgrep-rules") or key == "machine.json"
        }
        scan = _scan(machine, fx.path, base / "out")
        row = scan.rows()["semgrep-security"]
        assert row["status"] == "degraded" and reason in row["reason"], row
        assert machine.calls("semgrep", scans=True) == [], "no semgrep scan, and no rule download"
        after = {
            key: value for key, value in _fingerprint(saga).items()
            if key.startswith("semgrep-rules") or key == "machine.json"
        }
        assert after == before, "the scan changed the machine's rule cache"
        assert scan.code == 2 and scan.summary()["exit_code"] == 2


def test_summary_timeout_or_bad_output(tmp_path: Path) -> None:
    fx = _plain(tmp_path, extra={"requirements.txt": "inert-pkg==1.0.0\n"})
    machine = _machine(tmp_path)
    _python_stubs(machine)
    machine.stub("gitleaks", version="8.30.1", walk_marker=MARKER, sleep=30)
    machine.stub("semgrep", version="1.179.0", stdout="this is not json {")
    machine.stub("osv-scanner", version="2.6.0", exit=3, stderr="inert tool failure\n")
    scan = _scan(machine, fx.path, tmp_path / "out", "--timeout", "2")
    rows = scan.rows()
    assert rows["gitleaks"]["status"] == "degraded" and "timeout" in rows["gitleaks"]["reason"]
    for name in ("semgrep-security", "osv-scanner"):
        assert rows[name]["status"] == "degraded", rows[name]
        assert "unparseable" in rows[name]["reason"]
    for name in ("gitleaks", "semgrep-security", "osv-scanner"):
        assert _total(rows[name]) == 0 and rows[name]["status"] != "ran"
    assert scan.code == 2 and scan.summary()["exit_code"] == 2


# ---------------------------------------------------------------------------------------
# T17 to T18: rows that execute the scanned repository run only when named
# ---------------------------------------------------------------------------------------


def test_synthesized_default_skip(tmp_path: Path) -> None:
    sentinel = tmp_path / "cdk-ran"
    fx = _cdk_repo(tmp_path, sentinel)
    machine = _cdk_machine(tmp_path, sentinel)
    scan = _scan(machine, fx.path, tmp_path / "out")
    rows = scan.rows()
    for name in SYNTHESIZED:
        assert rows[name]["status"] == "skipped", rows[name]
        reason = rows[name]["reason"]
        assert "--include-synthesized" in reason or "opt-in" in reason.lower(), reason
    assert rows["checkov-cfn"]["status"] == "ran", "hand-written templates need no synthesis"
    assert machine.calls("cdk") == [] and not sentinel.exists(), "the app was executed"
    assert all("checkov-cdk" not in " ".join(call["argv"]) for call in machine.calls("checkov"))
    assert "--include-synthesized" in scan.markdown()
    assert scan.code == 0, scan.terminal


def test_synthesized_named_opt_in(tmp_path: Path) -> None:
    sentinel = tmp_path / "cdk-ran"
    fx = _cdk_repo(tmp_path, sentinel)
    machine = _cdk_machine(tmp_path, sentinel)

    def synth_calls(before: int) -> list[dict[str, Any]]:
        return machine.calls("cdk", scans=True)[before:]

    before = len(machine.calls("cdk"))
    only_nag = _scan(machine, fx.path, tmp_path / "nag", "--include-synthesized", "cdk-nag")
    nag_rows = only_nag.rows()
    assert nag_rows["cdk-nag"]["status"] == "ran" and _total(nag_rows["cdk-nag"]) == 1
    assert nag_rows["checkov-cdk"]["status"] == "skipped"
    calls = synth_calls(before)
    assert len(calls) == 1 and "--context" in calls[0]["argv"]

    before = len(machine.calls("cdk"))
    only_checkov = _scan(
        machine, fx.path, tmp_path / "checkov", "--include-synthesized", "checkov-cdk"
    )
    checkov_rows = only_checkov.rows()
    assert checkov_rows["checkov-cdk"]["status"] == "ran" and _total(checkov_rows["checkov-cdk"]) == 1
    assert checkov_rows["cdk-nag"]["status"] == "skipped"
    calls = synth_calls(before)
    assert len(calls) == 1 and "--context" not in calls[0]["argv"]

    before = len(machine.calls("cdk"))
    both = _scan(
        machine, fx.path, tmp_path / "both", "--include-synthesized", "cdk-nag",
        "--include-synthesized", "checkov-cdk", "--include-synthesized", "cdk-nag",
    )
    both_rows = both.rows()
    assert both_rows["cdk-nag"]["status"] == "ran" and both_rows["checkov-cdk"]["status"] == "ran"
    assert len(synth_calls(before)) == 2, "a duplicate name must not run a row twice"

    total = len(machine.calls())
    for bad in ("not-a-row", "gitleaks", "bandit"):
        refused = _scan(machine, fx.path, tmp_path / f"bad-{bad}", "--include-synthesized", bad)
        assert refused.code == 2, f"{bad}: {refused.terminal}"
    assert len(machine.calls()) == total, "an unknown name is refused before any tool runs"


# ---------------------------------------------------------------------------------------
# T19: the exit status
# ---------------------------------------------------------------------------------------


def test_exit_status(tmp_path: Path) -> None:
    machine = _machine(tmp_path)
    clean = _plain(tmp_path, "clean", marker=False)
    dirty = _plain(tmp_path, "dirty")
    outcomes = {}
    outcomes["clean"] = _scan(machine, clean.path, tmp_path / "o-clean")
    outcomes["findings"] = _scan(machine, dirty.path, tmp_path / "o-findings")
    machine.remove("osv-scanner")
    outcomes["incomplete"] = _scan(machine, clean.path, tmp_path / "o-incomplete")
    outcomes["both"] = _scan(machine, dirty.path, tmp_path / "o-both")
    assert [outcomes[name].code for name in ("clean", "findings", "incomplete", "both")] == [
        0, 1, 2, 2,
    ]
    for scan in outcomes.values():
        assert scan.summary()["exit_code"] == scan.code
    assert outcomes["clean"].findings() == []
    assert len(outcomes["findings"].findings()) == 1
    assert len(outcomes["both"].findings()) == 1, "incomplete wins, and the finding is kept"

    empty = tmp_path / "empty"
    _init(empty)
    _commit(empty, "an empty tree")
    nothing = _scan(machine, empty, tmp_path / "o-empty")
    assert nothing.code == 2, "a tree with no files is never reported as a clean scan"
    assert re.search(r"empty", nothing.terminal, re.IGNORECASE)

    calls = len(machine.calls())
    for bad in ("0", "-3"):
        refused = _scan(machine, clean.path, tmp_path / f"o-timeout{bad}", "--timeout", bad)
        assert refused.code == 2, f"--timeout {bad}: {refused.terminal}"
    assert len(machine.calls()) == calls
    _present(SCAN)
    usage = _run(machine, [sys.executable, str(SCAN)])
    assert usage.returncode == 2, "missing required arguments is an invalid input"


# ---------------------------------------------------------------------------------------
# T20 to T23: the command as a user runs it, and what it must never persist or run
# ---------------------------------------------------------------------------------------

_HEX40 = re.compile(r"\b[0-9a-f]{40}\b")


def test_end_to_end(tmp_path: Path) -> None:
    fx = _plain(tmp_path, extra={"requirements.txt": "inert-pkg==1.0.0\n"})
    machine = _machine(tmp_path)
    _python_stubs(machine)
    machine.stub("osv-scanner", version="2.6.0", stdout=_j(_OSV_FINDING))
    out = tmp_path / "out"
    scan = _scan(machine, fx.path, out)
    assert scan.code == 1, scan.terminal
    for name in ("summary.md", "summary.json", "findings.json", "measurements.json",
                 "degraded.json", "outcomes.json"):
        assert (out / name).is_file(), f"the run directory has no {name}"
    records = scan.findings()
    refs = {record["rule"]["ref"] for record in records}
    assert refs == {"inert-marker", "CVE-0000-0001"}
    validator = _module("review_records")
    for record in records:
        assert validator.validate(record) == [], record
    summary = scan.summary()
    assert summary["commit"] == fx.head and summary["exit_code"] == 1
    assert set(summary["advisory_service_rows"]) >= {"osv-scanner", "pip-audit"}
    assert "package names and versions" in scan.markdown()
    assert "docs/old.txt:2" in scan.proc.stdout, "the findings are printed to the terminal"
    assert "CVE-0000-0001" in scan.proc.stdout
    tree = _git(fx.path, "rev-parse", f"{fx.head}^{{tree}}")
    shown = scan.terminal + scan.markdown() + json.dumps(summary)
    assert set(_HEX40.findall(shown)) <= {fx.head, tree}, "the snapshot commit must not be named"
    allowed = {"semgrep", "gitleaks", "osv-scanner", "bandit", "pip-audit"}
    assert {call["tool"] for call in machine.calls()} <= allowed


def test_secret_redaction_all_surfaces(tmp_path: Path) -> None:
    fx = _plain(tmp_path)
    machine = _machine(tmp_path)
    kept = _scan(machine, fx.path, tmp_path / "out-kept")
    assert kept.code == 1, kept.terminal
    secret = [f for f in kept.findings() if f["source"]["name"] == "gitleaks"]
    assert [(f["rule"]["ref"], f["location"]["file"], f["location"]["lines"]["start"])
            for f in secret] == [("inert-marker", "docs/old.txt", 2)]
    assert MATCH not in kept.terminal
    _assert_absent_everywhere(MATCH, tmp_path / "out-kept", machine.home, machine.tmpdir)

    broken = MATCH.join(['[{"RuleID": "inert-marker", "Match": "', '", "Secret": "'])
    machine.stub("gitleaks", version="8.30.1", exit=2, stdout=broken, stderr=f"fatal: {MATCH}\n")
    failed = _scan(machine, fx.path, tmp_path / "out-failed")
    assert failed.code == 2, failed.terminal
    assert MATCH not in failed.terminal
    _assert_absent_everywhere(MATCH, tmp_path / "out-failed", machine.home, machine.tmpdir)


def test_source_only_no_hooks_credentials(tmp_path: Path) -> None:
    sentinels = tmp_path / "sentinels"
    sentinels.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(f"{MARKER} outside the repository\n", encoding="utf-8")
    profile_ran = sentinels / "profile"
    repo = tmp_path / "target"
    _init(repo)
    _write(repo, {
        "README.txt": "readme\n",
        "requirements.txt": "inert-pkg==1.0.0\nother-inert==2.0.0\n",
        "requirements-dev.txt": "unpinned-inert>=1.0\n",
        "requirements-local.txt": "./vendored/inert-local\n"
                                  "git+https://example.invalid/inert.git#egg=inert-git\n",
        ".semgrepignore": "docs/\n", ".gitleaksignore": "inert:docs/old.txt:2\n",
        ".gitleaks.toml": "title = \"inert\"\n",
        ".saga-profile.json": _j({
            "test_command": f"touch {profile_ran}",
            "review_tools": {"pins": {"gitleaks": {"version": "99.0.0"}}},
        }),
    })
    os.symlink(outside / "secret.txt", repo / "outside-link")
    _commit(repo, "add dependency files and settings")
    hook_ran = sentinels / "hook"
    fsmonitor_ran = sentinels / "fsmonitor"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    names = ("post-checkout", "post-commit", "post-merge", "reference-transaction", "pre-commit",
             "pre-push", "post-rewrite", "commit-msg", "prepare-commit-msg", "pre-auto-gc")
    for directory in (hooks, repo / ".git" / "hooks"):
        for name in names:
            script = directory / name
            script.write_text(f"#!/bin/sh\necho ran >> {hook_ran}\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
    monitor = tmp_path / "fsmonitor.sh"
    monitor.write_text(f"#!/bin/sh\necho ran >> {fsmonitor_ran}\nexit 0\n", encoding="utf-8")
    monitor.chmod(0o755)
    (repo / ".git" / "config").write_text(
        (repo / ".git" / "config").read_text(encoding="utf-8")
        + f"[core]\n\thooksPath = {hooks}\n\tfsmonitor = {monitor}\n", encoding="utf-8",
    )
    machine = _machine(tmp_path)
    _python_stubs(machine)
    machine.stub("pip-audit", version="2.10.1", stdout=_j(_PIP_FINDING))
    machine.stub("gitleaks", version="8.30.1", walk_marker=MARKER, match_text=MATCH,
                 log_tree=True)
    state = _settled(repo)
    scan = _scan(machine, repo, tmp_path / "out", env={"INERT_CREDENTIAL_SENTINEL": CREDENTIAL})

    for sentinel in (hook_ran, fsmonitor_ran, profile_ran):
        assert not sentinel.exists(), f"{sentinel.name} was executed by the scan"
    assert _settled(repo) == state
    calls = machine.calls()
    assert calls and all(call["credential"] is None for call in calls), "a credential passed through"
    assert all(call["seen"] == [] for call in calls), "scanned-commit tool settings were not stripped"
    assert scan.rows()["gitleaks"]["pin"] == "not-recorded", "the scanned commit set a pin"
    _assert_absent_everywhere(CREDENTIAL, tmp_path / "out")

    audits = machine.calls("pip-audit", scans=True)
    assert len(audits) == 1
    argv = audits[0]["argv"]
    assert "--disable-pip" in argv and "--no-deps" in argv
    listed = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--requirement"]
    assert listed == ["requirements.txt"], "only fully pinned requirement files are audited"
    row = scan.rows()["pip-audit"]
    assert row["status"] == "degraded"
    detail = json.dumps(row)
    assert "requirements-dev.txt" in detail and "requirements-local.txt" in detail
    assert any(f["rule"]["ref"] == "CVE-0000-0000" for f in scan.findings())
    assert scan.code == 2 and scan.summary()["exit_code"] == 2
    assert re.search(r"pip-audit.{0,200}only.{0,80}list", scan.markdown(), re.DOTALL | re.IGNORECASE)

    assert all(f["location"]["file"] != "outside-link" for f in scan.findings())
    trees = [call["tree"] for call in machine.calls("gitleaks", scans=True)]
    assert any(re.search(r"^120000 blob [0-9a-f]{40}\toutside-link$", t, re.M) for t in trees), (
        "a symbolic link is carried as a link, never followed"
    )

    script = SCAN.read_text(encoding="utf-8")
    assert "--disable-pip" not in script and "--no-deps" not in script, (
        "pip-audit's scan arguments belong beside its adapter, not in the new script"
    )
    adapter = (SCRIPTS / "review_adapters_python.py").read_text(encoding="utf-8")
    assert "--disable-pip" in adapter and "--no-deps" in adapter


def test_repeated_run_output_refusal(tmp_path: Path) -> None:
    fx = _plain(tmp_path)
    machine = _machine(tmp_path)
    first = _scan(machine, fx.path, tmp_path / "run-1")
    second = _scan(machine, fx.path, tmp_path / "run-2")
    assert first.code == second.code == 1
    identities = [sorted(f["id"] for f in scan.findings()) for scan in (first, second)]
    assert identities[0] and identities[0] == identities[1]
    assert first.summary()["commit"] == second.summary()["commit"] == fx.head

    saved = _fingerprint(tmp_path / "run-1")
    calls = len(machine.calls())
    again = _scan(machine, fx.path, tmp_path / "run-1")
    assert again.code == 2, "an occupied output directory must be refused, never overwritten"
    assert _fingerprint(tmp_path / "run-1") == saved
    stray = tmp_path / "stray"
    stray.mkdir()
    (stray / "old-result.txt").write_text("an older result\n", encoding="utf-8")
    refused = _scan(machine, fx.path, stray)
    assert refused.code == 2
    assert [path.name for path in stray.iterdir()] == ["old-result.txt"]
    assert len(machine.calls()) == calls, "no tool runs when the output is refused"


# ---------------------------------------------------------------------------------------
# T24: the portable skill and descriptor
# ---------------------------------------------------------------------------------------


def test_skill_entrypoint_registered() -> None:
    assert SKILL.is_file(), "plugins/saga/skills/security-scan/SKILL.md does not exist yet"
    text = SKILL.read_text(encoding="utf-8")
    front = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert front is not None, "the skill needs front matter"
    meta = yaml.safe_load(front.group(1))
    assert meta["name"] == "security-scan" and str(meta["description"]).strip()
    for needed in ("scripts/security_scan.py", "--repo", "--output", "--commit",
                   "--include-synthesized", "summary.md", "summary.json", "findings.json"):
        assert needed in text, f"the skill never mentions {needed}"
    assert re.search(r"outside (of )?the (scanned )?repository", text, re.IGNORECASE)
    for status in ("ran", "skipped", "degraded"):
        assert status in text
    for code in ("0", "1", "2"):
        assert re.search(rf"(?m)^.*\b{code}\b.*(complete|finding|incomplete)", text, re.IGNORECASE)
    port = json.loads(PORT.read_text(encoding="utf-8"))
    assert "scripts/security_scan.py" in port["assessment"]["entrypoints"]
    assert "skills/security-scan" in port["assessment"]["skill_units"]
    assert SCAN.is_file(), "the declared entry script must exist"
    assert "com.infiquetra" not in str(SKILL), "the skill is portable, not a client adapter file"


# ---------------------------------------------------------------------------------------
# T25: ordinary review is unchanged. This passes today and must keep passing.
# ---------------------------------------------------------------------------------------


def test_review_output_unchanged(tmp_path: Path) -> None:
    review = _module("review_tools")
    repo = tmp_path / "review"
    _init(repo)
    _write(repo, {"README.txt": "plain readme\n", "notes.txt": "one\n",
                  "requirements.txt": "inert-pkg==1.0.0\n"})
    base = _commit(repo, "base")
    _write(repo, {"notes.txt": "one\ntwo\n", "requirements-dev.txt": "other-pkg==2.0.0\n"})
    head = _commit(repo, "head")
    seen: list[list[str]] = []

    def process(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
                shell: bool) -> Any:
        assert shell is False
        seen.append(list(argv))
        if "--version" in argv:
            return review.ProcessResult(0, {"pip-audit": "2.10.1", "gitleaks": "8.30.1"}[argv[0]])
        if argv[0] == "pip-audit":
            at_base = _git(Path(cwd), "rev-parse", "HEAD") == base
            vulns = [] if at_base else [{"id": "PYSEC-0000-INERT", "aliases": ["CVE-0000-0000"]}]
            report = {"dependencies": [{"name": "inert-pkg", "version": "1.0.0", "vulns": vulns}]}
            return review.ProcessResult(0, json.dumps(report))
        leak = [{"RuleID": "inert-marker", "File": "notes.txt", "StartLine": 2, "EndLine": 2,
                 "Match": "x", "Secret": "x"}]
        return review.ProcessResult(0, json.dumps(leak))

    profile = tmp_path / "profile.json"
    profile.write_text(_j({"schema": "repository_profile.v1"}), encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    adapters = [a for a in review.default_adapters() if a.id in ("pip-audit", "gitleaks")]
    out = tmp_path / "out"
    assert review.run(repo, base, head, profile, out, home=home, adapters=adapters,
                      runner=process, framework=False) == 0

    pip_base = ["pip-audit", "--format", "json", "--progress-spinner", "off",
                "--requirement", "requirements.txt"]
    pip_head = ["pip-audit", "--format", "json", "--progress-spinner", "off",
                "--requirement", "requirements-dev.txt", "--requirement", "requirements.txt"]
    scans = [argv for argv in seen if argv[0] == "pip-audit" and "--version" not in argv]
    assert scans == [pip_base, pip_head]
    leaks = [argv for argv in seen if argv[0] == "gitleaks" and "--version" not in argv]
    assert len(leaks) == 1
    assert leaks[0][:6] == ["gitleaks", "detect", "--report-format", "json", "--report-path", "-"]
    assert leaks[0][6] == "--config" and leaks[0][7].endswith("references/gitleaks.toml")
    assert leaks[0][8] == "--ignore-gitleaks-allow"

    pip_module = _module("review_adapters_python")
    context = review.ScanContext(repo, repo, home)
    assert pip_module._invoke_pip_audit(context) == pip_head

    expected = [
        {
            "consequence": None, "consequence_jev": None, "degraded": False,
            "evidence": "tool-result", "id": "rf:a76f984639d3e0fbffa4f1d32dba2b48",
            "introduced": True, "kind": "finding", "language": "none", "lens": "security",
            "location": {"anchor": "CVE-0000-0000", "file": "requirements.txt",
                         "scope": "whole-project"},
            "merge_outcome": None,
            "proof": {"raw_output": "a2ff9d9c58a1f0d44e0d50b8092e7ee9d75a38a83bd4e43d76abaa1fb02282e1"},
            "rule": {"ref": "CVE-0000-0000", "row": "security.dependency-high"},
            "schema": "review_records.v1",
            "source": {"kind": "tool", "name": "pip-audit", "version": "2.10.1"},
            "statement": "Dependency advisory PYSEC-0000-INERT.", "subject": "code",
            "trigger": None, "unconfirmed": False,
        },
        {
            "consequence": None, "consequence_jev": None, "degraded": True,
            "evidence": "tool-result", "id": "rf:6b57e5144e5eec0892f5626236c16c23",
            "introduced": True, "kind": "finding", "language": "none", "lens": "security",
            "location": {"anchor": "inert-marker notes.txt", "file": "notes.txt",
                         "function": None, "lines": {"end": 2, "start": 2}, "scope": "lines"},
            "merge_outcome": None,
            "proof": {"raw_output": "368a2bbd2112cf07ae6d8e337b26f01e7c42e63e5931df023b84c60494ee2aeb"},
            "rule": {"ref": "inert-marker", "row": "security.secret-in-diff"},
            "schema": "review_records.v1",
            "source": {"kind": "tool", "name": "gitleaks", "version": "8.30.1"},
            "statement": "A secret scanner reported a match in this file.", "subject": "code",
            "trigger": None, "unconfirmed": False,
        },
    ]
    assert json.loads((out / "findings.json").read_text("utf-8")) == expected
    # The row with no recorded pin is still reported as a mismatch by ordinary review.
    assert json.loads((out / "degraded.json").read_text("utf-8")) == [{
        "input": "security.secret-in-diff", "language": "none", "lens": "security",
        "reason": "version-mismatch", "tool": "gitleaks",
    }]
