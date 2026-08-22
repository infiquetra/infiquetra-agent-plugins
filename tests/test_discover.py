"""Tests for portable read-only UniFi discovery.

Standard library only. The controller is a fixture transport: every method
and URL is recorded, and no test opens a network connection or writes into
the repository working tree.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
UNIFI_SCRIPTS = ROOT / "plugins" / "unifi" / "scripts"
sys.path.insert(0, str(UNIFI_SCRIPTS))

import discover  # noqa: E402
import site_profile  # noqa: E402

from test_site_profile import VALID_PROFILE, write_json  # noqa: E402


def source_files(root: Path) -> set[Path]:
    return {
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and path.name != ".DS_Store"
    }


class RecordingFixture:
    """Maps each classified operation to a payload by matching the path tail."""

    def __init__(self, payloads: dict[str, Any] | None = None) -> None:
        self.payloads: dict[str, Any] = payloads or {}
        self.invocations: list[discover.Invocation] = []

    def request(self, method: str, url: str, *, confirm: bool = False) -> Any:
        self.invocations.append(
            discover.Invocation(
                method=method, url=url, confirm=confirm, operation="transport"
            )
        )
        path = urlparse(url).path.rstrip("/")
        if path.endswith("/snapshot"):
            raise AssertionError(f"snapshot requested: {url}")
        operation = _operation_for_path(path)
        if operation is None:
            raise AssertionError(f"unclassified URL: {method} {url}")
        payload = self.payloads.get(operation.resource, [])
        if operation.envelope == "data":
            return {"data": payload}
        return payload


def _operation_for_path(path: str) -> discover.ReadOnlyOperation | None:
    for operation in discover.READ_ONLY_OPERATIONS:
        template = operation.path_template
        if "{site}" in template:
            tail = template.split("{site}", 1)[1]
            if path.endswith(tail):
                return operation
        elif path.endswith(template):
            return operation
    return None


EXAMPLE_NETWORK = {
    "name": "example-guest-network",
    "vlan": 30,
    "purpose": "guest",
}
EXAMPLE_DEVICE = {"name": "example-ap", "mac": "00:00:00:00:00:01"}
EXAMPLE_CLIENT = {"hostname": "example-discovered-host", "mac": "00:00:00:00:00:02"}
EXAMPLE_CAMERA = {"name": "example-camera", "id": "example-camera-id"}

EXAMPLE_PAYLOADS = {
    "networks": [EXAMPLE_NETWORK],
    "devices": [EXAMPLE_DEVICE],
    "clients": [EXAMPLE_CLIENT],
    "cameras": [EXAMPLE_CAMERA],
}


class DiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.environ = {"XDG_CONFIG_HOME": str(self.root / "config-home")}
        self.before_repo_files = source_files(ROOT)

    def tearDown(self) -> None:
        after = source_files(ROOT)
        leftover = after - self.before_repo_files
        self.assertEqual(
            leftover,
            set(),
            f"discovery test left files in the working tree: {leftover}",
        )

    def run_discovery(self, **kwargs: Any) -> discover.DiscoveryResult:
        payloads = kwargs.pop("payloads", EXAMPLE_PAYLOADS)
        transport = kwargs.pop("transport", None) or RecordingFixture(payloads)
        kwargs.setdefault("host", "controller.example")
        kwargs.setdefault("site", "default")
        kwargs.setdefault("environ", self.environ)
        kwargs.setdefault("repository_root", ROOT)
        result = discover.discover(transport, **kwargs)
        discover.assert_read_only(result.invocations)
        return result

    def assert_only_gets(self, invocations: tuple[discover.Invocation, ...]) -> None:
        self.assertTrue(invocations)
        for invocation in invocations:
            self.assertEqual(
                invocation.method.upper(),
                "GET",
                msg=f"non-GET recorded: {invocation.method} {invocation.url}",
            )
            self.assertFalse(
                invocation.confirm,
                msg=f"--confirm passed for {invocation.url}",
            )
            self.assertFalse(
                invocation.is_snapshot(),
                msg=f"camera snapshot invoked: {invocation.url}",
            )


class CatalogTest(DiscoveryTest):
    def test_every_catalogued_operation_is_get(self) -> None:
        self.assertTrue(discover.READ_ONLY_OPERATIONS)
        for operation in discover.READ_ONLY_OPERATIONS:
            with self.subTest(operation=operation.name):
                self.assertEqual(operation.method, "GET")
                self.assertNotIn("/snapshot", operation.path_template)

    def test_snapshot_is_named_as_forbidden_rather_than_omitted_silently(self) -> None:
        names = [entry["name"] for entry in discover.FORBIDDEN_OPERATIONS]
        self.assertIn("cameras.snapshot", names)
        for entry in discover.FORBIDDEN_OPERATIONS:
            self.assertIn("/snapshot", entry["path_template"])


class ReadOnlyPathTest(DiscoveryTest):
    def test_discovery_invokes_only_read_only_endpoints(self) -> None:
        result = self.run_discovery()
        self.assert_only_gets(result.invocations)
        operations = {invocation.operation for invocation in result.invocations}
        self.assertEqual(
            operations,
            {operation.name for operation in discover.READ_ONLY_OPERATIONS},
        )
        self.assertEqual(len(result.invocations), len(discover.READ_ONLY_OPERATIONS))

    def test_every_recorded_url_matches_the_classified_catalog(self) -> None:
        result = self.run_discovery()
        for invocation in result.invocations:
            matched = _operation_for_path(invocation.path)
            self.assertIsNotNone(matched, invocation.url)
            self.assertEqual(matched.method, "GET")

    def test_discovery_never_passes_confirm(self) -> None:
        transport = RecordingFixture(EXAMPLE_PAYLOADS)
        result = self.run_discovery(transport=transport)
        for invocation in result.invocations:
            self.assertIs(invocation.confirm, False)
        for invocation in transport.invocations:
            self.assertIs(invocation.confirm, False)

    def test_camera_snapshot_is_never_invoked(self) -> None:
        result = self.run_discovery()
        for invocation in result.invocations:
            self.assertNotIn("/snapshot", invocation.url)
        camera_urls = [
            invocation.url
            for invocation in result.invocations
            if invocation.operation == "cameras.list"
        ]
        self.assertEqual(len(camera_urls), 1)
        self.assertTrue(camera_urls[0].rstrip("/").endswith("/cameras"))

    def test_coverage_includes_networks_vlans_devices_clients_and_cameras(self) -> None:
        result = self.run_discovery()
        for resource in discover.DISCOVERY_RESOURCES:
            self.assertIn(resource, result.inventory)
        self.assertEqual(
            [entry["identifier"] for entry in result.inventory["networks"]],
            ["example-guest-network"],
        )
        self.assertEqual(
            [entry["identifier"] for entry in result.inventory["vlans"]],
            ["30"],
        )
        self.assertEqual(
            [entry["identifier"] for entry in result.inventory["devices"]],
            ["example-ap"],
        )
        self.assertEqual(
            [entry["identifier"] for entry in result.inventory["clients"]],
            ["example-discovered-host"],
        )
        self.assertEqual(
            [entry["identifier"] for entry in result.inventory["cameras"]],
            ["example-camera"],
        )

    def test_vlans_are_derived_from_the_networks_get_without_a_second_call(self) -> None:
        result = self.run_discovery()
        vlan_ops = [
            invocation
            for invocation in result.invocations
            if "vlan" in invocation.url.lower()
        ]
        self.assertEqual(vlan_ops, [])
        self.assertEqual(result.inventory["vlans"][0]["network"], "example-guest-network")

    def test_session_refuses_a_non_get_even_if_a_caller_asks(self) -> None:
        session = discover.DiscoverySession(
            RecordingFixture(), host="controller.example", site="default"
        )
        with self.assertRaises(discover.DiscoveryError) as raised:
            session._guard("POST", "https://controller.example/x", True, "networks.create")
        message = str(raised.exception)
        self.assertIn("--confirm", message)

        with self.assertRaises(discover.DiscoveryError) as raised:
            session._guard(
                "GET",
                "https://controller.example/proxy/protect/integration/v1/cameras/x/snapshot",
                False,
                "cameras.snapshot",
            )
        self.assertIn("snapshot", str(raised.exception).lower())


class PersistenceTest(DiscoveryTest):
    def test_discovery_with_no_output_path_writes_no_file_anywhere(self) -> None:
        before_temp = source_files(self.root)
        before_repo = source_files(ROOT)
        result = self.run_discovery()
        self.assertIsNone(result.written_path)
        self.assertEqual(source_files(self.root), before_temp)
        self.assertEqual(source_files(ROOT), before_repo)

    def test_output_path_inside_the_repository_working_tree_is_refused(self) -> None:
        inside = ROOT / "tests" / "discovery-output.example.json"
        self.assertTrue(inside.parent.is_dir())
        self.assertFalse(inside.exists())
        with self.assertRaises(discover.DiscoveryPersistenceError) as raised:
            self.run_discovery(output=inside)
        self.assertIn("working tree", str(raised.exception))
        self.assertFalse(inside.exists())

    def test_output_path_outside_the_repository_is_written(self) -> None:
        outside = self.root / "discovery.json"
        result = self.run_discovery(output=outside)
        self.assertEqual(result.written_path, outside.resolve())
        self.assertTrue(outside.is_file())
        payload = json.loads(outside.read_text(encoding="utf-8"))
        self.assertEqual(payload["clients"][0]["identifier"], "example-discovered-host")
        self.assertNotIn("invocations", payload)

    def test_output_path_inside_the_package_directory_is_always_refused(self) -> None:
        """A refusal that needs no checkout to decide.

        The named repository root here is an unrelated temporary directory, so
        the working-tree rule cannot be what refuses this path. A package
        copied out of its checkout keeps this layout and loses the ``.git``
        entry, and this is the rule that still holds there.
        """
        inside = discover.PACKAGE_ROOT / "discovery-output.example.json"
        self.assertFalse(inside.exists())
        with self.assertRaises(discover.DiscoveryPersistenceError) as raised:
            discover.refuse_repository_output(inside, repository_root=self.root)
        self.assertIn("package directory", str(raised.exception))
        self.assertFalse(inside.exists())

    def undeterminable_working_tree(self) -> None:
        """Make the ``.git`` walk find nothing, for the duration of one test.

        The walk starts at the current directory, and whether a real directory
        has a ``.git`` entry above it is a property of the machine the suite
        runs on — this developer's ``TMPDIR`` has one. Neutralizing the walk
        itself is what makes "discovery run from a copy with no checkout"
        mean the same thing everywhere. The production branch under test is
        the one that calls it with no argument.
        """
        original = discover.repository_root_from
        discover.repository_root_from = lambda start=None: None
        self.addCleanup(setattr, discover, "repository_root_from", original)
        self.assertIsNone(discover.repository_root_from())

    def test_persistence_refuses_when_no_working_tree_can_be_determined(self) -> None:
        """The deny-list refuses what it cannot evaluate.

        With no root named and none found, there is no tree to compare the
        output path against. Returning the path here is what let a discovery
        run from a copy without ``.git`` write an unfiltered controller
        response next to committable files.
        """
        self.undeterminable_working_tree()
        with self.assertRaises(discover.DiscoveryPersistenceError) as raised:
            discover.refuse_repository_output(self.root / "inventory.json")
        message = str(raised.exception)
        self.assertIn("no repository working tree", message)
        self.assertIn("--repository-root", message)

    def test_a_discovery_run_with_no_determinable_tree_writes_no_file(self) -> None:
        """The whole persistence chain, not just its leaf check.

        ``discover`` -> ``persist_payload`` -> ``refuse_repository_output`` is
        the path a real run takes, and the refusal has to stop the write
        rather than be reported after it.
        """
        self.undeterminable_working_tree()
        output = self.root / "inventory.json"
        with self.assertRaises(discover.DiscoveryPersistenceError):
            discover.discover(
                RecordingFixture(EXAMPLE_PAYLOADS),
                host="controller.example",
                site="default",
                output=output,
                environ=self.environ,
            )
        self.assertFalse(output.exists())

    def test_a_named_repository_root_lifts_the_undeterminable_refusal(self) -> None:
        """Fail-closed, not fail-always.

        An operator working outside a checkout says which tree to protect and
        the write proceeds, so the refusal above is a deny-list that cannot be
        evaluated rather than a ban on persistence.
        """
        self.undeterminable_working_tree()
        output = self.root / "inventory.json"
        result = discover.discover(
            RecordingFixture(EXAMPLE_PAYLOADS),
            host="controller.example",
            site="default",
            output=output,
            repository_root=ROOT,
            environ=self.environ,
        )
        self.assertEqual(result.written_path, output.resolve())
        self.assertTrue(output.is_file())

    def test_cli_rejects_confirm_rather_than_honoring_it(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(UNIFI_SCRIPTS / "discover.py"), "--confirm"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--confirm", completed.stderr)


class PolicyObservationTest(DiscoveryTest):
    """Discovery says its policy set is unobserved, not empty.

    Nothing in the read-only catalog lists policy objects, so the empty
    ``policies`` list is absence of evidence. A consumer that read it as
    controller state reported every intended policy as missing; the
    declaration is what stops that.
    """

    def test_no_catalogued_operation_covers_policies(self) -> None:
        self.assertNotIn(
            "policies",
            {operation.resource for operation in discover.READ_ONLY_OPERATIONS},
        )

    def test_a_discovery_inventory_declares_its_policy_set_unavailable(self) -> None:
        result = self.run_discovery()
        self.assertEqual(result.inventory["policies"], [])
        self.assertEqual(
            result.inventory[discover.POLICY_OBSERVATION_KEY],
            discover.POLICY_UNAVAILABLE,
        )

    def test_an_empty_inventory_declares_the_same_thing(self) -> None:
        inventory = discover.empty_inventory("default")
        self.assertEqual(
            inventory[discover.POLICY_OBSERVATION_KEY],
            discover.POLICY_UNAVAILABLE,
        )

    def test_the_declaration_survives_being_written_and_read_back(self) -> None:
        """``drift --inventory <file>`` is a real path, so the file must carry it."""
        outside = self.root / "discovery.json"
        self.run_discovery(output=outside)
        payload = json.loads(outside.read_text(encoding="utf-8"))
        self.assertEqual(
            payload[discover.POLICY_OBSERVATION_KEY],
            discover.POLICY_UNAVAILABLE,
        )


class ProposalTest(DiscoveryTest):
    def test_proposed_profile_is_generated_without_writing_the_configured_path(self) -> None:
        configured = site_profile.default_profile_path(self.environ)
        self.assertFalse(configured.exists())
        result = self.run_discovery(propose=True)
        self.assertIsNotNone(result.proposed_profile)
        self.assertFalse(configured.exists())
        self.assertIsNone(result.written_path)

    def test_proposal_does_not_write_a_remembered_live_profile_path(self) -> None:
        live = self.root / "live-profile.json"
        write_json(live, VALID_PROFILE)
        with self.assertRaises(discover.DiscoveryPersistenceError) as raised:
            self.run_discovery(
                propose=True,
                output=live,
                configured_profile_path=live,
            )
        self.assertIn("live profile", str(raised.exception))
        self.assertEqual(
            json.loads(live.read_text(encoding="utf-8"))["site"]["identifier"],
            "example-site",
        )

    def test_every_intent_field_of_a_generated_proposal_is_unknown(self) -> None:
        result = self.run_discovery(propose=True)
        proposal = result.proposed_profile
        self.assertIsNotNone(proposal)
        site_profile.validate_profile(proposal)
        self.assertEqual(proposal["intended_policies"], [])
        self.assertEqual(proposal["operational_constraints"], [])
        self.assertTrue(proposal["subjects"])
        for subject in proposal["subjects"]:
            with self.subTest(identifier=subject["identifier"]):
                self.assertEqual(subject["trust_role"], site_profile.UNKNOWN_LITERAL)
                self.assertEqual(subject["criticality"], site_profile.UNKNOWN_LITERAL)
                self.assertEqual(subject["ownership"], site_profile.UNKNOWN_LITERAL)
                self.assertTrue(site_profile.is_unknown(subject["trust_role"]))
                self.assertTrue(site_profile.is_unknown(subject["criticality"]))
                self.assertTrue(site_profile.is_unknown(subject["ownership"]))
                self.assertNotIn("intended_policies", subject)
        # Field-by-field across the four intent facets named by the contract.
        for field in site_profile.INTENT_FIELDS:
            with self.subTest(field=field):
                if field == "intended_policies":
                    self.assertEqual(proposal[field], [])
                else:
                    for subject in proposal["subjects"]:
                        self.assertEqual(subject[field], site_profile.UNKNOWN_LITERAL)

    def test_proposal_maps_observed_kinds_without_inventing_trust(self) -> None:
        result = self.run_discovery(propose=True)
        kinds = {
            (subject["kind"], subject["identifier"])
            for subject in result.proposed_profile["subjects"]
        }
        self.assertIn(("network", "example-guest-network"), kinds)
        self.assertIn(("device", "example-ap"), kinds)
        self.assertIn(("host", "example-discovered-host"), kinds)
        self.assertIn(("device", "example-camera"), kinds)

    def test_proposal_written_outside_the_tree_does_not_touch_the_live_profile(self) -> None:
        live = site_profile.default_profile_path(self.environ)
        outside = self.root / "proposal.json"
        result = self.run_discovery(propose=True, output=outside)
        self.assertTrue(outside.is_file())
        self.assertFalse(live.exists())
        written = json.loads(outside.read_text(encoding="utf-8"))
        self.assertEqual(written["intended_policies"], [])
        self.assertEqual(result.proposed_profile["schema_version"], "1.0")


class LiveTransportGuardTest(unittest.TestCase):
    def test_live_transport_refuses_a_missing_host_without_a_network_call(self) -> None:
        with self.assertRaises(discover.DiscoveryError) as raised:
            discover.LiveTransport(host="", api_key="inert-example-key")
        self.assertIn("no default", str(raised.exception))

    def test_live_transport_refuses_a_missing_api_key_without_a_network_call(self) -> None:
        with self.assertRaises(discover.DiscoveryError) as raised:
            discover.LiveTransport(host="controller.example", api_key="")
        self.assertIn("API key", str(raised.exception))

    def test_cli_without_credentials_fails_before_any_controller_call(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(UNIFI_SCRIPTS / "discover.py")],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
        )
        self.assertEqual(completed.returncode, 1)
        report = json.loads(completed.stdout)
        self.assertIn(report["error_type"], {"DiscoveryError"})
        self.assertNotIn("controller.example", completed.stdout.lower() + completed.stderr.lower())


class CommandLineTest(DiscoveryTest):
    def test_cli_with_injected_transport_prints_json_and_writes_nothing(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = discover.main(
                ["--site", "default"],
                transport=RecordingFixture(EXAMPLE_PAYLOADS),
                environ=self.environ,
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertIsNone(payload["wrote"])
        self.assertEqual(len(payload["invocations"]), 4)

    def test_cli_propose_profile_writes_only_the_named_outside_path(self) -> None:
        outside = self.root / "proposal.json"
        live = site_profile.default_profile_path(self.environ)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = discover.main(
                [
                    "--propose-profile",
                    "--output",
                    str(outside),
                    "--repository-root",
                    str(ROOT),
                ],
                transport=RecordingFixture(EXAMPLE_PAYLOADS),
                environ=self.environ,
            )
        self.assertEqual(code, 0)
        self.assertTrue(outside.is_file())
        self.assertFalse(live.exists())
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["proposed_profile"]["intended_policies"] == [])


if __name__ == "__main__":
    unittest.main()
