# Claude Code front-door architecture

The Claude Code plugin is a blocking file-tool guard and a thin dialogue
adapter. Team Mimir owns path classification, while Hermes owns health,
routing, credentials, dialogue, and any target-created change.

![Claude Code front-door architecture](assets/profile-evolution-claude-code-front-door.png)

## Request flow

1. The file-edit hook executes the active Team Mimir classifier for supported
   Claude Code edit tools.
2. Ordinary repository work continues. Governed or unclassifiable supported
   edits stop with guidance to use the plugin command.
3. The command builds a closed proposal envelope for one named target.
4. Before `suggest`, `reply`, or `resume`, the adapter runs canonical
   `hermes profile-request doctor --target <profile>` and requires the exact
   healthy response.
5. Hermes owns the live dialogue. The target may accept, decline, defer, ask a
   question, or take no action.

## Identity and authority

The proposal names the profile that owns the behavior. The requester and
delegation hop identify Claude Code as a claimed transport harness. They do not
impersonate the target or prove that the target accepted anything.

The plugin cannot edit or commit target behavior, settle a mutation, choose a
provider, store credentials, or operate an offline queue. The supported hook
does not cover Bash or external editors.

The [portability note](../PORTABILITY.md) lists the host-specific differences.
Use the [Team Mimir operator hub](https://github.com/infiquetra/team-mimir/tree/main/docs/team/profile-evolution)
for deployment and activation, and the
[Hermes producer documentation](https://github.com/infiquetra/infiquetra-hermes-plugins/tree/main/docs/profile-evolution)
for canonical request semantics.
