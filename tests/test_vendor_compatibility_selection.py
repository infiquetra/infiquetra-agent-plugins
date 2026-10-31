"""Dependency-free phase-one selector/admission controls; no vendor execution."""

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci/select_vendor_compatibility.py"
SPEC = importlib.util.spec_from_file_location("vendor_selection_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)
BASE, HEAD, CANDIDATE = "a" * 40, "b" * 40, "c" * 40


def evidence(data=b"M\0docs/example.md\0"):
    return SELECTOR.classify(data, BASE, HEAD, CANDIDATE)


def successful_needs():
    return {name: {"result": "success"} for name in SELECTOR.CHILDREN}


class VendorSelectionTests(unittest.TestCase):
    def test_each_path_class_remains_full_without_an_exemption_proof(self):
        paths = [
            "docs/public-safe-summary.md", "README.md", "AGENTS.md",
            "plugins/saga/skills/work/SKILL.md", "plugins/saga/scripts/run_record.py",
            "plugins/orchestrate/com.infiquetra.claude/mods/plan.tsx",
            "plugins/saga/plugin.json", "schemas/compatibility-matrix.schema.json",
            "requirements-plugin-tests.txt", "constraints-plugin-tests.txt",
            ".github/workflows/ci.yml", "scripts/check_repo.py", "tests/data.json",
            "new/unknown.md", "plugins/fleet-core/scripts/admission.py",
        ]
        self.assertEqual(SELECTOR.SAFE_PORTABLE_DOCUMENTS, frozenset())
        for path in paths:
            with self.subTest(path=path):
                result = evidence(b"M\0" + path.encode() + b"\0")
                self.assertEqual(result["recommendation"], "FULL")
                self.assertTrue(result["complete"])
        self.assertEqual(evidence(b"")["recommendation"], "FULL")

    def test_rename_both_sides_and_deleted_added_paths_are_bound(self):
        raw = b"R050\0docs/old.md\0plugins/saga/SKILL.md\0D\0old.md\0A\0new.md\0"
        result = evidence(raw)
        self.assertEqual(result["changes"][0]["paths"],
                         ["docs/old.md", "plugins/saga/SKILL.md"])
        self.assertEqual(result["diff_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual([x["status"] for x in result["changes"]], ["R050", "D", "A"])
        self.assertEqual(result["recommendation"], "FULL")

    def test_malformed_incomplete_unusual_and_oversized_diff_fallback(self):
        bad = [b"M\0a", b"R100\0old\0", b"R101\0old\0new\0", b"M\0../x\0",
               b"M\0/a\0", b"M\0a//b\0", b"M\0a\nb\0", b"M\0\xff\0",
               b"M\0a\\b\0", b"X\0a\0", b"\0", b"x" * 32769,
               b"M\0a\0" * 129]
        for raw in bad:
            with self.subTest(raw=raw[:30]):
                result = evidence(raw)
                self.assertEqual(result["recommendation"], "FULL")
                self.assertFalse(result["complete"])
                self.assertEqual(result["changes"], [])

    def test_binding_and_history_failures_do_not_recommend_skip(self):
        for base in ["", "a" * 39, "A" * 40, "a;echo nope"]:
            self.assertFalse(SELECTOR.classify(b"", base, HEAD, CANDIDATE)["complete"])
        with mock.patch.object(SELECTOR, "git", side_effect=FileNotFoundError):
            result = SELECTOR.collect(BASE, HEAD, CANDIDATE, "pull_request")
        self.assertFalse(result["candidate_checked"])
        self.assertEqual(result["recommendation"], "FULL")
        with mock.patch.object(SELECTOR, "git", return_value=(HEAD + "\n").encode()):
            self.assertEqual(SELECTOR.collect(BASE, HEAD, CANDIDATE, "pull_request")["reason"],
                             "candidate-mismatch")
        with mock.patch.object(SELECTOR, "git", side_effect=[
            (CANDIDATE + "\n").encode(), b"missing-parent\n",
        ]):
            result = SELECTOR.collect(BASE, HEAD, CANDIDATE, "pull_request")
        self.assertEqual(result["reason"], "missing-history")
        self.assertTrue(result["candidate_checked"])

    def test_complete_candidate_graph_and_diff_transport(self):
        parents = f"{CANDIDATE} {BASE} {HEAD}\n".encode()
        with mock.patch.object(SELECTOR, "git", side_effect=[
            (CANDIDATE + "\n").encode(), parents, b"M\0a.md\0",
        ]) as git:
            result = SELECTOR.collect(BASE, HEAD, CANDIDATE, "pull_request")
        self.assertTrue(result["complete"])
        self.assertEqual(git.call_args.args,
                         ("diff", "--name-status", "-z", "--find-renames", BASE, HEAD, "--"))
        with mock.patch.object(SELECTOR, "git", side_effect=[HEAD.encode(), b"M\0a.md\0"]):
            self.assertEqual(SELECTOR.collect(BASE, HEAD, HEAD, "push")["recommendation"], "FULL")


class VendorAggregateTests(unittest.TestCase):
    def test_phase_one_truth_table_requires_every_child(self):
        self.assertTrue(SELECTOR.admit(evidence(), successful_needs(), BASE, HEAD, CANDIDATE))
        for child in SELECTOR.CHILDREN:
            for outcome in ["failure", "cancelled", "skipped", "", None, True]:
                with self.subTest(child=child, outcome=outcome):
                    needs = successful_needs()
                    needs[child]["result"] = outcome
                    self.assertFalse(SELECTOR.admit(evidence(), needs, BASE, HEAD, CANDIDATE))
            needs = successful_needs()
            del needs[child]
            self.assertFalse(SELECTOR.admit(evidence(), needs, BASE, HEAD, CANDIDATE))

    def test_missing_malformed_forged_and_wrong_candidate_evidence_refuse(self):
        mutations = [
            ("schema", True), ("phase", "reduced"), ("head", "d" * 40),
            ("candidate", "d" * 40), ("candidate_checked", False),
            ("recommendation", "SKIP"), ("complete", "true"),
            ("diff_sha256", "0" * 64), ("changes", []),
            ("reason", "safe-markdown"),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                result = copy.deepcopy(evidence())
                result[key] = value
                self.assertFalse(SELECTOR.admit(result, successful_needs(), BASE, HEAD, CANDIDATE))
        for value in [None, [], {}, "FULL"]:
            self.assertFalse(SELECTOR.admit(value, successful_needs(), BASE, HEAD, CANDIDATE))
        result = evidence()
        result["extra"] = "unrecognized"
        self.assertFalse(SELECTOR.admit(result, successful_needs(), BASE, HEAD, CANDIDATE))

    def test_known_full_fallback_is_admitted_only_after_all_children(self):
        result = SELECTOR.fallback(BASE, HEAD, CANDIDATE, "missing-history", True)
        self.assertTrue(SELECTOR.admit(result, successful_needs(), BASE, HEAD, CANDIDATE))
        needs = successful_needs()
        needs["claude-mods"]["result"] = "skipped"
        self.assertFalse(SELECTOR.admit(result, needs, BASE, HEAD, CANDIDATE))

    def test_real_stdlib_cli_select_and_aggregate_entrypoints(self):
        env = {"PATH": "", "SELECT_BASE": BASE, "SELECT_HEAD": HEAD,
               "SELECT_CANDIDATE": CANDIDATE, "SELECT_EVENT": "pull_request"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "select"],
                                    env={**env, "GITHUB_OUTPUT": str(output)},
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text().split("=", 1)[1])["recommendation"],
                             "FULL")
        needs = successful_needs()
        needs["vendor-selection"]["outputs"] = {"evidence": json.dumps(evidence())}
        for payload, expected in [(json.dumps(needs), 0), ("malformed", 1)]:
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "aggregate"],
                                    env={**env, "NEEDS_JSON": payload},
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
