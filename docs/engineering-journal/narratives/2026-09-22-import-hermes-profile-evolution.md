# Importing hermes-profile-evolution

Date: 2026-09-22
Author: hermes-profile-evolution import unit
Related entries:

- [Custody move and retirement of infiquetra-claude-plugins](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md) — the recipe this import followed.

## Context

`hermes-profile-evolution` had no copy in this catalog. Upstream
`infiquetra-claude-plugins` at `acc99fe7` ships it as version 0.1.4: one
command, one PreToolUse hook, and one Python request script. The approved
plan scores it as a retirement candidate and still says to carry it, small,
so a later retirement is an operator decision rather than a missing package.
This unit ports it. It does not retire it.

The package is authored here from 0.1.5. There is no `PROVENANCE.json`.

## Narrative

### What the importer could already do

`scripts/import_vendor_package.py` read the pin through `git show` and
classified 12 portable-core files, 4 Claude-adapter files, and 2 generated
manifests. Nothing was dropped. The hook command in
`com.infiquetra.claude/hooks/hooks.json` was re-anchored from
`${CLAUDE_PLUGIN_ROOT}/hooks/profile_edit_guard.py` to
`${CLAUDE_PLUGIN_ROOT}/com.infiquetra.claude/hooks/profile_edit_guard.py`.
The command still runs `${CLAUDE_PLUGIN_ROOT}/scripts/profile_request.py`,
because `scripts/` stays at the package root.

Neither Python file mentions `fleet_commons_shim`. No `fleet-bundle.json`
was generated, and none was added by hand. A module this package does not
load is not a module the bundle should declare.

### The script stays beside the skill, not inside it

The four skill-scoped harnesses (OpenCode, Gemini CLI, Muse, Hermes) install
a skill directory. The request script lives at `scripts/profile_request.py`,
which is outside `skills/hermes-profile-evolution/`. Copying it under the
skill would make a second source for the same program. The skill instead
names that one path and says a copy of the skill directory alone does not
include the script.

`ports/hermes-profile-evolution.json` records the same geometry:
`assessment.entrypoints` is `scripts/profile_request.py` and
`assessment.skill_units` is `skills/hermes-profile-evolution`. A skill-scoped
assessment will block its invocation stage for this entrypoint, because the
script is not inside the skill unit. That block is the placement telling the
truth. It is not a missing file.

### What an assessment must strip, and what it must refuse to run

The two environment variables are `HERMES_TEAM_MIMIR_ROOT` (the hook) and
`HERMES_PROFILE_REQUEST_SSH_ALIAS` (the request script). Neither holds a
secret. Both point a process at a live checkout or a live Secure Shell alias.
`assessment.credential_prefixes` is the list an assessment removes from the
environment before it starts a subprocess, so the prefixes are
`HERMES_TEAM_MIMIR_` and `HERMES_PROFILE_REQUEST_`. Leaving them unset in the
descriptor would have meant an assessment inherited the operator's route.

Neither `os.environ.get` call passes a default. Unset, the script runs
`hermes` on `PATH`. Unset, the hook walks upward from the working directory
for `profiles/` and `scripts/classify_profile_change.py`, and allows the edit
when it finds neither. There is no host constant to delete.

`suggest`, `reply`, and `resume` submit a proposal, so they are
`assessment.mutating_operations`. `status` and `census` are reads and are
not in that list. `--help` names none of the three, so the credential-free
entrypoint run is still allowed.

### Tests

Upstream's repository-wide `tests/test_hermes_profile_evolution.py` and
`tests/test_hermes_profile_evolution_docs.py` are the only rows the triage
assigns to this package. Both are carried under
`plugins/hermes-profile-evolution/tests/`. No test was dropped. The rewrites
are path rewrites: the hook, the command, and `hooks.json` load from
`com.infiquetra.claude/`, and the release-surface test reads this
repository's marketplace instead of assuming the tests still sit in the
upstream `tests/` directory.

`test_profile_request_entrypoint.py` is new. The repository entrypoint
suite skips a package that has no provenance manifest, which is every
package authored here. The new test runs `python3 scripts/profile_request.py
--help` with both routing prefixes removed, and it checks the skill names
the script, the five actions, and the two variables.

The classifier fixture returns the resolved temporary root. The hook passes
`Path.resolve()` into the classifier argv, and a temporary directory whose
parent is a symlink would otherwise fail the argv comparison on this
machine while passing on Linux.

### Documents

`README.md` is rewritten for this repository. It describes the portable
script, the Claude adapter, and how Claude Code, the four skill-scoped
harnesses, and the other harnesses reach the script. The sentence that the
hook does not claim shell-command interception stays, because that is still
the hook's boundary and the carried contract test requires the sentence.

`docs/development.md` no longer tells a reader to run `uv`, the upstream
`tests/test_hermes_profile_evolution.py` paths, or
`scripts/validate_plugins.py`. Those paths are the upstream repository.
`docs/usage.md` documents version 0.1.5 and the marketplace install. The
diagram, its renderer receipt, and the usage command examples are unchanged,
so the documentation tests still bind the checked-in PNG and SVG.

No file under `docs/evidence/` was written. This package had no
compatibility matrix here to supersede. A matrix binds to a released
version, and 0.1.5 has not been assessed. That run is a later unit.

The adapter manifest's `repository` field still names
`infiquetra-claude-plugins`. That file is the relocated upstream manifest.
The root `.claude-plugin/plugin.json` names
`infiquetra-agent-plugins`, which is the manifest Claude reads. The voice
adapter has the same split.

## Outcome

Version 0.1.5 is the authored cut of upstream 0.1.4. The three manifests
agree, and `scripts/sync_marketplace.py` lists the package from the root
Claude manifest. The Python files are the upstream bytes. Retirement remains
an operator call.

The package tests pass: 40 tests. `scripts/bundle_fleet_module.py --check`,
`scripts/sync_marketplace.py --check`, `scripts/check_repo.py`, and
`git diff --check` pass. `python3 -m unittest discover -s tests` reports 2
failures, and `python3 -m pytest plugins/*/tests -q` reports the same pair
under `plugins/mission-control/tests/test_template_sync.py`. Both compare
mission-control's checked-in template reference with a sibling checkout of
`infiquetra-sdlc`, which currently has a Risk field the reference does not.
This import does not edit that reference. The tests skip when the sibling
checkout is absent, which is the continuous-integration case.

## References

- Upstream pin: `infiquetra-claude-plugins` `acc99fe71e25ad8a898eace7033051a7f1c3079e`
- Package: `plugins/hermes-profile-evolution/`
- Descriptor: `ports/hermes-profile-evolution.json`
- Triage row: `tests/test_hermes_profile_evolution.py`, `tests/test_hermes_profile_evolution_docs.py` (carry)
