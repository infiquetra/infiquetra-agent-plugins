"""Lint fixture (#371): the same gate call site WITH a declared absence_behavior — must PASS.

Byte-for-byte the ``gate_missing_absence.py`` site plus ``absence_behavior="HALT"``, so the pair
is a minimal red/green control for the lint's Python analyzer.
"""

from gate_record import open_gate

open_gate(
    ".saga/gates",
    "fixture-gate-with",
    "Proceed with the demo migration?",
    ["proceed", "hold"],
    absence_behavior="HALT",
)
