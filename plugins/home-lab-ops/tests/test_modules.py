"""Unit tests for vault_wire, inventory_register, and repo_stamp."""

from __future__ import annotations

import os
import pathlib

import pytest

from team_scaffold import inventory_register, repo_stamp, vault_wire
from team_scaffold.spec import from_dict

# ---------------------------------------------------------------- vault_wire

SRC_VAULT = """\
---
# preamble
vault_discord_bot_token_zeus: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  3938383939
vault_discord_bot_token_athena: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  6161616262
vault_unrelated: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ccccdddd
"""


def test_parse_blocks_roundtrip():
    blocks = vault_wire.parse_blocks(SRC_VAULT)
    assert set(blocks) >= {"vault_discord_bot_token_zeus", "vault_discord_bot_token_athena"}
    # block is copied verbatim, including the encrypted body lines
    assert "3938383939" in blocks["vault_discord_bot_token_zeus"]


def test_copy_blocks_verbatim_and_idempotent(tmp_path: pathlib.Path):
    src = tmp_path / "all.yml"
    src.write_text(SRC_VAULT)
    target = tmp_path / "team" / "vault.yml"

    added = vault_wire.copy_blocks_from(src, target, ["vault_discord_bot_token_zeus"])
    assert added == ["vault_discord_bot_token_zeus"]
    assert "3938383939" in target.read_text()
    assert "vault_unrelated" not in target.read_text()

    # second run is a no-op (idempotent)
    added2 = vault_wire.copy_blocks_from(src, target, ["vault_discord_bot_token_zeus"])
    assert added2 == []


def test_copy_blocks_missing_var_raises(tmp_path: pathlib.Path):
    src = tmp_path / "all.yml"
    src.write_text(SRC_VAULT)
    with pytest.raises(KeyError):
        vault_wire.copy_blocks_from(src, tmp_path / "v.yml", ["vault_nope"])


def test_append_encrypted_block(tmp_path: pathlib.Path):
    target = tmp_path / "vault.yml"
    block = "vault_discord_bot_token_nyx: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n  abcd1234\n"
    assert vault_wire.append_encrypted_block(target, "vault_discord_bot_token_nyx", block)
    assert "abcd1234" in target.read_text()
    # idempotent
    assert not vault_wire.append_encrypted_block(target, "vault_discord_bot_token_nyx", block)


# ----------------------------------------------------- inventory_register

HOSTS = """\
all:
  children:
    proxmox_hosts:
      hosts:
        node-a.example.com:
          ansible_host: 192.0.2.7

agent_vms:
  hosts:
    app-one.example.com:
      ansible_host: 192.0.2.50
      ansible_user: agent
    # a comment inside the group
    app-two.example.com:
      ansible_host: 192.0.2.51
      ansible_user: agent

mac_minis:
  hosts:
    workstation.example.com:
      ansible_host: 192.0.2.196
      ansible_user: operator
"""


def test_add_host_appends_under_group_and_preserves_comments():
    new, changed = inventory_register.add_host(
        HOSTS,
        "agent_vms",
        "guest.example.com",
        {"ansible_host": "192.0.2.71", "ansible_user": "agent"},
    )
    assert changed
    assert "# a comment inside the group" in new  # comments survive
    # new host lands inside agent_vms, before the mac_minis group
    agent_block = new.split("mac_minis:")[0]
    assert "guest.example.com:" in agent_block
    assert "192.0.2.71" in agent_block
    # mac_minis untouched
    assert new.count("workstation.example.com:") == 1


def test_add_host_idempotent():
    new, changed = inventory_register.add_host(
        HOSTS,
        "agent_vms",
        "app-one.example.com",
        {"ansible_host": "192.0.2.50", "ansible_user": "agent"},
    )
    assert not changed
    assert new == HOSTS


def test_add_host_unknown_group_raises():
    with pytest.raises(inventory_register.InventoryError):
        inventory_register.add_host(HOSTS, "nope_group", "x", {})


def test_register_dryrun_does_not_write(tmp_path: pathlib.Path):
    f = tmp_path / "hosts.yml"
    f.write_text(HOSTS)
    changed, diff = inventory_register.register(
        f,
        "mac_minis",
        "extra.example.com",
        {"ansible_host": "192.0.2.197", "ansible_user": "operator"},
        apply=False,
    )
    assert changed and diff
    assert f.read_text() == HOSTS  # unchanged on dry-run
    changed2, _ = inventory_register.register(
        f,
        "mac_minis",
        "extra.example.com",
        {"ansible_host": "192.0.2.197", "ansible_user": "operator"},
        apply=True,
    )
    assert changed2 and "extra.example.com:" in f.read_text()


# ------------------------------------------------------------- repo_stamp

_CONTEXT_LIBRARY = os.environ.get("INFIQUETRA_CONTEXT_LIBRARY")
CL = pathlib.Path(_CONTEXT_LIBRARY).expanduser() if _CONTEXT_LIBRARY else pathlib.Path("/nonexistent")


@pytest.mark.skipif(
    not _CONTEXT_LIBRARY or not CL.exists(),
    reason="INFIQUETRA_CONTEXT_LIBRARY is unset or is not a directory",
)
def test_stamp_new_single_profile_team(tmp_path: pathlib.Path):
    spec = from_dict(
        {
            "team": {
                "name": "nyx",
                "display": "Nyx (night monitor)",
                "host_group": "agent_vms",
                "limit_host": "nyx.infiquetra.com",
                "pin_runtime": False,
                "coresident": None,
                "roles": [
                    {"role": "ollama", "tags": "ollama,nyx"},
                    {"role": "hermes", "tags": "hermes,nyx"},
                    {"role": "hermes_dm_listener", "tags": "dm_listener,nyx"},
                ],
            },
            "profiles": [
                {
                    "name": "nyx",
                    "persona": "nyx",
                    "discord_token_var": "vault_discord_bot_token_nyx",
                }
            ],
        }
    )
    created = repo_stamp.stamp(spec, tmp_path, CL)
    assert created
    # archetype-required artifacts exist
    for rel in (
        "README.md",
        "AGENTS.md",
        ".gitignore",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "identity/README.md",
        "orchestration/README.md",
        "profiles/nyx/SOUL.md",
        "profiles/nyx/skills/.gitkeep",
        "profiles/nyx/config.yaml",
        "profiles/nyx/distribution.yaml",
        "deploy/nyx.yml",
        "deploy/requirements.yml",
        "deploy/README.md",
        "deploy/inventory.example.yml",
        "deploy/shared-infra-vault.example.yml",
        "deploy/team_profiles.yml",
        "docs/engineering-journal/LEARNINGS.md",
    ):
        assert (tmp_path / rel).exists(), f"missing {rel}"
    # identity records the token var NAME, never a secret value
    ident = (tmp_path / "identity/README.md").read_text()
    assert "vault_discord_bot_token_nyx" in ident
    # generated harness matches harness_gen exactly
    from team_scaffold import harness_gen

    assert (tmp_path / "deploy/nyx.yml").read_text() == harness_gen.render_harness(spec.as_cfg())[
        "nyx.yml"
    ]
    # the stamped team_profiles.yml validates
    from team_scaffold import profiles_validate

    errors, _ = profiles_validate.validate_file(tmp_path / "deploy/team_profiles.yml")
    assert errors == []


@pytest.mark.skipif(
    not _CONTEXT_LIBRARY or not CL.exists(),
    reason="INFIQUETRA_CONTEXT_LIBRARY is unset or is not a directory",
)
def test_stamp_is_idempotent(tmp_path: pathlib.Path):
    spec = from_dict(
        {
            "team": {
                "name": "nyx",
                "display": "Nyx",
                "host_group": "agent_vms",
                "limit_host": "nyx.infiquetra.com",
                "roles": [
                    {"role": "ollama", "tags": "ollama,nyx"},
                    {"role": "hermes", "tags": "hermes,nyx"},
                ],
            },
            "profiles": [
                {
                    "name": "nyx",
                    "persona": "nyx",
                    "discord_token_var": "vault_discord_bot_token_nyx",
                }
            ],
        }
    )
    repo_stamp.stamp(spec, tmp_path, CL)
    second = repo_stamp.stamp(spec, tmp_path, CL)
    assert second == []  # nothing re-created


@pytest.mark.skipif(
    not _CONTEXT_LIBRARY or not CL.exists(),
    reason="INFIQUETRA_CONTEXT_LIBRARY is unset or is not a directory",
)
def test_stamp_claude_gemini_are_symlinks_to_agents(tmp_path: pathlib.Path):
    spec = from_dict(
        {
            "team": {
                "name": "nyx",
                "display": "Nyx",
                "host_group": "agent_vms",
                "limit_host": "nyx.infiquetra.com",
                "roles": [
                    {"role": "ollama", "tags": "ollama,nyx"},
                    {"role": "hermes", "tags": "hermes,nyx"},
                ],
            },
            "profiles": [
                {
                    "name": "nyx",
                    "persona": "nyx",
                    "discord_token_var": "vault_discord_bot_token_nyx",
                }
            ],
        }
    )
    repo_stamp.stamp(spec, tmp_path, CL)
    agents = tmp_path / "AGENTS.md"
    claude = tmp_path / "CLAUDE.md"
    gemini = tmp_path / "GEMINI.md"
    # AGENTS.md is the canonical real file; CLAUDE/GEMINI are relative symlinks to it
    assert agents.is_file() and not agents.is_symlink()
    assert claude.is_symlink() and claude.readlink() == pathlib.Path("AGENTS.md")
    assert gemini.is_symlink() and gemini.readlink() == pathlib.Path("AGENTS.md")
    # reading through the symlink yields the canonical content (one source of truth)
    assert claude.read_text() == agents.read_text()
    assert gemini.read_text() == agents.read_text()
