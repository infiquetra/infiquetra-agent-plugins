"""The sweep classifies pieces it is given (issue 156). No test reaches the network."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons/jev_sweep.py"
RATE_KEYS = (
    "uncached_input",
    "cache_read",
    "cache_write_5m",
    "cache_write_1h",
    "output",
)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("jev_sweep_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["jev_sweep_under_test"] = module
    spec.loader.exec_module(module)
    return module


sweep_mod = _load()


class _Result:
    def __init__(
        self,
        answers: dict[str, Any] | None = None,
        *,
        status: str = "ok",
        model: str = "jev-1.13.0",
        usage: dict[str, int] | None = None,
        note: str = "",
        latency_ms: int = 5,
        transport: str = "urllib",
    ) -> None:
        self.status = status
        self.answers = answers or {}
        self.model = model
        self.usage = {"input_tokens": 10, "output_tokens": 1} if usage is None else usage
        self.note = note
        self.latency_ms = latency_ms
        self.transport = transport


def _rate(**overrides: float) -> dict[str, float]:
    rate = {key: 0.0 for key in RATE_KEYS}
    rate.update(overrides)
    return rate


def _yes_no(qid: str, *, lens: str = "security", piece: str = "function", when: dict | None = None):
    question: dict[str, Any] = {
        "id": qid,
        "lens": lens,
        "kind": "yes-no",
        "options": [
            {"id": "yes", "definition": "yes"},
            {"id": "no", "definition": "no"},
        ],
        "piece": piece,
    }
    if when is not None:
        question["when"] = when
    return question


def _bank(*questions: dict[str, Any]) -> dict[str, Any]:
    return {"schema": "question_bank.v1", "questions": list(questions)}


def _piece(
    path: str = "a.py",
    *,
    kind: str = "function",
    text: str = "def f():\n    return 1\n",
    qid: str | None = None,
    start: int = 1,
    end: int = 2,
) -> dict[str, Any]:
    piece: dict[str, Any] = {
        "id": f"{path}:{start}-{end}",
        "path": path,
        "language": "python",
        "kind": kind,
        "text": text,
        "degraded": False,
        "location": {
            "scope": "lines",
            "file": path,
            "lines": {"start": start, "end": end},
            "function": "f",
            "anchor": "def f():",
        },
    }
    if qid:
        piece["only_question"] = qid
        piece["id"] = f"{piece['id']}:{qid}"
    return piece


def _run(tmp_path: Path, bank: dict, pieces: list, thresholds: dict, rate: dict, ask, **kwargs):
    return sweep_mod.sweep(
        bank, pieces, thresholds, rate,
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "log",
        ask=ask,
        **kwargs,
    )


def _verdicts(tmp_path: Path) -> list[dict[str, Any]]:
    records, _skipped = sweep_mod.jev_log.read_verdicts(tmp_path / "log")
    return records


def test_choice_is_asked_in_both_orders_and_averaged(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def ask(_state, questions, **_kwargs):
        calls.append(questions)
        answers = {}
        for key, spec in questions.items():
            first = next(iter(spec["criteria"]))
            if first == "leak":
                answers[key] = {
                    "type": "choice", "choice": "leak", "confidence": 0.8,
                    "probabilities": {"leak": 0.8, "clean": 0.2},
                }
            else:
                answers[key] = {
                    "type": "choice", "choice": "clean", "confidence": 0.6,
                    "probabilities": {"leak": 0.4, "clean": 0.6},
                }
        return _Result(answers)

    question = {
        "id": "leak",
        "lens": "security",
        "kind": "choice",
        "options": [
            {"id": "leak", "definition": "a secret leaves"},
            {"id": "clean", "definition": "nothing leaves"},
        ],
        "piece": "function",
    }
    result = _run(tmp_path, _bank(question), [_piece()], {}, _rate(), ask)
    assert len(calls) == 1
    entries = list(calls[0].values())
    assert [entry["type"] for entry in entries] == ["choice", "choice"]
    assert list(entries[1]["criteria"]) == list(reversed(entries[0]["criteria"]))
    assert result["items"][0]["questions"][0]["probability"] == 0.6
    assert "answer" not in result["items"][0]


def test_yes_no_is_asked_once(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def ask(_state, questions, **_kwargs):
        calls.append(questions)
        return _Result({key: {"type": "noul", "noul": 0.75} for key in questions})

    result = _run(tmp_path, _bank(_yes_no("leak")), [_piece()], {}, _rate(), ask)
    assert len(calls) == 1
    assert list(calls[0].values()) == [{"type": "noul", "instructions": calls[0]["n0"]["instructions"]}]
    assert len(calls[0]) == 1
    assert calls[0]["n0"]["type"] == "noul"
    assert result["items"][0]["questions"][0]["probability"] == 0.75


def test_a_threshold_keeps_a_question_below_it_off(tmp_path: Path) -> None:
    def ask_at(probability: float):
        def ask(_state, questions, **_kwargs):
            return _Result({key: {"type": "noul", "noul": probability} for key in questions})
        return ask

    below = _run(
        tmp_path, _bank(_yes_no("leak")), [_piece()], {"leak": 0.8}, _rate(), ask_at(0.79),
    )
    assert below["items"] == []
    assert below["degraded"] == []
    assert len(_verdicts(tmp_path)) == 1

    above = _run(
        tmp_path / "above", _bank(_yes_no("leak")), [_piece()], {"leak": 0.8}, _rate(),
        ask_at(0.8),
    )
    assert above["items"][0]["questions"][0]["probability"] == 0.8


def test_without_thresholds_the_thirty_most_likely_return(tmp_path: Path) -> None:
    result = _ranked(tmp_path, {})
    assert len(result["items"]) == 30
    probabilities = [item["questions"][0]["probability"] for item in result["items"]]
    assert 0.01 not in probabilities
    assert {entry["reason"] for entry in result["degraded"]} == {"cap"}
    assert len(result["degraded"]) == 1


def test_thirty_one_hits_return_thirty_highest_first(tmp_path: Path) -> None:
    result = _ranked(tmp_path, {"leak": 0})
    probabilities = [item["questions"][0]["probability"] for item in result["items"]]
    assert probabilities == [index / 100 for index in range(31, 1, -1)]
    assert result["degraded"][0]["reason"] == "cap"
    assert result["degraded"][0]["piece"].startswith("p01.py")


def _ranked(tmp_path: Path, thresholds: dict) -> dict[str, Any]:
    pieces = [_piece(f"p{number:02d}.py") for number in range(1, 32)]

    def ask(state, questions, **_kwargs):
        number = int(state["path"][1:3]) / 100
        return _Result({key: {"type": "noul", "noul": number} for key in questions})

    return _run(tmp_path, _bank(_yes_no("leak")), pieces, thresholds, _rate(), ask)


def test_the_dollar_cap_stops_before_the_next_request(tmp_path: Path) -> None:
    calls: list[str] = []

    def ask(state, questions, **_kwargs):
        calls.append(state["path"])
        return _Result(
            {key: {"type": "noul", "noul": 0.9} for key in questions},
            usage={"input_tokens": 1_000_000, "output_tokens": 0},
        )

    result = _run(
        tmp_path, _bank(_yes_no("leak")), [_piece("a.py"), _piece("b.py")], {},
        _rate(uncached_input=1.0), ask,
    )
    assert calls == ["a.py"]
    assert [item["location"]["file"] for item in result["items"]] == ["a.py"]
    assert result["degraded"] == [{"reason": "spend", "piece": "b.py:1-2", "question": "leak"}]


def test_missing_usage_stops_the_sweep(tmp_path: Path) -> None:
    calls: list[str] = []

    def ask(state, questions, **_kwargs):
        calls.append(state["path"])
        return _Result(
            {key: {"type": "noul", "noul": 0.9} for key in questions},
            usage={"output_tokens": 4},
        )

    result = _run(
        tmp_path, _bank(_yes_no("leak")), [_piece("a.py"), _piece("b.py")], {}, _rate(), ask,
    )
    assert calls == ["a.py"]
    assert result["items"][0]["location"]["file"] == "a.py"
    assert result["degraded"][0]["reason"] == "spend"
    assert result["degraded"][0]["piece"] == "b.py:1-2"


def test_a_question_missing_from_a_threshold_map_still_fires(tmp_path: Path) -> None:
    def ask(_state, questions, **_kwargs):
        answers = {}
        for key, spec in questions.items():
            qid = spec["instructions"].split("\n", 1)[0]
            probability = 0.5 if qid == "gated" else 0.1
            answers[key] = {"type": "noul", "noul": probability}
        return _Result(answers)

    result = _run(
        tmp_path, _bank(_yes_no("gated"), _yes_no("open")), [_piece()], {"gated": 0.8}, _rate(),
        ask,
    )
    fired = [question["id"] for item in result["items"] for question in item["questions"]]
    assert fired == ["open"]
    assert all(entry.get("question") != "gated" for entry in result["degraded"])


def test_a_repeat_sweep_answers_from_the_cache(tmp_path: Path) -> None:
    calls: list[int] = []

    class _Response:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    def urlopen(request, timeout=None):  # noqa: ANN001
        del timeout
        calls.append(1)
        body = json.loads(request.data)
        assert body["model"] == "jev-latest"
        answers = {key: {"type": "noul", "noul": 0.66} for key in body["questions"]}
        payload = {
            "answers": answers,
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 12, "output_tokens": 3},
        }
        return _Response(json.dumps(payload).encode())

    def getenv(name: str) -> str | None:
        if name == "TYPESAFE_API_KEY":
            return "dummy-not-a-token"
        if name == "TYPESAFE_BASE_URL":
            return "http://127.0.0.1:9"
        return None

    kwargs = {
        "cache_dir": tmp_path / "cache",
        "log_dir": tmp_path / "log",
        "urlopen": urlopen,
        "getenv": getenv,
    }
    bank = _bank(_yes_no("leak"))
    first = sweep_mod.sweep(bank, [_piece()], {}, _rate(), **kwargs)
    second = sweep_mod.sweep(bank, [_piece()], {}, _rate(), **kwargs)
    assert calls == [1]
    assert first["items"] == second["items"]
    assert first["items"][0]["classifier"]["model"] == "jev-1.13.0"


def test_a_switch_keeps_a_question_off_a_piece_it_does_not_match(tmp_path: Path) -> None:
    def ask(*_args, **_kwargs):
        raise AssertionError("a rust-only question must not be sent about python")

    question = _yes_no("leak", when={"languages": ["rust"]})
    result = _run(tmp_path, _bank(question), [_piece()], {}, _rate(), ask)
    assert result["items"] == []
    assert result["failed"] is False


def test_a_path_star_does_not_cross_a_slash(tmp_path: Path) -> None:
    seen: list[str] = []

    def ask(state, questions, **_kwargs):
        seen.append(state["path"])
        return _Result({key: {"type": "noul", "noul": 0.9} for key in questions})

    question = _yes_no("leak", when={"paths": ["src/*.py"]})
    pieces = [_piece("src/a/b.py"), _piece("src/a.py")]
    _run(tmp_path, _bank(question), pieces, {}, _rate(), ask)
    assert seen == ["src/a.py"]


def test_a_failing_classifier_returns_no_items(tmp_path: Path) -> None:
    def ask(state, questions, **_kwargs):
        if state["path"] == "b.py":
            return _Result(status="error", note="boom", usage={})
        return _Result({key: {"type": "noul", "noul": 0.9} for key in questions})

    result = _run(
        tmp_path, _bank(_yes_no("leak")), [_piece("a.py"), _piece("b.py")], {}, _rate(), ask,
    )
    assert result["items"] == []
    assert result["failed"] is True
    assert result["degraded"] == [{"reason": "classifier"}]
    assert _verdicts(tmp_path) == []


def test_a_missing_key_is_its_own_reason(tmp_path: Path) -> None:
    note = f"{sweep_mod.typesafe_client.KEY_ENV} is not set in the environment; no request was attempted"

    def ask(_state, _questions, **_kwargs):
        return _Result(status="error", note=note, usage={})

    result = _run(tmp_path, _bank(_yes_no("leak")), [_piece()], {}, _rate(), ask)
    assert result["items"] == []
    assert result["failed"] is True
    assert result["degraded"] == [{"reason": "no-key"}]
    assert _verdicts(tmp_path) == []


def test_a_secret_in_a_piece_never_reaches_the_request_body(tmp_path: Path) -> None:
    token = "ghp_" + ("X" * 36)
    secret = "example-secret-value"
    captured: list[bytes] = []

    class _Response:
        def read(self) -> bytes:
            payload = {
                "answers": {"n0": {"type": "noul", "noul": 0.2}},
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 8, "output_tokens": 1},
            }
            return json.dumps(payload).encode()

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    def urlopen(request, timeout=None):  # noqa: ANN001
        del timeout
        captured.append(request.data)
        return _Response()

    def getenv(name: str) -> str | None:
        if name == "TYPESAFE_API_KEY":
            return "dummy-not-a-token"
        if name == "TYPESAFE_BASE_URL":
            return "http://127.0.0.1:9"
        return None

    piece = _piece(text=f'api_key = "{secret}"\n{token}\n')
    sweep_mod.sweep(
        _bank(_yes_no("leak")), [piece], {}, _rate(),
        cache_dir=tmp_path / "cache", log_dir=tmp_path / "log",
        urlopen=urlopen, getenv=getenv,
    )
    assert captured
    body = captured[0].decode()
    assert "[REDACTED]" in body
    assert secret not in body
    assert token not in body


def test_each_item_and_each_verdict_carries_the_resolved_model(tmp_path: Path) -> None:
    seen: list[str] = []

    def ask(_state, questions, **kwargs):
        seen.append(kwargs["model"])
        answers = {}
        for key, spec in questions.items():
            qid = spec["instructions"].split("\n", 1)[0]
            probability = 0.9 if qid == "fires" else 0.2
            answers[key] = {"type": "noul", "noul": probability}
        return _Result(answers, model="jev-1.13.0", latency_ms=42)

    result = _run(
        tmp_path,
        _bank(_yes_no("fires"), _yes_no("quiet")),
        [_piece()],
        {"fires": 0.5, "quiet": 0.8},
        _rate(),
        ask,
    )
    assert seen == ["jev-latest"]
    assert len(result["items"]) == 1
    assert result["items"][0]["classifier"] == {"name": "jev", "model": "jev-1.13.0"}
    verdicts = _verdicts(tmp_path)
    assert len(verdicts) == 2
    assert {record["resolved_model"] for record in verdicts} == {"jev-1.13.0"}
    assert "spend" in result and "seconds" in result


def test_over_budget_questions_split_by_lens_and_a_lens_that_still_does_not_fit_is_unasked(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def ask(_state, questions, **_kwargs):
        calls.append(questions)
        return _Result({key: {"type": "noul", "noul": 0.9} for key in questions})

    short = _yes_no("short", lens="correctness")
    fat = []
    for index in range(12):
        question = _yes_no(f"fat-{index}", lens="security")
        question["options"] = [
            {"id": "yes", "definition": "y" * 15000},
            {"id": "no", "definition": "n"},
        ]
        fat.append(question)
    piece = _piece(text="x" * 90000)
    result = _run(tmp_path, _bank(short, *fat), [piece], {}, _rate(), ask)
    assert len(calls) == 1
    sent = json.dumps(calls)
    assert "short" in sent
    assert "fat-0" not in sent
    reasons = [entry for entry in result["degraded"] if entry["reason"] == "budget"]
    assert {entry["question"] for entry in reasons} == {f"fat-{index}" for index in range(12)}


def test_only_question_limits_which_piece_is_asked(tmp_path: Path) -> None:
    seen: list[str] = []

    def ask(state, _questions, **_kwargs):
        seen.append(state["path"])
        return _Result({"n0": {"type": "noul", "noul": 0.9}})

    pieces = [_piece("full.py"), _piece("clip.py", qid="leak")]
    _run(tmp_path, _bank(_yes_no("leak")), pieces, {}, _rate(), ask)
    assert seen == ["clip.py"]


def test_the_module_imports_the_standard_library_only() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    siblings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_load_sibling":
            siblings.add(ast.literal_eval(node.args[0]))
    assert siblings <= {"typesafe_client", "jev_log"}
    assert imported <= set(sys.stdlib_module_names)
    for banned in ("yaml", "requests", "typesafe_sdk"):
        assert banned not in imported
