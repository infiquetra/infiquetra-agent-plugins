# Archive - shipped, rejected, and superseded items

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
