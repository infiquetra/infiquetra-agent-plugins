---
name: agent-launcher
description: "Create one verified coding-agent session with the local `agents` wrapper — one named tab in the current Herdr workspace, with model, effort, permissions, and working directory — then hand every interaction to the canonical `herdr` skill. Use when the user asks to launch, start, add, or open a coding-agent session for delegation, review, or parallel work. Creation only: after the session exists, use `herdr` for prompt, wait, read, input, and cleanup. Do not use merely because a task could benefit from delegation."
---

# Agent launcher (portable contract)

This skill is the portable form of the shared single-session launch contract:
create one coding-agent session through the installed `agents` wrapper, verify it
through Herdr, optionally deliver a first prompt, and close only a session this
launch proved it owns. The contract script ships in this package at
`skills/agent-launcher/scripts/launcher.py` (package-relative); from this skill's
directory it is `scripts/launcher.py`. Standard library only, so `python3` — no
package manager.

**Depends on:** the canonical `herdr` skill for every interaction after the
session exists. This package does not ship a copy of that skill. After the
creation command returns, switch to `herdr` and stay there.

**Scope boundary — the rule the whole skill hangs on:**

- `agents` **creates** a session: tab, pane, working directory, model, permissions.
- `herdr` **operates** it: prompt, wait, read, send keys, close.

Never use `agents` to prompt, poll, read, or clean up an agent that already exists.

## Verified launch

For one named tab that must be previewed, no-focus, directory-preserving, and
receipt-recorded, use the package script rather than assembling `agents` by hand.
Resolve the script from this package — never from another plugin's install:

```bash
S="<package-root>/skills/agent-launcher/scripts/launcher.py"

python3 "$S" roster                                        # vendors this machine can launch that this contract can drive
python3 "$S" preview --vendor <tool> --task <tab-name> --cwd "$PWD" --model <model> --effort <effort>
python3 "$S" launch  --vendor <tool> --task <tab-name> --cwd "$PWD" --model <model> --effort <effort> > receipt.json
python3 "$S" close --receipt-json receipt.json
```

`launch` always dry-runs first; `--skip-preview` is refused. It writes one JSON
receipt to stdout (redirect it to `receipt.json` as above). It verifies live Herdr
state (kind, pane, cwd, workspace, readiness; model and permission stay
`requested_only` because `herdr agent list` does not publish them) before any
prompt is sent. `close` reads `tab_id` and `owned` from that receipt. `owned` is
true only when the receipt `tab_id` was **not** in the Herdr workspace tab set
snapshotted immediately before the wrapper ran. The wrapper's `reused` bit means
the *workspace* already existed, which is the common case inside Herdr, and is not
tab ownership.

**Stop conditions (carried verbatim from the shared contract):**

- Stop before launch if the wrapper dry run does not resolve the requested working
  directory and current Herdr workspace.
- Stop before prompting if Herdr cannot verify the requested agent kind, model,
  effort, permissions, pane, and readiness. Fields Herdr does not publish are
  recorded as `requested_only` rather than invented; a disagreement on a field
  Herdr does publish is a stop.
- Stop rather than silently substituting an unavailable agent or launch setting.
- Stop cleanup if ownership of the target session cannot be proven (no `tab_id`,
  `tab_id` disagrees with the launch receipt, or `owned` is not true — the tab
  already existed in the pre-launch snapshot).

## The binary is the authority

Command syntax changes. Read it live rather than trusting this file or memory:
`agents --help`, and `--dry-run` before every creation command. Launcher options
go **before** the tool token; everything after it reaches the tool unchanged. The
contract keeps no vendor or model roster of its own: `roster` intersects the
vendors the script knows how to flag with what the wrapper lists in `Tools:` on
this machine, asked every run.

## Adapter-specific limitations

- The launcher's account verification applies only to `vendor claude` and reads
  that vendor's transcript roots and statusline evidence on the operator's
  machine. Every other vendor passes through it untouched.
- The package requires the installed `agents` wrapper and Herdr on the machine.
  An absent wrapper is a stop before launch, not a fallback.
- OpenCode variant selection and the qwen typing-limit file handover are
  interactive behaviors of the shared contract; they are documented by the
  contract's own tables and notes, unchanged here.
- This portable skill resolves its script from this package only. No other
  plugin's installed copy is a fallback.

## Verify, then hand off

The creation command prints one JSON object; keep `agent`, `agent_name`,
`pane_id`, `reused`, `session`, `tab_id`, `tab_name`, `workspace_id`. Read
`agent_name` back rather than assuming the name you asked for — the wrapper
uniquifies collisions. Never close a tab with `owned` false or missing. Then use
the `herdr` skill against those exact IDs, and from that point on: `herdr agent
prompt`, `herdr agent wait`, `herdr agent read`, and Herdr's own cleanup. One
creation command, then hand off; if you find yourself typing `agents` a second
time for the same session, you are in the wrong tool.
