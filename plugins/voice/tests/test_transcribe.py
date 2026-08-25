"""Tests for the relay transcription path (KTD9; R23, R25, R26, R27, R31).

Every request goes to an injected opener seam, so no test touches the
network. The seam records each ``urllib.request.Request`` verbatim, which is
how the wire contract — endpoint, profile parameter, data-URL body, the
in-memory session token header — is asserted without a live relay.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import providers  # noqa: E402
import settings  # noqa: E402
import transcribe  # noqa: E402

_AUDIO_BYTES = b"RIFF-inert-example-audio"
_BASE_URL = "http://127.0.0.1:8765"
_PROFILE = "mimir-engineer"
_TOKEN = "inert-session-token-1"
_REFRESHED_TOKEN = "inert-session-token-2"
_TOKEN_PAGE = (
    "<html><script>window.__HERMES_SESSION_TOKEN__ = "
    f'"{_TOKEN}";</script></html>'
).encode("utf-8")
_REFRESHED_PAGE = (
    "<html><script>window.__HERMES_SESSION_TOKEN__ = "
    f'"{_REFRESHED_TOKEN}";</script></html>'
).encode("utf-8")


def _ok_payload(
    transcript: str = "example transcript", provider: str = "xai"
) -> tuple[int, bytes]:
    body = {"transcript": transcript, "provider": provider, "ok": True}
    return 200, json.dumps(body).encode("utf-8")


def _header(request: urllib.request.Request, name: str) -> str | None:
    """Read a request header case-insensitively.

    ``urllib`` normalizes constructor-supplied header names, and the exact
    normalized form differs across interpreters, so a case-insensitive match
    keeps the assertion stable on every supported Python.
    """
    lowered = name.lower()
    for key, value in request.headers.items():
        if key.lower() == lowered:
            return value
    return None


class _OpenerSeam:
    """Replays canned relay answers and records every request and timeout."""

    def __init__(self, answers) -> None:
        self.answers = list(answers)
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.answers:
            raise AssertionError("an unexpected request was issued")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class TranscribeTestCase(unittest.TestCase):
    """A controlled state directory, acceptance settings, and a wav fixture."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.state_dir = Path(self._temp.name)
        env = {
            settings.STATE_DIR: str(self.state_dir),
            settings.HERMES_BASE_URL: _BASE_URL,
            settings.HERMES_PROFILE: _PROFILE,
        }
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_wav(self, payload: bytes = _AUDIO_BYTES) -> Path:
        wav_path = self.state_dir / "capture-example.wav"
        wav_path.write_bytes(payload)
        return wav_path

    def remaining_files(self) -> list[Path]:
        return sorted(path for path in self.state_dir.rglob("*") if path.is_file())


class RequestShapeTests(TranscribeTestCase):
    """The consumed wire contract: endpoint, profile, data-URL body, header."""

    def test_the_request_posts_a_data_url_body_to_the_transcribe_endpoint(
        self,
    ) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _ok_payload()])
        result = transcribe.transcribe(wav, open_url=opener)
        page_request, post_request = opener.requests
        self.assertEqual(page_request.full_url, _BASE_URL + "/")
        self.assertEqual(page_request.get_method(), "GET")
        self.assertIsInstance(post_request, urllib.request.Request)
        self.assertEqual(
            post_request.full_url,
            _BASE_URL + "/api/audio/transcribe?profile=" + _PROFILE,
        )
        self.assertEqual(post_request.get_method(), "POST")
        body = json.loads(post_request.data.decode("utf-8"))
        self.assertEqual(set(body), {"data_url"})
        expected = "data:audio/wav;base64," + base64.b64encode(_AUDIO_BYTES).decode(
            "ascii"
        )
        self.assertEqual(body["data_url"], expected)
        for invented in ("audio", "file", "content"):
            with self.subTest(field=invented):
                self.assertNotIn(invented, body)
        self.assertEqual(result.transcript, "example transcript")
        self.assertEqual(result.provider, "xai")

    def test_the_in_memory_token_rides_as_the_session_header(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _ok_payload()])
        transcribe.transcribe(wav, open_url=opener)
        post_request = opener.requests[1]
        self.assertEqual(_header(post_request, "X-Hermes-Session-Token"), _TOKEN)

    def test_both_calls_carry_bounded_deadlines(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _ok_payload()])
        transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(
            opener.timeouts,
            [
                transcribe.TOKEN_PAGE_TIMEOUT_SECONDS,
                transcribe.TRANSCRIBE_TIMEOUT_SECONDS,
            ],
        )
        for timeout in opener.timeouts:
            self.assertGreater(timeout, 0)


class TokenTests(TranscribeTestCase):
    """The session token comes from the root page and stays in memory."""

    def test_a_root_page_without_a_token_is_refused_and_posts_nothing(
        self,
    ) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, b"<html>no token here</html>")])
        with self.assertRaises(providers.ProviderRefusal) as caught:
            transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(caught.exception.provider, providers.HERMES_XAI)
        self.assertIn("did not carry a session token", caught.exception.reason)
        self.assertEqual(len(opener.requests), 1, "no transcription POSTs without a token")

    def test_a_non_success_root_page_is_refused_by_name(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(503, b"unavailable")])
        with self.assertRaises(providers.ProviderRefusal):
            transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(len(opener.requests), 1)


class RetryTests(TranscribeTestCase):
    """Exactly one refresh and one retry on 401 — never a loop."""

    def test_a_401_triggers_exactly_one_refresh_and_one_retry(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam(
            [(200, _TOKEN_PAGE), (401, b""), (200, _REFRESHED_PAGE), _ok_payload()]
        )
        result = transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(result.transcript, "example transcript")
        self.assertEqual(len(opener.requests), 4)
        first_post, retry_post = opener.requests[1], opener.requests[3]
        self.assertEqual(_header(first_post, "X-Hermes-Session-Token"), _TOKEN)
        self.assertEqual(
            _header(retry_post, "X-Hermes-Session-Token"), _REFRESHED_TOKEN
        )

    def test_a_second_401_after_the_single_retry_fails_by_name_not_a_loop(
        self,
    ) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam(
            [(200, _TOKEN_PAGE), (401, b""), (200, _REFRESHED_PAGE), (401, b"")]
        )
        with self.assertRaises(providers.ProviderRefusal) as caught:
            transcribe.transcribe(wav, open_url=opener)
        self.assertIn("never retries in a loop", caught.exception.reason)
        self.assertEqual(len(opener.requests), 4, "one refresh, one retry, then refusal")


class RefusalTests(TranscribeTestCase):
    """Named refusals; nothing ever substitutes for the declared provider."""

    def test_an_unreachable_relay_is_refused_by_name(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([urllib.error.URLError("connection refused")])
        with self.assertRaises(providers.ProviderRefusal) as caught:
            transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(caught.exception.provider, providers.HERMES_XAI)
        self.assertIn("unreachable", caught.exception.reason)

    def test_an_unexpected_provider_is_refused_and_nothing_substitutes(
        self,
    ) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam(
            [(200, _TOKEN_PAGE), _ok_payload(provider="another-provider")]
        )
        with self.assertRaises(providers.ProviderRefusal) as caught:
            transcribe.transcribe(wav, open_url=opener)
        self.assertIn("another-provider", caught.exception.reason)

    def test_a_response_without_a_transcript_is_refused(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), (200, b'{"provider": "xai"}')])
        with self.assertRaises(providers.ProviderRefusal) as caught:
            transcribe.transcribe(wav, open_url=opener)
        self.assertIn("no transcript", caught.exception.reason)

    def test_a_non_success_status_is_refused_by_name(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), (500, b"relay failure")])
        with self.assertRaises(providers.ProviderRefusal) as caught:
            transcribe.transcribe(wav, open_url=opener)
        self.assertIn("HTTP 500", caught.exception.reason)

    def test_a_non_json_answer_is_refused_by_name(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), (200, b"<html>not json</html>")])
        with self.assertRaises(providers.ProviderRefusal):
            transcribe.transcribe(wav, open_url=opener)

    def test_a_missing_audio_file_is_refused_before_any_request(self) -> None:
        opener = _OpenerSeam([])
        with self.assertRaises(providers.ProviderRefusal) as caught:
            transcribe.transcribe(self.state_dir / "capture-missing.wav", open_url=opener)
        self.assertIn("missing", caught.exception.reason)
        self.assertEqual(len(opener.requests), 0)

    def test_an_empty_transcript_is_consumed_not_refused(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _ok_payload(transcript="")])
        result = transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(result.transcript, "")

    def test_the_ok_field_is_not_part_of_the_consumed_contract(self) -> None:
        wav = self.write_wav()
        payload = json.dumps(
            {"transcript": "example transcript", "provider": "xai"}
        ).encode("utf-8")
        opener = _OpenerSeam([(200, _TOKEN_PAGE), (200, payload)])
        result = transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(result.transcript, "example transcript")


class RetentionAndPrivacyTests(TranscribeTestCase):
    """Ephemeral retention (R25) and the no-record, no-egress posture (R26, R27)."""

    def test_retention_the_audio_is_deleted_after_success(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _ok_payload()])
        transcribe.transcribe(wav, open_url=opener)
        self.assertFalse(wav.exists())

    def test_retention_the_audio_is_deleted_after_failure(self) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam(
            [(200, _TOKEN_PAGE), urllib.error.URLError("connection refused")]
        )
        with self.assertRaises(providers.ProviderRefusal):
            transcribe.transcribe(wav, open_url=opener)
        self.assertFalse(wav.exists())

    def test_nothing_is_left_behind_no_transcript_file_and_no_token_on_disk(
        self,
    ) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _ok_payload()])
        result = transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(result.transcript, "example transcript")
        leftovers = self.remaining_files()
        self.assertEqual(
            leftovers,
            [],
            "the transcript comes back in memory; no transcript file, no "
            "token file, and no other residue anywhere under the state dir",
        )

    def test_a_successful_run_emits_exactly_two_requests_and_nothing_else(
        self,
    ) -> None:
        wav = self.write_wav()
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _ok_payload()])
        transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(
            len(opener.requests),
            2,
            "the root page and the transcription POST; nothing else is "
            "emitted about the call, to anyone, anywhere",
        )


class BoundaryTests(TranscribeTestCase):
    """The credential boundary and the standard-library floor, by construction."""

    def test_the_module_imports_no_relay_code_and_no_http_dependency(
        self,
    ) -> None:
        source = inspect.getsource(transcribe)
        for forbidden in (
            "import hermes",
            "from hermes",
            "import requests",
            "import httpx",
            "import subprocess",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_module_spawns_nothing_and_never_reads_a_credential_store(
        self,
    ) -> None:
        source = inspect.getsource(transcribe)
        self.assertNotIn("subprocess", source)
        for forbidden in ("auth.json", "XAI_API_KEY"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
