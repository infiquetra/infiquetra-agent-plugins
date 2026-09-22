# Deploying Athena (legacy single agent) independently

Deploys only this team from this repository using the pinned
`infiquetra.hermes_team` collection.

Native Hermes profile-distribution packaging is deferred; this Ansible path is
the supported independent deploy mechanism.

## Prerequisites

1. Ansible plus `ansible-galaxy`.
2. Git authentication that can read the private collection repository.
3. Vault password at `~/.vault_pass.txt`.
4. An inventory file with a `agent_vms` group.
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

ANSIBLE_COLLECTIONS_PATH=.ansible/collections \
  ansible-playbook \
    -i /path/to/team-or-shared-inventory.yml \
    --limit athena.infiquetra.com \
    deploy/athena.yml \
    --vault-password-file ~/.vault_pass.txt
```

Dry-run first with `--check --diff`. The play prints its profile scope and
refuses to run if it cannot derive team profiles from this repo.

## Local Collection Artifact Test

Before the GitHub repository exists, install a locally built collection artifact
from `infiquetra-ansible-collections`:

```bash
ansible-galaxy collection install \
  /path/to/infiquetra-hermes_team-0.1.0.tar.gz \
  -p .ansible/collections --force
```
