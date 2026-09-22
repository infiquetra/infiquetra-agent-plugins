---
name: deploy-hotfix
description: Prepare and promote an Infiquetra hotfix tag through the deployment workflow
argument-hint: "[staging|production] [hotfix-version] [--dry-run]"
---

Prepare an Infiquetra hotfix deployment.

## Instructions

1. Load the deploy-state skill at `${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/SKILL.md`.
2. Verify the issue, regression scope, rollback path, and target environment.
3. Use `${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/scripts/mint_tag.py`, the same script as
   `/deploy`. Hotfix versions normally use an extra patch segment such as `1.2.3.1`, passed with
   `--version`, and a non-HEAD `--ref` when the hotfix commit is not the snapshot tag.
4. For production hotfixes, require explicit user approval before tag push.
5. Update the related issue with the tag, workflow URL, checks, and follow-up risks.

Arguments provided to the command:

`$ARGUMENTS`
