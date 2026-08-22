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
  (MCP) interfaces vendor-neutral.
- Put commands, hooks, native agent definitions, permissions, and client runtime
  integration in explicit vendor adapters.
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
