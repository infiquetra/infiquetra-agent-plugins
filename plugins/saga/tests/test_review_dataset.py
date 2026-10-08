"""The corpus dataset and the code evaluators (issue 166, card C15).

No test reaches the network; every post goes to an injected opener under a temporary home. The
evaluator fixture is worked by hand in the plan (U7), and the numbers below are those.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
ENV = {
    "SAGA_LANGFUSE_PUBLIC_KEY": "pk-lf-SENTINEL-public",
    "SAGA_LANGFUSE_SECRET_KEY": "sk-lf-SENTINEL-secret",
    "SAGA_LANGFUSE_HOST": "https://langfuse.example.test",
}


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D = _load("review_dataset")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("review dataset tests must make no network call")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


class _Response:
    status = 200

    def read(self) -> bytes:
        return b"{}"

    def getcode(self) -> int:
        return 200

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _Opener:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.requests.append(request)
        return _Response()

    def bodies(self) -> list[tuple[str, Any]]:
        return [(r.full_url, json.loads(r.data.decode())) for r in self.requests]


def _case(root: Path, name: str, split: str | None, **extra: Any) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    case: dict[str, Any] = {"case_id": name, **extra}
    if split is not None:
        case["split"] = split
    (folder / "case.json").write_text(json.dumps(case), encoding="utf-8")


def _corpus(tmp: Path) -> Path:
    root = tmp / "corpus"
    _case(root, "tune-1", "tuning", lens="security", defect_kind="injection")
    _case(root, "tune-2", "tuning", lens="testing", defect_kind="missing-test")
    _case(root, "held-1", "held-out", lens="security", defect_kind="HELD-OUT-KIND-SENTINEL",
          location={"file": "HELD-OUT-FILE-SENTINEL.py"})
    _case(root, "held-2", "held-out", lens="correctness", defect_kind="HELD-OUT-KIND-SENTINEL")
    return root


def test_dataset_items_carry_split(tmp_path: Path) -> None:
    opener = _Opener()
    code = D.main(["sync", "--corpus", str(_corpus(tmp_path)), "--home", str(tmp_path / "home")],
                  urlopen=opener, getenv=ENV.get)
    assert code == 0
    sent = opener.bodies()
    assert sent[0][0].endswith("/api/public/v2/datasets")
    assert sent[0][1]["name"] == "saga-review-corpus"
    items = [body for url, body in sent if url.endswith("/api/public/dataset-items")]
    assert len(items) == 4
    by_split = {item["metadata"]["split"] for item in items}
    assert by_split == {"tuning", "held-out"}
    for item in items:
        if item["metadata"]["split"] == "held-out":
            assert set(item["input"]) == {"case_id"}
    everything = json.dumps(sent)
    assert "HELD-OUT-KIND-SENTINEL" not in everything
    assert "HELD-OUT-FILE-SENTINEL" not in everything
    assert "injection" in everything


def test_case_without_split_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "corpus"
    _case(root, "good", "tuning")
    _case(root, "no-split", None)
    opener = _Opener()
    assert D.main(["sync", "--corpus", str(root), "--home", str(tmp_path / "home")],
                  urlopen=opener, getenv=ENV.get) == 2
    assert "no-split" in capsys.readouterr().err
    assert opener.requests == []


def _hand_worked() -> list[dict[str, Any]]:
    """Held-out security: 4 defects (3 blocked), 2 clean (1 blocked); q1 3 hits, 2 correct;
    4 repeated cases, 3 the same; $3.00 and 120 seconds over 6 reviews."""
    cases = []
    for index, blocked in enumerate((True, True, True, False)):
        cases.append({"case_id": f"d{index}", "split": "held-out", "lens": "security",
                      "language": "python", "expected": "defect", "blocked": blocked,
                      "cost_usd": 0.5, "seconds": 20})
    for index, blocked in enumerate((True, False)):
        cases.append({"case_id": f"c{index}", "split": "held-out", "lens": "security",
                      "language": "python", "expected": "clean", "blocked": blocked,
                      "cost_usd": 0.5, "seconds": 20})
    cases[0]["question_hits"] = [{"question": "security.q1", "correct": True}]
    cases[1]["question_hits"] = [{"question": "security.q1", "correct": True}]
    cases[4]["question_hits"] = [{"question": "security.q1", "correct": False}]
    for index, same in enumerate((True, True, True, False)):
        cases[index]["repeat_blocked"] = cases[index]["blocked"] if same else not cases[index]["blocked"]
    return cases


def test_evaluators_match_hand_worked_fixture() -> None:
    scores = {score["name"]: score["value"] for score in D.evaluate(_hand_worked())}
    assert scores == {
        "held-out.security.hit-rate": 0.75,
        "held-out.security.false-block-rate": 0.5,
        "held-out.question.security.q1.precision": 0.6667,
        "held-out.grade-stability": 0.75,
        "held-out.cost-usd-per-review": 0.5,
        "held-out.seconds-per-review": 20.0,
    }


def test_held_out_results_post_as_totals(tmp_path: Path) -> None:
    results = tmp_path / "harness.json"
    results.write_text(json.dumps({"cases": _hand_worked()}), encoding="utf-8")
    opener = _Opener()
    assert D.main(["score", "--results", str(results), "--run-id", "run-1",
                   "--home", str(tmp_path / "home")], urlopen=opener, getenv=ENV.get) == 0
    scores = [body for url, body in opener.bodies() if url.endswith("/api/public/scores")]
    assert len(scores) == 6
    allowed = ("held-out.security.", "held-out.question.", "held-out.grade-stability", "held-out.cost",
               "held-out.seconds")
    everything = json.dumps(opener.bodies())
    for score in scores:
        assert score["name"].startswith(allowed)
        assert score["dataType"] == "NUMERIC"
    for case in _hand_worked():
        assert f'"{case["case_id"]}"' not in everything


def test_score_dry_run_sends_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    results = tmp_path / "harness.json"
    results.write_text(json.dumps(_hand_worked()), encoding="utf-8")
    opener = _Opener()
    assert D.main(["score", "--results", str(results), "--run-id", "r", "--dry-run"],
                  urlopen=opener, getenv=ENV.get) == 0
    assert opener.requests == []
    assert len(json.loads(capsys.readouterr().out)["scores"]) == 6


def test_dataset_posts_private(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    (root / ".saga-profile.json").write_text(json.dumps({"visibility": "public"}), encoding="utf-8")
    opener = _Opener()
    home = tmp_path / "home"
    env = {**ENV, "SAGA_LANGFUSE_HOST": "http://langfuse.example.test"}
    assert D.main(["sync", "--corpus", str(root), "--home", str(home)],
                  urlopen=opener, getenv=env.get) == 0
    assert opener.requests == []
    reasons = D.review_trace.queue_status(home)["reasons"]
    assert reasons == {"plain-http-private": 5}
