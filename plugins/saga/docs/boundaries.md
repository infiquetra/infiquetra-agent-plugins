# Saga Boundaries

Saga owns lifecycle state and routing. It does not own adjacent systems' mutation surfaces.

## Ownership Map

| Owner | Owns | Saga holds |
|-------|------|------------|
| `saga` | lifecycle choice, local saga state, routing decisions, handoff envelopes | its own append-only ticks |
| `mission-control` | issue bodies, prepared issue drafts, labels, project fields, GitHub issue mutation | `issue_ref` pointer |
| `deploy` | tag promotion, deployment mutation, environment state | destination intent and PR refs |
| `orchestrate` | running one piece of work across several herdr sessions, one git worktree per unit | `orchestration_mode`, `orchestration_ref`, and `orchestration_run_id` (#693) |
| `agent-launcher` | the roles library and the launch surface the review and testing roles run as | the role name it asked for |

When Saga's cached pointer disagrees with the source system, the source system wins. Git owns branches and commits. GitHub owns PR state. `mission-control` owns SDLC issue state. `deploy` owns environment state.

## Hard Negatives

Saga must not create SDLC issue bodies directly. It prepares handoff context and routes to `mission-control`.

Saga must not promote tags, mutate environments, or run canaries. It records destination intent and routes deployment mutation to `deploy`.

Saga must not absorb reviewer or validator orchestration internals. It records the selected backend and routes to the owner. Issue 1030 archived the `team-execution` plugin that used to own that lane; review and testing roles are now herdr sessions launched from `plugins/agent-launcher/roles/`.

Saga must not treat off-chain command names as stored lifecycle phases.

## Claude Saga And Codex Saga

Claude Saga is the source surface for this repository. The Codex port is an adapter example that preserves the lifecycle semantics while changing host mechanics.

| Dimension | Claude Saga in this repo | Codex Saga adapter |
|-----------|--------------------------|--------------------|
| Command surface | 14 command files, 13 routable commands, `/ceo-review` alias | ported command family may omit or adapt host-only surfaces |
| State root | `.claude/saga/` | host-specific local state root |
| Backend availability | `inline` — the only selectable value since issue 1030 archived the alternatives | `inline`; the Codex port's own backends are its host's |
| Durable docs | repo `docs/*` artifacts plus plugin manual | same lifecycle artifact idea, host-adapted paths |
| Invariant semantics | stored axes, derived maturity, routing ownership, handoff boundaries | preserved |

Use Codex-port docs as comparative evidence, not as replacement truth for Claude Saga.
