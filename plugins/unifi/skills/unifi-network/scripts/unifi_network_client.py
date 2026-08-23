#!/usr/bin/env python3
"""
UniFi Network CLI - Command-line interface for UniFi Network API operations.

Manages UniFi network devices, clients, VLANs, firewall rules, traffic routes,
port forwards, VPN, DNS, DHCP, and network stats via the UniFi OS API.

Environment Variables:
    UNIFI_API_KEY: UniFi OS API key (required)
    UNIFI_HOST: UniFi controller IP or hostname (required; no default)
    UNIFI_SITE: UniFi site name (default: default)

Usage:
    python unifi_network_client.py devices list
    python unifi_network_client.py clients block --mac aa:bb:cc:dd:ee:ff --confirm
    python unifi_network_client.py networks create --json '{"name":"IoT","purpose":"corporate","vlan":30}' --confirm
    python unifi_network_client.py stats health
"""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import requests
except ImportError:
    print(
        json.dumps(
            {
                "error": "requests library not installed",
                "message": "Install with: pip install requests",
                "install_command": "pip install requests",
            }
        )
    )
    sys.exit(1)


# Shared 429 retry/backoff primitive via fleet-commons (#348 / DECISIONS {#fleet-commons-mechanism-463}).
sys.path.insert(0, str(Path(__file__).resolve().parent / "_bundled"))
# The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose
# resolution ladder is Claude-specific runtime discovery this package must not
# retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on
# disk at install time and Fleet Core is never installed separately.
import retry_backoff as _retry_backoff  # noqa: E402  (after the sys.path shim, by design)


class _RateLimited(Exception):  # noqa: N818 - a sentinel, not an error surface
    """A 429 raised inside the retry wrapper so ``retry_with_backoff`` backs off + retries (#348).

    ``retry_after`` is the server hint already reduced to seconds by the shared
    ``parse_retry_after`` (which accepts both RFC 7231 forms), or ``None`` when the response
    carried no usable hint — the primitive reads ``None`` as "no hint" and answers with its
    computed jittered backoff.
    """

    def __init__(self, retry_after: float | None) -> None:
        hint = "an unspecified delay" if retry_after is None else f"{retry_after}s"
        super().__init__(f"rate limited; retry after {hint}")
        self.status_code = 429
        self.retry_after = retry_after


class UnifiNetworkClient:
    """Wrapper for UniFi Network API operations with JSON output."""

    def __init__(
        self,
        api_key: str | None = None,
        host: str | None = None,
        site: str | None = None,
        verify_ssl: bool = False,
    ):
        """Initialize the UniFi Network client.

        Args:
            api_key: UniFi OS API key (defaults to UNIFI_API_KEY env var)
            host: controller IP or hostname (defaults to the UNIFI_HOST env var;
                required, and an absent or empty value exits 1)
            site: UniFi site name (defaults to UNIFI_SITE env var or default)
            verify_ssl: Whether to verify SSL certificates (default: False)
        """
        self.api_key = api_key or os.getenv("UNIFI_API_KEY")
        if not self.api_key:
            self._error("UNIFI_API_KEY environment variable not set")
            sys.exit(1)

        # The controller address has no baked-in default. One used to ship here, which
        # meant every installation carried one operator's address, and substituting a
        # different address would only move that problem rather than remove it. An absent
        # host now fails exactly the way an absent API key does, before any network call.
        # The empty string is absent, not a value: without the strip, an unset-but-present
        # UNIFI_HOST built the malformed URL "https:///proxy/network/...".
        self.host = (host or os.getenv("UNIFI_HOST") or "").strip()
        if not self.host:
            self._error(
                "UNIFI_HOST environment variable not set; "
                "pass --host or set UNIFI_HOST to the controller address"
            )
            sys.exit(1)

        self.site = site or os.getenv("UNIFI_SITE", "default")
        self.verify_ssl = verify_ssl
        self.base_v1 = f"https://{self.host}/proxy/network/api/s/{self.site}"
        self.base_v2 = f"https://{self.host}/proxy/network/v2/api/site/{self.site}"
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _error(self, message: str, **kwargs) -> None:
        """Output error in JSON format."""
        error_data = {"error": True, "message": message}
        error_data.update(kwargs)
        print(json.dumps(error_data, indent=2))

    def _success(self, data: Any, **kwargs) -> None:
        """Output success data in JSON format."""
        output = {"success": True, "data": data}
        output.update(kwargs)
        print(json.dumps(output, indent=2, default=str))

    def _dry_run(self, action: str, endpoint: str, data: dict[str, Any] | None = None) -> None:
        """Output dry-run information in JSON format."""
        output: dict[str, Any] = {
            "dry_run": True,
            "action": action,
            "endpoint": endpoint,
            "message": "Pass --confirm to execute this operation",
        }
        if data:
            output["payload"] = data
        print(json.dumps(output, indent=2))

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        confirm: bool = True,
    ) -> dict[str, Any]:
        """Make HTTP request to UniFi Network API with error handling.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            url: Full URL to request
            params: Query parameters
            data: Request body data
            confirm: Whether write operations should proceed (default: True)

        Returns:
            Response data as dict

        Raises:
            sys.exit on error or dry-run
        """
        if method in ("POST", "PUT", "PATCH", "DELETE") and not confirm:
            self._dry_run(method, url, data)
            sys.exit(0)

        def _do_request() -> Any:
            resp = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                json=data,
                timeout=30,
                verify=self.verify_ssl,
            )
            # A 429 is raised so the shared primitive backs off + retries (#348); a Retry-After
            # hint is honored. The hint goes through the shared ``parse_retry_after`` so BOTH
            # RFC 7231 forms work: a raw HTTP-date used to raise ValueError inside ``int()``, and
            # that ValueError carries no 429 status, so the primitive judged it non-retryable and
            # propagated it — one request, no backoff, a generic "Unexpected error" for the
            # operator. An absent or unparseable hint parses to None, meaning computed backoff.
            # All other statuses flow through unchanged to the handling below.
            if resp.status_code == 429:
                hint = _retry_backoff.parse_retry_after(resp.headers.get("Retry-After"))
                raise _RateLimited(hint)
            return resp

        try:
            try:
                response = _retry_backoff.retry_with_backoff(
                    _do_request,
                    retry_after=lambda exc: getattr(exc, "retry_after", None),
                    sleep=time.sleep,
                )
            except _RateLimited as exc:
                # Retries exhausted — preserve the existing typed-error + exit surface: whole
                # seconds, and the long-standing 60 when the controller gave no usable hint.
                advice = 60 if exc.retry_after is None else math.ceil(exc.retry_after)
                self._error(
                    f"Rate limited. Retry after {advice} seconds",
                    status_code=429,
                    retry_after=advice,
                )
                sys.exit(1)

            if response.status_code == 401:
                self._error("API key invalid or expired", status_code=401)
                sys.exit(1)

            if response.status_code == 403:
                self._error("Insufficient permissions. Check API key scope.", status_code=403)
                sys.exit(1)

            if response.status_code == 404:
                self._error("Resource not found. Verify ID/MAC.", status_code=404)
                sys.exit(1)

            if response.status_code >= 500:
                self._error(
                    f"Controller error: {response.status_code}",
                    status_code=response.status_code,
                )
                sys.exit(1)

            if response.status_code >= 400:
                error_msg = f"API error: {response.status_code}"
                try:
                    error_data = response.json()
                    if "message" in error_data:
                        error_msg = error_data["message"]
                    elif "meta" in error_data and "msg" in error_data["meta"]:
                        error_msg = error_data["meta"]["msg"]
                except (ValueError, KeyError):
                    pass
                self._error(error_msg, status_code=response.status_code)
                sys.exit(1)

            # 204 No Content — success with no body
            if response.status_code == 204 or not response.content:
                return {}

            return cast(dict[str, Any], response.json())

        except requests.exceptions.Timeout:
            self._error("Request timeout after 30 seconds")
            sys.exit(1)
        except requests.exceptions.SSLError:
            self._error("SSL verification failed. Set verify_ssl=True or check certificate.")
            sys.exit(1)
        except requests.exceptions.ConnectionError:
            self._error(f"Cannot reach UDM at {self.host}. Check network connectivity.")
            sys.exit(1)
        except Exception as e:
            self._error(f"Unexpected error: {str(e)}")
            sys.exit(1)

    # ===========================
    # DEVICES
    # ===========================

    def devices_list(self) -> None:
        """List all adopted devices on the site."""
        url = f"{self.base_v1}/stat/device"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def devices_get(self, mac: str) -> None:
        """Get details for a specific device by MAC address.

        Args:
            mac: Device MAC address
        """
        url = f"{self.base_v1}/stat/device/{mac}"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data[0] if data else {})

    def devices_restart(self, mac: str, confirm: bool = False) -> None:
        """Restart a device.

        Args:
            mac: Device MAC address
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/devmgr"
        payload = {"cmd": "restart", "mac": mac}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message=f"Device {mac} restart initiated")

    def devices_adopt(self, mac: str, confirm: bool = False) -> None:
        """Adopt a device.

        Args:
            mac: Device MAC address
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/devmgr"
        payload = {"cmd": "adopt", "mac": mac}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message=f"Device {mac} adoption initiated")

    def devices_forget(self, mac: str, confirm: bool = False) -> None:
        """Forget (remove) a device.

        Args:
            mac: Device MAC address
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/devmgr"
        payload = {"cmd": "forget", "mac": mac}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message=f"Device {mac} forgotten")

    def devices_upgrade(self, mac: str, confirm: bool = False) -> None:
        """Upgrade firmware on a device.

        Args:
            mac: Device MAC address
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/devmgr"
        payload = {"cmd": "upgrade", "mac": mac}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message=f"Device {mac} firmware upgrade initiated")

    def devices_locate(self, mac: str, confirm: bool = False) -> None:
        """Toggle locate (blink LEDs) on a device.

        Args:
            mac: Device MAC address
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/devmgr"
        payload = {"cmd": "locate", "mac": mac}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message=f"Device {mac} locate toggled")

    # ===========================
    # CLIENTS
    # ===========================

    def clients_list(self) -> None:
        """List currently active/connected clients."""
        url = f"{self.base_v1}/stat/sta"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def clients_list_history(self, limit: int = 200) -> None:
        """List client history (last 7 days).

        Args:
            limit: Maximum number of clients to return (default: 200)
        """
        url = f"{self.base_v1}/stat/alluser"
        params = {"within": 168, "_limit": limit}
        response = self._request("GET", url, params=params)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def clients_get(self, mac: str) -> None:
        """Get details for a specific active client by MAC address.

        Args:
            mac: Client MAC address
        """
        url = f"{self.base_v1}/stat/sta/{mac}"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data[0] if data else {})

    def clients_block(self, mac: str, confirm: bool = False) -> None:
        """Block a client from the network.

        Args:
            mac: Client MAC address
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/stamgr"
        payload = {"cmd": "block-sta", "mac": mac}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message=f"Client {mac} blocked")

    def clients_unblock(self, mac: str, confirm: bool = False) -> None:
        """Unblock a client.

        Args:
            mac: Client MAC address
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/stamgr"
        payload = {"cmd": "unblock-sta", "mac": mac}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message=f"Client {mac} unblocked")

    def clients_kick(self, mac: str, confirm: bool = False) -> None:
        """Kick (disconnect) a client from the network.

        Args:
            mac: Client MAC address
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/stamgr"
        payload = {"cmd": "kick-sta", "mac": mac}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message=f"Client {mac} kicked")

    # ===========================
    # NETWORKS
    # ===========================

    def networks_list(self) -> None:
        """List all network configurations."""
        url = f"{self.base_v1}/rest/networkconf"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def networks_get(self, network_id: str) -> None:
        """Get a specific network configuration.

        Args:
            network_id: Network configuration ID
        """
        url = f"{self.base_v1}/rest/networkconf/{network_id}"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data[0] if data else {})

    def networks_create(self, data: dict[str, Any], confirm: bool = False) -> None:
        """Create a new network configuration.

        Args:
            data: Network configuration payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/networkconf"
        response = self._request("POST", url, data=data, confirm=confirm)
        result = response.get("data", [{}])
        self._success(result[0] if result else {}, message="Network created")

    def networks_update(self, network_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update a network configuration.

        Args:
            network_id: Network configuration ID
            data: Updated network configuration payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/networkconf/{network_id}"
        response = self._request("PUT", url, data=data, confirm=confirm)
        result = response.get("data", [{}])
        self._success(result[0] if result else {}, message=f"Network {network_id} updated")

    def networks_delete(self, network_id: str, confirm: bool = False) -> None:
        """Delete a network configuration.

        Args:
            network_id: Network configuration ID
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/networkconf/{network_id}"
        self._request("DELETE", url, confirm=confirm)
        self._success({}, message=f"Network {network_id} deleted")

    # ===========================
    # FIREWALL
    # ===========================

    def firewall_list(self) -> None:
        """List all firewall rules."""
        url = f"{self.base_v1}/rest/firewallrule"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def firewall_get(self, rule_id: str) -> None:
        """Get a specific firewall rule.

        Args:
            rule_id: Firewall rule ID
        """
        url = f"{self.base_v1}/rest/firewallrule/{rule_id}"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data[0] if data else {})

    def firewall_create(self, data: dict[str, Any], confirm: bool = False) -> None:
        """Create a new firewall rule.

        Args:
            data: Firewall rule payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/firewallrule"
        response = self._request("POST", url, data=data, confirm=confirm)
        result = response.get("data", [{}])
        self._success(result[0] if result else {}, message="Firewall rule created")

    def firewall_update(self, rule_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update a firewall rule.

        Args:
            rule_id: Firewall rule ID
            data: Updated firewall rule payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/firewallrule/{rule_id}"
        response = self._request("PUT", url, data=data, confirm=confirm)
        result = response.get("data", [{}])
        self._success(result[0] if result else {}, message=f"Firewall rule {rule_id} updated")

    def firewall_delete(self, rule_id: str, confirm: bool = False) -> None:
        """Delete a firewall rule.

        Args:
            rule_id: Firewall rule ID
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/firewallrule/{rule_id}"
        self._request("DELETE", url, confirm=confirm)
        self._success({}, message=f"Firewall rule {rule_id} deleted")

    # ===========================
    # TRAFFIC ROUTES (v2)
    # ===========================

    def traffic_routes_list(self) -> None:
        """List all traffic routes."""
        url = f"{self.base_v2}/trafficroutes"
        response = self._request("GET", url)
        # v2 API returns a list directly or wrapped
        data = response if isinstance(response, list) else response.get("data", [])
        self._success(data, count=len(data))

    def traffic_routes_get(self, route_id: str) -> None:
        """Get a specific traffic route.

        Args:
            route_id: Traffic route ID
        """
        url = f"{self.base_v2}/trafficroutes/{route_id}"
        response = self._request("GET", url)
        data = (
            response
            if isinstance(response, dict) and "id" in response
            else response.get("data", {})
        )
        self._success(data)

    def traffic_routes_create(self, data: dict[str, Any], confirm: bool = False) -> None:
        """Create a new traffic route.

        Args:
            data: Traffic route payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v2}/trafficroutes"
        response = self._request("POST", url, data=data, confirm=confirm)
        self._success(response, message="Traffic route created")

    def traffic_routes_update(
        self, route_id: str, data: dict[str, Any], confirm: bool = False
    ) -> None:
        """Update a traffic route.

        Args:
            route_id: Traffic route ID
            data: Updated traffic route payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v2}/trafficroutes/{route_id}"
        response = self._request("PUT", url, data=data, confirm=confirm)
        self._success(response, message=f"Traffic route {route_id} updated")

    def traffic_routes_delete(self, route_id: str, confirm: bool = False) -> None:
        """Delete a traffic route.

        Args:
            route_id: Traffic route ID
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v2}/trafficroutes/{route_id}"
        self._request("DELETE", url, confirm=confirm)
        self._success({}, message=f"Traffic route {route_id} deleted")

    # ===========================
    # PORT FORWARDS
    # ===========================

    def port_forwards_list(self) -> None:
        """List all port forwarding rules."""
        url = f"{self.base_v1}/rest/portforward"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def port_forwards_get(self, forward_id: str) -> None:
        """Get a specific port forwarding rule.

        Args:
            forward_id: Port forward rule ID
        """
        url = f"{self.base_v1}/rest/portforward/{forward_id}"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data[0] if data else {})

    def port_forwards_create(self, data: dict[str, Any], confirm: bool = False) -> None:
        """Create a new port forwarding rule.

        Args:
            data: Port forward rule payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/portforward"
        response = self._request("POST", url, data=data, confirm=confirm)
        result = response.get("data", [{}])
        self._success(result[0] if result else {}, message="Port forward rule created")

    def port_forwards_update(
        self, forward_id: str, data: dict[str, Any], confirm: bool = False
    ) -> None:
        """Update a port forwarding rule.

        Args:
            forward_id: Port forward rule ID
            data: Updated port forward rule payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/portforward/{forward_id}"
        response = self._request("PUT", url, data=data, confirm=confirm)
        result = response.get("data", [{}])
        self._success(
            result[0] if result else {}, message=f"Port forward rule {forward_id} updated"
        )

    def port_forwards_delete(self, forward_id: str, confirm: bool = False) -> None:
        """Delete a port forwarding rule.

        Args:
            forward_id: Port forward rule ID
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/portforward/{forward_id}"
        self._request("DELETE", url, confirm=confirm)
        self._success({}, message=f"Port forward rule {forward_id} deleted")

    # ===========================
    # WLANS
    # ===========================

    def wlans_list(self) -> None:
        """List all WLAN configurations."""
        url = f"{self.base_v1}/rest/wlanconf"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def wlans_get(self, wlan_id: str) -> None:
        """Get a specific WLAN configuration.

        Args:
            wlan_id: WLAN configuration ID
        """
        url = f"{self.base_v1}/rest/wlanconf/{wlan_id}"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data[0] if data else {})

    def wlans_update(self, wlan_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update a WLAN configuration.

        Args:
            wlan_id: WLAN configuration ID
            data: Updated WLAN configuration payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/rest/wlanconf/{wlan_id}"
        response = self._request("PUT", url, data=data, confirm=confirm)
        result = response.get("data", [{}])
        self._success(result[0] if result else {}, message=f"WLAN {wlan_id} updated")

    # ===========================
    # VPN
    # ===========================

    def vpn_list_clients(self) -> None:
        """List active VPN client sessions."""
        url = f"{self.base_v1}/stat/vpnconn"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def vpn_list_servers(self) -> None:
        """List VPN server configurations."""
        url = f"{self.base_v1}/rest/vpnconn"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def vpn_get(self, vpn_id: str) -> None:
        """Get a specific VPN server configuration.

        Args:
            vpn_id: VPN configuration ID
        """
        url = f"{self.base_v1}/rest/vpnconn/{vpn_id}"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data[0] if data else {})

    # ===========================
    # DNS (v2)
    # ===========================

    def dns_list(self) -> None:
        """List all static DNS entries."""
        url = f"{self.base_v2}/static-dns"
        response = self._request("GET", url)
        data = response if isinstance(response, list) else response.get("data", [])
        self._success(data, count=len(data))

    def dns_get(self, dns_id: str) -> None:
        """Get a specific static DNS entry.

        Args:
            dns_id: Static DNS entry ID
        """
        url = f"{self.base_v2}/static-dns/{dns_id}"
        response = self._request("GET", url)
        data = (
            response
            if isinstance(response, dict) and "_id" in response
            else response.get("data", {})
        )
        self._success(data)

    def dns_create(self, data: dict[str, Any], confirm: bool = False) -> None:
        """Create a new static DNS entry.

        Args:
            data: Static DNS entry payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v2}/static-dns"
        response = self._request("POST", url, data=data, confirm=confirm)
        self._success(response, message="Static DNS entry created")

    def dns_update(self, dns_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update a static DNS entry.

        Args:
            dns_id: Static DNS entry ID
            data: Updated static DNS entry payload
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v2}/static-dns/{dns_id}"
        response = self._request("PUT", url, data=data, confirm=confirm)
        self._success(response, message=f"Static DNS entry {dns_id} updated")

    def dns_delete(self, dns_id: str, confirm: bool = False) -> None:
        """Delete a static DNS entry.

        Args:
            dns_id: Static DNS entry ID
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v2}/static-dns/{dns_id}"
        self._request("DELETE", url, confirm=confirm)
        self._success({}, message=f"Static DNS entry {dns_id} deleted")

    # ===========================
    # DHCP
    # ===========================

    def dhcp_list_leases(self) -> None:
        """List all current DHCP leases."""
        url = f"{self.base_v1}/stat/dhcp"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    # ===========================
    # STATS
    # ===========================

    def stats_health(self) -> None:
        """Get site health summary."""
        url = f"{self.base_v1}/stat/health"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data)

    def stats_sysinfo(self) -> None:
        """Get system information."""
        url = f"{self.base_v1}/stat/sysinfo"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data[0] if data else {})

    def stats_dpi(self) -> None:
        """Get deep packet inspection (DPI) statistics."""
        url = f"{self.base_v1}/stat/dpi"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def stats_events(self, limit: int = 50) -> None:
        """Get recent site events.

        Args:
            limit: Maximum number of events to return (default: 50)
        """
        url = f"{self.base_v1}/stat/event"
        params = {"_limit": limit}
        response = self._request("GET", url, params=params)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def stats_alarms(self) -> None:
        """Get active site alarms."""
        url = f"{self.base_v1}/list/alarm"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    # ===========================
    # BACKUP
    # ===========================

    def backup_list(self) -> None:
        """List available backups."""
        url = f"{self.base_v1}/stat/backup"
        response = self._request("GET", url)
        data = response.get("data", [])
        self._success(data, count=len(data))

    def backup_create(self, confirm: bool = False) -> None:
        """Create a new backup.

        Args:
            confirm: Set True to execute (default: dry-run)
        """
        url = f"{self.base_v1}/cmd/backup"
        payload = {"cmd": "backup"}
        response = self._request("POST", url, data=payload, confirm=confirm)
        self._success(response, message="Backup initiated")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="UniFi Network CLI for device and network management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Confirm write operations (POST/PUT/PATCH/DELETE). Without this flag, write ops show a dry-run.",
    )
    parser.add_argument("--host", help="Controller IP or hostname; overrides UNIFI_HOST")
    parser.add_argument("--site", help="Override UNIFI_SITE")
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        default=False,
        help="Enable SSL certificate verification",
    )

    subparsers = parser.add_subparsers(dest="resource", help="Resource type")

    # ===========================
    # DEVICES
    # ===========================
    devices_parser = subparsers.add_parser("devices", help="Manage UniFi devices")
    devices_subparsers = devices_parser.add_subparsers(dest="action", help="Device action")

    devices_subparsers.add_parser("list", help="List all adopted devices")

    devices_get_parser = devices_subparsers.add_parser("get", help="Get device details")
    devices_get_parser.add_argument("--mac", required=True, help="Device MAC address")

    devices_restart_parser = devices_subparsers.add_parser("restart", help="Restart a device")
    devices_restart_parser.add_argument("--mac", required=True, help="Device MAC address")

    devices_adopt_parser = devices_subparsers.add_parser("adopt", help="Adopt a device")
    devices_adopt_parser.add_argument("--mac", required=True, help="Device MAC address")

    devices_forget_parser = devices_subparsers.add_parser("forget", help="Forget a device")
    devices_forget_parser.add_argument("--mac", required=True, help="Device MAC address")

    devices_upgrade_parser = devices_subparsers.add_parser(
        "upgrade", help="Upgrade device firmware"
    )
    devices_upgrade_parser.add_argument("--mac", required=True, help="Device MAC address")

    devices_locate_parser = devices_subparsers.add_parser(
        "locate", help="Toggle locate mode on a device"
    )
    devices_locate_parser.add_argument("--mac", required=True, help="Device MAC address")

    # ===========================
    # CLIENTS
    # ===========================
    clients_parser = subparsers.add_parser("clients", help="Manage network clients")
    clients_subparsers = clients_parser.add_subparsers(dest="action", help="Client action")

    clients_subparsers.add_parser("list", help="List active clients")

    clients_history_parser = clients_subparsers.add_parser(
        "list-history", help="List client history (last 7 days)"
    )
    clients_history_parser.add_argument(
        "--limit", type=int, default=200, help="Maximum number of clients to return (default: 200)"
    )

    clients_get_parser = clients_subparsers.add_parser("get", help="Get client details")
    clients_get_parser.add_argument("--mac", required=True, help="Client MAC address")

    clients_block_parser = clients_subparsers.add_parser("block", help="Block a client")
    clients_block_parser.add_argument("--mac", required=True, help="Client MAC address")

    clients_unblock_parser = clients_subparsers.add_parser("unblock", help="Unblock a client")
    clients_unblock_parser.add_argument("--mac", required=True, help="Client MAC address")

    clients_kick_parser = clients_subparsers.add_parser("kick", help="Kick (disconnect) a client")
    clients_kick_parser.add_argument("--mac", required=True, help="Client MAC address")

    # ===========================
    # NETWORKS
    # ===========================
    networks_parser = subparsers.add_parser("networks", help="Manage network configurations")
    networks_subparsers = networks_parser.add_subparsers(dest="action", help="Network action")

    networks_subparsers.add_parser("list", help="List all networks")

    networks_get_parser = networks_subparsers.add_parser("get", help="Get network details")
    networks_get_parser.add_argument("--id", required=True, help="Network ID")

    networks_create_parser = networks_subparsers.add_parser("create", help="Create a network")
    networks_create_parser.add_argument(
        "--json",
        required=True,
        dest="json_data",
        help='Network configuration JSON (e.g. \'{"name":"IoT","purpose":"corporate","vlan":30}\')',
    )

    networks_update_parser = networks_subparsers.add_parser("update", help="Update a network")
    networks_update_parser.add_argument("--id", required=True, help="Network ID")
    networks_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="Updated network configuration JSON"
    )

    networks_delete_parser = networks_subparsers.add_parser("delete", help="Delete a network")
    networks_delete_parser.add_argument("--id", required=True, help="Network ID")

    # ===========================
    # FIREWALL
    # ===========================
    firewall_parser = subparsers.add_parser("firewall", help="Manage firewall rules")
    firewall_subparsers = firewall_parser.add_subparsers(dest="action", help="Firewall action")

    firewall_subparsers.add_parser("list", help="List all firewall rules")

    firewall_get_parser = firewall_subparsers.add_parser("get", help="Get firewall rule details")
    firewall_get_parser.add_argument("--id", required=True, help="Firewall rule ID")

    firewall_create_parser = firewall_subparsers.add_parser("create", help="Create a firewall rule")
    firewall_create_parser.add_argument(
        "--json", required=True, dest="json_data", help="Firewall rule configuration JSON"
    )

    firewall_update_parser = firewall_subparsers.add_parser("update", help="Update a firewall rule")
    firewall_update_parser.add_argument("--id", required=True, help="Firewall rule ID")
    firewall_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="Updated firewall rule configuration JSON"
    )

    firewall_delete_parser = firewall_subparsers.add_parser("delete", help="Delete a firewall rule")
    firewall_delete_parser.add_argument("--id", required=True, help="Firewall rule ID")

    # ===========================
    # TRAFFIC ROUTES
    # ===========================
    traffic_routes_parser = subparsers.add_parser("traffic-routes", help="Manage traffic routes")
    traffic_routes_subparsers = traffic_routes_parser.add_subparsers(
        dest="action", help="Traffic route action"
    )

    traffic_routes_subparsers.add_parser("list", help="List all traffic routes")

    traffic_routes_get_parser = traffic_routes_subparsers.add_parser(
        "get", help="Get traffic route details"
    )
    traffic_routes_get_parser.add_argument("--id", required=True, help="Traffic route ID")

    traffic_routes_create_parser = traffic_routes_subparsers.add_parser(
        "create", help="Create a traffic route"
    )
    traffic_routes_create_parser.add_argument(
        "--json", required=True, dest="json_data", help="Traffic route configuration JSON"
    )

    traffic_routes_update_parser = traffic_routes_subparsers.add_parser(
        "update", help="Update a traffic route"
    )
    traffic_routes_update_parser.add_argument("--id", required=True, help="Traffic route ID")
    traffic_routes_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="Updated traffic route configuration JSON"
    )

    traffic_routes_delete_parser = traffic_routes_subparsers.add_parser(
        "delete", help="Delete a traffic route"
    )
    traffic_routes_delete_parser.add_argument("--id", required=True, help="Traffic route ID")

    # ===========================
    # PORT FORWARDS
    # ===========================
    port_forwards_parser = subparsers.add_parser(
        "port-forwards", help="Manage port forwarding rules"
    )
    port_forwards_subparsers = port_forwards_parser.add_subparsers(
        dest="action", help="Port forward action"
    )

    port_forwards_subparsers.add_parser("list", help="List all port forwarding rules")

    port_forwards_get_parser = port_forwards_subparsers.add_parser(
        "get", help="Get port forward rule details"
    )
    port_forwards_get_parser.add_argument("--id", required=True, help="Port forward rule ID")

    port_forwards_create_parser = port_forwards_subparsers.add_parser(
        "create", help="Create a port forwarding rule"
    )
    port_forwards_create_parser.add_argument(
        "--json", required=True, dest="json_data", help="Port forward rule configuration JSON"
    )

    port_forwards_update_parser = port_forwards_subparsers.add_parser(
        "update", help="Update a port forwarding rule"
    )
    port_forwards_update_parser.add_argument("--id", required=True, help="Port forward rule ID")
    port_forwards_update_parser.add_argument(
        "--json",
        required=True,
        dest="json_data",
        help="Updated port forward rule configuration JSON",
    )

    port_forwards_delete_parser = port_forwards_subparsers.add_parser(
        "delete", help="Delete a port forwarding rule"
    )
    port_forwards_delete_parser.add_argument("--id", required=True, help="Port forward rule ID")

    # ===========================
    # WLANS
    # ===========================
    wlans_parser = subparsers.add_parser("wlans", help="Manage WLAN configurations")
    wlans_subparsers = wlans_parser.add_subparsers(dest="action", help="WLAN action")

    wlans_subparsers.add_parser("list", help="List all WLANs")

    wlans_get_parser = wlans_subparsers.add_parser("get", help="Get WLAN details")
    wlans_get_parser.add_argument("--id", required=True, help="WLAN ID")

    wlans_update_parser = wlans_subparsers.add_parser("update", help="Update a WLAN")
    wlans_update_parser.add_argument("--id", required=True, help="WLAN ID")
    wlans_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="Updated WLAN configuration JSON"
    )

    # ===========================
    # VPN
    # ===========================
    vpn_parser = subparsers.add_parser("vpn", help="Manage VPN connections")
    vpn_subparsers = vpn_parser.add_subparsers(dest="action", help="VPN action")

    vpn_subparsers.add_parser("list-clients", help="List active VPN client sessions")
    vpn_subparsers.add_parser("list-servers", help="List VPN server configurations")

    vpn_get_parser = vpn_subparsers.add_parser("get", help="Get VPN server configuration details")
    vpn_get_parser.add_argument("--id", required=True, help="VPN configuration ID")

    # ===========================
    # DNS
    # ===========================
    dns_parser = subparsers.add_parser("dns", help="Manage static DNS entries")
    dns_subparsers = dns_parser.add_subparsers(dest="action", help="DNS action")

    dns_subparsers.add_parser("list", help="List all static DNS entries")

    dns_get_parser = dns_subparsers.add_parser("get", help="Get static DNS entry details")
    dns_get_parser.add_argument("--id", required=True, help="Static DNS entry ID")

    dns_create_parser = dns_subparsers.add_parser("create", help="Create a static DNS entry")
    dns_create_parser.add_argument(
        "--json",
        required=True,
        dest="json_data",
        help='Static DNS entry JSON (e.g. \'{"key":"host.local","record_type":"A","value":"192.168.1.10"}\')',
    )

    dns_update_parser = dns_subparsers.add_parser("update", help="Update a static DNS entry")
    dns_update_parser.add_argument("--id", required=True, help="Static DNS entry ID")
    dns_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="Updated static DNS entry JSON"
    )

    dns_delete_parser = dns_subparsers.add_parser("delete", help="Delete a static DNS entry")
    dns_delete_parser.add_argument("--id", required=True, help="Static DNS entry ID")

    # ===========================
    # DHCP
    # ===========================
    dhcp_parser = subparsers.add_parser("dhcp", help="View DHCP leases")
    dhcp_subparsers = dhcp_parser.add_subparsers(dest="action", help="DHCP action")

    dhcp_subparsers.add_parser("list-leases", help="List all current DHCP leases")

    # ===========================
    # STATS
    # ===========================
    stats_parser = subparsers.add_parser("stats", help="View network statistics")
    stats_subparsers = stats_parser.add_subparsers(dest="action", help="Stats action")

    stats_subparsers.add_parser("health", help="Get site health summary")
    stats_subparsers.add_parser("sysinfo", help="Get system information")
    stats_subparsers.add_parser("dpi", help="Get DPI statistics")
    stats_subparsers.add_parser("alarms", help="Get active alarms")

    stats_events_parser = stats_subparsers.add_parser("events", help="Get recent events")
    stats_events_parser.add_argument(
        "--limit", type=int, default=50, help="Maximum number of events to return (default: 50)"
    )

    # ===========================
    # BACKUP
    # ===========================
    backup_parser = subparsers.add_parser("backup", help="Manage backups")
    backup_subparsers = backup_parser.add_subparsers(dest="action", help="Backup action")

    backup_subparsers.add_parser("list", help="List available backups")
    backup_subparsers.add_parser("create", help="Create a new backup (requires --confirm)")

    # Parse arguments
    args = parser.parse_args()

    if not args.resource:
        parser.print_help()
        sys.exit(1)

    # Initialize client
    client = UnifiNetworkClient(
        host=args.host,
        site=args.site,
        verify_ssl=args.verify_ssl,
    )

    # Route to appropriate handler
    if args.resource == "devices":
        if not args.action:
            devices_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.devices_list()
        elif args.action == "get":
            client.devices_get(mac=args.mac)
        elif args.action == "restart":
            client.devices_restart(mac=args.mac, confirm=args.confirm)
        elif args.action == "adopt":
            client.devices_adopt(mac=args.mac, confirm=args.confirm)
        elif args.action == "forget":
            client.devices_forget(mac=args.mac, confirm=args.confirm)
        elif args.action == "upgrade":
            client.devices_upgrade(mac=args.mac, confirm=args.confirm)
        elif args.action == "locate":
            client.devices_locate(mac=args.mac, confirm=args.confirm)

    elif args.resource == "clients":
        if not args.action:
            clients_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.clients_list()
        elif args.action == "list-history":
            client.clients_list_history(limit=args.limit)
        elif args.action == "get":
            client.clients_get(mac=args.mac)
        elif args.action == "block":
            client.clients_block(mac=args.mac, confirm=args.confirm)
        elif args.action == "unblock":
            client.clients_unblock(mac=args.mac, confirm=args.confirm)
        elif args.action == "kick":
            client.clients_kick(mac=args.mac, confirm=args.confirm)

    elif args.resource == "networks":
        if not args.action:
            networks_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.networks_list()
        elif args.action == "get":
            client.networks_get(network_id=args.id)
        elif args.action == "create":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.networks_create(data=payload, confirm=args.confirm)
        elif args.action == "update":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.networks_update(network_id=args.id, data=payload, confirm=args.confirm)
        elif args.action == "delete":
            client.networks_delete(network_id=args.id, confirm=args.confirm)

    elif args.resource == "firewall":
        if not args.action:
            firewall_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.firewall_list()
        elif args.action == "get":
            client.firewall_get(rule_id=args.id)
        elif args.action == "create":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.firewall_create(data=payload, confirm=args.confirm)
        elif args.action == "update":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.firewall_update(rule_id=args.id, data=payload, confirm=args.confirm)
        elif args.action == "delete":
            client.firewall_delete(rule_id=args.id, confirm=args.confirm)

    elif args.resource == "traffic-routes":
        if not args.action:
            traffic_routes_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.traffic_routes_list()
        elif args.action == "get":
            client.traffic_routes_get(route_id=args.id)
        elif args.action == "create":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.traffic_routes_create(data=payload, confirm=args.confirm)
        elif args.action == "update":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.traffic_routes_update(route_id=args.id, data=payload, confirm=args.confirm)
        elif args.action == "delete":
            client.traffic_routes_delete(route_id=args.id, confirm=args.confirm)

    elif args.resource == "port-forwards":
        if not args.action:
            port_forwards_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.port_forwards_list()
        elif args.action == "get":
            client.port_forwards_get(forward_id=args.id)
        elif args.action == "create":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.port_forwards_create(data=payload, confirm=args.confirm)
        elif args.action == "update":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.port_forwards_update(forward_id=args.id, data=payload, confirm=args.confirm)
        elif args.action == "delete":
            client.port_forwards_delete(forward_id=args.id, confirm=args.confirm)

    elif args.resource == "wlans":
        if not args.action:
            wlans_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.wlans_list()
        elif args.action == "get":
            client.wlans_get(wlan_id=args.id)
        elif args.action == "update":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.wlans_update(wlan_id=args.id, data=payload, confirm=args.confirm)

    elif args.resource == "vpn":
        if not args.action:
            vpn_parser.print_help()
            sys.exit(1)
        if args.action == "list-clients":
            client.vpn_list_clients()
        elif args.action == "list-servers":
            client.vpn_list_servers()
        elif args.action == "get":
            client.vpn_get(vpn_id=args.id)

    elif args.resource == "dns":
        if not args.action:
            dns_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.dns_list()
        elif args.action == "get":
            client.dns_get(dns_id=args.id)
        elif args.action == "create":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.dns_create(data=payload, confirm=args.confirm)
        elif args.action == "update":
            try:
                payload = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.dns_update(dns_id=args.id, data=payload, confirm=args.confirm)
        elif args.action == "delete":
            client.dns_delete(dns_id=args.id, confirm=args.confirm)

    elif args.resource == "dhcp":
        if not args.action:
            dhcp_parser.print_help()
            sys.exit(1)
        if args.action == "list-leases":
            client.dhcp_list_leases()

    elif args.resource == "stats":
        if not args.action:
            stats_parser.print_help()
            sys.exit(1)
        if args.action == "health":
            client.stats_health()
        elif args.action == "sysinfo":
            client.stats_sysinfo()
        elif args.action == "dpi":
            client.stats_dpi()
        elif args.action == "events":
            client.stats_events(limit=args.limit)
        elif args.action == "alarms":
            client.stats_alarms()

    elif args.resource == "backup":
        if not args.action:
            backup_parser.print_help()
            sys.exit(1)
        if args.action == "list":
            client.backup_list()
        elif args.action == "create":
            client.backup_create(confirm=args.confirm)


if __name__ == "__main__":
    main()
