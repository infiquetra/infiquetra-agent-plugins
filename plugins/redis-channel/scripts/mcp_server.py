#!/usr/bin/env python3
"""Portable entrypoint for the redis-channel MCP server.

Claude Code launches this file from the package root. Any other harness
runs the same file. ``--help`` exits before redis, mcp, or pydantic are
imported, and before the deployment env file is sourced.

The ``serverInfo`` literal below is the version the Claude packaging check
reads. ``server/__init__.py`` carries the same number, and ``build_app``
assigns it to the MCP server's ``serverInfo.version``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ENV = Path.home() / ".claude" / "channels" / "redis-channel" / "source-env.sh"

# The packaging check matches this literal. Keep it equal to plugin.json.
SERVER_INFO = {
    "serverInfo": {
        "name": "redis-channel",
        "version": "0.5.3",
    }
}


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="mcp_server.py",
        description=(
            "Redis Streams bridge for one agent session, as a Model Context "
            "Protocol stdio server. Sources ~/.claude/channels/redis-channel/"
            "source-env.sh when that file exists, then serves until stdin closes."
        ),
    )


def _load_channel_env() -> int:
    """Source the deployment env file, when the operator has one.

    The file is allowed to run a keychain lookup. This script does not name
    a keychain item of its own. A missing file is not an error: the password
    variable may already be in the environment.
    """
    if not SOURCE_ENV.is_file():
        return 0
    completed = subprocess.run(
        [
            "sh",
            "-c",
            'set -a; . "$1"; set +a; env -0',
            "redis-channel-env",
            str(SOURCE_ENV),
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        sys.stderr.buffer.write(completed.stderr or f"redis-channel: could not source {SOURCE_ENV}\n".encode())
        return 1
    # The sourced file is the authority for the names it exports. Copy the
    # shell's environment back so those exports overwrite inherited values.
    skip = {"_", "SHLVL", "PWD", "OLDPWD"}
    for entry in completed.stdout.split(b"\0"):
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        name = key.decode("utf-8", "surrogateescape")
        if not name or name in skip:
            continue
        os.environ[name] = value.decode("utf-8", "surrogateescape")
    return 0


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    loaded = _load_channel_env()
    if loaded != 0:
        return loaded
    sys.path.insert(0, str(PACKAGE_ROOT))
    try:
        from server import __version__
    except ModuleNotFoundError as exc:
        missing = (exc.name or "a runtime package").split(".")[0]
        print(
            f"redis-channel: missing Python package {missing!r}. "
            "Install mcp (1.x), redis, and pydantic. See README.md.",
            file=sys.stderr,
        )
        return 1
    expected = SERVER_INFO["serverInfo"]["version"]
    if __version__ != expected:
        print(
            f"redis-channel: package version {__version__} does not match "
            f"serverInfo version {expected}",
            file=sys.stderr,
        )
        return 2
    try:
        from server.channel import run
    except ModuleNotFoundError as exc:
        missing = (exc.name or "a runtime package").split(".")[0]
        print(
            f"redis-channel: missing Python package {missing!r}. "
            "Install mcp (1.x), redis, and pydantic. See README.md.",
            file=sys.stderr,
        )
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
