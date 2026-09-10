"""
sandbox/result.py

ExecutionResult and SANDBOX_IMAGE, kept separate from executor.py (which
imports the `docker` package at module level) so local_executor.py and
repo_local.py — neither of which touches Docker — don't need the
`docker` pip package installed just to import a dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass

SANDBOX_IMAGE = "praxis-sandbox-runner"


@dataclass
class ExecutionResult:
    """Ground-truth outcome of running a task's code against its tests."""

    task_id: str
    exit_code: int | None
    stdout: str
    stderr: str
    wall_time_seconds: float
    tests_collected: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    timed_out: bool = False
    container_error: str | None = None

    @property
    def pass_fraction(self) -> float:
        """
        The core outcome signal fed into calibration fusion.
        1.0 = fully correct, 0.0 = fully wrong or crashed, in between = partial credit.
        """
        if self.timed_out or self.container_error:
            return 0.0
        if self.tests_collected == 0:
            # Nothing to grade against — treat as a hard failure rather than
            # silently scoring 0/0 as success.
            return 0.0
        return self.tests_passed / self.tests_collected

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.container_error