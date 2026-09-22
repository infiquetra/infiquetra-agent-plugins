# TypeSafe (Jev): the data rule, the verdict log, and the house rules

This is the policy that governs every use of the TypeSafe System One endpoint from this fleet. The client that enforces it is `plugins/fleet-core/scripts/fleet_commons/typesafe_client.py`; the command-line front door is `plugins/fleet-core/scripts/jev.py`.

Read this before wiring a judgment into any skill, hook, or command.

---

## 1. The data rule — what may leave the machine

State sent to TypeSafe leaves this machine and reaches a third-party vendor. The rule below was decided once and is recorded in `docs/engineering-journal/DECISIONS.md`; it is not a per-caller judgment.

### May be sent, after redaction

Issue bodies, plan and requirements text, code-review findings, diffs, commit messages, file paths, and the repository's own policy documents. This is content this fleet already sends to other model vendors through the external-engine HTTP bridge, so sending it here creates no new class of exposure.

### May never be sent

Credentials of any kind, raw session transcripts, and customer content. A transcript is excluded even after redaction: it is long, it is uncontrolled, and it routinely contains material nobody vetted for this purpose.

### The rule is a mechanism, not a promise

Redaction is not something a caller remembers to do. `prepare_state()` redacts and then truncates, and it stamps its output with a marker; `build_body()` refuses any state without that marker. There is no path from a caller to a transport that skips it, including from inside the client module itself. The test `test_redaction_is_on_the_only_path_to_a_transport` asserts exactly this.

### What redaction replaces

Every match is replaced with the literal `[REDACTED]`.

| Shape | Example |
|---|---|
| Bearer tokens | a scheme word followed by the secret |
| Named assignments | a secret-shaped name, an equals sign, and the value |
| Private-key blocks | a PEM header and footer around the key material |
| Vendor key forms | Amazon access key identifiers, GitHub `ghp_`-style tokens, `sk-` prefixed keys |
| Secret-named mapping keys | any value under a key named `api_key`, `secret`, `token`, `password`, `credential`, `private_key`, or `authorization` |
| High-entropy runs | 40 or more characters from the base64 alphabet with a Shannon entropy of at least 4.0 bits per character |

The high-entropy rule deliberately does **not** fire on a line that looks like a lock-file integrity hash. Without that exemption the first real diff sent would arrive as mostly placeholders, and the answer would be wrong in a way no ordinary test catches. This catalog has no `uv.lock`. `test_a_long_repository_path_survives_redaction` keeps a long path from being shredded.

### The key itself

`TYPESAFE_API_KEY` is read through an injected environment reader at request-build time and placed only in the `Authorization` header. It is not a field of any result, it is never logged, and it is never interpolated into an exception message — vendor exceptions are re-raised with text this repository composes, so a vendor string quoting request details cannot reach a log unexamined. This holds on both transports: the SDK is handed the key explicitly rather than being left to read the environment through its own code.

Because the key lives only in the header, `jev ask --dry-run` is safe to print and safe to paste into an issue.

---

## 2. The verdict log

Every answer is recorded outside any model's context, so the evaluation harness has something real to score and so an operator can audit what was asked.

### Where it lives

`~/.claude/typesafe/verdicts.jsonl` by default, overridable with `INFIQUETRA_TYPESAFE_LOG_DIR`.

The home directory, not the repository, and that is load-bearing. Agents here run in git worktrees under `.claude/`, which is git-ignored, so a repository-rooted log would be per-worktree and would vanish with the worktree — taking the accumulated evidence with it. This matches where `audit_store.py` puts the delegation audit store, for the same reason.

### The record

One JSON object per line, appended, never rewritten.

| Field | Meaning |
|---|---|
| `kind` | `verdict` or `override` |
| `decision_id` | which judgment point asked; the join key the harness scores on |
| `state_hash` | a hash of the state, never the state itself |
| `questions_hash` | a hash of the question set |
| `answer` | the typed answer as returned |
| `confidence` | the answer's confidence, or `null` — see below |
| `threshold` | the confidence floor in force when the answer was taken |
| `resolved_model` | the version that answered, such as `jev-1.13.0`, never the alias |
| `label` | the known-correct value when one is known, else null; the harness scores against it |
| `at` | an ISO 8601 timestamp |
| `verdict_hash` | the identity an override points back to |

An override record carries `verdict_hash`, the `chosen` value, and a `rationale`.

### Confidence, and the one asymmetry worth knowing

A yes/no (`noul`) answer carries a probability and **no confidence field**; choice and score answers carry both. This was verified against the live endpoint, not taken from the documentation. So a yes/no verdict records `confidence` as `null`, and the harness bands it by the probability's distance from one half, doubled. Every caller uses `typesafe_client.answer_confidence()` rather than deriving this again.

### The model alias and the cache

The cache is keyed on the **requested** model alias, because the resolved version is only known from the response while a lookup necessarily happens before the call. A pin file records what each alias last resolved to; when the resolution moves, the whole bucket for that alias is invalidated rather than served. Keying on the alias alone would silently replay a `jev-1.13.0` answer after the alias moved on.

---

## 3. House rules for any use

1. Code owns control flow. Jev returns a probability; a typed answer never executes an action by itself.
2. Three bands per decision — act, confirm, escalate. The uncertain middle resolves to the cheaper mistake. Thresholds come from the evaluation harness, never from a cookbook.
3. Any existing regex or hard-coded pattern is a **floor**. Jev may only widen what triggers a mandatory gate, never narrow it.
4. One literal condition per question. Pass policy text as state. Write criteria from this repository's actual practice, with examples — generic criteria get the generic meaning, which is how a skills repository ends up with prose classified as though it were not behavior.
5. Batch every question about one state into one request.
6. Redact before sending, never send raw transcripts, and obey the data rule above.
7. Log every verdict with the resolved model version, outside model context. Pin it, and re-judge when the alias moves.
8. Fail open by documented policy, per gate, and say which side fails open.
9. Never use it for arithmetic, counting, date comparison, adversarial screening, live external state, generation, main-session model routing, or controller staffing from benchmark tables.
10. Suggest first. A decision becomes automatic only after a recorded harness run at the chosen band, and the operator can always override.

---

## 4. Measuring a judgment before trusting it

Ship every judgment in suggest mode with its verdict logged, and log operator overrides beside the verdicts. After roughly thirty real uses of a decision, run the harness:

```bash
uv run python plugins/fleet-core/scripts/jev.py eval --cached <recorded answers>
```

It reports agreement overall and per confidence band. The decision then stays advisory, becomes automatic above a band, or is removed — and whichever happens is recorded in `docs/engineering-journal/LEARNINGS.md`.

The harness reads either a list of records carrying `id`, `state`, `questions`, `answer`, `label` and `resolved_model`, or the verdict log itself, joining answers to labels on `decision_id`. Default confidence bands are below 0.6, 0.6 up to 0.8, and 0.8 and above.

---

## 5. The widen-only union

House rule 3 says a pattern is a floor the model may raise and never lower. `jev_widen.py` is the one place that implements it, so no caller writes the rule twice.

```python
# Loaded through the per-plugin bundle loader, the way plugins/saga/scripts/bundled_fleet.py
# and its callers (plugins/saga/scripts/parse_issue.py is the worked example) load it.
jev_widen = bundled_fleet.load("jev_widen")
result = jev_widen.widen(state, "issue-flags", floors, decision_prefix="issue-flags")
```

`floors` maps a question key to the pattern's verdict. Every key comes back carrying the floor, the probability, the union (`floor or probability >= threshold`) and which side produced it. There is no path in which a floor of `True` returns a union of `False`.

**Failure is always the floor.** An error, a timeout, a malformed body, a missing key, a missing answer or a non-numeric probability all return the caller's floors unchanged with a reason in `note`, and write no verdict. A caller that ignores `note` behaves exactly as it did before it asked anything.

**The question sets live in the verb registry**, not in the callers, so `jev issue-flags` and `jev journal-nudge` work from the command line for free.

| Verb | Keys | Threshold | Who asks |
|---|---|---|---|
| `issue-flags` | the five keyword flags plus the seven approval boundaries | 0.70 | `plugins/saga/scripts/parse_issue.py --flags` |
| `journal-nudge` | `earns_entry` | 0.60 | `plugins/saga/hooks/journal_nudge_hook.py` |

Both thresholds are **provisional**: they come from which mistake is cheaper, not from measurement. A false flag costs an extra review lens; a false nudge costs one line on standard error, which is why the nudge can afford to be readier. Every verdict records the threshold in force, and §4 is how they get settled.

**Which side each caller fails open on.** `parse_issue.py` returns the keyword result and still exits 0, because four saga skills read its JSON and a missing key would break them. The hook stays silent, asks at most once with a two-second request timeout and a three-second deadline, and never blocks a commit; `INFIQUETRA_TYPESAFE_JOURNAL_NUDGE=off` skips the call entirely.

**The seven approval boundaries report; they do not approve.** `issue-flags` also answers the seven categories from the sdlc chapter `docs/process/operator-escalations.md`. They have no pattern floor, nothing in this repository reads them, and no code grants or withholds an approval on them. They exist so a human sees the category named.

---

## 6. Which transport runs

The official `typesafe-sdk` package where it can be imported; a dependency-free `urllib` transport everywhere else, which is what lets a hook or a script run outside this project's environment. `INFIQUETRA_TYPESAFE_TRANSPORT` forces one or the other. An unrecognized value, or a request for the SDK where it is not installed, fails loudly — the two transports differ in how the key is handled, so a silent substitution would be a behavior change nobody could see.

The package is pinned to a single minor version with a guard test, because it is pre-1.0 and shipped breaking changes in two consecutive releases four days apart. When the guard reds, read the vendor changelog before widening the range.
