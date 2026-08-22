# Learnings - infiquetra-agent-plugins

## 2026-08-22

### A path a manifest names is untrusted input, even when the manifest is ours

**Author.** Jeff Cox and Claude

**Context.** Repairing finding F-06 of the 2026-08-22 code review of the portable UniFi
package, raised independently by the Cursor reviewer and confirmed by the controller.

**Evidence.** `previously_managed()` in
[`scripts/sync_vendor_source.py`](../../scripts/sync_vendor_source.py) accepted any
non-blank `path` string recorded in `plugins/unifi/PROVENANCE.json`, and the stale-cleanup
step in `apply_plan()` then evaluated `plugin_dir / path` and called `unlink()` on it.
Replaying the three attack shapes against the pre-repair script deleted a file planted
outside the package in all three cases: an absolute path, `../../../outside/victim.txt`,
and `skills/escape/victim.txt` reached through a symlink inside the package. The
[Cursor review](../reviews/2026-08-22-code-review-cursor-gpt-5.6-sol-xhigh.md) records the
finding at `scripts/sync_vendor_source.py:635`.

**Mechanism.** Two separate assumptions failed together. First, `pathlib` join is not
containment: `Path("/a/b") / "/etc/hosts"` is `/etc/hosts`, so an absolute string silently
discards the prefix that was supposed to confine it. Second, the repository already
carried the lexical half of the rule — `check_repo.py` rejects absolute and `..`-bearing
provenance paths when it validates a manifest — but that check runs in a different command
than the one that deletes, so the deleting path had no guard at all. A rule enforced by a
validator nobody calls before the dangerous operation is not enforcement. The lexical half
would also not have been enough on its own: a symlink inside the package makes
`skills/escape/victim.txt` lexically innocent and still land outside, which only resolving
the path and comparing it against the resolved package root can see.

**Generalizable rule.** Validate untrusted paths at the operation that acts on them, not
only where they are authored, and validate them twice: lexically, then by resolving and
proving containment. A validator in a different command is documentation, not a control.

### A byte-copied README describes the source package, not the derived one

**Author.** Jeff Cox

**Context.** Consensus C5 (Cursor F-07, OpenCode F-07): the portable UniFi
package's own README introduced the tree as a Claude Code plugin and told
readers to run `pytest tests/test_unifi_network_client.py` and
`tests/test_unifi_protect_client.py`, neither of which exists in this
repository.

**Evidence.**
`plugins/unifi/README.md` at the reviewed commit opened "Claude Code plugin
for managing…". `plugins/unifi/PROVENANCE.json` classified that file as
`upstream-byte-copy` with digest `a3b3b056…`, matching the Claude plugin
README at the pinned source. The plan labelled the same path "portable core,
rewritten site-neutral". The two statements cannot both be true of one file.
Fixed in this repair: the README is rewritten for this package, the provenance
entry is `target-owned`, and `tests/test_unifi_readme.py` reads the shipped
file the way a consumer does.

**Mechanism.** Synchronization treats an upstream byte copy as a success when
the bytes match the source. That is the right rule for a skill or a client.
It is the wrong rule for package documentation whose subject is the derived
tree: the client extension directory, the Fleet Core bundle, the site-profile
contract, and the commands that run here. Copying the source README faithfully
is how the portable package documented a plugin it is not, and named tests it
does not ship.

**Generalizable rule.** A derived package whose identity differs from its
source cannot keep the source README as a byte copy. Package documentation is
about the assembled artifact; if that artifact is not the source, the README
is target-owned (or a named transform), not a digest match.
### A check that cannot be evaluated must not return the permissive answer

**Author.** Jeff Cox and Claude

**Context.** Two independent reviews of the portable UniFi package, reconciled in
[the review consensus](../reviews/2026-08-22-code-review-consensus.md), each found a
runtime defect in the discovery and drift scripts. The two look unrelated — one is a
false drift finding, the other a persistence deny-list — and they are the same mistake.

**Evidence.** Both reviewers independently reported the drift defect (consensus item C2,
Cursor F-03 and OpenCode F-03, both rated P1). `drift.report` compared the profile's
intended policies against `inventory["policies"]`, which `discover.py` assigned as an
unconditional empty list because the read-only catalog composes no policy list
operation. Every intended policy therefore produced a `missing-policy` finding on every
live run, including for policies that exist on the controller. The persistence defect
(consensus item C10, OpenCode F-06, P2) is in `refuse_repository_output`: it resolved the
working tree by walking up for a `.git` entry, and when that walk found nothing it
returned the output path unrefused, so discovery run from a copy of the package without a
checkout could write an unfiltered controller response into the package directory.

**Mechanism.** In both places a guard reached a state where it had no answer, and
returned the answer that permits. Drift asked "is this policy on the controller?" of a
list nothing had ever looked at, and read the empty list as "no". Persistence asked "is
this path inside the working tree?" with no working tree to compare against, and read the
unanswerable question as "no". Neither failure is visible from inside the guard: an empty
list and a `None` root are both ordinary values, and the permissive branch is the one
with no error to raise. Both were also locked in by tests, which asserted the false
`missing-policy` finding as expected output and exercised persistence only with an
injected repository root, so the defective branch was never reached.

**The repair.** Discovery now declares `policy_observation` alongside `policies`, so an
inventory says whether its policy set was observed at all; drift emits `missing-policy`
only for an inventory that observed one, and names the gap in `limits` rather than
dropping the comparison silently. An inventory from a policy-aware source still gets the
full comparison, including when it observed an empty set. Persistence refuses a path
inside the package's own directory with or without a checkout, and refuses outright when
no working tree can be determined, naming `--repository-root` as the way to say which
tree to protect.

**Generalizable rule.** A check that cannot be evaluated must refuse, not pass. When a
guard's input can be absent as well as empty, absence and emptiness need separate values,
because collapsing them makes the unexamined case indistinguishable from the examined
one. And a test that asserts a guarantee should be run once against the unfixed code: a
regression test that passes either way is the same defect in the test suite.

---

### A package can satisfy every structural check and still have no working entrypoint

**Author.** Jeff Cox and Claude

**Context.** Running the ten-client compatibility matrix against the assembled portable
UniFi package, after every preceding unit of the pilot had reported green.

**Evidence.** Every client that reached the invocation stage produced the same failure:
both `unifi_network_client.py` and `unifi_protect_client.py` abort during module import
with `ModuleNotFoundError` for `fleet_commons_shim`, before any argument is parsed. The
import is at `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:49`, and
no file of that name exists anywhere in the assembled package. The full record is in the
[ten-client compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md).

**Mechanism.** Synchronization deliberately drops both copies of `fleet_commons_shim.py`,
because build-time bundling is meant to replace them, and
[`plugins/unifi/fleet-bundle.json`](../../plugins/unifi/fleet-bundle.json) duly declares
the `retry_backoff` module the package needs. Nothing ever emitted it. The repository
validator did not catch this, because its two bundle checks both validate
correctness-when-present rather than presence: `check_bundled_files` walks the bundle
files that exist and verifies their stamps, and `check_fleet_bundle_declarations`
validates the declaration's shape against a closed schema. A declaration naming a module
that was never written is well formed, so every gate stayed green while the package had
no runnable entrypoint at all.

**Generalizable rule.** A declaration that names a required artifact must be checked for
that artifact's presence, not only for its correctness when present. An absent file
produces no violation to report, so absence has to be asserted deliberately or it is
never noticed. This is a second instance of the seam defect recorded below, found the
same way: at the first end-to-end run.

---

### Every unit passed its own tests and the defect lived in the seam between two correct units

**Author.** Jeff Cox and Claude

**Context.** A correctly deployed operator site profile produced `mode=discovery-only`
with zero subjects during the pilot, on a machine where the profile file was present at
the documented path.

**Evidence.** The pilot's Run C follow-up commit. The deployment unit wrote a valid
profile to the documented runtime path, and the loader unit read the resolution contract
exactly as that contract is written. Neither unit was wrong, and both unit test suites
were green.

**Mechanism.** The contract resolves the `UNIFI_SITE_PROFILE` environment variable first,
then the path remembered in `config.json`, then no profile at all. Deploying a file to
the documented default runtime path registers it with neither rung. One unit owned
writing the file and another owned reading the contract; no unit owned making the
deployed path reachable by the resolution order. The capability was split across units,
and the seam between them belonged to nobody, so the end-to-end path did not work while
every unit-level check passed. The portable half of this gap remains open and is recorded
in [queued work](QUEUED.md#the-documented-default-site-profile-runtime-path-is-never-read).

**Generalizable rule.** A plan that splits a capability across units must name which unit
owns the seam, and gate the release on an end-to-end check rather than on the union of
unit-level green. The union of green units is not evidence that the capability works.

---

### Two correct halves and no owner for the join ships a package that cannot run

**Author.** Jeff Cox and Claude

**Context.** The assembled portable UniFi package had no working entrypoint on any
client, while every validator in the repository reported success.

**Evidence.**
`python3 plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py --help`
exited 1 with `ModuleNotFoundError: No module named 'fleet_commons_shim'`, raised at
module scope before argparse ran; `unifi_protect_client.py` failed identically. The
ten-client compatibility matrix in
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../evidence/2026-08-22-unifi-compatibility-matrix.md)
recorded the same abort for every client that reached the execution stage. Fixed by
`scripts/sync_vendor_source.py` transform `resolve-bundled-fleet-module`, the
per-client destinations in `plugins/unifi/fleet-bundle.json`, and
`check_repo.check_fleet_bundle_outputs`.

**Mechanism.** Two pieces of tooling each did their own job correctly. The bundler
(`scripts/bundle_fleet_module.py`) generates a Fleet Core module into the consuming
package and rejects a tampered or stale copy. The synchronization
(`scripts/sync_vendor_source.py`) reproduces upstream bytes exactly and refuses a
downstream edit. Between them sat one fact neither owned: the clients import
`fleet_commons_shim`, and the package deliberately ships no such module. The
synchronization classified both clients as upstream byte copies, so copying the broken
import verbatim was not merely permitted but required by its own rule; the bundler was
never asked to write anything the clients actually resolve, so no bundle was generated
at all. Each validator was correct about its half. Nothing asserted that the assembled
result would start.

The blind spot had a precise shape. `check_repo.check_bundled_files` reads the bundles
that are on disk, so a bundle that was never generated is invisible to it -- absence of
evidence read as evidence of absence of a problem. No test executed a shipped
entrypoint, so the one signal that would have caught it in a second was missing.

**Generalizable rule.** When two tools each own one half of an artifact, the join is
not covered by testing both halves. Add one test that runs the assembled thing the way
a user runs it, and one validator assertion that the two halves name the same files.

### Neutralizing an environment variable does not neutralize a fallback that reads a file

**Author.** Jeff Cox and Claude

**Context.** Two tests in `tests/test_drift.py` began failing on a branch whose
production code had not changed, once a real operator site profile was deployed on the
developer's machine.

**Evidence.** `tests/test_drift.py::PersistenceAndCliTest` called
`drift.main(..., environ={})` intending a run with no site profile.
`test_cli_writes_a_report_outside_the_tree` expected mode `discovery-only` and got
`profile`; `test_cli_with_injected_inventory_writes_nothing_inside_the_tree` expected
zero findings and got nine, the first being an `unprofiled-host` finding against a real
host. The same suite was green earlier in the same pilot, before any profile existed on
the machine.

**Mechanism.** The site-profile contract in
`plugins/unifi/scripts/site_profile.py:262` resolves a profile from two rungs: the
`UNIFI_SITE_PROFILE` environment variable first, and the path remembered in
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/config.json` second. An empty `environ`
mapping suppresses only the first rung. The second is read from the real filesystem
through `Path.home()`, which no `environ` argument reaches. The tests were therefore
asserting a property of the developer's machine, not of the code. The fix pins
`XDG_CONFIG_HOME` into the test's temporary directory and passes the `--config-path`
seam the command line already offers, so both rungs land inside the temporary tree.
A companion test now deploys a profile through the configured rung on purpose and
asserts profile mode with the two findings it implies, which is the case the failing
tests had been exercising by accident.

**Generalizable rule.** When a lookup has more than one rung, isolating a test means
pinning every rung, not the first one; a rung that ends in a filesystem default is the
one that will silently read the developer's machine.

### A validator that only inspects what a manifest already declares cannot detect a deletion

**Author.** Jeff Cox and Claude

**Context.** Closing three of the seven findings that two independent reviewers reached
about commit `95de0d5` (pull request #3), recorded in
[the two-reviewer consensus](../reviews/2026-08-22-code-review-consensus.md) as C3, C4,
and C6. All three are validator gates in `scripts/check_repo.py` that report green in
the situation they exist to catch.

**Evidence.** Three repairs, and each one has a scenario that the pre-repair validator
let through. C3: `check_provenance_manifests` iterated `payload["files"]` and recomputed
the digest of each listed file, so adding `plugins/example/scripts/extra.py` to a package
returned no errors, and so did deleting a file's entry from the manifest while leaving
the file on disk, and so did listing one path twice with two different classifications.
C4: `_check_bundle_source_freshness` opened with `if not source_rel or not recorded:
return []`, so deleting the `source-path` and `source-sha256` lines from a generated
bundle's stamp removed the comparison with Fleet Core and returned no errors; the same
held for `generated-by`, `source-version`, and `source-commit`, none of which were read
at all. C6: no value-level credential check existed, so a package file containing
`"notes": "controller password=hunter2"` passed the whole gate. Ten of the eleven
scenarios came back with an empty error list against the validator at `95de0d5`.

**Mechanism.** Each of the three gates took its input from the artifact it was supposed
to be judging. The provenance check asked the manifest which files to verify, so a file
the manifest omitted was outside the question being asked. The bundle check asked the
stamp which comparisons to run, so a deleted stamp line deleted the comparison rather
than failing it. The secret check asked the schema which field *names* were forbidden, so
a credential written into a permitted field's *value* was never a candidate. In all three
the artifact under test controlled the scope of its own test, which means the defect and
the thing that would have reported it are removed by the same edit. The repairs close the
loop against a source the artifact does not control: the package tree on disk, a fixed
tuple of required stamp fields, and the byte content of the value itself.

**Generalizable rule.** A check that derives its own scope from the artifact it is
checking can only ever detect corruption, never omission. Enumerate the required set
independently — from the filesystem, from a constant, from the bytes — and compare, or
the guarantee disappears with whatever line an editor deletes.

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
