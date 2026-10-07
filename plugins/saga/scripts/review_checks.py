#!/usr/bin/env python3
"""Five scripted review checks for the rows no installed tool answers (issue 155).

The runner starts this plugin's copy of the script. The commit under review does not choose
the checks, the test commands, or the user and host names. Each subcommand prints one JSON
document and exits 0, including when the document's only content is a gap.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import review_diff
import review_formula
import review_tools
from review_tools import (
    Adapter,
    Hit,
    ParseResult,
    ScanContext,
    language_for,
    plugin_root,
)

VERSION = "1.0.0"
COMMAND_TIMEOUT = 30
GH_TIMEOUT = 20
ROW_BEFORE = "testing.test-passes-before-change"
ROW_SKIPPED = "testing.test-skipped-in-ci"
ROW_MACHINE = "architecture-maintainability.machine-specific-value"
ROW_MENTION = "correctness.unupdated-mention"
ROW_DOCUMENT = "correctness.unupdated-mention-in-document"
ROW_DEAD = "correctness.workflow-dead-end"
CHECKS = ("two-runs", "ci-skips", "machine-values", "changed-names", "workflow-graph")
_PRIMARY = {
    "two-runs": ROW_BEFORE,
    "ci-skips": ROW_SKIPPED,
    "machine-values": ROW_MACHINE,
    "changed-names": ROW_MENTION,
    "workflow-graph": ROW_DEAD,
}

# The same four names as scripts/check_repo.py INERT_HOME_DIRECTORY_USERS. Copied here so the
# tree under review cannot replace the set.
INERT_HOME_USERS = frozenset({"operator", "example", "op", "test"})
INERT_URL_HOSTS = frozenset({"example.com", "example.org", "example.net", "localhost"})
END_KINDS = frozenset({"terminal", "undefined_route"})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FLAG = re.compile(r"(?<![A-Za-z0-9_])(--[A-Za-z][A-Za-z0-9_-]*)(?![A-Za-z0-9_])")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_UNIX_PATH = re.compile(r"(?<![A-Za-z0-9_])(/(?:[A-Za-z0-9._-]+)){2,}")
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]:\\[^\s\"']+)")
_UNC_PATH = re.compile(r"(\\\\[^\s\\'\"]+\\[^\s\\'\"]+)")
_HOME_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:Users|home)/([^/\s\"'()<>]+)/")
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_ACCOUNT = re.compile(r"(?<!\d)(\d{12})(?!\d)")
_AGENT_NAMES = frozenset({"AGENTS.md", "CLAUDE.md", "GEMINI.md"})
_AGENT_DIRS = frozenset({"skills", "commands", "agents", "roles"})


def _script() -> str:
    return str(plugin_root() / "scripts" / "review_checks.py")


def _empty(gaps: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"hits": [], "where_to_look": [], "gaps": list(gaps or [])}


def _gap(reason: str, row: str) -> dict[str, str]:
    return {"reason": reason, "row": row}


def _reason_gap(result: str, row: str, fallback: str) -> dict[str, str]:
    """Keep a missing binary or a timeout. Anything else is the check's own gap."""
    reason = result if result in {"missing", "timeout"} else fallback
    return _gap(reason, row)


def _failure(command: str) -> dict[str, Any]:
    return _empty([_gap("unparseable", _PRIMARY.get(command, ROW_MENTION))])


def _language(pair_language: str, path: str) -> str:
    if pair_language in review_formula.LANGUAGES and pair_language != "none":
        return pair_language
    return language_for(path)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _git(
    repo: Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    hooks = Path(tempfile.mkdtemp(prefix="saga-hooks-"))
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    try:
        return subprocess.run(  # nosec B603
            ["git", "-c", f"core.hooksPath={hooks}", *args],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        shutil.rmtree(hooks, ignore_errors=True)


@contextmanager
def _detached(repo: Path, revision: str) -> Iterator[Path]:
    """Check out ``revision`` without running its hooks or Git LFS smudge filters."""
    path = Path(tempfile.mkdtemp(prefix="saga-review-"))
    hooks = Path(tempfile.mkdtemp(prefix="saga-hooks-"))
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    try:
        added = subprocess.run(  # nosec B603
            [
                "git", "-c", f"core.hooksPath={hooks}", "worktree", "add", "--detach",
                str(path), revision,
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if added.returncode != 0:
            shutil.rmtree(path, ignore_errors=True)
            detail = (added.stderr or added.stdout or "git worktree add failed").strip()
            raise RuntimeError(detail)
        try:
            yield path
        finally:
            subprocess.run(  # nosec B603
                [
                    "git", "-c", f"core.hooksPath={hooks}",
                    "worktree", "remove", "--force", str(path),
                ],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
    finally:
        shutil.rmtree(hooks, ignore_errors=True)


def _run_argv(
    argv: Sequence[str], cwd: Path, timeout: int
) -> tuple[str, int] | str:
    """Run one argument vector. A missing program or a timeout is that reason, not a hit."""
    try:
        proc = subprocess.run(  # nosec B603
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError:
        return "missing"
    except subprocess.TimeoutExpired:
        return "timeout"
    return proc.stdout or "", proc.returncode


def _classify(command: str) -> tuple[str, list[str]] | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    if "pytest" in tokens:
        return "pytest", tokens
    base = Path(tokens[0]).name
    if base == "cargo" and "test" in tokens:
        return "cargo", tokens
    if base == "swift" and "test" in tokens:
        return "swift", tokens
    return None


def _list_argv(kind: str, tokens: Sequence[str]) -> list[str]:
    if kind == "pytest":
        # One quiet flag prints node ids. A second one prints only a count per file.
        extra = ["--collect-only"]
        if not {"-q", "--quiet", "-qq"} & set(tokens):
            extra.append("-q")
        return [*tokens, *extra]
    if kind == "cargo":
        head = list(tokens[:tokens.index("--")]) if "--" in tokens else list(tokens)
        return [*head, "--", "--list"]
    return [tokens[0], "test", "list"]


def _select_argv(kind: str, tokens: Sequence[str], node_id: str) -> list[str]:
    if kind == "pytest":
        return [*tokens, node_id]
    if kind == "cargo":
        head = list(tokens[:tokens.index("--")]) if "--" in tokens else list(tokens)
        return [*head, node_id, "--", "--exact"]
    return [tokens[0], "test", "--filter", node_id]


def _parse_ids(kind: str, stdout: str) -> list[str] | None:
    """Recognisable ids, an empty list, or ``None`` when the text is not that listing."""
    text = stdout or ""
    if kind == "pytest":
        found = [line.strip() for line in text.splitlines() if "::" in line]
    elif kind == "cargo":
        found = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.endswith(": test"):
                found.append(stripped[: -len(": test")].strip())
    else:
        found = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("Compiling", "Build", "error:", "Error")):
                continue
            found.append(stripped)
    if text.strip() and not found:
        return None
    return found


def _list_ids(kind: str, tokens: Sequence[str], cwd: Path, timeout: int) -> list[str] | str:
    result = _run_argv(_list_argv(kind, tokens), cwd, timeout)
    if isinstance(result, str):
        return result
    stdout, code = result
    if code != 0:
        return "no-test-list"
    parsed = _parse_ids(kind, stdout)
    if parsed is None:
        return "no-test-list"
    return parsed


def _test_path(kind: str, node_id: str) -> str:
    if kind != "pytest":
        return "."
    return node_id.split("::", 1)[0] or "."


def _hit(
    *,
    rule_id: str,
    path: str,
    statement: str,
    anchor: str,
    row: str,
    language: str,
    degraded: bool = False,
    function: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rule_id": rule_id,
        "path": path or ".",
        "statement": statement,
        "anchor": anchor,
        "whole_project": True,
        "row": row,
        "degraded": degraded,
        "language": language,
    }
    if function is not None:
        payload["function"] = function
    return payload


def _copy_tests(
    head: Path,
    base_root: Path,
    change: review_diff.Change,
    kind: str,
    node_ids: Sequence[str],
) -> None:
    """Copy added or modified test files onto the base tree. Leave production files behind."""
    wanted: set[str] = set()
    for item in change.files:
        if item.status not in {"added", "modified", "renamed"}:
            continue
        if any(piece in item.path for piece in ("test", "tests", "spec")):
            wanted.add(item.path)
        if kind == "pytest" and Path(item.path).name == "conftest.py":
            wanted.add(item.path)
    if kind == "pytest":
        for node_id in node_ids:
            wanted.add(_test_path(kind, node_id))
    for rel in wanted:
        if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
            continue
        source = head / rel
        dest = base_root / rel
        if not source.is_file() or not _inside(source, head) or not _inside(dest, base_root):
            continue
        if source.is_symlink() and not _inside(source.resolve(), head):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest, follow_symlinks=False)


def two_runs(
    root: Path,
    base: str,
    commands: Sequence[tuple[str, str]],
    *,
    command_timeout: int = COMMAND_TIMEOUT,
) -> dict[str, Any]:
    """A new test that passes at head and on the base tree, with the head's tests copied in."""
    change = review_diff.read(root, base, "HEAD")
    hits: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    for pair_language, command in commands:
        classified = _classify(command)
        if classified is None:
            gaps.append(_gap("no-test-list", ROW_BEFORE))
            continue
        kind, tokens = classified
        head_ids = _list_ids(kind, tokens, root, command_timeout)
        if isinstance(head_ids, str):
            reason = head_ids if head_ids in {"missing", "timeout"} else "no-test-list"
            gaps.append(_gap(reason, ROW_BEFORE))
            continue
        try:
            detached = _detached(root, base)
        except RuntimeError:
            gaps.append(_gap("no-test-list", ROW_BEFORE))
            continue
        with detached as base_root:
            base_ids = _list_ids(kind, tokens, base_root, command_timeout)
            if isinstance(base_ids, str):
                reason = base_ids if base_ids in {"missing", "timeout"} else "no-test-list"
                gaps.append(_gap(reason, ROW_BEFORE))
                continue
            fresh = [node for node in head_ids if node not in set(base_ids)]
            passing: list[str] = []
            failed = False
            for node in fresh:
                result = _run_argv(_select_argv(kind, tokens, node), root, command_timeout)
                if isinstance(result, str):
                    gaps.append(_reason_gap(result, ROW_BEFORE, "no-test-list"))
                    failed = True
                    break
                if result[1] == 0:
                    passing.append(node)
            if failed or not passing:
                continue
            _copy_tests(root, base_root, change, kind, passing)
            confirmed: list[str] = []
            for node in passing:
                result = _run_argv(_select_argv(kind, tokens, node), base_root, command_timeout)
                if isinstance(result, str):
                    gaps.append(_reason_gap(result, ROW_BEFORE, "no-test-list"))
                    confirmed = []
                    break
                if result[1] == 0:
                    confirmed.append(node)
            for node in confirmed:
                path = _test_path(kind, node)
                hits.append(_hit(
                    rule_id=node,
                    path=path,
                    statement="The new test passes on the code before the change.",
                    anchor=node,
                    row=ROW_BEFORE,
                    language=_language(pair_language, path),
                ))
    return {"hits": hits, "where_to_look": [], "gaps": gaps}


def _head_sha(root: Path) -> str:
    proc = _git(root, ["rev-parse", "HEAD"])
    if proc.returncode != 0:
        raise RuntimeError("git rev-parse HEAD failed")
    return (proc.stdout or "").strip()


def _gh(args: Sequence[str], timeout: int) -> tuple[str, int] | str:
    """Run ``gh`` in a fresh empty directory so it cannot read a config from the worktree."""
    empty = Path(tempfile.mkdtemp(prefix="saga-gh-"))
    try:
        return _run_argv(["gh", *args], empty, timeout)
    finally:
        shutil.rmtree(empty, ignore_errors=True)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _junit_cases(text: str) -> list[tuple[str, str, str | None]]:
    """``(name, classname, skip message or None when the case is not skipped)``."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    cases: list[tuple[str, str, str | None]] = []
    for element in root.iter():
        if _local(element.tag) != "testcase":
            continue
        name = element.attrib.get("name") or ""
        classname = element.attrib.get("classname") or ""
        skipped: str | None = None
        found_skip = False
        for child in list(element):
            if _local(child.tag) != "skipped":
                continue
            found_skip = True
            message = (child.attrib.get("message") or child.text or "").strip()
            skipped = message
        if found_skip:
            cases.append((name, classname, skipped or ""))
        else:
            cases.append((name, classname, None))
    return cases


def _case_matches(node_id: str, name: str, classname: str) -> bool:
    if name == node_id or node_id.endswith("::" + name):
        return True
    return bool(name) and name in node_id and (not classname or classname.split(".")[-1] in node_id)


def _log_skip(line: str, node_id: str) -> str | None:
    """The reason after SKIPPED, ``""`` when the skip has no reason, or ``None`` when not a skip."""
    if node_id not in line:
        return None
    match = re.search(r"\b(SKIPPED|skipped)\b", line)
    if match is None:
        return None
    return line[match.end():].strip()


def _ci_judgement(
    node_ids: Sequence[str], log_text: str, junit_text: str
) -> tuple[list[str], str | None]:
    """Node ids that block, or a gap reason when the report names no test."""
    cases = _junit_cases(junit_text) if junit_text.strip() else []
    names_a_test = ("::" in log_text) or bool(cases)
    if not names_a_test:
        return [], "log-names-no-test"
    blocking: list[str] = []
    for node_id in node_ids:
        reasoned = False
        silent = False
        shown = node_id in log_text
        for line in log_text.splitlines():
            reason = _log_skip(line, node_id)
            if reason is None:
                continue
            shown = True
            if reason:
                reasoned = True
            else:
                silent = True
        for name, classname, message in cases:
            if not _case_matches(node_id, name, classname):
                continue
            shown = True
            if message is None:
                continue
            if message.strip():
                reasoned = True
            else:
                silent = True
        if reasoned:
            continue
        if silent or not shown:
            blocking.append(node_id)
    return blocking, None


def ci_skips(
    root: Path,
    base: str,
    commands: Sequence[tuple[str, str]],
    *,
    command_timeout: int = COMMAND_TIMEOUT,
    gh_timeout: int = GH_TIMEOUT,
) -> dict[str, Any]:
    """A new test the finished run skipped with no reason, or never showed."""
    listed, list_gaps, _change = _collect_for_ci(root, base, commands, command_timeout)
    gaps = [
        _gap(item["reason"], ROW_SKIPPED) if item["row"] == ROW_BEFORE else item
        for item in list_gaps
    ]
    if any(item["reason"] in {"missing", "timeout", "no-test-list"} for item in gaps):
        # A language that could not be listed contributes no continuous-integration hit.
        failed = {gap["reason"] for gap in gaps}
        listed = [item for item in listed if item["language"] not in failed]
    if not listed and gaps:
        return {"hits": [], "where_to_look": [], "gaps": gaps}
    if not listed:
        return _empty(gaps)
    try:
        head = _head_sha(root)
    except RuntimeError:
        gaps.append(_gap("no-finished-run", ROW_SKIPPED))
        return {"hits": [], "where_to_look": [], "gaps": gaps}
    listed_run = _gh(
        ["run", "list", "--commit", head, "--json", "databaseId,conclusion,status,headSha"],
        gh_timeout,
    )
    if isinstance(listed_run, str):
        reason = listed_run if listed_run in {"missing", "timeout"} else "no-finished-run"
        gaps.append(_gap(reason, ROW_SKIPPED))
        return {"hits": [], "where_to_look": [], "gaps": gaps}
    stdout, code = listed_run
    try:
        runs = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError:
        runs = []
    if code != 0 or not isinstance(runs, list):
        gaps.append(_gap("no-finished-run", ROW_SKIPPED))
        return {"hits": [], "where_to_look": [], "gaps": gaps}
    completed = [
        item for item in runs
        if isinstance(item, dict) and item.get("status") == "completed" and item.get("databaseId")
    ]
    if not completed:
        gaps.append(_gap("no-finished-run", ROW_SKIPPED))
        return {"hits": [], "where_to_look": [], "gaps": gaps}
    run_id = str(completed[0]["databaseId"])
    viewed = _gh(["run", "view", run_id, "--json", "artifacts"], gh_timeout)
    if isinstance(viewed, str):
        gaps.append(_reason_gap(viewed, ROW_SKIPPED, "no-finished-run"))
        return {"hits": [], "where_to_look": [], "gaps": gaps}
    artifact_name = _junit_artifact(viewed[0])
    log_text = ""
    junit_text = ""
    if artifact_name:
        destination = Path(tempfile.mkdtemp(prefix="saga-junit-"))
        try:
            downloaded = _gh(
                ["run", "download", run_id, "--name", artifact_name, "--dir", str(destination)],
                gh_timeout,
            )
            if isinstance(downloaded, str):
                gaps.append(_reason_gap(downloaded, ROW_SKIPPED, "no-finished-run"))
                return {"hits": [], "where_to_look": [], "gaps": gaps}
            junit_text = _read_downloaded(destination)
        finally:
            shutil.rmtree(destination, ignore_errors=True)
    else:
        logged = _gh(["run", "view", run_id, "--log"], gh_timeout)
        if isinstance(logged, str):
            gaps.append(_reason_gap(logged, ROW_SKIPPED, "no-finished-run"))
            return {"hits": [], "where_to_look": [], "gaps": gaps}
        log_text = logged[0]
    blocking, silent = _ci_judgement([item["node"] for item in listed], log_text, junit_text)
    if silent:
        gaps.append(_gap(silent, ROW_SKIPPED))
        return {"hits": [], "where_to_look": [], "gaps": gaps}
    by_node = {item["node"]: item for item in listed}
    hits = []
    for node in blocking:
        item = by_node[node]
        hits.append(_hit(
            rule_id=node,
            path=item["path"],
            statement="The new test was skipped or never shown in the finished run.",
            anchor=node,
            row=ROW_SKIPPED,
            language=item["language"],
        ))
    return {"hits": hits, "where_to_look": [], "gaps": gaps}


def _collect_for_ci(
    root: Path,
    base: str,
    commands: Sequence[tuple[str, str]],
    timeout: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]], review_diff.Change]:
    change = review_diff.read(root, base, "HEAD")
    found: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    for pair_language, command in commands:
        classified = _classify(command)
        if classified is None:
            gaps.append(_gap("no-test-list", ROW_BEFORE))
            continue
        kind, tokens = classified
        head_ids = _list_ids(kind, tokens, root, timeout)
        if isinstance(head_ids, str):
            gaps.append(_reason_gap(head_ids, ROW_BEFORE, "no-test-list"))
            continue
        try:
            detached = _detached(root, base)
        except RuntimeError:
            gaps.append(_gap("no-test-list", ROW_BEFORE))
            continue
        with detached as base_root:
            base_ids = _list_ids(kind, tokens, base_root, timeout)
        if isinstance(base_ids, str):
            gaps.append(_reason_gap(base_ids, ROW_BEFORE, "no-test-list"))
            continue
        for node in head_ids:
            if node in set(base_ids):
                continue
            path = _test_path(kind, node)
            found.append({
                "language": _language(pair_language, path),
                "node": node,
                "path": path,
            })
    return found, gaps, change


def _junit_artifact(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        return None
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        name = str(artifact.get("name") or "")
        if "junit" in name.lower():
            return name
    return None


def _read_downloaded(directory: Path) -> str:
    chunks: list[str] = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not path.is_symlink():
            try:
                chunks.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
    return "\n".join(chunks)


def _mask(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < right and end > left for left, right in spans)


def _machine_spans(line: str, user: str, host: str) -> list[str]:
    """Kind names on this line. The matched text is not returned."""
    claimed: list[tuple[int, int]] = []
    kinds: list[str] = []

    def take(kind: str | None, start: int, end: int) -> None:
        if _mask(claimed, start, end):
            return
        claimed.append((start, end))
        if kind:
            kinds.append(kind)

    for match in _URL.finditer(line):
        host_name = (urlparse(match.group(0)).hostname or "").lower()
        take(None if host_name in INERT_URL_HOSTS else "url", match.start(), match.end())
    for pattern, kind in ((_UNC_PATH, "unc"), (_WINDOWS_PATH, "windows-path")):
        for match in pattern.finditer(line):
            take(kind, match.start(), match.end())
    for match in _HOME_PATH.finditer(line):
        inert = match.group(1) in INERT_HOME_USERS
        take(None if inert else "home", match.start(), match.end())
    for match in _UNIX_PATH.finditer(line):
        take("unix-path", match.start(), match.end())
    for match in _ACCOUNT.finditer(line):
        take("account-id", match.start(), match.end())
    for kind, needle in (("user", user), ("host", host)):
        if (
            len(needle) < 3
            or needle in INERT_HOME_USERS
            or needle.lower() in INERT_URL_HOSTS
        ):
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(needle)}(?![A-Za-z0-9_])")
        for match in pattern.finditer(line):
            take(kind, match.start(), match.end())
    return kinds


def _function_at(text: str, line: int) -> str | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        if node.lineno <= line <= end:
            span = end - node.lineno
            if best is None or span < best[0]:
                best = (span, node.name)
    return None if best is None else best[1]


def machine_values(root: Path, base: str, user: str, host: str) -> dict[str, Any]:
    """One unanswered where-to-look item for each machine-specific value on an added line."""
    change = review_diff.read(root, base, "HEAD")
    items: list[dict[str, Any]] = []
    for item in change.files:
        if item.status not in {"added", "modified", "renamed"}:
            continue
        path = root / item.path
        if not path.is_file() or not _inside(path, root):
            continue
        if path.is_symlink() and not _inside(path.resolve(), root):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        lines = text.splitlines()
        for number in sorted(item.lines):
            if number < 1 or number > len(lines):
                continue
            for kind in _machine_spans(lines[number - 1], user, host):
                function = _function_at(text, number) if path.suffix == ".py" else None
                items.append({
                    "kind": "where_to_look",
                    "schema": "review_records.v1",
                    "lens": "architecture-maintainability",
                    "language": language_for(item.path),
                    "degraded": False,
                    "questions": [{"id": "machine-specific-value", "probability": 1}],
                    "classifier": {
                        "name": "machine-specific-value",
                        "model": "review-checks 1.0.0",
                    },
                    "location": {
                        "scope": "lines",
                        "file": item.path,
                        "lines": {"start": number, "end": number},
                        "function": function,
                        "anchor": f"machine-specific-value:{kind}:{number}",
                    },
                })
    return {"hits": [], "where_to_look": items, "gaps": []}


def _searchable(name: str) -> bool:
    if re.fullmatch(r"--[A-Za-z][A-Za-z0-9_-]*", name):
        return True
    if _IDENT.fullmatch(name):
        return True
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name))


def _remember(found: dict[str, bool], name: str, degraded: bool) -> None:
    if not _searchable(name):
        return
    if name not in found or not degraded:
        found[name] = degraded if name not in found else False


def _python_defs(text: str) -> set[tuple[str, str, str]] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    found: set[tuple[str, str, str]] = set()

    def walk(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.add(("function", scope, child.name))
                walk(child, scope)
            elif isinstance(child, ast.ClassDef):
                found.add(("class", scope, child.name))
                next_scope = f"{scope}.{child.name}" if scope else child.name
                walk(child, next_scope)
            else:
                walk(child, scope)

    walk(tree, "")
    return found


def _argument_flags(text: str) -> set[str] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            name = ""
        if name != "add_argument" or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.add(arg.value)
    return found


def _json_keys(text: str) -> set[tuple[str, str]] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return _key_paths(payload)


def _toml_keys(text: str) -> set[tuple[str, str]] | None:
    import tomllib

    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    return _key_paths(payload)


def _key_paths(value: Any, prefix: str = "") -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            leaf = str(key)
            path = f"{prefix}.{leaf}" if prefix else leaf
            found.add((path, leaf))
            found |= _key_paths(inner, path)
    elif isinstance(value, list):
        for inner in value:
            found |= _key_paths(inner, prefix)
    return found


def _diff_lines(repo: Path, base: str) -> dict[str, tuple[list[str], list[str]]]:
    proc = _git(repo, ["diff", "-U0", "--no-color", "--find-renames", base, "HEAD"])
    files: dict[str, tuple[list[str], list[str]]] = {}
    current: str | None = None
    removed: list[str] = []
    added: list[str] = []

    def flush() -> None:
        if current is not None:
            files[current] = (list(removed), list(added))

    for line in (proc.stdout or "").splitlines():
        if line.startswith("diff --git "):
            flush()
            marker = " b/"
            current = line.split(marker, 1)[1] if marker in line else line.split()[-1]
            removed, added = [], []
        elif line.startswith("rename to "):
            current = line[len("rename to "):]
        elif line.startswith(("---", "+++")):
            continue
        elif current is not None and line.startswith("-"):
            removed.append(line[1:])
        elif current is not None and line.startswith("+"):
            added.append(line[1:])
    flush()
    return files


def _text_names(removed: Sequence[str], added: Sequence[str]) -> set[str]:
    gone = set(_TOKEN.findall("\n".join(removed))) - set(_TOKEN.findall("\n".join(added)))
    return {token for token in gone if _searchable(token)}


def _show(repo: Path, revision: str, path: str) -> str:
    proc = _git(repo, ["show", f"{revision}:{path}"])
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


def _read_head(root: Path, rel: str) -> str:
    path = root / rel
    if not path.is_file() or not _inside(path, root):
        return ""
    if path.is_symlink() and not _inside(path.resolve(), root):
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _removed_names(root: Path, base: str, change: review_diff.Change) -> dict[str, bool]:
    """Name to whether every way we learned it was a degraded text comparison."""
    found: dict[str, bool] = {}
    diff = _diff_lines(root, base)
    removed_flags: set[str] = set()
    added_flags: set[str] = set()
    for removed, added in diff.values():
        removed_flags.update(_FLAG.findall("\n".join(removed)))
        added_flags.update(_FLAG.findall("\n".join(added)))
    for flag in removed_flags - added_flags:
        _remember(found, flag, False)
    for item in change.files:
        old = item.old_path or item.path
        if item.status == "deleted":
            stem = Path(item.path).stem
            _remember(found, stem, False)
        elif (
            item.status == "renamed"
            and item.old_path
            and Path(item.old_path).stem != Path(item.path).stem
        ):
            _remember(found, Path(old).stem, False)
        before = "" if item.status == "added" else _show(root, base, old)
        after = "" if item.status == "deleted" else _read_head(root, item.path)
        removed_lines, added_lines = diff.get(item.path, ([], []))
        suffix = Path(item.path).suffix.lower()
        if suffix == ".py":
            _python_removed(found, before, after, removed_lines, added_lines)
        elif suffix == ".json":
            _structured_removed(found, before, after, removed_lines, added_lines, _json_keys)
        elif suffix == ".toml":
            _structured_removed(found, before, after, removed_lines, added_lines, _toml_keys)
        elif suffix in {".yaml", ".yml"}:
            for name in _text_names(removed_lines, added_lines):
                _remember(found, name, True)
        else:
            language = language_for(item.path)
            _other_removed(found, before, after, item.path, language, removed_lines, added_lines)
    return found


def _python_removed(
    found: dict[str, bool],
    before: str,
    after: str,
    removed_lines: Sequence[str],
    added_lines: Sequence[str],
) -> None:
    base_defs = _python_defs(before) if before else set()
    head_defs = _python_defs(after) if after else set()
    base_flags = _argument_flags(before) if before else set()
    head_flags = _argument_flags(after) if after else set()
    if (before and base_defs is None) or (after and head_defs is None):
        for name in _text_names(removed_lines, added_lines):
            _remember(found, name, True)
        return
    for _kind, _scope, name in set(base_defs or ()) - set(head_defs or ()):
        _remember(found, name, False)
    if base_flags is not None and head_flags is not None:
        for flag in set(base_flags) - set(head_flags):
            _remember(found, flag, False)


def _structured_removed(
    found: dict[str, bool],
    before: str,
    after: str,
    removed_lines: Sequence[str],
    added_lines: Sequence[str],
    keys_of: Any,
) -> None:
    base_keys = keys_of(before) if before else set()
    head_keys = keys_of(after) if after else set()
    if (before and base_keys is None) or (after and head_keys is None):
        for name in _text_names(removed_lines, added_lines):
            _remember(found, name, True)
        return
    head_paths = {path for path, _leaf in set(head_keys or ())}
    for path, leaf in set(base_keys or ()):
        if path not in head_paths:
            _remember(found, leaf, False)


def _other_removed(
    found: dict[str, bool],
    before: str,
    after: str,
    path: str,
    language: str,
    removed_lines: Sequence[str],
    added_lines: Sequence[str],
) -> None:
    import sweep_pieces

    if language in sweep_pieces.CTAGS_LANGUAGES:
        base_names = _span_names(before, path, language)
        head_names = _span_names(after, path, language)
        if base_names is not None and head_names is not None:
            for name in base_names - head_names:
                _remember(found, name, False)
            return
    for name in _text_names(removed_lines, added_lines):
        _remember(found, name, True)


def _span_names(text: str, path: str, language: str) -> set[str] | None:
    import sweep_pieces

    if not text.strip():
        return set()
    spans = sweep_pieces.read_ctags_spans(text, path, language)
    if spans is None:
        return None
    names = {
        str(span["name"])
        for span in spans
        if isinstance(span.get("name"), str) and span["name"]
    }
    return names


def _row_for_mention(path: str) -> str:
    name = Path(path).name
    if name in _AGENT_NAMES:
        return ROW_MENTION
    parts = set(Path(path).parts)
    if path.endswith(".md") and parts & _AGENT_DIRS:
        return ROW_MENTION
    if path.endswith(".md"):
        return ROW_DOCUMENT
    return ROW_MENTION


def _walk(root: Path) -> Iterator[Path]:
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for filename in filenames:
            path = Path(directory) / filename
            if path.is_symlink() and not _inside(path, root):
                continue
            yield path


def changed_names(root: Path, base: str) -> dict[str, Any]:
    """Mentions of a removed name on lines the change did not edit."""
    change = review_diff.read(root, base, "HEAD")
    removed = _removed_names(root, base, change)
    hits: list[dict[str, Any]] = []
    patterns = {
        name: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        for name in removed
    }
    seen: set[tuple[str, str]] = set()
    for path in _walk(root):
        rel = path.relative_to(root).as_posix()
        covered = change.lines_for(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if number in covered:
                continue
            for name, pattern in patterns.items():
                if (rel, name) in seen or pattern.search(line) is None:
                    continue
                seen.add((rel, name))
                hits.append(_hit(
                    rule_id=name,
                    path=rel,
                    statement="A mention of a removed name remains outside the edited lines.",
                    anchor=name,
                    row=_row_for_mention(rel),
                    language=language_for(rel),
                    degraded=removed[name],
                ))
    return {"hits": hits, "where_to_look": [], "gaps": []}


def _graph(payload: Any) -> tuple[dict[str, str], dict[str, list[str]]] | None:
    if not isinstance(payload, dict):
        return None
    steps = payload.get("steps")
    nodes = payload.get("nodes")
    transitions = payload.get("transitions")
    if not isinstance(transitions, list):
        return None
    if not isinstance(steps, list) and not isinstance(nodes, list):
        return None
    if steps is not None and not isinstance(steps, list):
        return None
    if nodes is not None and not isinstance(nodes, list):
        return None
    kinds: dict[str, str] = {}
    for node in nodes or []:
        if (
            isinstance(node, dict)
            and isinstance(node.get("id"), str)
            and isinstance(node.get("kind"), str)
        ):
            kinds[node["id"]] = str(node["kind"])
    for step in steps or []:
        if isinstance(step, dict) and isinstance(step.get("id"), str):
            kinds.setdefault(str(step["id"]), "step")
    edges: dict[str, list[str]] = {state: [] for state in kinds}
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        source = transition.get("from")
        target = transition.get("to")
        if source in edges and isinstance(target, str):
            edges[source].append(target)
    return kinds, edges


def _reaches_end(start: str, kinds: Mapping[str, str], edges: Mapping[str, Sequence[str]]) -> bool:
    if kinds.get(start) in END_KINDS:
        return True
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if kinds.get(current) in END_KINDS:
            return True
        stack.extend(edges.get(current, ()))
    return False


def workflow_graph(root: Path) -> dict[str, Any]:
    """States in a run-model file from which no end state can be reached."""
    hits: list[dict[str, Any]] = []
    for path in _walk(root):
        if path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        graph = _graph(payload)
        if graph is None:
            continue
        kinds, edges = graph
        rel = path.relative_to(root).as_posix()
        for state, kind in sorted(kinds.items()):
            if kind in END_KINDS or _reaches_end(state, kinds, edges):
                continue
            hits.append(_hit(
                rule_id=state,
                path=rel,
                statement="This state has no path to an end state.",
                anchor=state,
                row=ROW_DEAD,
                language="none",
            ))
    return {"hits": hits, "where_to_look": [], "gaps": []}


def parse(text: str) -> ParseResult:
    """Map one check document onto hits, where-to-look items, and gaps."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("review check output must be an object")
    hits: list[Hit] = []
    for item in data.get("hits") or []:
        if not isinstance(item, dict):
            raise ValueError("hit must be an object")
        start = item.get("start")
        end = item.get("end")
        hits.append(Hit(
            rule_id=str(item.get("rule_id") or item.get("anchor") or ""),
            path=str(item.get("path") or ""),
            statement=str(item.get("statement") or ""),
            anchor=str(item.get("anchor") or ""),
            start=start if isinstance(start, int) else None,
            end=end if isinstance(end, int) else None,
            function=item.get("function") if isinstance(item.get("function"), str) else None,
            whole_project=bool(item.get("whole_project")),
            row=str(item["row"]) if item.get("row") else None,
            language=str(item["language"]) if item.get("language") else None,
            degraded=bool(item.get("degraded")),
        ))
    where = tuple(
        dict(item) for item in (data.get("where_to_look") or []) if isinstance(item, dict)
    )
    gaps: list[tuple[str, str]] = []
    for gap in data.get("gaps") or []:
        if isinstance(gap, dict) and gap.get("reason") and gap.get("row"):
            gaps.append((str(gap["reason"]), str(gap["row"])))
    return ParseResult(tuple(hits), items=where, gaps=tuple(gaps))


def _invoke(context: ScanContext, check: str, extra: list[str]) -> list[str]:
    return [sys.executable, _script(), check, *extra]


def _commands_arg(context: ScanContext) -> str:
    return json.dumps([list(pair) for pair in context.commands])


def _invoke_two_runs(context: ScanContext) -> list[str]:
    return _invoke(
        context, "two-runs", ["--base", context.base, "--commands", _commands_arg(context)]
    )


def _invoke_ci(context: ScanContext) -> list[str]:
    return _invoke(
        context, "ci-skips", ["--base", context.base, "--commands", _commands_arg(context)]
    )


def _invoke_machine(context: ScanContext) -> list[str]:
    import getpass
    import socket

    return _invoke(context, "machine-values", [
        "--base", context.base,
        "--user", getpass.getuser(),
        "--host", socket.gethostname(),
    ])


def _invoke_names(context: ScanContext) -> list[str]:
    return _invoke(context, "changed-names", ["--base", context.base])


def _invoke_workflow(context: ScanContext) -> list[str]:
    return _invoke(context, "workflow-graph", [])


def _adapter(
    check: str,
    invoke: Any,
    *,
    comparison: str,
    lens: str,
    rows: tuple[str, ...],
    narrow: bool = False,
) -> Adapter:
    return Adapter(
        id=check,
        tool="review-checks",
        invoke=invoke,
        parse=parse,
        languages=("*",),
        rows=rows,
        comparison=comparison,
        lens=lens,
        timeout_seconds=120,
        default_version=VERSION,
        version_argv=(sys.executable, _script(), "--version"),
        narrow_env=narrow,
    )


ADAPTERS: tuple[Adapter, ...] = (
    _adapter(
        "two-runs", _invoke_two_runs, comparison="lines", lens="testing",
        rows=(ROW_BEFORE,), narrow=True,
    ),
    _adapter("ci-skips", _invoke_ci, comparison="lines", lens="testing", rows=(ROW_SKIPPED,)),
    _adapter(
        "machine-values", _invoke_machine, comparison="lines",
        lens="architecture-maintainability", rows=(ROW_MACHINE,),
    ),
    _adapter(
        "changed-names", _invoke_names, comparison="lines", lens="correctness",
        rows=(ROW_MENTION, ROW_DOCUMENT),
    ),
    _adapter(
        "workflow-graph", _invoke_workflow, comparison="base-head", lens="correctness",
        rows=(ROW_DEAD,),
    ),
)


def _pairs(text: str) -> list[tuple[str, str]]:
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("commands must be a list")
    pairs: list[tuple[str, str]] = []
    for item in payload:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("each command is a language and a command")
        pairs.append((str(item[0]), str(item[1])))
    return pairs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_checks.py",
        description=(
            "Scripted review checks: two-runs, ci-skips, machine-values, "
            "changed-names, and workflow-graph."
        ),
    )
    parser.add_argument("--version", action="store_true", help="Print 1.0.0 and exit.")
    sub = parser.add_subparsers(dest="command")
    for name in ("two-runs", "ci-skips"):
        command = sub.add_parser(name)
        command.add_argument("--base", required=True)
        command.add_argument("--commands", required=True)
    machine = sub.add_parser("machine-values")
    machine.add_argument("--base", required=True)
    machine.add_argument("--user", required=True)
    machine.add_argument("--host", required=True)
    names = sub.add_parser("changed-names")
    names.add_argument("--base", required=True)
    sub.add_parser("workflow-graph")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        print(VERSION)
        return 0
    parsed = _parser().parse_args(args)
    if parsed.version:
        print(VERSION)
        return 0
    root = Path.cwd()
    command = str(parsed.command or "")
    try:
        if command == "two-runs":
            payload = two_runs(root, parsed.base, _pairs(parsed.commands))
        elif command == "ci-skips":
            payload = ci_skips(root, parsed.base, _pairs(parsed.commands))
        elif command == "machine-values":
            payload = machine_values(root, parsed.base, parsed.user, parsed.host)
        elif command == "changed-names":
            payload = changed_names(root, parsed.base)
        elif command == "workflow-graph":
            payload = workflow_graph(root)
        else:
            _parser().print_help()
            return 2
    except Exception:
        traceback.print_exc(file=sys.stderr)
        payload = _failure(command)
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
