"""Closed-schema tests for the Fleet Core build declaration.

The declaration cannot live in the Agent Plugins manifest: that schema is
closed and forbids assigning semantics to unrecognized top-level fields.
These tests pin that the declaration schema is itself closed, and that a
violation is reported by naming the offending field.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bundle_fleet_module as bfm  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "fleet-bundle.schema.json"
LIVE_DECLARATION = ROOT / "plugins" / "unifi" / "fleet-bundle.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def valid_declaration(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "schema_version": "1",
        "modules": [{"name": "retry_backoff"}],
    }
    payload.update(overrides)
    return payload


def object_nodes(schema: object, path: str = "$") -> list[tuple[str, dict]]:
    """Every object-typed node in the schema, so closed-ness is not a root-only check."""
    if not isinstance(schema, dict):
        return []
    found: list[tuple[str, dict]] = []
    if schema.get("type") == "object" or "properties" in schema:
        found.append((path, schema))
    if isinstance(schema.get("properties"), dict):
        for key, child in schema["properties"].items():
            found.extend(object_nodes(child, f"{path}.{key}"))
    items = schema.get("items")
    if isinstance(items, dict):
        found.extend(object_nodes(items, f"{path}.items"))
    return found


class SchemaContractTests(unittest.TestCase):
    def test_schema_file_is_readable_json_object(self) -> None:
        schema = load_schema()
        self.assertIsInstance(schema, dict)
        self.assertEqual(schema.get("type"), "object")

    def test_every_object_node_is_closed(self) -> None:
        schema = load_schema()
        nodes = object_nodes(schema)
        self.assertGreaterEqual(len(nodes), 2, "expected a root object and a module object")
        for path, node in nodes:
            with self.subTest(path=path):
                self.assertIs(
                    node.get("additionalProperties"),
                    False,
                    f"{path} must set additionalProperties to false so an unknown "
                    "field cannot acquire meaning by being ignored",
                )

    def test_required_fields_are_schema_version_and_modules(self) -> None:
        schema = load_schema()
        self.assertEqual(schema.get("required"), ["schema_version", "modules"])

    def test_schema_does_not_declare_an_agent_plugins_dependency_field(self) -> None:
        schema = load_schema()
        properties = schema.get("properties")
        self.assertIsInstance(properties, dict)
        forbidden = {"dependencies", "depends", "requires", "FLEET_COMMONS_ROOT"}
        self.assertEqual(set(properties) & forbidden, set())


class SchemaValidationTests(unittest.TestCase):
    def test_valid_declaration_passes(self) -> None:
        self.assertEqual(
            bfm.validate_declaration(valid_declaration(), origin="fleet-bundle.json"),
            [],
        )

    def test_optional_schema_identifier_is_accepted(self) -> None:
        payload = valid_declaration(
            **{"$schema": "../../schemas/fleet-bundle.schema.json"}
        )
        self.assertEqual(
            bfm.validate_declaration(payload, origin="fleet-bundle.json"),
            [],
        )

    def test_extra_top_level_field_is_rejected_by_name(self) -> None:
        errors = bfm.validate_declaration(
            valid_declaration(dependencies=["fleet-core"]),
            origin="fleet-bundle.json",
        )
        self.assertTrue(errors, "expected a closed-schema rejection")
        self.assertTrue(
            any("dependencies" in error for error in errors),
            msg=f"expected the offending field to be named, got {errors}",
        )
        self.assertTrue(
            any("unexpected field" in error for error in errors),
            msg=f"expected an unexpected-field error, got {errors}",
        )

    def test_extra_module_field_is_rejected_by_name(self) -> None:
        errors = bfm.validate_declaration(
            valid_declaration(modules=[{"name": "retry_backoff", "depends_on": "core"}]),
            origin="fleet-bundle.json",
        )
        self.assertTrue(any("depends_on" in error for error in errors), msg=errors)

    def test_missing_required_field_is_named(self) -> None:
        errors = bfm.validate_declaration({"modules": [{"name": "retry_backoff"}]}, origin="decl.json")
        self.assertTrue(any("schema_version" in error for error in errors), msg=errors)

    def test_unsupported_schema_version_is_rejected(self) -> None:
        errors = bfm.validate_declaration(valid_declaration(schema_version="2"), origin="decl.json")
        self.assertTrue(any("schema_version" in error for error in errors), msg=errors)
        self.assertTrue(any("'2'" in error for error in errors), msg=errors)

    def test_empty_modules_array_is_rejected(self) -> None:
        errors = bfm.validate_declaration(valid_declaration(modules=[]), origin="decl.json")
        self.assertTrue(errors)
        self.assertTrue(any("modules" in error for error in errors), msg=errors)

    def test_module_name_as_a_bare_string_is_rejected(self) -> None:
        errors = bfm.validate_declaration(
            valid_declaration(modules=["retry_backoff"]),
            origin="decl.json",
        )
        self.assertTrue(
            any("must be an object" in error for error in errors),
            msg=f"expected a type error naming modules[0], got {errors}",
        )
        self.assertTrue(any("modules[0]" in error for error in errors), msg=errors)


class LiveDeclarationTests(unittest.TestCase):
    def test_live_unifi_declaration_matches_the_schema(self) -> None:
        self.assertTrue(LIVE_DECLARATION.is_file(), "U3 owns plugins/unifi/fleet-bundle.json")
        errors = bfm.validate_declaration_file(
            LIVE_DECLARATION,
            origin="plugins/unifi/fleet-bundle.json",
        )
        self.assertEqual(errors, [])

    def test_live_declaration_points_at_the_schema_file(self) -> None:
        payload = json.loads(LIVE_DECLARATION.read_text(encoding="utf-8"))
        reference = payload.get("$schema")
        self.assertIsInstance(reference, str)
        resolved = (LIVE_DECLARATION.parent / reference).resolve()
        self.assertEqual(resolved, SCHEMA_PATH.resolve())

    def test_live_declaration_names_the_ported_retry_module(self) -> None:
        payload = json.loads(LIVE_DECLARATION.read_text(encoding="utf-8"))
        names = [entry["name"] for entry in payload["modules"]]
        self.assertEqual(names, ["retry_backoff"])


if __name__ == "__main__":
    unittest.main()
