"""Voice policy and operator preferences store (R25, R107; KTD5).

This module manages the operator's voice policy and preferences:
- Stated preference instruction lines carried to the agent (R107);
- An armed one-shot 'Brief Next Turn' override (R107), consumed on transmission;
- A tool allow-list selecting which tools to record in PreToolUse observations (KTD7);
- Renders instructions without ever applying content transformations or
  making content decisions in the adapter (R25).

Storage follows the binding.py pattern: atomic write-replace, with absent and
corrupt states reported by name.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import settings

__all__ = [
    "VoicePolicy",
    "PolicyReport",
    "POLICY_FILENAME",
    "STATUS_OK",
    "STATUS_ABSENT",
    "STATUS_CORRUPT",
    "read_policy",
    "read_policy_report",
    "write_policy",
    "arm_brief_next_turn",
    "consume_brief_next_turn",
    "render_instructions",
]

POLICY_FILENAME = "policy.json"

STATUS_OK = "ok"
STATUS_ABSENT = "absent"
STATUS_CORRUPT = "corrupt"

BRIEF_INSTRUCTION = "Brief Next Turn override active: keep the spoken rendering concise and brief."


@dataclass(frozen=True)
class VoicePolicy:
    """The stored voice policy and preferences."""

    preferences: tuple[str, ...] = ()
    brief_next_turn: bool = False
    tool_allowlist: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "preferences": list(self.preferences),
            "brief_next_turn": self.brief_next_turn,
            "tool_allowlist": list(self.tool_allowlist),
        }


@dataclass(frozen=True)
class PolicyReport:
    """The result of reading the policy store."""

    policy: VoicePolicy
    status: str


def _policy_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return settings.state_dir() / POLICY_FILENAME


def write_policy(
    preferences: Sequence[str] | None = None,
    brief_next_turn: bool = False,
    tool_allowlist: Sequence[str] | None = None,
    *,
    path: Path | None = None,
) -> VoicePolicy:
    """Write the policy record atomically, replacing any previous record."""
    clean_prefs = (
        tuple(p.strip() for p in preferences if isinstance(p, str) and p.strip())
        if preferences is not None
        else ()
    )
    clean_tools = (
        tuple(t.strip() for t in tool_allowlist if isinstance(t, str) and t.strip())
        if tool_allowlist is not None
        else ()
    )
    policy = VoicePolicy(
        preferences=clean_prefs,
        brief_next_turn=bool(brief_next_turn),
        tool_allowlist=clean_tools,
    )
    target = _policy_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=".policy-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(policy.to_payload(), indent=2, sort_keys=True))
            handle.write("\n")
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return policy


def read_policy_report(path: Path | None = None) -> PolicyReport:
    """Read the policy store, reporting status as ok, absent, or corrupt."""
    target = _policy_path(path)
    if not target.exists():
        return PolicyReport(policy=VoicePolicy(), status=STATUS_ABSENT)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return PolicyReport(policy=VoicePolicy(), status=STATUS_CORRUPT)
        prefs_raw = payload.get("preferences", [])
        if not isinstance(prefs_raw, list) or not all(isinstance(p, str) for p in prefs_raw):
            return PolicyReport(policy=VoicePolicy(), status=STATUS_CORRUPT)
        brief_raw = payload.get("brief_next_turn", False)
        if not isinstance(brief_raw, bool):
            return PolicyReport(policy=VoicePolicy(), status=STATUS_CORRUPT)
        tools_raw = payload.get("tool_allowlist", [])
        if not isinstance(tools_raw, list) or not all(isinstance(t, str) for t in tools_raw):
            return PolicyReport(policy=VoicePolicy(), status=STATUS_CORRUPT)
        policy = VoicePolicy(
            preferences=tuple(prefs_raw),
            brief_next_turn=brief_raw,
            tool_allowlist=tuple(tools_raw),
        )
        return PolicyReport(policy=policy, status=STATUS_OK)
    except (OSError, ValueError):
        return PolicyReport(policy=VoicePolicy(), status=STATUS_CORRUPT)


def read_policy(path: Path | None = None) -> VoicePolicy:
    """Return the current policy, or a default policy if absent or corrupt."""
    return read_policy_report(path).policy


def arm_brief_next_turn(*, path: Path | None = None) -> VoicePolicy:
    """Arm the Brief Next Turn one-shot override atomically."""
    current = read_policy(path)
    return write_policy(
        preferences=current.preferences,
        brief_next_turn=True,
        tool_allowlist=current.tool_allowlist,
        path=path,
    )


def consume_brief_next_turn(*, path: Path | None = None) -> bool:
    """Consume the Brief Next Turn override if armed.

    Returns True if the override was armed and has now been disarmed,
    or False if it was not armed.
    """
    current = read_policy(path)
    if not current.brief_next_turn:
        return False
    write_policy(
        preferences=current.preferences,
        brief_next_turn=False,
        tool_allowlist=current.tool_allowlist,
        path=path,
    )
    return True


def render_instructions(
    policy: VoicePolicy | None = None,
    *,
    brief: bool | None = None,
    path: Path | None = None,
) -> str:
    """Render the operator policy and preferences into instruction text.

    Preferences are rendered verbatim and never applied to alter or transform
    content (R25). If brief is True (or armed in policy when brief is None),
    the brief directive is included.
    """
    if policy is None:
        policy = read_policy(path)
    is_brief = policy.brief_next_turn if brief is None else bool(brief)

    lines: list[str] = []
    if is_brief:
        lines.append(BRIEF_INSTRUCTION)
    for pref in policy.preferences:
        lines.append(pref)

    return "\n".join(lines)
