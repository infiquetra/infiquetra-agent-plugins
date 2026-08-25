#!/usr/bin/env python3
"""Consumer-side parity gate for the vendored issue-contract artifacts (U1/U4, KTD3).

The mission-control plugin is a CONSUMER of the issue-contract pipeline whose
source of truth is ``infiquetra-sdlc`` (``tools/docs/gen_issue_contract.py``) --
the same vendoring pattern the plugin already uses for ``config/sdlc-schema.json``.
TWO generated modules are vendored here, each next to its pinned SHA256 manifest:

  * ``issue_contract_data.py`` -- the WHOLE validator data surface (U1);
  * ``issue_contract_shim.py`` -- the mission-control validation-shim DATA the
    ``sdlc_manager.py`` ``validate_card_body`` algorithm imports (U4).

This gate proves both vendored copies have not silently drifted.

Design (deliberately does NOT run the sdlc generator): the source generator
emits, in the source repo, each artifact PLUS a pinned SHA256 fingerprint of its
bytes; both are vendored here. This gate recomputes the SHA256 of each vendored
module and compares it to its vendored ``.sha256`` manifest. A match means the
vendored bytes equal what the source generator last produced and pinned; any
hand-edit to a vendored module flips its hash and fails the gate. No sdlc
checkout, no generator run -- just stdlib hashlib.

A THIRD leg (#424, T14-F5-3, ``--live``-gated) reconciles a document this
two-way match never touched: ``config/sdlc-schema.json`` itself declares (its
own ``description`` field) that it "intentionally contains no live GitHub
Projects field option IDs; tooling must resolve those from GitHub at
runtime" -- but nothing previously asserted that resolution ever ran or ever
drifted. ``--live`` fetches each tracked board's live Status field options and
flags any schema-declared status that no longer resolves live (a renamed or
removed upstream option). This leg requires network + a Projects-scoped `gh`
token; when that's unavailable (e.g. an offline CI runner) it prints an
explicit SKIPPED line rather than silently passing, mirroring
``board_census.py --check``'s same offline posture.

Exit 0 = in sync (or live leg skipped); exit 1 = drift.

Usage::

    python3 check_issue_contract_parity.py            # two vendored-artifact legs
    python3 check_issue_contract_parity.py --live      # + live Status-option leg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

VENDOR_DIR = Path(__file__).resolve().parent
MISSION_CONTROL_DIR = VENDOR_DIR.parent.parent
SDLC_SCHEMA_PATH = VENDOR_DIR.parent / "sdlc-schema.json"

# Each vendored artifact + its pinned SHA256 sidecar manifest. Adding a future
# vendored artifact here extends the gate with no other change.
VENDORED_ARTIFACTS = (
    VENDOR_DIR / "issue_contract_data.py",
    VENDOR_DIR / "issue_contract_shim.py",
)


def _sha_path(artifact: Path) -> Path:
    """The pinned-SHA sidecar manifest path for a vendored artifact."""
    return artifact.with_suffix(artifact.suffix + ".sha256")


def parity_errors(artifacts: tuple[Path, ...] = VENDORED_ARTIFACTS) -> list[str]:
    """Return human-readable parity violations across every vendored artifact;
    empty list = all in sync."""
    errors: list[str] = []
    for artifact in artifacts:
        sha_path = _sha_path(artifact)
        if not artifact.exists():
            errors.append(f"vendored issue-contract artifact missing: {artifact}")
            continue
        if not sha_path.exists():
            errors.append(f"vendored issue-contract SHA manifest missing: {sha_path}")
            continue

        actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
        expected = sha_path.read_text(encoding="utf-8").strip()
        if actual != expected:
            errors.append(
                f"vendored {artifact.name} has drifted from the source-of-truth "
                "pinned hash (infiquetra-sdlc gen_issue_contract.py):\n"
                f"  expected (pinned): {expected}\n"
                f"  actual   (vendor): {actual}\n"
                "Re-vendor the generated artifact from infiquetra-sdlc."
            )
    return errors


class LiveParityUnavailableError(RuntimeError):
    """Raised when the live leg cannot reach GitHub -- a SKIP, never a silent pass."""


def live_status_option_errors(
    schema_path: Path = SDLC_SCHEMA_PATH,
    *,
    fetch_fields_census: Any = None,
    project_mappings: dict[str, Any] | None = None,
) -> list[str]:
    """Third, ``--live``-gated leg (#424, T14-F5-3): reconcile each board's
    schema-declared Status options against the LIVE GitHub Projects Status
    field. Returns human-readable violations; empty list = all resolve live.

    Raises ``LiveParityUnavailableError`` when live derivation itself cannot
    run (no network / no Projects-scoped `gh` auth, or the schema file is
    missing) -- callers must treat that as a SKIP, never fold it into "no
    violations found".

    ``fetch_fields_census`` / ``project_mappings`` are injectable for tests;
    production callers leave both ``None`` and get the real
    ``board_census.fetch_project_fields_census`` / live project mappings.
    """
    if fetch_fields_census is None or project_mappings is None:
        sys.path.insert(0, str(MISSION_CONTROL_DIR / "scripts"))
        try:
            from board_census import fetch_project_fields_census
            from sdlc_manager import load_config
        except ImportError as exc:
            raise LiveParityUnavailableError(
                f"cannot import live-resolution helpers: {exc}"
            ) from exc

        if fetch_fields_census is None:
            fetch_fields_census = fetch_project_fields_census
        if project_mappings is None:
            try:
                config = load_config()
            except Exception as exc:  # noqa: BLE001 - any live-access failure is a SKIP
                raise LiveParityUnavailableError(f"could not load project mappings: {exc}") from exc
            project_mappings = config.get("project_mappings", {}).get("projects", {})

    if not schema_path.exists():
        raise LiveParityUnavailableError(f"sdlc-schema.json not found at {schema_path}")
    schema = json.loads(schema_path.read_text())

    errors: list[str] = []
    for board_key, board_cfg in schema.get("boards", {}).items():
        proj = project_mappings.get(board_key)
        if not proj:
            continue
        workflow = schema.get("workflows", {}).get(board_cfg.get("workflow", ""), {})
        expected_statuses = set(workflow.get("statuses", []))
        if not expected_statuses:
            continue

        try:
            census = fetch_fields_census(proj["number"])
        except Exception as exc:  # noqa: BLE001 - any live-access failure is a SKIP
            raise LiveParityUnavailableError(
                f"could not fetch live fields for board '{board_key}': {exc}"
            ) from exc

        status_field = next((f for f in census["fields"] if f["name"] == "Status"), None)
        live_statuses = (
            {o["name"] for o in status_field.get("options", [])} if status_field else set()
        )
        missing = expected_statuses - live_statuses
        if missing:
            errors.append(
                f"live parity: board '{board_key}' declares Status option(s) "
                f"{sorted(missing)} in sdlc-schema.json that do not resolve on the "
                f"live project (live options: {sorted(live_statuses)}). The option "
                "was renamed/removed upstream, or sdlc-schema.json is stale."
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also run the live GitHub Projects Status-option reconciliation leg",
    )
    args = parser.parse_args()

    errors = parity_errors()
    live_skip_reason: str | None = None
    if args.live:
        try:
            errors.extend(live_status_option_errors())
        except LiveParityUnavailableError as exc:
            live_skip_reason = str(exc)

    if errors:
        for err in errors:
            print(f"FAIL {err}")
        print("\nissue-contract consumer parity check FAILED")
        return 1

    print("issue-contract consumer parity check passed: vendored artifacts are in sync")
    if args.live:
        if live_skip_reason:
            print(f"SKIPPED live parity leg: {live_skip_reason}")
        else:
            print("live parity leg passed: schema-declared Status options resolve live")
    else:
        print(
            "SKIPPED live parity leg: not requested (pass --live to run live GitHub Projects reconciliation)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
