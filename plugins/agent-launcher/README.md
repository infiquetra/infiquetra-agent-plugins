# agent-launcher portable package

Portable Agent Plugins 1.0 package for the shared single-session launch
contract: create one verified coding-agent session through the installed
`agents` wrapper, verify it through Herdr, deliver a prompt, and close only a
session the launch proved it owns. It ships one entrypoint
(`skills/agent-launcher/scripts/launcher.py`) and one Agent Skill over it.
The Claude Code manifest lives under the client extension directory
`com.infiquetra.claude/`; it is an adapter, not the identity of this package.

This tree is a derived artifact of `infiquetra-claude-plugins` at the commit
recorded in `PROVENANCE.json` (upstream plugin version 1.0.0, accepted under
issue #777 there and split to this repository by operator ruling G2). Custody
has not moved. The upstream repository remains the runtime source of truth; a
needed byte change in copied content is an upstream filing, never a downstream
patch.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins 1.0 manifest (target-owned) |
| [`README.md`](README.md) | This document: the portable package README (target-owned; supersedes the upstream README) |
| `PROVENANCE.json` | Source repository, pinned commit, and per-path custody |
| [`CHANGELOG.md`](CHANGELOG.md) | Upstream version history (byte copy) |
| [`skills/agent-launcher/SKILL.md`](skills/agent-launcher/SKILL.md) | The portable skill: contract, stop conditions, and package-relative discovery (target-owned; supersedes the upstream skill) |
| [`skills/agent-launcher/scripts/launcher.py`](skills/agent-launcher/scripts/launcher.py) | The shared launch contract: preview, launch, verify, deliver, owned close (byte copy) |
| `com.infiquetra.claude/plugin.json` | Relocated Claude Code manifest (adapter metadata only) |
| [`tests/`](tests/) | The portable contract suite, authored here (target-owned) |

The upstream `README.md` and `skills/agent-launcher/SKILL.md` are superseded
rather than copied: the upstream README documents the Claude plugin, and the
upstream skill resolves its script through Claude-runtime discovery paths that
have no meaning for other clients. The portable skill adapts the same contract
with package-relative discovery. The upstream test suite is dropped at the pin
for the same class of reason — its remaining premises belong to the upstream
repository — and the portable suite in this package re-proves the portable
contract. See `PROVENANCE.json` for the custody of every path.

## Running it

Standard library only, on the catalog floor `python>=3.12`. The launcher reads
no credentials and answers `--help` before any external command runs:

```bash
python3 skills/agent-launcher/scripts/launcher.py --help
python3 skills/agent-launcher/scripts/launcher.py roster
```

`roster` asks the live `agents` wrapper what this machine can launch and
intersects that with the vendors the contract knows how to tier; with the
wrapper present but listing nothing usable it prints nothing, and with no
wrapper on PATH it stops before printing, naming the missing binary — the
contract's no-fallback rule. `preview` and `launch` additionally
require Herdr, and `launch` always dry-runs first and refuses `--skip-preview`.
A launch writes one JSON receipt to stdout; pass `--prompt` with the first
instruction (a launch with no prompt sends an empty task and exits nonzero when
the session stays idle). `close` acts only on the tab that
receipt proves this launch created.

## Adapter-specific limitations

- Account verification applies only to `vendor claude` and reads that vendor's
  transcript roots and statusline evidence on the operator's machine; every
  other vendor passes through it untouched.
- The package requires the installed `agents` wrapper and Herdr on the
  machine. An absent wrapper is a stop before launch, not a fallback.
- The launcher keeps no vendor or model registry; availability and syntax come
  from the live wrapper and the contract's own tables, asked every run.
- OpenCode variant selection and the qwen typing-limit file handover are
  interactive behaviors of the shared contract, unchanged by this port.
