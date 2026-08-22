# Learnings - infiquetra-agent-plugins

## 2026-08-21

### A plugin's tracked file list does not reveal what it needs to run

**Author.** Jeff Cox and Claude

**Context.** Scoping the UniFi portability pilot from its thirteen tracked files.

**Evidence.** Both UniFi clients call a loader at module import time, not inside a
function, which reaches into a separate plugin the manifest never declares as a
dependency. The loader resolves that plugin four ways and three are host-specific: a
walk-up for the Claude marketplace manifest, a read of Claude Code's installed-plugin
registry, and a scan of a Claude-injected environment variable. Only one path is
host-neutral. Details and line citations are in the [pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md).

**Mechanism.** Because the call runs at import rather than at use, the failure lands
before argument parsing. On a host where the loader finds nothing, every command fails,
including read-only ones that never needed the dependency. Nothing in the file list, the
manifest, or the directory layout shows this; only reading the imports does.

**Generalizable rule.** Before scoping any port, read the target's import statements, not
its file list. An import-time dependency resolved through host-specific discovery is
invisible to packaging and fatal to portability, and a manifest that declares no
dependencies is not evidence that there are none.

---

### Documentation drifts in both directions, and the dangerous direction is over-promising

**Author.** Jeff Cox and Claude

**Context.** Building a behavior-parity inventory for the same pilot.

**Evidence.** A commit five months before the port removed four Protect capabilities
because the older API path rejects key-based authentication. Eighty-one references to
those capabilities survive across six documentation surfaces, including the plugin
manifest's own description. Separately, both API reference documents disagree with the
shipped code on multiple endpoint paths, and the network skill omits four capabilities
that do work.

**Mechanism.** Under-documentation costs a reader a discovery; over-documentation costs
an agent a failed invocation it was told would succeed. An agent loads the skill file,
not the source, so documentation that promises absent commands is not merely stale, it is
an instruction to do something impossible.

**Generalizable rule.** Derive a parity inventory from the code and treat every
documentation surface as a claim to be checked against it. When a port finds drift,
repair it in the authoritative source rather than in the copy, or the two diverge
permanently and neither can be trusted afterwards.

---

### Portable plugin standards do not replace vendor runtimes

**Author.** Jeff Cox and Codex

**Context.** Research compared the plugin and skill surfaces used by the coding
agent clients in the Infiquetra environment.

**Evidence.** The
[cross-vendor plugin architecture brief](../cross-vendor-plugin-architecture-brief.md)
links the Agent Skills and Agent Plugins specifications and records the client
compatibility findings.

**Mechanism.** Agent Skills can carry procedural instructions, and Agent
Plugins can package skills with Model Context Protocol servers. Commands,
hooks, native agent definitions, permissions, user interfaces, and marketplace
distribution remain client-specific.

**Generalizable rule.** Keep the shared behavioral contract portable, but use
explicit adapters for capabilities governed by a vendor runtime. Do not call an
installed or copied vendor package the shared source of truth.

---

Keep newest entries first. When evidence invalidates an entry, preserve the old
text in [ARCHIVE.md](ARCHIVE.md) and link the corrected learning.
