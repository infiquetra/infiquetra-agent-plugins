"""Default-bank Jev cache reuse and missing-key degradation (issue 254).

Cache/no-key checks exercise the ordinary ``prepare`` path with no
``--bank`` flag. They use the actual approved shipped banks via
their loader (approval is never weakened), the real
``typesafe_client``/``jev_sweep`` cache layer with a stubbed ``urlopen``
transport, and an isolated temp ``HOME``/cache per test. No live API calls.

Changed-input cache miss (a changed state or question must not reuse an
unrelated answer) is already covered at the cache layer by
``plugins/fleet-core/tests/test_jev_log.py`` (``test_a_changed_state_misses``,
``test_a_changed_question_misses``), so this file does not duplicate it.
It covers what that layer cannot: repeat ``prepare`` reuse, cold no-key
miss, and warm replay without a key through ``review_command``.

Spending behavior is preserved: the stub returns priced usage
(``input_tokens``/``output_tokens``) far under the sweep spend cap, so the
first prepare is fully warm. Stable packets are asserted only for fully
warm coverage with frozen inputs; a cold spend-capped or unpriced prepare
may legitimately expand on replay because cached calls cost zero.
"""

from __future__ import annotations

import importlib.util
import io
import json
import socket
import subprocess
import sys
import urllib.request
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> Any:
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
F = C.review_formula
QB = _load("question_banks")
BUNDLED = _load("bundled_fleet")
SWEEP = BUNDLED.load("jev_sweep")
REAL_CLIENT = SWEEP.typesafe_client
JEV_LOG = SWEEP.jev_log


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse real connections. The tests inject a stubbed transport only."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("default-cache tests must make no network call")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "default-cache@example.com")
    _git(repo, "config", "user.name", "default-cache")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp: Path) -> tuple[Path, str, str]:
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
    path.write_text(
        json.dumps(
            {
                "kind": "builder_record",
                "schema": R.SCHEMA,
                "unit": "U1",
                "acceptance_criteria": [
                    {
                        "id": "AC-1",
                        "text": "The changed line is the one the stub reports.",
                        "checks": ["line"],
                    }
                ],
                "declarations": [],
                "reasons": [],
            }
        ),
        encoding="utf-8",
    )
    return path


class _Runner:
    """Runs git for real and returns a fixed scan for the stub tool."""

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False
        if Path(argv[0]).name == "git":
            proc = subprocess.run(
                argv, cwd=cwd, env=env, capture_output=True, text=True,
                check=False, timeout=timeout,
            )
            return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
        if "--version" in argv:
            return T.ProcessResult(0, "1.0.0\n")
        return T.ProcessResult(0, "scan\n")


def _adapter(*, start: int = 2) -> Any:
    def invoke(_context: Any) -> list[str]:
        return ["stub", "scan"]

    def parse(_text: str) -> Any:
        return T.ParseResult(
            (
                T.Hit(
                    rule_id="example",
                    path="src/app.py",
                    statement="A stub reported this.",
                    anchor="example",
                    start=start,
                    end=start,
                    row="security.scanner-high",
                ),
            )
        )

    return T.Adapter(
        id="stub",
        tool="stub",
        invoke=invoke,
        parse=parse,
        default_version="1.0.0",
        rows=("security.scanner-high",),
        lens="security",
        comparison="lines",
    )


def _main(argv: list[str], **kwargs: Any) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        code = C.main(argv, **kwargs)
    return code, buffer.getvalue()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare_default(
    repo: Path,
    base: str,
    head: str,
    profile: Path,
    builder: Path,
    out: Path,
    home: Path,
    runner: _Runner,
    *,
    ask: Any,
) -> tuple[int, str]:
    argv = [
        "prepare",
        "--repo", str(repo),
        "--base", base,
        "--head", head,
        "--profile", str(profile),
        "--builder-record", str(builder),
        "--out", str(out),
        "--home", str(home),
    ]
    return _main(argv, adapters=[_adapter(start=2)], runner=runner, ask=ask)


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


class _CountingTransport:
    """Stubbed external transport. Counts provider requests, never the network."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: Any, timeout: float | None = None) -> _FakeResponse:
        del timeout
        self.calls += 1
        raw = getattr(request, "data", None)
        if raw is None:
            try:
                raw = request.get_data()
            except Exception:
                raw = b"{}"
        try:
            body = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else "{}")
        except Exception:
            body = {}
        questions = body.get("questions") if isinstance(body, dict) else None
        if not isinstance(questions, dict):
            questions = {}
        answers: dict[str, Any] = {}
        for key, spec in questions.items():
            kind = spec.get("type") if isinstance(spec, dict) else None
            if kind == "choice":
                criteria = spec.get("criteria") if isinstance(spec, dict) else None
                first = next(iter(criteria), "yes") if isinstance(criteria, dict) else "yes"
                answers[key] = {"type": "choice", "choice": first, "confidence": 0.91}
            else:
                answers[key] = {"type": "noul", "noul": 0.91}
        payload = json.dumps(
            {
                "answers": answers,
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 100, "output_tokens": 10},
            }
        ).encode("utf-8")
        return _FakeResponse(payload)


def _getenv_with_key(name: str) -> str | None:
    if name == REAL_CLIENT.KEY_ENV:
        return "test-inert-key"
    if name == REAL_CLIENT.TRANSPORT_ENV:
        return REAL_CLIENT.TRANSPORT_URLLIB
    return None


def _getenv_without_key(name: str) -> str | None:
    if name == REAL_CLIENT.TRANSPORT_ENV:
        return REAL_CLIENT.TRANSPORT_URLLIB
    return None


def _real_ask(transport: _CountingTransport, getenv: Any) -> Any:
    """The real client/cache layer with a stubbed transport. Forwards cache_dir."""

    def ask(state: Any, questions: Any, **kwargs: Any) -> Any:
        return REAL_CLIENT.ask(
            state,
            questions,
            model=kwargs.get("model") or "jev-latest",
            transport=REAL_CLIENT.TRANSPORT_URLLIB,
            urlopen=transport,
            getenv=getenv,
            cache_dir=kwargs.get("cache_dir"),
        )

    return ask


def _shipped_question_ids() -> set[str]:
    """Question ids from the approved shipped banks. Load verifies approval."""
    found: set[str] = set()
    for lens in QB.LENSES:
        bank = QB.load_bank(lens, REPO_ROOT)
        for question in bank["questions"]:
            found.add(str(question["id"]))
    assert found, "shipped banks must carry questions"
    return found


def _assert_substantive_where(where: Any, shipped: set[str]) -> None:
    assert isinstance(where, list) and where, (
        "expected substantive where-to-look from the shipped banks"
    )
    for item in where:
        assert isinstance(item, dict)
        assert item.get("classifier", {}).get("name") == "jev"
        assert item.get("lens") in F.LENSES
        questions = item.get("questions") or []
        assert questions, "each where-to-look item must name questions"
        for entry in questions:
            assert entry.get("id") in shipped
            probability = entry.get("probability")
            assert isinstance(probability, (int, float))
            assert 0.0 <= float(probability) <= 1.0
            assert float(probability) > 0.5


def _assert_valid_packet(packet: Path) -> None:
    assert (packet / "where-to-look.json").is_file()
    assert (packet / "degraded.json").is_file()
    assert (packet / "grades.json").is_file()
    degraded = _read(packet / "degraded.json")
    assert isinstance(degraded, list)
    for entry in degraded:
        assert {"lens", "language", "input", "tool", "reason"} <= set(entry)
        assert entry["lens"] in F.LENSES
        assert entry["language"] in F.LANGUAGES
    expected = F.compute(
        {
            "findings": _read(packet / "findings.json"),
            "measurements": _read(packet / "measurements.json"),
            "builder_records": [_read(packet / "builder-record.json")],
            "may_block": {
                str(lens): {
                    str(language): bool(record.get("blocks"))
                    if isinstance(record, dict)
                    else False
                    for language, record in languages.items()
                }
                for lens, languages in _read(packet / "may-block.json").items()
            },
            "degraded_inputs": degraded,
        }
    )
    assert _read(packet / "grades.json") == expected


def _isolate_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("INFIQUETRA_TYPESAFE_LOG_DIR", str(home / "typesafe-log"))
    monkeypatch.delenv(REAL_CLIENT.KEY_ENV, raising=False)


def test_repeat_prepare_reuses_cached_answers_without_another_transport_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second identical prepare reuses Jev answers with no new transport call."""
    repo, base, head = _repo(tmp_path)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    _isolate_home(monkeypatch, home)
    shipped = _shipped_question_ids()
    transport = _CountingTransport()
    ask = _real_ask(transport, _getenv_with_key)

    first = tmp_path / "packet-one"
    code, err = _prepare_default(
        repo, base, head, profile, builder, first, home, _Runner(), ask=ask
    )
    assert code == 0, err
    degraded = _read(first / "degraded.json")
    assert not any(entry.get("reason") == "no-bank" for entry in degraded), degraded
    where = _read(first / "where-to-look.json")
    _assert_substantive_where(where, shipped)
    assert transport.calls > 0, "the first prepare must make provider requests"
    first_calls = transport.calls
    cache_file = home / ".saga" / "review-sweep" / head / JEV_LOG.CACHE_FILENAME
    assert cache_file.is_file(), "the real cache must record the answers"
    _assert_valid_packet(first)

    second = tmp_path / "packet-two"
    code, err = _prepare_default(
        repo, base, head, profile, builder, second, home, _Runner(), ask=ask
    )
    assert code == 0, err
    assert transport.calls == first_calls, (
        f"the second identical prepare must reuse the cache "
        f"({first_calls} -> {transport.calls} transport calls)"
    )
    again = _read(second / "where-to-look.json")
    _assert_substantive_where(again, shipped)
    assert again == where, "fully warm coverage with frozen inputs must keep the packet stable"
    assert _read(second / "degraded.json") == degraded
    _assert_valid_packet(second)


def test_cold_prepare_without_key_reports_no_key_without_a_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cold miss with no key: explicit no-key, valid degraded packet, zero requests."""
    repo, base, head = _repo(tmp_path)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    _isolate_home(monkeypatch, home)
    transport = _CountingTransport()
    ask = _real_ask(transport, _getenv_without_key)

    out = tmp_path / "packet"
    code, err = _prepare_default(
        repo, base, head, profile, builder, out, home, _Runner(), ask=ask
    )
    assert code == 0, err
    assert transport.calls == 0, "a cold miss with no key must not reach the provider"
    degraded = _read(out / "degraded.json")
    assert not any(entry.get("reason") == "no-bank" for entry in degraded), degraded
    keyed = [
        entry
        for entry in degraded
        if entry.get("tool") == "jev" and "key" in str(entry.get("reason") or "").lower()
    ]
    assert keyed, f"missing key must degrade explicitly as missing key: {degraded}"
    assert _read(out / "where-to-look.json") == []
    _assert_valid_packet(out)


def test_warm_cache_replays_without_key_with_usable_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Complete warm cache replays without a key: usable answers, zero requests."""
    repo, base, head = _repo(tmp_path)
    profile = _profile(tmp_path / "outside")
    builder = _builder(tmp_path / "builder.json")
    home = tmp_path / "home"
    _isolate_home(monkeypatch, home)
    shipped = _shipped_question_ids()
    transport = _CountingTransport()

    warm = tmp_path / "packet-warm"
    code, err = _prepare_default(
        repo, base, head, profile, builder, warm, home, _Runner(),
        ask=_real_ask(transport, _getenv_with_key),
    )
    assert code == 0, err
    where = _read(warm / "where-to-look.json")
    _assert_substantive_where(where, shipped)
    assert transport.calls > 0
    warmed_calls = transport.calls

    replay = tmp_path / "packet-replay"
    code, err = _prepare_default(
        repo, base, head, profile, builder, replay, home, _Runner(),
        ask=_real_ask(transport, _getenv_without_key),
    )
    assert code == 0, err
    assert transport.calls == warmed_calls, (
        "a complete warm cache must replay without a provider request"
    )
    again = _read(replay / "where-to-look.json")
    _assert_substantive_where(again, shipped)
    assert again == where, "fully warm replay with frozen inputs must keep the packet stable"
    degraded = _read(replay / "degraded.json")
    assert not any(entry.get("reason") == "no-bank" for entry in degraded), degraded
    _assert_valid_packet(replay)
