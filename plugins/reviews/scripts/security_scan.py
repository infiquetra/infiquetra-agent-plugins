#!/usr/bin/env python3
"""Scan one committed tree with the review catalogue's security adapters.

The target is read through Git object commands only. All writable Git state belongs
to an independent snapshot repository, never to the target or its linked worktrees.
"""

from __future__ import annotations


def _reviews_load(name: str):
    """Load a sibling without occupying the bare name Saga tests import."""
    import importlib.util
    import sys
    from pathlib import Path

    key = "infiquetra_reviews.reviews_loader"
    loader = sys.modules.get(key)
    if loader is None:
        path = Path(__file__).resolve().parent / "reviews_loader.py"
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        loader = importlib.util.module_from_spec(spec)
        sys.modules[key] = loader
        spec.loader.exec_module(loader)
    return loader.load(name)


import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

review_formula = _reviews_load('review_formula')
tools = _reviews_load('review_tools')

SYNTHESIZED = frozenset({"cdk-nag", "checkov-cdk"})
ADVISORY_ROWS = frozenset({"osv-scanner", "pip-audit", "npm-audit"})
LEVELS = ("blocks", "fix-later", "note")
_GIT_OPTIONS = (
    "-c", "core.hooksPath=" + os.devnull,
    "-c", "core.fsmonitor=false", "-c", "gc.auto=0",
    "-c", "submodule.recurse=false", "-c", "core.autocrlf=false",
)


class ScanFailure(Exception):
    """A refusal or incomplete operation whose diagnostics contain no tool output."""


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    env = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TMPDIR")
           if name in os.environ}
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0",
        # Reads in partial clones can otherwise fetch into the target object store.
        "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "",
        "GIT_AUTHOR_NAME": "snapshot", "GIT_COMMITTER_NAME": "snapshot",
        "GIT_AUTHOR_EMAIL": "snapshot@example.invalid",
        "GIT_COMMITTER_EMAIL": "snapshot@example.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
    })
    result = subprocess.run(  # nosec B603 - fixed executable, argument vector, no shell
        ["git", *_GIT_OPTIONS, "-C", str(repo), *args], input=data,
        capture_output=True, timeout=120, env=env, check=False,
    )
    if result.returncode:
        raise ScanFailure("could not read or construct the selected Git tree")
    return result.stdout


def _text(repo: Path, *args: str) -> str:
    return _git(repo, *args).decode("utf-8").strip()


def _target(repo: Path) -> tuple[Path, list[Path]]:
    root = Path(_text(repo, "rev-parse", "--show-toplevel")).resolve()
    storage = []
    for flag in ("--absolute-git-dir", "--git-common-dir"):
        path = Path(_text(root, "rev-parse", flag))
        storage.append((path if path.is_absolute() else root / path).resolve())
    return root, [root, *storage]


def _outside(path: Path, protected: Sequence[Path], label: str) -> None:
    if any(_within(path, root) for root in protected):
        raise ScanFailure(f"{label} must be outside the scanned repository and its Git storage")


def _snapshot(source: Path, commit: str, destination: Path) -> tuple[str, str, list[str]]:
    tree = _text(source, "rev-parse", f"{commit}^{{tree}}")
    entries = _git(source, "ls-tree", "-rz", tree)
    if not entries:
        raise ScanFailure("the selected commit has an empty tree")
    submodules = []
    for entry in entries.split(b"\0"):
        if entry.startswith(b"160000 "):
            submodules.append(os.fsdecode(entry.split(b"\t", 1)[1]))
    destination.mkdir()
    _git(destination, "init", "--quiet", "--template=")
    for key, value in (("core.hooksPath", os.devnull), ("core.fsmonitor", "false"),
                       ("gc.auto", "0"), ("submodule.recurse", "false")):
        _git(destination, "config", key, value)
    # Transfer only the tree and its blobs, never source commits, refs, config or hooks.
    pack = _git(source, "pack-objects", "--stdout", "--revs", data=(tree + "\n").encode())
    _git(destination, "unpack-objects", "-q", data=pack)
    empty = _git(destination, "hash-object", "-t", "tree", "-w", "--stdin", data=b"").strip()
    base = _git(destination, "commit-tree", empty.decode(), data=b"Empty scan base\n").strip()
    head = _git(destination, "commit-tree", tree, "-p", base.decode(),
                data=b"Selected tree snapshot\n").strip()
    _git(destination, "update-ref", "refs/heads/snapshot", head.decode())
    _git(destination, "symbolic-ref", "HEAD", "refs/heads/snapshot")
    if _text(destination, "rev-parse", "HEAD^{tree}") != tree:
        raise ScanFailure("snapshot tree mismatch; scan incomplete")
    # Higher-precedence attributes keep checkout bytes literal rather than transforming
    # source through text/eol/encoding attributes in the untrusted tracked tree.
    info = destination / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "attributes").write_text("* -text -filter -ident -working-tree-encoding\n")
    return base.decode(), head.decode(), sorted(submodules)


def _machine_object(record: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _rule_caches(record: Path) -> dict[str, Any]:
    caches = _machine_object(record).get("rule_caches", {})
    return caches if isinstance(caches, dict) else {}


def _staged_pins(record: Path) -> dict[str, Any]:
    """Version pins the runner reads, keyed by binary name."""
    pins = _machine_object(record).get("pins")
    if not isinstance(pins, dict):
        return {}
    staged: dict[str, Any] = {}
    for tool, spec in pins.items():
        version = spec.get("version") if isinstance(spec, dict) else None
        if isinstance(version, str) and version:
            staged[str(tool)] = {"version": version}
    return staged


def _staged_record(record: Path) -> dict[str, Any]:
    body: dict[str, Any] = {"rule_caches": _rule_caches(record)}
    pins = _staged_pins(record)
    if pins:
        body["pins"] = pins
    return body


def _stage_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, symlinks=True)
    for path in [target, *target.rglob("*")]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & 0o700)


def _rule_home(home: Path, machine_home: Path) -> None:
    """Stage machine rule-cache inputs; new reports stay in this run's directory.

    The reviews cache and its recorded digest are preferred. The legacy cache is
    staged beside it and is not rewritten on the operator's machine.
    """
    reviews = Path(".config") / "infiquetra" / "reviews"
    reviews_record = machine_home / reviews / "machine.json"
    reviews_rules = machine_home / reviews / "semgrep-rules"
    if reviews_record.is_file() or reviews_rules.is_dir():
        staged = home / reviews
        staged.mkdir(parents=True, mode=0o700)
        (staged / "machine.json").write_text(
            json.dumps(_staged_record(reviews_record)) + "\n",
            encoding="utf-8",
        )
        if reviews_rules.is_dir():
            _stage_tree(reviews_rules, staged / "semgrep-rules")
    legacy = home / ".saga"
    legacy.mkdir(parents=True, mode=0o700)
    (legacy / "machine.json").write_text(
        json.dumps(_staged_record(machine_home / ".saga" / "machine.json")) + "\n",
        encoding="utf-8",
    )
    legacy_rules = machine_home / ".saga" / "semgrep-rules"
    if legacy_rules.is_dir():
        _stage_tree(legacy_rules, legacy / "semgrep-rules")


def _secret_report(result: tools.ProcessResult) -> tools.ProcessResult:
    """Gitleaks may return matched bytes even on failure; never persist either stream."""
    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            data = data.get("findings") or data.get("leaks") or []
        if not isinstance(data, list):
            raise ValueError("not a list")
        keys = ("RuleID", "File", "StartLine", "EndLine", "StartColumn", "EndColumn")
        text = json.dumps([{key: item[key] for key in keys if key in item}
                           for item in data if isinstance(item, dict)])
    except (ValueError, TypeError):
        text = "invalid secret scanner report"
    return tools.ProcessResult(result.code, text, "")


@dataclass
class Observation:
    adapter: tools.Adapter
    scratch: Path
    invoked: bool = False
    version: str | None = None
    unsupported: set[str] = field(default_factory=set)

    def invoke(self, context: tools.ScanContext) -> list[str]:
        if self.adapter.id == "pip-audit" and context.repository_scan:
            _loaded_review_adapters_python = _reviews_load('review_adapters_python')
            pip_audit_scan_inputs = _loaded_review_adapters_python.pip_audit_scan_inputs
            _accepted, unsupported = pip_audit_scan_inputs(context.root)
            self.unsupported.update(unsupported)
        argv = self.adapter.invoke(context)
        if argv and context.scan == "head":
            self.invoked = True
        return argv

    def process(self, argv: Sequence[str] | str, *, cwd: Path, env: dict[str, str],
                timeout: float, shell: bool) -> tools.ProcessResult:
        # Narrow-adapter version probes normally inherit ambient credentials. The
        # scan keeps them on the same fresh-home boundary as the actual tool run.
        allowed = {
            "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SYSTEMROOT", "WINDIR",
            "COMSPEC", "PATHEXT", "PYTHONHASHSEED", "CARGO_HOME", "RUSTUP_HOME",
            "RUSTUP_TOOLCHAIN", "SEMGREP_ENABLE_VERSION_CHECK",
        }
        clean = {key: value for key, value in env.items() if key in allowed}
        clean.update({"HOME": str(self.scratch), "TMPDIR": str(self.scratch)})
        result = tools.subprocess_runner(argv, cwd=cwd, env=clean, timeout=timeout,
                                         shell=shell, umask=0o077)
        if not self.invoked:
            if result.code == 0:
                self.version = tools._found_version(result.stdout or result.stderr or "")
        elif self.adapter.tool == "gitleaks":
            result = _secret_report(result)
        return result


def _row(row_id: str, pin: str) -> dict[str, Any]:
    return {"id": row_id, "status": "skipped", "reason": "no applicable input",
            "version": None, "pin": pin, "counts": dict.fromkeys(LEVELS, 0),
            "advisory_service": False}


def _scan_rows(repo: Path, base: str, head: str, profile_path: Path, output: Path,
               scratch: Path, include: set[str], timeout: int | None) -> tuple[list, list, list]:
    profile = tools._load_profile(profile_path)
    adapters = {adapter.id: adapter for adapter in tools.default_adapters()}
    audit_notes = {"scanner-settings", *(marker[3] for marker in tools._COMMENT_MARKERS)}
    rows, findings, degraded = [], [], []
    for item in tools.load_tool_list():
        if item.get("lens") != "security":
            continue
        row_id = item["id"]
        adapter = adapters.get(row_id)
        pin = tools._pinned_version(adapter, profile, output / ".cache") if adapter else str(
            item.get("default_version") or "not-recorded")
        row = _row(row_id, pin)
        rows.append(row)
        if row_id in SYNTHESIZED and row_id not in include:
            row["reason"] = "opt-in required: --include-synthesized " + row_id
            continue
        if adapter is None or adapter.mode == "fix" or adapter.lens != "security":
            row.update(status="degraded", reason="no executable security adapter")
            continue
        observer_home = scratch / (row_id + "-tool-home")
        observer_home.mkdir(mode=0o700)
        observer = Observation(adapter, observer_home)
        selected = replace(adapter, invoke=observer.invoke,
                           timeout_seconds=timeout or adapter.timeout_seconds)
        row_output = scratch / (row_id + "-records")
        try:
            code = tools.run(repo, base, head, profile_path, row_output,
                             home=output / ".cache", adapters=[selected],
                             runner=observer.process, framework=False, repository_scan=True)
            if code:
                raise ScanFailure("runner could not complete this row")
            hits = json.loads((row_output / "findings.json").read_text())
            gaps = json.loads((row_output / "degraded.json").read_text())
            outcomes = json.loads((row_output / "outcomes.json").read_text())
            for finding in outcomes["findings"]:
                row["counts"][finding["severity"]] += 1
            findings.extend(hits)
            degraded.extend(gaps)
            reasons = sorted({gap["reason"] for gap in gaps
                              if gap.get("tool") in {adapter.tool, adapter.id}
                              and gap.get("reason") not in audit_notes})
            if observer.unsupported:
                reasons.append("requirements-not-exactly-pinned: " + ", ".join(
                    sorted(observer.unsupported)))
            row["version"] = observer.version
            if reasons:
                row.update(status="degraded", reason="; ".join(reasons))
            elif observer.invoked:
                row.update(status="ran", reason="")
        except (OSError, ValueError, tools.RunnerFailure, ScanFailure):
            row.update(status="degraded", reason="execution-error")
        row["advisory_service"] = row_id in ADVISORY_ROWS and observer.invoked
    return rows, findings, degraded


def _summary(commit: str, rows: list, findings: list, submodules: list[str]) -> dict[str, Any]:
    incomplete = bool(submodules) or any(row["status"] == "degraded" for row in rows)
    return {"commit": commit, "exit_code": 2 if incomplete else int(bool(findings)),
            "rows": sorted(rows, key=lambda row: row["id"]),
            "unscanned_submodules": submodules,
            "advisory_service_rows": sorted(row["id"] for row in rows
                                             if row["advisory_service"])}


def _display(value: Any) -> str:
    """Keep untrusted paths and rule names from issuing terminal control sequences."""
    return "".join(char if ord(char) >= 32 and ord(char) != 127
                   else f"\\x{ord(char):02x}" for char in str(value))


def _markdown(summary: dict[str, Any], findings: list) -> str:
    lines = ["# Repository security scan", "", "Commit: " + summary["commit"], "",
             "Exit status: " + str(summary["exit_code"]), "",
             "| Row | Status | Version | Pin | blocks / fix-later / note | Reason |",
             "|---|---|---|---|---|---|"]
    for row in summary["rows"]:
        pin = "no pin recorded" if row["pin"] == "not-recorded" else row["pin"]
        counts = " / ".join(str(row["counts"][level]) for level in LEVELS)
        cells = (row["id"], row["status"], row["version"] or "not observed", pin,
                 counts, row["reason"])
        lines.append("| " + " | ".join(_display(cell).replace("|", "\\|")
                                       for cell in cells) + " |")
    lines += ["", "pip-audit audits only the packages and versions the files list.", "",
              "Rows that can send package names and versions to an advisory service: "
              + (", ".join(summary["advisory_service_rows"]) or "none invoked") + ".",
              "cargo-deny may fetch its public advisory database.", "", "## Findings", ""]
    for finding in review_formula.compute({"findings": findings})["findings"]:
        location = finding["location"]
        line = location.get("lines", {}).get("start")
        path = location["file"] + (f":{line}" if line is not None else "")
        lines.append(f"- {finding['severity']}: {_display(finding['rule']['ref'])} — {_display(path)}")
    if not findings:
        lines.append("No findings reported; consult row statuses for coverage gaps.")
    for path in summary["unscanned_submodules"]:
        lines.append(f"- Unscanned submodule gap: {_display(path)} (incomplete)")
    return "\n".join(lines) + "\n"


def _positive(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--include-synthesized", action="append", default=[],
                        choices=sorted(SYNTHESIZED))
    parser.add_argument("--timeout", type=_positive)
    args = parser.parse_args(argv)
    old_temp = tempfile.tempdir
    old_mask = os.umask(0o077)
    try:
        repo, protected = _target(args.repo.resolve())
        output = args.output.resolve()
        _outside(output, protected, "output")
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ScanFailure("output must be an absent or empty directory")
        if args.profile:
            args.profile = args.profile.resolve()
            _outside(args.profile, protected, "profile")
            tools._load_profile(args.profile)
        commit = _text(repo, "rev-parse", "--verify", "--end-of-options",
                       args.commit + "^{commit}")
        temp_root = Path(tempfile.gettempdir()).resolve()
        _outside(temp_root, protected, "temporary directory")
        machine_home = Path.home()
        with tempfile.TemporaryDirectory(prefix="saga-security-scan-", dir=temp_root) as name:
            scratch = Path(name)
            tempfile.tempdir = name
            base, head, submodules = _snapshot(repo, commit, scratch / "snapshot")
            output.mkdir(parents=True, mode=0o700, exist_ok=True)
            output.chmod(0o700)
            _rule_home(output / ".cache", machine_home)
            profile = args.profile or scratch / "profile.json"
            if not args.profile:
                profile.write_text("{}\n")
            rows, findings, degraded = _scan_rows(
                scratch / "snapshot", base, head, profile, output, scratch,
                set(args.include_synthesized), args.timeout)
            for path in submodules:
                degraded.append({"lens": "security", "language": "none", "tool": "git",
                                 "input": path, "reason": "unscanned-submodule"})
            tools._emit(output, findings, [], degraded, None)
            summary = _summary(commit, rows, findings, submodules)
            markdown = _markdown(summary, findings)
            (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            (output / "summary.md").write_text(markdown)
            print(markdown, end="")
            return summary["exit_code"]
    except ScanFailure as exc:
        print(f"security scan: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, subprocess.SubprocessError, tools.RunnerFailure):
        print("security scan: invalid input or incomplete scan; check paths, commit and output access",
              file=sys.stderr)
        return 2
    finally:
        tempfile.tempdir = old_temp
        os.umask(old_mask)


if __name__ == "__main__":
    raise SystemExit(main())
