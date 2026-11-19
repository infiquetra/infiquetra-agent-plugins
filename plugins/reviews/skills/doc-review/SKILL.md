---
name: doc-review
description: Review a plan, spec, issue, or other SDLC document for implementation readiness. Use when someone asks to review a plan, review a spec, review an issue, or check whether a document is ready to implement. Suggest code-review for a diff or pull request, security-review for a repository security audit, and review-setup when review tools are missing.
---

# Doc Review

Ask whether this document can drive implementation without invented decisions.

## Rubrics

Classify the document, then run the matching phase rubrics. Phases are `idea`, `spec`, and `issue`.

```bash
python3 plugins/reviews/scripts/lifecycle_review.py rubrics list-cores --phase <idea|spec|issue> --json
python3 plugins/reviews/scripts/lifecycle_review.py rubrics list-extras --phase <idea|spec|issue> --json
python3 plugins/reviews/scripts/lifecycle_review.py rubrics read --phase <phase> --slug <slug>
```

Apply every core rubric. Apply an extra rubric when its applicability matches the document. This pass does not write a lifecycle record and does not continue into implementation.

## Readiness

After the rubrics, do one readiness pass: name missing decisions, contradictions, and untested acceptance criteria. Stop there.

When the target is `docs/plans/*.md` and `plugins/plan` is present, run that package's `check_plan.py` and include its result. When it is absent, say so and continue the rubric review.

Write `docs/reviews/` only when the operator asked for a durable review note or the document is about to guide implementation. Otherwise report in the session.

Suggest `code-review` for a diff or pull request, `security-review` for a repository security audit, and `review-setup` to survey tool pins.
