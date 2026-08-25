"""Stated settings for the voice package.

This module is the one settings reader for the whole package: every other
module resolves its configuration through it rather than reading the
environment itself. Settings are stated names with split defaults, and
absent is never treated as empty — a setting that is present but empty is
refused by name, never silently defaulted or coerced.

- ``VOICE_FORGE_BASE_URL`` and ``VOICE_FORGE_VOICE_ID`` carry no default.
  They come from the operator's Voice Forge deployment; baking a default
  would hard-code a deployment, and no address is ever hard-coded. Absent
  produces a named refusal at preflight or use.
- ``VOICE_HERMES_BASE_URL`` and ``VOICE_HERMES_PROFILE`` default to the
  acceptance values.
- ``VOICE_CAPTURE_BIN`` and ``VOICE_PLAYBACK_BIN`` are executables supplied
  by the operator, never discovered.
- ``VOICE_STATE_DIR`` is the machine-local runtime state directory.
- ``VOICE_RETENTION`` is a stated setting rather than a silent default:
  version one accepts exactly ``ephemeral``, and an operator must write it
  down for the package to run at all. Any other posture is refused by name.

Every value here is non-secret. No setting may carry a credential: provider
credentials are declared by name (never by value) in ``providers.py``, and
the loopback session token used on the speech-to-text transport is held in
process memory only — never stated, persisted, or logged.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "SettingsRefusal",
    "SETTING_NAMES",
    "RETENTION_EPHEMERAL",
    "FORGE_BASE_URL",
    "FORGE_VOICE_ID",
    "HERMES_BASE_URL",
    "HERMES_PROFILE",
    "CAPTURE_BIN",
    "PLAYBACK_BIN",
    "STATE_DIR",
    "RETENTION",
    "forge_base_url",
    "forge_voice_id",
    "hermes_base_url",
    "hermes_profile",
    "capture_bin",
    "playback_bin",
    "state_dir",
    "retention",
]


class SettingsRefusal(Exception):
    """A named refusal for one setting.

    Carries the setting's name and the reason it is unusable, so preflight
    and use can report both by name. Voice never substitutes a value for a
    setting it cannot honour.
    """

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"{name}: {reason}")


FORGE_BASE_URL = "VOICE_FORGE_BASE_URL"
FORGE_VOICE_ID = "VOICE_FORGE_VOICE_ID"
HERMES_BASE_URL = "VOICE_HERMES_BASE_URL"
HERMES_PROFILE = "VOICE_HERMES_PROFILE"
CAPTURE_BIN = "VOICE_CAPTURE_BIN"
PLAYBACK_BIN = "VOICE_PLAYBACK_BIN"
STATE_DIR = "VOICE_STATE_DIR"
RETENTION = "VOICE_RETENTION"

#: The closed set of settings this package reads. Nothing outside this tuple
#: is ever read from the environment, and no member may carry a secret.
SETTING_NAMES = (
    FORGE_BASE_URL,
    FORGE_VOICE_ID,
    HERMES_BASE_URL,
    HERMES_PROFILE,
    CAPTURE_BIN,
    PLAYBACK_BIN,
    STATE_DIR,
    RETENTION,
)

DEFAULT_HERMES_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_HERMES_PROFILE = "mimir-engineer"
DEFAULT_CAPTURE_BIN = "/opt/homebrew/bin/ffmpeg"
DEFAULT_PLAYBACK_BIN = "/usr/bin/afplay"
DEFAULT_STATE_DIR = "~/.local/state/voice"

RETENTION_EPHEMERAL = "ephemeral"


def _stated(name: str, default: str | None) -> str:
    """Resolve one stated setting, refusing by name rather than guessing.

    Absent and empty are distinct states. An absent setting falls back to
    its documented default when it has one, and is refused by name when it
    does not. An empty setting is always refused: empty is never silently
    treated as a value, and never silently treated as absent either.
    """
    raw = os.environ.get(name)
    if raw is None:
        if default is not None:
            return default
        raise SettingsRefusal(
            name, "is not set and carries no default; state it explicitly"
        )
    value = raw.strip()
    if not value:
        raise SettingsRefusal(
            name,
            "is set but empty; absent is one state and empty is another, "
            "and empty is never treated as a value",
        )
    return value


def forge_base_url() -> str:
    """Base URL of the Voice Forge text-to-speech service. No default."""
    return _stated(FORGE_BASE_URL, None)


def forge_voice_id() -> str:
    """Voice the Voice Forge synthesis uses. No default."""
    return _stated(FORGE_VOICE_ID, None)


def hermes_base_url() -> str:
    """Base URL of the Hermes relay."""
    return _stated(HERMES_BASE_URL, DEFAULT_HERMES_BASE_URL)


def hermes_profile() -> str:
    """Hermes profile the speech-to-text route resolves through."""
    return _stated(HERMES_PROFILE, DEFAULT_HERMES_PROFILE)


def capture_bin() -> str:
    """Capture executable, supplied by the operator, never discovered."""
    return _stated(CAPTURE_BIN, DEFAULT_CAPTURE_BIN)


def playback_bin() -> str:
    """Playback executable, supplied by the operator, never discovered."""
    return _stated(PLAYBACK_BIN, DEFAULT_PLAYBACK_BIN)


def state_dir() -> Path:
    """Machine-local runtime state directory shared by the pane and hooks."""
    return Path(_stated(STATE_DIR, DEFAULT_STATE_DIR)).expanduser()


def retention() -> str:
    """The stated retention posture: exactly ``ephemeral`` in version one.

    Retention is stated rather than defaulted so the empty case — audio
    deleted after success and failure, no transcript log, no telemetry — is
    something a person wrote down. An unset or differently-valued setting is
    refused by name, never honoured and never silently coerced.
    """
    value = _stated(RETENTION, None)
    if value != RETENTION_EPHEMERAL:
        raise SettingsRefusal(
            RETENTION,
            f"states {value!r}; version one accepts exactly "
            f"{RETENTION_EPHEMERAL!r} and refuses other postures by name",
        )
    return value
