---
name: setup
description: Check the tools on this machine and the repository before a saga run.
---

# Setup

`/saga:setup` checks the tools on this machine and the repository. It does not install a tool, and it does not run an optional step, unless the operator names that id.

## Survey

**In Claude Code, when the tool `mcp__saga__setup` is listed and
the operator has not disabled panes, call it with `{"repo": "<repository>"}` instead of
running the survey below, and read the `status` it returns.** Submitted names the installed
and failed ids — never reinstall them; run the survey below, print its table, and continue
with the Questions section exactly as if the tool were absent. Dismissed, not-placed,
unavailable, nothing-to-review, timed-out or error means the pane settled nothing: run the
survey below, print its table, and ask which tools to install exactly as if the tool were absent.

Run the survey with the live sandbox probe and print the table:

```bash
python3 plugins/saga/scripts/saga_setup.py survey --repo <repository> --probe-sandbox live
```

Read the table. It names each selected tool, its lens, its status, and its pinned version. It names credential names only as present or absent. It names whether reproduction is available.

## Questions

Ask the numbered questions the survey prints. Do not invent an answer. Do not print an environment value.

Record the operator's answers:

```bash
python3 plugins/saga/scripts/saga_setup.py write --repo <repository> --answers <answers.json>
```

## Install and steps

Run an install only for tool ids the operator names:

```bash
python3 plugins/saga/scripts/saga_setup.py install --tools <id,id> --repo <repository>
```

Run an optional step only when the operator names it:

```bash
python3 plugins/saga/scripts/saga_setup.py step --name <name> --repo <repository>
```

A row with no install command is not installed by this skill. Say the install sentence and stop.

Offer the `outcome-schedule` step only on macOS where `launchctl` exists. Run it from the saga checkout without `--repo`, because step vectors resolve against the working directory. After setting up a repository, register it with `python3 plugins/saga/scripts/outcome_job.py register --repo-root <repository>`.
