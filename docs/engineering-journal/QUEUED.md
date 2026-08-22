# Queued work - infiquetra-agent-plugins

## P0

No items.

## P1

### Choose the first portability pilot and custody gate

**Author.** Jeff Cox and Codex

**Priority.** P1

**Effort.** One focused design session followed by a separately approved pilot.

**Worth it when.** Before any existing vendor plugin is migrated or generated
from this repository.

**Context.** The architecture research recommends `home-lab-ops`,
`mission-control`, or `unifi` as the first pilot. The work still needs a chosen
pilot, required client matrix, Herdr boundary, source-custody rule, and semantic
parity evidence.

**Refs.** [Architecture brief](../cross-vendor-plugin-architecture-brief.md),
[repository decision](DECISIONS.md#establish-a-public-cross-vendor-plugin-source-repository)

## P2

### Make code-review lens selection an operator-approved planning contract

**Author.** Jeff Cox and Codex

**Priority.** P2

**Effort.** One focused design and implementation unit during the future Saga
port, followed by cross-vendor compatibility proof.

**Worth it when.** Before Saga Plan and Saga Code Review become authoritative
from this repository.

**Context.** The current Claude Saga Plan does not select the later code-review
lenses. Saga Code Review instead loads the canonical roster, runs its four
always-on lenses, and judgment-selects conditional lenses from the completed
diff. Preserve that diff check, but move the operator decision earlier: Saga
Plan should recommend applicable conditional lenses with reasons and ask the
operator once. The approved roster, roster version, and reasons become part of
the plan contract. The review Arbiter (the Code Review coordinator) compares
the final diff with that contract and asks again only when implementation adds
material scope. Any later roster change must be an operator-approved, versioned
addendum created before findings influence lens selection; the Arbiter must not
silently add or remove lenses after seeing review results. Do not add a ritual
operator question when the approved contract still matches the diff.

**Guardrail.** This entry defers implementation. Do not change the current
vendor Saga plugins or transfer their custody until the relevant portability
pilot and custody decision authorize that work.

**Refs.** [Architecture brief](../cross-vendor-plugin-architecture-brief.md),
[queued pilot decision](#choose-the-first-portability-pilot-and-custody-gate),
[current Saga Plan](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/saga/skills/plan/SKILL.md),
[current Saga Code Review](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/saga/skills/code-review/SKILL.md).

## P3

No items.

## Maybe

No items.

When work ships or is rejected, move the complete entry to
[ARCHIVE.md](ARCHIVE.md); do not silently delete it.
