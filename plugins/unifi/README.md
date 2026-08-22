# UniFi Plugin

Claude Code plugin for managing UniFi Network infrastructure and UniFi Protect cameras via the UniFi OS API. Follows the PagerDuty/Slack CLI pattern for full auditability — no MCP server, no third-party dependencies beyond `requests`.

## Skills

| Skill | Script | Purpose |
|---|---|---|
| `unifi-network` | `unifi_network_client.py` | Devices, clients, VLANs, firewall, traffic routes, port forwards, WLANs, VPN, DNS, DHCP, stats, backup |
| `unifi-protect` | `unifi_protect_client.py` | Cameras, liveviews, lights, sensors, chimes, viewers |

## Setup

### 1. Generate API Key

In UniFi OS → Settings → API Keys, generate a new key with appropriate scope.

### 2. Set Environment Variables

```bash
export UNIFI_API_KEY="your-api-key"    # required
export UNIFI_HOST="192.0.2.1"          # required, no default
export UNIFI_SITE="default"            # optional, default: default (network only)
```

### 3. Install Dependencies

```bash
pip install requests
```

## Safety: Dry-Run by Default

**All write operations preview without executing.** Pass `--confirm` to execute:

```bash
# Shows what WOULD happen (safe to run anytime)
python unifi_network_client.py firewall create --json '{"name":"Block IoT","action":"drop"}'

# Actually creates the rule
python unifi_network_client.py firewall create --json '{"name":"Block IoT","action":"drop"}' --confirm
```

Dry-run output:
```json
{
  "dry_run": true,
  "action": "POST",
  "endpoint": "https://<UNIFI_HOST>/proxy/network/api/s/default/rest/firewallrule",
  "message": "Pass --confirm to execute this operation",
  "payload": {"name": "Block IoT", "action": "drop"}
}
```

## Network Client

```bash
# Devices
python unifi_network_client.py devices list
python unifi_network_client.py devices get --mac aa:bb:cc:dd:ee:ff
python unifi_network_client.py devices restart --mac aa:bb:cc:dd:ee:ff --confirm
python unifi_network_client.py devices adopt --mac aa:bb:cc:dd:ee:ff --confirm
python unifi_network_client.py devices forget --mac aa:bb:cc:dd:ee:ff --confirm
python unifi_network_client.py devices upgrade --mac aa:bb:cc:dd:ee:ff --confirm
python unifi_network_client.py devices locate --mac aa:bb:cc:dd:ee:ff --confirm

# Clients
python unifi_network_client.py clients list
python unifi_network_client.py clients list-history --limit 200
python unifi_network_client.py clients get --mac aa:bb:cc:dd:ee:ff
python unifi_network_client.py clients block --mac aa:bb:cc:dd:ee:ff --confirm
python unifi_network_client.py clients unblock --mac aa:bb:cc:dd:ee:ff --confirm
python unifi_network_client.py clients kick --mac aa:bb:cc:dd:ee:ff --confirm

# Networks (VLANs)
python unifi_network_client.py networks list
python unifi_network_client.py networks get --id <id>
python unifi_network_client.py networks create --json '{"name":"IoT","purpose":"corporate","vlan":30}' --confirm
python unifi_network_client.py networks update --id <id> --json '{"name":"IoT-Updated"}' --confirm
python unifi_network_client.py networks delete --id <id> --confirm

# Firewall Rules
python unifi_network_client.py firewall list
python unifi_network_client.py firewall get --id <id>
python unifi_network_client.py firewall create --json '{"name":"Block IoT","action":"drop","ruleset":"LAN_IN"}' --confirm
python unifi_network_client.py firewall update --id <id> --json '{"enabled":false}' --confirm
python unifi_network_client.py firewall delete --id <id> --confirm

# Traffic Routes
python unifi_network_client.py traffic-routes list
python unifi_network_client.py traffic-routes get --id <id>
python unifi_network_client.py traffic-routes create --json '{"name":"IoT via VPN","enabled":true}' --confirm
python unifi_network_client.py traffic-routes update --id <id> --json '{"enabled":false}' --confirm
python unifi_network_client.py traffic-routes delete --id <id> --confirm

# Port Forwards
python unifi_network_client.py port-forwards list
python unifi_network_client.py port-forwards get --id <id>
python unifi_network_client.py port-forwards create --json '{"name":"Plex","fwd":"192.0.2.50","fwd_port":32400,"dst_port":32400,"proto":"tcp"}' --confirm
python unifi_network_client.py port-forwards update --id <id> --json '{"enabled":false}' --confirm
python unifi_network_client.py port-forwards delete --id <id> --confirm

# WLANs
python unifi_network_client.py wlans list
python unifi_network_client.py wlans get --id <id>
python unifi_network_client.py wlans update --id <id> --json '{"enabled":false}' --confirm

# VPN
python unifi_network_client.py vpn list-clients
python unifi_network_client.py vpn list-servers
python unifi_network_client.py vpn get --id <id>

# DNS (Static Records)
python unifi_network_client.py dns list
python unifi_network_client.py dns get --id <id>
python unifi_network_client.py dns create --json '{"key":"proxmox.home","value":"192.0.2.7","record_type":"A"}' --confirm
python unifi_network_client.py dns update --id <id> --json '{"value":"192.0.2.8"}' --confirm
python unifi_network_client.py dns delete --id <id> --confirm

# DHCP Leases
python unifi_network_client.py dhcp list-leases

# Stats & Health
python unifi_network_client.py stats health
python unifi_network_client.py stats sysinfo
python unifi_network_client.py stats dpi
python unifi_network_client.py stats alarms
python unifi_network_client.py stats events --limit 20

# Backup
python unifi_network_client.py backup list
python unifi_network_client.py backup create --confirm
```

## Protect Client

```bash
# Cameras
python unifi_protect_client.py cameras list
python unifi_protect_client.py cameras get --id <camera_id>
python unifi_protect_client.py cameras snapshot --id <camera_id> --output /tmp/snap.jpg
python unifi_protect_client.py cameras snapshot --id <camera_id>   # base64 JSON output
python unifi_protect_client.py cameras update --id <camera_id> --json '{"name":"Driveway"}' --confirm

# Liveviews
python unifi_protect_client.py liveviews list
python unifi_protect_client.py liveviews get --id <id>
python unifi_protect_client.py liveviews create --json '{"name":"Security","slots":[]}' --confirm
python unifi_protect_client.py liveviews update --id <id> --json '{"name":"Renamed"}' --confirm
python unifi_protect_client.py liveviews delete --id <id> --confirm

# Lights
python unifi_protect_client.py lights list
python unifi_protect_client.py lights get --id <id>
python unifi_protect_client.py lights update --id <id> --json '{"lightModeSettings":{"mode":"motion"}}' --confirm

# Sensors
python unifi_protect_client.py sensors list
python unifi_protect_client.py sensors get --id <id>
python unifi_protect_client.py sensors update --id <id> --json '{"name":"Garage Door"}' --confirm

# Chimes
python unifi_protect_client.py chimes list
python unifi_protect_client.py chimes get --id <id>
python unifi_protect_client.py chimes update --id <id> --json '{"volume":50}' --confirm

# Viewers
python unifi_protect_client.py viewers list
python unifi_protect_client.py viewers get --id <id>
python unifi_protect_client.py viewers update --id <id> --json '{"liveview":"<liveview_id>"}' --confirm
```

## API Notes

- **Auth**: `X-Api-Key` header bypasses CSRF token requirement on UniFi OS 3.x+
- **SSL**: UDM uses a self-signed certificate; SSL verification is disabled by default with warnings suppressed
- **Site**: Network API uses site-scoped endpoints (`/api/s/{site}/`); Protect API is site-agnostic
- **API versions**: Most network endpoints use v1 (`/proxy/network/api/s/{site}/`); traffic routes and static DNS use v2 (`/proxy/network/v2/api/site/{site}/`). Protect uses the Integration API (`/proxy/protect/integration/v1`)

## Testing

```bash
# Run all UniFi tests
pytest tests/test_unifi_network_client.py tests/test_unifi_protect_client.py -v

# Run with coverage
pytest tests/test_unifi_network_client.py tests/test_unifi_protect_client.py --cov=plugins/unifi
```

## Smoke Tests (requires live UDM)

```bash
export UNIFI_API_KEY="your-key"

# Network
python plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py stats health
python plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py devices list

# Protect
python plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py cameras list
```
