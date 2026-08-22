# UniFi Network API Endpoints Reference

Two base URL patterns are in play, and which one a resource uses is not a matter of taste:

- v1: `https://<UNIFI_HOST>/proxy/network/api/s/<site>`
- v2: `https://<UNIFI_HOST>/proxy/network/v2/api/site/<site>`

This document is derived from `scripts/unifi_network_client.py` and describes only what that
client calls. All requests send `X-Api-Key` and `Content-Type: application/json`, use a
30-second timeout, and disable TLS verification by default because the UDM presents a
self-signed certificate.

---

## Devices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/stat/device` | List all adopted devices |
| GET | `/proxy/network/api/s/{site}/stat/device/{mac}` | Get device by MAC address |
| POST | `/proxy/network/api/s/{site}/cmd/devmgr` | Device management commands |

**Device management command bodies** — one per action, exactly as the client sends them:
```json
{ "cmd": "restart", "mac": "aa:bb:cc:dd:ee:ff" }
{ "cmd": "adopt",   "mac": "aa:bb:cc:dd:ee:ff" }
{ "cmd": "forget",  "mac": "aa:bb:cc:dd:ee:ff" }
{ "cmd": "upgrade", "mac": "aa:bb:cc:dd:ee:ff" }
{ "cmd": "locate",  "mac": "aa:bb:cc:dd:ee:ff" }
```

The locate command is a single `locate` verb. It is not the `set-locate` / `unset-locate`
pair an earlier revision of this document described, and the client sends no such body.

---

## Clients

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/stat/sta` | List active (currently connected) clients |
| GET | `/proxy/network/api/s/{site}/stat/alluser` | List clients including historical |
| GET | `/proxy/network/api/s/{site}/stat/sta/{mac}` | Get one client by MAC address |
| POST | `/proxy/network/api/s/{site}/cmd/stamgr` | Client management commands |

**History query params**: `?within=168&_limit=<limit>` — a fixed 168-hour window, with
`_limit` defaulting to 200.

**Client management command bodies**:
```json
{ "cmd": "block-sta",   "mac": "aa:bb:cc:dd:ee:ff" }
{ "cmd": "unblock-sta", "mac": "aa:bb:cc:dd:ee:ff" }
{ "cmd": "kick-sta",    "mac": "aa:bb:cc:dd:ee:ff" }
```

---

## Networks (VLANs / Network Configurations)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/rest/networkconf` | List all network configurations |
| GET | `/proxy/network/api/s/{site}/rest/networkconf/{id}` | Get a network by ID |
| POST | `/proxy/network/api/s/{site}/rest/networkconf` | Create a new network |
| PUT | `/proxy/network/api/s/{site}/rest/networkconf/{id}` | Update a network by ID |
| DELETE | `/proxy/network/api/s/{site}/rest/networkconf/{id}` | Delete a network by ID |

**Network create body example**:
```json
{
  "name": "IoT",
  "purpose": "corporate",
  "vlan": 30,
  "ip_subnet": "198.51.100.1/24",
  "dhcpd_enabled": true,
  "dhcpd_start": "198.51.100.100",
  "dhcpd_stop": "198.51.100.254"
}
```

---

## Firewall Rules

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/rest/firewallrule` | List all firewall rules |
| GET | `/proxy/network/api/s/{site}/rest/firewallrule/{id}` | Get a firewall rule by ID |
| POST | `/proxy/network/api/s/{site}/rest/firewallrule` | Create a firewall rule |
| PUT | `/proxy/network/api/s/{site}/rest/firewallrule/{id}` | Update a firewall rule |
| DELETE | `/proxy/network/api/s/{site}/rest/firewallrule/{id}` | Delete a firewall rule |

**Firewall rule body example**:
```json
{
  "name": "Block IoT to LAN",
  "ruleset": "LAN_IN",
  "rule_index": 2000,
  "action": "drop",
  "enabled": true,
  "src_networkconf_id": "<iot_network_id>",
  "dst_networkconf_id": "<lan_network_id>",
  "protocol": "all"
}
```

**Ruleset values**: `LAN_IN`, `LAN_OUT`, `LAN_LOCAL`, `WAN_IN`, `WAN_OUT`, `WAN_LOCAL`,
`GUEST_IN`, `GUEST_OUT`, `GUEST_LOCAL`

---

## Traffic Routes

Traffic routes are a v2 resource. An earlier revision of this document placed them at the v1
`/rest/routing` path, which the client has never called.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/v2/api/site/{site}/trafficroutes` | List all traffic routes |
| GET | `/proxy/network/v2/api/site/{site}/trafficroutes/{id}` | Get a traffic route by ID |
| POST | `/proxy/network/v2/api/site/{site}/trafficroutes` | Create a traffic route |
| PUT | `/proxy/network/v2/api/site/{site}/trafficroutes/{id}` | Update a traffic route |
| DELETE | `/proxy/network/v2/api/site/{site}/trafficroutes/{id}` | Delete a traffic route |

---

## Port Forwards

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/rest/portforward` | List all port forwards |
| GET | `/proxy/network/api/s/{site}/rest/portforward/{id}` | Get a port forward by ID |
| POST | `/proxy/network/api/s/{site}/rest/portforward` | Create a port forward |
| PUT | `/proxy/network/api/s/{site}/rest/portforward/{id}` | Update a port forward |
| DELETE | `/proxy/network/api/s/{site}/rest/portforward/{id}` | Delete a port forward |

**Port forward body example**:
```json
{
  "name": "Plex",
  "fwd": "192.0.2.50",
  "fwd_port": "32400",
  "dst_port": "32400",
  "proto": "tcp",
  "enabled": true
}
```

---

## WLANs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/rest/wlanconf` | List all wireless networks |
| GET | `/proxy/network/api/s/{site}/rest/wlanconf/{id}` | Get a wireless network by ID |
| PUT | `/proxy/network/api/s/{site}/rest/wlanconf/{id}` | Update a wireless network |

The client creates and deletes no wireless network. Only list, get, and update exist.

---

## VPN

Three distinct paths, and the earlier `/stat/vpn` path this document named was not one of
them.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/stat/vpnconn` | List active VPN client connections |
| GET | `/proxy/network/api/s/{site}/rest/vpnconn` | List configured VPN servers |
| GET | `/proxy/network/api/s/{site}/rest/vpnconn/{id}` | Get one VPN configuration by ID |

Every VPN action is read-only.

---

## DNS (Static Host Records)

Static DNS is a v2 resource with its own collection. An earlier revision of this document
routed it through the v1 `/rest/setting/dnsmasq` settings object, which the client has never
called.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/v2/api/site/{site}/static-dns` | List all static DNS records |
| GET | `/proxy/network/v2/api/site/{site}/static-dns/{id}` | Get a static DNS record by ID |
| POST | `/proxy/network/v2/api/site/{site}/static-dns` | Create a static DNS record |
| PUT | `/proxy/network/v2/api/site/{site}/static-dns/{id}` | Update a static DNS record |
| DELETE | `/proxy/network/v2/api/site/{site}/static-dns/{id}` | Delete a static DNS record |

**DNS record body example**:
```json
{
  "key": "proxmox.home",
  "value": "192.0.2.7",
  "record_type": "A"
}
```

---

## DHCP Leases

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/stat/dhcp` | List active DHCP leases |

The path is `stat/dhcp`. It is not `stat/dhcp_lease`, which an earlier revision named.

---

## Stats & Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/stat/health` | Network subsystem health summary |
| GET | `/proxy/network/api/s/{site}/stat/sysinfo` | System info (firmware version, uptime) |
| GET | `/proxy/network/api/s/{site}/stat/dpi` | Deep packet inspection statistics |
| GET | `/proxy/network/api/s/{site}/stat/event` | Recent network events |
| GET | `/proxy/network/api/s/{site}/list/alarm` | Active alarms |

**Event query params**: `?_limit=<limit>`, defaulting to 50.

Alarms are served from `list/alarm`, not from `stat/alarm`.

---

## Backup

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/network/api/s/{site}/stat/backup` | List available backup files |
| POST | `/proxy/network/api/s/{site}/cmd/backup` | Trigger a backup |

**Backup command body**:
```json
{ "cmd": "backup" }
```

The trigger path is `cmd/backup`, not `cmd/system`, and the client downloads no backup file.

---

## Response Handling

The client maps controller responses to a fixed JSON surface and exits non-zero on failure.

| Status | Client behavior |
|--------|-----------------|
| 429 | Retries with bounded exponential backoff, honoring `Retry-After` (default 60 seconds). On exhaustion, emits a typed rate-limit error and exits 1 |
| 401 | API key invalid or expired, exit 1 |
| 403 | Insufficient permissions, exit 1 |
| 404 | Resource not found, exit 1 |
| 4xx (other) | `API error: <status>`, exit 1 |
| 5xx | `Controller error: <status>`, exit 1 |

---

## API Version Notes

- **UniFi OS 3.x+**: Use the `X-Api-Key` header with a generated API key. No session cookie
  or CSRF token is required.
- **UniFi OS 2.x and earlier**: Requires session-based auth and an `X-Csrf-Token` header.
  Not supported by this client.
- **v1 versus v2**: Everything uses the v1 path except traffic routes and static DNS, which
  are v2. That split is read off the client, not assumed.
- **Site**: taken from `--site`, else `UNIFI_SITE`, else `default`.
- **Host**: taken from `--host`, else `UNIFI_HOST`. There is no default; an absent or
  empty value exits 1 with a structured error before any request is sent.
- **Dry run**: `POST`, `PUT`, `PATCH`, and `DELETE` print their method, URL, and payload and
  exit 0 unless `--confirm` is passed. `GET` is never gated.
