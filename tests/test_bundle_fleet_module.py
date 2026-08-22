"""Tests for build-time Fleet Core bundling, provenance stamps, and staleness.

Written as unittest against temporary directories, matching
``tests/test_check_repo.py``, so the repository's dependency-free baseline job
runs them. Every digest assertion uses the same helpers as ``check_repo.py``,
so bundle stamps and provenance manifests share one digest convention.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bundle_fleet_module as bfm  # noqa: E402
import check_repo  # noqa: E402


PIN = {
    "source_repository": "https://example.invalid/example/example-plugins",
    "source_commit": "0" * 40,
    "source_version": "0.25.0",
}

RETRY_BODY = "def retry():\n    return None\n"
ALPHA_BODY = "ALPHA = 1\n"
BETA_BODY = "BETA = 1\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def make_repo(
    tmp: Path,
    *,
    modules: dict[str, str] | None = None,
    declaration_modules: list[dict[str, object]] | None = None,
    consumer: str = "unifi",
    plugin_manifest: bool = True,
    extra_declaration: dict[str, object] | None = None,
) -> Path:
    """Build a repository-shaped tree with portable Fleet Core and one consumer."""
    root = tmp / "repo"
    modules = modules if modules is not None else {"retry_backoff": RETRY_BODY}
    fleet = root / "plugins" / "fleet-core"
    for name, body in modules.items():
        write(fleet / "scripts" / "fleet_commons" / f"{name}.py", body)
    write(fleet / check_repo.PROVENANCE_FILENAME, json.dumps(PIN, indent=2) + "\n")
    write(
        fleet / "plugin.json",
        json.dumps(
            {
                "$schema": check_repo.PLUGIN_SCHEMA,
                "name": "fleet-core",
                "version": PIN["source_version"],
                "description": "Portable Fleet Core slice",
            }
        )
        + "\n",
    )

    declared = declaration_modules
    if declared is None:
        declared = [{"name": name} for name in modules]
    payload: dict[str, object] = {"schema_version": "1", "modules": declared}
    if extra_declaration:
        payload.update(extra_declaration)

    consumer_dir = root / "plugins" / consumer
    write(consumer_dir / bfm.DECLARATION_FILENAME, json.dumps(payload, indent=2) + "\n")
    if plugin_manifest:
        write(
            consumer_dir / "plugin.json",
            json.dumps(
                {
                    "$schema": check_repo.PLUGIN_SCHEMA,
                    "name": consumer,
                    "version": "0.1.0",
                    "description": "Example consumer",
                }
            )
            + "\n",
        )
    return root


def bundled_path(root: Path, name: str = "retry_backoff", consumer: str = "unifi") -> Path:
    return root / "plugins" / consumer / "scripts" / "_bundled" / f"{name}.py"


class GenerateTests(unittest.TestCase):
    def test_generated_output_digest_matches_content_with_stamp_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            written = bfm.generate_consumer(root, root / "plugins" / "unifi")
            bundled = bundled_path(root)
            self.assertEqual(written, [bundled])

            text = bundled.read_text(encoding="utf-8")
            self.assertEqual(
                check_repo.bundle_output_digest(text),
                check_repo.sha256_text(RETRY_BODY),
            )
            stamp_lines, payload = check_repo.split_bundle_stamp(text)
            self.assertIsNotNone(stamp_lines)
            self.assertEqual(payload, RETRY_BODY)
            stamp = check_repo.parse_bundle_stamp(stamp_lines or [])
            self.assertEqual(stamp[check_repo.BUNDLE_OUTPUT_DIGEST_FIELD], check_repo.sha256_text(RETRY_BODY))
            self.assertEqual(
                stamp[check_repo.BUNDLE_SOURCE_DIGEST_FIELD],
                check_repo.sha256_path(root / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "retry_backoff.py"),
            )
            self.assertEqual(stamp["source-version"], PIN["source_version"])
            self.assertEqual(stamp["source-commit"], PIN["source_commit"])

    def test_generate_is_idempotent_and_rewrites_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            consumer = root / "plugins" / "unifi"
            first = bfm.generate_consumer(root, consumer)
            bundled = bundled_path(root)
            self.assertEqual(first, [bundled])
            mtime = bundled.stat().st_mtime_ns
            before = tree_snapshot(root)

            second = bfm.generate_consumer(root, consumer)

            self.assertEqual(second, [])
            self.assertEqual(bundled.stat().st_mtime_ns, mtime)
            self.assertEqual(tree_snapshot(root), before)

    def test_absent_module_fails_loudly_and_writes_no_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(
                Path(tmp),
                modules={"retry_backoff": RETRY_BODY},
                declaration_modules=[{"name": "not_ported"}],
            )
            consumer = root / "plugins" / "unifi"
            with self.assertRaises(bfm.BundleError) as caught:
                bfm.generate_consumer(root, consumer)

            self.assertIn("not_ported", str(caught.exception))
            self.assertIn("absent from the portable Fleet Core", str(caught.exception))
            self.assertFalse(bundled_path(root, "not_ported").exists())
            bundled_root = consumer / "scripts" / "_bundled"
            self.assertFalse(bundled_root.exists())

    def test_declaration_of_two_modules_receives_exactly_those_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(
                Path(tmp),
                modules={
                    "alpha": ALPHA_BODY,
                    "beta": BETA_BODY,
                    "gamma": "GAMMA = 1\n",
                },
                declaration_modules=[{"name": "alpha"}, {"name": "beta"}],
            )
            bfm.generate_consumer(root, root / "plugins" / "unifi")
            bundled_dir = root / "plugins" / "unifi" / "scripts" / "_bundled"
            names = sorted(path.name for path in bundled_dir.iterdir() if path.is_file())
            self.assertEqual(names, ["alpha.py", "beta.py"])
            self.assertFalse((bundled_dir / "gamma.py").exists())

    def test_explicit_destinations_are_honoured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(
                Path(tmp),
                declaration_modules=[
                    {
                        "name": "retry_backoff",
                        "destinations": [
                            "skills/one/scripts/_bundled/retry_backoff.py",
                            "skills/two/scripts/_bundled/retry_backoff.py",
                        ],
                    }
                ],
            )
            bfm.generate_consumer(root, root / "plugins" / "unifi")
            first = (
                root
                / "plugins"
                / "unifi"
                / "skills"
                / "one"
                / "scripts"
                / "_bundled"
                / "retry_backoff.py"
            )
            second = (
                root
                / "plugins"
                / "unifi"
                / "skills"
                / "two"
                / "scripts"
                / "_bundled"
                / "retry_backoff.py"
            )
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertFalse(bundled_path(root).exists())
            self.assertEqual(
                check_repo.bundle_output_digest(first.read_text(encoding="utf-8")),
                check_repo.sha256_text(RETRY_BODY),
            )


class CheckModeTests(unittest.TestCase):
    def test_stale_source_is_not_reported_as_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            consumer = root / "plugins" / "unifi"
            bfm.generate_consumer(root, consumer)
            source = root / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "retry_backoff.py"
            source.write_text(RETRY_BODY + "# changed\n", encoding="utf-8")

            errors = bfm.check_consumer(root, consumer)

            self.assertEqual(len(errors), 1, msg=errors)
            self.assertIn("stale source", errors[0])
            self.assertIn("retry_backoff", errors[0])
            self.assertNotIn("tampering", errors[0])

    def test_hand_edit_is_reported_as_tampering_not_stale_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            consumer = root / "plugins" / "unifi"
            bfm.generate_consumer(root, consumer)
            bundled = bundled_path(root)
            bundled.write_text(
                bundled.read_text(encoding="utf-8").replace("return None", "return 1"),
                encoding="utf-8",
            )

            errors = bfm.check_consumer(root, consumer)

            self.assertEqual(len(errors), 1, msg=errors)
            self.assertIn("tampering", errors[0])
            self.assertNotIn("stale source", errors[0])

    def test_check_mode_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            consumer = root / "plugins" / "unifi"
            bfm.generate_consumer(root, consumer)
            source = root / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "retry_backoff.py"
            before = tree_snapshot(root)
            source.write_text(RETRY_BODY + "# changed\n", encoding="utf-8")
            before[str(source.relative_to(root))] = source.read_bytes()

            self.assertTrue(bfm.check_consumer(root, consumer))
            self.assertEqual(tree_snapshot(root), before)

    def test_check_passes_on_a_fresh_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            consumer = root / "plugins" / "unifi"
            bfm.generate_consumer(root, consumer)
            self.assertEqual(bfm.check_consumer(root, consumer), [])

    def test_schema_violation_is_rejected_naming_the_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp), extra_declaration={"dependencies": ["fleet-core"]})
            with self.assertRaises(bfm.BundleError) as caught:
                bfm.generate_consumer(root, root / "plugins" / "unifi")
            self.assertIn("dependencies", str(caught.exception))
            self.assertIn("unexpected field", str(caught.exception))


class CheckRepoIntegrationTests(unittest.TestCase):
    def test_generate_then_repository_bundle_checks_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            bfm.generate_consumer(root, root / "plugins" / "unifi")
            self.assertEqual(check_repo.check_bundled_files(root), [])
            self.assertEqual(check_repo.check_plugin_manifests(root), [])
            self.assertEqual(check_repo.check_fleet_bundle_declarations(root), [])

    def test_seeded_stale_source_fails_check_repo_with_stale_source_not_stale_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            bfm.generate_consumer(root, root / "plugins" / "unifi")
            source = root / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "retry_backoff.py"
            source.write_text(RETRY_BODY + "# changed\n", encoding="utf-8")

            errors = check_repo.check_bundled_files(root)

            self.assertEqual(len(errors), 1, msg=errors)
            self.assertIn("stale source", errors[0])
            self.assertIn("retry_backoff", errors[0])
            self.assertNotIn("stale bundle", errors[0])

    def test_seeded_hand_edit_fails_check_repo_with_stale_bundle_not_stale_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            bfm.generate_consumer(root, root / "plugins" / "unifi")
            bundled = bundled_path(root)
            bundled.write_text(
                bundled.read_text(encoding="utf-8").replace("return None", "return 1"),
                encoding="utf-8",
            )

            errors = check_repo.check_bundled_files(root)

            self.assertEqual(len(errors), 1, msg=errors)
            self.assertIn("stale bundle", errors[0])
            self.assertNotIn("stale source", errors[0])

    def test_declaration_without_a_plugin_manifest_is_not_a_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp), plugin_manifest=False)
            self.assertEqual(check_repo.check_plugin_manifests(root), [])
            self.assertEqual(check_repo.check_fleet_bundle_declarations(root), [])

    def test_live_retry_backoff_round_trip_preserves_source_digest(self) -> None:
        live_source = ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "retry_backoff.py"
        live_body = live_source.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp), modules={"retry_backoff": live_body})
            live_pin = json.loads(
                (ROOT / "plugins" / "fleet-core" / check_repo.PROVENANCE_FILENAME).read_text(
                    encoding="utf-8"
                )
            )
            write(
                root / "plugins" / "fleet-core" / check_repo.PROVENANCE_FILENAME,
                json.dumps(
                    {
                        "source_repository": live_pin["source_repository"],
                        "source_commit": live_pin["source_commit"],
                        "source_version": live_pin["source_version"],
                    },
                    indent=2,
                )
                + "\n",
            )
            bfm.generate_consumer(root, root / "plugins" / "unifi")
            bundled = bundled_path(root)
            stamp_lines, payload = check_repo.split_bundle_stamp(bundled.read_text(encoding="utf-8"))
            stamp = check_repo.parse_bundle_stamp(stamp_lines or [])
            self.assertEqual(payload, live_body)
            self.assertEqual(stamp[check_repo.BUNDLE_SOURCE_DIGEST_FIELD], check_repo.sha256_path(live_source))
            self.assertEqual(stamp["source-version"], live_pin["source_version"])
            self.assertEqual(stamp["source-commit"], live_pin["source_commit"])
            self.assertEqual(check_repo.check_bundled_files(root), [])


class CommandLineTests(unittest.TestCase):
    def run_main(self, arguments: list[str]) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = bfm.main(arguments)
        return code, out.getvalue() + err.getvalue()

    def test_generate_and_check_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            generate_args = ["--root", str(root)]
            self.assertEqual(self.run_main(generate_args)[0], 0)
            self.assertEqual(self.run_main([*generate_args, "--check"])[0], 0)

            bundled = bundled_path(root)
            bundled.write_text(
                bundled.read_text(encoding="utf-8").replace("return None", "return 1"),
                encoding="utf-8",
            )
            code, output = self.run_main([*generate_args, "--check"])

        self.assertEqual(code, 1)
        self.assertIn("tampering", output)

    def test_check_mode_cli_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            self.assertEqual(self.run_main(["--root", str(root)])[0], 0)
            before = tree_snapshot(root)
            source = root / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "retry_backoff.py"
            source.write_text(RETRY_BODY + "# changed\n", encoding="utf-8")
            before[str(source.relative_to(root))] = source.read_bytes()

            code, output = self.run_main(["--root", str(root), "--check"])

            self.assertEqual(code, 1)
            self.assertIn("stale source", output)
            self.assertEqual(tree_snapshot(root), before)

    def test_absent_module_exits_non_zero_rather_than_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(
                Path(tmp),
                modules={"retry_backoff": RETRY_BODY},
                declaration_modules=[{"name": "missing_mod"}],
            )
            code, output = self.run_main(["--root", str(root)])

        self.assertEqual(code, 1)
        self.assertIn("missing_mod", output)
        self.assertIn("absent from the portable Fleet Core", output)


class LiveTreeTests(unittest.TestCase):
    def test_live_declaration_is_discovered(self) -> None:
        consumers = bfm.discover_consumers(ROOT)
        names = {path.name for path in consumers}
        self.assertIn("unifi", names)

    def test_live_declaration_plans_retry_backoff_from_fleet_core(self) -> None:
        consumer = ROOT / "plugins" / "unifi"
        planned = bfm.plan_copies(ROOT, consumer)
        self.assertEqual([copy.name for copy in planned], ["retry_backoff"])
        self.assertTrue(planned[0].source.is_file())
        self.assertEqual(
            planned[0].source,
            ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "retry_backoff.py",
        )
        self.assertEqual(
            planned[0].destination,
            ROOT / "plugins" / "unifi" / "scripts" / "_bundled" / "retry_backoff.py",
        )


if __name__ == "__main__":
    unittest.main()
