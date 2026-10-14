# AGENTS.md

## Repository purpose

This repository owns the proposed portable source catalog for Infiquetra Agent
Skills, Agent Plugins, shared workflow contracts, and the source inputs used to
build vendor adapters.

It does not yet replace an existing vendor plugin repository. It does not own
Herdr runtime implementation, vendor client code, credentials, installed plugin
copies, or Team Mimir profile definitions.

## Source of truth

- Start with [`README.md`](README.md).
- Architecture and open decisions:
  [`docs/cross-vendor-plugin-architecture-brief.md`](docs/cross-vendor-plugin-architecture-brief.md)
- Repository decisions and deferred work:
  [`docs/engineering-journal/`](docs/engineering-journal/README.md)
- Public contributor guidance:
  [`docs/public-safe-summary.md`](docs/public-safe-summary.md)
- Infiquetra organization standards:
  [`infiquetra-context-library`](https://github.com/infiquetra/infiquetra-context-library/blob/main/docs/00-index.md)
- Development lifecycle:
  [`infiquetra-sdlc`](https://github.com/infiquetra/infiquetra-sdlc/blob/main/README.md)
- Context and journal trigger rules:
  [context audit](https://github.com/infiquetra/infiquetra-context-library/blob/main/docs/ai-context/context-audit-standard.md)
  and
  [engineering journal](https://github.com/infiquetra/infiquetra-context-library/blob/main/docs/repositories/engineering-journal-standard.md)

## Commands

```bash
# Build step. Regenerate the build-time Fleet Core bundles after changing
# plugins/fleet-core/ or a consumer's fleet-bundle.json. check_repo.py rejects
# a declared bundle that is missing, stale, or hand-edited, so this runs first
# when either of those changed.
python3 scripts/bundle_fleet_module.py

python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

## Rules

- Keep shared skills, contracts, schemas, scripts, and Model Context Protocol
  (MCP) interfaces vendor-neutral. That includes the porting tools: package
  identity, the custody table, and assessment settings belong in that package's
  [port descriptor](ports/README.md) under `ports/`, never as a constant inside
  a script.
- Put commands, hooks, native agent definitions, permissions, and client runtime
  integration in explicit vendor adapters. A vendor's own packaging manifest is
  the one thing that may sit outside its adapter, and only where that vendor's
  tooling refuses to look anywhere else; it carries paths into the adapter, never
  behaviour.
- Claude-specific agents, commands, hooks, permissions, and marketplace metadata
  belong in an explicit Claude adapter, the package's `com.infiquetra.claude/`
  directory. They are not portable core merely because Claude is an initial source
  system. One narrow exception is forced by the Claude CLI rather than chosen: a Claude
  *packaging* manifest must sit at `<installed root>/.claude-plugin/plugin.json`, and a
  marketplace must sit at `<repository root>/.claude-plugin/marketplace.json`. The CLI
  offers no other location. So each package with a Claude adapter carries two manifests
  side by side: `plugins/<package>/plugin.json`, the portable Agent Plugins manifest,
  and `plugins/<package>/.claude-plugin/plugin.json`, Claude's packaging manifest. The
  Claude manifest holds paths into `com.infiquetra.claude/` or the portable skills,
  never behaviour. The reasoning is in the `2026-08-25` decision "Claude installs the
  package root; the client extension keeps the behaviour" in
  [`docs/engineering-journal/DECISIONS.md`](docs/engineering-journal/DECISIONS.md), and
  `tests/test_claude_plugin_packaging.py` enforces both halves.
- Do not add a root `CLAUDE.md`; `scripts/check_repo.py` rejects it. `AGENTS.md` is the
  single repository instruction file. The 2026-10-13 decision "Root CLAUDE.md is removed"
  in [`docs/engineering-journal/DECISIONS.md`](docs/engineering-journal/DECISIONS.md)
  records why.
- Do not claim a vendor package is generated or portable until the relevant
  build and live compatibility checks prove it.
- Treat existing vendor repositories as authoritative until a recorded custody
  decision moves that authority here.
- Do not edit installed plugin copies as maintained source.
- Keep changes scoped and add tests for changed script or packaging behavior.
- A portable package must be runnable, not merely present. When a package ships an
  executable entrypoint, a test has to run it the way a user runs it; validating the
  pieces separately is what let the UniFi clients ship importing a module nothing
  generated. See `tests/test_client_entrypoints.py`.
- Apply the security and publication rules in
  [`docs/public-safe-summary.md`](docs/public-safe-summary.md). In particular,
  generated validation fixtures must use inert example values.
- Maintain `docs/engineering-journal/` under the linked journal standard;
  compatibility results, source-custody changes, and portability limits are
  especially relevant in this repository.
- Use conventional commits and pull requests after initial bootstrap.
