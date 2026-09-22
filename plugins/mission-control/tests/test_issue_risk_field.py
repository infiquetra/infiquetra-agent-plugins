"""T1000-01..T1000-05: common ### Risk body field (#1000)."""

# ruff: noqa: E402,I001

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
VENDORED_SCHEMA = PLUGIN_ROOT / "config" / "sdlc-schema.json"

F_CORE = """### Objective
Add a prepared issue workflow.

### Intent
Authoring agents need a draft-then-approve path; without it cards skip review.
End-state: every prepared card is drafted, gated, and only then created.

### Acceptance criteria
- [ ] Drafts are written before GitHub mutation; `uv run pytest plugins/mission-control/tests/test_issue_risk_field.py` exits 0

### Out-of-scope / non-goals
- Do not auto-move issues to Ready

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_issue_risk_field.py

### Verification
```bash
uv run pytest plugins/mission-control/tests/test_issue_risk_field.py
```

### Context library links
_none_
"""

F_CONDITIONAL = """### Inputs inventory
- plugins/mission-control/tests/test_issue_risk_field.py

### Failure modes / pre-mortem
If the Risk token is dropped, restore the field from issue_fields.

### Stop conditions
Stop if issue_fields.fields has no key risk.
"""

F_CITE_WHY = "The change is confined to a pin test."


def _risk_block(token: str, why: str = F_CITE_WHY) -> str:
    return f"### Risk\n{token}\n{why}\n"


def _f_valid(token: str) -> str:
    body = F_CORE.rstrip() + "\n\n" + _risk_block(token)
    if token in {"high", "very-high"}:
        body = body.rstrip() + "\n\n" + F_CONDITIONAL
    return body + "\n"


def _names_risk(messages: list[str]) -> bool:
    return any("Risk" in message for message in messages)


@pytest.fixture
def isolate_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    copy = tmp_path / "vendored-sdlc-schema.json"
    copy.write_bytes(VENDORED_SCHEMA.read_bytes())
    loaded = json.loads(copy.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    schema = cast(dict[str, Any], loaded)
    monkeypatch.setattr(sdlc_manager, "_VENDORED_SDLC_SCHEMA_PATH", copy)
    monkeypatch.setattr(sdlc_manager, "_resolve_sdlc_schema", lambda _path: schema)

    def _blocked_gh(*args: object, **kwargs: object) -> str:
        raise AssertionError(f"live GitHub call escaped: {args!r}")

    monkeypatch.setattr(sdlc_manager, "_gh", _blocked_gh)
    return schema


def _prepare(
    tmp_path: Path,
    source: str,
    *,
    risk: str | None,
    title: str = "t",
    labels: list[str] | None = None,
) -> Path:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="enhancement",
        team="campps",
        project="campps",
        source=source,
        title=title,
        status=None,
        risk=risk,
        mode=None,
        draft_dir=tmp_path,
        stage="Intake",
    )
    if labels is not None:
        text = draft.read_text(encoding="utf-8")
        draft.write_text(
            text.replace("labels: enhancement, needs-plan", "labels: " + ", ".join(labels)),
            encoding="utf-8",
        )
        sidecar_path = draft.with_suffix(".json")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["labels"] = labels
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    assert isinstance(draft, Path)
    return draft


def _sidecar(draft: Path) -> dict[str, Any]:
    loaded = json.loads(draft.with_suffix(".json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _mapped_config() -> dict[str, Any]:
    return {
        "project_mappings": {
            "projects": {
                "campps": {
                    "number": 4,
                    "name": "CAMPPS",
                    "repositories": ["hermes-claude-code-router"],
                }
            }
        }
    }


def _intake_exit_patches(draft: Path) -> dict[str, Any]:
    return {
        "config": patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        "labels": patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        "templates": patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        "create": patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=(
                "https://github.com/infiquetra/hermes-claude-code-router/issues/42",
                42,
            ),
        ),
        "item_exists": patch.object(
            sdlc_manager, "_prepared_project_item_exists", return_value=False
        ),
        "board": patch.object(sdlc_manager, "board_add"),
        "flow": patch.object(sdlc_manager, "flow_set_field"),
    }


def test_t1000_01_missing_risk_blocks_prepare_and_names_field(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    draft = _prepare(tmp_path / "none", F_CORE, risk=None)
    sidecar = _sidecar(draft)
    assert sidecar["state"] == "blocked"
    assert sidecar["readiness"]["passed"] is False
    assert _names_risk(sidecar["readiness"]["blocking_gaps"])

    valid, errors = sdlc_manager.validate_card_body_for_context(F_CORE, "enhancement", None)
    assert valid is False
    assert _names_risk(errors)

    seeded = _prepare(tmp_path / "seed", F_CORE, risk="medium")
    seeded_sidecar = _sidecar(seeded)
    assert seeded_sidecar["state"] == "blocked"
    assert seeded_sidecar["readiness"]["passed"] is False
    assert _names_risk(seeded_sidecar["readiness"]["blocking_gaps"])

    labeled = _prepare(
        tmp_path / "label",
        F_CORE,
        risk=None,
        labels=["enhancement", "needs-plan", "risk:medium"],
    )
    labeled_issue = sdlc_manager._read_prepared_issue(labeled)
    labeled_readiness = sdlc_manager._readiness_for_prepared_issue(labeled_issue)
    assert labeled_readiness.passed is False
    assert _names_risk(labeled_readiness.blocking_gaps)


def test_t1000_02_missing_risk_blocks_create_prepared(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    draft = _prepare(tmp_path, F_CORE, risk="medium", title="seeded missing Risk")
    patches = _intake_exit_patches(draft)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"] as mock_create,
        patches["item_exists"],
        patches["board"],
        patches["flow"],
        pytest.raises(RuntimeError, match="blocking readiness"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True, skip_approval=True)
    mock_create.assert_not_called()
    assert _sidecar(draft).get("state") != "post_create_pending"


@pytest.mark.parametrize("token", ("low", "medium", "high", "very-high"))
def test_t1000_03_valid_risk_tokens_pass(
    tmp_path: Path, isolate_schema: dict[str, Any], token: str
) -> None:
    body = _f_valid(token)
    valid, errors = sdlc_manager.validate_card_body_for_context(body, "enhancement", token)
    assert valid is True
    assert not _names_risk(errors)

    draft = _prepare(tmp_path, body, risk=None)
    sidecar = _sidecar(draft)
    assert sidecar["readiness"]["passed"] is True
    assert sidecar["risk"] == token
    assert f"### Risk\n{token}\n" in draft.read_text(encoding="utf-8")


def test_t1000_03_high_without_conditional_trio_fails_on_headers(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    body = F_CORE.rstrip() + "\n\n" + _risk_block("high")
    draft = _prepare(tmp_path, body, risk=None)
    sidecar = _sidecar(draft)
    assert sidecar["readiness"]["passed"] is False
    gaps = " ".join(sidecar["readiness"]["blocking_gaps"])
    assert "Inputs inventory" in gaps or "Failure modes" in gaps or "Stop conditions" in gaps


def test_t1000_04_unknown_creates_with_warning_and_refuses_active(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    body = (
        F_CORE.rstrip()
        + "\n\n"
        + _risk_block("UNKNOWN", "Architect has not yet assessed blast radius.")
    )
    valid, errors = sdlc_manager.validate_card_body_for_context(body, "enhancement", "UNKNOWN")
    assert valid is True or not _names_risk(errors)

    draft = _prepare(tmp_path, body, risk=None, title="unknown risk")
    sidecar = _sidecar(draft)
    issue = sdlc_manager._read_prepared_issue(draft)
    readiness = sdlc_manager._readiness_for_prepared_issue(issue)
    assert readiness.passed is True
    warning_blob = " ".join(readiness.warnings)
    assert "Risk" in warning_blob
    assert "UNKNOWN" in warning_blob
    assert "Architect" in warning_blob
    assert sidecar["readiness"]["passed"] is True

    patches = _intake_exit_patches(draft)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"] as mock_create,
        patches["item_exists"],
        patches["board"],
        patches["flow"],
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True, skip_approval=True)
    mock_create.assert_called_once()
    created_body = draft.read_text(encoding="utf-8")
    assert "### Risk" in created_body
    assert "UNKNOWN" in created_body

    gate = getattr(sdlc_manager, "planning_to_active_risk_ready", None)
    assert callable(gate), "Planning-to-Active Risk gate is not implemented"
    assert gate(created_body) is False


@pytest.mark.parametrize(
    "risk_section",
    (
        "### Risk\nLow operational risk.\n",
        "### Risk\nmedium\n",
        "### Risk\nextreme\nNot a vocabulary token.\n",
        "### Risk\n\n",
    ),
    ids=("asgard-prose", "no-justification", "unrecognized", "empty"),
)
def test_t1000_05_invalid_risk_format_is_blocked(
    tmp_path: Path, isolate_schema: dict[str, Any], risk_section: str
) -> None:
    body = F_CORE.rstrip() + "\n\n" + risk_section
    draft = _prepare(tmp_path, body, risk="medium")
    sidecar = _sidecar(draft)
    assert sidecar["state"] == "blocked"
    assert sidecar["readiness"]["passed"] is False
    assert _names_risk(sidecar["readiness"]["blocking_gaps"])
