"""Tests for the ten-client compatibility matrix validator.

The validator exists because prose cannot enforce coverage. These tests pin the
two things that matter and pull in opposite directions:

* A row that looks covered but is not must fail — a missing stage, a renamed
  client, an executed stage with no evidence, a status outside the four.
* A row that honestly records a bad outcome must pass — ``unsupported`` and
  ``failed`` are results, not defects. Coverage is mandatory; passing is not.

A third pull was added after a review found the matrix describing a package that
no longer existed while passing every check:

* A record whose fingerprint does not identify the assessed tree must fail, and
  a well-formed digest of the wrong tree is the case that matters. Declaring a
  document superseded is the only exemption, and the tests below pin both that
  the exemption works and that it cannot be turned on the live matrix.

Standard library only, matching the validator and the repository baseline.
"""

from __future__ import annotations

import atexit
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_compatibility_matrix as ccm  # noqa: E402
import port_config  # noqa: E402


EVIDENCE = ROOT / "docs" / "evidence"
LIVE_DOCUMENT = EVIDENCE / "2026-08-22-unifi-compatibility-matrix.md"
SUPERSEDED_DOCUMENT = EVIDENCE / "2026-08-22-unifi-compatibility-matrix-pre-repair.md"
READBACK_DOCUMENT = EVIDENCE / "2026-08-22-unifi-post-activation-readback.md"
SCHEMA_PATH = ROOT / "schemas" / "compatibility-matrix.schema.json"
PACKAGE_ROOT = ROOT / "plugins" / "unifi"


def _build_fake_package() -> tuple[Path, "port_config.PortConfig"]:
    """A throwaway package tree, and the port descriptor that names it.

    The unit tests must not depend on the real package's file count or digest —
    that would couple every assertion here to whatever ``plugins/unifi/`` holds
    this week. They bind to this tree instead; the live documents are checked
    against the real one further down.

    The descriptor is built through `port_config.parse` rather than assembled by
    hand, so these tests drive the validator the same way a committed descriptor
    does, and a change that made the real descriptor unloadable would break here
    too.
    """
    directory = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, directory, True)
    package = directory / "plugins" / "unifi"
    (package / "skills" / "example").mkdir(parents=True)
    (package / "plugin.json").write_text(
        json.dumps({"name": "unifi", "version": "2.0.0"}), encoding="utf-8"
    )
    (package / "README.md").write_text("Example package.\n", encoding="utf-8")
    (package / "skills" / "example" / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    config = port_config.parse(
        {
            "schema_version": port_config.SCHEMA_VERSION,
            "package": "unifi",
            "package_root": "plugins/unifi",
            "source": {"repository": "https://example.com/upstream", "package_path": "plugins/x"},
            "custody": {},
            "assessment": {
                "package_scripts": list(REAL_CONFIG.assessment.package_scripts),
                "mutating_operations": sorted(REAL_CONFIG.assessment.mutating_operations),
                "credential_prefixes": list(REAL_CONFIG.assessment.credential_prefixes),
                "entrypoints": list(REAL_CONFIG.assessment.entrypoints),
                "declared_none": [],
            },
        },
        root=directory,
        path=directory / "ports" / "unifi.json",
    )
    return package, config


#: The committed descriptor. The constructed records borrow its assessment block
#: so the safety rules under test are the rules the shipped package actually
#: declares, rather than a second list invented in this file.
REAL_CONFIG = port_config.load("unifi", ROOT)

FAKE_PACKAGE, FAKE_CONFIG = _build_fake_package()
FAKE_FILE_COUNT, FAKE_TREE_SHA256 = ccm.package_fingerprint(FAKE_PACKAGE)


def executed_stage(command: str = "client list --json") -> dict:
    return {
        "result": "executed",
        "command": command,
        "evidence": "One entry resolved, with two skills and no diagnostic.",
    }


def blocked_stage(reason: str = "The client requires credentials.") -> dict:
    return {"result": "blocked", "reason": reason}


def valid_client(name: str, **overrides: object) -> dict:
    client = {
        "name": name,
        "version": "1.0.0",
        "stages": {stage: executed_stage() for stage in ccm.STAGES},
        "status": "works-directly",
        "reason": "Placed, discovered, and loaded the portable package as shipped.",
    }
    client.update(overrides)
    return client


def valid_record(**overrides: object) -> dict:
    record = {
        "schema_version": "1",
        "assessed_on": "2026-08-22",
        "package": {
            "name": "unifi",
            "version": "2.0.0",
            "file_count": FAKE_FILE_COUNT,
            "tree_sha256": FAKE_TREE_SHA256,
        },
        "method": {
            "stages": list(ccm.STAGES),
            "isolation": "Each client ran against its own empty home directory.",
            "credentials": "No client was authenticated at any stage.",
            "network": "No controller call was made at any stage.",
        },
        "clients": [valid_client(name) for name in ccm.CANONICAL_CLIENTS],
    }
    record.update(overrides)
    return record


def as_document(record: dict, preamble: str = "# Matrix\n\nProse first.\n\n") -> str:
    """Wrap a record the way the evidence document does."""
    return f"{preamble}```json\n{json.dumps(record, indent=2)}\n```\n\nProse after.\n"


def write_document(record: dict, preamble: str = "# Matrix\n\nProse first.\n\n") -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    )
    handle.write(as_document(record, preamble))
    handle.close()
    return Path(handle.name)


def check(record: dict, preamble: str = "# Matrix\n\nProse first.\n\n") -> list[str]:
    """Every problem the validator finds in a record, via a real document."""
    document = write_document(record, preamble)
    try:
        return ccm.check_matrix(document, FAKE_CONFIG)
    finally:
        document.unlink()


def superseded_preamble(
    successor: str = "successor.md",
    reason: str = "Re-run against the repaired package.",
) -> str:
    """The directive block a retired matrix carries."""
    return (
        f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_SUPERSEDED} -->\n"
        f"<!-- {ccm.SUPERSEDED_BY_DIRECTIVE}: {successor} -->\n"
        f"<!-- {ccm.SUPERSEDED_REASON_DIRECTIVE}: {reason} -->\n\n"
        "# Matrix\n\nProse first.\n\n"
    )


class RecordExtractionTest(unittest.TestCase):
    def test_first_fenced_json_block_is_the_record(self) -> None:
        record = valid_record()
        self.assertEqual(ccm.extract_record(as_document(record)), record)

    def test_prose_before_the_block_does_not_interfere(self) -> None:
        record = valid_record()
        preamble = "# Title\n\nA paragraph mentioning ```console fences.\n\n"
        self.assertEqual(ccm.extract_record(as_document(record, preamble)), record)

    def test_a_document_with_no_record_is_reported_not_ignored(self) -> None:
        with self.assertRaises(ccm.MatrixError):
            ccm.extract_record("# Matrix\n\nNo record here.\n")

    def test_a_malformed_record_is_reported_as_invalid_json(self) -> None:
        with self.assertRaises(ccm.MatrixError):
            ccm.extract_record("```json\n{not json}\n```\n")

    def test_a_missing_document_is_a_problem_not_a_crash(self) -> None:
        problems = ccm.check_matrix(ROOT / "docs" / "evidence" / "absent.md")
        self.assertEqual(len(problems), 1)
        self.assertIn("does not exist", problems[0])


class BaselineTest(unittest.TestCase):
    def test_the_constructed_record_is_clean(self) -> None:
        self.assertEqual(check(valid_record()), [])


class CoverageTest(unittest.TestCase):
    def test_all_ten_clients_are_required(self) -> None:
        record = valid_record()
        record["clients"] = record["clients"][:9]
        problems = check(record)
        self.assertTrue(any("has no row" in problem for problem in problems))

    def test_a_renamed_client_fails_even_though_the_count_is_ten(self) -> None:
        """Set equality, not a count: a substituted client keeps the count."""
        record = valid_record()
        record["clients"][4] = valid_client("Grokk")
        problems = check(record)
        self.assertEqual(len(record["clients"]), 10)
        self.assertTrue(any("has no row" in problem for problem in problems))
        self.assertTrue(
            any("not one of the ten named clients" in problem for problem in problems)
        )

    def test_a_duplicated_client_cannot_stand_in_for_a_missing_one(self) -> None:
        record = valid_record()
        record["clients"][4] = valid_client("Qwen")
        problems = check(record)
        self.assertTrue(any("appears more than once" in problem for problem in problems))

    def test_every_client_carries_all_four_stages(self) -> None:
        for stage in ccm.STAGES:
            with self.subTest(stage=stage):
                record = valid_record()
                del record["clients"][0]["stages"][stage]
                problems = check(record)
                self.assertTrue(
                    any(f"the {stage} stage is absent" in problem for problem in problems)
                )

    def test_a_row_missing_a_stage_fails_even_with_an_overall_status(self) -> None:
        """The defect this check closes: a status is not a substitute for coverage."""
        record = valid_record()
        del record["clients"][2]["stages"]["load"]
        record["clients"][2]["status"] = "failed"
        record["clients"][2]["reason"] = "Placement was refused."
        problems = check(record)
        self.assertTrue(any("the load stage is absent" in problem for problem in problems))

    def test_a_row_with_no_stages_at_all_is_reported(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"] = {}
        self.assertNotEqual(check(record), [])


class StageResultTest(unittest.TestCase):
    def test_a_stage_result_outside_the_three_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["load"] = {"result": "partial"}
        problems = check(record)
        self.assertTrue(
            any("not executed, blocked, or not-applicable" in problem for problem in problems)
        )

    def test_an_executed_stage_without_a_command_fails(self) -> None:
        record = valid_record()
        del record["clients"][1]["stages"]["discovery"]["command"]
        problems = check(record)
        self.assertTrue(any("records no command" in problem for problem in problems))

    def test_an_executed_stage_without_evidence_fails(self) -> None:
        record = valid_record()
        del record["clients"][1]["stages"]["discovery"]["evidence"]
        problems = check(record)
        self.assertTrue(any("records no evidence" in problem for problem in problems))

    def test_an_executed_stage_with_blank_evidence_fails(self) -> None:
        record = valid_record()
        record["clients"][1]["stages"]["discovery"]["evidence"] = "   "
        problems = check(record)
        self.assertTrue(any("records no evidence" in problem for problem in problems))

    def test_a_blocked_stage_without_a_reason_fails(self) -> None:
        record = valid_record()
        record["clients"][3]["stages"]["invocation"] = {"result": "blocked"}
        problems = check(record)
        self.assertTrue(any("names no reason" in problem for problem in problems))

    def test_a_not_applicable_stage_without_a_reason_fails(self) -> None:
        record = valid_record()
        record["clients"][3]["stages"]["invocation"] = {"result": "not-applicable"}
        problems = check(record)
        self.assertTrue(any("names no reason" in problem for problem in problems))

    def test_a_blocked_stage_with_a_reason_passes(self) -> None:
        record = valid_record()
        record["clients"][3]["stages"]["invocation"] = blocked_stage(
            "The client resolved no path to the package."
        )
        self.assertEqual(check(record), [])

    def test_a_blocked_stage_may_also_record_the_command_that_was_refused(self) -> None:
        record = valid_record()
        record["clients"][3]["stages"]["placement"] = {
            "result": "blocked",
            "command": "client plugin marketplace add <package>",
            "reason": "Refused with an authentication-required error.",
        }
        self.assertEqual(check(record), [])


class OverallStatusTest(unittest.TestCase):
    def test_each_permitted_status_is_accepted(self) -> None:
        for status in ccm.STATUSES:
            with self.subTest(status=status):
                record = valid_record()
                record["clients"][0]["status"] = status
                self.assertEqual(check(record), [])

    def test_a_status_outside_the_four_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["status"] = "mostly-works"
        problems = check(record)
        self.assertTrue(
            any("not one of the four permitted statuses" in problem for problem in problems)
        )

    def test_a_status_without_a_reason_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["reason"] = ""
        problems = check(record)
        self.assertTrue(any("no concrete reason" in problem for problem in problems))

    def test_unsupported_and_failed_never_fail_the_check(self) -> None:
        """Coverage is mandatory; passing is not."""
        record = valid_record()
        record["clients"][1]["status"] = "unsupported"
        record["clients"][1]["reason"] = "The client has no extension mechanism."
        record["clients"][2]["status"] = "failed"
        record["clients"][2]["reason"] = "Every extension surface refused."
        for stage in ccm.STAGES:
            record["clients"][2]["stages"][stage] = blocked_stage(
                "The client requires credentials before reporting state."
            )
        self.assertEqual(check(record), [])

    def test_every_client_failing_still_passes_the_check(self) -> None:
        """No single failing client blocks completion, and neither do all ten."""
        record = valid_record()
        for client in record["clients"]:
            client["status"] = "failed"
            client["reason"] = "The package could not be placed."
            for stage in ccm.STAGES:
                client["stages"][stage] = blocked_stage("Placement was refused.")
        self.assertEqual(check(record), [])


class SafetyBoundaryTest(unittest.TestCase):
    def test_a_recorded_invocation_passing_confirm_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["invocation"]["command"] = (
            "python3 <package>/skills/unifi-network/scripts/unifi_network_client.py "
            "devices list --confirm"
        )
        problems = check(record)
        self.assertTrue(any(ccm.CONFIRM_FLAG in problem for problem in problems))

    def test_confirm_is_refused_in_any_stage_not_only_invocation(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["placement"]["command"] = "client install --confirm"
        problems = check(record)
        self.assertTrue(any(ccm.CONFIRM_FLAG in problem for problem in problems))

    def test_a_recorded_mutating_operation_fails(self) -> None:
        for operation in ("restart", "block", "delete", "adopt", "forget", "snapshot"):
            with self.subTest(operation=operation):
                record = valid_record()
                record["clients"][0]["stages"]["invocation"]["command"] = (
                    "python3 <package>/skills/unifi-network/scripts/"
                    f"unifi_network_client.py devices {operation}"
                )
                problems = check(record)
                self.assertTrue(
                    any("mutating operation" in problem for problem in problems),
                    f"{operation} was not refused",
                )

    def test_a_read_only_operation_is_accepted(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["invocation"]["command"] = (
            "python3 <package>/skills/unifi-network/scripts/unifi_network_client.py "
            "devices list"
        )
        self.assertEqual(check(record), [])

    def test_a_client_subcommand_sharing_a_verb_is_not_a_controller_call(self) -> None:
        """The mutating check is scoped to the package's own scripts, so a
        client's own `update` subcommand does not read as a controller write."""
        record = valid_record()
        record["clients"][0]["stages"]["placement"]["command"] = "client extensions update"
        self.assertEqual(check(record), [])


class PerCommandStatusRecordTest(unittest.TestCase):
    """Version 2 records every command beside its own exit status.

    The whole rule shipped without a test. A mutation that stopped requiring
    per-command statuses altogether failed nothing, which means the guard could
    have been deleted and the suite would have said the record was still sound.
    """

    @staticmethod
    def version_two() -> dict:
        record = valid_record(schema_version="2")
        for client in record["clients"]:
            for value in client["stages"].values():
                value["commands"] = [{"command": value["command"], "exit_status": 0}]
        return record

    NO_STATUSES = "records no per-command statuses"

    def test_a_well_formed_version_two_record_is_accepted(self) -> None:
        self.assertEqual(self.version_two() and check(self.version_two()), [])

    def test_an_executed_stage_without_commands_is_refused(self) -> None:
        """A stage that ran several commands is not reproducible from the first."""
        record = self.version_two()
        del record["clients"][0]["stages"]["placement"]["commands"]
        self.assertTrue(
            any(self.NO_STATUSES in problem for problem in check(record)),
            "a version-2 stage with no per-command statuses was accepted",
        )

    def test_an_executed_stage_with_an_empty_command_list_is_refused(self) -> None:
        record = self.version_two()
        record["clients"][0]["stages"]["placement"]["commands"] = []
        self.assertTrue(any(self.NO_STATUSES in problem for problem in check(record)))

    def test_a_version_one_record_may_not_carry_per_command_statuses(self) -> None:
        """The field arrived in version 2; a version-1 record claiming it is lying."""
        record = valid_record()
        record["clients"][0]["stages"]["placement"]["commands"] = [
            {"command": "client install", "exit_status": 0}
        ]
        self.assertTrue(
            any("declares version 1" in problem for problem in check(record)),
            "a version-1 record carried a version-2 field unchallenged",
        )

    def test_the_recorded_command_must_be_the_first_of_its_statuses(self) -> None:
        """`command` is an alias of commands[0]; two names for one thing must agree."""
        record = self.version_two()
        record["clients"][0]["stages"]["placement"]["commands"][0]["command"] = "other"
        self.assertTrue(
            any("disagree about what ran first" in problem for problem in check(record)),
            "the alias and the list were allowed to name different commands",
        )

    def test_a_blocked_stage_needs_no_commands(self) -> None:
        """Nothing ran, so there is nothing to record; this must not be an error."""
        record = self.version_two()
        record["clients"][0]["stages"]["invocation"] = blocked_stage()
        self.assertFalse(any(self.NO_STATUSES in problem for problem in check(record)))


class PublicEvidenceTest(unittest.TestCase):
    def test_a_seeded_address_in_an_evidence_field_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["discovery"]["evidence"] = (
            "The client reached the controller at 203.0.113.7 and listed two skills."
        )
        problems = check(record)
        self.assertTrue(any("contains an address" in problem for problem in problems))

    def test_a_seeded_ipv6_address_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["discovery"]["evidence"] = (
            "Reached 2001:0db8:85a3:0000:8a2e:0370:7334 during discovery."
        )
        problems = check(record)
        self.assertTrue(any("contains an address" in problem for problem in problems))

    def test_a_seeded_hardware_address_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["load"]["evidence"] = (
            "Resolved the device aa:bb:cc:dd:ee:ff from the inventory."
        )
        problems = check(record)
        self.assertTrue(any("hardware address" in problem for problem in problems))

    def test_a_dash_separated_hardware_address_also_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["load"]["evidence"] = "Device aa-bb-cc-dd-ee-ff."
        problems = check(record)
        self.assertTrue(any("hardware address" in problem for problem in problems))

    def test_a_seeded_hostname_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["placement"]["command"] = (
            "python3 discover.py --host udm.internal.lan"
        )
        problems = check(record)
        self.assertTrue(any("contains the hostname" in problem for problem in problems))

    def test_an_inert_example_hostname_is_permitted(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["placement"]["command"] = (
            "python3 discover.py --host controller.example"
        )
        self.assertEqual(check(record), [])

    def test_a_filename_is_not_mistaken_for_a_hostname(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["placement"]["evidence"] = (
            "The client requires marketplace.json and reads SKILL.md; the script is "
            "unifi_network_client.py."
        )
        self.assertEqual(check(record), [])

    def test_the_client_extension_directory_is_not_mistaken_for_a_hostname(self) -> None:
        """Its reverse-domain name is a namespace, not a host."""
        record = valid_record()
        record["clients"][0]["stages"]["load"]["evidence"] = (
            "The com.infiquetra.claude client extension directory was not recognized."
        )
        self.assertEqual(check(record), [])

    def test_a_clock_time_is_not_mistaken_for_an_address(self) -> None:
        """Every digit of a time is valid hexadecimal, so the pattern must not
        treat three colon-separated groups as an address."""
        record = valid_record()
        record["clients"][0]["stages"]["load"]["evidence"] = "Installed at 15:13:17 local time."
        self.assertEqual(check(record), [])

    def test_a_version_string_is_not_mistaken_for_an_address(self) -> None:
        record = valid_record()
        record["clients"][0]["version"] = "2026.08.11"
        record["clients"][1]["version"] = "2.1.240"
        self.assertEqual(check(record), [])

    def test_a_credential_value_fails(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["invocation"]["command"] = (
            "python3 discover.py --host controller.example password=hunter2"
        )
        problems = check(record)
        self.assertTrue(any("credential" in problem for problem in problems))

    def test_an_explicitly_redacted_credential_is_permitted(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["invocation"]["command"] = (
            "python3 discover.py --host controller.example password=<redacted>"
        )
        self.assertEqual(check(record), [])

    def test_the_package_digest_is_not_read_as_a_leak(self) -> None:
        # Checked against the redaction rule directly rather than through the
        # whole validator: a digest of the wrong tree now fails the binding, and
        # that failure would mask what this test is actually about.
        record = valid_record()
        record["package"]["tree_sha256"] = "ab" * 32
        self.assertEqual(ccm.check_public_evidence_rules(record), [])


class SchemaContractTest(unittest.TestCase):
    def test_the_schema_file_is_a_readable_json_object(self) -> None:
        schema = ccm.load_schema()
        self.assertIsInstance(schema, dict)
        self.assertEqual(schema.get("type"), "object")

    def test_the_root_and_the_client_object_are_closed(self) -> None:
        schema = ccm.load_schema()
        self.assertIs(schema.get("additionalProperties"), False)
        client = schema["properties"]["clients"]["items"]
        self.assertIs(client.get("additionalProperties"), False)
        self.assertIs(client["properties"]["stages"].get("additionalProperties"), False)
        self.assertIs(schema["$defs"]["stage"].get("additionalProperties"), False)

    def test_an_unknown_field_is_rejected_by_name(self) -> None:
        record = valid_record()
        record["clients"][0]["confidence"] = "high"
        problems = check(record)
        self.assertTrue(any("confidence" in problem for problem in problems))

    def test_an_unknown_field_inside_a_stage_is_rejected(self) -> None:
        record = valid_record()
        record["clients"][0]["stages"]["load"]["notes"] = "looked fine"
        problems = check(record)
        self.assertTrue(any("notes" in problem for problem in problems))

    def test_the_schema_pins_exactly_ten_client_rows(self) -> None:
        schema = ccm.load_schema()
        clients = schema["properties"]["clients"]
        self.assertEqual(clients.get("minItems"), 10)
        self.assertEqual(clients.get("maxItems"), 10)

    def test_the_schema_enumerates_exactly_the_canonical_clients(self) -> None:
        schema = ccm.load_schema()
        names = schema["properties"]["clients"]["items"]["properties"]["name"]["enum"]
        self.assertEqual(set(names), set(ccm.CANONICAL_CLIENTS))

    def test_the_schema_enumerates_exactly_the_four_statuses(self) -> None:
        schema = ccm.load_schema()
        statuses = schema["properties"]["clients"]["items"]["properties"]["status"]["enum"]
        self.assertEqual(set(statuses), set(ccm.STATUSES))

    def test_the_schema_requires_all_four_stages(self) -> None:
        schema = ccm.load_schema()
        stages = schema["properties"]["clients"]["items"]["properties"]["stages"]
        self.assertEqual(set(stages["required"]), set(ccm.STAGES))

    def test_a_wrongly_typed_field_is_rejected(self) -> None:
        record = valid_record()
        record["package"]["file_count"] = "twenty-one"
        problems = check(record)
        self.assertTrue(any("expected integer" in problem for problem in problems))

    def test_a_malformed_digest_is_rejected(self) -> None:
        record = valid_record()
        record["package"]["tree_sha256"] = "not-a-digest"
        self.assertNotEqual(check(record), [])

    def test_a_missing_top_level_section_is_rejected(self) -> None:
        for field in ("package", "method", "clients", "assessed_on"):
            with self.subTest(field=field):
                record = valid_record()
                del record[field]
                problems = check(record)
                self.assertTrue(any(field in problem for problem in problems))


class FingerprintTest(unittest.TestCase):
    """The tree digest has to move when the tree does, and only then."""

    def setUp(self) -> None:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        self.package = directory / "unifi"
        (self.package / "scripts").mkdir(parents=True)
        (self.package / "plugin.json").write_text(
            json.dumps({"name": "unifi", "version": "2.0.0"}), encoding="utf-8"
        )
        (self.package / "scripts" / "client.py").write_text("print(1)\n", encoding="utf-8")
        self.baseline = ccm.package_fingerprint(self.package)

    def test_a_changed_byte_moves_the_digest(self) -> None:
        (self.package / "scripts" / "client.py").write_text("print(2)\n", encoding="utf-8")
        self.assertNotEqual(ccm.package_fingerprint(self.package), self.baseline)

    def test_a_rename_moves_the_digest_even_though_the_bytes_are_identical(self) -> None:
        # The reason relative paths are inside the hashed text: hashing the
        # file digests alone would leave a pure rename invisible.
        (self.package / "scripts" / "client.py").rename(self.package / "scripts" / "other.py")
        moved = ccm.package_fingerprint(self.package)
        self.assertEqual(moved[0], self.baseline[0])
        self.assertNotEqual(moved[1], self.baseline[1])

    def test_an_added_file_moves_the_digest_and_the_count(self) -> None:
        (self.package / "extra.md").write_text("extra\n", encoding="utf-8")
        self.assertEqual(ccm.package_fingerprint(self.package)[0], self.baseline[0] + 1)
        self.assertNotEqual(ccm.package_fingerprint(self.package)[1], self.baseline[1])

    def test_checkout_noise_does_not_move_the_digest(self) -> None:
        # Running the test suite leaves __pycache__ beside the package scripts.
        # A fingerprint that moved when tests ran would be abandoned in a week.
        cache = self.package / "scripts" / "__pycache__"
        cache.mkdir()
        (cache / "client.cpython-312.pyc").write_bytes(b"\x00\x01")
        (self.package / ".DS_Store").write_bytes(b"\x00")
        self.assertEqual(ccm.package_fingerprint(self.package), self.baseline)

    def test_bytecode_outside_the_interpreter_cache_moves_the_digest(self) -> None:
        """A fingerprint that ignores a file cannot notice the file was added.

        A blanket `.pyc`/`.pyo` suffix exclusion used to sit beside the
        directory exclusion, so a file at any depth carrying that suffix — and
        holding whatever its author liked — left this digest untouched. Only
        the interpreter's own cache directory is checkout noise.
        """
        smuggled = self.package / "skills" / "unifi-network" / "scripts" / "smuggled.pyo"
        smuggled.parent.mkdir(parents=True, exist_ok=True)
        smuggled.write_text(
            "this is not bytecode, it is arbitrary smuggled content", encoding="utf-8"
        )

        moved = ccm.package_fingerprint(self.package)

        self.assertEqual(moved[0], self.baseline[0] + 1)
        self.assertNotEqual(moved[1], self.baseline[1])

    def test_the_digest_is_stable_across_runs(self) -> None:
        self.assertEqual(ccm.package_fingerprint(self.package), self.baseline)

    def test_a_missing_package_directory_is_reported_not_crashed(self) -> None:
        with self.assertRaises(ccm.MatrixError):
            ccm.package_fingerprint(self.package / "absent")

    def test_a_package_with_no_manifest_is_reported(self) -> None:
        (self.package / "plugin.json").unlink()
        with self.assertRaises(ccm.MatrixError):
            ccm.package_identity(self.package)


class PackageBindingTest(unittest.TestCase):
    """A matrix must identify the tree it assessed, not merely look like it.

    Every case here passed validation before the binding existed. The digest
    case is the one the review actually hit: a well-formed 64-character digest
    of a package that had been replaced.
    """

    def test_a_wellformed_digest_of_the_wrong_tree_fails(self) -> None:
        record = valid_record()
        record["package"]["tree_sha256"] = "9" * 64
        problems = check(record)
        self.assertTrue(any("tree_sha256" in problem for problem in problems))
        self.assertTrue(any("does not describe the shipped tree" in p for p in problems))

    def test_a_wrong_file_count_fails(self) -> None:
        record = valid_record()
        record["package"]["file_count"] = FAKE_FILE_COUNT + 2
        problems = check(record)
        self.assertTrue(any("file_count" in problem for problem in problems))

    def test_the_failure_says_the_assessment_must_be_re_run_not_renumbered(self) -> None:
        record = valid_record()
        record["package"]["file_count"] = FAKE_FILE_COUNT + 2
        problems = check(record)
        self.assertTrue(any("re-run rather than renumbered" in p for p in problems))

    def test_a_wrong_package_name_fails(self) -> None:
        record = valid_record()
        record["package"]["name"] = "unifi-portable"
        problems = check(record)
        self.assertTrue(any("$.package.name" in problem for problem in problems))

    def test_a_wrong_package_version_fails(self) -> None:
        record = valid_record()
        record["package"]["version"] = "1.9.0"
        problems = check(record)
        self.assertTrue(any("$.package.version" in problem for problem in problems))

    def test_a_matching_fingerprint_passes(self) -> None:
        self.assertEqual(check(valid_record()), [])

    def test_a_record_with_no_package_section_binds_to_nothing_and_fails(self) -> None:
        record = valid_record()
        del record["package"]
        problems = ccm.check_package_binding(record, FAKE_CONFIG)
        self.assertTrue(any("nothing binds the record to a tree" in p for p in problems))

    def test_the_fingerprint_flag_reports_the_live_package(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ccm.main([ccm.FINGERPRINT_FLAG, REAL_CONFIG.name]), 0)
        printed = output.getvalue()
        file_count, tree_sha256 = ccm.package_fingerprint(REAL_CONFIG.package_directory)
        self.assertIn(f"file_count: {file_count}", printed)
        self.assertIn(f"tree_sha256: {tree_sha256}", printed)

    def test_the_fingerprint_flag_refuses_to_guess_a_package(self) -> None:
        """A fingerprint copied into a record must name the tree it came from.

        Defaulting to one package would make the first-ported package the
        silent one, which is the same class of mistake as a digest that is well
        formed and binds to nothing.
        """
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ccm.main([ccm.FINGERPRINT_FLAG]), 1)
        self.assertIn("needs a package name", output.getvalue())

    def test_the_fingerprint_flag_refuses_an_unported_package(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ccm.main([ccm.FINGERPRINT_FLAG, "not-a-package"]), 1)
        self.assertIn("no port descriptor", output.getvalue())


class PackageResolutionTest(unittest.TestCase):
    """The record names the package; the descriptor says where it lives.

    Resolution has to fail closed. A record naming a package this repository
    does not port must be refused, never quietly validated against whichever
    package happens to be first: with one package in the catalog a fallback
    still fails further down on the fingerprint, so it looks harmless, and with
    two it would validate one package's matrix against another package's tree.
    """

    def test_a_record_naming_an_unported_package_is_refused(self) -> None:
        record = valid_record(
            package={
                "name": "not-a-package",
                "version": "2.0.0",
                "file_count": FAKE_FILE_COUNT,
                "tree_sha256": FAKE_TREE_SHA256,
            }
        )
        config, problems = ccm.resolve_config(record, ROOT)
        self.assertIsNone(config, "resolution fell back to another package")
        self.assertTrue(any("no port descriptor" in problem for problem in problems))

    def test_resolution_never_returns_a_package_the_record_did_not_name(self) -> None:
        """The sharper statement of the same rule, as a property over the catalog."""
        for name in ("not-a-package", "unifi-", "UNIFI", "../unifi"):
            with self.subTest(name=name):
                record = valid_record(package={"name": name, "version": "1.0"})
                config, problems = ccm.resolve_config(record, ROOT)
                self.assertTrue(problems, f"{name!r} resolved with no problem reported")
                if config is not None:
                    self.assertEqual(config.name, name)

    def test_a_record_with_no_package_name_is_refused(self) -> None:
        for value in (None, "", "   ", 3, []):
            with self.subTest(value=value):
                record = valid_record(package={"name": value, "version": "1.0"})
                config, problems = ccm.resolve_config(record, ROOT)
                self.assertIsNone(config)
                self.assertTrue(problems)

    def test_a_named_package_resolves_to_its_own_tree(self) -> None:
        record = valid_record(package={"name": "unifi", "version": "1.0"})
        config, problems = ccm.resolve_config(record, ROOT)
        self.assertEqual(problems, [])
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.package_directory, ROOT / "plugins" / "unifi")

    def test_an_unresolvable_record_still_has_its_other_rules_applied(self) -> None:
        """One resolution failure must not silently drop nine other problems."""
        record = valid_record(
            package={
                "name": "not-a-package",
                "version": "2.0.0",
                "file_count": FAKE_FILE_COUNT,
                "tree_sha256": FAKE_TREE_SHA256,
            }
        )
        record["clients"] = [
            valid_client(name, reason="") for name in ccm.CANONICAL_CLIENTS
        ]
        document = write_document(record)
        try:
            problems = ccm.check_matrix(document)
        finally:
            document.unlink()
        self.assertTrue(any("no port descriptor" in problem for problem in problems))
        self.assertTrue(any("no concrete reason" in problem for problem in problems))

    def test_there_is_no_flag_that_rewrites_the_record(self) -> None:
        # A one-keystroke refresh would let a stale matrix pass by editing the
        # evidence to match the tree, which is the failure being repaired.
        source = Path(ccm.__file__).read_text(encoding="utf-8")
        for forbidden in ("--update", "--fix", "--write", "--refresh"):
            self.assertNotIn(f'"{forbidden}"', source)


class DocumentStatusTest(unittest.TestCase):
    """Supersession is the only exemption, and it carries obligations."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, True)

    def write(self, name: str, record: dict, preamble: str) -> Path:
        path = self.directory / name
        path.write_text(as_document(record, preamble), encoding="utf-8")
        return path

    def stale_record(self) -> dict:
        record = valid_record()
        record["package"]["file_count"] = FAKE_FILE_COUNT + 5
        record["package"]["tree_sha256"] = "1" * 64
        return record

    def current_successor(self, name: str = "successor.md") -> Path:
        return self.write(name, valid_record(), "# Current\n\n")

    def test_status_defaults_to_current_so_the_binding_is_fail_closed(self) -> None:
        path = self.write("no-directive.md", self.stale_record(), "# Matrix\n\n")
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("tree_sha256" in problem for problem in problems))

    def test_a_superseded_document_is_exempt_from_the_binding(self) -> None:
        self.current_successor()
        path = self.write("old.md", self.stale_record(), superseded_preamble())
        self.assertEqual(ccm.check_matrix(path, FAKE_CONFIG), [])

    def test_a_superseded_document_still_obeys_coverage_and_redaction(self) -> None:
        self.current_successor()
        record = self.stale_record()
        record["clients"] = record["clients"][:9]
        path = self.write("old.md", record, superseded_preamble())
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("has no row" in problem for problem in problems))

    def test_marking_the_live_matrix_superseded_does_not_switch_the_binding_off(self) -> None:
        # The escape hatch has to be closed, or the repair is cosmetic: anyone
        # could dodge the binding by relabelling the current matrix.
        self.current_successor()
        path = self.write("live.md", valid_record(), superseded_preamble())
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("still identifies the package" in problem for problem in problems))

    def test_a_superseded_document_must_name_a_successor(self) -> None:
        preamble = (
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_SUPERSEDED} -->\n"
            f"<!-- {ccm.SUPERSEDED_REASON_DIRECTIVE}: because -->\n\n# Matrix\n\n"
        )
        path = self.write("old.md", self.stale_record(), preamble)
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("names no superseded-by" in problem for problem in problems))

    def test_a_superseded_document_must_record_a_reason(self) -> None:
        self.current_successor()
        preamble = (
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_SUPERSEDED} -->\n"
            f"<!-- {ccm.SUPERSEDED_BY_DIRECTIVE}: successor.md -->\n\n# Matrix\n\n"
        )
        path = self.write("old.md", self.stale_record(), preamble)
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("superseded-reason" in problem for problem in problems))

    def test_a_successor_that_does_not_exist_fails(self) -> None:
        path = self.write("old.md", self.stale_record(), superseded_preamble("nowhere.md"))
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("does not exist" in problem for problem in problems))

    def test_a_successor_that_is_itself_superseded_fails(self) -> None:
        self.write("middle.md", self.stale_record(), superseded_preamble("further.md"))
        path = self.write("old.md", self.stale_record(), superseded_preamble("middle.md"))
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("chain has to end at a current matrix" in p for p in problems))

    def test_a_document_may_not_name_itself_as_its_successor(self) -> None:
        path = self.write("old.md", self.stale_record(), superseded_preamble("old.md"))
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("its own successor" in problem for problem in problems))

    def test_a_successor_path_may_not_escape_the_evidence_directory(self) -> None:
        path = self.write("old.md", self.stale_record(), superseded_preamble("../secrets.md"))
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("plain relative name" in problem for problem in problems))

    def test_a_current_document_may_not_carry_supersession_directives(self) -> None:
        preamble = (
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_CURRENT} -->\n"
            f"<!-- {ccm.SUPERSEDED_BY_DIRECTIVE}: successor.md -->\n\n# Matrix\n\n"
        )
        path = self.write("live.md", valid_record(), preamble)
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("never both" in problem for problem in problems))

    def test_an_unrecognized_status_fails_rather_than_being_ignored(self) -> None:
        preamble = f"<!-- {ccm.STATUS_DIRECTIVE}: retired -->\n\n# Matrix\n\n"
        path = self.write("odd.md", valid_record(), preamble)
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("neither 'current' nor 'superseded'" in p for p in problems))

    def test_a_directive_inside_a_code_fence_is_an_example_not_a_declaration(self) -> None:
        # A matrix has to be able to document the directive format without the
        # documentation switching the binding off.
        fenced = (
            "# Matrix\n\nHow to retire a matrix:\n\n```\n"
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_SUPERSEDED} -->\n"
            f"<!-- {ccm.SUPERSEDED_BY_DIRECTIVE}: successor.md -->\n"
            "```\n\n"
        )
        self.assertEqual(ccm.read_directives(fenced), {})
        path = self.write("live.md", self.stale_record(), fenced)
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(any("tree_sha256" in problem for problem in problems))

    def test_the_last_declaration_of_a_key_wins(self) -> None:
        text = (
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_CURRENT} -->\n"
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_SUPERSEDED} -->\n"
        )
        self.assertEqual(ccm.read_directives(text)[ccm.STATUS_DIRECTIVE], ccm.STATUS_SUPERSEDED)


class MatrixDiscoveryTest(unittest.TestCase):
    """Which documents the no-argument run validates."""

    def test_both_committed_matrices_are_discovered(self) -> None:
        found = {path.name for path in ccm.matrix_documents()}
        self.assertIn(LIVE_DOCUMENT.name, found)
        self.assertIn(SUPERSEDED_DOCUMENT.name, found)

    def test_other_evidence_documents_are_not_treated_as_matrices(self) -> None:
        found = {path.name for path in ccm.matrix_documents()}
        self.assertNotIn(READBACK_DOCUMENT.name, found)

    def test_a_document_with_no_record_is_not_a_matrix(self) -> None:
        self.assertFalse(ccm.is_matrix_document("# Notes\n\nNo record here.\n"))

    def test_a_record_without_clients_is_not_a_matrix(self) -> None:
        self.assertFalse(ccm.is_matrix_document("```json\n{\"package\": {}}\n```\n"))


class LiveDocumentTest(unittest.TestCase):
    """The committed matrix, checked as the operator would check it."""

    def setUp(self) -> None:
        self.record = ccm.extract_record(LIVE_DOCUMENT.read_text(encoding="utf-8"))

    def test_the_committed_matrix_passes_every_check(self) -> None:
        self.assertEqual(ccm.check_matrix(LIVE_DOCUMENT), [])

    def test_the_committed_matrix_covers_exactly_the_ten_clients(self) -> None:
        names = {client["name"] for client in self.record["clients"]}
        self.assertEqual(names, set(ccm.CANONICAL_CLIENTS))

    def test_the_committed_matrix_records_forty_stage_results(self) -> None:
        results = [
            stage["result"]
            for client in self.record["clients"]
            for stage in client["stages"].values()
        ]
        self.assertEqual(len(results), 40)
        self.assertTrue(set(results) <= set(ccm.STAGE_RESULTS))

    def test_the_committed_matrix_records_ten_overall_statuses(self) -> None:
        statuses = [client["status"] for client in self.record["clients"]]
        self.assertEqual(len(statuses), 10)
        self.assertTrue(set(statuses) <= set(ccm.STATUSES))

    def test_the_committed_matrix_records_no_confirmed_or_mutating_invocation(self) -> None:
        self.assertEqual(ccm.check_safety_rules(self.record, REAL_CONFIG), [])

    def test_the_committed_matrix_leaks_nothing(self) -> None:
        self.assertEqual(ccm.check_public_evidence_rules(self.record), [])

    def test_every_client_carries_a_reason_for_its_status(self) -> None:
        for client in self.record["clients"]:
            with self.subTest(client=client["name"]):
                self.assertTrue(client["reason"].strip())

    def test_the_schema_referenced_by_the_record_exists(self) -> None:
        referenced = (LIVE_DOCUMENT.parent / self.record["$schema"]).resolve()
        self.assertEqual(referenced, SCHEMA_PATH.resolve())
        self.assertTrue(referenced.is_file())

    def test_the_command_line_entrypoint_reports_success(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ccm.main([str(LIVE_DOCUMENT)]), 0)
        self.assertIn("validation passed", output.getvalue())

    def test_the_command_line_entrypoint_reports_failure(self) -> None:
        record = valid_record()
        record["clients"][0]["status"] = "mostly-works"
        document = write_document(record)
        try:
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(ccm.main([str(document)]), 1)
        finally:
            document.unlink()
        self.assertIn("mostly-works", output.getvalue())

    def test_the_committed_matrix_is_current(self) -> None:
        directives = ccm.read_directives(LIVE_DOCUMENT.read_text(encoding="utf-8"))
        self.assertEqual(directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_CURRENT)

    def test_the_committed_matrix_identifies_the_shipped_package(self) -> None:
        file_count, tree_sha256 = ccm.package_fingerprint(REAL_CONFIG.package_directory)
        name, version = ccm.package_identity(REAL_CONFIG.package_directory)
        self.assertEqual(self.record["package"]["file_count"], file_count)
        self.assertEqual(self.record["package"]["tree_sha256"], tree_sha256)
        self.assertEqual(self.record["package"]["name"], name)
        self.assertEqual(self.record["package"]["version"], version)

    def test_the_committed_matrix_records_the_repaired_invocation_stage(self) -> None:
        # The defect this document was re-run to fix: it reported every
        # invocation aborting at import, against a package whose entrypoints run.
        #
        # The count is pinned deliberately. It moved from 8 to 9 when Cursor Agent
        # was reassessed against the operator's real home: the earlier run exported
        # an empty scratch home for isolation, which stripped that client's
        # authentication and recorded a client failure that was an artifact of the
        # harness. A pinned count fails when a row's status changes, which forces
        # someone to look at why -- that is the point of pinning it rather than
        # asserting "more than zero".
        invocations = [
            client["stages"]["invocation"]
            for client in self.record["clients"]
            if client["stages"]["invocation"]["result"] == "executed"
        ]
        self.assertEqual(len(invocations), 9)
        for stage in invocations:
            self.assertNotIn("ModuleNotFoundError", stage["evidence"])
            self.assertIn("Exit status 0", stage["evidence"])

    def test_the_no_argument_run_validates_every_committed_matrix(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ccm.main([]), 0)
        printed = output.getvalue()
        self.assertIn(f"{LIVE_DOCUMENT.name} ({ccm.STATUS_CURRENT})", printed)
        self.assertIn(f"{SUPERSEDED_DOCUMENT.name} ({ccm.STATUS_SUPERSEDED})", printed)


class SupersededDocumentTest(unittest.TestCase):
    """The pre-repair matrix, kept as history rather than deleted."""

    def setUp(self) -> None:
        self.text = SUPERSEDED_DOCUMENT.read_text(encoding="utf-8")
        self.directives = ccm.read_directives(self.text)

    def test_it_exists_and_still_validates(self) -> None:
        self.assertTrue(SUPERSEDED_DOCUMENT.is_file())
        self.assertEqual(ccm.check_matrix(SUPERSEDED_DOCUMENT), [])

    def test_it_declares_itself_superseded_and_names_the_current_matrix(self) -> None:
        self.assertEqual(self.directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED)
        self.assertEqual(
            self.directives.get(ccm.SUPERSEDED_BY_DIRECTIVE), LIVE_DOCUMENT.name
        )
        self.assertTrue(self.directives.get(ccm.SUPERSEDED_REASON_DIRECTIVE, "").strip())

    def test_it_no_longer_describes_the_shipped_package(self) -> None:
        record = ccm.extract_record(self.text)
        self.assertNotEqual(ccm.check_package_binding(record, REAL_CONFIG), [])

    def test_it_preserves_the_original_record_it_was_published_with(self) -> None:
        record = ccm.extract_record(self.text)
        self.assertEqual(record["package"]["file_count"], 21)
        self.assertEqual(
            record["package"]["tree_sha256"],
            "92ed503207ca6eabfc5a70a892d682ee0030ad0d16db2db436abfb83f7fa240b",
        )

    def test_the_current_matrix_points_back_at_it(self) -> None:
        self.assertIn(SUPERSEDED_DOCUMENT.name, LIVE_DOCUMENT.read_text(encoding="utf-8"))


class ReadbackEvidenceTest(unittest.TestCase):
    """The post-activation readback evidence, bound the same way the matrix is.

    Capturing a readback once and letting it drift would rebuild the defect the
    matrix had, so the fingerprint it records is recomputed here too.
    """

    def setUp(self) -> None:
        self.text = READBACK_DOCUMENT.read_text(encoding="utf-8")
        self.record = ccm.extract_record(self.text)

    def test_the_document_exists(self) -> None:
        self.assertTrue(READBACK_DOCUMENT.is_file())

    def test_the_recorded_release_fingerprint_identifies_the_shipped_package(self) -> None:
        file_count, tree_sha256 = ccm.package_fingerprint(REAL_CONFIG.package_directory)
        name, version = ccm.package_identity(REAL_CONFIG.package_directory)
        release = self.record["release"]
        self.assertEqual(release["file_count"], file_count)
        self.assertEqual(release["tree_sha256"], tree_sha256)
        self.assertEqual(release["name"], name)
        self.assertEqual(release["version"], version)

    def test_the_recorded_unit_fingerprints_identify_the_shipped_skill_units(self) -> None:
        for unit, recorded in self.record["release"]["units"].items():
            with self.subTest(unit=unit):
                file_count, tree_sha256 = ccm.package_fingerprint(
                    PACKAGE_ROOT / "skills" / unit
                )
                self.assertEqual(recorded["file_count"], file_count)
                self.assertEqual(recorded["tree_sha256"], tree_sha256)

    def test_the_recorded_upstream_commit_matches_the_synchronization_pin(self) -> None:
        provenance = json.loads(
            (PACKAGE_ROOT / "PROVENANCE.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            self.record["release"]["upstream_commit"], provenance["source_commit"]
        )
        self.assertEqual(self.record["release"]["version"], provenance["source_version"])

    def test_every_readback_reports_bytes_equal_to_the_release(self) -> None:
        readbacks = self.record["readbacks"]
        self.assertTrue(readbacks)
        for readback in readbacks:
            with self.subTest(client=readback["client"]):
                self.assertTrue(readback["matches_release"])
                self.assertTrue(readback["entrypoints_exit_zero"])

    def test_all_three_profile_states_are_recorded(self) -> None:
        states = {state["state"]: state for state in self.record["profile_states"]}
        self.assertEqual(set(states), {"absent", "present", "unreadable"})
        self.assertEqual(states["absent"]["exit_status"], 0)
        self.assertEqual(states["absent"]["mode"], "discovery-only")
        self.assertEqual(states["present"]["exit_status"], 0)
        self.assertEqual(states["present"]["mode"], "profile")
        self.assertEqual(states["unreadable"]["exit_status"], 1)
        self.assertFalse(states["unreadable"]["fell_back_to_discovery_only"])

    def test_the_readback_leaks_nothing(self) -> None:
        self.assertEqual(ccm.check_public_evidence_rules(self.record), [])


if __name__ == "__main__":
    unittest.main()
