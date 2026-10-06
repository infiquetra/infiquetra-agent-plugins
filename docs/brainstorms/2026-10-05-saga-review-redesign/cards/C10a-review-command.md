---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: one review command from change to records

### Objective

One script takes a change (repository, base commit, head commit), the repository profile and the
builder record; runs the tools, our checks and the sweep (TypeSafe Jev's where-to-look questions);
writes the packet for the large language model (LLM) reviewer; checks, re-runs and merges one or two
answers; applies the formula; and writes the five review records and the reviewers' usage. It starts
no session, so `/code-review` (after C10b) and the corpus harness (K3) run the same code.

### Intent

Today on origin/main (1f7137d), paths under `plugins/saga/`:

- No script runs a review end to end. A controller session follows `skills/code-review/SKILL.md`;
  scripts only resolve a roster (`scripts/review_roster.py`), print a verdict word
  (`review_consensus.py:2313`) and append a result (`review_result.py:1194`). Only a test chains them.
- Saga must not start reviewer sessions; orchestrate and agent-launcher do
  (`skills/code-review/SKILL.md:77-90`). So the harness has no saga code to call.
- Session usage reaches the run record through `scripts/run_record.py usage add` (lines 815-853),
  where a repeat add with the same identity adds into the entry. The usage-capture mod
  (`com.infiquetra.claude/mods/usage-capture.ts:1-29`) calls it for each Claude Code session whose
  directory works a unit row, by session id, so it may already have recorded a reviewer session.

What changes (plan.md, Change 8, and "The harness: One review command"):

- **One script, two calls**, because a reviewer session runs between them and saga does not start it:
  1. `prepare` takes the repository, base and head commits, `.saga-profile.json` and the builder
     record (C1's format; C11 captures it, and corpus cases carry one). It runs the tools and our
     checks through C4a's runner (with C4b, C4c, C5 and C5b where present) and the sweep (C6), writes
     their findings, measurements and where-to-look items as records (C1), and writes the packet.
  2. `finish` takes one or two answer files and each session's result (C8). It runs C8's answer check
     on each answer, re-runs the reproduction tests, merges the findings, applies the formula (C1) with
     the calibration answer per lens and language (C2), and writes the lens grades and the review run.
- **The packet** carries the change, the where-to-look list, the deterministic results, the builder's
  declarations and recorded reasons (which the LLM checks and may dispute), the questions the LLM
  answers in place of a missing tool, and the cap on open-search findings.
- **Two answers merge.** A second reviewer answers the same packet on high and very-high risk cards
  (C9). `finish` drops duplicates by C1's finding identity, keeping any reproduction either recorded.
- **Reproductions re-run.** `finish` re-runs each reproduction test itself, in its own sandbox:
  write access to the scratch copy only, no network, no credentials. A finding counts as reproduced
  only when its test fails again there; otherwise it is treated as traced (fix later). In the final
  round, `finish` re-runs every blocking finding's test to confirm the fix. Without the sandbox
  (setup checks for it, C3), no finding counts as reproduced and the run is marked degraded.
- **Reviewer usage.** `finish` takes each session's usage from its result and keeps tokens, cost and
  time on the review run record. Given an issue number, it also writes each session through
  `run_record.py usage add` as an ordinary usage entry with the reviewer's role, vendor, model and
  effort, skipping a session the usage-capture mod already recorded, so none counts twice. Live
  spend, budget notices and the cost report (O1, O3, O4) then count reviewer cost without reading
  review runs. With no issue number, the usage stays in the output folder's records only.
- **Reviewer configuration.** The review run records each reviewer's vendor, model, prompt
  fingerprint and configuration fingerprint (its instruction files and enabled plugins, from its
  result). A configuration other than the calibration file's (C2) is noted there, never refused.
- **A missing tool degrades the review and never stops it.** Its checks go into the packet as
  questions for the LLM, and the records mark those answers degraded (plan.md Change 2).
- **Where records go.** Given an issue number, into the run record through C1's writer. Without one,
  into a named output folder, which is how the harness runs a corpus case.
- **The deterministic part runs alone.** `prepare` and the formula over its records give grades with
  no reviewer at all, and the same records for the same inputs. K2's wiring checks and K3's repeat
  runs call it. The command's paths join C2's fingerprinted component list.

Depends on C1 (saga: review records, validation and the A–F formula), C2 (saga: the calibration file
decides which lenses may block), C4a (saga: build-loop tool framework reporting only what a change
introduces), C6 (fleet-core + saga: the Jev sweep says where to look in a change) and C8 (saga +
agent-launcher: the targeted LLM reviewer).

### Risk

medium
It has no caller until C10b, but it becomes the one path every review and every corpus run takes.

### Out-of-scope / non-goals

- Switching `/code-review`, the rounds, the merge rules and the deletions (C10b).
- Starting reviewers and collecting their answers and results (C9 in saga, K3 in the harness); the
  reviewer's prompt, answer schema, answer check, launch and its own sandboxed test runs (C8).
- The tools, our checks and the sweep themselves (C4a to C4c, C5, C5b, C6); the review-state
  document, screens and pull request comment (C13, C14).
- Posting to Langfuse (C15 adds that step to this command); the combined-branch gate that fails on a
  blocking tool finding before the LLM step (C11).

### Files expected to change

- `plugins/saga/scripts/review_command.py` (new)
- `plugins/saga/references/review-command.md` (new)
- `plugins/saga/tests/test_review_command.py` (new)
- `plugins/saga/references/run-record.md`
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- `plugins/saga/tests/test_review_command.py`, on a throwaway git repository in a temporary folder,
  with fake tool adapters, a fake classifier behind C6's contract, and canned answers and results:
  - `prepare` writes a packet naming every where-to-look item, and records that pass C1's validator;
  - `finish` with one complete answer writes all five record kinds and the grades the formula gives;
  - two answers give one merged set; a finding both report appears once and keeps its reproduction;
  - an answer C8's check refuses stops `finish` with the reason, and nothing is written;
  - a test that passes on the re-run does not count as reproduced; the re-run's sandbox denies
    writes outside the scratch copy, the network and credentials; the final round re-runs every
    blocking test; with no sandbox nothing counts as reproduced and the run is degraded;
  - a missing tool puts its check into the packet, and the finding is degraded and does not block;
  - "report-only" reports a blocking item and allows merge; "may block" refuses it;
  - the deterministic part alone gives grades with no answer, identical on a second run;
  - with an issue number, each reviewer session becomes one `usage add` entry with its role, vendor,
    model and effort, and the review run keeps tokens, cost and time; a session the mod recorded, or
    a repeated `finish`, adds nothing; without a number, no run record is touched;
  - the review run records each reviewer's vendor, model and both fingerprints; a configuration
    other than the calibration file's is noted, and the review completes;
  - no process the command runs starts a reviewer session, and no test reaches the network.
- `plugins/saga/tests/test_entrypoints.py` picks up the new script's `--help` with no credentials.

### Context library links

- `plugins/saga/skills/code-review/SKILL.md` (reviewer-session transport, lines 77-90)
- infiquetra-context-library `docs/testing/quality-gates.md`

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/review_command.py prepare --repo <path> --base <commit> --head
      <commit> --profile <file> --builder-record <file> --out <folder>` writes the packet and the
      deterministic records.
- [ ] `python3 plugins/saga/scripts/review_command.py finish --packet <folder> --answer <file>
      --result <file>`, with a second answer and result allowed, writes the lens grades and the
      review run, or refuses with the reason and writes nothing.
- [ ] Each answer covers every where-to-look item or is refused; two answers merge with no duplicate.
- [ ] A finding counts as reproduced only after the command's own sandboxed re-run fails.
- [ ] Given an issue number, each reviewer session is written once through `run_record.py usage add`
      with its role, vendor, model and effort, skipping a session the usage-capture mod already
      recorded; without one, the run record is untouched.
- [ ] The review run records each reviewer's vendor, model, prompt fingerprint and configuration
      fingerprint; a configuration that differs from the calibrated one is noted, never refused.
- [ ] A missing tool marks its inputs degraded and never stops the review.
- [ ] The command never starts a reviewer session, asserted over every process it runs.
- [ ] `references/review-command.md` documents the inputs, outputs, exit codes and both callers.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes with no network call.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

For the planning step:

- File, subcommand and option names are proposals. `/code-review` keeps its name and this card adds
  no command, so the command surface pins do not change. Standard library and PyYAML only.
- The sandbox mechanism for the re-runs.
- How `finish` knows a round is the final one, and how a re-run's failure is matched to the output
  the reviewer recorded.
- Which unit row a reviewer's usage entry goes on. A repeat `usage add` adds into the entry
  (`run_record.py:829-830`), so `finish` first looks for the session's id, the mod's
  `<session>/<agent>` ids included (`usage-capture.ts:116-119`); that check also stops a repeated
  `finish` counting twice. The second reviewer's role name follows C9.
- Where the builder record is read from: the unit's run-record entry, or a corpus case's file.
- The fingerprinted component list's file is C2's; this card adds its paths in the same change.
