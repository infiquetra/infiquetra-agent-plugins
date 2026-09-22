# VM Lifecycle — Olympus Cluster

## Template Management

The Ubuntu 24.04 cloud-init template lives at VMID 9000 on r420 (master).

### Building the template

```bash
# 1. Download Ubuntu 24.04 cloud image
wget https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img \
  -O /var/lib/vz/template/iso/noble-server-cloudimg-amd64.img

# 2. Create base VM
qm create 9000 --name ubuntu-2404-template \
  --memory 2048 --cores 2 \
  --net0 virtio,bridge=vmbr0 \
  --ostype l26 \
  --bios seabios \
  --machine i440fx   # Use i440fx/SeaBIOS — avoid UEFI cloud-init slot conflict

# 3. Import disk
qm importdisk 9000 noble-server-cloudimg-amd64.img ceph-fast

# 4. Attach disk and cloud-init
qm set 9000 \
  --scsihw virtio-scsi-pci \
  --scsi0 ceph-fast:vm-9000-disk-0 \
  --ide2 ceph-fast:cloudinit \   # Cloud-init drive on ide2
  --boot c --bootdisk scsi0 \
  --serial0 socket \
  --vga serial0

# 5. Enable QEMU guest agent
qm set 9000 --agent enabled=1

# 6. Convert to template
qm template 9000
```

**Critical**: Use `--bios seabios --machine i440fx`. OVMF/q35 assigns EFI disk to ide0, pushing cloud-init to ide2 — but the cloud image may not find it there.

---

## VM Creation (Clone from Template)

### Via Ansible (proxmox_vm role pattern)

```yaml
- name: Clone VM from template
  ansible.builtin.command: >
    qm clone {{ proxmox_template_id }} {{ vm_id }}
    --name {{ vm_name }}
    --full
    --target {{ vm_target_host_short }}  # Short hostname, no domain
  delegate_to: "{{ proxmox_master }}"
  register: clone_result
  changed_when: clone_result.rc == 0
```

### Configure cloud-init

```yaml
- name: Configure VM cloud-init
  ansible.builtin.command: >
    qm set {{ vm_id }}
    --memory {{ vm_memory }}
    --cores {{ vm_cores }}
    --ipconfig0 ip={{ vm_ip }}/24,gw={{ vm_gateway }}
    --nameserver {{ vm_nameserver }}
    --searchdomain {{ vm_searchdomain }}
    --ciuser {{ vm_default_user }}
    --sshkey /tmp/vm_ssh_key.pub
  delegate_to: "{{ vm_target_host }}.infiquetra.com"
```

**Note**: SSH key file must be a plain text file with one key per line — not a variable string. Copy to a temp file first via `ansible.builtin.copy` before passing to `--sshkey`.

### Start and wait for SSH

```yaml
- name: Start VM
  ansible.builtin.command: qm start {{ vm_id }}
  delegate_to: "{{ vm_target_host }}.infiquetra.com"

- name: Wait for SSH
  ansible.builtin.wait_for:
    host: "{{ vm_ip }}"
    port: 22
    delay: 10
    timeout: 300
```

---

## VM Migration

### Live migration (VM stays running)

```bash
# Via CLI (run on source or master node)
qm migrate <vmid> <target_node_shortname> --online

# If VM has disks NOT on shared Ceph (on local storage):
qm migrate <vmid> <target_node> --with-local-disks --online
```

### Offline migration

```bash
qm stop <vmid>
qm migrate <vmid> <target_node>
qm start <vmid>  # On target node
```

### Check if VM is safe to migrate

```bash
qm config <vmid> | grep -E "^(scsi|virtio|ide|sata|net)" | grep -v ceph
# Any disk NOT on ceph-fast/ceph-bulk needs --with-local-disks
```

---

## VM Deletion

```bash
# Stop first if running
qm stop <vmid>

# Destroy VM and all its disk images
qm destroy <vmid> --purge

# --purge removes disk images from storage pools
# Without --purge, disk images remain in the storage pool
```

---

## Cloud-Init Patterns (Ubuntu 24.04)

### Network configuration

Ubuntu 24.04 uses **netplan** with **network-config v2**. Proxmox generates the correct v2 format when using `--ipconfig0`.

```bash
# Inside the VM, verify cloud-init applied the config:
cloud-init status
cat /etc/netplan/50-cloud-init.yaml
ip addr show ens3  # or whatever the NIC name is
```

### NIC naming on Ubuntu 24.04 VMs

- VirtIO NICs in Proxmox VMs appear as `ens3` (first), `ens4` (second) in Ubuntu 24.04
- Not `eth0` / `eth1` — those are legacy names
- Cloud-init's `--ipconfig0` targets the first NIC

### First boot behavior

Cloud-init runs in stages. The VM may take 30-90 seconds after SSH becomes available before all cloud-init modules complete. For provisioning tasks, wait for:

```bash
# On the VM:
cloud-init status --wait
```

### Regenerate cloud-init (force re-run)

```bash
# Inside VM (use with caution — resets everything)
cloud-init clean --logs
cloud-init init

# Via Proxmox (regenerate the cloud-init drive):
qm cloudinit dump <vmid> network
```

---

## QEMU Guest Agent

The guest agent must be running inside the VM for `qm guest exec` and other agent-based operations.

```bash
# Install inside VM
apt install -y qemu-guest-agent
systemctl enable --now qemu-guest-agent

# Verify from Proxmox host
qm agent <vmid> ping  # Returns "ping OK" if agent is running
```

---

## VM Snapshots

```bash
# Create snapshot
qm snapshot <vmid> <snapname> --description "Before applying X"

# List snapshots
qm listsnapshot <vmid>

# Rollback to snapshot
qm rollback <vmid> <snapname>

# Delete snapshot
qm delsnapshot <vmid> <snapname>
```

**Note**: VMs using Ceph RBD storage support live snapshots while the VM is running. Local storage does not support live snapshots.
