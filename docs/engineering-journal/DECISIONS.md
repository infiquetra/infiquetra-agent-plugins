# Decisions - infiquetra-agent-plugins

## 2026-08-22

### Reclassify both UniFi clients as a deterministic transform rather than a byte copy

**Author.** Jeff Cox and Claude

**Decision.** The two client scripts,
`skills/unifi-network/scripts/unifi_network_client.py` and
`skills/unifi-protect/scripts/unifi_protect_client.py`, move from **upstream byte copy**
to **deterministic transform** under requirement R4's three-way path classification. The
rule is `resolve-bundled-fleet-module`, version 1: it matches the single upstream block
that puts the client's own directory on `sys.path`, imports `fleet_commons_shim`, and
calls `fleet_commons_shim.load(NAME)`, and re-emits it as an insertion of the `_bundled/`
directory beside the client followed by a direct `import NAME`. The rule reads the module
name and the binding out of the source rather than assuming them, changes no other byte,
and raises rather than proceeding when the block is absent or appears more than once.
`plugins/unifi/fleet-bundle.json` declares a destination beside each client, which is
where the pilot plan's assembled-package tree already put the generated bundle.

**Rationale.** The portable package drops both `fleet_commons_shim.py` copies, because
their resolution ladder is Claude-specific runtime discovery the portable package must
not retain. A byte copy of a client that imports a module the package does not carry
aborts at module scope, so the package had no working entrypoint on any client. The
byte-copy rule is not a rule about bytes for their own sake: it exists so a downstream
edit cannot become an unrecorded second source. A versioned rule over the pinned upstream
bytes, with the source digest, the output digest, and the rule text in the provenance
manifest, satisfies that purpose exactly -- the output is reproducible from the source
alone, and re-synchronization re-applies the rule rather than silently restoring the
broken import.

**Rejected alternatives.**

- *Repair it upstream first, as the pilot does for every other divergence.* Upstream is
  a Claude package where `fleet_commons_shim` is present and correct. There is no
  upstream defect to repair, so this would mean degrading the Claude package to suit the
  portable one.
- *Copy `fleet_commons_shim.py` into the portable package.* Prohibited: the operator's
  Fleet Core amendment forbids retaining Claude-specific runtime discovery.
- *Require a `FLEET_COMMONS_ROOT` environment variable, or an Agent Plugins dependency
  field.* Both prohibited by the same amendment. The artifact must be complete at install
  time, with no separate Fleet Core installation.
- *Leave the clients as byte copies and document them as not executable.* This is what
  the package already did. A portable package with no runnable entrypoint is not a
  portability result.

**Revisit when.** Upstream stops importing `fleet_commons_shim` at module scope, or moves
to a mechanism the portable package can carry unchanged. The transform then has no input
to match and refuses to synchronize, which is the deliberate signal to revisit rather
than a failure to work around.

### Guard the join between the bundler and the synchronization in the validator, not only in tests

**Author.** Jeff Cox and Claude

**Decision.** `scripts/check_repo.py` gains `check_fleet_bundle_outputs`, which rejects a
module a consumer's `fleet-bundle.json` declares but no generated bundle carries, and any
file under a `_bundled/` directory that no declaration accounts for. The presence half of
`scripts/bundle_fleet_module.py --check` is factored into `presence_errors` so both
commands report the same two conditions from one implementation. Alongside it,
`tests/test_client_entrypoints.py` runs each shipped client's `--help` in a subprocess,
with third-party transport stubbed and every `UNIFI_*` variable removed, and separately
asserts that deleting the generated bundle from a copy of the package breaks every
entrypoint.

**Rationale.** `check_bundled_files` reads bundles that exist, so a bundle that was never
generated is invisible to it. That is how the repository reported success while shipping
two clients importing a module nothing had written. A validator that only inspects
present files cannot catch an absent one; the declaration is the statement of what should
be present, so comparing the two is the missing assertion. The subprocess test is the
independent signal: it fails whether the cause is the declaration, the transform, or the
bundler.

**Rejected alternatives.**

- *Reuse `check_consumer` wholesale inside `check_repo`.* It also re-checks the stamps,
  which `check_bundled_files` already owns, so one tampered bundle would be reported
  twice in different vocabulary.
- *Rely on the entrypoint test alone.* A test proves the shipped tree works today; the
  validator states the invariant, and continuous integration runs it in the hermetic
  standard-library-only job.

**Revisit when.** A consumer needs a generated bundle outside a `_bundled/` directory,
which would make the directory name the wrong discriminator.

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
