"""The bundled sweep validates once a later card attaches an answer (issue 156)."""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def test_the_bundled_sweep_validates_once_an_answer_is_attached(tmp_path: Path) -> None:
    bundled = _load("bundled_fleet")
    records = _load("review_records")
    sweep = bundled.load("jev_sweep")

    def ask(_state, questions, **_kwargs):
        class _Result:
            status = "ok"
            model = "jev-1.13.0"
            transport = "urllib"
            latency_ms = 5
            note = ""
            usage = {"input_tokens": 10, "output_tokens": 1}
            answers = {key: {"type": "noul", "noul": 0.91} for key in questions}

        return _Result()

    bank = {
        "schema": "question_bank.v1",
        "questions": [{
            "id": "leak",
            "lens": "security",
            "kind": "yes-no",
            "options": [
                {"id": "yes", "definition": "yes"},
                {"id": "no", "definition": "no"},
            ],
            "piece": "function",
        }],
    }
    piece = {
        "id": "a.py:1-2",
        "path": "a.py",
        "language": "python",
        "kind": "function",
        "text": "def f():\n    return 1\n",
        "degraded": False,
        "location": {
            "scope": "lines",
            "file": "a.py",
            "lines": {"start": 1, "end": 2},
            "function": "f",
            "anchor": "def f():",
        },
    }
    rate = {
        "uncached_input": 0,
        "cache_read": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "output": 0,
    }
    result = sweep.sweep(
        bank, [piece], {}, rate,
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "log",
        ask=ask,
    )
    assert len(result["items"]) == 1
    raw = result["items"][0]
    assert "answer" not in raw
    item = copy.deepcopy(raw)
    item["answer"] = {"kind": "cleared", "reason": "not reviewed yet"}
    assert records.validate(item) == []


def test_the_bundle_check_passes() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/bundle_fleet_module.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    declared = (REPO_ROOT / "plugins/saga/fleet-bundle.json").read_text(encoding="utf-8")
    assert "jev_sweep" in declared
