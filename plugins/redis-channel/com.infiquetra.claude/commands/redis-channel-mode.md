---
description: Override the router-side routing default for this session.
argument-hint: "<auto|always_route|never_route>"
---

Override the router-side routing default for inbound messages to this session:

- `auto` (default) — the router's normal state machine governs whether a message routes through this session or stays with the router LLM.
- `always_route` — every message from any chat with this user/endpoint forwards to this session regardless of mode-toggle phrases.
- `never_route` — this session ignores inbound; only the router LLM responds. Useful for "pause" scenarios.

The override publishes a `mode_change` lifecycle event. Router-side behavior depends on the consumer's implementation; reference implementations (e.g. `hermes-claude-code-router`) honor all three modes.

**Not implemented in Phase 0.** Lands in Phase 3 (voice routing) or later.
