#!/usr/bin/env python3
"""CI lint: every gate site must declare its machine-readable operator-absence contract (#371).

"We forgot to say what happens on silence" becomes a build failure, not an operator surprise.
The lint enumerates gate call sites across ``plugins/saga`` and
fails the build on any site with no declared ``absence_behavior``. Two site families:

**Markdown gate sites** (skills/commands/agents are prompt surfaces): every line mentioning
``AskUserQuestion`` in a scanned ``*.md`` file (``CHANGELOG.md``/``README.md`` basenames excluded
— release-notes and index surfaces, not behavior) is a candidate gate site. A candidate is
covered when its markdown section (split at ATX headings) contains a machine-readable marker:

    <!-- gate-record: id=<slug> absence=<HALT|safe-default-with-record|escalate> transport=<t> -->
    <!-- gate-exempt: <non-empty reason this mention is not a gate> -->

A marker that starts ``<!-- gate-`` but does not parse EXACTLY is a build failure (fail closed —
a malformed declaration is worse than a missing one, because it looks like coverage).

**Python gate sites**: every ``open_gate(...)`` call (AST, never regex/execution) must pass an
explicit ``absence_behavior=`` keyword whose value is a string literal in the vocabulary. A
missing keyword, a non-literal value, an off-vocabulary literal, or an opaque ``**kwargs`` is a
failure. The one module that DEFINES ``open_gate`` is the primitive's own surface (its CLI
forwards a runtime-validated operator value) — it is excluded from call-site enumeration by rule
and reported as such, never silently skipped.

**Ratchet baseline** (``gate_absence_baseline.json``, beside this script): the v1 migration
covers six saga skills; every other legacy file with uncovered mentions is pinned in the baseline
with its EXACT uncovered-mention count and reported as ``pending migration — surfaced, not
enforced (applied: false)``. Any drift fails the build: a new uncovered mention (count grew), a
migrated mention (count shrank — shrink the baseline), a vanished file, or a stale entry. New
files start unbaselined: fully enforced from their first mention.

Residuals, stated precisely: (1) this lint enumerates ``AskUserQuestion`` mentions and
``open_gate`` calls under the scanned roots — a gate built on some other widget, or living
outside the scanned roots, is not enumerated here; extending the candidate vocabulary is the
documented fast-follow path, and the baseline mechanism is how a newly enumerated family rolls
out without a flag day. (2) Markdown coverage granularity is the SECTION, not the mention: a
new ``AskUserQuestion`` mention added inside an already-marked section rides that section's
marker with no declaration of its own — "a new gate site fails the build" holds for new
sections and new files, not for additions beside an existing marker. (3) Python enumeration
matches the literal call name ``open_gate``: an aliased import (``open_gate as og``) removes
the site from enumeration entirely. Neither evasion exists in-repo today; both are named here
so they are found by reading, not by incident.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
# ``plugins/team-execution`` was the second root until issue #1030 archived that plugin. A scan
# root that does not exist is a hard error by design, so the root is removed rather than made
# optional -- an optional root is a root that can silently stop being scanned.
DEFAULT_ROOTS = ("plugins/saga",)
DEFAULT_BASELINE = Path(__file__).resolve().parent / "gate_absence_baseline.json"

ABSENCE_BEHAVIORS = ("HALT", "safe-default-with-record", "escalate")
TRANSPORTS = ("ask-user-question", "file-sentinel")
EXCLUDED_BASENAMES = frozenset({"CHANGELOG.md", "README.md"})

CANDIDATE_MENTION = "AskUserQuestion"
_MARKER_PREFIX_RE = re.compile(r"<!--\s*gate-")
_MARKER_RE = re.compile(r"<!--\s*gate-(record|exempt):\s*(.*?)\s*-->")
_HEADING_RE = re.compile(r"^#{1,6}\s")
_ATTR_RE = re.compile(r"^(id|absence|transport)=(\S+)$")
_GATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,199}$")


@dataclass
class Finding:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.message}"


@dataclass
class ScanResult:
    compliant: list[str] = field(default_factory=list)
    exempt: list[str] = field(default_factory=list)
    pending: dict[str, int] = field(default_factory=dict)  # baselined path -> uncovered count
    definers: list[str] = field(default_factory=list)
    python_ok: list[str] = field(default_factory=list)
    violations: list[Finding] = field(default_factory=list)
    uncovered: dict[str, list[Finding]] = field(default_factory=dict)  # path -> md candidates


def _relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# Markdown analysis.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Marker:
    kind: str  # "record" | "exempt"
    line: int
    section: int
    detail: str  # gate id for records, reason for exemptions


def _parse_marker(kind: str, body: str, where: str) -> Marker:
    if kind == "exempt":
        if not body.strip():
            raise ValueError(f"{where}: gate-exempt marker needs a non-empty reason")
        return Marker(kind="exempt", line=0, section=0, detail=body.strip())
    attrs: dict[str, str] = {}
    for token in body.split():
        match = _ATTR_RE.match(token)
        if match is None:
            raise ValueError(f"{where}: unparseable gate-record attribute {token!r}")
        key, value = match.group(1), match.group(2)
        if key in attrs:
            raise ValueError(f"{where}: duplicate gate-record attribute {key!r}")
        attrs[key] = value
    missing = {"id", "absence", "transport"} - attrs.keys()
    if missing:
        raise ValueError(f"{where}: gate-record marker missing attribute(s) {sorted(missing)}")
    if not _GATE_ID_RE.match(attrs["id"]):
        raise ValueError(f"{where}: gate-record id {attrs['id']!r} is not a valid slug")
    if attrs["absence"] not in ABSENCE_BEHAVIORS:
        raise ValueError(
            f"{where}: gate-record absence {attrs['absence']!r} not in {list(ABSENCE_BEHAVIORS)}"
        )
    if attrs["transport"] not in TRANSPORTS:
        raise ValueError(
            f"{where}: gate-record transport {attrs['transport']!r} not in {list(TRANSPORTS)}"
        )
    return Marker(kind="record", line=0, section=0, detail=attrs["id"])


def analyze_markdown(path: Path, result: ScanResult) -> None:
    rel = _relpath(path)
    text = path.read_text(encoding="utf-8")
    section = 0
    markers: list[Marker] = []
    candidates: list[tuple[int, int]] = []  # (line_no, section)
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _HEADING_RE.match(line):
            section += 1
        for match in _MARKER_RE.finditer(line):
            try:
                parsed = _parse_marker(match.group(1), match.group(2), f"{rel}:{line_no}")
            except ValueError as exc:
                result.violations.append(Finding(rel, line_no, f"malformed marker — {exc}"))
                continue
            markers.append(Marker(parsed.kind, line_no, section, parsed.detail))
        if len(_MARKER_PREFIX_RE.findall(line)) != len(_MARKER_RE.findall(line)):
            result.violations.append(
                Finding(rel, line_no, "unparseable gate marker (starts '<!-- gate-')")
            )
        if CANDIDATE_MENTION in line:
            candidates.append((line_no, section))
    sections_with_markers = {m.section for m in markers}
    for marker in markers:
        entry = f"{rel}:{marker.line}  id={marker.detail}"
        if marker.kind == "record":
            result.compliant.append(entry)
        else:
            result.exempt.append(f"{rel}:{marker.line}  reason={marker.detail}")
    for line_no, cand_section in candidates:
        if cand_section not in sections_with_markers:
            result.uncovered.setdefault(rel, []).append(
                Finding(
                    rel,
                    line_no,
                    f"{CANDIDATE_MENTION} gate site declares no absence contract "
                    f"(no gate-record/gate-exempt marker in its section)",
                )
            )


# ---------------------------------------------------------------------------
# Python analysis.
# ---------------------------------------------------------------------------


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def analyze_python(path: Path, result: ScanResult) -> None:
    rel = _relpath(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        result.violations.append(Finding(rel, exc.lineno or 0, f"unparseable Python ({exc.msg})"))
        return
    defines_primitive = any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "open_gate"
        for node in ast.walk(tree)
    )
    if defines_primitive:
        result.definers.append(rel)
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "open_gate":
            continue
        keyword = next((k for k in node.keywords if k.arg == "absence_behavior"), None)
        if keyword is None:
            has_star_kwargs = any(k.arg is None for k in node.keywords)
            if has_star_kwargs:
                result.violations.append(
                    Finding(
                        rel,
                        node.lineno,
                        "open_gate(**...) hides its absence_behavior behind opaque kwargs — "
                        "declare it explicitly",
                    )
                )
            else:
                result.violations.append(
                    Finding(
                        rel,
                        node.lineno,
                        "open_gate(...) declares no absence_behavior — every gate must declare "
                        "what silence means",
                    )
                )
            continue
        value = keyword.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            result.violations.append(
                Finding(
                    rel,
                    node.lineno,
                    "open_gate(absence_behavior=...) is not a string literal — the declaration "
                    "must be statically checkable",
                )
            )
            continue
        if value.value not in ABSENCE_BEHAVIORS:
            result.violations.append(
                Finding(
                    rel,
                    node.lineno,
                    f"open_gate(absence_behavior={value.value!r}) not in {list(ABSENCE_BEHAVIORS)}",
                )
            )
            continue
        result.python_ok.append(f"{rel}:{node.lineno}  absence={value.value}")


# ---------------------------------------------------------------------------
# Baseline (ratchet) handling.
# ---------------------------------------------------------------------------


def load_baseline(path: Path) -> dict[str, int]:
    if not path.exists():
        raise ValueError(f"baseline {path} does not exist")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data.keys()) != {"schema_version", "pending"}:
        raise ValueError(f"baseline {path}: expected exactly schema_version + pending keys")
    if data["schema_version"] != 1:
        raise ValueError(f"baseline {path}: unknown schema_version {data['schema_version']!r}")
    pending = data["pending"]
    if not isinstance(pending, dict):
        raise ValueError(f"baseline {path}: pending must be an object")
    out: dict[str, int] = {}
    for key, value in pending.items():
        if not isinstance(key, str) or type(value) is not int or value < 1:
            raise ValueError(f"baseline {path}: entry {key!r}: {value!r} must be a count >= 1")
        out[key] = value
    return out


def apply_baseline(
    result: ScanResult,
    baseline: dict[str, int],
    scanned_files: set[str],
    root_prefixes: list[str],
) -> None:
    """Reconcile uncovered markdown candidates against the ratchet baseline — exact or fail."""
    for rel, findings in sorted(result.uncovered.items()):
        expected = baseline.get(rel)
        if expected is None:
            result.violations.extend(findings)
        elif expected == len(findings):
            result.pending[rel] = expected
        else:
            result.violations.append(
                Finding(
                    rel,
                    findings[0].line,
                    f"baseline drift: {len(findings)} uncovered gate site(s), baseline pins "
                    f"{expected} — migrate the new site(s) or consciously update the baseline"
                    if len(findings) > expected
                    else f"baseline ratchet: only {len(findings)} uncovered gate site(s) remain, "
                    f"baseline pins {expected} — shrink the baseline entry",
                )
            )
    for rel, expected in sorted(baseline.items()):
        if rel in result.uncovered:
            continue
        under_scanned_root = any(
            rel == prefix or rel.startswith(prefix + "/") for prefix in root_prefixes
        )
        if not under_scanned_root:
            continue  # outside this scan's roots (partial scan) — not judged here
        if rel not in scanned_files:
            result.violations.append(
                Finding(
                    rel,
                    0,
                    f"baseline entry vanished: file is under a scanned root but was not found "
                    f"(baseline pins {expected}) — remove or correct the baseline entry",
                )
            )
            continue
        result.violations.append(
            Finding(
                rel,
                0,
                f"stale baseline entry: file has no uncovered gate site (baseline pins "
                f"{expected}) — remove it from the baseline",
            )
        )


# ---------------------------------------------------------------------------
# Drivers.
# ---------------------------------------------------------------------------


def _is_shipped(path: Path) -> bool:
    """Test modules are not a gate surface.

    The package's tests now live under ``plugins/saga/tests/``. A directory scan
    of the package would otherwise treat a red-path fixture (a gate call that
    deliberately declares nothing) as a shipped violation. A ``--fixture`` file
    is still judged: that path is a file, and this filter applies only to a
    directory walk.
    """
    return "tests" not in path.parts


def iter_files(roots: list[Path]) -> tuple[list[Path], list[Path]]:
    md: list[Path] = []
    py: list[Path] = []
    for root in roots:
        if root.is_file():
            (md if root.suffix == ".md" else py).append(root)
            continue
        md.extend(
            path
            for path in sorted(root.rglob("*.md"))
            if path.name not in EXCLUDED_BASENAMES and _is_shipped(path)
        )
        py.extend(path for path in sorted(root.rglob("*.py")) if _is_shipped(path))
    return md, py


def run_scan(roots: list[Path], baseline: dict[str, int] | None) -> ScanResult:
    result = ScanResult()
    md_files, py_files = iter_files(roots)
    for path in md_files:
        analyze_markdown(path, result)
    for path in py_files:
        analyze_python(path, result)
    if baseline is None:
        for findings in result.uncovered.values():
            result.violations.extend(findings)
    else:
        scanned = {_relpath(p) for p in md_files}
        prefixes = [_relpath(root) for root in roots]
        apply_baseline(result, baseline, scanned, prefixes)
    return result


def render_report(result: ScanResult) -> str:
    lines: list[str] = []
    lines.append(f"gate-record sites (compliant): {len(result.compliant)}")
    lines.extend(f"  {entry}" for entry in result.compliant)
    lines.append(f"gate-exempt mentions: {len(result.exempt)}")
    lines.extend(f"  {entry}" for entry in result.exempt)
    lines.append(f"python open_gate call sites (compliant): {len(result.python_ok)}")
    lines.extend(f"  {entry}" for entry in result.python_ok)
    lines.append(
        f"primitive definer modules (excluded from call-site enumeration by rule): "
        f"{len(result.definers)}"
    )
    lines.extend(f"  {entry}" for entry in result.definers)
    lines.append(
        f"pending migration (baselined, surfaced not enforced — applied: false): "
        f"{len(result.pending)}"
    )
    lines.extend(
        f"  {path}  {count} undeclared gate site(s)"
        for path, count in sorted(result.pending.items())
    )
    if result.violations:
        lines.append(f"VIOLATIONS: {len(result.violations)}")
        lines.extend(f"  {finding}" for finding in result.violations)
    else:
        lines.append("VIOLATIONS: 0")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lint_gate_absence_contract", description=__doc__)
    parser.add_argument(
        "--scan",
        action="append",
        default=[],
        help=f"root(s) to scan (repeatable; default: {', '.join(DEFAULT_ROOTS)})",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="lint exactly one file (baseline ignored) — the AC fixture mode",
    )
    parser.add_argument(
        "--baseline",
        default=str(DEFAULT_BASELINE),
        help="ratchet baseline of legacy files pending migration",
    )
    parser.add_argument(
        "--emit-baseline",
        action="store_true",
        help="print the baseline JSON matching the current uncovered state and exit 0",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.fixture:
        result = run_scan([Path(args.fixture)], baseline=None)
        print(render_report(result))
        return 1 if result.violations else 0

    roots = [Path(r) for r in args.scan] if args.scan else [REPO_ROOT / r for r in DEFAULT_ROOTS]
    for root in roots:
        if not root.exists():
            print(f"error: scan root {root} does not exist", file=sys.stderr)
            return 1

    if args.emit_baseline:
        result = run_scan(roots, baseline={})
        pending = {rel: len(findings) for rel, findings in sorted(result.uncovered.items())}
        print(json.dumps({"schema_version": 1, "pending": pending}, indent=2))
        return 0

    try:
        baseline = load_baseline(Path(args.baseline))
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    result = run_scan(roots, baseline)
    print(render_report(result))
    return 1 if result.violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
