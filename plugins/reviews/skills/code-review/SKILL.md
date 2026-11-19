---
name: code-review
description: Review a diff or pull request on a standalone git range and write C1 grades into a packet directory. Use when someone asks to review this PR, do a code review, check a diff, or grade a change. Suggest security-review for a repository security audit, doc-review for a plan, spec, or issue, and review-setup when review tools or the Semgrep rule-pack digest are missing.
---

# Code Review

Review one frozen git range. The packet directory is the record.

The command computes C1 grades, finding identities, and the merge answer. The reviewer supplies evidence for one pass. This skill does not start a second reviewer.

## Prepare

The script is `scripts/review_command.py` at the package root, two directories above this skill. Run that file by its path. Do not resolve the script from the repository checkout you are editing: a standalone install is not that repository's working directory.

```bash
# SKILL_DIR is the directory that contains this SKILL.md.
# CLAUDE_PLUGIN_ROOT is the package root when the package is installed.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  S="$CLAUDE_PLUGIN_ROOT/scripts/review_command.py"
else
  S="$SKILL_DIR/../../scripts/review_command.py"
fi
python3 "$S" prepare \
  --repo <checkout> --base <base-sha> --head <head-sha> \
  --profile <profile-json> --builder-record <builder-record-json> \
  --out .reviews/<name> --home <home>
```

`--issue` is optional metadata for a pull request or a report. Omit it when there is no issue. `--out` is the packet (`.reviews/<name>/` or another directory). A missing lifecycle directory is not an error and is not created.

Read `grades.json`, `degraded.json`, and `where-to-look.json`. A missing tool is a degraded input. It is not a clean result.

## Review

One pass. In this session, answer every `where-to-look.json` item against the packet, or ask the agent-launcher plugin to run one headless review session on this packet.

Write the answer and the transport result as JSON, then finish:

```bash
# $S is scripts/review_command.py resolved above. Resolve it again in a new shell.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  S="$CLAUDE_PLUGIN_ROOT/scripts/review_command.py"
else
  S="$SKILL_DIR/../../scripts/review_command.py"
fi
python3 "$S" finish \
  --packet .reviews/<name> --answer <answer-json> --result <result-json> \
  --home <home>
```

`finish` writes `review-run.json` in the packet. Read its grades, findings, and merge answer. Group findings by severity. Cite file, line, reviewer, confidence, and route. Put degraded inputs and coverage gaps below the findings.

When a pull request exists, publish one comment for the round. Do not submit an approving review from this skill.

## Route

- Every lens at C or better with no blocking items can merge. Fix-later items do not hold it.
- Reproduced data loss or security exposure blocks in every lens.
- Suggest `security-review` for a repository security audit, `doc-review` for a plan, spec, or issue, and `review-setup` when a tool pin or the rule-pack digest is missing.

Follow [formatting-style.md](../../references/formatting-style.md) for the review document.
