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
import time
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
    directory.mkdir(parents=True, exist_ok=True)
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

    def test_every_command_status_is_recorded_not_just_the_first(self) -> None:
        """A failing second entrypoint must not read as a working package.

        The pilot shipped a package whose two clients both failed at import.
        A stage that runs both and then reports only the first has checked
        both and learned nothing — the silent green this harness exists to
        prevent, one level up from where it bit last time.
        """
        write_executable(self.bin, "second-fails", 'exit 7\n')
        spec = harness.StageSpec("invocation", ("ok-client",))
        real = harness.stage_argvs
        harness.stage_argvs = lambda c, p, s, v: (("ok-client",), ("second-fails",))
        try:
            outcome = self.outcome(spec)
        finally:
            harness.stage_argvs = real
        self.assertEqual(outcome.result, harness.EXECUTED)
        self.assertEqual(outcome.returncodes, (0, 7))
        self.assertEqual(outcome.returncode, 7, "the deciding status ignored the failure")

    def test_a_stage_naming_an_unresolved_placeholder_is_blocked(self) -> None:
        """A value an earlier stage never reported is not guessed at.

        Two clients generate their own install id at placement. When the
        capture misses, the invocation path used to fall back to the package
        name, run a path that does not exist, and grade the package as failing
        for a value the client never reported.
        """
        spec = harness.StageSpec("invocation", ("ok-client", f"{harness.PLUGIN_ID}/x"))
        values = {key: value for key, value in self.values.items() if key != harness.PLUGIN_ID}
        outcome = harness.run_stage(
            harness.plan_for("Grok"), spec, CONFIG, values, self.environment
        )
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertIn(harness.PLUGIN_ID, outcome.reason)
        self.assertIn("never reported", outcome.reason)


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


class RealBinaryResolutionTest(FakeClientFixture):
    """The P0 class: the harness never guesses which same-named binary is real.

    Two earlier attempts guessed. `which` returned the wrapper, so the wrapper
    exec'd itself. Returning the first PATH entry that was not the *same file*
    as the wrapper accepted a second *copy* of the wrapper -- same defect, one
    arrangement further out. Nothing on disk distinguishes a launcher from what
    it launches, so the value is taken from the operator or the client is
    blocked.
    """

    def setUp(self) -> None:
        super().setUp()
        self.wrappers = self.base / "wrap"
        self.real = self.base / "real"
        write_executable(self.wrappers, "grok", 'exec "$GROK_AUTO_TRUST_REAL_BIN" "$@"\n')
        write_executable(self.real, "grok", 'echo "the real client"\nexit 0\n')
        self.path = os.pathsep.join([str(self.wrappers), str(self.real)])

    def test_an_explicit_path_is_used(self) -> None:
        resolved = harness.resolve_real_binary(
            "grok",
            "GROK_AUTO_TRUST_REAL_BIN",
            supplied={"grok": str(self.real / "grok")},
            environ={"PATH": self.path},
            path=self.path,
        )
        self.assertEqual(Path(resolved), self.real / "grok")

    def test_an_exported_override_is_used_when_no_flag_is_given(self) -> None:
        """The wrapper's own documented variable, which the operator already sets."""
        resolved = harness.resolve_real_binary(
            "grok",
            "GROK_AUTO_TRUST_REAL_BIN",
            environ={"PATH": self.path, "GROK_AUTO_TRUST_REAL_BIN": str(self.real / "grok")},
            path=self.path,
        )
        self.assertEqual(Path(resolved), self.real / "grok")

    def test_with_nothing_supplied_it_refuses_rather_than_guessing(self) -> None:
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.resolve_real_binary(
                "grok", "GROK_AUTO_TRUST_REAL_BIN", environ={"PATH": self.path}, path=self.path
            )
        message = str(caught.exception)
        self.assertIn("will not guess", message)
        self.assertIn("--real-binary", message)

    def test_a_copied_wrapper_is_never_selected(self) -> None:
        """The defect the previous repair reintroduced.

        Two byte-identical wrapper copies have different inodes, so a
        same-file check passes them. With no inference at all there is nothing
        to pass.
        """
        copy = self.base / "copy"
        write_executable(copy, "grok", 'exec "$GROK_AUTO_TRUST_REAL_BIN" "$@"\n')
        path = os.pathsep.join([str(self.wrappers), str(copy)])
        with self.assertRaises(harness.AssessmentError):
            harness.resolve_real_binary(
                "grok", "GROK_AUTO_TRUST_REAL_BIN", environ={"PATH": path}, path=path
            )

    def test_an_override_naming_the_launcher_itself_is_refused(self) -> None:
        """Even supplied explicitly, a wrapper pointed at itself still recurses."""
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.resolve_real_binary(
                "grok",
                "GROK_AUTO_TRUST_REAL_BIN",
                supplied={"grok": str(self.wrappers / "grok")},
                environ={"PATH": self.path},
                path=self.path,
            )
        self.assertIn("same file as", str(caught.exception))

    def test_a_symlink_to_the_launcher_is_refused(self) -> None:
        linked = self.base / "linked"
        linked.mkdir()
        (linked / "grok").symlink_to(self.wrappers / "grok")
        with self.assertRaises(harness.AssessmentError):
            harness.resolve_real_binary(
                "grok",
                "GROK_AUTO_TRUST_REAL_BIN",
                supplied={"grok": str(linked / "grok")},
                environ={"PATH": self.path},
                path=self.path,
            )

    def test_a_supplied_path_that_is_not_executable_is_refused(self) -> None:
        plain = self.base / "not-executable"
        plain.write_text("#!/bin/sh\n", encoding="utf-8")
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.resolve_real_binary(
                "grok",
                "GROK_AUTO_TRUST_REAL_BIN",
                supplied={"grok": str(plain)},
                environ={"PATH": self.path},
                path=self.path,
            )
        self.assertIn("not an executable file", str(caught.exception))

    def test_a_wrapper_client_with_nothing_supplied_is_blocked_not_run(self) -> None:
        """End to end: the whole client is blocked, and no process starts."""
        plan = harness.plan_for("Grok")
        started: list[object] = []

        def refuse(*arguments: object, **keywords: object):
            started.append(arguments)
            raise AssertionError("a stage started despite an unresolved override")

        with unittest.mock.patch.dict(os.environ, {"PATH": self.path}, clear=False):
            os.environ.pop("GROK_AUTO_TRUST_REAL_BIN", None)
            record = harness.assess(
                CONFIG,
                python=sys.executable,
                execute=True,
                only=(plan.name,),
                workspace=self.base / "ws",
                runner=refuse,
            )
        self.assertFalse(started)
        row = record["clients"][0]
        for stage in ccm.STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(row["stages"][stage]["result"], harness.BLOCKED)
                self.assertIn("will not guess", row["stages"][stage]["reason"])

    def test_the_cli_parses_and_refuses_real_binary_pairs(self) -> None:
        self.assertEqual(
            harness.parse_real_binaries(["grok=/usr/local/bin/grok"]),
            {"grok": "/usr/local/bin/grok"},
        )
        for bad in ("grok", "=/path", "grok=", "  =  "):
            with self.subTest(value=bad):
                with self.assertRaises(harness.AssessmentError):
                    harness.parse_real_binaries([bad])


class ProcessGroupTest(FakeClientFixture):
    """A deadline has to be a containment boundary, not a note about one."""

    def test_a_timed_out_launcher_does_not_leave_its_client_running(self) -> None:
        marker = self.base / "descendant-still-alive"
        write_executable(
            self.bin,
            "spawning-launcher",
            f'( sleep 5; touch "{marker}" ) &\nsleep 30\n',
        )
        outcome = self.outcome(
            harness.StageSpec("placement", ("spawning-launcher",), timeout=0.6)
        )
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertIn("process group was terminated and is empty", outcome.reason)
        # The descendant had 5s to appear; the group was killed well before.
        deadline = time.time() + 8
        while time.time() < deadline:
            if marker.exists():
                break
            time.sleep(0.2)
        self.assertFalse(
            marker.exists(),
            "a client descendant outlived the deadline and kept writing",
        )


    def test_a_descendant_that_leaves_the_session_is_not_claimed_as_killed(self) -> None:
        """`killpg` reaches a group, and a client can leave the group.

        A descendant that calls `setsid` has its own session before the deadline
        arrives, so the kill does not reach it and the probe does not see it. The
        cleanup used to answer that with "no client descendant survived it" --
        a claim about processes it cannot observe, on exactly the runs where the
        claim is false. What it may say is what it established: this group is
        empty, and that is not the same statement.

        Cycle 13's published proof said this test "confirms the descendant really
        does survive". It did not: it wrote a marker and never read it. Survival
        was observed by a separate uncommitted probe. The wait below is the
        round-5 repair -- without it the test still passes if the descendant
        dies, which is the overclaim.
        """
        marker = self.base / "escaped-descendant"
        escape = (
            f"{sys.executable} -c "
            f"'import os,time,pathlib; os.setsid(); time.sleep(3); "
            f'pathlib.Path("{marker}").write_text("x")\' &\n'
            "sleep 30\n"
        )
        write_executable(self.bin, "escaping-launcher", escape)
        outcome = self.outcome(
            harness.StageSpec("placement", ("escaping-launcher",), timeout=0.6)
        )
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertIn(
            "is not evidence that none is still running",
            outcome.reason,
            "the cleanup claimed containment it cannot observe",
        )
        self.assertNotIn("no client descendant survived", outcome.reason)
        deadline = time.time() + 7
        while time.time() < deadline and not marker.exists():
            time.sleep(0.2)
        self.assertTrue(
            marker.exists(),
            "the escaped descendant did not survive to write its marker; this test "
            "cannot claim the cleanup failed to observe an escape it did not produce",
        )

    def test_the_leader_is_reaped_before_the_group_is_probed(self) -> None:
        """An unreaped leader is a zombie, and a zombie is still a process.

        The cleanup ends by asking whether the group still holds anyone. Asked
        before the direct child is reaped, that question is answered by the
        child's own corpse: Linux replies success and macOS replies EPERM, so
        the probe reported a surviving descendant on every run on both
        platforms. A repair that read EPERM as "nothing left to signal" made the
        macOS answer right for the wrong reason and left Linux reporting that a
        descendant "may survive" on runs where none did -- a warning that fires
        every time is a warning nobody reads.

        No client here, no descendant, no signal that matters: the leader has
        already exited by the time the cleanup runs, and the only thing the
        answer can come from is whether it was reaped first. Asserted without
        naming an errno, because which one appears is exactly the platform
        difference this ordering exists to stop mattering.
        """
        process = subprocess.Popen(
            [sys.executable, "-c", "raise SystemExit(0)"], start_new_session=True
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.killpg(process.pid, 0)  # the zombie is still visible here
            except ProcessLookupError:  # pragma: no cover - reaped by something else
                self.skipTest("the leader was reaped before the probe could see it")
            if process.poll() is None and os.waitpid(process.pid, os.WNOHANG) == (0, 0):
                break
            time.sleep(0.05)

        reason = harness.terminate_process_group(process)
        self.assertIn(
            "process group was terminated and is empty",
            reason,
            "the leader's own unreaped corpse was read as a surviving client",
        )

    def test_a_leader_that_exits_still_has_its_descendant_killed(self) -> None:
        """The class the first repair missed.

        A launcher that starts a descendant and exits leaves the descendant
        holding the captured pipes, so the read still times out while the leader
        is already gone. Resolving the group id through the exited leader failed,
        and the cleanup reported the group had exited while the descendant kept
        running.
        """
        marker = self.base / "leader-descendant-alive"
        write_executable(
            self.bin, "exiting-leader", f'( sleep 4; touch "{marker}" ) &\nexit 0\n'
        )
        outcome = self.outcome(
            harness.StageSpec("placement", ("exiting-leader",), timeout=0.8)
        )
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertIn(
            "process group was terminated and is empty",
            outcome.reason,
            "the cleanup reported a state it had not established",
        )
        deadline = time.time() + 7
        while time.time() < deadline and not marker.exists():
            time.sleep(0.2)
        self.assertFalse(
            marker.exists(),
            "the descendant outlived its exited leader and the deadline",
        )


class WorkspaceFreshnessTest(unittest.TestCase):
    """A reused --workspace must never hand a client an earlier run's copy."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.workspace = Path(self._temporary.name)

    def test_a_second_run_in_the_same_workspace_gets_fresh_copies(self) -> None:
        """The defect: the copy was made only when the path did not exist.

        A client that mutated its copy left that copy behind, and the next run
        assessed the mutated tree while still binding the record to the shipped
        package's fingerprint.
        """
        harness.assess(
            CONFIG, python=sys.executable, execute=False,
            only=("OpenAI Codex",), workspace=self.workspace,
        )
        first = next(p for p in self.workspace.glob("*/*/package") if p.is_dir())
        (first / "INTRUDER.txt").write_text("mutated\n", encoding="utf-8")

        harness.assess(
            CONFIG, python=sys.executable, execute=False,
            only=("OpenAI Codex",), workspace=self.workspace,
        )
        copies = sorted(p for p in self.workspace.glob("*/*/package") if p.is_dir())
        self.assertEqual(len(copies), 2, "the second run reused the first run's directory")
        second = [p for p in copies if p != first][0]
        self.assertFalse(
            (second / "INTRUDER.txt").exists(),
            "the second run inherited a mutated copy from the first",
        )
        self.assertEqual(
            ccm.package_fingerprint(second),
            ccm.package_fingerprint(CONFIG.package_directory),
            "the fresh copy does not match the shipped package",
        )

    def test_a_pre_existing_copy_is_refused_rather_than_reused(self) -> None:
        """Two guards cover this defect, and only one of them was proved.

        `allocate_run_directory` hands out a directory no run has used, so the
        copy can never find its destination occupied -- which meant the copy
        could be made conditional and nothing failed. A guard whose only proof is
        that another guard makes it unreachable is a guard that can be deleted.
        Force the collision the run directory normally prevents.
        """
        run = self.workspace / "run-001"
        stale = run / "openai-codex" / "package"
        stale.mkdir(parents=True)
        (stale / "INTRUDER.txt").write_text("left by an earlier client\n", encoding="utf-8")

        with unittest.mock.patch.object(harness, "allocate_run_directory", lambda _: run):
            with self.assertRaises(FileExistsError):
                harness.assess(
                    CONFIG, python=sys.executable, execute=False,
                    only=("OpenAI Codex",), workspace=self.workspace,
                )
        self.assertTrue(
            (stale / "INTRUDER.txt").exists(),
            "the run destroyed the evidence it should have refused to assess",
        )

    def test_each_run_gets_its_own_numbered_directory(self) -> None:
        for _ in range(3):
            harness.assess(
                CONFIG, python=sys.executable, execute=False,
                only=("OpenAI Codex",), workspace=self.workspace,
            )
        runs = sorted(p.name for p in self.workspace.iterdir() if p.is_dir())
        self.assertEqual(runs, ["run-001", "run-002", "run-003"])

    def test_a_supplied_run_directory_that_already_holds_a_run_is_refused(self) -> None:
        """Naming the run directory must not skip the freshness guard.

        `run_directory` was added so the write path and the announced path are
        one value. The parameter accepted any existing directory, so a caller
        could hand `assess` last run's path, mix two package copies, and
        overwrite the first transcript through `write_private`.
        """
        binaries = self.workspace / "bin"
        write_executable(binaries, "codex", "exit 0\n")
        path = os.pathsep.join([str(binaries), os.environ.get("PATH", "")])
        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            harness.assess(
                CONFIG, python=sys.executable, execute=True,
                only=("OpenAI Codex",), workspace=self.workspace,
            )
        run = next(p for p in self.workspace.iterdir() if p.is_dir() and p.name.startswith("run-"))
        transcript = harness.transcript_path(run)
        original = transcript.read_text(encoding="utf-8")
        marker = run / "openai-codex" / "package" / "INTRUDER.txt"
        marker.write_text("from the first run\n", encoding="utf-8")

        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            with self.assertRaises(harness.AssessmentError) as caught:
                harness.assess(
                    CONFIG, python=sys.executable, execute=True,
                    only=("OpenAI Codex",), workspace=self.workspace,
                    run_directory=run,
                )
        self.assertIn("not empty", str(caught.exception))
        self.assertEqual(
            transcript.read_text(encoding="utf-8"),
            original,
            "the second assessment overwrote the first run's transcript",
        )
        self.assertTrue(
            marker.exists(),
            "the second assessment mixed its copy into the first run's directory",
        )

    def test_a_supplied_run_directory_that_does_not_exist_is_refused(self) -> None:
        missing = self.workspace / "run-999"
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.assess(
                CONFIG, python=sys.executable, execute=False,
                only=("OpenAI Codex",), workspace=self.workspace,
                run_directory=missing,
            )
        self.assertIn("does not exist", str(caught.exception))
        self.assertFalse(missing.exists(), "the harness created the directory it should have refused")

    def test_a_supplied_run_directory_outside_the_workspace_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as outsider:
            outside = Path(outsider)
            with self.assertRaises(harness.AssessmentError) as caught:
                harness.assess(
                    CONFIG, python=sys.executable, execute=False,
                    only=("OpenAI Codex",), workspace=self.workspace,
                    run_directory=outside,
                )
            self.assertIn("not inside workspace", str(caught.exception))
            self.assertEqual(list(outside.iterdir()), [])

    def test_the_workspace_itself_is_refused_as_a_run_directory(self) -> None:
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.assess(
                CONFIG, python=sys.executable, execute=False,
                only=("OpenAI Codex",), workspace=self.workspace,
                run_directory=self.workspace,
            )
        self.assertIn("workspace itself", str(caught.exception))

    def test_a_supplied_empty_run_directory_inside_the_workspace_is_accepted(self) -> None:
        """The command line's path: allocate, then pass the empty directory in."""
        run = self.workspace / "run-001"
        run.mkdir()
        harness.assess(
            CONFIG, python=sys.executable, execute=False,
            only=("OpenAI Codex",), workspace=self.workspace, run_directory=run,
        )
        self.assertTrue((run / "openai-codex" / "package").is_dir())
        self.assertEqual(
            sorted(p.name for p in self.workspace.iterdir() if p.is_dir()),
            ["run-001"],
        )


class InvalidEntrypointTest(unittest.TestCase):
    """A descriptor typo must not be charged to the package."""

    def variant(self, entrypoints: list[str]) -> port_config.PortConfig:
        return port_config.parse(
            {
                "schema_version": port_config.SCHEMA_VERSION,
                "package": CONFIG.name,
                "package_root": CONFIG.package_root,
                "source": {
                    "repository": CONFIG.source.repository,
                    "package_path": CONFIG.source.package_path,
                },
                "custody": {},
                "assessment": {
                    "credential_prefixes": list(CONFIG.assessment.credential_prefixes),
                    "package_scripts": list(CONFIG.assessment.package_scripts),
                    "mutating_operations": sorted(CONFIG.assessment.mutating_operations),
                    "entrypoints": entrypoints,
                    "skill_units": list(CONFIG.assessment.skill_units),
                    "declared_none": [],
                },
            },
            root=CONFIG.root,
            path=CONFIG.path,
        )

    def test_an_entrypoint_the_package_does_not_carry_is_refused(self) -> None:
        """Left to run, python exits 2 and propose_status reports `failed`."""
        config = self.variant(["skills/unifi-network/scripts/typoed_client.py"])
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.entrypoint_paths(config, harness.plan_for("Claude Code"))
        message = str(caught.exception)
        self.assertIn("does not carry", message)
        self.assertIn("blaming the package", message)

    def test_the_repository_gate_refuses_it_too(self) -> None:
        """Two independent catches: the gate, and the harness before it runs."""
        import check_repo

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ports").mkdir()
            (root / CONFIG.package_root).mkdir(parents=True)
            (root / CONFIG.package_root / "plugin.json").write_text(
                json.dumps({"name": CONFIG.name, "version": "1.0"}), encoding="utf-8"
            )
            document = json.loads(CONFIG.path.read_text(encoding="utf-8"))
            document["assessment"]["entrypoints"] = ["scripts/absent.py"]
            (root / "ports" / f"{CONFIG.name}.json").write_text(
                json.dumps(document), encoding="utf-8"
            )
            errors = check_repo.check_port_descriptors(root)
        self.assertTrue(any("assessment.entrypoints" in e for e in errors), errors)

    def test_the_shipped_descriptor_names_only_files_that_exist(self) -> None:
        for relative in CONFIG.assessment.entrypoints:
            with self.subTest(entrypoint=relative):
                self.assertTrue((CONFIG.package_directory / relative).is_file())


class TranscriptPrivacyTest(unittest.TestCase):
    """Raw unredacted client output must not be world-readable."""

    def test_the_transcript_is_written_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            os.chmod(workspace, 0o755)
            target = harness.transcript_path(workspace)
            previous = os.umask(0o022)
            try:
                harness.write_private(target, '{"x": "raw client output"}')
            finally:
                os.umask(previous)
            mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(mode, 0o600, f"transcript is {oct(mode)}, not owner-only")

    def test_the_file_is_created_owner_only_before_anything_is_written(self) -> None:
        """The chmod after the write cannot protect the window before it.

        Both guards leave the same final mode, so a test that reads the mode
        afterwards passes with the *creation* mode widened to 0644 -- and the raw
        client output is then written into a world-readable file and tightened a
        moment later. Neutralize the second guard to observe the first.
        """
        with tempfile.TemporaryDirectory() as directory:
            target = harness.transcript_path(Path(directory))
            previous = os.umask(0o022)
            try:
                with unittest.mock.patch.object(harness.os, "chmod", lambda *a, **k: None):
                    harness.write_private(target, '{"x": "raw client output"}')
                mode = stat.S_IMODE(target.stat().st_mode)
            finally:
                os.umask(previous)
        self.assertEqual(
            mode, 0o600, f"created {oct(mode)}; raw output is exposed until the chmod lands"
        )

    def test_an_existing_loose_file_is_tightened_on_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = harness.transcript_path(Path(directory))
            target.write_text("stale", encoding="utf-8")
            os.chmod(target, 0o644)
            harness.write_private(target, '{"x": "fresh"}')
            mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(mode, 0o600)


class TranscriptTest(FakeClientFixture):
    """Raw output is kept for the operator and kept out of the record."""

    def test_a_stage_retains_each_command_output(self) -> None:
        outcome = self.outcome(harness.StageSpec("discovery", ("ok-client", "list")))
        self.assertEqual(len(outcome.transcript), 1)
        self.assertIn("two skills resolved", outcome.transcript[0].stdout)

    def test_the_transcript_is_bounded(self) -> None:
        write_executable(
            self.bin, "loud-client", f'python3 -c "print(\'x\' * {harness.TRANSCRIPT_LIMIT * 2})"\n'
        )
        outcome = self.outcome(harness.StageSpec("discovery", ("loud-client",)))
        kept = outcome.transcript[0].stdout
        self.assertLessEqual(len(kept), harness.TRANSCRIPT_LIMIT + 200)
        self.assertIn("more characters not kept", kept)

    def test_the_record_never_carries_raw_output(self) -> None:
        outcome = self.outcome(harness.StageSpec("discovery", ("ok-client", "list")))
        self.assertNotIn("two skills resolved", json.dumps(outcome.record()))


class FailurePathTranscriptTest(FakeClientFixture):
    """The rows that most need output are the ones that used to lose it."""

    def test_a_timed_out_stage_keeps_what_already_ran(self) -> None:
        write_executable(self.bin, "slow-second", "sleep 30\n")
        real = harness.stage_argvs
        harness.stage_argvs = lambda c, p, s, v: (("ok-client",), ("slow-second",))
        try:
            outcome = self.outcome(
                harness.StageSpec("placement", ("ok-client",), timeout=0.8)
            )
        finally:
            harness.stage_argvs = real
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertTrue(outcome.transcript, "the timeout discarded the whole transcript")
        self.assertIn(
            "two skills resolved",
            "".join(item.stdout for item in outcome.transcript),
            "the completed command's output was lost",
        )

    def test_a_timed_out_stage_records_the_timed_out_command_too(self) -> None:
        outcome = self.outcome(
            harness.StageSpec("placement", ("hanging-client",), timeout=0.6)
        )
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertEqual(len(outcome.transcript), 1)
        self.assertIn("hanging-client", outcome.transcript[0].command)

    def test_the_timed_out_command_is_in_the_public_record_too(self) -> None:
        """A stage that started two commands must not record one.

        The deadline repair put the timed-out command in the private transcript
        and stopped there, so the version-2 record named only the commands that
        finished. Two consequences, both silent: the stage is not reproducible
        from the record, and the post-run safety rule -- which grades `commands`
        -- never sees the command that actually started.
        """
        write_executable(self.bin, "slow-second", "sleep 30\n")
        real = harness.stage_argvs
        harness.stage_argvs = lambda c, p, s, v: (("ok-client",), ("slow-second",))
        try:
            outcome = self.outcome(
                harness.StageSpec("placement", ("ok-client",), timeout=0.8)
            )
        finally:
            harness.stage_argvs = real

        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertEqual(
            [item.command for item in outcome.commands],
            ["ok-client", "slow-second"],
            "the command that hit the deadline is missing from the public record",
        )
        self.assertTrue(
            outcome.commands[-1].timed_out,
            "the command that hit the deadline is not marked timed_out",
        )
        self.assertIsNone(outcome.commands[-1].exit_status)
        recorded = outcome.record()
        self.assertEqual(
            recorded["command"],
            recorded["commands"][0]["command"],
            "the alias and the list disagree about what ran first",
        )
        self.assertEqual(len(recorded["commands"]), 2)
        self.assertEqual(
            recorded["commands"][-1],
            {"command": "slow-second", "timed_out": True},
        )
        self.assertTrue(outcome.transcript[-1].timed_out)
        self.assertIsNone(outcome.transcript[-1].returncode)
        self.assertNotIn("exit_status", outcome.transcript[-1].record())

    def test_an_invalidated_client_keeps_its_transcript(self) -> None:
        """Losing the classification must not lose the evidence of why."""
        workspace = self.base / "ws"
        plan = harness.plan_for("OpenAI Codex")
        write_executable(self.base / "cbin", plan.binary, 'echo "codex says no" >&2\nexit 3\n')

        def mutate_once(*arguments: object, **keywords: object):
            copies = list(workspace.glob("*/*/package"))
            if copies:
                (copies[0] / "INTRUDER.txt").write_text("x\n", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, "client output here", "")

        path = os.pathsep.join([str(self.base / "cbin"), os.environ.get("PATH", "")])
        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            harness.assess(
                CONFIG, python=sys.executable, execute=True,
                only=(plan.name,), workspace=workspace, runner=mutate_once,
            )
        transcript = json.loads(
            harness.transcript_path(sorted(workspace.iterdir())[0]).read_text(encoding="utf-8")
        )
        kept = json.dumps(transcript)
        self.assertIn("client output here", kept, "invalidation discarded the transcript")


    def test_an_invalidated_client_is_not_classified_at_all(self) -> None:
        """Keeping the transcript is half of it; the stage results must not stand.

        Every command returns 0 and the package is changed on the last of them,
        so on their own terms all four stages succeeded and the status they
        propose is `works-directly`. They must not stand: the tree the record's
        fingerprint names is not the tree they ran against, so nothing about this
        client was established. Invalidation rewrites every stage to `blocked`
        with the reason, and `unsupported` follows from there rather than being
        asserted separately.
        """
        workspace = self.base / "ws-status"
        plan = harness.plan_for("Claude Code")
        write_executable(self.base / "sbin", plan.binary, "exit 0\n")
        calls: list[int] = []

        def mutate_last(*arguments: object, **keywords: object):
            calls.append(1)
            if len(calls) == 5:  # Claude Code runs five commands across four stages
                copies = list(workspace.glob("*/*/package"))
                if copies:
                    (copies[0] / "INTRUDER.txt").write_text("x\n", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, "all four stages fine", "")

        path = os.pathsep.join([str(self.base / "sbin"), os.environ.get("PATH", "")])
        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            record = harness.assess(
                CONFIG, python=sys.executable, execute=True,
                only=(plan.name,), workspace=workspace, runner=mutate_last,
            )
        row = record["clients"][0]
        self.assertEqual(
            [row["stages"][stage]["result"] for stage in ccm.STAGES],
            ["blocked"] * len(ccm.STAGES),
            "stages that ran against bytes which no longer exist were left standing",
        )
        for stage in ccm.STAGES:
            self.assertIn(
                "changed the package copy",
                row["stages"][stage]["reason"],
                f"{stage} does not say why its result was withdrawn",
            )
        self.assertEqual(row["status"], "unsupported")

    def test_a_client_that_leaves_the_package_alone_keeps_its_results(self) -> None:
        """The contrast: the same run without the change is `works-directly`."""
        plan = harness.plan_for("Claude Code")
        write_executable(self.base / "sbin", plan.binary, "exit 0\n")
        path = os.pathsep.join([str(self.base / "sbin"), os.environ.get("PATH", "")])
        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            record = harness.assess(
                CONFIG, python=sys.executable, execute=True, only=(plan.name,),
                workspace=self.base / "ws-clean",
                runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "fine", ""),
            )
        self.assertEqual(record["clients"][0]["status"], "works-directly")


class DuplicateDiagnosticTest(unittest.TestCase):
    """Version 2 keeps `command` as an alias of commands[0]; grade it once."""

    def test_one_unsafe_command_yields_one_problem(self) -> None:
        script = CONFIG.assessment.package_scripts[0]
        operation = sorted(CONFIG.assessment.mutating_operations)[0]
        unsafe = f"python3 {script} {operation}"
        record = {
            "clients": [
                {
                    "name": "Claude Code",
                    "stages": {
                        "invocation": {
                            "result": "executed",
                            "command": unsafe,
                            "commands": [{"command": unsafe, "exit_status": 0}],
                            "evidence": "x",
                        }
                    },
                }
            ]
        }
        problems = ccm.check_safety_rules(record, CONFIG)
        self.assertEqual(len(problems), 1, problems)

    def test_a_version_one_stage_is_still_graded(self) -> None:
        script = CONFIG.assessment.package_scripts[0]
        operation = sorted(CONFIG.assessment.mutating_operations)[0]
        record = {
            "clients": [
                {
                    "name": "Claude Code",
                    "stages": {
                        "invocation": {
                            "result": "executed",
                            "command": f"python3 {script} {operation}",
                            "evidence": "x",
                        }
                    },
                }
            ]
        }
        self.assertEqual(len(ccm.check_safety_rules(record, CONFIG)), 1)

    def test_an_unsafe_second_command_is_still_caught(self) -> None:
        """Deduplicating the alias must not stop grading the rest."""
        script = CONFIG.assessment.package_scripts[0]
        operation = sorted(CONFIG.assessment.mutating_operations)[0]
        safe = f"python3 {script} list"
        record = {
            "clients": [
                {
                    "name": "Claude Code",
                    "stages": {
                        "invocation": {
                            "result": "executed",
                            "command": safe,
                            "commands": [
                                {"command": safe, "exit_status": 0},
                                {"command": f"python3 {script} {operation}", "exit_status": 0},
                            ],
                            "evidence": "x",
                        }
                    },
                }
            ]
        }
        self.assertEqual(len(ccm.check_safety_rules(record, CONFIG)), 1)


class PerCommandStatusTest(FakeClientFixture):
    """A stage that ran several commands records each one beside its status."""

    def test_each_command_is_recorded_with_its_own_status(self) -> None:
        write_executable(self.bin, "second-fails", "exit 7\n")
        real = harness.stage_argvs
        harness.stage_argvs = lambda c, p, s, v: (("ok-client",), ("second-fails",))
        try:
            outcome = self.outcome(harness.StageSpec("invocation", ("ok-client",)))
        finally:
            harness.stage_argvs = real
        recorded = outcome.record()
        self.assertEqual(len(recorded["commands"]), 2)
        self.assertEqual(recorded["commands"][0]["exit_status"], 0)
        self.assertEqual(recorded["commands"][1]["exit_status"], 7)
        self.assertEqual(recorded["commands"][0]["command"], recorded["command"])
        self.assertNotIn("timed_out", recorded["commands"][0])
        self.assertNotIn("timed_out", recorded["commands"][1])

    def test_a_reader_can_tell_which_command_failed(self) -> None:
        """The point of the change: the statuses are no longer anonymous."""
        write_executable(self.bin, "second-fails", "exit 7\n")
        real = harness.stage_argvs
        harness.stage_argvs = lambda c, p, s, v: (("ok-client",), ("second-fails",))
        try:
            outcome = self.outcome(harness.StageSpec("invocation", ("ok-client",)))
        finally:
            harness.stage_argvs = real
        failing = [e for e in outcome.record()["commands"] if e.get("exit_status") != 0]
        self.assertEqual(len(failing), 1)
        self.assertIn("second-fails", failing[0]["command"])

    def test_a_command_terminated_by_sighup_is_not_recorded_as_a_deadline(self) -> None:
        """subprocess returncode is -1 for SIGHUP; that is a real exit status.

        The deadline path used to write -1 and claim no real exit status can
        say that. A process that ends by signal 1 produces exactly -1, so a
        reader of -1 cannot tell 'killed at the deadline' from 'SIGHUP'. This
        test is the SIGHUP side of that distinction; the timeout test is the
        other side.
        """
        write_executable(
            self.bin,
            "sighup-self",
            f'exec {sys.executable} -c "import os,signal; os.kill(os.getpid(), signal.SIGHUP)"\n',
        )
        outcome = self.outcome(harness.StageSpec("discovery", ("sighup-self",)))
        self.assertEqual(outcome.result, harness.EXECUTED)
        self.assertEqual(outcome.commands[0].exit_status, -1)
        self.assertFalse(outcome.commands[0].timed_out)
        recorded = outcome.commands[0].record()
        self.assertEqual(recorded["exit_status"], -1)
        self.assertNotIn("timed_out", recorded)

    def test_a_command_cannot_be_both_exited_and_timed_out(self) -> None:
        with self.assertRaises(harness.AssessmentError):
            harness.StageCommand("client run", -1, timed_out=True)
        with self.assertRaises(harness.AssessmentError):
            harness.StageCommand("client run")


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

    def test_every_stage_argv_is_fully_substituted_before_it_runs(self) -> None:
        """No stage may reach a process still carrying a placeholder.

        The invocation stage's paths come from the descriptor as templates.
        Returning them unsubstituted made every client run a literal
        `<client-home>/…` path -- a file that never exists, and an exit status
        that would be blamed on the package. Asserted over every stage of every
        client rather than the one that broke.
        """
        values = {
            harness.PACKAGE: "/scratch/package",
            harness.CLIENT_HOME: "/scratch/home",
            harness.PYTHON: "/usr/bin/python3.12",
            harness.PLUGIN_NAME: CONFIG.name,
            harness.PLUGIN_ID: "unifi-37c9f17b",
        }
        for plan in harness.CLIENT_PLANS:
            for spec in plan.stages:
                if spec.blocked_reason is not None:
                    continue
                for argv in harness.stage_argvs(CONFIG, plan, spec, values):
                    with self.subTest(client=plan.name, stage=spec.stage):
                        self.assertEqual(harness.unresolved_placeholders(argv), [])

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
                "custody": {},
                "assessment": {
                    "credential_prefixes": ["UNIFI_"],
                    "package_scripts": ["unifi_network_client.py"],
                    "mutating_operations": ["reboot"],
                    # A file the package really carries, so the existence
                    # check passes and the skill-unit rule is what refuses it.
                    "entrypoints": ["scripts/discover.py"],
                    "skill_units": ["skills/unifi-network"],
                    "declared_none": [],
                },
            },
            root=ROOT,
            path=ROOT / "ports" / "unifi.json",
        )
        with self.assertRaises(harness.AssessmentError) as caught:
            harness.entrypoint_paths(variant, harness.plan_for("OpenCode"))
        self.assertIn("skill_units", str(caught.exception))

    def test_skill_scoped_plan_with_package_root_entrypoints_blocks_invocation_in_advance(self) -> None:
        """When entrypoints sit at package root, a skill-scoped client blocks invocation."""
        mc_config = port_config.load("mission-control", ROOT)
        for name in ("OpenCode", "Gemini CLI", "Muse", "Hermes"):
            plan = harness.plan_for(name)
            spec = plan.stage("invocation")
            with self.subTest(client=name):
                blocked = harness.stage_blocked_reason(mc_config, plan, spec)
                self.assertIsNotNone(blocked)
                self.assertIn(name, blocked)
                self.assertIn("installs skill units rather than the package", blocked)
                for entrypoint in mc_config.assessment.entrypoints:
                    self.assertIn(entrypoint, blocked)
                outcome = harness.run_stage(
                    plan,
                    spec,
                    mc_config,
                    {
                        harness.PACKAGE: "/scratch/package",
                        harness.PYTHON: sys.executable,
                        harness.CLIENT_HOME: "/scratch/home",
                        harness.PLUGIN_NAME: mc_config.name,
                    },
                    dict(os.environ),
                )
                self.assertEqual(outcome.result, harness.BLOCKED)
                self.assertEqual(outcome.reason, blocked)

    def test_skill_scoped_plan_with_all_deliverable_entrypoints_is_not_blocked(self) -> None:
        """When all entrypoints sit under skill units, skill-scoped clients execute normally."""
        for name in ("OpenCode", "Gemini CLI", "Muse", "Hermes"):
            plan = harness.plan_for(name)
            spec = plan.stage("invocation")
            with self.subTest(client=name):
                blocked = harness.stage_blocked_reason(CONFIG, plan, spec)
                self.assertIsNone(blocked)
                argvs = harness.stage_argvs(
                    CONFIG,
                    plan,
                    spec,
                    {
                        harness.PACKAGE: "/scratch/package",
                        harness.PYTHON: sys.executable,
                        harness.CLIENT_HOME: "/scratch/home",
                        harness.PLUGIN_NAME: CONFIG.name,
                    },
                )
                self.assertEqual(len(argvs), len(CONFIG.assessment.entrypoints))

    def test_agent_launcher_entrypoint_is_deliverable_to_every_skill_scoped_client(self) -> None:
        """agent-launcher's single entrypoint sits inside its single skill unit.

        The not-blocked shape this asserts is the UniFi geometry above; the
        mission-control blocked-in-advance test is the negative control this
        package must not resemble (its entrypoints sit at the package root).
        """
        al_config = port_config.load("agent-launcher", ROOT)
        for name in ("OpenCode", "Gemini CLI", "Muse", "Hermes"):
            plan = harness.plan_for(name)
            spec = plan.stage("invocation")
            with self.subTest(client=name):
                blocked = harness.stage_blocked_reason(al_config, plan, spec)
                self.assertIsNone(blocked)
                paths = harness.entrypoint_paths(al_config, plan)
                self.assertEqual(len(paths), len(al_config.assessment.entrypoints))
                for path, relative in zip(paths, al_config.assessment.entrypoints):
                    unit = relative.split("/", 2)[1]
                    self.assertEqual(path, f"{plan.invocation_root}/{unit}/{relative.split('/', 2)[2]}")

    def test_describe_plan_does_not_raise_for_agent_launcher_shape(self) -> None:
        """Plan print renders an unblocked invocation for every skill-scoped client.

        OpenAI Codex's load and invocation stay statically blocked by that
        client's own plan — it refuses the package root — which is a client
        property recorded in every matrix, not an agent-launcher geometry
        block; the four skill-scoped clients must show no invocation block.
        """
        al_config = port_config.load("agent-launcher", ROOT)
        plan_text = harness.describe_plan(al_config)
        self.assertIn("Assessment plan for agent-launcher", plan_text)
        for name in ("OpenCode", "Gemini CLI", "Muse", "Hermes"):
            with self.subTest(skill_scoped_client=name):
                section = plan_text.split(f"## {name}")[1].split("## ")[0]
                self.assertIn("invocation  <python>", section)
                self.assertNotIn("invocation  blocked in advance", section)
        codex = plan_text.split("## OpenAI Codex")[1].split("## ")[0]
        self.assertIn("blocked in advance", codex)

    def test_skill_scoped_plan_with_mixed_entrypoints_blocks_and_names_undeliverable_subset(self) -> None:
        """Mixed deliverable and undeliverable entrypoints block, naming only undeliverable."""
        variant = port_config.parse(
            {
                "schema_version": port_config.SCHEMA_VERSION,
                "package": "unifi",
                "package_root": "plugins/unifi",
                "source": {"repository": "https://example.com/u", "package_path": "plugins/unifi"},
                "custody": {},
                "assessment": {
                    "credential_prefixes": ["UNIFI_"],
                    "package_scripts": ["unifi_network_client.py", "discover.py"],
                    "mutating_operations": ["reboot"],
                    "entrypoints": [
                        "skills/unifi-network/scripts/unifi_network_client.py",
                        "scripts/discover.py",
                    ],
                    "skill_units": ["skills/unifi-network"],
                    "declared_none": [],
                },
            },
            root=ROOT,
            path=ROOT / "ports" / "unifi.json",
        )
        plan = harness.plan_for("OpenCode")
        spec = plan.stage("invocation")
        blocked = harness.stage_blocked_reason(variant, plan, spec)
        self.assertIsNotNone(blocked)
        self.assertIn("scripts/discover.py", blocked)
        self.assertNotIn("skills/unifi-network/scripts/unifi_network_client.py", blocked)
        outcome = harness.run_stage(
            plan,
            spec,
            variant,
            {
                harness.PACKAGE: "/scratch/package",
                harness.PYTHON: sys.executable,
                harness.CLIENT_HOME: "/scratch/home",
                harness.PLUGIN_NAME: variant.name,
            },
            dict(os.environ),
        )
        self.assertEqual(outcome.result, harness.BLOCKED)
        self.assertEqual(outcome.reason, blocked)

    def test_package_scoped_plan_with_package_root_entrypoints_resolves_unchanged(self) -> None:
        """Package-scoped clients resolve package-root entrypoints without blocking."""
        mc_config = port_config.load("mission-control", ROOT)
        for name in ("Claude Code", "Cursor Agent", "Qwen", "Grok", "Agy"):
            plan = harness.plan_for(name)
            spec = plan.stage("invocation")
            with self.subTest(client=name):
                blocked = harness.stage_blocked_reason(mc_config, plan, spec)
                self.assertIsNone(blocked)
                paths = harness.entrypoint_paths(mc_config, plan)
                self.assertEqual(len(paths), len(mc_config.assessment.entrypoints))
                for path, relative in zip(paths, mc_config.assessment.entrypoints):
                    self.assertEqual(path, f"{plan.invocation_root}/{relative}")

    def test_describe_plan_does_not_raise_for_mission_control_shape(self) -> None:
        """Plan print renders blocked invocation for skill-scoped and commands for package-scoped."""
        mc_config = port_config.load("mission-control", ROOT)
        plan_text = harness.describe_plan(mc_config)
        self.assertIn("Assessment plan for mission-control", plan_text)
        for name in ("OpenCode", "Gemini CLI", "Muse", "Hermes"):
            with self.subTest(skill_scoped_client=name):
                section = plan_text.split(f"## {name}")[1].split("## ")[0]
                self.assertIn("invocation  blocked in advance:", section)
                self.assertIn("scripts/sdlc_manager.py", section)
        for name in ("Claude Code", "Cursor Agent", "Qwen", "Grok", "Agy"):
            with self.subTest(package_scoped_client=name):
                section = plan_text.split(f"## {name}")[1].split("## ")[0]
                self.assertIn("invocation  <python>", section)
                self.assertIn("5 commands", section)


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

    def test_the_package_name_inside_a_path_survives_redaction(self) -> None:
        """Redacting the package name would describe a command nobody ran.

        Every entrypoint path contains the package name -- `unifi-network`,
        `unifi_network_client.py`. Substituting it back turned the recorded
        command into `skills/<plugin-name>-network/scripts/<plugin-name>_…`,
        which is not what ran and does not match the committed matrices. The
        name is already public in the record's own `$.package.name`; it is not
        a value redaction exists to hide.
        """
        values = {
            harness.PACKAGE: "/scratch/package",
            harness.CLIENT_HOME: "/scratch/home",
            harness.PYTHON: "/usr/bin/python3.12",
            harness.PLUGIN_NAME: CONFIG.name,
        }
        entrypoint = CONFIG.custody.entrypoint_transforms[0]
        command = f"/usr/bin/python3.12 /scratch/package/{entrypoint} --help"
        self.assertEqual(
            harness.redact(command, values),
            f"<python> <package>/{entrypoint} --help",
        )
        self.assertIn(CONFIG.name, harness.redact(command, values))

    def test_a_captured_install_id_is_still_redacted(self) -> None:
        """A client-generated id is machine-specific, so it does come back out."""
        values = {
            harness.PACKAGE: "/scratch/package",
            harness.PLUGIN_ID: "unifi-37c9f17b",
        }
        self.assertEqual(
            harness.redact("/scratch/home/.grok/installed-plugins/unifi-37c9f17b/x", values),
            "/scratch/home/.grok/installed-plugins/<plugin-id>/x",
        )

    def test_only_path_values_and_a_captured_id_are_redactable(self) -> None:
        values = {
            harness.PACKAGE: "/p",
            harness.CLIENT_HOME: "/h",
            harness.PYTHON: "/py",
            harness.PLUGIN_NAME: "unifi",
        }
        self.assertEqual(
            set(harness.redaction_values(values)),
            {harness.PACKAGE, harness.CLIENT_HOME, harness.PYTHON},
        )


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
        outcomes = {
            stage: harness.StageOutcome(stage, harness.EXECUTED, returncode=0)
            for stage in ("placement", "discovery", "load")
        }
        outcomes["invocation"] = harness.StageOutcome(
            "invocation", harness.EXECUTED, returncode=1
        )
        self.assertEqual(harness.propose_status(outcomes), "failed")

    def test_a_client_that_refused_every_stage_is_not_works_directly(self) -> None:
        """`executed` means a process completed, not that it accepted the package.

        Placement, discovery and load all returning non-zero is a client
        refusing the package at every step. Reading `executed` as success let
        that be proposed `works-directly` because the package's own `--help`
        happened to exit 0.
        """
        outcomes = {
            stage: harness.StageOutcome(stage, harness.EXECUTED, returncode=3)
            for stage in ("placement", "discovery", "load")
        }
        outcomes["invocation"] = harness.StageOutcome(
            "invocation", harness.EXECUTED, returncode=0
        )
        self.assertEqual(harness.propose_status(outcomes), "works-through-an-adapter")

    def test_a_failed_entrypoint_without_a_successful_placement_is_not_failed(self) -> None:
        """Nothing was established, so nothing about the package failed."""
        outcomes = {
            stage: harness.StageOutcome(stage, harness.EXECUTED, returncode=2)
            for stage in ccm.STAGES
        }
        self.assertEqual(harness.propose_status(outcomes), "works-through-an-adapter")

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

    def test_a_real_execute_run_produces_a_recordable_row(self) -> None:
        """One client, driven end to end against fake binaries.

        Every other test here drives a piece: one stage, one predicate, one
        plan-only record. Nothing drove `assess(execute=True)` all the way
        through with processes that actually run, and that gap is exactly where
        an unsubstituted invocation path survived -- every unit passed while the
        stage would have run a literal `<client-home>/…` path on every client.

        This runs placement, discovery, load, and invocation for one
        package-scoped client and asserts what lands in the record.
        """
        plan = harness.plan_for("Claude Code")
        scratch_bin = self.workspace / "bin"
        scratch_bin.mkdir(parents=True, exist_ok=True)
        write_executable(scratch_bin, plan.binary, 'echo "two skills"\nexit 0\n')

        path = os.pathsep.join([str(scratch_bin), os.environ.get("PATH", "")])
        with unittest.mock.patch.dict(os.environ, {"PATH": path}):
            record = harness.assess(
                CONFIG,
                python=sys.executable,
                execute=True,
                only=(plan.name,),
                workspace=self.workspace,
            )

        row = record["clients"][0]
        self.assertEqual(row["name"], plan.name)
        for stage in ccm.STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(row["stages"][stage]["result"], harness.EXECUTED)

        # The invocation really ran every shipped entrypoint on this
        # interpreter. What it must NOT assert is that they succeeded: the
        # entrypoints import requests and urllib3 at module scope, so their exit
        # status depends on whether the interpreter running these tests has
        # those packages. `tests/test_client_entrypoints.py` owns "do the
        # entrypoints work", with stubs that make it the same answer everywhere.
        # What this owns is that the stage ran them all and recorded each one.
        invocation = row["stages"]["invocation"]
        recorded_statuses = invocation["evidence"].split("exit status ")[1].split(".")[0]
        self.assertEqual(
            len(recorded_statuses.split(", ")),
            len(CONFIG.custody.entrypoint_transforms),
            invocation["evidence"],
        )
        # And the recorded command is the redacted form the matrices use.
        self.assertTrue(invocation["command"].startswith(f"{harness.PYTHON} {harness.PACKAGE}/"))
        self.assertIn(CONFIG.custody.entrypoint_transforms[0], invocation["command"])
        self.assertEqual(harness.unresolved_placeholders((invocation["command"],)), [
            harness.PACKAGE, harness.PYTHON
        ])
        self.assertEqual(ccm.check_public_evidence_rules(record), [])

    def test_the_record_states_whether_a_client_added_to_the_copy(self) -> None:
        """The copy is the tree a client could add a vendor artifact to.

        The source tree is the one nothing can reach, so fingerprinting only it
        proves nothing about what the clients did. The committed method
        fingerprints the handed-over copy before and after; this is that check,
        and the record states the observation rather than leaving it to memory.
        """
        record = self.plan_only_record()
        isolation = record["method"]["isolation"]
        self.assertIn("its own fresh copy", isolation)
        self.assertIn("no client added a vendor artifact", isolation)
        file_count, _ = ccm.package_fingerprint(CONFIG.package_directory)
        self.assertIn(f"{file_count} files", isolation)

    def test_each_client_is_handed_its_own_copy(self) -> None:
        """One shared copy let an early client change the bytes a later one saw.

        The record still bound itself to the original fingerprint, so ten rows
        could describe up to ten different trees under one digest.
        """
        self.plan_only_record()
        copies = sorted(p for p in self.workspace.glob("*/*/package") if p.is_dir())
        self.assertEqual(len(copies), len(harness.CLIENT_PLANS))
        digests = {ccm.package_fingerprint(copy)[1] for copy in copies}
        self.assertEqual(len(digests), 1, "the copies are not identical to begin with")
        for copy in copies:
            self.assertNotEqual(copy.resolve(), CONFIG.package_directory.resolve())

    def test_the_assessed_copy_is_a_copy_not_the_shipped_tree(self) -> None:
        """A client that installs in place must not be able to reach the source."""
        before = ccm.package_fingerprint(CONFIG.package_directory)
        self.plan_only_record()
        copies = [p for p in self.workspace.glob("*/*/package") if p.is_dir()]
        self.assertTrue(copies)
        for copy in copies:
            self.assertNotEqual(copy.resolve(), CONFIG.package_directory.resolve())
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

    def test_the_plan_shows_the_package_name_the_harness_already_knows(self) -> None:
        """The plan promises the exact argv, so a known value must not be a blank.

        `<plugin-name>` is the package's own name; the harness has it from the
        descriptor before anything runs. Leaving it as a placeholder makes the
        safety preview show an argv different from the one that will run, which
        is the one thing the preview exists to prevent. The only value still
        written as a placeholder is `<plugin-id>`, which the client generates at
        placement and nobody can know in advance.
        """
        plan = harness.describe_plan(CONFIG)
        naming = [line for line in plan.splitlines() if harness.PLUGIN_NAME in line]
        self.assertEqual(
            naming, [], f"the plan still shows {harness.PLUGIN_NAME}: {naming[:2]}"
        )
        self.assertTrue(
            any(f" {CONFIG.name}" in line for line in plan.splitlines()),
            f"the plan never names the package as {CONFIG.name!r}",
        )
        self.assertIn(
            harness.PLUGIN_ID, plan, "the client-generated id must stay a placeholder"
        )

    def test_an_executed_run_prints_a_transcript_path_that_exists(self) -> None:
        """The one path the operator is told to open must be the one written.

        The record ships with blank versions, reasons, and evidence on purpose,
        and the transcript is where an operator fills them from. The run
        directory repair moved the file into `<workspace>/run-NNN/` and left this
        message naming `<workspace>/`, so every executed assessment sent the
        operator to a file that did not exist -- and the only way to notice was
        to go looking. Asserted end to end through the real command line,
        because the defect was a disagreement between two call sites that each
        looked right on its own.
        """
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            binaries = base / "bin"
            write_executable(binaries, "codex", "exit 0\n")
            environment = dict(os.environ)
            environment["PATH"] = os.pathsep.join([str(binaries), environment.get("PATH", "")])
            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "assess_clients.py"),
                    "--package", "unifi", "--execute",
                    "--client", "OpenAI Codex",
                    "--workspace", str(base / "ws"),
                ],
                capture_output=True, text=True, timeout=300, env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
            announced = [
                line for line in completed.stdout.splitlines()
                if "The private transcript is at " in line
            ]
            self.assertEqual(len(announced), 1, completed.stdout[-1500:])
            tail = announced[0].split("The private transcript is at ", 1)[1]
            path = Path(tail.split(". It holds", 1)[0])
            self.assertTrue(
                path.is_file(),
                f"the command line announced {path}, which does not exist; "
                f"the workspace holds {sorted(p.name for p in (base / 'ws').rglob('*.json'))}",
            )

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
