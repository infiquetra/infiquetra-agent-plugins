#!/usr/bin/env python3
"""TypeScript review adapters, built from review-tools.yaml (issue 153).

Importing this module reads the yaml and builds adapter objects. It does not run a tool.
"""

from __future__ import annotations

import json
import os
import random
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

import review_formula
import review_tools
from review_tools import Adapter, Hit, ParseResult, RulePin, ScanContext, ToolGap

_TS_MARKER_NAMES = frozenset({
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
})
_NPM_LOCKS = ("package-lock.json", "npm-shrinkwrap.json")
_TS_SUFFIXES = (".ts", ".tsx", ".mts", ".cts")
_LINT_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
_PRUNE_DIRS = frozenset({".git", "node_modules"})
_ESLINT_CONFIGS = (
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json",
    ".eslintrc.yml", ".eslintrc.yaml",
)
_STRYKER_CONFIGS = (
    "stryker.conf.json", "stryker.conf.js", "stryker.conf.mjs", "stryker.conf.cjs",
)
_VITEST_CONFIGS = (
    "vitest.config.ts", "vitest.config.js", "vitest.config.mjs", "vitest.config.cjs",
    "vitest.config.mts", "vitest.config.cts",
    "vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.cjs",
    "vite.config.mts", "vite.config.cts",
)
_JEST_CONFIGS = (
    "jest.config.ts", "jest.config.js", "jest.config.mjs", "jest.config.cjs",
    "jest.config.json",
)
_BABEL_CONFIGS = (
    "babel.config.js", "babel.config.cjs", "babel.config.mjs", "babel.config.json",
    ".babelrc", ".babelrc.js", ".babelrc.json",
)
_KNIP_CONFIGS = (
    "knip.json", "knip.jsonc", ".knip.json", ".knip.jsonc",
    "knip.js", "knip.ts", "knip.config.js", "knip.config.ts",
)
_DEPCRUISE_CONFIGS = (
    ".dependency-cruiser.js", ".dependency-cruiser.cjs", ".dependency-cruiser.mjs",
    ".dependency-cruiser.json", "dependency-cruiser.config.js",
)
_ESLINT_RECOMMENDED = "eslint-recommended.eslint-config"
_TSCONFIG_NAMES = ("tsconfig.json", "tsconfig.app.json")
_SAGA_TSCONFIG = "tsconfig.saga.json"
_TSC_DEFAULTS = {
    "target": "es2020",
    "module": "commonjs",
    "moduleResolution": "node",
    "jsx": "react-jsx",
}
_ADVISORY_ID = re.compile(r"(GHSA-[0-9a-z]{4}(?:-[0-9a-z]{4}){2}|CVE-\d{4}-\d{4,})", re.IGNORECASE)
_TSC_LINE = re.compile(r"^(.+?)\((\d+),\s*(\d+)\):\s+error\s+(TS\d+):\s+(.*)$")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_VITEST_SEED = re.compile(r'Running tests with seed "(\d+)"')
_VITEST_FAIL = re.compile(r"^\s*FAIL\s+(\S+?)(?:\s*>\s*(.+))?\s*$", re.MULTILINE)
_VITEST_SUMMARY = re.compile(r"(?:Tests|Test Files)\s+(\d+)\s+failed")
_JEST_SEED = re.compile(r"^Seed:\s+(-?\d+)\s*$", re.MULTILINE)
_JEST_FAIL = re.compile(r"^FAIL\s+(\S+)\s*$", re.MULTILINE)
_JEST_CASE = re.compile(r"^\s*●\s*(.+?)\s*$", re.MULTILINE)
_JEST_TESTS = re.compile(r"^Tests:\s+(?:(\d+)\s+failed)?.*$", re.MULTILINE)
_JEST_SUITES = re.compile(r"^Test Suites:\s+(?:(\d+)\s+failed)?.*$", re.MULTILINE)

_ROWS: dict[str, tuple[str, ...]] = {
    "npm-audit": ("security.dependency-high", "security.dependency-medium-low"),
    "tsc": ("correctness.type-error",),
    "eslint": ("correctness.tool-error", "correctness.tool-warning"),
    "stryker": ("testing.surviving-mutant",),
    "vitest-shuffle": ("testing.flaky-order-or-network",),
    "jest-shuffle": ("testing.flaky-order-or-network",),
    "knip": ("architecture-maintainability.complexity-dead-code-naming",),
    "dependency-cruiser": ("architecture-maintainability.structural-check-fails",),
    "prettier": (),
    "typescript-no-network": ("testing.flaky-order-or-network",),
    "vitest-coverage": ("testing.uncovered-branch",),
    "jest-coverage": ("testing.uncovered-branch",),
}


def _document() -> dict[str, object]:
    loaded = yaml.safe_load(review_tools.TOOL_LIST.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise review_tools.RunnerFailure(2, "review-tools.yaml must be an object")
    return loaded


def _walk(root: Path) -> list[Path]:
    """Files under ``root`` with caches and env trees pruned."""
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        for pruned in [name for name in dirnames if name in _PRUNE_DIRS or name == ".git"]:
            dirnames.remove(pruned)
        for name in filenames:
            found.append(Path(directory) / name)
    return found


def _has_markers(root: Path) -> bool:
    for path in _walk(root):
        if path.name in _TS_MARKER_NAMES or path.name.startswith("tsconfig."):
            return True
    return False


def _files_with(root: Path, suffixes: tuple[str, ...]) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in _walk(root)
        if path.suffix in suffixes
    )


def _base_file(context: ScanContext, name: str) -> Path | None:
    for staged_name, staged_path in context.base_files:
        if staged_name == name:
            return staged_path
    return None


def _base_json(context: ScanContext, name: str) -> dict[str, object]:
    staged = _base_file(context, name)
    if staged is None:
        return {}
    try:
        data = json.loads(staged.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stage_base(context: ScanContext, name: str, dest: str | None = None) -> Path | None:
    """Copy the staged base file over the stripped name in the scan tree."""
    staged = _base_file(context, name)
    if staged is None:
        return None
    target = context.root / (dest or name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(staged.read_bytes())
    return target


def _stage_first_base(context: ScanContext, names: tuple[str, ...]) -> Path | None:
    for name in names:
        staged = _stage_base(context, name)
        if staged is not None:
            return staged
    return None


_JS_CONFIG_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts")
_RELATIVE_IMPORT = re.compile(
    r"(?:from\s+|import\s+|require\s*\(|import\s*\()\s*['\"]\.[./]"
)


def _refuse_relative_imports(staged: Path | None, row: str) -> None:
    """Decline a base config that imports a project-relative file.

    The staged copy runs in the scanned tree, so a relative import resolves
    to that tree's file, which the reviewed commit controls. Raw text on
    purpose: stripping comments could hide a real import inside a string,
    while a comment shaped like an import degrades in the safe direction.
    """
    if staged is None or staged.suffix not in _JS_CONFIG_SUFFIXES:
        return
    try:
        text = staged.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if _RELATIVE_IMPORT.search(text):
        raise ToolGap("config-imports-head", row)


_NPMRC_SECRET_LINE = re.compile(
    r"(?i)^\s*(?://[^=\s]*)?\s*(_authtoken|_auth|_password|username)\s*="
)


def _stage_npmrc(context: ScanContext) -> Path | None:
    """Stage the base ``.npmrc`` without auth lines.

    Auth tokens in the base commit must not be sent to a registry by the
    audit. A private registry that needed them fails into a degraded input.
    Proxy URLs are left alone: even a fake credential inside one trips the
    repository's own credential gate, which has no placeholder exemption.
    """
    staged = _base_file(context, ".npmrc")
    if staged is None:
        return None
    try:
        text = staged.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    kept = [
        line for line in text.splitlines() if not _NPMRC_SECRET_LINE.match(line)
    ]
    target = context.root / ".npmrc"
    target.write_bytes(("".join(f"{line}\n" for line in kept)).encode("utf-8"))
    return target


def _stage_tsconfig(context: ScanContext) -> None:
    """Stage the base tsconfig so tools that read it see base options, never head's."""
    _stage_first_base(context, ("tsconfig.json",))


def _declared_dependencies(context: ScanContext) -> bool:
    package = _base_json(context, "package.json")
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = package.get(key)
        if isinstance(value, dict) and value:
            return True
    return False


def _runner_choice(context: ScanContext) -> str | None:
    """vitest, jest or None from the base package manifest. Config breaks ties."""
    package = _base_json(context, "package.json")
    deps: dict[str, object] = {}
    for key in ("dependencies", "devDependencies"):
        value = package.get(key)
        if isinstance(value, dict):
            deps.update(value)
    vitest = "vitest" in deps
    jest = "jest" in deps
    if vitest and not jest:
        return "vitest"
    if jest and not vitest:
        return "jest"
    if not vitest:
        return None
    for name, _ in context.base_files:
        if name.startswith("vitest.config.") or name.startswith("vite.config."):
            return "vitest"
        if name.startswith("jest.config."):
            return "jest"
    return "vitest"


def _invoke_npm_audit(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    if not any((context.root / name).is_file() for name in _NPM_LOCKS):
        return []
    _stage_npmrc(context)
    return ["npm", "audit", "--json"]


def _npm_row(severity: object) -> str:
    word = str(severity or "").lower()
    if word in ("critical", "high"):
        return "security.dependency-high"
    if word in ("moderate", "low", "info"):
        return "security.dependency-medium-low"
    return "security.dependency-high"


def _parse_npm_audit(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("npm audit output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("npm audit output must be an object")
    found = data.get("vulnerabilities") or {}
    if not isinstance(found, dict):
        raise ValueError("npm audit vulnerabilities must be an object")
    hits: list[Hit] = []
    for name, entry in found.items():
        if not isinstance(entry, dict):
            continue
        identifiers: list[str] = []
        score: float | None = None
        via = entry.get("via") or []
        items = via if isinstance(via, list) else []
        for item in items:
            url = item.get("url") if isinstance(item, dict) else None
            if isinstance(url, str):
                for match in _ADVISORY_ID.findall(url):
                    ident = match.upper()
                    if ident not in identifiers:
                        identifiers.append(ident)
            if isinstance(item, dict):
                cvss = item.get("cvss")
                if isinstance(cvss, dict):
                    value = cvss.get("score")
                    if isinstance(value, bool):
                        pass
                    elif isinstance(value, (int, float)):
                        score = float(value) if score is None else max(score, float(value))
        canonical = identifiers[0] if identifiers else str(name)
        severity = entry.get("severity")
        level = str(severity or "unrated")
        hits.append(Hit(
            rule_id=canonical,
            path="package-lock.json",
            statement=f"npm audit reports a {level} advisory {canonical} in {name}.",
            anchor=f"{canonical} {name}",
            advisory_ids=tuple(identifiers),
            score=score,
            row=_npm_row(severity),
            whole_project=True,
        ))
    return ParseResult(tuple(hits))


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments outside string literals."""
    out: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and following == "/":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue
        if char == "/" and following == "*":
            index += 2
            while index + 1 < len(text) and text[index:index + 2] != "*/":
                index += 1
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _merge_options(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        if (
            key == "compilerOptions"
            and isinstance(merged.get(key), dict)
            and isinstance(value, dict)
        ):
            merged[key] = {**merged[key], **value}  # type: ignore[dict-item]
        else:
            merged[key] = value
    return merged


def _base_compiler_options(
    context: ScanContext,
) -> tuple[dict[str, object], str | None]:
    """Inline-merged base compilerOptions, or the pinned defaults.

    Returns the options and the base tsconfig name they came from (None for the
    defaults). Node-module extends resolve in the scan tree's lockfile-gated
    node_modules; relative extends cannot reach the base tree and decline.
    """
    name: str | None = None
    staged: Path | None = None
    for candidate in _TSCONFIG_NAMES:
        staged = _base_file(context, candidate)
        if staged is not None:
            name = candidate
            break
    if staged is None or name is None:
        return dict(_TSC_DEFAULTS), None
    try:
        raw = _strip_jsonc(staged.read_text(encoding="utf-8-sig"))
        data = json.loads(raw)
    except (OSError, ValueError):
        raise ToolGap("config-unresolved", "correctness.type-error")
    if not isinstance(data, dict):
        raise ToolGap("config-unresolved", "correctness.type-error")
    chain: list[object] = []
    extends = data.get("extends")
    if isinstance(extends, (str, list)):
        chain = [extends] if isinstance(extends, str) else list(extends)
    merged: dict[str, object] = {}
    for link in chain:
        if not isinstance(link, str) or link.startswith("."):
            raise ToolGap("config-unresolved", "correctness.type-error")
        target = context.root / "node_modules" / f"{link}.json"
        package_dir = context.root / "node_modules" / link
        if package_dir.is_dir():
            target = package_dir / "tsconfig.json"
        try:
            parent = json.loads(_strip_jsonc(target.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            raise ToolGap("config-unresolved", "correctness.type-error") from None
        if not isinstance(parent, dict):
            raise ToolGap("config-unresolved", "correctness.type-error")
        merged = _merge_options(merged, parent)
    merged = _merge_options(merged, data)
    options = merged.get("compilerOptions")
    if not isinstance(options, dict):
        return dict(_TSC_DEFAULTS), name
    return {str(key): value for key, value in options.items()}, name


def _stage_saga_tsconfig(context: ScanContext, files: list[str]) -> Path:
    options, _ = _base_compiler_options(context)
    # The staged file sits at the scan root, so relative baseUrl/typeRoots keep
    # their values and resolve onto the scanned tree.
    rebased: dict[str, object] = dict(options)
    rebased.update({"strict": True, "noEmit": True, "composite": False, "incremental": False})
    staged = {
        "compilerOptions": rebased,
        "files": files,
        "include": [],
        "exclude": [],
    }
    target = context.root / _SAGA_TSCONFIG
    target.write_text(json.dumps(staged, indent=2) + "\n", encoding="utf-8")
    return target


def _invoke_tsc(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    files = _files_with(context.root, _TS_SUFFIXES)
    if not files:
        return []
    if not (context.root / "node_modules").is_dir() and _declared_dependencies(context):
        raise ToolGap("deps-missing", "correctness.type-error")
    staged = _stage_saga_tsconfig(context, files)
    return ["tsc", "-p", staged.relative_to(context.root).as_posix()]


def _parse_tsc(text: str) -> ParseResult:
    hits: list[Hit] = []
    for line in text.splitlines():
        match = _TSC_LINE.match(line.strip())
        if match is None:
            continue
        path, line_no, _col, code, message = match.groups()
        start = int(line_no)
        hits.append(Hit(
            rule_id=code,
            path=path,
            statement=f"TypeScript {code}: {message.strip()}",
            anchor=f"{code}: {message.strip()}",
            start=start,
            end=start,
            row="correctness.type-error",
            whole_project=True,
        ))
    return ParseResult(tuple(hits))


def _invoke_eslint(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    if not _files_with(context.root, _LINT_SUFFIXES):
        return []
    _stage_tsconfig(context)
    staged = _stage_first_base(context, _ESLINT_CONFIGS)
    if staged is None:
        template = review_tools.TOOL_LIST.parent / _ESLINT_RECOMMENDED
        try:
            text = template.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolGap("config-unresolved", "correctness.tool-error") from exc
        staged = context.root / "eslint.config.mjs"
        staged.write_text(text, encoding="utf-8")
    _refuse_relative_imports(staged, "correctness.tool-error")
    return [
        "eslint", "--format", "json", "--config", str(staged), str(context.root),
    ]


def _parse_eslint(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("eslint output is not json") from exc
    if not isinstance(data, list):
        raise ValueError("eslint output must be a list")
    hits: list[Hit] = []
    for result in data:
        if not isinstance(result, dict):
            continue
        path = str(result.get("filePath") or ".")
        messages = result.get("messages") or []
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            severity = message.get("severity")
            level = "error" if severity == 2 else "warning" if severity == 1 else None
            if level is None:
                continue
            rule = str(message.get("ruleId") or "fatal")
            body = str(message.get("message") or rule)
            try:
                start = int(message.get("line") or 0) or None
            except (TypeError, ValueError):
                start = None
            try:
                end = int(message.get("endLine") or 0) or None
            except (TypeError, ValueError):
                end = None
            hits.append(Hit(
                rule_id=rule,
                path=path,
                statement=f"ESLint {rule}: {body}",
                anchor=f"{rule}: {body}",
                start=start,
                end=end or start,
                level=level,
            ))
    return ParseResult(tuple(hits))


_STRYKER_MUTATE = ("**/*.+(ts|js|mts|cts|tsx|jsx)",)
_STRYKER_IGNORE = (
    "**/*.spec.*", "**/*.test.*", "**/__tests__/**", "**/test/**", "**/tests/**",
)


def _invoke_stryker(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    runner = _runner_choice(context)
    if runner is None:
        raise ToolGap("not-configured", "testing.surviving-mutant")
    _stage_tsconfig(context)
    argv = ["stryker", "run", "--testRunner", runner, "--reporters", "json"]
    staged = _stage_first_base(context, _STRYKER_CONFIGS)
    _refuse_relative_imports(staged, "testing.surviving-mutant")
    if staged is None:
        for pattern in _STRYKER_MUTATE:
            argv.extend(["--mutate", pattern])
        for pattern in _STRYKER_IGNORE:
            argv.extend(["--ignorePatterns", pattern])
    return argv


def _parse_stryker(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("stryker report is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("stryker report must be an object")
    files = data.get("files") or {}
    if not isinstance(files, dict):
        raise ValueError("stryker report files must be an object")
    hits: list[Hit] = []
    for path, entry in files.items():
        if not isinstance(entry, dict):
            continue
        seen: dict[str, int] = {}
        for mutant in entry.get("mutants") or []:
            if not isinstance(mutant, dict):
                continue
            if str(mutant.get("status") or "") != "Survived":
                continue
            mutator = str(mutant.get("mutatorName") or "mutant")
            location = mutant.get("location") or {}
            start_map = location.get("start") if isinstance(location, dict) else None
            end_map = location.get("end") if isinstance(location, dict) else None
            try:
                start = int((start_map or {}).get("line") or 0) or None
            except (TypeError, ValueError):
                start = None
            try:
                end = int((end_map or {}).get("line") or 0) or None
            except (TypeError, ValueError):
                end = None
            seen[mutator] = seen.get(mutator, 0) + 1
            hits.append(Hit(
                rule_id="surviving-mutant",
                path=str(path),
                statement=f"StrykerJS mutant survived: {mutator} in {path}.",
                anchor=f"{mutator}:{seen[mutator]}",
                start=start,
                end=end or start,
                row="testing.surviving-mutant",
            ))
    return ParseResult(tuple(hits))


def _shuffle_seed() -> int:
    return random.randint(1, 2**31 - 1)


def _invoke_vitest_shuffle(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    if _runner_choice(context) != "vitest":
        return []
    _stage_tsconfig(context)
    staged = _stage_first_base(context, _VITEST_CONFIGS)
    _refuse_relative_imports(staged, "testing.flaky-order-or-network")
    return [
        "vitest", "run", "--sequence.shuffle",
        "--sequence.seed", str(_shuffle_seed()),
    ]


def _parse_vitest_shuffle(text: str) -> ParseResult:
    plain = _ANSI.sub("", text)
    if "No test files found" in plain:
        return ParseResult((), gap=("no-tests-ran", "testing.flaky-order-or-network"))
    seed_match = _VITEST_SEED.search(plain)
    seed = seed_match.group(1) if seed_match else "unreported"
    failed = any(
        int(count) > 0 for count in _VITEST_SUMMARY.findall(plain)
    ) or "Failed Tests" in plain
    failures: dict[tuple[str, str | None], None] = {}
    for match in _VITEST_FAIL.finditer(plain):
        path, case = match.group(1), match.group(2)
        failures[(path.strip(), case.strip() if case else None)] = None
    if not failed or not failures:
        if not failed:
            return ParseResult(())
        failures[(".", None)] = None
    row = "testing.flaky-order-or-network"
    return ParseResult(tuple(
        Hit(
            rule_id="shuffle-failure",
            path=path,
            statement=(
                f"Vitest {'test ' + case + ' ' if case else 'run '}failed "
                f"in random order (seed {seed})."
            ),
            anchor=f"{path} :: {case or 'suite'}",
            row=row,
            whole_project=True,
        )
        for path, case in failures
    ))


def _invoke_jest_shuffle(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    if _runner_choice(context) != "jest":
        return []
    _stage_tsconfig(context)
    babel = _stage_first_base(context, _BABEL_CONFIGS)
    _refuse_relative_imports(babel, "testing.flaky-order-or-network")
    _stage_first_base(context, (".swcrc", ".swcrc.json"))
    staged = _stage_first_base(context, _JEST_CONFIGS)
    _refuse_relative_imports(staged, "testing.flaky-order-or-network")
    argv = ["jest", "--randomize", "--seed", str(_shuffle_seed()), "--showSeed"]
    if staged is None:
        package = _base_json(context, "package.json")
        key = package.get("jest")
        if isinstance(key, dict):
            staged = context.root / "jest.config.saga.json"
            staged.write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    if staged is not None:
        argv.extend(["--config", str(staged)])
    elif _files_with(context.root, (".ts", ".tsx", ".mts", ".cts")):
        raise ToolGap("not-configured", "testing.flaky-order-or-network")
    return argv


def _parse_jest_shuffle(text: str) -> ParseResult:
    plain = _ANSI.sub("", text)
    if "No tests found" in plain:
        return ParseResult((), gap=("no-tests-ran", "testing.flaky-order-or-network"))
    seed_match = _JEST_SEED.search(plain)
    seed = seed_match.group(1) if seed_match else "unreported"
    tests_failed = any(count and int(count) > 0 for count in _JEST_TESTS.findall(plain))
    suites_failed = any(count and int(count) > 0 for count in _JEST_SUITES.findall(plain))
    if not tests_failed and not suites_failed:
        return ParseResult(())
    current: str | None = None
    failures: dict[tuple[str, str | None], None] = {}
    for line in plain.splitlines():
        fail = _JEST_FAIL.match(line)
        if fail:
            current = fail.group(1).strip()
            continue
        case = _JEST_CASE.match(line)
        if case and current is not None:
            name = case.group(1).strip()
            if name == "Test suite failed to run":
                failures[(current, None)] = None
            else:
                failures[(current, name)] = None
    if not failures:
        failures[(".", None)] = None
    row = "testing.flaky-order-or-network"
    return ParseResult(tuple(
        Hit(
            rule_id="shuffle-failure",
            path=path,
            statement=(
                f"Jest {'test ' + case + ' ' if case else 'suite '}failed "
                f"in random order (seed {seed})."
            ),
            anchor=f"{path} :: {case or 'suite'}",
            row=row,
            whole_project=True,
        )
        for path, case in failures
    ))


def _invoke_knip(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    _stage_tsconfig(context)
    staged = _stage_first_base(context, _KNIP_CONFIGS)
    _refuse_relative_imports(
        staged, "architecture-maintainability.complexity-dead-code-naming"
    )
    if staged is None:
        package = _base_json(context, "package.json")
        key = package.get("knip")
        if isinstance(key, dict):
            staged = context.root / "knip.saga.json"
            staged.write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
        else:
            staged = context.root / "knip.saga.json"
            staged.write_text("{}\n", encoding="utf-8")
    return ["knip", "--reporter", "json", "--config", str(staged)]


def _knip_name(item: object, fallback: str) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("name") or fallback)
    return fallback


def _knip_entries(issue: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """(kind, display, anchor) triples for one knip issue entry."""
    found: list[tuple[str, str, str]] = []
    path = str(issue.get("file") or ".")
    files = issue.get("files") or []
    for name in files if isinstance(files, list) else []:
        label = _knip_name(name, path)
        found.append(("file", label, f"{path} :: file"))
    for group, kind in (("exports", "export"), ("types", "type")):
        items = issue.get(group) or []
        for item in items if isinstance(items, list) else []:
            label = _knip_name(item, kind)
            found.append((kind, f"{label} in {path}", f"{path} :: {kind} {label}"))
    return found


def _parse_knip(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("knip output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("knip output must be an object")
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        raise ValueError("knip issues must be a list")
    row = "architecture-maintainability.complexity-dead-code-naming"
    hits: list[Hit] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        path = str(issue.get("file") or ".")
        for kind, display, anchor in _knip_entries(issue):
            hits.append(Hit(
                rule_id=f"unused-{kind}",
                path=path,
                statement=f"knip reports unused {kind} {display}.",
                anchor=anchor,
                row=row,
                whole_project=True,
            ))
        for group in ("dependencies", "devDependencies"):
            items = issue.get(group) or []
            for item in items if isinstance(items, list) else []:
                name = _knip_name(item, "")
                if not name:
                    continue
                hits.append(Hit(
                    rule_id="unused-dependency",
                    path=path if path != "." else "package.json",
                    statement=f"knip reports unused dependency {name}.",
                    anchor=f"dependency {name}",
                    row=row,
                    whole_project=True,
                ))
    return ParseResult(tuple(hits))


def _invoke_dependency_cruiser(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    staged = _stage_first_base(context, _DEPCRUISE_CONFIGS)
    _refuse_relative_imports(
        staged, "architecture-maintainability.structural-check-fails"
    )
    if staged is None:
        raise ToolGap("not-configured", "architecture-maintainability.structural-check-fails")
    return [
        "dependency-cruiser", "--validate", str(staged),
        "--output-type", "json", str(context.root),
    ]


def _parse_dependency_cruiser(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("dependency-cruiser output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("dependency-cruiser output must be an object")
    summary = data.get("summary")
    violations = summary.get("violations") if isinstance(summary, dict) else None
    if violations is None:
        raise ValueError("dependency-cruiser output has no summary violations")
    if not isinstance(violations, list):
        raise ValueError("dependency-cruiser violations must be a list")
    hits: list[Hit] = []
    for violation in violations:
        if not isinstance(violation, dict):
            continue
        rule = violation.get("rule") if isinstance(violation.get("rule"), dict) else {}
        name = str(rule.get("name") or "violation")
        severity = str(rule.get("severity") or "error").lower()
        level = "warning" if severity == "warn" else severity
        if level not in ("error", "warning", "info"):
            level = "error"
        source = str(violation.get("from") or ".")
        target = str(violation.get("to") or ".")
        hits.append(Hit(
            rule_id=name,
            path=source,
            statement=f"Dependency rule {name}: {source} -> {target}.",
            anchor=f"{name}: {source} -> {target}",
            level=level,
            whole_project=True,
        ))
    return ParseResult(tuple(hits))


def _invoke_prettier(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    return ["prettier", "--write", str(context.root)]


def _parse_empty(_text: str) -> ParseResult:
    return ParseResult(())


def _invoke_typescript_no_network(context: ScanContext) -> list[str]:
    if not _has_markers(context.root):
        return []
    raise ToolGap("known-gap", "testing.flaky-order-or-network")


def _rules(row: Mapping[str, object]) -> tuple[RulePin, ...]:
    rules = row.get("rules") or []
    if not isinstance(rules, list):
        return ()
    pins = []
    for entry in rules:
        if not isinstance(entry, dict):
            continue
        pins.append(RulePin(
            pack=entry.get("pack"),
            sha256=entry.get("sha256"),
            path=entry.get("path"),
        ))
    return tuple(pins)


def _level_map(row: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    mapping = row.get("level_map") or {}
    if not isinstance(mapping, dict):
        return ()
    return tuple((str(key), str(value)) for key, value in mapping.items())


def _build(document: Mapping[str, object]) -> list[Adapter]:
    tools = document.get("tools")
    if not isinstance(tools, list):
        raise review_tools.RunnerFailure(2, "review-tools.yaml tools must be a list")
    invoke = {
        "npm-audit": _invoke_npm_audit,
        "tsc": _invoke_tsc,
        "eslint": _invoke_eslint,
        "stryker": _invoke_stryker,
        "vitest-shuffle": _invoke_vitest_shuffle,
        "jest-shuffle": _invoke_jest_shuffle,
        "knip": _invoke_knip,
        "dependency-cruiser": _invoke_dependency_cruiser,
        "prettier": _invoke_prettier,
        "typescript-no-network": _invoke_typescript_no_network,
        "vitest-coverage": lambda _context: [],
        "jest-coverage": lambda _context: [],
    }
    parse = {
        "npm-audit": _parse_npm_audit,
        "tsc": _parse_tsc,
        "eslint": _parse_eslint,
        "stryker": _parse_stryker,
        "vitest-shuffle": _parse_vitest_shuffle,
        "jest-shuffle": _parse_jest_shuffle,
        "knip": _parse_knip,
        "dependency-cruiser": _parse_dependency_cruiser,
        "prettier": _parse_empty,
        "typescript-no-network": _parse_empty,
        "vitest-coverage": _parse_empty,
        "jest-coverage": _parse_empty,
    }
    built: list[Adapter] = []
    for row in tools:
        if not isinstance(row, dict):
            continue
        tool_id = str(row.get("id") or "")
        if tool_id not in invoke:
            continue
        gap = row.get("gap_until_present")
        built.append(Adapter(
            id=tool_id,
            tool=str(row.get("tool") or ""),
            invoke=invoke[tool_id],
            parse=parse[tool_id],
            languages=tuple(str(item) for item in (row.get("languages") or ["*"])),
            rows=_ROWS[tool_id],
            comparison=str(row.get("comparison") or "lines"),
            lens=str(row.get("lens") or "correctness"),
            type_checker=bool(row.get("type_checker")),
            mutation=bool(row.get("mutation")),
            mode=str(row.get("mode") or "report"),
            timeout_seconds=int(row.get("timeout_seconds") or 120),
            platforms=tuple(str(item) for item in (row.get("platforms") or ())),
            env_dirs=tuple(str(item) for item in (row.get("env_dirs") or ())),
            lockfiles=tuple(str(item) for item in (row.get("lockfiles") or ())),
            version_args=tuple(str(item) for item in (row.get("version_args") or ("--version",))),
            default_version=str(row.get("default_version") or "not-recorded"),
            gap_path=str(gap) if isinstance(gap, str) else None,
            gap_rows=(),
            curated_rules=tuple(str(item) for item in (row.get("curated_block_rules") or ())),
            level_map=_level_map(row),
            rules=_rules(row),
            stream=str(row.get("stream") or "stdout"),
            report_file=str(row.get("report_file")) if row.get("report_file") else None,
            silent_ok=bool(row.get("silent_ok")),
            gap_first=bool(row.get("gap_first")),
            base_files=tuple(str(item) for item in (row.get("base_files") or ())),
            local_bins=tuple(str(item) for item in (row.get("local_bins") or ())),
        ))
    return built


ADAPTERS: tuple[Adapter, ...] = tuple(_build(_document()))
