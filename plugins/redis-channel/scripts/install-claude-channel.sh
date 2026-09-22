#!/usr/bin/env bash
# install-claude-channel — symlink ~/bin/claude-channel → the cached plugin's wrapper.
#
# Claude caches an installed plugin at
# ~/.claude/plugins/cache/<marketplace>/redis-channel/<version>/.
# This catalog's marketplace is infiquetra-agent-plugins. Installs that
# still come from the previous marketplace name, infiquetra-plugins, stay
# resolvable until cutover. The newest version directory wins; a tie goes
# to infiquetra-agent-plugins.
#
# Re-run this script after each plugin update (or use the MCP server's
# auto-refresh, which covers the same two cache roots).

set -euo pipefail

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    cat <<'EOF'
Usage: install-claude-channel.sh

Point ~/bin/claude-channel at the newest cached redis-channel wrapper.

Looks under ~/.claude/plugins/cache/ for these marketplaces:

  infiquetra-agent-plugins
  infiquetra-plugins

The newest version directory wins. When both marketplaces have that
version, infiquetra-agent-plugins is used.
EOF
    exit 0
fi

MARKETPLACES=(infiquetra-agent-plugins infiquetra-plugins)
BIN_DIR="$HOME/bin"
SYMLINK="$BIN_DIR/claude-channel"

rows=()
for name in "${MARKETPLACES[@]}"; do
    cache="$HOME/.claude/plugins/cache/$name/redis-channel"
    if [ ! -d "$cache" ]; then
        continue
    fi
    rank=1
    if [ "$name" = "infiquetra-agent-plugins" ]; then
        rank=2
    fi
    while IFS= read -r version_dir; do
        [ -n "$version_dir" ] || continue
        version=$(basename "$version_dir")
        printf -v row '%s\t%s\t%s' "$version" "$rank" "$version_dir"
        rows+=("$row")
    done < <(find "$cache" -maxdepth 1 -mindepth 1 -type d)
done

if [ "${#rows[@]}" -eq 0 ]; then
    printf 'install-claude-channel: error: plugin cache not found under:\n' >&2
    for name in "${MARKETPLACES[@]}"; do
        printf '  %s\n' "$HOME/.claude/plugins/cache/$name/redis-channel" >&2
    done
    printf 'Install the redis-channel plugin from the infiquetra-agent-plugins marketplace first.\n' >&2
    exit 1
fi

LATEST=$(printf '%s\n' "${rows[@]}" | sort -t $'\t' -V -k1,1 -k2,2 | tail -1 | cut -f3)
if [ -z "$LATEST" ]; then
    printf 'install-claude-channel: error: no version dirs in the plugin cache\n' >&2
    exit 1
fi

TARGET="$LATEST/scripts/claude-channel.sh"
if [ ! -x "$TARGET" ]; then
    printf 'install-claude-channel: error: %s missing or not executable\n' \
        "$TARGET" >&2
    exit 1
fi

mkdir -p "$BIN_DIR"
ln -sf "$TARGET" "$SYMLINK"

printf '✓ %s -> %s\n' "$SYMLINK" "$TARGET"
printf '\nVerify with:\n  claude-channel --help\n'
