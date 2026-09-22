# Metric Registry — Olympus Cluster Exporters

Known metric names per exporter, including version-specific changes.

## node_exporter (All Proxmox nodes + VMs)

Port: `9100`
Scrape interval: 15s

### Key metrics

| Metric | Description |
|--------|-------------|
| `node_cpu_seconds_total` | CPU time by mode (idle, user, system, iowait) |
| `node_memory_MemAvailable_bytes` | Available RAM |
| `node_memory_MemTotal_bytes` | Total RAM |
| `node_filesystem_avail_bytes` | Disk space available |
| `node_filesystem_size_bytes` | Total disk size |
| `node_network_receive_bytes_total` | Network RX bytes |
| `node_network_transmit_bytes_total` | Network TX bytes |
| `node_load1`, `node_load5`, `node_load15` | System load averages |
| `node_disk_read_bytes_total` | Disk read bytes |
| `node_disk_written_bytes_total` | Disk write bytes |

### Common label values
- `instance`: `<hostname>:9100` (e.g., `r420.infiquetra.com:9100`)
- `job`: `node`

---

## pve-exporter (Proxmox VE metrics)

Port: `8082` (path: `/pve`)
Scrape config: per-node target with `module: default`

### Key metrics

| Metric | Description |
|--------|-------------|
| `pve_up` | Node/VM up status (1=up) |
| `pve_cpu_usage_ratio` | CPU usage fraction (0-1) |
| `pve_memory_usage_bytes` | Memory used |
| `pve_memory_size_bytes` | Memory configured |
| `pve_disk_usage_bytes` | Disk used |
| `pve_disk_size_bytes` | Disk configured |
| `pve_network_transmit_bytes_total` | VM network TX |
| `pve_network_receive_bytes_total` | VM network RX |

### Common label values
- `id`: `qemu/<vmid>` or `node/<hostname>` (e.g., `qemu/100`, `node/r820`)
- `name`: VM name or hostname
- `node`: Proxmox node hostname

---

## ceph-exporter (Ceph cluster metrics)

Port: `9283`
Must run on a node with access to Ceph admin socket.

### Key metrics

| Metric | Description |
|--------|-------------|
| `ceph_health_status` | 0=OK, 1=WARN, 2=ERR |
| `ceph_osd_up` | Per-OSD up status |
| `ceph_osd_in` | Per-OSD in-cluster status |
| `ceph_osd_stat_bytes` | OSD total capacity |
| `ceph_osd_stat_bytes_used` | OSD used capacity |
| `ceph_pool_bytes_used` | Pool data used |
| `ceph_pool_max_avail` | Pool available space |
| `ceph_mon_quorum_status` | Monitor quorum health |
| `ceph_pg_total` | Total placement groups |
| `ceph_pg_active` | Active PGs |
| `ceph_pg_clean` | Clean PGs |

### Label values
- `osd`: OSD ID number
- `pool_id`: Ceph pool ID
- `name`: Pool name

---

## ipmi-exporter (iDRAC hardware metrics)

Port: `9290`
Targets: iDRAC IPs per host (10.220.1.17-22)
Config: `/etc/ipmi_exporter/config.yml`

### Key metrics

| Metric | Description |
|--------|-------------|
| `ipmi_up` | Successful IPMI connection |
| `ipmi_temperature_celsius` | Temperature sensors |
| `ipmi_fan_speed_rpm` | Fan RPM |
| `ipmi_power_watts` | Power consumption |
| `ipmi_voltage_volts` | Voltage rails |
| `ipmi_chassis_power_state` | Power state (1=on) |

### Config field names (IMPORTANT)

The ipmi_exporter config uses `pass` not `password`:

```yaml
modules:
  default:
    user: root
    pass: "{{ vault_idrac_password }}"   # 'pass', NOT 'password'
```

---

## pbs-exporter (Proxmox Backup Server)

Port: `9101` (or custom)
Target: PBS API at `https://10.220.1.62:8007`
Auth: API token with **Admin** role (DatastoreAudit is insufficient for /nodes endpoint)

### Key metrics

| Metric | Description |
|--------|-------------|
| `proxmox_backup_successful_archives` | Successful backup count |
| `proxmox_backup_failed_archives` | Failed backup count |
| `proxmox_backup_last_duration_seconds` | Last backup duration |
| `proxmox_datastore_available_bytes` | PBS datastore free space |
| `proxmox_datastore_total_bytes` | PBS datastore total space |

---

## unifi-poller (UniFi Dream Machine Pro)

Port: Internal only (unifi-poller pushes directly to InfluxDB or Prometheus)
Config: Prometheus mode — exposes `/metrics` at configured port

### Key metrics

| Metric | Description |
|--------|-------------|
| `unifi_device_uptime_seconds` | Device uptime |
| `unifi_device_cpu_utilization_ratio` | UDM CPU usage |
| `unifi_device_mem_utilization_ratio` | UDM memory usage |
| `unifi_client_wireless_bytes_rx_total` | Client RX bytes |
| `unifi_client_wireless_bytes_tx_total` | Client TX bytes |
| `unifi_wlan_num_sta` | Connected WiFi clients |

---

## Recording Rules

Custom recording rules reduce query complexity in dashboards.

Rules file: `roles/monitoring/files/prometheus/recording_rules.yml`

Common pattern — resource utilization ratios:
```yaml
groups:
  - name: node_resource_ratios
    rules:
      - record: instance:node_cpu_utilization:ratio
        expr: 1 - avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
      - record: instance:node_memory_utilization:ratio
        expr: 1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
```

**When adding recording rules**: verify the base metric name exists in Prometheus before creating the rule. A rule that references a non-existent metric silently produces no data.

---

## Alerting Webhooks

Grafana alerts route to Discord via webhook:

```
vault_discord_monitoring_webhook = https://discord.com/api/webhooks/<id>/<token>
```

Alert channel: check the Grafana alerting configuration for which Discord channel receives which severity.
