# Langfuse: saga's review data, the data rule, and the keys

This is the policy for every post to saga's Langfuse project, "Saga Reviews". The client that enforces it is `plugins/fleet-core/scripts/fleet_commons/langfuse_client.py`. Saga's callers are `plugins/saga/scripts/review_trace.py` (review runs, plan reviews, merge outcomes, the queue) and `plugins/saga/scripts/review_dataset.py` (the corpus dataset and its evaluators). Issue 166 (card C15) added them.

Read this before anything new posts to Langfuse.

---

## 1. The keys

| Variable | Holds |
|---|---|
| `SAGA_LANGFUSE_PUBLIC_KEY` | the project's public key |
| `SAGA_LANGFUSE_SECRET_KEY` | the project's secret key |
| `SAGA_LANGFUSE_HOST` | the server's base address, `https://` once X3 (Langfuse over HTTPS) is in place |

The standard names (`LANGFUSE_PUBLIC_KEY` and the rest) belong to the tracing plugin's project. The client never reads them, so with only those set it sends nothing (`missing-keys`). That keeps review data out of the tracing project.

The operator creates the project and its key pair in the Langfuse web interface and stores the keys with `keychain-env set SAGA_LANGFUSE_PUBLIC_KEY` and `keychain-env set SAGA_LANGFUSE_SECRET_KEY`. The client reads them from the environment when it builds a request and puts them only in the `Authorization: Basic` header. No result, message, queued file or payload carries a key or the host address. `python3 plugins/saga/scripts/review_trace.py probe` checks that the keys answer for "Saga Reviews" and prints only the project name.

## 2. The data rule: what leaves the machine

**Sent, after redaction:** the five review records (findings, measurements, where-to-look items, lens grades, and the review run with its usage), each finding's code excerpt at the reviewed head (its lines plus 5 each side, at most 60), plan-review findings, merge outcomes, the corpus dataset, and evaluator totals.

**Never sent:**

- Raw tool output. It stays in `~/.saga/review-output/` and leaves only as its SHA-256. A stored raw-output entry's local path is dropped.
- A secret-scanner finding's text. A finding on row `security.secret-in-diff` sends its location and no excerpt. Any other excerpt replaces a line a secret finding covers with `[secret line withheld]`.
- Keys, the host address, and local paths. The trace names the repository as `owner/name`, never the directory it was reviewed in.
- Held-out corpus content. A held-out dataset item carries its case ID only, and held-out results post as totals.

**Redaction is on the only path out.** `prepare_payload` first replaces any `sk-lf-` or `pk-lf-` key followed by at least eight key characters with `[REDACTED]`, because TypeSafe's patterns miss both shapes. It then runs TypeSafe's redaction (`references/typesafe.md`, section 1) and stamps the result. `send` refuses an unstamped payload (`unprepared`).

## 3. The visibility rule

A repository's visibility is the `visibility` key of `.saga-profile.json`, which `/saga:setup` records. Saga reads it at the review's base commit, never the head or the working tree, because the change under review is untrusted. A plan review reads it at the merge base of `HEAD` and the default branch. A missing or unknown value counts as private, and the corpus dataset always posts as private.

| Host scheme | Private or unrecorded | Public |
|---|---|---|
| `https` | sent, with the default certificate check | sent, with the default certificate check |
| `http` | refused: `plain-http-private`, naming X3 | sent only when every address the host resolves to is loopback or private; otherwise `plain-http-public-address`, or `address-lookup-failed` when the lookup fails |
| anything else | refused: `bad-scheme` | refused: `bad-scheme` |

The client follows no redirect (`redirect`): a same-host redirect from `https` to `http` would put the key pair in clear.

## 4. Endpoints

The client can reach only these. None deletes or replaces anything, and nothing in saga deletes Langfuse data automatically.

| Kind | Method and path | Used for |
|---|---|---|
| `otel-traces` | `POST /api/public/otel/v1/traces` (JSON, header `x-langfuse-ingestion-version: 4`) | review-run, plan-review and corpus-run traces |
| `scores` | `POST /api/public/scores` | round scores, merge outcomes, plan answers, evaluator totals |
| `datasets` | `POST /api/public/v2/datasets` | the corpus dataset |
| `dataset-items` | `POST /api/public/dataset-items` | one item per corpus case |
| `projects` | `GET /api/public/projects` | `review_trace.py probe` |
| `metrics` | `GET /api/public/v2/metrics` | `review_trace.py rounds` |

Traces use the OpenTelemetry endpoint because Langfuse's published API marks the batch ingestion endpoint deprecated; a server in version-4-only write mode refuses traces there.

## 5. Outcomes and reasons

`send` returns one of `sent`, `refused`, `unreachable`, `timeout` or `rejected`, with a reason:

| Reason | Meaning |
|---|---|
| `missing-keys` | one or both saga key variables are unset |
| `missing-host` | `SAGA_LANGFUSE_HOST` is unset |
| `bad-scheme` | the host is not `https` or `http`, or has no host name |
| `plain-http-private` | a private or unrecorded repository on `http`; see X3 |
| `plain-http-public-address` | a public repository on `http` to a public address |
| `address-lookup-failed` | a public repository on `http` whose host could not be looked up |
| `unprepared` | the payload skipped `prepare_payload` |
| `redirect` | the server answered with a redirect |
| `unreachable` | the host could not be reached |
| `timeout` | the request timed out (10 seconds) |
| `http-<status>` | the server refused the post |
| `malformed-response` | a read returned something other than JSON |

Saga adds `client-error` (the client raised) and `budget` (one post spent its 30 seconds).

## 6. The queue

A post that does not go waits in `~/.saga/langfuse-queue/` (directory 0700, files 0600), one file per post with its reason. Every later post drains the queue oldest first before its own items, stops at the first `unreachable` or `timeout`, and re-checks every other reason against the keys and host current then. A file is removed only after Langfuse accepted it; nothing is dropped, including a 4xx refusal. `review_trace.py status` and `/saga:setup`'s survey show how many posts wait and why; `review_trace.py drain` sends them.

## 7. What a review run looks like

One trace per review run. Its ID is 32 hex characters of SHA-256 over the repository slug, base and head commits, card and round; each entry's ID is 16 hex characters of SHA-256 over the trace ID and the entry's key. A later post (an outcome, a resend) recomputes them and needs no lookup.

| Entry | Key | Carries |
|---|---|---|
| `review-run` (root) | `review-run` | slug, base, head, card, round, saga and tool versions, visibility, usage; lens grades and the merge decision |
| `tool:<name>` | `tool:<name>` | version, finding IDs, degraded reasons, raw-output fingerprints |
| `jev-sweep` | `sweep` | the where-to-look items, and each verdict's resolved model version |
| `llm:<role>` | `llm:<index>:<role>` | vendor, model, configuration fingerprint, prompt SHA-256, tokens, cost and time |
| `formula` | `formula` | measurements, may-block, builder records, lens grades, degraded inputs, merge |
| `finding` | `finding:<finding identity>` | the finding record and its excerpt |

OpenTelemetry attributes used: `langfuse.trace.name`, `langfuse.trace.metadata.*`, `langfuse.trace.output`, `langfuse.observation.type`, `langfuse.observation.input`, `langfuse.observation.output`, `langfuse.observation.metadata.*`, `langfuse.observation.model.name`, `langfuse.observation.usage_details`, `langfuse.observation.cost_details`, `langfuse.version`.

## 8. Scores

| Name | Type | On | When |
|---|---|---|---|
| `round` | NUMERIC | trace | every review run |
| `round-2-found-new`, `round-3-found-new` | BOOLEAN | trace | round 2 or 3: 1 when it holds a finding no earlier round of the card had |
| `round-new-findings`, `round-new-blocking`, `round-cleared` | NUMERIC | trace | round 2 and later, when a run record exists |
| `merge-outcome` | CATEGORICAL | finding entry | at merge: `fixed`, `dismissed` (comment: the reason), `fixed-now`, `filed` (comment `issue #<n>`, metadata `issue`), or `left` |
| `plan-answer` | CATEGORICAL | plan finding entry | `fixed` (comment: the section) or `rejected` (comment: the reason) |
| `<split>.<lens>.hit-rate`, `<split>.<lens>.false-block-rate` | NUMERIC | corpus-run trace | a harness run |
| `<split>.question.<id>.precision` | NUMERIC | corpus-run trace | a harness run |
| `<split>.grade-stability`, `<split>.cost-usd-per-review`, `<split>.seconds-per-review` | NUMERIC | corpus-run trace | a harness run |

A merge outcome attaches to the finding's entry in the latest stored review run that holds that finding identity. The identity ignores line numbers, so the outcome finds its entry after lines move. Score IDs are derived too, so a second post replaces the score instead of adding one.

## 9. The rounds view

The dashboard "Review rounds" has two widgets over the `scores-boolean` view: the average value of `round-2-found-new` and of `round-3-found-new`. Each is the share of round-2 (or round-3) runs that found anything new. The operator adds the dashboard in the web interface; Langfuse's dashboard API is marked unstable, so nothing here creates it. `python3 plugins/saga/scripts/review_trace.py rounds` reads the same numbers through the metrics API.

## 10. The corpus dataset and the evaluators

The dataset is `saga-review-corpus`. `review_dataset.py sync --corpus <dir>` posts one item per `<case>/case.json`; each case needs `case_id` and `split` (`tuning` or `held-out`). Item IDs derive from the case ID. A tuning item's input is its `case.json` record, redacted; patches and code are never read. A held-out item's input is `{"case_id": ...}`.

`review_dataset.py score --results <file> --run-id <id>` reads a harness result file, a JSON list of cases (or `{"cases": [...]}`), each:

| Field | Meaning |
|---|---|
| `case_id`, `split`, `lens`, `language` | the case |
| `expected` | `defect` or `clean` |
| `blocked` | whether the review blocked it |
| `repeat_blocked` | for a repeated case, whether the second run blocked it |
| `grades` | the lens grades, kept for K3 |
| `question_hits` | each `{question, correct}` the review raised |
| `cost_usd`, `seconds` | that review's cost and time |

The evaluators are plain code: per-lens hits (blocked defects over defects), false blocks (blocked clean cases over clean cases), per-question precision (correct hits over hits), grade stability (repeated cases with the same blocking decision), and cost and time per review. Values are rounded to 4 places. `--dry-run` prints them and sends nothing. LLM-based evaluators wait until they are checked against hand labels.
