#!/usr/bin/env python3
"""Load prior issue, PR, saga, and journal context (thin wrapper).

This aggregated prior issue/PR/checkpoint/journal context for loop resume. Under
the 0.4.0 saga model it is a thin wrapper over ``saga.py``: the durable local
context comes from ``saga.aggregate_context`` (which ``restore``\\s the issue's
saga from its latest immutable tick, gathers round-tagged prior PRs via ``gh``,
and matches journal sections by issue/ADR refs).

The legacy CLI flags (``--repo`` / ``--issue``) and the eight printed JSON keys
are preserved. The engine returns the local-context summary under ``saga``; this
wrapper exposes it under the legacy ``checkpoint`` key (same role: "the latest
durable local artifact for this issue"). It now resolves the issue's saga
directory (``sagas/issue-<N>/``) by FILENAME order rather than globbing
``checkpoints/issue-<N>-*.md`` by ``mtime``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the sibling ``saga.py`` engine is importable whether this script is run
# directly (its dir is already ``sys.path[0]``) or loaded via importlib from an
# arbitrary cwd (the test harness does not add the script dir to ``sys.path``).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import saga  # noqa: E402  (path bootstrap must run before this import)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    owner, repo = saga.parse_repo(args.repo)
    context = saga.aggregate_context(Path.cwd(), owner, repo, args.issue)
    print(
        json.dumps(
            {
                "repo": context["repo"],
                "issue": context["issue"],
                "rounds_seen": context["rounds_seen"],
                "next_round": context["next_round"],
                # Legacy "checkpoint" == the latest durable local artifact for
                # this issue, now the issue's restored saga summary.
                "checkpoint": context["saga"],
                "prior_prs": context["prior_prs"],
                "adr_refs": context["adr_refs"],
                "journal": context["journal"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
