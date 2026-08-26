#!/usr/bin/env python3
"""The voice command surface: one small CLI over the portable package.

Commands:

- ``pane`` — run the Voice pane loop in this pane (R13). The pane is the
  operator surface for the conversational loop.
- ``bind <agent>`` — bind voice to one Herdr agent explicitly (KTD7).
  The agent is resolved once through ``herdr agent get``; the binding is
  sticky until an explicit rebind (R2).
- ``preflight`` — probe the declared providers, the stop keybinding, and
  the operator-supplied executables, naming every missing prerequisite
  (R22).
- ``toggle`` — one recording toggle press, sharing the pane's listen-path
  sequencer (KTD16).
- ``stop`` — stop playback immediately; the command the operator's
  Herdr-wide stop keybinding invokes (R8 support).

This CLI is the only command surface the package ships; the Agent Skill
documents it rather than adding a second one. The heavy modules are
imported inside the command handlers, so the CLI's own import stays cheap
and ``deliver`` is never imported at module level (KTD16).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

__all__ = ["main"]

#: Bounded helper deadline (KTD3a): ``herdr agent get`` is a helper call.
HELPER_TIMEOUT_SECONDS = 10.0


def _parse_json_object(text: str) -> dict | None:
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _error_message(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def _session_value(record: dict) -> object:
    session = record.get("agent_session")
    if not isinstance(session, dict):
        return None
    return session.get("value")


def _bind(agent: str) -> int:
    """Resolve one Herdr agent and write the sticky binding (KTD7)."""
    import binding
    import process

    try:
        completed = process.run(
            ["herdr", "agent", "get", agent],
            timeout=HELPER_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            "voice: herdr did not answer within "
            f"{HELPER_TIMEOUT_SECONDS:.0f} seconds",
            file=sys.stderr,
        )
        return 1
    except OSError as error:
        print(f"voice: cannot run herdr: {error}", file=sys.stderr)
        return 1
    payload = _parse_json_object(completed.stdout)
    if completed.returncode != 0 or payload is None:
        # herdr answers successes on stdout and error envelopes on stderr.
        message = _error_message(payload) or _error_message(
            _parse_json_object(completed.stderr)
        ) or (f"herdr exited with status {completed.returncode}")
        print(f"voice: cannot bind {agent!r}: {message}", file=sys.stderr)
        return 1
    result = payload.get("result")
    record = result.get("agent") if isinstance(result, dict) else None
    if not isinstance(record, dict):
        print(
            f"voice: cannot bind {agent!r}: herdr returned no agent record",
            file=sys.stderr,
        )
        return 1
    resolved = {
        "agent name": record.get("name"),
        "session id": _session_value(record),
        "pane id": record.get("pane_id"),
    }
    for label, value in resolved.items():
        if not isinstance(value, str) or not value.strip():
            print(
                f"voice: cannot bind {agent!r}: herdr returned no {label}",
                file=sys.stderr,
            )
            return 1
    written = binding.write_binding(
        resolved["agent name"], resolved["session id"], resolved["pane id"]
    )
    print(
        f"bound agent {written.agent} · session {written.session_id} · "
        f"pane {written.pane_id}"
    )
    return 0


def _pane() -> int:
    import pane

    return pane.run()


def _preflight() -> int:
    import preflight

    return preflight.main()


def _toggle() -> int:
    import pane

    try:
        _recording, messages = pane.toggle_once()
    except Exception as error:
        print(f"voice: {error}", file=sys.stderr)
        return 1
    for message in messages:
        print(message)
    return 0


def _stop() -> int:
    import speak

    speak.stop_playback()
    print("playback stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voice_cli.py",
        description="The voice package command surface.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("pane", help="run the Voice pane loop in this pane")
    bind_parser = subparsers.add_parser(
        "bind", help="bind voice to one Herdr agent explicitly"
    )
    bind_parser.add_argument("agent", help="the Herdr agent name to bind")
    subparsers.add_parser(
        "preflight",
        help="probe the declared providers, keybinding, and executables",
    )
    subparsers.add_parser(
        "toggle", help="one recording toggle press: start, or stop and deliver"
    )
    subparsers.add_parser("stop", help="stop playback immediately")
    arguments = parser.parse_args(argv)
    if arguments.command == "pane":
        return _pane()
    if arguments.command == "bind":
        return _bind(arguments.agent)
    if arguments.command == "preflight":
        return _preflight()
    if arguments.command == "toggle":
        return _toggle()
    if arguments.command == "stop":
        return _stop()
    parser.error(f"unknown command {arguments.command!r}")
    return 2  # Unreached; parser.error exits.


if __name__ == "__main__":
    sys.exit(main())
