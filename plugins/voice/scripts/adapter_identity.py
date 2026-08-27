"""Complete adapter identity resolver (portable core; §5).

This module implements the C3 adapter identity discovery rule defined in
Section 5 of the Auralis Bridge Contract v1:

1. Reads ``HERDR_PANE_ID`` from its process environment via ``settings.py``.
2. Executes the ``HERDR_BIN_PATH`` executable with arguments ``agent``, ``list``
   under the package subprocess discipline (``process.run``) with a 2,000 ms
   deadline.
3. Verifies that the JSON envelope contains ``result.type == "agent_list"``.
4. Finds exactly one record in ``result.agents`` where ``pane_id == HERDR_PANE_ID``.
5. Copies that record's non-empty ``agent_session.value`` as ``agent_session_id``,
   that record's ``pane_id`` as ``pane_id``, and that record's ``terminal_id`` as
   ``terminal_id``.
6. Any Claude hook or agent request carrying Claude's session identifier must
   match ``agent_session_id``.
7. The adapter must never copy identity from ``GET /v1/current``.

A missing environment value, missing executable, command or envelope failure,
zero or multiple matches, a missing component, or a session mismatch means the
adapter registers and submits nothing.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

import process
import settings

__all__ = [
    "AdapterIdentity",
    "IdentityRefusal",
    "HERDR_TIMEOUT_SECONDS",
    "resolve_adapter_identity",
    "matches_session",
]

#: The normative Herdr subprocess deadline from the timeout budget table (2,000 ms).
HERDR_TIMEOUT_SECONDS = 2.0


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


def _extract_component(record: dict, key: str) -> str:
    """Extract a non-empty string component from a record dict."""
    val = record.get(key)
    if not isinstance(val, str):
        raise IdentityRefusal(
            f"record field {key!r} must be a string, got {type(val).__name__}"
        )
    val = val.strip()
    if not val:
        raise IdentityRefusal(f"record field {key!r} is empty")
    return val


def resolve_adapter_identity(
    *,
    run_process: Callable = process.run,
    pane_id_resolver: Callable[[], str] = settings.herdr_pane_id,
    bin_path_resolver: Callable[[], str] = settings.herdr_bin_path,
) -> AdapterIdentity:
    """Resolve the three-part adapter identity from Herdr (§5).

    Reads ``HERDR_PANE_ID`` and ``HERDR_BIN_PATH`` through ``settings.py``,
    runs ``herdr agent list``, parses the envelope, matches the pane, and
    constructs the validated ``AdapterIdentity``.

    Any failure produces an ``IdentityRefusal`` named refusal.
    """
    try:
        target_pane_id = pane_id_resolver()
    except settings.SettingsRefusal as refusal:
        raise IdentityRefusal(
            f"cannot resolve pane id: {refusal.name} {refusal.reason}"
        ) from refusal

    try:
        bin_path = bin_path_resolver()
    except settings.SettingsRefusal as refusal:
        raise IdentityRefusal(
            f"cannot resolve Herdr executable: {refusal.name} {refusal.reason}"
        ) from refusal

    command = [bin_path, "agent", "list"]
    try:
        completed = run_process(
            command,
            timeout=HERDR_TIMEOUT_SECONDS,
            check=True,
        )
    except subprocess.TimeoutExpired as expired:
        raise IdentityRefusal(
            f"Herdr command timed out after {HERDR_TIMEOUT_SECONDS}s: {expired}"
        ) from expired
    except (subprocess.CalledProcessError, FileNotFoundError, PermissionError, OSError) as err:
        raise IdentityRefusal(f"Herdr command failed: {err}") from err

    stdout_text = completed.stdout if hasattr(completed, "stdout") else str(completed)
    try:
        envelope = json.loads(stdout_text)
    except (json.JSONDecodeError, TypeError) as err:
        raise IdentityRefusal(f"Herdr output is not valid JSON: {err}") from err

    if not isinstance(envelope, dict):
        raise IdentityRefusal("Herdr output envelope is not a JSON object")

    if envelope.get("type") != "agent_list":
        raise IdentityRefusal(
            f"Herdr envelope type is {envelope.get('type')!r}, expected 'agent_list'"
        )

    agents = envelope.get("agents")
    if not isinstance(agents, list):
        raise IdentityRefusal("Herdr envelope 'agents' is not a list")

    matching = [
        agent
        for agent in agents
        if isinstance(agent, dict) and agent.get("pane_id") == target_pane_id
    ]

    if not matching:
        raise IdentityRefusal(f"no agent matching pane_id {target_pane_id!r}")
    if len(matching) > 1:
        raise IdentityRefusal(
            f"multiple ({len(matching)}) agents matching pane_id {target_pane_id!r}"
        )

    record = matching[0]

    agent_session = record.get("agent_session")
    if not isinstance(agent_session, dict):
        raise IdentityRefusal(
            f"record 'agent_session' must be an object, got {type(agent_session).__name__}"
        )

    agent_session_id = agent_session.get("value")
    if not isinstance(agent_session_id, str):
        raise IdentityRefusal(
            f"record agent_session.value must be a string, got {type(agent_session_id).__name__}"
        )
    agent_session_id = agent_session_id.strip()
    if not agent_session_id:
        raise IdentityRefusal("record agent_session.value is empty")

    pane_id = _extract_component(record, "pane_id")
    terminal_id = _extract_component(record, "terminal_id")

    return AdapterIdentity(
        agent_session_id=agent_session_id,
        pane_id=pane_id,
        terminal_id=terminal_id,
    )
