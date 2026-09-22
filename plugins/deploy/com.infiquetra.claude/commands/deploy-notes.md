---
name: deploy-notes
description: Preview release notes for an Infiquetra tag-promotion deployment
argument-hint: "[base-ref] [head-ref]"
---

Preview deployment notes before promotion.

## Instructions

1. Load `deploy/skills/deploy-state/SKILL.md`.
2. Use `plugins/deploy/scripts/preview_release_notes.py` to inspect the commit
   range and produce a concise operator-facing summary.
3. Include issue links, PR links, deployment tags, checks, and risk notes when available.
4. Do not create GitHub releases unless the user explicitly asks for that mutation.

Arguments provided to the command:

`$ARGUMENTS`
