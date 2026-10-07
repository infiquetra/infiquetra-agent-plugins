#!/usr/bin/env python3
"""A recording stand-in for mission-control's ``sdlc_manager.py`` (tests only).

Understands ``issue prepare`` and ``issue create-prepared`` well enough for
``review_state.py``'s filer: prepare writes a canned draft and sidecar under
``docs/sdlc-issue-drafts/`` in the working directory and prints
mission-control's JSON shapes; create-prepared marks the sidecar created with
number 412. Every invocation's argv is appended as one JSON array per line to
``$FAKE_MC_LOG`` when set.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def log(argv: list[str]) -> None:
    path = os.environ.get("FAKE_MC_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")


def slug(title: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return text[:60] or "draft"


def main(argv: list[str]) -> int:
    log(argv)
    try:
        at = argv.index("issue")
        verb = argv[at + 1]
    except (ValueError, IndexError):
        verb = ""
    if verb not in ("prepare", "create-prepared"):
        print("fake-sdlc-manager: expected 'issue prepare' or 'issue create-prepared'",
              file=sys.stderr)
        return 2
    if verb == "prepare":
        title = "draft"
        for index, token in enumerate(argv):
            if token == "--title" and index + 1 < len(argv):
                title = argv[index + 1]
        target = Path("docs") / "sdlc-issue-drafts"
        target.mkdir(parents=True, exist_ok=True)
        draft = target / f"2000-01-01-{slug(title)}.md"
        draft.write_text(
            "---\n"
            f"title: {title}\n"
            "repo: infiquetra-agent-plugins\n"
            "type: defect\n"
            "team: asgard\n"
            "project: operations\n"
            "status: Discovering\n"
            "---\n\n# canned\n",
            encoding="utf-8",
        )
        sidecar = draft.with_suffix(".json")
        sidecar.write_text(
            json.dumps({"state": "blocked", "approval_state": None}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"draft": str(draft), "sidecar": str(sidecar),
                          "readiness": {"passed": False}}))
        return 0
    draft = Path(argv[argv.index("create-prepared") + 1])
    sidecar = draft.with_suffix(".json")
    payload = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    payload.update({"state": "created", "created_issue_url": "https://example.invalid/o/r/issues/412",
                    "created_issue_number": 412})
    sidecar.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with open(draft, "a", encoding="utf-8") as handle:
        handle.write("\n## Created Issue\n\n- Number: 412\n")
    print(json.dumps({"created": True, "url": "https://example.invalid/o/r/issues/412",
                      "number": 412, "mapping_pr_url": None}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
