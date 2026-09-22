# Importing the Codex delegation package and authoring it here

Date: 2026-09-22

Related: [custody move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md).

## Context

`plugins/codex` did not exist in this catalog. Upstream
`infiquetra-claude-plugins` at commit `acc99fe7` ships it as version 0.1.4:
one wrapper, one command, two agents, and one skill. This import lays that
package out in the portable shape and maintains it here afterwards. There is
no provenance manifest.

## What was non-obvious

### Two Fleet Core loads, and none of the rewrite rules match

**Evidence.** `scripts/import_vendor_package.py --dry-run` classified
`scripts/codex_delegate.py` as `unresolved-shim`. The upstream block is one
`sys.path` insert, one `import fleet_commons_shim`, and two
`fleet_commons_shim.load` calls (`bridge_receipt` and `output_attestation`).
`scripts/sync_vendor_source.py` has three rewrite rules. Each one requires
exactly one load, and each raises when it finds any other count. The import
therefore wrote the file unchanged and exited non-zero, which is what that
script does for a shape it will not guess.

**Mechanism.** The hand rewrite inserts `scripts/_bundled` and imports the
two modules under the same bindings the wrapper already used. The generated
`fleet-bundle.json` already named both modules at that destination, because
the importer reads the load calls before it tries to rewrite them.
`bridge_receipt` then loads `output_attestation` from its own directory. The
bundle writes that file beside it, so the sibling load resolves inside
`scripts/_bundled/` and no third module is declared. `output_attestation`
imports only the standard library. `scripts/fleet_commons_shim.py` is not
carried.

**Generalizable rule.** A wrapper that loads two Fleet Core modules through
one shim import has to be rewritten by hand. The rewrite rules are
single-load on purpose. The importer still declares every module it saw, so
the bundle is on disk when the hand rewrite lands.

### The skill and the Claude adapter do not share a path prefix

**Evidence.** Upstream commands, agents, and the skill all invoked
`python3 plugins/codex/scripts/codex_delegate.py`. That path is the old
repository layout. After install, Claude's package root is this package, and
the command and agents live under `com.infiquetra.claude/`.

**Mechanism.** The command and both agents now call
`${CLAUDE_PLUGIN_ROOT}/scripts/codex_delegate.py`. The skill does not. A
skill-scoped harness (OpenCode, Gemini CLI, Muse, Hermes) has no
`CLAUDE_PLUGIN_ROOT`. The skill tells that harness to run
`python3 scripts/codex_delegate.py` from the package root, and it lists the
wrapper's flags. The script reads no credential variable. The `codex` process
it supervises inherits the environment.

**Generalizable rule.** A path that was true in the upstream monorepo is not
true in an installed package. Claude surfaces can use `CLAUDE_PLUGIN_ROOT`.
The portable skill has to say the same thing without that variable.

### The live smoke must not run because this machine is logged in

**Evidence.** Upstream `tests/test_codex_delegate_lifecycle.py` skips its one
live `codex exec` unless `codex login status` exits 0. That is a property of
the machine, not an opt-in.

**Mechanism.** The carried test also requires `CODEX_DELEGATE_LIVE_SMOKE=1`.
Unset, it returns before it looks for the binary. The other carried tests use
a fake `codex` binary. `plugins/codex/tests/test_delegate_entrypoint.py` runs
`--help` with `OPENAI_` and `CODEX_` removed from the environment, because
`tests/test_client_entrypoints.py` skips a package that has no
`PROVENANCE.json`.

**Generalizable rule.** A test that needs a live vendor CLI skips on an
explicit variable. A logged-in binary on the machine running the suite is not
that variable.

## Design calls

- Version is 0.1.5. Upstream was 0.1.4. The patch bump marks the authored
  cut. The portable manifest, the root Claude manifest, and the adapter
  manifest all state 0.1.5.
- The adapter manifest's `repository` is this repository. Relocation keeps
  the upstream bytes, which still named `infiquetra-claude-plugins`.
- `ports/codex.json` is authored mode: no `source`, no `custody`. Assessment
  strips `OPENAI_` and `CODEX_` because the child inherits the environment.
  The mutating operation is the word `task`, which is the write-capable mode.
  `--help` does not contain that word.
- Delegation-proof tests were not carried. At `acc99fe7` they do not mention
  codex, and `marketplace/bridge_plugins.json` declares the agy bridge only.
  Landing them would add repository-root scripts this import does not own.
- `test_codex_plugin.py` was rewritten for this layout rather than dropped.
  Its old assertions required the shim, version 0.1.4, the old repository
  URL, and commands and agents at the package root.
- No Fleet Core module was missing. Nothing was copied in by hand.

## Outcome

After rebasing onto `origin/main`, `python3 -m pytest plugins/codex/tests -q`
passed 58 tests and skipped 1, the live smoke. `python3 -m pytest
plugins/*/tests -q` reported 1450 passed, 4 skipped, and 2 failed, both in
`plugins/mission-control/tests/test_template_sync.py`. `python3 -m unittest
discover -s tests` reported 946 tests and the same two failures, in
`tests/test_mission_control_rule_audit.py`. The sibling checkout
`~/workspace/infiquetra/infiquetra-sdlc` adds a `Risk` line the checked-in
reference does not have (three added lines, nothing removed). Those tests
skip when that checkout is absent. This import does not edit mission-control
to silence them.
