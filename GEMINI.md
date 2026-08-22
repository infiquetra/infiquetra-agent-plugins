# Gemini CLI repository guidance

Read [`AGENTS.md`](AGENTS.md) first. It defines the repository boundary and the
required validation commands.

Keep Agent Skills and shared tools portable. Gemini extensions, hooks,
subagents, policies, and other Gemini-specific packaging belong in an explicit
Gemini adapter.

Before finishing a change, run:

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```
