"""Entry point: `python -m server` launches the redis-channel MCP server.

``--help`` is answered before ``redis``, ``mcp``, or ``pydantic`` are imported.
Claude Code does not launch this module directly. It launches
``scripts/mcp_server.py``, which sources the deployment env file and then
starts the same server.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="redis-channel",
        description=(
            "Redis Streams bridge for one agent session. With no arguments "
            "this process speaks Model Context Protocol on stdin and stdout. "
            "Runtime packages are mcp (1.x), redis, and pydantic."
        ),
    )


def _run_server() -> int:
    if __package__:
        from .channel import run
    else:
        package_root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(package_root))
        from server.channel import run
    return run()


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    try:
        return _run_server()
    except ModuleNotFoundError as exc:
        missing = (exc.name or "a runtime package").split(".")[0]
        print(
            f"redis-channel: missing Python package {missing!r}. "
            "Install mcp (1.x), redis, and pydantic. See README.md.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
