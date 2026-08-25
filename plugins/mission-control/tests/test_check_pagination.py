"""Tests for `check_pagination.py` -- the pagination-completeness lint (#424, T9-F4-5).

Proves the lint catches the exact call-site shape named in the grounding
brief's session-mining synthesis: an unguarded `gh project item-list` (or
equivalent raw list call) added to a plugin script or an agent-facing skill
reference doc, lacking a cursor loop or explicit `--limit`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_pagination  # noqa: E402


class TestUnguardedItemList:
    def test_unguarded_call_site_fails(self, tmp_path):
        """An unguarded `gh project item-list` added to a plugin script or an
        agent-facing skill reference doc fails the lint (T9-F4-5)."""
        doc = tmp_path / "some-agent-doc.md"
        doc.write_text(
            "Run this to see all items:\n\n"
            "```bash\n"
            "gh project item-list 4 --owner infiquetra --format json\n"
            "```\n"
        )
        violations = check_pagination.check_file(doc)
        assert violations
        assert any("gh project item-list" in v for v in violations)

    def test_guarded_call_with_limit_passes(self, tmp_path):
        doc = tmp_path / "guarded-doc.md"
        doc.write_text(
            "```bash\ngh project item-list 4 --owner infiquetra --format json --limit 1000\n```\n"
        )
        assert check_pagination.check_file(doc) == []

    def test_limit_on_a_wrapped_continuation_line_passes(self, tmp_path):
        """A `\\`-continued invocation with `--limit` on the next line is
        still guarded -- the window check must span continuation lines."""
        doc = tmp_path / "wrapped-doc.md"
        doc.write_text(
            "```bash\n"
            "gh project item-list 4 --owner infiquetra --format json \\\n"
            "  --limit 1000\n"
            "```\n"
        )
        assert check_pagination.check_file(doc) == []

    def test_comment_mentioning_the_command_by_name_is_not_flagged(self, tmp_path):
        """A comment explaining `gh project item-list`'s behavior (not an
        actual invocation) must not false-positive."""
        doc = tmp_path / "explainer-doc.md"
        doc.write_text(
            "```bash\n"
            "# `gh project item-list` flattens project-field values into top-level keys\n"
            "gh project item-list 4 --owner infiquetra --limit 1000\n"
            "```\n"
        )
        assert check_pagination.check_file(doc) == []


class TestBareRestPageFetch:
    def test_bare_rest_get_with_per_page_fails(self, tmp_path):
        script = tmp_path / "some_script.py"
        script.write_text('existing = _rest_get(f"/repos/{ORG}/{repo}/labels?per_page=100")\n')
        violations = check_pagination.check_file(script)
        assert violations
        assert any("_rest_list_paginated" in v for v in violations)

    def test_rest_list_paginated_call_passes(self, tmp_path):
        script = tmp_path / "some_script.py"
        script.write_text('existing = _rest_list_paginated(f"/repos/{ORG}/{repo}/labels")\n')
        assert check_pagination.check_file(script) == []

    def test_suppress_marker_allows_the_paginated_helpers_own_call(self, tmp_path):
        script = tmp_path / "helper.py"
        script.write_text(
            'batch = _rest_get(f"{path}?per_page={per_page}")  # pagination-lint: allow\n'
        )
        assert check_pagination.check_file(script) == []


class TestGraphqlFirstWithoutHasNextPage:
    def test_first_arg_without_has_next_page_check_fails(self, tmp_path):
        script = tmp_path / "query.py"
        script.write_text('QUERY = """query { items(first: 100) { nodes { id } } }"""\n')
        violations = check_pagination.check_file(script)
        assert violations
        assert any("hasNextPage" in v for v in violations)

    def test_first_arg_with_has_next_page_check_passes(self, tmp_path):
        script = tmp_path / "query.py"
        script.write_text(
            'QUERY = """query { items(first: 100) { pageInfo { hasNextPage } } }"""\n'
        )
        assert check_pagination.check_file(script) == []

    def test_unpaginated_query_inside_file_with_paginated_query_fails(self, tmp_path):
        """Query-scoped check flags an unpaginated query even if another query
        in the same file checks hasNextPage (#584, R2)."""
        script = tmp_path / "mixed_queries.py"
        script.write_text(
            'QUERY_PAGINATED = """\n'
            "query($org: String!, $number: Int!, $cursor: String) {\n"
            "  organization(login: $org) {\n"
            "    projectV2(number: $number) {\n"
            "      items(first: 100, after: $cursor) {\n"
            "        pageInfo { hasNextPage endCursor }\n"
            "        nodes { id }\n"
            "      }\n"
            "    }\n"
            "  }\n"
            '}\n"""\n\n'
            'QUERY_UNPAGINATED = """\n'
            "query($org: String!, $number: Int!) {\n"
            "  organization(login: $org) {\n"
            "    projectV2(number: $number) {\n"
            "      fields(first: 30) {\n"
            "        nodes { id }\n"
            "      }\n"
            "    }\n"
            "  }\n"
            '}\n"""\n'
        )
        violations = check_pagination.check_file(script)
        assert violations
        assert any("mixed_queries.py:14" in v and "hasNextPage" in v for v in violations)


class TestRunLint:
    def test_run_lint_aggregates_across_files(self, tmp_path):
        clean = tmp_path / "clean.py"
        clean.write_text("x = 1\n")
        dirty = tmp_path / "dirty.md"
        dirty.write_text("gh project item-list 4 --owner infiquetra\n")
        violations = check_pagination.run_lint([tmp_path])
        assert len(violations) == 1

    def test_the_actual_mission_control_tree_is_currently_clean(self):
        """Regression guard: the real mission-control scripts/skills/commands/
        agents tree must not regress to an unguarded call site."""
        assert check_pagination.run_lint() == []


class TestGraphqlGuardNeverFailsOpen:
    """The query-scoped rewrite (#584 R2) must never be WEAKER than the
    whole-file check it replaced: an extractor that cannot parse a literal
    shape falls back, it does not go quiet."""

    def test_stray_triple_single_quote_does_not_blind_the_file(self, tmp_path):
        """A module docstring containing ``'''`` must not desynchronize literal
        pairing and silently switch the GraphQL guard off for the whole file."""
        script = tmp_path / "mixed_quote_styles.py"
        script.write_text(
            '"""Module docstring mentioning \'\'\' inline."""\n'
            "\n"
            'QUERY = """\n'
            "query($org: String!) {\n"
            "  organization(login: $org) {\n"
            "    projectV2(number: 1) { fields(first: 30) { nodes { id } } }\n"
            "  }\n"
            "}\n"
            '"""\n'
        )
        violations = check_pagination.check_file(script)
        assert violations
        assert any("hasNextPage" in v for v in violations)

    def test_unpaginated_query_in_untagged_fence_beside_paginated_fence_fails(self, tmp_path):
        """A doc whose ``graphql`` fence paginates must not launder an
        unpaginated query sitting in a differently-tagged fence."""
        doc = tmp_path / "mixed_fences.md"
        doc.write_text(
            "# Queries\n\n"
            "```graphql\n"
            "query($c: String) { items(first: 10, after: $c) "
            "{ pageInfo { hasNextPage } nodes { id } } }\n"
            "```\n\n"
            "```json\n"
            '{"query": "query { projectV2 { fields(first: 30) { nodes { id } } } }"}\n'
            "```\n"
        )
        violations = check_pagination.check_file(doc)
        assert violations
        assert any("hasNextPage" in v for v in violations)
