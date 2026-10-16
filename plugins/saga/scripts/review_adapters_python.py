#!/usr/bin/env python3
"""Python review adapters, built from review-tools.yaml (issue 152).

Importing this module reads the yaml and builds adapter objects. It does not run a tool.
Settings come from the base commit or from a file this module writes under the runner home.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import yaml

import review_tools
from review_tools import Adapter, Hit, ParseResult, ScanContext, ToolGap

_OWNED = (
    "bandit",
    "pip-audit",
    "mypy",
    "ruff-lint",
    "ruff-format",
    "vulture",
    "import-linter",
    "cosmic-ray",
    "pytest-randomly",
    "pytest-socket",
)
_ROWS: dict[str, tuple[str, ...]] = {
    "bandit": ("security.scanner-high", "security.scanner-medium-low"),
    "pip-audit": ("security.dependency-high",),
    "mypy": ("correctness.type-error", "correctness.tool-style"),
    "ruff-lint": ("correctness.tool-error", "correctness.tool-warning", "correctness.tool-style"),
    "ruff-format": ("correctness.tool-style",),
    "vulture": ("architecture-maintainability.complexity-dead-code-naming",),
    "import-linter": ("architecture-maintainability.structural-check-fails",),
    "cosmic-ray": ("testing.surviving-mutant",),
    "pytest-randomly": ("testing.flaky-order-or-network",),
    "pytest-socket": ("testing.flaky-order-or-network",),
}
_VERSION_ARGV = {
    "pytest-randomly": (
        "python3", "-c",
        "import importlib.metadata as m; print(m.version('pytest-randomly'))",
    ),
    "pytest-socket": (
        "python3", "-c",
        "import importlib.metadata as m; print(m.version('pytest-socket'))",
    ),
}
_MYPY_LINE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?:(?P<col>\d+):)? "
    r"(?P<level>error|note|warning): (?P<message>.*)$"
)
_VULTURE_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<message>unused .+)$")
_CONTRACT_LINE = re.compile(r"^(.+?) (KEPT|BROKEN)$")
_CODE_SUFFIX = re.compile(r"\[([A-Za-z0-9_-]+)\]\s*$")

# Rewrites ruff's absolute filenames to paths relative to the scanned root.
_RUFF_WRAPPER = r"""
import json, subprocess, sys
argv = sys.argv[sys.argv.index("--") + 1:]
root = argv[-1].replace("\\", "/").rstrip("/")
proc = subprocess.run(argv, capture_output=True, text=True)
try:
    data = json.loads(proc.stdout or "[]")
except json.JSONDecodeError:
    sys.stdout.write(proc.stdout or "")
    raise SystemExit(proc.returncode)
prefix = root + "/"
if isinstance(data, list):
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("filename") or "").replace("\\", "/")
        if name.startswith(prefix):
            item["filename"] = name[len(prefix):]
        elif name.startswith("./"):
            item["filename"] = name[2:]
sys.stdout.write(json.dumps(data))
raise SystemExit(proc.returncode)
"""

# Copies Python files without a project config, then runs vulture from that copy.
_VULTURE_WRAPPER = r"""
import subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
dest = Path(sys.argv[2])
rels = sys.argv[3:]
for rel in rels:
    source = root / rel
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
if not rels:
    raise SystemExit(0)
proc = subprocess.run(["vulture", *rels], cwd=dest, capture_output=True, text=True)
sys.stdout.write(proc.stdout or "")
raise SystemExit(proc.returncode)
"""

# Shared per-run budget in seconds: the config's per-mutant timeout and the
# wrapper's baseline bound are the same value (issue 227). A suite slower than
# this fails the baseline instead of timing out per mutant into all-killed.
_COSMIC_TIMEOUT_SECONDS = 300

# Runs one cosmic-ray session: baseline first, then init, exec, dump. Reads the
# 8.7.0 dump as [work_item, result] arrays. Anything it cannot prove clean is
# unfinished. argv[2] overrides the baseline budget; tests use that, production
# passes _COSMIC_TIMEOUT_SECONDS.
_COSMIC_WRAPPER = r"""
import json, os, shlex, signal, subprocess, sys, tomllib
config = sys.argv[1]
try:
    budget = float(sys.argv[2])
except (IndexError, ValueError):
    budget = 300.0
if not budget > 0:
    budget = 300.0
def _done(unfinished, survivors):
    print(json.dumps({"unfinished": unfinished, "survivors": survivors}))
    raise SystemExit(0)
try:
    with open(config, "rb") as handle:
        test_command = tomllib.load(handle)["cosmic-ray"]["test-command"]
except (OSError, ValueError, KeyError):
    _done(True, [])
if not isinstance(test_command, str):
    _done(True, [])
try:
    proc = subprocess.Popen(
        shlex.split(test_command),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
except (OSError, ValueError):
    _done(True, [])
try:
    proc.communicate(timeout=budget)
except subprocess.TimeoutExpired:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (AttributeError, OSError):
        proc.kill()
    proc.communicate()
    _done(True, [])
if proc.returncode != 0:
    _done(True, [])
session = config + ".sqlite"
init = subprocess.run(["cosmic-ray", "init", config, session], capture_output=True, text=True)
if init.returncode != 0:
    _done(True, [])
# Skip every mutant off the change's lines; init alone queues whole files.
scoped = subprocess.run(
    ["cr-filter-git", session, "--config", config], capture_output=True, text=True
)
if scoped.returncode != 0:
    _done(True, [])
ran = subprocess.run(["cosmic-ray", "exec", config, session], capture_output=True, text=True)
dump = subprocess.run(
    ["cosmic-ray", "dump", session], capture_output=True, text=True
)
unfinished = ran.returncode != 0 or dump.returncode != 0
survivors = []
for line in (dump.stdout or "").splitlines():
    text = line.strip()
    if not text:
        continue
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        unfinished = True
        continue
    if not isinstance(row, list) or len(row) != 2:
        unfinished = True
        continue
    work, result = row
    if not isinstance(work, dict) or (result is not None and not isinstance(result, dict)):
        unfinished = True
        continue
    if result is None:
        unfinished = True
        continue
    if result.get("worker_outcome") == "skipped":
        # cr-filter-git skipped a mutant off the changed lines.
        continue
    if result.get("worker_outcome") != "normal":
        unfinished = True
    outcome = result.get("test_outcome")
    if outcome is None:
        unfinished = True
        continue
    lowered = str(outcome).lower()
    if lowered == "survived":
        mutations = work.get("mutations") or []
        first = mutations[0] if mutations else {}
        path = first.get("module_path") if isinstance(first, dict) else None
        start = first.get("start_pos") if isinstance(first, dict) else None
        number = start[0] if isinstance(start, (list, tuple)) and start else None
        if not path or not isinstance(number, int) or isinstance(number, bool):
            unfinished = True
            continue
        survivors.append({"path": str(path), "line": number})
    elif lowered != "killed":
        unfinished = True
_done(unfinished, survivors)
"""


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


def _py_rels(root: Path) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*.py"):
        if not path.is_file() or ".git" in path.parts:
            continue
        found.append(path.relative_to(root).as_posix())
    return sorted(found)


def _changed_python(context: ScanContext) -> list[str]:
    """Python files this review changed. cosmic-ray 8.7 reads one module-path string as one file."""
    if not context.base:
        return _py_rels(context.root)
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", context.base, "HEAD"],
        cwd=context.root, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return _py_rels(context.root)
    found = []
    for line in result.stdout.splitlines():
        rel = line.strip().replace("\\", "/")
        if rel.endswith(".py") and (context.root / rel).is_file():
            found.append(rel)
    return sorted(set(found))


def _toml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml(item) for item in values) + "]"


def _strip_randomly(argv: list[str]) -> list[str]:
    cleaned: list[str] = []
    index = 0
    while index < len(argv):
        part = argv[index]
        nxt = argv[index + 1] if index + 1 < len(argv) else ""
        if part == "-p" and nxt in {"randomly", "no:randomly"}:
            index += 2
            continue
        if part in {"-prandomly", "-pno:randomly"}:
            index += 1
            continue
        cleaned.append(part)
        index += 1
    return cleaned


def _resolve_python_head(parts: list[str]) -> list[str]:
    """Rewrite a bare python head to this interpreter (issue 227).

    A bare ``python`` resolves through PATH, which the temporary uv
    environment shadows with an interpreter that has no pytest. Every other
    head passes through: this adapter cannot know what ``make`` needs.
    """

    if parts and parts[0] in {"python", "python3"}:
        return [sys.executable, *parts[1:]]
    return parts


def _family_level(code: str, mapping: Mapping[str, str]) -> str:
    best = ""
    level = "warning"
    for prefix, mapped in mapping.items():
        if not code.startswith(prefix) or len(prefix) <= len(best):
            continue
        rest = code[len(prefix):]
        if rest and rest[0].isdigit():
            best = prefix
            level = mapped
    return level


def _invoke_bandit(context: ScanContext) -> list[str]:
    context.home.mkdir(parents=True, exist_ok=True)
    config = context.home / "bandit.toml"
    config.write_text("[tool.bandit]\nskips = []\n", encoding="utf-8")
    return [
        "bandit", "-f", "json", "-q", "--ignore-nosec",
        "-c", str(config), "-r", ".",
    ]


def _stable_bandit(text: str) -> str:
    """bandit's report without ``generated_at``, which differs on every run (issue 244)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        data.pop("generated_at", None)
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _parse_bandit(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("bandit output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("bandit output must be an object")
    hits: list[Hit] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("issue_severity") or "").upper()
        row = (
            "security.scanner-high" if severity == "HIGH" else "security.scanner-medium-low"
        )
        test_id = str(item.get("test_id") or "bandit")
        path = _rel(str(item.get("filename") or "."))
        summary = " ".join(str(item.get("issue_text") or "").split())
        start = item.get("line_number")
        line = int(start) if isinstance(start, int) else None
        hits.append(Hit(
            rule_id=test_id,
            path=path,
            statement=f"{test_id} {summary}".strip(),
            anchor=f"{test_id} {path}",
            start=line,
            end=line,
            row=row,
        ))
    return ParseResult(tuple(hits))


def _invoke_pip_audit(context: ScanContext) -> list[str]:
    files = [
        path.relative_to(context.root).as_posix()
        for path in context.root.rglob("requirements*.txt")
        if path.is_file() and ".git" not in path.parts
    ]
    if not files:
        return []
    argv = ["pip-audit", "--format", "json", "--progress-spinner", "off"]
    for name in sorted(files):
        argv.extend(["--requirement", name])
    return argv


def _parse_pip_audit(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("pip-audit output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("pip-audit output must be an object")
    hits: list[Hit] = []
    for dependency in data.get("dependencies") or []:
        if not isinstance(dependency, dict):
            continue
        for vuln in dependency.get("vulns") or []:
            if not isinstance(vuln, dict) or not vuln.get("id"):
                continue
            identifiers = [str(vuln["id"])]
            for alias in vuln.get("aliases") or []:
                if alias and str(alias) not in identifiers:
                    identifiers.append(str(alias))
            canonical = identifiers[0]
            hits.append(Hit(
                rule_id=canonical,
                path="requirements.txt",
                statement=f"Dependency advisory {canonical}.",
                anchor=canonical,
                advisory_ids=tuple(identifiers),
                score=None,
                whole_project=True,
                row="security.dependency-high",
            ))
    return ParseResult(tuple(hits))


def _mypy_config(context: ScanContext) -> Path:
    pyproject = _show(context.repo, context.base, "pyproject.toml")
    if pyproject and "[tool.mypy]" in pyproject:
        dest = context.home / "mypy-review.toml"
        dest.write_text(pyproject, encoding="utf-8")
        return dest
    for name in ("mypy.ini", ".mypy.ini"):
        text = _show(context.repo, context.base, name)
        if text:
            dest = context.home / "mypy-review.ini"
            dest.write_text(text, encoding="utf-8")
            return dest
    setup = _show(context.repo, context.base, "setup.cfg")
    if setup and "[mypy]" in setup:
        dest = context.home / "mypy-review.cfg"
        dest.write_text(setup, encoding="utf-8")
        return dest
    dest = context.home / "mypy-review.ini"
    dest.write_text("[mypy]\n", encoding="utf-8")
    return dest


def _invoke_mypy(context: ScanContext) -> list[str]:
    if not _py_rels(context.root):
        return []
    return [
        "mypy",
        "--config-file", str(_mypy_config(context)),
        "--show-column-numbers",
        "--hide-error-context",
        "--no-color-output",
        "--no-error-summary",
        "--no-pretty",
        "--follow-imports=silent",
        ".",
    ]


def _parse_mypy(text: str) -> ParseResult:
    hits: list[Hit] = []
    for raw in text.splitlines():
        match = _MYPY_LINE.match(raw.strip())
        if match is None:
            continue
        message = match.group("message").strip()
        code_match = _CODE_SUFFIX.search(message)
        code = code_match.group(1) if code_match else ""
        if code_match is not None:
            message = message[:code_match.start()].strip()
        word = match.group("level")
        row = "correctness.type-error" if word == "error" else None
        level = None if row else ("style" if word == "note" else word)
        line = int(match.group("line"))
        hits.append(Hit(
            rule_id=code or "mypy",
            path=_rel(match.group("path")),
            statement=message or "mypy reported a finding.",
            anchor=f"{code} {message}".strip(),
            level=level,
            start=line,
            end=line,
            row=row,
        ))
    return ParseResult(tuple(hits))


def _invoke_ruff(pin: str) -> Callable[[ScanContext], list[str]]:
    """Ruff at the row pin through uv, whatever PATH holds (issue 226)."""

    def invoke(context: ScanContext) -> list[str]:
        return [
            "python3", "-c", _RUFF_WRAPPER, "--",
            "uv", "run", "--with", f"ruff=={pin}",
            "ruff", "check", "--isolated", "--ignore-noqa", "--select", "ALL",
            "--output-format", "json", str(context.root),
        ]

    return invoke


def _parse_ruff(mapping: Mapping[str, str]) -> Callable[[str], ParseResult]:
    def parse(text: str) -> ParseResult:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("ruff output is not json") from exc
        if isinstance(data, dict):
            data = data.get("diagnostics") or data.get("results") or []
        if not isinstance(data, list):
            raise ValueError("ruff output must be a list")
        hits: list[Hit] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "ruff")
            location = item.get("location") if isinstance(item.get("location"), dict) else {}
            end = item.get("end_location") if isinstance(item.get("end_location"), dict) else {}
            start = location.get("row")
            stop = end.get("row") if isinstance(end.get("row"), int) else start
            message = " ".join(str(item.get("message") or code).split())
            hits.append(Hit(
                rule_id=code,
                path=_rel(str(item.get("filename") or ".")),
                statement=f"{code} {message}",
                anchor=code,
                level=_family_level(code, mapping),
                start=int(start) if isinstance(start, int) else None,
                end=int(stop) if isinstance(stop, int) else None,
            ))
        return ParseResult(tuple(hits))

    return parse


def _invoke_vulture(context: ScanContext) -> list[str]:
    files = _py_rels(context.root)
    if not files:
        return []
    dest = context.home / "vulture-src"
    dest.mkdir(parents=True, exist_ok=True)
    return ["python3", "-c", _VULTURE_WRAPPER, str(context.root), str(dest), *files]


def _parse_vulture(text: str) -> ParseResult:
    hits: list[Hit] = []
    for raw in text.splitlines():
        match = _VULTURE_LINE.match(raw.strip())
        if match is None:
            continue
        line = int(match.group("line"))
        message = " ".join(match.group("message").split())
        hits.append(Hit(
            rule_id="vulture",
            path=_rel(match.group("path")),
            statement=message,
            anchor=message,
            start=line,
            end=line,
            row="architecture-maintainability.complexity-dead-code-naming",
        ))
    return ParseResult(tuple(hits))


def _invoke_import_linter(context: ScanContext) -> list[str]:
    text = _show(context.repo, context.base, ".importlinter")
    if text is None:
        pyproject = _show(context.repo, context.base, "pyproject.toml") or ""
        if "[tool.importlinter]" not in pyproject:
            return []
        text = pyproject
    dest = context.home / "import-linter.cfg"
    dest.write_text(text, encoding="utf-8")
    return ["lint-imports", "--config", str(dest)]


def _parse_import_linter(text: str) -> ParseResult:
    hits: list[Hit] = []
    for raw in text.splitlines():
        match = _CONTRACT_LINE.match(raw.strip())
        if match is None or match.group(2) != "BROKEN":
            continue
        name = " ".join(match.group(1).split())
        hits.append(Hit(
            rule_id=name,
            path=".",
            statement=f"Import contract {name} is broken.",
            anchor=name,
            whole_project=True,
            row="architecture-maintainability.structural-check-fails",
        ))
    return ParseResult(tuple(hits))


def _invoke_cosmic(context: ScanContext) -> list[str]:
    command = context.test_command.strip()
    if not command:
        raise ToolGap("known-gap", "testing.surviving-mutant")
    parts = _resolve_python_head([*_strip_randomly(shlex.split(command)), "-p", "no:randomly"])
    modules = _changed_python(context)
    if not modules:
        return []
    toml = context.home / "cosmic-ray.toml"
    toml.write_text(
        "\n".join([
            "[cosmic-ray]",
            f"module-path = {_toml_list(modules)}",
            f"timeout = {float(_COSMIC_TIMEOUT_SECONDS)}",
            "excluded-modules = []",
            f"test-command = {_toml(shlex.join(parts))}",
            "",
            "[cosmic-ray.distributor]",
            'name = "local"',
            "",
            "[cosmic-ray.filters.git-filter]",
            f"branch = {_toml(context.base)}",
            "",
        ]),
        encoding="utf-8",
    )
    return [
        "uv", "run", "--with", "cosmic-ray==8.7.0",
        sys.executable, "-c", _COSMIC_WRAPPER, str(toml), str(_COSMIC_TIMEOUT_SECONDS),
    ]


def _parse_cosmic(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("cosmic-ray output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("cosmic-ray output must be an object")
    hits: list[Hit] = []
    for item in data.get("survivors") or []:
        if not isinstance(item, dict):
            continue
        line = item.get("line")
        start = int(line) if isinstance(line, int) else None
        path = _rel(str(item.get("path") or "."))
        hits.append(Hit(
            rule_id="surviving-mutant",
            path=path,
            statement="A mutant survived.",
            anchor=f"{path}:{start or 0}",
            start=start,
            end=start,
            row="testing.surviving-mutant",
        ))
    return ParseResult(tuple(hits), unfinished=bool(data.get("unfinished")))


def _pytest_argv(context: ScanContext, package: str, extra: list[str]) -> list[str]:
    command = context.test_command.strip()
    if not command:
        raise ToolGap("known-gap", "testing.flaky-order-or-network")
    parts = _resolve_python_head(_strip_randomly(shlex.split(command)))
    return ["uv", "run", "--with", package, *parts, *extra]


def _invoke_randomly(context: ScanContext) -> list[str]:
    # The seed is fixed by the change, so two runs of one change test one order.
    return _pytest_argv(
        context, "pytest-randomly==5.0.0",
        ["-p", "randomly", f"--randomly-seed={review_tools.change_seed(context)}"],
    )


def _invoke_socket(context: ScanContext) -> list[str]:
    return _pytest_argv(
        context, "pytest-socket==0.8.1", ["-p", "no:randomly", "--disable-socket"]
    )


def _parse_pytest(text: str) -> ParseResult:
    hits: list[Hit] = []
    for raw in text.splitlines():
        if not raw.startswith("FAILED "):
            continue
        node = raw[len("FAILED "):].split(" - ", 1)[0].strip()
        path = node.split("::", 1)[0] or "."
        hits.append(Hit(
            rule_id=node,
            path=path,
            statement=f"Test failed: {node}",
            anchor=node,
            whole_project=True,
            row="testing.flaky-order-or-network",
        ))
    return ParseResult(tuple(hits))


def _invoke_nothing(_context: ScanContext) -> list[str]:
    return []


def _parse_nothing(_text: str) -> ParseResult:
    return ParseResult()


def _level_map(row: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    mapping = row.get("level_map") or {}
    if not isinstance(mapping, dict):
        return ()
    return tuple((str(key), str(value)) for key, value in mapping.items())


def _from_row(
    row: Mapping[str, object],
    invoke: Callable[[ScanContext], list[str]],
    parse: Callable[[str], ParseResult],
    *,
    version_argv: tuple[str, ...] = (),
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
        type_checker=bool(row.get("type_checker")),
        mutation=bool(row.get("mutation")),
        mode=str(row.get("mode") or "report"),
        timeout_seconds=int(row.get("timeout_seconds") or 120),
        version_args=tuple(str(item) for item in (row.get("version_args") or ("--version",))),
        default_version=str(row.get("default_version") or "not-recorded"),
        curated_rules=tuple(str(item) for item in (row.get("curated_block_rules") or ())),
        level_map=_level_map(row),
        version_argv=version_argv,
        narrow_env=bool(row.get("narrow_env")),
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
    ruff_row = by_id.get("ruff-lint") or {}
    family = ruff_row.get("family_map") if isinstance(ruff_row, dict) else {}
    mapping = (
        {str(key): str(value) for key, value in family.items()}
        if isinstance(family, dict) else {}
    )
    ruff_pin = str(ruff_row.get("default_version") or "not-recorded")
    version_argvs = dict(_VERSION_ARGV)
    version_argvs["ruff-lint"] = (
        "uv", "run", "--with", f"ruff=={ruff_pin}", "ruff", "--version",
    )
    invoke = {
        "bandit": _invoke_bandit,
        "pip-audit": _invoke_pip_audit,
        "mypy": _invoke_mypy,
        "ruff-lint": _invoke_ruff(ruff_pin),
        "ruff-format": _invoke_nothing,
        "vulture": _invoke_vulture,
        "import-linter": _invoke_import_linter,
        "cosmic-ray": _invoke_cosmic,
        "pytest-randomly": _invoke_randomly,
        "pytest-socket": _invoke_socket,
    }
    parse = {
        "bandit": _parse_bandit,
        "pip-audit": _parse_pip_audit,
        "mypy": _parse_mypy,
        "ruff-lint": _parse_ruff(mapping),
        "ruff-format": _parse_nothing,
        "vulture": _parse_vulture,
        "import-linter": _parse_import_linter,
        "cosmic-ray": _parse_cosmic,
        "pytest-randomly": _parse_pytest,
        "pytest-socket": _parse_pytest,
    }
    return [
        _from_row(
            by_id[tool_id],
            invoke[tool_id],
            parse[tool_id],
            version_argv=version_argvs.get(tool_id, ()),
            stable_raw=_stable_bandit if tool_id == "bandit" else None,
        )
        for tool_id in _OWNED
        if tool_id in by_id
    ]


ADAPTERS: tuple[Adapter, ...] = tuple(_build(_document()))
