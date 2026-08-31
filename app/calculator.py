"""
app/calculator.py

A small, deliberately incomplete calculator module — Phase 2's seed repo.
Missing a `power` operation on purpose: this is what a future feature
request ("add exponentiation support") can plausibly target, giving PM/
Architect/Engineer/QA/Reviewer/DevOps a real, small, well-scoped change
to make against an existing codebase instead of writing from scratch.
"""

from __future__ import annotations

from app.validators import require_numbers


def add(a: float, b: float) -> float:
    require_numbers(a, b)
    return a + b


def subtract(a: float, b: float) -> float:
    require_numbers(a, b)
    return a - b


def multiply(a: float, b: float) -> float:
    require_numbers(a, b)
    return a * b


def divide(a: float, b: float) -> float:
    require_numbers(a, b)
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
