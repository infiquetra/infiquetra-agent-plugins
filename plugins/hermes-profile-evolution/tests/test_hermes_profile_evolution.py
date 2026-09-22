"""Contract tests for the Hermes profile-evolution request script and Claude hook.

Carried from infiquetra-claude-plugins ``tests/test_hermes_profile_evolution.py``
at acc99fe7. The request script stays at ``scripts/``. The hook, the command,
and ``hooks.json`` live under ``com.infiquetra.claude/``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import shlex
from pathlib import Path
from subprocess import CompletedProcess

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
MIMIR_ROOT = Path("/verified/team-mimir")
CANONICAL_README_REPORT = {
    "category": "ordinary_repository",
    "disposition": "normal_merge",
    "owner": "mimir-engineer",
    "paths": [
        {
            "category": "ordinary_repository",
            "disposition": "normal_merge",
            "owner": "mimir-engineer",
            "path": "README.md",
            "reason": "repository instruction or documentation surface",
        }
    ],
    "reason": "all paths classify as ordinary_repository",
    "schema_version": 1,
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


request = _load("profile_request", PACKAGE / "scripts/profile_request.py")
guard = _load(
    "profile_edit_guard",
    PACKAGE / "com.infiquetra.claude/hooks/profile_edit_guard.py",
)
HEALTHY = b'{"target":"brokkr","route_registered":true,"credential_available":true,"service_available":true}'


def _runner(calls: list[tuple[list[str], bytes | None]]):
    def fake_run(args, payload=None):
        calls.append((args, payload))
        if args[0] == "doctor":
            return CompletedProcess(args, 0, HEALTHY, b"")
        return CompletedProcess(args, 0, b"target reply\n", b"")

    return fake_run


def _report(disposition: str, category: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "disposition": disposition,
        "owner": "brokkr",
        "reason": "test response",
        "category": category,
        "paths": [
            {
                "path": "profiles/brokkr/SOUL.md",
                "disposition": disposition,
                "owner": "brokkr",
                "reason": "test response",
                "category": category,
            }
        ],
    }


def _write_classifier_fixture(root: Path, report: dict[str, object]) -> Path:
    """Create the minimum verified Team Mimir surface for the hook contract.

    Returns the resolved root. The hook passes that resolved path to the
    classifier, and a temporary directory can differ from the path pytest
    hands back when a parent is a symlink.
    """
    root = root.resolve()
    (root / "profiles").mkdir(parents=True)
    classifier = root / "scripts/classify_profile_change.py"
    classifier.parent.mkdir()
    classifier.write_text(
        "import json\n"
        "import sys\n"
        f"expected = {['--root', str(root), '--schema-version', '1', 'README.md']!r}\n"
        "if sys.argv[1:] != expected:\n"
        "    raise SystemExit(1)\n"
        f"print(json.dumps({report!r}))\n"
    )
    return root


def test_envelope_matches_closed_digest_and_keeps_shell_text_as_data() -> None:
    envelope = request.build_envelope("brokkr", "Keep $HOME; --not-an-option && literal")
    assert envelope["intent"] == "Keep $HOME; --not-an-option && literal"
    assert envelope["requester"]["verification"] == "claimed"
    assert (
        envelope["revision_digest"]
        == request.hashlib.sha256(
            request._canonical(
                {
                    key: envelope[key]
                    for key in (
                        "schema_version",
                        "target",
                        "requester",
                        "delegation_chain",
                        "intent",
                        "evidence_references",
                    )
                }
            )
        ).hexdigest()
    )


@pytest.mark.parametrize("target", ["default", "custom", "-alias", "x"])
def test_reserved_or_invalid_targets_are_rejected(target: str) -> None:
    with pytest.raises(request.RequestError):
        request.build_envelope(target, "A safe request")


@pytest.mark.parametrize(
    "references", [["docs/a.md", "docs/a.md"], ["../secret"], ["docs/transcript.md"], ["/absolute"]]
)
def test_invalid_evidence_references_are_rejected(references: list[str]) -> None:
    with pytest.raises(request.RequestError):
        request.build_envelope("brokkr", "A safe request", evidence=references)


def test_canonical_secret_screening_rejects_real_secret_but_allows_token_prose() -> None:
    assert (
        request.build_envelope("brokkr", "Discuss token budgets, not credentials")["target"]
        == "brokkr"
    )
    with pytest.raises(request.RequestError, match="secret-bearing"):
        request.build_envelope("brokkr", "api_key=abcdefghijklmnop")


@pytest.mark.parametrize("action", ["suggest", "reply", "resume"])
def test_all_mutating_actions_use_healthy_canonical_doctor_and_standard_input(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    calls: list[tuple[list[str], bytes | None]] = []
    monkeypatch.setattr(request, "_run", _runner(calls))
    envelope = request.build_envelope("brokkr", "Line one\n--literal; $(not-run)")
    assert (
        request.invoke(
            action, envelope, message="--message; $(not-run)" if action == "reply" else None
        )
        == "target reply\n"
    )
    assert calls[0] == (["doctor", "--target", "brokkr"], None)
    assert calls[1][0][0] == action
    payload = calls[1][1]
    assert payload is not None
    assert b"$(not-run)" in payload
    if action == "reply":
        assert calls[1][0] == ["reply", "--message", "--message; $(not-run)"]


def test_reply_rejects_whitespace_only_message_without_command_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bytes | None]] = []
    monkeypatch.setattr(request, "_run", _runner(calls))

    with pytest.raises(request.RequestError, match="reply is empty"):
        request.invoke(
            "reply", request.build_envelope("brokkr", "A safe request"), message=" \t\n "
        )

    assert calls == []


def test_reply_accepts_16384_characters_through_doctor_and_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bytes | None]] = []
    monkeypatch.setattr(request, "_run", _runner(calls))
    message = "x" * 16384

    assert request.invoke(
        "reply", request.build_envelope("brokkr", "A safe request"), message=message
    )
    assert calls[0] == (["doctor", "--target", "brokkr"], None)
    assert calls[1][0] == ["reply", "--message", message]


def test_reply_rejects_16385_characters_without_command_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bytes | None]] = []
    monkeypatch.setattr(request, "_run", _runner(calls))

    with pytest.raises(request.RequestError, match="reply is empty"):
        request.invoke(
            "reply", request.build_envelope("brokkr", "A safe request"), message="x" * 16385
        )

    assert calls == []


@pytest.mark.parametrize(
    "health",
    [
        b"{}",
        b'{"target":"brokkr","route_registered":true,"credential_available":false,"service_available":true}',
        b'{"status":"ok","schema_version":1}',
    ],
)
def test_doctor_incompatible_or_unready_fails_closed(
    monkeypatch: pytest.MonkeyPatch, health: bytes
) -> None:
    monkeypatch.setattr(
        request, "_run", lambda args, payload=None: CompletedProcess(args, 0, health, b"")
    )
    with pytest.raises(request.RequestError, match="unavailable or incompatible"):
        request.assert_healthy("brokkr")


def test_adapter_timeout_does_not_preempt_the_producer_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return CompletedProcess(args[0], 0, b"", b"")

    monkeypatch.setattr(request.subprocess, "run", fake_run)

    request._run(["doctor", "--target", "brokkr"])

    assert observed["timeout"] == 45
    assert request.COMMAND_TIMEOUT_SECONDS > 30


def test_read_only_status_and_census_keep_arguments_and_payload_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bytes | None]] = []
    monkeypatch.setattr(request, "_run", _runner(calls))
    assert (
        request.read_only(
            "status",
            ["--proposal-id", "proposal-12345678", "--revision", "a" * 64, "--target", "brokkr"],
        )
        == "target reply\n"
    )
    assert request.read_only("census", [], b'{"targets":[]}') == "target reply\n"
    assert calls[0][0][0] == "status" and calls[0][1] is None
    assert calls[1] == (["census"], b'{"targets":[]}')


def test_ssh_transport_quotes_every_dynamic_argument_and_rejects_option_aliases() -> None:
    command = request._ssh_command(
        "hermes-admin", ["reply", "--message", "--x; $(not-run)\nquoted ' text"]
    )
    assert command[:3] == ["ssh", "--", "hermes-admin"]
    assert shlex.split(command[3]) == [
        "exec",
        "hermes",
        "profile-request",
        "reply",
        "--message",
        "--x; $(not-run)\nquoted ' text",
    ]
    with pytest.raises(request.RequestError):
        request._ssh_command("-oProxyCommand=bad", ["doctor"])


def test_closed_envelope_rejects_extra_field_and_bad_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = request.build_envelope("brokkr", "A safe request")
    envelope["host"] = "untrusted"
    monkeypatch.setattr(
        request, "_run", lambda args, payload=None: CompletedProcess(args, 0, HEALTHY, b"")
    )
    with pytest.raises(request.RequestError, match="closed version-1"):
        request.invoke("suggest", envelope)


def test_main_routes_suggest_status_and_census(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], bytes | None]] = []
    monkeypatch.setattr(request, "_run", _runner(calls))
    assert request.main(["suggest", "brokkr", "A safe request"]) == 0
    assert (
        request.main(
            [
                "status",
                "--proposal-id",
                "proposal-12345678",
                "--revision",
                "a" * 64,
                "--target",
                "brokkr",
            ]
        )
        == 0
    )
    monkeypatch.setattr(request.sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"targets":[]}')))
    assert request.main(["census"]) == 0


@pytest.mark.parametrize(
    ("disposition", "category", "expected"),
    [
        ("normal_merge", "ordinary_repository", 0),
        ("target_request", "profile_owned_behavior", 2),
        ("governed_review", "unknown", 2),
    ],
)
def test_guard_allows_only_closed_ordinary_classifier_response(
    monkeypatch: pytest.MonkeyPatch, disposition: str, category: str, expected: int
) -> None:
    monkeypatch.setattr(guard, "resolve_team_mimir_root", lambda _cwd: MIMIR_ROOT)
    monkeypatch.setattr(guard, "classify", lambda *_: _report(disposition, category))
    monkeypatch.setattr(
        guard.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "Edit",
                    "cwd": str(MIMIR_ROOT),
                    "tool_input": {"file_path": str(MIMIR_ROOT / "profiles/brokkr/SOUL.md")},
                }
            )
        ),
    )
    assert guard.main() == expected


def test_guard_rejects_malformed_response_and_paths_outside_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "resolve_team_mimir_root", lambda _cwd: MIMIR_ROOT)
    monkeypatch.setattr(
        guard,
        "classify",
        lambda *_: guard._validate_report({"schema_version": 1, "disposition": "normal_merge"}),
    )
    monkeypatch.setattr(
        guard.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "Write",
                    "cwd": str(MIMIR_ROOT),
                    "tool_input": {"file_path": "README.md"},
                }
            )
        ),
    )
    assert guard.main() == 2
    with pytest.raises(RuntimeError, match="outside"):
        guard.normalize_path("/tmp/not-team-mimir", MIMIR_ROOT)


def test_guard_resolves_configured_root_and_runs_actual_classifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mimir_root = _write_classifier_fixture(tmp_path / "team-mimir", CANONICAL_README_REPORT)
    monkeypatch.setenv("HERMES_TEAM_MIMIR_ROOT", str(mimir_root))
    root = guard.resolve_team_mimir_root(str(PACKAGE / "tests"))
    report = guard.classify("README.md", root)
    assert report == CANONICAL_README_REPORT
    assert guard.normalize_path(str(mimir_root / "README.md"), root) == "README.md"


def test_installed_command_routes_all_actions_through_plugin_root() -> None:
    command = (PACKAGE / "com.infiquetra.claude/commands/hermes-profile-evolution.md").read_text()
    assert "argument-hint:" in command and "$ARGUMENTS" in command
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/profile_request.py" in command
    for action in ("suggest", "reply", "resume", "status", "census"):
        assert action in command


def test_manifest_hook_and_docs_preserve_truthful_boundary() -> None:
    hooks = json.loads((PACKAGE / "com.infiquetra.claude/hooks/hooks.json").read_text())
    assert hooks["hooks"]["PreToolUse"][0]["matcher"] == "Write|Edit|MultiEdit|NotebookEdit"
    command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "${CLAUDE_PLUGIN_ROOT}/com.infiquetra.claude/hooks/profile_edit_guard.py" in command
    assert "does not claim shell-command interception" in (PACKAGE / "README.md").read_text()
