"""Node project paths and literal test commands shared by prepare and its checks."""
from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Iterable
from pathlib import Path

MAX_PROJECTS = 4
_FOLDER = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")


def safe_folder(folder: str) -> bool:
    return bool(_FOLDER.fullmatch(folder)) and not {"..", ".", "node_modules", ".git"} & set(folder.split("/"))


def selected(folders: Iterable[str], paths: Iterable[str]) -> list[str]:
    """Nearest manifest owns a changed path; nested independent projects do not overlap."""
    candidates = sorted(set(folders))
    owners = set()
    for path in paths:
        matches = [folder for folder in candidates if folder == "." or path.startswith(folder + "/")]
        if matches:
            owners.add(max(matches, key=lambda folder: len(Path(folder).parts) if folder != "." else 0))
    return sorted(owners)


def projects(root: Path, paths: Iterable[str]) -> list[str]:
    if (root / "package.json").is_file() and not (root / "package.json").is_symlink():
        return ["."]
    folders = []
    # Do not follow links, including packet node_modules links.
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {"node_modules", ".git"}
                         and not (Path(directory) / d).is_symlink())
        if "package.json" in files:
            folder = Path(directory).relative_to(root).as_posix()
            if safe_folder(folder) and not (Path(directory) / "package.json").is_symlink():
                folders.append(folder)
    return selected(folders, paths)[:MAX_PROJECTS]


def is_test_file(path: str) -> bool:
    item = Path(path)
    return item.suffix in {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"} and (
        ".test." in item.name or ".spec." in item.name
        or bool({"test", "tests", "__tests__"} & set(item.parts[:-1])))


def unsupported_file_parallelism(text: str) -> bool:
    """Recognise Vitest's startup rejection, independently of its configured version pin."""
    return bool(re.search(
        r"(?m)^CACError: Unknown option [`'\"]--(?:no-)?(?:fileParallelism|file-parallelism)[`'\"]\s*$",
        text,
    ))


def _words(command: str) -> list[str] | None:
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    # Only literal arguments. No shell expansion, control operators or assignments.
    if not words or any(re.search(r"[;$`|&<>\n\r]", word) for word in words):
        return None
    return words


def test_command(command: str, root: Path) -> tuple[str, list[str], str] | None:
    """Recognise vitest/jest directly or through one literal package test script.

    Returns runner, runner arguments and repository-relative working folder. Managers are
    resolved to the script and then bypassed: no install, lifecycle hooks or unknown program
    ever receives runner options.
    """
    folder = "."
    if command.startswith("cd "):
        prefix, sep, command = command.partition(" && ")
        try:
            cd = shlex.split(prefix)
        except ValueError:
            return None
        if not sep or len(cd) != 2 or not safe_folder(cd[1]):
            return None
        folder = cd[1]
    cwd = root / folder
    if not cwd.is_dir() or not cwd.resolve().is_relative_to(root.resolve()):
        return None
    words = _words(command)
    if words is None:
        return None
    if words[0] in {"npm", "pnpm", "yarn"}:
        rest = words[1:]
        if rest[:1] == ["run"]:
            rest = rest[1:]
        if not rest or rest[0] != "test":
            return None
        tail = rest[1:]
        if tail[:1] == ["--"]:
            tail = tail[1:]
        manifest = cwd / "package.json"
        if manifest.is_symlink():
            return None
        try:
            package = json.loads(manifest.read_text("utf-8"))
            script = package.get("scripts", {}).get("test")
        except (OSError, ValueError, AttributeError):
            return None
        if not isinstance(script, str):
            return None
        words = _words(script)
        if words is None:
            return None
        words += tail
    if words[:1] == ["npx"]:
        words = words[1:]
    if not words or words[0] not in {"vitest", "jest"}:
        return None
    kind, args = words[0], words[1:]
    if kind == "vitest" and args[:1] == ["run"]:
        args = args[1:]
    # Recognised runner options only. Paths/default collection are replaced by changed test
    # files. Refusing everything else is safer than silently changing command semantics.
    allowed = {"--globals", "--silent", "--runInBand", "--no-color", "--no-colors",
               "--coverage", "--passWithNoTests"}
    if any(arg not in allowed for arg in args):
        return None
    if kind == "vitest" and "--runInBand" in args:
        return None
    return kind, args, folder
