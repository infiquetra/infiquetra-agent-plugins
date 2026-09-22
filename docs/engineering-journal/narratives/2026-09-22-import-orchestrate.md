# Import orchestrate as an authored package

Date: 2026-09-22
Author: agent
Related entries:

- `docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md` (unit U3)
- `plugins/orchestrate/CHANGELOG.md` (6.0.1)

## Context

Orchestrate is in daily use on this machine, so the custody move imports it
instead of retiring it. Upstream is `infiquetra-claude-plugins` at `acc99fe7`,
plugin version 6.0.0. This catalog authors it from that commit. There is no
`PROVENANCE.json`.

## Narrative

### The import script's shim warning was a comment

Evidence: `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py` line
2637 is a comment that names `fleet_commons_shim` to explain why the
saga-install resolver is hand-rolled. `scripts/import_vendor_package.py` treats
any occurrence of that string in a `.py` file as a shim import
(`SHIM_MENTION`). The dry run and the real import both exited non-zero and
named that file. `fleet_commons_shim.load(...)` does not occur, so no module
name was collected and no `fleet-bundle.json` was generated.

Mechanism: the detector is a substring test, applied before the three rewrite
rules, which only match a real `load` call. A comment takes the unresolved
path. The file was copied unchanged, which is the right bytes.

Generalizable rule: a substring match on a shim name is not a module load.
Do not add a Fleet Core bundle, and do not rewrite the file to import one,
when the only match is a comment that explains why the shim is not used.

Design call: this is not the plan's "transform is wrong" stop. The transform
did not rewrite the file. The non-zero exit is a false alarm. The package
ships no `fleet-bundle.json`.

### The companion launcher is the sibling package

Evidence: `_agent_launcher_script` in the same file. Upstream also searched
`CLAUDE_PLUGIN_ROOT` and versioned cache directories. The unit brief says the
default is `plugins/agent-launcher` and `AGENT_LAUNCHER_ROOT` is the override,
and that a `~/.claude/plugins/cache/...` path is not a default.

Mechanism: the first candidate after the environment variable was already the
sibling of this package (`plugins/orchestrate`'s parent, then
`agent-launcher`). The cache globs were a second and third chance. Removing
them leaves the sibling and the override. The version floor is read from
whichever manifest states `dependencies`. After the import that is
`com.infiquetra.claude/plugin.json`, because the root
`.claude-plugin/plugin.json` carries paths and the version only. A companion's
own version is read from its portable `plugin.json`, then the adapter
manifest, then `.claude-plugin/plugin.json`, so the sibling catalog package
and an older Claude-shaped tree both answer.

Generalizable rule: when a generated Claude manifest is paths-only, a reader
that used to find `dependencies` on `.claude-plugin/plugin.json` has to follow
the manifest that still states them. Do not copy `dependencies` back onto the
paths-only file to keep the old reader working.

Design call: this catalog's `plugins/agent-launcher` is version 1.0.0 and does
not define the names Orchestrate 6.0.0 execs (`guard_pane_before_write` among
them). With the variable unset, ingest refuses that sibling and read-only
commands still answer. The test suite sets `AGENT_LAUNCHER_ROOT` to a frozen
copy of upstream agent-launcher 1.7.0 (and its `composer.py`) from `acc99fe7`,
because that is the companion the suite was written against. Production
resolution does not point at the fixture.

### Saga's run record is not in this catalog yet

Evidence: `_run_record_candidates` still looks for
`plugins/saga/scripts/run_record.py`, then install caches. `ORCHESTRATE_RUN_RECORD`
overrides that. Saga is a separate import unit and is not on this branch.

Mechanism: the driver loads saga's module by path. The tests do the same
through `orchestrate_support.py`. A frozen copy of `run_record.py` from
`acc99fe7` lives at `plugins/orchestrate/tests/fixtures/saga_run_record.py`.
The suite points `ORCHESTRATE_RUN_RECORD` at the sibling when it exists and at
the fixture otherwise.

Generalizable rule: do not vendor another package's module into the portable
core so its tests can run. Pin the test process at a fixture, and leave the
production default as the sibling package plus the environment variable.

Design call: the saga install-cache walk stays. The brief's cache prohibition
is the agent-launcher default. Saga is how an installed copy is found on a
machine that does not have this catalog's `plugins/saga` yet. Removing that
walk would change behavior for those machines. Three tests skip until saga or
`fleet_commons.tier_resolver` is actually here:

- `tests/test_review_loop_end_to_end.py` needs saga's `review_consensus.py`.
- `test_stage_skills_do_not_invoke_retired_transport_as_launch_path` reads
  saga stage skills. That premise is the upstream repository layout.
- `test_fleet_commons_internal_team_execution_routing_unaffected` imports
  `fleet_commons.tier_resolver`, which this branch's fleet-core slice does
  not ship. The test does not call Orchestrate.

No test was deleted.

The triage table's orchestrate row omitted `test_orchestrate_review_loop.py`
and `test_orchestrate_review_transport.py`. The unit brief's
`tests/test_orchestrate*.py` includes them, so they are carried.

## Outcome

Package version 6.0.1. Portable core at `plugins/orchestrate/`, Claude command
under `com.infiquetra.claude/commands/`, root `.claude-plugin/plugin.json`
carries paths. `ports/orchestrate.json` is an authored descriptor (no
`source`, no `custody`). The orchestrate pytest suite: 619 passed, 3 skipped.

`python3 -m unittest discover -s tests` reports two failures in
`tests/test_mission_control_rule_audit.py` (`TemplateSyncAuditTests`). Both
call `sync_template_docs.check_reference()` against a local
`infiquetra-sdlc` checkout whose templates have drifted from mission-control's
reference. Those tests skip when that checkout is absent. This import does
not change mission-control or that reference.

## References

- Upstream pin `acc99fe71e25ad8a898eace7033051a7f1c3079e`
- `scripts/import_vendor_package.py` (`SHIM_MENTION`)
- `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`
- `plugins/orchestrate/tests/conftest.py`
