# Queued work - infiquetra-agent-plugins

## The link checker validates against the filesystem, not against the repository

`check_repo.py` resolves each local markdown link with `(document.parent /
target).resolve()` and accepts it if `.exists()` returns true. Nothing requires
the target to stay inside the repository, so a link that escapes the root passes
on any machine where the neighbouring path happens to exist and fails everywhere
else.

That is not hypothetical. A journal entry in this repository linked
`../../../infiquetra-claude-plugins`, which resolves in a working tree that has
the upstream repository checked out beside it. The gate passed locally, every
time, and failed in CI where only this repository exists. The link was replaced
with a plain name; the gate that let it through was not changed, because that is
outside the repair authorized for this cycle.

**Why it matters.** A gate whose verdict depends on what else is on the disk is
not a gate — it reports the environment, not the repository. This is the same
shape as the defects the credential rule went through: a check that passes for a
reason unrelated to what it claims to establish.

**Suggested fix.** Reject any local link whose resolved target falls outside the
repository root, with the message naming the escape rather than the missing file.
Pin it with a test that adds an escaping link and expects a finding.

## P0

Nothing open. The one P0 this file carried shipped in `4c1d30f` and is recorded in
[ARCHIVE.md](ARCHIVE.md); it sat here reading "No repair has begun" through four review
cycles before anyone compared it to the tree.

## P1

### Declare the catalog's Python floor in the UniFi skills' frontmatter, upstream

**Author.** Jeff Cox and Claude

**Priority.** P2

**Effort.** One upstream change in `infiquetra-claude-plugins`: add
`compatibility: python>=3.12` to both UniFi `SKILL.md` documents, release it, and take it
here by re-synchronization. Downstream, nothing but a re-sync and a matrix re-run.

**Worth it when.** Whenever the next UniFi re-synchronization happens for another reason.
It is not worth a re-synchronization of its own, because the floor is already declared and
checked in five other places and a consuming client that reads only frontmatter is a
hypothetical, not an observed one.

**Context.** The pilot plan's KTD7 claimed the floor is declared in the skills'
`compatibility` frontmatter field. It never was. Both
[`plugins/unifi/skills/unifi-network/SKILL.md`](../../plugins/unifi/skills/unifi-network/SKILL.md)
and
[`plugins/unifi/skills/unifi-protect/SKILL.md`](../../plugins/unifi/skills/unifi-protect/SKILL.md)
carry only `name` and `description`, and both are classified `upstream-byte-copy` in
[`plugins/unifi/PROVENANCE.json`](../../plugins/unifi/PROVENANCE.json).

**Why it cannot be fixed downstream.** Two independent reasons, either one sufficient.
Adding a field would break digest equality with the source, which is the byte-copy rule the
whole port rests on. And any byte change under `plugins/unifi/` moves the assessed package's
tree fingerprint, which retires the ten-client matrix and the post-activation readback bound
to it — the same eight-test failure the 0.25.1 re-synchronization caused, and one that can
only be cleared honestly by re-running an operator-run ten-client assessment.

**What is enforced meanwhile.** [`tests/test_python_floor.py`](../../tests/test_python_floor.py)
does not require a portable skill to declare `compatibility`, but it does require that one
which declares it declares the catalog floor. So the upstream change can land without a
downstream edit, and it cannot land at the wrong value.

**Refs.** [The floor decision](DECISIONS.md#the-portable-catalogs-minimum-supported-python-is-python312),
[pilot plan KTD7](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

### Decide, per client, what follows the compatibility matrix

**Author.** Jeff Cox and Claude

**Priority.** P1

**Effort.** One operator decision session; any resulting repair is separately scoped work.

**Worth it when.** After the operator has read the matrix and before any remediation is
attempted. The pilot is paused here on purpose.

**Context.** Ten clients were assessed identically across placement, discovery, load, and
invocation. Nine consumed the portable package or its skill units directly. OpenAI Codex is
the one client that did not: it is recorded as works through an adapter, because it needs a
marketplace manifest to be reachable at all, and building that adapter is remediation. It
needs its own decision among repair, an adapter, a different distribution path, or an
explicitly unsupported status.

Cursor Agent was recorded as failed in a superseded publication of the matrix and is now
recorded as works directly. The package did not change to earn that. The earlier run
exported an empty scratch home for isolation, which stripped that client's existing
authentication and measured an unauthenticated client rather than a first-run one; the
recorded failure was an artifact of the harness. Reassessed against the operator's real
home under the same read-only, credential-free rules, its session-scoped local-plugin path
places, discovers, and loads the package and runs its entrypoints. Its marketplace still
accepts only a git repository URL, which is a distribution limitation rather than a
compatibility result, and it is covered by the separate distribution-gap entry below.

**Guardrail.** Coverage was mandatory and passing was not. No failing client blocks the
pilot, and no client-specific remediation has begun or may begin without a separate
operator decision.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[operator pause decision](DECISIONS.md#pause-the-pilot-at-the-compatibility-matrix-and-take-no-client-specific-remediation),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

### The repository carries no marketplace manifest, so it cannot be registered as a catalog

**Author.** Jeff Cox and Claude

**Priority.** P1

**Effort.** Unknown until scoped. Writing a manifest is the obvious move and is explicitly
NOT authorized here; what the format must be, which clients it has to satisfy, and whether
one manifest can serve several are open questions.

**Worth it when.** Before anyone is told this repository can be added to a client as a
catalog. The operator's intended distribution path is catalog registration, and nothing in
the pilot has tested it.

**What it is.** The compatibility matrix proves that the individual `plugins/unifi/` package
installs from a local path. It says nothing about registering *this repository* as a client
marketplace or catalog, which is a different surface and was never assessed for any client.

For Qwen specifically, the two are distinct commands. `qwen extensions install <path>` takes
a package and is what the matrix exercises. `qwen extensions sources add <source>` is the
catalog command, and its own help declares it "Adds a marketplace source (Claude format)".
This repository has no `.claude-plugin/marketplace.json` and no marketplace manifest anywhere
at root level, so it cannot be registered that way today. The related
`marketplace-url:plugin-name` form of `extensions install` presupposes a registered source
and is closed for the same reason.

The gap is at the manifest, not at the client. Nothing published claims otherwise: the
matrix records only package-scoped commands for every client, and its scope section now says
in as many words that catalog registration was not assessed.

**Guardrail.** No manifest may be written and no distribution scope may be widened without a
separate operator decision. This entry records a gap; it does not authorize closing it.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[per-client decision entry](#decide-per-client-what-follows-the-compatibility-matrix)

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

### The ported Fleet Core test still pins the pre-2.0.1 caller shape

**Author.** Jeff Cox and Claude

**Priority.** P2

**Effort.** None remaining. The custody question this entry framed as open was answered by
re-synchronization rather than by decision: the Fleet Core pin moved to `3b5faa6c` for
release 0.25.2, and the ported test was re-derived at that revision by re-applying the
`guard-pytest-import` transform, so it no longer pins a pre-2.0.1 caller shape.

**Status.** Resolved. Retained here only until the next curation pass moves it to
[ARCHIVE.md](ARCHIVE.md); the entry is kept rather than deleted because this journal's
convention is that shipped work is archived, not silently removed.

**What it is.** [`tests/test_retry_backoff.py`](../../tests/test_retry_backoff.py) is a
`guard-pytest-import` version 2 transform of the upstream test at `ed72f439`, the revision
[`plugins/fleet-core/PROVENANCE.json`](../../plugins/fleet-core/PROVENANCE.json) pins. Its
recorded source digest `7d80f735…` still matches the upstream bytes at that revision
exactly, so the port is faithful and the suite passes.

Upstream changed that file at `0d81dd9a`. It inverted
`test_a_caller_that_pre_parses_with_int_still_loses_the_retry` into
`test_a_caller_that_pre_parses_with_parse_retry_after_keeps_the_retry`, because the UniFi
clients that test characterized were repaired in `2.0.1`. The ported copy therefore still
asserts what happens to a caller shape this repository no longer ships.

**Why this is not a defect today.** The assertion is still true of the primitive, which is
what the test exercises; nothing here is failing or lying about the primitive's behaviour.
What is stale is the *scenario* it pins, not the result.

**The custody question.** Re-deriving it means reading the file at `0d81dd9a`, which is
not the revision the Fleet Core slice pins. That slice's own rule is that its pin names the
revision at which the upstream `plugins/fleet-core` subtree last changed — and that subtree
did not change at `0d81dd9a`. So either the derived-test entry gets a pin of its own,
separate from the package pin, or the test waits for the next Fleet Core release. Deciding
that is the work; it should not be settled by whoever next touches the file.

**Refs.** [`plugins/fleet-core/PROVENANCE.json`](../../plugins/fleet-core/PROVENANCE.json)
`derived_files`, [learning](LEARNINGS.md#two-portable-slices-of-one-upstream-repository-can-legitimately-pin-two-revisions)

### Give the synchronization script a Fleet Core target

**Author.** Jeff Cox and Claude

**Priority.** P2

**Status.** Half done. The generalization shipped on 2026-08-23: package identity and the
custody table are now data in [`ports/`](../../ports/README.md), and
`scripts/sync_vendor_source.py` takes `--package NAME`. What remains is the Fleet Core
descriptor itself.

**Effort.** One implementation unit: write `ports/fleet-core.json` with its one byte copy
and its one derived test, and extend
[`tests/test_sync_vendor_source.py`](../../tests/test_sync_vendor_source.py) to cover it.

**Worth it when.** Before the next Fleet Core release has to be re-synchronized, so the
second package goes through the same contract as the first rather than beside it.

**Context.** `plugins/fleet-core/PROVENANCE.json` is currently generated by a different
route than `plugins/unifi/`'s, so writing the descriptor rewrites that manifest. Doing it
in the readiness change would have moved the Fleet Core tree, and a package tree that
moves invalidates evidence bound to its fingerprint — which is why it was left here rather
than folded in. The plan's requirement R32 says the Fleet Core slice is derived "under the
same synchronization rule as UniFi", and today that rule is still enforced by the
provenance digest check rather than by a shared code path.

The remaining blocker named in the entry above still applies: the derived-test pin and the
package pin may legitimately differ, and that has to be decided rather than settled by
whoever next touches the file.

**How the 0.25.1 resync worked around it.** The module was extracted with
`git show <commit>:<source_path>` and the ported test was re-derived by applying the recorded
`guard-pytest-import` rule to the same source bytes — the same primitive the script itself
uses internally to read a source byte, so the copy was a mechanical extraction from the
pinned revision rather than a hand edit. `scripts/check_repo.py` then recomputed and matched
every digest. That is sound but unshared: the next person has to know to do it the same way.

**Refs.** [`plugins/fleet-core/PROVENANCE.json`](../../plugins/fleet-core/PROVENANCE.json),
[the pilot plan's requirement R32](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

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
