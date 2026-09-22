"""Unit tests for unifi_network_client.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

pytest.importorskip("urllib3")
pytest.importorskip("requests")

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent
        / "skills"
        / "unifi-network"
        / "scripts"
    ),
)

from unifi_network_client import UnifiNetworkClient

# The clients require a controller address and no longer carry a default (plan unit U7).
# Every test below constructs a client, so the address is supplied once here; the tests that
# assert the requirement itself remove it explicitly. RFC 5737 TEST-NET-1, so no real
# operator's address is ever what a test asserts on.
TEST_HOST = "192.0.2.1"


@pytest.fixture(autouse=True)
def _supply_controller_host(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", TEST_HOST)


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------


class TestInit:
    """Test UnifiNetworkClient initialization."""

    def test_init_missing_api_key(self, monkeypatch, capsys):
        """Test initialization fails when UNIFI_API_KEY is missing."""
        monkeypatch.delenv("UNIFI_API_KEY", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            UnifiNetworkClient()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "UNIFI_API_KEY" in output["message"]

    def test_init_success(self, monkeypatch):
        """Test successful initialization with all expected attributes."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.delenv("UNIFI_SITE", raising=False)

        client = UnifiNetworkClient()

        assert client.api_key == "test-key-123"
        assert client.host == "192.0.2.1"
        assert client.site == "default"
        assert "192.0.2.1" in client.base_v1
        assert "default" in client.base_v1
        assert "192.0.2.1" in client.base_v2
        assert "default" in client.base_v2
        assert client.headers["X-Api-Key"] == "test-key-123"
        assert client.headers["Content-Type"] == "application/json"

    def test_init_custom_host(self, monkeypatch):
        """Test UNIFI_HOST environment variable override."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "198.51.100.1")

        client = UnifiNetworkClient()

        assert client.host == "198.51.100.1"
        assert "198.51.100.1" in client.base_v1
        assert "198.51.100.1" in client.base_v2

    def test_init_custom_site(self, monkeypatch):
        """Test UNIFI_SITE environment variable override."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_SITE", "homelab")

        client = UnifiNetworkClient()

        assert client.site == "homelab"
        assert "homelab" in client.base_v1
        assert "homelab" in client.base_v2

    def test_init_missing_host(self, monkeypatch, capsys):
        """No flag, no environment, no default: exit 1 naming UNIFI_HOST, before any request."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.delenv("UNIFI_HOST", raising=False)

        with (
            patch("unifi_network_client.requests.request") as mock_request,
            pytest.raises(SystemExit) as exc_info,
        ):
            UnifiNetworkClient()

        assert exc_info.value.code == 1
        assert mock_request.call_count == 0
        output = json.loads(capsys.readouterr().out)
        assert output["error"] is True
        assert "UNIFI_HOST" in output["message"]

    def test_init_empty_host_fails_loudly(self, monkeypatch, capsys):
        """A present-but-empty variable is absent, not a value.

        Without this the client built "https:///proxy/network/api/s/default" and only failed
        at request time, one layer away from the mistake.
        """
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "   ")

        with pytest.raises(SystemExit) as exc_info:
            UnifiNetworkClient()

        assert exc_info.value.code == 1
        assert "UNIFI_HOST" in json.loads(capsys.readouterr().out)["message"]

    def test_init_host_flag_wins_over_the_environment(self, monkeypatch):
        """An explicitly passed host is used and the environment is not consulted."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "198.51.100.9")

        client = UnifiNetworkClient(host="192.0.2.1")

        assert client.host == "192.0.2.1"
        assert "198.51.100.9" not in client.base_v1
        assert "198.51.100.9" not in client.base_v2

    def test_init_host_from_environment_only(self, monkeypatch):
        """With no flag, the environment supplies the address."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "198.51.100.9")

        client = UnifiNetworkClient()

        assert client.host == "198.51.100.9"
        assert "198.51.100.9" in client.base_v1

    def test_init_default_site(self, monkeypatch):
        """Test that site defaults to 'default' when UNIFI_SITE is not set."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.delenv("UNIFI_SITE", raising=False)

        client = UnifiNetworkClient()

        assert client.site == "default"


# ---------------------------------------------------------------------------
# TestRequestHandling
# ---------------------------------------------------------------------------


class TestRequestHandling:
    """Test _request method HTTP handling and error cases."""

    @patch("unifi_network_client.requests.request")
    def test_request_get_success(self, mock_request, monkeypatch):
        """Test a successful GET request returns parsed JSON."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        result = client._request("GET", f"{client.base_v1}/stat/device")

        assert result == {"data": []}
        mock_request.assert_called_once()

    @patch("unifi_network_client.requests.request")
    def test_request_post_with_confirm(self, mock_request, monkeypatch):
        """Test that POST with confirm=True executes the request."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        result = client._request(
            "POST", f"{client.base_v1}/cmd/devmgr", data={"cmd": "restart"}, confirm=True
        )

        assert result == {"data": []}
        mock_request.assert_called_once()

    @patch("unifi_network_client.requests.request")
    def test_request_401(self, mock_request, monkeypatch, capsys):
        """Test 401 response exits with code 1 and reports invalid API key."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", f"{client.base_v1}/stat/device")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "invalid or expired" in output["message"].lower()

    @patch("unifi_network_client.requests.request")
    def test_request_403(self, mock_request, monkeypatch, capsys):
        """Test 403 response exits with code 1 and reports insufficient permissions."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", f"{client.base_v1}/stat/device")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "permissions" in output["message"].lower()

    @patch("unifi_network_client.requests.request")
    def test_request_404(self, mock_request, monkeypatch, capsys):
        """Test 404 response exits with code 1 and reports resource not found."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", f"{client.base_v1}/stat/device/aa:bb:cc:dd:ee:ff")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "not found" in output["message"].lower()

    @patch("unifi_network_client.requests.request")
    def test_request_500(self, mock_request, monkeypatch, capsys):
        """Test 500 response exits with code 1 and reports controller error."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", f"{client.base_v1}/stat/device")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "500" in output["message"]

    @patch("unifi_network_client.requests.request")
    def test_request_429(self, mock_request, monkeypatch, capsys):
        """Test 429 rate limit exits with code 1 and includes retry_after."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "30"}
        mock_request.return_value = mock_response
        # #348: the shared primitive now retries a 429 before exiting; no real backoff sleep in tests.
        delays: list[float] = []
        monkeypatch.setattr("time.sleep", delays.append)

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", f"{client.base_v1}/stat/device")

        assert exc_info.value.code == 1
        # The request was retried (bounded) before the exit surface — proves adoption of the primitive.
        assert mock_request.call_count == 3
        # The delta-seconds form is honored exactly as it was before the caller-side repair.
        assert delays == [30.0, 30.0]
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert output["status_code"] == 429
        assert output["retry_after"] == 30
        assert "rate limit" in output["message"].lower() or "retry" in output["message"].lower()

    @patch("unifi_network_client.requests.request")
    def test_request_429_http_date_retry_after_retries(self, mock_request, monkeypatch):
        """A 429 whose Retry-After is an HTTP-date backs off and retries instead of raising.

        Before the caller-side repair the raw date went through ``int()``, which raised
        ``ValueError`` inside the request path. That error carries no 429 status, so the shared
        primitive judged it non-retryable and propagated it: the operator saw a generic
        "Unexpected error" after one request, with no backoff retry at all.
        """
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "Fri, 31 Dec 2100 23:59:59 GMT"}
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b'{"data": []}'
        ok.json.return_value = {"data": []}
        mock_request.side_effect = [rate_limited, rate_limited, ok]
        delays: list[float] = []
        monkeypatch.setattr("time.sleep", delays.append)

        client = UnifiNetworkClient()
        result = client._request("GET", f"{client.base_v1}/stat/device")

        assert result == {"data": []}
        assert mock_request.call_count == 3
        # The date parsed to a large positive hint, clamped to the primitive's 60s max_delay.
        assert delays == [60.0, 60.0]

    @patch("unifi_network_client.requests.request")
    def test_request_429_unparseable_retry_after_computes_backoff(self, mock_request, monkeypatch):
        """An unparseable Retry-After is no hint at all: computed backoff, and still retried."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "next Tuesday-ish"}
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b'{"data": []}'
        ok.json.return_value = {"data": []}
        mock_request.side_effect = [rate_limited, rate_limited, ok]
        delays: list[float] = []
        monkeypatch.setattr("time.sleep", delays.append)

        client = UnifiNetworkClient()
        result = client._request("GET", f"{client.base_v1}/stat/device")

        assert result == {"data": []}
        assert mock_request.call_count == 3
        # Computed backoff (base 1s, doubling, 50-100% jitter) — never the flat 60s a hint gives.
        assert len(delays) == 2
        assert 0.5 <= delays[0] <= 1.0
        assert 1.0 <= delays[1] <= 2.0

    @patch("unifi_network_client.requests.request")
    def test_request_timeout(self, mock_request, monkeypatch, capsys):
        """Test request timeout exits with code 1 and reports timeout."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_request.side_effect = requests.exceptions.Timeout("timed out")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", f"{client.base_v1}/stat/device")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "timeout" in output["message"].lower()

    @patch("unifi_network_client.requests.request")
    def test_request_connection_error(self, mock_request, monkeypatch, capsys):
        """Test connection error exits with code 1 and reports cannot reach UDM."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_request.side_effect = requests.exceptions.ConnectionError("refused")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", f"{client.base_v1}/stat/device")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "cannot reach udm" in output["message"].lower()

    @patch("unifi_network_client.requests.request")
    def test_request_ssl_error(self, mock_request, monkeypatch, capsys):
        """Test SSL error exits with code 1 and reports SSL verification failure."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_request.side_effect = requests.exceptions.SSLError("cert verify failed")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", f"{client.base_v1}/stat/device")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "ssl" in output["message"].lower()


# ---------------------------------------------------------------------------
# TestDryRun
# ---------------------------------------------------------------------------


class TestDryRun:
    """Test dry-run behavior for write operations."""

    @patch("unifi_network_client.requests.request")
    def test_dry_run_post_without_confirm(self, mock_request, monkeypatch, capsys):
        """Test POST without confirm exits with 0 and does not call requests."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request(
                "POST", f"{client.base_v1}/cmd/devmgr", data={"cmd": "restart"}, confirm=False
            )

        assert exc_info.value.code == 0
        mock_request.assert_not_called()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True

    @patch("unifi_network_client.requests.request")
    def test_dry_run_put_without_confirm(self, mock_request, monkeypatch, capsys):
        """Test PUT without confirm exits with 0 and does not call requests."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request(
                "PUT",
                f"{client.base_v1}/rest/networkconf/abc123",
                data={"name": "test"},
                confirm=False,
            )

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_dry_run_patch_without_confirm(self, mock_request, monkeypatch, capsys):
        """Test PATCH without confirm exits with 0 and does not call requests."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request(
                "PATCH",
                f"{client.base_v1}/rest/wlanconf/wlan1",
                data={"enabled": False},
                confirm=False,
            )

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_dry_run_delete_without_confirm(self, mock_request, monkeypatch, capsys):
        """Test DELETE without confirm exits with 0 and does not call requests."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client._request("DELETE", f"{client.base_v1}/rest/networkconf/abc123", confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_dry_run_includes_payload(self, mock_request, monkeypatch, capsys):
        """Test that dry-run output includes the request payload when data is provided."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()
        payload = {"cmd": "restart", "mac": "aa:bb:cc:dd:ee:ff"}

        with pytest.raises(SystemExit):
            client._request("POST", f"{client.base_v1}/cmd/devmgr", data=payload, confirm=False)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "payload" in output
        assert output["payload"]["cmd"] == "restart"

    @patch("unifi_network_client.requests.request")
    def test_dry_run_includes_action_and_endpoint(self, mock_request, monkeypatch, capsys):
        """Test that dry-run output includes action and endpoint fields."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()
        url = f"{client.base_v1}/cmd/devmgr"

        with pytest.raises(SystemExit):
            client._request("POST", url, data={"cmd": "restart"}, confirm=False)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["action"] == "POST"
        assert output["endpoint"] == url

    @patch("unifi_network_client.requests.request")
    def test_get_never_dry_runs(self, mock_request, monkeypatch):
        """Test that GET with confirm=False still executes the request (no dry-run for reads)."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client._request("GET", f"{client.base_v1}/stat/device", confirm=False)

        mock_request.assert_called_once()

    @patch("unifi_network_client.requests.request")
    def test_confirm_true_executes_write(self, mock_request, monkeypatch):
        """Test that POST with confirm=True calls requests.request."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client._request(
            "POST", f"{client.base_v1}/cmd/devmgr", data={"cmd": "restart"}, confirm=True
        )

        mock_request.assert_called_once()


# ---------------------------------------------------------------------------
# TestDevices
# ---------------------------------------------------------------------------


class TestDevices:
    """Test device management methods."""

    @patch("unifi_network_client.requests.request")
    def test_devices_list(self, mock_request, monkeypatch, capsys):
        """Test listing all adopted devices."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "abc", "name": "AP-01"}]}'
        mock_response.json.return_value = {"data": [{"_id": "abc", "name": "AP-01"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.devices_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert len(output["data"]) == 1
        assert output["data"][0]["name"] == "AP-01"

        call_args = mock_request.call_args
        assert "/stat/device" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_devices_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific device by MAC address."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:ff"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"mac": "aa:bb:cc:dd:ee:ff", "name": "AP-01"}]}'
        mock_response.json.return_value = {"data": [{"mac": mac, "name": "AP-01"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.devices_get(mac)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["mac"] == mac

        call_args = mock_request.call_args
        assert mac in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_devices_restart_dry_run(self, mock_request, monkeypatch, capsys):
        """Test device restart without --confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:ff"

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client.devices_restart(mac, confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True

    @patch("unifi_network_client.requests.request")
    def test_devices_restart_confirmed(self, mock_request, monkeypatch, capsys):
        """Test device restart with confirm=True sends POST with cmd=restart."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:ff"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.devices_restart(mac, confirm=True)

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "POST"
        assert call_args[1]["json"]["cmd"] == "restart"
        assert call_args[1]["json"]["mac"] == mac

    @patch("unifi_network_client.requests.request")
    def test_devices_adopt(self, mock_request, monkeypatch, capsys):
        """Test device adoption sends POST with cmd=adopt."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:ff"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.devices_adopt(mac, confirm=True)

        call_args = mock_request.call_args
        assert call_args[1]["json"]["cmd"] == "adopt"
        assert call_args[1]["json"]["mac"] == mac

    @patch("unifi_network_client.requests.request")
    def test_devices_upgrade(self, mock_request, monkeypatch, capsys):
        """Test device firmware upgrade sends POST with cmd=upgrade."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:ff"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.devices_upgrade(mac, confirm=True)

        call_args = mock_request.call_args
        assert call_args[1]["json"]["cmd"] == "upgrade"
        assert call_args[1]["json"]["mac"] == mac

    @patch("unifi_network_client.requests.request")
    def test_devices_locate(self, mock_request, monkeypatch, capsys):
        """Test device locate sends POST with cmd=locate."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:ff"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.devices_locate(mac, confirm=True)

        call_args = mock_request.call_args
        assert call_args[1]["json"]["cmd"] == "locate"
        assert call_args[1]["json"]["mac"] == mac


# ---------------------------------------------------------------------------
# TestClients
# ---------------------------------------------------------------------------


class TestClients:
    """Test client management methods."""

    @patch("unifi_network_client.requests.request")
    def test_clients_list(self, mock_request, monkeypatch, capsys):
        """Test listing active clients."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"mac": "aa:bb:cc:dd:ee:01", "hostname": "laptop"}]}'
        mock_response.json.return_value = {
            "data": [{"mac": "aa:bb:cc:dd:ee:01", "hostname": "laptop"}]
        }
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.clients_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert len(output["data"]) == 1

        call_args = mock_request.call_args
        assert "/stat/sta" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_clients_list_history(self, mock_request, monkeypatch, capsys):
        """Test listing client history uses /stat/alluser endpoint."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.clients_list_history()

        call_args = mock_request.call_args
        assert "/stat/alluser" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_clients_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific client by MAC address."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:01"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"mac": "aa:bb:cc:dd:ee:01"}]}'
        mock_response.json.return_value = {"data": [{"mac": mac}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.clients_get(mac)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["mac"] == mac

        call_args = mock_request.call_args
        assert mac in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_clients_block_dry_run(self, mock_request, monkeypatch, capsys):
        """Test client block without confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:01"

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client.clients_block(mac, confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_clients_block_confirmed(self, mock_request, monkeypatch, capsys):
        """Test client block with confirm=True sends POST with cmd=block-sta."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:01"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.clients_block(mac, confirm=True)

        call_args = mock_request.call_args
        assert call_args[1]["json"]["cmd"] == "block-sta"
        assert call_args[1]["json"]["mac"] == mac
        assert "/cmd/stamgr" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_clients_kick_confirmed(self, mock_request, monkeypatch, capsys):
        """Test client kick with confirm=True sends POST with cmd=kick-sta."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mac = "aa:bb:cc:dd:ee:01"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.clients_kick(mac, confirm=True)

        call_args = mock_request.call_args
        assert call_args[1]["json"]["cmd"] == "kick-sta"
        assert call_args[1]["json"]["mac"] == mac


# ---------------------------------------------------------------------------
# TestNetworks
# ---------------------------------------------------------------------------


class TestNetworks:
    """Test network configuration methods."""

    @patch("unifi_network_client.requests.request")
    def test_networks_list(self, mock_request, monkeypatch, capsys):
        """Test listing all network configurations."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "net1", "name": "LAN"}]}'
        mock_response.json.return_value = {"data": [{"_id": "net1", "name": "LAN"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.networks_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert len(output["data"]) == 1

        call_args = mock_request.call_args
        assert "/rest/networkconf" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_networks_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific network configuration by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        network_id = "net123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "net123", "name": "IoT"}]}'
        mock_response.json.return_value = {"data": [{"_id": network_id, "name": "IoT"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.networks_get(network_id)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["_id"] == network_id

        call_args = mock_request.call_args
        assert network_id in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_networks_create_dry_run(self, mock_request, monkeypatch, capsys):
        """Test network create without confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()
        payload = {"name": "IoT", "purpose": "corporate", "vlan": 30}

        with pytest.raises(SystemExit) as exc_info:
            client.networks_create(payload, confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_networks_create_confirmed(self, mock_request, monkeypatch, capsys):
        """Test network create with confirm=True sends POST to /rest/networkconf."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "newnet", "name": "IoT"}]}'
        mock_response.json.return_value = {"data": [{"_id": "newnet", "name": "IoT"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.networks_create({"name": "IoT", "purpose": "corporate", "vlan": 30}, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert "created" in output["message"].lower()

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "POST"
        assert "/rest/networkconf" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_networks_delete_confirmed(self, mock_request, monkeypatch, capsys):
        """Test network delete with confirm=True sends DELETE to /rest/networkconf/{id}."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        network_id = "net123"

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.json.return_value = {}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.networks_delete(network_id, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert network_id in output["message"]

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "DELETE"
        assert network_id in call_args[1]["url"]


# ---------------------------------------------------------------------------
# TestFirewall
# ---------------------------------------------------------------------------


class TestFirewall:
    """Test firewall rule management methods."""

    @patch("unifi_network_client.requests.request")
    def test_firewall_list(self, mock_request, monkeypatch, capsys):
        """Test listing all firewall rules."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "fw1", "name": "Block-IoT"}]}'
        mock_response.json.return_value = {"data": [{"_id": "fw1", "name": "Block-IoT"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.firewall_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert len(output["data"]) == 1

        call_args = mock_request.call_args
        assert "/rest/firewallrule" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_firewall_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific firewall rule by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        rule_id = "fw123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "fw123", "name": "Block-IoT"}]}'
        mock_response.json.return_value = {"data": [{"_id": rule_id, "name": "Block-IoT"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.firewall_get(rule_id)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["_id"] == rule_id

    @patch("unifi_network_client.requests.request")
    def test_firewall_create_dry_run(self, mock_request, monkeypatch, capsys):
        """Test firewall rule create without confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client.firewall_create({"name": "Block-IoT", "action": "drop"}, confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_firewall_create_confirmed(self, mock_request, monkeypatch, capsys):
        """Test firewall rule create with confirm=True sends POST to /rest/firewallrule."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "fw_new", "name": "Block-IoT"}]}'
        mock_response.json.return_value = {"data": [{"_id": "fw_new", "name": "Block-IoT"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.firewall_create({"name": "Block-IoT", "action": "drop"}, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert "created" in output["message"].lower()

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "POST"
        assert "/rest/firewallrule" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_firewall_delete_confirmed(self, mock_request, monkeypatch, capsys):
        """Test firewall rule delete with confirm=True sends DELETE to /rest/firewallrule/{id}."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        rule_id = "fw123"

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.json.return_value = {}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.firewall_delete(rule_id, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert rule_id in output["message"]

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "DELETE"
        assert rule_id in call_args[1]["url"]


# ---------------------------------------------------------------------------
# TestTrafficRoutes
# ---------------------------------------------------------------------------


class TestTrafficRoutes:
    """Test traffic route management methods (v2 API)."""

    @patch("unifi_network_client.requests.request")
    def test_traffic_routes_list(self, mock_request, monkeypatch, capsys):
        """Test listing traffic routes uses v2 endpoint."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'[{"id": "route1", "description": "VPN route"}]'
        mock_response.json.return_value = [{"id": "route1", "description": "VPN route"}]
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.traffic_routes_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "v2" in call_args[1]["url"]
        assert "trafficroutes" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_traffic_routes_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific traffic route by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        route_id = "route123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"id": "route123", "description": "VPN route"}'
        mock_response.json.return_value = {"id": route_id, "description": "VPN route"}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.traffic_routes_get(route_id)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert route_id in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_traffic_routes_create_dry_run(self, mock_request, monkeypatch, capsys):
        """Test traffic route create without confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client.traffic_routes_create({"description": "New route"}, confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_traffic_routes_create_confirmed(self, mock_request, monkeypatch, capsys):
        """Test traffic route create with confirm=True sends POST to v2 trafficroutes."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"id": "new_route"}'
        mock_response.json.return_value = {"id": "new_route"}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.traffic_routes_create({"description": "New route"}, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert "created" in output["message"].lower()

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "POST"
        assert "v2" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_traffic_routes_delete_confirmed(self, mock_request, monkeypatch, capsys):
        """Test traffic route delete with confirm=True sends DELETE to v2 trafficroutes/{id}."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        route_id = "route123"

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.json.return_value = {}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.traffic_routes_delete(route_id, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert route_id in output["message"]

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "DELETE"
        assert route_id in call_args[1]["url"]


# ---------------------------------------------------------------------------
# TestPortForwards
# ---------------------------------------------------------------------------


class TestPortForwards:
    """Test port forwarding rule management methods."""

    @patch("unifi_network_client.requests.request")
    def test_port_forwards_list(self, mock_request, monkeypatch, capsys):
        """Test listing all port forwarding rules."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "pf1", "name": "HTTP"}]}'
        mock_response.json.return_value = {"data": [{"_id": "pf1", "name": "HTTP"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.port_forwards_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/rest/portforward" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_port_forwards_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific port forwarding rule by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        forward_id = "pf123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "pf123", "name": "HTTP"}]}'
        mock_response.json.return_value = {"data": [{"_id": forward_id, "name": "HTTP"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.port_forwards_get(forward_id)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["_id"] == forward_id

    @patch("unifi_network_client.requests.request")
    def test_port_forwards_create_dry_run(self, mock_request, monkeypatch, capsys):
        """Test port forward create without confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client.port_forwards_create({"name": "HTTP", "dst_port": "80"}, confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_port_forwards_create_confirmed(self, mock_request, monkeypatch, capsys):
        """Test port forward create with confirm=True sends POST to /rest/portforward."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "pf_new", "name": "HTTP"}]}'
        mock_response.json.return_value = {"data": [{"_id": "pf_new", "name": "HTTP"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.port_forwards_create({"name": "HTTP", "dst_port": "80"}, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert "created" in output["message"].lower()

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "POST"
        assert "/rest/portforward" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_port_forwards_delete_confirmed(self, mock_request, monkeypatch, capsys):
        """Test port forward delete with confirm=True sends DELETE to /rest/portforward/{id}."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        forward_id = "pf123"

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.json.return_value = {}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.port_forwards_delete(forward_id, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert forward_id in output["message"]

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "DELETE"
        assert forward_id in call_args[1]["url"]


# ---------------------------------------------------------------------------
# TestWlans
# ---------------------------------------------------------------------------


class TestWlans:
    """Test WLAN configuration methods."""

    @patch("unifi_network_client.requests.request")
    def test_wlans_list(self, mock_request, monkeypatch, capsys):
        """Test listing all WLAN configurations."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "wlan1", "name": "HomeNetwork"}]}'
        mock_response.json.return_value = {"data": [{"_id": "wlan1", "name": "HomeNetwork"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.wlans_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/rest/wlanconf" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_wlans_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific WLAN configuration by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        wlan_id = "wlan123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "wlan123", "name": "HomeNetwork"}]}'
        mock_response.json.return_value = {"data": [{"_id": wlan_id, "name": "HomeNetwork"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.wlans_get(wlan_id)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["_id"] == wlan_id

    @patch("unifi_network_client.requests.request")
    def test_wlans_update_dry_run(self, mock_request, monkeypatch, capsys):
        """Test WLAN update without confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client.wlans_update("wlan123", {"enabled": False}, confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()


# ---------------------------------------------------------------------------
# TestVPN
# ---------------------------------------------------------------------------


class TestVPN:
    """Test VPN management methods."""

    @patch("unifi_network_client.requests.request")
    def test_vpn_list_clients(self, mock_request, monkeypatch, capsys):
        """Test listing active VPN client sessions."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"mac": "aa:bb:cc:dd:ee:ff", "vpn_type": "openvpn"}]}'
        mock_response.json.return_value = {
            "data": [{"mac": "aa:bb:cc:dd:ee:ff", "vpn_type": "openvpn"}]
        }
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.vpn_list_clients()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/stat/vpnconn" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_vpn_list_servers(self, mock_request, monkeypatch, capsys):
        """Test listing VPN server configurations."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "vpn1", "name": "OpenVPN"}]}'
        mock_response.json.return_value = {"data": [{"_id": "vpn1", "name": "OpenVPN"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.vpn_list_servers()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/rest/vpnconn" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_vpn_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific VPN server configuration by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        vpn_id = "vpn123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"_id": "vpn123", "name": "OpenVPN"}]}'
        mock_response.json.return_value = {"data": [{"_id": vpn_id, "name": "OpenVPN"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.vpn_get(vpn_id)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["_id"] == vpn_id


# ---------------------------------------------------------------------------
# TestDNS
# ---------------------------------------------------------------------------


class TestDNS:
    """Test static DNS entry management methods (v2 API)."""

    @patch("unifi_network_client.requests.request")
    def test_dns_list(self, mock_request, monkeypatch, capsys):
        """Test listing all static DNS entries uses v2 endpoint."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'[{"_id": "dns1", "record_type": "A", "key": "myhost.lan"}]'
        mock_response.json.return_value = [{"_id": "dns1", "record_type": "A", "key": "myhost.lan"}]
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.dns_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "v2" in call_args[1]["url"]
        assert "static-dns" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_dns_get(self, mock_request, monkeypatch, capsys):
        """Test getting a specific static DNS entry by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        dns_id = "dns123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"_id": "dns123", "record_type": "A", "key": "myhost.lan"}'
        mock_response.json.return_value = {"_id": dns_id, "record_type": "A", "key": "myhost.lan"}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.dns_get(dns_id)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert dns_id in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_dns_create_dry_run(self, mock_request, monkeypatch, capsys):
        """Test DNS entry create without confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client.dns_create(
                {"key": "myhost.lan", "record_type": "A", "value": "10.0.0.5"}, confirm=False
            )

        assert exc_info.value.code == 0
        mock_request.assert_not_called()

    @patch("unifi_network_client.requests.request")
    def test_dns_create_confirmed(self, mock_request, monkeypatch, capsys):
        """Test DNS entry create with confirm=True sends POST to v2 static-dns."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"_id": "dns_new", "key": "myhost.lan"}'
        mock_response.json.return_value = {"_id": "dns_new", "key": "myhost.lan"}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.dns_create(
            {"key": "myhost.lan", "record_type": "A", "value": "10.0.0.5"}, confirm=True
        )

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert "created" in output["message"].lower()

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "POST"
        assert "v2" in call_args[1]["url"]
        assert "static-dns" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_dns_delete_confirmed(self, mock_request, monkeypatch, capsys):
        """Test DNS entry delete with confirm=True sends DELETE to v2 static-dns/{id}."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        dns_id = "dns123"

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.json.return_value = {}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.dns_delete(dns_id, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert dns_id in output["message"]

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "DELETE"
        assert dns_id in call_args[1]["url"]


# ---------------------------------------------------------------------------
# TestDHCP
# ---------------------------------------------------------------------------


class TestDHCP:
    """Test DHCP management methods."""

    @patch("unifi_network_client.requests.request")
    def test_dhcp_list_leases(self, mock_request, monkeypatch, capsys):
        """Test listing all current DHCP leases."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"mac": "aa:bb:cc:dd:ee:01", "ip": "10.0.0.100"}]}'
        mock_response.json.return_value = {
            "data": [{"mac": "aa:bb:cc:dd:ee:01", "ip": "10.0.0.100"}]
        }
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.dhcp_list_leases()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert len(output["data"]) == 1

        call_args = mock_request.call_args
        assert "/stat/dhcp" in call_args[1]["url"]


# ---------------------------------------------------------------------------
# TestStats
# ---------------------------------------------------------------------------


class TestStats:
    """Test statistics and monitoring methods."""

    @patch("unifi_network_client.requests.request")
    def test_stats_health(self, mock_request, monkeypatch, capsys):
        """Test getting site health summary."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"subsystem": "wlan", "status": "ok"}]}'
        mock_response.json.return_value = {"data": [{"subsystem": "wlan", "status": "ok"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.stats_health()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/stat/health" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_stats_sysinfo(self, mock_request, monkeypatch, capsys):
        """Test getting system information."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"version": "7.0.0", "hostname": "udm-pro"}]}'
        mock_response.json.return_value = {"data": [{"version": "7.0.0", "hostname": "udm-pro"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.stats_sysinfo()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/stat/sysinfo" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_stats_dpi(self, mock_request, monkeypatch, capsys):
        """Test getting DPI statistics."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"app": "youtube", "rx_bytes": 1000}]}'
        mock_response.json.return_value = {"data": [{"app": "youtube", "rx_bytes": 1000}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.stats_dpi()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/stat/dpi" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_stats_events(self, mock_request, monkeypatch, capsys):
        """Test getting recent site events."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"key": "EVT_AP_Connected", "msg": "AP connected"}]}'
        mock_response.json.return_value = {
            "data": [{"key": "EVT_AP_Connected", "msg": "AP connected"}]
        }
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.stats_events()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/stat/event" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_stats_alarms(self, mock_request, monkeypatch, capsys):
        """Test getting active site alarms."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"key": "EVT_AP_Lost", "msg": "AP lost"}]}'
        mock_response.json.return_value = {"data": [{"key": "EVT_AP_Lost", "msg": "AP lost"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.stats_alarms()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/list/alarm" in call_args[1]["url"]


# ---------------------------------------------------------------------------
# TestBackup
# ---------------------------------------------------------------------------


class TestBackup:
    """Test backup management methods."""

    @patch("unifi_network_client.requests.request")
    def test_backup_list(self, mock_request, monkeypatch, capsys):
        """Test listing available backups."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"datetime": "2026-01-01", "filename": "backup.unf"}]}'
        mock_response.json.return_value = {
            "data": [{"datetime": "2026-01-01", "filename": "backup.unf"}]
        }
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.backup_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True

        call_args = mock_request.call_args
        assert "/stat/backup" in call_args[1]["url"]

    @patch("unifi_network_client.requests.request")
    def test_backup_create_dry_run(self, mock_request, monkeypatch, capsys):
        """Test backup create without confirm triggers dry-run."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()

        with pytest.raises(SystemExit) as exc_info:
            client.backup_create(confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and output format validation."""

    @patch("unifi_network_client.requests.request")
    def test_empty_device_list(self, mock_request, monkeypatch, capsys):
        """Test successful response with empty data list."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.devices_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"] == []
        assert output["count"] == 0

    @patch("unifi_network_client.requests.request")
    def test_invalid_json_payload_still_sends_request(self, mock_request, monkeypatch, capsys):
        """Test that pre-parsed dict data is passed through directly to the request."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        payload = {"cmd": "restart", "mac": "aa:bb:cc:dd:ee:ff"}
        client._request("POST", f"{client.base_v1}/cmd/devmgr", data=payload, confirm=True)

        call_args = mock_request.call_args
        assert call_args[1]["json"] == payload
        mock_request.assert_called_once()

    @patch("unifi_network_client.requests.request")
    def test_success_output_format(self, mock_request, monkeypatch, capsys):
        """Test that _success outputs JSON with 'success': True and 'data' key."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"name": "test"}]}'
        mock_response.json.return_value = {"data": [{"name": "test"}]}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client.devices_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert "data" in output

    def test_error_output_format(self, monkeypatch, capsys):
        """Test that _error outputs JSON with 'error': True and 'message' key."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()
        client._error("Something went wrong")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "message" in output
        assert output["message"] == "Something went wrong"

    def test_dry_run_output_format(self, monkeypatch, capsys):
        """Test that _dry_run outputs JSON with required fields."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiNetworkClient()
        client._dry_run("POST", "https://192.0.2.1/api/endpoint")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True
        assert output["action"] == "POST"
        assert output["endpoint"] == "https://192.0.2.1/api/endpoint"
        assert "message" in output

    def test_base_v1_url_construction(self, monkeypatch):
        """Test that base_v1 URL contains host and site."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "198.51.100.1")
        monkeypatch.setenv("UNIFI_SITE", "homelab")

        client = UnifiNetworkClient()

        assert "198.51.100.1" in client.base_v1
        assert "homelab" in client.base_v1
        assert client.base_v1 == "https://198.51.100.1/proxy/network/api/s/homelab"

    def test_base_v2_url_construction(self, monkeypatch):
        """Test that base_v2 URL contains 'v2' and host and site."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "198.51.100.1")
        monkeypatch.setenv("UNIFI_SITE", "homelab")

        client = UnifiNetworkClient()

        assert "v2" in client.base_v2
        assert "198.51.100.1" in client.base_v2
        assert "homelab" in client.base_v2
        assert client.base_v2 == "https://198.51.100.1/proxy/network/v2/api/site/homelab"

    @patch("unifi_network_client.requests.request")
    def test_request_includes_api_key_header(self, mock_request, monkeypatch):
        """Test that the X-Api-Key header is sent with every request."""
        monkeypatch.setenv("UNIFI_API_KEY", "my-secret-api-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = UnifiNetworkClient()
        client._request("GET", f"{client.base_v1}/stat/device")

        call_args = mock_request.call_args
        assert call_args[1]["headers"]["X-Api-Key"] == "my-secret-api-key"
