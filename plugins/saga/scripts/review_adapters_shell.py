#!/usr/bin/env python3
"""Shell review adapters (issue 152).

ShellCheck runs with --norc on a copy whose inline disable directives were removed.
shfmt is a formatter and the review runner does not start it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

import yaml

import review_tools
from review_tools import Adapter, Hit, ParseResult, ScanContext

_OWNED = ("shellcheck", "shfmt")
_ROWS = {
    "shellcheck": ("correctness.tool-error", "correctness.tool-warning", "correctness.tool-style"),
    "shfmt": ("correctness.tool-style",),
}

# Copies scripts, drops "# shellcheck disable", and runs shellcheck --norc.
_SHELLCHECK_WRAPPER = r"""
import json, subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
dest = Path(sys.argv[2])
scripts = []
for path in root.rglob("*"):
    if not path.is_file() or ".git" in path.parts:
        continue
    if path.name in {".shellcheckrc", "shellcheckrc"}:
        continue
    if path.suffix.lower() not in {".sh", ".bash", ".ksh"}:
        continue
    rel = path.relative_to(root)
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    kept = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "shellcheck disable" in line:
            head = line.split("#", 1)[0].rstrip()
            kept.append(head)
            continue
        kept.append(line)
    target.write_text("\n".join(kept) + "\n", encoding="utf-8")
    scripts.append(rel.as_posix())
if not scripts:
    print("[]")
    raise SystemExit(0)
proc = subprocess.run(
    ["shellcheck", "--norc", "-f", "json", *scripts],
    cwd=dest, capture_output=True, text=True,
)
sys.stdout.write(proc.stdout or "[]")
raise SystemExit(0)
"""


def _document() -> dict[str, object]:
    loaded = yaml.safe_load(review_tools.TOOL_LIST.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise review_tools.RunnerFailure(2, "review-tools.yaml must be an object")
    return loaded


def _rel(path: str) -> str:
    text = path.replace("\\", "/")
    return text[2:] if text.startswith("./") else text


def _invoke_shellcheck(context: ScanContext) -> list[str]:
    dest = context.home / "shellcheck-src"
    dest.mkdir(parents=True, exist_ok=True)
    return ["python3", "-c", _SHELLCHECK_WRAPPER, str(context.root), str(dest)]


def _parse_shellcheck(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("shellcheck output is not json") from exc
    if not isinstance(data, list):
        raise ValueError("shellcheck output must be a list")
    hits: list[Hit] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        rule_id = f"SC{code}" if code is not None else "shellcheck"
        level = str(item.get("level") or "warning").lower()
        if level not in {"error", "warning", "info", "style"}:
            level = "warning"
        start = item.get("line")
        end = item.get("endLine") if isinstance(item.get("endLine"), int) else start
        message = " ".join(str(item.get("message") or rule_id).split())
        hits.append(Hit(
            rule_id=rule_id,
            path=_rel(str(item.get("file") or ".")),
            statement=f"{rule_id} {message}",
            anchor=rule_id,
            level=level,
            start=int(start) if isinstance(start, int) else None,
            end=int(end) if isinstance(end, int) else None,
            language="shell",
        ))
    return ParseResult(tuple(hits))


def _invoke_nothing(_context: ScanContext) -> list[str]:
    return []


def _parse_nothing(_text: str) -> ParseResult:
    return ParseResult()


def _from_row(
    row: Mapping[str, object],
    invoke: Callable[[ScanContext], list[str]],
    parse: Callable[[str], ParseResult],
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
        "shellcheck": (_invoke_shellcheck, _parse_shellcheck),
        "shfmt": (_invoke_nothing, _parse_nothing),
    }
    return [
        _from_row(by_id[tool_id], specs[tool_id][0], specs[tool_id][1])
        for tool_id in _OWNED
        if tool_id in by_id
    ]


ADAPTERS: tuple[Adapter, ...] = tuple(_build(_document()))
