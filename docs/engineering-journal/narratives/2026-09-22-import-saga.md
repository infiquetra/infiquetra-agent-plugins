# 2026-09-22 — import saga and author it here

Unit U3 for `plugins/saga` on branch `mg/saga`. Upstream is
infiquetra-claude-plugins at `acc99fe7` (package version 1.2.0). The authored
cut is 1.2.1. No provenance manifest.

## What was non-obvious

**Evidence.** `scripts/import_vendor_package.py` wrote the tree and exited
non-zero. Nine scripts still called `fleet_commons_shim.load` from inside a
function, or loaded two modules from one file. The three rewrite rules match
one call at module scope, so those files were copied unchanged on purpose.

**Mechanism.** A new `plugins/saga/scripts/bundled_fleet.py` inserts
`scripts/_bundled` on `sys.path` and imports the module by name. Every former
shim call site, including the journal-nudge hook, goes through it. The bundle
declaration the importer wrote was the modules named in those calls. It was
not the modules those modules load themselves. `jev_widen` loads
`typesafe_client` and `jev_verbs`. `typesafe_client` loads `retry_backoff`.
`tier_palette`, `tier_resolver`, and `staffing` read `staffing.json` from the
same directory. Those three modules and that data file are declared in
`fleet-bundle.json` (schema version 2). `models.json` is not. Fleet Core's
tier palette reads `staffing.json`.

**Generalizable rule.** A Fleet Core bundle is closed under `_load_sibling`
and under data files read by path from that directory. Declaring only the
modules the consumer names leaves the import one hop short, and the failure
shows up at the first call rather than at `--help`.

## Design calls

- Hooks moved from `plugins/saga/hooks/` to
  `plugins/saga/com.infiquetra.claude/hooks/`. A relative `parent/scripts`
  from the old location pointed at the adapter directory after the move.
  The hooks now climb two parents to the package root. `hooks.json` paths
  were already rewritten by the importer.
- `prompt_suggestion_hook.commands_root` uses
  `$CLAUDE_PLUGIN_ROOT/com.infiquetra.claude/commands` when the variable is
  set. Without it, the hook's own parent directory is the adapter, and
  `commands/` is the sibling it already was after the move.
- `/ceo-review` is an alias of `/founder-review`. One skill covers that
  capability. A second `SKILL.md` would describe the same engine twice.
- The pre-push hook still reads `tools/gate-manifest.json` from the
  repository being pushed, and stays quiet when the file is absent. The
  upstream manifest's steps are that repository's CI. They were not copied.
- `add-engine.sh` and the cross-runtime outcome harness were not carried.
  Both exec scripts that are not in the package at `acc99fe7`
  (`engine_onboarding.py`, `outcome.py`, `outcome_compat.py`).
- Local lifecycle checkouts stay `INFIQUETRA_SDLC_PATH`, then
  `INFIQUETRA_SDLC_ROOT`, then `~/workspace/infiquetra/infiquetra-sdlc`.
  That default was already an environment variable with a home-relative
  fallback. It was not changed.
- Package tests that quote forbidden board-write tokens used to live in the
  upstream repo's `tests/` directory, outside `plugins/`. They now live in
  the package, so the direct-write scan ignores the "names the op" class
  inside a `tests/` directory and still flags a direct GitHub mutation
  there. The gate-absence lint skips `tests/` on a directory scan for the
  same reason: the red fixture has to live in the package, and it must not
  become a shipped violation.

## Gate, and what was left for the lead

`scripts/bundle_fleet_module.py --check`, `scripts/sync_marketplace.py --check`,
`scripts/check_repo.py`, and `python3 -m pytest plugins/saga/tests -q` pass
(1414 passed, 9 skipped, after the frontmatter and fixture fixes).

`python3 -m unittest discover -s tests` fails three tests this unit did not
edit:

- `test_structural_premises_are_honestly_evaluated` asserts
  `plugins/saga` does not exist. That assertion is the premise this import
  retires. The brief forbids editing files outside the package, the port
  descriptor, this narrative, and a supersession note, so the assertion was
  left for the lead.
- The two template-sync tests fail locally because the sibling
  `infiquetra-sdlc` checkout has a Risk field the committed mission-control
  reference does not. They skip when that checkout is absent. They are not
  this package.

`python3 -m pytest plugins/*/tests -q` fails the same local template-sync
pair under `plugins/mission-control/tests/test_template_sync.py`, for the
same reason.
