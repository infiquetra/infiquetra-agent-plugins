# Vault Variables Reference — Olympus Cluster

All variables prefixed with `vault_` must exist in:
`ansible/inventory/group_vars/all/all.yml` (Ansible Vault encrypted)

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

The vault file uses YAML. Keep secrets grouped by service area:

```yaml
---
# Proxmox infrastructure
vault_proxmox_api_token_secret: <token_secret>
vault_vm_password: <hashed_password_openssl_6>
vault_ssh_public_key: |
  ssh-ed25519 AAAA... user@host

# Service VMs
vault_grafana_admin_password: <password>
vault_pbs_api_token: monitoring-exporter@pbs!read-token=<secret>
vault_idrac_password: <password>
vault_unifi_api_key: <api_key>
vault_discord_monitoring_webhook: https://discord.com/api/webhooks/...

# OpenClaw agents
vault_zeus_discord_token: change-me
vault_athena_discord_token: change-me
# ... (one per agent)
```

## Vault Command Reference

```bash
# Edit
ansible-vault edit inventory/group_vars/all/all.yml \
  --vault-password-file ~/.vault_pass.txt

# View (read-only)
ansible-vault view inventory/group_vars/all/all.yml \
  --vault-password-file ~/.vault_pass.txt

# Re-key (change vault password)
ansible-vault rekey inventory/group_vars/all/all.yml \
  --vault-password-file ~/.vault_pass.txt

# Encrypt a new file
ansible-vault encrypt <file> --vault-password-file ~/.vault_pass.txt

# Encrypt a single value (for inline vault strings)
ansible-vault encrypt_string '<value>' --name 'variable_name' \
  --vault-password-file ~/.vault_pass.txt
```

## Security Notes

- `~/.vault_pass.txt` must have permissions `0600` (`chmod 600 ~/.vault_pass.txt`)
- Never commit the vault password file
- Never commit a decrypted vault file
- The `.gitignore` should exclude `*.vault_pass*` patterns
- VM passwords should be stored as openssl-hashed values, not plain text:
  ```bash
  openssl passwd -6 "your_password"  # Generates $6$... SHA-512 hash
  ```
