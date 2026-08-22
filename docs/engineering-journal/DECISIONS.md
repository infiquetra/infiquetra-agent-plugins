# Decisions - infiquetra-agent-plugins

## 2026-08-22

### Pause the pilot at the compatibility matrix and take no client-specific remediation

**Author.** Jeff Cox and Claude

**Decision.** The portability pilot stops at the completed ten-client compatibility
matrix. Two clients did not consume the portable package: OpenAI Codex is recorded as
works through an adapter, and Cursor Agent is recorded as failed. Neither is repaired
here. Whether a given client warrants a repair, an adapter, a different distribution path,
or an explicitly unsupported status is one operator decision per client, and each is taken
separately from this work. The package-side defect that leaves the assembled package with
no working entrypoint is recorded in the same way and is likewise not repaired here.

**Rejected alternatives.** Building the Codex marketplace manifest immediately, because
the matrix would then be reporting on a package that had been changed to make it pass, and
the assessment exists to say what was true of the package as assembled. Dropping the two
non-consuming clients from the matrix, because coverage was the deliverable and a client
recorded as unsupported or failed with its reason is a result, not a gap. Repairing the
missing bundle inside this unit, because a defect found by an assessment is scope the
assessment discovered, not scope it was granted.

**Rationale.** Implementation scope that expands itself the moment it finds a problem
stops being a scope. The matrix was built to inform a decision, and taking the decision
inside the same unit that produced the evidence removes the operator from a choice that is
theirs. Coverage was mandatory and passing was not, which is only true if failures end in
a pause rather than in a repair.

**Revisit when.** The operator has taken the per-client decisions, or the package
entrypoint defect is separately authorized for repair.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[per-client queued decision](QUEUED.md#decide-per-client-what-follows-the-compatibility-matrix),
[queued entrypoint repair](QUEUED.md#emit-the-declared-fleet-core-bundle-so-the-package-has-a-working-entrypoint)

---

### Leave the portable profile resolution order at two rungs and close the Infiquetra gap in deployment

**Author.** Jeff Cox and Claude

**Decision.** The portable site-profile contract keeps resolving exactly two rungs, the
`UNIFI_SITE_PROFILE` environment variable and then the path remembered in `config.json`,
followed by no profile at all. The documented deployed runtime default,
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/site-profile.json`, is not added as a
third rung by this work. The Infiquetra instance closes its own gap in the private
`home-lab` repository, where the Ansible deployment now also writes `config.json` so the
remembered rung resolves the file it just deployed. The general fix stays queued.

**Rejected alternatives.** Adding the default path as a final rung inside this pilot,
because it changes what an already-deployed host resolves and therefore touches the
portable contract, both consumers of it, and the Claude adapter's loader with their tests
— a contract change that deserves its own unit rather than a fix smuggled into a
documentation unit. Making the environment variable mandatory, which would delete the
optional-profile promise the contract exists to keep. Documenting the trap and leaving it
at that, because a documented trap is still a trap.

**Rationale.** The portable contract and the Infiquetra custody instance are separable on
purpose. This repository's normative documentation never presents the private `home-lab`
plus Ansible arrangement as required; it is one operator's deployment of an optional
profile. That separation is exactly what allows the operator's own gap to be closed in
their deployment today while the portable question stays open for a decision that affects
every other operator.

**Revisit when.** A second operator deploys a site profile on a host this repository does
not control, or the queued contract change is authorized.

**Refs.** [Queued contract change](QUEUED.md#the-documented-default-site-profile-runtime-path-is-never-read),
[seam learning](LEARNINGS.md#every-unit-passed-its-own-tests-and-the-defect-lived-in-the-seam-between-two-correct-units),
[site profile reference](../../plugins/unifi/references/site-profile.md)

---

### Keep a generated file's stamp outside the bytes it hashes

**Author.** Jeff Cox and Claude

**Decision.** A generated Fleet Core bundle carries two independent digests. The
source-payload digest covers the upstream module and detects a stale bundle whose source
has moved. The generated-output digest covers the generated file with its own stamp block
excluded, and detects a hand-edited output. `scripts/check_repo.py` reports the two as
different, deterministic failures.

**Rejected alternatives.** One digest over the whole generated file, which is
self-referential and cannot be computed, since the digest would have to appear inside the
bytes it covers. One digest over the source only, which would leave a hand-edited
generated file undetectable — the exact degradation that turns a generated artifact into
an unmaintained copy-paste fork.

**Rationale.** Stale source and tampered output are different problems with different
repairs. Collapsing them into one mismatch tells a maintainer that something is wrong
without telling them which thing, and a signal that needs investigation before it can be
acted on is a weak signal.

**Revisit when.** A second consumer bundles a Fleet Core module and the two-domain scheme
proves awkward, or a generated artifact appears that has no stable stamp location.

**Refs.** [Bundle declaration schema](../../schemas/fleet-bundle.schema.json),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

---

### Keep repository validation standard-library-only and give the ported plugin tests their own job

**Author.** Jeff Cox and Claude

**Decision.** Continuous integration runs two jobs. The repository validation job installs
nothing and runs `python3 scripts/check_repo.py`, the unittest suite, and `git diff
--check`, so the repository's own baseline uses the standard library alone. A second job
installs Python 3.10 with `requests`, `urllib3`, and `pytest`, and runs the ported plugin
tests. Neither job ever contacts a UniFi controller, and the compatibility matrix is
produced by an operator-run assessment rather than by continuous integration.

**Rejected alternatives.** Rewriting the existing pytest tests into unittest so a single
job could run everything, which would discard proven upstream coverage for no behavioral
gain. Installing dependencies in the one existing job, which would make a package index
outage able to break validation of documentation-only changes.

**Rationale.** The repository's fast hermetic baseline is worth protecting as its own
guarantee: it answers whether this repository is internally consistent, using nothing it
has to download. The ported plugin tests answer a different question and legitimately need
third-party packages, so they get a job whose failures mean what they say.

**Revisit when.** The ported packages acquire a dependency the second job cannot install,
or the repository grows a project file that makes a single job hermetic again.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[deferred Fleet Core inventory](../../plugins/fleet-core/DEFERRED.md)

---

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
[archived pilot item](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate)

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
[archived pilot decision](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate)

---

Keep newest entries first. When a decision is superseded, preserve the old text
in [ARCHIVE.md](ARCHIVE.md) and link the replacement.
