# Decisions - infiquetra-agent-plugins

## 2026-08-21

### Choose UniFi plus a portable Fleet Core slice as the first portability pilot

**Author.** Jeff Cox and Claude

**Decision.** Port the Claude `unifi` plugin into a portable Agent Plugins 1.0 package
in this repository, together with a new portable Fleet Core source carrying only the
`retry_backoff` module. The Claude repository is repaired first, released second, and
synchronized from third. Custody does not move.

The load-bearing choices, each recorded in full in the
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md):

- The portable copy is derived and digest-verified, never a second writable source.
- The authoritative source is repaired before the port consumes it; downstream-only
  correction and intentional target divergence are both rejected.
- Extract means relocate, not delete: the embedded lab topology moves into an operator
  site profile, and the repaired release is gated on that replacement path being
  verified so the Claude agent never loses site context.
- Fleet Core becomes a first-class portable source, but only one vertical slice is
  ported; the required module is bundled into consuming artifacts at build time, since
  Agent Plugins 1.0 has no dependency mechanism.
- Compatibility coverage across all ten installed clients is mandatory; passing is not.
  The matrix is a deliverable ending in an operator pause, not a release gate.

**Rejected alternatives.** A hand-port with no drift detection; a subtree or submodule of
the vendor repository; porting the documentation defect verbatim; inlining the retry
primitive and reversing the fleet-wide shared-primitive decision; inventing an Agent
Plugins dependency field; and requiring an environment variable that would resolve to
nothing on a non-Claude host.

**Rationale.** UniFi is small enough to finish and real enough to exercise the actual
architecture boundary. Investigation found three problems the file listing could not
show — an undeclared cross-plugin dependency resolved through Claude-specific discovery,
documentation describing capabilities removed five months earlier, and one operator's
controller address hard-coded as a universal default — and each of them is exactly the
kind of thing a pilot exists to surface before a larger port inherits it.

**Revisit when.** The ten-client compatibility matrix is complete and the operator has
made the per-client decisions that follow it, or evidence shows the build-time bundling
model does not generalize to a second consumer.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[architecture brief](../cross-vendor-plugin-architecture-brief.md),
[superseded parity decision](ARCHIVE.md#void-parity-baseline-recorded-in-error),
[queued pilot item](QUEUED.md#choose-the-first-portability-pilot-and-custody-gate)

---

### Establish a public cross-vendor plugin source repository

**Author.** Jeff Cox and Codex

**Decision.** Use `infiquetra-agent-plugins` as the public repository for the
portable architecture, future shared plugin sources, and explicit vendor
adapters. Existing vendor repositories remain authoritative until a pilot is
proven and custody is moved by a later decision.

**Rejected alternatives.** `infiquetra-plugins` was too broad to distinguish
coding-agent capabilities from other plugin systems. Immediately replacing the
vendor repositories would create an unproved big-bang migration.

**Rationale.** The name identifies the domain, while the staged custody rule
allows shared sources to be proven without breaking current clients.

**Revisit when.** The first portable plugin passes its agreed compatibility
gate, or evidence shows the proposed repository boundary is wrong.

**Refs.** [Architecture brief](../cross-vendor-plugin-architecture-brief.md),
[queued pilot decision](QUEUED.md#choose-the-first-portability-pilot-and-custody-gate)

---

Keep newest entries first. When a decision is superseded, preserve the old text
in [ARCHIVE.md](ARCHIVE.md) and link the replacement.
