"""Build the pip-audit and npm-audit advisory snapshots from OSV databases already on disk.

The offline pip-audit and npm-audit rows match a repository's pins against
``<home>/.config/infiquetra/reviews/advisories/<name>/advisories.json``. This module
writes those two files from the OSV databases osv-scanner already keeps in its native
layout, ``<advisories>/osv-scanner/osv-scalibr/<ecosystem>/all.zip``. It never uses
the network.

The matching functions near the top are self-contained. The evaluator scripts the
adapters write to disk embed their source with ``inspect.getsource``, so the command
that builds a snapshot and the evaluator that reads it share one definition.

Entry format (one entry per advisory and package; every key but ``package`` and ``id``
is optional)::

    {"package": "name", "id": "GHSA-...", "aliases": ["CVE-..."],
     "version": "1.0.0",                 # the original single exact version
     "versions": ["1.0.0", "1.0.1"],     # exact published versions
     "ranges": [{"introduced": "0", "fixed": "1.2.3"}],
     "severity": "high", "url": "https://...", "cvss": 7.5}

``ranges`` holds intervals. ``introduced`` is the inclusive lower bound, ``"0"`` meaning
the first version. ``fixed`` is an exclusive upper bound and ``last_affected`` an
inclusive one; an interval with neither has no upper bound. npm compares bounds with
SemVer 2.0.0 precedence. pip honours only the unbounded interval from ``"0"``, which
needs no version ordering; it does not order PEP 440 versions.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Any, Iterator


def _reviews_load(name: str):
    """Load a sibling without occupying the bare name Saga tests import."""
    import importlib.util

    key = "infiquetra_reviews.reviews_loader"
    loader = sys.modules.get(key)
    if loader is None:
        path = Path(__file__).resolve().parent / "reviews_loader.py"
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        loader = importlib.util.module_from_spec(spec)
        sys.modules[key] = loader
        spec.loader.exec_module(loader)
    return loader.load(name)


# --- Shared matching definitions. Each is self-contained: the evaluators embed them. ---


def _pep503_name(name):
    """A package name as pip compares it (PEP 503): lower case, runs of ``-_.`` as one ``-``."""
    out = []
    separator = False
    for char in str(name).strip().lower():
        if char in "-_.":
            separator = True
            continue
        if separator and out:
            out.append("-")
        separator = False
        out.append(char)
    return "".join(out)


def _pep440_canonical(version):
    """The PEP 440 normal form of *version* for an equality test, or None when it is not PEP 440.

    The normal form follows PEP 440's normalisation rules: case, a leading ``v``, the
    spellings ``alpha``/``beta``/``c``/``pre``/``preview``/``rev``/``r``, implicit
    numbers, separators and leading zeros. Trailing zero release components are dropped
    because PEP 440 version matching pads the shorter release segment with zeros, so
    ``==1.0`` matches the published ``1.0.0``. A local label is kept: PEP 440 matches a
    local label only exactly. Nothing here orders two versions.
    """
    import re

    text = str(version).strip()
    if not text or len(text) > 128:
        return None
    match = re.fullmatch(
        r"v?(?:(?P<epoch>[0-9]+)!)?(?P<release>[0-9]+(?:\.[0-9]+)*)"
        r"(?:[-_.]?(?P<pre_l>alpha|beta|preview|pre|rc|a|b|c)[-_.]?(?P<pre_n>[0-9]+)?)?"
        r"(?:-(?P<post_n1>[0-9]+)|[-_.]?(?P<post_l>post|rev|r)[-_.]?(?P<post_n2>[0-9]+)?)?"
        r"(?:[-_.]?(?P<dev_l>dev)[-_.]?(?P<dev_n>[0-9]+)?)?"
        r"(?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?",
        text.lower(),
    )
    if match is None:
        return None
    release = [int(part) for part in match.group("release").split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    out = ""
    if match.group("epoch") and int(match.group("epoch")):
        out += str(int(match.group("epoch"))) + "!"
    out += ".".join(str(part) for part in release)
    if match.group("pre_l"):
        letter = {"alpha": "a", "beta": "b", "c": "rc", "pre": "rc", "preview": "rc"}.get(
            match.group("pre_l"), match.group("pre_l"))
        out += letter + str(int(match.group("pre_n") or 0))
    if match.group("post_n1") is not None or match.group("post_l"):
        out += ".post" + str(int(match.group("post_n1") or match.group("post_n2") or 0))
    if match.group("dev_l"):
        out += ".dev" + str(int(match.group("dev_n") or 0))
    if match.group("local"):
        parts = re.split(r"[-_.]", match.group("local"))
        out += "+" + ".".join(str(int(part)) if part.isdigit() else part for part in parts)
    return out


def _semver_key(version):
    """A sort key that orders versions by SemVer 2.0.0 precedence, or None when not SemVer.

    ``MAJOR.MINOR.PATCH`` are numbers without leading zeros. A pre-release sorts before
    its release; its dot-separated identifiers compare left to right, numeric ones by
    value and below alphanumeric ones, which compare in ASCII order; a longer list wins
    when every earlier identifier is equal. Build metadata is validated and ignored.
    Parsing is character by character, with no regular expression to backtrack.
    """
    allowed = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-")
    if not isinstance(version, str) or not 0 < len(version) <= 256:
        return None
    rest, plus, build = version.partition("+")
    if plus and not all(part and set(part) <= allowed for part in build.split(".")):
        return None
    core, dash, pre = rest.partition("-")
    numbers = core.split(".")
    if len(numbers) != 3:
        return None
    release = []
    for part in numbers:
        if not part or not part.isascii() or not part.isdigit():
            return None
        if len(part) > 1 and part[0] == "0":
            return None
        release.append(int(part))
    if not dash:
        return (release[0], release[1], release[2], 1, ())
    identifiers = []
    for part in pre.split("."):
        if not part or not set(part) <= allowed:
            return None
        if part.isdigit():
            if len(part) > 1 and part[0] == "0":
                return None
            identifiers.append((0, int(part), ""))
        else:
            identifiers.append((1, 0, part))
    return (release[0], release[1], release[2], 0, tuple(identifiers))


def _unbounded_from_zero(interval):
    """True for the interval that holds every version: introduced ``"0"`` and no upper bound."""
    return (
        isinstance(interval, dict)
        and str(interval.get("introduced", "0")) == "0"
        and interval.get("fixed") is None
        and interval.get("last_affected") is None
    )


def _semver_in_interval(version, interval):
    """True when *version* lies in one SemVer interval. Unparseable bounds never match."""
    if _unbounded_from_zero(interval):
        return True
    if not isinstance(interval, dict):
        return False
    key = _semver_key(version)
    if key is None:
        return False
    introduced = str(interval.get("introduced", "0"))
    if introduced != "0":
        low = _semver_key(introduced)
        if low is None or key < low:
            return False
    fixed = interval.get("fixed")
    last = interval.get("last_affected")
    if fixed is not None:
        high = _semver_key(fixed)
        return high is not None and key < high
    if last is not None:
        high = _semver_key(last)
        return high is not None and key <= high
    return True


def _pip_entry_matches(item, version):
    """True when the pinned *version* is affected by one pip snapshot entry.

    A single ``version`` is compared as an exact string, as it always was. A
    ``versions`` list matches the same string or the same PEP 440 normal form. Of the
    ``ranges``, only the unbounded interval from ``"0"`` is honoured: PEP 440 versions
    are never ordered here.
    """
    single = item.get("version")
    if isinstance(single, str) and single and single == version:
        return True
    listed = item.get("versions")
    if isinstance(listed, list) and listed:
        canonical = _pep440_canonical(version)
        for candidate in listed:
            if not isinstance(candidate, str):
                continue
            if candidate == version:
                return True
            if canonical is not None and _pep440_canonical(candidate) == canonical:
                return True
    ranges = item.get("ranges")
    return isinstance(ranges, list) and any(_unbounded_from_zero(r) for r in ranges)


def _npm_entry_matches(item, version):
    """True when the installed *version* is affected by one npm snapshot entry.

    A single ``version`` and a ``versions`` list compare exact strings. ``ranges`` compare
    with SemVer 2.0.0 precedence. An installed version that is not SemVer matches only an
    exact string or the unbounded interval from ``"0"``.
    """
    single = item.get("version")
    if isinstance(single, str) and single and single == version:
        return True
    listed = item.get("versions")
    if isinstance(listed, list) and version in listed:
        return True
    ranges = item.get("ranges")
    return isinstance(ranges, list) and any(_semver_in_interval(version, r) for r in ranges)


# --- The snapshot builder. ---

#: One OSV record larger than this is refused unread. The largest in the real npm
#: database on 2026-11-22 was 1.15 MB.
MAX_MEMBER_BYTES = 8 * 1024 * 1024
SCHEMA = "reviews-advisories.v2"
DOWNLOAD_COMMAND = (
    "env OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY={cache} osv-scanner scan source "
    "--offline-vulnerabilities --download-offline-databases --lockfile <a lock file>"
)
#: Snapshot directory name to the OSV ecosystem it is built from.
TARGETS = (("pip-audit", "PyPI"), ("npm-audit", "npm"))
_SEVERITIES = {"LOW": "low", "MODERATE": "moderate", "HIGH": "high", "CRITICAL": "critical"}
_ID_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_.:")


def _text(value: object, limit: int) -> str | None:
    """A non-empty printable string no longer than *limit*, else None."""
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    if not value.isprintable() or value != value.strip():
        return None
    return value


def _identifier(value: object) -> str | None:
    text = _text(value, 128)
    if text is None or not set(text) <= _ID_CHARS:
        return None
    return text


def osv_database(home: Path, ecosystem: str) -> Path | None:
    """The first ``all.zip`` for *ecosystem* in the osv-scanner snapshot folders, or None.

    The reviews folder is preferred over the legacy ``.saga`` folder, and the
    ``osv-scanner`` name over ``osv``, the same order the osv-scanner row reads.
    """
    tools = _reviews_load("review_tools")
    for name in tools._ADVISORY_ADAPTER_NAMES["osv-scanner"]:
        for relative in tools._ADVISORY_ROOTS:
            folder = Path(home) / relative / name
            for candidate in (
                folder / "osv-scalibr" / ecosystem / "all.zip",
                folder / ecosystem / "all.zip",
            ):
                if candidate.is_file():
                    return candidate
    return None


def expected_database(home: Path, ecosystem: str) -> Path:
    tools = _reviews_load("review_tools")
    return Path(home) / tools._ADVISORY_ROOTS[0] / "osv-scanner" / "osv-scalibr" / ecosystem / "all.zip"


def _records(path: Path, stats: dict[str, int]) -> Iterator[dict[str, Any]]:
    """Each OSV record in the zip, read in memory as JSON only. Bad members are counted."""
    with zipfile.ZipFile(path) as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename):
            if info.is_dir():
                continue
            stats["members"] += 1
            if info.file_size > MAX_MEMBER_BYTES:
                stats["oversized"] += 1
                continue
            try:
                with archive.open(info) as handle:
                    data = handle.read(MAX_MEMBER_BYTES + 1)
            except (zipfile.BadZipFile, zlib.error, OSError, RuntimeError,
                    NotImplementedError, EOFError):
                stats["unparseable"] += 1
                continue
            if len(data) > MAX_MEMBER_BYTES:
                stats["oversized"] += 1
                continue
            try:
                record = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                stats["unparseable"] += 1
                continue
            if not isinstance(record, dict):
                stats["unparseable"] += 1
                continue
            yield record


def _event_key(version: str) -> tuple[int, Any] | None:
    if version == "0":
        return (0, ())
    key = _semver_key(version)
    return None if key is None else (1, key)


def _semver_intervals(events: object) -> list[dict[str, str]] | None:
    """OSV SEMVER events as intervals, walked in version order. None when unreadable."""
    if not isinstance(events, list) or not events:
        return None
    parsed = []
    for position, event in enumerate(events):
        if not isinstance(event, dict) or len(event) != 1:
            return None
        (kind, value), = event.items()
        if kind not in ("introduced", "fixed", "last_affected") or not isinstance(value, str):
            return None
        if value == "0" and kind != "introduced":
            return None
        key = _event_key(value)
        if key is None:
            return None
        parsed.append((key, position, kind, value))
    parsed.sort(key=lambda item: (item[0], item[1]))
    intervals: list[dict[str, str]] = []
    opened: str | None = None
    for _key, _position, kind, value in parsed:
        if kind == "introduced":
            if opened is None:
                opened = value
        elif opened is not None:
            intervals.append({"introduced": opened, kind: value})
            opened = None
    if opened is not None:
        intervals.append({"introduced": opened})
    return intervals


def _interval_sort_key(interval: dict[str, str]) -> tuple[Any, str]:
    return (_event_key(interval["introduced"]) or (2, ()), json.dumps(interval, sort_keys=True))


def _advisory_url(record: dict[str, Any]) -> str | None:
    for reference in record.get("references") or []:
        if not isinstance(reference, dict) or reference.get("type") != "ADVISORY":
            continue
        url = _text(reference.get("url"), 2048)
        if url and url.startswith(("https://", "http://")):
            return url
    return None


def _modified(record: dict[str, Any]) -> str | None:
    """``YYYY-MM-DDTHH:MM:SSZ`` from the record's ``modified`` value, or None."""
    value = record.get("modified")
    if not isinstance(value, str) or len(value) < 19:
        return None
    stamp = value[:19]
    digits = stamp[0:4] + stamp[5:7] + stamp[8:10] + stamp[11:13] + stamp[14:16] + stamp[17:19]
    shape = stamp[4] + stamp[7] + stamp[10] + stamp[13] + stamp[16]
    if not digits.isascii() or not digits.isdigit() or shape != "--T::":
        return None
    return stamp + "Z"


def _empty_stats() -> dict[str, int]:
    return {
        "members": 0, "records": 0, "unparseable": 0, "oversized": 0, "invalid": 0,
        "withdrawn": 0, "unsupported": 0,
    }


def convert(path: Path, ecosystem: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Snapshot entries for *ecosystem* from one OSV zip, and what was read and skipped.

    ``skipped`` counts records (by id) with an affected package of this ecosystem that
    could not be expressed: a PyPI range with no ``versions`` list (other than every
    version), an npm range that is not SEMVER or does not parse, or an affected package
    with neither versions nor a usable range (a GIT-only range is one).
    """
    stats = _empty_stats()
    skipped: dict[str, set[str]] = {}
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    newest: str | None = None

    def skip(reason: str, ident: str) -> None:
        skipped.setdefault(reason, set()).add(ident)

    for record in _records(path, stats):
        stats["records"] += 1
        ident = _identifier(record.get("id"))
        affected = record.get("affected")
        if ident is None or not isinstance(affected, list):
            stats["invalid"] += 1
            continue
        stamp = _modified(record)
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
        if record.get("withdrawn"):
            stats["withdrawn"] += 1
            continue
        aliases = sorted({
            alias for alias in (_identifier(item) for item in record.get("aliases") or [])
            if alias and alias != ident
        }) if isinstance(record.get("aliases"), list) else []
        database = record.get("database_specific")
        severity = (
            _SEVERITIES.get(str(database.get("severity") or "").upper())
            if isinstance(database, dict) else None
        )
        url = _advisory_url(record)
        for package in affected:
            if not isinstance(package, dict) or not isinstance(package.get("package"), dict):
                continue
            if package["package"].get("ecosystem") != ecosystem:
                continue
            name = _text(package["package"].get("name"), 256)
            if name is None:
                skip("invalid-package", ident)
                continue
            versions = {
                version for version in (_text(item, 256) for item in package.get("versions") or [])
                if version
            } if isinstance(package.get("versions"), list) else set()
            intervals: list[dict[str, str]] = []
            unexpressed = None
            ranges = [entry for entry in package.get("ranges") or [] if isinstance(entry, dict)]
            # osv-scanner 2.6.0 reads only the versions list of a PyPI package that also
            # carries a GIT range: PYSEC records pair the commit range with a rough
            # ECOSYSTEM range such as {"introduced": "0"}, which would match every version.
            git = any(entry.get("type") == "GIT" for entry in ranges)
            for entry in ranges:
                kind = entry.get("type")
                if kind == "GIT":
                    continue
                if ecosystem == "PyPI" and git:
                    if not versions:
                        unexpressed = "pypi-git-range-without-versions"
                    continue
                if ecosystem == "npm":
                    found = _semver_intervals(entry.get("events")) if kind == "SEMVER" else None
                    if found is None:
                        unexpressed = "npm-range-not-semver" if kind != "SEMVER" else "npm-range-unparseable"
                    else:
                        intervals.extend(found)
                elif kind == "ECOSYSTEM" and entry.get("events") == [{"introduced": "0"}]:
                    intervals.append({"introduced": "0"})
                elif not versions:
                    unexpressed = "pypi-range-without-versions"
            if unexpressed is not None:
                skip(unexpressed, ident)
            if not versions and not intervals:
                if unexpressed is None:
                    skip("no-versions-or-ranges", ident)
                continue
            key = (_pep503_name(name) if ecosystem == "PyPI" else name, ident)
            item = entries.setdefault(key, {"package": key[0], "id": ident})
            if aliases:
                item["aliases"] = aliases
            if severity:
                item["severity"] = severity
            if url and ecosystem == "npm":
                item["url"] = url
            merged = {json.dumps(interval, sort_keys=True) for interval in item.get("ranges", [])}
            merged.update(json.dumps(interval, sort_keys=True) for interval in intervals)
            if merged:
                item["ranges"] = sorted(
                    (json.loads(text) for text in merged), key=_interval_sort_key)
            if versions:
                item["versions"] = sorted(set(item.get("versions", [])) | versions)
    out = []
    for key in sorted(entries):
        item = entries[key]
        if any(_unbounded_from_zero(interval) for interval in item.get("ranges", [])):
            # Every version is affected, so a versions list adds nothing.
            item["ranges"] = [{"introduced": "0"}]
            item.pop("versions", None)
        out.append(item)
    report: dict[str, Any] = dict(stats)
    report["skipped"] = {reason: len(ids) for reason, ids in sorted(skipped.items())}
    report["entries"] = len(out)
    report["advisories"] = len({item["id"] for item in out})
    report["packages"] = len({item["package"] for item in out})
    report["newest_modified"] = newest
    return out, report


def _write_private(path: Path, data: bytes) -> None:
    """Replace *path* atomically with a 0600 file. The directory is 0700."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        try:
            os.fchmod(descriptor, 0o600)
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def snapshot_bytes(entries: list[dict[str, Any]], ecosystem: str) -> bytes:
    payload = {"schema": SCHEMA, "source": "osv", "ecosystem": ecosystem, "advisories": entries}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def metadata_bytes(report: dict[str, Any], data: bytes, source: Path) -> bytes:
    newest = report.get("newest_modified")
    meta: dict[str, Any] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": "osv",
        "source_sha256": _file_sha256(source),
        "schema": SCHEMA,
        "entries": report["entries"],
        "advisories": report["advisories"],
        "packages": report["packages"],
    }
    if newest:
        meta["version"] = newest[:10]
        meta["date"] = newest[:10]
        meta["updated_at"] = newest
    return (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build(home: Path, out=None, err=None) -> int:
    """Write both snapshots from the local OSV databases. 0 when both were written."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    tools = _reviews_load("review_tools")
    root = Path(home) / tools._ADVISORY_ROOTS[0]
    missing = []
    failed = False
    for name, ecosystem in TARGETS:
        source = osv_database(home, ecosystem)
        if source is None:
            missing.append((name, ecosystem))
            continue
        try:
            entries, report = convert(source, ecosystem)
        except (OSError, zipfile.BadZipFile) as exc:
            print(f"{name}: cannot read {source}: {exc}", file=err)
            failed = True
            continue
        data = snapshot_bytes(entries, ecosystem)
        folder = root / name
        _write_private(folder / "advisories.json", data)
        _write_private(folder / "metadata.json", metadata_bytes(report, data, source))
        skipped = report["skipped"]
        print(
            f"{name}: wrote {folder / 'advisories.json'} ({len(data)} bytes): "
            f"{report['advisories']} advisories, {report['packages']} packages, "
            f"{report['entries']} entries, newest record {report['newest_modified'] or 'unknown'}",
            file=out,
        )
        print(
            f"{name}: read {source}: {report['members']} members, {report['records']} records; "
            f"withdrawn {report['withdrawn']}, unparseable {report['unparseable']}, "
            f"oversized {report['oversized']}, invalid {report['invalid']}",
            file=out,
        )
        if skipped:
            detail = ", ".join(f"{reason} {count}" for reason, count in skipped.items())
            print(f"{name}: records not matched (not expressible offline): {detail}", file=out)
        else:
            print(f"{name}: records not matched (not expressible offline): none", file=out)
    for name, ecosystem in missing:
        print(
            f"{name}: no OSV {ecosystem} database; expected {expected_database(home, ecosystem)}. "
            "Download it with: "
            + DOWNLOAD_COMMAND.format(cache=root / "osv-scanner"),
            file=err,
        )
    return 1 if missing or failed else 0
