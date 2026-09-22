# agy harness proof

Status: passed live run on 2026-06-30

> **Historical record.** This documents what was proven on 2026-06-30 against the then-current
> contract. The coder flow below uses `--mode auto-if-clean --apply-policy apply-if-clean`, which
> was retired in 0.6.0 (#671) along with the lease broker that fenced it; a delegation no longer
> writes the live tree. The commands are preserved as run, not corrected — do not copy them.

This document records the release-gate proof for packaged `agy-coder` and `agy-reviewer`
teammates. Static tests are not enough for this plugin: the gate requires Claude Code transcripts
showing that the packaged agents invoked `plugins/agy/scripts/agy_delegate.py` and did not solve
with direct Claude repository file tools.

## Tooling

- Claude Code: `2.1.195`
- agy: `1.0.14`
- Plugin source: `plugins/agy`
- Audit command:

```bash
python3 plugins/agy/scripts/audit_harness_transcript.py <reviewer.jsonl> <coder.jsonl>
```

## Scratch Repo Setup

Create one scratch repo per flow so coder apply proof cannot contaminate reviewer proof:

```bash
mkdir -p .claude/agy/harness
git init "$SCRATCH_REVIEWER"
git init "$SCRATCH_CODER"
```

Each repo must have a committed base before the wrapper launches. `auto-if-clean` requires a clean
live tree before launch.

## Reviewer Flow

The reviewer harness must run Claude Code with the packaged `agy-reviewer` agent and capture
stream JSON:

```bash
claude --plugin-dir plugins/agy \
  --agent agy-reviewer \
  --permission-mode bypassPermissions \
  --allowedTools Bash \
  --disallowedTools Read,Edit,MultiEdit,Write,NotebookEdit,Glob,Grep,LS \
  --output-format stream-json \
  --include-hook-events \
  -p "<reviewer prompt>" \
  > .claude/agy/harness/reviewer.jsonl
```

The prompt instructs the bridge agent to invoke:

```bash
python3 plugins/agy/scripts/agy_delegate.py \
  --repo-root "$SCRATCH_REVIEWER" \
  --role reviewer \
  --mode no-write \
  --review-lens adversarial \
  --task "<bounded review task>" \
  --launch-agy
```

Expected proof:

- Transcript contains a Bash tool call to `plugins/agy/scripts/agy_delegate.py`.
- Transcript contains no Claude `Read`, `Edit`, `MultiEdit`, `Write`, `NotebookEdit`, `Glob`,
  `Grep`, or `LS` tool call.
- The wrapper bundle has `agy_launched=true`.

## Coder Flow

The coder harness must run Claude Code with the packaged `agy-coder` agent and capture stream JSON:

```bash
claude --plugin-dir plugins/agy \
  --agent agy-coder \
  --permission-mode bypassPermissions \
  --allowedTools Bash \
  --disallowedTools Read,Edit,MultiEdit,Write,NotebookEdit,Glob,Grep,LS \
  --output-format stream-json \
  --include-hook-events \
  -p "<coder prompt>" \
  > .claude/agy/harness/coder.jsonl
```

The prompt instructs the bridge agent to invoke:

```bash
python3 plugins/agy/scripts/agy_delegate.py \
  --repo-root "$SCRATCH_CODER" \
  --role coder \
  --mode auto-if-clean \
  --apply-policy apply-if-clean \
  --write-set target.txt \
  --verification-command "test \"$(cat target.txt)\" = done" \
  --verification-required \
  --task "<bounded coder task>" \
  --launch-agy
```

Expected proof:

- Transcript contains a Bash tool call to `plugins/agy/scripts/agy_delegate.py`.
- Transcript contains no direct Claude file-editing tool call.
- The wrapper bundle has `agy_launched=true`.
- `target.txt` is modified through the wrapper apply gate, not by Claude Code directly.

The wrapper uses different `agy` permission shapes by mode: reviewer `no-write` runs with
`--sandbox`; coder write modes run inside the disposable clone with
`--dangerously-skip-permissions` so noninteractive print mode can perform the requested edit before
the wrapper derives and imports a patch. The live-tree mutation still crosses the write-set,
verification, and `git apply` gate.

## Live Results

Run directory:

```text
.claude/agy/harness/claude-20260630T055233Z/
```

Transcript audit:

```bash
python3 plugins/agy/scripts/audit_harness_transcript.py \
  .claude/agy/harness/claude-20260630T055233Z/reviewer.jsonl \
  .claude/agy/harness/claude-20260630T055233Z/coder.jsonl \
  --output .claude/agy/harness/claude-20260630T055233Z/audit.json
```

Audit verdict: passed.

Reviewer proof:

- Transcript: `.claude/agy/harness/claude-20260630T055233Z/reviewer.jsonl`
- Bundle:
  `.claude/agy/harness/claude-20260630T055233Z/reviewer-repo/.claude/agy/runs/live-reviewer`
- Transcript classifier: `real`
- Claude file-tool use: none
- Wrapper status: `success`
- Wrapper command observed on transcript line 14.

Coder proof:

- Transcript: `.claude/agy/harness/claude-20260630T055233Z/coder.jsonl`
- Bundle:
  `.claude/agy/harness/claude-20260630T055233Z/coder-repo/.claude/agy/runs/live-coder`
- Transcript classifier: `real`
- Claude file-tool use: none
- Wrapper status: `applied`
- Changed paths: `target.txt`
- Post-apply proof: `only_expected_changes=true`
- Verification: `test "$(cat target.txt)" = done`
- Scratch repo result: `target.txt` contains `done`
- Wrapper command observed on transcript line 14.

Live proof discoveries folded into the wrapper:

- Relative `--repo-root` paths must be resolved before bundle and clone paths are built. Without
  this, wrapper evidence paths can become relative to the disposable clone.
- `agy --sandbox` is appropriate for `no-write`, but for write modes it writes to Antigravity's
  default scratch directory instead of the wrapper clone.
- Patch-producing modes therefore use noninteractive permission approval inside the disposable clone,
  pass the clone through `--add-dir`, and render the absolute clone path in the prompt packet. The
  live tree still changes only through the wrapper's write-set, verification, and `git apply` gate.
