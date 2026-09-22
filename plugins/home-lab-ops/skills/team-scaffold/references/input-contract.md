# team-spec.yaml — input contract

One operator-authored file per team. It carries exactly what the deterministic
pipeline needs; the full per-profile *runtime* config lives in the
operator-authored `deploy/team_profiles.yml` (validated, not generated).

## Schema

```yaml
team:
  name: nyx                       # lowercase slug -> repo = infiquetra/team-nyx, play = nyx.yml
  display: "Nyx (night-shift monitor)"   # -> the play/README "team" string
  host_group: agent_vms           # agent_vms | mac_minis | orchestrator_vms
  limit_host: nyx.infiquetra.com  # --limit target AND the inventory host key
  pin_runtime: false              # true -> emits `hermes_update: false` (shared host)
  coresident: null                # e.g. "Freya" -> co-resident note in play/README
  roles:                          # ordered (role, tags); MUST match the harness exactly
    - {role: ollama, tags: "ollama,nyx"}          # Linux only (per-team inference dep)
    - {role: hermes, tags: "hermes,nyx"}          # required, always
    - {role: hermes_dm_listener, tags: "dm_listener,nyx"}

inventory:                        # used by `register-host` (the one home-lab write-back)
  ansible_host: 10.220.1.71
  ansible_user: agent

profiles:                         # NAMES + token vars only (dir stamping + vault/identity)
  - name: nyx
    persona: nyx
    discord_token_var: vault_discord_bot_token_nyx  # variable name only
    # headless: true             # for headless workers (no persona / no token)
```

## Role conventions (validated)

- `hermes` is always required.
- **Linux** host groups (`agent_vms`, `orchestrator_vms`) require `ollama`
  (per-team local-inference dependency). **macOS** (`mac_minis`) must NOT include
  it (cloud models only).
- `orchestrator_vms` expects the `hermes_orchestrator` role.
- Multi-profile teams that coordinate via kanban add `hermes_team_listener`;
  GitHub-App-rail teams add `hermes_mint_broker` (see team-apollo / team-mimir
  specs under `specs/`).

## How the 12 existing teams map

`specs/team-*.yaml` are materialized from the migration generator's TEAMS dict,
the live `team_profiles.yml` profile refs, and `hosts.yml` inventory. They feed
the generated deploy fixtures checked by `team-scaffold golden`. Use them as
worked examples:

- `specs/team-themis.yaml` — single-profile legacy agent (minimal)
- `specs/team-apollo.yaml` — multi-profile dev team (`hermes_team_listener`)
- `specs/team-hermes.yaml` — orchestrator crew (`hermes_orchestrator`, no per-orch token)
- `specs/team-mimir.yaml` — co-resident on mac mini, `hermes_mint_broker`, headless Sons

## deploy/team_profiles.yml (authored separately)

Not in the spec — author it directly and validate with
`team-scaffold validate-profiles`. Full optional per-profile schema seen across
the fleet: `model`, `reasoning_effort`, `max_turns`, `worker_pool`, `provider`,
`base_url`, `fallback_providers` (list of `{provider, model}`), `skills` (list),
`bot_user_id`, `headless`, and voice fields (`voice_auto_join`,
`voice_channel_id`, `elevenlabs_voice_id`, `tts_provider`, `piper_voice`,
`edge_voice`). Invariants the validator enforces: unique names; `role`+`model`
required; `discord_token_var` matches `vault_discord_bot_token_<persona>`;
headless workers carry no token.
