# Hermes profile evolution

Portable request adapter for target-sovereign Hermes profile evolution. The
package sends a proposal. The named Hermes profile is the only party that can
create work from that proposal or change its own behavior. This package stores
no Hermes credential, route registry, mutation policy, or target ledger. It
calls the canonical `hermes profile-request` command with a closed version-1
envelope on standard input, and it requires a compatible health response
before `suggest`, `reply`, or `resume`.

The Claude file-edit hook blocks recognizable edits from Claude's `Write`,
`Edit`, `MultiEdit`, and `NotebookEdit` tools when the Team Mimir ownership
classifier reports profile-owned, mixed, unknown, or prohibited custody. The
hook does not claim shell-command interception.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Vendor-neutral. |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only: the command directory, the hook descriptor, and the portable skills directory. |
| [`scripts/profile_request.py`](scripts/profile_request.py) | The one request script. `suggest`, `reply`, `resume`, `status`, and `census`. |
| [`skills/hermes-profile-evolution/`](skills/hermes-profile-evolution/SKILL.md) | Agent Skill. Names the script, its flags, and the two environment variables. |
| [`tests/`](tests/) | Contract tests for the script, the hook, the docs, and a credential-free `--help` run. |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter: command, PreToolUse hook, and the adapter manifest. |
| [`docs/`](docs/usage.md) | Usage, architecture, development, and troubleshooting for the Claude front door. |
| [`PORTABILITY.md`](PORTABILITY.md) | Which surfaces are Claude's, and which behavior stays outside this package. |

`scripts/profile_request.py` and the hook were copied from
`infiquetra-claude-plugins` at `acc99fe7` and are maintained here from version
`0.1.5`. There is no provenance manifest.

## How a harness reaches it

Run the script from this package root, the directory that holds `plugin.json`:

```bash
python3 scripts/profile_request.py --help
```

| Harness | What it gets |
|---|---|
| Claude Code | The package root, installed from this repository's marketplace. That install includes the command, the PreToolUse hook, the skill, and `scripts/profile_request.py`. |
| OpenCode, Gemini CLI, Muse, Hermes | The skill at `skills/hermes-profile-evolution/SKILL.md`. The script those instructions run is `scripts/profile_request.py`, beside `skills/`, not inside the skill directory. A placement that copies only the skill directory does not include the script. |
| Codex, Grok, Qwen, Agy, Cursor Agent | The same script, run from a checkout of this package. These harnesses do not load the Claude hook. |

Claude Code install, from a checkout of this repository:

```bash
claude plugin marketplace add /path/to/infiquetra-agent-plugins
claude plugin install hermes-profile-evolution@infiquetra-agent-plugins
```

Restart Claude Code after installing. The hook is registered at session start.
Installing does not configure a Hermes host.

## Environment

Neither variable has a default host. A value that is present but empty is
treated as unset.

| Variable | Read by | When unset |
|---|---|---|
| `HERMES_PROFILE_REQUEST_SSH_ALIAS` | `scripts/profile_request.py` | The script runs `hermes profile-request` on `PATH`. When the variable is set, the script runs `ssh -- <alias> exec hermes profile-request ...`. The alias must be one token of letters, digits, `.`, `_`, and `-`, and this package never fills one in. |
| `HERMES_TEAM_MIMIR_ROOT` | the Claude PreToolUse hook | The hook walks from the working directory upward, looking for a directory that contains `profiles/` and `scripts/classify_profile_change.py`. If it finds none, and this variable is unset, the hook allows the edit. If the variable is set and that directory is not a verified Team Mimir root, the hook blocks the edit. |

Credentials, the route registry, and profile files stay outside this package.
Do not put a host, an API key, a model, a provider, a system prompt, or a tool
list in the envelope. The script rejects those fields.

## Commands

`suggest`, `reply`, and `resume` submit a proposal. Each one runs
`hermes profile-request doctor --target <profile>` first and requires the
exact healthy response. There is no public `doctor` subcommand.

`status` and `census` are reads. They do not run that health check.

The exit status is `0` after a successful response and `2` for invalid input,
an unhealthy or incompatible Hermes service, a rejected proposal, or invalid
JSON. On exit `2`, stop. The package has no offline queue and no second route.

Flags, standard-input rules, and examples are in the
[skill](skills/hermes-profile-evolution/SKILL.md) and in
[docs/usage.md](docs/usage.md).

## Operator guides

- [Install and use the Claude front door](docs/usage.md)
- [Trust boundaries](docs/architecture.md)
- [Develop and release](docs/development.md)
- [Troubleshoot requests](docs/troubleshooting.md)
- [Which surfaces are Claude's](PORTABILITY.md)

The [Team Mimir operator hub](https://github.com/infiquetra/team-mimir/tree/main/docs/team/profile-evolution)
covers deployment and activation. The
[Hermes producer documentation](https://github.com/infiquetra/infiquetra-hermes-plugins/tree/main/docs/profile-evolution)
owns dialogue and compatibility semantics.
