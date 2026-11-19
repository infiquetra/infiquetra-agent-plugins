#!/usr/bin/env python3
"""Lifecycle Review — helper CLI for the saga plugin's rubric review (doc-review + spec).

Deterministic operations on rubrics + review logs. The agent (Claude
Code, in skill context) does the reasoning; this script handles the
file-shaped concerns (parse rubric frontmatter, append review-log
markers, write peer-review files for ADRs).

Subcommands:

  rubrics list-cores --phase <idea|spec|issue>
      List always-applicability rubrics for a phase.

  rubrics list-extras --phase <idea|spec|issue>
      List conditional-applicability rubrics for a phase.

  rubrics read --phase <phase> --slug <slug>
      Print one rubric's content (skill loads this and applies it).

  log append-section <file> --reviewer <slug> --score <N> [--pr-url <url>] --headline <one-liner>
      Append an entry inside <!-- review-log:start --> markers in
      <file>. Creates the markers if missing.

  log read-section <file>
      Print existing review-log entries for <file>, or a stub if none.

  adr-review init <adr-path>
      Create the adrs/reviews/<adr-id>/ folder for peer reviews.

  adr-review write <adr-path> --reviewer <slug> --score <N> --content-file <file>
      Write adrs/reviews/<adr-id>/<date>-<reviewer>.md with frontmatter
      + content from --content-file.

  adr-review list <adr-path>
      List existing peer-review files for an ADR.

By convention, the script lives at:
  <plugin-cache>/scripts/lifecycle_review.py

And the rubrics live at:
  <plugin-cache>/rubrics/<phase>/{core,extras}/<slug>.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

# ─── Paths ────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SCRIPT_DIR.parent
RUBRICS_DIR = PLUGIN_DIR / "references" / "rubrics"

# Review-log marker convention.
REVIEW_LOG_START = "<!-- review-log:start -->"
REVIEW_LOG_END = "<!-- review-log:end -->"

# Frontmatter regex (same shape as the orchestrator's reviewer_picker).
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ─── Rubric library ───────────────────────────────────────────────────────


@dataclass
class Rubric:
    slug: str
    phase: str
    tier: str  # "core" or "extras"
    path: Path
    applicability: str
    phases: list[str]


def _parse_yaml_simple(block: str) -> dict:
    """Tiny subset of YAML — handles our rubric frontmatter shape only.

    Avoids adding a yaml dependency to a script users invoke ad-hoc.
    Supports:
      key: value
      key: [a, b, c]    (inline list)
      key: "value"
    """
    out: dict = {}
    for line in block.splitlines():
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if not val:
            continue
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            items = [s.strip().strip("\"'") for s in inner.split(",") if s.strip()]
            out[key] = items
        elif (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            out[key] = val[1:-1]
        else:
            out[key] = val
    return out


def load_rubric(path: Path) -> Rubric:
    text = path.read_text()
    fm = {}
    m = _FRONTMATTER_RE.match(text)
    if m:
        fm = _parse_yaml_simple(m.group(1))
    phases = fm.get("phases") or ["unknown"]
    if not isinstance(phases, list):
        phases = [str(phases)]
    applicability = fm.get("applicability", "unknown")
    # Phase + tier from path: rubrics/<phase>/<tier>/<slug>.md
    parts = path.relative_to(RUBRICS_DIR).parts
    phase = parts[0] if len(parts) >= 1 else "unknown"
    tier = parts[1] if len(parts) >= 2 else "unknown"
    return Rubric(
        slug=path.stem,
        phase=phase,
        tier=tier,
        path=path,
        applicability=str(applicability),
        phases=phases,
    )


class RubricsUnavailableError(Exception):
    """The rubric library for a phase and tier cannot be loaded.

    Raised rather than returned empty (issue 1026, card 932). An empty list and a missing
    library are indistinguishable to a caller, and the caller here is a review that can block
    ``/work``: reporting "no core rubrics apply" for a directory that is simply absent removes
    the protection while continuing to report success. There is no signal an operator could use
    to tell a thorough review from a degraded one, so the failure is loud.
    """


def rubrics_for_phase(phase: str, tier: str) -> list[Rubric]:
    d = RUBRICS_DIR / phase / tier
    if not d.exists():
        raise RubricsUnavailableError(
            f"no rubric library at {d} for phase={phase} tier={tier}: "
            "the review stops rather than continuing on a weaker rubric"
        )
    rubrics = sorted(
        (load_rubric(p) for p in d.glob("*.md")),
        key=lambda r: r.slug,
    )
    if tier == "core" and not rubrics:
        raise RubricsUnavailableError(
            f"the core rubric library at {d} for phase={phase} is empty: "
            "every phase has always-apply rubrics, so an empty one is a broken install"
        )
    return rubrics


def find_rubric(phase: str, slug: str) -> Rubric | None:
    """Find a rubric by slug across both core and extras tiers."""
    for tier in ("core", "extras"):
        path = RUBRICS_DIR / phase / tier / f"{slug}.md"
        if path.exists():
            return load_rubric(path)
    return None


# ─── CLI: rubrics ─────────────────────────────────────────────────────────


def cmd_rubrics_list_cores(args: argparse.Namespace) -> int:
    try:
        rubrics = rubrics_for_phase(args.phase, "core")
    except RubricsUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([r.slug for r in rubrics]))
    else:
        for r in rubrics:
            print(r.slug)
    return 0


def cmd_rubrics_list_extras(args: argparse.Namespace) -> int:
    try:
        rubrics = rubrics_for_phase(args.phase, "extras")
    except RubricsUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([r.slug for r in rubrics]))
    else:
        for r in rubrics:
            print(r.slug)
    return 0


def cmd_rubrics_read(args: argparse.Namespace) -> int:
    rubric = find_rubric(args.phase, args.slug)
    if rubric is None:
        print(
            f"ERROR: no rubric for phase={args.phase} slug={args.slug}",
            file=sys.stderr,
        )
        return 1
    print(rubric.path.read_text(), end="")
    return 0


# ─── CLI: log (section-embedded) ──────────────────────────────────────────


def _format_log_entry(
    *,
    date: str,
    slug: str,
    score: float,
    pr_url: str | None,
    headline: str,
) -> str:
    """Format a single review-log entry line.

    Pattern matches the convention documented in:
      infiquetra-sdlc/docs/lifecycle/ideation-to-pr.md
    """
    score_str = f"({score:.1f})"
    link = f" — [comment]({pr_url})" if pr_url else ""
    return f'- {date} — {slug} {score_str}{link} — "{headline}"'


def _ensure_markers(text: str) -> str:
    """Ensure the review-log markers exist at the end of the file.

    If absent, append a fresh block. If present, leave content untouched.
    """
    if REVIEW_LOG_START in text and REVIEW_LOG_END in text:
        return text
    sep = "" if text.endswith("\n") else "\n"
    block = f"\n{REVIEW_LOG_START}\n### Review log\n{REVIEW_LOG_END}\n"
    return text + sep + block


def cmd_log_append_section(args: argparse.Namespace) -> int:
    target = Path(args.file)
    if not target.exists():
        print(f"ERROR: file not found: {target}", file=sys.stderr)
        return 1
    text = target.read_text()
    text = _ensure_markers(text)
    date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    entry = _format_log_entry(
        date=date,
        slug=args.reviewer,
        score=args.score,
        pr_url=args.pr_url,
        headline=args.headline,
    )
    # Insert entry just before END marker.
    new = text.replace(
        REVIEW_LOG_END,
        f"{entry}\n{REVIEW_LOG_END}",
        1,
    )
    target.write_text(new)
    print(f"Appended to {target}: {entry}")
    return 0


def cmd_log_read_section(args: argparse.Namespace) -> int:
    target = Path(args.file)
    if not target.exists():
        print(f"ERROR: file not found: {target}", file=sys.stderr)
        return 1
    text = target.read_text()
    if REVIEW_LOG_START not in text:
        print("(no review log yet)")
        return 0
    start = text.index(REVIEW_LOG_START)
    end = text.index(REVIEW_LOG_END) + len(REVIEW_LOG_END) if REVIEW_LOG_END in text else len(text)
    print(text[start:end])
    return 0


# ─── CLI: adr-review (folder-of-peer-reviews) ─────────────────────────────


def _adr_id(adr_path: Path) -> str:
    """Extract the ADR id from a path like 'adrs/adr-001-flutter-foo.md'.

    Returns 'adr-001' (or the bare stem if not adr-NNN-shaped).
    """
    stem = adr_path.stem
    m = re.match(r"^(adr-\d+)", stem, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return stem


def _adr_reviews_dir(adr_path: Path) -> Path:
    """Return the canonical reviews/<adr-id>/ folder for a given ADR file."""
    return adr_path.parent / "reviews" / _adr_id(adr_path)


def cmd_adr_review_init(args: argparse.Namespace) -> int:
    adr_path = Path(args.adr_path)
    if not adr_path.exists():
        print(f"ERROR: adr file not found: {adr_path}", file=sys.stderr)
        return 1
    reviews_dir = _adr_reviews_dir(adr_path)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created (or exists): {reviews_dir}")
    return 0


def cmd_adr_review_write(args: argparse.Namespace) -> int:
    adr_path = Path(args.adr_path)
    if not adr_path.exists():
        print(f"ERROR: adr file not found: {adr_path}", file=sys.stderr)
        return 1
    content_path = Path(args.content_file)
    if not content_path.exists():
        print(f"ERROR: content file not found: {content_path}", file=sys.stderr)
        return 1
    reviews_dir = _adr_reviews_dir(adr_path)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = reviews_dir / f"{date}-{args.reviewer}.md"
    if out_path.exists():
        # Don't clobber existing reviews — append a counter suffix.
        for i in range(2, 100):
            candidate = reviews_dir / f"{date}-{args.reviewer}-v{i}.md"
            if not candidate.exists():
                out_path = candidate
                break
    body = content_path.read_text()
    frontmatter = (
        "---\n"
        f"reviewer: {args.reviewer}\n"
        f"score: {args.score:.1f}\n"
        f"date: {date}\n"
        f"adr: {_adr_id(adr_path)}\n"
        f"phase: {args.phase or 'idea'}\n"
        f"verdict: {args.verdict or 'PROCEED'}\n"
        "---\n\n"
    )
    out_path.write_text(frontmatter + body if not body.startswith("---") else body)
    print(f"Wrote: {out_path}")
    return 0


def cmd_adr_review_list(args: argparse.Namespace) -> int:
    adr_path = Path(args.adr_path)
    reviews_dir = _adr_reviews_dir(adr_path)
    if not reviews_dir.exists():
        print(f"(no reviews folder yet for {_adr_id(adr_path)})")
        return 0
    for f in sorted(reviews_dir.glob("*.md")):
        print(f.name)
    return 0


# ─── CLI dispatch ─────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lifecycle_review", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    # rubrics
    p_rub = sub.add_parser("rubrics", help="Rubric library operations")
    sub_rub = p_rub.add_subparsers(dest="subcmd", required=True)

    p_rlc = sub_rub.add_parser("list-cores", help="List always-applicability rubrics for a phase")
    p_rlc.add_argument("--phase", required=True, choices=["idea", "spec", "issue"])
    p_rlc.add_argument("--json", action="store_true", help="Emit JSON list of slugs")
    p_rlc.set_defaults(func=cmd_rubrics_list_cores)

    p_rle = sub_rub.add_parser(
        "list-extras", help="List conditional-applicability rubrics for a phase"
    )
    p_rle.add_argument("--phase", required=True, choices=["idea", "spec", "issue"])
    p_rle.add_argument("--json", action="store_true", help="Emit JSON list of slugs")
    p_rle.set_defaults(func=cmd_rubrics_list_extras)

    p_rr = sub_rub.add_parser("read", help="Print one rubric's content")
    p_rr.add_argument("--phase", required=True, choices=["idea", "spec", "issue"])
    p_rr.add_argument("--slug", required=True)
    p_rr.set_defaults(func=cmd_rubrics_read)

    # log
    p_log = sub.add_parser("log", help="Section-embedded review log")
    sub_log = p_log.add_subparsers(dest="subcmd", required=True)

    p_la = sub_log.add_parser("append-section", help="Append an entry inside review-log markers")
    p_la.add_argument("file")
    p_la.add_argument("--reviewer", required=True)
    p_la.add_argument("--score", required=True, type=float)
    p_la.add_argument("--pr-url")
    p_la.add_argument("--headline", required=True, help="One-line summary of the finding")
    p_la.add_argument("--date", help="Override date (default: today UTC)")
    p_la.set_defaults(func=cmd_log_append_section)

    p_lr = sub_log.add_parser("read-section", help="Read existing review-log entries from a file")
    p_lr.add_argument("file")
    p_lr.set_defaults(func=cmd_log_read_section)

    # adr-review
    p_adr = sub.add_parser("adr-review", help="ADR peer-review folder operations")
    sub_adr = p_adr.add_subparsers(dest="subcmd", required=True)

    p_ai = sub_adr.add_parser("init", help="Create reviews/<adr-id>/ folder")
    p_ai.add_argument("adr_path")
    p_ai.set_defaults(func=cmd_adr_review_init)

    p_aw = sub_adr.add_parser("write", help="Write a peer-review markdown file for an ADR")
    p_aw.add_argument("adr_path")
    p_aw.add_argument("--reviewer", required=True)
    p_aw.add_argument("--score", required=True, type=float)
    p_aw.add_argument(
        "--content-file", required=True, help="Path to file with the review body markdown"
    )
    p_aw.add_argument("--date", help="Override date (default: today UTC)")
    p_aw.add_argument("--phase", help="Phase (default: idea)")
    p_aw.add_argument("--verdict", help="PROCEED|REVISE|BLOCK (default: PROCEED)")
    p_aw.set_defaults(func=cmd_adr_review_write)

    p_al = sub_adr.add_parser("list", help="List peer-review files for an ADR")
    p_al.add_argument("adr_path")
    p_al.set_defaults(func=cmd_adr_review_list)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return cast(int, args.func(args))


if __name__ == "__main__":
    sys.exit(main())
