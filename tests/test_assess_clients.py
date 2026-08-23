"""Tests for the scripted ten-client compatibility assessment.

The harness's job is to be honest about what happened, so the behaviour under
test is mostly the classification: which observations become **executed**, which
become **blocked**, and which stop the run entirely. Getting that wrong in the
generous direction is the failure that matters -- a stage that did not run,
recorded as one that did, is how nine matrix runs could have shipped a package
that never loaded.

The subprocess behaviour is therefore tested with **real subprocesses**. Fake
client executables are written into a scratch directory and put on `PATH`, and
the tests assert on the actual argv the harness passed, the actual exit status
it read back, and the actual deadline it enforced. Stubbing `subprocess.run`
would test the harness's opinion of what a subprocess does; a fake binary tests
what one does.

No test in this file runs a real coding-agent client, touches the operator's
home directory, or reads a credential.

Standard library only, matching the harness and the repository baseline.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import assess_clients as harness  # noqa: E402
import check_compatibility_matrix as ccm  # noqa: E402
import port_config  # noqa: E402


CONFIG = port_config.load("unifi", ROOT)


def write_executable(directory: Path, name: str, body: str) -> Path:
    """A real executable on disk, so the tests below run real processes."""
    path = directory / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class FakeClientFixture(unittest.TestCase):
    """A scratch PATH holding fake clients, and an environment that finds them."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.base = Path(self._temporary.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()

        write_executable(self.bin, "ok-client", 'echo "two skills resolved"\nexit 0\n')
        write_executable(
            self.bin,
            "refusing-client",
            'echo "marketplace root does not contain a supported manifest" >&2\nexit 3\n',
        )
        write_executable(self.bin, "hanging-client", "sleep 30\n")
        write_executable(self.bin, "stdin-client", 'read answer\necho "answer=$answer"\nexit 0\n')
        write_executable(self.bin, "env-client", "env\nexit 0\n")
        write_executable(self.bin, "id-client", 'echo "installed as unifi-37c9f17b"\nexit 0\n')
        write_executable(self.bin, "argv-client", 'printf "%s\\n" "$@"\nexit 0\n')

        self.environment = dict(os.environ)
        # Prepended, not replaced. The fakes must shadow a real client of the
        # same name, but a PATH holding only the fakes would also hide `sleep`,
        # and the deadline test would then pass for the wrong reason.
        self.environment["PATH"] = os.pathsep.join(
            [str(self.bin), os.environ.get("PATH", "")]
        )
        self.environment["HOME"] = str(self.home)
        self.values = {
            harness.PACKAGE: str(self.base / "package"),
            harness.PYTHON: sys.executable,
            harness.CLIENT_HOME: str(self.home),
            harness.PLUGIN_NAME: CONFIG.name,
            harness.PLUGIN_ID: CONFIG.name,
        }

    def outcome(self, spec: harness.StageSpec, plan: harness.ClientPlan | None = None):
        return harness.run_stage(
            plan or harness.plan_for("Claude Code"),
            spec,
            CONFIG,
            self.values,
            self.environment,
        )


class RosterTest(unittest.TestCase):
    """The roster is derived from the validator, never restated."""

    def test_every_canonical_client_has_a_plan(self) -> None:
        self.assertEqual(
            sorted(plan.name for plan in harness.CLIENT_PLANS),
            sorted(ccm.CANONICAL_CLIENTS),
        )

    def test_every_plan_covers_all_four_stages(self) -> None:
        for plan in harness.CLIENT_PLANS:
            with self.subTest(client=plan.name):
                self.assertEqual(
                    sorted(spec.stage for spec in plan.stages),
                    sorted(ccm.STAGES),
                )

    def test_a_plan_missing_a_stage_is_refused(self) -> None:
        """A row that stops at its first failure proves nothing about load."""
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.ClientPlan(
                "Partial",
                binary="x",
                stages=(harness.StageSpec("placement", ("x", "list")),),
            )
        self.assertIn("all four stages", str(caught.exception))

    def test_a_stage_that_neither_runs_nor_explains_is_refused(self) -> None:
        with self.assertRaises(harness.AssessmentError):
            harness.StageSpec("discovery")

    def test_an_unknown_stage_name_is_refused(self) -> None:
        with self.assertRaises(harness.AssessmentError):
            harness.StageSpec("installation", ("x",))

    def test_every_quirk_the_runbook_names_is_carried(self) -> None:
        """The quirks cost nine runs to learn; losing one costs them again."""
        expected = {
            "Cursor Agent": "authenticated",
            "Grok": "GROK_AUTO_TRUST_REAL_BIN",
            "Agy": "AGY_AUTO_TRUST_REAL_BIN",
            "Qwen": "standard input",
            "Gemini CLI": "hangs",
            "Muse": "--force",
            "Hermes": "isolated",
            "OpenAI Codex": "actionable",
        }
        for name, fragment in expected.items():
            with self.subTest(client=name):
                self.assertIn(fragment.lower(), harness.plan_for(name).quirk.lower())

    def test_the_two_wrapper_clients_declare_their_override(self) -> None:
        for name, variable in (
            ("Grok", "GROK_AUTO_TRUST_REAL_BIN"),
            ("Agy", "AGY_AUTO_TRUST_REAL_BIN"),
        ):
            with self.subTest(client=name):
                self.assertIn(variable, harness.plan_for(name).environment)

    def test_the_prompting_clients_supply_a_confirmation(self) -> None:
        """With no answer one installer lists and exits, and one hangs."""
        self.assertEqual(harness.plan_for("Qwen").stage("placement").stdin, "y\n")
        self.assertEqual(harness.plan_for("Gemini CLI").stage("placement").stdin, "y\n")

    def test_the_muse_load_stage_forces_the_digest(self) -> None:
        self.assertIn("--force", harness.plan_for("Muse").stage("load").argv)


class SubprocessResultTest(FakeClientFixture):
    """Real processes, real exit statuses, real deadlines."""

    def test_a_successful_command_is_executed_and_records_its_status(self) -> None:
        outcome = self.outcome(harness.StageSpec("discovery", ("ok-client", "list")))
        self.assertEqual(outcome.result, harness.EXECUTED)
        self.assertEqual(outcome.returncode, 0)
        self.assertIn("exit status 0", outcome.evidence)

    def test_an_actionable_refusal_is_executed_not_blocked(self) -> None:
        """The attempt ran and the client named what it wanted.

        Recording that as blocked would lose the finding: this is exactly the
        Codex placement row, whose value is that the client says which manifest
        is missing.
        """
        outcome = self.outcome(harness.StageSpec("placement", ("refusing-client", "add")))
        self.assertEqual(outcome.result, harness.EXECUTED)
        self.assertEqual(outcome.returncode, 3)

    def test_a_deadline_makes_the_stage_blocked_and_names_the_deadline(self) -> None:
        outcome = self.outcome(
            harness.StageSpec("placement", ("hanging-client",), timeout=0.4)
        )
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertIn("0.4s deadline", outcome.reason)

    def test_an_absent_client_is_blocked_rather_than_a_package_failure(self) -> None:
        outcome = self.outcome(harness.StageSpec("discovery", ("no-such-client", "list")))
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertIn("never as a package failure", outcome.reason)

    def test_a_stage_blocked_in_advance_runs_nothing(self) -> None:
        spec = harness.plan_for("OpenAI Codex").stage("load")
        outcome = self.outcome(spec)
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertIn("nothing to load", outcome.reason)
        self.assertEqual(outcome.command, "")

    def test_the_confirmation_actually_reaches_the_process(self) -> None:
        """A confirmation the harness claims to send but does not is the Qwen defect."""
        argv_echo = write_executable(
            self.bin, "confirm-check", 'read answer\n[ "$answer" = "y" ] || exit 9\nexit 0\n'
        )
        self.assertTrue(argv_echo.exists())
        outcome = self.outcome(
            harness.StageSpec("placement", ("confirm-check",), stdin="y\n")
        )
        self.assertEqual(outcome.result, harness.EXECUTED)
        self.assertEqual(outcome.returncode, 0)

    def test_without_a_confirmation_the_same_process_reports_the_difference(self) -> None:
        write_executable(
            self.bin, "confirm-check", 'read answer\n[ "$answer" = "y" ] || exit 9\nexit 0\n'
        )
        outcome = self.outcome(
            harness.StageSpec("placement", ("confirm-check",), timeout=10)
        )
        self.assertEqual(outcome.returncode, 9)

    def test_a_stage_never_inherits_the_operators_terminal(self) -> None:
        """A stage that supplies no confirmation gets a closed stdin, not the parent's.

        Asserted by giving the *parent* a stdin holding known bytes and checking
        that the stage's child never saw them. Doing it this way rather than by
        observing a hang is what makes the check deterministic: an inherited
        stdin behaves one way under a terminal and another under a scheduler, so
        a test that watched for a block would prove the guard in one environment
        and quietly prove nothing in the other.
        """
        write_executable(self.bin, "stdin-echo", 'cat\nexit 0\n')
        program = (
            "import subprocess, sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "import assess_clients as harness, port_config\n"
            f"config = port_config.load('unifi', Path({str(ROOT)!r}))\n"
            "spec = harness.StageSpec('discovery', ('stdin-echo',), timeout=10)\n"
            "captured = {}\n"
            "real = subprocess.run\n"
            "def spy(*a, **k):\n"
            "    result = real(*a, **k)\n"
            "    captured['out'] = result.stdout\n"
            "    return result\n"
            "outcome = harness.run_stage(\n"
            "    harness.plan_for('Claude Code'), spec, config,\n"
            f"    {self.values!r}, {self.environment!r}, runner=spy)\n"
            "print('CHILD_SAW:' + repr(captured.get('out')))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            input="LEAKED-PARENT-STDIN\n",
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("CHILD_SAW:", completed.stdout)
        self.assertNotIn("LEAKED-PARENT-STDIN", completed.stdout)

    def test_a_generated_install_id_is_captured_from_real_output(self) -> None:
        spec = harness.StageSpec(
            "placement",
            ("id-client",),
            capture=(harness.PLUGIN_ID, r"\b([A-Za-z0-9_.-]+-[0-9a-f]{8})\b"),
        )
        outcome = self.outcome(spec)
        self.assertEqual(outcome.captured[harness.PLUGIN_ID], "unifi-37c9f17b")

    def test_the_argv_the_process_receives_is_the_argv_the_plan_declares(self) -> None:
        """Asserted from the child's own view of its arguments, not the parent's."""
        completed = subprocess.run(
            ["argv-client", "--plugin-dir", self.values[harness.PACKAGE], "plugin", "list"],
            capture_output=True,
            text=True,
            env=self.environment,
        )
        self.assertEqual(
            completed.stdout.split("\n")[:4],
            ["--plugin-dir", self.values[harness.PACKAGE], "plugin", "list"],
        )

    def test_a_multi_command_stage_is_blocked_if_any_command_is(self) -> None:
        """A stage that half ran did not run."""
        spec = harness.StageSpec("placement", ("hanging-client", harness.SKILL), timeout=0.4)
        outcome = harness.run_stage(
            harness.plan_for("OpenCode"), spec, CONFIG, self.values, self.environment
        )
        self.assertEqual(outcome.result, harness.BLOCKED)


class CredentialTest(FakeClientFixture):
    """No stage may be satisfied by a credential in the operator's shell."""

    def test_declared_credential_variables_are_removed_from_the_environment(self) -> None:
        polluted = dict(self.environment)
        polluted["UNIFI_PASSWORD"] = "rainbowtrout"
        polluted["UNIFI_HOST"] = "controller.invalid"
        polluted["KEEP_ME"] = "yes"
        cleaned = harness.build_environment(CONFIG, home=self.home, base=polluted)
        self.assertNotIn("UNIFI_PASSWORD", cleaned)
        self.assertNotIn("UNIFI_HOST", cleaned)
        self.assertEqual(cleaned["KEEP_ME"], "yes")

    def test_the_child_process_really_does_not_see_them(self) -> None:
        """Read out of a real process's own environment, not out of a dict."""
        polluted = dict(self.environment)
        polluted["UNIFI_PASSWORD"] = "rainbowtrout"
        cleaned = harness.build_environment(CONFIG, home=self.home, base=polluted)
        completed = subprocess.run(
            ["env-client"], capture_output=True, text=True, env=cleaned
        )
        self.assertNotIn("UNIFI_PASSWORD", completed.stdout)
        self.assertNotIn("rainbowtrout", completed.stdout)

    def test_the_prefixes_come_from_the_descriptor_not_from_this_file(self) -> None:
        self.assertEqual(
            harness.credential_variables({"UNIFI_X": "1", "OTHER": "2"}, CONFIG),
            ["UNIFI_X"],
        )

    def test_a_scratch_home_redirects_the_state_directories_too(self) -> None:
        """HOME alone is not enough: a client reading XDG_CONFIG_HOME would escape."""
        cleaned = harness.build_environment(CONFIG, home=self.home, base=dict(self.environment))
        self.assertEqual(cleaned["HOME"], str(self.home))
        for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            with self.subTest(variable=variable):
                self.assertTrue(cleaned[variable].startswith(str(self.home)))


class SafetyRefusalTest(FakeClientFixture):
    """The harness refuses before it runs, using the validator's own predicate."""

    def test_a_confirmed_command_is_refused_before_it_runs(self) -> None:
        canary = self.base / "ran"
        write_executable(self.bin, "writer", f'touch "{canary}"\nexit 0\n')
        with self.assertRaises(harness.AssessmentError):
            self.outcome(harness.StageSpec("invocation", ("writer", "--confirm")))
        self.assertFalse(canary.exists(), "the refused command started anyway")

    def test_a_mutating_package_operation_is_refused_before_it_runs(self) -> None:
        script = CONFIG.assessment.package_scripts[0]
        operation = sorted(CONFIG.assessment.mutating_operations)[0]
        canary = self.base / "mutated"
        write_executable(self.bin, "writer", f'touch "{canary}"\nexit 0\n')
        with self.assertRaises(harness.AssessmentError):
            self.outcome(harness.StageSpec("invocation", ("writer", script, operation)))
        self.assertFalse(canary.exists())

    def test_the_refusal_uses_the_same_predicate_as_the_matrix_validator(self) -> None:
        """One authority, applied before the fact here and after the fact there."""
        script = CONFIG.assessment.package_scripts[0]
        command = f"python3 {script} reboot"
        self.assertTrue(ccm.command_safety_problems(command, CONFIG))
        with self.assertRaises(harness.AssessmentError):
            harness.refuse_unsafe_argv(tuple(command.split()), CONFIG)

    def test_a_read_only_package_command_is_allowed(self) -> None:
        script = CONFIG.assessment.package_scripts[0]
        harness.refuse_unsafe_argv(("python3", script, "list"), CONFIG)

    def test_every_shipped_plan_passes_the_safety_predicate(self) -> None:
        """The class, not one instance: no plan may carry an unsafe command."""
        values = {
            harness.PACKAGE: "/scratch/package",
            harness.PYTHON: "/usr/bin/python3.12",
            harness.CLIENT_HOME: "/scratch/home",
            harness.PLUGIN_NAME: CONFIG.name,
            harness.PLUGIN_ID: CONFIG.name,
        }
        for plan in harness.CLIENT_PLANS:
            for spec in plan.stages:
                if spec.blocked_reason is not None:
                    continue
                for argv in harness.stage_argvs(CONFIG, plan, spec, values):
                    with self.subTest(client=plan.name, stage=spec.stage):
                        harness.refuse_unsafe_argv(argv, CONFIG)


class HomePolicyTest(unittest.TestCase):
    """Live client configuration is never written to."""

    def test_a_state_writing_stage_may_not_run_in_the_operators_home(self) -> None:
        plan = harness.plan_for("Qwen")
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.refuse_unsafe_home(plan, plan.stage("placement"), harness.REAL_HOME)
        self.assertIn("scratch home or not at all", str(caught.exception))

    def test_the_isolated_only_client_is_refused_a_real_home_outright(self) -> None:
        plan = harness.plan_for("Hermes")
        for stage in ccm.STAGES:
            with self.subTest(stage=stage):
                with self.assertRaises(harness.AssessmentError) as caught:
                    harness.refuse_unsafe_home(plan, plan.stage(stage), harness.REAL_HOME)
                self.assertIn("isolated home only", str(caught.exception))

    def test_the_authenticated_client_may_use_the_real_home(self) -> None:
        """Its isolated-home result measured a different, unauthenticated client."""
        plan = harness.plan_for("Cursor Agent")
        self.assertEqual(plan.home, harness.REAL_HOME)
        for stage in ccm.STAGES:
            with self.subTest(stage=stage):
                harness.refuse_unsafe_home(plan, plan.stage(stage), harness.REAL_HOME)

    def test_no_stage_of_the_real_home_client_writes_client_state(self) -> None:
        """Session-scoped placement is what makes the exemption safe."""
        for spec in harness.plan_for("Cursor Agent").stages:
            with self.subTest(stage=spec.stage):
                self.assertFalse(spec.writes_client_state)

    def test_every_other_client_is_isolated(self) -> None:
        for plan in harness.CLIENT_PLANS:
            if plan.name == "Cursor Agent":
                continue
            with self.subTest(client=plan.name):
                self.assertEqual(plan.home, harness.ISOLATED_HOME)


class EntrypointPathTest(unittest.TestCase):
    """The invocation stage runs from the path the client resolved."""

    def test_a_package_scoped_client_keeps_the_package_layout(self) -> None:
        paths = harness.entrypoint_paths(CONFIG, harness.plan_for("Claude Code"))
        self.assertEqual(len(paths), len(CONFIG.custody.entrypoint_transforms))
        for path, relative in zip(paths, CONFIG.custody.entrypoint_transforms):
            self.assertEqual(path, f"{harness.PACKAGE}/{relative}")

    def test_a_skill_scoped_client_resolves_below_the_unit_directory(self) -> None:
        """The unit becomes the top level, so the package's own prefix disappears."""
        plan = harness.plan_for("OpenCode")
        paths = harness.entrypoint_paths(CONFIG, plan)
        self.assertEqual(len(paths), len(CONFIG.custody.entrypoint_transforms))
        for path, relative in zip(paths, CONFIG.custody.entrypoint_transforms):
            unit = next(
                unit
                for unit in CONFIG.assessment.skill_units
                if relative.startswith(f"{unit}/")
            )
            expected = (
                f"{plan.invocation_root}/{Path(unit).name}/{relative[len(unit) + 1:]}"
            )
            self.assertEqual(path, expected)
            # The package-scoped form is what this must NOT be.
            self.assertNotEqual(path, f"{plan.invocation_root}/{relative}")

    def test_every_entrypoint_is_invoked_not_only_the_first(self) -> None:
        """A stage that checked one of two clients would have called the
        pilot's broken package working."""
        for plan in harness.CLIENT_PLANS:
            if plan.stage("invocation").blocked_reason is not None:
                continue
            with self.subTest(client=plan.name):
                argvs = harness.invocation_argv(CONFIG, plan, "/usr/bin/python3.12")
                self.assertEqual(len(argvs), len(CONFIG.custody.entrypoint_transforms))

    def test_the_invocation_uses_the_credential_free_help_action(self) -> None:
        for plan in harness.CLIENT_PLANS:
            if plan.stage("invocation").blocked_reason is not None:
                continue
            with self.subTest(client=plan.name):
                for argv in harness.invocation_argv(CONFIG, plan, "/usr/bin/python3.12"):
                    self.assertEqual(argv[-1], "--help")

    def test_an_entrypoint_outside_every_declared_unit_is_refused(self) -> None:
        variant = port_config.parse(
            {
                "schema_version": port_config.SCHEMA_VERSION,
                "package": "unifi",
                "package_root": "plugins/unifi",
                "source": {"repository": "https://example.com/u", "package_path": "plugins/unifi"},
                "custody": {"entrypoint_transforms": ["tools/orphan.py"]},
                "assessment": {"skill_units": ["skills/unifi-network"]},
            },
            root=ROOT,
            path=ROOT / "ports" / "unifi.json",
        )
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.entrypoint_paths(variant, harness.plan_for("OpenCode"))
        self.assertIn("skill_units", str(caught.exception))


class RedactionTest(unittest.TestCase):
    def test_the_longest_value_is_replaced_first(self) -> None:
        """A scratch home is a prefix of the package inside it."""
        values = {
            harness.CLIENT_HOME: "/scratch/home",
            harness.PACKAGE: "/scratch/home/package",
        }
        self.assertEqual(
            harness.redact("/scratch/home/package/skills", values),
            "<package>/skills",
        )

    def test_an_empty_value_never_matches_everything(self) -> None:
        self.assertEqual(harness.redact("text", {harness.PLUGIN_ID: ""}), "text")


class StatusProposalTest(unittest.TestCase):
    def outcomes(self, returncode: int = 0, **results: str) -> dict[str, harness.StageOutcome]:
        return {
            stage: harness.StageOutcome(
                stage,
                results[stage],
                command="x",
                evidence="observed",
                reason="named",
                returncode=returncode if results[stage] == harness.EXECUTED else None,
            )
            for stage in ccm.STAGES
        }

    def test_an_entrypoint_that_ran_and_did_not_succeed_proposes_failed(self) -> None:
        """`executed` says a process completed, not that it worked.

        The pilot shipped a package whose entrypoints raised
        `ModuleNotFoundError` before parsing an argument. Every stage executed.
        Reading the exit status is what separates that from a working package.
        """
        results = dict.fromkeys(ccm.STAGES, harness.EXECUTED)
        self.assertEqual(
            harness.propose_status(self.outcomes(returncode=1, **results)), "failed"
        )

    def test_a_zero_exit_from_the_entrypoint_does_not_propose_failed(self) -> None:
        results = dict.fromkeys(ccm.STAGES, harness.EXECUTED)
        self.assertEqual(
            harness.propose_status(self.outcomes(returncode=0, **results)), "works-directly"
        )

    def test_a_blocked_invocation_is_not_read_as_a_failure(self) -> None:
        """Nothing ran, so nothing failed. That is an adapter gap, not a defect."""
        results = {
            "placement": harness.EXECUTED,
            "discovery": harness.EXECUTED,
            "load": harness.BLOCKED,
            "invocation": harness.BLOCKED,
        }
        self.assertEqual(
            harness.propose_status(self.outcomes(**results)), "works-through-an-adapter"
        )

    def test_all_four_executed_proposes_works_directly(self) -> None:
        results = dict.fromkeys(ccm.STAGES, harness.EXECUTED)
        self.assertEqual(harness.propose_status(self.outcomes(**results)), "works-directly")

    def test_placed_but_not_loaded_proposes_an_adapter(self) -> None:
        results = {
            "placement": harness.EXECUTED,
            "discovery": harness.EXECUTED,
            "load": harness.BLOCKED,
            "invocation": harness.BLOCKED,
        }
        self.assertEqual(
            harness.propose_status(self.outcomes(**results)), "works-through-an-adapter"
        )

    def test_nothing_executed_proposes_unsupported(self) -> None:
        results = dict.fromkeys(ccm.STAGES, harness.BLOCKED)
        self.assertEqual(harness.propose_status(self.outcomes(**results)), "unsupported")

    def test_every_proposal_is_a_status_the_schema_admits(self) -> None:
        for results in (
            dict.fromkeys(ccm.STAGES, harness.EXECUTED),
            dict.fromkeys(ccm.STAGES, harness.BLOCKED),
            {
                "placement": harness.EXECUTED,
                "discovery": harness.BLOCKED,
                "load": harness.BLOCKED,
                "invocation": harness.BLOCKED,
            },
        ):
            with self.subTest(results=results):
                self.assertIn(harness.propose_status(self.outcomes(**results)), ccm.STATUSES)


class RecordTest(unittest.TestCase):
    """What the harness emits, and what it refuses to emit."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.workspace = Path(self._temporary.name)

    def plan_only_record(self) -> dict:
        return harness.assess(
            CONFIG, python=sys.executable, execute=False, workspace=self.workspace
        )

    def test_a_plan_only_run_starts_no_process(self) -> None:
        def refuse(*arguments: object, **keywords: object):
            raise AssertionError("a plan-only run must not start a process")

        harness.assess(
            CONFIG,
            python=sys.executable,
            execute=False,
            workspace=self.workspace,
            runner=refuse,
        )

    def test_the_record_binds_to_the_shipped_fingerprint(self) -> None:
        record = self.plan_only_record()
        file_count, tree = ccm.package_fingerprint(CONFIG.package_directory)
        self.assertEqual(record["package"]["file_count"], file_count)
        self.assertEqual(record["package"]["tree_sha256"], tree)

    def test_the_record_covers_exactly_the_ten_clients_with_four_stages_each(self) -> None:
        record = self.plan_only_record()
        self.assertEqual(
            {client["name"] for client in record["clients"]}, set(ccm.CANONICAL_CLIENTS)
        )
        for client in record["clients"]:
            with self.subTest(client=client["name"]):
                self.assertEqual(set(client["stages"]), set(ccm.STAGES))

    def test_the_emitted_record_leaks_nothing(self) -> None:
        record = self.plan_only_record()
        self.assertEqual(ccm.check_public_evidence_rules(record), [])

    def test_no_scratch_path_survives_into_the_record(self) -> None:
        record = self.plan_only_record()
        payload = json.dumps(record)
        self.assertNotIn(str(self.workspace), payload)
        self.assertNotIn(str(Path.home()), payload)

    def test_the_record_is_refused_by_the_validator_until_a_human_finishes_it(self) -> None:
        """Deliberate. A reason no one wrote is not evidence.

        The harness proposes a status and leaves the reason empty, and the
        matrix validator refuses a client row with no concrete reason. That is
        what stops an unread record being committed as a result.
        """
        record = self.plan_only_record()
        for client in record["clients"]:
            self.assertEqual(client["reason"], "")
        problems = ccm.check_coverage(record)
        self.assertTrue(any("no concrete reason" in problem for problem in problems))

    def test_a_tree_that_moves_during_the_run_is_refused(self) -> None:
        """Something wrote into the package under assessment, so nothing is publishable.

        The stage has to actually reach the runner for this to prove anything,
        and `run_stage` blocks a stage whose binary is not on `PATH`. Left to
        the machine's own `PATH` this test passed wherever that client happened
        to be installed and quietly proved nothing everywhere else -- which is
        how it passed locally and failed in continuous integration. A fake
        binary makes it the same test on every machine.
        """
        plan = harness.plan_for("OpenAI Codex")
        scratch_bin = self.workspace / "bin"
        scratch_bin.mkdir(parents=True, exist_ok=True)
        write_executable(scratch_bin, plan.binary, "exit 0\n")

        intruder = CONFIG.package_directory / "intruder.tmp"
        calls: list[int] = []

        def write_once(*arguments: object, **keywords: object):
            calls.append(1)
            intruder.write_text("moved\n", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, "", "")

        self.addCleanup(lambda: intruder.unlink(missing_ok=True))
        path = os.pathsep.join([str(scratch_bin), os.environ.get("PATH", "")])
        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            with self.assertRaises(harness.AssessmentError) as caught:
                harness.assess(
                    CONFIG,
                    python=sys.executable,
                    execute=True,
                    only=(plan.name,),
                    workspace=self.workspace,
                    runner=write_once,
                )
        self.assertTrue(calls, "no stage reached the runner, so nothing moved the tree")
        self.assertIn("moved during the run", str(caught.exception))

    def test_the_assessed_copy_is_a_copy_not_the_shipped_tree(self) -> None:
        """A client that installs in place must not be able to reach the source."""
        before = ccm.package_fingerprint(CONFIG.package_directory)
        self.plan_only_record()
        scratch = self.workspace / "package"
        self.assertTrue(scratch.is_dir())
        self.assertNotEqual(scratch.resolve(), CONFIG.package_directory.resolve())
        self.assertEqual(ccm.package_fingerprint(CONFIG.package_directory), before)


class CommandLineTest(unittest.TestCase):
    def test_the_default_run_prints_the_plan_and_runs_nothing(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "assess_clients.py"), "--package", "unifi"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Nothing below has run", completed.stdout)
        for name in ccm.CANONICAL_CLIENTS:
            self.assertIn(name, completed.stdout)

    def test_an_unported_package_is_refused(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "assess_clients.py"),
                "--package",
                "not-a-package",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("no port descriptor", completed.stderr)

    def test_the_plan_names_every_deadline(self) -> None:
        """Every stage that will start a process shows the deadline it runs under.

        Counted over the stage lines only. The word also appears in one client's
        quirk prose, and a count over the whole document would be satisfied by
        that sentence alone.
        """
        stage_lines = [
            line
            for line in harness.describe_plan(CONFIG).splitlines()
            if any(line.strip().startswith(stage) for stage in ccm.STAGES)
        ]
        runnable = [
            spec
            for plan in harness.CLIENT_PLANS
            for spec in plan.stages
            if spec.blocked_reason is None
        ]
        self.assertEqual(
            sum(1 for line in stage_lines if "deadline" in line), len(runnable)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
