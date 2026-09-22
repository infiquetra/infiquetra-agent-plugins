# team-scaffold — resumable runbook

Ordered steps to stand up a new team. Deterministic steps are `team-scaffold`
subcommands; **G1/G2** are human portal gates. Every step probes live state and
is idempotent, so a run can pause at a gate and resume later. `.team-scaffold
-state.json` (in the working dir) records progress but is only an optimization —
the live probe is the truth.

| # | Step | Command / actor | Idempotency probe | Rollback |
|---|------|-----------------|-------------------|----------|
| 0 | author + validate spec | `team-scaffold validate-spec team-spec.yaml` | pure | edit spec |
| 1 | create repo | `gh repo create infiquetra/team-<n> --private` | `gh repo view` exists → skip | `gh repo delete` (only if empty) |
| 2 | stamp skeleton + harness | `team-scaffold stamp team-spec.yaml --out <clone>` | per-file; existing files never overwritten | `git checkout -- .` |
| 3 | author SOUL(s) | edit `profiles/<n>/SOUL.md` (or pull live for a promoted agent) | SOUL ≠ placeholder marker → skip | revert file |
| 4 | fill + validate team_profiles | edit `deploy/team_profiles.yml`; `team-scaffold validate-profiles …` | validator clean → skip | edit |
| **G1** | **Discord bot App + token reveal** | Chrome-MCP per `home-lab/Discord-Bot-Creation-Instructions.md` | token var already in vault → skip gate | none (no state change until step 5) |
| 5 | encrypt token → team vault | `ansible-vault encrypt_string --name vault_discord_bot_token_<p> '<tok>'` → append to `…/all/vault.yml` | var present in vault.yml → skip | remove block |
| 5b | (promoted agent) copy block | `team-scaffold vault-wire team-spec.yaml --source <home-lab all.yml> --out <clone>` | var present → skip | remove block |
| **G2** | **GitHub App create + install** | `python3 home-lab/scripts/github_app_provision.py --app <p> --org infiquetra` | App recorded in `identity/README.md` → skip | uninstall App in org |
| 6 | record identity (NAMES only) | edit `identity/README.md` (token var + App slug) | section present → skip | revert file |
| 7 | Discord guild topology | `set_bot_intents.py`, `discord_phase3.py` (only if team needs channels) | scripts are idempotent | re-run scripts |
| 8 | commit + push team repo | git | remote HEAD == local → skip | force-with-lease |
| 9 | home-lab inventory write-back | `team-scaffold register-host team-spec.yaml --apply` | host already in group → skip | `git checkout hosts.yml` |
| 10 | dry-run then real deploy | `ansible-playbook … --limit <host> <team>.yml --check --diff` then live | n/a | reset profile |

## Abort safety

Steps 1–8 touch only the new team repo + external Discord/GitHub identities —
isolated; safe to leave half-built or delete. **Step 9 is the only home-lab
mutation** — keep it last, emit it as one commit, and never run it before step 8
(don't register a host for a team that isn't pushed). Abort of step 9 is a single
`git checkout ansible/inventory/hosts.yml`.

## Brand-new team vs promoted existing agent

- **Brand-new:** SOUL is authored (step 3 placeholder → real); the Discord token
  is freshly revealed (G1) and encrypted (step 5).
- **Promoted existing agent** (host-level agent → its own team): pull the live
  SOUL into `profiles/<n>/SOUL.md` (step 3); the Discord token already exists in
  home-lab `all.yml`, so use `vault-wire` (step 5b) to copy the `!vault` block
  verbatim instead of G1. G2 still applies if the agent needs a GitHub App.

## After scaffolding

Run the generator checks to confirm nothing regressed the scaffold output:

```bash
python3 -m pytest plugins/home-lab-ops/tests -q
python3 plugins/home-lab-ops/skills/team-scaffold/scripts/team-scaffold golden
```

Run both from the catalog repository root. `golden` re-derives the twelve
committed team fixtures. It does not read a machine-specific checkout.
