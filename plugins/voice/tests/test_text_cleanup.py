"""Tests for the Markdown cleanup pass (R5, R6, R7; KTD10).

Pure text in, text out: no seams to inject, no external behaviour. The
scenarios are the plan's: formatting syntax does not survive, fenced
code-block contents are omitted entirely, inline code keeps its text, and
a long input comes back whole because no length gate exists anywhere in
the pass.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import text_cleanup  # noqa: E402


class FormattingSyntaxStrippingTests(unittest.TestCase):
    """Formatting markers are stripped so they are not spoken (R6)."""

    def test_emphasis_and_strong_markers_are_not_spoken(self) -> None:
        cleaned = text_cleanup.clean(
            "This is **important**, *very* important, __truly__, and _really_ so."
        )
        self.assertEqual(
            cleaned, "This is important, very important, truly, and really so."
        )
        self.assertNotIn("*", cleaned)
        self.assertNotIn("_", cleaned)

    def test_heading_markers_are_not_spoken(self) -> None:
        cleaned = text_cleanup.clean("# Status\n\nDone.\n\n## Details\n\nAll green.")
        self.assertEqual(cleaned, "Status\nDone.\nDetails\nAll green.")
        self.assertNotIn("#", cleaned)

    def test_link_syntax_keeps_the_text_and_drops_the_url(self) -> None:
        cleaned = text_cleanup.clean(
            "See [the runbook](https://docs.example.invalid/runbook) for steps."
        )
        self.assertEqual(cleaned, "See the runbook for steps.")
        self.assertNotIn("docs.example.invalid", cleaned)

    def test_list_and_blockquote_markers_are_not_spoken(self) -> None:
        cleaned = text_cleanup.clean(
            "- first item\n- second item\n1. ordered item\n> quoted line"
        )
        self.assertEqual(
            cleaned, "first item\nsecond item\nordered item\nquoted line"
        )

    def test_horizontal_rules_are_not_spoken(self) -> None:
        for rule in ("---", "***", "___"):
            with self.subTest(rule=rule):
                cleaned = text_cleanup.clean(f"Above\n\n{rule}\n\nBelow")
                self.assertEqual(cleaned, "Above\nBelow")

    def test_table_pipes_are_not_spoken(self) -> None:
        cleaned = text_cleanup.clean(
            "| name | value |\n| --- | --- |\n| retries | 3 |"
        )
        self.assertEqual(cleaned, "name value\nretries 3")
        self.assertNotIn("|", cleaned)

    def test_a_quoted_heading_is_stripped_from_the_outside_in(self) -> None:
        self.assertEqual(text_cleanup.clean("> # quoted heading"), "quoted heading")

    def test_underscore_identifiers_survive_the_pass(self) -> None:
        cleaned = text_cleanup.clean("The flag is voice_state_dir today.")
        self.assertEqual(cleaned, "The flag is voice_state_dir today.")


class FencedCodeOmissionTests(unittest.TestCase):
    """Fenced code-block contents never reach speech (R7)."""

    def test_backtick_fence_contents_are_omitted_entirely(self) -> None:
        cleaned = text_cleanup.clean(
            "Summary line.\n\n"
            "```python\n"
            "def hidden():\n"
            "    return 42\n"
            "```\n\n"
            "Closing line."
        )
        self.assertEqual(cleaned, "Summary line.\nClosing line.")
        self.assertNotIn("hidden", cleaned)
        self.assertNotIn("42", cleaned)
        self.assertNotIn("`", cleaned)

    def test_tilde_fence_contents_are_omitted_entirely(self) -> None:
        cleaned = text_cleanup.clean("Before\n~~~\nhidden block\n~~~\nAfter")
        self.assertEqual(cleaned, "Before\nAfter")
        self.assertNotIn("hidden", cleaned)

    def test_an_unclosed_fence_omits_everything_after_it(self) -> None:
        cleaned = text_cleanup.clean("Before\n```\nhidden forever")
        self.assertEqual(cleaned, "Before")

    def test_a_reply_that_is_only_a_fence_cleans_to_nothing(self) -> None:
        cleaned = text_cleanup.clean("```bash\nmake test\n```")
        self.assertEqual(cleaned, "")

    def test_a_fence_does_not_swallow_a_later_tilde_fence_marker(self) -> None:
        # Inside a backtick fence only a backtick line closes it: the tilde
        # line is fence content and is omitted with the rest.
        cleaned = text_cleanup.clean("Before\n```\n~~~\ncode\n```\nAfter")
        self.assertEqual(cleaned, "Before\nAfter")


class InlineCodeTests(unittest.TestCase):
    """Inline code keeps its span text and loses its backticks."""

    def test_inline_code_keeps_its_text_without_backticks(self) -> None:
        cleaned = text_cleanup.clean("Run `make test` first.")
        self.assertEqual(cleaned, "Run make test first.")
        self.assertNotIn("`", cleaned)

    def test_an_unpaired_backtick_does_not_survive(self) -> None:
        cleaned = text_cleanup.clean("A stray ` marker.")
        self.assertNotIn("`", cleaned)
        self.assertIn("A stray", cleaned)


class NoLengthGateTests(unittest.TestCase):
    """A long input is returned whole: no gate of any kind (R5)."""

    def test_a_long_input_is_returned_whole(self) -> None:
        text = "\n".join(f"word{index} stays whole." for index in range(5000))
        cleaned = text_cleanup.clean(text)
        self.assertEqual(cleaned, text)
        self.assertGreater(len(cleaned), 100_000)

    def test_a_long_fenced_block_is_omitted_whole(self) -> None:
        filler = "\n".join(f"hidden {index}" for index in range(5000))
        cleaned = text_cleanup.clean(f"Before\n```\n{filler}\n```\nAfter")
        self.assertEqual(cleaned, "Before\nAfter")


class EdgeCaseTests(unittest.TestCase):
    """The small edges around the cleaned path."""

    def test_empty_input_cleans_to_empty_output(self) -> None:
        self.assertEqual(text_cleanup.clean(""), "")

    def test_plain_text_is_returned_unchanged(self) -> None:
        text = "The build passed. Nothing else to say."
        self.assertEqual(text_cleanup.clean(text), text)


class IntegratedResponseTests(unittest.TestCase):
    """A realistic completed response, cleaned end to end."""

    def test_a_mixed_response_is_cleaned_for_speech(self) -> None:
        response = (
            "## Build result\n"
            "\n"
            "The build **passed** with `0` errors.\n"
            "\n"
            "```bash\n"
            "python3 -m unittest discover -s tests\n"
            "```\n"
            "\n"
            "See [the CI log](https://ci.example.invalid/run/42) for details.\n"
            "\n"
            "- lint clean\n"
            "- tests green\n"
            "\n"
            "> Next: deploy on your approval.\n"
        )
        expected = (
            "Build result\n"
            "The build passed with 0 errors.\n"
            "See the CI log for details.\n"
            "lint clean\n"
            "tests green\n"
            "Next: deploy on your approval."
        )
        self.assertEqual(text_cleanup.clean(response), expected)


if __name__ == "__main__":
    unittest.main()
