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
import port_config  # noqa: E402
import sync_vendor_source as svs  # noqa: E402


#: The committed UniFi port descriptor. Every package-specific value these
#: tests need comes from it rather than from a constant restated here, so a
#: descriptor that stopped describing the shipped package fails these tests
#: rather than passing them against a stale copy of its own contents.
CONFIG = svs.load_config("unifi", ROOT)


def variant_config(**custody_overrides: object) -> "port_config.PortConfig":
    """The committed descriptor with one custody class replaced.

    Built through `port_config.parse` rather than by mutating the loaded object,
    so a variant that the validator would reject -- a path claimed twice, a
    traversing path -- fails to construct here exactly as it would on disk. This
    is what replaced patching a module constant: the custody table is data now,
    and a test that wants a different table asks for a different descriptor.
    """
    custody = {
        field: list(getattr(CONFIG.custody, field)) for field in port_config.CUSTODY_FIELDS
    }
    custody.update({key: list(value) for key, value in custody_overrides.items()})  # type: ignore[arg-type]
    # Descriptor schema version 3 states the transform rule per entry, so the
    # serialized table carries objects, not the bare paths the loaded table
    # exposes for its consumers.
    custody["entrypoint_transforms"] = [
        {"path": path, "rule": CONFIG.custody.entrypoint_rules[path]}
        for path in custody["entrypoint_transforms"]
    ]
    source = {
        "repository": CONFIG.source.repository,
        "package_path": CONFIG.source.package_path,
    }
    if CONFIG.source.manifest_path is not None:
        source["manifest_path"] = CONFIG.source.manifest_path
    if CONFIG.source.client_extension_dir is not None:
        source["client_extension_dir"] = CONFIG.source.client_extension_dir
    return port_config.parse(
        {
            "schema_version": port_config.SCHEMA_VERSION,
            "package": CONFIG.name,
            "package_root": CONFIG.package_root,
            "package_manifest": CONFIG.package_manifest,
            "source": source,
            "custody": custody,
            "assessment": {
                "credential_prefixes": list(CONFIG.assessment.credential_prefixes),
                "package_scripts": list(CONFIG.assessment.package_scripts),
                "mutating_operations": sorted(CONFIG.assessment.mutating_operations),
                "entrypoints": list(CONFIG.assessment.entrypoints),
                "skill_units": list(CONFIG.assessment.skill_units),
                "declared_none": list(CONFIG.assessment.declared_none),
            },
            "provenance": {
                "notes": list(CONFIG.notes),
                "dropped_reason": CONFIG.dropped_reason,
            },
        },
        root=CONFIG.root,
        path=CONFIG.path,
    )


# The corrected upstream revision this pilot synchronizes from. Requirement R3
# forbids pinning 995a475b, the revision before the documentation repair and the
# topology relocation landed, because synchronizing from it would re-import the
# defects that repair removed. The constant is pinned here on purpose: moving
# the pin is a deliberate act that has to change a test, not a silent drift.
#
# It has moved twice. First from 0eb1fe04 to its immediate child, when Fleet
# Core 0.25.1 repaired RFC 7231 `Retry-After` HTTP-date handling in the shared
# backoff primitive. The upstream `plugins/unifi` subtree is byte-identical
# across that step, so re-synchronizing changed no UniFi byte; the pin moved so
# that one revision names the corrected state of the whole port rather than two.
#
# Then from ed72f439 to 0d81dd9a, UniFi 2.0.1, which repaired the caller half of
# the same defect: both clients converted the raw `Retry-After` header with
# `int()` before raising, so a primitive that had learned to read the HTTP-date
# form never received one. That move does change UniFi bytes -- both client
# entrypoints and the upstream changelog -- so the `resolve-bundled-fleet-module`
# transform is re-applied over new source bytes and records new digests.
#
# Then from 0d81dd9a to c835f91d, UniFi 2.0.2, which closed a skew between the
# two halves of this one package. The Claude-path loader shipped here was pinned
# to site-profile schema 1.0 while the portable half advanced its own contract to
# 1.1, so an operator authoring the 1.1 document the package documents had it
# rejected by their own integration, and a credential pasted into a free-text
# value was refused on one path and accepted on the other. That move changes the
# byte-copied loader and the upstream changelog.
#
# Then from c835f91d to 769d06f1, UniFi 2.0.3, which repaired the credential-value
# rule in both directions. The previous repair had replaced a one-token window
# with a two-token window: a placeholder in the second slot consumed the window,
# so a credential in the third was never examined, and grading the first token
# unconditionally rejected ordinary prose, because entropy per character cannot
# separate `rotation` from `hunter2`. That move changes the byte-copied loader
# again, along with the upstream changelog.
CORRECTED_REVISION = "818fd6843e51a9126752061a834db9dead28f72b"
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
        write(directory / CONFIG.source.package_path / relative, body)
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
        (self.target / "plugins" / CONFIG.name).mkdir(parents=True)
        self.commit = make_source_checkout(self.source)

    @property
    def package(self) -> Path:
        return self.target / "plugins" / CONFIG.name

    def synchronize(self, **keywords: object) -> tuple[list[str], str]:
        return svs.synchronize(CONFIG, self.source, self.commit, root=self.target, **keywords)


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
            len(CONFIG.custody.byte_copies)
            + len(CONFIG.custody.entrypoint_transforms)
            + len(CONFIG.custody.client_byte_copies)
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
            sorted([f"{CONFIG.source.client_extension_dir}/plugin.json", *CONFIG.custody.entrypoint_transforms]),
        )
        for path, entry in transforms.items():
            with self.subTest(path=path):
                for field in ("source_sha256", "sha256"):
                    self.assertRegex(entry[field], r"^[0-9a-f]{64}$")
                self.assertTrue(entry["transform_rule"].strip())
                self.assertTrue(entry["transform_version"].strip())

        manifest_entry = transforms[f"{CONFIG.source.client_extension_dir}/plugin.json"]
        self.assertEqual(
            manifest_entry["source_path"], "plugins/unifi/.claude-plugin/plugin.json"
        )
        self.assertEqual(manifest_entry["transform"], svs.MANIFEST_TRANSFORM_NAME)
        self.assertEqual(manifest_entry["transform_version"], svs.MANIFEST_TRANSFORM_VERSION)

        for relative in CONFIG.custody.entrypoint_transforms:
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
            "skills/unifi-network/scripts/fleet_commons_shim.py", CONFIG.custody.dropped_from_source
        )
        self.assertIn(
            "skills/unifi-protect/scripts/fleet_commons_shim.py", CONFIG.custody.dropped_from_source
        )
        found = [str(path) for path in self.package.rglob("fleet_commons_shim.py")]
        self.assertEqual(found, [])
        manifest = (self.package / "PROVENANCE.json").read_text(encoding="utf-8")
        self.assertNotIn('"path": "skills/unifi-network/scripts/fleet_commons_shim.py"', manifest)

    def test_claude_manifest_lands_under_the_client_extension_directory(self) -> None:
        self.synchronize()
        relocated = self.package / CONFIG.source.client_extension_dir / "plugin.json"
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
        for relative in CONFIG.custody.entrypoint_transforms:
            with self.subTest(client=relative):
                body = (self.package / relative).read_text(encoding="utf-8")
                self.assertIsNone(SHIM_USE.search(body))
                self.assertIn("import retry_backoff as _retry_backoff", body)
                self.assertIn(expected, body)

    def test_resynchronizing_re_applies_the_rule_rather_than_restoring_the_shim(self) -> None:
        """A later synchronization must not silently put the broken import back."""
        self.synchronize()
        relative = CONFIG.custody.entrypoint_transforms[0]
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
        for relative in CONFIG.custody.client_byte_copies:
            self.assertTrue(
                (self.package / CONFIG.source.client_extension_dir / relative).is_file(),
                f"client-custody file missing: {relative}",
            )


# --- refusals ------------------------------------------------------------------


class RefusalTests(SyncFixture):
    def test_a_dirty_checkout_is_refused(self) -> None:
        # The witness is a path synchronization actually writes. README.md is
        # target-owned and is never written, so its absence would prove nothing.
        dirtied = self.source / CONFIG.source.package_path / "CHANGELOG.md"
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
        write(self.source / CONFIG.source.package_path / "hooks" / "hooks.json", "{}\n")
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
            svs.synchronize(CONFIG, base, commit, root=self.target)
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
            svs.synchronize(CONFIG, base, commit, root=self.target)
        self.assertIn("found 2", str(caught.exception))

    def test_a_missing_commit_is_refused(self) -> None:
        with self.assertRaises(svs.SyncError):
            svs.synchronize(CONFIG, self.source, "0" * 40, root=self.target)

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


# --- the mission-control transform shapes --------------------------------------


# The module-scope split shape `executor_profile_lint.py` carries at the
# mission-control pin: the shim import at module scope, the load call inside a
# function far away. Reproduced verbatim in the parts the
# `resolve-bundled-fleet-module-split` rule is defined over, so a rule change
# that stops matching the pin shape fails here against the shape itself.
SPLIT_SHAPE_SOURCE = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
    "\n"
    "import fleet_commons_shim  # noqa: E402  (after the sys.path shim, by design)\n"
    "\n"
    "\n"
    "def lint_body(body: str) -> tuple[int, list[str]]:\n"
    '    palette = fleet_commons_shim.load("tier_palette")\n'
    "    return 0, [str(palette)]\n"
)

# The function-scope guarded-contiguous shape `sdlc_manager.py` carries at the
# pin inside `_load_intent_envelope`: binding, guard, guarded insert, import,
# blank line, and the returned load, one contiguous block.
GUARDED_SHAPE_SOURCE = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def _load_intent_envelope():\n"
    '    """Lazy loader."""\n'
    "    scripts_dir = str(Path(__file__).resolve().parent)\n"
    "    if scripts_dir not in sys.path:\n"
    "        sys.path.insert(0, scripts_dir)\n"
    "    import fleet_commons_shim  # noqa: PLC0415\n"
    "\n"
    '    return fleet_commons_shim.load("intent_envelope")\n'
)

# The frontmatter shape all seven mission-control skills carry at the pin:
# name, a block-scalar description, a block-scalar when_to_use with blank
# lines inside it, then the body.
FRONTMATTER_SHAPE_SOURCE = (
    "---\n"
    "name: example\n"
    "description: |\n"
    "  A fixture skill.\n"
    "when_to_use: |\n"
    "  Use this fixture when:\n"
    "\n"
    "  - testing the fold\n"
    "---\n"
    "\n"
    "# Example skill\n"
)


class SplitModuleRuleTests(unittest.TestCase):
    """`resolve-bundled-fleet-module-split`: one import block, one load call."""

    def transform(self, body: str) -> str:
        return svs.split_module_transform(body.encode("utf-8"), "scripts/example.py").decode(
            "utf-8"
        )

    def test_the_split_shape_is_rewritten_to_the_bundle(self) -> None:
        rewritten = self.transform(SPLIT_SHAPE_SOURCE)
        self.assertNotRegex(rewritten, SHIM_USE)
        self.assertIn(
            'sys.path.insert(0, str(Path(__file__).resolve().parent / "_bundled"))', rewritten
        )
        self.assertIn(
            "import tier_palette  # noqa: E402  (after the sys.path shim, by design)", rewritten
        )
        self.assertIn("    palette = tier_palette", rewritten)
        # Nothing outside the two matched sites moves.
        self.assertIn("def lint_body(body: str) -> tuple[int, list[str]]:", rewritten)

    def test_zero_matches_of_either_site_are_refused(self) -> None:
        with self.assertRaises(svs.SyncError) as no_block:
            self.transform("palette = 1\n")
        self.assertIn("found 0", str(no_block.exception))
        without_call = SPLIT_SHAPE_SOURCE.replace(
            'palette = fleet_commons_shim.load("tier_palette")', "palette = None"
        )
        with self.assertRaises(svs.SyncError) as no_call:
            self.transform(without_call)
        message = str(no_call.exception)
        self.assertIn("load(NAME) call site", message)
        self.assertIn("found 0", message)

    def test_multiple_matches_are_refused_never_first_match(self) -> None:
        doubled_block = SPLIT_SHAPE_SOURCE + "\n" + (
            "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
            "\n"
            "import fleet_commons_shim\n"
        )
        with self.assertRaises(svs.SyncError) as two_blocks:
            self.transform(doubled_block)
        message = str(two_blocks.exception)
        self.assertIn("import block", message)
        self.assertIn("found 2", message)
        doubled_call = SPLIT_SHAPE_SOURCE + (
            '\nother = fleet_commons_shim.load("tier_palette")\n'
        )
        with self.assertRaises(svs.SyncError) as two_calls:
            self.transform(doubled_call)
        self.assertIn("found 2", str(two_calls.exception))

    def test_the_contiguous_v1_shape_does_not_match_the_split_rule(self) -> None:
        """The frozen rule and the split rule describe disjoint shapes."""
        with self.assertRaises(svs.SyncError):
            self.transform(FIXTURE_SHIM_BLOCK + "NETWORK = 1\n")


class GuardedModuleRuleTests(unittest.TestCase):
    """`resolve-bundled-fleet-module-guarded`: one if-guarded contiguous block."""

    def transform(self, body: str) -> str:
        return svs.guarded_module_transform(body.encode("utf-8"), "scripts/example.py").decode(
            "utf-8"
        )

    def test_the_guarded_shape_is_rewritten_to_the_bundle(self) -> None:
        rewritten = self.transform(GUARDED_SHAPE_SOURCE)
        self.assertNotRegex(rewritten, SHIM_USE)
        self.assertIn(
            '    scripts_dir = str(Path(__file__).resolve().parent / "_bundled")', rewritten
        )
        self.assertIn("    if scripts_dir not in sys.path:", rewritten)
        self.assertIn("        sys.path.insert(0, scripts_dir)", rewritten)
        self.assertIn("    import intent_envelope  # noqa: PLC0415", rewritten)
        self.assertIn("    return intent_envelope", rewritten)
        # The lazy, function-scope import survives: no module-scope import appeared.
        self.assertIsNone(re.search(r"^import intent_envelope", rewritten, re.MULTILINE))

    def test_zero_matches_are_refused(self) -> None:
        with self.assertRaises(svs.SyncError) as caught:
            self.transform("def _load():\n    return None\n")
        self.assertIn("found 0", str(caught.exception))

    def test_multiple_matches_are_refused_never_first_match(self) -> None:
        second_body = GUARDED_SHAPE_SOURCE.split("def _load_intent_envelope():\n", 1)[1]
        doubled = GUARDED_SHAPE_SOURCE + "\n\n" + "def second():\n" + second_body
        with self.assertRaises(svs.SyncError) as caught:
            self.transform(doubled)
        self.assertIn("found 2", str(caught.exception))

    def test_a_block_whose_lines_disagree_on_the_binding_is_refused(self) -> None:
        mismatched = GUARDED_SHAPE_SOURCE.replace(
            "    if scripts_dir not in sys.path:", "    if other_dir not in sys.path:"
        )
        with self.assertRaises(svs.SyncError):
            self.transform(mismatched)


class FrontmatterRuleTests(unittest.TestCase):
    """`normalize-skill-frontmatter`: fold when_to_use under metadata."""

    def transform(self, body: str) -> str:
        return svs.normalize_skill_frontmatter(
            body.encode("utf-8"), "skills/example/SKILL.md"
        ).decode("utf-8")

    def test_the_key_is_folded_under_metadata_with_its_value_reindented(self) -> None:
        rewritten = self.transform(FRONTMATTER_SHAPE_SOURCE)
        expected = (
            "---\n"
            "name: example\n"
            "description: |\n"
            "  A fixture skill.\n"
            "metadata:\n"
            "  when_to_use: |\n"
            "    Use this fixture when:\n"
            "\n"
            "    - testing the fold\n"
            "---\n"
            "\n"
            "# Example skill\n"
        )
        self.assertEqual(rewritten, expected)
        fields = check_repo.read_frontmatter(rewritten)
        self.assertIsNotNone(fields)
        assert fields is not None
        self.assertEqual(sorted(fields), ["description", "metadata", "name"])
        for field in fields:
            self.assertIn(field, check_repo.SKILL_FRONTMATTER_FIELDS)
        # The body below the frontmatter is untouched.
        self.assertTrue(rewritten.endswith("# Example skill\n"))

    def test_the_fold_is_deterministic_and_idempotent(self) -> None:
        once = svs.normalize_skill_frontmatter(
            FRONTMATTER_SHAPE_SOURCE.encode("utf-8"), "skills/example/SKILL.md"
        )
        again = svs.normalize_skill_frontmatter(once, "skills/example/SKILL.md")
        self.assertEqual(once, again, "a second application is a no-op")
        self.assertEqual(
            once,
            svs.normalize_skill_frontmatter(
                FRONTMATTER_SHAPE_SOURCE.encode("utf-8"), "skills/example/SKILL.md"
            ),
            "the same input always produces the same output",
        )

    def test_a_frontmatter_without_the_key_is_returned_unchanged(self) -> None:
        payload = ("---\nname: example\ndescription: fixture\n---\n# body\n").encode("utf-8")
        self.assertEqual(svs.normalize_skill_frontmatter(payload, "skills/x/SKILL.md"), payload)

    def test_an_unterminated_frontmatter_is_refused(self) -> None:
        with self.assertRaises(svs.SyncError) as caught:
            self.transform("---\nname: example\nwhen_to_use: |\n  use it\n")
        self.assertIn("no closing ---", str(caught.exception))

    def test_a_document_without_frontmatter_is_refused(self) -> None:
        with self.assertRaises(svs.SyncError):
            self.transform("# not frontmatter\n")

    def test_two_when_to_use_keys_are_refused(self) -> None:
        doubled = FRONTMATTER_SHAPE_SOURCE.replace(
            "---\n\n# Example skill\n", "when_to_use: again\n---\n\n# Example skill\n"
        )
        with self.assertRaises(svs.SyncError) as caught:
            self.transform(doubled)
        self.assertIn("found 2", str(caught.exception))

    def test_an_existing_metadata_key_beside_the_fold_is_refused(self) -> None:
        """Folding under an existing mapping is a shape version 1 does not describe."""
        with_metadata = FRONTMATTER_SHAPE_SOURCE.replace(
            "when_to_use: |", "metadata:\n  owner: fixture\nwhen_to_use: |"
        )
        with self.assertRaises(svs.SyncError) as caught:
            self.transform(with_metadata)
        self.assertIn("metadata", str(caught.exception))


#: A synthetic upstream shaped like mission-control's Lane A: the two shim
#: shapes, the frontmatter shape, and the dropped shim itself.
MISSION_SHAPED_SOURCE: dict[str, str] = {
    ".claude-plugin/plugin.json": FIXTURE_MANIFEST,
    "CHANGELOG.md": "# fixture changelog\n",
    "scripts/split_client.py": SPLIT_SHAPE_SOURCE,
    "scripts/guarded_client.py": GUARDED_SHAPE_SOURCE,
    "skills/example/SKILL.md": FRONTMATTER_SHAPE_SOURCE,
    "scripts/fleet_commons_shim.py": "SHIM = 1\n",
}


def mission_shaped_config(**entrypoint_overrides: object) -> port_config.PortConfig:
    """A schema-3 descriptor for the mission-shaped fixture, built like the committed ones."""
    entrypoints = [
        {"path": "scripts/split_client.py", "rule": svs.SPLIT_BUNDLED_TRANSFORM_NAME},
        {"path": "scripts/guarded_client.py", "rule": svs.GUARDED_BUNDLED_TRANSFORM_NAME},
        {"path": "skills/example/SKILL.md", "rule": svs.FRONTMATTER_TRANSFORM_NAME},
    ]
    entrypoints = [dict(entry, **entrypoint_overrides) for entry in entrypoints]
    return port_config.parse(
        {
            "schema_version": port_config.SCHEMA_VERSION,
            "package": CONFIG.name,
            "package_root": CONFIG.package_root,
            "package_manifest": CONFIG.package_manifest,
            "source": {
                "repository": CONFIG.source.repository,
                "package_path": CONFIG.source.package_path,
                "manifest_path": ".claude-plugin/plugin.json",
                "client_extension_dir": "com.infiquetra.claude",
            },
            "custody": {
                "byte_copies": ["CHANGELOG.md"],
                "entrypoint_transforms": entrypoints,
                "dropped_from_source": ["scripts/fleet_commons_shim.py"],
            },
            "assessment": {
                "credential_prefixes": list(CONFIG.assessment.credential_prefixes),
                "package_scripts": list(CONFIG.assessment.package_scripts),
                "mutating_operations": sorted(CONFIG.assessment.mutating_operations),
                "entrypoints": list(CONFIG.assessment.entrypoints),
                "skill_units": list(CONFIG.assessment.skill_units),
                "declared_none": list(CONFIG.assessment.declared_none),
            },
            "provenance": {
                "notes": [],
                "dropped_reason": "Replaced by the build-time Fleet Core bundle.",
            },
        },
        root=CONFIG.root,
        path=CONFIG.path,
    )


class MissionShapedSyncTests(SyncFixture):
    """The new rules end-to-end: sync the mission-shaped fixture and read the manifest."""

    def setUp(self) -> None:
        super().setUp()
        base = Path(self._temporary.name) / "upstream-mission-shaped"
        self.commit = make_source_checkout(base, MISSION_SHAPED_SOURCE)
        self.source = base
        self.config = mission_shaped_config()

    def synchronize_shaped(self, **keywords: object) -> tuple[list[str], str]:
        return svs.synchronize(self.config, self.source, self.commit, root=self.target, **keywords)

    def test_each_rule_is_recorded_with_its_name_version_and_digests(self) -> None:
        self.synchronize_shaped()
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        transforms = {
            entry["path"]: entry
            for entry in manifest["files"]
            if entry["classification"] == check_repo.TRANSFORM
        }
        expected_rules = {
            "scripts/split_client.py": (
                svs.SPLIT_BUNDLED_TRANSFORM_NAME,
                svs.SPLIT_BUNDLED_TRANSFORM_VERSION,
            ),
            "scripts/guarded_client.py": (
                svs.GUARDED_BUNDLED_TRANSFORM_NAME,
                svs.GUARDED_BUNDLED_TRANSFORM_VERSION,
            ),
            "skills/example/SKILL.md": (
                svs.FRONTMATTER_TRANSFORM_NAME,
                svs.FRONTMATTER_TRANSFORM_VERSION,
            ),
            # The client manifest is the one transform no descriptor entry
            # selects: it always relocates under its own rule.
            f"{CONFIG.source.client_extension_dir}/plugin.json": (
                svs.MANIFEST_TRANSFORM_NAME,
                svs.MANIFEST_TRANSFORM_VERSION,
            ),
        }
        self.assertEqual(sorted(transforms), sorted(expected_rules))
        rewrites = set(expected_rules) - {f"{CONFIG.source.client_extension_dir}/plugin.json"}
        for path, (name, version) in expected_rules.items():
            with self.subTest(path=path):
                entry = transforms[path]
                self.assertEqual(entry["transform"], name)
                self.assertEqual(entry["transform_version"], version)
                for field in ("source_sha256", "sha256"):
                    self.assertRegex(entry[field], r"^[0-9a-f]{64}$")
                if path in rewrites:
                    # The manifest relocation preserves bytes and derives only
                    # the output path; every rewriting rule must change some.
                    self.assertNotEqual(
                        entry["source_sha256"],
                        entry["sha256"],
                        "the rewrite changed no byte, so the output still carries "
                        "the shim shape",
                    )
                self.assertTrue(entry["transform_rule"].strip())

    def test_the_transformed_outputs_carry_no_shim_import(self) -> None:
        self.synchronize_shaped()
        for relative in ("scripts/split_client.py", "scripts/guarded_client.py"):
            with self.subTest(client=relative):
                body = (self.package / relative).read_text(encoding="utf-8")
                self.assertIsNone(SHIM_USE.search(body))
        self.assertEqual(check_repo.check_provenance_manifests(self.target), [])

    def test_resync_is_a_noop_and_check_mode_agrees(self) -> None:
        self.synchronize_shaped()
        before = tree_snapshot(self.package)
        written, _ = self.synchronize_shaped()
        self.assertEqual(written, [])
        self.assertEqual(tree_snapshot(self.package), before)
        errors, _ = self.synchronize_shaped(check_only=True)
        self.assertEqual(errors, [])

    def test_a_rule_name_the_tool_does_not_implement_is_refused(self) -> None:
        self.config = mission_shaped_config(rule="resolve-bundled-fleet-module-nonexistent")
        with self.assertRaises(svs.SyncError) as caught:
            self.synchronize_shaped()
        message = str(caught.exception)
        self.assertIn("does not implement", message)
        self.assertIn("resolve-bundled-fleet-module-nonexistent", message)

    def test_a_path_with_no_rule_named_is_refused(self) -> None:
        with self.assertRaises(svs.SyncError) as caught:
            svs.resolve_transform_rule(self.config, "scripts/unlisted.py")
        self.assertIn("names no transform rule", str(caught.exception))

    def test_rule_names_register_exactly_once(self) -> None:
        rule = svs.BUNDLED_MODULE_RULE
        with self.assertRaises(ValueError) as caught:
            svs._build_rule_registry(rule, rule)
        self.assertIn("registered twice", str(caught.exception))
        expected = {
            svs.MANIFEST_TRANSFORM_NAME,
            svs.BUNDLED_TRANSFORM_NAME,
            svs.SPLIT_BUNDLED_TRANSFORM_NAME,
            svs.GUARDED_BUNDLED_TRANSFORM_NAME,
            svs.FRONTMATTER_TRANSFORM_NAME,
            svs.PACKAGE_ROOT_MARKER_TRANSFORM_NAME,
        }
        self.assertEqual(set(svs.TRANSFORM_RULES), expected)


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
                "source_path": f"{CONFIG.source.package_path}/README.md",
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
        self.assertNotIn("README.md", CONFIG.custody.byte_copies)
        self.assertIn("README.md", CONFIG.custody.superseded_by_target_owned)
        svs.classify_source_tree(CONFIG, sorted(FIXTURE_SOURCE))

        without_supersession = variant_config(
            superseded_by_target_owned=[
                name for name in CONFIG.custody.superseded_by_target_owned if name != "README.md"
            ]
        )
        with self.assertRaises(svs.SyncError) as caught:
            svs.classify_source_tree(without_supersession, sorted(FIXTURE_SOURCE))
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
                "source_path": f"{CONFIG.source.package_path}/retired.py",
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
    package = ROOT / "plugins" / CONFIG.name
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
        self.assertEqual(manifest["source_repository"], CONFIG.source.repository)

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
        for relative in CONFIG.custody.byte_copies:
            expected[relative] = check_repo.BYTE_COPY
        for relative in CONFIG.custody.client_byte_copies:
            expected[f"{CONFIG.source.client_extension_dir}/{relative}"] = check_repo.BYTE_COPY
        for relative in CONFIG.custody.entrypoint_transforms:
            expected[relative] = check_repo.TRANSFORM
        expected[f"{CONFIG.source.client_extension_dir}/plugin.json"] = check_repo.TRANSFORM
        for relative in CONFIG.custody.superseded_by_target_owned:
            expected[relative] = check_repo.TARGET_OWNED

        for path, classification in expected.items():
            with self.subTest(path=path):
                self.assertEqual(
                    recorded.get(path),
                    classification,
                    f"the custody table in {svs.GENERATED_BY} and PROVENANCE.json disagree "
                    f"about {path}",
                )

        for relative in CONFIG.custody.dropped_from_source:
            with self.subTest(dropped=relative):
                self.assertNotIn(relative, recorded)

    def test_portable_manifest_carries_the_canonical_schema_and_a_conformant_name(self) -> None:
        manifest = json.loads((self.package / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["$schema"], check_repo.PLUGIN_SCHEMA)
        self.assertEqual(manifest["name"], CONFIG.name)
        self.assertEqual(manifest["name"], self.package.name)
        errors = check_repo.check_plugin_manifests(ROOT)
        # The run plan's landing model lets a synchronized tree land before the
        # target-owned portable manifest its own lane authors (Lane B). That
        # interim state is legitimate only while it names exactly the packages
        # whose manifest is missing -- the same condition the port-descriptor
        # gate reports -- never a defect in a manifest a package ships.
        incomplete = [
            config
            for config in port_config.load_all(ROOT)
            if config.package_directory.is_dir() and not config.manifest_path.is_file()
        ]
        for error in errors:
            self.assertTrue(
                any(config.package_root in error for config in incomplete),
                f"check_plugin_manifests reported a defect the landing model does not "
                f"expect: {error}",
            )

    def test_the_claude_manifest_is_not_at_the_plugin_root(self) -> None:
        self.assertTrue((self.package / CONFIG.source.client_extension_dir / "plugin.json").is_file())
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
        for relative in CONFIG.custody.entrypoint_transforms:
            with self.subTest(client=relative):
                body = (self.package / relative).read_text(encoding="utf-8")
                self.assertIsNone(SHIM_USE.search(body), f"{relative} still reaches for the shim")

    def test_shipped_clients_are_transforms_and_the_bundle_they_import_exists(self) -> None:
        manifest = json.loads((self.package / "PROVENANCE.json").read_text(encoding="utf-8"))
        entries = {entry["path"]: entry for entry in manifest["files"]}
        for relative in CONFIG.custody.entrypoint_transforms:
            with self.subTest(client=relative):
                entry = entries[relative]
                self.assertEqual(entry["classification"], check_repo.TRANSFORM)
                self.assertEqual(entry["transform"], svs.BUNDLED_TRANSFORM_NAME)
        for relative in CONFIG.custody.entrypoint_transforms:
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
            bundle_beside(Path(relative)) for relative in CONFIG.custody.entrypoint_transforms
        }
        self.assertTrue(
            resolved <= declared,
            f"clients resolve {sorted(resolved - declared)}, which fleet-bundle.json "
            "does not declare",
        )


# --- the shipped mission-control package ----------------------------------------


#: The audited mission-control pin (run plan R4; descriptor provenance notes).
#: Pinned here on purpose: moving it is a deliberate act that has to change a
#: test, not a silent drift.
MISSION_CONTROL_PIN = "3b2b7083fdda8e39e213b5f4acf9f8301d60dd52"
MISSION_CONTROL_SKILLS = ("board", "flow", "issues", "labels", "metrics", "milestones", "rollout")


def _skip_unless_mission_control_shipped(test: unittest.TestCase) -> Path:
    package = ROOT / "plugins" / "mission-control"
    if not (package / "PROVENANCE.json").is_file():
        test.skipTest("the portable mission-control package has not been synchronized yet")
    return package


class MissionControlShippedTests(unittest.TestCase):
    """The synchronized mission-control tree: child #13's custody outcomes on the real package."""

    def setUp(self) -> None:
        self.package = _skip_unless_mission_control_shipped(self)
        self.config = svs.load_config("mission-control", ROOT)
        self.manifest = json.loads(
            (self.package / "PROVENANCE.json").read_text(encoding="utf-8")
        )

    def test_provenance_pins_the_audited_revision(self) -> None:
        self.assertEqual(self.manifest["source_commit"], MISSION_CONTROL_PIN)
        self.assertEqual(self.manifest["source_version"], "2.15.2")
        self.assertEqual(self.manifest["source_repository"], self.config.source.repository)

    def test_the_transformed_entrypoints_resolve_the_bundle_and_never_the_shim(self) -> None:
        """Import-line correctness is assertable now; the bundle itself lands with Lane C.

        The two rules land the bundle directory differently: the split rule
        inserts it at module scope, the guarded rule moves the existing
        function-local binding's value, which the guarded insert then uses.
        """
        bundled = f'"{svs.BUNDLE_DIRECTORY_NAME}"'
        expected = {
            "scripts/executor_profile_lint.py": (
                svs.SPLIT_BUNDLED_TRANSFORM_NAME,
                (
                    f"sys.path.insert(0, str(Path(__file__).resolve().parent / {bundled}))",
                    "import tier_palette",
                    "palette = tier_palette",
                ),
            ),
            "scripts/sdlc_manager.py": (
                svs.GUARDED_BUNDLED_TRANSFORM_NAME,
                (
                    f"scripts_dir = str(Path(__file__).resolve().parent / {bundled})",
                    "sys.path.insert(0, scripts_dir)",
                    "import intent_envelope",
                    "return intent_envelope",
                ),
            ),
        }
        entries = {entry["path"]: entry for entry in self.manifest["files"]}
        for relative, (rule_name, fragments) in expected.items():
            with self.subTest(client=relative):
                body = (self.package / relative).read_text(encoding="utf-8")
                self.assertIsNone(
                    SHIM_USE.search(body), f"{relative} still reaches for the shim"
                )
                for fragment in fragments:
                    self.assertIn(fragment, body)
                entry = entries[relative]
                self.assertEqual(entry["classification"], check_repo.TRANSFORM)
                self.assertEqual(entry["transform"], rule_name)
                self.assertEqual(
                    entry["transform_version"], svs.TRANSFORM_RULES[rule_name].version
                )
                for field in ("source_sha256", "sha256"):
                    self.assertRegex(entry[field], r"^[0-9a-f]{64}$")
                self.assertNotEqual(
                    entry["source_sha256"], entry["sha256"], "the rewrite changed no byte"
                )

    def test_all_seven_skills_fold_when_to_use_under_metadata(self) -> None:
        entries = {entry["path"]: entry for entry in self.manifest["files"]}
        for skill in MISSION_CONTROL_SKILLS:
            with self.subTest(skill=skill):
                relative = f"skills/{skill}/SKILL.md"
                text = (self.package / relative).read_text(encoding="utf-8")
                fields = check_repo.read_frontmatter(text)
                self.assertIsNotNone(fields, f"missing frontmatter in {relative}")
                assert fields is not None
                self.assertEqual(fields.get("name"), skill)
                self.assertNotIn("when_to_use", fields, "the key stayed at top level")
                self.assertIn("metadata", fields)
                for field in fields:
                    self.assertIn(field, check_repo.SKILL_FRONTMATTER_FIELDS)
                # The fold preserved the key's content.
                self.assertIn("Use this skill when the user wants to:", text)
                self.assertNotIn("\nwhen_to_use:", text)
                entry = entries[relative]
                self.assertEqual(entry["classification"], check_repo.TRANSFORM)
                self.assertEqual(entry["transform"], svs.FRONTMATTER_TRANSFORM_NAME)

    def test_the_shim_is_dropped_with_its_reason_recorded(self) -> None:
        shim = [
            entry
            for entry in self.manifest["removed_from_source"]
            if entry["source_path"] == "plugins/mission-control/scripts/fleet_commons_shim.py"
        ]
        self.assertEqual(len(shim), 1)
        self.assertTrue(shim[0]["reason"].strip())
        self.assertEqual([str(path) for path in self.package.rglob("fleet_commons_shim.py")], [])

    def test_the_client_custody_files_land_under_the_extension_directory(self) -> None:
        for relative in self.config.custody.client_byte_copies:
            with self.subTest(file=relative):
                target = self.package / self.config.source.client_extension_dir / relative
                self.assertTrue(target.is_file(), f"client-custody file missing: {relative}")
        relocated = self.package / self.config.source.client_extension_dir / "plugin.json"
        self.assertTrue(relocated.is_file())
        self.assertFalse((self.package / ".claude-plugin").exists())

    def test_mission_control_skills_matches_the_shipped_roster(self) -> None:
        """U4c roster confirmation, re-derived against the shipped tree rather
        than copied forward: a removed skill would fail the frontmatter checks
        above, but an added skill would silently go unchecked, so the tuple and
        the shipped directories must be the same set in both directions."""
        skill_dirs = sorted(
            path.name
            for path in (self.package / "skills").iterdir()
            if path.is_dir()
        )
        self.assertEqual(sorted(MISSION_CONTROL_SKILLS), skill_dirs)
        for skill in skill_dirs:
            with self.subTest(skill=skill):
                self.assertTrue(
                    (self.package / "skills" / skill / "SKILL.md").is_file(),
                    f"skill roster entry {skill} carries no SKILL.md",
                )

    def test_pyyaml_stays_required_at_module_scope(self) -> None:
        """U4c PyYAML confirmation on the resynchronized package. Upstream
        filing #828 deferred only sdlc_manager.py's import into a function;
        these two module-scope imports still make PyYAML genuinely required,
        so the CI install line must keep it — dropping it would break the
        package suite in continuous integration while passing locally. The
        assertion is anchored on the module-scope pattern, never a line
        number, because line numbers may move at the next pin."""
        module_scope_import = re.compile(r"^import yaml$", re.MULTILINE)
        for relative in (
            "scripts/sync_template_docs.py",
            "tests/test_template_sync.py",
        ):
            with self.subTest(file=relative):
                body = (self.package / relative).read_text(encoding="utf-8")
                self.assertRegex(
                    body,
                    module_scope_import,
                    f"{relative} no longer imports yaml at module scope; "
                    "re-read upstream filing #828 before touching the CI install line",
                )
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("pyyaml", ci, "the CI install line dropped pyyaml")


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
                    svs.read_source_file(CONFIG, checkout, commit, relative), f"upstream_{name}"
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
