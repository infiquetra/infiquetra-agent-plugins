"""Contract tests for the codex.delegation.v1 envelope (plugins/codex/scripts/codex_delegate.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codex_delegate.py"


def _load_module():
    # The wrapper inserts scripts/_bundled on import. Do not also insert
    # scripts/: that insert existed so fleet_commons_shim could be imported,
    # and this package does not carry the shim.
    spec = importlib.util.spec_from_file_location("codex_delegate_under_test", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


codex_delegate = _load_module()


def _base_coder_payload(**overrides):
    payload = {
        "schema": codex_delegate.SCHEMA,
        "role": "coder",
        "mode": "task",
        "task": "Fix the bug in the parser.",
        "write_set": ["plugins/example/file.py"],
    }
    payload.update(overrides)
    return payload


def _base_reviewer_payload(**overrides):
    payload = {
        "schema": codex_delegate.SCHEMA,
        "role": "reviewer",
        "task": "Review the diff for correctness.",
    }
    payload.update(overrides)
    return payload


def _receipt_kwargs(content="codex message"):
    return {
        "run_id": "test-run",
        "external_tokens": 11,
        "output_attestation": codex_delegate._output_attestation.emit_attestation(
            artifact="last-message.txt",
            content=content,
        ),
    }


# --- Valid round-trips -----------------------------------------------------------------------


def test_valid_coder_envelope_round_trips() -> None:
    envelope = codex_delegate.Envelope.from_mapping(_base_coder_payload())
    assert envelope.role == "coder"
    assert envelope.mode == "task"
    assert envelope.write_set == ["plugins/example/file.py"]
    assert envelope.apply_policy == "preserve-patch"
    payload = envelope.to_jsonable()
    assert payload["schema"] == codex_delegate.SCHEMA
    round_tripped = codex_delegate.Envelope.from_mapping(payload)
    assert round_tripped == envelope


def test_valid_reviewer_envelope_defaults() -> None:
    envelope = codex_delegate.Envelope.from_mapping(_base_reviewer_payload())
    assert envelope.role == "reviewer"
    assert envelope.mode == "read-only"
    assert envelope.review_lens == "adversarial"
    assert envelope.write_set == []


def test_reviewer_lens_may_be_overridden() -> None:
    envelope = codex_delegate.Envelope.from_mapping(
        _base_reviewer_payload(review_lens="security-ops")
    )
    assert envelope.review_lens == "security-ops"


def test_model_and_effort_are_optional() -> None:
    envelope = codex_delegate.Envelope.from_mapping(_base_reviewer_payload())
    assert envelope.model is None
    assert envelope.effort is None
    envelope_with = codex_delegate.Envelope.from_mapping(
        _base_reviewer_payload(model="gpt-5", effort="high")
    )
    assert envelope_with.model == "gpt-5"
    assert envelope_with.effort == "high"


# --- Invalid envelopes -------------------------------------------------------------------------


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(_base_coder_payload(role="architect"))


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(_base_coder_payload(mode="auto-if-clean"))


def test_unknown_schema_is_rejected() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(_base_coder_payload(schema="agy.delegation.v1"))


def test_reviewer_with_write_set_is_rejected() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(
            _base_reviewer_payload(write_set=["plugins/example/file.py"])
        )


def test_task_mode_requires_write_set() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(_base_coder_payload(write_set=[]))


def test_empty_task_is_rejected() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(_base_coder_payload(task="   "))


def test_missing_role_is_rejected() -> None:
    payload = _base_coder_payload()
    del payload["role"]
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(payload)


def test_unknown_review_lens_is_rejected() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(_base_reviewer_payload(review_lens="vibes"))


def test_unknown_apply_policy_is_rejected() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(_base_coder_payload(apply_policy="apply-if-clean"))


def test_no_output_seconds_must_not_exceed_timeout() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(
            _base_coder_payload(timeout_seconds=10, no_output_seconds=20)
        )


def test_non_boolean_provenance_required_is_rejected() -> None:
    with pytest.raises(codex_delegate.EnvelopeError):
        codex_delegate.Envelope.from_mapping(_base_coder_payload(provenance_required="yes"))


# --- Receipt emission seam (R8/KTD6) -----------------------------------------------------------


def test_supervised_receipt_is_none_when_codex_did_not_launch() -> None:
    envelope = codex_delegate.Envelope.from_mapping(_base_reviewer_payload())
    now = datetime.now(UTC)
    run_result = codex_delegate.SupervisedRunResult(
        status="error",
        codex_launched=False,
        resolved_codex=None,
        argv=[],
        process_id=None,
        return_code=None,
        started_at=now,
        ended_at=now,
        stdout_bytes=0,
        stderr_bytes=0,
        error="codex binary not found",
    )
    assert (
        codex_delegate._supervised_receipt(run_result, envelope=envelope, **_receipt_kwargs())
        is None
    )


def test_supervised_receipt_is_emitted_when_codex_launched() -> None:
    envelope = codex_delegate.Envelope.from_mapping(_base_reviewer_payload(model="gpt-5"))
    started = datetime.now(UTC)
    ended = started
    run_result = codex_delegate.SupervisedRunResult(
        status="success",
        codex_launched=True,
        resolved_codex="/usr/local/bin/codex",
        argv=["codex", "exec", "--json"],
        process_id=4242,
        return_code=0,
        started_at=started,
        ended_at=ended,
        stdout_bytes=128,
        stderr_bytes=0,
    )
    receipt = codex_delegate._supervised_receipt(
        run_result,
        envelope=envelope,
        **_receipt_kwargs(),
    )
    assert receipt is not None
    assert receipt["schema"] == "bridge_receipt.v1"
    assert receipt["engine_id"] == "codex"
    assert receipt["variant"] == "gpt-5"
    assert receipt["transport"] == "cli"
    assert receipt["runner"]["pid"] == 4242
    assert receipt["runner"]["exit_code"] == 0

    bridge_receipt = codex_delegate._bridge_receipt
    assert bridge_receipt.validate_receipt(receipt) == []


def test_supervised_receipt_uses_canonical_model_effort_variant() -> None:
    envelope = codex_delegate.Envelope.from_mapping(
        _base_reviewer_payload(model="gpt-5.6-sol", effort="xhigh")
    )
    now = datetime.now(UTC)
    run_result = codex_delegate.SupervisedRunResult(
        status="success",
        codex_launched=True,
        resolved_codex="/usr/local/bin/codex",
        argv=["codex", "exec", "--json"],
        process_id=4242,
        return_code=0,
        started_at=now,
        ended_at=now,
        stdout_bytes=128,
        stderr_bytes=0,
    )

    receipt = codex_delegate._supervised_receipt(
        run_result,
        envelope=envelope,
        **_receipt_kwargs(),
    )

    assert receipt is not None
    assert receipt["variant"] == "gpt-5.6-sol-xhigh"


def test_validate_only_cli_prints_envelope_and_exits_zero(capsys, tmp_path) -> None:
    exit_code = codex_delegate.main(
        [
            "--role",
            "reviewer",
            "--task",
            "Review the diff.",
            "--validate-only",
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "validate-run",
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert '"schema": "codex.delegation.v1"' in captured.out
    bundle = tmp_path / ".claude" / "codex" / "runs" / "validate-run"
    assert (bundle / "envelope.json").exists()
    assert (bundle / "prompt.txt").exists()
    assert (bundle / "command.json").exists()
    assert (bundle / "result.json").exists()
    assert (bundle / "projection.md").exists()
    # validate-only must NOT launch codex (no transcript / receipt).
    assert not (bundle / "transcript.jsonl").exists()
    assert not (bundle / "bridge-receipt.json").exists()
    command = json.loads((bundle / "command.json").read_text())
    assert command["validation_only"] is True
    assert command["codex_launch_planned"] is False


def test_cli_rejects_invalid_envelope_with_nonzero_exit(capsys) -> None:
    exit_code = codex_delegate.main(
        [
            "--role",
            "reviewer",
            "--mode",
            "task",
            "--task",
            "Review the diff.",
            "--validate-only",
        ]
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "envelope error" in captured.err


# --- U2: supervised synchronous runner + evidence bundle ---------------------------------------


def _write_fake_codex_bin(tmp_path: Path, body: str) -> Path:
    """Write an executable fake ``codex`` that mimics the KTD3 invocation shape."""
    bin_path = tmp_path / "fake-codex.py"
    bin_path.write_text(body, encoding="utf-8")
    bin_path.chmod(0o755)
    return bin_path


# A cooperative fake codex: parses ``-o <path>``, echoes stdin into the transcript to prove
# delivery, emits JSONL (including a usage event), writes the last message, and exits 0.
_FAKE_CODEX_SUCCESS = """#!/usr/bin/env python3
import json, sys
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
piped = sys.stdin.read()
print(json.dumps({"type": "session_start", "argv": argv}))
print(json.dumps({"type": "stdin_echo", "stdin": piped}))
print(json.dumps({"type": "token_count", "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}}))
sys.stdout.flush()
if out_path:
    with open(out_path, "w") as fh:
        fh.write("final agent message")
sys.exit(0)
"""

_FAKE_CODEX_REPORTS_CMUX_BYPASS = """#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
sys.stdin.read()
print(json.dumps({"type": "cmux_bypass", "value": os.environ.get("CMUX_AGENT_BYPASS")}))
sys.stdout.flush()
if out_path:
    with open(out_path, "w") as fh:
        fh.write("final agent message")
sys.exit(0)
"""

# Emits malformed lines interleaved with valid JSONL; still exits 0.
_FAKE_CODEX_MALFORMED = """#!/usr/bin/env python3
import json, sys
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
sys.stdin.read()
print(json.dumps({"type": "session_start"}))
print("this is not json at all {{{")
print(json.dumps({"type": "token_count", "input_tokens": 3, "output_tokens": 4}))
print("<<< another malformed line >>>")
sys.stdout.flush()
if out_path:
    open(out_path, "w").write("done")
sys.exit(0)
"""

# Sleeps far past any small timeout and writes a marker file, so the test can prove the tree
# was killed (the marker's completion sentinel never appears).
_FAKE_CODEX_SLEEP = """#!/usr/bin/env python3
import sys, time
sys.stdin.read()
print('{"type": "session_start"}', flush=True)
time.sleep(120)
print('{"type": "done"}', flush=True)
sys.exit(0)
"""


def _run_bundle(tmp_path, envelope_kwargs, fake_body, *, timeout_seconds=None):
    import subprocess as _subprocess

    payload = {
        "schema": codex_delegate.SCHEMA,
        "role": "reviewer",
        "task": "Review the diff.",
    }
    payload.update(envelope_kwargs)
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
        payload["no_output_seconds"] = timeout_seconds
    envelope = codex_delegate.Envelope.from_mapping(payload)
    bin_path = _write_fake_codex_bin(tmp_path, fake_body)
    # codex_bin is invoked as a single argv[0]; wrap python + script in a shim script.
    shim = tmp_path / "codex-shim"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bin_path}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    _ = _subprocess  # keep import local
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    result = codex_delegate.create_supervised_bundle(
        envelope,
        repo_root=repo_root,
        run_id="run-under-test",
        codex_bin=str(shim),
    )
    return result, repo_root / ".claude" / "codex" / "runs" / "run-under-test"


def test_supervised_success_writes_full_bundle_and_receipt(tmp_path) -> None:
    result, bundle = _run_bundle(tmp_path, {"model": "gpt-5"}, _FAKE_CODEX_SUCCESS)
    assert result.status == "success"
    for name in (
        "envelope.json",
        "prompt.txt",
        "command.json",
        "transcript.jsonl",
        "last-message.txt",
        "result.json",
        "projection.md",
    ):
        assert (bundle / name).exists(), name

    # stdin was delivered and closed (fake echoes it back into the transcript).
    transcript = (bundle / "transcript.jsonl").read_text()
    assert "stdin_echo" in transcript
    assert "# codex delegation packet" in transcript  # the prompt reached codex via stdin

    assert (bundle / "last-message.txt").read_text() == "final agent message"

    result_payload = json.loads((bundle / "result.json").read_text())
    assert result_payload["codex_launched"] is True
    assert result_payload["return_code"] == 0
    assert result_payload["token_usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert result_payload["receipt_emitted"] is True

    # Receipt emitted iff launched, and it validates.
    receipt = json.loads((bundle / "bridge-receipt.json").read_text())
    assert receipt["schema"] == "bridge_receipt.v1"
    assert receipt["engine_id"] == "codex"
    assert codex_delegate._bridge_receipt.validate_receipt(receipt) == []


def test_supervised_codex_forces_cmux_bypass(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CMUX_AGENT_BYPASS", "0")

    result, bundle = _run_bundle(tmp_path, {}, _FAKE_CODEX_REPORTS_CMUX_BYPASS)

    assert result.status == "success"
    transcript = (bundle / "transcript.jsonl").read_text(encoding="utf-8")
    assert '"type": "cmux_bypass"' in transcript
    assert '"value": "1"' in transcript


def test_supervised_launch_failure_is_fail_loud_with_no_receipt(tmp_path) -> None:
    envelope = codex_delegate.Envelope.from_mapping(
        {"schema": codex_delegate.SCHEMA, "role": "reviewer", "task": "Review."}
    )
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    result = codex_delegate.create_supervised_bundle(
        envelope,
        repo_root=repo_root,
        run_id="launch-fail",
        codex_bin=str(tmp_path / "does-not-exist-codex"),
    )
    bundle = repo_root / ".claude" / "codex" / "runs" / "launch-fail"
    assert result.status == "error"
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["codex_launched"] is False
    assert payload["receipt_emitted"] is False
    assert payload["status"] != "running"
    # No receipt when codex never launched (R8).
    assert not (bundle / "bridge-receipt.json").exists()
    # result.json still validates as a terminal bundle.
    assert payload["schema"] == "codex.result.v1"


def test_supervised_timeout_kills_tree_and_records_terminal_status(tmp_path) -> None:
    result, bundle = _run_bundle(tmp_path, {}, _FAKE_CODEX_SLEEP, timeout_seconds=1)
    assert result.status in {"timeout", "no_output"}
    payload = json.loads((bundle / "result.json").read_text())
    # On-disk state must NEVER say running (R4).
    assert payload["status"] != "running"
    assert payload["status"] in {"timeout", "no_output"}
    assert payload["codex_launched"] is True


def test_supervised_malformed_jsonl_degrades_token_accounting(tmp_path) -> None:
    result, bundle = _run_bundle(tmp_path, {}, _FAKE_CODEX_MALFORMED)
    assert result.status == "success"
    payload = json.loads((bundle / "result.json").read_text())
    # Tolerant parse: picks the valid usage line, ignores the malformed ones, never fails.
    assert payload["token_usage"]["input_tokens"] == 3
    assert payload["token_usage"]["output_tokens"] == 4
    assert payload["token_usage"]["total_tokens"] is None
    receipt = json.loads((bundle / "bridge-receipt.json").read_text())
    assert receipt["external_tokens"] == 0
    # Raw transcript preserved as durable fallback, malformed lines and all.
    transcript = (bundle / "transcript.jsonl").read_text()
    assert "not json at all" in transcript


def test_supervised_sigterm_mid_run_is_die_clean(tmp_path) -> None:
    """A SIGTERM to the delegate mid-run kills the codex tree and finalizes a terminal bundle.

    Exercised through a real subprocess so the signal can arrive while codex is still running,
    mirroring a caller's Bash-tool timeout (R4).
    """
    import signal as _signal
    import subprocess as _subprocess
    import time as _time

    bin_path = _write_fake_codex_bin(tmp_path, _FAKE_CODEX_SLEEP)
    shim = tmp_path / "codex-shim"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bin_path}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    delegate = _subprocess.Popen(
        [
            sys.executable,
            str(MODULE_PATH),
            "--role",
            "reviewer",
            "--task",
            "Review the diff.",
            "--timeout-seconds",
            "300",
            "--no-output-seconds",
            "300",
            "--repo-root",
            str(repo_root),
            "--run-id",
            "sigterm-run",
            "--codex-bin",
            str(shim),
        ],
        stdout=_subprocess.PIPE,
        stderr=_subprocess.PIPE,
        start_new_session=True,
    )
    bundle = repo_root / ".claude" / "codex" / "runs" / "sigterm-run"
    # Wait for the run to actually launch codex (transcript begins to fill).
    deadline = _time.monotonic() + 15
    while _time.monotonic() < deadline:
        if (bundle / "transcript.jsonl").exists() and (
            bundle / "transcript.jsonl"
        ).read_text().strip():
            break
        _time.sleep(0.05)
    delegate.send_signal(_signal.SIGTERM)
    exit_code = delegate.wait(timeout=30)

    # die-clean: exits nonzero, terminal bundle, never running.
    assert exit_code != 0
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] != "running"
    assert payload["codex_launched"] is True
    # The fake codex "done" sentinel must never appear — the tree was killed mid-sleep.
    assert '"type": "done"' not in (bundle / "transcript.jsonl").read_text()


# --- Code-review fixes (#476 findings 3, 4) -----------------------------------------------------


def test_supervised_command_includes_model_flag_only_when_set(tmp_path) -> None:
    """`-m <model>` must appear in the recorded argv exactly when the envelope sets a model."""
    _, bundle = _run_bundle(tmp_path, {"model": "gpt-5"}, _FAKE_CODEX_SUCCESS)
    argv = json.loads((bundle / "command.json").read_text())["argv"]
    assert "-m" in argv
    assert argv[argv.index("-m") + 1] == "gpt-5"


@pytest.mark.parametrize(
    ("model", "effort"),
    [
        ("gpt-5.6-sol", "high"),
        ("gpt-5.6-sol", "xhigh"),
        ("gpt-5.6-terra", "high"),
        ("gpt-5.6-terra", "xhigh"),
        ("gpt-5.6-luna", "high"),
        ("gpt-5.6-luna", "xhigh"),
    ],
)
def test_registry_model_effort_reach_fake_codex_and_projection(
    tmp_path, model: str, effort: str
) -> None:
    _, bundle = _run_bundle(
        tmp_path,
        {"model": model, "effort": effort},
        _FAKE_CODEX_SUCCESS,
    )
    command = json.loads((bundle / "command.json").read_text())
    argv = command["argv"]
    assert argv[argv.index("-m") + 1] == model
    assert argv[argv.index("-c") + 1] == f"model_reasoning_effort={effort}"

    receipt = json.loads((bundle / "bridge-receipt.json").read_text())
    assert receipt["variant"] == f"{model}-{effort}"
    result = json.loads((bundle / "result.json").read_text())
    assert result["model"] == model
    assert result["effort"] == effort
    projection = (bundle / "projection.md").read_text()
    assert f"Model: {model}" in projection
    assert f"Effort: {effort}" in projection


def test_supervised_command_omits_model_flag_when_absent(tmp_path) -> None:
    _, bundle = _run_bundle(tmp_path, {}, _FAKE_CODEX_SUCCESS)
    argv = json.loads((bundle / "command.json").read_text())["argv"]
    assert "-m" not in argv


# Floods stdout past the OS pipe buffer BEFORE reading stdin: a supervisor that wrote stdin
# synchronously (instead of on the writer thread) would deadlock here — parent blocked writing
# a large prompt into a full stdin pipe, child blocked writing into a full stdout pipe.
_FAKE_CODEX_STDOUT_FIRST = """#!/usr/bin/env python3
import json, sys
argv = sys.argv[1:]
out_path = None
for i, tok in enumerate(argv):
    if tok == "-o":
        out_path = argv[i + 1]
filler = "x" * 1024
for _ in range(256):
    print(json.dumps({"type": "filler", "data": filler}))
sys.stdout.flush()
data = sys.stdin.read()
print(json.dumps({"type": "stdin_len", "n": len(data)}), flush=True)
if out_path:
    open(out_path, "w").write("done")
sys.exit(0)
"""


def test_supervised_large_prompt_does_not_deadlock_stdin(tmp_path) -> None:
    """A prompt larger than the OS pipe buffer must not deadlock against the stdout flood.

    Guards the threaded ``_feed_stdin`` writer: on a synchronous-write regression the watchdog
    kills the pair and the status stops being ``success`` (the test fails rather than hangs).
    """
    big_task = "Review this. " + ("x" * (256 * 1024))
    result, bundle = _run_bundle(
        tmp_path, {"task": big_task}, _FAKE_CODEX_STDOUT_FIRST, timeout_seconds=30
    )
    assert result.status == "success"
    transcript = (bundle / "transcript.jsonl").read_text()
    assert '"type": "stdin_len"' in transcript
