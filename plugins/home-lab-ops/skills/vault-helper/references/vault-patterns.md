# Vault Variables Reference — Olympus Cluster

All variables prefixed with `vault_` must exist in a plaintext YAML file under
`ansible/inventory/group_vars/all/` (`all.yml`, `vault_shared_infra.yml`,
`vault_ai_keys.yml`, or a per-team split vault). Each secret is an inline `!vault`
string block. None of these files is a whole-file encrypted vault.

## Proxmox & Infrastructure

| Variable | Purpose | Used By |
|----------|---------|---------|
| `vault_proxmox_api_token_secret` | Proxmox API token secret for ansible@pam | proxmox_base, proxmox_vm, proxmox_backup_server |
| `vault_vm_password` | Default cloud-init password for all VMs | proxmox_template, proxmox_vm |
| `vault_ssh_public_key` | SSH public key injected into all VMs | proxmox_vm cloud-init |

## Service Credentials

| Variable | Purpose | Used By |
|----------|---------|---------|
| `vault_grafana_admin_password` | Grafana web UI admin password | monitoring/grafana config |
| `vault_pbs_api_token` | PBS API token for backup integration | proxmox_backup_server, monitoring |
| `vault_idrac_password` | Shared iDRAC root password (all Dell servers) | monitoring/ipmi_exporter config |
| `vault_unifi_api_key` | UniFi Dream Machine Pro API key | monitoring/unifi-poller config |
| `vault_discord_monitoring_webhook` | Discord webhook URL for Grafana alerts | monitoring/alertmanager config |

## OpenClaw Agent Discord Tokens

One Discord bot token per agent VM:

| Variable | Agent VM |
|----------|---------|
| `vault_zeus_discord_token` | Zeus (VMID 100) |
| `vault_athena_discord_token` | Athena (VMID 101) |
| `vault_apollo_discord_token` | Apollo (VMID 102) |
| `vault_artemis_discord_token` | Artemis (VMID 103) |
| `vault_hermes_discord_token` | Hermes (VMID 104) |
| `vault_perseus_discord_token` | Perseus (VMID 105) |
| `vault_prometheus_discord_token` | Prometheus (VMID 106) |
| `vault_ares_discord_token` | Ares (VMID 107) |

## Vault File Structure

Plaintext YAML, one inline `!vault` block per secret, grouped by service area:

```text
# Proxmox infrastructure
<variable_name>: !vault |
  <ansible-vault ciphertext lines>

# Service VMs
<variable_name>: !vault |
  <ansible-vault ciphertext lines>
```

## Vault Command Reference

Whole-file `ansible-vault edit`, `view`, `decrypt`, `encrypt`, and `rekey` are
forbidden on these files, because they are not whole-file vaults. The one command
to use encrypts a single value from standard input:

```bash
printf '%s' "$SECRET_VALUE" | ansible-vault encrypt_string \
  --vault-password-file ~/.vault_pass.txt --stdin-name vault_<service>_<credential_type>
```

Never pass the secret as a positional or flag argument. Paste the printed block
over the variable's existing block.

Every Ansible task that handles a secret sets `no_log: true` and `diff: false`.

## Security Notes

- `~/.vault_pass.txt` must have permissions `0600` (`chmod 600 ~/.vault_pass.txt`)
- Never commit the vault password file
- Never commit a decrypted vault file
- The `.gitignore` should exclude `*.vault_pass*` patterns
- VM passwords should be stored as openssl-hashed values, not plain text:
  ```bash
  openssl passwd -6 "your_password"  # Generates $6$... SHA-512 hash
  ```
