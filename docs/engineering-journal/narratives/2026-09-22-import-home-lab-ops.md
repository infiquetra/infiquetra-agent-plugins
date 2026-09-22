# Import home-lab-ops

Date: 2026-09-22
Author: agent
Related entries:

- `docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md`

## Context

Unit U3 for `home-lab-ops`. The package was read once from
`infiquetra-claude-plugins` at `acc99fe7` (upstream 1.2.1) and is authored
here from 1.2.2. No Fleet Core module. No provenance manifest.

## Narrative

The import classified 116 portable-core files, 2 Claude-adapter files (the
agent and the relocated Claude manifest), 0 dropped, and 0 excluded. It
generated the root Claude manifest and the portable `plugin.json`. The
upstream pin does not contain a `.venv`. A virtual environment exists only
as an untracked directory in the upstream working tree, and the import reads
the commit, so that directory was never a candidate. The import also refuses
the directory name `.venv` if a later pin tracks one.

Three files named the private infrastructure checkout with a machine-specific
layout: the package README, `team_scaffold/cli.py`, and the
`materialize_specs.py` usage example. They now read `HOME_LAB_ROOT` (default
`~/home-lab`). `cli.py` also reads `INFIQUETRA_CONTEXT_LIBRARY` (default
`~/infiquetra-context-library`). A fourth, `tests/test_modules.py`, repeated
the context-library path and skipped only when that directory was absent,
which is true on this machine and false in CI for the wrong reason. Stamp
tests skip when `INFIQUETRA_CONTEXT_LIBRARY` is unset.

The publication check rejects a private-key header even when the body is
`change-me`, and it rejects a one-token assignment on a key that contains
`token` or `secret`. Two of those hits were real example values and became
`change-me`. The shared-infra vault example dropped the key armor and kept
the field name. The `discord_token_var` values could not change: the
validator requires `vault_discord_bot_token_<persona>`. Each of those lines
now says the value is a variable name, which is the check's own exemption
for a sentence about a credential, and the parsed YAML value is unchanged.
`repo_stamp` writes the same note so a newly stamped file has the same
shape.

The operational skills still name the cluster they were written for. That
text was already public in the upstream repository. The package README does
not repeat the address map. Replacing the skills with placeholders would
throw away the procedures the package exists to carry. A later pass can
split site notes out of the skills if publication policy requires it.

Repo-wide upstream tests that mention the package
(`test_agent_preamble_identity.py`, `test_agent_tiering.py`,
`test_release_triad.py`) stay with the repository-wide triage. They are not
this package's contract. The three generator tests moved from
`skills/team-scaffold/scripts/tests/` to `plugins/home-lab-ops/tests/`.

The launcher is `skills/team-scaffold/scripts/team-scaffold`. Running
`cli.py` as a file fails because the package uses relative imports. The
launcher puts the scripts directory on `sys.path` and calls `main`.

`credential_prefixes` is empty on purpose. The Python commands do not read
a credential from the environment. Vault material is a file the operator
passes. The empty list is named in `declared_none` so the assessment does
not treat "strip nothing" as an omission.

## Outcome

Version 1.2.2. Authored port descriptor at `ports/home-lab-ops.json`. No
compatibility matrix: the ten-client run is a later unit, and a version
with no matrix is that unit's job once it binds evidence to a release.

## References

- Upstream pin `acc99fe71e25ad8a898eace7033051a7f1c3079e`
- `plugins/home-lab-ops/CHANGELOG.md`
- `plugins/home-lab-ops/skills/team-scaffold/scripts/team_scaffold/paths.py`
