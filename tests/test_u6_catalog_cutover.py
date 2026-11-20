"""Fail-first red tests for Unit U6 (issue #332): Wave 2 catalog retirement cutover."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]

RETIRED_PACKAGES = (
    "saga",
    "orchestrate",
    "agy",
    "codex",
    "house-style",
    "hermes-profile-evolution",
    "voice",
    "redis-channel",
)

PRUNED_FLEET_COMMONS = (
    "bridge_receipt.py",
    "output_attestation.py",
    "audit_store.py",
    "merge_guard.py",
    "effort_rider.py",
    "render_tier_table.py",
)

ACTIVE_FLEET_COMMONS = (
    "staffing.py",
    "tier_palette.py",
    "tier_resolver.py",
    "intent_envelope.py",
    "retry_backoff.py",
    "plugin_resolution.py",
    "typesafe_client.py",
    "langfuse_client.py",
)

FORMULA_SHA256 = "528540c6958cf628d5cdf3ea44dc7fff45c16862ad11412c56a945ceb7e4e839"
SCHEMA_SHA256 = "a505807b505fbb65f98c58f36375256dd99b7afb2e7f3346bac9f79a9b90acd8"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class U6CatalogCutoverTests(unittest.TestCase):
    def test_retired_catalog_trees_and_descriptors_absent(self) -> None:
        missing_removals: list[str] = []
        for pkg in RETIRED_PACKAGES:
            plugin_dir = REPO_ROOT / "plugins" / pkg
            port_file = REPO_ROOT / "ports" / f"{pkg}.json"
            if plugin_dir.exists():
                missing_removals.append(f"plugins/{pkg}")
            if port_file.exists():
                missing_removals.append(f"ports/{pkg}.json")
        if (REPO_ROOT / ".saga-profile.json").exists():
            missing_removals.append(".saga-profile.json")
        self.assertEqual(
            missing_removals,
            [],
            f"retired catalog trees/descriptors still exist: {missing_removals}",
        )

    def test_surviving_catalog_uncoupled_from_house_style_and_saga(self) -> None:
        preamble = (
            REPO_ROOT
            / "plugins"
            / "agent-launcher"
            / "roles"
            / "references"
            / "subagent-presentation-preamble.md"
        )
        self.assertTrue(preamble.is_file(), f"missing relocated preamble: {preamble}")

        launcher_refs: list[str] = []
        for path in sorted((REPO_ROOT / "plugins" / "agent-launcher").rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "plugins/house-style" in text:
                launcher_refs.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(
            launcher_refs,
            [],
            f"plugins/agent-launcher still references plugins/house-style: {launcher_refs}",
        )

        handoff_path = (
            REPO_ROOT / "plugins" / "mission-control" / "scripts" / "handoff_envelope.py"
        )
        self.assertTrue(
            handoff_path.is_file(),
            f"missing internalized mission-control handoff_envelope.py: {handoff_path}",
        )
        handoff_mod = _load_module("_u6_mc_handoff_envelope", handoff_path)
        for symbol in ("assess_source", "assess_declared", "READINESS_CONTRACT_MAJOR"):
            self.assertTrue(
                hasattr(handoff_mod, symbol),
                f"mission-control handoff_envelope.py missing export {symbol!r}",
            )

        mc_saga_refs: list[str] = []
        for py_path in sorted(
            (REPO_ROOT / "plugins" / "mission-control" / "scripts").rglob("*.py")
        ):
            text = py_path.read_text(encoding="utf-8")
            if 'resolve_plugin_root("saga"' in text or "resolve_plugin_root('saga'" in text or "plugins/saga" in text:
                mc_saga_refs.append(py_path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(
            mc_saga_refs,
            [],
            f"mission-control scripts still reference saga: {mc_saga_refs}",
        )

        for deploy_rel in (
            "plugins/deploy/skills/deploy-state/SKILL.md",
            "plugins/deploy/com.infiquetra.claude/commands/deploy.md",
        ):
            deploy_path = REPO_ROOT / deploy_rel
            self.assertTrue(deploy_path.is_file(), f"missing {deploy_rel}")
            deploy_text = deploy_path.read_text(encoding="utf-8")
            self.assertNotIn("plugins/saga/scripts/deploy_handoff.py", deploy_text, deploy_rel)
            self.assertNotIn("Accepting a saga handoff", deploy_text, deploy_rel)

    def test_orphaned_fleet_core_modules_pruned_and_active_modules_retained(self) -> None:
        commons = REPO_ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons"
        self.assertTrue(commons.is_dir(), f"missing {commons}")

        still_present = [
            name for name in PRUNED_FLEET_COMMONS if (commons / name).exists()
        ]
        self.assertEqual(
            still_present,
            [],
            f"orphaned fleet_commons modules still present: {still_present}",
        )

        missing_active = [
            name for name in ACTIVE_FLEET_COMMONS if not (commons / name).is_file()
        ]
        self.assertEqual(
            missing_active,
            [],
            f"active fleet_commons modules missing: {missing_active}",
        )
        self.assertTrue(
            list(commons.glob("jev_*.py")),
            "expected at least one jev_*.py module in fleet_commons",
        )

    def test_ci_and_repo_checks_aligned(self) -> None:
        check_repo = _load_module("_u6_check_repo", REPO_ROOT / "scripts" / "check_repo.py")
        semgrep_dirs = check_repo.SEMGREP_RULE_TEST_DIRECTORY
        tokens: set[str] = set()
        for entry in semgrep_dirs:
            if isinstance(entry, tuple):
                tokens.update(str(part) for part in entry)
            else:
                tokens.add(str(entry))
        self.assertIn("reviews", tokens)
        self.assertNotIn("saga", tokens)

        ci_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("for required in saga orchestrate", ci_text)

        reqs_text = (REPO_ROOT / "requirements-plugin-tests.txt").read_text(encoding="utf-8")
        req_names = {
            line.strip().split(">")[0].split("=")[0].split("<")[0].strip().lower()
            for line in reqs_text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertNotIn("mcp", req_names)
        self.assertNotIn("redis", req_names)

    def test_d2_reviews_formula_and_schema_byte_identity(self) -> None:
        formula_path = REPO_ROOT / "plugins" / "reviews" / "scripts" / "review_formula.py"
        schema_path = (
            REPO_ROOT / "plugins" / "reviews" / "references" / "review-records.schema.json"
        )
        self.assertEqual(
            hashlib.sha256(formula_path.read_bytes()).hexdigest(),
            FORMULA_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(schema_path.read_bytes()).hexdigest(),
            SCHEMA_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
