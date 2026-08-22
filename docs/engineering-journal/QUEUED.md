# Queued work - infiquetra-agent-plugins

## P0

### Re-run the ten-client matrix and the readback against the resynced package

**Author.** Jeff Cox and Claude

**Priority.** P0

**Effort.** One operator-run session: re-run the four stages against all ten clients,
re-read the installed bytes back in each client, publish the new matrix as current, and
mark the present one superseded by it.

**Worth it when.** Now. Eight tests in
[`tests/test_check_compatibility_matrix.py`](../../tests/test_check_compatibility_matrix.py)
are failing, and they stay failing until this runs. This is the only honest way to clear
them.

**Context.** Re-synchronizing the portable Fleet Core slice to 0.25.1 regenerated both
`skills/*/scripts/_bundled/retry_backoff.py` bundles and re-pinned
`plugins/unifi/PROVENANCE.json`. All three files live inside `plugins/unifi/`, so the
package tree digest moved from `6e6b57c1…` to `da46ca77…` and the two evidence documents
stopped identifying the shipped tree. The file count is unchanged at 23; only the digest
moved, and no UniFi source byte changed. The binding is working exactly as designed: it is
reporting that the record describes a package that no longer ships.

**Do not close this by editing the number.** The matrix says so in its own text —
"There is deliberately no flag that writes that fingerprint back into this document.
Refreshing the numbers without re-running the assessment is precisely the failure this
binding exists to catch." Marking the current matrix superseded does not work either: the
supersession contract requires a named successor that is itself current, and there is none
until the re-run produces one.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[post-activation readback](../evidence/2026-08-22-unifi-post-activation-readback.md),
[decision](DECISIONS.md#a-re-synchronization-does-not-renumber-the-evidence-it-invalidates),
[learning](LEARNINGS.md#regenerating-a-build-artifact-retires-the-observational-evidence-bound-to-it)

### Emit the declared Fleet Core bundle so the package has a working entrypoint

**Author.** Jeff Cox and Claude

**Priority.** P0

**Effort.** One implementation unit: emit the declared module into the package, add a
presence check to the repository validator, and re-run the invocation stage.

**Worth it when.** Before anyone installs or uses the portable UniFi package, and before
any client-specific remediation is considered. This blocks real use on every client and
is independent of all of them.

**Recording only.** This entry records a finding. No repair has begun, and none may begin
without a separate operator decision, under the
[operator pause](DECISIONS.md#pause-the-pilot-at-the-compatibility-matrix-and-take-no-client-specific-remediation).

**Context.** Both skill entrypoints import `fleet_commons_shim` at module import time and
abort with `ModuleNotFoundError` before parsing any argument.
[`plugins/unifi/fleet-bundle.json`](../../plugins/unifi/fleet-bundle.json) declares the
`retry_backoff` module that would replace the dropped shim, but no bundle was ever written
into the package. Every repository check passes anyway, because the bundle checks validate
correctness-when-present rather than presence. The fix has two halves that must ship
together: emit the bundle, and make an unemitted declared module a validation failure.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[learning](LEARNINGS.md#a-package-can-satisfy-every-structural-check-and-still-have-no-working-entrypoint)

## P1

### Decide the Python floor the Fleet Core resync raised

**Author.** Jeff Cox and Claude

**Priority.** P1

**Effort.** One operator decision, then either an upstream repair released and
re-synchronized, or a floor change across the catalog's documentation and the ported-plugin
continuous-integration job.

**Worth it when.** Before the portable catalog is offered to anyone running Python 3.10,
and before the ported-plugin job is trusted as a floor check.

**Context.** Fleet Core 0.25.1 added `from datetime import UTC` at
[`plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:28`](../../plugins/fleet-core/scripts/fleet_commons/retry_backoff.py).
`datetime.UTC` exists only in Python 3.11 and newer; under 3.10 that line raises
`ImportError`, verified against a 3.10.20 interpreter. The catalog documents a 3.10 floor
and [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) pins Python 3.10 for the
ported-plugin job precisely so the floor is exercised. The byte-copy rule forbids repairing
this downstream, because an edit here would make the path diverge from its source and give
`retry_backoff` a second writable source.

**The two options.** Author the repair upstream — `timezone.utc` is available on every
supported version and the change is one line — release it, and re-synchronize. Or move the
declared floor to 3.11, which means the changelog note, the ported-plugin job's pinned
interpreter, and any other place the catalog states 3.10, all moving together.

**Refs.** [learning](LEARNINGS.md#a-byte-copy-imports-the-upstream-platform-floor-along-with-the-upstream-fix),
[the 0.25.1 changelog entry](../../plugins/fleet-core/CHANGELOG.md)

### Decide, per client, what follows the compatibility matrix

**Author.** Jeff Cox and Claude

**Priority.** P1

**Effort.** One operator decision session; any resulting repair is separately scoped work.

**Worth it when.** After the operator has read the matrix and before any remediation is
attempted. The pilot is paused here on purpose.

**Context.** Ten clients were assessed identically across placement, discovery, load, and
invocation. Eight consumed the portable package or its skill units directly. OpenAI Codex
is recorded as works through an adapter: it needs a marketplace manifest to be reachable
at all, and building that adapter is remediation. Cursor Agent is recorded as failed: it
could not be assessed credential-free, and its marketplace accepts only a git repository
URL, so a local directory is not a path there under any credentials. Each of those two
clients needs its own decision among repair, an adapter, a different distribution path, or
an explicitly unsupported status.

**Guardrail.** Coverage was mandatory and passing was not. No failing client blocks the
pilot, and no client-specific remediation has begun or may begin without a separate
operator decision.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[operator pause decision](DECISIONS.md#pause-the-pilot-at-the-compatibility-matrix-and-take-no-client-specific-remediation),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

### The documented default site-profile runtime path is never read

**Author.** Jeff Cox and Claude

**Priority.** P1

**Effort.** One implementation unit spanning the portable profile contract, the discovery
and drift reporting that consume it, and the Claude adapter's loader, with their tests.

**Worth it when.** Before a second operator deploys a site profile on a host this
repository does not control. The Infiquetra instance is already covered by its deployment;
every other operator is not.

**Context.** The portable contract resolves a profile in this order: the
`UNIFI_SITE_PROFILE` environment variable, then the path remembered in `config.json`, then
no profile at all. The same contract separately documents
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/site-profile.json` as the deployed runtime
default. Nothing reads that default directly. An operator who deploys a profile there
without also setting the environment variable silently gets discovery-only mode. This was
found during the pilot, when a correctly deployed profile produced `mode=discovery-only`
with zero subjects.

**Status update, 2026-08-22.** Closed for Infiquetra in the private `home-lab` repository
by having the Ansible deployment also write `config.json`, so the remembered rung resolves
the deployed file. The portable resolution order was deliberately left unchanged by
operator decision, which is what keeps this item open rather than shipped.

**Still open.** The general fix adds the default runtime path as a final resolution rung,
touching the portable site-profile module, the discovery and drift reporting that read it,
and the Claude adapter's `site_profile_loader.py`, each with its tests. Adding a rung
changes what an existing host resolves, so it is a contract change and not a patch.

**Refs.** [Resolution-order decision](DECISIONS.md#leave-the-portable-profile-resolution-order-at-two-rungs-and-close-the-infiquetra-gap-in-deployment),
[seam learning](LEARNINGS.md#every-unit-passed-its-own-tests-and-the-defect-lived-in-the-seam-between-two-correct-units),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

## P2

### Give the synchronization script a Fleet Core target

**Author.** Jeff Cox and Claude

**Priority.** P2

**Effort.** One implementation unit: generalize the script's single-package constants into a
per-package target, add the Fleet Core target with its one byte copy and its one derived
test, and extend [`tests/test_sync_vendor_source.py`](../../tests/test_sync_vendor_source.py)
to cover it.

**Worth it when.** Before the next Fleet Core release has to be re-synchronized, so the
second package goes through the same contract as the first rather than beside it.

**Context.** [`scripts/sync_vendor_source.py`](../../scripts/sync_vendor_source.py) derives
only `plugins/unifi/`: `SOURCE_PACKAGE_PATH` and `TARGET_PACKAGE` are module-level constants
naming that one package, and there is no Fleet Core target anywhere in the file. The plan's
requirement R32 says the Fleet Core slice is derived "under the same synchronization rule as
UniFi", and today that rule is enforced by the provenance digest check rather than by a
shared code path.

**How the 0.25.1 resync worked around it.** The module was extracted with
`git show <commit>:<source_path>` and the ported test was re-derived by applying the recorded
`guard-pytest-import` rule to the same source bytes — the same primitive the script itself
uses internally to read a source byte, so the copy was a mechanical extraction from the
pinned revision rather than a hand edit. `scripts/check_repo.py` then recomputed and matched
every digest. That is sound but unshared: the next person has to know to do it the same way.

**Refs.** [`plugins/fleet-core/PROVENANCE.json`](../../plugins/fleet-core/PROVENANCE.json),
[the pilot plan's requirement R32](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

### Drop README.md from the UniFi byte-copy table so a resync keeps the portable docs

**Author.** Jeff Cox

**Priority.** P2

**Effort.** One line in `scripts/sync_vendor_source.py`
(`PORTABLE_BYTE_COPIES`) plus the fixture expectations in
`tests/test_sync_vendor_source.py`. The live `PROVENANCE.json` entry is already
`target-owned`.

**Worth it when.** Before the next authorized `synchronize()` of the UniFi
package. Until then, `tests/test_unifi_readme.py` fails closed if a resync
restores the Claude README, so the defect cannot return unnoticed; a
deliberate sync would still have to fight that test.

**Context.** Consensus C5 rewrote `plugins/unifi/README.md` for the portable
package. The sync script still lists `README.md` as an upstream byte copy, and
that tuple is owned by the C8 path-safety repair running concurrently, so this
unit did not edit it. `target_owned_paths()` would record the rewritten README
as target-owned automatically once it is no longer in the managed set.

**Refs.** [README custody decision](DECISIONS.md#the-portable-unifi-readme-is-target-owned-rewritten-site-neutral),
[byte-copy README learning](LEARNINGS.md#a-byte-copied-readme-describes-the-source-package-not-the-derived-one)

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
[archived pilot decision](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate),
[current Saga Plan](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/saga/skills/plan/SKILL.md),
[current Saga Code Review](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/saga/skills/code-review/SKILL.md).

## P3

No items.

## Maybe

### Keep the matrix binding an identity check; do not add an execution-proof gate

**Author.** Jeff Cox

**Priority.** Maybe

**Effort.** None. Recording only.

**Worth it when.** Only if a later operator separately decides that
proving stage execution needs a new evidence mode. Not as a repair of
cycle-two open item O7.

**Recording only.** This entry records an operator ruling. No repair has
begun, and none is authorized. The finding is a non-blocking evidence
limitation, not a new gate. Do not add a blocking check. Do not weaken
the existing matrix binding.

**Context.** Ox Alpha finding F6, consensus O7: the matrix binding proves
the recorded digest identifies the shipped tree. It does not prove the
forty stages were actually executed against that tree — identity is not
execution. The approved plan already requires real runtime execution and
readback in specific places, so a new validator would duplicate intent
the machine still could not enforce:

- Plan unit U11, with requirements R22 and R43: the operator-run
  ten-client, forty-stage assessment (placement, discovery, load,
  invocation) recorded in
  [`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../evidence/2026-08-22-unifi-compatibility-matrix.md).
- Plan unit U9, requirement R40: post-activation installed-version and
  digest readback.
- Plan unit U9, requirement R41: a fresh client session proving the
  three profile states, recorded in
  [`docs/evidence/2026-08-22-unifi-post-activation-readback.md`](../evidence/2026-08-22-unifi-post-activation-readback.md).

**Guardrail.** Do not invent a broader new gate. Do not add a blocking
check. Do not weaken `check_package_binding`.

**Refs.**
[identity-is-not-execution learning](LEARNINGS.md#a-bound-digest-names-the-tree-not-the-forty-stages-that-assessed-it),
[binding decision](DECISIONS.md#bind-a-current-matrix-to-the-tree-it-assessed-and-make-supersession-the-only-exemption),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[Ox Alpha F6](../reviews/2026-08-22-code-review-cycle2-ox-alpha-max.md),
[cycle-two consensus O7](../reviews/2026-08-22-code-review-cycle2-consensus.md).

When work ships or is rejected, move the complete entry to
[ARCHIVE.md](ARCHIVE.md); do not silently delete it.
