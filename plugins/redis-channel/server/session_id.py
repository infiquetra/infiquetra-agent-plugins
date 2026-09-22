"""Session identity generation for redis-channel.

Auto-name pattern: `<cwd-basename>-<short-hash>`, where short-hash is the
first 8 hex chars of sha256(cwd + host). This is stable across restarts
of the same CC session (same cwd, same host) yet unique across machines
and across project directories.

The `CLAUDE_SESSION_NAME` env var overrides the auto-name. A user-supplied
name is used verbatim after validation (slug regex).
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
from pathlib import Path

# Conservative slug: lowercase, digits, hyphen, underscore; 1-64 chars.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_ENV_OVERRIDE = "CLAUDE_SESSION_NAME"


def _sanitize_basename(name: str) -> str:
    """Lowercase, replace non-slug chars with hyphen, collapse repeats, strip."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return cleaned or "session"


def _short_hash(cwd: str, host: str) -> str:
    digest = hashlib.sha256(f"{cwd}|{host}".encode()).hexdigest()
    return digest[:8]


def is_valid_session_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def auto_session_name(cwd: str | os.PathLike[str] | None = None, host: str | None = None) -> str:
    """Generate the auto-name from cwd + host.

    Stable for a given (cwd, host) pair. Does not consult env override.
    """
    cwd_str = str(Path(cwd or os.getcwd()).resolve())
    host_str = host or socket.gethostname()
    basename = _sanitize_basename(Path(cwd_str).name)
    return f"{basename}-{_short_hash(cwd_str, host_str)}"


def resolve_session_name(
    override: str | None = None,
    cwd: str | os.PathLike[str] | None = None,
    host: str | None = None,
) -> str:
    """Return the effective session name.

    Precedence: explicit `override` arg → env var → auto-name. The override
    must satisfy `is_valid_session_name`; otherwise raises ValueError.
    """
    candidate = override if override is not None else os.environ.get(_ENV_OVERRIDE)
    if candidate:
        candidate = candidate.strip()
        if not is_valid_session_name(candidate):
            raise ValueError(f"invalid session name {candidate!r}: must match {_NAME_RE.pattern}")
        return candidate
    return auto_session_name(cwd=cwd, host=host)
