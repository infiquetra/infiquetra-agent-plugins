# Investigation methodology — the full procedure

The ordered procedure `/investigate` runs. Every world-touching step here is **READ-ONLY** until the
GATED Phase 3 fix; the saga is read-only throughout (`restore` / `ticks` only). The spine — causal-chain
gate + predictions for uncertain links — is ported from CE `ce-debug`; the Iron Law + multi-component
boundary instrumentation are borrowed from superpowers `systematic-debugging`.

---

## Triage

**Parse the input** into a clear problem statement: an error message, a test path, a GitHub issue ref, or
a free-text description. For an issue ref, fetch READ-ONLY and read the **full comment thread**:

```bash
gh issue view <N> --json title,body,comments,labels
```

The latest comments usually carry the narrowed scope, updated repro, or prior failed attempts. For a
work-thread saga, read it for evidence READ-ONLY (never mint, never `save`):

```bash
python3 plugins/saga/scripts/saga.py restore --saga-id <issue-N|task-slug>
python3 plugins/saga/scripts/saga.py ticks --saga-id <issue-N|task-slug>
```

**Trivial-bug fast-path.** If the cause is immediately readable (single-file typo, missing import,
obvious null/off-by-one with a one-line fix) and verification needs no deep tracing: present the cause +
the one-line fix, run the fix-vs-diagnosis gate, then apply+self-verify or summarize. When in doubt, run
the full framework — a wrong root cause costs more than the ceremony.

**Prior-attempt awareness.** Only when the user signals "keeps failing" / "stuck" / "I've been trying",
ask what they already tried before investigating. Otherwise do not ask first — investigate.

---

## Investigate (read-only on the world)

### Reproduce

Run the test / trigger the error / follow the reported steps. For a UI surface, drive the running app via
the installed chrome-devtools / playwright MCP (read console + network). Does-not-reproduce after 2-3
attempts → intermittent-bug techniques: logging traps, statistical reproduction in a loop, environment
isolation, test-order pollution checks (run the test alone, then its file, then randomized order).

### Environment-sanity checklist

Before deep tracing, confirm the environment is what you think it is:

- Correct branch checked out; no unintended uncommitted changes.
- Dependencies installed and up to date (`uv sync`, `npm install`, etc.) — stale `node_modules` / venv is
  a frequent false lead.
- Expected interpreter / runtime version (`.tool-versions`, `.python-version`, `pyproject.toml`) vs what
  is actually active.
- Required env vars present and non-empty (and for serverless, the SSM / Secrets values they mirror).
- No stale build artifacts (`dist/`, `.next/`, compiled `.pyc`, generated code, prior-branch binaries).
- Dependent local services (DB, cache, queue) running at expected versions **when the bug plausibly
  involves them**.

### Backward-trace recipe

Trace data flow **backward** from the symptom to where valid state **first became invalid**:

1. Read the stack trace **bottom-to-top**, opening each frame. The bottom frame is the symptom; the cause
   is upstream.
2. Identify the first frame where the input data is **already invalid** — the upper bound on where to
   look.
3. **Instrument the boundaries** around that frame — targeted log/print, breakpoints, or test assertions
   that capture **actual** values at function entry/exit. Assumed values lie; observed values do not.
4. Walk the boundaries until valid input becomes invalid output. That transition is the root-cause site.

Do not stop at the first function that *looks* wrong — the cause is where bad state **originates**, not
where it is first observed.

### Multi-component boundary instrumentation

When the bug crosses subsystems (CI → build → sign, API → service → DynamoDB, queue → Lambda → store), a
single backward trace localizes poorly. Instead, instrument **every** boundary in **one** run:

1. List the boundaries data crosses from trigger to symptom.
2. At each, log what **enters** and what **exits** — values, relevant env, and a short boundary tag.
3. Run the scenario once.
4. Read the log linearly, comparing each "exits" value to the next "enters" value.
5. The boundary where data first stops matching expectation is the failing layer. Backward-trace **within**
   that layer once identified.

This beats backward tracing when the symptom is many components from the trigger, components are owned by
different systems, or the "call stack" is conceptual (message bus, HTTP, process boundaries).

### Recent changes + git bisect

```bash
git log --oneline -10 -- <file>     # what changed recently in files you read
git blame -L <start>,<end> <file>   # who/when for the suspect lines
```

If the bug is a regression ("it worked before"), binary-search the breaking commit:

```bash
git bisect start
git bisect bad                       # current commit is broken
git bisect good <known-good-ref>     # a commit where it worked
# test each checkout, mark good/bad, repeat
git bisect reset                     # return to original branch when done
# or automated: git bisect start HEAD <good-ref>; git bisect run <test-cmd>
```

Harvest additional evidence read-only from `gh` (issue/PR/check output), application logs, the saga
ticks, and prior-session skeletons (`discover_sessions.py` → `extract_session_skeleton.py`).

---

## Root cause

### Assumption audit (before any hypothesis)

List every "this must be true" belief your understanding depends on — the framework behaves as expected
here, this function returns what its name implies, the config loads before this runs, the caller passes a
non-null value, the DB is in the state the test implies. Mark each **verified** (read the code, checked
state, or ran it) or **assumed**. Many "wrong hypotheses" are correct hypotheses tested against a wrong
assumption.

### Hypotheses with evidence + predictions

Form hypotheses ranked by likelihood. For each, state:

- **what** is wrong and **where** (`file:line`);
- **≥1 concrete observation** — a runtime value, a log line, an instrumented boundary capture, a behavior
  delta vs a working case. "X seems off" is theorizing — go back and instrument;
- the **step-by-step causal chain** from trigger to symptom;
- **for uncertain links** — a **prediction**: something in a **different** code path/scenario that must
  also be true if the link holds. Obvious chains (missing import, explicit null) skip the prediction.

### Causal-chain GATE

Do **not** proceed to the fix until the full chain — trigger through every step to symptom — has **no
gaps**. "Somehow X leads to Y" is a gap. The user may explicitly authorize proceeding with the
best-available hypothesis if investigation is genuinely stuck.

### Smart-escalation table + the hypothesis-exhaustion gate

When **2-3 hypotheses are exhausted** without confirmation, STOP (the **hypothesis-exhaustion gate** —
Phase 2's numeric gate, counting hypotheses) and diagnose **why**:

| Pattern | Diagnosis | Next move |
|---|---|---|
| Hypotheses point to different subsystems | Architecture/design problem, not a localized bug | Present findings; suggest `/brainstorm` |
| Evidence contradicts itself | Wrong mental model of the code | Step back; re-read the path without assumptions |
| Works locally, fails in CI/prod | Environment problem | Focus on env diffs, config, deps, timing |
| Fix works but prediction was wrong | Symptom fix, not root cause | The real cause is still active — keep investigating |

### Parallel read-only sub-agent dispatch (offer)

When hypotheses are **evidence-bottlenecked across clearly independent subsystems**, run read-only
probes in parallel — `inline` is the only backend since issue #1030 archived the others, so there
is nothing to offer — each with one
explicit hypothesis and a structured evidence-return format, **no code edits**. Never auto-spawn. Skip
when hypotheses depend on each other's outcomes — parallelism is a latency optimization, not a
correctness requirement; run sequentially in ranked order otherwise. Sub-agents are **generic**
`Explore` / `Task` (this plugin has no `agents/` dir).

---

## Fix (GATED — only a trivial / single-concern fix; else route to /work)

*One change at a time. If you are changing multiple things, stop.*

**Workspace / branch check.** `git status` — confirm before overwriting uncommitted work. If on the
default branch (`main` / `master` / `git rev-parse --abbrev-ref origin/HEAD` with the `origin/` prefix
stripped), ask whether to create a feature branch; derive a name from the bug.

**Test-first → minimal diff:**

1. Write a **failing regression test** that captures the bug.
2. Verify it fails for the **RIGHT reason** — the root cause, not unrelated setup.
3. Implement the **minimal, root-cause-only** fix — no drive-by refactors, formatting, or cleanup.
4. The test passes.
5. Run the **full** suite for regressions.
6. Self-review every changed line (style, edge cases, adjacent regressions, missing coverage).

**Own minimal verification.** Fresh-**reproduce the original bug** and confirm it is fixed. This is the
engine's own verification — `/investigate` does **NOT** route to `/qa` to verify.

**Failed-fix invalidation.** On a failed fix, return to root-cause and **explicitly invalidate the
current hypothesis first** (state the evidence that ruled it out), then form a new one with its own
grounding observation and prediction. Never retry variants of the same theory.

**3-failed-fix-attempts gate (Phase 3's numeric gate — separate from the hypothesis-exhaustion gate).**
After **3 applied fixes fail**, question the **architecture** and return to root-cause. Counts applied
fix attempts, not hypotheses.

**>5-file blast-radius FLAG.** A fix touching >5 files is a **FLAG** — surface the blast radius and offer
a backend — **not** the inline-vs-route discriminator. The discriminator is **trivial/single-concern vs
real implementation work**. Real work routes to `/work` regardless of file count.

**Conditional defense-in-depth** (trigger: the root-cause pattern is in 3+ other files — grep the
signature — OR the bug would have been catastrophic in production). Pick the layers that apply, each as
narrow as possible:

| Layer | Purpose | Apply when |
|---|---|---|
| 1. Entry validation | Reject invalid input at the boundary | A caller passed bad data that should have been rejected |
| 2. Invariant check | Enforce data makes sense for the op | The op has preconditions entry validation can't express |
| 3. Environment guard | Refuse dangerous ops in wrong contexts | The op is catastrophic in the wrong environment |
| 4. Diagnostic breadcrumb | Forensic context before the risky op | Other layers may still be bypassed; future failures need evidence |

Do not duplicate the same check at every layer; do not add guards speculatively without a bug to justify
them. Skip entirely for a one-off with no realistic recurrence path.

`/investigate` never commits, pushes, opens a PR, or deploys — shipping the verified fix is `/work` /
`/code-review`'s job.
