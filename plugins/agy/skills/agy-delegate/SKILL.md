---
name: agy-delegate
description: Build one agy.delegation.v1 envelope and run it through the guarded agy wrapper, which executes in a disposable clone and returns a patch.
compatibility: python>=3.12
metadata:
  when_to_use: Use when the operator calls /agy:delegate or when agy-coder or agy-reviewer must delegate a bounded coding or review task to Antigravity.
---

# Agy Delegate

This skill prepares one `agy.delegation.v1` envelope and invokes the shared wrapper. The wrapper
validates the envelope, runs Antigravity in a disposable clone when asked, records an evidence
bundle, and returns a patch. It never writes the live tree.

The wrapper is the only supported execution path. Do not call raw `agy` directly, do not run a
background or detached path, and do not solve the delegated task locally as a fallback.
Direct Read/Edit/Write solving is a contract breach.

## How to run it

From this skill directory (what OpenCode, Gemini CLI, Muse, and Hermes install):

```bash
python3 scripts/agy_delegate.py --help
python3 scripts/agy_delegate.py --validation-only --task "Describe the bounded task"
```

From a checkout of this catalog, the guarded command the Claude agents emit is the launcher at
the historical path. That launcher executes the same script:

```bash
python3 plugins/agy/scripts/agy_delegate.py --help
```

`python3 plugins/agy/scripts/agy_delegate.py` and `python3 scripts/agy_delegate.py` (from this
directory) are the same program. The Fleet Core modules it needs (`audit_store`,
`bridge_receipt`, `output_attestation`) are the generated files in `scripts/_bundled/` beside the
implementation. Nothing installs Fleet Core separately.

The field contract is in [references/delegation-contract.md](references/delegation-contract.md).

## Flags

| Flag | Meaning |
|---|---|
| `--envelope PATH` | Read an `agy.delegation.v1` JSON envelope instead of assembling one from flags |
| `--repo-root PATH` | Repository the clone is taken from. Default: the current working directory |
| `--run-id ID` | Evidence-bundle id. Default: a new id |
| `--validation-only` | Validate and write the evidence bundle. Do not run `agy` |
| `--dry-run` | Alias of `--validation-only` |
| `--launch-agy` | After validation, run `agy` in the disposable clone |
| `--agy-bin PATH` | `agy` executable. Default: `agy` on `PATH` |
| `--role coder\|reviewer` | Envelope role. Default: `coder` |
| `--mode no-write\|patch-only` | Write gate. Coder default is `mode=patch-only`. Reviewer default is `mode=no-write` |
| `--task TEXT` | Delegated task text |
| `--task-file PATH` | File containing the delegated task text |
| `--model NAME` | Model name passed to `agy`. Default: `flash` |
| `--review-lens adversarial\|quality\|scope-gap\|security-ops` | Reviewer lens. Reviewer default is `review_lens=adversarial` |
| `--write-set PATH` | Repeatable. Repo-relative paths the delegate may change in the clone |
| `--apply-policy preserve-patch` | The only apply policy. The live tree is never written |
| `--evidence minimal\|summary\|full` | Evidence-bundle detail. Default: `summary` |
| `--verification-command CMD` | Repeatable. Command the orchestrator supplies. The delegate must not invent one |
| `--verification-required` / `--no-verification-required` | Whether a failing check is terminal |
| `--verification-run-scope clone\|none` | `clone` runs the commands. `none` records them as skipped |
| `--timeout-seconds N` | Wall-clock limit. Default: `900` |
| `--no-output-seconds N` | Silence limit. Default: `180` |
| `--provenance-required` / `--no-provenance-required` | Whether a missing provenance classification fails the run. Default: required |
| `--audit-store PATH` | Durable audit-store root. Default: `~/.claude/delegation-audit` (Fleet Core's home-relative default). Omit it and the CLI still mirrors there |

A validation-only run writes `.claude/agy/runs/<run-id>/` under `--repo-root` and prints the
projection. `--launch-agy` also runs `agy` inside a remotes-stripped clone of that repo.

## Credentials

The wrapper reads no credential environment variable. It does not take an API key flag. The `agy`
process it starts inherits the parent environment, so authentication stays with the `agy` binary
and is not configured here. Pass `--agy-bin` when the binary is not on `PATH`.

## Required inputs

- `role`: `coder` or `reviewer`.
- `mode`: `no-write` or `patch-only`.
- `task`: bounded task text or a task file path.
- `evidence`: `minimal`, `summary`, or `full`.
- `write_set`: explicit paths bounding what the delegate may change in the clone.
- `verification`: orchestrator-supplied commands when checks are required.

## Shared envelope gate

- A delegation never writes the live tree. Every mode runs in a disposable clone and returns a
  patch for the caller to apply; `apply_policy` is always `preserve-patch`. Concurrent writes are
  prevented by assigning work units that do not cross files, not by a runtime fence.
- Coder delegations default to `mode=patch-only`.
- Reviewer delegations default to `role=reviewer`, `mode=no-write`, and
  `review_lens=adversarial`.
- Supported reviewer lenses are `adversarial`, `quality`, `scope-gap`, and `security-ops`; route
  lens variants through the envelope instead of creating more agents.
- Verification commands are supplied by the orchestrator or operator. The delegated teammate must
  not invent the gate it will be judged by.
- Verification runs inside the disposable clone for `patch-only`, after the delegate's changes and
  before the patch is reported. `verification.required` decides whether a failure is terminal: a
  required command that fails yields `checks_failed`, while an unrequired one is recorded in
  `checks.json` and leaves the run `patch_ready`. `no-write` runs skip verification — the clone is
  unchanged, so there is nothing to verify.
- The wrapper owns evidence capture, provenance classification, and changed-path checks.

## Delegation flow

1. Read [references/delegation-contract.md](references/delegation-contract.md).
2. Normalize the requested role, mode, lens, write-set, evidence level, timeout, and verification
   policy into the `agy.delegation.v1` contract.
3. Write the task to a temporary task file when needed.
4. Invoke exactly one wrapper run through `plugins/agy/scripts/agy_delegate.py`, or through
   `scripts/agy_delegate.py` when this skill directory is the install root.
5. Report only the wrapper projection and evidence bundle path.

Each follow-up delegation is a fresh wrapper invocation unless a later wrapper version explicitly
adds stateful conversation support.
