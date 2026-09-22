# Portability

The portable core is `scripts/profile_request.py` at the package root. Claude
Code's command and PreToolUse hook live under `com.infiquetra.claude/`. Any
other harness runs that same script from the package root. The hook is Claude's.

This package adapts Team Mimir classification and canonical Hermes dialogue.
It is not a byte-for-byte copy of another harness plugin.

| Surface | Claude Code treatment |
|---|---|
| Profile request | Native command and skill call the bundled Python adapter. |
| Health check | `suggest`, `reply`, and `resume` automatically run canonical Hermes `doctor` before dialogue. The adapter has no public `doctor` action. |
| Direct-edit guard | Native `PreToolUse` hook covers `Write`, `Edit`, `MultiEdit`, and `NotebookEdit`. |
| Bash and external editors | Outside the supported blocking-hook boundary. |
| Credentials, routing, mutation, settlement | External custody; this plugin does not implement or store them. |
| Offline queue or provider selection | Unsupported. |

For commands and exit behavior, see the [usage guide](docs/usage.md). The
[architecture guide](docs/architecture.md) shows where Claude Code enforcement
ends and producer authority begins.
