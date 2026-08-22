"""Tests for UniFi actual-versus-intended drift reporting.

Standard library only. Drift never talks to a controller of its own; it
consumes an in-memory inventory from discovery (itself mocked) and a site
context. No test writes into the repository working tree.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIFI_SCRIPTS = ROOT / "plugins" / "unifi" / "scripts"
sys.path.insert(0, str(UNIFI_SCRIPTS))

import discover  # noqa: E402
import drift  # noqa: E402
import site_profile  # noqa: E402

from test_discover import (  # noqa: E402
    EXAMPLE_PAYLOADS,
    RecordingFixture,
    source_files,
)
from test_site_profile import VALID_PROFILE, write_json  # noqa: E402


class DriftTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.config_path = self.root / "config.json"
        self.environ = {"XDG_CONFIG_HOME": str(self.root / "config-home")}
        self.before_repo_files = source_files(ROOT)

    def tearDown(self) -> None:
        leftover = source_files(ROOT) - self.before_repo_files
        self.assertEqual(
            leftover,
            set(),
            f"drift test left files in the working tree: {leftover}",
        )

    def inventory(self, **overrides: object) -> dict:
        transport = RecordingFixture(EXAMPLE_PAYLOADS)
        result = discover.discover(
            transport, host="controller.example", site="default"
        )
        discover.assert_read_only(result.invocations)
        payload = dict(result.inventory)
        payload.update(overrides)
        return payload

    def discovery_only_context(self) -> site_profile.SiteContext:
        return site_profile.load_site_context(
            environ={}, config_path=self.config_path
        )

    def profile_context(self, payload: object | None = None) -> site_profile.SiteContext:
        path = write_json(
            self.root / "site-profile.json",
            VALID_PROFILE if payload is None else payload,
        )
        return site_profile.load_site_context(
            environ={site_profile.ENVIRONMENT_VARIABLE: str(path)},
            config_path=self.config_path,
        )


class NoProfileTest(DriftTest):
    def test_drift_with_no_profile_reports_discovery_only_and_no_findings(self) -> None:
        report = drift.report(self.inventory(), self.discovery_only_context())
        self.assertEqual(report["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["finding_count"], 0)
        self.assertEqual(report["limits"], list(site_profile.DISCOVERY_ONLY_LIMITS))
        # Actual hosts may exist; they are not findings without intended state.
        self.assertIn("example-discovered-host", report["actual_hosts"])
        self.assertEqual(report["profiled_hosts"], [])
        self.assertEqual(report["intended_policies"], [])

    def test_empty_inventory_without_a_profile_is_still_not_an_error(self) -> None:
        report = drift.report(
            discover.empty_inventory("default"), self.discovery_only_context()
        )
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["mode"], site_profile.DISCOVERY_ONLY_MODE)


class ProfiledDriftTest(DriftTest):
    def test_host_on_controller_absent_from_profile_and_policy_absent_on_controller(
        self,
    ) -> None:
        """The two findings the plan names, in one report.

        The mocked controller has ``example-discovered-host`` and no observed
        policies. The profile names a different host and an intended policy.
        """
        report = drift.report(self.inventory(), self.profile_context())
        self.assertEqual(report["mode"], site_profile.PROFILE_MODE)
        kinds = {finding["kind"] for finding in report["findings"]}
        self.assertEqual(kinds, {drift.UNPROFILED_HOST, drift.MISSING_POLICY})

        hosts = [
            finding["identifier"]
            for finding in report["findings"]
            if finding["kind"] == drift.UNPROFILED_HOST
        ]
        self.assertEqual(hosts, ["example-discovered-host"])
        self.assertNotIn("example-host", hosts)

        policies = [
            finding["identifier"]
            for finding in report["findings"]
            if finding["kind"] == drift.MISSING_POLICY
        ]
        self.assertEqual(policies, ["example-policy"])

    def test_a_profiled_host_is_not_reported_as_unprofiled(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"] = [
            {
                "kind": "host",
                "identifier": "example-discovered-host",
                "trust_role": "trusted",
            }
        ]
        payload["intended_policies"] = []
        report = drift.report(self.inventory(), self.profile_context(payload))
        self.assertEqual(
            [finding["kind"] for finding in report["findings"]],
            [],
        )

    def test_an_observed_policy_matching_the_profile_is_not_missing(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"] = [
            {
                "kind": "host",
                "identifier": "example-discovered-host",
            }
        ]
        inventory = self.inventory(policies=[{"identifier": "example-policy"}])
        report = drift.report(inventory, self.profile_context(payload))
        self.assertEqual(report["findings"], [])

    def test_drift_does_not_infer_intent_for_an_unprofiled_host(self) -> None:
        context = self.profile_context()
        self.assertIs(
            context.trust_role("example-discovered-host"), site_profile.UNKNOWN
        )
        report = drift.report(self.inventory(), context)
        unprofiled = [
            finding
            for finding in report["findings"]
            if finding["kind"] == drift.UNPROFILED_HOST
        ]
        self.assertEqual(len(unprofiled), 1)
        self.assertNotIn("trust_role", unprofiled[0])
        self.assertNotIn("criticality", unprofiled[0])
        self.assertNotIn("ownership", unprofiled[0])


class PersistenceAndCliTest(DriftTest):
    def test_cli_with_injected_inventory_writes_nothing_inside_the_tree(self) -> None:
        before = source_files(ROOT)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(
                [],
                environ={},
                inventory=self.inventory(),
            )
        self.assertEqual(code, 0)
        self.assertEqual(source_files(ROOT), before)
        self.assertEqual(json.loads(buffer.getvalue())["findings"], [])

    def test_cli_refuses_an_output_path_inside_the_working_tree(self) -> None:
        inside = ROOT / "tests" / "drift-output.example.json"
        self.assertFalse(inside.exists())
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(
                ["--output", str(inside), "--repository-root", str(ROOT)],
                environ={},
                inventory=self.inventory(),
            )
        self.assertEqual(code, 1)
        self.assertFalse(inside.exists())
        self.assertEqual(json.loads(buffer.getvalue())["error_type"], "DiscoveryPersistenceError")

    def test_cli_writes_a_report_outside_the_tree(self) -> None:
        outside = self.root / "drift.json"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(
                ["--output", str(outside), "--repository-root", str(ROOT)],
                environ={},
                inventory=self.inventory(),
            )
        self.assertEqual(code, 0)
        payload = json.loads(outside.read_text(encoding="utf-8"))
        self.assertEqual(payload["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertEqual(payload["findings"], [])

    def test_cli_composes_discovery_through_a_fixture_transport(self) -> None:
        profile = write_json(self.root / "site-profile.json", VALID_PROFILE)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(
                [],
                transport=RecordingFixture(EXAMPLE_PAYLOADS),
                environ={site_profile.ENVIRONMENT_VARIABLE: str(profile)},
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        kinds = {finding["kind"] for finding in payload["findings"]}
        self.assertEqual(kinds, {drift.UNPROFILED_HOST, drift.MISSING_POLICY})

    def test_cli_without_inventory_or_transport_does_not_open_a_controller(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main([], environ={})
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buffer.getvalue())["error_type"], "DriftError")


class FindingKindContractTest(unittest.TestCase):
    def test_finding_kinds_are_the_two_the_plan_names(self) -> None:
        self.assertEqual(
            set(drift.FINDING_KINDS),
            {drift.UNPROFILED_HOST, drift.MISSING_POLICY},
        )


if __name__ == "__main__":
    unittest.main()
