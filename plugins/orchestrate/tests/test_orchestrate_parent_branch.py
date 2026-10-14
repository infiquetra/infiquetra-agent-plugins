from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from orchestrate_support import load_orchestrate

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)
orch = load_orchestrate("orchestrate_parent_branch_test", SCRIPT)


def test_parent_branch_lookup_uses_checkout_origin_repository(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[:4] == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/acme/project.git\n")
        return SimpleNamespace(
            returncode=0,
            stdout='{"data":{"repository":{"issue":{"subIssues":{"totalCount":2}}}}}',
        )

    name, _reason = orch.parent_branch_name(147, runner=runner)

    assert name == "parent/147"
    assert 'repository(owner:"acme",name:"project")' in calls[1][-1]
