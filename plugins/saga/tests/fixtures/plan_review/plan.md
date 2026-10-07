# Fixture plan

## Implementation Units

### U1. The only unit

**Goal:** Ship the widget.

```functional-checks
- name: widget-check
  command: python3 -m pytest -q
  proves: [AC-1]
  runs: local
```

## Scenario Smoke

```scenario-smoke
- name: widget-smoke
  command: python3 -m pytest -q
  proves: [AC-1]
  runs: environment
```
