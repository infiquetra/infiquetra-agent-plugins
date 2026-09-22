---
description: Rename this Claude Code session's registry entry.
argument-hint: "<new-name>"
---

Change this session's registered name in the Redis presence registry to `$1`. The new name must be unique among live sessions on the same endpoint.

Effect: the registry hash field is moved, the heartbeat key is recreated under the new name, the consumer group is recreated, and an `unregistered{old_name}` + `registered{new_name}` event is published.

**Not implemented in Phase 0.** Lands in Phase 6 polish.
