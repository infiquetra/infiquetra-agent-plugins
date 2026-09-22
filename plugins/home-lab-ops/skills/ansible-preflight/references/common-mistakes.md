# Common Ansible Mistakes — Olympus Cluster

This catalog is extracted from the fix commit history of the home-lab repository. Each pattern describes a mistake that has happened before, its root cause, and the fix.

## Category 1: Proxmox CLI Argument Errors

### pvecm join — missing `--use-address` on multi-NIC nodes

**Symptom**: Node fails to join cluster with network error, or joins on wrong NIC
**Root cause**: `pvecm add <master_ip>` uses the first NIC, not the Ceph NIC
**Fix**: Always specify the corosync ring address explicitly when nodes have multiple NICs

### pvecm — serial: 1 missing on join tasks

**Symptom**: Race condition — two nodes try to join simultaneously, second node fails
**Root cause**: Ansible runs on all hosts in parallel by default
**Fix**: Add `serial: 1` to the play that joins nodes, or use `throttle: 1` at task level

```yaml
# WRONG — parallel join races
- hosts: proxmox_nodes
  roles:
    - proxmox_cluster

# CORRECT — join nodes one at a time
- hosts: proxmox_nodes
  serial: 1
  roles:
    - proxmox_cluster
```

### pveceph init — cluster already initialized check missing

**Symptom**: `pveceph init` fails with "ceph config already exists"
**Root cause**: Task runs unconditionally on re-runs
**Fix**: Check for existing ceph.conf before running init

```yaml
- name: Check if Ceph already initialized
  ansible.builtin.stat:
    path: /etc/ceph/ceph.conf
  register: ceph_conf

- name: Initialize Ceph cluster
  ansible.builtin.command: pveceph init --network "{{ ceph_cluster_network }}"
  when: not ceph_conf.stat.exists
  delegate_to: "{{ proxmox_master }}"
  run_once: true
```

### pveceph purge — wrong flag syntax

**Symptom**: `pveceph purge` fails with "unknown option"
**Root cause**: Flag syntax changed in Ceph Squid 19.x
**Fix**: Use `pveceph purge --crash` (the `--destroy` flag was renamed)

### pvesm add — `--add-storages` flag removed in PVE 9

**Symptom**: `pvesm add` returns "unknown option --add-storages"
**Root cause**: Flag was removed in Proxmox VE 9.x
**Fix**: Create pool without the flag, then configure storage separately via the API

---

## Category 2: Ceph OSD Timing Issues

### OSD creation fails — disk not fully wiped

**Symptom**: `pveceph createosd` fails with "disk already contains partitions"
**Root cause**: `wipefs -a` and `sgdisk --zap-all` complete before the kernel processes the partition table change
**Fix**: Add a short pause or re-read the partition table after wiping

```yaml
- name: Wipe disk
  ansible.builtin.shell: |
    wipefs -a /dev/{{ item.name }}
    sgdisk --zap-all /dev/{{ item.name }}
  changed_when: true

- name: Re-read partition table
  ansible.builtin.command: partprobe /dev/{{ item.name }}
  changed_when: false

- name: Wait for device to settle
  ansible.builtin.pause:
    seconds: 3
```

### Ceph monitor quorum — split-brain after rapid node joins

**Symptom**: `ceph -s` shows `HEALTH_WARN N mon(s) down` or quorum issues
**Root cause**: Monitors added too quickly before first one is fully up
**Fix**: Wait for each mon to be in quorum before adding the next

```yaml
- name: Wait for monitor quorum
  ansible.builtin.shell: ceph mon stat | grep -q "{{ inventory_hostname }}"
  register: mon_result
  retries: 20
  delay: 10
  until: mon_result.rc == 0
  delegate_to: "{{ proxmox_master }}"
```

---

## Category 3: VM Lifecycle Errors

### VM clone — must delegate to master node

**Symptom**: `qm clone` fails on non-master nodes
**Root cause**: Template VM lives on master; cloning from non-master requires API delegation
**Fix**: Always delegate clone tasks to the master node

```yaml
- name: Clone VM from template
  ansible.builtin.command: >
    qm clone {{ proxmox_template_id }} {{ vm_id }}
    --name {{ vm_name }}
    --full
    --target {{ vm_target_host }}
  delegate_to: "{{ proxmox_master }}"
  run_once: false  # runs once PER VM but delegates execution to master
```

### VM migration — `--with-local-disks` required for local storage

**Symptom**: `qm migrate` fails if VM has disks on local storage
**Root cause**: Without the flag, migration fails when disks aren't on shared storage
**Fix**: Use `--with-local-disks` flag; migrate to ceph-fast storage before migrating

```yaml
- name: Migrate VM to target host
  ansible.builtin.command: >
    qm migrate {{ vm_id }} {{ vm_target_host }}
    --with-local-disks
    --online
  delegate_to: "{{ proxmox_master }}"
```

### Cloud-init — UEFI vs SeaBIOS EFI disk confusion

**Symptom**: Cloud-init drive not visible inside VM; VM boots without cloud-init applied
**Root cause**: UEFI firmware (OVMF) with q35 machine type places EFI disk at slot `ide0`, bumping cloud-init to `ide2` — but the template was built with `ide2` hardcoded
**Fix**: Use SeaBIOS + i440fx for cloud-init templates (avoids EFI disk slot conflict)

```yaml
# CORRECT template configuration for cloud-init
- name: Configure template
  ansible.builtin.command: >
    qm set {{ proxmox_template_id }}
    --bios seabios
    --machine i440fx
    --ide2 {{ template_storage }}:cloudinit
```

### Cloud-init network — Ubuntu 24.04 uses network-config v2

**Symptom**: Static IP not applied; VM gets DHCP instead
**Root cause**: Ubuntu 24.04 cloud images use netplan (network-config v2); passing v1 config is silently ignored
**Fix**: Use `--ipconfig0` format with Proxmox cloud-init, which generates the correct v2 config

### qm exec — PVE 9.x API change

**Symptom**: `qm exec <vmid> -- <command>` returns "method not found"
**Root cause**: In PVE 9.x, the `exec` subcommand was moved to the guest agent API
**Fix**: Use `qm guest exec` instead of `qm exec`

```bash
# WRONG (PVE 8.x)
qm exec 100 -- ip addr show

# CORRECT (PVE 9.x)
qm guest exec 100 -- ip addr show
```

---

## Category 4: Debian Trixie / Package Management

### Apt sources — DEB822 format required on Debian Trixie

**Symptom**: `apt` fails with "Malformed stanza" or source not recognized
**Root cause**: Debian Trixie (PVE 9 base) uses DEB822 `.sources` format, not legacy `.list` format
**Fix**: Use `.sources` files instead of `.list` files

```yaml
# WRONG — legacy .list format (Debian Bullseye/Bookworm)
- name: Add Ceph repo
  ansible.builtin.copy:
    content: "deb https://download.ceph.com/debian-squid/ trixie main"
    dest: /etc/apt/sources.list.d/ceph.list

# CORRECT — DEB822 format (Debian Trixie)
- name: Add Ceph repo
  ansible.builtin.copy:
    content: |
      Types: deb
      URIs: https://download.ceph.com/debian-squid/
      Suites: trixie
      Components: main
      Signed-By: /etc/apt/trusted.gpg.d/ceph.gpg
    dest: /etc/apt/sources.list.d/ceph.sources
```

### Python 3.13 — crypt module removed

**Symptom**: `python3 -c "import crypt"` fails; password hashing in Ansible fails
**Root cause**: Python 3.13 (included in Debian Trixie) removed the `crypt` module
**Fix**: Use `openssl passwd -6` instead of `ansible.builtin.user` password hashing

```yaml
# WRONG — uses removed crypt module
- name: Set password
  ansible.builtin.user:
    name: ubuntu
    password: "{{ 'mypassword' | password_hash('sha512') }}"

# CORRECT — use openssl via shell
- name: Generate password hash
  ansible.builtin.command: openssl passwd -6 "{{ vm_password }}"
  register: pw_hash
  delegate_to: localhost
  changed_when: false

- name: Set password
  ansible.builtin.user:
    name: ubuntu
    password: "{{ pw_hash.stdout }}"
```

---

## Category 5: Proxmox Backup Server (PBS)

### PBS API token — DatastoreAudit role insufficient

**Symptom**: PBS exporter returns 403 on `/nodes` endpoint
**Root cause**: `DatastoreAudit` role only grants datastore access; the `/nodes` API requires `Admin` or `Sys.Audit`
**Fix**: Grant `Admin` role to the exporter token at the root (`/`) path

```bash
# WRONG — DatastoreAudit insufficient for node metrics
pveum acl modify / --users monitoring-exporter@pbs!read-token --roles DatastoreAudit

# CORRECT — Admin role at root
pveum acl modify / --users monitoring-exporter@pbs!read-token --roles Admin
```

### PBS generate-token — output must be captured immediately

**Symptom**: Token secret lost — PBS only shows the secret once at generation time
**Root cause**: The secret is only displayed once and cannot be retrieved again
**Fix**: Always capture and immediately store in Ansible vault; use `--output-format json` for reliable parsing

```bash
pveum user token add monitoring-exporter@pbs read-token \
  --privsep 0 --output-format json | jq -r '.value'
```

---

## Category 6: Monitoring Stack

### Promtail — rsyslog must be installed first

**Symptom**: Promtail syslog receiver starts but receives nothing
**Root cause**: Promtail's syslog pipeline requires rsyslog to forward to its TCP/UDP port
**Fix**: Install rsyslog before Promtail and add forwarding config

```yaml
- name: Install rsyslog
  ansible.builtin.apt:
    name: rsyslog
    state: present

- name: Configure rsyslog to forward to Promtail
  ansible.builtin.copy:
    content: |
      *.* action(type="omfwd" target="localhost" port="{{ promtail_syslog_port }}" protocol="tcp")
    dest: /etc/rsyslog.d/99-promtail.conf
  notify: restart rsyslog
```

### Config file permissions — Docker requires 0644

**Symptom**: Docker container fails to start; "permission denied" reading config
**Root cause**: Ansible default file creation mode is 0600; Docker containers run as non-root
**Fix**: Always set `mode: '0644'` on Docker config files

```yaml
- name: Write Prometheus config
  ansible.builtin.template:
    src: prometheus.yml.j2
    dest: "{{ monitoring_config_dir }}/prometheus/prometheus.yml"
    mode: '0644'  # Required for Docker container access
```

### IPMI exporter — password vs pass field name

**Symptom**: IPMI exporter returns "permission denied" despite correct credentials
**Root cause**: iDRAC IPMI config uses `pass` not `password` as the field name
**Fix**: Verify the config field name matches the exporter's expected format

```yaml
# WRONG
ipmi_password: "{{ vault_idrac_password }}"

# CORRECT for the ipmi_exporter config
- ipmihost: "{{ idrac_ip }}"
  user: root
  pass: "{{ vault_idrac_password }}"  # field is 'pass', not 'password'
```
