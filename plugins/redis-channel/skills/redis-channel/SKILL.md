---
name: redis-channel
description: Run the redis-channel Redis Streams bridge. Use when connecting an agent session to an external router over Redis, launching the Model Context Protocol server, or checking the live integration harness.
compatibility: python>=3.12
---

# redis-channel

A portable Redis Streams bridge. One process registers an agent session in
Redis, consumes an inbound stream, and publishes replies on an outbound
stream. Any router that speaks `PROTOCOL.md` can sit on the other side.
The server does not talk to Discord, voice audio, or a specific router.

Claude Code also installs slash commands and a coach agent from
`com.infiquetra.claude/`. This skill is the way every other harness reaches
the same scripts.

## Install

The server imports `mcp` (1.x; 2.x removed `mcp.server.fastmcp`), `redis`,
and `pydantic`. They are not vendored. From the package root (the directory
that contains `plugin.json`):

```bash
python3 -m pip install 'mcp>=1,<2' 'redis>=5' 'pydantic>=2.12'
```

`--help` on the scripts below does not import those packages.

## Model Context Protocol server

```bash
python3 scripts/mcp_server.py
python3 scripts/mcp_server.py --help
```

With no arguments the process speaks Model Context Protocol (MCP) on stdin
and stdout until stdin closes. Before it serves, it sources
`~/.claude/channels/redis-channel/source-env.sh` when that file exists.
The file may export the password variable named by the registry. This
script does not name a keychain item.

`python3 -m server` starts the same server and does not source that file.
Use it when the password variable is already in the environment.

The password itself is never stored in the registry. `registry.json` names
the environment variable in `redis_password_env`. An example name is
`MY_REDIS_PASSWORD`. A copy of the shape is `docs/registry.example.json`.
A copy of the env file is `docs/source-env.example.sh`.

## Claude session wrapper

`scripts/claude-channel.sh` execs the `claude` binary with the channel's
environment. `scripts/install-claude-channel.sh` points `~/bin/claude-channel`
at the newest cached copy of that wrapper.

```bash
bash scripts/claude-channel.sh --help
bash scripts/install-claude-channel.sh --help
```

| Flag | Effect |
|---|---|
| `--session-name NAME` | Export `CLAUDE_SESSION_NAME`. Name must match `^[a-z0-9][a-z0-9_-]{0,63}$` |
| `--endpoint NAME` | Export `CLAUDE_CHANNEL_ENDPOINT` |
| `--cwd PATH` | Change directory before exec |
| `--help` | Print usage and exit |
| `--` | Pass the rest through to `claude` |

Other flags are passed through to `claude`.

| Variable | Effect |
|---|---|
| `CLAUDE_BIN` | `claude` executable. Default: `command -v claude` |
| `CLAUDE_CHANNEL_PRODUCTION` | `1` omits the development-channel flags |
| `CLAUDE_CHANNEL_PLUGIN_REF` | Plugin ref for those flags. Default: `plugin:redis-channel@infiquetra-agent-plugins` |
| `CLAUDE_CHANNEL_AUTO_CONNECT` | The wrapper always exports this as `1` |
| `REDIS_CHANNEL_KEYCHAIN_ITEM` | macOS keychain item to read. Ignored unless the next variable is also set |
| `REDIS_CHANNEL_PASSWORD_ENV` | Environment variable that receives the keychain value |

## Live integration

`scripts/integ_test.py` drives the server against a real Redis. It exits 0
without connecting when either variable is unset.

| Variable | Effect |
|---|---|
| `REDIS_CHANNEL_INTEG_HOST` | Redis host. Required, no default |
| `REDIS_CHANNEL_INTEG_PASSWORD` | Redis password. Required, no default |
| `REDIS_CHANNEL_INTEG_PORT` | Redis port. Default `6379` |
| `REDIS_CHANNEL_INTEG_VAR` | Env var name the server's registry reads. Default `REDIS_CHANNEL_INTEG_PASSWORD` |

```bash
python3 scripts/integ_test.py --help
```

## Claude Code only

The marketplace entry installs this package root. Commands live in
`com.infiquetra.claude/commands/` (`connect`, `disconnect`, `list`, `rename`,
`configure`, `mode`, `setup`, `status`). The coach agent is
`com.infiquetra.claude/agents/redis-channel-coach.md`. The MCP launch is
`com.infiquetra.claude/mcp/servers.json`, which runs `scripts/mcp_server.py`.
