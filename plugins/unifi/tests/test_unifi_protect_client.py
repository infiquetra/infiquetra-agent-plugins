"""Unit tests for unifi_protect_client.py."""

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add plugin skills directory to path
pytest.importorskip("urllib3")
pytest.importorskip("requests")

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent
        / "skills"
        / "unifi-protect"
        / "scripts"
    ),
)

from unifi_protect_client import UnifiProtectClient

# The clients require a controller address and no longer carry a default (plan unit U7).
# Every test below constructs a client, so the address is supplied once here; the tests that
# assert the requirement itself remove it explicitly. RFC 5737 TEST-NET-1, so no real
# operator's address is ever what a test asserts on.
TEST_HOST = "192.0.2.1"


@pytest.fixture(autouse=True)
def _supply_controller_host(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", TEST_HOST)


class TestInit:
    """Test UnifiProtectClient initialization."""

    def test_init_missing_api_key(self, monkeypatch, capsys):
        """Test initialization fails when API key is missing."""
        monkeypatch.delenv("UNIFI_API_KEY", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            UnifiProtectClient()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "UNIFI_API_KEY" in output["message"]

    def test_init_success(self, monkeypatch):
        """Test successful initialization sets expected attributes."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()

        assert client.api_key == "test-key-123"
        assert client.base_url == "https://192.0.2.1/proxy/protect/integration/v1"

    def test_init_custom_host(self, monkeypatch):
        """Test UNIFI_HOST env var overrides the default host in base_url."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "198.51.100.1")

        client = UnifiProtectClient()

        assert client.base_url == "https://198.51.100.1/proxy/protect/integration/v1"
        assert client.host == "198.51.100.1"

    def test_init_missing_host(self, monkeypatch, capsys):
        """No flag, no environment, no default: exit 1 naming UNIFI_HOST, before any request."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.delenv("UNIFI_HOST", raising=False)

        with (
            patch("unifi_protect_client.requests.request") as mock_request,
            pytest.raises(SystemExit) as exc_info,
        ):
            UnifiProtectClient()

        assert exc_info.value.code == 1
        assert mock_request.call_count == 0
        output = json.loads(capsys.readouterr().out)
        assert output["error"] is True
        assert "UNIFI_HOST" in output["message"]

    def test_init_empty_host_fails_loudly(self, monkeypatch, capsys):
        """A present-but-empty variable is absent, not a value.

        Without this the client built "https:///proxy/protect/integration/v1" and only failed
        at request time, one layer away from the mistake.
        """
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "   ")

        with pytest.raises(SystemExit) as exc_info:
            UnifiProtectClient()

        assert exc_info.value.code == 1
        assert "UNIFI_HOST" in json.loads(capsys.readouterr().out)["message"]

    def test_init_host_flag_wins_over_the_environment(self, monkeypatch):
        """An explicitly passed host is used and the environment is not consulted."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "198.51.100.9")

        client = UnifiProtectClient(host="192.0.2.1")

        assert client.host == "192.0.2.1"
        assert "198.51.100.9" not in client.base_url

    def test_init_host_from_environment_only(self, monkeypatch):
        """With no flag, the environment supplies the address."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        monkeypatch.setenv("UNIFI_HOST", "198.51.100.9")

        client = UnifiProtectClient()

        assert client.host == "198.51.100.9"
        assert client.base_url == "https://198.51.100.9/proxy/protect/integration/v1"

    def test_init_verify_ssl_false_by_default(self, monkeypatch):
        """Test SSL verification is disabled by default."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()

        assert client.verify_ssl is False

    def test_init_headers(self, monkeypatch):
        """Test headers include X-Api-Key and Content-Type."""
        monkeypatch.setenv("UNIFI_API_KEY", "my-api-key")

        client = UnifiProtectClient()

        assert client.headers["X-Api-Key"] == "my-api-key"
        assert client.headers["Content-Type"] == "application/json"


class TestRequestHandling:
    """Test _request method HTTP error and success handling."""

    @patch("unifi_protect_client.requests.request")
    def test_request_get_success(self, mock_request, monkeypatch):
        """Test a successful GET request returns parsed JSON."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'[{"id": "cam1"}]'
        mock_response.json.return_value = [{"id": "cam1"}]
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        result = client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert result == [{"id": "cam1"}]

    @patch("unifi_protect_client.requests.request")
    def test_request_post_with_confirm(self, mock_request, monkeypatch):
        """Test a confirmed POST request executes and returns JSON."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_response.json.return_value = {"ok": True}
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        result = client._request(
            "POST",
            "https://192.0.2.1/proxy/protect/integration/v1/cameras/cam1/ptz",
            data={"type": "goto"},
            confirm=True,
        )

        assert result == {"ok": True}
        mock_request.assert_called_once()

    @patch("unifi_protect_client.requests.request")
    def test_request_401_unauthorized(self, mock_request, monkeypatch, capsys):
        """Test 401 response prints error and exits."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert output["status_code"] == 401

    @patch("unifi_protect_client.requests.request")
    def test_request_403_forbidden(self, mock_request, monkeypatch, capsys):
        """Test 403 response prints permissions error and exits."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert output["status_code"] == 403
        assert "permission" in output["message"].lower()

    @patch("unifi_protect_client.requests.request")
    def test_request_404_not_found(self, mock_request, monkeypatch, capsys):
        """Test 404 response prints not-found error and exits."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras/bad-id")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert output["status_code"] == 404

    @patch("unifi_protect_client.requests.request")
    def test_request_429_rate_limited(self, mock_request, monkeypatch, capsys):
        """Test 429 response includes retry_after and exits."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "30"}
        mock_request.return_value = mock_response
        # #348: the shared primitive now retries a 429 before exiting; no real backoff sleep in tests.
        delays: list[float] = []
        monkeypatch.setattr("time.sleep", delays.append)

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

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

    @patch("unifi_protect_client.requests.request")
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
        ok.content = b'[{"id": "cam1"}]'
        ok.json.return_value = [{"id": "cam1"}]
        mock_request.side_effect = [rate_limited, rate_limited, ok]
        delays: list[float] = []
        monkeypatch.setattr("time.sleep", delays.append)

        client = UnifiProtectClient()
        result = client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert result == [{"id": "cam1"}]
        assert mock_request.call_count == 3
        # The date parsed to a large positive hint, clamped to the primitive's 60s max_delay.
        assert delays == [60.0, 60.0]

    @patch("unifi_protect_client.requests.request")
    def test_request_429_unparseable_retry_after_computes_backoff(self, mock_request, monkeypatch):
        """An unparseable Retry-After is no hint at all: computed backoff, and still retried."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "next Tuesday-ish"}
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b'[{"id": "cam1"}]'
        ok.json.return_value = [{"id": "cam1"}]
        mock_request.side_effect = [rate_limited, rate_limited, ok]
        delays: list[float] = []
        monkeypatch.setattr("time.sleep", delays.append)

        client = UnifiProtectClient()
        result = client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert result == [{"id": "cam1"}]
        assert mock_request.call_count == 3
        # Computed backoff (base 1s, doubling, 50-100% jitter) — never the flat 60s a hint gives.
        assert len(delays) == 2
        assert 0.5 <= delays[0] <= 1.0
        assert 1.0 <= delays[1] <= 2.0

    @patch("unifi_protect_client.requests.request")
    def test_request_500_server_error(self, mock_request, monkeypatch, capsys):
        """Test 500+ response prints controller error and exits."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert output["status_code"] == 503

    @patch("unifi_protect_client.requests.request")
    def test_request_timeout(self, mock_request, monkeypatch, capsys):
        """Test timeout exception prints error and exits."""
        import requests as req_lib

        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mock_request.side_effect = req_lib.exceptions.Timeout()

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "timeout" in output["message"].lower()

    @patch("unifi_protect_client.requests.request")
    def test_request_connection_error(self, mock_request, monkeypatch, capsys):
        """Test ConnectionError prints network error and exits."""
        import requests as req_lib

        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mock_request.side_effect = req_lib.exceptions.ConnectionError()

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "192.0.2.1" in output["message"]

    @patch("unifi_protect_client.requests.request")
    def test_request_ssl_error(self, mock_request, monkeypatch, capsys):
        """Test SSLError prints SSL error message and exits."""
        import requests as req_lib

        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        mock_request.side_effect = req_lib.exceptions.SSLError()

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request("GET", "https://192.0.2.1/proxy/protect/integration/v1/cameras")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "ssl" in output["message"].lower()


class TestDryRun:
    """Test dry-run behavior for mutating HTTP methods."""

    def test_post_without_confirm_is_dry_run(self, monkeypatch, capsys):
        """Test POST without confirm=True exits with dry-run output."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request(
                "POST",
                "https://192.0.2.1/proxy/protect/integration/v1/cameras/c1/ptz",
                confirm=False,
            )

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True

    def test_put_without_confirm_is_dry_run(self, monkeypatch, capsys):
        """Test PUT without confirm=True exits with dry-run output."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request(
                "PUT",
                "https://192.0.2.1/proxy/protect/integration/v1/liveviews/lv1",
                confirm=False,
            )

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True

    def test_patch_without_confirm_is_dry_run(self, monkeypatch, capsys):
        """Test PATCH without confirm=True exits with dry-run output."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request(
                "PATCH", "https://192.0.2.1/proxy/protect/integration/v1/cameras/c1", confirm=False
            )

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True

    def test_delete_without_confirm_is_dry_run(self, monkeypatch, capsys):
        """Test DELETE without confirm=True exits with dry-run output."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client._request(
                "DELETE",
                "https://192.0.2.1/proxy/protect/integration/v1/liveviews/lv1",
                confirm=False,
            )

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True

    def test_dry_run_includes_method(self, monkeypatch, capsys):
        """Test dry-run output includes the HTTP method."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit):
            client._request(
                "POST",
                "https://192.0.2.1/proxy/protect/integration/v1/cameras/c1/ptz",
                confirm=False,
            )

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["method"] == "POST"

    def test_dry_run_includes_url(self, monkeypatch, capsys):
        """Test dry-run output includes the request URL."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        url = "https://192.0.2.1/proxy/protect/integration/v1/cameras/cam-abc/ptz"

        client = UnifiProtectClient()
        with pytest.raises(SystemExit):
            client._request("POST", url, confirm=False)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["url"] == url

    def test_dry_run_includes_body_when_data_provided(self, monkeypatch, capsys):
        """Test dry-run output includes the request body when data is given."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        body = {"type": "goto", "payload": {"presetId": 3}}

        client = UnifiProtectClient()
        with pytest.raises(SystemExit):
            client._request(
                "POST",
                "https://192.0.2.1/proxy/protect/integration/v1/cameras/c1/ptz",
                data=body,
                confirm=False,
            )

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["body"] == body

    @patch("unifi_protect_client.requests.request")
    def test_dry_run_makes_no_http_call(self, mock_request, monkeypatch):
        """Test dry-run does not make any HTTP request."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit):
            client._request(
                "POST",
                "https://192.0.2.1/proxy/protect/integration/v1/cameras/c1/ptz",
                confirm=False,
            )

        mock_request.assert_not_called()


class TestCameras:
    """Test camera-related methods."""

    @patch("unifi_protect_client.requests.request")
    def test_cameras_list(self, mock_request, monkeypatch, capsys):
        """Test cameras_list returns success with camera list."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        cameras = [{"id": "cam1", "name": "Front Door"}, {"id": "cam2", "name": "Garage"}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(cameras).encode()
        mock_response.json.return_value = cameras
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.cameras_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert len(output["data"]) == 2
        assert output["count"] == 2

    @patch("unifi_protect_client.requests.request")
    def test_cameras_get(self, mock_request, monkeypatch, capsys):
        """Test cameras_get returns details for a specific camera."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        camera = {"id": "cam1", "name": "Front Door", "state": "CONNECTED"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(camera).encode()
        mock_response.json.return_value = camera
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.cameras_get("cam1")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["id"] == "cam1"
        assert output["data"]["name"] == "Front Door"

    @patch("unifi_protect_client.requests.request")
    def test_cameras_snapshot_to_file(self, mock_request, monkeypatch, capsys, tmp_path):
        """Test cameras_snapshot saves image bytes to file and reports path."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        fake_jpeg = b"\xff\xd8\xff\xe0fake-jpeg-content"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_jpeg
        mock_request.return_value = mock_response

        output_file = tmp_path / "snapshot.jpg"
        client = UnifiProtectClient()
        client.cameras_snapshot("cam1", output_path=str(output_file))

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["saved_to"] == str(output_file)
        assert output["data"]["size_bytes"] == len(fake_jpeg)

    @patch("unifi_protect_client.requests.request")
    def test_cameras_snapshot_base64(self, mock_request, monkeypatch, capsys):
        """Test cameras_snapshot returns base64 data when no output path given."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        fake_jpeg = b"\xff\xd8\xff\xe0fake-jpeg-content"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_jpeg
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.cameras_snapshot("cam1")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["encoding"] == "base64"
        assert output["data"]["format"] == "jpeg"
        assert "data" in output["data"]

    @patch("unifi_protect_client.requests.request")
    def test_cameras_update_dry_run(self, mock_request, monkeypatch, capsys):
        """Test cameras_update without confirm produces dry-run output."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client.cameras_update("cam1", {"name": "New Name"}, confirm=False)

        assert exc_info.value.code == 0
        mock_request.assert_not_called()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True


class TestLiveviews:
    """Test liveview-related methods."""

    @patch("unifi_protect_client.requests.request")
    def test_liveviews_list(self, mock_request, monkeypatch, capsys):
        """Test liveviews_list returns all liveviews."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        liveviews = [{"id": "lv1", "name": "Main View"}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(liveviews).encode()
        mock_response.json.return_value = liveviews
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.liveviews_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["count"] == 1
        assert output["data"][0]["id"] == "lv1"

    @patch("unifi_protect_client.requests.request")
    def test_liveviews_get(self, mock_request, monkeypatch, capsys):
        """Test liveviews_get fetches a single liveview by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        liveview = {"id": "lv1", "name": "Main View", "slots": []}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(liveview).encode()
        mock_response.json.return_value = liveview
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.liveviews_get("lv1")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["id"] == "lv1"

    def test_liveviews_create_dry_run(self, monkeypatch, capsys):
        """Test liveviews_create without confirm produces dry-run output."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client.liveviews_create({"name": "New View"}, confirm=False)

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True

    @patch("unifi_protect_client.requests.request")
    def test_liveviews_create_confirmed(self, mock_request, monkeypatch, capsys):
        """Test liveviews_create with confirm sends POST to /liveviews."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        new_liveview = {"id": "lv2", "name": "New View"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(new_liveview).encode()
        mock_response.json.return_value = new_liveview
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.liveviews_create({"name": "New View"}, confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["message"] == "Liveview created"

        call_args = mock_request.call_args
        assert call_args[1]["url"].endswith("/liveviews")
        assert call_args[1]["method"] == "POST"

    @patch("unifi_protect_client.requests.request")
    def test_liveviews_delete_confirmed(self, mock_request, monkeypatch, capsys):
        """Test liveviews_delete with confirm sends DELETE and reports success."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b""
        mock_response.json.return_value = {}
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.liveviews_delete("lv1", confirm=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert "lv1" in output["message"]
        assert "deleted" in output["message"].lower()

        call_args = mock_request.call_args
        assert call_args[1]["method"] == "DELETE"


class TestLights:
    """Test light-related methods."""

    @patch("unifi_protect_client.requests.request")
    def test_lights_list(self, mock_request, monkeypatch, capsys):
        """Test lights_list returns all lights."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        lights = [{"id": "light1", "name": "Front Flood"}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(lights).encode()
        mock_response.json.return_value = lights
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.lights_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["count"] == 1

    @patch("unifi_protect_client.requests.request")
    def test_lights_get(self, mock_request, monkeypatch, capsys):
        """Test lights_get fetches a single light by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        light = {"id": "light1", "name": "Front Flood", "isOn": False}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(light).encode()
        mock_response.json.return_value = light
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.lights_get("light1")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["id"] == "light1"

    def test_lights_update_dry_run(self, monkeypatch, capsys):
        """Test lights_update without confirm produces dry-run output."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client.lights_update("light1", {"isOn": True}, confirm=False)

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True


class TestSensors:
    """Test sensor-related methods."""

    @patch("unifi_protect_client.requests.request")
    def test_sensors_list(self, mock_request, monkeypatch, capsys):
        """Test sensors_list returns all sensors."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        sensors = [{"id": "sensor1", "name": "Motion Sensor"}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(sensors).encode()
        mock_response.json.return_value = sensors
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.sensors_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["count"] == 1

    @patch("unifi_protect_client.requests.request")
    def test_sensors_get(self, mock_request, monkeypatch, capsys):
        """Test sensors_get fetches a single sensor by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        sensor = {"id": "sensor1", "name": "Door Sensor", "isOpened": False}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(sensor).encode()
        mock_response.json.return_value = sensor
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.sensors_get("sensor1")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["id"] == "sensor1"

    def test_sensors_update_dry_run(self, monkeypatch, capsys):
        """Test sensors_update without confirm produces dry-run output."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        with pytest.raises(SystemExit) as exc_info:
            client.sensors_update("sensor1", {"name": "Renamed Sensor"}, confirm=False)

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["dry_run"] is True


class TestChimes:
    """Test chime-related methods."""

    @patch("unifi_protect_client.requests.request")
    def test_chimes_list(self, mock_request, monkeypatch, capsys):
        """Test chimes_list returns all chimes."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        chimes = [{"id": "chime1", "name": "Doorbell"}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(chimes).encode()
        mock_response.json.return_value = chimes
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.chimes_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["count"] == 1

    @patch("unifi_protect_client.requests.request")
    def test_chimes_get(self, mock_request, monkeypatch, capsys):
        """Test chimes_get fetches a single chime by ID."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        chime = {"id": "chime1", "name": "Doorbell", "volume": 80}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(chime).encode()
        mock_response.json.return_value = chime
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.chimes_get("chime1")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["data"]["id"] == "chime1"
        assert output["data"]["volume"] == 80


class TestViewers:
    """Test viewer-related methods."""

    @patch("unifi_protect_client.requests.request")
    def test_viewers_list(self, mock_request, monkeypatch, capsys):
        """Test viewers_list returns all viewers."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        viewers = [{"id": "viewer1", "name": "Living Room TV"}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(viewers).encode()
        mock_response.json.return_value = viewers
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.viewers_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["success"] is True
        assert output["count"] == 1
        assert output["data"][0]["id"] == "viewer1"


class TestEdgeCases:
    """Test edge cases and output format contracts."""

    @patch("unifi_protect_client.requests.request")
    def test_snapshot_binary_content_written_to_file(self, mock_request, monkeypatch, tmp_path):
        """Test snapshot bytes are written exactly as received to file."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_jpeg
        mock_request.return_value = mock_response

        output_file = tmp_path / "test_snap.jpg"
        client = UnifiProtectClient()
        client.cameras_snapshot("cam1", output_path=str(output_file))

        assert output_file.exists()
        assert output_file.read_bytes() == fake_jpeg

    @patch("unifi_protect_client.requests.request")
    def test_snapshot_base64_decodable(self, mock_request, monkeypatch, capsys):
        """Test base64 snapshot output decodes back to the original bytes."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        original_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = original_bytes
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.cameras_snapshot("cam1")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        decoded = base64.b64decode(output["data"]["data"])
        assert decoded == original_bytes

    @patch("unifi_protect_client.requests.request")
    def test_success_output_format(self, mock_request, monkeypatch, capsys):
        """Test success output always includes success=True and data key."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        cameras = [{"id": "cam1", "name": "Front"}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps(cameras).encode()
        mock_response.json.return_value = cameras
        mock_request.return_value = mock_response

        client = UnifiProtectClient()
        client.cameras_list()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "success" in output
        assert output["success"] is True
        assert "data" in output

    def test_error_output_format(self, monkeypatch, capsys):
        """Test error output always includes error=True and message key."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")

        client = UnifiProtectClient()
        client._error("Something went wrong", extra_field="extra_value")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["error"] is True
        assert "message" in output
        assert output["message"] == "Something went wrong"
        assert output["extra_field"] == "extra_value"

    def test_dry_run_includes_endpoint(self, monkeypatch, capsys):
        """Test dry-run output includes the full URL endpoint."""
        monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
        url = "https://192.0.2.1/proxy/protect/integration/v1/cameras/cam-xyz"

        client = UnifiProtectClient()
        with pytest.raises(SystemExit):
            client._request("PATCH", url, data={"name": "Test"}, confirm=False)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["url"] == url
        assert "cam-xyz" in output["url"]
