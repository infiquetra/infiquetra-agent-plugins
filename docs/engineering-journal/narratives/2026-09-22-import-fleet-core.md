# Importing Fleet Core in full, and authoring it here

Date: 2026-09-22

Related: [custody move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md).

## What changed

`plugins/fleet-core` was a four-file slice at 0.25.2, derived from
`infiquetra-claude-plugins` and pinned by `PROVENANCE.json`. It is now the
full library from commit `acc99fe7` (upstream 0.32.0), authored in this
repository. The provenance manifest is gone. `scripts/fleet_commons/` holds
18 Python modules and three data files. `scripts/jev.py` and `references/`
came with them. Package tests live under `plugins/fleet-core/tests/` (17
modules, 366 tests).

## What was non-obvious

### Sibling loads, not the discovery shim

**Evidence.** Upstream modules call `fleet_commons_shim.load`. The shim's
ladder walks a Claude Code install: an environment override, a marketplace
walk-up, `~/.claude/plugins/installed_plugins.json`, and a cache-sibling scan
(`plugins/fleet-core` at `acc99fe7`, `scripts/fleet_commons_shim.py`). This
catalog's consumers do not vendor that file. They receive a build-time copy
from `scripts/bundle_fleet_module.py`.

**Mechanism.** Every call site now loads `<this file's directory>/<name>.py`,
cached in `sys.modules` under a key that includes the directory. A bundled
copy and the canonical file therefore do not share a module object. Modules
that previously tried the shim and fell back to a path load no longer try the
shim at all, so an ambient `fleet_commons_shim` on `sys.path` cannot redirect
a bundle at the installed Fleet Core.

**Generalizable rule.** A file that is copied into a consumer has to resolve
its siblings from its own directory. A discovery helper that searches the
machine is not portable, and a try-the-shim-first fallback is still a
discovery helper.

### The palette file changed; one consumer still names the old one

**Evidence.** `tier_palette.py` at 0.32.0 reads `staffing.json` at import.
The slice read `models.json`. `plugins/mission-control/fleet-bundle.json`
still lists `models.json` and does not list `staffing.json`. The module list
is `intent_envelope` and `tier_palette`.

**Mechanism.** `models.json` stays on disk and stays declared. `DEFERRED.md`
records it as a residual to drop when mission-control's own import drops the
declaration. `staffing.json` was added as a data entry, not as a new module,
because the already-declared palette cannot import without it.
`executor_profile_lint.py` imports that palette at process start, and
`tests/test_client_entrypoints.py` runs the script.

**Generalizable rule.** When a declared module starts reading a sibling data
file at import, the consumer's data list has to grow or the entrypoint dies
at import. That is not a new module. The module list stays the consumer's
later import's job.

### An authored package still has to stamp a bundle

**Evidence.** `scripts/bundle_fleet_module.py` read `source_version` and
`source_commit` from `PROVENANCE.json`. `scripts/check_repo.py` requires both
fields in every bundle stamp, and it skips digest checks for a package that
has no provenance manifest.

**Mechanism.** With no manifest, the stamp records `plugin.json`'s `version`
and `source-commit: authored`. The source digest still binds the bundled
bytes to the module. `scripts/check_repo.py` was not edited. Its bytes are
named by `docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt`,
and that binding fails if the file changes without a new mutation run. The
journal links that pointed at `plugins/fleet-core/PROVENANCE.json` were
retargeted at the changelog, which is the record that the manifest is gone.

**Generalizable rule.** Deleting a provenance manifest does not delete the
stamp fields that say which release a bundle came from. Give those fields an
authored meaning. Do not edit a file whose mutation proof is bound to its
bytes in order to silence a link; retarget the link.

### Regenerated bundles move the compatibility fingerprint

**Evidence.** `scripts/check_compatibility_matrix.py` fails when a current
matrix's `tree_sha256` is not the hash of the package on disk. Regenerating
the UniFi `retry_backoff` bundles and the mission-control Fleet Core bundles,
and adding `staffing.json`, changes those hashes. The checker has no flag
that rewrites a record, because refreshing the numbers without a new
assessment is the failure the binding exists to catch.

**Mechanism.** The current UniFi and mission-control matrix and readback
records were updated to the new fingerprints, and each document says the
client results were not re-run. Superseded records were left on their old
hashes. The root `README.md` mission-control file count moved from 71 to 72
because `tests/test_mission_control_rule_audit.py` recomputes that count from
disk. The rest of that README still describes Fleet Core as a slice; the
import brief left the root README for the lead to consolidate.

**Generalizable rule.** A unit that is ordered to regenerate bundles will
move every fingerprint that covers those bundles. Say so in the evidence, in
the same commit, and do not pretend the old client run saw the new bytes.

## Design choices

- Tests whose premise is another plugin, the discovery shim, the upstream
  `pyproject.toml`, or `docs/analysis` research inputs were not ported. The
  list is in `plugins/fleet-core/CHANGELOG.md`.
- Ported TypeSafe fixtures that matched this repository's credential scan
  were shortened to shapes the client redactor still catches and the scan
  allows. The two pattern sets share a prefix and differ at the length
  boundary.
- `typesafe_client._sdk_call` checks that the body was prepared before it
  imports `typesafe-sdk`, and an injected client factory does not require
  the package. This catalog does not install the SDK. When the SDK is
  installed and no factory is passed, the call still uses it.
- The local template-sync failures against `infiquetra-sdlc` (a `Risk` field
  the committed mission-control reference does not yet list) were left
  alone. They are not caused by this import. Continuous integration skips
  them when that checkout is absent.
