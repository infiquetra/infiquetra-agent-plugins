#!/usr/bin/env python3
"""Store a unit's builder record, and check its declarations without opening a run record.

``write`` validates a file, merges it with the row's current ``builder_record``, and stores the
merge through ``review_records.record_builder``. ``check`` judges one file against the saga
plugin's policy list and the named proving tests. It never opens a run record (issue #162).

Exit codes for ``check``: 0 passed; 1 a declaration or a named test failed, one
``question <id>: <missing declaration|unknown question|test absent|test failing>`` line per
question on standard error; 2 the file is unreadable, the record is not valid, the revision
does not resolve, the policy fails to load, a proving test is not a node id, a proving test
escapes the revision worktree, or a question id is repeated.

Exit codes for ``write``: 0 stored; 1 the validator rejected the file or the merged record, and
nothing was written; 2 no run record, or the file is unreadable; 5 the row is missing on a record
orchestrate drives.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess  # nosec B404  (proving tests and git are argument vectors, never a shell)
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import question_banks  # noqa: E402  (after the sys.path shim, by design)
import review_records  # noqa: E402
import run_record  # noqa: E402

#: A pytest node id. Anything else is refused before a test runs. The pattern still admits an
#: absolute path and a ``..`` segment; ``_escapes_worktree`` refuses those, because pytest would
#: load that file from outside the revision worktree.
NODE_ID = re.compile(r"^[A-Za-z0-9_./:=\[\]-]+$")

#: A full commit, the only revision a proving test is checked out at.
FULL_REVISION = re.compile(r"^[0-9a-f]{40}$")

#: How long one proving test may run. A timeout is a failing test, not a pass.
TEST_TIMEOUT_SECONDS = 120

#: Environment variables copied into the proving-test child. Everything else is dropped.
_KEPT_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")

#: What a proving test did. ``absent`` is pytest's "nothing collected"; ``fail`` is any other no.
TestVerdict = str  # "pass" | "absent" | "fail"

RunTest = Callable[[str, str, Path], TestVerdict]


def plugin_dir() -> Path:
    """The saga plugin that contains this script.

    The policy is read from here, never from the checkout under test.
    """
    return Path(__file__).resolve().parents[1]


def _policy_ids() -> tuple[int, list[str]]:
    """``(exit, ids or problems)``. Exit 2 when the plugin's policy will not load."""
    try:
        policy = question_banks.load_policy(plugin_dir())
    except question_banks.BankRefusal as exc:
        return 2, [str(exc)]
    questions = policy.get("questions")
    if not isinstance(questions, list):
        return 2, ["policy: questions is not a list"]
    ids: list[str] = []
    for entry in questions:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("id"), str):
            return 2, ["policy: a question has no id"]
        ids.append(entry["id"])
    return 0, ids


def _missing(question_id: str) -> str:
    return f"question {question_id}: missing declaration"


def _unknown(question_id: str) -> str:
    return f"question {question_id}: unknown question"


def _escapes_worktree(node: str) -> bool:
    """True when pytest would load a file outside the revision worktree.

    The file is the node id before ``::``. An absolute path, or a ``..`` segment, names a
    file outside the checkout the proving test runs in. A ``..`` inside a parameter, after
    ``::``, is not a path segment.
    """
    path = node.split("::", 1)[0]
    if path.startswith("/") or Path(path).is_absolute():
        return True
    return ".." in path.split("/")


def _resolve_sha(repo: Path, revision: str) -> str | None:
    """The full commit *revision* names in *repo*, or ``None`` when git cannot say."""
    proc = subprocess.run(  # nosec B603  (shell=False, argv is git and the caller's revision)
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    sha = proc.stdout.strip()
    if proc.returncode == 0 and FULL_REVISION.fullmatch(sha):
        return sha
    return None


def _child_env(home: Path, tmp: Path) -> dict[str, str]:
    """A new environment: a few inherited settings, and fresh ``HOME`` and ``TMPDIR``."""
    env = {key: os.environ[key] for key in _KEPT_ENV if key in os.environ}
    env["HOME"] = str(home)
    env["TMPDIR"] = str(tmp)
    return env


def _run_proving_test(node: str, revision: str, repo: Path) -> TestVerdict:
    """Run *node* in a detached worktree of *revision*. The worktree is removed afterwards."""
    if NODE_ID.fullmatch(node) is None or _escapes_worktree(node):
        raise _Unrun("the proving test escapes the revision worktree")
    path = Path(tempfile.mkdtemp(prefix="saga-builder-worktree-"))
    hooks = Path(tempfile.mkdtemp(prefix="saga-builder-hooks-"))
    home = Path(tempfile.mkdtemp(prefix="saga-builder-home-"))
    tmp = Path(tempfile.mkdtemp(prefix="saga-builder-tmp-"))
    git_env = dict(os.environ)
    git_env["GIT_LFS_SKIP_SMUDGE"] = "1"
    try:
        added = subprocess.run(  # nosec B603
            [
                "git",
                "-C",
                str(repo),
                "-c",
                f"core.hooksPath={hooks}",
                "worktree",
                "add",
                "--detach",
                str(path),
                revision,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=git_env,
        )
        if added.returncode != 0:
            raise _Unrun("the proving-test worktree could not be created")
        try:
            proc = subprocess.run(  # nosec B603
                [sys.executable, "-m", "pytest", node, "-q", "--import-mode=importlib"],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                cwd=str(path),
                env=_child_env(home, tmp),
                timeout=TEST_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return "fail"
        text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        if proc.returncode == 0:
            return "pass"
        if proc.returncode in (4, 5) or "no tests ran" in text or "collected 0" in text:
            return "absent"
        return "fail"
    finally:
        subprocess.run(  # nosec B603
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(hooks, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


class _Unrun(Exception):
    """A proving test could not be started. The check fails closed."""


def _declaration_lines(
    declarations: list[Any],
) -> tuple[int, list[str], dict[str, Mapping[str, Any]]]:
    """Validate node ids and reject a repeated question before any test runs.

    Returns ``(exit, problems, by question id)``. Exit 0 means the declarations may be run.
    """
    by_question: dict[str, Mapping[str, Any]] = {}
    for declaration in declarations:
        if not isinstance(declaration, Mapping):
            return 2, ["declarations: an entry is not an object"], {}
        question_id = declaration.get("question")
        if not isinstance(question_id, str):
            return 2, ["declarations: a question id is missing"], {}
        if question_id in by_question:
            return 2, [f"declarations: duplicate question {question_id}"], {}
        proving = declaration.get("proving_test", None)
        if proving is not None:
            if not isinstance(proving, str) or NODE_ID.fullmatch(proving) is None:
                return 2, [f"question {question_id}: proving_test is not a node id"], {}
            if _escapes_worktree(proving):
                return 2, [
                    f"question {question_id}: proving_test escapes the revision worktree"
                ], {}
        by_question[question_id] = declaration
    return 0, [], by_question


def evaluate(
    record: Mapping[str, Any] | None,
    revision: str,
    repo: Path,
    *,
    run_test: RunTest | None = None,
) -> tuple[int, list[str]]:
    """Judge *record* against the plugin policy. Return ``(exit, lines)`` and write nothing.

    A missing record is exit 1, one missing-declaration line per policy id, and neither git nor
    pytest runs. A record ``review_records.validate`` rejects is exit 2, before git and pytest.
    The revision is resolved before any proving test, including when every proving test is null.
    """
    code, ids = _policy_ids()
    if code != 0:
        return code, ids
    if record is None:
        return 1, [_missing(question_id) for question_id in ids]
    if not isinstance(record, Mapping):
        return 2, ["record: not an object"]
    problems = review_records.validate(record)
    if problems:
        return 2, problems
    declarations = record.get("declarations")
    if not isinstance(declarations, list):
        return 2, ["declarations: not a list"]
    refused, refusal, by_question = _declaration_lines(declarations)
    if refused != 0:
        return refused, refusal

    sha = _resolve_sha(repo, revision)
    if sha is None:
        return 2, [f"revision {revision!r} does not resolve to a commit"]

    runner = run_test or _run_proving_test
    lines: list[str] = []
    policy = set(ids)
    try:
        for question_id in ids:
            declaration = by_question.get(question_id)
            if declaration is None:
                lines.append(_missing(question_id))
                continue
            proving = declaration.get("proving_test", None)
            if proving is None:
                continue
            verdict = runner(str(proving), sha, repo)
            if verdict == "pass":
                continue
            reason = "test absent" if verdict == "absent" else "test failing"
            lines.append(f"question {question_id}: {reason}")
        for question_id in by_question:
            if question_id not in policy:
                lines.append(_unknown(question_id))
    except _Unrun as exc:
        return 2, [str(exc)]
    return (1, lines) if lines else (0, [])


def merge_builder(
    stored: Mapping[str, Any] | None, incoming: Mapping[str, Any], unit: str
) -> dict[str, Any]:
    """Merge *incoming* onto *stored*. *unit* is the row's id and replaces the file's unit.

    Declarations merge by question id: the new file wins for an id it carries, and an id only on
    the stored record stays, in stored order, with new ids appended. Reasons merge by
    ``(kind, finding_id)`` the same way. ``acceptance_criteria`` comes from the new file when that
    array is non-empty, otherwise from the stored record.
    """
    merged = copy.deepcopy(dict(incoming))
    merged["unit"] = unit
    if stored is None:
        return merged
    merged["declarations"] = _merge_by(
        stored.get("declarations"), incoming.get("declarations"), lambda item: item.get("question")
    )
    merged["reasons"] = _merge_by(
        stored.get("reasons"),
        incoming.get("reasons"),
        lambda item: (item.get("kind"), item.get("finding_id")),
    )
    criteria = incoming.get("acceptance_criteria") or []
    if not criteria:
        merged["acceptance_criteria"] = copy.deepcopy(list(stored.get("acceptance_criteria") or []))
    return merged


def _merge_by(stored: Any, incoming: Any, key_of: Callable[[Mapping[str, Any]], Any]) -> list[Any]:
    """Stored order, then new ids. An incoming entry replaces the stored entry with the same key."""
    stored_items = list(stored or [])
    incoming_items = list(incoming or [])
    incoming_by: dict[Any, Mapping[str, Any]] = {}
    for item in incoming_items:
        if isinstance(item, Mapping):
            incoming_by[key_of(item)] = item
    merged: list[Any] = []
    seen: set[Any] = set()
    for item in stored_items:
        if not isinstance(item, Mapping):
            merged.append(copy.deepcopy(item))
            continue
        key = key_of(item)
        chosen = incoming_by.get(key, item)
        merged.append(copy.deepcopy(dict(chosen)))
        seen.add(key)
    for item in incoming_items:
        if not isinstance(item, Mapping):
            continue
        key = key_of(item)
        if key not in seen:
            merged.append(copy.deepcopy(dict(item)))
            seen.add(key)
    return merged


def write_record(
    store_root: Path, issue: int, unit: str, incoming: Mapping[str, Any]
) -> tuple[int, list[str]]:
    """Validate, merge, validate again, then store. A refusal writes nothing."""
    if not isinstance(incoming, Mapping):
        return 2, ["record: not an object"]
    problems = review_records.validate(incoming)
    if problems:
        return 1, problems
    try:
        existing = run_record.load(store_root, issue)
    except run_record.RunRecordError as exc:
        return 2, [str(exc)]
    if existing is None:
        return 2, [f"no record for issue {issue}"]
    stored = review_records.builder_record_for(existing, unit)
    if stored is not None:
        stored_problems = review_records.validate(stored)
        if stored_problems:
            return 1, stored_problems
    merged = merge_builder(stored, incoming, unit)
    problems = review_records.validate(merged)
    if problems:
        return 1, problems
    try:
        review_records.record_builder(store_root, issue, unit, merged)
    except review_records.MissingUnitError as exc:
        return 5, [str(exc)]
    except review_records.ReviewRecordError as exc:
        return 1, list(exc.problems)
    except run_record.RunRecordError as exc:
        return 2, [str(exc)]
    return 0, []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="builder_record.py",
        description=(
            "Store a unit's builder record, merging with what the row already holds, or check "
            "one file's declarations. check never opens a run record."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser(
        "check", help="Judge one builder-record file. Does not open a run record."
    )
    check.add_argument("--record", type=Path, required=True, help="The builder-record JSON file.")
    check.add_argument("--revision", required=True, help="The commit whose proving tests run.")
    check.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="The checkout the proving tests run against. Defaults to the working directory.",
    )
    write = sub.add_parser("write", help="Merge a builder record onto a unit row and store it.")
    write.add_argument("--issue", type=int, required=True)
    write.add_argument("--unit", required=True)
    write.add_argument("--record", type=Path, required=True)
    write.add_argument(
        "--store-root",
        type=Path,
        default=None,
        help="Override the resolved run-record store directory.",
    )
    return parser


def _read_object(path: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"builder_record: cannot read {path}: {exc}"
    if not isinstance(data, Mapping):
        return None, f"builder_record: {path} is not a JSON object"
    return data, None


def _emit(lines: list[str]) -> None:
    for line in lines:
        print(line, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data, problem = _read_object(args.record)
    if problem is not None or data is None:
        print(problem, file=sys.stderr)
        return 2
    if args.command == "check":
        code, lines = evaluate(data, args.revision, Path(args.repo))
        _emit(lines)
        return code
    store = (
        Path(args.store_root).resolve()
        if args.store_root is not None
        else run_record.resolve_store_root()
    )
    code, lines = write_record(store, args.issue, args.unit, data)
    _emit(lines)
    return code


if __name__ == "__main__":
    sys.exit(main())
