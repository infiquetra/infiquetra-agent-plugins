"""Local config reader for redis-channel endpoints.

The endpoint registry lives at `~/.claude/channels/redis-channel/registry.json`
and lists the Redis backends this CC plugin can connect to. Each endpoint is
one configured router target — the plugin itself is router-agnostic, so this
could be any consumer that speaks the protocol (a Hermes profile, a custom
router, a CLI test harness).

Schema:
    {
      "endpoints": {
        "<name>": {
          "redis_url": "redis://host:6379/0",
          "redis_password_env": "MY_REDIS_PASSWORD",
          "display_name": "Human label"
        }, ...
      },
      "defaults": {
        "session_name_override_env": "CLAUDE_SESSION_NAME",
        "heartbeat_seconds": 10,
        "registry_ttl_seconds": 60,
        "destructive_confirm_seconds": 3,
        "permission_window_seconds": 30,
        "consumer_block_ms": 1000
      }
    }

A missing file is treated as "no endpoints configured" — surfaces a friendly
error to the user via the connect tool.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.claude/channels/redis-channel/registry.json").expanduser()


@dataclass(frozen=True, slots=True)
class Endpoint:
    name: str
    redis_url: str
    redis_password_env: str | None
    display_name: str


@dataclass(frozen=True, slots=True)
class Defaults:
    session_name_override_env: str = "CLAUDE_SESSION_NAME"
    heartbeat_seconds: int = 10
    registry_ttl_seconds: int = 60
    destructive_confirm_seconds: int = 3
    permission_window_seconds: int = 30
    consumer_block_ms: int = 1000
    # Name of the endpoint to use when `redis_channel_connect` is called without
    # an explicit `endpoint` arg. Falls back to single-endpoint convenience: if
    # this name isn't in endpoints AND there's exactly one configured endpoint,
    # that endpoint is used. Else `resolve_default_endpoint` raises.
    default_endpoint: str = "default"
    # Name of the endpoint to use for env-var-driven auto-connect at MCP server
    # startup (see CLAUDE_CHANNEL_AUTO_CONNECT in server/channel.py::run). When
    # None, auto-connect requires CLAUDE_CHANNEL_ENDPOINT to be set.
    auto_connect_endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class Registry:
    endpoints: dict[str, Endpoint]
    defaults: Defaults
    source: Path

    def get(self, name: str) -> Endpoint:
        try:
            return self.endpoints[name]
        except KeyError as e:
            available = ", ".join(sorted(self.endpoints)) or "<none>"
            raise EndpointNotFoundError(
                f"endpoint {name!r} not in registry (available: {available})"
            ) from e

    def resolve_default_endpoint(self) -> Endpoint:
        """Return the endpoint to use when no explicit endpoint is passed.

        Tries (in order):
          1. `defaults.default_endpoint` if it names a configured endpoint.
          2. The sole configured endpoint, if exactly one exists
             (single-endpoint convenience for solo setups).
          3. Raises EndpointNotFoundError otherwise.
        """
        name = self.defaults.default_endpoint
        if name in self.endpoints:
            return self.endpoints[name]
        if len(self.endpoints) == 1:
            return next(iter(self.endpoints.values()))
        available = ", ".join(sorted(self.endpoints)) or "<none>"
        raise EndpointNotFoundError(
            f"no default endpoint resolvable: defaults.default_endpoint={name!r} "
            f"not in registry, and multiple endpoints configured (available: "
            f"{available}). Specify --endpoint explicitly or set "
            f"defaults.default_endpoint to one of them."
        )


class RegistryError(Exception):
    """Base for registry config errors."""


class RegistryNotFoundError(RegistryError):
    """The registry.json file does not exist."""


class RegistryParseError(RegistryError):
    """The registry.json file exists but is malformed."""


class EndpointNotFoundError(RegistryError):
    """The named endpoint is not present in the registry."""


def load_registry(path: Path | None = None) -> Registry:
    """Read and validate the endpoint registry.

    Raises RegistryNotFoundError if the file is missing; the caller surfaces
    that to the user with instructions to run `/redis-channel-configure`.
    """
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise RegistryNotFoundError(
            f"registry config not found at {cfg_path} — run /redis-channel-configure to create"
        )
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RegistryParseError(f"{cfg_path}: invalid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise RegistryParseError(f"{cfg_path}: top-level must be object")

    endpoints_raw = raw.get("endpoints") or {}
    if not isinstance(endpoints_raw, dict):
        raise RegistryParseError(f"{cfg_path}: 'endpoints' must be object")

    endpoints: dict[str, Endpoint] = {}
    for name, body in endpoints_raw.items():
        if not isinstance(body, dict):
            raise RegistryParseError(f"{cfg_path}: endpoint {name!r} must be object")
        url = body.get("redis_url")
        if not isinstance(url, str) or not url:
            raise RegistryParseError(f"{cfg_path}: endpoint {name!r} missing 'redis_url'")
        endpoints[name] = Endpoint(
            name=name,
            redis_url=url,
            redis_password_env=body.get("redis_password_env"),
            display_name=body.get("display_name") or name,
        )

    defaults_raw = raw.get("defaults") or {}
    base = Defaults()  # dataclass-default values
    defaults = Defaults(
        session_name_override_env=defaults_raw.get(
            "session_name_override_env", base.session_name_override_env
        ),
        heartbeat_seconds=int(defaults_raw.get("heartbeat_seconds", base.heartbeat_seconds)),
        registry_ttl_seconds=int(
            defaults_raw.get("registry_ttl_seconds", base.registry_ttl_seconds)
        ),
        destructive_confirm_seconds=int(
            defaults_raw.get("destructive_confirm_seconds", base.destructive_confirm_seconds)
        ),
        permission_window_seconds=int(
            defaults_raw.get("permission_window_seconds", base.permission_window_seconds)
        ),
        consumer_block_ms=int(defaults_raw.get("consumer_block_ms", base.consumer_block_ms)),
        default_endpoint=str(defaults_raw.get("default_endpoint", base.default_endpoint)),
        auto_connect_endpoint=(
            str(defaults_raw["auto_connect_endpoint"])
            if defaults_raw.get("auto_connect_endpoint") is not None
            else base.auto_connect_endpoint
        ),
    )

    return Registry(endpoints=endpoints, defaults=defaults, source=cfg_path)
