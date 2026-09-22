"""The prompt-submission suggestion hook: local, advisory, and silent when unsure (issue #1029).

The load-bearing test here is the one that proves the hook makes **no network call**. Whether the
operator's live prompt text may be sent to a third-party vendor is an open operator decision
(issue #1038's exploration recommended deferring it), and this hook's whole claim is that the text
never leaves the machine. A test that asserted only the hook's output would not establish that.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "prompt_suggestion_hook.py"
HOOKS_DIR = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks"
COMMANDS_DIR = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "commands"

sys.path.insert(0, str(HOOKS_DIR))

import prompt_suggestion_hook as hook  # noqa: E402

COMMANDS = ["plan", "doc-review", "work", "code-review", "qa", "retro", "investigate"]


def _run_hook(payload: dict | bytes, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    raw = json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else payload
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=raw,
        cwd=str(cwd),
        capture_output=True,
    )


# --------------------------------------------------------------------------------------------
# It suggests, exactly once, when the operator's own words name one command.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("can you /plan issue 1029 for me", "plan"),
        ("run the qa checks", "qa"),
        ("time for a code-review of this branch", "code-review"),
        ("/investigate why the suite hangs", "investigate"),
    ],
)
def test_a_prompt_naming_one_command_suggests_it(text: str, expected: str) -> None:
    assert hook.suggest(text, COMMANDS) == expected


def test_a_prompt_naming_two_commands_is_silent() -> None:
    """Ambiguity is silence: guessing between two is how a hook earns being ignored."""
    assert hook.suggest("should I run plan or work next", COMMANDS) is None


@pytest.mark.parametrize(
    "text",
    [
        "what does this function do",
        "the deployment is failing again",
        "planning permission for the extension came through",
        "replan the sprint",
    ],
)
def test_an_unrelated_prompt_is_silent(text: str) -> None:
    assert hook.suggest(text, COMMANDS) is None


def test_an_empty_prompt_is_silent() -> None:
    assert hook.suggest("   ", COMMANDS) is None


def test_no_known_commands_is_silent() -> None:
    assert hook.suggest("run the plan", []) is None


# --------------------------------------------------------------------------------------------
# The run record's next step, used only when the operator asks to get on with it.
# --------------------------------------------------------------------------------------------


def test_the_recorded_next_step_answers_a_continuation_prompt() -> None:
    assert hook.suggest("what's next here", COMMANDS, "run /work on the plan") == "work"


def test_the_recorded_next_step_does_not_answer_an_unrelated_prompt() -> None:
    """A prompt about something else entirely is not answered with the run's next step."""
    assert hook.suggest("why is this test flaky", COMMANDS, "run /work on the plan") is None


def test_the_slash_form_wins_over_a_command_word_in_the_rest_of_the_step() -> None:
    """ "run /work on the plan" names `/work`; "plan" there is part of a noun, not a command."""
    assert hook.command_in_step("run /work on the plan", COMMANDS) == "work"


def test_an_ambiguous_recorded_next_step_is_silent() -> None:
    assert hook.suggest("what's next", COMMANDS, "run /work then /qa") is None


def test_an_empty_recorded_next_step_is_silent() -> None:
    assert hook.suggest("what's next", COMMANDS, "") is None


# --------------------------------------------------------------------------------------------
# The data-governance claim: nothing leaves the machine.
# --------------------------------------------------------------------------------------------


def test_the_hook_imports_no_network_client() -> None:
    """No `socket`, `http`, `urllib`, `requests`, or TypeSafe client anywhere in the module.

    A static read of the import graph rather than a runtime probe, because the claim is about what
    the hook *can* do, not only about what one code path happened to do.
    """
    tree = ast.parse(HOOK_SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "typesafe_client",
        "fleet_commons",
        "ssl",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
    }
    assert not (imported & forbidden), f"the hook imports {sorted(imported & forbidden)}"


def test_the_hook_opens_no_socket_when_it_runs(tmp_path: Path, monkeypatch) -> None:
    """Belt and braces: a live run with a socket constructor that fails the test if called."""
    import socket

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the suggestion hook opened a socket")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    assert hook.suggest("run the plan", COMMANDS, "run /work on the plan") == "plan"


def test_the_hook_writes_no_file(tmp_path: Path) -> None:
    """The operator's prompt text is read and discarded; nothing is logged."""
    before = set(tmp_path.rglob("*"))
    result = _run_hook({"prompt": "can you /plan issue 1029", "cwd": str(tmp_path)}, tmp_path)
    assert result.returncode == 0
    assert set(tmp_path.rglob("*")) == before


# --------------------------------------------------------------------------------------------
# It is advisory, and it never fails a turn.
# --------------------------------------------------------------------------------------------


def test_a_matching_prompt_emits_advisory_context(tmp_path: Path) -> None:
    result = _run_hook({"prompt": "can you /plan issue 1029", "cwd": str(tmp_path)}, tmp_path)
    assert result.returncode == 0
    payload = json.loads(result.stdout.decode("utf-8"))
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "/plan" in context
    assert "suggestion, not an instruction" in context
    # Nothing that would block or rewrite the prompt.
    assert "decision" not in payload
    assert "permissionDecision" not in json.dumps(payload)


def test_an_unrelated_prompt_emits_nothing(tmp_path: Path) -> None:
    result = _run_hook({"prompt": "what does this function do", "cwd": str(tmp_path)}, tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""


@pytest.mark.parametrize(
    "payload",
    [b"", b"not json", b"[]", b'{"cwd": "/tmp"}', b'{"prompt": 7}'],
    ids=["empty", "malformed", "not-an-object", "no-prompt", "prompt-not-a-string"],
)
def test_a_payload_the_hook_cannot_use_emits_nothing(tmp_path: Path, payload: bytes) -> None:
    result = _run_hook(payload, tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""


def test_the_command_list_comes_from_the_plugins_own_commands_directory() -> None:
    names = hook.known_commands(COMMANDS_DIR)
    assert "plan" in names
    assert "work" in names
    assert names == sorted(names)
