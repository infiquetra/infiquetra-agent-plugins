# Claude Code repository guidance

Read [`AGENTS.md`](AGENTS.md) first. It defines the repository boundary and the
required validation commands.

The repository is designing a portable source catalog. Claude-specific agents,
commands, hooks, permissions, and marketplace metadata belong in an explicit
Claude adapter; they are not portable core merely because Claude is an initial
source system.

One narrow exception, forced by the Claude CLI rather than chosen: a Claude
*packaging* manifest must sit at `<installed root>/.claude-plugin/plugin.json`,
and a marketplace must sit at `<repository root>/.claude-plugin/marketplace.json`.
The CLI offers no other location. Those files are distribution metadata only —
they name paths and carry no command, hook body, agent, or permission — and
every Claude behaviour they point at stays inside the adapter. See the
`2026-08-25` decision "Claude installs the package root" in
[`docs/engineering-journal/DECISIONS.md`](docs/engineering-journal/DECISIONS.md),
which `tests/test_claude_plugin_packaging.py` enforces in both directions.

Before finishing a change, run:

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```
