"""Fail-first red tests for R6 (issue #245): offline advisory snapshots & deterministic prepare.

Every test in this module has ``offline`` in its name so ``pytest -k offline`` selects the full
suite. All tests run hermetically with network sockets refused and no assumption of host-installed
``cargo``, ``cargo-deny``, ``osv-scanner``, ``pip-audit``, ``npm``, or ``uv``.
"""

from __future__ import annotations

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
RUST = _load("review_adapters_rust")
ALL = _load("review_adapters_all_languages")
PY = _load("review_adapters_python")
TS = _load("review_adapters_typescript")
SETUP = _load("review_setup")
CMD = _load("review_command")
REC = _load("review_records")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse all socket and HTTP calls during R6 offline tests."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("R6 offline tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _find_adapter(adapters: tuple[Any, ...], tool_id: str) -> Any:
    matches = [adapter for adapter in adapters if adapter.id == tool_id]
    assert len(matches) == 1, f"expected 1 adapter for {tool_id!r}, found {len(matches)}"
    return matches[0]


def _context(
    tmp_path: Path,
    *,
    files: dict[str, str] | None = None,
    test_command: str = "pytest",
    home: Path | None = None,
) -> Any:
    root = tmp_path / "scan-root"
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in (files or {}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    resolved_home = home if home is not None else (tmp_path / "home")
    resolved_home.mkdir(parents=True, exist_ok=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return T.ScanContext(
        root,
        root,
        resolved_home,
        scratch=scratch,
        test_command=test_command,
        base="base-sha",
        head="head-sha",
    )


def _seed_advisory_snapshots(home: Path) -> dict[str, Any]:
    """Seed local advisory snapshots and machine.json provenance metadata under *home*.

    Writes snapshot directories under ``<home>/.config/infiquetra/reviews/advisories/<name>``
    (and ``<home>/.saga/advisories/<name>``) plus ``advisory_snapshots`` metadata in
    ``<home>/.config/infiquetra/reviews/machine.json`` so adapters and ``prepare`` can locate
    the local snapshot and record its version/date without touching the network.
    """
    snapshot_meta = {
        "version": SNAPSHOT_VERSION,
        "date": SNAPSHOT_VERSION,
        "updated_at": SNAPSHOT_TIMESTAMP,
        "sha256": hashlib.sha256(SNAPSHOT_VERSION.encode("utf-8")).hexdigest(),
    }
    names = ("cargo-deny", "rustsec", "osv-scanner", "osv", "pip-audit", "pypa", "npm-audit", "npm")
    snapshots_record: dict[str, dict[str, Any]] = {}
    for base_dir in (
        home / ".config" / "infiquetra" / "reviews" / "advisories",
        home / ".saga" / "advisories",
    ):
        for name in names:
            folder = base_dir / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "advisories.json").write_text(
                json.dumps({"version": SNAPSHOT_VERSION, "advisories": [], "vulnerabilities": {}})
                + "\n",
                encoding="utf-8",
            )
            (folder / "metadata.json").write_text(
                json.dumps(snapshot_meta) + "\n",
                encoding="utf-8",
            )
            if folder.parent.name == "advisories" and ".config" in str(folder):
                snapshots_record[name] = {**snapshot_meta, "path": str(folder)}

    existing = SETUP.load_machine(home) or {
        "schema": SETUP.MACHINE_SCHEMA,
        "ran": True,
        "languages": ["rust", "python", "typescript"],
        "pins": {},
        "survey": {"tools": [], "sandbox": SETUP.sandbox_admission()},
        "rule_caches": {},
        "updated_at": SNAPSHOT_TIMESTAMP,
    }
    existing["advisory_snapshots"] = snapshots_record
    SETUP.write_machine(home, existing)
    return snapshots_record


def test_offline_d2_formula_and_schema_byte_identity() -> None:
    formula_bytes = (SCRIPTS / "review_formula.py").read_bytes()
    schema_bytes = (REFERENCES / "review-records.schema.json").read_bytes()
    assert hashlib.sha256(formula_bytes).hexdigest() == FORMULA_SHA256
    assert hashlib.sha256(schema_bytes).hexdigest() == SCHEMA_SHA256


def test_offline_cargo_deny_uses_local_snapshot_and_disables_fetch(tmp_path: Path) -> None:
    adapter = _find_adapter(RUST.ADAPTERS, "cargo-deny")
    rust_files = {
        "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n',
        "Cargo.lock": 'version = 3\n\n[[package]]\nname = "demo"\nversion = "0.1.0"\n',
    }

    # 1. When no local advisory snapshot has been refreshed in home, cargo-deny must
    # record a deterministic ToolGap rather than cloning the advisory DB from the network.
    empty_ctx = _context(tmp_path / "absent", files=rust_files)
    with pytest.raises(T.ToolGap) as exc_info:
        adapter.invoke(empty_ctx)
    assert any(
        token in exc_info.value.reason
        for token in ("known-gap", "missing", "snapshot", "advisory")
    ), f"unexpected gap reason: {exc_info.value.reason!r}"

    # 2. cargo-deny 0.20.2 takes global --offline. db-path is deny.toml config.
    seeded_home = tmp_path / "seeded-home"
    _seed_advisory_snapshots(seeded_home)
    seeded_ctx = _context(tmp_path / "present", files=rust_files, home=seeded_home)
    argv = adapter.invoke(seeded_ctx)
    assert argv, "expected non-empty cargo-deny argv when snapshot is present"
    assert "--offline" in argv, f"cargo-deny must pass --offline: {argv!r}"
    assert "--disable-fetch" not in argv, f"cargo-deny 0.20.2 rejects --disable-fetch: {argv!r}"
    assert "--db-path" not in argv, f"cargo-deny 0.20.2 rejects --db-path: {argv!r}"
    config = Path(argv[argv.index("--config") + 1])
    text = config.read_text(encoding="utf-8")
    assert "db-path = " in text
    assert 'maximum-db-staleness = "P3650D"' in text


def test_offline_cargo_invocations_pass_offline_and_never_fetch_crates(tmp_path: Path) -> None:
    rust_files = {
        "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n',
        "Cargo.lock": 'version = 3\n\n[[package]]\nname = "demo"\nversion = "0.1.0"\n',
        "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n",
    }
    ctx = _context(tmp_path, files=rust_files)

    for adapter_id in ("cargo-check", "clippy"):
        adapter = _find_adapter(RUST.ADAPTERS, adapter_id)
        argv = adapter.invoke(ctx)
        assert argv, f"expected non-empty argv for {adapter_id}"
        assert "--offline" in argv or "--frozen" in argv, (
            f"{adapter_id} must pass --offline or --frozen to prevent crate fetches: {argv!r}"
        )

    env, temps = T._tool_env(tmp_path / "home")
    try:
        assert env.get("CARGO_NET_OFFLINE") == "true", (
            "review_tools._tool_env must set CARGO_NET_OFFLINE=true for cargo tools"
        )
    finally:
        import shutil

        for temp in temps:
            shutil.rmtree(temp, ignore_errors=True)


def test_offline_osv_scanner_uses_local_snapshot_and_offline_flag(tmp_path: Path) -> None:
    adapter = _find_adapter(ALL.ADAPTERS, "osv-scanner")
    lock_files = {
        "Cargo.lock": 'version = 3\n\n[[package]]\nname = "demo"\nversion = "0.1.0"\n',
    }

    # 1. Without a local advisory snapshot, osv-scanner must raise a deterministic ToolGap.
    empty_ctx = _context(tmp_path / "absent", files=lock_files)
    with pytest.raises(T.ToolGap) as exc_info:
        adapter.invoke(empty_ctx)
    assert any(
        token in exc_info.value.reason
        for token in ("known-gap", "missing", "snapshot", "advisory")
    ), f"unexpected gap reason: {exc_info.value.reason!r}"

    # 2. With a local advisory snapshot seeded, osv-scanner must run with --offline.
    seeded_home = tmp_path / "seeded-home"
    _seed_advisory_snapshots(seeded_home)
    seeded_ctx = _context(tmp_path / "present", files=lock_files, home=seeded_home)
    argv = adapter.invoke(seeded_ctx)
    assert argv, "expected non-empty osv-scanner argv when snapshot is present"
    assert "--offline" in argv and "--offline-vulnerabilities" in argv, (
        f"osv-scanner must pass --offline and --offline-vulnerabilities: {argv!r}"
    )
    assert argv[argv.index("--data-source") + 1] == "native", (
        f"osv-scanner --data-source accepts native or deps.dev, not a directory: {argv!r}"
    )
    assert any(
        part.startswith("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=") for part in argv
    ), f"osv-scanner must receive the local DB cache directory: {argv!r}"


def test_offline_pip_audit_uses_local_snapshot_and_never_queries_network(tmp_path: Path) -> None:
    adapter = _find_adapter(PY.ADAPTERS, "pip-audit")
    py_files = {
        "requirements.txt": "requests==2.31.0\n",
    }

    # 1. Without a local advisory snapshot, pip-audit must raise a deterministic ToolGap
    # rather than querying PyPI / OSV over the network.
    empty_ctx = _context(tmp_path / "absent", files=py_files)
    with pytest.raises(T.ToolGap) as exc_info:
        adapter.invoke(empty_ctx)
    assert any(
        token in exc_info.value.reason
        for token in ("known-gap", "missing", "snapshot", "advisory")
    ), f"unexpected gap reason: {exc_info.value.reason!r}"

    # 2. With a local advisory snapshot seeded, pip-audit must run offline against the local
    # snapshot and never invoke pip dependency resolution over the network.
    seeded_home = tmp_path / "seeded-home"
    _seed_advisory_snapshots(seeded_home)
    seeded_ctx = _context(tmp_path / "present", files=py_files, home=seeded_home)
    folder = (
        seeded_home / ".config" / "infiquetra" / "reviews" / "advisories" / "pip-audit"
    )
    (folder / "advisories.json").write_text(
        json.dumps({
            "advisories": [{
                "package": "requests",
                "version": "2.31.0",
                "id": "PYSEC-2099-0001",
                "aliases": ["CVE-2099-0001"],
            }],
        }),
        encoding="utf-8",
    )
    argv = adapter.invoke(seeded_ctx)
    assert argv and argv[0] == sys.executable, (
        f"pip-audit 2.10.1 has no --offline flag; evaluate the snapshot: {argv!r}"
    )
    assert "--offline" not in argv
    completed = subprocess.run(argv, check=True, capture_output=True, text=True)
    parsed = PY._parse_pip_audit(completed.stdout)
    assert any("PYSEC-2099-0001" in hit.advisory_ids for hit in parsed.hits)


def test_offline_uv_invocations_in_python_adapter_pass_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    py_files = {
        "src/app.py": "def add(a: int, b: int) -> int:\n    return a + b\n",
        "tests/test_app.py": "from src.app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    }
    ctx = _context(tmp_path, files=py_files, test_command="pytest")

    for adapter_id in ("ruff-lint", "pytest-randomly", "pytest-socket", "cosmic-ray"):
        adapter = _find_adapter(PY.ADAPTERS, adapter_id)
        if adapter.version_argv and "uv" in adapter.version_argv:
            assert "--offline" in adapter.version_argv, (
                f"{adapter_id}.version_argv must pass --offline to uv: {adapter.version_argv!r}"
            )
        argv = adapter.invoke(ctx)
        assert argv, f"expected non-empty argv for {adapter_id}"
        assert "--offline" in argv, (
            f"{adapter_id} invoke must pass --offline to uv: {argv!r}"
        )

    recorded_uv_calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        recorded_uv_calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(PY.subprocess, "run", fake_run)
    PY._install_pytest_plugin(ctx, PY._RANDOMLY_PACKAGE, sys.executable)
    assert len(recorded_uv_calls) == 1
    assert "--offline" in recorded_uv_calls[0], (
        f"_install_pytest_plugin must pass --offline to uv pip install: {recorded_uv_calls[0]!r}"
    )


def test_offline_npm_audit_uses_local_snapshot_and_never_hits_registry(tmp_path: Path) -> None:
    adapter = _find_adapter(TS.ADAPTERS, "npm-audit")
    ts_files = {
        "package.json": json.dumps({"name": "demo", "version": "1.0.0", "dependencies": {"lodash": "4.17.21"}}),
        "package-lock.json": json.dumps(
            {
                "name": "demo",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "demo", "version": "1.0.0"},
                    "node_modules/lodash": {"version": "4.17.21"},
                },
            }
        ),
    }

    # 1. Without a local advisory snapshot, npm-audit must raise a deterministic ToolGap
    # rather than posting to registry.npmjs.org.
    empty_ctx = _context(tmp_path / "absent", files=ts_files)
    with pytest.raises(T.ToolGap) as exc_info:
        adapter.invoke(empty_ctx)
    assert any(
        token in exc_info.value.reason
        for token in ("known-gap", "missing", "snapshot", "advisory")
    ), f"unexpected gap reason: {exc_info.value.reason!r}"

    # 2. With a local advisory snapshot seeded, npm-audit must not run bare `npm audit --json`
    # against the live registry.
    seeded_home = tmp_path / "seeded-home"
    _seed_advisory_snapshots(seeded_home)
    seeded_ctx = _context(tmp_path / "present", files=ts_files, home=seeded_home)
    folder = (
        seeded_home / ".config" / "infiquetra" / "reviews" / "advisories" / "npm-audit"
    )
    (folder / "advisories.json").write_text(
        json.dumps({
            "advisories": [{
                "package": "lodash",
                "version": "4.17.21",
                "id": "GHSA-0000-0000-0000",
                "severity": "high",
            }],
        }),
        encoding="utf-8",
    )
    argv = adapter.invoke(seeded_ctx)
    assert argv and argv[0] == sys.executable, (
        f"npm 12 --offline reports nothing; evaluate the snapshot: {argv!r}"
    )
    assert "npm" not in argv
    assert "--offline" not in argv
    completed = subprocess.run(argv, check=True, capture_output=True, text=True)
    parsed = TS._parse_npm_audit(completed.stdout)
    assert any(hit.rule_id == "GHSA-0000-0000-0000" for hit in parsed.hits)
    assert any(hit.row == "security.dependency-high" for hit in parsed.hits)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_offline_prepare_rust_fixture_twice_writes_byte_identical_packets_and_snapshot_metadata(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "rust-repo"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "r6-offline@example.com")
    _git(repo, "config", "user.name", "r6-offline")
    (repo / "Cargo.toml").write_text(
        '[package]\nname = "r6-fixture"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (repo / "Cargo.lock").write_text(
        'version = 3\n\n[[package]]\nname = "r6-fixture"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (repo / "src" / "lib.rs").write_text(
        "pub fn compute(x: i32) -> i32 {\n    x + 1\n}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")

    (repo / "src" / "lib.rs").write_text(
        "pub fn compute(x: i32) -> i32 {\n    x + 2\n}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    home.mkdir()
    _seed_advisory_snapshots(home)

    profile = tmp_path / "outside" / "profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(json.dumps({"schema": "repository_profile.v1"}) + "\n", encoding="utf-8")

    builder = tmp_path / "builder.json"
    builder.write_text(
        json.dumps(
            {
                "kind": "builder_record",
                "schema": REC.SCHEMA,
                "unit": "R6",
                "acceptance_criteria": [
                    {
                        "id": "AC-1",
                        "text": "Offline prepare produces deterministic byte-identical packets.",
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
        ),
        encoding="utf-8",
    )

    rust_adapters = [
        _find_adapter(RUST.ADAPTERS, "cargo-deny"),
        _find_adapter(RUST.ADAPTERS, "cargo-check"),
        _find_adapter(RUST.ADAPTERS, "clippy"),
        _find_adapter(ALL.ADAPTERS, "osv-scanner"),
    ]
    seen_invocations: list[list[str]] = []

    def hermetic_runner(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
        shell: bool,
        umask: int | None = None,
    ) -> Any:
        assert shell is False
        prog = Path(argv[0]).name
        if prog == "git":
            proc = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
        seen_invocations.append(list(argv))
        if "--version" in argv or "-V" in argv:
            for adapter in rust_adapters:
                if adapter.tool == prog or adapter.id == prog:
                    return T.ProcessResult(0, f"{prog} {adapter.default_version}\n", "")
            return T.ProcessResult(0, "1.0.0\n", "")
        if prog == "cargo-deny":
            assert "--offline" in argv, f"cargo-deny called without --offline: {argv!r}"
            assert "--disable-fetch" not in argv
            assert "--db-path" not in argv
            config = Path(argv[argv.index("--config") + 1])
            assert "db-path = " in config.read_text(encoding="utf-8")
            return T.ProcessResult(0, '{"type":"summary","fields":{"advisories":0}}\n', "")
        if "osv-scanner" in argv:
            assert "--offline" in argv and "--offline-vulnerabilities" in argv
            assert argv[argv.index("--data-source") + 1] == "native"
            assert any(
                part.startswith("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=") for part in argv
            )
            return T.ProcessResult(0, '{"results":[]}\n', "")
        if prog in {"cargo", "cargo-clippy"}:
            assert "--offline" in argv or "--frozen" in argv, (
                f"{prog} called without --offline/--frozen: {argv!r}"
            )
            assert env.get("CARGO_NET_OFFLINE") == "true"
            return T.ProcessResult(0, '{"reason":"build-finished","success":true}\n', "")
        return T.ProcessResult(0, "{}\n", "")

    def fake_ask(_state: Any, questions: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            status="ok",
            ok=True,
            model="jev-test",
            latency_ms=5,
            note="",
            usage={"input_tokens": 10, "output_tokens": 2},
            answers={key: {"type": "noul", "noul": 0.1} for key in questions},
        )

    packet_a = tmp_path / "packet-a"
    packet_b = tmp_path / "packet-b"
    for packet in (packet_a, packet_b):
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
                adapters=rust_adapters,
                runner=hermetic_runner,
                ask=fake_ask,
            )
        assert code == 0, err_buf.getvalue()

    assert seen_invocations, "expected hermetic_runner to execute offline Rust/advisory adapters"

    files_a = sorted(
        path.relative_to(packet_a).as_posix() for path in packet_a.rglob("*") if path.is_file()
    )
    files_b = sorted(
        path.relative_to(packet_b).as_posix() for path in packet_b.rglob("*") if path.is_file()
    )
    assert files_a == files_b, f"packet file sets differ: {files_a} vs {files_b}"
    for rel in files_a:
        bytes_a = (packet_a / rel).read_bytes()
        bytes_b = (packet_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"packet artifact {rel!r} differed across identical prepare runs"

    # Verify the packet records the local advisory snapshot version/date used.
    packet_texts = "\n".join(
        (packet_a / rel).read_text(encoding="utf-8", errors="ignore")
        for rel in files_a
        if rel.endswith(".json")
    )
    assert SNAPSHOT_VERSION in packet_texts, (
        f"expected packet JSON artifacts to record local advisory snapshot version/date "
        f"{SNAPSHOT_VERSION!r}; checked files: {files_a}"
    )
    recorded = json.loads((packet_a / "advisory-snapshots.json").read_text(encoding="utf-8"))
    assert set(recorded) == {"cargo-deny", "osv-scanner"}
    assert recorded["cargo-deny"]["version"] == SNAPSHOT_VERSION
    assert recorded["osv-scanner"]["version"] == SNAPSHOT_VERSION


def test_offline_missing_snapshot_is_not_cached_as_an_empty_base(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "r6-offline@example.com")
    _git(repo, "config", "user.name", "r6-offline")
    (repo / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    home.mkdir()
    adapter = _find_adapter(PY.ADAPTERS, "pip-audit")
    context = T.ScanContext(
        repo, repo, home, scratch=tmp_path / "scratch", base=base, head=head,
    )
    (context.scratch or tmp_path).mkdir(exist_ok=True)

    def runner(argv, *, cwd, env, timeout, shell, umask=None):
        del cwd, env, timeout, shell, umask
        completed = subprocess.run(argv, check=False, capture_output=True, text=True)
        return T.ProcessResult(completed.returncode, completed.stdout, completed.stderr)

    env, temps = T._tool_env(home)
    try:
        degraded: list[dict[str, str]] = []
        hits, _digest = T._base_and_head(
            adapter, repo, base, head, repo, context, runner, env, 30, "2.10.1",
            degraded, "rules", [],
        )
        assert hits == ()
        assert any(item.get("reason") == "missing-advisory-snapshot" for item in degraded)
        assert not (home / ".saga" / "review-cache").exists()

        folder = home / ".config" / "infiquetra" / "reviews" / "advisories" / "pip-audit"
        folder.mkdir(parents=True)
        (folder / "advisories.json").write_text(
            json.dumps({
                "advisories": [{
                    "package": "requests",
                    "version": "2.31.0",
                    "id": "PYSEC-2099-0001",
                }],
            }),
            encoding="utf-8",
        )
        before = T.advisory_cache_token(home, "pip-audit")
        degraded.clear()
        hits, _digest = T._base_and_head(
            adapter, repo, base, head, repo, context, runner, env, 30, "2.10.1",
            degraded, "rules", [],
        )
        assert degraded == [], degraded
        assert hits == ()
        assert (home / ".saga" / "review-cache" / "pip-audit").is_dir()
        (folder / "advisories.json").write_text(
            (folder / "advisories.json").read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        assert T.advisory_cache_token(home, "pip-audit") != before
    finally:
        for temp in temps:
            shutil.rmtree(temp, ignore_errors=True)


def test_offline_snapshot_fingerprint_ignores_adapters_without_one(tmp_path: Path) -> None:
    home = tmp_path / "home"
    folder = home / ".config" / "infiquetra" / "reviews" / "advisories" / "npm-audit"
    folder.mkdir(parents=True)
    payload = folder / "advisories.json"
    payload.write_text('{"advisories":[]}\n', encoding="utf-8")
    first = T.advisory_cache_token(home, "npm-audit")
    payload.write_text('{"advisories":[{"id":"GHSA-0000-0000-0000"}]}\n', encoding="utf-8")
    assert first != T.advisory_cache_token(home, "npm-audit")
    assert T.advisory_cache_token(home, "ruff-lint") == ""
    assert T.advisory_cache_token(tmp_path / "empty", "npm-audit") == "missing"
    assert "missing-advisory-snapshot" in CMD._GAP_REASONS


def test_offline_failed_scan_is_not_recorded_as_snapshot_provenance(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _seed_advisory_snapshots(home)
    context = _context(
        tmp_path,
        files={"requirements.txt": "requests==2.31.0\n"},
        home=home,
    )
    adapter = _find_adapter(ALL.ADAPTERS, "osv-scanner")

    def missing(argv, *, cwd, env, timeout, shell, umask=None):
        del argv, cwd, env, timeout, shell, umask
        raise FileNotFoundError("osv-scanner")

    T.clear_used_snapshots(home)
    _hits, _digest, problem, ran = T._scan_root(
        adapter, context, missing, {}, 5, "head", [], [],
    )
    assert ran is True and problem == "missing"
    assert T.advisory_used_record(home) == {}

    def succeeded(argv, *, cwd, env, timeout, shell, umask=None):
        del argv, cwd, env, timeout, shell, umask
        return T.ProcessResult(0, '{"results":[]}\n', "")

    T._scan_root(adapter, context, succeeded, {}, 5, "head", [], [])
    used = T.advisory_used_record(home)
    assert set(used) == {"osv-scanner"}
    assert used["osv-scanner"]["version"] == SNAPSHOT_VERSION


def test_offline_review_setup_requires_a_payload_and_reads_osv_native_layout(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    meta = home / ".config" / "infiquetra" / "reviews" / "advisories" / "pip-audit"
    meta.mkdir(parents=True)
    (meta / "metadata.json").write_text(
        json.dumps({"version": "metadata-only"}) + "\n", encoding="utf-8",
    )
    native = home / ".config" / "infiquetra" / "reviews" / "advisories" / "osv-scanner"
    zip_dir = native / "osv-scalibr" / "PyPI"
    zip_dir.mkdir(parents=True)
    (zip_dir / "all.zip").write_bytes(b"PK\x03\x04")
    record = T.advisory_snapshot_record(home)
    assert "pip-audit" not in record
    assert "osv-scanner" in record
    repo = tmp_path / "repo"
    repo.mkdir()
    surveyed = SETUP.survey(repo, home)
    snapshots = surveyed["advisory_snapshots"]
    assert "pip-audit" not in snapshots
    assert "osv-scanner" in snapshots
    assert T.osv_local_db_cache(native) == native


def test_offline_security_scan_stages_advisory_snapshots(tmp_path: Path) -> None:
    security = _load("security_scan")
    machine = tmp_path / "machine"
    deny = machine / ".config" / "infiquetra" / "reviews" / "advisories" / "cargo-deny"
    deny.mkdir(parents=True)
    (deny / "advisories.json").write_text('{"advisories":[]}\n', encoding="utf-8")
    meta = machine / ".config" / "infiquetra" / "reviews" / "advisories" / "npm-audit"
    meta.mkdir(parents=True)
    (meta / "metadata.json").write_text("{}\n", encoding="utf-8")
    native = machine / ".saga" / "advisories" / "osv-scanner" / "osv-scalibr" / "PyPI"
    native.mkdir(parents=True)
    (native / "all.zip").write_bytes(b"PK\x03\x04")
    staged = tmp_path / "staged"
    staged.mkdir()
    security._rule_home(staged, machine)
    assert T.advisory_snapshot(staged, "cargo-deny") is not None
    assert not (staged / ".config" / "infiquetra" / "reviews" / "advisories" / "npm-audit").exists()
    found = T.advisory_snapshot(staged, "osv-scanner")
    assert found is not None and (found / "osv-scalibr" / "PyPI" / "all.zip").is_file()


def test_offline_fresh_cargo_home_links_the_operator_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = tmp_path / "operator-cargo"
    (operator / "registry").mkdir(parents=True)
    (operator / "git").mkdir()
    (operator / "registry" / "marker").write_text("warm\n", encoding="utf-8")
    monkeypatch.setenv("CARGO_HOME", str(operator))
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    T.link_operator_cargo_cache(fresh)
    assert (fresh / "registry").is_symlink()
    assert (fresh / "registry" / "marker").read_text(encoding="utf-8") == "warm\n"
    assert (fresh / "git").is_symlink()
    T.link_operator_cargo_cache(operator)
    assert not (operator / "registry").is_symlink()

    seen: dict[str, bool] = {}

    def runner(argv, *, cwd, env, timeout, shell, umask=None):
        del argv, cwd, timeout, shell, umask
        home = Path(env["CARGO_HOME"])
        seen["linked"] = (home / "registry").is_symlink()
        seen["offline"] = env.get("CARGO_NET_OFFLINE") == "true"
        return T.ProcessResult(0, "", "")

    adapter = _find_adapter(RUST.ADAPTERS, "cargo-check")
    T._execute(
        adapter, ["cargo", "check", "--offline"], tmp_path, runner,
        {"CARGO_NET_OFFLINE": "true"}, 5,
    )
    assert seen == {"linked": True, "offline": True}

    deps = _load("review_dependencies")
    work = tmp_path / "fetch"
    work.mkdir()
    fetched = deps._cargo_env(work)
    assert (Path(fetched["CARGO_HOME"]) / "registry").is_symlink()
    assert fetched.get("CARGO_NET_OFFLINE") == "true"


def test_offline_tool_env_points_uv_at_the_warmed_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "uv-cache"
    cache.mkdir()
    monkeypatch.setenv("UV_CACHE_DIR", str(cache))
    home = tmp_path / "home"
    home.mkdir()
    env, temps = T._tool_env(home)
    relocated, relocated_temps = T._relocated_env()
    try:
        assert env["UV_CACHE_DIR"] == str(cache)
        assert env["HOME"] != str(Path.home())
        assert relocated["UV_CACHE_DIR"] == str(cache)
        assert relocated["HOME"] != str(Path.home())
        assert PY._plugin_install_env()["UV_CACHE_DIR"] == str(cache)
    finally:
        for temp in (*temps, *relocated_temps):
            shutil.rmtree(temp, ignore_errors=True)


def test_offline_absent_pinned_toolchain_is_a_known_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rustup_home = tmp_path / "rustup"
    (rustup_home / "toolchains" / "1.80.0-x86_64-unknown-linux-gnu").mkdir(parents=True)
    monkeypatch.setenv("RUSTUP_HOME", str(rustup_home))
    rust_files = {
        "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n',
        "Cargo.lock": 'version = 3\n\n[[package]]\nname = "demo"\nversion = "0.1.0"\n',
        "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n",
    }
    present = _context(tmp_path / "present", files={**rust_files, "rust-toolchain": "1.80.0\n"})
    argv = _find_adapter(RUST.ADAPTERS, "cargo-check").invoke(present)
    assert "--offline" in argv

    absent = _context(
        tmp_path / "absent",
        files={**rust_files, "rust-toolchain.toml": '[toolchain]\nchannel = "0.0.0-absent"\n'},
    )
    with pytest.raises(T.ToolGap) as exc_info:
        _find_adapter(RUST.ADAPTERS, "cargo-check").invoke(absent)
    assert exc_info.value.reason == "known-gap"

    no_pin = _context(tmp_path / "nopin", files=rust_files)
    assert "--offline" in _find_adapter(RUST.ADAPTERS, "clippy").invoke(no_pin)

    monkeypatch.delenv("RUSTUP_HOME", raising=False)
    empty_home = tmp_path / "no-toolchains"
    empty_home.mkdir()
    monkeypatch.setenv("RUSTUP_HOME", str(empty_home))
    monkeypatch.setattr(RUST.shutil, "which", lambda name: "/usr/bin/rustup" if name == "rustup" else None)
    with pytest.raises(T.ToolGap) as download:
        _find_adapter(RUST.ADAPTERS, "cargo-deny").invoke(
            _context(
                tmp_path / "deny",
                files={**rust_files, "rust-toolchain": "nightly-2099-01-01\n"},
                home=_seeded(tmp_path / "deny-home"),
            )
        )
    assert download.value.reason == "known-gap"


def _seeded(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    _seed_advisory_snapshots(home)
    return home


def _osv_binary() -> str | None:
    found = shutil.which("osv-scanner")
    if found:
        return found
    candidate = Path("/tmp/osv-scanner-2.7.1")
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


@pytest.mark.skipif(shutil.which("cargo-deny") is None or shutil.which("cargo") is None,
                    reason="cargo-deny or cargo is not installed")
def test_offline_smoke_cargo_deny_reports_a_local_advisory(tmp_path: Path) -> None:
    operator = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    if not (operator / "registry").is_dir():
        pytest.skip("operator cargo registry is not warmed")
    home = tmp_path / "home"
    snapshot = home / ".config" / "infiquetra" / "reviews" / "advisories" / "cargo-deny"
    crate = snapshot / "crates" / "itoa"
    crate.mkdir(parents=True)
    (crate / "RUSTSEC-2099-0001.md").write_text(
        "```toml\n"
        "[advisory]\n"
        'id = "RUSTSEC-2099-0001"\n'
        'package = "itoa"\n'
        'date = "2024-01-01"\n'
        'url = "https://example.invalid/itoa"\n'
        'categories = ["code-execution"]\n'
        'keywords = ["test"]\n'
        'cvss = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"\n'
        "\n[versions]\n"
        'patched = [">= 9.9.9"]\n'
        "```\n"
        "# Synthetic itoa advisory\n",
        encoding="utf-8",
    )
    _git(snapshot, "init", "-b", "main")
    _git(snapshot, "config", "user.email", "r6-offline@example.com")
    _git(snapshot, "config", "user.name", "r6-offline")
    _git(snapshot, "add", "-A")
    _git(snapshot, "commit", "-m", "synthetic advisory")
    (snapshot / ".git" / "FETCH_HEAD").write_text("synthetic\n", encoding="utf-8")
    project = {
        "Cargo.toml": (
            '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n\n'
            "[dependencies]\nitoa = \"=1.0.18\"\n"
        ),
        "Cargo.lock": (
            "version = 4\n\n[[package]]\nname = \"demo\"\nversion = \"0.1.0\"\n"
            "dependencies = [\n \"itoa\",\n]\n\n[[package]]\nname = \"itoa\"\n"
            "version = \"1.0.18\"\n"
            'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
            'checksum = "8f42a60cbdf9a97f5d2305f08a87dc4e09308d1276d28c869c684d7777685682"\n'
        ),
        "src/lib.rs": "pub fn demo() -> String { itoa::Buffer::new().format(1).to_owned() }\n",
    }
    context = _context(tmp_path / "scan", files=project, home=home)
    argv = _find_adapter(RUST.ADAPTERS, "cargo-deny").invoke(context)
    env, temps = T._tool_env(home)
    try:
        completed = subprocess.run(
            argv, cwd=context.root, env=env, check=False, capture_output=True, text=True,
        )
    finally:
        for temp in temps:
            shutil.rmtree(temp, ignore_errors=True)
    parsed = RUST._parse_cargo_deny(completed.stderr)
    assert any("RUSTSEC-2099-0001" in hit.advisory_ids for hit in parsed.hits), completed.stderr


@pytest.mark.skipif(_osv_binary() is None, reason="osv-scanner 2.7.1 is not installed")
def test_offline_smoke_osv_scanner_reads_the_native_cache(tmp_path: Path) -> None:
    binary = _osv_binary()
    assert binary is not None
    home = tmp_path / "home"
    zip_dir = (
        home / ".config" / "infiquetra" / "reviews" / "advisories"
        / "osv-scanner" / "osv-scalibr" / "PyPI"
    )
    zip_dir.mkdir(parents=True)
    document = {
        "id": "PYSEC-2099-0001",
        "summary": "synthetic",
        "affected": [{
            "package": {"ecosystem": "PyPI", "name": "requests"},
            "versions": ["2.31.0"],
        }],
        "severity": [{
            "type": "CVSS_V3",
            "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        }],
    }
    blob = tmp_path / "PYSEC-2099-0001.json"
    blob.write_text(json.dumps(document), encoding="utf-8")
    with zipfile.ZipFile(zip_dir / "all.zip", "w") as archive:
        archive.write(blob, "PYSEC-2099-0001.json")
    context = _context(
        tmp_path / "scan",
        files={"requirements.txt": "requests==2.31.0\n"},
        home=home,
    )
    argv = [
        binary if part == "osv-scanner" else part
        for part in _find_adapter(ALL.ADAPTERS, "osv-scanner").invoke(context)
    ]
    completed = subprocess.run(
        argv, cwd=context.root, check=False, capture_output=True, text=True,
    )
    parsed = ALL._parse_osv(completed.stdout)
    assert any("PYSEC-2099-0001" in hit.advisory_ids for hit in parsed.hits), completed.stderr


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_offline_smoke_uv_resolves_from_the_warmed_cache(tmp_path: Path) -> None:
    cache = os.environ.get("UV_CACHE_DIR") or str(Path.home() / ".cache" / "uv")
    if not Path(cache).is_dir():
        pytest.skip("uv cache is not warmed")
    home = tmp_path / "home"
    home.mkdir()
    env, temps = T._tool_env(home)
    try:
        completed = subprocess.run(
            [
                "uv", "run", "--offline", "--no-project",
                "--with", "pytest-randomly==5.0.0",
                "python", "-c",
                "import importlib.metadata as m; print(m.version('pytest-randomly'))",
            ],
            cwd=tmp_path, env=env, check=False, capture_output=True, text=True,
        )
    finally:
        for temp in temps:
            shutil.rmtree(temp, ignore_errors=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "5.0.0"
