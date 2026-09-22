# Ceph Squid 19.x Operations — Olympus Cluster

## Cluster Architecture

- **Ceph version**: Squid 19.x
- **Cluster network**: 10.220.2.0/24 (dedicated 10GbE, vmbr1 on each node)
- **Public network**: 10.220.1.0/24 (shared with management)
- **Replication size**: 2 (min_size: 1)
- **Two tiers**:
  - `ceph-fast` — NVMe/SSD OSDs on R640s (r640-1, r640-2, r640-3)
  - `ceph-bulk` — SAS HDD OSDs on r420, r720xd, r820

## Health Monitoring

```bash
ceph -s                   # Full health summary
ceph health detail        # Detailed warnings/errors
ceph osd stat             # OSD count (up/in/total)
ceph osd tree             # Full OSD topology with device classes
ceph osd df               # Per-OSD disk usage
ceph pg stat              # Placement group status
ceph pg dump | grep -v ^pg  # Summary without per-PG detail
```

### Interpreting `ceph -s` output

- `HEALTH_OK` — all good
- `HEALTH_WARN` — degraded but functional; investigate but not urgent
- `HEALTH_ERR` — data at risk or inaccessible; urgent

Common WARNs:
- `N pgs degraded` — replication in progress (normal after OSD restart)
- `clock skew detected` — NTP drift between nodes; check `chronyc tracking`
- `too few PGs per OSD` — pool has too few PGs; use `ceph osd pool set <pool> pg_num <n>`

## OSD Operations

### Check OSD status

```bash
ceph osd tree           # Full tree with device classes
ceph osd stat           # Count of up/in OSDs
ceph osd dump | grep -E "^osd\."  # Per-OSD flags
```

### Bring a downed OSD back

```bash
# Check which OSD is down
ceph osd tree | grep down

# Restart on the affected node
systemctl start ceph-osd@<id>
# OR via pveceph:
pveceph osd start <id>
```

### Mark OSD out (for maintenance)

```bash
# Before taking a node down for maintenance:
ceph osd out osd.<id>   # Ceph starts rebalancing away from this OSD
# Wait for rebalancing: watch -n5 'ceph -s'
# Proceed with maintenance
# When done:
ceph osd in osd.<id>    # Ceph rebalances data back
```

### Remove an OSD permanently

```bash
# 1. Mark it out and wait for PG migration
ceph osd out osd.<id>
# 2. Stop the OSD
systemctl stop ceph-osd@<id>
# 3. Remove from crush, auth, and osd map
ceph osd purge osd.<id> --yes-i-really-mean-it
```

### Device class management

```bash
# Show device classes
ceph osd crush tree --show-shadow | grep class

# Change device class
ceph osd crush rm-device-class osd.<id>
ceph osd crush set-device-class ssd osd.<id>  # or 'hdd', 'nvme'
```

## Pool Operations

### List pools and their CRUSH rules

```bash
ceph osd pool ls                      # Pool names
ceph osd pool ls detail               # Pools with replication, PGs, CRUSH rule
ceph osd crush rule dump              # All CRUSH rules
```

### Create a tiered pool (e.g., new fast pool)

```bash
# 1. Create CRUSH rule for SSD-only placement
ceph osd crush rule create-replicated ceph-fast-rule default host ssd

# 2. Create pool using that rule
ceph osd pool create vm-disks 128 128 replicated ceph-fast-rule
ceph osd pool set vm-disks size 2
ceph osd pool set vm-disks min_size 1

# 3. Enable RBD application on pool
ceph osd pool application enable vm-disks rbd

# 4. Register in Proxmox
pvesm add rbd vm-disks \
  --monhost 10.220.2.7,10.220.2.8,10.220.2.9 \
  --content images,rootdir \
  --pool vm-disks
```

### PG autoscaling

Ceph Squid enables PG autoscaling by default. To check:

```bash
ceph osd pool autoscale-status
# Shows current_pg, target_pg, ratio for each pool
```

If a pool has too many or too few PGs:
```bash
ceph osd pool set <pool_name> pg_autoscale_mode on
```

## Monitor Operations

```bash
ceph mon stat             # Monitor quorum members
ceph mon dump             # Monitor addresses
```

### Add a monitor

```bash
# Via pveceph (preferred — handles all steps)
pveceph createmon <hostname>

# Wait for quorum to include new mon:
ceph mon stat  # Should show +1 member
```

### Monitor split-brain recovery

Symptom: `ceph -s` shows "mon is allowing insecure global_id reclaim" or monitors disagree on cluster state.

```bash
# Check which mons think they're in quorum
ceph quorum_status

# If /etc/hosts has stale IPs for cluster nodes, corosync/mons lose each other
# Fix: update /etc/hosts on ALL nodes with correct IPs for all members
# Then restart corosync: systemctl restart corosync
```

## Network Considerations

### Ceph cluster network (10.220.2.0/24)

All OSD replication and heartbeat traffic uses the 10.220.2.x network via vmbr1.

Each Proxmox node has:
- Physical 10GbE NIC → vmbr1 bridge → 10.220.2.x IP
- The NIC name varies: `nic0`, `nic4` — defined per host in `host_vars`

Verify Ceph is using the cluster network:
```bash
ceph config get osd cluster_network  # Should show 10.220.2.0/24
```

### Check OSD latency

High latency suggests Ceph network congestion or disk issues:
```bash
ceph osd perf          # Per-OSD apply/commit latency
```

## Backup Considerations

PBS (Proxmox Backup Server) uses `ceph-bulk` storage (HDD pool) for backups. The PBS VM (VMID 202) runs on r720xd.

Backup schedule: daily at 02:00, snapshot mode, zstd compression
Retention: 7 daily, 4 weekly, 3 monthly
