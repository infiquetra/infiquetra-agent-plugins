# Importing agy and authoring it here

Date: 2026-09-22

Related: [custody move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md).

## What changed

`plugins/agy` was imported from `infiquetra-claude-plugins` at `acc99fe7`
(upstream 0.6.1) and is authored here at 0.6.2. There is no
`PROVENANCE.json`. The portable manifest, the root Claude manifest, and the
adapter manifest all say 0.6.2. The root marketplace lists the package.

The wrapper implementation is `skills/agy-delegate/scripts/agy_delegate.py`.
`scripts/agy_delegate.py` is a launcher that runs that file. Fleet Core
modules `audit_store`, `bridge_receipt`, and `output_attestation` are
generated under `skills/agy-delegate/scripts/_bundled/`.

## What was non-obvious

### The shim shape the importer knows did not match this file

**Evidence.** `python3 scripts/import_vendor_package.py --package agy
--source <infiquetra-claude-plugins> --commit acc99fe7` wrote the tree and
exited non-zero. The classification marked `scripts/agy_delegate.py` as
`unresolved-shim`. The file loads three modules in one block
(`bridge_receipt`, `output_attestation`, `audit_store`). The importer's
rewrite rules each require exactly one `fleet_commons_shim.load` of one
shape, so none of them matched, and the file was copied unchanged.

**Mechanism.** The import still declared those three names in
`fleet-bundle.json`, which is what makes a hand rewrite possible. The
wrapper now inserts `scripts/_bundled` (beside the implementation) on
`sys.path` and imports the three modules directly. `bridge_receipt` loads
`output_attestation` as a sibling file in that same directory.
`audit_store` imports no other Fleet Core module, so the declaration does
not grow past the three names.

**Generalizable rule.** An unresolved shim is a file the importer carried
on purpose and named on the way out. Rewrite that file onto the bundle it
already declared. Do not copy `fleet_commons_shim.py` back in, and do not
add a fourth rule to the importer from one package's shape.

### The executable has to live in the skill directory, and the old path has to keep working

**Evidence.** OpenCode, Gemini CLI, Muse, and Hermes install a skill
directory rather than the package root. `scripts/assess_clients.py` refuses
a declared entrypoint that sits outside every declared skill unit.
`ports/agy.json` therefore names
`skills/agy-delegate/scripts/agy_delegate.py`. The bridge discriminator in
upstream `marketplace/bridge_plugins.json`, `_looks_like_agy_command`, and
the agent prompts all treat the string `plugins/agy/scripts/agy_delegate.py`
as the sign of a guarded run.

**Mechanism.** The implementation moved into the skill, and the bundle
moved with it, because the script resolves `_bundled` from its own
`__file__`. The catalog path remains a launcher (`runpy.run_path` of the
implementation) so a Claude agent that emits the historical command still
runs the wrapper. The command check also accepts
`skills/agy-delegate/scripts/agy_delegate.py`, so a skill-scoped invocation
is classified as a guarded run rather than as a raw `agy` call. Tests that
import the module or read its source load the implementation. A launcher
that only re-exported names would have broken monkeypatches of module
globals, because those names are looked up in the implementation's
namespace.

**Generalizable rule.** When a command string is part of the behavior
(a transcript classifier, a proof discriminator), keep that string working
as a launcher. Put the bytes a skill-only install needs inside the skill
directory, including the bundle the script imports at startup.

### `--help` must not print this machine's home directory

**Evidence.** The upstream `--audit-store` help interpolated
`audit_store.DEFAULT_AUDIT_STORE_ROOT`, which is `Path.home() /
".claude" / "delegation-audit"`. On this machine that string is an absolute
`/Users/...` path. `plugins/agy/tests/test_agy_entrypoint.py` runs `--help` with
credential-shaped variables removed and rejects `/Users/` in the output.

**Mechanism.** The help text now says `~/.claude/delegation-audit`. The
default behavior is unchanged: omitting `--audit-store` still resolves
Fleet Core's home-relative root inside `main`, after argparse has already
handled `--help`. The wrapper reads no credential environment variable.
`ports/agy.json` names `credential_prefixes` in `declared_none`. The one
mutating token recorded for assessment is `--launch-agy`, which `--help`
does not pass, so a client assessment can still invoke the entrypoint.

**Generalizable rule.** A default that is computed from the home directory
can still leak a machine path if the help string formats the computed
value. Describe the default. Do not interpolate it.

### The delegation-proof suite does not belong in this package

**Evidence.** Upstream `tests/test_check_delegation_proof.py`,
`tests/test_delegation_fleet_monitor.py`, and
`tests/test_delegation_proof_receipt.py` import
`scripts/check_delegation_proof.py` from the repository root, read
`marketplace/bridge_plugins.json`, sweep `docs/delegation-proofs/`, and one
of them reads `.github/workflows/delegation-integrity.yml`. The triage
marked that cluster as agy's because agy is the only bridge declared in
`bridge_plugins.json`. The import recipe says to drop a test whose premise
is the upstream repository layout or the marketplace format, and this unit
does not edit the shared catalog root.

**Mechanism.** Those three modules were not copied. The `tests/test_agy_*`
modules were, under `plugins/agy/tests/`, with `tests/fixtures/agy/`. Their
roots resolve from the package (`parents[1]`) and the fleet-core audit
store from the repository (`parents[3]`). Agent and command paths point
under `com.infiquetra.claude/`. Carrying the gate scripts into
`plugins/agy/scripts/` would have made `Path(__file__).parents[1]` the
package rather than the catalog, so the gate's default marketplace and
proof directories would have been wrong. Copying them to the repository
`scripts/` directory would collide with the codex import, which shares the
same gate. The drop is recorded in `plugins/agy/CHANGELOG.md`.

**Generalizable rule.** A test that passes only while the process's
repository root is the old catalog is a catalog test. Leave it for the
unit that owns that root. Do not vendor a second copy whose defaults
silently point at the package.

## Design calls

- Version bump is the patch: 0.6.1 to 0.6.2. No behavior of a launched
  delegation was changed except the help text and the extra accepted
  wrapper path above.
- `ports/agy.json` is authored (no `source`, no `custody`). Entrypoint is
  the skill script. `package_scripts` are `agy_delegate.py` and
  `audit_harness_transcript.py`. Mutating operation is `--launch-agy`.
- The historical harness-proof note stays. It records a 2026-06-30 run that
  used `auto-if-clean`, which 0.6.0 removed. The README says that document
  is not a procedure.
- Shared journal files (`DECISIONS.md`, `LEARNINGS.md`, `QUEUED.md`) and the
  repository README were not edited. This narrative is the record.

## Local gate that this package did not cause

`python3 -m unittest discover -s tests` and `python3 -m pytest plugins/*/tests`
both fail two Mission Control template-sync checks when
`~/workspace/infiquetra/infiquetra-sdlc` is present and its templates carry a
Risk field that `plugins/mission-control/skills/issues/references/templates-reference.md`
does not. The checks skip when that checkout is absent, which is the CI
case. This import does not change that reference. `plugins/agy/tests` is
82 passed.
