"""Tests for synchronizing the portable UniFi package from a pinned upstream revision.

Written as unittest against temporary directories, matching
``tests/test_bundle_fleet_module.py``, so the repository's dependency-free
baseline job runs them. Two kinds of test live here.

Fixture tests build a small synthetic upstream git checkout and synchronize from
it, which is how the classification rules, the refusals, and the idempotence
guarantee are exercised without depending on any particular clone being present.

Shipped-tree tests assert against the package this repository actually carries:
its manifest, its skill frontmatter, and its clients' command surface. The
parser-to-parser comparison against the upstream client runs wherever a Claude
checkout is reachable and is skipped elsewhere; the byte-identity that makes the
comparison redundant is verified unconditionally by ``check_repo.py`` against
the provenance manifest.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import sync_vendor_source as svs  # noqa: E402


# The corrected upstream revision this pilot synchronizes from. Requirement R3
# forbids pinning 995a475b, the revision before the documentation repair and the
# topology relocation landed, because synchronizing from it would re-import the
# defects that repair removed. The constant is pinned here on purpose: moving
# the pin is a deliberate act that has to change a test, not a silent drift.
#
# It moved once, from 0eb1fe04 to its immediate child, when Fleet Core 0.25.1
# repaired RFC 7231 `Retry-After` HTTP-date handling in the shared backoff
# primitive. The upstream `plugins/unifi` subtree is byte-identical across that
# step, so re-synchronizing changed no UniFi byte; the pin moved so that one
# revision names the corrected state of the whole port rather than two.
CORRECTED_REVISION = "ed72f439ba01f2e20d94be074e5612c5641c0c8e"
FORBIDDEN_REVISION_PREFIX = "995a475b"

#: A client actually reaching for the dropped shim, as opposed to a comment
#: naming the shim the rewrite replaced. The rewritten block keeps that comment
#: on purpose: it is the sentence that stops a later reader putting the import
#: back, so the guard has to match code rather than the whole file.
SHIM_USE = re.compile(r"^[ \t]*(?:import|from)[ \t]+fleet_commons_shim\b|fleet_commons_shim[ \t]*\.", re.MULTILINE)

NETWORK_RESOURCE_GROUPS = 12
NETWORK_ACTIONS = 52
PROTECT_RESOURCE_GROUPS = 6
PROTECT_ACTIONS = 21


# --- synthetic upstream checkout ----------------------------------------------


FIXTURE_MANIFEST = json.dumps({"name": "unifi", "version": "9.9.9"}, indent=2) + "\n"

# The upstream module-scope block both clients carry at the pinned commit. The
# fixture reproduces it verbatim because it is the input the
# `resolve-bundled-fleet-module` transform is defined over: a fixture client
# without it would exercise the classification bookkeeping and none of the
# rewrite that gives the portable package a working entrypoint.
FIXTURE_SHIM_BLOCK = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "# Shared 429 retry/backoff primitive via fleet-commons (#348).\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
    "import fleet_commons_shim  # noqa: E402  (after the sys.path shim, by design)\n"
    "\n"
    '_retry_backoff = fleet_commons_shim.load("retry_backoff")\n'
)

FIXTURE_NETWORK_CLIENT = FIXTURE_SHIM_BLOCK + "NETWORK = 1\n"
FIXTURE_PROTECT_CLIENT = FIXTURE_SHIM_BLOCK + "PROTECT = 1\n"

FIXTURE_SOURCE: dict[str, str] = {
    ".claude-plugin/plugin.json": FIXTURE_MANIFEST,
    "README.md": "# fixture readme\n",
    "CHANGELOG.md": "# fixture changelog\n",
    "commands/unifi.md": "fixture command\n",
    "agents/unifi-network-ops.md": "fixture agent\n",
    "skills/unifi-network/SKILL.md": "---\nname: unifi-network\ndescription: fixture\n---\n",
    "skills/unifi-network/references/udm-api-endpoints.md": "fixture network reference\n",
    "skills/unifi-network/scripts/unifi_network_client.py": FIXTURE_NETWORK_CLIENT,
    "skills/unifi-network/scripts/site_profile_loader.py": "LOADER = 1\n",
    "skills/unifi-network/scripts/fleet_commons_shim.py": "SHIM = 1\n",
    "skills/unifi-protect/SKILL.md": "---\nname: unifi-protect\ndescription: fixture\n---\n",
    "skills/unifi-protect/references/protect-api-endpoints.md": "fixture protect reference\n",
    "skills/unifi-protect/scripts/unifi_protect_client.py": FIXTURE_PROTECT_CLIENT,
    "skills/unifi-protect/scripts/fleet_commons_shim.py": "SHIM = 1\n",
}


#: A stand-in for the site-neutral README this repository authors for the
#: portable package. Its only requirement is that it is not the upstream text:
#: every assertion below is that synchronization leaves these bytes alone.
PORTABLE_README = (
    "# portable fixture readme\n"
    "\n"
    "Describes the portable package, not the source plugin.\n"
)


def git(source: Path, *arguments: str) -> str:
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *arguments,
        ],
        capture_output=True,
        check=True,
        env=environment,
    )
    return completed.stdout.decode("utf-8")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def bundle_beside(client: Path, module: str = "retry_backoff") -> str:
    """The package-relative bundle path a rewritten client resolves."""
    return (client.parent / svs.BUNDLE_DIRECTORY_NAME / f"{module}.py").as_posix()


def make_source_checkout(directory: Path, files: dict[str, str] | None = None) -> str:
    """Create a synthetic upstream checkout and return the commit that holds it."""
    directory.mkdir(parents=True, exist_ok=True)
    git(directory, "init", "--quiet")
    for relative, body in (files or FIXTURE_SOURCE).items():
        write(directory / svs.SOURCE_PACKAGE_PATH / relative, body)
    git(directory, "add", "--all")
    git(directory, "commit", "--quiet", "--message", "fixture upstream package")
    return git(directory, "rev-parse", "HEAD").strip()


def tree_snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): check_repo.sha256_path(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class SyncFixture(unittest.TestCase):
    """A synthetic upstream checkout plus an empty target repository root."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        base = Path(self._temporary.name)
        self.source = base / "upstream"
        self.target = base / "target"
        (self.target / "plugins" / svs.TARGET_PACKAGE).mkdir(parents=True)
        self.commit = make_source_checkout(self.source)

    @property
    def package(self) -> Path:
        return self.target / "plugins" / svs.TARGET_PACKAGE

    def synchronize(self, **keywords: object) -> tuple[list[str], str]:
        return svs.synchronize(self.source, self.commit, root=self.target, **keywords)


# --- classification, digests, and idempotence ---------------------------------


class SynchronizedTreeTests(SyncFixture):
    def test_written_tree_matches_the_manifest_digest_for_digest(self) -> None:
        self.synchronize()
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        recorded = 0
        for entry in manifest["files"]:
            target = self.package / entry["path"]
            self.assertTrue(target.is_file(), f"manifest names a missing file: {entry['path']}")
            if entry["classification"] == check_repo.TARGET_OWNED:
                self.assertNotIn("sha256", entry)
                continue
            recorded += 1
            self.assertEqual(check_repo.sha256_path(target), entry["sha256"], entry["path"])
        self.assertEqual(
            recorded,
            len(svs.PORTABLE_BYTE_COPIES)
            + len(svs.PORTABLE_ENTRYPOINT_TRANSFORMS)
            + len(svs.CLIENT_BYTE_COPIES)
            + 1,
        )
        self.assertEqual(check_repo.check_provenance_manifests(self.target), [])

    def test_every_path_carries_exactly_one_classification(self) -> None:
        self.synchronize()
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        paths = [entry["path"] for entry in manifest["files"]]
        self.assertEqual(len(paths), len(set(paths)), "a path appears in more than one entry")
        for entry in manifest["files"]:
            self.assertIn(entry["classification"], check_repo.PATH_CLASSIFICATIONS)
        present = {
            str(path.relative_to(self.package).as_posix())
            for path in self.package.rglob("*")
            if path.is_file() and path.name != "PROVENANCE.json"
        }
        self.assertEqual(
            set(paths), present, "the manifest and the tree disagree on which paths exist"
        )

    def test_every_transform_records_source_output_rule_and_version(self) -> None:
        self.synchronize()
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        transforms = {
            entry["path"]: entry
            for entry in manifest["files"]
            if entry["classification"] == check_repo.TRANSFORM
        }
        self.assertEqual(
            sorted(transforms),
            sorted([f"{svs.CLIENT_EXTENSION_DIR}/plugin.json", *svs.PORTABLE_ENTRYPOINT_TRANSFORMS]),
        )
        for path, entry in transforms.items():
            with self.subTest(path=path):
                for field in ("source_sha256", "sha256"):
                    self.assertRegex(entry[field], r"^[0-9a-f]{64}$")
                self.assertTrue(entry["transform_rule"].strip())
                self.assertTrue(entry["transform_version"].strip())

        manifest_entry = transforms[f"{svs.CLIENT_EXTENSION_DIR}/plugin.json"]
        self.assertEqual(
            manifest_entry["source_path"], "plugins/unifi/.claude-plugin/plugin.json"
        )
        self.assertEqual(manifest_entry["transform"], svs.MANIFEST_TRANSFORM_NAME)
        self.assertEqual(manifest_entry["transform_version"], svs.MANIFEST_TRANSFORM_VERSION)

        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            entry = transforms[relative]
            self.assertEqual(entry["transform"], svs.BUNDLED_TRANSFORM_NAME)
            self.assertEqual(entry["transform_version"], svs.BUNDLED_TRANSFORM_VERSION)
            self.assertNotEqual(
                entry["source_sha256"],
                entry["sha256"],
                "the rewrite changed no byte, so the client still imports the dropped shim",
            )

    def test_rerunning_against_the_same_commit_changes_nothing(self) -> None:
        self.synchronize()
        before = tree_snapshot(self.package)
        written, _ = self.synchronize()
        self.assertEqual(written, [])
        self.assertEqual(tree_snapshot(self.package), before)
        errors, _ = self.synchronize(check_only=True)
        self.assertEqual(errors, [])

    def test_neither_fleet_commons_shim_appears_in_the_output(self) -> None:
        self.synchronize()
        self.assertIn(
            "skills/unifi-network/scripts/fleet_commons_shim.py", svs.DROPPED_FROM_SOURCE
        )
        self.assertIn(
            "skills/unifi-protect/scripts/fleet_commons_shim.py", svs.DROPPED_FROM_SOURCE
        )
        found = [str(path) for path in self.package.rglob("fleet_commons_shim.py")]
        self.assertEqual(found, [])
        manifest = (self.package / "PROVENANCE.json").read_text(encoding="utf-8")
        self.assertNotIn('"path": "skills/unifi-network/scripts/fleet_commons_shim.py"', manifest)

    def test_claude_manifest_lands_under_the_client_extension_directory(self) -> None:
        self.synchronize()
        relocated = self.package / svs.CLIENT_EXTENSION_DIR / "plugin.json"
        self.assertTrue(relocated.is_file())
        self.assertEqual(relocated.read_text(encoding="utf-8"), FIXTURE_MANIFEST)
        self.assertFalse((self.package / ".claude-plugin").exists())
        # The plugin root belongs to the portable Agent Plugins manifest, and
        # synchronization never writes it, so nothing collides there.
        self.assertFalse((self.package / "plugin.json").exists())

    def test_each_client_resolves_the_bundled_module_instead_of_the_dropped_shim(self) -> None:
        """The defect this transform exists to close.

        The package drops ``fleet_commons_shim`` but the upstream clients import
        it at module scope, so a byte copy of either one raises
        ``ModuleNotFoundError`` before it parses a single argument. After the
        rewrite each client resolves the generated Fleet Core bundle the package
        itself ships.
        """
        self.synchronize()
        expected = (
            "sys.path.insert(0, str(Path(__file__).resolve().parent / "
            f'"{svs.BUNDLE_DIRECTORY_NAME}"))'
        )
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                body = (self.package / relative).read_text(encoding="utf-8")
                self.assertIsNone(SHIM_USE.search(body))
                self.assertIn("import retry_backoff as _retry_backoff", body)
                self.assertIn(expected, body)

    def test_resynchronizing_re_applies_the_rule_rather_than_restoring_the_shim(self) -> None:
        """A later synchronization must not silently put the broken import back."""
        self.synchronize()
        relative = svs.PORTABLE_ENTRYPOINT_TRANSFORMS[0]
        client = self.package / relative
        transformed = client.read_text(encoding="utf-8")

        client.write_text(FIXTURE_NETWORK_CLIENT, encoding="utf-8")
        errors, _ = self.synchronize(check_only=True)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("does not match its planned output", errors[0])
        self.assertIn(relative, errors[0])

        written, _ = self.synchronize()
        self.assertIn(relative, written)
        self.assertEqual(client.read_text(encoding="utf-8"), transformed)
        self.assertIsNone(SHIM_USE.search(client.read_text(encoding="utf-8")))

    def test_client_custody_files_keep_their_upstream_relative_path(self) -> None:
        self.synchronize()
        for relative in svs.CLIENT_BYTE_COPIES:
            self.assertTrue(
                (self.package / svs.CLIENT_EXTENSION_DIR / relative).is_file(),
                f"client-custody file missing: {relative}",
            )


# --- refusals ------------------------------------------------------------------


class RefusalTests(SyncFixture):
    def test_a_dirty_checkout_is_refused(self) -> None:
        # The witness is a path synchronization actually writes. README.md is
        # target-owned and is never written, so its absence would prove nothing.
        dirtied = self.source / svs.SOURCE_PACKAGE_PATH / "CHANGELOG.md"
        dirtied.write_text("# edited after the commit\n", encoding="utf-8")
        with self.assertRaises(svs.SyncError) as caught:
            self.synchronize()
        self.assertIn("dirty checkout", str(caught.exception))
        self.assertFalse((self.package / "CHANGELOG.md").exists())

    def test_an_untracked_file_is_not_a_dirty_checkout(self) -> None:
        write(self.source / "scratch.txt", "not tracked\n")
        written, _ = self.synchronize()
        self.assertIn("CHANGELOG.md", written)

    def test_an_unclassified_upstream_path_is_refused(self) -> None:
        write(self.source / svs.SOURCE_PACKAGE_PATH / "hooks" / "hooks.json", "{}\n")
        git(self.source, "add", "--all")
        git(self.source, "commit", "--quiet", "--message", "add an unclassified path")
        self.commit = git(self.source, "rev-parse", "HEAD").strip()
        with self.assertRaises(svs.SyncError) as caught:
            self.synchronize()
        message = str(caught.exception)
        self.assertIn("no custody assignment", message)
        self.assertIn("plugins/unifi/hooks/hooks.json", message)

    def test_a_client_without_the_rewritable_block_is_refused(self) -> None:
        """A rule that cannot find its input fails loudly instead of shipping a stub.

        Silently leaving the client alone is the failure mode that produced the
        defect in the first place: the package looked synchronized and had no
        working entrypoint.
        """
        source = dict(FIXTURE_SOURCE)
        source["skills/unifi-network/scripts/unifi_network_client.py"] = "NETWORK = 1\n"
        base = Path(self._temporary.name) / "upstream-without-shim"
        commit = make_source_checkout(base, source)
        with self.assertRaises(svs.SyncError) as caught:
            svs.synchronize(base, commit, root=self.target)
        message = str(caught.exception)
        self.assertIn("skills/unifi-network/scripts/unifi_network_client.py", message)
        self.assertIn("found 0", message)
        self.assertFalse(
            (self.package / "CHANGELOG.md").exists(), "the plan wrote before it failed"
        )

    def test_a_client_with_the_block_twice_is_refused(self) -> None:
        source = dict(FIXTURE_SOURCE)
        source["skills/unifi-network/scripts/unifi_network_client.py"] = (
            FIXTURE_NETWORK_CLIENT + "\n" + FIXTURE_SHIM_BLOCK
        )
        base = Path(self._temporary.name) / "upstream-twice"
        commit = make_source_checkout(base, source)
        with self.assertRaises(svs.SyncError) as caught:
            svs.synchronize(base, commit, root=self.target)
        self.assertIn("found 2", str(caught.exception))

    def test_a_missing_commit_is_refused(self) -> None:
        with self.assertRaises(svs.SyncError):
            svs.synchronize(self.source, "0" * 40, root=self.target)

    def test_a_byte_copy_that_differs_from_its_source_fails_and_is_never_a_transform(self) -> None:
        self.synchronize()
        relative = "skills/unifi-network/SKILL.md"
        document = self.package / relative
        document.write_text("# edited downstream\n", encoding="utf-8")
        errors, _ = self.synchronize(check_only=True)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("byte copy diverged from its source", errors[0])
        self.assertIn(relative, errors[0])
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        entry = next(item for item in manifest["files"] if item["path"] == relative)
        self.assertEqual(entry["classification"], check_repo.BYTE_COPY)
        # A byte copy is repaired by re-copying from the source, never by
        # recording the downstream edit as a derivation.
        written, _ = self.synchronize()
        self.assertIn(relative, written)
        self.assertEqual(
            document.read_text(encoding="utf-8"),
            FIXTURE_SOURCE[relative],
        )

    def test_check_mode_writes_nothing(self) -> None:
        self.synchronize()
        before = tree_snapshot(self.package)
        (self.package / "CHANGELOG.md").write_text("# edited\n", encoding="utf-8")
        errors, _ = self.synchronize(check_only=True)
        self.assertTrue(errors)
        after = tree_snapshot(self.package)
        after["CHANGELOG.md"] = before["CHANGELOG.md"]
        self.assertEqual(after, before)


# --- target-owned portable source ---------------------------------------------


class TargetOwnedTests(SyncFixture):
    def test_target_owned_files_are_never_overwritten_or_removed(self) -> None:
        owned = {
            "plugin.json": '{"name": "unifi"}\n',
            "fleet-bundle.json": '{"schema_version": "1"}\n',
            "scripts/site_profile.py": "PROFILE = 1\n",
            "scripts/discover.py": "DISCOVER = 1\n",
            "references/site-profile.md": "# profile reference\n",
            "skills/unifi-network/scripts/_bundled/retry_backoff.py": "BUNDLED = 1\n",
        }
        for relative, body in owned.items():
            write(self.package / relative, body)
        before = {relative: check_repo.sha256_text(body) for relative, body in owned.items()}

        self.synchronize()

        for relative, digest in before.items():
            target = self.package / relative
            self.assertTrue(target.is_file(), f"synchronization removed target-owned {relative}")
            self.assertEqual(
                check_repo.sha256_path(target), digest, f"synchronization overwrote {relative}"
            )

        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        recorded = {
            entry["path"]
            for entry in manifest["files"]
            if entry["classification"] == check_repo.TARGET_OWNED
        }
        self.assertEqual(recorded, set(owned))

    def test_a_synchronization_leaves_the_portable_readme_untouched(self) -> None:
        """The portable README is target-owned, so a resync must not restore upstream bytes.

        `plugins/unifi/README.md` documents this package; the upstream README
        documents the Claude Code plugin. While `README.md` sat in
        `PORTABLE_BYTE_COPIES` the next `synchronize()` would have copied the
        upstream text over the portable file, contradicting both the manifest
        classification and the recorded custody decision.
        """
        portable = write(self.package / "README.md", PORTABLE_README)
        self.assertNotEqual(
            PORTABLE_README,
            FIXTURE_SOURCE["README.md"],
            "the fixture cannot detect an overwrite it would not change",
        )

        written, _ = self.synchronize()

        self.assertNotIn("README.md", written, "synchronization wrote a target-owned path")
        self.assertEqual(
            portable.read_text(encoding="utf-8"),
            PORTABLE_README,
            "synchronization overwrote the portable README with upstream bytes",
        )

        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        entry = next(item for item in manifest["files"] if item["path"] == "README.md")
        self.assertEqual(entry["classification"], check_repo.TARGET_OWNED)
        self.assertNotIn("sha256", entry)
        self.assertNotIn("source_path", entry)

        errors, _ = self.synchronize(check_only=True)
        self.assertEqual(errors, [], "check mode disagrees with the tree the write path produced")

    def test_a_manifest_from_before_the_custody_change_does_not_delete_the_readme(self) -> None:
        """The hazard the custody change introduces, and the guard that closes it.

        A tree synchronized before `README.md` became target-owned still carries
        a manifest recording it as an upstream byte copy. Stale cleanup deletes
        every managed path the current plan no longer produces, so without the
        superseded set being subtracted from that stale set, the first run after
        the change unlinks the portable README instead of preserving it.
        """
        portable = write(self.package / "README.md", PORTABLE_README)
        self.synchronize()

        manifest_path = self.package / "PROVENANCE.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = [
            entry for entry in manifest["files"] if entry["path"] != "README.md"
        ]
        manifest["files"].append(
            {
                "path": "README.md",
                "classification": check_repo.BYTE_COPY,
                "source_path": f"{svs.SOURCE_PACKAGE_PATH}/README.md",
                "sha256": check_repo.sha256_text(FIXTURE_SOURCE["README.md"]),
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        self.synchronize()

        self.assertTrue(portable.is_file(), "stale cleanup deleted the portable README")
        self.assertEqual(portable.read_text(encoding="utf-8"), PORTABLE_README)

        errors, _ = self.synchronize(check_only=True)
        self.assertEqual(
            [error for error in errors if "README.md" in error],
            [],
            "check mode reports the target-owned README as a stale synchronized file",
        )

    def test_the_superseded_readme_is_classified_rather_than_dropped(self) -> None:
        """Removing a path from the byte-copy table must not make it unclassified.

        `classify_source_tree` refuses an upstream path no rule names, because a
        dropped path is how a derived tree quietly stops being a copy of
        anything. The superseded set is what keeps that refusal honest after the
        custody change.
        """
        self.assertNotIn("README.md", svs.PORTABLE_BYTE_COPIES)
        self.assertIn("README.md", svs.SUPERSEDED_BY_TARGET_OWNED)
        svs.classify_source_tree(sorted(FIXTURE_SOURCE))

        without_supersession = tuple(
            name for name in svs.SUPERSEDED_BY_TARGET_OWNED if name != "README.md"
        )
        with unittest.mock.patch.object(
            svs, "SUPERSEDED_BY_TARGET_OWNED", without_supersession
        ):
            with self.assertRaises(svs.SyncError) as caught:
                svs.classify_source_tree(sorted(FIXTURE_SOURCE))
        self.assertIn("no custody assignment", str(caught.exception))
        self.assertIn("plugins/unifi/README.md", str(caught.exception))

    def test_a_stale_synchronized_path_is_removed_but_target_owned_source_is_not(self) -> None:
        self.synchronize()
        orphan = self.package / "skills" / "unifi-network" / "scripts" / "retired_client.py"
        write(orphan, "RETIRED = 1\n")
        manifest_path = self.package / "PROVENANCE.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append(
            {
                "path": "skills/unifi-network/scripts/retired_client.py",
                "classification": check_repo.BYTE_COPY,
                "source_path": "plugins/unifi/skills/unifi-network/scripts/retired_client.py",
                "sha256": check_repo.sha256_text("RETIRED = 1\n"),
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        owned = write(self.package / "scripts" / "drift.py", "DRIFT = 1\n")

        self.synchronize()

        self.assertFalse(orphan.exists(), "a stale synchronized path survived")
        self.assertTrue(owned.is_file(), "target-owned source was removed")


# --- a hostile provenance manifest ---------------------------------------------


class ManifestPathSafetyTests(SyncFixture):
    """`PROVENANCE.json` is untrusted input, and stale cleanup unlinks what it names.

    A manifest arrives on disk from an earlier run, a merge, a patch, or an
    attacker with write access to the tree, and synchronization deletes every
    managed path it records that the current plan no longer produces. Without a
    containment check, `plugin_dir / "/etc/hosts"` is `/etc/hosts` and
    `../../..` climbs out, so the cleanup step deletes any user-writable file
    the manifest names. Each test below plants a victim file outside the package
    and proves that the victim survives, that synchronization refuses, and that
    nothing was written before the refusal.
    """

    def plant_victim(self, name: str) -> Path:
        """A file outside the package that no synchronization may ever touch."""
        return write(Path(self._temporary.name) / "outside" / name, "DO NOT DELETE\n")

    def record_managed_path(self, path_value: str) -> None:
        """Add one managed entry to the manifest on disk, as a hostile writer would."""
        manifest_path = self.package / "PROVENANCE.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append(
            {
                "path": path_value,
                "classification": check_repo.BYTE_COPY,
                "source_path": f"{svs.SOURCE_PACKAGE_PATH}/retired.py",
                "sha256": check_repo.sha256_text("DO NOT DELETE\n"),
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def assert_refused(self, victim: Path) -> str:
        """Both commands refuse, the victim survives, and no byte was written first."""
        # A managed file removed from the tree is the write the run would make
        # first. It must still be missing afterwards: the refusal has to land
        # before any write, not part-way through one.
        rewritten = self.package / "CHANGELOG.md"
        rewritten.unlink()

        with self.assertRaises(svs.SyncError) as caught:
            self.synchronize()
        self.assertTrue(victim.is_file(), "synchronization deleted a file outside the package")
        self.assertFalse(rewritten.exists(), "the refusal landed after a write, not before one")

        with self.assertRaises(svs.SyncError):
            self.synchronize(check_only=True)
        self.assertTrue(victim.is_file(), "check mode deleted a file outside the package")
        return str(caught.exception)

    def test_an_absolute_managed_path_is_refused_and_deletes_nothing(self) -> None:
        self.synchronize()
        victim = self.plant_victim("absolute-victim.txt")
        self.record_managed_path(str(victim))
        message = self.assert_refused(victim)
        self.assertIn("unsafe managed path", message)
        self.assertIn(str(victim), message)

    def test_a_traversing_managed_path_is_refused_and_deletes_nothing(self) -> None:
        self.synchronize()
        victim = self.plant_victim("traversal-victim.txt")
        traversal = "../../../outside/traversal-victim.txt"
        self.assertEqual((self.package / traversal).resolve(), victim.resolve())
        self.record_managed_path(traversal)
        message = self.assert_refused(victim)
        self.assertIn("unsafe managed path", message)
        self.assertIn(traversal, message)

    def test_a_symlinked_managed_path_is_refused_and_deletes_nothing(self) -> None:
        """The escape a lexical check cannot see: no `..`, no leading slash, still outside."""
        self.synchronize()
        victim = self.plant_victim("symlink-victim.txt")
        link = self.package / "skills" / "escape"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(victim.parent, target_is_directory=True)
        escaping = "skills/escape/symlink-victim.txt"
        self.assertFalse(Path(escaping).is_absolute())
        self.assertNotIn("..", Path(escaping).parts)
        self.record_managed_path(escaping)
        message = self.assert_refused(victim)
        self.assertIn("resolves outside the package", message)
        self.assertIn(escaping, message)

    def test_the_package_directory_itself_is_not_a_managed_path(self) -> None:
        """`.` resolves to the package root, which is a directory no cleanup may name."""
        self.synchronize()
        with self.assertRaises(svs.SyncError) as caught:
            svs.resolve_managed_path(self.package, ".")
        self.assertIn("resolves outside the package", str(caught.exception))
        self.assertTrue(self.package.is_dir())

    def test_a_blank_managed_path_is_refused(self) -> None:
        for value in ("", "   ", None, 7):
            with self.subTest(value=value):
                with self.assertRaises(svs.SyncError):
                    svs.resolve_managed_path(self.package, value)  # type: ignore[arg-type]

    def test_an_ordinary_package_relative_path_still_resolves(self) -> None:
        """The guard refuses escapes without narrowing what synchronization may write."""
        self.assertEqual(
            svs.resolve_managed_path(self.package, "skills/unifi-network/SKILL.md"),
            self.package / "skills" / "unifi-network" / "SKILL.md",
        )


# --- the shipped package -------------------------------------------------------


def _skip_unless_shipped(test: unittest.TestCase) -> Path:
    package = ROOT / "plugins" / svs.TARGET_PACKAGE
    if not (package / "PROVENANCE.json").is_file():
        test.skipTest("the portable unifi package has not been synchronized yet")
    return package


class ShippedPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = _skip_unless_shipped(self)

    def test_provenance_pins_the_corrected_revision(self) -> None:
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        commit = manifest["source_commit"]
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        self.assertFalse(
            commit.startswith(FORBIDDEN_REVISION_PREFIX),
            "requirement R3 forbids pinning the revision before the upstream repair",
        )
        self.assertEqual(commit, CORRECTED_REVISION)
        self.assertEqual(manifest["source_repository"], svs.SOURCE_REPOSITORY)

    def test_the_custody_table_agrees_with_the_recorded_classification(self) -> None:
        """The generator and the shipped manifest must not disagree about custody.

        A path the manifest records `target-owned` while the table still lists
        it as an upstream byte copy is a package whose own derivation tool would
        revert it on the next run. This compares every entry in the table
        against the classification the shipped `PROVENANCE.json` records, so the
        contradiction cannot come back at any path, not just this one.
        """
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        recorded = {entry["path"]: entry["classification"] for entry in manifest["files"]}
        expected: dict[str, str] = {}
        for relative in svs.PORTABLE_BYTE_COPIES:
            expected[relative] = check_repo.BYTE_COPY
        for relative in svs.CLIENT_BYTE_COPIES:
            expected[f"{svs.CLIENT_EXTENSION_DIR}/{relative}"] = check_repo.BYTE_COPY
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            expected[relative] = check_repo.TRANSFORM
        expected[f"{svs.CLIENT_EXTENSION_DIR}/plugin.json"] = check_repo.TRANSFORM
        for relative in svs.SUPERSEDED_BY_TARGET_OWNED:
            expected[relative] = check_repo.TARGET_OWNED

        for path, classification in expected.items():
            with self.subTest(path=path):
                self.assertEqual(
                    recorded.get(path),
                    classification,
                    f"the custody table in {svs.GENERATED_BY} and PROVENANCE.json disagree "
                    f"about {path}",
                )

        for relative in svs.DROPPED_FROM_SOURCE:
            with self.subTest(dropped=relative):
                self.assertNotIn(relative, recorded)

    def test_portable_manifest_carries_the_canonical_schema_and_a_conformant_name(self) -> None:
        manifest = json.loads((self.package / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["$schema"], check_repo.PLUGIN_SCHEMA)
        self.assertEqual(manifest["name"], svs.TARGET_PACKAGE)
        self.assertEqual(manifest["name"], self.package.name)
        self.assertEqual(check_repo.check_plugin_manifests(ROOT), [])

    def test_the_claude_manifest_is_not_at_the_plugin_root(self) -> None:
        self.assertTrue((self.package / svs.CLIENT_EXTENSION_DIR / "plugin.json").is_file())
        root_manifest = json.loads((self.package / "plugin.json").read_text(encoding="utf-8"))
        self.assertIn("$schema", root_manifest, "the plugin root carries the portable manifest")
        self.assertFalse((self.package / ".claude-plugin").exists())

    def test_portable_skill_frontmatter_conforms(self) -> None:
        skills = sorted(path for path in (self.package / "skills").iterdir() if path.is_dir())
        self.assertEqual([path.name for path in skills], ["unifi-network", "unifi-protect"])
        for skill in skills:
            fields = check_repo.read_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIsNotNone(fields, f"missing frontmatter in {skill.name}")
            assert fields is not None
            self.assertEqual(fields.get("name"), skill.name)
            for field in fields:
                self.assertIn(field, check_repo.SKILL_FRONTMATTER_FIELDS)
        self.assertEqual(check_repo.check_skill_frontmatter(ROOT), [])

    def test_no_fleet_commons_shim_is_shipped(self) -> None:
        self.assertEqual([str(p) for p in self.package.rglob("fleet_commons_shim.py")], [])

    def test_no_shipped_client_still_imports_the_dropped_shim(self) -> None:
        """The file being absent is not the guarantee; nothing importing it is.

        Matched against code rather than against the whole file, because the
        rewritten block keeps a comment naming the shim it replaced, and that
        sentence is the reason a later reader will not put the import back.
        """
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                body = (self.package / relative).read_text(encoding="utf-8")
                self.assertIsNone(SHIM_USE.search(body), f"{relative} still reaches for the shim")

    def test_shipped_clients_are_transforms_and_the_bundle_they_import_exists(self) -> None:
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        entries = {entry["path"]: entry for entry in manifest["files"]}
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                entry = entries[relative]
                self.assertEqual(entry["classification"], check_repo.TRANSFORM)
                self.assertEqual(entry["transform"], svs.BUNDLED_TRANSFORM_NAME)
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                bundled = bundle_beside(Path(relative))
                self.assertTrue(
                    (self.package / bundled).is_file(),
                    f"{relative} imports a bundle nothing wrote: {bundled}",
                )
                self.assertEqual(entries[bundled]["classification"], check_repo.TARGET_OWNED)

    def test_the_declaration_writes_a_bundle_beside_every_client_that_imports_one(self) -> None:
        """The join U3's bundler and U10's synchronization each own one half of.

        The rewrite points every client at a sibling ``_bundled`` directory. The
        build declaration is what puts a module there. When the two sets differ,
        the package ships a client importing a path nothing generates -- which
        is the defect this whole transform exists to close -- so they are
        compared directly rather than left to be noticed at run time.
        """
        declaration = json.loads(
            (self.package / "fleet-bundle.json").read_text(encoding="utf-8")
        )
        declared = {
            destination
            for module in declaration["modules"]
            for destination in module["destinations"]
        }
        resolved = {
            bundle_beside(Path(relative)) for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS
        }
        self.assertTrue(
            resolved <= declared,
            f"clients resolve {sorted(resolved - declared)}, which fleet-bundle.json "
            "does not declare",
        )


# --- parser-to-parser command surface ------------------------------------------


class _CapturedParser(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__("parser captured")
        self.parser = parser


def _stub(name: str, **attributes: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


@contextlib.contextmanager
def _client_import_environment():
    """Make both clients importable without third-party packages or the shim.

    The clients import ``requests`` and ``urllib3`` for transport and reach the
    shared retry primitive two different ways: upstream through
    ``fleet_commons_shim``, and here through the generated Fleet Core bundle the
    ``resolve-bundled-fleet-module`` transform points at. Both names are stood
    in, because this comparison copies each client to a temporary directory,
    where neither the shim nor the package's bundle directory is reachable.
    None of it participates in building the argument parser, so inert modules
    let the command surface be read on both sides under one rule. That the real
    bundled import resolves from the real package path is a different question,
    and ``tests/test_client_entrypoints.py`` answers it by running the shipped
    scripts where they actually live.
    """
    names = ("requests", "urllib3", "urllib3.exceptions", "fleet_commons_shim", "retry_backoff")
    saved_modules = {name: sys.modules.get(name) for name in names}
    saved_path = list(sys.path)
    exceptions = _stub(
        "urllib3.exceptions",
        InsecureRequestWarning=type("InsecureRequestWarning", (Warning,), {}),
    )
    retry = _stub("retry_backoff", retry_with_backoff=lambda *a, **k: None)
    sys.modules["urllib3.exceptions"] = exceptions
    sys.modules["urllib3"] = _stub(
        "urllib3", exceptions=exceptions, disable_warnings=lambda *a, **k: None
    )
    sys.modules["requests"] = _stub(
        "requests",
        request=lambda *a, **k: None,
        Session=object,
        exceptions=_stub("requests.exceptions"),
    )
    sys.modules["fleet_commons_shim"] = _stub("fleet_commons_shim", load=lambda name: retry)
    sys.modules["retry_backoff"] = retry
    try:
        yield
    finally:
        sys.path[:] = saved_path
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _subparser_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def command_surface(source: bytes, module_name: str) -> dict[str, list[str]]:
    """Build a client's real argparse parser and read its command surface.

    ``main()`` builds every subparser before it calls ``parse_args``, so
    intercepting that call yields the finished parser without running any
    command. The surface is read from the parser objects rather than from the
    documentation, which is the comparison the parity obligation asks for.
    """
    original = argparse.ArgumentParser.parse_args

    def capture(self, *arguments, **keywords):  # type: ignore[no-untyped-def]
        raise _CapturedParser(self)

    with _client_import_environment(), tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / f"{module_name}.py"
        path.write_bytes(source)
        specification = importlib.util.spec_from_file_location(module_name, path)
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[module_name] = module
        argparse.ArgumentParser.parse_args = capture  # type: ignore[method-assign]
        try:
            specification.loader.exec_module(module)
            try:
                module.main()
            except _CapturedParser as captured:
                parser = captured.parser
            else:  # pragma: no cover - main() must reach parse_args
                raise AssertionError(f"{module_name} did not build a parser")
        finally:
            argparse.ArgumentParser.parse_args = original  # type: ignore[method-assign]
            sys.modules.pop(module_name, None)

    surface: dict[str, list[str]] = {}
    for group, group_parser in _subparser_choices(parser).items():
        actions = _subparser_choices(group_parser)
        if not actions:
            surface[group] = sorted(
                {flag for action in group_parser._actions for flag in action.option_strings}
            )
            continue
        for action_name, action_parser in actions.items():
            surface[f"{group} {action_name}"] = sorted(
                {flag for action in action_parser._actions for flag in action.option_strings}
            )
    return surface


def _upstream_checkout() -> Path | None:
    override = os.environ.get("UNIFI_CLAUDE_CHECKOUT")
    candidates = [Path(override)] if override else []
    candidates.append(ROOT.parent / "infiquetra-claude-plugins")
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return None


CLIENTS = (
    (
        "skills/unifi-network/scripts/unifi_network_client.py",
        NETWORK_ACTIONS,
        NETWORK_RESOURCE_GROUPS,
    ),
    (
        "skills/unifi-protect/scripts/unifi_protect_client.py",
        PROTECT_ACTIONS,
        PROTECT_RESOURCE_GROUPS,
    ),
)


class CommandSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = _skip_unless_shipped(self)

    def test_ported_clients_carry_the_command_surface_the_parity_inventory_names(self) -> None:
        for relative, actions, groups in CLIENTS:
            with self.subTest(client=relative):
                name = Path(relative).stem
                surface = command_surface((self.package / relative).read_bytes(), f"ported_{name}")
                self.assertEqual(len(surface), actions)
                self.assertEqual(len({key.split(" ", 1)[0] for key in surface}), groups)

    def test_ported_command_surface_equals_the_upstream_surface(self) -> None:
        checkout = _upstream_checkout()
        if checkout is None:
            self.skipTest("no infiquetra-claude-plugins checkout is reachable from here")
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        commit = manifest["source_commit"]
        try:
            svs.resolve_commit(checkout, commit)
        except svs.SyncError:
            self.skipTest(f"the reachable checkout does not carry {commit}")
        for relative, actions, _groups in CLIENTS:
            with self.subTest(client=relative):
                name = Path(relative).stem
                upstream = command_surface(
                    svs.read_source_file(checkout, commit, relative), f"upstream_{name}"
                )
                ported = command_surface(
                    (self.package / relative).read_bytes(), f"ported_{name}"
                )
                differences = [
                    key
                    for key in sorted(set(upstream) | set(ported))
                    if upstream.get(key) != ported.get(key)
                ]
                self.assertEqual(differences, [])
                self.assertEqual(len(upstream), actions)


if __name__ == "__main__":
    unittest.main()
