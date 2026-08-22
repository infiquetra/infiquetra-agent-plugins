"""Tests for the UniFi site-profile first-setup entrypoint.

The contract is that exactly three safe paths are offered, that the operator's
choice is remembered, and that a second invocation reads the remembered choice
back instead of asking again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIFI_SCRIPTS = ROOT / "plugins" / "unifi" / "scripts"
sys.path.insert(0, str(UNIFI_SCRIPTS))

import site_profile  # noqa: E402
import site_profile_setup  # noqa: E402

from test_site_profile import VALID_PROFILE, write_json  # noqa: E402


class SetupTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.config_path = self.root / "config" / "config.json"
        self.environ = {site_profile.CONFIG_HOME_VARIABLE: str(self.root / "config-home")}

    def subprocess_environment(self) -> dict[str, str]:
        """A child environment whose profile resolution stays inside ``self.root``.

        ``site_profile_setup.main`` reads ``os.environ``, so a child process
        otherwise inherits both rungs of the resolution order from the
        developer's shell: ``UNIFI_SITE_PROFILE`` and the configuration
        directory under ``${XDG_CONFIG_HOME:-~/.config}``. Dropping the first
        and pinning the second keeps these tests independent of whether a
        profile happens to be deployed on the machine running them.
        """
        environment = {
            key: value
            for key, value in os.environ.items()
            if key != site_profile.ENVIRONMENT_VARIABLE
        }
        environment.update(self.environ)
        return environment

    def write_profile(self, name: str = "site-profile.json", payload: object | None = None) -> Path:
        return write_json(self.root / name, VALID_PROFILE if payload is None else payload)


class PresentedPathsTest(SetupTest):
    def test_exactly_three_paths_are_offered(self) -> None:
        self.assertEqual(len(site_profile_setup.SETUP_PATHS), 3)
        self.assertEqual(len(site_profile_setup.SETUP_PATH_KEYS), 3)
        self.assertEqual(
            set(site_profile_setup.SETUP_PATH_KEYS),
            {"existing-profile", "discovery-proposal", "discovery-only"},
        )

    def test_presentation_reports_the_same_count_it_lists(self) -> None:
        report = site_profile_setup.present_paths(self.environ)
        self.assertEqual(report["path_count"], 3)
        self.assertEqual(len(report["paths"]), 3)
        self.assertFalse(report["configured"])

    def test_presentation_names_the_environment_override_and_documented_paths(self) -> None:
        report = site_profile_setup.present_paths(self.environ)
        self.assertEqual(report["environment_override"], site_profile.ENVIRONMENT_VARIABLE)
        self.assertTrue(report["config_file"].endswith("infiquetra/unifi/config.json"))
        self.assertTrue(
            report["default_profile_path"].endswith("infiquetra/unifi/site-profile.json")
        )

    def test_presentation_states_the_limits_of_running_without_a_profile(self) -> None:
        report = site_profile_setup.present_paths(self.environ)
        self.assertEqual(report["discovery_only_limits"], list(site_profile.DISCOVERY_ONLY_LIMITS))

    def test_only_one_path_requires_a_profile_path(self) -> None:
        requiring = [
            path.key for path in site_profile_setup.SETUP_PATHS if path.requires_profile_path
        ]
        self.assertEqual(requiring, ["existing-profile"])

    def test_unknown_setup_path_is_rejected_naming_the_three(self) -> None:
        with self.assertRaises(site_profile.SiteProfileError) as raised:
            site_profile_setup.setup_path("import-from-controller")
        message = str(raised.exception)
        for key in site_profile_setup.SETUP_PATH_KEYS:
            self.assertIn(key, message)


class ChoiceTest(SetupTest):
    def test_choosing_an_existing_profile_remembers_it(self) -> None:
        profile = self.write_profile()
        report = site_profile_setup.choose(
            "existing-profile", profile_path=profile, config_path=self.config_path
        )
        self.assertTrue(report["configured"])
        self.assertEqual(report["mode"], site_profile.PROFILE_MODE)
        self.assertEqual(report["site_profile_path"], str(profile))

        written = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(written["setup_path"], "existing-profile")
        self.assertEqual(written["site_profile_path"], str(profile))

        context = site_profile.load_site_context(environ={}, config_path=self.config_path)
        self.assertEqual(context.mode, site_profile.PROFILE_MODE)
        self.assertEqual(context.source, site_profile.CONFIGURED_SOURCE)

    def test_choosing_discovery_only_remembers_that_too(self) -> None:
        report = site_profile_setup.choose("discovery-only", config_path=self.config_path)
        self.assertEqual(report["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertIsNone(report["site_profile_path"])
        context = site_profile.load_site_context(environ={}, config_path=self.config_path)
        self.assertEqual(context.mode, site_profile.DISCOVERY_ONLY_MODE)

    def test_choosing_the_discovery_proposal_writes_no_profile(self) -> None:
        report = site_profile_setup.choose("discovery-proposal", config_path=self.config_path)
        self.assertEqual(report["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertIsNone(report["site_profile_path"])
        self.assertIn("discover.py", report["next_step"])
        self.assertFalse(site_profile.default_profile_path(self.environ).exists())

    def test_choosing_an_existing_profile_without_a_path_fails(self) -> None:
        with self.assertRaises(site_profile.SiteProfileError):
            site_profile_setup.choose("existing-profile", config_path=self.config_path)
        self.assertFalse(self.config_path.exists())

    def test_choosing_a_missing_profile_fails_and_remembers_nothing(self) -> None:
        with self.assertRaises(site_profile.ProfileNotFoundError):
            site_profile_setup.choose(
                "existing-profile",
                profile_path=self.root / "absent.json",
                config_path=self.config_path,
            )
        self.assertFalse(self.config_path.exists())

    def test_choosing_an_invalid_profile_fails_and_remembers_nothing(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["site"]["api_token"] = "inert-example-value"
        invalid = self.write_profile("invalid.json", payload)
        with self.assertRaises(site_profile.ProfileInvalidError):
            site_profile_setup.choose(
                "existing-profile", profile_path=invalid, config_path=self.config_path
            )
        self.assertFalse(self.config_path.exists())

    def test_a_path_that_takes_no_profile_rejects_one(self) -> None:
        profile = self.write_profile()
        with self.assertRaises(site_profile.SiteProfileError):
            site_profile_setup.choose(
                "discovery-only", profile_path=profile, config_path=self.config_path
            )


class StatusTest(SetupTest):
    def test_first_invocation_presents_the_three_paths(self) -> None:
        report = site_profile_setup.status(environ=self.environ, config_path=self.config_path)
        self.assertFalse(report["configured"])
        self.assertEqual(report["path_count"], 3)

    def test_second_invocation_reads_the_remembered_choice_back(self) -> None:
        profile = self.write_profile()
        site_profile_setup.choose(
            "existing-profile", profile_path=profile, config_path=self.config_path
        )
        report = site_profile_setup.status(environ={}, config_path=self.config_path)
        self.assertTrue(report["configured"])
        self.assertNotIn("paths", report)
        self.assertEqual(report["setup_path"], "existing-profile")
        self.assertEqual(report["mode"], site_profile.PROFILE_MODE)
        self.assertEqual(report["context"]["site_identifier"], "example-site")

    def test_remembered_path_that_no_longer_exists_is_reported_not_swallowed(self) -> None:
        profile = self.write_profile()
        site_profile_setup.choose(
            "existing-profile", profile_path=profile, config_path=self.config_path
        )
        profile.unlink()
        report = site_profile_setup.status(environ={}, config_path=self.config_path)
        self.assertTrue(report["configured"])
        self.assertEqual(report["error_type"], "ProfileNotFoundError")
        self.assertIn(str(profile), report["error"])
        self.assertNotEqual(report.get("mode"), site_profile.DISCOVERY_ONLY_MODE)


class CommandLineTest(SetupTest):
    def run_setup(self, *arguments: str) -> tuple[int, dict]:
        completed = subprocess.run(
            [sys.executable, str(UNIFI_SCRIPTS / "site_profile_setup.py"), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env=self.subprocess_environment(),
        )
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        return completed.returncode, json.loads(completed.stdout)

    def test_list_prints_exactly_three_paths(self) -> None:
        code, report = self.run_setup("--list")
        self.assertEqual(code, 0)
        self.assertEqual(report["path_count"], 3)
        self.assertEqual(len(report["paths"]), 3)

    def test_choose_then_status_does_not_ask_again(self) -> None:
        profile = self.write_profile()
        code, report = self.run_setup(
            "--choose",
            "existing-profile",
            "--profile-path",
            str(profile),
            "--config-path",
            str(self.config_path),
        )
        self.assertEqual(code, 0)
        self.assertTrue(report["configured"])

        code, report = self.run_setup("--config-path", str(self.config_path))
        self.assertEqual(code, 0)
        self.assertTrue(report["configured"])
        self.assertNotIn("paths", report)

    def test_choose_rejects_an_undeclared_fourth_path(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(UNIFI_SCRIPTS / "site_profile_setup.py"),
                "--choose",
                "import-from-controller",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=self.subprocess_environment(),
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("invalid choice", completed.stderr)

    def test_failure_is_reported_as_json_with_a_non_zero_status(self) -> None:
        code, report = self.run_setup(
            "--choose",
            "existing-profile",
            "--profile-path",
            str(self.root / "absent.json"),
            "--config-path",
            str(self.config_path),
        )
        self.assertEqual(code, 1)
        self.assertEqual(report["error_type"], "ProfileNotFoundError")


if __name__ == "__main__":
    unittest.main()
