"""Resumable scaffold state — an optimization, never the source of truth.

Each step probes live state (repo exists? token vaulted? host in inventory?) and
skips if satisfied; this file just records which steps completed so a resumed run
can narrate progress. A lost state file costs only re-probing, not re-doing.
"""

from __future__ import annotations

import json
import pathlib

STEPS = [
    "validate-spec",
    "repo-create",
    "stamp",
    "author-soul",
    "gen-profiles",
    "gen-harness",
    "discord-app",
    "vault-token",
    "vault-wire",
    "github-app",
    "identity",
    "discord-topology",
    "push",
    "register-host",
    "dry-run-deploy",
]


class ScaffoldState:
    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path)
        self.done: dict[str, bool] = {}
        if self.path.exists():
            self.done = json.loads(self.path.read_text()).get("done", {})

    def mark(self, step: str, value: bool = True) -> None:
        if step not in STEPS:
            raise ValueError(f"unknown step {step!r}")
        self.done[step] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"done": self.done}, indent=2) + "\n")

    def is_done(self, step: str) -> bool:
        return self.done.get(step, False)

    def next_step(self) -> str | None:
        for s in STEPS:
            if not self.done.get(s):
                return s
        return None
