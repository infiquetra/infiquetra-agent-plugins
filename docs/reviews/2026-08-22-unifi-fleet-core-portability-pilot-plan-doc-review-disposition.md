# Disposition — document review of the UniFi and portable Fleet Core pilot plan

This records the independent validation and repair of every finding in the
[incoming review](2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review.md). The review
artifact is preserved unmodified as incoming evidence; nothing in it was rewritten, softened, or
deleted.

## Provenance of the incoming review

| field | value |
|---|---|
| artifact | `docs/reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review.md` |
| SHA-256 as delivered | `3d50ae5ae128d3f15fcf4750c43a747d3c8dee123369997a4584e62eb24f01e5` |
| length | 228 lines |
| verdict | NOT READY / BLOCKED — ten priority-1 findings, two priority-2 findings |
| reviewed revision | pull request #2 head `43b4cc833381cd6da3593de7808cc2ab7dcb43bc` |

## Validation method

Each finding was checked against primary evidence rather than accepted on the reviewer's authority:
the exact plan text at the reviewed revision, the authoritative source repository at commit
`995a475`, the installed Orchestrate contract, the published Agent Plugins 1.0.0 specification, and
this repository's own standing rules. Repository validation being green was not treated as evidence
against any finding, because the findings concern decisions and gates rather than document syntax.

## Outcome

**Twelve findings raised, twelve confirmed, none refuted and none narrowed.** No repair required a
new operator decision; each was either a correction of the document to match an already-settled
ruling, or an application of a standing repository rule.

| finding | verdict | independently verified against | repair |
|---|---|---|---|
| D1 | CONFIRMED | Plan carries `backend: inline` in frontmatter while Open Questions declared the backend unchosen. Orchestrate's own contract states "orchestrate is always inline, and the plan carries `backend: inline` so every `/work` unit is told rather than asked." | Stale open question removed; an Execution ownership section names Orchestrate-through-Herdr as outer controller and `inline` as the per-dispatched-unit backend; KTD8 records the two-layer model. |
| D2 | CONFIRMED | Orchestrate's README describes one run record over one repository's branches and worktrees. The plan spanned three repositories with no handoff topology. | A run-topology table defines Run A, B, and C, one per repository, joined by three named receipts; KTD9 records the rule; stop conditions gained a missing-receipt stop. |
| D3 | CONFIRMED | R4 forbade intentional divergence while U10 reduced skill frontmatter downstream, and U4 and U5 authored target-owned files under `plugins/unifi/` with no classification. | R4 rewritten to classify every path as byte copy, versioned transform, or target-owned source; frontmatter repair moved upstream into U6 so skill files stay byte copies; U10 made classification-aware and forbidden from overwriting target-owned paths. |
| D4 | CONFIRMED | R16 promised versioning, provenance, and releases; U2's file list carried none, and this repository's standing rule keeps vendor repositories authoritative absent a recorded custody decision. | R32 and R33 added; KTD10 records that custody does not move and the slice derives under the same rule as UniFi; U2 gained a provenance manifest, a changelog, and a named release surface. |
| D5 | CONFIRMED | U3 named a declared module list but no declaration file, and Agent Plugins 1.0 has a closed manifest schema that forbids assigning semantics to unknown top-level fields. The digest was self-referential. | R34 and R35 added; a separate `fleet-bundle.json` with a closed schema; KTD11 defines two digest domains, with the generated-output digest excluding its own stamp block; generate and check modes separated. |
| D6 | CONFIRMED | U8 named a YAML profile while the dependency-bearing job installed no parser; no component owned the three-path setup; U7 required the upstream agent to consume a loader that existed only in this repository. | R36 through R39 added; KTD12 pins JSON parsed by the standard library; U4 gained a named setup entrypoint and explicit configuration and runtime paths; U7 gained a Claude-side loader; U5 must emit unknown for every intent field. |
| D7 | CONFIRMED | U9 named only "release artifacts" and the changelog, while the upstream repository enforces a tri-lock requiring plugin manifest, marketplace entry, and changelog versions to be equal, plus a generator check. Rollback was undefined. | R40 through R42 added; U9 names all three release surfaces, a staged pre-activation load, a post-activation installed-version and digest readback, and a fresh-session proof of all three profile states; the Rollback section gained a trigger, a version strategy, and a re-proof requirement. |
| D8 | CONFIRMED | U11's tests asserted row count and permitted statuses only, and its file list owned no validator, so a row could be counted as covered after one early failure. | R43 added; every client now carries four stage results — placement, discovery, load, invocation — each executed, blocked, or not applicable with command and evidence, then exactly one overall status; a schema and validator were added; unsupported and failed remain accepted outcomes. |
| D9 | CONFIRMED | U9 wrote fact-by-fact equivalence evidence into this public repository with no schema, allowlist, or check enforcing the stated exclusion. | R44 added; a public evidence schema records field names, counts, per-field results, digests, and redacted commands, and forbids raw topology or controller responses; the private receipt stays outside this repository and is linked by digest. |
| D10 | CONFIRMED | The upstream `fleet_commons` package holds 18 files — 15 Python modules and 3 data files — plus `fleet_commons_shim.py` beside it. No counting basis yields sixteen remaining after porting one module. | The handwritten count was removed everywhere; the deferred inventory is generated from the pinned source tree by set difference, with its counting basis stated in the file, so an upstream addition fails the check until regenerated. |
| D11 | CONFIRMED | The plan said four repositories while its ownership table named three distinct ones and repeated the target repository in a fourth row; the pull request body repeated the count. | Corrected to three in the plan and in the pull request body; the repeated row is labelled as the same repository. |
| D12 | CONFIRMED | U6's file list contained no test path although its scenarios required new assertions, and its stated checks omitted the README, slash command, agent definition, and changelog that R5 also covers. | R45 added; U6 owns a named upstream test file; assertions now cover all eight surfaces named by R5 through R7, with a surface-to-assertion map so none is left to an unrecorded review gate. |

## Refutations and narrowings

None. Every finding survived independent validation on primary evidence.

The reviewer's two priority-2 findings were factual arithmetic and count errors in the plan, and both
were reproduced exactly. The reviewer's own alternative count for D10 was also checked and is
correct.

## Operator rulings preserved through the repair

Each was re-checked against the repaired document rather than assumed to have survived.

Orchestrate through Herdr is the outer controller, and `backend: inline` is the per-dispatched-unit
Saga backend. Fleet Core is a first-class portable source, but only `retry_backoff` is ported now and
every other item is inventoried as deferred. All ten clients must be assessed and none must pass. No
client-specific remediation begins before the operator pause. The authoritative Claude source is
repaired and released before the port synchronizes from it, and extract means relocate rather than
delete.

## What changed in the plan

Requirements grew from 29 to 45; no existing requirement identifier was renumbered. Decisions grew
from 8 to 15, retaining the void decision preserved for audit. Implementation units remain U1 through
U12 with no renumbering, as the identifier stability rule requires. Four design sections were added:
execution ownership, run topology, path classification, and the public evidence schema.

## Checks

| check | result |
|---|---|
| `python3 scripts/check_repo.py` | passed |
| `python3 -m unittest discover -s tests -v` | passed, 4 tests |
| `git diff --check` | passed |

These confirm document syntax, required paths, and local link integrity. As the incoming review
correctly noted, they cannot resolve decision-level findings; the validation above did that.

No implementation, installation, publication, release, credential access, UniFi controller call, or
change to any other repository was performed.
