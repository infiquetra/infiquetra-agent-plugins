"""Advisory snapshots built from local OSV databases, and the evaluators that read them.

Every test name carries ``offline`` so ``pytest -k offline`` selects it with the R6 suite.
The OSV zips here are synthetic, with inert package names and identifiers.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import stat
import subprocess
import sys
import urllib.request
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "reviews" / "scripts"


def _load(name: str) -> ModuleType:
    key = f"infiquetra_reviews.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


T = _load("review_tools")
ADV = _load("review_advisories")
SETUP = _load("review_setup")
PY = _load("review_adapters_python")
TS = _load("review_adapters_typescript")

ADVISORIES = Path(".config") / "infiquetra" / "reviews" / "advisories"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("advisory snapshot tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _record(ident: str, *affected: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"id": ident, "modified": "2026-01-02T03:04:05.123456Z", "affected": list(affected),
            **extra}


def _pkg(ecosystem: str, name: str, *, versions: list[str] | None = None,
         ranges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"package": {"ecosystem": ecosystem, "name": name}}
    if versions is not None:
        entry["versions"] = versions
    if ranges is not None:
        entry["ranges"] = ranges
    return entry


def _semver(*events: dict[str, str]) -> dict[str, Any]:
    return {"type": "SEMVER", "events": list(events)}


def _ecosystem(*events: dict[str, str]) -> dict[str, Any]:
    return {"type": "ECOSYSTEM", "events": list(events)}


_GIT = {"type": "GIT", "repo": "https://example.invalid/repo", "events": [{"introduced": "0"}]}

PYPI_RECORDS = {
    "PYSEC-2099-1.json": _record(
        "PYSEC-2099-1",
        _pkg("PyPI", "Example_Pkg", versions=["1.0.0", "1.1.0"],
             ranges=[_ecosystem({"introduced": "1.0.0"}, {"fixed": "1.2.0"})]),
        _pkg("npm", "example-pkg", ranges=[_semver({"introduced": "0"})]),
        aliases=["CVE-2099-0001"],
    ),
    "PYSEC-2099-2.json": _record(
        "PYSEC-2099-2",
        _pkg("PyPI", "example-pkg", ranges=[_ecosystem({"introduced": "2.0"}, {"fixed": "2.5"})]),
    ),
    "MAL-2099-3.json": _record(
        "MAL-2099-3", _pkg("PyPI", "evil-pkg", ranges=[_ecosystem({"introduced": "0"})]),
        modified="2026-03-04T05:06:07Z",
    ),
    "PYSEC-2099-4.json": _record(
        "PYSEC-2099-4",
        _pkg("PyPI", "commit-pkg", versions=["3.0"],
             ranges=[_GIT, _ecosystem({"introduced": "0"})]),
    ),
    "PYSEC-2099-5.json": _record(
        "PYSEC-2099-5", _pkg("PyPI", "gone-pkg", versions=["1.0"]), withdrawn="2026-01-01T00:00:00Z",
    ),
    "PYSEC-2099-11.json": _record(
        "PYSEC-2099-11",
        _pkg("PyPI", "na-pkg", versions=["2.5.0"],
             ranges=[_ecosystem({"introduced": "0"}, {"fixed": "2.6.0-NA"})]),
    ),
    "PYSEC-2099-12.json": _record(
        "PYSEC-2099-12", _pkg("PyPI", "semver-pkg", ranges=[_semver({"introduced": "0"},
                                                                     {"fixed": "1.0.0"})]),
    ),
    "broken.json": "{not json",
    "list.json": [1, 2, 3],
}

NPM_RECORDS = {
    "GHSA-aaaa-bbbb-cccc.json": _record(
        "GHSA-aaaa-bbbb-cccc",
        _pkg("npm", "left-thing",
             ranges=[_semver({"introduced": "1.0.0"}, {"fixed": "1.4.2"},
                             {"introduced": "2.0.0-beta.1"}, {"last_affected": "2.1.0"})]),
        aliases=["CVE-2099-0002"],
        database_specific={"severity": "MODERATE"},
        references=[{"type": "WEB", "url": "https://example.invalid/web"},
                    {"type": "ADVISORY", "url": "https://example.invalid/advisory"}],
    ),
    "GHSA-dddd-eeee-ffff.json": _record(
        "GHSA-dddd-eeee-ffff",
        _pkg("npm", "listed-thing", versions=["0.3.1", "0.3.2"]),
        database_specific={"severity": "CRITICAL"},
    ),
    "MAL-2099-6.json": _record("MAL-2099-6", _pkg("npm", "bad-thing",
                                                   ranges=[_semver({"introduced": "0"})])),
    "GHSA-gggg-hhhh-iiii.json": _record(
        "GHSA-gggg-hhhh-iiii",
        _pkg("npm", "eco-thing", ranges=[_ecosystem({"introduced": "0"}, {"fixed": "1.0.0"})]),
    ),
    "GHSA-jjjj-kkkk-llll.json": _record(
        "GHSA-jjjj-kkkk-llll",
        _pkg("npm", "loose-thing", ranges=[_semver({"introduced": "1.0"}, {"fixed": "2.0"})]),
    ),
    "GHSA-mmmm-nnnn-oooo.json": _record(
        "GHSA-mmmm-nnnn-oooo", _pkg("npm", "git-thing", ranges=[_GIT]),
    ),
    "GHSA-pppp-qqqq-rrrr.json": _record(
        "GHSA-pppp-qqqq-rrrr", _pkg("npm", "left-thing", versions=["9.9.9"]),
        withdrawn="2026-01-01T00:00:00Z",
    ),
    "oversized.json": _record("GHSA-ssss-tttt-uuuu", _pkg("npm", "huge-thing", versions=["1.0.0"]),
                              details="x" * 5000),
}


def _write_zip(path: Path, members: dict[str, Any], *, reverse: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = sorted(members, reverse=reverse)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            value = members[name]
            archive.writestr(name, value if isinstance(value, str) else json.dumps(value))
    return path


def _osv_home(home: Path, *, root: Path = ADVISORIES, ecosystems=("PyPI", "npm"),
              reverse: bool = False) -> Path:
    data = {"PyPI": PYPI_RECORDS, "npm": NPM_RECORDS}
    for ecosystem in ecosystems:
        _write_zip(home / root / "osv-scanner" / "osv-scalibr" / ecosystem / "all.zip",
                   data[ecosystem], reverse=reverse)
    return home


def _run_command(home: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = SETUP.main(["advisories", "--home", str(home)])
    return code, out.getvalue(), err.getvalue()


def _snapshot(home: Path, name: str) -> dict[str, Any]:
    return json.loads((home / ADVISORIES / name / "advisories.json").read_text(encoding="utf-8"))


def _entries(home: Path, name: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {(item["package"], item["id"]): item for item in _snapshot(home, name)["advisories"]}


@pytest.fixture
def small_member_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ADV, "MAX_MEMBER_BYTES", 4096)


def test_offline_advisories_command_builds_both_snapshots_from_osv_zips(
    tmp_path: Path, small_member_cap: None,
) -> None:
    home = _osv_home(tmp_path / "home")
    code, out, err = _run_command(home)
    assert code == 0, err

    pip = _entries(home, "pip-audit")
    assert set(pip) == {
        ("example-pkg", "PYSEC-2099-1"), ("example-pkg", "PYSEC-2099-2"),
        ("evil-pkg", "MAL-2099-3"), ("commit-pkg", "PYSEC-2099-4"), ("na-pkg", "PYSEC-2099-11"),
    }
    # The versions list and the ECOSYSTEM range are both kept: OSV's list can leave out
    # published versions (mostly pre-releases) that the range still covers.
    assert pip[("example-pkg", "PYSEC-2099-1")] == {
        "package": "example-pkg", "id": "PYSEC-2099-1", "aliases": ["CVE-2099-0001"],
        "versions": ["1.0.0", "1.1.0"], "ranges": [{"introduced": "1.0.0", "fixed": "1.2.0"}],
    }
    assert pip[("example-pkg", "PYSEC-2099-2")] == {
        "package": "example-pkg", "id": "PYSEC-2099-2",
        "ranges": [{"introduced": "2.0", "fixed": "2.5"}],
    }
    # A range whose bound is not PEP 440 is counted and left out; the list still counts.
    assert pip[("na-pkg", "PYSEC-2099-11")] == {
        "package": "na-pkg", "id": "PYSEC-2099-11", "versions": ["2.5.0"],
    }
    assert pip[("evil-pkg", "MAL-2099-3")]["ranges"] == [{"introduced": "0"}]
    # A GIT range makes osv-scanner read only the versions list, so the rough
    # ECOSYSTEM {"introduced": "0"} beside it is not every version.
    assert pip[("commit-pkg", "PYSEC-2099-4")] == {
        "package": "commit-pkg", "id": "PYSEC-2099-4", "versions": ["3.0"],
    }

    npm = _entries(home, "npm-audit")
    assert set(npm) == {
        ("left-thing", "GHSA-aaaa-bbbb-cccc"), ("listed-thing", "GHSA-dddd-eeee-ffff"),
        ("bad-thing", "MAL-2099-6"),
    }
    assert npm[("left-thing", "GHSA-aaaa-bbbb-cccc")] == {
        "package": "left-thing", "id": "GHSA-aaaa-bbbb-cccc", "aliases": ["CVE-2099-0002"],
        "severity": "moderate", "url": "https://example.invalid/advisory",
        "ranges": [
            {"introduced": "1.0.0", "fixed": "1.4.2"},
            {"introduced": "2.0.0-beta.1", "last_affected": "2.1.0"},
        ],
    }
    assert npm[("listed-thing", "GHSA-dddd-eeee-ffff")]["severity"] == "critical"
    assert "severity" not in npm[("bad-thing", "MAL-2099-6")]

    for name in ("pip-audit", "npm-audit"):
        listed = [(item["package"], item["id"]) for item in _snapshot(home, name)["advisories"]]
        assert listed == sorted(listed)
    assert "pip-audit: wrote" in out and "5 advisories, 4 packages" in out
    assert "npm-audit: wrote" in out
    assert "withdrawn 1, unparseable 2, oversized 0" in out
    assert "withdrawn 1, unparseable 0, oversized 1" in out
    assert "pypi-range-unparseable 1" in out
    assert "pypi-range-not-ecosystem 1" in out
    assert "pypi-range-without-versions" not in out
    assert "npm-range-not-semver 1" in out
    assert "npm-range-unparseable 1" in out
    assert "no-versions-or-ranges 1" in out


def test_offline_advisories_command_writes_private_files_and_metadata_review_setup_reads(
    tmp_path: Path,
) -> None:
    home = _osv_home(tmp_path / "home")
    assert _run_command(home)[0] == 0
    for name in ("pip-audit", "npm-audit"):
        folder = home / ADVISORIES / name
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        for leaf in ("advisories.json", "metadata.json"):
            assert stat.S_IMODE((folder / leaf).stat().st_mode) == 0o600
        assert sorted(path.name for path in folder.iterdir()) == ["advisories.json",
                                                                  "metadata.json"]
    record = T.advisory_snapshot_record(home)
    assert record["pip-audit"]["version"] == "2026-03-04"
    assert record["pip-audit"]["updated_at"] == "2026-03-04T05:06:07Z"
    assert record["npm-audit"]["date"] == "2026-01-02"
    data = (home / ADVISORIES / "npm-audit" / "advisories.json").read_bytes()
    import hashlib

    assert record["npm-audit"]["sha256"] == hashlib.sha256(data).hexdigest()


def test_offline_advisories_command_is_deterministic(tmp_path: Path) -> None:
    first = _osv_home(tmp_path / "first")
    second = _osv_home(tmp_path / "second", reverse=True)
    assert _run_command(first)[0] == 0
    before = {name: (first / ADVISORIES / name / leaf).read_bytes()
              for name in ("pip-audit", "npm-audit") for leaf in ("advisories.json",)}
    assert _run_command(first)[0] == 0
    assert _run_command(second)[0] == 0
    for name in ("pip-audit", "npm-audit"):
        for leaf in ("advisories.json", "metadata.json"):
            again = (first / ADVISORIES / name / leaf).read_bytes()
            other = (second / ADVISORIES / name / leaf).read_bytes()
            if leaf == "advisories.json":
                assert again == before[name]
            if leaf == "metadata.json":
                # The source zip's own hash differs with member order; nothing else may.
                again_meta = json.loads(again)
                other_meta = json.loads(other)
                again_meta.pop("source_sha256")
                other_meta.pop("source_sha256")
                assert again_meta == other_meta
            else:
                assert again == other


def test_offline_advisories_command_names_a_missing_database_and_how_to_download_it(
    tmp_path: Path,
) -> None:
    home = _osv_home(tmp_path / "home", ecosystems=("PyPI",))
    code, out, err = _run_command(home)
    assert code != 0
    assert "pip-audit: wrote" in out
    expected = home / ADVISORIES / "osv-scanner" / "osv-scalibr" / "npm" / "all.zip"
    assert str(expected) in err
    assert "--download-offline-databases" in err
    assert f"OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY={home / ADVISORIES / 'osv-scanner'}" in err
    assert not (home / ADVISORIES / "npm-audit").exists()


def test_offline_advisories_command_reads_the_legacy_osv_folder(tmp_path: Path) -> None:
    home = _osv_home(tmp_path / "home", root=Path(".saga") / "advisories")
    assert _run_command(home)[0] == 0
    assert ("evil-pkg", "MAL-2099-3") in _entries(home, "pip-audit")
    assert not (home / ".saga" / "advisories" / "pip-audit").exists()


def test_offline_advisories_command_reports_an_unreadable_zip_without_a_traceback(
    tmp_path: Path,
) -> None:
    home = _osv_home(tmp_path / "home", ecosystems=("npm",))
    bad = home / ADVISORIES / "osv-scanner" / "osv-scalibr" / "PyPI" / "all.zip"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not a zip")
    code, out, err = _run_command(home)
    assert code != 0
    assert "pip-audit: cannot read" in err
    assert "npm-audit: wrote" in out


@pytest.mark.parametrize("bad", [
    {"affected": [_pkg("PyPI", "typed-pkg", versions=["1.0"]) | {"ranges": 5}]},
    {"affected": [_pkg("PyPI", "typed-pkg", versions=["1.0"]) | {"ranges": True}]},
    {"affected": [_pkg("PyPI", "typed-pkg", versions=["1.0"])], "references": 5},
    {"affected": [_pkg("PyPI", "typed-pkg", versions=["1.0"],
                       ranges=[{"type": "ECOSYSTEM", "events": 7}])]},
    {"affected": [_pkg("PyPI", "typed-pkg", versions=["1.0"],
                       ranges=[_ecosystem({"introduced": 5})])]},
])
def test_offline_advisories_command_survives_wrongly_typed_record_fields(
    tmp_path: Path, bad: dict[str, Any],
) -> None:
    # One malformed record must not stop either snapshot from being written.
    home = _osv_home(tmp_path / "home")
    members = dict(PYPI_RECORDS)
    members["PYSEC-2099-20.json"] = {"id": "PYSEC-2099-20",
                                     "modified": "2026-01-02T03:04:05Z", **bad}
    _write_zip(home / ADVISORIES / "osv-scanner" / "osv-scalibr" / "PyPI" / "all.zip", members)
    code, out, err = _run_command(home)
    assert code == 0, err
    assert "Traceback" not in err
    pip = _entries(home, "pip-audit")
    assert ("evil-pkg", "MAL-2099-3") in pip
    assert pip[("typed-pkg", "PYSEC-2099-20")]["versions"] == ["1.0"]
    assert ("left-thing", "GHSA-aaaa-bbbb-cccc") in _entries(home, "npm-audit")


# --- SemVer 2.0.0 precedence, straight from the specification's examples. ---

SPEC_ORDER = [
    "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
    "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "2.0.0", "2.1.0", "2.1.1",
]


def test_offline_semver_precedence_follows_the_specification_examples() -> None:
    keys = [ADV._semver_key(version) for version in SPEC_ORDER]
    assert all(key is not None for key in keys)
    for lower, higher in zip(keys, keys[1:]):
        assert lower < higher
    assert ADV._semver_key("1.0.0-alpha+001") == ADV._semver_key("1.0.0-alpha")
    assert ADV._semver_key("1.0.0+20130313144700") == ADV._semver_key("1.0.0")
    assert ADV._semver_key("1.0.0-beta+exp.sha.5114f85") == ADV._semver_key("1.0.0-beta")
    assert ADV._semver_key("1.9.0") < ADV._semver_key("1.10.0") < ADV._semver_key("1.11.0")
    assert ADV._semver_key("1.0.0-x-y-z.--") is not None


@pytest.mark.parametrize("version", [
    "1.0", "1", "01.0.0", "1.01.0", "1.0.0-01", "1.0.0-", "1.0.0+", "v1.0.0", "1.0.0-alpha..1",
    "1.0.0+a..b", "1.0.0-al pha", "", "1.0.0-٣", "١.0.0", "1.0.0" + "0" * 300,
])
def test_offline_semver_rejects_what_the_specification_does_not_allow(version: str) -> None:
    assert ADV._semver_key(version) is None


# --- Interval and list matching. ---


def _npm(item: dict[str, Any], version: str) -> bool:
    return ADV._npm_entry_matches(item, version)


@pytest.mark.parametrize(("version", "expected"), [
    ("0.9.9", False),
    ("1.0.0-rc.1", False),  # a pre-release of the introduced version sorts below it
    ("1.0.0", True),  # introduced is inclusive
    ("1.2.0", True),
    ("1.4.2-beta.1", True),  # a pre-release of the fixed version sorts below it
    ("1.4.2", False),  # fixed is exclusive
    ("1.4.2+build.7", False),  # build metadata is ignored
    ("2.0.0-alpha", False),
    ("2.0.0-beta.1", True),
    ("2.1.0", True),  # last_affected is inclusive
    ("2.1.0+build", True),
    ("2.1.1-alpha", False),
    ("2.1.1", False),
    ("not-a-version", False),
    # osv-scanner 2.6.0 reads an installed version with a leading v or a missing part.
    ("1.2", True),
    ("1.4", True),
    ("1", True),  # 1.0.0
    ("2", True),  # 2.0.0, above 2.0.0-beta.1
    ("3", False),
    ("v1.2.0", True),
    ("v1.4.2", False),
    ("v2.1", True),
    ("1.2-beta.1", True),
    ("=1.2.0", False),
    ("V1.2.0", False),
    ("vv1.2.0", False),
    ("01.2.0", False),
])
def test_offline_npm_intervals_match_at_each_bound(version: str, expected: bool) -> None:
    item = {"package": "p", "id": "GHSA-x", "ranges": [
        {"introduced": "1.0.0", "fixed": "1.4.2"},
        {"introduced": "2.0.0-beta.1", "last_affected": "2.1.0"},
    ]}
    assert _npm(item, version) is expected


def test_offline_npm_interval_from_zero_and_without_an_upper_bound() -> None:
    assert _npm({"ranges": [{"introduced": "0", "fixed": "1.0.0"}]}, "0.0.1-alpha")
    assert not _npm({"ranges": [{"introduced": "0", "fixed": "1.0.0"}]}, "1.0.0")
    assert _npm({"ranges": [{"introduced": "3.0.0"}]}, "99.0.0")
    assert not _npm({"ranges": [{"introduced": "3.0.0"}]}, "2.9.9")
    # Every version: even one that is not SemVer, since no comparison is needed.
    assert _npm({"ranges": [{"introduced": "0"}]}, "git+https://example.invalid/x")
    # A bound that is not SemVer never matches.
    assert not _npm({"ranges": [{"introduced": "1.0", "fixed": "2.0"}]}, "1.5.0")


def test_offline_npm_versions_list_and_single_version_match_exact_strings() -> None:
    assert _npm({"versions": ["0.3.1", "0.3.2"]}, "0.3.2")
    assert not _npm({"versions": ["0.3.1", "0.3.2"]}, "0.3.3")
    assert _npm({"version": "4.17.21"}, "4.17.21")
    assert not _npm({"version": "4.17.21"}, "4.17.20")


@pytest.mark.parametrize(("pin", "listed", "expected"), [
    ("1.0.0", "1.0.0", True),
    ("1.0", "1.0.0", True),  # PEP 440 == pads the shorter release with zeros
    ("1.0.0", "1", True),
    ("1.0.0a1", "1.0.0-alpha.1", True),  # PEP 440 spelling and separator normalisation
    ("1.0.0RC1", "1.0.0rc1", True),
    ("v2.0", "2.0", True),
    ("1.0.post1", "1.0-1", True),
    ("2!1.0", "1.0", False),
    ("1.0.1", "1.0.10", False),
    ("1.0+local", "1.0", False),  # a local label matches only exactly
    ("1.0.0a1", "1.0.0", False),
    ("1.0.0.dev1", "1.0.0", False),
    ("not-pep440", "not-pep440", True),  # the same string still matches
])
def test_offline_pip_versions_list_compares_pep440_normal_forms(
    pin: str, listed: str, expected: bool,
) -> None:
    assert ADV._pip_entry_matches({"versions": [listed]}, pin) is expected


def test_offline_pip_single_version_entries_keep_exact_string_matching() -> None:
    assert ADV._pip_entry_matches({"version": "2.31.0"}, "2.31.0")
    assert not ADV._pip_entry_matches({"version": "2.31.0"}, "2.31")
    assert ADV._pip_entry_matches({"ranges": [{"introduced": "0"}]}, "0.0.1")


def test_offline_single_version_written_as_a_json_number_still_matches() -> None:
    # Older snapshots compared str(item["version"]); a number there kept matching.
    assert ADV._pip_entry_matches({"version": 1.0}, "1.0")
    assert not ADV._pip_entry_matches({"version": 1.0}, "1.1")
    assert ADV._npm_entry_matches({"version": 1}, "1")
    assert not ADV._pip_entry_matches({"version": None}, "None")
    assert not ADV._npm_entry_matches({"version": ""}, "")


# PEP 440's own ordering example, lowest first.
PEP440_ORDER = [
    "1.0.dev456", "1.0a1", "1.0a2.dev456", "1.0a12.dev456", "1.0a12", "1.0b1.dev456",
    "1.0b2", "1.0b2.post345.dev456", "1.0b2.post345", "1.0rc1.dev456", "1.0rc1", "1.0",
    "1.0+abc.5", "1.0+abc.7", "1.0+5", "1.0.post456.dev34", "1.0.post456", "1.0.15",
    "1.1.dev1", "2.0", "1!0.1",
]


def test_offline_pep440_order_follows_the_specification_example() -> None:
    keys = [ADV._pep440_key(version) for version in PEP440_ORDER]
    assert all(key is not None for key in keys)
    for lower, higher in zip(keys, keys[1:]):
        assert lower < higher
    assert ADV._pep440_key("1.0") == ADV._pep440_key("1.0.0") == ADV._pep440_key("v1.0.0.0")
    assert ADV._pep440_key("1.0a1") == ADV._pep440_key("1.0-ALPHA.1")
    assert ADV._pep440_key("1.0.post1") == ADV._pep440_key("1.0-1") == ADV._pep440_key("1.0r1")
    assert ADV._pep440_key("1.0rc1") == ADV._pep440_key("1.0c1") == ADV._pep440_key("1.0pre1")
    assert ADV._pep440_key("0") == ADV._pep440_key("0.0")
    for text in ("", "not-pep440", "1.0-NA", "2be7ce80df05", "1.0+", "1..0"):
        assert ADV._pep440_key(text) is None


def test_offline_pep440_order_agrees_with_packaging() -> None:
    packaging_version = pytest.importorskip("packaging.version")
    samples = [
        "0", "0.0.1", "0.1", "0.9.13", "1", "1.0", "1.0.0", "1.0.0.0.1", "1.0.dev0", "1.0a1.dev0",
        "1.0a1", "1.0a1.post1.dev0", "1.0a1.post1", "1.0b1", "1.0rc1", "1.0+abc", "1.0+abc.1",
        "1.0+1", "1.0+1.abc", "1.0+a-b_c.d", "1.0.post0.dev0", "1.0.post0", "1.0.post1", "1!0.1",
        "v1.0", "1.0-1", "1.0_rc_2", "1.0.c1", "1.0preview3", "1.0rev2", "1.0r", "1.0dev",
        "1.0-dev-3", "2.4.0rc0", "2.7.0rc0", "2.7.2", "4.1rc1", "11.2.0", "2012.2", "1.0.0b0",
    ]
    parsed = sorted((packaging_version.Version(text), text) for text in samples)
    for (left, left_text), (right, right_text) in zip(parsed, parsed[1:]):
        ours_left, ours_right = ADV._pep440_key(left_text), ADV._pep440_key(right_text)
        assert ours_left <= ours_right, (left_text, right_text)
        assert (ours_left == ours_right) == (left == right), (left_text, right_text)


@pytest.mark.parametrize(("pin", "expected"), [
    ("1.9.9", False),
    ("2.0a1", False),  # a pre-release of the introduced version sorts below it
    ("2.0", True),  # introduced is inclusive
    ("2.0.0", True),
    ("2.7.0rc0", True),  # a pre-release OSV's versions list leaves out
    ("2.7.1.post1", True),
    ("2.7.2rc1", True),  # a pre-release of the fixed version sorts below it
    ("2.7.2.dev0", True),
    ("2.7.2", False),  # fixed is exclusive
    ("2.7.2.post1", False),
    ("3.0.dev1", False),
    ("3.0", True),
    ("3.0.0", True),  # last_affected is inclusive, and == pads with zeros
    ("3.0.post1", False),
    ("1!2.5", False),  # a later epoch sorts above every bound
    ("2be7ce80df05", False),  # not PEP 440: no ordering is guessed
])
def test_offline_pip_intervals_match_at_each_bound(pin: str, expected: bool) -> None:
    item = {"package": "p", "id": "GHSA-x", "versions": ["2.7.1"], "ranges": [
        {"introduced": "2.0", "fixed": "2.7.2"},
        {"introduced": "3.0.dev2", "last_affected": "3.0"},
    ]}
    assert ADV._pip_entry_matches(item, pin) is expected


def test_offline_pip_interval_from_zero_and_unparseable_bounds() -> None:
    assert ADV._pip_entry_matches({"ranges": [{"introduced": "0", "fixed": "9"}]}, "1.0")
    assert not ADV._pip_entry_matches({"ranges": [{"introduced": "0", "fixed": "9"}]}, "9.0")
    assert ADV._pip_entry_matches({"ranges": [{"introduced": "3"}]}, "99.0")
    assert not ADV._pip_entry_matches({"ranges": [{"introduced": "3"}]}, "2.9")
    # Every version: even a pin that is not PEP 440, since no comparison is needed.
    assert ADV._pip_entry_matches({"ranges": [{"introduced": "0"}]}, "2be7ce80df05")
    # A bound that is not PEP 440 never matches.
    assert not ADV._pip_entry_matches({"ranges": [{"introduced": "0", "fixed": "2.6.0-NA"}]},
                                      "1.0")


def test_offline_pep503_names_compare_the_way_pip_does() -> None:
    assert ADV._pep503_name("Foo_Bar.baz") == "foo-bar-baz"
    assert ADV._pep503_name("foo--__..bar") == "foo-bar"
    assert ADV._pep503_name("FOO") == ADV._pep503_name("foo")
    assert ADV._pep503_name("foo-bar") != ADV._pep503_name("foobar")


# --- The evaluators the adapters write to disk. ---


def _pip_evaluate(tmp_path: Path, entries: list[dict[str, Any]], *texts: str) -> set[tuple]:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "advisories.json").write_text(json.dumps({"advisories": entries}),
                                              encoding="utf-8")
    script = tmp_path / "audit.py"
    script.write_text(PY._PIP_AUDIT_OFFLINE, encoding="utf-8")
    files = []
    for index, text in enumerate(texts):
        path = tmp_path / f"requirements-{index}.txt"
        path.write_text(text, encoding="utf-8")
        files.append(str(path))
    completed = subprocess.run([sys.executable, "-I", str(script), str(snapshot), *files],
                               check=True, capture_output=True, text=True, cwd=tmp_path)
    return {
        (dep["name"], dep["version"], vuln["id"])
        for dep in json.loads(completed.stdout)["dependencies"] for vuln in dep["vulns"]
    }


def test_offline_pip_evaluator_matches_lists_pep503_names_and_every_pinned_file(
    tmp_path: Path,
) -> None:
    entries = [
        {"package": "example-pkg", "id": "PYSEC-2099-1", "versions": ["1.0.0", "1.1.0"]},
        {"package": "evil-pkg", "id": "MAL-2099-3", "ranges": [{"introduced": "0"}]},
        {"package": "Old.Style", "version": "3.1", "id": "PYSEC-2099-7"},
        {"package": "example-pkg", "id": "PYSEC-2099-8", "ranges": [
            {"introduced": "0", "fixed": "2.0"}]},
    ]
    found = _pip_evaluate(
        tmp_path, entries,
        "Example_Pkg==1.0\nevil.pkg==4.2\nold-style==3.1\n",
        "example-pkg==1.2.0\n",
    )
    assert found == {
        ("Example_Pkg", "1.0", "PYSEC-2099-1"),
        ("evil.pkg", "4.2", "MAL-2099-3"),
        ("old-style", "3.1", "PYSEC-2099-7"),
        ("Example_Pkg", "1.0", "PYSEC-2099-8"),
        ("example-pkg", "1.2.0", "PYSEC-2099-8"),
    }


def test_offline_pip_evaluator_honours_ranges_beyond_the_versions_list(tmp_path: Path) -> None:
    # GHSA-2475-53vw-vp25's versions list leaves out tensorflow-cpu 2.7.0rc0, a published
    # version inside its range; osv-scanner reports it and so must the evaluator.
    entries = [
        {"package": "tensorflow-cpu", "id": "GHSA-2475-53vw-vp25", "versions": ["2.6.0", "2.7.0"],
         "ranges": [{"introduced": "0", "fixed": "2.7.2"}]},
        {"package": "plone", "id": "PYSEC-2099-9", "ranges": [
            {"introduced": "4.0", "last_affected": "4.1"}]},
        {"package": "num-pkg", "id": "PYSEC-2099-10", "version": 1.0},
    ]
    found = _pip_evaluate(
        tmp_path, entries,
        "tensorflow-cpu==2.7.0rc0\nplone==4.1rc1\nnum-pkg==1.0\n",
        "tensorflow-cpu==2.7.2\nplone==4.1.post1\n",
    )
    assert found == {
        ("tensorflow-cpu", "2.7.0rc0", "GHSA-2475-53vw-vp25"),
        ("plone", "4.1rc1", "PYSEC-2099-9"),
        ("num-pkg", "1.0", "PYSEC-2099-10"),
    }


def _npm_evaluate(tmp_path: Path, entries: list[dict[str, Any]],
                  packages: dict[str, Any]) -> dict[str, Any]:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "advisories.json").write_text(json.dumps({"advisories": entries}),
                                              encoding="utf-8")
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"lockfileVersion": 3, "packages": packages}), encoding="utf-8")
    script = tmp_path / "audit.py"
    script.write_text(TS._NPM_AUDIT_OFFLINE, encoding="utf-8")
    completed = subprocess.run([sys.executable, "-I", str(script), str(snapshot), str(lock)],
                               check=True, capture_output=True, text=True, cwd=tmp_path)
    return json.loads(completed.stdout)


def test_offline_npm_evaluator_reports_every_advisory_and_installed_copy(tmp_path: Path) -> None:
    entries = [
        {"package": "left-thing", "id": "GHSA-aaaa-bbbb-cccc", "severity": "moderate",
         "aliases": ["CVE-2099-0002"], "ranges": [{"introduced": "1.0.0", "fixed": "1.4.2"}]},
        {"package": "left-thing", "id": "MAL-2099-9", "ranges": [{"introduced": "0"}]},
        {"package": "listed-thing", "id": "GHSA-dddd-eeee-ffff", "severity": "low",
         "versions": ["0.3.1"]},
        {"package": "demo", "id": "MAL-2099-10", "ranges": [{"introduced": "0"}]},
    ]
    output = _npm_evaluate(tmp_path, entries, {
        "": {"name": "demo", "version": "1.0.0"},
        "node_modules/left-thing": {"version": "1.4.2"},
        "node_modules/a/node_modules/left-thing": {"version": "1.3.0"},
        "node_modules/listed-thing": {"version": "0.3.2"},
        "node_modules/odd-thing": {"version": "file:../odd"},
    })
    found = output["vulnerabilities"]
    assert set(found) == {"left-thing"}
    left = found["left-thing"]
    assert left["severity"] == "high"  # an unrated advisory counts as high
    assert [(via["id"], via["versions"]) for via in left["via"]] == [
        ("GHSA-aaaa-bbbb-cccc", ["1.3.0"]),
        ("MAL-2099-9", ["1.3.0", "1.4.2"]),
    ]
    hits = TS._parse_npm_audit(json.dumps(output)).hits
    assert len(hits) == 1
    # The OSV id keeps its own spelling, so the same advisory from osv-scanner merges.
    assert hits[0].advisory_ids == ("GHSA-aaaa-bbbb-cccc", "CVE-2099-0002", "MAL-2099-9")
    assert hits[0].row == "security.dependency-high"


def test_offline_npm_evaluator_keeps_single_version_entries_working(tmp_path: Path) -> None:
    output = _npm_evaluate(
        tmp_path,
        [{"package": "lodash", "version": "4.17.21", "id": "GHSA-0000-0000-0000",
          "severity": "moderate"}],
        {"node_modules/lodash": {"version": "4.17.21"}},
    )
    hits = TS._parse_npm_audit(json.dumps(output)).hits
    assert [hit.rule_id for hit in hits] == ["GHSA-0000-0000-0000"]
    assert hits[0].row == "security.dependency-medium-low"


# --- End to end: a repository scan reads a snapshot the command built. ---


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_offline_repository_scan_reports_a_vulnerable_pin_from_a_built_snapshot(
    tmp_path: Path,
) -> None:
    home = _osv_home(tmp_path / "home")
    assert _run_command(home)[0] == 0
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "advisories@example.com")
    _git(repo, "config", "user.name", "advisories")
    (repo / "requirements.txt").write_text("example-pkg==1.1.0\nclean-pkg==1.0.0\n",
                                           encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0",
                    "dependencies": {"left-thing": "1.4.1", "listed-thing": "0.3.3"}}),
        encoding="utf-8",
    )
    (repo / "package-lock.json").write_text(json.dumps({
        "name": "demo", "version": "1.0.0", "lockfileVersion": 3,
        "packages": {
            "": {"name": "demo", "version": "1.0.0"},
            "node_modules/left-thing": {"version": "1.4.1"},
            "node_modules/listed-thing": {"version": "0.3.3"},
        },
    }), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "pins")
    output = tmp_path / "scan-out"
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "security_scan.py"), "--repo", str(repo),
         "--output", str(output)],
        capture_output=True, text=True, check=False, timeout=300,
        env={**os.environ, "HOME": str(home)},
    )
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in summary["rows"]}
    for name in ("pip-audit", "npm-audit"):
        assert rows[name]["status"] == "ran", (rows[name], completed.stderr)
    assert rows["pip-audit"]["counts"]["blocks"] == 1
    assert rows["npm-audit"]["counts"]["fix-later"] == 1
    findings = (output / "findings.json").read_text(encoding="utf-8")
    assert "PYSEC-2099-1" in findings
    assert "GHSA-aaaa-bbbb-cccc" in findings
    assert "GHSA-dddd-eeee-ffff" not in findings
    assert "clean-pkg" not in findings


def test_offline_version_readers_finish_quickly_on_hostile_input() -> None:
    # Lock and requirements files come from the scanned repository, which is not trusted.
    import time

    started = time.perf_counter()
    assert ADV._pep440_canonical("1." * 200_000 + "x") is None
    assert ADV._pep440_canonical("1" + "-" * 100 + "a") is None
    assert ADV._semver_key("1.0.0-" + "a." * 200_000) is None
    assert ADV._semver_installed_key("v" + "1." * 200_000) is None
    assert ADV._pep440_key("1." * 200_000 + "x") is None
    assert ADV._pep503_name("a" + "-_." * 200_000 + "b") == "a-b"
    assert time.perf_counter() - started < 2.0
