# Infiquetra Agent Plugins

Portable Agent Skills, Agent Plugins, and vendor adapters for Infiquetra
engineering workflows.

This public repository is the design and future source catalog for behavior
that does not belong to one coding-agent vendor. It will complement, and may
eventually generate parts of, the existing Claude Code, Codex, Antigravity,
OpenCode, and Hermes plugin repositories.

## Status

No runtime plugins have been migrated. Existing vendor repositories remain the
runtime sources of truth until a portable pilot proves semantic and operational
parity.

The current architecture brief records the research, proposed direction, and
decisions still required:

- [Cross-vendor plugin architecture brief](docs/cross-vendor-plugin-architecture-brief.md)

## Repository layout

| Path | Purpose |
|---|---|
| [`docs/`](docs/README.md) | Architecture, public guidance, and durable repository knowledge |
| [`docs/engineering-journal/`](docs/engineering-journal/README.md) | Learnings, decisions, queued work, and archive |
| [`.github/`](.github/PULL_REQUEST_TEMPLATE.md) | Pull request, issue, and validation workflow configuration |
| [`scripts/check_repo.py`](scripts/check_repo.py) | Public repository and future plugin-package validation |

The proposed future package layout is documented in the architecture brief.
Creating that layout before the first pilot would imply implementation that has
not yet been approved.

## Validation

Run the same checks used by continuous integration (CI):

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

The validation script checks the repository baseline, local Markdown links,
and any future Agent Plugin manifests under `plugins/`.

## Development

- Read [`AGENTS.md`](AGENTS.md) before changing the repository.
- Use conventional commit messages.
- Use pull requests after the initial repository bootstrap.
- Update the engineering journal when work creates a durable learning,
  repository decision, or deferred item.
- Do not commit credentials, generated installed copies, or local agent state.

Public development guidance is summarized in
[`docs/public-safe-summary.md`](docs/public-safe-summary.md).
