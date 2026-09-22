"""T942-01..T942-10: Saga-owned readiness alignment (#942)."""

# ruff: noqa: E402,I001

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
VENDORED_SCHEMA = PLUGIN_ROOT / "config" / "sdlc-schema.json"
SAGA_OWNER_PATH = PLUGIN_ROOT.parent / "saga" / "scripts" / "handoff_envelope.py"

HANDOFF_MATURITIES = (
    "idea-ready",
    "requirements-ready",
    "plan-ready",
    "resume-ready",
    "deferred-context",
    "pending-confirmation",
)
LIVE_COMMAND_STATES = frozenset({"idea-ready", "requirements-ready", "plan-ready", "resume-ready"})

F_VALID_LOW = """### Objective
Align readiness.

### Intent
Cards must carry Saga-owned maturity.

### Acceptance criteria
- [ ] `uv run pytest plugins/mission-control/tests/test_saga_readiness_alignment.py` exits 0

### Out-of-scope / non-goals
- Do not invent a second parser

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_saga_readiness_alignment.py

### Verification
```bash
uv run pytest plugins/mission-control/tests/test_saga_readiness_alignment.py
```

### Context library links
_none_

### Risk
low
The change is confined to a pin test.
"""


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


def _load_saga_owner() -> ModuleType:
    if not SAGA_OWNER_PATH.is_file():
        pytest.skip(
            "saga's handoff_envelope.py is not in this catalog yet "
            f"({SAGA_OWNER_PATH}); these tests run when that plugin is present"
        )
    spec = importlib.util.spec_from_file_location("saga_handoff_owner", SAGA_OWNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assess_source():
    owner = _load_saga_owner()
    fn = getattr(owner, "assess_source", None)
    assert callable(fn), "Saga assess_source is not implemented"
    return owner, fn


def _assess_declared():
    owner = _load_saga_owner()
    fn = getattr(owner, "assess_declared", None)
    assert callable(fn), "Saga assess_declared is not implemented"
    return owner, fn


def _has_live_route(text: str) -> bool:
    return "/plan" in text or "/work" in text


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _brainstorm_pending(root: Path) -> Path:
    return _write(
        root,
        "docs/brainstorms/2026-09-13-alignment-boundary.md",
        "---\n"
        "topic: alignment-boundary\n"
        "date: 2026-09-13\n"
        "maturity: pending-confirmation\n"
        "---\n\n"
        "# Alignment boundary\n\n"
        "Proposed scope only. Not confirmed.\n",
    )


def _draft_bare(root: Path) -> Path:
    path = _write(
        root,
        "docs/sdlc-issue-drafts/2026-09-13-bare-draft.md",
        F_VALID_LOW,
    )
    sidecar = path.with_suffix(".json")
    sidecar.write_text(json.dumps({"title": "bare draft"}), encoding="utf-8")
    return path


def _state_bare(root: Path) -> Path:
    _draft_bare(root)
    return _write(
        root,
        ".claude/saga/state.json",
        json.dumps(
            {"current_work": {"plan_path": "docs/sdlc-issue-drafts/2026-09-13-bare-draft.md"}}
        ),
    )


def _declared_markdown(root: Path, folder: str, name: str, state: str) -> Path:
    return _write(
        root,
        f"{folder}/{name}",
        f"---\ndate: 2026-09-13\nmaturity: {state}\n---\n\n# Declared\n",
    )


def _declared_draft(root: Path, state: str) -> Path:
    path = _write(
        root,
        "docs/sdlc-issue-drafts/declared.md",
        f"---\nhandoff_maturity: {state}\n---\n\n# Draft\n",
    )
    path.with_suffix(".json").write_text(json.dumps({"handoff_maturity": state}), encoding="utf-8")
    return path


def _maturity_of(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    return str(getattr(obj, "maturity", getattr(obj, "inferred_maturity", "")))


def _next_action_of(obj: Any) -> str:
    return str(getattr(obj, "next_action", "") or "")


def _incomplete_vocab_assess_declared(
    value: object, _published: object, *, declaration_required: bool = False
) -> SimpleNamespace:
    token = str(value)
    if token == "idea-ready":
        return SimpleNamespace(maturity="idea-ready")
    return SimpleNamespace(maturity=f"unknown:unrecognized:{token}")


def test_t942_01_pending_confirmation_stays_pending_confirmation(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    path = _brainstorm_pending(tmp_path)
    rel = "docs/brainstorms/2026-09-13-alignment-boundary.md"
    owner, assess = _assess_source()
    saga = assess(rel, tmp_path)
    assert _maturity_of(saga) == "pending-confirmation"
    assert _has_live_route(_next_action_of(saga)) is False

    artifact = sdlc_manager.resolve_source_artifact(rel, tmp_path)
    assert artifact.inferred_maturity == "pending-confirmation"
    assert Path(path).is_file()

    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="enhancement",
        team="campps",
        project="campps",
        source=F_VALID_LOW,
        title="pending confirmation card",
        status=None,
        risk=None,
        mode=None,
        draft_dir=tmp_path / "drafts",
        stage="Intake",
        source_artifact=artifact,
        handoff_maturity=None,
    )
    sidecar = json.loads(draft.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["handoff_maturity"] == "pending-confirmation"
    text = draft.read_text(encoding="utf-8")
    assert "pending-confirmation" in text
    assert "requirements-ready" not in text.split("### Handoff maturity", 1)[-1][:80]
    assert _has_live_route(text) is False


def test_t942_02_bare_draft_is_undeclared_and_writes_no_draft(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    _draft_bare(tmp_path)
    rel = "docs/sdlc-issue-drafts/2026-09-13-bare-draft.md"
    owner, assess = _assess_source()
    saga = assess(rel, tmp_path)
    maturity = _maturity_of(saga)
    assert maturity.startswith("unknown:undeclared:")
    assert "resume-ready" not in maturity
    assert "requirements-ready" not in maturity
    assert "draft" in str(getattr(saga, "diagnostic", "")).lower() or "draft" in maturity

    draft_dir = tmp_path / "out"
    draft_dir.mkdir()
    with pytest.raises(RuntimeError, match="undeclared|dependenc|draft"):
        sdlc_manager.issue_prepare(
            repo="hermes-claude-code-router",
            issue_type="enhancement",
            team="campps",
            project="campps",
            source=F_VALID_LOW,
            title="bare draft",
            status=None,
            risk=None,
            mode=None,
            draft_dir=draft_dir,
            stage="Intake",
            source_artifact=sdlc_manager.resolve_source_artifact(rel, tmp_path),
        )
    assert list(draft_dir.glob("*.md")) == []


def test_t942_03_bare_state_is_undeclared_and_writes_no_draft(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    _state_bare(tmp_path)
    rel = ".claude/saga/state.json"
    owner, assess = _assess_source()
    saga = assess(rel, tmp_path)
    maturity = _maturity_of(saga)
    assert maturity.startswith("unknown:undeclared:")
    assert "resume-ready" not in maturity
    assert "requirements-ready" not in maturity

    draft_dir = tmp_path / "out"
    draft_dir.mkdir()
    with pytest.raises(RuntimeError, match="undeclared|dependenc|saga"):
        sdlc_manager.issue_prepare(
            repo="hermes-claude-code-router",
            issue_type="enhancement",
            team="campps",
            project="campps",
            source=F_VALID_LOW,
            title="bare state",
            status=None,
            risk=None,
            mode=None,
            draft_dir=draft_dir,
            stage="Intake",
            source_artifact=sdlc_manager.resolve_source_artifact(rel, tmp_path),
        )
    assert list(draft_dir.glob("*.md")) == []


@pytest.mark.parametrize("state", HANDOFF_MATURITIES)
@pytest.mark.parametrize(
    "folder",
    ("docs/brainstorms", "docs/plans", "docs/sdlc-issue-drafts"),
)
def test_t942_04_declared_state_overrides_folder(
    tmp_path: Path, isolate_schema: dict[str, Any], state: str, folder: str
) -> None:
    if folder == "docs/sdlc-issue-drafts":
        path = _declared_draft(tmp_path, state)
        rel = path.relative_to(tmp_path).as_posix()
    else:
        path = _declared_markdown(tmp_path, folder, "declared.md", state)
        rel = path.relative_to(tmp_path).as_posix()
    owner, assess = _assess_source()
    saga = assess(rel, tmp_path)
    assert _maturity_of(saga) == state
    artifact = sdlc_manager.resolve_source_artifact(rel, tmp_path)
    assert artifact.inferred_maturity == state
    assert _has_live_route(_next_action_of(saga)) is (state in LIVE_COMMAND_STATES)


def test_t942_05_out_of_root_is_refused(tmp_path: Path, isolate_schema: dict[str, Any]) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("---\nmaturity: requirements-ready\n---\n\n# Outside\n", encoding="utf-8")
    twin = tmp_path / "docs" / "brainstorms" / "ghost.md"
    twin.parent.mkdir(parents=True, exist_ok=True)
    twin.write_text("# No declaration\n", encoding="utf-8")
    escape = tmp_path / "docs" / "brainstorms" / "escape.md"
    escape.symlink_to(outside)
    outside_twin = tmp_path.parent / "docs" / "brainstorms" / "ghost.md"
    outside_twin.parent.mkdir(parents=True, exist_ok=True)
    outside_twin.write_text(
        "---\nmaturity: requirements-ready\n---\n\n# Outside twin\n",
        encoding="utf-8",
    )

    owner, assess = _assess_source()
    cases = (
        str(outside),
        "../" + outside.name,
        "docs/brainstorms/escape.md",
        str(outside_twin),
    )
    for source in cases:
        saga = assess(source, tmp_path)
        maturity = _maturity_of(saga)
        assert maturity.startswith("unknown:out-of-root:"), source
        assert _has_live_route(_next_action_of(saga)) is False
        with pytest.raises(RuntimeError, match="out-of-root|refus|dependenc"):
            sdlc_manager.resolve_source_artifact(source, tmp_path)


def test_t942_06_explicit_choices_preserve_source_identity(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    twin = _write(
        tmp_path,
        "docs/brainstorms/selected-twin.md",
        "---\nmaturity: plan-ready\n---\n\n# Twin\n",
    )
    owner, assess = _assess_source()
    twin_rel = "docs/brainstorms/selected-twin.md"
    saga = assess(twin_rel, tmp_path)
    assert getattr(saga, "published_source", None) == twin_rel
    assert _maturity_of(saga) == "plan-ready"
    artifact = sdlc_manager.resolve_source_artifact(twin_rel, tmp_path)
    assert artifact.ref == twin_rel
    assert artifact.path == twin_rel
    assert twin.is_file()

    payload = {
        "title": "Issue handoff",
        "body": "Issue body",
        "url": "https://github.com/infiquetra/home-lab/issues/42",
    }
    url = "https://github.com/infiquetra/home-lab/issues/42"
    with patch.object(sdlc_manager, "_gh", return_value=json.dumps(payload)):
        url_artifact = sdlc_manager.resolve_source_artifact(url)
    assert url_artifact.ref == url or url_artifact.url == url
    _owner, assess_declared = _assess_declared()
    declared = assess_declared(url_artifact.inferred_maturity, url, declaration_required=False)
    assert getattr(declared, "published_source", url) in {url, url_artifact.ref}

    def fake_git(args: list[str], cwd: Path) -> str:
        if args[:2] == ["git", "rev-parse"] and args[-1] == "feature/test":
            return "abc123"
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return "origin/feature/test"
        if args[:2] == ["git", "status"]:
            return "## feature/test"
        raise AssertionError(args)

    with patch.object(sdlc_manager, "_run_git_command", side_effect=fake_git):
        branch_artifact = sdlc_manager.resolve_source_artifact("branch:feature/test", tmp_path)
    assert branch_artifact.branch == "feature/test"


def test_t942_07_missing_saga_is_a_dependency_diagnostic(
    tmp_path: Path, isolate_schema: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _brainstorm_pending(tmp_path)
    # The script loads its bundled module by path under a unique name, so the
    # patch has to land on that very module object, not on a bare-name import.
    plugin_resolution = sdlc_manager._load_bundled("plugin_resolution")

    def _missing_saga(*_args: object, **_kwargs: object) -> tuple[Path, int]:
        raise FileNotFoundError("saga plugin not installed")

    monkeypatch.setattr(plugin_resolution, "resolve_plugin_root", _missing_saga)
    draft_dir = tmp_path / "out"
    draft_dir.mkdir()
    with pytest.raises(RuntimeError, match="[Ss]aga|dependenc"):
        sdlc_manager.issue_prepare(
            repo="hermes-claude-code-router",
            issue_type="enhancement",
            team="campps",
            project="campps",
            source=F_VALID_LOW,
            title="needs saga",
            status=None,
            risk=None,
            mode=None,
            draft_dir=draft_dir,
            stage="Intake",
            source_artifact=sdlc_manager.resolve_source_artifact(
                "docs/brainstorms/2026-09-13-alignment-boundary.md", tmp_path
            ),
        )
    assert list(draft_dir.glob("*.md")) == []

    monkeypatch.setattr(
        sdlc_manager,
        "load_config",
        lambda: {
            "sdlc_schema": isolate_schema,
            "project_mappings": {
                "projects": {
                    "campps": {
                        "number": 4,
                        "name": "CAMPPS",
                        "repositories": [],
                    }
                }
            },
        },
    )
    monkeypatch.setattr(sdlc_manager, "get_project_items", lambda *_a, **_k: ("P", []))
    sdlc_manager.board_view("campps", None, "json")


@pytest.mark.parametrize(
    "owner",
    (
        SimpleNamespace(),
        SimpleNamespace(READINESS_CONTRACT_MAJOR=0, assess_source=lambda *_a, **_k: None),
        SimpleNamespace(
            READINESS_CONTRACT_MAJOR=1,
            HANDOFF_MATURITIES=("idea-ready",),
            assess_source=lambda *_a, **_k: None,
            assess_declared=_incomplete_vocab_assess_declared,
        ),
    ),
    ids=("missing-contract", "wrong-major", "incomplete-vocab"),
)
def test_t942_08_incompatible_saga_is_a_dependency_diagnostic(
    tmp_path: Path,
    isolate_schema: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    owner: SimpleNamespace,
) -> None:
    _brainstorm_pending(tmp_path)
    loader = getattr(sdlc_manager, "_load_saga_readiness_owner", None)
    assert callable(loader), "Saga owner loader is not implemented"
    monkeypatch.setattr(sdlc_manager, "_load_saga_readiness_owner", lambda: owner)
    draft_dir = tmp_path / "out"
    draft_dir.mkdir()
    with pytest.raises(RuntimeError, match="incompatib|[Ss]aga|dependenc|contract"):
        sdlc_manager.issue_prepare(
            repo="hermes-claude-code-router",
            issue_type="enhancement",
            team="campps",
            project="campps",
            source=F_VALID_LOW,
            title="incompatible saga",
            status=None,
            risk=None,
            mode=None,
            draft_dir=draft_dir,
            stage="Intake",
            source_artifact=sdlc_manager.resolve_source_artifact(
                "docs/brainstorms/2026-09-13-alignment-boundary.md", tmp_path
            ),
        )
    assert list(draft_dir.glob("*.md")) == []


def test_t942_09_malformed_and_unknown_declarations_fail_closed(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    cases = {
        "bogus.md": "---\nmaturity: bogus-value\n---\n\n# Bogus\n",
        "dup.md": ("---\nmaturity: pending-confirmation\nmaturity: plan-ready\n---\n\n# Dup\n"),
        "carrier.md": "maturity: plan-ready\n\n# Carrier\n",
        "open.md": "---\nmaturity: plan-ready\n",
        "blank.md": "---\nmaturity:\n---\n\n# Blank\n",
    }
    owner, assess = _assess_source()
    for name, text in cases.items():
        rel = f"docs/brainstorms/{name}"
        _write(tmp_path, rel, text)
        saga = assess(rel, tmp_path)
        maturity = _maturity_of(saga)
        assert maturity == "" or maturity.startswith("unknown:"), name
        assert _has_live_route(_next_action_of(saga)) is False
        draft_dir = tmp_path / f"out-{name}"
        draft_dir.mkdir()
        with pytest.raises(RuntimeError, match="unknown|blank|unrecognized|carrier|undeclared"):
            sdlc_manager.issue_prepare(
                repo="hermes-claude-code-router",
                issue_type="enhancement",
                team="campps",
                project="campps",
                source=F_VALID_LOW,
                title=name,
                status=None,
                risk=None,
                mode=None,
                draft_dir=draft_dir,
                stage="Intake",
                source_artifact=sdlc_manager.resolve_source_artifact(rel, tmp_path),
            )
        assert list(draft_dir.glob("*.md")) == []

    unreadable = tmp_path / "docs" / "brainstorms" / "binary.md"
    unreadable.parent.mkdir(parents=True, exist_ok=True)
    unreadable.write_bytes(b"\xff\xfe\xfd\xfc\xfb")
    saga = assess("docs/brainstorms/binary.md", tmp_path)
    assert _maturity_of(saga).startswith("unknown:")
    assert _has_live_route(_next_action_of(saga)) is False
    draft_dir = tmp_path / "out-binary.md"
    draft_dir.mkdir()
    with pytest.raises((RuntimeError, UnicodeDecodeError), match="unknown|utf-8|codec|unreadable"):
        sdlc_manager.issue_prepare(
            repo="hermes-claude-code-router",
            issue_type="enhancement",
            team="campps",
            project="campps",
            source=F_VALID_LOW,
            title="binary.md",
            status=None,
            risk=None,
            mode=None,
            draft_dir=draft_dir,
            stage="Intake",
            source_artifact=sdlc_manager.resolve_source_artifact(
                "docs/brainstorms/binary.md", tmp_path
            ),
        )
    assert list(draft_dir.glob("*.md")) == []


def test_t942_10_no_local_parser_and_entry_points_agree(
    tmp_path: Path, isolate_schema: dict[str, Any]
) -> None:
    source = Path(sdlc_manager.__file__).read_text(encoding="utf-8")
    assert "_HANDOFF_MATURITY_CHOICES" not in source
    assert "_infer_maturity_from_path" not in source
    assert not hasattr(sdlc_manager, "_HANDOFF_MATURITY_CHOICES")

    owner, assess = _assess_source()
    resolvable: list[str] = []
    refused: list[str] = []

    pending = _brainstorm_pending(tmp_path)
    resolvable.append(pending.relative_to(tmp_path).as_posix())
    for folder, name, state in (
        ("docs/brainstorms", "idea.md", "idea-ready"),
        ("docs/plans", "plan.md", "plan-ready"),
        ("docs/brainstorms", "deferred.md", "deferred-context"),
        ("docs/brainstorms", "pending.md", "pending-confirmation"),
    ):
        path = _declared_markdown(tmp_path, folder, name, state)
        resolvable.append(path.relative_to(tmp_path).as_posix())
    resolvable.append(_declared_draft(tmp_path, "resume-ready").relative_to(tmp_path).as_posix())
    twin = _write(
        tmp_path,
        "docs/brainstorms/selected-twin.md",
        "---\nmaturity: plan-ready\n---\n\n# Twin\n",
    )
    resolvable.append(twin.relative_to(tmp_path).as_posix())

    _draft_bare(tmp_path)
    refused.append("docs/sdlc-issue-drafts/2026-09-13-bare-draft.md")
    _write(tmp_path, "docs/brainstorms/bogus.md", "---\nmaturity: bogus-value\n---\n\n# Bogus\n")
    refused.append("docs/brainstorms/bogus.md")
    _write(tmp_path, "docs/brainstorms/blank.md", "---\nmaturity:\n---\n\n# Blank\n")
    refused.append("docs/brainstorms/blank.md")
    outside = tmp_path.parent / f"{tmp_path.name}-t942-10-outside.md"
    outside.write_text("---\nmaturity: requirements-ready\n---\n\n# Out\n", encoding="utf-8")
    refused.append(str(outside))

    for rel in resolvable:
        saga = assess(rel, tmp_path)
        artifact = sdlc_manager.resolve_source_artifact(rel, tmp_path)
        assert artifact.inferred_maturity == _maturity_of(saga), rel
        assert artifact.ref == getattr(saga, "published_source", artifact.ref), rel
        assert _has_live_route(_next_action_of(saga)) is (
            _maturity_of(saga) in LIVE_COMMAND_STATES
        ), rel

    for rel in refused:
        saga = assess(rel, tmp_path)
        assert _maturity_of(saga) == "" or _maturity_of(saga).startswith("unknown:"), rel
        assert _has_live_route(_next_action_of(saga)) is False, rel
        with pytest.raises((RuntimeError, UnicodeDecodeError)):
            sdlc_manager.resolve_source_artifact(rel, tmp_path)
