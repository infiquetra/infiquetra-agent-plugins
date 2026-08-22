# Archive - shipped, rejected, and superseded items

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
