"""
AE6 tests for the journal-omission nudge hook (U8, R14).

Covers:
- feat/fix commit touching code with no journal entry -> nudge printed to stderr,
  exit 0 (non-blocking).
- feat/fix commit that INCLUDES a docs/engineering-journal/ file -> no nudge.
- docs-only commit (type != feat/fix) -> silent, exit 0.
- chore commit -> silent, exit 0.
- non-Bash tool -> pass-through, exit 0.
- non-commit Bash command -> pass-through, exit 0.
- Cross-repo safety: graceful when journal dir absent (no error, no nudge).
- Hook never writes any file.
- Hook script exists and is importable.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "journal_nudge_hook.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _judgment_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the model judgment OFF for every test in this file.

    Since issue 1036 the hook asks a model whenever the `feat`/`fix` floor did
    NOT fire, so a test that calls `main()` on a chore commit touching code
    would otherwise make a live request.  The widen-path tests below turn it
    back on and inject a fake; everything else is testing the floor.
    """
    monkeypatch.setenv("INFIQUETRA_TYPESAFE_JOURNAL_NUDGE", "off")


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    """Run the hook script with the given JSON payload on stdin."""
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return result


def _bash_payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def _load_hook_module():
    """Import the hook module dynamically (no package install needed)."""
    spec = importlib.util.spec_from_file_location("journal_nudge_hook", HOOK_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_main_patched(
    mod, payload: dict, *, files: list[str] | None, journal_exists: bool
) -> tuple[int, str]:
    """
    Call mod.main() with stdin from payload and captured stderr.

    Returns (exit_code, stderr_text).
    """
    old_stdin = sys.stdin
    old_stderr = sys.stderr
    captured = io.StringIO()
    sys.stdin = io.StringIO(json.dumps(payload))
    sys.stderr = captured

    exit_code: int = 0
    patches = [patch.object(mod, "_journal_dir_exists", return_value=journal_exists)]
    if files is not None:
        patches.append(patch.object(mod, "_git_show_files", return_value=files))

    try:
        with patches[0]:
            if len(patches) > 1:
                with patches[1]:
                    mod.main()
            else:
                mod.main()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 0
    finally:
        sys.stdin = old_stdin
        sys.stderr = old_stderr

    return exit_code, captured.getvalue()


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------


def test_hook_script_exists() -> None:
    """The nudge hook script must exist at the expected path."""
    assert HOOK_SCRIPT.exists(), f"Missing hook script: {HOOK_SCRIPT}"


def test_hooks_json_registers_post_tool_use() -> None:
    """hooks.json must have a PostToolUse section wiring journal_nudge_hook.py."""
    hooks_json = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "hooks.json"
    data = json.loads(hooks_json.read_text())
    assert "PostToolUse" in data["hooks"], "hooks.json must have a PostToolUse section"
    entries = data["hooks"]["PostToolUse"]
    commands = [
        h["command"]
        for entry in entries
        for h in entry.get("hooks", [])
        if h.get("type") == "command"
    ]
    assert any("journal_nudge_hook" in cmd for cmd in commands), (
        "PostToolUse must reference journal_nudge_hook.py"
    )


def test_hooks_json_still_valid_json() -> None:
    """hooks.json (now with both hooks) must still parse as valid JSON."""
    hooks_json = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "hooks.json"
    data = json.loads(hooks_json.read_text())
    assert "hooks" in data
    assert "PreToolUse" in data["hooks"]
    assert "PostToolUse" in data["hooks"]


# ---------------------------------------------------------------------------
# Unit tests via module import (fast, no subprocess git calls)
# ---------------------------------------------------------------------------


def test_is_git_commit_command_detects_commit() -> None:
    mod = _load_hook_module()
    assert mod._is_git_commit_command('git commit -m "feat: add stuff"')
    assert mod._is_git_commit_command('git -C /some/path commit -m "fix: bug"')
    assert mod._is_git_commit_command("git commit --allow-empty -m 'chore: bump'")


def test_is_git_commit_command_rejects_non_commit() -> None:
    mod = _load_hook_module()
    assert not mod._is_git_commit_command("git status")
    assert not mod._is_git_commit_command("git push origin main")
    assert not mod._is_git_commit_command("git log --oneline -5")
    assert not mod._is_git_commit_command("echo hello")
    assert not mod._is_git_commit_command("")


def test_extract_commit_message_double_quote() -> None:
    mod = _load_hook_module()
    assert mod._extract_commit_message('git commit -m "feat: add hook"') == "feat: add hook"


def test_extract_commit_message_single_quote() -> None:
    mod = _load_hook_module()
    assert mod._extract_commit_message("git commit -m 'fix(scope): bug'") == "fix(scope): bug"


def test_extract_commit_message_unquoted() -> None:
    mod = _load_hook_module()
    msg = mod._extract_commit_message("git commit -m chore")
    assert msg == "chore"


def test_extract_commit_message_not_found() -> None:
    mod = _load_hook_module()
    assert mod._extract_commit_message("git commit") == ""


def test_feat_fix_re_matches_feat_and_fix() -> None:
    mod = _load_hook_module()
    assert mod._FEAT_FIX_RE.match("feat: add hook")
    assert mod._FEAT_FIX_RE.match("fix: correct bug")
    assert mod._FEAT_FIX_RE.match("feat(scope): add thing")
    assert mod._FEAT_FIX_RE.match("Fix: case-insensitive")


def test_feat_fix_re_ignores_other_types() -> None:
    mod = _load_hook_module()
    assert not mod._FEAT_FIX_RE.match("chore: bump")
    assert not mod._FEAT_FIX_RE.match("docs: update")
    assert not mod._FEAT_FIX_RE.match("refactor: clean up")
    assert not mod._FEAT_FIX_RE.match("test: add unit tests")


def test_has_code_files_detects_python() -> None:
    mod = _load_hook_module()
    assert mod._has_code_files(["plugins/saga/scripts/saga.py"])
    assert mod._has_code_files(["src/main.ts", "README.md"])


def test_has_code_files_false_for_markdown_only() -> None:
    mod = _load_hook_module()
    assert not mod._has_code_files(["docs/plan.md", "README.md"])
    assert not mod._has_code_files(["docs/engineering-journal/LEARNINGS.md"])


def test_has_journal_entry_true() -> None:
    mod = _load_hook_module()
    files = [
        "plugins/saga/scripts/saga.py",
        "docs/engineering-journal/LEARNINGS.md",
    ]
    assert mod._has_journal_entry(files)


def test_has_journal_entry_false() -> None:
    mod = _load_hook_module()
    files = [
        "plugins/saga/scripts/saga.py",
        "tests/test_saga_saga.py",
    ]
    assert not mod._has_journal_entry(files)


def test_parse_git_dash_c_extracts_path() -> None:
    mod = _load_hook_module()
    cmd = "git -C /some/repo commit -m 'fix: bug'"
    assert mod._parse_git_dash_c(cmd) == "/some/repo"


def test_parse_git_dash_c_returns_none_when_absent() -> None:
    mod = _load_hook_module()
    assert mod._parse_git_dash_c('git commit -m "feat: thing"') is None


# ---------------------------------------------------------------------------
# AE6: Integration — non-blocking, non-writing
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """
    Set up a minimal fake git repo with docs/engineering-journal/ present
    and a Python file committed.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create the journal dir so the cross-repo guard passes.
    (repo / "docs" / "engineering-journal").mkdir(parents=True)
    (repo / "docs" / "engineering-journal" / ".gitkeep").write_text("")

    # Create a Python file.
    (repo / "main.py").write_text("def main(): pass\n")

    # Initial commit (so HEAD exists and git show works).
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initial"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


def test_ae6_code_feat_commit_no_journal_produces_nudge(fake_repo: Path) -> None:
    """AE6 core: feat commit with a code file but no journal -> nudge in stderr, exit 0."""
    mod = _load_hook_module()
    command = f'git -C {fake_repo} commit -m "feat: improve main"'
    payload = _bash_payload(command)

    exit_code, stderr = _run_main_patched(mod, payload, files=["main.py"], journal_exists=True)

    assert exit_code == 0, f"Expected exit 0 (non-blocking); got {exit_code}"
    assert "journal-nudge" in stderr, f"Expected nudge; got: {stderr!r}"


def test_ae6_code_feat_commit_with_journal_no_nudge() -> None:
    """AE6: feat commit that includes a journal file -> no nudge."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "feat: add hook"')

    exit_code, stderr = _run_main_patched(
        mod,
        payload,
        files=["main.py", "docs/engineering-journal/LEARNINGS.md"],
        journal_exists=True,
    )

    assert exit_code == 0
    assert "journal-nudge" not in stderr


def test_ae6_docs_only_commit_is_silent() -> None:
    """AE6: docs-only commit (type = docs, no code) -> silent."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "docs: update README"')

    exit_code, stderr = _run_main_patched(mod, payload, files=None, journal_exists=True)

    assert exit_code == 0
    assert stderr == ""


def test_ae6_chore_commit_is_silent() -> None:
    """AE6: chore commit -> silent regardless of files."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "chore: bump versions"')

    exit_code, stderr = _run_main_patched(
        mod, payload, files=["pyproject.toml", "saga.py"], journal_exists=True
    )

    assert exit_code == 0
    assert stderr == ""


def test_ae6_fix_commit_no_journal_produces_nudge() -> None:
    """AE6: fix commit with code, no journal -> nudge (same as feat)."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "fix(scope): correct off-by-one"')

    exit_code, stderr = _run_main_patched(
        mod, payload, files=["plugins/saga/scripts/saga.py"], journal_exists=True
    )

    assert exit_code == 0
    assert "journal-nudge" in stderr


def test_ae6_code_only_no_journal_still_exits_0() -> None:
    """AE6: hook is NON-blocking -- even when nudge fires, exit code is 0."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "feat: add stuff"')

    exit_code, _ = _run_main_patched(mod, payload, files=["src/main.py"], journal_exists=True)

    assert exit_code == 0, "Hook must never block (exit 0 always)"


# ---------------------------------------------------------------------------
# Cross-repo safety: journal dir absent -> silent, no error
# ---------------------------------------------------------------------------


def test_cross_repo_no_journal_dir_is_silent() -> None:
    """When docs/engineering-journal/ is absent, degrade silently (exit 0, no output)."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "feat: some feature"')

    exit_code, stderr = _run_main_patched(mod, payload, files=["main.py"], journal_exists=False)

    assert exit_code == 0
    assert stderr == "", "Must be silent when journal dir is absent (cross-repo safety)"


def test_cross_repo_git_unavailable_is_silent() -> None:
    """When git show fails (not a repo, etc.), degrade silently."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "feat: thing"')

    # files=[] simulates _git_show_files returning empty (failure case)
    exit_code, stderr = _run_main_patched(mod, payload, files=[], journal_exists=True)

    assert exit_code == 0
    assert stderr == ""


# ---------------------------------------------------------------------------
# Non-Bash tool and non-commit command -> pass-through
# ---------------------------------------------------------------------------


def test_non_bash_tool_passes_through() -> None:
    """A non-Bash tool -> exit 0, no output."""
    result = _run_hook(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": "foo.md"},
        }
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_non_commit_bash_command_passes_through() -> None:
    """A Bash command that is not a git commit -> exit 0, no output."""
    result = _run_hook(_bash_payload("git status"))
    assert result.returncode == 0
    assert result.stderr == ""


def test_non_git_bash_command_passes_through() -> None:
    """A non-git Bash command -> exit 0, no output."""
    result = _run_hook(_bash_payload("echo hello"))
    assert result.returncode == 0
    assert result.stderr == ""


# ---------------------------------------------------------------------------
# Hook never writes any file (R14 property)
# ---------------------------------------------------------------------------


def test_hook_does_not_write_any_file(tmp_path: Path) -> None:
    """The nudge hook must not create or modify any file."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "feat: something"')

    files_before = set(tmp_path.rglob("*"))

    _run_main_patched(mod, payload, files=["main.py"], journal_exists=True)

    files_after = set(tmp_path.rglob("*"))
    assert files_before == files_after, "Hook must not write any files"


# ---------------------------------------------------------------------------
# Subprocess integration: raw hook invocation
# ---------------------------------------------------------------------------


def test_hook_exits_0_on_malformed_input() -> None:
    """Malformed JSON input -> exit 0, no crash."""
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input="not json at all {{{",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Expected exit 0 on bad JSON; got {result.returncode}"


def test_hook_exits_0_on_empty_input() -> None:
    """Empty stdin -> exit 0."""
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input="",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# The widen-only union (issue 1036)
# ---------------------------------------------------------------------------


def _widen_returning(union: bool, calls: list | None = None):
    """A fake `widen` that runs no request and returns a fixed union."""

    class _Judgment:
        def __init__(self, value: bool) -> None:
            self.union = value
            self.regex = False
            self.probability = 0.9 if value else 0.1
            self.source = "model" if value else "none"

    def _widen(state, verb, floors, **kwargs):
        if calls is not None:
            calls.append({"state": state, "verb": verb, "floors": floors, "options": kwargs})
        return type("_Result", (), {"judgments": {"earns_entry": _Judgment(union)}})()

    return _widen


def _must_not_run(*_args, **_kwargs):
    raise AssertionError("the model must not be asked here")


def test_a_refactor_commit_the_model_judges_worthy_now_nudges(monkeypatch) -> None:
    """The widen: a message the feat/fix floor passed in silence can now nudge."""
    monkeypatch.delenv("INFIQUETRA_TYPESAFE_JOURNAL_NUDGE", raising=False)
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "refactor: collapse the retry ladder"')

    with (
        patch.object(mod, "_commit_message", return_value="refactor: collapse the retry ladder"),
        patch.object(mod, "_earned_a_journal_entry", return_value=True),
    ):
        exit_code, stderr = _run_main_patched(mod, payload, files=["main.py"], journal_exists=True)

    assert exit_code == 0
    assert "journal-nudge" in stderr
    assert "non-obvious mechanism" in stderr


def test_a_refactor_commit_the_model_judges_ordinary_stays_silent(monkeypatch) -> None:
    monkeypatch.delenv("INFIQUETRA_TYPESAFE_JOURNAL_NUDGE", raising=False)
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "refactor: rename a variable"')

    with (
        patch.object(mod, "_commit_message", return_value="refactor: rename a variable"),
        patch.object(mod, "_earned_a_journal_entry", return_value=False),
    ):
        exit_code, stderr = _run_main_patched(mod, payload, files=["main.py"], journal_exists=True)

    assert exit_code == 0
    assert stderr == ""


def test_a_feat_commit_never_asks_the_model(monkeypatch) -> None:
    """The floor already nudges, so asking could only agree and cost a request."""
    monkeypatch.delenv("INFIQUETRA_TYPESAFE_JOURNAL_NUDGE", raising=False)
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "feat: add the thing"')

    with patch.object(mod, "_earned_a_journal_entry", _must_not_run):
        exit_code, stderr = _run_main_patched(mod, payload, files=["main.py"], journal_exists=True)

    assert exit_code == 0
    assert "journal-nudge" in stderr
    assert "feat/fix commit touches code" in stderr


def test_the_off_switch_makes_no_call_at_all() -> None:
    """The autouse fixture sets the switch off; assert nothing is asked."""
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "refactor: collapse the retry ladder"')

    with patch.object(mod, "_earned_a_journal_entry", _must_not_run):
        exit_code, stderr = _run_main_patched(mod, payload, files=["main.py"], journal_exists=True)

    assert exit_code == 0
    assert stderr == ""


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "no"])
def test_every_documented_off_value_disables_the_judgment(value: str) -> None:
    mod = _load_hook_module()
    assert mod._judgment_enabled(getenv=lambda _name: value) is False


@pytest.mark.parametrize("value", [None, "", "on", "1", "anything else"])
def test_anything_else_leaves_the_judgment_on(value: str | None) -> None:
    mod = _load_hook_module()
    assert mod._judgment_enabled(getenv=lambda _name: value) is True


def test_a_docs_only_commit_still_never_asks(monkeypatch) -> None:
    """The code-file precondition is deliberately not widened."""
    monkeypatch.delenv("INFIQUETRA_TYPESAFE_JOURNAL_NUDGE", raising=False)
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "docs: rewrite the README"')

    with patch.object(mod, "_earned_a_journal_entry", _must_not_run):
        exit_code, stderr = _run_main_patched(
            mod, payload, files=["README.md"], journal_exists=True
        )

    assert exit_code == 0
    assert stderr == ""


def test_a_commit_carrying_a_journal_entry_never_asks(monkeypatch) -> None:
    monkeypatch.delenv("INFIQUETRA_TYPESAFE_JOURNAL_NUDGE", raising=False)
    mod = _load_hook_module()
    payload = _bash_payload('git commit -m "refactor: collapse the retry ladder"')

    with patch.object(mod, "_earned_a_journal_entry", _must_not_run):
        exit_code, stderr = _run_main_patched(
            mod,
            payload,
            files=["main.py", "docs/engineering-journal/LEARNINGS.md"],
            journal_exists=True,
        )

    assert exit_code == 0
    assert stderr == ""


def test_the_judgment_sends_only_the_message_and_the_file_list() -> None:
    """The data rule: a commit message and paths, never a transcript or a diff."""
    mod = _load_hook_module()
    calls: list = []

    assert (
        mod._earned_a_journal_entry(
            "refactor: collapse the retry ladder",
            ["plugins/saga/scripts/retry.py"],
            widen=_widen_returning(True, calls),
        )
        is True
    )

    assert len(calls) == 1
    assert calls[0]["state"] == {
        "message": "refactor: collapse the retry ladder",
        "files": ["plugins/saga/scripts/retry.py"],
    }
    assert calls[0]["verb"] == "journal-nudge"
    assert calls[0]["floors"] == {"earns_entry": False}


def test_the_judgment_is_bounded_to_one_short_attempt() -> None:
    mod = _load_hook_module()
    calls: list = []

    mod._earned_a_journal_entry("refactor: x", ["a.py"], widen=_widen_returning(False, calls))

    options = calls[0]["options"]
    assert options["max_attempts"] == 1
    assert options["timeout"] == mod._JUDGMENT_TIMEOUT
    assert options["total_deadline"] == mod._JUDGMENT_DEADLINE
    assert mod._JUDGMENT_DEADLINE <= 3.0


def test_a_raising_client_is_silent_and_judges_nothing() -> None:
    mod = _load_hook_module()

    def _raises(*_args, **_kwargs):
        raise RuntimeError("the vendor is unreachable")

    assert mod._earned_a_journal_entry("refactor: x", ["a.py"], widen=_raises) is False


def test_the_model_reads_the_real_commit_message_not_the_parsed_one(monkeypatch) -> None:
    """A here-document commit parses to an empty message; HEAD still has one."""
    monkeypatch.delenv("INFIQUETRA_TYPESAFE_JOURNAL_NUDGE", raising=False)
    mod = _load_hook_module()
    seen: list = []

    def _record(message, files, **kwargs):
        seen.append(message)
        return False

    payload = _bash_payload("git commit -F - <<EOF\nperf: cache the lookup\nEOF")
    assert mod._extract_commit_message(payload["tool_input"]["command"]) == ""

    with (
        patch.object(mod, "_commit_message", return_value="perf: cache the lookup"),
        patch.object(mod, "_earned_a_journal_entry", _record),
    ):
        exit_code, _stderr = _run_main_patched(mod, payload, files=["main.py"], journal_exists=True)

    assert exit_code == 0
    assert seen == ["perf: cache the lookup"]
