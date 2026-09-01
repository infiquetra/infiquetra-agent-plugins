---
title: U2 — Synchronize the portable mission-control package from pinned upstream 3b2b7083
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: high
handoff_maturity: requirements-ready
approval_state: approved
---

# U2 — Synchronize the portable mission-control package from pinned upstream 3b2b7083

### Objective

Run the synchronization that derives the portable package from upstream
`3b2b7083`, regenerating every byte copy, re-applying all four transform rules,
relocating the Claude manifest, and rewriting `PROVENANCE.json`.

This is the unit that actually moves the pin. It is mechanical by design: the
descriptor decides custody, and the tool applies it. If this unit finds itself
making a judgment call, something upstream of it was left unsettled.

### Intent

Run `scripts/sync_vendor_source.py --package mission-control --source <upstream>
--commit 3b2b7083`, then prove the result round-trips.

**What changes, measured.** 36 files differ between the two pins: 17 upstream byte
copies, 5 transform outputs (`scripts/sdlc_manager.py` plus four of the seven
`SKILL.md` files), 5 client byte copies (the four Claude commands and the
`sdlc-operator` agent), the relocated Claude manifest, and the superseded upstream
README whose bytes are deliberately never read. Seven new test files arrive as byte
copies per U1's custody. Nothing is deleted upstream. The package moves from 64
files to 71.

**All four transform premises were verified to hold at the new pin, and this unit
must prove it rather than assume it.** All seven `SKILL.md` files still carry the
`when_to_use` key that `normalize-skill-frontmatter` folds. `executor_profile_lint.py`
is byte-identical to the old pin, so `resolve-bundled-fleet-module-split` is
untouched. The guarded block in `sdlc_manager.py` that
`resolve-bundled-fleet-module-guarded` rewrites is byte-identical in shape — only
its line number moved, from 4283 to 5134 — and the rule matches by pattern, not by
line. `relocate-claude-manifest` is a pure relocation whose source and output
digests are equal.

**Fleet Core needs nothing.** `git diff 84eaf042 3b2b7083 -- plugins/fleet-core` is
empty across the whole window, so the bundled modules under `scripts/_bundled/` and
`fleet-bundle.json` are unaffected. Do not regenerate them, and do not repin
fleet-core: that would churn the UniFi bundles and invalidate UniFi's committed
matrix, which is a stop condition inherited from #9.

**The target-owned surface is not this unit's.** `README.md`, `plugin.json`,
`fleet-bundle.json`, and `scripts/_bundled/` are authored here and must not be
overwritten. The tool records them as target-owned without a digest and never
writes them; if `--check` reports drift in one of those paths, stop.

### Out-of-scope / non-goals

- No edit to `plugins/mission-control/README.md` or `plugins/mission-control/plugin.json`. Those are U3's.
- No edit to `ports/mission-control.json`. U1 owns the descriptor.
- No fleet-core repin and no bundle regeneration.
- No hand-repair of any synchronized byte. A needed change goes upstream.
- No downstream test edits. U4 owns those.

### Inputs inventory

- `ports/mission-control.json` as U1 left it, with all eight new upstream paths classified.
- Upstream read-only checkout at `3b2b7083`, proven green by U0.
- `scripts/sync_vendor_source.py` and its four transform rules: `relocate-claude-manifest`, `resolve-bundled-fleet-module-split`, `resolve-bundled-fleet-module-guarded`, `normalize-skill-frontmatter`.
- Current package state: 64 files, tree `651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682`.

### Files expected to change

- `plugins/mission-control/PROVENANCE.json`
- `plugins/mission-control/CHANGELOG.md`
- `plugins/mission-control/config/sdlc-schema.json`
- `plugins/mission-control/scripts/sdlc_manager.py`
- `plugins/mission-control/scripts/sync_template_docs.py`
- `plugins/mission-control/skills/board/SKILL.md`
- `plugins/mission-control/skills/flow/SKILL.md`
- `plugins/mission-control/skills/issues/SKILL.md`
- `plugins/mission-control/skills/rollout/SKILL.md`
- `plugins/mission-control/skills/board/references/graphql-queries.md`
- `plugins/mission-control/skills/board/references/kanban-workflow.md`
- `plugins/mission-control/com.infiquetra.claude/plugin.json`
- `plugins/mission-control/com.infiquetra.claude/agents/sdlc-operator.md`
- `plugins/mission-control/com.infiquetra.claude/commands/board.md`
- `plugins/mission-control/com.infiquetra.claude/commands/issue.md`
- `plugins/mission-control/com.infiquetra.claude/commands/metrics.md`
- `plugins/mission-control/com.infiquetra.claude/commands/triage.md`
- `plugins/mission-control/tests/` — eleven modified and seven new test files

### Tests to add or update

None authored by this unit. The seven new upstream test files arrive as byte copies
and are not edited here; editing a byte copy to make it pass is the custody
violation this whole arrangement exists to prevent. If a carried test cannot pass
in the portable layout, that is an upstream filing or a recorded custody decision,
not a content change — see Stop conditions.

### Failure modes / pre-mortem

**Most likely: a transform rule refuses on new upstream bytes and the run relaxes
the rule to fit.** The rules assert "expected exactly one" match by design. A rule
that is widened to accept a second shape stops proving the thing it exists to prove.
If a rule refuses, stop and report the shape it found.

**Second: a byte copy is hand-edited to make the suite pass.** The digest check
catches it, but only if it is run. Prove digest equality for every byte-copied path
before claiming the unit is done.

**Third: the target-owned surface is overwritten.** If `--check` reports drift in
`README.md`, `plugin.json`, `fleet-bundle.json`, or `scripts/_bundled/`, the
descriptor's custody is wrong and the sync must not be applied.

**Fourth: the package tests fail because the portable layout differs from upstream's.**
Seven new tests were verified hermetic, but verification is not execution. Run them.

### Stop conditions

| Condition | Action |
|---|---|
| Any transform rule refuses | Stop. Report the shape found. Never relax a rule to fit. |
| `--check` reports drift in a `target-owned` path | Stop. The sync would overwrite authored source. |
| A byte copy's post-sync digest does not equal its source digest | Stop. |
| A carried test cannot pass without a content change | Stop. Upstream filing or recorded custody decision, never an edit. |
| Upstream `requires-python` has moved above this catalog's floor | Stop. The floor is part of the synchronization contract. |
| Any live GitHub write from build or test | Run-level stop. |
| A resync-forced edit to any of the five mutation-proof graded files | Stop and escalate. |

### Context library links

- `docs/runbooks/portable-plugin-port.md` — Phase 1, Lane A
- `docs/engineering-journal/DECISIONS.md` — transform-rule selection and skill-frontmatter custody

### Acceptance criteria

- [ ] `python3 scripts/sync_vendor_source.py --package mission-control --source <upstream> --commit 3b2b7083` completes without error.
- [ ] The round-trip proves clean: re-running the same command with `--check` prints a match line naming `3b2b7083` and exits 0.
- [ ] `PROVENANCE.json` records `source_commit` `3b2b7083...` and `source_version` `2.15.2`, proven by `python3 -c "import json;d=json.load(open('plugins/mission-control/PROVENANCE.json'));print(d['source_commit'],d['source_version'])"`.
- [ ] The package holds 71 files, proven by `git ls-files plugins/mission-control | wc -l` printing `71`.
- [ ] `tests/test_card_validator_agreement.py` is absent from the package, proven by `test ! -e plugins/mission-control/tests/test_card_validator_agreement.py`.
- [ ] Every byte-copied path's recorded digest equals its source digest, enforced by the `--check` round-trip above.
- [ ] `python3 scripts/check_repo.py` prints `Repository validation passed.`
- [ ] `python3 -m pytest plugins/mission-control/tests -q` passes on the floor interpreter.
- [ ] `git diff --check` produces no output.

### Verification

```bash
# Apply, then prove the round-trip
python3 scripts/sync_vendor_source.py --package mission-control \
  --source ../infiquetra-claude-plugins --commit 3b2b7083
python3 scripts/sync_vendor_source.py --package mission-control \
  --source ../infiquetra-claude-plugins --commit 3b2b7083 --check

# Pin, file count, and the excluded test
python3 -c "import json;d=json.load(open('plugins/mission-control/PROVENANCE.json'));print(d['source_commit'],d['source_version'])"
git ls-files plugins/mission-control | wc -l
test ! -e plugins/mission-control/tests/test_card_validator_agreement.py && echo "excluded as ruled"

# Gates
python3 scripts/check_repo.py
python3 -m pytest plugins/mission-control/tests -q
git diff --check
```

### Handoff maturity
requirements-ready

### Suggested next action
Use `/plan <issue>` to create an implementation plan.

### Source context
- Source: session issue-shaping pass, 2026-08-30, validated against a fresh upstream fetch
- Source type: operator-settled shaping decisions
- Source title: Mission Control resynchronization 2.12.2 to 2.15.2 — settled shaping

### Recommended Tier Band
opus/high

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/53
- Number: 53
- Created at: 2026-08-30T19:23:49.734173+00:00

