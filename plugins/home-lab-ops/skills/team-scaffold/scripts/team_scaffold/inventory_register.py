"""Register a team's host in home-lab/ansible/inventory/hosts.yml.

This is the ONLY write-back into the (otherwise infra-only) home-lab repo. It
appends one host entry under the target group's ``hosts:`` mapping using
text-based insertion so the file's comments + formatting survive (PyYAML round
-trip would drop them). Idempotent: a host already present anywhere is left as-is.

Emit it as a single revertible commit (the caller's job); abort == git checkout.
"""

from __future__ import annotations

import pathlib
import re


class InventoryError(RuntimeError):
    pass


def _group_bounds(lines: list[str], group: str) -> tuple[int, int]:
    """Return [start, end) line indices of a top-level group block."""
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^{re.escape(group)}:\s*$", ln):
            start = i
            break
    if start is None:
        raise InventoryError(f"group {group!r} not found in inventory")
    # end = next top-level key (col 0, non-space, non-comment) after start
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j] and not lines[j][0].isspace() and not lines[j].lstrip().startswith("#"):
            end = j
            break
    return start, end


def host_present(text: str, host_key: str) -> bool:
    return re.search(rf"^\s+{re.escape(host_key)}:\s*$", text, re.MULTILINE) is not None


def render_host_entry(host_key: str, attrs: dict, host_indent: int = 4) -> str:
    pad = " " * host_indent
    apad = " " * (host_indent + 2)
    out = [f"{pad}{host_key}:\n"]
    for k, v in attrs.items():
        out.append(f"{apad}{k}: {v}\n")
    return "".join(out)


def add_host(text: str, group: str, host_key: str, attrs: dict) -> tuple[str, bool]:
    """Return (new_text, changed). No-op (changed=False) if host already present."""
    if host_present(text, host_key):
        return text, False
    lines = text.splitlines(keepends=True)
    start, end = _group_bounds(lines, group)

    # locate the `  hosts:` line within the group
    hosts_idx = None
    for i in range(start + 1, end):
        if re.match(r"^\s{2}hosts:\s*$", lines[i]):
            hosts_idx = i
            break
    if hosts_idx is None:
        raise InventoryError(f"group {group!r} has no 'hosts:' mapping")

    # end of the hosts mapping = first line after hosts_idx (within group) whose
    # indent is <= 2 (a sibling of `hosts:`), else the group end.
    insert_at = end
    for i in range(hosts_idx + 1, end):
        ln = lines[i]
        if ln.strip() == "" or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent <= 2:
            insert_at = i
            break

    # back up over trailing blank lines so the new host tucks under the last entry
    while insert_at - 1 > hosts_idx and lines[insert_at - 1].strip() == "":
        insert_at -= 1

    entry = render_host_entry(host_key, attrs)
    new_lines = lines[:insert_at] + [entry] + lines[insert_at:]
    return "".join(new_lines), True


def register(
    hosts_yml: str | pathlib.Path, group: str, host_key: str, attrs: dict, apply: bool = False
) -> tuple[bool, str]:
    """Return (changed, unified_diff). Writes the file only when apply=True."""
    path = pathlib.Path(hosts_yml).expanduser()
    text = path.read_text()
    new_text, changed = add_host(text, group, host_key, attrs)
    if not changed:
        return False, ""
    import difflib

    diff = "".join(
        difflib.unified_diff(
            text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path) + " (new)",
        )
    )
    if apply:
        path.write_text(new_text)
    return True, diff
