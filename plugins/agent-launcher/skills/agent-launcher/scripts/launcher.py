#!/usr/bin/env python3
"""Headless sandboxed reviewer for one commit.

``review`` and ``reviewer-probe`` are the commands. Session creation is the
installed ``agents`` wrapper in the Herdr app, and herdr core (``hc``) after
that. Both are documented in the skill. This file does not launch a pane.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

# How each agent takes a model and a reasoning effort. The reviewer refuses
# these flags on the commands it builds; the keys stay aligned with that table.
VENDOR_FLAGS: dict[str, dict[str, str]] = {
    "claude": {"model": "--model {value}", "effort": "--effort {value}"},
    "codex": {"model": "--model {value}", "effort": "-c model_reasoning_effort={value}"},
    "grok": {"model": "-m {value}", "effort": "--reasoning-effort {value}"},
    "muse": {"model": "--model {value}", "effort": "--reasoning-effort {value}"},
    "agy": {"model": "--model {value}", "effort": "--effort {value}"},
    # opencode wants the model as `provider/model`, e.g. `deepseek/deepseek-v4-pro`; a bare name is
    # rejected at startup with "Invalid model format".
    "opencode": {"model": "-m {value}"},
}


class TimedOutProcess(subprocess.CompletedProcess[str]):
    """A process result synthesized specifically from ``subprocess.TimeoutExpired``."""


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command. Pass ``timeout`` for anything that can hang.

    A timeout is reported as a non-zero result when ``check`` is false, so callers handle it as
    "no answer" rather than as a crash. ``check=False`` also turns a missing program into a result:
    ``subprocess.run`` raises when the program does not exist.
    """
    try:
        proc = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if check:
            raise SystemExit(f"timed out after {timeout}s while running {cmd[0]!r}") from None
        stdout = (
            exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
        )
        stderr = (
            exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        )
        return TimedOutProcess(
            cmd,
            returncode=124,
            stdout=stdout or "",
            stderr=stderr or f"timed out after {timeout}s while running {cmd[0]!r}",
        )
    except OSError as exc:
        if check:
            raise SystemExit(f"cannot run {cmd[0]!r}: {exc}") from None
        # 127 is the shell's own "command not found", so a caller reading returncode sees the
        # ordinary shape of a failure rather than a special case.
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr=str(exc))
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"command failed ({proc.returncode}) while running {cmd[0]!r}\n{err}")
    return proc


# --------------------------------------------------------------------------- the targeted reviewer
#
# Issue #158. Saga's targeted reviewer runs headless, never in a Herdr pane: one session per
# review, on a staffed vendor, with that vendor's normal configuration (instruction files, plugins,
# hooks, the subscription sign-in), in a sandbox that keeps its commands to a scratch copy of the
# head commit with no network and no credentials. ``launcher.py review`` starts it and returns its
# answer and a result; ``launcher.py reviewer-probe`` runs the same recipe live and checks every
# denial from outside the session. Every name below carries ``reviewer``.

REVIEWER_RESULT_SCHEMA = "targeted_reviewer_launch.v1"
REVIEWER_PROMPT_ID = "targeted-reviewer-prompt"
REVIEWER_TIMEOUT_SECONDS = 3600
REVIEWER_EXIT_REFUSED = 2
REVIEWER_EXIT_NO_ANSWER = 3
#: Issue #248: the most of an unreadable final message the launcher keeps beside result.json.
REVIEWER_FINAL_MESSAGE_LIMIT = 64 * 1024
REVIEWER_EXIT_TIMEOUT = 124
REVIEWER_DEFAULT_CAP = 5
#: Issue #223. The dollar ceiling the probe's own Claude launch carries. One shell command on a
#: small model never comes near it, and it still bounds a runaway.
REVIEWER_PROBE_CEILING_USD = "1.00"
#: A ceiling is a positive decimal with at most two places, written as the operator typed it.
_REVIEWER_CEILING = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?")

#: Every launcher vendor's flags that turn off instruction files, plugins, hooks or skills, or
#: remove its sandbox or approvals, read from each vendor's own ``--help`` on 2026-10-06. No
#: reviewer launch may pass one; a test keeps the keys equal to ``VENDOR_FLAGS``.
REVIEWER_FORBIDDEN_FLAGS: dict[str, tuple[str, ...]] = {
    "claude": (
        "--bare", "--safe-mode", "--restricted", "--disable-slash-commands",
        "--strict-mcp-config", "--setting-sources", "--dangerously-skip-permissions",
        "bypassPermissions",
    ),
    "codex": (
        "--ignore-user-config", "--ignore-rules", "--disable",
        "--dangerously-bypass-approvals-and-sandbox",
    ),
    # Issue #223 added ``--trust`` (trusts the folder, so the reviewed change's own hooks load) and
    # the ``--sandbox`` values ``off`` and ``devbox``, read from grok 1.0.50's help and sandbox guide.
    "grok": (
        "--always-approve", "--system-prompt-override", "bypassPermissions", "--trust", "off",
        "devbox",
    ),
    # Issue #223 added ``--disable-approval`` and ``--trust-workspace`` (loads the reviewed
    # change's own rules and skills), read from muse 1.4.6's ``exec --help``.
    "muse": (
        "--disable-sandbox", "--no-foreign-personal-context", "--disable-reminders", "--yolo",
        "never", "--disable-approval", "--trust-workspace",
    ),
    "agy": ("--dangerously-skip-permissions", "--disable-slash-commands"),
    "opencode": ("--auto",),
}

#: Variables that make a vendor sign in with an API key instead of the subscription. The launch
#: removes them from the session's environment.
REVIEWER_API_KEY_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_PROFILE",
)
REVIEWER_API_KEY_PREFIXES = ("CLAUDE_CODE_USE_",)

#: A variable whose name looks like a credential never reaches the reviewer's sandboxed commands,
#: even if it is added to the allow-list below.
REVIEWER_CREDENTIAL_NAME = re.compile(
    r"TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|SESSION|COOKIE", re.IGNORECASE
)
#: The only launch-environment variables the reviewer's sandboxed commands receive (issue #189).
#: Every other name is denied, whatever it is called. Measured on Claude Code 2.1.292: a Python
#: test and git run with exactly these. The sandbox adds its own proxy and runtime variables, which
#: are not in the launch environment.
REVIEWER_ENVIRONMENT_ALLOWED = (
    "PATH",  # finds the toolchain
    "HOME",  # tools resolve ``~`` against it; the sandbox blocks reads under it
    "USER",  # some tools look up the current user
    "LOGNAME",  # the same, by its older name
    "SHELL",  # the shell commands run in
    "TERM",  # terminal-aware output
    "LANG",  # text encoding
    "LC_ALL",  # text encoding, when set
    "LC_CTYPE",  # text encoding, when set
    "TZ",  # time zone
    "TMPDIR",  # where temp files go; the sandbox sets its own
    "GIT_CONFIG_GLOBAL",  # points git at /dev/null, because home is unreadable
    "CARGO_HOME",  # issue #262: the launcher's read-only cargo home beside the copy
    "CARGO_NET_OFFLINE",  # issue #262: cargo never tries the network it is denied
    "RUSTUP_HOME",  # issue #262: a rustup proxy finds its toolchains
    "RUSTUP_TOOLCHAIN",  # issue #262: the operator's toolchain choice, when set
    "VIRTUAL_ENV",  # the packet's Python environment, set only by the launcher
)
#: Credential files and directories. The sandbox blocks the whole home directory, so this list no
#: longer feeds ``denyRead``. It feeds the permission layer's ``Read`` deny rules, and the check
#: that a path allowed back re-opens none of these.
REVIEWER_CREDENTIAL_PATHS = (
    "~/.ssh",
    "~/.aws",
    "~/.config/gh",
    "~/.gnupg",
    "~/.netrc",
    "~/.docker/config.json",
    "~/.kube",
    "~/.config/gcloud",
    "~/.azure",
    "~/.claude/.credentials.json",
    "~/.codex/auth.json",
    "~/.git-credentials",
    "~/.pypirc",
    "~/.cargo/credentials",
    "~/.cargo/credentials.toml",
    "~/.terraform.d",
    "~/.vault-token",
    "~/.config/hub",
    "~/.local/share/keyrings",
    "~/.npmrc",
)
#: Directories under home that hold many tools' state; allowing one back would re-open them all.
REVIEWER_SHARED_ROOTS = ("~/.config", "~/.local", "~/.local/share", "~/.cache", "~/Library")
#: Interpreters a reviewed repository's tests run on. When one on the session's ``PATH`` lives
#: under home, its install is allowed back: a binary under a blocked home runs but cannot read its
#: own files (measured on Claude Code 2.1.292).
REVIEWER_TOOLCHAIN_COMMANDS = (
    ("python3", "python3 on the session PATH resolves here; its standard library and packages"),
    ("node", "node on the session PATH resolves here; its bundled libraries"),
    # Issue #262. A rustup proxy under ``~/.cargo``: that prefix holds cargo's credentials file,
    # so only its ``bin`` comes back, with rustup's toolchains (``reviewer_rustup_paths``). A
    # Homebrew or system cargo sits outside home and needs nothing.
    ("cargo", "cargo on the session PATH resolves here; its executables and libraries"),
    ("rustc", "rustc on the session PATH resolves here; its executables and libraries"),
)
#: The parts of a toolchain install allowed back, never the whole install.
REVIEWER_TOOLCHAIN_PARTS = (
    ("bin", "its executables"),
    ("lib", "its standard library and packages"),
    ("pyvenv.cfg", "the marker a virtual environment's interpreter reads at start"),
)
#: Paths in the scratch copy that tools write and nobody edits: Python's temp-directory fallback
#: (the sandbox denies the system temp roots, so ``tempfile`` falls back to the working directory),
#: pytest's caches and compiled bytecode; since issue #262 cargo's ``target/`` and a ``Cargo.lock``
#: that a build writes where the head has none. They never count as a change. ``.claude/`` is not among
#: them: Claude leaves only an empty ``.claude/.cc-writes/`` there (measured on 2.1.292), so a file
#: under it is one the session wrote, and saga's check refuses it.
#:
#: Tool caches the reviewer's own checks write into the working tree are listed too. Each entry is
#: a folder or a file name that is generated and never edited, matched whole at a path boundary,
#: so ``src/ruff_cache.py`` and ``.ruff_cache.md`` do not match. An entry counts only for a path
#: that is new: the ignore applies to the ``added`` list, so a tracked file at one of these paths
#: that the session edits or deletes is a change like any other.
#:
#: - ``.pytest_cache/`` at any depth: ``cd pkg && pytest`` writes ``pkg/.pytest_cache/``.
#: - ``pytest-of-<user>/`` at any depth: pytest's ``tmp_path`` tree, which lands in the folder a
#:   test ran from when Python's ``tempfile`` falls back to the working directory. Its
#:   ``current`` links are matched by ``REVIEWER_PYTEST_LINK``. ``__pycache__/`` and ``*.pyc`` are
#:   ignored at any depth as well.
#: - ``.ruff_cache/`` and ``.mypy_cache/``: ruff's and mypy's result caches, written wherever the
#:   tool runs. ``.hypothesis/``: Hypothesis's example database, written beside the tests it runs.
#: - ``.eslintcache``: ESLint's cache file, written by ``eslint --cache``.
#: - ``*.tsbuildinfo``: TypeScript's incremental-build record, written by ``tsc`` when
#:   ``incremental`` is on. A suffix, so a file merely containing the word does not match.
#:
#: Entries that other things also use are matched only at a package root; see
#: ``REVIEWER_PACKAGE_CACHES``.
REVIEWER_SCRATCH_IGNORED = re.compile(
    r"^(tmp[a-z0-9_]{8}/|target/)|(^|/)pytest-of-[^/]+/"
    r"|(^|/)\.pytest_cache/|(^|/)__pycache__/|\.pyc$"
    r"|(^|/)Cargo\.lock$"
    r"|(^|/)(\.ruff_cache|\.mypy_cache|\.hypothesis)/"
    r"|(^|/)\.eslintcache$|(^|/)[^/]+\.tsbuildinfo$"
)
#: The links pytest makes in its ``tmp_path`` tree, at any depth: ``pytest-current`` beside the
#: numbered runs, and ``<test>current`` inside a run, each pointing at a numbered folder beside
#: it (see :func:`reviewer_pytest_link`). Every other link the session makes is still reported.
REVIEWER_PYTEST_LINK = re.compile(
    r"(?:^|/)pytest-of-[^/]+/(?:(?P<run>pytest-)current|pytest-[0-9]+/(?P<test>[^/]+)current)$"
)
#: Entries whose names other things also use, so each counts only at a package root: the folder
#: that holds one of the named marker files in the exported copy (or, where noted, the root of the
#: copy itself). Under a folder with no marker, or in a different place, the same name is an
#: ordinary change and is refused. Like the list above they apply to new paths only.
#:
#: - ``node_modules/.vite/``, ``node_modules/.cache/``: Vite's and Vitest's result and transform
#:   caches, and the shared cache folder that Jest, Babel, ESLint and Prettier write when
#:   ``find-cache-dir`` places a cache (marker ``package.json``).
#: - ``coverage/``, ``.nyc_output/``: the report and raw data that Jest, Vitest, c8 and nyc write
#:   when a run asks for coverage (marker ``package.json``).
#: - ``.coverage`` and ``.coverage.<host>.<pid>.<random>``: coverage.py's data file, written to
#:   the folder the tests run from (the root of the copy, or beside ``pyproject.toml``,
#:   ``setup.py`` or ``setup.cfg``).
#: - ``.dart_tool/``: ``dart pub get``, ``dart analyze`` and ``dart test`` write the package
#:   configuration and test caches there (marker ``pubspec.yaml``; measured with Dart 3.13).
#:   ``pubspec.lock`` is what ``dart pub get`` and ``dart run`` write when the package does not
#:   track one, beside ``pubspec.yaml``.
#: - ``.build/``: SwiftPM's build folder, written by ``swift build`` and ``swift test``, including a
#:   ``debug`` symlink (marker ``Package.swift``; measured with Swift 6.4). ``Package.resolved``
#:   is what SwiftPM writes beside ``Package.swift`` when it resolves dependencies.
#: - ``cdk.out/``: the folder ``cdk synth`` writes the synthesised templates to (marker
#:   ``cdk.json``).
#:
#: A new symlink inside one of the folders is ignored with it: the tools make them (SwiftPM's
#: ``.build/debug``), and saga reads nothing under a path that is ignored. A symlink that replaces
#: or retargets a tracked path is never ignored, and a link anywhere else is still refused.
REVIEWER_PACKAGE_CACHES = (
    (re.compile(r"(?:^|(?<=/))node_modules/\.(?:vite|cache)/"), ("package.json",), False),
    (re.compile(r"(?:^|(?<=/))(?:coverage|\.nyc_output)/"), ("package.json",), False),
    (
        re.compile(r"(?:^|(?<=/))\.coverage(?:\.[^/.]+\.\d+\.[0-9A-Za-z]+)?$"),
        ("pyproject.toml", "setup.py", "setup.cfg"), True,
    ),
    (re.compile(r"(?:^|(?<=/))\.dart_tool/"), ("pubspec.yaml",), False),
    (re.compile(r"(?:^|(?<=/))pubspec\.lock$"), ("pubspec.yaml",), False),
    (re.compile(r"(?:^|(?<=/))\.build/"), ("Package.swift",), False),
    (re.compile(r"(?:^|(?<=/))Package\.resolved$"), ("Package.swift",), False),
    (re.compile(r"(?:^|(?<=/))cdk\.out/"), ("cdk.json",), False),
)


def reviewer_in_package_cache(path: str, manifest: Mapping[str, str]) -> bool:
    """True when *path* is a cache entry at a package root of the exported copy."""
    for pattern, markers, root_of_copy in REVIEWER_PACKAGE_CACHES:
        for found in pattern.finditer(path):
            root = path[:found.start()]
            if (root_of_copy and not root) or any(root + marker in manifest for marker in markers):
                return True
    return False
#: Issue #262: saga's prepare vendors the head's crates.io dependencies into the packet and
#: names them in this file. The schema and directory rules match saga's ``review_dependencies``.
REVIEWER_DEPENDENCIES_FILE = "dependencies.json"
REVIEWER_DEPENDENCIES_SCHEMA = "saga.review_dependencies.v1"
#: The start of the name the cargo home gives the vendored sources. Each launch adds a random
#: suffix, so a commit's own cargo configuration cannot name the source to redefine or chain it.
REVIEWER_VENDORED_SOURCE = "saga-vendored"


#: The change under review is untrusted. Claude acts on a project's ``.claude/`` directory (settings
#: with hooks, ``apiKeyHelper`` and environment; rules; skills and agents, whose frontmatter can
#: carry hooks) and its ``.mcp.json`` without a trust prompt in ``-p``, and hooks and MCP servers
#: run outside the command sandbox. So every one of them, at any depth, is withheld from the copy.
#: The operator's own user-level configuration is what "normal configuration" means, and it loads.
REVIEWER_UNTRUSTED_DIRS = (".claude",)
REVIEWER_UNTRUSTED_FILES = (".mcp.json",)
#: Instruction files Claude loads from the working directory and, on demand, from subdirectories.
#: Claude Code reads ``AGENTS.md`` when no ``CLAUDE.md`` is present and expands ``@`` imports in
#: it (measured on 2.1.299), so an import that leaves the copy withholds that file too (#277).
REVIEWER_INSTRUCTION_NAMES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md")
def _reviewer_fold(name: str) -> str:
    """A name as a forgiving file system may match it: compatibility-normalised and casefolded.

    A case-insensitive file system loads ``.CLAUDE`` as ``.claude``; folding more than any file
    system does only withholds more, never less.
    """
    return unicodedata.normalize("NFKC", name).casefold()


_REVIEWER_INSTRUCTION_NAMES = frozenset(_reviewer_fold(n) for n in REVIEWER_INSTRUCTION_NAMES)
#: How deep Claude follows ``@`` imports.
REVIEWER_IMPORT_DEPTH = 5
#: A deliberately wider net than Claude's own import parser: any ``@`` followed by text up to ASCII
#: whitespace, inside code spans or not, is treated as an import, so no import Claude follows can
#: be missed. A token is safe only when it is a plain relative path: then every reading of it,
#: whatever Claude's parser takes as its end, stays inside the copy.
_REVIEWER_ANY_IMPORT = re.compile(r"@([^ \t\n\r\f\v]+)")
_REVIEWER_IMPORT_TRAILING = "`'\")]}>.,;:!?*"
_REVIEWER_RISKY_IMPORT = re.compile(r"\.\.|~|\$|%|\\|^/|[^\x21-\x7e]")


class ReviewerRefused(Exception):
    """A reviewer launch refused before any session started."""


def reviewer_temp_roots(platform: str | None = None) -> tuple[str, ...]:
    """The system temp roots the reviewer's commands may not write to.

    On macOS ``/tmp`` and ``/var/folders`` are symlinks under ``/private``. The sandbox
    ``denyWrite`` matches the path it is given, so both spellings are named. Linux stays
    ``/tmp`` and ``/var/tmp`` and does not treat ``/private`` as a temp root.
    """
    if (platform or sys.platform) == "darwin":
        return ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
    return ("/tmp", "/var/tmp")


def reviewer_denied_variables(env: Mapping[str, str]) -> list[str]:
    """The environment variables hidden from sandboxed commands: every name off the allow-list."""
    return sorted(
        name for name in env
        if name not in REVIEWER_ENVIRONMENT_ALLOWED or REVIEWER_CREDENTIAL_NAME.search(name)
    )


def reviewer_session_environment(
    env: Mapping[str, str],
    variables: Sequence[str] = REVIEWER_API_KEY_VARIABLES,
    prefixes: Sequence[str] = REVIEWER_API_KEY_PREFIXES,
) -> dict[str, str]:
    """The session's environment: everything, except what would sign in with an API key.

    *variables* and *prefixes* are the vendor's API-key names; Claude's are the defaults. Git fails
    outright when it cannot read its global configuration, and the sandbox makes the home
    directory unreadable, so git is pointed at ``/dev/null`` instead (measured on 2.1.292).
    """
    kept = {
        name: value
        for name, value in env.items()
        if name not in variables and not name.startswith(tuple(prefixes))
    }
    kept["GIT_CONFIG_GLOBAL"] = os.devnull
    return kept


def _reviewer_home(env: Mapping[str, str]) -> Path:
    return Path(env.get("HOME") or Path.home())


def _reviewer_expand(path: str, home: Path) -> Path:
    if path == "~":
        return home
    return home / path[2:] if path.startswith("~/") else Path(path)


def _reviewer_forms(path: Path) -> set[Path]:
    """*path* as written, with ``..`` collapsed, and resolved through every symlink.

    Resolve the path as given, then collapse ``..``. Collapsing first cancels a
    symlink and the ``..`` that follows it, so ``link/..`` where ``link`` points
    into a denied temp root would look like it sits outside that root.
    """
    written = Path(os.path.normpath(path))
    try:
        resolved = Path(os.path.normpath(path.resolve()))
    except (OSError, RuntimeError):
        return {written}
    return {written, resolved}


def reviewer_allowed_read_problem(path: Path, home: Path) -> str | None:
    """Why allowing *path* back inside the blocked home would re-open too much, or ``None``.

    A path fails when, as written or resolved, it is the home directory or above it, is a shared
    root such as ``~/.config``, or is equal to, inside, or above a credential path. Being inside
    home is not a failure: the scratch copy lives under ``~/.cache``.
    """
    forms = _reviewer_forms(home / path)
    homes = _reviewer_forms(home)
    for form in forms:
        if any(form == h or h.is_relative_to(form) for h in homes):
            return f"{path} is the home directory or above it"
        for root in REVIEWER_SHARED_ROOTS:
            if any(form == r for h in homes for r in _reviewer_forms(_reviewer_expand(root, h))):
                return f"{path} is the shared root {root}"
        for credential in REVIEWER_CREDENTIAL_PATHS:
            for h in homes:
                for c in _reviewer_forms(_reviewer_expand(credential, h)):
                    if form == c or form.is_relative_to(c) or c.is_relative_to(form):
                        return f"{path} is, is inside, or holds the credential path {credential}"
    return None


def reviewer_toolchain_paths(
    env: Mapping[str, str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The toolchain installs under home to allow back, and the candidates dropped, with reasons.

    For each interpreter on the session's ``PATH``, two candidates: the prefix as found (a virtual
    environment's directory) and the prefix it resolves to (the real install). A candidate outside
    home needs no allow-back; one that would re-open too much is dropped. Of a candidate kept, only
    the parts in ``REVIEWER_TOOLCHAIN_PARTS`` that exist are allowed back.
    """
    home = _reviewer_home(env)
    homes = _reviewer_forms(home)
    allowed: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    rust_under_home = False
    for command, reason in REVIEWER_TOOLCHAIN_COMMANDS:
        found = shutil.which(command, path=env.get("PATH", ""))
        if not found:
            continue
        binary = Path(os.path.normpath(Path(found).absolute()))
        if command in ("cargo", "rustc") and any(binary.is_relative_to(h) for h in homes):
            rust_under_home = True
        for candidate in (binary.parent.parent, binary.resolve().parent.parent):
            if str(candidate) in seen or not any(candidate.is_relative_to(h) for h in homes):
                continue
            seen.add(str(candidate))
            problem = reviewer_allowed_read_problem(candidate, home)
            if problem:
                dropped.append({"path": str(candidate), "reason": problem})
                # Issue #262: rustup's ``~/.cargo`` holds cargo's credentials beside ``bin/``.
                # For cargo and rustc only, the folder holding the binary comes back on its own
                # when it passes the check; any other interpreter there is still dropped.
                folder = binary.parent
                if (command in ("cargo", "rustc") and "credential path" in problem
                        and str(folder) not in seen
                        and folder.is_relative_to(candidate)
                        and reviewer_allowed_read_problem(folder, home) is None):
                    seen.add(str(folder))
                    allowed.append({"path": str(folder), "reason": f"{reason}; its executables, "
                                    "without the prefix that holds a credential path"})
                continue
            # Only the parts an interpreter reads, never the prefix itself: a prefix such as
            # ``~/.sometool`` can hold that tool's own ``.env`` beside ``bin/`` (measured: a uv
            # interpreter runs a real test with just ``bin`` and ``lib`` allowed back).
            for part, why in REVIEWER_TOOLCHAIN_PARTS:
                path = candidate / part
                if (path.exists() or path.is_symlink()) and str(path) not in seen:
                    seen.add(str(path))
                    trouble = reviewer_allowed_read_problem(path, home)
                    entry = {"path": str(path), "reason": trouble or f"{reason}; {why}"}
                    (dropped if trouble else allowed).append(entry)
    if rust_under_home:
        for path, why in reviewer_rustup_paths(env):
            if str(path) in seen:
                continue
            seen.add(str(path))
            trouble = reviewer_allowed_read_problem(path, home)
            entry = {"path": str(path), "reason": trouble or why}
            (dropped if trouble else allowed).append(entry)
    return sorted(allowed, key=lambda i: i["path"]), sorted(dropped, key=lambda i: i["path"])


def reviewer_rustup_home(env: Mapping[str, str]) -> Path:
    """The rustup home: ``RUSTUP_HOME``, or ``.rustup`` in the session's home."""
    given = env.get("RUSTUP_HOME")
    return Path(given) if given else _reviewer_home(env) / ".rustup"


def reviewer_rustup_paths(env: Mapping[str, str]) -> list[tuple[Path, str]]:
    """What a rustup proxy under home reads to run a toolchain (issue #262), when it exists.

    Only ``toolchains`` and ``settings.toml``; never the rustup home itself, which also keeps
    downloads and update state.
    """
    rustup = reviewer_rustup_home(env)
    homes = _reviewer_forms(_reviewer_home(env))
    if not any(rustup.absolute().is_relative_to(h) for h in homes):
        return []
    return [
        (rustup / part, f"rustup's {why}, which a rustup cargo or rustc runs (issue #262)")
        for part, why in (("toolchains", "installed toolchains"),
                          ("settings.toml", "default toolchain"))
        if (rustup / part).exists()
    ]


def reviewer_ceiling_problem(amount: str | None) -> str | None:
    """Why *amount* is not a dollar ceiling, or ``None``: a positive decimal, two places at most."""
    if amount is None:
        return "no --max-budget-usd was given"
    if not _REVIEWER_CEILING.fullmatch(amount) or float(amount) <= 0:
        return f"--max-budget-usd {amount!r} is not a positive dollar amount with two places at most"
    return None


#: Schema keys Claude Code 2.1.301 cannot take in ``--json-schema``. Measured: a schema declaring
#: ``"$schema": "https://json-schema.org/draft/2020-12/schema"`` is refused before the session
#: starts (``--json-schema is not a valid JSON Schema: no schema with key or ref ...``). Neither key
#: changes what the schema accepts.
REVIEWER_CLAUDE_SCHEMA_DROPPED = ("$schema", "$id")


def reviewer_claude_schema_text(answer_schema: str) -> str:
    """The answer schema as compact JSON without the keys Claude's validator cannot resolve."""
    schema = json.loads(answer_schema)
    for key in REVIEWER_CLAUDE_SCHEMA_DROPPED:
        schema.pop(key, None)
    return json.dumps(schema, separators=(",", ":"), ensure_ascii=False)


def reviewer_claude_argv(
    model: str,
    effort: str | None,
    settings_path: Path,
    *,
    max_budget_usd: str | None = None,
    executable: Path | None = None,
    prompt_path: Path | None = None,
    answer_schema: str | None = None,
) -> list[str]:
    """Claude's reviewer argv: headless, sandboxed through ``--settings``, JSON result, a ceiling.

    Issue #223: every Claude reviewer launch carries ``--max-budget-usd``; there is no default, so a
    caller that forgets one is refused. Claude runs as ``claude`` from ``PATH`` and reads its prompt
    on standard input, so *executable* and *prompt_path* are unused here.

    Issue #248: *answer_schema*, the answer schema as compact JSON text, becomes ``--json-schema``,
    so Claude validates the answer and returns it in the result's ``structured_output`` field
    instead of leaving it to a prompt line. Grok and Muse take the keyword and ignore it.
    """
    problem = reviewer_ceiling_problem(max_budget_usd)
    if problem:
        raise ReviewerRefused(f"a Claude reviewer launch needs a spending ceiling: {problem}")
    argv = ["claude", "-p", "--model", model]
    if effort:
        argv += ["--effort", effort]
    argv += [
        "--permission-mode", "dontAsk",
        "--settings", str(settings_path),
        "--output-format", "json",
        "--no-session-persistence",
    ]
    if answer_schema:
        argv += ["--json-schema", reviewer_claude_schema_text(answer_schema)]
    return argv + ["--max-budget-usd", str(max_budget_usd)]


#: Issue #225: Claude runs every Bash command, hook and MCP server as ``<prefix> '<command>'``
#: when ``CLAUDE_CODE_SHELL_PREFIX`` names a file, and only after the shell around it has read its
#: start-up files. Measured on Claude Code 2.1.296: a variable a ``BASH_ENV`` file exports reaches a
#: sandboxed command, because ``credentials.envVars`` denies only names the launch environment
#: had. The reviewer's prefix rebuilds a sandboxed command's environment from the allow-list after
#: start-up, in a bash that reads no start-up file. It lives beside the copy, never inside it.
REVIEWER_SHELL_PREFIX = "CLAUDE_CODE_SHELL_PREFIX"


def reviewer_claude_shell_paths(copy: Path) -> tuple[Path, Path]:
    """The reviewer's shell prefix and its sentinel, both beside *copy* in the launch root.

    Sandboxed commands may read the prefix's directory but not the sentinel; the prefix reads the
    sentinel to tell a hook or an MCP server, which run outside the sandbox, from a command.
    """
    root = copy.resolve().parent
    return root / "shell" / "reviewer-shell.sh", root / "unsandboxed"


def reviewer_claude_temp_dir(copy: Path) -> Path:
    """The reviewer's own temp folder, beside *copy* in the launch root and never inside it.

    The sandbox denies writes to every system temp root, and Claude's own temp directory for
    sandboxed commands sits under one of them, so without this folder a reviewer's test that
    writes a temp file fails for a reason the replay, which gives each test a writable
    ``TMPDIR``, does not share. Outside the copy, so the scratch-change comparison never sees it.
    """
    return copy.resolve().parent / "tmp"


def reviewer_claude_shell_script(
    sentinel: Path, token: str, temp: Path | None = None, python_env: Path | None = None,
    dart_env: tuple[Path, Path] | None = None,
    *, path_front: Sequence[Path] = (),
) -> str:
    """The prefix: outside the sandbox it runs the command as given; inside, on the allow-list.

    The sentinel holds *token*. Only a process outside the sandbox can read it, so anything else,
    a denied read or a missing file included, filters: the check fails closed. With *temp*, the
    prefix sets ``TMPDIR``, ``TEMP`` and ``TMP`` to that folder. Claude's own command string then
    exports ``TMPDIR`` again, to its sandbox temp folder, which the reviewer may not write. So the
    bash the prefix starts runs Claude's command string through ``eval`` under a ``DEBUG`` trap
    that, the first time ``TMPDIR`` differs from *temp* (right after Claude's export), sets it
    back and removes itself: node's ``os.tmpdir()``, bun, Go, Rust and ``mktemp``, which read
    ``TMPDIR`` alone, see the reviewer's folder, and so does Python. The trap keeps ``$_`` and is
    gone before the reviewer's own command runs, so ``$_``, ``PIPESTATUS`` (which any ``DEBUG``
    trap resets on bash 3.2) and a ``TMPDIR`` the command sets itself, by ``export`` or a leading
    assignment, all behave as they would without the prefix.
    *path_front* folders come first on ``PATH``, after the Python environment's ``bin``.
    Sandboxed commands also run under ``umask 022``, as saga's replay does; it is never reached
    outside the sandbox.
    """
    names = [n for n in REVIEWER_ENVIRONMENT_ALLOWED if not REVIEWER_CREDENTIAL_NAME.search(n)]
    for name in names:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"{name!r} is not a variable name")
    kept = " ".join(f'${{{n}+"{n}=${n}"}}' for n in names)
    if temp is not None:
        # Last, so it wins over the TMPDIR the allow-list passed on. Claude's own command string
        # then exports TMPDIR again, to its sandbox temp folder under a root the reviewer's
        # settings deny (reviewer_temp_roots): seen live on Claude Code 2.1.311, and the same
        # export is in the 2.1.308 executable. Python's tempfile tries TMPDIR, then TEMP, then
        # TMP, then the system roots, and falls back to the working directory, the scratch copy,
        # when none is writable. TEMP and TMP name the reviewer's folder too, so Python's temp
        # files land there; the DEBUG trap below restores TMPDIR for every other tool.
        quoted_temp = shlex.quote(str(temp))
        kept += f" TMPDIR={quoted_temp} TEMP={quoted_temp} TMP={quoted_temp}"
    front = [str(path) for path in path_front]
    if python_env is not None:
        # Sandboxed commands only: the launcher's environment, whose bin holds just python3 and
        # python, first on PATH. The vendor process's own PATH is never changed.
        kept += f" VIRTUAL_ENV={shlex.quote(str(python_env))}"
        front.insert(0, str(python_env / "bin"))
    kept += reviewer_dart_prefix(dart_env, front)
    if front:
        kept += f' PATH={shlex.quote(os.pathsep.join(front))}:"${{PATH-}}"'
    run = '-c "$1"'
    if temp is not None:
        # Claude's command string exports its own TMPDIR before the command. The trap runs before
        # each simple command until it sees that export, then restores the reviewer's TMPDIR and
        # removes itself; it saves and restores ``$_``, and bash keeps ``$?`` across a trap.
        reset = (f'reviewer_last=$_; if [ "${{TMPDIR-}}" != {quoted_temp} ]; then '
                 f'TMPDIR={quoted_temp}; trap - DEBUG; fi; : "$reviewer_last"')
        body = f'trap {shlex.quote(reset)} DEBUG; reviewer_command=$1; shift; eval "$reviewer_command"'
        run = f'-c {shlex.quote(body)} reviewer-shell "$1"'

    read = f"/bin/cat {shlex.quote(str(sentinel))} 2>/dev/null"
    return (
        "#!/bin/sh\n"
        "# agent-launcher's reviewer shell (issue #225), written for one Claude reviewer launch.\n"
        "# Claude runs each command as: <this file> '<command>'. Outside the sandbox (a hook\n"
        "# or an MCP server) the sentinel is readable and the command runs as it would without\n"
        "# this file. Inside it, the command runs with only the reviewer's allowed variables,\n"
        "# in a bash that reads no start-up file, so nothing a start-up file exported reaches it.\n"
        f'if [ "$({read})" = {shlex.quote(token)} ]; then\n'
        '  exec /bin/sh -c "$1"\n'
        "fi\n"
        'case "${SHELL-}" in\n'
        '  */bash) reviewer_bash=$SHELL ;;\n'
        "  *) reviewer_bash=/bin/bash ;;\n"
        "esac\n"
        "# Same file-creation mask as saga's replay (RERUN_UMASK, 022), so a file the reviewer's\n"
        "# test creates gets the mode the replay gives it, not one from the launching harness.\n"
        "umask 022 || exit 1\n"
        f'exec /usr/bin/env -i {kept} "$reviewer_bash" --noprofile --norc {run}\n'
    )


def reviewer_claude_materialize(
    settings: Mapping[str, Any], root: Path, copy: Path, *,
    path_front: Sequence[Path] = (), **_options: Any,
) -> tuple[Path, dict[str, str]]:
    """Write the settings, shell prefix, sentinel and temp folder beside the copy; name the prefix.

    *path_front* goes first on a sandboxed command's ``PATH`` (see
    :func:`reviewer_toolchain_front`)."""
    path, _ = reviewer_settings_materialize(settings, root, copy)
    prefix, sentinel = reviewer_claude_shell_paths(copy)
    temp = reviewer_claude_temp_dir(copy)
    token = os.urandom(16).hex()
    sentinel.write_text(token, "utf-8")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    temp.mkdir(exist_ok=True)
    temp.chmod(0o700)
    python_env = reviewer_python_env_dir(root)
    dart_env = reviewer_dart_env_dir(root)
    prefix.write_text(reviewer_claude_shell_script(
        sentinel, token, temp,
        python_env if (python_env / "pyvenv.cfg").is_file() else None,
        (dart_env, reviewer_dart_pub_cache_dir(copy))
        if (dart_env / "bin" / "dart").is_symlink() else None,
        path_front=path_front,
    ), "utf-8")
    prefix.chmod(0o755)
    return path, {REVIEWER_SHELL_PREFIX: str(prefix)}


#: What the Dart CLI needs in a sandboxed command: telemetry off, because it otherwise opens a
#: file under the unreadable home and exits 255; and no HTTP retry, because ``dart test`` asks
#: pub.dev for version listings the packet does not keep and would wait out the time limit on the
#: denied network. They match saga's ``review_dependencies_dart.RUN_FLAGS``.
REVIEWER_DART_FLAGS = (("DASH__SUPPRESS_ANALYTICS", "true"), ("PUB_MAX_HTTP_RETRIES", "0"))


def reviewer_packet_dart(packet: Path) -> tuple[Path, str] | None:
    """The packet's pub cache and the SDK version that fetched it, or ``None``.

    Saga's prepare fetches a Dart head's pub.dev packages into ``dependencies/dart/pub-cache``.
    The entry counts only when it says ``installed``, records ``sdk.version``, and names a
    relative directory inside the packet with no symlink along the way; the rules match saga's
    ``review_dependencies_dart``.
    """
    try:
        data = json.loads((packet / REVIEWER_DEPENDENCIES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != REVIEWER_DEPENDENCIES_SCHEMA:
        return None
    entry = data.get("dart")
    if not isinstance(entry, dict) or entry.get("state") != "installed":
        return None
    sdk = entry.get("sdk")
    version = sdk.get("version") if isinstance(sdk, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+[A-Za-z0-9.+-]*", version):
        return None
    relative = entry.get("directory")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    parts = Path(relative).parts
    if any(part in ("", ".", "..") for part in parts) or packet.is_symlink():
        return None
    cursor = packet
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    if not cursor.is_dir() or not _reviewer_inside(cursor, packet):
        return None
    return cursor.resolve(), version


def reviewer_dart_sdk(env: Mapping[str, str]) -> tuple[Path, Path, str] | None:
    """The Dart SDK the session's ``PATH`` finds: its real ``dart`` executable, root and version.

    A Flutter install's ``bin/dart`` is a shell wrapper that needs git and writes into the SDK;
    its SDK is ``bin/cache/dart-sdk``. Only a root with a ``version`` file and a ``bin/dart``
    that is not a script counts. The rules match saga's ``review_dependencies_dart.dart_sdk``.
    """
    found = shutil.which("dart", path=env.get("PATH", ""))
    if not found:
        return None
    real = Path(os.path.realpath(found))
    for root in (real.parent.parent, real.parent / "cache" / "dart-sdk"):
        executable = root / "bin" / "dart"
        try:
            if not executable.is_file() or not (root / "version").is_file():
                continue
            with executable.open("rb") as handle:
                if handle.read(2) == b"#!":
                    continue
            version = (root / "version").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        return executable.resolve(), root.resolve(), version
    return None


def reviewer_dart_env_dir(root: Path) -> Path:
    """Where the launcher writes the reviewer's ``dart`` folder: beside the copy."""
    return root / "dart-env"


def reviewer_dart_pub_cache_dir(copy: Path) -> Path:
    """The reviewer's writable pub cache, inside its own temp folder."""
    return reviewer_claude_temp_dir(copy) / "saga-pub-cache"


def reviewer_dart_env(
    root: Path, copy: Path, packages: tuple[Path, str] | None, env: Mapping[str, str]
) -> tuple[Path, Path] | None:
    """Write the reviewer's ``dart`` folder and writable pub cache; return ``(folder, sdk)``.

    The folder's ``bin`` holds only ``dart``, linked to the SDK's real executable. The pub cache
    is a writable folder in the reviewer's temp folder whose ``hosted`` and ``hosted-hashes``
    link to the packet's read-only cache: ``dart test`` records the project there before each
    run. Only the shell prefix gives either to sandboxed commands. ``None`` without a cache, without
    an SDK, with an SDK of another major or minor version than the one that fetched the packages,
    or with an SDK that cannot be allowed back for reading (a ``dart`` that could not run).
    """
    if packages is None:
        return None
    cache, recorded = packages
    sdk = reviewer_dart_sdk(env)
    if sdk is None:
        return None
    executable, sdk_root, version = sdk
    if version.split(".")[:2] != recorded.split(".")[:2]:
        return None
    if reviewer_allowed_read_problem(sdk_root, _reviewer_home(env)) is not None:
        return None
    folder = reviewer_dart_env_dir(root)
    (folder / "bin").mkdir(parents=True, exist_ok=True)
    (folder / "bin" / "dart").symlink_to(executable)
    pub_cache = reviewer_dart_pub_cache_dir(copy)
    pub_cache.mkdir(parents=True, exist_ok=True)
    for part in ("hosted", "hosted-hashes"):
        if (cache / part).is_dir():
            (pub_cache / part).symlink_to(cache / part)
    return folder, sdk_root


def reviewer_dart_reads(
    dart: tuple[Path, Path] | None, packages: tuple[Path, str] | None, home: Path,
    pub_cache: Path | None = None,
) -> list[dict[str, str]]:
    """The read-only allowances a Dart review adds: the ``dart`` folder, the packet's cache, and
    the SDK's root (under home on a Flutter install), unless it would re-open too much."""
    if dart is None or packages is None:
        return []
    cache = packages[0]
    folder, sdk_root = dart
    reads = [
        {"path": str(folder.resolve()),
         "reason": "the reviewer's dart folder beside the copy, read-only; its bin holds only dart"},
        {"path": str(cache), "reason": "the packet's pub packages, read-only"},
    ]
    if pub_cache is not None:
        # The writable cache's own links into the packet: the temp folder is editable, so these
        # paths are stated read-only to deny Claude's file tools a write through them.
        reads += [{"path": str(pub_cache / part),
                   "reason": "a link from the reviewer's pub cache to the packet's, read-only"}
                  for part in ("hosted", "hosted-hashes") if (pub_cache / part).is_symlink()]
    if reviewer_allowed_read_problem(sdk_root, home) is None:
        reads.append({"path": str(sdk_root),
                      "reason": "dart on the session PATH belongs to this SDK; read-only"})
    return reads


def reviewer_dart_prefix(dart_env: tuple[Path, Path] | None, front: list[str]) -> str:
    """The shell prefix's Dart assignments, and the ``dart`` folder added to *front*."""
    if dart_env is None:
        return ""
    folder, pub_cache = dart_env
    front.append(str(folder / "bin"))
    flags = "".join(f" {name}={value}" for name, value in REVIEWER_DART_FLAGS)
    return f" PUB_CACHE={shlex.quote(str(pub_cache))}{flags}"


#: Where saga's prepare installs a JavaScript head's npm packages, and the link the reviewer's
#: copy gets to them.
REVIEWER_NODE_LINK = "node_modules"


def reviewer_packet_node(packet: Path) -> Path | None:
    """The packet's installed npm packages, or ``None`` when there are none to trust.

    The ``node`` entry counts only when it says ``installed`` and names a relative directory
    inside the packet that exists, with no symlink anywhere along the way. The rules match
    saga's ``review_dependencies_node.node_modules``.
    """
    try:
        data = json.loads((packet / REVIEWER_DEPENDENCIES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != REVIEWER_DEPENDENCIES_SCHEMA:
        return None
    entry = data.get("node")
    if not isinstance(entry, dict) or entry.get("state") != "installed":
        return None
    relative = entry.get("directory")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    parts = Path(relative).parts
    if any(part in ("", ".", "..") for part in parts) or packet.is_symlink():
        return None
    cursor = packet
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    if not cursor.is_dir() or not _reviewer_inside(cursor, packet):
        return None
    return cursor.resolve()


def reviewer_link_node_modules(copy: Path, modules: Path | None) -> bool:
    """Link the copy's root ``node_modules`` to the packet's packages, before the scratch
    manifest is taken, so the link is part of the export's baseline and never a change.

    Node's CommonJS and ESM resolvers, bun, vitest and jest all walk up from the importing file to
    the nearest ``node_modules``; ``NODE_PATH`` reaches CommonJS only. A head that already has a
    path by that name keeps it and gets no link.
    """
    link = copy / REVIEWER_NODE_LINK
    if modules is None or os.path.lexists(link):
        return False
    link.symlink_to(modules, target_is_directory=True)
    return True


def reviewer_toolchain_front(env: Mapping[str, str]) -> list[Path]:
    """Folders to put first on a sandboxed command's ``PATH``: the real ``bin`` of a ``node``
    the session's ``PATH`` reaches through a symlink (a link under home such as
    ``~/.local/bin/node``). The sandbox denies reading that link, so a lookup by name would fail
    even though the install it points at is allowed back. ``npm`` and ``npx`` sit beside the
    real ``node``. Never a packet folder."""
    found = shutil.which("node", path=env.get("PATH", ""))
    if not found:
        return []
    real = Path(os.path.realpath(found)).parent
    return [real] if real != Path(found).parent else []


def reviewer_packet_vendor(packet: Path) -> Path | None:
    """The packet's vendored Rust sources (issue #262), or ``None`` when there are none to trust.

    The entry counts only when it says ``fetched`` and names a relative directory inside the
    packet that exists, with no symlink anywhere along the way. Anything else is ignored and the
    reviewer runs without it.
    """
    try:
        data = json.loads((packet / REVIEWER_DEPENDENCIES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != REVIEWER_DEPENDENCIES_SCHEMA:
        return None
    entry = data.get("rust")
    if not isinstance(entry, dict) or entry.get("state") != "fetched":
        return None
    relative = entry.get("directory")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    parts = Path(relative).parts
    if any(part in ("", ".", "..") for part in parts) or packet.is_symlink():
        return None
    cursor = packet
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    if not cursor.is_dir() or not _reviewer_inside(cursor, packet):
        return None
    return cursor.resolve()


def reviewer_packet_python(packet: Path) -> tuple[Path, str] | None:
    """The packet's Python packages and the interpreter version they were installed for, or
    ``None`` when there are none to trust.

    Saga's prepare installs the head's Python dependencies into a plain ``site-packages`` folder
    in the packet: no interpreter, no ``bin``. The entry counts only when it says ``installed``
    or ``partial``, records a ``major.minor.micro`` version, and names a relative directory
    inside the packet with no symlink along the way. The rules match saga's
    ``review_dependencies.python_environment``.
    """
    try:
        data = json.loads((packet / REVIEWER_DEPENDENCIES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != REVIEWER_DEPENDENCIES_SCHEMA:
        return None
    entry = data.get("python")
    if not isinstance(entry, dict) or entry.get("state") not in ("installed", "partial"):
        return None
    interpreter = entry.get("interpreter")
    version = interpreter.get("version") if isinstance(interpreter, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return None
    relative = entry.get("directory")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    parts = Path(relative).parts
    if any(part in ("", ".", "..") for part in parts) or packet.is_symlink():
        return None
    cursor = packet
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    if not cursor.is_dir() or not _reviewer_inside(cursor, packet):
        return None
    return cursor.resolve(), version


def reviewer_python_env_dir(root: Path) -> Path:
    """Where the launcher writes the reviewer's Python environment: beside the copy."""
    return root / "python-env"


def reviewer_python_env(
    root: Path, packages: tuple[Path, str] | None, env: Mapping[str, str]
) -> Path | None:
    """Write the reviewer's own virtual environment over the packet's packages.

    Its ``bin`` holds only ``python3`` and ``python``, links to the ``python3`` the session's
    ``PATH`` finds; ``lib/pythonX.Y/site-packages`` links to the packet's folder. Nothing from the
    packet is ever put on a ``PATH``, and the vendor's own process never sees this one: only the
    shell prefix gives it to sandboxed commands (:func:`reviewer_claude_shell_script`). ``None``
    when there are no packages, no ``python3``, or that interpreter's major and minor version are
    not the ones the packages were installed for.
    """
    if packages is None:
        return None
    site, version = packages
    found = shutil.which("python3", path=env.get("PATH", ""))
    if not found:
        return None
    try:
        proc = subprocess.run(
            [found, "-I", "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
            capture_output=True, text=True, timeout=30, check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    actual = proc.stdout.strip()
    minor = ".".join(version.split(".")[:2])
    if proc.returncode != 0 or ".".join(actual.split(".")[:2]) != minor:
        return None
    real = Path(os.path.realpath(found))
    directory = reviewer_python_env_dir(root)
    (directory / "bin").mkdir(parents=True, exist_ok=True)
    lib = directory / "lib" / f"python{minor}"
    lib.mkdir(parents=True, exist_ok=True)
    (directory / "pyvenv.cfg").write_text(
        f"home = {real.parent}\ninclude-system-site-packages = false\nversion = {actual}\n",
        "utf-8",
    )
    for name in ("python3", "python"):
        (directory / "bin" / name).symlink_to(real)
    (lib / "site-packages").symlink_to(site)
    return directory


def reviewer_offline_python(session_env: dict[str, str]) -> None:
    """Keep the operator's own ``VIRTUAL_ENV`` from the reviewer; the session's ``PATH`` is never
    changed for Python, so the vendor binary and git are found where they always are."""
    session_env.pop("VIRTUAL_ENV", None)


def reviewer_cargo_config(vendor: Path | None, source: str = REVIEWER_VENDORED_SOURCE) -> str:
    """The reviewer's cargo ``config.toml``: offline, and crates.io replaced by *vendor* if given.

    Measured on cargo 1.98.1 (issue #262): ``CARGO_SOURCE_*`` variables alone do not replace a
    source, a ``config.toml`` in ``CARGO_HOME`` does, and cargo builds offline from a directory
    source with that home and the vendored tree both read-only.
    """
    lines = ["# Written by agent-launcher for an offline review (issue #262).", ""]
    if vendor is not None:
        lines += [
            "[source.crates-io]",
            f"replace-with = {json.dumps(source)}",
            "",
            f"[source.{json.dumps(source)}]",
            f"directory = {json.dumps(str(vendor))}",
            "",
        ]
    return "\n".join(lines + ["[net]", "offline = true", ""])


def reviewer_cargo_shim(cargo: str, config: Path) -> str:
    """A ``cargo`` that runs *cargo* with *config* passed as ``--config`` (issue #262).

    Measured on cargo 1.98.1: a commit's own ``.cargo/config.toml`` that replaces crates.io
    outranks both the ``CARGO_HOME`` configuration and ``CARGO_SOURCE_*`` variables, and only
    ``--config`` outranks it. A rustup ``+toolchain`` argument has to stay first.
    """
    real, given = shlex.quote(cargo), shlex.quote(str(config))
    return (
        "#!/bin/sh\n"
        "# Written by agent-launcher for an offline review (issue #262): this cargo home's\n"
        "# configuration outranks the commit's own.\n"
        'case "${1-}" in\n'
        f'  +*) toolchain=$1; shift; exec {real} "$toolchain" --config {given} "$@" ;;\n'
        "esac\n"
        f'exec {real} --config {given} "$@"\n'
    )


def reviewer_cargo_home(
    root: Path, vendor: Path | None, env: Mapping[str, str] | None = None
) -> Path:
    """Write the reviewer's cargo home beside the copy, never in it, with a read-only config.

    It is made even without vendored sources, so the reviewer's cargo never looks for the
    operator's ``~/.cargo``. When *env*'s ``PATH`` finds a cargo, ``bin/cargo`` is a
    :func:`reviewer_cargo_shim` around it.
    """
    home = root / "cargo-home"
    home.mkdir(parents=True, exist_ok=True)
    config = home / "config.toml"
    source = f"{REVIEWER_VENDORED_SOURCE}-{os.urandom(8).hex()}"
    config.write_text(reviewer_cargo_config(vendor, source), "utf-8")
    config.chmod(0o444)
    found = shutil.which("cargo", path=env.get("PATH", "")) if env is not None else None
    if found:
        shim = home / "bin" / "cargo"
        shim.parent.mkdir(exist_ok=True)
        shim.write_text(reviewer_cargo_shim(str(Path(found).absolute()), config), "utf-8")
        shim.chmod(0o555)
    return home


def reviewer_offline_cargo(session_env: dict[str, str], cargo_home: Path) -> None:
    """Point the session's cargo at *cargo_home*, offline, with its shim first on ``PATH``.

    Both cargo values replace the operator's, whatever they were.
    """
    session_env["CARGO_HOME"] = str(cargo_home)
    session_env["CARGO_NET_OFFLINE"] = "true"
    # A rustup proxy picks its toolchain from here; the shell prefix passes both names.
    session_env["RUSTUP_HOME"] = str(reviewer_rustup_home(session_env))
    shim = cargo_home / "bin" / "cargo"
    if shim.is_file():
        session_env["PATH"] = os.pathsep.join(
            [str(shim.parent)] + ([session_env["PATH"]] if session_env.get("PATH") else [])
        )


def reviewer_claude_settings(
    copy: Path,
    packet: Path,
    env: Mapping[str, str],
    *,
    toolchain: Sequence[Mapping[str, str]] | None = None,
    extra_deny_read: Sequence[str] = (),
    platform: str | None = None,
    read_only: Sequence[str] = (),
) -> dict[str, Any]:
    """The per-launch settings that turn on Claude's command sandbox and confine the session.

    Measured on Claude Code 2.1.292 on 2026-10-06: under ``dontAsk`` Bash is denied unless allowed,
    even with ``autoAllowBashIfSandboxed``; the sandbox's own temp directory stays writable until a
    ``denyWrite`` names its root; any variable reaches sandboxed commands until
    ``credentials.envVars`` denies it by name. Issue #189 measured that ``denyRead: ["~"]`` blocks
    the whole home directory and ``allowRead`` re-opens a path inside it, so commands read only the
    copy, the packet and the toolchain *toolchain* names (derived from *env* when not given). The
    settings set no ``apiKeyHelper``, plugins or hooks, so the user's own configuration is what
    loads.

    Issue #225: commands run through the reviewer's shell prefix, whose directory is readable and
    whose sentinel is denied by name, so the prefix filters even when the launch root is outside
    the home directory. The prefix is named in ``env`` as well, which outranks the user's settings.

    The one write allowed beyond the copy is the reviewer's own temp folder
    (:func:`reviewer_claude_temp_dir`), read back as well and under no denied temp root. Claude's
    file Write and Edit tools may write there too, through their own permission rule, because the
    launch message names it as the reviewer's draft folder: its answer draft and saved run outputs
    belong outside the copy, where the scratch-change comparison never sees them.

    Issue #262: *read_only* (the cargo home and the vendored dependencies) is allowed back for
    reading and named in ``denyWrite``, so read-only is stated rather than implied.
    """
    if toolchain is None:
        toolchain = reviewer_toolchain_paths(env)[0]
    prefix, sentinel = reviewer_claude_shell_paths(copy)
    temp = reviewer_claude_temp_dir(copy)
    allow_read = [str(copy.resolve()), str(packet.resolve()), str(prefix.parent)]
    allow_read += [item["path"] for item in toolchain if item["path"] not in allow_read]
    allow_read += [path for path in read_only if path not in allow_read]
    allow_read.append(str(temp))
    return {
        "env": {REVIEWER_SHELL_PREFIX: str(prefix)},
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {
                "denyWrite": list(reviewer_temp_roots(platform)) + list(read_only),
                "denyRead": ["~"] + list(extra_deny_read) + [str(sentinel)],
                "allowRead": allow_read,
                "allowWrite": [str(temp)],
            },
            "network": {"strictAllowlist": True, "allowedDomains": []},
            "credentials": {
                "envVars": [
                    {"name": name, "mode": "deny"} for name in reviewer_denied_variables(env)
                ]
            },
        },
        "permissions": {
            # ``//`` starts an absolute path in a permission rule; ``/`` is relative to the settings
            # file. ``packet.resolve()`` begins with ``/``, so this reads ``Read(//<packet>/**)``.
            # The temp folder is written the same way, so file Write and Edit may use it.
            "allow": [
                "Bash", "Edit(./**)", f"Edit(/{temp}/**)", f"Read(/{packet.resolve()}/**)",
            ],
            "deny": ["WebFetch", "WebSearch", "mcp__*"]
            + [f"Read({path})" for path in list(REVIEWER_CREDENTIAL_PATHS) + list(extra_deny_read)]
            # Claude's file tools run outside the OS sandbox: they may never write the read-only
            # dependencies, by their real path or through the copy's node_modules link.
            + [f"Edit(/{Path(path)}/**)" for path in read_only]
            + [f"Edit(./{REVIEWER_NODE_LINK})", f"Edit(./{REVIEWER_NODE_LINK}/**)"],
        },
    }


def reviewer_parse_claude_result(stdout: str) -> dict[str, Any]:
    """Usage, resolved models and the final message from ``claude -p --output-format json``."""
    try:
        data = json.loads(stdout)
    except (TypeError, ValueError):
        return {"usage": None, "resolved": [], "final": None, "is_error": True,
                "error": "the session printed no JSON result"}
    if not isinstance(data, dict):
        return {"usage": None, "resolved": [], "final": None, "is_error": True,
                "error": "the session's result is not a JSON object"}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    duration = data.get("duration_ms")
    model_usage = data.get("modelUsage")
    return {
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cost_usd": data.get("total_cost_usd"),
            "seconds": duration / 1000 if isinstance(duration, (int, float)) else None,
            "turns": data.get("num_turns"),
            "session_id": data.get("session_id"),
        },
        "resolved": sorted(model_usage) if isinstance(model_usage, dict) else [],
        "final": data.get("result") if isinstance(data.get("result"), str) else None,
        # Issue #248: with ``--json-schema`` the validated answer is this object. Measured on
        # Claude Code 2.1.301: a model that never satisfied the schema leaves the key out and
        # still reports ``subtype: success``, so only the key's absence says there is none.
        "structured": (
            data["structured_output"] if isinstance(data.get("structured_output"), dict) else None
        ),
        "is_error": bool(data.get("is_error")),
        "error": None if not data.get("is_error") else str(data.get("subtype") or "error"),
    }


def _reviewer_read(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def _reviewer_inside(path: Path, copy: Path) -> bool:
    try:
        return path.resolve().is_relative_to(copy.resolve())
    except (OSError, RuntimeError):
        return False


def _reviewer_risky_imports(content: bytes) -> list[str]:
    """``@`` tokens that are not plain relative paths: each could name a file outside the copy."""
    tokens = _REVIEWER_ANY_IMPORT.findall(content.decode("utf-8", "replace"))
    return [token for token in tokens if _REVIEWER_RISKY_IMPORT.search(token)]


def _reviewer_import_targets(content: bytes, parent: Path) -> list[tuple[str, Path]]:
    """Every ``@`` token in *content* that could be an import, with the path it would name."""
    found: list[tuple[str, Path]] = []
    for raw in _REVIEWER_ANY_IMPORT.findall(content.decode("utf-8", "replace")):
        token = raw.rstrip(_REVIEWER_IMPORT_TRAILING)
        if not token:
            continue
        target = Path(token).expanduser() if token.startswith("~") else parent / token
        found.append((token, target))
    return found


def _reviewer_imports_leave(start: Path, copy: Path) -> bool:
    """Whether *start*'s possible imports, followed as Claude follows them, can leave *copy*."""
    frontier, seen = [start], set()
    for _ in range(REVIEWER_IMPORT_DEPTH + 1):
        following: list[Path] = []
        for path in frontier:
            if path in seen:
                continue
            seen.add(path)
            if path.is_symlink() and not _reviewer_inside(path, copy):
                return True
            content = _reviewer_read(path) if _reviewer_inside(path, copy) else None
            if content is None:
                continue
            if _reviewer_risky_imports(content):
                return True
            for _token, target in _reviewer_import_targets(content, path.parent):
                if not _reviewer_inside(target, copy):
                    return True
                following.append(target)
        frontier = following
    return False


def reviewer_withhold_untrusted(
    copy: Path,
    dirs: Sequence[str] = REVIEWER_UNTRUSTED_DIRS,
    files: Sequence[str] = REVIEWER_UNTRUSTED_FILES,
    instructions: Sequence[str] = REVIEWER_INSTRUCTION_NAMES,
) -> list[str]:
    """Remove what the reviewed change could use to run or read outside the sandbox.

    *dirs*, *files* and *instructions* are the vendor's untrusted names; Claude's are the defaults.

    Every ``.claude/`` directory and ``.mcp.json`` at any depth (Claude acts on them outside the
    command sandbox), every symlink that leaves the copy, and every instruction file whose possible
    ``@`` imports can leave the copy (Claude would load the imported file, a credential for example,
    into the reviewer's context). Returns each withheld path with the reason; the reviewer still
    sees them in the packet's diff.
    """
    withheld: list[str] = []
    dir_names = frozenset(_reviewer_fold(n) for n in dirs)
    file_names = frozenset(_reviewer_fold(n) for n in files)
    instruction_names = frozenset(_reviewer_fold(n) for n in instructions)

    def drop(path: Path, why: str) -> None:
        withheld.append(f"{path.relative_to(copy).as_posix()} ({why})")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    for path in sorted(copy.rglob("*")):
        if not (path.exists() or path.is_symlink()):
            continue  # inside a directory already withheld
        name = _reviewer_fold(path.name)
        if name in dir_names and (path.is_dir() or path.is_symlink()):
            drop(path, "Claude would act on it outside the sandbox")
        elif name in file_names:
            drop(path, "Claude would act on it outside the sandbox")
        elif path.is_symlink() and not _reviewer_inside(path, copy):
            drop(path, "a symlink out of the copy")
    for path in sorted(copy.rglob("*")):
        if _reviewer_fold(path.name) in instruction_names and path.is_file() and (
            _reviewer_imports_leave(path, copy)
        ):
            drop(path, "it can import a file outside the copy")
    return withheld


def reviewer_claude_widening(env: Mapping[str, str]) -> list[str]:
    """Settings outside the copy that would widen the reviewer's sandbox.

    ``--settings`` overrides scalar keys, but list keys merge across levels, and managed settings
    outrank it. So a user, local or managed setting that excludes commands from the sandbox, allows
    a domain, a write or a read, adds a working directory, or turns the sandbox off would carry into
    the session; the launch refuses rather than run a review it cannot confine.
    """
    home = Path(env.get("HOME") or Path.home())
    base = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    files = [
        base / "settings.json",
        base / "settings.local.json",
        Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
        Path("/etc/claude-code/managed-settings.json"),
    ]
    problems: list[str] = []
    for path in files:
        if not path.exists():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Claude may read a file this strict parser cannot (comments, trailing commas); a
            # setting unchecked could widen the sandbox, so an unreadable file refuses the launch.
            problems.append(f"{path} cannot be read as JSON to check it")
            continue
        if not isinstance(loaded, dict):
            problems.append(f"{path} is not a JSON object")
            continue
        sandbox = loaded.get("sandbox") if isinstance(loaded.get("sandbox"), dict) else {}
        network = sandbox.get("network") if isinstance(sandbox.get("network"), dict) else {}
        filesystem = (
            sandbox.get("filesystem") if isinstance(sandbox.get("filesystem"), dict) else {}
        )
        permissions = (
            loaded.get("permissions") if isinstance(loaded.get("permissions"), dict) else {}
        )
        widening = {
            "sandbox.excludedCommands": sandbox.get("excludedCommands"),
            "sandbox.network.allowedDomains": network.get("allowedDomains"),
            "sandbox.filesystem.allowWrite": filesystem.get("allowWrite"),
            "sandbox.filesystem.allowRead": filesystem.get("allowRead"),
            "permissions.additionalDirectories": permissions.get("additionalDirectories"),
        }
        for key, value in widening.items():
            if value:
                problems.append(f"{path.name} sets {key}")
        if sandbox.get("enabled") is False and "managed" in path.name:
            problems.append(f"{path.name} turns the sandbox off")
        if filesystem.get("disabled") is True:
            problems.append(f"{path.name} sets sandbox.filesystem.disabled")
        # Issue #225: managed settings outrank ``--settings``, so a shell prefix set there would
        # replace the one that keeps start-up exports out of sandboxed commands.
        environment = loaded.get("env") if isinstance(loaded.get("env"), dict) else {}
        if REVIEWER_SHELL_PREFIX in environment:
            problems.append(f"{path.name} sets env.{REVIEWER_SHELL_PREFIX}")
    return problems


def reviewer_claude_config_sources(
    copy: Path, env: Mapping[str, str]
) -> list[tuple[str, bytes | None]]:
    """What Claude's normal configuration loads, as ``(label, content)`` pairs.

    The user's and the project's instruction files, each file they import with ``@path`` one level
    deep, and the enabled plugins with their installed versions. A missing file is recorded as
    absent, so creating one changes the fingerprint. Labels never carry an absolute path.
    """
    home = Path(env.get("HOME") or Path.home())
    base = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    files = [
        ("user:CLAUDE.md", base / "CLAUDE.md"),
        ("project:CLAUDE.md", copy / "CLAUDE.md"),
    ] + [
        (f"project:{path.relative_to(copy).as_posix()}", path)
        for path in sorted(copy.rglob("*"))
        if _reviewer_fold(path.name) in _REVIEWER_INSTRUCTION_NAMES and path != copy / "CLAUDE.md"
    ]
    sources: list[tuple[str, bytes | None]] = []
    for label, path in files:
        content = _reviewer_read(path)
        sources.append((label, content))
        if content is None:
            continue
        for token, target in sorted(set(_reviewer_import_targets(content, path.parent))):
            if label.startswith("project:") and not _reviewer_inside(target, copy):
                # Never read a file the reviewed change points at outside the copy.
                sources.append((f"import:{label}:{token}", b"outside the copy"))
                continue
            sources.append((f"import:{label}:{token}", _reviewer_read(target)))

    enabled: set[str] = set()
    for settings in (base / "settings.json", copy / ".claude" / "settings.json"):
        try:
            loaded = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        plugins = loaded.get("enabledPlugins") if isinstance(loaded, dict) else None
        if isinstance(plugins, dict):
            enabled |= {str(name) for name, on in plugins.items() if on is True}
    try:
        installed = json.loads((base / "plugins" / "installed_plugins.json").read_text("utf-8"))
    except (OSError, ValueError):
        installed = {}
    entries = installed.get("plugins", {}) if isinstance(installed, dict) else {}
    for name in sorted(enabled):
        rows = entries.get(name) if isinstance(entries, dict) else None
        versions = sorted(
            f"{row.get('version')}@{row.get('gitCommitSha') or ''}"
            for row in (rows or [])
            if isinstance(row, dict)
        )
        sources.append((f"plugin:{name}", ",".join(versions).encode("utf-8")))
    return sources


def reviewer_configuration_fingerprint(
    sources: Sequence[tuple[str, bytes | None]],
) -> dict[str, Any]:
    """SHA-256 over the sorted ``(label, content digest)`` pairs, and the labels that went in.

    ``source_digests`` names the digest that went into each label, so two runs whose
    fingerprint differs can be told apart by the source that changed. It reuses the
    sorted pairs the fingerprint itself is computed from, so it carries the same order
    and the same tie-breaking as ``sources``. A source that was absent contributes the
    literal ``absent``. Only digests are kept, never the content they came from.
    """
    pairs = sorted(
        (label, hashlib.sha256(content).hexdigest() if content is not None else "absent")
        for label, content in sources
    )
    digest = hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode("utf-8"))
    return {
        "fingerprint": digest.hexdigest(),
        "sources": [label for label, _ in pairs],
        "source_digests": [{"label": label, "sha256": sha256} for label, sha256 in pairs],
    }


#: The first bytes of a native executable (Mach-O, thin or fat, either byte order; ELF). A
#: reviewer whose executable is bound to a probe record must be one of these, never a script that
#: picks another binary at run time.
_REVIEWER_NATIVE_MAGIC = (
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\x7fELF",
)


def reviewer_is_native(path: Path) -> bool:
    """Whether *path* is a regular file that starts like a native executable."""
    try:
        with path.open("rb") as handle:
            return path.is_file() and handle.read(4) in _REVIEWER_NATIVE_MAGIC
    except OSError:
        return False


def _reviewer_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def reviewer_executable_file(path: Path) -> dict[str, str]:
    """The file's name and SHA-256, read as bytes; nothing runs it.

    The name is the file name only, never a path, because records are committed to a public
    repository.
    """
    return {"name": path.name, "sha256": _reviewer_sha256(path)}


def reviewer_executable_identity(path: Path, env: Mapping[str, str]) -> dict[str, str]:
    """The identity a probe record binds: the file's name, its SHA-256 and what it reports.

    It runs *path* with ``--version``, outside any sandbox, so a bound recipe calls it only on the
    pinned copy whose bytes were already compared (issue #223's review, finding 2).
    """
    version = _reviewer_vendor_version(str(path), env) or ""
    return {**reviewer_executable_file(path), "version": version}


def reviewer_grok_executable(env: Mapping[str, str]) -> Path:
    """Grok's own native executable, never a wrapper script in front of it.

    Grok installs itself under its home directory (``bin/grok``, a link into ``downloads/``); a
    ``grok`` on ``PATH`` may be a local wrapper that adds flags such as ``--trust``.
    """
    grok_home = Path(env["GROK_HOME"]) if env.get("GROK_HOME") else _reviewer_home(env) / ".grok"
    candidates = [grok_home / "bin" / "grok"]
    found = shutil.which("grok", path=env.get("PATH", ""))
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if reviewer_is_native(resolved):
            return resolved
    raise ReviewerRefused("no native grok executable was found to bind to a probe record")


def reviewer_muse_executable(env: Mapping[str, str]) -> Path:
    """Muse's versioned native binary, never the ``muse`` launcher script that updates it.

    The launcher script keeps the active version in ``.muse-version`` beside itself and runs
    ``muse-bin-<version>``; running that binary directly means no update happens mid-review.
    """
    found = shutil.which("muse", path=env.get("PATH", ""))
    if not found:
        raise ReviewerRefused("muse is not on PATH")
    resolved = Path(found).resolve()
    if reviewer_is_native(resolved):
        return resolved
    marker = resolved.parent / ".muse-version"
    try:
        version = marker.read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-R[0-9]+(\.[0-9]+)?", version):
        binary = resolved.parent / f"muse-bin-{version}"
        if reviewer_is_native(binary):
            return binary
    raise ReviewerRefused("no native muse binary was found beside the muse launcher script")


def _reviewer_user_files(
    env: Mapping[str, str], files: Sequence[tuple[str, str]]
) -> list[tuple[str, bytes | None]]:
    home = _reviewer_home(env)
    return [(label, _reviewer_read(_reviewer_expand(path, home))) for label, path in files]


def reviewer_grok_profile_name(settings_path: Path) -> str:
    """A per-launch sandbox profile name, so no user profile of the same name can shadow it."""
    return "reviewer-" + hashlib.sha256(str(settings_path).encode("utf-8")).hexdigest()[:16]


def reviewer_grok_argv(
    model: str,
    effort: str | None,
    settings_path: Path,
    *,
    max_budget_usd: str | None = None,
    executable: Path | None = None,
    prompt_path: Path | None = None,
    answer_schema: str | None = None,
) -> list[str]:
    """Grok's reviewer argv, from grok 1.0.50's ``--help`` and headless guide.

    Headless mode does not read standard input, so the message goes by ``--prompt-file``. Plan
    mode is off, Bash is allowed by rule under ``dontAsk`` (never ``--always-approve``), and the
    sandbox is the per-launch profile written into the copy's ``.grok/sandbox.toml``.
    """
    if max_budget_usd is not None:
        raise ReviewerRefused("grok has no dollar ceiling; --max-budget-usd cannot be honoured")
    if executable is None or prompt_path is None:
        raise ReviewerRefused("a grok reviewer launch needs its verified executable and prompt")
    argv = [str(executable), "--prompt-file", str(prompt_path), "-m", model]
    if effort:
        argv += ["--reasoning-effort", effort]
    return argv + [
        "--sandbox", reviewer_grok_profile_name(settings_path),
        "--no-plan",
        "--permission-mode", "dontAsk",
        "--allow", "Bash",
        "--disable-web-search",
        "--output-format", "json",
    ]


def reviewer_grok_settings(
    copy: Path,
    packet: Path,
    env: Mapping[str, str],
    *,
    toolchain: Sequence[Mapping[str, str]] | None = None,
    extra_deny_read: Sequence[str] = (),
    platform: str | None = None,
    read_only: Sequence[str] = (),
) -> dict[str, Any]:
    """Grok's per-launch sandbox profile and the environment overlay for its commands.

    The profile extends ``strict`` (reads the working directory, system paths and the Grok home;
    writes the working directory, ``~/.grok/sessions`` and temp), blocks child network, grants
    the packet, the prompt and the toolchain read-only, and denies the temp roots, Grok's sign-in
    file and anything *extra_deny_read* names. The overlay keeps only the allow-listed variables
    in Grok's tool commands.
    """
    if toolchain is None:
        toolchain = reviewer_toolchain_paths(env)[0]
    home = _reviewer_home(env)
    granted = [str(packet.resolve()), str((copy.parent / "prompt").resolve())]
    granted += [item["path"] for item in toolchain if item["path"] not in granted]
    granted += [path for path in read_only if path not in granted]
    deny = list(reviewer_temp_roots(platform)) + [
        str(_reviewer_expand(path, home)) for path in REVIEWER_GROK_CREDENTIAL_FILES
    ] + list(extra_deny_read)
    return {
        "profile": {
            "extends": "strict",
            "restrict_network": True,
            "read_only": granted,
            "deny": deny,
        },
        "overlay": {
            "shell_environment_policy": {
                "inherit": "all",
                "ignore_default_excludes": False,
                "include_only": list(REVIEWER_ENVIRONMENT_ALLOWED),
            }
        },
    }


def _reviewer_toml_string(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


def reviewer_grok_materialize(
    settings: Mapping[str, Any], root: Path, copy: Path, **_options: Any
) -> tuple[Path, dict[str, str]]:
    """Write the profile into the copy's ``.grok/sandbox.toml``; return it and the overlay.

    Grok reads custom profiles only from a user or project ``sandbox.toml``, and the reviewed
    change's own ``.grok/`` has already been withheld, so this file is the launcher's.
    """
    path = copy / ".grok" / "sandbox.toml"
    profile = settings["profile"]
    lines = [f"[profiles.{reviewer_grok_profile_name(path)}]"]
    lines.append(f"extends = {_reviewer_toml_string(profile['extends'])}")
    lines.append(f"restrict_network = {'true' if profile['restrict_network'] else 'false'}")
    for key in ("read_only", "deny"):
        items = ", ".join(_reviewer_toml_string(item) for item in profile[key])
        lines.append(f"{key} = [{items}]")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path, {"GROK_CONFIG": json.dumps(settings["overlay"], separators=(",", ":"))}


def reviewer_grok_widening(env: Mapping[str, str]) -> list[str]:
    """Grok configuration that would sign the review in with an API key, or widen it.

    Grok's authentication guide ranks a per-model ``api_key`` or ``env_key`` in ``config.toml``
    above the signed-in session; with one set, removing ``XAI_API_KEY`` does not make the review
    use the subscription.
    """
    import tomllib

    grok_home = Path(env["GROK_HOME"]) if env.get("GROK_HOME") else _reviewer_home(env) / ".grok"
    path = grok_home / "config.toml"
    if not path.exists():
        return []
    try:
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{path.name} cannot be read as TOML to check it"]
    models = loaded.get("model") if isinstance(loaded.get("model"), dict) else {}
    return [
        f"config.toml sets {key} for model {name}"
        for name, table in sorted(models.items())
        if isinstance(table, dict)
        for key in ("api_key", "env_key")
        if table.get(key)
    ]


def reviewer_parse_grok_result(stdout: str) -> dict[str, Any]:
    """Usage, resolved models and the final message from ``grok --output-format json``."""
    try:
        data = json.loads(stdout)
    except (TypeError, ValueError):
        return {"usage": None, "resolved": [], "final": None, "is_error": True,
                "error": "the session printed no JSON result"}
    if not isinstance(data, dict):
        return {"usage": None, "resolved": [], "final": None, "is_error": True,
                "error": "the session's result is not a JSON object"}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    model_usage = data.get("modelUsage")
    stop = data.get("stopReason")
    final = data.get("text") if isinstance(data.get("text"), str) else None
    is_error = stop != "end_turn"
    return {
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cost_usd": data.get("total_cost_usd"),
            "seconds": None,
            "turns": data.get("num_turns"),
            "session_id": data.get("sessionId"),
        },
        "resolved": sorted(model_usage) if isinstance(model_usage, dict) else [],
        "final": final,
        "is_error": is_error,
        "error": f"the session stopped with {stop!r}" if is_error else None,
    }


def reviewer_grok_config_sources(
    copy: Path, env: Mapping[str, str]
) -> list[tuple[str, bytes | None]]:
    """Grok's user configuration: its settings and its own sandbox profiles."""
    return _reviewer_user_files(
        env, [("user:config.toml", "~/.grok/config.toml"), ("user:sandbox.toml",
                                                             "~/.grok/sandbox.toml")]
    )


def reviewer_muse_argv(
    model: str,
    effort: str | None,
    settings_path: Path,
    *,
    max_budget_usd: str | None = None,
    executable: Path | None = None,
    prompt_path: Path | None = None,
    answer_schema: str | None = None,
) -> list[str]:
    """Muse's reviewer argv, from muse 1.4.6's ``exec --help``.

    The sandbox and approvals stay on (their defaults); the network sandbox is ``restricted``,
    web tools are off and no session log is written. ``--permission-profile`` cannot be combined
    with ``--sandbox-network`` (measured), so the network setting is the one passed.
    """
    if max_budget_usd is not None:
        raise ReviewerRefused("muse has no dollar ceiling; --max-budget-usd cannot be honoured")
    if executable is None or prompt_path is None:
        raise ReviewerRefused("a muse reviewer launch needs its verified executable and prompt")
    argv = [str(executable), "exec", "--model", model]
    if effort:
        argv += ["--reasoning-effort", effort]
    return argv + [
        "--json",
        "--prompt-file", str(prompt_path),
        "--sandbox-network", "restricted",
        "--disable-web-tools",
        "--no-session-log",
    ]


def reviewer_muse_settings(
    copy: Path,
    packet: Path,
    env: Mapping[str, str],
    *,
    toolchain: Sequence[Mapping[str, str]] | None = None,
    extra_deny_read: Sequence[str] = (),
    platform: str | None = None,
    read_only: Sequence[str] = (),
) -> dict[str, Any]:
    """What the Muse launch asks of its sandbox, for the record: Muse takes it as flags."""
    return {"sandbox": "default (on)", "sandbox_network": "restricted", "web_tools": "disabled"}


def reviewer_parse_muse_result(stdout: str) -> dict[str, Any]:
    """The final message and model from ``muse exec --json``; Muse reports no usage there."""
    final: str | None = None
    terminal: str | None = None
    reason: Any = None
    resolved: set[str] = set()
    for line in (stdout or "").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        kind = record.get("payload_type")
        try:
            payload = record.get("payload")
            payload = json.loads(payload) if isinstance(payload, str) else payload
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        if kind == "run.model.configured" and isinstance(payload.get("model_id"), str):
            resolved.add(payload["model_id"])
        elif kind is not None and str(kind).startswith("run.terminal."):
            terminal = payload.get("terminal") if isinstance(payload.get("terminal"), str) else None
            final = payload.get("text") if isinstance(payload.get("text"), str) else None
            reason = payload.get("reason")
    if terminal is None:
        return {"usage": None, "resolved": sorted(resolved), "final": None, "is_error": True,
                "error": "the session printed no terminal event"}
    is_error = terminal != "completed"
    return {
        "usage": None,
        "resolved": sorted(resolved),
        "final": final,
        "is_error": is_error,
        "error": f"the run ended {terminal}: {reason}" if is_error else None,
    }


def reviewer_muse_config_sources(
    copy: Path, env: Mapping[str, str]
) -> list[tuple[str, bytes | None]]:
    """Muse's user configuration: its settings and its approval policy."""
    return _reviewer_user_files(
        env, [("user:settings.json", "~/.config/muse/settings.json"),
              ("user:approval-policy.json", "~/.config/muse/approval-policy.json")]
    )


def reviewer_settings_materialize(
    settings: Mapping[str, Any], root: Path, copy: Path, **_options: Any
) -> tuple[Path, dict[str, str]]:
    """Write the settings beside the copy, never inside it; no extra environment."""
    path = root / "settings.json"
    path.write_text(json.dumps(settings, indent=2) + "\n", "utf-8")
    return path, {}


#: Grok's own sign-in and configuration files (its authentication guide: ``auth.json`` holds the
#: session token and ``config.toml`` may hold a per-model ``api_key``).
REVIEWER_GROK_CREDENTIAL_FILES = ("~/.grok/auth.json", "~/.grok/config.toml")


@dataclass(frozen=True)
class ReviewerRecipe:
    """How one vendor runs the targeted reviewer: argv, sandbox settings, result, configuration.

    Issue #223 moved what differs between vendors into fields, so the launch never branches on a
    vendor's name. Every default but ``materialize`` is Claude's (issue #225 gave Claude its own).
    """

    binary: str
    argv: Any
    settings: Any
    parse: Any
    config_sources: Any
    #: Variables that would sign the session in with an API key; removed from its environment.
    api_key_variables: tuple[str, ...] = REVIEWER_API_KEY_VARIABLES
    api_key_prefixes: tuple[str, ...] = REVIEWER_API_KEY_PREFIXES
    #: Project names the vendor would act on outside its sandbox; withheld from the copy.
    untrusted_dirs: tuple[str, ...] = REVIEWER_UNTRUSTED_DIRS
    untrusted_files: tuple[str, ...] = REVIEWER_UNTRUSTED_FILES
    instruction_names: tuple[str, ...] = REVIEWER_INSTRUCTION_NAMES
    #: ``stdin``, or ``file`` when the vendor reads its prompt from a file it is given.
    prompt_via: str = "stdin"
    #: The vendor's own sign-in files, which a sandboxed command must not read.
    credential_files: tuple[str, ...] = ()
    #: The vendor's own state directory, where the probe plants a read canary.
    vendor_home: str | None = None
    #: A directory under it that the probe tries to write.
    vendor_writable: str | None = None
    #: The model ``reviewer-probe`` uses when none is given.
    probe_model: str = "haiku"
    #: The platforms a live probe passed on; ``None`` for any (Claude's recipe predates records).
    platforms: tuple[str, ...] | None = None
    #: Whether the vendor takes a dollar ceiling; one is then required on every launch.
    takes_ceiling: bool = False
    #: Configuration outside the copy that would widen the sandbox or change the sign-in.
    widening: Any = None
    #: Writes the settings and returns the path the argv names, plus environment to add.
    materialize: Any = reviewer_settings_materialize
    #: Resolves the native executable a probe record binds; ``None`` runs ``binary`` from PATH.
    executable: Any = None
    #: Maps the copy to the temp folder the sandbox leaves writable; ``None`` leaves none, and the
    #: probe then proves a write to ``TMPDIR`` is denied.
    temp_dir: Any = None


REVIEWER_CLAUDE_RECIPE = ReviewerRecipe(
    binary="claude",
    argv=reviewer_claude_argv,
    settings=reviewer_claude_settings,
    parse=reviewer_parse_claude_result,
    config_sources=reviewer_claude_config_sources,
    credential_files=("~/.claude/.credentials.json",),
    vendor_home="~/.claude",
    vendor_writable="~/.claude",
    takes_ceiling=True,
    widening=reviewer_claude_widening,
    # Issue #225: commands run through the shell prefix that keeps start-up exports out.
    materialize=reviewer_claude_materialize,
    # The replay gives each test a writable TMPDIR; the reviewer gets one beside its copy.
    temp_dir=reviewer_claude_temp_dir,
)

#: Recipes ``reviewer-probe`` may run but ``review`` never does (issue #223, plan KTD1). A
#: candidate reviews only once a committed probe record for its executable and platform admits it.
REVIEWER_CANDIDATES: dict[str, ReviewerRecipe] = {
    "grok": ReviewerRecipe(
        binary="grok",
        argv=reviewer_grok_argv,
        settings=reviewer_grok_settings,
        parse=reviewer_parse_grok_result,
        config_sources=reviewer_grok_config_sources,
        api_key_variables=("XAI_API_KEY", "GROK_DEPLOYMENT_KEY"),
        api_key_prefixes=(),
        # In an untrusted directory grok 1.0.50 loads no project instructions, MCP servers or
        # hooks (measured with ``grok inspect``); withholding them as well costs nothing.
        untrusted_dirs=(".grok", ".claude", ".cursor"),
        untrusted_files=(".mcp.json",),
        instruction_names=("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md"),
        prompt_via="file",
        credential_files=REVIEWER_GROK_CREDENTIAL_FILES,
        vendor_home="~/.grok",
        vendor_writable="~/.grok/sessions",
        probe_model="grok-4.7",
        widening=reviewer_grok_widening,
        materialize=reviewer_grok_materialize,
        executable=reviewer_grok_executable,
    ),
    "muse": ReviewerRecipe(
        binary="muse",
        argv=reviewer_muse_argv,
        settings=reviewer_muse_settings,
        parse=reviewer_parse_muse_result,
        config_sources=reviewer_muse_config_sources,
        # ``muse login --help``: "META_API_KEY always takes priority over the account login."
        api_key_variables=("META_API_KEY",),
        api_key_prefixes=(),
        untrusted_dirs=(".muse", ".claude", ".agents"),
        untrusted_files=(".mcp.json",),
        instruction_names=("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md"),
        prompt_via="file",
        credential_files=("~/.config/muse/auth.json",),
        vendor_home="~/.config/muse",
        vendor_writable="~/.config/muse",
        probe_model="muse-wonder-full-1.0",
        executable=reviewer_muse_executable,
    ),
}

#: Committed probe records that admit a candidate, by ``(vendor, platform)``. Each is the record
#: ``reviewer-probe --record`` wrote, every check held, bound to the executable it ran. A test
#: keeps this table equal to the records under ``tests/fixtures/reviewer-probe/``.
REVIEWER_ADMISSIONS: dict[tuple[str, str], Mapping[str, Any]] = {}


def _reviewer_admitted() -> dict[str, ReviewerRecipe]:
    admitted: dict[str, ReviewerRecipe] = {}
    for vendor, platform in sorted(REVIEWER_ADMISSIONS):
        base = admitted.get(vendor) or REVIEWER_CANDIDATES[vendor]
        platforms = tuple(sorted({*(base.platforms or ()), platform}))
        admitted[vendor] = dataclasses.replace(base, platforms=platforms)
    return admitted


#: The vendors with a reviewer recipe. A vendor joins only when ``reviewer-probe`` passes on it;
#: every other vendor is refused by name (plan KTD2: codex-cli 0.160.1's workspace-write sandbox
#: read a file outside its workspace on 2026-10-06). Issue #223: Grok and Muse join only through
#: ``REVIEWER_ADMISSIONS``.
REVIEWER_RECIPES: dict[str, ReviewerRecipe] = {
    "claude": REVIEWER_CLAUDE_RECIPE,
    **_reviewer_admitted(),
}


def reviewer_recipe(vendor: str) -> ReviewerRecipe:
    recipe = REVIEWER_RECIPES.get(vendor)
    if recipe is None:
        raise ReviewerRefused(
            f"{vendor} has no reviewer sandbox recipe that denies writes outside the copy, network "
            "and credential reads; it cannot staff the targeted reviewer"
        )
    return recipe


def reviewer_probe_recipe(vendor: str) -> ReviewerRecipe:
    """The recipe ``reviewer-probe`` runs: a reviewer's, else a candidate's."""
    if vendor in REVIEWER_RECIPES:
        return REVIEWER_RECIPES[vendor]
    if vendor in REVIEWER_CANDIDATES:
        return REVIEWER_CANDIDATES[vendor]
    return reviewer_recipe(vendor)


def _reviewer_sits_under_temp(root: Path, temp: str) -> bool:
    """Whether *root* is the temp root *temp* or inside it, as written or resolved.

    Both sides are compared in the form the caller wrote and the form the filesystem
    resolves, so a symlink such as macOS ``/var/folders`` -> ``/private/var/folders``
    cannot hide the scratch copy on the other spelling. A prefix check would also
    treat ``/tmp-extra`` as inside ``/tmp``; ``is_relative_to`` does not.
    """
    bases = _reviewer_forms(Path(temp))
    return any(
        form == base or form.is_relative_to(base)
        for form in _reviewer_forms(root)
        for base in bases
    )


def reviewer_work_root(env: Mapping[str, str], platform: str | None = None) -> Path:
    """Where scratch copies live: outside every temp root the sandbox denies."""
    cache = env.get("XDG_CACHE_HOME") or str(Path(env.get("HOME") or Path.home()) / ".cache")
    root = Path(cache).expanduser() / "agent-launcher" / "reviews"
    for temp in reviewer_temp_roots(platform):
        if _reviewer_sits_under_temp(root, temp):
            raise ReviewerRefused(
                f"the scratch copy would sit under {temp}, which the reviewer's sandbox denies"
            )
    return root


def _reviewer_manifest(copy: Path) -> dict[str, str]:
    """Each file's SHA-256, and each symlink as ``link:<target>``, never followed."""
    manifest: dict[str, str] = {}
    for path in sorted(copy.rglob("*")):
        relative = path.relative_to(copy).as_posix()
        if path.is_symlink():
            manifest[relative] = f"link:{os.readlink(path)}"
        elif path.is_file():
            manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _reviewer_safe_path(copy: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if (
        not parts
        or Path(relative).is_absolute()
        or any(p in ("..", "") or _reviewer_fold(p) == ".git" for p in parts)
    ):
        raise ReviewerRefused(f"the head names an unsafe path {relative!r}")
    return copy.joinpath(*parts)


def _reviewer_writable_at(copy: Path, target: Path, relative: str) -> None:
    """Refuse a write whose directory leaves the copy or passes through a symlink."""
    ancestor = target.parent
    while ancestor != copy:
        if ancestor.is_symlink():
            raise ReviewerRefused(f"the head writes {relative!r} through a symlink")
        ancestor = ancestor.parent
    if not _reviewer_inside(target.parent, copy):
        raise ReviewerRefused(f"the head writes {relative!r} outside the copy")


def reviewer_export_head(repo: Path, head: str, copy: Path) -> dict[str, str]:
    """Write *head*'s tracked files into *copy* from git's object store, with no ``.git``.

    Read with ``ls-tree`` and ``cat-file`` rather than ``git archive``, so the change's own
    ``.gitattributes`` (``export-ignore``, ``export-subst``) cannot make the copy differ from the
    head. Every path is checked, regular files are written before symlinks, and submodules are
    left out. Returns the copy's manifest.
    """
    resolved = run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{head}^{{commit}}"],
        check=False, timeout=30,
    )
    if resolved.returncode != 0:
        raise ReviewerRefused(f"{head} is not a commit in {repo}")
    commit = resolved.stdout.strip()
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree", commit],
        capture_output=True, timeout=120, check=False,
    )
    if listing.returncode != 0:
        raise ReviewerRefused(f"git ls-tree failed: {listing.stderr.decode(errors='replace')}")
    entries: list[tuple[str, str, str]] = []
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        mode, kind, sha = meta.decode().split()
        if kind == "blob":
            entries.append((mode, sha, name.decode("utf-8", "surrogateescape")))
    batch = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input="".join(f"{sha}\n" for _, sha, _ in entries).encode(),
        capture_output=True, timeout=300, check=False,
    )
    if batch.returncode != 0:
        raise ReviewerRefused(f"git cat-file failed: {batch.stderr.decode(errors='replace')}")
    blobs: list[bytes] = []
    stream, offset = batch.stdout, 0
    for _ in entries:
        newline = stream.index(b"\n", offset)
        size = int(stream[offset:newline].split()[2])
        blobs.append(stream[newline + 1 : newline + 1 + size])
        offset = newline + 1 + size + 1
    folded: dict[str, str] = {}
    for _mode, _sha, relative in entries:
        for depth in range(1, len(Path(relative).parts) + 1):
            prefix = "/".join(Path(relative).parts[:depth])
            seen = folded.setdefault(_reviewer_fold(prefix), prefix)
            if seen != prefix:
                # On a case-insensitive file system the two would land on one path.
                raise ReviewerRefused(
                    f"the head names {seen!r} and {prefix!r}, which differ only by case"
                )
    copy.mkdir(parents=True)
    links: list[tuple[Path, bytes]] = []
    for (mode, _sha, relative), data in zip(entries, blobs, strict=True):
        target = _reviewer_safe_path(copy, relative)
        if mode == "120000":
            links.append((target, data))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _reviewer_writable_at(copy, target, relative)
        target.write_bytes(data)
        # Explicit modes, so the copy matches saga's 022 re-run whatever mask the launcher has.
        target.chmod(0o755 if mode == "100755" else 0o644)
    for target, data in links:
        target.parent.mkdir(parents=True, exist_ok=True)
        _reviewer_writable_at(copy, target, target.relative_to(copy).as_posix())
        os.symlink(data.decode("utf-8", "surrogateescape"), target)
    return _reviewer_manifest(copy)


def reviewer_pytest_link(copy: Path, path: str, value: str) -> bool:
    """Whether *path*, a new link whose manifest *value* is ``link:<target>``, is one pytest made.

    It must sit in a ``pytest-of-<user>/`` tree (``REVIEWER_PYTEST_LINK``) and point at a folder
    beside it named as pytest numbers them: ``pytest-current`` at ``pytest-<n>``, and
    ``<test>current`` at ``<test><n>``. pytest writes the target as an absolute path; a bare name
    is accepted too. A link pointing anywhere else is the session's, and is reported.
    """
    match = REVIEWER_PYTEST_LINK.search(path)
    if match is None or not value.startswith("link:"):
        return False
    stem = match.group("run") or match.group("test")
    target = value[len("link:"):]
    parent = PurePosixPath(path).parent
    if "/" in target:
        candidate = PurePosixPath(target)
        folders = {PurePosixPath(base.as_posix()) / parent for base in (copy, copy.resolve())}
        if not candidate.is_absolute() or candidate.parent not in folders:
            return False
        target = candidate.name
    return re.fullmatch(re.escape(stem) + r"[0-9]+", target) is not None


def reviewer_scratch_changes(copy: Path, manifest: Mapping[str, str]) -> dict[str, list[str]]:
    """The files added, modified and deleted in the copy since the export, minus tool clutter."""
    now = _reviewer_manifest(copy)

    def is_link(path: str) -> bool:
        return now.get(path, "").startswith("link:")

    # Clutter is ignored only where it is new: a tracked file at a clutter-looking path that the
    # session modified or deleted is a change like any other.
    def clutter(path: str) -> bool:
        return bool(
            REVIEWER_SCRATCH_IGNORED.search(path) or reviewer_in_package_cache(path, manifest)
        )

    return {
        "added": sorted(
            p for p in now if p not in manifest and not is_link(p) and not clutter(p)
        ),
        "modified": sorted(
            p for p in now if p in manifest and now[p] != manifest[p] and not is_link(p)
        ),
        "deleted": sorted(p for p in manifest if p not in now),
        # A symlink the session made or changed is never a reproduction test: reading it later,
        # outside the sandbox, could read whatever it points at.
        "links": sorted(
            p for p in now
            if now[p].startswith("link:") and manifest.get(p) != now[p]
            and not (p not in manifest and reviewer_in_package_cache(p, manifest))
            and not (p not in manifest and reviewer_pytest_link(copy, p, now[p]))
        ),
    }


def _reviewer_front_matter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    head = text[4:].split("\n---", 1)[0]
    pairs = (line.split(":", 1) for line in head.splitlines() if ":" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def _reviewer_body(text: str) -> str:
    if text.startswith("---\n") and "\n---" in text[4:]:
        return text[4:].split("\n---", 1)[1].lstrip("-").lstrip("\n")
    return text


def reviewer_wrapper_path() -> Path:
    """The roles library's wrapper, beside this script's package root."""
    source = Path(reviewer_wrapper_path.__code__.co_filename).resolve()
    return source.parents[3] / "roles" / "targeted-reviewer.md"


def reviewer_launch_message(
    wrapper: str, prompt: str, packet: Path, copy: Path, cap: int,
    withheld: Sequence[str] = (), draft_folder: Path | None = None,
) -> str:
    """What the session reads on standard input: the wrapper, saga's prompt, where things are.

    With *draft_folder*, the message names it as the place for the reviewer's answer draft and
    saved run outputs: outside the scratch copy, so the scratch-change comparison never sees it.
    Without one (a vendor that gets no such folder), the line is left out and the prompt tells the
    reviewer to keep drafts in the copy and delete them.
    """
    draft = (
        "- Your draft folder, outside the scratch copy and never compared: "
        f"`{draft_folder.resolve()}`\n"
        if draft_folder is not None else ""
    )
    note = (
        "\nWithheld from the scratch copy, because they would run or read outside the sandbox; "
        "the packet's change still shows them:\n"
        + "".join(f"- `{item}`\n" for item in withheld)
        if withheld else ""
    )
    return (
        f"{_reviewer_body(wrapper).rstrip()}\n\n"
        "---\n\n"
        f"{_reviewer_body(prompt).rstrip()}\n\n"
        "---\n\n"
        "# This review\n\n"
        f"- The review packet: `{packet.resolve()}`\n"
        f"- The scratch copy, your working directory: `{copy.resolve()}`\n"
        f"- The open search's cap on findings: {cap}\n"
        f"{draft}"
        f"{note}\n"
        "Your final message is the answer JSON and nothing else.\n"
    )


def reviewer_extract_answer(final: str | None) -> tuple[Any, str | None]:
    """The answer in the final message, unwrapping one code fence; or why there is none."""
    if not final or not final.strip():
        return None, "the session gave no final message"
    text = final.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*)\n```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        answer = json.loads(text)
    except ValueError:
        return None, "the final message is not JSON"
    if not isinstance(answer, dict):
        return None, "the final message is not a JSON object"
    return answer, None


def reviewer_read_answer(parsed: Mapping[str, Any]) -> tuple[Any, str | None, str | None]:
    """The answer, where it came from and why there is none: structured output first (issue #248).

    The order is Claude's validated ``structured_output``, then a final message that is entirely
    one JSON object (bare or in one fence). A message that merely contains an object is never read:
    the prompt quotes example objects, so a quoted one must not pass for the answer.
    """
    structured = parsed.get("structured")
    if isinstance(structured, dict):
        return structured, "structured_output", None
    answer, missing = reviewer_extract_answer(parsed.get("final"))
    if answer is not None:
        return answer, "final_message", None
    return None, None, missing


def reviewer_keep_final_message(final: str | None, out: Path) -> dict[str, Any] | None:
    """Write an unreadable final message beside result.json, bounded; never inside the copy.

    The file is evidence only: nothing reads it back or runs it. ``None`` when there was nothing.
    """
    if not final or not final.strip():
        return None
    raw = final.encode("utf-8")
    kept = raw[:REVIEWER_FINAL_MESSAGE_LIMIT].decode("utf-8", "ignore")
    path = out / "final-message.txt"
    path.write_text(kept, "utf-8")
    return {
        "path": str(path), "bytes": len(raw), "truncated": len(raw) > REVIEWER_FINAL_MESSAGE_LIMIT,
    }


def reviewer_deliver_prompt(
    recipe: ReviewerRecipe, root: Path, message: str
) -> tuple[Path | None, str]:
    """Where the session reads its message: standard input, or a file outside the copy."""
    if recipe.prompt_via != "file":
        return None, message
    prompt_dir = root / "prompt"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / "message.md"
    path.write_text(message, "utf-8")
    return path, ""


def reviewer_pin_executable(executable: Path, identity: Mapping[str, str], root: Path) -> Path:
    """Copy the verified executable into the launch root and check the copy, then run the copy.

    An updater can replace the installed file between the check and the run; it cannot replace a
    private copy, so what runs is what the probe record names.
    """
    pinned = root / "bin" / executable.name
    pinned.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(executable, pinned)
    pinned.chmod(0o755)
    if _reviewer_sha256(pinned) != identity["sha256"]:
        raise ReviewerRefused(f"the copied {executable.name} does not match the verified one")
    return pinned


def reviewer_run_session(
    argv: list[str], *, stdin: str, cwd: Path, env: Mapping[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run the session; a timeout comes back as exit 124, never an exception."""
    try:
        return subprocess.run(
            argv, input=stdin, cwd=str(cwd), env=dict(env), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, REVIEWER_EXIT_TIMEOUT, "", "timed out")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _reviewer_vendor_version(binary: str, env: Mapping[str, str]) -> str | None:
    try:
        proc = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=20, env=dict(env),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


@dataclass
class ReviewerRequest:
    """One targeted-reviewer launch."""

    vendor: str
    model: str
    effort: str
    repo: Path
    head: str
    packet: Path
    prompt: Path
    schema: Path
    out: Path
    open_search_cap: int = REVIEWER_DEFAULT_CAP
    timeout: float = REVIEWER_TIMEOUT_SECONDS
    work_root: Path | None = None
    #: Issue #223: the dollar ceiling, required for a vendor that takes one (Claude).
    max_budget_usd: str | None = None


def reviewer_record_admits(
    record: Any,
    vendor: str,
    platform: str,
    identity: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """Whether a probe record admits *vendor* on *platform*, and why not when it does not.

    Admission needs a complete, well-formed record for exactly this vendor and platform: the
    schema, every check in ``REVIEWER_PROBE_CHECKS`` once and nothing else, each one held (a real
    ``True``), a session that exited 0, and an executable identity. With *identity* (the
    executable about to run), its SHA-256 and version must equal the record's. Anything missing,
    duplicated, malformed or mismatched refuses.
    """
    if not isinstance(record, Mapping):
        return False, "the probe record is not a JSON object"
    if record.get("schema") != REVIEWER_PROBE_RECORD_SCHEMA:
        return False, f"the probe record's schema is not {REVIEWER_PROBE_RECORD_SCHEMA}"
    if record.get("vendor") != vendor:
        return False, f"the probe record is for {record.get('vendor')!r}, not {vendor!r}"
    if record.get("platform") != platform:
        return False, f"the probe record is for {record.get('platform')!r}, not {platform!r}"
    verdicts = record.get("verdicts")
    if not isinstance(verdicts, list) or not verdicts:
        return False, "the probe record has no verdicts"
    names: list[str] = []
    for verdict in verdicts:
        if not (
            isinstance(verdict, Mapping)
            and isinstance(verdict.get("denial"), str)
            and isinstance(verdict.get("held"), bool)
            and isinstance(verdict.get("detail"), str)
        ):
            return False, "a verdict in the probe record is malformed"
        names.append(verdict["denial"])
    if len(names) != len(set(names)):
        return False, "the probe record names a check more than once"
    if set(names) != set(REVIEWER_PROBE_CHECKS):
        missing = sorted(set(REVIEWER_PROBE_CHECKS) - set(names))
        extra = sorted(set(names) - set(REVIEWER_PROBE_CHECKS))
        return False, f"the probe record's checks differ: missing {missing}, unknown {extra}"
    failed = [v["denial"] for v in verdicts if v["held"] is not True]
    if failed:
        return False, "the probe record has checks that did not hold: " + ", ".join(failed)
    exit_code = record.get("session_exit")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 0:
        return False, "the probe record's session did not exit 0"
    executable = record.get("executable")
    if not (
        isinstance(executable, Mapping)
        and isinstance(executable.get("name"), str) and executable["name"]
        and isinstance(executable.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", executable["sha256"])
        and isinstance(executable.get("version"), str) and executable["version"]
    ):
        return False, "the probe record has no well-formed executable identity"
    if identity is not None and (
        identity.get("sha256") != executable["sha256"]
        or identity.get("version") != executable["version"]
    ):
        return False, (
            f"the {vendor} executable is not the one the probe passed on (probed "
            f"{executable['version']}, found {identity.get('version') or 'no version'}); run "
            f"reviewer-probe --vendor {vendor} --record again and commit the record"
        )
    return True, "admitted"


def reviewer_launch(
    request: ReviewerRequest,
    *,
    env: Mapping[str, str] | None = None,
    session: Any = reviewer_run_session,
) -> tuple[dict[str, Any], int]:
    """Start the targeted reviewer headless and return ``(result, exit code)``.

    Refusals (``ReviewerRefused``) happen before anything is created: a vendor with no recipe, a
    prompt that is not saga's, a missing packet or schema, or a head that is not a commit.
    """
    environ = dict(os.environ if env is None else env)
    recipe = reviewer_recipe(request.vendor)
    platform = sys.platform
    if recipe.platforms is not None and platform not in recipe.platforms:
        raise ReviewerRefused(
            f"{request.vendor}'s reviewer recipe passed its probe only on "
            f"{', '.join(recipe.platforms)}, not {platform}"
        )
    if recipe.takes_ceiling:
        problem = reviewer_ceiling_problem(request.max_budget_usd)
        if problem:
            raise ReviewerRefused(
                f"a {request.vendor} reviewer launch needs a spending ceiling: {problem}"
            )
    elif request.max_budget_usd is not None:
        raise ReviewerRefused(
            f"{request.vendor} has no dollar ceiling; --max-budget-usd cannot be honoured"
        )
    executable: Path | None = None
    identity: dict[str, str] | None = None
    record: Mapping[str, Any] | None = None
    if recipe.executable is not None:
        record = REVIEWER_ADMISSIONS.get((request.vendor, platform))
        if record is None:
            raise ReviewerRefused(f"{request.vendor} has no admitted probe record on {platform}")
        admitted, why = reviewer_record_admits(record, request.vendor, platform)
        if not admitted:
            raise ReviewerRefused(why)
        executable = recipe.executable(environ)
        # Issue #223's review, finding 2: the bytes are compared before anything runs them, so
        # a replaced or redirected executable is refused without being run.
        if reviewer_executable_file(executable)["sha256"] != record["executable"]["sha256"]:
            raise ReviewerRefused(
                f"the {request.vendor} executable is not the one the probe passed on (its SHA-256 "
                f"differs from the record's); run reviewer-probe --vendor {request.vendor} "
                "--record again and commit the record"
            )
    try:
        prompt_bytes = request.prompt.read_bytes()
    except OSError as exc:
        raise ReviewerRefused(f"cannot read the prompt {request.prompt}: {exc}") from None
    prompt_text = prompt_bytes.decode("utf-8")
    if _reviewer_front_matter(prompt_text).get("id") != REVIEWER_PROMPT_ID:
        raise ReviewerRefused(f"{request.prompt} is not saga's {REVIEWER_PROMPT_ID}")
    if not request.schema.is_file():
        raise ReviewerRefused(f"the answer schema {request.schema} does not exist")
    try:
        schema_object = json.loads(request.schema.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewerRefused(f"the answer schema {request.schema} is not JSON: {exc}") from None
    if not isinstance(schema_object, dict):
        raise ReviewerRefused(f"the answer schema {request.schema} is not a JSON object")
    answer_schema = json.dumps(schema_object, separators=(",", ":"), ensure_ascii=False)
    if not request.packet.is_dir():
        raise ReviewerRefused(f"the review packet {request.packet} is not a directory")
    wrapper = reviewer_wrapper_path()
    if not wrapper.is_file():
        raise ReviewerRefused(f"the roles library's wrapper {wrapper} is missing")
    widening = recipe.widening(environ) if recipe.widening is not None else []
    if widening:
        raise ReviewerRefused(
            "settings outside the copy would widen the reviewer's sandbox: " + "; ".join(widening)
        )

    root = (request.work_root or reviewer_work_root(environ)) / (
        f"{request.repo.resolve().name}-{request.head[:12]}-{os.urandom(4).hex()}"
    )
    copy = root / "copy"
    session_env = reviewer_session_environment(
        environ, recipe.api_key_variables, recipe.api_key_prefixes
    )
    home = _reviewer_home(session_env)
    for label, path in (("scratch copy", copy), ("review packet", request.packet)):
        problem = reviewer_allowed_read_problem(path.absolute(), home)
        if problem:
            raise ReviewerRefused(f"the {label} cannot be allowed back inside the blocked home: "
                                  f"{problem}")
    reviewer_offline_python(session_env)
    toolchain, dropped = reviewer_toolchain_paths(session_env)
    reviewer_export_head(request.repo, request.head, copy)
    withheld = reviewer_withhold_untrusted(
        copy, recipe.untrusted_dirs, recipe.untrusted_files, recipe.instruction_names
    )
    # Issue #262: cargo builds offline from the packet's vendored crates, through a read-only
    # cargo home beside the copy and the shim in it.
    vendor = reviewer_packet_vendor(request.packet)
    node_modules = reviewer_packet_node(request.packet)
    reviewer_link_node_modules(copy, node_modules)
    packages = reviewer_packet_python(request.packet)
    python_env = reviewer_python_env(root, packages, session_env)
    dart_cache = reviewer_packet_dart(request.packet)
    dart = (reviewer_dart_env(root, copy, dart_cache, session_env)
            if recipe.temp_dir is not None else None)
    cargo_home = reviewer_cargo_home(root, vendor, session_env)
    reviewer_offline_cargo(session_env, cargo_home)
    dependency_reads = [
        {"path": str(cargo_home.resolve()),
         "reason": "the reviewer's read-only cargo home, offline (issue #262)"},
    ] + ([{"path": str(vendor),
           "reason": "the packet's vendored Rust dependencies, read-only (issue #262)"}]
         if vendor is not None else []) + ([
        {"path": str(python_env.resolve()),
         "reason": "the reviewer's Python environment beside the copy, read-only; its bin holds "
                   "only python3 and python"},
        {"path": str(packages[0]) if packages else "",
         "reason": "the packet's installed Python packages, read-only"},
    ] if python_env is not None and packages is not None else []) + reviewer_dart_reads(
        dart, dart_cache, home, reviewer_dart_pub_cache_dir(copy) if dart is not None else None
    ) + ([
        {"path": str(node_modules),
         "reason": "the packet's installed npm packages, read-only; the copy's node_modules "
                   "links here"},
    ] if node_modules is not None else [])
    settings_path, extra_env = recipe.materialize(
        recipe.settings(
            copy, request.packet, session_env, toolchain=toolchain,
            read_only=[item["path"] for item in dependency_reads],
        ),
        root, copy, path_front=reviewer_toolchain_front(session_env),
    )
    manifest = _reviewer_manifest(copy)
    configuration = reviewer_configuration_fingerprint(recipe.config_sources(copy, session_env))
    message = reviewer_launch_message(
        wrapper.read_text(encoding="utf-8"), prompt_text, request.packet, copy,
        request.open_search_cap, withheld,
        draft_folder=recipe.temp_dir(copy) if recipe.temp_dir is not None else None,
    )
    prompt_path, stdin = reviewer_deliver_prompt(recipe, root, message)
    if executable is not None and record is not None:
        try:
            executable = reviewer_pin_executable(executable, record["executable"], root)
            # The version comes only from the verified copy, without the API-key variables.
            identity = reviewer_executable_identity(executable, session_env)
            admitted, why = reviewer_record_admits(record, request.vendor, platform, identity)
            if not admitted:
                raise ReviewerRefused(why)
        except ReviewerRefused:
            shutil.rmtree(root, ignore_errors=True)
            raise
    argv = recipe.argv(
        request.model, request.effort, settings_path, max_budget_usd=request.max_budget_usd,
        executable=executable, prompt_path=prompt_path, answer_schema=answer_schema,
    )
    proc = session(
        argv, stdin=stdin, cwd=copy, env={**session_env, **extra_env}, timeout=request.timeout
    )
    parsed = recipe.parse(proc.stdout)
    answer, answer_source, missing = reviewer_read_answer(parsed)

    shell_reads = [
        {"path": str(Path(extra_env[REVIEWER_SHELL_PREFIX]).parent),
         "reason": "the reviewer's shell prefix, which keeps start-up exports out (issue #225)"}
    ] if REVIEWER_SHELL_PREFIX in extra_env else []
    temp_reads = [
        {"path": str(recipe.temp_dir(copy)),
         "reason": "the reviewer's own temp folder, also writable and beside the copy"}
    ] if recipe.temp_dir is not None else []
    request.out.mkdir(parents=True, exist_ok=True)
    answer_path = request.out / "answer.json"
    final_message: dict[str, Any] | None = None
    if answer is not None:
        answer_path.write_text(json.dumps(answer, indent=2, ensure_ascii=False) + "\n", "utf-8")
    else:
        final_message = reviewer_keep_final_message(parsed.get("final"), request.out)
    if proc.returncode == REVIEWER_EXIT_TIMEOUT:
        code, error = REVIEWER_EXIT_TIMEOUT, "the session timed out"
    elif answer is None:
        code, error = REVIEWER_EXIT_NO_ANSWER, parsed.get("error") or missing
    else:
        code, error = 0, parsed.get("error")
    result = {
        "schema": REVIEWER_RESULT_SCHEMA,
        "vendor": request.vendor,
        "vendor_version": (
            identity["version"] if identity is not None
            else _reviewer_vendor_version(recipe.binary, session_env)
        ),
        "model": {"requested": request.model, "resolved": parsed["resolved"]},
        "effort": request.effort,
        "ceiling_usd": request.max_budget_usd,
        "executable": identity,
        "usage": parsed["usage"],
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "schema_sha256": hashlib.sha256(request.schema.read_bytes()).hexdigest(),
        "configuration": configuration,
        "scratch": {
            "path": str(copy),
            "withheld": withheld,
            "changes": reviewer_scratch_changes(copy, manifest),
        },
        "sandbox_reads": {
            "allowed": [
                {"path": str(copy.resolve()), "reason": "the scratch copy the review works in"},
                {"path": str(request.packet.resolve()), "reason": "the review packet"},
            ] + shell_reads + dependency_reads + list(toolchain) + temp_reads,
            "dropped": dropped,
        },
        "answer_path": str(answer_path) if answer is not None else None,
        "answer_source": answer_source,
        "final_message": final_message,
        "exit": code,
        "error": error,
    }
    (request.out / "result.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    return result, code


#: The address the probe's network check tries, from inside the session and from outside it.
REVIEWER_PROBE_URL = "https://example.com"
#: curl exit statuses that mean the connection never left: 6, the name did not resolve; 7, the
#: connection was refused. 56 counts only with a refused proxy tunnel (Claude's sandbox proxy
#: answers CONNECT with 403; since issue #225 its commands get no proxy variables and give 6).
#: Timeouts (28), TLS and certificate failures (35, 51, 58, 60, 77, 83, 90, 91) and an unrunnable
#: curl (126, 127) prove nothing, so they never count as denial.
REVIEWER_NETWORK_DENIED = frozenset({"6", "7"})

#: The fixed command the probe asks the session to run. Each line records its own exit status in
#: ``probe-results.txt`` inside the copy, so every verdict comes from the command, never the model.
REVIEWER_PROBE_SCRIPT = """\
r=probe-results.txt
: > "$r"
cat "{outside}/canary.txt" > /dev/null 2>&1; echo "read=$?" >> "$r"
touch "{outside}/written" 2> /dev/null; echo "write_outside=$?" >> "$r"
touch inside-written 2> /dev/null; echo "write_inside=$?" >> "$r"
touch "${{TMPDIR:-/tmp}}/reviewer-probe-{tag}" 2> /dev/null; echo "write_tmpdir=$?" >> "$r"
touch "/tmp/reviewer-probe-{tag}" 2> /dev/null; echo "write_tmp=$?" >> "$r"
c=$(curl -sS -m 5 -o /dev/null -w '%{{http_connect}}' {url} 2> /dev/null); echo "network=$?" >> "$r"
echo "network_connect=$c" >> "$r"
if [ -n "${{REVIEWER_PROBE_TOKEN+x}}" ]; then v=set; else v=unset; fi; echo "variable=$v" >> "$r"
cat "{home_canary}" > /dev/null 2>&1; echo "read_home=$?" >> "$r"
cat "{packet}/packet.txt" > /dev/null 2>&1; echo "read_packet=$?" >> "$r"
python3 -m unittest discover -s tests -q > /dev/null 2>&1; echo "python_test=$?" >> "$r"
git --version > /dev/null 2>&1; echo "git=$?" >> "$r"
[ -n "${{REVIEWER_PROBE_PLAIN+x}}" ] && v=set || v=unset; echo "plain_variable=$v" >> "$r"
cat "{vendor_canary}" > /dev/null 2>&1; echo "read_vendor_home=$?" >> "$r"
touch "{vendor_write}" 2> /dev/null; echo "write_vendor_home=$?" >> "$r"
"""
#: Every recipe's probe checks shell start-up exports (issue #225 added Claude's).
REVIEWER_PROBE_STARTUP_LINE = (
    '[ -n "${REVIEWER_PROBE_STARTUP+x}" ] && v=set || v=unset; '
    'echo "startup_variable=$v" >> "$r"\n'
)

#: A real Python test the probe runs in the copy: blocking home must leave the toolchain working.
REVIEWER_PROBE_TEST = """\
import unittest


class ReviewerProbeTest(unittest.TestCase):
    def test_the_toolchain_runs(self):
        self.assertEqual(sum([1, 2]), 3)
"""

REVIEWER_PROBE_MESSAGE = (
    "Run exactly this one Bash command, from your working directory, and then reply with the "
    "single word done: sh probe.sh"
)

REVIEWER_PROBE_RECORD_SCHEMA = "reviewer_probe_record.v1"

#: Every check a probe makes, by name, for every recipe. A record admits a vendor only when it
#: holds exactly these.
REVIEWER_PROBE_CHECKS = (
    "read-credential", "write-outside", "write-inside", "write-tmpdir", "write-tmp", "network",
    "credential-variable", "read-home", "read-packet", "python-test", "git-runs",
    "plain-variable", "no-canary-in-output",
    # Issue #223.
    "read-vendor-home", "write-vendor-home", "read-vendor-credential", "startup-variable",
    "answer-parsed", "session-exit",
)


def reviewer_network_reachable(env: Mapping[str, str]) -> int:
    """curl's exit status for the probe's address, run outside any sandbox; 127 without curl."""
    try:
        proc = subprocess.run(
            ["curl", "-sS", "-m", "5", "-o", os.devnull, REVIEWER_PROBE_URL],
            capture_output=True, timeout=20, env=dict(env), check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127
    return proc.returncode


def reviewer_network_verdict(
    results: Mapping[str, str], reachability: tuple[int, int] | None
) -> tuple[bool, str]:
    """Whether the network was denied by the sandbox, not by the network itself.

    Denial counts only when the same address was reachable from outside the session just before
    and just after it, and the session's curl failed in a way that means the connection never
    left. Anything else, an unreachable network included, is inconclusive and does not hold.
    """
    code, connect = results.get("network"), results.get("network_connect", "")
    before, after = reachability if reachability is not None else (None, None)
    detail = f"network={code} connect={connect} outside_before={before} outside_after={after}"
    if before != 0 or after != 0:
        return False, detail + " (inconclusive: the address was not reachable from outside)"
    if code in REVIEWER_NETWORK_DENIED or (code == "56" and connect == "403"):
        return True, detail
    return False, detail


def reviewer_probe_verdicts(
    root: Path,
    outside: Path,
    tag: str,
    canaries: Sequence[str],
    session_output: str,
    *,
    parsed: Mapping[str, Any] | None = None,
    session_exit: int | None = None,
    reachability: tuple[int, int] | None = None,
    vendor_write: Path | None = None,
    credential_count: int = 0,
    credentials_absent: Sequence[str] = (),
    temp_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Judge each denial from outside the session: the filesystem and the command's own results.

    With *temp_dir*, the recipe leaves that folder writable, so ``write-tmpdir`` holds when the
    session's write to ``TMPDIR`` succeeded and landed there; ``write-tmp`` still proves ``/tmp``.

    Every check in ``REVIEWER_PROBE_CHECKS`` gets a verdict, so a record is always complete; when
    the command never ran, each check that needed it does not hold.
    """
    copy = root / "copy"
    results_path = copy / "probe-results.txt"
    try:
        text = results_path.read_text(encoding="utf-8")
        ran = True
    except OSError:
        text, ran = "", False
    lines = text.splitlines()
    results = dict(line.split("=", 1) for line in lines if "=" in line)
    seen = text + "\n" + session_output

    def nonzero(key: str) -> bool:
        return results.get(key, "0") not in ("", "0")

    def did(key: str) -> str:
        return f"{key}={results.get(key)}" if ran else "the command did not run"

    network_held, network_detail = reviewer_network_verdict(results, reachability)
    credential_keys = [f"read_vendor_credential_{n}" for n in range(credential_count)]
    credential_detail = ", ".join(f"{k}={results.get(k)}" for k in credential_keys)
    if credentials_absent:
        credential_detail += (", " if credential_detail else "") + (
            f"{len(credentials_absent)} absent"
        )
    canary_seen = any(c in seen for c in canaries)
    answer = parsed or {}
    verdicts = [
        ("read-credential", nonzero("read"), did("read")),
        ("write-outside", nonzero("write_outside") and not (outside / "written").exists(),
         did("write_outside")),
        ("write-inside", results.get("write_inside") == "0" and (copy / "inside-written").exists(),
         did("write_inside")),
        ("write-tmpdir",
         (results.get("write_tmpdir") == "0" and (temp_dir / f"reviewer-probe-{tag}").exists())
         if temp_dir is not None else nonzero("write_tmpdir"),
         did("write_tmpdir")),
        ("write-tmp", nonzero("write_tmp") and not Path(f"/tmp/reviewer-probe-{tag}").exists(),
         did("write_tmp")),
        # Issue #223: denial is proven against a reachability check made outside the session.
        ("network", ran and network_held, network_detail if ran else did("network")),
        ("credential-variable", results.get("variable") == "unset", did("variable")),
        # Issue #189: the whole home directory is blocked, and only what the review needs is back.
        ("read-home", nonzero("read_home"), did("read_home")),
        ("read-packet", results.get("read_packet") == "0", did("read_packet")),
        ("python-test", results.get("python_test") == "0", did("python_test")),
        ("git-runs", results.get("git") == "0", did("git")),
        ("plain-variable", results.get("plain_variable") == "unset", did("plain_variable")),
        ("no-canary-in-output", ran and not canary_seen,
         "a canary value appeared in the results or the session's output" if canary_seen
         else ("no canary value seen" if ran else "the command did not run")),
        # Issue #223: the vendor's own state, sign-in files and shell start-up exports.
        ("read-vendor-home", nonzero("read_vendor_home"), did("read_vendor_home")),
        ("write-vendor-home", nonzero("write_vendor_home") and not (
            vendor_write is not None and vendor_write.exists()
        ), did("write_vendor_home")),
        ("read-vendor-credential", ran and all(nonzero(k) for k in credential_keys),
         (credential_detail or "no sign-in file declared") if ran else did("credential")),
        ("startup-variable", results.get("startup_variable") == "unset", did("startup_variable")),
        ("answer-parsed", bool(answer.get("final")) and not answer.get("is_error"),
         "a final message was parsed" if answer.get("final") and not answer.get("is_error")
         else f"no answer: {answer.get('error') or 'the session gave no final message'}"),
        ("session-exit", session_exit == 0, f"exit={session_exit}"),
    ]
    return [{"denial": name, "held": held, "detail": detail} for name, held, detail in verdicts]


def reviewer_probe(
    vendor: str,
    model: str | None = None,
    effort: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    session: Any = reviewer_run_session,
    work_root: Path | None = None,
    keep: bool = False,
    record_path: Path | None = None,
    max_budget_usd: str | None = None,
    reachable: Any = reviewer_network_reachable,
) -> tuple[list[dict[str, Any]], int]:
    """Run *vendor*'s reviewer recipe, or its candidate recipe, live and check each denial.

    Besides the probe directory it plants a canary file directly in the home directory and one in
    the vendor's own state directory, both outside every credential path, and removes them
    however the probe ends. With *record_path* it writes the record a candidate's admission is
    reviewed against.
    """
    recipe = reviewer_probe_recipe(vendor)
    model = model or recipe.probe_model
    platform = sys.platform
    tag = os.urandom(6).hex()
    canary_file = f"reviewer-probe-canary-{os.urandom(8).hex()}"
    canary_variable = f"reviewer-probe-variable-{os.urandom(8).hex()}"
    canary_home = f"reviewer-probe-home-{os.urandom(8).hex()}"
    canary_plain = f"reviewer-probe-plain-{os.urandom(8).hex()}"
    canary_vendor = f"reviewer-probe-vendor-{os.urandom(8).hex()}"
    canary_startup = f"reviewer-probe-startup-{os.urandom(8).hex()}"
    environ = dict(os.environ if env is None else env)
    environ["REVIEWER_PROBE_TOKEN"] = canary_variable
    environ["REVIEWER_PROBE_PLAIN"] = canary_plain
    home = _reviewer_home(environ)
    identity: dict[str, str] | None = None
    if recipe.executable is not None:
        # Its version is read from the pinned copy below, never from the installed file.
        executable: Path | None = recipe.executable(environ)
    else:
        executable = None
        found = shutil.which(recipe.binary, path=environ.get("PATH", ""))
        identity = reviewer_executable_identity(Path(found).resolve(), environ) if found else None
    root = (work_root or reviewer_work_root(environ)) / f"probe-{tag}"
    copy, outside, packet = root / "copy", root / "outside", root / "packet"
    startup = root / "startup"
    home_canary = home / f".reviewer-probe-home-canary-{tag}"
    vendor_home = _reviewer_expand(recipe.vendor_home, home) if recipe.vendor_home else None
    vendor_canary = (vendor_home or root / "no-vendor-home") / f".reviewer-probe-canary-{tag}"
    vendor_write = (
        _reviewer_expand(recipe.vendor_writable, home) / f"reviewer-probe-write-{tag}"
        if recipe.vendor_writable else root / "no-vendor-home" / "write"
    )
    credentials = [_reviewer_expand(path, home) for path in recipe.credential_files]
    present = [path for path in credentials if path.is_file()]
    absent = [str(path.name) for path in credentials if not path.is_file()]
    (copy / "tests").mkdir(parents=True)
    outside.mkdir()
    packet.mkdir()
    startup.mkdir()
    (outside / "canary.txt").write_text(canary_file + "\n", "utf-8")
    (packet / "packet.txt").write_text("the review packet\n", "utf-8")
    (copy / "tests" / "test_reviewer_probe.py").write_text(REVIEWER_PROBE_TEST, "utf-8")
    script = REVIEWER_PROBE_SCRIPT.format(
        outside=outside, tag=tag, home_canary=home_canary, packet=packet, url=REVIEWER_PROBE_URL,
        vendor_canary=vendor_canary, vendor_write=vendor_write,
    ) + "".join(
        f'cat "{path}" > /dev/null 2>&1; echo "read_vendor_credential_{n}=$?" >> "$r"\n'
        for n, path in enumerate(present)
    ) + REVIEWER_PROBE_STARTUP_LINE
    (copy / "probe.sh").write_text(script, "utf-8")
    # Shell start-up files that export an inert secret; the session's shell must not hand it to
    # a sandboxed command. Set through the environment, so no operator file is edited.
    export = f"export REVIEWER_PROBE_STARTUP={canary_startup}\n"
    for name in (".zshenv", ".zprofile", ".zshrc", "bash_env", "sh_env"):
        (startup / name).write_text(export, "utf-8")
    startup_env = {
        "ZDOTDIR": str(startup), "BASH_ENV": str(startup / "bash_env"),
        "ENV": str(startup / "sh_env"),
    }
    planted: list[Path] = []
    try:
        home_canary.write_text(canary_home + "\n", "utf-8")
        planted.append(home_canary)
        if vendor_home is not None and vendor_home.is_dir():
            vendor_canary.write_text(canary_vendor + "\n", "utf-8")
            planted.append(vendor_canary)
        session_env = reviewer_session_environment(
            environ, recipe.api_key_variables, recipe.api_key_prefixes
        )
        # Issue #262: the same offline cargo home and read-only vendored folder a review gets, so
        # every denial is checked with them in place.
        vendored = packet / "dependencies" / "rust"
        vendored.mkdir(parents=True)
        cargo_home = reviewer_cargo_home(root, vendored.resolve(), session_env)
        reviewer_offline_cargo(session_env, cargo_home)
        settings = recipe.settings(
            copy, packet, session_env, extra_deny_read=[str(outside)],
            read_only=[str(cargo_home.resolve()), str(vendored.resolve())],
        )
        settings_path, extra_env = recipe.materialize(settings, root, copy)
        prompt_path, stdin = reviewer_deliver_prompt(recipe, root, REVIEWER_PROBE_MESSAGE)
        if executable is not None:
            executable = reviewer_pin_executable(
                executable, reviewer_executable_file(executable), root
            )
            identity = reviewer_executable_identity(executable, session_env)
        ceiling = (max_budget_usd or REVIEWER_PROBE_CEILING_USD) if recipe.takes_ceiling else None
        before = reachable(environ)
        proc = session(
            recipe.argv(model, effort, settings_path, max_budget_usd=ceiling,
                        executable=executable, prompt_path=prompt_path),
            stdin=stdin, cwd=copy, env={**session_env, **extra_env, **startup_env}, timeout=300,
        )
        after = reachable(environ)
        verdicts = reviewer_probe_verdicts(
            root, outside, tag,
            (canary_file, canary_variable, canary_home, canary_plain, canary_vendor,
             canary_startup),
            (proc.stdout or "") + (proc.stderr or ""),
            parsed=recipe.parse(proc.stdout or ""), session_exit=proc.returncode,
            reachability=(before, after), vendor_write=vendor_write,
            credential_count=len(present), credentials_absent=absent,
            temp_dir=recipe.temp_dir(copy) if recipe.temp_dir is not None else None,
        )
    finally:
        for path in planted:
            path.unlink(missing_ok=True)
        vendor_write.unlink(missing_ok=True)
        Path(f"/tmp/reviewer-probe-{tag}").unlink(missing_ok=True)
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    passed = all(v["held"] for v in verdicts)
    if record_path is not None:
        record = {
            "schema": REVIEWER_PROBE_RECORD_SCHEMA,
            "vendor": vendor,
            "platform": platform,
            "date": time.strftime("%Y-%m-%d", time.gmtime()),
            "model": model,
            "effort": effort,
            "executable": identity,
            "session_exit": proc.returncode,
            # The session ran with the vendor's API-key variables removed; an answer then means
            # it signed in some other way, which for these recipes is the operator's own sign-in.
            "sign_in": "subscription" if any(
                v["denial"] == "answer-parsed" and v["held"] for v in verdicts
            ) else "not established",
            "verdicts": verdicts,
        }
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=2) + "\n", "utf-8")
    return verdicts, 0 if passed else 1


def _reviewer_args(sub: Any) -> None:
    review_p = sub.add_parser(
        "review",
        help="Start saga's targeted reviewer headless in a sandboxed scratch copy (issue #158)",
        description=(
            "Start saga's targeted reviewer headless on a vendor with a reviewer recipe, with its "
            "normal configuration, in a sandboxed export of --head. Writes answer.json and "
            "result.json to --out and prints the result. Exit 0 answer; 2 refused before "
            "anything started; 3 no parsable answer; 124 timed out."
        ),
    )
    review_p.add_argument("--vendor", required=True)
    review_p.add_argument("--model", required=True)
    review_p.add_argument("--effort", required=True)
    review_p.add_argument("--repo", required=True, type=Path, help="The repository to export")
    review_p.add_argument("--head", required=True, help="The commit under review")
    review_p.add_argument("--packet", required=True, type=Path, help="The review packet directory")
    review_p.add_argument(
        "--prompt", required=True, type=Path,
        help="saga's targeted-reviewer-prompt.md (reviewer_answer.py paths prints it)",
    )
    review_p.add_argument("--schema", required=True, type=Path, help="saga's answer schema")
    review_p.add_argument("--out", required=True, type=Path, help="Where answer and result go")
    review_p.add_argument("--open-search-cap", type=int, default=REVIEWER_DEFAULT_CAP)
    review_p.add_argument("--timeout", type=float, default=REVIEWER_TIMEOUT_SECONDS)
    review_p.add_argument(
        "--max-budget-usd", default=None,
        help="Dollar ceiling for the session; required for claude, refused for a vendor without one",
    )
    probe_p = sub.add_parser(
        "reviewer-probe",
        help="Run a vendor's reviewer recipe live and check every sandbox denial",
        description=(
            "Run the reviewer recipe on one fixed command and check, from outside the session, "
            "that a credential read, a read of a canary planted in the home directory, writes "
            "outside the copy and to the temp roots, the network, a credential variable and an "
            "ordinary-named variable are denied, and that a write inside the copy, a read of the "
            "packet, a real Python test and git work. Issue #223 adds: the network denial is "
            "judged against the same address reached from outside the session; the vendor's own "
            "state directory, sign-in files and a secret exported by shell start-up files stay "
            "out of reach; and the session answers and exits 0. Runs a reviewer's recipe or a "
            "candidate's. Exit 0 when every check held, 1 otherwise, 2 for a vendor with neither."
        ),
    )
    probe_p.add_argument("--vendor", required=True)
    probe_p.add_argument("--model", default=None, help="Default: the recipe's probe model")
    probe_p.add_argument("--effort", default=None)
    probe_p.add_argument("--keep", action="store_true", help="Keep the probe directory")
    probe_p.add_argument(
        "--record", type=Path, default=None,
        help="Write the probe record (vendor, platform, executable identity, every verdict) here",
    )
    probe_p.add_argument(
        "--max-budget-usd", default=None,
        help=f"Dollar ceiling for a vendor that takes one (default {REVIEWER_PROBE_CEILING_USD})",
    )


def _reviewer_cli(args: argparse.Namespace) -> int:
    try:
        if args.cmd == "reviewer-probe":
            verdicts, code = reviewer_probe(
                args.vendor, args.model, args.effort, keep=args.keep, record_path=args.record,
                max_budget_usd=args.max_budget_usd,
            )
            json.dump(verdicts, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return code
        result, code = reviewer_launch(
            ReviewerRequest(
                vendor=args.vendor, model=args.model, effort=args.effort, repo=args.repo,
                head=args.head, packet=args.packet, prompt=args.prompt, schema=args.schema,
                out=args.out, open_search_cap=args.open_search_cap, timeout=args.timeout,
                max_budget_usd=args.max_budget_usd,
            )
        )
    except ReviewerRefused as refused:
        print(f"launcher: {refused}", file=sys.stderr)
        return REVIEWER_EXIT_REFUSED
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the headless sandboxed reviewer on one commit."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    _reviewer_args(sub)
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return _reviewer_cli(args)


if __name__ == "__main__":
    raise SystemExit(cli_main())
