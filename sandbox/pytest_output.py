"""
sandbox/pytest_output.py

Shared by executor.py, local_executor.py, repo_executor.py, and
repo_local.py — all need to turn raw pytest stdout into
(collected, passed, failed) counts. Also now home to
check_pytest_available(), a preflight check added after a real incident:
a fresh clone with no dependencies installed produced a fully-formed,
plausible-looking PHASE 0 RESULT (real Brier numbers, "three_way_wins":
true) built entirely on pytest silently failing to launch (WinError 2 on
Windows) — every outcome/ground_truth score was a false 0.0 masquerading
as "the code was wrong," not "the harness never ran." The system should
never be able to report a confident calibration result built on zero
real test executions. This check makes that failure loud and immediate
instead of silent and indistinguishable from a real result.
"""

from __future__ import annotations

import re
import subprocess

# pytest's short summary line looks like: "2 passed, 1 failed in 0.03s"
_PYTEST_SUMMARY_RE = re.compile(
    r"(?:(?P<passed>\d+) passed)?"
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


def check_pytest_available() -> None:
    """
    Fail loudly, immediately, and before any task runs, if pytest isn't
    actually invokable — rather than letting a FileNotFoundError-class
    error get silently caught by an executor's broad except-Exception
    handler and converted into a container_error that reads like just
    another execution detail buried in a 13-task run.

    Called once at executor construction time, so a missing dependency
    is caught before wasting any LLM API calls on a run that was always
    going to produce garbage data.
    """
    try:
        result = subprocess.run(
            ["pytest", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "pytest not found on PATH. PRAXIS_SANDBOX=local requires pytest "
            "installed in this environment. Run: "
            "pip install -r orchestrator/requirements.txt"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — any other launch failure is equally disqualifying
        raise RuntimeError(f"Could not run pytest to verify it's available: {exc}") from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"pytest was found but failed to run (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )