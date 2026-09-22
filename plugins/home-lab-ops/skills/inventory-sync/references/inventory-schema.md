# Inventory Schema — Olympus Cluster

## hosts.yml Group Structure

```yaml
all:
  children:
    proxmox_hosts:          # All 6 Proxmox nodes
      children:
        proxmox_master:     # r420 only (single master)
          hosts:
            r420.infiquetra.com:
              ansible_host: 10.220.1.7
        proxmox_nodes:      # The other 5 nodes
          hosts:
            r640-1.infiquetra.com:
              ansible_host: 10.220.1.8
            # ... etc
    agent_vms:              # 8 OpenClaw agent VMs
      hosts:
        zeus.infiquetra.com:
          ansible_host: 10.220.1.50
        # ... 101–107 → 10.220.1.51–57
    service_vms:            # 4 service VMs
      hosts:
        monitoring.infiquetra.com:
          ansible_host: 10.220.1.63
        # ...
```

## host_vars Schema — Proxmox Nodes

Required for every host in `proxmox_hosts`:

```yaml
# ansible/inventory/host_vars/<hostname>.infiquetra.com.yml

# REQUIRED: Ceph cluster network NIC
# Run 'ip link' on the host — look for 10GbE interfaces
# Dell R640: typically nic0 or nic4 (depends on slot)
# Dell r420/r720xd/r820: typically nic0
ceph_nic: nic0

# REQUIRED (for nodes that contribute Ceph OSDs):
# List all non-boot disks to be used as Ceph OSDs
# device_class: 'ssd' (NVMe or SATA SSD), 'hdd' (SAS/SATA spinning)
ceph_disks:
  - name: nvme0n1       # NO /dev/ prefix
    device_class: ssd
  - name: sdc
    device_class: ssd

# REQUIRED (for monitoring):
# iDRAC IP for IPMI hardware metrics
idrac_ip: 10.220.1.17

# OPTIONAL: Override VM storage pool for VMs on this host
# Defaults to ceph-fast; set to ceph-bulk for non-R640 hosts
# vm_storage: ceph-fast
```

## host_vars Schema — Agent VMs

```yaml
# ansible/inventory/host_vars/<agent_name>.infiquetra.com.yml

# Agent identity (used by openclaw role)
agent_name: zeus              # Lowercase, matches VM name
agent_email: zeus@infiquetra.com
agent_vmid: 100               # Proxmox VM ID

# OPTIONAL: Target Proxmox host for VM placement
# proxmox_target_host: r820.infiquetra.com
```

## group_vars/all/all.yml Structure

This file is Ansible Vault encrypted. The following variables are expected:

```yaml
# Cluster identity
proxmox_cluster_name: olympus
proxmox_master: r420.infiquetra.com

# Proxmox API credentials (created during proxmox_base role)
proxmox_api_user: ansible@pam
proxmox_api_token_id: <ansible-token-id>
vault_proxmox_api_token_secret: <encrypted>

# VM template config
proxmox_template_id: 9000
proxmox_template_storage: ceph-fast
proxmox_template_vm_storage: ceph-fast

# Cloud-init default user
vm_default_user: ubuntu
vault_vm_password: <encrypted>
vault_ssh_public_key: <encrypted>

# PBS credentials
pbs_host: 10.220.1.62
vault_pbs_api_token: <encrypted>

# Monitoring credentials
vault_grafana_admin_password: <encrypted>
vault_idrac_password: <encrypted>       # Shared across all Dell servers
vault_unifi_api_key: <encrypted>
vault_discord_monitoring_webhook: <encrypted>

# OpenClaw agent secrets (one per agent VM)
vault_zeus_discord_token: <encrypted>
vault_athena_discord_token: <encrypted>
# ... etc for each agent
```

## Required Variables by Role

| Role | Required host_vars | Required group_vars |
|------|--------------------|---------------------|
| `proxmox_network` | `ceph_nic` | — |
| `proxmox_disk_prep` | `ceph_disks[].name` | — |
| `proxmox_ceph` | `ceph_disks[].name`, `ceph_disks[].device_class` | `proxmox_master` |
| `proxmox_cluster` | — | `proxmox_cluster_name`, `proxmox_master` |
| `proxmox_template` | — | `proxmox_template_id`, `proxmox_template_storage` |
| `proxmox_vm` | (per VM: vmid, target host) | `vault_vm_password`, `vault_ssh_public_key` |
| `monitoring` | `idrac_ip` (on Proxmox hosts) | `vault_idrac_password`, `vault_unifi_api_key` |
| `proxmox_backup_server` | — | `vault_pbs_api_token` |
| `openclaw` | `agent_name`, `agent_email` | `vault_<agent>_discord_token` |
