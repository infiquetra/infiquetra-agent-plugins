# agent-launcher

Portable Agent Plugins 1.0 package for the shared single-session launch contract.
The portable core is this directory: `plugin.json`, the `agent-launcher` skill, the
scripts under `skills/agent-launcher/scripts/`, and the `roles/` prompt library.
Claude-only packaging sits in two manifests that carry paths and no behaviour: the
root `.claude-plugin/plugin.json` (what the Claude CLI reads at the installed
package root) and `com.infiquetra.claude/plugin.json` (the relocated upstream
manifest). This package is authored in this repository from the 1.7.1 cut. There
is no provenance manifest.

Create one verified coding-agent session in the current Herdr workspace. The package requires the installed `agents` wrapper and Herdr on the machine. An absent wrapper is a stop before launch, not a fallback. The wrapper is the only creation path. Herdr is the only interaction path after creation. The scripts are standard library only, on the catalog floor `python>=3.12`.

Orchestrate consumes this plugin's `skills/agent-launcher/scripts/launcher.py` as its
launch seam. An ordinary session uses the same script as a CLI, or follows
`skills/agent-launcher/SKILL.md`.

This plugin does not ship a copy of the `herdr` skill. After a session exists, use that
skill for prompt, wait, read, input, and cleanup.

`roles/` holds one reusable prompt per role the software development lifecycle names — what to
send a session once it exists, so the briefing is not hand-written each time. Its contract is in
[`roles/README.md`](roles/README.md). Nothing in this plugin spawns or orders those roles today.

## Quick start

From the package root, any harness runs the script by path:

```bash
python3 skills/agent-launcher/scripts/launcher.py --help
python3 skills/agent-launcher/scripts/roster.py --help
```

Claude Code sets `CLAUDE_PLUGIN_ROOT` to the installed package root, so the same
files are `$CLAUDE_PLUGIN_ROOT/skills/agent-launcher/scripts/launcher.py` and
`roster.py`. Skill-scoped harnesses (OpenCode, Gemini CLI, Muse, Hermes) install
the `skills/agent-launcher/` unit and run those paths from the skill directory's
parent package. Nothing in this package searches a Claude plugin cache.

```bash
S="$CLAUDE_PLUGIN_ROOT/skills/agent-launcher/scripts/launcher.py"

python3 "$S" roster
python3 "$S" preview --vendor codex --task reviewer --cwd "$PWD" --model gpt-5.4 --effort xhigh
python3 "$S" launch  --vendor codex --task reviewer --cwd "$PWD" --model gpt-5.4 --effort xhigh --prompt "review the diff" > receipt.json
python3 "$S" close --receipt-json receipt.json
# after a staged-input stop, once the composer is clear -- never a second launch:
python3 "$S" redeliver --vendor <tool> --task <tab-name> --cwd "$PWD" --prompt <text> --receipt-json receipt.json > receipt-retry.json
```

The launch line carries a real prompt: without one, the session never leaves idle and the command exits nonzero.

Standard library only, so `python3` — not `uv run`.

## Input-box receipt contract

The launch receipt records the last composer inspection under `input_box`. Every line that enters
a session — each setup slash command, the task, each resend, both picker keystrokes on OpenCode,
and every later prompt Orchestrate sends — goes through one door, `PaneWriter.write`, which
inspects the pane immediately before the write whenever the write could land behind staged text:
before the first write into a session the launcher did not create, and before every later write
into any session, owned or not, once the launcher has written into it. The only uninspected write
is the first one into a tab the launcher created seconds earlier. A fresh owned launch with no
setup lines whose first prompt was taken therefore made no inspection and its receipt carries no
`input_box` key; any session written to more than once carries it. Its complete value set is
`empty`, `staged`, `unclassifiable`, `not_found`, `unsupported_vendor`, `read_failed`, and
`read_timeout`. Only `staged` also carries `input_box_text_chars`: the visible length of what the
parser absorbed — visible characters after border stripping, rows joined without a separator, one
character short at each wrapped-row boundary, and a lower bound of the draft's true length when a
blank line inside the draft ends the absorption — never the text itself. Blank or indented rows
that cannot be distinguished from vendor chrome are `unclassifiable`, never affirmative `empty`;
the accepted asymmetry runs the other way too, where an unbordered indented row directly below the
marker with no separator row between is read as input, because no capture shows chrome there.

## Launch receipt keys

The receipt `launch` prints, and `redeliver` and `close` read, carries these keys. `close` needs
`tab_id` and `owned`; `redeliver` needs `unit_name`, `pane`, `tab_id`, `owned`, `agent_name`, and
one of the two retryable markers (`input_box` equal to `staged`, or `prompt_delivered` equal to
`false`). There is no `pane_id` key; `pane` is the only spelling.

| Key | Meaning |
|---|---|
| `unit_name`, `vendor` | The task name and vendor the launch was asked for. |
| `tab_id`, `pane`, `agent_name` | The Herdr identifiers the wrapper returned. |
| `owned` | True only when `tab_id` was absent from the workspace tab set snapshotted before the wrapper ran. |
| `reused` | The wrapper joined a workspace that already existed; not ownership. |
| `permission`, `permission_resolved` | The posture asked for, and the launch tokens it was confirmed against. |
| `provider`, `model`, `variant`, `account`, `account_evidence` | Requested values; `account_evidence` is `statusline`, `transcript`, or `none`. |
| `variant_confirmed_from` | OpenCode only: `session` when the variant was read back from a non-menu row, `picker_menu_only` otherwise. |
| `kind`, `working_directory`, `workspace`, `readiness` | What Herdr reported at preflight. |
| `confirmed_against_herdr`, `requested_only` | Which fields Herdr confirmed, and which remain the request echoed back. |
| `verified` | True once the preflight ran. |
| `prompt_delivered` | `true` once the session was observed to take the task, `false` when it was not, `null` before any prompt. |
| `input_box`, `input_box_text_chars` | The last composer inspection; see the section above. |

## Boundaries

- Preview with `--dry-run` before every creation. It confirms `cwd` and `herdr_workspace`; it does not confirm model, effort, or account. Stop if the working directory or Herdr workspace is wrong.
- Launch is no-focus. Do not steal the operator's pane.
- Do not silently substitute an unavailable vendor, model, effort, or topology.
- Close only a session whose `tab_id` matches the launch receipt.
- Do not invent a vendor/model roster. The launcher keeps no vendor or model registry. The live wrapper and Herdr remain authoritative.
- Account verification applies only to `vendor claude` and reads that vendor's transcript roots and statusline evidence. The two directory overrides are the environment variables `claude_transcript_roots` reads; each default is under the home directory. Every other vendor passes through account verification untouched.
