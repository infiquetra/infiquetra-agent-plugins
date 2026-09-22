# Changelog

## [0.1.5] - 2026-09-22

### Changed

0.1.5 — imported from infiquetra-claude-plugins@acc99fe7 (upstream 0.1.4); authored here from this commit; no provenance manifest from now on.

- The Claude command, PreToolUse hook, and adapter manifest now live under `com.infiquetra.claude/`. The hook command is `${CLAUDE_PLUGIN_ROOT}/com.infiquetra.claude/hooks/profile_edit_guard.py`. The request script stays at `scripts/profile_request.py`, which is the path the command and the skill run.
- `README.md` is target-owned. It describes the portable core, the Claude adapter, and how each harness reaches the script. The statement that this plugin does not claim shell-command interception stays, because that boundary is still the hook's boundary.
- `docs/development.md` local checks now run this repository's pytest path. The upstream commands assumed `uv`, a repository-root `tests/` directory, `hooks/profile_edit_guard.py` at the package root, and `scripts/validate_plugins.py`.
- `docs/usage.md` documents source version `0.1.5` and installs the package from this repository's marketplace.
- `scripts/profile_request.py` and `com.infiquetra.claude/hooks/profile_edit_guard.py` are the upstream bytes. Neither imports Fleet Core, so there is no `fleet-bundle.json` and no `fleet_commons_shim` bootstrap to rewrite.
- `HERMES_TEAM_MIMIR_ROOT` and `HERMES_PROFILE_REQUEST_SSH_ALIAS` are documented. Neither is given a host default. Unset, the hook searches upward from the working directory, and the request script runs `hermes` on `PATH`.

### Tests

No upstream test was dropped.

`tests/test_hermes_profile_evolution.py` and `tests/test_hermes_profile_evolution_docs.py` are carried from the upstream repository-wide `tests/` directory into `plugins/hermes-profile-evolution/tests/`.

- The guard, the command, and `hooks.json` load from `com.infiquetra.claude/` instead of the package root.
- The release-surface test reads this repository's marketplace from the repository root and checks that the portable manifest, the root Claude manifest, the adapter manifest, and the marketplace entry state one version. It no longer assumes the tests live in the upstream `tests/` directory, or that the version is still `0.1.4`.
- `test_profile_request_entrypoint.py` runs `python3 scripts/profile_request.py --help` with `HERMES_PROFILE_REQUEST_*` and `HERMES_TEAM_MIMIR_*` removed from the environment, and checks that the skill names the script, its actions, and those two variables.

## [0.1.4] - 2026-08-09

### Fixed

- Allow the producer's bounded 30-second network request to finish before the
  Claude Code adapter exits.
- Convert launch and timeout failures into the existing generic service-unavailable error.

## [0.1.3] - 2026-08-09

### Fixed

- Bind the explanatory diagram's SVG source and PNG render to checked SHA-256
  digests and enforce the renderer receipt in the documentation test.

## [0.1.2] - 2026-08-08

### Documentation

- Add comprehensive usage, architecture, development, portability, and
  troubleshooting guidance for the existing Claude Code profile-evolution
  front door.

## [0.1.1] - 2026-08-02

### Fixed

- Match Hermes reply-message validation: reject whitespace-only messages and accept messages up to 16,384 characters.

## [0.1.0] - 2026-08-01

### Added

- Add the Claude Code request-only surface for Hermes target-sovereign profile evolution.
