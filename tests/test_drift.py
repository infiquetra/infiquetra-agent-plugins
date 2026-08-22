"""Tests for UniFi actual-versus-intended drift reporting.

Standard library only. Drift never talks to a controller of its own; it
consumes an in-memory inventory from discovery (itself mocked) and a site
context. No test writes into the repository working tree.

Every test here is hermetic with respect to the site-profile contract. The
contract resolves a profile from ``UNIFI_SITE_PROFILE`` first and from the path
remembered in the configuration file second, and that configuration file lives
under ``${XDG_CONFIG_HOME:-~/.config}``. Neutralizing only the environment
variable therefore leaves the second rung reading the developer's real home
directory, so a machine with an operator profile deployed on it would resolve
that profile and compare this suite's synthetic inventory against a real site.
Both rungs are pinned inside a temporary directory instead, which is what makes
a no-profile run mean the same thing on every machine.
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
        self.config_home = self.root / "config-home"
        self.config_path = self.root / "config.json"
        self.environ = {site_profile.CONFIG_HOME_VARIABLE: str(self.config_home)}
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

    def observed_inventory(self, *identifiers: str) -> dict:
        """A live-discovery inventory whose policy set really was observed.

        Discovery composes no policy list operation, so the inventory it
        produces declares its own policy set unavailable. A policy-aware
        source declares the opposite, and that declaration is what earns the
        ``missing-policy`` comparison. Passing no identifier models a source
        that looked and genuinely found nothing.
        """
        return self.inventory(
            policies=[{"identifier": identifier} for identifier in identifiers],
            **{discover.POLICY_OBSERVATION_KEY: discover.POLICY_OBSERVED},
        )

    def environment(self, **overrides: str) -> dict[str, str]:
        """An environment whose profile resolution cannot leave ``self.root``.

        An empty mapping neutralizes ``UNIFI_SITE_PROFILE`` and nothing else.
        Pinning ``XDG_CONFIG_HOME`` as well moves the configuration directory
        that carries the second resolution rung inside the temporary
        directory, so no profile deployed on the developer's machine is
        reachable from a test.
        """
        environment = dict(self.environ)
        environment.update(overrides)
        return environment

    def config_arguments(self) -> list[str]:
        """Command-line arguments pinning the configuration file to ``self.root``.

        ``--config-path`` is the seam ``drift.main`` already offers for the
        second resolution rung. Naming it keeps a command-line run reading the
        same configuration file the in-process helpers read.
        """
        return ["--config-path", str(self.config_path)]

    def discovery_only_context(self) -> site_profile.SiteContext:
        return site_profile.load_site_context(
            environ=self.environment(), config_path=self.config_path
        )

    def profile_context(self, payload: object | None = None) -> site_profile.SiteContext:
        path = write_json(
            self.root / "site-profile.json",
            VALID_PROFILE if payload is None else payload,
        )
        return site_profile.load_site_context(
            environ=self.environment(
                **{site_profile.ENVIRONMENT_VARIABLE: str(path)}
            ),
            config_path=self.config_path,
        )


class NoProfileTest(DriftTest):
    def test_drift_with_no_profile_reports_discovery_only_and_no_findings(self) -> None:
        report = drift.report(self.inventory(), self.discovery_only_context())
        self.assertEqual(report["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["finding_count"], 0)
        self.assertEqual(
            report["limits"],
            list(site_profile.DISCOVERY_ONLY_LIMITS) + [drift.POLICY_UNOBSERVED_LIMIT],
        )
        self.assertEqual(report["policy_observation"], discover.POLICY_UNAVAILABLE)
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

        The mocked controller has ``example-discovered-host``; the profile
        names a different host and an intended policy. The inventory declares
        that it observed the controller's policy set and that the set holds
        some other policy, which is what makes ``example-policy`` provably
        absent rather than merely unlooked-for.
        """
        report = drift.report(
            self.observed_inventory("example-other-policy"), self.profile_context()
        )
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
        inventory = self.observed_inventory("example-policy")
        report = drift.report(inventory, self.profile_context(payload))
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["policy_observation"], discover.POLICY_OBSERVED)
        self.assertEqual(report["limits"], [])

    def test_a_policy_present_on_the_controller_emits_no_finding(self) -> None:
        """The intended policy exists on the controller, so nothing is wrong.

        The profile names ``example-policy`` and the observed policy set
        contains it alongside another. Before the repair this still produced a
        ``missing-policy`` finding for every profile whose inventory came from
        live discovery, because an unexamined empty list was read as the
        controller's answer.
        """
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"] = [
            {"kind": "host", "identifier": "example-discovered-host"}
        ]
        report = drift.report(
            self.observed_inventory("example-policy", "example-other-policy"),
            self.profile_context(payload),
        )
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["finding_count"], 0)
        self.assertEqual(report["intended_policies"], ["example-policy"])
        self.assertIn("example-policy", report["observed_policies"])

    def test_a_live_discovery_inventory_reports_no_policy_missing(self) -> None:
        """The repair for the false ``missing-policy`` finding.

        This is the ordinary live shape: an inventory straight out of
        discovery, and a profile with an intended policy. Discovery composes
        no policy list operation, so it has observed nothing about policies
        and the report may not claim the policy is absent. It says so in
        ``limits`` rather than dropping the comparison silently.
        """
        report = drift.report(self.inventory(), self.profile_context())
        self.assertEqual(report["mode"], site_profile.PROFILE_MODE)
        self.assertEqual(report["intended_policies"], ["example-policy"])
        self.assertEqual(
            [finding["kind"] for finding in report["findings"]],
            [drift.UNPROFILED_HOST],
        )
        self.assertNotIn(
            drift.MISSING_POLICY,
            {finding["kind"] for finding in report["findings"]},
        )
        self.assertEqual(report["policy_observation"], discover.POLICY_UNAVAILABLE)
        self.assertIn(drift.POLICY_UNOBSERVED_LIMIT, report["limits"])

    def test_a_policy_absent_from_an_observed_set_is_still_reported_missing(
        self,
    ) -> None:
        """The guarantee still bites where it is entitled to.

        A repair that stopped emitting ``missing-policy`` at all would pass
        every other test in this class. Here the inventory observed the
        controller's policy set, the set does not hold the intended policy,
        and the finding is required.
        """
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"] = [
            {"kind": "host", "identifier": "example-discovered-host"}
        ]
        report = drift.report(
            self.observed_inventory("example-other-policy"),
            self.profile_context(payload),
        )
        self.assertEqual(
            [(finding["kind"], finding["identifier"]) for finding in report["findings"]],
            [(drift.MISSING_POLICY, "example-policy")],
        )
        self.assertEqual(report["limits"], [])

    def test_an_observed_but_empty_policy_set_still_reports_the_policy_missing(
        self,
    ) -> None:
        """Observed-and-empty is a real answer; unobserved-and-empty is not.

        A source that looked at the controller and found no policy at all has
        proved the intended policy absent, so the finding stands even though
        the list is empty. The declaration is the whole difference between
        this case and the live-discovery one above.
        """
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"] = [
            {"kind": "host", "identifier": "example-discovered-host"}
        ]
        report = drift.report(
            self.observed_inventory(), self.profile_context(payload)
        )
        self.assertEqual(report["observed_policies"], [])
        self.assertEqual(
            [(finding["kind"], finding["identifier"]) for finding in report["findings"]],
            [(drift.MISSING_POLICY, "example-policy")],
        )

    def test_a_policy_list_that_never_said_whether_it_looked_is_unobserved(
        self,
    ) -> None:
        """An undeclared empty list is read closed, not open.

        A hand-written or older inventory carrying a bare ``policies: []`` and
        no declaration cannot distinguish "looked and found none" from "never
        looked". Reading it as the former is what produced the false finding,
        so it is read as the latter and the limitation is named.
        """
        inventory = self.inventory(policies=[])
        inventory.pop(discover.POLICY_OBSERVATION_KEY, None)
        report = drift.report(inventory, self.profile_context())
        self.assertEqual(report["policy_observation"], discover.POLICY_UNAVAILABLE)
        self.assertNotIn(
            drift.MISSING_POLICY,
            {finding["kind"] for finding in report["findings"]},
        )
        self.assertIn(drift.POLICY_UNOBSERVED_LIMIT, report["limits"])

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
                self.config_arguments(),
                environ=self.environment(),
                inventory=self.inventory(),
            )
        self.assertEqual(code, 0)
        self.assertEqual(source_files(ROOT), before)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertEqual(payload["findings"], [])

    def test_cli_refuses_an_output_path_inside_the_working_tree(self) -> None:
        inside = ROOT / "tests" / "drift-output.example.json"
        self.assertFalse(inside.exists())
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(
                [
                    "--output",
                    str(inside),
                    "--repository-root",
                    str(ROOT),
                    *self.config_arguments(),
                ],
                environ=self.environment(),
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
                [
                    "--output",
                    str(outside),
                    "--repository-root",
                    str(ROOT),
                    *self.config_arguments(),
                ],
                environ=self.environment(),
                inventory=self.inventory(),
            )
        self.assertEqual(code, 0)
        payload = json.loads(outside.read_text(encoding="utf-8"))
        self.assertEqual(payload["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertEqual(payload["findings"], [])

    def test_cli_composes_discovery_through_a_fixture_transport(self) -> None:
        """The whole chain, transport to report, on the live-shaped path.

        Discovery observes no policy set, so the report the command line
        prints carries the unprofiled host and no ``missing-policy`` finding
        for the profile's ``example-policy``, and names the gap in
        ``limits``.
        """
        profile = write_json(self.root / "site-profile.json", VALID_PROFILE)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(
                self.config_arguments(),
                transport=RecordingFixture(EXAMPLE_PAYLOADS),
                environ=self.environment(
                    **{site_profile.ENVIRONMENT_VARIABLE: str(profile)}
                ),
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        kinds = {finding["kind"] for finding in payload["findings"]}
        self.assertEqual(kinds, {drift.UNPROFILED_HOST})
        self.assertEqual(payload["intended_policies"], ["example-policy"])
        self.assertEqual(payload["policy_observation"], discover.POLICY_UNAVAILABLE)
        self.assertIn(drift.POLICY_UNOBSERVED_LIMIT, payload["limits"])

    def test_cli_without_inventory_or_transport_does_not_open_a_controller(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(self.config_arguments(), environ=self.environment())
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buffer.getvalue())["error_type"], "DriftError")


class DeployedProfileTest(DriftTest):
    """A profile reached through the remembered configured path.

    This is the case the command-line tests were exercising by accident on a
    machine with an operator profile deployed, and it deserves an intentional
    test. It covers the second rung of the resolution order rather than the
    environment variable: setup writes the chosen profile path into the
    configuration file, and every later run reads it back from there. Both the
    profile and the configuration file are written inside the temporary
    configuration home, so the run is the same on every machine.
    """

    def deploy_profile(self, payload: object | None = None) -> Path:
        """Deploy a profile the way first-setup does, inside ``self.root``."""
        profile = write_json(
            self.config_home
            / site_profile.CONFIG_RELATIVE_DIRECTORY
            / site_profile.DEFAULT_PROFILE_FILENAME,
            VALID_PROFILE if payload is None else payload,
        )
        site_profile.write_config(
            {"setup_path": "existing-profile", "site_profile_path": str(profile)},
            environ=self.environment(),
            config_path=self.config_path,
        )
        return profile

    def test_a_configured_profile_is_resolved_and_reported_as_profile_mode(self) -> None:
        profile = self.deploy_profile()
        context = site_profile.load_site_context(
            environ=self.environment(), config_path=self.config_path
        )
        self.assertEqual(context.mode, site_profile.PROFILE_MODE)
        self.assertEqual(context.source, site_profile.CONFIGURED_SOURCE)
        self.assertEqual(context.path, profile)

        report = drift.report(self.inventory(), context)
        self.assertEqual(report["mode"], site_profile.PROFILE_MODE)
        # The deployed profile is this test's own, not the machine's.
        self.assertEqual(report["site_identifier"], "example-site")
        self.assertEqual(report["profiled_hosts"], ["example-host"])
        self.assertEqual(report["intended_policies"], ["example-policy"])
        # Live discovery observes no policy set, so the intended policy is
        # unlooked-for rather than absent, and the report says which.
        self.assertEqual(report["limits"], [drift.POLICY_UNOBSERVED_LIMIT])
        self.assertEqual(
            [(finding["kind"], finding["identifier"]) for finding in report["findings"]],
            [(drift.UNPROFILED_HOST, "example-discovered-host")],
        )
        self.assertEqual(report["finding_count"], 1)

        # The same deployed profile against a policy-aware inventory: the
        # comparison runs and the missing policy is reported.
        observed = drift.report(self.observed_inventory("example-other-policy"), context)
        self.assertEqual(observed["limits"], [])
        self.assertEqual(
            [(finding["kind"], finding["identifier"]) for finding in observed["findings"]],
            [
                (drift.UNPROFILED_HOST, "example-discovered-host"),
                (drift.MISSING_POLICY, "example-policy"),
            ],
        )

    def test_cli_reports_the_drift_a_configured_profile_implies(self) -> None:
        self.deploy_profile()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(
                self.config_arguments(),
                environ=self.environment(),
                inventory=self.inventory(),
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], site_profile.PROFILE_MODE)
        self.assertEqual(payload["site_identifier"], "example-site")
        self.assertEqual(payload["finding_count"], 1)
        self.assertEqual(
            [(finding["kind"], finding["identifier"]) for finding in payload["findings"]],
            [(drift.UNPROFILED_HOST, "example-discovered-host")],
        )
        self.assertIn(drift.POLICY_UNOBSERVED_LIMIT, payload["limits"])

    def test_the_same_run_without_the_configuration_file_is_discovery_only(self) -> None:
        """The one difference between the two modes is the deployed profile.

        Same inventory, same environment, same command line; only the
        remembered configuration is absent. If this pair ever agreed, the
        no-profile assertion would have stopped meaning anything.
        """
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = drift.main(
                self.config_arguments(),
                environ=self.environment(),
                inventory=self.inventory(),
            )
        self.assertEqual(code, 0)
        self.assertFalse(self.config_path.exists())
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertEqual(payload["findings"], [])


class FindingKindContractTest(unittest.TestCase):
    def test_finding_kinds_are_the_two_the_plan_names(self) -> None:
        self.assertEqual(
            set(drift.FINDING_KINDS),
            {drift.UNPROFILED_HOST, drift.MISSING_POLICY},
        )

    def test_policy_observation_reads_a_declaration_it_does_not_recognize_closed(
        self,
    ) -> None:
        """An unknown declaration is not an observation.

        The vocabulary may grow. Until a value is recognized, an inventory
        that used it has not earned the comparison, and an empty list under an
        unrecognized label must not be read as controller state.
        """
        self.assertEqual(
            drift.policy_observation(
                {"policies": [], discover.POLICY_OBSERVATION_KEY: "partial"}
            ),
            discover.POLICY_UNAVAILABLE,
        )
        self.assertEqual(
            drift.policy_observation(
                {"policies": [], discover.POLICY_OBSERVATION_KEY: "OBSERVED"}
            ),
            discover.POLICY_OBSERVED,
        )
        # Rows outrank the label: a populated list was observed either way.
        self.assertEqual(
            drift.policy_observation(
                {
                    "policies": [{"identifier": "example-policy"}],
                    discover.POLICY_OBSERVATION_KEY: discover.POLICY_UNAVAILABLE,
                }
            ),
            discover.POLICY_OBSERVED,
        )


if __name__ == "__main__":
    unittest.main()
