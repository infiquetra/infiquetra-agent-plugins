"""The sticky single-speaker binding store (portable core).

Voice binds to exactly one Herdr agent, chosen explicitly by the operator,
and stays bound until the operator explicitly changes it (R2). This module
is the store for that binding: ``binding.json`` under the machine-local
state directory carries the Herdr agent name, the Claude session id that
joins the hook to the agent (the ``agent_session.value`` of ``herdr agent
list``), the pane id, and a bound-at timestamp.

The binding is single-valued and sticky. Writing replaces the whole record
— that is the only mutation path — and nothing here ever infers a target
from focus or recency. Reads are pure local file reads, so the Stop hook
can compare its own session id against the stored one without touching a
subprocess on the hot path (KTD7).

A missing or unreadable file reads as unbound, and the two states stay
reportable so the pane can name "not bound yet" and "binding unreadable —
rebind" distinctly rather than collapsing them. Writes are atomic
(write-temp-then-replace) so a reader never observes a partial record.

The binding is vendor-neutral on purpose (R29): only the hook that fires
on the Claude ``Stop`` event is client-specific, and it lives under the
client extension directory, not here.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import settings

__all__ = [
    "Binding",
    "BindingReport",
    "BINDING_FILENAME",
    "STATUS_BOUND",
    "STATUS_ABSENT",
    "STATUS_CORRUPT",
    "read_binding",
    "read_binding_report",
    "write_binding",
]

BINDING_FILENAME = "binding.json"

#: The binding file holds exactly one record and it is readable.
STATUS_BOUND = "bound"
#: There is no binding file: nothing has been bound yet.
STATUS_ABSENT = "absent"
#: A binding file exists but does not read as one usable record.
STATUS_CORRUPT = "corrupt"

_FIELDS = ("agent", "session_id", "pane_id", "bound_at")


@dataclass(frozen=True)
class Binding:
    """The one bound identity: Herdr agent, Claude session, pane, bound-at."""

    agent: str
    session_id: str
    pane_id: str
    bound_at: str

    def to_payload(self) -> dict[str, str]:
        return {
            "agent": self.agent,
            "session_id": self.session_id,
            "pane_id": self.pane_id,
            "bound_at": self.bound_at,
        }


@dataclass(frozen=True)
class BindingReport:
    """One read of the binding state: the record when bound, plus the status.

    The status distinguishes the absent file from the unreadable one so the
    pane can report both by name; ``binding`` is ``None`` for either
    unbound state.
    """

    binding: Binding | None
    status: str


def _stated_field(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"binding field {name!r} must be a string, not {type(value).__name__}"
        )
    stated = value.strip()
    if not stated:
        raise ValueError(
            f"binding field {name!r} is empty; a binding field is stated "
            "outright and empty is never a value"
        )
    return stated


def _binding_path() -> Path:
    return settings.state_dir() / BINDING_FILENAME


def write_binding(
    agent: str,
    session_id: str,
    pane_id: str,
    *,
    bound_at: str | None = None,
) -> Binding:
    """Write the one binding record, replacing whatever was bound before.

    The values are the resolved Herdr identity (the caller resolves them
    through ``herdr agent get``; this store never calls out). ``bound_at``
    defaults to the current UTC timestamp. The write is atomic and creates
    the state directory when it does not exist yet.
    """
    record = Binding(
        agent=_stated_field("agent", agent),
        session_id=_stated_field("session_id", session_id),
        pane_id=_stated_field("pane_id", pane_id),
        bound_at=_stated_field("bound_at", bound_at)
        if bound_at is not None
        else datetime.now(UTC).isoformat(),
    )
    target = _binding_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=".binding-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_payload(), indent=2, sort_keys=True))
            handle.write("\n")
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return record


def read_binding_report() -> BindingReport:
    """Read the binding state once, never raising for an unbound state.

    An absent file reports ``absent``; a file that exists but does not
    parse to one complete record reports ``corrupt``; both read as unbound.
    """
    path = _binding_path()
    if not path.exists():
        return BindingReport(binding=None, status=STATUS_ABSENT)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return BindingReport(binding=None, status=STATUS_CORRUPT)
        fields = {name: _stated_field(name, payload.get(name)) for name in _FIELDS}
    except (OSError, ValueError):
        return BindingReport(binding=None, status=STATUS_CORRUPT)
    return BindingReport(binding=Binding(**fields), status=STATUS_BOUND)


def read_binding() -> Binding | None:
    """The bound record, or ``None`` when absent or corrupt (unbound)."""
    return read_binding_report().binding
