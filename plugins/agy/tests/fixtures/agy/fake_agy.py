#!/usr/bin/env python3
"""Deterministic fake agy executable for wrapper subprocess tests."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _apply_prompt_writes(prompt: str) -> None:
    for line in prompt.splitlines():
        if not line.startswith("FAKE_AGY_WRITE "):
            continue
        raw_path, separator, content = line.removeprefix("FAKE_AGY_WRITE ").partition("::")
        if not separator:
            content = "fake agy content\n"
        path = Path(raw_path.strip())
        if path.is_absolute() or ".." in path.parts:
            print(f"refusing unsafe fake write path: {path}", file=sys.stderr, flush=True)
            raise SystemExit(8)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--print-timeout")
    parser.add_argument("--log-file")
    parser.add_argument("--add-dir", action="append", default=[])
    parser.add_argument("--sandbox", action="store_true")
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    parser.add_argument("--print", dest="prompt", required=True)
    args = parser.parse_args()

    if args.log_file:
        Path(args.log_file).write_text("fake agy log\n", encoding="utf-8")

    if "FAKE_AGY_MODE=nonzero" in args.prompt:
        print("fake agy nonzero stdout", flush=True)
        print("fake agy nonzero stderr", file=sys.stderr, flush=True)
        return 7

    if "FAKE_AGY_MODE=no_output" in args.prompt:
        time.sleep(10)
        return 0

    if "FAKE_AGY_MODE=timeout" in args.prompt:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            print("fake agy still working", flush=True)
            time.sleep(0.2)
        return 0

    _apply_prompt_writes(args.prompt)
    print(f"fake agy success model={args.model}", flush=True)
    print("fake agy stderr note", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
