"""Tests for the voice policy store and instruction renderer (R25, R107; KTD5).

Covers:
- Storing and reading operator preferences and one-shot brief-next-turn override;
- Atomic one-shot arming and consuming;
- Corrupt and absent store states reported by name;
- Rendering instructions containing stated preferences verbatim without content alterations;
- CLI verbs 'voice policy show' and 'voice policy brief-next-turn'.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import voice_cli  # noqa: E402
import voice_policy  # noqa: E402


class VoicePolicyStoreTestCase(unittest.TestCase):
    """Common fixture: one fresh temporary state directory per test."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_dir = Path(temporary.name)
        environment = patch.dict(
            os.environ, {"VOICE_STATE_DIR": str(self.state_dir)}
        )
        environment.start()
        self.addCleanup(environment.stop)

    def policy_path(self) -> Path:
        return self.state_dir / voice_policy.POLICY_FILENAME


class PolicyStoreReadWriteTests(VoicePolicyStoreTestCase):
    """Store read, write, absent, and corrupt state behaviors."""

    def test_absent_store_reports_absent_and_returns_default(self) -> None:
        report = voice_policy.read_policy_report()
        self.assertEqual(report.status, voice_policy.STATUS_ABSENT)
        self.assertEqual(report.policy.preferences, ())
        self.assertFalse(report.policy.brief_next_turn)
        self.assertEqual(report.policy.tool_allowlist, ())

        policy = voice_policy.read_policy()
        self.assertEqual(policy, voice_policy.VoicePolicy())

    def test_corrupt_store_reports_corrupt_and_returns_default(self) -> None:
        cases = {
            "invalid json": "not json {",
            "not dict": json.dumps(["list", "of", "items"]),
            "preferences not list": json.dumps({"preferences": "single string"}),
            "preferences elements not strings": json.dumps({"preferences": [1, 2, 3]}),
            "brief not bool": json.dumps({"brief_next_turn": "true"}),
            "tool_allowlist not list": json.dumps({"tool_allowlist": 123}),
            "tool_allowlist elements not strings": json.dumps({"tool_allowlist": [None]}),
        }
        for name, contents in cases.items():
            with self.subTest(name=name):
                self.policy_path().write_text(contents, encoding="utf-8")
                report = voice_policy.read_policy_report()
                self.assertEqual(report.status, voice_policy.STATUS_CORRUPT)
                self.assertEqual(report.policy, voice_policy.VoicePolicy())
                self.assertEqual(voice_policy.read_policy(), voice_policy.VoicePolicy())

    def test_write_and_read_policy_round_trips(self) -> None:
        prefs = ["Be concise.", "No markdown."]
        tools = ["read_file", "grep_search"]
        written = voice_policy.write_policy(
            preferences=prefs,
            brief_next_turn=True,
            tool_allowlist=tools,
        )
        self.assertEqual(written.preferences, tuple(prefs))
        self.assertTrue(written.brief_next_turn)
        self.assertEqual(written.tool_allowlist, tuple(tools))

        report = voice_policy.read_policy_report()
        self.assertEqual(report.status, voice_policy.STATUS_OK)
        self.assertEqual(report.policy, written)


class BriefNextTurnOverrideTests(VoicePolicyStoreTestCase):
    """Arming and consuming the one-shot Brief Next Turn override."""

    def test_arm_and_consume_brief_next_turn(self) -> None:
        voice_policy.write_policy(preferences=["Speak warmly."])
        self.assertFalse(voice_policy.read_policy().brief_next_turn)

        armed = voice_policy.arm_brief_next_turn()
        self.assertTrue(armed.brief_next_turn)
        self.assertTrue(voice_policy.read_policy().brief_next_turn)

        # First consume consumes the armed override
        consumed = voice_policy.consume_brief_next_turn()
        self.assertTrue(consumed)
        self.assertFalse(voice_policy.read_policy().brief_next_turn)

        # Second consume reports unarmed
        consumed_again = voice_policy.consume_brief_next_turn()
        self.assertFalse(consumed_again)
        self.assertFalse(voice_policy.read_policy().brief_next_turn)

    def test_arm_when_absent_creates_file_and_arms(self) -> None:
        self.assertFalse(self.policy_path().exists())
        armed = voice_policy.arm_brief_next_turn()
        self.assertTrue(self.policy_path().exists())
        self.assertTrue(armed.brief_next_turn)


class RenderInstructionsTests(VoicePolicyStoreTestCase):
    """Instruction rendering contains preferences verbatim without content transforms."""

    def test_render_instructions_with_preferences_and_brief(self) -> None:
        prefs = ["Always speak casually.", "Avoid acronyms."]
        policy = voice_policy.VoicePolicy(
            preferences=tuple(prefs), brief_next_turn=True
        )

        instructions = voice_policy.render_instructions(policy)
        self.assertIn(voice_policy.BRIEF_INSTRUCTION, instructions)
        for pref in prefs:
            self.assertIn(pref, instructions)

    def test_render_instructions_without_brief(self) -> None:
        prefs = ["Speak clearly."]
        policy = voice_policy.VoicePolicy(
            preferences=tuple(prefs), brief_next_turn=False
        )

        instructions = voice_policy.render_instructions(policy)
        self.assertNotIn(voice_policy.BRIEF_INSTRUCTION, instructions)
        self.assertIn("Speak clearly.", instructions)

    def test_render_instructions_with_explicit_brief_flag(self) -> None:
        policy = voice_policy.VoicePolicy(preferences=("Preference 1",), brief_next_turn=False)
        rendered_brief = voice_policy.render_instructions(policy, brief=True)
        self.assertIn(voice_policy.BRIEF_INSTRUCTION, rendered_brief)

        rendered_not_brief = voice_policy.render_instructions(policy, brief=False)
        self.assertNotIn(voice_policy.BRIEF_INSTRUCTION, rendered_not_brief)


class VoiceCliPolicyTests(VoicePolicyStoreTestCase):
    """CLI policy verbs round-trip through voice_cli.main()."""

    def test_cli_policy_show_and_brief_next_turn(self) -> None:
        voice_policy.write_policy(preferences=["Keep it short."])

        # Show policy via CLI
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = voice_cli.main(["policy", "show"])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["preferences"], ["Keep it short."])
        self.assertFalse(output["brief_next_turn"])

        # Arm brief next turn via CLI
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = voice_cli.main(["policy", "brief-next-turn"])
        self.assertEqual(code, 0)
        self.assertIn("armed brief next turn override", stdout.getvalue())
        self.assertTrue(voice_policy.read_policy().brief_next_turn)

        # Verify show now reports armed brief_next_turn
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = voice_cli.main(["policy", "show"])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue())
        self.assertTrue(output["brief_next_turn"])


if __name__ == "__main__":
    unittest.main()
