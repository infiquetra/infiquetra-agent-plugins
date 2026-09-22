"""T1000-06..T1000-08: public flow repair-window verb (#1000)."""

# ruff: noqa: E402,I001

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
VENDORED_SCHEMA = PLUGIN_ROOT / "config" / "sdlc-schema.json"

F_CITE_FAIL = (
    "uv run pytest plugins/mission-control/tests/test_issue_risk_field.py"
    "::test_placeholder -q → 1 failed"
)
F_CITE_PASS = (
    "uv run pytest plugins/mission-control/tests/test_issue_risk_field.py"
    "::test_placeholder -q → 1 passed"
)

MARKER_PATH = (
    "work_hierarchy",
    "parent_stage_derivation",
    "parent_outcome_state",
    "own_verification_failed",
    "repair_window_encoding",
)


def _with_marker(schema: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(schema)
    cursor: dict[str, Any] = out
    for key in MARKER_PATH[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[key] = nxt
        cursor = nxt
    cursor[MARKER_PATH[-1]] = {
        "marker_kind": "label",
        "marker": "repair-window",
    }
    return out


def _without_marker(schema: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(schema)
    cursor: Any = out
    for key in MARKER_PATH[:-1]:
        if not isinstance(cursor, dict):
            return out
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            return out
        cursor = nxt
    cursor.pop(MARKER_PATH[-1], None)
    return out


def _with_marker_and_source(schema: dict[str, Any]) -> dict[str, Any]:
    out = _with_marker(schema)
    cursor: dict[str, Any] = out
    for key in MARKER_PATH[:-1]:
        nxt = cursor.get(key)
        assert isinstance(nxt, dict)
        cursor = nxt
    encoding = cursor[MARKER_PATH[-1]]
    assert isinstance(encoding, dict)
    encoding["marker_source"] = "config/labels.json"
    return out


@pytest.fixture
def isolate_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    copy_path = tmp_path / "vendored-sdlc-schema.json"
    copy_path.write_bytes(VENDORED_SCHEMA.read_bytes())
    loaded = json.loads(copy_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    schema = cast(dict[str, Any], loaded)
    monkeypatch.setattr(sdlc_manager, "_VENDORED_SDLC_SCHEMA_PATH", copy_path)

    def _blocked_gh(*args: object, **kwargs: object) -> str:
        raise AssertionError(f"live GitHub call escaped: {args!r}")

    monkeypatch.setattr(sdlc_manager, "_gh", _blocked_gh)
    return schema


def _repair_window():
    fn = getattr(sdlc_manager, "flow_repair_window", None)
    assert callable(fn), "public flow_repair_window verb is not implemented"
    return fn


def _install_verb_harness(
    monkeypatch: pytest.MonkeyPatch,
    schema: dict[str, Any],
    *,
    labels: list[str],
    labels_config: dict[str, Any] | None = None,
) -> dict[str, MagicMock]:
    config: dict[str, Any] = {
        "sdlc_schema": schema,
        "project_mappings": {"projects": {}},
    }
    if labels_config is not None:
        config["labels"] = labels_config
    monkeypatch.setattr(sdlc_manager, "_resolve_sdlc_schema", lambda _path: schema)
    monkeypatch.setattr(sdlc_manager, "load_config", lambda: config)
    graphql = MagicMock(return_value={})
    monkeypatch.setattr(sdlc_manager, "_graphql", graphql)
    add = MagicMock()
    remove = MagicMock()
    comment = MagicMock()
    verify = MagicMock()
    monkeypatch.setattr(sdlc_manager, "issue_label_add", add)
    monkeypatch.setattr(sdlc_manager, "issue_label_remove", remove)
    monkeypatch.setattr(sdlc_manager, "issue_comment", comment)
    monkeypatch.setattr(sdlc_manager, "flow_verify_label", verify)
    monkeypatch.setattr(sdlc_manager, "_get_item_labels", lambda *_a, **_k: list(labels))
    rest_post = MagicMock()
    rest_delete = MagicMock()
    monkeypatch.setattr(sdlc_manager, "_rest_post", rest_post)
    monkeypatch.setattr(sdlc_manager, "_rest_delete", rest_delete)
    return {
        "graphql": graphql,
        "add": add,
        "remove": remove,
        "comment": comment,
        "verify": verify,
        "rest_post": rest_post,
        "rest_delete": rest_delete,
    }


def _no_project_field_write(graphql: MagicMock) -> None:
    for call in graphql.call_args_list:
        query = call.args[0] if call.args else None
        assert query != sdlc_manager.QUERY_SET_FIELD_VALUE


def test_t1000_06_open_repair_window_with_failing_citation(
    tmp_path: Path, isolate_schema: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = _with_marker(isolate_schema)
    present: list[str] = []

    def _labels(*_a: object, **_k: object) -> list[str]:
        return list(present)

    harness = _install_verb_harness(monkeypatch, schema, labels=[])
    monkeypatch.setattr(sdlc_manager, "_get_item_labels", _labels)

    def _add(_repo: str, _number: int, label: str, fmt: str = "text") -> None:
        if label not in present:
            present.append(label)

    harness["add"].side_effect = _add
    fn = _repair_window()
    fn(
        repo="hermes-claude-code-router",
        number=42,
        action="open",
        citation=F_CITE_FAIL,
        fmt="json",
    )
    harness["add"].assert_called()
    assert any(call.args[2] == "repair-window" for call in harness["add"].call_args_list)
    harness["comment"].assert_called_once()
    comment_body = harness["comment"].call_args.args[2]
    assert "repair-window" in comment_body or "open" in comment_body.lower()
    assert F_CITE_FAIL in comment_body
    _no_project_field_write(harness["graphql"])

    harness["comment"].reset_mock()
    harness["add"].reset_mock()
    fn(
        repo="hermes-claude-code-router",
        number=42,
        action="open",
        citation=F_CITE_FAIL,
        fmt="json",
    )
    harness["comment"].assert_not_called()
    _no_project_field_write(harness["graphql"])


def test_t1000_07_close_repair_window_with_passing_citation(
    tmp_path: Path, isolate_schema: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = _with_marker(isolate_schema)
    present = ["repair-window"]
    harness = _install_verb_harness(monkeypatch, schema, labels=present)

    def _labels(*_a: object, **_k: object) -> list[str]:
        return list(present)

    def _remove(_repo: str, _number: int, label: str, fmt: str = "text") -> None:
        if label in present:
            present.remove(label)

    monkeypatch.setattr(sdlc_manager, "_get_item_labels", _labels)
    harness["remove"].side_effect = _remove
    fn = _repair_window()
    fn(
        repo="hermes-claude-code-router",
        number=42,
        action="close",
        citation=F_CITE_PASS,
        fmt="json",
    )
    harness["remove"].assert_called()
    assert any(call.args[2] == "repair-window" for call in harness["remove"].call_args_list)
    harness["comment"].assert_called_once()
    assert F_CITE_PASS in harness["comment"].call_args.args[2]
    _no_project_field_write(harness["graphql"])

    harness["comment"].reset_mock()
    harness["remove"].reset_mock()
    fn(
        repo="hermes-claude-code-router",
        number=42,
        action="close",
        citation=F_CITE_PASS,
        fmt="json",
    )
    harness["comment"].assert_not_called()
    _no_project_field_write(harness["graphql"])


@pytest.mark.parametrize("action", ("open", "close"))
@pytest.mark.parametrize("citation", (None, "", "   "))
def test_t1000_08_refuses_blank_citation_before_network(
    tmp_path: Path,
    isolate_schema: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    citation: str | None,
) -> None:
    schema = _with_marker(isolate_schema)
    harness = _install_verb_harness(monkeypatch, schema, labels=[])
    fn = _repair_window()
    with pytest.raises(RuntimeError, match="citation|result"):
        fn(
            repo="hermes-claude-code-router",
            number=42,
            action=action,
            citation=citation,
            fmt="json",
        )
    harness["add"].assert_not_called()
    harness["remove"].assert_not_called()
    harness["comment"].assert_not_called()
    harness["rest_post"].assert_not_called()
    harness["rest_delete"].assert_not_called()
    _no_project_field_write(harness["graphql"])


def test_t1000_08_refuses_schema_without_marker(
    tmp_path: Path, isolate_schema: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = _without_marker(isolate_schema)
    harness = _install_verb_harness(monkeypatch, schema, labels=[])
    fn = _repair_window()
    with pytest.raises(RuntimeError, match="too old"):
        fn(
            repo="hermes-claude-code-router",
            number=42,
            action="open",
            citation=F_CITE_FAIL,
            fmt="json",
        )
    harness["add"].assert_not_called()
    harness["comment"].assert_not_called()
    harness["verify"].assert_not_called()
    _no_project_field_write(harness["graphql"])


def test_t1000_08_marker_source_self_heals_label_definition(
    tmp_path: Path, isolate_schema: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = _with_marker_and_source(isolate_schema)
    labels_config = {
        "labels": [
            {
                "name": "repair-window",
                "color": "B60205",
                "description": "Own verification failed; repair window open",
            }
        ]
    }
    present: list[str] = []
    harness = _install_verb_harness(monkeypatch, schema, labels=[], labels_config=labels_config)
    monkeypatch.setattr(sdlc_manager, "_get_item_labels", lambda *_a, **_k: list(present))

    def _add(_repo: str, _number: int, label: str, fmt: str = "text") -> None:
        if label not in present:
            present.append(label)

    harness["add"].side_effect = _add
    fn = _repair_window()
    fn(
        repo="hermes-claude-code-router",
        number=42,
        action="open",
        citation=F_CITE_FAIL,
        fmt="json",
    )
    harness["verify"].assert_called_once()
    assert harness["verify"].call_args.args[0] == "hermes-claude-code-router"
    assert harness["verify"].call_args.args[1] == "repair-window"
    assert harness["verify"].call_args.args[2] == "B60205"
    assert harness["verify"].call_args.args[3] == ("Own verification failed; repair window open")
    harness["add"].assert_called()
    harness["comment"].assert_called_once()
    _no_project_field_write(harness["graphql"])
