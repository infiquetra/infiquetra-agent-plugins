"""Harness contract tests for the collection-era team deploy generator."""

from __future__ import annotations

import pathlib

import pytest

from team_scaffold import harness_gen, spec

ROOT = pathlib.Path(__file__).resolve().parents[1] / "skills" / "team-scaffold"
SPECS = ROOT / "specs"

SPEC_FILES = sorted(SPECS.glob("team-*.yaml"))
assert len(SPEC_FILES) == 12, f"expected 12 specs, found {len(SPEC_FILES)}"


@pytest.mark.parametrize("spec_path", SPEC_FILES, ids=lambda p: p.stem)
def test_harness_uses_collection_contract(spec_path: pathlib.Path) -> None:
    ts = spec.load_spec(spec_path)
    assert ts.validate() == [], f"{ts.repo} spec is invalid"
    rendered = harness_gen.render_harness(ts.as_cfg())
    assert set(rendered) == {
        "README.md",
        "requirements.yml",
        "inventory.example.yml",
        "shared-infra-vault.example.yml",
        ts.play,
    }
    assert "infiquetra-ansible-collections.git" in rendered["requirements.yml"]
    assert "git+https://github.com/namredips/home-lab.git" not in rendered["requirements.yml"]
    assert "ANSIBLE_ROLES_PATH" not in rendered["README.md"]
    assert "homelab_root" not in rendered[ts.play]
    assert "INFIQUETRA_SHARED_INFRA_VAULT" in rendered[ts.play]
    assert "pin_guard" not in rendered[ts.play]

    for role_name, _tags in ts.roles:
        fqcn = harness_gen.COLLECTION_ROLES.get(role_name)
        assert fqcn, f"{role_name} is not mapped to infiquetra.hermes_team"
        assert f"role: {fqcn}" in rendered[ts.play]


def test_requirements_uses_collection_source() -> None:
    assert "infiquetra-ansible-collections.git" in harness_gen.REQUIREMENTS
    assert "type: git" in harness_gen.REQUIREMENTS
    assert "version: v0.1.1" in harness_gen.REQUIREMENTS
