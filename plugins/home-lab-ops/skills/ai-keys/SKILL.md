---
name: ai-keys
description: Use and manage isolated per-project AI provider API keys with the ai-keys command from the home-lab repository — list projects, load keys into a shell or one command, and create, set, or rotate keys on mac-studio
metadata:
  when_to_use: |
    Use this skill when the user:
    - Needs a project's Gemini, OpenAI, Anthropic, ElevenLabs, or Langfuse key
    - Asks which AI key projects exist or what a project's env var names are
    - Wants to run a command with a project's keys without exporting them globally
    - Wants to create, set, or rotate a project's provider key
---

# ai-keys — per-project AI provider keys

`ai-keys` is a command owned by the `home-lab` repository. This skill only says
how to call it. The keys are sealed in Ansible Vault and synced to workstations
as one `0600` env file per project. Nothing here prints or stores a secret value.

## Use a project's keys (any machine)

```bash
# See synced projects: slug, personal or business billing label, providers, cap,
# and env var names. Secret values are never shown.
ai-keys list
ai-keys list --json --account personal
ai-keys list --names-only

# Load one project's keys into the current shell
eval "$(ai-keys emit <project>)"

# Or give the keys to one command only, leaving the login shell clean
ai-keys run <project> -- <command...>
```

Prefer `ai-keys run` when a single command needs the keys. `emit` and `run` work
the same in personal and company sessions. Do not add `emit` to a shell profile or
a service unit, and do not copy the printed values anywhere.

## Create, set, or rotate (mac-studio only)

The administrative credentials live only on `mac-studio`, so these commands refuse
to run anywhere else and print the `mac-studio` command to use instead.

```bash
# New project: choose the billing account and the providers
ai-keys create --account personal --providers gemini,openai <project>
ai-keys create --account business --providers anthropic,langfuse <project>

# Set one value. The value is read from hidden input, never from an argument.
ai-keys set <project> <VAR_NAME>

# Rotate a provider key: new key, auth probe, seal to Vault, retire the old key
ai-keys rotate --provider gemini <project>
```

`--providers` accepts `gemini`, `openai`, `anthropic`, `elevenlabs`, and `langfuse`.
`create` also takes `--cap`, `--gcp-project-id`, `--allow-manual-cap`, `--no-probe`,
and `--sync`. Run `ai-keys --help` for the current options.

After a create, set, or rotate, the change reaches other machines only through the
`home-lab` Ansible sync. Review and merge the resulting `home-lab` change; do not
edit the vault files by hand. Hand edits follow the `vault-helper` skill.

## Rules

- Never type, paste, or log a key value in a prompt, command line, commit, or issue.
- Never run `ansible-vault edit`, `view`, or `decrypt` on the vault files.
- Admin credentials never leave `mac-studio`.
