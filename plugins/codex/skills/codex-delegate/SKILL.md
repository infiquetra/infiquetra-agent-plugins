---
name: codex-delegate
description: Build a codex.delegation.v1 envelope and run it through the guarded Codex wrapper, which supervises one codex exec and writes an evidence bundle with an output-attested receipt.
compatibility: python>=3.12
---

# Codex delegate

The wrapper at `scripts/codex_delegate.py` is the only supported way to delegate
work to the Codex CLI. It checks one `codex.delegation.v1` envelope, then either
validates that envelope or supervises one `codex exec` process. A coder run in
`task` mode is confined to a disposable clone and keeps its patch in the
evidence bundle. A reviewer run in `read-only` mode scans the live tree for new
changes. Neither mode applies a patch to the live tree.

Run it from the package root, the directory that contains `plugin.json`:

```bash
python3 scripts/codex_delegate.py --help
```

Invoking the wrapper without `--validate-only` or `--dry-run` launches a live
`codex exec` subprocess. `--help` does not. `--validate-only` and `--dry-run`
print the envelope and write a validation bundle, and they do not launch
`codex`.

## Flags

| Flag | Meaning |
|---|---|
| `--envelope PATH` | JSON envelope file. When set, the role and task flags are not required |
| `--role coder\|reviewer` | Envelope role. Required when `--envelope` is omitted |
| `--mode read-only\|task` | Write gate. Coder defaults to `task`. Reviewer defaults to `read-only` |
| `--task TEXT` | Task text |
| `--task-file PATH` | Task text read from a file |
| `--model NAME` | Optional model. Omitted, the `codex` binary uses its own default |
| `--effort LEVEL` | Optional reasoning effort |
| `--review-lens adversarial\|quality\|scope-gap\|security-ops` | Reviewer lens. Reviewer defaults to `adversarial` |
| `--write-set PATH` | Repeatable. Required when the mode is `task` |
| `--apply-policy preserve-patch` | The only policy. The patch stays in the bundle |
| `--evidence minimal\|summary\|full` | Bundle detail. Default `summary` |
| `--timeout-seconds N` | Wall-clock limit. Default `900` |
| `--no-output-seconds N` | No-output limit. Default `180`. Must not exceed the wall-clock limit |
| `--no-provenance-required` | Allow a run that does not record model and effort provenance |
| `--validate-only`, `--dry-run` | Check the envelope and write a validation bundle. Do not launch `codex` |
| `--repo-root PATH` | Repository the run is about. Default is the current directory |
| `--run-id ID` | Evidence-bundle directory name. Default is generated |
| `--codex-bin PATH` | `codex` executable. Default is `codex` on `PATH` |

A `task` run requires a non-empty write set. A reviewer envelope must not carry
a write set.

## Evidence

The bundle is `<repo-root>/.claude/codex/runs/<run-id>/`. Pass `--repo-root`
explicitly when the current directory is not the repository being delegated.

## Credentials

This script reads no credential variable and accepts no token flag. The
supervised `codex` process inherits the environment, so whatever that binary
uses to authenticate stays that binary's own login. Do not put a key on the
command line. `codex exec` is skipped unless the operator has already
authenticated that binary.

## Claude Code

The Claude command and the two agents live under `com.infiquetra.claude/`.
They call the same script through `${CLAUDE_PLUGIN_ROOT}/scripts/codex_delegate.py`.
A skill-scoped harness does not have that variable. It runs the package-root
command above.
