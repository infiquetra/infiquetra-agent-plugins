"""Tests for the per-user defaults file at ~/.claude/sdlc-defaults.json
and the first-run wizard `config init-defaults`."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


@pytest.fixture
def tmp_defaults_path(tmp_path, monkeypatch):
    """Redirect _USER_DEFAULTS_PATH into a tmp dir so tests don't write
    to the real ~/.claude/sdlc-defaults.json."""
    fake_path = tmp_path / ".claude" / "sdlc-defaults.json"
    monkeypatch.setattr(sdlc_manager, "_USER_DEFAULTS_PATH", fake_path)
    return fake_path


# --- Read-side -------------------------------------------------------------


def test_load_user_defaults_returns_empty_when_file_missing(tmp_defaults_path) -> None:
    assert sdlc_manager.load_user_defaults() == {}


def test_load_user_defaults_returns_dict_when_file_present(tmp_defaults_path) -> None:
    tmp_defaults_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_defaults_path.write_text('{"assignee": "namredips", "default_project": "mount-olympus"}')
    data = sdlc_manager.load_user_defaults()
    assert data == {"assignee": "namredips", "default_project": "mount-olympus"}


def test_load_user_defaults_tolerates_malformed_json(tmp_defaults_path, capsys) -> None:
    """Malformed JSON returns {} + warning — must not crash the CLI."""
    tmp_defaults_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_defaults_path.write_text("{ not-valid-json")
    data = sdlc_manager.load_user_defaults()
    assert data == {}
    captured = capsys.readouterr()
    assert "malformed" in (captured.out + captured.err).lower()


def test_load_user_defaults_tolerates_non_object_root(tmp_defaults_path) -> None:
    """File contains a list (not a dict) — return {} + warning, not crash."""
    tmp_defaults_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_defaults_path.write_text('["not", "an", "object"]')
    data = sdlc_manager.load_user_defaults()
    assert data == {}


def test_load_user_defaults_tolerates_unreadable_file(tmp_defaults_path, capsys) -> None:
    """If the file can't be opened (permissions, broken symlink, encoding
    issue), return {} + warning. The CLI must remain usable; the operator
    can re-run init-defaults to reseed."""
    tmp_defaults_path.parent.mkdir(parents=True, exist_ok=True)
    # Create with non-UTF-8 bytes so the open()/json.load chain raises
    # UnicodeDecodeError (caught by the widened except clause)
    tmp_defaults_path.write_bytes(b"\xff\xfe\xfd not valid utf-8")
    data = sdlc_manager.load_user_defaults()
    assert data == {}
    captured = capsys.readouterr()
    # Either warning text or stderr should mention the issue
    assert (
        "could not be read" in (captured.out + captured.err).lower()
        or "malformed" in (captured.out + captured.err).lower()
    )


def test_get_default_returns_None_when_unset(tmp_defaults_path) -> None:
    assert sdlc_manager.get_default("assignee") is None


def test_get_default_returns_value_when_set(tmp_defaults_path) -> None:
    tmp_defaults_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_defaults_path.write_text('{"assignee": "namredips"}')
    assert sdlc_manager.get_default("assignee") == "namredips"


# --- Write-side ------------------------------------------------------------


def test_save_user_defaults_creates_parent_dir(tmp_defaults_path) -> None:
    """First-run case: ~/.claude/ may not exist. save_user_defaults must
    create it rather than raising FileNotFoundError."""
    assert not tmp_defaults_path.parent.exists()
    sdlc_manager.save_user_defaults({"assignee": "namredips"})
    assert tmp_defaults_path.exists()
    assert json.loads(tmp_defaults_path.read_text()) == {"assignee": "namredips"}


def test_save_user_defaults_is_atomic(tmp_defaults_path) -> None:
    """Atomicity: a crash mid-write must not leave a partially-written file.
    Implementation uses tempfile + rename. We test by writing twice and
    confirming no .tmp file is left over."""
    tmp_defaults_path.parent.mkdir(parents=True, exist_ok=True)
    sdlc_manager.save_user_defaults({"assignee": "first"})
    sdlc_manager.save_user_defaults({"assignee": "second"})

    # Final state matches second write
    assert json.loads(tmp_defaults_path.read_text()) == {"assignee": "second"}

    # No .tmp leftover
    tmp_files = list(tmp_defaults_path.parent.glob("*.tmp"))
    assert tmp_files == [], f"Tempfile leftover: {tmp_files}"


def test_save_then_load_round_trips(tmp_defaults_path) -> None:
    payload = {
        "assignee": "namredips",
        "default_project": "mount-olympus",
        "default_status": "Backlog",
        "preferred_repos": ["campps-mvp", "mimir"],
    }
    sdlc_manager.save_user_defaults(payload)
    assert sdlc_manager.load_user_defaults() == payload


# --- First-run wizard (--non-interactive path) -----------------------------


def test_init_defaults_non_interactive_seeds_from_gh_login(tmp_defaults_path) -> None:
    """--non-interactive: no prompts, just auto-detected values.
    `assignee` comes from `gh api user --jq .login` (NOT $USER)."""
    with (
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="namredips"),
        patch.object(sdlc_manager, "load_config") as mock_cfg,
    ):
        mock_cfg.return_value = {
            "project_mappings": {"projects": {"mount-olympus": {"number": 1, "name": "Olympus"}}}
        }
        sdlc_manager.config_init_defaults(non_interactive=True, fmt="text")

    saved = json.loads(tmp_defaults_path.read_text())
    assert saved["assignee"] == "namredips"
    assert saved["default_project"] == "mount-olympus"  # auto-detected (single project)
    assert saved["default_status"] == "Backlog"
    assert saved["default_priority"] == "medium-priority"


def test_init_defaults_non_interactive_skips_unset_when_no_gh_login(
    tmp_defaults_path,
) -> None:
    """If `gh api user` fails (unauthenticated), assignee should NOT default
    to $USER or any string — it should be omitted so the operator notices."""
    with (
        patch.object(sdlc_manager, "_fetch_gh_login", return_value=None),
        patch.object(sdlc_manager, "load_config") as mock_cfg,
    ):
        mock_cfg.return_value = {"project_mappings": {"projects": {}}}
        sdlc_manager.config_init_defaults(non_interactive=True, fmt="text")

    saved = json.loads(tmp_defaults_path.read_text())
    assert "assignee" not in saved


def test_init_defaults_non_interactive_skips_default_project_with_multiple_projects(
    tmp_defaults_path,
) -> None:
    """Auto-detection of default_project ONLY fires when exactly 1 project
    is mapped. With 2+, the operator must choose; we don't guess."""
    with (
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="namredips"),
        patch.object(sdlc_manager, "load_config") as mock_cfg,
    ):
        mock_cfg.return_value = {
            "project_mappings": {
                "projects": {
                    "olympus": {"number": 1},
                    "strategic": {"number": 2},
                }
            }
        }
        sdlc_manager.config_init_defaults(non_interactive=True, fmt="text")

    saved = json.loads(tmp_defaults_path.read_text())
    assert "default_project" not in saved


# --- Wizard preserves existing values -------------------------------------


def test_init_defaults_preserves_existing_unrecognized_keys(tmp_defaults_path) -> None:
    """A future version of the script may add new defaults keys; an older
    script running --non-interactive must NOT clobber them."""
    tmp_defaults_path.parent.mkdir(parents=True, exist_ok=True)
    sdlc_manager.save_user_defaults(
        {
            "assignee": "namredips",
            "future_key_not_in_schema": "custom-value",
        }
    )
    with (
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="namredips"),
        patch.object(sdlc_manager, "load_config") as mock_cfg,
    ):
        mock_cfg.return_value = {"project_mappings": {"projects": {}}}
        sdlc_manager.config_init_defaults(non_interactive=True, fmt="text")

    saved = json.loads(tmp_defaults_path.read_text())
    assert saved["future_key_not_in_schema"] == "custom-value"
