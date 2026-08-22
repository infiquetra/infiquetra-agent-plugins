"""Tests for the ten-client compatibility matrix validator.

The validator exists because prose cannot enforce coverage. These tests pin the
two things that matter and pull in opposite directions:

* A row that looks covered but is not must fail — a missing stage, a renamed
  client, an executed stage with no evidence, a status outside the four.
* A row that honestly records a bad outcome must pass — ``unsupported`` and
  ``failed`` are results, not defects. Coverage is mandatory; passing is not.

Standard library only, matching the validator and the repository baseline.
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
sys.path.insert(0, str(ROOT / "scripts"))

import check_compatibility_matrix as ccm  # noqa: E402


LIVE_DOCUMENT = ROOT / "docs" / "evidence" / "2026-08-22-unifi-compatibility-matrix.md"
SCHEMA_PATH = ROOT / "schemas" / "compatibility-matrix.schema.json"


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
            "file_count": 21,
            "tree_sha256": "0" * 64,
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


def write_document(record: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    )
    handle.write(as_document(record))
    handle.close()
    return Path(handle.name)


def check(record: dict) -> list[str]:
    """Every problem the validator finds in a record, via a real document."""
    document = write_document(record)
    try:
        return ccm.check_matrix(document)
    finally:
        document.unlink()


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
        record = valid_record()
        record["package"]["tree_sha256"] = "ab" * 32
        self.assertEqual(check(record), [])


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
        self.assertEqual(ccm.check_safety_rules(self.record), [])

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


if __name__ == "__main__":
    unittest.main()
