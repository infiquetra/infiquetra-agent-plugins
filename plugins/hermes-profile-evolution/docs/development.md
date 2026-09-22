# Develop the Claude Code adapter

Keep this plugin thin. Claude Code-specific command and hook behavior belongs
here. Classification policy belongs in Team Mimir, and dialogue or profile
behavior belongs in the Hermes producer.

## Local checks

From the repository root:

```bash
python3 -m pytest plugins/hermes-profile-evolution/tests -q
```

The request script is `plugins/hermes-profile-evolution/scripts/profile_request.py`.
The file-edit hook is
`plugins/hermes-profile-evolution/com.infiquetra.claude/hooks/profile_edit_guard.py`.

Tests should use fake producer responses and temporary Team Mimir checkouts.
They must not need live credentials or contact a real profile.

## Compatibility and release

The adapter consumes the canonical Hermes version-1 envelope and exact health
response. A producer schema change requires a reviewed compatibility update;
do not invent optional fields or an implicit fallback.

For a real release, set the same version in `plugin.json`,
`.claude-plugin/plugin.json`, `com.infiquetra.claude/plugin.json`, and
`CHANGELOG.md`, then run `python3 scripts/sync_marketplace.py`. Run the package
tests and `python3 scripts/check_repo.py`, install through this repository's
marketplace, restart Claude Code, and verify the loaded manifest. Installed
plugin bytes are not the maintained source.

See [usage](usage.md), [architecture](architecture.md), and
[troubleshooting](troubleshooting.md).
