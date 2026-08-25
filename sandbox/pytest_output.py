"""
sandbox/pytest_output.py

Shared by executor.py (Docker) and local_executor.py (no isolation) — both
need to turn raw pytest stdout into (collected, passed, failed) counts.
This used to live as a "private" (underscore-prefixed) function inside
executor.py, which was fine when only that file used it, but became
incorrect the moment local_executor.py needed the same logic — a private
symbol shouldn't be imported across module boundaries. Promoting it here
is the actual fix, not just silencing the linter warning.
"""

from __future__ import annotations

import re

# pytest's short summary line looks like: "2 passed, 1 failed in 0.03s"
# The .*? prefix on every group is required — without it, re.search()
# matches a zero-width "success" at position 0 (since every group here is
# optional) instead of scanning forward to find the actual summary line,
# which appears after pytest's dot-per-test progress output. This is what
# caused every real pass/fail result to be silently read as 0 collected.
_PYTEST_SUMMARY_RE = re.compile(
    r"(?:.*?(?P<passed>\d+) passed)?"
    r"(?:.*?(?P<failed>\d+) failed)?"
    r"(?:.*?(?P<errors>\d+) error)?",
    re.DOTALL,
)


def parse_pytest_output(stdout: str) -> tuple[int, int, int]:
    """
    Extract (collected, passed, failed) from raw pytest stdout.
    Deliberately simple regex parsing for Phase 0 — swap for
    `pytest --json-report` in Phase 1+ once the harness stabilizes.
    """
    match = _PYTEST_SUMMARY_RE.search(stdout)
    passed = int(match.group("passed") or 0) if match else 0
    failed = int(match.group("failed") or 0) if match else 0
    errors = int(match.group("errors") or 0) if match else 0
    collected = passed + failed + errors
    return collected, passed, failed + errors