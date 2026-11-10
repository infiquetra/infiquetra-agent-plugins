"""Complete adapter identity resolver (portable core; §5).

The Auralis Bridge Contract v1 (Section 5) needs a three-part identity on
every presence and rendering request, compared byte-exact and never
normalized: ``agent_session_id``, ``pane_id`` and ``terminal_id``. The
contract treats the three as opaque; this module decides where they come
from. They come from herdr core, which runs the terminal this Claude
session lives in:

1. Reads ``HC_TERMINAL_ID`` from its process environment via ``settings.py``.
   herdr core sets it in every terminal as that terminal's address (``t21``).
2. Runs ``hc get <HC_TERMINAL_ID> --json`` (the ``VOICE_HC_BIN`` command)
   under the package subprocess discipline (``process.run``) with a
   2,000 ms deadline.
3. Requires a live terminal whose ``address`` is exactly ``HC_TERMINAL_ID``.
4. Copies that terminal's ``voice.agent-session`` label as
   ``agent_session_id``. herdr core does not know which Claude session runs
   in a terminal; the Claude adapter's ``SessionStart`` hook writes this
   label on its own terminal at every start, resume, clear and compact.
5. Copies the terminal's address as both ``terminal_id`` and ``pane_id``.
   herdr core has no panes: panes belong to the Herdr app's window, which
   can rearrange them while the terminal keeps running. The terminal
   address is the stable "where" for this session.
6. Any Claude hook or agent request carrying Claude's session identifier must
   match ``agent_session_id``.
7. The adapter must never copy identity from ``GET /v1/current``.

A missing environment value, a missing executable, a command or record
failure, a finished terminal, an address mismatch, a missing session label,
or a session mismatch means the adapter registers and submits nothing.

Old Herdr (``HERDR_PANE_ID``, ``HERDR_BIN_PATH`` and ``herdr agent list``)
is retired and no longer read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import herdr_core
import process
import settings

__all__ = [
    "AdapterIdentity",
    "IdentityRefusal",
    "HC_TIMEOUT_SECONDS",
    "resolve_adapter_identity",
    "matches_session",
]

#: The normative identity subprocess deadline from the timeout budget table (2,000 ms).
HC_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class AdapterIdentity:
    """The three-part complete adapter identity (§5)."""

    agent_session_id: str
    pane_id: str
    terminal_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_session_id": self.agent_session_id,
            "pane_id": self.pane_id,
            "terminal_id": self.terminal_id,
        }

    def to_payload(self) -> dict[str, str]:
        return self.to_dict()


class IdentityRefusal(Exception):
    """A named refusal for identity resolution (§5)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"adapter identity refused: {reason}")


def matches_session(identity: AdapterIdentity, session_id: str) -> bool:
    """Return whether a Claude session id matches the adapter's agent_session_id (§5)."""
    if not isinstance(session_id, str):
        return False
    return identity.agent_session_id == session_id


def resolve_adapter_identity(
    *,
    run_process: Callable = process.run,
    terminal_id_resolver: Callable[[], str] = settings.hc_terminal_id,
    bin_path_resolver: Callable[[], str] = settings.hc_bin,
) -> AdapterIdentity:
    """Resolve the three-part adapter identity from herdr core (§5).

    Reads ``HC_TERMINAL_ID`` and ``VOICE_HC_BIN`` through ``settings.py``,
    runs ``hc get <terminal> --json``, and builds the validated
    ``AdapterIdentity`` from the terminal's address and its
    ``voice.agent-session`` label.

    Any failure produces an ``IdentityRefusal`` named refusal.
    """
    try:
        terminal_id = terminal_id_resolver()
    except settings.SettingsRefusal as refusal:
        raise IdentityRefusal(
            f"cannot resolve the herdr core terminal: {refusal.name} {refusal.reason}"
        ) from refusal

    try:
        hc = bin_path_resolver()
    except settings.SettingsRefusal as refusal:
        raise IdentityRefusal(
            f"cannot resolve the herdr core command: {refusal.name} {refusal.reason}"
        ) from refusal

    try:
        record = herdr_core.get_terminal(
            terminal_id,
            timeout=HC_TIMEOUT_SECONDS,
            run_process=run_process,
            hc=hc,
        )
    except herdr_core.CoreRefusal as refusal:
        raise IdentityRefusal(refusal.reason) from refusal

    address = record["address"]
    if address != terminal_id:
        raise IdentityRefusal(
            f"hc get {terminal_id} answered for terminal {address!r}, not this one"
        )
    if not herdr_core.is_live(record):
        raise IdentityRefusal(f"terminal {terminal_id!r} is not live")

    agent_session_id = herdr_core.session_of(record)
    if agent_session_id is None:
        raise IdentityRefusal(
            f"terminal {terminal_id!r} carries no {herdr_core.SESSION_LABEL} label; "
            "the session-start hook has not recorded this Claude session"
        )

    return AdapterIdentity(
        agent_session_id=agent_session_id,
        pane_id=address,
        terminal_id=address,
    )
