#!/usr/bin/env python3
"""Lint a program issue's ``Recommended Executor Profile`` block against the fleet tier palette.

Every plugin-fleet program issue carries a profile block::

    ### Recommended Executor Profile
    - **Model:** opus
    - **Effort:** medium
    - **Backend:** inline
    - **Justification (required — profile is above sonnet):** ...

with a rule no code enforced until now: a profile above sonnet requires a justification line.
This lint validates model/effort membership and the above-sonnet rule against the canonical
fleet palette, resolved through the vendored fleet-commons shim (issue #463 U4 — the second
genuine palette consumer; DECISIONS ``{#fleet-commons-mechanism-463}``).

Stdlib-only; no gh calls — callers pipe the body in::

    gh issue view 463 --json body -q .body | python3 executor_profile_lint.py

Exit codes: 0 = profile passes; 1 = named findings (printed one per line); 2 = no profile
block found (a distinct outcome, not a lint failure — callers decide whether absence is an
error for their issue class).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_bundled"))
# The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose
# resolution ladder is Claude-specific runtime discovery this package must not
# retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on
# disk at install time and Fleet Core is never installed separately.
import tier_palette  # noqa: E402  (after the sys.path shim, by design)

_HEADING = re.compile(r"^#{2,6}\s*Recommended Executor Profile\s*$", re.IGNORECASE)
# Field names are whitelisted and matched ANCHORED at the start of a sentence segment, so prose
# colons inside values can't spawn phantom fields. Bullets in the real corpus come bolded
# (`- **Model:** opus`), plain (`- Model: sonnet`), backticked (`- Model: \`opus\``), and packed
# several-to-a-line (`- **Model**: sonnet. **Effort**: high.`); parse_profile() strips the
# markers, splits on sentence boundaries, and takes at most one field per segment.
_FIELD = re.compile(
    r"(?P<name>model|effort|backend|external-llm posture|justification[^:]*)\s*:\s*(?P<value>\S*)",
    re.IGNORECASE,
)

# Fields whose value is prose: once one is seen, the rest of its bullet is that value — never
# scanned for further field names (a justification legitimately containing "model: haiku" must
# not override the authored Model bullet).
_PROSE_FIELDS = ("justification", "external-llm")


def extract_profile_block(body: str) -> list[str] | None:
    """Lines of the profile block (heading excluded), or None when no block exists."""
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if _HEADING.match(line.strip()):
            block: list[str] = []
            for candidate in lines[index + 1 :]:
                if candidate.lstrip().startswith("#"):
                    break
                block.append(candidate)
            return block
    return None


def parse_profile(block: list[str]) -> dict[str, str]:
    """Map of lowercased field name -> first value seen, across the block's bullet lines."""
    fields: dict[str, str] = {}
    for line in block:
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        normalized = stripped.lstrip("- ").replace("*", "").replace("`", "")
        for segment in normalized.split(". "):
            match = _FIELD.match(segment.strip())
            if not match:
                continue
            name = match.group("name").strip().lower()
            fields.setdefault(name, match.group("value").strip().lower().rstrip(".,;"))
            if name.startswith(_PROSE_FIELDS):
                break
    return fields


def lint_body(body: str) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)`` for an issue body per the module contract."""
    palette = tier_palette
    block = extract_profile_block(body)
    if block is None:
        return 2, [
            "executor-profile-lint: no-profile-block (no 'Recommended Executor Profile' heading)"
        ]

    fields = parse_profile(block)
    findings: list[str] = []

    model = fields.get("model", "")
    if model not in palette.MODELS:
        findings.append(
            f"executor-profile-lint: unknown-model {model!r} (expected one of {palette.MODELS})"
        )
    effort = fields.get("effort", "")
    if effort not in palette.EFFORTS:
        findings.append(
            f"executor-profile-lint: unknown-effort {effort!r} (expected one of {palette.EFFORTS})"
        )

    has_justification = any(name.startswith("justification") for name in fields)
    if model in palette.MODELS:
        above_sonnet = palette.model_rank(model) < palette.model_rank("sonnet")
        if above_sonnet and not has_justification:
            findings.append(
                f"executor-profile-lint: missing-justification (model {model!r} ranks above "
                "sonnet; a '**Justification ...:**' line is required)"
            )

    if findings:
        return 1, findings
    return 0, [f"executor-profile-lint: ok (model={model} effort={effort})"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--body-file",
        type=Path,
        default=None,
        help="issue body file to lint (default: read stdin)",
    )
    args = parser.parse_args(argv)
    body = args.body_file.read_text(encoding="utf-8") if args.body_file else sys.stdin.read()
    exit_code, messages = lint_body(body)
    for message in messages:
        print(message)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
