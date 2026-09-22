# Delegation Contract

`agy` delegation is centered on the `agy.delegation.v1` envelope. The command and agents construct
that envelope; `plugins/agy/scripts/agy_delegate.py` validates it, runs Antigravity, records
evidence, and decides whether a patch may be preserved or imported.

## Envelope Fields

```json
{
  "schema": "agy.delegation.v1",
  "role": "coder",
  "mode": "patch-only",
  "task": "Implement the requested bounded change.",
  "model": "flash",
  "review_lens": null,
  "write_set": ["plugins/agy/scripts/agy_delegate.py"],
  "apply_policy": "preserve-patch",
  "evidence": "summary",
  "verification": {
    "commands": ["PYTHONPATH=. python3 -m pytest -q tests/test_agy_delegate_contract.py"],
    "required": true,
    "run_scope": "clone"
  },
  "timeout_seconds": 900,
  "no_output_seconds": 180,
  "provenance_required": true
}
```

Field rules:

- `schema` must be `agy.delegation.v1`.
- `role` must be `coder` or `reviewer`.
- `mode` must be `no-write` or `patch-only`.
- `task` and `model` must be non-empty strings.
- `review_lens` may be `null`, `adversarial`, `quality`, `scope-gap`, or `security-ops`.
- `write_set` must contain repo-relative paths only. Absolute paths and `..` are invalid.
- `apply_policy` must be `preserve-patch`.
- `evidence` must be `minimal`, `summary`, or `full`.
- `verification.commands` must be a list of non-empty strings supplied by the orchestrator or
  operator, not by the delegate. When `verification.required` is `true`, at least one command is
  required. `verification.run_scope` must be `clone` or `none`.
- `timeout_seconds` and `no_output_seconds` must be positive integers, and `no_output_seconds`
  must not exceed `timeout_seconds`.
- `provenance_required` must be a boolean.

## Modes

The wrapper is the only supported execution path for every mode. **No mode writes the live tree.**
Every run happens in a disposable, remotes-stripped clone and returns a patch for the caller to
apply — the same contract the codex plugin has always had.

- `no-write`: review or analysis only. No mutation is expected; a changed path in the clone is
  reported as `out_of_scope_mutation`.
- `patch-only`: preserve a derived patch in the evidence bundle without applying it.

Reviewer delegation defaults to `no-write`. Coder delegation defaults to `mode=patch-only`.
`apply_policy` is always `preserve-patch`.

The live-apply mode `auto-if-clean` was retired in 0.6.0 (#671) along with the lease-broker
admission, renewal, and settlement machinery that fenced it. Concurrent-write safety is a planning
concern: assign work units that do not cross files, or sequence the writes. An envelope requesting
`auto-if-clean` is now rejected as an invalid `mode` value before any bundle is created.

## Verification

Declared verification commands run inside the disposable clone on a `patch-only` run, after the
delegate's changes and before the patch is reported. `no-write` runs skip them — the clone is
unchanged, so the result would prove nothing.

`verification.required` decides whether a failure is terminal:

- required and failing → `checks_failed`
- unrequired and failing → recorded in `checks.json`, run stays `patch_ready`
- none declared, or `run_scope` is not `clone` → `passed` is `null` with a `skipped_reason`

Before 0.6.0 these commands were reachable only from the retired apply path, so a `patch-only` run
recorded `passed: null, commands: []` even when it declared `required: true`.

## Bridge-Agent Contract

Packaged bridge agents are Bash-only. `agy-coder` and `agy-reviewer` have `tools: Bash` and must
invoke exactly one foreground wrapper run per delegated turn:

```bash
python3 plugins/agy/scripts/agy_delegate.py
```

They must not use direct Claude repo file tools such as Read, Edit, MultiEdit, Write, NotebookEdit,
Glob, Grep, or LS to inspect, solve, patch, or review the repository.
Direct Read/Edit/Write solving is a contract breach. They also must not call raw `agy`, use
background or detached launch paths, commit, push, rewrite history, edit remotes, open PRs, change
remote state, or perform deployment or production actions. The wrapper invokes `agy` in foreground
print mode. `no-write` runs with `--sandbox`; patch-producing modes run with
`--dangerously-skip-permissions` inside the disposable clone so print mode cannot stall on tool
permission prompts. V1's enforceable guarantee is repository patch import safety through the
disposable clone and apply gate, not broad machine-level containment.

The coder packet should frame the delegate as an expert software engineer, instruct it to
read-broad/write-narrow, name the exact write-set, include orchestrator-supplied verification
commands, require `PLAN_GAP:`, `TEST_CONFLICT:`, and `PATH_MISSING:` markers when blocked, and ask
for a run report covering changed files, checks run, checks not run, evidence, and residual risk.

The reviewer packet defaults to `role=reviewer`, `mode=no-write`, and `review_lens=adversarial`.
The only supported review lenses are `adversarial`, `quality`, `scope-gap`, and `security-ops`;
lens changes belong in the envelope, not in additional agents.

## Evidence

Every wrapper run writes a local bundle under:

```text
.claude/agy/runs/<run-id>/
```

The projection returned to Claude Code must include the bundle path. If the wrapper cannot write
the bundle, the run fails.

Validation-only wrapper runs write this minimum bundle:

```text
.claude/agy/runs/<run-id>/
  envelope.json
  prompt.txt
  command.json
  run-lease.json
  result.json
  projection.md
```

Launched wrapper runs execute `agy` inside a disposable clone and add write-policy evidence:

```text
.claude/agy/runs/<run-id>/
  worktree/
  stdout.log
  stderr.log
  agy.log
  diff.patch
  changed-paths.json
  checks.json
  git-proof.json
```

`projection.md` is emitted to stdout. `diff.patch`, `changed-paths.json`, and `git-proof.json`
are derived from the disposable clone relative to the recorded base SHA. The clone remotes are
removed before `agy` runs.

## Status Enum

Wrapper result statuses are snake_case:

- `success`
- `patch_ready`
- `plan_gap`
- `test_conflict`
- `path_missing`
- `timeout`
- `no_output`
- `fallback_suspected`
- `out_of_scope_mutation`
- `checks_failed`
- `shutdown_incomplete`
- `bundle_failed`
- `error`

## Prompt Surface Rule

Packaged commands and bridge agents invoke:

```bash
python3 plugins/agy/scripts/agy_delegate.py
```

They do not expose raw `agy`, background execution, direct file editing, local solving fallback, or
a second execution path.
