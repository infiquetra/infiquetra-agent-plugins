"""Enforced end-to-end deterministic scanner combine suite for R7 (issue #335).

Proves that R1 (#255), R2 (#258), R3 (#257), R4 (#246), R5 (#261), and R6 (#245) compose
cleanly without regressions across a single multi-stack Git repository fixture (Python +
CloudFormation + Markdown + custom Semgrep rule pin + cached Semgrep security pack + local
offline advisory snapshots), with network sockets refused and a stripped PATH containing no
host uv, semgrep, checkov, cfn-lint, cargo, cargo-deny, osv-scanner, pip-audit, or npm.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = REPO_ROOT / "plugins" / "reviews"
SCRIPTS = PACKAGE / "scripts"
REFERENCES = PACKAGE / "references"

FORMULA_SHA256 = "528540c6958cf628d5cdf3ea44dc7fff45c16862ad11412c56a945ceb7e4e839"
SCHEMA_SHA256 = "a505807b505fbb65f98c58f36375256dd99b7afb2e7f3346bac9f79a9b90acd8"
SNAPSHOT_VERSION = "2026-11-19"
SNAPSHOT_TIMESTAMP = "2026-11-19T00:00:00Z"


def _load(name: str) -> ModuleType:
    key = f"infiquetra_reviews.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


T = _load("review_tools")
ALL = _load("review_adapters_all_languages")
PY = _load("review_adapters_python")
INFRA = _load("review_adapters_infrastructure")
CHECKS = _load("review_checks")
SETUP = _load("review_setup")
CMD = _load("review_command")
REC = _load("review_records")
SCAN = _load("security_scan")


@pytest.fixture(autouse=True)
def _refuse_all_sockets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Disable network sockets in-process and in spawned Python subprocesses."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("R7 combine suite must make no network or socket calls")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    guard_dir = tmp_path / "socket-guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    (guard_dir / "sitecustomize.py").write_text(
        "import socket, urllib.request\n"
        "def _blocked(*_a, **_kw):\n"
        "    raise RuntimeError('network socket refused by R7 combine sitecustomize')\n"
        "socket.socket = _blocked\n"
        "socket.create_connection = _blocked\n"
        "socket.create_server = _blocked\n"
        "socket.socketpair = _blocked\n"
        "socket.getaddrinfo = _blocked\n"
        "urllib.request.urlopen = _blocked\n",
        encoding="utf-8",
    )
    existing = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH",
        str(guard_dir) if not existing else f"{guard_dir}{os.pathsep}{existing}",
    )
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    child = subprocess.run(
        [sys.executable, "-c", "import socket; socket.socket()"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode != 0
    assert "network socket refused" in f"{child.stdout}{child.stderr}"
    with pytest.raises(AssertionError, match="no network or socket"):
        socket.socket()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _schema_document() -> dict[str, Any]:
    return json.loads((REFERENCES / "review-records.schema.json").read_text(encoding="utf-8"))


def _jsonschema():
    """The installed validator. A missing package is a failed check, not a skip."""
    try:
        import jsonschema
    except ImportError as exc:
        pytest.fail(f"jsonschema is required to validate review records: {exc}")
    return jsonschema


def _assert_against_schema(record: dict[str, Any]) -> None:
    """Check *record* against the schema file and the review_records validator."""
    schema = _schema_document()
    kind = record.get("kind")
    spec = schema["$defs"].get(kind)
    assert isinstance(spec, dict), f"schema has no definition for {kind!r}"
    missing = [key for key in spec.get("required", []) if key not in record]
    assert missing == [], f"{kind} record missing {missing}"
    for key, prop in spec.get("properties", {}).items():
        if isinstance(prop, dict) and "const" in prop and key in record:
            assert record[key] == prop["const"], key
    assert REC.validate(record) == [], record
    _jsonschema().validate(record, schema)


def _answer_required(error: Any) -> bool:
    message = getattr(error, "message", "")
    if getattr(error, "validator", None) == "required" and "answer" in str(message):
        return True
    return any(_answer_required(child) for child in getattr(error, "context", ()))


def _assert_unanswered_where_to_look(items: list[dict[str, Any]]) -> None:
    """Prepare prompts are not answered ``where_to_look`` records.

    The schema requires ``answer`` once a reviewer has answered. Prepare emits
    the question, the classifier, and ``degraded`` without that field.
    """
    schema = _schema_document()
    where = schema["$defs"]["where_to_look"]
    assert "answer" in where["required"]
    validator = _jsonschema().Draft202012Validator(schema)
    assert items, "prepare emitted no where-to-look prompts"
    for item in items:
        assert item.get("kind") == "where_to_look"
        assert item.get("schema") == REC.SCHEMA
        assert "answer" not in item
        for key in ("lens", "location", "language", "questions", "classifier", "degraded"):
            assert key in item, key
        assert item["questions"]
        assert all("id" in question and "probability" in question for question in item["questions"])
        errors = list(validator.iter_errors(item))
        assert any(_answer_required(error) for error in errors), errors


def _invocations(bindir: Path) -> list[dict[str, Any]]:
    log = bindir / "invocations.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _semgrep_configs(invocations: list[dict[str, Any]]) -> list[str]:
    configs: list[str] = []
    for item in invocations:
        if item.get("name") != "semgrep":
            continue
        argv = item.get("argv") or []
        if "--config" not in argv:
            continue
        configs.append(str(argv[argv.index("--config") + 1]))
    return configs


def _prove_osv_cache_zip(bindir: Path, cache: Path, tmp_path: Path) -> None:
    """The shim's advisories come from the zip, and a bad zip is a failure."""
    work = tmp_path / "osv-parse-proof"
    (work / "deps").mkdir(parents=True)
    (work / "deps" / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    argv = [
        str(bindir / "osv-scanner"), "scan", "source",
        "--offline", "--offline-vulnerabilities",
        "--format", "json", "--data-source", "native",
        "--lockfile", "requirements.txt:deps/requirements.txt",
    ]

    def _run(directory: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            cwd=work,
            env={
                "PATH": str(bindir),
                "OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY": str(directory),
                "LANG": "C",
            },
            capture_output=True,
            text=True,
            check=False,
        )

    parsed = _run(cache)
    assert parsed.returncode == 0, parsed.stderr
    body = json.loads(parsed.stdout)
    vulns = body["results"][0]["packages"][0]["vulnerabilities"]
    assert [item["id"] for item in vulns] == ["GHSA-2099-0002"]
    assert vulns[0]["aliases"] == ["CVE-2099-0002"]

    bad = tmp_path / "osv-bad-cache"
    (bad / "osv-scalibr" / "PyPI").mkdir(parents=True)
    (bad / "osv-scalibr" / "PyPI" / "all.zip").write_bytes(b"PK\x03\x04")
    assert _run(bad).returncode != 0

    missing = tmp_path / "osv-missing-cache"
    (missing / "osv-scalibr" / "PyPI").mkdir(parents=True)
    assert _run(missing).returncode != 0


def _find_adapter(adapters: tuple[Any, ...], tool_id: str) -> Any:
    matches = [adapter for adapter in adapters if adapter.id == tool_id]
    assert len(matches) == 1, f"expected 1 adapter for {tool_id!r}, found {len(matches)}"
    return matches[0]


_RANDOMLY_PLUGIN = """\
def pytest_addoption(parser):
    parser.addoption("--randomly-seed", action="store", default="0")
"""

_SOCKET_PLUGIN = """\
import socket

class SocketBlockedError(RuntimeError):
    pass

def pytest_addoption(parser):
    parser.addoption("--disable-socket", action="store_true", default=False)

def pytest_configure(config):
    if not config.getoption("--disable-socket"):
        return
    def blocked(*_args, **_kwargs):
        raise SocketBlockedError("socket blocked by hermetic pytest_socket")
    socket.socket = blocked
    socket.create_connection = blocked
    socket.create_server = blocked
    socket.getaddrinfo = blocked
"""

_PYTHON_SHIM = """\
#!__PYTHON__
import json
import os
import runpy
import socket
import sys
from pathlib import Path

def _refuse(*_args, **_kwargs):
    raise OSError("network socket refused by R7 python3 shim")

socket.socket = _refuse
socket.create_connection = _refuse
socket.create_server = _refuse
socket.socketpair = _refuse
socket.getaddrinfo = _refuse

log = Path(__file__).resolve().parent / "invocations.jsonl"
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"name": "python3", "argv": sys.argv[1:]}) + "\\n")

argv = sys.argv[1:]
real = "__PYTHON__"
if argv[:1] in (["--version"], ["-V"]):
    os.execv(real, [real, *argv])
if argv[:1] == ["-c"] and len(argv) >= 2:
    sys.argv = ["-c", *argv[2:]]
    exec(compile(argv[1], "<string>", "exec"), {"__name__": "__main__"})
elif argv[:1] == ["-m"] and len(argv) >= 2:
    sys.argv = [argv[1], *argv[2:]]
    runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
elif argv and not argv[0].startswith("-"):
    sys.argv = list(argv)
    runpy.run_path(argv[0], run_name="__main__")
else:
    os.execv(real, [real, *argv])
"""


def _assert_python3_shim_refuses_sockets(bindir: Path, tmp_path: Path) -> None:
    """The shim blocks AF_INET construction after production envs drop PYTHONPATH."""
    code = "import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM)"
    scanner_home = tmp_path / "scanner-home"
    scanner_home.mkdir(parents=True, exist_ok=True)
    scanner_env = {
        "PATH": str(bindir),
        "LANG": "C.UTF-8",
        "HOME": str(scanner_home),
        "TMPDIR": str(scanner_home),
        "SEMGREP_ENABLE_VERSION_CHECK": "0",
    }
    installer_env = dict(PY._plugin_install_env())
    assert "PYTHONPATH" not in scanner_env
    assert "PYTHONPATH" not in installer_env
    for label, env in (("scanner", scanner_env), ("plugin-installer", installer_env)):
        proc = subprocess.run(
            [str(bindir / "python3"), "-c", code],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, (label, proc.returncode, proc.stderr)
        assert "network socket refused" in f"{proc.stdout}{proc.stderr}", (label, proc.stderr)


def _install_hermetic_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a stripped PATH containing only hermetic scanner/uv shims plus git and env."""
    bindir = tmp_path / "hermetic-bin"
    bindir.mkdir(parents=True, exist_ok=True)

    real_git = shutil.which("git") or "/usr/bin/git"
    real_env = shutil.which("env") or "/usr/bin/env"
    (bindir / "git").symlink_to(real_git)
    env_wrapper = bindir / "env"
    env_wrapper.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "log = Path(__file__).resolve().parent / 'invocations.jsonl'\n"
        "with log.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps({'name': 'env', 'argv': sys.argv[1:]}) + '\\n')\n"
        f"os.execv({real_env!r}, [{real_env!r}, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    env_wrapper.chmod(0o755)
    python_wrapper = bindir / "python3"
    python_wrapper.write_text(
        _PYTHON_SHIM.replace("__PYTHON__", sys.executable),
        encoding="utf-8",
    )
    python_wrapper.chmod(0o755)
    (bindir / "python").symlink_to(python_wrapper)

    catalogue = yaml.safe_load((REFERENCES / "review-tools.yaml").read_text(encoding="utf-8"))
    versions: dict[str, str] = {}
    for row in catalogue.get("tools") or []:
        if not isinstance(row, dict):
            continue
        tool = str(row.get("tool") or row.get("id") or "")
        ver = str(row.get("default_version") or "1.0.0")
        if tool and ver != "not-recorded":
            versions.setdefault(tool, ver)
        if row.get("id") and ver != "not-recorded":
            versions.setdefault(str(row["id"]), ver)

    share = tmp_path / "hermetic-share"
    share.mkdir(parents=True, exist_ok=True)
    (share / "randomly.py").write_text(_RANDOMLY_PLUGIN, encoding="utf-8")
    (share / "pytest_socket.py").write_text(_SOCKET_PLUGIN, encoding="utf-8")
    for dist_name, key in (
        ("pytest_randomly", "pytest-randomly"),
        ("pytest_socket", "pytest-socket"),
    ):
        pin = versions.get(key, "1.0.0")
        dist_info = share / f"{dist_name}-{pin}.dist-info"
        dist_info.mkdir(parents=True, exist_ok=True)
        (dist_info / "METADATA").write_text(
            f"Name: {key}\nVersion: {pin}\n", encoding="utf-8"
        )

    uv_script = bindir / "uv"
    uv_script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, shutil, sys\n"
        "from pathlib import Path\n"
        f"SHARE = Path({str(share)!r})\n"
        f"PYTHON = {sys.executable!r}\n"
        f"RUFF_VER = {versions.get('ruff', '0.15.18')!r}\n"
        "PACKAGES = {\n"
        "    'pytest-randomly==5.0.0': 'randomly.py',\n"
        "    'pytest-socket==0.8.1': 'pytest_socket.py',\n"
        "}\n"
        "args = sys.argv[1:]\n"
        "LOG = Path(__file__).resolve().parent / 'invocations.jsonl'\n"
        "with LOG.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps({'name': 'uv', 'argv': args}) + '\\n')\n"
        "if args[:2] == ['pip', 'install']:\n"
        "    if '--offline' not in args or '--no-deps' not in args:\n"
        "        sys.stderr.write('uv pip install missing --offline or --no-deps\\n')\n"
        "        raise SystemExit(2)\n"
        "    target = Path(args[args.index('--target') + 1])\n"
        "    pkg = args[-1]\n"
        "    mod = PACKAGES.get(pkg)\n"
        "    if not mod:\n"
        "        raise SystemExit(2)\n"
        "    target.mkdir(parents=True, exist_ok=True)\n"
        "    shutil.copyfile(SHARE / mod, target / mod)\n"
        "    raise SystemExit(0)\n"
        "if args[:1] == ['run']:\n"
        "    if '--offline' not in args or '--with' not in args:\n"
        "        sys.stderr.write('uv run missing --offline or --with\\n')\n"
        "        raise SystemExit(2)\n"
        "    idx = args.index('--with')\n"
        "    pkg = args[idx + 1]\n"
        "    rest = args[idx + 2:]\n"
        "    if rest[:1] == ['ruff']:\n"
        "        if '--version' in rest:\n"
        "            print(f'ruff {RUFF_VER}')\n"
        "            raise SystemExit(0)\n"
        "        print('[]')\n"
        "        raise SystemExit(0)\n"
        "    env = os.environ.copy()\n"
        "    prev = env.get('PYTHONPATH', '')\n"
        "    env['PYTHONPATH'] = str(SHARE) if not prev else f'{SHARE}{os.pathsep}{prev}'\n"
        "    if rest[:1] == ['python']:\n"
        "        os.execve(PYTHON, [PYTHON, *rest[1:]], env)\n"
        "    if rest[:1] == ['pytest']:\n"
        "        os.execve(PYTHON, [PYTHON, '-m', 'pytest', *rest[1:]], env)\n"
        "sys.stderr.write('unsupported uv command in hermetic shim\\n')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    uv_script.chmod(0o755)

    scanner_script = bindir / "scanner-shim.py"
    scanner_script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, socket, sys, urllib.request, zipfile\n"
        "def _refuse_socket(*_a, **_k):\n"
        "    raise RuntimeError('network socket refused by R7 scanner shim')\n"
        "socket.socket = _refuse_socket\n"
        "socket.create_connection = _refuse_socket\n"
        "socket.getaddrinfo = _refuse_socket\n"
        "urllib.request.urlopen = _refuse_socket\n"
        "from pathlib import Path\n"
        f"VERSIONS = {json.dumps(versions)}\n"
        "HERE = Path(__file__).resolve().parent\n"
        "LOG = HERE / 'invocations.jsonl'\n"
        "COUNTER = HERE / 'semgrep-counter.txt'\n"
        "name = Path(sys.argv[0]).name\n"
        "args = sys.argv[1:]\n"
        "with LOG.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps({'name': name, 'argv': args}) + '\\n')\n"
        "if '--version' in args or '-version' in args:\n"
        "    print(VERSIONS.get(name, '1.0.0'))\n"
        "    raise SystemExit(0)\n"
        "if name == 'semgrep':\n"
        "    assert '--metrics=off' in args and '--disable-version-check' in args\n"
        "    cfg = args[args.index('--config') + 1] if '--config' in args else ''\n"
        "    count = int(COUNTER.read_text()) if COUNTER.is_file() else 0\n"
        "    COUNTER.write_text(str(count + 1))\n"
        "    if 'p--security-audit' in cfg:\n"
        "        pack_count_path = HERE / 'semgrep-security-count.txt'\n"
        "        pack_count = int(pack_count_path.read_text()) if pack_count_path.is_file() else 0\n"
        "        pack_count_path.write_text(str(pack_count + 1))\n"
        "        items = [\n"
        "            {\n"
        "                'check_id': 'python.security.audit.exec-used',\n"
        "                'path': 'src/app.py',\n"
        "                'start': {'line': 3},\n"
        "                'end': {'line': 3},\n"
        "                'extra': {'message': 'Security pack flagged line 3.', 'severity': 'ERROR'},\n"
        "            },\n"
        "            {\n"
        "                'check_id': 'python.security.audit. weak-hash',\n"
        "                'path': 'src/app.py',\n"
        "                'start': {'line': 3},\n"
        "                'end': {'line': 3},\n"
        "                'extra': {'message': 'Security pack warning on line 3.', 'severity': 'WARNING'},\n"
        "            },\n"
        "        ]\n"
        "        if pack_count % 2 == 1:\n"
        "            items = list(reversed(items))\n"
        "        with LOG.open('a', encoding='utf-8') as handle:\n"
        "            handle.write(json.dumps({'name': 'semgrep', 'order': [item['check_id'] for item in items], 'cfg': cfg}) + '\\n')\n"
        "        print(json.dumps({\n"
        "            'results': items,\n"
        "            'errors': [],\n"
        "            'time': {'total_time': 0.123 + count},\n"
        "        }))\n"
        "        raise SystemExit(0)\n"
        "    items = [\n"
        "        {\n"
        "            'check_id': f'{cfg}.saga.swallowed-error',\n"
        "            'path': 'src/app.py',\n"
        "            'start': {'line': 3},\n"
        "            'end': {'line': 3},\n"
        "            'extra': {\n"
        "                'message': 'Custom saga rule flagged swallowed error.',\n"
        "                'severity': 'ERROR',\n"
        "                'metadata': {\n"
        "                    'row': 'correctness.pattern.swallowed-error',\n"
        "                    'harm': 'wrong-result-reported-as-success',\n"
        "                },\n"
        "            },\n"
        "        }\n"
        "    ]\n"
        "    print(json.dumps({'results': items, 'errors': [], 'time': {'total_time': 0.456 + count}}))\n"
        "    raise SystemExit(0)\n"
        "if name == 'checkov':\n"
        "    assert '--skip-download' in args\n"
        "    scan_dir = Path(args[args.index('-d') + 1]) if '-d' in args else Path('.')\n"
        "    tpl = scan_dir / 'infra' / 'template.yaml'\n"
        "    failed = []\n"
        "    if tpl.is_file() and 'example-head-bucket' in tpl.read_text(encoding='utf-8'):\n"
        "        failed.append({\n"
        "            'check_id': 'CKV_AWS_20',\n"
        "            'check_name': 'S3 Bucket has an ACL defined which allows public READ access.',\n"
        "            'file_path': 'infra/template.yaml',\n"
        "            'file_line_range': [7, 7],\n"
        "            'resource': 'AWS::S3::Bucket.ArtifactBucket',\n"
        "        })\n"
        "    print(json.dumps({'results': {'failed_checks': failed}}))\n"
        "    raise SystemExit(0)\n"
        "if name == 'cfn-lint':\n"
        "    tpl = Path('infra/template.yaml')\n"
        "    findings = []\n"
        "    if tpl.is_file() and 'example-head-bucket' in tpl.read_text(encoding='utf-8'):\n"
        "        findings.append({\n"
        "            'Rule': {'Id': 'W3045'},\n"
        "            'Level': 'Warning',\n"
        "            'Message': 'BucketName should avoid static naming in templates.',\n"
        "            'Filename': 'infra/template.yaml',\n"
        "            'Location': {'Start': {'LineNumber': 7}, 'End': {'LineNumber': 7}},\n"
        "        })\n"
        "    print(json.dumps(findings))\n"
        "    raise SystemExit(0)\n"
        "if name == 'osv-scanner':\n"
        "    assert '--offline' in args and '--offline-vulnerabilities' in args\n"
        "    assert args[args.index('--data-source') + 1] == 'native'\n"
        "    cache = os.environ.get('OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY')\n"
        "    if not cache:\n"
        "        sys.stderr.write('OSV cache directory was not supplied\\n')\n"
        "        raise SystemExit(2)\n"
        "    zips = sorted(Path(cache).glob('osv-scalibr/*/all.zip'))\n"
        "    if len(zips) != 1 or not zips[0].is_file():\n"
        "        sys.stderr.write('OSV cache zip is missing\\n')\n"
        "        raise SystemExit(2)\n"
        "    try:\n"
        "        archive = zipfile.ZipFile(zips[0])\n"
        "        docs = []\n"
        "        for member in archive.namelist():\n"
        "            if member.endswith('.json'):\n"
        "                docs.append(json.loads(archive.read(member)))\n"
        "        archive.close()\n"
        "    except (zipfile.BadZipFile, OSError, ValueError) as exc:\n"
        "        sys.stderr.write(f'OSV cache zip is unreadable: {exc}\\n')\n"
        "        raise SystemExit(2)\n"
        "    lock_text = ''\n"
        "    lock_path = 'deps/requirements.txt'\n"
        "    if '--lockfile' in args:\n"
        "        token = args[args.index('--lockfile') + 1]\n"
        "        lock_path = token.split(':', 1)[-1]\n"
        "        candidate = Path(lock_path)\n"
        "        if candidate.is_file():\n"
        "            lock_text = candidate.read_text(encoding='utf-8')\n"
        "    vulns = []\n"
        "    for doc in docs:\n"
        "        if not isinstance(doc, dict) or not doc.get('id'):\n"
        "            continue\n"
        "        matched = False\n"
        "        for affected in doc.get('affected') or []:\n"
        "            if not isinstance(affected, dict):\n"
        "                continue\n"
        "            package = (affected.get('package') or {}).get('name')\n"
        "            versions = affected.get('versions') or []\n"
        "            if package and any(f'{package}=={version}' in lock_text for version in versions):\n"
        "                matched = True\n"
        "        if not matched:\n"
        "            continue\n"
        "        vulns.append({\n"
        "            'id': doc['id'],\n"
        "            'aliases': list(doc.get('aliases') or []),\n"
        "            'severity': list(doc.get('severity') or []),\n"
        "        })\n"
        "    results = []\n"
        "    if vulns:\n"
        "        results.append({\n"
        "            'source': {'path': lock_path},\n"
        "            'packages': [{'vulnerabilities': vulns}],\n"
        "        })\n"
        "    print(json.dumps({'results': results}))\n"
        "    raise SystemExit(0)\n"
        "if name == 'bandit':\n"
        "    print(json.dumps({'results': [], 'generated_at': '2026-11-19T00:00:00Z'}))\n"
        "    raise SystemExit(0)\n"
        "if name == 'gitleaks':\n"
        "    print('[]')\n"
        "    raise SystemExit(0)\n"
        "if name == 'pip-audit':\n"
        "    print(json.dumps({'dependencies': []}))\n"
        "    raise SystemExit(0)\n"
        "print('{}')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    scanner_script.chmod(0o755)

    for tool_name in (
        "semgrep",
        "checkov",
        "cfn-lint",
        "osv-scanner",
        "pip-audit",
        "bandit",
        "gitleaks",
    ):
        (bindir / tool_name).symlink_to(scanner_script)

    monkeypatch.setenv("PATH", str(bindir))
    for absent in ("cargo", "cargo-deny", "npm", "pytest"):
        assert shutil.which(absent) is None
    _assert_python3_shim_refuses_sockets(bindir, tmp_path)
    return bindir


def _build_combined_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a multi-stack git repository combining Python, CloudFormation, and Markdown."""
    repo = tmp_path / "combined-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "deps").mkdir(parents=True)
    (repo / "infra").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "decoys").mkdir(parents=True)

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "r7-combine@example.com")
    _git(repo, "config", "user.name", "r7-combine")
    _git(repo, "config", "commit.gpgsign", "false")

    (repo / "src" / "app.py").write_text(
        "def compute(x: int) -> int:\n"
        "    # the skip button and check_plan.py remain mentioned on this unedited line\n"
        "    return x + 1\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_app.py").write_text(
        "import socket\n"
        "from src.app import compute\n\n"
        "def test_compute() -> None:\n"
        "    assert compute(2) == 4\n\n"
        "def test_socket_construction_is_refused() -> None:\n"
        "    try:\n"
        "        socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    except Exception as exc:\n"
        "        assert 'blocked' in str(exc).lower() or 'refused' in str(exc).lower()\n"
        "        return\n"
        "    raise AssertionError('socket.socket(AF_INET, SOCK_STREAM) opened')\n",
        encoding="utf-8",
    )
    (repo / "deps" / "requirements.txt").write_text("requests==2.30.0\n", encoding="utf-8")
    (repo / "infra" / "template.yaml").write_text(
        'AWSTemplateFormatVersion: "2010-09-09"\n'
        "Description: Multi-stack CloudFormation template\n"
        "Resources:\n"
        "  ArtifactBucket:\n"
        "    Type: AWS::S3::Bucket\n"
        "    Properties:\n"
        "      BucketName: example-base-bucket\n",
        encoding="utf-8",
    )
    (repo / "docs" / "notes.md").write_text(
        "# Operator Guide\n\n"
        "The skip button is the way to leave.\n"
        "See `check_plan.py` before you skip the step.\n",
        encoding="utf-8",
    )
    (repo / "decoys" / "config.yaml").write_text(
        "service: api\nport: 8080\n", encoding="utf-8"
    )
    (repo / "decoys" / "resources.yaml").write_text(
        "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n", encoding="utf-8"
    )
    (repo / "decoys" / "nested.json").write_text(
        '{"nested": {"Resources": {"Bucket": {"Type": "AWS::S3::Bucket"}}}}\n',
        encoding="utf-8",
    )
    (repo / "decoys" / "comment.yml").write_text(
        "# AWSTemplateFormatVersion: '2010-09-09' in a comment\nname: plain\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")

    (repo / "src" / "app.py").write_text(
        "def compute(x: int) -> int:\n"
        "    # the skip button and check_plan.py remain mentioned on this unedited line\n"
        "    return x + 2\n",
        encoding="utf-8",
    )
    (repo / "deps" / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    (repo / "infra" / "template.yaml").write_text(
        'AWSTemplateFormatVersion: "2010-09-09"\n'
        "Description: Multi-stack CloudFormation template\n"
        "Resources:\n"
        "  ArtifactBucket:\n"
        "    Type: AWS::S3::Bucket\n"
        "    Properties:\n"
        "      BucketName: example-head-bucket\n",
        encoding="utf-8",
    )
    (repo / "docs" / "notes.md").write_text(
        "# Operator Guide\n\n"
        "A different sentence remains here.\n"
        "See the updated notes before you leave the step.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")
    return repo, base, head


def _seed_home_for_combined_fixture(repo: Path, home: Path) -> str:
    """Seed p/security-audit rule cache and offline advisory snapshots, then run review_setup."""
    cache = T.semgrep_cache(home, "p/security-audit")
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "rules.yml").write_text("rules: []\n", encoding="utf-8")
    pack_digest = T.digest_tree(cache)

    snapshot_meta = {
        "version": SNAPSHOT_VERSION,
        "date": SNAPSHOT_VERSION,
        "updated_at": SNAPSHOT_TIMESTAMP,
    }
    adv_base = home / ".config" / "infiquetra" / "reviews" / "advisories"

    pip_adv = adv_base / "pip-audit"
    pip_adv.mkdir(parents=True, exist_ok=True)
    (pip_adv / "advisories.json").write_text(
        json.dumps(
            {
                "version": SNAPSHOT_VERSION,
                "advisories": [
                    {
                        "package": "requests",
                        "version": "2.31.0",
                        "id": "PYSEC-2099-0001",
                        "aliases": ["CVE-2099-0001"],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (pip_adv / "metadata.json").write_text(json.dumps(snapshot_meta) + "\n", encoding="utf-8")

    osv_adv = adv_base / "osv-scanner"
    osv_zip = osv_adv / "osv-scalibr" / "PyPI"
    osv_zip.mkdir(parents=True, exist_ok=True)
    advisory = {
        "id": "GHSA-2099-0002",
        "aliases": ["CVE-2099-0002"],
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": "requests"},
                "versions": ["2.31.0"],
            }
        ],
        "severity": [{"score": "7.5"}],
    }
    with zipfile.ZipFile(osv_zip / "all.zip", "w") as archive:
        archive.writestr("GHSA-2099-0002.json", json.dumps(advisory))
    (osv_adv / "metadata.json").write_text(json.dumps(snapshot_meta) + "\n", encoding="utf-8")

    record = SETUP.survey(repo, home)
    assert record["rule_caches"]["semgrep-security"] == pack_digest
    assert record["rule_caches"]["p/security-audit"] == pack_digest
    assert "cloudformation" in record["languages"]
    assert set(record["pins"]) == {"checkov", "cfn-lint"}
    assert "pip-audit" in record["advisory_snapshots"]
    assert "osv-scanner" in record["advisory_snapshots"]
    return pack_digest


def test_two_offline_prepare_runs_produce_byte_identical_packets_across_python_cfn_markdown_and_semgrep_packs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hashlib.sha256((SCRIPTS / "review_formula.py").read_bytes()).hexdigest() == FORMULA_SHA256
    assert (
        hashlib.sha256((REFERENCES / "review-records.schema.json").read_bytes()).hexdigest()
        == SCHEMA_SHA256
    )

    bindir = _install_hermetic_bin(tmp_path, monkeypatch)
    repo, base, head = _build_combined_fixture(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    pack_digest = _seed_home_for_combined_fixture(repo, home)
    _prove_osv_cache_zip(
        bindir,
        home / ".config" / "infiquetra" / "reviews" / "advisories" / "osv-scanner",
        tmp_path,
    )

    profile = tmp_path / "outside" / "profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        json.dumps(
            {
                "schema": "repository_profile.v1",
                "review": {"shared_update_paths": {"python": ["save_record"]}},
                "review_tools": {
                    "languages": {
                        "python": {"test_command": "PYTHONPATH=. python3 -m pytest -q"}
                    },
                    "pins": {
                        "gitleaks": {"version": "1.0.0"},
                        "osv-scanner": {"version": "1.0.0"},
                        "semgrep": {
                            "version": "1.179.0",
                            "rules": [
                                {"path": "plugins/reviews/references/semgrep"},
                                {"pack": "p/security-audit", "sha256": pack_digest},
                            ],
                        },
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    builder = tmp_path / "builder.json"
    builder.write_text(
        json.dumps(
            {
                "kind": "builder_record",
                "schema": REC.SCHEMA,
                "unit": "R7",
                "acceptance_criteria": [
                    {
                        "id": "AC-1",
                        "text": "Combined R1-R6 offline prepare produces byte-identical packets.",
                        "checks": ["line"],
                    }
                ],
                "declarations": [],
                "reasons": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    bank = tmp_path / "bank.json"
    bank.write_text(
        json.dumps(
            {
                "schema": "question_bank.v1",
                "questions": [
                    {
                        "id": "correctness.q-compute",
                        "lens": "correctness",
                        "kind": "yes-no",
                        "options": [
                            {"id": "yes", "definition": "Breaks compute behaviour."},
                            {"id": "no", "definition": "Preserves compute behaviour."},
                        ],
                        "piece": "function",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    combined_adapters = [
        _find_adapter(ALL.ADAPTERS, "semgrep-security"),
        _find_adapter(ALL.ADAPTERS, "semgrep-saga"),
        _find_adapter(ALL.ADAPTERS, "osv-scanner"),
        _find_adapter(ALL.ADAPTERS, "gitleaks"),
        _find_adapter(PY.ADAPTERS, "bandit"),
        _find_adapter(PY.ADAPTERS, "pip-audit"),
        _find_adapter(PY.ADAPTERS, "ruff-lint"),
        _find_adapter(PY.ADAPTERS, "pytest-socket"),
        _find_adapter(INFRA.ADAPTERS, "checkov-cfn"),
        _find_adapter(INFRA.ADAPTERS, "cfn-lint"),
        _find_adapter(CHECKS.ADAPTERS, "changed-names"),
        _find_adapter(CHECKS.ADAPTERS, "machine-values"),
    ]

    def fake_ask(_state: Any, questions: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            status="ok",
            ok=True,
            model="jev-test",
            latency_ms=5,
            note="",
            usage={"input_tokens": 12, "output_tokens": 3},
            answers={key: {"type": "noul", "noul": 0.92} for key in questions},
        )

    packet_1 = tmp_path / "review-run-1" / "packet"
    packet_2 = tmp_path / "review-run-2" / "packet"
    for packet in (packet_1, packet_2):
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = CMD.main(
                [
                    "prepare",
                    "--repo",
                    str(repo),
                    "--base",
                    base,
                    "--head",
                    head,
                    "--profile",
                    str(profile),
                    "--builder-record",
                    str(builder),
                    "--out",
                    str(packet),
                    "--home",
                    str(home),
                    "--bank",
                    str(bank),
                ],
                adapters=combined_adapters,
                ask=fake_ask,
            )
        assert code == 0, err_buf.getvalue()

    # 1. Byte-for-byte identity across every packet artifact between run 1 and run 2.
    files_1 = sorted(
        path.relative_to(packet_1).as_posix() for path in packet_1.rglob("*") if path.is_file()
    )
    files_2 = sorted(
        path.relative_to(packet_2).as_posix() for path in packet_2.rglob("*") if path.is_file()
    )
    assert files_1 == files_2
    for rel in files_1:
        assert (packet_1 / rel).read_bytes() == (packet_2 / rel).read_bytes(), (
            f"packet file {rel!r} differed between consecutive offline prepare runs"
        )

    # The security pack answered in opposite orders. The packet must not follow that order.
    security_orders = [
        tuple(item["order"])
        for item in _invocations(bindir)
        if item.get("name") == "semgrep" and "p--security-audit" in str(item.get("cfg") or "")
    ]
    assert len(security_orders) >= 2, security_orders
    assert security_orders[0] != security_orders[1]
    assert security_orders[0] == tuple(reversed(security_orders[1]))
    prepare_configs = _semgrep_configs(_invocations(bindir))
    assert any("p--security-audit" in cfg for cfg in prepare_configs), prepare_configs
    assert any("p--security-audit" not in cfg for cfg in prepare_configs), prepare_configs
    pytest_calls = [item["argv"] for item in _invocations(bindir) if item.get("name") == "env"]
    assert any(
        "--disable-socket" in argv and "pytest_socket" in argv and "pytest" in argv
        for argv in pytest_calls
    ), pytest_calls

    # 2. Schema validation against review-records.schema.json.
    findings = json.loads((packet_1 / "findings.json").read_text(encoding="utf-8"))
    measurements = json.loads((packet_1 / "measurements.json").read_text(encoding="utf-8"))
    degraded = json.loads((packet_1 / "degraded.json").read_text(encoding="utf-8"))
    builder_rec = json.loads((packet_1 / "builder-record.json").read_text(encoding="utf-8"))
    _assert_against_schema(builder_rec)
    for record in (*findings, *measurements):
        _assert_against_schema(record)
    outcomes = json.loads((packet_1 / "outcomes.json").read_text(encoding="utf-8"))
    for grade in outcomes["lens_grades"]:
        _assert_against_schema(grade)
    prompts = json.loads((packet_1 / "where-to-look.json").read_text(encoding="utf-8"))
    _assert_unanswered_where_to_look(prompts)
    assert "socket.socket(socket.AF_INET, socket.SOCK_STREAM)" in (
        repo / "tests" / "test_app.py"
    ).read_text(encoding="utf-8")
    assert not any(
        "test_socket_construction_is_refused" in item["rule"]["ref"] for item in findings
    ), findings
    assert degraded == [], f"expected zero degraded inputs in combined run, got: {degraded}"

    # 3. Verify additive Semgrep execution (both custom saga rule and security pack findings).
    rule_refs = {item["rule"]["ref"] for item in findings}
    assert "saga.swallowed-error" in rule_refs, f"missing custom semgrep rule in {rule_refs}"
    assert "python.security.audit.exec-used" in rule_refs, (
        f"missing p/security-audit finding in {rule_refs}"
    )
    rule_sources = json.loads((packet_1 / "rule-sources.json").read_text(encoding="utf-8"))
    assert rule_sources["semgrep-security"]["rules"][0]["pack"] == "p/security-audit"
    assert rule_sources["semgrep-security"]["rules"][0]["sha256"] == pack_digest

    # 4. Verify CloudFormation checkov-cfn and cfn-lint findings on the real template only.
    assert "CKV_AWS_20" in rule_refs, f"missing checkov-cfn finding in {rule_refs}"
    assert "W3045" in rule_refs, f"missing cfn-lint finding in {rule_refs}"
    decoys = {"config.yaml", "resources.yaml", "nested.json", "comment.yml"}
    for ref in ("CKV_AWS_20", "W3045"):
        located = {
            item["location"]["file"]
            for item in findings
            if item["rule"]["ref"] == ref
        }
        assert located == {"infra/template.yaml"}, located
    assert not any(
        Path(item["location"]["file"]).name in decoys for item in findings
    ), "a non-CloudFormation decoy produced a finding"

    # 5. Verify Markdown prose filtering (R5 #261): code symbol `check_plan.py` reported
    # on the unedited Python line, while ordinary prose words are ignored.
    mentions = [item for item in findings if item["rule"]["ref"] == "check_plan.py"]
    assert mentions, f"missing removed Markdown code symbol in {rule_refs}"
    assert {item["location"]["file"] for item in mentions} == {"src/app.py"}
    for word in ("skip", "button", "the", "way", "leave", "sentence"):
        assert word not in rule_refs, word

    # 6. Verify offline advisory snapshot provenance and findings (R6 #245).
    assert "CVE-2099-0001" in rule_refs and "CVE-2099-0002" in rule_refs, (
        f"missing offline advisory findings in {rule_refs}"
    )
    osv_scans = [
        item["argv"]
        for item in _invocations(bindir)
        if item.get("name") == "osv-scanner" and "--version" not in item.get("argv", [])
    ]
    assert osv_scans, "osv-scanner never ran offline"
    assert all(
        "--offline" in argv and "--offline-vulnerabilities" in argv and "--data-source" in argv
        for argv in osv_scans
    )
    snapshots = json.loads((packet_1 / "advisory-snapshots.json").read_text(encoding="utf-8"))
    assert set(snapshots) == {"osv-scanner", "pip-audit"}
    assert snapshots["pip-audit"]["version"] == SNAPSHOT_VERSION
    assert snapshots["osv-scanner"]["version"] == SNAPSHOT_VERSION

    # 7. security_scan.py on its own call log, with the same profile wired in.
    monkeypatch.setattr(SCAN.Path, "home", lambda: home)
    (bindir / "invocations.jsonl").write_text("", encoding="utf-8")
    scan_out = tmp_path / "security-scan-out"
    scan_err = io.StringIO()
    with redirect_stderr(scan_err):
        scan_code = SCAN.main(
            [
                "--repo", str(repo),
                "--commit", head,
                "--output", str(scan_out),
                "--profile", str(profile),
            ]
        )
    assert scan_code == 1, scan_err.getvalue()
    summary = json.loads((scan_out / "summary.json").read_text(encoding="utf-8"))
    assert summary["commit"] == head
    assert summary["exit_code"] == 1
    rows_by_id = {row["id"]: row for row in summary["rows"]}
    for expected_ran in (
        "semgrep-security", "semgrep-saga", "pip-audit", "osv-scanner",
        "checkov-cfn", "bandit", "gitleaks",
    ):
        assert rows_by_id[expected_ran]["status"] == "ran", rows_by_id[expected_ran]
    scan_findings = json.loads((scan_out / "findings.json").read_text(encoding="utf-8"))
    for record in scan_findings:
        _assert_against_schema(record)
    scan_refs = {item["rule"]["ref"] for item in scan_findings}
    assert "python.security.audit.exec-used" in scan_refs, scan_refs
    assert "python.security.audit. weak-hash" in scan_refs, scan_refs
    assert "CKV_AWS_20" in scan_refs and "CVE-2099-0002" in scan_refs
    assert "saga.swallowed-error" in scan_refs, scan_refs
    scan_log = _invocations(bindir)
    assert scan_log, "security_scan.py recorded no invocations of its own"
    scan_configs = _semgrep_configs(scan_log)
    assert any("p--security-audit" in cfg for cfg in scan_configs), scan_configs
    assert any("p--security-audit" not in cfg for cfg in scan_configs), scan_configs


def test_review_tools_direct_script_known_gap_and_cloudformation_setup_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = _install_hermetic_bin(tmp_path, monkeypatch)
    repo, base, head = _build_combined_fixture(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    _seed_home_for_combined_fixture(repo, home)

    # 1. R2 (#258): Direct script invocation `python3 plugins/reviews/scripts/review_tools.py run`
    # catches an adapter's ToolGap("known-gap", ...) identically to the imported module and exits 0.
    gap_profile = tmp_path / "gap-profile.json"
    gap_profile.write_text(
        json.dumps(
            {
                "schema": "repository_profile.v1",
                "review_tools": {"languages": {"python": {"test_command": ""}}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    direct_out = tmp_path / "direct-cli-out"
    direct_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "review_tools.py"),
            "run",
            "--repo",
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--profile",
            str(gap_profile),
            "--output",
            str(direct_out),
            "--home",
            str(home),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert direct_proc.returncode == 0, direct_proc.stderr
    assert "Traceback" not in direct_proc.stderr
    direct_degraded = json.loads((direct_out / "degraded.json").read_text(encoding="utf-8"))
    assert any(
        item.get("tool") == "pytest-socket"
        and item.get("input") == "testing.flaky-order-or-network"
        and item.get("reason") == "known-gap"
        for item in direct_degraded
    ), f"expected pytest-socket known-gap in {direct_degraded}"
    imported_out = tmp_path / "imported-cli-out"
    imported_code = T.run(
        repo, base, head, gap_profile, imported_out, home=home, framework=False,
    )
    assert imported_code == 0

    def _socket_gaps(path: Path) -> list[dict[str, Any]]:
        return [
            item
            for item in json.loads((path / "degraded.json").read_text(encoding="utf-8"))
            if item.get("tool") == "pytest-socket" and item.get("reason") == "known-gap"
        ]

    assert _socket_gaps(direct_out) == _socket_gaps(imported_out)
    assert _socket_gaps(direct_out)

    # 2. R3 (#257): CloudFormation detection in review-setup pins checkov and cfn-lint on real CFN
    # templates while rejecting ordinary YAML/JSON/Resources/AWS:: comments, and review_tools
    # honors saved pins even when adapter default versions differ.
    non_cfn = tmp_path / "non-cfn-repo"
    non_cfn.mkdir()
    (non_cfn / "config.yaml").write_text("service: api\nport: 8080\n", encoding="utf-8")
    (non_cfn / "resources.yaml").write_text(
        "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n", encoding="utf-8"
    )
    (non_cfn / "nested.json").write_text(
        '{"nested": {"Resources": {"Bucket": {"Type": "AWS::S3::Bucket"}}}}\n',
        encoding="utf-8",
    )
    (non_cfn / "comment.yml").write_text(
        "# AWSTemplateFormatVersion: '2010-09-09' in a comment\nname: plain\n",
        encoding="utf-8",
    )
    non_cfn_record = SETUP.survey(non_cfn, tmp_path / "non-cfn-home")
    assert "cloudformation" not in non_cfn_record["languages"]
    assert non_cfn_record["pins"] == {}

    off_default_cfn = [
        replace(adapter, default_version="0.0.1")
        for adapter in INFRA.ADAPTERS
        if adapter.id in {"checkov-cfn", "cfn-lint"}
    ]
    honored_out = tmp_path / "honored-pins-out"
    bare_profile = tmp_path / "bare-profile.json"
    bare_profile.write_text("{}\n", encoding="utf-8")
    code = T.run(
        repo,
        base,
        head,
        bare_profile,
        honored_out,
        home=home,
        adapters=off_default_cfn,
        framework=False,
    )
    assert code == 0
    honored_degraded = json.loads((honored_out / "degraded.json").read_text(encoding="utf-8"))
    assert not any(
        item.get("reason") == "version-mismatch" for item in honored_degraded
    ), f"saved machine.json CFN pins were not honored: {honored_degraded}"

    # 3. R4 (#246): Python pytest-socket plugin loads hermetically without host uv under the
    # resolved interpreter and blocks socket creation inside the test run.
    socket_adapter = _find_adapter(PY.ADAPTERS, "pytest-socket")
    socket_profile = tmp_path / "socket-profile.json"
    socket_profile.write_text(
        json.dumps(
            {
                "schema": "repository_profile.v1",
                "review_tools": {
                    "languages": {
                        "python": {"test_command": "PYTHONPATH=. python3 -m pytest -q"}
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    socket_out = tmp_path / "socket-out"
    socket_code = T.run(
        repo,
        base,
        head,
        socket_profile,
        socket_out,
        home=home,
        adapters=[socket_adapter],
        framework=False,
    )
    assert socket_code == 0
    assert json.loads((socket_out / "degraded.json").read_text(encoding="utf-8")) == []
    assert json.loads((socket_out / "findings.json").read_text(encoding="utf-8")) == []
    assert "socket.socket(socket.AF_INET, socket.SOCK_STREAM)" in (
        repo / "tests" / "test_app.py"
    ).read_text(encoding="utf-8")
    assert shutil.which("uv") == str(bindir / "uv")
    uv_calls = [item["argv"] for item in _invocations(bindir) if item.get("name") == "uv"]
    assert any(
        "pip" in argv and "install" in argv and any(str(arg).startswith("pytest-socket==") for arg in argv)
        for argv in uv_calls
    ), uv_calls
    pytest_calls = [item["argv"] for item in _invocations(bindir) if item.get("name") == "env"]
    assert any(
        "--disable-socket" in argv and "pytest_socket" in argv and "pytest" in argv
        for argv in pytest_calls
    ), pytest_calls
