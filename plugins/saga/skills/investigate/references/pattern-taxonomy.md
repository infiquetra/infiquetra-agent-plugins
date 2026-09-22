# Pattern taxonomy + anti-patterns

Check the symptom against a known signature **before** deep tracing — pattern-matching is cheap, and the
class implies where to look first. The 6 base signatures are GRAFTED from gstack `investigate`; the
serverless row is an infiquetra ADDITION (it does not replace the 6). The anti-patterns catalog is from
CE `ce-debug`.

---

## Bug signatures (gstack's 6) — symptom → suspect

| Signature | Symptom | First suspect |
|---|---|---|
| **Race condition** | Intermittent, timing-dependent, passes alone / fails under load | Concurrent access to shared state; async ordering; unsynchronized reads-then-writes |
| **Null / nil propagation** | `NoneType`/`NoMethodError`/`TypeError`, "X of undefined" | Missing guard on an optional value; a function that returns `None` on a path the caller assumes can't happen |
| **State corruption** | Inconsistent data, partial updates, wrong values that "shouldn't be possible" | Transactions, callbacks/hooks, shared mutable state mutated out of order |
| **Integration failure** | Timeout, unexpected response, 4xx/5xx from a dependency | External API / service-boundary call; contract drift; auth/headers; retry/backoff |
| **Config drift** | Works locally, fails in staging/prod (or vice versa) | Env vars, feature flags, DB state, version/dependency drift between environments |
| **Stale cache** | Shows old data; fixes on cache clear / restart | Redis, CDN, HTTP cache, app-level memoization, browser service worker |

---

## Infiquetra serverless ADDITION — symptom → suspect

These extend (do not replace) the 6 for AWS serverless repos:

| Signature | Symptom | First suspect |
|---|---|---|
| **Cold-start** | First invocation slow/timeout/init error; warm calls fine | Heavy module-level init, VPC ENI attach, connection setup in the handler init path; `init` vs handler timing |
| **IAM permission** | `AccessDenied` / `not authorized to perform`; works for one role/env not another | Lambda execution role policy, resource policy, cross-account/cross-service trust, missing `Resource`/`Action` |
| **Eventual-consistency (DynamoDB)** | Read right after a write returns stale/missing item; flaky on fast paths | A strongly-consistent read assumed but a GSI or eventually-consistent read used; read-after-write on a GSI (always eventual) |
| **Throttling** | `ProvisionedThroughputExceeded` / `TooManyRequests` / `Rate exceeded`; bursty failures | DynamoDB/Lambda/API Gateway throttle limits, hot partition key, concurrency cap, missing backoff |
| **Env / SSM drift** | Works in one stage, fails in another; "config not found" / wrong value | Lambda env var vs SSM Parameter Store / Secrets Manager value drift between stages; stale deployed config |

When the symptom matches none of these, sanitize the error (strip hostnames, IPs, paths, SQL, customer
data) and search the error **category**, not the raw message. Also run the cheap bug-class pass: time/
timezone, encoding/locale, floating-point, integer overflow, off-by-one, permissions/auth, path/case
sensitivity, TOCTOU, observer-effect (heisenbug), stale build artifacts.

---

## Anti-patterns catalog (CE `ce-debug`)

These feel productive in the moment — that is what makes them dangerous. Read before forming hypotheses.

### Shotgun debugging

Changing multiple things at once to "see if it helps." If the bug goes away you don't know which change
fixed it; if it persists you don't know which are relevant. **Fix:** one hypothesis, one change, one test;
revert a failed change before the next.

### Confirmation bias

Interpreting ambiguous evidence as supporting your current hypothesis — a log line that *could* fit, a
test passing without checking it exercised the failure path, an error changing slightly read as "getting
closer." **Defense:** before declaring a hypothesis confirmed, ask "what evidence would DISPROVE this?"
If you can't name it, you're justifying, not testing.

### "It works now, move on"

The bug stops appearing after a change and you declare victory. **Trap:** if you can't explain WHY the
change fixed it — the full causal chain — you may have fixed a symptom, masked the bug, or gotten lucky
with timing. **Test:** can you explain the fix without "somehow" or "I think"? If not, the root cause is
not confirmed.

### Prediction quality — bad vs good

The prediction tests whether your understanding is correct, not just whether the error disappears.

- **Bad (restates the hypothesis):** *Hypothesis:* the null is because `user` isn't initialized.
  *Prediction:* `user` will be null when I log it. — Cannot be wrong if the hypothesis is right, so it
  cannot catch a wrong hypothesis.
- **Good (tests something non-obvious):** *Hypothesis:* the null is because auth middleware skips init on
  cached requests. *Prediction:* non-cached requests to the same endpoint will NOT produce the null, and
  the `X-Cache` header is present on failing ones. — Tests a different path and a different observable.

**Rule of thumb:** a good prediction names something you have **not looked at yet**.

### Rationalization-spiral red flags

If the internal monologue contains any of these, STOP and return to root-cause investigation:

- "Quick fix for now, investigate later" — there is no "for now."
- "This should work" / "it's probably X" — certainty without a tested prediction or without reading the
  code.
- "Let me just try…" — "just" signals a minimized scope; small problems don't resist 2-3 attempts.
- "One more fix attempt" (after 2+ failures) — guessing with increasing frustration, not iterating.
- "Works on my machine" — the environment difference IS the investigation; compare systematically.
- Proposing a fix before stating the root cause — explain the cause first.
