"""U3 mode-surface tests for the codex delegate (plugins/codex/scripts/codex_delegate.py).

Covers R2 / KTD5:

* Reviewer (read-only) runs against the live tree with a post-run diff-scan proving
  non-mutation against a pre-run ``git status --porcelain`` snapshot. NEW dirt relative to the
  baseline maps to ``out_of_scope_mutation`` with the diff evidence in the bundle. A PRE-DIRTY
  operator tree must NOT false-positive (snapshot-based scan).
* Coder (task / workspace-write) runs inside a disposable, remotes-stripped clone via
  ``--cd`` / ``--skip-git-repo-check``, captures the resulting diff as a preserved patch
  artifact (never auto-applied to the live tree), honors ``write_set`` scoping, and tears the
  clone down on both success and failure. The live primary tree is untouched by every run.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codex_delegate.py"


def _load_module():
    # The wrapper inserts scripts/_bundled on import. Do not also insert
    # scripts/: that insert existed so fleet_commons_shim could be imported,
    # and this package does not carry the shim.
    spec = importlib.util.spec_from_file_location("codex_delegate_modes_under_test", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


codex_delegate = _load_module()


# --- git + fake-bin harness --------------------------------------------------------------------


def _git(args, *, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> Path:
    """Initialize a git repo with one committed file so HEAD resolves (clone base)."""
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    _git(["config", "commit.gpgsign", "false"], cwd=path)
    (path / "README.md").write_text("baseline readme\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-q", "-m", "seed"], cwd=path)
    return path


def _porcelain(path: Path) -> str:
    """Worktree dirt excluding the delegate's own ``.claude`` evidence bundle.

    The bundle legitimately lands under ``.claude/codex/runs`` in the live tree; the
    "live tree untouched" guarantee is about SOURCE/working files, so it is measured the same
    way the delegate itself measures mutation (``:(exclude).claude``).
    """
    return subprocess.run(
        ["git", "status", "--porcelain", "--", ".", ":(exclude).claude"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _write_shim(tmp_path: Path, body: str) -> Path:
    bin_path = tmp_path / "fake-codex.py"
    bin_path.write_text(body, encoding="utf-8")
    bin_path.chmod(0o755)
    shim = tmp_path / "codex-shim"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bin_path}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return shim


# Fakes ignore the sandbox flag deliberately — the whole point of the diff-scan is to catch a
# codex that mutated despite ``-s read-only``. Each parses ``-o`` to write the last message.

# Writes ``note.txt`` into its cwd. For a coder run cwd is the disposable clone; for a reviewer
# run cwd is the live repo (used to prove the scan catches an out-of-band mutation).
_FAKE_WRITES_NOTE = """#!/usr/bin/env python3
import sys, os
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
sys.stdin.read()
print('{"type": "session_start"}', flush=True)
with open(os.path.join(os.getcwd(), "note.txt"), "w") as fh:
    fh.write("codex was here\\n")
if out_path:
    open(out_path, "w").write("wrote note.txt")
sys.exit(0)
"""

# Appends to the tracked README.md in cwd (mutates a tracked file → non-empty diff/patch).
_FAKE_APPENDS_README = """#!/usr/bin/env python3
import sys, os
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
sys.stdin.read()
print('{"type": "session_start"}', flush=True)
with open(os.path.join(os.getcwd(), "README.md"), "a") as fh:
    fh.write("codex appended this line\\n")
if out_path:
    open(out_path, "w").write("appended")
sys.exit(0)
"""

# Non-mutating: reads stdin, writes the last message, touches nothing in the workspace.
_FAKE_NO_MUTATION = """#!/usr/bin/env python3
import sys
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
sys.stdin.read()
print('{"type": "session_start"}', flush=True)
if out_path:
    open(out_path, "w").write("nothing changed")
sys.exit(0)
"""

# Writes note.txt then exits nonzero — exercises the failure-path clone teardown.
_FAKE_FAILS = """#!/usr/bin/env python3
import sys, os
sys.stdin.read()
print('{"type": "session_start"}', flush=True)
with open(os.path.join(os.getcwd(), "note.txt"), "w") as fh:
    fh.write("partial\\n")
sys.exit(3)
"""


def _run(monkeypatch, tmp_path, repo_root, envelope_kwargs, fake_body, *, clone_base=None):
    """Run create_supervised_bundle with a fake codex; return (result, bundle_path)."""
    if clone_base is not None:
        # Force disposable clones under a known dir so teardown can be asserted.
        monkeypatch.setattr(codex_delegate.tempfile, "tempdir", str(clone_base))
    shim = _write_shim(tmp_path, fake_body)
    envelope = codex_delegate.Envelope.from_mapping(envelope_kwargs)
    result = codex_delegate.create_supervised_bundle(
        envelope,
        repo_root=repo_root,
        run_id="modes-run",
        codex_bin=str(shim),
    )
    bundle = repo_root / ".claude" / "codex" / "runs" / "modes-run"
    return result, bundle


def _reviewer_env(**overrides):
    payload = {"schema": codex_delegate.SCHEMA, "role": "reviewer", "task": "Review the diff."}
    payload.update(overrides)
    return payload


def _coder_env(write_set, **overrides):
    payload = {
        "schema": codex_delegate.SCHEMA,
        "role": "coder",
        "mode": "task",
        "task": "Make the change.",
        "write_set": write_set,
    }
    payload.update(overrides)
    return payload


# --- Reviewer: read-only diff-scan proof -------------------------------------------------------


def test_reviewer_mutation_flags_out_of_scope_mutation(monkeypatch, tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    result, bundle = _run(monkeypatch, tmp_path, repo, _reviewer_env(), _FAKE_APPENDS_README)

    assert result.status == "out_of_scope_mutation"
    # Runs -s read-only against the live repo.
    command = json.loads((bundle / "command.json").read_text())
    assert command["sandbox"] == "read-only"
    assert command["working_directory"] == str(repo)
    assert "-s" in command["argv"]
    assert command["argv"][command["argv"].index("-s") + 1] == "read-only"

    # Diff-scan evidence is in the bundle and names the NEW dirt.
    scan = json.loads((bundle / "diff-scan.json").read_text())
    assert scan["mutation_detected"] is True
    assert "README.md" in scan["new_paths"]
    assert scan["baseline_dirty"] == []
    # A concrete patch of the mutation is preserved.
    assert (bundle / "mutation.patch").exists()
    assert "codex appended this line" in (bundle / "mutation.patch").read_text()

    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "out_of_scope_mutation"


def test_reviewer_untracked_mutation_is_flagged(monkeypatch, tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    result, bundle = _run(monkeypatch, tmp_path, repo, _reviewer_env(), _FAKE_WRITES_NOTE)

    assert result.status == "out_of_scope_mutation"
    scan = json.loads((bundle / "diff-scan.json").read_text())
    assert "note.txt" in scan["new_paths"]


def test_reviewer_pre_dirty_tree_does_not_false_positive(monkeypatch, tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    # Operator's pre-existing dirt BEFORE the delegate runs.
    (repo / "README.md").write_text("operator edited this before the run\n", encoding="utf-8")
    (repo / "scratch.txt").write_text("operator scratch\n", encoding="utf-8")
    pre = _porcelain(repo)
    assert "README.md" in pre and "scratch.txt" in pre

    result, bundle = _run(monkeypatch, tmp_path, repo, _reviewer_env(), _FAKE_NO_MUTATION)

    # A non-mutating reviewer over a pre-dirty tree is a clean success — no false positive.
    assert result.status == "success"
    scan = json.loads((bundle / "diff-scan.json").read_text())
    assert scan["mutation_detected"] is False
    assert scan["new_paths"] == []
    # The pre-existing dirt is recorded as baseline, not counted as a mutation.
    assert "README.md" in scan["baseline_dirty"]
    assert "scratch.txt" in scan["baseline_dirty"]
    assert not (bundle / "mutation.patch").exists()
    # The operator's working tree is exactly as they left it (delegate touched no source files).
    assert _porcelain(repo) == pre


# --- Coder: disposable clone + preserved patch -------------------------------------------------


def test_coder_captures_patch_and_leaves_live_tree_untouched(monkeypatch, tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    clone_base = tmp_path / "clones"
    clone_base.mkdir()
    pre = _porcelain(repo)  # clean

    result, bundle = _run(
        monkeypatch,
        tmp_path,
        repo,
        _coder_env(write_set=["note.txt"]),
        _FAKE_WRITES_NOTE,
        clone_base=clone_base,
    )

    assert result.status == "patch_ready"
    # Ran -s workspace-write inside the disposable clone, not the live tree.
    command = json.loads((bundle / "command.json").read_text())
    assert command["sandbox"] == "workspace-write"
    assert command["working_directory"] != str(repo)
    assert "--cd" in command["argv"]
    assert "--skip-git-repo-check" in command["argv"]

    # Patch preserved in the bundle; never applied to the live tree (KTD5).
    patch = (bundle / "diff.patch").read_text()
    assert "note.txt" in patch
    changed = json.loads((bundle / "changed-paths.json").read_text())
    assert changed["changed_paths"] == ["note.txt"]
    assert changed["out_of_scope_paths"] == []

    # Live primary tree is untouched: git status identical to the pre-run snapshot, and the
    # clone's mutation did NOT leak into the live repo.
    assert _porcelain(repo) == pre
    assert not (repo / "note.txt").exists()

    # Clone was torn down on the success path.
    assert glob.glob(str(clone_base / "codex-clone-*")) == []


def test_coder_out_of_write_set_mutation_is_flagged(monkeypatch, tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    clone_base = tmp_path / "clones"
    clone_base.mkdir()
    pre = _porcelain(repo)

    # Fake writes note.txt, but the write_set only permits allowed.txt.
    result, bundle = _run(
        monkeypatch,
        tmp_path,
        repo,
        _coder_env(write_set=["allowed.txt"]),
        _FAKE_WRITES_NOTE,
        clone_base=clone_base,
    )

    assert result.status == "out_of_scope_mutation"
    changed = json.loads((bundle / "changed-paths.json").read_text())
    assert changed["changed_paths"] == ["note.txt"]
    assert changed["out_of_scope_paths"] == ["note.txt"]
    # Patch is still captured as evidence.
    assert "note.txt" in (bundle / "diff.patch").read_text()
    # Live tree untouched; clone gone.
    assert _porcelain(repo) == pre
    assert glob.glob(str(clone_base / "codex-clone-*")) == []


def test_coder_clone_is_torn_down_on_failure_path(monkeypatch, tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    clone_base = tmp_path / "clones"
    clone_base.mkdir()
    pre = _porcelain(repo)

    # Fake mutates the clone then exits nonzero → terminal error, clone still torn down.
    result, bundle = _run(
        monkeypatch,
        tmp_path,
        repo,
        _coder_env(write_set=["note.txt"]),
        _FAKE_FAILS,
        clone_base=clone_base,
    )

    assert result.status == "error"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] != "running"
    # Teardown happened on the failure path too.
    assert glob.glob(str(clone_base / "codex-clone-*")) == []
    # Live tree untouched.
    assert _porcelain(repo) == pre
    assert not (repo / "note.txt").exists()


def test_coder_clone_strips_remotes(monkeypatch, tmp_path) -> None:
    upstream = _init_repo(tmp_path / "upstream")
    # Give the live repo a remote so the clone would inherit one absent the strip.
    repo = _init_repo(tmp_path / "repo")
    _git(["remote", "add", "origin", str(upstream)], cwd=repo)
    clone_base = tmp_path / "clones"
    clone_base.mkdir()

    result, bundle = _run(
        monkeypatch,
        tmp_path,
        repo,
        _coder_env(write_set=["note.txt"]),
        _FAKE_WRITES_NOTE,
        clone_base=clone_base,
    )

    assert result.status == "patch_ready"
    command = json.loads((bundle / "command.json").read_text())
    # The clone's inherited remote was stripped (recorded in the mode-surface evidence).
    assert command["mode_surface"]["removed_remotes"] == ["origin"]
    assert glob.glob(str(clone_base / "codex-clone-*")) == []


def test_coder_clone_setup_failure_is_terminal_and_never_touches_live_tree(
    monkeypatch, tmp_path
) -> None:
    # A non-git repo_root cannot be cloned (rev-parse HEAD fails) → terminal error, no mutation.
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    clone_base = tmp_path / "clones"
    clone_base.mkdir()

    result, bundle = _run(
        monkeypatch,
        tmp_path,
        repo,
        _coder_env(write_set=["note.txt"]),
        _FAKE_WRITES_NOTE,
        clone_base=clone_base,
    )

    assert result.status == "error"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] != "running"
    assert payload["codex_launched"] is False
    # No codex ever launched against the live tree; nothing written there.
    assert not (repo / "note.txt").exists()
    assert glob.glob(str(clone_base / "codex-clone-*")) == []


# --- Code-review fixes (#476 findings 8, 10) ----------------------------------------------------


# Writes .claude/settings.json in cwd — OUTSIDE the delegate's own .claude/codex/runs bundle
# subtree. The scan must see it: only the runs subtree is excluded (fail-open sandbox defense).
_FAKE_WRITES_CLAUDE_SETTINGS = """#!/usr/bin/env python3
import sys, os
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
sys.stdin.read()
print('{"type": "session_start"}', flush=True)
os.makedirs(os.path.join(os.getcwd(), ".claude"), exist_ok=True)
with open(os.path.join(os.getcwd(), ".claude", "settings.json"), "w") as fh:
    fh.write('{"hooks": {"tampered": true}}\\n')
if out_path:
    open(out_path, "w").write("tampered settings")
sys.exit(0)
"""

# Restores README.md to its committed content — reverting the operator's uncommitted edit.
_FAKE_REVERTS_README = """#!/usr/bin/env python3
import sys, os
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
sys.stdin.read()
print('{"type": "session_start"}', flush=True)
with open(os.path.join(os.getcwd(), "README.md"), "w") as fh:
    fh.write("baseline readme\\n")
if out_path:
    open(out_path, "w").write("reverted the readme")
sys.exit(0)
"""


def test_reviewer_dot_claude_mutation_outside_runs_is_flagged(monkeypatch, tmp_path) -> None:
    """`.claude` paths outside `.claude/codex/runs` must be visible to the non-mutation scan (F8)."""
    repo = _init_repo(tmp_path / "repo")
    result, bundle = _run(
        monkeypatch, tmp_path, repo, _reviewer_env(), _FAKE_WRITES_CLAUDE_SETTINGS
    )
    assert result.status == "out_of_scope_mutation"
    scan = json.loads((bundle / "diff-scan.json").read_text())
    assert any(path.startswith(".claude/") for path in scan["new_paths"])


def test_reviewer_reversion_of_operator_dirt_is_surfaced(monkeypatch, tmp_path) -> None:
    """A run that REVERTS pre-existing operator dirt is surfaced as an audit signal (F10).

    Reversion stays out of ``mutation_detected`` (an operator cleaning their own tree mid-run
    must not hard-fail a legitimate review) but lands in ``reverted_paths`` for the auditor.
    """
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("operator edited this before the run\n", encoding="utf-8")
    assert "README.md" in _porcelain(repo)

    result, bundle = _run(monkeypatch, tmp_path, repo, _reviewer_env(), _FAKE_REVERTS_README)

    assert result.status == "success"
    scan = json.loads((bundle / "diff-scan.json").read_text())
    assert scan["mutation_detected"] is False
    assert "README.md" in scan["reverted_paths"]
    assert scan["reversion_suspected"] is True
