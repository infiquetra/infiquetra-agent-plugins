#!/bin/sh
# Example per-deployment env file for redis-channel.
#
# Install at ~/.claude/channels/redis-channel/source-env.sh
# scripts/mcp_server.py sources this file (via a shell `.`) before starting the
# server, so any `export` here lands in the server's environment. Claude's
# registration is com.infiquetra.claude/mcp/servers.json, which runs that script.
#
# The env var name MUST match your registry.json's `redis_password_env` field.
# This file is per-deployment — the plugin itself is router-agnostic and never
# references specific env var names.

# Example: source the password from macOS keychain.
# Replace `my-redis-password` with the keychain item name you actually use,
# and replace `MY_REDIS_PASSWORD` with whatever name your registry expects.
if command -v security >/dev/null 2>&1; then
    pwd="$(security find-generic-password -s 'my-redis-password' -w 2>/dev/null)"
    if [ -n "$pwd" ]; then
        export MY_REDIS_PASSWORD="$pwd"
    fi
fi

# Linux alternative: read from a chmod-600 file.
# [ -r ~/.config/redis-channel/password ] && export MY_REDIS_PASSWORD="$(cat ~/.config/redis-channel/password)"

# Other env vars worth setting here (optional):
# export CLAUDE_CHANNEL_AUTO_CONNECT=1
# export CLAUDE_CHANNEL_ENDPOINT=default
