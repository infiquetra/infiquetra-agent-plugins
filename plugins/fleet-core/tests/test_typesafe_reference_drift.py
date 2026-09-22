"""Drift guard binding the data-rule document to the code that enforces it.

``plugins/fleet-core/references/typesafe.md`` states the redaction placeholder,
the verdict-record fields, the entropy threshold, the log location and the band
defaults.  Without this guard the pattern set could change in the client and
leave the document describing a rule the code no longer applies -- a policy
document that quietly stops being true is worse than none, because people act on
it.  Same posture as the version pin's guard.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE = REPO_ROOT / "plugins/fleet-core/references/typesafe.md"
FLEET_COMMONS = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons"


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, FLEET_COMMONS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tc = _load("typesafe_client_for_reference_drift", "typesafe_client.py")
log = _load("jev_log_for_reference_drift", "jev_log.py")
ev = _load("jev_eval_for_reference_drift", "jev_eval.py")

DOC = REFERENCE.read_text(encoding="utf-8")


def test_the_reference_exists() -> None:
    assert REFERENCE.is_file()


def test_the_redaction_placeholder_matches_the_code() -> None:
    assert f"`{tc.REDACTION_PLACEHOLDER}`" in DOC


def test_the_entropy_threshold_matches_the_code() -> None:
    assert str(tc.ENTROPY_MIN_RUN) in DOC
    assert f"{tc.ENTROPY_MIN_BITS}" in DOC


def test_the_key_environment_variable_is_named() -> None:
    assert tc.KEY_ENV in DOC
    assert tc.TRANSPORT_ENV in DOC


def test_every_verdict_field_is_documented() -> None:
    fields = {
        "kind",
        "decision_id",
        "state_hash",
        "questions_hash",
        "answer",
        "confidence",
        "threshold",
        "resolved_model",
        "label",
        "at",
        "verdict_hash",
    }
    for name in fields:
        assert f"`{name}`" in DOC, f"the verdict field {name!r} is not described in the reference"


def test_the_verdict_record_carries_exactly_the_documented_fields(tmp_path) -> None:
    record = log.record_verdict(
        decision_id="d",
        state={"x": 1},
        questions={"q": {"type": "noul"}},
        answer={"type": "noul", "noul": 0.9},
        confidence=None,
        threshold=0.6,
        resolved_model="jev-1.13.0",
        directory=tmp_path,
    )
    documented = {
        "kind",
        "decision_id",
        "state_hash",
        "questions_hash",
        "answer",
        "confidence",
        "threshold",
        "resolved_model",
        "label",
        "at",
        "verdict_hash",
    }
    assert set(record) == documented


def test_the_log_location_matches_the_code() -> None:
    assert log.LOG_DIR_ENV in DOC
    assert "~/.claude/typesafe/" in DOC
    assert log.VERDICT_FILENAME in DOC


def test_the_documented_bands_match_the_defaults() -> None:
    lows = [str(low) for low, _high, _name in ev.DEFAULT_BANDS]
    assert "0.6" in DOC and "0.8" in DOC
    assert lows == ["0.0", "0.6", "0.8"]


def test_the_documented_secret_key_names_are_all_recognized() -> None:
    for name in (
        "api_key",
        "secret",
        "token",
        "password",
        "credential",
        "private_key",
        "authorization",
    ):
        assert f"`{name}`" in DOC
        assert tc.names_a_secret(name), f"the reference claims {name!r} is redacted, but it is not"
