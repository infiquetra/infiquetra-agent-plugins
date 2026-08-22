# Archive - shipped, rejected, and superseded items

## 2026-08-22

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
