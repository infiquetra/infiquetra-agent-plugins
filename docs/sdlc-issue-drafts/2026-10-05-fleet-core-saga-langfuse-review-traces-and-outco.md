---
title: fleet-core + saga: Langfuse review traces and outcomes at merge
repo: infiquetra-agent-plugins
type: enhancement
team: asgard
project: operations
labels: enhancement, needs-plan
risk: high
handoff_maturity: requirements-ready
stage: Shaping
status: Discovering
approval_state: approved
---

# fleet-core + saga: Langfuse review traces and outcomes at merge

### Objective

Every saga review run and plan review becomes one trace in a Langfuse project of its own, "Saga
Reviews", with each finding's fate at merge attached and the corpus as a dataset. Keys are never
printed, secrets and raw tool output never leave the machine, a private repository sends nothing until
Langfuse has HTTPS (encrypted web traffic), and a Langfuse problem never fails a review.

### Intent

Today Langfuse appears nowhere in saga or fleet-core, and review results carry no tokens, cost or time.
fleet-core's TypeSafe client (`plugins/fleet-core/scripts/fleet_commons/typesafe_client.py`) is the
pattern for data leaving the machine: the key goes only into the request header (`:552-561`),
redaction runs on the only path to a transport (`:420-474`), and plain HTTP is refused off this machine.

What changes (plan.md, Change 9; Change 1 "Review run"; Change 8 "Watched"):
1. A standard-library Langfuse client in fleet-core, bundled into saga. It reads only
   `SAGA_LANGFUSE_PUBLIC_KEY`, `SAGA_LANGFUSE_SECRET_KEY` and `SAGA_LANGFUSE_HOST`, because the standard
   names hold the tracing plugin's keys. It never prints a key, redacts on the only path out, and checks
   certificates against the default trust store.
2. A private repository, or one whose visibility `/saga:setup` (C3) has not recorded, posts only when
   `SAGA_LANGFUSE_HOST` is `https`. A public one may post before X3. When X3's publicly trusted
   certificate is in place, the operator points the host at it.
3. The review command (C10a) gains the posting step, which never fails the review. An unreachable
   Langfuse, or a refused post (a private repository while the host is plain HTTP, or missing keys),
   leaves the post in an owner-only queue under the user's home with its reason. It is sent once the
   reason clears and is never dropped; setup's degraded signal shows how many posts wait.
4. One trace per review run carries the repository, base and head commits, card, saga and tool
   versions. It has an entry per step (each tool run, the Jev sweep, each large language model (LLM)
   step, the formula) and per finding. The sweep's entry holds each verdict's resolved model version.
   Each LLM step holds its reviewer's vendor, model, configuration fingerprint, tokens, cost and time,
   from the session's result.
5. Sent: the five records (C1) and each finding's code excerpt. Raw tool output stays in C4a's
   owner-only store under the user's home and leaves only as a fingerprint. A secret-scanner finding
   sends its location, never the secret.
6. At merge, each finding's outcome attaches to it by C1's finding identity: fixed (its lines changed,
   and its reproducing test passed in C10a's final round), dismissed with the reason, fixed now, filed
   with the issue number, or left. Plan reviews post the same way (C12 adds the call). Round additions
   post too, and a Langfuse view shows how often round 2 or 3 finds anything new.
7. The operator creates the project and key pair; keychain-env holds the keys. The corpus is one
   dataset and counts as private. Held-out items carry case IDs only; held-out results post as totals.
   Code evaluators post per-lens hits and false blocks, per-question precision, grade stability and
   cost as scores. Nothing is deleted automatically.

Depends on C1 (saga: review records, validation and the A–F formula) and C10a (saga: one review command
from change to records). Private repositories also need X3 (Langfuse: serve over HTTPS before review
data includes private code).

### Risk

high
It sends code and review data off the machine with a key pair; one wrong default can leak private code.

### Inputs inventory

- The five records (C1), each reviewer's usage, plan-review findings (C12) and C13's merge outcomes.
- Code excerpts at the reviewed head; raw tool output (C4a), which can hold the secrets a scanner found.
- The recorded visibility (C3), the three `SAGA_LANGFUSE_*` values, and corpus cases (K1), some private.

### Failure modes / pre-mortem

- **Wrong project:** the client reads the standard `LANGFUSE_*` names and posts to the tracing project.
- **A secret is sent:** redaction misses a shape, or a scanner finding's excerpt is the secret line.
- **Private code in clear text:** a visibility check treats an unrecorded answer as public.
- **Keys on the wire:** a public repository's posts carry the key pair over plain HTTP until X3.
- **Held-out cases leak:** a held-out item carries code, or a held-out result is posted per case.
- **Local data leaks or Langfuse is down:** the queue or store is readable by others; a review waits,
  fails or loses its posts.

### Stop conditions

- Stop before any request for a private or unrecorded repository while the host is not `https`.
- Stop if a test, log or payload shows a key, a scanner-matched secret, unredacted secret text, or
  held-out case content.
- Stop before adding anything that deletes Langfuse data automatically.

### Out-of-scope / non-goals

- HTTPS on the server (X3); records and finding identity (C1); re-running reproducing tests (C10a);
  recording merge outcomes (C13); the raw-output store (C4a); recording visibility (C3).
- The corpus and harness (K1 to K3), which use this dataset and its evaluators; `/qa` misses and the
  scheduled outcome job (C16); LLM-based evaluators, until checked against hand labels.

### Files expected to change

- `plugins/fleet-core/scripts/fleet_commons/langfuse_client.py` (new)
- `plugins/fleet-core/references/langfuse.md` (new)
- `plugins/fleet-core/README.md`
- `plugins/fleet-core/CHANGELOG.md`
- `plugins/saga/fleet-bundle.json`
- `plugins/saga/scripts/_bundled/langfuse_client.py` (new, generated by the bundling script)
- `plugins/saga/scripts/review_trace.py` (new): trace layout, visibility rule, local queue
- `plugins/saga/scripts/review_dataset.py` (new): corpus dataset and code evaluators
- `plugins/saga/scripts/review_command.py` (C10a's command: the posting step)
- `plugins/saga/references/review-command.md` (C10a's reference: the posting step)
- `plugins/saga/scripts/release_step.py` (posts outcomes once the merge is seen)
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- `plugins/fleet-core/tests/test_langfuse_client.py` (new), injected opener, no network: a sentinel key
  never shows in a result, log, error or payload; a payload that skipped redaction is refused (as in
  `test_typesafe_client.py:545`); secret shapes become `[REDACTED]`; with only the standard names set,
  nothing is sent; a private or unrecorded repository on plain HTTP is refused naming X3, and a public
  one is sent; requests keep the default certificate check.
- `plugins/saga/tests/test_review_trace.py` (new): a fixture run gives the trace and entries above; raw
  output leaves only as a fingerprint, a scanner finding as its location; outcomes attach after a line
  shift; an unreachable server queues the post owner-only under a temporary home for the next post.
- `plugins/saga/tests/test_review_dataset.py` (new): held-out items carry case IDs only, held-out
  results post as totals, and each evaluator matches a hand-worked fixture.
- `plugins/saga/tests/`: `test_review_command.py` (a Langfuse failure changes no record or exit status),
  `test_release_step.py` (only a merged release posts outcomes, once), `test_entrypoints.py` (the
  bundled client is internal; Langfuse key prefixes are stripped).

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` (Change 9)
- `plugins/fleet-core/references/typesafe.md` (the data rule and key handling this client mirrors)
- infiquetra-context-library: `docs/governance/adrs/adr-0007-fleet-observability.md`

### Acceptance criteria

- [ ] `python3 scripts/bundle_fleet_module.py --check` passes; the client uses only the standard library.
- [ ] The client reads only the `SAGA_LANGFUSE_*` variables; the standard names alone send nothing.
- [ ] A private or unrecorded repository sends nothing over plain HTTP, naming X3, and posts over `https`
      with the default certificate check; a public repository posts either way.
- [ ] With Langfuse unreachable or refusing, a review finishes with the same records and exit status; the
      post waits in the queue with its reason and goes once the reason clears.
- [ ] A review run posts one trace with an entry per step and per finding, each verdict's model version
      and each reviewer's tokens, cost and time; raw tool output leaves only as a fingerprint.
- [ ] After a merge, each finding's entry carries its outcome, with the reason or issue number it needs.
- [ ] The project and key pair exist; `git grep -nE '(sk|pk)-lf-[0-9a-f]{8}'` finds no key in the tree.
- [ ] The corpus dataset has both splits; held-out items carry case IDs only and held-out results are
      totals; the code evaluators post the agreed numbers as scores.
- [ ] A Langfuse view shows how often round 2 or 3 found anything new; nothing deletes data automatically.

### Verification

```bash
python3 scripts/bundle_fleet_module.py && python3 scripts/bundle_fleet_module.py --check
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/fleet-core/tests plugins/saga/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

For the planning step:
- `CREDENTIAL_PREFIXES` (`plugins/saga/tests/test_entrypoints.py:45`) gains `SAGA_LANGFUSE_` and
  `LANGFUSE_`. The key pair goes only into the basic-auth header, resolved as
  `typesafe_client.py:552-561` resolves its key; requests use `urllib`'s default certificate context.
- Visibility comes from the key C3 names; a missing value counts as private, and the corpus dataset
  always posts as private. Trace IDs derive from C1's review run ID, so later posts need no lookup.
- The posting subcommand's name (for example `post`): `finish` calls it, C12 calls `review_trace.py`,
  and `release_step.py release` calls it once it sees the merge (C16 also edits `release()`). The queue
  sits beside C4a's store, owner-only as `fleet_commons/audit_store.py:89-99` writes, oldest first out.
- A secret-scanner finding's excerpt is left out rather than redacted. Score names and data types are
  set here; the rounds view is a Langfuse dashboard over the round scores. Dataset items carry their
  split in metadata; K3 records harness runs and calls the evaluators. New file names are proposals.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C15-langfuse-review-traces.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C15-langfuse-review-traces.md
- Source type: brainstorm
- Source title: fleet-core + saga: Langfuse review traces and outcomes at merge

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/166
- Number: 166
- Created at: 2026-10-05T19:15:15.813005+00:00
