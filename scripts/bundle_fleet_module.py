#!/usr/bin/env python3
"""Copy declared Fleet Core modules into a consuming plugin at build time.

The copy is generated, digest-stamped, and read-only by convention. Users never
install Fleet Core separately: the installable artifact already contains the
modules it needs. Agent Plugins 1.0 has no dependency mechanism, and inventing
a dependency field in its closed manifest is prohibited, so the declaration
lives in its own file, ``fleet-bundle.json``, at the consumer's plugin root.

Two commands:

    bundle_fleet_module.py              # generate: write stamped copies
    bundle_fleet_module.py --check      # verify: write nothing, exit non-zero
                                        # on stale source or tampering

Two digest domains, because a stamp cannot hash the bytes that contain it:

* source-payload (``source-sha256``) covers the live Fleet Core module and
  answers "is this bundle stale against its source?"
* generated-output (``output-sha256``) covers the generated file with its stamp
  block excluded and answers "has this bundle been hand-edited?"

The Fleet Core version and source commit come from that package's provenance
manifest, so there is one version source rather than a second hand-maintained
one.

Standard library only, and no network access.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_repo  # noqa: E402


DECLARATION_FILENAME = check_repo.FLEET_BUNDLE_FILENAME
SCHEMA_FILENAME = "fleet-bundle.schema.json"
FLEET_CORE_PLUGIN = check_repo.FLEET_CORE_PLUGIN_NAME
FLEET_COMMONS_DIR = Path("scripts") / "fleet_commons"
DEFAULT_BUNDLE_DIR = Path("scripts") / check_repo.BUNDLE_DIRECTORY_NAME
PROVENANCE_FILENAME = check_repo.PROVENANCE_FILENAME

GENERATED_BY = "scripts/bundle_fleet_module.py"


class BundleError(RuntimeError):
    """Raised when a declaration, source tree, or stamp cannot be trusted."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def schema_path(root: Path | None = None) -> Path:
    return (root or repository_root()) / "schemas" / SCHEMA_FILENAME


def load_schema(root: Path | None = None) -> dict[str, Any]:
    candidates: list[Path] = []
    if root is not None:
        candidates.append(root / "schemas" / SCHEMA_FILENAME)
    candidates.append(schema_path())
    seen: set[Path] = set()
    last_error: Exception | None = None
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            continue
        if not isinstance(payload, dict):
            raise BundleError(f"fleet-bundle schema {path} is not an object")
        return payload
    detail = f": {last_error}" if last_error is not None else ""
    raise BundleError(f"unreadable fleet-bundle schema {schema_path()}{detail}")


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _join_path(parent: str, child: str) -> str:
    if not parent:
        return child
    return f"{parent} {child}"


def _validate_against_schema(
    instance: object,
    schema: dict[str, Any],
    *,
    location: str,
    errors: list[str],
) -> None:
    """Validate against the closed subset this schema actually uses.

    Draft 2020-12, standard library only: type, const, enum, minLength, minItems,
    pattern, required, properties, additionalProperties=false, items, if/then/else.
    Unknown schema keywords are ignored rather than invented.
    """
    expected_type = schema.get("type")
    if expected_type is not None and _type_name(instance) != expected_type:
        article = "an" if expected_type[:1] in "aeiou" else "a"
        errors.append(f"{location} must be {article} {expected_type}")
        return

    if "const" in schema and instance != schema["const"]:
        errors.append(
            f"unsupported value {instance!r} in {location} (expected {schema['const']!r})"
        )

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(
            f"unsupported value {instance!r} in {location} (expected one of {schema['enum']!r})"
        )

    if expected_type == "string":
        assert isinstance(instance, str)
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(instance) < min_length:
            errors.append(f"{location} is empty")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, instance) is None:
            errors.append(f"unsupported value {instance!r} in {location}")
        return

    if expected_type == "array":
        assert isinstance(instance, list)
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(instance) < min_items:
            errors.append(f"{location} must contain at least {min_items} item(s)")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                _validate_against_schema(
                    item,
                    item_schema,
                    location=f"{location}[{index}]",
                    errors=errors,
                )
        return

    if isinstance(instance, dict) and (expected_type is None or expected_type == "object"):
        properties = schema.get("properties")
        allowed = set(properties) if isinstance(properties, dict) else set()
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in allowed:
                    errors.append(f"unexpected field {key!r} in {location}")
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"missing field {key!r} in {location}")
        if isinstance(properties, dict):
            for key, subschema in properties.items():
                if key in instance and isinstance(subschema, dict):
                    _validate_against_schema(
                        instance[key],
                        subschema,
                        location=_join_path(location, key),
                        errors=errors,
                    )

    if "if" in schema and isinstance(schema["if"], dict):
        if_errors: list[str] = []
        _validate_against_schema(instance, schema["if"], location=location, errors=if_errors)
        if not if_errors:
            if "then" in schema and isinstance(schema["then"], dict):
                _validate_against_schema(instance, schema["then"], location=location, errors=errors)
        elif "else" in schema and isinstance(schema["else"], dict):
            _validate_against_schema(instance, schema["else"], location=location, errors=errors)


def validate_declaration(
    payload: object,
    *,
    origin: str,
    schema: dict[str, Any] | None = None,
    root: Path | None = None,
) -> list[str]:
    """Return schema-violation errors for one declaration payload.

    Extra keys are reported by name, which is the closed-schema guarantee: a
    field this file does not declare cannot acquire meaning by being ignored.
    """
    if schema is None:
        schema = load_schema(root)
    errors: list[str] = []
    _validate_against_schema(payload, schema, location=origin, errors=errors)
    return errors


def validate_declaration_file(path: Path, *, origin: str | None = None, root: Path | None = None) -> list[str]:
    label = origin or str(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid fleet-bundle declaration {label}: {exc}"]
    return validate_declaration(payload, origin=label, root=root)


def read_pin(fleet_core: Path) -> dict[str, str]:
    """Read version and commit from the portable Fleet Core provenance manifest."""
    manifest = fleet_core / PROVENANCE_FILENAME
    if not manifest.is_file():
        raise BundleError(f"missing provenance manifest: {manifest}")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid provenance manifest {manifest}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BundleError(f"invalid provenance manifest {manifest}: expected an object")
    pin: dict[str, str] = {}
    for field in ("source_commit", "source_version"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise BundleError(f"missing non-empty {field} in {manifest}")
        pin[field] = value.strip()
    return pin


def source_path_for(name: str) -> Path:
    return FLEET_COMMONS_DIR / f"{name}.py"


def default_destination_for(name: str) -> Path:
    return DEFAULT_BUNDLE_DIR / f"{name}.py"


def _safe_relative(raw: str, *, origin: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise BundleError(f"unsafe path {raw!r} in {origin}")
    return candidate


class PlannedCopy:
    __slots__ = ("name", "source", "destination", "source_rel", "is_data")

    def __init__(
        self,
        name: str,
        source: Path,
        destination: Path,
        source_rel: Path,
        *,
        is_data: bool = False,
    ) -> None:
        self.name = name
        self.source = source
        self.destination = destination
        self.source_rel = source_rel
        self.is_data = is_data


def load_declaration(path: Path, *, origin: str, root: Path | None = None) -> dict[str, Any]:
    errors = validate_declaration_file(path, origin=origin, root=root)
    if errors:
        raise BundleError("\n".join(errors))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def plan_copies(
    root: Path,
    consumer: Path,
    *,
    declaration: dict[str, Any] | None = None,
) -> list[PlannedCopy]:
    origin = str(consumer.relative_to(root) / DECLARATION_FILENAME) if consumer.is_relative_to(root) else str(consumer / DECLARATION_FILENAME)
    declaration_path = consumer / DECLARATION_FILENAME
    payload = declaration if declaration is not None else load_declaration(
        declaration_path,
        origin=origin,
        root=root,
    )
    fleet_core = root / "plugins" / FLEET_CORE_PLUGIN
    modules = payload.get("modules")
    if not isinstance(modules, list):
        raise BundleError(f"missing modules list in {origin}")

    planned: list[PlannedCopy] = []
    seen_destinations: dict[str, str] = {}
    for index, entry in enumerate(modules):
        if not isinstance(entry, dict):
            raise BundleError(f"{origin} modules[{index}] must be an object")
        name = entry.get("name")
        if not isinstance(name, str):
            raise BundleError(f"missing name in {origin} modules[{index}]")
        source_rel = source_path_for(name)
        source = fleet_core / source_rel
        if not source.is_file():
            raise BundleError(
                f"module {name} is absent from the portable Fleet Core "
                f"(expected {source.relative_to(root) if source.is_relative_to(root) else source})"
            )
        raw_destinations = entry.get("destinations")
        if raw_destinations is None:
            destinations = [default_destination_for(name)]
        else:
            if not isinstance(raw_destinations, list):
                raise BundleError(f"{origin} modules[{index}] destinations must be an array")
            destinations = [
                _safe_relative(item, origin=f"{origin} modules[{index}] destinations")
                for item in raw_destinations
                if isinstance(item, str)
            ]
        for dest_rel in destinations:
            dest_key = dest_rel.as_posix()
            prior = seen_destinations.get(dest_key)
            if prior is not None:
                raise BundleError(
                    f"destination {dest_key} is declared twice "
                    f"(entries {prior!r} and {name!r}) in {origin}"
                )
            seen_destinations[dest_key] = name
            planned.append(
                PlannedCopy(
                    name=name,
                    source=source,
                    destination=consumer / dest_rel,
                    source_rel=source_rel,
                    is_data=False,
                )
            )

    data_entries = payload.get("data")
    if data_entries is not None:
        if not isinstance(data_entries, list):
            raise BundleError(f"{origin} data must be an array")
        for index, entry in enumerate(data_entries):
            if not isinstance(entry, dict):
                raise BundleError(f"{origin} data[{index}] must be an object")
            name = entry.get("name")
            if not isinstance(name, str):
                raise BundleError(f"missing name in {origin} data[{index}]")
            source_rel = FLEET_COMMONS_DIR / name
            source = fleet_core / source_rel
            if not source.is_file():
                raise BundleError(
                    f"data file {name} is absent from the portable Fleet Core "
                    f"(expected {source.relative_to(root) if source.is_relative_to(root) else source})"
                )
            raw_destinations = entry.get("destinations")
            if raw_destinations is None:
                destinations = [DEFAULT_BUNDLE_DIR / name]
            else:
                if not isinstance(raw_destinations, list):
                    raise BundleError(f"{origin} data[{index}] destinations must be an array")
                destinations = [
                    _safe_relative(item, origin=f"{origin} data[{index}] destinations")
                    for item in raw_destinations
                    if isinstance(item, str)
                ]
            for dest_rel in destinations:
                dest_key = dest_rel.as_posix()
                prior = seen_destinations.get(dest_key)
                if prior is not None:
                    raise BundleError(
                        f"destination {dest_key} is declared twice "
                        f"(entries {prior!r} and {name!r}) in {origin}"
                    )
                seen_destinations[dest_key] = name
                planned.append(
                    PlannedCopy(
                        name=name,
                        source=source,
                        destination=consumer / dest_rel,
                        source_rel=source_rel,
                        is_data=True,
                    )
                )
    return planned


def render_bundle(source: Path, pin: dict[str, str], source_rel: Path) -> str:
    source_bytes = source.read_bytes()
    try:
        body = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError(f"Fleet Core module is not UTF-8: {source}: {exc}") from exc
    source_digest = check_repo.sha256_bytes(source_bytes)
    output_digest = check_repo.sha256_text(body)
    stamp = (
        f"{check_repo.BUNDLE_STAMP_BEGIN}\n"
        f"# generated-by: {GENERATED_BY}\n"
        f"# source-version: {pin['source_version']}\n"
        f"# source-commit: {pin['source_commit']}\n"
        f"# {check_repo.BUNDLE_SOURCE_PATH_FIELD}: {source_rel.as_posix()}\n"
        f"# {check_repo.BUNDLE_SOURCE_DIGEST_FIELD}: {source_digest}\n"
        f"# {check_repo.BUNDLE_OUTPUT_DIGEST_FIELD}: {output_digest}\n"
        f"{check_repo.BUNDLE_STAMP_END}\n"
    )
    return stamp + body


def write_if_changed(path: Path, text: str) -> bool:
    """Write ``text`` only when the existing bytes differ. Returns True if written."""
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def write_bytes_if_changed(path: Path, data: bytes) -> bool:
    """Write ``data`` only when the existing bytes differ. Returns True if written."""
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def generate_consumer(root: Path, consumer: Path) -> list[Path]:
    pin = read_pin(root / "plugins" / FLEET_CORE_PLUGIN)
    written: list[Path] = []
    for copy in plan_copies(root, consumer):
        if copy.is_data:
            source_bytes = copy.source.read_bytes()
            if write_bytes_if_changed(copy.destination, source_bytes):
                written.append(copy.destination)
        else:
            text = render_bundle(copy.source, pin, copy.source_rel)
            if write_if_changed(copy.destination, text):
                written.append(copy.destination)
    return written


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def presence_errors(root: Path, consumer: Path, planned: list[PlannedCopy]) -> list[str]:
    """Report the declaration and the generated tree disagreeing on which files exist.

    Two directions, and both are real failures. A declared module with no
    generated bundle is the seam that leaves a package importing something
    nothing wrote; an undeclared file under the bundle directory is a generated
    copy no declaration accounts for. Neither is visible to a check that reads
    only the bundles already on disk, which is why this lives beside the
    stamp checks rather than inside them.
    """
    errors: list[str] = []
    for copy in planned:
        if not copy.destination.is_file():
            kind = "data file" if copy.is_data else "module"
            errors.append(
                f"missing generated bundle: {_relative(root, copy.destination)} "
                f"({kind} {copy.name})"
            )

    # Every generated bundle under the consumer, not just the default directory:
    # a declaration may place a copy beside each consumer of it, and a scan of
    # one fixed directory would leave the others unaccounted for.
    declared = {copy.destination.resolve() for copy in planned}
    for path in sorted(consumer.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if check_repo.BUNDLE_DIRECTORY_NAME not in path.relative_to(consumer).parts:
            continue
        if path.resolve() not in declared:
            errors.append(f"undeclared generated bundle: {_relative(root, path)}")
    return errors


def check_copy(root: Path, copy: PlannedCopy) -> list[str]:
    """Verify one generated bundle's stamp or data byte-equality. Presence is ``presence_errors``' job."""
    relative = _relative(root, copy.destination)
    if not copy.destination.is_file():
        return []

    if copy.is_data:
        try:
            actual_bytes = copy.destination.read_bytes()
        except OSError as exc:
            return [f"unreadable generated bundle {relative}: {exc}"]
        try:
            source_bytes = copy.source.read_bytes()
        except OSError as exc:
            return [f"unreadable source file {_relative(root, copy.source)}: {exc}"]
        if actual_bytes != source_bytes:
            actual_digest = check_repo.sha256_bytes(actual_bytes)
            source_digest = check_repo.sha256_bytes(source_bytes)
            return [
                f"stale source: {copy.name} in {relative} "
                f"(bundle {actual_digest}, source {source_digest})"
            ]
        return []

    try:
        text = copy.destination.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"unreadable generated bundle {relative}: {exc}"]

    errors: list[str] = []
    stamp_lines, payload = check_repo.split_bundle_stamp(text)
    if stamp_lines is None:
        return [f"unstamped generated bundle: {relative}"]
    stamp = check_repo.parse_bundle_stamp(stamp_lines)

    live_digest = check_repo.sha256_path(copy.source)
    recorded_source = stamp.get(check_repo.BUNDLE_SOURCE_DIGEST_FIELD)
    if recorded_source != live_digest:
        errors.append(
            f"stale source: {copy.name} in {relative} "
            f"(stamp {recorded_source}, source {live_digest})"
        )

    recorded_output = stamp.get(check_repo.BUNDLE_OUTPUT_DIGEST_FIELD)
    actual_output = check_repo.sha256_text(payload)
    if recorded_output != actual_output:
        errors.append(
            f"tampering: {relative} (stamp {recorded_output}, content {actual_output})"
        )
    return errors


def check_consumer(root: Path, consumer: Path) -> list[str]:
    read_pin(root / "plugins" / FLEET_CORE_PLUGIN)
    planned = plan_copies(root, consumer)
    errors = presence_errors(root, consumer, planned)
    for copy in planned:
        errors.extend(check_copy(root, copy))
    return errors


def discover_consumers(root: Path) -> list[Path]:
    plugins = root / "plugins"
    if not plugins.is_dir():
        return []
    return sorted(
        path
        for path in plugins.iterdir()
        if path.is_dir() and (path / DECLARATION_FILENAME).is_file()
    )


def resolve_consumer(root: Path, plugin: Path) -> Path:
    if plugin.is_absolute():
        consumer = plugin
    else:
        candidate = (root / plugin).resolve()
        if candidate.is_dir():
            consumer = candidate
        else:
            consumer = (root / "plugins" / plugin).resolve()
    if not (consumer / DECLARATION_FILENAME).is_file():
        raise BundleError(f"no {DECLARATION_FILENAME} under {consumer}")
    return consumer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root containing plugins/fleet-core and consumer plugins "
        "(default: this repository)",
    )
    parser.add_argument(
        "--plugin",
        type=Path,
        default=None,
        help="limit to one consumer plugin directory (relative to --root, or "
        "a name under plugins/)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify without writing; exit non-zero on stale source or tampering",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = (args.root or repository_root()).resolve()

    try:
        consumers = (
            [resolve_consumer(root, args.plugin)]
            if args.plugin is not None
            else discover_consumers(root)
        )
        if not consumers:
            raise BundleError(f"no {DECLARATION_FILENAME} found under {root / 'plugins'}")

        if args.check:
            errors: list[str] = []
            for consumer in consumers:
                errors.extend(check_consumer(root, consumer))
            if errors:
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                return 1
            print("Fleet Core bundle check passed.")
            return 0

        written = 0
        for consumer in consumers:
            paths = generate_consumer(root, consumer)
            written += len(paths)
            for path in paths:
                print(f"Wrote {_relative(root, path)}")
        if written == 0:
            print("Fleet Core bundles already up to date.")
        return 0
    except BundleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
