#!/usr/bin/env python3
"""Manifest reader: advisory signals over the provenance-manifest tree (U6/KTD8).

Sibling to ``override_rate_reader.py`` — same house pattern (pure functions over an
injectable ``root``, offline-testable, ``--json``/human dual output). Scans every manifest
JSON file under a manifest-namespace directory (``<git-common-dir>/saga-manifests/`` — see
``manifest_store.MANIFEST_NAMESPACE``) and surfaces three advisory signals, all optional
consumers of ``provenance_manifest.py``'s schema:

* **parroting_count** (R7) — claims that were producer-claimed ``verified`` but Claude's
  adjudication refuted them or found them unsupported. Delegates to
  ``provenance_manifest.is_parroting`` — the taxonomy predicate lives there, not here
  (KTD5), so this reader can never drift from the schema's own definition.
* **disposition_rate** (R18) — the fraction of manifests landing in each ``Disposition``
  bucket (``ran-as-requested`` / ``fell-back-to-claude`` / ``substituted-engine``), mirroring
  ``override_rate_reader``'s rate semantics: a bucket's rate is ``None`` only when there are
  zero manifests total (not zero for that bucket — an empty bucket is a legitimate 0.0%,
  distinct from "no data yet").
* **verified_ratio** (R16) — among adjudicated claims, the fraction landing ``verified``
  vs. ``inferred``/``not-checked`` (``refuted`` claims are excluded from the denominator:
  they are parroting/mismatch signal, not a confidence-tier data point). ``None`` when no
  claim in the tree has been adjudicated yet.
* **fallback_reasons** (R6/U4/KTD2) — for every manifest whose disposition is not
  ``RAN_AS_REQUESTED``, the execution id, disposition, and ``disposition_note`` prose. This is
  the operator-facing surface for the reason a run fell back or was substituted (the
  ``disposition_note`` is already builder-enforced non-empty for these dispositions per R3 —
  this reader just renders it, it does not invent a new roll-up artifact or write ledger
  records).

Every signal here is advisory only (R8/R12): this module computes findings, never raises,
never gates, and an empty or absent manifest tree is not an error (R12 — no gate of its own).

CLI::

    python3 manifest_reader.py [--root <path>] [--json]

``--root`` is the manifest-namespace directory itself (i.e. the directory that directly
contains one subdirectory per saga id, each holding ``<execution-id>.json`` files) — the same
directory ``manifest_store.Store.for_saga().root.parent`` points at. Passing the git-common-dir
directly also works since manifests always live at ``<root>/saga-manifests/<saga-id>/*.json``;
callers that already have a resolved common dir should pass ``<common-dir>/saga-manifests``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import provenance_manifest  # noqa: E402  (after the sys.path shim, by design)

# ---------------------------------------------------------------------------
# Manifest tree scan
# ---------------------------------------------------------------------------


def _all_manifest_files(root: Path) -> list[Path]:
    """Return every ``*.json`` manifest file under ``root`` (one subdir per saga id).

    Missing/non-directory ``root`` is not an error — an empty list, advisory by construction
    (R8/R12): callers treat "no manifests yet" the same as "manifest tree not created yet".
    """
    if not root.is_dir():
        return []
    files: list[Path] = []
    for saga_dir in root.iterdir():
        if not saga_dir.is_dir():
            continue
        files.extend(sorted(saga_dir.glob("*.json")))
    return sorted(files)


def read_manifests(root: Path) -> list[provenance_manifest.Manifest]:
    """Load every parseable manifest under ``root``. Malformed files are skipped, not fatal."""
    manifests: list[provenance_manifest.Manifest] = []
    for path in _all_manifest_files(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            manifests.append(provenance_manifest.Manifest.from_dict(data))
        except provenance_manifest.ManifestError:
            continue
    return manifests


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FallbackReason:
    """A single non-``RAN_AS_REQUESTED`` manifest's operator-facing reason (R6/U4)."""

    execution_id: str
    disposition: str
    disposition_note: str

    def as_dict(self) -> dict[str, str]:
        return {
            "execution_id": self.execution_id,
            "disposition": self.disposition,
            "disposition_note": self.disposition_note,
        }


@dataclass(frozen=True)
class ManifestSummary:
    """The full U6 advisory surface (R7/R16/R18) plus the R6/U4 fallback-reason roll-up."""

    total_manifests: int
    total_claims: int
    parroting_count: int  # R7
    disposition_counts: dict[str, int]  # R18 raw tallies, one key per Disposition value
    adjudicated_verified_count: int  # R16
    adjudicated_inferred_count: int  # R16
    adjudicated_not_checked_count: int  # R16
    adjudicated_refuted_count: int  # excluded from the R16 ratio denominator
    fallback_reasons: tuple[FallbackReason, ...] = ()  # R6/U4

    @property
    def disposition_rate(self) -> dict[str, float | None]:
        """Fraction of manifests per disposition bucket; all ``None`` when there is no data."""
        if self.total_manifests == 0:
            return dict.fromkeys(self.disposition_counts, None)
        return {key: count / self.total_manifests for key, count in self.disposition_counts.items()}

    @property
    def verified_ratio(self) -> float | None:
        """R16: verified / (verified + inferred + not-checked) among adjudicated claims.

        ``refuted`` claims are excluded (they are parroting/mismatch signal, not a
        confidence-tier data point). ``None`` when nothing has been adjudicated yet.
        """
        denom = (
            self.adjudicated_verified_count
            + self.adjudicated_inferred_count
            + self.adjudicated_not_checked_count
        )
        if denom == 0:
            return None
        return self.adjudicated_verified_count / denom

    @property
    def parroting_rate(self) -> float | None:
        """Fraction of all claims that count as parroting; ``None`` when there are no claims."""
        if self.total_claims == 0:
            return None
        return self.parroting_count / self.total_claims

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_manifests": self.total_manifests,
            "total_claims": self.total_claims,
            "parroting_count": self.parroting_count,
            "parroting_rate": self.parroting_rate,
            "disposition_counts": dict(self.disposition_counts),
            "disposition_rate": self.disposition_rate,
            "adjudicated_verified_count": self.adjudicated_verified_count,
            "adjudicated_inferred_count": self.adjudicated_inferred_count,
            "adjudicated_not_checked_count": self.adjudicated_not_checked_count,
            "adjudicated_refuted_count": self.adjudicated_refuted_count,
            "verified_ratio": self.verified_ratio,
            "fallback_reasons": [reason.as_dict() for reason in self.fallback_reasons],
        }


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------


def summarize(manifests: list[provenance_manifest.Manifest]) -> ManifestSummary:
    """Compute the R7/R16/R18 advisory summary over an already-loaded manifest list."""
    disposition_counts: dict[str, int] = {d.value: 0 for d in provenance_manifest.Disposition}
    total_claims = 0
    parroting = 0
    verified = inferred = not_checked = refuted = 0
    fallback_reasons: list[FallbackReason] = []

    for manifest in manifests:
        disposition_counts[manifest.disposition.value] += 1
        if manifest.disposition != provenance_manifest.Disposition.RAN_AS_REQUESTED:
            fallback_reasons.append(
                FallbackReason(
                    execution_id=manifest.execution_id,
                    disposition=manifest.disposition.value,
                    disposition_note=manifest.disposition_note,
                )
            )
        if manifest.claim_provenance is None:
            continue
        for claim in manifest.claim_provenance.claims:
            total_claims += 1
            if provenance_manifest.is_parroting(claim):
                parroting += 1
            if claim.adjudicated is provenance_manifest.AdjudicatedStatus.VERIFIED:
                verified += 1
            elif claim.adjudicated is provenance_manifest.AdjudicatedStatus.INFERRED:
                inferred += 1
            elif claim.adjudicated is provenance_manifest.AdjudicatedStatus.NOT_CHECKED:
                not_checked += 1
            elif claim.adjudicated is provenance_manifest.AdjudicatedStatus.REFUTED:
                refuted += 1

    return ManifestSummary(
        total_manifests=len(manifests),
        total_claims=total_claims,
        parroting_count=parroting,
        disposition_counts=disposition_counts,
        adjudicated_verified_count=verified,
        adjudicated_inferred_count=inferred,
        adjudicated_not_checked_count=not_checked,
        adjudicated_refuted_count=refuted,
        fallback_reasons=tuple(fallback_reasons),
    )


def read_manifest_summary(root: Path) -> tuple[ManifestSummary, list[provenance_manifest.Manifest]]:
    """Scan ``root`` and return ``(summary, manifests)``. Never raises on an empty/absent tree."""
    manifests = read_manifests(root)
    return summarize(manifests), manifests


# ---------------------------------------------------------------------------
# Human-readable report
# ---------------------------------------------------------------------------


def _pct(rate: float | None) -> str:
    if rate is None:
        return "no data yet"
    return f"{rate * 100:.1f}%"


def format_report(summary: ManifestSummary) -> str:
    """Return a human-readable R7/R16/R18 signal report."""
    lines: list[str] = [
        "## Provenance Manifest Signals",
        "",
        f"Manifests scanned: {summary.total_manifests}",
        f"Claims scanned: {summary.total_claims}",
        "",
        "### Parroting (R7)",
        f"  Parroting claims: {summary.parroting_count}"
        + (f" ({_pct(summary.parroting_rate)} of claims)" if summary.total_claims > 0 else ""),
        "",
        "### Disposition Rate (R18)",
    ]
    for key, count in sorted(summary.disposition_counts.items()):
        rate = summary.disposition_rate.get(key)
        lines.append(f"  {key}: {count} ({_pct(rate)})")

    lines += [
        "",
        "### Adjudicated Verified Ratio (R16)",
        f"  verified: {summary.adjudicated_verified_count}",
        f"  inferred: {summary.adjudicated_inferred_count}",
        f"  not-checked: {summary.adjudicated_not_checked_count}",
        f"  refuted (excluded from ratio): {summary.adjudicated_refuted_count}",
        f"  verified ratio: {_pct(summary.verified_ratio)}",
    ]

    if summary.fallback_reasons:
        lines += [
            "",
            "### Fallback Reasons (R6)",
        ]
        for reason in summary.fallback_reasons:
            lines.append(
                f"  {reason.execution_id} [{reason.disposition}]: {reason.disposition_note}"
            )

    if summary.total_manifests == 0:
        lines += [
            "",
            "No manifests recorded yet. This is advisory-only signal (R8/R12) — it never",
            "blocks. Run again after delegated executions have written manifests.",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Surface R7/R16/R18 advisory signals from the provenance-manifest tree."
    )
    parser.add_argument(
        "--root",
        default=".claude/saga-manifests",
        help=(
            "Manifest-namespace directory (one subdirectory per saga id). Default: "
            "'.claude/saga-manifests' (repo-local fallback; production trees live under the "
            "resolved git-common-dir's 'saga-manifests/' — pass that path explicitly)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit a machine-readable JSON summary instead of the human report.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    summary, _manifests = read_manifest_summary(root)

    if args.as_json:
        print(json.dumps(summary.as_dict(), indent=2))
    else:
        print(format_report(summary))
    return 0  # advisory only — never a non-zero exit (R8/R12)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
