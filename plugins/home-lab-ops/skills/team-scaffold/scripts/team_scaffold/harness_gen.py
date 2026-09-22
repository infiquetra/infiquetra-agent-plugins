"""Render a team's deploy harness.

The harness is collection-first: reusable Hermes team roles are referenced by
their ``infiquetra.hermes_team`` fully qualified collection names, while
inventory and shared runtime secrets are explicit operator inputs.
"""

from __future__ import annotations

COLLECTION_ROLES = {
    "hermes": "infiquetra.hermes_team.hermes",
    "hermes_dm_listener": "infiquetra.hermes_team.hermes_dm_listener",
    "hermes_mint_broker": "infiquetra.hermes_team.hermes_mint_broker",
    "deploy_skill": "infiquetra.hermes_team.deploy_skill",
    "ollama": "infiquetra.hermes_team.ollama",
    "hermes_team_listener": "infiquetra.hermes_team.hermes_team_listener",
    "hermes_orchestrator": "infiquetra.hermes_team.hermes_orchestrator",
}

REQUIREMENTS = """---
# Install reusable Hermes team deployment roles from the shared collection.
# Pin by tag or commit. Private-repository auth should come from SSH/netrc/Git
# credential config, not credentials embedded in this URL.
collections:
  - name: git+https://github.com/infiquetra/infiquetra-ansible-collections.git#/ansible_collections/infiquetra/hermes_team/
    type: git
    version: v0.1.1
"""

SHARED_INFRA_VAULT_EXAMPLE = """---
# Example shape only. Store the real file as an encrypted Ansible Vault artifact
# supplied by the operator at deploy time via INFIQUETRA_SHARED_INFRA_VAULT.

vault_redis_password: "change-me"
vault_langfuse_public_key: "change-me"
vault_langfuse_secret_key: "change-me"
vault_elevenlabs_api_key: "change-me"

# Required by infiquetra.hermes_team.ollama when ollama_cloud_models is non-empty.
# The operator supplies the key material in the encrypted vault. This example
# names the fields and does not carry a key block.
ollama_cloud_ssh_private_key: "change-me"
ollama_cloud_ssh_public_key: "ssh-ed25519 change-me"

# Required when deploying the Hermes orchestrator role.
vault_hermes_conductor_token: "change-me"
vault_github_webhook_secret: "change-me"
"""


def _format_tags(tags: str) -> str:
    parts = [p.strip() for p in tags.split(",") if p.strip()]
    return "[" + ", ".join(repr(p) for p in parts) + "]"


def _render_role(role: str, tags: str) -> str:
    rendered_role = COLLECTION_ROLES.get(role, role)
    return f"    - {{ role: {rendered_role}, tags: {_format_tags(tags)} }}"


def _render_inventory_example(cfg: dict) -> str:
    lines = [
        "---",
        "all:",
        "  children:",
        f"    {cfg['hosts']}:",
        "      hosts:",
        f"        {cfg['limit']}:",
    ]
    for key, value in (cfg.get("inventory") or {}).items():
        lines.append(f"          {key}: {value}")
    return "\n".join(lines) + "\n"


def render_play(name: str, cfg: dict) -> str:
    """Render deploy/<team>.yml. ``name`` is the play filename (e.g. themis.yml)."""
    coresident = cfg.get("coresident")
    coresident_note = (
        f" Co-resident team on this host ({coresident}) is NOT in the filter and is left untouched."
        if coresident
        else " Only this team's profiles are touched."
    )
    pin = "    hermes_update: false  # runtime pinned (shared host)\n" if cfg["pin"] else ""
    roles = "\n".join(_render_role(r, t) for r, t in cfg["roles"])
    return f"""---
# Deploy the {cfg["team"]} - and ONLY this team - from this repo.
#
# Uses the infiquetra.hermes_team collection via deploy/requirements.yml:
#   hermes_team_profiles_filter : narrows the host's profiles to this team's
#     (derived from this repo's profiles/ dir) so co-resident teams are untouched.
#   hermes_souls_source         : SOULs sourced from this repo's profiles/<n>/SOUL.md.
#
# Usage (see deploy/README.md):
#   export INFIQUETRA_SHARED_INFRA_VAULT=/path/to/shared-infra-vault.yml
#   ansible-playbook -i <inventory> \\
#     --limit {cfg["limit"]} {name} --vault-password-file ~/.vault_pass.txt
#
# Native distribution packaging (`hermes profile install`) is DEFERRED.

- name: Deploy {cfg["team"]} (profile-scoped)
  hosts: {cfg["hosts"]}
  gather_facts: true
  vars:
    # realpath normalizes the .. so the control-node find() gets an absolute dir.
    # NOTE: ansible's fileglob lookup does NOT expand '..' - use find() instead.
    _team_repo_root: "{{{{ (playbook_dir + '/..') | realpath }}}}"
    hermes_souls_source: "{{{{ _team_repo_root }}}}/profiles"
    # profile-dir layout = source each SOUL from <repo>/profiles/<name>/SOUL.md.
    hermes_souls_layout: profile-dir
    # Explicit operator-provided shared runtime secrets (Redis, Langfuse, and
    # optional voice-tooling credentials). Keep this outside the team repo unless
    # the file is encrypted for this consumer.
    shared_infra_vault_path: "{{{{ lookup('ansible.builtin.env', 'INFIQUETRA_SHARED_INFRA_VAULT') | default('', true) }}}}"
{pin}  vars_files:
    # This team's OWN secrets (post vault-split): Discord tokens etc.
    - "{{{{ _team_repo_root }}}}/ansible/inventory/group_vars/all/vault.yml"
    # This team's hermes_team_profiles. The team repo is authoritative.
    - "{{{{ _team_repo_root }}}}/deploy/team_profiles.yml"
  pre_tasks:
    - name: Require explicit shared-infra vault input
      ansible.builtin.assert:
        that:
          - shared_infra_vault_path | length > 0
        fail_msg: >-
          Set INFIQUETRA_SHARED_INFRA_VAULT to the encrypted shared runtime
          secrets file before running this play.
      tags: [always]

    - name: Refuse legacy infrastructure checkout inputs
      ansible.builtin.assert:
        that:
          - "'/home-lab/ansible/' not in shared_infra_vault_path"
          - (ansible_inventory_sources | default([]) | select('search', '/home-lab/ansible/') | list | length) == 0
        fail_msg: >-
          {cfg["team"]} deploy inputs must be independent artifacts. Do not pass
          the legacy infrastructure checkout inventory or shared-infra vault path.
      tags: [always]

    - name: Check shared-infra vault path on the control node
      ansible.builtin.stat:
        path: "{{{{ shared_infra_vault_path }}}}"
      delegate_to: localhost
      run_once: true
      register: _shared_infra_vault_stat
      tags: [always]

    - name: Refuse missing shared-infra vault file
      ansible.builtin.assert:
        that:
          - _shared_infra_vault_stat.stat.exists
          - _shared_infra_vault_stat.stat.isreg
        fail_msg: "Shared-infra vault file not found: {{{{ shared_infra_vault_path }}}}"
      tags: [always]

    - name: Load shared-infra runtime secrets
      ansible.builtin.include_vars:
        file: "{{{{ shared_infra_vault_path }}}}"
      no_log: true
      tags: [always]

    - name: Enumerate this repo's profile dirs on the control node
      ansible.builtin.find:
        paths: "{{{{ _team_repo_root }}}}/profiles"
        file_type: directory
        recurse: false
      delegate_to: localhost
      run_once: true
      register: _team_profile_dirs

    - name: Derive the per-team filter from the profile dirs
      ansible.builtin.set_fact:
        hermes_team_profiles_filter: >-
          {{{{ _team_profile_dirs.files | map(attribute='path') | map('basename') | list | sort }}}}

    # HARD GATE: an empty filter would make the hermes role deploy ALL of the
    # host's profiles (incl. co-resident teams). Refuse, loudly, before any role runs.
    - name: Refuse to proceed on an empty filter (would deploy co-resident teams)
      ansible.builtin.assert:
        that:
          - hermes_team_profiles_filter | length > 0
        fail_msg: >-
          Derived an EMPTY profile filter from {{{{ _team_repo_root }}}}/profiles -
          refusing to deploy (an empty filter makes the hermes role deploy the
          host's entire profile set, including co-resident teams). Check the
          repo layout / playbook_dir.

    - name: Show profile-scope (and what it won't touch)
      ansible.builtin.debug:
        msg: >-
          Deploying {{{{ hermes_team_profiles_filter | length }}}} profiles
          ({{{{ hermes_team_profiles_filter | join(', ') }}}}).{coresident_note}
  roles:
{roles}
"""


README_TMPL = """# Deploying {team} independently

Deploys only this team from this repository using the pinned
`infiquetra.hermes_team` collection.{coresident_line}

Native Hermes profile-distribution packaging is deferred; this Ansible path is
the supported independent deploy mechanism.

## Prerequisites

1. Ansible plus `ansible-galaxy`.
2. Git authentication that can read the private collection repository.
3. Vault password at `~/.vault_pass.txt`.
4. An inventory file with a `{hosts}` group.
5. An encrypted shared-infra vault file containing cross-team runtime secrets,
   including Ollama Cloud SSH key material when `ollama_cloud_models` is non-empty.

The playbook does not discover role code, inventory, or shared-infra secrets
from a sibling infrastructure checkout.

## Install Collections

From the repository root:

```bash
ansible-galaxy collection install -r deploy/requirements.yml -p .ansible/collections --force
```

## Deploy

```bash
export INFIQUETRA_SHARED_INFRA_VAULT=/path/to/shared-infra-vault.yml

ANSIBLE_COLLECTIONS_PATH=.ansible/collections \\
  ansible-playbook \\
    -i /path/to/team-or-shared-inventory.yml \\
    --limit {limit} \\
    deploy/{play} \\
    --vault-password-file ~/.vault_pass.txt
```

Dry-run first with `--check --diff`. The play prints its profile scope and
refuses to run if it cannot derive team profiles from this repo.

## Local Collection Artifact Test

Before the GitHub repository exists, install a locally built collection artifact
from `infiquetra-ansible-collections`:

```bash
ansible-galaxy collection install \\
  /path/to/infiquetra-hermes_team-0.1.0.tar.gz \\
  -p .ansible/collections --force
```
"""


def render_readme(cfg: dict) -> str:
    coresident_line = (
        f"\n\nThis team shares its host with {cfg['coresident']}. "
        f"The profile filter ensures {cfg['coresident']} is never touched by this deploy."
        if cfg.get("coresident")
        else ""
    )
    return README_TMPL.format(
        team=cfg["team"],
        hosts=cfg["hosts"],
        limit=cfg["limit"],
        play=cfg["play"],
        coresident_line=coresident_line,
    )


def render_harness(cfg: dict) -> dict[str, str]:
    """Return {filename: content} for generated deploy/ files."""
    return {
        cfg["play"]: render_play(cfg["play"], cfg),
        "requirements.yml": REQUIREMENTS,
        "README.md": render_readme(cfg),
        "inventory.example.yml": _render_inventory_example(cfg),
        "shared-infra-vault.example.yml": SHARED_INFRA_VAULT_EXAMPLE,
    }
