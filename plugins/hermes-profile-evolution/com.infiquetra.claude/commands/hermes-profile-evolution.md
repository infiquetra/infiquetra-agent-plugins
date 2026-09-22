---
name: hermes-profile-evolution
description: Submit a target-addressed Hermes profile-evolution suggestion without direct profile edits
argument-hint: "suggest <target> <intent> | reply --message <text> | resume | status --proposal-id <id> --revision <digest> --target <target> | census"
---

# Hermes Profile Evolution

## Usage

The command routes `$ARGUMENTS` to the bundled adapter at `${CLAUDE_PLUGIN_ROOT}/scripts/profile_request.py`.
It supports `suggest`, `reply`, `resume`, `status`, and `census`; each forwards only to the canonical
`hermes profile-request` command. For `reply`, `resume`, and `census`, provide the canonical JSON input
on standard input. `status` uses only its listed options.

## Instructions

1. Classify intended Team Mimir paths before editing. Profile-owned, mixed, unknown, or secret material must not be directly edited.
2. For a permitted suggestion, build the closed version-1 envelope with `scripts/profile_request.py`; never add host, API key, model, provider, system prompt, or tool fields.
3. Send the JSON envelope on standard input to `hermes profile-request`. Do not construct a shell command from intent, evidence, or reply text.
4. If health or version checking fails, stop. Do not fall back to a direct edit.

## Examples

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/profile_request.py" suggest brokkr \
  "Consider a change to your stated review preference"
```

The command is a suggestion surface only. The target profile may decline, defer, ask questions, or make no change.
