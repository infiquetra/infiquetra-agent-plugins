#!/usr/bin/env python3
"""A recording stand-in for ``gh`` (tests only).

Records each invocation's argv as one JSON array per line in ``$FAKE_GH_LOG``,
writes the ``--body`` value to ``$FAKE_GH_DIR/body-<seq>.md``, and prints a
fake comment URL. Only ``pr comment`` is answered.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    log = os.environ.get("FAKE_GH_LOG", "")
    outdir = os.environ.get("FAKE_GH_DIR", "")
    if not log or not outdir:
        print("fake-gh: FAKE_GH_LOG and FAKE_GH_DIR are required", file=sys.stderr)
        return 2
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(argv) + "\n")
    if argv[1:3] != ["pr", "comment"]:
        print(f"fake-gh: unexpected argv {argv[1:3]!r}", file=sys.stderr)
        return 2
    try:
        body = argv[argv.index("--body") + 1]
    except (ValueError, IndexError):
        print("fake-gh: no --body value", file=sys.stderr)
        return 2
    target = Path(outdir)
    seq = len(list(target.glob("body-*.md"))) + 1
    (target / f"body-{seq}.md").write_text(body, encoding="utf-8")
    print("https://example.invalid/o/r/pull/7#issuecomment-1")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
