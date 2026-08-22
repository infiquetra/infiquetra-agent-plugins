#!/usr/bin/env python3
"""
UniFi Protect CLI - Command-line interface for UniFi Protect API operations.

Manages UniFi Protect cameras, liveviews, lights, sensors, chimes, and viewers
via the UniFi OS Protect Integration API (/proxy/protect/integration/v1).

Note: The integration API supports API key auth (X-Api-Key). The older
/proxy/protect/api path requires cookie-based auth and is not used here.

Environment Variables:
    UNIFI_API_KEY: UniFi OS API key (required)
    UNIFI_HOST: UniFi controller IP or hostname (required; no default)

Usage:
    python unifi_protect_client.py cameras list
    python unifi_protect_client.py cameras snapshot --id <cam_id> --output /tmp/snap.jpg
    python unifi_protect_client.py cameras update --id <cam_id> --json '{"name":"Front"}' --confirm
    python unifi_protect_client.py liveviews list
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

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
    """A 429 raised inside the retry wrapper so ``retry_with_backoff`` backs off + retries (#348)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited; retry after {retry_after}s")
        self.status_code = 429
        self.retry_after = retry_after


class UnifiProtectClient:
    """Wrapper for UniFi Protect API operations with JSON output."""

    def __init__(
        self,
        api_key: str | None = None,
        host: str | None = None,
        verify_ssl: bool = False,
    ):
        """Initialize the UniFi Protect client.

        Args:
            api_key: UniFi OS API key (defaults to UNIFI_API_KEY env var)
            host: controller IP or hostname (defaults to the UNIFI_HOST env var;
                required, and an absent or empty value exits 1)
            verify_ssl: Whether to verify SSL certificates (default: False for self-signed certs)
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
        # UNIFI_HOST built the malformed URL "https:///proxy/protect/integration/v1".
        self.host = (host or os.getenv("UNIFI_HOST") or "").strip()
        if not self.host:
            self._error(
                "UNIFI_HOST environment variable not set; "
                "pass --host or set UNIFI_HOST to the controller address"
            )
            sys.exit(1)

        self.verify_ssl = verify_ssl
        self.base_url = f"https://{self.host}/proxy/protect/integration/v1"
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _error(self, message: str, **kwargs: Any) -> None:
        """Output error in JSON format."""
        error_data = {"error": True, "message": message}
        error_data.update(kwargs)
        print(json.dumps(error_data, indent=2))

    def _success(self, data: Any, **kwargs: Any) -> None:
        """Output success data in JSON format."""
        output = {"success": True, "data": data}
        output.update(kwargs)
        print(json.dumps(output, indent=2, default=str))

    def _dry_run(self, method: str, url: str, data: dict[str, Any] | None = None) -> None:
        """Output dry-run info in JSON format."""
        dry_run_data: dict[str, Any] = {
            "dry_run": True,
            "message": "Pass --confirm to execute this operation",
            "method": method,
            "url": url,
        }
        if data is not None:
            dry_run_data["body"] = data
        print(json.dumps(dry_run_data, indent=2))

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        confirm: bool = True,
        binary: bool = False,
    ) -> Any:
        """Make HTTP request to UniFi Protect API with error handling.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            url: Full URL (already includes base_url)
            params: Query parameters
            data: Request body data
            confirm: Whether this mutation is confirmed (False → dry-run for mutating methods)
            binary: Whether to return raw bytes instead of parsed JSON

        Returns:
            Response data as dict, bytes (if binary=True), or exits on error
        """
        mutating_methods = {"POST", "PUT", "PATCH", "DELETE"}

        if method.upper() in mutating_methods and not confirm:
            self._dry_run(method.upper(), url, data)
            sys.exit(0)

        def _do_request() -> Any:
            resp = requests.request(
                method=method.upper(),
                url=url,
                headers=self.headers,
                params=params,
                json=data,
                timeout=30,
                verify=self.verify_ssl,
            )
            # A 429 is raised so the shared primitive backs off + retries (#348); a Retry-After hint
            # is honored. All other statuses flow through unchanged to the handling below.
            if resp.status_code == 429:
                raise _RateLimited(int(resp.headers.get("Retry-After", 60)))
            return resp

        try:
            try:
                response = _retry_backoff.retry_with_backoff(
                    _do_request,
                    retry_after=lambda exc: getattr(exc, "retry_after", None),
                    sleep=time.sleep,
                )
            except _RateLimited as exc:
                # Retries exhausted — preserve the existing typed-error + exit surface.
                self._error(
                    f"Rate limited. Retry after {exc.retry_after} seconds",
                    status_code=429,
                    retry_after=exc.retry_after,
                )
                sys.exit(1)

            if response.status_code == 401:
                self._error("API key invalid or expired", status_code=401)
                sys.exit(1)

            if response.status_code == 403:
                self._error(
                    "Insufficient permissions. Check API key scope.",
                    status_code=403,
                )
                sys.exit(1)

            if response.status_code == 404:
                self._error(
                    "Resource not found. Verify camera/device ID.",
                    status_code=404,
                )
                sys.exit(1)

            if response.status_code >= 500:
                self._error(
                    f"Controller error: {response.status_code}",
                    status_code=response.status_code,
                )
                sys.exit(1)

            if response.status_code >= 400:
                self._error(
                    f"API error: {response.status_code}",
                    status_code=response.status_code,
                )
                sys.exit(1)

            if binary:
                return response.content

            # Handle empty responses (e.g., 204 No Content)
            if not response.content:
                return {}

            return response.json()

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
    # CAMERAS
    # ===========================

    def cameras_list(self) -> None:
        """List all cameras."""
        url = f"{self.base_url}/cameras"
        result = self._request("GET", url)
        self._success(result, count=len(result) if isinstance(result, list) else None)

    def cameras_get(self, camera_id: str) -> None:
        """Get camera details.

        Args:
            camera_id: Camera ID
        """
        url = f"{self.base_url}/cameras/{camera_id}"
        result = self._request("GET", url)
        self._success(result)

    def cameras_snapshot(self, camera_id: str, output_path: str | None = None) -> None:
        """Get a JPEG snapshot from a camera.

        Args:
            camera_id: Camera ID
            output_path: Optional file path to save the snapshot; if omitted returns base64
        """
        url = f"{self.base_url}/cameras/{camera_id}/snapshot"
        image_bytes = self._request("GET", url, binary=True)

        if output_path:
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            self._success({"saved_to": output_path, "size_bytes": len(image_bytes)})
        else:
            encoded = base64.b64encode(image_bytes).decode("utf-8")
            self._success({"data": encoded, "encoding": "base64", "format": "jpeg"})

    def cameras_update(self, camera_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update camera settings.

        Args:
            camera_id: Camera ID
            data: Fields to update (JSON object)
            confirm: Must be True to execute; False shows dry-run
        """
        url = f"{self.base_url}/cameras/{camera_id}"
        result = self._request("PATCH", url, data=data, confirm=confirm)
        self._success(result, message=f"Camera {camera_id} updated")

    # ===========================
    # LIVEVIEWS
    # ===========================

    def liveviews_list(self) -> None:
        """List all liveviews."""
        url = f"{self.base_url}/liveviews"
        result = self._request("GET", url)
        self._success(result, count=len(result) if isinstance(result, list) else None)

    def liveviews_get(self, liveview_id: str) -> None:
        """Get liveview details.

        Args:
            liveview_id: Liveview ID
        """
        url = f"{self.base_url}/liveviews/{liveview_id}"
        result = self._request("GET", url)
        self._success(result)

    def liveviews_create(self, data: dict[str, Any], confirm: bool = False) -> None:
        """Create a new liveview.

        Args:
            data: Liveview configuration (JSON object)
            confirm: Must be True to execute; False shows dry-run
        """
        url = f"{self.base_url}/liveviews"
        result = self._request("POST", url, data=data, confirm=confirm)
        self._success(result, message="Liveview created")

    def liveviews_update(
        self, liveview_id: str, data: dict[str, Any], confirm: bool = False
    ) -> None:
        """Update a liveview.

        Args:
            liveview_id: Liveview ID
            data: Fields to update (JSON object)
            confirm: Must be True to execute; False shows dry-run
        """
        url = f"{self.base_url}/liveviews/{liveview_id}"
        result = self._request("PUT", url, data=data, confirm=confirm)
        self._success(result, message=f"Liveview {liveview_id} updated")

    def liveviews_delete(self, liveview_id: str, confirm: bool = False) -> None:
        """Delete a liveview.

        Args:
            liveview_id: Liveview ID
            confirm: Must be True to execute; False shows dry-run
        """
        url = f"{self.base_url}/liveviews/{liveview_id}"
        self._request("DELETE", url, confirm=confirm)
        self._success({}, message=f"Liveview {liveview_id} deleted")

    # ===========================
    # LIGHTS
    # ===========================

    def lights_list(self) -> None:
        """List all lights."""
        url = f"{self.base_url}/lights"
        result = self._request("GET", url)
        self._success(result, count=len(result) if isinstance(result, list) else None)

    def lights_get(self, light_id: str) -> None:
        """Get light details.

        Args:
            light_id: Light ID
        """
        url = f"{self.base_url}/lights/{light_id}"
        result = self._request("GET", url)
        self._success(result)

    def lights_update(self, light_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update light settings.

        Args:
            light_id: Light ID
            data: Fields to update (JSON object)
            confirm: Must be True to execute; False shows dry-run
        """
        url = f"{self.base_url}/lights/{light_id}"
        result = self._request("PATCH", url, data=data, confirm=confirm)
        self._success(result, message=f"Light {light_id} updated")

    # ===========================
    # SENSORS
    # ===========================

    def sensors_list(self) -> None:
        """List all sensors."""
        url = f"{self.base_url}/sensors"
        result = self._request("GET", url)
        self._success(result, count=len(result) if isinstance(result, list) else None)

    def sensors_get(self, sensor_id: str) -> None:
        """Get sensor details.

        Args:
            sensor_id: Sensor ID
        """
        url = f"{self.base_url}/sensors/{sensor_id}"
        result = self._request("GET", url)
        self._success(result)

    def sensors_update(self, sensor_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update sensor settings.

        Args:
            sensor_id: Sensor ID
            data: Fields to update (JSON object)
            confirm: Must be True to execute; False shows dry-run
        """
        url = f"{self.base_url}/sensors/{sensor_id}"
        result = self._request("PATCH", url, data=data, confirm=confirm)
        self._success(result, message=f"Sensor {sensor_id} updated")

    # ===========================
    # CHIMES
    # ===========================

    def chimes_list(self) -> None:
        """List all chimes."""
        url = f"{self.base_url}/chimes"
        result = self._request("GET", url)
        self._success(result, count=len(result) if isinstance(result, list) else None)

    def chimes_get(self, chime_id: str) -> None:
        """Get chime details.

        Args:
            chime_id: Chime ID
        """
        url = f"{self.base_url}/chimes/{chime_id}"
        result = self._request("GET", url)
        self._success(result)

    def chimes_update(self, chime_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update chime settings.

        Args:
            chime_id: Chime ID
            data: Fields to update (JSON object)
            confirm: Must be True to execute; False shows dry-run
        """
        url = f"{self.base_url}/chimes/{chime_id}"
        result = self._request("PATCH", url, data=data, confirm=confirm)
        self._success(result, message=f"Chime {chime_id} updated")

    # ===========================
    # VIEWERS
    # ===========================

    def viewers_list(self) -> None:
        """List all viewers."""
        url = f"{self.base_url}/viewers"
        result = self._request("GET", url)
        self._success(result, count=len(result) if isinstance(result, list) else None)

    def viewers_get(self, viewer_id: str) -> None:
        """Get viewer details.

        Args:
            viewer_id: Viewer ID
        """
        url = f"{self.base_url}/viewers/{viewer_id}"
        result = self._request("GET", url)
        self._success(result)

    def viewers_update(self, viewer_id: str, data: dict[str, Any], confirm: bool = False) -> None:
        """Update viewer settings.

        Args:
            viewer_id: Viewer ID
            data: Fields to update (JSON object)
            confirm: Must be True to execute; False shows dry-run
        """
        url = f"{self.base_url}/viewers/{viewer_id}"
        result = self._request("PATCH", url, data=data, confirm=confirm)
        self._success(result, message=f"Viewer {viewer_id} updated")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="UniFi Protect CLI for camera and device management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--confirm", action="store_true", help="Confirm mutating operations")
    parser.add_argument("--host", help="Controller IP or hostname; overrides UNIFI_HOST")
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        default=False,
        help="Enable SSL certificate verification (disabled by default for self-signed certs)",
    )

    subparsers = parser.add_subparsers(dest="resource", help="Resource type")

    # ===========================
    # CAMERAS
    # ===========================
    cameras_parser = subparsers.add_parser("cameras", help="Manage cameras")
    cameras_subparsers = cameras_parser.add_subparsers(dest="action", help="Camera action")

    # cameras list
    cameras_subparsers.add_parser("list", help="List all cameras")

    # cameras get
    cameras_get_parser = cameras_subparsers.add_parser("get", help="Get camera details")
    cameras_get_parser.add_argument("--id", required=True, help="Camera ID")

    # cameras snapshot
    cameras_snapshot_parser = cameras_subparsers.add_parser(
        "snapshot", help="Capture a JPEG snapshot"
    )
    cameras_snapshot_parser.add_argument("--id", required=True, help="Camera ID")
    cameras_snapshot_parser.add_argument(
        "--output", help="File path to save snapshot (optional; returns base64 if omitted)"
    )

    # cameras update
    cameras_update_parser = cameras_subparsers.add_parser("update", help="Update camera settings")
    cameras_update_parser.add_argument("--id", required=True, help="Camera ID")
    cameras_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="JSON object of fields to update"
    )

    # ===========================
    # LIVEVIEWS
    # ===========================
    liveviews_parser = subparsers.add_parser("liveviews", help="Manage liveviews")
    liveviews_subparsers = liveviews_parser.add_subparsers(dest="action", help="Liveviews action")

    # liveviews list
    liveviews_subparsers.add_parser("list", help="List all liveviews")

    # liveviews get
    liveviews_get_parser = liveviews_subparsers.add_parser("get", help="Get liveview details")
    liveviews_get_parser.add_argument("--id", required=True, help="Liveview ID")

    # liveviews create
    liveviews_create_parser = liveviews_subparsers.add_parser("create", help="Create a liveview")
    liveviews_create_parser.add_argument(
        "--json", required=True, dest="json_data", help="JSON object for liveview configuration"
    )

    # liveviews update
    liveviews_update_parser = liveviews_subparsers.add_parser("update", help="Update a liveview")
    liveviews_update_parser.add_argument("--id", required=True, help="Liveview ID")
    liveviews_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="JSON object of fields to update"
    )

    # liveviews delete
    liveviews_delete_parser = liveviews_subparsers.add_parser("delete", help="Delete a liveview")
    liveviews_delete_parser.add_argument("--id", required=True, help="Liveview ID")

    # ===========================
    # LIGHTS
    # ===========================
    lights_parser = subparsers.add_parser("lights", help="Manage lights")
    lights_subparsers = lights_parser.add_subparsers(dest="action", help="Lights action")

    # lights list
    lights_subparsers.add_parser("list", help="List all lights")

    # lights get
    lights_get_parser = lights_subparsers.add_parser("get", help="Get light details")
    lights_get_parser.add_argument("--id", required=True, help="Light ID")

    # lights update
    lights_update_parser = lights_subparsers.add_parser("update", help="Update light settings")
    lights_update_parser.add_argument("--id", required=True, help="Light ID")
    lights_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="JSON object of fields to update"
    )

    # ===========================
    # SENSORS
    # ===========================
    sensors_parser = subparsers.add_parser("sensors", help="Manage sensors")
    sensors_subparsers = sensors_parser.add_subparsers(dest="action", help="Sensors action")

    # sensors list
    sensors_subparsers.add_parser("list", help="List all sensors")

    # sensors get
    sensors_get_parser = sensors_subparsers.add_parser("get", help="Get sensor details")
    sensors_get_parser.add_argument("--id", required=True, help="Sensor ID")

    # sensors update
    sensors_update_parser = sensors_subparsers.add_parser("update", help="Update sensor settings")
    sensors_update_parser.add_argument("--id", required=True, help="Sensor ID")
    sensors_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="JSON object of fields to update"
    )

    # ===========================
    # CHIMES
    # ===========================
    chimes_parser = subparsers.add_parser("chimes", help="Manage chimes")
    chimes_subparsers = chimes_parser.add_subparsers(dest="action", help="Chimes action")

    # chimes list
    chimes_subparsers.add_parser("list", help="List all chimes")

    # chimes get
    chimes_get_parser = chimes_subparsers.add_parser("get", help="Get chime details")
    chimes_get_parser.add_argument("--id", required=True, help="Chime ID")

    # chimes update
    chimes_update_parser = chimes_subparsers.add_parser("update", help="Update chime settings")
    chimes_update_parser.add_argument("--id", required=True, help="Chime ID")
    chimes_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="JSON object of fields to update"
    )

    # ===========================
    # VIEWERS
    # ===========================
    viewers_parser = subparsers.add_parser("viewers", help="Manage viewers")
    viewers_subparsers = viewers_parser.add_subparsers(dest="action", help="Viewers action")

    # viewers list
    viewers_subparsers.add_parser("list", help="List all viewers")

    # viewers get
    viewers_get_parser = viewers_subparsers.add_parser("get", help="Get viewer details")
    viewers_get_parser.add_argument("--id", required=True, help="Viewer ID")

    # viewers update
    viewers_update_parser = viewers_subparsers.add_parser("update", help="Update viewer settings")
    viewers_update_parser.add_argument("--id", required=True, help="Viewer ID")
    viewers_update_parser.add_argument(
        "--json", required=True, dest="json_data", help="JSON object of fields to update"
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.resource:
        parser.print_help()
        sys.exit(1)

    # Initialize client
    client = UnifiProtectClient(host=args.host, verify_ssl=args.verify_ssl)

    # ===========================
    # ROUTE: CAMERAS
    # ===========================
    if args.resource == "cameras":
        if not args.action:
            cameras_parser.print_help()
            sys.exit(1)

        if args.action == "list":
            client.cameras_list()

        elif args.action == "get":
            client.cameras_get(camera_id=args.id)

        elif args.action == "snapshot":
            client.cameras_snapshot(camera_id=args.id, output_path=args.output)

        elif args.action == "update":
            try:
                data = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.cameras_update(camera_id=args.id, data=data, confirm=args.confirm)

    # ===========================
    # ROUTE: LIVEVIEWS
    # ===========================
    elif args.resource == "liveviews":
        if not args.action:
            liveviews_parser.print_help()
            sys.exit(1)

        if args.action == "list":
            client.liveviews_list()

        elif args.action == "get":
            client.liveviews_get(liveview_id=args.id)

        elif args.action == "create":
            try:
                data = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.liveviews_create(data=data, confirm=args.confirm)

        elif args.action == "update":
            try:
                data = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.liveviews_update(liveview_id=args.id, data=data, confirm=args.confirm)

        elif args.action == "delete":
            client.liveviews_delete(liveview_id=args.id, confirm=args.confirm)

    # ===========================
    # ROUTE: LIGHTS
    # ===========================
    elif args.resource == "lights":
        if not args.action:
            lights_parser.print_help()
            sys.exit(1)

        if args.action == "list":
            client.lights_list()

        elif args.action == "get":
            client.lights_get(light_id=args.id)

        elif args.action == "update":
            try:
                data = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.lights_update(light_id=args.id, data=data, confirm=args.confirm)

    # ===========================
    # ROUTE: SENSORS
    # ===========================
    elif args.resource == "sensors":
        if not args.action:
            sensors_parser.print_help()
            sys.exit(1)

        if args.action == "list":
            client.sensors_list()

        elif args.action == "get":
            client.sensors_get(sensor_id=args.id)

        elif args.action == "update":
            try:
                data = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.sensors_update(sensor_id=args.id, data=data, confirm=args.confirm)

    # ===========================
    # ROUTE: CHIMES
    # ===========================
    elif args.resource == "chimes":
        if not args.action:
            chimes_parser.print_help()
            sys.exit(1)

        if args.action == "list":
            client.chimes_list()

        elif args.action == "get":
            client.chimes_get(chime_id=args.id)

        elif args.action == "update":
            try:
                data = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.chimes_update(chime_id=args.id, data=data, confirm=args.confirm)

    # ===========================
    # ROUTE: VIEWERS
    # ===========================
    elif args.resource == "viewers":
        if not args.action:
            viewers_parser.print_help()
            sys.exit(1)

        if args.action == "list":
            client.viewers_list()

        elif args.action == "get":
            client.viewers_get(viewer_id=args.id)

        elif args.action == "update":
            try:
                data = json.loads(args.json_data)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": True, "message": f"Invalid JSON: {e}"}))
                sys.exit(1)
            client.viewers_update(viewer_id=args.id, data=data, confirm=args.confirm)


if __name__ == "__main__":
    main()
