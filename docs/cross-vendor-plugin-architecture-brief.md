# Cross-vendor plugin architecture brief

**Status:** Research complete; architecture proposed; implementation decisions
remain open.

## Purpose

Infiquetra currently maintains overlapping plugin behavior for Claude Code,
Codex, Google Antigravity, OpenCode, and Hermes Agent. Grok, Qwen Code, Cursor,
Gemini CLI, and Muse Code add further installation and runtime formats.

The objective is to author vendor-neutral behavior once while preserving the
native capabilities that genuinely differ between clients. This should reduce
manual ports, version drift, and review inconsistencies without flattening all
clients to their weakest common feature set.

## What the research established

Two open standards provide a useful common layer:

- [Agent Skills](https://github.com/agentskills/agentskills) standardizes a
  `SKILL.md` directory with optional scripts, references, and assets.
- [Agent Plugins 1.0](https://github.com/agentplugins/agent-plugins-spec/blob/main/spec/1.0.0.md)
  packages Agent Skills and optional Model Context Protocol (MCP) servers under
  a portable root `plugin.json`.

Agent Plugins 1.0 intentionally does **not** standardize commands, hooks, agent
definitions, rules, permissions, Language Server Protocol servers, user
interfaces, or marketplace distribution. Those features remain client-specific.
`AGENTS.md` is also separate: it supplies repository instructions rather than a
distributable plugin contract.

Therefore:

- One Infiquetra source catalog is feasible.
- One portable package for skills and MCP tools is feasible.
- One marketplace interface or complete runtime package shared unchanged by
  every client is not currently feasible.

## Proposed architecture

### 1. Portable capability layer

Store vendor-neutral behavior as Agent Plugins:

```text
plugins/<name>/
├── plugin.json
├── skills/
│   └── <skill>/
│       ├── SKILL.md
│       ├── scripts/
│       ├── references/
│       └── assets/
└── mcp.json                 # only when the capability exposes MCP tools
```

This layer should own workflow contracts, review rules, durable artifact
formats, procedural guidance, and portable tool interfaces.

### 2. Herdr execution layer

Use Herdr as the default vendor-independent execution boundary. Herdr should
choose the vendor and model, create and organize sessions, manage workspaces and
concurrency, monitor delivery, and return results to the coordinator.

Vendor-native agent teams may remain available as optional accelerators. The
portable workflow must not depend on Claude agent teams, Codex collaboration,
Grok subagents, or another single client's orchestration semantics.

### 3. Vendor adapter layer

Keep only genuine host-specific behavior in adapters:

```text
plugins/<name>/
├── com.infiquetra.claude/
├── com.infiquetra.codex/
├── com.infiquetra.cursor/
├── com.infiquetra.gemini/
├── com.infiquetra.antigravity/
├── com.infiquetra.opencode/
└── com.infiquetra.hermes/
```

Adapters may supply native manifests, commands, hooks, agents, permissions, and
runtime integration. Build tooling may generate the vendor repositories or
marketplace manifests from these sources. A client-specific directory does not
become portable merely because it is stored beside the portable core.

## Current client compatibility

| Client | Portable support | Remaining native work |
|---|---|---|
| Claude Code | Agent Skills and MCP inside Claude plugins | Claude manifest, commands, agents, hooks, monitors, settings, and LSP |
| Cursor | Direct Agent Plugins 1.0 support | Cursor rules, commands, agents, hooks, and variables |
| Qwen Code | Direct Agent Plugins 1.0 and Claude marketplace imports | Native extension needed for commands, agents, and hooks |
| Grok Build | Reads Claude marketplaces, plugins, skills, MCP, agents, and hooks | No immediate port required; a portable source can replace the indirect dependency later |
| Codex and ChatGPT | Shared OpenAI plugin directory with Agent Skills and MCP | OpenAI packaging and Codex-native hooks or profiles |
| Gemini CLI | Agent Skills through `.agents/skills` | Gemini extension for commands, hooks, subagents, and policies |
| Antigravity | Agent Skills | Antigravity manifest, agents, hooks, rules, and orchestration |
| OpenCode | Agent Skills through `.agents/skills` and `.claude/skills` | Native plugin code and runtime-specific commands or agents |
| Muse Code | Imports skills from Claude or Codex | No confirmed complete Agent Plugins runtime; managed skill sync is required |
| Hermes Agent | Skills and MCP concepts plus a native plugin system | Python `plugin.yaml` packages for tools, hooks, commands, permissions, and profiles |

## Initial Infiquetra plugin classification

| Current Claude plugin | Proposed treatment |
|---|---|
| `home-lab-ops` | Strong first portable pilot; skills are the primary behavior |
| `mission-control` | Portable skills and scripts with command and agent adapters |
| `orchestrate` | Portable orchestration contract; delegate actual session execution to Herdr |
| `unifi` | Portable skills and scripts with native command and agent adapters |
| `deploy` | Portable workflow and scripts with host-specific authorization and command presentation |
| `redis-channel` | Portable skill and MCP core; commands and agent remain adapters |
| `agy` | Portable routing contract with Antigravity-specific execution adapter |
| `codex` | Portable routing contract with Codex-specific execution adapter |
| `hermes-profile-evolution` | Portable proposal contract; Hermes custody, activation, and hooks remain native |
| `house-style` | Extract common behavior into an Agent Skill; keep exact output-style integration native |
| `saga` | Extract portable lifecycle skills while retaining native controllers, hooks, commands, and agents |
| `team-execution` | Move portable contracts to skills; make Herdr the execution path; keep vendor teams optional |
| `fleet-core` | Treat as a versioned library, CLI, or MCP service rather than an Agent Plugin by itself |

## Saga boundaries

Saga does not need to be broken apart merely because it is large. Split it only
where a capability has a genuinely independent permission boundary, dependency
set, release cadence, or consumer population. Possible independently installable
areas include ideation, planning, work, review, and deployment, while the shared
lifecycle and artifact contracts remain coherent.

## Source custody and distribution

The target model is exactly one writable source for shared behavior. Published
vendor packages are immutable, generated snapshots tied to a source commit and
content digest. Installed copies are consumers, not authoring locations.

A release pipeline should:

1. Validate Agent Skills and Agent Plugins schemas.
2. Assemble each required vendor adapter.
3. Record plugin name, version, source commit, and content digest in a catalog.
4. Publish or update native marketplace and collection manifests.
5. Run focused smoke tests against each supported client.
6. Detect installed-version drift and report clients that require restart or
   manual refresh.

## Recommended proof sequence

1. Port `home-lab-ops` to prove shared Agent Skill discovery.
2. Port `mission-control` or `unifi` to prove bundled scripts and native aliases
   (UniFi pilot completed 2026-08-23, [`evidence/2026-08-22-unifi-compatibility-matrix.md`](evidence/2026-08-22-unifi-compatibility-matrix.md);
   mission-control port completed 2026-08-25, [`evidence/2026-08-25-mission-control-compatibility-matrix.md`](evidence/2026-08-25-mission-control-compatibility-matrix.md)).
3. Port an MCP-bearing capability to prove portable tool packaging.
4. Extract Saga's portable skills while retaining its native control adapters.
5. Redesign `team-execution` and `fleet-core` only after the Herdr boundary is
   explicit and proven.

Avoid a big-bang migration. Existing vendor repositories should remain active
until each generated or shared replacement passes semantic parity and live
client checks.

## Decisions for the next session

1. Is Herdr the required execution substrate, with vendor-native agent teams
   treated only as optional accelerators?
2. Does this repository immediately become the canonical source, or does the
   Claude repository remain authoritative during the first pilots?
3. Which plugin is the first pilot: `home-lab-ops`, `mission-control`, or
   `unifi`?
4. Do portable role contracts need an Infiquetra-owned schema that can generate
   Claude agents, Codex profiles, Hermes profiles, and other native definitions?
5. What exact criteria justify splitting one Saga capability into a separately
   versioned plugin?
6. Which clients are required for the first compatibility gate, and which are
   best-effort consumers?

## Non-goals for the first iteration

- Reimplement every vendor-native feature in the portable layer.
- Make portable skills responsible for vendor selection or credential policy.
- Retire existing marketplaces before their replacements are proven.
- Treat copied installed plugin files as maintained source.
- Split Saga or Team Execution before their new ownership boundaries are
  decision-complete.
