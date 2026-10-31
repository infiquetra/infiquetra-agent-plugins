"""A mention of a removed name outside the edited lines (issue 155)."""

from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _harness() -> Any:
    path = Path(__file__).resolve().parent / "review_check_harness.py"
    spec = importlib.util.spec_from_file_location("review_check_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = _harness()

MENTION = "correctness.unupdated-mention"
DOCUMENT = "correctness.unupdated-mention-in-document"
OLD = "def old_name():\n    return 1\n"
NEW = "def new_name():\n    return 1\n"
CALLER = "import a\n\nvalue = a.old_name()\n"
STATEMENT = "A mention of a removed name remains outside the edited lines."


def test_generated_mentions_match_the_original_boundary_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare the complete result to the former per-name search on varied trees."""
    rng = random.Random(3917)
    paths = [tmp_path / name for name in (
        "src/a.py", "notes.md", "AGENTS.md", "skills/guide.md", "data.json",
    )]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    covered = {path.relative_to(tmp_path).as_posix(): {2, 5} for path in paths}

    class Change:
        def lines_for(self, path: str) -> set[int]:
            return covered.get(path, set())

    change = Change()
    removed: dict[str, bool] = {}
    monkeypatch.setattr(H.C.review_diff, "read", lambda *_args: change)
    monkeypatch.setattr(H.C, "_removed_names", lambda *_args: removed)
    monkeypatch.setattr(H.C, "_walk", lambda _root: iter(reversed(paths)))

    def old() -> dict[str, Any]:
        patterns = {name: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
                    for name in sorted(removed)}
        seen: set[tuple[str, str]] = set()
        hits: list[dict[str, Any]] = []
        for path in H.C._walk(tmp_path):
            rel = path.relative_to(tmp_path).as_posix()
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if number in change.lines_for(rel):
                    continue
                for name, pattern in patterns.items():
                    if (rel, name) in seen or pattern.search(line) is None:
                        continue
                    seen.add((rel, name))
                    hits.append(H.C._hit(
                        rule_id=name, path=rel, statement=STATEMENT, anchor=name,
                        row=H.C._row_for_mention(rel), language=H.C.language_for(rel),
                        degraded=removed[name],
                    ))
        hits.sort(key=lambda hit: (hit["path"], hit["rule_id"]))
        return {"hits": hits, "where_to_look": [], "gaps": []}

    names = ["", "a", "ab", "abc", "a_b", "7", "77", "_", "--flag", "a-b",
             "key.value", "é", "x/y", "[x]", "quote\"key"]
    fragments = ["", "a", "ab", "abc", "a_b", "7", "77", "_", "--flag", "a-b",
                 "key.value", "é", "界", "٣", "x/y", "[x]", "quote\"key", ".", " ", "!", "\t"]
    for iteration in range(60):
        removed.clear()
        removed.update({name: bool(rng.getrandbits(1)) for name in rng.sample(names, rng.randrange(1, len(names) + 1))})
        for path in paths:
            lines = ["".join(rng.choices(fragments, k=rng.randrange(0, 7))) for _ in range(9)]
            lines[0] = "éa٣ !ab! _abc_ 77"
            lines[1] = "--flag a-b key.value"
            lines[2] = ""
            lines[3] = "a a abc --flag --flag"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        actual = H.C.changed_names(tmp_path, "base")
        expected = old()
        assert actual == expected, f"generated tree {iteration}"
        assert json.dumps(actual) == json.dumps(expected), f"generated tree {iteration}"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sockets stay refused."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("scripted check tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _files(base_name: str, head_name: str, **extra: str) -> tuple[dict[str, str], dict[str, str]]:
    base = {"a.py": base_name, **extra}
    head = {"a.py": head_name, **extra}
    return base, head


def _by_file(output: Path, ref: str) -> dict[str, dict[str, Any]]:
    return {item["location"]["file"]: item for item in H.outcomes_for(output, ref)}


def test_a_caller_outside_the_change_blocks(tmp_path: Path) -> None:
    base, head = _files(OLD, NEW, **{"caller.py": CALLER})
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    H.valid(output)
    found = _by_file(output, "old_name")
    assert "caller.py" in found
    assert found["caller.py"]["severity"] == "blocks"
    assert found["caller.py"]["rule"]["row"] == MENTION
    raw = next(
        item for item in H.read(output, "findings.json")
        if item["rule"]["ref"] == "old_name" and item["location"]["file"] == "caller.py"
    )
    assert raw["statement"] == STATEMENT


def test_a_builder_reason_of_unaffected_turns_the_mention_into_a_note(tmp_path: Path) -> None:
    base, head = _files(OLD, NEW, **{"caller.py": CALLER})
    code, first, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    finding = next(
        item for item in H.read(first, "findings.json")
        if item["rule"]["ref"] == "old_name" and item["location"]["file"] == "caller.py"
    )
    repo, base_sha, head_sha = H.make_repo(tmp_path / "again", base, head)
    record = H.builder(finding["id"], "unaffected", tmp_path / "builder.json")
    second = tmp_path / "second"
    code = H.run(
        repo, base_sha, head_sha, H.profile(tmp_path / "profile.json", "echo ok"),
        second, tmp_path / "home", [H.adapter("changed-names")], builder=record,
    )
    assert code == 0
    found = _by_file(second, "old_name")["caller.py"]
    assert found["severity"] == "note"
    assert "excused" in found["severity_basis"]["modifiers"]


def test_a_document_mention_is_fix_later(tmp_path: Path) -> None:
    note = "The old_name stays in this note.\n"
    base, head = _files(OLD, NEW, **{"notes.md": note})
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")["notes.md"]
    assert found["severity"] == "fix-later"
    assert found["rule"]["row"] == DOCUMENT


def test_an_agent_instruction_and_a_skill_mention_block(tmp_path: Path) -> None:
    extra = {
        "AGENTS.md": "Call old_name from the instruction.\n",
        "skills/guide.md": "Call old_name from the skill.\n",
    }
    base, head = _files(OLD, NEW, **extra)
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")
    for path in ("AGENTS.md", "skills/guide.md"):
        assert found[path]["severity"] == "blocks"
        assert found[path]["rule"]["row"] == MENTION


def test_a_mention_on_an_edited_line_yields_nothing(tmp_path: Path) -> None:
    base = {"a.py": "def old_name():\n    return 1\n\nvalue = 1\n"}
    head = {"a.py": "def new_name():\n    return 1\n\nvalue = old_name()\n"}
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    assert H.outcomes_for(output, "old_name") == []


def test_a_name_that_remains_in_the_same_scope_yields_nothing(tmp_path: Path) -> None:
    base, head = _files(
        "def old_name():\n    return 1\n",
        "def old_name():\n    return 2\n",
        **{"caller.py": CALLER},
    )
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    assert H.outcomes_for(output, "old_name") == []


def test_the_same_spelling_in_another_file_still_blocks(tmp_path: Path) -> None:
    base, head = _files(OLD, NEW, **{"b.py": OLD, "caller.py": CALLER})
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")
    assert "caller.py" in found
    assert found["caller.py"]["severity"] == "blocks"
    assert all(item["severity"] == "blocks" for item in found.values())


def test_a_rust_file_is_degraded_when_ctags_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    H.executable(tmp_path / "bin" / "ctags", "#!/bin/sh\nexit 1\n")
    H.prepend(monkeypatch, tmp_path / "bin")
    base = {"lib.rs": "fn old_name() {}\n", "other.rs": "fn use_it() { old_name(); }\n"}
    head = {"lib.rs": "fn new_name() {}\n", "other.rs": "fn use_it() { old_name(); }\n"}
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")["other.rs"]
    assert found["degraded"] is True
    assert found["severity"] == "fix-later"
    assert "degraded" in found["severity_basis"]["modifiers"]


def test_a_python_file_that_does_not_parse_is_degraded(tmp_path: Path) -> None:
    base, head = _files(
        "def old_name():\n    return 1\n", "def new_name(\n", **{"caller.py": CALLER},
    )
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")["caller.py"]
    assert found["degraded"] is True
    assert found["severity"] == "fix-later"


def _mentions(root: Path, base: str) -> set[str]:
    payload = H.C.changed_names(root, base)
    return {hit["path"] for hit in payload["hits"]}


def test_only_tracked_files_report_a_mention(tmp_path: Path) -> None:
    """Issue 252: build output and ignored files in the copy are not repository files."""
    base, head = _files(OLD, NEW, **{"caller.py": CALLER, ".gitignore": "scratch.log\n"})
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    H.write(repo, {
        "target/debug/build.txt": "a.old_name()\n",
        "mutants.out/log.txt": "old_name\n",
        "scratch.log": "old_name\n",
    })
    assert H.git(repo, "status", "--porcelain", "--ignored").count("?? target/") == 1
    assert _mentions(repo, base_sha) == {"caller.py"}


def test_a_tracked_file_a_tool_deleted_is_not_read(tmp_path: Path) -> None:
    base, head = _files(OLD, NEW, **{"caller.py": CALLER})
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    (repo / "caller.py").unlink()
    assert _mentions(repo, base_sha) == set()


def test_a_tracked_file_a_tool_rewrote_is_read_as_it_is_on_disk(tmp_path: Path) -> None:
    """The file list comes from git; the text comes from the copy, as before."""
    base, head = _files(OLD, NEW, **{"caller.py": "value = 1\n"})
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    (repo / "caller.py").write_text(CALLER, encoding="utf-8")
    assert _mentions(repo, base_sha) == {"caller.py"}


def test_a_scan_root_that_is_not_a_git_repository_reads_every_file_but_dot_git(
    tmp_path: Path,
) -> None:
    """Fallback: no tracked set exists, so the old walk runs with ``.git`` skipped."""
    plain = tmp_path / "plain"
    H.write(plain, {
        "a.py": NEW, "caller.py": CALLER, "target/debug/build.txt": "a.old_name()\n",
        ".git/notes.txt": "old_name\n",
    })
    paths = {path.relative_to(plain).as_posix() for path in H.C._walk(plain)}
    assert paths == {"a.py", "caller.py", "target/debug/build.txt"}


def test_a_symlink_that_leaves_the_scan_root_is_still_refused(tmp_path: Path) -> None:
    base, head = _files(OLD, NEW, **{"caller.py": CALLER})
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    outside = tmp_path / "outside.py"
    outside.write_text(CALLER, encoding="utf-8")
    (repo / "link.py").symlink_to(outside)
    H.commit(repo, "link")
    assert {path.name for path in H.C._walk(repo)} == {"a.py", "caller.py"}
    assert _mentions(repo, base_sha) == {"caller.py"}


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_RAW = (
    "import json, sys\n"
    "from pathlib import Path\n"
    f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
    "import review_checks\n"
    "payload = review_checks.changed_names(Path(sys.argv[1]), sys.argv[2])\n"
    "sys.stdout.write(json.dumps(payload))\n"
)


def _raw_output(repo: Path, base: str, seed: int) -> str:
    """The check's whole output, as the stored raw output is built, in a fresh process."""
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _RAW, str(repo), base],
        env={**os.environ, "PYTHONHASHSEED": str(seed)},
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


def test_raw_output_is_identical_under_different_hash_seeds(tmp_path: Path) -> None:
    """Issue 260: removed names came from sets, so hit order followed each process's seed."""
    names = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    base = {
        "a.py": "".join(f"def {name}():\n    return 1\n" for name in names),
        "all.py": "x = " + ", ".join(f"{name}()" for name in names) + "\n",
        "b.txt": " ".join(names) + "\n",
        "--flags.md": "".join(f"--{name}-flag " for name in names) + "\n",
    }
    head = {**base, "a.py": "def zulu():\n    return 1\n", "--flags.md": "nothing\n"}
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    outputs = {_raw_output(repo, base_sha, seed) for seed in (0, 1, 2, 3, 4, 5, 6, 7)}
    assert len(outputs) == 1
    hits = json.loads(next(iter(outputs)))["hits"]
    assert len(hits) > len(names)
    assert hits == sorted(hits, key=lambda hit: (hit["path"], hit["rule_id"]))


def test_hits_are_sorted_by_path_and_name(tmp_path: Path) -> None:
    base, head = _files(
        "def zed():\n    pass\n\ndef abe():\n    pass\n", NEW,
        **{"z.py": "zed(); abe()\n", "m.py": "abe(); zed()\n"},
    )
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    hits = H.C.changed_names(repo, base_sha)["hits"]
    assert [(hit["path"], hit["rule_id"]) for hit in hits] == [
        ("m.py", "abe"), ("m.py", "zed"), ("z.py", "abe"), ("z.py", "zed"),
    ]


@pytest.mark.parametrize(("path", "line", "keywords"), [
    ("a.rs", "if self.ready { fn old_thing() }", ["if", "self", "fn"]),
    ("a.py", "if self.ready: return old_thing", ["if", "self", "return"]),
    ("a.go", "for _, v := range old_thing { func }", ["for", "range", "func"]),
    ("a.ts", "if (this.ready) { const old_thing }", ["if", "this", "const"]),
    ("a.sh", "if [ -n old_thing ]; then local fi", ["if", "then", "local", "fi"]),
    ("a.c", "if (ready) { while (old_thing) static }", ["if", "while", "static"]),
])
def test_the_text_fallback_never_reads_a_keyword_as_a_removed_name(
    path: str, line: str, keywords: list[str],
) -> None:
    names = H.C._text_names([line], [], path)
    assert not set(keywords) & set(names)
    assert "old_thing" in names


def test_the_text_fallback_keeps_a_keyword_of_another_language() -> None:
    """``func`` is Go's, not Python's: a Python file's own tokens decide."""
    assert "func" in H.C._text_names(["func run_it()"], [], "a.py")
    assert "func" not in H.C._text_names(["func run_it()"], [], "a.go")


@pytest.mark.parametrize("path", ["a.go", "a.c", "a.rs", "a.py", "a.ts", "a.sh", "notes.md"])
def test_the_text_fallback_drops_self_and_nothing_words_in_every_language(path: str) -> None:
    """Issue 260: ``self`` is noise in a Go or C file as much as in Python."""
    names = H.C._text_names(["self this cls nil null true None legacy_flag"], [], path)
    assert names == ["legacy_flag"]


def test_the_text_fallback_drops_every_languages_keywords_for_an_unlisted_suffix() -> None:
    names = H.C._text_names(["if self is pub in fn while legacy_flag"], [], "notes.md")
    assert names == ["legacy_flag"]


def test_the_text_fallback_drops_short_tokens_and_returns_sorted_names() -> None:
    names = H.C._text_names(["id io ab abc zebra apple q"], [], "a.go")
    assert names == ["abc", "apple", "zebra"]
    assert H.C._text_names(["old_thing"], ["old_thing"], "a.go") == []


def test_keywords_in_a_changed_go_file_are_not_mentions(tmp_path: Path) -> None:
    """End to end: Go has no ctags path, so a removed line's words used to be names."""
    base = {
        "a.go": "func run() {\n\tif legacy_flag() { return }\n}\n",
        "other.go": "func other() {\n\tif ok { return }\n}\nlegacy_flag()\n",
    }
    head = {**base, "a.go": "func run() {\n\t// gone\n}\n"}
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    hits = H.C.changed_names(repo, base_sha)["hits"]
    assert [(hit["path"], hit["rule_id"]) for hit in hits] == [("other.go", "legacy_flag")]


def test_a_python_file_that_does_not_parse_also_drops_keywords(tmp_path: Path) -> None:
    base = {
        "a.py": "def run(self):\n    if self.x:\n        legacy_flag()\n",
        "caller.py": "if self.x:\n    legacy_flag()\n",
    }
    head = {**base, "a.py": "def run(\n"}
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    hits = H.C.changed_names(repo, base_sha)["hits"]
    assert {(hit["path"], hit["rule_id"]) for hit in hits} == {("caller.py", "legacy_flag")}
