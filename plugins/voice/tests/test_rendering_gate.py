"""Tests for the plain-spoken-text rendering gate (R121, R20; KTD1; AE26).

These tests hold the gate to its self-contained normative grammar:
- Every row of the normative class table has at least one rejecting scenario;
- Every line-anchored class has a 3-space-indented variant;
- Every class has a rule-not-spelling scenario;
- Every stated non-class has an accepting scenario;
- Precedence: fenced code block takes precedence over markdown formatting;
- R20 public surface guard: no text transformation function is exported.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import rendering_gate  # noqa: E402


class AE26CoreGateTests(unittest.TestCase):
    """The AE26 core: gate rejects fences and markdown, naming reason, class, line."""

    def test_gate_rejects_fenced_code_block(self) -> None:
        text = "Here is the plan:\n```python\nprint('hello')\n```"
        verdict = rendering_gate.evaluate(text)
        self.assertFalse(verdict.is_plain)
        self.assertEqual(verdict.verdict, rendering_gate.VERDICT_REJECTED)
        self.assertEqual(verdict.reason, rendering_gate.REASON_FENCED_CODE_BLOCK)
        self.assertIsNotNone(verdict.detail)
        self.assertIn(rendering_gate.CLASS_FENCED_CODE_BLOCK, verdict.detected_classes)
        self.assertEqual(verdict.first_offending_line, 2)

    def test_gate_rejects_markdown_emphasis(self) -> None:
        text = "This is *important* and needs review."
        verdict = rendering_gate.evaluate(text)
        self.assertFalse(verdict.is_plain)
        self.assertEqual(verdict.verdict, rendering_gate.VERDICT_REJECTED)
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIsNotNone(verdict.detail)
        self.assertIn(rendering_gate.CLASS_EMPHASIS_STRONG, verdict.detected_classes)
        self.assertEqual(verdict.first_offending_line, 1)

    def test_gate_accepts_plain_spoken_text(self) -> None:
        text = "The unit tests pass and the adapter is ready for review."
        verdict = rendering_gate.evaluate(text)
        self.assertTrue(verdict.is_plain)
        self.assertEqual(verdict.verdict, rendering_gate.VERDICT_PLAIN)
        self.assertIsNone(verdict.reason)
        self.assertIsNone(verdict.detail)
        self.assertEqual(verdict.detected_classes, [])
        self.assertIsNone(verdict.first_offending_line)


class ClassTableRejectingTests(unittest.TestCase):
    """Every row of the class table has at least one rejecting scenario."""

    def test_fenced_code_block_backticks(self) -> None:
        verdict = rendering_gate.evaluate("```\ncode\n```")
        self.assertEqual(verdict.reason, rendering_gate.REASON_FENCED_CODE_BLOCK)
        self.assertIn(rendering_gate.CLASS_FENCED_CODE_BLOCK, verdict.detected_classes)

    def test_indented_code_block(self) -> None:
        verdict = rendering_gate.evaluate("    def foo(): return 42")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_INDENTED_CODE_BLOCK, verdict.detected_classes)
        self.assertEqual(verdict.first_offending_line, 1)

    def test_atx_heading(self) -> None:
        verdict = rendering_gate.evaluate("# Heading 1")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_ATX_HEADING, verdict.detected_classes)

    def test_setext_heading(self) -> None:
        verdict = rendering_gate.evaluate("Section Title\n===")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_SETEXT_HEADING, verdict.detected_classes)

    def test_list_marker(self) -> None:
        verdict = rendering_gate.evaluate("- First item\n- Second item")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_LIST_MARKER, verdict.detected_classes)

    def test_blockquote(self) -> None:
        verdict = rendering_gate.evaluate("> This is quoted text.")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_BLOCKQUOTE, verdict.detected_classes)

    def test_horizontal_rule(self) -> None:
        verdict = rendering_gate.evaluate("---")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_HORIZONTAL_RULE, verdict.detected_classes)

    def test_table_pipe_row(self) -> None:
        verdict = rendering_gate.evaluate("| col1 | col2 |\n| --- | --- |")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_TABLE_PIPE_ROW, verdict.detected_classes)

    def test_link_reference_definition(self) -> None:
        verdict = rendering_gate.evaluate("[homepage]: https://example.com")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(
            rendering_gate.CLASS_LINK_REFERENCE_DEFINITION, verdict.detected_classes
        )

    def test_hard_line_break_trailing_spaces(self) -> None:
        verdict = rendering_gate.evaluate("First line with hard break  \nSecond line")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_HARD_LINE_BREAK, verdict.detected_classes)
        self.assertEqual(verdict.first_offending_line, 1)

    def test_hard_line_break_backslash(self) -> None:
        verdict = rendering_gate.evaluate("First line with backslash\\\nSecond line")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_HARD_LINE_BREAK, verdict.detected_classes)
        self.assertEqual(verdict.first_offending_line, 1)

    def test_raw_html_tag_and_comment(self) -> None:
        verdict1 = rendering_gate.evaluate("Please see <div class='highlight'>text</div>")
        self.assertEqual(verdict1.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_RAW_HTML, verdict1.detected_classes)

        verdict2 = rendering_gate.evaluate("Secret <!-- comment --> note")
        self.assertEqual(verdict2.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_RAW_HTML, verdict2.detected_classes)

    def test_backslash_escape(self) -> None:
        verdict = rendering_gate.evaluate("An escaped asterisk \\* looks like this")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_BACKSLASH_ESCAPE, verdict.detected_classes)

    def test_emphasis_strong(self) -> None:
        verdict = rendering_gate.evaluate("Some **bold** text here")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_EMPHASIS_STRONG, verdict.detected_classes)

    def test_strikethrough(self) -> None:
        verdict = rendering_gate.evaluate("Some ~~deleted~~ text here")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_STRIKETHROUGH, verdict.detected_classes)

    def test_inline_code_span(self) -> None:
        verdict = rendering_gate.evaluate("Run `pytest` to test")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_INLINE_CODE_SPAN, verdict.detected_classes)

    def test_inline_link_image(self) -> None:
        verdict = rendering_gate.evaluate("Click [here](https://example.com) for info")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_INLINE_LINK_IMAGE, verdict.detected_classes)

    def test_reference_link(self) -> None:
        verdict = rendering_gate.evaluate("See [documentation][ref] for details")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_REFERENCE_LINK, verdict.detected_classes)

    def test_autolink(self) -> None:
        verdict = rendering_gate.evaluate("Check <https://example.com> now")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_AUTOLINK, verdict.detected_classes)


class LineAnchoredThreeSpaceIndentedTests(unittest.TestCase):
    """Every line-anchored class has a 3-space-indented variant plus seam check."""

    def test_three_space_indented_list_marker(self) -> None:
        verdict = rendering_gate.evaluate("   - indented bullet")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_LIST_MARKER, verdict.detected_classes)

    def test_three_space_indented_atx_heading(self) -> None:
        verdict = rendering_gate.evaluate("   ## Indented Heading")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_ATX_HEADING, verdict.detected_classes)

    def test_three_space_indented_blockquote(self) -> None:
        verdict = rendering_gate.evaluate("   > indented quote")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_BLOCKQUOTE, verdict.detected_classes)

    def test_three_space_indented_fence(self) -> None:
        verdict = rendering_gate.evaluate("   ```bash\necho 1\n   ```")
        self.assertEqual(verdict.reason, rendering_gate.REASON_FENCED_CODE_BLOCK)
        self.assertIn(rendering_gate.CLASS_FENCED_CODE_BLOCK, verdict.detected_classes)

    def test_three_space_indented_horizontal_rule(self) -> None:
        verdict = rendering_gate.evaluate("   ---")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_HORIZONTAL_RULE, verdict.detected_classes)

    def test_three_space_indented_setext_underline(self) -> None:
        verdict = rendering_gate.evaluate("Header\n   ===")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(rendering_gate.CLASS_SETEXT_HEADING, verdict.detected_classes)

    def test_three_space_indented_link_ref_def(self) -> None:
        verdict = rendering_gate.evaluate("   [ref]: https://example.com")
        self.assertEqual(verdict.reason, rendering_gate.REASON_MARKDOWN_FORMATTING)
        self.assertIn(
            rendering_gate.CLASS_LINK_REFERENCE_DEFINITION, verdict.detected_classes
        )

    def test_three_space_vs_four_space_seam_scenario(self) -> None:
        three_spaces = "   - item"
        verdict3 = rendering_gate.evaluate(three_spaces)
        self.assertIn(rendering_gate.CLASS_LIST_MARKER, verdict3.detected_classes)
        self.assertNotIn(rendering_gate.CLASS_INDENTED_CODE_BLOCK, verdict3.detected_classes)

        four_spaces = "    - item"
        verdict4 = rendering_gate.evaluate(four_spaces)
        self.assertIn(rendering_gate.CLASS_INDENTED_CODE_BLOCK, verdict4.detected_classes)


class RuleNotSpellingTests(unittest.TestCase):
    """Every rejecting class has a rule-not-spelling scenario."""

    def test_ordered_list_marker_non_one(self) -> None:
        verdict = rendering_gate.evaluate("7. Seventh item")
        self.assertIn(rendering_gate.CLASS_LIST_MARKER, verdict.detected_classes)

    def test_multi_digit_ordered_marker_parenthesis(self) -> None:
        verdict = rendering_gate.evaluate("12) Twelfth item")
        self.assertIn(rendering_gate.CLASS_LIST_MARKER, verdict.detected_classes)

    def test_bullet_marker_at_end_of_line(self) -> None:
        verdict = rendering_gate.evaluate("-")
        self.assertIn(rendering_gate.CLASS_LIST_MARKER, verdict.detected_classes)

    def test_empty_atx_heading(self) -> None:
        verdict = rendering_gate.evaluate("##")
        self.assertIn(rendering_gate.CLASS_ATX_HEADING, verdict.detected_classes)

    def test_tab_delimited_atx_heading(self) -> None:
        verdict = rendering_gate.evaluate("#\tTab heading")
        self.assertIn(rendering_gate.CLASS_ATX_HEADING, verdict.detected_classes)

    def test_fence_run_of_four_backticks(self) -> None:
        verdict = rendering_gate.evaluate("````python\ncode\n````")
        self.assertEqual(verdict.reason, rendering_gate.REASON_FENCED_CODE_BLOCK)
        self.assertIn(rendering_gate.CLASS_FENCED_CODE_BLOCK, verdict.detected_classes)

    def test_tab_indented_code_line(self) -> None:
        verdict = rendering_gate.evaluate("\tdef helper(): pass")
        self.assertIn(rendering_gate.CLASS_INDENTED_CODE_BLOCK, verdict.detected_classes)

    def test_one_character_setext_underline(self) -> None:
        verdict = rendering_gate.evaluate("Paragraph line\n=")
        self.assertIn(rendering_gate.CLASS_SETEXT_HEADING, verdict.detected_classes)

    def test_blockquote_no_space_after_gt(self) -> None:
        verdict = rendering_gate.evaluate(">quote with no space")
        self.assertIn(rendering_gate.CLASS_BLOCKQUOTE, verdict.detected_classes)

    def test_spaced_horizontal_rule(self) -> None:
        verdict = rendering_gate.evaluate("- - -")
        self.assertIn(rendering_gate.CLASS_HORIZONTAL_RULE, verdict.detected_classes)

    def test_underscore_horizontal_rule(self) -> None:
        verdict = rendering_gate.evaluate("___")
        self.assertIn(rendering_gate.CLASS_HORIZONTAL_RULE, verdict.detected_classes)

    def test_pipe_row_no_leading_or_trailing_pipe(self) -> None:
        verdict = rendering_gate.evaluate("cell | cell")
        self.assertIn(rendering_gate.CLASS_TABLE_PIPE_ROW, verdict.detected_classes)

    def test_link_ref_def_multi_word_label(self) -> None:
        verdict = rendering_gate.evaluate("[multi word label]: https://example.com")
        self.assertIn(
            rendering_gate.CLASS_LINK_REFERENCE_DEFINITION, verdict.detected_classes
        )

    def test_hard_break_three_trailing_spaces(self) -> None:
        verdict = rendering_gate.evaluate("First line   \nSecond line")
        self.assertIn(rendering_gate.CLASS_HARD_LINE_BREAK, verdict.detected_classes)

    def test_raw_html_attribute_tag_and_non_tag_openers(self) -> None:
        v_attr = rendering_gate.evaluate("<div class='custom'>content</div>")
        self.assertIn(rendering_gate.CLASS_RAW_HTML, v_attr.detected_classes)

        v_decl = rendering_gate.evaluate("<!DOCTYPE html>")
        self.assertIn(rendering_gate.CLASS_RAW_HTML, v_decl.detected_classes)

        v_pi = rendering_gate.evaluate("<?xml version='1.0'?>")
        self.assertIn(rendering_gate.CLASS_RAW_HTML, v_pi.detected_classes)

    def test_backslash_escape_bracket(self) -> None:
        verdict = rendering_gate.evaluate(r"An escaped bracket \[ here")
        self.assertIn(rendering_gate.CLASS_BACKSLASH_ESCAPE, verdict.detected_classes)

    def test_three_asterisk_emphasis_run(self) -> None:
        verdict = rendering_gate.evaluate("***bold and italic***")
        self.assertIn(rendering_gate.CLASS_EMPHASIS_STRONG, verdict.detected_classes)

    def test_one_tilde_strikethrough(self) -> None:
        verdict = rendering_gate.evaluate("~one tilde strike~")
        self.assertIn(rendering_gate.CLASS_STRIKETHROUGH, verdict.detected_classes)

    def test_two_backtick_code_span(self) -> None:
        verdict = rendering_gate.evaluate("``code with ` backtick``")
        self.assertIn(rendering_gate.CLASS_INLINE_CODE_SPAN, verdict.detected_classes)

    def test_inline_link_empty_bracket_text(self) -> None:
        verdict = rendering_gate.evaluate("[](https://example.com/empty)")
        self.assertIn(rendering_gate.CLASS_INLINE_LINK_IMAGE, verdict.detected_classes)

    def test_reference_link_multi_word_label(self) -> None:
        verdict = rendering_gate.evaluate("[text][multi word label]")
        self.assertIn(rendering_gate.CLASS_REFERENCE_LINK, verdict.detected_classes)

    def test_autolink_mailto_no_slashes(self) -> None:
        verdict = rendering_gate.evaluate("<mailto:ops@example.com>")
        self.assertIn(rendering_gate.CLASS_AUTOLINK, verdict.detected_classes)


class StatedNonClassesAcceptingTests(unittest.TestCase):
    """Every stated non-class passes as plain spoken text."""

    def test_arithmetic_asterisks(self) -> None:
        self.assertTrue(rendering_gate.evaluate("The total is 2 * 3 items.").is_plain)
        self.assertTrue(rendering_gate.evaluate("Calculate 2 * 3 * 4").is_plain)

    def test_identifier_underscores(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate("Check the snake_case variable in the module.").is_plain
        )
        self.assertTrue(
            rendering_gate.evaluate("Function get_user_by_id returns the user.").is_plain
        )

    def test_mid_sentence_hyphens(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate(
                "This is a high-level single-operator developer tool."
            ).is_plain
        )

    def test_spaced_comparison_angle_brackets(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate("Ensure that x < y and threshold > 0.").is_plain
        )

    def test_bare_bracketed_aside(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate(
                "The report stated that all tests passed [sic] yesterday."
            ).is_plain
        )

    def test_colon_labelled_line(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate("note: all checks passed successfully.").is_plain
        )

    def test_bare_spoken_url(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate(
                "You can view results at https://example.com/status."
            ).is_plain
        )

    def test_ampersand_in_prose_before_semicolon(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate("AT&T; announced their quarterly results.").is_plain
        )

    def test_backslash_before_letter_or_digit(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate(r"Check directory C:\Users\jefcox\workspace").is_plain
        )
        self.assertTrue(rendering_gate.evaluate(r"Item \100 in the list").is_plain)

    def test_trailing_spaces_on_final_line(self) -> None:
        self.assertTrue(
            rendering_gate.evaluate("This is the final line of text.   ").is_plain
        )

    def test_trailing_spaces_before_blank_line(self) -> None:
        text = "First paragraph with spaces.   \n\nSecond paragraph."
        self.assertTrue(rendering_gate.evaluate(text).is_plain)

    def test_multi_paragraph_separated_by_blank_lines(self) -> None:
        text = (
            "Here is the first paragraph of speech.\n\n"
            "Here is the second paragraph.\n\n"
            "And here is the conclusion."
        )
        self.assertTrue(rendering_gate.evaluate(text).is_plain)


class PrecedenceAndSurfaceTests(unittest.TestCase):
    """Precedence rules and public surface constraints."""

    def test_fenced_code_block_takes_precedence_over_emphasis(self) -> None:
        text = "Here is *bold* text and code:\n```bash\necho 'hi'\n```"
        verdict = rendering_gate.evaluate(text)
        self.assertFalse(verdict.is_plain)
        self.assertEqual(verdict.reason, rendering_gate.REASON_FENCED_CODE_BLOCK)
        self.assertIn(rendering_gate.CLASS_FENCED_CODE_BLOCK, verdict.detected_classes)
        self.assertIn(rendering_gate.CLASS_EMPHASIS_STRONG, verdict.detected_classes)

    def test_public_surface_has_no_transformation_function(self) -> None:
        forbidden = ("clean", "strip", "transform", "reformat", "sanitize", "repair")
        for name in dir(rendering_gate):
            if any(f in name.lower() for f in forbidden):
                self.fail(f"rendering_gate must not export transformation function {name!r} (R20)")


if __name__ == "__main__":
    unittest.main()
