# Archive - shipped, rejected, and superseded items

## 2026-08-23

### SUPERSEDED - A completion watcher that can never fire looks exactly like work that never finished

**Resolution.** Superseded by [A verification step that reports success for an
unrelated reason is worth less than none](LEARNINGS.md), which generalises this
instance together with five others from the same pilot. The mechanism recorded
here is accurate and is cited by the successor as one of its six cases; what it
lacked was the observation that the same defect was simultaneously live in the
product, in the mutation harness, and in the repository gate. Archived rather
than deleted, per this journal's convention.

### A completion watcher that can never fire looks exactly like work that never finished

**Author.** Jeff Cox and Claude

**Context.** The cycle-7 review panel finished and wrote both artifacts. The coordinator's
background watcher never reported them, so the coordinator sat idle while two complete,
schema-valid reports sat on disk. The operator noticed and reconciled from the artifacts
directly.

**Evidence.** Background task `bo084hhi2` (PID 97405), the watcher loop in this session. Its
completion test was:

```bash
mo=$( [ -f "$OX" ] && grep -c APPEND_HERE "$OX" || echo 1 )
[ "$so" -gt 3000 ] && [ "$mo" -eq 0 ] && ...
```

**Mechanism.** `grep -c` prints the count *and* exits non-zero when the count is zero. Zero
matches is the success condition being waited for, so on exactly that condition the command
printed `0`, exited 1, and the `|| echo 1` branch fired too. `mo` became the two-line string
`"0\n1"`, and `[ "0\n1" -eq 0 ]` is never true. The watcher was structurally incapable of
reporting success: the closer the artifacts got to done, the more certainly it stayed silent.

Two things made this worse than a stuck loop. It failed *only* in the success case, so every
partial-progress poll behaved correctly and the bug was invisible until it mattered. And its
silence was indistinguishable from the condition it was built to detect — a reviewer stalled
mid-delivery with the marker still present — which is the failure this same session had already
hit three times, so the silence read as expected rather than anomalous.

**Generalizable rule.** Never let a predicate's success path depend on a command whose exit
status disagrees with its output. For `grep -c`, capture the count with `$(grep -c X f || true)`,
or test the file directly with `! grep -q X f`. More generally: a watcher must be able to fail
*loudly*, so give it a bounded timeout that prints the observed state rather than one that
prints nothing, and prefer checking the artifact and the reviewer's real foreground process over
a derived boolean. When a watcher goes quiet on work that should be finishing, read the artifact
before believing the watcher.

### SUPERSEDED - A negative test that passed for the wrong reason reported coverage that did not exist

**Resolution.** Superseded by the same successor entry, which cites this as its
first case. The remedy recorded here — break the code on purpose and require the
new assertions to fail — became the general habit rather than a credential-rule
habit, and the successor states it for every kind of check rather than for
must-not-fire tests alone. Archived rather than deleted, per this journal's
convention.

### A negative test that passed for the wrong reason reported coverage that did not exist

**Author.** Jeff Cox and Claude

**Context.** The credential-value rule was repaired once for grading the wrong span, and the
repair broke in both directions: it cleared a real credential hidden behind a placeholder, and
it rejected ordinary operational prose. Two independent reviewers found both on the next
cycle. The repair had shipped with a must-not-fire test written specifically to catch the
second class.

**Evidence.** The cycle-4 negative set used `auth: see the runbook for the rotation
procedure`. It passed. The cycle-5 reviewers used `token: rotation happens quarterly`, which
failed. Both are the same shape — a credential-shaped key assigned English prose — and the
difference is only that the first sentence begins with `see`, three characters, which falls
under the rule's six-character length floor before any grading happens.

**Mechanism.** The test exercised the length floor, not the rule it was written for. Its
subject never reached the code under test, so it could not have failed no matter how wrong
that code was. It looked like coverage of the false-positive category and was coverage of
nothing.

**Fix.** The replacement set is chosen so each case would fail for the *right* reason if the
rule were wrong: first tokens that are long English words (`rotation`, `managed`,
`internationalization`), capitalized forms, and a ticket number that carries a digit. Twenty
eight assertions fail against the defective rule.

**What surprised.** Reviewing my own test set would not have caught this. Reading it, the
example plainly belongs to the category; only running it against deliberately broken code
shows that it never touches the rule. Mutation is the only cheap check that distinguishes a
test from a test-shaped statement.

**Generalizable rule.** For any test that exists to prove a guard does *not* fire, verify it
would fire if the guard were wrong. A negative case that is filtered out by a precondition
before reaching the logic is worse than no test, because it is counted as coverage. Cheapest
implementation: break the code on purpose and require the new assertions to fail. Every repair
in this pilot now ships with that count recorded, which is how this one was caught.

**Refs.** the upstream repository `infiquetra-claude-plugins`,
cycle-5 reviews in [`docs/reviews/`](../reviews/).

## 2026-08-22

### SHIPPED - Emit the declared Fleet Core bundle so the package has a working entrypoint

**Resolution.** Shipped in `4c1d30f`, before the cycle-1 review baseline. Both
`plugins/unifi/skills/*/scripts/_bundled/retry_backoff.py` copies are emitted,
`scripts/check_repo.py` rejects a declared-but-missing bundle, and
`tests/test_client_entrypoints.py` runs the shipped scripts as an operator does (5 tests,
green). The entry's own text still read "No repair has begun" through four review cycles;
an operator reading the queue would have believed the package unusable and re-authorized
finished work. Archived rather than deleted, per this journal's convention.

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

### SHIPPED - Drop README.md from the UniFi byte-copy table so a resync keeps the portable docs

**Resolution.** Shipped. `scripts/sync_vendor_source.py:105` carries
`SUPERSEDED_BY_TARGET_OWNED = ("README.md",)`, `plugins/unifi/PROVENANCE.json` classifies
`README.md` as `target-owned`, and `tests/test_sync_vendor_source.py` asserts a target-owned
file survives a re-run. Stale for the same reason as the entry above, and found by the same
reviewer in the same pass.

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

## 2026-08-22

### Re-run the ten-client matrix and the readback against the resynced package

**Status.** Shipped on 2026-08-22, and then shipped a second time the same day.

**Outcome.** Done twice, for two different re-synchronizations, by the same method both
times. The first re-run cleared the Fleet Core 0.25.1 resync: the package tree digest had
moved from `6e6b57c1…` to `da46ca77…`, and forty stage results were executed again rather
than the digest edited. The second re-run cleared the UniFi 2.0.1 resync, which replaced
both client entrypoints and moved the tree digest to `cafe8836…` and the manifest version
to `2.0.1`; forty stage results were executed again against that tree, and the readback
was re-captured from three fresh installs.

No verdict changed in either re-run: eight clients work directly, OpenAI Codex works
through an adapter, Cursor Agent failed, 34 executed and 6 blocked stage results both
times. What changed was digests, one manifest version, and — in the second re-run — the
interpreter, which is now the catalog's declared floor rather than whatever was default.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[post-activation readback](../evidence/2026-08-22-unifi-post-activation-readback.md),
[the matrix superseded before the 2.0.1 re-run](../evidence/2026-08-22-unifi-compatibility-matrix-pre-unifi-201.md)

### Decide the Python floor the Fleet Core resync raised

**Status.** Resolved by operator decision on 2026-08-22.

**Outcome.** Neither of the two options this item framed was taken. The item asked whether
to repair the import upstream and keep a 3.10 floor, or to move the floor to 3.11 — the
minimum that one import happened to require. The operator rejected both premises and set
the catalog's minimum supported Python to `python>=3.12`, the floor the authoritative
source repository already declares and tests, on the grounds that a derived catalog must
not promise more compatibility than the source it is derived from. A floor read off the
current bytes gets re-derived by every byte copy; a floor inherited from the source is
stable across them. The declared floor now lives in one place with a gate over every site
that states it, and the ported-plugin continuous-integration job pins `3.12` so the floor
is actually exercised. Recorded as
[the floor decision](DECISIONS.md#the-portable-catalogs-minimum-supported-python-is-python312).

**Not closed by this.** The `compatibility` frontmatter declaration KTD7 claimed, which
cannot be authored downstream and is
[queued as upstream work](QUEUED.md#declare-the-catalogs-python-floor-in-the-unifi-skills-frontmatter-upstream).

**Original text.** Preserved as written:

> ### Decide the Python floor the Fleet Core resync raised
>
> **Author.** Jeff Cox and Claude
>
> **Priority.** P1
>
> **Effort.** One operator decision, then either an upstream repair released and
> re-synchronized, or a floor change across the catalog's documentation and the ported-plugin
> continuous-integration job.
>
> **Worth it when.** Before the portable catalog is offered to anyone running Python 3.10,
> and before the ported-plugin job is trusted as a floor check.
>
> **Context.** Fleet Core 0.25.1 added `from datetime import UTC` at
> [`plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:28`](../../plugins/fleet-core/scripts/fleet_commons/retry_backoff.py).
> `datetime.UTC` exists only in Python 3.11 and newer; under 3.10 that line raises
> `ImportError`, verified against a 3.10.20 interpreter. The catalog documents a 3.10 floor
> and [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) pins Python 3.10 for the
> ported-plugin job precisely so the floor is exercised. The byte-copy rule forbids repairing
> this downstream, because an edit here would make the path diverge from its source and give
> `retry_backoff` a second writable source.
>
> **The two options.** Author the repair upstream — `timezone.utc` is available on every
> supported version and the change is one line — release it, and re-synchronize. Or move the
> declared floor to 3.11, which means the changelog note, the ported-plugin job's pinned
> interpreter, and any other place the catalog states 3.10, all moving together.
>
> **Refs.** [learning](LEARNINGS.md#a-byte-copy-imports-the-upstream-platform-floor-along-with-the-upstream-fix),
> [the 0.25.1 changelog entry](../../plugins/fleet-core/CHANGELOG.md)


### Choose the first portability pilot and custody gate

**Status.** Shipped. The pilot was chosen, planned, executed, and stopped at its operator
pause on 2026-08-22.

**Outcome.** The pilot is `unifi` plus a one-module portable Fleet Core slice, and both
packages now exist in this repository as derived artifacts pinned by provenance to a
corrected upstream revision. The ten-client compatibility matrix is complete: ten clients,
forty stage results, ten overall statuses, eight of them works directly. The custody gate
resolved by not moving: existing vendor repositories remain authoritative, the portable
copy is derived and digest-verified rather than a second writable source, and no custody
transfer was made. Two things the pilot found are recorded rather than repaired — the
assembled package has no working entrypoint, and two clients did not consume it — because
the pilot ends in an operator decision per client rather than in remediation.

**Original text.** Preserved as written:

> **Author.** Jeff Cox and Codex
>
> **Priority.** P1
>
> **Effort.** One focused design session followed by a separately approved pilot.
>
> **Worth it when.** Before any existing vendor plugin is migrated or generated
> from this repository.
>
> **Status update, 2026-08-21.** The design session is complete and its output is the
> UniFi and portable Fleet Core portability pilot plan. The pilot is `unifi`
> plus a one-module portable Fleet Core slice; the client matrix is all ten installed
> clients as mandatory coverage rather than a pass gate; and the source-custody rule is
> that the Claude repository stays authoritative, is repaired and released first, and is
> then synchronized from by a digest-verified derivation. This item stays queued until the
> pilot itself is executed and its compatibility matrix reaches the operator pause.
>
> **Still open.** The Herdr execution boundary is untouched by this pilot, and the
> custody-transfer question remains deliberately unanswered until the pilot produces
> evidence.
>
> **Original context.** The architecture research recommends `home-lab-ops`,
> `mission-control`, or `unifi` as the first pilot. The work still needs a chosen
> pilot, required client matrix, Herdr boundary, source-custody rule, and semantic
> parity evidence.

**What stayed open.** The two questions the entry named as still open are still open, and
neither was answered by the pilot. The Herdr execution boundary was untouched, and the
custody-transfer question remains deliberately unanswered. Closing this item records that
the pilot ran, not that everything it deferred was settled.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[operator pause decision](DECISIONS.md#pause-the-pilot-at-the-compatibility-matrix-and-take-no-client-specific-remediation),
[pilot decision](DECISIONS.md#choose-unifi-plus-a-portable-fleet-core-slice-as-the-first-portability-pilot),
[architecture brief](../cross-vendor-plugin-architecture-brief.md)

---

## 2026-08-21

### Void parity baseline recorded in error

**Status.** Void. Never a valid decision at any point.

**Original text.** "Parity with code; correct the ported docs downstream." Under this
reading the portable skill and reference documents would have been corrected in this
repository only, the Claude source would have kept its stale documentation, and the
provenance manifest would have carried a per-file `intentional-deviation` status to
legitimize the difference.

**Why it was invalid.** It was not the operator's selection. The controlling client
mis-entered the choice: the operator selected "fix the authoritative source first, then
port," and the downstream-correction option was recorded instead. Nothing downstream of
the mis-entered option was ever approved. Downstream-only documentation correction and
intentional target divergence are both explicitly unapproved.

**Replacement.** The authoritative source is repaired, verified, and released before the
port synchronizes from it. See
[the pilot decision](DECISIONS.md#choose-unifi-plus-a-portable-fleet-core-slice-as-the-first-portability-pilot)
and the [pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md).

**Preserved because.** The repository's supersession convention requires the original
text to survive rather than be erased, and an audit trail that hides a mis-entry teaches
nothing about how the mis-entry happened.

---


When an item reaches a terminal state, preserve the original entry, its outcome,
the date, and the validating commit, pull request, issue, or evidence link.
