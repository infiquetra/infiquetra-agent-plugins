# Proxmox VE 9.x CLI Quirks

Behaviors that differ from documentation or previous PVE versions.

## pvecm — Cluster Management

### `pvecm add` — join a node to the cluster

```bash
# Correct syntax (run on the joining node, not the master)
pvecm add <master_ip> --use-address <this_node_cluster_ip>

# The --use-address flag is required when the node has multiple NICs
# Without it, pvecm may pick the wrong interface for corosync
# Cluster IP = the 10.220.2.x address on vmbr1
```

### `pvecm delnode` — remove a node

```bash
# Must run from a surviving node (not the node being removed)
# Node must be offline first
pvecm delnode <nodename>

# If corosync has stale /etc/hosts entries, cluster won't form
# Fix: ensure /etc/hosts on all nodes has correct IPs for all cluster members
```

### Quorum — 6-node cluster requires majority

With 6 nodes, quorum requires 4 nodes. If 3+ nodes are down simultaneously, the cluster goes into "no quorum" state and VMs are frozen. This is by design (split-brain prevention).

To check quorum state:
```bash
pvecm status | grep "Quorum information"
cat /etc/corosync/corosync.conf | grep -A5 quorum
```

---

## pveceph — Ceph Management via Proxmox

### `pveceph init` — initialize Ceph

```bash
# Only run once, on the master node
# Check if already initialized before running
test -f /etc/ceph/ceph.conf && echo "already initialized"

pveceph init --network 10.220.2.0/24
```

### `pveceph createmon` — add monitor

```bash
# Run on the master; specify the node to add the mon to
pveceph createmon <node_hostname>

# Monitors need time to sync before the next one is added
# Wait for ceph quorum to include the new mon:
ceph mon stat
```

### `pveceph createosd` — add OSD

```bash
# Run on the master; specify node and device
pveceph createosd /dev/<device> --node <hostname>

# IMPORTANT: disk must be completely wiped first
# wipefs -a /dev/<device> && sgdisk --zap-all /dev/<device>

# Set device class after creation if needed:
ceph osd crush rm-device-class osd.<id>
ceph osd crush set-device-class ssd osd.<id>
```

### `pveceph purge` — destroy Ceph cluster (PVE 9.x syntax)

```bash
# PVE 9.x — use --crash flag
pveceph purge --crash

# WRONG in PVE 9.x (old syntax):
# pveceph purge --destroy  ← flag was renamed
```

### Creating pools and CRUSH rules

```bash
# Create the fast pool (SSD OSDs only)
ceph osd pool create <pool_name> 128 128 replicated ceph-fast-rule
ceph osd pool set <pool_name> size 2

# Create a CRUSH rule that targets only SSD device class:
ceph osd crush rule create-replicated ceph-fast-rule default host ssd

# Register pool as Proxmox storage:
pvesm add rbd <pool_name> \
  --monhost 10.220.2.7,10.220.2.8,10.220.2.9 \
  --content images,rootdir \
  --pool <pool_name>
# NOTE: --add-storages flag was REMOVED in PVE 9 — omit it
```

---

## qm — VM Management

### `qm clone` — clone template to new VM

```bash
# Must delegate to the master node if template is on master
qm clone <template_id> <new_vmid> \
  --name <vm_name> \
  --full \
  --target <target_host_shortname>  # e.g. r820 not r820.infiquetra.com

# Target host shortname = hostname without domain
```

### `qm migrate` — move VM to another host

```bash
# Use --with-local-disks if VM has disks NOT on shared Ceph storage
qm migrate <vmid> <target_node> --with-local-disks --online

# If disks are already on ceph-fast, --with-local-disks is harmless but not needed
# --online = live migration (VM stays running)
# Without --online = offline migration (VM must be stopped first)
```

### `qm exec` vs `qm guest exec` — PVE 9.x API change

```bash
# WRONG — removed in PVE 9.x:
qm exec <vmid> -- ip addr show

# CORRECT — PVE 9.x syntax:
qm guest exec <vmid> -- ip addr show

# Requires qemu-guest-agent running inside the VM
```

### `qm set` — configure VM

```bash
# Set cloud-init config (Ubuntu 24.04)
qm set <vmid> \
  --ipconfig0 ip=10.220.1.<x>/24,gw=10.220.1.1 \
  --nameserver 10.220.1.1 \
  --searchdomain infiquetra.com \
  --ciuser ubuntu \
  --cipassword <hashed_password> \
  --sshkey ~/.ssh/authorized_keys

# Memory/CPU
qm set <vmid> --memory 8192 --cores 8 --sockets 1

# Add a disk from Ceph
qm set <vmid> --scsi0 ceph-fast:<size_GB>
```

### VM BIOS/Machine type for cloud-init

```bash
# SeaBIOS + i440fx (CORRECT for cloud-init templates)
qm set <vmid> --bios seabios --machine i440fx

# OVMF + q35 causes cloud-init disk slot conflict:
# EFI disk takes ide0, bumping cloud-init to ide2
# Some Ubuntu cloud images don't find cloud-init on ide2
# → use SeaBIOS to avoid this
```

---

## pvesm — Storage Management

### List storage

```bash
pvesm status          # All storage, active/inactive
pvesm list <storage>  # Contents of specific storage pool
```

### Add external storage (e.g., PBS)

```bash
# Add PBS as backup storage
pvesm add pbs <storage_name> \
  --server <pbs_ip> \
  --datastore <datastore_name> \
  --username <user>@pbs \
  --token <tokenid>!<secret> \
  --fingerprint <fingerprint>

# Get PBS fingerprint:
# On PBS server: proxmox-backup-manager cert info | grep Fingerprint
```

---

## General PVE 9.x Notes

- Base OS: Debian Trixie (Debian 13) — uses DEB822 apt sources format
- Python: 3.13 (crypt module removed — use openssl passwd -6 for password hashing)
- Ceph version: Squid 19.x (significant changes from Reef 18.x)
- Kernel: Proxmox custom kernel on top of Debian Trixie
- corosync: Version 3.x (uses knet transport by default)
