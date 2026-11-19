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
import socket
import subprocess
import sys
import urllib.request
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

    # 2. When the local advisory snapshot is seeded, cargo-deny must pass --disable-fetch.
    seeded_home = tmp_path / "seeded-home"
    _seed_advisory_snapshots(seeded_home)
    seeded_ctx = _context(tmp_path / "present", files=rust_files, home=seeded_home)
    argv = adapter.invoke(seeded_ctx)
    assert argv, "expected non-empty cargo-deny argv when snapshot is present"
    assert "--disable-fetch" in argv, f"cargo-deny must pass --disable-fetch: {argv!r}"


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
    assert any(flag.startswith("--offline") for flag in argv), (
        f"osv-scanner must pass --offline / --offline-vulnerabilities: {argv!r}"
    )


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
    argv = adapter.invoke(seeded_ctx)
    assert argv, "expected non-empty pip-audit argv when snapshot is present"
    assert (
        "--disable-pip" in argv
        or "--no-deps" in argv
        or "--offline" in argv
        or any("advisories" in part for part in argv)
    ), f"pip-audit invocation must be offline / local-snapshot backed: {argv!r}"


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
    argv = adapter.invoke(seeded_ctx)
    assert argv, "expected non-empty npm-audit argv when snapshot is present"
    assert argv != ["npm", "audit", "--json"], (
        "npm-audit must use the local advisory snapshot or --offline, never bare `npm audit --json`"
    )


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
            assert "--disable-fetch" in argv, f"cargo-deny called without --disable-fetch: {argv!r}"
            return T.ProcessResult(0, '{"type":"summary","fields":{"advisories":0}}\n', "")
        if prog in {"cargo", "cargo-clippy"}:
            assert "--offline" in argv or "--frozen" in argv, (
                f"{prog} called without --offline/--frozen: {argv!r}"
            )
            assert env.get("CARGO_NET_OFFLINE") == "true"
            return T.ProcessResult(0, '{"reason":"build-finished","success":true}\n', "")
        if prog == "osv-scanner":
            assert any(flag.startswith("--offline") for flag in argv), (
                f"osv-scanner called without --offline: {argv!r}"
            )
            return T.ProcessResult(0, '{"results":[]}\n', "")
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
