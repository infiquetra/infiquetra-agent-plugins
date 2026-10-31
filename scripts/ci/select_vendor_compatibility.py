"""Candidate-bound vendor selection and phase-one full-matrix admission (stdlib)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import PurePosixPath

SHA = re.compile(r"[0-9a-f]{40}")
STATUS = re.compile(r"(?:[MADT]|R(?:100|0[0-9]{2}))")
CHILDREN = ("vendor-selection", "validate", "plugin-tests", "claude-mods")
KEYS = {
    "schema", "phase", "base", "head", "candidate", "candidate_checked",
    "recommendation", "complete", "reason", "diff_sha256", "changes",
}
# No individual portable document has a proven dependency exemption yet.
# This phase prepares evidence; it never authorizes reduced execution.
SAFE_PORTABLE_DOCUMENTS: frozenset[str] = frozenset()


def valid_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return (
        bool(path) and len(path) <= 512 and not path.startswith("/")
        and "\\" not in path and ".." not in parts and "." not in path.split("/")
        and "" not in path.split("/") and all(ord(c) >= 32 and ord(c) != 127 for c in path)
    )


def parse_changes(data: bytes) -> list[dict[str, object]]:
    """Require complete name-status -z records, including both rename sides."""
    if len(data) > 32768:
        raise ValueError("diff-too-large")
    if not data:
        return []
    if not data.endswith(b"\0"):
        raise ValueError("incomplete-diff")
    fields = data[:-1].decode("utf-8", errors="strict").split("\0")
    changes = []
    index = 0
    while index < len(fields):
        status = fields[index]
        if not STATUS.fullmatch(status):
            raise ValueError("invalid-status")
        count = 2 if status.startswith("R") else 1
        paths = fields[index + 1:index + 1 + count]
        if len(paths) != count or not all(valid_path(path) for path in paths):
            raise ValueError("invalid-path-record")
        changes.append({"status": status, "paths": paths})
        if len(changes) > 128:
            raise ValueError("too-many-changes")
        index += 1 + count
    return changes


def fallback(base: str, head: str, candidate: str, reason: str,
             checked: bool = False) -> dict[str, object]:
    return {
        "schema": 1, "phase": "observe-full", "base": base, "head": head,
        "candidate": candidate, "candidate_checked": checked,
        "recommendation": "FULL", "complete": False, "reason": reason,
        "diff_sha256": None, "changes": [],
    }


def classify(data: bytes, base: str, head: str, candidate: str) -> dict[str, object]:
    evidence = fallback(base, head, candidate, "invalid-binding")
    if not all(SHA.fullmatch(value) for value in (base, head, candidate)):
        return evidence
    try:
        changes = parse_changes(data)
    except (ValueError, UnicodeError):
        return fallback(base, head, candidate, "invalid-diff", True)
    evidence.update(
        candidate_checked=True, complete=True, reason="no-proven-exemption",
        diff_sha256=hashlib.sha256(data).hexdigest(), changes=changes,
    )
    return evidence


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, timeout=10,
    ).stdout


def collect(base: str, head: str, candidate: str, event: str) -> dict[str, object]:
    if not all(SHA.fullmatch(value) for value in (base, head, candidate)):
        return fallback(base, head, candidate, "invalid-binding")
    checked = False
    try:
        if git("rev-parse", "HEAD").decode().strip() != candidate:
            return fallback(base, head, candidate, "candidate-mismatch")
        checked = True
        if event == "pull_request":
            parents = git("rev-list", "--parents", "-n", "1", candidate).decode().split()
            if parents != [candidate, base, head]:
                return fallback(base, head, candidate, "missing-history", True)
        elif head != candidate:
            return fallback(base, head, candidate, "candidate-mismatch")
        data = git("diff", "--name-status", "-z", "--find-renames", base, head, "--")
        return classify(data, base, head, candidate)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return fallback(base, head, candidate, "missing-history", checked)


def admit(evidence: object, needs: object, base: str, head: str, candidate: str) -> bool:
    """Phase one always requires every original child, including the whole matrix."""
    if not isinstance(evidence, dict) or set(evidence) != KEYS or not isinstance(needs, dict):
        return False
    if not all(SHA.fullmatch(value) for value in (base, head, candidate)):
        return False
    if (type(evidence["schema"]) is not int or evidence["schema"] != 1
            or evidence["phase"] != "observe-full" or evidence["candidate_checked"] is not True
            or [evidence[k] for k in ("base", "head", "candidate")] != [base, head, candidate]
            or evidence["recommendation"] != "FULL" or type(evidence["complete"]) is not bool):
        return False
    if evidence["complete"]:
        changes = evidence["changes"]
        if not isinstance(changes, list) or evidence["reason"] != "no-proven-exemption":
            return False
        try:
            fields = []
            for change in changes:
                if not isinstance(change, dict) or set(change) != {"status", "paths"}:
                    return False
                if not isinstance(change["status"], str) or not isinstance(change["paths"], list):
                    return False
                if not all(isinstance(path, str) for path in change["paths"]):
                    return False
                fields.extend([change["status"], *change["paths"]])
            raw = ("\0".join(fields) + "\0").encode() if fields else b""
            if parse_changes(raw) != changes or hashlib.sha256(raw).hexdigest() != evidence["diff_sha256"]:
                return False
        except (ValueError, TypeError, UnicodeError):
            return False
    elif (evidence["reason"] not in {"missing-history", "invalid-diff"}
          or evidence["changes"] != [] or evidence["diff_sha256"] is not None):
        return False
    return set(needs) == set(CHILDREN) and all(
        isinstance(needs[name], dict) and needs[name].get("result") == "success"
        for name in CHILDREN
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("select", "aggregate"))
    mode = parser.parse_args().mode
    base, head, candidate = (os.environ.get("SELECT_" + key, "") for key in ("BASE", "HEAD", "CANDIDATE"))
    if mode == "select":
        evidence = collect(base, head, candidate, os.environ.get("SELECT_EVENT", ""))
        encoded = json.dumps(evidence, separators=(",", ":"), sort_keys=True)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("evidence=" + encoded + "\n")
        print(encoded)
        return 0
    try:
        needs = json.loads(os.environ["NEEDS_JSON"])
        evidence = json.loads(needs["vendor-selection"]["outputs"]["evidence"])
        accepted = admit(evidence, needs, base, head, candidate)
    except (KeyError, TypeError, ValueError):
        accepted = False
    print("FULL vendor validation admitted" if accepted else "Vendor validation refused")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
