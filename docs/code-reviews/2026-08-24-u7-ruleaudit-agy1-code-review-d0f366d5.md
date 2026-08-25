# Saga Code Review — U7 validation-rule audit (`u7-ruleaudit-agy1`)

This review covers the frozen Phase 2 commit on `orch/mcport-9-resume1-u7-ruleaudit-agy1` because the ported package carries five validation rules, and a copied constant that cannot fail when the authority moves is the failure class this unit exists to close.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `d0f366d5fecbe704e3f352ce43a96cc1084193da` (`d0f366d`, `test(rules): audit the mission-control validation rules class-first (run unit U7)`)
- Named base: `40367a8a8ba17383a71907e874f58a85464ad163`
- Target: 3 files, +889
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `d0f366d` is accepted.** The 37 tests are the load-bearing audit. The two defective probe transcripts in the committed note do **not** require a repair cycle: this controller reproduced the real guards first-hand, and the tests already encode capable-of-failing corpora.

## Scope and built-versus-planned audit

**Scope Check: CLEAN** (the `docs/plans/` note is authorized by the dispatched task; see item 1)

- Intent (child #17 / plan U7 / Key Technical Decision 5): class-first audit of the Phase 0 inventory — card validator with live home-lab authority and verdict agreement; issue-contract parity offline plus loud `--live` skip; pagination lint on the portable tree plus rejection corpus; prompt-alignment drop honored with portable taxonomy invariants; template-sync against infiquetra-sdlc with loud skip. Every added check capable of failing. Zero byte-copy edits.
- Delivered: `tests/test_mission_control_rule_audit.py` (37 tests), the audit note, one LEARNINGS entry for dataclass `sys.modules` registration.

### Plan-completion (U7)

| Item | State | Evidence |
| --- | --- | --- |
| Card validator: authority loaded at test time; loud skip if absent | DONE | `_find_home_lab_card_validator` / `_load_home_lab_authority`; `skipTest` in `setUp` |
| Card validator: class corpus + verdict agreement | DONE | 23 methods covering valid / missing-header / placeholder / semantic / risk-tier; 37/37 suite green with home-lab present |
| Issue-contract parity: offline sha256 + `--live` loud skip | DONE | `parity_errors()` empty; injected drift caught; `LiveParityUnavailableError` on missing schema |
| Pagination lint: clean tree + rejection corpus | DONE | `run_lint()` empty; unguarded item-list / bare `_rest_get` / GraphQL `first:` rejected |
| Prompt-alignment: dropped-from-source + portable taxonomy | DONE | descriptor and provenance asserts; `assertNotIn("hermes-task")` |
| Template-sync: exact match + loud skip + drift fail | DONE | `check_reference()` true; skip if templates absent; injected drift fails |
| Capable-of-failing recorded | DONE in tests; PARTIAL in note probes | tests inject drift / missing headers / unguarded calls; note Probe 3/4 defective (items 2–3) |
| Zero byte-copy edits; sync `--check` | DONE | exit 0 at pin `84eaf042` |

COMPLETION: 7/8 DONE, 1 PARTIAL (note probe transcripts only).

## Judgments

### (1) Audit note under `docs/plans/` — in scope

Child #17's file list names `tests/` and the journal. The committed note is `docs/plans/2026-08-24-mission-control-port-u7-phase2-rule-audit.md`. The dispatched task authorized a committed per-rule record under `docs/`. No other unit owns `docs/plans/`. The card also requires the audit "recorded in the unit PR." **Not overreach.**

### (2) and (3) Defective probe transcripts — endorse; do not repair

This controller verified both defects, then verified the substance:

- **Probe 3 as committed** is `SyntaxError` (`import tempfile, Path from pathlib`). It cannot have produced the recorded output. **Corrected first-hand:** `check_pagination.check_file` on a temp file containing `gh project item-list 4 --owner infiquetra` returned **exactly 1** violation: `unguarded \`gh project item-list\` (no cursor loop, no --limit)`. The suite test `test_rejects_unguarded_raw_item_list` is the durable capable-of-failing check.
- **Probe 4 as committed** asserts `'hermes-task' in '`capability`, `needs-plan`, `hermes-task`'` — a tautology. **Real guard first-hand:** appending `hermes-task` to `skills/issues/references/issue-types.md` made `test_portable_prompts_and_references_carry_current_taxonomy` FAIL (returncode 1). The file was restored; `git status` clean.

The card's "shown capable of failing" requirement is satisfied by the **37 committed tests**, which inject violating fixtures and restore them. The note's Probe 1/2/5 transcripts are runnable; 3 and 4 are a bad retelling of evidence that already lives in the test file.

A repair cycle would rewrite two code fences in a plans-directory note. That is closeout annotation, not a Phase 2 miss. Cycle-13's rule against leaving a published proof *claiming more than the tests established* does not apply to block: the tests establish the guards; the note overclaims two *probe commands*, not the rules.

**Endorse as-is. No repair cycle.** Residuals below.

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 10.00 | `true` | none |
| `documentation-clarity` | 9.00 | `true` | none |
| `adversarial` | 10.00 | `true` | none |

Documentation is 9.00 because Probe 3 cannot run as written and Probe 4 does not exercise the guard; the table also says "37 corpus classes" for the card validator, which is the file's test count, not that rule's method count (23).

## What was verified

Worktree at `d0f366d`:

- Five graded-file sha256 values equal the cycle-15 footer
- `python3 scripts/check_repo.py` — passed
- `python3 -m unittest tests.test_mission_control_rule_audit` — 37/37
- `python3 -m unittest discover -s tests` — 736 ran, 0 failed, 1 skipped
- `python3 -m pytest plugins/mission-control/tests -q` — 266 passed
- `sync_vendor_source.py --package mission-control --commit 84eaf042 --check` — exit 0
- `git diff --check` clean; UniFi porcelain empty
- Probe 3 committed snippet: `SyntaxError`; corrected snippet: 1 violation
- Probe 4 tautology runs; appending `hermes-task` fails the taxonomy test; restore clean

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - Audit note Probe 3/4 transcripts are inaccurate; capable-of-failing evidence is the test file. Closeout may annotate the note.
  - `test_authority_derived_data_structures` compares authority `REQUIRED_FIELDS` to a hardcoded tuple, not to the portable shim — a copied constant on that one assertion.
  - `test_live_leg_unavailable_raises_and_skips_loudly` uses a missing schema path, not a missing GitHub token. The loud-skip type is still raised.
- Independent gates actually run at `d0f366d`: `check_repo`, discover, package pytest, sync `--check`, graded-file match, `git diff --check`. `evaluate_review_readiness` `can_proceed` is true.

## Findings

None.

## Routing

`accepted` — continue. No fix requests. Items 1–3 are endorsed; Probe 3/4 stay as documentation residuals, not repairs.
