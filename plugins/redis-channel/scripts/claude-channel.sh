#!/usr/bin/env bash
# claude-channel — launch claude with a redis-channel session pre-configured.
#
# Thin wrapper around `claude`. Sets env vars + dev flags the plugin needs,
# then exec's claude. All standard claude flags (--bg, --print, --resume,
# --model, --remote-control, --worktree, etc.) pass straight through.
#
# Wrapper-owned flags:
#   --session-name NAME   exports CLAUDE_SESSION_NAME (regex-validated)
#   --endpoint NAME       exports CLAUDE_CHANNEL_ENDPOINT
#   --cwd PATH            cd before exec (load-bearing for auto-naming
#                         and Phase 5 programmatic spawn)
#   --help                show this help and exit
#
# Env knobs:
#   CLAUDE_BIN                  override claude binary path
#   CLAUDE_CHANNEL_PRODUCTION   if "1", omit --dangerously-* dev flags
#   CLAUDE_CHANNEL_PLUGIN_REF   override plugin ref for the dev-channel loader
#
# Backgrounding is claude's job: pass `--bg` to claude-channel and it goes
# straight to claude, which spawns a background agent and prints the agent
# ID + attach/logs/stop commands. Use `claude agents` to list and
# `claude attach <id>` to attach. The redis-channel session presence
# registry (cc-sessions:registry + hb keys) is the canonical discovery
# mechanism for external consumers (Phase 5+).
#
# Exit codes:
#   0  success (claude's exit code in foreground; claude --bg returns 0)
#   2  invalid wrapper argument (e.g., bad --session-name regex)
#   3  claude binary not found
#   4  internal error (cd failed, etc.)

set -uo pipefail

# ─── Defaults ───────────────────────────────────────────────────────────────

SESSION_NAME=""
ENDPOINT=""
CWD=""
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || true)}"
PLUGIN_REF="${CLAUDE_CHANNEL_PLUGIN_REF:-plugin:redis-channel@infiquetra-agent-plugins}"
PRODUCTION="${CLAUDE_CHANNEL_PRODUCTION:-0}"

# Session-name regex matches session_id.py:_NAME_RE.
SESSION_NAME_RE='^[a-z0-9][a-z0-9_-]{0,63}$'

# Everything we don't claim passes through to claude.
PASSTHRU_ARGS=()

# ─── Helpers ────────────────────────────────────────────────────────────────

usage() {
    cat <<'EOF'
Usage: claude-channel [WRAPPER OPTS] [CLAUDE OPTS] [-- <claude args>]

Launch claude with a redis-channel session pre-configured. Sets the env
vars and dev flags the plugin needs, then exec's claude. Standard claude
flags (--bg, --print, --resume, --model, --remote-control, etc.) pass
straight through.

Wrapper options:
  --session-name NAME    Session name (regex: ^[a-z0-9][a-z0-9_-]{0,63}$).
                         Exports CLAUDE_SESSION_NAME. If omitted, the
                         plugin auto-generates <cwd-basename>-<8hex>.
  --endpoint NAME        Router endpoint name. Exports CLAUDE_CHANNEL_ENDPOINT.
                         If omitted, plugin resolves to registry's
                         default_endpoint.
  --cwd PATH             cd to PATH before exec. Load-bearing for
                         auto-naming and programmatic callers spawning
                         in a target dir.
  --help                 Show this help and exit.
  --                     Everything after passes verbatim to claude.

Env knobs:
  CLAUDE_BIN                    Path to claude binary. Default: $(command -v claude).
  CLAUDE_CHANNEL_PRODUCTION     If "1", omit dev-only --dangerously-* flags.
  CLAUDE_CHANNEL_PLUGIN_REF     Plugin ref for the dev-channel loader.
                                Default: plugin:redis-channel@infiquetra-agent-plugins.
  REDIS_CHANNEL_KEYCHAIN_ITEM   macOS keychain item to read. Ignored unless
                                REDIS_CHANNEL_PASSWORD_ENV is also set.
  REDIS_CHANNEL_PASSWORD_ENV    Env var name that receives the keychain value.

Backgrounding: use claude's native --bg flag (just pass it as a claude
option). claude prints the background agent ID + attach/logs/stop
commands. `claude agents` lists running sessions.

Examples:
  # Foreground, named session
  claude-channel --session-name auth-feature

  # Background, named, in a specific dir
  claude-channel --session-name auth-feature --cwd ~/work/myrepo --bg

  # Production mode (no dev-only flags), one-shot prompt
  CLAUDE_CHANNEL_PRODUCTION=1 claude-channel --print "what's the status?"
EOF
}

die() {
    printf 'claude-channel: error: %s\n' "$*" >&2
    exit "${2:-2}"
}

require_claude_bin() {
    if [ -z "$CLAUDE_BIN" ] || [ ! -x "$CLAUDE_BIN" ]; then
        die "claude binary not found (set CLAUDE_BIN or put 'claude' in PATH)" 3
    fi
}

# Optional macOS keychain read. Both variables must be set; this wrapper
# does not name a keychain item or a password variable of its own. The
# primary mechanism remains ~/.claude/channels/redis-channel/source-env.sh,
# which scripts/mcp_server.py sources before the MCP server starts.
source_keychain_password() {
    local item="${REDIS_CHANNEL_KEYCHAIN_ITEM:-}"
    local varname="${REDIS_CHANNEL_PASSWORD_ENV:-}"
    if [ -z "$item" ] || [ -z "$varname" ]; then
        return 0
    fi
    if [ "$(uname)" != "Darwin" ]; then
        return 0
    fi
    if [ -n "${!varname:-}" ]; then
        return 0
    fi
    if ! command -v security >/dev/null 2>&1; then
        return 0
    fi
    local pwd
    pwd=$(security find-generic-password -s "$item" -w 2>/dev/null || true)
    if [ -n "$pwd" ]; then
        export "${varname}=${pwd}"
    fi
}

# ─── Argument parsing ───────────────────────────────────────────────────────

while [ $# -gt 0 ]; do
    case "$1" in
        --session-name)
            [ $# -ge 2 ] || die "--session-name requires a value"
            SESSION_NAME="$2"; shift 2 ;;
        --session-name=*)
            SESSION_NAME="${1#*=}"; shift ;;
        --endpoint)
            [ $# -ge 2 ] || die "--endpoint requires a value"
            ENDPOINT="$2"; shift 2 ;;
        --endpoint=*)
            ENDPOINT="${1#*=}"; shift ;;
        --cwd)
            [ $# -ge 2 ] || die "--cwd requires a value"
            CWD="$2"; shift 2 ;;
        --cwd=*)
            CWD="${1#*=}"; shift ;;
        --help|-h)
            usage; exit 0 ;;
        --)
            shift
            PASSTHRU_ARGS+=("$@")
            break ;;
        *)
            # Pass through everything we don't claim (flags AND positional).
            PASSTHRU_ARGS+=("$1"); shift ;;
    esac
done

# ─── Validation + env setup ─────────────────────────────────────────────────

if [ -n "$SESSION_NAME" ]; then
    if ! [[ "$SESSION_NAME" =~ $SESSION_NAME_RE ]]; then
        die "invalid session-name '$SESSION_NAME' (must match $SESSION_NAME_RE)"
    fi
    export CLAUDE_SESSION_NAME="$SESSION_NAME"
fi

if [ -n "$ENDPOINT" ]; then
    export CLAUDE_CHANNEL_ENDPOINT="$ENDPOINT"
fi

if [ -n "$CWD" ]; then
    cd "$CWD" || die "cannot cd to '$CWD'" 4
fi

require_claude_bin
source_keychain_password
export CLAUDE_CHANNEL_AUTO_CONNECT=1

# Detect --bg / --background in the passthru args. Background-dispatched
# claude sessions do NOT inherit env from this wrapper's invocation —
# they're spawned by claude's agent-dispatch IPC, which gives them a
# fresh env. To get our env vars (CLAUDE_CHANNEL_AUTO_CONNECT etc.) into
# the dispatched session, we must inject them via --settings JSON.
# Pattern verified against ~/bin/claude-codex which uses the same
# mechanism for proxy env vars.
bg_mode=0
has_user_settings=0
for arg in "${PASSTHRU_ARGS[@]}"; do
    case "$arg" in
        --bg|--background) bg_mode=1 ;;
        --settings|--settings=*) has_user_settings=1 ;;
    esac
done

# Compose claude argv: dev flags (unless production) + --settings env
# injection (if --bg) + passthru.
CLAUDE_ARGS=()
if [ "$PRODUCTION" != "1" ]; then
    CLAUDE_ARGS+=(--allow-dangerously-skip-permissions)
    CLAUDE_ARGS+=(--dangerously-load-development-channels "$PLUGIN_REF")
fi

if [ "$bg_mode" -eq 1 ]; then
    if [ "$has_user_settings" -eq 1 ]; then
        printf 'claude-channel: warning: --bg + user-supplied --settings detected. ' >&2
        printf 'Make sure your settings include env: {CLAUDE_CHANNEL_AUTO_CONNECT="1"' >&2
        if [ -n "$SESSION_NAME" ]; then
            printf ', CLAUDE_SESSION_NAME="%s"' "$SESSION_NAME" >&2
        fi
        if [ -n "$ENDPOINT" ]; then
            printf ', CLAUDE_CHANNEL_ENDPOINT="%s"' "$ENDPOINT" >&2
        fi
        printf '} so redis-channel auto-connect fires in the dispatched session.\n' >&2
    else
        # Build {"env":{...}} JSON. Values are regex-validated (session_name)
        # or simple strings (endpoint); no JSON-escape needed for these.
        env_entries='"CLAUDE_CHANNEL_AUTO_CONNECT":"1"'
        if [ -n "$SESSION_NAME" ]; then
            env_entries="${env_entries},\"CLAUDE_SESSION_NAME\":\"${SESSION_NAME}\""
        fi
        if [ -n "$ENDPOINT" ]; then
            env_entries="${env_entries},\"CLAUDE_CHANNEL_ENDPOINT\":\"${ENDPOINT}\""
        fi
        CLAUDE_ARGS+=(--settings "{\"env\":{${env_entries}}}")
    fi
fi

CLAUDE_ARGS+=("${PASSTHRU_ARGS[@]}")

exec "$CLAUDE_BIN" "${CLAUDE_ARGS[@]}"
