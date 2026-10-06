---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: switch /code-review to the review command, with the new round and merge rules

### Objective

`/code-review` runs the review command (C10a), and the old review is deleted in the same change with
no switch back. Rounds and merges follow the new rules, an unattended run merges only as its intent
envelope allows, and admission stops asking for lenses and round allowances.

### Intent

Today on origin/main (1f7137d), paths under `plugins/saga/`:

- `/code-review` resolves a lens roster (`skills/code-review/SKILL.md:142-185`), runs one large
  language model (LLM) session per lens a cycle (`:187-247`), and states the data-loss block only in
  prose (`:381-392`). Cycles are 3 plus 2 escalated (`scripts/review_consensus.py:115-116`); the
  post-merge repair loop has its own 3 plus 2 and one extension (`scripts/release_step.py:309-445`).
- Admission asks for lenses and allowances (`scripts/admission.py:130-139`); the run configuration
  lists lens and escalation parameters (`scripts/run_record.py:102-116`); `/work`'s stale path skips
  the combined-branch run (`skills/work/SKILL.md:943-953`, #144).
- Old-shape readers: `scripts/run_status.py:56-57`, `scripts/cost_report.py:61-65`,
  `scripts/release_step.py:517-616`, `scripts/status_card.py:452`, and orchestrate's fallback to
  `review_result.v2`, which C9 keeps until this switch. Merge is explicitly confirmed
  (`skills/work/SKILL.md:1078-1080`), and no saga script reads the envelope's merge setting.

What changes (plan.md, Change 8, and "Block, fix later and note"):

- `/code-review` runs C10a's `prepare`, has orchestrate start the reviewer (C9), runs `finish`, and
  shows and publishes through C13's review-state document and pull request comment.
- Deleted, no switch: the lens roster, consensus scoring, the verifier, both result shapes, TypeSafe
  Jev's duplicate, severity and lens-proposal checks, every old-shape reader and their tests, and the
  lens-reviewer role and its staffing row. The review-controller role describes the new flow.
- Rounds: every lens at C or better goes to merge; a repair round leaving the same blocking items (by
  C1's finding identity) stops early; round 3 stops. Later rounds re-check only repaired code; fix-now
  rounds do not count; each round records new and cleared items, cost and time. The post-merge repair
  loop follows the same rule, with no escalation and no extension.
- At an early stop or the limit, the operator merges with a recorded reason, filing the blocking items
  as linked defect issues through mission-control, or stops the card. Unattended runs wait for this too.
- Merge blocks on reproduced data loss or security exposure in any lens, report-only ones included,
  and on unresolved review threads (the release step). Fix-later choices never hold a merge.
- Unattended means the run mode the intent envelope records, with no new run-start question. At the
  merge setting `auto` an unattended run merges once every lens is at C or better; at `gate` it waits.
  A merge confirmation that times out in the Claude Code pane follows the same setting (C14).
- Admission drops its lens and allowance questions, and the run configuration its lens and escalation
  parameters. `/work` reads grades, and a stale review redoes Phase 3.3. A run mid-review at the
  switch restarts on the new command.

Depends on C1 (saga: review records, validation and the A–F formula), C2 (saga: the calibration file
decides which lenses may block), C9 (orchestrate: one targeted reviewer per review, two on high-risk
cards), C10a (saga: one review command from change to records) and C13 (saga: review state for every
harness, the pull request checklist and fix-later choices). Lands together with X1b (Retire the lens
roster, executor ledger and lens catalogue in the lifecycle repository) and X2 (CI standard: the
pinned review tools per language as a required check).

### Risk

high
It replaces saga's only code-review merge gate with no fallback and deletes about 4,500 script lines.

### Inputs inventory

- C1's records and the old `review_cycles` entries (kept, unread); the intent envelope's run mode and
  `ceremony_gates.merge` (fleet-core's `intent_envelope.py:118-127`, `:217`); C2's calibration file.

### Failure modes / pre-mortem

- Most likely: a reader of the old result shapes survives and silently shows nothing or refuses.
- At the switch every lens reports only, so only reproduced data loss or security exposure blocks.
- Moved lines break "the same blocking items" (C1's identity guards it); re-checking only changed code
  drops an unrepaired item (C10a's final-round re-run guards it); a resumed step files twice; bot
  review threads are misread.
- An unattended `auto` run merges past an early stop or the limit. Guard: those always wait (test).

### Stop conditions

- C1, C2, C9, C10a or C13 is unmerged, or X1b and X2 cannot land with this card.
- X1b's lifecycle revision still names the lens-reviewer role, which the roles-library test requires.
- A reader of the old shapes has no owning card.
- A lens blocks before calibration allows it, other than on reproduced data loss or security exposure.

### Out-of-scope / non-goals

- Records, calibration, reviewer, transport and orchestrate's readers, screens, Langfuse (C1, C2, C8,
  C9, C13 to C15); plan review (C12); `/qa` (C16), whose app-interface driver is outside this plan;
  the lifecycle repository and CI (X1b, X2).

### Files expected to change

- `plugins/saga/scripts/review_{roster,consensus,result}.py` (deleted)
- `plugins/saga/skills/code-review/references/{lens-execution,validator,findings-schema}.md` (deleted)
- `plugins/saga/tests/test_review_*.py` (all nine on origin/main, deleted)
- `plugins/saga/tests/test_code_review_switch.py` (new)
- `plugins/saga/skills/code-review/{SKILL.md,references/built-vs-planned.md}`
- `plugins/saga/skills/work/{SKILL.md,references/test-and-gates.md}`
- `plugins/saga/scripts/{admission,run_record,run_status,cost_report,release_step,status_card}.py`
- `plugins/saga/scripts/role_agent_types.py`
- `plugins/saga/com.infiquetra.claude/{commands/code-review.md,types/index.d.ts}`
- `plugins/saga/com.infiquetra.claude/mods/**/admission-review*` (the pane, its test and fixture)
- `plugins/saga/{references/run-record.md,docs/commands.md,CHANGELOG.md}`
- `plugins/agent-launcher/roles/lens-reviewer.md` (deleted)
- `plugins/agent-launcher/roles/expert-repair-implementer.md` (deleted; it serves only escalated
  repairs, `planner.md:140`, and escalation rounds are dropped)
- `plugins/agent-launcher/roles/{review-controller.md,planner.md,index.json,README.md,lifecycle-snapshot.json}`
- `plugins/agent-launcher/skills/agent-launcher/scripts/roster.py`
- `plugins/fleet-core/{scripts/fleet_commons/staffing.json,references/staffing.md}`
- `ports/saga.json`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `test_code_review_switch.py` (canned answers): each round and merge rule, moved lines, a report-only
  lens with reproduced data loss, a resumed filing step, `auto` and `gate` runs, a mid-review restart.
- `test_release_step.py`: an unresolved thread holds the merge; the post-merge loop stops at round 3
  or early. `test_work_gate_integrity.py`: the confirmation contract holds, `auto` included.
- `test_admission.py`, `test_run_record.py`, `test_run_status.py`, `test_cost_report.py`,
  `test_status_card.py`, `test_role_agent_types.py`, `test_build_loop.py`, `usage-capture.test.ts`,
  agent-launcher's `test_roles_library.py` and `test_roster.py`: the lens and allowance cases go.

### Context library links

- infiquetra-sdlc `docs/adrs/adr-001-code-review-executor-boundary.md` (superseded; X1a records it)

### Acceptance criteria

- [ ] `grep -rn "review_roster\|review_consensus\|review_result" plugins/saga/scripts
      plugins/saga/skills plugins/saga/com.infiquetra.claude ports/saga.json` prints nothing, and
      `grep -rn "review_result.v2" plugins/orchestrate` prints nothing.
- [ ] `grep -rln "lens-reviewer\|lens_reviewer\|expert_repair_implementer" plugins --exclude=CHANGELOG.md`
      prints nothing.
- [ ] `/code-review` runs only the review command; each round and merge rule has a passing test.
- [ ] An unattended run merges by itself only at `auto` with every lens at C or better; an early stop
      or the limit with blocking items waits for the operator whatever the setting.
- [ ] Unresolved threads and reproduced data loss or security exposure hold the merge; fix-later
      choices never do. The post-merge loop stops at round 3, or early on the same failures.
- [ ] Admission asks neither question; the run configuration has no lens or escalation parameter;
      `/work` §5.3 sends a stale review through Phase 3.3 (#144).

### Verification

```bash
python3 scripts/bundle_fleet_module.py
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/agent-launcher/tests plugins/fleet-core/tests -q --import-mode=importlib
claude plugin validate --strict plugins/saga && claude plugin test plugins/saga
git diff --check
```

### Notes / conventions

For the planning step:

- `/work` §5.5 keeps its pinned sentence (`tests/test_work_gate_integrity.py:345-366`) and adds that
  an unattended `auto` merge is the operator's run-start confirmation, as the envelope defines `auto`.
- The usage mappings from `review-controller` and `external-reviewer` to `lens-reviewer`
  (`run_status.py:228-233`, `references/run-record.md:299`) move to `targeted-reviewer`.
- How the release step reads unresolved threads through `gh` (an injected runner in tests); how a
  failing scenario is matched across post-merge rounds; how a mid-review run is found at the switch.
