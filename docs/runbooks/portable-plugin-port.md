# Runbook: porting a Claude plugin into the portable catalog

**Version 1.0.0** · Adopted 2026-08-23 · Derived from the UniFi pilot

Record the version you followed in the port's plan and its saga tick. Change the
minor version when a step is added or reordered; the major when the phase
structure changes.

This runbook is the checklist. It carries no narrative and no rationale — those
live in [the pilot retrospective](../engineering-journal/narratives/2026-08-23-unifi-portability-pilot-retrospective.md)
and in [`DECISIONS.md`](../engineering-journal/DECISIONS.md).

---

## Entry criteria

Do not begin porting until every line is true.

- [ ] Upstream plugin sits at a pinned commit; its own suite is green there.
- [ ] The package's port descriptor exists at `ports/<package>.json` (see [Reusable assets](#reusable-assets)) and `scripts/check_repo.py` passes on the empty port.
- [ ] Every validation rule the plugin carries is inventoried, each with a named **predicate** and a named **authority** (a standard-library function, a specification, a schema — not a description).
- [ ] The client roster and assessment method are scripted in `scripts/assess_clients.py`, not to be re-derived. Print the plan with `python3 scripts/assess_clients.py --package <package>` before running it.
- [ ] The Python floor is decided and a matching interpreter exists.
- [ ] Non-goals are written down.

---

## Phase 0 — Prepare (serial, ~1h)

- [ ] Write `ports/<package>.json`: package identity, package root, upstream source, custody table, and the `assessment` block naming the package's own scripts, its mutating operations, its credential variable prefixes, its **entrypoints**, and its skill units. Every object is closed against unknown keys, and every safety field must be stated — a package for which one is genuinely empty names it in `assessment.declared_none`.
- [ ] Classify **every** path as `upstream-byte-copy`, `deterministic-transform`, or `target-owned` in that descriptor's `custody` table, which is what `PROVENANCE.json` is then generated from.
- [ ] Confirm the floor interpreter by explicit path, never as `python3`.

## Phase 1 — Port (parallel, concurrency cap 3)

Three lanes that share no files. Cap is 3 because the fleet runs above Haiku.

- [ ] **Lane A** — byte copies and the provenance manifest, via `python3 scripts/sync_vendor_source.py --package <package> --source PATH --commit SHA`.
- [ ] **Lane B** — target-owned surface: README, entrypoints, package manifest.
- [ ] **Lane C** — bundling and deferred inventory, if the plugin has dependencies.

Sequence, never parallelize, any two units that touch one file.

## Phase 2 — Rule audit (serial) — *do not skip*

For each validation rule, in this order:

- [ ] State the **predicate**: the decision the rule must make.
- [ ] Name the **authority** for it, and **derive it at test time** rather than restating it. A test that rebuilds the rule's premise from its authority fails when the premise moves; a copied constant does not.
- [ ] Write the **class corpus** — every member of the input class, in every vulnerable shape — *before* the rule ships.
- [ ] Where a rule exists in more than one copy, assert agreement on **verdicts**, not on constants, patterns, or helper outputs.

## Phase 3 — Freeze and gather evidence (serial)

- [ ] Repository gate and full suite green.
- [ ] Floor verified from **staged bytes**, not the source tree; every entrypoint runs credential-free.
- [ ] Freeze the candidate: exact commit recorded, working tree clean.
- [ ] **One** client matrix run and **one** readback, bound to the shipped fingerprint.
- [ ] Mutation proof per rule copy, bound by test to the committed blobs.

## Phase 4 — Review (2 reviewers in parallel, **maximum 3 rounds**)

- [ ] Both reviewers independent, models confirmed by live readback before briefing.
- [ ] Brief on the **class**: require reviewers to enumerate a rule's input space and probe it, and to state the rule's authority. Do not brief only on what was just repaired.
- [ ] Reviewers verify the commit id and a clean tree before scoring.
- [ ] Reports delivered incrementally behind a completion marker; verify the artifact and the real process, never a status badge.
- [ ] Each round batches **all** confirmed findings into one repair and one release. See [the decision](../engineering-journal/DECISIONS.md) on round bounds.

---

## Stop conditions

Stop and report rather than continuing when any of these hold.

| Condition | Action |
|---|---|
| A confirmed fail-open in a security rule | Stop immediately. Do not batch it with anything. |
| Reviewers split on **fact** | Decide empirically; the reproduction is the arbiter, not the reviewer's rank. |
| Reviewers split on **severity** | Operator decides. |
| Three rounds exhausted | Stop with residuals listed and evidence preserved. |
| Any verification harness found unsound | Discard that round's evidence and re-run. A harness that cannot fail proves nothing. |

## Completion evidence

All required, on the exact frozen commit.

- [ ] Typed `review_result.v1` **accepted** from both reviewers.
- [ ] Repository gate, full suite, and upstream suite green.
- [ ] Floor verified from staged bytes.
- [ ] One fingerprint-bound matrix and readback.
- [ ] Mutation proof per rule copy, bound by test to committed blobs.
- [ ] Provenance digests equal across every copy of a byte-copied path.

---

## Reusable assets

Do not rebuild these.

| Asset | State | Action for a new package |
|---|---|---|
| `scripts/check_repo.py` | Package-agnostic | Use as-is |
| `scripts/bundle_fleet_module.py` | Package-agnostic | Use as-is |
| `scripts/check_compatibility_matrix.py` | Package-agnostic | Use as-is; it resolves the package from the record's own `$.package.name` |
| `scripts/sync_vendor_source.py` | Package-agnostic | Use as-is; pass `--package <package>` |
| `ports/<package>.json` | Per package | Write one. It is the only place package identity, custody, and assessment settings live |
| `scripts/assess_clients.py` | Package-agnostic | Use as-is; it carries the ten-client roster and every quirk below |
| `PROVENANCE.json` three-way custody schema | Generic | Reuse the schema |
| `MutationProofBindingTest` pattern | Generic | Reuse; it fails when a graded file changes without its proof |
| The credential value rule and its corpus | Stable at unifi 2.0.6 | Reuse for any profile-like contract rather than re-deriving |
| Review brief template | Evolved through nine cycles | Start from the cycle-9 brief |
| Python 3.12.13 virtualenv | Built | Reuse |

## Client assessment

Ten clients, four stages each: placement, discovery, load, invocation. Every quirk
below was learned the expensive way, and every one of them is now carried by
[`scripts/assess_clients.py`](../../scripts/assess_clients.py) rather than by
whoever is running the assessment.

```bash
python3 scripts/assess_clients.py --package <package>              # print the plan; runs nothing
python3 scripts/assess_clients.py --package <package> --execute \
    --python <venv>/bin/python3.12 --out <record>.json
```

`--python` must name an interpreter that already has the package's own
third-party imports — the pilot used a throwaway virtual environment holding
only `requests` and `urllib3`. The entrypoints import them at module scope, so a
bare floor interpreter records a non-zero status for every client and proposes
`failed` for all ten.

Each client is handed its **own** fresh copy of the package, fingerprinted before
and after that client runs. A client that changes the copy it was given has its
row recorded without a classification: the stages describe bytes that no longer
exist. The run also writes a private `transcript.json` beside those copies,
holding each command's bounded raw output. That transcript is what the record's
`evidence`, `reason`, and `version` fields are written from — it is operator-only,
never committed, and never quoted into the public record.

The table below is the reference for reading that plan; the harness is what
executes it.

| Client | Quirk |
|---|---|
| Cursor | Must run against the **real authenticated** `HOME`. An isolated home strips authentication and produces a false failure. |
| Grok | Needs `GROK_AUTO_TRUST_REAL_BIN` under an isolated home. `plugin details` takes the plugin **name**, not the install id. |
| Agy | Needs `AGY_AUTO_TRUST_REAL_BIN` under an isolated home. |
| Qwen | Installer prompts for confirmation on stdin; with no answer it lists and exits without installing. Adds one metadata file to the extension directory. |
| Gemini | `skills link` prompts on stdin and hangs rather than declining when stdin is closed. |
| Muse | `--force` is required on the JSON install to report a digest once placement has installed the unit. |
| Hermes | Run in an isolated home only. Confirm the live skills directory is unchanged before and after. |
| Grok, Agy | The auto-trust override must name the **real** binary. Resolving it with `which` returns the wrapper, which then launches itself recursively until the host gives out; the harness refuses that rather than spawning it. |
| Codex | Refuses the package root with an actionable message; load and invocation stay blocked. |

Name the package's credential variable prefixes in the descriptor's
`assessment.credential_prefixes`; the harness removes every matching variable
from every stage's environment. A client that needs credentials before it will
report state gets a **blocked** stage with the requirement named, never a
satisfied one.

## Anti-patterns

- Repairing a byte copy or a transform in place. Repairs go upstream and come back through a resync.
- Weakening the fingerprint binding to avoid re-running evidence. Batch the repairs instead.
- Deriving a fix from the failing example rather than from the rule's predicate.
- Adding a guard scoped to the instance just repaired.
- Editing evidence to match a moved tree. Re-run it, and preserve the superseded record with its reason.
