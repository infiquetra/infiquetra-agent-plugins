# Importing deploy as an authored package

Date: 2026-09-22
Author: agent
Related entries:

- [Custody move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md)

## Context

Unit U3 imports the deploy plugin from `infiquetra-claude-plugins` at `acc99fe7`
into this worktree (`mg/deploy`) and leaves it authored here. Deploy had no
prior port. The import script classified twelve upstream files and generated
the two manifests. Nothing in the package reaches Fleet Core.

## Narrative

The brief said upstream had no skill and to author `skills/deploy/SKILL.md`.
The pin does have a skill: `plugins/deploy/skills/deploy-state/SKILL.md` at
`acc99fe7`, and the import copied it to the package root under `skills/`. The
four slash commands are four ways of using that one capability (promote,
status, notes, hotfix). A second skill named `deploy` would describe the same
scripts under a second name, and the commands would still tell Claude to load
`deploy-state`. The imported skill stays the capability. Its description is now
one line, because the repository's frontmatter reader stores a `|` block
scalar as the character `|` and a harness that uses the same reader would see
no description. The body now says how to run each script, every flag, and the
credential variables `GH_TOKEN` and `GITHUB_TOKEN` by name only.

The scripts moved from `scripts/` at the package root into
`skills/deploy-state/scripts/`. That is a path change, not a behaviour change:
`mint_tag.py`, `query_deployments.py`, and `preview_release_notes.py` are the
upstream files. The reason is the assessment harness. OpenCode, Gemini CLI,
Muse, and Hermes install a skill directory and not the package
(`scripts/assess_clients.py`, `skill_scoped=True`). An entrypoint that does not
sit inside a declared skill unit is reported as undeliverable and the
invocation stage is blocked before it runs. Leaving the scripts at the package
root would make those four harnesses unable to run the thing the skill tells
them to run. Package-scoped clients still receive the whole tree, so the same
files are at `skills/deploy-state/scripts/` under the installed root. Claude
commands name that path with `${CLAUDE_PLUGIN_ROOT}`.

No `${CLAUDE_PLUGIN_ROOT}` path in the upstream package pointed at a surface
the import moved. The token did not occur at all. The paths that were wrong
were checkout-relative (`plugins/deploy/scripts/...` and
`deploy/skills/deploy-state/SKILL.md`), which name a directory layout rather
than the installed package. Those now point at the skill inside the installed
root.

The saga handoff script stays `plugins/saga/scripts/deploy_handoff.py`. It is
not part of deploy, upstream or here, and both catalogs keep saga as a sibling
package. Deploy does not vendor it. When the saga import moves that file, the
sentence in this skill has to move with it. That is a coupling, and it is
called out in the changelog rather than papered over with a path that does not
exist yet.

`preview_release_notes.py` does not reject a non-Infiquetra owner.
`mint_tag.py` and `query_deployments.py` do. The notes script takes `--repo` as
`owner/name` and calls `gh` with it. Tightening that would change portable
behaviour to match the skill's prose. This import does not do that.

The port descriptor is authored mode (schema version 4): no `source`, no
`custody`. Credential prefixes are `GH_` and `GITHUB_`, because the scripts
shell out to `gh` and do not read a variable themselves. Mutating tokens are
`push` and `--force-unhealthy`. The assessment checker intersects argv tokens
with that set. `--help` and a dry-run mint contain neither, so those commands
stay read-only. A recorded command that includes either token next to one of
the three script names is rejected. The checker cannot see the `git push`
inside `mint_tag.py`, so the token `push` only fires when it is on the
recorded command line. That is the limit of the checker, recorded here so a
later assessment does not treat a dry-run as a classified write or a bare mint
as one the checker already caught.

The adapter `plugin.json` keeps the repository URL from the relocated upstream
manifest (`infiquetra-claude-plugins`). The generated root Claude manifest
points at this repository, which is what the import script writes. Versions
agree at 0.2.3. The adapter URL was left so the relocated file stays the
upstream manifest plus the required version bump.

No Fleet Core module is loaded. `python3 scripts/bundle_fleet_module.py` had
nothing to generate for this package. No test was dropped. The one upstream
contract file, `tests/test_deploy_plugin.py`, was rewritten onto the package
layout and gained the `--help` run.

## Outcome

Deploy 0.2.3 is authored here. The skill directory is enough for a skill-scoped
harness to mint, query, and preview. Claude commands and the release
orchestrator are under the adapter. The marketplace entry is generated.

## References

- Upstream pin `acc99fe7`, plugin version 0.2.2
- `plugins/deploy/CHANGELOG.md` entry 0.2.3
- `ports/deploy.json`
- `scripts/assess_clients.py` skill-scoped placement
