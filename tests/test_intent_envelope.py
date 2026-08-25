"""Target-owned tests for the portable ``intent_envelope`` slice module.

These tests are target-owned, not a byte-port. Upstream's
``tests/test_intent_envelope.py`` cannot be ported as specified (KTD8 item 4
in ``docs/plans/2026-08-24-mission-control-port-run-plan.md``): it imports a
saga re-export at module level, loads team-execution, mission-control, and
shim surfaces during execution, exercises saga-only APIs, and carries a
repo-tree drift guard. The upstream suite stays upstream; this file proves the
transformed portable module instead, minimally:

* the transformed module imports cleanly;
* an envelope round-trips through the issue-carried block surface;
* ``tier_ceiling`` validation resolves through the sibling ``tier_palette``
  and its ``models.json`` registry;
* the deferred-name call path (``tier_resolver``) fails at call time naming
  the missing sibling path, never at import;
* the identical file works relocated (the ``_bundled/`` placement claim of
  transform ``resolve-fleet-commons-sibling`` v1).

Standard library only, unittest-shaped, so the repository's dependency-free
baseline job (``python3 -m unittest discover -s tests``) runs them.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parent.parent
FLEET_COMMONS_DIR = ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons"
MOD_PATH = FLEET_COMMONS_DIR / "intent_envelope.py"

_LOADED: ModuleType | None = None


def _load(path: Path = MOD_PATH, name: str = "portable_intent_envelope") -> ModuleType:
    """Load the module by path, registering it before exec.

    The registration is load-bearing on the current interpreter: ``dataclasses``
    looks the module up in ``sys.modules`` while processing a frozen dataclass.
    ``_load_sibling`` inside the module under test registers its siblings the
    same way, mirroring the upstream discovery shim's load contract.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def envelope_module() -> ModuleType:
    global _LOADED
    if _LOADED is None:
        _LOADED = _load()
    return _LOADED


class TransformImportTests(unittest.TestCase):
    def test_transformed_module_imports_cleanly(self) -> None:
        mod = envelope_module()
        self.assertEqual(mod.SCHEMA_VERSION, 1)
        # The transform's surface contract: both lazy legs exist, and the file
        # that satisfies the live leg sits in the module's own directory.
        self.assertTrue(callable(mod._tier_palette))
        self.assertTrue(callable(mod._tier_resolver))


class EnvelopeRoundTripTests(unittest.TestCase):
    def test_issue_block_round_trip(self) -> None:
        mod = envelope_module()
        envelope = mod.apply_answers(
            {"run_mode": "attended", "merge": "gate"},
            source="test",
            authored_by="tests/test_intent_envelope.py",
        )
        body = "preamble\n\n" + mod.render_issue_block(envelope) + "\ntail"
        parsed = mod.envelope_from_issue_body(body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed, envelope)
        self.assertEqual(parsed.to_dict(), envelope.to_dict())

    def test_dict_round_trip_preserves_meaning(self) -> None:
        mod = envelope_module()
        envelope = mod.apply_answers({"run_mode": "unattended"}, source="test")
        rebuilt = mod.IntentEnvelope.from_dict(envelope.to_dict())
        self.assertEqual(rebuilt.run_mode, "unattended")
        self.assertEqual(rebuilt.to_dict(), envelope.to_dict())


class TierCeilingValidationTests(unittest.TestCase):
    def test_tier_ceiling_resolves_through_sibling_palette(self) -> None:
        mod = envelope_module()
        palette = mod._tier_palette()
        self.assertEqual(
            Path(palette.__file__).resolve().parent,
            FLEET_COMMONS_DIR,
            "the palette must load from the envelope module's own directory",
        )
        self.assertTrue(palette.MODELS, "models.json must yield a non-empty ladder")

        envelope = mod.IntentEnvelope.from_dict(
            {
                "run_mode": "attended",
                "spend_envelope": {"tier_ceiling": palette.MODELS[0]},
            }
        )
        envelope.validate()
        self.assertEqual(envelope.spend_envelope.tier_ceiling, palette.MODELS[0])

    def test_off_ladder_ceiling_fails_closed(self) -> None:
        mod = envelope_module()
        with self.assertRaises(mod.IntentEnvelopeError) as caught:
            mod.IntentEnvelope.from_dict(
                {
                    "run_mode": "attended",
                    "spend_envelope": {"tier_ceiling": "not-a-model"},
                }
            )
        self.assertIn("not-a-model", str(caught.exception))


class DeferredNameTests(unittest.TestCase):
    def test_deferred_leg_fails_at_call_time_naming_the_sibling_path(self) -> None:
        mod = envelope_module()
        missing = MOD_PATH.parent / "tier_resolver.py"
        self.assertFalse(missing.is_file(), "tier_resolver stays deferred in this slice")
        with self.assertRaises(RuntimeError) as caught:
            mod._tier_resolver()
        message = str(caught.exception)
        self.assertIn("tier_resolver", message)
        self.assertIn(str(missing), message)

    def test_dormant_api_surfaces_the_same_failure(self) -> None:
        # ``recommend_tier``'s only dependency on the deferred leg is the
        # resolver load, so the public dormant API fails with the same shape.
        mod = envelope_module()
        with self.assertRaises(RuntimeError):
            mod.recommend_tier("work-shape", "attended")


class RelocatedCopyTests(unittest.TestCase):
    def test_identical_file_works_in_a_bundled_style_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Resolve up front: the module under test resolves its own paths,
            # and on macOS tempfile sits behind the /var -> /private/var link.
            dest = (Path(tmp) / "_bundled").resolve()
            dest.mkdir()
            for name in ("intent_envelope.py", "tier_palette.py", "models.json"):
                shutil.copy(FLEET_COMMONS_DIR / name, dest / name)

            mod = _load(dest / "intent_envelope.py", name="relocated_intent_envelope")
            envelope = mod.apply_answers({"run_mode": "unattended"})
            envelope.validate()

            palette = mod._tier_palette()
            self.assertTrue(palette.MODELS)
            self.assertEqual(Path(palette.__file__).resolve().parent, dest)

            with self.assertRaises(RuntimeError) as caught:
                mod._tier_resolver()
            self.assertIn(str(dest / "tier_resolver.py"), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
