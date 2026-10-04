---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# mods U0 — Mod foundation: TypeScript modules in the Claude adapters, validated and tested in CI

### Objective

Set up everything the seven mods share:

- where module files live inside each plugin's Claude adapter, and how the hooks file names them;
- how a mod reads saga state and writes answers back;
- the minimum Claude Code build;
- CI that validates and tests every mod.

### Intent

1. **Location.** Module files live inside the plugin's Claude adapter, under
   `com.infiquetra.claude/`. They are named from the adapter's existing `hooks/hooks.json` under
   `modules`, beside the command hooks already there. Each plugin that keeps state contracts ships
   one `types/index.d.ts`, named from its Claude packaging manifest. That manifest change is
   path-only, as the 2026-08-25 packaging decision requires. `tests/test_claude_plugin_packaging.py`
   is updated to hold the new path in both directions.
2. **Reading and writing state.** A shared pattern reads saga state by running
   `run_record.py show <N>` through the mod's host-command call and parsing its JSON. It never
   parses prose and never reads files the scripts own directly. Answers go back only through a
   script's command line. The pattern lives in one module that the other mods import.
3. **Version floor.** Record the minimum Claude Code build that loads these modules, 2.1.289 or the
   first build with mods, whichever is earlier. Verify on a real older build how it treats a hooks
   file that names a module. If an older build rejects the whole file, saga's existing command hooks,
   including the pre-push gate, would stop loading there. That outcome is a stop condition.
4. **CI.** Install Claude Code in `.github/workflows/ci.yml`. Run `claude plugin validate` and
   `claude plugin test` for each plugin that ships a module, and make `check_repo.py` refuse
   TypeScript outside a Claude adapter.

### Risk

medium
A loader or packaging regression would reach every Claude Code session with these plugins, though
nothing here changes policy.

### Out-of-scope / non-goals

- The mods themselves are U1 to U8.
- No mod outside the saga and orchestrate Claude adapters.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/hooks/hooks.json`
- `plugins/saga/.claude-plugin/plugin.json`
- `plugins/orchestrate/com.infiquetra.claude/plugin.json`
- `tests/test_claude_plugin_packaging.py`
- `scripts/check_repo.py`
- `.github/workflows/ci.yml`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `tests/test_claude_plugin_packaging.py`: the manifest names only paths into the adapter, including
  the types path.
- A `*.test.ts` for the shared state-reading module: parses `run_record.py show` output and refuses
  a record version it does not know.
- A `check_repo.py` rule with a test: TypeScript outside `com.infiquetra.claude/` is refused.

### Failure modes / pre-mortem

- An older Claude Code build rejects a hooks file that names a module, and saga's command hooks
  silently stop loading. Verified on a real older build before merge.

### Stop conditions

- Stop if a supported older build rejects the hooks file; ship the module through a separate hooks
  file instead, and record why.

### Context library links

- `docs/engineering-journal/DECISIONS.md` — "Claude installs the package root", 2026-08-25

### Acceptance criteria

- [ ] `claude plugin validate plugins/saga` lists the module's hooks and passes.
- [ ] CI runs `claude plugin validate` and `claude plugin test` for saga and orchestrate.
- [ ] `python3 -m unittest tests.test_claude_plugin_packaging -v` passes with the types path.
- [ ] `DECISIONS.md` records the version floor and the older-build observation.

### Verification

```bash
claude --version
claude plugin validate plugins/saga
claude plugin test plugins/saga
python3 -m unittest tests.test_claude_plugin_packaging -v
python3 scripts/check_repo.py
git diff --check
```
