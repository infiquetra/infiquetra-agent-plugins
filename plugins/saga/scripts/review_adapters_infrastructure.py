#!/usr/bin/env python3
"""CloudFormation and CDK review adapters (issue 152).

cdk-nag and checkov-cdk set narrow_env. A missing nag report is a degraded input.
The adapter does not look for a cdk_nag import. Checkov scans a copy or a synth
directory, so a settings file in the reviewed tree is not an input.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import yaml

import review_tools
from review_tools import Adapter, Hit, ParseResult, ScanContext, ToolGap

_OWNED = ("cdk-nag", "checkov-cdk", "checkov-cfn", "cfn-lint")
_ROWS = {
    "cdk-nag": ("security.workflow-infra-high", "security.workflow-infra-medium-low"),
    "checkov-cdk": ("security.tool-curated", "security.tool-unscoped"),
    "checkov-cfn": ("security.tool-curated", "security.tool-unscoped"),
    "cfn-lint": ("correctness.tool-error", "correctness.tool-warning", "correctness.tool-style"),
}
_CDK_VERSION = (
    "python3", "-c",
    "import importlib.metadata as m; print(m.version('cdk-nag'))",
)
_NAG_ROW = "security.workflow-infra-high"

# Synthesizes with the environment the runner supplied and prints one JSON document.
_CDK_NAG_WRAPPER = r"""
import json, subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
out = Path(sys.argv[2])
try:
    proc = subprocess.run(
        ["cdk", "synth", "--output", str(out)],
        cwd=root, capture_output=True, text=True,
    )
except FileNotFoundError:
    print(json.dumps({"report_present": False, "synth_missing": True, "findings": []}))
    raise SystemExit(0)
findings = []

def walk(node, logical):
    if not isinstance(node, dict):
        return
    meta = node.get("Metadata")
    nag = meta.get("cdk_nag") if isinstance(meta, dict) else None
    rules = nag.get("rules") if isinstance(nag, dict) else None
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            level = str(rule.get("level") or "warning").lower()
            findings.append({
                "rule_id": str(rule.get("id") or "cdk-nag"),
                "level": "error" if level in {"error", "critical", "high"} else "warning",
                "resource": logical or "Stack",
                "path": "template.json",
                "summary": " ".join(str(rule.get("info") or rule.get("explanation") or "").split()),
            })
    for key, child in node.items():
        if key == "Metadata":
            continue
        if isinstance(child, dict):
            walk(child, key if logical == "" else logical)
if proc.returncode == 0:
    for path in out.rglob("*"):
        if path.suffix not in {".json", ".yaml", ".yml"} or not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        before = len(findings)
        walk(loaded, "")
        if len(findings) != before:
            relative = path.name
            for item in findings[before:]:
                item["path"] = relative
text = (proc.stdout or "") + "\n" + (proc.stderr or "")
for line in text.splitlines():
    if " at /" not in line or "]" not in line:
        continue
    if line.startswith("[Error"):
        kind = "error"
    elif line.startswith("[Warning"):
        kind = "warning"
    else:
        kind = ""
    if not kind:
        continue
    body = line.split("]", 1)[-1].strip()
    rule_id = body.split(":", 1)[0].strip() or "cdk-nag"
    summary = body.split(":", 1)[-1].strip()
    findings.append({
        "rule_id": rule_id,
        "level": kind,
        "resource": "Stack",
        "path": "template.json",
        "summary": " ".join(summary.split()),
    })
print(json.dumps({
    "report_present": bool(findings),
    "synth_missing": False,
    "findings": findings,
}))
"""

_CHECKOV_WRAPPER = r"""
import json, shutil, subprocess, sys
from pathlib import Path
mode = sys.argv[1]
root = Path(sys.argv[2])
dest = Path(sys.argv[3])
if mode == "cdk":
    try:
        synth = subprocess.run(
            ["cdk", "synth", "--output", str(dest)],
            cwd=root, capture_output=True, text=True,
        )
    except FileNotFoundError:
        print("[]")
        raise SystemExit(0)
    if synth.returncode != 0:
        sys.stdout.write(synth.stdout or "")
        raise SystemExit(synth.returncode)
    scan = dest
else:
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.name.startswith(".checkov"):
            continue
        if path.suffix.lower() not in {".yaml", ".yml", ".json", ".template"}:
            continue
        target = dest / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    scan = dest
proc = subprocess.run(
    [
        "checkov", "--framework", "cloudformation", "-o", "json", "--compact",
        "--quiet", "--skip-download", "--soft-fail", "-d", str(scan),
    ],
    capture_output=True, text=True,
)
try:
    data = json.loads(proc.stdout or "[]")
except json.JSONDecodeError:
    sys.stdout.write(proc.stdout or "")
    raise SystemExit(proc.returncode)
prefix = str(scan).replace("\\", "/").rstrip("/") + "/"
root_prefix = str(root).replace("\\", "/").rstrip("/") + "/"

def rewrite(value):
    text = str(value or "").replace("\\", "/")
    if text.startswith(prefix):
        return text[len(prefix):]
    if text.startswith(root_prefix):
        return text[len(root_prefix):]
    if text.startswith("./"):
        return text[2:]
    return text

items = data if isinstance(data, list) else [data]
for item in items:
    if not isinstance(item, dict):
        continue
    results = item.get("results") if isinstance(item.get("results"), dict) else {}
    for check in results.get("failed_checks") or []:
        if isinstance(check, dict) and "file_path" in check:
            check["file_path"] = rewrite(check.get("file_path"))
sys.stdout.write(json.dumps(data))
raise SystemExit(0)
"""

_CFN_WRAPPER = r"""
import json, shutil, subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
dest = Path(sys.argv[2])
rels = []
for path in root.rglob("*"):
    if not path.is_file() or ".git" in path.parts:
        continue
    if path.name.startswith(".") and "cfnlint" in path.name:
        continue
    if path.suffix.lower() not in {".yaml", ".yml", ".json", ".template"}:
        continue
    rel = path.relative_to(root)
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    rels.append(rel.as_posix())
if not rels:
    print("[]")
    raise SystemExit(0)
proc = subprocess.run(
    ["cfn-lint", "--format", "json", *rels], cwd=dest, capture_output=True, text=True
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
    marker = "/.github/"
    if text.startswith("./"):
        text = text[2:]
    if marker in f"/{text}":
        return text
    return text[2:] if text.startswith("./") else text


def _invoke_cdk_nag(context: ScanContext) -> list[str]:
    if not (context.root / "cdk.json").is_file():
        return []
    out = context.home / "cdk-nag-out"
    out.mkdir(parents=True, exist_ok=True)
    return ["python3", "-c", _CDK_NAG_WRAPPER, str(context.root), str(out)]


def _parse_cdk_nag(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("cdk-nag output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("cdk-nag output must be an object")
    if data.get("synth_missing"):
        raise ToolGap("missing", _NAG_ROW)
    if not data.get("report_present"):
        raise ToolGap("known-gap", _NAG_ROW)
    hits: list[Hit] = []
    for item in data.get("findings") or []:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "warning").lower()
        row = _NAG_ROW if level == "error" else "security.workflow-infra-medium-low"
        rule_id = str(item.get("rule_id") or "cdk-nag")
        resource = str(item.get("resource") or "Stack")
        summary = " ".join(str(item.get("summary") or "").split())
        hits.append(Hit(
            rule_id=rule_id,
            path=_rel(str(item.get("path") or "template.json")),
            statement=f"{rule_id} {summary}".strip(),
            anchor=f"{resource} {rule_id}",
            whole_project=True,
            row=row,
            language="cloudformation",
        ))
    return ParseResult(tuple(hits))


def _invoke_checkov_cdk(context: ScanContext) -> list[str]:
    if not (context.root / "cdk.json").is_file():
        return []
    dest = context.home / "checkov-cdk"
    dest.mkdir(parents=True, exist_ok=True)
    return ["python3", "-c", _CHECKOV_WRAPPER, "cdk", str(context.root), str(dest)]


def _invoke_checkov_cfn(context: ScanContext) -> list[str]:
    dest = context.home / "checkov-cfn"
    dest.mkdir(parents=True, exist_ok=True)
    return ["python3", "-c", _CHECKOV_WRAPPER, "cfn", str(context.root), str(dest)]


def _parse_checkov(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("checkov output is not json") from exc
    if isinstance(data, dict):
        documents = [data]
    elif isinstance(data, list):
        documents = [item for item in data if isinstance(item, dict)]
    else:
        raise ValueError("checkov output must be an object")
    hits: list[Hit] = []
    for document in documents:
        results = document.get("results") if isinstance(document.get("results"), dict) else {}
        for check in results.get("failed_checks") or []:
            if not isinstance(check, dict):
                continue
            rule_id = str(check.get("check_id") or "checkov")
            raw_span = check.get("file_line_range")
            span = raw_span if isinstance(raw_span, list) else []
            start = span[0] if span and isinstance(span[0], int) else None
            end = span[1] if len(span) > 1 and isinstance(span[1], int) else start
            name = " ".join(str(check.get("check_name") or "").split())
            resource = str(check.get("resource") or "")
            hits.append(Hit(
                rule_id=rule_id,
                path=_rel(str(check.get("file_path") or ".")),
                statement=f"{rule_id} {name}".strip(),
                anchor=f"{rule_id} {resource}".strip(),
                start=start,
                end=end,
                language="cloudformation",
            ))
    return ParseResult(tuple(hits))


def _invoke_cfn_lint(context: ScanContext) -> list[str]:
    dest = context.home / "cfn-lint-src"
    dest.mkdir(parents=True, exist_ok=True)
    return ["python3", "-c", _CFN_WRAPPER, str(context.root), str(dest)]


def _cfn_level(rule_id: str, word: str) -> str:
    prefix = rule_id[:1].upper()
    if prefix == "E":
        return "error"
    if prefix == "W":
        return "warning"
    if prefix == "I":
        return "info"
    lowered = word.lower()
    if lowered in {"error", "warning", "info"}:
        return lowered
    return "warning"


def _parse_cfn_lint(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("cfn-lint output is not json") from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("cfn-lint output must be a list")
    hits: list[Hit] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        rule = item.get("Rule")
        if isinstance(rule, dict):
            rule_id = str(rule.get("Id") or "cfn-lint")
        else:
            rule_id = str(rule or item.get("Id") or "cfn-lint")
        location = item.get("Location") if isinstance(item.get("Location"), dict) else {}
        start_at = location.get("Start") if isinstance(location.get("Start"), dict) else {}
        end_at = location.get("End") if isinstance(location.get("End"), dict) else {}
        start = start_at.get("LineNumber")
        end = end_at.get("LineNumber") if isinstance(end_at.get("LineNumber"), int) else start
        message = " ".join(str(item.get("Message") or rule_id).split())
        hits.append(Hit(
            rule_id=rule_id,
            path=_rel(str(item.get("Filename") or ".")),
            statement=f"{rule_id} {message}",
            anchor=rule_id,
            level=_cfn_level(rule_id, str(item.get("Level") or "")),
            start=int(start) if isinstance(start, int) else None,
            end=int(end) if isinstance(end, int) else None,
            language="cloudformation",
        ))
    return ParseResult(tuple(hits))


def _from_row(
    row: Mapping[str, object],
    invoke: Callable[[ScanContext], list[str]],
    parse: Callable[[str], ParseResult],
    *,
    version_argv: tuple[str, ...] = (),
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
        type_checker=bool(row.get("type_checker")),
        mutation=bool(row.get("mutation")),
        mode=str(row.get("mode") or "report"),
        timeout_seconds=int(row.get("timeout_seconds") or 120),
        version_args=tuple(str(item) for item in (row.get("version_args") or ("--version",))),
        default_version=str(row.get("default_version") or "not-recorded"),
        curated_rules=tuple(str(item) for item in (row.get("curated_block_rules") or ())),
        version_argv=version_argv,
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
    invoke = {
        "cdk-nag": _invoke_cdk_nag,
        "checkov-cdk": _invoke_checkov_cdk,
        "checkov-cfn": _invoke_checkov_cfn,
        "cfn-lint": _invoke_cfn_lint,
    }
    parse = {
        "cdk-nag": _parse_cdk_nag,
        "checkov-cdk": _parse_checkov,
        "checkov-cfn": _parse_checkov,
        "cfn-lint": _parse_cfn_lint,
    }
    built = []
    for tool_id in _OWNED:
        if tool_id not in by_id:
            continue
        argv = _CDK_VERSION if tool_id == "cdk-nag" else ()
        built.append(_from_row(by_id[tool_id], invoke[tool_id], parse[tool_id], version_argv=argv))
    return built


ADAPTERS: tuple[Adapter, ...] = tuple(_build(_document()))
