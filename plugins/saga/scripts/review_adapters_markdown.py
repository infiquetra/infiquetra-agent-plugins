#!/usr/bin/env python3
"""Markdown review adapters (issue 152).

markdownlint-cli2 and cspell are notes. markdownlint-cli2 v0.23.3 prints
``path:line[:col] error|warning MDxxx/name message`` on stderr; the column is present only for
some rules, and the older ``path:line:col MDxxx/name message`` shape is still read. A lychee broken
link is fix later and is compared base against head, because the report names
the file and the URL and not a line. cspell's dictionary, when the base commit
has one, is that file. lychee runs offline, so it checks local file links only and
a remote server never decides the result (issue 244).
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import yaml

import review_tools
from review_tools import Adapter, Hit, ParseResult, ScanContext

_OWNED = ("markdownlint-cli2", "lychee", "cspell")
_ROWS = {
    "markdownlint-cli2": ("correctness.tool-style",),
    "lychee": ("architecture-maintainability.tool-warning",),
    "cspell": ("architecture-maintainability.tool-style",),
}
_MARKDOWN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?::(?P<col>\d+))? "
    r"(?:(?:error|warning) )?(?P<code>MD\d+)(?:/\S+)?(?P<message>.*)$"
)
_CSPELL = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+) - Unknown word \((?P<word>[^)]+)\)\s*$"
)


def _document() -> dict[str, object]:
    loaded = yaml.safe_load(review_tools.TOOL_LIST.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise review_tools.RunnerFailure(2, "review-tools.yaml must be an object")
    return loaded


def _show(repo: Path, revision: str, path: str) -> str | None:
    if not revision:
        return None
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _rel(path: str) -> str:
    text = path.replace("\\", "/")
    return text[2:] if text.startswith("./") else text


def _markdown_files(root: Path) -> list[str]:
    found = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix.lower() == ".md":
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def _invoke_markdownlint(context: ScanContext) -> list[str]:
    files = _markdown_files(context.root)
    if not files:
        return []
    context.home.mkdir(parents=True, exist_ok=True)
    config = context.home / "markdownlint.yaml"
    config.write_text("{}\n", encoding="utf-8")
    return ["markdownlint-cli2", "--config", str(config), *files]


def _parse_markdownlint(text: str) -> ParseResult:
    hits: list[Hit] = []
    for raw in text.splitlines():
        match = _MARKDOWN.match(raw.strip())
        if match is None:
            continue
        code = match.group("code")
        line = int(match.group("line"))
        message = " ".join(match.group("message").split()) or code
        hits.append(Hit(
            rule_id=code,
            path=_rel(match.group("path")),
            statement=f"{code} {message}".strip(),
            anchor=code,
            level="style",
            start=line,
            end=line,
            language="markdown",
        ))
    return ParseResult(tuple(hits))


def _invoke_lychee(context: ScanContext) -> list[str]:
    files = _markdown_files(context.root)
    if not files:
        return []
    return ["lychee", "--offline", "--format", "json", *files]


def _without_durations(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_durations(item)
            for key, item in value.items()
            if key not in ("duration", "duration_secs")
        }
    if isinstance(value, list):
        return [_without_durations(item) for item in value]
    return value


def _stable_lychee(text: str) -> str:
    """lychee's report without its timings, which differ on every run."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(_without_durations(data), indent=2, sort_keys=True) + "\n"


def _parse_lychee(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("lychee output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("lychee output must be an object")
    # lychee 0.24, the pinned version, names the map error_map; older releases
    # called it fail_map.
    fail_map = data.get("error_map") or data.get("fail_map") or {}
    if not isinstance(fail_map, dict):
        raise ValueError("lychee error_map must be an object")
    hits: list[Hit] = []
    for path, entries in fail_map.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            url = entry.get("url") if isinstance(entry, dict) else entry
            if not url:
                continue
            hits.append(Hit(
                rule_id=str(url),
                path=_rel(str(path)),
                statement=f"Broken link {url}.",
                anchor=str(url),
                level="warning",
                whole_project=True,
                language="markdown",
            ))
    return ParseResult(tuple(hits))


def _cspell_config(context: ScanContext) -> Path:
    context.home.mkdir(parents=True, exist_ok=True)
    for name in ("cspell.json", ".cspell.json"):
        text = _show(context.repo, context.base, name)
        if text:
            dest = context.home / "cspell.json"
            dest.write_text(text, encoding="utf-8")
            return dest
    dest = context.home / "cspell.json"
    dest.write_text('{"version": "0.2", "language": "en"}\n', encoding="utf-8")
    return dest


def _invoke_cspell(context: ScanContext) -> list[str]:
    files = _markdown_files(context.root)
    if not files:
        return []
    return ["cspell", "lint", "--config", str(_cspell_config(context)), *files]


def _parse_cspell(text: str) -> ParseResult:
    hits: list[Hit] = []
    for raw in text.splitlines():
        match = _CSPELL.match(raw.strip())
        if match is None:
            continue
        word = match.group("word")
        line = int(match.group("line"))
        hits.append(Hit(
            rule_id=word,
            path=_rel(match.group("path")),
            statement=f"Unknown word {word}.",
            anchor=word,
            level="style",
            start=line,
            end=line,
            language="markdown",
        ))
    return ParseResult(tuple(hits))


def _from_row(
    row: Mapping[str, object],
    invoke: Callable[[ScanContext], list[str]],
    parse: Callable[[str], ParseResult],
    stable_raw: Callable[[str], str] | None = None,
) -> Adapter:
    tool_id = str(row.get("id") or "")
    return Adapter(
        id=tool_id,
        tool=str(row.get("tool") or ""),
        invoke=invoke,
        parse=parse,
        languages=tuple(str(item) for item in (row.get("languages") or ["*"])),
        rows=_ROWS[tool_id],
        comparison=str(row.get("comparison") or "lines"),
        lens=str(row.get("lens") or "correctness"),
        mode=str(row.get("mode") or "report"),
        timeout_seconds=int(row.get("timeout_seconds") or 120),
        version_args=tuple(str(item) for item in (row.get("version_args") or ("--version",))),
        default_version=str(row.get("default_version") or "not-recorded"),
        narrow_env=bool(row.get("narrow_env")),
        stream=str(row.get("stream") or "stdout"),
        stable_raw=stable_raw,
    )


def _build(document: Mapping[str, object]) -> list[Adapter]:
    tools = document.get("tools")
    if not isinstance(tools, list):
        raise review_tools.RunnerFailure(2, "review-tools.yaml tools must be a list")
    by_id = {
        str(row.get("id") or ""): row
        for row in tools
        if isinstance(row, dict) and str(row.get("id") or "") in _OWNED
    }
    specs = {
        "markdownlint-cli2": (_invoke_markdownlint, _parse_markdownlint, None),
        "lychee": (_invoke_lychee, _parse_lychee, _stable_lychee),
        "cspell": (_invoke_cspell, _parse_cspell, None),
    }
    return [
        _from_row(by_id[tool_id], *specs[tool_id])
        for tool_id in _OWNED
        if tool_id in by_id
    ]


ADAPTERS: tuple[Adapter, ...] = tuple(_build(_document()))
