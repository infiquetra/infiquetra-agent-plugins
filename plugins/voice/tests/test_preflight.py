"""Tests for voice preflight (R14, R15, R22, R23; KTD13, KTD15).

Every seam is injected per KTD12: HTTP through the opener seam, the
keybinding config path and the executables through path parameters. No
test touches the network, writes any Herdr configuration, or spawns a
platform binary. Fixture values are inert.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import preflight  # noqa: E402
import providers  # noqa: E402

FORGE_BASE = "http://forge.voice.example.invalid:8080"
FORGE_VOICE_ID = "example-voice"
HERMES_BASE = "http://hermes.relay.example.invalid:8765"
HERMES_PROFILE = "mimir-engineer"

SESSION_TOKEN = "inert-session-token"
ROOT_PAGE_WITH_TOKEN = (
    "<html><script>window.__HERMES_SESSION_TOKEN__ = '"
    + SESSION_TOKEN
    + "';</script></html>"
).encode("utf-8")
ROOT_PAGE_WITHOUT_TOKEN = b"<html><body>no token here</body></html>"

# The deployed Voice Forge v0.3.0 /health document (review F05): an ``ok``
# flag plus backend bookkeeping — no ``status`` key, no ``backend`` member.
HEALTHY_FORGE_HEALTH = json.dumps(
    {
        "ok": True,
        "version": "0.3.0",
        "registry_dir": "example-registry",
        "voices_count": 2,
        "backends_available": ["example-backend"],
        "backends_loaded": ["example-backend"],
    }
).encode("utf-8")
VOICES_LISTED = json.dumps(
    {"voices": [{"id": FORGE_VOICE_ID}, {"id": "another-voice"}]}
).encode("utf-8")
SAMPLE_AUDIO = b"RIFF-inert-sample-bytes"
HERMES_HEALTH = json.dumps(
    {"version": "0.20.4", "auth_required": False}
).encode("utf-8")
# The deployed relay v0.20.4 /api/profiles entry shape (review F06): no
# ``stt`` surface — ``provider`` is the profile's LLM provider, and
# ``gateway_running``, ``model``, ``path``, ``skill_count`` and similar
# carry its state. The speech-to-text proof is the sample round trip.
PROFILES_LISTED = json.dumps(
    {
        "profiles": {
            HERMES_PROFILE: {
                "description": "example profile",
                "display_name": "Example Profile",
                "gateway_running": True,
                "model": "example-model",
                "name": HERMES_PROFILE,
                "path": "example-profile-path",
                "provider": "xai",
                "skill_count": 3,
            }
        }
    }
).encode("utf-8")
SAMPLE_TRANSCRIPTION = json.dumps(
    {"transcript": "voice preflight sample", "provider": "xai"}
).encode("utf-8")

GOOD_KEYBINDING_TOML = (
    "[[keys.command]]\n"
    'key = "f9"\n'
    'command = "voice stop"\n'
    'description = "stop voice playback"\n'
)
OTHER_KEYBINDING_TOML = (
    "[[keys.command]]\n" 'key = "f9"\n' 'command = "something else"\n'
)


class _RouteTable:
    """An open_url seam routing (method, path) to canned answers.

    A route value is ``(status, body)`` or an exception to raise. An
    unrouted request raises, so an unexpected call is a test failure, and
    every request is recorded for assertions.
    """

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: list = []

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        parsed = urllib.parse.urlsplit(request.full_url)
        key = (request.get_method(), parsed.path)
        if key not in self.routes:
            raise AssertionError(f"unexpected request during preflight: {key}")
        response = self.routes[key]
        if isinstance(response, Exception):
            raise response
        return response

    def paths_requested(self) -> list[str]:
        return [
            urllib.parse.urlsplit(request.full_url).path
            for request in self.requests
        ]


def _happy_routes() -> dict:
    return {
        ("GET", "/health"): (200, HEALTHY_FORGE_HEALTH),
        ("GET", "/v1/audio/voices"): (200, VOICES_LISTED),
        ("POST", "/v1/audio/speech"): (200, SAMPLE_AUDIO),
        ("GET", "/api/health"): (200, HERMES_HEALTH),
        ("GET", "/"): (200, ROOT_PAGE_WITH_TOKEN),
        ("GET", "/api/profiles"): (200, PROFILES_LISTED),
        ("POST", "/api/audio/transcribe"): (200, SAMPLE_TRANSCRIPTION),
    }


class PreflightTestBase(unittest.TestCase):
    """Shared fixture: inert settings, a temp state dir, and real paths."""

    def setUp(self) -> None:
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state_dir = Path(state.name)
        self.config_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.config_dir.cleanup)
        self.bin_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin_dir.cleanup)
        self.keybinding_path = Path(self.config_dir.name) / "config.toml"
        self.keybinding_path.write_text(GOOD_KEYBINDING_TOML, encoding="utf-8")
        self.capture_bin = Path(self.bin_dir.name) / "capture-bin"
        self.playback_bin = Path(self.bin_dir.name) / "playback-bin"
        for binary in (self.capture_bin, self.playback_bin):
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
        env = mock.patch.dict(
            os.environ,
            {
                "VOICE_FORGE_BASE_URL": FORGE_BASE,
                "VOICE_FORGE_VOICE_ID": FORGE_VOICE_ID,
                "VOICE_HERMES_BASE_URL": HERMES_BASE,
                "VOICE_HERMES_PROFILE": HERMES_PROFILE,
                "VOICE_STATE_DIR": str(self.state_dir),
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def run_all(self, seam) -> list:
        return preflight.run_all(
            open_url=seam,
            keybinding_path=self.keybinding_path,
            capture_path=str(self.capture_bin),
            playback_path=str(self.playback_bin),
        )

    def result_for(self, results, owner: str, check_substring: str):
        matches = [
            result
            for result in results
            if result.owner == owner and check_substring in result.check
        ]
        self.assertEqual(
            len(matches), 1, f"expected exactly one {owner} {check_substring!r} result"
        )
        return matches[0]


class VoiceForgeProbeTests(PreflightTestBase):
    def test_missing_forge_settings_fail_by_name_and_skip_nothing_else(self) -> None:
        seam = _RouteTable(_happy_routes())
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("VOICE_FORGE_BASE_URL", None)
            results = self.run_all(seam)
        settings_result = self.result_for(results, providers.VOICE_FORGE, "settings")
        self.assertEqual(settings_result.status, preflight.CHECK_FAILED)
        self.assertIn("VOICE_FORGE_BASE_URL", settings_result.detail)
        forge_statuses = {
            result.status
            for result in results
            if result.owner == providers.VOICE_FORGE
        }
        self.assertNotIn(preflight.CHECK_OK, forge_statuses)
        # A forge failure never skips the hermes probes (R22, no coupling).
        hermes_health = self.result_for(
            results, providers.HERMES_XAI, "/api/health"
        )
        self.assertEqual(hermes_health.status, preflight.CHECK_OK)

    def test_the_live_health_document_passes(self) -> None:
        # The deployed v0.3.0 document itself is the contract (review F05).
        seam = _RouteTable({("GET", "/health"): (200, HEALTHY_FORGE_HEALTH)})
        result = preflight.probe_forge_health(FORGE_BASE, open_url=seam)
        self.assertEqual(result.status, preflight.CHECK_OK)

    def test_a_loaded_backend_count_passes(self) -> None:
        seam = _RouteTable({("GET", "/health"): (200, json.dumps(
            {"ok": True, "version": "0.3.0", "voices_count": 2,
             "backends_available": 1, "backends_loaded": 1}
        ).encode("utf-8"))})
        result = preflight.probe_forge_health(FORGE_BASE, open_url=seam)
        self.assertEqual(result.status, preflight.CHECK_OK)

    def test_healthy_process_without_a_loaded_backend_fails(self) -> None:
        seam = _RouteTable({("GET", "/health"): (200, json.dumps(
            {"ok": True, "version": "0.3.0", "voices_count": 0,
             "backends_available": [], "backends_loaded": []}
        ).encode("utf-8"))})
        result = preflight.probe_forge_health(FORGE_BASE, open_url=seam)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("no loaded backend", result.detail)

    def test_ok_false_fails_by_name(self) -> None:
        seam = _RouteTable({("GET", "/health"): (200, json.dumps(
            {"ok": False, "version": "0.3.0", "backends_loaded": ["engine"]}
        ).encode("utf-8"))})
        result = preflight.probe_forge_health(FORGE_BASE, open_url=seam)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("ok=False", result.detail)

    def test_an_answer_without_the_ok_flag_fails_by_name(self) -> None:
        seam = _RouteTable({("GET", "/health"): (200, json.dumps(
            {"version": "0.3.0", "backends_loaded": ["engine"]}
        ).encode("utf-8"))})
        result = preflight.probe_forge_health(FORGE_BASE, open_url=seam)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("not true", result.detail)

    def test_a_zero_loaded_backend_count_fails(self) -> None:
        seam = _RouteTable({("GET", "/health"): (200, json.dumps(
            {"ok": True, "version": "0.3.0", "backends_loaded": 0}
        ).encode("utf-8"))})
        result = preflight.probe_forge_health(FORGE_BASE, open_url=seam)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("no loaded backend", result.detail)

    def test_unreachable_forge_fails_by_name(self) -> None:
        seam = _RouteTable(
            {("GET", "/health"): urllib.error.URLError("connection refused")}
        )
        result = preflight.probe_forge_health(FORGE_BASE, open_url=seam)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("unreachable", result.detail)

    def test_missing_voice_id_fails_by_name(self) -> None:
        seam = _RouteTable({("GET", "/v1/audio/voices"): (200, json.dumps(
            {"voices": [{"id": "another-voice"}]}
        ).encode("utf-8"))})
        result = preflight.probe_forge_voice_id(
            FORGE_BASE, FORGE_VOICE_ID, open_url=seam
        )
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn(FORGE_VOICE_ID, result.detail)

    def test_voice_id_present_passes(self) -> None:
        seam = _RouteTable(
            {("GET", "/v1/audio/voices"): (200, VOICES_LISTED)}
        )
        result = preflight.probe_forge_voice_id(
            FORGE_BASE, FORGE_VOICE_ID, open_url=seam
        )
        self.assertEqual(result.status, preflight.CHECK_OK)

    def test_failed_synthesis_is_named_and_hermes_probes_still_run(self) -> None:
        routes = _happy_routes()
        routes[("POST", "/v1/audio/speech")] = (500, b"")
        seam = _RouteTable(routes)
        results = self.run_all(seam)
        synthesis = self.result_for(results, providers.VOICE_FORGE, "sample synthesis")
        self.assertEqual(synthesis.status, preflight.CHECK_FAILED)
        sample = self.result_for(results, providers.HERMES_XAI, "sample round trip")
        self.assertEqual(sample.status, preflight.CHECK_NOT_RUN)
        self.assertIn("synthesis", sample.detail)
        # The token, profile, and health probes still ran (KTD15).
        token_result = self.result_for(results, providers.HERMES_XAI, "session token")
        profile_result = self.result_for(results, providers.HERMES_XAI, "/api/profiles")
        self.assertEqual(token_result.status, preflight.CHECK_OK)
        self.assertEqual(profile_result.status, preflight.CHECK_OK)


class HermesProbeTests(PreflightTestBase):
    def test_relay_unreachable_fails_by_name(self) -> None:
        seam = _RouteTable(
            {("GET", "/api/health"): urllib.error.URLError("connection refused")}
        )
        result = preflight.probe_hermes_health(HERMES_BASE, open_url=seam)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("unreachable", result.detail)

    def test_anonymous_relay_call_is_token_missing_not_healthy(self) -> None:
        # health reports auth_required: false; the root page carries no
        # token. The missing token is reported as token-missing — never
        # read as "healthy, no token needed".
        routes = _happy_routes()
        routes[("GET", "/")] = (200, ROOT_PAGE_WITHOUT_TOKEN)
        seam = _RouteTable(routes)
        results = self.run_all(seam)
        token_result = self.result_for(results, providers.HERMES_XAI, "session token")
        self.assertEqual(token_result.status, preflight.CHECK_FAILED)
        self.assertIn("token-missing", token_result.detail)
        profile_result = self.result_for(results, providers.HERMES_XAI, "/api/profiles")
        self.assertEqual(profile_result.status, preflight.CHECK_NOT_RUN)
        sample = self.result_for(results, providers.HERMES_XAI, "sample round trip")
        self.assertEqual(sample.status, preflight.CHECK_NOT_RUN)
        self.assertIn("no session token", sample.detail)

    def test_token_fetch_refusal_names_the_condition_only(self) -> None:
        seam = _RouteTable({("GET", "/"): (200, ROOT_PAGE_WITHOUT_TOKEN)})
        with self.assertRaises(providers.ProviderRefusal) as caught:
            preflight.fetch_session_token(HERMES_BASE, open_url=seam)
        self.assertIn("token-missing", str(caught.exception))
        # The refusal never repeats the page that carries the token.
        self.assertNotIn("no token here", str(caught.exception))

    def test_token_is_in_memory_only_never_url_report_or_disk(self) -> None:
        seam = _RouteTable(_happy_routes())
        results = self.run_all(seam)
        report = preflight.format_report(results)
        self.assertNotIn(SESSION_TOKEN, report)
        profile_requests = [
            request
            for request in seam.requests
            if urllib.parse.urlsplit(request.full_url).path == "/api/profiles"
        ]
        self.assertEqual(len(profile_requests), 1)
        # The token rides the header only — never the URL. ``Request``
        # normalizes header keys, so the lookup uses the normalized name.
        self.assertEqual(
            profile_requests[0].get_header("X-hermes-session-token"),
            SESSION_TOKEN,
        )
        for request in seam.requests:
            self.assertNotIn(SESSION_TOKEN, request.full_url)
        for path in self.state_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(
                    SESSION_TOKEN, path.read_text(encoding="utf-8", errors="replace")
                )

    def test_profile_absent_fails_by_name(self) -> None:
        seam = _RouteTable({("GET", "/api/profiles"): (200, json.dumps(
            {"profiles": {"someone-else": {
                "name": "someone-else",
                "provider": "xai",
                "model": "example-model",
            }}}
        ).encode("utf-8"))})
        result = preflight.probe_hermes_profile(
            HERMES_BASE, HERMES_PROFILE, SESSION_TOKEN, open_url=seam
        )
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn(HERMES_PROFILE, result.detail)

    def test_the_live_profile_document_passes(self) -> None:
        # The deployed v0.20.4 entry shape — no ``stt`` surface — is the
        # contract (review F06); the STT proof is the sample round trip.
        seam = _RouteTable({("GET", "/api/profiles"): (200, PROFILES_LISTED)})
        result = preflight.probe_hermes_profile(
            HERMES_BASE, HERMES_PROFILE, SESSION_TOKEN, open_url=seam
        )
        self.assertEqual(result.status, preflight.CHECK_OK)

    def test_a_profile_without_any_stt_surface_passes(self) -> None:
        seam = _RouteTable({("GET", "/api/profiles"): (200, json.dumps(
            {"profiles": {HERMES_PROFILE: {}}}
        ).encode("utf-8"))})
        result = preflight.probe_hermes_profile(
            HERMES_BASE, HERMES_PROFILE, SESSION_TOKEN, open_url=seam
        )
        self.assertEqual(result.status, preflight.CHECK_OK)

    def test_the_probe_does_not_assert_the_profile_llm_provider(self) -> None:
        # A profile's ``provider`` is its LLM provider, never the
        # speech-to-text resolution; the probe does not assert it.
        seam = _RouteTable({("GET", "/api/profiles"): (200, json.dumps(
            {"profiles": {HERMES_PROFILE: {
                "name": HERMES_PROFILE,
                "provider": "openai",
            }}}
        ).encode("utf-8"))})
        result = preflight.probe_hermes_profile(
            HERMES_BASE, HERMES_PROFILE, SESSION_TOKEN, open_url=seam
        )
        self.assertEqual(result.status, preflight.CHECK_OK)

    def test_rejected_token_fails_by_name_without_a_loop(self) -> None:
        seam = _RouteTable({("GET", "/api/profiles"): (401, b"")})
        result = preflight.probe_hermes_profile(
            HERMES_BASE, HERMES_PROFILE, SESSION_TOKEN, open_url=seam
        )
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("rejected the session token", result.detail)
        self.assertEqual(len(seam.requests), 1)


class SampleRoundTripTests(PreflightTestBase):
    def test_full_preflight_passes_end_to_end(self) -> None:
        seam = _RouteTable(_happy_routes())
        results = self.run_all(seam)
        statuses = {result.status for result in results}
        self.assertEqual(statuses, {preflight.CHECK_OK})
        # The KTD15 sample file is ephemeral like every other audio file.
        leftovers = list(self.state_dir.glob("preflight-sample-*"))
        self.assertEqual(leftovers, [])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = preflight.main(
                open_url=seam,
                keybinding_path=self.keybinding_path,
                capture_path=str(self.capture_bin),
                playback_path=str(self.playback_bin),
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("pass", buffer.getvalue())

    def test_empty_transcript_fails_by_name(self) -> None:
        routes = _happy_routes()
        routes[("POST", "/api/audio/transcribe")] = (
            200,
            json.dumps({"transcript": "", "provider": "xai"}).encode("utf-8"),
        )
        seam = _RouteTable(routes)
        results = self.run_all(seam)
        sample = self.result_for(results, providers.HERMES_XAI, "sample round trip")
        self.assertEqual(sample.status, preflight.CHECK_FAILED)
        self.assertIn("empty transcript", sample.detail)

    def test_the_relay_silence_document_fails_as_nothing_to_deliver(
        self,
    ) -> None:
        # The live silence mapping (review F07): empty transcript, absent
        # provider. The round trip names it nothing to deliver — never a
        # substitution.
        routes = _happy_routes()
        routes[("POST", "/api/audio/transcribe")] = (
            200,
            json.dumps(
                {"ok": True, "transcript": "", "provider": None}
            ).encode("utf-8"),
        )
        seam = _RouteTable(routes)
        results = self.run_all(seam)
        sample = self.result_for(results, providers.HERMES_XAI, "sample round trip")
        self.assertEqual(sample.status, preflight.CHECK_FAILED)
        self.assertIn("nothing to deliver", sample.detail)

    def test_sample_provider_mismatch_fails_by_name(self) -> None:
        routes = _happy_routes()
        routes[("POST", "/api/audio/transcribe")] = (
            200,
            json.dumps(
                {"transcript": "voice preflight sample", "provider": "openai"}
            ).encode("utf-8"),
        )
        seam = _RouteTable(routes)
        results = self.run_all(seam)
        sample = self.result_for(results, providers.HERMES_XAI, "sample round trip")
        self.assertEqual(sample.status, preflight.CHECK_FAILED)
        self.assertIn("'openai'", sample.detail)


class KeybindingProbeTests(PreflightTestBase):
    def test_absent_config_is_reported_and_never_created(self) -> None:
        absent = Path(self.config_dir.name) / "does-not-exist.toml"
        result = preflight.probe_keybinding(absent)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("no readable herdr config", result.detail)
        self.assertFalse(absent.exists())

    def test_config_without_voice_stop_is_reported_and_never_written(self) -> None:
        self.keybinding_path.write_text(OTHER_KEYBINDING_TOML, encoding="utf-8")
        before = self.keybinding_path.read_bytes()
        result = preflight.probe_keybinding(self.keybinding_path)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("voice stop", result.detail)
        self.assertEqual(self.keybinding_path.read_bytes(), before)

    def test_config_with_voice_stop_passes(self) -> None:
        result = preflight.probe_keybinding(self.keybinding_path)
        self.assertEqual(result.status, preflight.CHECK_OK)

    def test_probe_does_not_require_a_specific_type_field(self) -> None:
        self.keybinding_path.write_text(
            "[[keys.command]]\n"
            'key = "f9"\n'
            'type = "something-else"\n'
            'command = "voice stop"\n',
            encoding="utf-8",
        )
        result = preflight.probe_keybinding(self.keybinding_path)
        self.assertEqual(result.status, preflight.CHECK_OK)

    def test_unparseable_config_is_reported_by_name(self) -> None:
        self.keybinding_path.write_text("[ not toml", encoding="utf-8")
        result = preflight.probe_keybinding(self.keybinding_path)
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("TOML", result.detail)

    def test_an_absent_keybinding_fails_the_run(self) -> None:
        self.keybinding_path.write_text(OTHER_KEYBINDING_TOML, encoding="utf-8")
        seam = _RouteTable(_happy_routes())
        results = self.run_all(seam)
        keybinding = self.result_for(results, "herdr-config", "keybinding")
        self.assertEqual(keybinding.status, preflight.CHECK_FAILED)
        self.assertFalse(all(r.status == preflight.CHECK_OK for r in results))


class ExecutableProbeTests(PreflightTestBase):
    def test_missing_capture_binary_is_reported_by_name(self) -> None:
        missing = Path(self.bin_dir.name) / "no-such-binary"
        result = preflight.probe_executable("capture-bin", str(missing))
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("missing", result.detail)
        self.assertIn(str(missing), result.detail)

    def test_present_but_not_executable_is_reported(self) -> None:
        inert = Path(self.bin_dir.name) / "not-executable"
        inert.write_text("data", encoding="utf-8")
        inert.chmod(0o644)
        result = preflight.probe_executable("playback-bin", str(inert))
        self.assertEqual(result.status, preflight.CHECK_FAILED)
        self.assertIn("not executable", result.detail)

    def test_present_executable_passes(self) -> None:
        result = preflight.probe_executable("capture-bin", str(self.capture_bin))
        self.assertEqual(result.status, preflight.CHECK_OK)


if __name__ == "__main__":
    unittest.main()
