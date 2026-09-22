# Built vs Planned

The audit that answers: **did this change build what was requested — nothing more, nothing less?** It has
two halves, both grounded in the active plan artifact (`docs/plans/`) and the engineering journal
(`docs/engineering-journal/`): **scope-drift detection** (informational) and the **plan-completion audit**
(5-state). Both always run on every review and emit findings. The typed `outcome`, derived from the
overall-score and applicable-dimension thresholds, is the sole acceptance decision; neither half blocks.

## Inputs

- **Stated intent** — the PR body (`gh pr view --json body -q .body` when a PR exists), the branch name,
  commit messages (`git log origin/<base>..HEAD --oneline`), and the calling context. When no PR exists
  (the common case, since `/code-review` runs before a PR), rely on commits and the plan.
- **The plan** — the active artifact under `docs/plans/`, located via the saga's `plan_path` when a saga
  exists, or by content-matching the branch/topic.
- **The journal** — DECISIONS/QUEUED entries for the relevant initiative, for context on what was
  intentionally deferred or chosen.

## Part 1 — Scope-drift detection (INFORMATIONAL)

Compare the files the diff changed against the stated intent, with skepticism:

- **SCOPE CREEP** — files changed that are unrelated to the stated intent; new features or refactors not
  in the plan; "while I was in there..." changes that expand the blast radius.
- **REQUIREMENTS MISSING** — requirements from the plan/PR/TODOS not addressed in the diff; test-coverage
  gaps for stated requirements; partial implementations started but not finished.

Output (before the main lens findings):

```
Scope Check: [CLEAN / DRIFT DETECTED / REQUIREMENTS MISSING]
Intent:    <one-line summary of what was requested>
Delivered: <one-line summary of what the diff actually does>
[If drift: list each out-of-scope change]
[If missing: list each unaddressed requirement]
```

This is **informational** — it produces findings, it does not block. Drift items surface as findings the
operator triages; the typed `outcome`, not the scope check itself, determines whether the PR can proceed.

## Part 2 — Plan-completion audit (5-state)

Extract every actionable item from the plan (checkbox items, numbered implementation steps, imperative
statements, file-level specs, test requirements, data-model changes; cap at ~50). Ignore context/background
sections, open questions, and explicitly deferred items ("Future:", "Out of scope:", "P2:"/"P3:"). Then
classify each item into one of **five states**:

- **DONE** — clear evidence the item shipped. Cite the specific changed file(s) (DIFF-VERIFIABLE) or the
  verified path that exists (CROSS-REPO). Be conservative: a file being touched is not enough — the
  described functionality must be present.
- **PARTIAL** — some work toward the item exists but is incomplete (model created but controller missing;
  function exists but edge cases unhandled).
- **NOT-DONE** — verification ran and produced negative evidence (file missing, code absent from the diff,
  sibling-repo file confirmed absent).
- **CHANGED** — implemented with a different approach than the plan described, but the same goal is
  achieved. Note the difference. Be generous here: if the goal is met by different means, it counts.
- **UNVERIFIABLE** — the diff and any reachable checks can neither prove nor disprove the item. Cite the
  specific manual verification the user must perform.

## The three verification modes

Before judging completion, classify HOW each item can be verified — the diff alone cannot prove every kind
of work:

- **DIFF** (DIFF-VERIFIABLE) — a code change in this repo manifests in `git diff origin/<base>...HEAD`.
  Cross-reference the item against the diff and `git log origin/<base>..HEAD`.
- **CROSS-REPO** — the item names a file or change in a sibling repo. The current diff cannot prove it. If
  the sibling repo is reachable on disk, run `[ -f <path> ]`: exists -> DONE (cite path); missing ->
  NOT-DONE (cite path); unreachable -> UNVERIFIABLE (cite the manual check). A concrete filesystem path
  MUST resolve to DONE or NOT-DONE via the existence check — UNVERIFIABLE is only valid for genuinely
  abstract targets or an unreachable sibling root.
- **EXTERNAL-STATE** — the item names state in an external system (DynamoDB table contents, AWS/IaC
  deployed state, DNS, third-party SaaS, OAuth allowlists). The diff cannot prove it -> UNVERIFIABLE. Cite
  the system and the specific check the user must run.

## The honesty rule

Do NOT classify an item DONE just because related code shipped. **Code that *handles* a deliverable is not
the deliverable** — shipping a markdown-extraction library is not shipping the markdown file. When torn
between DONE and UNVERIFIABLE, prefer **UNVERIFIABLE**: better to surface a confirmation prompt than to
silently miss a deliverable. This is the same no-lies discipline the verify-don't-guess principle enforces
on lens findings — never assert completion the evidence does not support.

## Output

Emit a completion checklist grouped by category (Implementation / Test / Migration / Cross-Repo &
External), each item tagged with its state and evidence, then a one-line rollup:

```
COMPLETION: 5/9 DONE, 1 PARTIAL, 1 NOT-DONE, 1 CHANGED, 2 UNVERIFIABLE
```

NOT-DONE and UNVERIFIABLE items become findings the operator must resolve. If no plan file is found, skip
the completion audit with "No plan file detected — skipping plan-completion audit" and run scope-drift on
intent alone.
