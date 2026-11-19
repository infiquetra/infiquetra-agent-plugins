# <title>

## Summary

<1-3 sentences: what will be true when this work is done.>

## Non-Goals

- <what this work will not do>

## Key Decisions

- **<choice>:** <one-line rationale, including the tradeoff>

## Units

### 1. <name>

- **Files:** `path/to/existing.py`, `path/to/added.py` (new)
- **Tests:** <input, action, and expected outcome, written so the test fails until the unit lands>
- **Verify:** `<command>`
- **Boundaries:** empty or malformed input, partial failure, and idempotency or rollback — say which apply and what should happen

A file marked `(new)` must sit under a directory that already exists, or under a parent also marked `(new)`:

- **Files:** `new-package/` (new), `new-package/README.md` (new)

## Verification

```bash
<commands that prove the units>
```
