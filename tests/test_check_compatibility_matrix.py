"""Tests for the ten-client compatibility matrix validator.

The validator exists because prose cannot enforce coverage. These tests pin the
two things that matter and pull in opposite directions:

* A row that looks covered but is not must fail — a missing stage, a renamed
  client, an executed stage with no evidence, a status outside the four.
* A row that honestly records a bad outcome must pass — ``unsupported`` and
  ``failed`` are results, not defects. Coverage is mandatory; passing is not.

A third pull was added after a review found the matrix describing a package that
no longer existed while passing every check:

* A record whose fingerprint does not identify the assessed tree is reported,
  not failed, when the package version still matches. A version that moved
  with no fresh run still fails. Declaring a document superseded is the
  exemption from the binding, and the tests below pin both that the exemption
  works and that it cannot be turned on the live matrix.

Standard library only, matching the validator and the repository baseline.
"""

from __future__ import annotations

import atexit
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_compatibility_matrix as ccm  # noqa: E402
import port_config  # noqa: E402
import sync_vendor_source as svs  # noqa: E402

#: The client extension directory, read from the module that owns the name
#: rather than spelled again here.
EXTENSION_DIRECTORY = svs.PORTABLE_PACKAGE_ROOT_MARKER


EVIDENCE = ROOT / "docs" / "evidence"


def assert_version_binds_and_a_moved_tree_is_only_reported(
    test: unittest.TestCase,
    recorded: dict,
    config: port_config.PortConfig,
) -> None:
    """The released version is the binding. A fingerprint move under it is reported.

    Rewriting the evidence so the digest matches the tree is what the
    2026-09-22 rule refuses. ``split_binding_problems`` is the partition the
    checker uses: a wrong name or version fails, and file count and tree
    digest are reports.
    """
    file_count, tree_sha256 = ccm.package_fingerprint(config.package_directory)
    name, version = ccm.package_identity(config.package_directory, config.package_manifest)
    test.assertEqual(recorded.get("name"), name)
    test.assertEqual(recorded.get("version"), version)
    failures, reports = ccm.split_binding_problems(
        ccm.check_package_binding({"package": recorded}, config)
    )
    test.assertEqual(failures, [])
    moved = recorded.get("file_count") != file_count or recorded.get("tree_sha256") != tree_sha256
    if moved:
        test.assertTrue(reports, "a tree that moved under an unchanged version must be reported")
    else:
        test.assertEqual(reports, [])
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


def check_with_reports(
    record: dict, preamble: str = "# Matrix\n\nProse first.\n\n"
) -> tuple[list[str], list[str]]:
    """The problems and the non-failing reports, from one run over a document."""
    document = write_document(record, preamble)
    reports: list[str] = []
    try:
        return ccm.check_matrix(document, FAKE_CONFIG, reports=reports), reports
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

    def test_a_non_executed_stage_command_must_still_match_its_first_status(self) -> None:
        """Blocked stages carry `commands`; skipping them left the alias unenforced.

        The version-2 executed-only continue meant a blocked row could name one
        command in `command` and a different first command in `commands`, and
        the validator reported no problem.
        """
        extras = {
            "blocked": {"reason": "No result within the 60s deadline."},
            "not-applicable": {"reason": "This client has no invocation path."},
        }
        for result, extra in extras.items():
            with self.subTest(result=result):
                record = self.version_two()
                record["clients"][0]["stages"]["invocation"] = {
                    "result": result,
                    "command": "client run --json",
                    "commands": [{"command": "other command entirely", "exit_status": 0}],
                    **extra,
                }
                problems = check(record)
                self.assertTrue(
                    any("disagree about what ran first" in problem for problem in problems),
                    f"{result} stage was allowed to name two different first commands; "
                    f"got {problems}",
                )

    def test_a_blocked_stage_still_has_its_commands_safety_graded(self) -> None:
        """A stage that hit its deadline started commands, and they are graded.

        The harness records the timed-out command with `timed_out: true`, on a
        stage whose result is `blocked`. If safety grading only looked at
        `executed` stages, the one command most likely to have been doing
        something unbounded would be the one command nobody checked.
        """
        operation = sorted(REAL_CONFIG.assessment.mutating_operations)[0]
        script = REAL_CONFIG.assessment.package_scripts[0]
        unsafe = f"python3 <package>/{script} {operation}"
        record = self.version_two()
        record["clients"][0]["stages"]["invocation"] = {
            "result": "blocked",
            "command": "client run --json",
            "commands": [
                {"command": "client run --json", "exit_status": 0},
                {"command": unsafe, "timed_out": True},
            ],
            "reason": "No result within the 60s deadline.",
        }
        problems = check(record)
        self.assertTrue(
            any(operation in problem for problem in problems),
            f"the timed-out command was never safety-graded; got {problems}",
        )

    def test_a_blocked_stage_needs_no_commands(self) -> None:
        """Nothing ran, so there is nothing to record; this must not be an error."""
        record = self.version_two()
        record["clients"][0]["stages"]["invocation"] = blocked_stage()
        self.assertFalse(any(self.NO_STATUSES in problem for problem in check(record)))

    def test_a_deadline_killed_command_is_accepted_without_an_exit_status(self) -> None:
        record = self.version_two()
        record["clients"][0]["stages"]["invocation"] = {
            "result": "blocked",
            "command": "client run --json",
            "commands": [{"command": "client run --json", "timed_out": True}],
            "reason": "No result within the 60s deadline.",
        }
        self.assertEqual(check(record), [])

    def test_exit_status_negative_one_is_sighup_and_is_accepted(self) -> None:
        """-1 is a real wait status. Forbidding it would confuse SIGHUP with a lie."""
        record = self.version_two()
        record["clients"][0]["stages"]["placement"]["commands"][0]["exit_status"] = -1
        self.assertEqual(check(record), [])

    def test_a_command_cannot_carry_both_exit_status_and_timed_out(self) -> None:
        record = self.version_two()
        record["clients"][0]["stages"]["placement"]["commands"][0]["timed_out"] = True
        problems = check(record)
        self.assertTrue(
            any("timed_out and no exit_status" in problem for problem in problems),
            f"a command with both endings was accepted; got {problems}",
        )

    def test_a_command_must_say_how_it_ended(self) -> None:
        record = self.version_two()
        command = record["clients"][0]["stages"]["placement"]["command"]
        record["clients"][0]["stages"]["placement"]["commands"] = [{"command": command}]
        problems = check(record)
        self.assertTrue(
            any("neither exit_status nor timed_out" in problem for problem in problems),
            f"a command with no ending was accepted; got {problems}",
        )


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

    def test_a_wellformed_digest_of_the_wrong_tree_is_still_detected(self) -> None:
        record = valid_record()
        record["package"]["tree_sha256"] = "9" * 64
        problems = ccm.check_package_binding(record, FAKE_CONFIG)
        self.assertTrue(any("tree_sha256" in problem for problem in problems))
        self.assertTrue(any("does not describe the shipped tree" in p for p in problems))

    def test_a_wrong_file_count_is_still_detected(self) -> None:
        record = valid_record()
        record["package"]["file_count"] = FAKE_FILE_COUNT + 2
        problems = ccm.check_package_binding(record, FAKE_CONFIG)
        self.assertTrue(any("file_count" in problem for problem in problems))

    def test_the_message_says_the_assessment_must_be_re_run_not_renumbered(self) -> None:
        record = valid_record()
        record["package"]["file_count"] = FAKE_FILE_COUNT + 2
        problems = ccm.check_package_binding(record, FAKE_CONFIG)
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


class ClientExtensionRedactionTest(unittest.TestCase):
    """The client extension directory must stay a directory, not read as a host.

    The redaction rule reports dotted tokens in evidence as hostnames. The
    client extension directory is spelled in reverse-domain form
    (`com.infiquetra.claude`), so it has to be collected as a known
    non-host token or every matrix that mentions it fails redaction.

    It used to be collected from the port descriptors alone. Under the
    2026-09-22 custody decision every descriptor becomes authored and states no
    `source`, so that reading returns nothing and the directory reads as a
    hostname again -- in a catalog whose own evidence is full of it. The
    package trees are therefore read as well.

    The cycle-17 mutation campaign found this guard untested: deleting the tree
    scan survived. These tests are that gap closed.
    """

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, True)

    def package_with_extension(self, name: str = "example") -> None:
        extension = self.directory / "plugins" / name / EXTENSION_DIRECTORY
        extension.mkdir(parents=True)
        (extension / "plugin.json").write_text("{}", encoding="utf-8")

    def test_the_directory_is_collected_from_the_package_trees(self) -> None:
        self.package_with_extension()
        self.assertIn(EXTENSION_DIRECTORY, ccm.non_host_dotted_tokens(self.directory))

    def test_it_is_collected_even_when_no_descriptor_names_it(self) -> None:
        """Which is every package's state once custody has moved here."""
        self.package_with_extension()
        self.assertEqual(port_config.available(self.directory), [])
        self.assertIn(EXTENSION_DIRECTORY, ccm.non_host_dotted_tokens(self.directory))

    def test_an_ordinary_package_directory_is_not_collected(self) -> None:
        """Only reverse-domain names are directories; the rest stay hostnames."""
        package = self.directory / "plugins" / "example" / "scripts"
        package.mkdir(parents=True)
        self.assertEqual(ccm.non_host_dotted_tokens(self.directory), frozenset())

    def test_the_committed_catalog_still_declares_the_directory(self) -> None:
        self.assertIn(EXTENSION_DIRECTORY, ccm.non_host_dotted_tokens(ROOT))


class VersionBoundEvidenceTest(unittest.TestCase):
    """Evidence binds to a released version, not to every tree (2026-09-22).

    For a derived package every byte came from one pin, so a moved fingerprint
    meant a moved pin and failing on it was right. An authored package's tree
    moves on every commit -- a typo fixed in a README moves it -- and a
    per-commit ten-client run is not a standard anyone will keep. Left as a
    failure the rule would be switched off within a week, which is worse than a
    rule that reports.

    So the version fails and the fingerprint reports. Both halves are pinned
    here, including that nothing is silently dropped.
    """

    def test_a_version_bump_without_a_fresh_run_fails(self) -> None:
        record = valid_record()
        record["package"]["version"] = "1.9.0"
        problems, _reports = check_with_reports(record)
        self.assertTrue(any(p.startswith(ccm.VERSION_PROBLEM_PREFIX) for p in problems))

    def test_a_moved_tree_under_an_unchanged_version_does_not_fail(self) -> None:
        record = valid_record()
        record["package"]["tree_sha256"] = "9" * 64
        record["package"]["file_count"] = FAKE_FILE_COUNT + 2
        problems, _reports = check_with_reports(record)
        self.assertEqual(problems, [])

    def test_a_moved_tree_is_reported_rather_than_dropped(self) -> None:
        """Not failing is not the same as not saying anything."""
        record = valid_record()
        record["package"]["tree_sha256"] = "9" * 64
        record["package"]["file_count"] = FAKE_FILE_COUNT + 2
        _problems, reports = check_with_reports(record)
        self.assertTrue(any("tree_sha256" in report for report in reports))
        self.assertTrue(any("file_count" in report for report in reports))

    def test_the_report_says_the_next_release_needs_a_fresh_run(self) -> None:
        record = valid_record()
        record["package"]["tree_sha256"] = "9" * 64
        _problems, reports = check_with_reports(record)
        self.assertTrue(any("fresh run" in report for report in reports))

    def test_every_binding_problem_is_either_a_failure_or_a_report(self) -> None:
        """The partition is total, so no rule is turned off by being forgotten."""
        record = valid_record()
        record["package"]["version"] = "1.9.0"
        record["package"]["name"] = "unifi-portable"
        record["package"]["tree_sha256"] = "9" * 64
        record["package"]["file_count"] = FAKE_FILE_COUNT + 2
        everything = ccm.check_package_binding(record, FAKE_CONFIG)
        failures, reports = ccm.split_binding_problems(everything)
        self.assertEqual(sorted(failures + reports), sorted(everything))
        self.assertEqual(len(everything), 4)

    def test_the_version_is_the_only_binding_field_that_fails(self) -> None:
        record = valid_record()
        record["package"]["tree_sha256"] = "9" * 64
        record["package"]["file_count"] = FAKE_FILE_COUNT + 2
        failures, _reports = ccm.split_binding_problems(
            ccm.check_package_binding(record, FAKE_CONFIG)
        )
        self.assertEqual(failures, [])

    def test_a_package_with_no_matrix_at_all_is_allowed(self) -> None:
        """Voice ships none today, and shipping none is not a defect.

        Discovery is over the evidence documents that exist, so a package with
        no matrix contributes no document and no problem. Asserted rather than
        assumed: a later change that made a missing matrix a failure would make
        every authored package fail on the day it lands.
        """
        documents = ccm.matrix_documents()
        assessed = set()
        for document in documents:
            record = ccm.extract_record(document.read_text(encoding="utf-8"))
            assessed.add(record["package"]["name"])
        unassessed = {
            path.name
            for path in (ROOT / "plugins").iterdir()
            if path.is_dir() and path.name not in assessed
        }
        self.assertTrue(unassessed, "every package has a matrix, so this proves nothing")
        for document in documents:
            with self.subTest(document=document.name):
                self.assertEqual(ccm.check_matrix(document), [])

    def test_the_report_wording_matches_the_run_it_belongs_to(self) -> None:
        """A report may not say the version matches while the version failed."""
        record = valid_record()
        record["package"]["version"] = "1.9.0"
        record["package"]["tree_sha256"] = "9" * 64
        _problems, reports = check_with_reports(record)
        self.assertTrue(reports)
        for report in reports:
            self.assertNotIn("the recorded version still matches", report)


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
        """A record the binding rejects: a different release *and* a moved tree.

        The version is what moved it from "reported" to "failed" after the
        2026-09-22 rule change. Both fields are stale because a superseded
        matrix in practice is both, and the supersession tests below have to be
        exempting a document that really would fail.
        """
        record = valid_record()
        record["package"]["version"] = "1.9.0"
        record["package"]["file_count"] = FAKE_FILE_COUNT + 5
        record["package"]["tree_sha256"] = "1" * 64
        return record

    def current_successor(self, name: str = "successor.md") -> Path:
        return self.write(name, valid_record(), "# Current\n\n")

    def test_status_defaults_to_current_so_the_binding_is_fail_closed(self) -> None:
        path = self.write("no-directive.md", self.stale_record(), "# Matrix\n\n")
        problems = ccm.check_matrix(path, FAKE_CONFIG)
        self.assertTrue(
            any(problem.startswith(ccm.VERSION_PROBLEM_PREFIX) for problem in problems)
        )

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
        self.assertTrue(
            any("none of 'current', 'superseded', 'notice'" in p for p in problems)
        )

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
        self.assertTrue(
            any(problem.startswith(ccm.VERSION_PROBLEM_PREFIX) for problem in problems)
        )

    def test_the_last_declaration_of_a_key_wins(self) -> None:
        text = (
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_CURRENT} -->\n"
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_SUPERSEDED} -->\n"
        )
        self.assertEqual(ccm.read_directives(text)[ccm.STATUS_DIRECTIVE], ccm.STATUS_SUPERSEDED)


def notice_preamble() -> str:
    return f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_NOTICE} -->\n\n# Notice\n\n"


NOTICE_RECORD = {"notice": "no ten-client run yet"}


class NoticeStatusTest(unittest.TestCase):
    """A notice performs no assessment, and the checker has to treat it that way.

    Added with the 2026-09-22 "explicit notice state for compatibility
    evidence" decision: three documents under `docs/evidence/` explained why no
    live matrix exists yet without embedding a `$.package`/`$.clients` record,
    and were marked (or would have defaulted to) `current` all the same. A
    notice closes that gap: it is a valid `superseded-by` target, it is never
    treated as a matrix, and it is never counted as a current matrix.
    """

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, True)

    def write(self, name: str, text: str) -> Path:
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_well_formed_notice_has_no_document_status_problems(self) -> None:
        """The notice branch itself: no binding, no supersession obligations."""
        text = notice_preamble() + "```json\n" + json.dumps(NOTICE_RECORD) + "\n```\n"
        path = self.write("notice.md", text)
        record = ccm.extract_record(text)
        problems = ccm.check_document_status(text, record, path, FAKE_CONFIG)
        self.assertEqual(problems, [])

    def test_a_notice_is_never_treated_as_a_matrix(self) -> None:
        text = notice_preamble() + "```json\n" + json.dumps(NOTICE_RECORD) + "\n```\n"
        self.write("notice.md", text)
        self.assertFalse(ccm.is_matrix_document(text))
        self.assertEqual(ccm.matrix_documents(self.directory), [])

    def test_a_notice_shaped_like_a_matrix_is_still_never_a_matrix(self) -> None:
        """Even a fenced block with `package`/`clients` does not make a notice
        a matrix: the status directive controls, not the shape alone."""
        record = valid_record()
        text = notice_preamble() + "```json\n" + json.dumps(record) + "\n```\n"
        self.assertFalse(ccm.is_matrix_document(text))

    def test_a_notice_is_a_valid_supersession_target(self) -> None:
        notice_path = self.write(
            "notice.md", notice_preamble() + "```json\n" + json.dumps(NOTICE_RECORD) + "\n```\n"
        )
        # A stale record -- a different version and a moved tree -- the way a
        # real retired matrix actually is; a live-tree record here would trip
        # the separate "marking the live matrix superseded" refusal instead of
        # exercising the successor check this test targets.
        stale = valid_record()
        stale["package"]["version"] = "1.9.0"
        stale["package"]["file_count"] = FAKE_FILE_COUNT + 5
        stale["package"]["tree_sha256"] = "1" * 64
        old = self.write("old.md", superseded_preamble(notice_path.name) + as_document(stale))
        record = ccm.extract_record(old.read_text(encoding="utf-8"))
        problems = ccm.check_document_status(
            old.read_text(encoding="utf-8"), record, old, FAKE_CONFIG
        )
        self.assertEqual(problems, [])

    def test_a_notice_may_not_also_declare_supersession_directives(self) -> None:
        text = (
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_NOTICE} -->\n"
            f"<!-- {ccm.SUPERSEDED_BY_DIRECTIVE}: elsewhere.md -->\n\n# Notice\n\n"
            "```json\n" + json.dumps(NOTICE_RECORD) + "\n```\n"
        )
        path = self.write("notice.md", text)
        record = ccm.extract_record(text)
        problems = ccm.check_document_status(text, record, path, FAKE_CONFIG)
        self.assertTrue(any("notice is not a supersession" in p for p in problems))

    def test_an_assessment_free_document_marked_current_fails(self) -> None:
        self.write(
            "stale-current.md",
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_CURRENT} -->\n\n# Notice\n\n"
            "```json\n" + json.dumps(NOTICE_RECORD) + "\n```\n",
        )
        problems = ccm.check_notice_discipline(self.directory)
        self.assertTrue(
            any(
                "stale-current.md" in p and "embeds no machine-readable" in p
                for p in problems
            )
        )

    def test_an_assessment_free_document_with_no_directive_also_fails(self) -> None:
        """`matrix-status` defaults to `current`, so silence is not an escape."""
        self.write(
            "no-directive.md",
            "# Notice\n\n```json\n" + json.dumps(NOTICE_RECORD) + "\n```\n",
        )
        problems = ccm.check_notice_discipline(self.directory)
        self.assertTrue(
            any(
                "no-directive.md" in p and "embeds no machine-readable" in p
                for p in problems
            )
        )

    def test_a_document_marked_notice_is_never_flagged(self) -> None:
        self.write(
            "notice.md", notice_preamble() + "```json\n" + json.dumps(NOTICE_RECORD) + "\n```\n"
        )
        self.assertEqual(ccm.check_notice_discipline(self.directory), [])

    def test_a_real_matrix_marked_current_is_never_flagged(self) -> None:
        self.write("matrix.md", as_document(valid_record()))
        self.assertEqual(ccm.check_notice_discipline(self.directory), [])

    def test_a_superseded_document_with_no_record_is_not_this_rules_concern(self) -> None:
        """Out of scope for this rule: only an explicit or defaulted `current`
        claim over an assessment-free document is refused here."""
        self.write(
            "old-notice.md",
            superseded_preamble("target.md") + "```json\n" + json.dumps(NOTICE_RECORD) + "\n```\n",
        )
        problems = ccm.check_notice_discipline(self.directory)
        self.assertEqual(problems, [])

    def test_the_three_committed_notices_declare_themselves_notices(self) -> None:
        for name in (
            "2026-08-27-agent-launcher-compatibility-matrix.md",
            "2026-09-22-unifi-authored-cut.md",
            "2026-09-22-mission-control-compatibility-notice.md",
        ):
            with self.subTest(document=name):
                path = EVIDENCE / name
                self.assertTrue(path.is_file())
                text = path.read_text(encoding="utf-8")
                self.assertEqual(
                    ccm.read_directives(text).get(ccm.STATUS_DIRECTIVE), ccm.STATUS_NOTICE
                )
                self.assertFalse(ccm.is_matrix_document(text))

    def test_the_committed_evidence_directory_has_no_notice_discipline_problems(self) -> None:
        self.assertEqual(ccm.check_notice_discipline(EVIDENCE), [])


class CurrentMatrixReportTest(unittest.TestCase):
    """The per-package 'current matrix: yes/none' line the summary prints."""

    def test_unifi_has_no_current_matrix_today(self) -> None:
        # unifi's only non-superseded compatibility document is the notice
        # explaining that 2.0.7 has no ten-client run yet.
        lines = ccm.current_matrix_report(ROOT)
        self.assertIn("unifi: current matrix: none", lines)

    def test_a_package_with_no_current_matrix_reports_none(self) -> None:
        # house-style has no compatibility document at all. It declares no
        # executable entrypoint, so `scripts/assess_clients.py` refuses the
        # package rather than recording an assessment of nothing, and it stays
        # the standing example of a package that reports none. This case named
        # mission-control until the 2026-09-22 ten-client run gave that package
        # a matrix.
        lines = ccm.current_matrix_report(ROOT)
        self.assertIn("house-style: current matrix: none", lines)

    def test_every_ported_package_gets_exactly_one_line(self) -> None:
        lines = ccm.current_matrix_report(ROOT)
        names = [line.split(":", 1)[0] for line in lines]
        self.assertEqual(names, port_config.available(ROOT))

    def test_a_document_that_is_current_and_has_a_record_reports_yes(self) -> None:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        evidence = directory / "docs" / "evidence"
        evidence.mkdir(parents=True)
        ports_dir = directory / "ports"
        ports_dir.mkdir()
        (ports_dir / "unifi.json").write_text(
            (ROOT / "ports" / "unifi.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (evidence / "matrix.md").write_text(as_document(valid_record()), encoding="utf-8")
        lines = ccm.current_matrix_report(directory)
        self.assertIn("unifi: current matrix: yes", lines)


class CLIWiringTest(unittest.TestCase):
    """The command-line entrypoint actually runs the new checks, not just the
    library functions the other tests exercise directly.

    These write a throwaway file into the real evidence directory rather than
    a scratch one, because `check_notice_discipline` and `current_matrix_report`
    default to `EVIDENCE_DIRECTORY` as a bound parameter default: patching the
    module attribute after import does not change a default already captured
    at function-definition time, and `ccm.main` calls both with no arguments.
    Every write is removed in `finally`, whatever the test result.
    """

    def test_the_cli_fails_on_an_assessment_free_current_document(self) -> None:
        path = EVIDENCE / "zzz-test-only-cli-wiring-notice-discipline.md"
        self.assertFalse(path.exists(), "stray fixture from a previous run")
        path.write_text(
            f"<!-- {ccm.STATUS_DIRECTIVE}: {ccm.STATUS_CURRENT} -->\n\n# Not a matrix\n\n"
            "```json\n" + json.dumps({"notice": "no run yet"}) + "\n```\n",
            encoding="utf-8",
        )
        try:
            with redirect_stdout(io.StringIO()) as output:
                exit_code = ccm.main([])
        finally:
            path.unlink()
        self.assertEqual(exit_code, 1)
        printed = output.getvalue()
        self.assertIn("Notice discipline:", printed)
        self.assertIn(path.name, printed)
        self.assertIn("embeds no machine-readable", printed)

    def test_the_cli_prints_the_current_matrix_report(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            ccm.main([])
        printed = output.getvalue()
        self.assertIn("Current matrix by package:", printed)
        self.assertIn("unifi: current matrix: none", printed)


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

    def test_the_committed_matrix_is_superseded(self) -> None:
        """2.0.7 has no ten-client matrix. The 2026-08-22 record is history."""
        directives = ccm.read_directives(LIVE_DOCUMENT.read_text(encoding="utf-8"))
        self.assertEqual(directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED)
        successor = directives.get(ccm.SUPERSEDED_BY_DIRECTIVE)
        self.assertEqual(successor, "2026-09-22-unifi-authored-cut.md")
        assert successor is not None
        target = LIVE_DOCUMENT.parent / successor
        self.assertTrue(target.is_file())
        self.assertFalse(
            ccm.is_matrix_document(target.read_text(encoding="utf-8")),
            "the successor must not be an invented matrix",
        )
        self.assertEqual(
            ccm.read_directives(target.read_text(encoding="utf-8")).get(ccm.STATUS_DIRECTIVE),
            ccm.STATUS_NOTICE,
        )
        self.assertNotEqual(ccm.check_package_binding(self.record, REAL_CONFIG), [])

    def test_the_committed_matrix_does_not_identify_the_shipped_package(self) -> None:
        """Supersession is illegal when the record still describes this tree."""
        self.assertNotEqual(ccm.check_package_binding(self.record, REAL_CONFIG), [])

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
        self.assertIn(f"{LIVE_DOCUMENT.name} ({ccm.STATUS_SUPERSEDED})", printed)
        self.assertIn(f"{SUPERSEDED_DOCUMENT.name} ({ccm.STATUS_SUPERSEDED})", printed)
        self.assertNotIn("2026-09-22-unifi-authored-cut.md", printed)


class SupersededDocumentTest(unittest.TestCase):
    """The pre-repair matrix, kept as history rather than deleted."""

    def setUp(self) -> None:
        self.text = SUPERSEDED_DOCUMENT.read_text(encoding="utf-8")
        self.directives = ccm.read_directives(self.text)

    def test_it_exists_and_still_validates(self) -> None:
        self.assertTrue(SUPERSEDED_DOCUMENT.is_file())
        self.assertEqual(ccm.check_matrix(SUPERSEDED_DOCUMENT), [])

    def test_it_declares_itself_superseded_and_names_the_successor(self) -> None:
        """The chain ends at the authored-cut note, which is not a matrix."""
        self.assertEqual(self.directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED)
        successor = self.directives.get(ccm.SUPERSEDED_BY_DIRECTIVE)
        self.assertEqual(successor, "2026-09-22-unifi-authored-cut.md")
        assert successor is not None
        target = SUPERSEDED_DOCUMENT.parent / successor
        self.assertTrue(target.is_file())
        self.assertFalse(ccm.is_matrix_document(target.read_text(encoding="utf-8")))
        self.assertEqual(
            ccm.read_directives(target.read_text(encoding="utf-8")).get(
                ccm.STATUS_DIRECTIVE, ccm.STATUS_CURRENT
            ),
            ccm.STATUS_NOTICE,
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

    def test_the_readback_is_superseded_history(self) -> None:
        """The readback describes derived 2.0.6. It is not a claim about 2.0.7."""
        directives = ccm.read_directives(self.text)
        self.assertEqual(directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED)
        self.assertEqual(
            directives.get(ccm.SUPERSEDED_BY_DIRECTIVE), "2026-09-22-unifi-authored-cut.md"
        )
        _, version = ccm.package_identity(
            REAL_CONFIG.package_directory, REAL_CONFIG.package_manifest
        )
        self.assertNotEqual(self.record["release"]["version"], version)
        self.assertEqual(self.record["release"]["version"], "2.0.6")
        self.assertFalse((PACKAGE_ROOT / "PROVENANCE.json").is_file())

    def test_the_recorded_unit_fingerprints_stay_well_formed_history(self) -> None:
        for unit, recorded in self.record["release"]["units"].items():
            with self.subTest(unit=unit):
                self.assertRegex(recorded["tree_sha256"], r"^[0-9a-f]{64}$")
                self.assertIsInstance(recorded["file_count"], int)
                self.assertGreater(recorded["file_count"], 0)

    def test_the_recorded_upstream_commit_is_history_not_a_live_pin(self) -> None:
        self.assertEqual(
            self.record["release"]["upstream_commit"],
            "818fd6843e51a9126752061a834db9dead28f72b",
        )
        self.assertEqual(self.record["release"]["version"], "2.0.6")
        changelog = (PACKAGE_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("acc99fe7", changelog)

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


MISSION_CONTROL_NOTICE = EVIDENCE / "2026-09-22-mission-control-compatibility-notice.md"
MISSION_CONTROL_LIVE_DOCUMENT = (
    EVIDENCE / "2026-08-30-mission-control-compatibility-matrix.md"
)
MISSION_CONTROL_READBACK_DOCUMENT = (
    EVIDENCE / "2026-08-30-mission-control-post-activation-readback.md"
)
MISSION_CONTROL_SUPERSEDED_MATRIX = EVIDENCE / "2026-08-25-mission-control-compatibility-matrix.md"
MISSION_CONTROL_SUPERSEDED_READBACK = (
    EVIDENCE / "2026-08-25-mission-control-post-activation-readback.md"
)
MISSION_CONTROL_INTERMEDIATE_MATRIX = (
    EVIDENCE / "2026-08-30-mission-control-compatibility-matrix-pre-fingerprint-move.md"
)
MISSION_CONTROL_INTERMEDIATE_READBACK = (
    EVIDENCE / "2026-08-30-mission-control-post-activation-readback-pre-fingerprint-move.md"
)
MISSION_CONTROL_BEADS_MATRIX = (
    EVIDENCE / "2026-08-30-mission-control-compatibility-matrix-pre-beads-config-ladder.md"
)
MISSION_CONTROL_BEADS_READBACK = (
    EVIDENCE / "2026-08-30-mission-control-post-activation-readback-pre-beads-config-ladder.md"
)
MISSION_CONTROL_PACKAGE_ROOT = ROOT / "plugins" / "mission-control"
MISSION_CONTROL_CONFIG = port_config.load("mission-control", ROOT)
MISSION_CONTROL_SKILLS = ("board", "flow", "issues", "labels", "metrics", "milestones", "rollout")


def _results_table(text: str) -> list[dict[str, str]]:
    """Parse the markdown table under the `## Results` heading of a matrix
    document into a list of row dicts keyed by the header cells."""
    lines = text.splitlines()
    heading = next(i for i, line in enumerate(lines) if line.strip() == "## Results")
    header_index = next(
        i for i in range(heading + 1, len(lines)) if lines[i].startswith("|")
    )
    header = [cell.strip() for cell in lines[header_index].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(dict(zip(header, cells)))
    return rows


class MissionControlMatrixBindingTest(unittest.TestCase):
    """The resynchronized matrix identifies the shipped package, live.

    The pre-resync matrix drifted in silence for exactly the reason these
    assertions exist: a well-formed record whose fingerprint names a tree that
    was replaced. Every case recomputes from disk rather than trusting the
    recorded number.
    """

    def setUp(self) -> None:
        self.text = MISSION_CONTROL_LIVE_DOCUMENT.read_text(encoding="utf-8")
        self.record = ccm.extract_record(self.text)

    def test_the_document_exists_and_validates(self) -> None:
        self.assertTrue(MISSION_CONTROL_LIVE_DOCUMENT.is_file())
        self.assertEqual(ccm.check_matrix(MISSION_CONTROL_LIVE_DOCUMENT), [])

    def test_the_headline_fingerprint_appears_in_the_prose(self) -> None:
        """F91: the document's prose headline must carry the record's own
        file_count and full tree_sha256, so a hand-edited headline cannot
        diverge from the machine-readable record."""
        self.assertIn(str(self.record["package"]["file_count"]), self.text)
        self.assertIn(self.record["package"]["tree_sha256"], self.text)

    def test_it_declares_itself_current(self) -> None:
        directives = ccm.read_directives(self.text)
        self.assertEqual(directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED)
        self.assertEqual(
            directives.get(ccm.SUPERSEDED_BY_DIRECTIVE),
            MISSION_CONTROL_NOTICE.name,
        )

    def test_the_recorded_fingerprint_identifies_the_shipped_package(self) -> None:
        """The 2026-08-30 record stays bound to derived 2.15.2. It is not the 2.21.1 tree."""
        self.assertEqual(self.record["package"]["version"], "2.15.2")
        _name, version = ccm.package_identity(
            MISSION_CONTROL_PACKAGE_ROOT, "plugin.json"
        )
        self.assertNotEqual(self.record["package"]["version"], version)

    def test_it_covers_exactly_the_ten_canonical_clients(self) -> None:
        names = {client["name"] for client in self.record["clients"]}
        self.assertEqual(names, set(ccm.CANONICAL_CLIENTS))

    def test_it_records_forty_stage_results_and_ten_statuses(self) -> None:
        results = [
            stage["result"]
            for client in self.record["clients"]
            for stage in client["stages"].values()
        ]
        self.assertEqual(len(results), 40)
        self.assertTrue(set(results) <= set(ccm.STAGE_RESULTS))
        statuses = [client["status"] for client in self.record["clients"]]
        self.assertEqual(len(statuses), 10)
        self.assertTrue(set(statuses) <= set(ccm.STATUSES))

    def test_every_client_carries_a_reason_for_its_status(self) -> None:
        for client in self.record["clients"]:
            with self.subTest(client=client["name"]):
                self.assertTrue(client["reason"].strip())
                self.assertTrue(client["version"].strip())

    def test_no_client_with_a_blocked_stage_claims_to_work_directly(self) -> None:
        """A status contradicting its own stage results is the exact
        mis-transcription the binding exists to catch: a client with any
        blocked stage cannot be recorded works-directly. (The converse is not
        asserted — a client can execute every stage and still fail overall.)"""
        for client in self.record["clients"]:
            with self.subTest(client=client["name"]):
                if any(
                    stage["result"] == "blocked" for stage in client["stages"].values()
                ):
                    self.assertNotEqual(
                        client["status"],
                        "works-directly",
                        "the client's status contradicts its blocked stages",
                    )

    def test_the_results_table_matches_the_record(self) -> None:
        """F56: the rendered Results table and the one-sentence summary are
        parsed and held to the machine-readable record, so hand-edited prose
        cannot diverge from the JSON without failing."""
        rows = _results_table(self.text)
        self.assertEqual(len(rows), 10, "the Results table does not carry ten rows")
        clients = {client["name"]: client for client in self.record["clients"]}
        for row in rows:
            with self.subTest(client=row["Client"]):
                client = clients[row["Client"]]
                self.assertEqual(row["Version"], client["version"])
                self.assertEqual(row["Status"], client["status"])
                for stage in ("Placement", "Discovery", "Load", "Invocation"):
                    self.assertEqual(
                        row[stage],
                        client["stages"][stage.lower()]["result"],
                        f"{row['Client']} {stage} cell contradicts the record",
                    )
        statuses = Counter(client["status"] for client in self.record["clients"])
        summary = (
            f"{statuses['works-directly']} clients work directly, "
            f"{statuses['works-through-an-adapter']} work through an adapter, "
            f"{statuses['failed']} failed, and {statuses['unsupported']} are unsupported."
        )
        self.assertIn(summary, self.text, "the one-sentence summary contradicts the record")

    def test_the_record_violates_no_safety_or_public_evidence_rule(self) -> None:
        self.assertEqual(ccm.check_safety_rules(self.record, MISSION_CONTROL_CONFIG), [])
        self.assertEqual(ccm.check_public_evidence_rules(self.record), [])


class MissionControlReadbackBindingTest(unittest.TestCase):
    """The resynchronized readback, bound the way the matrix is.

    Mission Control's readback is not discovered by the checker at all — its
    record uses `release` and `readbacks` keys rather than `package` and
    `clients` — so this class is the only thing that keeps it from drifting in
    silence. It asserts the release block, the seven per-skill-unit
    fingerprints, the provenance pin, and every readback entry, and it omits
    the profile-state assertions that are a UniFi concept.
    """

    def setUp(self) -> None:
        self.text = MISSION_CONTROL_READBACK_DOCUMENT.read_text(encoding="utf-8")
        self.record = ccm.extract_record(self.text)

    def test_the_document_exists(self) -> None:
        self.assertTrue(MISSION_CONTROL_READBACK_DOCUMENT.is_file())

    def test_the_release_fingerprint_identifies_the_shipped_package(self) -> None:
        directives = ccm.read_directives(self.text)
        self.assertEqual(directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED)
        self.assertEqual(self.record["release"]["version"], "2.15.2")

    def test_the_recorded_upstream_commit_matches_the_synchronization_pin(self) -> None:
        self.assertEqual(
            self.record["release"]["upstream_commit"],
            "3b2b7083fdda8e39e213b5f4acf9f8301d60dd52",
        )
        self.assertEqual(self.record["release"]["version"], "2.15.2")

    def test_all_seven_skill_unit_fingerprints_are_recorded_and_match(self) -> None:
        units = self.record["release"]["units"]
        self.assertEqual(set(units), set(MISSION_CONTROL_SKILLS))
        for unit in MISSION_CONTROL_SKILLS:
            with self.subTest(unit=unit):
                self.assertIsInstance(units[unit]["file_count"], int)
                self.assertRegex(units[unit]["tree_sha256"], r"^[0-9a-f]{64}$")

    def test_every_readback_reports_bytes_equal_to_the_release(self) -> None:
        """Every readback entry is asserted, branching on the install unit so
        the skill-directory client's seven per-skill digests are held to the
        release's unit fingerprints rather than skipped on a null tree digest."""
        readbacks = self.record["readbacks"]
        self.assertEqual(
            len(readbacks),
            3,
            "the readback records a different client count than the one it was captured with",
        )
        units = self.record["release"]["units"]
        for readback in readbacks:
            with self.subTest(client=readback["client"]):
                self.assertTrue(readback["matches_release"])
                self.assertTrue(
                    readback["entrypoints_exit_zero"],
                    "the readback records a failed or missing entrypoint verification",
                )
                if readback["install_unit"] == "package-root":
                    self.assertEqual(
                        readback["recomputed_tree_sha256"],
                        self.record["release"]["tree_sha256"],
                    )
                    self.assertEqual(
                        readback["recomputed_file_count"], self.record["release"]["file_count"]
                    )
                else:
                    self.assertIsNone(
                        readback["recomputed_tree_sha256"],
                        "a skill-directory install has no single recomputed tree",
                    )
                    reported = readback["reported_digest"]
                    for unit in MISSION_CONTROL_SKILLS:
                        with self.subTest(unit=unit):
                            self.assertEqual(
                                reported[unit],
                                units[unit]["tree_sha256"],
                                f"the reported digest for skill {unit} diverged from the release",
                            )
                    self.assertEqual(
                        readback["recomputed_file_count"],
                        sum(units[unit]["file_count"] for unit in MISSION_CONTROL_SKILLS),
                        "the skill-directory file count diverged from the summed units",
                    )

    def test_the_cycle_16_verification_block_is_present_and_positive(self) -> None:
        block = self.record["cycle_16_verification"]
        self.assertEqual(block["disposition"], "verified_by_digest_recheck")
        self.assertTrue(block["all_digests_match_cycle_16_footer"])
        self.assertTrue(block["mutation_proof_binding_test_passed"])
        self.assertEqual(
            block["frozen_candidate_commit"], "143a71b8aec09c7605f57b860bcfa9179ca103e8"
        )

    def test_the_readback_leaks_nothing(self) -> None:
        self.assertEqual(ccm.check_public_evidence_rules(self.record), [])


class MissionControlSupersededDocumentTest(unittest.TestCase):
    """The retired pair, kept as history rather than deleted or renumbered."""

    def test_the_old_matrix_validates_as_superseded(self) -> None:
        self.assertEqual(ccm.check_matrix(MISSION_CONTROL_SUPERSEDED_MATRIX), [])

    def test_the_old_matrix_declares_supersession_and_names_the_current_successor(self) -> None:
        directives = ccm.read_directives(
            MISSION_CONTROL_SUPERSEDED_MATRIX.read_text(encoding="utf-8")
        )
        self.assertEqual(directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED)
        successor = directives.get(ccm.SUPERSEDED_BY_DIRECTIVE)
        self.assertEqual(successor, MISSION_CONTROL_NOTICE.name)
        assert successor is not None
        self.assertTrue(directives.get(ccm.SUPERSEDED_REASON_DIRECTIVE, "").strip())
        self.assertTrue((EVIDENCE / successor).is_file())

    def test_the_old_readback_declares_supersession_and_names_the_current_successor(self) -> None:
        directives = ccm.read_directives(
            MISSION_CONTROL_SUPERSEDED_READBACK.read_text(encoding="utf-8")
        )
        self.assertEqual(directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED)
        successor = directives.get(ccm.SUPERSEDED_BY_DIRECTIVE)
        self.assertEqual(successor, MISSION_CONTROL_NOTICE.name)
        assert successor is not None
        self.assertTrue(directives.get(ccm.SUPERSEDED_REASON_DIRECTIVE, "").strip())
        self.assertTrue((EVIDENCE / successor).is_file())

    def test_each_successor_is_itself_current(self) -> None:
        for document in (MISSION_CONTROL_LIVE_DOCUMENT, MISSION_CONTROL_READBACK_DOCUMENT):
            with self.subTest(document=document.name):
                directives = ccm.read_directives(document.read_text(encoding="utf-8"))
                self.assertEqual(
                    directives.get(ccm.STATUS_DIRECTIVE),
                    ccm.STATUS_SUPERSEDED,
                )
        # The successor both chains name is a notice, not an invented matrix:
        # no ten-client run has been made against mission-control 2.21.1. A
        # notice is a valid supersession target -- see the 2026-09-22 "explicit
        # notice state for compatibility evidence" decision.
        notice = ccm.read_directives(MISSION_CONTROL_NOTICE.read_text(encoding="utf-8"))
        self.assertEqual(notice.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_NOTICE)
        self.assertFalse(
            ccm.is_matrix_document(MISSION_CONTROL_NOTICE.read_text(encoding="utf-8"))
        )

    def test_the_old_records_preserve_the_fingerprints_they_were_published_with(self) -> None:
        record = ccm.extract_record(
            MISSION_CONTROL_SUPERSEDED_MATRIX.read_text(encoding="utf-8")
        )
        self.assertEqual(record["package"]["file_count"], 64)
        self.assertEqual(
            record["package"]["tree_sha256"],
            "651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682",
        )
        readback = ccm.extract_record(
            MISSION_CONTROL_SUPERSEDED_READBACK.read_text(encoding="utf-8")
        )
        self.assertEqual(readback["release"]["file_count"], 64)
        self.assertEqual(
            readback["release"]["tree_sha256"],
            "651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682",
        )

    def test_the_intermediate_pair_validates_as_superseded(self) -> None:
        self.assertEqual(ccm.check_matrix(MISSION_CONTROL_INTERMEDIATE_MATRIX), [])

    def test_the_intermediate_pair_names_the_final_current_successors(self) -> None:
        for document, successor_document in (
            (MISSION_CONTROL_INTERMEDIATE_MATRIX, MISSION_CONTROL_LIVE_DOCUMENT),
            (MISSION_CONTROL_INTERMEDIATE_READBACK, MISSION_CONTROL_READBACK_DOCUMENT),
        ):
            with self.subTest(document=document.name):
                directives = ccm.read_directives(document.read_text(encoding="utf-8"))
                self.assertEqual(
                    directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED
                )
                successor = directives.get(ccm.SUPERSEDED_BY_DIRECTIVE)
                self.assertEqual(successor, MISSION_CONTROL_NOTICE.name)
                assert successor is not None
                self.assertTrue(
                    directives.get(ccm.SUPERSEDED_REASON_DIRECTIVE, "").strip()
                )
                self.assertTrue((EVIDENCE / successor).is_file())

    def test_the_beads_pair_names_the_final_current_successors(self) -> None:
        for document, successor_document in (
            (MISSION_CONTROL_BEADS_MATRIX, MISSION_CONTROL_LIVE_DOCUMENT),
            (MISSION_CONTROL_BEADS_READBACK, MISSION_CONTROL_READBACK_DOCUMENT),
        ):
            with self.subTest(document=document.name):
                directives = ccm.read_directives(document.read_text(encoding="utf-8"))
                self.assertEqual(
                    directives.get(ccm.STATUS_DIRECTIVE), ccm.STATUS_SUPERSEDED
                )
                successor = directives.get(ccm.SUPERSEDED_BY_DIRECTIVE)
                self.assertEqual(successor, MISSION_CONTROL_NOTICE.name)
                assert successor is not None
                self.assertTrue(
                    directives.get(ccm.SUPERSEDED_REASON_DIRECTIVE, "").strip()
                )
                self.assertTrue((EVIDENCE / successor).is_file())

    def test_the_beads_records_preserve_the_659f91f6_fingerprint(self) -> None:
        record = ccm.extract_record(
            MISSION_CONTROL_BEADS_MATRIX.read_text(encoding="utf-8")
        )
        self.assertEqual(record["package"]["file_count"], 71)
        self.assertEqual(
            record["package"]["tree_sha256"],
            "659f91f6eae524612ad8daf3046d083281e0e76a950de3600b4b2948c68a18bd",
        )
        readback = ccm.extract_record(
            MISSION_CONTROL_BEADS_READBACK.read_text(encoding="utf-8")
        )
        self.assertEqual(
            readback["release"]["tree_sha256"],
            "659f91f6eae524612ad8daf3046d083281e0e76a950de3600b4b2948c68a18bd",
        )

    def test_the_intermediate_records_preserve_the_old_fingerprint(self) -> None:
        record = ccm.extract_record(
            MISSION_CONTROL_INTERMEDIATE_MATRIX.read_text(encoding="utf-8")
        )
        self.assertEqual(record["package"]["file_count"], 71)
        self.assertEqual(
            record["package"]["tree_sha256"],
            "1f49322e8412ac6b2ae0b1fbebf4a022ac2e53489be71aae674506a7613531f9",
        )
        readback = ccm.extract_record(
            MISSION_CONTROL_INTERMEDIATE_READBACK.read_text(encoding="utf-8")
        )
        self.assertEqual(
            readback["release"]["tree_sha256"],
            "1f49322e8412ac6b2ae0b1fbebf4a022ac2e53489be71aae674506a7613531f9",
        )


class EvidenceDiscoveryTest(unittest.TestCase):
    """The discovery-based gates the hand-registered classes rely on: the
    checker's own matrix discovery validates every matrix document, current
    readbacks bind their release to the live package, and no prose outside the
    evidence directory links a superseded document as if it were live."""

    @staticmethod
    def _is_readback(text: str) -> bool:
        try:
            record = ccm.extract_record(text)
        except ccm.MatrixError:
            return False
        return isinstance(record, dict) and "release" in record and "readbacks" in record

    @staticmethod
    def _superseded_names() -> set[str]:
        return {
            path.name
            for path in EVIDENCE.glob("*.md")
            if ccm.read_directives(path.read_text(encoding="utf-8")).get(
                ccm.STATUS_DIRECTIVE
            )
            == ccm.STATUS_SUPERSEDED
        }

    def test_every_discovered_matrix_document_validates(self) -> None:
        discovered = ccm.matrix_documents()
        self.assertTrue(discovered, "matrix discovery found no documents")
        for path in discovered:
            with self.subTest(document=path.name):
                self.assertEqual(ccm.check_matrix(path), [], path.name)

    def test_every_discovered_current_readback_binds_its_release(self) -> None:
        bound = 0
        for path in sorted(EVIDENCE.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            if not self._is_readback(text):
                continue
            directives = ccm.read_directives(text)
            if directives.get(ccm.STATUS_DIRECTIVE) == ccm.STATUS_SUPERSEDED:
                continue
            record = ccm.extract_record(text)
            release = record["release"]
            config = port_config.load(release["name"], ROOT)
            with self.subTest(document=path.name):
                assert_version_binds_and_a_moved_tree_is_only_reported(self, release, config)
            bound += 1
        if bound == 0:
            # Every readback is superseded while the authored versions await
            # their fresh ten-client run (2026-09-22 decision: evidence binds to
            # a released version; a package with no live record is allowed).
            self.skipTest("no current readback documents exist; the authored versions await assessment")

    def test_no_prose_outside_evidence_links_a_superseded_document(self) -> None:
        """A superseded document may only be cited with its retirement stated:
        the link's own anchor text must mark the citation as historical, and a
        superseded document's own banner may name its successor. A bare
        present-tense link to retired evidence is the index defect. The walk
        enumerates tracked markdown from `git ls-files`, so gitignored
        directories can never contribute a false positive."""
        superseded = self._superseded_names()
        self.assertTrue(superseded, "expected at least one superseded document to guard")
        link = re.compile(r"\[([^\]]*)\]\(([^)#]+)(?:#[^)]*)?\)")
        tracked = subprocess.run(
            ["git", "ls-files", "--", "*.md"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout.splitlines()
        for relative in tracked:
            path = ROOT / relative
            if not path.exists():
                # F92: a tracked file deleted in the working tree must be
                # skipped, not read into a FileNotFoundError.
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if EVIDENCE in path.parents:
                directives = ccm.read_directives(text)
                if directives.get(ccm.STATUS_DIRECTIVE) == ccm.STATUS_SUPERSEDED:
                    # A retired document is historical context by definition;
                    # its chain lists cite other retired documents as history.
                    continue
                own_successor = directives.get(ccm.SUPERSEDED_BY_DIRECTIVE)
            else:
                own_successor = None
            for anchor, target in link.findall(text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                name = target.split("/")[-1]
                if name == own_successor:
                    continue
                if name in superseded and not re.search(
                    r"supersed|historical|retired", anchor, re.I
                ):
                    self.fail(
                        f"{relative} links the superseded evidence document {name} "
                        "without marking the citation as historical; repoint the link "
                        "at the successor or state the retirement in the anchor text"
                    )


if __name__ == "__main__":
    unittest.main()
