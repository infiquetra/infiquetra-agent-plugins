---
name: deploy-hotfix
description: Prepare and promote an Infiquetra hotfix tag through the deployment workflow
argument-hint: "[staging|production] [hotfix-version] [--dry-run]"
---

Prepare an Infiquetra hotfix deployment.

## Instructions

1. Load `deploy/skills/deploy-state/SKILL.md`.
2. Verify the issue, regression scope, rollback path, and target environment.
3. Use the same tag-promotion script as `/deploy`; hotfix versions normally use an extra patch
   segment such as `1.2.3.1`.
4. For production hotfixes, require explicit user approval before tag push.
5. Update the related issue with the tag, workflow URL, checks, and follow-up risks.

Arguments provided to the command:

`$ARGUMENTS`
