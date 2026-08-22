# UniFi Protect API Endpoints Reference

Base URL pattern: `https://<UNIFI_HOST>/proxy/protect/integration/v1`

This document is derived from `scripts/unifi_protect_client.py` and describes only what that
client calls. The Integration API accepts API key authentication through the `X-Api-Key`
header. The older `/proxy/protect/api` path requires cookie-based authentication and is not
used by this client.

All requests send `X-Api-Key` and `Content-Type: application/json`, use a 30-second timeout,
and disable TLS verification by default because the UDM presents a self-signed certificate.

---

## Cameras

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/protect/integration/v1/cameras` | List all cameras |
| GET | `/proxy/protect/integration/v1/cameras/{id}` | Get a specific camera by ID |
| GET | `/proxy/protect/integration/v1/cameras/{id}/snapshot` | Get a JPEG snapshot from the camera |
| PATCH | `/proxy/protect/integration/v1/cameras/{id}` | Update camera settings |

The snapshot request is sent with no query parameters. The response body is raw
`image/jpeg` bytes: the client writes them to the path given by `--output`, or base64-encodes
them into its JSON wrapper when `--output` is omitted.

**Camera update body example**:
```json
{ "name": "Front Door" }
```

---

## Liveviews

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/protect/integration/v1/liveviews` | List all saved liveviews |
| GET | `/proxy/protect/integration/v1/liveviews/{id}` | Get a specific liveview by ID |
| POST | `/proxy/protect/integration/v1/liveviews` | Create a new liveview |
| PUT | `/proxy/protect/integration/v1/liveviews/{id}` | Update a liveview |
| DELETE | `/proxy/protect/integration/v1/liveviews/{id}` | Delete a liveview |

The update verb is `PUT`, not `PATCH`. Delete returns an empty body, which the client
normalizes to `{}`.

**Liveview body example**:
```json
{
  "name": "Security Overview",
  "slots": [
    { "cameras": ["<camera_id_1>"] },
    { "cameras": ["<camera_id_2>"] }
  ]
}
```

---

## Lights

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/protect/integration/v1/lights` | List all UniFi Flood Lights |
| GET | `/proxy/protect/integration/v1/lights/{id}` | Get a specific light |
| PATCH | `/proxy/protect/integration/v1/lights/{id}` | Update light settings |

**Light update body example**:
```json
{ "lightModeSettings": { "mode": "motion" } }
```

---

## Sensors

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/protect/integration/v1/sensors` | List all sensors |
| GET | `/proxy/protect/integration/v1/sensors/{id}` | Get a specific sensor |
| PATCH | `/proxy/protect/integration/v1/sensors/{id}` | Update sensor settings |

---

## Chimes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/protect/integration/v1/chimes` | List all UniFi Chimes |
| GET | `/proxy/protect/integration/v1/chimes/{id}` | Get a specific chime |
| PATCH | `/proxy/protect/integration/v1/chimes/{id}` | Update chime settings |

---

## Viewers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/proxy/protect/integration/v1/viewers` | List all UniFi Viewers |
| GET | `/proxy/protect/integration/v1/viewers/{id}` | Get a specific viewer |
| PATCH | `/proxy/protect/integration/v1/viewers/{id}` | Update viewer settings |

---

## Paths This Client Does Not Call

The client reaches no path outside the six groups above. In particular:

- Not implemented: any `stream` or stream-URL path under a camera.
- Not implemented: any `ptz` or `cameraActions` path or payload.
- Not implemented: any `events` path.
- Not implemented: any `nvr` or `bootstrap` path.
- Not implemented: the chime `play-speaker` path.

An earlier revision of this document described all of these against the cookie-authenticated
`/proxy/protect/api` base. Commit `8a14ad49` on 2026-03-17 moved the client to the Integration
API and removed the corresponding code; the description outlived it until this repair.

---

## Response Handling

The client maps controller responses to a fixed JSON surface and exits non-zero on failure.

| Status | Client behavior |
|--------|-----------------|
| 429 | Retries with bounded exponential backoff, honoring `Retry-After` (default 60 seconds). On exhaustion, emits a typed rate-limit error and exits 1 |
| 401 | `API key invalid or expired`, exit 1 |
| 403 | `Insufficient permissions. Check API key scope.`, exit 1 |
| 404 | `Resource not found. Verify camera/device ID.`, exit 1 |
| 4xx (other) | `API error: <status>`, exit 1 |
| 5xx | `Controller error: <status>`, exit 1 |
| 2xx, empty body | Normalized to `{}` |

Network-level failures are reported the same way: a 30-second timeout, a TLS verification
failure, and an unreachable host each produce a typed error and exit 1.

---

## API Notes

- **Authentication**: `X-Api-Key` header with a key generated in UniFi OS → Settings → API
  Keys. The same key works for both the Network and Protect APIs.
- **SSL**: The UDM uses a self-signed TLS certificate. Requests disable verification by
  default (`--verify-ssl` turns it on) and `urllib3.InsecureRequestWarning` is suppressed.
- **IDs**: UniFi Protect uses 24-character hex string IDs (for example
  `64a2f3b1c8e4d500011a2b3c`). They are returned in list and get responses and are required
  for every targeted operation.
- **Dry run**: `POST`, `PUT`, `PATCH`, and `DELETE` print their method, URL, and body and
  exit 0 unless `--confirm` is passed. `GET` is never gated.
- **Host**: taken from `--host`, else `UNIFI_HOST`. There is no default; an absent or
  empty value exits 1 with a structured error before any request is sent.
