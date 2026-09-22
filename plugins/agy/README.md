# agy

Antigravity-backed coder and reviewer bridge. One guarded wrapper builds an
`agy.delegation.v1` envelope, runs `agy` in a disposable clone, and returns a
patch plus an evidence bundle. The live tree is never written.

Version 0.6.2 is registered in `.claude-plugin/marketplace.json` at the root of
this repository. The package is authored here. Upstream was
`infiquetra-claude-plugins` at `acc99fe7` (plugin 0.6.1). There is no
provenance manifest.

## Portable core

The core is everything outside `com.infiquetra.claude/`:

- `skills/agy-delegate/scripts/agy_delegate.py` is the wrapper. Skill-scoped
  harnesses (OpenCode, Gemini CLI, Muse, Hermes) install `skills/agy-delegate/`
  and run `python3 scripts/agy_delegate.py` from that directory.
- `scripts/agy_delegate.py` is a launcher to that same wrapper. Claude agents
  and the bridge discriminator keep the catalog path
  `plugins/agy/scripts/agy_delegate.py`.
- `scripts/audit_harness_transcript.py` classifies a Claude transcript as a
  real delegation or a local-edit fallback, and checks the evidence bundle the
  wrapper wrote.
- `skills/agy-delegate/SKILL.md` is the operator contract: flags, the envelope,
  and the credential surface (the wrapper reads none).
- `skills/agy-delegate/scripts/_bundled/` is the generated Fleet Core copy
  (`audit_store`, `bridge_receipt`, `output_attestation`). Regenerate it with
  `python3 scripts/bundle_fleet_module.py --plugin agy` from the repository
  root. Do not edit the generated files.

```bash
python3 skills/agy-delegate/scripts/agy_delegate.py --help
python3 scripts/agy_delegate.py --validation-only --task "Describe the bounded task"
```

Run those from `plugins/agy/` in this checkout, or run the skill-directory
form after a skill install. `--help` and `--validation-only` do not launch
`agy`. `--launch-agy` does. The `agy` binary is resolved on `PATH` unless
`--agy-bin` names it. The durable audit copy defaults to
`~/.claude/delegation-audit` and moves with `--audit-store`.

## Claude adapter

Claude-only behavior lives under `com.infiquetra.claude/`:

- `commands/delegate.md` is the `/agy:delegate` command.
- `agents/agy-coder.md` and `agents/agy-reviewer.md` are Bash-only bridge
  agents. Each must invoke the wrapper exactly once and must not edit the
  repository itself.
- `plugin.json` in that directory is the relocated Claude manifest. The root
  `.claude-plugin/plugin.json` only points at the adapter, the skill, and the
  command and agent directories.

A Claude session working in this catalog runs:

```bash
python3 plugins/agy/scripts/agy_delegate.py
```

## Write modes

No mode writes the live tree. Every launched run happens in a disposable,
remotes-stripped clone and hands back a patch.

- `no-write`: reviewer default. The wrapper runs `agy` in foreground print
  mode with `--sandbox`.
- `patch-only`: coder default. The wrapper preserves `diff.patch`, scores
  changed paths against the declared write-set, and runs any declared
  verification commands inside the clone.

`auto-if-clean` was retired in 0.6.0. An envelope that names it is rejected
before a bundle is created.

## Layout

```text
agy/
├── .claude-plugin/plugin.json
├── plugin.json
├── fleet-bundle.json
├── com.infiquetra.claude/
│   ├── plugin.json
│   ├── agents/
│   │   ├── agy-coder.md
│   │   └── agy-reviewer.md
│   └── commands/
│       └── delegate.md
├── docs/harness-proof.md
├── skills/agy-delegate/
│   ├── SKILL.md
│   ├── references/delegation-contract.md
│   └── scripts/
│       ├── agy_delegate.py
│       └── _bundled/
├── scripts/
│   ├── agy_delegate.py
│   └── audit_harness_transcript.py
├── README.md
└── CHANGELOG.md
```

## Harness proof

`docs/harness-proof.md` is the dated record of the 2026-06-30 live run. The
coder half of that record used `auto-if-clean`, which no longer exists, so the
document is not a runnable procedure.
