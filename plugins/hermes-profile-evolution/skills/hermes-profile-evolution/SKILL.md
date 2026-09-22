---
name: hermes-profile-evolution
description: Route proposed Team Mimir profile behavior changes to target-owned Hermes dialogue.
compatibility: python>=3.12
---

# Hermes Profile Evolution

This skill sends a proposal. The named Hermes profile is the only party that
can create work from it or change its own behavior. The script builds a closed
version-1 envelope and passes that JSON on standard input to the canonical
`hermes profile-request` command. It does not edit profile files.

Run it from the package root, the directory that holds `plugin.json`:

```bash
python3 scripts/profile_request.py --help
```

Claude Code installs that same directory and can use either form:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_request.py" --help
```

OpenCode, Gemini CLI, Muse, and Hermes read this skill. The script is
`scripts/profile_request.py` at the package root, beside `skills/`. A copy of
this skill directory alone does not include the script.

## Actions

| Action | What it does | Invocation |
|---|---|---|
| `suggest` | Build an envelope from a target and an intent, check health, submit it. | `python3 scripts/profile_request.py suggest <target> "<intent>" [--evidence <path>]` |
| `reply` | Continue a proposal. The envelope is the JSON on standard input. | `python3 scripts/profile_request.py reply --message "<text>"` |
| `resume` | Continue a proposal with no new message. The envelope is on standard input. | `python3 scripts/profile_request.py resume` |
| `status` | Read one proposal. Does not run the health check. | `python3 scripts/profile_request.py status --proposal-id <id> --revision <digest> --target <target>` |
| `census` | Read the producer census. The producer JSON is on standard input. Does not run the health check. | `python3 scripts/profile_request.py census` |

`<target>` is a named Hermes profile: a lowercase letter, then lowercase
letters, digits, or hyphens, 2 to 64 characters. `default` and `custom` are
rejected.

`--evidence` may be repeated. Each value is a repository-relative path. An
absolute path, a `..` segment, and a reference whose name looks like a
session, transcript, credential, token, database, or log are rejected.

`suggest`, `reply`, and `resume` run `hermes profile-request doctor` for the
target before submitting. There is no `doctor` subcommand on this script.
If the health check fails, the script exits `2` and does not submit.

`--message` is required for `reply`. A blank message is rejected. The limit
is 16,384 characters. The intent limit on `suggest` is 8,192 characters.

Exit status `0` means the producer returned a response. Exit status `2` means
the input was invalid, the service was unhealthy or incompatible, the
proposal was rejected, or the JSON on standard input did not parse. On exit
`2`, stop. Do not edit the profile to get around it.

## Environment

Set these only when the operator has named them. This package never fills in
a host.

| Variable | When unset |
|---|---|
| `HERMES_PROFILE_REQUEST_SSH_ALIAS` | The script runs `hermes profile-request` on `PATH`. When set, it runs `ssh -- <alias> exec hermes profile-request ...`. The value is an alias, not a command line. |
| `HERMES_TEAM_MIMIR_ROOT` | Read by the Claude PreToolUse hook, not by the request script. Unset, the hook walks upward from the working directory for a Team Mimir checkout (`profiles/` and `scripts/classify_profile_change.py`). If it finds none, it allows the edit. |

The Hermes credential, the route registry, and the profile files stay outside
this package. Do not pass a host, an API key, a model, a provider, a system
prompt, a tool list, or a shell fragment. The envelope rejects those fields.
Put continuation JSON on standard input. Do not interpolate it into a shell
command.

## Claude hook

Claude's PreToolUse hook covers `Write`, `Edit`, `MultiEdit`, and
`NotebookEdit`. It blocks the edit when the Team Mimir classifier reports
profile-owned, mixed, unknown, or prohibited custody. The hook does not claim shell-command interception. Bash and external editors are outside it. Other
harnesses do not load this hook; they still use the request script for a
proposal.
