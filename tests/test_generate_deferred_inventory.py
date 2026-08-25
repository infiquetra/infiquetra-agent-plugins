"""Tests for the portable Fleet Core deferred-module inventory generator.

Written as unittest against temporary directories, matching
``tests/test_check_repo.py``, so the repository's dependency-free baseline job
runs them. Every assertion about the inventory is a set difference computed
independently in the test rather than a literal count, because a literal count
is exactly what the generator exists to stop anyone from typing.
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

import generate_deferred_inventory as gdi  # noqa: E402


LIVE_PACKAGE = ROOT / "plugins" / "fleet-core"

PIN = {
    "source_repository": "https://example.invalid/example/example-plugins",
    "source_commit": "0000000000000000000000000000000000000000",
    "source_version": "0.1.0",
}

UPSTREAM_MODULES = ("alpha.py", "beta.py", "gamma.py", "retry_backoff.py")
UPSTREAM_DATA = ("weights.json", "policy.json")
PORTED = ("retry_backoff.py",)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_source(
    root: Path,
    *,
    modules: tuple[str, ...] = UPSTREAM_MODULES,
    shim: bool = True,
) -> Path:
    """Build a fake upstream Fleet Core package root."""
    package = root / "upstream"
    for name in modules:
        write(package / "scripts" / "fleet_commons" / name, f"# {name}\n")
    for name in UPSTREAM_DATA:
        write(package / "scripts" / "fleet_commons" / name, "{}\n")
    if shim:
        write(package / "scripts" / gdi.SHIM_FILENAME, "# shim\n")
    return package


def make_package(
    root: Path,
    *,
    ported: tuple[str, ...] = PORTED,
    pin: dict[str, str] | None = None,
) -> Path:
    """Build a fake portable package root with a provenance manifest."""
    package = root / "portable"
    for name in ported:
        write(package / "scripts" / "fleet_commons" / name, f"# {name}\n")
    write(
        package / gdi.PROVENANCE_FILENAME,
        json.dumps(dict(pin or PIN), indent=2) + "\n",
    )
    return package


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class InventoryTests(unittest.TestCase):
    def test_counting_basis_covers_the_package_and_the_shim_beside_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            names = {item.name for item in gdi.inventory(source)}

        expected = {f"fleet_commons/{name}" for name in UPSTREAM_MODULES + UPSTREAM_DATA}
        expected.add(gdi.SHIM_FILENAME)
        self.assertEqual(names, expected)

    def test_python_modules_and_data_files_are_classified_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            kinds = {item.name: item.kind for item in gdi.inventory(source)}

        self.assertEqual(kinds["fleet_commons/alpha.py"], gdi.PYTHON_MODULE)
        self.assertEqual(kinds["fleet_commons/weights.json"], gdi.DATA_FILE)
        self.assertEqual(kinds[gdi.SHIM_FILENAME], gdi.PYTHON_MODULE)

    def test_missing_upstream_package_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "nothing-here"
            empty.mkdir()
            with self.assertRaises(gdi.InventoryError) as caught:
                gdi.inventory(empty)

        self.assertIn(gdi.PACKAGE_DIRNAME, str(caught.exception))

    def test_pycache_is_not_inventoried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            write(source / "scripts" / "fleet_commons" / "__pycache__" / "alpha.pyc", "x")
            names = {item.name for item in gdi.inventory(source)}

        self.assertFalse([name for name in names if "__pycache__" in name])


class SetDifferenceTests(unittest.TestCase):
    def test_deferred_is_the_set_difference_not_a_literal_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            upstream = gdi.inventory(source)
            ported = gdi.inventory(package)
            deferred = {item.name for item in gdi.deferred_items(upstream, ported)}

        expected = {item.name for item in upstream} - {item.name for item in ported}
        self.assertEqual(deferred, expected)
        self.assertNotIn("fleet_commons/retry_backoff.py", deferred)

    def test_ported_item_absent_upstream_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp), ported=("retry_backoff.py", "invented.py"))
            unknown = gdi.unknown_ported_items(gdi.inventory(source), gdi.inventory(package))
            self.assertEqual([item.name for item in unknown], ["fleet_commons/invented.py"])

            with self.assertRaises(gdi.InventoryError) as caught:
                gdi.generate(package, source, package / gdi.DEFERRED_FILENAME)

        self.assertIn("invented.py", str(caught.exception))


class GenerateTests(unittest.TestCase):
    def test_generated_document_names_every_deferred_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            output = package / gdi.DEFERRED_FILENAME
            text = gdi.generate(package, source, output)

            deferred = gdi.deferred_items(gdi.inventory(source), gdi.inventory(package))

        for item in deferred:
            self.assertIn(f"`{item.name}`", text)
        recorded = {item.name for item in gdi.parse_rendered_items(text, gdi.DEFERRED_HEADING)}
        self.assertEqual(recorded, {item.name for item in deferred})

    def test_generation_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            output = package / gdi.DEFERRED_FILENAME
            first = gdi.generate(package, source, output)
            second = gdi.generate(package, source, output)

        self.assertEqual(first, second)

    def test_generated_document_restates_the_pin_from_the_provenance_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            text = gdi.generate(package, source, package / gdi.DEFERRED_FILENAME)

        self.assertIn(PIN["source_commit"], text)
        self.assertIn(PIN["source_version"], text)

    def test_missing_provenance_manifest_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            (package / gdi.PROVENANCE_FILENAME).unlink()
            with self.assertRaises(gdi.InventoryError) as caught:
                gdi.generate(package, source, package / gdi.DEFERRED_FILENAME)

        self.assertIn(gdi.PROVENANCE_FILENAME, str(caught.exception))


class CheckAgainstSourceTests(unittest.TestCase):
    def test_a_module_added_upstream_fails_the_check_until_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            output = package / gdi.DEFERRED_FILENAME
            gdi.generate(package, source, output)
            self.assertEqual(gdi.check_against_source(package, source, output), [])

            write(source / "scripts" / "fleet_commons" / "newcomer.py", "# newcomer\n")
            errors = gdi.check_against_source(package, source, output)
            self.assertTrue(errors)
            self.assertTrue(
                any("fleet_commons/newcomer.py" in error for error in errors),
                msg=f"expected the added module to be named, got {errors}",
            )

            gdi.generate(package, source, output)
            self.assertEqual(gdi.check_against_source(package, source, output), [])

    def test_a_module_removed_upstream_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            output = package / gdi.DEFERRED_FILENAME
            gdi.generate(package, source, output)

            (source / "scripts" / "fleet_commons" / "beta.py").unlink()
            errors = gdi.check_against_source(package, source, output)

        self.assertTrue(
            any("fleet_commons/beta.py" in error for error in errors),
            msg=f"expected the removed module to be named, got {errors}",
        )

    def test_missing_inventory_document_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            errors = gdi.check_against_source(package, source, package / gdi.DEFERRED_FILENAME)

        self.assertEqual(len(errors), 1)
        self.assertIn(gdi.DEFERRED_FILENAME, errors[0])

    def test_check_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            package = make_package(root)
            output = package / gdi.DEFERRED_FILENAME
            gdi.generate(package, source, output)

            # Seed a drift the check must notice, and record it as expected state.
            # Anything else that differs afterwards is the check having written.
            newcomer = source / "scripts" / "fleet_commons" / "newcomer.py"
            before = tree_snapshot(root)
            write(newcomer, "# newcomer\n")
            before[str(newcomer.relative_to(root))] = b"# newcomer\n"

            self.assertTrue(gdi.check_against_source(package, source, output))
            self.assertEqual(tree_snapshot(root), before)
            self.assertEqual(gdi.self_check(package, output), [])
            self.assertEqual(tree_snapshot(root), before)


class SelfCheckTests(unittest.TestCase):
    def test_self_check_passes_on_a_freshly_generated_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            output = package / gdi.DEFERRED_FILENAME
            gdi.generate(package, source, output)
            self.assertEqual(gdi.self_check(package, output), [])

    def test_porting_a_module_without_regenerating_fails_the_self_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            output = package / gdi.DEFERRED_FILENAME
            gdi.generate(package, source, output)

            write(package / "scripts" / "fleet_commons" / "beta.py", "# beta\n")
            errors = gdi.self_check(package, output)

        self.assertTrue(
            any("fleet_commons/beta.py" in error for error in errors),
            msg=f"expected the newly ported module to be named, got {errors}",
        )

    def test_dropping_a_ported_module_fails_the_self_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            output = package / gdi.DEFERRED_FILENAME
            gdi.generate(package, source, output)

            (package / "scripts" / "fleet_commons" / "retry_backoff.py").unlink()
            errors = gdi.self_check(package, output)

        self.assertTrue(
            any("retry_backoff.py" in error for error in errors),
            msg=f"expected the dropped module to be named, got {errors}",
        )


class CommandLineTests(unittest.TestCase):
    def run_main(self, arguments: list[str]) -> tuple[int, str]:
        """Invoke the command line, capturing its streams so test output stays readable."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gdi.main(arguments)
        return code, out.getvalue() + err.getvalue()

    def test_generate_without_a_source_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = make_package(Path(tmp))
            with self.assertRaises(SystemExit) as caught:
                self.run_main(["--package", str(package)])

        self.assertNotEqual(caught.exception.code, 0)

    def test_exit_codes_track_the_check_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(Path(tmp))
            package = make_package(Path(tmp))
            arguments = ["--package", str(package), "--source", str(source)]
            self.assertEqual(self.run_main(arguments)[0], 0)
            self.assertEqual(self.run_main([*arguments, "--check"])[0], 0)

            write(source / "scripts" / "fleet_commons" / "newcomer.py", "# newcomer\n")
            code, output = self.run_main([*arguments, "--check"])

        self.assertEqual(code, 1)
        self.assertIn("fleet_commons/newcomer.py", output)

    def test_unreadable_source_exits_non_zero_rather_than_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = make_package(Path(tmp))
            missing = Path(tmp) / "absent"
            code, output = self.run_main(["--package", str(package), "--source", str(missing)])

        self.assertEqual(code, 1)
        self.assertIn(gdi.PACKAGE_DIRNAME, output)


class LivePackageTests(unittest.TestCase):
    """Checks against the real portable Fleet Core package in this repository.

    These close a gap no other file in this unit can close. ``check_repo.py``
    verifies digests for paths inside a package, but the ported test suite lives
    at the repository root and the recorded inventory is a generated document,
    so neither is covered there.
    """

    def test_live_inventory_is_self_consistent(self) -> None:
        self.assertEqual(gdi.self_check(LIVE_PACKAGE, LIVE_PACKAGE / gdi.DEFERRED_FILENAME), [])

    def test_live_inventory_records_the_pinned_source(self) -> None:
        pin = gdi.read_pin(LIVE_PACKAGE)
        text = (LIVE_PACKAGE / gdi.DEFERRED_FILENAME).read_text(encoding="utf-8")
        for value in pin.values():
            self.assertIn(value, text)

    def test_live_inventory_does_not_name_the_ported_module_as_deferred(self) -> None:
        text = (LIVE_PACKAGE / gdi.DEFERRED_FILENAME).read_text(encoding="utf-8")
        deferred = {item.name for item in gdi.parse_rendered_items(text, gdi.DEFERRED_HEADING)}
        ported = {item.name for item in gdi.parse_rendered_items(text, gdi.PORTED_HEADING)}

        self.assertEqual(
            ported,
            {
                "fleet_commons/intent_envelope.py",
                "fleet_commons/models.json",
                "fleet_commons/retry_backoff.py",
                "fleet_commons/tier_palette.py",
            },
        )
        self.assertEqual(deferred & ported, set())
        self.assertIn(gdi.SHIM_FILENAME, deferred)

    def test_recorded_derived_file_digests_match_the_tree(self) -> None:
        import hashlib

        payload = json.loads((LIVE_PACKAGE / gdi.PROVENANCE_FILENAME).read_text(encoding="utf-8"))
        derived = payload["derived_files"]
        self.assertTrue(derived, "expected at least one recorded derived file")

        for entry in derived:
            path = ROOT / entry["path"]
            with self.subTest(path=entry["path"]):
                self.assertTrue(path.is_file(), f"recorded derived file is missing: {path}")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(
                    digest,
                    entry["sha256"],
                    f"{entry['path']} no longer matches the digest recorded in "
                    f"{gdi.PROVENANCE_FILENAME}; regenerate the transform or update the record",
                )

    def test_release_surface_paths_all_exist(self) -> None:
        payload = json.loads((LIVE_PACKAGE / gdi.PROVENANCE_FILENAME).read_text(encoding="utf-8"))
        for path in payload["release_surface"]["items"]:
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file(), f"release surface path is missing: {path}")


if __name__ == "__main__":
    unittest.main()
