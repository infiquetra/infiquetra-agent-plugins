"""Cap on scripted where-to-look items in a review packet."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType
from typing import Any

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


def _item(
    file: str = "src/a.py",
    line: int = 1,
    *,
    lens: str = "architecture-maintainability",
    language: str = "python",
    classifier: str = "machine-specific-value",
    anchor: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "where_to_look",
        "schema": R.SCHEMA,
        "lens": lens,
        "language": language,
        "degraded": False,
        "questions": [{"id": "machine-specific-value", "probability": 1}],
        "classifier": {"name": classifier, "model": "review-checks 1.0.0"},
        "location": {
            "scope": "lines",
            "file": file,
            "lines": {"start": line, "end": line},
            "function": "changed",
            "anchor": anchor if anchor is not None else f"machine-specific-value:home:{line}",
        },
    }


def test_sixty_items_of_one_classifier_all_kept() -> None:
    items = [_item("src/a.py", n) for n in range(1, 61)]
    kept, degraded = C._cap_scripted_items(items)
    assert len(kept) == 60
    assert kept == items
    assert degraded == []


def test_sixty_one_items_in_one_file_cut_to_sixty() -> None:
    items = [_item("src/a.py", n) for n in range(1, 62)]
    kept, degraded = C._cap_scripted_items(items)
    assert len(kept) == 60
    assert len(degraded) == 1
    assert degraded[0]["reason"] == "item-cap"
    assert degraded[0]["count"] == 1


def test_two_hundred_items_over_one_hundred_files_spread() -> None:
    items: list[dict[str, Any]] = []
    for i in range(100):
        for j in range(2):
            items.append(_item(f"src/f{i:03d}.py", j + 1))
    kept, degraded = C._cap_scripted_items(items)
    assert len(kept) == 60
    files = {item["location"]["file"] for item in kept}
    assert len(files) == 60
    assert degraded[0]["count"] == 140


def test_two_languages_among_dropped_get_two_entries() -> None:
    items = [
        _item("src/a.py", n, language="python" if n % 2 == 0 else "rust")
        for n in range(1, 71)
    ]
    kept, degraded = C._cap_scripted_items(items)
    assert len(kept) == 60
    assert len(degraded) == 2
    assert sum(entry["count"] for entry in degraded) == 10
    assert {entry["language"] for entry in degraded} == {"python", "rust"}


def test_two_classifiers_only_over_cap_is_cut() -> None:
    over = [_item("src/a.py", n, classifier="machine-specific-value") for n in range(1, 71)]
    under = [_item("src/b.py", n, classifier="other-check") for n in range(1, 11)]
    kept, degraded = C._cap_scripted_items([*over, *under])
    over_kept = [i for i in kept if i["classifier"]["name"] == "machine-specific-value"]
    under_kept = [i for i in kept if i["classifier"]["name"] == "other-check"]
    assert len(over_kept) == 60
    assert len(under_kept) == 10
    assert all(entry["reason"] == "item-cap" for entry in degraded)
    assert all("machine-specific-value" in entry["input"] for entry in degraded)


def test_same_input_different_file_order_same_kept_set() -> None:
    items: list[dict[str, Any]] = []
    for i in range(40):
        for j in range(2):
            items.append(_item(f"src/f{i:03d}.py", j + 1))
    reordered = sorted(items, key=lambda e: json.dumps(e, sort_keys=True), reverse=True)
    kept_a, _ = C._cap_scripted_items(items)
    kept_b, _ = C._cap_scripted_items(reordered)
    def dump(rows: list[dict[str, Any]]) -> list[str]:
        return sorted(json.dumps(r, sort_keys=True) for r in rows)
    assert dump(kept_a) == dump(kept_b)


def test_detail_reads_exactly() -> None:
    items = [_item("src/a.py", n) for n in range(1, 62)]
    _, degraded = C._cap_scripted_items(items)
    assert degraded[0]["detail"] == (
        "listed 60 of 61 machine-specific-value items as where-to-look items"
    )


# --- end-to-end prepare check (copied setup from test_review_command.py) ---


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


class _Runner:
    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool, umask: int | None = None) -> Any:
        assert shell is False
        if Path(argv[0]).name == "git":
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
            return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
        if "--version" in argv:
            return T.ProcessResult(0, "1.0.0\n")
        return T.ProcessResult(0, "scan\n")


def _main(argv: list[str], **kwargs: Any) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        code = C.main(argv, **kwargs)
    return code, buffer.getvalue()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_prepare_caps_scripted_items_in_packet(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("def changed():\n    return 2\n", encoding="utf-8")
    head = _commit(repo, "head")
    profile_dir = tmp_path / "outside"
    profile_dir.mkdir()
    profile = profile_dir / "profile.json"
    profile.write_text(json.dumps({"schema": "repository_profile.v1"}) + "\n", encoding="utf-8")
    builder = tmp_path / "builder.json"
    builder.write_text(json.dumps({
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": "U1",
        "acceptance_criteria": [
            {"id": "AC-1", "text": "The changed line is the one the stub reports.", "checks": ["line"]},
        ],
        "declarations": [],
        "reasons": [],
    }), encoding="utf-8")
    bank = tmp_path / "bank.json"
    bank.write_text(json.dumps({
        "schema": "question_bank.v1",
        "questions": [{
            "id": "correctness.q-changed",
            "lens": "correctness",
            "kind": "yes-no",
            "options": [
                {"id": "yes", "definition": "The change breaks the behaviour the name describes."},
                {"id": "no", "definition": "The change keeps that behaviour."},
            ],
            "piece": "function",
        }],
    }), encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "packet"

    def _ask(_state: Any, questions: Any, **_kwargs: Any) -> Any:
        from types import SimpleNamespace

        if isinstance(questions, dict) and "consequence" in questions:
            return SimpleNamespace(
                status="ok", model="jev-test", note="",
                answers={"consequence": {"type": "choice", "choice": "required-behaviour-missing", "confidence": 0.9}},
            )
        answers = {key: {"type": "noul", "noul": 0.91} for key in questions}
        return SimpleNamespace(
            status="ok", ok=True, model="jev-test", latency_ms=5, note="",
            usage={"input_tokens": 12, "output_tokens": 4}, answers=answers,
        )

    items = tuple(_item("src/app.py", n) for n in range(1, 72))
    adapter = T.Adapter(
        id="scripted", tool="scripted", invoke=lambda _context: ["scripted", "scan"],
        parse=lambda _text: T.ParseResult(items=items), default_version="1.0.0",
        rows=("security.scanner-high",), lens="security", comparison="lines",
    )
    argv = [
        "prepare", "--repo", str(repo), "--base", base, "--head", head,
        "--profile", str(profile), "--builder-record", str(builder),
        "--out", str(out), "--home", str(home), "--bank", str(bank),
    ]
    code, err = _main(argv, adapters=[adapter], runner=_Runner(), ask=_ask)
    assert code == 0, err
    where = _read(out / "where-to-look.json")
    scripted = [i for i in where if i["classifier"]["name"] == "machine-specific-value"]
    assert len(scripted) == 60
    degraded = _read(out / "degraded.json")
    item_caps = [e for e in degraded if e["reason"] == "item-cap"]
    assert len(item_caps) == 1
    assert item_caps[0]["count"] == 11
