# Import redis-channel

Date: 2026-09-22
Author: agent (unit U3, worktree mg-redis-channel)
Related entries:

- [Custody move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md)

## Context

redis-channel had no prior port. Upstream `infiquetra-claude-plugins` at
`acc99fe7` carried it at version 0.5.2: an MCP server under `server/`, eight
commands, one agent, three shell/Python scripts, and nine contract tests in
the repository-wide `tests/` directory. The import script laid that out.
Several behaviours the script cannot see still pointed at the old repository,
a lab Redis host, and a hard-coded keychain item.

## Narrative

The dry run classified 22 portable-core files, 11 Claude-adapter files, and
2 generated manifests. Nothing imported `fleet_commons_shim`, so there is no
`fleet-bundle.json` and the Fleet Core bundler was not asked to copy a module.

The MCP server is the `server/` package, not a single file under `scripts/`.
The package note said the code stays under `scripts/`. Moving `server/` would
have broken `import server`, which every carried test uses. The code stayed
at `server/`. What moved is the Claude registration, to
`com.infiquetra.claude/mcp/servers.json`, in the same shape as `plugins/voice`:
`python3` plus `${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py`. The new
`scripts/mcp_server.py` is the launcher. It sources
`~/.claude/channels/redis-channel/source-env.sh` when that file exists, which
is what the old `.mcp.json` shell string did, and it answers `--help` before
importing `redis`, `mcp`, or `pydantic`.

FastMCP 1.x constructs its low-level server without a version, and
`create_initialization_options` then reports the `mcp` library version as
`serverInfo.version`. `build_app` assigns `server.__version__` onto that
server. The packaging check does not execute the server. It regex-matches a
`"serverInfo"` literal in the file the MCP arguments name, so the same
number is also a literal in `scripts/mcp_server.py`. Upstream's
`server/__init__.py` said `0.5.0` while `plugin.json` said `0.5.2`. The
authored cut sets every site to `0.5.3`.

`mcp` 2.x removed `mcp.server.fastmcp`. The server and the carried tests
import that name. `requirements-plugin-tests.txt` therefore pins `mcp>=1,<2`
rather than an unpinned `mcp`, which on 2026-09-22 resolved to 2.2.0 and
raised `ModuleNotFoundError` at import. `fakeredis`, `pydantic`, and `redis`
were added on the same list because the carried tests import them. Each test
module skips when the import it needs is missing, so a machine without those
packages does not fail the suite.

The integration harness defaulted its host to `olympus-bus.infiquetra.com`
and indexed `HERMES_REDIS_PASSWORD` at import time. It now skips, exit 0,
unless `REDIS_CHANNEL_INTEG_HOST` and `REDIS_CHANNEL_INTEG_PASSWORD` are both
set. `scripts/claude-channel.sh` read keychain item `hermes-redis-password`
into `HERMES_REDIS_PASSWORD`. It now reads a keychain item only when
`REDIS_CHANNEL_KEYCHAIN_ITEM` and `REDIS_CHANNEL_PASSWORD_ENV` are both set.

Claude's plugin cache directory is named for the marketplace. This catalog's
marketplace is `infiquetra-agent-plugins`. Existing symlinks point at
`infiquetra-plugins`. Auto-refresh and the install script accept both, and
the carried tests still cover the old name. A new test covers the new name.
The wrapper's default plugin ref follows the new marketplace. `CLAUDE_CHANNEL_PLUGIN_REF`
still overrides it.

The adapter manifest kept the upstream repository URL because
`relocate-claude-manifest` preserves bytes. It now names
`infiquetra-agent-plugins`, matching the generated root Claude manifest.
Voice's adapter still names the old repository. That was not this package's
to edit.

No upstream test was dropped. The protocol test's path bootstrap assumed the
old repository root. `tests/conftest.py` inserts this package root instead.
One fixture's working-directory value was a personal absolute path. It is
now `/home/operator/example-project`.

## Outcome

The package is authored here at 0.5.3. Fleet Core was not involved. The live
integration does not run unless its two variables are set, and it was not
run in this import.

## References

- Upstream pin `acc99fe7` (`infiquetra-claude-plugins`)
- `plugins/redis-channel/`
- `ports/redis-channel.json`
- `scripts/import_vendor_package.py`
- `tests/test_claude_plugin_packaging.py` (`serverInfo` literal, `${CLAUDE_PLUGIN_ROOT}` path)
