"""Tests for the stated settings surface (KTD6, KTD1; R28).

Every scenario runs against a controlled environment: ``clear=True`` patches
make "absent" genuinely absent, so the absent-never-means-empty contract is
tested against the real distinction rather than a guess about the host.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import settings  # noqa: E402

#: Every resolver in the module, keyed by the setting it reads. The closed
#: set is exercised through its public surface, one resolver at a time.
_RESOLVERS = {
    settings.FORGE_BASE_URL: settings.forge_base_url,
    settings.FORGE_VOICE_ID: settings.forge_voice_id,
    settings.HERMES_BASE_URL: settings.hermes_base_url,
    settings.HERMES_PROFILE: settings.hermes_profile,
    settings.CAPTURE_BIN: settings.capture_bin,
    settings.PLAYBACK_BIN: settings.playback_bin,
    settings.STATE_DIR: settings.state_dir,
    settings.RETENTION: settings.retention,
    settings.HERDR_PANE_ID: settings.herdr_pane_id,
    settings.HERDR_BIN_PATH: settings.herdr_bin_path,
}


class RetentionPostureTests(unittest.TestCase):
    """The retention posture is stated, not defaulted (R28)."""

    def test_retention_is_refused_when_nobody_wrote_it_down(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(settings.SettingsRefusal) as caught:
                settings.retention()
        self.assertEqual(caught.exception.name, settings.RETENTION)

    def test_the_stated_ephemeral_posture_resolves(self) -> None:
        env = {settings.RETENTION: settings.RETENTION_EPHEMERAL}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(settings.retention(), settings.RETENTION_EPHEMERAL)

    def test_an_unknown_retention_value_is_refused_by_name(self) -> None:
        with mock.patch.dict(os.environ, {settings.RETENTION: "retain"}, clear=True):
            with self.assertRaises(settings.SettingsRefusal) as caught:
                settings.retention()
        refusal = caught.exception
        self.assertEqual(refusal.name, settings.RETENTION)
        self.assertIn("retain", refusal.reason)

    def test_the_accepted_value_is_exact_not_case_folded(self) -> None:
        env = {settings.RETENTION: settings.RETENTION_EPHEMERAL.upper()}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(settings.SettingsRefusal):
                settings.retention()


class AbsentNeverEmptyTests(unittest.TestCase):
    """Absent and empty are distinct states, and empty is never a value."""

    def test_an_empty_setting_is_refused_not_defaulted(self) -> None:
        for name, resolve in _RESOLVERS.items():
            with self.subTest(setting=name):
                with mock.patch.dict(os.environ, {name: ""}, clear=True):
                    with self.assertRaises(settings.SettingsRefusal) as caught:
                        resolve()
                refusal = caught.exception
                self.assertEqual(refusal.name, name)
                self.assertIn("empty", refusal.reason)

    def test_an_unset_setting_without_a_default_is_refused_by_name(self) -> None:
        for name, resolve in _RESOLVERS.items():
            with self.subTest(setting=name):
                with mock.patch.dict(os.environ, {}, clear=True):
                    try:
                        resolve()
                    except settings.SettingsRefusal as refusal:
                        self.assertEqual(refusal.name, name)
                        self.assertIn("not set", refusal.reason)

    def test_every_refusal_names_a_declared_setting(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            for name, resolve in _RESOLVERS.items():
                with self.subTest(setting=name):
                    try:
                        resolve()
                    except settings.SettingsRefusal as refusal:
                        self.assertIn(refusal.name, settings.SETTING_NAMES)


class ProviderSettingTests(unittest.TestCase):
    """The four provider settings resolve: Hermes defaults, Forge stated."""

    def test_hermes_settings_resolve_to_their_documented_defaults(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                settings.hermes_base_url(), "http://127.0.0.1:8765"
            )
            self.assertEqual(settings.hermes_profile(), "mimir-engineer")

    def test_hermes_settings_resolve_to_stated_values(self) -> None:
        env = {
            settings.HERMES_BASE_URL: "http://127.0.0.1:9999",
            settings.HERMES_PROFILE: "example-profile",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                settings.hermes_base_url(), "http://127.0.0.1:9999"
            )
            self.assertEqual(settings.hermes_profile(), "example-profile")

    def test_forge_settings_are_refused_by_name_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(settings.SettingsRefusal) as caught:
                settings.forge_base_url()
            self.assertEqual(caught.exception.name, "VOICE_FORGE_BASE_URL")
            with self.assertRaises(settings.SettingsRefusal) as caught:
                settings.forge_voice_id()
            self.assertEqual(caught.exception.name, "VOICE_FORGE_VOICE_ID")

    def test_forge_settings_resolve_when_stated(self) -> None:
        env = {
            settings.FORGE_BASE_URL: "http://voice-forge.internal.example",
            settings.FORGE_VOICE_ID: "example-voice",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                settings.forge_base_url(), "http://voice-forge.internal.example"
            )
            self.assertEqual(settings.forge_voice_id(), "example-voice")

    def test_executable_settings_default_and_resolve_stated(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                settings.capture_bin(), "/opt/homebrew/bin/ffmpeg"
            )
            self.assertEqual(settings.playback_bin(), "/usr/bin/afplay")
        env = {
            settings.CAPTURE_BIN: "/example/capture",
            settings.PLAYBACK_BIN: "/example/playback",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(settings.capture_bin(), "/example/capture")
            self.assertEqual(settings.playback_bin(), "/example/playback")


class StateDirTests(unittest.TestCase):
    """The state directory honours VOICE_STATE_DIR (KTD1)."""

    def test_state_dir_honours_the_setting(self) -> None:
        env = {settings.STATE_DIR: "/tmp/voice-state-example"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                settings.state_dir(), Path("/tmp/voice-state-example")
            )

    def test_state_dir_defaults_under_the_state_home(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                settings.state_dir(),
                Path("~/.local/state/voice").expanduser(),
            )


class NoSecretsTests(unittest.TestCase):
    """No setting carries a credential: the surface is closed and non-secret."""

    _CREDENTIAL_FRAGMENTS = (
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "passphrase",
        "passwd",
        "password",
        "privatekey",
        "secret",
        "token",
        "auth",
        "key",
    )

    def test_the_setting_names_form_the_closed_declared_set(self) -> None:
        self.assertEqual(
            settings.SETTING_NAMES,
            (
                "VOICE_FORGE_BASE_URL",
                "VOICE_FORGE_VOICE_ID",
                "VOICE_HERMES_BASE_URL",
                "VOICE_HERMES_PROFILE",
                "VOICE_CAPTURE_BIN",
                "VOICE_PLAYBACK_BIN",
                "VOICE_STATE_DIR",
                "VOICE_RETENTION",
                "HERDR_PANE_ID",
                "HERDR_BIN_PATH",
            ),
        )

    def test_no_setting_name_is_credential_shaped(self) -> None:
        for name in settings.SETTING_NAMES:
            normalized = "".join(
                character for character in name.lower() if character.isalnum()
            )
            for fragment in self._CREDENTIAL_FRAGMENTS:
                with self.subTest(setting=name, fragment=fragment):
                    self.assertNotIn(fragment, normalized)

    def test_settings_resolve_from_the_live_environment_each_call(self) -> None:
        with mock.patch.dict(
            os.environ, {settings.HERMES_PROFILE: "first"}, clear=True
        ):
            self.assertEqual(settings.hermes_profile(), "first")
        with mock.patch.dict(
            os.environ, {settings.HERMES_PROFILE: "second"}, clear=True
        ):
            self.assertEqual(settings.hermes_profile(), "second")


class HerdrSettingTests(unittest.TestCase):
    """The Herdr environment settings resolve stated values and carry no default (KTD9; §5)."""

    def test_herdr_settings_are_refused_by_name_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(settings.SettingsRefusal) as caught:
                settings.herdr_pane_id()
            self.assertEqual(caught.exception.name, "HERDR_PANE_ID")
            self.assertIn("not set", caught.exception.reason)

            with self.assertRaises(settings.SettingsRefusal) as caught:
                settings.herdr_bin_path()
            self.assertEqual(caught.exception.name, "HERDR_BIN_PATH")
            self.assertIn("not set", caught.exception.reason)

    def test_herdr_settings_are_refused_by_name_when_empty(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                settings.HERDR_PANE_ID: "",
                settings.HERDR_BIN_PATH: "   ",
            },
            clear=True,
        ):
            with self.assertRaises(settings.SettingsRefusal) as caught:
                settings.herdr_pane_id()
            self.assertEqual(caught.exception.name, "HERDR_PANE_ID")
            self.assertIn("empty", caught.exception.reason)

            with self.assertRaises(settings.SettingsRefusal) as caught:
                settings.herdr_bin_path()
            self.assertEqual(caught.exception.name, "HERDR_BIN_PATH")
            self.assertIn("empty", caught.exception.reason)

    def test_herdr_settings_resolve_when_stated(self) -> None:
        env = {
            settings.HERDR_PANE_ID: "w1:p2",
            settings.HERDR_BIN_PATH: "/usr/local/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(settings.herdr_pane_id(), "w1:p2")
            self.assertEqual(
                settings.herdr_bin_path(), "/usr/local/bin/herdr"
            )


if __name__ == "__main__":
    unittest.main()
