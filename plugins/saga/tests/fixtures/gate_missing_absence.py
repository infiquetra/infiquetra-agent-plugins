"""Lint fixture (#371): a gate call site that declares NO absence_behavior — must FAIL the lint.

Never executed (pytest does not collect it; the lint parses its AST only). The import mirrors a
real consumer so the fixture is a faithful gate call site, not a toy string.
"""

from gate_record import open_gate

open_gate(
    ".saga/gates",
    "fixture-gate-missing",
    "Proceed with the demo migration?",
    ["proceed", "hold"],
)
