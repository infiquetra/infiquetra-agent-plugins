# redis-channel

Portable Redis Streams bridge for one agent session. The process registers
the session, consumes an inbound stream, and publishes replies on an
outbound stream. A router on the other side speaks the same protocol
(`PROTOCOL.md`). This package does not speak Discord, voice audio, or any
one router's API.

The portable core is the `server/` package and the scripts under `scripts/`.
Claude Code's commands, coach agent, and Model Context Protocol (MCP)
registration live under `com.infiquetra.claude/`. The root
`.claude-plugin/plugin.json` only names paths into that adapter and into
`skills/`.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Portable Agent Plugins manifest |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only |
| [`server/`](server/) | MCP server: presence, inbound consumer, outbound producer, protocol models |
| [`scripts/mcp_server.py`](scripts/mcp_server.py) | Entrypoint every harness runs. Sources the deployment env file, then serves stdio |
| [`scripts/claude-channel.sh`](scripts/claude-channel.sh) | Launches `claude` with the channel's environment |
| [`scripts/install-claude-channel.sh`](scripts/install-claude-channel.sh) | Points `~/bin/claude-channel` at the newest cached wrapper |
| [`scripts/integ_test.py`](scripts/integ_test.py) | Live Redis integration. Skips unless `REDIS_CHANNEL_INTEG_HOST` and `REDIS_CHANNEL_INTEG_PASSWORD` are set |
| [`skills/redis-channel/SKILL.md`](skills/redis-channel/SKILL.md) | Agent Skill: the scripts, their flags, and the environment variable names |
| [`com.infiquetra.claude/`](com.infiquetra.claude/) | Claude adapter: eight commands, the coach agent, the MCP registration |
| [`PROTOCOL.md`](PROTOCOL.md) | Wire format |
| [`docs/registry.example.json`](docs/registry.example.json) | Example endpoint registry. The password is an environment variable name, not a value |
| [`docs/source-env.example.sh`](docs/source-env.example.sh) | Example env file the MCP entrypoint sources |

## Install the Python packages

`mcp` (1.x), `redis`, and `pydantic` are not vendored. `mcp` 2.x renamed
`mcp.server.fastmcp`, which this server imports, so the pin stays on 1.x.

```bash
python3 -m pip install 'mcp>=1,<2' 'redis>=5' 'pydantic>=2.12'
```

`--help` works without them:

```bash
python3 scripts/mcp_server.py --help
python3 -m server --help
python3 scripts/integ_test.py --help
```

Run those from the package root, the directory that contains `plugin.json`.
`python3 -m server` needs that directory on `PYTHONPATH` or as the current
directory. `scripts/mcp_server.py` puts the package root on `sys.path` itself.

## How a harness reaches it

Claude Code installs this package from the `infiquetra-agent-plugins`
marketplace. The install is the package root, so the portable core and the
Claude adapter travel together. The MCP registration runs
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py`.

OpenCode, Gemini CLI, Muse, and Hermes read
[`skills/redis-channel/SKILL.md`](skills/redis-channel/SKILL.md) and run the
scripts it names.

Any harness that can run a program runs the same entrypoint:

```bash
python3 scripts/mcp_server.py
```

That process sources `~/.claude/channels/redis-channel/source-env.sh` when
the file exists, then serves MCP on stdin and stdout. `python3 -m server`
does not source the file. Use it when the password variable is already
exported, including the live integration harness.

## Configuration

`~/.claude/channels/redis-channel/registry.json` lists endpoints. The Redis
password is not in that file. `redis_password_env` names the environment
variable that holds it. An example name is `MY_REDIS_PASSWORD`. See
[`docs/registry.example.json`](docs/registry.example.json) and
[`docs/source-env.example.sh`](docs/source-env.example.sh).

| Variable | Meaning |
|---|---|
| `CLAUDE_CHANNEL_AUTO_CONNECT` | `1` registers at startup. Any other value leaves the server idle until a connect tool call |
| `CLAUDE_CHANNEL_ENDPOINT` | Endpoint name used when auto-connect is on |
| `CLAUDE_SESSION_NAME` | Session name override. Otherwise the server derives one from the working directory |
| `REDIS_CHANNEL_KEYCHAIN_ITEM` | Optional macOS keychain item. `scripts/claude-channel.sh` reads it only when `REDIS_CHANNEL_PASSWORD_ENV` is also set |
| `REDIS_CHANNEL_PASSWORD_ENV` | Environment variable that receives that keychain value |
| `REDIS_CHANNEL_INTEG_HOST` | Host for `scripts/integ_test.py`. No default. Unset skips the run |
| `REDIS_CHANNEL_INTEG_PASSWORD` | Password for that run. No default. Unset skips the run |
| `REDIS_CHANNEL_INTEG_PORT` | Port for that run. Default `6379` |
| `REDIS_CHANNEL_INTEG_VAR` | Env var name the server's registry reads during the integration run. Default `REDIS_CHANNEL_INTEG_PASSWORD` |
| `CLAUDE_BIN` | `claude` executable for the wrapper |
| `CLAUDE_CHANNEL_PRODUCTION` | `1` omits the development-channel flags in the wrapper |
| `CLAUDE_CHANNEL_PLUGIN_REF` | Plugin ref for those flags. Default `plugin:redis-channel@infiquetra-agent-plugins` |

## Claude commands

These exist only in the Claude adapter:

| Command | What it asks the server to do |
|---|---|
| `/redis-channel-connect` | Register presence and start the inbound consumer |
| `/redis-channel-disconnect` | Remove the session |
| `/redis-channel-list` | List live sessions |
| `/redis-channel-status` | Report this session's connection |
| `/redis-channel-rename` | Change the session name |
| `/redis-channel-configure` | Write an endpoint into the local registry |
| `/redis-channel-mode` | Set the router-side routing override for this session |
| `/redis-channel-setup` | Symlink `~/bin/claude-channel` and scaffold the env file and registry if they are absent |

The wrapper symlink auto-refreshes when it already points at a redis-channel
cache directory under either `infiquetra-agent-plugins` or
`infiquetra-plugins`. A symlink that points anywhere else is left alone.

## Tests

```bash
python3 -m pytest plugins/redis-channel/tests -q
```

The live integration is separate and skips unless both
`REDIS_CHANNEL_INTEG_HOST` and `REDIS_CHANNEL_INTEG_PASSWORD` are set:

```bash
python3 plugins/redis-channel/scripts/integ_test.py
```

## Known limitation

Claude Code background sessions (`claude --bg`) drop channel notifications
when the development-channel flag is not carried into the background
process. Foreground sessions receive them. The server itself does not
distinguish the two. The wrapper passes the flag through unless
`CLAUDE_CHANNEL_PRODUCTION=1`.
