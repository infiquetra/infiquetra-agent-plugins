---
name: deploy-status
description: Show Infiquetra deployment status and version drift across environments
argument-hint: "[repo]"
---

Show deployment status for an Infiquetra repository.

## Instructions

1. Load the deploy-state skill at `${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/SKILL.md`.
2. Resolve the repository through
   `${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/scripts/query_deployments.py`.
3. Report the latest `nonprod`, `staging`, and `production` deployments.
4. Strip environment prefixes when comparing versions.
5. Call out drift, missing environments, and the GitHub Actions workflow URL when available.

Arguments provided to the command:

`$ARGUMENTS`
