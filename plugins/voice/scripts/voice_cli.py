#!/usr/bin/env python3
"""The voice command surface: one small CLI over the portable package.

Commands:

- ``pane`` — run the Voice pane loop in this pane (R13). The pane is the
  operator surface for the conversational loop.
- ``bind <terminal>`` — bind voice to one Claude session explicitly (KTD7),
  named by its herdr core terminal: a name (``review``) or an address
  (``t7``). The terminal is resolved once through ``hc get``; the binding
  is sticky until an explicit rebind (R2).
- ``preflight`` — probe the declared providers, the stop keybinding, and
  the operator-supplied executables, naming every missing prerequisite
  (R22).
- ``toggle`` — one recording toggle press, sharing the pane's listen-path
  sequencer (KTD16).
- ``stop`` — stop playback immediately; the command the operator's
  Herdr-wide stop key invokes (R8 support).
- ``policy`` — inspect or configure voice policy (``show``, ``brief-next-turn``).

This CLI is the only command surface the package ships; the Agent Skill
documents it rather than adding a second one. The heavy modules are
imported inside the command handlers, so the CLI's own import stays cheap
and ``deliver`` is never imported at module level (KTD16).
"""

from __future__ import annotations

import argparse
import json
import sys

__all__ = ["main"]

#: Bounded helper deadline (KTD3a): ``hc get`` is a helper call.
HELPER_TIMEOUT_SECONDS = 10.0


def _bind(target: str) -> int:
    """Resolve one herdr core terminal and write the sticky binding (KTD7).

    The terminal must be live, on this machine, and labelled with the
    Claude session running in it (``voice.agent-session``, written by the
    Claude adapter's SessionStart hook). The binding stores the terminal's
    address, which herdr core never reuses, so delivery can never reach a
    different terminal that later takes the same name.
    """
    import binding
    import herdr_core
    import process

    def refuse(reason: str) -> int:
        print(f"voice: cannot bind {target!r}: {reason}", file=sys.stderr)
        return 1

    try:
        record = herdr_core.get_terminal(
            target, timeout=HELPER_TIMEOUT_SECONDS, run_process=process.run
        )
    except herdr_core.CoreRefusal as refusal:
        return refuse(refusal.reason)
    address = record["address"]
    if herdr_core.is_other_machine(address):
        return refuse(
            f"it is terminal {address} on another machine; voice records and "
            "plays audio on this machine, so it binds only a terminal here"
        )
    if not herdr_core.is_live(record):
        return refuse(f"terminal {address} has finished")
    session_id = herdr_core.session_of(record)
    if session_id is None:
        return refuse(
            f"terminal {address} carries no {herdr_core.SESSION_LABEL} label, so "
            "herdr core cannot say which Claude session runs there. Is the voice "
            "plugin enabled in that Claude session? Its SessionStart hook writes "
            "the label: restart or resume that session, then bind again"
        )
    if herdr_core.printable(session_id, limit=len(session_id)) != session_id:
        return refuse(
            f"terminal {address}'s {herdr_core.SESSION_LABEL} label holds control "
            "characters or spacing a Claude session id never has"
        )
    # The terminal's name is set by whoever started it; the pane shows it on
    # every redraw, so keep only printable text.
    name = record.get("name")
    shown = herdr_core.printable(name) if isinstance(name, str) else ""
    agent = shown or address
    written = binding.write_binding(agent, session_id, address)
    print(
        f"bound agent {written.agent} · session {written.session_id} · "
        f"terminal {written.terminal}"
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


def _policy(policy_args: argparse.Namespace) -> int:
    import voice_policy

    if policy_args.policy_command == "show":
        policy = voice_policy.read_policy()
        print(json.dumps(policy.to_payload(), indent=2, sort_keys=True))
        return 0
    if policy_args.policy_command == "brief-next-turn":
        voice_policy.arm_brief_next_turn()
        print("armed brief next turn override")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voice_cli.py",
        description="The voice package command surface.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("pane", help="run the Voice pane loop in this pane")
    bind_parser = subparsers.add_parser(
        "bind", help="bind voice to one Claude session's herdr core terminal"
    )
    bind_parser.add_argument(
        "agent",
        metavar="terminal",
        help="the herdr core terminal to bind: its name or its address (t7)",
    )
    subparsers.add_parser(
        "preflight",
        help="probe the declared providers, keybinding, and executables",
    )
    subparsers.add_parser(
        "toggle", help="one recording toggle press: start, or stop and deliver"
    )
    subparsers.add_parser("stop", help="stop playback immediately")
    policy_parser = subparsers.add_parser(
        "policy", help="inspect or configure voice policy"
    )
    policy_subparsers = policy_parser.add_subparsers(
        dest="policy_command", required=True
    )
    policy_subparsers.add_parser("show", help="show current voice policy")
    policy_subparsers.add_parser(
        "brief-next-turn", help="arm brief next turn override"
    )
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
    if arguments.command == "policy":
        return _policy(arguments)
    parser.error(f"unknown command {arguments.command!r}")
    return 2  # Unreached; parser.error exits.


if __name__ == "__main__":
    sys.exit(main())
