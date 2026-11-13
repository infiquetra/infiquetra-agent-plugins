"""Preflight for the declared providers, keybinding, and executables.

Preflight proves the loop's prerequisites before first use and reports
every missing or misconfigured one by provider and prerequisite name —
rather than failing at first use (R22). Nothing is ever substituted
(R23), installed, written, or repaired: the probes read and probe only
(R15, R24).

The probes, in fixed order:

- ``voice-forge`` — ``GET /health`` requiring ``ok: true`` *with* a loaded
  backend (a healthy process with no loaded backend fails), ``GET
  /v1/audio/voices`` requiring the configured voice id, then one real
  short synthesis whose audio becomes the speech-to-text sample (KTD15).
- ``hermes-xai`` — ``GET /api/health``, the loopback session token read
  from the dashboard root page into memory only, ``GET /api/profiles``
  with the token header requiring the configured profile to resolve among
  the relay's profiles (live profiles carry no speech-to-text surface —
  the profile's ``provider`` is its LLM provider), then the KTD15 sample
  through ``POST /api/audio/transcribe`` requiring a non-empty transcript
  from provider ``xai``: the round trip itself is the speech-to-text
  guarantee. ``auth_required: false`` on the health endpoint is never read
  as anonymous access: the token is required either way, and a missing
  token is reported as token-missing, never as healthy.
- The operator's Herdr-wide stop key — one read-only probe of the Herdr
  app's ``keys.json`` and the mod a key there reaches (KTD13); voice never
  writes any Herdr configuration.
- The operator-supplied capture and playback executables.

When synthesis is unavailable, the sample round trip is reported by name
as not run while the token, profile, and health probes still run —
degradation is named, never silent (KTD15). The session token is never
persisted, printed, or logged; refusals never repeat the page that
carries it.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shlex
import shutil
import urllib.error
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import providers
import settings
import transcribe

__all__ = [
    "ProbeResult",
    "CHECK_OK",
    "CHECK_FAILED",
    "CHECK_NOT_RUN",
    "PROBE_TIMEOUT_SECONDS",
    "SAMPLE_PHRASE",
    "DEFAULT_KEYBINDING_PATH",
    "KEYBINDING_OWNER",
    "probe_forge_health",
    "probe_forge_voice_id",
    "synthesize_sample",
    "probe_hermes_health",
    "fetch_session_token",
    "probe_hermes_profile",
    "probe_sample_round_trip",
    "probe_keybinding",
    "command_is_runnable",
    "command_names_stop_path",
    "probe_executable",
    "run_all",
    "format_report",
    "main",
]

#: Bounded probe deadline (KTD3a class): a hang is a named refusal.
PROBE_TIMEOUT_SECONDS = 10.0

CHECK_OK = "ok"
CHECK_FAILED = "failed"
CHECK_NOT_RUN = "not-run"

HEALTH_PATH = "/health"
VOICES_PATH = "/v1/audio/voices"
SPEECH_PATH = "/v1/audio/speech"
HERMES_HEALTH_PATH = "/api/health"
HERMES_PROFILES_PATH = "/api/profiles"

#: The fixed phrase the KTD15 sample synthesizes. The loop can produce a
#: phrase for free; no binary fixture is committed and no probe records a
#: fresh microphone sample.
SAMPLE_PHRASE = "Voice preflight sample."

SAMPLE_FILE_PREFIX = "preflight-sample-"

#: The Herdr app's key bindings live here (KTD13); its mods live beside it
#: in ``mods/<name>/main.js``. Old Herdr's ``~/.config/herdr/config.toml``
#: is retired and no longer read.
DEFAULT_KEYBINDING_PATH = Path("~/.config/herdr-app/keys.json")

#: The owner name the stop-key probe reports under.
KEYBINDING_OWNER = "herdr-app-keys"

#: The documented binding, and what the probe reports by name.
KEYBINDING_MARKER = "voice stop"

#: The package CLI, for recognizing a binding that invokes it directly rather
#: than through the launcher. Both forms are legitimate; only the launcher form
#: survives a version bump, which is why it is the one documented.
KEYBINDING_CLI = "voice_cli.py"

_TOKEN_HEADER = "X-Hermes-Session-Token"
#: The wire contract of KTD9: the session token is served on the dashboard
#: root page. The pattern is duplicated from ``transcribe`` deliberately —
#: that copy is private, and preflight probes the same page on its own.
_TOKEN_PATTERN = re.compile(
    r"window\.__HERMES_SESSION_TOKEN__\s*=\s*([\"'])([^\"']+)\1"
)


@dataclass(frozen=True)
class ProbeResult:
    """One probe's outcome: who owns it, what it checked, and the status.

    The detail names the missing prerequisite (or the observed state) and
    never carries a credential or anything a credential rides in.
    """

    owner: str
    check: str
    status: str
    detail: str = ""

    @property
    def label(self) -> str:
        return f"{self.owner}: {self.check}"


def _default_open(request, *, timeout: float) -> tuple[int, bytes]:
    """Open one request via ``urllib.request`` and answer status plus body.

    HTTP error statuses are returned, not raised, so probes can name them;
    transport failures propagate for the probe to refuse by name.
    """
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _get_json(
    base_url: str,
    path: str,
    *,
    open_url: Callable,
    headers: dict[str, str] | None = None,
) -> tuple[int, object]:
    url = base_url.rstrip("/") + path
    request = urllib.request.Request(url, method="GET", headers=headers or {})
    status, body = open_url(request, timeout=PROBE_TIMEOUT_SECONDS)
    try:
        payload = json.loads(body.decode("utf-8")) if body else None
    except ValueError:
        payload = None
    return status, payload


def _backends_loaded(value: object) -> bool:
    """A non-empty ``backends_loaded`` is the usable-backend proof.

    Accepts the loaded-backend collection or a positive loaded count, so a
    healthy process proves it has a backend to synthesize with under
    either representation.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value > 0
    if isinstance(value, (str, list, tuple, dict)):
        return len(value) > 0
    return False


def probe_forge_health(base_url: str, *, open_url: Callable) -> ProbeResult:
    """``GET /health``: a healthy process with a usable backend.

    Voice Forge v0.3.0 answers ``{"ok": true, "version", "registry_dir",
    "voices_count", "backends_available", "backends_loaded"}`` — ``ok`` is
    the health flag, and a non-empty ``backends_loaded`` proves the
    backend. A healthy process with no loaded backend fails — the process
    answering is not the backend synthesizing.
    """
    check = f"GET {HEALTH_PATH}"
    try:
        status, payload = _get_json(base_url, HEALTH_PATH, open_url=open_url)
    except (OSError, ValueError, http.client.HTTPException) as error:
        return ProbeResult(
            providers.VOICE_FORGE, check, CHECK_FAILED, f"unreachable: {error}"
        )
    if not 200 <= status < 300:
        return ProbeResult(
            providers.VOICE_FORGE, check, CHECK_FAILED, f"answered HTTP {status}"
        )
    if not isinstance(payload, dict):
        return ProbeResult(
            providers.VOICE_FORGE,
            check,
            CHECK_FAILED,
            "answered something that is not a JSON object",
        )
    if payload.get("ok") is not True:
        return ProbeResult(
            providers.VOICE_FORGE,
            check,
            CHECK_FAILED,
            f"the process reports ok={payload.get('ok')!r}, not true",
        )
    if not _backends_loaded(payload.get("backends_loaded")):
        return ProbeResult(
            providers.VOICE_FORGE,
            check,
            CHECK_FAILED,
            "the process is healthy but reports no loaded backend",
        )
    return ProbeResult(
        providers.VOICE_FORGE,
        check,
        CHECK_OK,
        "process healthy with a loaded backend",
    )


def _voice_ids(payload: object) -> set[str]:
    """The voice ids a ``/v1/audio/voices`` answer lists.

    Accepts a bare list, or an object carrying one under ``voices`` or
    ``data``; each entry is an id string or an object with one.
    """
    entries = payload
    if isinstance(payload, dict):
        entries = None
        for key in ("voices", "data"):
            if isinstance(payload.get(key), list):
                entries = payload[key]
                break
    if not isinstance(entries, list):
        return set()
    ids: set[str] = set()
    for entry in entries:
        if isinstance(entry, str) and entry.strip():
            ids.add(entry)
        elif isinstance(entry, dict):
            for key in ("id", "voice_id", "name"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    ids.add(value)
                    break
    return ids


def probe_forge_voice_id(
    base_url: str, voice_id: str, *, open_url: Callable
) -> ProbeResult:
    """``GET /v1/audio/voices``: the configured voice id must be listed."""
    check = f"GET {VOICES_PATH}"
    try:
        status, payload = _get_json(base_url, VOICES_PATH, open_url=open_url)
    except (OSError, ValueError, http.client.HTTPException) as error:
        return ProbeResult(
            providers.VOICE_FORGE, check, CHECK_FAILED, f"unreachable: {error}"
        )
    if not 200 <= status < 300:
        return ProbeResult(
            providers.VOICE_FORGE, check, CHECK_FAILED, f"answered HTTP {status}"
        )
    ids = _voice_ids(payload)
    if not ids:
        return ProbeResult(
            providers.VOICE_FORGE,
            check,
            CHECK_FAILED,
            "the answer lists no voices",
        )
    if voice_id not in ids:
        return ProbeResult(
            providers.VOICE_FORGE,
            check,
            CHECK_FAILED,
            f"voice id {voice_id!r} is not among the {len(ids)} voices the "
            "service lists",
        )
    return ProbeResult(
        providers.VOICE_FORGE, check, CHECK_OK, f"voice id {voice_id!r} is listed"
    )


def synthesize_sample(
    base_url: str, voice_id: str, *, open_url: Callable
) -> bytes:
    """One real short synthesis (KTD15); raises ``ProviderRefusal`` by name.

    The same OpenAI-compatible body the speak path uses; the bytes stay in
    memory until the sample round trip writes them to its ephemeral file.
    """
    url = base_url.rstrip("/") + SPEECH_PATH
    body = json.dumps(
        {"input": SAMPLE_PHRASE, "voice": voice_id, "response_format": "wav"}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        status, payload = open_url(request, timeout=PROBE_TIMEOUT_SECONDS)
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE, f"sample synthesis unreachable: {error}"
        ) from error
    if not 200 <= status < 300:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE,
            f"sample synthesis refused with HTTP status {status}",
        )
    if not payload:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE, "sample synthesis returned no audio"
        )
    return payload


def probe_hermes_health(base_url: str, *, open_url: Callable) -> ProbeResult:
    """``GET /api/health``: the relay answers.

    The ``auth_required`` field is deliberately never consulted: a relay
    that reports ``auth_required: false`` is still probed with a session
    token, and an anonymous call is treated as token-missing, never as
    healthy.
    """
    check = f"GET {HERMES_HEALTH_PATH}"
    try:
        status, payload = _get_json(base_url, HERMES_HEALTH_PATH, open_url=open_url)
    except (OSError, ValueError, http.client.HTTPException) as error:
        return ProbeResult(
            providers.HERMES_XAI, check, CHECK_FAILED, f"unreachable: {error}"
        )
    if not 200 <= status < 300:
        return ProbeResult(
            providers.HERMES_XAI, check, CHECK_FAILED, f"answered HTTP {status}"
        )
    if not isinstance(payload, dict):
        return ProbeResult(
            providers.HERMES_XAI,
            check,
            CHECK_FAILED,
            "answered something that is not a JSON object",
        )
    version = payload.get("version")
    detail = f"relay answering (version {version})" if version else "relay answering"
    return ProbeResult(providers.HERMES_XAI, check, CHECK_OK, detail)


def fetch_session_token(base_url: str, *, open_url: Callable) -> str:
    """Read one session token from the dashboard root page, into memory only.

    Raises ``ProviderRefusal`` naming the token-missing condition. The
    refusal never repeats the page body, because the page carries the
    token.
    """
    request = urllib.request.Request(base_url.rstrip("/") + "/", method="GET")
    try:
        status, body = open_url(request, timeout=PROBE_TIMEOUT_SECONDS)
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise providers.ProviderRefusal(
            providers.HERMES_XAI, f"the relay root page is unreachable: {error}"
        ) from error
    if not 200 <= status < 300:
        raise providers.ProviderRefusal(
            providers.HERMES_XAI,
            f"the relay root page answered HTTP {status} instead of serving "
            "the session token",
        )
    match = _TOKEN_PATTERN.search(body.decode("utf-8", errors="replace"))
    if match is None or not match.group(2):
        raise providers.ProviderRefusal(
            providers.HERMES_XAI,
            "token-missing: the relay root page did not carry a session token",
        )
    return match.group(2)


def _find_profile(payload: object, profile_name: str) -> dict | None:
    """The configured profile in a ``/api/profiles`` answer, in any shape.

    Accepts a mapping keyed by profile name, a list of objects carrying
    ``name``, or either nested under a ``profiles`` key.
    """
    containers: list[object] = []
    if isinstance(payload, dict):
        if "profiles" in payload:
            containers.append(payload["profiles"])
        else:
            containers.append(payload)
    elif isinstance(payload, list):
        containers.append(payload)
    for container in containers:
        if isinstance(container, dict):
            entry = container.get(profile_name)
            if isinstance(entry, dict):
                return entry
            for value in container.values():
                if isinstance(value, dict) and value.get("name") == profile_name:
                    return value
        elif isinstance(container, list):
            for entry in container:
                if isinstance(entry, dict) and entry.get("name") == profile_name:
                    return entry
    return None


def probe_hermes_profile(
    base_url: str, profile: str, token: str, *, open_url: Callable
) -> ProbeResult:
    """``GET /api/profiles``: the configured profile must resolve.

    Live relay profiles carry no speech-to-text surface — a profile's
    ``provider`` is its LLM provider — so the probe proves the token
    authenticates and the configured profile is among the relay's
    profiles, and stops there. The speech-to-text guarantee is the sample
    round trip, which resolves the provider from the relay's own
    transcription answer (KTD15).

    The session token rides in the header only — never in the URL — and
    the report names the profile, never a credential.
    """
    check = f"GET {HERMES_PROFILES_PATH}"
    url = base_url.rstrip("/") + HERMES_PROFILES_PATH
    request = urllib.request.Request(
        url, method="GET", headers={_TOKEN_HEADER: token}
    )
    try:
        status, body = open_url(request, timeout=PROBE_TIMEOUT_SECONDS)
    except (OSError, ValueError, http.client.HTTPException) as error:
        return ProbeResult(
            providers.HERMES_XAI, check, CHECK_FAILED, f"unreachable: {error}"
        )
    if status == 401:
        return ProbeResult(
            providers.HERMES_XAI,
            check,
            CHECK_FAILED,
            "the relay rejected the session token",
        )
    if not 200 <= status < 300:
        return ProbeResult(
            providers.HERMES_XAI, check, CHECK_FAILED, f"answered HTTP {status}"
        )
    try:
        payload = json.loads(body.decode("utf-8")) if body else None
    except ValueError:
        payload = None
    entry = _find_profile(payload, profile)
    if entry is None:
        return ProbeResult(
            providers.HERMES_XAI,
            check,
            CHECK_FAILED,
            f"profile {profile!r} is not among the relay's profiles",
        )
    return ProbeResult(
        providers.HERMES_XAI,
        check,
        CHECK_OK,
        f"profile {profile!r} resolved among the relay's profiles",
    )


def probe_sample_round_trip(sample_bytes: bytes, *, open_url: Callable) -> ProbeResult:
    """The KTD15 sample: synthesized audio in, non-empty ``xai`` transcript out.

    The sample file lives under the state directory and is deleted as soon
    as the round trip returns — success and failure alike. The round trip
    runs through ``transcribe`` itself, so the token refresh-and-retry
    contract and the ephemeral deletion are the declared path's, not a
    preflight copy of them.
    """
    check = f"sample round trip via POST {transcribe.TRANSCRIBE_PATH}"
    directory = settings.state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    sample_path = directory / f"{SAMPLE_FILE_PREFIX}{uuid.uuid4().hex}.wav"
    sample_path.write_bytes(sample_bytes)
    try:
        transcription = transcribe.transcribe(sample_path, open_url=open_url)
    except (providers.ProviderRefusal, settings.SettingsRefusal, OSError) as error:
        return ProbeResult(providers.HERMES_XAI, check, CHECK_FAILED, str(error))
    finally:
        sample_path.unlink(missing_ok=True)
    if not transcription.transcript.strip():
        return ProbeResult(
            providers.HERMES_XAI,
            check,
            CHECK_FAILED,
            "the sample came back as an empty transcript",
        )
    return ProbeResult(
        providers.HERMES_XAI,
        check,
        CHECK_OK,
        f"sample transcribed by provider {transcription.provider!r}",
    )


#: A literal ``exec("program", ["arg", ...])`` call in a Herdr app mod.
_EXEC_CALL = re.compile(r"""\bexec\(\s*(["'`])([^"'`]+)\1\s*,\s*\[([^\]]*)\]""")
#: One string literal inside that call's argument list.
_STRING_LITERAL = re.compile(r"""^\s*(["'`])([^"'`]*)\1\s*$""")


def _key_actions(config: object):
    """Every ``(section, key, action name)`` bound in the app's ``keys.json``.

    An action is a string (``"tab.new"``, ``"send:..."``, ``"<mod>.<command>"``)
    or an object whose ``command`` names it.
    """
    if not isinstance(config, dict):
        return
    for section, keys in config.items():
        if not isinstance(keys, dict):
            continue
        for key, action in keys.items():
            if isinstance(action, dict):
                action = action.get("command")
            if isinstance(action, str) and action.strip():
                yield section, key, action.strip()


def _mod_exec_commands(main_js: Path) -> list[str]:
    """The programs a mod runs through literal ``exec(...)`` calls, as command lines.

    Only calls whose program and every argument are string literals are
    read; anything built at run time cannot be resolved without running
    the mod, so it is left out rather than guessed.
    """
    try:
        text = main_js.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    commands = []
    for match in _EXEC_CALL.finditer(text):
        arguments = []
        for part in match.group(3).split(","):
            if not part.strip():
                continue
            literal = _STRING_LITERAL.match(part)
            if literal is None:
                break
            arguments.append(literal.group(2))
        else:
            commands.append(shlex.join([match.group(2), *arguments]))
    return commands


def probe_keybinding(config_path: Path | str | None = None) -> ProbeResult:
    """Read-only probe of the operator's Herdr-wide ``voice stop`` key.

    The Herdr app binds a key to an app command, to ``send:<text>`` (which
    types into the focused terminal), or to a mod's command; it cannot bind
    a key to a program directly. So a stop key that works from anywhere is a
    key bound to ``<mod>.<command>`` in ``keys.json`` whose mod runs the stop
    path with ``exec``. This probe reads ``keys.json``, follows each mod
    action to ``mods/<mod>/main.js`` beside it, resolves the literal
    ``exec(...)`` calls there, and reports whether one runs the stop path
    and can actually run (KTD13). It does not trace which of a mod's
    commands reaches which ``exec`` call.

    Absence — of the file, of a key, or of a runnable command — is reported
    by name; the probe never creates or repairs any Herdr configuration and
    never runs the command (R15).
    """
    check = f"Herdr app key running {KEYBINDING_MARKER!r}"
    if config_path is not None:
        path = Path(config_path).expanduser()
    else:
        path = DEFAULT_KEYBINDING_PATH.expanduser()
    try:
        raw = path.read_bytes()
    except OSError:
        return ProbeResult(
            KEYBINDING_OWNER,
            check,
            CHECK_FAILED,
            f"no readable Herdr app keys at {path}; the stop key cannot be verified",
        )
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ProbeResult(
            KEYBINDING_OWNER, check, CHECK_FAILED, f"{path} does not parse as JSON"
        )
    mods = path.parent / "mods"
    marked = []
    for section, key, action in _key_actions(config):
        if action.startswith("send:"):
            continue  # types into whichever terminal has focus; runs nothing
        mod, separator, _command = action.partition(".")
        if not separator or not mod:
            continue
        main_js = mods / mod / "main.js"
        if not main_js.is_file():
            continue  # an app command such as tab.new, not a mod
        for command in _mod_exec_commands(main_js):
            if command_names_stop_path(command):
                marked.append((section, key, mod, command))
    if not marked:
        return ProbeResult(
            KEYBINDING_OWNER,
            check,
            CHECK_FAILED,
            f"no key in {path} reaches a mod that runs {KEYBINDING_MARKER!r}; "
            "the Herdr app binds keys to app and mod commands only, so the "
            "stop key needs a mod whose command runs it with exec",
        )
    reasons = []
    for section, key, mod, command in marked:
        runnable, detail = command_is_runnable(command)
        if runnable:
            return ProbeResult(
                KEYBINDING_OWNER,
                check,
                CHECK_OK,
                f"key {key!r} ({section}) reaches mod {mod!r}: {detail}",
            )
        reasons.append(detail)
    return ProbeResult(
        KEYBINDING_OWNER,
        check,
        CHECK_FAILED,
        "a key reaches the stop path but cannot run it: " + "; ".join(reasons),
    )


def command_names_stop_path(command: str) -> bool:
    """Whether a binding command invokes the package's stop path, in either form.

    Two spellings reach the same stop, and a probe that knew only one would be
    wrong in a different direction each time:

    - ``voice stop`` -- through the launcher. The documented form, because it is
      the only one that survives a Claude plugin version bump.
    - ``... voice_cli.py ... stop`` -- straight at the package CLI. Legitimate,
      and pinned to a versioned install directory, so it goes stale on update.

    Matching only the first would report a working direct binding as absent.
    """
    if KEYBINDING_MARKER in command:
        return True
    return KEYBINDING_CLI in command and "stop" in command.split()


def command_is_runnable(command: str) -> tuple[bool, str]:
    """Whether a configured keybinding command could actually execute.

    Containing the marker only proves the operator *meant* the stop path. It
    does not prove anything runs, and the two came apart in practice: the
    documented binding was ``voice stop`` while no ``voice`` existed on
    ``PATH``, so the binding parsed, the key worked, and nothing happened. A
    probe that reported that as healthy is worse than no probe, because it
    retires the operator's own suspicion.

    Two things are checked, and neither executes the command -- a preflight that
    fires a stop as a side effect of asking whether a stop is possible would be
    its own defect:

    1. The program resolves: a bare name is looked up on ``PATH``; a path is
       checked for existence and the executable bit.
    2. Every script argument that names a ``.py`` file exists. This is what
       catches an interpreter invocation whose script path went stale --
       ``python3`` resolves perfectly well while the script beside it does not.

    Returns the verdict and the sentence the report shows either way.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False, f"{command!r} does not parse as a shell command"
    if not tokens:
        return False, "the keybinding command is empty"

    program, *arguments = tokens
    if os.sep in program or program.startswith("~"):
        resolved = Path(program).expanduser()
        if not resolved.is_file():
            return False, f"{program!r} does not exist"
        if not os.access(resolved, os.X_OK):
            return False, f"{program!r} is present but not executable"
        located = str(resolved)
    else:
        found = shutil.which(program)
        if found is None:
            return False, f"{program!r} is not on PATH"
        located = found

    for argument in arguments:
        if not argument.endswith(".py"):
            continue
        script = Path(argument).expanduser()
        if not script.is_file():
            return False, f"{program!r} resolves but its script {argument!r} does not exist"

    return True, f"{KEYBINDING_MARKER!r} runs {located}"


def probe_executable(owner: str, stated_path: str) -> ProbeResult:
    """One operator-supplied executable, checked at its stated path."""
    check = "executable present"
    path = Path(stated_path).expanduser()
    if not path.is_file():
        return ProbeResult(owner, check, CHECK_FAILED, f"missing at {path}")
    if not os.access(path, os.X_OK):
        return ProbeResult(
            owner, check, CHECK_FAILED, f"present at {path} but not executable"
        )
    return ProbeResult(owner, check, CHECK_OK, f"present at {path}")


def run_all(
    *,
    open_url: Callable = _default_open,
    keybinding_path: Path | str | None = None,
    capture_path: str | None = None,
    playback_path: str | None = None,
) -> list[ProbeResult]:
    """Every probe, in fixed order; one provider's failure never skips another.

    Degradation is named, never silent: a check that cannot run reports
    ``not-run`` with the missing prerequisite it depends on.
    """
    results: list[ProbeResult] = []
    synthesis_check = f"POST {SPEECH_PATH} sample synthesis"

    # --- voice-forge: settings, health, voice id, one real short synthesis.
    sample_bytes: bytes | None = None
    try:
        forge_base = settings.forge_base_url()
        forge_voice = settings.forge_voice_id()
    except settings.SettingsRefusal as refusal:
        detail = f"missing prerequisite: {refusal}"
        results.append(
            ProbeResult(providers.VOICE_FORGE, "settings", CHECK_FAILED, detail)
        )
        for skipped in (f"GET {HEALTH_PATH}", f"GET {VOICES_PATH}", synthesis_check):
            results.append(
                ProbeResult(providers.VOICE_FORGE, skipped, CHECK_NOT_RUN, detail)
            )
    else:
        health = probe_forge_health(forge_base, open_url=open_url)
        results.append(health)
        voices = probe_forge_voice_id(forge_base, forge_voice, open_url=open_url)
        results.append(voices)
        if health.status != CHECK_OK or voices.status != CHECK_OK:
            results.append(
                ProbeResult(
                    providers.VOICE_FORGE,
                    synthesis_check,
                    CHECK_NOT_RUN,
                    "the voice-forge probes above did not pass",
                )
            )
        else:
            try:
                sample_bytes = synthesize_sample(
                    forge_base, forge_voice, open_url=open_url
                )
                results.append(
                    ProbeResult(
                        providers.VOICE_FORGE,
                        synthesis_check,
                        CHECK_OK,
                        "one short real synthesis succeeded",
                    )
                )
            except providers.ProviderRefusal as refusal:
                results.append(
                    ProbeResult(
                        providers.VOICE_FORGE, synthesis_check, CHECK_FAILED, refusal.reason
                    )
                )

    # --- hermes-xai: health, session token, profile, sample round trip.
    token: str | None = None
    sample_check = f"sample round trip via POST {transcribe.TRANSCRIBE_PATH}"
    try:
        hermes_base = settings.hermes_base_url()
        hermes_profile = settings.hermes_profile()
    except settings.SettingsRefusal as refusal:
        detail = f"missing prerequisite: {refusal}"
        results.append(
            ProbeResult(providers.HERMES_XAI, "settings", CHECK_FAILED, detail)
        )
        for skipped in (
            f"GET {HERMES_HEALTH_PATH}",
            "session token from the root page",
            f"GET {HERMES_PROFILES_PATH}",
            sample_check,
        ):
            results.append(
                ProbeResult(providers.HERMES_XAI, skipped, CHECK_NOT_RUN, detail)
            )
    else:
        results.append(probe_hermes_health(hermes_base, open_url=open_url))
        try:
            token = fetch_session_token(hermes_base, open_url=open_url)
            results.append(
                ProbeResult(
                    providers.HERMES_XAI,
                    "session token from the root page",
                    CHECK_OK,
                    "read into memory only; never persisted, printed, or logged",
                )
            )
        except providers.ProviderRefusal as refusal:
            results.append(
                ProbeResult(
                    providers.HERMES_XAI,
                    "session token from the root page",
                    CHECK_FAILED,
                    refusal.reason,
                )
            )
        if token is None:
            results.append(
                ProbeResult(
                    providers.HERMES_XAI,
                    f"GET {HERMES_PROFILES_PATH}",
                    CHECK_NOT_RUN,
                    "no session token",
                )
            )
        else:
            results.append(
                probe_hermes_profile(
                    hermes_base, hermes_profile, token, open_url=open_url
                )
            )
        if sample_bytes is None:
            results.append(
                ProbeResult(
                    providers.HERMES_XAI,
                    sample_check,
                    CHECK_NOT_RUN,
                    "voice-forge sample synthesis unavailable",
                )
            )
        elif token is None:
            results.append(
                ProbeResult(
                    providers.HERMES_XAI, sample_check, CHECK_NOT_RUN, "no session token"
                )
            )
        else:
            results.append(probe_sample_round_trip(sample_bytes, open_url=open_url))

    # --- the keybinding and the operator-supplied executables.
    results.append(probe_keybinding(keybinding_path))
    executables = (
        ("capture-bin", capture_path, settings.capture_bin),
        ("playback-bin", playback_path, settings.playback_bin),
    )
    for owner, stated, resolve in executables:
        try:
            path = stated if stated is not None else resolve()
            results.append(probe_executable(owner, path))
        except settings.SettingsRefusal as refusal:
            results.append(
                ProbeResult(
                    owner,
                    "executable present",
                    CHECK_FAILED,
                    f"missing prerequisite: {refusal}",
                )
            )
    return results


def format_report(results: Sequence[ProbeResult]) -> str:
    """The operator-facing report; it never carries a credential."""
    lines = ["voice preflight"]
    for result in results:
        line = f"  {result.status:<8} {result.label}"
        if result.detail:
            line += f" — {result.detail}"
        lines.append(line)
    counts = Counter(result.status for result in results)
    failed = counts.get(CHECK_FAILED, 0)
    not_run = counts.get(CHECK_NOT_RUN, 0)
    verdict = "pass" if failed == 0 and not_run == 0 else "fail"
    lines.append(
        f"verdict: {counts.get(CHECK_OK, 0)} ok, {failed} failed, "
        f"{not_run} not-run — {verdict}"
    )
    return "\n".join(lines)


def main(
    *,
    open_url: Callable = _default_open,
    keybinding_path: Path | str | None = None,
    capture_path: str | None = None,
    playback_path: str | None = None,
) -> int:
    """Run every probe, print the report, and answer with the verdict."""
    results = run_all(
        open_url=open_url,
        keybinding_path=keybinding_path,
        capture_path=capture_path,
        playback_path=playback_path,
    )
    print(format_report(results))
    return 0 if all(result.status == CHECK_OK for result in results) else 1
