# Develop the Claude Code adapter

Keep this plugin thin. Claude Code-specific command and hook behavior belongs
here. Classification policy belongs in Team Mimir, and dialogue or profile
behavior belongs in the Hermes producer.

## Local checks

From the repository root:

```bash
uv sync --locked --extra dev
uv run pytest -q \
  tests/test_hermes_profile_evolution.py \
  tests/test_hermes_profile_evolution_docs.py
uv run ruff check \
  plugins/hermes-profile-evolution \
  tests/test_hermes_profile_evolution.py \
  tests/test_hermes_profile_evolution_docs.py
uv run mypy plugins/hermes-profile-evolution/scripts/profile_request.py \
  plugins/hermes-profile-evolution/hooks/profile_edit_guard.py
uv run python scripts/validate_plugins.py
```

Tests should use fake producer responses and temporary Team Mimir checkouts.
They must not need live credentials or contact a real profile.

## Compatibility and release

The adapter consumes the canonical Hermes version-1 envelope and exact health
response. A producer schema change requires a reviewed compatibility update;
do not invent optional fields or an implicit fallback.

For a real release, update `.claude-plugin/plugin.json`, `CHANGELOG.md`, and the
marketplace through the repository's release-parity tooling. Run focused and
repository-wide checks, install through a supported repository method, restart
Claude Code, and verify the loaded manifest. Installed plugin bytes are not the
maintained source.

See [usage](usage.md), [architecture](architecture.md), and
[troubleshooting](troubleshooting.md).
