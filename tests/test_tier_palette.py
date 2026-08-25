"""Target-owned minimal tests for the ported ``tier_palette`` module.

Upstream ships no standalone palette test; the AGENTS.md
changed-packaging-carries-tests rule wants the smallest proof that the ported
module loads — which here means its import-time read of the sibling
``models.json`` registry succeeds — and that the palette contract it publishes
holds. Standard library only, unittest-shaped, so the repository's
dependency-free baseline job runs them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parent.parent
FLEET_COMMONS_DIR = ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons"
MOD_PATH = FLEET_COMMONS_DIR / "tier_palette.py"
REGISTRY_PATH = FLEET_COMMONS_DIR / "models.json"

_LOADED: ModuleType | None = None


def palette() -> ModuleType:
    global _LOADED
    if _LOADED is None:
        spec = importlib.util.spec_from_file_location("portable_tier_palette", MOD_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Registration before exec mirrors the discovery-shim load contract the
        # portable slice follows; dataclasses-era interpreters also look the
        # module up in sys.modules while processing classes.
        sys.modules["portable_tier_palette"] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop("portable_tier_palette", None)
            raise
        _LOADED = module
    return _LOADED


def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


class PaletteLoadTests(unittest.TestCase):
    def test_module_loads_by_reading_its_sibling_registry(self) -> None:
        # Import IS the proof of the read: the ordered vocabularies are derived
        # at import time from models.json in the module's own directory.
        mod = palette()
        data = registry()

        self.assertEqual(list(mod.MODELS), list(data["models"]))
        self.assertEqual(list(mod.EFFORTS), list(data["efforts"]))
        self.assertTrue(mod.MODELS)
        self.assertTrue(mod.EFFORTS)


class PaletteContractTests(unittest.TestCase):
    def test_ranks_round_trip_and_reject_unknown_names(self) -> None:
        mod = palette()
        for index, model in enumerate(mod.MODELS):
            self.assertEqual(mod.model_rank(model), index)
        for index, effort in enumerate(mod.EFFORTS):
            self.assertEqual(mod.effort_rank(effort), index)

        with self.assertRaises(ValueError) as caught:
            mod.model_rank("opus-high")
        self.assertIn("opus-high", str(caught.exception))
        with self.assertRaises(ValueError):
            mod.effort_rank("ultra")

    def test_every_model_has_a_known_effort_ceiling(self) -> None:
        mod = palette()
        data = registry()
        for model in mod.MODELS:
            ceiling = mod.effort_ceiling(model)
            self.assertIn(ceiling, mod.EFFORTS)
            self.assertEqual(ceiling, data["models"][model]["effort_ceiling"])

    def test_ladder_ops_reason_in_strength(self) -> None:
        mod = palette()
        weakest, strongest_effort = mod.EFFORTS[0], mod.EFFORTS[-1]

        self.assertEqual(mod.escalate("effort", weakest), mod.EFFORTS[1])
        self.assertEqual(mod.escalate("effort", strongest_effort), strongest_effort)
        self.assertEqual(mod.downgrade("effort", weakest), weakest)
        self.assertEqual(
            mod.clamp("effort", strongest_effort, ceiling=mod.EFFORTS[1]),
            mod.EFFORTS[1],
        )
        self.assertEqual(mod.strongest("model", list(mod.MODELS)), mod.MODELS[0])

    def test_supports_effort_respects_the_ceiling(self) -> None:
        mod = palette()
        for model in mod.MODELS:
            ceiling = mod.effort_ceiling(model)
            self.assertTrue(mod.supports_effort(model, ceiling))
            above = [e for e in mod.EFFORTS if mod.effort_rank(e) > mod.effort_rank(ceiling)]
            for effort in above:
                self.assertFalse(mod.supports_effort(model, effort))


if __name__ == "__main__":
    unittest.main()
