# Claude Code repository guidance

Read [`AGENTS.md`](AGENTS.md) first. It defines the repository boundary and the
required validation commands.

The repository is designing a portable source catalog. Claude-specific agents,
commands, hooks, permissions, and marketplace metadata belong in an explicit
Claude adapter; they are not portable core merely because Claude is an initial
source system.

Before finishing a change, run:

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```
