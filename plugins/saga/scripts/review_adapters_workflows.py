#!/usr/bin/env python3
"""GitHub workflow review adapters (issue 152).

zizmor runs offline, with the narrowed environment, and receives no token.
actionlint scans a copy of the workflows. Its -config-file flag does not stop
it from parsing a discovered .github/actionlint.yaml, so that file is omitted
from the copy. The copy's command also disables the integrations that would
download a helper.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

import yaml

import review_tools
from review_tools import Adapter, Hit, ParseResult, ScanContext

_OWNED = ("zizmor", "actionlint")
_ROWS = {
    "zizmor": (
        "security.workflow-infra-high",
        "security.workflow-infra-medium-low",
        "security.tool-style",
    ),
    "actionlint": (
        "correctness.tool-error",
        "correctness.tool-warning",
        "correctness.tool-style",
    ),
}

_ZIZMOR_WRAPPER = r"""
import json, subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
dest = Path(sys.argv[2])
workflows = root / ".github" / "workflows"
copied = dest / ".github" / "workflows"
if workflows.is_dir():
    copied.mkdir(parents=True, exist_ok=True)
    for path in workflows.iterdir():
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}:
            (copied / path.name).write_text(
                path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
            )
if not copied.is_dir() or not any(copied.iterdir()):
    print("[]")
    raise SystemExit(0)
proc = subprocess.run(
    ["zizmor", "--offline", "--format=json", str(copied)],
    capture_output=True, text=True,
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
    if text.startswith("./"):
        text = text[2:]
    marker = ".github/workflows/"
    index = text.find(marker)
    if index >= 0:
        return text[index:]
    return text


def _invoke_zizmor(context: ScanContext) -> list[str]:
    dest = context.home / "zizmor-src"
    dest.mkdir(parents=True, exist_ok=True)
    return ["python3", "-c", _ZIZMOR_WRAPPER, str(context.root), str(dest)]


def _zizmor_location(item: dict) -> tuple[str, int | None]:
    locations = item.get("locations") or item.get("location") or []
    if isinstance(locations, dict):
        locations = [locations]
    path = str(item.get("path") or ".github/workflows/workflow.yml")
    line: int | None = None
    for location in locations if isinstance(locations, list) else []:
        if not isinstance(location, dict):
            continue
        symbolic = location.get("symbolic") if isinstance(location.get("symbolic"), dict) else {}
        key = symbolic.get("key") if isinstance(symbolic.get("key"), dict) else {}
        concrete = location.get("concrete") if isinstance(location.get("concrete"), dict) else {}
        path = str(
            concrete.get("path") or key.get("path") or location.get("path") or path
        )
        start = concrete.get("start") if isinstance(concrete.get("start"), dict) else {}
        candidate = start.get("line") or location.get("line")
        if isinstance(candidate, int):
            line = candidate
            break
    if line is None and isinstance(item.get("line"), int):
        line = int(item["line"])
    return _rel(path), line


def _parse_zizmor(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("zizmor output is not json") from exc
    if isinstance(data, dict):
        findings = data.get("findings") or data.get("results") or []
    elif isinstance(data, list):
        findings = data
    else:
        raise ValueError("zizmor output must be a list or an object")
    hits: list[Hit] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        raw_determinations = item.get("determinations")
        determinations = raw_determinations if isinstance(raw_determinations, dict) else {}
        severity = str(determinations.get("severity") or item.get("severity") or "low").lower()
        confidence = str(determinations.get("confidence") or "unknown")
        rule_id = str(item.get("ident") or item.get("rule") or "zizmor")
        path, line = _zizmor_location(item)
        if severity in {"critical", "high"}:
            row, level = "security.workflow-infra-high", None
        elif severity in {"medium", "low"}:
            row, level = "security.workflow-infra-medium-low", None
        else:
            row, level = None, "style"
        hits.append(Hit(
            rule_id=rule_id,
            path=path,
            statement=f"{rule_id} confidence {confidence}.",
            anchor=f"{rule_id} {path}",
            level=level,
            start=line,
            end=line,
            row=row,
            language="github-workflows",
        ))
    return ParseResult(tuple(hits))


# Copies workflows only. actionlint 1.7.12 still parses .github/actionlint.yaml
# in the scan directory when -config-file points at another file.
_ACTIONLINT_WRAPPER = r"""
import subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
dest = Path(sys.argv[2])
config = Path(sys.argv[3])
workflows = root / ".github" / "workflows"
copied = dest / ".github" / "workflows"
names = []
if workflows.is_dir():
    copied.mkdir(parents=True, exist_ok=True)
    for path in sorted(workflows.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        (copied / path.name).write_text(
            path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
        )
        names.append(".github/workflows/" + path.name)
if not names:
    print("[]")
    raise SystemExit(0)
proc = subprocess.run(
    [
        "actionlint", "-format", "{{json .}}", "-config-file", str(config),
        "-shellcheck=", "-pyflakes=", *names,
    ],
    cwd=dest, capture_output=True, text=True,
)
text = proc.stdout or ""
if text.strip():
    sys.stdout.write(text)
    raise SystemExit(0)
if proc.returncode in {0, 1}:
    print("[]")
    raise SystemExit(0)
raise SystemExit(proc.returncode)
"""


def _invoke_actionlint(context: ScanContext) -> list[str]:
    workflows = context.root / ".github" / "workflows"
    if not workflows.is_dir():
        return []
    names = [
        path.name
        for path in sorted(workflows.iterdir())
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    ]
    if not names:
        return []
    dest = context.home / "actionlint-src"
    dest.mkdir(parents=True, exist_ok=True)
    config = context.home / "actionlint.yaml"
    config.write_text("{}\n", encoding="utf-8")
    return ["python3", "-c", _ACTIONLINT_WRAPPER, str(context.root), str(dest), str(config)]


def _parse_actionlint(mapping: Mapping[str, str]) -> Callable[[str], ParseResult]:
    def parse(text: str) -> ParseResult:
        try:
            data = json.loads(text or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("actionlint output is not json") from exc
        if not isinstance(data, list):
            raise ValueError("actionlint output must be a list")
        hits: list[Hit] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "unknown")
            level = mapping.get(kind, "warning")
            start = item.get("line")
            message = " ".join(str(item.get("message") or kind).split())
            hits.append(Hit(
                rule_id=kind,
                path=_rel(str(item.get("filepath") or ".github/workflows/workflow.yml")),
                statement=f"{kind} {message}",
                anchor=kind,
                level=level,
                start=int(start) if isinstance(start, int) else None,
                end=int(start) if isinstance(start, int) else None,
                language="github-workflows",
            ))
        return ParseResult(tuple(hits))

    return parse


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
    action = by_id.get("actionlint") or {}
    kinds = action.get("kind_map") if isinstance(action, dict) else {}
    mapping = (
        {str(key): str(value) for key, value in kinds.items()}
        if isinstance(kinds, dict) else {}
    )
    if "zizmor" in by_id:
        zizmor = _from_row(by_id["zizmor"], _invoke_zizmor, _parse_zizmor)
    else:
        zizmor = None
    actionlint = (
        _from_row(by_id["actionlint"], _invoke_actionlint, _parse_actionlint(mapping))
        if "actionlint" in by_id else None
    )
    return [item for item in (zizmor, actionlint) if item is not None]


ADAPTERS: tuple[Adapter, ...] = tuple(_build(_document()))
