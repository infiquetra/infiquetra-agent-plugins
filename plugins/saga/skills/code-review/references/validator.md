# Validator

The independent per-finding validator. After Stage A merges and confidence-gates findings, a **fresh**
agent re-checks each survivor with no commitment to the original lens's analysis. This is a second
opinion, not a critique — false positives are common, and a review that cries wolf is worse than none.
The validator is the operational form of the verify-don't-guess principle.

## The three questions

For each finding, the validator answers:

1. **Is the issue real in the code as written?** Read the cited file and surrounding code. If the code
   does not actually have the described problem, the finding is invalid. Common false-positive shapes:
   - the lens missed an existing guard / null check / validation that handles the case
   - the lens misread a type or signature
   - the lens flagged a pattern that is intentional in this codebase (check comments, parallel handlers,
     project conventions)
2. **Is the issue introduced by THIS diff?** Use `git blame` or diff inspection. If the cited line
   predates this branch's commits and the diff does not interact with it (does not call into it, does not
   change its callers in a way that newly exposes the issue), the finding is **pre-existing** — not
   validated for externalization, regardless of whether it is a real issue.
3. **Is the issue not handled elsewhere?** Look for guards in callers, middleware in the request chain,
   framework defaults, type-system constraints, or parallel handlers that already address the concern. If
   the issue is functionally prevented by surrounding infrastructure, the finding is invalid.

## Mode-based right-sizing

The validator pass runs differently per mode (this matches CE's actual Stage-5b mechanism — it is
**not** a per-severity carve-out):

- **Programmatic / report-only mode:** spawn one validator per Stage-A survivor, **capped at 15**. When
  the survivor set exceeds 15, validate the highest-severity 15 (P0 first, then P1, P2, P3, breaking ties
  by confidence anchor descending); drop the remainder and record the over-budget count in the Coverage
  section. A review producing 15+ survivors is already past the point where a second wave would change the
  triage approach.
- **Interactive mode:** **skip the pre-dispatch validator pass** — the operator is the per-finding
  validator. The operator's routing decisions (fix / defer / reject) are the validation, and any fixer the
  operator dispatches naturally re-checks each finding while applying it.

The upstream suppress-<75 gate plus this 15-cap are the cost control. Do not add a severity-based
exemption — that would be a no-op after the suppress gate has already removed low-confidence findings.

## Conservative bias

When in doubt, **reject**. A validator failure (cannot read the file, agent error, ambiguous result) ->
**drop the finding**. It is better to drop a borderline real finding than to externalize a false positive
that erodes trust in the review. The validator does not invent new findings; anything else it notices is
surfaced as a no-vote with a reason, not a new entry.

## Read-only constraint

The validator is **operationally read-only**. It does NOT edit, commit, push, or modify any file. It uses
Read, Grep, Glob, and `git blame` to inspect the cited code, its callers, guards, and framework defaults.
If it cannot access the cited file, it returns a no-vote rather than guessing.

## Return contract

The validator returns ONLY this JSON, no prose:

```json
{
  "validated": true,
  "reason": "<one sentence explaining the verdict>"
}
```

Examples:

- `{ "validated": true, "reason": "Cited line is new in this diff and lacks the ownership guard parallel handlers use." }`
- `{ "validated": false, "reason": "Line 87 already guards user.email with a present? check; the null deref cannot occur." }`
- `{ "validated": false, "reason": "Cited line predates this branch; the diff does not modify or interact with it." }`
- `{ "validated": false, "reason": "Framework handles the timeout via the client default; no application-level retry needed." }`
- `{ "validated": false, "reason": "Could not access the cited file path to verify." }`

Findings the validator confirms flow through to the report unchanged. Findings it rejects are dropped.
