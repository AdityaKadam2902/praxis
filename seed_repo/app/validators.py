"""
app/validators.py

Shared input validation for app/calculator.py. Kept in its own module
rather than inlined, so a Phase 2 feature request can plausibly target
this file too (e.g. "reject NaN/infinity inputs") without every task
being about calculator.py specifically.
"""

from __future__ import annotations


def require_numbers(*args) -> None:
    for value in args:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"Expected a number, got {type(value).__name__}: {value!r}")
