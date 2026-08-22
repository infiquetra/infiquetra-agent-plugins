#!/usr/bin/env python3
"""Credential-safe, read-only UniFi discovery.

Discovery composes only the list operations the existing UniFi clients classify
as read-only — GET of networks (from which VLANs are derived), devices,
clients, and cameras — and never passes ``--confirm``. Camera snapshot is
itself a GET, but it returns imagery rather than topology, so it is forbidden
here even though it would pass a method-only filter.

Because neither client filters or redacts a controller response, persistence
is default-deny. The in-memory inventory and a generated proposed profile stay
in memory unless the operator names an output path, and a path inside this
package's own directory or inside the repository working tree is refused. When
no working tree can be determined at all, the write is refused rather than
allowed, because that is the case where the deny-list would otherwise have
nothing to compare against. Generating a proposal never writes the live
configured profile: the proposal is a review artifact, not an applied one, and
every intent field on it is the explicit unknown.

The module imports the standard library only. Live HTTP is an injected
transport, not an import-time side effect; tests supply a fixture transport
and never open a network connection.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import site_profile
from site_profile import (
    INTENT_FIELDS,
    UNKNOWN_LITERAL,
    SiteProfileError,
    default_profile_path,
    validate_profile,
)


# --- operation classification ---------------------------------------------

#: Resources this unit is required to cover. VLANs have no list endpoint of
#: their own in the shipped client; they are derived from the networks GET.
DISCOVERY_RESOURCES = ("networks", "vlans", "devices", "clients", "cameras")

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
READ_ONLY_METHOD = "GET"

NETWORK_API_PREFIX = "/proxy/network/api/s/{site}"
PROTECT_API_PREFIX = "/proxy/protect/integration/v1"

#: Path suffix that identifies a Protect camera snapshot. Snapshot is GET, so
#: a method-only read-only check is not enough to keep it out of discovery.
CAMERA_SNAPSHOT_SUFFIX = "/snapshot"


@dataclass(frozen=True)
class ReadOnlyOperation:
    """One classified-read-only list operation composed by discovery."""

    name: str
    method: str
    path_template: str
    resource: str
    envelope: str

    def path(self, site: str) -> str:
        return self.path_template.format(site=site)


#: The closed catalog discovery is allowed to compose. A new row is a change
#: to the read-only contract, not a convenience. Every method is GET.
READ_ONLY_OPERATIONS: tuple[ReadOnlyOperation, ...] = (
    ReadOnlyOperation(
        name="networks.list",
        method=READ_ONLY_METHOD,
        path_template=f"{NETWORK_API_PREFIX}/rest/networkconf",
        resource="networks",
        envelope="data",
    ),
    ReadOnlyOperation(
        name="devices.list",
        method=READ_ONLY_METHOD,
        path_template=f"{NETWORK_API_PREFIX}/stat/device",
        resource="devices",
        envelope="data",
    ),
    ReadOnlyOperation(
        name="clients.list",
        method=READ_ONLY_METHOD,
        path_template=f"{NETWORK_API_PREFIX}/stat/sta",
        resource="clients",
        envelope="data",
    ),
    ReadOnlyOperation(
        name="cameras.list",
        method=READ_ONLY_METHOD,
        path_template=f"{PROTECT_API_PREFIX}/cameras",
        resource="cameras",
        envelope="list",
    ),
)

#: Named so a later reader does not have to reconstruct why snapshot is
#: absent from the catalog. Discovery must never compose this row.
FORBIDDEN_OPERATIONS: tuple[dict[str, str], ...] = (
    {
        "name": "cameras.snapshot",
        "method": READ_ONLY_METHOD,
        "path_template": f"{PROTECT_API_PREFIX}/cameras/{{id}}/snapshot",
        "reason": "returns imagery rather than topology",
    },
)

RESOURCE_SUBJECT_KIND = {
    "networks": "network",
    "vlans": "network",
    "devices": "device",
    "clients": "host",
    "cameras": "device",
}

IDENTIFIER_KEYS = ("name", "hostname", "identifier", "_id", "id", "mac")
CLIENT_IDENTIFIER_KEYS = ("hostname", "name", "identifier", "mac", "_id", "id")

PROPOSAL_SITE_DESCRIPTION = (
    "Proposed profile generated from read-only discovery for operator review. "
    "Every intent field is unknown."
)


# --- policy observation ----------------------------------------------------

#: Whether an inventory's ``policies`` list is an observation at all.
#:
#: The catalog above composes no policy list operation, so discovery never
#: looks at controller policy objects. An empty ``policies`` list is therefore
#: absence of evidence, not evidence of absence, and a consumer that reads it
#: as "the controller holds no policy" will report every intended policy as
#: missing. The inventory says which of the two it means, and a consumer that
#: wants to derive absence has to find the affirmative ``observed`` value.
POLICY_OBSERVATION_KEY = "policy_observation"
POLICY_OBSERVED = "observed"
POLICY_UNAVAILABLE = "unavailable"

#: Why a discovery inventory reports its policy set as unavailable. Kept next
#: to the value so a reader does not have to re-derive it from the catalog.
POLICY_UNAVAILABLE_REASON = (
    "discovery composes no read-only policy list operation, so controller "
    "policy state is unobserved rather than empty"
)


# --- errors ---------------------------------------------------------------


class DiscoveryError(Exception):
    """Base class for every discovery failure."""


class DiscoveryPersistenceError(DiscoveryError):
    """An output path was named but is not a permitted persistence target."""


class DiscoveryTransportError(DiscoveryError):
    """The injected transport refused or could not complete a request."""


# --- invocation record ----------------------------------------------------


@dataclass(frozen=True)
class Invocation:
    """One composed call, recorded so tests can assert method, URL, and confirm."""

    method: str
    url: str
    confirm: bool
    operation: str

    def as_record(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def path(self) -> str:
        parsed = urlparse(self.url)
        return parsed.path or self.url

    def is_snapshot(self) -> bool:
        return is_snapshot_url(self.url)


def is_snapshot_url(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    return path.endswith(CAMERA_SNAPSHOT_SUFFIX)


# --- transport ------------------------------------------------------------


class Transport(Protocol):
    """Minimal controller session. Tests inject a fixture; live is opt-in."""

    def request(
        self,
        method: str,
        url: str,
        *,
        confirm: bool = False,
    ) -> Any:  # pragma: no cover - protocol
        ...


class LiveTransport:
    """Stdlib HTTP session for an operator-named controller.

    There is no default host. A missing host or API key fails in the
    constructor, before any network call. Tests never construct this with
    real credentials and never call :meth:`request`.
    """

    def __init__(self, host: str, api_key: str, verify_ssl: bool = True) -> None:
        host = (host or "").strip()
        api_key = (api_key or "").strip()
        if not host:
            raise DiscoveryError(
                "live discovery requires a controller host; there is no default"
            )
        if not api_key:
            raise DiscoveryError(
                "live discovery requires an API key; credentials never live in a profile"
            )
        self.host = host
        self.api_key = api_key
        self.verify_ssl = verify_ssl

    def request(self, method: str, url: str, *, confirm: bool = False) -> Any:
        # Imported here so loading this module in the hermetic test job never
        # depends on a network stack beyond the standard library, and so a
        # test that never calls request() cannot open a connection.
        import ssl
        import urllib.error
        import urllib.request

        if confirm:
            raise DiscoveryError("discovery never passes --confirm")
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        request = urllib.request.Request(url, headers=headers, method=method.upper())
        context = ssl.create_default_context()
        if not self.verify_ssl:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                payload = response.read()
        except urllib.error.URLError as exc:
            raise DiscoveryTransportError(f"controller request failed: {exc}") from exc
        if not payload:
            return {}
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiscoveryTransportError(f"unparseable controller response: {exc}") from exc


# --- persistence ----------------------------------------------------------


#: This package's own directory tree, resolved from the module rather than
#: from the current directory. Persistence refuses it with or without a
#: repository root: a package copied out of a checkout keeps its committable
#: layout but loses the ``.git`` entry the walk below looks for, and writing
#: raw controller responses beside the package source is the exact outcome
#: default-deny persistence exists to prevent.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def repository_root_from(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (or cwd) until a ``.git`` entry is found."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def refuse_repository_output(
    path: Path,
    repository_root: Path | None = None,
) -> Path:
    """Return a resolved output path, or refuse it as a committable location.

    Two independent refusals, because the second one cannot always be
    evaluated:

    - inside :data:`PACKAGE_ROOT`, always. This one needs no checkout to
      decide, so it still holds for a copy of the package taken out of one.
    - inside the repository working tree, when that tree is known.

    When no root is named and the walk finds none, the deny-list has nothing
    to evaluate. That is refused rather than allowed. A deny-list that returns
    the path whenever it cannot decide is not a deny-list, and the case where
    it cannot decide — a package copied out of its checkout — is exactly the
    case where an unfiltered controller response would land next to
    committable files. The operator names ``--repository-root`` to say which
    tree to protect.
    """
    resolved = Path(path).expanduser().resolve()
    if _is_inside(resolved, PACKAGE_ROOT):
        raise DiscoveryPersistenceError(
            "refusing to write discovery output inside the package directory: "
            f"{resolved}"
        )
    if repository_root is not None:
        root = Path(repository_root).resolve()
    else:
        root = repository_root_from()
        if root is None:
            raise DiscoveryPersistenceError(
                "refusing to write discovery output: no repository working tree "
                "could be determined from the current directory, so the in-tree "
                f"deny-list cannot be evaluated for {resolved}. Name the tree to "
                "protect with --repository-root."
            )
    if _is_inside(resolved, root):
        raise DiscoveryPersistenceError(
            "refusing to write discovery output inside the repository working "
            f"tree: {resolved}"
        )
    return resolved


def live_profile_target(
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> Path:
    """Where the live profile would be written, whether or not the file exists.

    Used only as a persistence deny-list for proposed profiles. Resolution
    here must not raise when the named file is missing: the question is
    "would this write clobber the live profile?", not "can we load it?".
    """
    env = os.environ if environ is None else environ
    if site_profile.ENVIRONMENT_VARIABLE in env:
        named = (env.get(site_profile.ENVIRONMENT_VARIABLE) or "").strip()
        if named:
            return Path(named).expanduser()
    config = site_profile.read_config(environ=env, config_path=config_path)
    configured = config.get("site_profile_path")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser()
    return default_profile_path(environ=env)


def refuse_live_profile_output(
    path: Path,
    configured_profile_path: Path | None,
) -> None:
    """Generating a proposal must never write the live configured profile."""
    if configured_profile_path is None:
        return
    if path.resolve() == Path(configured_profile_path).expanduser().resolve():
        raise DiscoveryPersistenceError(
            "generating a proposed profile never writes the live profile at "
            f"{path}"
        )


def persist_payload(
    payload: Mapping[str, Any],
    output: Path,
    *,
    repository_root: Path | None = None,
    configured_profile_path: Path | None = None,
) -> Path:
    """Write ``payload`` only to an operator-named, outside-the-tree path."""
    resolved = refuse_repository_output(output, repository_root=repository_root)
    refuse_live_profile_output(resolved, configured_profile_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return resolved


# --- inventory extraction -------------------------------------------------


def unwrap_records(payload: object, envelope: str) -> list[Mapping[str, Any]]:
    """Normalize a client-shaped payload to a list of record mappings."""
    if envelope == "data" and isinstance(payload, dict):
        payload = payload.get("data", [])
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        return [payload]
    return []


def record_identifier(record: Mapping[str, Any], resource: str) -> str | None:
    keys = CLIENT_IDENTIFIER_KEYS if resource == "clients" else IDENTIFIER_KEYS
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def observed_subject(resource: str, identifier: str) -> dict[str, Any]:
    """A profile subject carrying observed identity and unknown intent."""
    kind = RESOURCE_SUBJECT_KIND[resource]
    subject = {
        "kind": kind,
        "identifier": identifier,
        "trust_role": UNKNOWN_LITERAL,
        "criticality": UNKNOWN_LITERAL,
        "ownership": UNKNOWN_LITERAL,
    }
    return subject


def extract_vlans(networks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """VLAN rows derived from the networks list; no extra controller call."""
    vlans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for network in networks:
        vlan = network.get("vlan")
        if vlan is None or isinstance(vlan, bool):
            continue
        identifier = str(vlan).strip()
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        parent = record_identifier(network, "networks")
        entry: dict[str, Any] = {"identifier": identifier}
        if parent:
            entry["network"] = parent
        vlans.append(entry)
    return vlans


def summarize_records(
    records: list[Mapping[str, Any]], resource: str
) -> list[dict[str, Any]]:
    """Keep observed identifiers (and VLAN ids) only; drop the raw payload."""
    summarized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        identifier = record_identifier(record, resource)
        if identifier is None or identifier in seen:
            continue
        seen.add(identifier)
        entry: dict[str, Any] = {"identifier": identifier}
        if resource == "networks" and record.get("vlan") is not None:
            entry["vlan"] = record.get("vlan")
        summarized.append(entry)
    return summarized


def empty_inventory(site: str) -> dict[str, Any]:
    inventory: dict[str, Any] = {resource: [] for resource in DISCOVERY_RESOURCES}
    inventory["site"] = {"identifier": site}
    inventory["policies"] = []
    inventory[POLICY_OBSERVATION_KEY] = POLICY_UNAVAILABLE
    return inventory


# --- proposal -------------------------------------------------------------


def proposed_profile(inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Build a review-only profile: observed identity, unknown intent.

    Prefilling an intent field from observation would be the inference the
    no-inference rule forbids. ``intended_policies`` is therefore empty rather
    than guessed from networks or hosts, and every subject intent field is
    the literal ``unknown``.
    """
    site_identifier = "discovered"
    site = inventory.get("site")
    if isinstance(site, Mapping):
        candidate = site.get("identifier")
        if isinstance(candidate, str) and candidate.strip():
            site_identifier = candidate.strip()

    subjects: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for resource in ("networks", "devices", "clients", "cameras"):
        for entry in inventory.get(resource, []):
            if not isinstance(entry, Mapping):
                continue
            identifier = entry.get("identifier")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            subject = observed_subject(resource, identifier.strip())
            key = (subject["kind"], subject["identifier"])
            if key in seen:
                continue
            seen.add(key)
            subjects.append(subject)

    document = {
        "schema_version": site_profile.SUPPORTED_SCHEMA_VERSIONS[0],
        "site": {
            "identifier": site_identifier,
            "description": PROPOSAL_SITE_DESCRIPTION,
        },
        "subjects": subjects,
        "intended_policies": [],
        "operational_constraints": [],
    }
    return validate_profile(document)


def assert_unknown_intent(document: Mapping[str, Any]) -> None:
    """Fail loudly if any intent field on a proposal is not unknown.

    Exposed so tests (and a later reader) share one field-by-field check
    rather than re-deriving the no-inference rule.
    """
    for subject in document.get("subjects", []):
        for field in INTENT_FIELDS:
            if field == "intended_policies":
                continue
            value = subject.get(field)
            if not site_profile.is_unknown(value):
                raise DiscoveryError(
                    f"proposed profile subject {subject.get('identifier')!r} "
                    f"has inferred {field}={value!r}"
                )
    if document.get("intended_policies"):
        raise DiscoveryError(
            "proposed profile prefills intended_policies; observation cannot "
            "establish operator policy"
        )


# --- session --------------------------------------------------------------


@dataclass
class DiscoveryResult:
    """In-memory discovery outcome. Persistence is optional and default-deny."""

    inventory: dict[str, Any]
    invocations: tuple[Invocation, ...]
    proposed_profile: dict[str, Any] | None
    written_path: Path | None

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "inventory": self.inventory,
            "invocations": [invocation.as_record() for invocation in self.invocations],
            "proposed_profile": self.proposed_profile,
            "wrote": str(self.written_path) if self.written_path is not None else None,
        }
        return payload


class DiscoverySession:
    """Compose the read-only catalog against an injected transport."""

    def __init__(
        self,
        transport: Transport,
        *,
        host: str,
        site: str,
    ) -> None:
        self.transport = transport
        self.host = host.rstrip("/")
        if "://" in self.host:
            # An operator may pass a full origin; discovery still only GETs.
            parsed = urlparse(self.host)
            self.origin = f"{parsed.scheme}://{parsed.netloc}"
        else:
            self.origin = f"https://{self.host}"
        self.site = site
        self.invocations: list[Invocation] = []

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.origin}{path}"

    def _guard(self, method: str, url: str, confirm: bool, operation: str) -> None:
        if confirm:
            raise DiscoveryError(
                f"discovery never passes --confirm (operation {operation})"
            )
        if method.upper() in MUTATING_METHODS or method.upper() != READ_ONLY_METHOD:
            raise DiscoveryError(
                f"discovery refuses non-GET method {method.upper()} for {url}"
            )
        if is_snapshot_url(url):
            raise DiscoveryError(f"discovery never invokes a camera snapshot: {url}")

    def _call(self, operation: ReadOnlyOperation) -> Any:
        url = self._url(operation.path(self.site))
        invocation = Invocation(
            method=operation.method,
            url=url,
            confirm=False,
            operation=operation.name,
        )
        self.invocations.append(invocation)
        self._guard(operation.method, url, confirm=False, operation=operation.name)
        return self.transport.request(operation.method, url, confirm=False)

    def collect(self) -> dict[str, Any]:
        inventory = empty_inventory(self.site)
        for operation in READ_ONLY_OPERATIONS:
            payload = self._call(operation)
            records = unwrap_records(payload, operation.envelope)
            inventory[operation.resource] = summarize_records(
                records, operation.resource
            )
        inventory["vlans"] = extract_vlans(
            # Re-derive from summarized networks, which still carry vlan.
            inventory["networks"]
        )
        # Not observed, so not empty. See POLICY_OBSERVATION_KEY.
        inventory["policies"] = []
        inventory[POLICY_OBSERVATION_KEY] = POLICY_UNAVAILABLE
        return inventory


def discover(
    transport: Transport,
    *,
    host: str = "controller.example",
    site: str = "default",
    propose: bool = False,
    output: Path | str | None = None,
    repository_root: Path | None = None,
    configured_profile_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> DiscoveryResult:
    """Run read-only discovery. Writes a file only when ``output`` is named.

    ``host`` is used only to build request URLs for the injected transport.
    Tests pass an inert hostname; live callers pass the operator's controller.
    """
    session = DiscoverySession(transport, host=host, site=site)
    inventory = session.collect()
    proposal = proposed_profile(inventory) if propose else None
    if proposal is not None:
        assert_unknown_intent(proposal)

    written: Path | None = None
    if output is not None:
        live_profile = (
            Path(configured_profile_path)
            if configured_profile_path is not None
            else default_profile_path(environ)
        )
        written = persist_payload(
            proposal if proposal is not None else inventory,
            Path(output),
            repository_root=repository_root,
            configured_profile_path=live_profile,
        )

    return DiscoveryResult(
        inventory=inventory,
        invocations=tuple(session.invocations),
        proposed_profile=proposal,
        written_path=written,
    )


def assert_read_only(invocations: tuple[Invocation, ...] | list[Invocation]) -> None:
    """Fail if any recorded call is mutating, confirmed, or a snapshot.

    This is the verification the plan names: a method-and-URL recorder that
    shows zero non-GET calls across the whole discovery path.
    """
    if not invocations:
        raise DiscoveryError("discovery recorded no invocations")
    for invocation in invocations:
        if invocation.method.upper() != READ_ONLY_METHOD:
            raise DiscoveryError(
                f"non-GET invocation recorded: {invocation.method} {invocation.url}"
            )
        if invocation.confirm:
            raise DiscoveryError(
                f"--confirm was passed for {invocation.operation}: {invocation.url}"
            )
        if invocation.is_snapshot():
            raise DiscoveryError(
                f"camera snapshot was invoked: {invocation.url}"
            )


# --- CLI ------------------------------------------------------------------


def _json_error(exc: BaseException) -> int:
    print(
        json.dumps(
            {"error": str(exc), "error_type": type(exc).__name__},
            indent=2,
        )
    )
    return 1


def live_transport_from(
    environ: Mapping[str, str] | None = None,
    host: str | None = None,
    api_key: str | None = None,
) -> LiveTransport:
    env = os.environ if environ is None else environ
    resolved_host = (host or env.get("UNIFI_HOST") or "").strip()
    resolved_key = (api_key or env.get("UNIFI_API_KEY") or "").strip()
    verify_raw = (env.get("UNIFI_VERIFY_SSL") or "1").strip().lower()
    verify_ssl = verify_raw not in {"0", "false", "no"}
    return LiveTransport(host=resolved_host, api_key=resolved_key, verify_ssl=verify_ssl)


def main(
    argv: list[str] | None = None,
    *,
    transport: Transport | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run discovery and print JSON on standard output.

    ``--confirm`` is deliberately not a flag. Passing it is an argparse error
    rather than a confirmed mutation. A live controller session is constructed
    only when no transport is injected and both host and API key are present;
    otherwise the process exits before any network call.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Credential-safe, read-only UniFi discovery. Writes a file only "
            "when --output names a path outside the repository working tree."
        )
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Operator-named path outside the repository. Omitted means write nothing.",
    )
    parser.add_argument(
        "--propose-profile",
        action="store_true",
        help="Generate a proposed profile for operator review; does not apply it.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Controller host. Required for a live session; there is no default.",
    )
    parser.add_argument(
        "--site",
        default=None,
        help="UniFi site slug (defaults to UNIFI_SITE or 'default').",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Site-profile configuration file, used only to locate the live profile.",
    )
    parser.add_argument(
        "--repository-root",
        default=None,
        help="Working tree root used to refuse in-repo output paths.",
    )
    arguments = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    site = (arguments.site or env.get("UNIFI_SITE") or "default").strip() or "default"
    host = (arguments.host or env.get("UNIFI_HOST") or "").strip()
    config_path = Path(arguments.config_path) if arguments.config_path else None
    repository_root = (
        Path(arguments.repository_root) if arguments.repository_root else None
    )

    try:
        session_transport = transport
        if session_transport is None:
            session_transport = live_transport_from(environ=env, host=host or None)
        if not host:
            host = getattr(session_transport, "host", None) or "controller.example"
        configured = live_profile_target(environ=env, config_path=config_path)
        result = discover(
            session_transport,
            host=host,
            site=site,
            propose=arguments.propose_profile,
            output=Path(arguments.output) if arguments.output else None,
            repository_root=repository_root,
            configured_profile_path=configured,
            environ=env,
        )
        assert_read_only(result.invocations)
    except (DiscoveryError, SiteProfileError) as exc:
        return _json_error(exc)

    print(json.dumps(result.as_json(), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
