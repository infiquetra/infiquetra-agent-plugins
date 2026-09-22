"""The team_profiles.yml validator must accept every live team's real config.

Proves the validator is calibrated to reality (orchestrator-no-token, headless
workers with no persona/token, voice fields, nested fallback_providers) and not
just a toy schema. Live fixtures live next to the golden harness fixtures.
"""

from __future__ import annotations

import pathlib

import pytest

from team_scaffold import profiles_validate

ROOT = pathlib.Path(__file__).resolve().parents[1] / "skills" / "team-scaffold"
FIXTURES = ROOT / "specs" / "fixtures" / "team_profiles"

PROFILE_FILES = sorted(FIXTURES.glob("team-*.yml"))


def test_have_all_twelve() -> None:
    assert len(PROFILE_FILES) == 12, (
        f"expected 12 live profile fixtures, found {len(PROFILE_FILES)}"
    )


@pytest.mark.parametrize("path", PROFILE_FILES, ids=lambda p: p.stem)
def test_live_profiles_validate_clean(path: pathlib.Path) -> None:
    errors, _warnings = profiles_validate.validate_file(path)
    assert errors == [], f"{path.name} produced validator ERRORS: {errors}"


def test_rejects_headless_with_token() -> None:
    data = {
        "hermes_team_profiles": [
            {
                "name": "w",
                "role": "worker",
                "model": "x",
                "headless": True,
                "discord_token_var": "vault_discord_bot_token_w",
            },
        ]
    }
    errors, _ = profiles_validate.validate_data(data)
    assert any("headless" in e for e in errors)


def test_rejects_bad_token_var() -> None:
    data = {
        "hermes_team_profiles": [
            {
                "name": "a",
                "role": "olympian_agent",
                "model": "x",
                "discord_token_var": "DISCORD_TOKEN_A",
            },
        ]
    }
    errors, _ = profiles_validate.validate_data(data)
    assert any("discord_token_var" in e for e in errors)


def test_requires_nonempty_list() -> None:
    errors, _ = profiles_validate.validate_data({"hermes_team_profiles": []})
    assert errors
