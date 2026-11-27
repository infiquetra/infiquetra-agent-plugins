---
name: vault-helper
description: Streamlines Ansible Vault secret management for the olympus cluster — scaffolds new secrets, validates vault references, and guides rotation workflows
metadata:
  when_to_use: |
    Use this skill when the user:
    - Needs to add a new secret or credential to the cluster
    - Is setting up a new service that needs credentials
    - Wants to rotate a credential
    - References vault_ variables in Ansible tasks
    - Asks about ansible-vault commands or encrypted variables
    - Is onboarding a new service VM or agent VM that needs secrets
---

# Ansible Vault Helper — Olympus Cluster

## How the vault is laid out

The `home-lab` repository does NOT use whole-file encrypted vault files. Every
vault file is plaintext YAML in which each secret is its own inline `!vault`
string block:

```text
<variable_name>: !vault |
  <ansible-vault ciphertext lines>
```

The files live under `ansible/inventory/group_vars/all/`:

- `all.yml`
- `vault_shared_infra.yml`
- `vault_ai_keys.yml` (project API keys, managed with the `ai-keys` skill)
- per-team split vault files

The vault password file is `~/.vault_pass.txt` (mode `0600`, never committed).

## Forbidden: whole-file vault commands

Never run `ansible-vault edit`, `ansible-vault view`, or `ansible-vault decrypt`
on these files. They are not whole-file vaults, so the commands fail, and a
decrypt-in-place habit would leave plaintext secrets in the working tree.
Do not use `ansible-vault encrypt` or `rekey` on them either.

To change a secret, encrypt one value and replace that variable's block.

## Encrypting one value

Always pipe the secret through standard input and name the variable with
`--stdin-name`. Never pass a secret value as a positional or flag argument:
it lands in shell history and the process list.

```bash
cd ansible
printf '%s' "$SECRET_VALUE" | ansible-vault encrypt_string \
  --vault-password-file ~/.vault_pass.txt --stdin-name vault_<service>_<credential_type>
```

Paste the printed `!vault |` block into the right vault file, replacing the old
block for that variable. Read the secret from a hidden prompt or a pipe, not
from a command line you type.

## Adding a New Secret

### Step 1: Determine the vault variable name

All vault variables are prefixed with `vault_`:

```
vault_<service>_<credential_type>

# Examples:
vault_grafana_admin_password
vault_pbs_api_token
vault_zeus_discord_token
vault_idrac_password
```

### Step 2: Encrypt and add it

Use the `--stdin-name` command above, then add the resulting inline block to the
matching vault file. Keep related secrets grouped.

### Step 3: Reference in the role

In the role's `tasks/setup.yml`, reference as `{{ vault_<name> }}`.

### Step 4: Protect every secret-bearing task

Every Ansible task that renders, copies, or passes a secret needs both
`no_log: true` and `diff: false`. Without them, task output and diffs print the
secret to the terminal and to logs.

```yaml
- name: Set service password
  ansible.builtin.template:
    src: config.yml.j2
    dest: /etc/service/config.yml
    mode: "0600"
  vars:
    password: "{{ vault_grafana_admin_password }}"
  no_log: true
  diff: false
```

### Step 5: Add a default placeholder in `defaults/main.yml`

```yaml
# roles/<role>/defaults/main.yml
# Do NOT put real values here — this is for documentation only
grafana_admin_password: "{{ vault_grafana_admin_password }}"
```

## New Service Secret Scaffolding

| Service Type | Required Secrets |
|-------------|-----------------|
| Monitoring exporter | `vault_<exporter>_api_token`, `vault_<exporter>_password` |
| Discord bot | `vault_<agent_name>_discord_token` |
| Proxmox API user | `vault_proxmox_api_token_secret` |
| PBS integration | `vault_pbs_api_token` |
| External service | `vault_<service>_api_key` |
| Database | `vault_<db>_password`, `vault_<db>_root_password` |
| Project AI API keys | use the `ai-keys` skill, not hand edits |

## Vault Reference Check

Verify every `vault_*` variable used in tasks has a matching entry. Compare names
only; the vault files are plaintext YAML, so a grep over the variable names works
without decrypting anything:

```bash
# Variables referenced by roles:
grep -rhoE 'vault_[A-Za-z0-9_]+' ansible/roles/ --include="*.yml" | sort -u

# Variables defined in the vault files:
grep -hoE '^vault_[A-Za-z0-9_]+' ansible/inventory/group_vars/all/*.yml | sort -u
```

Any name in the first list and not in the second needs to be added.

## Credential Rotation

1. Find every reference: `grep -r "vault_<old_var_name>" ansible/ --include="*.yml"`
   and the role templates.
2. Rotate the credential at the service first (Grafana, PBS, Proxmox API, Discord
   portal, and so on).
3. Encrypt the new value with `--stdin-name` and replace that variable's inline block.
4. Re-apply the affected roles:

```bash
cd ansible
ansible-playbook -i inventory/hosts.yml service_vms.yml \
  --tags <affected_service> \
  --vault-password-file ~/.vault_pass.txt
```

5. Confirm the service works with the new credential before committing.

For project AI API keys, use `ai-keys rotate` (see the `ai-keys` skill).

## Current Vault Variables Reference

See `references/vault-patterns.md` for the list of expected vault variables.
