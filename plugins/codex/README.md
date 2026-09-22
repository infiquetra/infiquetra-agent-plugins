# Codex

Portable wrapper that delegates one bounded coding or review task to the Codex
CLI. The wrapper checks a `codex.delegation.v1` envelope, supervises one
`codex exec` process, and writes an evidence bundle with an output-attested
bridge receipt. A run without `--validate-only` or `--dry-run` launches that
process. Those two flags check the envelope and write a validation bundle
without launching `codex`. `--help` does neither.

Coder runs use `mode=task`. The write stays inside a disposable clone, and the
patch is kept in the evidence bundle. Reviewer runs use `mode=read-only` and
scan the live tree for new changes. Neither mode applies a patch to the live
tree.

The `codex` executable is taken from `PATH` unless `--codex-bin` names one.
The wrapper reads no credential variable. The child process inherits the
environment, so authentication is the Codex CLI's own login.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Portable manifest |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only, into the adapter and the skill |
| [`scripts/codex_delegate.py`](scripts/codex_delegate.py) | The wrapper |
| [`scripts/_bundled/`](scripts/_bundled/bridge_receipt.py) | Build-time copies of `bridge_receipt` and `output_attestation` |
| [`fleet-bundle.json`](fleet-bundle.json) | Declares those two Fleet Core modules |
| [`skills/codex-delegate/`](skills/codex-delegate/SKILL.md) | How to run the wrapper, its flags, and the credential rule |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude command, coder agent, and reviewer agent |

Regenerate the bundle after `plugins/fleet-core/` or `fleet-bundle.json`
changes:

```bash
python3 scripts/bundle_fleet_module.py --plugin codex
```

## How a harness reaches it

Claude Code installs this package from the `infiquetra-agent-plugins`
marketplace. The install is the package root, so the wrapper and the Claude
adapter travel together. The command is `delegate`. The agents are
`codex-coder` and `codex-reviewer`. Both call
`${CLAUDE_PLUGIN_ROOT}/scripts/codex_delegate.py`.

OpenCode, Gemini CLI, Muse, and Hermes are skill-scoped. They load
[`skills/codex-delegate/SKILL.md`](skills/codex-delegate/SKILL.md) and run the
wrapper from the package root:

```bash
python3 scripts/codex_delegate.py --help
```

Any other harness that can run a Python script uses that same entrypoint.
There is no second command surface.

## Evidence

The bundle is `<repo-root>/.claude/codex/runs/<run-id>/`. `--repo-root`
defaults to the current directory. Pass it explicitly when that is not the
repository the run is about.

## Modes

- `read-only`: reviewer default. Codex is invoked with a read-only sandbox.
- `task`: coder default. Write-capable, and confined to a disposable clone.
  The patch is preserved in the bundle and is not applied to the live tree.
