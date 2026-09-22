---
name: deploy-state
description: Infiquetra tag-promotion deployment. Mint a policy tag, report environment drift, preview release notes, or prepare a hotfix. Use for deploy, deploy-status, deploy-notes, and deploy-hotfix.
compatibility: python>=3.12
---

# Deploy State

Use this skill for Infiquetra repository deployment work. It is intentionally separate from
`saga` because deployment mutation deserves a hard boundary.

The capability name is `deploy-state`. The four command behaviors (promote, status, release
notes, hotfix) are this one skill. Claude Code also exposes them as slash commands under the
client extension; other harnesses run the scripts below.

## Running the scripts

The three scripts are standard-library Python. They live in this skill directory so a harness
that installs the skill, rather than the whole package, still has them.

From this skill directory (the installed skill root, or `skills/deploy-state/` in the package):

```bash
python3 scripts/mint_tag.py --help
python3 scripts/query_deployments.py --help
python3 scripts/preview_release_notes.py --help
```

Claude Code installs the package root. From that root the same files are
`${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/scripts/`.

### mint_tag.py

Builds an Infiquetra deployment tag. Without `--dry-run` it creates the tag and pushes it.

| Flag | Required | Meaning |
|---|---|---|
| `--env` | yes | `nonprod`, `staging`, or `production` |
| `--version` | no | `1.2.3`, or hotfix form `1.2.3.1`. When omitted, nonprod uses the latest snapshot tag, staging uses the current nonprod deployment, and production uses the current staging deployment |
| `--repo` | no | Repository name or `owner/name`. When omitted, the `origin` remote of the current git checkout, which must be `github.com/infiquetra/*` |
| `--ref` | no | Commit-ish to tag. Default `HEAD`. A value other than `HEAD` is a hotfix and requires `--version` |
| `--rollback` | no | Mint `rollback-<env>-v<version>` instead of a forward tag |
| `--dry-run` | no | Print the tag, the ref, and the git commands. Do not create or push a tag |
| `--force-unhealthy` | no | Promote even when `unhealthy-v<version>` exists, after the operator has verified the snapshot by hand |

`--dry-run` still resolves the repository and may call `git` and `gh` to infer a version. It does not push.

### query_deployments.py

Prints the latest tag-promotion deployment in `nonprod`, `staging`, and `production`, and whether those versions drift.

| Flag | Required | Meaning |
|---|---|---|
| `--repo` | no | Repository name or `owner/name`. Same default as `mint_tag.py` |

### preview_release_notes.py

Prints a short summary of the commits and files between two refs. It does not create a GitHub release.

| Flag | Required | Meaning |
|---|---|---|
| `--repo` | yes | `owner/name` |
| `--base` | yes | Base ref or tag |
| `--head` | yes | Head ref or tag |

### Credentials

The scripts do not read a credential variable. `mint_tag.py` and `query_deployments.py` call `git` and the GitHub CLI (`gh`). `preview_release_notes.py` calls `gh`. When `GH_TOKEN` or `GITHUB_TOKEN` is set, `gh` uses that variable. This skill never asks for the value and never writes it down. A run with neither variable set and no existing `gh` login fails at the CLI.

Pushing a tag uses the git credentials already configured for that checkout. `--dry-run` does not push.

### Which harness runs what

- Claude Code installs this package from the catalog marketplace. The slash commands `/deploy`, `/deploy-status`, `/deploy-notes`, and `/deploy-hotfix`, and the `release-orchestrator` agent, live under `com.infiquetra.claude/`. They call the scripts above.
- OpenCode, Gemini CLI, Muse, and Hermes install this skill directory. Run the scripts from that directory.
- A harness that installs the package root finds the same scripts at `skills/deploy-state/scripts/`.

This package has no Model Context Protocol (MCP) server.

## Source Of Truth

- Link to the Infiquetra context library instead of copying long-lived policy text.
- Search the context library for ADR-0004 before changing deployment behavior.
- Also reference the current CI/CD standards and repository-local workflow files under
  `.github/workflows/`.
- If the target repository does not resolve to `github.com/infiquetra/*`, stop before mutation.

## Environments

Infiquetra tag-promotion environments:

| Environment | Tag Prefix | Purpose |
|-------------|------------|---------|
| `nonprod` | `nonprod-v` | First automated integration environment. |
| `staging` | `staging-v` | Candidate validation before production. |
| `production` | `production-v` | Customer-facing production promotion. |

Rollback tags use `rollback-<environment>-v<version>`. Hotfix tags use the same environment
prefix with an explicit hotfix version such as `production-v1.2.3.1`.

## Deployment Workflow

1. Resolve the repository and reject non-Infiquetra owners.
2. Inspect `.github/workflows/` and classify whether tag-promotion is full, partial, or absent.
3. Infer versions only from policy-safe sources: latest snapshot for nonprod, current nonprod for
   staging, current staging for production.
4. Refuse forward promotion when `unhealthy-v<version>` exists unless the user explicitly chooses
   an audited override after manual verification.
5. Preview the tag, target ref, workflow URL, and release notes.
6. Require explicit confirmation before pushing tags for staging, production, rollback, or hotfix.
7. Push the tag only after checks and approval are clear.
8. Capture the GitHub Actions URL, deployment status, tag, commit SHA, and issue or PR links.

## State Model

Durable evidence belongs in the repository:

- Release notes or deployment notes in repo docs when the repo already has that convention.
- Issue comments through `mission-control` when an SDLC issue exists.
- PR comments when deployment is tied to a PR.

Runtime scratch belongs under ignored local state such as `.claude/saga/` or a
deployment-specific cache. Do not commit raw API responses or validator JSON.

## Accepting a saga handoff

When promoting on behalf of a saga-tracked item, `saga`'s `/work` mints an **offer** (an ack
token + a gate-or-auto payload) at or after merge via the saga package's
`scripts/deploy_handoff.py offer`. In this catalog that file is
`plugins/saga/scripts/deploy_handoff.py`. It is not part of deploy. Ownership is not considered
transferred until `deploy` explicitly **acknowledges (ack)** it — an offer alone is never read
as "done".

1. Read the offer before promoting:

   ```bash
   python3 plugins/saga/scripts/deploy_handoff.py read --saga-id <saga-id>
   ```

2. Record the write-once ack once you take the item:

   ```bash
   python3 plugins/saga/scripts/deploy_handoff.py accept \
     --saga-id <saga-id> --token <token-from-offer> \
     --by <identity> --evidence <durable-evidence-e.g.-PR-or-tag-url>
   ```

   A double-accept, an accept without a matching offer, or a stale (superseded) token is refused.

3. **Apply the gate-or-auto rule before promoting** — do not decide gate-vs-auto by convention.
   Read the payload from the offer (`deploy_handoff.py read`); the rule below is implemented
   mechanically as `authorize_promotion` in the saga package's `scripts/deploy_handoff.py`. The
   payload is `gate` or `auto`, captured once at saga intent time and carried unmodified with the
   offer:
   - `gate` **always** blocks pending explicit operator confirmation. A `gate` payload is never
     silently overridden to auto-fire, regardless of environment.
   - `auto` authorizes unattended promotion for `nonprod` only; `staging` and `production` always
     require explicit confirmation regardless of payload.
4. An unacknowledged offer reads `handed-off-unacknowledged` on
   `deploy_handoff.py reconcile --saga-id <saga-id>` (or `--all` for a sweep) — treat that as a
   dropped baton, not a clean state, and accept it before proceeding.

This ack contract is scoped to the saga -> deploy edge and does not change tag-promotion
mechanics, environment model, or the confirmation requirements in "Deployment Workflow" above.
