---
name: deploy
description: Promote an Infiquetra repository by minting a policy-compliant deployment tag
argument-hint: "[nonprod|staging|production] [version] [--dry-run]"
---

Promote an Infiquetra repository through the tag-promotion deployment workflow.

## Instructions

1. Load the deploy-state skill at `${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/SKILL.md`.
2. Confirm the target repository resolves to `github.com/infiquetra/*`.
3. Confirm the target environment is `nonprod`, `staging`, or `production`.
4. Preview the tag and workflow URL before mutating anything.
5. Use `${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/scripts/mint_tag.py` for deterministic tag naming.
6. For production, rollback, or hotfix work, state the blast radius and ask for explicit
   confirmation before pushing a tag.

## Quick Reference

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/scripts/mint_tag.py" \
  --env nonprod \
  --version 1.2.3 \
  --dry-run
```

Arguments provided to the command:

`$ARGUMENTS`
