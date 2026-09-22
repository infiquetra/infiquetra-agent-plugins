"""The acceptance gate for issue 1035, at the path the card names.

The card's two acceptance criteria are checked here end to end against a fake
client: the prepared-issue sidecar carries a type suggestion with a distribution
and a risk suggestion, and the labels union widens without ever narrowing.

The per-unit suites under ``plugins/mission-control/tests/`` remain the detailed
tests; this file is the card's own gate and deliberately repeats their happy
paths rather than replacing them.

Nothing here opens a socket, reads ``TYPESAFE_API_KEY``, or writes to the real
verdict log.

The card's first acceptance criterion is written without ``--team`` and
``--project``, which the prepare subparser has required since the prepared-issue
pipeline shipped, so the command as printed exits on an argparse error before any
suggestion code runs. ``test_the_cards_acceptance_command_runs_in_its_runnable_form``
runs the runnable form, and
``test_the_cards_acceptance_command_as_printed_is_refused_for_a_named_reason``
pins why the printed form is refused, so the correction cannot be lost.
"""

from __future__ import annotations

# ruff: noqa: E402,I001

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "mission-control" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SENTINEL_KEY = "SENTINEL-do-not-leak-ac1035"  # noqa: S105 - a test fixture, not a credential


def _load(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


client = _load(
    "typesafe_client_for_acceptance",
    "plugins/fleet-core/scripts/fleet_commons/typesafe_client.py",
)
jev_log = _load(
    "jev_log_for_acceptance",
    "plugins/fleet-core/scripts/fleet_commons/jev_log.py",
)

import sdlc_manager  # noqa: E402
import triage_suggest as ts  # noqa: E402


CARD_BODY = """### Objective
Add advisory triage suggestions to the prepared-issue path.

### Intent
An author picks an issue type from five with only a decision tree to help.
End-state: the draft records a typed judgment beside the author's own choice.

### Acceptance criteria
- [ ] The sidecar carries a type suggestion; `uv run pytest tests/test_mission_control_suggest.py -q` exits 0

### Out-of-scope / non-goals
- No auto-apply of any suggestion.

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
tests/test_mission_control_suggest.py

### Verification
```bash
uv run pytest tests/test_mission_control_suggest.py -q
```

### Risk
low
Suggestions land in a draft the operator already reviews before creation.

### Context library links
_none_
"""


ANSWERS = {
    ts.QUESTION_TYPE: {
        "type": "choice",
        "choice": "enhancement",
        "confidence": 0.82,
        "probabilities": {
            "capability": 0.05,
            "enhancement": 0.82,
            "defect": 0.08,
            "exploration": 0.02,
            "context-update": 0.03,
        },
    },
    ts.QUESTION_RISK: {"type": "score", "score": 0.3, "confidence": 0.71},
}


class _FakeResult:
    def __init__(self, status: str = "ok", answers: dict | None = None, note: str = "") -> None:
        self.status = status
        self.answers = dict(ANSWERS) if answers is None else answers
        self.note = note
        self.model = "jev-1.13.0"
        self.truncation = ()


def _ask(result: Any = None):
    def _fake(_state, _questions, **_kwargs):
        return result if result is not None else _FakeResult()

    return _fake


def _prepare(tmp_path: Path, source_file: Path, **overrides: Any) -> Path:
    """The card's first criterion, in its runnable form.

    `--team asgard --project operations` are added: both are required by the
    parser and relaxing them would change team and board routing for every
    prepared draft, which the card does not ask for.
    """
    kwargs: dict[str, Any] = {
        "repo": "infiquetra-claude-plugins",
        "issue_type": "defect",
        "team": "asgard",
        "project": "operations",
        "source": source_file.read_text(encoding="utf-8"),
        "title": "t",
        "status": None,
        "risk": None,
        "mode": None,
        "draft_dir": tmp_path / "drafts",
        "stage": "Intake",
        "suggest": True,
        "ask": _ask(),
        "suggest_client": client,
        "suggest_log": jev_log,
        "suggest_log_dir": tmp_path / "log",
    }
    kwargs.update(overrides)
    draft: Path = sdlc_manager.issue_prepare(**kwargs)
    return draft


@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "card.md"
    path.write_text(CARD_BODY, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Acceptance criterion 1 — the sidecar carries the suggestions
# --------------------------------------------------------------------------- #


def test_the_cards_acceptance_command_runs_in_its_runnable_form(tmp_path, source_file) -> None:
    draft = _prepare(tmp_path, source_file)
    sidecar = json.loads(draft.with_suffix(".json").read_text())

    type_suggestion = sidecar["type_suggestion"]
    assert type_suggestion["suggested"] == "enhancement"
    assert set(type_suggestion["distribution"]) == set(sdlc_manager._ISSUE_TYPES)
    assert sum(type_suggestion["distribution"].values()) == pytest.approx(1.0)

    risk_suggestion = sidecar["risk_suggestion"]
    assert risk_suggestion["suggested"] in sdlc_manager._RISK_TIER_VOCABULARY
    assert risk_suggestion["score"] == pytest.approx(0.3)


def test_the_authors_type_wins_and_the_disagreement_is_recorded(tmp_path, source_file) -> None:
    """Nothing auto-applies: `--type defect` stays the card's type."""
    draft = _prepare(tmp_path, source_file, issue_type="defect")
    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["issue_type"] == "defect"
    assert sidecar["type_suggestion"]["suggested"] == "enhancement"
    assert sidecar["type_suggestion"]["overridden"] is True


def test_the_cards_acceptance_command_as_printed_is_refused_for_a_named_reason() -> None:
    """The card omits two required flags; the parser refuses before any call."""
    result = subprocess.run(  # noqa: S603 - fixed interpreter, in-repo script
        [
            sys.executable,
            str(SCRIPTS / "sdlc_manager.py"),
            "issue",
            "prepare",
            "--repo",
            "infiquetra-claude-plugins",
            "--type",
            "defect",
            "--title",
            "t",
            "--suggest",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode != 0
    assert "--team" in result.stderr
    assert "--project" in result.stderr


# --------------------------------------------------------------------------- #
# Acceptance criterion 2 — the labels union widens and never narrows
# --------------------------------------------------------------------------- #


def test_the_labels_union_widens_and_keeps_every_rule_label(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sdlc_manager,
        "load_config",
        lambda: {
            "labels": {
                "auto_label_rules": {
                    "mentions_security": {
                        "pattern": r"security|vulnerability|CVE",
                        "add_labels": ["security"],
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        sdlc_manager,
        "_rest_get",
        lambda _path: {"title": "Security: a token outlives its session", "body": "detail"},
    )
    monkeypatch.setattr(
        sdlc_manager,
        "_rest_post",
        lambda *_a, **_k: pytest.fail("suggest mode must apply nothing"),
    )

    sdlc_manager.labels_auto_label(
        "infiquetra-claude-plugins",
        42,
        "text",
        suggest=True,
        ask=_ask(_FakeResult(answers={"performance": {"type": "noul", "noul": 0.93}})),
        suggest_client=client,
    )
    out = capsys.readouterr().out

    assert "security (rule)" in out
    assert "performance (model)" in out
    assert "nothing was applied" in out


def test_a_model_that_rejects_everything_still_leaves_the_rule_label(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sdlc_manager,
        "load_config",
        lambda: {
            "labels": {
                "auto_label_rules": {
                    "mentions_security": {
                        "pattern": r"security|vulnerability|CVE",
                        "add_labels": ["security"],
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        sdlc_manager,
        "_rest_get",
        lambda _path: {"title": "Security: a token outlives its session", "body": "detail"},
    )
    monkeypatch.setattr(
        sdlc_manager,
        "_rest_post",
        lambda *_a, **_k: pytest.fail("suggest mode must apply nothing"),
    )

    sdlc_manager.labels_auto_label(
        "infiquetra-claude-plugins",
        42,
        "text",
        suggest=True,
        ask=_ask(
            _FakeResult(
                answers={label: {"type": "noul", "noul": 0.0} for label in ts.CONTENT_LABELS}
            )
        ),
        suggest_client=client,
    )
    out = capsys.readouterr().out

    assert "security (rule)" in out


# --------------------------------------------------------------------------- #
# The card's third named expectation, and key safety
# --------------------------------------------------------------------------- #


def test_a_client_failure_leaves_the_draft_unchanged_with_a_note(tmp_path, source_file) -> None:
    plain = _prepare(tmp_path / "plain", source_file, suggest=False, ask=None)
    failed = _prepare(
        tmp_path / "failed",
        source_file,
        ask=_ask(_FakeResult(status="error", note="the endpoint refused")),
    )

    assert failed.read_bytes() == plain.read_bytes()
    sidecar = json.loads(failed.with_suffix(".json").read_text())
    assert sidecar["suggestions"] == {"status": "error", "note": "the endpoint refused"}
    assert "type_suggestion" not in sidecar


def test_the_key_appears_in_no_artefact_the_run_produced(
    tmp_path, source_file, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", SENTINEL_KEY)
    draft = _prepare(tmp_path, source_file)
    captured = capsys.readouterr()

    log = tmp_path / "log" / jev_log.VERDICT_FILENAME
    assert SENTINEL_KEY not in draft.read_text()
    assert SENTINEL_KEY not in draft.with_suffix(".json").read_text()
    assert SENTINEL_KEY not in log.read_text()
    assert SENTINEL_KEY not in captured.out
    assert SENTINEL_KEY not in captured.err
