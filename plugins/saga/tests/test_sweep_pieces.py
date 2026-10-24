"""Saga cuts one piece per changed function (issue 156)."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P = _load("sweep_pieces")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("sweep piece tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-tools@example.com")
    _git(repo, "config", "user.name", "review-tools")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _bank(*kinds: str, ids: list[str] | None = None) -> dict[str, Any]:
    chosen = kinds or ("function",)
    questions = []
    for index, kind in enumerate(chosen):
        qid = ids[index] if ids else f"q{index}"
        questions.append({
            "id": qid,
            "lens": "correctness",
            "kind": "yes-no",
            "piece": kind,
            "options": [
                {"id": "yes", "definition": "yes"},
                {"id": "no", "definition": "no"},
            ],
        })
    return {"schema": "question_bank.v1", "questions": questions}


def _cut(repo: Path, base: str, head: str, bank: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("block_context_lines", 20)
    kwargs.setdefault("small_file_max_lines", 400)
    return P.pieces(repo, base, head, bank, **kwargs)


def test_a_changed_python_function_is_one_piece(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    target = repo / "src" / "billing"
    target.mkdir(parents=True)
    source = target / "charge.py"
    source.write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    base = _commit(repo, "base")
    source.write_text(
        "@billing\ndef charge(amount):\n    return amount + 1\n", encoding="utf-8",
    )
    head = _commit(repo, "head")

    result = _cut(repo, base, head, _bank("function"))
    functions = [piece for piece in result["pieces"] if piece["kind"] == "function"]
    assert len(functions) == 1
    piece = functions[0]
    assert piece["degraded"] is False
    assert piece["location"]["function"] == "charge"
    assert piece["location"]["anchor"] == "def charge(amount):"
    assert piece["text"] == "@billing\ndef charge(amount):\n    return amount + 1\n"
    assert piece["text"].startswith("@billing\n")
    assert "only_question" not in piece


def test_a_fake_parser_makes_one_piece_for_another_language(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    source = repo / "lib.rs"
    source.write_text("fn add() {\n    return 1;\n}\n", encoding="utf-8")
    base = _commit(repo, "base")
    source.write_text("fn add() {\n    return 2;\n}\n", encoding="utf-8")
    head = _commit(repo, "head")

    def parser(text: str, path: str, language: str) -> list[dict[str, Any]]:
        assert language == "rust" and path == "lib.rs"
        assert "return 2" in text
        return [{"name": "add", "start": 1, "end": 3, "anchor": "fn add() {"}]

    result = _cut(repo, base, head, _bank("function"), parser=parser)
    functions = [piece for piece in result["pieces"] if piece["kind"] == "function"]
    assert len(functions) == 1
    assert functions[0]["degraded"] is False
    assert functions[0]["text"] == "fn add() {\n    return 2;\n}\n"
    assert functions[0]["location"]["function"] == "add"


def test_without_the_parser_the_piece_is_the_window_and_degraded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    lines = [f"line {number}\n" for number in range(1, 51)]
    source = repo / "lib.rs"
    source.write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[24] = "LINE 25\n"
    source.write_text("".join(lines), encoding="utf-8")
    head = _commit(repo, "head")

    def parser(_text: str, _path: str, _language: str) -> list[dict[str, Any]]:
        raise FileNotFoundError("ctags")

    result = _cut(repo, base, head, _bank("function"), parser=parser)
    functions = [piece for piece in result["pieces"] if piece["kind"] == "function"]
    assert len(functions) == 1
    piece = functions[0]
    assert piece["degraded"] is True
    assert piece["location"]["function"] is None
    assert piece["location"]["lines"] == {"start": 5, "end": 45}
    assert piece["text"] == "".join(lines[4:45])


def test_a_question_that_asks_for_a_small_file_gets_the_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    small = repo / "small.py"
    small_text = "".join(f"line {number}\n" for number in range(1, 11))
    small.write_text(small_text, encoding="utf-8")
    base = _commit(repo, "base")
    changed = small_text.replace("line 2\n", "LINE 2\n")
    small.write_text(changed, encoding="utf-8")
    head = _commit(repo, "head")

    result = _cut(repo, base, head, _bank("file"))
    files = [piece for piece in result["pieces"] if piece["kind"] == "file"]
    assert len(files) == 1
    assert files[0]["text"] == changed
    assert result["degraded"] == []

    huge = repo / "huge.py"
    huge_text = "".join(f"v{number}\n" for number in range(1, 402))
    huge.write_text(huge_text, encoding="utf-8")
    grown = _commit(repo, "grow")
    huge.write_text(huge_text.replace("v2\n", "V2\n"), encoding="utf-8")
    grown_head = _commit(repo, "edit huge")
    large = _cut(repo, grown, grown_head, _bank("file", ids=["whole"]))
    assert not any(piece["kind"] == "file" for piece in large["pieces"])
    assert any(entry["reason"] == "file-too-large" for entry in large["degraded"])


def test_a_rename_with_no_edits_gives_no_piece(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "old.py").write_text("def charge():\n    return 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    _git(repo, "mv", "old.py", "new.py")
    head = _commit(repo, "rename")
    result = _cut(repo, base, head, _bank("function"))
    assert result["pieces"] == []


def test_overlapping_windows_merge(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    lines = [f"row {number}\n" for number in range(1, 81)]
    source = repo / "lib.rs"
    source.write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[9] = "ROW 10\n"
    lines[39] = "ROW 40\n"
    source.write_text("".join(lines), encoding="utf-8")
    head = _commit(repo, "head")

    def parser(_text: str, _path: str, _language: str) -> list[dict[str, Any]]:
        raise FileNotFoundError("ctags")

    result = _cut(repo, base, head, _bank("function"), parser=parser)
    functions = [piece for piece in result["pieces"] if piece["kind"] == "function"]
    assert len(functions) == 1
    assert functions[0]["location"]["lines"] == {"start": 1, "end": 60}


def test_a_nested_function_owns_the_line(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    source = repo / "nest.py"
    source.write_text(
        "def outer():\n    def inner():\n        return 1\n    return 0\n", encoding="utf-8",
    )
    base = _commit(repo, "base")
    source.write_text(
        "def outer():\n    def inner():\n        return 2\n    return 0\n", encoding="utf-8",
    )
    head = _commit(repo, "head")
    result = _cut(repo, base, head, _bank("function"))
    functions = [piece for piece in result["pieces"] if piece["kind"] == "function"]
    assert len(functions) == 1
    assert functions[0]["location"]["function"] == "inner"
    assert "def outer" not in functions[0]["text"]
    assert "return 2" in functions[0]["text"]


def test_a_corrupt_calibration_file_raises(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    source = repo / "charge.py"
    source.write_text("def charge():\n    return 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    source.write_text("def charge():\n    return 2\n", encoding="utf-8")
    head = _commit(repo, "head")
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(P.SweepPiecesError):
        _cut(repo, base, head, _bank("function", ids=["q0"]), calibration=broken)
    missing = tmp_path / "missing.json"
    with pytest.raises(P.SweepPiecesError):
        _cut(repo, base, head, _bank("function"), calibration=missing)

    empty = tmp_path / "empty.json"
    empty.write_text(
        json.dumps({"schema": "review_calibration.v1", "thresholds": [], "note": "extra"}),
        encoding="utf-8",
    )
    result = _cut(repo, base, head, _bank("function", ids=["q0"]), calibration=empty)
    functions = [piece for piece in result["pieces"] if piece["kind"] == "function"]
    assert len(functions) == 1
    assert functions[0]["text"] == "def charge():\n    return 2\n"
    assert "only_question" not in functions[0]
    assert result["thresholds"] == {}


def test_a_calibration_row_with_an_unexpected_key_raises(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    source = repo / "charge.py"
    source.write_text("def charge():\n    return 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    source.write_text("def charge():\n    return 2\n", encoding="utf-8")
    head = _commit(repo, "head")
    unexpected = tmp_path / "extra.json"
    unexpected.write_text(
        json.dumps({
            "schema": "review_calibration.v1",
            "thresholds": [{"question": "q0", "threshold": 0.5, "note": "no"}],
        }),
        encoding="utf-8",
    )
    with pytest.raises(P.SweepPiecesError):
        _cut(repo, base, head, _bank("function", ids=["q0"]), calibration=unexpected)
    missing_question = tmp_path / "missing-question.json"
    missing_question.write_text(
        json.dumps({
            "schema": "review_calibration.v1",
            "thresholds": [{"threshold": 0.5}],
        }),
        encoding="utf-8",
    )
    with pytest.raises(P.SweepPiecesError):
        _cut(repo, base, head, _bank("function", ids=["q0"]), calibration=missing_question)


def test_a_piece_size_clips_that_question(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    body = "".join(f"    keep_{number} = {number}\n" for number in range(1, 9))
    source = repo / "charge.py"
    source.write_text(f"def charge():\n{body}    return 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    source.write_text(f"def charge():\n{body}    return 2\n", encoding="utf-8")
    head = _commit(repo, "head")
    calibration = tmp_path / "calibration.json"
    calibration.write_text(
        json.dumps({
            "schema": "review_calibration.v1",
            "thresholds": [{"question": "q0", "threshold": 0.5, "piece_size": 4}],
        }),
        encoding="utf-8",
    )
    result = _cut(repo, base, head, _bank("function", ids=["q0"]), calibration=calibration)
    functions = [piece for piece in result["pieces"] if piece["kind"] == "function"]
    assert len(functions) == 2
    full = next(piece for piece in functions if "only_question" not in piece)
    clip = next(piece for piece in functions if piece.get("only_question") == "q0")
    assert full["text"].startswith("def charge():\n")
    assert clip["id"].endswith(":q0")
    assert clip["degraded"] is False
    assert clip["location"]["lines"]["end"] - clip["location"]["lines"]["start"] + 1 == 4
    assert "return 2" in clip["text"]


def test_an_exuberant_ctags_version_falls_back(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    lines = [f"line {number}\n" for number in range(1, 11)]
    source = repo / "lib.rs"
    source.write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[4] = "LINE 5\n"
    source.write_text("".join(lines), encoding="utf-8")
    head = _commit(repo, "head")

    def exuberant(_argv: list[str], _cwd: str) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="Exuberant Ctags 5.8\n", stderr="")

    fallen = _cut(repo, base, head, _bank("function"), ctags_runner=exuberant)
    assert fallen["pieces"][0]["degraded"] is True
    assert fallen["pieces"][0]["kind"] == "function"

    def universal(argv: list[str], _cwd: str) -> SimpleNamespace:
        if "--version" in argv:
            return SimpleNamespace(returncode=0, stdout="Universal Ctags 6.0.0\n", stderr="")
        payload = {"name": "add", "kind": "function", "line": 1, "end": 10}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload) + "\n", stderr="")

    parsed = _cut(repo, base, head, _bank("function"), ctags_runner=universal)
    assert parsed["pieces"][0]["degraded"] is False
    assert parsed["pieces"][0]["location"]["function"] == "add"
    assert P.ctags_is_universal("Exuberant Ctags 5.8") is False
    assert P.ctags_is_universal("Universal Ctags 6.0.0") is True


def test_the_ctags_tempfile_keeps_the_suffix_and_forces_the_language() -> None:
    seen: list[list[str]] = []
    held: list[Path] = []

    def runner(argv: list[str], _cwd: str) -> SimpleNamespace:
        seen.append(list(argv))
        if "--version" in argv:
            return SimpleNamespace(returncode=0, stdout="Universal Ctags 6.0.0\n", stderr="")
        blob = Path(argv[-1])
        assert blob.suffix == ".rs"
        assert blob.is_file()
        assert stat.S_IMODE(blob.stat().st_mode) == 0o600
        assert stat.S_IMODE(blob.parent.stat().st_mode) == 0o700
        held.append(blob)
        payload = {"name": "add", "kind": "function", "line": 1, "end": 1}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload) + "\n", stderr="")

    spans = P.read_ctags_spans("fn add() {}\n", "src/app.rs", "rust", runner=runner)
    assert spans is not None and spans[0]["name"] == "add"
    assert "--language-force=Rust" in seen[1]
    assert seen[1][1] == "--options=NONE"
    assert held and not held[0].exists()


def test_the_ctags_call_passes_no_double_dash_and_an_absolute_path() -> None:
    seen: list[list[str]] = []

    def runner(argv: list[str], _cwd: str) -> SimpleNamespace:
        seen.append(list(argv))
        if "--version" in argv:
            return SimpleNamespace(returncode=0, stdout="Universal Ctags 6.2.1\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    assert P.read_ctags_spans("fn a() {}\n", "-odd/-name.rs", "rust", runner=runner) == []
    assert "--" not in seen[1]
    assert Path(seen[1][-1]).is_absolute()
    assert not Path(seen[1][-1]).name.startswith("-")


def _real_universal_ctags_languages() -> set[str]:
    try:
        version = subprocess.run(  # noqa: S603
            ["ctags", "--options=NONE", "--version"],  # noqa: S607
            check=False, capture_output=True, text=True, timeout=30,
        )
        if version.returncode != 0 or "Universal Ctags" not in version.stdout:
            return set()
        listed = subprocess.run(  # noqa: S603
            ["ctags", "--options=NONE", "--list-languages"],  # noqa: S607
            check=False, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.split()[0] for line in listed.stdout.splitlines() if line.split()}


_REAL_CTAGS = _real_universal_ctags_languages()

_REAL_SOURCES = {
    "rust": (
        "src/lib.rs", "Rust",
        "pub struct Thing {\n    n: i32,\n}\n\nimpl Thing {\n"
        "    pub fn new() -> Self {\n        Thing { n: 0 }\n    }\n\n"
        "    #[inline]\n    pub fn get(&self) -> i32 {\n        self.n\n    }\n}\n",
        {"new": (6, 8), "get": (11, 13)},
    ),
    "typescript": (
        "src/app.ts", "TypeScript",
        "function add(a: number): number {\n  return a + 1;\n}\n\n"
        "function sub(a: number): number {\n  return a - 1;\n}\n",
        {"add": (1, 3), "sub": (5, 7)},
    ),
    "shell": (
        "bin/run.sh", "Sh",
        "first() {\n  echo one\n}\n\nsecond() {\n  echo two\n}\n",
        {"first": (1, 3), "second": (5, 7)},
    ),
}

# Code after the last function that ctags does not tag. The span must stop at the closing brace.
_UNTAGGED_AFTER = {
    "shell": (
        "bin/setup.sh", "Sh",
        "#!/bin/sh\nsetup() {\n  echo ready\n}\n\nsetup\necho done\n",
        {"setup": (2, 4)},
    ),
    "typescript": (
        "src/app.ts", "TypeScript",
        'import { n } from "./n";\n\nconst k = 1;\n\n// adds one\n'
        "function f(x: number) {\n  return x + k;\n}\n\n"
        "export default {\n  f,\n};\n",
        {"f": (6, 8)},
    ),
    "rust": (
        "src/lib.rs", "Rust",
        "struct S;\n\nimpl S {\n    fn a(&self) -> u8 {\n        1\n    }\n}\n\n"
        "fn free() -> u8 {\n    let c = '}';\n    \"}\".len() as u8\n}\n\n"
        "println!(\"trailing\");\n",
        {"a": (4, 6), "free": (9, 12)},
    ),
}


def _require_ctags(ctags_name: str) -> None:
    """Skip when ctags is absent here; fail when it is absent in CI, where it must be installed."""
    if ctags_name in _REAL_CTAGS:
        return
    reason = f"Universal Ctags with the {ctags_name} parser is not installed"
    if os.environ.get("CI"):
        pytest.fail(f"{reason}; the CI job installs it, so it must be there")
    pytest.skip(reason)


@pytest.mark.parametrize("language", sorted(_REAL_SOURCES))
def test_the_real_ctags_returns_function_boundaries(language: str) -> None:
    """The unit tests above mock ctags, so only this one saw the "--" the real tool rejects."""
    path, ctags_name, text, expected = _REAL_SOURCES[language]
    _require_ctags(ctags_name)
    spans = P.read_ctags_spans(text, path, language)
    assert spans, "ctags ran but no function came back; the call is probably rejected again"
    found = {span["name"]: (span["start"], span["end"]) for span in spans}
    assert found == expected


@pytest.mark.parametrize("language", sorted(_UNTAGGED_AFTER))
def test_the_real_ctags_spans_stop_at_the_closing_brace_not_at_untagged_code(
    language: str,
) -> None:
    """Holds whether this ctags gives an ``end`` (it is used) or not (the brace scan derives it)."""
    path, ctags_name, text, expected = _UNTAGGED_AFTER[language]
    _require_ctags(ctags_name)
    spans = P.read_ctags_spans(text, path, language)
    assert spans
    found = {span["name"]: (span["start"], span["end"]) for span in spans}
    assert found == expected


def _tags(*tags: dict[str, Any]) -> str:
    return "\n".join(json.dumps(tag) for tag in tags)


def _found(spans: list[dict[str, Any]] | None) -> dict[str, tuple[int, int]]:
    assert spans is not None
    return {span["name"]: (span["start"], span["end"]) for span in spans}


def test_a_function_with_no_end_ends_at_its_closing_brace_inside_the_next_tags_limit() -> None:
    lines = _tags(
        {"name": "outer", "kind": "function", "line": 1},
        {"name": "inner", "kind": "function", "line": 2, "scope": "outer"},
        {"name": "next", "kind": "function", "line": 7},
    )
    source = ["fn outer() {", "    fn inner() {}", "}", "", "// about next", "#[inline]",
              "fn next() {", "}", "", ""]
    assert _found(P._parse_tags(lines, source)) == {  # type: ignore[attr-defined]
        "outer": (1, 3), "inner": (2, 2), "next": (7, 8),
    }
    assert P._parse_tags(lines) == []  # type: ignore[attr-defined]


def test_a_shell_function_does_not_run_to_the_end_of_the_file() -> None:
    source = ["#!/bin/sh", "setup() {", "  echo ready", "}", "", "setup", "echo done"]
    lines = _tags({"name": "setup", "kind": "function", "line": 2})
    spans = P._parse_tags(lines, source, "shell")  # type: ignore[attr-defined]
    assert _found(spans) == {"setup": (2, 4)}


def test_a_typescript_function_does_not_swallow_the_export_default_after_it() -> None:
    source = [
        'import { n } from "./n";', "", "const k = 1;", "", "// adds one",
        "function f(x: number) {", "  return x + k;", "}", "",
        "export default {", "  f,", "};",
    ]
    lines = _tags({"name": "f", "kind": "function", "line": 6})
    spans = P._parse_tags(lines, source, "typescript")  # type: ignore[attr-defined]
    assert _found(spans) == {"f": (6, 8)}


def test_a_rust_impl_method_and_free_function_end_at_their_own_braces() -> None:
    source = [
        "struct S;", "", "impl S {", "    fn a(&self) -> u8 {", "        1", "    }", "}", "",
        "fn free() -> u8 {", "    let c = '}';", '    "}".len() as u8', "}", "",
        'println!("trailing");',
    ]
    lines = _tags(
        {"name": "S", "kind": "implementation", "line": 3},
        {"name": "a", "kind": "method", "line": 4, "scope": "S", "scopeKind": "implementation"},
        {"name": "free", "kind": "function", "line": 9},
    )
    spans = P._parse_tags(lines, source, "rust")  # type: ignore[attr-defined]
    assert _found(spans) == {"a": (4, 6), "free": (9, 12)}


def test_a_tags_own_end_is_used_when_ctags_gives_one() -> None:
    """A newer ctags may emit ``end`` for Rust; its value wins and the scan is not run."""
    source = ["fn a() {", "}", "trailing", "fn b() {", "}"]
    lines = _tags(
        {"name": "a", "kind": "function", "line": 1, "end": 2},
        {"name": "b", "kind": "function", "line": 4, "end": 5},
    )
    assert _found(P._parse_tags(lines, source, "rust")) == {  # type: ignore[attr-defined]
        "a": (1, 2), "b": (4, 5),
    }


@pytest.mark.parametrize(
    ("language", "source"),
    [
        ("rust", ["fn a() {", "    let x = 1;"]),
        ("rust", ["trait T {", "    fn a(&self);", "    fn b(&self);", "}"]),
        ("shell", ["a() {", '  echo "}"', "  # }"]),
        ("typescript", ["function f() {", '  const s = "}";', "  // }", "  /* } */"]),
    ],
)
def test_a_function_with_no_matching_close_brace_gets_no_span(
    language: str, source: list[str],
) -> None:
    """The braces in strings and comments do not count, so these never close: fixed window."""
    line = 2 if source[0].startswith("trait") else 1
    name = "a" if language != "typescript" else "f"
    lines = _tags({"name": name, "kind": "function", "line": line})
    assert P._parse_tags(lines, source, language) == []  # type: ignore[attr-defined]


def test_braces_in_parameters_strings_and_comments_do_not_move_the_end() -> None:
    source = [
        "function C({ a, b }: Props, [c]: number[] = []) {",
        '  const s = "{"; // }',
        "  const t = `${a}`;",
        "  /* } */ return { a, b };",
        "}",
        "const after = {};",
    ]
    lines = _tags({"name": "C", "kind": "function", "line": 1})
    spans = P._parse_tags(lines, source, "typescript")  # type: ignore[attr-defined]
    assert _found(spans) == {"C": (1, 5)}
    shell = ["f() {", '  echo "${#x} {"', "  case $1 in a) echo a ;; esac", "}", "echo $#"]
    lines = _tags({"name": "f", "kind": "function", "line": 1})
    spans = P._parse_tags(lines, shell, "shell")  # type: ignore[attr-defined]
    assert _found(spans) == {"f": (1, 4)}


def test_the_parser_row_is_on_the_tool_list_and_not_an_adapter() -> None:
    document = yaml.safe_load((REFERENCES / "review-tools.yaml").read_text(encoding="utf-8"))
    row = next(item for item in document["tools"] if item.get("id") == "universal-ctags")
    assert row["tool"] == "ctags"
    assert row["languages"] == ["typescript", "dart", "rust", "swift", "shell"]
    assert row["default_version"] == "not-recorded"
    assert row["version_args"] == ["--version"]
    assert "Universal Ctags" in row["install"]
    assert "Exuberant" in row["install"]
    for field in (
        "id", "tool", "languages", "lens", "purpose", "install", "default_version",
        "version_args", "timeout_seconds", "platforms", "comparison", "type_checker",
        "mutation", "mode", "level_map", "curated_block_rules", "rules", "env_dirs",
        "lockfiles",
    ):
        assert field in row
    adapters = _load("review_adapters_all_languages")
    assert all(item.id != "universal-ctags" for item in adapters.ADAPTERS)


def test_sweep_components_name_the_three_paths() -> None:
    assert P.SWEEP_COMPONENTS == (
        "plugins/fleet-core/scripts/fleet_commons/jev_sweep.py",
        "plugins/saga/scripts/sweep_pieces.py",
        "plugins/saga/references/model-prices.yaml",
    )
    lists = P.calibration_path_lists()
    calibration = SCRIPTS / "review_calibration.py"
    if lists is None:
        assert not calibration.is_file()
    else:
        assert calibration.is_file()
        assert any(all(path in found for path in P.SWEEP_COMPONENTS) for found in lists)


def test_c4a_fingerprint_is_unchanged() -> None:
    # C6 left C4a's five paths as the prefix. A later card may append.
    tools = _load("review_tools")
    # C4b and C4c each append their adapter modules after these five; the
    # full tuple is asserted by test_fingerprint_names_c4c_paths.
    assert tools.FINGERPRINT_COMPONENTS[:5] == (
        "plugins/saga/scripts/review_tools.py",
        "plugins/saga/scripts/review_diff.py",
        "plugins/saga/scripts/coverage_lines.py",
        "plugins/saga/scripts/review_adapters_all_languages.py",
        "plugins/saga/references/review-tools.yaml",
    )


def test_omitted_line_counts_come_from_the_bundle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    lines = [f"line {number}\n" for number in range(1, 51)]
    source = repo / "lib.rs"
    source.write_text("".join(lines), encoding="utf-8")
    base = _commit(repo, "base")
    lines[24] = "LINE 25\n"
    source.write_text("".join(lines), encoding="utf-8")
    head = _commit(repo, "head")

    def parser(_text: str, _path: str, _language: str) -> list[dict[str, Any]]:
        raise FileNotFoundError("ctags")

    result = P.pieces(repo, base, head, _bank("function"), parser=parser)
    piece = result["pieces"][0]
    assert piece["location"]["lines"] == {"start": 5, "end": 45}
