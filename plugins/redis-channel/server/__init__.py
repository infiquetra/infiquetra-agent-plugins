"""redis-channel — Claude Code channel over Redis streams.

See PROTOCOL.md for the wire format and docs/STATE_MACHINE.md for the
routing semantics on the consumer side.

This package is the CC-side implementation: an MCP server (stdio) that:
  - emits notifications/claude/channel from inbound Redis stream messages
  - registers a reply tool that XADDs to outbound
  - manages presence via heartbeat
  - intercepts AskUserQuestion and converts to inline-choice replies
  - relays permission_request / permission_verdict
"""

__version__ = "0.5.3"
