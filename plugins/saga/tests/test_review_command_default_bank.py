"""Prepare without --bank uses the shipped per-lens banks (issue 254).

``review_command.py prepare`` defaulted ``--bank`` to
``references/question-bank.json``, which never shipped, so every default
prepare recorded ``jev no-bank`` and asked nothing. The four per-lens banks
under ``references/question-banks/`` are the shipped default, merged the way
the ``/saga:work`` path merges them.

The central test runs the normal CLI main with a deterministic stub of the
existing ``ask`` transport and pins real question IDs from all four lenses,
so loading only one bank fails. Default bank loading itself is never
stubbed there. An explicit ``--bank`` still wins alone, a refused bank
allows no partial inference, and the shipped entrypoint degrades as
``no-key`` when run as a user runs it without ``TYPESAFE_API_KEY``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
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
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = _load("review_command")
T = C.review_tools
R = C.review_records

_LENSES: tuple[str, ...] = (
    "correctness",
    "security",
    "testing",
    "architecture-maintainability",
)

#: Two shipped, python-eligible questions per lens. Any single-bank load misses
#: at least six of these, so this pins the four-way merge without naming all 49.
_PINNED_BY_LENS: dict[str, tuple[str, ...]] = {
    "correctness": (
        "correctness.concurrent-write-without-a-lock",
        "correctness.unvalidated-outside-data",
    ),
    "security": (
        "security.caller-owns-record",
        "security.trusts-client-claims",
    ),
    "testing": (
        "testing.asserts-nothing",
        "testing.shared-state-between-tests",
    ),
    "architecture-maintainability": (
        "architecture-maintainability.comment-lies-about-code",
        "architecture-maintainability.public-surface-grows",
    ),
}

_SYNTHETIC_ID = "correctness.q-changed"

_CREDENTIAL_PREFIXES = (
    "TYPESAFE_", "GH_", "GITHUB_", "INFIQUETRA_", "SAGA_LANGFUSE_", "LANGFUSE_",
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse new connections from this process. The stubbed ask never needs one."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("default-bank tests must make no network call")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-command@example.com")
    _git(repo, "config", "user.name", "review-command")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp: Path) -> tuple[Path, str, str]:
    """A one-function python change, which every per-lens bank can ask about."""
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("def changed():\n    return 2\n", encoding="utf-8")
    return repo, base, _commit(repo, "head")


def _profile(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "profile.json"
    path.write_text(json.dumps({"schema": "repository_profile.v1"}) + "\n", encoding="utf-8")
    return path


def _builder(path: Path) -> Path:
    path.write_text(json.dumps({
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": "U1",
        "acceptance_criteria": [
            {"id": "AC-1", "text": "The changed line is the one the stub reports.",
             "checks": ["line"]},
        ],
        "declarations": [],
        "reasons": [],
    }), encoding="utf-8")
    return path


class _Runner:
    """Runs git for real and returns a fixed scan for the stub tool. Never a shell."""

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        assert shell is False
        if Path(argv[0]).name == "git":
            proc = subprocess.run(
                argv, cwd=cwd, env=env, capture_output=True, text=True, check=False,
                timeout=timeout,
            )
            return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
        if "--version" in argv:
            return T.ProcessResult(0, "1.0.0\n")
        return T.ProcessResult(0, "scan\n")


def _adapter() -> Any:
    def invoke(_context: Any) -> list[str]:
        return ["stub", "scan"]

    def parse(_text: str) -> Any:
        return T.ParseResult((T.Hit(
            rule_id="example", path="src/app.py", statement="A stub reported this.",
            anchor="example", start=2, end=2, row="security.scanner-high",
        ),))

    return T.Adapter(
        id="stub", tool="stub", invoke=invoke, parse=parse, default_version="1.0.0",
        rows=("security.scanner-high",), lens="security", comparison="lines",
    )


def _ask() -> Any:
    """The existing ask seam, stubbed deterministically: every question reads 0.91."""

    def ask(_state: Any, questions: Any, **_kwargs: Any) -> Any:
        answers = {key: {"type": "noul", "noul": 0.91} for key in questions}
        return SimpleNamespace(
            status="ok", ok=True, model="jev-test", latency_ms=5, note="",
            usage={"input_tokens": 12, "output_tokens": 4}, answers=answers,
        )

    return ask


def _main(argv: list[str], **kwargs: Any) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        code = C.main(argv, **kwargs)
    return code, buffer.getvalue()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare(
    repo: Path, base: str, head: str, profile: Path, builder: Path, out: Path, home: Path,
    runner: _Runner, *, ask: Any = None, bank: Path | None = None,
) -> tuple[int, str]:
    argv = [
        "prepare", "--repo", str(repo), "--base", base, "--head", head, "--profile",
        str(profile), "--builder-record", str(builder), "--out", str(out), "--home",
        str(home),
    ]
    if bank is not None:
        argv.extend(["--bank", str(bank)])
    return _main(argv, adapters=[_adapter()], runner=runner, ask=ask)


def test_prepare_without_bank_merges_all_four_shipped_banks(tmp_path: Path) -> None:
    """The default prepare asks Jev with the shipped per-lens banks.

    No ``--bank`` is passed and default bank loading is not stubbed: the
    production path must find the four approved banks itself. Only the model
    transport is stubbed, deterministically.
    """
    repo, base, head = _repo(tmp_path)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    first, second = tmp_path / "packet", tmp_path / "again"
    for out in (first, second):
        code, err = _prepare(
            repo, base, head, profile, builder, out, home, _Runner(), ask=_ask(),
        )
        assert code == 0, err
    degraded = _read(first / "degraded.json")
    assert not any(entry.get("reason") == "no-bank" for entry in degraded), (
        "prepare without --bank recorded no-bank instead of loading the shipped banks: "
        f"{degraded}"
    )
    where = _read(first / "where-to-look.json")
    lenses = {item["lens"] for item in where}
    assert lenses == set(_LENSES), (
        f"expected one Jev item per shipped lens, got lenses {sorted(lenses)}"
    )
    assert all(item.get("classifier", {}).get("name") == "jev" for item in where), (
        f"every default where-to-look item is a Jev item, got {where}"
    )
    found: dict[str, set[str]] = {}
    for item in where:
        found.setdefault(item["lens"], set()).update(
            question["id"] for question in item["questions"]
        )
    for lens, pinned in _PINNED_BY_LENS.items():
        missing = [qid for qid in pinned if qid not in found.get(lens, set())]
        assert not missing, f"lens {lens} is missing shipped questions {missing}"
    assert (second / "where-to-look.json").read_bytes() == (
        first / "where-to-look.json"
    ).read_bytes()
    assert (second / "grades.json").read_bytes() == (first / "grades.json").read_bytes()


def test_explicit_bank_still_overrides_the_shipped_default(tmp_path: Path) -> None:
    """An explicit --bank keeps working alone after the default is fixed."""
    repo, base, head = _repo(tmp_path)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    bank = tmp_path / "bank.json"
    bank.write_text(json.dumps({
        "schema": "question_bank.v1",
        "questions": [{
            "id": _SYNTHETIC_ID,
            "lens": "correctness",
            "kind": "yes-no",
            "options": [
                {"id": "yes", "definition": "The change breaks the named behaviour."},
                {"id": "no", "definition": "The change keeps that behaviour."},
            ],
            "piece": "function",
        }],
    }), encoding="utf-8")
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), ask=_ask(), bank=bank,
    )
    assert code == 0, err
    where = _read(out / "where-to-look.json")
    found = {question["id"] for item in where for question in item["questions"]}
    assert found == {_SYNTHETIC_ID}, f"the explicit bank should win alone, got {found}"
    assert _read(out / "degraded.json") == []


def test_refused_default_bank_allows_no_partial_jev_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused shipped bank degrades the sweep instead of inferring from the rest."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import question_banks as QB

    refusal_reason = "security: simulated refusal for the no-partial test"
    real_load_bank = QB.load_bank

    def _refuse_security(lens: str, root: Any = None) -> Any:
        if lens == "security":
            raise QB.BankRefusal(refusal_reason)
        return real_load_bank(lens, root)

    monkeypatch.setattr(QB, "load_bank", _refuse_security)
    calls: list[Any] = []
    inner_ask = _ask()

    def _counting_ask(state: Any, questions: Any, **kwargs: Any) -> Any:
        calls.append(questions)
        return inner_ask(state, questions, **kwargs)

    repo, base, head = _repo(tmp_path)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    code, err = _prepare(
        repo, base, head, profile, builder, out, home, _Runner(), ask=_counting_ask,
    )
    assert code == 0, err
    where = _read(out / "where-to-look.json")
    jev_items = [
        item for item in where if item.get("classifier", {}).get("name") == "jev"
    ]
    assert jev_items == [], f"a refused bank must not allow partial inference: {jev_items}"
    degraded = _read(out / "degraded.json")
    assert any(refusal_reason in str(entry.get("reason")) for entry in degraded), (
        "a refused bank must surface its refusal instead of the old no-bank branch: "
        f"{degraded}"
    )
    assert calls == [], (
        f"a refused bank must prevent inference, but ask ran {len(calls)} time(s)"
    )


def test_prepare_executable_without_key_degrades_as_no_key(tmp_path: Path) -> None:
    """The shipped entrypoint, run as a user runs it, degrades without a key.

    No ``TYPESAFE_API_KEY`` is provided and no request is attempted: prepare
    exits 0 with a jev no-key degraded entry, not no-bank and not a traceback.
    """
    repo, base, head = _repo(tmp_path)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(key.startswith(prefix) for prefix in _CREDENTIAL_PREFIXES)
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    assert "TYPESAFE_API_KEY" not in env
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "review_command.py"), "prepare",
         "--repo", str(repo), "--base", base, "--head", head, "--profile", str(profile),
         "--builder-record", str(builder), "--out", str(out), "--home", str(home)],
        capture_output=True, text=True, env=env, timeout=180, cwd=tmp_path,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "Traceback" not in completed.stderr, completed.stderr
    degraded = _read(out / "degraded.json")
    assert not any(entry.get("reason") == "no-bank" for entry in degraded), (
        f"the executable still records no-bank instead of loading the shipped banks: "
        f"{degraded}"
    )
    assert any(
        entry.get("tool") == "jev" and entry.get("reason") == "no-key"
        for entry in degraded
    ), f"expected a jev no-key degraded entry without TYPESAFE_API_KEY, got {degraded}"
    where = _read(out / "where-to-look.json")
    assert all(
        item.get("classifier", {}).get("name") != "jev" for item in where
    ), f"a no-key run must not emit Jev items, got {where}"
