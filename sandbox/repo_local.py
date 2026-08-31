"""
sandbox/repo_local.py

Repo-level grounding, no-Docker variant — mirrors local_executor.py's
pattern, but operates on an already-prepared repo directory (files
already written via git_ops.write_files, already committed on a branch)
instead of a single solution+test string pair. This is what closes
Phase 2 gap #1 from the build spec: QA needs to run a seed repo's own
test suite after a multi-file change, not just one function against one
test file.

Same isolation caveat as local_executor.py: runs directly on the host,
no network block, no resource caps. Fine for a seed repo you wrote
yourself; switch to repo_executor.py (Docker) before running anything
containing code you haven't reviewed.
"""

from __future__ import annotations

import subprocess
import time

from sandbox.result import ExecutionResult
from sandbox.pytest_output import parse_pytest_output

DEFAULT_TIMEOUT_SECONDS = 60  # repo-level suites take longer than a single function's tests


def _coerce_text(value: bytes | str | None) -> str:
    """Same reasoning as local_executor.py's helper of the same name —
    subprocess.TimeoutExpired.stdout/.stderr are typed generically, this
    handles both bytes and str explicitly rather than assuming text=True
    always held."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class RepoLocalExecutor:
    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        task_id: str,
        repo_dir: str,
        test_command: list[str] | None = None,
    ) -> ExecutionResult:
        """
        Run `test_command` (default ["pytest", "-q"]) inside repo_dir,
        which is expected to already have Engineer's changes written and
        committed before this is called. Returns the same ExecutionResult
        shape Phase 0 used for single-function tasks — calibration code
        downstream doesn't need to know whether it's grounding one
        function or a whole repo.
        """
        command = test_command or ["pytest", "-q"]
        start = time.monotonic()

        try:
            try:
                proc = subprocess.run(
                    command,
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                )
                timed_out = False
                exit_code = proc.returncode
                stdout = proc.stdout + proc.stderr
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                exit_code = None
                stdout = _coerce_text(exc.stdout) + _coerce_text(exc.stderr)

            collected, passed, failed = parse_pytest_output(stdout)

            return ExecutionResult(
                task_id=task_id,
                exit_code=exit_code,
                stdout=stdout,
                stderr="",
                wall_time_seconds=time.monotonic() - start,
                tests_collected=collected,
                tests_passed=passed,
                tests_failed=failed,
                timed_out=timed_out,
            )

        except Exception as exc:  # noqa: BLE001 — mirror local_executor.py's fail-safe behavior
            return ExecutionResult(
                task_id=task_id,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                wall_time_seconds=time.monotonic() - start,
                container_error=str(exc),
            )