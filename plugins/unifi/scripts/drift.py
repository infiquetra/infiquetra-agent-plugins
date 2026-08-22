#!/usr/bin/env python3
"""Drift report over the merged actual-plus-intended UniFi view.

Actual state comes from read-only discovery. Intended state comes from an
operator site profile. With no profile there is no intended state to differ
from, so the report is discovery-only and carries no findings — that is a
supported outcome, not an error.

Two findings this unit must be able to produce when a profile is present:

- a host present on the controller but absent from the profile
- a policy expected by the profile but absent on the controller

Discovery does not fetch firewall or other policy objects, so observed
policies are whatever the inventory carries under ``policies``. An empty
list is honest: this unit's coverage is networks, VLANs, devices, clients,
and cameras. A profile policy whose identifier is not in that list is
absent on the controller.

Output is JSON on standard output. Persistence of a drift report follows
the same default-deny rule as discovery: write only to an operator-named
path outside the repository working tree.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

import discover
import site_profile
from site_profile import (
    DISCOVERY_ONLY_LIMITS,
    DISCOVERY_ONLY_MODE,
    PROFILE_MODE,
    SiteContext,
    SiteProfileError,
    load_site_context,
)


UNPROFILED_HOST = "unprofiled-host"
MISSING_POLICY = "missing-policy"

FINDING_KINDS = (UNPROFILED_HOST, MISSING_POLICY)


class DriftError(Exception):
    """Base class for every drift-report failure."""


def actual_hosts(inventory: Mapping[str, Any]) -> tuple[str, ...]:
    """Host identifiers observed on the controller.

    Clients are the connected hosts. Discovery maps them to profile kind
    ``host``, so drift compares that same identifier set to profile subjects
    of kind ``host``.
    """
    seen: list[str] = []
    for resource in ("clients",):
        for entry in inventory.get(resource, []):
            if not isinstance(entry, Mapping):
                continue
            identifier = entry.get("identifier")
            if isinstance(identifier, str) and identifier.strip():
                if identifier not in seen:
                    seen.append(identifier)
    return tuple(seen)


def observed_policy_identifiers(inventory: Mapping[str, Any]) -> tuple[str, ...]:
    seen: list[str] = []
    for entry in inventory.get("policies", []):
        if not isinstance(entry, Mapping):
            continue
        identifier = entry.get("identifier")
        if isinstance(identifier, str) and identifier.strip():
            if identifier not in seen:
                seen.append(identifier)
    return tuple(seen)


def profiled_hosts(context: SiteContext) -> tuple[str, ...]:
    return tuple(
        str(subject["identifier"])
        for subject in context.known_subjects(kind="host")
        if subject.get("identifier")
    )


def intended_policy_identifiers(context: SiteContext) -> tuple[str, ...]:
    if context.profile is None:
        return ()
    return tuple(
        str(policy["identifier"])
        for policy in context.profile.policies
        if policy.get("identifier")
    )


def report(
    inventory: Mapping[str, Any],
    context: SiteContext,
) -> dict[str, Any]:
    """Compare actual inventory to intended profile. Never infers intent."""
    if not context.has_profile:
        return {
            "mode": DISCOVERY_ONLY_MODE,
            "findings": [],
            "finding_count": 0,
            "limits": list(DISCOVERY_ONLY_LIMITS),
            "actual_hosts": list(actual_hosts(inventory)),
            "profiled_hosts": [],
            "intended_policies": [],
            "observed_policies": list(observed_policy_identifiers(inventory)),
        }

    findings: list[dict[str, Any]] = []
    intended_hosts = set(profiled_hosts(context))
    for identifier in actual_hosts(inventory):
        if identifier not in intended_hosts:
            findings.append(
                {
                    "kind": UNPROFILED_HOST,
                    "identifier": identifier,
                    "message": (
                        "host is present on the controller but absent from the profile"
                    ),
                }
            )

    observed_policies = set(observed_policy_identifiers(inventory))
    for identifier in intended_policy_identifiers(context):
        if identifier not in observed_policies:
            findings.append(
                {
                    "kind": MISSING_POLICY,
                    "identifier": identifier,
                    "message": (
                        "policy is expected by the profile but absent on the controller"
                    ),
                }
            )

    return {
        "mode": PROFILE_MODE,
        "findings": findings,
        "finding_count": len(findings),
        "limits": [],
        "actual_hosts": list(actual_hosts(inventory)),
        "profiled_hosts": list(profiled_hosts(context)),
        "intended_policies": list(intended_policy_identifiers(context)),
        "observed_policies": list(observed_policy_identifiers(inventory)),
        "site_identifier": context.profile.site_identifier if context.profile else None,
    }


def load_inventory(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DriftError(f"inventory file does not exist: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DriftError(f"unreadable inventory {path}: {exc}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("inventory"), dict):
        return payload["inventory"]
    if isinstance(payload, dict):
        return payload
    raise DriftError(f"inventory file {path} does not contain an object")


def _json_error(exc: BaseException) -> int:
    print(
        json.dumps(
            {"error": str(exc), "error_type": type(exc).__name__},
            indent=2,
        )
    )
    return 1


def main(
    argv: list[str] | None = None,
    *,
    transport: discover.Transport | None = None,
    environ: Mapping[str, str] | None = None,
    inventory: Mapping[str, Any] | None = None,
) -> int:
    """Print a drift report as JSON on standard output.

    Inventory is taken from ``--inventory``, or from an injected mapping, or
    from a read-only discovery run against an injected transport. There is no
    live default: a missing inventory and a missing transport fail before any
    controller call.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Report drift between read-only controller discovery and an "
            "operator site profile. With no profile, reports discovery-only "
            "and no findings."
        )
    )
    parser.add_argument(
        "--inventory",
        default=None,
        help="Path to a previously captured discovery inventory (JSON).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Operator-named path outside the repository. Omitted means write nothing.",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Site-profile configuration file instead of the XDG default.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Controller host used only when discovery must run live.",
    )
    parser.add_argument(
        "--site",
        default=None,
        help="UniFi site slug (defaults to UNIFI_SITE or 'default').",
    )
    parser.add_argument(
        "--repository-root",
        default=None,
        help="Working tree root used to refuse in-repo output paths.",
    )
    arguments = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    config_path = Path(arguments.config_path) if arguments.config_path else None
    repository_root = (
        Path(arguments.repository_root) if arguments.repository_root else None
    )

    try:
        context = load_site_context(environ=env, config_path=config_path)
        loaded: Mapping[str, Any]
        if inventory is not None:
            loaded = inventory
        elif arguments.inventory:
            loaded = load_inventory(Path(arguments.inventory))
        elif transport is not None:
            site = (arguments.site or env.get("UNIFI_SITE") or "default").strip() or "default"
            host = (arguments.host or env.get("UNIFI_HOST") or "").strip() or "controller.example"
            result = discover.discover(transport, host=host, site=site)
            discover.assert_read_only(result.invocations)
            loaded = result.inventory
        else:
            raise DriftError(
                "drift needs an --inventory file or an injected discovery transport; "
                "it will not open a controller session by default"
            )
        payload = report(loaded, context)
        if arguments.output:
            discover.persist_payload(
                payload,
                Path(arguments.output),
                repository_root=repository_root,
                configured_profile_path=discover.live_profile_target(
                    environ=env, config_path=config_path
                ),
            )
    except (DriftError, discover.DiscoveryError, SiteProfileError) as exc:
        return _json_error(exc)

    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
